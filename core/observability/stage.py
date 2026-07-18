"""StageContext — structured logging context manager for pipeline stages."""

import logging
import time
import traceback
from datetime import datetime, timezone

from core.observability.logger import write_event
from core.observability.evidence import insert_evidence
from core.observability.metrics import record_stage

logger = logging.getLogger(__name__)


class StageContext:
    """Context manager that captures a structured stage event.

    Usage:
        with StageContext(task_id, "transcribe") as stage:
            stage.input(audio_path=str(path), language="zh")
            transcript = asr.transcribe(path, language)
            stage.output(text_length=len(transcript))
            if len(transcript) == 0:
                stage.warning("0 chars transcribed")
            stage.decision("backend", "faster-whisper", reason="configured")
    """

    def __init__(self, task_id: str, stage_name: str):
        self.task_id = task_id
        self.stage_name = stage_name
        self._input_data: dict = {}
        self._output_data: dict = {}
        self._decisions: list[dict] = []
        self._warnings: list[str] = []
        self._status = "success"
        self._error: str | None = None
        self._started_at: str = ""
        self._start_time: float = 0

    def __enter__(self) -> "StageContext":
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._start_time = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        duration_ms = int((time.monotonic() - self._start_time) * 1000)

        if exc_type is not None:
            self._status = "error"
            self._error = f"{exc_type.__name__}: {exc_val}"

        event = {
            "task_id": self.task_id,
            "stage": self.stage_name,
            "status": self._status,
            "started_at": self._started_at,
            "duration_ms": duration_ms,
            "input": self._input_data,
            "output": self._output_data,
            "decisions": self._decisions,
            "warnings": self._warnings,
        }
        if self._error:
            event["error"] = self._error

        try:
            write_event(self.task_id, event)
        except Exception:
            logger.warning("Failed to write JSONL log for %s/%s", self.task_id[:8], self.stage_name)

        try:
            insert_evidence(
                task_id=self.task_id,
                stage=self.stage_name,
                status=self._status,
                input_summary=self._input_data,
                output_summary=self._output_data,
                decisions=self._decisions,
                warnings=self._warnings,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.warning("Failed to write evidence for %s/%s", self.task_id[:8], self.stage_name)

        try:
            record_stage(self.stage_name, self._status, duration_ms)
        except Exception:
            pass

        # Log at appropriate level
        if self._status == "error":
            logger.error("[%s] %s failed in %dms: %s", self.task_id[:8], self.stage_name, duration_ms, self._error)
        elif self._warnings:
            logger.warning("[%s] %s done in %dms (warnings: %s)", self.task_id[:8], self.stage_name, duration_ms, "; ".join(self._warnings))
        else:
            logger.info("[%s] %s done in %dms", self.task_id[:8], self.stage_name, duration_ms)

        return False  # Don't suppress exceptions

    def input(self, **kwargs):
        """Record input parameters (key summaries, not full data)."""
        self._input_data.update(kwargs)

    def output(self, **kwargs):
        """Record output results."""
        self._output_data.update(kwargs)

    def warning(self, msg: str):
        """Record a warning."""
        self._warnings.append(msg)

    def decision(self, key: str, value: str, reason: str = ""):
        """Record a decision point."""
        entry = {"key": key, "value": value}
        if reason:
            entry["reason"] = reason
        self._decisions.append(entry)
