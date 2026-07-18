# Proposal: CLI-Pipeline-Service Refactor

## Problem

The project had three architectural issues:
1. **CLI duplicated pipeline logic** — `_run_local()` reimplemented download→transcribe→LLM without SQLite caching or task tracking
2. **Pipeline used raw threading** — `threading.Thread` with no concurrency limit, no graceful shutdown, SSE via 500ms polling
3. **Test infrastructure was fragile** — MagicMock settings copy-pasted across 4 files, mock paths broken by module refactoring

## Solution

Unified architecture: CLI wraps the Web server (embedded FastAPI), shares pipeline + SQLite cache. Pipeline and service layer upgraded with proper concurrency, streaming, and shutdown. Tests refactored with shared fixtures.

## Scope

- CLI: `run` starts embedded server, `serve` for standalone, `--timeout`, Rich progress
- Pipeline: ASR abstraction, ffmpeg batch extraction, Whisper VAD, frame caching
- Service: ThreadPoolExecutor, asyncio.Queue SSE, graceful shutdown
- Tests: conftest.py, Settings factory, 58 new tests

## Non-goals

- Distributed task queue (Celery/Redis) — single-server is sufficient
- New platform support — Bilibili + YouTube only
- Frontend changes — WebUI unchanged
