"""Abstract base class for ASR (Automatic Speech Recognition) providers."""

from abc import ABC, abstractmethod
from pathlib import Path


class BaseASR(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path, language: str = "zh") -> str:
        """Transcribe audio file to text with timestamps.

        Returns:
            Text with [MM:SS] timestamp prefixes per segment.
        """
        ...

    def transcribe_segments(self, audio_path: Path, language: str = "zh") -> tuple[str, list[dict]]:
        """Transcribe and return both plain text and structured segments.

        Returns:
            (text, segments) where segments is a list of
            {"start": float, "end": float, "text": str} dicts.
        """
        return self.transcribe(audio_path, language), []
