"""The automated review must post its verdict, or fail where a reader sees it."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/claude-review.yml"


def steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return list(workflow["jobs"]["review"]["steps"])


def allowed_tools() -> list[str]:
    action = next(s for s in steps() if str(s.get("uses", "")).startswith("anthropics/"))
    found = re.fullmatch(r'--allowedTools "([^"]*)"', action["with"]["claude_args"])
    assert found is not None
    return found.group(1).split(",")


def test_a_review_that_posts_nothing_fails_the_job() -> None:
    names = [s.get("name") or s.get("uses") for s in steps()]
    action = next(i for i, n in enumerate(names) if str(n).startswith("anthropics/"))
    check = names.index("Require the posted review comment")
    assert names.index("Record the start time") < action < check
    step = steps()[check]
    assert "if" not in step  # runs only after a successful review step, never skipped silently
    assert step["env"]["SINCE"] == "${{ steps.start.outputs.time }}"
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert '"claude[bot]"' in step["run"] and "exit 1" in step["run"]
    assert "''|*[!0-9]*) posted=0" in step["run"]  # an empty answer counts as no comment
    # Event values reach the shell through env only, never by interpolation into the script.
    assert "${{" not in step["run"]


def test_the_reviewer_can_read_a_large_diff_and_post_without_shell_tricks() -> None:
    tools = allowed_tools()
    for needed in ("Bash(git diff:*)", "Bash(git log:*)", "Bash(gh pr comment:*)", "Write"):
        assert needed in tools
    # Every Bash permission names one command; none allows an arbitrary shell.
    assert all(t.startswith("Bash(") and t.endswith(":*)") for t in tools if "Bash" in t)
    assert "Bash" not in tools and "Bash(*)" not in tools
    prompt = next(s for s in steps() if str(s.get("uses", "")).startswith("anthropics/"))["with"][
        "prompt"
    ]
    assert "--body-file /tmp/claude-review.md" in prompt
    assert "exactly ONE PR comment, even when the review is partial" in prompt
