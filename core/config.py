from pathlib import Path
from typing import Literal

from platformdirs import user_cache_path, user_config_path, user_data_path
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def user_config_file() -> Path:
    """Return the user-level dotenv file loaded before the project file."""
    return user_config_path("video-sum") / "config.env"


def project_config_file(project_dir: Path | None = None) -> Path:
    """Return the project-level dotenv file."""
    return (project_dir or Path.cwd()) / ".env"


class Settings(BaseSettings):
    # ASR
    asr_provider: Literal["whisper-cpp", "local", "openai"] = "whisper-cpp"
    # None preserves the pre-onboarding whisper_cpp_model behavior. Onboarding
    # writes an explicit profile, which capture then applies.
    asr_profile: Literal["fast", "balanced", "accurate"] | None = None
    asr_endpoint: str = ""           # http://gpu-server:8001 (for local)
    asr_api_key: str = ""            # API key (for openai cloud)
    asr_model: str = "whisper-1"     # cloud model name
    asr_timeout_seconds: int = 3600
    asr_model_dir: Path = Field(
        default_factory=lambda: user_data_path("video-sum") / "models",
        validation_alias=AliasChoices("VIDEO_SUM_MODEL_DIR", "ASR_MODEL_DIR"),
    )
    whisper_cpp_executable: str = "whisper-cli"
    whisper_cpp_model: Path = (
        user_data_path("video-sum") / "models" / "ggml-small-q5_1.bin"
    )

    # Cookies (for Bilibili etc.)
    cookies_path: Path = Field(
        default=user_data_path("video-sum") / "cookies.txt",
        validation_alias=AliasChoices(
            "VIDEO_SUM_COOKIES_PATH",
            "COOKIES_PATH",
        ),
    )

    # Vision / frame extraction
    scene_threshold: float = 0.3
    scene_offsets: str = "0,0.5,1,2"
    frame_format: str = "webp"
    frame_quality: int = 85
    frame_width: int = 1280
    frame_workers: int = 4
    min_gap: float = 5.0
    max_scene_per_seg: int = 2
    segments: int = 60

    # Storage
    cache_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("VIDEO_SUM_CACHE_DIR", "CACHE_ROOT"),
    )
    library_dir: Path = Field(
        default=Path("library"),
        validation_alias=AliasChoices("VIDEO_SUM_LIBRARY_DIR", "LIBRARY_DIR"),
    )

    # Capture defaults
    default_language: Literal["zh", "en", "ja"] = Field(
        default="zh",
        validation_alias=AliasChoices("VIDEO_SUM_DEFAULT_LANGUAGE"),
    )
    default_frames: int = Field(
        default=10,
        ge=0,
        le=100,
        validation_alias=AliasChoices("VIDEO_SUM_DEFAULT_FRAMES"),
    )
    default_frame_mode: Literal["hybrid", "timestamp", "scene", "fps"] = Field(
        default="hybrid",
        validation_alias=AliasChoices("VIDEO_SUM_DEFAULT_FRAME_MODE"),
    )
    default_cache_policy: Literal["reuse", "refresh", "off"] = Field(
        default="reuse",
        validation_alias=AliasChoices("VIDEO_SUM_DEFAULT_CACHE_POLICY"),
    )
    fact_check: Literal["off", "auto", "important", "all", "required"] = Field(
        default="auto",
        validation_alias=AliasChoices("VIDEO_SUM_FACT_CHECK"),
    )
    fact_check_source_policy: Literal["primary-first"] = Field(
        default="primary-first",
        validation_alias=AliasChoices("VIDEO_SUM_FACT_CHECK_SOURCE_POLICY"),
    )

    @field_validator(
        "asr_model_dir",
        "whisper_cpp_model",
        "cookies_path",
        "cache_root",
        "library_dir",
    )
    @classmethod
    def expand_user_path(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None

    @property
    def cache_dir(self) -> Path:
        if self.cache_root is not None:
            return self.cache_root.expanduser()
        return user_cache_path("video-sum")

    model_config = SettingsConfigDict(
        # pydantic-settings applies later dotenv files over earlier files and
        # process environment variables over every dotenv file.
        env_file=(user_config_file(), project_config_file()),
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )


settings = Settings()
