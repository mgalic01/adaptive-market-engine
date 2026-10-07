"""The backtest workflow's variant input reaches the CLI.

A variant chosen in the dispatch form that no case arm of the "Run backtest" step maps to a flag
would run V0 under its name, so every choice except V0 needs its arm.
"""

import re
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/backtest.yml"
# One case arm: `<choice>) set -- "$@" <flag> ;;`.
ARM = re.compile(r'^\s*(\S+)\)\s+set -- "\$@" (--[a-z-]+) ;;$', re.MULTILINE)


def _workflow() -> dict:
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_every_variant_choice_maps_to_a_cli_flag() -> None:
    workflow = _workflow()
    choices = workflow[True]["workflow_dispatch"]["inputs"]["variant"]["options"]
    steps = workflow["jobs"]["run"]["steps"]
    (script,) = [step["run"] for step in steps if step.get("name") == "Run backtest"]
    arms = dict(ARM.findall(script))
    assert len(choices) == len(set(choices))
    assert set(choices) - {"V0"} == set(arms)
    assert arms["MS"] == "--mode-switch"
