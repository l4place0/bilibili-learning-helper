"""Resolve executables bundled with a standalone release or supplied by the OS."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def ffmpeg_executable() -> str:
    """Return the configured, bundled, or system FFmpeg executable."""
    configured = os.getenv("VIDEO_SUM_FFMPEG", "").strip()
    if configured:
        return str(Path(configured).expanduser())

    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return bundled
    except (ImportError, RuntimeError):
        pass

    return shutil.which("ffmpeg") or ""


def ffprobe_executable() -> str:
    """Return an optional system ffprobe executable."""
    configured = os.getenv("VIDEO_SUM_FFPROBE", "").strip()
    if configured:
        return str(Path(configured).expanduser())
    return shutil.which("ffprobe") or ""
