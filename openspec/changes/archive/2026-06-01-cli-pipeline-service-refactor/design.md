# Design: CLI-Pipeline-Service Refactor

## Architecture

```
CLI (thin wrapper)
  └── Starts embedded FastAPI (daemon thread)
        ├── ThreadPoolExecutor(max_workers=3)
        │     └── run_pipeline()
        │           ├── download → cache
        │           ├── ASR (get_asr() → inprocess/local/openai)
        │           ├── LLM classify + summarize
        │           └── publish() → asyncio.Queue → SSE
        ├── SQLite task tracking
        └── Graceful shutdown (threading.Event checkpoints)
```

## Key Decisions

### CLI wraps Web server (not direct pipeline)
- Eliminates code duplication (`_run_local()` removed)
- CLI inherits all caching, task management, streaming
- `--remote` mode connects to external server

### ThreadPoolExecutor (not Celery)
- Single-server, SQLite storage — no Redis dependency
- Bounded concurrency (max_workers=3)
- Graceful shutdown via `executor.shutdown(wait=True)`

### asyncio.Queue SSE (not polling)
- Eliminates 500ms polling latency
- `subscribe()`/`publish()`/`unsubscribe()` pattern
- Bridge from sync pipeline to async SSE via `call_soon_threadsafe`

### ffmpeg batch extraction
- Single `select` filter command vs N subprocess invocations
- Saves ~30-60s per video (subprocess startup overhead)

### Whisper VAD + batch_size
- `vad_filter=True` reduces effective audio 20-40%
- `batch_size=4` on GPU, `batch_size=2` on CPU

## File Changes

| File | Change |
|------|--------|
| `cli/commands.py` | Timeout, Rich progress, server lifecycle |
| `core/workers.py` | New: ThreadPoolExecutor + shutdown |
| `core/streaming.py` | New: asyncio.Queue pub/sub |
| `core/api/routes.py` | Use workers + streaming, fix json import |
| `core/pipeline.py` | ASR abstraction, shutdown checkpoints, frame cache |
| `core/vision/frames.py` | Batch ffmpeg extraction |
| `core/asr/whisper.py` | VAD, batch_size, InProcessASR inherits BaseASR |
| `core/llm/claude.py` | Fix detail parameter |
| `core/models.py` | Add generating_three_stage status |
| `tests/conftest.py` | Shared fixtures, Settings factory |
