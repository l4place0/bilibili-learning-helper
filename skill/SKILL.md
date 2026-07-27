---
name: bilibili-learning-helper
description: >-
  Ingest Bilibili or YouTube videos into a local resource library through the
  video-sum CLI. Use when the user shares a video URL or share text, asks for a
  video summary/transcript/key frames, asks to save video learning material
  into a local folder, needs first-install configuration, or wants to diagnose
  and report a problem encountered in that workflow. The Skill interprets
  intent and composes deterministic CLI primitives.
---

# Video Learning Resource Ingestion

Use `video-sum` as the only business-operation interface. Interpret the user's
intent, choose explicit arguments, execute the CLI, and report its structured
result.

Before the first operation, run `python3 scripts/bootstrap.py status` on
macOS/Linux (`py -3 scripts/bootstrap.py status` on Windows). Use the exact
absolute executable returned in `command` for every CLI invocation. If
the runtime is missing or broken, read
[environment-recovery.md](references/environment-recovery.md), show the
pinned GitHub Release download plan, and obtain explicit approval before using
`--apply`. Never clone the repository or install Python packages during normal
recovery.

Before the first capture or compose operation, run
`python3 scripts/bootstrap.py onboard status` on macOS/Linux
(`py -3 scripts/bootstrap.py onboard status` on Windows). Consume the
secret-safe effective values and their sources. Configuration precedence is:
explicit CLI argument, process environment, project `.env`, user
`config.env`, then built-in default.

If library, cache, or ASR configuration has not been confirmed, compose an
onboarding plan with absolute paths and explicit options:

```bash
python3 scripts/bootstrap.py onboard \
  --scope project \
  --library-dir "<absolute-library-path>" \
  --cache-dir "<absolute-cache-path>" \
  --asr-provider whisper-cpp \
  --asr-profile balanced
```

Show the returned `onboard_plan` and obtain explicit approval before rerunning
with `--apply`. Applying may create directories and write project or user
configuration. Existing differing values are preserved unless the user
approves `--update`. Treat `onboard_done.ready=false` as a blocked setup and
report the failed checks; do not start a capture.

The project does not publish a GPU-specific whisper.cpp runtime. Never invent
a CUDA download URL or imply that hardware detection proves backend support.
Configure only an existing absolute `whisper-cli` path or a separately
verified runtime whose installation the user approved.

Consume `acceleration` and `ai_guidance` from bootstrap status before choosing
an ASR path:

- Treat `acceleration.hardware` only as a dependency-free hardware candidate
  probe. It does not prove that a compatible runtime is installed.
- If `acceleration.whisper_cpp.recommendation` is
  `prefer_whisper_cpp_gpu`, the user did not select another provider, and
  `doctor --asr-profile balanced` is healthy, prefer
  `--asr-profile balanced`. The detected whisper.cpp GPU backend is enabled by
  default; do not invent additional GPU flags.
- If the recommendation is `offer_gpu_whisper_setup` or
  `offer_gpu_whisper_runtime`, tell the user which hardware backend was
  detected and offer a matching GPU-enabled whisper.cpp runtime and model.
  Obtain approval before installing dependencies, then rerun bootstrap status
  and doctor. Keep the configured ASR provider until the backend is verified.
- If the probe is `unverified` or `unavailable`, keep the configured provider.
  Do not infer GPU support merely from installed GPU hardware or a
  `--no-gpu` help option.
- Always obey `frame_extraction.recommendation`. The current CLI frame pipeline
  is CPU-only even when bundled FFmpeg reports hardware acceleration methods;
  never add unsupported FFmpeg flags.

Run `<command> doctor --asr-profile <profile>` when capability state is
unknown or after a missing-tool or missing-provider failure. Consume its
structured checks; do not ask for credentials that are already configured.

In the examples below, replace `video-sum` with the exact `command` returned by
bootstrap status. Do not rely on shell PATH changes.

## Delegate analysis

Prefer subagents whenever the host supports them and the request contains two
or more independent content-analysis stages. Keep CLI mutations and final
resource assembly in the main agent.

After raw artifacts are available:

1. Run a transcript agent and a visual agent in parallel.
   - The transcript agent determines the domain, builds a glossary, corrects
     likely ASR terminology errors, and returns the corrected transcript plus a
     correction map. It must preserve timestamps and meaning.
   - The visual agent inspects the key frames, identifies which frames add
     explanatory value, and returns frame indices with concise reasons. It must
     inspect actual image contents rather than infer them from filenames.
     When a local source video is available and a UI transition, command, or
     prompt is only partly visible, request targeted follow-up frames with:

     ```bash
     video-sum frames extract "<video-file>" \
       --at "<MM:SS>" \
       --around 2 \
       --output-dir "<temporary-frame-dir>"
     ```

     Repeat `--at` for multiple regions. Treat scene/hybrid sampling as
     candidate generation and the host AI as the semantic selector.
2. Extract externally verifiable claims from the corrected transcript before
   synthesis. Preserve timestamps and include only `objective_fact` and
   `time_sensitive_fact`; do not fact-check opinions or personal experience.
   Follow the configured fact-check mode:
   - `off`: record `skipped` with `user_disabled`.
   - `auto`: verify important claims when search, page reading, source
     evaluation, and budget are available; otherwise record an explicit skip.
   - `important`: verify only decision-relevant or time-sensitive claims.
   - `all`: attempt every extracted factual claim.
   - `required`: stop before compose if verification cannot be completed.

   Prefer official material, primary papers, datasets, benchmarks, and source
   repositories. Use reliable secondary sources only when primary evidence is
   unavailable. Never treat a search-result snippet as verified evidence.
   Supported skip reason codes are `user_disabled`, `no_web_access`,
   `no_search_tool`, `no_page_reader`, `insufficient_source_evaluation`,
   `time_or_budget_limit`, and `source_unavailable`.
3. Give the corrected transcript, visual findings, and fact-check result to a
   synthesis agent. Ask
   it for the summary and `# 辅助理解` Markdown, including Mermaid diagrams and
   `{{frame:N}}` placeholders.
4. Use a verification agent to check factual faithfulness, source quality,
   claim timestamps, fact-check status, Mermaid syntax, frame references,
   heading order, and preservation of raw data.
5. Reconcile the results in the main agent and invoke the CLI once to save the
   resource.

Give each subagent only the artifacts needed for its role and require
structured output. Do not let multiple agents write the same note or run
overwriting CLI operations. Skip delegation for trivial read-only lookups,
very short material, or hosts without subagent support.

## Capture and compose a video

Run:

```bash
video-sum capture "<URL or complete share text>" \
  --output-dir "<destination>" \
  --lang zh \
  --frame-mode hybrid \
  --cache reuse \
  --fact-check auto \
  --frames 10
```

If the user has configured `VIDEO_SUM_LIBRARY_DIR`, omit `--output-dir` unless
they explicitly request a different destination. An explicit CLI destination
overrides the configured library only for that operation.

Pass complete Bilibili share text unchanged; the CLI extracts and HTML-decodes
the URL.

Ask for a destination only when it cannot be inferred from the request or
configured default. Preserve an explicitly supplied destination exactly.

Use:

- `--lang zh|en|ja` for the video's spoken/output language.
- `--asr-provider whisper-cpp|local|openai` only when the user selects or
  configuration recovery requires a specific transcription provider.
- `--asr-profile fast|balanced|accurate` selects a local `whisper.cpp` model
  from `ASR_MODEL_DIR` and implies `--asr-provider whisper-cpp`. When local
  model state is unknown, run `video-sum asr profiles` first. For local
  transcription, use `balanced` unless the user prioritizes speed or accuracy;
  do not select a profile for a configured remote provider.
- `--frames N` for key-frame count. Keep frames enabled unless the user
  explicitly requests audio-only output.
- `--frame-mode hybrid` combines uniform coverage with scene-change candidates
  and is the default for host-AI visual selection. Use `timestamp` for the
  fastest uniform sampling, or `scene` when transitions matter more than
  timeline coverage.
- `--cache reuse|refresh|off` defaults to `reuse`. Keep it for repeat work;
  use `refresh` only when the user asks to disregard cached artifacts, and
  `off` for cache-isolation diagnostics.
- `--fact-check off|auto|important|all|required` selects external verification
  strictness. Keep `auto` unless the user requests another mode.
- `--force` only after the user explicitly asks to replace an existing resource.

After delegation and verification, save the host-authored result exactly once:

```bash
video-sum resource compose "<resource_id>" \
  --summary-file "<summary.md>" \
  --understanding-file "<understanding.md>" \
  --corrected-transcript-file "<corrected-transcript.md>" \
  --corrections-file "<corrections.json>" \
  --fact-check-file "<fact-check.json>" \
  --fact-check auto \
  --output-dir "<destination>"
```

The summary and understanding files must not contain level-one headings.
The understanding file must contain at least one Mermaid diagram. The corrected
transcript is optional only when the user explicitly declines enhancement.

The fact-check file must use one of these distinct outcomes:

```json
{"schema_version":1,"status":"completed","mode":"important","checked_at":"2026-07-27","claims":[]}
```

```json
{"schema_version":1,"status":"skipped","mode":"auto","reason":"no_web_access","message":"Host has no web search or page-reading capability.","claims":[]}
```

A completed claim must include its timestamp, classification, video statement,
verification result, status, and linked sources. Supported claim statuses are
`confirmed`, `partially_confirmed`, `contradicted`, `outdated`, `disputed`,
and `unverified`. A non-`unverified` claim requires at least one linked source.
`completed` with no claims is not the same as `skipped`.

Distinguish video evidence, host inference, and external supplementation. Any
claim introduced from outside the captured video must include a clickable
source link next to the claim, preferring the author's own material and then a
reputable secondary source. If a source cannot be linked, omit the unsupported
detail or label it explicitly as unverified. Never present external
supplementation as content demonstrated by the video.

## Consume output

Treat stdout as versioned NDJSON. Ignore human logs on stderr.

Expected events:

```json
{"schema_version":1,"event":"started","source":"...","output_dir":"..."}
{"schema_version":1,"event":"stage","stage":"download","progress":10,"message":"..."}
{"schema_version":1,"event":"done","resource_id":"...","note_path":"...","manifest_path":"...","frame_paths":[]}
{"schema_version":1,"event":"composed","resource_id":"...","note_path":"...","manifest_path":"...","frame_paths":[]}
```

On success, verify the returned paths exist. Inspect the note and confirm it
contains these level-one headings in order:

```markdown
# 总结稿
# 辅助理解
# Data
```

Keep each resource as one Markdown note. Store every image in the single
`assets/` directory beside the note; never create a per-note directory.

The host AI authors `# 辅助理解` as Markdown containing one or more Mermaid
diagrams. Insert only frames that materially clarify the adjacent explanation,
using `{{frame:N}}` placeholders for the CLI to resolve. Put the complete raw
transcript and all extracted key frames under `# Data`; do not create separate
transcript or data files.

Report the saved note path, resource ID, and number of key frames. Do not paste
the full transcript back into chat unless requested.

## Inspect the resource library

Use read-only primitives:

```bash
video-sum library list --output-dir "<destination>"
video-sum library search "<query>" --output-dir "<destination>"
video-sum library show "<resource_id>" --output-dir "<destination>"
```

Use the `resource_id` returned by `capture` for an exact lookup. Prefer
`library search` over scanning Markdown files manually.

## Handle failures

Use the structured `code` field from the final `error` event:

- `invalid_input`: explain that the URL/platform or argument is unsupported.
- `resource_exists`: show the existing target and ask whether to rerun with
  `--force`; do not overwrite automatically.
- `ingestion_failed`: inspect stderr for the concrete provider/tool failure,
  then offer the narrow recovery action.

If `ffmpeg` or `yt-dlp` is missing, report the missing dependency. If ASR
credentials or local model capability are missing, ask the user which
configured transcription provider to use; do not silently switch providers.

If the problem remains unresolved, appears to be a product defect, or required
an undocumented workaround, offer to report it:

> 这个问题可能值得反馈给维护者。要我替你收集脱敏诊断、检查重复项、起草并创建 GitHub Issue 吗？提交前我会先把完整草稿给你确认，你不需要手动填写表单。

When the user accepts, read
[issue-reporting.md](references/issue-reporting.md) and complete the workflow
through the AI. Do not merely send the user to an empty form. Creating an Issue
is an external write: show the sanitized title and body and obtain explicit
confirmation immediately before submission. If no authenticated GitHub tool is
available, return the complete ready-to-submit draft and the repository Issue
URL instead of requesting credentials or claiming success.

## Safety

- Never delete or overwrite resources without explicit user authorization.
- Never echo API keys, cookies, or authorization headers.
- Never attach private video content, full transcripts, cookies, API keys,
  authorization headers, or local usernames to an Issue.
- Do not reimplement downloading, transcription, frame extraction, summary
  generation, or note rendering in shell/Python snippets; invoke the CLI
  primitive.
