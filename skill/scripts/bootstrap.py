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
import urllib.request
import zipfile
from pathlib import Path


DEFAULT_REPOSITORY = "l4place0/bilibili-learning-helper"
DEFAULT_VERSION = "0.1.0"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=120,
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
            "gpu_enabled_by_default": exposes_gpu_controls,
            "evidence": evidence,
            "recommendation": "prefer_whisper_cpp_gpu",
        }
    if hardware.get("candidate"):
        return {
            "status": "runtime_gpu_unverified",
            "gpu_capable": False,
            "backend": "",
            "gpu_enabled_by_default": exposes_gpu_controls,
            "evidence": evidence,
            "recommendation": "offer_gpu_whisper_runtime",
        }
    return {
        "status": "unverified" if exposes_gpu_controls else "unavailable",
        "gpu_capable": False,
        "backend": "",
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
    args = parser.parse_args()

    if args.command == "status":
        payload = status_payload(args.install_dir.expanduser())
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
