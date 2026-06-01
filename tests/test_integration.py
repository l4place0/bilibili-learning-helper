"""Integration tests: mock external deps, test full business flow via real HTTP."""
import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# Mock paths — target where the name is USED (imported), not where it's defined
MOCK_DOWNLOAD = "core.platforms.bilibili.BilibiliPlatform.download"
MOCK_YT_DOWNLOAD = "core.platforms.youtube.YouTubePlatform.download"
MOCK_GET_LLM = "core.pipeline.get_llm"
MOCK_GET_ASR = "core.pipeline.get_asr"


def _mock_yt_download(url, output_dir, keep_video=False):
    output_dir.mkdir(parents=True, exist_ok=True)
    from core.platforms.youtube import YouTubePlatform
    video_id = YouTubePlatform().parse_url(url)
    audio_path = output_dir / f"{video_id}.wav"
    audio_path.write_bytes(b"fake audio")
    return audio_path, {"title": "YouTube Video", "duration": 300, "video_id": video_id}, None


def _wait_done(client, task_id, timeout=10):
    for _ in range(timeout * 2):
        resp = client.get(f"/api/tasks/{task_id}")
        data = resp.json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(0.5)
    return data


# --- Tests ---

def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_invalid_url_400(client):
    r = client.post("/api/summarize", json={"url": "https://youtube.com/x"})
    assert r.status_code == 400


def test_full_pipeline_happy_path(client, mock_download, mock_asr, mock_llm):
    with patch(MOCK_DOWNLOAD, side_effect=mock_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=mock_llm("这是摘要")):

        r = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        assert r.status_code == 202
        task_id = r.json()["task_id"]

        data = _wait_done(client, task_id)
        assert data["status"] == "done", f"got {data['status']}: {data.get('error')}"
        assert data["summary"] == "这是摘要"
        assert data["metadata"]["title"] == "Test Video"
        assert data["transcript"] == "这是一段测试转录文本。"


def test_task_list(client, mock_download, mock_asr, mock_llm):
    with patch(MOCK_DOWNLOAD, side_effect=mock_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=mock_llm("摘要")):

        client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        time.sleep(1)

        r = client.get("/api/tasks")
        assert len(r.json()["tasks"]) >= 1


def test_status_transitions(client, mock_download, mock_asr):
    statuses = []

    def track_download(url, output_dir, keep_video=False):
        statuses.append("downloading")
        return mock_download(url, output_dir, keep_video)

    asr = mock_asr()
    asr.transcribe_segments.side_effect = lambda *a, **kw: (statuses.append("transcribing"), ("转录文本", [{"start": 0.0, "end": 5.0, "text": "转录文本"}]))[1]

    llm = MagicMock()
    llm.classify.side_effect = lambda *a, **kw: (statuses.append("classifying"), {"summary": "", "type": "general"})[1]
    llm.generate_three_stage.side_effect = lambda *a, **kw: (statuses.append("generating_three_stage"), {
        "preview": {"overview": "概述", "questions": [], "pre_quiz": []},
        "index": [{"time_seconds": 10, "time_display": "00:10", "label": "点", "detail": "d"}],
        "summary": {"text": "摘要", "cards": [], "post_quiz": [], "weak_points": []},
    })[1]

    with patch(MOCK_DOWNLOAD, side_effect=track_download), \
         patch(MOCK_GET_ASR, return_value=asr), \
         patch(MOCK_GET_LLM, return_value=llm):

        r = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        _wait_done(client, r.json()["task_id"])

        assert statuses == ["downloading", "transcribing", "classifying", "generating_three_stage"]


def test_pipeline_download_error(client, mock_download):
    with patch(MOCK_DOWNLOAD, side_effect=ConnectionError("超时")):
        r = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        data = _wait_done(client, r.json()["task_id"])
        assert data["status"] == "failed"
        assert "超时" in data["error"]


def test_pipeline_llm_error(client, mock_download, mock_asr, mock_llm):
    llm = mock_llm()
    llm.classify.side_effect = RuntimeError("API key invalid")

    with patch(MOCK_DOWNLOAD, side_effect=mock_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=llm):

        r = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        data = _wait_done(client, r.json()["task_id"])
        assert data["status"] == "failed"
        assert "API key invalid" in data["error"]


def test_storage_query_and_cleanup(client):
    r = client.get("/api/storage")
    assert r.status_code == 200
    assert "db_size_bytes" in r.json()

    r = client.delete("/api/storage")
    assert r.status_code == 200
    assert "deleted_files" in r.json()


def test_task_not_found(client):
    assert client.get("/api/tasks/nonexist").status_code == 404


def test_openai_provider(client, mock_download, mock_asr, mock_llm):
    with patch(MOCK_DOWNLOAD, side_effect=mock_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=mock_llm("OpenAI摘要")):

        r = client.post("/api/summarize", json={
            "url": "https://bilibili.com/video/BV123",
            "llm_provider": "openai",
        })
        data = _wait_done(client, r.json()["task_id"])
        assert data["status"] == "done"
        assert data["summary"] == "OpenAI摘要"


def test_cache_hit_skips_download(client, mock_download, mock_asr, mock_llm):
    """Same video_id reuses cached audio/transcript, skips download and transcription."""
    download_count = 0
    asr = mock_asr()

    def counting_download(url, output_dir, keep_video=False):
        nonlocal download_count
        download_count += 1
        return mock_download(url, output_dir, keep_video)

    with patch(MOCK_DOWNLOAD, side_effect=counting_download), \
         patch(MOCK_GET_ASR, return_value=asr), \
         patch(MOCK_GET_LLM, return_value=mock_llm("摘要")):

        r1 = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        _wait_done(client, r1.json()["task_id"])
        assert download_count == 1
        assert asr.transcribe_segments.call_count == 1

        r2 = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        _wait_done(client, r2.json()["task_id"])
        assert download_count == 1  # cache hit, no re-download
        assert asr.transcribe_segments.call_count == 1  # cache hit, no re-transcribe

        tasks = client.get("/api/tasks").json()["tasks"]
        assert len(tasks) == 2
        assert all(t["status"] == "done" for t in tasks)


def test_content_type_routing(client, mock_download, mock_asr, mock_llm):
    """Classify returns 'tutorial' -> summarize receives content_type='tutorial'."""
    llm = mock_llm("教程摘要", content_type="tutorial")

    with patch(MOCK_DOWNLOAD, side_effect=mock_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=llm):

        r = client.post("/api/summarize", json={"url": "https://bilibili.com/video/BV123"})
        _wait_done(client, r.json()["task_id"])

        llm.classify.assert_called_once()
        # Pipeline uses generate_three_stage for text-only mode
        call_args = llm.generate_three_stage.call_args
        assert call_args is not None


def test_youtube_happy_path(client, mock_asr, mock_llm):
    with patch(MOCK_YT_DOWNLOAD, side_effect=_mock_yt_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=mock_llm("YouTube摘要")):

        r = client.post("/api/summarize", json={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"})
        assert r.status_code == 202
        task_id = r.json()["task_id"]

        data = _wait_done(client, task_id)
        assert data["status"] == "done", f"got {data['status']}: {data.get('error')}"
        assert data["summary"] == "YouTube摘要"
        assert data["metadata"]["title"] == "YouTube Video"


def test_youtube_short_url(client, mock_asr, mock_llm):
    with patch(MOCK_YT_DOWNLOAD, side_effect=_mock_yt_download), \
         patch(MOCK_GET_ASR, return_value=mock_asr()), \
         patch(MOCK_GET_LLM, return_value=mock_llm("摘要")):

        r = client.post("/api/summarize", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
        assert r.status_code == 202
        data = _wait_done(client, r.json()["task_id"])
        assert data["status"] == "done"


def test_youtube_invalid_url_400(client):
    r = client.post("/api/summarize", json={"url": "https://youtube.com/x"})
    assert r.status_code == 400
