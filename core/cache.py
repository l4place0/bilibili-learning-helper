"""Content-addressed user cache for the lightweight ingestion CLI."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


CACHE_SCHEMA_VERSION = 1


def stable_key(namespace: str, **values: Any) -> str:
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "namespace": namespace,
        **values,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def media_key(
    platform: str,
    video_id: str,
    *,
    quality: str = "720p",
    media_format: str = "dash",
) -> str:
    return stable_key(
        "media",
        platform=platform,
        video_id=video_id,
        quality=quality,
        format=media_format,
    )


def derived_key(parent_key: str, artifact: str, **parameters: Any) -> str:
    return stable_key(
        artifact,
        parent_key=parent_key,
        parameters=parameters,
    )


@dataclass(frozen=True)
class CacheEntry:
    key: str
    kind: str
    path: Path
    size: int
    last_access: float
    expiry: float
    state: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["path"] = str(self.path)
        return result


class CacheStore:
    """SQLite-indexed object cache with atomic staging commits."""

    DEFAULT_TTL = {
        "media": 7 * 86400,
        "audio": 14 * 86400,
        "transcript": 90 * 86400,
        "frames": 30 * 86400,
        "metadata": 7 * 86400,
    }

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.objects = self.root / "objects"
        self.staging = self.root / "staging"
        self.locks = self.root / "locks"
        self.db_path = self.root / "cache.db"
        for directory in (self.objects, self.staging, self.locks):
            directory.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS objects (
                    key TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    last_access REAL NOT NULL,
                    expiry REAL NOT NULL,
                    state TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )

    def _target(self, key: str) -> Path:
        return self.objects / key[:2] / key

    @staticmethod
    def _size(path: Path) -> int:
        if path.is_file():
            return path.stat().st_size
        return sum(
            item.stat().st_size for item in path.rglob("*") if item.is_file()
        )

    def get(self, key: str) -> CacheEntry | None:
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM objects WHERE key = ? AND state = 'ready'",
                (key,),
            ).fetchone()
            if not row:
                return None
            path = self.root / row["relative_path"]
            if row["expiry"] < now or not path.exists():
                connection.execute("DELETE FROM objects WHERE key = ?", (key,))
                return None
            connection.execute(
                "UPDATE objects SET last_access = ? WHERE key = ?",
                (now, key),
            )
        return CacheEntry(
            key=key,
            kind=row["kind"],
            path=path,
            size=row["size"],
            last_access=now,
            expiry=row["expiry"],
            state=row["state"],
            metadata=json.loads(row["metadata"]),
        )

    def put_path(
        self,
        key: str,
        kind: str,
        source: Path,
        *,
        metadata: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
    ) -> CacheEntry:
        target = self._target(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=f"{key[:12]}-", dir=self.staging))
        staged_object = stage / "object"
        if source.is_dir():
            shutil.copytree(source, staged_object)
        else:
            staged_object.mkdir()
            shutil.copy2(source, staged_object / source.name)
        if target.exists():
            shutil.rmtree(target)
        os.replace(staged_object, target)
        shutil.rmtree(stage, ignore_errors=True)

        now = time.time()
        ttl = ttl_seconds or self.DEFAULT_TTL.get(kind, 7 * 86400)
        size = self._size(target)
        relative = target.relative_to(self.root).as_posix()
        encoded_metadata = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO objects
                (key, kind, relative_path, size, last_access, expiry, state, metadata)
                VALUES (?, ?, ?, ?, ?, ?, 'ready', ?)
                """,
                (
                    key,
                    kind,
                    relative,
                    size,
                    now,
                    now + ttl,
                    encoded_metadata,
                ),
            )
        self.prune()
        return self.get(key)  # type: ignore[return-value]

    def put_json(
        self,
        key: str,
        kind: str,
        payload: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> CacheEntry:
        with tempfile.TemporaryDirectory(prefix="video-sum-cache-json-") as tmp:
            source = Path(tmp) / "data.json"
            source.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
            return self.put_path(
                key,
                kind,
                source,
                ttl_seconds=ttl_seconds,
            )

    @staticmethod
    def first_file(entry: CacheEntry) -> Path:
        files = sorted(path for path in entry.path.iterdir() if path.is_file())
        if not files:
            raise FileNotFoundError(f"Cache object is empty: {entry.key}")
        return files[0]

    def read_json(self, key: str) -> Any | None:
        entry = self.get(key)
        if not entry:
            return None
        return json.loads(self.first_file(entry).read_text(encoding="utf-8"))

    def materialize_file(self, entry: CacheEntry, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.first_file(entry), destination)
        return destination

    def materialize_directory(
        self, entry: CacheEntry, destination: Path
    ) -> list[Path]:
        destination.mkdir(parents=True, exist_ok=True)
        paths = []
        for source in sorted(entry.path.iterdir()):
            if source.is_file():
                target = destination / source.name
                shutil.copy2(source, target)
                paths.append(target)
        return paths

    def list(self, kind: str = "") -> list[CacheEntry]:
        query = "SELECT * FROM objects"
        params: tuple[str, ...] = ()
        if kind:
            query += " WHERE kind = ?"
            params = (kind,)
        query += " ORDER BY last_access DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        entries = []
        for row in rows:
            path = self.root / row["relative_path"]
            if path.exists():
                entries.append(
                    CacheEntry(
                        key=row["key"],
                        kind=row["kind"],
                        path=path,
                        size=row["size"],
                        last_access=row["last_access"],
                        expiry=row["expiry"],
                        state=row["state"],
                        metadata=json.loads(row["metadata"]),
                    )
                )
        return entries

    def status(self) -> dict[str, Any]:
        entries = self.list()
        return {
            "root": str(self.root),
            "count": len(entries),
            "size": sum(entry.size for entry in entries),
            "by_kind": {
                kind: sum(1 for entry in entries if entry.kind == kind)
                for kind in sorted({entry.kind for entry in entries})
            },
        }

    def prune(self, max_bytes: int = 5 * 1024**3) -> dict[str, int]:
        entries = sorted(self.list(), key=lambda entry: entry.last_access)
        now = time.time()
        total = sum(entry.size for entry in entries)
        deleted = 0
        freed = 0
        for entry in entries:
            if entry.expiry >= now and total <= max_bytes:
                continue
            shutil.rmtree(entry.path, ignore_errors=True)
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM objects WHERE key = ?", (entry.key,)
                )
            deleted += 1
            freed += entry.size
            total -= entry.size
        return {"deleted": deleted, "freed": freed}

    def clear(self) -> dict[str, int]:
        entries = self.list()
        freed = sum(entry.size for entry in entries)
        for entry in entries:
            shutil.rmtree(entry.path, ignore_errors=True)
        with self._connect() as connection:
            connection.execute("DELETE FROM objects")
        return {"deleted": len(entries), "freed": freed}
