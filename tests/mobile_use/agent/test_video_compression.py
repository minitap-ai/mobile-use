"""Fix round 5: oversized recordings are compressed to fit or rejected explicitly (class M7)."""

import asyncio
import shutil
import subprocess

import pytest

from minitap.mobile_use.utils import video

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_video(path, seconds=4):
    subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=1280x720:rate=30:duration={seconds}",
            "-c:v",
            "libx264",
            "-b:v",
            "8M",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def test_compressed_video_fits_the_limit(tmp_path):
    src = _make_video(tmp_path / "a.mp4")
    limit = src.stat().st_size // 4
    out = asyncio.run(video.compress_video_for_api(src, target_size_bytes=limit))
    assert out != src and out.stat().st_size <= limit


def test_impossible_limit_raises_instead_of_returning_the_original(tmp_path):
    src = _make_video(tmp_path / "b.mp4")
    with pytest.raises(video.VideoTooLargeError, match="shorter video"):
        asyncio.run(video.compress_video_for_api(src, target_size_bytes=2_000))


def test_small_video_is_returned_unchanged(tmp_path):
    src = _make_video(tmp_path / "c.mp4", seconds=1)
    assert asyncio.run(video.compress_video_for_api(src, target_size_bytes=10**9)) == src
