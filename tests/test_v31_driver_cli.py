"""The V3.1 driver CLI: gated subcommands and the offline smoke mode.

Synthetic only, and the network is blocked for the whole module, at two levels:

- a module-scoped block that is live from the module's first fixture to its last.
  Every module-scoped fixture depends on it, so it already holds while those fixtures
  build their worlds and run prepare (they are set up before any function-scoped
  fixture);
- the function-scoped block every test also gets, as in tests/test_v31_fetch.py.

``test_the_network_block_covers_module_scoped_fixtures`` shows the first one is in force
inside a module-scoped fixture. Prepare's archives come from in-memory fake hosts
(``v31_smoke.Archives``), one per transport, always passed explicitly. Two kinds of world,
each a tiny git repository:

- the smoke world (``v31_smoke.build_world``), with stub modules committed so that the
  adapter pins read real blob ids at its code pin, and its registration committed on top
  with the synthetic V3.1 trial's completion (the trial gate): picks, run-cell and
  aggregate run on it;
- a prepare world: a synthetic V3 inventory (spot, futures and funding archives, one
  excluded and one missing month), a legacy dataset whose minutes and hours agree, so the
  frozen mask job runs for real (one BTC hour lacks a minute, so its mask holds it), an
  XRP hour priced so that its quotes break rule 8, a V3.1 minute manifest, filter
  snapshots, and V3's trial and the synthetic V3.1 trial's registration in the trial
  register.

V3's walk-forward, and in the smoke world the frozen mask job, run as the smoke's
stand-ins (``v31_smoke.stand_ins``); the V3 input pack builder, whose V3 loader needs the
full 2710-entry inventory, is replaced in the prepare tests by a recording builder.

The owner's plan (``owner_plan.OWNER_PLAN``: W1 2021-07 to 2025 on ten coins, W0 from
2020-03 on eight, the 2024-12-31 FX fixing) is far beyond what a test can synthesize, so a
real-mode test on one of these worlds stands the world's own plan in for it
(``smoke_plan``, ``prepare_plan``, ``stand_in_plan``). The plan refusals
(``test_every_real_mode_refuses_any_plan_but_the_owners``) run under the owner's own plan,
and so do the smoke and the rehearsal, which keep their synthetic plans by mode.
"""

import argparse
import contextlib
import hashlib
import io
import json
import re
import shutil
import socket
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest
from test_v31_registration import MODULES

from crypto_grid_bot.backtest.dataset import (
    fetch_dataset,
    load_manifest,
    load_spec,
    verify_dataset,
    write_manifest,
)
from crypto_grid_bot.backtest.jobs import manifest_path
from crypto_grid_bot.backtest.klines import Kline, aggregate, month_bounds_ms
from crypto_grid_bot.backtest.masking import tick_limit_quotes
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.driver import owner_plan, run_baselines
from crypto_grid_bot.combined.driver.aggregate import _CLAIMED_ATTEMPT
from crypto_grid_bot.combined.driver.packs import read_pack
from crypto_grid_bot.combined.driver.registration import (
    FilePin,
    PrepareConfig,
    PrepareWindow,
    adapter_pins,
    load_prepare_config,
)
from crypto_grid_bot.combined.driver.run_baselines import MINUTE_MANIFEST_PATH, MINUTE_SPEC_PATH
from crypto_grid_bot.combined.driver.v3_pack import read_v3_pack, write_v3_pack
from crypto_grid_bot.market_data.client import FeedError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v31_driver  # noqa: E402
import v31_smoke  # noqa: E402
from fetch_v3_data import ArchiveObject, inspect_archive  # noqa: E402
from fetch_v3_data import archive_path as inventory_path_of  # noqa: E402
from trial_register import append_event  # noqa: E402

HOUR = 3_600_000
DAY = 24 * HOUR
MINUTE = 60_000
RESERVED = 1_735_689_600_000
RUN = "38267478452-attempt-1"  # what the workflow passes: <run_id>-attempt-<run_attempt>
CELL = "w1.combined.olhc.c1.research"
KIND_CELLS = {
    "v31": "w1.combined.olhc.c1.research",
    "hold": "w1.matched_spot_hold.native.c2.owner_small",
    "v3": "w1.unchanged_v3_selector.native.c1.research",
    "minute": "w1.matched_v1_g_grid_low_first.native.c1.research",
}


GITHUB_VARIABLES = ("GITHUB_TOKEN", "GITHUB_REPOSITORY", "GITHUB_RUN_ID")


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def block_network(patch: pytest.MonkeyPatch) -> None:
    """Make every name lookup and every connection raise ``NetworkBlocked``."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    patch.setattr(socket, "getaddrinfo", refuse)
    patch.setattr(socket, "create_connection", refuse)
    patch.setattr(socket.socket, "connect", refuse)
    patch.setattr(socket.socket, "connect_ex", refuse)


@pytest.fixture(scope="module", autouse=True)
def module_network_blocked():
    """The network is blocked for the whole module: the module-scoped fixtures depend on
    this, so it already holds while they build their worlds and run prepare."""
    with pytest.MonkeyPatch.context() as patch:
        block_network(patch)
        yield


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket. Nor does it hold the
    runner's variables for GitHub's API: without them the dispatch check (a registered
    aggregate's) refuses before any request; a test of the check sets its own."""
    block_network(monkeypatch)
    for name in GITHUB_VARIABLES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def module_probe(module_network_blocked) -> dict:
    """What a module-scoped fixture meets when it opens the network: each attempt's
    exception (a ``.invalid`` name, so nothing could be reached even unblocked)."""

    def connect():
        with socket.socket() as stream:
            stream.settimeout(1)
            stream.connect(("192.0.2.1", 443))  # TEST-NET-1: never routed

    seen = {}
    attempts = {
        "getaddrinfo": lambda: socket.getaddrinfo("v31-driver.invalid", 443),
        "create_connection": lambda: socket.create_connection(("v31-driver.invalid", 443), 1),
        "connect": connect,
    }
    for name, attempt in attempts.items():
        try:
            attempt()
        except Exception as exc:
            seen[name] = exc
        else:
            seen[name] = None
    return seen


def test_the_network_block_covers_module_scoped_fixtures(module_probe):
    assert set(module_probe) == {"getaddrinfo", "create_connection", "connect"}
    assert all(isinstance(exc, NetworkBlocked) for exc in module_probe.values()), module_probe


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def run(argv, capsys, **options):
    """``main(argv)``: its exit status, its stdout document (or None) and its stderr."""
    code = v31_driver.main(argv, **options)
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if code == 0 else None), captured.err


def quietly(argv, **options):
    """``main(argv)`` outside a test's capsys: (status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = v31_driver.main(argv, **options)
    return code, out.getvalue(), err.getvalue()


def stand_in_plan(windows: dict, symbols) -> owner_plan.OwnerPlan:
    """A synthetic world's own plan (its windows, each on ``symbols``, and the owner's FX
    date), standing in for the owner's while a real mode runs on that world."""
    return owner_plan.OwnerPlan(
        tuple(
            owner_plan.PlanWindow(wid, start, end, frozenset(symbols))
            for wid, (start, end) in windows.items()
        ),
        owner_plan.OWNER_PLAN.fx_reference_date,
    )


SMOKE_PLAN = stand_in_plan(v31_smoke.WINDOWS, v31_smoke.SYMBOLS)


@pytest.fixture
def smoke_plan(monkeypatch):
    """A real-mode test on the smoke world: its plan stands in for the owner's."""
    monkeypatch.setattr(owner_plan, "OWNER_PLAN", SMOKE_PLAN)


# --- the smoke mode ---------------------------------------------------------------------


def test_smoke_runs_end_to_end_offline(tmp_path, capsys):
    original = (baseline_v3.run_walk_forward, run_baselines.mask_job)
    code, document, err = run(["smoke", "--out", str(tmp_path / "s"), "--cells", "6"], capsys)
    assert code == 0, err

    summary = tmp_path / "s" / "a" / "summary"
    verdict = json.loads((summary / "verdict.json").read_bytes())
    assert verdict["status"] in ("pass", "fail", "incomplete")
    # Six of the 216 registered cells ran, so acceptance cannot pass: incomplete, not a crash.
    assert document["status"] == verdict["status"] == "incomplete"
    assert document["verdict_sha256"] == sha((summary / "verdict.json").read_bytes())
    assert (document["cells_registered"], document["cells_run"]) == (216, 6)
    assert len(verdict["cells"]) == 216
    completed = {cell for cell, read in verdict["cells"].items() if read["state"] == "completed"}
    # The first W1 cell of each kind (the V3 selector and a fixed long-only V3 rule both)
    # and the first W0 cell; each completed, as did the picks job. The rest were never run.
    assert completed == {
        "w1.spot_trend.olhc.c1.research",
        "w1.matched_spot_hold.native.c1.research",
        "w1.unchanged_v3_selector.native.c1.research",
        "w1.unchanged_v3_r1_long_only.native.c1.research",
        "w1.matched_v0_grid_high_first.native.c1.research",
        "w0.combined.olhc.c1.research",
    }
    assert verdict["mode"] == "smoke"
    assert {read["state"] for cell, read in verdict["cells"].items() if cell not in completed} == {
        "missing"
    }
    assert verdict["v3_picks"]["state"] == "completed"
    # The prepare-equivalent document: W1's derived skipped hour, its labelled sources (the
    # extra sources run on the synthetic legacy dataset), W0 without extra sources.
    prepared = document["prepare"]
    assert prepared["skipped_hours"]["w1"]["hours"] == [v31_smoke.GAP]
    assert prepared["skipped_hours"]["w1"]["sources"] == {
        "BTCUSDT: no spot bar": [v31_smoke.GAP],
        "minute_mask:BTCUSDT": [],
        "minute_mask:ETHUSDT": [],
        "minute_mask:XRPUSDT": [],
        "quote_test:XRPUSDT": [],
    }
    assert prepared["skipped_hours"]["w0"] == {"hours": [], "sources": {}}
    assert len(document["stand_ins"]) == 2  # disclosed
    assert (baseline_v3.run_walk_forward, run_baselines.mask_job) == original  # restored
    # Under the owner's real plan (in force here), which the smoke's synthetic plan is not:
    # the smoke passes no plan gate.
    smoke_config = load_prepare_config(tmp_path / "s" / "repo" / "config/v3_1_prepare.json")
    assert owner_plan.OWNER_PLAN.windows[0].start_ms == owner_plan.W1_START_MS
    assert owner_plan.owner_plan_errors(smoke_config)
    # Nothing is replaced: a second smoke into the same directory is refused.
    code, _, err = run(["smoke", "--out", str(tmp_path / "s"), "--cells", "1"], capsys)
    assert code == 1 and "exists" in err


# --- a registered world: picks, run-cell and aggregate -----------------------------------


@dataclass(frozen=True)
class Registered:
    repo: Path
    head: str
    code_pin: str
    packs: Path
    legacy: Path
    config_sha: str
    pins: dict
    window_packs: dict


# What a registration commit changes since its code pin: the registration, its run-manifest
# and the trial register with the V3.1 trial's completion.
REGISTRATION_CHANGES = (
    "config/v3_1_registration.json",
    "config/v3_1_run_manifest.json",
    "docs/trials/register.jsonl",
)


@pytest.fixture(scope="module")
def registered(module_network_blocked, tmp_path_factory) -> Registered:
    """The smoke world with stub modules committed on top of the synthetic V3.1 trial's
    registration, its packs, and a registration whose code pin is that commit and whose
    adapter pins are its, committed with the trial's completion as Task 11 commits the
    real one (the trial gate reads them as the head commits them)."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path_factory.mktemp("cli")
    with v31_smoke.stand_ins():
        world = v31_smoke.build_world(root, extra_files=MODULES, trial=True)
        document = v31_driver.smoke_packs(world, root / "packs")
    pins = adapter_pins(world.repo, world.head)
    reg, config_sha = v31_smoke.register(world, document, code_pin=world.head, adapter_pins=pins)
    v31_smoke.complete_trial(
        world.repo,
        code_pin=world.head,
        config_sha256=config_sha,
        manifest_sha256=reg.run_manifest_pin,
    )
    head = v31_smoke.commit_all(world.repo, "the registration (synthetic)")
    window_packs = dict(reg.run_manifest.window_packs)
    return Registered(
        world.repo, head, world.head, root / "packs", world.legacy, config_sha, pins, window_packs
    )


def registered_args(world: Registered, command: str, *extra: str, repo=None, sha=None):
    return [
        command,
        "--repo",
        str(world.repo if repo is None else repo),
        "--registration-sha256",
        world.config_sha if sha is None else sha,
        *extra,
    ]


def changed_copy(world: Registered, tmp_path: Path) -> Path:
    """A copy of the world's repository with a code change committed after the code pin."""
    copy = tmp_path / "repo"
    shutil.copytree(world.repo, copy)
    (copy / "src/crypto_grid_bot/combined/engine.py").write_bytes(b"ENGINE = 2\n")
    v31_smoke.commit_all(copy, "a code change after the code pin")
    return copy


def test_run_cell_refuses_without_the_gate(registered, smoke_plan, tmp_path, capsys, monkeypatch):
    out = tmp_path / "out"

    def attempt(cell=CELL, packs=registered.packs, **options):
        extra = ("--cell", cell, "--packs", str(packs), "--attempt-id", RUN, "--out", str(out))
        return run(registered_args(registered, "run-cell", *extra, **options), capsys)

    # Another registration than the dispatch pinned.
    code, _, err = attempt(sha="0" * 64)
    assert code == 1 and f"execution gate refused cell {CELL!r}" in err
    assert "differs from the config pin" in err
    # A cell the registration does not list.
    code, _, err = attempt(cell="w1.combined.olhc.c3.research")
    assert code == 1 and "not a registered cell" in err
    # A pack other than the pinned one: the gate's pin is the one the pack is read against.
    wrong = tmp_path / "packs"
    wrong.mkdir()
    shutil.copyfile(registered.packs / "window-w0.pack.json.gz", wrong / "window-w1.pack.json.gz")
    code, _, err = attempt(packs=wrong)
    assert code == 1 and f"differs from the pinned {registered.window_packs['w1']}" in err
    # Code changed after the code pin: the V3.1 trial's completion no longer covers the
    # head's code, so the trial gate refuses first, before the pack is read.
    copy = changed_copy(registered, tmp_path)
    code, _, err = attempt(repo=copy)
    assert code == 1 and f"trial gate refused cell {CELL!r}" in err
    assert "committed code does not match pin" in err
    # The execution gate refuses it too, on its own: the changed path and the moved
    # adapter pin, both named (the trial gate stood down to show it).
    monkeypatch.setattr(v31_driver, "trial_errors", lambda *args, **kwargs: [])
    code, _, err = attempt(repo=copy)
    assert code == 1 and f"execution gate refused cell {CELL!r}" in err
    assert "outside the registration artifacts: src/crypto_grid_bot/combined/engine.py" in err
    assert "the adapter pin of combined at the checkout" in err
    assert not out.exists()  # nothing was written for any refused run


def test_each_cell_kind_runs_through_the_execution_gate(
    registered, smoke_plan, tmp_path, capsys, monkeypatch
):
    calls = []

    def spy(reg, cell_id, **arguments):
        calls.append((cell_id, arguments))
        return gate(reg, cell_id, **arguments)

    gate = v31_driver.execution_gate
    monkeypatch.setattr(v31_driver, "execution_gate", spy)
    handed = []
    job = v31_driver.run_cell_job

    def job_spy(cell, pack, *args, **kwargs):
        handed.append((cell.kind, pack))
        return job(cell, pack, *args, **kwargs)

    monkeypatch.setattr(v31_driver, "run_cell_job", job_spy)
    cells = tmp_path / "cells"
    packs = ("--packs", str(registered.packs), "--attempt-id", RUN)
    with v31_smoke.stand_ins():
        # The picks job prints the SHA-256 of its completion marker, for the job output.
        argv = registered_args(registered, "picks", *packs, "--out", str(tmp_path / "p"))
        code, document, err = run(argv, capsys)
        assert code == 0, err
        picks = tmp_path / "p" / "v3_picks"
        assert document == {
            "job": "v3_picks",
            "attempt_id": "38267478452-v3_picks-attempt-1",
            "repo_head": registered.head,
            "directory": str(picks),
            "outcome_sha256": sha((picks / "outcome.json").read_bytes()),
        }
        assert (
            json.loads((picks / "attempt.json").read_bytes())["attempt_id"]
            == document["attempt_id"]
        )
        for kind, cell_id in KIND_CELLS.items():
            extra = {
                "v3": ("--picks", str(picks)),
                "minute": ("--legacy-data", str(registered.legacy)),
            }
            out = cells / f"cell-{cell_id}-attempt-1"  # as the workflow will download it
            argv = registered_args(
                registered,
                "run-cell",
                "--cell",
                cell_id,
                *packs,
                "--out",
                str(out),
                *extra.get(kind, ()),
            )
            code, document, err = run(argv, capsys)
            assert code == 0, err
            directory = out / cell_id
            assert document == {
                "cell_id": cell_id,
                "kind": kind,
                "attempt_id": f"38267478452-{cell_id}-attempt-1",
                "repo_head": registered.head,
                "directory": str(directory),
                "outcome_sha256": sha((directory / "outcome.json").read_bytes()),
            }
            claim = json.loads((directory / "attempt.json").read_bytes())
            assert (claim["attempt_id"], claim["repo_head"]) == (
                document["attempt_id"],
                registered.head,
            )
    # A minute or V3 cell runs without the window pack once the gate has checked it, so
    # the pack's memory is freed (Ruling F8); a V3.1 or hold cell replays it.
    assert [(kind, pack is None) for kind, pack in handed] == [
        ("v31", False),
        ("hold", False),
        ("v3", True),
        ("minute", True),
    ]
    # The gate ran before each cell, on the W1 pack read against the pin it checked, with
    # the head, only the registration commit's changes since the code pin, the head's
    # adapter pins and the dispatch's pin.
    assert [cell_id for cell_id, _ in calls] == list(KIND_CELLS.values())
    for _, arguments in calls:
        assert arguments["pack_sha256"] == registered.window_packs["w1"]
        assert arguments["pack"].window_id == "w1"
        assert (arguments["repo_head"], arguments["changed_paths"]) == (
            registered.head,
            REGISTRATION_CHANGES,
        )
        assert arguments["adapter_pins_now"] == registered.pins
        assert arguments["config_sha256"] == registered.config_sha
    # Aggregate the four cells with the picks job downloaded beside them: a verdict.
    (cells / "v3-picks-attempt-1").mkdir()
    picks.rename(cells / "v3-picks-attempt-1" / "v3_picks")
    argv = registered_args(
        registered,
        "aggregate",
        "--cells",
        str(cells),
        "--attempt-id",
        RUN,
        "--out",
        str(tmp_path / "a"),
    )
    code, document, err = run(argv, capsys)
    assert code == 0, err
    verdict_raw = (tmp_path / "a" / "summary" / "verdict.json").read_bytes()
    verdict = json.loads(verdict_raw)
    # Most cells never ran, so acceptance cannot pass (it may fail on what it observed).
    assert document["status"] == verdict["status"] != "pass"
    assert document["verdict_sha256"] == sha(verdict_raw)
    completed = {cell for cell, read in verdict["cells"].items() if read["state"] == "completed"}
    assert completed == set(KIND_CELLS.values()) and verdict["v3_picks"]["state"] == "completed"
    # Every job ran as attempt 1 of the run aggregation names: no re-run.
    assert verdict["run"]["run_id"] == "38267478452" and verdict["run"]["reruns"] == []
    assert verdict["mode"] == "registered"


def test_picks_and_aggregate_refuse_without_the_gate(registered, tmp_path, capsys):
    picks = ("--packs", str(registered.packs), "--attempt-id", RUN, "--out", str(tmp_path / "p"))
    summary = ("--cells", str(tmp_path), "--attempt-id", RUN, "--out", str(tmp_path / "a"))
    for command, extra in (("picks", picks), ("aggregate", summary)):
        code, _, err = run(registered_args(registered, command, *extra, sha="0" * 64), capsys)
        assert code == 1 and "job gate refused" in err and "not the expected" in err
    copy = changed_copy(registered, tmp_path)
    for command, extra in (("picks", picks), ("aggregate", summary)):
        code, _, err = run(registered_args(registered, command, *extra, repo=copy), capsys)
        assert code == 1 and "src/crypto_grid_bot/combined/engine.py" in err
    assert not (tmp_path / "p").exists() and not (tmp_path / "a").exists()


def test_a_long_only_v3_cell_runs_without_picks_and_only_the_selector_needs_them(
    registered, smoke_plan, tmp_path, capsys
):
    """Only the selector reads the picks (Ruling C1). A fixed long-only V3 rule runs from
    run-main's very arguments (no --picks; the legacy dataset, which it ignores), before any
    picks job exists; the selector without --picks, and a long-only rule given one, are
    refused before anything is written (a refusal, not a warning: the cell's inputs are
    exact, and a picks directory handed to a cell that never reads it is a wiring error)."""
    long_only = "w1.unchanged_v3_r1_long_only.native.c1.research"
    selector = "w1.unchanged_v3_selector.native.c1.research"

    def run_main(cell, out, *extra):  # the run-main step's arguments
        argv = registered_args(
            registered,
            "run-cell",
            "--cell",
            cell,
            "--packs",
            str(registered.packs),
            "--attempt-id",
            RUN,
            "--legacy-data",
            str(registered.legacy),
            "--out",
            str(out),
            *extra,
        )
        return run(argv, capsys)

    out = tmp_path / f"cell-{long_only}-attempt-1"
    code, document, err = run_main(long_only, out)
    assert code == 0, err
    directory = out / long_only
    assert document["kind"] == "v3" and (directory / "outcome.json").is_file()
    native = (directory / "native_evidence.json").read_text(encoding="ascii")
    assert "v3-picks" not in native  # it cites the V3 pack and the run-manifest alone
    # The selector without --picks: refused.
    code, _, err = run_main(selector, tmp_path / "selector")
    assert code == 1 and "the V3 selector needs --picks" in err
    assert not (tmp_path / "selector").exists()
    # A long-only rule given --picks: refused.
    picks = tmp_path / "v3_picks"
    picks.mkdir()
    other = "w1.unchanged_v3_r2_long_only.native.c1.research"
    code, _, err = run_main(other, tmp_path / "given", "--picks", str(picks))
    assert code == 1 and "a fixed long-only V3 rule reads no picks; --picks refused" in err
    assert not (tmp_path / "given").exists()


@pytest.mark.parametrize(
    "bad",
    [
        "38267478452",
        "38267478452-attempt-0",
        "1-attempt-01",
        "attempt-1",
        "",
        "7 7-attempt-1",
        None,
    ],
)
def test_a_malformed_attempt_id_is_refused(bad):
    with pytest.raises(ValueError, match="attempt id"):
        v31_driver.job_attempt_id(bad, CELL)


def test_each_job_records_a_unique_attempt_id_ending_in_its_attempt(registered, tmp_path, capsys):
    recorded = v31_driver.job_attempt_id("38267478452-attempt-2", CELL)
    assert recorded == f"38267478452-{CELL}-attempt-2"
    assert (
        v31_driver.job_attempt_id("run.1_a-attempt-10", "v3_picks") == "run.1_a-v3_picks-attempt-10"
    )
    assert _CLAIMED_ATTEMPT.search(recorded).group(1) == "2"  # aggregation reads it back
    # The help says what the workflow passes and what each job records.
    for command, recorded_form in (
        ("run-cell", "<run_id>-<cell_id>-attempt-<run_attempt>"),
        ("picks", "<run_id>-v3_picks-attempt-<run_attempt>"),
    ):
        with pytest.raises(SystemExit):
            v31_driver.main([command, "--help"])
        text = "".join(capsys.readouterr().out.split())  # argparse wraps at hyphens
        assert "<run_id>-attempt-<run_attempt>" in text and recorded_form in text
    # run-cell refuses a malformed attempt id before it writes anything.
    extra = ("--cell", CELL, "--packs", str(registered.packs), "--attempt-id", "1-attempt-01")
    argv = registered_args(registered, "run-cell", *extra, "--out", str(tmp_path / "out"))
    code, _, err = run(argv, capsys)
    assert code == 1 and "attempt id" in err and not (tmp_path / "out").exists()


# --- plan: the first job's gate and the matrices (Rulings F6, F7) -------------------------


def test_plan_gates_first_and_sends_only_the_selector_to_the_picks_matrix(
    registered, smoke_plan, tmp_path, capsys
):
    code, document, err = run(registered_args(registered, "plan"), capsys)
    assert code == 0, err
    v3_cells, main_cells = document["v3_cells"], document["main_cells"]
    # Only the four selector cells read the picks; the six long-only V3 rules (24 cells)
    # replay their own rule, so they run in the main matrix and never wait for the picks.
    assert len(v3_cells) == 4 and all(".unchanged_v3_selector." in c for c in v3_cells)
    assert len(main_cells) == 216 - 4 == 212
    long_only = [c for c in main_cells if "_long_only." in c and "unchanged_v3_r" in c]
    assert len(long_only) == 6 * 2 * 2
    assert set(v3_cells).isdisjoint(main_cells)
    assert (document["cells_registered"], document["cells_planned"]) == (216, 216)
    assert document["registration_sha256"] == registered.config_sha
    assert (document["code_pin"], document["repo_head"]) == (registered.code_pin, registered.head)
    # A registered run plans every cell: --cells belongs to a rehearsal.
    code, _, err = run(registered_args(registered, "plan", "--cells", "5"), capsys)
    assert code == 1 and "a registered run runs every registered cell" in err
    # A wrong ref fails here, in the first job: another registration, or code changed
    # after the code pin.
    code, _, err = run(registered_args(registered, "plan", sha="0" * 64), capsys)
    assert code == 1 and "job gate refused" in err
    copy = changed_copy(registered, tmp_path)
    code, _, err = run(registered_args(registered, "plan", repo=copy), capsys)
    assert code == 1 and "src/crypto_grid_bot/combined/engine.py" in err
    # This world holds no rehearsal marker, so a rehearsal refuses it.
    code, _, err = run(registered_args(registered, "plan", "--mode", "rehearsal"), capsys)
    assert code == 1 and "rehearsal refused" in err


@pytest.mark.parametrize("value", ["0", "-1", "05", "x", "1.5"])
def test_plan_refuses_a_malformed_cell_count(registered, capsys, value):
    with pytest.raises(SystemExit):
        v31_driver.main(registered_args(registered, "plan", "--cells", value))
    assert "empty or a positive integer required" in capsys.readouterr().err


# --- the V3.1 trial authorizes the registration (Codex P1, PR #269 round 4; Ruling R4-1) --


@dataclass(frozen=True)
class TrialWorld:
    repo: Path
    code_pin: str
    head: str
    pins: dict  # trial_errors' registration pins: the code pin and the two files' SHA-256


TRIAL_FILES = {  # stand-ins: the trial gate reads the registration and run-manifest's hashes
    "registration": b'{"synthetic": "registration"}\n',
    "manifest": b'{"synthetic": "run-manifest"}\n',
}
NOT_READY = "the spec-v3.1 trial v3-1-synthetic is not ready at the head"


def trial_world(root: Path, *, late: bool = False, **paths: str) -> TrialWorld:
    """A tiny repository laid out as a registration commit: the synthetic V3.1 trial's spec
    and registration event, a code pin committing one module on top, then the registration
    and run-manifest at their paths with the trial's completion (``paths``: other paths for
    the completion to pin, the same bytes committed there too). ``late``: the module comes
    with the spec, so the code pin is the registration event's own commit, whose first
    parent holds no register."""
    repo = root / "repo"
    v31_smoke.init_repo(repo)
    module = repo / "src/crypto_grid_bot/combined/engine.py"
    if late:
        module.parent.mkdir(parents=True)
        module.write_bytes(b"ENGINE = 1\n")
        code_pin = v31_smoke.register_trial(repo)
    else:
        v31_smoke.register_trial(repo)
        module.parent.mkdir(parents=True)
        module.write_bytes(b"ENGINE = 1\n")
        code_pin = v31_smoke.commit_all(repo, "the code pin")
    pinned = {"registration": v31_driver.REGISTRATION, "manifest": v31_driver.RUN_MANIFEST}
    for key, default in tuple(pinned.items()):
        pinned[key] = paths.get(key, default)
        for path in {default, pinned[key]}:
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_bytes(TRIAL_FILES[key])
    pins = {
        "code_pin": code_pin,
        "config_sha256": sha(TRIAL_FILES["registration"]),
        "manifest_sha256": sha(TRIAL_FILES["manifest"]),
    }
    v31_smoke.complete_trial(
        repo,
        code_pin=code_pin,
        config_sha256=pins["config_sha256"],
        manifest_sha256=pins["manifest_sha256"],
        **pinned,
    )
    head = v31_smoke.commit_all(repo, "the registration (synthetic)")
    return TrialWorld(repo, code_pin, head, pins)


def register_lines(repo: Path, commit: str) -> list[dict]:
    raw = v31_driver._committed(repo, commit, v31_smoke.TRIAL_REGISTER)
    return [json.loads(line) for line in raw.splitlines()]


def test_the_trial_gate_passes_a_completed_v31_trial_that_binds_the_registration(tmp_path):
    world = trial_world(tmp_path)
    assert v31_driver.V31_FAMILY == v31_smoke.TRIAL_FAMILY == "spec-v3.1"
    assert v31_driver.trial_errors(world.repo, world.head, **world.pins) == []
    # The layout check_ready requires: the registration event in the code pin's first
    # parent, the completion committed after the code pin, with the registration commit.
    before = register_lines(world.repo, f"{world.code_pin}^1")
    assert [(e["family"], e["event_type"]) for e in before] == [("spec-v3.1", "registration")]
    events = register_lines(world.repo, world.head)
    assert [e["event_type"] for e in events] == ["registration", "completion"]
    assert events[1]["payload"]["code_commit"] == world.code_pin


@pytest.mark.parametrize("case", ["no register", "no V3.1 registration", "two V3.1 registrations"])
def test_the_trial_gate_needs_exactly_one_v31_registration_at_the_head(tmp_path, case):
    if case == "no register":
        repo = tmp_path / "repo"
        v31_smoke.init_repo(repo)
        (repo / "README.md").write_bytes(b"no register\n")
        head = v31_smoke.commit_all(repo, "no register")
        pins = {"code_pin": head, "config_sha256": "1" * 64, "manifest_sha256": "2" * 64}
        expected = f"the head {head} commits no docs/trials/register.jsonl"
    elif case == "no V3.1 registration":  # V3's own trial alone
        repo = tmp_path / "repo"
        v31_smoke.init_repo(repo)
        register = repo / v31_smoke.TRIAL_REGISTER
        register.parent.mkdir(parents=True)
        for event in v3_trial("3" * 64, "4" * 64):
            append_event(register, event)
        head = v31_smoke.commit_all(repo, "V3's trial alone")
        pins = {"code_pin": head, "config_sha256": "1" * 64, "manifest_sha256": "2" * 64}
        expected = "must hold one spec-v3.1 registration, found 0"
    else:
        world = trial_world(tmp_path)
        repo, pins = world.repo, world.pins
        second = {**register_lines(repo, world.head)[0], "trial_id": "v3-1-second"}
        append_event(repo / v31_smoke.TRIAL_REGISTER, {**second, "event_id": "v3-1-second-reg"})
        head = v31_smoke.commit_all(repo, "a second V3.1 registration")
        expected = "must hold one spec-v3.1 registration, found 2"
    assert v31_driver.trial_errors(repo, head, **pins) == [
        expected
        if case == "no register"
        else f"docs/trials/register.jsonl at the head {head} {expected}"
    ]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("another code commit", "pins code commit {code_pin}, not the registration's code pin"),
        ("another config SHA-256", "pins its config config/v3_1_registration.json at {config}, "),
        ("another manifest SHA-256", "pins its manifest config/v3_1_run_manifest.json at {man}, "),
        ("another config path", "pins its config config/other-registration.json at {config}, "),
        ("another manifest path", "pins its manifest config/other-manifest.json at {man}, "),
    ],
)
def test_the_trial_gate_refuses_a_completion_that_binds_another_registration(
    tmp_path, case, expected
):
    """check_ready passes each of these (its pins hold at the head); the completion pins
    another code commit, config or manifest than this registration's, so it does not
    authorize this one."""
    paths = {
        "another config path": {"registration": "config/other-registration.json"},
        "another manifest path": {"manifest": "config/other-manifest.json"},
    }.get(case, {})
    world = trial_world(tmp_path, **paths)
    pins = dict(world.pins)
    changed = {
        "another code commit": "code_pin",
        "another config SHA-256": "config_sha256",
        "another manifest SHA-256": "manifest_sha256",
    }.get(case)
    if changed is not None:
        pins[changed] = "0" * len(pins[changed])
    errors = v31_driver.trial_errors(world.repo, world.head, **pins)
    shown = expected.format(
        code_pin=world.code_pin,
        config=world.pins["config_sha256"],
        man=world.pins["manifest_sha256"],
    )
    assert len(errors) == 1 and shown in errors[0], errors
    assert errors[0].startswith("the spec-v3.1 completion pins")


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("a correction", "corrected trial requires a new registration before dispatch"),
        ("code changed after the completion", "committed code does not match pin"),
        (
            "a code pin before the registration",
            "registration must precede the implementation commit",
        ),
        ("no completion", "one committed completion required"),
    ],
)
def test_the_trial_gate_refuses_whatever_check_ready_refuses(tmp_path, case, reason):
    world = trial_world(tmp_path, late=case == "a code pin before the registration")
    repo, head = world.repo, world.head
    register = repo / v31_smoke.TRIAL_REGISTER
    if case == "a correction":
        correction = v31_smoke.trial_event(
            "correction",
            {"target_id": "v3-1-synthetic-completion", "reason": "synthetic", "details": "x"},
        )
        append_event(register, correction)
        head = v31_smoke.commit_all(repo, "a correction")
    elif case == "code changed after the completion":
        (repo / "src/crypto_grid_bot/combined/engine.py").write_bytes(b"ENGINE = 2\n")
        head = v31_smoke.commit_all(repo, "a code change")
    elif case == "no completion":
        register.write_bytes(v31_driver._committed(repo, world.code_pin, v31_smoke.TRIAL_REGISTER))
        head = v31_smoke.commit_all(repo, "the completion dropped")
    assert v31_driver.trial_errors(repo, head, **world.pins) == [f"{NOT_READY} {head}: {reason}"]


def without_completion(repo: Path, code_pin: str, root: Path) -> Path:
    """A copy of ``repo`` whose head commits the trial register as the code pin does: the
    V3.1 registration event without its completion."""
    copy = root / "repo"
    shutil.copytree(repo, copy)
    raw = v31_driver._committed(copy, code_pin, v31_smoke.TRIAL_REGISTER)
    (copy / v31_smoke.TRIAL_REGISTER).write_bytes(raw)
    v31_smoke.commit_all(copy, "the V3.1 trial's completion dropped")
    return copy


def test_every_registered_job_and_cell_refuses_a_registration_the_trial_does_not_authorize(
    registered, smoke_plan, tmp_path, capsys
):
    """job_gate (registered prepare, plan, picks, aggregate) and run-cell, before it reads
    any pack, refuse a registration that no committed V3.1 completion authorizes."""
    copy = without_completion(registered.repo, registered.code_pin, tmp_path)
    out = tmp_path / "out"
    missing = tmp_path / "no-packs"  # run-cell refuses before it would read a pack here
    jobs = ("--packs", str(missing), "--attempt-id", RUN, "--out", str(out))
    calls = {
        "plan": (),
        "prepare": ("--mode", "registered", "--work", str(tmp_path / "w"), "--out", str(out)),
        "picks": jobs,
        "run-cell": ("--cell", CELL, *jobs),
        "aggregate": ("--cells", str(missing), "--attempt-id", RUN, "--out", str(out)),
    }
    for command, extra in calls.items():
        code, _, err = run(registered_args(registered, command, *extra, repo=copy), capsys)
        refusal = f"trial gate refused cell {CELL!r}" if command == "run-cell" else "job gate"
        assert code == 1 and refusal in err, (command, err)
        assert f"{NOT_READY} " in err and "one committed completion required" in err, command
        assert str(missing) not in err, command  # no pack or cell was looked for
    assert not out.exists() and not (tmp_path / "w").exists()


# --- the rehearsal: the registered job graph on a synthetic world (Ruling F3) -------------


@dataclass(frozen=True)
class Rehearsal:
    root: Path
    repo: Path
    document: dict


@pytest.fixture(scope="module")
def rehearsal(module_network_blocked, tmp_path_factory) -> Rehearsal:
    """The rehearsal world, as the plan job builds it."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path_factory.mktemp("rehearsal") / "work"
    code, out, err = quietly(["rehearsal-world", "--out", str(root)])
    assert code == 0, err
    return Rehearsal(root, root / "repo", json.loads(out))


def rehearsal_args(world: Rehearsal, command: str, *extra: str, mode: str = "rehearsal"):
    sha = world.document["registration_sha256"]
    return [
        command,
        "--mode",
        mode,
        "--repo",
        str(world.repo),
        "--registration-sha256",
        sha,
        *extra,
    ]


def git_lines(repo: Path, *args: str) -> list[str]:
    return v31_driver._git(repo, *args).decode("utf-8").split()


def test_the_rehearsal_world_is_a_registration_on_top_of_its_code_pin(rehearsal):
    document, repo = rehearsal.document, rehearsal.repo
    assert document["schema"] == "v3.1-rehearsal-world-1"
    code_pin, head = document["code_pin"], document["head"]
    assert code_pin != head and git_lines(repo, "rev-parse", "HEAD") == [head]
    # Like a real registration commit: only the registration artifacts changed since the
    # code pin, and the real execution gate's path rule accepts them.
    changed = v31_driver.changed_since(repo, code_pin)
    assert changed == REGISTRATION_CHANGES
    assert v31_driver._path_errors(changed, ()) == []
    # The synthetic V3.1 trial is laid out as the trial gate requires: its registration
    # event in the code pin's first parent, its completion at the head binding the code pin,
    # the registration and the run-manifest (Ruling R4-1).
    earlier = v31_driver._committed(repo, f"{code_pin}^1", v31_smoke.TRIAL_REGISTER)
    assert [json.loads(line)["event_type"] for line in earlier.splitlines()] == ["registration"]
    manifest_sha = sha((repo / "config/v3_1_run_manifest.json").read_bytes())
    pins = {"config_sha256": document["registration_sha256"], "manifest_sha256": manifest_sha}
    assert v31_driver.trial_errors(repo, head, code_pin=code_pin, **pins) == []
    # The code pin commits the marker and every module of this checkout's package, so the
    # adapter pins are read from real blobs.
    marker = v31_driver._committed(repo, code_pin, v31_smoke.REHEARSAL_MARKER)
    assert marker == v31_smoke.rehearsal_marker()
    listed = set(git_lines(repo, "ls-tree", "-r", "--name-only", code_pin))
    assert set(v31_smoke.source_modules()) <= listed
    assert "src/crypto_grid_bot/combined/driver/run_cell.py" in listed
    registration = json.loads((repo / "config/v3_1_registration.json").read_bytes())
    assert registration["adapter_pins"] == adapter_pins(repo, code_pin)
    assert len(set(registration["adapter_pins"].values())) == 4  # one per arm kind
    assert registration["code_pin"] == code_pin and len(registration["cells"]) == 216
    raw = (repo / "config/v3_1_registration.json").read_bytes()
    assert sha(raw) == document["registration_sha256"]
    # Nothing but the repository and the synthetic dataset is left: the packs built to
    # register were temporary (the rehearsal's prepare builds them again).
    assert sorted(path.name for path in rehearsal.root.iterdir()) == ["legacy", "repo"]


def test_the_rehearsal_runs_the_registered_job_graph_offline(
    rehearsal, tmp_path, capsys, monkeypatch
):
    """plan, prepare, picks, each planned cell and aggregate, through the same
    subcommands and gates as a registered run, on the world: nothing fetched (any
    transport or fetch refuses) and the stand-ins only inside each subcommand."""

    def no_network(*args, **kwargs):
        raise AssertionError("a rehearsal touched a transport or a fetch")

    monkeypatch.setattr(v31_driver, "V3Transport", no_network)
    monkeypatch.setattr(v31_driver, "LegacyTransport", no_network)
    monkeypatch.setattr(v31_driver, "fetch_entries", no_network)
    original = (baseline_v3.run_walk_forward, run_baselines.mask_job)
    run_id = "4242-attempt-1"
    # Under the owner's real plan, which the world's synthetic plan is not: the rehearsal
    # mode is exempt from the plan gate by name (v31_driver.plan_gate).
    world_config = load_prepare_config(rehearsal.repo / "config/v3_1_prepare.json")
    assert owner_plan.OWNER_PLAN.windows[0].start_ms == owner_plan.W1_START_MS
    assert owner_plan.owner_plan_errors(world_config)

    # plan: the gate, then six cells (one W1 cell of each kind, the selector and a fixed
    # long-only V3 rule both, and one W0 cell); fewer cannot exercise every cell path.
    code, _, err = run(rehearsal_args(rehearsal, "plan", "--cells", "5"), capsys)
    assert code == 1 and "--cells: at least 6" in err
    code, planned, err = run(rehearsal_args(rehearsal, "plan", "--cells", "6"), capsys)
    assert code == 0, err
    assert planned["v3_cells"] == ["w1.unchanged_v3_selector.native.c1.research"]
    assert len(planned["main_cells"]) == 5 and planned["cells_planned"] == 6
    # The long-only V3 rule runs in the main matrix, without the picks.
    assert "w1.unchanged_v3_r1_long_only.native.c1.research" in planned["main_cells"]
    assert planned["registration_sha256"] == rehearsal.document["registration_sha256"]

    # prepare: the registered gates, the world's dataset verified, the packs reproduced.
    work = tmp_path / "work"
    shutil.copytree(rehearsal.root, work)  # as each job unpacks the world
    out = tmp_path / "out"
    argv = rehearsal_args(rehearsal, "prepare", "--work", str(work), "--out", str(out))
    argv[argv.index("--repo") + 1] = str(work / "repo")
    code, prepared, err = run(argv, capsys)
    assert code == 0, err
    assert prepared["mode"] == "rehearsal"
    assert prepared["window_packs"] == rehearsal.document["window_packs"]
    assert prepared["v3_pack_sha256"] == rehearsal.document["v3_pack_sha256"]
    packs = out / "packs"
    assert sorted(p.name for p in packs.iterdir()) == [
        "v3-input.pack.json.gz",
        "window-w0.pack.json.gz",
        "window-w1.pack.json.gz",
    ]

    # picks, then each planned cell as its matrix job runs it, into its artifact folder.
    cells = tmp_path / "cells"
    extra = ("--packs", str(packs), "--attempt-id", run_id)
    code, picked, err = run(
        rehearsal_args(rehearsal, "picks", *extra, "--out", str(tmp_path / "p")), capsys
    )
    assert code == 0, err
    (cells / "v3-picks-attempt-1").mkdir(parents=True)
    picks_dir = cells / "v3-picks-attempt-1" / "v3_picks"
    (tmp_path / "p" / "v3_picks").rename(picks_dir)
    for cell_id in planned["main_cells"] + planned["v3_cells"]:
        folder = cells / f"cell-{cell_id}-attempt-1"
        more = ("--picks", str(picks_dir)) if cell_id in planned["v3_cells"] else ()
        argv = rehearsal_args(
            rehearsal,
            "run-cell",
            "--cell",
            cell_id,
            *extra,
            "--legacy-data",
            str(work / "legacy"),
            "--out",
            str(folder),
            *more,
        )
        code, document, err = run(argv, capsys)
        assert code == 0, (cell_id, err)
        assert document["attempt_id"] == f"4242-{cell_id}-attempt-1"
    argv = rehearsal_args(
        rehearsal,
        "aggregate",
        "--cells",
        str(cells),
        "--attempt-id",
        run_id,
        "--out",
        str(tmp_path / "a"),
    )
    code, judged, err = run(argv, capsys)
    assert code == 0, err
    verdict = json.loads((tmp_path / "a" / "summary" / "verdict.json").read_bytes())
    completed = {c for c, read in verdict["cells"].items() if read["state"] == "completed"}
    assert completed == set(planned["main_cells"] + planned["v3_cells"])
    assert verdict["v3_picks"]["state"] == "completed" and verdict["run"]["reruns"] == []
    # A rehearsal dispatches no registration: its aggregate reads no workflow runs (without
    # the runner's variables a registered one could not rule another dispatch out).
    assert verdict["run"]["other_dispatches"] == []
    assert judged["status"] == "incomplete"  # 6 of 216 cells: never a verdict
    assert verdict["mode"] == "rehearsal"
    summary_md = (tmp_path / "a" / "summary" / "summary.md").read_text(encoding="utf-8")
    assert summary_md.startswith("# V3.1 run summary: REHEARSAL")
    assert (baseline_v3.run_walk_forward, run_baselines.mask_job) == original


def test_a_registered_run_refuses_a_rehearsal_world(rehearsal, tmp_path, capsys):
    """Every registered subcommand, and prepare-only and timing, refuse a world built for
    a rehearsal: its stand-ins can never pass for a registered run."""
    out = str(tmp_path / "out")
    packs = ("--packs", str(tmp_path), "--attempt-id", RUN, "--out", out)
    calls = {
        "plan": (),
        "prepare": ("--work", str(rehearsal.root), "--out", out),
        "picks": packs,
        "run-cell": ("--cell", CELL, *packs),
        "aggregate": ("--cells", str(tmp_path), "--attempt-id", RUN, "--out", out),
    }
    for command, extra in calls.items():
        code, _, err = run(rehearsal_args(rehearsal, command, *extra, mode="registered"), capsys)
        assert code == 1, command
        assert "registered run refused: the checkout is a rehearsal world" in err, command
    prepare_sha = sha((rehearsal.repo / "config/v3_1_prepare.json").read_bytes())
    head = rehearsal.document["head"]
    gate = ("--code-commit", head, "--prepare-sha256", prepare_sha)
    code, _, err = run(
        ["prepare", "--mode", "prepare-only", "--repo", str(rehearsal.repo), *gate]
        + ["--work", str(tmp_path / "w"), "--out", out],
        capsys,
    )
    assert code == 1 and "prepare-only run refused: the checkout is a rehearsal world" in err
    code, _, err = run(
        ["timing", "--part", "cell", "--repo", str(rehearsal.repo), *gate]
        + ["--scratch", str(tmp_path / "s"), "--out", str(tmp_path / "t")],
        capsys,
    )
    assert code == 1 and "timing run refused: the checkout is a rehearsal world" in err
    assert not (tmp_path / "out").exists() and not (tmp_path / "w").exists()


def test_a_rehearsal_refuses_any_world_without_the_marker(registered, rehearsal, tmp_path, capsys):
    """A rehearsal runs the stand-ins, so it refuses a world whose code pin does not
    commit the marker (a smoke world here; the repository never holds it), and a world
    whose marker was edited since."""
    out = str(tmp_path / "out")
    packs = ("--packs", str(registered.packs), "--attempt-id", RUN, "--out", out)
    calls = {
        "plan": (),
        "picks": packs,
        "run-cell": ("--cell", CELL, *packs),
        "aggregate": ("--cells", str(tmp_path), "--attempt-id", RUN, "--out", out),
        "prepare": ("--work", str(tmp_path / "w"), "--out", out),
    }
    for command, extra in calls.items():
        argv = registered_args(registered, command, "--mode", "rehearsal", *extra)
        code, _, err = run(argv, capsys)
        assert code == 1 and "rehearsal refused" in err, (command, err)
    edited = tmp_path / "edited"
    shutil.copytree(rehearsal.root, edited)
    marker = edited / "repo" / v31_smoke.REHEARSAL_MARKER
    marker.write_bytes(marker.read_bytes().replace(b"synthetic", b"real"))
    argv = rehearsal_args(rehearsal, "plan")
    argv[argv.index("--repo") + 1] = str(edited / "repo")
    code, _, err = run(argv, capsys)
    assert code == 1 and v31_smoke.REHEARSAL_MARKER in err  # an uncommitted change too
    assert not (tmp_path / "out").exists()
    # And the repository itself, which holds no registration of its own yet, never runs a
    # rehearsal (or anything else) without one.
    code, _, err = run(
        ["plan", "--mode", "rehearsal", "--repo", str(ROOT), "--registration-sha256", "0" * 64],
        capsys,
    )
    assert code == 1


def test_a_rehearsal_holds_the_trial_gate_on_its_world(rehearsal, tmp_path, capsys):
    """The rehearsal's world carries a synthetic V3.1 trial, so a rehearsal runs the trial
    gate as a registered run does: a world whose completion was dropped is refused."""
    copy = without_completion(rehearsal.repo, rehearsal.document["code_pin"], tmp_path)
    argv = rehearsal_args(rehearsal, "plan")
    argv[argv.index("--repo") + 1] = str(copy)
    code, _, err = run(argv, capsys)
    assert code == 1 and "job gate refused" in err
    assert f"{NOT_READY} " in err and "one committed completion required" in err


# --- one dispatch per registration (Codex P1, PR #269 round 4; Ruling R4-2) --------------

SHA = "e" * 64
TITLE = f"v31-run registered {SHA}"  # the workflow's run-name for a registered dispatch
NOW, EARLIER, LATER = "2026-10-13T12:00:00Z", "2026-10-13T11:59:59Z", "2026-10-13T12:00:01Z"
API = "https://api.github.com/repos/owner/repo/actions/"


def workflow_run(run_id, created=EARLIER, title=TITLE, status="completed", conclusion="success"):
    """A run as GitHub's REST API lists it: the fields the check reads, and two it ignores."""
    return {
        "id": run_id,
        "display_title": title,
        "created_at": created,
        "status": status,
        "conclusion": conclusion,
    }


CURRENT = workflow_run(500, created=NOW, status="in_progress", conclusion=None)


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [
        ("queued", None),
        ("waiting", None),
        ("in_progress", None),
        ("completed", "failure"),
        ("completed", "cancelled"),
        ("completed", "timed_out"),
        ("completed", "success"),
    ],
)
def test_an_earlier_dispatch_of_the_registration_counts_whatever_its_status(status, conclusion):
    earlier = workflow_run(400, status=status, conclusion=conclusion)
    assert v31_driver.other_dispatches([CURRENT, earlier], CURRENT, SHA) == (400,)


def test_only_another_earlier_or_simultaneous_registered_dispatch_of_the_registration_counts():
    runs = [
        workflow_run(600, created=LATER),  # created after this run: it never counts
        CURRENT,
        workflow_run(499, created=NOW),  # the same second: a tie counts
        workflow_run(401, title=f"v31-run registered {'f' * 64}"),  # another registration
        workflow_run(402, title=f"v31-run rehearsal {SHA}"),  # another mode
        workflow_run(403, title=f"v31-run smoke {SHA}"),
        workflow_run(404, title=f"{TITLE} "),  # not exactly the title
        workflow_run(300, created="2026-10-01T00:00:00Z"),
    ]
    assert v31_driver.other_dispatches(runs, CURRENT, SHA) == (300, 499)
    # The current run alone is no other dispatch, whatever it shares with itself.
    assert v31_driver.other_dispatches([CURRENT], CURRENT, SHA) == ()
    assert v31_driver.registered_title(SHA) == TITLE


def without(document: dict, key: str) -> dict:
    return {name: value for name, value in document.items() if name != key}


@pytest.mark.parametrize(
    ("runs", "current", "message"),
    [
        ([CURRENT, "a run"], CURRENT, "workflow run 2 of 2: a JSON object required"),
        ([CURRENT, without(workflow_run(400), "id")], CURRENT, "id None"),
        ([CURRENT, workflow_run(True)], CURRENT, "id True"),
        ([CURRENT, workflow_run("400")], CURRENT, "id '400'"),
        ([CURRENT, workflow_run(0)], CURRENT, "id 0"),
        ([CURRENT, without(workflow_run(400), "display_title")], CURRENT, "display_title None"),
        ([CURRENT, workflow_run(400, title=7)], CURRENT, "display_title 7"),
        ([CURRENT, without(workflow_run(400), "created_at")], CURRENT, "created_at None"),
        ([CURRENT, workflow_run(400, created="2026-10-13T11:59:59")], CURRENT, "created_at"),
        ([CURRENT, workflow_run(400, created="2026-10-13T11:59:59.5Z")], CURRENT, "created_at"),
        ([CURRENT, workflow_run(400, created="2026-02-30T00:00:00Z")], CURRENT, "not a date"),
        ([CURRENT, workflow_run(400), workflow_run(400)], CURRENT, "run 400 is listed twice"),
        ([workflow_run(400)], CURRENT, "the current run 500 is not among"),
        ([CURRENT], {**CURRENT, "created_at": None}, "the current run"),
        ([CURRENT], "a run", "the current run: a JSON object required"),
        (
            [CURRENT],
            {**CURRENT, "display_title": f"v31-run registered {'f' * 64}"},
            "the current run 500 is titled",
        ),
    ],
)
def test_a_malformed_run_or_run_list_is_refused(runs, current, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        v31_driver.other_dispatches(runs, current, SHA)


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


class FakeGitHub:
    """GitHub's REST API for the dispatch check, in memory (no network): the current run
    (``runs/500``) and this workflow's ``runs`` in pages of 100. ``totals`` replaces a
    page's total_count, ``answers`` a path's response (an exception is raised). Records
    every request: its URL, method, Authorization header and timeout."""

    def __init__(self, runs, current=CURRENT, *, totals=None, answers=None):
        self.runs, self.current = list(runs), current
        self.totals, self.answers = totals or {}, answers or {}
        self.requests = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.requests.append(
            (url, request.get_method(), request.get_header("Authorization"), timeout)
        )
        assert url.startswith(API), url
        path = url[len(API) :]
        if path in self.answers:
            given = self.answers[path]
            if isinstance(given, BaseException):
                raise given
            return given
        if path == "runs/500":
            return answer(self.current)
        page = re.fullmatch(r"workflows/v31-run\.yml/runs\?per_page=100&page=([1-9][0-9]*)", path)
        assert page is not None, url
        number = int(page[1])
        listed = self.runs[(number - 1) * 100 : number * 100]
        total = self.totals.get(number, len(self.runs))
        return answer({"total_count": total, "workflow_runs": listed})


def page(number: int) -> str:
    return f"workflows/v31-run.yml/runs?per_page=100&page={number}"


@pytest.fixture
def github_env(monkeypatch):
    """The runner's variables for GitHub's API, a stand-in token among them."""
    monkeypatch.setenv("GITHUB_TOKEN", "stand-in-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "500")


def test_the_dispatch_check_reads_the_current_run_and_every_page_of_runs(github_env):
    others = [workflow_run(1000 + i, title="v31-run smoke ") for i in range(248)]
    api = FakeGitHub([CURRENT, *others, workflow_run(400)])  # 250 runs: three pages
    assert v31_driver.dispatch_check(SHA, api) == (400,)
    assert [url for url, *_ in api.requests] == [API + "runs/500"] + [
        API + page(n) for n in (1, 2, 3)
    ]
    for _, method, authorization, timeout in api.requests:
        assert (method, authorization) == ("GET", "Bearer stand-in-token")
        assert timeout == v31_driver.GITHUB_TIMEOUT
    # Exactly one full page: its total ends the listing, no empty page is asked for.
    full = FakeGitHub([CURRENT, *others[:99]])
    assert v31_driver.dispatch_check(SHA, full) == ()
    assert [url for url, *_ in full.requests] == [API + "runs/500", API + page(1)]


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(API, code, "synthetic", {}, None)


MANY = [CURRENT, *(workflow_run(1000 + i, title="v31-run smoke ") for i in range(149))]
FAILS_CLOSED = {
    "no token": ({"GITHUB_TOKEN": None}, FakeGitHub([CURRENT]), "GITHUB_TOKEN is not set"),
    "no repository": ({"GITHUB_REPOSITORY": None}, FakeGitHub([CURRENT]), "GITHUB_REPOSITORY"),
    "a repository path": ({"GITHUB_REPOSITORY": "owner/.."}, FakeGitHub([CURRENT]), "owner/.."),
    "a malformed run id": ({"GITHUB_RUN_ID": "05"}, FakeGitHub([CURRENT]), "GITHUB_RUN_ID"),
    "an HTTP error": ({}, FakeGitHub([CURRENT], answers={"runs/500": http_error(502)}), "HTTP 502"),
    "a redirect": ({}, FakeGitHub([CURRENT], answers={page(1): http_error(301)}), "HTTP 301"),
    "a transport failure": (
        {},
        FakeGitHub([CURRENT], answers={page(1): urllib.error.URLError("down")}),
        "URLError",
    ),
    "a timeout": ({}, FakeGitHub([CURRENT], answers={page(1): TimeoutError()}), "TimeoutError"),
    "another status": (
        {},
        FakeGitHub([CURRENT], answers={"runs/500": Response(b"{}", 204)}),
        "HTTP 204",
    ),
    "not JSON": ({}, FakeGitHub([CURRENT], answers={page(1): Response(b"<html>")}), "not JSON"),
    "no total_count": (
        {},
        FakeGitHub([CURRENT], answers={page(1): answer({"workflow_runs": [CURRENT]})}),
        "total_count and workflow_runs required",
    ),
    "no workflow_runs": (
        {},
        FakeGitHub([CURRENT], answers={page(1): answer({"total_count": 1})}),
        "total_count and workflow_runs required",
    ),
    "a total that changes between pages": (
        {},
        FakeGitHub(MANY, totals={2: 151}),
        "total_count changed from 150 to 151",
    ),
    "pages that end before the total": (
        {},
        FakeGitHub([CURRENT], totals={1: 2}),
        "1 run(s) listed, total_count 2",
    ),
    "more runs than the total": ({}, FakeGitHub(MANY, totals={1: 99, 2: 99}), "more than"),
    "a page larger than asked": (
        {},
        FakeGitHub(
            [CURRENT],
            answers={page(1): answer({"total_count": 101, "workflow_runs": MANY[:1] * 101})},
        ),
        "more than 100 runs",
    ),
    "a current run of another id": (
        {},
        FakeGitHub([{**CURRENT, "id": 501}], {**CURRENT, "id": 501}),
        "not GITHUB_RUN_ID 500",
    ),
}


@pytest.mark.parametrize("case", list(FAILS_CLOSED))
def test_the_dispatch_check_fails_closed(github_env, monkeypatch, case):
    variables, api, message = FAILS_CLOSED[case]
    for name, value in variables.items():
        if value is None:
            monkeypatch.delenv(name)
        else:
            monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=re.escape(message)) as refused:
        v31_driver.dispatch_check(SHA, api)
    assert "stand-in-token" not in str(refused.value)  # no message ever carries the token
    if variables:  # a missing or malformed variable: refused before any request
        assert api.requests == []


def test_the_dispatch_check_refuses_a_body_beyond_its_limit(github_env, monkeypatch):
    monkeypatch.setattr(v31_driver, "MAX_GITHUB_BYTES", 16)
    with pytest.raises(ValueError, match="larger than 16 bytes"):
        v31_driver.dispatch_check(SHA, FakeGitHub([CURRENT]))


def test_the_default_opener_follows_no_redirect():
    """A redirect would carry the token's request elsewhere; the default opener's
    handler builds no new request for one, so urllib raises it as an HTTP error."""
    handler = v31_driver._NoRedirect()
    request = urllib.request.Request(API + "runs/500")
    assert (
        handler.redirect_request(request, None, 302, "Found", {}, "https://example.invalid/")
        is None
    )


def test_the_dispatch_check_subcommand_refuses_a_second_dispatch(github_env, capsys):
    argv = ["dispatch-check", "--registration-sha256", SHA]
    later = FakeGitHub([workflow_run(600, created=LATER), CURRENT])
    code, document, err = run(argv, capsys, github_opener=later)
    assert code == 0, err
    assert document == {
        "schema": "v3.1-dispatch-check-1",
        "registration_sha256": SHA,
        "other_dispatches": [],
    }
    earlier = FakeGitHub([CURRENT, workflow_run(400), workflow_run(300, status="queued")])
    code, _, err = run(argv, capsys, github_opener=earlier)
    assert code == 1 and "another dispatch of this registration: run 300, run 400" in err
    failing = FakeGitHub([CURRENT], answers={"runs/500": http_error(502)})
    code, _, err = run(argv, capsys, github_opener=failing)
    assert code == 1 and "HTTP 502" in err
    code, _, err = run(["dispatch-check", "--registration-sha256", "E" * 64], capsys)
    assert code == 1 and "64 lowercase hex" in err


def test_a_registered_aggregate_leaves_the_verdict_incomplete_on_another_dispatch(
    registered, smoke_plan, tmp_path, capsys, monkeypatch
):
    """The aggregate reads the workflow's runs in a registered run (Ruling R4-2), and
    names another dispatch of its registration in the verdict, or why none could be ruled
    out; a rehearsal's aggregate never reads them (test_the_rehearsal_runs_...)."""
    title = f"v31-run registered {registered.config_sha}"
    current = workflow_run(38267478452, created=NOW, title=title, status="in_progress")
    cells = tmp_path / "cells"
    cells.mkdir()

    def aggregate_with(name, api):
        argv = registered_args(registered, "aggregate", "--cells", str(cells))
        argv += ["--attempt-id", RUN, "--out", str(tmp_path / name)]
        code, document, err = run(argv, capsys, github_opener=api)
        assert code == 0, err
        verdict = json.loads((tmp_path / name / "summary" / "verdict.json").read_bytes())
        assert document["status"] == verdict["status"] == "incomplete"
        return verdict["run"]["other_dispatches"]

    # Without the runner's variables: no other dispatch can be ruled out.
    (reason,) = aggregate_with("no-variables", None)
    assert reason.startswith("another dispatch of this registration could not be ruled out: ")
    assert "GITHUB_TOKEN is not set" in reason
    monkeypatch.setenv("GITHUB_TOKEN", "stand-in-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "38267478452")
    seen = FakeGitHub([current, workflow_run(400, title=title)], current)
    seen.answers["runs/38267478452"] = answer(current)
    assert aggregate_with("another", seen) == ["another dispatch of this registration: run 400"]
    alone = FakeGitHub([current, workflow_run(600, created=LATER, title=title)], current)
    alone.answers["runs/38267478452"] = answer(current)
    assert aggregate_with("alone", alone) == []
    assert alone.requests  # the check ran


# --- the owner's plan: every real mode refuses any other (Codex P1 and P2, PR #269) -------


def test_the_plan_gate_holds_every_real_mode_and_exempts_the_rehearsal(tmp_path):
    synthetic = PrepareConfig(
        (PrepareWindow("w1", 0, 2 * DAY, ("BTCUSDT",)),),
        (FilePin("manifest.json", "0" * 64),),
        FilePin("spot.json", "1" * 64),
        FilePin("futures.json", "2" * 64),
        "3" * 64,
    )
    owner = replace(
        synthetic,
        windows=tuple(
            PrepareWindow(w.id, w.start_ms, w.end_ms, tuple(sorted(w.symbols)))
            for w in owner_plan.OWNER_PLAN.windows
        ),
    )
    assert v31_driver.REAL_MODES == ("registered", "prepare-only", "timing")
    for mode in v31_driver.REAL_MODES:
        with pytest.raises(ValueError, match=f"{mode} run refused, not the owner's plan"):
            v31_driver.plan_gate(mode, synthetic)
        assert v31_driver.plan_gate(mode, owner) is None
    # A rehearsal keeps its synthetic plan, and reads nothing for the gate.
    assert v31_driver.plan_gate("rehearsal", synthetic) is None
    assert v31_driver.plan_gate("rehearsal", tmp_path / "no-such-config.json") is None
    # The smoke calls no gate; no other mode passes one.
    with pytest.raises(ValueError, match="unknown mode 'smoke'"):
        v31_driver.plan_gate("smoke", owner)


def test_the_plan_gate_leaves_the_owners_plan_unchanged(registered):
    """plan_gate reads owner_plan.OWNER_PLAN and never changes it, whether it passes or
    refuses, with a registration or without: after every call the plan is the owner's,
    value for value (claude[bot]'s review of PR #269 at c1e5cc0)."""
    w1 = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"}
    w1 |= {"LTCUSDT", "LINKUSDT", "TRXUSDT"}
    w0 = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT", "TRXUSDT"}
    end = 1_735_689_600_000  # 2025-01-01 00:00 UTC
    expected = owner_plan.OwnerPlan(
        (
            owner_plan.PlanWindow("w1", 1_625_097_600_000, end, frozenset(w1)),
            owner_plan.PlanWindow("w0", 1_583_020_800_000, end, frozenset(w0)),
        ),
        date(2024, 12, 31),
    )
    plan = owner_plan.OWNER_PLAN
    assert plan == expected
    owner = PrepareConfig(
        tuple(
            PrepareWindow(w.id, w.start_ms, w.end_ms, tuple(sorted(w.symbols)))
            for w in expected.windows
        ),
        (FilePin("manifest.json", "0" * 64),),
        FilePin("spot.json", "1" * 64),
        FilePin("futures.json", "2" * 64),
        "3" * 64,
    )
    files = argparse.Namespace(
        registration=v31_driver.REGISTRATION, run_manifest=v31_driver.RUN_MANIFEST
    )
    reg, _ = v31_driver.load_registered(registered.repo, files)
    smoke_config = registered.repo / v31_driver.PREPARE_CONFIG
    for mode in v31_driver.REAL_MODES:
        assert v31_driver.plan_gate(mode, owner) is None
        with pytest.raises(ValueError, match="not the owner's plan"):
            v31_driver.plan_gate(mode, smoke_config, reg)  # the smoke world's plan
    assert v31_driver.plan_gate("rehearsal", smoke_config, reg) is None
    assert owner_plan.OWNER_PLAN is plan and plan == expected  # the same object, unchanged
    symbols = (owner_plan.W1_SYMBOLS, owner_plan.W0_SYMBOLS)
    assert symbols == (frozenset(w1), frozenset(w0))


def owner_windows(**changes: dict) -> list[dict]:
    """The owner's windows as a prepare config lists them, ``changes[<window id>]`` applied."""
    return [
        {
            "id": window.id,
            "start_ms": window.start_ms,
            "end_ms": window.end_ms,
            "symbols": sorted(window.symbols),
            **changes.get(window.id, {}),
        }
        for window in owner_plan.OWNER_PLAN.windows
    ]


W1_COINS, W0_COINS = owner_plan.W1_SYMBOLS, owner_plan.W0_SYMBOLS
# Each case: the prepare windows, the FX record's reference date and the refusal each real
# mode gives (None: the owner's plan, which no mode refuses for its plan).
PLAN_CASES = {
    "the owner's plan": (owner_windows(), "2024-12-31", None),
    "W1 without SOLUSDT": (
        owner_windows(w1={"symbols": sorted(W1_COINS - {"SOLUSDT"})}),
        "2024-12-31",
        "window w1 must hold the owner's 10 coins (missing: SOLUSDT; outside the plan: none)",
    ),
    "an extra W1 coin": (
        owner_windows(w1={"symbols": sorted(W1_COINS | {"AVAXUSDT"})}),
        "2024-12-31",
        "window w1 must hold the owner's 10 coins (missing: none; outside the plan: AVAXUSDT)",
    ),
    "a shifted W1 start": (
        owner_windows(w1={"start_ms": owner_plan.W1_START_MS + DAY}),
        "2024-12-31",
        "window w1 is [2021-07-02 00:00 UTC, 2025-01-01 00:00 UTC), not the owner's "
        "[2021-07-01 00:00 UTC, 2025-01-01 00:00 UTC)",
    ),
    "another W0 coin set": (
        owner_windows(w0={"symbols": sorted(W0_COINS - {"TRXUSDT"} | {"DOGEUSDT"})}),
        "2024-12-31",
        "window w0 must hold the owner's 8 coins (missing: TRXUSDT; outside the plan: DOGEUSDT)",
    ),
    "an FX record of 2024-12-30": (
        owner_windows(),
        "2024-12-30",
        "capital owner_small's FX record is the reference rate for 2024-12-30, not the "
        "owner's 2024-12-31",
    ),
}
REGISTERED_ONLY = {"an FX record of 2024-12-30"}  # a prepare config names no FX record


@dataclass(frozen=True)
class PlanWorld:
    repo: Path
    head: str
    prepare_sha: str
    registration: str
    manifest: str
    config_sha: str


def plan_world(registered: Registered, root: Path, windows: list, fx_date: str) -> PlanWorld:
    """A copy of the smoke world whose prepare config holds ``windows`` and whose FX record
    is the ECB rate of ``fx_date`` (its rate unchanged), registered over them as Task 11
    registers the real run, with pack pins naming no pack (each plan refusal comes before
    any pack is read), the V3.1 trial completed with them, and committed: the head is
    clean, and only registration artifacts changed since the code pin."""
    repo = root / "repo"
    shutil.copytree(registered.repo, repo)
    path = repo / "config/v3_1_prepare.json"
    path.write_bytes(dumped({**json.loads(path.read_bytes()), "windows": windows}))
    fx = {**v31_smoke.fx_record(), "reference_date": fx_date}
    (repo / v31_smoke.FX_RECORD).write_bytes(dumped(fx))
    prepare = load_prepare_config(path)
    world = v31_smoke.World(root, repo, registered.code_pin, registered.legacy, prepare)
    ids = [window["id"] for window in windows]
    document = {
        "window_packs": {wid: sha(f"no pack {wid}".encode()) for wid in ids},
        "v3_pack_sha256": sha(b"no V3 pack"),
        "skipped_hours": {wid: {"hours": []} for wid in ids},
    }
    files = {"registration": v31_driver.REGISTRATION, "manifest": v31_driver.RUN_MANIFEST}
    for name in files.values():  # the smoke world's own registration, replaced
        (repo / name).unlink()
    reg, config_sha = v31_smoke.register(
        world, document, code_pin=registered.code_pin, adapter_pins=registered.pins, **files
    )
    v31_smoke.complete_trial(
        repo,
        code_pin=registered.code_pin,
        config_sha256=config_sha,
        manifest_sha256=reg.run_manifest_pin,
    )
    head = v31_smoke.commit_all(repo, "a plan variant, registered")
    return PlanWorld(
        repo, head, prepare.sha256, files["registration"], files["manifest"], config_sha
    )


def plan_world_calls(world: PlanWorld, root: Path) -> dict[str, tuple[list, Path | None]]:
    """Every real mode's call on ``world``, by name, with the output it must not create
    when refused (None: timing, whose record starts before its gate, and plan)."""
    gated = ["--repo", str(world.repo), "--registration", world.registration]
    gated += ["--run-manifest", world.manifest, "--registration-sha256", world.config_sha]
    only = ["--repo", str(world.repo), "--code-commit", world.head]
    only += ["--prepare-sha256", world.prepare_sha]
    jobs = ("--packs", str(root / "packs"), "--attempt-id", RUN)
    (root / "cells").mkdir()
    calls: dict[str, tuple[list, Path | None]] = {
        "prepare-only": (
            ["prepare", "--mode", "prepare-only", *only, "--work", str(root / "w1")],
            root / "prepared-only",
        ),
        "registered prepare": (
            ["prepare", "--mode", "registered", *gated, "--work", str(root / "w2")],
            root / "prepared",
        ),
        "plan": (["plan", *gated], None),
        "picks": (["picks", *gated, *jobs], root / "picked"),
        "run-cell": (["run-cell", *gated, "--cell", CELL, *jobs], root / "ran"),
        "aggregate": (
            ["aggregate", *gated, "--cells", str(root / "cells"), "--attempt-id", RUN],
            root / "aggregated",
        ),
    }
    for part in v31_driver.TIMING_PARTS:
        argv = ["timing", "--part", part, *only, "--scratch", str(root / f"scratch-{part}")]
        calls[f"timing {part}"] = ([*argv, "--out", str(root / f"timing-{part}")], None)
    for argv, out in calls.values():
        if out is not None:
            argv += ["--out", str(out)]
    return calls


@pytest.mark.parametrize("case", list(PLAN_CASES))
def test_every_real_mode_refuses_any_plan_but_the_owners(registered, case, tmp_path, capsys):
    """Prepare-only, timing (each part) and every registered job (prepare, plan, picks,
    run-cell, aggregate) refuse a prepare config whose windows, dates or coin sets are not
    the owner's, before anything is fetched, read or replayed; the registered jobs also
    refuse an FX record of another day than 2024-12-31. The owner's plan passes the gate
    in every mode (the steps after it then miss this world's data: plan alone completes)."""
    windows, fx_date, refusal = PLAN_CASES[case]
    world = plan_world(registered, tmp_path / "world", windows, fx_date)
    hosts = {"inventory_transport": v31_smoke.Archives(), "legacy_transport": v31_smoke.Archives()}
    for name, (argv, out) in plan_world_calls(world, tmp_path).items():
        code, document, err = run(argv, capsys, **hosts)
        registered_job = not name.startswith(("prepare-only", "timing"))
        if refusal is not None and (registered_job or case not in REGISTERED_ONLY):
            assert code == 1 and "run refused, not the owner's plan" in err, (name, err)
            assert refusal in err, (name, err)
            assert out is None or not out.exists(), name
        else:
            assert "not the owner's plan" not in err, (name, err)
        if name == "plan" and refusal is None:
            assert code == 0 and document["cells_planned"] == 216, err
    assert all(host.requested == [] for host in hosts.values())  # nothing was fetched


# --- rule 8: the boundary (opening) quote --------------------------------------------

XRP_SPREAD = D("0.05") / 100  # the frozen spec's assumed spread, as quote_limits gives it
XRP_TICK = D("0.0001")  # the manifest's tick
XRP_LIMIT = D("0.15")  # config/default.toml's maximum_spread_pct, in percent
HOUR_A = 1_606_780_800_000 + 10 * HOUR  # 2020-12-01 10:00 UTC


def xrp_hour(case: str) -> list[Kline]:
    """The 60 replayed minutes of ``HOUR_A`` and the next hour's opening minute, around
    1.0 (every quote inside the limit), with one breaching place per ``case``."""
    minutes = [flat_bar(HOUR_A + m * MINUTE, D(1)) for m in range(61)]
    cheap = D("0.05")  # a one-tick spread is 0.2% here, over the 0.15% limit
    if case == "a mid-hour minute":
        minutes[30] = flat_bar(HOUR_A + 30 * MINUTE, cheap)
    elif case == "the opening minute":
        minutes[0] = flat_bar(HOUR_A, cheap)
    elif case == "the whole hour":
        minutes[:60] = [flat_bar(HOUR_A + m * MINUTE, cheap) for m in range(60)]
    elif case == "the opening minute's low only":
        minutes[0] = Kline(HOUR_A, D(1), D(1), cheap, D(1), D(10), D(10), D(6))
    return minutes


@pytest.mark.parametrize(
    ("case", "skipped"),
    [
        ("a mid-hour minute", ()),  # (a): the boundary quote is inside the limit
        ("the opening minute", (HOUR_A,)),  # (b): the boundary quote is rejected
        ("the whole hour", (HOUR_A,)),  # (c): as before
        ("the opening minute's low only", ()),  # the open point (index 0) is inside it
    ],
)
def test_rule_8_skips_an_hour_only_when_its_opening_quote_breaks_the_limit(case, skipped):
    minutes = xrp_hour(case)
    # The frozen rule-8 count sees a breach somewhere in the hour in every case...
    assert tick_limit_quotes(minutes, "XRPUSDT", XRP_SPREAD, XRP_TICK, XRP_LIMIT) > 0
    # ...but only a rejected opening quote leaves the hour without a boundary.
    hours = v31_driver.quote_test_hours(
        minutes, "XRPUSDT", XRP_SPREAD, XRP_TICK, XRP_LIMIT, HOUR_A - DAY, HOUR_A + DAY
    )
    assert hours == skipped
    # Outside [start, end) nothing counts, a breaching opening minute included.
    late = v31_driver.quote_test_hours(
        minutes, "XRPUSDT", XRP_SPREAD, XRP_TICK, XRP_LIMIT, HOUR_A + HOUR, HOUR_A + DAY
    )
    assert late == ()


# --- 2025 and later, snapshots ----------------------------------------------------------


def test_months_from_2025_on_are_refused_before_anything_reads_them():
    start = RESERVED - 3 * DAY
    late = PrepareWindow("w1", start, RESERVED + DAY, ("BTCUSDT",))
    with pytest.raises(ValueError, match="window w1: month 2025-01 is at or after 2025-01"):
        v31_driver.window_months(late)
    months = v31_driver.window_months(PrepareWindow("w1", start, RESERVED, ("BTCUSDT",)))
    assert (months.spot[-1], months.futures[-1], months.minutes[-1]) == ("2024-12",) * 3
    assert (months.spot[0], months.futures[0], months.minutes[0]) == (
        "2023-12",
        "2024-11",
        "2024-12",
    )
    manifest = {
        "files": [{"symbol": "BTCUSDT", "interval": "1m", "month": "2025-01", "status": "missing"}]
    }
    with pytest.raises(ValueError, match="2025-01"):
        v31_driver.present_entries(manifest, "legacy.manifest.json", v31_driver.LEGACY_KINDS)


def test_output_names_from_2025_on_are_refused(tmp_path):
    kept = tmp_path / "data" / "spot" / "BTCUSDT"
    kept.mkdir(parents=True)
    (kept / "BTCUSDT-1m-2024-12.zip").write_bytes(b"")
    (tmp_path / "v3-1-minute-bars-2021-2024.manifest.json").write_bytes(b"")
    v31_driver.refuse_sealed_names(tmp_path)  # 2021 and 2024 only
    (kept / "BTCUSDT-1m-2025-01.zip").write_bytes(b"")
    with pytest.raises(ValueError, match="-2025-"):
        v31_driver.refuse_sealed_names(tmp_path)
    (kept / "BTCUSDT-1m-2025-01.zip").unlink()
    (kept / "x-2024-2031-").mkdir()  # overlapping: both years are read
    with pytest.raises(ValueError, match="-2031-"):
        v31_driver.refuse_sealed_names(tmp_path)


def test_a_snapshot_with_a_duplicate_key_is_refused(tmp_path):
    good = b'{"symbols": [{"symbol": "BTCUSDT"}], "timezone": "UTC"}'
    duplicate = b'{"symbols": [{"symbol": "BTCUSDT", "symbol": "ETHUSDT"}]}'
    for name, raw in (("good.json", good), ("duplicate.json", duplicate)):
        (tmp_path / name).write_bytes(raw)
    raw, document = v31_driver.load_snapshot(tmp_path, FilePin("good.json", sha(good)), "spot")
    assert raw == good and document["timezone"] == "UTC"
    with pytest.raises(ValueError, match="duplicate JSON key 'symbol'"):
        v31_driver.load_snapshot(tmp_path, FilePin("duplicate.json", sha(duplicate)), "spot")
    with pytest.raises(ValueError, match="the prepare config pins"):
        v31_driver.load_snapshot(tmp_path, FilePin("good.json", "0" * 64), "futures")


# --- a prepare world ---------------------------------------------------------------------

DEC_1 = 1_606_780_800_000  # 2020-12-01 00:00 UTC
OCT_1 = 1_601_510_400_000  # 2020-10-01 00:00 UTC
NOV_1 = 1_604_188_800_000
JAN_1 = 1_609_459_200_000  # 2021-01-01 00:00 UTC
MAY_1 = 1_588_291_200_000
P_WINDOWS = {"w1": (DEC_1 + 2 * DAY, DEC_1 + 4 * DAY), "w0": (DEC_1 + 4 * DAY, DEC_1 + 6 * DAY)}
P_SYMBOLS = ["ADAUSDT", "BTCUSDT"]
PREPARE_PLAN = stand_in_plan(P_WINDOWS, P_SYMBOLS)
MASKED = DEC_1 + 2 * DAY + 5 * HOUR  # BTC lacks a minute in this hour, so its mask holds it
QUOTED = DEC_1 + 3 * DAY + 10 * HOUR  # XRP trades at 0.05 here: its quotes break rule 8
INVENTORY = "config/datasets/v3-20261009/inventory.manifest.json"
MINUTES = "config/datasets/v3-1-minute-bars/smoke-minutes.manifest.json"
V3_CONFIG = "config/v3-development-run.json"
SNAPSHOTS = {
    "spot": "config/datasets/v3-20261009/snapshots/spot.json",
    "futures": "config/datasets/v3-20261009/snapshots/futures.json",
}
FIRST_MONTHS = {"ADAUSDT": "2020-11", "BTCUSDT": "2020-11"}
PREPARE_SPEC = """name = "prepare-minutes"
purpose = "synthetic prepare test dataset (labelled synthetic)"
traded = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT"]
daily_warmup_start = "2020-05"
warmup_start = "2020-11"
start = "2020-12"
end = "2020-12"
initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""


def flat_bar(open_ms: int, price: D, wick: str = "0.0002") -> Kline:
    up, down = 1 + D(wick), 1 - D(wick)
    return Kline(open_ms, price, price * up, price * down, price, D(10), D(10) * price, D(6))


def legacy_minutes(symbol: str) -> list[Kline]:
    """Every minute of 2020-12, a two-hour saw around 1.0; XRP at 0.05 in ``QUOTED``."""
    bars = []
    for t in range(DEC_1, JAN_1, MINUTE):
        price = 1 + (t // MINUTE % 120 - 60) * D("0.0001")
        if symbol == "XRPUSDT" and QUOTED <= t < QUOTED + HOUR:
            price = D("0.05")
        bars.append(flat_bar(t, price))
    return bars


def consistent(bars) -> list[Kline]:
    """``bars`` with a quote volume of volume x close, as the frozen reader expects."""
    return [replace(bar, quote_volume=bar.volume * bar.close) for bar in bars]


def inventory_entry(host, kind: str, symbol: str, month: str, text: str | None) -> dict:
    """An inventory entry as V3's own inspection writes it, its archive on ``host``."""
    path = inventory_path_of(kind, symbol, month)
    if text is None:
        return inspect_archive(None, kind, symbol, month)
    member = f"{symbol}-{'fundingRate' if kind == 'funding' else '1h'}-{month}.csv"
    host.put(path, member, text)
    content = host.objects[path]
    entry = inspect_archive(ArchiveObject(path, sha(content), content), kind, symbol, month)
    return {**entry, "local_path": "archives/" + path.lstrip("/")}


def exchange_info(futures: bool) -> dict:
    def entry(symbol: str) -> dict:
        notional = (
            {"filterType": "MIN_NOTIONAL", "notional": "5"}
            if futures
            else {
                "filterType": "NOTIONAL",
                "minNotional": "5",
            }
        )
        document = {
            "symbol": symbol,
            "quoteAsset": "USDT",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                {
                    "filterType": "LOT_SIZE",
                    "stepSize": "0.001",
                    "minQty": "0.001",
                    "maxQty": "1000",
                },
                notional,
            ],
        }
        return {**document, "contractType": "PERPETUAL"} if futures else document

    return {"symbols": [entry(symbol) for symbol in P_SYMBOLS]}


def dumped(document: object) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("ascii")


def v3_trial(inventory_sha: str, config_sha: str) -> list[dict]:
    """V3's registered trial (family ``spec-v3``) in the trial register's schema: its
    registration and the completion pinning the inventory manifest and V3's run
    configuration (the rest of its pins stand-ins, as no V3 gate reads them here)."""
    common = {
        "schema_version": 1,
        "trial_id": "v3-synthetic",
        "recorded_at": "2024-12-31T00:00:00Z",
        "agent": "V3.1 driver tests (synthetic)",
        "family": "spec-v3",
        "parent_trial_id": None,
        "sources": ["docs/EXPERIMENT_SPEC_V3.md"],
    }
    spec = {"path": "docs/EXPERIMENT_SPEC_V3.md", "commit": "a" * 40, "sha256": "b" * 64}
    registration = {
        **common,
        "event_id": "v3-synthetic-record",
        "event_type": "registration",
        "payload": {
            "preregistered": True,
            "hypothesis": "synthetic",
            "spec": spec,
            "candidates": ["R1"],
            "sizes": [1],
            "fees": "synthetic",
            "folds": "synthetic",
            "mask": "synthetic",
            "seeds": [],
            "budget": "synthetic",
            "stopping": "synthetic",
            "selection": "synthetic",
            "data": None,
            "code": None,
        },
    }
    completion = {
        **common,
        "event_id": "v3-synthetic-complete",
        "event_type": "completion",
        "payload": {
            "registration_id": "v3-synthetic-record",
            "code_commit": "c" * 40,
            "code_sha256": "d" * 64,
            "code_paths": ["src/crypto_grid_bot/combined/baseline_v3.py"],
            "manifest": {"path": INVENTORY, "sha256": inventory_sha},
            "config": {"path": V3_CONFIG, "sha256": config_sha},
            "review": "synthetic",
        },
    }
    return [registration, completion]


def pin_inventory(repo: Path, raw: bytes, pins: dict) -> str:
    """Write the inventory manifest, V3's trial pinning it after the register's other
    events (the synthetic V3.1 trial's), and the prepare config pinning every manifest;
    return the prepare config's SHA-256."""
    (repo / INVENTORY).write_bytes(raw)
    config_raw = (repo / V3_CONFIG).read_bytes()
    register = repo / "docs/trials/register.jsonl"
    register.parent.mkdir(parents=True, exist_ok=True)
    kept = [
        line
        for line in (register.read_bytes().splitlines(keepends=True) if register.exists() else [])
        if json.loads(line)["family"] != "spec-v3"
    ]
    events = [
        (json.dumps(e, sort_keys=True) + "\n").encode("ascii")
        for e in v3_trial(sha(raw), sha(config_raw))
    ]
    register.write_bytes(b"".join(kept + events))
    document = {
        "schema": "v3.1-prepare-1",
        "windows": [
            {"id": wid, "start_ms": start, "end_ms": end, "symbols": P_SYMBOLS}
            for wid, (start, end) in P_WINDOWS.items()
        ],
        "data_manifests": {**pins, INVENTORY: sha(raw)},
        "filter_snapshots": {
            market: {"path": path, "sha256": sha((repo / path).read_bytes())}
            for market, path in SNAPSHOTS.items()
        },
    }
    prepared = dumped(document)
    (repo / "config/v3_1_prepare.json").write_bytes(prepared)
    return sha(prepared)


@dataclass(frozen=True)
class PrepareWorld:
    root: Path
    repo: Path
    head: str
    prepare_sha: str
    inventory: object  # v31_smoke.Archives: the V3 transport's host
    legacy: object  # v31_smoke.Archives: the legacy transport's host
    inventory_raw: bytes
    present: frozenset
    legacy_paths: frozenset


@pytest.fixture
def prepare_plan(monkeypatch):
    """A real-mode test on the prepare world: its plan stands in for the owner's."""
    monkeypatch.setattr(owner_plan, "OWNER_PLAN", PREPARE_PLAN)


@pytest.fixture(scope="module")
def prepare_world(module_network_blocked, tmp_path_factory) -> PrepareWorld:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path_factory.mktemp("prepare-world")
    repo = root / "repo"
    v31_smoke.init_repo(repo)
    v31_smoke.register_trial(repo)  # the code pin (the head) sits on the V3.1 registration
    inventory, legacy = v31_smoke.Archives(), v31_smoke.Archives()
    # The inventory: spot from 2020-10 (only its first 20 days, so excluded: the history
    # starts 2020-11-01) to 2020-12, futures and funding 2020-11 and 2020-12, and a missing
    # 2020-09 spot month (never fetched).
    entries = []
    spot = consistent(v31_smoke.hourly(v31_smoke.uptrend, (JAN_1 - OCT_1) // HOUR, start=OCT_1))
    futures = consistent(v31_smoke.hourly(v31_smoke.uptrend, (JAN_1 - NOV_1) // HOUR, start=NOV_1))
    for symbol in P_SYMBOLS:
        entries.append(inventory_entry(inventory, "spot", symbol, "2020-09", None))
        for month in ("2020-10", "2020-11", "2020-12"):
            first, end = month_bounds_ms(month)
            if month == "2020-10":
                end = first + 20 * DAY
            rows = [bar for bar in spot if first <= bar.open_ms < end]
            entries.append(
                inventory_entry(inventory, "spot", symbol, month, v31_smoke.kline_csv(rows, HOUR))
            )
        for month in ("2020-11", "2020-12"):
            first, end = month_bounds_ms(month)
            rows = [bar for bar in futures if first <= bar.open_ms < end]
            csv = v31_smoke.kline_csv(rows, HOUR, header=True)
            entries.append(inventory_entry(inventory, "futures", symbol, month, csv))
            records = v31_smoke.funding(first, end - 8 * HOUR)
            entries.append(
                inventory_entry(inventory, "funding", symbol, month, v31_smoke.funding_csv(records))
            )
    assert [e["status"] for e in entries if e["month"] == "2020-10"] == ["excluded", "excluded"]
    snapshots = {market: dumped(exchange_info(market == "futures")) for market in SNAPSHOTS}
    for market, path in SNAPSHOTS.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(snapshots[market])
    inventory_raw = dumped(
        {
            "schema_version": 1,
            "experiment": "v3",
            "replay_ready": False,
            "entries": sorted(entries, key=lambda e: (e["symbol"], e["month"], e["kind"])),
            "snapshots": {
                market: {"path": f"snapshots/{market}.json", "sha256": sha(raw), "bytes": len(raw)}
                for market, raw in snapshots.items()
            },
        }
    )
    # The legacy dataset: minutes and hours that agree, so the frozen mask job runs for real.
    hourly = {}
    for pair in ("BTCUSDT", "ETHUSDT", "XRPUSDT"):
        minutes = legacy_minutes(pair)
        hourly[pair] = list(aggregate(minutes))
        if pair == "BTCUSDT":
            minutes = [bar for bar in minutes if bar.open_ms != MASKED + 30 * MINUTE]
        legacy.spot_klines(pair, "1m", MINUTE, minutes)
        days = [flat_bar(MAY_1 + i * DAY, D(1), "0.01") for i in range((JAN_1 - MAY_1) // DAY)]
        legacy.spot_klines(pair, "1d", DAY, days)
    warmup = [flat_bar(NOV_1 + i * HOUR, D(1)) for i in range((DEC_1 - NOV_1) // HOUR)]
    for symbol in ("BTCUSDT", "ETHUSDT", "XRPUSDT", "BNBUSDT", "LTCUSDT"):
        december = hourly.get(symbol) or [
            flat_bar(DEC_1 + i * HOUR, D(1)) for i in range((JAN_1 - DEC_1) // HOUR)
        ]
        legacy.spot_klines(symbol, "1h", HOUR, warmup + december)
    spec_path = repo / MINUTE_SPEC_PATH
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_bytes(PREPARE_SPEC.encode("ascii"))
    filters = {"base": "X", "quote": "USDT", "tick_size": "0.0001", "quantity_step": "0.1"}
    manifest = fetch_dataset(
        load_spec(spec_path),
        root / "scratch",
        fetcher=legacy,
        instruments=lambda symbol: {**filters, "min_notional": "5"},
        now=lambda: v31_smoke._FIXED_NOW,
    )
    write_manifest(manifest_path(spec_path), manifest)
    # The V3.1 minute manifest: ADA's minutes for its flow schedules.
    ada = [flat_bar(t, D(100)) for t in range(DEC_1, DEC_1 + 7 * DAY, MINUTE)]
    legacy.spot_klines("ADAUSDT", "1m", MINUTE, ada)
    ada_path = "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2020-12.zip"
    minutes_manifest = {
        "schema": 1,
        "dataset": "smoke-minutes",
        "files": [
            {
                "symbol": "ADAUSDT",
                "interval": "1m",
                "month": "2020-12",
                "url": "https://data.binance.vision" + ada_path,
                "sha256": sha(legacy.objects[ada_path]),
                "status": "ok",
            }
        ],
    }
    (repo / MINUTES).parent.mkdir(parents=True, exist_ok=True)
    (repo / MINUTES).write_bytes(dumped(minutes_manifest))
    (repo / V3_CONFIG).write_bytes(
        dumped({"experiment": "v3", "first_months": FIRST_MONTHS, "schema_version": 1})
    )
    shutil.copyfile(v31_smoke.CHECKOUT / "config/default.toml", repo / "config/default.toml")
    (repo / "config/v3_1_experiment_menu.json").write_bytes(
        (v31_smoke.CHECKOUT / "config/v3_1_experiment_menu.json").read_bytes()
    )
    v31_smoke.write_json(repo / v31_smoke.FX_RECORD, v31_smoke.fx_record())
    for name, content in MODULES.items():  # the adapter pins read blobs at the head
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_bytes(content)
    pins = {
        MINUTE_MANIFEST_PATH: sha((repo / MINUTE_MANIFEST_PATH).read_bytes()),
        MINUTES: sha((repo / MINUTES).read_bytes()),
    }
    prepare_sha = pin_inventory(repo, inventory_raw, pins)
    head = v31_smoke.commit_all(repo, "a synthetic prepare world")
    legacy.requested.clear()
    present = frozenset(e["path"] for e in entries if e["status"] != "missing")
    legacy_paths = frozenset(
        entry["url"].removeprefix("https://data.binance.vision") for entry in manifest["files"]
    ) | {ada_path}
    return PrepareWorld(
        root, repo, head, prepare_sha, inventory, legacy, inventory_raw, present, legacy_paths
    )


class Flaky:
    """The legacy host, whose first answer for ``path`` is a transport failure (HTTP 503)."""

    def __init__(self, host, path: str) -> None:
        self.host, self.path, self.failed = host, path, False

    def archive(self, path: str) -> bytes | None:
        if path == self.path and not self.failed:
            self.failed = True
            raise FeedError(f"archive returned HTTP 503 for {path}")
        return self.host.archive(path)


class V3Builder:
    """Stands in for ``build_v3_pack`` (V3's loader needs the full 2710-entry inventory):
    records its arguments and what V3's collection layout holds, then writes a pack."""

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, inventory_root: Path, manifest_sha256: str, first_months, path: Path) -> str:
        archives = sorted(
            "/" + p.relative_to(inventory_root / "archives").as_posix()
            for p in (inventory_root / "archives").rglob("*.zip")
        )
        held = {
            "manifest": (inventory_root / "inventory.manifest.json").read_bytes(),
            "snapshots": {
                m: (inventory_root / "snapshots" / f"{m}.json").read_bytes() for m in SNAPSHOTS
            },
            "archives": archives,
        }
        self.calls.append((inventory_root, manifest_sha256, dict(first_months), path, held))
        return write_v3_pack(v31_smoke.v3_fields(), path)


def prepare_args(
    world: PrepareWorld, work: Path, out: Path, *extra: str, repo=None, mode="prepare-only"
):
    argv = ["prepare", "--mode", mode, "--repo", str(world.repo if repo is None else repo)]
    if mode == "prepare-only":
        argv += ["--code-commit", world.head, "--prepare-sha256", world.prepare_sha]
    return [*argv, "--work", str(work), "--out", str(out), *extra]


@dataclass(frozen=True)
class Prepared:
    work: Path
    out: Path
    code: int
    stdout: str
    stderr: str
    sleeps: list
    builder: V3Builder
    flaky: Flaky


@pytest.fixture(scope="module")
def prepared(module_network_blocked, prepare_world, tmp_path_factory) -> Prepared:
    """One prepare-only run, with the legacy host failing once; its cache is reused."""
    root = tmp_path_factory.mktemp("prepared")
    work, out = root / "work", root / "out"
    sleeps, builder = [], V3Builder()
    flaky = Flaky(
        prepare_world.legacy, "/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2020-12.zip"
    )
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(owner_plan, "OWNER_PLAN", PREPARE_PLAN)  # the world's plan stands in
        code, stdout, stderr = quietly(
            prepare_args(prepare_world, work, out),
            inventory_transport=prepare_world.inventory,
            legacy_transport=flaky,
            sleep=sleeps.append,
            v3_pack_builder=builder,
        )
    return Prepared(work, out, code, stdout, stderr, sleeps, builder, flaky)


def test_prepare_only_needs_no_registration_and_prints_pack_hashes(prepare_world, prepared):
    assert prepared.code == 0, prepared.stderr
    assert not (prepare_world.repo / "config/v3_1_registration.json").exists()
    document = json.loads(prepared.stdout)
    # One canonical document, printed and written beside the packs.
    assert prepared.stdout.encode("ascii") == (prepared.out / "prepare.json").read_bytes()
    assert prepared.stdout.encode("ascii") == v31_driver.canonical(document)
    assert document["schema"] == "v3.1-prepare-output-1" and document["mode"] == "prepare-only"
    assert (document["code_commit"], document["registration_sha256"]) == (prepare_world.head, None)
    assert document["prepare_sha256"] == prepare_world.prepare_sha
    config = load_prepare_config(prepare_world.repo / "config/v3_1_prepare.json")
    assert document["data_manifests"] == {pin.path: pin.sha256 for pin in config.data_manifests}
    assert document["filter_snapshots"] == {
        path: sha((prepare_world.repo / path).read_bytes()) for path in SNAPSHOTS.values()
    }
    # Each window pack, read against its printed pin, holds the printed skipped hours.
    assert set(document["window_packs"]) == {"w1", "w0"}
    for wid, pin in document["window_packs"].items():
        pack = read_pack(prepared.out / document["pack_files"][wid], pin)
        assert (pack.window_id, pack.start_ms, pack.end_ms) == (wid, *P_WINDOWS[wid])
        assert [coin.symbol for coin in pack.coins] == P_SYMBOLS
        assert list(pack.skipped_hours) == document["skipped_hours"][wid]["hours"]
        # ADA's excluded 2020-10 spot month starts its history on 2020-11-01 (Ruling P7).
        assert {coin.history_start_ms for coin in pack.coins} == {NOV_1}
    # W1's skipped hours join the frozen mask (BTC's hour without a minute) and XRP's rule-8
    # quote-test hour, each disclosed under its label; W0 takes no extra source.
    assert document["skipped_hours"]["w1"] == {
        "hours": [MASKED, QUOTED],
        "sources": {
            "minute_mask:BTCUSDT": [MASKED],
            "minute_mask:ETHUSDT": [],
            "minute_mask:XRPUSDT": [],
            "quote_test:XRPUSDT": [QUOTED],
        },
    }
    assert document["skipped_hours"]["w0"] == {"hours": [], "sources": {}}
    # The V3 input pack: built in V3's collection layout from the pinned inventory manifest,
    # snapshots and every present archive, with V3's registered calendar; its pin printed.
    ((root, manifest_sha, first_months, path, held),) = prepared.builder.calls
    assert (
        root == prepared.work / "inventory"
        and path == prepared.out / "staging" / "v3-input.pack.json.gz"
    )
    assert (manifest_sha, first_months) == (sha(prepare_world.inventory_raw), FIRST_MONTHS)
    assert held["manifest"] == prepare_world.inventory_raw
    assert held["snapshots"] == {
        m: (prepare_world.repo / p).read_bytes() for m, p in SNAPSHOTS.items()
    }
    assert set(held["archives"]) == prepare_world.present
    read_v3_pack(prepared.out / document["pack_files"]["v3"], document["v3_pack_sha256"])
    assert not (prepared.out / "staging").exists()
    # Every present archive was requested once from its own family's host, never a missing
    # one; the transport failure was retried after a logged attempt and a real sleep.
    assert sorted(prepare_world.inventory.requested) == sorted(prepare_world.present)
    assert set(prepare_world.legacy.requested) == prepare_world.legacy_paths
    assert len(prepare_world.legacy.requested) == len(prepare_world.legacy_paths)
    assert prepared.flaky.failed and prepared.sleeps == [1]
    assert f"RETRY attempt 1 of 4 for {prepared.flaky.path}" in prepared.stderr
    assert f"VERIFIED legacy {prepared.flaky.path}" in prepared.stderr
    # The legacy dataset lies as backtest reads it and verifies.
    spec_path = prepare_world.repo / MINUTE_SPEC_PATH
    verify_dataset(
        load_spec(spec_path), load_manifest(manifest_path(spec_path)), prepared.work / "legacy"
    )


def test_prepare_only_gate_refuses_another_commit_config_or_a_dirty_tree(
    prepare_world, tmp_path, capsys
):
    hosts = {"inventory_transport": v31_smoke.Archives(), "legacy_transport": v31_smoke.Archives()}
    argv = prepare_args(prepare_world, tmp_path / "work", tmp_path / "out")
    argv[argv.index("--code-commit") + 1] = "0" * 40
    argv[argv.index("--prepare-sha256") + 1] = "0" * 64
    code, _, err = run(argv, capsys, **hosts)
    assert code == 1 and "prepare gate refused" in err
    assert f"is not the code commit {'0' * 40}" in err and "not the expected '0000" in err
    dirty = tmp_path / "repo"
    shutil.copytree(prepare_world.repo, dirty)
    (dirty / "config/default.toml").write_bytes(b"# edited\n")
    code, _, err = run(
        prepare_args(prepare_world, tmp_path / "work", tmp_path / "out", repo=dirty),
        capsys,
        **hosts,
    )
    assert code == 1 and "uncommitted changes: config/default.toml" in err
    assert all(host.requested == [] for host in hosts.values()) and not (tmp_path / "out").exists()


def test_prepare_uses_the_given_transports_even_when_they_test_false(
    prepare_world, tmp_path, capsys, monkeypatch
):
    class Empty(v31_smoke.Archives):
        def __len__(self) -> int:  # an empty host evaluates as false
            return 0

    def real_transport(*args, **kwargs):
        raise AssertionError("a real guarded transport was built")

    monkeypatch.setattr(v31_driver, "V3Transport", real_transport)
    monkeypatch.setattr(v31_driver, "LegacyTransport", real_transport)
    hosts = {"inventory_transport": Empty(), "legacy_transport": Empty()}
    assert not any(hosts.values())
    argv = prepare_args(prepare_world, tmp_path / "work", tmp_path / "out")
    argv[argv.index("--code-commit") + 1] = "0" * 40  # the gate refuses before any fetch
    code, _, err = run(argv, capsys, **hosts)
    assert code == 1 and "prepare gate refused" in err


def test_prepare_refuses_any_2025_month_before_any_fetch(
    prepare_world, prepare_plan, tmp_path, capsys
):
    repo = tmp_path / "repo"
    shutil.copytree(prepare_world.repo, repo)
    inventory = json.loads(prepare_world.inventory_raw)
    late = {**inventory["entries"][-1], "month": "2025-01"}
    late["path"] = late["path"].replace("2020-12", "2025-01")
    inventory["entries"].append(late)
    config = load_prepare_config(repo / "config/v3_1_prepare.json")
    pins = {pin.path: pin.sha256 for pin in config.data_manifests if pin.path != INVENTORY}
    prepare_sha = pin_inventory(repo, dumped(inventory), pins)
    head = v31_smoke.commit_all(repo, "an inventory listing 2025-01")
    hosts = {"inventory_transport": v31_smoke.Archives(), "legacy_transport": v31_smoke.Archives()}
    argv = prepare_args(prepare_world, tmp_path / "work", tmp_path / "out", repo=repo)
    argv[argv.index("--code-commit") + 1] = head
    argv[argv.index("--prepare-sha256") + 1] = prepare_sha
    code, _, err = run(argv, capsys, **hosts)
    assert code == 1 and "month 2025-01 is at or after 2025-01" in err
    assert all(host.requested == [] for host in hosts.values())
    assert not (tmp_path / "work").exists() and not (tmp_path / "out").exists()


def registered_world(prepare_world: PrepareWorld, root: Path, document: dict) -> tuple[Path, str]:
    """A copy of the prepare world's repository registered over the prepare ``document``
    (its pack pins and skipped hours) as Task 11 registers the real run: the registration,
    its run-manifest and the V3.1 trial's completion, committed on the prepare world's
    head, the code pin. Returns the copy and the registration's SHA-256."""
    repo = root / "repo"
    shutil.copytree(prepare_world.repo, repo)
    prepare = load_prepare_config(repo / "config/v3_1_prepare.json")
    world = v31_smoke.World(root, repo, prepare_world.head, root / "unused", prepare)
    reg, config_sha = v31_smoke.register(world, document, code_pin=prepare_world.head)
    v31_smoke.complete_trial(
        repo,
        code_pin=prepare_world.head,
        config_sha256=config_sha,
        manifest_sha256=reg.run_manifest_pin,
    )
    v31_smoke.commit_all(repo, "the registration (synthetic)")
    return repo, config_sha


def test_registered_prepare_refuses_a_different_pack_hash(
    prepare_world, prepared, prepare_plan, tmp_path, capsys
):
    assert prepared.code == 0, prepared.stderr
    document = json.loads(prepared.stdout)
    hosts = {
        "inventory_transport": prepare_world.inventory,
        "legacy_transport": prepare_world.legacy,
    }

    def registered_prepare(doc, name, out):
        repo, config_sha = registered_world(prepare_world, tmp_path / name, doc)
        argv = prepare_args(
            prepare_world,
            prepared.work,
            out,
            "--registration-sha256",
            config_sha,
            repo=repo,
            mode="registered",
        )
        return (
            repo,
            config_sha,
            run(argv, capsys, sleep=lambda seconds: None, v3_pack_builder=V3Builder(), **hosts),
        )

    # A registration pinning another W1 pack: refused, and nothing final written.
    wrong = {**document, "window_packs": {**document["window_packs"], "w1": "0" * 64}}
    _, _, (code, _, err) = registered_prepare(wrong, "wrong-pack", tmp_path / "refused")
    assert code == 1 and "registered prepare did not reproduce the registration" in err
    derived = document["window_packs"]["w1"]
    assert f"window w1: pack SHA-256 {derived} differs from the pinned {'0' * 64}" in err
    assert not (tmp_path / "refused" / "packs").exists()
    assert not (tmp_path / "refused" / "prepare.json").exists()
    # A registration whose W1 skipped hours lack the quote-test hour: refused too.
    skipped = {**document["skipped_hours"], "w1": {"hours": [MASKED], "sources": {}}}
    _, _, (code, _, err) = registered_prepare(
        {**document, "skipped_hours": skipped}, "wrong-hours", tmp_path / "hours"
    )
    assert code == 1 and "window w1: the derived skipped hours differ" in err
    assert f"derived only: [{QUOTED}]" in err
    assert not (tmp_path / "hours" / "packs").exists()
    # The registration of the prepare-only document: every pin and hour reproduced. The
    # document records the registration commit, the head, as its code commit.
    repo, config_sha, (code, again, err) = registered_prepare(
        document, "true", tmp_path / "reproduced"
    )
    assert code == 0, err
    head = v31_driver.head_commit(repo)
    assert head != prepare_world.head
    assert again == {
        **document,
        "mode": "registered",
        "registration_sha256": config_sha,
        "code_commit": head,
    }
    assert (tmp_path / "reproduced" / "packs" / "window-w1.pack.json.gz").is_file()


# --- timing: the heavy steps measured before registration (Ruling F4) --------------------

RESULT_FILES = ("outcome.json", "report.json", "native_evidence.json", "attempts.jsonl")


def timing_args(world: PrepareWorld, part: str, scratch: Path, out: Path) -> list[str]:
    return [
        "timing",
        "--part",
        part,
        "--repo",
        str(world.repo),
        "--code-commit",
        world.head,
        "--prepare-sha256",
        world.prepare_sha,
        "--scratch",
        str(scratch),
        "--out",
        str(out),
    ]


def every_key(document: object) -> set[str]:
    """Every key of a JSON document, nested ones included (a phase map's names aside)."""
    if isinstance(document, dict):
        keys = set(document)
        for key, value in document.items():
            if key != "phases":
                keys |= every_key(value)
        return keys
    if isinstance(document, list):
        return set().union(*(every_key(item) for item in document)) if document else set()
    return set()


@dataclass(frozen=True)
class Timed:
    scratch: Path
    out: Path
    runs: dict  # part: (status, stdout document, stderr)
    requested: dict  # part: (inventory paths, legacy paths) the part asked for


@pytest.fixture(scope="module")
def timed(module_network_blocked, prepare_world, tmp_path_factory) -> Timed:
    """The three timing parts on the prepare world, each closed as its workflow step is,
    with V3's walk-forward the smoke's stand-in (the real one trains for hours)."""
    root = tmp_path_factory.mktemp("timing")
    scratch, out = root / "v31" / "timing-scratch", root / "v31" / "timing"
    runs, requested = {}, {}
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(baseline_v3, "run_walk_forward", v31_smoke._walk_forward)
        patch.setattr(owner_plan, "OWNER_PLAN", PREPARE_PLAN)  # the world's plan stands in
        for part in v31_driver.TIMING_PARTS:
            prepare_world.inventory.requested.clear()
            prepare_world.legacy.requested.clear()
            code, stdout, stderr = quietly(
                timing_args(prepare_world, part, scratch / part, out),
                inventory_transport=prepare_world.inventory,
                legacy_transport=prepare_world.legacy,
                sleep=lambda seconds: None,
                v3_pack_builder=V3Builder(),
            )
            runs[part] = (code, json.loads(stdout) if code == 0 else None, stderr)
            requested[part] = (
                list(prepare_world.inventory.requested),
                list(prepare_world.legacy.requested),
            )
            closing = ["timing-close", "--part", part, "--step-outcome", "success"]
            code, _, stderr = quietly(
                [*closing, "--step-timeout-minutes", "335", "--out", str(out)]
            )
            assert code == 0, stderr
    return Timed(scratch, out, runs, requested)


def test_each_timing_part_measures_its_step_and_fetches_only_what_it_needs(timed, prepare_world):
    for part in v31_driver.TIMING_PARTS:
        code, document, stderr = timed.runs[part]
        assert code == 0, (part, stderr)
        assert document["schema"] == "v3.1-timing-1" and document["part"] == part
        assert document["finished"] is True and document["code_commit"] == prepare_world.head
        assert document["elapsed_s"] >= sum(document["phases"].values()) - 0.01
    assert set(timed.runs["prepare"][1]["phases"]) == {"prepare"}
    assert set(timed.runs["picks"][1]["phases"]) == {
        "gate",
        "fetch_inventory",
        "build_v3_pack",
        "read_v3_pack",
        "picks",
    }
    assert set(timed.runs["cell"][1]["phases"]) == {
        "gate",
        "fetch_legacy",
        "verify_legacy",
        "w1_extra_skipped_hours",
        "minute_cell",
    }
    assert timed.runs["cell"][1]["cell"] == v31_driver.TIMING_CELL
    assert timed.runs["picks"][1]["attempt_records"] == 2  # the stand-in's two records
    # The picks part fetches the inventory alone, the cell part the legacy dataset alone;
    # the prepare part is the whole prepare.
    inventory, legacy = timed.requested["picks"]
    assert sorted(inventory) == sorted(prepare_world.present) and legacy == []
    inventory, legacy = timed.requested["cell"]
    assert inventory == [] and legacy and set(legacy) < prepare_world.legacy_paths
    inventory, legacy = timed.requested["prepare"]
    assert sorted(inventory) == sorted(prepare_world.present)
    assert set(legacy) == prepare_world.legacy_paths


def test_the_timing_upload_holds_only_times_memory_and_attempt_bookkeeping(timed):
    names = sorted(path.name for path in timed.out.iterdir())
    assert names == sorted(
        [
            *(
                f"{part}.{suffix}"
                for part in ("prepare", "picks", "cell")
                for suffix in (
                    "timing.jsonl",
                    "json",
                    "close.json",
                )
            ),
            "picks.attempts.jsonl",
        ]
    )
    for path in timed.out.iterdir():
        raw = path.read_bytes()
        rows = (
            [json.loads(line) for line in raw.splitlines()]
            if path.suffix == ".jsonl"
            else [json.loads(raw)]
        )
        for row in rows:
            assert every_key(row) <= v31_driver.TIMING_KEYS, (path.name, row)
        assert b"equity" not in raw and b"result" not in raw.replace(b"has_result", b"")
    # V3's attempt bookkeeping: each record's shape and timing, never its result, the
    # error's message or the picks.
    rows = [
        json.loads(line) for line in (timed.out / "picks.attempts.jsonl").read_bytes().splitlines()
    ]
    assert [(row["run"], row["state"], row["has_result"]) for row in rows] == [
        ("train-2020-12-R2L", "started", False),
        ("train-2020-12-R2L", "finished", True),
    ]
    assert all("pick_schedule" not in row and "result" not in row for row in rows)
    # Every result was written to a temporary directory and discarded: no outcome, report,
    # native evidence, attempt log or picks file is left anywhere.
    for root in (timed.out, timed.scratch):
        left = [p for p in root.rglob("*") if p.name in RESULT_FILES or p.name == "v3_picks.json"]
        assert left == [], left


def test_timing_prints_only_timing_fields(timed):
    for part, (_, document, stderr) in timed.runs.items():
        assert every_key(document) <= v31_driver.TIMING_KEYS, part
        assert "equity" not in stderr and "final" not in stderr, part


def test_a_timing_strategy_failure_is_named_by_its_type_alone(
    prepare_world, prepare_plan, tmp_path, capsys, monkeypatch
):
    def failing(*args, **kwargs):
        raise RuntimeError("final equity 12345.67")

    monkeypatch.setattr(baseline_v3, "run_walk_forward", failing)
    out = tmp_path / "timing"
    code, _, err = run(
        timing_args(prepare_world, "picks", tmp_path / "scratch", out),
        capsys,
        inventory_transport=prepare_world.inventory,
        legacy_transport=prepare_world.legacy,
        sleep=lambda seconds: None,
        v3_pack_builder=V3Builder(),
    )
    assert code == 1 and "the picks step failed with RuntimeError" in err
    assert "12345.67" not in err and "withheld" in err
    events = [json.loads(line) for line in (out / "picks.timing.jsonl").read_bytes().splitlines()]
    assert events[-1] == {**events[-1], "event": "failed", "phase": "picks"}
    assert events[-1]["error_type"] == "RuntimeError"
    assert not (out / "picks.json").exists()  # not finished
    assert b"12345.67" not in b"".join(p.read_bytes() for p in out.iterdir())


def test_timing_close_records_a_step_killed_at_its_timeout(tmp_path, capsys, monkeypatch):
    out = tmp_path / "timing"
    started = 1_800_000_000.0
    monkeypatch.setattr(v31_driver, "_wall", lambda: started)
    record = v31_driver.TimingLog(out, "picks")
    with record.phase("gate"):
        pass
    (out / "picks.attempts.jsonl").write_bytes(
        v31_driver.canonical({"seq": 1, "peak_rss_kib": 7_000_000, "state": "started"})
    )
    record.close()  # killed: never finished
    monkeypatch.setattr(v31_driver, "_wall", lambda: started + 335 * 60 + 12)
    argv = ["timing-close", "--part", "picks", "--step-outcome", "failure"]
    code, document, err = run([*argv, "--step-timeout-minutes", "335", "--out", str(out)], capsys)
    assert code == 0, err
    assert document["finished"] is False and document["timed_out"] is True
    assert document["elapsed_s_until_close"] == 335 * 60 + 12
    assert (document["last_event"], document["step_outcome"]) == ("phase", "failure")
    assert document["peak_rss_kib_seen"] >= 7_000_000 and document["attempt_records"] == 1
    assert json.loads((out / "picks.close.json").read_bytes()) == document
    # Once only, and only a step's outcome.
    code, _, err = run([*argv, "--step-timeout-minutes", "335", "--out", str(out)], capsys)
    assert code == 1 and "exists" in err
    code, _, err = run(
        ["timing-close", "--part", "cell", "--step-outcome", "maybe", "--step-timeout-minutes", "1"]
        + ["--out", str(out)],
        capsys,
    )
    assert code == 1 and "--step-outcome" in err


def test_timing_is_gated_like_prepare_only(prepare_world, tmp_path, capsys):
    hosts = {"inventory_transport": v31_smoke.Archives(), "legacy_transport": v31_smoke.Archives()}
    for part in v31_driver.TIMING_PARTS:
        argv = timing_args(prepare_world, part, tmp_path / part / "s", tmp_path / part / "t")
        argv[argv.index("--code-commit") + 1] = "0" * 40
        code, _, err = run(argv, capsys, **hosts)
        assert code == 1 and f"is not the code commit {'0' * 40}" in err, part
    assert all(host.requested == [] for host in hosts.values())
