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
2020-03 on eight, the three USDT capitals) is far beyond what a test can synthesize, so a
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
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from decimal import Decimal as D
from http.client import (
    BadStatusLine,
    HTTPException,
    HTTPMessage,
    IncompleteRead,
    LineTooLong,
    RemoteDisconnected,
)
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
    "hold": "w1.matched_spot_hold.native.c2.small",
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
    aggregate's) refuses before any request; a test of the check sets its own. Nor the
    job's start (V31_JOB_STARTED): a check's deadline is then DISPATCH_DEADLINE alone."""
    block_network(monkeypatch)
    for name in GITHUB_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("V31_JOB_STARTED", raising=False)


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
    """A synthetic world's own plan (its windows, each on ``symbols``, and the owner's
    capitals), standing in for the owner's while a real mode runs on that world."""
    return owner_plan.OwnerPlan(
        tuple(
            owner_plan.PlanWindow(wid, start, end, frozenset(symbols))
            for wid, (start, end) in windows.items()
        ),
        owner_plan.OWNER_PLAN.capitals,
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
    # Six of the 324 registered cells ran, so acceptance cannot pass: incomplete, not a crash.
    assert document["status"] == verdict["status"] == "incomplete"
    assert document["verdict_sha256"] == sha((summary / "verdict.json").read_bytes())
    assert (document["cells_registered"], document["cells_run"]) == (324, 6)
    assert len(verdict["cells"]) == 324
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
    minute_cells = document["minute_cells"]
    # Only the six selector cells read the picks; the six long-only V3 rules (36 cells)
    # replay their own rule, so they run in the main matrix and never wait for the picks.
    assert len(v3_cells) == 6 and all(".unchanged_v3_selector." in c for c in v3_cells)
    # The 144 minute cells have a matrix of their own, so no matrix passes GitHub's 256.
    files = argparse.Namespace(
        registration=v31_driver.REGISTRATION, run_manifest=v31_driver.RUN_MANIFEST
    )
    reg, _ = v31_driver.load_registered(registered.repo, files)
    kinds = {cell.cell_id: cell.kind for cell in reg.cells}
    assert len(minute_cells) == 144 and {kinds[c] for c in minute_cells} == {"minute"}
    assert len(main_cells) == 324 - 6 - 144 == 174
    assert {kinds[c] for c in main_cells} == {"v31", "hold", "v3"}
    long_only = [c for c in main_cells if "_long_only." in c and "unchanged_v3_r" in c]
    assert len(long_only) == 6 * 2 * 3
    assert sorted([*v3_cells, *minute_cells, *main_cells]) == sorted(kinds)  # each once
    for listed in (v3_cells, minute_cells, main_cells):
        assert 0 < len(listed) <= v31_driver.MAX_MATRIX == 256
    assert (document["cells_registered"], document["cells_planned"]) == (324, 324)
    # Its shape changed with the third matrix, and so did its name: no old plan passes for it.
    assert document["schema"] == v31_driver.PLAN_SCHEMA == "v3.1-plan-2"
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


SECOND_TRIAL = "v3-1-second"
CORRECTED_REGISTRATION = b'{"synthetic": "corrected registration"}\n'


def second_trial(world: TrialWorld, *, earlier: str, registration: bytes) -> TrialWorld:
    """``world`` with a second synthetic V3.1 trial on top, as Task 11 would register a
    corrected or superseding run: the first trial ``earlier`` ("corrected": a correction
    of its completion is committed first; "superseded": nothing), the second trial's
    registration event, a new code pin on top of it (the module changed), then the
    registration file as ``registration`` with the second trial's completion binding the
    new code pin, the registration and the unchanged run-manifest."""
    repo = world.repo
    register = repo / v31_smoke.TRIAL_REGISTER
    if earlier == "corrected":
        correction = v31_smoke.trial_event(
            "correction",
            {"target_id": "v3-1-synthetic-completion", "reason": "synthetic", "details": "x"},
        )
        append_event(register, correction)
    first = register_lines(repo, world.head)[0]
    append_event(
        register, {**first, "trial_id": SECOND_TRIAL, "event_id": f"{SECOND_TRIAL}-registration"}
    )
    v31_smoke.commit_all(repo, "a second V3.1 registration")
    (repo / "src/crypto_grid_bot/combined/engine.py").write_bytes(b"ENGINE = 2\n")
    code_pin = v31_smoke.commit_all(repo, "the second trial's code pin")
    (repo / v31_driver.REGISTRATION).write_bytes(registration)
    pins = {**world.pins, "code_pin": code_pin, "config_sha256": sha(registration)}
    v31_smoke.complete_trial(
        repo,
        code_pin=code_pin,
        config_sha256=pins["config_sha256"],
        manifest_sha256=pins["manifest_sha256"],
        trial_id=SECOND_TRIAL,
    )
    head = v31_smoke.commit_all(repo, "the second registration (synthetic)")
    return TrialWorld(repo, code_pin, head, pins)


@pytest.mark.parametrize("earlier", ["corrected", "superseded"])
def test_the_trial_gate_picks_the_trial_whose_completion_pins_the_registration(tmp_path, earlier):
    """Ruling R5-1: two spec-v3.1 trials, and only the second's completion pins this
    registration. The second authorizes it; the first, corrected or superseded, does not
    block it (check_ready refuses a corrected trial, so a corrected run needs a new
    registration and a new trial)."""
    world = trial_world(tmp_path)
    second = second_trial(world, earlier=earlier, registration=CORRECTED_REGISTRATION)
    events = register_lines(second.repo, second.head)
    registrations = [e["trial_id"] for e in events if e["event_type"] == "registration"]
    assert registrations == ["v3-1-synthetic", SECOND_TRIAL]
    assert v31_driver.trial_errors(second.repo, second.head, **second.pins) == []
    # The first registration's pins pick the first trial, which check_ready refuses at the
    # new head: its correction, or its config pin no longer matching the committed file.
    reason = {
        "corrected": "corrected trial requires a new registration before dispatch",
        "superseded": "committed file does not match pin",
    }[earlier]
    assert v31_driver.trial_errors(second.repo, second.head, **world.pins) == [
        f"{NOT_READY} {second.head}: {reason}"
    ]


def test_a_second_v31_registration_does_not_block_the_first_trial(tmp_path):
    """The deadlock Ruling R5-1 removes: a second spec-v3.1 registration, whose trial has
    no completion yet, used to refuse every job ("found 2" registrations); the trial is
    now the one whose completion pins the registration."""
    world = trial_world(tmp_path)
    second = {**register_lines(world.repo, world.head)[0], "trial_id": SECOND_TRIAL}
    append_event(world.repo / v31_smoke.TRIAL_REGISTER, {**second, "event_id": "v3-1-second-reg"})
    head = v31_smoke.commit_all(world.repo, "a second V3.1 registration")
    assert v31_driver.trial_errors(world.repo, head, **world.pins) == []


COUNT = "must hold one spec-v3.1 completion pinning config/v3_1_registration.json at"


@pytest.mark.parametrize(
    "case",
    [
        "no register",
        "no V3.1 completion",
        "no completion",
        "another config SHA-256",
        "another config path",
        "two completions pinning it",
    ],
)
def test_the_trial_gate_needs_exactly_one_v31_completion_pinning_the_registration(tmp_path, case):
    """Ruling R5-1: exactly one spec-v3.1 completion pins ``config/v3_1_registration.json``
    at the registration's SHA-256; none, or more than one, refuses, naming the count."""
    found = "found 0"
    if case in ("no register", "no V3.1 completion"):
        repo = tmp_path / "repo"
        v31_smoke.init_repo(repo)
        if case == "no register":
            (repo / "README.md").write_bytes(b"no register\n")
        else:  # V3's own trial alone
            register = repo / v31_smoke.TRIAL_REGISTER
            register.parent.mkdir(parents=True)
            for event in v3_trial("3" * 64, "4" * 64):
                append_event(register, event)
        head = v31_smoke.commit_all(repo, case)
        pins = {"code_pin": head, "config_sha256": "1" * 64, "manifest_sha256": "2" * 64}
    elif case == "two completions pinning it":
        first = trial_world(tmp_path)
        world = second_trial(first, earlier="superseded", registration=TRIAL_FILES["registration"])
        assert world.pins["config_sha256"] == first.pins["config_sha256"]
        repo, head, pins = world.repo, world.head, world.pins
        found = f"found 2 (v3-1-synthetic, {SECOND_TRIAL})"
    else:
        paths = {"registration": "config/other-registration.json"}
        world = trial_world(tmp_path, **(paths if case == "another config path" else {}))
        repo, head, pins = world.repo, world.head, dict(world.pins)
        if case == "no completion":  # the register as the code pin commits it
            raw = v31_driver._committed(repo, world.code_pin, v31_smoke.TRIAL_REGISTER)
            (repo / v31_smoke.TRIAL_REGISTER).write_bytes(raw)
            head = v31_smoke.commit_all(repo, "the completion dropped")
        elif case == "another config SHA-256":
            pins["config_sha256"] = "0" * 64
    if case == "no register":
        expected = f"the head {head} commits no docs/trials/register.jsonl"
    else:
        config = pins["config_sha256"]
        expected = f"docs/trials/register.jsonl at the head {head} {COUNT} {config}, {found}"
    assert v31_driver.trial_errors(repo, head, **pins) == [expected]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("another code commit", "pins code commit {code_pin}, not the registration's code pin"),
        ("another manifest SHA-256", "pins its manifest config/v3_1_run_manifest.json at {man}, "),
        ("another manifest path", "pins its manifest config/other-manifest.json at {man}, "),
    ],
)
def test_the_trial_gate_refuses_a_completion_that_binds_another_registration(
    tmp_path, case, expected
):
    """check_ready passes each of these (its pins hold at the head); the completion pins
    this registration's config but another code commit or manifest, so it does not
    authorize this one. A completion pinning another config is no completion of this
    registration at all (``found 0``, Ruling R5-1:
    ``test_the_trial_gate_needs_exactly_one_v31_completion_pinning_the_registration``)."""
    paths = {"another manifest path": {"manifest": "config/other-manifest.json"}}.get(case, {})
    world = trial_world(tmp_path, **paths)
    pins = dict(world.pins)
    changed = {
        "another code commit": "code_pin",
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
    ],
)
def test_the_trial_gate_refuses_whatever_check_ready_refuses(tmp_path, case, reason):
    """The completion pins this registration, so its trial is the one check_ready reads.
    (A dropped completion never reaches check_ready: no completion pins the registration,
    ``found 0``.)"""
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
    assert v31_driver.trial_errors(repo, head, **world.pins) == [f"{NOT_READY} {head}: {reason}"]


UNAUTHORIZED = ("no completion", "a correction")


def unauthorized(
    repo: Path, code_pin: str, root: Path, case: str, config_sha256: str
) -> tuple[Path, str]:
    """A copy of ``repo`` whose head no V3.1 completion authorizes, and the line the trial
    gate refuses it with: "no completion", the trial register as the code pin commits it
    (the V3.1 registration event without its completion), so no completion pins the
    registration; "a correction", the completion corrected, which check_ready refuses."""
    copy = root / "repo"
    shutil.copytree(repo, copy)
    register = copy / v31_smoke.TRIAL_REGISTER
    if case == "no completion":
        register.write_bytes(v31_driver._committed(copy, code_pin, v31_smoke.TRIAL_REGISTER))
    else:
        correction = v31_smoke.trial_event(
            "correction",
            {"target_id": "v3-1-synthetic-completion", "reason": "synthetic", "details": "x"},
        )
        append_event(register, correction)
    head = v31_smoke.commit_all(copy, f"the V3.1 trial's completion unauthorized: {case}")
    if case == "no completion":
        found = f"{COUNT} {config_sha256}, found 0"
        return copy, f"docs/trials/register.jsonl at the head {head} {found}"
    return copy, f"{NOT_READY} {head}: corrected trial requires a new registration before dispatch"


@pytest.mark.parametrize("case", UNAUTHORIZED)
def test_every_registered_job_and_cell_refuses_a_registration_the_trial_does_not_authorize(
    registered, smoke_plan, tmp_path, capsys, case
):
    """job_gate (registered prepare, plan, picks, aggregate) and run-cell, before it reads
    any pack, refuse a registration that no committed V3.1 completion authorizes: none
    pins it, or check_ready refuses the one that does."""
    copy, reason = unauthorized(
        registered.repo, registered.code_pin, tmp_path, case, registered.config_sha
    )
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
        assert f"\n- {reason}\n" in err, (command, err)
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
    assert v31_driver._path_errors(changed) == []
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
    assert registration["code_pin"] == code_pin and len(registration["cells"]) == 324
    # The owner's three USDT capitals, and no FX record anywhere in the world.
    assert registration["capitals"] == v31_smoke.capitals_document()
    assert [c["id"] for c in registration["capitals"]] == ["research", "medium", "small"]
    assert "config/v3_1_fx_record.json" not in listed
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
    # Every one of the three matrices gets a cell, so the rehearsal runs every matrix job.
    assert planned["v3_cells"] == ["w1.unchanged_v3_selector.native.c1.research"]
    assert planned["minute_cells"] == ["w1.matched_v0_grid_high_first.native.c1.research"]
    assert len(planned["main_cells"]) == 4 and planned["cells_planned"] == 6
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
    planned_cells = planned["main_cells"] + planned["minute_cells"] + planned["v3_cells"]
    for cell_id in planned_cells:
        folder = cells / f"cell-{cell_id}-attempt-1"
        # Each matrix job's own arguments: run-v3 passes the picks, run-minute the legacy
        # dataset, run-main neither.
        more: tuple[str, ...] = ()
        if cell_id in planned["v3_cells"]:
            more = ("--picks", str(picks_dir))
        elif cell_id in planned["minute_cells"]:
            more = ("--legacy-data", str(work / "legacy"))
        argv = rehearsal_args(
            rehearsal, "run-cell", "--cell", cell_id, *extra, "--out", str(folder), *more
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
    assert completed == set(planned_cells)
    assert verdict["v3_picks"]["state"] == "completed" and verdict["run"]["reruns"] == []
    # A rehearsal dispatches no registration: its aggregate reads no workflow runs (without
    # the runner's variables a registered one could not rule another dispatch out).
    assert verdict["run"]["other_dispatches"] == []
    assert judged["status"] == "incomplete"  # 6 of 324 cells: never a verdict
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


@pytest.mark.parametrize("case", UNAUTHORIZED)
def test_a_rehearsal_holds_the_trial_gate_on_its_world(rehearsal, tmp_path, capsys, case):
    """The rehearsal's world carries a synthetic V3.1 trial, so a rehearsal runs the trial
    gate as a registered run does: a world whose completion was dropped or corrected is
    refused."""
    document = rehearsal.document
    copy, reason = unauthorized(
        rehearsal.repo, document["code_pin"], tmp_path, case, document["registration_sha256"]
    )
    argv = rehearsal_args(rehearsal, "plan")
    argv[argv.index("--repo") + 1] = str(copy)
    code, _, err = run(argv, capsys)
    assert code == 1 and "job gate refused" in err
    assert f"\n- {reason}\n" in err, err


# --- one dispatch per registration (Codex P1, PR #269 round 4; Ruling R4-2) --------------

SHA = "e" * 64
TITLE = f"v31-run registered {SHA}"  # the workflow's run-name for a registered dispatch
NOW, EARLIER, LATER = "2026-10-13T12:00:00Z", "2026-10-13T11:59:59Z", "2026-10-13T12:00:01Z"
API = "https://api.github.com/repos/owner/repo/actions/"


def workflow_run(
    run_id, created=EARLIER, title=TITLE, status="completed", conclusion="success", attempts=1
):
    """A run as GitHub's REST API lists it: the fields the check reads (its status and
    attempts decide an earlier launch, L2), and one it ignores."""
    return {
        "id": run_id,
        "display_title": title,
        "created_at": created,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempts,
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
    """What the opener returns: a urllib response, as the dispatch check reads it (its
    status, its headers when a test gives them, its body)."""

    def __init__(self, raw: bytes, status: int = 200, headers=None) -> None:
        self.raw, self.status = raw, status
        if headers is not None:
            self.headers = HTTPMessage()
            for name, value in headers.items():
                self.headers[name] = value

    def read(self, limit: int = -1) -> bytes:
        return self.raw if limit < 0 else self.raw[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answer(document: object) -> Response:
    return Response(json.dumps(document).encode("utf-8"))


def job(job_id, name, conclusion, *, run=400, attempt=1, status="completed"):
    """A job record as GitHub's jobs listing gives it: the fields the check reads."""
    return {
        "id": job_id,
        "run_id": run,
        "run_attempt": attempt,
        "name": name,
        "status": status,
        "conclusion": conclusion,
    }


# Every job of the workflow as GitHub lists a registered launch whose plan job failed:
# the status job (always()) ran, every other job was skipped (the matrix jobs before their
# matrix expanded, so under their bare names).
STOPPED = (
    ("smoke", "skipped"),
    ("plan", "failure"),
    ("prepare", "skipped"),
    ("picks", "skipped"),
    ("run-main", "skipped"),
    ("run-minute", "skipped"),
    ("run-v3", "skipped"),
    ("aggregate", "skipped"),
    ("status", "success"),
    ("timing", "skipped"),
)
# A launch that ran: the plan job and every later one, cells included.
RAN = (
    ("smoke", "skipped"),
    ("plan", "success"),
    ("prepare", "success"),
    ("picks", "success"),
    ("run-main (w1.combined.olhc.c1.research)", "success"),
    ("run-minute (w1.matched_v0_grid_high_first.native.c1.research)", "success"),
    ("run-v3 (w1.unchanged_v3_selector.native.c1.research)", "success"),
    ("aggregate", "success"),
    ("status", "success"),
    ("timing", "skipped"),
)


def jobs_of(pattern, *, run=400, attempt=1, first=1):
    """The job records of one attempt of ``run`` laid out as ``pattern`` (name,
    conclusion), ids from ``first``."""
    return [
        job(first + index, name, conclusion, run=run, attempt=attempt)
        for index, (name, conclusion) in enumerate(pattern)
    ]


class FakeGitHub:
    """GitHub's REST API for the dispatch check, in memory (no network): the current run
    (``runs/500``), this workflow's ``runs`` in pages of 100, and each run's jobs of every
    attempt (``runs/<id>/jobs?filter=all``) in pages of 100: ``jobs`` by run id, a run that
    ran (``RAN``) by default. ``totals`` replaces a runs page's total_count; ``answers`` a
    path's response (an exception is raised), or a list of them, answered in turn before
    the default answer takes over. Records every request: its URL, method, Authorization
    header and timeout."""

    def __init__(self, runs, current=CURRENT, *, totals=None, answers=None, jobs=None):
        self.runs, self.current = list(runs), current
        self.totals, self.answers = totals or {}, answers or {}
        self.jobs = jobs or {}
        self.requests = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.requests.append(
            (url, request.get_method(), request.get_header("Authorization"), timeout)
        )
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
        listed = re.fullmatch(
            r"runs/([1-9][0-9]*)/jobs\?filter=all&per_page=100&page=([1-9][0-9]*)", path
        )
        if listed is not None:
            run_id, number = int(listed[1]), int(listed[2])
            records = self.jobs.get(run_id, jobs_of(RAN, run=run_id))
            shown = records[(number - 1) * 100 : number * 100]
            return answer({"total_count": len(records), "jobs": shown})
        page = re.fullmatch(r"workflows/v31-run\.yml/runs\?per_page=100&page=([1-9][0-9]*)", path)
        assert page is not None, url
        number = int(page[1])
        listed_runs = self.runs[(number - 1) * 100 : number * 100]
        total = self.totals.get(number, len(self.runs))
        return answer({"total_count": total, "workflow_runs": listed_runs})


def page(number: int) -> str:
    return f"workflows/v31-run.yml/runs?per_page=100&page={number}"


def jobs_page(run_id: int, number: int = 1) -> str:
    return f"runs/{run_id}/jobs?filter=all&per_page=100&page={number}"


def no_sleep(seconds):
    raise AssertionError(f"slept {seconds} s: no retry was due")


def counted(launches) -> tuple[int, ...]:
    return tuple(launch.run_id for launch in launches if launch.counts)


def uncounted(launches) -> tuple[int, ...]:
    return tuple(launch.run_id for launch in launches if not launch.counts)


@pytest.fixture
def github_env(monkeypatch):
    """The runner's variables for GitHub's API, a stand-in token among them."""
    monkeypatch.setenv("GITHUB_TOKEN", "stand-in-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "500")


def test_the_dispatch_check_reads_the_current_run_and_every_page_of_runs(github_env):
    others = [workflow_run(1000 + i, title="v31-run smoke ") for i in range(248)]
    api = FakeGitHub([CURRENT, *others, workflow_run(400)])  # 250 runs: three pages
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert (launch.run_id, launch.counts, launch.unreadable) == (400, True, False)
    # The earlier launch finished, so its jobs decide it (L2): they show a plan that ran.
    assert [url for url, *_ in api.requests] == [API + "runs/500"] + [
        API + page(n) for n in (1, 2, 3)
    ] + [API + jobs_page(400)]
    for _, method, authorization, timeout in api.requests:
        assert (method, authorization) == ("GET", "Bearer stand-in-token")
        assert timeout == v31_driver.GITHUB_TIMEOUT
    # Exactly one full page: its total ends the listing, no empty page is asked for.
    full = FakeGitHub([CURRENT, *others[:99]])
    assert v31_driver.dispatch_check(SHA, full, sleep=no_sleep) == ()
    assert [url for url, *_ in full.requests] == [API + "runs/500", API + page(1)]


def http_error(code: int, headers=None, body: bytes | None = None) -> urllib.error.HTTPError:
    """An HTTP error as urllib raises it: its headers, and its body when given."""
    message = HTTPMessage()
    for name, value in (headers or {}).items():
        message[name] = value
    stream = None if body is None else io.BytesIO(body)
    return urllib.error.HTTPError(API, code, "synthetic", message, stream)


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


# The failures a repeated read may not meet (L1): retried, five attempts in all, before the
# check fails closed on the last one. Every other case fails at once.
TRANSIENT = ("an HTTP error", "a transport failure", "a timeout")


@pytest.mark.parametrize("case", list(FAILS_CLOSED))
def test_the_dispatch_check_fails_closed(github_env, monkeypatch, case):
    variables, api, message = FAILS_CLOSED[case]
    for name, value in variables.items():
        if value is None:
            monkeypatch.delenv(name)
        else:
            monkeypatch.setenv(name, value)
    slept = []
    with pytest.raises(ValueError, match=re.escape(message)) as refused:
        v31_driver.dispatch_check(SHA, api, sleep=slept.append)
    assert "stand-in-token" not in str(refused.value)  # no message ever carries the token
    if variables:  # a missing or malformed variable: refused before any request
        assert api.requests == []
    if case in TRANSIENT:
        assert slept == [15, 30, 60, 120]
        assert "still failing after 5 attempts" in str(refused.value)
        (failing,) = {url for url, *_ in api.requests[-1:]}
        assert [url for url, *_ in api.requests].count(failing) == 5
    else:
        assert slept == []


def test_the_dispatch_check_refuses_a_body_beyond_its_limit(github_env, monkeypatch):
    monkeypatch.setattr(v31_driver, "MAX_GITHUB_BYTES", 16)
    with pytest.raises(ValueError, match="larger than 16 bytes"):
        v31_driver.dispatch_check(SHA, FakeGitHub([CURRENT]), sleep=no_sleep)


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
    code, document, err = run(argv, capsys, github_opener=later, sleep=no_sleep)
    assert code == 0, err
    assert document == {
        "schema": "v3.1-dispatch-check-1",
        "report_only": False,
        "registration_sha256": SHA,
        "other_dispatches": [],
        "uncounted_dispatches": [],
    }
    earlier = FakeGitHub([CURRENT, workflow_run(400), workflow_run(300, status="queued")])
    code, _, err = run(argv, capsys, github_opener=earlier, sleep=no_sleep)
    # The first that counts is named, with why: still queued. It decides the refusal, so
    # no later launch is judged (run 400's jobs are never read).
    assert code == 1 and "another dispatch of this registration: run 300; " in err
    assert "run 300: its status is 'queued', not completed" in err
    assert "run 400" not in err
    assert API + jobs_page(400) not in [url for url, *_ in earlier.requests]
    slept = []
    failing = FakeGitHub([CURRENT], answers={"runs/500": http_error(502)})
    code, _, err = run(argv, capsys, github_opener=failing, sleep=slept.append)
    assert code == 1 and "HTTP 502" in err and "still failing after 5 attempts" in err
    assert slept == [15, 30, 60, 120]
    code, _, err = run(["dispatch-check", "--registration-sha256", "E" * 64], capsys)
    assert code == 1 and "64 lowercase hex" in err


def test_a_registered_aggregate_leaves_the_verdict_incomplete_on_another_dispatch(
    registered, smoke_plan, tmp_path, capsys, monkeypatch
):
    """The aggregate reads the workflow's runs in a registered run (Ruling R4-2), and
    names another dispatch of its registration in the verdict, or why none could be ruled
    out; a rehearsal's aggregate never reads them (test_the_rehearsal_runs_...). An earlier
    launch stopped at the plan job with nothing run is named apart and does not count
    (owner decision v31-d21)."""
    title = f"v31-run registered {registered.config_sha}"
    current = workflow_run(38267478452, created=NOW, title=title, status="in_progress")
    cells = tmp_path / "cells"
    cells.mkdir()

    def aggregate_with(name, api):
        argv = registered_args(registered, "aggregate", "--cells", str(cells))
        argv += ["--attempt-id", RUN, "--out", str(tmp_path / name)]
        code, document, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
        assert code == 0, err
        verdict = json.loads((tmp_path / name / "summary" / "verdict.json").read_bytes())
        assert document["status"] == verdict["status"] == "incomplete"
        return verdict["run"]["other_dispatches"], verdict["run"]["uncounted_dispatches"]

    # Without the runner's variables: no other dispatch can be ruled out.
    (reason,), none = aggregate_with("no-variables", None)
    assert reason.startswith("another dispatch of this registration could not be ruled out: ")
    assert "GITHUB_TOKEN is not set" in reason and none == []
    monkeypatch.setenv("GITHUB_TOKEN", "stand-in-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "38267478452")
    seen = FakeGitHub([current, workflow_run(400, title=title)], current)
    seen.answers["runs/38267478452"] = answer(current)
    assert aggregate_with("another", seen) == (
        [
            "another dispatch of this registration: run 400 (its plan job 'plan' (job 2, "
            "attempt 1) ended 'success', not failure)"
        ],
        [],
    )
    alone = FakeGitHub([current, workflow_run(600, created=LATER, title=title)], current)
    alone.answers["runs/38267478452"] = answer(current)
    assert aggregate_with("alone", alone) == ([], [])
    assert alone.requests  # the check ran
    stopped = FakeGitHub(
        [current, workflow_run(400, title=title, conclusion="failure")],
        current,
        jobs={400: jobs_of(STOPPED)},
    )
    stopped.answers["runs/38267478452"] = answer(current)
    line = "earlier launch 400 stopped at the plan job with nothing run; not counted"
    assert aggregate_with("stopped", stopped) == ([], [line])
    text = (tmp_path / "stopped" / "summary" / "summary.md").read_text(encoding="utf-8")
    assert f"- {line}" in text and "None that counts" in text


# --- L2: an earlier launch counts unless it provably did nothing (owner decision v31-d21) --

DONE = workflow_run(400, conclusion="failure")  # a finished earlier launch, one attempt


def test_a_launch_stopped_at_the_plan_job_with_nothing_run_does_not_count():
    assert v31_driver.launch_reason(DONE, jobs_of(STOPPED)) is None
    # Only the plan job and the status job listed (GitHub lists no skipped job).
    only = [job(1, "plan", "failure"), job(2, "status", "success")]
    assert v31_driver.launch_reason(DONE, only) is None
    # The status job always runs, whatever it ends with.
    for ended in ("success", "failure", "cancelled", "skipped", None):
        jobs = [job(1, "plan", "failure"), job(2, "status", ended)]
        assert v31_driver.launch_reason(DONE, jobs) is None, ended
    # The matrix jobs under their matrix values, skipped, and in any order.
    named = [
        job(10, "run-minute (w1.matched_v0_grid_high_first.native.c1.research)", "skipped"),
        job(9, "run-main (w1.combined.olhc.c1.research)", "skipped"),
        job(8, "run-v3 (w1.unchanged_v3_selector.native.c1.research)", "skipped"),
        job(7, "timing (prepare)", "skipped"),
        job(6, "plan", "failure"),
    ]
    assert v31_driver.launch_reason(DONE, named) is None
    assert v31_driver.launch_reason(DONE, tuple(jobs_of(STOPPED))) is None
    # A re-run of the failed plan that failed again, every later job skipped again.
    twice = workflow_run(400, attempts=2, conclusion="failure")
    jobs = jobs_of(STOPPED) + jobs_of(STOPPED, attempt=2, first=100)
    assert v31_driver.launch_reason(twice, jobs) is None
    # How the plan's output and the verdict name it.
    assert v31_driver.uncounted_line(400) == (
        "earlier launch 400 stopped at the plan job with nothing run; not counted"
    )


def stopped_but(name, conclusion):
    """``STOPPED`` with the job ``name`` ending ``conclusion`` (added when not listed)."""
    pattern = [(n, c) for n, c in STOPPED if n != name] + [(name, conclusion)]
    return jobs_of(pattern)


@pytest.mark.parametrize(
    ("jobs", "message"),
    [
        (
            stopped_but("plan", "success"),
            "its plan job 'plan' (job 10, attempt 1) ended 'success'",
        ),
        (stopped_but("plan", "cancelled"), "ended 'cancelled', not failure"),
        (stopped_but("plan", "timed_out"), "ended 'timed_out', not failure"),
        (stopped_but("plan", None), "ended None, not failure"),
        ([j for j in jobs_of(STOPPED) if j["name"] != "plan"], "no plan job is listed"),
        ([job(1, "status", "success")], "no plan job is listed"),
        ([], "no job is listed for its attempt(s) 1"),
    ],
)
def test_a_launch_whose_plan_job_did_not_fail_counts(jobs, message):
    reason, malformed = v31_driver.launch_decision(DONE, jobs)
    assert reason is not None and message in reason
    assert v31_driver.launch_reason(DONE, jobs) == reason
    # A decision on well-formed records; only an attempt with no job record at all lacks
    # the shape the rule reads.
    assert malformed is (jobs == [])


LATER_JOBS = (
    "smoke",
    "prepare",
    "picks",
    "aggregate",
    "timing",
    "run-main",
    "run-minute",
    "run-v3",
)


@pytest.mark.parametrize("ended", ["success", "failure", "cancelled", "timed_out", None])
@pytest.mark.parametrize(
    "name",
    [
        *LATER_JOBS,
        "run-main (cell-x)",
        "run-minute (w1.matched_v0_grid_high_first.native.c1.research)",
        "run-v3 (w1.unchanged_v3_selector.native.c1.research)",
        "timing (picks)",
    ],
)
def test_a_launch_any_later_job_of_which_was_not_skipped_counts(name, ended):
    reason, malformed = v31_driver.launch_decision(DONE, stopped_but(name, ended))
    assert reason is not None and f"its job {name!r}" in reason
    assert f"ended {ended!r}, not skipped: it ran" in reason
    assert malformed is False  # an unexpected conclusion is a decision


@pytest.mark.parametrize(
    "name",
    [
        "deploy",
        "Plan",
        "plan (x)",
        "prepare (x)",
        "status (x)",
        "aggregate (x)",
        "run-main(cell-x)",
        "run-main (cell-x",
        "run-mainx",
        "run-minutes (cell-x)",
        "run-minute(cell-x)",
        "",
    ],
)
def test_a_launch_with_a_job_of_an_unknown_name_counts(name):
    jobs = [*jobs_of(STOPPED), job(50, name, "skipped")]
    reason, malformed = v31_driver.launch_decision(DONE, jobs)
    assert reason is not None and "is not a job of this workflow" in reason
    assert malformed is False  # an unknown name is a decision


@pytest.mark.parametrize(
    ("status", "conclusion"),
    [("queued", None), ("waiting", None), ("in_progress", None), ("requested", None), (None, None)],
)
def test_a_launch_queued_or_running_counts_whatever_its_jobs(status, conclusion):
    run_ = workflow_run(400, status=status, conclusion=conclusion)
    reason, malformed = v31_driver.launch_decision(run_, jobs_of(STOPPED))
    assert reason is not None and f"its status is {status!r}, not completed" in reason
    assert malformed is (status is None)  # a missing status is a missing field


def test_a_second_attempt_that_ran_prepare_counts():
    twice = workflow_run(400, attempts=2, conclusion="success")
    jobs = jobs_of(STOPPED) + jobs_of(RAN, attempt=2, first=100)
    reason = v31_driver.launch_reason(twice, jobs)
    assert reason is not None and "(job 101, attempt 2) ended 'success', not failure" in reason
    # The plan job failed again in attempt 2, but prepare ran.
    rerun = [(n, "success" if n == "prepare" else c) for n, c in STOPPED]
    reason = v31_driver.launch_reason(
        twice, jobs_of(STOPPED) + jobs_of(rerun, attempt=2, first=100)
    )
    assert reason is not None and "'prepare' (job 102, attempt 2) ended 'success'" in reason
    # An attempt that lists no job cannot be shown to have done nothing.
    reason = v31_driver.launch_reason(twice, jobs_of(STOPPED))
    assert reason == "no job is listed for its attempt(s) 2"


def with_field(key, value, index=1):
    """``STOPPED``'s job records with record ``index``'s ``key`` set to ``value`` (or
    removed, for ``without``)."""
    jobs = jobs_of(STOPPED)
    if value is without:
        del jobs[index][key]
    else:
        jobs[index][key] = value
    return jobs


@pytest.mark.parametrize(
    ("run_", "jobs", "message"),
    [
        ("a run", jobs_of(STOPPED), "its run record is not a JSON object"),
        (without(DONE, "status"), jobs_of(STOPPED), "its status is None"),
        (without(DONE, "run_attempt"), jobs_of(STOPPED), "its run_attempt is None"),
        ({**DONE, "run_attempt": 0}, jobs_of(STOPPED), "its run_attempt is 0"),
        ({**DONE, "run_attempt": True}, jobs_of(STOPPED), "its run_attempt is True"),
        ({**DONE, "run_attempt": "1"}, jobs_of(STOPPED), "its run_attempt is '1'"),
        (DONE, None, "its jobs are not a list"),
        (DONE, {"jobs": jobs_of(STOPPED)}, "its jobs are not a list"),
        (DONE, [*jobs_of(STOPPED), "a job"], "its job record 11 is not a JSON object"),
        (DONE, with_field("id", without), "its job record 2 has id None"),
        (DONE, with_field("id", 0), "has id 0"),
        (DONE, with_field("id", True), "has id True"),
        (DONE, with_field("id", "2"), "has id '2'"),
        (DONE, with_field("id", 1), "its job 1 is listed twice"),
        (DONE, with_field("run_id", without), "its job 2 has run_id None, not 400"),
        (DONE, with_field("run_id", 401), "has run_id 401, not 400"),
        (DONE, with_field("run_id", "400"), "has run_id '400'"),
        (DONE, with_field("run_attempt", without), "has run_attempt None, not 1 to 1"),
        (DONE, with_field("run_attempt", 2), "has run_attempt 2, not 1 to 1"),
        (DONE, with_field("run_attempt", 0), "has run_attempt 0"),
        (DONE, with_field("run_attempt", True), "has run_attempt True"),
        (DONE, with_field("name", without), "has no string name and status"),
        (DONE, with_field("name", 7), "has no string name and status"),
        (DONE, with_field("status", without), "has no string name and status"),
        (DONE, with_field("conclusion", 7), "has conclusion 7, not a string or null"),
        (DONE, with_field("conclusion", without), "ended None, not failure"),
    ],
)
def test_a_launch_with_a_malformed_run_or_job_record_counts(run_, jobs, message):
    reason, malformed = v31_driver.launch_decision(run_, jobs)
    assert reason is not None and message in reason
    # Every case lacks the shape the rule reads, but a missing conclusion, which reads as
    # null: that plan job just did not fail.
    assert malformed is (message != "ended None, not failure")


def test_the_check_judges_each_earlier_launch_on_its_jobs(github_env):
    """Through the HTTP layer: the jobs of every attempt, every page (250 records, three
    pages), decide a finished launch; one still running counts without them. A registered
    check stops at the first launch that counts (it already refuses); a report-only check
    judges them all."""
    skipped_cells = [(f"run-main (cell-{i})", "skipped") for i in range(250 - len(STOPPED))]
    many = jobs_of([*STOPPED, *skipped_cells], run=300)
    assert len(many) == 250

    def runs(title):
        return [
            rehearsal_run(500, created=NOW, title=title, status="in_progress"),
            rehearsal_run(300, title=title, conclusion="failure"),
            rehearsal_run(301, title=title),  # it ran (RAN): it counts
            rehearsal_run(400, title=title, status="in_progress", conclusion=None),
        ]

    registered = runs(TITLE)
    api = FakeGitHub(registered, registered[0], jobs={300: many})
    launches = v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert (counted(launches), uncounted(launches)) == ((301,), (300,))
    assert launches[0].reason is None
    urls = [url for url, *_ in api.requests]
    assert urls == [API + "runs/500", API + page(1)] + [
        API + jobs_page(300, n) for n in (1, 2, 3)
    ] + [API + jobs_page(301)]  # 400 is never judged: 301 decides the refusal
    rehearsals = runs(REHEARSAL)
    api = FakeGitHub(rehearsals, rehearsals[0], jobs={300: many})
    launches = v31_driver.dispatch_check("", api, sleep=no_sleep, report_only=True)
    assert (counted(launches), uncounted(launches)) == ((301, 400), (300,))
    assert "its status is 'in_progress'" in launches[2].reason
    urls = [url for url, *_ in api.requests]
    # A report-only check also reads this run's own jobs (the probe, right after it).
    assert urls == [API + "runs/500", API + jobs_page(500), API + page(1)] + [
        API + jobs_page(300, n) for n in (1, 2, 3)
    ] + [API + jobs_page(301)]  # nothing for 400: queued or running, it counts


@pytest.mark.parametrize(
    ("answers", "message", "slept"),
    [
        ([http_error(502)] * 5, "HTTP 502 (still failing after 5 attempts)", [15, 30, 60, 120]),
        ([urllib.error.URLError("down")] * 5, "URLError", [15, 30, 60, 120]),
        ([http_error(404)], "HTTP 404", []),
        ([Response(b"<html>")], "not JSON", []),
        ([answer({"total_count": 1})], "total_count and jobs required", []),
        ([answer({"total_count": 1, "jobs": [1, 2]})], "2 jobs listed, more than total", []),
    ],
)
def test_a_launch_whose_jobs_cannot_be_read_counts(github_env, answers, message, slept):
    """Fail closed: a jobs listing that still fails after L1's retries, or fails for good
    at once, makes the launch count; in a registered check it is no read failure of the
    check itself, so the plan refuses on it as on any launch that counts."""
    api = FakeGitHub(
        [CURRENT, workflow_run(300, conclusion="failure")],
        answers={jobs_page(300): list(answers)},
        jobs={300: jobs_of(STOPPED, run=300)},
    )
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert (launch.run_id, launch.counts, launch.unreadable) == (300, True, True)
    # A 404 means the run was deleted since the listing: gone, and it counts all the same.
    gone = message == "HTTP 404"
    prefix = "gone (404): " if gone else ""
    assert launch.reason.startswith(f"{prefix}its jobs could not be read: GitHub API ")
    assert launch.gone is gone
    assert message in launch.reason and waits == slept


def test_the_jobs_pages_must_agree(github_env):
    """A job listed on two pages, or a total that changes between them, is a pagination
    inconsistency: the launch counts, unreadable, with no retry."""
    cells = ((f"run-v3 (c{i})", "skipped") for i in range(109 - len(STOPPED)))
    records = jobs_of([*STOPPED, *cells], run=300)
    assert len(records) == 109
    twice = {**records[100], "id": records[0]["id"]}
    api = FakeGitHub(
        [CURRENT, workflow_run(300, conclusion="failure")],
        jobs={300: [*records[:100], twice, *records[101:]]},
    )
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert launch.unreadable and "job 1 is listed twice: the pages disagree" in launch.reason
    moved = FakeGitHub(
        [CURRENT, workflow_run(300, conclusion="failure")],
        answers={jobs_page(300, 2): answer({"total_count": 110, "jobs": records[100:]})},
        jobs={300: records},
    )
    (launch,) = v31_driver.dispatch_check(SHA, moved, sleep=no_sleep)
    assert launch.unreadable and "total_count changed from 109 to 110" in launch.reason


# --- L1: glitch-type reads are retried before the check fails closed (v31-d21) ----------


def test_a_server_error_then_success_passes_after_one_retry(github_env, capsys):
    api = FakeGitHub([CURRENT], answers={"runs/500": [http_error(503)]})
    slept = []
    assert v31_driver.dispatch_check(SHA, api, sleep=slept.append) == ()
    assert slept == [15]  # the first backoff
    assert [url for url, *_ in api.requests] == [API + "runs/500"] * 2 + [API + page(1)]
    err = capsys.readouterr().err
    assert (
        "dispatch check: the current run: attempt 1 of 5 failed (GitHub API "
        "/repos/owner/repo/actions/runs/500: HTTP 503); retrying in 15 s"
    ) in err


@pytest.mark.parametrize(
    ("headers", "slept"),
    [
        ({"Retry-After": "200"}, [120]),  # capped at 120 s
        ({"Retry-After": "45"}, [45]),  # longer than the first backoff: honoured
        ({"Retry-After": "5"}, [15]),  # shorter: the backoff stands
        ({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}, [15]),  # not seconds: the backoff
        ({}, [15]),
    ],
)
def test_a_rate_limit_honours_a_longer_retry_after_up_to_the_cap(github_env, headers, slept):
    api = FakeGitHub([CURRENT], answers={page(1): [http_error(429, headers)]})
    waits = []
    assert v31_driver.dispatch_check(SHA, api, sleep=waits.append) == ()
    assert waits == slept


def test_a_rate_limited_403_is_retried_and_any_other_403_is_not(github_env):
    for headers in ({"Retry-After": "60"}, {"x-ratelimit-remaining": "0"}):
        api = FakeGitHub([CURRENT], answers={page(1): [http_error(403, headers)]})
        waits = []
        assert v31_driver.dispatch_check(SHA, api, sleep=waits.append) == (), headers
        assert waits == [60 if "Retry-After" in headers else 15]
    for headers in ({}, {"x-ratelimit-remaining": "59"}):
        api = FakeGitHub([CURRENT], answers={page(1): [http_error(403, headers)]})
        with pytest.raises(ValueError, match="HTTP 403"):
            v31_driver.dispatch_check(SHA, api, sleep=no_sleep)


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("timed out"),
        RemoteDisconnected("Remote end closed connection without response"),  # no reply
        urllib.error.URLError("no route"),
        ConnectionResetError("reset"),
        ConnectionRefusedError("refused"),
    ],
)
def test_no_reply_a_timeout_or_a_connection_error_then_success_passes(github_env, failure):
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={page(1): [failure]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [15]


def test_five_failures_refuse_after_five_attempts_naming_the_last_error(github_env, capsys):
    failures = [http_error(500), urllib.error.URLError("down"), TimeoutError(), http_error(502)]
    api = FakeGitHub([CURRENT], answers={"runs/500": [*failures, http_error(504)]})
    waits = []
    with pytest.raises(ValueError, match=r"HTTP 504 \(still failing after 5 attempts\)$"):
        v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert waits == [15, 30, 60, 120]
    assert [url for url, *_ in api.requests] == [API + "runs/500"] * 5
    err = capsys.readouterr().err
    for attempt in (1, 2, 3, 4):
        assert f"attempt {attempt} of 5 failed" in err
    assert "attempt 5 of 5" not in err


@pytest.mark.parametrize("code", [400, 401, 404, 410, 422, 301])
def test_a_permanent_http_error_refuses_at_once(github_env, code):
    api = FakeGitHub([CURRENT], answers={page(1): [http_error(code, {"Retry-After": "1"})]})
    with pytest.raises(ValueError, match=f"HTTP {code}"):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert [url for url, *_ in api.requests] == [API + "runs/500", API + page(1)]


@pytest.mark.parametrize(
    "response",
    [
        Response(b"<html>"),
        Response(b'{"total_count": 1, "total_count": 1, "workflow_runs": []}'),
        answer({"total_count": 1}),
        answer([]),
    ],
)
def test_malformed_json_refuses_at_once(github_env, response):
    api = FakeGitHub([CURRENT], answers={page(1): [response]})
    with pytest.raises(ValueError, match="GitHub API"):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)


def test_the_current_run_missing_once_then_present_passes(github_env, capsys):
    """GitHub's listing can lag a run just created: the whole listing is read again."""
    lagging = answer({"total_count": 1, "workflow_runs": [workflow_run(400)]})
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={page(1): [lagging]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [15]
    assert "the current run 500 is not among this workflow's runs" in capsys.readouterr().err
    # Missing at every attempt: refused after five, naming it.
    always = FakeGitHub([workflow_run(400)])
    waits = []
    with pytest.raises(ValueError, match="the current run 500 is not among"):
        v31_driver.dispatch_check(SHA, always, sleep=waits.append)
    assert waits == [15, 30, 60, 120]


def test_a_found_counting_dispatch_refuses_with_no_retry(github_env, capsys):
    """A launch that counts is a decision, not a read failure: never retried."""
    api = FakeGitHub([CURRENT, workflow_run(400, status="in_progress", conclusion=None)])
    argv = ["dispatch-check", "--registration-sha256", SHA]
    code, _, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1 and "another dispatch of this registration: run 400" in err
    assert len(api.requests) == 2  # the current run and one page: nothing read twice


def test_the_retries_take_about_five_minutes_and_each_wait_is_capped():
    assert v31_driver.GITHUB_ATTEMPTS == 5
    assert v31_driver.GITHUB_BACKOFF == (15, 30, 60, 120)
    assert len(v31_driver.GITHUB_BACKOFF) == v31_driver.GITHUB_ATTEMPTS - 1
    assert sum(v31_driver.GITHUB_BACKOFF) == 225  # with the reads' own time: about 5 minutes
    assert v31_driver.MAX_GITHUB_WAIT == 120 == max(v31_driver.GITHUB_BACKOFF)


# --- L3: the rehearsal proves the check against GitHub, report-only (v31-d21) ------------

REHEARSAL = "v31-run rehearsal "  # the run-name with an empty registration_sha256 input


def rehearsal_run(run_id, created=EARLIER, title=REHEARSAL, **fields):
    return workflow_run(run_id, created=created, title=title, **fields)


@pytest.mark.parametrize("current_title", [REHEARSAL, "v31-run rehearsal"])
def test_a_report_only_check_prints_its_decision_and_exits_0(github_env, capsys, current_title):
    current = rehearsal_run(500, created=NOW, title=current_title, status="in_progress")
    api = FakeGitHub(
        [
            current,
            rehearsal_run(400),  # an earlier rehearsal that ran: it counts
            rehearsal_run(300, title="v31-run rehearsal", conclusion="failure"),  # stopped
            rehearsal_run(200, title=TITLE),  # a registered run: another title
            rehearsal_run(600, created=LATER),  # created later: never counts
        ],
        current,
        jobs={300: jobs_of(STOPPED, run=300)},
    )
    argv = ["dispatch-check", "--report-only", "--registration-sha256", ""]
    code, document, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 0, err
    assert document == {
        "schema": "v3.1-dispatch-check-1",
        "report_only": True,
        "registration_sha256": "",
        "other_dispatches": [
            "run 400: its plan job 'plan' (job 2, attempt 1) ended 'success', not failure"
        ],
        "uncounted_dispatches": [
            "earlier launch 300 stopped at the plan job with nothing run; not counted"
        ],
    }
    assert "a registered check would refuse; counted: run 400" in err
    # Nothing before it: a registered check would pass.
    alone = FakeGitHub([current], current)
    code, document, err = run(argv, capsys, github_opener=alone, sleep=no_sleep)
    assert code == 0, err
    assert (document["other_dispatches"], document["uncounted_dispatches"]) == ([], [])
    assert "would pass; counted: none; not counted: none" in err


def test_a_report_only_check_takes_a_rehearsal_sha_and_refuses_a_malformed_one(github_env, capsys):
    current = rehearsal_run(500, created=NOW, title=f"v31-run rehearsal {SHA}")
    api = FakeGitHub([current, rehearsal_run(400, title=f"v31-run rehearsal {SHA}")], current)
    argv = ["dispatch-check", "--report-only", "--registration-sha256", SHA]
    code, document, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 0, err
    assert [line.split(":")[0] for line in document["other_dispatches"]] == ["run 400"]
    for bad in ("E" * 64, "e" * 63, "not a sha", " "):
        argv = ["dispatch-check", "--report-only", "--registration-sha256", bad]
        code, _, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
        assert code == 1 and "a rehearsal's may be empty" in err, bad
    # A current run of another title (a registered one) is refused: its own title only.
    registered_current = FakeGitHub([CURRENT], CURRENT)
    argv = ["dispatch-check", "--report-only", "--registration-sha256", ""]
    code, _, err = run(argv, capsys, github_opener=registered_current, sleep=no_sleep)
    assert code == 1 and "is titled" in err


def test_a_report_only_check_exits_non_zero_when_github_cannot_be_read(
    github_env, capsys, monkeypatch
):
    current = rehearsal_run(500, created=NOW, status="in_progress")
    argv = ["dispatch-check", "--report-only", "--registration-sha256", ""]
    listing = FakeGitHub([current], current, answers={page(1): http_error(502)})
    waits = []
    code, _, err = run(argv, capsys, github_opener=listing, sleep=waits.append)
    assert code == 1 and "HTTP 502 (still failing after 5 attempts)" in err
    assert waits == [15, 30, 60, 120]
    # An earlier launch's jobs that cannot be read: still a failure to read GitHub.
    jobs = FakeGitHub(
        [current, rehearsal_run(400)], current, answers={jobs_page(400): http_error(503)}
    )
    waits = []
    code, _, err = run(argv, capsys, github_opener=jobs, sleep=waits.append)
    assert code == 1 and "could not read GitHub's records: run 400" in err
    assert waits == [15, 30, 60, 120]
    # Without the runner's variables: refused before any request.
    for name in GITHUB_VARIABLES:
        monkeypatch.delenv(name)
    untouched = FakeGitHub([current], current)
    code, _, err = run(argv, capsys, github_opener=untouched, sleep=no_sleep)
    assert code == 1 and "GITHUB_TOKEN is not set" in err and untouched.requests == []


def test_a_registered_check_still_refuses_a_counted_duplicate_and_names_uncounted_ones(
    github_env, capsys
):
    argv = ["dispatch-check", "--registration-sha256", SHA]
    stopped = workflow_run(300, conclusion="failure")
    api = FakeGitHub([CURRENT, stopped, workflow_run(400)], jobs={300: jobs_of(STOPPED, run=300)})
    code, _, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1
    assert "another dispatch of this registration: run 400; a registration is dispatched" in err
    assert "earlier launch 300 stopped at the plan job with nothing run; not counted" in err
    # Only a stopped launch before it: the registered run goes on, and its output names it.
    alone = FakeGitHub([CURRENT, stopped], jobs={300: jobs_of(STOPPED, run=300)})
    code, document, err = run(argv, capsys, github_opener=alone, sleep=no_sleep)
    assert code == 0, err
    assert document["other_dispatches"] == [] and document["report_only"] is False
    assert document["uncounted_dispatches"] == [
        "earlier launch 300 stopped at the plan job with nothing run; not counted"
    ]
    # A registered check never takes an empty pin, nor looks at the rehearsal's titles.
    code, _, err = run(["dispatch-check", "--registration-sha256", ""], capsys, sleep=no_sleep)
    assert code == 1 and "64 lowercase hex" in err
    rehearsals = FakeGitHub([CURRENT, rehearsal_run(400), rehearsal_run(401, title="v31-run")])
    code, document, err = run(argv, capsys, github_opener=rehearsals, sleep=no_sleep)
    assert code == 0 and document["other_dispatches"] == [], err


def test_the_rehearsal_titles():
    assert v31_driver.run_titles("registered", SHA) == (TITLE,)
    assert v31_driver.run_titles("rehearsal", SHA) == (f"v31-run rehearsal {SHA}",)
    assert v31_driver.run_titles("rehearsal", "") == ("v31-run rehearsal ", "v31-run rehearsal")
    runs = [rehearsal_run(500, created=NOW, title="v31-run rehearsal"), rehearsal_run(400)]
    assert v31_driver.other_dispatches(runs, runs[0], "", mode="rehearsal") == (400,)
    with pytest.raises(ValueError, match="is titled"):
        v31_driver.other_dispatches(runs, runs[0], "")  # a registered check: not its title


# --- the review's fix round: one deadline, replies cut short, a deleted run, page 2 -------


class FakeTime:
    """An injected clock and sleep: sleeping moves the clock, and a ``slowed`` opener moves
    it ``per_request`` seconds with each request it makes."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def slowed(self, api, per_request):
        def opener(request, timeout):
            self.now += per_request
            return api(request, timeout)

        return opener


def test_a_long_outage_stops_at_the_deadline_so_the_plan_job_fails(github_env, capsys):
    """A report-only check judges every earlier launch, each jobs read retried for 225 s:
    at the sixth, the wait before attempt 4 would end past the deadline (20 minutes, inside
    the plan job's 30), so the check stops there and fails (exit 1), and the plan job fails
    rather than being cancelled at its timeout (a cancelled plan counts, L2)."""
    current = rehearsal_run(500, created=NOW, status="in_progress")
    earlier = [rehearsal_run(300 + i) for i in range(10)]
    api = FakeGitHub(
        [current, *earlier],
        current,
        answers={jobs_page(300 + i): http_error(502) for i in range(10)},
    )
    time_ = FakeTime()
    argv = ["dispatch-check", "--report-only", "--registration-sha256", ""]
    code, _, err = run(argv, capsys, github_opener=api, sleep=time_.sleep, clock=time_.clock)
    assert code == 1
    assert (
        "the dispatch check stopped at its deadline of 1200 s before attempt 4 of the jobs of "
        "run 305 (the last error: GitHub API /repos/owner/repo/actions/runs/305/jobs"
    ) in err
    assert time_.slept == [15, 30, 60, 120] * 5 + [15, 30]
    assert time_.now == 1170 < v31_driver.DISPATCH_DEADLINE
    # A registered check stops at the first launch that counts (unreadable): no deadline.
    registered = FakeGitHub(
        [CURRENT, *(workflow_run(300 + i) for i in range(10))],
        answers={jobs_page(300 + i): http_error(502) for i in range(10)},
    )
    time_ = FakeTime()
    argv = ["dispatch-check", "--registration-sha256", SHA]
    code, _, err = run(argv, capsys, github_opener=registered, sleep=time_.sleep, clock=time_.clock)
    assert code == 1 and "another dispatch of this registration: run 300; " in err
    assert "deadline" not in err and time_.slept == [15, 30, 60, 120]


def test_no_request_starts_after_the_deadline_nor_waits_past_it(github_env, capsys):
    """Slow replies, no error: each request takes 295 s. The last one before the deadline
    is given only the 20 s left as its timeout; the next is never made."""
    stopped = [workflow_run(300 + i, conclusion="failure") for i in range(4)]
    jobs = {300 + i: jobs_of(STOPPED, run=300 + i) for i in range(4)}
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    time_ = FakeTime()
    argv = ["dispatch-check", "--registration-sha256", SHA]
    opener = time_.slowed(api, 295)
    code, _, err = run(argv, capsys, github_opener=opener, sleep=no_sleep, clock=time_.clock)
    assert code == 1
    assert (
        "stopped at its deadline of 1200 s before GET "
        "/repos/owner/repo/actions/runs/303/jobs?filter=all&per_page=100&page=1"
    ) in err
    assert [url for url, *_ in api.requests] == [API + "runs/500", API + page(1)] + [
        API + jobs_page(300 + i) for i in range(3)
    ]
    assert [timeout for *_, timeout in api.requests] == [30, 30, 30, 30, 20]
    # The aggregate's check has the same deadline: on expiry, a reason naming it.
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    time_ = FakeTime()
    counted_, uncounted_ = v31_driver.dispatch_reasons(
        SHA, time_.slowed(api, 295), sleep=no_sleep, clock=time_.clock
    )
    assert uncounted_ == ()
    (reason,) = counted_
    assert reason.startswith(
        "another dispatch of this registration could not be ruled out: the dispatch check "
        "stopped at its deadline of 1200 s before GET /repos/owner/repo/actions/runs/303/jobs"
    )


def test_the_aggregate_names_every_earlier_launch_where_the_plan_stops_at_the_first(github_env):
    """Run 300 is still queued (it counts); run 350 stopped at its plan job (it does not).
    The plan's check refuses on 300 and reads no further; the aggregate's verdict names
    both, as it must name every earlier launch."""
    queued = workflow_run(300, status="queued", conclusion=None)
    stopped = workflow_run(350, conclusion="failure")
    jobs = {350: jobs_of(STOPPED, run=350)}
    api = FakeGitHub([CURRENT, queued, stopped], jobs=jobs)
    assert counted(v31_driver.dispatch_check(SHA, api, sleep=no_sleep)) == (300,)
    assert API + jobs_page(350) not in [url for url, *_ in api.requests]
    api = FakeGitHub([CURRENT, queued, stopped], jobs=jobs)
    counted_, uncounted_ = v31_driver.dispatch_reasons(SHA, api, sleep=no_sleep)
    assert [reason.split(" (")[0] for reason in counted_] == [
        "another dispatch of this registration: run 300"
    ]
    assert uncounted_ == (v31_driver.uncounted_line(350),)


class Broken(Response):
    """A reply whose body cannot be read: ``failure`` is raised while reading it."""

    def __init__(self, failure: BaseException) -> None:
        super().__init__(b"")
        self.failure = failure

    def read(self, limit: int = -1) -> bytes:
        raise self.failure


@pytest.mark.parametrize(
    "failure",
    [
        IncompleteRead(b'{"total_count"', 40),
        BadStatusLine("garbage"),
        ssl.SSLError(1, "bad record mac"),
        ssl.SSLEOFError(8, "EOF occurred in violation of protocol"),
    ],
)
def test_a_reply_cut_short_while_reading_is_retried(github_env, failure):
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={page(1): [Broken(failure)]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [15]
    urls = [url for url, *_ in api.requests]
    assert urls[:3] == [API + "runs/500", API + page(1), API + page(1)]
    # Still cut short at every attempt: refused after five, naming it.
    always = FakeGitHub([CURRENT], answers={page(1): Broken(failure)})
    with pytest.raises(ValueError, match=type(failure).__name__) as refused:
        v31_driver.dispatch_check(SHA, always, sleep=lambda seconds: None)
    assert "still failing after 5 attempts" in str(refused.value)


def test_a_body_shorter_than_its_content_length_is_retried(github_env):
    whole = json.dumps({"total_count": 1, "workflow_runs": [CURRENT]}).encode("utf-8")
    short = Response(whole[:20], headers={"Content-Length": str(len(whole))})
    api = FakeGitHub([CURRENT], answers={page(1): [short]})
    waits = []
    assert v31_driver.dispatch_check(SHA, api, sleep=waits.append) == () and waits == [15]
    exact = Response(whole, headers={"Content-Length": str(len(whole))})
    api = FakeGitHub([CURRENT], answers={page(1): [exact]})
    assert v31_driver.dispatch_check(SHA, api, sleep=no_sleep) == ()
    api = FakeGitHub([CURRENT], answers={page(1): short})
    message = f"the reply ended after 20 of its {len(whole)} bytes (Content-Length)"
    with pytest.raises(ValueError, match=re.escape(message)):
        v31_driver.dispatch_check(SHA, api, sleep=lambda seconds: None)


def test_any_other_broken_reply_still_refuses_at_once(github_env):
    api = FakeGitHub([CURRENT], answers={page(1): [Broken(HTTPException("odd"))]})
    with pytest.raises(ValueError, match="HTTPException: odd"):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)


def test_a_report_only_check_lists_a_run_deleted_since_the_listing_as_gone(github_env, capsys):
    current = rehearsal_run(500, created=NOW, status="in_progress")
    runs = [current, rehearsal_run(300, conclusion="failure"), rehearsal_run(400)]
    jobs = {300: jobs_of(STOPPED, run=300)}
    api = FakeGitHub(runs, current, answers={jobs_page(400): http_error(404)}, jobs=jobs)
    argv = ["dispatch-check", "--report-only", "--registration-sha256", ""]
    code, document, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 0, err
    assert document["other_dispatches"] == [
        "run 400: gone (404): its jobs could not be read: GitHub API "
        "/repos/owner/repo/actions/runs/400/jobs?filter=all&per_page=100&page=1: HTTP 404"
    ]
    assert document["uncounted_dispatches"] == [
        "earlier launch 300 stopped at the plan job with nothing run; not counted"
    ]
    # Any other unreadable listing still fails a report-only check.
    api = FakeGitHub(runs, current, answers={jobs_page(400): http_error(410)}, jobs=jobs)
    code, _, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1 and "could not read GitHub's records: run 400" in err
    # A registered check counts a deleted run (fail closed).
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={jobs_page(400): http_error(404)})
    argv = ["dispatch-check", "--registration-sha256", SHA]
    code, _, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1 and "run 400: gone (404): its jobs could not be read" in err


def test_a_transient_failure_on_page_2_of_the_runs_restarts_from_page_1(github_env):
    """Only a complete, consistent listing is accepted: the retry reads page 1 again, so a
    run created meanwhile (the total 150, then 151) is no inconsistency."""
    runs = [CURRENT, *(workflow_run(1000 + i, title="v31-run smoke ") for i in range(149))]
    runs.append(workflow_run(400))  # 151 runs: two pages
    stale = answer({"total_count": 150, "workflow_runs": runs[:100]})
    api = FakeGitHub(runs, answers={page(1): [stale], page(2): [http_error(502)]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [15]
    assert [url for url, *_ in api.requests] == [
        API + "runs/500",
        *(API + page(n) for n in (1, 2, 1, 2)),
        API + jobs_page(400),
    ]
    # Page 2 failing at every attempt: each attempt starts at page 1, then refused.
    always = FakeGitHub(runs, answers={page(2): http_error(502)})
    with pytest.raises(ValueError, match="page=2: HTTP 502 \\(still failing after 5"):
        v31_driver.dispatch_check(SHA, always, sleep=lambda seconds: None)
    urls = [url for url, *_ in always.requests]
    assert urls[1:] == [API + page(n) for n in (1, 2) * 5]


def test_a_transient_failure_on_page_2_of_a_jobs_listing_restarts_from_page_1(github_env):
    cells = [(f"run-main (cell-{i})", "skipped") for i in range(150 - len(STOPPED))]
    records = jobs_of([*STOPPED, *cells], run=300)  # 150 records: two pages
    assert len(records) == 150
    stale = answer({"total_count": 149, "jobs": records[:100]})
    api = FakeGitHub(
        [CURRENT, workflow_run(300, conclusion="failure")],
        answers={jobs_page(300, 1): [stale], jobs_page(300, 2): [http_error(503)]},
        jobs={300: records},
    )
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert (launch.run_id, launch.counts, waits) == (300, False, [15])
    assert [url for url, *_ in api.requests][2:] == [API + jobs_page(300, n) for n in (1, 2, 1, 2)]


def test_the_current_runs_id_is_checked_before_anything_else_is_read(github_env):
    api = FakeGitHub([CURRENT], {**CURRENT, "id": 501})
    message = "the current run's id is 501, not GITHUB_RUN_ID 500: this is not the run"
    with pytest.raises(ValueError, match=re.escape(message)):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert [url for url, *_ in api.requests] == [API + "runs/500"]
    malformed = FakeGitHub([CURRENT], {**CURRENT, "id": "500"})
    with pytest.raises(ValueError, match=re.escape("the current run: id '500'")):
        v31_driver.dispatch_check(SHA, malformed, sleep=no_sleep)
    assert [url for url, *_ in malformed.requests] == [API + "runs/500"]


def test_the_deadline_is_twenty_minutes():
    assert v31_driver.DISPATCH_DEADLINE == 20 * 60


# --- Codex's findings on PR #281: per-attempt plans, the job's budget, malformed records --


def test_every_attempt_must_list_a_failed_plan_job():
    """Codex P1: a second attempt that lists no plan job (here only the status job, re-run)
    cannot be shown to have stopped at its plan job: the launch counts. Two attempts that
    each failed at the plan, every other job skipped, do not count."""
    twice = workflow_run(400, attempts=2, conclusion="failure")
    first = [job(1, "plan", "failure"), job(2, "status", "success")]
    second = [job(103, "status", "success", attempt=2)]
    reason, malformed = v31_driver.launch_decision(twice, first + second)
    assert (reason, malformed) == ("no plan job is listed for its attempt(s) 2", False)
    # The same with every skipped job listed in attempt 1.
    reason = v31_driver.launch_reason(twice, jobs_of(STOPPED) + second)
    assert reason == "no plan job is listed for its attempt(s) 2"
    # Each attempt failed at its plan job: not counted.
    both = first + [job(3, "plan", "failure", attempt=2), job(4, "status", "failure", attempt=2)]
    assert v31_driver.launch_decision(twice, both) == (None, False)
    full = jobs_of(STOPPED) + jobs_of(STOPPED, attempt=2, first=100)
    assert v31_driver.launch_decision(twice, full) == (None, False)
    # Three attempts, the middle one without a plan job.
    thrice = workflow_run(400, attempts=3, conclusion="failure")
    jobs = first + second + [job(5, "plan", "failure", attempt=3)]
    assert v31_driver.launch_reason(thrice, jobs) == "no plan job is listed for its attempt(s) 2"


def test_a_report_only_check_fails_on_a_malformed_job_record(github_env, capsys):
    """Codex P2: a record of a shape the rule does not know is an API-shape problem, which
    the rehearsal must surface (exit 1); a registered check counts the launch, as before.
    An unknown job name or an unexpected conclusion is a decision, not a failure to read."""
    current = rehearsal_run(500, created=NOW, status="in_progress")
    malformed = jobs_of(STOPPED, run=400)
    del malformed[1]["run_attempt"]
    api = FakeGitHub([current, rehearsal_run(400)], current, jobs={400: malformed})
    argv = ["dispatch-check", "--report-only", "--registration-sha256", ""]
    code, _, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1
    assert (
        "could not read GitHub's records: run 400: its job 2 has run_attempt None, not 1 to 1"
    ) in err
    # An unknown job name: counted, and no failure.
    named = [*jobs_of(STOPPED, run=400), job(50, "deploy", "success")]
    api = FakeGitHub([current, rehearsal_run(400)], current, jobs={400: named})
    code, document, err = run(argv, capsys, github_opener=api, sleep=no_sleep)
    assert code == 0, err
    assert document["other_dispatches"] == [
        "run 400: its job 'deploy' (job 50, attempt 1) is not a job of this workflow"
    ]
    # A registered check counts the malformed launch (unreadable) and refuses.
    api = FakeGitHub([CURRENT, workflow_run(400)], jobs={400: malformed})
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert (launch.counts, launch.unreadable, launch.gone) == (True, True, False)
    code, _, err = run(
        ["dispatch-check", "--registration-sha256", SHA], capsys, github_opener=api, sleep=no_sleep
    )
    assert code == 1 and "run 400: its job 2 has run_attempt None" in err


class FakeWall:
    """An injected wall clock: the epoch second it reads."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


EPOCH = 1_792_000_000.0  # a wall-clock second for the tests (2026-10)


def test_a_job_that_started_twelve_minutes_ago_gets_only_thirteen(github_env, monkeypatch, capsys):
    """Codex P1: the plan job's budget (25 of its 30 minutes) counts from the job's start,
    which its first step records, so slow installs before the check shorten the check's
    deadline: started 12 minutes before, it gets 13 (780 s), not 20."""
    monkeypatch.setenv("V31_JOB_STARTED", str(int(EPOCH) - 12 * 60))
    stopped = [workflow_run(300 + i, conclusion="failure") for i in range(4)]
    jobs = {300 + i: jobs_of(STOPPED, run=300 + i) for i in range(4)}
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    time_ = FakeTime()
    argv = ["dispatch-check", "--registration-sha256", SHA]
    code, _, err = run(
        argv,
        capsys,
        github_opener=time_.slowed(api, 300),
        sleep=no_sleep,
        clock=time_.clock,
        wall=FakeWall(EPOCH),
    )
    assert code == 1
    assert (
        "stopped at its deadline of 780 s (what was left of its job's 1500 s budget: the job "
        "started 720 s before the check) before GET /repos/owner/repo/actions/runs/301/jobs"
    ) in err
    # Requests at 0, 300 and 600 s; none at 900 s, 120 s past the deadline.
    assert [timeout for *_, timeout in api.requests] == [30, 30, 30]
    assert v31_driver.PLAN_JOB_BUDGET == 25 * 60
    # Started 2 minutes before: 23 minutes left, so the check's own 20 minutes stand.
    monkeypatch.setenv("V31_JOB_STARTED", str(int(EPOCH) - 2 * 60))
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    time_ = FakeTime()
    code, _, err = run(
        argv,
        capsys,
        github_opener=time_.slowed(api, 300),
        sleep=no_sleep,
        clock=time_.clock,
        wall=FakeWall(EPOCH),
    )
    assert code == 1 and "stopped at its deadline of 1200 s before GET" in err
    assert "budget" not in err
    # Started 26 minutes before: nothing is left, and no request is made.
    monkeypatch.setenv("V31_JOB_STARTED", str(int(EPOCH) - 26 * 60))
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    code, _, err = run(
        argv,
        capsys,
        github_opener=api,
        sleep=no_sleep,
        clock=FakeTime().clock,
        wall=FakeWall(EPOCH),
    )
    assert code == 1 and "deadline of 0 s" in err and "before its first request" in err
    assert api.requests == []


@pytest.mark.parametrize(
    "started",
    ["", "abc", "0", "-5", "1792000000.5", " 1792000000", "01792000000", str(int(EPOCH) + 1)],
)
def test_a_malformed_or_future_job_start_refuses_before_any_request(
    github_env, monkeypatch, capsys, started
):
    monkeypatch.setenv("V31_JOB_STARTED", started)
    api = FakeGitHub([CURRENT])
    argv = ["dispatch-check", "--registration-sha256", SHA]
    code, _, err = run(
        argv,
        capsys,
        github_opener=api,
        sleep=no_sleep,
        clock=FakeTime().clock,
        wall=FakeWall(EPOCH),
    )
    assert code == 1 and f"V31_JOB_STARTED {started!r}: the job's start" in err
    assert api.requests == []
    # The aggregate's check refuses it too: a reason that leaves the verdict incomplete.
    counted_, uncounted_ = v31_driver.dispatch_reasons(
        SHA, api, sleep=no_sleep, clock=FakeTime().clock, wall=FakeWall(EPOCH)
    )
    (reason,) = counted_
    assert reason.startswith("another dispatch of this registration could not be ruled out")
    assert "V31_JOB_STARTED" in reason and uncounted_ == () and api.requests == []


def test_the_aggregates_check_budgets_from_its_jobs_start_too(github_env, monkeypatch):
    """The aggregate job's budget is 355 of its 360 minutes: a job started 350 minutes
    before the check leaves it 5 minutes; one started an hour before leaves the check's own
    20."""
    assert v31_driver.AGGREGATE_JOB_BUDGET == 355 * 60
    monkeypatch.setenv("V31_JOB_STARTED", str(int(EPOCH) - 350 * 60))
    stopped = [workflow_run(300 + i, conclusion="failure") for i in range(4)]
    jobs = {300 + i: jobs_of(STOPPED, run=300 + i) for i in range(4)}
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    time_ = FakeTime()
    counted_, _ = v31_driver.dispatch_reasons(
        SHA, time_.slowed(api, 200), sleep=no_sleep, clock=time_.clock, wall=FakeWall(EPOCH)
    )
    (reason,) = counted_
    assert "stopped at its deadline of 300 s (what was left of its job's 21300 s budget" in reason
    monkeypatch.setenv("V31_JOB_STARTED", str(int(EPOCH) - 60 * 60))
    api = FakeGitHub([CURRENT, *stopped], jobs=jobs)
    counted_, uncounted_ = v31_driver.dispatch_reasons(
        SHA, api, sleep=no_sleep, clock=FakeTime().clock, wall=FakeWall(EPOCH)
    )
    assert counted_ == () and len(uncounted_) == 4


# --- Codex's P2s at 88fcb87: the rehearsal probes the jobs endpoint; secondary limits ----

REPORT_ONLY = ["dispatch-check", "--report-only", "--registration-sha256", ""]


def in_progress_jobs(run=500, attempt=1):
    """This run's own jobs as GitHub lists them while its plan job runs: the plan in
    progress, every later job queued or still to come, no conclusion yet."""
    return [
        job(1, "plan", None, run=run, attempt=attempt, status="in_progress"),
        job(2, "prepare", None, run=run, attempt=attempt, status="queued"),
        job(3, "status", None, run=run, attempt=attempt, status="queued"),
    ]


def test_a_first_rehearsal_still_reads_and_checks_the_jobs_endpoint(github_env, capsys):
    """No earlier launch of its title: a report-only check reads this run's own job
    listing anyway, checks every record's shape, takes no L2 decision on it (the run is in
    progress) and passes, saying so. A registered check makes no such request."""
    current = rehearsal_run(500, created=NOW, status="in_progress")
    api = FakeGitHub([current], current, jobs={500: in_progress_jobs()})
    code, document, err = run(REPORT_ONLY, capsys, github_opener=api, sleep=no_sleep)
    assert code == 0, err
    assert (document["other_dispatches"], document["uncounted_dispatches"]) == ([], [])
    assert "jobs endpoint checked on this run: 3 job records, shape valid" in err
    assert [url for url, *_ in api.requests] == [
        API + "runs/500",
        API + jobs_page(500),
        API + page(1),
    ]
    # Its own listing paginates like any other: 250 records, three pages.
    many = [job(n, f"run-main (cell-{n})", None, run=500, status="queued") for n in range(1, 251)]
    api = FakeGitHub([current], current, jobs={500: many})
    code, _, err = run(REPORT_ONLY, capsys, github_opener=api, sleep=no_sleep)
    assert code == 0 and "250 job records, shape valid" in err
    assert [url for url, *_ in api.requests][1:4] == [API + jobs_page(500, n) for n in (1, 2, 3)]
    # A registered check reads no jobs of its own run.
    registered = FakeGitHub([CURRENT], jobs={500: in_progress_jobs()})
    code, _, err = run(
        ["dispatch-check", "--registration-sha256", SHA],
        capsys,
        github_opener=registered,
        sleep=no_sleep,
    )
    assert code == 0, err
    assert [url for url, *_ in registered.requests] == [API + "runs/500", API + page(1)]
    assert "jobs endpoint" not in err


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda jobs: jobs[1].pop("name"), "its job 2 has no string name and status"),
        (lambda jobs: jobs[1].update(run_id=501), "its job 2 has run_id 501, not 500"),
        (lambda jobs: jobs[1].update(run_attempt=2), "its job 2 has run_attempt 2, not 1 to 1"),
        # An id twice is caught first by the paging (run_jobs), which fails the same way.
        (lambda jobs: jobs[1].update(id=1), "run 500: job 1 is listed twice: the pages disagree"),
        (lambda jobs: jobs[1].update(conclusion=7), "its job 2 has conclusion 7"),
        (lambda jobs: jobs.append("a job"), "its job record 4 is not a JSON object"),
        (lambda jobs: jobs.clear(), "it lists no job record, though its own plan job is running"),
    ],
)
def test_a_malformed_record_in_this_runs_own_jobs_fails_a_report_only_check(
    github_env, capsys, change, message
):
    current = rehearsal_run(500, created=NOW, status="in_progress")
    jobs = in_progress_jobs()
    change(jobs)
    api = FakeGitHub([current], current, jobs={500: jobs})
    code, _, err = run(REPORT_ONLY, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1
    prefix = "the jobs endpoint, checked on this run (500), does not have the shape the check"
    if message.startswith("run 500: "):
        assert message in err and prefix not in err
    else:
        assert f"{prefix} reads: {message}" in err
    assert API + page(1) not in [url for url, *_ in api.requests]  # it stops there


def test_this_runs_own_jobs_failing_to_read_fail_a_report_only_check(github_env, capsys):
    current = rehearsal_run(500, created=NOW, status="in_progress")
    api = FakeGitHub([current], current, answers={jobs_page(500): http_error(502)})
    waits = []
    code, _, err = run(REPORT_ONLY, capsys, github_opener=api, sleep=waits.append)
    assert code == 1 and waits == [15, 30, 60, 120]
    assert "this run's own jobs: attempt 1 of 5 failed" in err
    assert "runs/500/jobs?filter=all&per_page=100&page=1: HTTP 502 (still failing after 5" in err
    # A 404 on this run's own jobs is no deleted earlier launch: it fails too.
    api = FakeGitHub([current], current, answers={jobs_page(500): http_error(404)})
    code, _, err = run(REPORT_ONLY, capsys, github_opener=api, sleep=no_sleep)
    assert code == 1 and "HTTP 404" in err


def test_the_current_runs_listing_shape_pure():
    current = rehearsal_run(500, created=NOW, status="in_progress")
    assert v31_driver.job_listing_error(current, in_progress_jobs()) is None
    assert v31_driver.job_listing_error(current, tuple(in_progress_jobs())) is None
    rerun = rehearsal_run(500, created=NOW, status="in_progress", attempts=2)
    both = jobs_of(STOPPED, run=500) + [
        job(100 + j["id"], j["name"], None, run=500, attempt=2, status="queued")
        for j in in_progress_jobs()
    ]
    assert v31_driver.job_listing_error(rerun, both) is None
    assert v31_driver.job_listing_error("a run", []) == "its run record is not a JSON object"
    assert "run_attempt is None" in v31_driver.job_listing_error(
        without(current, "run_attempt"), []
    )
    assert v31_driver.job_listing_error(current, None) == "its jobs are not a list"


def secondary_limit(message="You have exceeded a secondary rate limit. Please wait a few minutes"):
    """GitHub's secondary rate limit, as its docs describe it: a 403 that may carry neither
    Retry-After nor x-ratelimit-remaining, its JSON body's message naming the limit."""
    body = json.dumps({"message": message, "documentation_url": "https://docs.github.com/"})
    return http_error(403, {}, body.encode("utf-8"))


def test_a_secondary_rate_limit_403_is_retried_after_a_minute(github_env, capsys):
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={page(1): [secondary_limit()]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [60]  # at least a minute, as GitHub asks
    assert "HTTP 403 (secondary rate limit)); retrying in 60 s" in capsys.readouterr().err
    # Any case of the words; repeated at every attempt: refused after the retries, named.
    always = [secondary_limit("SECONDARY RATE LIMIT exceeded") for _ in range(5)]
    api = FakeGitHub([CURRENT], answers={page(1): always})
    waits = []
    with pytest.raises(ValueError) as refused:
        v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert waits == [60, 60, 60, 120]  # each at least a minute, at most the cap
    assert str(refused.value).endswith(
        "page=1: HTTP 403 (secondary rate limit) (still failing after 5 attempts)"
    )


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"message": "Resource not accessible by integration"}).encode("utf-8"),
        b"<html>secondary rate limit</html>",  # not JSON: permanent
        json.dumps(["secondary rate limit"]).encode("utf-8"),  # no message
        json.dumps({"message": 7}).encode("utf-8"),
        b"",
    ],
)
def test_any_other_403_still_refuses_at_once(github_env, body):
    api = FakeGitHub([CURRENT], answers={page(1): [http_error(403, {}, body)]})
    with pytest.raises(ValueError, match=r"HTTP 403$"):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)


def test_a_secondary_limit_body_beyond_the_size_limit_is_not_read_as_one(github_env, monkeypatch):
    # Only a 403 is read for it: a 404 naming the limit is still a 404.
    named = json.dumps({"message": "secondary rate limit"}).encode("utf-8")
    api = FakeGitHub([CURRENT], answers={page(1): [http_error(404, {}, named)]})
    with pytest.raises(v31_driver.GitHubNotFound):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    # A body beyond the size limit is not read as one: the 403 is permanent.
    monkeypatch.setattr(v31_driver, "MAX_GITHUB_BYTES", 16)
    api = FakeGitHub([CURRENT], answers={"runs/500": [secondary_limit()]})
    with pytest.raises(ValueError, match=r"HTTP 403$"):
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)


# --- Codex's P2 at 09559b3: a 403 body cut short while read is retried --------------------


class CutShortBody(io.RawIOBase):
    """A 403's body whose read fails as the connection does: ``failure`` is raised."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure

    def readable(self) -> bool:
        return True

    def read(self, size=-1):
        raise self.failure


def cut_short_403(failure: BaseException) -> urllib.error.HTTPError:
    """A headerless 403 (neither Retry-After nor x-ratelimit-remaining) whose body fails to
    read with ``failure``."""
    return urllib.error.HTTPError(API, 403, "synthetic", HTTPMessage(), CutShortBody(failure))


@pytest.mark.parametrize(
    "failure",
    [
        IncompleteRead(b'{"message": "You have exceeded a sec', 70),
        BadStatusLine("the reply ended"),
        ConnectionResetError("connection reset by peer"),
        TimeoutError("the read timed out"),
        ssl.SSLEOFError("EOF occurred in violation of protocol"),
        urllib.error.URLError("down"),
    ],
    ids=lambda failure: type(failure).__name__,
)
def test_a_403_body_cut_short_while_read_is_retried(github_env, capsys, failure):
    """A read of the headerless 403's body (for the secondary-limit message) failing as a
    200 reply's would be retried is a reply cut short, which may have been the limit's:
    retried after at least a minute, as the limit is, then the listing succeeds; refused,
    named, after the last attempt."""
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={page(1): [cut_short_403(failure)]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [60]
    err = capsys.readouterr().err
    assert f"HTTP 403 (its body was cut short: {type(failure).__name__}: " in err
    assert "attempt 1 of 5 failed" in err and "retrying in 60 s" in err
    assert [url for url, *_ in api.requests].count(API + page(1)) == 2
    api = FakeGitHub([CURRENT], answers={page(1): [cut_short_403(failure) for _ in range(5)]})
    waits = []
    with pytest.raises(ValueError, match=r"\(still failing after 5 attempts\)$") as refused:
        v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert waits == [60, 60, 60, 120]  # each at least a minute, at most the cap
    assert f"page=1: HTTP 403 (its body was cut short: {type(failure).__name__}" in str(
        refused.value
    )


def test_a_403_body_ending_before_its_content_length_is_retried(github_env, capsys):
    """``read(amt)`` raises nothing when a body ends before its Content-Length: it returns
    the short read. A 403's body so cut short is retried as one that raised, after at
    least a minute, as a 200 reply's short body is retried."""
    body = b'{"message": "You have exc'
    short = http_error(403, {"Content-Length": "100"}, body)
    api = FakeGitHub([CURRENT, workflow_run(400)], answers={page(1): [short]})
    waits = []
    (launch,) = v31_driver.dispatch_check(SHA, api, sleep=waits.append)
    assert launch.run_id == 400 and waits == [60]
    err = capsys.readouterr().err
    assert f"HTTP 403 (its body ended after {len(body)} of its 100 bytes (Content-Length))" in err
    assert [url for url, *_ in api.requests].count(API + page(1)) == 2


@pytest.mark.parametrize(
    "failure",
    [
        LineTooLong("header line"),
        HTTPException("an HTTP failure of no other kind"),
        OSError("an OS failure of no other kind"),
        ValueError("I/O operation on closed file"),
    ],
    ids=lambda failure: type(failure).__name__,
)
def test_any_other_failure_reading_a_403_body_stays_permanent(github_env, failure):
    """A failure a 200 reply's read would not retry is no reply cut short on a 403's
    body either: the 403 is refused at once, as permanent as any other."""
    api = FakeGitHub([CURRENT], answers={page(1): [cut_short_403(failure)]})
    with pytest.raises(ValueError, match=r"HTTP 403$") as refused:
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert not isinstance(refused.value, v31_driver.TransientGitHubError)
    assert [url for url, *_ in api.requests].count(API + page(1)) == 1


@pytest.mark.parametrize("declared", [False, True], ids=["no length", "its length"])
def test_a_permission_403_whose_body_reads_in_full_stays_permanent(github_env, declared):
    """A headerless 403 whose body reads in full (all its Content-Length, when it declares
    one) and names no secondary limit is GitHub refusing the token: refused at once, never
    retried, the body's read not a cut-short reply."""
    body = json.dumps({"message": "Resource not accessible by integration"}).encode("utf-8")
    headers = {"Content-Length": str(len(body))} if declared else {}
    api = FakeGitHub([CURRENT], answers={page(1): [http_error(403, headers, body)]})
    with pytest.raises(ValueError, match=r"HTTP 403$") as refused:
        v31_driver.dispatch_check(SHA, api, sleep=no_sleep)
    assert not isinstance(refused.value, v31_driver.TransientGitHubError)
    assert [url for url, *_ in api.requests].count(API + page(1)) == 1


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
        (
            owner_plan.PlanCapital("research", "USDT", D(10000), D(10000)),
            owner_plan.PlanCapital("medium", "USDT", D(1000), D(1000)),
            owner_plan.PlanCapital("small", "USDT", D(100), D(100)),
        ),
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
# Each case: the prepare windows and the refusal each real mode gives (None: the owner's
# plan, which no mode refuses for its plan). A registration's capitals other than the
# owner's three never load
# (test_every_registered_job_refuses_capitals_other_than_the_owners).
PLAN_CASES = {
    "the owner's plan": (owner_windows(), None),
    "W1 without SOLUSDT": (
        owner_windows(w1={"symbols": sorted(W1_COINS - {"SOLUSDT"})}),
        "window w1 must hold the owner's 10 coins (missing: SOLUSDT; outside the plan: none)",
    ),
    "an extra W1 coin": (
        owner_windows(w1={"symbols": sorted(W1_COINS | {"AVAXUSDT"})}),
        "window w1 must hold the owner's 10 coins (missing: none; outside the plan: AVAXUSDT)",
    ),
    "a shifted W1 start": (
        owner_windows(w1={"start_ms": owner_plan.W1_START_MS + DAY}),
        "window w1 is [2021-07-02 00:00 UTC, 2025-01-01 00:00 UTC), not the owner's "
        "[2021-07-01 00:00 UTC, 2025-01-01 00:00 UTC)",
    ),
    "another W0 coin set": (
        owner_windows(w0={"symbols": sorted(W0_COINS - {"TRXUSDT"} | {"DOGEUSDT"})}),
        "window w0 must hold the owner's 8 coins (missing: TRXUSDT; outside the plan: DOGEUSDT)",
    ),
}
# The capital the owner replaced on 2026-10-14: EUR 100 at the ECB rate, with its FX record.
EUR_CAPITAL = {
    "id": "owner_small",
    "currency": "EUR",
    "amount": "100",
    "initial_equity": "103.89",
    "fx_rate": "1.0389",
    "fx_record": {"path": "config/v3_1_fx_record.json", "sha256": "e" * 64},
}


@dataclass(frozen=True)
class PlanWorld:
    repo: Path
    head: str
    prepare_sha: str
    registration: str
    manifest: str
    config_sha: str


def plan_world(
    registered: Registered, root: Path, windows: list, capitals: list | None = None
) -> PlanWorld:
    """A copy of the smoke world whose prepare config holds ``windows``, registered over
    them as Task 11 registers the real run, with pack pins naming no pack (each plan
    refusal comes before any pack is read), the V3.1 trial completed with them, and
    committed: the head is clean, and only registration artifacts changed since the code
    pin. ``capitals`` replaces the registration file's owner capitals, as a registration
    no loader passes would hold them."""
    repo = root / "repo"
    shutil.copytree(registered.repo, repo)
    path = repo / "config/v3_1_prepare.json"
    path.write_bytes(dumped({**json.loads(path.read_bytes()), "windows": windows}))
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
    if capitals is not None:
        written = repo / files["registration"]
        registration = {**json.loads(written.read_bytes()), "capitals": capitals}
        written.unlink()
        config_sha = v31_smoke.write_json(written, registration)
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
    the owner's, before anything is fetched, read or replayed. The owner's plan, its three
    USDT capitals registered, passes the gate in every mode (the steps after it then miss
    this world's data: plan alone completes)."""
    windows, refusal = PLAN_CASES[case]
    world = plan_world(registered, tmp_path / "world", windows)
    hosts = {"inventory_transport": v31_smoke.Archives(), "legacy_transport": v31_smoke.Archives()}
    for name, (argv, out) in plan_world_calls(world, tmp_path).items():
        code, document, err = run(argv, capsys, **hosts)
        if refusal is not None:
            assert code == 1 and "run refused, not the owner's plan" in err, (name, err)
            assert refusal in err, (name, err)
            assert out is None or not out.exists(), name
        else:
            assert "not the owner's plan" not in err, (name, err)
        if name == "plan" and refusal is None:
            assert code == 0 and document["cells_planned"] == 324, err
    assert all(host.requested == [] for host in hosts.values())  # nothing was fetched


@pytest.mark.parametrize(
    ("capitals", "refusal"),
    [
        (
            [*v31_smoke.capitals_document()[:2], EUR_CAPITAL],
            "capital: unexpected fields: fx_rate, fx_record",
        ),
        (
            [{**c, "fx_rate": "1"} for c in v31_smoke.capitals_document()],
            "capital: unexpected fields: fx_rate",
        ),
        (
            v31_smoke.capitals_document()[:2],
            "the research, medium and small USDT capitals required",
        ),
    ],
    ids=["the EUR 100 capital", "an FX rate on each", "no small capital"],
)
def test_every_registered_job_refuses_capitals_other_than_the_owners(
    registered, tmp_path, capsys, capitals, refusal
):
    """A registration whose capitals are not the owner's three USDT ones, the replaced EUR
    100 capital with its FX record above all, never loads: every registered job refuses it
    before anything is fetched, read or replayed, and no FX record is read."""
    world = plan_world(registered, tmp_path / "world", owner_windows(), capitals)
    hosts = {"inventory_transport": v31_smoke.Archives(), "legacy_transport": v31_smoke.Archives()}
    calls = plan_world_calls(world, tmp_path)
    for name in ("registered prepare", "plan", "picks", "run-cell", "aggregate"):
        argv, out = calls[name]
        code, _, err = run(argv, capsys, **hosts)
        assert code == 1 and refusal in err, (name, err)
        assert out is None or not out.exists(), name
    assert not (world.repo / "config/v3_1_fx_record.json").exists()
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
