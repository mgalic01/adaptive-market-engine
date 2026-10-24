"""The v4-run workflow: V4.0's registered run, its rehearsal and its timing run.

``.github/workflows/v4-run.yml`` (plan ``docs/superpowers/plans/2026-10-24-v4-step4b-pipeline.md``,
Tasks 9 and 10) runs the 48 cells of V4's registration on GitHub's machines, in one of three modes:
``rehearsal`` (the registered job graph on a synthetic world, Ruling W3), ``timing`` (the 44 cells
that are not v3 on the real-size synthetic world, Ruling W2) and ``registered`` (the registered
experiment, once). These tests pin part 1 of its job graph: ``plan``, ``v3-pack``, ``v3-picks``,
``cell`` and ``v3-cell``.

They pin that it is dispatch-only and read-only, that its run name is the title the dispatch check
looks for and its jobs carry the names the check reads, that every action is pinned and every
checkout keeps no token, that no value is spliced into a script, that every artifact is kept one
day and named as Ruling W1 says, that the registered plan gates the checkout, refuses a second
dispatch and checks the data run before it downloads anything, that every cell job guards its data
and gates its checkout before its cell runs, that a cell's standard output goes to /dev/null, and
that the V3 pack's and the picks' pins are checked against the files.

The tests parse the YAML and never call GitHub. Some run one step's script in bash, as GitHub runs
it (``-e -o pipefail``): either for real on small files (the pin checks), or with ``python``,
``gh``, ``tar`` and ``sha256sum`` replaced by shell functions that only record their arguments
(``trace``), so no step reaches the network, GitHub's API or a real CLI.
"""

from __future__ import annotations

import functools
import hashlib
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

from crypto_grid_bot.v4.engine.v3_as_built import PICKS_FILE
from crypto_grid_bot.v4.verdict import inputs as verdict_inputs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_cell  # noqa: E402
import v4_cells_timing  # noqa: E402
import v4_registration  # noqa: E402
import v4_rehearsal  # noqa: E402
import v4_run_guard  # noqa: E402
import v4_run_plan  # noqa: E402
import v4_v3_cell  # noqa: E402
import v4_v3_pack  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "v4-run.yml"
CELLS_WORKFLOW = ROOT / ".github" / "workflows" / "v4-cells.yml"
V3_WORKFLOW = ROOT / ".github" / "workflows" / "v4-v3.yml"
MODES = ("rehearsal", "timing", "registered")
# Part 1's jobs, in the file's order (Task 9); part 2 (Task 10) adds scenarios, verdict, analysis
# and status after them.
PART_1_JOBS = ("plan", "v3-pack", "v3-picks", "cell", "v3-cell")
# The jobs that read GitHub's run listings or another run's artifacts: only they hold
# actions: read, and each records its start first, the dispatch check's budget clock.
CHECKING_JOBS = ("plan",)
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
# A cell's uploads run when every step passed, or when only the timing step failed (v4-cells.yml).
UPLOAD_CONDITION = "${{ success() || steps.timing.outcome == 'failure' }}"
TIMING_UPLOAD_CONDITION = (
    "${{ (success() || steps.timing.outcome == 'failure') && inputs.mode == 'timing' }}"
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
COMMIT = "c" * 40
# The cells each mode plans: the v3-cell job's matrix is empty in timing.
V3_COUNT = {mode: str(len(v4_run_plan.matrix(mode)[1])) for mode in MODES}


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
    script: str, cwd: Path, env: Mapping[str, str], *, prelude: str = ""
) -> subprocess.CompletedProcess[str]:
    """``script`` as GitHub runs a bash step (``-e -o pipefail``) in ``cwd``."""
    return subprocess.run(
        [real_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", prelude + script],
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
        "matrix.cell": "v4_main-1000-1x",
        "matrix.arm": "v4_main",
        "matrix.capital": "1000",
        "matrix.costs": "1",
        "needs.plan.outputs.registration_sha256": PLAN_SHA,
        "needs.plan.outputs.v3_pack_sha256": PLAN_PACK,
        "needs.v3-picks.outputs.picks_sha256": PICKS_SHA,
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


def test_jobs_are_named_as_the_dispatch_check_reads_them():
    # The dispatch check (layer L2) reads each earlier launch's jobs by the names GitHub gives
    # them: a job's id, or "<id> (<matrix values>)" for a matrix job. A job `name:` would change
    # them, and a launch with a job it does not know always counts.
    names = list(jobs())
    assert names[: len(PART_1_JOBS)] == list(PART_1_JOBS)
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
    found = 0
    for name, job in jobs().items():
        for step in job["steps"]:
            if "v4_rehearsal.py" not in str(step.get("run", "")):
                continue
            found += 1
            assert "if" in step, (name, step.get("name"))
            for failed in (False, True):
                assert not step_runs(step, "registered", failed=failed), (name, step.get("name"))
            assert step_runs(step, "rehearsal") or step_runs(step, "timing"), name
    assert found >= 2  # the plan's world and the rehearsal's picks
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


def test_cells_need_plan_and_guard_first(tmp_path):
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
    assert SETUP_STEPS <= download < guard < gate < replay

    # What runs before the cell, in each mode: the guard of the mode's data, then the gate
    # again (registered: on this checkout; rehearsal: on the world's repository; timing: none).
    for mode in MODES:
        events = trace("cell", mode, tmp_path / mode)
        timed = [i for i, event in enumerate(events) if event[0] == "timed"]
        before = events[: timed[0]]
        gate_repo = {"registered": ".", "rehearsal": "world/repo"}.get(mode)
        expected: list[tuple[Any, ...]] = [
            ("download", {"name": "v4-data", "path": "v4data"}),
            ("call", ["python", "scripts/v4_run_guard.py", "--data", "v4data",
                      *(["--manifest", MANIFEST] if mode == "registered" else ["--synthetic"])]),
        ]  # fmt: skip
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
        assert before == expected, mode
        for call in calls_of(before, "v4_registration.py"):
            assert v4_registration.build_parser().parse_args(call).mode == mode


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
    assert max(downloads) < pins < gate < replay
    assert "if" not in v3_steps[pins]

    # The check, run for real on small files: both digests must be the pins.
    (tmp_path / "v3pack").mkdir()
    (tmp_path / "picks").mkdir()
    (tmp_path / PACK_PATH).write_bytes(b"a pack")
    (tmp_path / PICKS_PATH).write_bytes(b'{"picks":{}}')
    pack = hashlib.sha256(b"a pack").hexdigest()
    picks = hashlib.sha256(b'{"picks":{}}').hexdigest()
    script = str(v3_steps[pins]["run"])
    done = run_script(script, tmp_path, {"PACK_SHA256": pack, "PICKS_SHA256": picks})
    assert done.returncode == 0, done.stderr
    assert done.stdout == ""
    for pack_pin, picks_pin in ((picks, picks), (pack, pack), ("", picks), (pack, ""), ("", "")):
        done = run_script(script, tmp_path, {"PACK_SHA256": pack_pin, "PICKS_SHA256": picks_pin})
        assert done.returncode != 0 and "::error::" in done.stderr, (pack_pin, picks_pin)
    for missing in (PACK_PATH, PICKS_PATH):
        moved = tmp_path / "moved"
        (tmp_path / missing).rename(moved)
        done = run_script(script, tmp_path, {"PACK_SHA256": pack, "PICKS_SHA256": picks})
        assert done.returncode != 0, missing
        moved.rename(tmp_path / missing)

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
                expected = job_steps[index]["if"] == UPLOAD_CONDITION or mode == "timing"
                assert (after_timing[index] == "success") is expected, (job, mode, index)
                assert after_replay[index] == "skipped", (job, mode, index)
    # The cells' standard output is the only one sent to /dev/null, and no step prints a result.
    redirected = [
        run_text(step)
        for body in jobs().values()
        for step in body["steps"]
        if "/dev/null" in str(step.get("run", ""))
    ]
    assert sorted(redirected) == sorted(f"mkdir -p out {TIMED}{c}" for c in REPLAYS.values())
    shown = re.compile(r"\b(cat|head|tail|less|more|jq|grep|sed|awk)\b")
    for name, body in jobs().items():
        for step in body["steps"]:
            script = run_text(step)
            assert shown.search(script) is None, (name, script)
            for result in ("records.jsonl", "summary.json", "receipt.json", "report.html"):
                assert result not in script, (name, result)


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
    build = index_of("v3-pack", "scripts/v4_v3_pack.py")
    check = index_of("v3-pack", "sha256sum")
    (upload,) = [i for i, s in enumerate(job_steps) if is_upload(s)]
    assert SETUP_STEPS <= build < check < upload == len(job_steps) - 1
    for step in job_steps[build:]:
        assert "if" not in step and "continue-on-error" not in step  # a refusal uploads nothing
    assert job_steps[upload]["with"] == {
        "name": "v4-v3-pack",
        "path": "out/",
        "if-no-files-found": "error",
        "retention-days": 1,
        "compression-level": 0,
    }

    # The check, run for real: the pack's digest must be both V3.1's pin and the plan's (the run
    # manifest's).
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / v4_v3_pack.PACK_FILE).write_bytes(b"a pack")
    digest = hashlib.sha256(b"a pack").hexdigest()
    script = str(job_steps[check]["run"])
    done = run_script(script, tmp_path, {"V3_PACK_SHA256": digest, "PACK_SHA256": digest})
    assert done.returncode == 0, done.stderr
    for v3_pin, plan_pin in ((digest, "0" * 64), ("0" * 64, digest), (digest, ""), ("", "")):
        done = run_script(script, tmp_path, {"V3_PACK_SHA256": v3_pin, "PACK_SHA256": plan_pin})
        assert done.returncode != 0 and "::error::" in done.stderr, (v3_pin, plan_pin)
    (tmp_path / "out" / v4_v3_pack.PACK_FILE).unlink()
    done = run_script(script, tmp_path, {"V3_PACK_SHA256": digest, "PACK_SHA256": digest})
    assert done.returncode != 0


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
