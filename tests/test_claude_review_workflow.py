"""The automated review must post a verdict for its head, or fail where a reader sees it."""

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

# Each entry is one read-only command, the one fixed posting command, or a file tool;
# nothing opens a general shell, pushes, or reads the PR thread's other comments.
ALLOWED = [
    "Bash(gh pr comment ${{ github.event.pull_request.number }} --body-file /tmp/claude-review.md)",
    "Bash(gh pr diff:*)",
    "Bash(git log:*)",
    "Bash(git diff:*)",
    "Bash(git show:*)",
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


SNAPSHOT_FILE = "/tmp/checkout-before.txt"


def run_step(
    name: str, cwd: Path, stub: str, env: dict[str, str], snapshot: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run a step's script as GitHub's default run shell does (bash -e, no pipefail),
    with only the GitHub CLI faked as a shell function. ``snapshot`` stands in for the
    workflow's fixed snapshot path, so tests never share a file."""
    script = step(name)["run"]
    if snapshot is not None:
        script = script.replace(SNAPSHOT_FILE, snapshot.as_posix())
    return subprocess.run(
        [bash(), "--noprofile", "--norc", "-e", "-c", stub + "\n" + script],
        cwd=cwd,
        # Git Bash on Windows rewrites arguments such as "origin/main:.claude/x" as
        # paths; the runner's Linux bash does not, so neither do the tests.
        env={**os.environ, "MSYS_NO_PATHCONV": "1", "MSYS2_ARG_CONV_EXCL": "*", **env},
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
    assert (
        "Its second line is `Scope: complete` when you read the whole diff, "
        "otherwise `Scope: partial`"
    ) in prompt
    assert "CHANGES NEEDED may be partial; APPROVE never is." in prompt
    assert "Never modify, create or delete a file in the checkout" in prompt
    assert "Verdict: <APPROVE|CHANGES NEEDED|INCOMPLETE> at <HEAD_SHA in full>" in prompt
    assert "git diff BASE_SHA...HEAD_SHA" in prompt and "origin/main" not in prompt
    # The workflow installs before the snapshot; the reviewer installs nothing.
    assert "The project is installed already, as CI installs it; do not install anything." in (
        prompt
    )
    assert "pip install" not in prompt


def test_no_step_may_fail_without_failing_the_job() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert "continue-on-error" not in workflow["jobs"]["review"]
    assert all("continue-on-error" not in s for s in steps())


def test_no_run_script_interpolates_an_event_value() -> None:
    scripts = [s["run"] for s in steps() if "run" in s]
    assert len(scripts) == 6
    assert all("${{" not in run for run in scripts)


CACHES = {
    "PYTHONPYCACHEPREFIX": "/tmp/pycache",
    "MYPY_CACHE_DIR": "/tmp/mypy-cache",
    "RUFF_CACHE_DIR": "/tmp/ruff-cache",
    "PYTEST_ADDOPTS": "-p no:cacheprovider",
}


def test_tool_caches_live_outside_the_checkout() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert workflow["jobs"]["review"]["env"] == CACHES
    settings = json.loads(step("anthropics/")["with"]["settings"])
    assert settings == {"env": CACHES}


def test_the_checkout_is_snapshotted_after_install_and_checked_after_any_outcome() -> None:
    names = [s.get("name") or s.get("uses") for s in steps()]
    review = next(i for i, n in enumerate(names) if str(n).startswith("anthropics/"))
    install = names.index("Install the project")
    snapshot = names.index("Snapshot the checkout")
    void = names.index("Void a verdict from a modified checkout")
    assert names.index("actions/setup-python@v5") < install < snapshot < review < void
    # Installed exactly as CI's quality job installs it.
    assert step("Install the project")["run"].splitlines() == [
        "python -m pip install --upgrade pip",
        "python -m pip install -r requirements-dev.lock",
        "python -m pip install -e . --no-deps",
    ]
    assert step("Snapshot the checkout")["run"] == (
        "git status --porcelain --ignored=traditional --untracked-files=all > " + SNAPSHOT_FILE
    )
    # A verdict posted before the action failed, or before a same-head re-run cancelled
    # this run, is still voided.
    assert steps()[void]["if"] == "${{ always() }}"


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


IGNORED = "*.egg-info/\n__pycache__/\n.pytest_cache/\n.mypy_cache/\n.ruff_cache/\nbuild/\ndata/\n"


GIT_USER = ["-c", "user.name=T", "-c", "user.email=t@example.invalid"]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def write(repo: Path, name: str, text: str = "changed\n") -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def restore_from_base(repo: Path, *paths: str) -> None:
    """Replay restoreConfigFromBase: delete, check out from origin/<base>, unstage."""
    for path in paths:
        if (repo / path).is_file():
            (repo / path).unlink()
    present = [p for p in paths if p in ("CLAUDE.md", ".claude/settings.json")]
    git(repo, "checkout", "origin/main", "--", *present)
    git(repo, "reset", "-q", "--", *paths)


def checkout(tmp_path: Path, *, pr: str = "", installed: tuple[str, ...] = ()) -> tuple[Path, Path]:
    """The PR's checkout, origin/main as the base, the install output written before
    the snapshot, and the snapshot the workflow takes before the review.

    ``pr`` = "edits" makes the PR edit CLAUDE.md and add CLAUDE.local.md; "deletes"
    makes it delete CLAUDE.md. Either way the action's restore from origin/main is
    replayed after the snapshot, as it happens inside the action step."""
    repo = tmp_path / "checkout"
    write(repo, "src/module.py", "x = 1\n")
    write(repo, ".gitignore", IGNORED)
    write(repo, "CLAUDE.md", "base\n")
    write(repo, ".claude/settings.json", "{}\n")
    git(repo, "init", "-q")
    git(repo, *GIT_USER, "add", ".")
    git(repo, *GIT_USER, "commit", "-q", "-m", "base")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    if pr == "edits":
        write(repo, "CLAUDE.md", "from the PR\n")
        write(repo, "CLAUDE.local.md", "from the PR\n")
    elif pr == "deletes":
        (repo / "CLAUDE.md").unlink()
    if pr:
        git(repo, *GIT_USER, "add", "-A")
        git(repo, *GIT_USER, "commit", "-q", "-m", "pr")
    for name in installed:
        write(repo, name)
    snapshot = tmp_path / "checkout-before.txt"
    taken = run_step("Snapshot the checkout", repo, "", {}, snapshot)
    assert taken.returncode == 0 and snapshot.is_file(), taken.stderr
    if pr:
        restore_from_base(repo, "CLAUDE.md", "CLAUDE.local.md")
        write(repo, ".claude-pr/CLAUDE.md", "from the PR\n")
    return repo, snapshot


POSTER = 'gh() { printf "%s\n" "$*" >> "$GH_LOG"; }'


def void_env(log: Path) -> dict[str, str]:
    return {"GH_LOG": str(log), "PR": "7", "HEAD_SHA": HEAD, "BASE_REF": "main"}


INSTALL_OUTPUT = ("src/pkg.egg-info/PKG-INFO", "build/lib/module.py")


@pytest.mark.parametrize(
    ("installed", "touched"),
    [
        ((), []),
        # The install runs before the snapshot, so its output is part of it.
        (INSTALL_OUTPUT, []),
        # The action's own snapshot of the PR's config.
        ((), [".claude-pr/CLAUDE.md"]),
    ],
)
def test_an_untouched_checkout_keeps_the_verdict(
    tmp_path: Path, installed: tuple[str, ...], touched: list[str]
) -> None:
    repo, snapshot = checkout(tmp_path, installed=installed)
    for name in touched:
        write(repo, name)
    log = tmp_path / "gh.log"
    result = run_step(VOID, repo, POSTER, void_env(log), snapshot)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not log.exists()


@pytest.mark.parametrize("pr", ["edits", "deletes"])
def test_the_actions_own_restore_from_the_base_keeps_the_verdict(tmp_path: Path, pr: str) -> None:
    # "deletes": the PR removes CLAUDE.md, the action restores the base copy and unstages
    # it, so the index still records the deletion; only the files on disk count.
    repo, snapshot = checkout(tmp_path, pr=pr)
    log = tmp_path / "gh.log"
    result = run_step(VOID, repo, POSTER, void_env(log), snapshot)
    assert result.returncode == 0, result.stdout + result.stderr
    assert not log.exists()


@pytest.mark.parametrize(
    "name",
    [
        "src/module.py",
        "conftest.py",
        "config/default.toml",
        "docs/rules.md",
        ".github/x.yml",
        "data/planted.csv",  # ignored by .gitignore, still a write the tests could read
        # Nothing is exempt: a cache or build file written after the snapshot counts too.
        "build/generated.json",
        "src/pkg.egg-info/PKG-INFO",
        "src/__pycache__/module.cpython-312.pyc",
        ".pytest_cache/v/cache/nodeids",
        ".mypy_cache/3.12/module.data.json",
        ".ruff_cache/0.6.0/123",
        # Paths the action restores: a reviewer write there differs from origin/main.
        "CLAUDE.md",
        ".claude/settings.local.json",
        ".mcp.json",
    ],
)
def test_a_changed_checkout_voids_the_verdict_visibly(tmp_path: Path, name: str) -> None:
    repo, snapshot = checkout(tmp_path)
    write(repo, name)
    log = tmp_path / "gh.log"
    result = run_step(VOID, repo, POSTER, void_env(log), snapshot)
    assert result.returncode == 1
    posted = log.read_text(encoding="utf-8")
    assert posted.startswith("pr comment 7 --body Automated review VOID at " + HEAD)
    assert name in posted


def test_deleting_a_restored_file_voids_the_verdict(tmp_path: Path) -> None:
    repo, snapshot = checkout(tmp_path)
    (repo / ".claude" / "settings.json").unlink()
    log = tmp_path / "gh.log"
    result = run_step(VOID, repo, POSTER, void_env(log), snapshot)
    assert result.returncode == 1
    assert "missing .claude/settings.json" in log.read_text(encoding="utf-8")


def test_an_unknown_base_fails_the_check(tmp_path: Path) -> None:
    repo, snapshot = checkout(tmp_path)
    env = {**void_env(tmp_path / "gh.log"), "BASE_REF": "no-such-branch"}
    result = run_step(VOID, repo, POSTER, env, snapshot)
    assert result.returncode == 1
    assert "origin/no-such-branch is unknown" in result.stdout


def test_without_a_snapshot_the_verdict_is_not_trusted(tmp_path: Path) -> None:
    repo, snapshot = checkout(tmp_path)
    snapshot.unlink()
    log = tmp_path / "gh.log"
    result = run_step(VOID, repo, POSTER, void_env(log), snapshot)
    assert result.returncode == 1
    assert "no snapshot of the checkout was taken" in result.stdout


def test_a_void_notice_pings_nobody_and_a_failed_post_still_fails(tmp_path: Path) -> None:
    repo, snapshot = checkout(tmp_path)
    write(repo, "notes/@someone.md")
    log = tmp_path / "gh.log"
    env = void_env(log)
    result = run_step(VOID, repo, POSTER, env, snapshot)
    assert result.returncode == 1
    assert "@" not in log.read_text(encoding="utf-8")
    failing = "gh() { return 1; }"
    assert run_step(VOID, repo, failing, env, snapshot).returncode != 0
