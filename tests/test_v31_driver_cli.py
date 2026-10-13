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
  adapter pins read real blob ids at its head: picks, run-cell and aggregate run on it;
- a prepare world: a synthetic V3 inventory (spot, futures and funding archives, one
  excluded and one missing month), a legacy dataset whose minutes and hours agree, so the
  frozen mask job runs for real (one BTC hour lacks a minute, so its mask holds it), an
  XRP hour priced so that its quotes break rule 8, a V3.1 minute manifest, filter
  snapshots, and V3's registration in the trial register.

V3's walk-forward, and in the smoke world the frozen mask job, run as the smoke's
stand-ins (``v31_smoke.stand_ins``); the V3 input pack builder, whose V3 loader needs the
full 2710-entry inventory, is replaced in the prepare tests by a recording builder.
"""

import contextlib
import hashlib
import io
import json
import shutil
import socket
import sys
from dataclasses import dataclass, replace
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
from crypto_grid_bot.combined.driver import run_baselines
from crypto_grid_bot.combined.driver.aggregate import _CLAIMED_ATTEMPT
from crypto_grid_bot.combined.driver.packs import read_pack
from crypto_grid_bot.combined.driver.registration import (
    FilePin,
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
    """No test in this file may resolve a name or open a socket."""
    block_network(monkeypatch)


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
    # The first W1 cell of each kind and the first W0 cell ran first, then the next cell in
    # registration order; each completed, as did the picks job. The rest were never run.
    assert completed == {
        "w1.spot_trend.olhc.c1.research",
        "w1.matched_spot_hold.native.c1.research",
        "w1.unchanged_v3_selector.native.c1.research",
        "w1.matched_v0_grid_high_first.native.c1.research",
        "w0.combined.olhc.c1.research",
        "w1.unchanged_v3_selector.native.c1.owner_small",
    }
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
    # Nothing is replaced: a second smoke into the same directory is refused.
    code, _, err = run(["smoke", "--out", str(tmp_path / "s"), "--cells", "1"], capsys)
    assert code == 1 and "exists" in err


# --- a registered world: picks, run-cell and aggregate -----------------------------------


@dataclass(frozen=True)
class Registered:
    repo: Path
    head: str
    packs: Path
    legacy: Path
    config_sha: str
    pins: dict
    window_packs: dict


@pytest.fixture(scope="module")
def registered(module_network_blocked, tmp_path_factory) -> Registered:
    """The smoke world with stub modules committed, its packs, and a registration whose
    code pin is the head and whose adapter pins are the head's."""
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path_factory.mktemp("cli")
    with v31_smoke.stand_ins():
        world = v31_smoke.build_world(root, extra_files=MODULES)
        document = v31_driver.smoke_packs(world, root / "packs")
    pins = adapter_pins(world.repo, world.head)
    reg, config_sha = v31_smoke.register(world, document, code_pin=world.head, adapter_pins=pins)
    window_packs = dict(reg.run_manifest.window_packs)
    return Registered(
        world.repo, world.head, root / "packs", world.legacy, config_sha, pins, window_packs
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


def test_run_cell_refuses_without_the_gate(registered, tmp_path, capsys):
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
    # Code changed after the code pin: the changed path and the moved adapter pin, both named.
    code, _, err = attempt(repo=changed_copy(registered, tmp_path))
    assert code == 1 and f"execution gate refused cell {CELL!r}" in err
    assert "outside the registration artifacts: src/crypto_grid_bot/combined/engine.py" in err
    assert "the adapter pin of combined at the checkout" in err
    assert not out.exists()  # nothing was written for any refused run


def test_each_cell_kind_runs_through_the_execution_gate(registered, tmp_path, capsys, monkeypatch):
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
    # the head, no change since the code pin, the head's adapter pins and the dispatch's pin.
    assert [cell_id for cell_id, _ in calls] == list(KIND_CELLS.values())
    for _, arguments in calls:
        assert arguments["pack_sha256"] == registered.window_packs["w1"]
        assert arguments["pack"].window_id == "w1"
        assert (arguments["repo_head"], arguments["changed_paths"]) == (registered.head, ())
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
    registered, tmp_path, capsys
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
    assert (document["code_pin"], document["repo_head"]) == (registered.head, registered.head)
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
    assert changed == ("config/v3_1_registration.json", "config/v3_1_run_manifest.json")
    assert v31_driver._path_errors(changed, ()) == []
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

    # plan: the gate, then five cells (one W1 cell of each kind, one W0 cell).
    code, planned, err = run(rehearsal_args(rehearsal, "plan", "--cells", "5"), capsys)
    assert code == 0, err
    assert planned["v3_cells"] == ["w1.unchanged_v3_selector.native.c1.research"]
    assert len(planned["main_cells"]) == 4 and planned["cells_planned"] == 5
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
    assert judged["status"] == "incomplete"  # 5 of 216 cells: never a verdict
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


def pin_inventory(repo: Path, raw: bytes, pins: dict) -> str:
    """Write the inventory manifest, V3's completion pinning it, and the prepare config
    pinning every manifest; return the prepare config's SHA-256."""
    (repo / INVENTORY).write_bytes(raw)
    config_raw = (repo / V3_CONFIG).read_bytes()
    completion = {
        "event_type": "completion",
        "family": "spec-v3",
        "trial_id": "v3-synthetic",
        "payload": {
            "manifest": {"path": INVENTORY, "sha256": sha(raw)},
            "config": {"path": V3_CONFIG, "sha256": sha(config_raw)},
        },
    }
    register = repo / "docs/trials/register.jsonl"
    register.parent.mkdir(parents=True, exist_ok=True)
    register.write_bytes((json.dumps(completion, sort_keys=True) + "\n").encode("ascii"))
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


@pytest.fixture(scope="module")
def prepare_world(module_network_blocked, tmp_path_factory) -> PrepareWorld:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    root = tmp_path_factory.mktemp("prepare-world")
    repo = root / "repo"
    v31_smoke.init_repo(repo)
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


def test_prepare_refuses_any_2025_month_before_any_fetch(prepare_world, tmp_path, capsys):
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


def registered_world(prepare_world: PrepareWorld, tmp_path: Path) -> v31_smoke.World:
    """A copy of the prepare world's repository, to register in without touching it."""
    repo = tmp_path / "repo"
    shutil.copytree(prepare_world.repo, repo)
    prepare = load_prepare_config(repo / "config/v3_1_prepare.json")
    return v31_smoke.World(tmp_path, repo, prepare_world.head, tmp_path / "unused", prepare)


def test_registered_prepare_refuses_a_different_pack_hash(
    prepare_world, prepared, tmp_path, capsys
):
    assert prepared.code == 0, prepared.stderr
    document = json.loads(prepared.stdout)
    world = registered_world(prepare_world, tmp_path)
    hosts = {
        "inventory_transport": prepare_world.inventory,
        "legacy_transport": prepare_world.legacy,
    }

    def registered_prepare(doc, name, out):
        files = {
            "registration": f"config/{name}-registration.json",
            "manifest": f"config/{name}-manifest.json",
        }
        _, config_sha = v31_smoke.register(world, doc, code_pin=prepare_world.head, **files)
        argv = prepare_args(
            prepare_world,
            prepared.work,
            out,
            "--registration",
            files["registration"],
            "--run-manifest",
            files["manifest"],
            "--registration-sha256",
            config_sha,
            repo=world.repo,
            mode="registered",
        )
        return config_sha, run(
            argv, capsys, sleep=lambda seconds: None, v3_pack_builder=V3Builder(), **hosts
        )

    # A registration pinning another W1 pack: refused, and nothing final written.
    wrong = {**document, "window_packs": {**document["window_packs"], "w1": "0" * 64}}
    _, (code, _, err) = registered_prepare(wrong, "wrong-pack", tmp_path / "refused")
    assert code == 1 and "registered prepare did not reproduce the registration" in err
    derived = document["window_packs"]["w1"]
    assert f"window w1: pack SHA-256 {derived} differs from the pinned {'0' * 64}" in err
    assert not (tmp_path / "refused" / "packs").exists()
    assert not (tmp_path / "refused" / "prepare.json").exists()
    # A registration whose W1 skipped hours lack the quote-test hour: refused too.
    skipped = {**document["skipped_hours"], "w1": {"hours": [MASKED], "sources": {}}}
    _, (code, _, err) = registered_prepare(
        {**document, "skipped_hours": skipped}, "wrong-hours", tmp_path / "hours"
    )
    assert code == 1 and "window w1: the derived skipped hours differ" in err
    assert f"derived only: [{QUOTED}]" in err
    assert not (tmp_path / "hours" / "packs").exists()
    # The registration of the prepare-only document: every pin and hour reproduced.
    config_sha, (code, again, err) = registered_prepare(document, "true", tmp_path / "reproduced")
    assert code == 0, err
    assert again == {**document, "mode": "registered", "registration_sha256": config_sha}
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
    prepare_world, tmp_path, capsys, monkeypatch
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
