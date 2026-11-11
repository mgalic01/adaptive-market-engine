"""The committed V4.0 registration passes every gate of the registered run, for good.

The registration is three commits on main at ``BASE`` (the step-5 plan, steps 2 to 4; owner
decision v4-d27):

1. the V4 trial's registration event in ``docs/trials/register.jsonl``;
2. the code pin: ``BASE``'s code unchanged, plus this test and nothing else;
3. the registration files (``config/v4_run_manifest.json``, ``config/v4_registration.json``), the
   trial's completion and the review.

This test belongs to the code pin, because after the pin only the registration files may change
(``v4_registration.ALLOWED``, Ruling G2): a test added later would make every registered job's gate
refuse. So it is written before the registration exists:

- while HEAD commits no ``config/v4_registration.json`` (at the code pin itself), and outside a git
  checkout, it skips;
- once HEAD commits it, it never skips. A registration present but broken fails, and so does a
  checkout whose history is too shallow to check it (CI fetches the whole history).

Every check runs at the commit that last changed ``config/v4_registration.json``, never at the
moving HEAD: code lands on main after the registered run, and a check of HEAD's changes since the
code pin would then fail for good. The checks run in a subprocess on a scratch checkout of that
commit (sharing this repository's objects through git alternates), with that commit's own ``src/``
and ``scripts/`` first on the import path, so later changes to the gate can neither break nor weaken
them. The subprocess is this file run as a script; it prints one JSON document of facts, which the
tests below compare with the values the registration was built from: main at ``BASE`` and the
pinning data run 42614834522. Nothing here reads market data or touches the network.
"""

import hashlib
import json
import shutil
import subprocess  # nosec B404
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
THIS_TEST = "tests/test_v4_registration_committed.py"
REGISTRATION = "config/v4_registration.json"
RUN_MANIFEST = "config/v4_run_manifest.json"
TRIAL_REGISTER = "docs/trials/register.jsonl"
REVIEW = "docs/reviews/2026-11-09-claude-v4-registration.md"
FAMILY = "spec-v4.0"
TRIAL_ID = "v4-0-registered-1"
REGISTRATION_EVENT = f"{TRIAL_ID}-record"
COMPLETION_EVENT = f"{TRIAL_ID}-complete"
# Main where the registration starts (the step-5 plan's B). The code pin must hold exactly its code.
BASE = "0c87fdde51e4a55dfaa5a7cab52fa79133bff406"
SPEC = {
    "path": "docs/superpowers/specs/2026-10-17-v4-design.md",
    "commit": BASE,
    "sha256": "ada8b856c45fc4be5a31e870e154884286013d5184a1c4f23ccb7871ca2b4e06",
}
# The pinning data run's printed pins (run 42614834522 at BASE, the step-5 plan's step 1).
DATA_PINS = {
    "config_path": "config/v4_data.json",
    "config_sha256": "7868b35a21db5e725db3febf61f4d7d8c1cee7d6729bffb939de5d4a1ea36659",
    "end_month": "2026-09",
    "daily_sha256": "69268e3fac006199746442486e1de38da1dc8bb1f78680c427dc474ffa8be138",
    "index_sha256": "b364ccd2c3f0cbe938f1972c3706733f10ddad2b8c146cd847a068e12fc4afe3",
}
# V3.1's input pack, the workflow's V3_PACK_SHA256.
V3_PACK_SHA256 = "8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee"
CAPITALS = {100: 24, 1000: 24, 10000: 24}
CODE_PREFIXES = ("src/", "scripts/")
CODE_FILES = frozenset({"pyproject.toml", "requirements-dev.lock", "requirements.txt"})


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    # A fixed argument list, no shell; git is resolved from PATH as in CI.
    return subprocess.run(  # nosec B603 B607
        ["git", "-C", str(root), *args], capture_output=True, check=False
    )


def _git_bytes(root: Path, *args: str) -> bytes:
    done = _run_git(root, *args)
    if done.returncode:
        message = done.stderr.decode("utf-8", "replace").strip()
        raise AssertionError(f"git {' '.join(args)} failed in {root}: {message}")
    return done.stdout


def _git(root: Path, *args: str) -> str:
    return _git_bytes(root, *args).decode("utf-8")


def _code_entries(root: Path, commit: str) -> list[str]:
    """``git ls-tree`` records of every code path at ``commit``: the files whose bytes
    ``trial_register.check_ready`` digests (``src/``, ``scripts/`` and the packaging files)."""
    listing = _git(root, "ls-tree", "-r", "-z", "--full-tree", commit).split("\0")
    return sorted(
        record
        for record in listing
        if record
        and (
            record.partition("\t")[2].startswith(CODE_PREFIXES)
            or record.partition("\t")[2] in CODE_FILES
        )
    )


def _introducing_commit() -> str:
    """The commit that last changed the committed registration; skips while there is none."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    inside = _run_git(ROOT, "rev-parse", "--is-inside-work-tree")
    if inside.returncode or inside.stdout.strip() != b"true":
        pytest.skip("not a git checkout")
    if _run_git(ROOT, "cat-file", "-e", f"HEAD:{REGISTRATION}").returncode:
        if (ROOT / REGISTRATION).exists():
            pytest.fail(f"{REGISTRATION} exists in the working tree but HEAD does not commit it")
        pytest.skip(f"HEAD commits no {REGISTRATION} yet (the code pin precedes it)")
    if _git(ROOT, "rev-parse", "--is-shallow-repository").strip() != "false":
        pytest.fail(
            "this checkout's history is shallow, so the registration's code pin and trial events "
            "cannot be read; check out the whole history (fetch-depth: 0)"
        )
    return _git(ROOT, "log", "-1", "--format=%H", "HEAD", "--", REGISTRATION).strip()


def _scratch_checkout(directory: Path, revision: str) -> Path:
    """A checkout of ``revision`` in ``directory``, sharing this repository's objects (git
    alternates), with the bytes of every blob as committed."""
    objects = _git(ROOT, "rev-parse", "--path-format=absolute", "--git-path", "objects").strip()
    _git(directory.parent, "init", "-q", str(directory))
    # Bytes, not text: a text write on Windows would end the path in "\r".
    (directory / ".git/objects/info/alternates").write_bytes(f"{objects}\n".encode())
    _git(directory, "config", "core.autocrlf", "false")
    _git(directory, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", revision)
    return directory


@pytest.fixture(scope="module")
def committed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The facts the registration's own commit gives, from its own code (``_facts``)."""
    revision = _introducing_commit()
    checkout = _scratch_checkout(tmp_path_factory.mktemp("v4-registration") / "repo", revision)
    done = subprocess.run(  # nosec B603: this file, run by this interpreter, no shell
        [sys.executable, "-E", "-P", str(Path(__file__).resolve()), str(checkout), revision],
        capture_output=True,
        check=False,
    )
    stderr = done.stderr.decode("utf-8", "replace")
    assert done.returncode == 0, f"the registration's checks crashed:\n{stderr}"
    facts: dict[str, Any] = json.loads(done.stdout)
    facts["revision"], facts["checkout"] = revision, checkout
    return facts


def test_the_checks_run_the_registrations_own_code(committed: dict[str, Any]) -> None:
    checkout = Path(committed["checkout"]).resolve()
    for module in ("crypto_grid_bot", "v4_registration", "trial_register"):
        assert Path(committed["modules"][module]).resolve().is_relative_to(checkout), module
    assert committed["head"] == committed["revision"]


def test_the_job_gate_accepts_the_registration(committed: dict[str, Any]) -> None:
    """``v4_registration.gate``, as every registered job calls it, with the file's own SHA-256."""
    assert committed["gate_errors"] == []
    assert committed["gate"]["head"] == committed["revision"]
    assert committed["gate"]["registration_sha256"] == committed["registration_file_sha256"]
    assert committed["gate"]["outputs"] == [
        ["code_pin", committed["registration"]["code_pin"]],
        ["v3_pack_sha256", V3_PACK_SHA256],
        *([key, value] for key, value in DATA_PINS.items()),
    ]


def test_the_files_are_canonical_and_pin_each_other(committed: dict[str, Any]) -> None:
    registration = committed["registration"]
    assert registration["schema"] == "v4-registration-1"
    assert registration["trial_id"] == TRIAL_ID
    assert registration["run_manifest_sha256"] == committed["run_manifest_file_sha256"]
    assert registration["spec"] == {"path": SPEC["path"], "sha256": SPEC["sha256"]}
    assert committed["registration_read"] is None
    assert committed["run_manifest_read"] is None


def test_the_run_manifest_holds_the_pinning_data_runs_pins(committed: dict[str, Any]) -> None:
    assert committed["run_manifest"] == {
        "schema": "v4-run-manifest-1",
        "data": DATA_PINS,
        "v3_pack_sha256": V3_PACK_SHA256,
    }
    assert committed["data_config_sha256"] == DATA_PINS["config_sha256"]


def test_the_cells_are_the_72_of_the_run(committed: dict[str, Any]) -> None:
    cells = committed["cells"]
    assert cells == committed["registered_cells"] == committed["registration"]["cells"]
    assert len(cells) == len(set(cells)) == 72
    assert Counter(capital for _, capital, _ in committed["cell_specs"]) == {
        str(capital): count for capital, count in CAPITALS.items()
    }
    assert Counter(multiple for _, _, multiple in committed["cell_specs"]) == {"1": 36, "2": 36}
    assert len({arm for arm, _, _ in committed["cell_specs"]}) == 12


def test_the_code_pin_is_the_bases_code_plus_this_test(committed: dict[str, Any]) -> None:
    code_pin = committed["registration"]["code_pin"]
    event_commit = _git(ROOT, "rev-parse", f"{code_pin}^1").strip()
    assert _git(ROOT, "rev-parse", f"{event_commit}^1").strip() == BASE
    assert len(_git(ROOT, "rev-list", "--parents", "-n", "1", code_pin).split()) == 2
    assert len(_git(ROOT, "rev-list", "--parents", "-n", "1", event_commit).split()) == 2
    assert _code_entries(ROOT, code_pin) == _code_entries(ROOT, BASE)
    assert _git(ROOT, "diff", "--name-only", BASE, event_commit).split() == [TRIAL_REGISTER]
    assert _git(ROOT, "diff", "--name-only", event_commit, code_pin).split() == [THIS_TEST]


def test_only_the_registration_files_changed_after_the_pin(committed: dict[str, Any]) -> None:
    assert set(committed["changed_since"]) == {
        REGISTRATION,
        RUN_MANIFEST,
        TRIAL_REGISTER,
        REVIEW,
    }
    assert committed["world_errors"] == []


def test_the_v4_trial_authorizes_the_registration(committed: dict[str, Any]) -> None:
    """``trial_register.check_ready`` passes for the trial at the registration commit, and its
    completion binds the code pin, the registration and the run manifest."""
    revision = committed["revision"]
    code_pin = committed["registration"]["code_pin"]
    assert committed["trial_errors"] == []
    assert committed["v4_completions"] == [TRIAL_ID]
    completion = committed["check_ready"]
    assert isinstance(completion, dict), completion
    assert completion["event_id"] == COMPLETION_EVENT
    assert completion["family"] == FAMILY
    payload = completion["payload"]
    assert payload["registration_id"] == REGISTRATION_EVENT
    assert payload["code_commit"] == code_pin
    assert payload["config"] == {
        "path": REGISTRATION,
        "sha256": committed["registration_file_sha256"],
    }
    assert payload["manifest"] == {
        "path": RUN_MANIFEST,
        "sha256": committed["run_manifest_file_sha256"],
    }
    assert payload["review"] == REVIEW
    assert _run_git(ROOT, "cat-file", "-e", f"{revision}:{REVIEW}").returncode == 0


def test_the_register_grew_by_the_event_then_the_completion(committed: dict[str, Any]) -> None:
    """The event is the one line the code pin's parent added to main's register, and the completion
    is the one line the registration commit added to that."""
    revision = committed["revision"]
    code_pin = committed["registration"]["code_pin"]
    base = _git_bytes(ROOT, "show", f"{BASE}:{TRIAL_REGISTER}")
    earlier = _git_bytes(ROOT, "show", f"{code_pin}^1:{TRIAL_REGISTER}")
    later = _git_bytes(ROOT, "show", f"{revision}:{TRIAL_REGISTER}")
    assert earlier.startswith(base) and later.startswith(earlier)
    added = earlier[len(base) :].splitlines()
    assert len(added) == 1
    assert json.loads(added[0]) == committed["registration_event"]
    finished = later[len(earlier) :].splitlines()
    assert len(finished) == 1
    assert json.loads(finished[0]) == committed["check_ready"]


def test_the_registration_event_pins_the_spec_at_the_base(committed: dict[str, Any]) -> None:
    event = committed["registration_event"]
    assert event["event_id"] == REGISTRATION_EVENT
    assert event["trial_id"] == TRIAL_ID
    assert event["family"] == FAMILY and event["parent_trial_id"] is None
    payload = event["payload"]
    assert payload["spec"] == SPEC
    assert payload["preregistered"] is True
    assert payload["sizes"] == list(CAPITALS)
    assert payload["seeds"] == []
    assert payload["data"] is None and payload["code"] is None
    assert len(payload["candidates"]) == 12
    blob = _git_bytes(ROOT, "show", f"{BASE}:{SPEC['path']}")
    assert hashlib.sha256(blob).hexdigest() == SPEC["sha256"]


def _facts(checkout: Path, revision: str) -> dict[str, object]:
    """Run in a subprocess (``__main__``) on the scratch checkout of the registration commit, with
    that commit's ``src/`` and ``scripts/`` first on the import path: the gate and the readers of
    the registered run, as each registered job calls them, and the values they read. A refusal is
    recorded as its message, never raised past here."""
    sys.path[:0] = [str(checkout / "src"), str(checkout / "scripts")]
    import trial_register
    import v4_registration

    import crypto_grid_bot
    from crypto_grid_bot.combined.driver.run_cell import changed_since, head_commit
    from crypto_grid_bot.v4.engine.arms import all_cells

    registration_raw = (checkout / REGISTRATION).read_bytes()
    manifest_raw = (checkout / RUN_MANIFEST).read_bytes()
    registration = json.loads(registration_raw)
    code_pin = registration["code_pin"]
    registration_sha = hashlib.sha256(registration_raw).hexdigest()
    manifest_sha = hashlib.sha256(manifest_raw).hexdigest()

    def refusal(call: Any, raw: bytes) -> str | None:
        try:
            call(raw)
        except ValueError as exc:  # recorded for the assertion, which names it
            return str(exc)
        return None

    facts: dict[str, object] = {
        "modules": {
            "crypto_grid_bot": crypto_grid_bot.__file__,
            "v4_registration": v4_registration.__file__,
            "trial_register": trial_register.__file__,
        },
        "head": head_commit(checkout),
        "registration": registration,
        "run_manifest": json.loads(manifest_raw),
        "registration_file_sha256": registration_sha,
        "run_manifest_file_sha256": manifest_sha,
        "data_config_sha256": hashlib.sha256(
            (checkout / DATA_PINS["config_path"]).read_bytes()
        ).hexdigest(),
        "registration_read": refusal(v4_registration.read_registration, registration_raw),
        "run_manifest_read": refusal(v4_registration.read_manifest, manifest_raw),
        "cells": registration["cells"],
        "registered_cells": list(v4_registration.registered_cells()),
        "cell_specs": [
            [cell.arm, str(cell.capital), str(cell.cost_multiple)] for cell in all_cells()
        ],
        "changed_since": list(changed_since(checkout, code_pin)),
        "world_errors": v4_registration.world_errors(checkout, "registered", code_pin),
        "trial_errors": v4_registration.trial_errors(
            checkout,
            revision,
            code_pin=code_pin,
            registration_sha256=registration_sha,
            manifest_sha256=manifest_sha,
        ),
    }
    try:
        gated = v4_registration.gate(checkout, "registered", registration_sha)
    except v4_registration.GateError as exc:
        facts["gate_errors"], facts["gate"] = list(exc.errors), None
    else:
        facts["gate_errors"] = []
        facts["gate"] = {
            "head": gated.head,
            "registration_sha256": gated.registration_sha256,
            "outputs": [list(pair) for pair in v4_registration.github_outputs(gated)],
        }
    try:
        facts["check_ready"] = trial_register.check_ready(checkout, TRIAL_ID, revision)
    except ValueError as exc:
        facts["check_ready"] = f"{type(exc).__name__}: {exc}"
    events = trial_register.load_events(checkout / TRIAL_REGISTER)
    facts["registration_event"] = next(
        (event for event in events if event["event_id"] == REGISTRATION_EVENT), None
    )
    facts["v4_completions"] = [
        event["trial_id"]
        for event in events
        if event["family"] == FAMILY and event["event_type"] == "completion"
    ]
    return facts


if __name__ == "__main__":
    sys.stdout.write(json.dumps(_facts(Path(sys.argv[1]), sys.argv[2]), sort_keys=True) + "\n")
