"""Tests for LLM fallback chains and error handling."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestClassifyErrorTypes:
    """Test that classify distinguishes JSON decode vs network errors."""

    def test_json_error_logs_raw_response(self, caplog):
        """JSON decode error logs the raw LLM response."""
        from core.llm.base import BaseLLM

        class StubLLM(BaseLLM):
            def _chat(self, prompt, max_tokens=4096):
                return "not valid json"

        llm = StubLLM()
        result = llm.classify("test transcript", lang="zh")
        assert result["type"] == "general"  # falls back after 3 attempts
        assert "invalid JSON" in caplog.text

    def test_network_error_logged(self, caplog):
        """Network error is logged with exception details."""
        from core.llm.base import BaseLLM

        class StubLLM(BaseLLM):
            def _chat(self, prompt, max_tokens=4096):
                raise ConnectionError("API timeout")

        llm = StubLLM()
        result = llm.classify("test transcript", lang="zh")
        assert result["type"] == "general"
        assert "network/API error" in caplog.text

    def test_valid_json_returns_result(self):
        """Valid JSON response is parsed correctly."""
        import json
        from core.llm.base import BaseLLM

        class StubLLM(BaseLLM):
            def _chat(self, prompt, max_tokens=4096):
                return json.dumps({"type": "tutorial", "summary": "A tutorial"})

        llm = StubLLM()
        result = llm.classify("test transcript", lang="zh")
        assert result["type"] == "tutorial"
        assert result["summary"] == "A tutorial"

    def test_markdown_code_block_parsed(self):
        """JSON wrapped in markdown code blocks is parsed."""
        import json
        from core.llm.base import BaseLLM

        class StubLLM(BaseLLM):
            def _chat(self, prompt, max_tokens=4096):
                return "```json\n" + json.dumps({"type": "tech_talk", "summary": "Tech"}) + "\n```"

        llm = StubLLM()
        result = llm.classify("test transcript", lang="zh")
        assert result["type"] == "tech_talk"


class TestMultimodalFallback:
    """Test summarize_multimodal 3-tier fallback in OpenAILLM."""

    @patch("core.llm.openai_proto.settings")
    @patch("core.llm.openai_proto.OpenAI")
    def test_frame_based_fails_falls_to_native_video(self, mock_openai_cls, mock_settings):
        """When frame-based fails, falls back to native video."""
        mock_settings.openai_api_key = "test-key"
        mock_settings.openai_model = "gpt-4o"
        mock_settings.openai_vision_model = ""
        mock_settings.openai_base_url = "https://api.openai.com/v1"

        client = MagicMock()
        mock_openai_cls.return_value = client

        # First call (frame-based) fails, second (native video) succeeds
        call_count = {"n": 0}
        def create_side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("Frame extraction failed")
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.content = "Native video summary"
            return resp

        client.chat.completions.create = create_side_effect

        from core.llm.openai_proto import OpenAILLM
        llm = OpenAILLM()

        video_path = MagicMock(spec=Path)
        video_path.read_bytes.return_value = b"fake-video"
        video_path.suffix = ".mp4"
        video_path.name = "test.mp4"

        # Mock extract_frames to raise
        with patch("core.llm.openai_proto.extract_frames", side_effect=RuntimeError("fail")):
            result = llm.summarize_multimodal("transcript", video_path)
        assert result == "Native video summary"
