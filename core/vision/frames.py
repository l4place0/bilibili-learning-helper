import logging
import re
import subprocess
import tempfile
from pathlib import Path

from core.config import settings
from core.platforms.base import BasePlatform

logger = logging.getLogger(__name__)


def _get_video_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe failed for %s: %s", video_path.name, e)
        return 0


def _detect_scene_changes(video_path: Path, threshold: float = 0.3) -> list[tuple[float, float]]:
    """Detect scene changes globally using ffmpeg, returns list of (timestamp, score)."""
    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-vsync", "vfr", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        logger.warning("Scene detection timed out for %s", video_path.name)
        return []

    scenes = []
    for match in re.finditer(r"pts_time:(\d+\.?\d*)\s.*scene:(\d+\.?\d*)", stderr):
        ts = float(match.group(1))
        score = float(match.group(2))
        scenes.append((ts, score))

    logger.info("Detected %d scene changes in %s", len(scenes), video_path.name)
    return scenes


def _assign_scenes_to_segments(
    scenes: list[tuple[float, float]],
    duration: float,
    num_segments: int,
    max_per_seg: int,
    min_gap: float,
    baseline_timestamps: list[float],
) -> list[float]:
    """Assign scene frames to segments, dedup against baselines and each other."""
    if duration <= 0 or num_segments <= 0:
        return []

    seg_len = duration / num_segments
    result = []

    for seg_idx in range(num_segments):
        seg_start = seg_idx * seg_len
        seg_end = (seg_idx + 1) * seg_len
        baseline = baseline_timestamps[seg_idx] if seg_idx < len(baseline_timestamps) else seg_start + seg_len / 2

        # Find scenes in this segment
        seg_scenes = [(ts, score) for ts, score in scenes if seg_start <= ts < seg_end]
        seg_scenes.sort(key=lambda x: x[1], reverse=True)

        chosen = []
        for ts, _score in seg_scenes:
            if len(chosen) >= max_per_seg:
                break
            # Dedup: must be >= min_gap from baseline
            if abs(ts - baseline) < min_gap:
                continue
            # Dedup: must be >= min_gap from other chosen scenes in this segment
            if any(abs(ts - c) < min_gap for c in chosen):
                continue
            chosen.append(ts)

        result.extend(chosen)

    result.sort()
    logger.info("Assigned %d scene frames across %d segments", len(result), num_segments)
    return result


def _encode_frame(video_path: Path, ts: float, out_path: Path, width: int, fmt: str, quality: int) -> bool:
    """Extract a single frame at the given timestamp, scale and encode to target format."""
    vf = f"scale={width}:-2"
    cmd = [
        "ffmpeg", "-ss", f"{ts:.1f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", vf,
        "-y", "-hide_banner", "-loglevel", "error",
    ]
    if fmt == "webp":
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(min(quality // 5, 5))])  # map 85 -> ~2 for JPEG

    cmd.append(str(out_path))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode == 0 and out_path.exists()
    except subprocess.TimeoutExpired:
        logger.warning("Timeout extracting frame at %.1fs", ts)
        return False


def _extract_frames_hybrid(
    video_path: Path,
    output_dir: Path,
    segments: int = 60,
    max_scene_per_seg: int = 2,
    scene_threshold: float = 0.3,
    min_gap: float = 5.0,
    width: int = 1280,
    fmt: str = "webp",
    quality: int = 85,
) -> list[Path]:
    """Hybrid extraction: uniform baseline (segment midpoints) + scene detection."""
    duration = _get_video_duration(video_path)
    if duration <= 0:
        logger.warning("Could not determine duration, falling back to fps filter")
        return _extract_frames_fps(video_path, output_dir, segments, max(1, int(duration / segments)) if duration > 0 else 30, width, fmt, quality)

    seg_len = duration / segments
    ext = "webp" if fmt == "webp" else "jpg"

    # Baseline: midpoint of each segment
    baseline_ts = [seg_idx * seg_len + seg_len / 2 for seg_idx in range(segments)]

    # Scene detection (global single pass)
    scenes = _detect_scene_changes(video_path, scene_threshold)
    scene_ts = _assign_scenes_to_segments(scenes, duration, segments, max_scene_per_seg, min_gap, baseline_ts)

    # Merge and sort all timestamps
    all_ts = sorted(set(baseline_ts + scene_ts))

    logger.info(
        "Hybrid extraction: %d baseline + %d scene = %d total frames from %.0fs video",
        len(baseline_ts), len(scene_ts), len(all_ts), duration,
    )

    # Extract frames
    frames = []
    for i, ts in enumerate(all_ts):
        out_path = output_dir / f"frame_{i+1:04d}.{ext}"
        if _encode_frame(video_path, ts, out_path, width, fmt, quality):
            frames.append(out_path)
        else:
            logger.warning("Failed to extract frame at %.1fs", ts)

    logger.info("Extracted %d/%d frames from %s", len(frames), len(all_ts), video_path.name)
    return frames


def _extract_frames_timestamp(video_path: Path, tmp_dir: Path, max_frames: int, interval: int, width: int = 0, fmt: str = "jpg", quality: int = 2) -> list[Path]:
    """Extract frames by seeking to evenly-spaced timestamps using a single ffmpeg select filter."""
    duration = _get_video_duration(video_path)
    if duration <= 0:
        logger.warning("Could not determine video duration, falling back to fps filter")
        return _extract_frames_fps(video_path, tmp_dir, max_frames, interval, width, fmt, quality)

    step = max(interval, duration / max_frames)
    timestamps = []
    t = step / 2
    while t < duration and len(timestamps) < max_frames:
        timestamps.append(t)
        t += step

    logger.info("Extracting %d frames from %.0fs video (step=%.0fs)", len(timestamps), duration, step)

    ext = "webp" if fmt == "webp" else "jpg"
    effective_width = width or settings.frame_width

    # Build single ffmpeg command with select filter for all timestamps
    select_expr = "+".join(f"eq(t,{ts:.1f})" for ts in timestamps)
    vf = f"select='{select_expr}'"
    if effective_width:
        vf += f",scale={effective_width}:-2"

    out_pattern = str(tmp_dir / f"frame_%04d.{ext}")
    cmd = [
        "ffmpeg", "-ss", "0",
        "-i", str(video_path),
        "-vf", vf,
        "-vsync", "vfr",
        "-frames:v", str(len(timestamps)),
        "-y", "-hide_banner", "-loglevel", "error",
    ]
    if fmt == "webp":
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(min(quality // 5, 5))])

    cmd.append(out_pattern)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.warning("ffmpeg batch extraction failed: %s", result.stderr[-500:] if result.stderr else "")
    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg batch extraction timed out for %s", video_path.name)

    frames = sorted(tmp_dir.glob(f"frame_*.{ext}"))

    # Rename to match expected naming convention
    renamed_frames = []
    for i, fpath in enumerate(frames):
        target = tmp_dir / f"frame_{i+1:04d}.{ext}"
        if fpath != target:
            fpath.rename(target)
        renamed_frames.append(target)

    logger.info("Extracted %d/%d frames from %s", len(renamed_frames), len(timestamps), video_path.name)
    return renamed_frames


def _extract_frames_fps(video_path: Path, tmp_dir: Path, max_frames: int, interval: int, width: int = 0, fmt: str = "jpg", quality: int = 2) -> list[Path]:
    """Fallback: extract frames using fps filter (for unknown duration)."""
    ext = "webp" if fmt == "webp" else "jpg"
    fps_filter = f"fps=1/{interval}"
    vf = fps_filter
    if width:
        vf += f",scale={width}:-2"

    cmd = [
        "ffmpeg", "-i", str(video_path),
        "-vf", vf,
        "-frames:v", str(max_frames),
        "-y", "-hide_banner", "-loglevel", "error",
    ]
    if fmt == "webp":
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(min(quality // 5, 5))])

    cmd.append(str(tmp_dir / f"frame_%04d.{ext}"))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning("ffmpeg frame extraction failed: %s", result.stderr)
        return []
    return sorted(tmp_dir.glob(f"frame_*.{ext}"))


def _extract_frames_scene(video_path: Path, tmp_dir: Path, max_frames: int, threshold: float, width: int = 0, fmt: str = "jpg", quality: int = 3) -> list[Path]:
    """Extract frames at scene change boundaries."""
    ext = "webp" if fmt == "webp" else "jpg"
    vf = f"select='gt(scene,{threshold})'"
    if width:
        vf += f",scale={width}:-2"

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", vf,
        "-vsync", "vfr",
        "-frames:v", str(max_frames),
    ]
    if fmt == "webp":
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(quality)])

    cmd.append(str(tmp_dir / f"frame_%04d.{ext}"))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg frame extraction failed: %s", result.stderr[-500:] if result.stderr else "")
        return []
    frames = sorted(tmp_dir.glob(f"frame_*.{ext}"))
    logger.info("Extracted %d frames (scene mode)", len(frames))
    return frames


def extract_frames(
    video_path: Path,
    output_dir: Path | None = None,
    max_frames: int = 0,
    mode: str = "hybrid",
    interval: int = 30,
    scene_threshold: float = 0.3,
) -> list[Path]:
    """Extract key frames from video using ffmpeg.

    Modes:
        hybrid: Uniform baseline + scene detection (default, recommended).
        timestamp: Seek to evenly-spaced timestamps (fast, legacy).
        fps: Decode with fps filter (fallback when duration unknown).
        scene: Scene change detection only.

    When max_frames is explicitly set (> 0), falls back to timestamp mode for backward compatibility.
    """
    # Backward compat: explicit max_frames reverts to timestamp mode
    if max_frames > 0 and mode == "hybrid":
        mode = "timestamp"

    if mode == "scene":
        BasePlatform.check_ffmpeg()

    if output_dir:
        tmp_dir = output_dir
        tmp_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="frames_"))

    fmt = settings.frame_format
    quality = settings.frame_quality
    width = settings.frame_width

    if mode == "hybrid":
        return _extract_frames_hybrid(
            video_path, tmp_dir,
            segments=settings.segments,
            max_scene_per_seg=settings.max_scene_per_seg,
            scene_threshold=settings.scene_threshold,
            min_gap=settings.min_gap,
            width=width, fmt=fmt, quality=quality,
        )
    if mode == "scene":
        return _extract_frames_scene(video_path, tmp_dir, max_frames or 20, scene_threshold, width, fmt, quality)
    if mode == "fps":
        return _extract_frames_fps(video_path, tmp_dir, max_frames or 20, interval, width, fmt, quality)
    return _extract_frames_timestamp(video_path, tmp_dir, max_frames or 20, interval, width, fmt, quality)
