"""
Video recording utilities for mobile devices.

Provides shared types and utilities for video recording across platforms.
"""

import asyncio
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from minitap.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_DURATION_SECONDS = 900  # 15 minutes
VIDEO_READY_DELAY_SECONDS = 1
ANDROID_DEVICE_VIDEO_PATH = "/sdcard/screen_recording.mp4"
ANDROID_MAX_RECORDING_DURATION_SECONDS = 180  # Android screenrecord limit


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


async def concatenate_videos(segments: list[Path], output_path: Path) -> bool:
    """Concatenate multiple video segments using ffmpeg."""
    if not segments:
        return False

    if len(segments) == 1:
        segments[0].rename(output_path)
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
        list_file.unlink()
        return output_path.exists()
    except Exception as e:
        logger.error(f"Failed to concatenate videos: {e}")
        return False


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
