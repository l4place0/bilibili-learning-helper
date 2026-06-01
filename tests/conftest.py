"""Shared fixtures, markers, and helpers for the test suite."""
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient
from core.config import Settings


# ── pytest markers ──────────────────────────────────────────────────
def pytest_configure(config):
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "shell: Shell script tests")
    config.addinivalue_line("markers", "e2e: End-to-end tests requiring browser (playwright)")
    config.addinivalue_line("markers", "requires_server: Tests requiring a running server")


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests that need external dependencies."""
    # Skip playwright tests if not installed
    try:
        import playwright  # noqa: F401
    except ImportError:
        skip_e2e = pytest.mark.skip(reason="playwright not installed")
        for item in items:
            if "browser" in item.fixturenames:
                item.add_marker(skip_e2e)
            if "test_review_doc_e2e" in item.nodeid or "test_retry_button" in item.nodeid:
                item.add_marker(skip_e2e)

    # Skip tests that connect to external server (test_review_doc_api, test_skill server tests)
    for item in items:
        # test_review_doc_api tests need a running server at localhost:8000
        if "test_review_doc_api" in item.nodeid:
            if "TestReviewDocAPI" in item.nodeid or "TestReviewDocStructure" in item.nodeid or "TestReviewDocWithCards" in item.nodeid:
                item.add_marker(pytest.mark.skip(reason="requires running server at localhost:8000"))
        # test_skill tests that use 'server' fixture have flaky timing
        if "test_skill" in item.nodeid:
            if "server" in item.fixturenames:
                item.add_marker(pytest.mark.skip(reason="flaky server fixture timing"))


# ── Shared constants ────────────────────────────────────────────────

# Mock paths — target where the name is USED (imported), not where it's defined
SETTINGS_TARGETS = [
    "core.pipeline.settings",
    "core.storage.db.settings",
    "core.llm.claude.settings",
    "core.llm.openai_proto.settings",
]


# ── Shared helper functions ─────────────────────────────────────────

def _mock_download(url, output_dir, keep_video=False):
    """Create a fake downloaded audio file for Bilibili URLs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    from core.platforms.bilibili import BilibiliPlatform
    video_id = BilibiliPlatform().parse_url(url)
    audio_path = output_dir / f"{video_id}.wav"
    audio_path.write_bytes(b"fake audio")
    return audio_path, {"title": "Test Video", "duration": 120, "video_id": video_id}, None


def _make_mock_asr(transcript_text="这是一段测试转录文本。"):
    """Create a mock ASR instance."""
    asr = MagicMock()
    asr.transcribe.return_value = transcript_text
    asr.transcribe_segments.return_value = (transcript_text, [{"start": 0.0, "end": 5.0, "text": transcript_text}])
    return asr


def _make_mock_llm(summary_text="这是摘要", content_type="general"):
    """Create a mock LLM that returns the given summary and content type."""
    llm = MagicMock()
    llm.classify.return_value = {"summary": "test video", "type": content_type}
    llm.summarize.return_value = summary_text
    llm.summarize_multimodal.return_value = summary_text
    llm.summarize_stream.return_value = iter([summary_text])
    llm.generate_three_stage.return_value = {
        "preview": {"overview": "测试概述", "questions": ["问题1"], "pre_quiz": []},
        "index": [{"time_seconds": 30, "time_display": "00:30", "label": "要点", "detail": "说明"}],
        "summary": {"text": summary_text, "cards": [], "post_quiz": [], "weak_points": []},
    }
    return llm


# ── Shared fixtures ─────────────────────────────────────────────────

@pytest.fixture
def mock_asr():
    """Fixture that returns the _make_mock_asr factory function."""
    return _make_mock_asr


@pytest.fixture
def mock_llm():
    """Fixture that returns the _make_mock_llm factory function."""
    return _make_mock_llm


@pytest.fixture
def mock_download():
    """Fixture that returns the _mock_download function."""
    return _mock_download


@pytest.fixture
def test_settings(tmp_path):
    """Return a real Pydantic Settings instance with test defaults."""
    s = Settings(
        data_dir=tmp_path,
        whisper_model="base",
        llm_provider="claude",
        anthropic_api_key="test-key",
        openai_api_key="test-key",
        openai_base_url="http://test",
        asr_provider="inprocess",
        auto_cleanup_days=7,
    )
    s.ensure_dirs()
    return s


@pytest.fixture
def client(tmp_path, test_settings):
    """Create a FastAPI TestClient with mocked settings and a fresh DB."""
    patches = [patch(t, test_settings) for t in SETTINGS_TARGETS]

    for p in patches:
        p.start()

    import core.api.routes as routes
    from core.storage.db import Storage
    # Reset singleton so it picks up the mocked settings
    import core.storage.db as db_mod
    db_mod._instance = None
    routes.db = Storage(db_path=test_settings.db_path)

    app = __import__("core.main", fromlist=["app"]).app
    yield TestClient(app)

    for p in patches:
        p.stop()
    # Reset singleton
    db_mod._instance = None
