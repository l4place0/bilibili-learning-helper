"""Tests for pipeline internal helpers."""
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.pipeline import (
    MetricsTracker,
    get_stream_chunks,
    _stream_callback,
    _cleanup_stream,
    _build_metadata_context,
    get_platform,
)


class TestMetricsTracker:
    def test_tracks_duration(self):
        tracker = MetricsTracker()
        tracker.start_stage("test")
        time.sleep(0.01)
        tracker.end_stage("test")
        result = tracker.finish()
        assert "test" in result
        assert result["test"]["duration_ms"] >= 0
        assert "total_duration_ms" in result

    def test_extra_fields(self):
        tracker = MetricsTracker()
        tracker.start_stage("download")
        tracker.end_stage("download", file_size_bytes=1024, cached=False)
        result = tracker.finish()
        assert result["download"]["file_size_bytes"] == 1024
        assert result["download"]["cached"] is False

    def test_multiple_stages(self):
        tracker = MetricsTracker()
        tracker.start_stage("a")
        tracker.end_stage("a")
        tracker.start_stage("b")
        tracker.end_stage("b")
        result = tracker.finish()
        assert "a" in result
        assert "b" in result


class TestStreamBuffers:
    def setup_method(self):
        # Clean up any leftover buffers
        from core.pipeline import _stream_buffers
        _stream_buffers.clear()

    def test_callback_accumulates(self):
        _stream_callback("task1", "hello")
        _stream_callback("task1", " world")
        chunks = get_stream_chunks("task1")
        assert chunks == ["hello", " world"]

    def test_get_returns_copy(self):
        _stream_callback("task2", "data")
        chunks1 = get_stream_chunks("task2")
        chunks2 = get_stream_chunks("task2")
        assert chunks1 == chunks2
        assert chunks1 is not chunks2

    def test_cleanup_removes(self):
        _stream_callback("task3", "data")
        _cleanup_stream("task3")
        assert get_stream_chunks("task3") == []

    def test_empty_task(self):
        assert get_stream_chunks("nonexistent") == []

    def test_concurrent_access(self):
        """No crash under concurrent writes and reads."""
        errors = []

        def writer():
            try:
                for i in range(50):
                    _stream_callback("concurrent", f"chunk{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    get_stream_chunks("concurrent")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(get_stream_chunks("concurrent")) == 150


class TestBuildMetadataContext:
    def test_with_description_and_tags(self):
        metadata = {
            "description": "This is a test video",
            "tags": ["python", "tutorial"],
        }
        ctx = _build_metadata_context(metadata, lang="zh")
        assert "This is a test video" in ctx
        assert "python" in ctx

    def test_empty_metadata(self):
        ctx = _build_metadata_context({}, lang="zh")
        assert ctx == ""

    def test_english_labels(self):
        metadata = {"description": "desc", "tags": ["tag1"]}
        ctx = _build_metadata_context(metadata, lang="en")
        assert "Video Description" in ctx
        assert "Tags" in ctx

    def test_no_description(self):
        metadata = {"tags": ["tag1"]}
        ctx = _build_metadata_context(metadata)
        assert "tag1" in ctx
        assert "简介" not in ctx

    def test_no_tags(self):
        metadata = {"description": "desc"}
        ctx = _build_metadata_context(metadata)
        assert "desc" in ctx


class TestGetPlatform:
    def test_bilibili_url(self):
        p = get_platform("https://www.bilibili.com/video/BV1234567890")
        assert p.__class__.__name__ == "BilibiliPlatform"

    def test_youtube_url(self):
        p = get_platform("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert p.__class__.__name__ == "YouTubePlatform"

    def test_unsupported_url(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_platform("https://example.com/video")
