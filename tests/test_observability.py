"""Tests for the observability module: StageContext, JSONL logger, evidence, metrics."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def test_stage_context_normal_execution():
    """StageContext records input, output, decisions, and duration on success."""
    from core.observability.stage import StageContext

    with tempfile.TemporaryDirectory() as tmp:
        with patch("core.observability.stage.write_event") as mock_write, \
             patch("core.observability.stage.insert_evidence") as mock_evidence, \
             patch("core.observability.stage.record_stage") as mock_metrics:

            with StageContext("task-123", "transcribe") as stage:
                stage.input(audio_path="/tmp/test.wav", language="zh")
                stage.output(text_length=500)
                stage.decision("backend", "faster-whisper", reason="configured")

            # Verify write_event was called
            mock_write.assert_called_once()
            event = mock_write.call_args[0][1]
            assert event["task_id"] == "task-123"
            assert event["stage"] == "transcribe"
            assert event["status"] == "success"
            assert event["input"]["audio_path"] == "/tmp/test.wav"
            assert event["output"]["text_length"] == 500
            assert len(event["decisions"]) == 1
            assert event["decisions"][0]["key"] == "backend"
            assert event["duration_ms"] >= 0

            # Verify evidence was written
            mock_evidence.assert_called_once()

            # Verify metrics were recorded
            mock_metrics.assert_called_once_with("transcribe", "success", event["duration_ms"])


def test_stage_context_exception():
    """StageContext records error status when exception occurs."""
    from core.observability.stage import StageContext

    with patch("core.observability.stage.write_event") as mock_write, \
         patch("core.observability.stage.insert_evidence"), \
         patch("core.observability.stage.record_stage"):

        with pytest.raises(ValueError, match="test error"):
            with StageContext("task-123", "classify") as stage:
                stage.input(transcript_length=100)
                raise ValueError("test error")

        event = mock_write.call_args[0][1]
        assert event["status"] == "error"
        assert "ValueError: test error" in event["error"]


def test_stage_context_warning():
    """StageContext records warnings."""
    from core.observability.stage import StageContext

    with patch("core.observability.stage.write_event") as mock_write, \
         patch("core.observability.stage.insert_evidence"), \
         patch("core.observability.stage.record_stage"):

        with StageContext("task-123", "transcribe") as stage:
            stage.input(audio_path="/tmp/test.wav")
            stage.output(text_length=0)
            stage.warning("0 chars transcribed — ASR model may be too small")

        event = mock_write.call_args[0][1]
        assert len(event["warnings"]) == 1
        assert "0 chars" in event["warnings"][0]


def test_jsonl_write_and_read():
    """JSONL logger writes and reads events correctly."""
    from core.observability.logger import write_event, read_events

    with tempfile.TemporaryDirectory() as tmp:
        with patch("core.observability.logger._get_log_dir", return_value=Path(tmp)):
            # Write two events
            write_event("task-abc", {"stage": "download", "status": "success", "duration_ms": 100})
            write_event("task-abc", {"stage": "transcribe", "status": "success", "duration_ms": 200})

            events = read_events("task-abc")
            assert len(events) == 2
            assert events[0]["stage"] == "download"
            assert events[1]["stage"] == "transcribe"

            # Non-existent task
            assert read_events("task-xyz") == []


def test_jsonl_file_format():
    """JSONL file has one JSON object per line."""
    from core.observability.logger import write_event

    with tempfile.TemporaryDirectory() as tmp:
        with patch("core.observability.logger._get_log_dir", return_value=Path(tmp)):
            write_event("task-1", {"stage": "a", "status": "ok"})
            write_event("task-1", {"stage": "b", "status": "ok"})

            content = (Path(tmp) / "task-1.jsonl").read_text()
            lines = content.strip().split("\n")
            assert len(lines) == 2
            for line in lines:
                parsed = json.loads(line)
                assert "stage" in parsed


def test_evidence_write_and_query():
    """Evidence table stores and retrieves records."""
    from core.observability.evidence import insert_evidence, get_evidence

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test.db"
        with patch("core.observability.evidence._get_db_path", return_value=db_path):
            insert_evidence(
                task_id="task-1",
                stage="transcribe",
                status="success",
                input_summary={"audio": "/tmp/test.wav"},
                output_summary={"chars": 500},
                decisions=[{"key": "backend", "value": "faster"}],
                warnings=["test warning"],
                duration_ms=1234,
            )

            results = get_evidence("task-1")
            assert len(results) == 1
            r = results[0]
            assert r["task_id"] == "task-1"
            assert r["stage"] == "transcribe"
            assert r["status"] == "success"
            assert r["input_summary"]["audio"] == "/tmp/test.wav"
            assert r["output_summary"]["chars"] == 500
            assert r["decisions"][0]["key"] == "backend"
            assert r["warnings"] == ["test warning"]
            assert r["duration_ms"] == 1234


def test_metrics_counter_increment():
    """Metrics counters increment correctly."""
    from core.observability.metrics import record_stage, record_transcribe_empty, record_llm_fallback, get_metrics

    # Reset by importing fresh (counters are module-level)
    import core.observability.metrics as m
    old_counters = dict(m._counters)
    old_empty = m._transcribe_empty_total
    old_fallback = m._llm_fallback_total
    m._counters.clear()
    m._histograms.clear()
    m._transcribe_empty_total = 0
    m._llm_fallback_total = 0

    try:
        record_stage("download", "success", 1000)
        record_stage("download", "success", 2000)
        record_stage("transcribe", "error", 500)
        record_transcribe_empty()
        record_transcribe_empty()
        record_llm_fallback()

        metrics = get_metrics()
        assert metrics['counters']['pipeline_stage_total{stage="download",status="success"}'] == 2
        assert metrics['counters']['pipeline_stage_total{stage="transcribe",status="error"}'] == 1
        assert metrics["transcribe_empty_total"] == 2
        assert metrics["llm_fallback_total"] == 1

        # Histogram has entries
        assert len(metrics["histograms"]) == 2  # download and transcribe
    finally:
        m._counters.clear()
        m._counters.update(old_counters)
        m._histograms.clear()
        m._transcribe_empty_total = old_empty
        m._llm_fallback_total = old_fallback


def test_metrics_prometheus_format():
    """Metrics text output is valid Prometheus format."""
    from core.observability.metrics import metrics_text, record_stage

    import core.observability.metrics as m
    old_counters = dict(m._counters)
    old_histograms = dict(m._histograms)
    old_empty = m._transcribe_empty_total
    old_fallback = m._llm_fallback_total
    m._counters.clear()
    m._histograms.clear()
    m._transcribe_empty_total = 0
    m._llm_fallback_total = 0

    try:
        record_stage("download", "success", 1500)
        text = metrics_text()

        assert "# HELP pipeline_stage_total" in text
        assert "# TYPE pipeline_stage_total counter" in text
        assert "# HELP pipeline_stage_duration_seconds" in text
        assert "# TYPE pipeline_stage_duration_seconds histogram" in text
        assert "pipeline_transcribe_empty_total 0" in text
        assert "pipeline_llm_fallback_total 0" in text
        assert 'stage="download"' in text
    finally:
        m._counters.clear()
        m._counters.update(old_counters)
        m._histograms.clear()
        m._histograms.update(old_histograms)
        m._transcribe_empty_total = old_empty
        m._llm_fallback_total = old_fallback
