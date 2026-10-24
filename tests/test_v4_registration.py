"""V4's registration, job gate and dispatch check (``scripts/v4_registration.py``).

Synthetic only, and the network is blocked for every test: the autouse fixture, as
``tests/test_v4_cell_cli.py`` does, and a module-scoped block that holds while the module's
fixtures build their worlds. GitHub is a fake opener (``FakeGitHub``), as in
``tests/test_v31_driver_cli.py``, whose gate and dispatch-check tests these follow.

The worlds are tiny git repositories under pytest's temporary folders. ``build_rehearsal_repo``
builds them from a tiny checkout (a few tracked files, one untracked, and this checkout's trial
register), so ``trial_register.check_ready``, which reads every code blob twice, stays fast; one
test builds the world from this checkout itself, as the workflow's rehearsal does. Every git call
passes its identity with ``-c`` and writes no config; nothing touches this repository's refs.
"""

import hashlib
import io
import json
import re
import shutil
import socket
import subprocess
import sys
import urllib.error
from http.client import HTTPMessage
from pathlib import Path

import pytest

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine.arms import all_cells
from crypto_grid_bot.v4.verdict import report

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_registration as reg  # noqa: E402
from trial_register import append_event  # noqa: E402

GITHUB_VARIABLES = ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")
GIT = (
    "-c",
    "user.name=v4-rehearsal",
    "-c",
    "user.email=rehearsal@invalid",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
)


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def _refuse(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("the network is blocked in tests")


_SOCKET_CALLS = [
    (socket, "getaddrinfo"),
    (socket, "create_connection"),
    (socket.socket, "connect"),
    (socket.socket, "connect_ex"),
]


@pytest.fixture(scope="module", autouse=True)
def module_network_blocked():
    """The network is blocked while the module-scoped fixtures build their worlds."""
    with pytest.MonkeyPatch.context() as patch:
        for owner, name in _SOCKET_CALLS:
            patch.setattr(owner, name, _refuse)
        yield


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test may resolve a name or open a socket. Nor does it hold the runner's variables for
    GitHub's API or the job's start: a test of the check sets its own."""
    for owner, name in _SOCKET_CALLS:
        monkeypatch.setattr(owner, name, _refuse)
    for name in (*GITHUB_VARIABLES, "V4_JOB_STARTED", "V31_JOB_STARTED"):
        monkeypatch.delenv(name, raising=False)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git(repo: Path, *args: str) -> str:
    """``git`` in a temporary repository, its identity passed with ``-c``: no config written."""
    done = subprocess.run(["git", *GIT, "-C", str(repo), *args], capture_output=True, check=False)
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    return done.stdout.decode("utf-8")


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def events_at(repo: Path, commit: str) -> list[dict]:
    raw = git(repo, "show", f"{commit}:{reg.TRIAL_REGISTER}")
    return [json.loads(line) for line in raw.splitlines()]


# ---- the worlds -------------------------------------------------------------------------------

MANIFEST = reg.RunManifest(
    data={
        "config_path": "config/v4_data.json",
        "config_sha256": "1" * 64,
        "end_month": "2025-03",
        "daily_sha256": "2" * 64,
        "index_sha256": "3" * 64,
    },
    v3_pack_sha256="4" * 64,
)
TINY_CODE = {
    "src/crypto_grid_bot/__init__.py": b"",
    "src/crypto_grid_bot/v4/__init__.py": b'"""V4 (tiny checkout)."""\n',
    "scripts/v4_cell.py": b"CELL = 1\n",
    "pyproject.toml": b'[project]\nname = "tiny"\n',
    "requirements-dev.lock": b"pytest==8.3.0\n",
}
TINY_SPEC = b"A tiny V4 spec (synthetic): the rehearsal world's registered spec.\n"


def tiny_checkout(root: Path) -> Path:
    """A checkout with the V4 spec at its path, this checkout's trial register, ``TINY_CODE``
    tracked, and one untracked script (never copied)."""
    checkout = root / "checkout"
    files = {
        **TINY_CODE,
        reg.SPEC: TINY_SPEC,
        reg.TRIAL_REGISTER: (ROOT / reg.TRIAL_REGISTER).read_bytes(),
        "docs/notes.md": b"not code\n",
    }
    for path, content in files.items():
        (checkout / path).parent.mkdir(parents=True, exist_ok=True)
        (checkout / path).write_bytes(content)
    git(checkout, "init", "-q")
    git(checkout, "add", "-A")
    (checkout / "scripts/untracked.py").write_bytes(b"UNTRACKED = 1\n")
    return checkout


@pytest.fixture(scope="module")
def world(module_network_blocked, tmp_path_factory) -> tuple[Path, str]:
    """The rehearsal repository of a tiny checkout and its registration's SHA-256."""
    root = tmp_path_factory.mktemp("world")
    return reg.build_rehearsal_repo(root, tiny_checkout(root), MANIFEST)


def copied(world: tuple[Path, str], tmp_path: Path) -> Path:
    """A copy of the world's repository, for a test to change."""
    copy = tmp_path / "repo"
    shutil.copytree(world[0], copy)
    return copy


def code_pin_of(repo: Path) -> str:
    raw = (repo / reg.REGISTRATION).read_bytes()
    return reg.read_registration(raw).code_pin


# ---- the registration files (Ruling G1) --------------------------------------------------------


def registration_document() -> dict:
    return {
        "schema": "v4-registration-1",
        "code_pin": "a" * 40,
        "run_manifest_sha256": "b" * 64,
        "spec": {"path": reg.SPEC, "sha256": "c" * 64},
        "cells": [cell.cell_id for cell in all_cells()],
        "trial_id": "v4-0-registered-1",
    }


def manifest_document() -> dict:
    return {"schema": "v4-run-manifest-1", "data": dict(MANIFEST.data), "v3_pack_sha256": "4" * 64}


def test_the_constants_are_v4s():
    assert (reg.REGISTRATION, reg.RUN_MANIFEST) == (
        "config/v4_registration.json",
        "config/v4_run_manifest.json",
    )
    assert reg.TRIAL_REGISTER == "docs/trials/register.jsonl"
    assert reg.REHEARSAL_MARKER == "config/v4_rehearsal.json"
    assert (reg.V4_FAMILY, reg.WORKFLOW_FILE) == ("spec-v4.0", "v4-run.yml")
    assert reg.REGISTRATION_SCHEMA == "v4-registration-1"
    assert reg.MANIFEST_SCHEMA == "v4-run-manifest-1"
    # The verdict step reads what the dispatch check writes (Task 4's reader).
    assert reg.DISPATCH_CHECK_SCHEMA == report.DISPATCH_FORMAT == "v4-dispatch-check-1"
    allowed = {"config/v4_registration.json", "config/v4_run_manifest.json", reg.TRIAL_REGISTER}
    assert allowed == reg.ALLOWED
    assert reg.JOB_STARTED == "V4_JOB_STARTED"
    assert (reg.PLAN_JOB_BUDGET, reg.VERDICT_JOB_BUDGET) == (25 * 60, 55 * 60)
    assert (reg.PLAN_JOB, reg.STATUS_JOB) == ("plan", "status")
    assert reg.SKIPPED_JOBS == ("v3-pack", "v3-picks", "scenarios", "verdict", "analysis")
    assert reg.SKIPPED_MATRIX_JOBS == ("cell", "v3-cell")


def test_read_registration_and_manifest_exact_keys():
    document = registration_document()
    read = reg.read_registration(_canonical(document))
    assert read == reg.Registration(
        code_pin="a" * 40,
        run_manifest_sha256="b" * 64,
        spec={"path": reg.SPEC, "sha256": "c" * 64},
        cells=tuple(cell.cell_id for cell in all_cells()),
        trial_id="v4-0-registered-1",
    )
    assert len(read.cells) == 48
    for key in document:
        missing = {name: value for name, value in document.items() if name != key}
        with pytest.raises(ValueError, match="keys"):
            reg.read_registration(_canonical(missing))
    with pytest.raises(ValueError, match="keys"):
        reg.read_registration(_canonical({**document, "registration_sha256": "d" * 64}))
    cells = document["cells"]
    for wrong in (cells[::-1], cells[:-1], [*cells, cells[0]], [*cells[:-1], "v4_main-100-1x"]):
        with pytest.raises(ValueError, match=re.escape("arms.all_cells()")):
            reg.read_registration(_canonical({**document, "cells": wrong}))
    for key, value in (
        ("schema", "v4-registration-2"),
        ("code_pin", "A" * 40),
        ("run_manifest_sha256", "b" * 63),
        ("spec", {"path": reg.SPEC}),
        ("spec", {"path": "../spec.md", "sha256": "c" * 64}),
        ("trial_id", ""),
    ):
        with pytest.raises(ValueError):
            reg.read_registration(_canonical({**document, key: value}))
    # Canonical JSON only (combined.artifacts._canonical): no newline, no spaces, unique keys.
    for raw in (
        _canonical(document) + b"\n",
        json.dumps(document, indent=1).encode(),
        _canonical(document).replace(b'{"cells"', b'{"trial_id":"x","cells"', 1),
    ):
        with pytest.raises(ValueError):
            reg.read_registration(raw)

    manifest = manifest_document()
    assert reg.read_manifest(_canonical(manifest)) == MANIFEST
    for key in manifest:
        missing = {name: value for name, value in manifest.items() if name != key}
        with pytest.raises(ValueError, match="keys"):
            reg.read_manifest(_canonical(missing))
    with pytest.raises(ValueError, match="keys"):
        reg.read_manifest(_canonical({**manifest, "picks_sha256": "5" * 64}))
    data = manifest["data"]
    for key in data:
        short = {name: value for name, value in data.items() if name != key}
        with pytest.raises(ValueError, match="keys"):
            reg.read_manifest(_canonical({**manifest, "data": short}))
    with pytest.raises(ValueError, match="keys"):
        reg.read_manifest(_canonical({**manifest, "data": {**data, "coins": "10"}}))
    for key, value in (
        ("config_path", "/etc/v4.json"),
        ("config_sha256", "1" * 63),
        ("end_month", "2025-13"),
        ("daily_sha256", 2),
        ("index_sha256", None),
    ):
        with pytest.raises(ValueError):
            reg.read_manifest(_canonical({**manifest, "data": {**data, key: value}}))
    for key, value in (("schema", "v4-run-manifest-0"), ("v3_pack_sha256", "")):
        with pytest.raises(ValueError):
            reg.read_manifest(_canonical({**manifest, key: value}))
    with pytest.raises(ValueError, match="canonical"):
        reg.read_manifest(_canonical(manifest) + b"\n")


def test_the_marker_is_fixed_canonical_and_never_in_this_repository():
    marker = reg.marker_bytes()
    assert marker == reg.marker_bytes()
    document = json.loads(marker)
    assert _canonical(document) == marker
    assert document["synthetic"] is True and document["schema"] == "v4-rehearsal-1"
    # Ruling G3: the repository itself never holds it.
    assert not (ROOT / reg.REHEARSAL_MARKER).exists()
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--", reg.REHEARSAL_MARKER],
        capture_output=True,
        check=True,
    ).stdout
    assert tracked == b""


# ---- the rehearsal repository ------------------------------------------------------------------


def test_the_rehearsal_repo_sits_its_registration_on_its_code_pin(world):
    repo, registration_sha = world
    raw = (repo / reg.REGISTRATION).read_bytes()
    assert sha(raw) == registration_sha
    registration = reg.read_registration(raw)
    code_pin = registration.code_pin
    commits = git(repo, "rev-list", "--first-parent", "HEAD").split()
    assert len(commits) == 4 and commits[1] == code_pin
    head, _, registered, spec_commit = commits
    # The spec, at its real path, then the register with the checkout's events and the synthetic
    # registration naming that spec, then the code pin, then the registration files.
    assert git(repo, "show", "--name-only", "--format=", spec_commit).split() == [reg.SPEC]
    before = events_at(repo, registered)
    checkout_events = (ROOT / reg.TRIAL_REGISTER).read_bytes().splitlines()
    assert len(before) == len(checkout_events) + 1
    event = before[-1]
    assert (event["trial_id"], event["family"], event["event_type"]) == (
        "v4-0-synthetic",
        "spec-v4.0",
        "registration",
    )
    assert event["payload"]["spec"] == {
        "path": reg.SPEC,
        "commit": spec_commit,
        "sha256": sha(TINY_SPEC),
    }
    assert events_at(repo, f"{code_pin}^1") == before
    # The code pin: the tracked code (never the untracked script) and the marker.
    listed = set(git(repo, "ls-tree", "-r", "--name-only", code_pin).split())
    assert listed == {*TINY_CODE, reg.SPEC, reg.TRIAL_REGISTER, reg.REHEARSAL_MARKER}
    assert git(repo, "show", f"{code_pin}:{reg.REHEARSAL_MARKER}").encode() == reg.marker_bytes()
    # The head: the run manifest, the registration and the completion, nothing else.
    changed = git(repo, "diff", "--name-only", code_pin, head).split()
    assert changed == sorted(reg.ALLOWED)
    assert reg.read_manifest((repo / reg.RUN_MANIFEST).read_bytes()) == MANIFEST
    assert registration.run_manifest_sha256 == sha((repo / reg.RUN_MANIFEST).read_bytes())
    assert registration.spec == {"path": reg.SPEC, "sha256": sha(TINY_SPEC)}
    assert registration.trial_id == "v4-0-synthetic"
    completion = events_at(repo, head)[-1]
    assert completion["event_type"] == "completion"
    assert completion["payload"]["code_commit"] == code_pin
    assert completion["payload"]["code_paths"] == sorted(TINY_CODE)
    assert completion["payload"]["config"] == {"path": reg.REGISTRATION, "sha256": registration_sha}
    assert git(repo, "status", "--porcelain") == ""


def test_the_rehearsal_repo_refuses_an_existing_folder(tmp_path):
    (tmp_path / "repo").mkdir()
    with pytest.raises(OSError):
        reg.build_rehearsal_repo(tmp_path, tiny_checkout(tmp_path), MANIFEST)


# ---- the job gate (Rulings G2, G3) -------------------------------------------------------------


def test_gate_accepts_the_rehearsal_repo(world):
    repo, registration_sha = world
    gated = reg.gate(repo, "rehearsal", registration_sha)
    assert gated.head == git(repo, "rev-parse", "HEAD").strip()
    assert gated.registration_sha256 == registration_sha
    assert gated.registration.code_pin == code_pin_of(repo)
    assert gated.manifest == MANIFEST


def test_gate_accepts_the_rehearsal_repo_of_this_checkout(tmp_path):
    """The world the workflow's rehearsal gates: this checkout's own tracked code."""
    repo, registration_sha = reg.build_rehearsal_repo(tmp_path, ROOT, MANIFEST)
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--", "src", "scripts"],
        capture_output=True,
        check=True,
    ).stdout
    code_pin = code_pin_of(repo)
    listed = git(repo, "ls-tree", "-r", "-z", "--name-only", code_pin).split("\0")
    assert set(tracked.decode().split("\0")) - {""} <= set(listed)
    assert reg.gate(repo, "rehearsal", registration_sha).registration.code_pin == code_pin


def test_the_gate_command_writes_the_pins_for_github(world, tmp_path, capsys):
    repo, registration_sha = world
    output = tmp_path / "github_output"
    output.write_bytes(b"earlier=kept\n")
    argv = ["gate", "--repo", str(repo), "--mode", "rehearsal"]
    argv += ["--registration-sha256", registration_sha, "--github-output", str(output)]
    assert reg.main(argv) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.rstrip().endswith(": accepted")
    assert registration_sha in out and code_pin_of(repo) in out
    assert output.read_text(encoding="ascii").splitlines() == [
        "earlier=kept",
        f"code_pin={code_pin_of(repo)}",
        "v3_pack_sha256=" + "4" * 64,
        "config_path=config/v4_data.json",
        "config_sha256=" + "1" * 64,
        "end_month=2025-03",
        "daily_sha256=" + "2" * 64,
        "index_sha256=" + "3" * 64,
    ]


def test_gate_accepts_a_change_under_docs_reviews(world, tmp_path):
    repo = copied(world, tmp_path)
    note = repo / "docs/reviews/2026-10-24-claude-v4-registration.md"
    note.parent.mkdir(parents=True)
    note.write_bytes(b"a review of the registration\n")
    commit_all(repo, "a review")
    (repo / "docs/tasks").mkdir(parents=True)
    (repo / "docs/tasks/note.md").write_bytes(b"untracked, in the working tree\n")
    assert reg.gate(repo, "rehearsal", world[1]).registration_sha256 == world[1]


def test_gate_refuses_a_changed_file_outside_the_allowed_set(world, tmp_path, capsys):
    repo = copied(world, tmp_path)
    (repo / "scripts/v4_cell.py").write_bytes(b"CELL = 2\n")
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "rehearsal", world[1])
    (changed,) = [error for error in refused.value.errors if "scripts/v4_cell.py" in error]
    assert "after the code pin" in changed
    head = commit_all(repo, "a code change after the code pin")
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "rehearsal", world[1])
    errors = refused.value.errors
    assert any("scripts/v4_cell.py" in error and "after the code pin" in error for error in errors)
    assert f"not ready at the head {head}: committed code does not match pin" in "\n".join(errors)
    # The command: every error on a line of its own, exit 1, nothing written for GitHub.
    output = tmp_path / "github_output"
    argv = ["gate", "--repo", str(repo), "--mode", "rehearsal"]
    argv += ["--registration-sha256", world[1], "--github-output", str(output)]
    assert reg.main(argv) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and not output.exists()
    lines = captured.err.splitlines()
    assert len(lines) == len(errors)
    assert all(line.startswith("::error::v4_registration gate: refused: ") for line in lines)


def test_gate_refuses_a_wrong_registration_sha(world):
    repo, registration_sha = world
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "rehearsal", "f" * 64)
    errors = "\n".join(refused.value.errors)
    assert f"{reg.REGISTRATION} has SHA-256 {registration_sha}, not the dispatch's {'f' * 64}" in (
        errors
    )
    assert f"pinning {reg.REGISTRATION} at {'f' * 64}, found 0" in errors
    for wrong in ("F" * 64, "f" * 63, ""):
        with pytest.raises(reg.GateError, match="64 lowercase hex"):
            reg.gate(repo, "rehearsal", wrong)


def test_gate_refuses_a_manifest_that_is_not_the_registrations(world, tmp_path):
    repo = copied(world, tmp_path)
    other = {**manifest_document(), "v3_pack_sha256": "5" * 64}
    (repo / reg.RUN_MANIFEST).write_bytes(_canonical(other))
    head = commit_all(repo, "another run manifest")
    registered = reg.read_registration((repo / reg.REGISTRATION).read_bytes())
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "rehearsal", world[1])
    errors = "\n".join(refused.value.errors)
    expected = (
        f"{reg.RUN_MANIFEST} has SHA-256 {sha(_canonical(other))}; the registration pins "
        f"{registered.run_manifest_sha256}"
    )
    assert expected in errors
    assert f"not ready at the head {head}: committed file does not match pin" in errors


def test_registered_mode_refuses_the_marker(world):
    repo, registration_sha = world
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "registered", registration_sha)
    (error,) = refused.value.errors
    assert error.startswith(
        f"registered run refused: the checkout is a rehearsal world ({reg.REHEARSAL_MARKER} in "
        "the working tree, the head, the code pin)"
    )
    assert reg.world_errors(repo, "registered", code_pin_of(repo)) == [error]


def test_registered_mode_refuses_the_marker_anywhere(tmp_path):
    """In the working tree alone (untracked, or not a file), or committed after the code pin."""
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", str(repo))
    (repo / "README.md").write_bytes(b"a checkout\n")
    code_pin = commit_all(repo, "a code pin")
    assert reg.world_errors(repo, "registered", code_pin) == []
    (repo / "config").mkdir()
    (repo / reg.REHEARSAL_MARKER).mkdir()
    (error,) = reg.world_errors(repo, "registered", code_pin)
    assert f"({reg.REHEARSAL_MARKER} in the working tree)" in error
    (repo / reg.REHEARSAL_MARKER).rmdir()
    (repo / reg.REHEARSAL_MARKER).write_bytes(b"{}")
    (error,) = reg.world_errors(repo, "registered", code_pin)
    assert f"({reg.REHEARSAL_MARKER} in the working tree)" in error
    commit_all(repo, "a marker after the code pin")
    (error,) = reg.world_errors(repo, "registered", code_pin)
    assert f"({reg.REHEARSAL_MARKER} in the working tree, the head)" in error


def test_rehearsal_mode_requires_the_marker(world, tmp_path):
    repo, registration_sha = world
    code_pin = code_pin_of(repo)
    assert reg.world_errors(repo, "rehearsal", code_pin) == []
    # A code pin without it (the spec's commit).
    spec_commit = git(repo, "rev-list", "--first-parent", "HEAD").split()[-1]
    (error,) = reg.world_errors(repo, "rehearsal", spec_commit)
    assert f"{reg.REHEARSAL_MARKER} is not the rehearsal marker at the code pin" in error
    # A working tree without it, or with other bytes.
    copy = copied(world, tmp_path)
    (copy / reg.REHEARSAL_MARKER).write_bytes(reg.marker_bytes() + b"\n")
    (error,) = reg.world_errors(copy, "rehearsal", code_pin)
    assert "is not the rehearsal marker at the working tree" in error
    (copy / reg.REHEARSAL_MARKER).unlink()
    with pytest.raises(reg.GateError) as refused:
        reg.gate(copy, "rehearsal", registration_sha)
    assert any("at the working tree" in error for error in refused.value.errors)
    # Neither mode is any other.
    assert reg.world_errors(repo, "timing", code_pin) == ["unknown mode 'timing'"]
    with pytest.raises(reg.GateError, match="mode"):
        reg.gate(repo, "timing", registration_sha)  # type: ignore[arg-type]


def reregister(repo: Path, **changes: object) -> str:
    """Commit, on top of ``repo``'s head, a registration with ``changes`` and a completion of the
    synthetic trial pinning it (the register as the code pin commits it, plus that completion);
    its SHA-256."""
    code_pin = code_pin_of(repo)
    head_events = events_at(repo, "HEAD")
    document = {**json.loads((repo / reg.REGISTRATION).read_bytes()), **changes}
    raw = _canonical(document)
    (repo / reg.REGISTRATION).write_bytes(raw)
    register = repo / reg.TRIAL_REGISTER
    register.write_bytes(git(repo, "show", f"{code_pin}:{reg.TRIAL_REGISTER}").encode())
    completion = head_events[-1]
    payload = {**completion["payload"], "config": {"path": reg.REGISTRATION, "sha256": sha(raw)}}
    append_event(register, {**completion, "payload": payload})
    commit_all(repo, "another registration")
    return sha(raw)


def test_gate_refuses_a_registration_naming_another_trial_or_spec(world, tmp_path):
    repo = copied(world, tmp_path)
    other = reregister(repo, trial_id="v4-0-other")
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "rehearsal", other)
    assert refused.value.errors == (
        "the registration names trial v4-0-other, but the spec-v4.0 completion that authorizes "
        "it is trial v4-0-synthetic",
    )
    other = reregister(repo, trial_id="v4-0-synthetic", spec={"path": reg.SPEC, "sha256": "c" * 64})
    with pytest.raises(reg.GateError) as refused:
        reg.gate(repo, "rehearsal", other)
    (error,) = refused.value.errors
    assert error.startswith(f"the registration pins the spec {reg.SPEC} at {'c' * 64}")


# ---- the V4 trial (Ruling G2) ------------------------------------------------------------------


def trial_pins(repo: Path, registration_sha: str) -> dict:
    registration = reg.read_registration((repo / reg.REGISTRATION).read_bytes())
    return {
        "code_pin": registration.code_pin,
        "registration_sha256": registration_sha,
        "manifest_sha256": registration.run_manifest_sha256,
    }


def renamed(event: dict, trial: str, family: str) -> dict:
    payload = dict(event["payload"])
    if event["event_type"] == "completion":
        payload["registration_id"] = f"{trial}-registration"
    return {
        **event,
        "trial_id": trial,
        "event_id": f"{trial}-{event['event_type']}",
        "family": family,
        "payload": payload,
    }


@pytest.mark.parametrize("case", ["no completion", "another family", "two completions"])
def test_trial_errors_need_one_completion_of_family_spec_v4(world, tmp_path, case):
    repo, registration_sha = world
    pins = trial_pins(repo, registration_sha)
    head = git(repo, "rev-parse", "HEAD").strip()
    assert reg.trial_errors(repo, head, **pins) == []
    copy = copied(world, tmp_path)
    events = events_at(copy, "HEAD")
    registration, completion = events[-2], events[-1]
    register = copy / reg.TRIAL_REGISTER
    found = "found 0"
    if case in ("no completion", "another family"):
        at_pin = git(copy, "show", f"{pins['code_pin']}:{reg.TRIAL_REGISTER}")
        register.write_bytes(at_pin.encode())
        if case == "another family":  # V3.1's family, pinning V4's registration: not V4's trial
            append_event(register, renamed(registration, "v3-1-other", "spec-v3.1"))
            append_event(register, renamed(completion, "v3-1-other", "spec-v3.1"))
    else:
        append_event(register, renamed(registration, "v4-0-second", "spec-v4.0"))
        append_event(register, renamed(completion, "v4-0-second", "spec-v4.0"))
        found = "found 2 (v4-0-synthetic, v4-0-second)"
    head = commit_all(copy, case)
    assert reg.trial_errors(copy, head, **pins) == [
        f"{reg.TRIAL_REGISTER} at the head {head} must hold one spec-v4.0 completion pinning "
        f"{reg.REGISTRATION} at {registration_sha}, {found}"
    ]


def test_trial_errors_need_the_completion_to_bind_the_registration(world):
    repo, registration_sha = world
    pins = trial_pins(repo, registration_sha)
    head = git(repo, "rev-parse", "HEAD").strip()
    (error,) = reg.trial_errors(repo, head, **{**pins, "code_pin": "0" * 40})
    assert error == (
        f"the spec-v4.0 completion pins code commit {pins['code_pin']}, not the registration's "
        f"code pin {'0' * 40}"
    )
    (error,) = reg.trial_errors(repo, head, **{**pins, "manifest_sha256": "0" * 64})
    assert error.startswith(f"the spec-v4.0 completion pins its manifest {reg.RUN_MANIFEST} at")
    assert reg.trial_errors(repo, "0" * 40, **pins)[0].startswith("the head 0000")


# ---- one dispatch per registration (Ruling G4) ---------------------------------------------------

SHA = "e" * 64
TITLE = f"v4-run registered {SHA}"
NOW, EARLIER, LATER = "2026-10-24T12:00:00Z", "2026-10-24T11:59:59Z", "2026-10-24T12:00:01Z"
API = "https://api.github.com/repos/owner/repo/actions/"


def test_registered_title():
    assert reg.registered_title("ab" * 32) == "v4-run registered " + "ab" * 32
    assert reg.run_titles("registered", SHA) == (TITLE,)
    assert reg.run_titles("rehearsal", SHA) == (f"v4-run rehearsal {SHA}",)
    assert reg.run_titles("timing", SHA) == (f"v4-run timing {SHA}",)
    # An empty input leaves the run-name ending in a space, which GitHub may keep or trim.
    assert reg.run_titles("rehearsal", "") == ("v4-run rehearsal ", "v4-run rehearsal")
    with pytest.raises(ValueError, match="mode"):
        reg.run_titles("smoke", SHA)


def workflow_run(
    run_id, created=EARLIER, title=TITLE, status="completed", conclusion="success", attempts=1
):
    """A run as GitHub's REST API lists it: the fields the check reads."""
    return {
        "id": run_id,
        "display_title": title,
        "created_at": created,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempts,
    }


CURRENT = workflow_run(500, created=NOW, status="in_progress", conclusion=None)


def test_other_dispatches_counts_an_earlier_and_a_same_second_run():
    runs = [
        workflow_run(600, created=LATER),  # created after this run: it never counts
        CURRENT,
        workflow_run(499, created=NOW),  # the same second: a tie counts
        workflow_run(401, title=f"v4-run registered {'f' * 64}"),  # another registration
        workflow_run(402, title=f"v4-run rehearsal {SHA}"),  # another mode
        workflow_run(403, title=f"v31-run registered {SHA}"),  # V3.1's workflow's title
        workflow_run(404, title=f"{TITLE} "),  # not exactly the title
        workflow_run(300, created="2026-10-01T00:00:00Z", status="queued", conclusion=None),
    ]
    assert reg.other_dispatches(runs, CURRENT, SHA) == (300, 499)
    assert reg.other_dispatches([CURRENT], CURRENT, SHA) == ()
    rehearsal = {**CURRENT, "display_title": f"v4-run rehearsal {SHA}"}
    assert reg.other_dispatches(runs, rehearsal, SHA, mode="rehearsal") == (402,)
    with pytest.raises(ValueError, match="the current run 500 is titled"):
        reg.other_dispatches(runs, rehearsal, SHA)
    with pytest.raises(ValueError, match="the current run 500 is not among"):
        reg.other_dispatches([workflow_run(400)], CURRENT, SHA)


def job(job_id, name, conclusion, *, run=400, attempt=1, status="completed"):
    return {
        "id": job_id,
        "run_id": run,
        "run_attempt": attempt,
        "name": name,
        "status": status,
        "conclusion": conclusion,
    }


# Every job of v4-run.yml as GitHub lists a launch whose plan job failed: the status job ran,
# every other job was skipped (the matrix jobs under their bare names).
STOPPED = (
    ("plan", "failure"),
    ("v3-pack", "skipped"),
    ("v3-picks", "skipped"),
    ("cell", "skipped"),
    ("v3-cell", "skipped"),
    ("scenarios", "skipped"),
    ("verdict", "skipped"),
    ("analysis", "skipped"),
    ("status", "success"),
)


def jobs_of(pattern, *, run=400, attempt=1, first=1):
    return [
        job(first + index, name, conclusion, run=run, attempt=attempt)
        for index, (name, conclusion) in enumerate(pattern)
    ]


def stopped_but(name, conclusion):
    return jobs_of([(n, c) for n, c in STOPPED if n != name] + [(name, conclusion)])


DONE = workflow_run(400, conclusion="failure")


def test_launch_decision_uncounted_only_when_plan_failed_and_the_rest_skipped():
    assert reg.launch_decision(DONE, jobs_of(STOPPED)) == (None, False)
    assert reg.launch_reason(DONE, jobs_of(STOPPED)) is None
    # The matrix jobs under their matrix values; a second attempt that stopped the same way.
    named = [
        job(1, "plan", "failure"),
        job(2, "cell (v4_main-1000-1x, v4_main, 1000, 1)", "skipped"),
        job(3, "v3-cell (v3_as_built-1000-1x)", "skipped"),
        job(4, "status", "failure"),
    ]
    assert reg.launch_decision(DONE, named) == (None, False)
    twice = workflow_run(400, attempts=2, conclusion="failure")
    jobs = jobs_of(STOPPED) + jobs_of(STOPPED, attempt=2, first=100)
    assert reg.launch_decision(twice, jobs) == (None, False)
    # The plan job did not fail: it counts.
    for ended in ("success", "cancelled", None):
        reason, malformed = reg.launch_decision(DONE, stopped_but("plan", ended))
        assert f"ended {ended!r}, not failure" in reason and malformed is False
    # Any later job of V4's workflow that ran: it counts.
    later = ("v3-pack", "v3-picks", "scenarios", "verdict", "analysis", "cell", "v3-cell")
    for name in (*later, "cell (v4_main-1000-1x)", "v3-cell (v3_as_built-10000-1x)"):
        reason, malformed = reg.launch_decision(DONE, stopped_but(name, "success"))
        assert f"its job {name!r}" in reason and "not skipped: it ran" in reason, name
        assert malformed is False
    # V3.1's job names are not V4's: a launch listing one counts.
    for name in ("aggregate", "run-main (w1.combined.olhc.c1.research)", "prepare", "picks"):
        reason, _ = reg.launch_decision(DONE, [*jobs_of(STOPPED), job(50, name, "skipped")])
        assert reason is not None and "is not a job of this workflow" in reason, name
    # Queued or running, or malformed records: it counts.
    running = workflow_run(400, status="in_progress", conclusion=None)
    assert "not completed" in reg.launch_decision(running, jobs_of(STOPPED))[0]
    assert reg.launch_decision(DONE, [])[1] is True
    assert reg.launch_decision(DONE, "jobs") == ("its jobs are not a list", True)


class Response:
    """What the opener returns: a urllib response, as the dispatch check reads it."""

    def __init__(self, raw: bytes, status: int = 200) -> None:
        self.raw, self.status = raw, status

    def read(self, limit: int = -1) -> bytes:
        return self.raw if limit < 0 else self.raw[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answer(document: object) -> Response:
    return Response(json.dumps(document).encode("utf-8"))


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(API, code, "synthetic", HTTPMessage(), io.BytesIO(b"{}"))


class FakeGitHub:
    """GitHub's REST API for the dispatch check, in memory: the current run (``runs/500``), the
    runs of ``v4-run.yml`` in pages of 100, and each run's jobs (a launch stopped at the plan job
    by default). ``answers`` gives a path's responses (an exception is raised) in turn before the
    default takes over. Records every URL asked for."""

    def __init__(self, runs, current=CURRENT, *, answers=None, jobs=None):
        self.runs, self.current = list(runs), current
        self.answers, self.jobs = answers or {}, jobs or {}
        self.requests: list[str] = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.requests.append(url)
        assert url.startswith(API), url
        path = url[len(API) :]
        given = self.answers.get(path)
        if isinstance(given, list):
            given = given.pop(0) if given else None
        if isinstance(given, BaseException):
            raise given
        if given is not None:
            return given
        if path == "runs/500":
            return answer(self.current)
        listed = re.fullmatch(r"runs/([1-9][0-9]*)/jobs\?filter=all&per_page=100&page=1", path)
        if listed is not None:
            run_id = int(listed[1])
            records = self.jobs.get(run_id, jobs_of(STOPPED, run=run_id))
            return answer({"total_count": len(records), "jobs": records})
        assert path == "workflows/v4-run.yml/runs?per_page=100&page=1", url
        return answer({"total_count": len(self.runs), "workflow_runs": self.runs})


PAGE = "workflows/v4-run.yml/runs?per_page=100&page=1"


def no_sleep(seconds):
    raise AssertionError(f"slept {seconds} s: no retry was due")


@pytest.fixture
def github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "stand-in-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "500")


def test_dispatch_check_reads_v4_runs_workflow(github_env):
    api = FakeGitHub([CURRENT, workflow_run(400, conclusion="failure"), workflow_run(300)])
    api.jobs[300] = jobs_of([("plan", "success"), ("cell (v4_main-1000-1x)", "success")], run=300)
    launches = reg.dispatch_check(SHA, api, mode="registered", sleep=no_sleep, judge_all=True)
    assert [(launch.run_id, launch.counts) for launch in launches] == [(300, True), (400, False)]
    assert api.requests == [
        API + "runs/500",
        API + PAGE,
        API + "runs/300/jobs?filter=all&per_page=100&page=1",
        API + "runs/400/jobs?filter=all&per_page=100&page=1",
    ]
    # A registered check stops at the first that counts: it already refuses.
    api.requests.clear()
    (launch,) = reg.dispatch_check(SHA, api, mode="registered", sleep=no_sleep)
    assert launch.run_id == 300 and API + "runs/400/jobs?filter=all&per_page=100&page=1" not in (
        api.requests
    )


def test_dispatch_check_retries_transient_errors_then_fails_closed(github_env, capsys, tmp_path):
    # A server error once: retried after the first backoff, then the check passes.
    api = FakeGitHub([CURRENT], answers={"runs/500": [http_error(503)]})
    slept: list[float] = []
    assert reg.dispatch_check(SHA, api, mode="registered", sleep=slept.append) == ()
    assert slept == [15]
    assert "the current run: attempt 1 of 5 failed" in capsys.readouterr().err
    # At every attempt: five in all, then the check fails closed, naming the last error.
    failing = FakeGitHub([CURRENT], answers={PAGE: [http_error(502)] * 5})
    slept = []
    with pytest.raises(ValueError, match=r"HTTP 502 \(still failing after 5 attempts\)") as caught:
        reg.dispatch_check(SHA, failing, mode="registered", sleep=slept.append)
    assert slept == [15, 30, 60, 120]
    assert failing.requests.count(API + PAGE) == 5
    assert "stand-in-token" not in str(caught.value)
    # A permanent error: at once, no wait.
    once = FakeGitHub([CURRENT], answers={PAGE: [http_error(401)]})
    with pytest.raises(ValueError, match="HTTP 401"):
        reg.dispatch_check(SHA, once, mode="registered", sleep=no_sleep)
    # The plan job's command refuses, exit 1, and writes nothing.
    out = tmp_path / "reasons.json"
    failing = FakeGitHub([CURRENT], answers={PAGE: [http_error(502)] * 5})
    argv = ["dispatch-check", "--mode", "registered", "--registration-sha256", SHA]
    code = reg.main([*argv, "--out", str(out)], github_opener=failing, sleep=lambda s: None)
    captured = capsys.readouterr()
    assert code == 1 and "still failing after 5 attempts" in captured.err
    assert captured.out == "" and not out.exists()
    # The verdict job's check (--judge-all) records the failure as a reason instead, so the
    # verdict is incomplete (fail closed), and exits 0 once the file is written.
    failing = FakeGitHub([CURRENT], answers={PAGE: [http_error(502)] * 5})
    code = reg.main(
        [*argv, "--judge-all", "--out", str(out)], github_opener=failing, sleep=lambda s: None
    )
    assert code == 0, capsys.readouterr().err
    (reason,) = report.read_dispatch_reasons(out)
    assert reason.startswith("another dispatch of this registration could not be ruled out: ")
    assert "HTTP 502 (still failing after 5 attempts)" in reason


def test_the_dispatch_check_command_and_its_reasons_file(github_env, capsys, tmp_path):
    argv = ["dispatch-check", "--mode", "registered", "--registration-sha256", SHA]
    # No earlier launch: it passes, one line, and the file lists none.
    out = tmp_path / "none.json"
    api = FakeGitHub([workflow_run(600, created=LATER), CURRENT])
    assert reg.main([*argv, "--out", str(out)], github_opener=api, sleep=no_sleep) == 0
    line = capsys.readouterr().out
    assert line.count("\n") == 1 and "0 counted, 0 not counted" in line
    assert out.read_bytes() == _canonical({"format": "v4-dispatch-check-1", "earlier": []})
    assert report.read_dispatch_reasons(out) == ()
    # An earlier launch that counts: the plan's check refuses, naming it and why.
    api = FakeGitHub([CURRENT, workflow_run(400, conclusion="failure"), workflow_run(300)])
    api.jobs[300] = jobs_of([("plan", "success")], run=300)
    assert reg.main(argv, github_opener=api, sleep=no_sleep) == 1
    err = capsys.readouterr().err
    assert "another dispatch of this registration: run 300" in err
    # The verdict job's check judges every launch and writes each one that counts.
    api = FakeGitHub([CURRENT, workflow_run(400, conclusion="failure"), workflow_run(300)])
    api.jobs[300] = jobs_of([("plan", "success")], run=300)
    out = tmp_path / "reasons.json"
    code = reg.main([*argv, "--judge-all", "--out", str(out)], github_opener=api, sleep=no_sleep)
    assert code == 0
    captured = capsys.readouterr()
    assert "1 counted, 1 not counted" in captured.out
    assert reg.uncounted_line(400) in captured.err
    (reason,) = report.read_dispatch_reasons(out)
    assert reason.startswith("another dispatch of this registration: run 300 (its plan job")
    # An existing file is never replaced: refused before any request.
    api = FakeGitHub([CURRENT])
    code = reg.main([*argv, "--judge-all", "--out", str(out)], github_opener=api, sleep=no_sleep)
    assert code == 1 and api.requests == [] and "exists" in capsys.readouterr().err
    assert report.read_dispatch_reasons(out) == (reason,)


def test_a_report_only_check_prints_its_decision(github_env, capsys, tmp_path):
    title = "v4-run rehearsal "  # the rehearsal's run-name with an empty input
    current = {**CURRENT, "display_title": title}
    runs = [current, workflow_run(300, title="v4-run rehearsal", conclusion="failure")]
    api = FakeGitHub(runs, current, jobs={500: jobs_of([("plan", None)], run=500)})
    argv = ["dispatch-check", "--mode", "rehearsal", "--report-only", "--registration-sha256", ""]
    out = tmp_path / "rehearsal.json"
    assert reg.main([*argv, "--out", str(out)], github_opener=api, sleep=no_sleep) == 0
    captured = capsys.readouterr()
    assert "a registered check would pass; counted: none" in captured.err
    assert reg.uncounted_line(300) in captured.err
    assert API + "runs/500/jobs?filter=all&per_page=100&page=1" in api.requests  # the probe
    assert report.read_dispatch_reasons(out) == ()


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (["--mode", "registered", "--report-only"], "a registered check always decides"),
        (["--mode", "rehearsal"], "--report-only"),
        (["--mode", "timing"], "--report-only"),
        (["--mode", "registered", "--judge-all"], "--judge-all needs --out"),
        (["--mode", "rehearsal", "--report-only", "--judge-all", "--out", "x"], "registered"),
    ],
)
def test_the_dispatch_check_refuses_conflicting_options(github_env, capsys, extra, message):
    api = FakeGitHub([CURRENT])
    argv = ["dispatch-check", "--registration-sha256", SHA, *extra]
    assert reg.main(argv, github_opener=api, sleep=no_sleep) == 1
    assert message in capsys.readouterr().err and api.requests == []


def test_the_job_start_is_v4s(github_env, monkeypatch):
    """The deadline counts from V4_JOB_STARTED; V3.1's variable is not read."""
    monkeypatch.setenv("V31_JOB_STARTED", "not a time")
    assert reg.dispatch_check(SHA, FakeGitHub([CURRENT]), mode="registered", sleep=no_sleep) == ()
    monkeypatch.setenv("V4_JOB_STARTED", "not a time")
    api = FakeGitHub([CURRENT])
    with pytest.raises(ValueError, match="V4_JOB_STARTED 'not a time'"):
        reg.dispatch_check(SHA, api, mode="registered", sleep=no_sleep)
    assert api.requests == []
    # A plan job that started 25 minutes ago has no time left: refused before any request.
    monkeypatch.setenv("V4_JOB_STARTED", "1792000000")
    with pytest.raises(ValueError, match="deadline"):
        reg.dispatch_check(
            SHA, api, mode="registered", sleep=no_sleep, wall=lambda: 1792000000.0 + 25 * 60
        )
    assert api.requests == []
