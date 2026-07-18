"""JSONL per-task log writer."""

import json
from pathlib import Path

from core.config import settings


def _get_log_dir() -> Path:
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def write_event(task_id: str, event: dict) -> None:
    """Append a structured event as one JSON line to the task's log file."""
    log_file = _get_log_dir() / f"{task_id}.jsonl"
    line = json.dumps(event, ensure_ascii=False) + "\n"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(line)


def read_events(task_id: str) -> list[dict]:
    """Read all events from a task's log file."""
    log_file = _get_log_dir() / f"{task_id}.jsonl"
    if not log_file.exists():
        return []
    events = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def delete_log(task_id: str) -> bool:
    """Delete a task's log file. Returns True if deleted."""
    log_file = _get_log_dir() / f"{task_id}.jsonl"
    if log_file.exists():
        log_file.unlink()
        return True
    return False
