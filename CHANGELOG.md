# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-06-02

### Added

- Video summarization pipeline: download (yt-dlp) -> transcribe (Whisper ASR) -> classify (LLM) -> summarize (LLM)
- Content-type-aware structured prompts for 7 video categories (tutorial, tech_talk, demo, review, news, vlog, general)
- Multimodal frame extraction with interval and scene-change modes
- Batch and group summarization endpoints with combined synthesis
- SSE streaming for real-time summary output
- Prompt customization (classify and per-content-type summary prompts)
- GitHub Pages publishing for review documents
- Bilibili cookies management for VIP/login content
- Prometheus-compatible metrics endpoint
- Evidence chain tracking per task
- Task favorites, retry, and granular resource endpoints (metadata, transcript, summary, frames)
- Storage management with auto-cleanup and manual purge
- API key authentication (optional via API_SECRET)
- Web UI with dark theme
- Skill scripts for CLI-based usage
- Docker Compose deployment
