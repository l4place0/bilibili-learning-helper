import hashlib
import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path("skill/scripts/bootstrap.py").resolve()
SPEC = importlib.util.spec_from_file_location("skill_bootstrap", SCRIPT)
assert SPEC and SPEC.loader
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


def onboard_args(tmp_path, **overrides):
    values = {
        "action": "plan",
        "scope": "project",
        "project_dir": tmp_path,
        "install_dir": tmp_path / "bin",
        "library_dir": str(tmp_path / "notes"),
        "cache_dir": str(tmp_path / "cache"),
        "model_dir": str(tmp_path / "models"),
        "cookies_path": "",
        "whisper_cpp_executable": "",
        "asr_provider": "openai",
        "asr_profile": "balanced",
        "asr_endpoint": "",
        "language": "zh",
        "frames": 10,
        "frame_mode": "hybrid",
        "cache_policy": "reuse",
        "fact_check": "auto",
        "fact_check_source_policy": "primary-first",
        "update": False,
        "apply": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


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


def test_windows_user_config_uses_local_app_data(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/example/AppData/Local")
    with patch.object(bootstrap.platform, "system", return_value="Windows"):
        path = bootstrap.default_user_config_file()

    assert path == Path(
        "C:/Users/example/AppData/Local/video-sum/config.env"
    )


def test_onboard_plan_is_side_effect_free(tmp_path):
    args = onboard_args(tmp_path)
    hardware = {"candidate": False, "devices": []}
    whisper = {"status": "runtime_missing", "gpu_capable": False}
    with (
        patch.object(
            bootstrap,
            "gpu_hardware_probe",
            return_value=hardware,
        ),
        patch.object(
            bootstrap,
            "whisper_gpu_probe",
            return_value=whisper,
        ),
    ):
        payload = bootstrap.onboard_payload(args)

    assert payload["event"] == "onboard_plan"
    assert payload["side_effects"] is False
    assert payload["requires_approval"] is True
    assert payload["runtime"]["download"] is None
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "notes").exists()
    assert not (tmp_path / "cache").exists()


def test_onboard_apply_is_idempotent_and_redacts_secrets(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ASR_API_KEY", "super-secret")
    args = onboard_args(tmp_path, apply=True)
    hardware = {"candidate": False, "devices": []}
    whisper = {"status": "runtime_missing", "gpu_capable": False}
    healthy = {"name": "doctor", "available": True, "returncode": 0}
    asr = {"name": "asr", "provider": "openai", "available": True}
    with (
        patch.object(
            bootstrap,
            "gpu_hardware_probe",
            return_value=hardware,
        ),
        patch.object(
            bootstrap,
            "whisper_gpu_probe",
            return_value=whisper,
        ),
        patch.object(
            bootstrap,
            "doctor_onboard_check",
            return_value=healthy,
        ),
        patch.object(
            bootstrap,
            "asr_onboard_check",
            return_value=asr,
        ),
    ):
        first = bootstrap.onboard_payload(args)
        content = (tmp_path / ".env").read_text(encoding="utf-8")
        second = bootstrap.onboard_payload(args)

    assert first["event"] == "onboard_done"
    assert first["ready"] is True
    assert second["idempotent"] is True
    assert (tmp_path / ".env").read_text(encoding="utf-8") == content
    assert (tmp_path / "notes").is_dir()
    assert (tmp_path / "cache").is_dir()
    serialized = json.dumps(second)
    assert "super-secret" not in serialized
    assert second["effective"]["secrets"]["ASR_API_KEY"] == {
        "configured": True,
        "source": "environment",
    }


def test_onboard_rerun_without_options_preserves_confirmed_values(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("ASR_API_KEY", "configured")
    explicit = onboard_args(
        tmp_path,
        apply=True,
        library_dir=str(tmp_path / "notes with spaces"),
        language="ja",
        frames=7,
    )
    defaults = onboard_args(
        tmp_path,
        apply=True,
        library_dir="",
        cache_dir="",
        model_dir="",
        asr_provider=None,
        asr_profile=None,
        asr_endpoint=None,
        language=None,
        frames=None,
        frame_mode=None,
        cache_policy=None,
    )
    hardware = {"candidate": False, "devices": []}
    healthy = {"name": "doctor", "available": True, "returncode": 0}
    asr = {"name": "asr", "provider": "openai", "available": True}
    with (
        patch.object(
            bootstrap,
            "gpu_hardware_probe",
            return_value=hardware,
        ),
        patch.object(
            bootstrap,
            "whisper_gpu_probe",
            return_value={},
        ),
        patch.object(
            bootstrap,
            "doctor_onboard_check",
            return_value=healthy,
        ),
        patch.object(
            bootstrap,
            "asr_onboard_check",
            return_value=asr,
        ),
    ):
        first = bootstrap.onboard_payload(explicit)
        second = bootstrap.onboard_payload(defaults)

    assert first["event"] == "onboard_done"
    assert second["event"] == "onboard_done"
    assert second["idempotent"] is True
    assert (
        second["effective"]["values"]["VIDEO_SUM_LIBRARY_DIR"]["value"]
        == str(tmp_path / "notes with spaces")
    )
    assert (
        second["effective"]["values"]["VIDEO_SUM_DEFAULT_LANGUAGE"]["value"]
        == "ja"
    )
    assert (
        second["effective"]["values"]["VIDEO_SUM_DEFAULT_FRAMES"]["value"]
        == "7"
    )


def test_onboard_apply_preserves_conflicting_config_without_update(tmp_path):
    config = tmp_path / ".env"
    config.write_text(
        f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'existing'}\n",
        encoding="utf-8",
    )
    args = onboard_args(tmp_path, apply=True)
    with (
        patch.object(
            bootstrap,
            "gpu_hardware_probe",
            return_value={"candidate": False, "devices": []},
        ),
        patch.object(
            bootstrap,
            "whisper_gpu_probe",
            return_value={},
        ),
    ):
        payload = bootstrap.onboard_payload(args)

    assert payload["event"] == "bootstrap_error"
    assert payload["stage"] == "onboard_config"
    assert "--update" in payload["error"]
    assert "existing" in config.read_text(encoding="utf-8")


def test_onboard_status_reports_layer_sources_without_secret_values(
    monkeypatch,
    tmp_path,
):
    user_config = tmp_path / "user.env"
    user_config.write_text(
        f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'user-notes'}\n"
        "ASR_API_KEY=user-secret\n"
        "ASR_ENDPOINT=https://agent:endpoint-secret@example.test/asr"
        "?token=query-secret\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'project-notes'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIDEO_SUM_CACHE_DIR", str(tmp_path / "env-cache"))
    with patch.object(
        bootstrap,
        "default_user_config_file",
        return_value=user_config,
    ):
        payload = bootstrap.onboard_payload(
            onboard_args(tmp_path, action="status"),
        )

    assert payload["event"] == "onboard_status"
    assert payload["values"]["VIDEO_SUM_LIBRARY_DIR"]["source"] == "project"
    assert payload["values"]["VIDEO_SUM_CACHE_DIR"]["source"] == "environment"
    assert payload["secrets"]["ASR_API_KEY"] == {
        "configured": True,
        "source": "user",
    }
    serialized = json.dumps(payload)
    assert "user-secret" not in serialized
    assert "endpoint-secret" not in serialized
    assert "query-secret" not in serialized
    assert (
        payload["values"]["ASR_ENDPOINT"]["value"]
        == "https://example.test/asr?token=redacted"
    )


def test_onboard_rejects_relative_paths(tmp_path):
    args = onboard_args(tmp_path, library_dir="relative/notes")
    payload = bootstrap.onboard_payload(args)

    assert payload["event"] == "bootstrap_error"
    assert payload["stage"] == "onboard_plan"
    assert "absolute path" in payload["error"]


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
    assert probe["loaded_backend"] == "cpu"
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
    assert probe["loaded_backend"] == "metal"
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
    assert probe["loaded_backend"] == "cpu"
    assert probe["recommendation"] == "offer_gpu_whisper_runtime"


def test_onboard_requires_observed_whisper_backend():
    values = {
        "ASR_PROVIDER": "whisper-cpp",
        "WHISPER_CPP_EXECUTABLE": "/bin/whisper-cli",
    }
    hardware = {"candidate": True, "devices": []}
    with patch.object(
        bootstrap,
        "whisper_gpu_probe",
        return_value={
            "status": "runtime_gpu_unverified",
            "loaded_backend": "cpu",
            "recommendation": "offer_gpu_whisper_runtime",
        },
    ):
        check = bootstrap.whisper_backend_onboard_check(values, hardware)

    assert check["available"] is True
    assert check["loaded_backend"] == "cpu"


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
