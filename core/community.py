"""Bilibili comment and current-danmaku primitives.

The module intentionally keeps network collection deterministic and leaves
semantic interpretation to the host AI. Raw public records are written as
JSONL with one metadata record followed by content records.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import statistics
import tempfile
import time
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any, Callable, Iterable

import httpx


API_ROOT = "https://api.bilibili.com"
XML_DANMAKU_ROOT = "https://comment.bilibili.com"
SEGMENT_SECONDS = 360
SCHEMA_VERSION = 1
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
}
WBI_MIXIN_KEY_ORDER = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)


def _atomic_write(path: Path, content: str) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_staged = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    staged = Path(raw_staged)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    content = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        for record in records
    )
    _atomic_write(path, content)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def read_jsonl(path: Path, record_type: str) -> tuple[dict, list[dict]]:
    metadata: dict[str, Any] = {}
    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            item = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSONL at line {line_number}: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"JSONL line {line_number} must contain an object")
        if item.get("record_type") == "metadata":
            metadata = item
        elif item.get("record_type") == record_type:
            records.append(item)
    if not metadata:
        raise ValueError("JSONL does not contain a metadata record")
    return metadata, records


def load_netscape_cookies(path: Path | None) -> dict[str, str]:
    if path is None or not path.expanduser().is_file():
        return {}
    jar = MozillaCookieJar(str(path.expanduser()))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception as exc:
        raise ValueError(f"invalid Netscape cookie file: {path}") from exc
    return {cookie.name: cookie.value for cookie in jar}


class BilibiliCommunityClient:
    def __init__(
        self,
        cookies_path: Path | None = None,
        client: httpx.Client | None = None,
    ):
        self.authenticated = False
        self._owns_client = client is None
        if client is None:
            cookies = load_netscape_cookies(cookies_path)
            self.authenticated = bool(cookies.get("SESSDATA"))
            client = httpx.Client(
                headers=HEADERS,
                cookies=cookies,
                follow_redirects=True,
                timeout=httpx.Timeout(30.0, read=60.0),
            )
        self.client = client
        self._wbi_key: str | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> BilibiliCommunityClient:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def _request(self, endpoint: str, params: dict[str, Any]) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.get(endpoint, params=params)
                if response.status_code in {412, 429} or response.status_code >= 500:
                    raise RuntimeError(f"Bilibili HTTP {response.status_code}")
                response.raise_for_status()
                return response
            except (httpx.HTTPError, RuntimeError) as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2**attempt)
        raise RuntimeError(f"Bilibili request failed: {last_error}")

    def _json(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = self._request(endpoint, params).json()
        if payload.get("code") != 0:
            raise RuntimeError(
                f"Bilibili API error {payload.get('code')}: "
                f"{payload.get('message', 'unknown error')}"
            )
        return payload.get("data") or {}

    def _get_wbi_key(self) -> str:
        if self._wbi_key:
            return self._wbi_key
        payload = self._request(f"{API_ROOT}/x/web-interface/nav", {}).json()
        data = payload.get("data") or {}
        wbi_image = data.get("wbi_img") or {}
        keys = []
        for name in ("img_url", "sub_url"):
            filename = str(wbi_image.get(name) or "").rsplit("/", 1)[-1]
            keys.append(filename.split(".", 1)[0])
        raw_key = "".join(keys)
        if len(raw_key) < 64:
            raise RuntimeError("Bilibili nav response did not include WBI keys")
        self._wbi_key = "".join(raw_key[index] for index in WBI_MIXIN_KEY_ORDER)[:32]
        return self._wbi_key

    def _sign_wbi(self, params: dict[str, Any]) -> dict[str, Any]:
        signed = {**params, "wts": round(time.time())}
        filtered = {
            key: "".join(
                character for character in str(value) if character not in "!'()*"
            )
            for key, value in sorted(signed.items())
        }
        query = urllib.parse.urlencode(
            filtered,
            quote_via=urllib.parse.quote,
            safe="",
        )
        signed["w_rid"] = hashlib.md5(
            f"{query}{self._get_wbi_key()}".encode()
        ).hexdigest()
        return signed

    def resolve_video(self, url: str) -> dict[str, Any]:
        match = re.search(r"bilibili\.com/video/(BV[\w]+)", url)
        if not match:
            shared_urls = re.findall(r"https?://[^\s]+", url)
            short_url = next(
                (
                    value.rstrip("，。,.!！?？)]}")
                    for value in shared_urls
                    if urllib.parse.urlparse(value).hostname in {"b23.tv", "www.b23.tv"}
                ),
                "",
            )
            if short_url:
                resolved = self._request(short_url, {})
                url = str(resolved.url)
                match = re.search(r"bilibili\.com/video/(BV[\w]+)", url)
        if not match:
            raise ValueError("comments and danmaku currently require a Bilibili URL")
        bvid = match.group(1)
        view = self._json(f"{API_ROOT}/x/web-interface/view", {"bvid": bvid})
        pages = view.get("pages") or []
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        try:
            page_number = int((query.get("p") or ["1"])[0])
        except ValueError as exc:
            raise ValueError("Bilibili page parameter must be an integer") from exc
        if pages:
            if page_number < 1 or page_number > len(pages):
                raise ValueError(
                    f"Bilibili page {page_number} is outside 1..{len(pages)}"
                )
            page = pages[page_number - 1]
        else:
            page = view
        return {
            "bvid": bvid,
            "aid": view.get("aid"),
            "cid": page.get("cid") or view.get("cid"),
            "duration": page.get("duration") or view.get("duration") or 0,
            "page": page_number,
            "title": view.get("title") or "",
            "reported_comment_count": (view.get("stat") or {}).get("reply"),
            "reported_danmaku_count": (view.get("stat") or {}).get("danmaku"),
        }

    def fetch_comments(
        self,
        url: str,
        mode: str = "hot",
        limit: int = 50,
        progress: Callable[[int, int | None], None] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if mode not in {"hot", "all"}:
            raise ValueError("comment mode must be hot or all")
        video = self.resolve_video(url)
        comments: list[dict[str, Any]] = []
        seen: set[str] = set()
        total_available = None
        sort_mode = 3 if mode == "hot" else 2
        next_offset = ""
        seen_offsets: set[str] = set()
        while True:
            previous_count = len(comments)
            data = self._json(
                f"{API_ROOT}/x/v2/reply/wbi/main",
                self._sign_wbi(
                    {
                        "oid": video["aid"],
                        "type": 1,
                        "mode": sort_mode,
                        "pagination_str": json.dumps(
                            {"offset": next_offset},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        "plat": 1,
                        "web_location": 1315875,
                    }
                ),
            )
            if data.get("v_voucher"):
                raise RuntimeError("Bilibili rejected the WBI comment request")
            cursor = data.get("cursor") or {}
            total_available = cursor.get("all_count", total_available)
            replies = data.get("replies") or []
            if not replies:
                break
            for reply in replies:
                comment_id = str(reply.get("rpid_str") or reply.get("rpid") or "")
                if not comment_id or comment_id in seen:
                    continue
                seen.add(comment_id)
                member = reply.get("member") or {}
                content = reply.get("content") or {}
                up_action = reply.get("up_action") or {}
                comments.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "record_type": "comment",
                        "comment_id": comment_id,
                        "author": member.get("uname") or "",
                        "author_id": str(
                            member.get("mid_str") or member.get("mid") or ""
                        ),
                        "text": content.get("message") or "",
                        "created_at": reply.get("ctime"),
                        "likes": int(reply.get("like") or 0),
                        "reply_count": int(reply.get("rcount") or 0),
                        "uploader_liked": bool(up_action.get("like")),
                        "uploader_replied": bool(up_action.get("reply")),
                    }
                )
                if limit > 0 and len(comments) >= limit:
                    break
            if progress:
                progress(len(comments), total_available)
            if limit > 0 and len(comments) >= limit:
                break
            if len(comments) == previous_count:
                break
            pagination = cursor.get("pagination_reply") or {}
            next_offset = str(pagination.get("next_offset") or "")
            if cursor.get("is_end") or not next_offset or next_offset in seen_offsets:
                break
            seen_offsets.add(next_offset)
            time.sleep(0.15)
        if mode == "hot":
            comments.sort(
                key=lambda item: (
                    item["likes"],
                    item["reply_count"],
                    item["created_at"] or 0,
                ),
                reverse=True,
            )
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "metadata",
            "kind": "comments",
            "source": "bilibili_reply_wbi_api",
            "scope": "top_level_hot" if mode == "hot" else "top_level_all_accessible",
            "authenticated": self.authenticated,
            "bvid": video["bvid"],
            "aid": video["aid"],
            "title": video["title"],
            "reported_comment_count": video["reported_comment_count"],
            "api_available_count": total_available,
            "fetched_count": len(comments),
            "nested_replies_included": False,
        }
        return metadata, comments

    def fetch_danmaku(
        self,
        url: str,
        progress: Callable[[int, int], None] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        video = self.resolve_video(url)
        segment_count = max(1, math.ceil(video["duration"] / SEGMENT_SECONDS))
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        source = "bilibili_seg_so"
        coverage = "current_accessible"
        try:
            for segment_index in range(1, segment_count + 1):
                response = self._request(
                    f"{API_ROOT}/x/v2/dm/web/seg.so",
                    {
                        "type": 1,
                        "oid": video["cid"],
                        "pid": video["aid"],
                        "segment_index": segment_index,
                    },
                )
                for item in parse_danmaku_segment(response.content):
                    item["segment_index"] = segment_index
                    item_id = item["danmaku_id"]
                    if item_id and item_id in seen:
                        continue
                    if item_id:
                        seen.add(item_id)
                    records.append(item)
                if progress:
                    progress(segment_index, segment_count)
        except Exception:
            source = "bilibili_xml"
            coverage = "sampled_degraded"
            response = self._request(f"{XML_DANMAKU_ROOT}/{video['cid']}.xml", {})
            records = parse_danmaku_xml(response.content)
        records.sort(key=lambda item: (item["progress_ms"], item["danmaku_id"]))
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "record_type": "metadata",
            "kind": "danmaku",
            "source": source,
            "scope": coverage,
            "authenticated": self.authenticated,
            "complete_historical": False,
            "bvid": video["bvid"],
            "aid": video["aid"],
            "cid": video["cid"],
            "page": video["page"],
            "title": video["title"],
            "duration_seconds": video["duration"],
            "reported_danmaku_count": video["reported_danmaku_count"],
            "fetched_count": len(records),
            "segment_count": segment_count,
        }
        return metadata, records


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(data):
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
        if shift > 70:
            break
    raise ValueError("invalid protobuf varint")


def _protobuf_fields(data: bytes):
    position = 0
    while position < len(data):
        key, position = _read_varint(data, position)
        number, wire_type = key >> 3, key & 7
        if wire_type == 0:
            value, position = _read_varint(data, position)
        elif wire_type == 1:
            value, position = data[position : position + 8], position + 8
        elif wire_type == 2:
            length, position = _read_varint(data, position)
            value = data[position : position + length]
            position += length
        elif wire_type == 5:
            value, position = data[position : position + 4], position + 4
        else:
            raise ValueError(f"unsupported protobuf wire type: {wire_type}")
        if position > len(data):
            raise ValueError("truncated protobuf field")
        yield number, wire_type, value


def _text(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _parse_danmaku_element(data: bytes) -> dict[str, Any]:
    values: dict[int, Any] = {}
    for number, wire_type, value in _protobuf_fields(data):
        if wire_type == 0 or number in {6, 7, 10, 12}:
            values[number] = value
    danmaku_id = str(values.get(12) or values.get(1) or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "danmaku",
        "danmaku_id": danmaku_id,
        "progress_ms": int(values.get(2) or 0),
        "mode": int(values.get(3) or 0),
        "font_size": int(values.get(4) or 0),
        "color": int(values.get(5) or 0),
        "user_hash": _text(values.get(6) or b""),
        "text": _text(values.get(7) or b""),
        "created_at": int(values.get(8) or 0),
        "weight": int(values.get(9) or 0),
        "pool": int(values.get(11) or 0),
        "attributes": int(values.get(13) or 0),
        "high_liked": bool(int(values.get(13) or 0) & 4),
    }


def parse_danmaku_segment(data: bytes) -> list[dict[str, Any]]:
    if data.lstrip().startswith(b"{"):
        try:
            payload = json.loads(data)
        except json.JSONDecodeError as exc:
            raise ValueError("danmaku endpoint returned invalid JSON") from exc
        raise RuntimeError(
            f"Bilibili danmaku API error {payload.get('code')}: "
            f"{payload.get('message', 'unknown error')}"
        )
    return [
        _parse_danmaku_element(value)
        for number, wire_type, value in _protobuf_fields(data)
        if number == 1 and wire_type == 2
    ]


def parse_danmaku_xml(data: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(data)
    records = []
    for element in root.findall("d"):
        values = (element.get("p") or "").split(",")
        if len(values) < 8:
            continue
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "record_type": "danmaku",
                "danmaku_id": values[7],
                "progress_ms": round(float(values[0]) * 1000),
                "mode": int(values[1]),
                "font_size": int(values[2]),
                "color": int(values[3]),
                "user_hash": values[6],
                "text": element.text or "",
                "created_at": int(values[4]),
                "weight": 0,
                "pool": int(values[5]),
                "attributes": 0,
                "high_liked": False,
            }
        )
    return records


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower().strip()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)


SENTIMENT_LEXICONS = {
    "positive": ("好", "牛", "赞", "厉害", "喜欢", "支持", "优秀", "学到了"),
    "negative": ("差", "烂", "垃圾", "错误", "不行", "失望", "离谱"),
    "question": ("?", "？", "吗", "怎么", "为什么", "啥", "什么"),
    "surprise": ("卧槽", "震惊", "居然", "竟然", "原来"),
    "joke": ("哈哈", "笑死", "绷不住", "草", "乐"),
}


def _sentiment_labels(text: str) -> list[str]:
    return sorted(
        label
        for label, words in SENTIMENT_LEXICONS.items()
        if any(word in text for word in words)
    )


def _representative_danmaku(
    items: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    candidates = []
    seen: set[str] = set()
    for item in items:
        text = str(item.get("text") or "").strip()
        normalized = normalize_text(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        labels = _sentiment_labels(text)
        candidates.append(
            {
                "progress_ms": int(item.get("progress_ms") or 0),
                "text": text,
                "signals": labels,
                "_rank": (
                    bool(labels),
                    len(labels),
                    bool(item.get("high_liked")),
                    int(item.get("weight") or 0),
                    min(len(normalized), 80),
                    -int(item.get("progress_ms") or 0),
                ),
            }
        )
    candidates.sort(key=lambda item: item["_rank"], reverse=True)
    return [
        {key: value for key, value in item.items() if key != "_rank"}
        for item in candidates[:limit]
    ]


def analyze_danmaku(
    metadata: dict[str, Any],
    records: list[dict[str, Any]],
    bucket_seconds: int = 30,
    hotspot_limit: int = 10,
    cluster_limit: int = 30,
) -> dict[str, Any]:
    if bucket_seconds <= 0:
        raise ValueError("bucket seconds must be positive")
    buckets: Counter[int] = Counter()
    cluster_counts: Counter[str] = Counter()
    representatives: dict[str, str] = {}
    sentiment_counts: Counter[str] = Counter()
    bucket_sentiment_counts: dict[int, Counter[str]] = {}
    bucket_records: dict[int, list[dict[str, Any]]] = {}
    for item in records:
        bucket = int((item.get("progress_ms") or 0) / (bucket_seconds * 1000))
        buckets[bucket] += 1
        bucket_records.setdefault(bucket, []).append(item)
        text = str(item.get("text") or "")
        normalized = normalize_text(text)
        if normalized:
            cluster_counts[normalized] += 1
            representatives.setdefault(normalized, text)
        labels = _sentiment_labels(text)
        for label in labels:
            sentiment_counts[label] += 1
            bucket_sentiment_counts.setdefault(bucket, Counter())[label] += 1
    bucket_values = list(buckets.values())
    baseline = statistics.median(bucket_values) if bucket_values else 0
    hotspots = []
    for bucket, count in buckets.items():
        score = (count - baseline) / math.sqrt(max(baseline, 1))
        hotspots.append(
            {
                "start_seconds": bucket * bucket_seconds,
                "end_seconds": (bucket + 1) * bucket_seconds,
                "count": count,
                "burst_score": round(score, 4),
            }
        )
    hotspots.sort(key=lambda item: (item["burst_score"], item["count"]), reverse=True)
    time_buckets = []
    for bucket in sorted(buckets):
        signals = dict(sorted(bucket_sentiment_counts.get(bucket, Counter()).items()))
        peak = max(signals.values(), default=0)
        time_buckets.append(
            {
                "start_seconds": bucket * bucket_seconds,
                "end_seconds": (bucket + 1) * bucket_seconds,
                "count": buckets[bucket],
                "sentiment_signals": signals,
                "leading_signals": [
                    label for label, count in signals.items() if count == peak
                ],
                "representative_danmaku": _representative_danmaku(
                    bucket_records[bucket]
                ),
            }
        )
    clusters = [
        {
            "representative_text": representatives[normalized],
            "normalized_text": normalized,
            "count": count,
        }
        for normalized, count in cluster_counts.most_common(cluster_limit)
        if count >= 2
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "danmaku_analysis_candidates",
        "source_metadata": metadata,
        "record_count": len(records),
        "bucket_seconds": bucket_seconds,
        "baseline_bucket_count": baseline,
        "time_buckets": time_buckets,
        "hotspots": hotspots[:hotspot_limit],
        "repetition_clusters": clusters,
        "sentiment_signals": dict(sorted(sentiment_counts.items())),
        "method": {
            "clustering": "exact_normalized_repetition",
            "sentiment": "transparent_lexicon_signals",
            "time_bucket_signals": "same_lexicon_signals_grouped_by_progress_ms",
            "representatives": "signal_rich_unique_then_weight",
            "hotspots": "count_vs_median_burst_score",
        },
        "host_ai_review_required": True,
    }


def select_comment_candidates(
    metadata: dict[str, Any],
    comments: list[dict[str, Any]],
    limit: int = 20,
) -> dict[str, Any]:
    if limit <= 0:
        raise ValueError("comment candidate limit must be positive")
    candidates = []
    seen_text: set[str] = set()
    for comment in comments:
        text = str(comment.get("text") or "").strip()
        normalized = normalize_text(text)
        if not normalized or normalized in seen_text:
            continue
        seen_text.add(normalized)
        likes = max(0, int(comment.get("likes") or 0))
        replies = max(0, int(comment.get("reply_count") or 0))
        length_score = min(len(normalized) / 80, 2.0)
        low_information_penalty = 3.0 if len(normalized) < 8 else 0.0
        score = (
            math.log1p(likes) * 3
            + math.log1p(replies) * 2
            + (3 if comment.get("uploader_liked") else 0)
            + (2 if comment.get("uploader_replied") else 0)
            + length_score
            - low_information_penalty
        )
        candidates.append(
            {
                **comment,
                "quality_candidate_score": round(score, 4),
                "score_signals": {
                    "likes": likes,
                    "reply_count": replies,
                    "uploader_liked": bool(comment.get("uploader_liked")),
                    "uploader_replied": bool(comment.get("uploader_replied")),
                    "normalized_length": len(normalized),
                },
            }
        )
    candidates.sort(
        key=lambda item: (
            item["quality_candidate_score"],
            item.get("likes", 0),
        ),
        reverse=True,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "comment_quality_candidates",
        "source_metadata": metadata,
        "candidate_count": min(limit, len(candidates)),
        "candidates": candidates[:limit],
        "method": "engagement_information_heuristic",
        "host_ai_review_required": True,
        "warning": "Popularity is not evidence of factual correctness.",
    }
