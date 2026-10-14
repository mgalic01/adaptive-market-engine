"""The v31-run workflow (Task 10b): its triggers, permissions, job graph and artifact layout.

The registered experiment runs once, on GitHub's machines, through this workflow, so its
safety properties are tested as structure: the tests parse the YAML and never call GitHub.
Three kinds of test:

- structure: triggers, permissions, checkouts, concurrency, pins, matrices, artifacts;
- control flow: ``jobs_that_run`` follows each job's ``needs`` and ``if`` for a dispatch
  mode (and for a failing job), the way GitHub decides which jobs run;
- steps run for real, in bash and offline: the registration check, the 2025 guard, the
  picks check and the plan step (on a registration of the owner's plan with all 216
  cells, its files synthetic).

A driver call is also parsed with the driver's own argument parser, so a misspelled or
missing flag fails here and not hours into a run.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v31_driver  # noqa: E402
import v31_smoke  # noqa: E402
from test_v31_registration import MODULES  # noqa: E402

from crypto_grid_bot.combined.driver.owner_plan import OWNER_PLAN  # noqa: E402
from crypto_grid_bot.combined.driver.registration import (  # noqa: E402
    V3_ARMS,
    adapter_pins,
    load_prepare_config,
    load_registration,
)

WORKFLOW = ROOT / ".github/workflows/v31-run.yml"
QUALITY = ROOT / ".github/workflows/quality.yml"

JOBS = (
    "smoke",
    "plan",
    "prepare",
    "picks",
    "run-main",
    "run-v3",
    "aggregate",
    "status",
    "timing",
)
DATA_JOBS = JOBS  # each fetches, downloads or makes data (the plan job a rehearsal's world)
GRAPH = ("plan", "prepare", "picks", "run-main", "run-v3", "aggregate", "status")
MATRIX_JOBS = ("run-main", "run-v3")
GATED_JOBS = ("picks", *MATRIX_JOBS, "aggregate")  # each runs the driver on the registration
# Every action pinned to a full commit SHA, the tag in a trailing comment (Ruling F9); the
# same major versions as before (checkout v4, setup-python v5, the artifact actions v4).
PINS = {
    "actions/checkout": ("11d5960a326750d5838078e36cf38b85af677262", "v4.4.0"),
    "actions/setup-python": ("a26af69be951a213d495a4c3e4e4022e16d87065", "v5.6.0"),
    "actions/upload-artifact": ("ea165f8d65b6e75b540449e92b4886f43607fa02", "v4.6.2"),
    "actions/download-artifact": ("d3f86a106a0bac45b974a628896c90dbdf5c8093", "v4.3.0"),
}
CHECKOUT = "actions/checkout@" + PINS["actions/checkout"][0]
SETUP_PYTHON = "actions/setup-python@" + PINS["actions/setup-python"][0]
STEP_TIMEOUT = 335  # minutes: the long steps end inside the 360-minute job limit (Ruling F2)
# The summary's and the status's artifact names: a rehearsal's are its own (Ruling C2).
SUMMARY_NAME = "${{ inputs.mode == 'rehearsal' && 'v31-rehearsal-summary' || 'v31-summary' }}"
STATUS_NAME = "${{ inputs.mode == 'rehearsal' && 'v31-rehearsal-status' || 'v31-status' }}"
ATTEMPT_ID = "${{ github.run_id }}-attempt-${{ github.run_attempt }}"
GUARD_PATTERNS = ("-202[5-9]-", "-20[3-9][0-9]-")
GITHUB_EXPRESSION = re.compile(r"\$\{\{.*?\}\}")


# --- reading the workflow ---------------------------------------------------------------


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _workflow() -> dict[str, Any]:
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    return yaml.safe_load(_text())


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    return workflow[True] if True in workflow else workflow["on"]


def _jobs() -> dict[str, dict[str, Any]]:
    return _workflow()["jobs"]


def _steps(job: str) -> list[dict[str, Any]]:
    return _jobs()[job]["steps"]


def _action(step: dict[str, Any]) -> str:
    return step.get("uses", "")


def _scripts(job: str) -> list[str]:
    return [step["run"] for step in _steps(job) if "run" in step]


def _find_steps(job: str, action: str) -> list[dict[str, Any]]:
    return [step for step in _steps(job) if _action(step).startswith(action)]


def _downloads(job: str) -> list[dict[str, Any]]:
    return _find_steps(job, "actions/download-artifact@")


def _uploads(job: str) -> list[dict[str, Any]]:
    return _find_steps(job, "actions/upload-artifact@")


def _download(job: str, name: str) -> dict[str, Any]:
    (step,) = [
        s
        for s in _downloads(job)
        if s["with"].get("name") == name or s["with"].get("pattern") == name
    ]
    return step["with"]


def _upload(job: str, name: str) -> dict[str, Any]:
    (step,) = [s for s in _uploads(job) if s["with"]["name"] == name]
    return step["with"]


def _guard_steps(job: str) -> list[int]:
    """The indexes of the steps that hold both patterns of the 2025 guard."""
    return [
        index
        for index, step in enumerate(_steps(job))
        if all(pattern in step.get("run", "") for pattern in GUARD_PATTERNS)
    ]


def _driver_calls(job: str) -> list[tuple[str, list[str]]]:
    """Each ``scripts/v31_driver.py`` call of the job: its subcommand and its arguments (the
    redirection cut off, each ``${{ }}`` expression replaced by ``X``)."""
    calls = []
    for script in _scripts(job):
        joined = re.sub(r"\\\n\s*", " ", script)
        for line in joined.splitlines():
            if "scripts/v31_driver.py" not in line:
                continue
            rest = GITHUB_EXPRESSION.sub("X", line.split("scripts/v31_driver.py", 1)[1])
            tokens = shlex.split(rest)
            for index, token in enumerate(tokens):
                if token[0] in "<>|":
                    tokens = tokens[:index]
                    break
            calls.append((tokens[0], tokens))
    return calls


def _option(tokens: list[str], option: str) -> str:
    return tokens[tokens.index(option) + 1]


# --- which jobs run ---------------------------------------------------------------------


def _needs(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def _condition(job: dict[str, Any]) -> str | None:
    if "if" not in job:
        return None
    text = str(job["if"]).strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    return text


def _truth(
    expression: str, mode: str, results: dict[str, str], outcomes: dict[str, str] | None = None
) -> bool:
    """A job's or step's ``if`` for a dispatch ``mode``, its needed jobs' ``results`` and the
    ``outcomes`` of earlier steps. Only what the workflow uses is understood:
    ``inputs.mode``, ``needs.<job>.result``, ``steps.<id>.outcome``, ``always()``,
    ``!cancelled()``, string literals, ``==``, ``!=``, ``!``, ``&&``, ``||`` and parentheses; a
    job that is not one of this job's needs is not in ``results`` (GitHub offers a job its
    needs alone)."""
    python = re.sub(r"needs\.([A-Za-z0-9_-]+)\.result", r"RESULTS['\1']", expression)
    python = re.sub(r"steps\.([A-Za-z0-9_-]+)\.outcome", r"OUTCOMES['\1']", python)
    python = python.replace("inputs.mode", "MODE").replace("!cancelled()", "True")
    python = python.replace("always()", "True")
    python = python.replace("&&", " and ").replace("||", " or ")
    python = re.sub(r"!(?!=)", " not ", python)
    assert not re.search(r"[A-Za-z_]\(", python), f"an expression this test cannot read: {python}"
    names = {"MODE": mode, "RESULTS": results, "OUTCOMES": outcomes or {}}
    return bool(eval(python, {"__builtins__": {}}, names))


def jobs_that_run(mode: str, failing: Iterable[str] = ()) -> dict[str, str]:
    """Each job's result for a dispatch of ``mode``: ``success``, ``failure`` (named in
    ``failing``) or ``skipped``.

    GitHub skips a job whose needed job failed or was skipped unless its ``if`` calls a
    status function (here ``!cancelled()`` or ``always()``), and an ``if`` without one also
    requires every needed job to have succeeded."""
    jobs = _jobs()
    results: dict[str, str] = {}
    pending = list(jobs)
    while pending:
        name = next(job for job in pending if all(n in results for n in _needs(jobs[job])))
        pending.remove(name)
        needs = {need: results[need] for need in _needs(jobs[name])}
        condition = _condition(jobs[name])
        needs_succeeded = all(result == "success" for result in needs.values())
        if condition is None:
            runs = needs_succeeded
        else:
            status_aware = any(f in str(jobs[name]["if"]) for f in ("cancelled()", "always()"))
            runs = _truth(condition, mode, needs) and (status_aware or needs_succeeded)
        results[name] = ("failure" if name in set(failing) else "success") if runs else "skipped"
    return results


def _ran(mode: str, failing: Iterable[str] = ()) -> set[str]:
    return {name for name, result in jobs_that_run(mode, failing).items() if result != "skipped"}


def steps_that_run(
    job: str,
    failing: Iterable[int] = (),
    mode: str = "registered",
    forced: Mapping[int, str] | None = None,
) -> list[str]:
    """Each step of ``job``'s outcome (``success``, ``failure``, ``cancelled`` or ``skipped``)
    when the steps at the indexes in ``failing`` fail as they run (the job being otherwise a
    dispatch of ``mode``). A step without an ``if`` runs only while every earlier step
    succeeded; one whose ``if`` calls ``always()`` or ``!cancelled()`` is decided by its
    expression alone. ``forced`` maps a step's index to the outcome it ends with whatever its
    ``if`` says: ``cancelled`` (the run was cancelled while it ran, which fails the steps that
    follow it too) or ``skipped``."""
    forced = forced or {}
    outcomes: dict[str, str] = {}
    result: list[str] = []
    failed = False
    for index, step in enumerate(_steps(job)):
        condition = step.get("if")
        if condition is None:
            runs = not failed
        else:
            text = str(condition).strip()
            if text.startswith("${{") and text.endswith("}}"):
                text = text[3:-2].strip()
            status_aware = "always()" in text or "cancelled()" in text
            runs = _truth(text, mode, {}, outcomes) and (status_aware or not failed)
        if index in forced:
            outcome = forced[index]
        else:
            outcome = ("failure" if index in set(failing) else "success") if runs else "skipped"
        failed = failed or outcome in ("failure", "cancelled")
        result.append(outcome)
        if "id" in step:
            outcomes[step["id"]] = outcome
    return result


# --- running a step for real ------------------------------------------------------------


def _bash() -> str:
    shell = (
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    assert shell and Path(shell).is_file(), "Git Bash (Windows) or bash is required"
    return shell


# A runner's variables for GitHub's API, emptied in every step run here unless the test
# sets them: the dispatch check then refuses before any request, so no step ever reaches
# api.github.com from a test, whatever the machine's own environment holds.
NO_GITHUB_API = {"GITHUB_TOKEN": "", "GITHUB_REPOSITORY": "", "GITHUB_RUN_ID": ""}


def _run_step(
    script: str, cwd: Path, env: dict[str, str], prelude: str = ""
) -> subprocess.CompletedProcess[str]:
    """``script`` as GitHub runs a bash step (``-e -o pipefail``), with ``env`` added
    (and the GitHub API's variables emptied unless ``env`` sets them)."""
    return subprocess.run(
        [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", prelude + script],
        cwd=cwd,
        env={**os.environ, **NO_GITHUB_API, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _step(job: str, step_id: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if s.get("id") == step_id]
    return step


# --- triggers, permissions, checkout, concurrency ---------------------------------------


def test_the_only_trigger_is_workflow_dispatch_with_the_four_inputs() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"mode", "registration_sha256", "code_commit", "rehearsal_cells"}
    assert inputs["mode"]["type"] == "choice"
    assert inputs["mode"]["options"] == [
        "smoke",
        "prepare-only",
        "timing",
        "rehearsal",
        "registered",
    ]
    assert inputs["mode"]["default"] == "smoke"
    for name in ("registration_sha256", "code_commit", "rehearsal_cells"):
        # Each belongs to one or two modes, so none can be required for all.
        assert inputs[name]["type"] == "string" and not inputs[name].get("required"), name
        assert inputs[name]["default"] == "", name


# The jobs that run the dispatch check (Ruling R4-2) read this workflow's runs, and nothing
# more: actions: read beside contents: read. No other job sets its own permissions.
CHECKING_JOBS = ("plan", "aggregate")
CHECKING_PERMISSIONS = {"contents": "read", "actions": "read"}


def test_workflow_has_the_2025_guard_and_no_write_permissions() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        if name in CHECKING_JOBS:
            assert job["permissions"] == CHECKING_PERMISSIONS, name
        else:
            assert "permissions" not in job, f"{name} sets its own permissions"
    assert not re.search(r"\bwrite\b", json.dumps(workflow))
    for name in DATA_JOBS:
        assert _guard_steps(name), f"{name} has no 2025 guard step"


def test_permissions_are_exactly_contents_read_and_no_job_widens_them() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    widened = {
        name: job["permissions"] for name, job in workflow["jobs"].items() if "permissions" in job
    }
    # Only the two checking jobs add one read scope, to list this workflow's runs.
    assert widened == dict.fromkeys(CHECKING_JOBS, CHECKING_PERMISSIONS)
    assert "id-token" not in json.dumps(workflow)


def test_no_step_commits_pushes_or_writes_through_gh() -> None:
    forbidden = re.compile(
        r"\bgit\s+(commit|push|add|tag|config|checkout|reset|clean|merge|rebase|stash)\b"
        r"|\bgh\s|\bcurl\b|\bwget\b|x-access-token"
    )
    for name in JOBS:
        for script in _scripts(name):
            assert not forbidden.search(script), f"{name}: {script}"
    # Reading history is allowed and used (the guard lists tracked files).
    assert any("git ls-files" in script for name in JOBS for script in _scripts(name))


# The checking jobs' first step: the job's start, from which the dispatch check budgets
# its deadline (owner decision v31-d21; Codex P1 on PR #281). No input reaches it.
JOB_START_STEP = {
    "name": "Record the job's start",
    "run": 'echo "V31_JOB_STARTED=$(date +%s)" >> "$GITHUB_ENV"',
}


def _checked_out(name: str) -> list[dict[str, Any]]:
    """The job's steps from its checkout on: a checking job's start record comes first."""
    steps = _steps(name)
    return steps[1:] if name in CHECKING_JOBS else steps


def test_every_job_checks_out_the_full_history_without_credentials() -> None:
    # changed_since(code_pin) needs the code commit's history; credentials stay out of .git.
    for name in JOBS:
        if name in CHECKING_JOBS:
            assert _steps(name)[0] == JOB_START_STEP, name
        first = _checked_out(name)[0]
        assert _action(first) == CHECKOUT, name
        assert first["with"] == {"fetch-depth": 0, "persist-credentials": False}, name
        assert [_action(s) for s in _steps(name)].count(CHECKOUT) == 1, name


def _header() -> str:
    """The comment block above ``on:``, as one line of text."""
    head = _text().split("\non:\n", 1)[0]
    lines = [line.lstrip("#").strip() for line in head.splitlines() if line.startswith("#")]
    return re.sub(r"\s+", " ", " ".join(lines))


def test_concurrency_never_cancels_a_running_run() -> None:
    workflow = _workflow()
    # queue: max keeps every pending dispatch; without it GitHub keeps one pending run per
    # group and cancels it when a newer one arrives.
    assert workflow["concurrency"] == {
        "group": "v31-run",
        "cancel-in-progress": False,
        "queue": "max",
    }
    assert all("concurrency" not in job for job in workflow["jobs"].values())


def test_a_queued_run_is_protected_by_queue_max_and_by_an_operating_rule() -> None:
    header = _header()
    assert "never dispatch v31-run while another v31-run is queued or running" in header.lower()
    assert "workflow level" in header  # the key is not shown to be honoured there
    # Nor is a registered dispatch cancelled: a cancelled launch counts (v31-d21, L2).
    assert (
        "Never cancel a queued or running registered dispatch either: a cancelled launch "
        "counts as an execution of its registration."
    ) in header
    # The comment on the concurrency block says what it does; it does not claim more.
    comment = _text().split("\nconcurrency:\n", 1)[0].rsplit("\n\n", 1)[-1]
    assert "queue: max" in comment and "pending" in comment
    assert "never cancels" not in comment
    assert "operating rule" in comment


def test_the_header_records_every_attempt_and_does_not_invite_a_rerun() -> None:
    header = _header()
    assert "Every attempt is recorded" in header
    assert "even when it fails or times out" in header
    assert "new recorded attempt" in header
    # An upload after a failure waits for a scan that succeeded; a scan that fails, is
    # cancelled or is skipped uploads nothing.
    assert "steps.guard_outputs.outcome == 'success'" in header
    assert "fails, is cancelled or is skipped, nothing is uploaded" in header
    assert "refuses the duplicate" in header
    assert "Do not re-run a registered run" in header
    assert not re.search(r"can be re-run|re-run from the Actions page", header)
    # The summaries are named for their attempt, so re-running aggregate alone is harmless.
    assert "v31-summary-attempt-<n>" in header and "v31-smoke-summary-attempt-<n>" in header


TOKEN_ENV = {"GITHUB_TOKEN": "${{ github.token }}"}  # the job's own token, nothing stored


def _token_steps() -> list[tuple[str, str | None]]:
    """Each (job, step name) whose env holds the job's token."""
    return [
        (job, step.get("name"))
        for job in JOBS
        for step in _steps(job)
        if "GITHUB_TOKEN" in step.get("env", {})
    ]


def test_no_secret_is_referenced() -> None:
    # The public archives need none; the checkout is read-only with no stored credentials.
    # The one token is the job's own (github.token, never a stored secret), in the env of
    # the two steps that check for another dispatch of the registration (Ruling R4-2).
    assert _token_steps() == [
        ("plan", "Refuse a second dispatch of the registration"),
        ("aggregate", "Aggregate"),
    ]
    workflow = _workflow()
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            env = step.get("env", {})
            if "GITHUB_TOKEN" in env:
                assert {"GITHUB_TOKEN": env.pop("GITHUB_TOKEN")} == TOKEN_ENV
    # Without those two entries (removed from this parsed copy), nothing names a secret.
    parsed = json.dumps(workflow)
    assert not re.search(r"secrets|_token|token\b|api[_-]?key|password", parsed, re.IGNORECASE)


def test_python_is_pinned_and_the_install_uses_the_lock() -> None:
    quality_steps = yaml.safe_load(QUALITY.read_text(encoding="utf-8"))["jobs"]
    (quality_python,) = [
        s["with"]["python-version"]
        for job in quality_steps.values()
        for s in job["steps"]
        if s.get("uses", "").startswith("actions/setup-python@")
    ]
    for name in JOBS:
        (setup,) = _find_steps(name, SETUP_PYTHON)
        assert setup["with"]["python-version"] == quality_python == "3.12", name
        installs = [s["run"] for s in _steps(name) if s.get("run", "").startswith("python -m pip")]
        if name == "status":  # it runs a short standard-library script and installs nothing
            assert installs == [] and set(setup["with"]) == {"python-version"}
            continue
        assert setup["with"]["cache-dependency-path"] == "requirements-dev.lock", name
        assert installs == [
            "python -m pip install --upgrade pip",
            "python -m pip install -r requirements-dev.lock",
            "python -m pip install -e . --no-deps",
        ], name
    allowed = {f"{action}@{sha}" for action, (sha, _) in PINS.items()}
    used = {_action(s) for job in _jobs().values() for s in job["steps"] if "uses" in s}
    assert used == allowed, used ^ allowed


def test_every_action_is_pinned_to_a_full_commit_sha_with_its_tag() -> None:
    """Ruling F9: a moved tag cannot change what runs. Each ``uses:`` line names a full
    commit SHA and, in a trailing comment, the exact tag that commit carries, the same
    major versions as before."""
    lines = [
        line.strip()
        for line in _text().splitlines()
        if line.strip().startswith(("- uses:", "uses:"))
    ]
    assert lines
    for line in lines:
        match = re.fullmatch(
            r"(?:- )?uses: ([\w.-]+/[\w.-]+)@([0-9a-f]{40}) # (v[0-9]+\.[0-9]+\.[0-9]+)", line
        )
        assert match is not None, line
        action, sha, tag = match.groups()
        assert PINS[action] == (sha, tag), line
    majors = {action: tag.split(".")[0] for action, (_, tag) in PINS.items()}
    assert majors == {
        "actions/checkout": "v4",
        "actions/setup-python": "v5",
        "actions/upload-artifact": "v4",
        "actions/download-artifact": "v4",
    }


# --- the job graph ----------------------------------------------------------------------


def test_prepare_only_mode_runs_only_prepare() -> None:
    assert _ran("prepare-only") == {"prepare"}
    calls = {tokens[2]: tokens for _, tokens in _driver_calls("prepare")}  # by --mode
    assert set(calls) == {"$MODE", "prepare-only"}  # $MODE: registered or rehearsal
    only = calls["prepare-only"]
    assert _option(only, "--code-commit") == "$CODE_COMMIT"
    assert "--prepare-sha256" in only
    assert "--registration-sha256" not in only and "--repo" not in only
    assert "--code-commit" not in calls["$MODE"]
    only_steps = [s for s in _steps("prepare") if "prepare-only" in str(s.get("if", ""))]
    assert [s["name"] for s in only_steps] == ["Check the code commit", "Prepare (prepare-only)"]
    # It uploads the packs with prepare.json, and prints prepare.json; the legacy dataset
    # belongs to a registered run's minute cells.
    assert any("cat v31/out/prepare.json" in script for script in _scripts("prepare"))
    assert _upload("prepare", "v31-packs")["path"] == "v31/out/"
    (legacy,) = [s for s in _uploads("prepare") if s["with"]["name"] == "v31-legacy-data"]
    assert legacy["if"] == "${{ (inputs.mode == 'registered' || inputs.mode == 'rehearsal') }}"


def test_smoke_mode_runs_only_the_smoke_job_with_all_216_cells_and_no_registration() -> None:
    assert _ran("smoke") == {"smoke"}
    ((subcommand, tokens),) = _driver_calls("smoke")
    assert subcommand == "smoke"
    assert "--cells" not in tokens  # the full default: every registered cell
    scripts = " ".join(_scripts("smoke"))
    assert "registration" not in scripts.lower()
    assert "REGISTRATION_SHA256" not in scripts
    smoke_summary = "v31-smoke-summary-attempt-${{ github.run_attempt }}"
    assert _upload("smoke", smoke_summary)["retention-days"] == 90
    assert not _downloads("smoke")


def test_registered_mode_runs_every_job_and_a_failure_stops_only_what_depends_on_it() -> None:
    everything = set(GRAPH)
    assert _ran("registered") == everything
    # prepare fails: nothing is left to run or to aggregate; status records it.
    assert _ran("registered", failing=["prepare"]) == {"plan", "prepare", "status"}
    assert _ran("registered", failing=["plan"]) == {"plan", "status"}
    # picks fails: the V3 cells cannot run; the others and the aggregate still do.
    assert _ran("registered", failing=["picks"]) == everything - {"run-v3"}
    # A failed cell never stops the aggregate: it judges what ran and names what did not.
    assert _ran("registered", failing=["run-main"]) == everything
    assert _ran("registered", failing=["run-v3"]) == everything


def test_v3_cells_wait_for_picks_and_other_cells_do_not() -> None:
    """Only the selector cells read the picks, and only they wait for the picks job
    (run-v3, with --picks); every other cell, the six fixed long-only V3 rules among them,
    runs in run-main without --picks, which the driver requires of the selector alone and
    refuses for a long-only rule (tests/test_v31_driver_cli.py). The rehearsal's real steps
    run a long-only cell through run-main (test_the_rehearsal_steps_run_end_to_end_offline)."""
    jobs = _jobs()
    assert "picks" in _needs(jobs["run-v3"])
    assert "picks" not in _needs(jobs["run-main"])
    assert set(_needs(jobs["run-main"])) == {"plan", "prepare"}
    assert set(_needs(jobs["run-v3"])) == {"plan", "prepare", "picks"}
    assert _needs(jobs["picks"]) == ["plan", "prepare"]
    # The driver's one rule for both the plan's split and run-cell's --picks: the selector.
    assert [arm for arm in V3_ARMS if v31_driver.needs_picks(arm)] == ["unchanged_v3_selector"]
    (v3_call,) = _driver_calls("run-v3")
    (main_call,) = _driver_calls("run-main")
    assert "--picks" in v3_call[1]
    assert "--picks" not in main_call[1]  # long-only V3 rules run here, reading no picks
    assert "--legacy-data" not in v3_call[1]  # the selector replays the picks, not minutes
    picks_download = _download("run-v3", "v3-picks-attempt-*")
    assert picks_download["path"] == "v31/picks"
    assert not [s for s in _downloads("run-main") if "picks" in str(s["with"])]
    # A failed picks job skips the V3 cells, and only them.
    assert jobs_that_run("registered", failing=["picks"])["run-v3"] == "skipped"
    assert jobs_that_run("registered", failing=["picks"])["run-main"] == "success"


def test_aggregate_runs_after_failures_and_needs_both_run_jobs_and_picks() -> None:
    aggregate = _jobs()["aggregate"]
    assert set(_needs(aggregate)) == {"plan", "run-main", "run-v3", "picks"}
    assert "!cancelled()" in aggregate["if"]
    # !cancelled() alone would also run it in the other modes, with every job it needs
    # skipped; and after a failed prepare, with nothing to read.
    assert "aggregate" not in _ran("smoke") | _ran("prepare-only") | _ran("timing")
    assert "aggregate" not in _ran("registered", failing=["prepare"])
    assert _ran("registered", failing=["run-main"]) >= {"aggregate"}


def test_matrices_are_parallel_capped_and_not_fail_fast_with_six_hour_timeouts() -> None:
    jobs = _jobs()
    for name in MATRIX_JOBS:
        strategy = jobs[name]["strategy"]
        assert strategy["max-parallel"] == 20, name
        assert strategy["fail-fast"] is False, name
    for name in ("prepare", "picks", *MATRIX_JOBS, "aggregate", "timing"):
        assert jobs[name]["timeout-minutes"] == 360, name
    for name in JOBS:
        assert jobs[name]["runs-on"] == "ubuntu-latest", name
        assert 0 < jobs[name]["timeout-minutes"] <= 360, name


def test_workflow_matrix_comes_from_the_registration_cell_list() -> None:
    jobs = _jobs()
    assert jobs["run-main"]["strategy"]["matrix"] == {
        "cell": "${{ fromJSON(needs.plan.outputs.main_cells) }}"
    }
    assert jobs["run-v3"]["strategy"]["matrix"] == {
        "cell": "${{ fromJSON(needs.plan.outputs.v3_cells) }}"
    }
    assert jobs["plan"]["outputs"] == {
        "v3_cells": "${{ steps.cells.outputs.v3_cells }}",
        "main_cells": "${{ steps.cells.outputs.main_cells }}",
        "registration_sha256": "${{ steps.cells.outputs.registration_sha256 }}",
    }
    # The driver's own plan lists the cells, after its job gate (Rulings F6, F7): the split
    # and GitHub's 256-job limit are the driver's, tested with it.
    ((subcommand, call),) = [c for c in _driver_calls("plan") if c[0] == "plan"]
    assert _option(call, "--mode") == "$MODE" and _option(call, "--repo") == "$REPO"
    assert _option(call, "--cells") == "$REHEARSAL_CELLS"
    assert v31_driver.MAX_MATRIX == 256
    for name in ("picks", *MATRIX_JOBS, "aggregate", "prepare"):
        assert jobs[name]["env"] == {
            "REGISTRATION_SHA256": "${{ needs.plan.outputs.registration_sha256 }}"
        }, name


def test_artifact_names_carry_the_run_attempt_and_nest_the_cell_folder() -> None:
    attempt = "attempt-${{ github.run_attempt }}"
    for name in MATRIX_JOBS:
        ((_, call),) = _driver_calls(name)
        upload = _upload(name, f"cell-${{{{ matrix.cell }}}}-{attempt}")
        # run-cell writes <out>/<cell_id>/; the artifact is <out>, so a download keeps the
        # cell's folder one level down: cell-<id>-attempt-<n>/<id>/.
        assert upload["path"] == _option(call, "--out") == "v31/cell-out"
        assert "matrix" not in upload["path"]
        assert upload["retention-days"] == 90
    ((_, picks),) = _driver_calls("picks")
    upload = _upload("picks", f"v3-picks-{attempt}")
    assert upload["path"] == _option(picks, "--out") == "v31/picks-out"  # holds v3_picks/
    for name in ("picks", *MATRIX_JOBS, "aggregate"):
        for _, call in _driver_calls(name):
            assert _option(call, "--attempt-id") == "X-attempt-X"
        assert any(f"--attempt-id {ATTEMPT_ID}" in s for s in _scripts(name)), name
    # Every upload keeps its artifact for the maximum retention. A run job's upload only warns
    # about a missing directory (a job killed before it wrote anything); the others fail.
    for name in JOBS:
        for step in _uploads(name):
            expected = "warn" if name in ("picks", *MATRIX_JOBS, "timing") else "error"
            assert step["with"]["retention-days"] == 90, (name, step["with"]["name"])
            assert step["with"]["if-no-files-found"] == expected, (name, step["with"]["name"])
    names = {s["with"]["name"] for name in JOBS for s in _uploads(name)}
    assert names == {
        "v31-rehearsal-world",
        "v31-packs",
        "v31-legacy-data",
        f"v3-picks-{attempt}",
        f"cell-${{{{ matrix.cell }}}}-{attempt}",
        f"{SUMMARY_NAME}-{attempt}",
        f"v31-smoke-summary-{attempt}",
        f"{STATUS_NAME}-{attempt}",
        f"v31-timing-${{{{ matrix.part }}}}-{attempt}",
    }
    # The world, the packs and the dataset keep fixed names, so a re-run of every job fails
    # closed at the first upload; every other artifact is named for its attempt.
    fixed = {n for n in names if "attempt" not in n}
    assert fixed == {"v31-rehearsal-world", "v31-packs", "v31-legacy-data"}


def test_downstream_jobs_read_the_prepared_artifacts_where_the_driver_looks() -> None:
    for name in ("picks", *MATRIX_JOBS):
        packs = _download(name, "v31-packs")
        ((_, call),) = _driver_calls(name)
        assert _option(call, "--packs") == f"{packs['path']}/packs"  # the layout it uploaded
    for name in ("run-main",):
        legacy = _download(name, "v31-legacy-data")
        ((_, call),) = _driver_calls(name)
        assert _option(call, "--legacy-data") == legacy["path"]
    assert not [s for s in _downloads("run-v3") if s["with"].get("name") == "v31-legacy-data"]
    # prepare uploads exactly those layouts: out/ holds packs/ and prepare.json; the
    # legacy dataset is work/legacy, whose root holds binance/.
    ((_, prepare),) = [(c, t) for c, t in _driver_calls("prepare") if t[2] == "$MODE"]
    assert _upload("prepare", "v31-packs")["path"] == _option(prepare, "--out") + "/"
    assert _upload("prepare", "v31-legacy-data")["path"] == _option(prepare, "--work") + "/legacy"


def test_aggregate_downloads_each_artifact_into_its_own_folder() -> None:
    world = [s for s in _downloads("aggregate") if s["with"].get("name") == "v31-rehearsal-world"]
    assert len(world) == 1 and world[0]["with"]["path"] == "v31/world-download"  # rehearsal
    downloads = [s for s in _downloads("aggregate") if s not in world]
    patterns = [s["with"]["pattern"] for s in downloads]
    assert patterns == ["cell-*-attempt-*", "v3-picks-attempt-*"]
    for step in downloads:
        assert "merge-multiple" not in step["with"]  # a merge would drop the folder names
        assert "name" not in step["with"]
        assert step["with"]["path"] == "v31/cells"
    ((_, call),) = _driver_calls("aggregate")
    assert _option(call, "--cells") == "v31/cells"  # cells/cell-<id>-attempt-<n>/<id>/
    summary = f"{SUMMARY_NAME}-attempt-${{{{ github.run_attempt }}}}"
    assert _upload("aggregate", summary)["path"] == _option(call, "--out")
    assert "merge-multiple" not in json.dumps(_workflow())


def test_aggregate_makes_its_cells_folder_before_it_downloads_into_it() -> None:
    """download-artifact creates no destination when a pattern matches no artifact, and the
    aggregation refuses a cells directory that is not there; the folder is made first."""
    steps = _steps("aggregate")
    (make,) = [i for i, s in enumerate(steps) if s.get("name") == "Create the cells folder"]
    by_pattern = [
        i
        for i, s in enumerate(steps)
        if _action(s).startswith("actions/download-artifact@") and "pattern" in s["with"]
    ]
    ((_, call),) = _driver_calls("aggregate")
    folder = _option(call, "--cells")
    # The exact path the downloads and the aggregate step use; no input reaches the script;
    # no condition, so a rehearsal makes it too; the checkout (which cleans the workspace)
    # comes first.
    assert steps[make] == {"name": "Create the cells folder", "run": f"mkdir -p {folder}"}
    assert len(by_pattern) == 2 and make < min(by_pattern)
    assert {steps[i]["with"]["path"] for i in by_pattern} == {folder}
    assert steps[0] == JOB_START_STEP and _action(steps[1]) == CHECKOUT and make > 1
    for mode in ("registered", "rehearsal"):
        assert steps_that_run("aggregate", mode=mode)[make] == "success"
    # Only the cells folder is made: no job makes a picks folder that could pass for the
    # picks job's (run-v3 requires exactly one verified picks artifact).
    for job in JOBS:
        for script in _scripts(job):
            assert not re.search(r"mkdir.*picks", script), job


def test_every_driver_call_parses_with_the_drivers_own_parser() -> None:
    parser = v31_driver.build_parser()
    # argparse accepts an unambiguous prefix (--registration-sha for --registration-sha256);
    # a workflow must spell the option out, so abbreviations are off for every subcommand.
    (subparsers,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    for subparser in subparsers.choices.values():
        subparser.allow_abbrev = False
    seen = set()
    # The variables a choice or a count reads, as a registered dispatch and a timing leg set
    # them (each mode's own values are parsed in the bash tests below).
    values = {"$MODE": "registered", "$PART": "picks", "$REHEARSAL_CELLS": ""}
    for name in JOBS:
        for subcommand, tokens in _driver_calls(name):
            seen.add(subcommand)
            try:
                args = parser.parse_args([values.get(token, token) for token in tokens])
            except SystemExit as exc:  # argparse reports a bad call by exiting
                raise AssertionError(f"{name}: {tokens} is refused by the CLI") from exc
            assert args.command == subcommand
    assert seen == {
        "plan",
        "dispatch-check",
        "prepare",
        "picks",
        "run-cell",
        "aggregate",
        "smoke",
        "rehearsal-world",
        "timing",
        "timing-close",
    }
    # The registered calls pass the plan's pin, the run mode and the checkout ($REPO: the
    # repository, or a rehearsal's world); nothing else is overridden.
    for name in ("picks", "run-main", "run-v3", "aggregate"):
        ((_, call),) = _driver_calls(name)
        assert _option(call, "--registration-sha256") == "$REGISTRATION_SHA256"
        assert (_option(call, "--mode"), _option(call, "--repo")) == ("$MODE", "$REPO")
        assert not {"--registration", "--run-manifest"} & set(call)
    for _, call in _driver_calls("run-main") + _driver_calls("run-v3"):
        assert _option(call, "--cell") == "$CELL"


# --- registration check and 2025 guard --------------------------------------------------


def test_registered_mode_verifies_the_registration_hash_first() -> None:
    assert _steps("plan")[0] == JOB_START_STEP  # the job's start, before anything else
    steps = _checked_out("plan")
    assert _action(steps[0]) == CHECKOUT
    verify = steps[1]  # before Python is set up, installed or run
    script = verify["run"]
    assert "sha256sum config/v3_1_registration.json" in script
    assert "$REGISTRATION_SHA256" in script and "exit 1" in script
    assert all("python" not in s.get("run", "") for s in steps[:2])
    assert verify["if"] == "${{ inputs.mode == 'registered' }}"
    assert _jobs()["plan"]["if"] == (
        "${{ (inputs.mode == 'registered' || inputs.mode == 'rehearsal') }}"
    )
    # The inputs reach the shell through the environment, never spliced into a script.
    for name in JOBS:
        assert "${{" not in " ".join(_scripts(name)).replace(ATTEMPT_ID, ""), name
    assert _workflow()["env"] == {
        "MODE": "${{ inputs.mode }}",
        "REGISTRATION_SHA256": "${{ inputs.registration_sha256 }}",
        "CODE_COMMIT": "${{ inputs.code_commit }}",
        "REHEARSAL_CELLS": "${{ inputs.rehearsal_cells }}",
        "REPO": "${{ inputs.mode == 'rehearsal' && 'v31/work/repo' || '.' }}",
    }


@pytest.mark.parametrize(
    ("pin", "passes"),
    [
        ("{good}", True),
        ("{bad}", False),  # a well-formed pin of another file
        ("{good_upper}", False),  # not the lowercase hex sha256sum prints
        ("", False),
        ("abc", False),
    ],
)
def test_the_registration_check_step_fails_on_any_other_pin(
    tmp_path: Path, pin: str, passes: bool
) -> None:
    registration = tmp_path / "config/v3_1_registration.json"
    registration.parent.mkdir()
    registration.write_bytes(b'{"schema": "v3.1-registration-1"}\n')
    good = hashlib.sha256(registration.read_bytes()).hexdigest()
    value = pin.format(good=good, bad="0" * 64, good_upper=good.upper())
    step = _checked_out("plan")[1]
    assert step["name"] == "Verify the registration against the dispatched SHA-256"
    result = _run_step(step["run"], tmp_path, {"REGISTRATION_SHA256": value})
    assert (result.returncode == 0) is passes, result.stderr + result.stdout


def test_every_data_job_has_the_guard_after_its_data_step() -> None:
    scripts = set()
    for name in DATA_JOBS:
        steps = _steps(name)
        guards = _guard_steps(name)
        scripts |= {steps[guard]["run"] for guard in guards}
        data = [
            index
            for index, step in enumerate(steps)
            if _action(step).startswith("actions/download-artifact@")
            or re.search(
                r"v31_driver\.py (prepare|smoke|rehearsal-world|timing)\b|tar -xf|status\.json",
                step.get("run", ""),
            )
        ]
        assert data, f"{name} has no data step"
        assert guards[0] > max(data), f"{name}: the guard comes before its data step"
        # The first guard can never be skipped: it has no condition, or (in a timing job,
        # whose only scan follows a step that may time out) always().
        assert steps[guards[0]].get("if", "${{ always() }}") == "${{ always() }}", name
        driver = [i for i, s in enumerate(steps) if "scripts/v31_driver.py" in s.get("run", "")]
        if name in ("smoke", "prepare", "plan", "status", "timing"):
            # The driver (or the status script) makes the data; one scan follows it.
            assert len(guards) == 1, name
            assert not driver or max(driver) < guards[0], name
        else:
            # Downstream jobs check what they downloaded before the driver reads it, and
            # check again what the driver wrote.
            assert len(guards) == 2, name
            assert guards[0] < min(driver) and max(driver) < guards[1], name
    assert len(scripts) == 1, "the guard is one script, the same in every job and position"


def test_a_guard_step_immediately_precedes_every_upload() -> None:
    # What the driver wrote is scanned too: the step before an upload (or before the run of
    # consecutive uploads it starts) is a guard.
    for name in JOBS:
        steps = _steps(name)
        guards = set(_guard_steps(name))
        for index, step in enumerate(steps):
            if not _action(step).startswith("actions/upload-artifact@"):
                continue
            before = index - 1
            while before >= 0 and _action(steps[before]).startswith("actions/upload-artifact@"):
                before -= 1
            assert before in guards, f"{name}: upload {step['with']['name']} follows no guard"


@pytest.mark.parametrize("job", ["picks", "run-main", "run-v3"])
def test_a_run_job_records_its_attempt_even_when_it_fails(job: str) -> None:
    steps = _steps(job)
    (upload,) = [i for i, s in enumerate(steps) if _action(s).startswith("actions/upload")]
    driver = next(i for i, s in enumerate(steps) if "scripts/v31_driver.py" in s.get("run", ""))
    first, last = _guard_steps(job)
    assert last == upload - 1 and steps[last]["id"] == "guard_outputs"
    # A failed or timed-out run still uploads its directory (and its claim); a missing
    # directory only warns, so a job killed before it wrote anything shows in the log.
    assert steps[upload]["if"] == UPLOAD_AFTER_SCAN
    assert steps[last]["if"] == "${{ always() }}"
    assert steps[upload]["with"]["if-no-files-found"] == "warn"
    assert steps_that_run(job)[upload] == "success"
    assert steps_that_run(job, failing=[driver])[upload] == "success"
    # The scan before the upload ran after the failure, and a scan that fails blocks the upload.
    assert steps_that_run(job, failing=[driver])[last] == "success"
    assert steps_that_run(job, failing=[last])[upload] == "skipped"
    assert steps_that_run(job, failing=[first, last])[upload] == "skipped"
    # So does a scan that was cancelled or skipped: it has not failed, and it has not passed
    # either, so nothing unscanned is uploaded (with the driver having failed or not).
    for scan in ("cancelled", "skipped"):
        for failing in ((), (driver,)):
            outcomes = steps_that_run(job, failing=failing, forced={last: scan})
            assert (outcomes[last], outcomes[upload]) == (scan, "skipped"), (scan, failing)
    # The other jobs upload only what succeeded.
    for other in ("smoke", "prepare", "aggregate"):
        for step in _uploads(other):
            assert "always()" not in str(step.get("if", "")), other


UPLOAD_AFTER_SCAN = "${{ always() && steps.guard_outputs.outcome == 'success' }}"


def _scan_gated_uploads() -> list[tuple[str, int]]:
    """Each (job, step index) of an upload that runs after a failure too (``always()``)."""
    return [
        (name, index)
        for name in JOBS
        for index, step in enumerate(_steps(name))
        if _action(step).startswith("actions/upload-artifact@") and "always()" in step.get("if", "")
    ]


def test_an_upload_after_a_failure_runs_only_when_the_scan_before_it_succeeded() -> None:
    """The scan has to have succeeded, not merely not failed: a scan that was cancelled or
    skipped has not looked at what the upload would publish."""
    gated = _scan_gated_uploads()
    assert [name for name, _ in gated] == ["picks", "run-main", "run-v3", "timing"]
    assert "!= 'failure'" not in _text()
    for name, upload in gated:
        steps = _steps(name)
        assert steps[upload]["if"] == UPLOAD_AFTER_SCAN, name
        # The scan is the step just before it, runs after a failed step (if: always()), and is
        # the 2025 guard itself.
        assert steps[upload - 1]["id"] == "guard_outputs", name
        assert steps[upload - 1]["if"] == "${{ always() }}", name
        assert upload - 1 in _guard_steps(name), name
        condition = steps[upload]["if"][3:-2].strip()
        for scan, runs in {
            "success": True,
            "failure": False,
            "cancelled": False,
            "skipped": False,
        }.items():
            ran = _truth(condition, "registered", {}, {"guard_outputs": scan})
            assert ran is runs, (name, scan)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A repository like the runner's checkout: tracked files, one of them named for 2026."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "docs/backtests").mkdir(parents=True)
    # A real file of this repository whose name the guard's patterns match.
    (repo / "docs/backtests/fee-levels-2026-09.md").write_text("fees\n", encoding="utf-8")
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "branch", "bob/task-2026-10-12-example")  # a ref named for a date, as here
    return repo


def _guard(checkout: Path, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    script = _steps("prepare")[_guard_steps("prepare")[0]]["run"]
    return _run_step(script, checkout, {"RUNNER_TEMP": runner_temp.as_posix()})


def test_the_guard_passes_a_tree_with_no_data_and_one_with_pre_2025_archives(
    checkout: Path, tmp_path: Path
) -> None:
    # Tracked files named for 2026 and a ref named for 2026 are the repository, not data.
    assert _guard(checkout, tmp_path).returncode == 0
    data = checkout / "v31/work/legacy/binance/data/spot/monthly/klines/BTCUSDT/1m"
    data.mkdir(parents=True)
    for month in ("2019-09", "2020-12", "2024-12"):
        (data / f"BTCUSDT-1m-{month}.zip").write_bytes(b"x")
    (checkout / "v31/out/packs").mkdir(parents=True)
    (checkout / "v31/out/packs/window-w1.pack.json.gz").write_bytes(b"x")
    (checkout / "v31/out/prepare.json").write_text("{}\n", encoding="utf-8")
    result = _guard(checkout, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "BTCUSDT-1m-2025-01.zip",
        "BTCUSDT-1h-2026-03.zip",
        "ETHUSDT-fundingRate-2029-12.zip.CHECKSUM",
        "BTCUSDT-1d-2030-01.zip",
        "XRPUSDT-1m-2099-12.zip",
    ],
)
def test_the_guard_fails_on_any_file_named_for_2025_or_later(
    checkout: Path, tmp_path: Path, name: str
) -> None:
    data = checkout / "v31/work/inventory/archives"
    data.mkdir(parents=True)
    (data / "BTCUSDT-1m-2024-12.zip").write_bytes(b"x")
    (data / name).write_bytes(b"x")
    result = _guard(checkout, tmp_path)
    assert result.returncode == 1
    assert name in result.stdout


@pytest.mark.parametrize("tool", ["git", "tr", "sed", "sort", "find", "comm", "grep"])
def test_the_guard_fails_when_its_own_scan_fails(checkout: Path, tmp_path: Path, tool: str) -> None:
    # A tool that fails with status 2 (grep's own error status, or any other tool's failure)
    # is a broken scan, not a clean tree.
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    script = _steps("prepare")[_guard_steps("prepare")[0]]["run"]
    result = _run_step(
        script, checkout, {"RUNNER_TEMP": runner_temp.as_posix()}, f"{tool}() {{ return 2; }}\n"
    )
    assert result.returncode != 0, result.stdout + result.stderr


def test_the_guard_tolerates_only_greps_no_match_status(checkout: Path, tmp_path: Path) -> None:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(exist_ok=True)
    script = _steps("prepare")[_guard_steps("prepare")[0]]["run"]
    env = {"RUNNER_TEMP": runner_temp.as_posix()}
    assert _run_step(script, checkout, env, "grep() { return 1; }\n").returncode == 0
    assert _run_step(script, checkout, env, "grep() { return 3; }\n").returncode == 1


def test_the_guard_fails_outside_a_git_checkout(tmp_path: Path) -> None:
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    bare = tmp_path / "not-a-checkout"
    bare.mkdir()
    script = _steps("prepare")[_guard_steps("prepare")[0]]["run"]
    result = _run_step(script, bare, {"RUNNER_TEMP": runner_temp.as_posix()})
    assert result.returncode != 0


def test_the_guard_also_fails_on_a_downloaded_artifact_folder_named_for_2025(
    checkout: Path, tmp_path: Path
) -> None:
    folder = checkout / "v31/prepared/packs/window-2025-01"
    folder.mkdir(parents=True)
    (folder / "pack.json").write_text("{}\n", encoding="utf-8")
    assert _guard(checkout, tmp_path).returncode == 1


# --- picks, plan -------------------------------------------------------------------------


def _picks_check() -> str:
    return _step("run-v3", "picks_dir")["run"]


@pytest.mark.parametrize("case", ["good", "wrong-receipt", "two-attempts", "none", "no-folder"])
def test_run_v3_uses_exactly_the_picks_the_picks_job_published(tmp_path: Path, case: str) -> None:
    """``no-folder``: the pattern download matched no artifact, so download-artifact left
    ``v31/picks`` uncreated. The step then fails with its message, as for an empty folder;
    nothing creates a picks folder that could pass for a verified one."""
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    picks = tmp_path / "v31/picks"
    if case != "no-folder":
        picks.mkdir(parents=True)
    outcome = b'{"job": "v3_picks"}\n'
    receipt = hashlib.sha256(outcome).hexdigest()
    attempts = {
        "good": ["1"],
        "wrong-receipt": ["1"],
        "two-attempts": ["1", "2"],
        "none": [],
        "no-folder": [],
    }
    for attempt in attempts[case]:
        directory = picks / f"v3-picks-attempt-{attempt}/v3_picks"
        directory.mkdir(parents=True)
        (directory / "outcome.json").write_bytes(outcome)
    given = "0" * 64 if case == "wrong-receipt" else receipt
    result = _run_step(
        _picks_check(),
        tmp_path,
        {"PICKS_RECEIPT_SHA256": given, "GITHUB_OUTPUT": output.as_posix()},
    )
    if case == "good":
        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8") == "dir=v31/picks/v3-picks-attempt-1/v3_picks\n"
    else:
        assert result.returncode == 1
        assert output.read_text(encoding="utf-8") == ""
        assert "::error::" in result.stdout
        if case in ("none", "no-folder"):
            assert "expected one v3-picks-attempt-<n>/v3_picks directory" in result.stdout
            assert not (tmp_path / "v31/picks/v3-picks-attempt-1").exists()


def test_the_picks_receipt_is_a_job_output_of_the_picks_job() -> None:
    picks = _jobs()["picks"]
    assert picks["outputs"] == {"picks_receipt_sha256": "${{ steps.picks.outputs.receipt_sha256 }}"}
    step = _step("picks", "picks")
    assert step["id"] == "picks"
    assert "receipt_sha256=" in step["run"] and '"$GITHUB_OUTPUT"' in step["run"]
    check = _step("run-v3", "picks_dir")
    assert check["env"]["PICKS_RECEIPT_SHA256"] == "${{ needs.picks.outputs.picks_receipt_sha256 }}"
    # The run step passes the directory the check found.
    ((_, call),) = _driver_calls("run-v3")
    assert _option(call, "--picks") == "$PICKS_DIR"
    run_step = next(s for s in _steps("run-v3") if "scripts/v31_driver.py" in s.get("run", ""))
    assert run_step["env"]["PICKS_DIR"] == f"${{{{ steps.{check['id']}.outputs.dir }}}}"


FAKE_RECEIPT = "c" * 64
FAKE_REGISTRATION = "d" * 64
# What the stub prints: every field a step reads from a driver document.
STUB_DOCUMENT = {
    "outcome_sha256": FAKE_RECEIPT,
    "summary": "x",
    "registration_sha256": FAKE_REGISTRATION,
    "v3_cells": ["w1.unchanged_v3_selector.native.c1.research"],
    "main_cells": ["w1.combined.olhc.c1.research"],
}
STUB = """\
python() {
  if [ "$1" = scripts/v31_driver.py ]; then
    shift
    printf '%s\\0' "$@" > "$ARGV_FILE"
    printf '%s\\n' 'DOCUMENT'
  else
    REAL "$@"
  fi
}
"""


def _driver_step_run(
    step: dict[str, Any], tmp_path: Path, **extra: str
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    """Run a step that calls the driver with ``python`` replaced by a stub that records the
    driver's argv and prints a document (``STUB_DOCUMENT``). Returns the result, the argv
    (of the step's last driver call) and the output file."""
    argv_file, output = tmp_path / "argv", tmp_path / "github-output"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "checkout"
    (cwd / "config").mkdir(parents=True, exist_ok=True)
    (cwd / "config/v3_1_prepare.json").write_bytes(b'{"schema": "v3.1-prepare-1"}\n')
    (cwd / "v31/work").mkdir(parents=True, exist_ok=True)  # what rehearsal-world makes
    output.write_text("", encoding="utf-8")
    real = shlex.quote(Path(sys.executable).as_posix())
    document = json.dumps(STUB_DOCUMENT)
    prelude = STUB.replace("DOCUMENT", document).replace("REAL", real)
    script = step["run"].replace("${{ github.run_id }}", "4242")
    script = script.replace("${{ github.run_attempt }}", "2")
    env = {
        "ARGV_FILE": argv_file.as_posix(),
        "RUNNER_TEMP": runner_temp.as_posix(),
        "GITHUB_OUTPUT": output.as_posix(),
        "MODE": "registered",
        "REPO": ".",
        "REGISTRATION_SHA256": "a" * 64,
        "CODE_COMMIT": "b" * 40,
        "REHEARSAL_CELLS": "",
        "CELL": "w1.combined.olhc.c1.research",
        "PART": "picks",
        "OUTCOME": "success",
        **extra,
    }
    result = _run_step(script, cwd, env, prelude)
    argv = argv_file.read_bytes().decode().split("\0")[:-1] if argv_file.exists() else []
    return result, argv, output


def _driver_steps() -> list[tuple[str, dict[str, Any]]]:
    return [
        (job, step)
        for job in JOBS
        for step in _steps(job)
        if "scripts/v31_driver.py" in step.get("run", "")
    ]


def test_each_driver_step_passes_the_dispatch_values_to_the_cli(tmp_path: Path) -> None:
    """The steps run in bash with a stub for the driver, so the shell's quoting, line
    continuations and variables are exercised, and the argv is parsed by the real parser."""
    parser = v31_driver.build_parser()
    picks_dir = "v31/picks/v3-picks-attempt-1/v3_picks"
    cell = "w1.combined.olhc.c1.research"
    seen = []
    for index, (job, step) in enumerate(_driver_steps()):
        folder = tmp_path / str(index)
        result, argv, output = _driver_step_run(step, folder, PICKS_DIR=picks_dir)
        assert result.returncode == 0, (job, result.stderr)
        args = parser.parse_args(argv)
        seen.append((job, args.command, getattr(args, "mode", None)))
        if args.command in ("plan", "prepare", "picks", "run-cell", "aggregate"):
            # The checkout ($REPO) and the committed registration files.
            assert (args.repo, args.registration, args.run_manifest) == (
                ".",
                "config/v3_1_registration.json",
                "config/v3_1_run_manifest.json",
            )
        if args.command == "plan":
            assert (args.mode, args.registration_sha256, args.cells) == (
                "registered",
                "a" * 64,
                None,
            )
            assert output.read_text(encoding="utf-8").splitlines() == [
                'v3_cells=["w1.unchanged_v3_selector.native.c1.research"]',
                'main_cells=["w1.combined.olhc.c1.research"]',
                f"registration_sha256={FAKE_REGISTRATION}",
            ]
        elif args.command == "prepare" and args.mode == "registered":
            assert args.registration_sha256 == "a" * 64
            assert (args.work, args.out) == ("v31/work", "v31/out")
        elif args.command == "prepare":
            config = folder / "checkout/config/v3_1_prepare.json"
            assert args.code_commit == "b" * 40
            assert args.prepare_sha256 == hashlib.sha256(config.read_bytes()).hexdigest()
            assert args.registration_sha256 is None
        elif args.command == "picks":
            assert (args.packs, args.out) == ("v31/prepared/packs", "v31/picks-out")
            assert (args.attempt_id, args.registration_sha256) == ("4242-attempt-2", "a" * 64)
            # The printed receipt becomes the job's output.
            assert output.read_text(encoding="utf-8") == f"receipt_sha256={FAKE_RECEIPT}\n"
        elif args.command == "run-cell":
            assert (args.cell, args.attempt_id) == (cell, "4242-attempt-2")
            assert (args.packs, args.out) == ("v31/prepared/packs", "v31/cell-out")
            assert args.registration_sha256 == "a" * 64
            assert args.picks == (picks_dir if job == "run-v3" else None)
            assert args.legacy_data == ("v31/legacy-data" if job == "run-main" else None)
        elif args.command == "aggregate":
            assert (args.cells, args.out) == ("v31/cells", "v31/summary-out")
            assert (args.attempt_id, args.registration_sha256) == ("4242-attempt-2", "a" * 64)
        elif args.command == "dispatch-check":
            assert args.registration_sha256 == "a" * 64  # the dispatched pin
            assert args.report_only is False  # a registered run's check refuses
        elif args.command == "rehearsal-world":
            assert args.out == "v31/work"
            assert (
                output.read_text(encoding="utf-8") == f"registration_sha256={FAKE_REGISTRATION}\n"
            )
        elif args.command == "timing":
            config = folder / "checkout/config/v3_1_prepare.json"
            assert (args.part, args.code_commit) == ("picks", "b" * 40)
            assert args.prepare_sha256 == hashlib.sha256(config.read_bytes()).hexdigest()
            assert (args.scratch, args.out, args.repo) == ("v31/timing-scratch", "v31/timing", ".")
        elif args.command == "timing-close":
            assert (args.part, args.step_outcome, args.out) == ("picks", "success", "v31/timing")
            assert args.step_timeout_minutes == STEP_TIMEOUT
        else:
            assert args.command == "smoke" and (args.out, args.cells) == ("v31/smoke", None)
    assert sorted(seen, key=str) == sorted(
        [
            ("smoke", "smoke", None),
            ("plan", "dispatch-check", None),
            ("plan", "rehearsal-world", None),
            ("plan", "plan", "registered"),
            ("prepare", "prepare", "registered"),
            ("prepare", "prepare", "prepare-only"),
            ("picks", "picks", "registered"),
            ("run-main", "run-cell", "registered"),
            ("run-v3", "run-cell", "registered"),
            ("aggregate", "aggregate", "registered"),
            ("timing", "timing", None),
            ("timing", "timing-close", None),
        ],
        key=str,
    )


def test_the_picks_step_refuses_a_receipt_that_is_not_a_sha256(tmp_path: Path) -> None:
    step = _step("picks", "picks")
    result, _, output = _driver_step_run(step, tmp_path)
    assert result.returncode == 0
    assert FAKE_RECEIPT in output.read_text(encoding="utf-8")
    # A receipt of the wrong shape stops the job before it publishes anything.
    short = {"run": step["run"].replace("outcome_sha256", "outcome_sha25")}
    result, _, output = _driver_step_run(short, tmp_path / "short")
    assert result.returncode != 0
    assert output.read_text(encoding="utf-8") == ""


# --- step timeouts (Ruling F2) -----------------------------------------------------------


def _long_steps() -> dict[tuple[str, str], dict[str, Any]]:
    """Each long step, by job and name: the steps that run the driver's heavy work."""
    names = {
        ("prepare", "Prepare (registered or rehearsal)"),
        ("prepare", "Prepare (prepare-only)"),
        ("picks", "V3 selector picks"),
        ("run-main", "Run the cell"),
        ("run-v3", "Run the cell"),
        ("aggregate", "Aggregate"),
        ("timing", "Time the part"),
    }
    found = {(job, step.get("name")): step for job in JOBS for step in _steps(job)}
    return {key: found[key] for key in names}


def test_long_steps_time_out_inside_the_job_limit_so_the_scan_and_upload_still_run() -> None:
    jobs = _jobs()
    for (job, name), step in _long_steps().items():
        assert step["timeout-minutes"] == STEP_TIMEOUT, (job, name)
        assert STEP_TIMEOUT < jobs[job]["timeout-minutes"] == 360, (job, name)
    # Twenty-five minutes remain for the checkout, the setup, the downloads, the scans and
    # the upload, each of which takes a few minutes at most.
    assert 360 - STEP_TIMEOUT == 25
    # Every other driver step is short and has no step timeout of its own.
    long_steps = set(_long_steps())
    for job, step in _driver_steps():
        if (job, step.get("name")) not in long_steps:
            assert "timeout-minutes" not in step, (job, step.get("name"))
    # A timed-out step fails, and the steps that record the attempt still run after it.
    for job in ("picks", *MATRIX_JOBS):
        steps = _steps(job)
        (index,) = [i for i, s in enumerate(steps) if s.get("timeout-minutes") == STEP_TIMEOUT]
        outcomes = steps_that_run(job, failing=[index])
        assert outcomes[-2:] == ["success", "success"], job  # the scan, then the upload
    # timing-close is told the timing step's own timeout.
    ((_, close),) = [c for c in _driver_calls("timing") if c[0] == "timing-close"]
    assert int(_option(close, "--step-timeout-minutes")) == STEP_TIMEOUT


# --- the dispatch ref and the first job's gate (Ruling F6) --------------------------------


def test_the_header_and_the_plan_job_hold_the_dispatch_ref_rule() -> None:
    header = _header()
    assert (
        "a registered or timing run is dispatched from a ref whose tree is the code pin plus "
        "the registration artifacts only" in header
    )
    assert "a wrong ref fails in the first job" in header
    # The plan job is the first job of a registered run, and its job gate runs before any
    # other job: prepare, picks and the cells all need it.
    jobs = _jobs()
    for name in ("prepare", "picks", *MATRIX_JOBS, "aggregate", "status"):
        assert "plan" in _needs(jobs[name]), name
    steps = _steps("plan")
    gate = next(
        i for i, s in enumerate(steps) if re.search(r"v31_driver\.py plan\b", s.get("run", ""))
    )
    # Before it: only the dispatch check (a registered run's, Ruling R4-2) and a
    # rehearsal's world.
    assert all(
        "v31_driver.py" not in s.get("run", "")
        or "rehearsal-world" in s["run"]
        or "dispatch-check" in s["run"]
        for s in steps[:gate]
    )
    # The CLI documents it too.
    assert (
        "a ref" in v31_driver.__doc__
        and "code pin plus the registration artifacts" in v31_driver.__doc__
    )


# --- one dispatch per registration (Codex P1, PR #269 round 4; Ruling R4-2) --------------


def test_each_run_is_titled_with_its_mode_and_registration() -> None:
    """A second dispatch of a registration gets a new run id and attempt 1, so only the
    run's title, set by run-name, can tell it from the first: the driver looks for exactly
    the title a registered dispatch gets."""
    run_name = _workflow()["run-name"]
    assert run_name == "v31-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}"
    sha = "e" * 64
    evaluated = run_name.replace("${{ inputs.mode }}", "registered")
    assert evaluated.replace("${{ inputs.registration_sha256 }}", sha) == (
        v31_driver.registered_title(sha)
    )
    assert WORKFLOW.name == v31_driver.WORKFLOW_FILE  # the runs the check lists are these


def test_the_plan_job_refuses_a_second_dispatch_first_in_a_registered_run() -> None:
    steps = _steps("plan")
    names = [step.get("name") for step in steps]
    check = names.index("Refuse a second dispatch of the registration")
    step = steps[check]
    # A registered run's check, and a rehearsal's report-only one (owner decision v31-d21,
    # layer L3); never in smoke, prepare-only or timing.
    assert step["if"] == "${{ inputs.mode == 'registered' || inputs.mode == 'rehearsal' }}"
    assert step["env"] == TOKEN_ENV
    assert [line.strip() for line in step["run"].splitlines()] == [
        'if [ "$MODE" = registered ]; then',
        'python scripts/v31_driver.py dispatch-check --registration-sha256 "$REGISTRATION_SHA256"',
        'elif [ "$MODE" = rehearsal ]; then',
        "python scripts/v31_driver.py dispatch-check --report-only "
        '--registration-sha256 "$REGISTRATION_SHA256"',
        "else",
        'echo "::error::The dispatch check runs in registered and rehearsal mode only, not $MODE."',
        "exit 1",
        "fi",
    ]
    for mode in ("smoke", "prepare-only", "timing"):
        assert not _truth(_condition(step) or "", mode, {}), mode
        assert "plan" not in _ran(mode), mode
    # Its first driver step: after the registration's hash check and the install (it needs
    # Python), before the world, the job gate, the scan and any upload.
    installs = [i for i, s in enumerate(steps) if s.get("run", "").startswith("python -m pip")]
    assert names.index("Verify the registration against the dispatched SHA-256") < check
    assert max(installs) < check < names.index("Plan the run")
    assert check < _guard_steps("plan")[0]
    driver = [i for i, s in enumerate(steps) if "scripts/v31_driver.py" in s.get("run", "")]
    assert driver[0] == check
    # A refusal fails the plan job, so nothing after it runs: no world, no plan, no upload,
    # and none of the jobs that need the plan (the status job records it).
    outcomes = steps_that_run("plan", failing=[check])
    assert outcomes[check] == "failure"
    assert set(outcomes[check + 1 :]) == {"skipped"}
    assert _ran("registered", failing=["plan"]) == {"plan", "status"}
    # A rehearsal runs it too, report-only, first of its driver steps (before its world is
    # built); when GitHub cannot be read it fails the rehearsal's plan job the same way.
    assert steps_that_run("plan", mode="rehearsal")[check] == "success"
    outcomes = steps_that_run("plan", failing=[check], mode="rehearsal")
    assert outcomes[check] == "failure" and set(outcomes[check + 1 :]) == {"skipped"}
    assert check < names.index("Build the rehearsal world")
    assert _ran("rehearsal", failing=["plan"]) == {"plan", "status"}


@pytest.mark.parametrize(
    ("mode", "sha", "expected"),
    [
        ("registered", "a" * 64, ["dispatch-check", "--registration-sha256", "a" * 64]),
        # A rehearsal's registration_sha256 input is usually empty: its own title then.
        ("rehearsal", "", ["dispatch-check", "--report-only", "--registration-sha256", ""]),
        (
            "rehearsal",
            "b" * 64,
            ["dispatch-check", "--report-only", "--registration-sha256", "b" * 64],
        ),
        ("smoke", "", None),
        ("timing", "", None),
    ],
)
def test_the_dispatch_check_step_passes_report_only_in_a_rehearsal_alone(
    tmp_path: Path, mode: str, sha: str, expected: list[str] | None
) -> None:
    """The step in bash with a stub for the driver: a registered run's check refuses, a
    rehearsal's reports only (L3), on the registration_sha256 input its title carries
    (the workflow's env, the input itself, possibly empty); any other mode stops it."""
    (step,) = [
        s for s in _steps("plan") if s.get("name") == "Refuse a second dispatch of the registration"
    ]
    result, argv, _ = _driver_step_run(step, tmp_path, MODE=mode, REGISTRATION_SHA256=sha)
    if expected is None:
        assert result.returncode == 1 and argv == []
        assert "::error::The dispatch check runs in registered and rehearsal mode only" in (
            result.stdout
        )
        return
    assert result.returncode == 0, result.stderr
    assert argv == expected
    args = v31_driver.build_parser().parse_args(argv)
    assert (args.command, args.report_only) == ("dispatch-check", mode == "rehearsal")
    # The workflow-level env passes the input itself, never the world's registration.
    assert _workflow()["env"]["REGISTRATION_SHA256"] == "${{ inputs.registration_sha256 }}"
    assert "REGISTRATION_SHA256" not in step["env"]


def test_the_driver_knows_every_job_of_the_workflow() -> None:
    """L2 judges an earlier launch by its job records: the plan job, the always-running
    status job and every other job, each matched by name (a matrix job also by its matrix
    suffix). A job added to the workflow and not to the driver would count as unknown (fail
    closed); this keeps the two in step."""
    known = {
        v31_driver.PLAN_JOB,
        v31_driver.STATUS_JOB,
        *v31_driver.SKIPPED_JOBS,
        *v31_driver.SKIPPED_MATRIX_JOBS,
    }
    assert known == set(JOBS) == set(_jobs())
    matrix = {name for name, job in _jobs().items() if "matrix" in job.get("strategy", {})}
    assert set(v31_driver.SKIPPED_MATRIX_JOBS) == matrix
    assert _jobs()[v31_driver.STATUS_JOB]["if"].startswith("${{ always() ")


@pytest.mark.parametrize("failing", [["plan"], ["prepare"], ["picks"], ["run-main"], []])
def test_what_runs_after_a_failed_plan_is_exactly_what_l2_does_not_count(failing) -> None:
    """The workflow's control flow, as GitHub decides it (``jobs_that_run``), against L2's
    rule: a registered launch whose plan job failed ran the status job alone, so its job
    records (one per job, the matrix jobs under their bare names) are not counted; a launch
    that got past the plan job is."""
    results = jobs_that_run("registered", failing)
    records = [
        {
            "id": index,
            "run_id": 400,
            "run_attempt": 1,
            "name": name,
            "status": "completed",
            "conclusion": result,
        }
        for index, (name, result) in enumerate(results.items(), start=1)
    ]
    run = {"id": 400, "status": "completed", "run_attempt": 1}
    reason = v31_driver.launch_reason(run, records)
    if failing == ["plan"]:
        assert set(_ran("registered", failing)) == {"plan", "status"}
        assert reason is None
    else:
        assert reason is not None


def test_the_aggregate_step_holds_the_token_to_check_again() -> None:
    (step,) = [s for s in _steps("aggregate") if s.get("name") == "Aggregate"]
    assert step["env"] == TOKEN_ENV
    # The driver decides by mode: a registered aggregate checks, a rehearsal's never does
    # (tests/test_v31_driver_cli.py); the step itself runs in both.
    assert "if" not in step


def test_the_header_says_a_second_dispatch_is_refused_and_why() -> None:
    header = _header()
    assert "A second dispatch of a registration is refused too" in header
    assert "new run id and attempt 1" in header
    assert "fails the plan and leaves the verdict incomplete" in header
    # Ruling R5-2: what a later dispatch can and cannot do to an earlier one.
    assert "never voids" not in header
    assert (
        "A dispatch created a second or more later never counts against an earlier one, but "
        "two dispatches created in the same second void each other, and one created while an "
        "earlier run's plan or aggregate is paging through the runs can make that listing "
        "inconsistent, which fails that plan or leaves that verdict incomplete (fail closed). "
        "The operating rule above forbids both."
    ) in header
    assert "holds no stored credentials" in header
    # The Aggregate step holds the token in a rehearsal too, unused there; the dispatch
    # check holds it in a rehearsal to check report-only (owner decision v31-d21).
    assert (
        "Two steps get the job's own token, with read access to this repository's workflow "
        "runs and nothing more: the plan job's dispatch check (a registered run's, and a "
        "rehearsal's report-only one), and the Aggregate step, which holds it in a rehearsal "
        "too, where the driver does not use it."
    ) in header
    # Owner decision v31-d21: a launch that did nothing does not count, and a transient
    # GitHub error is retried before the check fails closed.
    assert "queued, running or finished, fails the plan and leaves the verdict incomplete" in (
        header
    )
    assert "whatever its status" not in header
    assert (
        "A launch that stopped at the plan job with nothing run does not count: GitHub's "
        "records must show it completed, its plan job failed and every later job skipped in "
        "every attempt (the status job aside), and anything else counts."
    ) in header
    assert (
        "Transient GitHub errors (no reply, a timeout, a reply cut short, HTTP 5xx or 429, a "
        "rate limit, a secondary rate limit's 403 included, a run not yet listed) are "
        "retried, five attempts over about five minutes, before the check fails closed; the "
        "whole check stops at a 20-minute deadline, and no later than 25 minutes after its "
        "job started (the job's first step records the start), so a long outage fails the "
        "plan job (not counted) instead of running into its 30-minute timeout, which cancels "
        "it (counted). A rehearsal runs the same check report-only, on its own title, to "
        "prove it against GitHub, and also reads its own run's job listing, so even the "
        "first rehearsal proves the jobs endpoint."
    ) in header


def test_the_dispatch_checks_deadline_ends_inside_its_jobs_timeout() -> None:
    """A plan job run into its timeout is cancelled, and a cancelled plan counts (L2), so
    the check's deadline is budgeted from the job's start, which the job's first step
    records (Codex P1 on PR #281): each job's budget ends at least five minutes before its
    timeout-minutes, however long the checkout, setup and installs took. The aggregate's
    check reads the same record against its own job's budget."""
    jobs = _jobs()
    margin = 5 * 60
    assert jobs["plan"]["timeout-minutes"] == 30
    assert v31_driver.PLAN_JOB_BUDGET + margin <= jobs["plan"]["timeout-minutes"] * 60
    assert jobs["aggregate"]["timeout-minutes"] == 360
    assert v31_driver.AGGREGATE_JOB_BUDGET + margin <= jobs["aggregate"]["timeout-minutes"] * 60
    assert v31_driver.DISPATCH_DEADLINE == 20 * 60 <= v31_driver.PLAN_JOB_BUDGET
    assert v31_driver.JOB_STARTED == "V31_JOB_STARTED"
    for name in CHECKING_JOBS:
        assert _steps(name)[0] == JOB_START_STEP, name
    (check,) = [s for s in _steps("plan") if "dispatch-check" in s.get("run", "")]
    assert "timeout-minutes" not in check  # the driver's deadline, not a step timeout, ends it


def test_the_job_start_step_records_an_epoch_second(tmp_path: Path) -> None:
    env_file = tmp_path / "github-env"
    env_file.write_text("", encoding="utf-8")
    before = int(time.time())
    result = _run_step(JOB_START_STEP["run"], tmp_path, {"GITHUB_ENV": env_file.as_posix()})
    after = int(time.time())
    assert result.returncode == 0, result.stderr
    (line,) = env_file.read_text(encoding="utf-8").splitlines()
    name, value = line.split("=", 1)
    assert name == "V31_JOB_STARTED" and re.fullmatch(r"[1-9][0-9]*", value)
    assert before <= int(value) <= after


# --- the status job (Ruling F11) ---------------------------------------------------------


def test_the_status_job_records_every_job_result_even_when_aggregate_is_skipped(
    tmp_path: Path,
) -> None:
    jobs = _jobs()
    status = jobs["status"]
    assert set(_needs(status)) == {"plan", "prepare", "picks", "run-main", "run-v3", "aggregate"}
    assert (
        status["if"]
        == "${{ always() && (inputs.mode == 'registered' || inputs.mode == 'rehearsal') }}"
    )
    # A failed prepare skips the aggregate; the status job still runs.
    ran = jobs_that_run("registered", failing=["prepare"])
    assert (ran["aggregate"], ran["status"]) == ("skipped", "success")
    assert jobs_that_run("registered", failing=["plan"])["status"] == "success"
    assert "status" not in _ran("smoke") | _ran("prepare-only") | _ran("timing")
    upload = _upload("status", f"{STATUS_NAME}-attempt-${{{{ github.run_attempt }}}}")
    assert upload["path"] == "v31/status" and upload["if-no-files-found"] == "error"
    # Its script, run for real on a failed prepare's results.
    (step,) = [s for s in _steps("status") if "status.json" in s.get("run", "")]
    env = {name: "" for name in step["env"]}
    env.update(
        {
            "MODE": "registered",
            "PLAN_RESULT": "success",
            "PREPARE_RESULT": "failure",
            "PICKS_RESULT": "skipped",
            "RUN_MAIN_RESULT": "skipped",
            "RUN_V3_RESULT": "skipped",
            "AGGREGATE_RESULT": "skipped",
            "PLANNED_SHA256": "e" * 64,
            "V3_CELLS": json.dumps(["a"] * 4),
            "MAIN_CELLS": json.dumps(["b"] * 212),
            "RUN_ID": "4242",
            "RUN_ATTEMPT": "1",
        }
    )
    real = shlex.quote(Path(sys.executable).as_posix())
    result = _run_step(step["run"], tmp_path, env, f'python() {{ {real} "$@"; }}\n')
    assert result.returncode == 0, result.stderr
    document = json.loads((tmp_path / "v31/status/status.json").read_bytes())
    assert document == {
        "schema": "v3.1-status-1",
        "mode": "registered",
        "run_id": "4242",
        "run_attempt": "1",
        "jobs": {
            "plan": "success",
            "prepare": "failure",
            "picks": "skipped",
            "run-main": "skipped",
            "run-v3": "skipped",
            "aggregate": "skipped",
        },
        "aggregate_ran": False,
        "registration_sha256": "e" * 64,
        "v3_cells": 4,
        "main_cells": 212,
        "picks_receipt_sha256": None,
    }


# --- timing (Ruling F4) -------------------------------------------------------------------


def test_timing_mode_runs_three_parts_and_uploads_only_their_timing_files() -> None:
    assert _ran("timing") == {"timing"}
    job = _jobs()["timing"]
    assert job["strategy"] == {"fail-fast": False, "matrix": {"part": ["prepare", "picks", "cell"]}}
    assert list(job["strategy"]["matrix"]["part"]) == list(v31_driver.TIMING_PARTS)
    ((_, timed), (_, close)) = _driver_calls("timing")
    assert timed[0] == "timing" and close[0] == "timing-close"
    assert _option(timed, "--part") == _option(close, "--part") == "$PART"
    assert _option(timed, "--out") == _option(close, "--out") == "v31/timing"
    assert _option(timed, "--scratch") == "v31/timing-scratch"
    assert _option(timed, "--code-commit") == "$CODE_COMMIT"
    # Only v31/timing is uploaded, never the scratch data or results.
    (upload,) = _uploads("timing")
    assert upload["with"]["path"] == "v31/timing"
    assert "scratch" not in json.dumps(upload)
    # Gated like prepare-only: the commit is checked first, the config hashed from the checkout.
    script = _step("timing", "timing")["run"]
    assert 'prepare_sha256="$(sha256sum config/v3_1_prepare.json' in script


def test_a_timing_part_killed_at_its_step_timeout_still_uploads_what_it_measured() -> None:
    steps = _steps("timing")
    (timed,) = [i for i, s in enumerate(steps) if s.get("id") == "timing"]
    (close,) = [i for i, s in enumerate(steps) if "timing-close" in s.get("run", "")]
    (guard,) = _guard_steps("timing")
    (upload,) = [i for i, s in enumerate(steps) if _action(s).startswith("actions/upload")]
    assert timed < close < guard == upload - 1
    assert steps[close]["env"]["OUTCOME"] == "${{ steps.timing.outcome }}"
    for failing in ([timed], [timed - 1]):  # the part itself, or a step before it
        outcomes = steps_that_run("timing", failing=failing, mode="timing")
        assert (outcomes[close], outcomes[guard], outcomes[upload]) == ("success",) * 3
    # A failed scan uploads nothing, and neither does one that was cancelled or skipped.
    assert steps_that_run("timing", failing=[guard], mode="timing")[upload] == "skipped"
    for scan in ("cancelled", "skipped"):
        outcomes = steps_that_run("timing", forced={guard: scan}, mode="timing")
        assert (outcomes[guard], outcomes[upload]) == (scan, "skipped")
        outcomes = steps_that_run("timing", failing=[timed], forced={guard: scan}, mode="timing")
        assert outcomes[upload] == "skipped"


# --- the plan step, for real ------------------------------------------------------------


@dataclass(frozen=True)
class RegisteredWorld:
    repo: Path
    registration_sha256: str


@pytest.fixture(scope="module")
def registered_world(tmp_path_factory: pytest.TempPathFactory) -> RegisteredWorld:
    """What Task 11 commits, in miniature: a repository holding config/v3_1_registration.json
    and its run-manifest, with all 42 arms and 216 cells, its adapter pins read from module
    stubs at its code pin, committed with the V3.1 trial's completion on top of that code
    pin, which sits on the trial's registration event (the trial gate, Ruling R4-1). Its
    prepare config holds the owner's plan (``OWNER_PLAN``: W1 on ten coins, W0 on eight),
    which a registered run requires (``v31_driver.plan_gate``), on the smoke world's files,
    with its end-2024 FX record. Its pack pins name no pack: the plan step and an aggregate
    with nothing downloaded read none."""
    root = tmp_path_factory.mktemp("v31-workflow") / "world"
    root.mkdir()
    with v31_smoke.stand_ins():
        world = v31_smoke.build_world(root, extra_files=MODULES, trial=True)
    path = world.repo / v31_driver.PREPARE_CONFIG
    document = json.loads(path.read_bytes())
    document["windows"] = [
        {"id": w.id, "start_ms": w.start_ms, "end_ms": w.end_ms, "symbols": sorted(w.symbols)}
        for w in OWNER_PLAN.windows
    ]
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="ascii", newline="\n")
    world = replace(world, prepare=load_prepare_config(path))
    ids = [window.id for window in world.prepare.windows]
    no_pack = {
        "window_packs": {wid: hashlib.sha256(f"no pack {wid}".encode()).hexdigest() for wid in ids},
        "v3_pack_sha256": hashlib.sha256(b"no V3 pack").hexdigest(),
        "skipped_hours": {wid: {"hours": []} for wid in ids},
    }
    pins = adapter_pins(world.repo, world.head)
    reg, sha = v31_smoke.register(world, no_pack, code_pin=world.head, adapter_pins=pins)
    v31_smoke.complete_trial(
        world.repo, code_pin=world.head, config_sha256=sha, manifest_sha256=reg.run_manifest_pin
    )
    v31_smoke.commit_all(world.repo, "the registration (synthetic)")
    return RegisteredWorld(world.repo, sha)


def _real_step(script: str) -> tuple[str, str]:
    """``script`` with the driver at its absolute path and ``python`` this interpreter, run
    from anywhere: (the script, the bash prelude)."""
    driver = (ROOT / "scripts/v31_driver.py").as_posix()
    real = shlex.quote(Path(sys.executable).as_posix())
    return script.replace("scripts/v31_driver.py", driver), f'python() {{ {real} "$@"; }}\n'


def _outputs(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines())


def test_the_plan_step_gates_and_splits_the_registered_cells_into_4_and_212(
    registered_world: RegisteredWorld, tmp_path: Path
) -> None:
    repo = registered_world.repo
    registration = load_registration(
        repo / "config/v3_1_registration.json",
        repo / "config/v3_1_run_manifest.json",
        repo_root=repo,
    )
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    script, prelude = _real_step(_step("plan", "cells")["run"])
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    env = {
        "GITHUB_OUTPUT": output.as_posix(),
        "RUNNER_TEMP": runner_temp.as_posix(),
        "PYTHONPATH": str(ROOT / "src"),
        "MODE": "registered",
        "REPO": repo.as_posix(),
        "REGISTRATION_SHA256": registered_world.registration_sha256,
        "REHEARSAL_CELLS": "",
    }
    result = _run_step(script, tmp_path, env, prelude)
    assert result.returncode == 0, result.stderr
    lines = _outputs(output)
    assert set(lines) == {"v3_cells", "main_cells", "registration_sha256"}
    v3_cells, main_cells = json.loads(lines["v3_cells"]), json.loads(lines["main_cells"])
    # Only the selector waits for the picks (Ruling F7): 4 cells; the other 212, the six
    # long-only V3 rules' 24 among them, run in the main matrix.
    assert (len(v3_cells), len(main_cells)) == (4, 212)
    assert {c.cell_id for c in registration.cells if c.arm == "unchanged_v3_selector"} == set(
        v3_cells
    )
    assert {*v3_cells, *main_cells} == {cell.cell_id for cell in registration.cells}
    assert sum("unchanged_v3_r" in c for c in main_cells) == 24
    assert lines["registration_sha256"] == registered_world.registration_sha256
    # GitHub reads the output as one line per array.
    assert lines["main_cells"].startswith("[") and "\n" not in lines["main_cells"]
    # A wrong pin fails the first job (the job gate).
    output.write_text("", encoding="utf-8")
    result = _run_step(script, tmp_path, {**env, "REGISTRATION_SHA256": "0" * 64}, prelude)
    assert result.returncode != 0 and "job gate refused" in result.stderr
    assert output.read_text(encoding="utf-8") == ""


# --- the rehearsal: the registered job graph's steps, for real (Ruling F3) ---------------


def test_rehearsal_mode_runs_the_same_job_graph_as_a_registered_run() -> None:
    assert _ran("rehearsal") == _ran("registered") == set(GRAPH)
    for failing in (["prepare"], ["picks"], ["run-main"], ["plan"]):
        assert _ran("rehearsal", failing) == _ran("registered", failing), failing
    # Every gated job unpacks the plan job's world before its first scan, and in a
    # rehearsal alone; the plan job builds and uploads it.
    for name in ("prepare", "picks", *MATRIX_JOBS, "aggregate"):
        steps = _steps(name)
        (download,) = [
            i for i, s in enumerate(steps) if s.get("with", {}).get("name") == "v31-rehearsal-world"
        ]
        (unpack,) = [i for i, s in enumerate(steps) if "tar -xf" in s.get("run", "")]
        for index in (download, unpack):
            assert steps[index]["if"] == "${{ inputs.mode == 'rehearsal' }}", name
        assert download < unpack < _guard_steps(name)[0], name
        assert steps[download]["with"]["path"] == "v31/world-download"
    world = _step("plan", "world")
    assert world["if"] == "${{ inputs.mode == 'rehearsal' }}"
    assert _upload("plan", "v31-rehearsal-world")["path"] == "v31/rehearsal-world.tar"
    # The plan step takes the world's registration in a rehearsal, the dispatched one else.
    assert _step("plan", "cells")["env"]["REGISTRATION_SHA256"] == (
        "${{ inputs.mode == 'rehearsal' && steps.world.outputs.registration_sha256 "
        "|| inputs.registration_sha256 }}"
    )
    # The registration's hash check runs in a registered run alone; the dispatch check in a
    # rehearsal too, report-only on the rehearsal's own title (owner decision v31-d21).
    verify = _checked_out("plan")[1]
    assert verify["if"] == "${{ inputs.mode == 'registered' }}"
    assert verify["name"] == "Verify the registration against the dispatched SHA-256"
    (check,) = [s for s in _steps("plan") if "dispatch-check" in s.get("run", "")]
    assert check["if"] == "${{ inputs.mode == 'registered' || inputs.mode == 'rehearsal' }}"
    assert "dispatch-check --report-only" in check["run"]
    # A rehearsal never takes a fetching path: its prepare is the registered step with
    # --mode rehearsal (which the driver runs without any transport), never prepare-only.
    steps = _steps("prepare")
    outcomes = dict(
        zip(
            (s.get("name") for s in steps), steps_that_run("prepare", mode="rehearsal"), strict=True
        )
    )
    assert outcomes["Prepare (registered or rehearsal)"] == "success"
    assert outcomes["Prepare (prepare-only)"] == outcomes["Check the code commit"] == "skipped"
    assert outcomes["Unpack the rehearsal world"] == "success"
    # Nor does the timing job run in a rehearsal.
    assert "timing" not in _ran("rehearsal")


def test_the_rehearsal_steps_run_end_to_end_offline(tmp_path: Path) -> None:
    """The rehearsal's own steps, in bash with the real driver, from the world's build to
    the verdict: plan (the world, the gate, the matrices), prepare, picks, run-v3's picks
    check and its cell, run-main's cells and aggregate. Each job runs in its own folder; the
    artifacts move between them as download-artifact v4 lays them out (by name: into the
    path; by pattern: each into its own folder named for it), which is what the dispatched
    rehearsal checks on GitHub. Nothing touches the network."""
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    base = {
        "RUNNER_TEMP": runner_temp.as_posix(),
        "PYTHONPATH": str(ROOT / "src"),
        "MODE": "rehearsal",
        "REPO": "v31/work/repo",
        "REHEARSAL_CELLS": "6",
    }

    def step_run(job: str, step: dict[str, Any], cwd: Path, **env: str) -> dict[str, str]:
        cwd.mkdir(parents=True, exist_ok=True)
        output = cwd / "github-output"
        output.write_text("", encoding="utf-8")
        script, prelude = _real_step(step["run"])
        script = script.replace("${{ github.run_id }}", "4242")
        script = script.replace("${{ github.run_attempt }}", "1")
        result = _run_step(
            script, cwd, {**base, "GITHUB_OUTPUT": output.as_posix(), **env}, prelude
        )
        assert result.returncode == 0, (job, step.get("name"), result.stderr[-3000:])
        return _outputs(output)

    def named(job: str, name: str) -> dict[str, Any]:
        (step,) = [s for s in _steps(job) if s.get("name") == name]
        return step

    def unpack(cwd: Path) -> None:  # the world artifact, downloaded by name, then unpacked
        (cwd / "v31/world-download").mkdir(parents=True)
        shutil.copyfile(tarball, cwd / "v31/world-download/rehearsal-world.tar")
        step_run("any", named("prepare", "Unpack the rehearsal world"), cwd)

    # plan
    plan_dir = tmp_path / "pl"
    world = step_run("plan", _step("plan", "world"), plan_dir)
    tarball = plan_dir / "v31/rehearsal-world.tar"
    assert tarball.is_file()
    sha = world["registration_sha256"]
    planned = step_run("plan", _step("plan", "cells"), plan_dir, REGISTRATION_SHA256=sha)
    assert planned["registration_sha256"] == sha
    v3_cells, main_cells = json.loads(planned["v3_cells"]), json.loads(planned["main_cells"])
    assert (len(v3_cells), len(main_cells)) == (1, 5)
    # A fixed long-only V3 rule goes through run-main's step, without picks (Ruling C1).
    assert "w1.unchanged_v3_r1_long_only.native.c1.research" in main_cells
    gated = {"REGISTRATION_SHA256": sha}  # each later job's env, from the plan's output

    # prepare
    prepare_dir = tmp_path / "pr"
    unpack(prepare_dir)
    step_run("prepare", named("prepare", "Prepare (registered or rehearsal)"), prepare_dir, **gated)
    prepared = json.loads((prepare_dir / "v31/out/prepare.json").read_bytes())
    assert prepared["mode"] == "rehearsal" and prepared["registration_sha256"] == sha

    def download_packs(cwd: Path) -> None:  # v31-packs by name into v31/prepared
        shutil.copytree(prepare_dir / "v31/out", cwd / "v31/prepared")

    # picks
    picks_dir = tmp_path / "pk"
    download_packs(picks_dir)
    unpack(picks_dir)
    receipt = step_run("picks", _step("picks", "picks"), picks_dir, **gated)["receipt_sha256"]

    # aggregate's downloads, by pattern: each artifact in its own folder.
    cells = tmp_path / "ag/v31/cells"
    shutil.copytree(picks_dir / "v31/picks-out", cells / "v3-picks-attempt-1")

    # run-v3: the picks downloaded by pattern, checked against the receipt, then the cell.
    for index, cell in enumerate(v3_cells):
        job_dir = tmp_path / f"v{index}"
        download_packs(job_dir)
        shutil.copytree(picks_dir / "v31/picks-out", job_dir / "v31/picks/v3-picks-attempt-1")
        unpack(job_dir)
        found = step_run(
            "run-v3", _step("run-v3", "picks_dir"), job_dir, PICKS_RECEIPT_SHA256=receipt
        )
        step_run(
            "run-v3",
            named("run-v3", "Run the cell"),
            job_dir,
            CELL=cell,
            PICKS_DIR=found["dir"],
            **gated,
        )
        shutil.copytree(job_dir / "v31/cell-out", cells / f"cell-{cell}-attempt-1")

    # run-main: the packs and the legacy dataset (by name into v31/legacy-data).
    for index, cell in enumerate(main_cells):
        job_dir = tmp_path / f"m{index}"
        download_packs(job_dir)
        shutil.copytree(prepare_dir / "v31/work/legacy", job_dir / "v31/legacy-data")
        unpack(job_dir)
        step_run("run-main", named("run-main", "Run the cell"), job_dir, CELL=cell, **gated)
        shutil.copytree(job_dir / "v31/cell-out", cells / f"cell-{cell}-attempt-1")

    # aggregate
    aggregate_dir = tmp_path / "ag"
    unpack(aggregate_dir)
    step_run("aggregate", named("aggregate", "Aggregate"), aggregate_dir, **gated)
    verdict = json.loads((aggregate_dir / "v31/summary-out/summary/verdict.json").read_bytes())
    completed = {c for c, read in verdict["cells"].items() if read["state"] == "completed"}
    assert completed == {*v3_cells, *main_cells}
    assert verdict["v3_picks"]["state"] == "completed"
    assert verdict["run"]["run_id"] == "4242" and verdict["run"]["reruns"] == []
    assert verdict["status"] == "incomplete"  # six of 216 cells
    assert verdict["mode"] == "rehearsal"


def _run_real_step(
    step: dict[str, Any], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """A workflow step in bash with the real driver, the run id and attempt filled in as
    GitHub does (``github.run_id`` 4242, ``github.run_attempt`` 1)."""
    cwd.mkdir(parents=True, exist_ok=True)
    script, prelude = _real_step(step["run"])
    script = script.replace("${{ github.run_id }}", "4242")
    script = script.replace("${{ github.run_attempt }}", "1")
    return _run_step(script, cwd, env, prelude)


def _named_step(job: str, name: str) -> dict[str, Any]:
    (step,) = [s for s in _steps(job) if s.get("name") == name]
    return step


@pytest.mark.parametrize("mode", ["registered", "rehearsal"])
def test_aggregate_with_no_artifact_downloaded_is_incomplete_and_names_every_cell(
    registered_world: RegisteredWorld, tmp_path: Path, mode: str
) -> None:
    """Every cell job and the picks job failed before they wrote a folder, so their uploads
    only warned and the pattern downloads matched nothing: download-artifact then creates no
    ``v31/cells``. The aggregate job's own steps, in bash with the real driver, still end in
    an incomplete verdict that names all 216 cells and in a summary to upload. Without the
    step that makes the folder the aggregation refuses. The rehearsal's aggregate takes the
    same path, on the world its plan job built."""
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    env = {
        "RUNNER_TEMP": runner_temp.as_posix(),
        "PYTHONPATH": str(ROOT / "src"),
        "MODE": mode,
        "REHEARSAL_CELLS": "",
    }
    job = tmp_path / "ag"  # the aggregate job's workspace: no download made anything in it
    job.mkdir()
    if mode == "registered":
        repo = registered_world.repo
        env |= {
            "REPO": repo.as_posix(),
            "REGISTRATION_SHA256": registered_world.registration_sha256,
        }
    else:
        plan = tmp_path / "pl"
        output = plan / "github-output"
        plan.mkdir()
        output.write_text("", encoding="utf-8")
        built = _run_real_step(
            _step("plan", "world"), plan, {**env, "GITHUB_OUTPUT": output.as_posix()}
        )
        assert built.returncode == 0, built.stderr[-3000:]
        (job / "v31/world-download").mkdir(parents=True)  # the world, downloaded by name
        shutil.copyfile(
            plan / "v31/rehearsal-world.tar", job / "v31/world-download/rehearsal-world.tar"
        )
        env |= {
            "REPO": "v31/work/repo",
            "REGISTRATION_SHA256": _outputs(output)["registration_sha256"],
        }
        unpacked = _run_real_step(_named_step("aggregate", "Unpack the rehearsal world"), job, env)
        assert unpacked.returncode == 0, unpacked.stderr[-3000:]
        repo = job / "v31/work/repo"
    registration = load_registration(
        repo / "config/v3_1_registration.json",
        repo / "config/v3_1_run_manifest.json",
        repo_root=repo,
    )
    cell_ids = {cell.cell_id for cell in registration.cells}
    assert len(cell_ids) == 216

    aggregate_step = _named_step("aggregate", "Aggregate")
    assert not (job / "v31/cells").exists()
    refused = _run_real_step(aggregate_step, job, env)
    assert refused.returncode != 0 and "cells directory" in refused.stderr
    assert not (job / "v31/summary-out/summary").exists()

    made = _run_real_step(_named_step("aggregate", "Create the cells folder"), job, env)
    assert made.returncode == 0, made.stderr
    assert (job / "v31/cells").is_dir() and not list((job / "v31/cells").iterdir())
    result = _run_real_step(aggregate_step, job, env)
    assert result.returncode == 0, result.stderr[-3000:]
    summary = job / "v31/summary-out/summary"
    verdict = json.loads((summary / "verdict.json").read_bytes())
    assert verdict["status"] == "incomplete" and verdict["mode"] == mode
    assert {cell: read["state"] for cell, read in verdict["cells"].items()} == dict.fromkeys(
        cell_ids, "missing"
    )
    assert verdict["v3_picks"]["state"] == "missing"
    # Every cell is named missing in the summary; the verdict's reasons name each W1 cell
    # (the W0 cells are reported, not judged) and the picks job.
    text = (summary / "summary.md").read_text(encoding="utf-8")
    reasons = verdict["cell_incomplete_reasons"]
    missing = "no artifact: not run, or failed before its claim"
    w1 = {cell.cell_id for cell in registration.cells if not cell.reported_only}
    assert 0 < len(w1) < len(cell_ids)
    assert sorted(reasons) == sorted(f"{name}: {missing}" for name in (*w1, "v3_picks"))
    for cell_id in sorted(cell_ids):
        assert f"`{cell_id}` | missing" in text, cell_id
    # A registered aggregate checks for another dispatch of its registration (Ruling R4-2):
    # here, without the runner's variables, it cannot rule one out, and says so; a rehearsal
    # dispatches no registration and checks nothing.
    dispatches = verdict["run"]["other_dispatches"]
    if mode == "registered":
        (reason,) = dispatches
        assert reason.startswith("another dispatch of this registration could not be ruled out")
        assert "GITHUB_TOKEN is not set" in reason
    else:
        assert dispatches == []


def _name_for(template: str, mode: str) -> str:
    """An artifact name as GitHub evaluates it for a dispatch of ``mode``: each
    ``${{ inputs.mode == 'rehearsal' && 'A' || 'B' }}`` becomes A or B, and the run
    attempt 1."""

    def choose(match: re.Match[str]) -> str:
        rehearsal, other = match.groups()
        return rehearsal if mode == "rehearsal" else other

    pattern = r"\$\{\{ inputs\.mode == 'rehearsal' && '([^']+)' \|\| '([^']+)' \}\}"
    named = re.sub(pattern, choose, template)
    return named.replace("${{ github.run_attempt }}", "1")


def test_a_rehearsals_summary_and_status_never_take_a_registered_runs_names() -> None:
    """Ruling C2: a synthetic rehearsal's verdict could read PASS, so its summary and its
    status are uploaded under names of their own; the verdict itself names its mode
    (aggregate --mode, tests/test_v31_aggregate.py)."""
    (summary,) = _uploads("aggregate")
    status = next(s for s in _uploads("status"))
    expected = {
        "registered": ("v31-summary-attempt-1", "v31-status-attempt-1"),
        "rehearsal": ("v31-rehearsal-summary-attempt-1", "v31-rehearsal-status-attempt-1"),
    }
    for mode, names in expected.items():
        got = (_name_for(summary["with"]["name"], mode), _name_for(status["with"]["name"], mode))
        assert got == names, mode
    # The aggregate step passes the run's mode, so verdict.json and summary.md name it.
    ((_, call),) = _driver_calls("aggregate")
    assert _option(call, "--mode") == "$MODE"
    # Every other upload name is the same in both modes or belongs to one mode alone.
    for job in JOBS:
        for step in _uploads(job):
            if step not in (summary, status):
                assert "inputs.mode" not in step["with"]["name"], (job, step["with"]["name"])
