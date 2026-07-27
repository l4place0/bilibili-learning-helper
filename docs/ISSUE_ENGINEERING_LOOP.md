# AI Issue Engineering Loop

This repository uses a goal-driven loop for turning an Issue into reviewable
evidence. The loop may be started on demand or by a periodic automation, but
external writes and integration remain explicitly gated.

## Recommended composition

- **Goal/loop** owns one run, its budget, current state, and exit condition.
- **Skill instructions** provide reusable intent analysis, safety rules, and
  evidence requirements across repositories.
- **Repository workflows** are the authoritative quality gate for lint and
  tests. They do not create or merge implementation commits.
- **Automation** may periodically discover and triage Issues. It may open an
  implementation run only when repository policy allows it; it must never
  merge, publish, or weaken branch protection.

The loop does not belong in the product Skill. Product usage instructions and
engineering governance have different triggers and permission boundaries.
Keep the contract repository-local for this first trial. Promote it to a
dedicated cross-repository engineering Skill only after a second repository
validates that the states and evidence schema generalize.

## State machine

```text
DISCOVERED
  -> ANALYZED
  -> PLANNED
  -> IMPLEMENTING
  -> TESTED
  -> REVIEWED
  -> COMMITTED
  -> PR_OPEN
  -> REPORTED
  -> DONE
```

Any state may move to `BLOCKED` with a concrete missing fact, permission, or
dependency. `IMPLEMENTING` through `REVIEWED` may move back to `PLANNED` after
new evidence. A failed write stays in its current state and is retried by
looking up the intended remote object before creating another one.

Exit successfully only when the PR exists, required local checks passed, CI is
green or explicitly pending, and the Issue contains links to the PR and
evidence. Exit blocked when an acceptance criterion cannot be conservatively
implemented without a missing artifact or decision. Exit rejected when the
Issue is duplicate, invalid, unsafe, or no longer desired.

## Gates and permissions

| Action | Default |
| --- | --- |
| Read Issues, code, history, releases, and CI | Automatic |
| Analyze intent, duplicates, risk, and acceptance criteria | Automatic |
| Generate a task plan, patch, tests, and local review | Automatic |
| Create or switch an isolated branch | Automatic within the requested repo |
| Commit a reviewed, scoped patch | Automatic after local gates pass |
| Push the implementation branch | External write; allowed only for the requested run |
| Create/update a PR and post Issue evidence | External write; allowed only after quality gates |
| Install dependencies, publish releases, change secrets/protection | Approval required |
| Merge, force-push, delete branches, close without accepted evidence | Never automatic |

Use `Closes #N` only when the implemented scope satisfies the Issue's
acceptance criteria. Otherwise use `Refs #N` and record the remaining blocker.
An Issue may be closed as blocked only when the evidence identifies a hard
external constraint and a concrete condition for reopening. With neither
verified progress nor a hard blocker, leave it open.

## Idempotency and recovery

Use `(repository, issue number, base commit)` as the run key. Derive one stable
branch name and search for an existing open PR from that branch before
creating one. Before posting a comment, search for the run marker
`issue-engineering:<issue>:<head-sha>` and update or skip matching evidence.
Do not duplicate commits when the tree is unchanged.

Keep patches atomic and exclude unrelated dirty files. On test failure, retain
the worktree and return to `IMPLEMENTING`. On push or API timeout, read remote
branch, PR, and comment state before retrying. On base-branch drift, fetch,
replay only when conflict-free, then rerun all gates. Never treat a network
timeout as proof that a write failed.

## Executable checklist

1. Capture the Issue body, comments, labels, related Issues/PRs, release facts,
   current branch, dirty files, CI commands, and repository instructions.
2. Restate the real user outcome, acceptance tests, assumptions, duplicates,
   blockers, risks, and deliberately excluded scope.
3. Write an ordered task list and mark each task automatic, approval-gated, or
   blocked.
4. Implement the smallest conservative patch and add regression tests.
5. Run targeted tests, the full test suite, lint, and any platform-safe smoke
   checks. Preserve exact commands and results.
6. Review the diff for correctness, secrets, unrelated files, fabricated
   evidence, unsafe writes, and incomplete acceptance criteria.
7. Commit one coherent change, push the stable branch, and create a PR only
   after step 5 passes. Do not merge.
8. Post one idempotent evidence update to the Issue with the PR, commit, test
   results, residual limitations, and next state.

## Issue #1 trial plan

| Task | Mode | Done when |
| --- | --- | --- |
| Layer project and user configuration with explicit precedence and secret-safe source reporting | Automatic | Unit tests prove precedence and redaction |
| Add `bootstrap.py onboard`, `onboard status`, and `--apply` for library, cache, ASR, and capture defaults | Automatic; apply is user-approved in real use | Plan is side-effect free and repeated apply is idempotent |
| Validate absolute/writable paths and UTF-8 NDJSON; surface existing GPU/runtime probes | Automatic | Cross-platform unit tests and local smoke checks pass |
| Download/install a CUDA whisper.cpp runtime | Blocked | No published, pinned, checksum-verified project artifact exists |
| Update Skill guidance and user docs | Automatic | First use invokes onboarding without manual `.env` editing |
| Commit, PR, and Issue evidence | External write after gates | PR uses `Closes #1`; no merge |
