#!/usr/bin/env python3
"""Deterministic state controller for the repository engineering loop."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.parse
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1
DEFAULT_STATE_FILE = Path(__file__).with_name("state.json")
LOCK_TIMEOUT_SECONDS = 5
STALE_LOCK_SECONDS = 300

AUTHORIZATION_KEYS = {
    "code_changes",
    "commit",
    "push",
    "create_pr",
    "update_issue",
    "push_master",
    "create_tag",
    "publish_release",
    "merge",
}

ISSUE_TRANSITIONS = {
    "discovered": {"analyzed", "rejected", "blocked"},
    "analyzed": {"planned", "rejected", "blocked"},
    "planned": {"implementing", "blocked"},
    "implementing": {"local_verified", "planned", "blocked"},
    "local_verified": {"pr_open", "implementing", "blocked"},
    "pr_open": {"ci_verified", "implementing", "blocked"},
    "ci_verified": {"reported", "implementing", "blocked"},
    "reported": {"done", "blocked"},
    "blocked": {"analyzed", "planned", "implementing", "rejected"},
    "rejected": set(),
    "done": set(),
}

RELEASE_TRANSITIONS = {
    "merged": {"versioned", "blocked"},
    "versioned": {"tagged", "merged", "blocked"},
    "tagged": {"building", "versioned", "blocked"},
    "building": {"published", "versioned", "blocked"},
    "published": {"asset_verified", "blocked"},
    "asset_verified": {"reported", "blocked"},
    "reported": {"done", "blocked"},
    "blocked": {"merged", "versioned", "building"},
    "done": set(),
}

CHECK_KINDS = {
    "local_tests",
    "lint",
    "diff_check",
    "skill_validation",
    "ci",
    "version_consistency",
    "asset_inventory",
    "checksum",
    "manifest",
    "binary_smoke",
}

REMOTE_KINDS = {
    "issue",
    "pull_request",
    "ci_run",
    "tag",
    "release",
}

REPORT_KINDS = {"issue_update", "release_update"}

SECRET_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|authorization|cookie|password|secret|token)"
    r"\s*[:=]\s*\S+"
)


class LoopError(Exception):
    def __init__(self, code: str, message: str, **details: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "revision": 0,
        "runs": {},
        "events": [],
    }


def emit(event: str, **data: Any) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event": event,
        **data,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def reject_secret(value: str, field: str) -> None:
    if SECRET_ASSIGNMENT.search(value):
        raise LoopError(
            "secret_rejected",
            f"{field} appears to contain a secret assignment",
            field=field,
        )


def safe_url(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError as exc:
        raise LoopError("invalid_url", "URL could not be parsed") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LoopError("invalid_url", "URL must use http or https")
    if parsed.username or parsed.password:
        raise LoopError("secret_rejected", "URL must not contain credentials")
    sensitive = ("key", "token", "secret", "password", "authorization")
    for key, _value in urllib.parse.parse_qsl(
        parsed.query,
        keep_blank_values=True,
    ):
        if any(marker in key.lower() for marker in sensitive):
            raise LoopError(
                "secret_rejected",
                "URL must not contain secret-bearing query parameters",
            )
    return value


def validate_state(state: dict[str, Any]) -> None:
    if state.get("schema_version") != SCHEMA_VERSION:
        raise LoopError(
            "schema_mismatch",
            "state schema version is unsupported",
            expected=SCHEMA_VERSION,
            actual=state.get("schema_version"),
        )
    if state.get("protocol_version") != PROTOCOL_VERSION:
        raise LoopError(
            "protocol_mismatch",
            "state protocol version is unsupported",
            expected=PROTOCOL_VERSION,
            actual=state.get("protocol_version"),
        )
    if not isinstance(state.get("revision"), int):
        raise LoopError("invalid_state", "state revision must be an integer")
    if not isinstance(state.get("runs"), dict):
        raise LoopError("invalid_state", "runs must be an object")
    if not isinstance(state.get("events"), list):
        raise LoopError("invalid_state", "events must be an array")
    for run_id, run in state["runs"].items():
        if run.get("run_id") != run_id:
            raise LoopError(
                "invalid_state",
                "run key does not match run_id",
                run_id=run_id,
            )
        operation = run.get("operation")
        transitions = transitions_for(operation)
        if run.get("state") not in transitions:
            raise LoopError(
                "invalid_state",
                "run contains an unknown state",
                run_id=run_id,
                state=run.get("state"),
            )
        if not isinstance(run.get("revision"), int):
            raise LoopError(
                "invalid_state",
                "run revision must be an integer",
                run_id=run_id,
            )


def transitions_for(operation: str) -> dict[str, set[str]]:
    if operation == "issue":
        return ISSUE_TRANSITIONS
    if operation == "release":
        return RELEASE_TRANSITIONS
    raise LoopError("invalid_operation", f"unsupported operation: {operation}")


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            raise LoopError(
                "state_missing",
                f"state file does not exist: {self.path}",
                recovery="run init",
            )
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LoopError(
                "state_unreadable",
                f"state file is not valid JSON: {type(exc).__name__}",
            ) from exc
        validate_state(state)
        return state

    @contextmanager
    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
        descriptor = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(
                    descriptor,
                    json.dumps(
                        {"pid": os.getpid(), "created_at": now()}
                    ).encode("utf-8"),
                )
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if age > STALE_LOCK_SECONDS:
                    try:
                        self.lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise LoopError(
                        "state_locked",
                        "timed out waiting for state lock",
                    )
                time.sleep(0.05)
        try:
            yield
        finally:
            os.close(descriptor)
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass

    def write(self, state: dict[str, Any]) -> None:
        validate_state(state)
        staged = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.staging"
        )
        serialized = json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        try:
            with staged.open("w", encoding="utf-8", newline="\n") as output:
                output.write(serialized)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(staged, self.path)
            try:
                directory = os.open(self.path.parent, os.O_RDONLY)
            except OSError:
                directory = None
            if directory is not None:
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            if staged.exists():
                staged.unlink()

    def initialize(self) -> bool:
        with self.lock():
            if self.path.exists():
                self.load()
                return False
            self.write(empty_state())
            return True

    def mutate(
        self,
        run_id: str,
        expected_revision: int,
        event_type: str,
        mutation: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        with self.lock():
            state = self.load()
            run = state["runs"].get(run_id)
            if not run:
                raise LoopError(
                    "run_not_found",
                    f"run does not exist: {run_id}",
                )
            actual = run["revision"]
            if actual != expected_revision:
                raise LoopError(
                    "revision_mismatch",
                    "run revision changed; read and reconcile before retrying",
                    expected=expected_revision,
                    actual=actual,
                    recovery=f"run show {run_id}",
                )
            details = mutation(run)
            run["revision"] += 1
            run["updated_at"] = now()
            state["revision"] += 1
            state["events"].append(
                {
                    "event_id": state["revision"],
                    "run_id": run_id,
                    "type": event_type,
                    "at": run["updated_at"],
                    "run_revision": run["revision"],
                    "details": details or {},
                }
            )
            self.write(state)
            return run, details


def get_run(store: StateStore, run_id: str) -> dict[str, Any]:
    state = store.load()
    try:
        return state["runs"][run_id]
    except KeyError as exc:
        raise LoopError("run_not_found", f"run does not exist: {run_id}") from exc


def run_id_for(args: argparse.Namespace) -> str:
    if args.operation == "issue":
        if args.issue is None or not args.base_sha:
            raise LoopError(
                "invalid_request",
                "issue runs require --issue and --base-sha",
            )
        return f"{args.repository}:issue:{args.issue}:{args.base_sha}"
    if not args.version or not args.commit:
        raise LoopError(
            "invalid_request",
            "release runs require --version and --commit",
        )
    return f"{args.repository}:release:{args.version}:{args.commit}"


def command_init(store: StateStore, _args: argparse.Namespace) -> None:
    created = store.initialize()
    state = store.load()
    emit(
        "state_initialized" if created else "state_exists",
        path=str(store.path),
        revision=state["revision"],
        protocol_version=state["protocol_version"],
    )


def command_validate(store: StateStore, _args: argparse.Namespace) -> None:
    state = store.load()
    emit(
        "state_valid",
        path=str(store.path),
        revision=state["revision"],
        run_count=len(state["runs"]),
        event_count=len(state["events"]),
        protocol_version=state["protocol_version"],
    )


def command_run_start(store: StateStore, args: argparse.Namespace) -> None:
    run_id = run_id_for(args)
    with store.lock():
        state = store.load()
        if run_id in state["runs"]:
            run = state["runs"][run_id]
            emit(
                "run_exists",
                run_id=run_id,
                state=run["state"],
                revision=run["revision"],
            )
            return
        authorization = {
            key: key in set(args.allow or [])
            for key in sorted(AUTHORIZATION_KEYS)
        }
        if authorization["merge"]:
            raise LoopError(
                "unsafe_authorization",
                "merge cannot be enabled by the engineering controller",
            )
        timestamp = now()
        subject = (
            {
                "issue": args.issue,
                "base_sha": args.base_sha,
                "head_sha": "",
            }
            if args.operation == "issue"
            else {
                "version": args.version,
                "commit": args.commit,
            }
        )
        run = {
            "run_id": run_id,
            "operation": args.operation,
            "repository": args.repository,
            "state": "discovered" if args.operation == "issue" else "merged",
            "revision": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
            "subject": subject,
            "authorization": authorization,
            "checks": {},
            "remote": {},
            "reports": {},
            "blockers": [],
        }
        state["runs"][run_id] = run
        state["revision"] += 1
        state["events"].append(
            {
                "event_id": state["revision"],
                "run_id": run_id,
                "type": "run_started",
                "at": timestamp,
                "run_revision": 1,
                "details": {"operation": args.operation},
            }
        )
        store.write(state)
    emit(
        "run_started",
        run_id=run_id,
        state=run["state"],
        revision=run["revision"],
        protocol_version=PROTOCOL_VERSION,
    )


def command_run_show(store: StateStore, args: argparse.Namespace) -> None:
    run = get_run(store, args.run_id)
    emit(
        "run",
        run=run,
        next_allowed_states=sorted(
            transitions_for(run["operation"])[run["state"]]
        ),
    )


def command_run_list(store: StateStore, args: argparse.Namespace) -> None:
    runs = list(store.load()["runs"].values())
    if args.operation:
        runs = [run for run in runs if run["operation"] == args.operation]
    if args.run_state:
        runs = [run for run in runs if run["state"] == args.run_state]
    runs.sort(key=lambda item: (item["updated_at"], item["run_id"]))
    emit(
        "runs",
        count=len(runs),
        runs=[
            {
                "run_id": run["run_id"],
                "operation": run["operation"],
                "state": run["state"],
                "revision": run["revision"],
                "updated_at": run["updated_at"],
            }
            for run in runs
        ],
    )


def check_passed(run: dict[str, Any], name: str) -> bool:
    return run["checks"].get(name, {}).get("status") == "passed"


def require_transition_evidence(run: dict[str, Any], target: str) -> None:
    if target == "local_verified":
        required = ("local_tests", "lint", "diff_check")
        missing = [name for name in required if not check_passed(run, name)]
        if missing:
            raise LoopError(
                "evidence_missing",
                "local verification evidence is incomplete",
                missing=missing,
            )
    elif target == "pr_open":
        pull_request = run["remote"].get("pull_request", {})
        if not pull_request.get("url") or not pull_request.get("head_sha"):
            raise LoopError(
                "evidence_missing",
                "pull request URL and head SHA are required",
            )
    elif target == "ci_verified" and not check_passed(run, "ci"):
        raise LoopError("evidence_missing", "passing CI evidence is required")
    elif target == "versioned":
        required = ("version_consistency", "local_tests", "lint")
        missing = [name for name in required if not check_passed(run, name)]
        if missing:
            raise LoopError(
                "evidence_missing",
                "release version evidence is incomplete",
                missing=missing,
            )
    elif target == "tagged":
        tag = run["remote"].get("tag", {})
        if tag.get("state") != "exists" or not tag.get("head_sha"):
            raise LoopError(
                "evidence_missing",
                "observed tag and target SHA are required",
            )
    elif target == "published":
        release = run["remote"].get("release", {})
        if release.get("state") != "published" or not release.get("url"):
            raise LoopError(
                "evidence_missing",
                "published Release URL is required",
            )
    elif target == "asset_verified":
        required = ("asset_inventory", "checksum", "manifest", "binary_smoke")
        missing = [name for name in required if not check_passed(run, name)]
        if missing:
            raise LoopError(
                "evidence_missing",
                "Release asset evidence is incomplete",
                missing=missing,
            )
    elif target == "reported":
        report_kind = (
            "issue_update"
            if run["operation"] == "issue"
            else "release_update"
        )
        report = run["reports"].get(report_kind, {})
        if report.get("status") != "posted" or not report.get("marker"):
            raise LoopError(
                "evidence_missing",
                f"{report_kind} marker is required",
            )
    elif target == "done":
        unresolved = [
            item for item in run["blockers"] if item["status"] == "open"
        ]
        if unresolved:
            raise LoopError(
                "blockers_open",
                "run has unresolved blockers",
                blockers=[item["blocker_id"] for item in unresolved],
            )


def command_transition(store: StateStore, args: argparse.Namespace) -> None:
    def mutation(run: dict[str, Any]) -> dict[str, Any]:
        previous = run["state"]
        allowed = transitions_for(run["operation"])[previous]
        if args.target not in allowed:
            raise LoopError(
                "invalid_transition",
                f"cannot transition from {previous} to {args.target}",
                allowed=sorted(allowed),
            )
        require_transition_evidence(run, args.target)
        run["state"] = args.target
        return {"from": previous, "to": args.target}

    run, details = store.mutate(
        args.run_id,
        args.expect_revision,
        "transition",
        mutation,
    )
    emit(
        "transitioned",
        run_id=args.run_id,
        previous_state=details["from"],
        state=run["state"],
        revision=run["revision"],
        next_allowed_states=sorted(
            transitions_for(run["operation"])[run["state"]]
        ),
    )


def command_evidence_add(store: StateStore, args: argparse.Namespace) -> None:
    for field in ("summary", "command_text", "marker"):
        reject_secret(getattr(args, field) or "", field)
    url = safe_url(args.url) if args.url else ""

    def mutation(run: dict[str, Any]) -> dict[str, Any]:
        record = {
            "status": args.status,
            "summary": args.summary or "",
            "command": args.command_text or "",
            "url": url,
            "marker": args.marker or "",
            "recorded_at": now(),
        }
        if args.kind in CHECK_KINDS:
            run["checks"][args.kind] = record
        elif args.kind in REPORT_KINDS:
            run["reports"][args.kind] = record
        else:
            raise LoopError(
                "invalid_evidence_kind",
                f"unsupported evidence kind: {args.kind}",
            )
        return {"kind": args.kind, "status": args.status}

    run, _details = store.mutate(
        args.run_id,
        args.expect_revision,
        "evidence_recorded",
        mutation,
    )
    emit(
        "evidence_recorded",
        run_id=args.run_id,
        kind=args.kind,
        status=args.status,
        revision=run["revision"],
    )


def command_remote_record(store: StateStore, args: argparse.Namespace) -> None:
    if args.kind not in REMOTE_KINDS:
        raise LoopError(
            "invalid_remote_kind",
            f"unsupported remote kind: {args.kind}",
        )
    url = safe_url(args.url) if args.url else ""

    def mutation(run: dict[str, Any]) -> dict[str, Any]:
        record = {
            "url": url,
            "number": args.number,
            "state": args.remote_state or "",
            "head_sha": args.head_sha or "",
            "recorded_at": now(),
        }
        run["remote"][args.kind] = record
        if args.kind == "pull_request" and args.head_sha:
            run["subject"]["head_sha"] = args.head_sha
        return {"kind": args.kind, "state": args.remote_state or ""}

    run, _details = store.mutate(
        args.run_id,
        args.expect_revision,
        "remote_recorded",
        mutation,
    )
    emit(
        "remote_recorded",
        run_id=args.run_id,
        kind=args.kind,
        revision=run["revision"],
    )


def command_blocker_add(store: StateStore, args: argparse.Namespace) -> None:
    for field in ("capability", "reason", "resume_when", "safe_fallback"):
        reject_secret(getattr(args, field), field)

    def mutation(run: dict[str, Any]) -> dict[str, Any]:
        blocker_id = len(run["blockers"]) + 1
        blocker = {
            "blocker_id": blocker_id,
            "capability": args.capability,
            "reason": args.reason,
            "resume_when": args.resume_when,
            "safe_fallback": args.safe_fallback,
            "status": "open",
            "created_at": now(),
            "resolved_at": "",
        }
        run["blockers"].append(blocker)
        return {"blocker_id": blocker_id, "capability": args.capability}

    run, details = store.mutate(
        args.run_id,
        args.expect_revision,
        "blocker_added",
        mutation,
    )
    emit(
        "blocker_added",
        run_id=args.run_id,
        blocker_id=details["blocker_id"],
        revision=run["revision"],
    )


def command_blocker_resolve(store: StateStore, args: argparse.Namespace) -> None:
    def mutation(run: dict[str, Any]) -> dict[str, Any]:
        blocker = next(
            (
                item
                for item in run["blockers"]
                if item["blocker_id"] == args.blocker_id
            ),
            None,
        )
        if not blocker:
            raise LoopError(
                "blocker_not_found",
                f"blocker does not exist: {args.blocker_id}",
            )
        blocker["status"] = "resolved"
        blocker["resolved_at"] = now()
        return {"blocker_id": args.blocker_id}

    run, _details = store.mutate(
        args.run_id,
        args.expect_revision,
        "blocker_resolved",
        mutation,
    )
    emit(
        "blocker_resolved",
        run_id=args.run_id,
        blocker_id=args.blocker_id,
        revision=run["revision"],
    )


def command_reconcile(store: StateStore, args: argparse.Namespace) -> None:
    run = get_run(store, args.run_id)
    observations = []
    if run["state"] in {"pr_open", "ci_verified", "reported", "done"}:
        if "pull_request" not in run["remote"]:
            observations.append("pull_request_missing")
    if run["state"] in {"ci_verified", "reported", "done"}:
        if not check_passed(run, "ci"):
            observations.append("ci_not_verified")
    if run["state"] in {"published", "asset_verified", "reported", "done"}:
        if run["operation"] == "release" and "release" not in run["remote"]:
            observations.append("release_missing")
    emit(
        "reconciled",
        run_id=args.run_id,
        state=run["state"],
        revision=run["revision"],
        observations=observations,
        consistent=not observations,
        next_allowed_states=sorted(
            transitions_for(run["operation"])[run["state"]]
        ),
    )


def command_result(store: StateStore, args: argparse.Namespace) -> None:
    run = get_run(store, args.run_id)
    emit(
        "result",
        protocol_version=PROTOCOL_VERSION,
        run_id=run["run_id"],
        operation=run["operation"],
        final_state=run["state"],
        revision=run["revision"],
        checks=run["checks"],
        remote=run["remote"],
        blockers=run["blockers"],
        evidence=run["reports"],
        authorization=run["authorization"],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init")
    subparsers.add_parser("validate")

    run = subparsers.add_parser("run")
    run_commands = run.add_subparsers(dest="run_command", required=True)
    start = run_commands.add_parser("start")
    start.add_argument("--operation", choices=("issue", "release"), required=True)
    start.add_argument("--repository", required=True)
    start.add_argument("--issue", type=int)
    start.add_argument("--base-sha", default="")
    start.add_argument("--version", default="")
    start.add_argument("--commit", default="")
    start.add_argument(
        "--allow",
        action="append",
        choices=sorted(AUTHORIZATION_KEYS),
        default=[],
    )
    show = run_commands.add_parser("show")
    show.add_argument("run_id")
    listing = run_commands.add_parser("list")
    listing.add_argument("--operation", choices=("issue", "release"))
    listing.add_argument("--state", dest="run_state")

    transition = subparsers.add_parser("transition")
    transition.add_argument("run_id")
    transition.add_argument("target")
    transition.add_argument("--expect-revision", type=int, required=True)

    evidence = subparsers.add_parser("evidence")
    evidence_commands = evidence.add_subparsers(
        dest="evidence_command",
        required=True,
    )
    evidence_add = evidence_commands.add_parser("add")
    evidence_add.add_argument("run_id")
    evidence_add.add_argument("--kind", required=True)
    evidence_add.add_argument(
        "--status",
        choices=("passed", "failed", "pending", "posted", "skipped"),
        required=True,
    )
    evidence_add.add_argument("--summary", default="")
    evidence_add.add_argument("--command", dest="command_text", default="")
    evidence_add.add_argument("--url", default="")
    evidence_add.add_argument("--marker", default="")
    evidence_add.add_argument("--expect-revision", type=int, required=True)

    remote = subparsers.add_parser("remote")
    remote_commands = remote.add_subparsers(
        dest="remote_command",
        required=True,
    )
    remote_record = remote_commands.add_parser("record")
    remote_record.add_argument("run_id")
    remote_record.add_argument("--kind", choices=sorted(REMOTE_KINDS), required=True)
    remote_record.add_argument("--url", default="")
    remote_record.add_argument("--number", type=int)
    remote_record.add_argument("--state", dest="remote_state", default="")
    remote_record.add_argument("--head-sha", default="")
    remote_record.add_argument("--expect-revision", type=int, required=True)

    blocker = subparsers.add_parser("blocker")
    blocker_commands = blocker.add_subparsers(
        dest="blocker_command",
        required=True,
    )
    blocker_add = blocker_commands.add_parser("add")
    blocker_add.add_argument("run_id")
    blocker_add.add_argument("--capability", required=True)
    blocker_add.add_argument("--reason", required=True)
    blocker_add.add_argument("--resume-when", required=True)
    blocker_add.add_argument("--safe-fallback", required=True)
    blocker_add.add_argument("--expect-revision", type=int, required=True)
    blocker_resolve = blocker_commands.add_parser("resolve")
    blocker_resolve.add_argument("run_id")
    blocker_resolve.add_argument("--blocker-id", type=int, required=True)
    blocker_resolve.add_argument("--expect-revision", type=int, required=True)

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("run_id")
    result = subparsers.add_parser("result")
    result.add_argument("run_id")
    return parser


def dispatch(store: StateStore, args: argparse.Namespace) -> None:
    if args.command == "init":
        command_init(store, args)
    elif args.command == "validate":
        command_validate(store, args)
    elif args.command == "run" and args.run_command == "start":
        command_run_start(store, args)
    elif args.command == "run" and args.run_command == "show":
        command_run_show(store, args)
    elif args.command == "run" and args.run_command == "list":
        command_run_list(store, args)
    elif args.command == "transition":
        command_transition(store, args)
    elif args.command == "evidence":
        command_evidence_add(store, args)
    elif args.command == "remote":
        command_remote_record(store, args)
    elif args.command == "blocker" and args.blocker_command == "add":
        command_blocker_add(store, args)
    elif args.command == "blocker" and args.blocker_command == "resolve":
        command_blocker_resolve(store, args)
    elif args.command == "reconcile":
        command_reconcile(store, args)
    elif args.command == "result":
        command_result(store, args)
    else:
        raise LoopError("invalid_command", "command is not implemented")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    store = StateStore(args.state_file.expanduser().resolve())
    try:
        dispatch(store, args)
    except LoopError as exc:
        emit("error", code=exc.code, message=exc.message, **exc.details)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
