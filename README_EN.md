# Bilibili Learning Helper

English | [中文](README.md)

A Skill-driven, local-first video learning library. The CLI exposes
deterministic primitives; the host AI interprets intent, improves terminology,
selects frames, and writes summaries and Mermaid diagrams.

## Core workflow

```text
Video URL
  -> video-sum capture
  -> raw transcript + frame candidates
  -> Host AI / Skill
  -> video-sum resource compose
  -> one Markdown note + sibling assets/
```

The core supports Bilibili and YouTube, Chinese/English/Japanese
transcription, a user-level artifact cache, direct `whisper.cpp`, the OpenAI
transcription API, and a generic local HTTP ASR endpoint.

## Skill installation

Normal Skill use does not clone the repository, create a virtual environment,
or install Python packages. The bootstrap uses the host's Python to select a
pinned platform-specific GitHub Release; the installed CLI does not depend on
the host Python:

```bash
python3 skill/scripts/bootstrap.py status
python3 skill/scripts/bootstrap.py install
# After reviewing the version, URLs, checksum, and destination:
python3 skill/scripts/bootstrap.py install --apply
```

Each bundle contains the Python runtime, Python dependencies, yt-dlp, the
OpenAI ASR client, and FFmpeg. It excludes `whisper-cli` and Whisper models.
The bootstrap verifies the release's SHA-256 sidecar and manifest before an
atomic user-level installation.

After installing the CLI, generate a first-use configuration plan:

```bash
python3 skill/scripts/bootstrap.py onboard \
  --scope project \
  --library-dir "/absolute/path/video-notes" \
  --cache-dir "/absolute/path/video-cache" \
  --asr-provider whisper-cpp \
  --asr-profile balanced
# After reviewing the config file, directories, and runtime probes:
python3 skill/scripts/bootstrap.py onboard ... --apply
python3 skill/scripts/bootstrap.py onboard status
```

`onboard` is side-effect free unless `--apply` is present. Apply creates
directories and atomically writes project or user configuration; it preserves
different existing values unless `--update` is explicitly approved. Status
reports effective value sources and credential presence without printing
secrets. The project publishes no CUDA-specific whisper.cpp bundle, so the
plan never invents a GPU runtime URL or treats hardware detection as loaded
backend evidence.

## Capture and compose

```bash
uv run video-sum doctor --asr-profile balanced
uv run video-sum capture "https://www.bilibili.com/video/BVxxxxx/" \
  --asr-profile balanced \
  --frame-mode hybrid \
  --cache reuse \
  --frames 10
```

The Skill then asks the host AI to enhance the transcript and visual
explanation before invoking `video-sum resource compose`. Each resource is one
Markdown file with these level-one sections:

```markdown
# 总结稿
# 辅助理解
# Data
```

All images live in the sibling `assets/` directory.

## Paths

```dotenv
VIDEO_SUM_LIBRARY_DIR=/absolute/path/to/video-notes
VIDEO_SUM_CACHE_DIR=/absolute/path/to/cache
VIDEO_SUM_MODEL_DIR=/absolute/path/to/whisper-models
VIDEO_SUM_DEFAULT_LANGUAGE=zh
VIDEO_SUM_DEFAULT_FRAMES=10
VIDEO_SUM_DEFAULT_FRAME_MODE=hybrid
VIDEO_SUM_DEFAULT_CACHE_POLICY=reuse
```

Precedence is CLI argument > environment > project `.env` > user
`config.env` > operating-system or built-in default.
Models are never bundled with the project or Skill.

## CLI primitives

```bash
video-sum doctor
video-sum capture "<URL>"
video-sum resource compose "<resource_id>" ...
video-sum library list|show|search
video-sum cache dir|status|list|inspect|prune|clear
video-sum frames extract "<video-file>" --at 12:30 --around 2
video-sum asr profiles
```

## Skill package

```text
skill/
├── SKILL.md
├── agents/openai.yaml
├── references/environment-recovery.md
└── scripts/bootstrap.py
```

`bootstrap.py status` returns the exact executable in `command`.
`bootstrap.py install` produces a pinned download plan; adding `--apply`
downloads, verifies, and installs it.

## Development

```bash
git clone https://github.com/l4place0/bilibili-learning-helper.git
cd bilibili-learning-helper
uv sync --extra dev
uv run ruff check .
uv run pytest
uv sync --extra standalone
uv run python scripts/build_standalone.py \
  --target darwin-arm64 --version 0.2.0
```

Pushing a `v*` tag runs the five-platform release workflow and publishes each
bundle with its `.sha256` sidecar.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module boundaries.

## License

MIT
