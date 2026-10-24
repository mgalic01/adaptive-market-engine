"""The v4-run workflow: V4.0's registered run, its rehearsal and its timing run.

``.github/workflows/v4-run.yml`` (plan ``docs/superpowers/plans/2026-10-24-v4-step4b-pipeline.md``,
Tasks 9 and 10) runs the 48 cells of V4's registration on GitHub's machines, in one of three modes:
``rehearsal`` (the registered job graph on a synthetic world, Ruling W3), ``timing`` (the 44 cells
that are not v3 on the real-size synthetic world, Ruling W2) and ``registered`` (the registered
experiment, once). These tests pin its job graph: part 1, ``plan``, ``v3-pack``, ``v3-picks``,
``cell`` and ``v3-cell`` (Task 9), and part 2, ``scenarios``, ``verdict``, ``analysis`` and
``status`` (Task 10).

They pin that it is dispatch-only and read-only, that its run name is the title the dispatch check
looks for and its jobs carry the names the check reads, that every action is pinned and every
checkout keeps no token, that no value is spliced into a script, that every artifact is kept one
day and named as Ruling W1 says, that the registered plan gates the checkout, refuses a second
dispatch and checks the data run before it downloads anything, that every cell job gates its
checkout first and guards its data before its cell runs, that a cell's standard output goes to
/dev/null, and that the V3 pack's and the picks' pins are checked against the files. Part 2's tests
pin that the verdict reads the cells' summaries alone, runs after failed cells but never after a
failed plan, checks for another dispatch again in a registered run (first, before any download),
times its expected step and its verdict step and judges every scenario of a rehearsal;
that the analysis reads the cells but never the v3 cells; that each mode names its outputs as its
own; that the status job always runs and reads the jobs' results through the environment; and
that no CLI whose standard output could tell a result prints it to the public log.

The tests parse the YAML and never call GitHub. Some run one step's script in bash, as GitHub runs
it (``-e -o pipefail``): either for real on small files (the pin checks), or with ``python``,
``gh``, ``tar`` and ``sha256sum`` replaced by shell functions that only record their arguments
(``trace``), so no step reaches the network, GitHub's API or a real CLI.
"""

from __future__ import annotations

import argparse
import fnmatch
import functools
import hashlib
import itertools
import json
import os
import re
import shlex
import shutil
import subprocess  # nosec B404: the tests run the workflow's own steps in bash
import sys
import tarfile
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.combined.driver.packs import _write_gzip_json
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.run import LIQUIDATED, data_record
from crypto_grid_bot.v4.engine.v3_as_built import PICKS_FILE
from crypto_grid_bot.v4.synthetic import (
    CoinSpec,
    Series,
    World,
    every_month,
    month_start,
    write_world,
)
from crypto_grid_bot.v4.synthetic import (
    path as price_path,
)
from crypto_grid_bot.v4.verdict import inputs as verdict_inputs
from crypto_grid_bot.v4.verdict import report as verdict_report

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_cell  # noqa: E402
import v4_cells_timing  # noqa: E402
import v4_diagnose  # noqa: E402
import v4_registration  # noqa: E402
import v4_rehearsal  # noqa: E402
import v4_run_guard  # noqa: E402
import v4_run_plan  # noqa: E402
import v4_run_status  # noqa: E402
import v4_v3_cell  # noqa: E402
import v4_v3_pack  # noqa: E402
import v4_verdict  # noqa: E402
import v4_verdict_fixtures  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "v4-run.yml"
CELLS_WORKFLOW = ROOT / ".github" / "workflows" / "v4-cells.yml"
V3_WORKFLOW = ROOT / ".github" / "workflows" / "v4-v3.yml"
MODES = ("rehearsal", "timing", "registered")
# Part 1's jobs, in the file's order (Task 9), then part 2's (Task 10).
PART_1_JOBS = ("plan", "v3-pack", "v3-picks", "cell", "v3-cell")
PART_2_JOBS = ("scenarios", "verdict", "analysis", "status")
# The jobs that read GitHub's run listings or another run's artifacts: only they hold
# actions: read, and each records its start first, the dispatch check's budget clock (the plan's
# dispatch check, and the registered verdict's check again).
CHECKING_JOBS = ("plan", "verdict")
PINNED = re.compile(r"^(?P<action>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{40})$")
CHECKOUT = "actions/checkout@"
UPLOAD = "actions/upload-artifact@"
DOWNLOAD = "actions/download-artifact@"
SETUP_STEPS = 5  # checkout, setup-python and three installs, as in v4-cells.yml
JOB_START_STEP = {
    "name": "Record the job's start",
    "run": 'echo "V4_JOB_STARTED=$(date +%s)" >> "$GITHUB_ENV"',
}
# Ruling W1: every artifact carries the attempt, but these three, whose fixed names make a re-run
# of the whole workflow fail closed at the plan job.
ATTEMPT = "-attempt-${{ github.run_attempt }}"
FIXED_NAMES = ("v4-data", "v4-v3-pack", "v4-rehearsal-world")
MATRIX_CELL = "${{ matrix.cell }}"
# A cell's uploads run when every step passed, or when only the timing step failed (v4-cells.yml);
# its timing alone, in a timing run, only once the timing step wrote it.
UPLOAD_CONDITION = "${{ success() || steps.timing.outcome == 'failure' }}"
TIMING_UPLOAD_CONDITION = (
    "${{ success() && steps.timing.outcome == 'success' && inputs.mode == 'timing' }}"
)
PACK_PIN = v4_v3_pack.EXPECTED_PACK_SHA256
PACK_PATH = f"v3pack/{v4_v3_pack.PACK_FILE}"
PICKS_PATH = f"picks/{PICKS_FILE}"
MANIFEST = "config/v4_run_manifest.json"
TIMED = '/usr/bin/time -v -o "out/$CELL.time" '
REPLAYS = {
    "cell": (
        'python scripts/v4_cell.py run --data v4data --arm "$ARM" --capital "$CAPITAL" '
        '--costs "$COSTS" --out out > /dev/null'
    ),
    "v3-cell": (
        f'python scripts/v4_v3_cell.py run --pack {PACK_PATH} --pack-sha256 "$PACK_SHA256" '
        f'--picks {PICKS_PATH} --picks-sha256 "$PICKS_SHA256" '
        '--capital "$CAPITAL" --costs "$COSTS" --out out > /dev/null'
    ),
}
TIMING_STEP = (
    'python scripts/v4_cells_timing.py --time-file "out/$CELL.time" --cell-dir "out/$CELL"'
)
# The values a traced step sees for the dispatch's inputs and GitHub's context.
INPUT_SHA = "e" * 64  # the registered dispatch's registration_sha256
WORLD_SHA = "d" * 64  # what the recorder's ``python -c`` prints: the world's registration pin
PLAN_SHA = "a" * 64  # needs.plan.outputs.registration_sha256
PLAN_PACK = "b" * 64  # needs.plan.outputs.v3_pack_sha256
PICKS_SHA = "f" * 64  # needs.v3-picks.outputs.picks_sha256
DATA_RUN = "40000000001"
RUN_ID = "40000000099"  # github.run_id
COMMIT = "c" * 40
# The cells each mode plans: the v3-cell job's matrix is empty in timing.
V3_COUNT = {mode: str(len(v4_run_plan.matrix(mode)[1])) for mode in MODES}
# needs.plan.outputs.cell_ids: the 44 cells that are not v3, the analysis' --planned.
CELL_IDS = ",".join(str(cell["cell"]) for cell in v4_run_plan.matrix("registered")[0])
# Part 2: the verdict's and the analysis' downloads of the cells' artifacts, one folder per
# artifact (Ruling V1's folder rule: summaries/v4-summary-<cell>-attempt-<n>/), and their if.
SUMMARIES = {"pattern": "v4-summary-*", "merge-multiple": False, "path": "summaries"}
CELL_FOLDERS = {"pattern": "v4-cell-*", "merge-multiple": False, "path": "cells"}
AFTER_THE_CELLS = "${{ !cancelled() && needs.plan.result == 'success' }}"
DIAGNOSED = (
    "${{ !cancelled() && (steps.diagnose.outcome == 'success' || "
    "steps.diagnose.outcome == 'failure') }}"
)
# Each mode's prefix of its outputs (Ruling W3): a synthetic verdict never passes for the
# registered run's.
OUTPUT_PREFIX = {"registered": "v4-", "rehearsal": "v4-rehearsal-", "timing": "v4-timing-"}
# The verdict job's picks pin when the picks job did not succeed: no picks file hashes to it.
NO_PICKS = "0" * 64
VERDICT_RAN = (
    "${{ !cancelled() && (steps.verdict.outcome == 'success' || "
    "steps.verdict.outcome == 'failure') }}"
)
EXPECTED_RAN = (
    "${{ !cancelled() && (steps.expected.outcome == 'success' || "
    "steps.expected.outcome == 'failure') }}"
)
# The verdict job's expected step and its timing (v4_cells_timing.py --expected-dir).
EXPECTED_TIMING_STEP = (
    "mkdir -p verdict python scripts/v4_cells_timing.py --time-file expected.time "
    "--expected-dir verdict"
)


# ---- reading the workflow -----------------------------------------------------------------------


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


@functools.cache
def _document() -> dict[str, Any]:
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    document = yaml.safe_load(text())
    assert isinstance(document, dict)
    return document


def workflow() -> dict[str, Any]:
    return _document()


def jobs() -> dict[str, dict[str, Any]]:
    found = workflow()["jobs"]
    assert isinstance(found, dict)
    return found


def steps(job: str) -> list[dict[str, Any]]:
    found = jobs()[job]["steps"]
    assert isinstance(found, list)
    return found


def uses(step: Mapping[str, Any]) -> str:
    return str(step.get("uses", ""))


def is_upload(step: Mapping[str, Any]) -> bool:
    return uses(step).startswith(UPLOAD)


def is_download(step: Mapping[str, Any]) -> bool:
    return uses(step).startswith(DOWNLOAD)


def run_text(step: Mapping[str, Any]) -> str:
    """A step's script on one line: continuations joined, whitespace collapsed."""
    return " ".join(str(step.get("run", "")).replace("\\\n", " ").split())


def code() -> str:
    """The workflow's text without its comment lines."""
    return "\n".join(line for line in text().splitlines() if not line.lstrip().startswith("#"))


def header() -> str:
    """The comment block above ``on:``, as one line of text."""
    head = text().split("\non:\n", 1)[0]
    lines = [line.lstrip("#").strip() for line in head.splitlines() if line.startswith("#")]
    return re.sub(r"\s+", " ", " ".join(lines))


def index_of(job: str, needle: str) -> int:
    """The position of the one step of ``job`` whose script holds ``needle``."""
    found = [i for i, step in enumerate(steps(job)) if needle in run_text(step)]
    assert len(found) == 1, (job, needle, found)
    return found[0]


def needs(job: Mapping[str, Any]) -> list[str]:
    value = job.get("needs", [])
    return [value] if isinstance(value, str) else list(value)


def ancestors(name: str) -> set[str]:
    """Every job ``name`` needs, directly or through another."""
    found: set[str] = set()
    pending = needs(jobs()[name])
    while pending:
        need = pending.pop()
        if need not in found:
            found.add(need)
            pending.extend(needs(jobs()[need]))
    return found


def bare(condition: object) -> str:
    """An ``if`` without its ``${{ }}``."""
    value = str(condition).strip()
    if value.startswith("${{") and value.endswith("}}"):
        value = value[3:-2].strip()
    return value


# ---- which jobs and steps run -----------------------------------------------------------------

STATUS_FUNCTIONS = ("always()", "cancelled()", "success()", "failure()")


def truth(
    expression: object,
    mode: str,
    *,
    results: Mapping[str, str] | None = None,
    outcomes: Mapping[str, str] | None = None,
    succeeded: bool = True,
    v3_count: str | None = None,
) -> bool:
    """A job's or step's ``if`` for a dispatch of ``mode``. Only what the workflow uses is read:
    ``inputs.mode``, ``needs.<job>.result``, ``needs.plan.outputs.v3_count``,
    ``steps.<id>.outcome``, ``success()`` (``succeeded``), ``!cancelled()`` and ``always()``
    (true: no run here is cancelled), string literals, ``==``, ``!=``, ``!``, ``&&``, ``||`` and
    parentheses. ``results`` holds the job's needs alone: GitHub offers a job no other job's."""
    python = bare(expression)
    python = python.replace("needs.plan.outputs.v3_count", "V3_COUNT")
    python = re.sub(r"needs\.([A-Za-z0-9_-]+)\.result", r"RESULTS['\1']", python)
    python = re.sub(r"steps\.([A-Za-z0-9_-]+)\.outcome", r"OUTCOMES['\1']", python)
    python = python.replace("inputs.mode", "MODE").replace("!cancelled()", "True")
    python = python.replace("always()", "True").replace("success()", "SUCCESS")
    python = python.replace("&&", " and ").replace("||", " or ")
    python = re.sub(r"!(?!=)", " not ", python)
    assert not re.search(r"[A-Za-z_]\(", python), f"an expression this test cannot read: {python}"
    assert not re.search(r"\b(needs|steps|inputs|github|matrix)\.", python), python
    names = {
        "MODE": mode,
        "V3_COUNT": V3_COUNT[mode] if v3_count is None else v3_count,
        "RESULTS": dict(results or {}),
        "OUTCOMES": defaultdict(lambda: "skipped", outcomes or {}),
        "SUCCESS": succeeded,
    }
    return bool(eval(python, {"__builtins__": {}}, names))  # nosec B307: the workflow's own ifs


def jobs_that_run(
    mode: str, failing: Iterable[str] = (), *, v3_count: str | None = None
) -> dict[str, str]:
    """Each job's result for a dispatch of ``mode``: ``success``, ``failure`` (the jobs named in
    ``failing``) or ``skipped``.

    An ``if`` without a status function has GitHub's implicit ``success()``, which is false when
    any job before it, needed directly or through another job, failed or was skipped (so a job
    after a job its mode skips needs ``!cancelled()``); no ``if`` at all is that ``success()``."""
    failed = set(failing)
    results: dict[str, str] = {}
    pending = list(jobs())
    while pending:
        name = next(job for job in pending if all(n in results for n in needs(jobs()[job])))
        pending.remove(name)
        job = jobs()[name]
        all_succeeded = all(results[a] == "success" for a in ancestors(name))
        if "if" not in job:
            runs = all_succeeded
        else:
            condition = bare(job["if"])
            value = truth(
                condition,
                mode,
                results={n: results[n] for n in needs(job)},
                succeeded=all_succeeded,
                v3_count=v3_count,
            )
            aware = any(function in condition for function in STATUS_FUNCTIONS)
            runs = value if aware else (all_succeeded and value)
        results[name] = ("failure" if name in failed else "success") if runs else "skipped"
    return results


def part_1(results: Mapping[str, str]) -> dict[str, str]:
    return {name: results[name] for name in PART_1_JOBS}


def step_runs(
    step: Mapping[str, Any],
    mode: str,
    *,
    outcomes: Mapping[str, str] | None = None,
    failed: bool = False,
) -> bool:
    """Whether a step runs in ``mode``, after the earlier steps' ``outcomes`` (``failed`` when one
    of them failed): one without an ``if`` runs only while every earlier step succeeded."""
    if "if" not in step:
        return not failed
    condition = bare(step["if"])
    value = truth(condition, mode, outcomes=outcomes, succeeded=not failed)
    aware = any(function in condition for function in STATUS_FUNCTIONS)
    return value if aware else (value and not failed)


def steps_that_run(job: str, mode: str, failing: Iterable[int] = ()) -> list[str]:
    """Each step's outcome (``success``, ``failure`` or ``skipped``) when the steps at the indexes
    in ``failing`` fail as they run."""
    failed_at = set(failing)
    outcomes: dict[str, str] = {}
    result = []
    failed = False
    for index, step in enumerate(steps(job)):
        runs = step_runs(step, mode, outcomes=outcomes, failed=failed)
        outcome = ("failure" if index in failed_at else "success") if runs else "skipped"
        failed = failed or outcome == "failure"
        result.append(outcome)
        if "id" in step:
            outcomes[step["id"]] = outcome
    return result


RESULT_VALUES = ("success", "failure", "skipped")


def job_can_run(name: str, mode: str) -> bool:
    """Whether job ``name`` runs in any dispatch of ``mode``, whatever its needs ended with."""
    job = jobs()[name]
    if "if" not in job:
        return True
    condition = bare(job["if"])
    aware = any(function in condition for function in STATUS_FUNCTIONS)
    named = needs(job)
    for ended in itertools.product(RESULT_VALUES, repeat=len(named)):
        succeeded = all(result == "success" for result in ended)
        results = dict(zip(named, ended, strict=True))
        value = truth(condition, mode, results=results, succeeded=succeeded)
        if value and (aware or succeeded):
            return True
    return False


def step_can_run(step: Mapping[str, Any], mode: str) -> bool:
    """Whether ``step`` runs in any dispatch of ``mode``, whatever the steps before it did."""
    if "if" not in step:
        return True
    ids = sorted(set(re.findall(r"steps\.([\w-]+)\.outcome", bare(step["if"]))))
    return any(
        step_runs(step, mode, outcomes=dict(zip(ids, ended, strict=True)), failed=failed)
        for failed in (False, True)
        for ended in itertools.product(RESULT_VALUES, repeat=len(ids))
    )


def can_run(job: str, step: Mapping[str, Any], mode: str) -> bool:
    return job_can_run(job, mode) and step_can_run(step, mode)


def index_of_upload(job: str, name: str) -> int:
    """The position of the one upload of ``job`` whose artifact is ``name``."""
    found = [i for i, s in enumerate(steps(job)) if is_upload(s) and s["with"]["name"] == name]
    assert len(found) == 1, (job, name, found)
    return found[0]


# ---- running a step in bash ---------------------------------------------------------------------


def real_bash() -> str:
    shell = (
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    assert shell and Path(shell).is_file(), "Git Bash (Windows) or bash is required"
    return shell


# GitHub's API variables are emptied in every step run here, so nothing could reach it.
NO_GITHUB_API = {"GITHUB_TOKEN": "", "GH_TOKEN": "", "GITHUB_REPOSITORY": "", "GITHUB_RUN_ID": ""}
# The recorder: each CLI a step calls writes its arguments, tab-separated, to $CALLS and does
# nothing else; ``python -c`` prints $STUB_SHA256 (a step reading a pin from a file), and
# ``sha256sum`` prints it as the digest of its file. ``python`` exits $STUB_STATUS (a refusal).
RECORDER = r"""log() { local IFS=$'\t'; printf '%s\n' "$*" >> "$CALLS"; }
python() {
  log python "$@"
  if [ "$1" = -c ]; then printf '%s\n' "$STUB_SHA256"; fi
  return "${STUB_STATUS:-0}"
}
gh() { log gh "$@"; printf '{}\n'; }
tar() { log tar "$@"; }
sha256sum() { log sha256sum "$@"; printf '%s  %s\n' "$STUB_SHA256" "$1"; }
"""
# The test's own interpreter, for a step run for real.
REAL_PYTHON = 'python() { "$TEST_PYTHON" "$@"; }\n'


def run_script(
    script: str, cwd: Path, env: Mapping[str, str], *, prelude: str = "", pipefail: bool = True
) -> subprocess.CompletedProcess[str]:
    """``script`` as GitHub runs a bash step (``-e -o pipefail``) in ``cwd``; with ``pipefail``
    False, as a bash without that option runs it (a step that needs it must set it itself)."""
    options = ["-e", "-o", "pipefail"] if pipefail else ["-e"]
    return subprocess.run(
        [real_bash(), "--noprofile", "--norc", *options, "-c", prelude + script],
        cwd=cwd,
        env={
            **os.environ,
            **NO_GITHUB_API,
            "TEST_PYTHON": Path(sys.executable).as_posix(),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )


def write_pack(path: Path) -> tuple[str, str]:
    """A small V3 pack written as ``write_v3_pack`` writes one (``packs._write_gzip_json``): its
    pin, the SHA-256 of the canonical JSON the file compresses, and the SHA-256 of the gzip
    file's own bytes, which is not the pin."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pin = _write_gzip_json({"format": "a synthetic pack", "rows": [1, 2, 3]}, path)
    file_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert pin != file_digest
    return pin, file_digest


def context(mode: str) -> dict[str, str]:
    """The value of every expression a traced job reads, for a dispatch of ``mode``."""
    return {
        "inputs.mode": mode,
        "inputs.registration_sha256": INPUT_SHA if mode == "registered" else "",
        "inputs.data_run": DATA_RUN if mode == "registered" else "",
        "github.token": "fake-token",
        "github.repository": "owner/repository",
        "github.sha": COMMIT,
        "github.run_attempt": "1",
        "github.run_id": RUN_ID,
        "matrix.cell": "v4_main-1000-1x",
        "matrix.arm": "v4_main",
        "matrix.capital": "1000",
        "matrix.costs": "1",
        "needs.plan.outputs.registration_sha256": PLAN_SHA,
        "needs.plan.outputs.v3_pack_sha256": PLAN_PACK,
        "needs.v3-picks.outputs.picks_sha256": PICKS_SHA,
        "needs.v3-picks.result": "success",
        "needs.plan.outputs.cell_ids": CELL_IDS,
        "toJSON(needs)": "{}",
    }


EXPRESSION = re.compile(r"\$\{\{\s*(.*?)\s*\}\}")


def resolve(value: object, known: Mapping[str, str]) -> object:
    """``value`` with each ``${{ }}`` replaced by its value in ``known``. A step's output that no
    step wrote is empty, as on GitHub (a skipped step's, say); any other expression the test does
    not know fails the test. A value that is not text (a number of days) is kept as it is."""
    if not isinstance(value, str):
        return value

    def one(match: re.Match[str]) -> str:
        if match[1] in known:
            return known[match[1]]
        assert re.fullmatch(r"steps\.[\w-]+\.outputs\.[\w-]+", match[1]), (
            f"an expression the test does not know: {match[1]}"
        )
        return ""

    return EXPRESSION.sub(one, value)


def step_env(job: str, step: Mapping[str, Any], known: Mapping[str, str]) -> dict[str, str]:
    """A step's effective environment: the workflow's, the job's, then the step's own."""
    env: dict[str, str] = {}
    for scope in (workflow(), jobs()[job], step):
        for key, value in scope.get("env", {}).items():
            env[key] = str(resolve(value, known))
    return env


def outputs_of(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="ascii").splitlines() if path.exists() else []
    return dict(line.split("=", 1) for line in lines)


def run_recorded(
    job: str,
    step: Mapping[str, Any],
    mode: str,
    folder: Path,
    *,
    known: Mapping[str, str] | None = None,
    extra: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], dict[str, str]]:
    """One step of ``job`` run with the recorder: its result, the CLI calls it made (each one's
    arguments, the step's output file named ``$GITHUB_OUTPUT``) and what it wrote to its
    outputs."""
    folder.mkdir(parents=True, exist_ok=True)
    calls, output = folder / "calls.txt", folder / "github_output"
    for path in (calls, output):
        path.write_text("", encoding="ascii")
    env = {
        **step_env(job, step, known or context(mode)),
        "CALLS": calls.as_posix(),
        "GITHUB_OUTPUT": output.as_posix(),
        "GITHUB_ENV": (folder / "github_env").as_posix(),
        "STUB_SHA256": WORLD_SHA,
        **(extra or {}),
    }
    done = run_script(str(step["run"]), folder, env, prelude=RECORDER)
    recorded = [
        [word.replace(output.as_posix(), "$GITHUB_OUTPUT") for word in line.split("\t")]
        for line in calls.read_text(encoding="ascii").splitlines()
    ]
    return done, recorded, outputs_of(output)


TIMED_BY = re.compile(r"/usr/bin/time -v -o \S+ ")


def run_untimed(
    job: str, step: Mapping[str, Any], mode: str, folder: Path
) -> tuple[subprocess.CompletedProcess[str], list[list[str]], dict[str, str]]:
    """A step that runs its CLI under GNU time, run with the recorder and GNU time left out (a
    Windows bash has none; ``trace`` records such a step as ``timed``): the calls its CLI gets in
    ``mode``."""
    script = str(step["run"])
    assert TIMED_BY.search(script), (job, step.get("name"))
    return run_recorded(job, {**step, "run": TIMED_BY.sub("", script)}, mode, folder)


def trace(job: str, mode: str, folder: Path) -> list[tuple[Any, ...]]:
    """What ``job`` does in a dispatch of ``mode`` when every step succeeds, in order: each CLI
    call of its scripts (``("call", argv)``; the pip installs left out), each artifact step
    (``("download" | "upload", with)``, its expressions resolved, a step's outputs from what it
    wrote) and each step that runs GNU time (``("timed", script)``, which a Windows bash cannot
    run). Setup actions (checkout, setup-python) are left out."""
    known = context(mode)
    outcomes: dict[str, str] = {}
    events: list[tuple[Any, ...]] = []
    for index, step in enumerate(steps(job)):
        if not step_runs(step, mode, outcomes=outcomes):
            if "id" in step:
                outcomes[step["id"]] = "skipped"
            continue
        if is_upload(step) or is_download(step):
            kind = "upload" if is_upload(step) else "download"
            events.append((kind, {k: resolve(v, known) for k, v in step["with"].items()}))
        elif "/usr/bin/time" in str(step.get("run", "")):
            events.append(("timed", run_text(step)))
        elif "run" in step:
            done, calls, written = run_recorded(job, step, mode, folder / str(index), known=known)
            assert done.returncode == 0, (job, mode, index, done.stderr)
            events.extend(("call", call) for call in calls if call[1:2] != ["-m"])
            if "id" in step:
                known = {
                    **known,
                    **{f"steps.{step['id']}.outputs.{k}": v for k, v in written.items()},
                }
        if "id" in step:
            outcomes[step["id"]] = "success"
    return events


def calls_of(events: Iterable[tuple[Any, ...]], script: str) -> list[list[str]]:
    """The recorded calls of ``python scripts/<script>``: their arguments after the script."""
    found = []
    for event in events:
        if event[0] == "call" and event[1][:2] == ["python", f"scripts/{script}"]:
            found.append(event[1][2:])
    return found


# ---- dispatch, permissions, names, pins ---------------------------------------------------------


def test_dispatch_only_inputs_and_permissions():
    document = workflow()
    assert document["name"] == "v4-run"
    assert list(document[True]) == ["workflow_dispatch"]
    inputs = document[True]["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["mode", "registration_sha256", "data_run"]
    mode = inputs["mode"]
    assert (mode["type"], mode["options"], mode["default"]) == ("choice", list(MODES), "rehearsal")
    # The modes are those of the verdict's expected file and of the dispatch check's titles.
    assert tuple(mode["options"]) == verdict_inputs.MODES
    assert set(mode["options"]) == set(v4_registration.TITLE_MODES)
    for name in ("registration_sha256", "data_run"):
        spec = inputs[name]
        assert (spec["type"], spec["default"], spec["required"]) == ("string", "", False), name

    # Read-only: actions: read only where GitHub's run listings or another run's artifacts are read.
    assert document["permissions"] == {"contents": "read"}
    widened = {name: job["permissions"] for name, job in jobs().items() if "permissions" in job}
    assert widened == {name: {"contents": "read", "actions": "read"} for name in CHECKING_JOBS}
    assert "secrets." not in code()
    for name, job in jobs().items():
        assert job["runs-on"] == "ubuntu-latest", name

    # One v4-run at a time, and a running one is never cancelled for a newer one.
    assert document["concurrency"] == {"group": "v4-run", "cancel-in-progress": False}
    assert all("concurrency" not in job for job in jobs().values())

    # The inputs reach scripts through the workflow's environment only.
    assert document["env"] == {
        "MODE": "${{ inputs.mode }}",
        "REGISTRATION_SHA256": "${{ inputs.registration_sha256 }}",
        "DATA_RUN": "${{ inputs.data_run }}",
        "V3_PACK_SHA256": PACK_PIN,
    }
    assert document["defaults"] == {"run": {"shell": "bash"}}
    # The registration's pin is read in the run's name and the environment; the data run's id in
    # the environment alone (the plan's data-run step validates it before any use).
    assert code().count("inputs.registration_sha256") == 2
    assert code().count("inputs.data_run") == 1


def test_run_name_matches_registration_titles():
    document = workflow()
    run_name = document["run-name"]
    assert run_name == "v4-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}"

    def title(mode: str, sha: str) -> str:
        return run_name.replace("${{ inputs.mode }}", mode).replace(
            "${{ inputs.registration_sha256 }}", sha
        )

    sha = "0123456789abcdef" * 4
    assert title("registered", sha) == v4_registration.registered_title(sha)
    for mode in MODES:
        assert title(mode, sha) in v4_registration.run_titles(mode, sha), mode
    for mode in ("rehearsal", "timing"):  # dispatched with no registration
        assert title(mode, "") in v4_registration.run_titles(mode, ""), mode
    assert WORKFLOW.name == v4_registration.WORKFLOW_FILE
    assert document["name"] == v4_registration.RUN_NAME
    # The registration script's note of the run-name quotes it as it is.
    source = (ROOT / "scripts" / "v4_registration.py").read_text(encoding="utf-8")
    assert run_name in source and "${{ inputs.sha }}" not in source


def test_jobs_are_named_as_the_dispatch_check_reads_them():
    # The dispatch check (layer L2) reads each earlier launch's jobs by the names GitHub gives
    # them: a job's id, or "<id> (<matrix values>)" for a matrix job. A job `name:` would change
    # them, and a launch with a job it does not know always counts.
    names = list(jobs())
    assert names == [*PART_1_JOBS, *PART_2_JOBS]
    known = {
        v4_registration.PLAN_JOB,
        v4_registration.STATUS_JOB,
        *v4_registration.SKIPPED_JOBS,
        *v4_registration.SKIPPED_MATRIX_JOBS,
    }
    assert set(names) <= known
    for name, job in jobs().items():
        assert "name" not in job, name
        assert v4_registration._job_kind(name) == name, name
        assert ("strategy" in job) == (name in v4_registration.SKIPPED_MATRIX_JOBS), name
    for name in v4_registration.SKIPPED_MATRIX_JOBS:
        assert v4_registration._job_kind(f"{name} (v4_main-1000-1x, v4_main, 1000, 1)") == name


def test_every_action_pinned_and_checkout_without_credentials():
    cells_text = CELLS_WORKFLOW.read_text(encoding="utf-8")
    known = dict(re.findall(r"uses: ([\w./-]+)@([0-9a-f]{40})", cells_text))
    model = yaml.safe_load(cells_text)["jobs"]["plan"]["steps"][:SETUP_STEPS]
    assert model[0]["with"] == {"persist-credentials": False}
    for name, job in jobs().items():
        for step in job["steps"]:
            if "uses" in step:
                match = PINNED.match(uses(step))
                assert match is not None, (name, uses(step))
                assert known[match["action"]] == match["sha"], (name, uses(step))
        # A checking job records its start first; every job checks out once, at the top.
        first = 1 if name in CHECKING_JOBS else 0
        if name in CHECKING_JOBS:
            assert job["steps"][0] == JOB_START_STEP, name
        checkouts = [i for i, s in enumerate(job["steps"]) if uses(s).startswith(CHECKOUT)]
        assert checkouts == [first], name
        setup = job["steps"][first : first + SETUP_STEPS]
        # v4-cells.yml's five setup steps; the checkout keeps no token, and holds the full
        # history, since the job gate lists every change since the code pin (git diff
        # <code pin> HEAD), which a shallow clone does not hold.
        assert setup[0] == {**model[0], "with": {"fetch-depth": 0, "persist-credentials": False}}
        assert setup[1:] == model[1:], name
        assert setup[1]["with"]["python-version"] == "3.12"


def test_no_expression_inside_a_run_script():
    # Inputs, matrix values and outputs reach a script as environment variables ("$ARM"), never
    # as text in it, so a value cannot become shell code.
    for name, job in jobs().items():
        for step in job["steps"]:
            assert "${{" not in str(step.get("run", "")), (name, step.get("name"))
            assert "shell" not in step, (name, step.get("name"))  # bash, as the defaults say


def test_plan_records_its_start_first_and_its_budget_ends_inside_its_timeout(tmp_path):
    # The dispatch check's deadline counts from the job's start (V4_JOB_STARTED), which the
    # plan's first step records before the checkout and the installs: its budget ends at least
    # five minutes before the job's timeout, so a long outage fails the plan (not counted)
    # rather than running into the timeout, which cancels it (counted).
    plan = jobs()["plan"]
    assert plan["steps"][0] == JOB_START_STEP
    assert v4_registration.JOB_STARTED == "V4_JOB_STARTED"
    assert plan["timeout-minutes"] == 60
    assert plan["timeout-minutes"] * 60 >= v4_registration.PLAN_JOB_BUDGET + 5 * 60
    (check,) = [s for s in plan["steps"] if "dispatch-check" in run_text(s)]
    assert "timeout-minutes" not in check  # the check's own deadline ends it

    env_file = tmp_path / "github_env"
    env_file.write_text("", encoding="utf-8")
    before = int(time.time())
    done = run_script(JOB_START_STEP["run"], tmp_path, {"GITHUB_ENV": env_file.as_posix()})
    after = int(time.time())
    assert done.returncode == 0, done.stderr
    (line,) = env_file.read_text(encoding="utf-8").splitlines()
    name, value = line.split("=", 1)
    assert name == "V4_JOB_STARTED" and re.fullmatch(r"[1-9][0-9]*", value)
    assert before <= int(value) <= after


# ---- the job graph ------------------------------------------------------------------------------


def test_each_mode_runs_its_jobs_and_a_failure_stops_what_depends_on_it():
    graph = jobs()
    assert needs(graph["plan"]) == [] and "if" not in graph["plan"]
    assert needs(graph["v3-pack"]) == ["plan"]
    assert needs(graph["v3-picks"]) == ["plan", "v3-pack"]
    assert needs(graph["cell"]) == ["plan"] and "if" not in graph["cell"]
    assert needs(graph["v3-cell"]) == ["plan", "v3-pack", "v3-picks"]
    timeouts = {name: graph[name]["timeout-minutes"] for name in PART_1_JOBS}
    assert timeouts == {"plan": 60, "v3-pack": 120, "v3-picks": 300, "cell": 60, "v3-cell": 60}

    ok, skip = "success", "skipped"
    assert part_1(jobs_that_run("registered")) == dict.fromkeys(PART_1_JOBS, ok)
    assert part_1(jobs_that_run("rehearsal")) == {
        "plan": ok,
        "v3-pack": skip,  # the plan built the world's V3 pack
        "v3-picks": ok,
        "cell": ok,
        "v3-cell": ok,
    }
    assert part_1(jobs_that_run("timing")) == {
        "plan": ok,
        "v3-pack": skip,
        "v3-picks": skip,
        "cell": ok,
        "v3-cell": skip,  # no v3 cell: GitHub refuses an empty matrix
    }
    # A failed plan stops every job of every mode.
    for mode in MODES:
        results = part_1(jobs_that_run(mode, ["plan"]))
        assert results == {"plan": "failure", **dict.fromkeys(PART_1_JOBS[1:], skip)}, mode
    # A failed pack stops the picks and the v3 cells, never the other cells; a failed picks job
    # stops the v3 cells; a failed cell stops nothing of part 1.
    assert part_1(jobs_that_run("registered", ["v3-pack"])) == {
        "plan": ok,
        "v3-pack": "failure",
        "v3-picks": skip,
        "cell": ok,
        "v3-cell": skip,
    }
    for mode in ("registered", "rehearsal"):
        results = part_1(jobs_that_run(mode, ["v3-picks"]))
        assert (results["v3-picks"], results["cell"], results["v3-cell"]) == (
            "failure",
            ok,
            skip,
        ), mode
        results = part_1(jobs_that_run(mode, ["cell"]))
        assert results["v3-cell"] == ok, mode
    # The v3-cell job never runs on an empty matrix, whatever the mode.
    for mode in MODES:
        assert jobs_that_run(mode, v3_count="0")["v3-cell"] == skip, mode
    assert "needs.plan.outputs.v3_count != '0'" in graph["v3-cell"]["if"]
    # A job after one its mode skips can run only through !cancelled() (GitHub skips the
    # dependents of a skipped job otherwise), and then says which result it accepts.
    for name in ("v3-picks", "v3-cell"):
        condition = graph[name]["if"]
        assert "!cancelled()" in condition and "always()" not in condition, name
        assert "needs.plan.result == 'success'" in condition, name
        assert "needs.v3-pack.result == 'skipped'" in condition, name
        assert "inputs.mode == 'rehearsal'" in condition, name
    assert graph["v3-pack"]["if"] == "${{ inputs.mode == 'registered' }}"


# ---- the plan job -------------------------------------------------------------------------------


def test_plan_outputs_come_from_the_matrix_and_the_gate(tmp_path):
    assert jobs()["plan"]["outputs"] == {
        "cells": "${{ steps.matrix.outputs.cells }}",
        "v3_cells": "${{ steps.matrix.outputs.v3_cells }}",
        "cell_ids": "${{ steps.matrix.outputs.cell_ids }}",
        "v3_count": "${{ steps.matrix.outputs.v3_count }}",
        "v3_pack_sha256": "${{ steps.gate.outputs.v3_pack_sha256 }}",
        "registration_sha256": "${{ steps.gate.outputs.registration_sha256 }}",
    }
    # The matrix step's outputs are what the plan script writes (no data is read).
    matrix = steps("plan")[index_of("plan", "scripts/v4_run_plan.py")]
    assert matrix["id"] == "matrix" and "if" not in matrix
    assert run_text(matrix) == (
        'python scripts/v4_run_plan.py matrix --mode "$MODE" --github-output "$GITHUB_OUTPUT"'
    )
    for mode in MODES:
        out = tmp_path / f"{mode}.txt"
        assert v4_run_plan.main(["matrix", "--mode", mode, "--github-output", str(out)]) == 0
        written = outputs_of(out)
        assert {"cells", "v3_cells", "cell_ids", "v3_count"} <= set(written), mode
        assert written["v3_count"] == V3_COUNT[mode] == ("0" if mode == "timing" else "4")
        assert len(written["cell_ids"].split(",")) == 44
    # The gate writes the run manifest's V3 pack pin among its outputs.
    gated = SimpleNamespace(
        registration=SimpleNamespace(code_pin="1" * 40),
        manifest=SimpleNamespace(
            v3_pack_sha256=PLAN_PACK, data={key: "x" for key in v4_registration._DATA_ORDER}
        ),
    )
    assert ("v3_pack_sha256", PLAN_PACK) in v4_registration.github_outputs(gated)


def test_plan_runs_gate_dispatch_check_and_data_run_check_before_any_download_in_registered_mode(
    tmp_path,
):
    events = trace("plan", "registered", tmp_path)
    data_run_check = [
        ["gh", "api", f"repos/owner/repository/actions/runs/{DATA_RUN}"],
        ["python", "scripts/v4_run_guard.py", "--data-run", DATA_RUN, "--commit", COMMIT],
    ]
    # The pipeline's two ends run side by side, so their lines may come in either order.
    pipeline = [
        i for i, event in enumerate(events) if event[0] == "call" and event[1] in data_run_check
    ]
    assert len(pipeline) == 2 and pipeline[1] == pipeline[0] + 1
    first = pipeline[0]
    ordered = [*events[:first], ("call", "<data-run check>"), *events[first + 2 :]]
    assert ordered == [
        ("call", ["python", "scripts/v4_run_plan.py", "matrix", "--mode", "registered",
                  "--github-output", "$GITHUB_OUTPUT"]),
        # The job gate first of all: the registration is the dispatched one, and the checkout
        # is the code pin plus the registration files (Rulings G2, G3). The guard below trusts
        # the manifest it is given; the gate is what holds that manifest to the registration.
        ("call", ["python", "scripts/v4_registration.py", "gate", "--repo", ".", "--mode",
                  "registered", "--registration-sha256", INPUT_SHA,
                  "--github-output", "$GITHUB_OUTPUT"]),
        # One dispatch per registration (Ruling G4), refusing, not report-only.
        ("call", ["python", "scripts/v4_registration.py", "dispatch-check", "--mode",
                  "registered", "--registration-sha256", INPUT_SHA]),
        # The data run, through GitHub's API, before anything of it is downloaded (Ruling G5).
        ("call", "<data-run check>"),
        ("download", {"name": "v4-data", "run-id": DATA_RUN, "github-token": "fake-token",
                      "path": "v4data"}),
        ("call", ["python", "scripts/v4_run_guard.py", "--data", "v4data", "--manifest",
                  MANIFEST]),
        ("upload", {"name": "v4-data", "path": "v4data/", "if-no-files-found": "error",
                    "retention-days": 1}),
    ]  # fmt: skip
    # Each command is one its CLI's own parser reads as that check.
    gate, check = calls_of(events, "v4_registration.py")
    args = v4_registration.build_parser().parse_args(gate)
    assert (args.command, args.repo, args.mode, args.registration_sha256) == (
        "gate",
        ".",
        "registered",
        INPUT_SHA,
    )
    args = v4_registration.build_parser().parse_args(check)
    assert (args.command, args.mode, args.report_only, args.judge_all) == (
        "dispatch-check",
        "registered",
        False,
        False,
    )
    assert v4_registration._option_problem(args) is None
    for guard in calls_of(events, "v4_run_guard.py"):
        v4_run_guard.build_parser().parse_args(guard)
    # The dispatch check reads GitHub with the job's own token, and the data-run check too.
    plan = steps("plan")
    (dispatch,) = [s for s in plan if "dispatch-check" in run_text(s)]
    assert dispatch["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    data_run = plan[index_of("plan", "--data-run")]
    assert data_run["id"] == "data_run"
    assert data_run["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPOSITORY": "${{ github.repository }}",
        "COMMIT": "${{ github.sha }}",
    }
    # The download names the data run by the id the check validated and accepted.
    (download,) = [s for s in plan if is_download(s)]
    assert download["with"]["run-id"] == "${{ steps.data_run.outputs.data_run }}"


def test_plan_in_rehearsal_builds_and_gates_the_world_and_guards_its_synthetic_data(tmp_path):
    events = trace("plan", "rehearsal", tmp_path)
    assert events == [
        ("call", ["python", "scripts/v4_run_plan.py", "matrix", "--mode", "rehearsal",
                  "--github-output", "$GITHUB_OUTPUT"]),
        ("call", ["python", "scripts/v4_rehearsal.py", "world", "--scale", "rehearsal",
                  "--out", "world"]),
        ("call", ["tar", "-xf", "world/world.tar", "-C", "world"]),
        ("call", ["python", "-c", events[3][1][2], "world/rehearsal.json"]),
        # The real gate, on the world's own git repository, with the world's registration.
        ("call", ["python", "scripts/v4_registration.py", "gate", "--repo", "world/repo",
                  "--mode", "rehearsal", "--registration-sha256", WORLD_SHA,
                  "--github-output", "$GITHUB_OUTPUT"]),
        # Report-only, on the rehearsal's own title (the dispatch's input: none).
        ("call", ["python", "scripts/v4_registration.py", "dispatch-check", "--mode",
                  "rehearsal", "--report-only", "--registration-sha256", ""]),
        ("call", ["python", "scripts/v4_run_guard.py", "--data", "world/v4data",
                  "--synthetic"]),
        ("upload", {"name": "v4-data", "path": "world/v4data/", "if-no-files-found": "error",
                    "retention-days": 1}),
        ("upload", {"name": "v4-v3-pack", "path": "world/v3pack/", "if-no-files-found": "error",
                    "retention-days": 1, "compression-level": 0}),
        ("upload", {"name": "v4-rehearsal-world", "path": "world/world.tar\nworld/rehearsal.json\n",
                    "if-no-files-found": "error", "retention-days": 1}),
    ]  # fmt: skip
    for call in calls_of(events, "v4_registration.py"):
        args = v4_registration.build_parser().parse_args(call)
        if args.command == "dispatch-check":
            assert v4_registration._option_problem(args) is None
    args = v4_rehearsal.build_parser().parse_args(calls_of(events, "v4_rehearsal.py")[0])
    assert (args.command, args.scale, args.out) == ("world", "rehearsal", Path("world"))


def test_plan_in_timing_builds_the_world_and_neither_gates_nor_checks_a_dispatch(tmp_path):
    # No registration exists for a timing run: no gate, no dispatch check, no data run.
    events = trace("plan", "timing", tmp_path)
    assert events == [
        ("call", ["python", "scripts/v4_run_plan.py", "matrix", "--mode", "timing",
                  "--github-output", "$GITHUB_OUTPUT"]),
        ("call", ["python", "scripts/v4_rehearsal.py", "world", "--scale", "timing",
                  "--out", "world"]),
        ("call", ["python", "scripts/v4_run_guard.py", "--data", "world/v4data",
                  "--synthetic"]),
        ("upload", {"name": "v4-data", "path": "world/v4data/", "if-no-files-found": "error",
                    "retention-days": 1}),
    ]  # fmt: skip


def test_plans_gate_writes_the_registration_only_once_the_gate_accepts(tmp_path):
    # The plan's registration_sha256 is the one the gate accepted: the dispatched one in a
    # registered run, the world's in a rehearsal. A refused gate writes none.
    gate = steps("plan")[index_of("plan", "v4_registration.py gate")]
    assert gate["id"] == "gate"
    assert gate["env"] == {
        "WORLD_REGISTRATION_SHA256": "${{ steps.world.outputs.registration_sha256 }}"
    }
    for mode, sha in (("registered", INPUT_SHA), ("rehearsal", WORLD_SHA)):
        known = {**context(mode), "steps.world.outputs.registration_sha256": WORLD_SHA}
        done, _, written = run_recorded("plan", gate, mode, tmp_path / mode, known=known)
        assert done.returncode == 0, done.stderr
        assert written == {"registration_sha256": sha}, mode
        done, _, written = run_recorded(
            "plan",
            gate,
            mode,
            tmp_path / f"{mode}-refused",
            known=known,
            extra={"STUB_STATUS": "1"},
        )
        assert done.returncode != 0 and written == {}, mode


def test_plans_data_run_step_refuses_an_id_that_is_not_one(tmp_path):
    step = steps("plan")[index_of("plan", "--data-run")]
    done, calls, written = run_recorded("plan", step, "registered", tmp_path / "good")
    assert done.returncode == 0, done.stderr
    assert written == {"data_run": DATA_RUN}
    for index, bad in enumerate(("", "0", "012", "12a", "1/../2", "1 2", "1" * 21)):
        known = {**context("registered"), "inputs.data_run": bad}
        done, calls, written = run_recorded(
            "plan", step, "registered", tmp_path / str(index), known=known
        )
        assert done.returncode != 0 and "::error::" in done.stderr, bad
        assert calls == [] and written == {}, bad  # nothing asked of GitHub, nothing kept


def test_plans_world_step_unpacks_the_world_and_keeps_its_registration_pin(tmp_path):
    step = steps("plan")[index_of("plan", "world/world.tar")]
    assert step["id"] == "world" and step["if"] == "${{ inputs.mode == 'rehearsal' }}"

    def world(folder: Path, document: str) -> Path:
        (folder / "world").mkdir(parents=True)
        (folder / "world" / "rehearsal.json").write_text(document, encoding="ascii")
        readme = folder / "README"
        readme.write_text("synthetic", encoding="ascii")
        with tarfile.open(folder / "world" / "world.tar", "w") as archive:
            archive.add(readme, arcname="repo/README")
        return folder

    pin = "9" * 64
    for name, value, accepted in (
        ("good", f'"{pin}"', True),
        ("null", "null", False),
        ("short", '"abc"', False),
        ("upper", f'"{pin.upper().replace("9", "A")}"', False),
    ):
        folder = world(tmp_path / name, '{"registration_sha256":' + value + "}")
        output = folder / "github_output"
        output.write_text("", encoding="ascii")
        done = run_script(
            str(step["run"]), folder, {"GITHUB_OUTPUT": output.as_posix()}, prelude=REAL_PYTHON
        )
        assert (done.returncode == 0) is accepted, (name, done.stderr)
        assert (folder / "world" / "repo" / "README").is_file()
        assert outputs_of(output) == ({"registration_sha256": pin} if accepted else {}), name
        if not accepted:
            assert "::error::" in done.stderr, name


# ---- the rehearsal script and the data guard ----------------------------------------------------


def test_registered_steps_never_call_the_rehearsal_script():
    # A step that calls the rehearsal script runs in no registered dispatch, whatever the jobs
    # and steps before it did: its own if excludes a registered run, or its job's does (the
    # scenarios job is a rehearsal's only).
    found = 0
    for name, job in jobs().items():
        for step in job["steps"]:
            if "v4_rehearsal.py" not in str(step.get("run", "")):
                continue
            found += 1
            assert "if" in step or "if" in job, (name, step.get("name"))
            assert not can_run(name, step, "registered"), (name, step.get("name"))
            assert step_runs(step, "rehearsal") or step_runs(step, "timing"), name
    # The plan's world, the rehearsal's picks, the forced cells, the scenarios and their check.
    assert found >= 5
    # The world's scale is the mode: the script's own parser refuses any other.
    world = steps("plan")[index_of("plan", "v4_rehearsal.py world")]
    command = shlex.split(run_text(world))[2:]
    for mode in ("rehearsal", "timing"):
        args = v4_rehearsal.build_parser().parse_args([w.replace("$MODE", mode) for w in command])
        assert (args.command, args.scale, args.out) == ("world", mode, Path("world"))
    with pytest.raises(SystemExit):
        v4_rehearsal.build_parser().parse_args([w.replace("$MODE", "registered") for w in command])


def test_every_guard_passes_its_data_and_refuses_real_data_outside_the_registered_run(tmp_path):
    # v4-d03: a rehearsal and a timing run open synthetic data only (--synthetic); a registered
    # run only the registered data (--manifest). Every call names its data folder.
    for job, data in (("plan", None), ("cell", "v4data")):
        step = steps(job)[index_of(job, "v4_run_guard.py --data ")]
        assert "if" not in step, job  # every mode guards
        for mode in MODES:
            done, calls, _ = run_recorded(job, step, mode, tmp_path / job / mode)
            assert done.returncode == 0, done.stderr
            folder = data or ("v4data" if mode == "registered" else "world/v4data")
            kind = ["--manifest", MANIFEST] if mode == "registered" else ["--synthetic"]
            assert calls == [["python", "scripts/v4_run_guard.py", "--data", folder, *kind]], mode
            args = v4_run_guard.build_parser().parse_args(calls[0][2:])
            assert args.data == Path(folder), mode
        # Any other mode is refused before the guard runs: no data is opened unguarded.
        done, calls, _ = run_recorded(job, step, "smoke", tmp_path / job / "smoke")
        assert done.returncode != 0 and calls == [] and "::error::" in done.stderr, job


# ---- the cell jobs ------------------------------------------------------------------------------


def test_cells_need_plan_and_gate_first_then_guard(tmp_path):
    job = jobs()["cell"]
    assert needs(job) == ["plan"] and "if" not in job
    assert job["strategy"] == {
        "fail-fast": False,
        "max-parallel": 20,
        "matrix": "${{ fromJSON(needs.plan.outputs.cells) }}",
    }
    assert job["env"] == {
        "CELL": "${{ matrix.cell }}",
        "ARM": "${{ matrix.arm }}",
        "CAPITAL": "${{ matrix.capital }}",
        "COSTS": "${{ matrix.costs }}",
        "RUN_REGISTRATION_SHA256": "${{ needs.plan.outputs.registration_sha256 }}",
    }
    cell_steps = steps("cell")
    (download,) = [
        i for i, s in enumerate(cell_steps) if is_download(s) and s["with"]["name"] == "v4-data"
    ]
    assert cell_steps[download]["with"] == {"name": "v4-data", "path": "v4data"}  # this run's
    guard = index_of("cell", "scripts/v4_run_guard.py")
    gate = index_of("cell", "v4_registration.py gate")
    replay = index_of("cell", "scripts/v4_cell.py")
    # The job gate runs first (Ruling G5), before the run's data is downloaded or guarded.
    assert SETUP_STEPS <= gate < download < guard < replay

    # What runs before the cell, in each mode: the gate again (registered: on this checkout;
    # rehearsal: on the world's repository, downloaded first; timing: none), then the guard of
    # the mode's data.
    for mode in MODES:
        events = trace("cell", mode, tmp_path / mode)
        timed = [i for i, event in enumerate(events) if event[0] == "timed"]
        before = events[: timed[0]]
        gate_repo = {"registered": ".", "rehearsal": "world/repo"}.get(mode)
        expected: list[tuple[Any, ...]] = []
        if mode == "rehearsal":
            expected += [
                ("download", {"name": "v4-rehearsal-world", "path": "world"}),
                ("call", ["tar", "-xf", "world/world.tar", "-C", "world"]),
            ]
        if gate_repo is not None:
            expected.append(
                ("call", ["python", "scripts/v4_registration.py", "gate", "--repo", gate_repo,
                          "--mode", mode, "--registration-sha256", PLAN_SHA])
            )  # fmt: skip
        expected += [
            ("download", {"name": "v4-data", "path": "v4data"}),
            ("call", ["python", "scripts/v4_run_guard.py", "--data", "v4data",
                      *(["--manifest", MANIFEST] if mode == "registered" else ["--synthetic"])]),
        ]  # fmt: skip
        assert before == expected, mode
        for call in calls_of(before, "v4_registration.py"):
            assert v4_registration.build_parser().parse_args(call).mode == mode
    # A gate that refused skips everything after it: no data is downloaded, nothing replayed.
    for mode in ("registered", "rehearsal"):
        after = steps_that_run("cell", mode, failing=[gate])
        assert {after[download], after[guard], after[replay]} == {"skipped"}, mode


def test_v3_cell_checks_both_pins_before_anything_runs(tmp_path):
    job = jobs()["v3-cell"]
    assert job["strategy"] == {
        "fail-fast": False,
        "matrix": "${{ fromJSON(needs.plan.outputs.v3_cells) }}",
    }
    assert job["env"] == {
        "CELL": "${{ matrix.cell }}",
        "CAPITAL": "${{ matrix.capital }}",
        "COSTS": "${{ matrix.costs }}",
        "PACK_SHA256": "${{ needs.plan.outputs.v3_pack_sha256 }}",
        "PICKS_SHA256": "${{ needs.v3-picks.outputs.picks_sha256 }}",
        "RUN_REGISTRATION_SHA256": "${{ needs.plan.outputs.registration_sha256 }}",
    }
    v3_steps = steps("v3-cell")
    downloads = {i: s["with"] for i, s in enumerate(v3_steps) if is_download(s) and "if" not in s}
    assert list(downloads.values()) == [
        {"name": "v4-v3-pack", "path": "v3pack"},
        {"name": f"v4-v3-picks{ATTEMPT}", "path": "picks"},
    ]
    pins = index_of("v3-cell", "sha256sum")
    gate = index_of("v3-cell", "v4_registration.py gate")
    replay = index_of("v3-cell", "scripts/v4_v3_cell.py")
    # The job gate first, as in the cell job; the pins are checked before anything reads the
    # files.
    assert SETUP_STEPS <= gate < min(downloads) and max(downloads) < pins < replay
    assert "if" not in v3_steps[pins]

    # The check, run for real on small files: a pack written as write_v3_pack writes one, whose
    # pin is the SHA-256 of the JSON it compresses, and a picks file, whose pin is the SHA-256 of
    # its own bytes.
    pack, pack_file_digest = write_pack(tmp_path / PACK_PATH)
    (tmp_path / "picks").mkdir()
    (tmp_path / PICKS_PATH).write_bytes(b'{"picks":{}}')
    picks = hashlib.sha256(b'{"picks":{}}').hexdigest()
    script = str(v3_steps[pins]["run"])
    done = run_script(script, tmp_path, {"PACK_SHA256": pack, "PICKS_SHA256": picks})
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    for pack_pin, picks_pin in (
        (picks, picks),
        (pack, pack),
        ("", picks),
        (pack, ""),
        ("", ""),
        (pack_file_digest, picks),  # the gzip file's own SHA-256 is not the pack's pin
    ):
        done = run_script(script, tmp_path, {"PACK_SHA256": pack_pin, "PICKS_SHA256": picks_pin})
        assert done.returncode != 0 and "::error::" in done.stderr, (pack_pin, picks_pin)
    for missing in (PACK_PATH, PICKS_PATH):
        moved = tmp_path / "moved"
        (tmp_path / missing).rename(moved)
        done = run_script(script, tmp_path, {"PACK_SHA256": pack, "PICKS_SHA256": picks})
        assert done.returncode != 0, missing
        moved.rename(tmp_path / missing)
    # A pack that is not gzip fails the step, even in a bash without pipefail: the step sets it.
    (tmp_path / PACK_PATH).write_bytes(b"not a gzip file")
    empty = hashlib.sha256(b"").hexdigest()  # what a failed gzip would pipe to sha256sum
    for pipefail in (True, False):
        env = {"PACK_SHA256": empty, "PICKS_SHA256": picks}
        done = run_script(script, tmp_path, env, pipefail=pipefail)
        assert done.returncode != 0, pipefail

    # The gate again before the cell: on this checkout, or on the rehearsal world's repository,
    # which the job downloads and unpacks first.
    for mode, repo in (("registered", "."), ("rehearsal", "world/repo")):
        done, calls, _ = run_recorded("v3-cell", v3_steps[gate], mode, tmp_path / mode)
        assert done.returncode == 0, done.stderr
        assert calls == [
            ["python", "scripts/v4_registration.py", "gate", "--repo", repo, "--mode", mode,
             "--registration-sha256", PLAN_SHA]
        ]  # fmt: skip
    world = [
        i
        for i, s in enumerate(v3_steps)
        if (is_download(s) and s["with"]["name"] == "v4-rehearsal-world")
        or "world/world.tar" in run_text(s)
    ]
    assert len(world) == 2 and max(world) < gate
    for index in world:
        assert v3_steps[index]["if"] == "${{ inputs.mode == 'rehearsal' }}"


def test_cell_stdout_goes_to_dev_null_under_gnu_time():
    values = {
        "$ARM": "v4_faster",
        "$CAPITAL": "1000",
        "$COSTS": "2",
        "$PACK_SHA256": PLAN_PACK,
        "$PICKS_SHA256": PICKS_SHA,
    }
    parsers = {"cell": v4_cell.build_parser(), "v3-cell": v4_v3_cell.build_parser()}
    for job, command in REPLAYS.items():
        job_steps = steps(job)
        check = index_of(job, "-x /usr/bin/time")
        replay = index_of(job, "/usr/bin/time -v")
        timing = index_of(job, "scripts/v4_cells_timing.py")
        assert check < replay < timing, job
        assert "::error::" in run_text(job_steps[check]) and "exit 1" in run_text(job_steps[check])
        # The cell's own line holds its outcome, a result: its standard output goes to /dev/null,
        # never to the public log.
        assert run_text(job_steps[replay]) == f"mkdir -p out {TIMED}{command}", job
        assert command.endswith(" > /dev/null") and command.count(">") == 1
        words = [values.get(w, w) for w in shlex.split(command.removesuffix(" > /dev/null"))[2:]]
        args = parsers[job].parse_args(words)
        assert (args.command, args.capital, args.costs, args.out) == ("run", 1000, 2, Path("out"))
        if job == "cell":
            assert (args.data, args.arm) == (Path("v4data"), "v4_faster")
        else:
            assert (args.pack, args.pack_sha256) == (Path(PACK_PATH), PLAN_PACK)
            assert (args.picks, args.picks_sha256) == (Path(PICKS_PATH), PICKS_SHA)
        assert job_steps[timing]["id"] == "timing" and "if" not in job_steps[timing]
        assert run_text(job_steps[timing]) == TIMING_STEP
        parsed = v4_cells_timing.build_parser().parse_args(shlex.split(TIMING_STEP)[2:])
        assert (parsed.time_file, parsed.cell_dir) == (Path("out/$CELL.time"), Path("out/$CELL"))
        # The uploads come last, after a successful run or a failed timing step only, so a failed
        # replay (or guard, gate or pin check) uploads nothing and the job still ends red.
        uploads = [i for i, s in enumerate(job_steps) if is_upload(s)]
        assert min(uploads) > timing and uploads == list(range(min(uploads), len(job_steps)))
        for index in uploads:
            assert job_steps[index]["if"] in (UPLOAD_CONDITION, TIMING_UPLOAD_CONDITION), job
        for mode in MODES:
            if job == "v3-cell" and mode == "timing":
                continue
            after_timing = steps_that_run(job, mode, failing=[timing])
            after_replay = steps_that_run(job, mode, failing=[replay])
            for index in uploads:
                # After a failed timing step the cell's folder and summary are uploaded, never
                # its timing alone: a failed timing step wrote no timing.json.
                expected = job_steps[index]["if"] == UPLOAD_CONDITION
                assert (after_timing[index] == "success") is expected, (job, mode, index)
                assert after_replay[index] == "skipped", (job, mode, index)
    # The other CLIs whose standard output goes to /dev/null, and that no step prints a result,
    # are in test_logs_counts_only.


# ---- the artifacts ------------------------------------------------------------------------------


def test_every_upload_kept_one_day_and_named_per_W1():
    names: dict[str, list[str]] = {}
    for job_name, job in jobs().items():
        for step in job["steps"]:
            if not is_upload(step):
                continue
            spec = step["with"]
            assert spec["retention-days"] == 1, (job_name, spec)  # v4-d10
            assert spec["if-no-files-found"] == "error", (job_name, spec)
            # Nothing replaces an artifact: a fixed name uploaded twice fails closed.
            assert "overwrite" not in spec, (job_name, spec)
            name = spec["name"]
            assert name in FIXED_NAMES or name.endswith(ATTEMPT), (job_name, name)
            names.setdefault(job_name, []).append(name)
    cell = MATRIX_CELL
    assert {job: names[job] for job in PART_1_JOBS} == {
        "plan": ["v4-data", "v4-data", "v4-v3-pack", "v4-rehearsal-world"],
        "v3-pack": ["v4-v3-pack"],
        "v3-picks": [f"v4-v3-picks{ATTEMPT}"],
        "cell": [f"v4-cell-{cell}{ATTEMPT}", f"v4-summary-{cell}{ATTEMPT}",
                 f"v4-timing-cell-{cell}{ATTEMPT}"],
        # The analysis downloads v4-cell-*: a v3 cell never uploads under that name.
        "v3-cell": [f"v4-v3-cell-{cell}{ATTEMPT}", f"v4-summary-{cell}{ATTEMPT}"],
    }  # fmt: skip
    # In a run of any mode, each fixed name is uploaded once at most, by the job that made it.
    expected = {
        "registered": {"v4-data": "plan", "v4-v3-pack": "v3-pack"},
        "rehearsal": {"v4-data": "plan", "v4-v3-pack": "plan", "v4-rehearsal-world": "plan"},
        "timing": {"v4-data": "plan"},
    }
    for mode in MODES:
        ran = jobs_that_run(mode)
        fixed = [
            (s["with"]["name"], job)
            for job in jobs()
            if ran[job] == "success"
            for s in steps(job)
            if is_upload(s) and s["with"]["name"] in FIXED_NAMES and step_runs(s, mode)
        ]
        assert sorted(fixed) == sorted(expected[mode].items()), mode
    # A cell's folder, its summary (summary.json and receipt.json alone: what the verdict reads)
    # and, in a timing run, its timing.json alone.
    for job in ("cell", "v3-cell"):
        paths = {
            s["with"]["name"].split("-${{")[0]: s["with"]["path"].strip().splitlines()
            for s in steps(job)
            if is_upload(s)
        }
        prefix = "v4-cell-" if job == "cell" else "v4-v3-cell-"
        assert paths[prefix.rstrip("-")] == [f"out/{cell}/"], job
        assert paths["v4-summary"] == [f"out/{cell}/summary.json", f"out/{cell}/receipt.json"]
    (timing,) = [
        s for s in steps("cell") if is_upload(s) and s["with"]["name"].startswith("v4-timing-")
    ]
    assert timing["with"]["path"] == f"out/{cell}/timing.json"
    assert timing["if"] == TIMING_UPLOAD_CONDITION
    for mode in ("registered", "rehearsal"):
        assert not step_runs(timing, mode), mode
    # In a timing run, uploaded once the timing step wrote its file, and never after a timing
    # step that failed: it wrote no timing.json, and the upload would fail on the missing file.
    upload = index_of_upload("cell", f"v4-timing-cell-{cell}{ATTEMPT}")
    timed = index_of("cell", "scripts/v4_cells_timing.py")
    assert steps_that_run("cell", "timing")[upload] == "success"
    assert steps_that_run("cell", "timing", failing=[timed])[upload] == "skipped"
    kept = [
        index_of_upload("cell", f"v4-cell-{cell}{ATTEMPT}"),
        index_of_upload("cell", f"v4-summary-{cell}{ATTEMPT}"),
    ]
    for index in kept:  # the replay succeeded: its folder and summary are kept
        assert steps_that_run("cell", "timing", failing=[timed])[index] == "success"


# ---- the V3 pack and the picks ------------------------------------------------------------------


def test_v3_pack_pin_equals_v4_v3_and_the_pack_script(tmp_path):
    pin = workflow()["env"]["V3_PACK_SHA256"]
    v3 = yaml.safe_load(V3_WORKFLOW.read_text(encoding="utf-8"))
    manifest = yaml.safe_load((ROOT / "config" / "v3_1_run_manifest.json").read_text("utf-8"))
    assert pin == v3["env"]["V3_PACK_SHA256"] == v4_v3_pack.EXPECTED_PACK_SHA256
    assert pin == manifest["v3_pack_sha256"]
    assert code().count(pin) == 1

    job = jobs()["v3-pack"]
    assert job["env"] == {"PACK_SHA256": "${{ needs.plan.outputs.v3_pack_sha256 }}"}
    job_steps = job["steps"]
    scripts = [run_text(s) for s in job_steps if "scripts/" in str(s.get("run", ""))]
    assert scripts == ["python scripts/v4_v3_pack.py --work work --out out"]
    args = v4_v3_pack.build_parser().parse_args(shlex.split(scripts[0])[2:])
    assert (args.work, args.out, args.repo) == (Path("work"), Path("out"), Path("."))
    manifest_check = index_of("v3-pack", '[ "$PACK_SHA256" != "$V3_PACK_SHA256" ]')
    build = index_of("v3-pack", "scripts/v4_v3_pack.py")
    check = index_of("v3-pack", "sha256sum")
    (upload,) = [i for i, s in enumerate(job_steps) if is_upload(s)]
    # The manifest's pin is checked before the long fetch, the pack's after it.
    assert SETUP_STEPS == manifest_check < build < check < upload == len(job_steps) - 1
    for step in job_steps[manifest_check:]:
        assert "if" not in step and "continue-on-error" not in step  # a refusal uploads nothing
    assert job_steps[upload]["with"] == {
        "name": "v4-v3-pack",
        "path": "out/",
        "if-no-files-found": "error",
        "retention-days": 1,
        "compression-level": 0,
    }

    # Before the fetch, run for real: the run manifest's pin must be V3.1's.
    script = str(job_steps[manifest_check]["run"])
    done = run_script(script, tmp_path, {"V3_PACK_SHA256": pin, "PACK_SHA256": pin})
    assert done.returncode == 0 and done.stdout == "", done.stderr
    for plan_pin in ("0" * 64, "", pin.upper()):
        done = run_script(script, tmp_path, {"V3_PACK_SHA256": pin, "PACK_SHA256": plan_pin})
        assert done.returncode != 0 and "::error::" in done.stderr, plan_pin

    # After the build, run for real on a pack written as write_v3_pack writes one: its pin is the
    # SHA-256 of the JSON the file compresses, and it must be both V3.1's and the plan's.
    pack = tmp_path / "out" / v4_v3_pack.PACK_FILE
    digest, file_digest = write_pack(pack)
    script = str(job_steps[check]["run"])
    done = run_script(script, tmp_path, {"V3_PACK_SHA256": digest, "PACK_SHA256": digest})
    assert done.returncode == 0 and done.stdout == "", done.stderr
    for v3_pin, plan_pin in (
        (digest, "0" * 64),
        ("0" * 64, digest),
        (digest, ""),
        ("", ""),
        (file_digest, file_digest),  # the gzip file's own SHA-256 is not the pack's pin
    ):
        done = run_script(script, tmp_path, {"V3_PACK_SHA256": v3_pin, "PACK_SHA256": plan_pin})
        assert done.returncode != 0 and "::error::" in done.stderr, (v3_pin, plan_pin)
    # A file that is not gzip fails the step, even in a bash without pipefail: the step sets it.
    pack.write_bytes(b"not a gzip file")
    empty = hashlib.sha256(b"").hexdigest()  # what a failed gzip would pipe to sha256sum
    for pipefail in (True, False):
        done = run_script(
            script, tmp_path, {"V3_PACK_SHA256": empty, "PACK_SHA256": empty}, pipefail=pipefail
        )
        assert done.returncode != 0, pipefail
    pack.unlink()
    for pipefail in (True, False):
        done = run_script(
            script, tmp_path, {"V3_PACK_SHA256": empty, "PACK_SHA256": empty}, pipefail=pipefail
        )
        assert done.returncode != 0, pipefail


def test_v3_picks_runs_the_modes_picks_and_pins_the_file_it_wrote(tmp_path):
    job = jobs()["v3-picks"]
    assert job["outputs"] == {"picks_sha256": "${{ steps.pin.outputs.picks_sha256 }}"}
    assert job["env"] == {"PACK_SHA256": "${{ needs.plan.outputs.v3_pack_sha256 }}"}
    job_steps = job["steps"]
    pin = [i for i, s in enumerate(job_steps) if s.get("id") == "pin"]
    (upload,) = [i for i, s in enumerate(job_steps) if is_upload(s)]
    assert pin == [upload - 1] and upload == len(job_steps) - 1
    assert "if" not in job_steps[pin[0]] and "if" not in job_steps[upload]
    assert job_steps[upload]["with"] == {
        "name": f"v4-v3-picks{ATTEMPT}",
        "path": "picks/",
        "if-no-files-found": "error",
        "retention-days": 1,
    }
    expected = {
        "registered": (
            [{"name": "v4-v3-pack", "path": "v3pack"}],
            f'python scripts/v4_v3_cell.py picks --pack {PACK_PATH} --pack-sha256 "$PACK_SHA256" '
            "--out picks",
        ),
        "rehearsal": (
            [
                {"name": "v4-rehearsal-world", "path": "world"},
                {"name": "v4-v3-pack", "path": "world/v3pack"},
            ],
            "python scripts/v4_rehearsal.py picks --world world --out picks",
        ),
    }
    for mode, (downloads, picks) in expected.items():
        running = [s for s in job_steps if step_runs(s, mode)]
        assert [s["with"] for s in running if is_download(s)] == downloads, mode
        scripts = [run_text(s) for s in running if "scripts/" in str(s.get("run", ""))]
        assert scripts == [picks], mode
        last_download = max(i for i, s in enumerate(job_steps) if is_download(s))
        assert last_download < index_of("v3-picks", picks.split(" --")[0]) < pin[0]
    args = v4_v3_cell.build_parser().parse_args(
        [w.replace("$PACK_SHA256", PLAN_PACK) for w in shlex.split(expected["registered"][1])[2:]]
    )
    assert (args.command, args.pack, args.pack_sha256, args.out) == (
        "picks",
        Path(PACK_PATH),
        PLAN_PACK,
        Path("picks"),
    )
    args = v4_rehearsal.build_parser().parse_args(shlex.split(expected["rehearsal"][1])[2:])
    assert (args.command, args.world, args.out) == ("picks", Path("world"), Path("picks"))

    # The picks' pin is the digest of the file the step wrote, never a value from outside.
    step = job_steps[pin[0]]
    (tmp_path / "picks").mkdir()
    raw = b'{"picks":{}}'
    (tmp_path / PICKS_PATH).write_bytes(raw)
    output = tmp_path / "github_output"
    done = run_script(str(step["run"]), tmp_path, {"GITHUB_OUTPUT": output.as_posix()})
    assert done.returncode == 0, done.stderr
    assert output.read_text(encoding="ascii") == f"picks_sha256={hashlib.sha256(raw).hexdigest()}\n"
    assert done.stdout == ""
    (tmp_path / PICKS_PATH).unlink()
    output.write_text("", encoding="ascii")
    done = run_script(str(step["run"]), tmp_path, {"GITHUB_OUTPUT": output.as_posix()})
    assert done.returncode != 0 and output.read_text(encoding="ascii") == ""


# ---- part 2: the scenarios, verdict, analysis and status jobs -----------------------------------


def scenario_folders(folder: Path) -> None:
    """``folder/scenarios/<name>/`` for every scenario of the table and its ``scenarios.json``,
    as ``v4_rehearsal.py scenarios`` writes them: what the step judging every scenario reads."""
    for name in v4_rehearsal.SCENARIOS:
        (folder / "scenarios" / name).mkdir(parents=True)
    (folder / "scenarios" / v4_rehearsal.SCENARIOS_FILE).write_bytes(b"{}")


def upload_event(name: str, path: str) -> tuple[str, dict[str, Any]]:
    """A traced upload of this run's first attempt, kept one day."""
    spec = {"name": name, "path": path, "if-no-files-found": "error", "retention-days": 1}
    return ("upload", spec)


def test_scenarios_job_forces_each_stop_outcome_through_the_real_clis(tmp_path):
    job = jobs()["scenarios"]
    assert needs(job) == ["plan", "v3-picks"]
    # A rehearsal's only, after the picks. The v3-pack job is skipped in a rehearsal, and GitHub
    # skips the dependents of a skipped job, transitively, hence !cancelled().
    assert job["if"] == (
        "${{ !cancelled() && inputs.mode == 'rehearsal' && needs.plan.result == 'success' "
        "&& needs.v3-picks.result == 'success' }}"
    )
    assert job["env"] == {"PICKS_SHA256": "${{ needs.v3-picks.outputs.picks_sha256 }}"}
    for mode in ("registered", "timing"):
        assert not job_can_run("scenarios", mode), mode
    assert jobs_that_run("rehearsal", ["v3-picks"])["scenarios"] == "skipped"

    events = trace("scenarios", "rehearsal", tmp_path)
    forced = calls_of(events, "v4_rehearsal.py")
    assert events == [
        # The world folder force reads (rehearsal.json, the data pack and the V3 pack, as the
        # plan built them) and this attempt's picks, the picks job's own.
        ("download", {"name": "v4-rehearsal-world", "path": "world"}),
        ("download", {"name": "v4-data", "path": "world/v4data"}),
        ("download", {"name": "v4-v3-pack", "path": "world/v3pack"}),
        ("download", {"name": "v4-v3-picks-attempt-1", "path": "picks"}),
        *(("call", ["python", "scripts/v4_rehearsal.py", *call]) for call in forced),
        upload_event("v4-forced-attempt-1", "forced/*/*/summary.json\nforced/*/*/receipt.json\n"),
    ]
    # One call per forced kind, in force's own order, each into its own folder: the v3 kinds with
    # the picks job's own picks file and pin (the expected file's), the others with neither.
    assert [call[call.index("--kind") + 1] for call in forced] == list(v4_rehearsal.FORCED)
    for call in forced:
        args = v4_rehearsal.build_parser().parse_args(call)
        assert (args.command, args.world, args.out) == (
            "force",
            Path("world"),
            Path(f"forced/{args.kind}"),
        )
        if args.kind in v4_rehearsal.FORCED_CELL:  # a v3 kind: v3_as_built's cell
            assert (args.picks, args.picks_sha256) == (Path(PICKS_PATH), PICKS_SHA), args.kind
        else:
            assert (args.picks, args.picks_sha256) == (None, None), args.kind
    # Force writes forced/<kind>/<cell id>/, and the scenarios read each one's summary and
    # receipt there. The upload's root is forced/, the common folder of its paths, so the
    # verdict job's download into forced gives that layout back.
    for kind in v4_rehearsal.FORCED:
        folder = tmp_path / "layout" / kind / v4_rehearsal.forced_cell(kind)
        folder.mkdir(parents=True)
        for name in ("summary.json", "receipt.json"):
            (folder / name).write_bytes(b"{}")
    assert set(v4_rehearsal._read_forced(tmp_path / "layout")) == set(v4_rehearsal.FORCED)


def test_verdict_downloads_only_summaries(tmp_path):
    # Ruling W1: the verdict reads each cell's summary.json and receipt.json alone (about 3 MB a
    # cell), never a cell's records: v4-data (the expected file's window and pins) and every
    # v4-summary-*, one folder per artifact; a rehearsal also its world (the expected file's V3
    # pin) and its forced cells, whose artifact holds their summaries and receipts alone.
    verdict_steps = steps("verdict")
    for mode in MODES:
        downloads = [s["with"] for s in verdict_steps if is_download(s) and step_runs(s, mode)]
        expected = [{"name": "v4-data", "path": "v4data"}, SUMMARIES]
        if mode == "rehearsal":
            expected += [
                {"name": "v4-rehearsal-world", "path": "world"},
                {"name": f"v4-forced{ATTEMPT}", "path": "forced"},
            ]
        assert downloads == expected, mode
    # The pattern takes every cell's summary artifact, the v3 cells' too, and nothing else that
    # any job uploads; those artifacts and the forced cells' hold summary.json and receipt.json.
    known = context("rehearsal")
    matching = [
        (job, s["with"])
        for job in jobs()
        for s in steps(job)
        if is_upload(s)
        and fnmatch.fnmatchcase(str(resolve(s["with"]["name"], known)), SUMMARIES["pattern"])
    ]
    assert [job for job, _ in matching] == ["cell", "v3-cell"]
    for _, spec in matching:
        assert spec["path"].strip().splitlines() == [f"out/{MATRIX_CELL}/summary.json",
                                                     f"out/{MATRIX_CELL}/receipt.json"]  # fmt: skip
    (forced,) = [s for s in steps("scenarios") if is_upload(s)]
    assert forced["with"]["path"].strip().splitlines() == [
        "forced/*/*/summary.json",
        "forced/*/*/receipt.json",
    ]
    # No download of the verdict job takes a cell's or a v3 cell's folder.
    cell = "v4_main-1000-1x"
    for step in verdict_steps:
        if is_download(step):
            wanted = str(resolve(step["with"].get("name") or step["with"]["pattern"], known))
            for folder in (f"v4-cell-{cell}-attempt-1", f"v4-v3-cell-{cell}-attempt-1"):
                assert not fnmatch.fnmatchcase(folder, wanted), (wanted, folder)

    # download-artifact makes no folder when no artifact matches (no cell uploaded a summary):
    # the folder is made next, so the verdict is incomplete, naming every cell, not a crash.
    made = index_of("verdict", "mkdir -p summaries")
    assert run_text(verdict_steps[made]) == "mkdir -p summaries" and "if" not in verdict_steps[made]
    assert verdict_steps[made - 1]["with"] == SUMMARIES
    assert made < index_of("verdict", "--summaries summaries --expected")
    for name, exists in (("none", False), ("some", True)):
        folder = tmp_path / name
        (folder / "summaries" if exists else folder).mkdir(parents=True)
        done = run_script(str(verdict_steps[made]["run"]), folder, {})
        assert done.returncode == 0 and (folder / "summaries").is_dir(), done.stderr


def test_verdict_expects_the_modes_cells_against_the_modes_pins(tmp_path):
    # The expected file (scripts/v4_run_plan.py expected): its cells, window and data from this
    # run's v4-data, its V3 pack pin from the mode's own source (registered: the run manifest;
    # rehearsal: the world's rehearsal.json; timing: none) and the picks pin of the picks job,
    # which every v3 cell was run with and checked against.
    verdict_steps = steps("verdict")
    expected = index_of("verdict", "v4_run_plan.py expected")
    assert "if" not in verdict_steps[expected] and verdict_steps[expected]["id"] == "expected"
    assert jobs()["verdict"]["env"] == {
        "PICKS_RESULT": "${{ needs.v3-picks.result }}",
        "PICKS_SHA256": "${{ needs.v3-picks.outputs.picks_sha256 }}",
    }
    # It loads the whole data pack (Market.load) in the verdict job, so it runs under GNU time,
    # each mode's call (test_verdict_and_analysis_are_timed_as_the_cells_are keeps its timing).
    script = str(verdict_steps[expected]["run"])
    calls_made = [line.strip() for line in script.splitlines() if "scripts/" in line]
    assert len(calls_made) == len(MODES)
    for line in calls_made:
        assert line.startswith("/usr/bin/time -v -o expected.time python scripts/v4_run_plan.py ")

    def expected_call(mode: str, folder: str, **known: str) -> argparse.Namespace:
        # GNU time left out (a Windows bash has none): the call its CLI gets.
        step = {**verdict_steps[expected], "run": TIMED_BY.sub("", script)}
        done, calls, _ = run_recorded(
            "verdict", step, mode, tmp_path / folder, known={**context(mode), **known}
        )
        assert done.returncode == 0, done.stderr
        (call,) = calls
        return v4_run_plan.build_parser().parse_args(call[2:])

    for mode in MODES:
        args = expected_call(mode, mode)
        assert (args.command, args.mode, args.data, args.out) == (
            "expected",
            mode,
            Path("v4data"),
            Path("expected.json"),
        )
        source = {
            "registered": (Path(MANIFEST), None),
            "rehearsal": (None, Path("world")),
            "timing": (None, None),
        }
        assert (args.manifest, args.world) == source[mode], mode
        assert args.picks_sha256 == (None if mode == "timing" else PICKS_SHA), mode
        # A picks job that did not succeed gave no pin: 64 zeros take its place, so the verdict
        # is still written (its v3 cells missing); a timing run is unchanged.
        for result in ("failure", "skipped", "cancelled"):
            known = {"needs.v3-picks.result": result, "needs.v3-picks.outputs.picks_sha256": ""}
            args = expected_call(mode, f"{mode}-{result}", **known)
            assert args.picks_sha256 == (None if mode == "timing" else NO_PICKS), (mode, result)
            assert (args.manifest, args.world) == source[mode], (mode, result)
        # The sentinel is keyed on the job's result: a picks job that succeeded with no pin, or
        # a bad one, passes it on, and the script refuses it (nothing is written).
        if mode != "timing":
            for pin in ("", "A" * 64, "0" * 63):
                args = expected_call(mode, f"{mode}-bad-{len(pin)}", **{
                    "needs.v3-picks.outputs.picks_sha256": pin,
                })  # fmt: skip
                assert args.picks_sha256 == pin, (mode, pin)
                with pytest.raises(v4_run_plan.PlanError):
                    v4_run_plan._picks(mode, args.picks_sha256)
    # A rehearsal's world is downloaded before the expected file reads its rehearsal.json.
    (world,) = [
        i
        for i, s in enumerate(verdict_steps)
        if is_download(s) and s["with"].get("name") == "v4-rehearsal-world"
    ]
    assert world < expected and verdict_steps[world]["if"] == "${{ inputs.mode == 'rehearsal' }}"


@pytest.fixture(scope="module")
def small_data(tmp_path_factory) -> Path:
    """A synthetic data pack of three months of one coin, written in a moment."""
    btc = CoinSpec(
        "BTCUSDT", Series(month_start("2025-01"), price_path("100", (24 * 90, "0.0002")))
    )
    world = World("2025-03", (btc,), every_month("2025-01", "2025-03", ("BTCUSDT",)))
    return write_world(tmp_path_factory.mktemp("world"), world)


def test_a_verdict_without_picks_counts_the_v3_cells_missing(tmp_path, small_data, capsys):
    # The picks job's sentinel, round trip: the expected file takes it (the real write_expected,
    # on a synthetic world, and read_expected reads it back) ...
    world = tmp_path / "world"
    world.mkdir()
    document = {
        "format": v4_rehearsal.WORLD_FORMAT,
        "scale": "rehearsal",
        "data": data_record(Market.load(small_data).pins),
        "v3_pack_sha256": "1" * 64,
        "registration_sha256": "2" * 64,
    }
    (world / v4_rehearsal.WORLD_FILE).write_bytes(_canonical(document))
    out = tmp_path / "expected.json"
    v4_run_plan.write_expected(
        "rehearsal",
        small_data,
        out,
        manifest=None,
        world=v4_rehearsal.read_world(world),
        picks_sha256=NO_PICKS,
    )
    assert verdict_inputs.read_expected(out).picks_sha256 == NO_PICKS
    assert v4_run_plan._picks("registered", NO_PICKS) == NO_PICKS
    for empty in ("", None):  # an empty pin is still refused
        with pytest.raises(v4_run_plan.PlanError):
            v4_run_plan._picks("registered", empty)

    # ... and a v3 cell judged against it is refused at its data (no picks file hashes to it), so
    # it counts as missing (V2): the verdict is incomplete, and a stopped v4_main still fails it.
    fixtures = v4_verdict_fixtures
    zero = fixtures.write_expected(
        tmp_path / "zero.json", fixtures.expected_for(picks_sha256=NO_PICKS)
    )
    v3_cells = [c for c in fixtures.expected_for().cells if c.startswith("v3_as_built-")]
    assert len(v3_cells) == 4

    def judge(name: str, overrides: Mapping[str, Mapping[str, object]] | None) -> dict[str, Any]:
        summaries = tmp_path / name / "summaries"
        fixtures.full_set(summaries, overrides=overrides)  # the v3 cells carry the real picks pin
        if name == "complete":
            folder = summaries / f"v4-summary-{v3_cells[0]}-attempt-1"
            with pytest.raises(verdict_inputs.CellRefused) as refused:
                verdict_inputs.read_cell(folder, verdict_inputs.read_expected(zero))
            assert refused.value.step == "data"
        argv = ["--summaries", str(summaries), "--expected", str(zero)]
        argv += ["--progress", str(tmp_path / name / "progress")]
        argv += ["--out", str(tmp_path / name / "verdict")]
        assert v4_verdict.main(argv) == 0
        verdict = json.loads((tmp_path / name / "verdict" / "verdict.json").read_bytes())
        assert sorted(verdict["missing"]) == sorted(v3_cells), name
        refused = sorted((row["folder"], row["step"]) for row in verdict["refused"])
        assert refused == sorted((f"v4-summary-{c}-attempt-1", "data") for c in v3_cells), name
        return verdict

    assert judge("complete", None)["verdict"]["outcome"] == "incomplete"
    main = "v4_main-1000-1x"
    stopped = {
        main: {
            "outcome": LIQUIDATED,
            "marks": fixtures.marks_for(main)[:20],
            "final_after_close": None,
            "equity_2025": None,
        }
    }
    assert judge("stopped", stopped)["verdict"]["outcome"] == "fail"
    capsys.readouterr()


def test_verdict_runs_after_failed_cells_but_not_after_a_failed_plan():
    graph = jobs()
    assert needs(graph["verdict"]) == ["plan", "cell", "v3-cell", "v3-picks", "scenarios"]
    assert needs(graph["analysis"]) == ["plan", "cell"]
    # After every cell job that ended, failed or timed out included (GitHub may report a job
    # that hit its timeout as cancelled, so no cell's result is tested); never after a cancelled
    # run or a failed plan. !cancelled() also keeps the jobs a mode skips (v3-picks and v3-cell
    # in a timing run, scenarios outside a rehearsal) from skipping the verdict.
    assert graph["verdict"]["if"] == graph["analysis"]["if"] == AFTER_THE_CELLS
    # The scenarios replay six forced cells one after another, two of them V3's 3.5-year
    # replays; the verdict has more than two hours after its dispatch check's deadline.
    timeouts = {name: graph[name]["timeout-minutes"] for name in PART_2_JOBS}
    assert timeouts == {"scenarios": 180, "verdict": 180, "analysis": 120, "status": 15}

    ok, skip = "success", "skipped"
    for mode in MODES:
        ran = jobs_that_run(mode)
        assert (ran["verdict"], ran["analysis"], ran["status"]) == (ok, ok, ok), mode
        assert ran["scenarios"] == (ok if mode == "rehearsal" else skip), mode
        for failing in (
            ["cell"],
            ["v3-cell"],
            ["v3-picks"],
            ["v3-pack"],
            ["scenarios"],
            ["cell", "v3-cell", "scenarios"],
        ):
            results = jobs_that_run(mode, failing)
            assert (results["verdict"], results["analysis"], results["status"]) == (ok, ok, ok), (
                mode,
                failing,
            )
        # A failed plan skips every job but the status job, as the dispatch check's layer L2
        # requires of a launch that stopped at the plan job with nothing run.
        assert jobs_that_run(mode, ["plan"]) == {
            **dict.fromkeys(jobs(), skip),
            "plan": "failure",
            "status": ok,
        }, mode
    # Without !cancelled(), GitHub's implicit success() would skip a timing run's verdict: some of
    # the jobs before it were skipped.
    timing = jobs_that_run("timing")
    assert any(timing[name] == skip for name in ancestors("verdict"))


def test_rehearsal_verdict_checks_every_scenario(tmp_path):
    verdict_steps = steps("verdict")
    judge = index_of("verdict", "--summaries summaries --expected")
    timing = index_of("verdict", "--verdict-dir verdict")
    expected_timing = index_of("verdict", "--expected-dir verdict")
    (forced,) = [
        i
        for i, s in enumerate(verdict_steps)
        if is_download(s) and s["with"].get("name") == f"v4-forced{ATTEMPT}"
    ]
    make = index_of("verdict", "v4_rehearsal.py scenarios")
    each = index_of("verdict", '--summaries "scenarios/$scenario"')
    check = index_of("verdict", "v4_rehearsal.py check")
    upload = index_of_upload("verdict", f"v4-rehearsal-verdict{ATTEMPT}")
    assert judge < timing < expected_timing < forced < make < each < check < upload
    # A rehearsal's steps alone.
    for index in (forced, make, each, check, upload):
        assert step_can_run(verdict_steps[index], "rehearsal"), index
        for mode in ("registered", "timing"):
            assert not step_can_run(verdict_steps[index], mode), (index, mode)

    # The trace after the main verdict's timing, with the folders the scenarios step writes.
    scenario_folders(tmp_path / str(each))
    events = trace("verdict", "rehearsal", tmp_path)
    timed = ["python", "scripts/v4_cells_timing.py", "--time-file", "verdict.time"]
    start = events.index(("call", [*timed, "--verdict-dir", "verdict"]))
    tail = events[start + 1 :]

    def judged(event: tuple[Any, ...]) -> bool:
        return event[0] == "call" and event[1][:2] == ["python", "scripts/v4_verdict.py"]

    assert [event for event in tail if not judged(event)] == [
        # The expected step's timing, beside the verdict's: the artifact below holds both.
        ("call", ["python", "scripts/v4_cells_timing.py", "--time-file", "expected.time",
                  "--expected-dir", "verdict"]),
        ("download", {"name": "v4-forced-attempt-1", "path": "forced"}),
        # The eleven scenarios of the base set (the downloaded summaries) and the forced cells.
        ("call", ["python", "scripts/v4_rehearsal.py", "scenarios", "--base", "summaries",
                  "--forced", "forced", "--out", "scenarios"]),
        ("call", ["python", "scripts/v4_rehearsal.py", "check", "--scenarios", "scenarios",
                  "--verdicts", "scenario-verdicts"]),
        upload_event("v4-rehearsal-verdict-attempt-1", "verdict/\nscenario-verdicts/\ncheck.txt\n"),
    ]  # fmt: skip
    # Each scenario judged once, between the scenarios and the check, by the verdict step itself:
    # every folder the scenarios wrote, so every scenario of the table, each with its own
    # progress and output folders (a resumed progress of other inputs is refused), against the
    # run's expected file, and with no dispatch reasons (a rehearsal's).
    positions = [i for i, event in enumerate(tail) if judged(event)]
    assert positions == list(range(3, 3 + len(v4_rehearsal.SCENARIOS)))
    names = []
    for i in positions:
        args = v4_verdict.build_parser().parse_args(tail[i][1][2:])
        names.append(args.summaries.name)
        assert args.summaries == Path("scenarios") / args.summaries.name
        assert args.progress == Path("scenario-progress") / args.summaries.name
        assert args.out == Path("scenario-verdicts") / args.summaries.name
        assert (args.expected, args.dispatch_reasons) == (Path("expected.json"), None)
    assert sorted(names) == sorted(v4_rehearsal.SCENARIOS)
    # The check reads the scenarios' folder and their verdicts' (V/<name>/verdict.json); its
    # lines go to check.txt, which the rehearsal's verdict artifact holds with the verdicts.
    args = v4_rehearsal.build_parser().parse_args(tail[2][1][2:])
    assert (args.base, args.forced, args.out) == (
        Path("summaries"),
        Path("forced"),
        Path("scenarios"),
    )
    args = v4_rehearsal.build_parser().parse_args(tail[-2][1][2:])
    assert (args.scenarios, args.verdicts) == (Path("scenarios"), Path("scenario-verdicts"))
    assert run_text(verdict_steps[check]).endswith(" > check.txt")
    assert verdict_steps[upload]["with"]["path"].strip().splitlines() == [
        "verdict/",
        "scenario-verdicts/",
        "check.txt",
    ]
    # Whatever failed after the main verdict was written (its timing, the expected step's
    # timing, the forced download, the scenarios, one scenario's verdict, the check), the
    # rehearsal's verdict is still uploaded and the job still fails; a main verdict that failed
    # (nothing written) uploads nothing.
    for failing in (timing, expected_timing, forced, make, each, check):
        assert steps_that_run("verdict", "rehearsal", failing=[failing])[upload] == "success"
    assert steps_that_run("verdict", "rehearsal", failing=[judge])[upload] == "skipped"


def test_registered_verdict_rechecks_other_dispatches(tmp_path):
    job = jobs()["verdict"]
    verdict_steps = job["steps"]
    # It lists this workflow's runs again (actions: read), and its deadline counts from the
    # job's start, its first step: the 55-minute budget ends inside the timeout, and the job's
    # 180 minutes leave the verdict more than two hours after it.
    assert verdict_steps[0] == JOB_START_STEP
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    assert job["timeout-minutes"] == 180
    assert job["timeout-minutes"] * 60 >= v4_registration.VERDICT_JOB_BUDGET + 5 * 60
    assert job["timeout-minutes"] * 60 - v4_registration.VERDICT_JOB_BUDGET > 2 * 3600
    expected = index_of("verdict", "v4_run_plan.py expected")
    check = index_of("verdict", "dispatch-check")
    judge = index_of("verdict", "--summaries summaries --expected")
    # The check is the first step after the setup steps, before any download and the expected
    # step, so its deadline never eats into the verdict's time.
    assert check == 1 + SETUP_STEPS
    downloads = [i for i, s in enumerate(verdict_steps) if is_download(s)]
    assert check < min(downloads) and check < expected < judge
    step = verdict_steps[check]
    assert step["if"] == "${{ inputs.mode == 'registered' }}"
    assert step["env"] == {"GITHUB_TOKEN": "${{ github.token }}"}
    assert "timeout-minutes" not in step  # the check's own deadline ends it
    for mode in ("rehearsal", "timing"):
        assert not step_can_run(step, mode), mode

    events = trace("verdict", "registered", tmp_path / "trace")
    gnu_check = index_of("verdict", "-x /usr/bin/time")
    assert events == [
        # Every earlier launch of the registration judged and none refused: each one that
        # counts, or why none could be ruled out, is the verdict's input (Ruling G4).
        ("call", ["python", "scripts/v4_registration.py", "dispatch-check", "--mode",
                  "registered", "--registration-sha256", INPUT_SHA, "--judge-all", "--out",
                  "reasons.json"]),
        ("download", {"name": "v4-data", "path": "v4data"}),
        ("download", SUMMARIES),
        ("timed", run_text(verdict_steps[gnu_check])),  # the GNU time check
        ("timed", run_text(verdict_steps[expected])),
        ("timed", run_text(verdict_steps[judge])),
        ("call", ["python", "scripts/v4_cells_timing.py", "--time-file", "verdict.time",
                  "--verdict-dir", "verdict"]),
        ("call", ["python", "scripts/v4_cells_timing.py", "--time-file", "expected.time",
                  "--expected-dir", "verdict"]),
        # verdict/: the verdict, its timing and the expected step's.
        upload_event("v4-verdict-attempt-1", "verdict/"),
    ]  # fmt: skip
    done, calls, _ = run_untimed("verdict", verdict_steps[expected], "registered", tmp_path / "e")
    assert done.returncode == 0, done.stderr
    assert calls == [
        ["python", "scripts/v4_run_plan.py", "expected", "--mode", "registered", "--data",
         "v4data", "--out", "expected.json", "--manifest", MANIFEST, "--picks-sha256", PICKS_SHA]
    ]  # fmt: skip
    (call,) = calls_of(events, "v4_registration.py")
    args = v4_registration.build_parser().parse_args(call)
    assert (args.command, args.mode, args.judge_all, args.report_only, args.out) == (
        "dispatch-check",
        "registered",
        True,
        False,
        "reasons.json",
    )
    assert args.registration_sha256 == INPUT_SHA  # the dispatch's input, as the plan's check
    assert v4_registration._option_problem(args) is None

    # The verdict reads the reasons the check wrote, in a registered run only.
    for mode in MODES:
        done, calls, _ = run_untimed("verdict", verdict_steps[judge], mode, tmp_path / mode)
        assert done.returncode == 0, done.stderr
        (verdict,) = calls
        args = v4_verdict.build_parser().parse_args(verdict[2:])
        assert (args.summaries, args.expected, args.progress, args.out) == (
            Path("summaries"),
            Path("expected.json"),
            Path("progress"),
            Path("verdict"),
        )
        assert args.dispatch_reasons == (Path("reasons.json") if mode == "registered" else None)
    # A check that failed (it turns any failure to read GitHub into a reason and still writes
    # its file, so it fails only when the file cannot be written) skips everything after it, so
    # a registered verdict never runs without the reasons; nothing is downloaded or uploaded.
    after = steps_that_run("verdict", "registered", failing=[check])
    assert {after[i] for i in (*downloads, expected, judge)} == {"skipped"}
    assert after[index_of_upload("verdict", f"v4-verdict{ATTEMPT}")] == "skipped"
    # A timing step that failed does not discard the verdict (the job still fails).
    timing = index_of("verdict", "--verdict-dir verdict")
    after = steps_that_run("verdict", "registered", failing=[timing])
    assert after[index_of_upload("verdict", f"v4-verdict{ATTEMPT}")] == "success"


# GNU time -v's reports (the lines the timing helper reads) of a command that exited 1, and of one
# killed by signal 9 (out of memory), for which GNU time prints "Exit status: 0".
FAILED_REPORT = (
    "Command exited with non-zero status 1\n"
    "\tElapsed (wall clock) time (h:mm:ss or m:ss): 1:02.50\n"
    "\tMaximum resident set size (kbytes): 2097152\n"
    "\tExit status: 1\n"
)
KILLED_REPORT = (
    "Command terminated by signal 9\n"
    "\tElapsed (wall clock) time (h:mm:ss or m:ss): 3:00.00\n"
    "\tMaximum resident set size (kbytes): 2200000\n"
    "\tExit status: 0\n"
)
# Each timed step of part 2: its job, the id of the step GNU time times, its time file, its
# timing step's target and id, the timing file and the step that file names.
TIMED_STEPS = (
    ("verdict", "verdict", "verdict.time", "--verdict-dir verdict", "timing",
     v4_cells_timing.VERDICT_TIMING_FILE, "verdict"),
    ("verdict", "expected", "expected.time", "--expected-dir verdict", "expected_timing",
     v4_cells_timing.EXPECTED_TIMING_FILE, "expected"),
    ("analysis", "diagnose", "diagnose.time", "--diagnosis-dir diagnosis", "timing",
     v4_cells_timing.DIAGNOSE_TIMING_FILE, "diagnose"),
)  # fmt: skip
# The verdict job's timing-run upload: either timing, once written.
VERDICT_TIMING_UPLOAD = (
    "${{ !cancelled() && (steps.timing.outcome == 'success' || "
    "steps.expected_timing.outcome == 'success') && inputs.mode == 'timing' }}"
)


def index_of_id(job: str, step_id: str) -> int:
    (found,) = [i for i, step in enumerate(steps(job)) if step.get("id") == step_id]
    return found


def test_verdict_and_analysis_are_timed_as_the_cells_are(tmp_path):
    # Each runs its CLI under GNU time, checked first as in a cell job, and keeps the wall time
    # and peak memory in its folder (scripts/v4_cells_timing.py): the verdict's 2 GB limit (the
    # verdict step's, and the expected step's, which loads the whole data pack) and the
    # analysis' size are what a timing run measures (Ruling W2). A timing run uploads those
    # files alone, and only once written.
    for job, step_id, time_file, target, timing_id, timing_file, step_name in TIMED_STEPS:
        job_steps = steps(job)
        check = index_of(job, "-x /usr/bin/time")
        timed = index_of_id(job, step_id)
        timing = index_of(job, target)
        assert check < timed < timing and job_steps[timing]["id"] == timing_id, step_id
        assert "::error::" in run_text(job_steps[check]) and "exit 1" in run_text(job_steps[check])
        lines = [line.strip() for line in str(job_steps[timed]["run"]).splitlines()]
        clis = [line for line in lines if "python scripts/" in line]
        assert clis, step_id
        for line in clis:
            assert line.startswith(f"/usr/bin/time -v -o {time_file} python scripts/"), line
        folder = Path(target.split()[1])
        command = f"python scripts/v4_cells_timing.py --time-file {time_file} {target}"
        # The folder is made first: a step that failed before writing made none.
        assert run_text(job_steps[timing]) == f"mkdir -p {folder.as_posix()} {command}"
        args = v4_cells_timing.build_parser().parse_args(shlex.split(command)[2:])
        assert args.time_file == Path(time_file)
        assert getattr(args, target.split()[0].removeprefix("--").replace("-", "_")) == folder
        # Each timing runs after its step succeeded or failed, never after one that did not run.
        assert job_steps[timing]["if"] == (
            f"${{{{ !cancelled() && (steps.{step_id}.outcome == 'success' || "
            f"steps.{step_id}.outcome == 'failure') }}}}"
        )
        (upload,) = [
            i
            for i, s in enumerate(job_steps)
            if is_upload(s) and s["with"]["name"].startswith("v4-timing-")
        ]
        assert f"{folder.as_posix()}/{timing_file}" in job_steps[upload]["with"]["path"].split()
        assert steps_that_run(job, "timing")[upload] == "success"
        # A step that failed (at real size, out of memory, say: the run a timing run exists to
        # measure) is timed too, and its timing uploaded; a step that never ran is not.
        after_failure = steps_that_run(job, "timing", failing=[timed])
        assert (after_failure[timing], after_failure[upload]) == ("success", "success"), step_id
        never_ran = steps_that_run(job, "timing", failing=[check])
        assert (never_ran[timing], never_ran[upload]) == ("skipped", "skipped"), step_id
        # The step itself, with a time file of a command that failed and no folder: it makes
        # the folder, and the timing helper keeps the failure's time, memory and exit status.
        work = tmp_path / f"{step_id}-failed"
        work.mkdir()
        done, calls, _ = run_recorded(job, job_steps[timing], "timing", work)
        assert done.returncode == 0 and (work / folder).is_dir(), done.stderr
        assert calls == [shlex.split(command)], step_id
        for report, status in ((FAILED_REPORT, 1), (KILLED_REPORT, 128 + 9)):
            (work / time_file).write_text(report, encoding="ascii")
            (work / folder / timing_file).unlink(missing_ok=True)
            argv = ["--time-file", str(work / time_file), target.split()[0], str(work / folder)]
            assert v4_cells_timing.main(argv) == 0, (step_id, status)
            written = json.loads((work / folder / timing_file).read_text(encoding="ascii"))
            assert (written["step"], written["exit_status"]) == (step_name, status), step_id
    assert steps("verdict")[index_of("verdict", "--verdict-dir verdict")]["if"] == VERDICT_RAN
    assert steps("verdict")[index_of("verdict", "--expected-dir verdict")]["if"] == EXPECTED_RAN
    assert steps("analysis")[index_of("analysis", "--diagnosis-dir")]["if"] == DIAGNOSED
    assert run_text(steps("verdict")[index_of("verdict", "--expected-dir")]) == EXPECTED_TIMING_STEP

    # The analysis' timing-run upload: its timing alone, once written.
    analysis_steps = steps("analysis")
    upload = index_of_upload("analysis", f"v4-timing-analysis{ATTEMPT}")
    assert analysis_steps[upload]["with"]["path"] == "diagnosis/diagnose-timing.json"
    assert analysis_steps[upload]["if"] == (
        "${{ !cancelled() && steps.timing.outcome == 'success' && inputs.mode == 'timing' }}"
    )
    timing = index_of("analysis", "--diagnosis-dir")
    assert steps_that_run("analysis", "timing", failing=[timing])[upload] == "skipped"

    # The verdict job: the GNU time check, then the expected step, the verdict, and their two
    # timings, the expected step's after the verdict's, so that a timing step that fails never
    # keeps the verdict from running.
    verdict_steps = steps("verdict")
    check = index_of("verdict", "-x /usr/bin/time")
    expected = index_of_id("verdict", "expected")
    judge = index_of_id("verdict", "verdict")
    timing = index_of_id("verdict", "timing")
    expected_timing = index_of_id("verdict", "expected_timing")
    assert (check, expected, judge, timing) == tuple(range(check, check + 4))
    assert expected_timing == timing + 1
    # Its timing-run upload: the two timings of one folder, so both sit at the artifact's
    # root, each once it was written, of a step that succeeded or failed.
    upload = index_of_upload("verdict", f"v4-timing-verdict{ATTEMPT}")
    assert verdict_steps[upload]["with"]["path"].strip().splitlines() == [
        f"verdict/{v4_cells_timing.VERDICT_TIMING_FILE}",
        f"verdict/{v4_cells_timing.EXPECTED_TIMING_FILE}",
    ]
    assert verdict_steps[upload]["if"] == VERDICT_TIMING_UPLOAD
    for failing, uploaded in (
        ([timing], "success"),  # the expected step's timing alone
        ([expected_timing], "success"),  # the verdict's alone
        ([timing, expected_timing], "skipped"),  # no timing was written
    ):
        assert steps_that_run("verdict", "timing", failing=failing)[upload] == uploaded, failing
    # An expected step that failed skips the verdict and its timing; its own timing is kept and
    # uploaded alone.
    after = steps_that_run("verdict", "timing", failing=[expected])
    assert (after[judge], after[timing], after[expected_timing], after[upload]) == (
        "skipped",
        "skipped",
        "success",
        "success",
    )
    for mode in ("registered", "rehearsal"):
        upload = index_of_upload("verdict", f"{OUTPUT_PREFIX[mode]}verdict{ATTEMPT}")
        # The registered and rehearsal verdicts are uploaded only once written, with both
        # timings in verdict/; a failed timing step never discards a written verdict.
        assert steps_that_run("verdict", mode, failing=[judge])[upload] == "skipped", mode
        assert steps_that_run("verdict", mode, failing=[expected])[upload] == "skipped", mode
        for failing in ([timing], [expected_timing]):
            assert steps_that_run("verdict", mode, failing=failing)[upload] == "success", mode
        assert verdict_steps[upload]["with"]["path"].strip().splitlines()[0] == "verdict/"

    # A timing run's verdict, traced: its 44 cells' summaries, no v3 pin, no dispatch check.
    events = trace("verdict", "timing", tmp_path)
    assert events == [
        ("download", {"name": "v4-data", "path": "v4data"}),
        ("download", SUMMARIES),
        ("timed", run_text(verdict_steps[check])),
        ("timed", run_text(verdict_steps[expected])),
        ("timed", run_text(verdict_steps[judge])),
        ("call", ["python", "scripts/v4_cells_timing.py", "--time-file", "verdict.time",
                  "--verdict-dir", "verdict"]),
        ("call", ["python", "scripts/v4_cells_timing.py", "--time-file", "expected.time",
                  "--expected-dir", "verdict"]),
        upload_event("v4-timing-verdict-attempt-1",
                     "verdict/verdict-timing.json\nverdict/expected-timing.json\n"),
    ]  # fmt: skip
    done, calls, _ = run_untimed("verdict", verdict_steps[expected], "timing", tmp_path / "e")
    assert done.returncode == 0, done.stderr
    assert calls == [
        ["python", "scripts/v4_run_plan.py", "expected", "--mode", "timing", "--data", "v4data",
         "--out", "expected.json"]
    ]  # fmt: skip


def test_analysis_downloads_cells_not_v3_cells(tmp_path, small_data, capsys):
    job = jobs()["analysis"]
    assert job["env"] == {"PLANNED_CELLS": "${{ needs.plan.outputs.cell_ids }}"}
    # Ruling W1: the analysis reads every v4-cell-* folder (the 44 cells that are not v3, the
    # plan's cell_ids, its --planned); a v3 cell uploads v4-v3-cell-*, which no step of any job
    # downloads.
    cell = "v4_main-1000-1x"
    v3_folder = f"v4-v3-cell-{cell}-attempt-1"
    assert fnmatch.fnmatchcase(f"v4-cell-{cell}-attempt-1", CELL_FOLDERS["pattern"])
    for other in (v3_folder, f"v4-summary-{cell}-attempt-1", f"v4-timing-cell-{cell}-attempt-1"):
        assert not fnmatch.fnmatchcase(other, CELL_FOLDERS["pattern"]), other
    for name, body in jobs().items():
        for step in body["steps"]:
            if is_download(step):
                wanted = step["with"].get("name") or step["with"]["pattern"]
                wanted = str(resolve(wanted, context("registered")))
                assert not fnmatch.fnmatchcase(v3_folder, wanted), (name, wanted)
    planned = CELL_IDS.split(",")
    assert len(planned) == 44 and not any(c.startswith("v3_as_built-") for c in planned)

    analysis_steps = steps("analysis")
    guard = index_of("analysis", "scripts/v4_run_guard.py")
    diagnose = index_of("analysis", "scripts/v4_diagnose.py")
    timing = index_of("analysis", "--diagnosis-dir")
    assert analysis_steps[diagnose]["id"] == "diagnose" and "if" not in analysis_steps[diagnose]
    uploads = {
        "registered": upload_event("v4-analysis-attempt-1", "diagnosis/"),
        "rehearsal": upload_event("v4-rehearsal-analysis-attempt-1", "diagnosis/"),
        "timing": upload_event("v4-timing-analysis-attempt-1", "diagnosis/diagnose-timing.json"),
    }
    for mode in MODES:
        kind = ["--manifest", MANIFEST] if mode == "registered" else ["--synthetic"]
        events = trace("analysis", mode, tmp_path / mode)
        assert events == [
            ("download", {"name": "v4-data", "path": "v4data"}),
            # The mode's guard before the cells are read (v4-d03).
            ("call", ["python", "scripts/v4_run_guard.py", "--data", "v4data", *kind]),
            ("download", CELL_FOLDERS),
            ("timed", run_text(analysis_steps[diagnose - 1])),  # the GNU time check
            ("timed", run_text(analysis_steps[diagnose])),
            ("call", ["python", "scripts/v4_cells_timing.py", "--time-file", "diagnose.time",
                      "--diagnosis-dir", "diagnosis"]),
            uploads[mode],
        ], mode  # fmt: skip
        done, calls, _ = run_untimed("analysis", analysis_steps[diagnose], mode, tmp_path / "d")
        assert done.returncode == 0, done.stderr
        assert calls == [
            ["python", "scripts/v4_diagnose.py", "--data", "v4data", "--cells", "cells",
             "--planned", CELL_IDS, "--out", "diagnosis", *kind]
        ], mode  # fmt: skip
        args = v4_diagnose.build_parser().parse_args(calls[0][2:])
        registered = mode == "registered"
        assert (args.manifest, args.synthetic) == (
            (Path(MANIFEST), False) if registered else (None, True)
        )
        # A diagnosis that refused a cell exits 1 after writing the others': its timing and its
        # upload still run (the job still fails). After a failed guard, nothing runs.
        upload = index_of_upload("analysis", f"{OUTPUT_PREFIX[mode]}analysis{ATTEMPT}")
        refused = steps_that_run("analysis", mode, failing=[diagnose])
        assert (refused[timing], refused[upload]) == ("success", "success"), mode
        unguarded = steps_that_run("analysis", mode, failing=[guard])
        assert {unguarded[diagnose], unguarded[timing], unguarded[upload]} == {"skipped"}, mode

    # download-artifact makes no folder when no artifact matches (no cell uploaded one): the
    # cells folder is made next, before the diagnosis, in every mode.
    (download,) = [
        i for i, s in enumerate(analysis_steps) if is_download(s) and s["with"] == CELL_FOLDERS
    ]
    made = index_of("analysis", "mkdir -p cells")
    assert made == download + 1 and made < diagnose
    assert run_text(analysis_steps[made]) == "mkdir -p cells" and "if" not in analysis_steps[made]
    for name, exists in (("none", False), ("some", True)):
        folder = tmp_path / "made" / name
        (folder / "cells" if exists else folder).mkdir(parents=True)
        done = run_script(str(analysis_steps[made]["run"]), folder, {})
        assert done.returncode == 0 and (folder / "cells").is_dir(), done.stderr
    # The diagnosis, given that empty folder, refuses it in its own words and writes nothing (it
    # diagnoses no set without a cell); its timing and its upload then still run, so a timing
    # run keeps its time (test_verdict_and_analysis_are_timed_as_the_cells_are).
    capsys.readouterr()
    empty = tmp_path / "made" / "none" / "cells"
    out = tmp_path / "made" / "none" / "diagnosis"
    argv = ["--data", str(small_data), "--cells", str(empty), "--planned", CELL_IDS]
    assert v4_diagnose.main([*argv, "--out", str(out), "--synthetic"]) == 1
    assert "no cell folder holds a summary.json" in capsys.readouterr().err
    assert not out.exists()


def test_mode_names_its_outputs():
    # Ruling W3: a rehearsal's and a timing run's outputs carry their mode's name, so a synthetic
    # verdict, analysis or status can never pass for the registered run's; and the registered
    # run uploads nothing named for another mode.
    def modes_of(name: str) -> set[str]:
        if name.startswith(("v4-rehearsal-", "v4-forced-")):
            return {"rehearsal"}
        if name.startswith("v4-timing-"):
            return {"timing"}
        if name.startswith(("v4-verdict-", "v4-analysis-", "v4-status-")):
            return {"registered"}
        return set(MODES)  # the run's own hand-offs: data, packs, picks, cells and summaries

    for job, body in jobs().items():
        for step in body["steps"]:
            if is_upload(step):
                name = step["with"]["name"]
                ran = {mode for mode in MODES if can_run(job, step, mode)}
                assert ran and ran <= modes_of(name), (job, name, ran)
    names = {job: [s["with"]["name"] for s in steps(job) if is_upload(s)] for job in PART_2_JOBS}
    assert names == {
        "scenarios": [f"v4-forced{ATTEMPT}"],
        "verdict": [f"v4-verdict{ATTEMPT}", f"v4-rehearsal-verdict{ATTEMPT}",
                    f"v4-timing-verdict{ATTEMPT}"],
        "analysis": [f"v4-analysis{ATTEMPT}", f"v4-rehearsal-analysis{ATTEMPT}",
                     f"v4-timing-analysis{ATTEMPT}"],
        "status": [f"v4-status{ATTEMPT}", f"v4-rehearsal-status{ATTEMPT}",
                   f"v4-timing-status{ATTEMPT}"],
    }  # fmt: skip
    # Each mode uploads one verdict, one analysis and one status, under its own name; the
    # analysis' is the one the verdict page names.
    for mode in MODES:
        ran = jobs_that_run(mode)
        for job in ("verdict", "analysis", "status"):
            assert ran[job] == "success", (mode, job)
            outcome = steps_that_run(job, mode)
            uploaded = [
                s["with"]["name"]
                for i, s in enumerate(steps(job))
                if is_upload(s) and outcome[i] == "success"
            ]
            assert uploaded == [f"{OUTPUT_PREFIX[mode]}{job}{ATTEMPT}"], (mode, job)
        page = verdict_report.ANALYSIS_ARTIFACTS[mode].replace("<n>", "${{ github.run_attempt }}")
        assert page == f"{OUTPUT_PREFIX[mode]}analysis{ATTEMPT}", mode


def test_status_always_runs_and_reads_needs_through_env(tmp_path, monkeypatch, capsys):
    job = jobs()["status"]
    # Whatever the other jobs did, a cancelled run included, so a run that stopped half way still
    # records how far it got. It needs every other job: NEEDS must list exactly those.
    assert job["if"] == "${{ always() }}"
    assert len(needs(job)) == len(set(needs(job)))
    assert set(needs(job)) == set(v4_run_status.JOBS) == set(jobs()) - {"status"}
    (record,) = [s for s in job["steps"] if "scripts/v4_run_status.py" in str(s.get("run", ""))]
    assert record["env"] == {
        "RUN_ID": "${{ github.run_id }}",
        "RUN_ATTEMPT": "${{ github.run_attempt }}",
        "NEEDS": "${{ toJSON(needs) }}",
    }
    # The dispatch's own registration_sha256 (the workflow's environment): a plan that stopped
    # early has no output to give.
    assert run_text(record) == (
        'python scripts/v4_run_status.py --mode "$MODE" --registration-sha256 '
        '"$REGISTRATION_SHA256" --out status/status.json'
    )
    assert "needs.plan.outputs" not in str(job)
    for mode in MODES:
        events = trace("status", mode, tmp_path / mode)
        sha = INPUT_SHA if mode == "registered" else ""
        assert events == [
            ("call", ["python", "scripts/v4_run_status.py", "--mode", mode,
                      "--registration-sha256", sha, "--out", "status/status.json"]),
            upload_event(f"{OUTPUT_PREFIX[mode]}status-attempt-1", "status/"),
        ]  # fmt: skip
        args = v4_run_status.build_parser().parse_args(events[0][1][2:])
        assert (args.mode, args.registration_sha256) == (mode, sha)
        # Run for real on the needs context such a run gives (toJSON(needs): each job's result
        # and outputs): the script accepts it and records each job's result.
        for failing in ([], ["plan"], ["cell", "verdict"], ["v3-picks", "analysis"]):
            results = jobs_that_run(mode, failing)
            assert results["status"] == "success", (mode, failing)
            context_needs = {name: {"result": results[name], "outputs": {}} for name in needs(job)}
            monkeypatch.setenv("NEEDS", json.dumps(context_needs))
            monkeypatch.setenv("RUN_ID", RUN_ID)
            monkeypatch.setenv("RUN_ATTEMPT", "1")
            out = tmp_path / "real" / mode / "-".join(failing or ["none"]) / "status.json"
            assert v4_run_status.main(["--mode", mode, "--registration-sha256", sha,
                                       "--out", str(out)]) == 0  # fmt: skip
            document = json.loads(out.read_bytes())
            assert document["jobs"] == {name: results[name] for name in needs(job)}
            assert document["verdict_ran"] is (results["verdict"] in ("success", "failure"))
    capsys.readouterr()


# The CLIs whose standard output could tell a result, and where each call sends it instead of the
# public log (owner rule: counts, ids, sizes, times and pins only).
QUIET = {
    ("v4_cell.py", "run"): "/dev/null",  # the cell's outcome
    ("v4_v3_cell.py", "run"): "/dev/null",
    ("v4_rehearsal.py", "force"): "/dev/null",  # a forced cell's line, as a cell's own
    # Its counts of missing and refused cells can tell an incomplete verdict.
    ("v4_verdict.py", None): "/dev/null",
    # A cell's record and month counts can tell a cell that stopped.
    ("v4_diagnose.py", None): "/dev/null",
    # Its lines per scenario, kept in the rehearsal's verdict artifact.
    ("v4_rehearsal.py", "check"): "check.txt",
}
# The CLIs whose standard output is counts, ids, sizes, times and pins only, as each one's
# docstring says: it stays in the log.
COUNTS = {
    ("v4_run_plan.py", "matrix"),
    ("v4_run_plan.py", "expected"),
    ("v4_rehearsal.py", "world"),
    ("v4_rehearsal.py", "picks"),
    ("v4_rehearsal.py", "scenarios"),
    ("v4_registration.py", "gate"),
    ("v4_registration.py", "dispatch-check"),
    ("v4_run_guard.py", None),
    ("v4_v3_pack.py", None),
    ("v4_v3_cell.py", "picks"),
    ("v4_cells_timing.py", None),
    ("v4_run_status.py", None),
}
CLI_CALL = re.compile(r"python scripts/(?P<script>[\w.]+)(?: (?P<command>[a-z][\w-]*))?")


def cli_lines() -> list[tuple[str, tuple[str, str | None], str]]:
    """Every line of a script that calls one of the repository's scripts: its job, the script
    and its subcommand, and the line (continuations joined, whitespace collapsed)."""
    found = []
    for name, body in jobs().items():
        for step in body["steps"]:
            for line in str(step.get("run", "")).replace("\\\n", " ").splitlines():
                line = " ".join(line.split())
                for match in CLI_CALL.finditer(line):
                    found.append((name, (match["script"], match["command"]), line))
    return found


def test_logs_counts_only():
    # The logs are public: never a price, an equity, a return, a cell's outcome or the verdict.
    # Every call of a CLI whose standard output could tell one sends it elsewhere, and every
    # other CLI called is one whose output is counts, which the log keeps.
    seen = set()
    for job, cli, line in cli_lines():
        assert cli in QUIET or cli in COUNTS, (job, cli)
        seen.add(cli)
        if cli in QUIET:
            assert line.endswith(f" > {QUIET[cli]}") and line.count(">") == 1, (job, line)
        else:
            assert ">" not in line, (job, line)
    assert seen == set(QUIET) | COUNTS  # each is called: none is listed for nothing
    # The steps that send a CLI's output to /dev/null are exactly these.
    redirected = sorted(
        (job, step["name"])
        for job, body in jobs().items()
        for step in body["steps"]
        if "/dev/null" in str(step.get("run", ""))
    )
    assert redirected == sorted([
        ("cell", "Replay the cell"),
        ("v3-cell", "Replay the cell"),
        ("scenarios", "Force the six stop outcomes"),
        ("verdict", "Judge the cells"),
        ("verdict", "Judge every scenario"),
        ("analysis", "Diagnose the cells"),
    ])  # fmt: skip
    # The scenario check's lines are kept in the rehearsal's verdict artifact, not printed.
    upload = steps("verdict")[index_of_upload("verdict", f"v4-rehearsal-verdict{ATTEMPT}")]
    assert "check.txt" in upload["with"]["path"].strip().splitlines()
    # No step prints, copies to the log or searches a result file.
    shown = re.compile(r"\b(cat|head|tail|less|more|jq|grep|sed|awk|tee)\b")
    results = ("records.jsonl", "summary.json", "receipt.json", "report.html")
    results += ("verdict.json", "verdict.md", "diagnosis.json", "diagnosis.md")
    for name, body in jobs().items():
        for step in body["steps"]:
            script = run_text(step)
            assert shown.search(script) is None, (name, script)
            for result in results:
                assert result not in script, (name, result)


# ---- fail closed and the header -----------------------------------------------------------------


def test_every_mode_switch_refuses_a_mode_it_does_not_know(tmp_path):
    # A step that does different things by mode lists each mode it serves and fails, calling
    # nothing, on any other.
    switches = [
        (name, index, step)
        for name, job in jobs().items()
        for index, step in enumerate(job["steps"])
        if '"$MODE" =' in str(step.get("run", ""))
    ]
    assert len(switches) >= 5  # the plan's gate, dispatch check and guard; the cells' guard, gate
    for name, index, step in switches:
        done, calls, written = run_recorded(name, step, "smoke", tmp_path / f"{name}-{index}")
        assert done.returncode != 0 and "::error::" in done.stderr, (name, index)
        assert calls == [] and written == {}, (name, index)


def test_header_states_the_modes_and_the_operating_rules():
    said = header()
    for phrase in (
        "- rehearsal",
        "- timing",
        "- registered",
        "OPERATING RULE",
        "one v4-run at a time",
        "Never cancel",
        "never re-run",
        "THE DISPATCH REF",
        "THE MATRICES",
        "-attempt-<n>",
        "v4-data, v4-v3-pack and v4-rehearsal-world",
        "fails closed at the plan job",
        "v4-d03",
        "v4-d10",
        "kept one day",
        "/dev/null",
        "Jobs:",
        "- plan",
        "- v3-pack",
        "- v3-picks",
        "- cell",
        "- v3-cell",
    ):
        assert phrase in said, phrase


def test_header_says_what_the_jobs_do():
    said = header()
    for phrase in (
        # Part 2's jobs, in "Jobs:".
        "- scenarios (rehearsal)",
        "- verdict (every mode)",
        "- analysis (every mode)",
        "- status (always)",
        # What each one does and uploads.
        "six stop outcomes",
        "v4-forced-attempt-<n>",
        "never a cell's records",
        "--judge-all",
        "eleven scenarios",
        "verdict-timing.json",
        "diagnose-timing.json",
        "v4-verdict-attempt-<n>",
        "v4-rehearsal-verdict-attempt-<n>",
        "v4-timing-verdict-attempt-<n>",
        "v4-analysis-attempt-<n>",
        "v4-rehearsal-analysis-attempt-<n>",
        "v4-timing-analysis-attempt-<n>",
        "v4-status-attempt-<n>",
        "v4-rehearsal-status-attempt-<n>",
        "v4-timing-status-attempt-<n>",
        "toJSON(needs)",
        # The token is the plan's and the registered verdict's; the spec's one re-run.
        "the verdict job of a registered run",
        "single aggregate-only re-run",
        # The verdict job's check comes first, its timeout leaves the verdict two hours, and its
        # expected step is timed beside the verdict.
        "before any download",
        "the job's timeout is 180 minutes",
        "expected-timing.json",
        # A verdict-only re-run starts from zero.
        "its progress/ folder is never uploaded",
        # What a timing run uploads, and how its verdict time is to be read (Ruling W2).
        "it uploads v4-data and every cell's v4-cell-* and v4-summary-*",
        "46 measures that load marks, against about 92 in a registered run",
        # The dispatch ref of each mode, once.
        "A registered run is dispatched from the registration's ref",
        "A timing run, made before the registration exists, is dispatched from a ref at the code",
        "A rehearsal may be dispatched from any ref",
        # The accepted residual: sizes and times are public.
        "Accepted residual",
    ):
        assert phrase in said, phrase
    assert "Three steps of the plan job" not in said
    # A single path uploads its files at the artifact's root: only the rehearsal's verdict
    # artifact, of three paths, keeps a folder.
    for wrong in (
        "verdict/ (verdict.json",
        "diagnosis/ (diagnosis.json",
        "status/status.json",
        "verdict/verdict-timing.json alone",
        "diagnosis/diagnose-timing.json alone",
        "a registered or timing run is dispatched from the registration's ref",
        "Only its v4-timing-* artifacts are downloaded after it; the cells' own artifacts",
    ):
        assert wrong not in said, wrong
