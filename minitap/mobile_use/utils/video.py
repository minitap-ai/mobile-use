"""
Video recording utilities for mobile devices.

Provides shared types and utilities for video recording across platforms.
"""

import asyncio
import platform
import shutil
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_DURATION_SECONDS = 900  # 15 minutes
VIDEO_READY_DELAY_SECONDS = 1
ANDROID_DEVICE_VIDEO_PATH = "/sdcard/screen_recording.mp4"
ANDROID_MAX_RECORDING_DURATION_SECONDS = 180  # Android screenrecord limit

# Gemini API limits: 20MB for inline requests, but base64 adds ~33% overhead
# So we target ~14MB to be safe after base64 encoding
MAX_VIDEO_SIZE_MB = 14
MAX_VIDEO_SIZE_BYTES = MAX_VIDEO_SIZE_MB * 1024 * 1024


class RecordingSession(BaseModel):
    """Tracks an active video recording session."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    device_id: str
    start_time: float
    process: asyncio.subprocess.Process | None = None
    local_video_path: Path | None = None
    android_device_path: str = ANDROID_DEVICE_VIDEO_PATH
    android_video_segments: list[Path] = []
    android_segment_index: int = 0
    android_restart_task: asyncio.Task | None = None
    errors: list[str] = []


class VideoRecordingResult(BaseModel):
    """Result of a video recording operation."""

    success: bool
    message: str
    video_path: Path | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


# Global session storage - keyed by device_id
_active_recordings: dict[str, RecordingSession] = {}


def get_active_session(device_id: str) -> RecordingSession | None:
    """Get the active recording session for a device."""
    return _active_recordings.get(device_id)


def set_active_session(device_id: str, session: RecordingSession) -> None:
    """Set the active recording session for a device."""
    _active_recordings[device_id] = session


def remove_active_session(device_id: str) -> RecordingSession | None:
    """Remove and return the active recording session for a device."""
    return _active_recordings.pop(device_id, None)


def has_active_session(device_id: str) -> bool:
    """Check if there's an active recording session for a device."""
    return device_id in _active_recordings


def is_ffmpeg_installed() -> bool:
    """Check if ffmpeg is available in the system PATH."""
    return shutil.which("ffmpeg") is not None


class FFmpegNotInstalledError(Exception):
    """Raised when ffmpeg is required but not installed."""

    def __init__(self):
        os_name = platform.system().lower()
        if os_name == "darwin":  # macOS
            install_instructions = "brew install ffmpeg"
        elif os_name == "windows":
            install_instructions = "Download from https://www.ffmpeg.org/download.html"
        else:  # Linux and others
            install_instructions = (
                "Install via your package manager (e.g., apt install ffmpeg, "
                "dnf install ffmpeg) or download from https://www.ffmpeg.org/download.html"
            )

        message = (
            f"\n\n❌ ffmpeg is required for video recording but is not installed.\n\n"
            f"Please install ffmpeg first:\n"
            f"  → {install_instructions}\n\n"
            f"After installation, restart mobile-use.\n"
        )
        super().__init__(message)


def check_ffmpeg_available() -> None:
    """
    Check if ffmpeg is installed and raise an error if not.

    Raises:
        FFmpegNotInstalledError: If ffmpeg is not found in PATH.
    """
    if not is_ffmpeg_installed():
        raise FFmpegNotInstalledError()


async def concatenate_videos(segments: list[Path], output_path: Path) -> bool:
    """Concatenate multiple video segments using ffmpeg."""
    if not segments:
        return False

    if len(segments) == 1:
        shutil.move(segments[0], output_path)
        return True

    list_file = output_path.parent / "segments.txt"
    with open(list_file, "w") as f:
        for segment in segments:
            f.write(f"file '{segment}'\n")

    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.wait()
        return output_path.exists()
    except Exception as e:
        logger.error(f"Failed to concatenate videos: {e}")
        return False
    finally:
        if list_file.exists():
            list_file.unlink()


def cleanup_video_segments(segments: list[Path], keep_path: Path | None = None) -> None:
    """Clean up temporary video segments, optionally keeping one path."""
    for segment in segments:
        try:
            if segment.exists() and segment != keep_path:
                segment.unlink()
                if segment.parent.exists() and not any(segment.parent.iterdir()):
                    segment.parent.rmdir()
        except Exception:
            pass


async def compress_video_for_api(
    input_path: Path,
    target_size_bytes: int = MAX_VIDEO_SIZE_BYTES,
) -> Path:
    """
    Compress a video to fit within API size limits using ffmpeg.

    Uses a two-pass approach:
    1. First check if video is already small enough
    2. If not, compress with reduced resolution and bitrate

    Args:
        input_path: Path to the input video file
        target_size_bytes: Target maximum file size in bytes

    Returns:
        Path to the compressed video (may be same as input if no compression needed)
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Video file not found: {input_path}")

    current_size = input_path.stat().st_size
    logger.info(f"Video size: {current_size / 1024 / 1024:.2f} MB")

    if current_size <= target_size_bytes:
        logger.info("Video already within size limit, no compression needed")
        return input_path

    logger.info(f"Compressing video to fit within {target_size_bytes / 1024 / 1024:.1f} MB")

    output_path = input_path.parent / f"compressed_{input_path.name}"

    # Get video duration using ffprobe
    duration_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(input_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *duration_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        duration = float(stdout.decode().strip())
    except Exception:
        duration = 120.0  # Default estimate if probe fails

    # Calculate target bitrate (bits per second)
    # Leave some margin for container overhead
    target_bitrate = int((target_size_bytes * 8 * 0.9) / duration)
    # Ensure minimum quality
    target_bitrate = max(target_bitrate, 100_000)  # At least 100kbps

    logger.info(f"Target bitrate: {target_bitrate / 1000:.0f} kbps for {duration:.1f}s video")

    # Compress with ffmpeg: reduce resolution to 720p max, use target bitrate
    compress_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "scale='min(720,iw)':'-2'",  # Max 720p width, maintain aspect
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-b:v",
        str(target_bitrate),
        "-maxrate",
        str(int(target_bitrate * 1.5)),
        "-bufsize",
        str(int(target_bitrate * 2)),
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        str(output_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *compress_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"ffmpeg compression failed: {stderr.decode()}")
            return input_path  # Return original if compression fails

        new_size = output_path.stat().st_size
        logger.info(
            f"Compressed: {current_size / 1024 / 1024:.2f} MB -> "
            f"{new_size / 1024 / 1024:.2f} MB"
        )

        return output_path

    except Exception as e:
        logger.error(f"Video compression failed: {e}")
        return input_path  # Return original if compression fails
