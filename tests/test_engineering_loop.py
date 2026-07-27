"""Tests for the repository-local engineering loop controller."""

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path("docs/automation/loopctl.py").resolve()
PROTOCOL = Path("docs/automation/engineering-loop.md").resolve()


def invoke(state_file, *arguments, check=True):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--state-file",
            str(state_file),
            *arguments,
        ],
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if check:
        assert result.returncode == 0, payload
    return result, payload


def start_issue(state_file):
    invoke(state_file, "init")
    _result, payload = invoke(
        state_file,
        "run",
        "start",
        "--operation",
        "issue",
        "--repository",
        "owner/repository",
        "--issue",
        "3",
        "--base-sha",
        "abc1234",
        "--allow",
        "code_changes",
        "--allow",
        "create_pr",
    )
    return payload["run_id"]


def transition(state_file, run_id, target, revision):
    return invoke(
        state_file,
        "transition",
        run_id,
        target,
        "--expect-revision",
        str(revision),
    )[1]


def evidence(
    state_file,
    run_id,
    kind,
    status,
    revision,
    *extra,
):
    return invoke(
        state_file,
        "evidence",
        "add",
        run_id,
        "--kind",
        kind,
        "--status",
        status,
        "--expect-revision",
        str(revision),
        *extra,
    )[1]


def test_protocol_requires_cli_control():
    content = PROTOCOL.read_text(encoding="utf-8")

    assert "MUST NOT edit `state.json` directly" in content
    assert "loopctl.py" in content
    assert "state_machines:" in content
    assert "idempotency:" in content


def test_init_validate_and_idempotent_start(tmp_path):
    state_file = tmp_path / "state.json"

    _result, initialized = invoke(state_file, "init")
    _result, validated = invoke(state_file, "validate")
    run_id = start_issue(state_file)
    _result, existing = invoke(
        state_file,
        "run",
        "start",
        "--operation",
        "issue",
        "--repository",
        "owner/repository",
        "--issue",
        "3",
        "--base-sha",
        "abc1234",
    )

    assert initialized["event"] == "state_initialized"
    assert validated["event"] == "state_valid"
    assert existing["event"] == "run_exists"
    assert existing["run_id"] == run_id
    assert existing["revision"] == 1


def test_issue_state_machine_enforces_evidence(tmp_path):
    state_file = tmp_path / "state.json"
    run_id = start_issue(state_file)

    assert transition(state_file, run_id, "analyzed", 1)["revision"] == 2
    assert transition(state_file, run_id, "planned", 2)["revision"] == 3
    assert transition(state_file, run_id, "implementing", 3)["revision"] == 4

    result, missing = invoke(
        state_file,
        "transition",
        run_id,
        "local_verified",
        "--expect-revision",
        "4",
        check=False,
    )
    assert result.returncode == 2
    assert missing["code"] == "evidence_missing"
    assert missing["missing"] == ["local_tests", "lint", "diff_check"]

    evidence(
        state_file,
        run_id,
        "local_tests",
        "passed",
        4,
        "--summary",
        "78 passed",
    )
    evidence(state_file, run_id, "lint", "passed", 5)
    evidence(state_file, run_id, "diff_check", "passed", 6)
    assert transition(state_file, run_id, "local_verified", 7)["revision"] == 8

    invoke(
        state_file,
        "remote",
        "record",
        run_id,
        "--kind",
        "pull_request",
        "--url",
        "https://github.com/owner/repository/pull/4",
        "--number",
        "4",
        "--state",
        "open",
        "--head-sha",
        "def5678",
        "--expect-revision",
        "8",
    )
    transition(state_file, run_id, "pr_open", 9)
    evidence(
        state_file,
        run_id,
        "ci",
        "passed",
        10,
        "--url",
        "https://github.com/owner/repository/actions/runs/1",
    )
    transition(state_file, run_id, "ci_verified", 11)
    evidence(
        state_file,
        run_id,
        "issue_update",
        "posted",
        12,
        "--marker",
        "issue-engineering:3:def5678",
        "--url",
        "https://github.com/owner/repository/issues/3#comment",
    )
    transition(state_file, run_id, "reported", 13)
    transition(state_file, run_id, "done", 14)

    _result, final = invoke(state_file, "result", run_id)
    assert final["final_state"] == "done"
    assert final["revision"] == 15
    assert final["remote"]["pull_request"]["number"] == 4


def test_revision_conflict_does_not_overwrite_state(tmp_path):
    state_file = tmp_path / "state.json"
    run_id = start_issue(state_file)
    transition(state_file, run_id, "analyzed", 1)

    result, conflict = invoke(
        state_file,
        "transition",
        run_id,
        "planned",
        "--expect-revision",
        "1",
        check=False,
    )
    _result, shown = invoke(state_file, "run", "show", run_id)

    assert result.returncode == 2
    assert conflict["code"] == "revision_mismatch"
    assert conflict["actual"] == 2
    assert shown["run"]["state"] == "analyzed"
    assert shown["run"]["revision"] == 2


def test_open_blocker_prevents_completion(tmp_path):
    state_file = tmp_path / "state.json"
    run_id = start_issue(state_file)

    invoke(
        state_file,
        "blocker",
        "add",
        run_id,
        "--capability",
        "web_search",
        "--reason",
        "No search capability",
        "--resume-when",
        "Search is available",
        "--safe-fallback",
        "Record an explicit skipped result",
        "--expect-revision",
        "1",
    )
    _result, shown = invoke(state_file, "run", "show", run_id)

    assert shown["run"]["blockers"][0]["status"] == "open"
    assert shown["run"]["blockers"][0]["safe_fallback"]


def test_release_state_machine_requires_asset_evidence(tmp_path):
    state_file = tmp_path / "state.json"
    invoke(state_file, "init")
    _result, started = invoke(
        state_file,
        "run",
        "start",
        "--operation",
        "release",
        "--repository",
        "owner/repository",
        "--version",
        "0.3.0",
        "--commit",
        "abcdef1",
        "--allow",
        "create_tag",
        "--allow",
        "publish_release",
    )
    run_id = started["run_id"]

    result, failure = invoke(
        state_file,
        "transition",
        run_id,
        "versioned",
        "--expect-revision",
        "1",
        check=False,
    )

    assert result.returncode == 2
    assert failure["code"] == "evidence_missing"
    assert failure["missing"] == [
        "version_consistency",
        "local_tests",
        "lint",
    ]


def test_secret_bearing_url_is_rejected(tmp_path):
    state_file = tmp_path / "state.json"
    run_id = start_issue(state_file)

    result, payload = invoke(
        state_file,
        "remote",
        "record",
        run_id,
        "--kind",
        "issue",
        "--url",
        "https://user:password@example.com/issues/3",
        "--expect-revision",
        "1",
        check=False,
    )

    assert result.returncode == 2
    assert payload["code"] == "secret_rejected"


def test_compare_and_swap_allows_only_one_concurrent_writer(tmp_path):
    state_file = tmp_path / "state.json"
    run_id = start_issue(state_file)
    base_command = [
        sys.executable,
        str(SCRIPT),
        "--state-file",
        str(state_file),
        "evidence",
        "add",
        run_id,
        "--status",
        "passed",
        "--expect-revision",
        "1",
    ]
    first = subprocess.Popen(
        [*base_command, "--kind", "local_tests"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second = subprocess.Popen(
        [*base_command, "--kind", "lint"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first_output, _first_error = first.communicate()
    second_output, _second_error = second.communicate()
    payloads = [json.loads(first_output), json.loads(second_output)]

    assert sorted([first.returncode, second.returncode]) == [0, 2]
    assert {item["event"] for item in payloads} == {
        "error",
        "evidence_recorded",
    }
    _result, validated = invoke(state_file, "validate")
    assert validated["event"] == "state_valid"
