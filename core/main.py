import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core.api.routes import router
from core.config import settings
from core.storage.db import get_storage
from core.storage.files import auto_clean_cache
from core.workers import shutdown_workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    logger = logging.getLogger(__name__)
    # Auto-cleanup: DB tasks (favorites preserved)
    storage = get_storage()
    deleted_tasks = storage.auto_cleanup()
    if deleted_tasks:
        logger.info("Startup auto-cleanup: removed %d expired tasks", deleted_tasks)
    # Auto-cleanup: video/audio after 1 day, transcripts/frames after 7 days
    exclude = storage.get_active_and_favorite_task_ids()
    deleted_files, freed = auto_clean_cache(video_days=1, data_days=7, exclude_tasks=exclude)
    if deleted_files:
        logger.info("Startup cache cleanup: removed %d files, freed %.1f MB", deleted_files, freed / 1024 / 1024)
    yield
    # Shutdown: drain pipeline thread pool
    shutdown_workers()
    logger.info("Pipeline workers shut down")


app = FastAPI(title="Video Summarizer", version="0.1.0", lifespan=lifespan)
app.include_router(router)

# Static files mounted AFTER API routes to avoid overriding /api/* and /health
web_dir = Path(__file__).parent / "web"
app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("core.main:app", host=settings.host, port=settings.port, reload=True)
