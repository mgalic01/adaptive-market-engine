"""Run bob-task.yml's revision steps offline against a real local Git history.

A queued task run used to check out ``main`` when its job started, so a commit merged
while it waited in the ``bob-task`` concurrency queue could change what Bob ran (Codex's
review of PR #193). Each trigger now fixes one commit, the run revision, and the worker
checks out exactly that commit. These tests run the workflow's own step scripts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/bob-task.yml"
TASK = "docs/tasks/2026-10-07-bob-example.md"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def workflow() -> dict:
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def step(job: str, step_id: str) -> dict:
    return next(s for s in workflow()["jobs"][job]["steps"] if s.get("id") == step_id)


def run_step(script: str, cwd: Path, env: dict[str, str]) -> tuple[int, dict[str, str], str]:
    """Run a step's script with GitHub's default shell for `run`: bash -e, no pipefail."""
    shell = (
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    assert shell and Path(shell).is_file(), "Git Bash (Windows) or bash is required"
    output = cwd / "github-output.txt"
    output.write_text("", encoding="utf-8")
    script_file = cwd / "step.sh"
    script_file.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [shell, "--noprofile", "--norc", "-e", str(script_file)],
        cwd=cwd,
        env={**os.environ, "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(cwd), **env},
        capture_output=True,
        text=True,
        check=False,
    )
    outputs = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines() if line
    )
    return result.returncode, outputs, result.stdout + result.stderr


@pytest.fixture(scope="module")
def remote(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, str]]:
    """main: base, merge of a task branch, then a later edit of the task; plus a stray branch."""
    root = tmp_path_factory.mktemp("bob-task") / "remote"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "base")
    revisions = {"base": git(root, "rev-parse", "HEAD")}
    git(root, "switch", "-c", "task")
    (root / "docs/tasks").mkdir(parents=True)
    (root / TASK).write_text("draft\n", encoding="utf-8")
    git(root, "add", TASK)
    git(root, "commit", "-m", "task draft")
    revisions["inside_branch"] = git(root, "rev-parse", "HEAD")
    (root / TASK).write_text("reviewed\n", encoding="utf-8")
    git(root, "commit", "-am", "task reviewed")
    git(root, "switch", "main")
    git(root, "merge", "--no-ff", "-m", "merge the reviewed task", "task")
    revisions["merge"] = git(root, "rev-parse", "HEAD")
    (root / TASK).write_text("edited after the merge\n", encoding="utf-8")
    git(root, "commit", "-am", "later edit")
    revisions["later"] = git(root, "rev-parse", "HEAD")
    git(root, "switch", "-c", "stray", revisions["base"])
    (root / "docs/tasks").mkdir(parents=True, exist_ok=True)
    (root / TASK).write_text("never reviewed\n", encoding="utf-8")
    git(root, "add", TASK)
    git(root, "commit", "-m", "stray task")
    revisions["stray"] = git(root, "rev-parse", "HEAD")
    git(root, "switch", "main")
    return root, revisions


@pytest.fixture
def checkout(remote: tuple[Path, dict[str, str]], tmp_path: Path) -> Path:
    """A clone with every branch as origin/*, like actions/checkout with fetch-depth 0."""
    root, _ = remote
    clone = tmp_path / "checkout"
    git(tmp_path, "clone", "--no-checkout", str(root), str(clone))
    return clone


# --- resolve: one revision per trigger ----------------------------------------------


def resolve(cwd: Path, **env: str) -> tuple[int, dict[str, str], str]:
    base = {"EVENT": "", "BODY": "", "INPUT_TASK": "", "INPUT_REVISION": "", "BEFORE": ""}
    base["AFTER"] = ""
    return run_step(step("resolve", "list")["run"], cwd, {**base, **env})


def test_a_push_runs_at_the_pushed_commit(
    remote: tuple[Path, dict[str, str]], checkout: Path
) -> None:
    _, rev = remote
    code, out, log = resolve(checkout, EVENT="push", BEFORE=rev["base"], AFTER=rev["merge"])
    assert code == 0, log
    assert out["tasks"] == f'["{TASK}"]'
    assert out["revision"] == rev["merge"]


def test_a_push_that_adds_no_task_runs_nothing(
    remote: tuple[Path, dict[str, str]], checkout: Path
) -> None:
    _, rev = remote
    code, out, log = resolve(checkout, EVENT="push", BEFORE=rev["merge"], AFTER=rev["later"])
    assert code == 0, log
    assert out["tasks"] == "[]"


def test_a_comment_runs_at_the_commit_it_names(tmp_path: Path) -> None:
    sha = "a" * 40
    body = f"Rerun after the diagnosis above.\n/bob-run {TASK} {sha}\nThanks"
    code, out, log = resolve(tmp_path, EVENT="issue_comment", BODY=body)
    assert code == 0, log
    assert out["tasks"] == f'["{TASK}"]'
    assert out["revision"] == sha


@pytest.mark.parametrize(
    "body",
    [
        f"/bob-run {TASK}",  # no revision: nothing runs, rather than main's current head
        f"/bob-run {TASK} abc1234",  # short SHA
        f"/bob-run {TASK} {'b' * 64}",  # a SHA-256, not a commit: never its first 40
        f"/bob-run {TASK} {'C' * 40}",  # upper case is not how Git prints a commit
        f"/bob-run {TASK}\n{'d' * 40}",  # revision on another line
        f"`/bob-run {TASK} {'e' * 40}`",  # quoted, as before
    ],
)
def test_a_comment_without_one_full_revision_runs_nothing(tmp_path: Path, body: str) -> None:
    code, out, log = resolve(tmp_path, EVENT="issue_comment", BODY=body)
    assert code == 0, log
    assert out["tasks"] == "[]"
    assert out["revision"] == ""


def test_run_workflow_runs_at_the_commit_it_names(tmp_path: Path) -> None:
    sha = "f" * 40
    code, out, log = resolve(
        tmp_path, EVENT="workflow_dispatch", INPUT_TASK=TASK, INPUT_REVISION=sha
    )
    assert code == 0, log
    assert out == {"tasks": f'["{TASK}"]', "revision": sha}


@pytest.mark.parametrize("revision", ["", "main", "abc1234", "a" * 39, f"{'a' * 40}\ntasks=[]"])
def test_run_workflow_without_a_full_revision_fails(tmp_path: Path, revision: str) -> None:
    code, out, _ = resolve(
        tmp_path, EVENT="workflow_dispatch", INPUT_TASK=TASK, INPUT_REVISION=revision
    )
    assert code != 0
    assert "tasks" not in out


# --- the worker: exactly the recorded commit, which main has been at -----------------


def gate(cwd: Path, revision: str, task: str = TASK) -> tuple[int, dict[str, str], str]:
    return run_step(step("bob-task", "gate")["run"], cwd, {"TASK_IN": task, "REVISION": revision})


def test_the_gate_passes_the_revision_on(tmp_path: Path) -> None:
    code, out, log = gate(tmp_path, "a" * 40)
    assert code == 0, log
    assert out["ok"] == "true"
    assert out["revision"] == "a" * 40


@pytest.mark.parametrize("revision", ["", "main", "a" * 39])
def test_the_gate_never_lets_checkout_fall_back_to_main(tmp_path: Path, revision: str) -> None:
    code, out, _ = gate(tmp_path, revision)
    assert code != 0
    assert "ok" not in out


def test_the_worker_checks_out_the_gate_revision_and_never_main() -> None:
    jobs = workflow()["jobs"]
    assert jobs["resolve"]["outputs"]["revision"] == "${{ steps.list.outputs.revision }}"
    assert step("resolve", "list")["env"]["AFTER"] == "${{ github.sha }}"
    assert step("bob-task", "gate")["env"]["REVISION"] == "${{ needs.resolve.outputs.revision }}"
    checkouts = [
        s for s in jobs["bob-task"]["steps"] if s.get("uses", "").startswith("actions/checkout@")
    ]
    assert len(checkouts) == 1
    assert checkouts[0]["with"]["ref"] == "${{ steps.gate.outputs.revision }}"
    assert checkouts[0]["with"]["persist-credentials"] is False
    names = [s.get("id") or s.get("uses") or s.get("name") for s in jobs["bob-task"]["steps"]]
    # The revision is verified after the checkout and before Bob starts.
    assert names.index("exists") == names.index(checkouts[0]["uses"]) + 1
    assert names.index("exists") < names.index("bob")


def verify(checkout: Path, head: str, revision: str) -> tuple[int, str]:
    git(checkout, "checkout", "--quiet", "--detach", head)
    code, _, log = run_step(
        step("bob-task", "exists")["run"], checkout, {"TASK": TASK, "REVISION": revision}
    )
    return code, log


def test_a_merge_commit_main_has_been_at_is_run_as_it_was(
    remote: tuple[Path, dict[str, str]], checkout: Path
) -> None:
    _, rev = remote
    code, log = verify(checkout, rev["merge"], rev["merge"])
    assert code == 0, log
    # The later edit on main is not what this run reads.
    assert (checkout / TASK).read_text(encoding="utf-8") == "reviewed\n"


@pytest.mark.parametrize(
    ("head", "revision", "message"),
    [
        # An ancestor of main, but main was never at it: an unreviewed intermediate state.
        ("inside_branch", "inside_branch", "is not a commit main has been at"),
        ("stray", "stray", "is not a commit main has been at"),
        ("later", "merge", "not the run revision"),
        ("base", "base", f"{TASK} is not in"),
    ],
)
def test_the_worker_stops_before_bob_on(
    remote: tuple[Path, dict[str, str]], checkout: Path, head: str, revision: str, message: str
) -> None:
    _, rev = remote
    code, log = verify(checkout, rev[head], rev[revision])
    assert code != 0
    assert message in log
