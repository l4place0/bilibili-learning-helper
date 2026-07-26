"""JSON output utilities for CLI — structured events on stdout, logs on stderr."""

import json
import sys

SCHEMA_VERSION = 1


def emit(event: str, **data):
    """Print a JSON event line to stdout. Logs go to stderr."""
    obj = {"schema_version": SCHEMA_VERSION, "event": event, **data}
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def emit_error(message: str, code: int = 1, error_code: str = "operation_failed"):
    """Print an error event and exit."""
    emit("error", code=error_code, message=message)
    sys.exit(code)
