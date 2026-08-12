# Bili Tutor CLI

[中文](README.md) | English

A deterministic CLI for local video-learning workflows. It owns downloading,
transcription, candidate-frame extraction, caching, and atomic note writes.
Intent interpretation, terminology enhancement, visual selection, summaries,
and Mermaid diagrams belong to the host AI through the separate
[bili-tutor-skill](https://github.com/l4place0/bili-tutor-skill).

## Core workflow

```text
video URL
  → video-sum capture
  → raw transcript + candidate frames + optional audience material
  → host AI analysis
  → video-sum resource compose
  → one Markdown note + sibling assets/
```

The CLI supports Bilibili and YouTube, Chinese/English/Japanese transcription,
layered user-level caching, local whisper.cpp, OpenAI transcription, and a
compatible HTTP transcription service. Whisper models and `whisper-cli` are
not included in release bundles.

## Installation

For end users, install
[bili-tutor-skill](https://github.com/l4place0/bili-tutor-skill). Its thin
bootstrap downloads a platform-specific standalone bundle from this
repository's GitHub Releases:

```text
bili-tutor-cli-<version>-<platform>-<arch>.zip
├── video-sum[.exe]
└── manifest.json
```

For source development:

```bash
git clone https://github.com/l4place0/bili-tutor-cli.git
cd bili-tutor-cli
uv sync --extra dev
uv run video-sum --help
```

## CLI primitives

```bash
video-sum doctor
video-sum capture "<URL>" --frame-mode hybrid --cache reuse --frames 10
video-sum resource compose "<resource_id>" ...
video-sum library list|show|search
video-sum cache dir|status|list|inspect|prune|clear
video-sum frames extract "<video-file>" --at 12:30 --around 2
video-sum asr profiles
video-sum comments fetch "<URL>" --mode hot --output comments.jsonl
video-sum comments select comments.jsonl --output comment-candidates.json
video-sum danmaku fetch "<URL>" --output danmaku.jsonl
video-sum danmaku analyze danmaku.jsonl --output danmaku-analysis.json
```

`capture` creates reusable raw artifacts. After the host AI processes them,
`resource compose` atomically saves one Markdown note with these H1 sections:

```markdown
# 总结稿
# 辅助理解
# Data
```

Images live in a sibling `assets/` directory; no per-video directory is made.

Comment collection defaults to hot, highly liked top-level comments. Use
`--mode all --limit 0` to fetch every currently accessible top-level comment;
nested replies are intentionally excluded and full collection may be slow or
rate-limited. Danmaku collection anonymously requests the current `seg.so`
segments and never requests history. It falls back to the XML sample with
`sampled_degraded` metadata when segment retrieval fails.

`danmaku analyze` produces time hotspots, normalized repetition clusters, and
transparent lexicon signals. `comments select` produces engagement and
information-density candidates. Both require host-AI semantic review, and
popularity is never treated as proof of factual correctness.

## Paths and configuration

```dotenv
VIDEO_SUM_LIBRARY_DIR=/Users/you/Documents/video-notes
VIDEO_SUM_CACHE_DIR=/Users/you/Library/Caches/video-sum
VIDEO_SUM_MODEL_DIR=/Users/you/Library/Application Support/video-sum/models
VIDEO_SUM_DEFAULT_LANGUAGE=zh
VIDEO_SUM_DEFAULT_FRAMES=10
VIDEO_SUM_DEFAULT_FRAME_MODE=hybrid
VIDEO_SUM_DEFAULT_CACHE_POLICY=reuse
VIDEO_SUM_FACT_CHECK=auto
VIDEO_SUM_FACT_CHECK_SOURCE_POLICY=primary-first
```

Precedence is CLI arguments > environment > project `.env` > user
`config.env` > OS/built-in defaults. Selected frames are copied into `assets/`
and manifests store stable cache keys rather than absolute cache paths.

## Development and releases

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest
uv sync --extra standalone
uv run python scripts/build_standalone.py \
  --target darwin-arm64 --version 0.3.0
```

Tags matching `v*` trigger GitHub Actions to build five platform bundles plus
SHA-256 sidecars. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the
boundary model.

## License

MIT
