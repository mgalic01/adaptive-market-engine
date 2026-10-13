"""The automated review is a reading that posts a verdict for its run, or fails visibly."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/claude-review.yml"

# The reviewer may run one command (posting its comment body), read the prepared input
# and write that one body file; --permission-mode dontAsk refuses everything else.
CLAUDE_ARGS = (
    "--setting-sources user --permission-mode dontAsk --add-dir /tmp/pr --allowedTools "
    '"Bash(gh pr comment ${{ github.event.pull_request.number }} '
    '--body-file /tmp/claude-review.md),Read(//tmp/pr/**),Edit(//tmp/claude-review.md)"'
)


def workflow() -> dict[str, Any]:
    return dict(yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))


def steps() -> list[dict[str, Any]]:
    return list(workflow()["jobs"]["review"]["steps"])


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
        # Git Bash on Windows rewrites some arguments as paths; the runner's bash does not.
        env={**os.environ, "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*", **env},
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_reviewer_can_post_read_and_write_only_its_own_comment() -> None:
    assert step("anthropics/")["with"]["claude_args"] == CLAUDE_ARGS


def test_no_hook_setting_or_server_from_the_checkout_reaches_the_reviewer() -> None:
    # The base's .claude/settings.json runs scripts/claims.py from the checkout (the PR's
    # copy) before every shell command: user settings only, every hook off, and the
    # file removed so that hook exits at once whatever settings apply.
    assert json.loads(step("anthropics/")["with"]["settings"]) == {
        "disableAllHooks": True,
        "enableAllProjectMcpServers": False,
    }
    assert CLAUDE_ARGS.startswith("--setting-sources user ")
    assert "rm -f scripts/claims.py" in step("Prepare the review input")["run"]


def test_the_review_job_runs_no_code_from_the_pr() -> None:
    names = [s.get("name") or s.get("uses") for s in steps()]
    assert names == [
        "actions/checkout@v4",
        "Record the start time",
        "Prepare the review input",
        "anthropics/claude-code-action@v1",
        "Require the posted verdict for this run",
    ]
    scripts = "\n".join(s["run"] for s in steps() if "run" in s)
    for runs_pr_code in ("pip ", "pytest", "python", "ruff", "mypy", "make "):
        assert runs_pr_code not in scripts
    prompt = step("anthropics/")["with"]["prompt"]
    assert "You cannot run commands other than the one posting command below" in prompt
    assert "CI's quality job runs ruff, mypy and the whole test suite on a clean checkout." in (
        prompt
    )


def test_only_this_bots_earlier_reviews_reach_the_reviewer() -> None:
    prepare = step("Prepare the review input")["run"]
    assert '--jq \'.[] | select(.user.login == "claude[bot]") |' in prepare
    assert "> /tmp/pr/previous-reviews.md" in prepare
    action = step("anthropics/")["with"]
    # The action's own PR context is filtered too; its default includes every actor.
    assert action["include_comments_by_actor"] == "claude[bot]"
    assert "Nothing else from the PR thread is input to this review." in action["prompt"]


def test_the_diff_comes_from_the_event_shas_prepared_before_the_reviewer_starts() -> None:
    prepare = step("Prepare the review input")
    assert prepare["env"]["BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert prepare["env"]["HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert 'git diff "$BASE_SHA...$HEAD_SHA" > /tmp/pr/diff.patch' in prepare["run"]
    assert "origin/main" not in prepare["run"]
    assert (
        "/tmp/pr/diff.patch: the whole diff. Read all of it"
        in step("anthropics/")["with"]["prompt"]
    )


def test_a_partial_reading_never_approves() -> None:
    prompt = step("anthropics/")["with"]["prompt"]
    assert "never answer APPROVE for a partial reading" in prompt
    assert "APPROVE only when you read every changed line of the whole diff" in prompt
    # No scoped approval (docs/AGENT_HANDOFF.md: any change to the contribution means a
    # full review).
    assert "Your scope is always the whole diff BASE_SHA...HEAD_SHA" in prompt
    assert "incremental" not in prompt.lower()
    assert "CHANGES NEEDED may be partial; APPROVE never is." in prompt
    assert (
        "Verdict: <APPROVE|CHANGES NEEDED|INCOMPLETE> at <HEAD_SHA in full> run <RUN_TAG>"
    ) in prompt
    assert "RUN_TAG (this run): ${{ github.run_id }}-${{ github.run_attempt }}" in prompt


def test_no_step_may_fail_without_failing_the_job() -> None:
    assert "continue-on-error" not in workflow()["jobs"]["review"]
    assert all("continue-on-error" not in s for s in steps())


def test_no_run_script_interpolates_an_event_value() -> None:
    scripts = [s["run"] for s in steps() if "run" in s]
    assert len(scripts) == 3
    assert all("${{" not in run for run in scripts)


GATE = "Require the posted verdict for this run"
HEAD = "a" * 40


def test_the_gate_requires_this_runs_verdict_line() -> None:
    gate = step(GATE)
    assert "if" not in gate  # runs only after a successful review step, never skipped silently
    assert gate["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPO": "${{ github.repository }}",
        "PR": "${{ github.event.pull_request.number }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
        "RUN_TAG": "${{ github.run_id }}-${{ github.run_attempt }}",
        "SINCE": "${{ steps.start.outputs.time }}",
    }
    run = gate["run"]
    assert "\nset -o pipefail\n" in run and "--paginate" in run
    # This bot's comment, created during the run, whose first line names this head and run.
    assert '.user.login == "claude[bot]"' in run and ".created_at >= env.SINCE" in run
    # \A and \z anchor at the start and end of the whole body in every jq regex engine;
    # ^ and $ would match at any line start in jq's Oniguruma.
    assert (
        'test("\\\\AVerdict: (APPROVE|CHANGES NEEDED|INCOMPLETE) at " + env.HEAD_SHA + " run " '
        '+ env.RUN_TAG + "\\\\r?(\\\\n|\\\\z)")'
    ) in run
    assert (
        'if [ "$posted" -lt 1 ]; then\n'
        '  echo "::error::the review finished without posting a verdict for $HEAD_SHA in run '
        '$RUN_TAG"\n'
        "  exit 1\nfi"
    ) in run


@pytest.mark.parametrize(
    ("answer", "since", "run_tag", "passes"),
    [
        ("1001\n", "2026-10-13T20:00:00Z", "38500000000-1", True),  # one matching verdict
        ("1001\n1002\n", "2026-10-13T20:00:00Z", "38500000000-2", True),
        ("", "2026-10-13T20:00:00Z", "38500000000-1", False),  # no verdict for this run
        ("FAIL", "2026-10-13T20:00:00Z", "38500000000-1", False),  # the API call fails
        ("1001\n", "", "38500000000-1", False),  # no start time recorded
        ("1001\n", "yesterday", "38500000000-1", False),  # a malformed start time
        ("1001\n", "2026-10-13T20:00:00Z", "", False),  # no run tag
    ],
)
def test_the_gate_script_fails_closed(
    tmp_path: Path, answer: str, since: str, run_tag: str, passes: bool
) -> None:
    # The fake gh prints the ids the real filter would have kept, or fails like an API
    # error; the jq filter itself is pinned above and runs inside the real gh.
    stub = (
        'gh() { if [ "$ANSWER" = FAIL ]; then echo "HTTP 502" >&2; return 1; fi; '
        'printf "%s" "$ANSWER"; }'
    )
    env = {
        "ANSWER": answer,
        "SINCE": since,
        "RUN_TAG": run_tag,
        "HEAD_SHA": HEAD,
        "PR": "7",
        "REPO": "o/r",
    }
    result = run_step(GATE, tmp_path, stub, env)
    assert (result.returncode == 0) is passes, result.stdout + result.stderr
    if answer == "FAIL":
        # pipefail: the failed API call stops the step before any count is taken.
        assert "HTTP 502" in result.stderr
        assert "without posting a verdict" not in result.stdout


def test_the_prepare_step_writes_the_whole_diff_from_the_event_shas(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    user = ["-c", "user.name=T", "-c", "user.email=t@example.invalid"]

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    (repo / "a.txt").write_text("base\n", encoding="utf-8")
    git("add", ".")
    git(*user, "commit", "-q", "-m", "base")
    base = git("rev-parse", "HEAD")
    (repo / "a.txt").write_text("head\n", encoding="utf-8")
    git(*user, "commit", "-q", "-am", "change a")
    head = git("rev-parse", "HEAD")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "claims.py").write_text("print('PR code')\n", encoding="utf-8")
    out = tmp_path / "pr"
    body = tmp_path / "claude-review.md"
    script_env = {"BASE_SHA": base, "HEAD_SHA": head, "PR": "7", "REPO": "o/r"}
    stub = 'gh() { echo "--- posted 2026-10-13T20:00:00Z"; }'
    prepare = (
        step("Prepare the review input")["run"]
        .replace("/tmp/claude-review.md", body.as_posix())
        .replace("/tmp/pr", out.as_posix())
    )
    result = subprocess.run(
        [bash(), "--noprofile", "--norc", "-e", "-c", stub + "\n" + prepare],
        cwd=repo,
        env={**os.environ, "MSYS_NO_PATHCONV": "1", **script_env},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    diff = (out / "diff.patch").read_text(encoding="utf-8")
    assert "-base" in diff and "+head" in diff
    assert f"{head} change a" in (out / "log.txt").read_text(encoding="utf-8")
    assert "a.txt" in (out / "stat.txt").read_text(encoding="utf-8")
    assert (out / "previous-reviews.md").read_text(encoding="utf-8").startswith("--- posted")
    # The hook's target is gone, and the body file exists as a placeholder that can never
    # pass the verdict check.
    assert not (repo / "scripts" / "claims.py").exists()
    assert body.read_text(encoding="utf-8") == "(no review written)\n"


def gate_filter() -> str:
    found = re.search(r"--jq '([^']*)'", step(GATE)["run"])
    assert found is not None
    return found.group(1)


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is not installed")
def test_the_real_verdict_filter_keeps_only_this_runs_first_line() -> None:
    since, tag, other = "2026-10-13T20:00:00Z", "77-1", "b" * 40

    def comment(n: int, body: str, *, login: str = "claude[bot]", at: str = since) -> object:
        return {"id": n, "user": {"login": login}, "created_at": at, "body": body}

    line = f"Verdict: APPROVE at {HEAD} run {tag}"
    comments = [
        comment(1, line + "\nScope: complete"),
        comment(2, f"Verdict: CHANGES NEEDED at {HEAD} run {tag}\r\nScope: partial"),
        comment(3, f"Verdict: INCOMPLETE at {HEAD} run {tag}"),  # the whole body
        comment(4, "A preface\n" + line),  # not the first line
        comment(5, f"Verdict: APPROVE at {HEAD} run 77-2\n"),  # another run
        comment(6, f"Verdict: APPROVE at {HEAD} run {tag}2\n"),  # a longer run tag
        comment(7, f"Verdict: APPROVE at {other} run {tag}\n"),  # another head
        comment(8, line + "\n", login="github-actions[bot]"),  # another author
        comment(9, line + "\n", at="2026-10-13T19:59:59Z"),  # before this run started
        comment(10, f"**Verdict: APPROVE** at {HEAD} run {tag}\n"),  # not the exact line
    ]
    result = subprocess.run(
        ["jq", "-r", gate_filter()],
        input=json.dumps(comments),
        env={**os.environ, "SINCE": since, "HEAD_SHA": HEAD, "RUN_TAG": tag},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.split() == ["1", "2", "3"]
