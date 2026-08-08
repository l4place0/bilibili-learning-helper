"""Tests for the core video-sum CLI."""

import io
import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cli.output import emit, emit_error


def test_emit_json_line(capsys):
    emit("test_event", key="value")
    data = json.loads(capsys.readouterr().out)
    assert data["event"] == "test_event"
    assert data["key"] == "value"


def test_emit_unicode(capsys):
    emit("test", title="测试标题")
    assert json.loads(capsys.readouterr().out)["title"] == "测试标题"


def test_emit_reconfigures_legacy_stdout_to_utf8():
    from cli import output

    raw = io.BytesIO()
    legacy_stdout = io.TextIOWrapper(raw, encoding="gbk")
    with patch.object(output.sys, "stdout", legacy_stdout):
        output.emit("test", title="中文 🎬")
        legacy_stdout.flush()
    legacy_stdout.detach()

    assert json.loads(raw.getvalue().decode("utf-8"))["title"] == "中文 🎬"


def test_emit_unicode_with_gbk_process_default():
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "gbk"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from cli.output import emit; "
                "emit('test', title='中文 🎬')"
            ),
        ],
        capture_output=True,
        env=environment,
        check=True,
    )

    assert json.loads(result.stdout.decode("utf-8"))["title"] == "中文 🎬"


def test_emit_error_exits():
    with pytest.raises(SystemExit) as exc_info:
        emit_error("something broke", code=42)
    assert exc_info.value.code == 42


def test_core_command_surface():
    from cli import main

    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in (
        "asr",
        "cache",
        "capture",
        "doctor",
        "frames",
        "library",
        "resource",
    ):
        assert command in result.output
    for removed in ("ingest", "run", "serve", "submit", "status", "result"):
        assert removed not in result.output


def test_version():
    from cli import main

    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "0.2.1" in result.output


def test_doctor_reports_structured_checks(tmp_path):
    from cli import main
    from core.config import settings

    with (
        patch.object(settings, "library_dir", tmp_path),
        patch.object(settings, "asr_provider", "whisper-cpp"),
        patch.object(settings, "whisper_cpp_model", tmp_path / "model.bin"),
        patch("cli.commands.shutil.which", return_value="/usr/local/bin/tool"),
    ):
        (tmp_path / "model.bin").write_bytes(b"model")
        result = CliRunner().invoke(main, ["doctor"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["event"] == "doctor"
    assert data["healthy"] is True


def test_capture_uses_configured_defaults():
    from cli import main
    from core.config import settings

    with (
        patch.object(settings, "default_language", "ja"),
        patch.object(settings, "default_frames", 4),
        patch.object(settings, "default_frame_mode", "scene"),
        patch.object(settings, "default_cache_policy", "off"),
        patch.object(settings, "asr_provider", "whisper-cpp"),
        patch.object(settings, "asr_profile", "accurate"),
        patch("cli.commands._run_ingestion") as run_ingestion,
    ):
        result = CliRunner().invoke(
            main,
            ["capture", "https://example.com/video"],
        )

    assert result.exit_code == 0
    assert run_ingestion.call_args.args[1] == "ja"
    assert run_ingestion.call_args.args[3] == "accurate"
    assert run_ingestion.call_args.args[5] == 4
    assert run_ingestion.call_args.kwargs == {
        "frame_mode": "scene",
        "cache_policy": "off",
        "fact_check_mode": "auto",
    }


def test_capture_does_not_require_profile_before_onboarding():
    from cli import main
    from core.config import settings

    with (
        patch.object(settings, "asr_provider", "whisper-cpp"),
        patch.object(settings, "asr_profile", None),
        patch("cli.commands._run_ingestion") as run_ingestion,
    ):
        result = CliRunner().invoke(
            main,
            ["capture", "https://example.com/video"],
        )

    assert result.exit_code == 0
    assert run_ingestion.call_args.args[3] == ""


def test_asr_profiles_reports_installed_models(tmp_path):
    from cli import main
    from core.config import settings

    (tmp_path / "ggml-small-q5_1.bin").write_bytes(b"model")
    with patch.object(settings, "asr_model_dir", tmp_path):
        result = CliRunner().invoke(main, ["asr", "profiles"])

    assert result.exit_code == 0
    profiles = {item["name"]: item for item in json.loads(result.output)["profiles"]}
    assert profiles["balanced"]["installed"] is True
    assert profiles["fast"]["installed"] is False


@patch("core.vision.frames.extract_frames_at")
def test_frames_extract_accepts_explicit_timestamps(mock_extract, tmp_path):
    from cli import main

    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    output = tmp_path / "frames"
    mock_extract.return_value = [output / "frame_0001.webp"]

    result = CliRunner().invoke(
        main,
        [
            "frames",
            "extract",
            str(video),
            "--at",
            "01:30",
            "--around",
            "2",
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert mock_extract.call_args.args[2] == [88.0, 90.0, 92.0]
    assert json.loads(result.output)["event"] == "frames_extracted"
