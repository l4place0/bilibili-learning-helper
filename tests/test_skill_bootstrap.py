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
    assert "hardware" in payload["acceleration"]
    assert "whisper_cpp" in payload["acceleration"]
    assert "frame_extraction" in payload["acceleration"]
    assert payload["ai_guidance"]
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


def test_whisper_gpu_probe_requires_loaded_backend():
    help_only = subprocess.CompletedProcess(
        ["whisper-cli", "--help"],
        0,
        stdout="--no-gpu disable GPU\n--device N GPU device",
        stderr="load_backend: loaded CPU backend",
    )
    with patch.object(bootstrap, "run", return_value=help_only):
        probe = bootstrap.whisper_gpu_probe("/bin/whisper-cli")

    assert probe["status"] == "unverified"
    assert probe["gpu_capable"] is False
    assert probe["recommendation"] == "keep_configured_asr_provider"


def test_whisper_gpu_probe_recommends_detected_backend():
    metal = subprocess.CompletedProcess(
        ["whisper-cli", "--help"],
        0,
        stdout="--no-gpu disable GPU\n--device N GPU device",
        stderr="load_backend: loaded Metal backend",
    )
    with patch.object(bootstrap, "run", return_value=metal):
        probe = bootstrap.whisper_gpu_probe("/bin/whisper-cli")

    assert probe["status"] == "available"
    assert probe["gpu_capable"] is True
    assert probe["backend"] == "metal"
    assert probe["recommendation"] == "prefer_whisper_cpp_gpu"


def test_missing_whisper_with_gpu_candidate_offers_setup():
    hardware = {
        "candidate": True,
        "devices": [{"backend": "cuda", "device": "Example GPU"}],
    }

    probe = bootstrap.whisper_gpu_probe("", hardware)
    frames = {"recommendation": "use_cpu_frame_extraction"}
    guidance = bootstrap.acceleration_guidance(hardware, probe, frames)

    assert probe["status"] == "runtime_missing"
    assert probe["gpu_capable"] is False
    assert probe["recommendation"] == "offer_gpu_whisper_setup"
    assert "whisper-cli is missing" in guidance[0]


def test_hardware_probe_does_not_require_whisper_runtime():
    profiler = subprocess.CompletedProcess(
        ["system_profiler", "SPDisplaysDataType", "-json"],
        0,
        stdout=json.dumps(
            {
                "SPDisplaysDataType": [
                    {
                        "sppci_model": "Example Radeon",
                        "spdisplays_mtlgpufamilysupport": "spdisplays_metal3",
                    }
                ]
            }
        ),
        stderr="",
    )

    def fake_which(name):
        return "/usr/sbin/system_profiler" if name == "system_profiler" else None

    with (
        patch.object(bootstrap.platform, "system", return_value="Darwin"),
        patch.object(bootstrap.platform, "machine", return_value="x86_64"),
        patch.object(bootstrap.shutil, "which", side_effect=fake_which),
        patch.object(bootstrap, "run", return_value=profiler),
    ):
        probe = bootstrap.gpu_hardware_probe()

    assert probe["status"] == "candidate_detected"
    assert probe["devices"] == [
        {"backend": "metal", "device": "Example Radeon"}
    ]


def test_installed_cpu_runtime_with_gpu_candidate_offers_gpu_build():
    cpu_only = subprocess.CompletedProcess(
        ["whisper-cli", "--help"],
        0,
        stdout="--no-gpu disable GPU",
        stderr="load_backend: loaded CPU backend",
    )
    hardware = {
        "candidate": True,
        "devices": [{"backend": "metal", "device": "Example GPU"}],
    }
    with patch.object(bootstrap, "run", return_value=cpu_only):
        probe = bootstrap.whisper_gpu_probe("/bin/whisper-cli", hardware)

    assert probe["status"] == "runtime_gpu_unverified"
    assert probe["recommendation"] == "offer_gpu_whisper_runtime"


def test_ffmpeg_probe_does_not_claim_supported_frame_path():
    ffmpeg = subprocess.CompletedProcess(
        ["ffmpeg", "-hide_banner", "-hwaccels"],
        0,
        stdout="Hardware acceleration methods:\nvideotoolbox\n",
        stderr="",
    )
    with patch.object(bootstrap, "run", return_value=ffmpeg):
        probe = bootstrap.ffmpeg_gpu_probe("/bin/ffmpeg")

    assert probe["status"] == "unsupported"
    assert probe["gpu_capable"] is False
    assert probe["probe_executable"] == "/bin/ffmpeg"
    assert probe["ffmpeg_hwaccels"] == ["videotoolbox"]
    assert probe["recommendation"] == "use_cpu_frame_extraction"
