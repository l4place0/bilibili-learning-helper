"""CLI subcommands for video-sum."""

import importlib.util
import logging
import os
import shutil
import sys
from pathlib import Path

import click

from cli.output import emit, emit_error

# Redirect all logging to stderr so stdout stays clean JSON
logging.basicConfig(
    stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s"
)


def _run_ingestion(
    url: str,
    lang: str,
    asr_provider: str,
    asr_profile: str,
    output_dir: str,
    frames: int,
    force: bool,
    frame_mode: str = "timestamp",
    cache_policy: str = "reuse",
    fact_check_mode: str = "auto",
):
    """Run the framework-independent ingestion service and emit NDJSON."""
    from core.asr.profiles import resolve_asr_profile
    from core.config import settings
    from core.ingestion import IngestionRequest, IngestionService

    destination = Path(output_dir).expanduser() if output_dir else settings.library_dir
    asr_model_path = None
    if asr_profile:
        _profile, asr_model_path = resolve_asr_profile(
            asr_profile, settings.asr_model_dir
        )
        if not asr_model_path.is_file():
            emit_error(
                (
                    f"ASR model for profile '{asr_profile}' is not installed: "
                    f"{asr_model_path}. Place the model file at this path."
                ),
                code=2,
                error_code="asr_model_missing",
            )
        asr_provider = "whisper-cpp"

    def on_progress(stage: str, progress: int, message: str):
        emit("stage", stage=stage, progress=progress, message=message)

    emit(
        "started",
        source=url,
        output_dir=str(destination),
        asr_provider=asr_provider or "configured-default",
        asr_profile=asr_profile or "configured-default",
        asr_model=str(asr_model_path) if asr_model_path else "configured-default",
        fact_check_mode=fact_check_mode,
    )
    try:
        record = IngestionService().ingest(
            IngestionRequest(
                source=url,
                output_dir=destination,
                language=lang,
                asr_provider=asr_provider,
                asr_profile=asr_profile,
                asr_model_path=asr_model_path,
                frame_count=frames,
                frame_mode=frame_mode,
                cache_policy=cache_policy,
                fact_check_mode=fact_check_mode,
                force=force,
            ),
            progress=on_progress,
        )
    except FileExistsError as exc:
        emit_error(str(exc), code=3, error_code="resource_exists")
    except ValueError as exc:
        emit_error(str(exc), code=2, error_code="invalid_input")
    except Exception as exc:
        logging.getLogger(__name__).exception("Ingestion failed")
        emit_error(str(exc), code=1, error_code="ingestion_failed")

    emit("done", **record.to_dict())


@click.command()
@click.option("--asr-provider", default="", help="Validate this ASR provider")
@click.option(
    "--asr-profile",
    default=None,
    type=click.Choice(["fast", "balanced", "accurate"]),
)
def doctor(asr_provider, asr_profile):
    """Report required tools and configured provider capabilities."""
    from core.config import settings

    checks = []

    def add(name: str, available: bool, required: bool, detail: str):
        checks.append(
            {
                "name": name,
                "available": available,
                "required": required,
                "detail": detail,
            }
        )

    from core.runtime import ffmpeg_executable

    ffmpeg = ffmpeg_executable()
    yt_dlp = shutil.which("yt-dlp") or (
        "python-package" if importlib.util.find_spec("yt_dlp") else None
    )
    add("ffmpeg", bool(ffmpeg), True, ffmpeg or "not found")
    add("yt-dlp", bool(yt_dlp), True, yt_dlp or "not found")

    library_dir = settings.library_dir.expanduser().resolve()
    probe = library_dir
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    writable = probe.is_dir() and os.access(probe, os.W_OK)
    add("library", writable, True, str(library_dir))

    selected_model = None
    if asr_profile:
        from core.asr.profiles import resolve_asr_profile

        _profile, selected_model = resolve_asr_profile(
            asr_profile, settings.asr_model_dir
        )
        asr_provider = "whisper-cpp"
    else:
        asr_provider = asr_provider or settings.asr_provider
    if asr_provider in ("whisper-cpp", "whisper_cpp"):
        executable = shutil.which(settings.whisper_cpp_executable)
        model_path = selected_model or settings.whisper_cpp_model.expanduser()
        model_exists = model_path.is_file()
        add(
            "asr",
            bool(executable and model_exists),
            True,
            (f"whisper-cpp executable={executable or 'missing'}, model={model_path}"),
        )
    elif asr_provider == "openai":
        add("asr", bool(settings.asr_api_key), True, "openai API configuration")
    elif asr_provider == "local":
        add(
            "asr",
            bool(settings.asr_endpoint),
            True,
            settings.asr_endpoint or "endpoint missing",
        )
    else:
        add("asr", False, True, f"unknown provider: {asr_provider}")
    add("host_ai", True, False, "transcript enhancement and note composition")

    healthy = all(item["available"] for item in checks if item["required"])
    emit("doctor", healthy=healthy, checks=checks)
    if not healthy:
        raise SystemExit(1)


@click.group(name="library")
def library_commands():
    """Inspect resources saved in the local library."""


@click.group(name="resource")
def resource_commands():
    """Compose captured resources."""


@click.group(name="frames")
def frame_commands():
    """Extract frames for host-AI visual analysis."""


@click.group(name="cache")
def cache_commands():
    """Inspect and maintain the user-level content cache."""


@click.group(name="comments")
def comment_commands():
    """Fetch and rank public top-level video comments."""


@click.group(name="danmaku")
def danmaku_commands():
    """Fetch and pre-analyze current Bilibili danmaku."""


@comment_commands.command(name="fetch")
@click.argument("url")
@click.option("--mode", type=click.Choice(["hot", "all"]), default="hot")
@click.option(
    "--limit",
    type=click.IntRange(0),
    default=None,
    help="Maximum top-level comments; 0 means unlimited in all mode",
)
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--force", is_flag=True, help="Replace an existing output file")
def comments_fetch(url, mode, limit, output, force):
    """Fetch hot or all accessible top-level Bilibili comments."""
    from core.community import BilibiliCommunityClient, write_jsonl
    from core.config import settings

    if output.exists() and not force:
        emit_error(
            f"Output already exists: {output}",
            code=3,
            error_code="output_exists",
        )
    selected_limit = (50 if mode == "hot" else 0) if limit is None else limit
    if mode == "hot" and selected_limit == 0:
        emit_error(
            "hot mode requires a positive --limit",
            code=2,
            error_code="invalid_input",
        )
    try:
        with BilibiliCommunityClient(settings.cookies_path) as client:
            metadata, comments = client.fetch_comments(
                url,
                mode=mode,
                limit=selected_limit,
                progress=lambda count, total: emit(
                    "stage",
                    stage="comments",
                    progress=count,
                    message=f"Fetched {count} of {total or 'unknown'} comments",
                ),
            )
        write_jsonl(output, [metadata, *comments])
    except (OSError, RuntimeError, ValueError) as exc:
        emit_error(str(exc), code=1, error_code="comments_fetch_failed")
    emit(
        "comments_fetched",
        output=str(output.expanduser().resolve()),
        count=len(comments),
        mode=mode,
        authenticated=metadata["authenticated"],
        nested_replies_included=False,
        warning=(
            "All mode may be slow and may trigger platform rate limits."
            if mode == "all"
            else ""
        ),
    )


@comment_commands.command(name="select")
@click.argument(
    "comments_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--limit", default=20, type=click.IntRange(1, 200))
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--force", is_flag=True, help="Replace an existing output file")
def comments_select(comments_file, limit, output, force):
    """Rank comment candidates for host-AI quality review."""
    from core.community import read_jsonl, select_comment_candidates, write_json

    if output.exists() and not force:
        emit_error(
            f"Output already exists: {output}",
            code=3,
            error_code="output_exists",
        )
    try:
        metadata, comments = read_jsonl(comments_file, "comment")
        result = select_comment_candidates(metadata, comments, limit)
        write_json(output, result)
    except (OSError, ValueError) as exc:
        emit_error(str(exc), code=2, error_code="comments_select_failed")
    emit(
        "comment_candidates_selected",
        output=str(output.expanduser().resolve()),
        count=result["candidate_count"],
        host_ai_review_required=True,
    )


@danmaku_commands.command(name="fetch")
@click.argument("url")
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--force", is_flag=True, help="Replace an existing output file")
def danmaku_fetch(url, output, force):
    """Fetch the currently accessible Bilibili danmaku segments."""
    from core.community import BilibiliCommunityClient, write_jsonl
    from core.config import settings

    if output.exists() and not force:
        emit_error(
            f"Output already exists: {output}",
            code=3,
            error_code="output_exists",
        )
    try:
        with BilibiliCommunityClient(settings.cookies_path) as client:
            metadata, records = client.fetch_danmaku(
                url,
                progress=lambda current, total: emit(
                    "stage",
                    stage="danmaku",
                    progress=round(current / total * 100),
                    message=f"Fetched danmaku segment {current}/{total}",
                ),
            )
        write_jsonl(output, [metadata, *records])
    except (OSError, RuntimeError, ValueError) as exc:
        emit_error(str(exc), code=1, error_code="danmaku_fetch_failed")
    emit(
        "danmaku_fetched",
        output=str(output.expanduser().resolve()),
        count=len(records),
        source=metadata["source"],
        scope=metadata["scope"],
        authenticated=metadata["authenticated"],
        complete_historical=False,
    )


@danmaku_commands.command(name="analyze")
@click.argument(
    "danmaku_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option("--bucket-seconds", default=30, type=click.IntRange(5, 600))
@click.option("--hotspots", "hotspot_limit", default=10, type=click.IntRange(1, 100))
@click.option("--clusters", "cluster_limit", default=30, type=click.IntRange(1, 500))
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.option("--force", is_flag=True, help="Replace an existing output file")
def danmaku_analyze(
    danmaku_file,
    bucket_seconds,
    hotspot_limit,
    cluster_limit,
    output,
    force,
):
    """Create deterministic hotspot and semantic-analysis candidates."""
    from core.community import analyze_danmaku, read_jsonl, write_json

    if output.exists() and not force:
        emit_error(
            f"Output already exists: {output}",
            code=3,
            error_code="output_exists",
        )
    try:
        metadata, records = read_jsonl(danmaku_file, "danmaku")
        result = analyze_danmaku(
            metadata,
            records,
            bucket_seconds=bucket_seconds,
            hotspot_limit=hotspot_limit,
            cluster_limit=cluster_limit,
        )
        write_json(output, result)
    except (OSError, ValueError) as exc:
        emit_error(str(exc), code=2, error_code="danmaku_analysis_failed")
    emit(
        "danmaku_analyzed",
        output=str(output.expanduser().resolve()),
        record_count=result["record_count"],
        hotspot_count=len(result["hotspots"]),
        cluster_count=len(result["repetition_clusters"]),
        host_ai_review_required=True,
    )


def _cache_store():
    from core.cache import CacheStore
    from core.config import settings

    return CacheStore(settings.cache_dir)


@cache_commands.command(name="dir")
def cache_dir():
    """Show the active cache directory."""
    emit("cache_dir", path=str(_cache_store().root))


@cache_commands.command(name="status")
def cache_status():
    """Show cache size and object counts."""
    emit("cache_status", **_cache_store().status())


@cache_commands.command(name="list")
@click.option("--kind", default="")
def cache_list(kind):
    """List cached objects."""
    entries = [entry.to_dict() for entry in _cache_store().list(kind)]
    emit("cache_entries", count=len(entries), entries=entries)


@cache_commands.command(name="inspect")
@click.argument("key")
def cache_inspect(key):
    """Inspect one cached object by key."""
    entry = _cache_store().get(key)
    if not entry:
        emit_error("Cache object not found", code=2, error_code="cache_miss")
    emit("cache_entry", entry=entry.to_dict())


@cache_commands.command(name="prune")
@click.option("--max-gb", default=5.0, type=click.FloatRange(min=0.1))
def cache_prune(max_gb):
    """Remove expired and least-recently-used objects."""
    result = _cache_store().prune(int(max_gb * 1024**3))
    emit("cache_pruned", **result)


@cache_commands.command(name="clear")
@click.confirmation_option(prompt="Clear the video-sum cache?")
def cache_clear():
    """Delete every cached object."""
    emit("cache_cleared", **_cache_store().clear())


def _parse_timestamp(value: str) -> float:
    parts = value.strip().split(":")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise click.BadParameter(f"invalid timestamp: {value}") from exc
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    if len(numbers) == 3:
        return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
    raise click.BadParameter(f"invalid timestamp: {value}")


@frame_commands.command(name="extract")
@click.argument(
    "video",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--at",
    "timestamps",
    multiple=True,
    required=True,
    help="Timestamp in seconds, MM:SS, or HH:MM:SS; repeat as needed",
)
@click.option(
    "--around",
    default=0.0,
    type=click.FloatRange(min=0),
    help="Also extract one frame this many seconds before and after each --at",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
)
def extract_targeted_frames(video, timestamps, around, output_dir):
    """Extract frames at explicit timestamps from a local video."""
    from core.vision.frames import extract_frames_at

    selected = []
    for raw_timestamp in timestamps:
        timestamp = _parse_timestamp(raw_timestamp)
        selected.append(timestamp)
        if around:
            selected.extend([max(0, timestamp - around), timestamp + around])
    selected = sorted(set(selected))
    paths = extract_frames_at(video, output_dir, selected)
    emit(
        "frames_extracted",
        video=str(video.resolve()),
        frame_paths=[str(path.resolve()) for path in paths],
        timestamps=selected,
    )


@resource_commands.command(name="compose")
@click.argument("resource_id")
@click.option(
    "--content-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--summary-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--understanding-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--corrected-transcript-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--corrections-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--fact-check-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--data-asset",
    "data_assets",
    multiple=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Raw supplemental file to copy into sibling assets/; repeat as needed",
)
@click.option(
    "--fact-check",
    "fact_check_mode",
    default=None,
    type=click.Choice(["off", "auto", "important", "all", "required"]),
)
@click.option("--output-dir", default="", type=click.Path(file_okay=False))
def resource_compose(
    resource_id,
    content_file,
    summary_file,
    understanding_file,
    corrected_transcript_file,
    corrections_file,
    fact_check_file,
    data_assets,
    fact_check_mode,
    output_dir,
):
    """Compose a note from host-AI authored JSON content."""
    import json

    from core.config import settings
    from core.library import FilesystemLibrary

    root = Path(output_dir).expanduser() if output_dir else settings.library_dir
    try:
        if content_file:
            content = json.loads(content_file.read_text(encoding="utf-8"))
            if not isinstance(content, dict):
                raise ValueError("content file must contain a JSON object")
        else:
            if not summary_file or not understanding_file:
                raise ValueError(
                    "provide --content-file or both --summary-file and "
                    "--understanding-file"
                )
            content = {
                "summary": summary_file.read_text(encoding="utf-8"),
                "understanding": understanding_file.read_text(encoding="utf-8"),
                "corrected_transcript": (
                    corrected_transcript_file.read_text(encoding="utf-8")
                    if corrected_transcript_file
                    else ""
                ),
                "corrections": (
                    json.loads(corrections_file.read_text(encoding="utf-8"))
                    if corrections_file
                    else []
                ),
            }
        if fact_check_file:
            content["fact_check"] = json.loads(
                fact_check_file.read_text(encoding="utf-8")
            )
        record = FilesystemLibrary(root).compose(
            resource_id,
            summary=str(content.get("summary") or ""),
            understanding=str(content.get("understanding") or ""),
            corrected_transcript=str(content.get("corrected_transcript") or ""),
            corrections=content.get("corrections") or [],
            fact_check=content.get("fact_check"),
            fact_check_mode=fact_check_mode,
            data_assets=list(data_assets),
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        emit_error(str(exc), code=2, error_code="invalid_content")
    emit("composed", **record.to_dict())


@click.group(name="asr")
def asr_commands():
    """Inspect local transcription capabilities."""


@asr_commands.command(name="profiles")
def asr_profiles():
    """List local model profiles and their installation state."""
    from core.asr.profiles import ASR_PROFILES, resolve_asr_profile
    from core.config import settings

    profiles = []
    for name, profile in ASR_PROFILES.items():
        _profile, model_path = resolve_asr_profile(name, settings.asr_model_dir)
        profiles.append(
            {
                "name": name,
                "description": profile.description,
                "model": profile.model_filename,
                "path": str(model_path),
                "installed": model_path.is_file(),
            }
        )
    emit(
        "asr_profiles",
        model_dir=str(settings.asr_model_dir.expanduser().resolve()),
        profiles=profiles,
    )


@library_commands.command(name="list")
@click.option("--output-dir", default="", type=click.Path(file_okay=False))
def library_list(output_dir):
    """List saved resources."""
    from core.config import settings
    from core.library import FilesystemLibrary

    root = Path(output_dir).expanduser() if output_dir else settings.library_dir
    resources = FilesystemLibrary(root).list_resources()
    emit("resources", count=len(resources), resources=resources)


@library_commands.command(name="show")
@click.argument("resource_id")
@click.option("--output-dir", default="", type=click.Path(file_okay=False))
def library_show(resource_id, output_dir):
    """Show one saved resource manifest."""
    from core.config import settings
    from core.library import FilesystemLibrary

    root = Path(output_dir).expanduser() if output_dir else settings.library_dir
    try:
        resource = FilesystemLibrary(root).get_resource(resource_id)
    except FileNotFoundError as exc:
        emit_error(str(exc), code=4, error_code="resource_not_found")
    except ValueError as exc:
        emit_error(str(exc), code=2, error_code="invalid_input")
    emit("resource", resource=resource)


@library_commands.command(name="search")
@click.argument("query")
@click.option("--output-dir", default="", type=click.Path(file_okay=False))
def library_search(query, output_dir):
    """Search title, URL, uploader, and tags."""
    from core.config import settings
    from core.library import FilesystemLibrary

    root = Path(output_dir).expanduser() if output_dir else settings.library_dir
    resources = FilesystemLibrary(root).search_resources(query)
    emit("resources", query=query, count=len(resources), resources=resources)


@click.command()
@click.argument("url")
@click.option("--output-dir", default="", type=click.Path(file_okay=False))
@click.option("--lang", default=None, type=click.Choice(["zh", "en", "ja"]))
@click.option(
    "--asr-provider",
    default="",
    help="ASR provider (configured default/whisper-cpp/local/openai)",
)
@click.option(
    "--asr-profile",
    default=None,
    type=click.Choice(["fast", "balanced", "accurate"]),
    help="Local whisper.cpp model profile",
)
@click.option("--frames", default=None, type=click.IntRange(0, 100))
@click.option(
    "--frame-mode",
    default=None,
    type=click.Choice(["hybrid", "timestamp", "scene", "fps"]),
)
@click.option(
    "--cache",
    "cache_policy",
    default=None,
    type=click.Choice(["reuse", "refresh", "off"]),
)
@click.option(
    "--fact-check",
    "fact_check_mode",
    default=None,
    type=click.Choice(["off", "auto", "important", "all", "required"]),
)
@click.option("--force", is_flag=True)
def capture(
    url,
    output_dir,
    lang,
    asr_provider,
    asr_profile,
    frames,
    frame_mode,
    cache_policy,
    fact_check_mode,
    force,
):
    """Capture transcript and frames without invoking an internal LLM."""
    from core.config import settings

    selected_profile = (
        asr_profile
        or (
            settings.asr_profile
            if not asr_provider and settings.asr_provider == "whisper-cpp"
            else ""
        )
        or ""
    )
    _run_ingestion(
        url,
        lang or settings.default_language,
        asr_provider,
        selected_profile,
        output_dir,
        settings.default_frames if frames is None else frames,
        force,
        frame_mode=frame_mode or settings.default_frame_mode,
        cache_policy=cache_policy or settings.default_cache_policy,
        fact_check_mode=fact_check_mode or settings.fact_check,
    )
