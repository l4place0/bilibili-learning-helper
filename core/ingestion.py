"""Framework-independent synchronous video ingestion application service."""

from __future__ import annotations

import html
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.asr import get_asr
from core.cache import CacheStore, derived_key, media_key
from core.config import settings
from core.library import FilesystemLibrary, ResourceRecord
from core.platforms import get_platform
from core.vision.frames import extract_frames


_URL_RE = re.compile(r"https?://[^\s]+")
ProgressCallback = Callable[[str, int, str], None]


def extract_shared_url(value: str) -> str:
    """Extract and HTML-decode a URL from Bilibili/YouTube share text."""
    decoded = html.unescape(value).strip()
    match = _URL_RE.search(decoded)
    if not match:
        return decoded
    return match.group(0).rstrip("。，、；;！!）)]}")


@dataclass(frozen=True)
class IngestionRequest:
    source: str
    output_dir: Path
    language: str = "zh"
    asr_provider: str = ""
    asr_profile: str = ""
    asr_model_path: Path | None = None
    frame_count: int = 10
    frame_mode: str = "hybrid"
    cache_policy: str = "off"
    fact_check_mode: str = "auto"
    force: bool = False


class IngestionService:
    def __init__(
        self,
        *,
        asr_factory=get_asr,
        platform_resolver=get_platform,
        frame_extractor=extract_frames,
    ):
        self._asr_factory = asr_factory
        self._platform_resolver = platform_resolver
        self._frame_extractor = frame_extractor

    def ingest(
        self,
        request: IngestionRequest,
        progress: ProgressCallback | None = None,
    ) -> ResourceRecord:
        url = extract_shared_url(request.source)
        platform = self._platform_resolver(url)
        platform_name = platform.__class__.__name__.replace("Platform", "").lower()
        video_id = platform.parse_url(url)
        media_cache_key = media_key(platform_name, video_id)
        audio_cache_key = derived_key(
            media_cache_key,
            "audio",
            sample_rate=16000,
            channels=1,
            codec="pcm_s16le",
        )
        video_cache_key = derived_key(
            media_cache_key,
            "video",
            quality="720p",
            format="m4s",
        )
        metadata_cache_key = derived_key(media_cache_key, "metadata")
        transcript_cache_key = derived_key(
            audio_cache_key,
            "transcript",
            provider=request.asr_provider or settings.asr_provider,
            profile=request.asr_profile,
            model=(
                request.asr_model_path.name
                if request.asr_model_path is not None
                else settings.asr_model
            ),
            language=request.language,
            implementation=1,
        )
        frames_cache_key = derived_key(
            video_cache_key,
            "frames",
            mode=request.frame_mode,
            count=request.frame_count,
            threshold=settings.scene_threshold,
            offsets=settings.scene_offsets,
            width=settings.frame_width,
            format=settings.frame_format,
            quality=settings.frame_quality,
            implementation=5,
        )
        cache = (
            CacheStore(settings.cache_dir)
            if request.cache_policy != "off"
            else None
        )
        use_cached = cache is not None and request.cache_policy == "reuse"

        def report(stage: str, percent: int, message: str) -> None:
            if progress:
                progress(stage, percent, message)

        report("prepare", 5, "Preparing temporary workspace")
        work_dir = Path(tempfile.mkdtemp(prefix=f"video-sum-{video_id}-"))
        try:
            cached_transcript = (
                cache.read_json(transcript_cache_key) if use_cached else None
            )
            cached_metadata = (
                cache.read_json(metadata_cache_key) if use_cached else None
            )
            cached_frames = (
                cache.get(frames_cache_key)
                if use_cached and request.frame_count > 0
                else None
            )
            needs_video_for_processing = (
                request.frame_count > 0 and cached_frames is None
            )
            cached_audio = (
                cache.get(audio_cache_key)
                if use_cached and cached_transcript is None
                else None
            )
            cached_video = (
                cache.get(video_cache_key)
                if (
                    use_cached
                    and needs_video_for_processing
                )
                else None
            )

            needs_download = (
                cached_metadata is None
                or (cached_transcript is None and cached_audio is None)
                or (
                    needs_video_for_processing
                    and cached_video is None
                )
            )
            audio_path: Path | None = None
            video_path: Path | None = None
            if needs_download:
                report("download", 10, "Downloading source media")
                audio_path, metadata, video_path = platform.download(
                    url,
                    work_dir,
                    keep_video=needs_video_for_processing,
                )
                if cache:
                    cache.put_path(audio_cache_key, "audio", audio_path)
                    cache.put_json(
                        metadata_cache_key, "metadata", metadata
                    )
                    if video_path:
                        cache.put_path(video_cache_key, "media", video_path)
            else:
                report("cache", 15, "Reusing cached source artifacts")
                metadata = cached_metadata

            if cached_transcript is None and audio_path is None:
                assert cache is not None and cached_audio is not None
                audio_path = cache.materialize_file(
                    cached_audio, work_dir / "cached-audio.wav"
                )
            if (
                needs_video_for_processing
                and video_path is None
            ):
                assert cache is not None and cached_video is not None
                video_path = cache.materialize_file(
                    cached_video, work_dir / "cached-video.m4s"
                )

            frames: list[Path] = []
            if request.frame_count > 0:
                if cached_frames is not None and cache is not None:
                    report("cache", 35, "Reusing cached key frames")
                    frames = cache.materialize_directory(
                        cached_frames, work_dir / "frames"
                    )
                elif not video_path or not video_path.exists():
                    raise RuntimeError(
                        "Video stream is unavailable; cannot produce required key frames"
                    )
                else:
                    report("frames", 35, "Extracting key frames")
                    frames = self._frame_extractor(
                        video_path,
                        work_dir / "frames",
                        max_frames=request.frame_count,
                        mode=request.frame_mode,
                    )
                    if cache and frames:
                        cache.put_path(
                            frames_cache_key,
                            "frames",
                            work_dir / "frames",
                        )
                if not frames:
                    raise RuntimeError("Key-frame extraction produced no frames")

            if cached_transcript is not None:
                report("cache", 85, "Reusing cached transcript")
                transcript = str(cached_transcript.get("transcript") or "")
                segments = cached_transcript.get("segments") or []
            else:
                if audio_path is None:
                    raise RuntimeError("Audio stream is unavailable")
                report("transcribe", 50, "Transcribing audio")
                asr_kwargs = {}
                if request.asr_model_path is not None:
                    asr_kwargs["model_path"] = request.asr_model_path
                asr_kwargs["progress_callback"] = lambda value: report(
                    "transcribe",
                    50 + int(value * 0.35),
                    f"Transcribing audio ({value}%)",
                )
                asr = self._asr_factory(request.asr_provider, **asr_kwargs)
                transcript, segments = asr.transcribe_segments(
                    audio_path, request.language
                )
                if cache and transcript.strip():
                    cache.put_json(
                        transcript_cache_key,
                        "transcript",
                        {"transcript": transcript, "segments": segments},
                    )
            if not transcript.strip():
                raise RuntimeError("Transcription returned empty text")

            metadata = dict(metadata)
            metadata["content_type"] = "unclassified"
            metadata["language"] = request.language
            report("save", 90, "Saving resource note")
            record = FilesystemLibrary(request.output_dir).save(
                platform=platform_name,
                video_id=video_id,
                source_url=url,
                metadata=metadata,
                summary="",
                transcript=transcript,
                transcript_segments=segments,
                frames=frames,
                providers={
                    "asr": request.asr_provider or "configured-default",
                    "asr_profile": request.asr_profile or "configured-default",
                    "asr_model": (
                        request.asr_model_path.name
                        if request.asr_model_path is not None
                        else "configured-default"
                    ),
                    "llm": "host-pending",
                    "cache": request.cache_policy,
                },
                cache_keys={
                    "media": video_cache_key,
                    "audio": audio_cache_key,
                    "transcript": transcript_cache_key,
                    "frames": (
                        frames_cache_key if request.frame_count > 0 else ""
                    ),
                },
                fact_check_mode=request.fact_check_mode,
                force=request.force,
            )
            report("done", 100, "Resource saved")
            return record
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
