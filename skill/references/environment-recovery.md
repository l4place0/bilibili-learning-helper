# Runtime recovery

Use this reference only when `video-sum` is missing or its bundled runtime is
broken.

## State machine

1. Run `python3 scripts/bootstrap.py status` on macOS/Linux, or
   `py -3 scripts/bootstrap.py status` on Windows.
2. If `ready` is true, use the exact absolute executable in `command`.
   Consume the `acceleration` probe and follow each `ai_guidance` entry.
   Hardware candidates do not require optional dependencies, but do not prove
   runtime support. Treat `available` as verified loaded-backend evidence,
   `runtime_missing` and `runtime_gpu_unverified` as reasons to offer an
   approved setup action, and `unsupported` as a prohibition on inventing
   acceleration flags.
3. If the CLI is missing, run `python3 scripts/bootstrap.py install` on
   macOS/Linux (or `py -3 scripts/bootstrap.py install` on Windows) without
   `--apply` and show the pinned release URL, checksum URL, target, and
   destination to the user.
4. After explicit approval, rerun with `--apply`.
5. Run the returned absolute command with `doctor`.
6. Use `repair --apply` with the same repository and version if verification
   fails.

Do not clone the repository, install Python packages, create a virtual
environment, or invoke `uv` during normal Skill recovery.

## Release source

The Skill defaults to:

```text
repository: l4place0/bilibili-learning-helper
version: 0.2.0
```

Each platform asset contains the CLI, Python runtime, Python dependencies,
OpenAI ASR client, yt-dlp, and FFmpeg. The bootstrap verifies its `.sha256`
sidecar and internal manifest before atomically installing the executable.

Override the source only when the user or trusted deployment configuration
explicitly supplies it:

```bash
python3 scripts/bootstrap.py install \
  --repository "trusted-owner/trusted-repository" \
  --version "1.2.3"
```

`VIDEO_SUM_RELEASE_REPOSITORY`, `VIDEO_SUM_RELEASE_VERSION`,
`VIDEO_SUM_BIN_DIR`, and `VIDEO_SUM_EXECUTABLE` provide managed overrides.
`GITHUB_TOKEN` may be present for private release downloads; never print it.

## Optional local transcription

Release assets intentionally exclude `whisper-cli` and Whisper models.
OpenAI/API transcription works from the bundle. Local whisper.cpp requires the
user to install `whisper-cli` and one selected model separately. Show the exact
external installation action and obtain approval before changing the machine.
