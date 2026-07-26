import logging
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from core.config import settings
from core.platforms.base import BasePlatform
from core.runtime import ffmpeg_executable, ffprobe_executable

logger = logging.getLogger(__name__)


@lru_cache(maxsize=None)
def _supports_encoder(name: str) -> bool:
    try:
        result = subprocess.run(
            [ffmpeg_executable(), "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and name in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


@lru_cache(maxsize=1)
def _supports_cwebp() -> bool:
    executable = shutil.which("cwebp")
    if not executable:
        return False
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _get_video_duration(video_path: Path) -> float:
    """Get video duration using ffprobe or the bundled FFmpeg fallback."""
    ffprobe = ffprobe_executable()
    try:
        if ffprobe:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(video_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return float(result.stdout.strip())

        result = subprocess.run(
            [ffmpeg_executable(), "-hide_banner", "-i", str(video_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        match = re.search(
            r"Duration:\s*(\d+):(\d+):([\d.]+)",
            result.stderr,
        )
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return 0
    except Exception as e:
        logger.warning("Video duration probe failed for %s: %s", video_path.name, e)
        return 0


def _detect_scene_changes(video_path: Path, threshold: float = 0.3) -> list[tuple[float, float]]:
    """Detect scene changes globally using ffmpeg, returns list of (timestamp, score)."""
    cmd = [
        ffmpeg_executable(), "-i", str(video_path),
        "-vf",
        (
            f"select='gt(scene,{threshold})',"
            "metadata=print:file=-"
        ),
        "-an",
        "-vsync", "vfr", "-f", "null", "-",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        output = f"{result.stdout}\n{result.stderr}"
    except subprocess.TimeoutExpired:
        logger.warning("Scene detection timed out for %s", video_path.name)
        return []

    scenes = []
    pattern = re.compile(
        r"frame:\d+.*?pts_time:([-\d.]+)\s*\n"
        r"lavfi\.scene_score=([\d.]+)"
    )
    for match in pattern.finditer(output):
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
    use_cwebp = (
        fmt == "webp"
        and not _supports_encoder("libwebp")
        and _supports_cwebp()
    )
    ffmpeg_output = (
        out_path.with_name(f"{out_path.stem}.source.jpg")
        if use_cwebp
        else out_path
    )
    vf = f"scale={width}:-2"
    cmd = [
        ffmpeg_executable(), "-ss", f"{ts:.1f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", vf,
        "-y", "-hide_banner", "-loglevel", "error",
    ]
    if fmt == "webp" and not use_cwebp:
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(min(quality // 5, 5))])  # map 85 -> ~2 for JPEG

    cmd.append(str(ffmpeg_output))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0 or not ffmpeg_output.exists():
            return False
        if not use_cwebp:
            return out_path.exists()
        converted = subprocess.run(
            [
                shutil.which("cwebp") or "cwebp",
                "-quiet",
                "-q",
                str(quality),
                str(ffmpeg_output),
                "-o",
                str(out_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        ffmpeg_output.unlink(missing_ok=True)
        return converted.returncode == 0 and out_path.exists()
    except subprocess.TimeoutExpired:
        logger.warning("Timeout extracting frame at %.1fs", ts)
        ffmpeg_output.unlink(missing_ok=True)
        return False


def _encode_timestamps(
    video_path: Path,
    output_dir: Path,
    timestamps: list[float],
    width: int,
    fmt: str,
    quality: int,
    prefix: str = "frame",
) -> list[Path]:
    """Extract independent timestamp seeks concurrently and preserve ordering."""
    ext = "webp" if fmt == "webp" else "jpg"
    jobs = [
        (timestamp, output_dir / f"{prefix}_{index:04d}.{ext}")
        for index, timestamp in enumerate(timestamps, 1)
    ]
    if not jobs:
        return []

    workers = min(max(1, settings.frame_workers), len(jobs))

    def encode(job: tuple[float, Path]) -> tuple[Path, bool]:
        timestamp, target = job
        return (
            target,
            _encode_frame(video_path, timestamp, target, width, fmt, quality),
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(encode, jobs))
    return [target for target, succeeded in results if succeeded]


def _select_diverse_scene_events(
    timestamps: list[float],
    scores: dict[float, float],
    duration: float,
    buckets: int,
    limit: int,
) -> list[float]:
    """Prefer one high-score event per time bucket before global fill."""
    if limit <= 0:
        return []
    bucket_size = duration / max(1, buckets)
    selected = []
    for bucket in range(max(1, buckets)):
        start = bucket * bucket_size
        end = (bucket + 1) * bucket_size
        candidates = [
            timestamp for timestamp in timestamps if start <= timestamp < end
        ]
        if candidates:
            selected.append(
                max(candidates, key=lambda item: scores.get(item, 0))
            )
        if len(selected) >= limit:
            return selected
    remaining = sorted(
        (timestamp for timestamp in timestamps if timestamp not in selected),
        key=lambda item: scores.get(item, 0),
        reverse=True,
    )
    return (selected + remaining)[:limit]


def _choose_burst_frames(
    video_path: Path,
    output_dir: Path,
    baseline_timestamps: list[float],
    event_timestamps: list[float],
    all_scene_timestamps: list[float],
    offsets: tuple[float, ...],
    max_frames: int,
    duration: float,
    width: int,
    fmt: str,
    quality: int,
) -> list[Path]:
    """Encode scene bursts, keep one representative per event, and renumber."""
    groups: list[list[tuple[float, float]]] = []
    for timestamp in event_timestamps:
        next_scene = next(
            (
                candidate
                for candidate in all_scene_timestamps
                if candidate > timestamp
            ),
            duration,
        )
        group = []
        for offset in offsets:
            candidate = min(
                duration - 0.1,
                next_scene - 0.05,
                timestamp + max(0.0, offset),
            )
            if candidate >= 0 and all(
                abs(candidate - existing[0]) >= 0.2 for existing in group
            ):
                group.append((candidate, offset))
        if group:
            groups.append(group)

    candidates = list(baseline_timestamps)
    for group in groups:
        candidates.extend(timestamp for timestamp, _offset in group)
    encoded = _encode_timestamps(
        video_path,
        output_dir,
        candidates,
        width,
        fmt,
        quality,
        prefix="candidate",
    )
    encoded_set = set(encoded)
    ext = "webp" if fmt == "webp" else "jpg"
    paths = [
        output_dir / f"candidate_{index:04d}.{ext}"
        for index in range(1, len(candidates) + 1)
    ]
    selected: list[tuple[float, Path]] = []
    for index, timestamp in enumerate(baseline_timestamps):
        if paths[index] in encoded_set:
            selected.append((timestamp, paths[index]))

    cursor = len(baseline_timestamps)
    unused: list[tuple[float, Path]] = []
    for group in groups:
        choices = []
        for timestamp, offset in group:
            path = paths[cursor]
            cursor += 1
            if path in encoded_set:
                # WebP size is a cheap proxy for retained visual/text detail.
                preference = -abs(offset - 0.5)
                choices.append(
                    (path.stat().st_size, preference, timestamp, path)
                )
        if choices:
            best = max(choices)
            selected.append((best[2], best[3]))
            unused.extend(
                (item[2], item[3]) for item in choices if item != best
            )

    if len(selected) < max_frames:
        unused.sort(key=lambda item: item[1].stat().st_size, reverse=True)
        selected.extend(unused[: max_frames - len(selected)])
    selected = sorted(selected, key=lambda item: item[0])[:max_frames]

    staged = []
    for index, (_timestamp, source) in enumerate(selected, 1):
        target = output_dir / f".selected_{index:04d}.{ext}"
        os.replace(source, target)
        staged.append(target)
    for candidate in output_dir.glob(f"candidate_*.{ext}"):
        candidate.unlink(missing_ok=True)
    result = []
    for index, source in enumerate(staged, 1):
        target = output_dir / f"frame_{index:04d}.{ext}"
        os.replace(source, target)
        result.append(target)
    return result


def extract_frames_at(
    video_path: Path,
    output_dir: Path,
    timestamps: list[float],
    *,
    width: int | None = None,
    fmt: str | None = None,
    quality: int | None = None,
) -> list[Path]:
    """Extract frames at explicit timestamps for host-AI visual follow-up."""
    BasePlatform.check_ffmpeg()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_format = fmt or settings.frame_format
    if (
        selected_format == "webp"
        and not _supports_encoder("libwebp")
        and not _supports_cwebp()
    ):
        logger.warning("No WebP encoder is available; falling back to JPEG frames")
        selected_format = "jpg"
    normalized = sorted({max(0.0, float(timestamp)) for timestamp in timestamps})
    return _encode_timestamps(
        video_path,
        output_dir,
        normalized,
        width or settings.frame_width,
        selected_format,
        quality or settings.frame_quality,
    )


def _convert_images_to_webp(paths: list[Path], quality: int) -> list[Path]:
    """Convert extracted JPEG frames with cwebp, preserving successful inputs."""
    executable = shutil.which("cwebp")
    if not executable:
        return paths
    converted_paths: list[Path] = []
    for source in paths:
        target = source.with_suffix(".webp")
        try:
            result = subprocess.run(
                [
                    executable,
                    "-quiet",
                    "-q",
                    str(quality),
                    str(source),
                    "-o",
                    str(target),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            logger.warning("Timed out converting %s to WebP", source.name)
            converted_paths.append(source)
            continue
        if result.returncode == 0 and target.is_file():
            source.unlink(missing_ok=True)
            converted_paths.append(target)
        else:
            logger.warning("cwebp failed for %s: %s", source.name, result.stderr)
            converted_paths.append(source)
    return converted_paths


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
    max_frames: int = 0,
    scene_offsets: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0),
) -> list[Path]:
    """Hybrid extraction: uniform baseline (segment midpoints) + scene detection."""
    duration = _get_video_duration(video_path)
    if duration <= 0:
        logger.warning("Could not determine duration, falling back to fps filter")
        return _extract_frames_fps(video_path, output_dir, segments, max(1, int(duration / segments)) if duration > 0 else 30, width, fmt, quality)

    baseline_count = segments
    if max_frames > 0:
        baseline_count = max(1, min(segments, max_frames // 2))
    seg_len = duration / baseline_count
    # Baseline: midpoint of each segment
    baseline_ts = [
        seg_idx * seg_len + seg_len / 2
        for seg_idx in range(baseline_count)
    ]

    # Scene detection (global single pass)
    scenes = _detect_scene_changes(video_path, scene_threshold)
    scene_ts = _assign_scenes_to_segments(
        scenes,
        duration,
        baseline_count,
        max_scene_per_seg,
        min_gap,
        baseline_ts,
    )
    if max_frames > 0:
        remaining = max(0, max_frames - len(baseline_ts))
        scores = {timestamp: score for timestamp, score in scenes}
        selected_events = _select_diverse_scene_events(
            scene_ts,
            scores,
            duration,
            baseline_count,
            remaining,
        )
        target_baselines = max_frames - len(selected_events)
        if len(baseline_ts) < target_baselines:
            supplemental = [
                (index + 0.5) * duration / max_frames
                for index in range(max_frames)
            ]
            for timestamp in supplemental:
                if len(baseline_ts) >= target_baselines:
                    break
                if any(
                    abs(timestamp - existing) < 0.5
                    for existing in baseline_ts
                ):
                    continue
                baseline_ts.append(timestamp)
            baseline_ts.sort()
        all_scene_times = sorted(timestamp for timestamp, _score in scenes)
        frames = _choose_burst_frames(
            video_path,
            output_dir,
            baseline_ts,
            selected_events,
            all_scene_times,
            scene_offsets,
            max_frames,
            duration,
            width,
            fmt,
            quality,
        )
        logger.info(
            "Hybrid extraction: %d baseline + %d representative scenes = "
            "%d total frames from %.0fs video",
            len(baseline_ts),
            max(0, len(frames) - len(baseline_ts)),
            len(frames),
            duration,
        )
        return frames

    # Merge and sort all timestamps
    all_ts = sorted(set(baseline_ts + scene_ts))

    logger.info(
        "Hybrid extraction: %d baseline + %d scene = %d total frames from %.0fs video",
        len(baseline_ts), len(scene_ts), len(all_ts), duration,
    )

    # Extract frames
    frames = _encode_timestamps(
        video_path, output_dir, all_ts, width, fmt, quality
    )

    logger.info("Extracted %d/%d frames from %s", len(frames), len(all_ts), video_path.name)
    return frames


def _extract_frames_timestamp(video_path: Path, tmp_dir: Path, max_frames: int, interval: int, width: int = 0, fmt: str = "jpg", quality: int = 2) -> list[Path]:
    """Extract frames by seeking to evenly-spaced timestamps using a single ffmpeg select filter."""
    duration = _get_video_duration(video_path)
    if duration <= 0:
        logger.warning("Could not determine video duration, falling back to fps filter")
        return _extract_frames_fps(video_path, tmp_dir, max_frames, interval, width, fmt, quality)

    step = duration / max_frames if max_frames > 0 else interval
    timestamps = []
    t = step / 2
    while t < duration and len(timestamps) < max_frames:
        timestamps.append(t)
        t += step

    logger.info("Extracting %d frames from %.0fs video (step=%.0fs)", len(timestamps), duration, step)

    effective_width = width or settings.frame_width

    # Exact equality in a single select filter misses frames when stream time
    # bases do not land on the requested decimal timestamp. Per-timestamp seek
    # is slightly more subprocess work but reliably honors --frames N.
    frames = _encode_timestamps(
        video_path,
        tmp_dir,
        timestamps,
        effective_width,
        fmt,
        quality,
    )

    logger.info(
        "Extracted %d/%d frames from %s",
        len(frames),
        len(timestamps),
        video_path.name,
    )
    return frames


def _extract_frames_fps(video_path: Path, tmp_dir: Path, max_frames: int, interval: int, width: int = 0, fmt: str = "jpg", quality: int = 2) -> list[Path]:
    """Fallback: extract frames using fps filter (for unknown duration)."""
    convert_after = (
        fmt == "webp"
        and not _supports_encoder("libwebp")
        and _supports_cwebp()
    )
    encoder_fmt = "jpg" if convert_after else fmt
    ext = "webp" if encoder_fmt == "webp" else "jpg"
    fps_filter = f"fps=1/{interval}"
    vf = fps_filter
    if width:
        vf += f",scale={width}:-2"

    cmd = [
        ffmpeg_executable(), "-i", str(video_path),
        "-vf", vf,
        "-frames:v", str(max_frames),
        "-y", "-hide_banner", "-loglevel", "error",
    ]
    if encoder_fmt == "webp":
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(min(quality // 5, 5))])

    cmd.append(str(tmp_dir / f"frame_%04d.{ext}"))

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        logger.warning("ffmpeg frame extraction failed: %s", result.stderr)
        return []
    frames = sorted(tmp_dir.glob(f"frame_*.{ext}"))
    return _convert_images_to_webp(frames, quality) if convert_after else frames


def _extract_frames_scene(video_path: Path, tmp_dir: Path, max_frames: int, threshold: float, width: int = 0, fmt: str = "jpg", quality: int = 3) -> list[Path]:
    """Extract frames at scene change boundaries."""
    convert_after = (
        fmt == "webp"
        and not _supports_encoder("libwebp")
        and _supports_cwebp()
    )
    encoder_fmt = "jpg" if convert_after else fmt
    ext = "webp" if encoder_fmt == "webp" else "jpg"
    vf = f"select='gt(scene,{threshold})'"
    if width:
        vf += f",scale={width}:-2"

    cmd = [
        ffmpeg_executable(), "-y", "-i", str(video_path),
        "-vf", vf,
        "-vsync", "vfr",
        "-frames:v", str(max_frames),
    ]
    if encoder_fmt == "webp":
        cmd.extend(["-c:v", "libwebp", "-quality", str(quality)])
    else:
        cmd.extend(["-q:v", str(quality)])

    cmd.append(str(tmp_dir / f"frame_%04d.{ext}"))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("ffmpeg frame extraction failed: %s", result.stderr[-500:] if result.stderr else "")
        return []
    frames = sorted(tmp_dir.glob(f"frame_*.{ext}"))
    if convert_after:
        frames = _convert_images_to_webp(frames, quality)
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

    """
    if mode == "scene":
        BasePlatform.check_ffmpeg()

    managed_tmp = False
    if output_dir:
        tmp_dir = output_dir
        tmp_dir.mkdir(parents=True, exist_ok=True)
    else:
        tmp_dir = Path(tempfile.mkdtemp(prefix="frames_"))
        managed_tmp = True

    desired_fmt = settings.frame_format
    cwebp_available = _supports_cwebp()
    if (
        desired_fmt == "webp"
        and not _supports_encoder("libwebp")
        and not cwebp_available
    ):
        logger.warning("ffmpeg does not provide libwebp; falling back to JPEG frames")
        desired_fmt = "jpg"
    convert_after = (
        desired_fmt == "webp"
        and not _supports_encoder("libwebp")
        and cwebp_available
        and mode in ("fps", "scene")
    )
    fmt = "jpg" if convert_after else desired_fmt
    quality = settings.frame_quality
    width = settings.frame_width

    try:
        if mode == "hybrid":
            frames = _extract_frames_hybrid(
                video_path, tmp_dir,
                segments=settings.segments,
                max_scene_per_seg=settings.max_scene_per_seg,
                scene_threshold=settings.scene_threshold,
                min_gap=settings.min_gap,
                width=width, fmt=fmt, quality=quality,
                max_frames=max_frames,
                scene_offsets=tuple(
                    float(value)
                    for value in settings.scene_offsets.split(",")
                    if value.strip()
                ),
            )
        elif mode == "scene":
            frames = _extract_frames_scene(video_path, tmp_dir, max_frames or 20, scene_threshold, width, fmt, quality)
        elif mode == "fps":
            frames = _extract_frames_fps(video_path, tmp_dir, max_frames or 20, interval, width, fmt, quality)
        else:
            frames = _extract_frames_timestamp(video_path, tmp_dir, max_frames or 20, interval, width, fmt, quality)
        return _convert_images_to_webp(frames, quality) if convert_after else frames
    finally:
        if managed_tmp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
