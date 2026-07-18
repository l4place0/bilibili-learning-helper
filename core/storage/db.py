import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.config import settings

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id      TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    platform     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',
    summary      TEXT,
    transcript   TEXT,
    metadata     TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    completed_at TEXT,
    favorite     INTEGER NOT NULL DEFAULT 0
);
"""

_MIGRATE_ADD_FAVORITE = "ALTER TABLE tasks ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0"
_MIGRATE_ADD_PROGRESS = "ALTER TABLE tasks ADD COLUMN progress INTEGER"
_MIGRATE_ADD_VIDEO_ID = "ALTER TABLE tasks ADD COLUMN video_id TEXT"
_CREATE_VIDEO_ID_INDEX = "CREATE INDEX IF NOT EXISTS idx_tasks_video_id ON tasks(video_id)"
_CREATE_CREATED_AT_INDEX = "CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC)"

ALLOWED_COLUMNS = frozenset({
    "url", "platform", "status", "summary", "transcript",
    "metadata", "error", "created_at", "completed_at",
    "favorite", "progress",
})


_write_lock = threading.Lock()


class Storage:
    """Thread-safe SQLite storage backend for pipeline tasks.

    Provides CRUD operations on the ``tasks`` table with automatic JSON
    serialization for metadata, column-whitelist validation on updates, and
    schema migration for new columns. All write operations are serialized
    through a module-level threading lock. The connection uses WAL journal
    mode for concurrent read access.

    Typically obtained via the ``get_storage()`` singleton factory rather
    than instantiated directly.
    """

    def __init__(self, db_path: Path | None = None):
        """Initialize the storage backend and ensure the schema is up to date.

        Args:
            db_path: Path to the SQLite database file. Defaults to
                     ``settings.db_path`` (``data/db.sqlite3``).
        """
        self.db_path = db_path or settings.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add missing columns to existing tables."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "favorite" not in cols:
            self._conn.execute(_MIGRATE_ADD_FAVORITE)
            self._conn.commit()
        if "progress" not in cols:
            self._conn.execute(_MIGRATE_ADD_PROGRESS)
            self._conn.commit()
        if "video_id" not in cols:
            self._conn.execute(_MIGRATE_ADD_VIDEO_ID)
            self._conn.commit()
            self._backfill_video_id()
        self._conn.execute(_CREATE_VIDEO_ID_INDEX)
        self._conn.execute(_CREATE_CREATED_AT_INDEX)
        self._conn.commit()

    def _backfill_video_id(self) -> None:
        """Extract video_id from metadata JSON for existing rows."""
        rows = self._conn.execute("SELECT task_id, metadata FROM tasks WHERE metadata IS NOT NULL").fetchall()
        for row in rows:
            try:
                meta = json.loads(row[1])
                vid = meta.get("video_id")
                if vid:
                    self._conn.execute("UPDATE tasks SET video_id = ? WHERE task_id = ?", (vid, row[0]))
            except (json.JSONDecodeError, KeyError):
                continue
        self._conn.commit()

    def create_task(self, url: str, platform: str) -> str:
        """Create a new task in pending state.

        Args:
            url: Source video URL.
            platform: Platform identifier (e.g. "bilibili", "youtube", "synthesis").

        Returns:
            The generated UUID string for the new task.
        """
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with _write_lock:
            self._conn.execute(
                "INSERT INTO tasks (task_id, url, platform, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                (task_id, url, platform, now),
            )
            self._conn.commit()
        return task_id

    def update_task(self, task_id: str, **fields) -> None:
        """Update one or more columns on an existing task.

        Column names are validated against ``ALLOWED_COLUMNS``. Dict and list
        values are automatically serialized to JSON. If ``metadata`` contains
        a ``video_id`` key, it is also written to the dedicated ``video_id``
        column for indexing.

        Args:
            task_id: UUID of the task to update.
            **fields: Column name/value pairs to set.

        Raises:
            ValueError: If any field name is not in ``ALLOWED_COLUMNS``.
        """
        if not fields:
            return
        # Validate column names against whitelist
        invalid = set(fields.keys()) - ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column names: {invalid}")
        # Auto-extract video_id from metadata if present
        meta = fields.get("metadata")
        if isinstance(meta, dict) and "video_id" in meta:
            fields["video_id"] = meta["video_id"]
        # Serialize dicts/lists to JSON for SQLite
        for k, v in fields.items():
            if isinstance(v, (dict, list)):
                fields[k] = json.dumps(v, ensure_ascii=False)
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values())
        vals.append(task_id)
        with _write_lock:
            self._conn.execute(f"UPDATE tasks SET {sets} WHERE task_id = ?", vals)
            self._conn.commit()

    def get_task(self, task_id: str) -> dict | None:
        """Retrieve a single task by ID with all columns.

        Args:
            task_id: UUID of the task.

        Returns:
            A dict with all task columns (metadata deserialized from JSON,
            favorite converted to bool), or None if not found.
        """
        row = self._conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_tasks(self, limit: int = 50) -> list[dict]:
        """List recent tasks with all columns.

        Args:
            limit: Maximum number of tasks to return (default 50).

        Returns:
            List of task dicts ordered by creation time (newest first).
        """
        rows = self._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_tasks_light(self, limit: int = 50) -> list[dict]:
        """List recent tasks without heavy fields (transcript, summary, error).

        Optimized for history/list views where only metadata and status are
        needed. Omits the large text columns to reduce memory and transfer.

        Args:
            limit: Maximum number of tasks to return (default 50).

        Returns:
            List of task dicts ordered by creation time (newest first).
        """
        rows = self._conn.execute(
            "SELECT task_id, url, platform, status, created_at, favorite, progress, metadata "
            "FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if d.get("metadata"):
                d["metadata"] = json.loads(d["metadata"])
            d["favorite"] = bool(d.get("favorite", 0))
            result.append(d)
        return result

    def get_task_status(self, task_id: str) -> dict | None:
        """Return only status and progress for a task (lightweight polling).

        Args:
            task_id: UUID of the task.

        Returns:
            A dict with ``task_id``, ``status``, and ``progress`` keys,
            or None if the task does not exist.
        """
        row = self._conn.execute(
            "SELECT task_id, status, progress FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return {"task_id": row[0], "status": row[1], "progress": row[2] or 0}

    def delete_task(self, task_id: str) -> bool:
        """Delete a single task by ID.

        Args:
            task_id: UUID of the task to delete.

        Returns:
            True if a row was deleted, False if no matching task existed.
        """
        with _write_lock:
            cur = self._conn.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def delete_tasks(self, older_than_days: int | None = None, exclude_favorites: bool = False) -> int:
        """Bulk-delete tasks with optional age and favorite filters.

        Args:
            older_than_days: Only delete tasks created more than this many days
                ago. If None, no age filter is applied.
            exclude_favorites: If True, skip tasks marked as favorite.

        Returns:
            Number of tasks deleted.
        """
        with _write_lock:
            if older_than_days is not None:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
                if exclude_favorites:
                    cur = self._conn.execute("DELETE FROM tasks WHERE created_at < ? AND favorite = 0", (cutoff,))
                else:
                    cur = self._conn.execute("DELETE FROM tasks WHERE created_at < ?", (cutoff,))
            else:
                if exclude_favorites:
                    cur = self._conn.execute("DELETE FROM tasks WHERE favorite = 0")
                else:
                    cur = self._conn.execute("DELETE FROM tasks")
            self._conn.commit()
        return cur.rowcount

    def set_favorite(self, task_id: str, favorite: bool) -> bool:
        """Set or unset the favorite flag on a task.

        Args:
            task_id: UUID of the task.
            favorite: True to mark as favorite, False to unmark.

        Returns:
            True if the task was updated, False if not found.
        """
        with _write_lock:
            cur = self._conn.execute("UPDATE tasks SET favorite = ? WHERE task_id = ?", (1 if favorite else 0, task_id))
            self._conn.commit()
        return cur.rowcount > 0

    def reset_task(self, task_id: str) -> bool:
        """Reset a failed task for retry.

        Clears summary, transcript, error, and completed_at fields, then sets
        status back to ``pending`` so the pipeline can re-process it.

        Args:
            task_id: UUID of the task to reset.

        Returns:
            True if the task was updated, False if not found.
        """
        with _write_lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status = 'pending', summary = NULL, transcript = NULL, "
                "error = NULL, completed_at = NULL WHERE task_id = ?",
                (task_id,),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def get_active_and_favorite_task_ids(self) -> set[str]:
        """Return task IDs that are either actively processing or favorited.

        Used by cleanup routines to protect in-progress and pinned tasks from
        deletion.

        Returns:
            Set of task_id strings.
        """
        rows = self._conn.execute(
            "SELECT task_id FROM tasks WHERE favorite = 1 OR status IN "
            "('pending', 'downloading', 'transcribing', 'extracting_frames', 'classifying', 'summarizing')"
        ).fetchall()
        return {row[0] for row in rows}

    def auto_cleanup(self, days: int | None = None) -> int:
        """Delete non-favorite tasks older than the given retention period.

        Called during application startup to purge expired tasks.

        Args:
            days: Retention period in days. Defaults to
                  ``settings.auto_cleanup_days``.

        Returns:
            Number of tasks deleted.
        """
        if days is None:
            days = settings.auto_cleanup_days
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with _write_lock:
            cur = self._conn.execute("DELETE FROM tasks WHERE created_at < ? AND favorite = 0", (cutoff,))
            self._conn.commit()
            deleted = cur.rowcount
        if deleted:
            logging.getLogger(__name__).info("Auto-cleanup: deleted %d tasks older than %d days", deleted, days)
        return deleted

    def find_cached_task(self, video_id: str) -> dict | None:
        """Find the most recent completed task with the given video_id.

        Used by the pipeline's cache layer to avoid re-downloading and
        re-transcribing a video that was already processed.

        Args:
            video_id: Platform-specific video identifier (e.g. BV号 for Bilibili).

        Returns:
            The task dict of the most recent matching ``done`` task, or None.
        """
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE status = 'done' AND video_id = ? ORDER BY created_at DESC LIMIT 1",
            (video_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def get_tasks_by_group(self, group_id: str) -> list[dict]:
        """Find all tasks belonging to a group.

        Group membership is stored in the ``metadata`` JSON under the
        ``group_id`` key and queried via ``json_extract``.

        Args:
            group_id: The group identifier string.

        Returns:
            List of task dicts ordered by creation time, or empty list.
        """
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE json_extract(metadata, '$.group_id') = ? ORDER BY created_at",
            (group_id,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_group_synthesis(self, group_id: str) -> dict | None:
        """Find the synthesis task for a group.

        Synthesis tasks are created when all individual tasks in a group
        complete, combining their summaries into a unified analysis.

        Args:
            group_id: The group identifier string.

        Returns:
            The synthesis task dict, or None if not yet created.
        """
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE json_extract(metadata, '$.synthesis_for') = ? LIMIT 1",
            (group_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def task_count(self) -> int:
        """Return the total number of tasks in the database."""
        return self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    def db_size(self) -> int:
        """Return the size of the SQLite database file in bytes."""
        return self.db_path.stat().st_size if self.db_path.exists() else 0

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("metadata"):
            d["metadata"] = json.loads(d["metadata"])
        d["favorite"] = bool(d.get("favorite", 0))
        return d


# Singleton — all callers share one Storage instance (and one connection)
_instance: Storage | None = None
_init_lock = threading.Lock()


def get_storage() -> Storage:
    global _instance
    if _instance is None:
        with _init_lock:
            if _instance is None:
                _instance = Storage()
    return _instance
