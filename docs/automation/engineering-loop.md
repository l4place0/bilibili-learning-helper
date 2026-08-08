---
protocol: engineering-loop
version: 1
repository: l4place0/bili-tutor-cli
state_file: docs/automation/state.json
controller: docs/automation/loopctl.py
---

# Engineering Loop

## AI instructions

Read this document completely before engineering an Issue or Release.

All persistent run data MUST be read and changed through `loopctl.py`. The AI
MUST NOT edit `state.json` directly with an editor, patch, shell redirection,
or an ad-hoc script. GitHub Issues, pull requests, Actions, tags, and Releases
remain the remote sources of truth; the JSON file is a local coordination
ledger and is intentionally ignored by Git.

Begin by running `init`, `validate`, and `run start`. Before every mutation,
read the run and pass its current revision as `--expect-revision`. Record
evidence before requesting a state that depends on it. After an ambiguous
external write, inspect the remote system before calling `remote record` or
retrying the write.

Never fabricate tests, sources, commits, CI, Releases, or assets. Never
automatically merge, force-push, overwrite a Release, weaken branch
protection, or add `library/` resources. A missing capability or trustworthy
artifact is a structured blocker, not permission to invent evidence.

## Project policy

```yaml
project:
  default_branch: master
  protected_paths:
    - library/

quality:
  required_local_checks:
    - local_tests
    - lint
    - diff_check
  commands:
    local_tests: uv run pytest --tb=short -q
    lint: uv run ruff check .
    diff_check: git diff --check
  require_pull_request_ci: true

release:
  version_files:
    - pyproject.toml
    - uv.lock
    - cli/__init__.py
  targets:
    - darwin-arm64
    - darwin-x64
    - linux-arm64
    - linux-x64
    - windows-x64
  required_asset_checks:
    - asset_inventory
    - checksum
    - manifest
    - binary_smoke
```

## State machines

```yaml
state_machines:
  issue:
    initial: discovered
    terminal: [done, rejected]
    transitions:
      discovered: [analyzed, rejected, blocked]
      analyzed: [planned, rejected, blocked]
      planned: [implementing, blocked]
      implementing: [local_verified, planned, blocked]
      local_verified: [pr_open, implementing, blocked]
      pr_open: [ci_verified, implementing, blocked]
      ci_verified: [reported, implementing, blocked]
      reported: [done, blocked]
      blocked: [analyzed, planned, implementing, rejected]

  release:
    initial: merged
    terminal: [done]
    transitions:
      merged: [versioned, blocked]
      versioned: [tagged, merged, blocked]
      tagged: [building, versioned, blocked]
      building: [published, versioned, blocked]
      published: [asset_verified, blocked]
      asset_verified: [reported, blocked]
      reported: [done, blocked]
      blocked: [merged, versioned, building]
```

The controller additionally enforces evidence gates:

```yaml
evidence_gates:
  local_verified: [local_tests, lint, diff_check]
  pr_open: [pull_request]
  ci_verified: [ci]
  issue_reported: [issue_update]
  versioned: [version_consistency, local_tests, lint]
  tagged: [tag]
  published: [release]
  asset_verified: [asset_inventory, checksum, manifest, binary_smoke]
  release_reported: [release_update]
```

## Permissions

```yaml
permissions:
  automatic:
    - repository_read
    - issue_analysis
    - patch_generation
    - local_tests
    - self_review
  conditional:
    - code_changes
    - commit
    - push
    - create_pr
    - update_issue
    - push_master
    - create_tag
    - publish_release
  prohibited_by_default:
    - merge
    - force_push
    - overwrite_release
    - delete_remote_data
    - weaken_branch_protection
```

The run's authorization is captured at `run start`. The controller records
authorization but does not broaden it. External actions still require the
user's request or applicable repository policy.

## Controller usage

The CLI emits versioned JSON on stdout and errors as JSON with a nonzero exit
code. Human diagnostics belong on stderr.

```bash
python3 docs/automation/loopctl.py init
python3 docs/automation/loopctl.py validate

python3 docs/automation/loopctl.py run start \
  --operation issue \
  --repository l4place0/bili-tutor-cli \
  --issue 3 \
  --base-sha 7352e81 \
  --allow code_changes \
  --allow commit \
  --allow push \
  --allow create_pr \
  --allow update_issue

python3 docs/automation/loopctl.py run show "<run_id>"
python3 docs/automation/loopctl.py transition "<run_id>" analyzed \
  --expect-revision 1

python3 docs/automation/loopctl.py evidence add "<run_id>" \
  --kind local_tests \
  --status passed \
  --command "uv run pytest --tb=short -q" \
  --summary "all tests passed" \
  --expect-revision 2

python3 docs/automation/loopctl.py remote record "<run_id>" \
  --kind pull_request \
  --url "https://github.com/owner/repository/pull/4" \
  --number 4 \
  --state open \
  --head-sha abc1234 \
  --expect-revision 3

python3 docs/automation/loopctl.py blocker add "<run_id>" \
  --capability external_source_verification \
  --reason "No web access" \
  --resume-when "A search and page-reading capability is available" \
  --safe-fallback "Record an explicit skipped result"

python3 docs/automation/loopctl.py reconcile "<run_id>"
python3 docs/automation/loopctl.py result "<run_id>"
```

## Idempotency and recovery

```yaml
idempotency:
  issue_run: "{repository}:issue:{issue}:{base_sha}"
  release_run: "{repository}:release:{version}:{commit}"
  issue_evidence: "issue-engineering:{issue}:{head_sha}"
  release_evidence: "release:{version}:{commit}"

recovery:
  ambiguous_external_write:
    - query_remote_state
    - search_for_stable_marker
    - record_observed_remote_state
    - retry_only_when_absent
  revision_conflict:
    - run_show
    - reconcile_new_evidence
    - retry_with_current_revision
```

All mutations use a lock, compare-and-swap run revision, temporary file,
`fsync`, and atomic replacement. A revision conflict MUST be reconciled; it
MUST NOT be bypassed by editing the JSON file.

## Required result

Finish by returning the controller's `result` event and a concise human
summary.

```yaml
result:
  protocol_version: 1
  run_id: ""
  operation: issue
  final_state: ""
  revision: 0
  checks: {}
  remote: {}
  blockers: []
  evidence: {}
  authorization: {}
```

A blocker MUST include `capability`, `reason`, `resume_when`, and
`safe_fallback`. An Issue without verified progress and without a hard blocker
MUST remain open. A Release is not complete until published assets are
verified independently of the workflow's success status.
