"""Run the review input step offline: dummy GitHub responses, real local Git history."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/bob-review.yml"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def history(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-b", "main")
    git(remote, "config", "user.name", "Test")
    git(remote, "config", "user.email", "test@example.invalid")
    (remote / "sample.txt").write_text("base\n", encoding="utf-8")
    git(remote, "add", "sample.txt")
    git(remote, "commit", "-m", "base")
    base = git(remote, "rev-parse", "HEAD")
    git(remote, "switch", "-c", "proposal")
    (remote / "sample.txt").write_text("reviewed A\n", encoding="utf-8")
    git(remote, "commit", "-am", "head A")
    head = git(remote, "rev-parse", "HEAD")
    (remote / "sample.txt").write_text("later B\n", encoding="utf-8")
    git(remote, "commit", "-am", "head B")
    later = git(remote, "rev-parse", "HEAD")
    git(remote, "switch", "main")
    git(remote, "update-ref", "refs/heads/proposal", head)
    (remote / "unrelated.txt").write_text("base advanced\n", encoding="utf-8")
    git(remote, "add", "unrelated.txt")
    git(remote, "commit", "-m", "advance base")
    current_base = git(remote, "rev-parse", "HEAD")
    checkout = tmp_path / "checkout"
    git(tmp_path, "clone", str(remote), str(checkout))
    metadata = {
        "title": "Review example",
        "body": "Dummy PR",
        "headRefName": "proposal",
        "baseRefOid": current_base,
        "headRefOid": head,
    }
    (checkout / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (checkout / "later.sha").write_text(later, encoding="utf-8")
    (checkout / "later.diff").write_text(
        git(remote, "diff", f"{base}...{later}") + "\n", encoding="utf-8"
    )
    return checkout, metadata


def gather(checkout: Path, *, github_fails: bool = False) -> subprocess.CompletedProcess[str]:
    shell = (
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Git/bin/bash.exe")
        if os.name == "nt"
        else shutil.which("bash")
    )
    assert shell and Path(shell).is_file(), "Git Bash (Windows) or bash is required"
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["bob-review"]["steps"] if s.get("id") == "gather")
    # Only the external GitHub boundary is faked. Its diff now belongs to a newer
    # head than the metadata, exactly the race the real workflow must withstand.
    stub = """
    gh() {
      if [ "$GITHUB_FAILS" = 1 ]; then return 17; fi
      if [ "$1 $2" = 'pr view' ]; then
        cat metadata.json
        git -C ../remote update-ref refs/heads/proposal "$(cat later.sha)"
      elif [ "$1 $2" = 'pr diff' ]; then cat later.diff;
      else return 18; fi
    }
    """
    stub += f'\npython3() {{ {shlex.quote(Path(sys.executable).as_posix())} "$@"; }}\n'
    return subprocess.run(
        [shell, "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", stub + step["run"]],
        cwd=checkout,
        env={
            **os.environ,
            "PR_NUMBER": "1",
            "REPO": "example/repo",
            "REQUEST": "Review this exact head",
            "GITHUB_FAILS": "1" if github_fails else "0",
            "GIT_ALLOW_PROTOCOL": "file",
        },
        capture_output=True,
        text=True,
        check=False,
    )


def test_review_diff_belongs_to_named_head_when_pr_moves(
    history: tuple[Path, dict[str, str]],
) -> None:
    checkout, metadata = history
    result = gather(checkout)
    assert result.returncode == 0, result.stderr
    captured = json.loads((checkout / ".bob-input/pr.json").read_text())
    assert captured["headRefOid"] == metadata["headRefOid"]
    diff = (checkout / ".bob-input/pr.diff").read_text()
    assert "+reviewed A\n" in diff
    assert "later B" not in diff
    assert "unrelated.txt" not in diff  # PR three-dot semantics, not a two-dot diff.
    assert git(checkout, "rev-parse", "HEAD") == metadata["baseRefOid"]


@pytest.mark.parametrize("bad_head", ["-bad-option", "f" * 40])
def test_unusable_snapshot_fails_before_review(
    history: tuple[Path, dict[str, str]], bad_head: str
) -> None:
    checkout, metadata = history
    metadata["headRefOid"] = bad_head
    (checkout / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    result = gather(checkout)
    assert result.returncode != 0
    assert not (checkout / ".bob-input/pr.diff").exists()


def test_github_failure_stops_gather(history: tuple[Path, dict[str, str]]) -> None:
    checkout, _ = history
    result = gather(checkout, github_fails=True)
    assert result.returncode == 17
    assert not (checkout / ".bob-input/pr.diff").exists()
