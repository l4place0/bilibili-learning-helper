"""Tests for direct CLI ingestion and filesystem resource notes."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from core.config import settings
from core.ingestion import IngestionRequest, IngestionService, extract_shared_url
from core.library import FilesystemLibrary


SHARE_TEXT = (
    "【一口气讲透大数据】 "
    "https://www.bilibili.com/video/BV12qKq6PETb/"
    "?share_source=copy_web&amp;vd_source=test"
)


class BilibiliPlatform:
    def match(self, url):
        return "BV12qKq6PETb" in url

    def parse_url(self, url):
        return "BV12qKq6PETb"

    def download(self, url, output_dir, keep_video=False):
        output_dir.mkdir(parents=True, exist_ok=True)
        audio = output_dir / "audio.wav"
        audio.write_bytes(b"audio")
        video = output_dir / "video.mp4"
        video.write_bytes(b"video")
        return audio, {
            "title": "一口气讲透大数据",
            "video_id": "BV12qKq6PETb",
            "duration": 120,
            "uploader": "测试作者",
            "tags": ["数据库", "数据仓库"],
        }, video


def _fake_asr(_provider, **_kwargs):
    asr = MagicMock()
    asr.transcribe_segments.return_value = (
        "[00:00] 第一段\n[00:10] 第二段",
        [
            {"start": 0.0, "end": 10.0, "text": "第一段"},
            {"start": 10.0, "end": 20.0, "text": "第二段"},
        ],
    )
    return asr


def _fake_frames(_video, output_dir, **_kwargs):
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for index in range(1, 3):
        path = output_dir / f"frame_{index:04d}.webp"
        path.write_bytes(f"frame-{index}".encode())
        frames.append(path)
    return frames


def test_extract_shared_url_decodes_html_entities():
    url = extract_shared_url(SHARE_TEXT)
    assert url.endswith("share_source=copy_web&vd_source=test")


def test_ingestion_exports_required_note_sections(tmp_path):
    service = IngestionService(
        asr_factory=_fake_asr,
        platform_resolver=lambda _url: BilibiliPlatform(),
        frame_extractor=_fake_frames,
    )

    result = service.ingest(
        IngestionRequest(source=SHARE_TEXT, output_dir=tmp_path, frame_count=2)
    )

    assert result.note_path.exists()
    note = result.note_path.read_text(encoding="utf-8")
    assert "\n# 总结稿\n" in note
    assert "\n# 辅助理解\n" in note
    assert "\n# Data\n" in note
    assert note.index("# 总结稿") < note.index("# 辅助理解") < note.index("# Data")
    assert "暂无总结。" in note
    assert "[00:00] 第一段" in note
    assert len(result.frame_paths) == 2
    assert all(path.exists() for path in result.frame_paths)
    assert "assets/bilibili-BV12qKq6PETb-frame-0001.webp" in note
    assert result.manifest_path == (
        tmp_path / "assets" / "bilibili-BV12qKq6PETb.json"
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["resource_id"] == "bilibili-BV12qKq6PETb"
    assert len(manifest["transcript_segments"]) == 2

    library = FilesystemLibrary(tmp_path)
    listed = library.list_resources()
    assert listed[0]["resource_id"] == result.resource_id
    assert listed[0]["frame_count"] == 2
    assert library.search_resources("数据库")[0]["resource_id"] == result.resource_id
    shown = library.get_resource(result.resource_id)
    assert shown["note_path"] == str(result.note_path)


def test_existing_resource_requires_force(tmp_path):
    service = IngestionService(
        asr_factory=_fake_asr,
        platform_resolver=lambda _url: BilibiliPlatform(),
        frame_extractor=_fake_frames,
    )
    request = IngestionRequest(source=SHARE_TEXT, output_dir=tmp_path, frame_count=2)

    service.ingest(request)

    try:
        service.ingest(request)
    except FileExistsError as exc:
        assert "--force" in str(exc)
    else:
        raise AssertionError("Expected an existing resource error")


def test_ingestion_reuses_content_addressed_cache(tmp_path):
    download_count = 0
    frame_count = 0
    asr_count = 0
    platform = BilibiliPlatform()

    original_download = platform.download

    def download(*args, **kwargs):
        nonlocal download_count
        download_count += 1
        return original_download(*args, **kwargs)

    def asr_factory(*args, **kwargs):
        nonlocal asr_count
        asr_count += 1
        return _fake_asr(*args, **kwargs)

    def frames(*args, **kwargs):
        nonlocal frame_count
        frame_count += 1
        return _fake_frames(*args, **kwargs)

    platform.download = download
    service = IngestionService(
        asr_factory=asr_factory,
        platform_resolver=lambda _url: platform,
        frame_extractor=frames,
    )
    request = IngestionRequest(
        source=SHARE_TEXT,
        output_dir=tmp_path / "library",
        frame_count=2,
        cache_policy="reuse",
        force=True,
    )

    with patch.object(settings, "cache_root", tmp_path / "cache"):
        first = service.ingest(request)
        second = service.ingest(request)

    assert download_count == 1
    assert asr_count == 1
    assert frame_count == 1
    manifest = json.loads(
        second.manifest_path.read_text(encoding="utf-8")
    )
    assert manifest["cache_keys"]["transcript"]
    assert first.resource_id == second.resource_id


def test_cli_capture_emits_structured_done_event(tmp_path):
    from cli import main

    record = MagicMock()
    record.to_dict.return_value = {
        "resource_id": "bilibili-BV12qKq6PETb",
        "note_path": str(tmp_path / "note.md"),
        "manifest_path": str(tmp_path / "resource.json"),
        "frame_paths": [],
        "metadata": {},
    }

    runner = CliRunner()
    with patch(
        "core.ingestion.IngestionService.ingest", return_value=record
    ) as mock_ingest:
        result = runner.invoke(
            main,
            [
                "capture",
                SHARE_TEXT,
                "--output-dir",
                str(tmp_path),
                "--fact-check",
                "important",
            ],
        )

    assert result.exit_code == 0
    events = [json.loads(line) for line in result.output.strip().splitlines()]
    assert events[0]["schema_version"] == 1
    assert events[0]["event"] == "started"
    assert events[0]["fact_check_mode"] == "important"
    assert events[-1]["event"] == "done"
    assert events[-1]["resource_id"] == "bilibili-BV12qKq6PETb"
    assert mock_ingest.call_args.args[0].fact_check_mode == "important"


def test_cli_asr_profile_selects_whisper_cpp_model(tmp_path):
    from cli import main
    from core.config import settings

    model_path = tmp_path / "ggml-small-q5_1.bin"
    model_path.write_bytes(b"model")
    record = MagicMock()
    record.to_dict.return_value = {
        "resource_id": "bilibili-BV12qKq6PETb",
        "note_path": str(tmp_path / "note.md"),
        "manifest_path": str(tmp_path / "resource.json"),
        "frame_paths": [],
        "metadata": {},
    }

    with (
        patch.object(settings, "asr_model_dir", tmp_path),
        patch(
            "core.ingestion.IngestionService.ingest", return_value=record
        ) as mock_ingest,
    ):
        result = CliRunner().invoke(
            main,
            ["capture", SHARE_TEXT, "--asr-profile", "balanced"],
        )

    assert result.exit_code == 0
    request = mock_ingest.call_args.args[0]
    assert request.asr_provider == "whisper-cpp"
    assert request.asr_profile == "balanced"
    assert request.asr_model_path == model_path.resolve()


def test_cli_library_list_reads_saved_manifests(tmp_path):
    from cli import main

    asset_dir = tmp_path / "assets"
    asset_dir.mkdir(parents=True)
    (asset_dir / "bilibili-BV1test.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "resource_id": "bilibili-BV1test",
                "title": "测试资源",
                "source": {"url": "https://example.test"},
                "updated_at": "2026-07-25T00:00:00+00:00",
                "artifacts": {"note": "测试资源.md", "frames": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        main, ["library", "list", "--output-dir", str(tmp_path)]
    )

    assert result.exit_code == 0
    event = json.loads(result.output)
    assert event["event"] == "resources"
    assert event["count"] == 1
    assert event["resources"][0]["resource_id"] == "bilibili-BV1test"


def test_note_injects_mermaid_and_selected_frame(tmp_path):
    frame = tmp_path / "source.webp"
    frame.write_bytes(b"frame")

    result = FilesystemLibrary(tmp_path / "library").save(
        platform="bilibili",
        video_id="BV1visual",
        source_url="https://example.test/video",
        metadata={"title": "可视化笔记"},
        summary="总结内容",
        understanding=(
            "```mermaid\n"
            'flowchart TD\n  A["输入"] --> B["结论"]\n'
            "```\n\n"
            "{{frame:1}}"
        ),
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[frame],
        providers={"asr": "test", "llm": "host"},
    )

    note = result.note_path.read_text(encoding="utf-8")
    assert 'A["输入"] --> B["结论"]' in note
    assert "{{frame:1}}" not in note
    assert "assets/bilibili-BV1visual-frame-0001.webp" in note
    assert not (tmp_path / "library" / "assets" / "bilibili-BV1visual").exists()


def test_compose_copies_and_links_supplemental_data_assets(tmp_path):
    library = FilesystemLibrary(tmp_path / "library")
    captured = library.save(
        platform="bilibili",
        video_id="BV1audience",
        source_url="https://example.test/video",
        metadata={"title": "观众材料样本"},
        summary="",
        understanding="",
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
    )
    comments = tmp_path / "comments.jsonl"
    comments.write_text('{"record_type":"comment"}\n', encoding="utf-8")

    composed = library.compose(
        captured.resource_id,
        summary="总结内容",
        understanding='```mermaid\nflowchart TD\n  A["视频"] --> B["讨论"]\n```',
        data_assets=[comments],
    )

    expected = (
        tmp_path
        / "library"
        / "assets"
        / "bilibili-BV1audience-comments.jsonl"
    )
    manifest = json.loads(composed.manifest_path.read_text(encoding="utf-8"))
    note = composed.note_path.read_text(encoding="utf-8")
    assert expected.read_text(encoding="utf-8") == comments.read_text(encoding="utf-8")
    assert manifest["artifacts"]["data"] == [
        "assets/bilibili-BV1audience-comments.jsonl"
    ]
    assert "## 补充原始数据" in note
    assert "assets/bilibili-BV1audience-comments.jsonl" in note


def test_compose_adds_completed_fact_check_to_note_and_manifest(tmp_path):
    library = FilesystemLibrary(tmp_path / "library")
    captured = library.save(
        platform="bilibili",
        video_id="BV1fact",
        source_url="https://example.test/video",
        metadata={"title": "事实核验样本"},
        summary="",
        understanding="",
        transcript="[00:30] 产品于 2025 年发布。",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
    )
    fact_check = {
        "status": "completed",
        "mode": "important",
        "checked_at": "2026-07-27",
        "claims": [
            {
                "claim": "产品于 2025 年发布。",
                "timestamp": "00:30",
                "classification": "time_sensitive_fact",
                "status": "confirmed",
                "video_statement": "产品于 2025 年发布。",
                "verified_result": "官方公告发布日期为 2025 年。",
                "sources": [
                    {
                        "title": "官方公告",
                        "url": "https://example.test/announcement",
                        "source_type": "primary",
                    }
                ],
            }
        ],
    }

    composed = library.compose(
        captured.resource_id,
        summary="总结内容",
        understanding='```mermaid\nflowchart TD\n  A["声明"] --> B["核验"]\n```',
        fact_check=fact_check,
        fact_check_mode="important",
    )

    note = composed.note_path.read_text(encoding="utf-8")
    manifest = json.loads(composed.manifest_path.read_text(encoding="utf-8"))
    assert "## 外部事实核验" in note
    assert "声明 1（00:30）" in note
    assert "[官方公告](https://example.test/announcement)" in note
    assert note.index("## 外部事实核验") < note.index("# Data")
    assert manifest["fact_check"]["status"] == "completed"


def test_skipped_fact_check_is_visible_and_does_not_block_compose(tmp_path):
    library = FilesystemLibrary(tmp_path / "library")
    captured = library.save(
        platform="bilibili",
        video_id="BV1skip",
        source_url="https://example.test/video",
        metadata={"title": "跳过核验样本"},
        summary="",
        understanding="",
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
    )

    composed = library.compose(
        captured.resource_id,
        summary="正常生成的总结",
        understanding='```mermaid\nflowchart TD\n  A["输入"] --> B["总结"]\n```',
        fact_check={
            "status": "skipped",
            "mode": "auto",
            "reason": "no_web_access",
            "message": "当前宿主无法访问外部网页。",
            "claims": [],
        },
    )

    note = composed.note_path.read_text(encoding="utf-8")
    assert "正常生成的总结" in note
    assert "原因代码：`no_web_access`" in note
    assert "不代表已由独立来源确认" in note


def test_required_fact_check_blocks_missing_payload(tmp_path):
    library = FilesystemLibrary(tmp_path / "library")
    captured = library.save(
        platform="bilibili",
        video_id="BV1required",
        source_url="https://example.test/video",
        metadata={"title": "强制核验样本"},
        summary="",
        understanding="",
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
        fact_check_mode="required",
    )

    try:
        library.compose(
            captured.resource_id,
            summary="总结",
            understanding=(
                '```mermaid\nflowchart TD\n  A["输入"] --> B["总结"]\n```'
            ),
        )
    except ValueError as exc:
        assert "required fact checking needs" in str(exc)
    else:
        raise AssertionError("required mode must reject a missing fact check")


def test_cli_compose_fact_check_file_overrides_content_payload(tmp_path):
    from cli import main

    library = FilesystemLibrary(tmp_path)
    captured = library.save(
        platform="bilibili",
        video_id="BV1cli-fact",
        source_url="https://example.test/video",
        metadata={"title": "CLI 核验样本"},
        summary="",
        understanding="",
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
    )
    content_file = tmp_path / "content.json"
    content_file.write_text(
        json.dumps(
            {
                "summary": "CLI 总结",
                "understanding": (
                    '```mermaid\nflowchart TD\n  A["输入"] --> B["总结"]\n```'
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    fact_check_file = tmp_path / "fact-check.json"
    fact_check_file.write_text(
        json.dumps(
            {
                "status": "completed",
                "mode": "auto",
                "checked_at": "2026-07-27",
                "claims": [],
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        main,
        [
            "resource",
            "compose",
            captured.resource_id,
            "--content-file",
            str(content_file),
            "--fact-check-file",
            str(fact_check_file),
            "--output-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    note = captured.note_path.read_text(encoding="utf-8")
    assert "外部事实核验已完成" in note


def test_compose_stages_replacements_beside_each_target(tmp_path):
    library = FilesystemLibrary(tmp_path / "library")
    captured = library.save(
        platform="bilibili",
        video_id="BV1acl",
        source_url="https://example.test/video",
        metadata={"title": "Windows ACL 样本"},
        summary="",
        understanding="",
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
    )
    real_replace = os.replace
    replacements = []

    def recording_replace(source, target):
        replacements.append((source, target))
        real_replace(source, target)

    with patch("core.library.os.replace", side_effect=recording_replace):
        library.compose(
            captured.resource_id,
            summary="总结",
            understanding=(
                '```mermaid\nflowchart TD\n  A["输入"] --> B["总结"]\n```'
            ),
        )

    assert len(replacements) == 2
    for source, target in replacements:
        assert Path(source).parent == Path(target).parent
        assert Path(source).name.startswith(".video-sum-")
    assert not (tmp_path / "library" / ".video-sum-staging").exists()


def test_compose_cleans_adjacent_temporary_files_after_replace_error(tmp_path):
    library_root = tmp_path / "library"
    library = FilesystemLibrary(library_root)
    captured = library.save(
        platform="bilibili",
        video_id="BV1acl-failure",
        source_url="https://example.test/video",
        metadata={"title": "Windows ACL 失败恢复"},
        summary="",
        understanding="",
        transcript="[00:00] 原始转写",
        transcript_segments=[],
        frames=[],
        providers={"asr": "test", "llm": "host"},
    )

    with patch("core.library.os.replace", side_effect=OSError("replace failed")):
        try:
            library.compose(
                captured.resource_id,
                summary="总结",
                understanding=(
                    '```mermaid\n'
                    'flowchart TD\n  A["输入"] --> B["总结"]\n'
                    "```"
                ),
            )
        except OSError as exc:
            assert str(exc) == "replace failed"
        else:
            raise AssertionError("compose must surface replacement errors")

    assert not list(library_root.glob(".video-sum-*.tmp"))
    assert not list((library_root / "assets").glob(".video-sum-*.tmp"))
