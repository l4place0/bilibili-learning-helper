#!/usr/bin/env python3
"""Install the platform-specific video-sum bundle from GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_REPOSITORY = "l4place0/bilibili-learning-helper"
DEFAULT_VERSION = "0.2.0"
ASR_MODEL_FILENAMES = {
    "fast": "ggml-base-q5_1.bin",
    "balanced": "ggml-small-q5_1.bin",
    "accurate": "ggml-medium-q5_0.bin",
}
def run(
    command: list[str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=cwd,
    )


def platform_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architectures = {
        "x86_64": "x64",
        "amd64": "x64",
        "arm64": "arm64",
        "aarch64": "arm64",
    }
    architecture = architectures.get(machine, "")
    systems = {"darwin": "darwin", "linux": "linux", "windows": "windows"}
    if system not in systems or not architecture:
        raise RuntimeError(f"Unsupported platform: {system}-{machine}")
    target = f"{systems[system]}-{architecture}"
    if target == "windows-arm64":
        raise RuntimeError("Windows ARM64 does not have a published bundle")
    return target


def default_install_dir() -> Path:
    configured = os.getenv("VIDEO_SUM_BIN_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    if platform.system().lower() == "windows":
        root = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(root) if root else Path.home() / "AppData" / "Local"
        return base / "video-sum" / "bin"
    return Path.home() / ".local" / "bin"


def default_user_config_file() -> Path:
    system = platform.system().lower()
    if system == "windows":
        root = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(root) if root else Path.home() / "AppData" / "Local"
    elif system == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        root = os.getenv("XDG_CONFIG_HOME", "").strip()
        base = Path(root) if root else Path.home() / ".config"
    return base / "video-sum" / "config.env"


def default_user_data_dir() -> Path:
    system = platform.system().lower()
    if system == "windows":
        root = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(root) if root else Path.home() / "AppData" / "Local"
    elif system == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        root = os.getenv("XDG_DATA_HOME", "").strip()
        base = Path(root) if root else Path.home() / ".local" / "share"
    return base / "video-sum"


def default_user_cache_dir() -> Path:
    system = platform.system().lower()
    if system == "windows":
        root = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(root) if root else Path.home() / "AppData" / "Local"
        return base / "video-sum" / "Cache"
    if system == "darwin":
        return Path.home() / "Library" / "Caches" / "video-sum"
    root = os.getenv("XDG_CACHE_HOME", "").strip()
    base = Path(root) if root else Path.home() / ".cache"
    return base / "video-sum"


def executable_name(target: str | None = None) -> str:
    selected = target or platform_target()
    return "video-sum.exe" if selected.startswith("windows-") else "video-sum"


def installed_executable(install_dir: Path | None = None) -> Path:
    return (install_dir or default_install_dir()) / executable_name()


def locate_video_sum(install_dir: Path | None = None) -> str:
    configured = os.getenv("VIDEO_SUM_EXECUTABLE", "").strip()
    if configured and Path(configured).expanduser().is_file():
        return str(Path(configured).expanduser())
    if install_dir is not None:
        installed = installed_executable(install_dir)
        if installed.is_file():
            return str(installed)
    discovered = shutil.which("video-sum")
    if discovered:
        return discovered
    installed = installed_executable(install_dir)
    return str(installed) if installed.is_file() else ""


def doctor_checks(video_sum: str) -> dict:
    if not video_sum:
        return {}
    result = run([video_sum, "doctor"])
    if result.returncode != 0:
        return {}
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {}
    return {
        item.get("name"): item
        for item in payload.get("checks", [])
        if item.get("name")
    }


GPU_BACKENDS = {
    "metal": ("metal",),
    "cuda": ("cuda", "cublas"),
    "vulkan": ("vulkan",),
    "rocm": ("rocm", "hipblas"),
    "sycl": ("sycl",),
    "opencl": ("opencl",),
}


def gpu_hardware_probe() -> dict:
    """Find GPU candidates without requiring whisper.cpp or FFmpeg."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    candidates: list[dict[str, str]] = []

    if system == "darwin":
        profiler = shutil.which("system_profiler")
        if not profiler and Path("/usr/sbin/system_profiler").is_file():
            profiler = "/usr/sbin/system_profiler"
        if profiler:
            try:
                result = run([profiler, "SPDisplaysDataType", "-json"])
                displays = json.loads(result.stdout).get(
                    "SPDisplaysDataType",
                    [],
                )
                for display in displays:
                    if display.get("spdisplays_mtlgpufamilysupport"):
                        candidates.append(
                            {
                                "backend": "metal",
                                "device": (
                                    display.get("sppci_model")
                                    or display.get("_name")
                                    or "Metal-capable GPU"
                                ),
                            }
                        )
            except (
                json.JSONDecodeError,
                OSError,
                subprocess.SubprocessError,
            ):
                pass
        if not candidates and machine in {"arm64", "aarch64"}:
            candidates.append(
                {"backend": "metal", "device": "Apple Silicon GPU"}
            )

    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = run(
                [
                    nvidia_smi,
                    "--query-gpu=name",
                    "--format=csv,noheader",
                ]
            )
            if result.returncode == 0:
                candidates.extend(
                    {"backend": "cuda", "device": line.strip()}
                    for line in result.stdout.splitlines()
                    if line.strip()
                )
        except (OSError, subprocess.SubprocessError):
            pass

    if system == "linux" and Path("/dev/kfd").exists():
        candidates.append({"backend": "rocm", "device": "/dev/kfd"})

    unique = []
    seen = set()
    for candidate in candidates:
        key = (candidate["backend"], candidate["device"])
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return {
        "status": "candidate_detected" if unique else "not_detected",
        "candidate": bool(unique),
        "devices": unique,
        "evidence_level": "hardware_only",
    }


def whisper_gpu_probe(executable: str, hardware: dict | None = None) -> dict:
    """Inspect whisper.cpp startup output without loading a model."""
    hardware = hardware or {"candidate": False, "devices": []}
    if not executable:
        candidate = bool(hardware.get("candidate"))
        return {
            "status": "runtime_missing",
            "gpu_capable": False,
            "backend": "",
            "loaded_backend": "",
            "evidence": (
                ["GPU hardware candidate detected, but whisper-cli is missing"]
                if candidate
                else ["whisper-cli not found"]
            ),
            "recommendation": (
                "offer_gpu_whisper_setup"
                if candidate
                else "keep_configured_asr_provider"
            ),
        }

    try:
        result = run([executable, "--help"])
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "unverified",
            "gpu_capable": False,
            "backend": "",
            "loaded_backend": "",
            "evidence": [f"probe failed: {type(exc).__name__}"],
            "recommendation": "keep_configured_asr_provider",
        }

    output = "\n".join((result.stdout, result.stderr)).lower()
    backend_lines = [
        line.strip()
        for line in output.splitlines()
        if "backend" in line and ("load" in line or "device" in line)
    ]
    detected = ""
    for name, markers in GPU_BACKENDS.items():
        if any(
            any(marker in line for marker in markers)
            for line in backend_lines
        ):
            detected = name
            break
    cpu_loaded = any(
        "cpu" in line or "blas" in line
        for line in backend_lines
    )

    exposes_gpu_controls = bool(
        re.search(r"(?:--no-gpu|--device(?:\s|$))", output)
    )
    evidence = backend_lines[:4]
    if not evidence:
        evidence.append("no loaded GPU backend reported by whisper-cli --help")
    if detected:
        return {
            "status": "available",
            "gpu_capable": True,
            "backend": detected,
            "loaded_backend": detected,
            "gpu_enabled_by_default": exposes_gpu_controls,
            "evidence": evidence,
            "recommendation": "prefer_whisper_cpp_gpu",
        }
    if hardware.get("candidate"):
        return {
            "status": "runtime_gpu_unverified",
            "gpu_capable": False,
            "backend": "",
            "loaded_backend": "cpu" if cpu_loaded else "",
            "gpu_enabled_by_default": exposes_gpu_controls,
            "evidence": evidence,
            "recommendation": "offer_gpu_whisper_runtime",
        }
    return {
        "status": "unverified" if exposes_gpu_controls else "unavailable",
        "gpu_capable": False,
        "backend": "",
        "loaded_backend": "cpu" if cpu_loaded else "",
        "gpu_enabled_by_default": exposes_gpu_controls,
        "evidence": evidence,
        "recommendation": "keep_configured_asr_provider",
    }


def ffmpeg_gpu_probe(executable: str) -> dict:
    """Report FFmpeg hardware methods while preserving the CPU-only contract."""
    accelerators: list[str] = []
    if executable:
        try:
            result = run([executable, "-hide_banner", "-hwaccels"])
            if result.returncode == 0:
                accelerators = [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip()
                    and not line.lower().startswith("hardware acceleration")
                ]
        except (OSError, subprocess.SubprocessError):
            pass
    return {
        "status": "unsupported",
        "gpu_capable": False,
        "probe_executable": executable,
        "ffmpeg_hwaccels": accelerators,
        "evidence": (
            ["FFmpeg exposes: " + ", ".join(accelerators)]
            if accelerators
            else ["FFmpeg reported no hardware acceleration methods"]
        ),
        "reason": (
            "video-sum frame extraction does not currently enable FFmpeg "
            "hardware decode or GPU filters"
        ),
        "recommendation": "use_cpu_frame_extraction",
    }


def acceleration_guidance(
    hardware: dict,
    whisper: dict,
    frames: dict,
) -> list[str]:
    guidance = []
    if whisper.get("recommendation") == "prefer_whisper_cpp_gpu":
        guidance.append(
            "When the user did not select another ASR provider, run doctor "
            "for a local profile and prefer --asr-profile balanced when it "
            "is healthy; whisper.cpp enables its detected GPU backend by "
            "default."
        )
    elif whisper.get("recommendation") == "offer_gpu_whisper_setup":
        backends = sorted(
            {
                item.get("backend", "")
                for item in hardware.get("devices", [])
                if item.get("backend")
            }
        )
        guidance.append(
            "GPU-capable hardware was detected"
            + (f" ({', '.join(backends)})" if backends else "")
            + ", but whisper-cli is missing. Tell the user that local GPU "
            "ASR is optional, offer installation of a matching GPU-enabled "
            "whisper.cpp runtime and model, obtain approval before installing "
            "anything, then rerun bootstrap status and doctor. Until then, "
            "keep the configured ASR provider."
        )
    elif whisper.get("recommendation") == "offer_gpu_whisper_runtime":
        guidance.append(
            "GPU-capable hardware and whisper-cli were found, but no GPU "
            "backend was loaded. Offer a matching GPU-enabled whisper.cpp "
            "build and rerun bootstrap status after installation; do not "
            "claim or force GPU use before verification."
        )
    else:
        guidance.append(
            "Do not switch ASR providers for presumed GPU acceleration; "
            "keep the configured provider because no loaded whisper.cpp GPU "
            "backend was verified."
        )
    if frames.get("recommendation") == "use_cpu_frame_extraction":
        guidance.append(
            "Use the normal frame extraction path. Do not add FFmpeg GPU "
            "flags because the current video-sum frame pipeline does not "
            "support them."
        )
    return guidance


def status_payload(install_dir: Path | None = None) -> dict:
    video_sum = locate_video_sum(install_dir)
    version = ""
    if video_sum:
        result = run([video_sum, "--version"])
        if result.returncode == 0:
            version = result.stdout.strip()
    runtime_checks = doctor_checks(video_sum)
    ffmpeg = runtime_checks.get("ffmpeg", {})
    yt_dlp = runtime_checks.get("yt-dlp", {})
    whisper = shutil.which("whisper-cli") or ""
    hardware_acceleration = gpu_hardware_probe()
    whisper_acceleration = whisper_gpu_probe(
        whisper,
        hardware_acceleration,
    )
    bundled_ffmpeg = ffmpeg.get("detail", "")
    ffmpeg_probe_executable = (
        bundled_ffmpeg
        if bundled_ffmpeg and Path(bundled_ffmpeg).is_file()
        else (shutil.which("ffmpeg") or "")
    )
    frame_acceleration = ffmpeg_gpu_probe(ffmpeg_probe_executable)
    ready = bool(
        video_sum
        and version
        and ffmpeg.get("available")
        and yt_dlp.get("available")
    )
    return {
        "schema_version": 1,
        "event": "bootstrap_status",
        "ready": ready,
        "target": platform_target(),
        "command": video_sum,
        "checks": {
            "video_sum": {
                "available": bool(video_sum),
                "required": True,
                "path": video_sum,
                "version": version,
            },
            "ffmpeg": {
                "available": bool(ffmpeg.get("available")),
                "required": True,
                "path": ffmpeg.get("detail", ""),
                "bundled": bool(ffmpeg.get("available")),
            },
            "yt-dlp": {
                "available": bool(yt_dlp.get("available")),
                "required": True,
                "path": yt_dlp.get("detail", ""),
                "bundled": bool(yt_dlp.get("available")),
            },
            "whisper_cpp": {
                "available": bool(whisper),
                "required": False,
                "path": whisper,
            },
        },
        "acceleration": {
            "hardware": hardware_acceleration,
            "whisper_cpp": whisper_acceleration,
            "frame_extraction": frame_acceleration,
        },
        "ai_guidance": acceleration_guidance(
            hardware_acceleration,
            whisper_acceleration,
            frame_acceleration,
        ),
    }


def release_urls(repository: str, version: str, target: str) -> tuple[str, str]:
    asset = f"video-sum-{version}-{target}.zip"
    base = f"https://github.com/{repository}/releases/download/v{version}/{asset}"
    return base, f"{base}.sha256"


def request(url: str) -> urllib.request.Request:
    headers = {
        "Accept": "application/octet-stream",
        "User-Agent": "video-sum-skill-bootstrap",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def download(url: str, destination: Path) -> None:
    with urllib.request.urlopen(request(url), timeout=120) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def install_release(
    repository: str,
    version: str,
    install_dir: Path,
    apply: bool,
) -> dict:
    try:
        target = platform_target()
    except RuntimeError as exc:
        return {
            "schema_version": 1,
            "event": "bootstrap_error",
            "stage": "platform",
            "error": str(exc),
        }
    asset_url, checksum_url = release_urls(repository, version, target)
    destination = install_dir / executable_name(target)
    plan = {
        "schema_version": 1,
        "event": "bootstrap_plan",
        "requires_approval": True,
        "repository": repository,
        "version": version,
        "target": target,
        "asset_url": asset_url,
        "checksum_url": checksum_url,
        "destination": str(destination),
    }
    if not apply:
        return plan

    try:
        with tempfile.TemporaryDirectory(prefix="video-sum-install-") as temp:
            temp_dir = Path(temp)
            archive_path = temp_dir / "bundle.zip"
            checksum_path = temp_dir / "bundle.sha256"
            download(asset_url, archive_path)
            download(checksum_url, checksum_path)

            expected = checksum_path.read_text(encoding="utf-8").split()[0].lower()
            actual = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            if len(expected) != 64 or actual != expected:
                raise RuntimeError(
                    f"SHA-256 mismatch: expected {expected}, received {actual}"
                )

            with zipfile.ZipFile(archive_path) as bundle:
                manifest = json.loads(bundle.read("manifest.json"))
                expected_name = executable_name(target)
                if (
                    manifest.get("version") != version
                    or manifest.get("target") != target
                    or manifest.get("executable") != expected_name
                ):
                    raise RuntimeError("Release manifest does not match request")
                executable_data = bundle.read(expected_name)

            install_dir.mkdir(parents=True, exist_ok=True)
            staged = install_dir / f".{destination.name}.staging"
            staged.write_bytes(executable_data)
            if not target.startswith("windows-"):
                staged.chmod(0o755)
            os.replace(staged, destination)
    except Exception as exc:
        return {
            "schema_version": 1,
            "event": "bootstrap_error",
            "stage": "download_release",
            "error": str(exc),
        }

    return {
        "schema_version": 1,
        "event": "bootstrap_installed",
        "repository": repository,
        "version": version,
        "target": target,
        "command": str(destination),
        "status": status_payload(install_dir),
    }


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without evaluating shell syntax."""
    if not path.is_file():
        return {}
    values = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = value[1:-1]
        elif len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
        values[key] = value
    return values


def onboard_config_path(scope: str, project_dir: Path) -> Path:
    if scope == "project":
        return project_dir / ".env"
    return default_user_config_file()


def sanitize_config_value(key: str, value: str) -> str:
    if key != "ASR_ENDPOINT" or not value:
        return value
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname or ""
        if parsed.port:
            hostname = f"{hostname}:{parsed.port}"
    except ValueError:
        return "invalid_endpoint"
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    sanitized_query = [
        (name, "redacted")
        for name, _item in query
    ]
    return urllib.parse.urlunsplit(
        (
            parsed.scheme,
            hostname,
            parsed.path,
            urllib.parse.urlencode(sanitized_query),
            "redacted" if parsed.fragment else "",
        )
    )


def effective_onboard_config(
    project_dir: Path,
    reveal: bool = False,
) -> dict:
    defaults = {
        "VIDEO_SUM_LIBRARY_DIR": str(Path("library")),
        "VIDEO_SUM_CACHE_DIR": str(default_user_cache_dir()),
        "ASR_PROVIDER": "whisper-cpp",
        "ASR_PROFILE": "balanced",
        "ASR_ENDPOINT": "",
        "VIDEO_SUM_MODEL_DIR": str(default_user_data_dir() / "models"),
        "WHISPER_CPP_EXECUTABLE": "whisper-cli",
        "VIDEO_SUM_DEFAULT_LANGUAGE": "zh",
        "VIDEO_SUM_DEFAULT_FRAMES": "10",
        "VIDEO_SUM_DEFAULT_FRAME_MODE": "hybrid",
        "VIDEO_SUM_DEFAULT_CACHE_POLICY": "reuse",
        "VIDEO_SUM_FACT_CHECK": "auto",
        "VIDEO_SUM_FACT_CHECK_SOURCE_POLICY": "primary-first",
        "VIDEO_SUM_COOKIES_PATH": str(
            default_user_data_dir() / "cookies.txt"
        ),
    }
    values = dict(defaults)
    sources = {key: "built_in" for key in defaults}
    layers = (
        ("user", default_user_config_file()),
        ("project", project_dir / ".env"),
    )
    for source, path in layers:
        for key, value in read_dotenv(path).items():
            if key in values:
                values[key] = value
                sources[key] = source
    for key in values:
        if key in os.environ:
            values[key] = os.environ[key]
            sources[key] = "environment"
    secret_sources = {}
    for key in ("ASR_API_KEY",):
        source = "unset"
        configured = False
        for candidate_source, path in layers:
            candidate = read_dotenv(path).get(key, "")
            if candidate:
                configured = True
                source = candidate_source
        if os.getenv(key, ""):
            configured = True
            source = "environment"
        secret_sources[key] = {"configured": configured, "source": source}
    return {
        "values": {
            key: {
                "value": (
                    value if reveal else sanitize_config_value(key, value)
                ),
                "source": sources[key],
            }
            for key, value in values.items()
        },
        "secrets": secret_sources,
        "precedence": [
            "cli",
            "environment",
            "project",
            "user",
            "built_in",
        ],
        "paths": {
            "project": str(project_dir / ".env"),
            "user": str(default_user_config_file()),
        },
    }


def resolved_path(raw: str, fallback: Path, name: str) -> Path:
    path = Path(raw).expanduser() if raw else fallback
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path: {path}")
    return path


def onboard_values(args: argparse.Namespace) -> dict[str, str]:
    project_dir = args.project_dir.expanduser().resolve()
    data_dir = default_user_data_dir()
    config_path = onboard_config_path(args.scope, project_dir)
    existing = read_dotenv(config_path)
    effective = effective_onboard_config(project_dir, reveal=True)["values"]

    def selected(key: str, explicit, fallback: str) -> str:
        if explicit not in (None, ""):
            return str(explicit)
        if key in existing:
            return existing[key]
        active = effective[key]
        if active["source"] != "built_in":
            return active["value"]
        return fallback

    library_default = (
        project_dir / "library"
        if args.scope == "project"
        else data_dir / "library"
    )
    library = resolved_path(
        selected(
            "VIDEO_SUM_LIBRARY_DIR",
            args.library_dir,
            str(library_default),
        ),
        library_default,
        "VIDEO_SUM_LIBRARY_DIR",
    )
    cache = resolved_path(
        selected(
            "VIDEO_SUM_CACHE_DIR",
            args.cache_dir,
            str(default_user_cache_dir()),
        ),
        default_user_cache_dir(),
        "VIDEO_SUM_CACHE_DIR",
    )
    models = resolved_path(
        selected(
            "VIDEO_SUM_MODEL_DIR",
            args.model_dir,
            str(data_dir / "models"),
        ),
        data_dir / "models",
        "VIDEO_SUM_MODEL_DIR",
    )
    values = {
        "VIDEO_SUM_LIBRARY_DIR": str(library),
        "VIDEO_SUM_CACHE_DIR": str(cache),
        "ASR_PROVIDER": selected(
            "ASR_PROVIDER",
            args.asr_provider,
            "whisper-cpp",
        ),
        "ASR_PROFILE": selected(
            "ASR_PROFILE",
            args.asr_profile,
            "balanced",
        ),
        "ASR_ENDPOINT": selected("ASR_ENDPOINT", args.asr_endpoint, ""),
        "VIDEO_SUM_MODEL_DIR": str(models),
        "VIDEO_SUM_DEFAULT_LANGUAGE": selected(
            "VIDEO_SUM_DEFAULT_LANGUAGE",
            args.language,
            "zh",
        ),
        "VIDEO_SUM_DEFAULT_FRAMES": selected(
            "VIDEO_SUM_DEFAULT_FRAMES",
            args.frames,
            "10",
        ),
        "VIDEO_SUM_DEFAULT_FRAME_MODE": selected(
            "VIDEO_SUM_DEFAULT_FRAME_MODE",
            args.frame_mode,
            "hybrid",
        ),
        "VIDEO_SUM_DEFAULT_CACHE_POLICY": selected(
            "VIDEO_SUM_DEFAULT_CACHE_POLICY",
            args.cache_policy,
            "reuse",
        ),
        "VIDEO_SUM_FACT_CHECK": selected(
            "VIDEO_SUM_FACT_CHECK",
            args.fact_check,
            "auto",
        ),
        "VIDEO_SUM_FACT_CHECK_SOURCE_POLICY": selected(
            "VIDEO_SUM_FACT_CHECK_SOURCE_POLICY",
            args.fact_check_source_policy,
            "primary-first",
        ),
    }
    allowed = {
        "ASR_PROVIDER": {"whisper-cpp", "openai", "local"},
        "ASR_PROFILE": {"fast", "balanced", "accurate"},
        "VIDEO_SUM_DEFAULT_LANGUAGE": {"zh", "en", "ja"},
        "VIDEO_SUM_DEFAULT_FRAME_MODE": {
            "hybrid",
            "timestamp",
            "scene",
            "fps",
        },
        "VIDEO_SUM_DEFAULT_CACHE_POLICY": {"reuse", "refresh", "off"},
        "VIDEO_SUM_FACT_CHECK": {
            "off",
            "auto",
            "important",
            "all",
            "required",
        },
        "VIDEO_SUM_FACT_CHECK_SOURCE_POLICY": {"primary-first"},
    }
    for key, choices in allowed.items():
        if values[key] not in choices:
            raise ValueError(
                f"{key} must be one of {', '.join(sorted(choices))}"
            )
    try:
        frame_count = int(values["VIDEO_SUM_DEFAULT_FRAMES"])
    except ValueError as exc:
        raise ValueError(
            "VIDEO_SUM_DEFAULT_FRAMES must be an integer"
        ) from exc
    if not 0 <= frame_count <= 100:
        raise ValueError("VIDEO_SUM_DEFAULT_FRAMES must be between 0 and 100")
    values["VIDEO_SUM_DEFAULT_FRAMES"] = str(frame_count)

    whisper = selected(
        "WHISPER_CPP_EXECUTABLE",
        args.whisper_cpp_executable,
        "",
    ).strip()
    if not whisper:
        whisper = shutil.which("whisper-cli") or ""
    elif not Path(whisper).is_absolute():
        whisper = shutil.which(whisper) or whisper
    if whisper:
        whisper_path = resolved_path(
            whisper,
            Path(whisper),
            "WHISPER_CPP_EXECUTABLE",
        )
        values["WHISPER_CPP_EXECUTABLE"] = str(whisper_path)
    cookies = selected(
        "VIDEO_SUM_COOKIES_PATH",
        args.cookies_path,
        "",
    )
    if cookies:
        values["VIDEO_SUM_COOKIES_PATH"] = str(
            resolved_path(
                cookies,
                Path(cookies),
                "VIDEO_SUM_COOKIES_PATH",
            )
        )
    return values


def config_changes(
    config_path: Path,
    desired: dict[str, str],
) -> list[dict[str, str]]:
    existing = read_dotenv(config_path)
    changes = []
    for key, value in desired.items():
        current = existing.get(key)
        if current is None:
            action = "add"
        elif current == value:
            action = "unchanged"
        else:
            action = "update"
        changes.append(
            {
                "key": key,
                "action": action,
                "value": sanitize_config_value(key, value),
            }
        )
    return changes


def write_dotenv(
    path: Path,
    desired: dict[str, str],
    update: bool,
) -> None:
    existing = read_dotenv(path)
    conflicts = [
        key
        for key, value in desired.items()
        if key in existing and existing[key] != value
    ]
    if conflicts and not update:
        joined = ", ".join(conflicts)
        raise RuntimeError(
            f"existing values differ for {joined}; rerun with --update"
        )

    def render(key: str, value: str) -> str:
        if "\n" in value or "\r" in value:
            raise RuntimeError(f"{key} contains a newline")
        return f"{key}={json.dumps(value, ensure_ascii=False)}"

    original = (
        path.read_text(encoding="utf-8").splitlines()
        if path.is_file()
        else []
    )
    remaining = dict(desired)
    rendered = []
    for line in original:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        key = match.group(1) if match else ""
        if key in remaining:
            rendered.append(render(key, remaining.pop(key)))
        else:
            rendered.append(line)
    if rendered and rendered[-1]:
        rendered.append("")
    rendered.extend(render(key, value) for key, value in remaining.items())
    content = "\n".join(rendered).rstrip() + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(f".{path.name}.staging")
    staged.write_text(content, encoding="utf-8")
    os.replace(staged, path)


def writable_path_check(name: str, path: Path) -> dict:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".video-sum-write-",
            dir=path,
            delete=False,
        ) as probe:
            probe.write(b"ok")
            probe_path = Path(probe.name)
        probe_path.unlink()
        free_bytes = shutil.disk_usage(path).free
        return {
            "name": name,
            "available": True,
            "path": str(path),
            "free_bytes": free_bytes,
        }
    except OSError as exc:
        return {
            "name": name,
            "available": False,
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }


def utf8_ndjson_check() -> dict:
    sample = json.dumps(
        {"schema_version": 1, "event": "onboard_check", "text": "中文 🎬"},
        ensure_ascii=False,
    )
    available = sample.encode("utf-8").decode("utf-8") == sample
    return {
        "name": "utf8_ndjson",
        "available": available,
        "encoding": "utf-8",
    }


def asr_onboard_check(
    values: dict[str, str],
    secret_state: dict[str, dict],
) -> dict:
    provider = values["ASR_PROVIDER"]
    if provider == "whisper-cpp":
        executable = values.get("WHISPER_CPP_EXECUTABLE", "")
        executable_path = Path(executable) if executable else None
        model = (
            Path(values["VIDEO_SUM_MODEL_DIR"])
            / ASR_MODEL_FILENAMES[values["ASR_PROFILE"]]
        )
        return {
            "name": "asr",
            "provider": provider,
            "available": bool(
                executable_path
                and executable_path.is_absolute()
                and executable_path.is_file()
                and model.is_file()
            ),
            "executable": executable,
            "model": str(model),
        }
    if provider == "openai":
        configured = secret_state["ASR_API_KEY"]["configured"]
        return {
            "name": "asr",
            "provider": provider,
            "available": configured,
            "credential": {
                "configured": configured,
                "value": "redacted",
            },
        }
    return {
        "name": "asr",
        "provider": provider,
        "available": bool(values.get("ASR_ENDPOINT", "")),
        "endpoint_configured": bool(values.get("ASR_ENDPOINT", "")),
    }


def whisper_backend_onboard_check(
    values: dict[str, str],
    hardware: dict,
) -> dict:
    if values["ASR_PROVIDER"] != "whisper-cpp":
        return {
            "name": "whisper_backend",
            "available": True,
            "applicable": False,
        }
    probe = whisper_gpu_probe(
        values.get("WHISPER_CPP_EXECUTABLE", ""),
        hardware,
    )
    return {
        "name": "whisper_backend",
        "available": bool(probe.get("loaded_backend")),
        "applicable": True,
        **probe,
    }


def doctor_onboard_check(
    values: dict[str, str],
    install_dir: Path,
    project_dir: Path,
) -> dict:
    video_sum = locate_video_sum(install_dir)
    if not video_sum:
        return {
            "name": "doctor",
            "available": False,
            "detail": "video-sum executable not found",
        }
    command = [video_sum, "doctor"]
    if values["ASR_PROVIDER"] == "whisper-cpp":
        command.extend(["--asr-profile", values["ASR_PROFILE"]])
    else:
        command.extend(["--asr-provider", values["ASR_PROVIDER"]])
    try:
        result = run(command, cwd=project_dir)
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "name": "doctor",
            "available": False,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "name": "doctor",
        "available": result.returncode == 0,
        "returncode": result.returncode,
    }


def onboard_payload(args: argparse.Namespace) -> dict:
    project_dir = args.project_dir.expanduser().resolve()
    if args.action == "status":
        return {
            "schema_version": 1,
            "event": "onboard_status",
            **effective_onboard_config(project_dir),
        }

    try:
        values = onboard_values(args)
    except ValueError as exc:
        return {
            "schema_version": 1,
            "event": "bootstrap_error",
            "stage": "onboard_plan",
            "error": str(exc),
        }
    config_path = onboard_config_path(args.scope, project_dir)
    changes = config_changes(config_path, values)
    hardware = gpu_hardware_probe()
    whisper = whisper_gpu_probe(
        values.get("WHISPER_CPP_EXECUTABLE", ""),
        hardware,
    )
    plan = {
        "schema_version": 1,
        "event": "onboard_plan",
        "scope": args.scope,
        "config_path": str(config_path),
        "requires_approval": True,
        "side_effects": False,
        "changes": changes,
        "runtime": {
            "hardware": hardware,
            "whisper_cpp": whisper,
            "download": None,
            "reason": (
                "No project-published GPU-specific whisper.cpp artifact is "
                "available; configure only an existing or user-approved, "
                "independently verified runtime."
            ),
        },
    }
    if not args.apply:
        return plan

    try:
        write_dotenv(config_path, values, args.update)
    except (OSError, RuntimeError) as exc:
        return {
            "schema_version": 1,
            "event": "bootstrap_error",
            "stage": "onboard_config",
            "error": str(exc),
            "config_path": str(config_path),
        }

    raw_effective = effective_onboard_config(project_dir, reveal=True)
    effective_values = {
        key: item["value"]
        for key, item in raw_effective["values"].items()
    }
    checks = [
        writable_path_check(
            "library_writable",
            Path(effective_values["VIDEO_SUM_LIBRARY_DIR"]),
        ),
        writable_path_check(
            "cache_writable",
            Path(effective_values["VIDEO_SUM_CACHE_DIR"]),
        ),
        writable_path_check(
            "model_dir_writable",
            Path(effective_values["VIDEO_SUM_MODEL_DIR"]),
        ),
        utf8_ndjson_check(),
        asr_onboard_check(effective_values, raw_effective["secrets"]),
        whisper_backend_onboard_check(effective_values, hardware),
        doctor_onboard_check(
            effective_values,
            args.install_dir.expanduser().resolve(),
            project_dir,
        ),
    ]
    return {
        "schema_version": 1,
        "event": "onboard_done",
        "scope": args.scope,
        "config_path": str(config_path),
        "ready": all(check["available"] for check in checks),
        "idempotent": all(
            change["action"] == "unchanged"
            for change in config_changes(config_path, values)
        ),
        "checks": checks,
        "effective": effective_onboard_config(project_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    status = subparsers.add_parser("status")
    status.add_argument("--install-dir", type=Path, default=default_install_dir())
    for name in ("install", "repair"):
        command = subparsers.add_parser(name)
        command.add_argument(
            "--repository",
            default=os.getenv(
                "VIDEO_SUM_RELEASE_REPOSITORY",
                DEFAULT_REPOSITORY,
            ),
        )
        command.add_argument(
            "--version",
            default=os.getenv("VIDEO_SUM_RELEASE_VERSION", DEFAULT_VERSION),
        )
        command.add_argument(
            "--install-dir",
            type=Path,
            default=default_install_dir(),
        )
        command.add_argument("--apply", action="store_true")
    onboard = subparsers.add_parser("onboard")
    onboard.add_argument(
        "action",
        nargs="?",
        choices=("plan", "status"),
        default="plan",
    )
    onboard.add_argument(
        "--scope",
        choices=("project", "user"),
        default="project",
    )
    onboard.add_argument(
        "--project-dir",
        type=Path,
        default=Path.cwd(),
    )
    onboard.add_argument(
        "--install-dir",
        type=Path,
        default=default_install_dir(),
    )
    onboard.add_argument("--library-dir", default="")
    onboard.add_argument("--cache-dir", default="")
    onboard.add_argument("--model-dir", default="")
    onboard.add_argument("--cookies-path", default="")
    onboard.add_argument("--whisper-cpp-executable", default="")
    onboard.add_argument(
        "--asr-provider",
        choices=("whisper-cpp", "openai", "local"),
        default=None,
    )
    onboard.add_argument(
        "--asr-profile",
        choices=("fast", "balanced", "accurate"),
        default=None,
    )
    onboard.add_argument("--asr-endpoint", default=None)
    onboard.add_argument(
        "--language",
        choices=("zh", "en", "ja"),
        default=None,
    )
    onboard.add_argument("--frames", type=int, choices=range(0, 101))
    onboard.add_argument(
        "--frame-mode",
        choices=("hybrid", "timestamp", "scene", "fps"),
        default=None,
    )
    onboard.add_argument(
        "--cache-policy",
        choices=("reuse", "refresh", "off"),
        default=None,
    )
    onboard.add_argument(
        "--fact-check",
        choices=("off", "auto", "important", "all", "required"),
        default=None,
    )
    onboard.add_argument(
        "--fact-check-source-policy",
        choices=("primary-first",),
        default=None,
    )
    onboard.add_argument("--update", action="store_true")
    onboard.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.command == "status":
        payload = status_payload(args.install_dir.expanduser())
    elif args.command == "onboard":
        payload = onboard_payload(args)
    else:
        payload = install_release(
            args.repository,
            args.version.removeprefix("v"),
            args.install_dir.expanduser(),
            args.apply,
        )
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("event") != "bootstrap_error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
