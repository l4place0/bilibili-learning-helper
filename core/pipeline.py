import logging
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from core.asr import get_asr
from core.config import settings
from core.llm import get_llm
from core.vision.frames import extract_frames
from core.platforms.base import BasePlatform
from core.platforms.bilibili import BilibiliPlatform
from core.platforms.youtube import YouTubePlatform
from core.storage.db import Storage, get_storage
from core.observability.stage import StageContext
from core.observability.metrics import record_transcribe_empty, record_llm_fallback
from core.workers import _shutdown

logger = logging.getLogger(__name__)


# Per-group locks to prevent duplicate synthesis runs
_synthesis_locks: dict[str, threading.Lock] = {}


class MetricsTracker:
    """Track resource usage metrics for pipeline stages."""

    def __init__(self):
        self.metrics: dict = {}
        self._stage_start: float = 0
        self._total_start: float = time.monotonic()

    def start_stage(self, stage: str):
        """Record the start time for a pipeline stage.

        Args:
            stage: Stage name (e.g. "download", "transcribe", "classify").
        """
        self._stage_start = time.monotonic()
        if stage not in self.metrics:
            self.metrics[stage] = {}

    def end_stage(self, stage: str, **extra):
        """Record the end time and optional extra metrics for a pipeline stage.

        Args:
            stage: Stage name (must match a prior ``start_stage`` call).
            **extra: Arbitrary key-value pairs to attach to this stage's metrics
                     (e.g. file_size_bytes, text_length, frame_count, api_calls).
        """
        duration_ms = int((time.monotonic() - self._stage_start) * 1000)
        self.metrics[stage]["duration_ms"] = duration_ms
        for k, v in extra.items():
            self.metrics[stage][k] = v

    def finish(self) -> dict:
        """Finalize metrics by recording total elapsed time.

        Returns:
            The complete metrics dict with per-stage durations and a
            ``total_duration_ms`` key.
        """
        self.metrics["total_duration_ms"] = int((time.monotonic() - self._total_start) * 1000)
        return self.metrics

# Streaming buffers: task_id -> list of text chunks
_stream_buffers: dict[str, list[str]] = {}
_stream_lock = threading.Lock()


def get_stream_chunks(task_id: str) -> list[str]:
    """Return accumulated chunks for a task (used by SSE endpoint). Returns a copy."""
    with _stream_lock:
        return list(_stream_buffers.get(task_id, []))


def _stream_callback(task_id: str, chunk: str):
    """Called by the LLM layer for each streaming text chunk during summary generation.

    Appends the chunk to an in-memory buffer keyed by task_id (for the SSE
    endpoint) and publishes it to asyncio.Queue subscribers so that connected
    clients receive incremental updates in real time.

    Args:
        task_id: The task whose stream this chunk belongs to.
        chunk: A piece of generated summary text.
    """
    with _stream_lock:
        buf = _stream_buffers.setdefault(task_id, [])
        if len(buf) < 1000:
            buf.append(chunk)
    # Also publish to queue-based subscribers
    try:
        from core.streaming import publish as _publish
        _publish(task_id, {"chunk": chunk})
    except Exception:
        pass


def _cleanup_stream(task_id: str):
    """Remove stream buffer after task completes."""
    with _stream_lock:
        _stream_buffers.pop(task_id, None)


def _build_metadata_context(metadata: dict, lang: str = "zh") -> str:
    """Build a supplementary context string from video metadata for LLM prompts.

    Extracts the video description and tags from the metadata dict and formats
    them as labeled sections that are prepended to the transcript when
    constructing the enriched prompt for classification and summarization.

    Args:
        metadata: Video metadata dict (may contain "description" and "tags" keys).
        lang: Language code -- determines section labels ("zh" for Chinese, "en" for English).

    Returns:
        A context string with labeled description and tags sections, joined
        by double newlines. Returns an empty string if neither is present.
    """
    parts = []
    desc = metadata.get("description", "").strip()
    if desc:
        label = "视频简介" if lang == "zh" else "Video Description"
        parts.append(f"[{label}]\n{desc}")
    tags = metadata.get("tags", [])
    if tags:
        label = "标签" if lang == "zh" else "Tags"
        parts.append(f"[{label}]\n{', '.join(tags)}")
    return "\n\n".join(parts)


PLATFORMS: list[BasePlatform] = [
    BilibiliPlatform(),
    YouTubePlatform(),
]


def get_platform(url: str) -> BasePlatform:
    for p in PLATFORMS:
        if p.match(url):
            return p
    raise ValueError(f"Unsupported URL: no platform matched for {url}")


def _try_cache(db: Storage, url: str, task_id: str) -> tuple[str, dict] | None:
    """Attempt to reuse cached audio, transcript, and frames from a previous task.

    Looks up a completed task with the same video_id in the database. If found
    and the cached files still exist on disk, copies them into the new task's
    directories so the download and ASR stages can be skipped entirely.

    Args:
        db: Storage instance for database lookups.
        url: Source video URL (used to extract the platform video_id).
        task_id: The new task's UUID -- cached files are copied into this
                 task's directories.

    Returns:
        A (transcript_text, metadata_dict) tuple if cache hit, or None on miss.
    """
    platform = get_platform(url)
    video_id = platform.parse_url(url)
    cached = db.find_cached_task(video_id)
    if not cached:
        return None

    cached_task_id = cached["task_id"]
    cached_audio = settings.audio_dir / cached_task_id / f"{video_id}.wav"
    cached_transcript = settings.transcript_dir / f"{cached_task_id}.txt"

    if not cached_audio.exists() or not cached_transcript.exists():
        return None

    new_audio_dir = settings.audio_dir / task_id
    new_audio_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(cached_audio, new_audio_dir / f"{video_id}.wav")

    new_transcript = settings.transcript_dir / f"{task_id}.txt"
    shutil.copy2(cached_transcript, new_transcript)

    # Copy cached frames if they exist for this video
    cached_frames_dir = settings.frames_dir / cached_task_id
    if cached_frames_dir.exists() and any(cached_frames_dir.iterdir()):
        new_frames_dir = settings.frames_dir / task_id
        if not new_frames_dir.exists():
            shutil.copytree(cached_frames_dir, new_frames_dir)
            logger.info("[%s] Copied %d cached frames from task %s",
                        task_id[:8], len(list(new_frames_dir.iterdir())), cached_task_id[:8])

    transcript = cached_transcript.read_text(encoding="utf-8")
    metadata = cached.get("metadata", {})
    logger.info("[%s] Cache hit for video_id=%s (from task %s)", task_id[:8], video_id, cached_task_id[:8])
    return transcript, metadata


def run_pipeline(task_id: str, url: str, language: str, llm_provider: str, detail: str, mode: str = "multimodal") -> None:
    """Run the full summarization pipeline for a task in a background thread.

    Orchestrates the end-to-end flow: download audio/video from the source
    platform, transcribe with ASR, optionally extract video frames, classify
    content type with the LLM, and generate three-stage learning materials
    (preview + index + summary). Results are persisted to the database and
    published to SSE subscribers.

    The function checks a global shutdown signal at two points (after
    download/transcribe and after classify) to allow graceful abort during
    server shutdown.

    Args:
        task_id: UUID string identifying this task.
        url: Source video URL (Bilibili or YouTube).
        language: Language code for ASR and LLM prompts (e.g. "zh", "en", "ja").
        llm_provider: LLM provider name ("openai" or "claude").
        detail: Summary detail level ("brief", "normal", "detailed").
        mode: Processing mode -- "audio" for text-only, "multimodal" to include
              video frame extraction and vision-capable LLM calls.
    """
    db = get_storage()
    asr = get_asr()
    tracker = MetricsTracker()
    total_start = time.monotonic()
    video_path: Path | None = None
    try:
        platform = get_platform(url)
        platform_name = platform.__class__.__name__.replace("Platform", "").lower()

        # Try cache first
        db.update_task(task_id, status="downloading", progress=10)
        cached = _try_cache(db, url, task_id)

        prefetched_frames: list[Path] | None = None

        if cached:
            transcript, metadata = cached
            transcript_segments = metadata.get("transcript_segments", [])
            db.update_task(task_id, platform=platform_name, metadata=metadata, transcript=transcript)
            logger.info("[%s] Using cached transcript (%d chars, %d segments)", task_id[:8], len(transcript), len(transcript_segments))
            tracker.metrics["download"] = {"duration_ms": 0, "cached": True}
        else:
            # Download
            with StageContext(task_id, "download") as stage:
                stage.input(url=url, mode=mode)
                logger.info("[%s] Downloading...", task_id[:8])
                tracker.start_stage("download")
                audio_dir = settings.audio_dir / task_id
                keep_video = mode == "multimodal"
                audio_path, metadata, video_path = platform.download(url, audio_dir, keep_video=keep_video)
                file_size = audio_path.stat().st_size if audio_path.exists() else 0
                tracker.end_stage("download", file_size_bytes=file_size, cached=False)
                stage.output(file_size_bytes=file_size, platform=platform_name, has_video=video_path is not None)
                stage.decision("platform", platform_name, reason="URL matched")
                db.update_task(task_id, platform=platform_name, metadata=metadata, progress=25)

            db.update_task(task_id, status="transcribing", progress=30)

            # Transcribe (+ frame extraction in multimodal mode)
            if mode == "multimodal" and video_path and video_path.exists():
                frames_output_dir = settings.frames_dir / task_id

                # Heartbeat: update progress every 30s so the UI shows activity
                _stop_heartbeat = threading.Event()
                def _heartbeat():
                    pct = 30
                    while not _stop_heartbeat.wait(timeout=30):
                        pct = min(pct + 3, 58)
                        try:
                            db.update_task(task_id, progress=pct)
                        except Exception:
                            pass
                hb_thread = threading.Thread(target=_heartbeat, daemon=True)
                hb_thread.start()

                with StageContext(task_id, "transcribe") as stage_t, \
                     StageContext(task_id, "extract_frames") as stage_f:
                    stage_t.input(audio_path=str(audio_path), language=language)
                    stage_t.decision("backend", asr.__class__.__name__, reason="configured provider")
                    stage_f.input(video_path=str(video_path), mode="hybrid")
                    stage_f.decision("mode", "hybrid", reason="default hybrid strategy")

                    tracker.start_stage("transcribe")
                    transcript, transcript_segments = asr.transcribe_segments(audio_path, language)
                    tracker.end_stage("transcribe", text_length=len(transcript))

                    tracker.start_stage("extract_frames")
                    prefetched_frames = extract_frames(
                        video_path, frames_output_dir, 0, "hybrid", settings.frame_interval
                    )
                    tracker.end_stage("extract_frames", frame_count=len(prefetched_frames))

                    stage_t.output(text_length=len(transcript))
                    stage_f.output(frame_count=len(prefetched_frames))

                    if len(transcript) == 0:
                        stage_t.warning("0 chars transcribed — ASR model may be too small or audio codec issue")
                        record_transcribe_empty()

                _stop_heartbeat.set()
                logger.info("[%s] Transcription done (%d chars, %d segments), frames extracted (%d)",
                            task_id[:8], len(transcript), len(transcript_segments), len(prefetched_frames))
            else:
                with StageContext(task_id, "transcribe") as stage:
                    stage.input(audio_path=str(audio_path), language=language)
                    stage.decision("backend", asr.__class__.__name__, reason="configured provider")
                    tracker.start_stage("transcribe")
                    transcript, transcript_segments = asr.transcribe_segments(audio_path, language)
                    tracker.end_stage("transcribe", text_length=len(transcript))
                    stage.output(text_length=len(transcript))
                    if len(transcript) == 0:
                        stage.warning("0 chars transcribed — ASR model may be too small or audio codec issue")
                        record_transcribe_empty()

            transcript_path = settings.transcript_dir / f"{task_id}.txt"
            transcript_path.write_text(transcript, encoding="utf-8")
            metadata["transcript_segments"] = transcript_segments
            db.update_task(task_id, transcript=transcript, metadata=metadata)

        # Shutdown checkpoint after download/transcribe
        if _shutdown.is_set():
            logger.info("[%s] Shutdown requested, aborting pipeline", task_id[:8])
            return

        llm = get_llm(llm_provider)
        is_multimodal = mode == "multimodal" and video_path and video_path.exists()

        # Format segments for LLM if available
        from core.asr import format_segments_for_llm
        has_segments = bool(transcript_segments)
        if has_segments:
            formatted_segments = format_segments_for_llm(transcript_segments)
            segment_transcript = formatted_segments
        else:
            segment_transcript = transcript

        # Build enriched transcript with metadata context (description, tags)
        meta_ctx = _build_metadata_context(metadata, language)
        enriched_transcript = f"{meta_ctx}\n\n[转录文本]\n{segment_transcript}" if meta_ctx else segment_transcript

        # Classify
        with StageContext(task_id, "classify") as stage:
            stage.input(transcript_length=len(enriched_transcript), multimodal=is_multimodal)
            stage.decision("llm_provider", llm_provider, reason="configured")
            db.update_task(task_id, status="classifying", progress=75)
            tracker.start_stage("classify")
            classification = llm.classify(enriched_transcript, lang=language, multimodal=is_multimodal)
            tracker.end_stage("classify", api_calls=1)
            content_type = classification["type"]
            stage.output(content_type=content_type)
            stage.decision("content_type", content_type, reason="LLM classification")

        metadata["content_type"] = content_type
        metadata["language"] = language
        db.update_task(task_id, metadata=metadata)

        # Shutdown checkpoint after classify
        if _shutdown.is_set():
            logger.info("[%s] Shutdown requested, aborting pipeline", task_id[:8])
            return

        # Generate three-stage learning materials (preview + index + summary)
        with StageContext(task_id, "generate_three_stage") as stage:
            stage.input(content_type=content_type, detail=detail, multimodal=is_multimodal)
            stage.decision("llm_provider", llm_provider, reason="configured")
            db.update_task(task_id, status="generating_three_stage", progress=90)
            tracker.start_stage("generate_three_stage")

            logger.info("[%s] Generating three-stage materials (type=%s, has_segments=%s)...",
                        task_id[:8], content_type, has_segments)
            three_stage = llm.generate_three_stage(
                enriched_transcript, lang=language, detail=detail, has_segments=has_segments,
            )

            summary = three_stage.get("summary", {}).get("text", "")
            metadata["preview"] = three_stage.get("preview", {})
            metadata["index"] = three_stage.get("index", [])
            metadata["questions"] = three_stage.get("summary", {}).get("cards", [])

            # Stream summary text for SSE compatibility
            _stream_callback(task_id, summary)

            tracker.end_stage("generate_three_stage", api_calls=1)
            stage.output(summary_length=len(summary), index_count=len(metadata.get("index", [])))

        # Save metrics to metadata
        metadata["metrics"] = tracker.finish()
        now = datetime.now(timezone.utc).isoformat()
        db.update_task(task_id, status="done", summary=summary, completed_at=now, progress=100, metadata=metadata)
        logger.info("[%s] Done! Total: %dms", task_id[:8], metadata["metrics"]["total_duration_ms"])

        # Publish done event to SSE subscribers
        try:
            from core.streaming import publish as _publish
            _publish(task_id, {"done": True, "summary": summary})
        except Exception:
            pass

        # Auto-trigger synthesis if this task belongs to a group
        group_id = metadata.get("group_id")
        if group_id:
            _maybe_trigger_synthesis(group_id, language, llm_provider)

    except Exception as e:
        logger.exception("[%s] Failed: %s", task_id[:8], e)
        now = datetime.now(timezone.utc).isoformat()
        error_msg = "Pipeline execution failed"
        # Save partial metrics even on failure
        try:
            metadata["metrics"] = tracker.finish()
            db.update_task(task_id, status="failed", error=error_msg, completed_at=now, metadata=metadata)
        except Exception:
            db.update_task(task_id, status="failed", error=error_msg, completed_at=now)
        # Publish failure event to SSE subscribers
        try:
            from core.streaming import publish as _publish
            _publish(task_id, {"done": True, "error": error_msg})
        except Exception:
            pass
    finally:
        _cleanup_stream(task_id)
        if video_path and video_path.exists():
            video_path.unlink(missing_ok=True)


def _maybe_trigger_synthesis(group_id: str, language: str, llm_provider: str) -> None:
    """Check if all tasks in a group are done, and if so, trigger synthesis."""
    db = get_storage()
    tasks = db.get_tasks_by_group(group_id)
    if len(tasks) < 2:
        return
    all_done = all(t.get("status") == "done" for t in tasks)
    if not all_done:
        return
    # Check if synthesis already exists
    existing = db.get_group_synthesis(group_id)
    if existing:
        return
    # Acquire per-group lock to prevent duplicate synthesis triggers
    lock = _synthesis_locks.setdefault(group_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return  # another thread is already running synthesis for this group
    logger.info("All tasks in group %s are done, triggering synthesis", group_id)
    thread = threading.Thread(
        target=_run_synthesis_with_lock, args=(lock, group_id, language, llm_provider), daemon=True,
    )
    thread.start()


def _run_synthesis_with_lock(lock: threading.Lock, group_id: str, language: str, llm_provider: str) -> None:
    """Wrapper that releases the group lock after synthesis completes."""
    try:
        run_synthesis(group_id, language, llm_provider)
    finally:
        lock.release()
        _synthesis_locks.pop(group_id, None)


def run_synthesis(group_id: str, language: str, llm_provider: str) -> str | None:
    """Run synthesis for a group of completed tasks. Returns synthesis task_id or None."""
    db = get_storage()
    tasks = db.get_tasks_by_group(group_id)
    if not tasks:
        logger.warning("Synthesis: no tasks found for group %s", group_id)
        return None

    # Only proceed if all tasks are done
    done_tasks = [t for t in tasks if t.get("status") == "done"]
    if len(done_tasks) < 2:
        logger.warning("Synthesis: need at least 2 completed tasks, got %d", len(done_tasks))
        return None

    # Build synthesis input
    from core.asr import format_segments_for_llm
    from core.llm.prompts import get_synthesis_prompt

    summaries = []
    transcripts = []
    for i, task in enumerate(done_tasks, 1):
        summary = task.get("summary", "") or ""
        # Strip review cards from summary for synthesis
        import re
        summary_clean = re.sub(r"##\s*(?:复习卡片|Review Cards)[\s\S]*$", "", summary, flags=re.IGNORECASE).strip()
        summaries.append(f"[视频{i} - {task.get('metadata', {}).get('title', 'Untitled')}]\n{summary_clean}")

        # Get top segments
        segments = task.get("metadata", {}).get("transcript_segments", [])
        if segments:
            seg_limit = max(10, len(segments) * 2 // 5)
            top_segs = segments[:seg_limit]
            transcripts.append(f"[视频{i} 转录片段]\n{format_segments_for_llm(top_segs)}")
        else:
            transcript = task.get("transcript", "") or ""
            transcripts.append(f"[视频{i} 转录]\n{transcript[:2000]}")

    prompt_template = get_synthesis_prompt(lang=language)
    prompt = prompt_template.format(
        n=len(done_tasks),
        summaries="\n\n".join(summaries),
        transcripts="\n\n".join(transcripts),
    )

    # Create synthesis task
    synthesis_task_id = db.create_task(url=f"group:{group_id}", platform="synthesis")
    first_meta = done_tasks[0].get("metadata") or {}
    synthesis_meta = {
        "group_id": group_id,
        "synthesis_for": group_id,
        "title": f"综合分析: {first_meta.get('title', group_id)}",
        "language": language,
        "source_count": len(done_tasks),
        "source_titles": [t.get("metadata", {}).get("title", "") for t in done_tasks],
    }
    db.update_task(synthesis_task_id, metadata=synthesis_meta, status="summarizing", progress=50)

    try:
        llm = get_llm(llm_provider)
        summary = llm._chat(prompt, max_tokens=8192)

        # Generate synthesis questions
        from core.questions import parse_questions
        from core.llm.prompts import get_question_generation_prompt
        q_prompt_template = get_question_generation_prompt("general", lang=language)
        q_prompt = q_prompt_template.format(summary=summary, transcript=transcripts[0][:2000] if transcripts else "")
        raw_questions = llm._chat(q_prompt, max_tokens=4096)
        questions = parse_questions(raw_questions)

        synthesis_meta["questions"] = questions
        now = datetime.now(timezone.utc).isoformat()
        db.update_task(synthesis_task_id, status="done", summary=summary, completed_at=now, progress=100, metadata=synthesis_meta)
        logger.info("Synthesis done for group %s: %d chars, %d questions", group_id, len(summary), len(questions))
        return synthesis_task_id
    except Exception as e:
        logger.exception("Synthesis failed for group %s: %s", group_id, e)
        now = datetime.now(timezone.utc).isoformat()
        db.update_task(synthesis_task_id, status="failed", error="Synthesis failed", completed_at=now, metadata=synthesis_meta)
        return None
