from pathlib import Path

from platformdirs import user_cache_path, user_data_path
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ASR
    asr_provider: str = "whisper-cpp"  # whisper-cpp | local | openai
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
    cookies_path: Path = user_data_path("video-sum") / "cookies.txt"

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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "populate_by_name": True,
    }


settings = Settings()
