"""Filesystem resource library for durable video learning notes."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTIPLE_SPACE = re.compile(r"\s+")


def safe_filename(value: str, fallback: str = "video-note", max_length: int = 120) -> str:
    """Return a portable filename without changing the human-readable title."""
    cleaned = _UNSAFE_FILENAME.sub("_", value)
    cleaned = _MULTIPLE_SPACE.sub(" ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_length].rstrip(" .")


def _yaml_string(value: Any) -> str:
    return json.dumps("" if value is None else str(value), ensure_ascii=False)


@dataclass(frozen=True)
class ResourceRecord:
    resource_id: str
    note_path: Path
    manifest_path: Path
    frame_paths: list[Path]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["note_path"] = str(self.note_path)
        data["manifest_path"] = str(self.manifest_path)
        data["frame_paths"] = [str(path) for path in self.frame_paths]
        return data


class FilesystemLibrary:
    """Write one portable Markdown note plus relative assets into a directory."""

    schema_version = 2

    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()

    def list_resources(self) -> list[dict[str, Any]]:
        """Return lightweight manifest records ordered by update time."""
        resources = []
        assets_root = self.root / "assets"
        if not assets_root.is_dir():
            return resources
        manifest_paths = list(assets_root.glob("*.json"))
        manifest_paths.extend(assets_root.glob("*/resource.json"))
        for manifest_path in manifest_paths:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            note_name = (manifest.get("artifacts") or {}).get("note", "")
            resources.append(
                {
                    "resource_id": manifest.get("resource_id", manifest_path.parent.name),
                    "title": manifest.get("title", ""),
                    "source": manifest.get("source", {}),
                    "updated_at": manifest.get("updated_at", ""),
                    "note_path": str(self.root / note_name) if note_name else "",
                    "manifest_path": str(manifest_path),
                    "frame_count": len(
                        (manifest.get("artifacts") or {}).get("frames") or []
                    ),
                }
            )
        resources.sort(key=lambda item: item["updated_at"], reverse=True)
        return resources

    def get_resource(self, resource_id: str) -> dict[str, Any]:
        """Return a resource manifest using an explicit safe identifier."""
        if not re.fullmatch(r"[A-Za-z0-9._-]+", resource_id):
            raise ValueError("Invalid resource_id")
        manifest_path = self.root / "assets" / f"{resource_id}.json"
        if not manifest_path.is_file():
            legacy_path = (
                self.root / "assets" / resource_id / "resource.json"
            )
            if legacy_path.is_file():
                manifest_path = legacy_path
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Resource not found: {resource_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        note_name = (manifest.get("artifacts") or {}).get("note", "")
        manifest["note_path"] = str(self.root / note_name) if note_name else ""
        manifest["manifest_path"] = str(manifest_path)
        return manifest

    def search_resources(self, query: str) -> list[dict[str, Any]]:
        """Search resource metadata without loading transcripts."""
        needle = query.casefold().strip()
        if not needle:
            return self.list_resources()
        matches = []
        for item in self.list_resources():
            try:
                manifest = self.get_resource(item["resource_id"])
            except (FileNotFoundError, ValueError, json.JSONDecodeError):
                continue
            metadata = manifest.get("metadata") or {}
            haystack = " ".join(
                [
                    manifest.get("title", ""),
                    (manifest.get("source") or {}).get("url", ""),
                    metadata.get("uploader", ""),
                    " ".join(metadata.get("tags") or []),
                ]
            ).casefold()
            if needle in haystack:
                matches.append(item)
        return matches

    def compose(
        self,
        resource_id: str,
        *,
        summary: str,
        understanding: str,
        corrected_transcript: str = "",
        corrections: list[dict[str, Any]] | None = None,
    ) -> ResourceRecord:
        """Compose a captured resource using host-AI authored content."""
        if not summary.strip():
            raise ValueError("summary is required")
        if "```mermaid" not in understanding:
            raise ValueError("understanding must contain a Mermaid diagram")
        if understanding.count("```") % 2:
            raise ValueError("understanding contains an unclosed code fence")

        manifest = self.get_resource(resource_id)
        note_path = Path(manifest["note_path"])
        manifest_path = Path(manifest["manifest_path"])
        manifest.pop("note_path", None)
        manifest.pop("manifest_path", None)
        if not note_path.is_file():
            raise FileNotFoundError(f"Resource note not found: {note_path}")

        raw_transcript = self._extract_raw_transcript(
            note_path.read_text(encoding="utf-8")
        )
        artifacts = manifest.get("artifacts") or {}
        relative_frames = [
            Path(path) for path in artifacts.get("frames") or []
        ]
        for relative_frame in relative_frames:
            if not (self.root / relative_frame).is_file():
                raise FileNotFoundError(
                    f"Resource frame not found: {self.root / relative_frame}"
                )

        source = manifest.get("source") or {}
        metadata = manifest.get("metadata") or {}
        note_text = self._render_note(
            title=manifest.get("title") or resource_id,
            source_url=source.get("url", ""),
            platform=source.get("platform", ""),
            video_id=source.get("video_id", ""),
            metadata=metadata,
            summary=summary,
            understanding=understanding,
            corrected_transcript=corrected_transcript,
            transcript=raw_transcript,
            relative_frames=relative_frames,
        )

        staging_parent = self.root / ".video-sum-staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(
            tempfile.mkdtemp(prefix=f"{resource_id}-compose-", dir=staging_parent)
        )
        try:
            staged_note = stage_dir / note_path.name
            staged_note.write_text(note_text, encoding="utf-8")
            manifest["schema_version"] = self.schema_version
            manifest["providers"] = dict(manifest.get("providers") or {})
            manifest["providers"]["llm"] = "host"
            manifest["corrections"] = corrections or []
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            staged_manifest = stage_dir / "resource.json"
            staged_manifest.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(staged_manifest, manifest_path)
            os.replace(staged_note, note_path)
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
            try:
                staging_parent.rmdir()
            except OSError:
                pass

        return ResourceRecord(
            resource_id=resource_id,
            note_path=note_path,
            manifest_path=manifest_path,
            frame_paths=[self.root / path for path in relative_frames],
            metadata=metadata,
        )

    def save(
        self,
        *,
        platform: str,
        video_id: str,
        source_url: str,
        metadata: dict[str, Any],
        summary: str,
        transcript: str,
        transcript_segments: list[dict[str, Any]],
        frames: list[Path],
        providers: dict[str, str],
        cache_keys: dict[str, str] | None = None,
        understanding: str = "",
        force: bool = False,
    ) -> ResourceRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        resource_id = f"{platform}-{video_id}"
        title = metadata.get("title") or video_id
        note_name = f"{safe_filename(title, video_id)}.md"
        note_path = self.root / note_name
        asset_root = self.root / "assets"
        manifest_path = asset_root / f"{resource_id}.json"

        if (note_path.exists() or manifest_path.exists()) and not force:
            raise FileExistsError(
                f"Resource already exists: {note_path}. Use --force to replace it."
            )

        staging_parent = self.root / ".video-sum-staging"
        staging_parent.mkdir(parents=True, exist_ok=True)
        stage_dir = Path(tempfile.mkdtemp(prefix=f"{resource_id}-", dir=staging_parent))
        stage_frames = stage_dir / "assets"
        stage_frames.mkdir(parents=True)

        try:
            copied_frames = []
            for index, source in enumerate(frames, 1):
                suffix = source.suffix.lower() or ".webp"
                target = stage_frames / f"{resource_id}-frame-{index:04d}{suffix}"
                shutil.copy2(source, target)
                copied_frames.append(target)

            relative_frames = [Path("assets") / path.name for path in copied_frames]
            note_text = self._render_note(
                title=title,
                source_url=source_url,
                platform=platform,
                video_id=video_id,
                metadata=metadata,
                summary=summary,
                understanding=understanding,
                corrected_transcript="",
                transcript=transcript,
                relative_frames=relative_frames,
            )
            staged_note = stage_dir / note_name
            staged_note.write_text(note_text, encoding="utf-8")

            manifest = {
                "schema_version": self.schema_version,
                "resource_id": resource_id,
                "source": {
                    "url": source_url,
                    "platform": platform,
                    "video_id": video_id,
                },
                "title": title,
                "metadata": metadata,
                "providers": providers,
                "cache_keys": cache_keys or {},
                "transcript_segments": transcript_segments,
                "artifacts": {
                    "note": note_name,
                    "frames": [path.as_posix() for path in relative_frames],
                },
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            (stage_dir / "resource.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            asset_root.mkdir(parents=True, exist_ok=True)
            current_frame_names = {path.name for path in copied_frames}
            for staged_frame in copied_frames:
                os.replace(staged_frame, asset_root / staged_frame.name)
            if force:
                for old_frame in asset_root.glob(f"{resource_id}-frame-*"):
                    if old_frame.name not in current_frame_names:
                        old_frame.unlink()
            os.replace(stage_dir / "resource.json", manifest_path)
            os.replace(staged_note, note_path)

            return ResourceRecord(
                resource_id=resource_id,
                note_path=note_path,
                manifest_path=manifest_path,
                frame_paths=[self.root / path for path in relative_frames],
                metadata=metadata,
            )
        finally:
            shutil.rmtree(stage_dir, ignore_errors=True)
            try:
                staging_parent.rmdir()
            except OSError:
                pass

    @staticmethod
    def _render_note(
        *,
        title: str,
        source_url: str,
        platform: str,
        video_id: str,
        metadata: dict[str, Any],
        summary: str,
        understanding: str,
        corrected_transcript: str,
        transcript: str,
        relative_frames: list[Path],
    ) -> str:
        tags = metadata.get("tags") or []
        lines = [
            "---",
            f"title: {_yaml_string(title)}",
            f"source: {_yaml_string(source_url)}",
            f"platform: {_yaml_string(platform)}",
            f"video_id: {_yaml_string(video_id)}",
            f"uploader: {_yaml_string(metadata.get('uploader', ''))}",
            f"duration_seconds: {int(metadata.get('duration') or 0)}",
            f"tags: {json.dumps(tags, ensure_ascii=False)}",
            "---",
            "",
            "# 总结稿",
            "",
            summary.strip() or "暂无总结。",
            "",
            "# 辅助理解",
            "",
        ]
        if understanding.strip():
            lines.extend(
                [
                    FilesystemLibrary._inject_frames(
                        understanding.strip(), relative_frames
                    ),
                    "",
                ]
            )
        lines.extend(
            [
                "# Data",
                "",
            ]
        )
        if corrected_transcript.strip():
            lines.extend(
                [
                    "## 增强转写稿",
                    "",
                    corrected_transcript.strip(),
                    "",
                ]
            )
        lines.extend(
            [
                "## 原始转写稿",
                "",
                transcript.strip() or "暂无转写稿。",
                "",
                "## 原始关键帧",
                "",
            ]
        )
        if relative_frames:
            for index, frame in enumerate(relative_frames, 1):
                lines.extend(
                    [
                        f"### 关键帧 {index}",
                        "",
                        f"![关键帧 {index}]({frame.as_posix()})",
                        "",
                    ]
                )
        else:
            lines.append("未提取到关键帧。")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _extract_raw_transcript(note: str) -> str:
        marker = "## 原始转写稿"
        end_marker = "## 原始关键帧"
        if marker not in note or end_marker not in note:
            raise ValueError("Resource note does not contain raw transcript data")
        return note.split(marker, 1)[1].split(end_marker, 1)[0].strip()

    @staticmethod
    def _inject_frames(markdown: str, relative_frames: list[Path]) -> str:
        """Replace host-AI frame placeholders with stable asset references."""

        def replace(match: re.Match) -> str:
            index = int(match.group(1))
            if index < 1 or index > len(relative_frames):
                raise ValueError(
                    f"Understanding references unavailable frame: {index}"
                )
            frame = relative_frames[index - 1]
            return f"![关键帧 {index}]({frame.as_posix()})"

        return re.sub(r"\{\{frame:(\d+)\}\}", replace, markdown)
