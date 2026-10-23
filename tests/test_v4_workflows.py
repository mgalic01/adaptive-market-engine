"""V4 workflows: the data workflow's ``config`` input, and every call that carries it.

``.github/workflows/v4-data.yml`` runs V4's data step on GitHub's machines. Its ``config`` input
picks the data config: the full one, or the pre-2025 one that the diagnostic run (2018-2024)
takes, whose ``end_month`` is 2024-12. The CLI and the month guard refuse any month after the
``end_month`` of the config they are given, so the reserved window (owner decision v4-d03: no
2025+ market data before the registered run) holds only if every call is given the chosen
config. The tests parse the YAML and never call GitHub.
"""

from __future__ import annotations

import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_data  # noqa: E402
import v4_data_month_guard  # noqa: E402

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
