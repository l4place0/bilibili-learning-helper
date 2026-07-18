"""Tests for three-stage learning feature: URL builder, JSON parsing, pipeline integration."""

import json
from unittest.mock import MagicMock, patch

from core.llm.base import BaseLLM
from core.platforms import build_video_url


# ============================================================
# Task 4.2: build_video_url tests
# ============================================================

class TestBuildVideoUrl:
    def test_youtube_with_timestamp(self):
        url = build_video_url("youtube", "dQw4w9WgXcQ", 225)
        assert url == "https://youtube.com/watch?v=dQw4w9WgXcQ&t=225"

    def test_youtube_without_timestamp(self):
        url = build_video_url("youtube", "dQw4w9WgXcQ", 0)
        assert url == "https://youtube.com/watch?v=dQw4w9WgXcQ"

    def test_bilibili_with_timestamp(self):
        url = build_video_url("bilibili", "BV1xx411c7XW", 180)
        assert url == "https://bilibili.com/video/BV1xx411c7XW?t=180"

    def test_bilibili_without_timestamp(self):
        url = build_video_url("bilibili", "BV1xx411c7XW", 0)
        assert url == "https://bilibili.com/video/BV1xx411c7XW"

    def test_unknown_platform_returns_none(self):
        url = build_video_url("vimeo", "12345", 60)
        assert url is None


# ============================================================
# Task 1.3: Three-stage JSON parsing tests
# ============================================================

class TestParseThreeStageJson:
    def test_valid_json(self):
        raw = json.dumps({
            "preview": {"overview": "test", "questions": ["q1"], "pre_quiz": []},
            "index": [{"time_seconds": 60, "time_display": "01:00", "label": "point", "detail": "desc"}],
            "summary": {"text": "full summary", "cards": [], "post_quiz": [], "weak_points": []},
        })
        result = BaseLLM._parse_three_stage_json(raw)
        assert result["preview"]["overview"] == "test"
        assert len(result["index"]) == 1

    def test_json_in_markdown_block(self):
        raw = '```json\n{"preview": {"overview": "x", "questions": [], "pre_quiz": []}, "index": [], "summary": {"text": "y", "cards": [], "post_quiz": [], "weak_points": []}}\n```'
        result = BaseLLM._parse_three_stage_json(raw)
        assert result["preview"]["overview"] == "x"

    def test_json_with_surrounding_text(self):
        raw = 'Here is the result:\n{"preview": {"overview": "ok", "questions": [], "pre_quiz": []}, "index": [], "summary": {"text": "done", "cards": [], "post_quiz": [], "weak_points": []}}\nEnd.'
        result = BaseLLM._parse_three_stage_json(raw)
        assert result["preview"]["overview"] == "ok"

    def test_invalid_json_raises(self):
        import pytest
        with pytest.raises(json.JSONDecodeError):
            BaseLLM._parse_three_stage_json("not json at all")


class TestValidateThreeStage:
    def test_valid_complete(self):
        result = {
            "preview": {"overview": "test", "questions": ["q1"], "pre_quiz": []},
            "index": [{"time_seconds": 60}],
            "summary": {"text": "full", "cards": [], "post_quiz": [], "weak_points": []},
        }
        assert BaseLLM._validate_three_stage(result) is True

    def test_missing_preview(self):
        result = {
            "preview": {"overview": "", "questions": [], "pre_quiz": []},
            "index": [{"time_seconds": 60}],
            "summary": {"text": "full", "cards": [], "post_quiz": [], "weak_points": []},
        }
        assert BaseLLM._validate_three_stage(result) is False

    def test_missing_index(self):
        result = {
            "preview": {"overview": "test", "questions": [], "pre_quiz": []},
            "index": [],
            "summary": {"text": "full", "cards": [], "post_quiz": [], "weak_points": []},
        }
        assert BaseLLM._validate_three_stage(result) is False

    def test_missing_summary_text(self):
        result = {
            "preview": {"overview": "test", "questions": [], "pre_quiz": []},
            "index": [{"time_seconds": 60}],
            "summary": {"text": "", "cards": [], "post_quiz": [], "weak_points": []},
        }
        assert BaseLLM._validate_three_stage(result) is False


class TestFillThreeStageDefaults:
    def test_fills_missing_fields(self):
        result = {"preview": {"overview": "ok"}, "index": [{"time_seconds": 10}], "summary": {"text": "done"}}
        filled = BaseLLM._fill_three_stage_defaults(result)
        assert filled["preview"]["questions"] == []
        assert filled["preview"]["pre_quiz"] == []
        assert filled["summary"]["cards"] == []
        assert filled["summary"]["post_quiz"] == []
        assert filled["summary"]["weak_points"] == []

    def test_empty_preview_becomes_default(self):
        result = {"preview": {}, "index": [{"time_seconds": 10}], "summary": {"text": "ok"}}
        filled = BaseLLM._fill_three_stage_defaults(result)
        assert filled["preview"]["overview"] == ""


class TestEmptyThreeStage:
    def test_returns_complete_structure(self):
        result = BaseLLM._empty_three_stage()
        assert "preview" in result
        assert "index" in result
        assert "summary" in result
        assert result["preview"]["overview"] == ""
        assert result["index"] == []
        assert result["summary"]["text"] == ""


# ============================================================
# Pipeline integration test (mocked LLM)
# ============================================================

class TestThreeStagePrompt:
    def test_prompt_contains_transcript_placeholder(self):
        from core.llm.prompts import get_three_stage_prompt
        prompt = get_three_stage_prompt("zh")
        assert "{transcript}" in prompt

    def test_prompt_zh_and_en(self):
        from core.llm.prompts import get_three_stage_prompt
        zh = get_three_stage_prompt("zh")
        en = get_three_stage_prompt("en")
        assert "预习" in zh or "概述" in zh
        assert "overview" in en.lower()

    def test_prompt_with_segments_adds_citation(self):
        from core.llm.prompts import get_three_stage_prompt
        with_segs = get_three_stage_prompt("zh", has_segments=True)
        without_segs = get_three_stage_prompt("zh", has_segments=False)
        assert "引用" in with_segs
        assert "引用" not in without_segs
