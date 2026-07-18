"""End-to-end browser simulation: real HTTP, mocked externals, full user journey."""
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

MOCK_DOWNLOAD = "core.platforms.bilibili.BilibiliPlatform.download"
MOCK_GET_ASR = "core.pipeline.get_asr"
MOCK_GET_LLM = "core.pipeline.get_llm"

SETTINGS_TARGETS = [
    "core.pipeline.settings",
    "core.storage.db.settings",
    "core.llm.claude.settings",
    "core.llm.openai_proto.settings",
]


def _make_settings(tmp_dir):
    s = MagicMock()
    s.data_dir = Path(tmp_dir)
    s.cache_dir = Path(tmp_dir) / "cache"
    s.audio_dir = Path(tmp_dir) / "cache" / "audio"
    s.transcript_dir = Path(tmp_dir) / "cache" / "transcripts"
    s.frames_dir = Path(tmp_dir) / "cache" / "frames"
    s.db_path = Path(tmp_dir) / "test.db"
    s.whisper_model = "base"
    s.llm_provider = "claude"
    s.llm_model = "test-model"
    s.anthropic_api_key = "test-key"
    s.openai_api_key = "test-key"
    s.openai_base_url = "http://test"
    s.anthropic_base_url = ""
    for d in [s.data_dir, s.cache_dir, s.audio_dir, s.transcript_dir]:
        d.mkdir(parents=True, exist_ok=True)
    return s


def _mock_download(url, output_dir, keep_video=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    from core.platforms.bilibili import BilibiliPlatform
    video_id = BilibiliPlatform().parse_url(url)
    audio_path = output_dir / f"{video_id}.wav"
    audio_path.write_bytes(b"fake audio data")
    return audio_path, {"title": "Linux网络命名空间核心", "duration": 360, "video_id": video_id}, None


_MOCK_TRANSCRIPT = "这是一段关于Linux网络命名空间的详细讲解。首先介绍了什么是网络命名空间..."


def _make_mock_asr(transcript=_MOCK_TRANSCRIPT):
    asr = MagicMock()
    asr.transcribe_segments.return_value = (transcript, [{"start": 0.0, "end": 5.0, "text": transcript}])
    return asr


def _mock_download_error(url, output_dir, keep_video=False):
    raise ConnectionError("网络连接超时")


def _make_mock_llm(summary="本视频详细讲解了Linux网络命名空间的核心概念，包括隔离原理、veth pair配置和实际应用场景。", content_type="general"):
    llm = MagicMock()
    llm.classify.return_value = {"summary": "Linux网络命名空间", "type": content_type}
    llm.summarize.return_value = summary
    llm.summarize_multimodal.return_value = summary
    llm.generate_three_stage.return_value = {
        "preview": {"overview": "Linux网络命名空间概述", "questions": ["什么是网络命名空间？"], "pre_quiz": []},
        "index": [{"time_seconds": 30, "time_display": "00:30", "label": "核心概念", "detail": "介绍网络命名空间"}],
        "summary": {"text": summary, "cards": [], "post_quiz": [], "weak_points": []},
    }
    return llm


@pytest.fixture
def client(tmp_path):
    mock_s = _make_settings(tmp_path)
    patches = [patch(t, mock_s) for t in SETTINGS_TARGETS]
    for p in patches:
        p.start()

    import core.api.routes as routes
    from core.storage.db import Storage
    import core.storage.db as db_mod
    db_mod._instance = None
    routes.db = Storage(db_path=tmp_path / "test.db")

    app = __import__("core.main", fromlist=["app"]).app
    yield TestClient(app)

    for p in patches:
        p.stop()
    db_mod._instance = None


def _wait_done(client, task_id, timeout=15):
    for _ in range(timeout * 2):
        resp = client.get(f"/api/tasks/{task_id}")
        data = resp.json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(0.5)
    return data


# === Scenario 1: Homepage ===

def test_scenario_1_homepage(client):
    """GET / shows full web page."""
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text

    assert "Video Summarizer" in html
    assert 'id="url-input"' in html
    assert 'id="language-select"' in html
    assert 'id="provider-select"' in html
    assert 'id="submit-btn"' in html
    assert 'id="result-section"' in html
    assert 'id="history-table"' in html
    assert 'id="cleanup-btn"' in html
    assert 'href="/style.css"' in html
    assert 'src="/app.js"' in html


# === Scenario 2: Submit and status updates ===

def test_scenario_2_submit_and_status_updates(client):
    """Submit URL → task created → status transitions."""
    statuses_seen = []

    def track_download(url, output_dir, keep_video=False):
        statuses_seen.append("downloading")
        return _mock_download(url, output_dir, keep_video)

    tracking_asr = _make_mock_asr()
    _orig_ts = tracking_asr.transcribe_segments.side_effect
    def track_transcribe_segments(*a, **kw):
        statuses_seen.append("transcribing")
        return (_MOCK_TRANSCRIPT, [{"start": 0.0, "end": 5.0, "text": _MOCK_TRANSCRIPT}])
    tracking_asr.transcribe_segments.side_effect = track_transcribe_segments

    llm = _make_mock_llm()
    llm.classify.side_effect = lambda *a, **kw: (statuses_seen.append("classifying"), {"summary": "", "type": "general"})[1]
    llm.generate_three_stage.side_effect = lambda *a, **kw: (statuses_seen.append("generating_three_stage"), {
        "preview": {"overview": "概述", "questions": [], "pre_quiz": []},
        "index": [{"time_seconds": 10, "time_display": "00:10", "label": "点", "detail": "d"}],
        "summary": {"text": "本视频详细讲解了Linux网络命名空间的核心概念，包括隔离原理、veth pair配置和实际应用场景。", "cards": [], "post_quiz": [], "weak_points": []},
    })[1]

    with patch(MOCK_DOWNLOAD, side_effect=track_download), \
         patch(MOCK_GET_ASR, return_value=tracking_asr), \
         patch(MOCK_GET_LLM, return_value=llm):

        resp = client.post("/api/summarize", json={
            "url": "https://bilibili.com/video/BV1xx411c7mq",
            "language": "zh",
            "llm_provider": "claude",
        })
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]
        assert resp.json()["status"] == "pending"

        data = _wait_done(client, task_id)
        assert data["status"] == "done"
        assert statuses_seen == ["downloading", "transcribing", "classifying", "generating_three_stage"]


# === Scenario 3: Done shows summary ===

def test_scenario_3_done_shows_summary(client):
    """Task done → returns title, summary, transcript, metadata."""
    with patch(MOCK_DOWNLOAD, side_effect=_mock_download), \
         patch(MOCK_GET_ASR, return_value=_make_mock_asr()), \
         patch(MOCK_GET_LLM, return_value=_make_mock_llm()):

        resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
        task_id = resp.json()["task_id"]
        data = _wait_done(client, task_id)

        assert data["status"] == "done"
        assert data["summary"] == "本视频详细讲解了Linux网络命名空间的核心概念，包括隔离原理、veth pair配置和实际应用场景。"
        assert data["metadata"]["title"] == "Linux网络命名空间核心"
        assert data["metadata"]["duration"] == 360
        assert data["transcript"] == "这是一段关于Linux网络命名空间的详细讲解。首先介绍了什么是网络命名空间..."
        assert data["platform"] == "bilibili"
        assert data["completed_at"] is not None


# === Scenario 4: Failed shows error ===

def test_scenario_4_failed_shows_error(client):
    """Task failed → returns error message."""
    llm = _make_mock_llm()
    llm.classify.side_effect = RuntimeError("API key invalid")

    with patch(MOCK_DOWNLOAD, side_effect=_mock_download), \
         patch(MOCK_GET_ASR, return_value=_make_mock_asr()), \
         patch(MOCK_GET_LLM, return_value=llm):

        resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
        task_id = resp.json()["task_id"]
        data = _wait_done(client, task_id)

        assert data["status"] == "failed"
        assert "API key invalid" in data["error"]


def test_scenario_4b_download_error(client):
    """Download failed → returns error."""
    with patch(MOCK_DOWNLOAD, side_effect=_mock_download_error):
        resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
        task_id = resp.json()["task_id"]
        data = _wait_done(client, task_id)

        assert data["status"] == "failed"
        assert "网络连接超时" in data["error"]


# === Scenario 5: History after refresh ===

def test_scenario_5_history_after_refresh(client):
    """After task done → GET /api/tasks returns history."""
    with patch(MOCK_DOWNLOAD, side_effect=_mock_download), \
         patch(MOCK_GET_ASR, return_value=_make_mock_asr()), \
         patch(MOCK_GET_LLM, return_value=_make_mock_llm()):

        resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
        _wait_done(client, resp.json()["task_id"])

        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        tasks = resp.json()["tasks"]
        assert len(tasks) >= 1

        task = tasks[0]
        assert task["status"] == "done"
        assert task["metadata"]["title"] == "Linux网络命名空间核心"


# === Scenario 6: View history task ===

def test_scenario_6_view_history_task(client):
    """Click view → GET /api/tasks/{id} returns full detail."""
    with patch(MOCK_DOWNLOAD, side_effect=_mock_download), \
         patch(MOCK_GET_ASR, return_value=_make_mock_asr()), \
         patch(MOCK_GET_LLM, return_value=_make_mock_llm()):

        resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
        task_id = resp.json()["task_id"]
        _wait_done(client, task_id)

        resp = client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        detail = resp.json()

        assert detail["task_id"] == task_id
        assert detail["status"] == "done"
        assert detail["summary"] is not None
        assert detail["transcript"] is not None
        assert detail["metadata"]["title"] == "Linux网络命名空间核心"


# === Scenario 7: Cleanup storage ===

def test_scenario_7_cleanup_storage(client):
    """Cleanup → deletes all tasks and cache."""
    with patch(MOCK_DOWNLOAD, side_effect=_mock_download), \
         patch(MOCK_GET_ASR, return_value=_make_mock_asr()), \
         patch(MOCK_GET_LLM, return_value=_make_mock_llm()):

        resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
        _wait_done(client, resp.json()["task_id"])

        resp = client.get("/api/storage")
        info = resp.json()
        assert info["task_count"] >= 1

        resp = client.delete("/api/storage")
        assert resp.status_code == 200
        result = resp.json()
        assert result["deleted_tasks"] >= 1

        resp = client.get("/api/storage")
        info = resp.json()
        assert info["task_count"] == 0


# === Scenario 8: Invalid URL rejected ===

def test_scenario_8_invalid_url_rejected(client):
    """Invalid URL → 400, no task created."""
    resp = client.post("/api/summarize", json={"url": "https://youtube.com/watch?v=abc"})
    assert resp.status_code == 400

    resp = client.get("/api/tasks")
    assert len(resp.json()["tasks"]) == 0


# === Static assets ===

def test_static_assets_all_served(client):
    """CSS/JS served correctly."""
    assert client.get("/style.css").status_code == 200
    assert client.get("/app.js").status_code == 200


def test_api_not_overridden_by_static(client):
    """Static mount doesn't override API routes."""
    assert client.get("/health").status_code == 200
    assert client.get("/api/tasks").status_code == 200
    assert client.get("/api/storage").status_code == 200
    assert client.post("/api/summarize", json={"url": "https://youtube.com/x"}).status_code == 400


# === Multi-task ===

def test_multiple_tasks(client):
    """Multiple tasks in parallel, history complete."""
    with patch(MOCK_DOWNLOAD, side_effect=_mock_download), \
         patch(MOCK_GET_ASR, return_value=_make_mock_asr()), \
         patch(MOCK_GET_LLM, return_value=_make_mock_llm()):

        ids = []
        for _ in range(3):
            resp = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV1xx411c7mq"})
            ids.append(resp.json()["task_id"])

        for tid in ids:
            _wait_done(client, tid)

        resp = client.get("/api/tasks")
        assert len(resp.json()["tasks"]) == 3
