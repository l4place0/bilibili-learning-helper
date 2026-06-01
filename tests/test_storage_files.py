"""Tests for storage file operations and extended storage features."""
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.storage.files import (
    cache_size,
    clean_cache,
    clean_all,
    _should_exclude,
    _clean_dir_by_age,
    auto_clean_cache,
)
from core.storage.db import Storage


class TestShouldExclude:
    def test_empty_excludes(self):
        assert _should_exclude(Path("data/cache/audio/task1/file.wav"), set()) is False

    def test_matching_task_id(self):
        assert _should_exclude(Path("data/cache/audio/task123/file.wav"), {"task123"}) is True

    def test_non_matching(self):
        assert _should_exclude(Path("data/cache/audio/task456/file.wav"), {"task123"}) is False

    def test_nested_path(self):
        assert _should_exclude(Path("a/b/task_id/c/file.txt"), {"task_id"}) is True


class TestCacheOperations:
    def test_cache_size_empty(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.cache_dir = tmp_path / "cache"
            mock_s.cache_dir.mkdir()
            assert cache_size() == 0

    def test_cache_size_with_files(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.cache_dir = tmp_path / "cache"
            mock_s.cache_dir.mkdir()
            (mock_s.cache_dir / "file.txt").write_bytes(b"x" * 100)
            assert cache_size() == 100

    def test_clean_cache_empty(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.cache_dir = tmp_path / "cache"
            mock_s.cache_dir.mkdir()
            deleted, freed = clean_cache()
            assert deleted == 0
            assert freed == 0

    def test_clean_cache_removes_old_files(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.cache_dir = tmp_path / "cache"
            mock_s.cache_dir.mkdir()
            old_file = mock_s.cache_dir / "old.txt"
            old_file.write_bytes(b"data")
            # Set mtime to 10 days ago
            old_time = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
            old_file.touch()
            import os
            os.utime(old_file, (old_time, old_time))

            deleted, freed = clean_cache(older_than_days=7)
            assert deleted == 1
            assert not old_file.exists()

    def test_clean_cache_preserves_excluded(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.cache_dir = tmp_path / "cache"
            task_dir = mock_s.cache_dir / "audio" / "task1"
            task_dir.mkdir(parents=True)
            task_file = task_dir / "audio.wav"
            task_file.write_bytes(b"data")

            deleted, freed = clean_cache(exclude_tasks={"task1"})
            assert deleted == 0
            assert task_file.exists()

    def test_clean_all(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.cache_dir = tmp_path / "cache"
            mock_s.cache_dir.mkdir()
            (mock_s.cache_dir / "file.txt").write_bytes(b"data")
            deleted, freed = clean_all()
            assert deleted == 1


class TestCleanDirByAge:
    def test_removes_old_files(self, tmp_path):
        old_file = tmp_path / "old.txt"
        old_file.write_bytes(b"data")
        import os
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
        os.utime(old_file, (old_time, old_time))

        deleted, freed = _clean_dir_by_age(tmp_path, max_age_days=7)
        assert deleted == 1
        assert not old_file.exists()

    def test_preserves_new_files(self, tmp_path):
        new_file = tmp_path / "new.txt"
        new_file.write_bytes(b"data")
        deleted, freed = _clean_dir_by_age(tmp_path, max_age_days=7)
        assert deleted == 0
        assert new_file.exists()

    def test_removes_empty_dirs(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        old_file = sub / "old.txt"
        old_file.write_bytes(b"data")
        import os
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
        os.utime(old_file, (old_time, old_time))

        _clean_dir_by_age(tmp_path, max_age_days=7)
        assert not sub.exists()

    def test_nonexistent_dir(self, tmp_path):
        deleted, freed = _clean_dir_by_age(tmp_path / "nope", max_age_days=7)
        assert deleted == 0


class TestAutoCleanCache:
    def test_cleans_audio_and_data(self, tmp_path):
        with patch("core.storage.files.settings") as mock_s:
            mock_s.audio_dir = tmp_path / "audio"
            mock_s.transcript_dir = tmp_path / "transcripts"
            mock_s.frames_dir = tmp_path / "frames"
            for d in [mock_s.audio_dir, mock_s.transcript_dir, mock_s.frames_dir]:
                d.mkdir(parents=True)
                old = d / "old.txt"
                old.write_bytes(b"data")
                import os
                old_time = (datetime.now(timezone.utc) - timedelta(days=10)).timestamp()
                os.utime(old, (old_time, old_time))

            total_deleted, total_freed = auto_clean_cache(video_days=1, data_days=7)
            assert total_deleted == 3


class TestStorageExtended:
    def test_find_cached_task(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        task_id = db.create_task("https://bilibili.com/video/BV123", "bilibili")
        db.update_task(task_id, status="done", metadata={"video_id": "BV123"})

        cached = db.find_cached_task("BV123")
        assert cached is not None
        assert cached["task_id"] == task_id

    def test_find_cached_task_miss(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        assert db.find_cached_task("nonexist") is None

    def test_set_favorite(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        task_id = db.create_task("url", "bilibili")
        assert db.set_favorite(task_id, True) is True
        task = db.get_task(task_id)
        assert task["favorite"] is True

    def test_reset_task(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        task_id = db.create_task("url", "bilibili")
        db.update_task(task_id, status="failed", error="oops")
        assert db.reset_task(task_id) is True
        task = db.get_task(task_id)
        assert task["status"] == "pending"
        assert task["error"] is None

    def test_get_active_and_favorite(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        t1 = db.create_task("url1", "bilibili")
        t2 = db.create_task("url2", "bilibili")
        db.update_task(t1, status="transcribing")
        db.set_favorite(t2, True)

        ids = db.get_active_and_favorite_task_ids()
        assert t1 in ids
        assert t2 in ids

    def test_auto_cleanup(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        old = db.create_task("url", "bilibili")
        # Set created_at to 10 days ago
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        db._conn.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (old_time, old))
        db._conn.commit()

        deleted = db.auto_cleanup(days=7)
        assert deleted == 1
        assert db.get_task(old) is None

    def test_auto_cleanup_preserves_favorites(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        fav = db.create_task("url", "bilibili")
        db.set_favorite(fav, True)
        old_time = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        db._conn.execute("UPDATE tasks SET created_at = ? WHERE task_id = ?", (old_time, fav))
        db._conn.commit()

        deleted = db.auto_cleanup(days=7)
        assert deleted == 0
        assert db.get_task(fav) is not None

    def test_task_count(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        assert db.task_count() == 0
        db.create_task("url1", "bilibili")
        assert db.task_count() == 1

    def test_list_tasks_light(self, tmp_path):
        db = Storage(db_path=tmp_path / "test.db")
        db.create_task("url1", "bilibili")
        tasks = db.list_tasks_light()
        assert len(tasks) == 1
        # Light listing should not include transcript or summary
        assert "transcript" not in tasks[0]
        assert "summary" not in tasks[0]
