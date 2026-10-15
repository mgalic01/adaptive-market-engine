"""The committed V3.1 registration (Task 11) passes every gate of the registered run, for good.

The registration is three commits (Rulings R4-1, TC-5 and TC-6):

1. the V3.1 trial's registration event in ``docs/trials/register.jsonl``, with the V3
   bootstrap-seed test reading V3's own registration;
2. the code pin: main's reviewed code unchanged, plus this test, the CI job's full-history
   checkout and the experiment menu's status set at the owner's go;
3. the registration artifacts (``config/v3_1_run_manifest.json``,
   ``config/v3_1_registration.json``) with the trial's completion and the review.

This test belongs to the code pin, because after the pin only registration artifacts may
change (``run_cell.REGISTRATION_ARTIFACTS``, Ruling P10c): a test added later would make
every registered job's gate refuse. So it is written before the registration exists:

- while HEAD commits no ``config/v3_1_registration.json`` (at the code pin itself), and
  outside a git checkout, it skips;
- once HEAD commits it, it never skips. A registration present but broken fails, and so
  does a checkout whose history is too shallow to check it: the CI job fetches the whole
  history for it (``fetch-depth: 0`` in ``.github/workflows/quality.yml``).

Every check runs at the commit that introduced the registration, the last commit that
changed ``config/v3_1_registration.json``, never at the moving HEAD: code changes land on
main after the registered run, and a check of HEAD's changes since the code pin would
then fail for good. The checks run in a subprocess on a scratch checkout of that commit
(sharing this repository's objects through git alternates), with that commit's own
``src/`` and ``scripts/`` first on the import path, so later changes to the driver can
neither break nor weaken them. The subprocess is this file run as a script; it prints one
JSON document of facts, which the tests below compare with the values the registration
was built from: main at ``BASE``, the prepare-only output (GitHub runs 38620166885 at
780636f and 38655808728 at 5357674, identical but for ``code_commit``) and the owner's
plan. Nothing here reads market data or touches the network.
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
REGISTRATION = "config/v3_1_registration.json"
RUN_MANIFEST = "config/v3_1_run_manifest.json"
PREPARE_CONFIG = "config/v3_1_prepare.json"
TRIAL_REGISTER = "docs/trials/register.jsonl"
REVIEW = "docs/reviews/2026-10-15-claude-v3-1-registration.md"
FAMILY = "spec-v3.1"
TRIAL_ID = "v3-1-registered-1"
REGISTRATION_EVENT = f"{TRIAL_ID}-record"
COMPLETION_EVENT = f"{TRIAL_ID}-complete"
# Main when the registration was built: the run driver (#269), the launch protection
# (#281, #282), the prepare config (#283), the head-SHA fix (#280) and the owner's three
# USDT capitals (#284). The code pin must hold exactly its code.
BASE = "5357674bc3f612b7970e0a356113e8aef2032e7f"
SPEC = {
    "path": "docs/superpowers/specs/2026-10-10-v3-1-design.md",
    "commit": BASE,
    "sha256": "dbf3b23222cef3eb36e5e8f337cb424b1917d3b23a2ce34a5f1bead64cbfca5d",
}
# The prepare-only output's pins, which the run-manifest must hold.
PREPARE_SHA256 = "71954170e9ebd35be5af1b199147df6f18e4b905912642e9d8ea961a02ce8293"
DATA_MANIFESTS = {
    "config/datasets/full-range-2017-2024.manifest.json": (
        "069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e"
    ),
    "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.manifest.json": (
        "c2582815d56b3eec2fd3468002c0e3fe6c09914fb967ac7faba31392b109966a"
    ),
    "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.manifest.json": (
        "589b9a8c493240e24f24900e8c9b81f43a4330bd652c4c8ebf628c7c5403444d"
    ),
    "config/datasets/v3-20261009/inventory.manifest.json": (
        "78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a"
    ),
}
FILTER_SNAPSHOTS = {
    "config/datasets/v3-20261009/snapshots/futures.json": (
        "db6a0c5bde5fc247224826f26be78729da74eecd2bc419a93728f255fd9244f4"
    ),
    "config/datasets/v3-20261009/snapshots/spot.json": (
        "d5dbeeb908dde49269e7e654359b59981e7958636b2ed61103999bdec826b05d"
    ),
}
WINDOW_PACKS = {
    "w0": "16e4cce6c426944c3a38a411baa136ef5f6126412adbe31db38a43e6be44683c",
    "w1": "1bc5feea67af4aa978e11ed6deb6947d35721c8de24008665b65e2b75f3341fd",
}
V3_PACK_SHA256 = "8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee"
# Each window's skipped hours as prepare derived them: the count, and the SHA-256 of
# the list as compact JSON (json.dumps(hours, separators=(",", ":"))).
SKIPPED_HOURS = {
    "w1": (140, "da437e05e9cae6cf85e50342fe5cabdaec8bad363b5ea52b14c115196564917c"),
    "w0": (159, "21a621d5bef899136cdfe7ce4ed7f5f92a19685b19418d110573d9a904fda769"),
}
WINDOWS = {"w1": (1_625_097_600_000, 1_735_689_600_000)}
REPORTED_WINDOWS = {"w0": (1_583_020_800_000, 1_735_689_600_000)}
CAPITALS = [
    ["research", "USDT", "10000", "10000"],
    ["medium", "USDT", "1000", "1000"],
    ["small", "USDT", "100", "100"],
]
COST_PROFILES = [
    [1, "080ebaee2ff778dd082d3a15e868da3c2e55d6dbb20e7f718706e2e394e41c76"],
    [2, "b99eb4ad4f3458f8d501be30fe53aab695906117478884bdcdff2e42a5c3af1e"],
]
MATRICES = {"v3_cells": 6, "minute_cells": 144, "main_cells": 174}
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
    ``trial_register.check_ready`` digests (``src/``, ``scripts/`` and the packaging
    files)."""
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
    """The commit that introduced the committed registration; skips while there is none."""
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
            "this checkout's history is shallow, so the registration's code pin and trial "
            "events cannot be read; check out the whole history (fetch-depth: 0)"
        )
    return _git(ROOT, "log", "-1", "--format=%H", "HEAD", "--", REGISTRATION).strip()


def _scratch_checkout(directory: Path, revision: str) -> Path:
    """A checkout of ``revision`` in ``directory``, sharing this repository's objects
    (git alternates), with the bytes of every blob as committed."""
    objects = _git(ROOT, "rev-parse", "--path-format=absolute", "--git-path", "objects").strip()
    _git(directory.parent, "init", "-q", str(directory))
    # Bytes, not text: a text write on Windows would end the path in "\r".
    (directory / ".git/objects/info/alternates").write_bytes(f"{objects}\n".encode())
    for key, value in (("core.autocrlf", "false"), ("core.longpaths", "true")):
        _git(directory, "config", key, value)
    _git(directory, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", revision)
    return directory


@pytest.fixture(scope="module")
def committed(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """The facts the registration's own commit gives, from its own code (``_facts``)."""
    revision = _introducing_commit()
    checkout = _scratch_checkout(tmp_path_factory.mktemp("v31-registration") / "repo", revision)
    done = subprocess.run(  # nosec B603: this file, run by this interpreter, no shell
        [sys.executable, "-E", "-P", str(Path(__file__).resolve()), str(checkout), revision],
        capture_output=True,
        check=False,
    )
    stderr = done.stderr.decode("utf-8", "replace")
    assert done.returncode == 0, f"the registration's checks crashed:\n{stderr}"
    facts: dict[str, Any] = json.loads(done.stdout)
    if facts["load_registration"] is not None:
        pytest.fail(f"the committed registration does not load: {facts['load_registration']}")
    facts["revision"], facts["checkout"] = revision, checkout
    return facts


def test_the_checks_run_the_registrations_own_code(committed: dict[str, Any]) -> None:
    checkout = Path(committed["checkout"]).resolve()
    for module in ("crypto_grid_bot", "v31_driver", "trial_register"):
        assert Path(committed["modules"][module]).resolve().is_relative_to(checkout), module
    assert committed["head"] == committed["revision"]


def test_the_registration_loads_and_carries_the_owners_plan(committed: dict[str, Any]) -> None:
    assert committed["check_registration"] is None
    assert committed["owner_plan_errors"] == []
    assert committed["plan_gate"] is None
    assert committed["windows"] == {k: list(v) for k, v in WINDOWS.items()}
    assert committed["reported_windows"] == {k: list(v) for k, v in REPORTED_WINDOWS.items()}
    assert committed["capitals"] == CAPITALS  # the three USDT capitals, in cell order, no FX
    assert committed["cost_profiles"] == COST_PROFILES
    assert committed["v1_variants"] == ["a", "b", "c", "e", "f", "g", "cg", "h", "ch"]
    assert committed["prepare_config_sha256"] == committed["prepare_pin"] == PREPARE_SHA256


def test_the_cells_are_the_324_required_cells_in_three_matrices(committed: dict[str, Any]) -> None:
    cells = committed["cells"]
    assert committed["cells_equal_required"] is True
    assert len(cells) == len({cell["cell_id"] for cell in cells}) == 324
    by_kind = Counter((cell["window"], cell["kind"]) for cell in cells)
    assert by_kind == {
        ("w1", "v31"): 120,
        ("w1", "v3"): 42,
        ("w1", "hold"): 6,
        ("w1", "minute"): 144,
        ("w0", "v31"): 12,
    }
    assert Counter(cell["capital_id"] for cell in cells) == {
        "research": 108,
        "medium": 108,
        "small": 108,
    }
    assert all(cell["reported_only"] == (cell["window"] == "w0") for cell in cells)
    assert {cell["arm"] for cell in cells if cell["window"] == "w0"} == {"combined"}
    assert committed["matrices"] == MATRICES
    plan = committed["plan"]
    assert "refused" not in plan, plan["refused"]
    assert {name: len(plan[name]) for name in MATRICES} == MATRICES
    assert plan["cells_registered"] == plan["cells_planned"] == 324
    assert plan["mode"] == "registered"
    assert plan["code_pin"] == committed["code_pin"]
    assert plan["repo_head"] == committed["revision"]
    assert plan["registration_sha256"] == committed["config_pin"]


def test_the_run_manifest_and_skipped_hours_are_the_prepare_outputs(
    committed: dict[str, Any],
) -> None:
    manifest = committed["run_manifest"]
    assert manifest["data_manifests"] == DATA_MANIFESTS
    assert manifest["filter_snapshots"] == FILTER_SNAPSHOTS
    assert manifest["window_packs"] == WINDOW_PACKS
    assert manifest["v3_pack_sha256"] == V3_PACK_SHA256
    assert manifest["prepare_sha256"] == PREPARE_SHA256
    assert committed["run_manifest_file_sha256"] == committed["run_manifest_pin"]
    assert committed["skipped_hours"] == {k: list(v) for k, v in SKIPPED_HOURS.items()}


def test_the_code_pin_is_mains_reviewed_code(committed: dict[str, Any]) -> None:
    """The code pin holds exactly main's code at ``BASE`` (nothing under ``src/`` or
    ``scripts/`` and no packaging file differs), descends from it, and every arm's
    adapter pin is the one ``adapter_pins`` reads there and at the registration commit."""
    code_pin = committed["code_pin"]
    assert _run_git(ROOT, "merge-base", "--is-ancestor", BASE, code_pin).returncode == 0
    assert _code_entries(ROOT, code_pin) == _code_entries(ROOT, BASE)
    registered = committed["adapter_pins"]["registered"]
    assert len(registered) == 42
    for where in ("code_pin", "base", "head"):
        assert committed["adapter_pins"][where] == registered, where


def test_the_v31_trial_authorizes_the_registration(committed: dict[str, Any]) -> None:
    """``trial_register.check_ready`` passes for the trial at the registration commit, and
    its completion binds the code pin, the registration and the run-manifest
    (``v31_driver.trial_errors``)."""
    revision, code_pin = committed["revision"], committed["code_pin"]
    assert committed["trial_errors"] == []
    assert committed["spec_v31_completions"] == [TRIAL_ID]
    completion = committed["check_ready"]
    assert isinstance(completion, dict), completion
    assert completion["event_id"] == COMPLETION_EVENT
    assert completion["family"] == FAMILY
    payload = completion["payload"]
    assert payload["registration_id"] == REGISTRATION_EVENT
    assert payload["code_commit"] == code_pin
    assert payload["config"] == {"path": REGISTRATION, "sha256": committed["config_pin"]}
    assert payload["manifest"] == {"path": RUN_MANIFEST, "sha256": committed["run_manifest_pin"]}
    assert payload["review"] == REVIEW
    assert _run_git(ROOT, "cat-file", "-e", f"{revision}:{REVIEW}").returncode == 0
    event = committed["registration_event"]
    assert event["family"] == FAMILY and event["parent_trial_id"] is None
    assert event["payload"]["spec"] == SPEC
    assert event["payload"]["preregistered"] is True
    # The registration event is in the code pin's first parent, unchanged at the
    # registration commit: the register only grew by appends since main.
    earlier = _git_bytes(ROOT, "show", f"{code_pin}^1:{TRIAL_REGISTER}")
    later = _git_bytes(ROOT, "show", f"{revision}:{TRIAL_REGISTER}")
    base = _git_bytes(ROOT, "show", f"{BASE}:{TRIAL_REGISTER}")
    assert later.startswith(earlier) and earlier.startswith(base) and earlier != base


def test_the_job_gate_passes_at_the_registration(committed: dict[str, Any]) -> None:
    """The registered jobs' gates on the registration commit: ``job_gate`` returns the
    head, ``world_gate`` admits a registered run, and every path changed since the code
    pin is a registration artifact (``run_cell._path_errors``)."""
    assert committed["job_gate"] == committed["revision"]
    assert committed["world_gate"] is None
    changed = committed["changed_since"]
    assert committed["path_errors"] == []
    assert {REGISTRATION, RUN_MANIFEST, TRIAL_REGISTER, REVIEW} <= set(changed)


def _facts(checkout: Path, revision: str) -> dict[str, object]:
    """Run in a subprocess (``__main__``) on the scratch checkout of the registration
    commit, with that commit's ``src/`` and ``scripts/`` first on the import path: every
    gate and loader of the registered run, as each registered job calls them, and the
    values they read. A refusal is recorded as its message, never raised past here once
    the registration has loaded."""
    sys.path[:0] = [str(checkout / "src"), str(checkout / "scripts")]
    import trial_register
    import v31_driver

    import crypto_grid_bot
    from crypto_grid_bot.combined.driver.owner_plan import owner_plan_errors
    from crypto_grid_bot.combined.driver.registration import (
        adapter_pins,
        check_registration,
        load_prepare_config,
        load_registration,
        required_cells,
    )
    from crypto_grid_bot.combined.driver.run_cell import (
        _path_errors,
        changed_since,
        head_commit,
    )

    def refusal(call: Any) -> str | None:
        try:
            call()
        except Exception as exc:  # recorded for the assertion, which names it
            return f"{type(exc).__name__}: {exc}"
        return None

    facts: dict[str, object] = {
        "modules": {
            "crypto_grid_bot": crypto_grid_bot.__file__,
            "v31_driver": v31_driver.__file__,
            "trial_register": trial_register.__file__,
        },
        "head": head_commit(checkout),
    }
    try:
        reg = load_registration(
            checkout / REGISTRATION, checkout / RUN_MANIFEST, repo_root=checkout
        )
    except Exception as exc:
        facts["load_registration"] = f"{type(exc).__name__}: {exc}"
        return facts
    facts["load_registration"] = None
    registration = reg.registration
    prepare = load_prepare_config(checkout / PREPARE_CONFIG)
    manifest_sha = hashlib.sha256((checkout / RUN_MANIFEST).read_bytes()).hexdigest()
    code_pin = registration.code_pin
    facts.update(
        {
            "code_pin": code_pin,
            "config_pin": registration.config_pin,
            "run_manifest_pin": reg.run_manifest_pin,
            "run_manifest_file_sha256": manifest_sha,
            "prepare_pin": reg.prepare_pin,
            "prepare_config_sha256": prepare.sha256,
            "check_registration": refusal(lambda: check_registration(reg)),
            "owner_plan_errors": owner_plan_errors(prepare, reg),
            "plan_gate": refusal(
                lambda: v31_driver.plan_gate("registered", checkout / PREPARE_CONFIG, reg)
            ),
            "world_gate": refusal(lambda: v31_driver.world_gate(checkout, "registered", code_pin)),
            "windows": {w.id: [w.start_ms, w.end_ms] for w in registration.windows},
            "reported_windows": {w.id: [w.start_ms, w.end_ms] for w in reg.reported_windows},
            "skipped_hours": {
                w.id: [
                    len(w.skipped_hours),
                    hashlib.sha256(
                        json.dumps(list(w.skipped_hours), separators=(",", ":")).encode("ascii")
                    ).hexdigest(),
                ]
                for w in (*registration.windows, *reg.reported_windows)
            },
            "capitals": [
                [c.id, c.currency, str(c.amount), str(c.initial_equity)]
                for c in registration.capitals
            ],
            "cost_profiles": [list(profile) for profile in registration.cost_profiles],
            "v1_variants": list(registration.v1_variants),
            "cells": [
                {
                    "cell_id": c.cell_id,
                    "arm": c.arm,
                    "window": c.window,
                    "capital_id": c.capital_id,
                    "kind": c.kind,
                    "reported_only": c.reported_only,
                }
                for c in reg.cells
            ],
            "cells_equal_required": reg.cells == required_cells(reg),
            "matrices": {
                name: len(ids) for name, ids in v31_driver.matrix_cells(reg.cells).items()
            },
            "run_manifest": json.loads((checkout / RUN_MANIFEST).read_bytes()),
            "adapter_pins": {
                "registered": dict(registration.adapter_pins),
                "code_pin": adapter_pins(checkout, code_pin),
                "base": adapter_pins(checkout, BASE),
                "head": adapter_pins(checkout, head_commit(checkout)),
            },
        }
    )
    changed = changed_since(checkout, code_pin)
    facts["changed_since"] = list(changed)
    facts["path_errors"] = _path_errors(changed)
    facts["trial_errors"] = v31_driver.trial_errors(
        checkout,
        revision,
        code_pin=code_pin,
        config_sha256=registration.config_pin,
        manifest_sha256=reg.run_manifest_pin,
    )
    try:
        facts["check_ready"] = trial_register.check_ready(checkout, TRIAL_ID, revision)
    except Exception as exc:
        facts["check_ready"] = f"{type(exc).__name__}: {exc}"
    events = trial_register.load_events(checkout / TRIAL_REGISTER)
    facts["registration_event"] = next(
        (event for event in events if event["event_id"] == REGISTRATION_EVENT), None
    )
    facts["spec_v31_completions"] = [
        event["trial_id"]
        for event in events
        if event["family"] == FAMILY and event["event_type"] == "completion"
    ]
    try:
        facts["job_gate"] = v31_driver.job_gate(
            reg,
            checkout,
            registration_sha256=registration.config_pin,
            manifest_sha256=manifest_sha,
        )
    except Exception as exc:
        facts["job_gate"] = f"{type(exc).__name__}: {exc}"
    arguments = [
        "plan",
        "--repo",
        str(checkout),
        "--registration-sha256",
        registration.config_pin,
    ]
    try:
        facts["plan"] = v31_driver.plan(v31_driver.build_parser().parse_args(arguments))
    except Exception as exc:
        facts["plan"] = {"refused": f"{type(exc).__name__}: {exc}"}
    return facts


if __name__ == "__main__":
    sys.stdout.write(json.dumps(_facts(Path(sys.argv[1]), sys.argv[2]), sort_keys=True) + "\n")
