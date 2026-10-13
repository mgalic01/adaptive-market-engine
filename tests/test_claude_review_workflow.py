"""The automated review must post a verdict for its head, or fail where a reader sees it."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
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


def bash() -> str:
    shell = (
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    assert shell and Path(shell).is_file(), "Git Bash (Windows) or bash is required"
    return shell


def run_step(
    name: str, cwd: Path, stub: str, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    """Run a step's script as GitHub's default run shell does (bash -e, no pipefail),
    with only the GitHub CLI faked as a shell function."""
    return subprocess.run(
        [bash(), "--noprofile", "--norc", "-e", "-c", stub + "\n" + step(name)["run"]],
        cwd=cwd,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_allowed_tools_are_exactly_the_reviewed_list() -> None:
    found = re.fullmatch(r'--allowedTools "([^"]*)"', step("anthropics/")["with"]["claude_args"])
    assert found is not None
    assert found.group(1).split(",") == ALLOWED


def test_only_this_bots_earlier_reviews_reach_the_reviewer() -> None:
    collect = step("Collect this bot's earlier reviews")
    # claude[bot] reviews, plus this workflow's own VOID notices; no other author.
    assert (
        'select(.user.login == "claude[bot]" or (.user.login == "github-actions[bot]" and '
        '(.body | startswith("Automated review VOID at "))))'
    ) in collect["run"]
    assert "> /tmp/previous-reviews.md" in collect["run"]
    assert "${{" not in collect["run"]
    action = step("anthropics/")["with"]
    # The action's own PR context is filtered too; its default includes every actor.
    assert action["include_comments_by_actor"] == "claude[bot]"
    prompt = action["prompt"]
    assert "Nothing else from the PR thread is input to this review" in prompt
    assert "gh pr view" not in prompt


def test_a_partial_reading_never_approves() -> None:
    prompt = step("anthropics/")["with"]["prompt"]
    assert "never answer APPROVE for a partial reading" in prompt
    assert "APPROVE only when you read every changed line of the whole diff" in prompt
    # No scoped approval: an earlier verdict never stands in for reading part of the diff
    # (docs/AGENT_HANDOFF.md: any change to the contribution means a full review).
    assert "Your scope is always the whole diff BASE_SHA...HEAD_SHA" in prompt
    assert "incremental" not in prompt.lower()
    assert "Its second line is `Scope: complete` or, for INCOMPLETE, `Scope: partial`" in prompt
    assert "Never modify, create or delete a file in the checkout" in prompt
    assert "Verdict: <APPROVE|CHANGES NEEDED|INCOMPLETE> at <HEAD_SHA in full>" in prompt
    assert "git diff BASE_SHA...HEAD_SHA" in prompt and "origin/main" not in prompt


def test_no_step_may_fail_without_failing_the_job() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "continue-on-error" not in workflow["jobs"]["review"]
    assert all("continue-on-error" not in s for s in steps())


def test_no_run_script_interpolates_an_event_value() -> None:
    scripts = [s["run"] for s in steps() if "run" in s]
    assert len(scripts) == 4
    assert all("${{" not in run for run in scripts)


def test_a_review_without_a_verdict_for_this_head_fails_the_job() -> None:
    names = [s.get("name") or s.get("uses") for s in steps()]
    review = next(i for i, n in enumerate(names) if str(n).startswith("anthropics/"))
    void = names.index("Void a verdict from a modified checkout")
    check = names.index("Require the posted verdict for this head")
    assert names.index("Record the start time") < review < void < check
    gate = steps()[check]
    assert "if" not in gate  # runs only after a successful review step, never skipped silently
    assert gate["run"].startswith("# The default run shell is bash -e without pipefail")
    assert "\nset -o pipefail\n" in gate["run"]
    assert (
        'if [ "$posted" -lt 1 ]; then\n'
        '  echo "::error::the review finished without posting a verdict for $HEAD_SHA"\n'
        "  exit 1\nfi"
    ) in gate["run"]
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


GATE = "Require the posted verdict for this head"
HEAD = "a" * 40


@pytest.mark.parametrize(
    ("answer", "since", "passes"),
    [
        ("1001\n", "2026-10-13T20:00:00Z", True),  # one matching verdict
        ("1001\n1002\n", "2026-10-13T20:00:00Z", True),
        ("", "2026-10-13T20:00:00Z", False),  # no verdict for this head
        ("FAIL", "2026-10-13T20:00:00Z", False),  # the API call fails
        ("1001\n", "", False),  # no start time recorded
        ("1001\n", "yesterday", False),  # a malformed start time
    ],
)
def test_the_gate_script_fails_closed(
    tmp_path: Path, answer: str, since: str, passes: bool
) -> None:
    # The fake gh prints the ids the real filter would have kept, or fails like an
    # API error; the jq filter itself is pinned above and runs inside the real gh.
    stub = (
        'gh() { if [ "$ANSWER" = FAIL ]; then echo "HTTP 502" >&2; return 1; fi; '
        'printf "%s" "$ANSWER"; }'
    )
    env = {"ANSWER": answer, "SINCE": since, "HEAD_SHA": HEAD, "PR": "7", "REPO": "o/r"}
    result = run_step(GATE, tmp_path, stub, env)
    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    if not passes and answer == "FAIL":
        # pipefail: the failed API call stops the step before any count is taken.
        assert "HTTP 502" in result.stderr
        assert "without posting a verdict" not in result.stdout


VOID = "Void a verdict from a modified checkout"


def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "module.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.egg-info/\n__pycache__/\n", encoding="utf-8")
    for args in (
        ["init", "-q"],
        ["-c", "user.name=T", "-c", "user.email=t@example.invalid", "add", "."],
        ["-c", "user.name=T", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "c"],
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


POSTER = 'gh() { printf "%s\n" "$*" >> "$GH_LOG"; }'


def write(repo: Path, name: str, text: str = "changed\n") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "touched",
    [
        [],
        ["src/pkg.egg-info/PKG-INFO"],  # pip install -e output, ignored
        # What the action itself restores from the base, or snapshots, before the review.
        ["CLAUDE.md", ".claude/settings.json", ".mcp.json", ".claude-pr/CLAUDE.md"],
    ],
)
def test_an_untouched_checkout_keeps_the_verdict(tmp_path: Path, touched: list[str]) -> None:
    repo = checkout(tmp_path)
    for name in touched:
        write(repo, name)
    log = tmp_path / "gh.log"
    env = {"GH_LOG": str(log), "PR": "7", "HEAD_SHA": HEAD}
    result = run_step(VOID, repo, POSTER, env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not log.exists()


@pytest.mark.parametrize(
    "name",
    ["src/module.py", "conftest.py", "config/default.toml", "docs/rules.md", ".github/x.yml"],
)
def test_a_changed_checkout_voids_the_verdict_visibly(tmp_path: Path, name: str) -> None:
    repo = checkout(tmp_path)
    write(repo, name)
    log = tmp_path / "gh.log"
    env = {"GH_LOG": str(log), "PR": "7", "HEAD_SHA": HEAD}
    result = run_step(VOID, repo, POSTER, env)
    assert result.returncode == 1
    posted = log.read_text(encoding="utf-8")
    assert posted.startswith("pr comment 7 --body Automated review VOID at " + HEAD)
    assert name in posted


def test_a_void_notice_pings_nobody_and_a_failed_post_still_fails(tmp_path: Path) -> None:
    repo = checkout(tmp_path)
    write(repo, "notes/@someone.md")
    log = tmp_path / "gh.log"
    env = {"GH_LOG": str(log), "PR": "7", "HEAD_SHA": HEAD}
    result = run_step(VOID, repo, POSTER, env)
    assert result.returncode == 1
    assert "@" not in log.read_text(encoding="utf-8")
    failing = "gh() { return 1; }"
    assert run_step(VOID, repo, failing, env).returncode != 0
