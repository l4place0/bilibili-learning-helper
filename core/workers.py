"""Thread pool for background pipeline tasks."""

from concurrent.futures import ThreadPoolExecutor
import threading

_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="pipeline")
_shutdown = threading.Event()


def submit_pipeline(fn, *args, **kwargs):
    """Submit a pipeline function to the thread pool. Raises RuntimeError on shutdown."""
    if _shutdown.is_set():
        raise RuntimeError("Server is shutting down")
    return _executor.submit(fn, *args, **kwargs)


def shutdown_workers():
    """Signal shutdown and wait for all running tasks to complete."""
    _shutdown.set()
    _executor.shutdown(wait=True)
