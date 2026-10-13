"""The v31-run workflow (Task 10b): its triggers, permissions, job graph and artifact layout.

The registered experiment runs once, on GitHub's machines, through this workflow, so its
safety properties are tested as structure: the tests parse the YAML and never call GitHub.
Three kinds of test:

- structure: triggers, permissions, checkouts, concurrency, pins, matrices, artifacts;
- control flow: ``jobs_that_run`` follows each job's ``needs`` and ``if`` for a dispatch
  mode (and for a failing job), the way GitHub decides which jobs run;
- steps run for real, in bash and offline: the registration check, the 2025 guard, the
  picks check and the plan step (on a synthetic registration with all 216 cells).

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
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v31_driver  # noqa: E402
import v31_smoke  # noqa: E402

from crypto_grid_bot.combined.driver.registration import load_registration  # noqa: E402

WORKFLOW = ROOT / ".github/workflows/v31-run.yml"
QUALITY = ROOT / ".github/workflows/quality.yml"

JOBS = ("smoke", "plan", "prepare", "picks", "run-main", "run-v3", "aggregate")
DATA_JOBS = tuple(job for job in JOBS if job != "plan")  # each fetches, downloads or makes data
MATRIX_JOBS = ("run-main", "run-v3")
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
    status function (here ``!cancelled()``), and an ``if`` without one also requires every
    needed job to have succeeded."""
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
            runs = _truth(condition, mode, needs) and (
                "cancelled()" in str(jobs[name]["if"]) or needs_succeeded
            )
        results[name] = ("failure" if name in set(failing) else "success") if runs else "skipped"
    return results


def _ran(mode: str, failing: Iterable[str] = ()) -> set[str]:
    return {name for name, result in jobs_that_run(mode, failing).items() if result != "skipped"}


def steps_that_run(job: str, failing: Iterable[int] = ()) -> list[str]:
    """Each step of ``job``'s outcome (``success``, ``failure`` or ``skipped``) when the steps
    at the indexes in ``failing`` fail as they run (the job being otherwise a registered
    dispatch). A step without an ``if`` runs only while every earlier step succeeded; one
    whose ``if`` calls ``always()`` or ``!cancelled()`` is decided by its expression alone."""
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
            runs = _truth(text, "registered", {}, outcomes) and (status_aware or not failed)
        outcome = ("failure" if index in set(failing) else "success") if runs else "skipped"
        failed = failed or outcome == "failure"
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


def _run_step(
    script: str, cwd: Path, env: dict[str, str], prelude: str = ""
) -> subprocess.CompletedProcess[str]:
    """``script`` as GitHub runs a bash step (``-e -o pipefail``), with ``env`` added."""
    return subprocess.run(
        [_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", prelude + script],
        cwd=cwd,
        env={**os.environ, **env},
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


def test_the_only_trigger_is_workflow_dispatch_with_the_three_inputs() -> None:
    triggers = _triggers(_workflow())
    assert set(triggers) == {"workflow_dispatch"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"mode", "registration_sha256", "code_commit"}
    assert inputs["mode"]["type"] == "choice"
    assert inputs["mode"]["options"] == ["smoke", "prepare-only", "registered"]
    assert inputs["registration_sha256"]["type"] == "string"
    assert inputs["code_commit"]["type"] == "string"
    # The first two inputs belong to one mode each, so neither can be required for all.
    assert not inputs["registration_sha256"].get("required")
    assert not inputs["code_commit"].get("required")


def test_workflow_has_the_2025_guard_and_no_write_permissions() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        assert "permissions" not in job, f"{name} sets its own permissions"
    assert not re.search(r"\bwrite\b", json.dumps(workflow))
    for name in DATA_JOBS:
        assert _guard_steps(name), f"{name} has no 2025 guard step"
    assert _guard_steps("plan") == []  # it reads the registration and fetches nothing


def test_permissions_are_exactly_contents_read_and_no_job_widens_them() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert all("permissions" not in job for job in workflow["jobs"].values())
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


def test_every_job_checks_out_the_full_history_without_credentials() -> None:
    # changed_since(code_pin) needs the code commit's history; credentials stay out of .git.
    for name in JOBS:
        first = _steps(name)[0]
        assert _action(first) == "actions/checkout@v4", name
        assert first["with"] == {"fetch-depth": 0, "persist-credentials": False}, name
        assert [_action(s) for s in _steps(name)].count("actions/checkout@v4") == 1, name


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
    assert "refuses the duplicate" in header
    assert "Do not re-run a registered run" in header
    assert not re.search(r"can be re-run|re-run from the Actions page", header)
    # The summaries are named for their attempt, so re-running aggregate alone is harmless.
    assert "v31-summary-attempt-<n>" in header and "v31-smoke-summary-attempt-<n>" in header


def test_no_secret_is_referenced() -> None:
    # The public archives need none; the checkout is read-only with no stored credentials.
    parsed = json.dumps(_workflow())
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
        (setup,) = _find_steps(name, "actions/setup-python@v5")
        assert setup["with"]["python-version"] == quality_python == "3.12", name
        assert setup["with"]["cache-dependency-path"] == "requirements-dev.lock", name
        installs = [s["run"] for s in _steps(name) if s.get("run", "").startswith("python -m pip")]
        assert installs == [
            "python -m pip install --upgrade pip",
            "python -m pip install -r requirements-dev.lock",
            "python -m pip install -e . --no-deps",
        ], name
    allowed = {
        "actions/checkout@v4",
        "actions/setup-python@v5",
        "actions/upload-artifact@v4",
        "actions/download-artifact@v4",
    }
    used = {_action(s) for job in _jobs().values() for s in job["steps"] if "uses" in s}
    assert used <= allowed, used - allowed


# --- the job graph ----------------------------------------------------------------------


def test_prepare_only_mode_runs_only_prepare() -> None:
    assert _ran("prepare-only") == {"prepare"}
    calls = {tokens[2]: tokens for _, tokens in _driver_calls("prepare")}  # by --mode
    assert set(calls) == {"registered", "prepare-only"}
    only = calls["prepare-only"]
    assert _option(only, "--code-commit") == "$CODE_COMMIT"
    assert "--prepare-sha256" in only
    assert "--registration-sha256" not in only
    assert "--code-commit" not in calls["registered"]
    only_steps = [s for s in _steps("prepare") if "prepare-only" in str(s.get("if", ""))]
    assert [s["name"] for s in only_steps] == ["Check the code commit", "Prepare (prepare-only)"]
    # It uploads the packs with prepare.json, and prints prepare.json; the legacy dataset
    # belongs to a registered run's minute cells.
    assert any("cat v31/out/prepare.json" in script for script in _scripts("prepare"))
    assert _upload("prepare", "v31-packs")["path"] == "v31/out/"
    (legacy,) = [s for s in _uploads("prepare") if s["with"]["name"] == "v31-legacy-data"]
    assert legacy["if"] == "${{ inputs.mode == 'registered' }}"


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
    everything = set(JOBS) - {"smoke"}
    assert _ran("registered") == everything
    # prepare fails: nothing is left to run or to aggregate.
    assert _ran("registered", failing=["prepare"]) == {"plan", "prepare"}
    assert _ran("registered", failing=["plan"]) == {"plan"}
    # picks fails: the V3 cells cannot run; the others and the aggregate still do.
    assert _ran("registered", failing=["picks"]) == everything - {"run-v3"}
    # A failed cell never stops the aggregate: it judges what ran and names what did not.
    assert _ran("registered", failing=["run-main"]) == everything
    assert _ran("registered", failing=["run-v3"]) == everything


def test_v3_cells_wait_for_picks_and_other_cells_do_not() -> None:
    jobs = _jobs()
    assert "picks" in _needs(jobs["run-v3"])
    assert "picks" not in _needs(jobs["run-main"])
    assert set(_needs(jobs["run-main"])) == {"plan", "prepare"}
    assert set(_needs(jobs["run-v3"])) == {"plan", "prepare", "picks"}
    assert _needs(jobs["picks"]) == ["prepare"]
    (v3_call,) = _driver_calls("run-v3")
    (main_call,) = _driver_calls("run-main")
    assert "--picks" in v3_call[1]
    assert "--picks" not in main_call[1]
    assert "--legacy-data" not in v3_call[1]  # V3 cells replay the picks, not minutes
    picks_download = _download("run-v3", "v3-picks-attempt-*")
    assert picks_download["path"] == "v31/picks"
    assert not [s for s in _downloads("run-main") if "picks" in str(s["with"])]
    # A failed picks job skips the V3 cells, and only them.
    assert jobs_that_run("registered", failing=["picks"])["run-v3"] == "skipped"
    assert jobs_that_run("registered", failing=["picks"])["run-main"] == "success"


def test_aggregate_runs_after_failures_and_needs_both_run_jobs_and_picks() -> None:
    aggregate = _jobs()["aggregate"]
    assert set(_needs(aggregate)) == {"run-main", "run-v3", "picks"}
    assert "!cancelled()" in aggregate["if"]
    # !cancelled() alone would also run it in smoke and prepare-only mode, with every job
    # it needs skipped; and after a failed prepare, with nothing to read.
    assert "aggregate" not in _ran("smoke") | _ran("prepare-only")
    assert "aggregate" not in _ran("registered", failing=["prepare"])
    assert _ran("registered", failing=["run-main"]) >= {"aggregate"}


def test_matrices_are_parallel_capped_and_not_fail_fast_with_six_hour_timeouts() -> None:
    jobs = _jobs()
    for name in MATRIX_JOBS:
        strategy = jobs[name]["strategy"]
        assert strategy["max-parallel"] == 20, name
        assert strategy["fail-fast"] is False, name
    for name in ("prepare", "picks", *MATRIX_JOBS, "aggregate"):
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
    }
    script = _step("plan", "cells")["run"]
    assert "crypto_grid_bot.combined.driver.registration" in script
    assert "load_registration" in script
    assert 'cell.kind == "v3"' in script and 'cell.kind != "v3"' in script
    assert "256" in script  # GitHub's matrix limit
    assert _step("plan", "cells")["id"] == "cells"


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
            expected = "warn" if name in ("picks", *MATRIX_JOBS) else "error"
            assert step["with"]["retention-days"] == 90, (name, step["with"]["name"])
            assert step["with"]["if-no-files-found"] == expected, (name, step["with"]["name"])
    names = {s["with"]["name"] for name in JOBS for s in _uploads(name)}
    assert names == {
        "v31-packs",
        "v31-legacy-data",
        f"v3-picks-{attempt}",
        f"cell-${{{{ matrix.cell }}}}-{attempt}",
        f"v31-summary-{attempt}",
        f"v31-smoke-summary-{attempt}",
    }
    # The packs and the dataset keep fixed names, so a re-run of every job fails closed at the
    # first upload; every other artifact is named for its attempt.
    fixed = {n for n in names if "attempt" not in n}
    assert fixed == {"v31-packs", "v31-legacy-data"}


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
    ((_, prepare),) = [(c, t) for c, t in _driver_calls("prepare") if t[2] == "registered"]
    assert _upload("prepare", "v31-packs")["path"] == _option(prepare, "--out") + "/"
    assert _upload("prepare", "v31-legacy-data")["path"] == _option(prepare, "--work") + "/legacy"


def test_aggregate_downloads_each_artifact_into_its_own_folder() -> None:
    downloads = _downloads("aggregate")
    patterns = [s["with"]["pattern"] for s in downloads]
    assert patterns == ["cell-*-attempt-*", "v3-picks-attempt-*"]
    for step in downloads:
        assert "merge-multiple" not in step["with"]  # a merge would drop the folder names
        assert "name" not in step["with"]
        assert step["with"]["path"] == "v31/cells"
    ((_, call),) = _driver_calls("aggregate")
    assert _option(call, "--cells") == "v31/cells"  # cells/cell-<id>-attempt-<n>/<id>/
    summary = "v31-summary-attempt-${{ github.run_attempt }}"
    assert _upload("aggregate", summary)["path"] == _option(call, "--out")
    assert "merge-multiple" not in json.dumps(_workflow())


def test_every_driver_call_parses_with_the_drivers_own_parser() -> None:
    parser = v31_driver.build_parser()
    # argparse accepts an unambiguous prefix (--registration-sha for --registration-sha256);
    # a workflow must spell the option out, so abbreviations are off for every subcommand.
    (subparsers,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    for subparser in subparsers.choices.values():
        subparser.allow_abbrev = False
    seen = set()
    for name in JOBS:
        for subcommand, tokens in _driver_calls(name):
            seen.add(subcommand)
            try:
                args = parser.parse_args(tokens)
            except SystemExit as exc:  # argparse reports a bad call by exiting
                raise AssertionError(f"{name}: {tokens} is refused by the CLI") from exc
            assert args.command == subcommand
    assert seen == {"prepare", "picks", "run-cell", "aggregate", "smoke"}
    # The registered calls pass the dispatch's pin; nothing else is overridden.
    for name in ("picks", "run-main", "run-v3", "aggregate"):
        ((_, call),) = _driver_calls(name)
        assert _option(call, "--registration-sha256") == "$REGISTRATION_SHA256"
        assert not {"--registration", "--run-manifest", "--repo"} & set(call)
    for _, call in _driver_calls("run-main") + _driver_calls("run-v3"):
        assert _option(call, "--cell") == "$CELL"


# --- registration check and 2025 guard --------------------------------------------------


def test_registered_mode_verifies_the_registration_hash_first() -> None:
    steps = _steps("plan")
    assert _action(steps[0]) == "actions/checkout@v4"
    verify = steps[1]  # before Python is set up, installed or run
    script = verify["run"]
    assert "sha256sum config/v3_1_registration.json" in script
    assert "$REGISTRATION_SHA256" in script and "exit 1" in script
    assert all("python" not in s.get("run", "") for s in steps[:2])
    assert _jobs()["plan"]["if"] == "${{ inputs.mode == 'registered' }}"
    # The inputs reach the shell through the environment, never spliced into a script.
    assert "${{" not in " ".join(_scripts("plan") + _scripts("prepare")).replace(ATTEMPT_ID, "")
    assert _workflow()["env"]["REGISTRATION_SHA256"] == "${{ inputs.registration_sha256 }}"
    assert _workflow()["env"]["CODE_COMMIT"] == "${{ inputs.code_commit }}"


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
    step = _steps("plan")[1]
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
            or re.search(r"v31_driver\.py (prepare|smoke)\b", step.get("run", ""))
        ]
        assert data, f"{name} has no data step"
        assert guards[0] > max(data), f"{name}: the guard comes before its data step"
        # The first guard has no condition, so it can never be skipped.
        assert "if" not in steps[guards[0]], name
        driver = [i for i, s in enumerate(steps) if "scripts/v31_driver.py" in s.get("run", "")]
        if name in ("smoke", "prepare"):
            assert len(guards) == 1, name  # the driver is the data step; one scan follows it
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
    assert "always()" in steps[upload]["if"]
    assert "always()" in steps[last]["if"]
    assert steps[upload]["with"]["if-no-files-found"] == "warn"
    assert steps_that_run(job)[upload] == "success"
    assert steps_that_run(job, failing=[driver])[upload] == "success"
    # The scan before the upload ran after the failure, and a scan that fails blocks the upload.
    assert steps_that_run(job, failing=[driver])[last] == "success"
    assert steps_that_run(job, failing=[last])[upload] == "skipped"
    assert steps_that_run(job, failing=[first, last])[upload] == "skipped"
    # The other jobs upload only what succeeded.
    for other in ("smoke", "prepare", "aggregate"):
        for step in _uploads(other):
            assert "always()" not in str(step.get("if", "")), other


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


@pytest.mark.parametrize("case", ["good", "wrong-receipt", "two-attempts", "none"])
def test_run_v3_uses_exactly_the_picks_the_picks_job_published(tmp_path: Path, case: str) -> None:
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    picks = tmp_path / "v31/picks"
    picks.mkdir(parents=True)
    outcome = b'{"job": "v3_picks"}\n'
    receipt = hashlib.sha256(outcome).hexdigest()
    attempts = {"good": ["1"], "wrong-receipt": ["1"], "two-attempts": ["1", "2"], "none": []}
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
STUB = """\
python() {
  if [ "$1" = scripts/v31_driver.py ]; then
    shift
    printf '%s\\0' "$@" > "$ARGV_FILE"
    echo '{"outcome_sha256": "RECEIPT", "summary": "x"}'
  else
    REAL "$@"
  fi
}
"""


def _driver_step_run(
    step: dict[str, Any], tmp_path: Path, **extra: str
) -> tuple[subprocess.CompletedProcess[str], list[str], Path]:
    """Run a step that calls the driver with ``python`` replaced by a stub that records the
    driver's argv and prints a receipt. Returns the result, the argv and the output file."""
    argv_file, output = tmp_path / "argv", tmp_path / "github-output"
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "checkout"
    (cwd / "config").mkdir(parents=True, exist_ok=True)
    (cwd / "config/v3_1_prepare.json").write_bytes(b'{"schema": "v3.1-prepare-1"}\n')
    output.write_text("", encoding="utf-8")
    real = shlex.quote(Path(sys.executable).as_posix())
    prelude = STUB.replace("RECEIPT", FAKE_RECEIPT).replace("REAL", real)
    script = step["run"].replace("${{ github.run_id }}", "4242")
    script = script.replace("${{ github.run_attempt }}", "2")
    env = {
        "ARGV_FILE": argv_file.as_posix(),
        "RUNNER_TEMP": runner_temp.as_posix(),
        "GITHUB_OUTPUT": output.as_posix(),
        "REGISTRATION_SHA256": "a" * 64,
        "CODE_COMMIT": "b" * 40,
        "CELL": "w1.combined.olhc.c1.research",
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
        if args.command != "smoke":  # the checkout and the committed registration files
            assert (args.repo, args.registration, args.run_manifest) == (
                ".",
                "config/v3_1_registration.json",
                "config/v3_1_run_manifest.json",
            )
        if args.command == "prepare" and args.mode == "registered":
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
        else:
            assert args.command == "smoke" and (args.out, args.cells) == ("v31/smoke", None)
    assert sorted(seen, key=str) == sorted(
        [
            ("smoke", "smoke", None),
            ("prepare", "prepare", "registered"),
            ("prepare", "prepare", "prepare-only"),
            ("picks", "picks", None),
            ("run-main", "run-cell", None),
            ("run-v3", "run-cell", None),
            ("aggregate", "aggregate", None),
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


@pytest.fixture(scope="module")
def registered_world(tmp_path_factory: pytest.TempPathFactory) -> v31_smoke.World:
    """What Task 11 commits, in miniature: a repository holding config/v3_1_registration.json
    and its run-manifest, with all 42 arms and 216 cells (the smoke's synthetic world)."""
    root = tmp_path_factory.mktemp("v31-workflow") / "world"
    root.mkdir()
    with v31_smoke.stand_ins():
        world = v31_smoke.build_world(root)
        document = v31_driver.smoke_packs(world, root / v31_driver.PACKS_DIR)
        v31_smoke.register(world, document, code_pin=world.head)
    return world


def test_the_plan_step_splits_the_registered_cells_into_28_v3_and_188_other_cells(
    registered_world: v31_smoke.World, tmp_path: Path
) -> None:
    repo = registered_world.repo
    registration = load_registration(
        repo / "config/v3_1_registration.json",
        repo / "config/v3_1_run_manifest.json",
        repo_root=repo,
    )
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    # `python` on the runner is the one with the project installed; here it is this one.
    prelude = "python() { " + shlex.quote(Path(sys.executable).as_posix()) + ' "$@"; }\n'
    result = _run_step(
        _step("plan", "cells")["run"],
        repo,
        {"GITHUB_OUTPUT": output.as_posix(), "PYTHONPATH": str(ROOT / "src")},
        prelude,
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    assert set(lines) == {"v3_cells", "main_cells"}
    v3_cells, main_cells = json.loads(lines["v3_cells"]), json.loads(lines["main_cells"])
    assert (len(v3_cells), len(main_cells)) == (28, 188)
    assert len(v3_cells) <= 256 and len(main_cells) <= 256
    assert set(v3_cells).isdisjoint(main_cells)
    assert {*v3_cells, *main_cells} == {cell.cell_id for cell in registration.cells}
    assert {c.cell_id for c in registration.cells if c.kind == "v3"} == set(v3_cells)
    assert all(re.fullmatch(r"[a-z0-9._-]+", cell) for cell in (*v3_cells, *main_cells))
    # GitHub reads the output as one line per array.
    assert lines["main_cells"].startswith("[") and "\n" not in lines["main_cells"]
