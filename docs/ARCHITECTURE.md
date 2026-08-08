# Architecture

This repository contains the local-first CLI only. It exposes deterministic
operation primitives. The separately versioned
[`bili-tutor-skill`](https://github.com/l4place0/bili-tutor-skill) lets a host
AI interpret intent, enhance transcripts, select frames, create Mermaid
diagrams, and assemble the final note.

## Core path

```text
Video URL
   |
   v
video-sum capture
   |
   +-- platform adapter / yt-dlp
   +-- user-level media cache
   +-- selected ASR provider
   +-- hybrid frame candidates
   |
   v
Host AI + external bili-tutor-skill
   |
   +-- transcript terminology enhancement
   +-- summary and Mermaid composition
   +-- semantic frame selection / follow-up extraction
   |
   v
video-sum resource compose
   |
   v
Single Markdown note + sibling assets/
```

The durable library is intentionally flat. A video produces one Markdown file;
selected images are copied to the library-level `assets/` directory. Capture
manifests contain stable cache keys rather than absolute cache paths.

## Distribution path

```text
v* tag
  -> GitHub Actions matrix
  -> PyInstaller standalone CLI per OS/architecture
  -> zip + manifest + SHA-256 sidecar
  -> GitHub Release
  -> bili-tutor-skill bootstrap download and atomic user-level install
```

The standalone bundle includes Python, Python dependencies, yt-dlp, the OpenAI
ASR client, and a platform FFmpeg executable supplied by `imageio-ffmpeg`.
Whisper models and `whisper-cli` remain optional external local-ASR assets.

## Modules

| Area | Main modules | Responsibility |
| --- | --- | --- |
| CLI | `cli/commands.py` | Capture, compose, library, cache, frame, and ASR primitives |
| Capture | `core/ingestion.py` | Download, ASR, frame extraction, and capture manifests |
| Cache | `core/cache.py` | User-level object cache, SQLite index, leases, TTL, and LRU |
| Library | `core/library.py` | Portable note composition and library queries |
| ASR | `core/asr/` | OpenAI API, generic local HTTP, and direct whisper.cpp providers |
| Vision | `core/vision/frames.py` | Hybrid scene/timestamp sampling and targeted extraction |
| Platforms | `core/platforms/` | Bilibili and YouTube URL/download adapters |
| Runtime | `core/runtime.py` | Bundled/system FFmpeg resolution |
| Release | `scripts/build_standalone.py`, `.github/workflows/release.yml` | Cross-platform bundle production |

## Storage boundaries

- Media, audio, transcripts, and candidate frames use the OS user cache
  directory through `platformdirs`.
- Whisper models use the OS user data directory and are never bundled with the
  CLI release.
- The resource library is user-selected and contains only durable notes/assets.
- `VIDEO_SUM_CACHE_DIR`, `VIDEO_SUM_MODEL_DIR`, and
  `VIDEO_SUM_LIBRARY_DIR` provide explicit overrides.
