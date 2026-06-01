"""Tests for CLI commands and output utilities."""
import json
import sys
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from cli.output import emit, emit_error


class TestOutput:
    """Test JSON output utilities."""

    def test_emit_json_line(self, capsys):
        emit("test_event", key="value")
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert data["event"] == "test_event"
        assert data["key"] == "value"

    def test_emit_unicode(self, capsys):
        emit("test", title="测试标题")
        out = capsys.readouterr().out.strip()
        data = json.loads(out)
        assert data["title"] == "测试标题"

    def test_emit_error_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            emit_error("something broke")
        assert exc_info.value.code == 1

    def test_emit_error_custom_code(self):
        with pytest.raises(SystemExit) as exc_info:
            emit_error("fail", code=42)
        assert exc_info.value.code == 42


class TestCLICommands:
    """Test CLI command definitions."""

    def test_run_help(self):
        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0
        assert "URL" in result.output or "url" in result.output

    def test_serve_help(self):
        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "port" in result.output

    def test_submit_help(self):
        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["submit", "--help"])
        assert result.exit_code == 0

    def test_status_help(self):
        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0

    def test_result_help(self):
        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["result", "--help"])
        assert result.exit_code == 0

    def test_version(self):
        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    @patch("cli.commands._run_remote")
    def test_run_with_remote(self, mock_remote):
        from cli import main
        runner = CliRunner()
        runner.invoke(main, ["run", "https://bilibili.com/video/BV123", "--remote", "http://localhost:8000"])
        mock_remote.assert_called_once()

    @patch("cli.commands._free_port", return_value=9999)
    @patch("cli.commands._start_server")
    @patch("cli.commands._run_remote")
    def test_run_local_starts_server(self, mock_remote, mock_start, mock_port):
        from cli import main
        runner = CliRunner()
        runner.invoke(main, ["run", "https://bilibili.com/video/BV123"])
        mock_start.assert_called_once_with(9999)
        mock_remote.assert_called_once()

    @patch("cli.commands.httpx.post")
    def test_submit_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"task_id": "abc-123", "status": "pending"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["submit", "https://bilibili.com/video/BV123", "--remote", "http://test:8000"])
        assert result.exit_code == 0
        assert "abc-123" in result.output

    @patch("cli.commands.httpx.get")
    def test_status_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"task_id": "abc", "status": "done", "progress": 100}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["status", "abc", "--remote", "http://test:8000"])
        assert result.exit_code == 0
        assert "done" in result.output

    @patch("cli.commands.httpx.get")
    def test_status_not_found(self, mock_get):
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.side_effect = httpx.HTTPStatusError("404", request=MagicMock(), response=mock_resp)

        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["status", "nonexist", "--remote", "http://test:8000"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "error" in result.output.lower()

    @patch("cli.commands.httpx.get")
    def test_result_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"task_id": "abc", "summary": "test summary", "status": "done"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        from cli import main
        runner = CliRunner()
        result = runner.invoke(main, ["result", "abc", "--remote", "http://test:8000"])
        assert result.exit_code == 0
        assert "test summary" in result.output


class TestFreePort:
    """Test _free_port utility."""

    def test_returns_int(self):
        from cli.commands import _free_port
        port = _free_port()
        assert isinstance(port, int)
        assert 1024 < port < 65535

    def test_port_is_usable(self):
        import socket
        from cli.commands import _free_port
        port = _free_port()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", port))
        finally:
            s.close()
