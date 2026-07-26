"""Lightweight local ASR adapter for the whisper.cpp CLI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from core.asr.base import BaseASR
from core.config import settings


def parse_progress(text: str) -> int | None:
    """Return the latest whisper.cpp progress percentage in a text chunk."""
    matches = re.findall(r"progress\s*=\s*(\d+)%", text)
    return min(100, int(matches[-1])) if matches else None


class WhisperCppASR(BaseASR):
    def __init__(
        self,
        executable: str = "",
        model_path: Path | None = None,
        progress_callback: Callable[[int], None] | None = None,
    ):
        self.executable = executable or settings.whisper_cpp_executable
        self.model_path = (model_path or settings.whisper_cpp_model).expanduser()
        self.progress_callback = progress_callback

    def transcribe(self, audio_path: Path, language: str = "zh") -> str:
        transcript, _segments = self.transcribe_segments(audio_path, language)
        return transcript

    def transcribe_segments(
        self, audio_path: Path, language: str = "zh"
    ) -> tuple[str, list[dict]]:
        executable = shutil.which(self.executable)
        if not executable:
            raise RuntimeError(
                "whisper.cpp is not installed; install whisper-cpp or configure "
                "WHISPER_CPP_EXECUTABLE"
            )
        if not self.model_path.is_file():
            raise RuntimeError(
                f"whisper.cpp model not found: {self.model_path}. "
                "Configure WHISPER_CPP_MODEL."
            )

        with tempfile.TemporaryDirectory(prefix="whisper-cpp-") as tmp:
            output_base = Path(tmp) / "transcript"
            command = [
                executable,
                "--model",
                str(self.model_path),
                "--file",
                str(audio_path),
                "--language",
                language,
                "--output-json",
                "--output-file",
                str(output_base),
                "--print-progress",
            ]
            process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            stderr_parts: list[str] = []
            reported_progress = -1

            def consume_stderr() -> None:
                nonlocal reported_progress
                assert process.stderr is not None
                buffer = ""
                while True:
                    char = process.stderr.read(1)
                    if not char:
                        break
                    stderr_parts.append(char)
                    buffer = (buffer + char)[-200:]
                    value = parse_progress(buffer)
                    if value is not None:
                        if value != reported_progress and self.progress_callback:
                            reported_progress = value
                            self.progress_callback(value)

            reader = threading.Thread(target=consume_stderr, daemon=True)
            reader.start()
            try:
                process.wait(timeout=settings.asr_timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise RuntimeError(
                    "whisper.cpp transcription timed out after "
                    f"{settings.asr_timeout_seconds}s"
                )
            finally:
                reader.join(timeout=5)

            if process.returncode != 0:
                details = "".join(stderr_parts).strip()[-1000:]
                raise RuntimeError(f"whisper.cpp transcription failed: {details}")
            if self.progress_callback and reported_progress != 100:
                self.progress_callback(100)

            json_path = output_base.with_suffix(".json")
            if not json_path.is_file():
                raise RuntimeError("whisper.cpp did not create JSON output")
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        segments = self._parse_segments(payload)
        lines = [
            f"[{self._format_timestamp(segment['start'])}] {segment['text']}"
            for segment in segments
            if segment["text"]
        ]
        return "\n".join(lines).strip(), segments

    @classmethod
    def _parse_segments(cls, payload: dict) -> list[dict]:
        result = []
        for item in payload.get("transcription") or payload.get("segments") or []:
            offsets = item.get("offsets") or {}
            timestamps = item.get("timestamps") or {}
            start = cls._seconds(
                offsets.get("from", item.get("start", timestamps.get("from", 0)))
            )
            end = cls._seconds(
                offsets.get("to", item.get("end", timestamps.get("to", start)))
            )
            # whisper.cpp JSON offsets are milliseconds.
            if offsets:
                start /= 1000
                end /= 1000
            text = (item.get("text") or "").strip()
            if text:
                result.append({"start": start, "end": end, "text": text})
        return result

    @staticmethod
    def _seconds(value) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if not value:
            return 0.0
        match = re.match(
            r"(?:(\d+):)?(\d+):(\d+)(?:[,.](\d+))?", str(value).strip()
        )
        if not match:
            return 0.0
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        fraction = float(f"0.{match.group(4)}") if match.group(4) else 0.0
        return hours * 3600 + minutes * 60 + seconds + fraction

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes:02d}:{remainder:02d}"
