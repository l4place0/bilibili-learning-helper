#!/usr/bin/env python3
"""Build and package one platform-specific standalone release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def build(target: str, version: str, output_dir: Path) -> tuple[Path, Path]:
    executable_name = "video-sum.exe" if target.startswith("windows-") else "video-sum"
    work_dir = ROOT / "build" / "standalone"
    dist_dir = work_dir / "dist"
    spec_dir = work_dir / "spec"
    shutil.rmtree(work_dir, ignore_errors=True)
    dist_dir.mkdir(parents=True)
    spec_dir.mkdir(parents=True)

    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--noconfirm",
            "--name",
            "video-sum",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(work_dir / "work"),
            "--specpath",
            str(spec_dir),
            "--collect-all",
            "imageio_ffmpeg",
            "--collect-all",
            "yt_dlp",
            "--collect-all",
            "openai",
            "--hidden-import",
            "core.asr.cloud",
            "--hidden-import",
            "core.asr.local",
            "--hidden-import",
            "core.asr.whisper_cpp",
            str(ROOT / "cli" / "__main__.py"),
        ]
    )

    executable = dist_dir / executable_name
    if not executable.is_file():
        raise FileNotFoundError(f"Standalone executable was not created: {executable}")
    run([str(executable), "--version"])

    output_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"bili-tutor-cli-{version}-{target}.zip"
    asset = output_dir / asset_name
    manifest = {
        "schema_version": 1,
        "name": "bili-tutor-cli",
        "version": version,
        "target": target,
        "executable": executable_name,
        "includes": [
            "python-runtime",
            "python-dependencies",
            "ffmpeg",
            "openai-asr-client",
        ],
        "excludes": ["whisper-models", "whisper-cli"],
    }
    with zipfile.ZipFile(asset, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(executable, executable_name)
        archive.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )

    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    checksum = output_dir / f"{asset_name}.sha256"
    checksum.write_text(f"{digest}  {asset_name}\n", encoding="utf-8")
    return asset, checksum


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    asset, checksum = build(args.target, args.version, args.output_dir)
    print(json.dumps({"asset": str(asset), "checksum": str(checksum)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
