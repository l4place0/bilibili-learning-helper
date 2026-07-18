# Tasks: CLI-Pipeline-Service Refactor

## Track A: Test Infrastructure
- [x] Create conftest.py with shared fixtures (Settings factory, mock helpers)
- [x] Add pytest markers (unit, integration, shell, e2e)
- [x] Refactor test_integration.py to use conftest fixtures
- [x] Fix missing json import in routes.py

## Track B: Pipeline Optimization
- [x] ffmpeg batch extraction (single select filter command)
- [x] Whisper vad_filter=True + batch_size optimization
- [x] InProcessASR inherits from BaseASR
- [x] Frame caching in _try_cache()

## Track C: Service Layer
- [x] Create core/workers.py (ThreadPoolExecutor + shutdown)
- [x] Create core/streaming.py (asyncio.Queue pub/sub)
- [x] Update routes.py to use workers + streaming
- [x] Add shutdown checkpoints in pipeline.py
- [x] Register shutdown_workers in app lifespan

## Track D: CLI Enhancement
- [x] Add --timeout option with time.monotonic()
- [x] Rich progress bar integration
- [x] atexit server cleanup
- [x] Fix Claude summarize() detail parameter
- [x] Add generating_three_stage to TaskStatus enum

## Verification
- [x] All 196 tests pass, 27 skipped, 0 failed
- [x] CLI --timeout option visible in --help
- [x] Import verification for new modules
