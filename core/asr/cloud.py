"""ASR provider that calls OpenAI's Whisper API (cloud)."""

import logging
from pathlib import Path

from openai import OpenAI

from core.asr.base import BaseASR

logger = logging.getLogger(__name__)


class OpenAIWhisperAPI(BaseASR):
    """Transcribe using OpenAI's Whisper API."""

    def __init__(self, api_key: str, model: str = "whisper-1", base_url: str = ""):
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = OpenAI(**kwargs)
        self.model = model

    def transcribe(self, audio_path: Path, language: str = "zh") -> str:
        text, _ = self.transcribe_segments(audio_path, language)
        return text

    def transcribe_segments(self, audio_path: Path, language: str = "zh") -> tuple[str, list[dict]]:
        logger.info("Calling OpenAI Whisper API for %s", audio_path.name)
        with open(audio_path, "rb") as f:
            resp = self.client.audio.transcriptions.create(
                model=self.model,
                file=f,
                language=language,
                response_format="verbose_json",
            )
        # verbose_json response has .text and .segments
        transcript = resp.text if hasattr(resp, "text") else str(resp)
        segments = []
        if hasattr(resp, "segments") and resp.segments:
            for seg in resp.segments:
                segments.append({
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "text": seg.get("text", "").strip(),
                })
        logger.info("OpenAI Whisper returned %d chars, %d segments", len(transcript), len(segments))
        return transcript, segments
