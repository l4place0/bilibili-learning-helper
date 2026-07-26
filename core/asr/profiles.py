"""Simple, deterministic local ASR model profiles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ASRProfile:
    name: str
    model_filename: str
    description: str


ASR_PROFILES = {
    "fast": ASRProfile(
        name="fast",
        model_filename="ggml-base-q5_1.bin",
        description="Fast local transcription with lower accuracy.",
    ),
    "balanced": ASRProfile(
        name="balanced",
        model_filename="ggml-small-q5_1.bin",
        description="Balanced speed and accuracy for normal ingestion.",
    ),
    "accurate": ASRProfile(
        name="accurate",
        model_filename="ggml-medium-q5_0.bin",
        description="Higher local accuracy with greater CPU and memory cost.",
    ),
}


def resolve_asr_profile(name: str, model_dir: Path) -> tuple[ASRProfile, Path]:
    """Resolve a profile to its expected whisper.cpp model path."""
    try:
        profile = ASR_PROFILES[name]
    except KeyError as exc:
        choices = ", ".join(ASR_PROFILES)
        raise ValueError(f"Unknown ASR profile: {name}. Available: {choices}") from exc
    return profile, model_dir.expanduser().resolve() / profile.model_filename
