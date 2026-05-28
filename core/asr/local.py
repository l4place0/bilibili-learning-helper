"""ASR provider that calls a self-hosted Whisper HTTP service."""

import logging
from pathlib import Path

import httpx

from core.asr.base import BaseASR

logger = logging.getLogger(__name__)


class LocalASR(BaseASR):
    """Transcribe by calling a self-hosted Whisper HTTP backend."""

    def __init__(self, endpoint: str, timeout: float = 600):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def transcribe(self, audio_path: Path, language: str = "zh") -> str:
        text, _ = self.transcribe_segments(audio_path, language)
        return text

    def transcribe_segments(self, audio_path: Path, language: str = "zh") -> tuple[str, list[dict]]:
        logger.info("Calling ASR service at %s for %s", self.endpoint, audio_path.name)
        with open(audio_path, "rb") as f:
            resp = httpx.post(
                f"{self.endpoint}/transcribe",
                files={"audio": (audio_path.name, f, "audio/wav")},
                data={"language": language},
                timeout=self.timeout,
            )
        resp.raise_for_status()
        data = resp.json()
        transcript = data.get("transcript", "")
        segments = data.get("segments", [])
        logger.info("ASR service returned %d chars, %d segments", len(transcript), len(segments))
        return transcript, segments
