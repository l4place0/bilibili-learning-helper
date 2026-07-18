# Architecture

## Module Dependency Graph

```
core/main.py  (FastAPI app, lifespan, static mount)
  |
  +-- core/api/routes.py  (REST endpoints: summarize, tasks, storage, publish)
  |     |
  |     +-- core/pipeline.py  (orchestrator: download -> ASR -> LLM -> output)
  |     |     |
  |     |     +-- core/platforms/  (BilibiliPlatform, YouTubePlatform)
  |     |     |     +-- core/platforms/base.py  (BasePlatform, YtdlpPlatform)
  |     |     |
  |     |     +-- core/asr/  (BaseASR providers)
  |     |     |     +-- core/asr/whisper.py  (InProcessASR, faster-whisper / openai-whisper)
  |     |     |     +-- core/asr/local.py  (LocalASR, self-hosted HTTP service)
  |     |     |     +-- core/asr/cloud.py  (OpenAIWhisperAPI, cloud Whisper)
  |     |     |
  |     |     +-- core/llm/  (BaseLLM providers)
  |     |     |     +-- core/llm/openai_proto.py  (OpenAILLM)
  |     |     |     +-- core/llm/claude.py  (ClaudeLLM)
  |     |     |     +-- core/llm/prompts.py  (prompt templates, content-type routing)
  |     |     |     +-- core/llm/prompt_store.py  (custom prompt persistence)
  |     |     |
  |     |     +-- core/vision/frames.py  (ffmpeg frame extraction)
  |     |     +-- core/storage/db.py  (SQLite Storage singleton)
  |     |     +-- core/observability/  (StageContext, metrics, evidence, JSONL logs)
  |     |     +-- core/workers.py  (ThreadPoolExecutor)
  |     |     +-- core/streaming.py  (asyncio.Queue SSE pub/sub)
  |     |
  |     +-- core/storage/files.py  (cache size, cleanup)
  |     +-- core/review_doc.py  (self-contained HTML review generator)
  |     +-- core/github/  (GitHub Pages publisher)
  |
  +-- core/config.py  (pydantic-settings, .env loading)
  +-- core/models.py  (Pydantic request/response schemas)
  +-- core/questions/  (question schema, LLM output parser)
  +-- core/templates/  (Jinja2 HTML templates)
  +-- core/web/  (SPA frontend: index.html, app.js, style.css)
```

## Pipeline Stages

The pipeline (`core/pipeline.py:run_pipeline`) processes a single task end-to-end. Each stage is wrapped in a `StageContext` that records structured observability data.

### Stage 1: Download

- **Input**: URL, mode (audio / multimodal)
- **Action**: `BasePlatform.download()` uses yt-dlp to fetch audio (and optionally video) from Bilibili or YouTube.
- **Output**: WAV audio file, video metadata (title, duration, tags, description, video_id), optional MP4 video path.
- **Cache check**: Before downloading, `_try_cache()` looks for a previously completed task with the same `video_id`. If found, it copies the cached audio, transcript, and frames to the new task directory and skips to the LLM stage.

### Stage 2: ASR (Transcription)

- **Input**: WAV audio file, language code
- **Action**: `BaseASR.transcribe_segments()` converts audio to timestamped text segments.
- **Output**: Plain transcript text and a list of `{"start", "end", "text"}` segment dicts.
- **Multimodal branch**: When `mode == "multimodal"`, frame extraction runs in parallel with transcription via a background thread. A heartbeat thread updates progress every 30 seconds to keep the UI responsive.

### Stage 3: Frame Extraction (multimodal mode only)

- **Input**: MP4 video file
- **Action**: `extract_frames()` in `core/vision/frames.py` uses ffmpeg to extract key frames. Default mode is "hybrid": uniform baseline (segment midpoints) plus scene-change detection.
- **Output**: List of frame image paths (WebP or JPEG).

### Stage 4: LLM Classification

- **Input**: Enriched transcript (transcript + metadata context: description, tags), language, multimodal flag
- **Action**: `BaseLLM.classify()` sends a short prompt to the LLM to determine content type (tutorial, tech_talk, demo, review, news, vlog, general).
- **Output**: `{"type": str, "summary": str}`.

### Stage 5: LLM Three-Stage Generation

- **Input**: Enriched transcript, content type, detail level, language, has_segments flag
- **Action**: `BaseLLM.generate_three_stage()` produces structured learning materials in one LLM call:
  - **Preview**: overview, guiding questions, pre-quiz
  - **Index**: timestamped topic outline
  - **Summary**: detailed text, review cards (Q&A), post-quiz, weak points
- **Output**: JSON structure saved to task metadata.
- **Streaming**: Summary text is pushed to the SSE stream buffer via `_stream_callback()`.

### Completion

- Task status set to `done` with all metadata, metrics, and timestamps.
- SSE subscribers receive a `done` event.
- If the task belongs to a group, `_maybe_trigger_synthesis()` checks whether all group tasks are complete and triggers a synthesis run if so.

## Provider Abstraction

### BaseASR (`core/asr/base.py`)

Abstract base class for speech recognition. Two methods:

- `transcribe(audio_path, language) -> str` -- plain text with `[MM:SS]` timestamps
- `transcribe_segments(audio_path, language) -> (str, list[dict])` -- text + structured segments

Implementations:
| Provider | Class | Backend |
|----------|-------|---------|
| `inprocess` (default) | `InProcessASR` | faster-whisper or openai-whisper, loaded in-process with CUDA/CPU auto-detection and OOM fallback |
| `local` | `LocalASR` | HTTP POST to a self-hosted Whisper service |
| `openai` | `OpenAIWhisperAPI` | OpenAI Whisper cloud API |

Factory: `core.asr.get_asr()` reads `settings.asr_provider` and returns the appropriate instance.

### BaseLLM (`core/llm/base.py`)

Abstract base class for language model providers. Core methods:

- `_chat(prompt, max_tokens) -> str` -- single-turn text completion
- `_chat_stream(prompt, max_tokens) -> Generator` -- streaming variant
- `_chat_multimodal(content, max_tokens) -> str` -- multimodal (text + images/video)
- `classify(transcript, lang, multimodal) -> dict` -- content type classification with retry
- `generate_three_stage(transcript, lang, detail, has_segments) -> dict` -- structured learning materials with retry and JSON validation

Implementations:
| Provider | Class | SDK |
|----------|-------|-----|
| `openai` (default) | `OpenAILLM` | `openai` Python SDK, supports streaming and native video upload |
| `claude` | `ClaudeLLM` | `anthropic` Python SDK, supports multimodal via base64 images |

Factory: `core.llm.get_llm()` reads `settings.llm_provider` and returns the appropriate instance.

### BasePlatform (`core/platforms/base.py`)

Abstract base class for video platform adapters. Methods:

- `match(url) -> bool` -- URL pattern matching
- `parse_url(url) -> str` -- extract video ID
- `download(url, output_dir, keep_video) -> (audio_path, metadata, video_path)` -- full download with retry

`YtdlpPlatform` provides a shared base for yt-dlp-based platforms with retry logic, parallel audio+video download, and metadata extraction.

Implementations:
| Platform | Class | URL Pattern |
|----------|-------|-------------|
| Bilibili | `BilibiliPlatform` | `bilibili.com/video/BV...` (with cookie support) |
| YouTube | `YouTubePlatform` | `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/embed/` |

Registry: `PLATFORMS` list in `core/pipeline.py`, matched via `get_platform(url)`.

## Storage Schema

### SQLite `tasks` table (`core/storage/db.py`)

```sql
CREATE TABLE tasks (
    task_id      TEXT PRIMARY KEY,       -- UUID
    url          TEXT NOT NULL,
    platform     TEXT NOT NULL,           -- "bilibili", "youtube", "synthesis"
    status       TEXT NOT NULL DEFAULT 'pending',
    summary      TEXT,                    -- LLM-generated summary (markdown)
    transcript   TEXT,                    -- full transcript text
    metadata     TEXT,                    -- JSON blob (title, duration, video_id, tags, etc.)
    error        TEXT,                    -- error message on failure
    created_at   TEXT NOT NULL,           -- ISO 8601 UTC
    completed_at TEXT,                    -- ISO 8601 UTC
    favorite     INTEGER NOT NULL DEFAULT 0,
    progress     INTEGER,                 -- 0-100 percentage
    video_id     TEXT                     -- platform video ID (indexed)
);

CREATE INDEX idx_tasks_video_id ON tasks(video_id);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);
```

**Metadata JSON structure** (stored in `metadata` column):
```json
{
  "title": "...",
  "duration": 1234,
  "thumbnail": "...",
  "uploader": "...",
  "video_id": "BV...",
  "description": "...",
  "tags": ["..."],
  "content_type": "tutorial",
  "language": "zh",
  "transcript_segments": [{"start": 0.0, "end": 5.0, "text": "..."}],
  "preview": {"overview": "...", "questions": [...], "pre_quiz": [...]},
  "index": [{"time": "01:23", "topic": "..."}],
  "questions": [{"id": "...", "type": "qa", "question": "...", "answer": "..."}],
  "metrics": {"download": {...}, "transcribe": {...}, "total_duration_ms": ...},
  "group_id": "abc123",
  "synthesis_for": "abc123",
  "publish_url": "https://...",
  "published_at": "..."
}
```

### SQLite `evidence` table (`core/observability/evidence.py`)

```sql
CREATE TABLE evidence (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id        TEXT NOT NULL,
    stage          TEXT NOT NULL,
    status         TEXT NOT NULL,
    input_summary  TEXT,          -- JSON
    output_summary TEXT,          -- JSON
    decisions      TEXT,          -- JSON array
    warnings       TEXT,          -- JSON array
    duration_ms    INTEGER,
    created_at     TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
```

### Filesystem layout (`data/`)

```
data/
  db.sqlite3              -- SQLite database
  logs/
    {task_id}.jsonl        -- per-task structured event log
  cache/
    audio/{task_id}/       -- WAV audio files
    transcripts/{task_id}.txt  -- plain transcript files
    frames/{task_id}/      -- extracted frame images (WebP/JPEG)
  github-repo/             -- local clone for GitHub Pages publishing
```

## Threading Model

- **API layer**: FastAPI (asyncio event loop) handles HTTP requests.
- **Pipeline execution**: Background tasks run in a `ThreadPoolExecutor` (`core/workers.py`) with 3 worker threads. Submitted via `submit_pipeline()`.
- **Graceful shutdown**: A `_shutdown` threading.Event signals workers to stop. `shutdown_workers()` sets the event and waits for in-flight tasks. The pipeline checks `_shutdown.is_set()` at two checkpoints (after download/transcribe and after classify) to abort early.
- **SQLite concurrency**: A single `Storage` instance is shared across all threads. All write operations are serialized via a module-level `_write_lock` (threading.Lock). The connection uses WAL journal mode for concurrent reads.
- **SSE streaming**: `_stream_buffers` (dict of task_id -> list of chunks) is protected by `_stream_lock`. The `core/streaming.py` module uses `asyncio.Queue` for pub/sub between the pipeline thread and the async SSE endpoint.
- **Frame extraction**: In multimodal mode, transcription and frame extraction run in parallel within the pipeline thread using a `ThreadPoolExecutor(max_workers=2)`.
- **Heartbeat**: A daemon thread updates task progress every 30 seconds during long-running stages (transcription + frame extraction).

## Extension Points

### Adding a new video platform

1. Create `core/platforms/newplatform.py` extending `YtdlpPlatform` (or `BasePlatform` for non-yt-dlp sources).
2. Implement `match(url)`, `parse_url(url)`, and optionally override `_get_ydl_opts()` for platform-specific options (cookies, format selection).
3. Add an instance to the `PLATFORMS` list in `core/pipeline.py`.

### Adding a new ASR provider

1. Create `core/asr/newprovider.py` extending `BaseASR`.
2. Implement `transcribe()` and optionally `transcribe_segments()`.
3. Register in the `get_asr()` factory in `core/asr/__init__.py`.

### Adding a new LLM provider

1. Create `core/llm/newprovider.py` extending `BaseLLM`.
2. Implement `_chat()` at minimum. Override `_chat_stream()`, `_chat_multimodal()` for richer support.
3. Register in the `_PROVIDERS` dict in `core/llm/__init__.py`.

### Adding new content types

1. Add the type name to `CONTENT_TYPES` in `core/llm/prompts.py`.
2. Add a classification prompt variant in `get_classify_prompt()`.
3. Add a summary prompt template in `get_summary_prompt()` with appropriate structure for the content type.
4. Optionally add a question-type preference mapping in `core/questions/schema.py:CONTENT_TYPE_QUESTION_MAP`.

### Adding new question types

1. Define the type constant in `core/questions/schema.py` and add it to `ALL_TYPES`.
2. Add any LLM-side prompt guidance for generating that question type.
3. The frontend renders questions generically from the question dict structure.

### Customizing prompts

Prompts can be customized at runtime via the `/api/prompts` endpoints without code changes. Custom prompts are persisted by `core/llm/prompt_store.py` and override the built-in defaults.
