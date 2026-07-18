"""Evidence chain storage — writes stage events to SQLite."""

import json
import sqlite3
import threading
from pathlib import Path

_evidence_lock = threading.Lock()


def _get_db_path() -> Path:
    from core.config import settings
    return settings.db_path


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            input_summary TEXT,
            output_summary TEXT,
            decisions TEXT,
            warnings TEXT,
            duration_ms INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (task_id) REFERENCES tasks(task_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_evidence_task_id ON evidence(task_id)")
    conn.commit()


def insert_evidence(
    task_id: str,
    stage: str,
    status: str,
    input_summary: dict | None = None,
    output_summary: dict | None = None,
    decisions: list | None = None,
    warnings: list | None = None,
    duration_ms: int = 0,
) -> None:
    """Insert an evidence record."""
    with _evidence_lock:
        conn = sqlite3.connect(str(_get_db_path()))
        try:
            _ensure_table(conn)
            conn.execute(
                "INSERT INTO evidence (task_id, stage, status, input_summary, output_summary, decisions, warnings, duration_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    stage,
                    status,
                    json.dumps(input_summary, ensure_ascii=False) if input_summary else None,
                    json.dumps(output_summary, ensure_ascii=False) if output_summary else None,
                    json.dumps(decisions, ensure_ascii=False) if decisions else None,
                    json.dumps(warnings, ensure_ascii=False) if warnings else None,
                    duration_ms,
                ),
            )
            conn.commit()
        finally:
            conn.close()


def get_evidence(task_id: str) -> list[dict]:
    """Retrieve all evidence records for a task."""
    conn = sqlite3.connect(str(_get_db_path()))
    conn.row_factory = sqlite3.Row
    try:
        _ensure_table(conn)
        rows = conn.execute(
            "SELECT * FROM evidence WHERE task_id = ? ORDER BY created_at", (task_id,)
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            for field in ("input_summary", "output_summary", "decisions", "warnings"):
                if d.get(field):
                    d[field] = json.loads(d[field])
            results.append(d)
        return results
    finally:
        conn.close()
