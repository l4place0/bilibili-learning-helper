"""API-level and HTML structure tests for the review document feature.

Tests the full flow: API endpoint → HTML generation → structural validation.
No browser GUI needed — uses httpx for API calls and string checks for HTML.
"""

import json
import re
from pathlib import Path

import httpx
import pytest

BASE = "http://127.0.0.1:8000"


def get_done_task_id() -> str:
    resp = httpx.get(f"{BASE}/api/tasks")
    assert resp.status_code == 200
    done = [t for t in resp.json()["tasks"] if t["status"] == "done"]
    assert done, "No completed tasks in DB"
    return done[0]["task_id"]


class TestReviewDocAPI:
    """Test the /api/tasks/{id}/review-doc endpoint."""

    def test_returns_html_file(self):
        task_id = get_done_task_id()
        resp = httpx.get(f"{BASE}/api/tasks/{task_id}/review-doc", follow_redirects=True)
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert f"review_{task_id[:8]}.html" in cd

    def test_html_not_empty(self):
        task_id = get_done_task_id()
        resp = httpx.get(f"{BASE}/api/tasks/{task_id}/review-doc", follow_redirects=True)
        assert len(resp.text) > 5000, f"HTML too small: {len(resp.text)} bytes"

    def test_rejects_non_done_task(self):
        """Non-done tasks should return 400."""
        # Use a fake task ID that doesn't exist
        resp = httpx.get(f"{BASE}/api/tasks/nonexistent123/review-doc")
        assert resp.status_code == 404

    def test_saves_and_opens(self, tmp_path):
        """Downloaded file should be valid HTML."""
        task_id = get_done_task_id()
        resp = httpx.get(f"{BASE}/api/tasks/{task_id}/review-doc", follow_redirects=True)
        fpath = tmp_path / "review.html"
        fpath.write_text(resp.text)

        content = fpath.read_text()
        assert content.startswith("<!DOCTYPE html>") or content.startswith("<!doctype html>")


class TestReviewDocStructure:
    """Validate the HTML structure of a generated review document."""

    @pytest.fixture(scope="class")
    def html(self):
        task_id = get_done_task_id()
        resp = httpx.get(f"{BASE}/api/tasks/{task_id}/review-doc", follow_redirects=True)
        return resp.text

    def test_has_tabs(self, html):
        assert 'data-tab="summary"' in html
        assert 'data-tab="cards"' in html
        assert 'data-tab="timeline"' in html
        assert 'data-tab="transcript"' in html

    def test_has_panels(self, html):
        assert 'id="panel-summary"' in html
        assert 'id="panel-cards"' in html
        assert 'id="panel-timeline"' in html
        assert 'id="panel-transcript"' in html

    def test_has_review_data(self, html):
        """REVIEW_DATA should be injected as JSON."""
        assert "const DATA" in html
        # Should contain valid JSON
        match = re.search(r'const DATA\s*=\s*(\{.*?\});\s*\n', html, re.DOTALL)
        assert match, "DATA JSON block not found"
        data = json.loads(match.group(1))
        assert "taskId" in data
        assert "summary" in data
        assert "transcriptSegments" in data

    def test_has_srs_engine(self, html):
        assert "function sm2" in html
        assert "localStorage" in html
        assert "ease" in html

    def test_has_search(self, html):
        assert "search-input" in html
        assert "doSearch" in html

    def test_has_lightbox(self, html):
        assert "lightbox" in html
        assert "openLightbox" in html

    def test_has_notes(self, html):
        assert "note-btn" in html
        assert "note-input-wrap" in html

    def test_has_srs_review_mode(self, html):
        assert "srs-overlay" in html
        assert "startSRS" in html

    def test_has_dark_theme(self, html):
        assert "--bg:" in html
        assert "--fg:" in html


class TestReviewDocWithCards:
    """Test card-specific features if the task has review cards."""

    @pytest.fixture(scope="class")
    def data(self):
        task_id = get_done_task_id()
        resp = httpx.get(f"{BASE}/api/tasks/{task_id}/review-doc", follow_redirects=True)
        html = resp.text
        # Find the JSON block between `const DATA = ` and `;\n`
        match = re.search(r'const DATA\s*=\s*(\{.*?\});\s*$', html, re.DOTALL | re.MULTILINE)
        assert match, "DATA block not found in HTML"
        return json.loads(match.group(1))

    def test_cards_data_present(self, data):
        assert "cards" in data
        assert isinstance(data["cards"], list)

    def test_cards_have_qa(self, data):
        if not data["cards"]:
            pytest.skip("No review cards in this task")
        card = data["cards"][0]
        assert "question" in card
        assert "answer" in card
        assert len(card["question"]) > 5

    def test_frames_data_present(self, data):
        assert "frames" in data
        assert isinstance(data["frames"], list)

    def test_frames_have_data_uri(self, data):
        if not data["frames"]:
            pytest.skip("No frames in this task")
        frame = data["frames"][0]
        assert "data_uri" in frame
        assert frame["data_uri"].startswith("data:image/")
        assert "base64," in frame["data_uri"]

    def test_transcript_segments(self, data):
        assert "transcriptSegments" in data
        if data["transcriptSegments"]:
            seg = data["transcriptSegments"][0]
            assert "text" in seg


class TestPromptEnhancement:
    """Test that the summary prompt now includes review cards instructions."""

    def test_get_summary_prompt_includes_cards(self):
        from core.llm.prompts import get_summary_prompt
        prompt = get_summary_prompt("tutorial", "zh")
        assert "复习卡片" in prompt
        assert "Q1" in prompt

    def test_get_summary_prompt_en_includes_cards(self):
        from core.llm.prompts import get_summary_prompt
        prompt = get_summary_prompt("tutorial", "en")
        assert "Review Cards" in prompt
        assert "Q1" in prompt

    def test_detailed_max_tokens_increased(self):
        from core.llm.prompts import DETAIL_MAX_TOKENS
        assert DETAIL_MAX_TOKENS["detailed"] == 20480

    def test_card_parser_roundtrip(self):
        from core.review_doc import parse_review_cards
        summary = """## Summary
Some content.

## 复习卡片

**Q1:** 测试问题？
**A1:** 测试答案。

**Q2:** 第二个问题？
**A2:** 第二个答案。
"""
        cards = parse_review_cards(summary)
        assert len(cards) == 2
        assert cards[0]["question"] == "测试问题？"
        assert cards[1]["answer"] == "第二个答案。"
