import json
import logging
import re
from pathlib import Path

_URL_RE = re.compile(r"https?://[^\s]+")

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from core.config import settings
from core.models import (
    BatchSummarizeRequest,
    BatchSummarizeResponse,
    BatchTaskItem,
    FavoriteRequest,
    GroupSummarizeRequest,
    GroupSummarizeResponse,
    GroupStatusResponse,
    HealthResponse,
    StorageCleanupResult,
    StorageInfo,
    SummarizeRequest,
    TaskDetail,
    TaskListItem,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
)
from core.pipeline import get_platform, run_pipeline
from core.workers import submit_pipeline, shutdown_workers
from core.streaming import subscribe, unsubscribe, publish
from core.storage.db import get_storage
from core.storage.files import cache_size, clean_all, clean_cache

logger = logging.getLogger(__name__)
router = APIRouter()
db = get_storage()


def _extract_url(text: str) -> str:
    """Extract URL from share text like '【标题】 https://...'."""
    m = _URL_RE.search(text)
    return m.group(0) if m else text.strip()


@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse()


@router.post("/api/summarize", response_model=TaskResponse, status_code=202)
async def summarize(req: SummarizeRequest):
    # Extract URL from share text and validate
    url = _extract_url(req.url)
    try:
        get_platform(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    task_id = db.create_task(url, platform="unknown")

    # Run pipeline in background thread pool
    submit_pipeline(run_pipeline, task_id, url, req.language, req.llm_provider, req.detail, req.mode)

    return TaskResponse(task_id=task_id, status=TaskStatus.PENDING)


@router.post("/api/summarize/batch", response_model=BatchSummarizeResponse, status_code=202)
async def summarize_batch(req: BatchSummarizeRequest):
    """Submit multiple URLs for summarization. Invalid URLs are skipped."""
    created = []
    skipped = []

    for raw_url in req.urls:
        raw_url = raw_url.strip()
        if not raw_url:
            continue
        url = _extract_url(raw_url)
        try:
            get_platform(url)
        except ValueError:
            skipped.append(raw_url)
            continue

        task_id = db.create_task(url, platform="unknown")
        submit_pipeline(run_pipeline, task_id, url, req.language, req.llm_provider, req.detail, req.mode)
        created.append(BatchTaskItem(task_id=task_id, url=url, status=TaskStatus.PENDING))

    return BatchSummarizeResponse(tasks=created, skipped=skipped)


@router.post("/api/summarize/group", response_model=GroupSummarizeResponse, status_code=202)
async def summarize_group(req: GroupSummarizeRequest):
    """Submit multiple URLs as a group for combined analysis."""
    import uuid
    group_id = str(uuid.uuid4())[:8]
    created = []
    skipped = []

    for raw_url in req.urls:
        raw_url = raw_url.strip()
        if not raw_url:
            continue
        url = _extract_url(raw_url)
        try:
            get_platform(url)
        except ValueError:
            skipped.append(raw_url)
            continue

        task_id = db.create_task(url, platform="unknown")
        # Store group_id in metadata
        meta = {"group_id": group_id}
        db.update_task(task_id, metadata=meta)

        submit_pipeline(run_pipeline, task_id, url, req.language, req.llm_provider, req.detail, req.mode)
        created.append(task_id)

    return GroupSummarizeResponse(group_id=group_id, task_ids=created, skipped=skipped)


@router.get("/api/groups/{group_id}", response_model=GroupStatusResponse)
async def get_group_status(group_id: str):
    """Get group status including individual tasks and synthesis result."""
    tasks = db.get_tasks_by_group(group_id)
    if not tasks:
        raise HTTPException(status_code=404, detail="Group not found")

    task_items = [
        TaskListItem(
            task_id=t["task_id"],
            url=t["url"],
            platform=t["platform"],
            status=t["status"],
            created_at=t["created_at"],
            metadata=t.get("metadata"),
            favorite=t.get("favorite", False),
            progress=t.get("progress") or 0,
        )
        for t in tasks
    ]

    # Determine group status
    statuses = [t["status"] for t in tasks]
    if all(s == "done" for s in statuses):
        group_status = "complete"
    elif any(s == "failed" for s in statuses) and not any(s in ("pending", "downloading", "transcribing", "summarizing") for s in statuses):
        group_status = "partial"
    elif any(s in ("pending", "downloading", "transcribing", "summarizing") for s in statuses):
        group_status = "pending"
    else:
        group_status = "partial"

    # Check for synthesis
    synthesis_task = db.get_group_synthesis(group_id)
    synthesis_item = None
    if synthesis_task:
        synthesis_item = TaskListItem(
            task_id=synthesis_task["task_id"],
            url=synthesis_task["url"],
            platform=synthesis_task["platform"],
            status=synthesis_task["status"],
            created_at=synthesis_task["created_at"],
            metadata=synthesis_task.get("metadata"),
            favorite=synthesis_task.get("favorite", False),
            progress=synthesis_task.get("progress") or 0,
        )

    return GroupStatusResponse(
        group_id=group_id,
        status=group_status,
        tasks=task_items,
        synthesis=synthesis_item,
    )


@router.get("/api/tasks", response_model=TaskListResponse)
async def list_tasks():
    tasks = db.list_tasks_light()
    items = [
        TaskListItem(
            task_id=t["task_id"],
            url=t["url"],
            platform=t["platform"],
            status=t["status"],
            created_at=t["created_at"],
            metadata=t.get("metadata"),
            favorite=t.get("favorite", False),
            progress=t.get("progress") or 0,
        )
        for t in tasks
    ]
    return TaskListResponse(tasks=items)


@router.get("/api/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    """Lightweight polling endpoint: returns only status and progress."""
    status = db.get_task_status(task_id)
    if not status:
        raise HTTPException(status_code=404, detail="Task not found")
    return status


@router.get("/api/tasks/{task_id}/stream")
async def stream_task_summary(task_id: str):
    """SSE endpoint: stream summary chunks as they are generated via asyncio.Queue."""
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    q = subscribe(task_id)

    async def event_generator():
        try:
            while True:
                data = await q.get()
                if data.get("done"):
                    yield f"data: {json.dumps(data)}\n\n"
                    break
                yield f"data: {json.dumps(data)}\n\n"
        finally:
            unsubscribe(task_id, q)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/api/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str):
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return TaskDetail(
        task_id=task["task_id"],
        url=task["url"],
        platform=task["platform"],
        status=task["status"],
        summary=task.get("summary"),
        transcript=task.get("transcript"),
        created_at=task["created_at"],
        completed_at=task.get("completed_at"),
        metadata=task.get("metadata"),
        error=task.get("error"),
        favorite=task.get("favorite", False),
        progress=task.get("progress") or 0,
    )


@router.put("/api/tasks/{task_id}/favorite")
async def set_task_favorite(task_id: str, body: FavoriteRequest):
    """Toggle favorite status."""
    _get_task_or_404(task_id)
    db.set_favorite(task_id, body.favorite)
    return {"task_id": task_id, "favorite": body.favorite}


@router.get("/api/storage", response_model=StorageInfo)
async def get_storage():
    return StorageInfo(
        db_size_bytes=db.db_size(),
        cache_size_bytes=cache_size(),
        task_count=db.task_count(),
    )


@router.delete("/api/storage", response_model=StorageCleanupResult)
async def delete_storage(older_than: str | None = Query(None, description="e.g. '7d'")):
    days = None
    if older_than:
        try:
            days = int(older_than.rstrip("d"))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid older_than format, use e.g. '7d'")

    # Exclude active and favorited tasks from cleanup
    exclude = db.get_active_and_favorite_task_ids()
    deleted_files, freed = clean_cache(older_than_days=days, exclude_tasks=exclude)
    deleted_tasks = db.delete_tasks(older_than_days=days, exclude_favorites=True)

    return StorageCleanupResult(
        deleted_files=deleted_files,
        deleted_tasks=deleted_tasks,
        freed_bytes=freed,
    )


# ============================================================
# Granular resource endpoints
# ============================================================

def _get_task_or_404(task_id: str) -> dict:
    task = db.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/api/tasks/{task_id}/metadata")
async def get_task_metadata(task_id: str):
    """Return video metadata only."""
    task = _get_task_or_404(task_id)
    return {
        "task_id": task_id,
        "url": task.get("url"),
        "platform": task.get("platform"),
        "metadata": task.get("metadata", {}),
    }


@router.get("/api/tasks/{task_id}/transcript")
async def get_task_transcript(task_id: str):
    """Return transcript text only."""
    task = _get_task_or_404(task_id)
    transcript = task.get("transcript")
    if not transcript:
        raise HTTPException(status_code=404, detail="Transcript not available")
    return {
        "task_id": task_id,
        "transcript": transcript,
        "length": len(transcript),
    }


@router.get("/api/tasks/{task_id}/summary")
async def get_task_summary(task_id: str):
    """Return summary only."""
    task = _get_task_or_404(task_id)
    summary = task.get("summary")
    if not summary:
        raise HTTPException(status_code=404, detail="Summary not available")
    return {
        "task_id": task_id,
        "summary": summary,
    }


@router.get("/api/tasks/{task_id}/frames")
async def list_task_frames(task_id: str):
    """List all extracted frame images for a task."""
    _get_task_or_404(task_id)
    frames_dir = settings.cache_dir / "frames" / task_id
    if not frames_dir.exists():
        # Also check in the audio dir (frames may be stored alongside video)
        audio_dir = settings.audio_dir / task_id
        frames_dir = audio_dir

    frame_files = sorted(frames_dir.glob("frame_*.jpg")) if frames_dir.exists() else []
    # Also check for any jpg/png in the task directories
    if not frame_files:
        frame_files = sorted(
            list(frames_dir.glob("*.jpg")) + list(frames_dir.glob("*.png"))
        ) if frames_dir.exists() else []

    return {
        "task_id": task_id,
        "count": len(frame_files),
        "frames": [
            {"index": i, "filename": f.name, "size_bytes": f.stat().st_size}
            for i, f in enumerate(frame_files)
        ],
    }


@router.get("/api/tasks/{task_id}/frames/{filename}")
async def get_task_frame(task_id: str, filename: str):
    """Serve a specific frame image."""
    _get_task_or_404(task_id)
    # Prevent path traversal: use only the pure filename
    safe_name = Path(filename).name
    if not safe_name or safe_name != filename or safe_name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid filename")
    # Search in multiple possible locations
    for base in [settings.cache_dir / "frames" / task_id, settings.audio_dir / task_id]:
        frame_path = (base / safe_name).resolve()
        # Ensure resolved path is still under the base directory
        if not str(frame_path).startswith(str(base.resolve())):
            continue
        if frame_path.exists() and frame_path.suffix in (".jpg", ".png", ".jpeg"):
            return FileResponse(frame_path, media_type=f"image/{frame_path.suffix.lstrip('.')}")

    raise HTTPException(status_code=404, detail="Frame not found")


@router.get("/api/tasks/{task_id}/review-doc")
async def get_review_doc(task_id: str):
    """Generate and download a self-contained interactive review HTML document."""
    task = _get_task_or_404(task_id)
    if task.get("status") != "done":
        raise HTTPException(status_code=400, detail="Task is not completed yet")
    if not task.get("summary"):
        raise HTTPException(status_code=404, detail="Summary not available")

    from core.review_doc import encode_frames, generate_review_doc, parse_review_cards

    cards = parse_review_cards(task["summary"])
    metadata = task.get("metadata") or {}
    duration = metadata.get("duration")
    frames = encode_frames(task_id, duration=duration)

    html = generate_review_doc(task, cards, frames)

    return HTMLResponse(
        content=html,
        headers={
            "Content-Disposition": f'attachment; filename="review_{task_id[:8]}.html"'
        },
    )


@router.post("/api/tasks/{task_id}/retry", response_model=TaskResponse, status_code=202)
async def retry_task(task_id: str):
    """Retry a failed task. Resets status and re-runs the pipeline."""
    task = _get_task_or_404(task_id)
    if task["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")

    db.reset_task(task_id)

    # Read original parameters from task metadata
    meta = task.get("metadata") or {}
    language = meta.get("language", "zh")
    content_type = meta.get("content_type", "general")

    submit_pipeline(run_pipeline, task_id, task["url"], language, "openai", "normal", "multimodal")

    return TaskResponse(task_id=task_id, status=TaskStatus.PENDING)


_ACTIVE_STATUSES = {"pending", "downloading", "transcribing", "extracting_frames", "classifying", "summarizing"}


@router.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """Delete a task and its associated files."""
    task = _get_task_or_404(task_id)
    if task["status"] in _ACTIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Cannot delete a task that is still processing")
    video_id = (task.get("metadata") or {}).get("video_id", "")

    # Delete associated files
    deleted_files = 0
    for subdir in [settings.audio_dir / task_id, settings.cache_dir / "frames" / task_id]:
        if subdir.exists():
            for f in subdir.iterdir():
                f.unlink(missing_ok=True)
            subdir.rmdir()
            deleted_files += 1

    transcript_path = settings.transcript_dir / f"{task_id}.txt"
    if transcript_path.exists():
        transcript_path.unlink()
        deleted_files += 1

    # Delete from DB
    db.delete_task(task_id)

    return {"task_id": task_id, "deleted_files": deleted_files}


# ============================================================
# Prompt management endpoints
# ============================================================

@router.get("/api/prompts")
async def list_prompts():
    """List all customized prompts with their sizes."""
    from core.llm.prompt_store import get_prompt_store
    from core.llm.prompts import CONTENT_TYPES
    store = get_prompt_store()
    return {
        "customized": store.list_prompts(),
        "available_types": sorted(CONTENT_TYPES),
        "available_langs": ["zh", "en"],
    }


@router.get("/api/prompts/classify")
async def get_classify_prompt(lang: str = "zh", multimodal: bool = False):
    """Get the current classify prompt (built-in or customized)."""
    from core.llm.prompts import get_classify_prompt as _get
    return {
        "category": "classify_multimodal" if multimodal else "classify",
        "lang": lang,
        "prompt": _get(lang, multimodal),
    }


@router.put("/api/prompts/classify")
async def set_classify_prompt(body: dict):
    """Set a custom classify prompt. Body: {lang, prompt, multimodal?}"""
    lang = body.get("lang", "zh")
    prompt = body.get("prompt", "")
    multimodal = body.get("multimodal", False)
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    from core.llm.prompt_store import get_prompt_store
    get_prompt_store().set_classify(lang, prompt.strip(), multimodal)
    return {"status": "ok", "category": "classify_multimodal" if multimodal else "classify", "lang": lang}


@router.delete("/api/prompts/classify")
async def reset_classify_prompt(lang: str = "zh", multimodal: bool = False):
    """Reset classify prompt to built-in default."""
    from core.llm.prompt_store import get_prompt_store
    category = "classify_multimodal" if multimodal else "classify"
    get_prompt_store().reset(category=category, lang=lang)
    return {"status": "reset", "category": category, "lang": lang}


@router.get("/api/prompts/summary/{content_type}")
async def get_summary_prompt(content_type: str, lang: str = "zh"):
    """Get the current summary prompt for a content type."""
    from core.llm.prompts import get_summary_prompt as _get, CONTENT_TYPES
    if content_type not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {content_type}")
    return {
        "content_type": content_type,
        "lang": lang,
        "prompt": _get(content_type, lang, multimodal=False),
    }


@router.put("/api/prompts/summary/{content_type}")
async def set_summary_prompt(content_type: str, body: dict):
    """Set a custom summary prompt. Body: {lang, prompt}"""
    from core.llm.prompts import CONTENT_TYPES
    if content_type not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {content_type}")
    lang = body.get("lang", "zh")
    prompt = body.get("prompt", "")
    if not prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")
    from core.llm.prompt_store import get_prompt_store
    get_prompt_store().set_summary(content_type, lang, prompt.strip())
    return {"status": "ok", "content_type": content_type, "lang": lang}


@router.delete("/api/prompts/summary/{content_type}")
async def reset_summary_prompt(content_type: str, lang: str = "zh"):
    """Reset summary prompt to built-in default."""
    from core.llm.prompts import CONTENT_TYPES
    if content_type not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown content type: {content_type}")
    from core.llm.prompt_store import get_prompt_store
    get_prompt_store().reset(category="summary", content_type=content_type, lang=lang)
    return {"status": "reset", "content_type": content_type, "lang": lang}


# ============================================================
# Cookies management endpoints
# ============================================================

@router.get("/api/settings/cookies")
async def get_cookies_status():
    """Check Bilibili cookies validity."""
    from core.platforms.bilibili import BilibiliPlatform
    status = BilibiliPlatform.check_cookies()
    return {
        "status": status,
        "path": str(settings.cookies_path),
        "exists": settings.cookies_path.is_file(),
    }


@router.put("/api/settings/cookies")
async def update_cookies(body: dict):
    """Update Bilibili cookies file. Body: {"cookies": "...Netscape format..."}"""
    cookies = body.get("cookies", "").strip()
    if not cookies:
        raise HTTPException(status_code=400, detail="Cookies content cannot be empty")
    # Basic Netscape format validation
    lines = cookies.split("\n")
    has_domain = any(".bilibili.com" in line for line in lines)
    if not has_domain:
        raise HTTPException(status_code=400, detail="Invalid cookies format: missing .bilibili.com domain")

    settings.cookies_path.parent.mkdir(parents=True, exist_ok=True)
    settings.cookies_path.write_text(cookies, encoding="utf-8")

    # Verify the new cookies
    from core.platforms.bilibili import BilibiliPlatform
    status = BilibiliPlatform.check_cookies()
    return {"status": status, "message": "Cookies updated"}


@router.get("/api/metrics")
async def prometheus_metrics():
    """Return Prometheus-compatible metrics."""
    from core.observability.metrics import metrics_text
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=metrics_text(), media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/api/tasks/{task_id}/evidence")
async def get_task_evidence(task_id: str):
    """Return the evidence chain for a task."""
    _get_task_or_404(task_id)
    from core.observability.evidence import get_evidence
    return {"task_id": task_id, "evidence": get_evidence(task_id)}


# ============================================================
# GitHub Pages publish endpoints
# ============================================================

@router.get("/api/publish/status")
async def publish_status():
    """Return publish configuration status."""
    from core.github.publisher import get_publish_status
    from core.storage.db import get_storage
    status = get_publish_status()
    # Count published tasks
    storage = get_storage()
    tasks = storage.list_tasks_light()
    published_count = sum(1 for t in tasks if (t.get("metadata") or {}).get("publish_url"))
    status["published_count"] = published_count
    return status


@router.post("/api/publish", status_code=200)
async def publish_reviews(body: dict):
    """Publish review docs to GitHub Pages. Body: { task_ids: [...] }"""
    task_ids = body.get("task_ids", [])
    if not task_ids:
        raise HTTPException(status_code=400, detail="task_ids is required")

    from core.github.publisher import PublishError, publish_reviews as _publish
    try:
        result = _publish(task_ids)
    except PublishError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.delete("/api/publish/{task_id}")
async def unpublish_review(task_id: str):
    """Remove a published review from GitHub Pages."""
    from core.github.publisher import PublishError, unpublish_review as _unpublish
    try:
        result = _unpublish(task_id)
    except PublishError as e:
        status = 404 if "never published" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))
    return result
