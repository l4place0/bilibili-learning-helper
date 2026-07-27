"""Tests for structured external fact-check validation and rendering."""

import pytest

from core.fact_check import normalize_fact_check, render_fact_check


def completed_claim():
    return {
        "schema_version": 1,
        "status": "completed",
        "mode": "important",
        "checked_at": "2026-07-27",
        "claims": [
            {
                "claim": "The product launched in 2025.",
                "timestamp": "27:30",
                "classification": "time_sensitive_fact",
                "status": "confirmed",
                "video_statement": "The product launched in 2025.",
                "verified_result": "The official announcement is dated 2025.",
                "sources": [
                    {
                        "title": "Secondary report",
                        "url": "https://news.example/report",
                        "source_type": "secondary",
                    },
                    {
                        "title": "Official announcement",
                        "url": "https://example.com/announcement",
                        "source_type": "primary",
                    },
                ],
            }
        ],
    }


def test_completed_fact_check_prefers_primary_source():
    result = normalize_fact_check(completed_claim())

    assert result["status"] == "completed"
    assert result["claims"][0]["sources"][0]["source_type"] == "primary"
    rendered = render_fact_check(result)
    assert "## 外部事实核验" in rendered
    assert "[Official announcement]" in rendered
    assert "27:30" in rendered


def test_completed_without_claims_is_distinct_from_skipped():
    completed = normalize_fact_check(
        {
            "status": "completed",
            "mode": "auto",
            "checked_at": "2026-07-27",
            "claims": [],
        }
    )
    skipped = normalize_fact_check(
        {
            "status": "skipped",
            "mode": "auto",
            "reason": "no_web_access",
            "message": "Host cannot access the web.",
            "claims": [],
        }
    )

    assert "未发现值得独立核验" in render_fact_check(completed)
    assert "已跳过" in render_fact_check(skipped)
    assert "不代表已由独立来源确认" in render_fact_check(skipped)


def test_required_fact_check_cannot_be_skipped():
    with pytest.raises(ValueError, match="cannot be skipped"):
        normalize_fact_check(
            {
                "status": "skipped",
                "mode": "required",
                "reason": "no_web_access",
                "message": "No web access.",
                "claims": [],
            },
            configured_mode="required",
        )


def test_subjective_classification_is_rejected():
    value = completed_claim()
    value["claims"][0]["classification"] = "opinion"

    with pytest.raises(ValueError, match="objective or time-sensitive"):
        normalize_fact_check(value)


def test_verified_claim_requires_linked_source():
    value = completed_claim()
    value["claims"][0]["sources"] = []

    with pytest.raises(ValueError, match="requires a linked source"):
        normalize_fact_check(value)


def test_unverified_claim_may_have_no_source():
    value = completed_claim()
    value["claims"][0]["status"] = "unverified"
    value["claims"][0]["verified_result"] = "No suitable source was found."
    value["claims"][0]["sources"] = []

    result = normalize_fact_check(value)

    assert result["claims"][0]["status"] == "unverified"


def test_off_mode_requires_explicit_user_disabled_skip():
    with pytest.raises(ValueError, match="explicitly skipped"):
        normalize_fact_check(
            {
                "status": "completed",
                "mode": "off",
                "checked_at": "2026-07-27",
                "claims": [],
            }
        )

    with pytest.raises(ValueError, match="user_disabled"):
        normalize_fact_check(
            {
                "status": "skipped",
                "mode": "off",
                "reason": "no_web_access",
                "message": "disabled",
            }
        )


def test_source_url_rejects_credential_query_parameters():
    value = completed_claim()
    value["claims"][0]["sources"][0]["url"] = (
        "https://example.test/report?api_key=secret"
    )

    with pytest.raises(ValueError, match="credential-like"):
        normalize_fact_check(value)
