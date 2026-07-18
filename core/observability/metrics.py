"""In-memory metrics aggregation with Prometheus text format output."""

import threading

_lock = threading.Lock()

# Counters: name -> value
_counters: dict[str, float] = {}

# Histograms: name -> list of observed values
_histograms: dict[str, list[float]] = {}

# Special counters
_transcribe_empty_total = 0
_llm_fallback_total = 0


def _counter_name(name: str, labels: dict[str, str] | None = None) -> str:
    if not labels:
        return name
    label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}"


def record_stage(stage: str, status: str, duration_ms: int) -> None:
    """Record a pipeline stage completion."""
    global _transcribe_empty_total, _llm_fallback_total
    with _lock:
        # Stage counter
        key = _counter_name("pipeline_stage_total", {"stage": stage, "status": status})
        _counters[key] = _counters.get(key, 0) + 1

        # Duration histogram
        hkey = f"pipeline_stage_duration_seconds{{stage=\"{stage}\"}}"
        if hkey not in _histograms:
            _histograms[hkey] = []
        _histograms[hkey].append(duration_ms / 1000.0)

        # Special counters
        if stage == "transcribe" and status == "success":
            # Will be updated separately via record_transcribe_result
            pass


def record_transcribe_empty() -> None:
    """Increment empty transcription counter."""
    global _transcribe_empty_total
    with _lock:
        _transcribe_empty_total += 1


def record_llm_fallback() -> None:
    """Increment LLM fallback counter."""
    global _llm_fallback_total
    with _lock:
        _llm_fallback_total += 1


def get_metrics() -> dict:
    """Return current metrics snapshot."""
    with _lock:
        return {
            "counters": dict(_counters),
            "histograms": {k: list(v) for k, v in _histograms.items()},
            "transcribe_empty_total": _transcribe_empty_total,
            "llm_fallback_total": _llm_fallback_total,
        }


def metrics_text() -> str:
    """Generate Prometheus text format output."""
    with _lock:
        lines = []

        # HELP/TYPE headers
        lines.append("# HELP pipeline_stage_total Total pipeline stage executions")
        lines.append("# TYPE pipeline_stage_total counter")
        for name, value in sorted(_counters.items()):
            lines.append(f"{name} {int(value)}")

        lines.append("# HELP pipeline_stage_duration_seconds Pipeline stage duration in seconds")
        lines.append("# TYPE pipeline_stage_duration_seconds histogram")
        for name, values in sorted(_histograms.items()):
            if not values:
                continue
            base = name.split("{")[0]
            label = name[len(base):]
            # Strip trailing }
            label_inner = label.strip("{}")

            total = sum(values)
            count = len(values)
            lines.append(f'{base}_count{{label_inner}} {count}'.replace("label_inner", label_inner))
            lines.append(f'{base}_sum{{label_inner}} {total:.3f}'.replace("label_inner", label_inner))

            # Buckets: 0.1, 0.5, 1, 5, 10, 30, 60, 120, 300
            buckets = [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
            for b in buckets:
                count_le = sum(1 for v in values if v <= b)
                lines.append(f'{base}_bucket{{le="{b}",{label_inner}}} {count_le}')
            lines.append(f'{base}_bucket{{le="+Inf",{label_inner}}} {count}')

        lines.append("# HELP pipeline_transcribe_empty_total Transcriptions that produced 0 chars")
        lines.append("# TYPE pipeline_transcribe_empty_total counter")
        lines.append(f"pipeline_transcribe_empty_total {_transcribe_empty_total}")

        lines.append("# HELP pipeline_llm_fallback_total LLM multimodal-to-text fallbacks")
        lines.append("# TYPE pipeline_llm_fallback_total counter")
        lines.append(f"pipeline_llm_fallback_total {_llm_fallback_total}")

        return "\n".join(lines) + "\n"
