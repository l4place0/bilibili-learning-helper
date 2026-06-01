"""CLI subcommands for video-sum."""

import atexit
import logging
import socket
import sys
import threading
import time

import click
import httpx

from cli.output import emit, emit_error

# Redirect all logging to stderr so stdout stays clean JSON
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")

# Server lifecycle
_server = None


def _free_port() -> int:
    """Find a free TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int):
    """Start FastAPI app in a background thread. Returns the thread."""
    global _server
    from core.main import app
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    _server = server
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Register cleanup
    atexit.register(lambda: setattr(server, "should_exit", True))

    # Wait for server to be ready
    url = f"http://127.0.0.1:{port}"
    for _ in range(30):
        try:
            httpx.get(f"{url}/health", timeout=2)
            return thread
        except httpx.ConnectError:
            time.sleep(0.5)
    emit_error(f"Server failed to start on {url}")


def _create_progress():
    """Create a Rich progress bar if available, else None."""
    try:
        from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
        return Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            file=sys.stderr,  # Keep stdout clean
        )
    except ImportError:
        return None


@click.command()
@click.argument("url")
@click.option("--lang", default="zh", help="Language (zh/en/ja)")
@click.option("--provider", default="openai", help="LLM provider (openai/claude)")
@click.option("--detail", default="normal", help="Detail level (brief/normal/detailed)")
@click.option("--mode", default="multimodal", help="Mode (multimodal/audio)")
@click.option("--remote", default="", help="Remote server URL (e.g. http://localhost:8000)")
@click.option("--port", default=0, help="Local server port (0 = auto)")
@click.option("--timeout", default=300, type=int, help="Timeout in seconds (default: 300)")
def run(url, lang, provider, detail, mode, remote, port, timeout):
    """Summarize a video URL. Emits JSON events to stdout."""
    if remote:
        _run_remote(url, lang, provider, detail, mode, remote, timeout)
    else:
        # Start embedded server
        port = port or _free_port()
        _start_server(port)
        _run_remote(url, lang, provider, detail, mode, f"http://127.0.0.1:{port}", timeout)


@click.command()
@click.option("--port", default=8000, help="Server port")
@click.option("--host", default="0.0.0.0", help="Server host")
def serve(port, host):
    """Start the web server (foreground)."""
    import uvicorn
    from core.main import app

    uvicorn.run(app, host=host, port=port)


@click.command()
@click.argument("url")
@click.option("--lang", default="zh")
@click.option("--provider", default="openai")
@click.option("--detail", default="normal")
@click.option("--mode", default="multimodal")
@click.option("--remote", default="", help="Remote server URL")
def submit(url, lang, provider, detail, mode, remote):
    """Submit a video URL for summarization. Returns task_id."""
    server = remote or "http://localhost:8000"
    try:
        resp = httpx.post(f"{server}/api/summarize", json={
            "url": url, "language": lang, "llm_provider": provider,
            "detail": detail, "mode": mode,
        }, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        emit("submitted", task_id=data["task_id"], status=data["status"])
    except httpx.HTTPStatusError as e:
        emit_error(f"Server error: {e.response.status_code} {e.response.text}")
    except httpx.ConnectError:
        emit_error(f"Cannot connect to {server}. Is the server running?")


@click.command()
@click.argument("task_id")
@click.option("--remote", default="", help="Remote server URL")
def status(task_id, remote):
    """Query task status."""
    server = remote or "http://localhost:8000"
    try:
        resp = httpx.get(f"{server}/api/tasks/{task_id}/status", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        emit("status", **data)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            emit_error(f"Task not found: {task_id}")
        else:
            emit_error(f"Server error: {e.response.status_code}")
    except httpx.ConnectError:
        emit_error(f"Cannot connect to {server}")


@click.command()
@click.argument("task_id")
@click.option("--remote", default="", help="Remote server URL")
def result(task_id, remote):
    """Get full task result."""
    server = remote or "http://localhost:8000"
    try:
        resp = httpx.get(f"{server}/api/tasks/{task_id}", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        emit("result", **data)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            emit_error(f"Task not found: {task_id}")
        else:
            emit_error(f"Server error: {e.response.status_code}")
    except httpx.ConnectError:
        emit_error(f"Cannot connect to {server}")


def _run_remote(url, lang, provider, detail, mode, server, timeout=300):
    """Submit → poll → result with timeout."""
    try:
        # Submit
        emit("submitting", url=url)
        resp = httpx.post(f"{server}/api/summarize", json={
            "url": url, "language": lang, "llm_provider": provider,
            "detail": detail, "mode": mode,
        }, timeout=30)
        resp.raise_for_status()
        task_id = resp.json()["task_id"]
        emit("submitted", task_id=task_id)

        # Poll with timeout
        progress = _create_progress()
        deadline = time.monotonic() + timeout

        if progress:
            with progress:
                task = progress.add_task("Processing...", total=100)
                while time.monotonic() < deadline:
                    time.sleep(2)
                    data = _poll_status(server, task_id)
                    if data is None:
                        continue
                    progress.update(task, completed=data.get("progress", 0))
                    emit("progress", status=data["status"], progress=data.get("progress", 0))

                    if data["status"] == "done":
                        _emit_result(server, task_id)
                        return
                    elif data["status"] == "failed":
                        emit_error(f"Task failed: {data.get('error', 'unknown')}")
        else:
            while time.monotonic() < deadline:
                time.sleep(2)
                data = _poll_status(server, task_id)
                if data is None:
                    continue
                emit("progress", status=data["status"], progress=data.get("progress", 0))

                if data["status"] == "done":
                    _emit_result(server, task_id)
                    return
                elif data["status"] == "failed":
                    emit_error(f"Task failed: {data.get('error', 'unknown')}")

        emit_error(f"Timed out after {timeout}s")

    except httpx.ConnectError:
        emit_error(f"Cannot connect to {server}")
    except httpx.HTTPStatusError as e:
        emit_error(f"Server error: {e.response.status_code}")


def _poll_status(server, task_id):
    """Poll task status. Returns data dict or None on transient error."""
    try:
        status_resp = httpx.get(f"{server}/api/tasks/{task_id}/status", timeout=10)
        status_resp.raise_for_status()
        return status_resp.json()
    except (httpx.ConnectError, httpx.HTTPStatusError):
        return None


def _emit_result(server, task_id):
    """Fetch and emit full task result."""
    result_resp = httpx.get(f"{server}/api/tasks/{task_id}", timeout=10)
    result_resp.raise_for_status()
    full = result_resp.json()
    emit("done", summary=full.get("summary", ""),
         transcript=full.get("transcript", ""),
         metadata=full.get("metadata", {}))
