"""The automated review must post a verdict for its head, or fail where a reader sees it."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/claude-review.yml"

# Each entry is one read-only command, the one fixed posting command, or a file tool;
# nothing opens a general shell, pushes, or reads the PR thread's other comments.
ALLOWED = [
    "Bash(gh pr comment ${{ github.event.pull_request.number }} --body-file /tmp/claude-review.md)",
    "Bash(gh pr diff:*)",
    "Bash(git log:*)",
    "Bash(git diff:*)",
    "Bash(git show:*)",
    "Bash(git merge-base:*)",
    "Bash(pip install:*)",
    "Bash(pytest:*)",
    "Bash(ruff:*)",
    "Bash(mypy:*)",
    "Read",
    "Glob",
    "Grep",
    "Write",
]


def steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return list(workflow["jobs"]["review"]["steps"])


def step(name: str) -> dict[str, Any]:
    return next(s for s in steps() if (s.get("name") or s.get("uses", "")).startswith(name))


def test_the_allowed_tools_are_exactly_the_reviewed_list() -> None:
    found = re.fullmatch(r'--allowedTools "([^"]*)"', step("anthropics/")["with"]["claude_args"])
    assert found is not None
    assert found.group(1).split(",") == ALLOWED


def test_only_this_bots_earlier_reviews_reach_the_reviewer() -> None:
    collect = step("Collect this bot's earlier reviews")
    assert 'select(.user.login == "claude[bot]")' in collect["run"]
    assert "> /tmp/previous-reviews.md" in collect["run"]
    assert "${{" not in collect["run"]
    prompt = step("anthropics/")["with"]["prompt"]
    assert "nothing else from the PR thread is input to this review" in prompt
    assert "gh pr view" not in prompt


def test_a_partial_reading_never_approves() -> None:
    prompt = step("anthropics/")["with"]["prompt"]
    assert "never answer APPROVE for a partial reading" in prompt
    assert "APPROVE only when you read every changed line in your scope" in prompt
    assert "Verdict: <APPROVE|CHANGES NEEDED|INCOMPLETE> at <HEAD_SHA in full>" in prompt
    assert "git diff BASE_SHA...HEAD_SHA" in prompt and "origin/main" not in prompt


def test_a_review_without_a_verdict_for_this_head_fails_the_job() -> None:
    names = [s.get("name") or s.get("uses") for s in steps()]
    review = next(i for i, n in enumerate(names) if str(n).startswith("anthropics/"))
    check = names.index("Require the posted verdict for this head")
    assert names.index("Record the start time") < review < check
    gate = steps()[check]
    assert "if" not in gate  # runs only after a successful review step, never skipped silently
    assert gate["env"]["SINCE"] == "${{ steps.start.outputs.time }}"
    assert gate["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert gate["env"]["GH_TOKEN"] == "${{ github.token }}"
    run = gate["run"]
    # Event values reach the shell through env only, never by interpolation into the script.
    assert "${{" not in run
    # The comment must be this bot's, created during the run, with a verdict line naming this head.
    assert '.user.login == "claude[bot]"' in run and ".created_at >= env.SINCE" in run
    assert 'test("^Verdict: (APPROVE|CHANGES NEEDED|INCOMPLETE) at " + env.HEAD_SHA)' in run
    assert "--paginate" in run
    # A malformed start time or an empty count fails closed.
    assert '*) echo "::error::no valid start time recorded"; exit 1 ;;' in run
    assert "''|*[!0-9]*) posted=0" in run and "exit 1" in run
