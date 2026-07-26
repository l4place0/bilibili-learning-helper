#!/usr/bin/env python3
"""Install the platform-specific video-sum bundle from GitHub Releases."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
