from pathlib import Path

import httpx

from core.community import (
    BilibiliCommunityClient,
    analyze_danmaku,
    parse_danmaku_segment,
    parse_danmaku_xml,
    read_jsonl,
    select_comment_candidates,
    write_jsonl,
)


def _varint(value: int) -> bytes:
    result = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        result.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(result)


def _varint_field(number: int, value: int) -> bytes:
    return _varint(number << 3) + _varint(value)


def _bytes_field(number: int, value: bytes) -> bytes:
    return _varint((number << 3) | 2) + _varint(len(value)) + value


def _danmaku_segment(*items: tuple[int, int, str]) -> bytes:
    output = b""
    for danmaku_id, progress_ms, text in items:
        element = b"".join(
            [
                _varint_field(1, danmaku_id),
                _varint_field(2, progress_ms),
                _bytes_field(6, b"user-hash"),
                _bytes_field(7, text.encode()),
                _varint_field(8, 123456789),
                _varint_field(13, 4),
            ]
        )
        output += _bytes_field(1, element)
    return output


def _view_payload():
    return {
        "code": 0,
        "data": {
            "aid": 42,
            "cid": 99,
            "duration": 420,
            "title": "Test video",
            "pages": [{"cid": 99, "duration": 420}],
            "stat": {"reply": 2, "danmaku": 2},
        },
    }


def test_parse_danmaku_segment_preserves_analysis_fields():
    records = parse_danmaku_segment(_danmaku_segment((123, 4500, "学到了")))

    assert records == [
        {
            "schema_version": 1,
            "record_type": "danmaku",
            "danmaku_id": "123",
            "progress_ms": 4500,
            "mode": 0,
            "font_size": 0,
            "color": 0,
            "user_hash": "user-hash",
            "text": "学到了",
            "created_at": 123456789,
            "weight": 0,
            "pool": 0,
            "attributes": 4,
            "high_liked": True,
        }
    ]


def test_parse_danmaku_xml():
    xml = (
        '<?xml version="1.0"?><i><d p="1.5,1,25,16777215,10,0,abc,99">测试</d></i>'
    ).encode()

    records = parse_danmaku_xml(xml)

    assert records[0]["danmaku_id"] == "99"
    assert records[0]["progress_ms"] == 1500
    assert records[0]["text"] == "测试"


def test_fetch_comments_only_returns_top_level_records():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/x/web-interface/view":
            return httpx.Response(200, json=_view_payload())
        if request.url.path == "/x/web-interface/nav":
            return httpx.Response(
                200,
                json={
                    "code": -101,
                    "data": {
                        "wbi_img": {
                            "img_url": f"https://example.com/{'a' * 32}.png",
                            "sub_url": f"https://example.com/{'b' * 32}.png",
                        }
                    },
                },
            )
        if request.url.path == "/x/v2/reply/wbi/main":
            assert request.url.params["w_rid"]
            replies = [
                {
                    "rpid": 1,
                    "member": {"mid": 7, "uname": "author"},
                    "content": {"message": "详细补充材料"},
                    "ctime": 10,
                    "like": 25,
                    "rcount": 3,
                    "up_action": {"like": True},
                    "replies": [{"rpid": 2}],
                }
            ]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "cursor": {"all_count": 1, "is_end": True},
                        "replies": replies,
                    },
                },
            )
        raise AssertionError(request.url)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = BilibiliCommunityClient(client=http_client)
        metadata, comments = client.fetch_comments(
            "https://www.bilibili.com/video/BV1234567890",
            mode="all",
            limit=0,
        )

    assert metadata["nested_replies_included"] is False
    assert metadata["scope"] == "top_level_all_accessible"
    assert len(comments) == 1
    assert comments[0]["likes"] == 25
    assert comments[0]["uploader_liked"] is True


def test_fetch_current_danmaku_segments_without_cookies():
    segments = {
        "1": _danmaku_segment((1, 1000, "第一段")),
        "2": _danmaku_segment((2, 370000, "第二段")),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/x/web-interface/view":
            return httpx.Response(200, json=_view_payload())
        if request.url.path == "/x/v2/dm/web/seg.so":
            return httpx.Response(
                200, content=segments[request.url.params["segment_index"]]
            )
        raise AssertionError(request.url)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = BilibiliCommunityClient(client=http_client)
        metadata, records = client.fetch_danmaku(
            "https://www.bilibili.com/video/BV1234567890"
        )

    assert metadata["authenticated"] is False
    assert metadata["scope"] == "current_accessible"
    assert metadata["segment_count"] == 2
    assert [item["danmaku_id"] for item in records] == ["1", "2"]


def test_danmaku_analysis_outputs_candidates_not_semantic_truth():
    metadata = {"record_type": "metadata", "source": "bilibili_seg_so"}
    records = [
        {"record_type": "danmaku", "progress_ms": 1000, "text": "哈哈厉害"},
        {"record_type": "danmaku", "progress_ms": 2000, "text": "哈哈厉害"},
        {"record_type": "danmaku", "progress_ms": 65000, "text": "为什么？"},
    ]

    result = analyze_danmaku(metadata, records, bucket_seconds=30)

    assert result["host_ai_review_required"] is True
    assert result["repetition_clusters"][0]["count"] == 2
    assert result["sentiment_signals"]["positive"] == 2
    assert result["sentiment_signals"]["question"] == 1
    assert result["hotspots"][0]["start_seconds"] == 0
    assert result["time_buckets"] == [
        {
            "start_seconds": 0,
            "end_seconds": 30,
            "count": 2,
            "sentiment_signals": {"joke": 2, "positive": 2},
            "leading_signals": ["joke", "positive"],
            "representative_danmaku": [
                {
                    "progress_ms": 1000,
                    "text": "哈哈厉害",
                    "signals": ["joke", "positive"],
                }
            ],
        },
        {
            "start_seconds": 60,
            "end_seconds": 90,
            "count": 1,
            "sentiment_signals": {"question": 1},
            "leading_signals": ["question"],
            "representative_danmaku": [
                {
                    "progress_ms": 65000,
                    "text": "为什么？",
                    "signals": ["question"],
                }
            ],
        },
    ]


def test_danmaku_time_bucket_representatives_prefer_signal_rich_unique_items():
    records = [
        {"progress_ms": 1000, "text": "普通弹幕", "weight": 20},
        {"progress_ms": 2000, "text": "普通弹幕", "weight": 30},
        {"progress_ms": 3000, "text": "为什么这么厉害", "weight": 1},
    ]

    bucket = analyze_danmaku({}, records)["time_buckets"][0]

    assert bucket["sentiment_signals"] == {"positive": 1, "question": 1}
    assert bucket["leading_signals"] == ["positive", "question"]
    assert [item["text"] for item in bucket["representative_danmaku"]] == [
        "为什么这么厉害",
        "普通弹幕",
    ]


def test_comment_selection_favors_engagement_and_requires_ai_review():
    comments = [
        {
            "record_type": "comment",
            "comment_id": "1",
            "text": "这是一条包含具体补充信息的评论",
            "likes": 100,
            "reply_count": 10,
            "uploader_liked": True,
        },
        {
            "record_type": "comment",
            "comment_id": "2",
            "text": "支持",
            "likes": 1,
            "reply_count": 0,
        },
    ]

    result = select_comment_candidates({}, comments, limit=1)

    assert result["host_ai_review_required"] is True
    assert result["candidates"][0]["comment_id"] == "1"
    assert "factual correctness" in result["warning"]


def test_jsonl_round_trip(tmp_path: Path):
    path = tmp_path / "comments.jsonl"
    write_jsonl(
        path,
        [
            {"record_type": "metadata", "kind": "comments"},
            {"record_type": "comment", "comment_id": "1"},
        ],
    )

    metadata, records = read_jsonl(path, "comment")

    assert metadata["kind"] == "comments"
    assert records[0]["comment_id"] == "1"
