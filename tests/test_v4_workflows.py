"""V4 workflows: the data workflow's ``config`` input, and the cells workflow's guard and jobs.

``.github/workflows/v4-data.yml`` runs V4's data step on GitHub's machines. Its ``config`` input
picks the data config: the full one, or the pre-2025 one that the diagnostic run (2018-2024)
takes, whose ``end_month`` is 2024-12. The CLI and the month guard refuse any month after the
``end_month`` of the config they are given, so the reserved window (owner decision v4-d03: no
2025+ market data before the registered run) holds only if every call is given the chosen
config.

``.github/workflows/v4-cells.yml`` runs the diagnostic run's cells over a ``v4-data`` run's packs.
Its tests pin the guard that refuses a data run reaching 2025 in every job that reads the packs,
the check of the data run itself (through the GitHub API) before plan downloads anything, the
one-day retention of every upload, the pinned actions, the way each input reaches the shell
(through the environment, never expanded into a script), the shape of the jobs, and the timing
and upload of a diagnosis that refused a cell.

``.github/workflows/v4-v3.yml`` runs the ``v3_as_built`` arm on GitHub: the ``pack`` job rebuilds
V3's input pack, the ``picks`` job trains V3's selector once on it, and the ``cells`` job replays
the four cells (capital 1000 and 10000, cost multiple 1 and 2) under GNU time. Its tests pin that
it is dispatch-only and read-only, installs as the data workflow does, takes no input, passes
every value to a script through the environment, pairs the pack's pin (a constant, the one of
V3.1's manifest) with the picks' pin (the picks job's output, computed from the file it wrote),
keeps a refused pin from ever uploading, and keeps what it makes for one day.

The tests parse the YAML and never call GitHub.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import subprocess  # nosec B404: the tests run the workflow's own steps in bash
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

from crypto_grid_bot.v4.engine.arms import CAPITALS, COST_MULTIPLES, DIAGNOSTIC_ARMS, CellSpec
from crypto_grid_bot.v4.engine.v3_as_built import PICKS_FILE, V3_ARM

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_cell  # noqa: E402
import v4_cells_guard  # noqa: E402
import v4_cells_plan  # noqa: E402
import v4_cells_timing  # noqa: E402
import v4_data  # noqa: E402
import v4_data_month_guard  # noqa: E402
import v4_v3_cell  # noqa: E402
import v4_v3_pack  # noqa: E402

DATA_WORKFLOW = ROOT / ".github" / "workflows" / "v4-data.yml"
FULL = "config/v4_data.json"
PRE2025 = "config/v4_data_pre2025.json"
SUBCOMMANDS = ("discover", "fetch", "select", "pack")
# Every `python scripts/v4_data.py ...` call, by job, in step order: one per job.
CLI_CALLS = {
    "discover": ["discover"],
    "fetch-daily": ["fetch"],
    "select-candidates": ["select"],
    "fetch-hourly": ["fetch"],
    "select-final": ["select"],
    "pack": ["pack"],
}
# What the workflow's shell variables are, in a call, when a test parses it with the real parser.
SHELL_VARIABLES = {"$KIND": "spot_1h", "$SHARD": "0", "$SHARDS": "8"}
# A script named in a `run` step: the script's name and the rest of its command line.
SCRIPT = re.compile(r"scripts/(?P<name>v4_data(?:_month_guard)?)\.py(?P<args>[^\n]*)")


def workflow() -> dict[str, Any]:
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    document = yaml.safe_load(DATA_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


@dataclass(frozen=True)
class Call:
    job: str
    script: str  # "v4_data" or "v4_data_month_guard"
    args: str  # the rest of the command line, its line continuations joined
    env: dict[str, str]  # the step's effective environment: workflow, job, then step


def calls(document: dict[str, Any]) -> list[Call]:
    found = []
    for job_name, job in document["jobs"].items():
        for step in job["steps"]:
            env: dict[str, str] = {}
            for scope in (document, job, step):
                env.update(scope.get("env", {}))
            run = step.get("run", "").replace("\\\n", " ")
            for match in SCRIPT.finditer(run):
                found.append(Call(job_name, match["name"], match["args"].strip(), env))
    return found


def parse(call: Call, config: str) -> Any:
    """The call's arguments, as the CLI's own parser reads them with ``$CONFIG`` set."""
    values = {**SHELL_VARIABLES, "$CONFIG": config}
    words = []
    for word in shlex.split(call.args):
        for name in sorted(values, key=len, reverse=True):  # $SHARDS before $SHARD
            word = word.replace(name, values[name])
        words.append(word)
    return v4_data.build_parser().parse_args(words)


def test_data_workflow_takes_a_config_input():
    document = workflow()
    inputs = document[True]["workflow_dispatch"]["inputs"]
    assert list(document[True]) == ["workflow_dispatch"]
    assert list(inputs) == ["stage", "config"]

    # A choice of exactly the two configs, the full one the default.
    config = inputs["config"]
    assert config["type"] == "choice"
    assert config["options"] == [FULL, PRE2025]
    assert config["default"] == FULL
    assert config["required"] is True
    for option in config["options"]:
        assert (ROOT / option).is_file(), option

    # Every call of the CLI and of the month guard passes it, through an environment variable.
    found = calls(document)
    assert [call.script for call in found].count("v4_data") == 6
    assert [call.script for call in found].count("v4_data_month_guard") == 6
    for call in found:
        assert call.env["CONFIG"] == "${{ inputs.config }}", call
        if call.script == "v4_data":
            assert call.args.startswith('--config "$CONFIG" '), call
        else:
            assert call.args == '--config "$CONFIG" --root v4', call

    # The run's name says which config it ran with.
    assert "inputs.config" in document["run-name"]
    assert "inputs.stage" in document["run-name"]

    # No config path is hard-coded outside the input (its default and its choices).
    text = DATA_WORKFLOW.read_text(encoding="utf-8")
    block = re.search(r"^      config:\n(?:        .*\n)+", text, re.MULTILINE)
    assert block is not None
    assert "config/v4_data" in block.group(0)
    assert "config/v4_data" not in text.replace(block.group(0), "")


def test_each_job_calls_the_cli_with_the_config_before_the_subcommand():
    found = [call for call in calls(workflow()) if call.script == "v4_data"]
    by_job: dict[str, list[str]] = {}
    for call in found:
        words = shlex.split(call.args)
        # argparse reads `--config` only before the subcommand: the CLI's docstring says so.
        assert words[:2] == ["--config", "$CONFIG"], call
        assert words[2] in SUBCOMMANDS, call
        by_job.setdefault(call.job, []).append(words[2])
    assert by_job == CLI_CALLS


@pytest.mark.parametrize("config", [FULL, PRE2025])
def test_the_real_parser_reads_every_call_with_the_chosen_config(config):
    found = [call for call in calls(workflow()) if call.script == "v4_data"]
    assert len(found) == 6
    for call in found:
        args = parse(call, config)
        assert args.config == Path(config), call
        assert args.command == shlex.split(call.args)[2], call


def test_no_step_sets_config_to_anything_but_the_input():
    document = workflow()
    assert document["env"] == {"CONFIG": "${{ inputs.config }}"}
    for name, job in document["jobs"].items():
        assert "CONFIG" not in job.get("env", {}), name
        for step in job["steps"]:
            assert "CONFIG" not in step.get("env", {}), (name, step)


def test_the_month_guard_follows_the_chosen_config(tmp_path, capsys):
    # The guard reads end_month from the config it is given (the workflow passes the input),
    # and looks at file names only: a file named for 2025-01 fails it with the pre-2025
    # config and passes it with the full one; 2024-12 passes with both.
    archive = "fetched/cache/data/spot/monthly/klines/AAAUSDT/1h/AAAUSDT-1h-"
    root = tmp_path / "v4"
    for name in ("2024-12", "2025-01"):
        path = root / f"{archive}{name}.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def guard(config: str, folder: Path) -> tuple[int, str]:
        argv = ["--config", str(ROOT / config), "--root", str(folder)]
        code = v4_data_month_guard.main(argv)
        captured = capsys.readouterr()
        return code, captured.out + captured.err

    code, output = guard(FULL, root)
    assert code == 0 and "end_month 2026-09" in output
    code, output = guard(PRE2025, root)
    assert code == 1 and "AAAUSDT-1h-2025-01.zip" in output and "end_month 2024-12" in output
    assert "AAAUSDT-1h-2024-12.zip" not in output
    (root / f"{archive}2025-01.zip").unlink()
    code, output = guard(PRE2025, root)
    assert code == 0 and "end_month 2024-12" in output


# ---- the v4-cells workflow ----

CELLS_WORKFLOW = ROOT / ".github" / "workflows" / "v4-cells.yml"
GUARD = "python scripts/v4_cells_guard.py --data v4data --config config/v4_data_pre2025.json"
# The SHA-256 of config/v4_data_pre2025.json, the config of the diagnostic data run 39885846429.
PRE2025_SHA256 = "58032f30391c7e66b239fe47e89b8f98e4a50ffbb33dc2d8a6b59f98b4d71b16"
PINNED = re.compile(r"^(?P<action>[\w.-]+/[\w.-]+)@(?P<sha>[0-9a-f]{40})$")
UPLOAD = "actions/upload-artifact@"
DOWNLOAD = "actions/download-artifact@"
# The cell's upload runs when every step passed, or when only the timing step failed.
UPLOAD_CONDITION = "${{ success() || steps.timing.outcome == 'failure' }}"
# The diagnosis's timing and upload run whenever the diagnosis ran, failed included.
DIAGNOSED = (
    "${{ !cancelled() && (steps.diagnose.outcome == 'success' || "
    "steps.diagnose.outcome == 'failure') }}"
)
DIAGNOSE = (
    "/usr/bin/time -v -o diagnose.time "
    'python scripts/v4_diagnose.py --data v4data --cells cells --planned "$PLANNED_CELLS" '
    "--out diagnosis"
)
DATA_RUN_CHECK = (
    'gh api "repos/$REPOSITORY/actions/runs/$RUN_ID" '
    '| python scripts/v4_cells_guard.py --data-run "$RUN_ID" --commit "$COMMIT"'
)


def cells() -> dict[str, Any]:
    document = yaml.safe_load(CELLS_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def cell_steps(job: str) -> list[dict[str, Any]]:
    steps = cells()["jobs"][job]["steps"]
    assert isinstance(steps, list)
    return steps


def run_text(step: dict[str, Any]) -> str:
    """A step's script on one line: continuations joined, whitespace collapsed."""
    return " ".join(str(step.get("run", "")).replace("\\\n", " ").split())


def index_of_run(job: str, needle: str) -> int:
    """The position of the one step of ``job`` whose script holds ``needle``."""
    found = [i for i, step in enumerate(cell_steps(job)) if needle in run_text(step)]
    assert len(found) == 1, (job, needle, found)
    return found[0]


def downloads(job: str) -> list[dict[str, Any]]:
    return [
        step["with"] for step in cell_steps(job) if str(step.get("uses", "")).startswith(DOWNLOAD)
    ]


def uploads(job: str) -> list[dict[str, Any]]:
    return [
        step["with"] for step in cell_steps(job) if str(step.get("uses", "")).startswith(UPLOAD)
    ]


def test_cells_workflow_guards_before_every_cell():
    jobs = cells()["jobs"]
    assert list(jobs) == ["plan", "cell", "diagnose"]

    # The guard runs in plan, after the data run's artifact is downloaded; in every cell job
    # before the cell; and in diagnose before the diagnosis reads the packs.
    for job, after in (("plan", None), ("cell", "scripts/v4_cell.py"), ("diagnose", "v4_diagnose")):
        guard = index_of_run(job, GUARD)
        (download,) = [
            i
            for i, s in enumerate(cell_steps(job))
            if str(s.get("uses", "")).startswith(DOWNLOAD) and s["with"].get("name") == "v4-data"
        ]
        assert download < guard, job
        if after is not None:
            assert guard < index_of_run(job, after), job
    # Codex P2 on #294: plan uploads the data it checked as this run's own v4-data, after the
    # guard, so the cells and the diagnosis never depend on the data run's artifact lasting.
    steps = cell_steps("plan")
    (upload,) = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(UPLOAD)]
    assert index_of_run("plan", GUARD) < upload == len(steps) - 1
    assert steps[upload]["with"]["path"] == "v4data/" and "if" not in steps[upload]
    assert steps[upload]["with"]["overwrite"] is True

    # No cell starts unless plan, guard included, succeeded: no `if` overrides the default.
    assert jobs["cell"]["needs"] == "plan"
    assert "if" not in jobs["cell"]
    assert "if" not in jobs["plan"] and "needs" not in jobs["plan"]

    # Every upload is kept one day, and an empty one is an error.
    assert [step["name"] for step in uploads("cell")] == ["v4-cell-${{ matrix.cell }}"]
    assert [step["name"] for step in uploads("diagnose")] == ["v4-diagnosis"]
    assert [step["name"] for step in uploads("plan")] == ["v4-data"]
    for job in jobs:
        for step in uploads(job):
            assert step["retention-days"] == 1, job
            assert step["if-no-files-found"] == "error", job


def test_cells_workflow_checks_the_data_run_before_downloading_it():
    """M2 of the final review: before plan downloads the data run's artifact, it asks the GitHub
    API for that run and refuses it unless it is a successful run of the v4-data workflow's full
    stage with the pre-2025 config (``v4_cells_guard.check_data_run``, tested on JSON in
    ``tests/test_v4_cells_guard.py``), made from this run's own commit (Codex P2 on #294:
    ``github.sha``, so the same data code made the packs). The run's JSON goes from ``gh api``
    straight into the check, through environment variables only, and the id is the plan step's
    validated one."""
    steps = cell_steps("plan")
    check = index_of_run("plan", "v4_cells_guard.py --data-run")
    assert run_text(steps[check]) == DATA_RUN_CHECK
    assert steps[check]["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPOSITORY": "${{ github.repository }}",
        "RUN_ID": "${{ steps.plan.outputs.data_run }}",
        "COMMIT": "${{ github.sha }}",
    }
    assert "if" not in steps[check]
    names = [step.get("with", {}).get("name") for step in steps]
    assert index_of_run("plan", "v4_cells_plan.py") < check < names.index("v4-data")
    # The cell and diagnose jobs download only after plan, this check included, succeeded.
    for job in ("cell", "diagnose"):
        assert not any("guard.py --data-run" in run_text(step) for step in cell_steps(job)), job
    # The command line is one the guard's own parser reads as the data-run check.
    command = run_text(steps[check]).split("| python scripts/v4_cells_guard.py ", 1)[1]
    values = {"$RUN_ID": "18734501234", "$COMMIT": "c" * 40}
    words = [values.get(w, w) for w in shlex.split(command)]
    args = v4_cells_guard.build_parser().parse_args(words)
    assert (args.data_run, args.commit, args.data) == ("18734501234", "c" * 40, None)
    # The data workflow's run name is the one the check requires of the data run.
    assert workflow()["run-name"] == "v4-data ${{ inputs.stage }} ${{ inputs.config }}"
    assert v4_cells_guard.DATA_RUN_TITLE.split(" ") == ["v4-data", "full", PRE2025]
    assert (ROOT / v4_cells_guard.DATA_WORKFLOW_PATH) == DATA_WORKFLOW


def test_cells_workflow_is_dispatch_only_and_read_only():
    document = cells()
    assert list(document[True]) == ["workflow_dispatch"]
    # actions: read lets the jobs download the artifact of another run (the data run).
    assert document["permissions"] == {"contents": "read", "actions": "read"}
    for name, job in document["jobs"].items():
        assert "permissions" not in job, name
        assert job["runs-on"] == "ubuntu-latest", name
        checkouts = [
            s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")
        ]
        assert len(checkouts) == 1 and checkouts[0]["with"] == {"persist-credentials": False}, name


def test_cells_workflow_inputs():
    inputs = cells()[True]["workflow_dispatch"]["inputs"]
    assert list(inputs) == ["data_run", "arms", "capitals", "costs"]
    for spec in inputs.values():
        assert spec["type"] == "string" and spec["required"] is True
    assert "default" not in inputs["data_run"]
    # The eight diagnostic arms by default, in the run's order: the arms only the registered run
    # adds (v4-d22) are not dispatched here.
    assert inputs["arms"]["default"] == ",".join(DIAGNOSTIC_ARMS)
    assert inputs["capitals"]["default"] == "10000"
    assert inputs["costs"]["default"] == "1"
    # The defaults are a plan the plan script accepts.
    planned = v4_cells_plan.build_cells(
        inputs["arms"]["default"], inputs["capitals"]["default"], inputs["costs"]["default"]
    )
    assert len(planned) == 8


def test_cells_workflow_pins_every_action_as_the_data_workflow_does():
    data_text = DATA_WORKFLOW.read_text(encoding="utf-8")
    known = dict(re.findall(r"uses: ([\w./-]+)@([0-9a-f]{40})", data_text))
    assert {"actions/checkout", "actions/setup-python", UPLOAD[:-1], DOWNLOAD[:-1]} <= set(known)
    used = [
        str(step["uses"])
        for job in cells()["jobs"].values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert used
    for uses in used:
        match = PINNED.match(uses)
        assert match is not None, uses
        assert known[match["action"]] == match["sha"], uses


def test_cells_workflow_never_expands_an_expression_into_a_script():
    # Inputs and matrix values reach a script as environment variables ("$ARM"), never as text
    # in it, so a value cannot become shell code.
    for job, body in cells()["jobs"].items():
        for step in body["steps"]:
            assert "${{" not in str(step.get("run", "")), (job, step)


def test_cells_workflow_takes_the_data_run_id_only_after_the_plan_validated_it():
    plan = cells()["jobs"]["plan"]
    assert plan["outputs"] == {
        "matrix": "${{ steps.plan.outputs.matrix }}",
        "cells": "${{ steps.plan.outputs.cells }}",
        "cell_ids": "${{ steps.plan.outputs.cell_ids }}",
    }
    # The raw input is read twice: the run's name, and the plan step's environment.
    text = CELLS_WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert code.count("inputs.data_run") == 2
    assert plan["env"]["DATA_RUN"] == "${{ inputs.data_run }}"
    assert plan["steps"][index_of_run("plan", "v4_cells_plan.py")]["id"] == "plan"
    # The one download of the data run's artifact, in plan, names the run by the validated
    # output, and the validation comes first. The cell and diagnose jobs download this run's own
    # copy, which plan uploaded after its guard (Codex P2 on #294): no run-id.
    assert index_of_run("plan", "v4_cells_plan.py") < [
        s.get("with", {}).get("name") for s in plan["steps"]
    ].index("v4-data")
    (data,) = [d for d in downloads("plan") if d.get("name") == "v4-data"]
    assert data == {
        "name": "v4-data",
        "run-id": "${{ steps.plan.outputs.data_run }}",
        "github-token": "${{ github.token }}",
        "path": "v4data",
    }
    for job in ("cell", "diagnose"):
        (data,) = [d for d in downloads(job) if d.get("name") == "v4-data"]
        assert data == {"name": "v4-data", "path": "v4data"}, job
    assert "outputs.data_run" not in str(cells()["jobs"]["cell"])
    assert "outputs.data_run" not in str(cells()["jobs"]["diagnose"])


def test_cells_workflow_plan_step_matches_the_plan_scripts_parser():
    plan = cells()["jobs"]["plan"]
    assert plan["env"] == {
        "DATA_RUN": "${{ inputs.data_run }}",
        "ARMS": "${{ inputs.arms }}",
        "CAPITALS": "${{ inputs.capitals }}",
        "COSTS": "${{ inputs.costs }}",
    }
    run = run_text(plan["steps"][index_of_run("plan", "v4_cells_plan.py")])
    prefix = "python scripts/v4_cells_plan.py "
    assert run.startswith(prefix)
    values = {
        "$DATA_RUN": "1234567890",
        "$ARMS": "v4_main,hold_btc",
        "$CAPITALS": "10000",
        "$COSTS": "1",
        "$GITHUB_OUTPUT": "out.txt",
    }
    words = shlex.split(run.removeprefix(prefix))
    args = v4_cells_plan.build_parser().parse_args([values.get(word, word) for word in words])
    assert (args.data_run, args.arms, args.capitals, args.costs) == (
        "1234567890",
        "v4_main,hold_btc",
        "10000",
        "1",
    )
    assert args.github_output == Path("out.txt")


def test_cells_workflow_guard_steps_match_the_guards_parser():
    for job in ("plan", "cell", "diagnose"):
        run = run_text(cell_steps(job)[index_of_run(job, GUARD)])
        assert run == GUARD, job
        args = v4_cells_guard.build_parser().parse_args(shlex.split(run.split("guard.py ")[1]))
        assert args.data == Path("v4data") and args.latest_month == "2024-12"
        # Codex P2 on #294: the data's config pin must be the checked-in pre-2025 config's.
        assert args.config == Path("config/v4_data_pre2025.json")
        digest = hashlib.sha256((ROOT / args.config).read_bytes()).hexdigest()
        assert digest == PRE2025_SHA256


def test_cells_workflow_cell_job_runs_one_matrix_entry_under_gnu_time():
    job = cells()["jobs"]["cell"]
    # The first run is where the real cell time is learned: 340 of the 360 minutes a hosted job
    # may run.
    assert job["timeout-minutes"] == 340
    assert job["strategy"] == {
        "fail-fast": False,
        "matrix": "${{ fromJSON(needs.plan.outputs.matrix) }}",
    }  # no max-parallel
    assert job["env"] == {
        "CELL": "${{ matrix.cell }}",
        "ARM": "${{ matrix.arm }}",
        "CAPITAL": "${{ matrix.capital }}",
        "COSTS": "${{ matrix.costs }}",
    }
    steps = job["steps"]

    # GNU time is checked first, then the cell runs under it, then the helper reads its file.
    check = index_of_run("cell", "-x /usr/bin/time")
    replay = index_of_run("cell", "scripts/v4_cell.py")
    timing = index_of_run("cell", "scripts/v4_cells_timing.py")
    assert check < replay < timing
    assert "::error::" in run_text(steps[check]) and "exit 1" in run_text(steps[check])
    run = run_text(steps[replay])
    assert run.count('/usr/bin/time -v -o "out/$CELL.time" ') == 1
    command = run.split('"out/$CELL.time" ', 1)[1]
    assert command.startswith("python scripts/v4_cell.py run ")
    # Codex P2 on #294: the cell's own line holds its outcome, a result, so its standard output
    # goes to /dev/null, never to the public log.
    assert command.endswith(" > /dev/null") and command.count(">") == 1
    command = command.removesuffix(" > /dev/null")
    values = {"$ARM": "v4_faster", "$CAPITAL": "1000", "$COSTS": "2"}
    words = [values.get(word, word) for word in shlex.split(command)[2:]]
    args = v4_cell.build_parser().parse_args(words)
    assert (args.command, args.arm, args.capital, args.costs) == ("run", "v4_faster", 1000, 2)
    assert (args.data, args.out) == (Path("v4data"), Path("out"))
    assert run_text(steps[timing]) == (
        'python scripts/v4_cells_timing.py --time-file "out/$CELL.time" --cell-dir "out/$CELL"'
    )

    # The cell's own folder, timing.json included, is the artifact, named for the cell.
    (upload,) = uploads("cell")
    assert upload["name"] == "v4-cell-${{ matrix.cell }}"
    assert upload["path"] == "out/${{ matrix.cell }}/"


def test_cells_workflow_a_failed_timing_step_does_not_discard_the_replay():
    steps = cell_steps("cell")
    timing = index_of_run("cell", "scripts/v4_cells_timing.py")
    assert steps[timing]["id"] == "timing"
    (upload,) = [i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith(UPLOAD)]
    assert upload > timing
    # After a successful run of every step, or after a failed timing step and nothing else: a
    # failed replay (or guard, or download) leaves the timing step skipped, so nothing uploads.
    assert steps[upload]["if"] == UPLOAD_CONDITION
    assert UPLOAD_CONDITION == "${{ success() || steps.timing.outcome == 'failure' }}"
    # Nothing else that could fail the job follows the upload, so the job still ends red.
    assert upload == len(steps) - 1


def test_cells_workflow_has_no_continue_on_error_and_three_step_conditions():
    text = CELLS_WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "continue-on-error" not in code
    conditions = [
        (job, str(step.get("uses", step.get("run"))).split("@")[0].split(" --")[0], step["if"])
        for job, body in cells()["jobs"].items()
        for step in body["steps"]
        if "if" in step
    ]
    # The allowed step conditions: the cell's upload (see the test above), and the diagnosis's
    # timing and upload, which run after a diagnosis that failed too (see the diagnose tests).
    assert conditions == [
        ("cell", "actions/upload-artifact", UPLOAD_CONDITION),
        ("diagnose", "python scripts/v4_cells_timing.py", DIAGNOSED),
        ("diagnose", "actions/upload-artifact", DIAGNOSED),
    ]
    # Neither plan nor cell has a job condition (diagnose's own is pinned in its test).
    for name in ("plan", "cell"):
        assert "if" not in cells()["jobs"][name], name


def test_cells_workflow_diagnose_runs_after_every_cell_that_finished():
    job = cells()["jobs"]["diagnose"]
    assert job["needs"] == ["plan", "cell"]
    # A failed or timed-out cell still lets the diagnosis of the others run: GitHub may report a
    # timed-out job as cancelled, so the cell's result is not tested. A cancelled run does not
    # run it, and a failed plan (which skips every cell) never does.
    assert job["if"] == "${{ !cancelled() && needs.plan.result == 'success' }}"
    assert "needs.cell.result" not in job["if"] and "always()" not in job["if"]
    (cell_download,) = [d for d in downloads("diagnose") if "pattern" in d]
    assert cell_download == {"pattern": "v4-cell-*", "merge-multiple": False, "path": "cells"}
    diagnose = index_of_run("diagnose", "scripts/v4_diagnose.py")
    assert run_text(job["steps"][diagnose]) == DIAGNOSE
    # Codex P2 on #294: its --planned is the plan's validated cell ids, as an environment
    # variable, so the missing cells it lists are the dispatch's.
    assert job["env"]["PLANNED_CELLS"] == "${{ needs.plan.outputs.cell_ids }}"
    (upload,) = uploads("diagnose")
    assert upload["name"] == "v4-diagnosis" and upload["path"] == "diagnosis/"
    # The cells are counted before the diagnosis; none at all stops the job with an error.
    counted = index_of_run("diagnose", "planned cells")
    assert counted < diagnose
    assert "::error::" in run_text(job["steps"][counted])
    assert "exit 1" in run_text(job["steps"][counted])


def test_cells_workflow_times_the_diagnosis_and_keeps_a_partial_one():
    """M1 and M4 of the final review. The diagnosis runs under GNU time, checked first as in a
    cell job; its wall time and peak memory go to ``diagnosis/diagnose-timing.json`` (the proxy
    for the registered run's verdict step and its 2 GB memory limit). A diagnosis that refused a
    cell writes the others' diagnosis and exits 1, so the timing and the upload run after the
    diagnosis step whether it succeeded or failed, and not when it never ran; the upload comes
    last, after the timing, so the artifact holds diagnose-timing.json."""
    steps = cell_steps("diagnose")
    check = index_of_run("diagnose", "-x /usr/bin/time")
    diagnose = index_of_run("diagnose", "scripts/v4_diagnose.py")
    timing = index_of_run("diagnose", "scripts/v4_cells_timing.py")
    (upload,) = [i for i, step in enumerate(steps) if str(step.get("uses", "")).startswith(UPLOAD)]
    assert index_of_run("diagnose", GUARD) < check < diagnose < timing < upload == len(steps) - 1
    assert "::error::" in run_text(steps[check]) and "exit 1" in run_text(steps[check])
    assert steps[diagnose]["id"] == "diagnose" and "if" not in steps[diagnose]
    assert run_text(steps[diagnose]) == DIAGNOSE
    assert run_text(steps[timing]) == (
        "python scripts/v4_cells_timing.py --time-file diagnose.time --diagnosis-dir diagnosis"
    )
    args = v4_cells_timing.build_parser().parse_args(shlex.split(run_text(steps[timing]))[2:])
    assert (args.time_file, args.diagnosis_dir, args.cell_dir) == (
        Path("diagnose.time"),
        Path("diagnosis"),
        None,
    )
    assert steps[timing]["if"] == steps[upload]["if"] == DIAGNOSED
    assert steps[upload]["with"]["if-no-files-found"] == "error"


def test_cells_workflow_logs_counts_only():
    # No step prints or searches a result file: the logs are public.
    shown = re.compile(r"\b(cat|head|tail|less|more|jq|grep|sed|awk)\b")
    for job, body in cells()["jobs"].items():
        for step in body["steps"]:
            text = run_text(step)
            assert shown.search(text) is None, (job, text)
            for name in ("records.jsonl", "summary.json", "receipt.json", "report.html"):
                assert name not in text, (job, name)


def test_cells_workflow_header_says_what_the_run_depends_on():
    header = CELLS_WORKFLOW.read_text(encoding="utf-8").split("\non:\n")[0]
    # The data artifact is kept one day, so a cells run must start within a day of its data run,
    # and the data run must be of the cells run's own commit.
    assert "24 hours" in header
    assert "same commit as this run" in header
    # The reserved window.
    assert "v4-d03" in header and "2024-12" in header and "2025-01" in header
    # No market-data request, which is not "no network request": checkout, pip and the artifact
    # downloads are network requests.
    assert "no market-data request" in header
    assert "no network request" not in header


# ---- the v4-v3 workflow ----

V3_WORKFLOW = ROOT / ".github" / "workflows" / "v4-v3.yml"
# The steps every job of the data workflow starts with: checkout, setup-python, three installs.
SETUP_STEPS = 5


def v3_workflow() -> dict[str, Any]:
    document = yaml.safe_load(V3_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_v4_v3_workflow_pack_job():
    document = v3_workflow()
    # Dispatch only, and no input: the pack is one fixed thing, so nothing reaches a script.
    assert list(document[True]) == ["workflow_dispatch"]
    assert not (document[True]["workflow_dispatch"] or {}).get("inputs")
    assert document["permissions"] == {"contents": "read"}

    job = document["jobs"]["pack"]
    assert "permissions" not in job and job["runs-on"] == "ubuntu-latest"
    steps = job["steps"]

    # It checks out without keeping the token, sets up Python 3.12 and installs exactly as the
    # data workflow's jobs do (the same SHA-pinned actions, the same pip cache, the same locks).
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkouts) == 1 and checkouts[0]["with"] == {"persist-credentials": False}
    data_steps = yaml.safe_load(DATA_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["discover"][
        "steps"
    ]
    assert steps[:SETUP_STEPS] == data_steps[:SETUP_STEPS]
    assert steps[1]["with"]["python-version"] == "3.12"

    # It runs the pack script on the two folders, and only that.
    scripts = [run_text(s) for s in steps if "scripts/" in str(s.get("run", ""))]
    assert scripts == ["python scripts/v4_v3_pack.py --work work --out out"]

    # It uploads out/ as v4-v3-pack, kept one day, and fails when there is nothing to upload.
    (upload,) = [s for s in steps if str(s.get("uses", "")).startswith(UPLOAD)]
    assert steps.index(upload) > max(
        i for i, s in enumerate(steps) if "scripts/" in str(s.get("run", ""))
    )
    assert upload["with"]["name"] == "v4-v3-pack"
    assert upload["with"]["path"] == "out/"
    assert upload["with"]["retention-days"] == 1
    assert upload["with"]["if-no-files-found"] == "error"


def test_v4_v3_workflow_pins_every_action_as_the_data_workflow_does():
    data_text = DATA_WORKFLOW.read_text(encoding="utf-8")
    known = dict(re.findall(r"uses: ([\w./-]+)@([0-9a-f]{40})", data_text))
    used = [
        str(step["uses"])
        for job in v3_workflow()["jobs"].values()
        for step in job["steps"]
        if "uses" in step
    ]
    assert used
    for uses in used:
        match = PINNED.match(uses)
        assert match is not None, uses
        assert known[match["action"]] == match["sha"], uses


def test_v4_v3_workflow_never_expands_an_expression_into_a_script():
    for job, body in v3_workflow()["jobs"].items():
        for step in body["steps"]:
            assert "${{" not in str(step.get("run", "")), (job, step)


def test_v4_v3_workflow_keeps_every_upload_one_day_and_checks_out_without_credentials():
    for job, body in v3_workflow()["jobs"].items():
        steps = body["steps"]
        for step in steps:
            uses = str(step.get("uses", ""))
            if uses.startswith(UPLOAD):
                assert step["with"]["retention-days"] == 1, job
                assert step["with"]["if-no-files-found"] == "error", job
            if uses.startswith("actions/checkout@"):
                assert step["with"] == {"persist-credentials": False}, job


# ---- the v4-v3 workflow's picks and cells jobs ----

# V3.1's registered pack pin, in the workflow's environment (see the pin test below).
PACK_PIN = v4_v3_pack.EXPECTED_PACK_SHA256
PACK_PATH = f"v3pack/{v4_v3_pack.PACK_FILE}"
PICKS_PATH = f"picks/{PICKS_FILE}"
V3_PICKS = (
    f'python scripts/v4_v3_cell.py picks --pack {PACK_PATH} --pack-sha256 "$V3_PACK_SHA256" '
    "--out picks"
)
V3_TIMED = '/usr/bin/time -v -o "out/$CELL.time" '
V3_CELL_RUN = (
    f'python scripts/v4_v3_cell.py run --pack {PACK_PATH} --pack-sha256 "$V3_PACK_SHA256" '
    f'--picks {PICKS_PATH} --picks-sha256 "$PICKS_SHA256" '
    '--capital "$CAPITAL" --costs "$COSTS" --out out > /dev/null'
)
# The cells job's upload runs after a failed timing step, as in the diagnostic run's cell job.
V3_UPLOAD_CONDITION = UPLOAD_CONDITION


def v3_steps(job: str) -> list[dict[str, Any]]:
    steps = v3_workflow()["jobs"][job]["steps"]
    assert isinstance(steps, list)
    return steps


def v3_index(job: str, needle: str) -> int:
    """The position of the one step of ``job`` whose script holds ``needle``."""
    found = [i for i, step in enumerate(v3_steps(job)) if needle in run_text(step)]
    assert len(found) == 1, (job, needle, found)
    return found[0]


def v3_downloads(job: str) -> list[dict[str, Any]]:
    return [s["with"] for s in v3_steps(job) if str(s.get("uses", "")).startswith(DOWNLOAD)]


def v3_code() -> str:
    """The workflow's text without its comment lines."""
    text = V3_WORKFLOW.read_text(encoding="utf-8")
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def real_bash() -> str:
    shell = (
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    assert shell and Path(shell).is_file(), "Git Bash (Windows) or bash is required"
    return shell


def run_v3_step(
    step: dict[str, Any], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """The step's script as GitHub runs a bash step (``-e -o pipefail``) in ``cwd``."""
    return subprocess.run(
        [real_bash(), "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_v4_v3_workflow_job_graph_and_timeouts():
    document = v3_workflow()
    jobs = document["jobs"]
    assert list(jobs) == ["pack", "picks", "cells"]
    assert jobs["pack"]["timeout-minutes"] == 180
    assert jobs["picks"]["needs"] == "pack" and jobs["picks"]["timeout-minutes"] == 300
    # The cells download both artifacts: they come after the pack and the picks.
    assert jobs["cells"]["needs"] == ["pack", "picks"] and jobs["cells"]["timeout-minutes"] == 60
    assert document["permissions"] == {"contents": "read"}
    data_steps = yaml.safe_load(DATA_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["discover"][
        "steps"
    ]
    for name in ("picks", "cells"):
        job = jobs[name]
        # Read-only, like every job here; no job condition: a failed job skips the ones after it.
        assert "permissions" not in job and "if" not in job, name
        assert job["runs-on"] == "ubuntu-latest", name
        assert job["steps"][:SETUP_STEPS] == data_steps[:SETUP_STEPS], name


def test_v4_v3_workflow_pack_pin_is_v31s_registered_one():
    # The pack's pin is a constant of the workflow, never an input and never read from the pack
    # job's own file: it is the pin of V3.1's run manifest and of scripts/v4_v3_pack.py, so the
    # picks and cell jobs check the downloaded pack against the registered pin.
    manifest = yaml.safe_load((ROOT / "config" / "v3_1_run_manifest.json").read_text("utf-8"))
    assert manifest["v3_pack_sha256"] == PACK_PIN
    assert v3_workflow()["env"] == {"V3_PACK_SHA256": PACK_PIN}
    assert v3_code().count(PACK_PIN) == 1


def test_v4_v3_workflow_picks_job():
    job = v3_workflow()["jobs"]["picks"]
    steps = job["steps"]

    # The pack job's artifact, of this run, into v3pack/.
    assert v3_downloads("picks") == [{"name": "v4-v3-pack", "path": "v3pack"}]
    download = next(i for i, s in enumerate(steps) if "download-artifact" in str(s.get("uses")))
    picks = v3_index("picks", "scripts/v4_v3_cell.py")
    pin = v3_index("picks", "GITHUB_OUTPUT")
    (upload,) = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(UPLOAD)]
    assert SETUP_STEPS <= download < picks < pin < upload == len(steps) - 1

    # The picks command, read by the real parser: the pack and its registered pin, the folder.
    assert run_text(steps[picks]) == V3_PICKS
    command = run_text(steps[picks])
    values = {"$V3_PACK_SHA256": PACK_PIN}
    words = [values.get(word, word) for word in shlex.split(command)[2:]]
    args = v4_v3_cell.build_parser().parse_args(words)
    assert (args.command, args.pack, args.pack_sha256, args.out) == (
        "picks",
        Path(PACK_PATH),
        PACK_PIN,
        Path("picks"),
    )

    # The picks' pin is the job's output, computed from the file the script wrote.
    assert steps[pin]["id"] == "pin"
    assert job["outputs"] == {"picks_sha256": "${{ steps.pin.outputs.picks_sha256 }}"}
    assert f"sha256sum {PICKS_PATH}" in run_text(steps[pin])

    # The picks folder, which holds the picks file alone, is the artifact.
    assert steps[upload]["with"] == {
        "name": "v4-v3-picks",
        "path": "picks/",
        "if-no-files-found": "error",
        "retention-days": 1,
        "overwrite": True,
    }


def test_v4_v3_workflow_the_picks_pin_reaches_the_cells_only_through_the_picks_output():
    code = v3_code()
    # No dispatch input exists, so no input can name a pin.
    assert "inputs." not in code and "workflow_dispatch" in code
    # The output name occurs in the picks job's output, the step that writes it, and the cells'
    # environment, which reads it from the picks job: nowhere else.
    assert code.count("needs.picks.outputs.picks_sha256") == 1
    cells = v3_workflow()["jobs"]["cells"]
    assert cells["env"]["PICKS_SHA256"] == "${{ needs.picks.outputs.picks_sha256 }}"
    # The cell's command takes both pins from the environment.
    run = run_text(cells["steps"][v3_index("cells", "scripts/v4_v3_cell.py")])
    assert '--pack-sha256 "$V3_PACK_SHA256"' in run and '--picks-sha256 "$PICKS_SHA256"' in run


def test_v4_v3_workflow_picks_output_step_writes_the_files_digest(tmp_path):
    step = v3_steps("picks")[v3_index("picks", "GITHUB_OUTPUT")]
    (tmp_path / "picks").mkdir()
    raw = b'{"picks":{}}'
    (tmp_path / PICKS_PATH).write_bytes(raw)
    output = tmp_path / "github_output"
    done = run_v3_step(step, tmp_path, {"GITHUB_OUTPUT": output.as_posix()})
    assert done.returncode == 0, done.stderr
    assert output.read_text(encoding="utf-8") == f"picks_sha256={hashlib.sha256(raw).hexdigest()}\n"
    assert done.stdout == ""  # nothing to the public log from this step


def test_v4_v3_workflow_picks_output_step_fails_without_the_file_and_writes_nothing(tmp_path):
    step = v3_steps("picks")[v3_index("picks", "GITHUB_OUTPUT")]
    output = tmp_path / "github_output"
    done = run_v3_step(step, tmp_path, {"GITHUB_OUTPUT": output.as_posix()})
    assert done.returncode != 0
    assert not output.exists() or output.read_text(encoding="utf-8") == ""


def test_v4_v3_workflow_cells_job_matrix_and_environment():
    job = v3_workflow()["jobs"]["cells"]
    assert job["name"] == "cell ${{ matrix.cell }}"
    # The four cells of the arm, one job each, one failed cell leaving the others running.
    expected = [
        {"cell": CellSpec(V3_ARM, capital, costs).cell_id, "capital": capital, "costs": costs}
        for capital in CAPITALS
        for costs in COST_MULTIPLES
    ]
    assert len(expected) == 4
    assert job["strategy"] == {"fail-fast": False, "matrix": {"include": expected}}
    assert job["env"] == {
        "CELL": "${{ matrix.cell }}",
        "CAPITAL": "${{ matrix.capital }}",
        "COSTS": "${{ matrix.costs }}",
        "PICKS_SHA256": "${{ needs.picks.outputs.picks_sha256 }}",
    }


def test_v4_v3_workflow_cells_job_runs_one_cell_under_gnu_time():
    steps = v3_steps("cells")
    assert v3_downloads("cells") == [
        {"name": "v4-v3-pack", "path": "v3pack"},
        {"name": "v4-v3-picks", "path": "picks"},
    ]
    downloads_at = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(DOWNLOAD)]
    verify = v3_index("cells", "sha256sum")
    check = v3_index("cells", "-x /usr/bin/time")
    replay = v3_index("cells", "scripts/v4_v3_cell.py")
    timing = v3_index("cells", "scripts/v4_cells_timing.py")
    (upload,) = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(UPLOAD)]
    # Both artifacts, then the picks' pin check, then GNU time's check, the cell under it, the
    # helper that reads time's file, and the upload last.
    assert min(downloads_at) >= SETUP_STEPS and max(downloads_at) < verify < check < replay
    assert replay < timing < upload == len(steps) - 1
    assert "::error::" in run_text(steps[check]) and "exit 1" in run_text(steps[check])

    run = run_text(steps[replay])
    assert run.count(V3_TIMED) == 1 and run == f"mkdir -p out {V3_TIMED}{V3_CELL_RUN}"
    command = run.split(V3_TIMED, 1)[1]
    # The cell's own line holds its outcome, a result, so its standard output goes to /dev/null.
    assert command.endswith(" > /dev/null") and command.count(">") == 1
    command = command.removesuffix(" > /dev/null")
    picks_pin = "ab" * 32
    values = {
        "$V3_PACK_SHA256": PACK_PIN,
        "$PICKS_SHA256": picks_pin,
        "$CAPITAL": "1000",
        "$COSTS": "2",
    }
    words = [values.get(word, word) for word in shlex.split(command)[2:]]
    args = v4_v3_cell.build_parser().parse_args(words)
    assert (args.command, args.pack, args.pack_sha256) == ("run", Path(PACK_PATH), PACK_PIN)
    assert (args.picks, args.picks_sha256) == (Path(PICKS_PATH), picks_pin)
    assert (args.capital, args.costs, args.out) == (1000, 2, Path("out"))
    assert steps[timing]["id"] == "timing"
    assert run_text(steps[timing]) == (
        'python scripts/v4_cells_timing.py --time-file "out/$CELL.time" --cell-dir "out/$CELL"'
    )
    parsed = v4_cells_timing.build_parser().parse_args(shlex.split(run_text(steps[timing]))[2:])
    assert (parsed.time_file, parsed.cell_dir) == (Path("out/$CELL.time"), Path("out/$CELL"))

    # The cell's folder is the artifact: kept after a failed timing step, not after a failed
    # replay, which leaves the timing step skipped.
    assert steps[upload]["if"] == V3_UPLOAD_CONDITION
    assert steps[upload]["with"] == {
        "name": "v4-cell-${{ matrix.cell }}",
        "path": "out/${{ matrix.cell }}/",
        "if-no-files-found": "error",
        "retention-days": 1,
        "overwrite": True,
    }


def test_v4_v3_workflow_cells_check_the_picks_file_against_the_picks_jobs_pin(tmp_path):
    step = v3_steps("cells")[v3_index("cells", "sha256sum")]
    text = run_text(step)
    assert PICKS_PATH in text and '"$PICKS_SHA256"' in text
    assert "::error::" in text and "exit 1" in text
    (tmp_path / "picks").mkdir()
    raw = b'{"picks":{}}'
    (tmp_path / PICKS_PATH).write_bytes(raw)
    right = hashlib.sha256(raw).hexdigest()

    done = run_v3_step(step, tmp_path, {"PICKS_SHA256": right})
    assert done.returncode == 0, done.stderr
    assert done.stdout == "" and right not in done.stderr

    for wrong in ("0" * 64, "", right.upper()):  # another digest, none (the output was empty)
        done = run_v3_step(step, tmp_path, {"PICKS_SHA256": wrong})
        assert done.returncode != 0 and "::error::" in done.stderr, wrong
    (tmp_path / PICKS_PATH).unlink()  # no picks file at all
    assert run_v3_step(step, tmp_path, {"PICKS_SHA256": right}).returncode != 0


def test_v4_v3_workflow_a_refused_pin_never_uploads():
    # Task 5's review: no step lets a failure through, and no upload carries a condition that
    # would run it after a failed step, so a pack, picks or cell that failed uploads nothing.
    code = v3_code()
    assert "continue-on-error" not in code
    for job, script in (("pack", "scripts/v4_v3_pack.py"), ("picks", "scripts/v4_v3_cell.py")):
        steps = v3_steps(job)
        (at,) = [i for i, s in enumerate(steps) if script in str(s.get("run", ""))]
        assert "continue-on-error" not in steps[at] and "if" not in steps[at], job
        (upload,) = [i for i, s in enumerate(steps) if str(s.get("uses", "")).startswith(UPLOAD)]
        assert upload > at and "continue-on-error" not in steps[upload], job
        assert steps[upload].get("if") in (None, "${{ success() }}"), job
        for between in steps[at + 1 : upload]:  # nothing between them may be skipped over
            assert "continue-on-error" not in between and "if" not in between, job
    # The only step condition of the whole workflow is the cells' upload.
    conditions = [
        (job, str(step.get("uses", step.get("run"))).split("@")[0], step["if"])
        for job, body in v3_workflow()["jobs"].items()
        for step in body["steps"]
        if "if" in step
    ]
    assert conditions == [("cells", "actions/upload-artifact", V3_UPLOAD_CONDITION)]


def test_v4_v3_workflow_logs_counts_only():
    # No step prints or searches a result file: the logs are public.
    shown = re.compile(r"\b(cat|head|tail|less|more|jq|grep|sed|awk)\b")
    for job, body in v3_workflow()["jobs"].items():
        for step in body["steps"]:
            text = run_text(step)
            assert shown.search(text) is None, (job, text)
            for name in ("records.jsonl", "summary.json", "receipt.json", "report.html"):
                assert name not in text, (job, name)
    # A cell's standard output, which holds its outcome, is the only redirect to /dev/null.
    redirected = [
        run_text(step)
        for body in v3_workflow()["jobs"].values()
        for step in body["steps"]
        if "/dev/null" in run_text(step)
    ]
    assert len(redirected) == 1 and redirected[0].endswith(V3_CELL_RUN)


def test_v4_v3_workflow_header_says_what_the_jobs_do():
    header = V3_WORKFLOW.read_text(encoding="utf-8").split("\non:\n")[0]
    for text in (
        "- pack:",
        "- picks (",
        "- cells (",
        "v4-v3-picks",
        "picks_sha256",
        "/dev/null",
        "R4",
    ):
        assert text in header, text
