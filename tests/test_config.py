from pathlib import Path

from core.config import Settings


def test_video_sum_paths_load_from_environment(monkeypatch, tmp_path):
    library = tmp_path / "notes"
    cache = tmp_path / "cache"
    models = tmp_path / "models"
    monkeypatch.setenv("VIDEO_SUM_LIBRARY_DIR", str(library))
    monkeypatch.setenv("VIDEO_SUM_CACHE_DIR", str(cache))
    monkeypatch.setenv("VIDEO_SUM_MODEL_DIR", str(models))

    settings = Settings(_env_file=None)

    assert settings.library_dir == library
    assert settings.cache_dir == cache
    assert settings.asr_model_dir == models


def test_video_sum_paths_load_from_dotenv(monkeypatch, tmp_path):
    for name in (
        "VIDEO_SUM_LIBRARY_DIR",
        "VIDEO_SUM_CACHE_DIR",
        "VIDEO_SUM_MODEL_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'dotenv-notes'}",
                f"VIDEO_SUM_CACHE_DIR={tmp_path / 'dotenv-cache'}",
                f"VIDEO_SUM_MODEL_DIR={tmp_path / 'dotenv-models'}",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=dotenv)

    assert settings.library_dir == tmp_path / "dotenv-notes"
    assert settings.cache_dir == tmp_path / "dotenv-cache"
    assert settings.asr_model_dir == tmp_path / "dotenv-models"


def test_environment_takes_precedence_over_dotenv(monkeypatch, tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'dotenv-notes'}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VIDEO_SUM_LIBRARY_DIR", str(tmp_path / "env-notes"))

    settings = Settings(_env_file=dotenv)

    assert settings.library_dir == tmp_path / "env-notes"


def test_project_config_takes_precedence_over_user_config(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDEO_SUM_LIBRARY_DIR", raising=False)
    user = tmp_path / "user.env"
    project = tmp_path / "project.env"
    user.write_text(
        f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'user-notes'}\n",
        encoding="utf-8",
    )
    project.write_text(
        f"VIDEO_SUM_LIBRARY_DIR={tmp_path / 'project-notes'}\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=(user, project))

    assert settings.library_dir == tmp_path / "project-notes"


def test_capture_defaults_load_from_layered_config(monkeypatch, tmp_path):
    for name in (
        "VIDEO_SUM_DEFAULT_LANGUAGE",
        "VIDEO_SUM_DEFAULT_FRAMES",
        "VIDEO_SUM_DEFAULT_FRAME_MODE",
        "VIDEO_SUM_DEFAULT_CACHE_POLICY",
    ):
        monkeypatch.delenv(name, raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "VIDEO_SUM_DEFAULT_LANGUAGE=ja",
                "VIDEO_SUM_DEFAULT_FRAMES=6",
                "VIDEO_SUM_DEFAULT_FRAME_MODE=scene",
                "VIDEO_SUM_DEFAULT_CACHE_POLICY=off",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=dotenv)

    assert settings.default_language == "ja"
    assert settings.default_frames == 6
    assert settings.default_frame_mode == "scene"
    assert settings.default_cache_policy == "off"


def test_legacy_library_dir_name_remains_supported(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDEO_SUM_LIBRARY_DIR", raising=False)
    monkeypatch.setenv("LIBRARY_DIR", str(tmp_path / "legacy-notes"))

    settings = Settings(_env_file=None)

    assert settings.library_dir == Path(tmp_path / "legacy-notes")
