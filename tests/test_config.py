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


def test_legacy_library_dir_name_remains_supported(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDEO_SUM_LIBRARY_DIR", raising=False)
    monkeypatch.setenv("LIBRARY_DIR", str(tmp_path / "legacy-notes"))

    settings = Settings(_env_file=None)

    assert settings.library_dir == Path(tmp_path / "legacy-notes")
