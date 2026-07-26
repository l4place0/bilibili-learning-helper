import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path("skill/scripts/bootstrap.py").resolve()
SPEC = importlib.util.spec_from_file_location("skill_bootstrap", SCRIPT)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def test_bootstrap_status_is_structured():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "status"],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["event"] == "bootstrap_status"
    assert "video_sum" in payload["checks"]
    assert "ffmpeg" in payload["checks"]
    assert payload["target"] in {
        "darwin-arm64",
        "darwin-x64",
        "linux-arm64",
        "linux-x64",
        "windows-x64",
    }


def test_bootstrap_install_requires_apply():
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "install",
            "--repository",
            "owner/repository",
            "--version",
            "1.2.3",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["event"] == "bootstrap_plan"
    assert payload["requires_approval"] is True
    assert payload["repository"] == "owner/repository"
    assert "/releases/download/v1.2.3/" in payload["asset_url"]
    assert payload["checksum_url"].endswith(".sha256")


def test_release_install_verifies_and_atomically_installs(tmp_path):
    target = "linux-x64"
    version = "1.2.3"
    executable = b"standalone-binary"
    source_archive = tmp_path / "source.zip"
    with zipfile.ZipFile(source_archive, "w") as bundle:
        bundle.writestr("video-sum", executable)
        bundle.writestr(
            "manifest.json",
            json.dumps(
                {
                    "version": version,
                    "target": target,
                    "executable": "video-sum",
                }
            ),
        )
    digest = hashlib.sha256(source_archive.read_bytes()).hexdigest()

    def fake_download(url, destination):
        if url.endswith(".sha256"):
            destination.write_text(f"{digest}  bundle.zip\n", encoding="utf-8")
        else:
            destination.write_bytes(source_archive.read_bytes())

    install_dir = tmp_path / "bin"
    with (
        patch.object(bootstrap, "platform_target", return_value=target),
        patch.object(bootstrap, "download", side_effect=fake_download),
        patch.object(bootstrap, "status_payload", return_value={"ready": True}),
    ):
        payload = bootstrap.install_release(
            "owner/repository",
            version,
            install_dir,
            apply=True,
        )

    assert payload["event"] == "bootstrap_installed"
    installed = install_dir / "video-sum"
    assert installed.read_bytes() == executable
    assert installed.stat().st_mode & 0o111


def test_status_prefers_managed_bundle_over_path(tmp_path):
    target = "linux-x64"
    managed = tmp_path / "video-sum"
    managed.write_bytes(b"managed")
    with (
        patch.object(bootstrap, "platform_target", return_value=target),
        patch.object(bootstrap.shutil, "which", return_value="/old/video-sum"),
    ):
        assert bootstrap.locate_video_sum(tmp_path) == str(managed)
