"""Validation and rendering for host-authored external fact checks."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any


FACT_CHECK_MODES = {"off", "auto", "important", "all", "required"}
FACT_CHECK_STATUSES = {
    "confirmed",
    "partially_confirmed",
    "contradicted",
    "outdated",
    "disputed",
    "unverified",
}
FACT_CLASSIFICATIONS = {"objective_fact", "time_sensitive_fact"}
SKIP_REASONS = {
    "user_disabled",
    "no_web_access",
    "no_search_tool",
    "no_page_reader",
    "insufficient_source_evaluation",
    "time_or_budget_limit",
    "source_unavailable",
}
SOURCE_TYPES = {"primary", "secondary"}
TIMESTAMP = re.compile(r"^\d{1,2}:[0-5]\d(?::[0-5]\d)?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "key",
    "password",
    "secret",
    "signature",
    "token",
}


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"fact_check.{field} is required")
    return text


def _source(source: Any, claim_index: int, source_index: int) -> dict[str, str]:
    if not isinstance(source, dict):
        raise ValueError(
            f"fact_check.claims[{claim_index}].sources[{source_index}] "
            "must be an object"
        )
    title = _required_text(
        source.get("title"),
        f"claims[{claim_index}].sources[{source_index}].title",
    )
    url = _required_text(
        source.get("url"),
        f"claims[{claim_index}].sources[{source_index}].url",
    )
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            f"fact_check.claims[{claim_index}].sources[{source_index}].url "
            "must be a public http(s) URL without credentials"
        )
    query_keys = {
        key.casefold()
        for key, _value in urllib.parse.parse_qsl(
            parsed.query, keep_blank_values=True
        )
    }
    if query_keys & SENSITIVE_QUERY_KEYS:
        raise ValueError(
            f"fact_check.claims[{claim_index}].sources[{source_index}].url "
            "must not contain credential-like query parameters"
        )
    source_type = str(source.get("source_type") or "").strip()
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            f"fact_check.claims[{claim_index}].sources[{source_index}]"
            ".source_type must be primary or secondary"
        )
    return {"title": title, "url": url, "source_type": source_type}


def normalize_fact_check(
    value: Any,
    *,
    configured_mode: str = "auto",
) -> dict[str, Any]:
    """Validate host-authored fact-check data and return normalized content."""
    if configured_mode not in FACT_CHECK_MODES:
        raise ValueError(f"Unknown configured fact-check mode: {configured_mode}")
    if not isinstance(value, dict):
        raise ValueError("fact_check must be an object")
    if value.get("schema_version", 1) != 1:
        raise ValueError("fact_check.schema_version must be 1")

    status = str(value.get("status") or "").strip()
    mode = str(value.get("mode") or configured_mode).strip()
    if mode not in FACT_CHECK_MODES:
        raise ValueError(f"Unknown fact-check mode: {mode}")
    if mode == "off" and status != "skipped":
        raise ValueError("off fact checking must be explicitly skipped")
    if status == "skipped":
        reason = str(value.get("reason") or "").strip()
        if reason not in SKIP_REASONS:
            raise ValueError(
                "fact_check.reason must use a supported skip reason code"
            )
        if mode == "required" or configured_mode == "required":
            raise ValueError("required fact checking cannot be skipped")
        if mode == "off" and reason != "user_disabled":
            raise ValueError("off fact checking must use reason user_disabled")
        if value.get("claims"):
            raise ValueError("skipped fact_check must not contain claims")
        return {
            "schema_version": 1,
            "status": "skipped",
            "mode": mode,
            "reason": reason,
            "message": _required_text(value.get("message"), "message"),
            "claims": [],
        }
    if status != "completed":
        raise ValueError("fact_check.status must be completed or skipped")

    checked_at = str(value.get("checked_at") or "").strip()
    if not DATE.fullmatch(checked_at):
        raise ValueError("fact_check.checked_at must use YYYY-MM-DD")
    claims = value.get("claims")
    if not isinstance(claims, list):
        raise ValueError("fact_check.claims must be an array")

    normalized_claims = []
    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ValueError(
                f"fact_check.claims[{claim_index}] must be an object"
            )
        timestamp = _required_text(
            claim.get("timestamp"),
            f"claims[{claim_index}].timestamp",
        )
        if not TIMESTAMP.fullmatch(timestamp):
            raise ValueError(
                f"fact_check.claims[{claim_index}].timestamp is invalid"
            )
        classification = str(claim.get("classification") or "").strip()
        if classification not in FACT_CLASSIFICATIONS:
            raise ValueError(
                f"fact_check.claims[{claim_index}].classification must "
                "describe an objective or time-sensitive fact"
            )
        claim_status = str(claim.get("status") or "").strip()
        if claim_status not in FACT_CHECK_STATUSES:
            raise ValueError(
                f"fact_check.claims[{claim_index}].status is unsupported"
            )
        sources_value = claim.get("sources") or []
        if not isinstance(sources_value, list):
            raise ValueError(
                f"fact_check.claims[{claim_index}].sources must be an array"
            )
        sources = [
            _source(source, claim_index, source_index)
            for source_index, source in enumerate(sources_value)
        ]
        if claim_status != "unverified" and not sources:
            raise ValueError(
                f"fact_check.claims[{claim_index}] requires a linked source"
            )
        if any(
            source["source_type"] == "primary"
            for source in sources
        ):
            sources.sort(
                key=lambda source: source["source_type"] != "primary"
            )
        normalized_claims.append(
            {
                "claim": _required_text(
                    claim.get("claim"),
                    f"claims[{claim_index}].claim",
                ),
                "timestamp": timestamp,
                "classification": classification,
                "status": claim_status,
                "video_statement": _required_text(
                    claim.get("video_statement"),
                    f"claims[{claim_index}].video_statement",
                ),
                "verified_result": _required_text(
                    claim.get("verified_result"),
                    f"claims[{claim_index}].verified_result",
                ),
                "sources": sources,
            }
        )
    return {
        "schema_version": 1,
        "status": "completed",
        "mode": mode,
        "checked_at": checked_at,
        "claims": normalized_claims,
    }


def render_fact_check(value: dict[str, Any]) -> str:
    """Render normalized fact-check data for the note understanding section."""
    lines = ["## 外部事实核验", ""]
    if value["status"] == "skipped":
        lines.extend(
            [
                (
                    "> 外部事实核验：已跳过。"
                    f"原因代码：`{value['reason']}`。"
                ),
                f"> {value['message']}",
                (
                    "> 下列相关内容仅表示视频中的陈述，"
                    "不代表已由独立来源确认。"
                ),
            ]
        )
        return "\n".join(lines)

    claims = value["claims"]
    if not claims:
        lines.append(
            f"> 外部事实核验已完成（{value['checked_at']}），"
            "未发现值得独立核验的客观声明。"
        )
        return "\n".join(lines)

    status_names = {
        "confirmed": "已确认",
        "partially_confirmed": "部分确认",
        "contradicted": "存在矛盾",
        "outdated": "已过时",
        "disputed": "存在争议",
        "unverified": "未验证",
    }
    for index, claim in enumerate(claims, 1):
        lines.extend(
            [
                f"### 声明 {index}（{claim['timestamp']}）",
                "",
                f"- 视频陈述：{claim['video_statement']}",
                f"- 核验状态：{status_names[claim['status']]}",
                f"- 核验结果：{claim['verified_result']}",
                f"- 检索日期：{value['checked_at']}",
            ]
        )
        if claim["sources"]:
            lines.append("- 来源：")
            for source in claim["sources"]:
                lines.append(
                    f"  - [{source['title']}]({source['url']})"
                    f"（{source['source_type']}）"
                )
        else:
            lines.append("- 来源：未找到可链接来源")
        lines.append("")
    return "\n".join(lines).rstrip()
