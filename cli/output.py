"""JSON output utilities for CLI — structured events on stdout, logs on stderr."""

import json
import sys

SCHEMA_VERSION = 1


def _ensure_utf8_stdout():
    """Avoid Windows legacy-console encoding failures for NDJSON."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure and getattr(sys.stdout, "encoding", "").lower() != "utf-8":
        try:
            reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def emit(event: str, **data):
    """Print a JSON event line to stdout. Logs go to stderr."""
    _ensure_utf8_stdout()
    obj = {"schema_version": SCHEMA_VERSION, "event": event, **data}
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def emit_error(message: str, code: int = 1, error_code: str = "operation_failed"):
    """Print an error event and exit."""
    emit("error", code=error_code, message=message)
    sys.exit(code)
