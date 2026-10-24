"""V4 step 4b, task 7: the rehearsal world's repository (``world.tar``), the forced outcomes and the
scenario checks of ``scripts/v4_rehearsal.py``.

The rehearsal world itself replays four years per forced cell, so these tests run ``world --scale
rehearsal`` once (the module fixture ``world``) with its two presets replaced by small ones:

* the data: BTCUSDT and its perpetual, falling with noise from 2023-06, with a window of three
  months, 2024-04 to 2024-06. ``v4_main-1000-1x`` is short on the perpetual through 2024-06-01
  00:00, the real ``FORCE_FROM_MS``, so every forced fault hits while the cell holds a futures
  position (``test_the_small_world_is_short_at_force_from_ms``) and no constant is moved;
* V3's pack: ``tests/test_v4_v3_as_built.py``'s 72 hours of V3.1's synthetic inputs, with V3's
  window moved onto them in the v3 tests, as that module does.

The world's repository is built from this checkout, as the workflow's rehearsal builds it, and
the gate on it (``test_world_tar_gates_as_rehearsal``) takes about half a minute here.

The scenarios are judged on ``v4_verdict_fixtures.full_set``'s 50-hour summaries (the module
fixture ``judged``), with hand-written forced cells and V3's period moved onto the cells' own
hours, as ``tests/test_v4_verdict_cli.py`` does: the real verdict step on every scenario, then
``check``. That is the local proof of the scenario table; the GitHub rehearsal repeats it on
cells the real CLIs wrote.

The network is blocked for every test (the autouse fixture, and the module fixtures block it for
their own runs). Only synthetic worlds in pytest's temporary folders are read.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import shutil
import socket
import sys
import tarfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import v4_verdict_fixtures
from test_combined_baseline_v3 import END, START
from test_v4_v3_as_built import fields as v3_fields
from test_v4_v3_as_built import train
from v4_verdict_fixtures import HOURS, full_set, marks_for, write_expected, write_summary

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine import run, safety, v3_as_built
from crypto_grid_bot.v4.engine.market import HOUR_MS, Market
from crypto_grid_bot.v4.engine.records import read_receipt, read_records
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    ENGINE_ERROR,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
    OUTCOME_COMPLETE,
)
from crypto_grid_bot.v4.engine.v3_as_built import run_v3_picks
from crypto_grid_bot.v4.synthetic import (
    CONFIG_SHA256,
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    every_month,
    hours_in,
    month_start,
    path,
    read_data_json,
    write_data_json,
)
from crypto_grid_bot.v4.verdict import inputs as verdict_inputs
from crypto_grid_bot.v4.verdict import rule
from crypto_grid_bot.v4.verdict.inputs import Expected, expected_cells, read_cell

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import v4_cell  # noqa: E402
import v4_registration  # noqa: E402
import v4_rehearsal  # noqa: E402
import v4_v3_cell  # noqa: E402
import v4_verdict  # noqa: E402
from v4_rehearsal import (  # noqa: E402
    DATA_DIR,
    FORCE_FROM_MS,
    FORCED,
    FORCED_CELL,
    REHEARSAL_CONFIG_PATH,
    SCENARIOS,
    SCENARIOS_FILE,
    V3_DIR,
    WORLD_FILE,
    WORLD_TAR,
)
from v4_v3_pack import EXPECTED_PACK_SHA256, PACK_FILE  # noqa: E402

MAIN = "v4_main-1000-1x"
V3_CELL = "v3_as_built-1000-1x"
V4_KINDS = ("liquidated", "limit_unrestorable", "accounting_failure", "engine_error")
V3_KINDS = ("v3_stop", "v3_accounting")
# The pre-2025 config's pin: a real data run's, which a rehearsal must never replay.
PRE2025_PIN = hashlib.sha256((ROOT / "config" / "v4_data_pre2025.json").read_bytes()).hexdigest()
# Every outcome and verdict word: none may appear in force's or check's standard output.
OUTCOME_WORDS = re.compile(
    r"\b(complete|liquidated|limit_unrestorable|accounting_failure|engine_error|pass|fail"
    r"|incomplete)\b"
)
HISTORY, FIRST, LAST = "2023-06", "2024-04", "2024-06"


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


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    for owner, name in _SOCKET_CALLS:
        monkeypatch.setattr(owner, name, _refuse)


@pytest.fixture(scope="module")
def module_network_blocked():
    """The same, for the module fixtures' own runs."""
    with pytest.MonkeyPatch.context() as patch:
        for owner, name in _SOCKET_CALLS:
            patch.setattr(owner, name, _refuse)
        yield


def run_cli(argv: Sequence[str]) -> tuple[int, str, str]:
    """``v4_rehearsal.main(argv)`` with its standard output and error captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = v4_rehearsal.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---- the small world -----------------------------------------------------------------------------


def small_world() -> World:
    """BTCUSDT and its perpetual, falling with noise from 2023-06 (the history feeds the signals),
    with universes, and so a window, from 2024-04 to 2024-06 (module docstring)."""
    hours = hours_in(HISTORY, LAST)
    closes = path("60000", (hours, "-0.0002"), noise="0.002", seed=1)
    btc = CoinSpec("BTCUSDT", Series(month_start(HISTORY), closes), perpetual=PerpetualSpec())
    return World(LAST, (btc,), every_month(FIRST, LAST, ("BTCUSDT",)))


@pytest.fixture(scope="module")
def world(module_network_blocked, tmp_path_factory) -> Path:
    """The small rehearsal world, written once through ``world --scale rehearsal``: its data, V3's
    pack, ``world.tar`` (built from this checkout) and ``rehearsal.json``."""
    root = tmp_path_factory.mktemp("small") / "world"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(v4_rehearsal, "rehearsal_world", small_world)
        patch.setattr(v4_rehearsal, "rehearsal_v3_fields", v3_fields)
        code, stdout, stderr = run_cli(["world", "--scale", "rehearsal", "--out", str(root)])
    assert (code, stderr) == (0, ""), stderr
    return root


@pytest.fixture(scope="module")
def market(world) -> Market:
    return Market.load(world / DATA_DIR)


def copy_world(world: Path, target: Path) -> Path:
    """A copy of the world's data, V3 pack and world file (not its repository), for a test to
    change."""
    for item in (DATA_DIR, V3_DIR):
        shutil.copytree(world / item, target / item)
    shutil.copyfile(world / WORLD_FILE, target / WORLD_FILE)
    return target


def write_world_file(folder: Path, **changes: object) -> None:
    document = v4_rehearsal.read_world(folder) | changes
    (folder / WORLD_FILE).write_bytes(_canonical(document))


def force_argv(world: Path, kind: str, out: Path, *extra: str) -> list[str]:
    return ["force", "--world", str(world), "--kind", kind, "--out", str(out), *extra]


def load(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_bytes())
    assert isinstance(document, dict)
    return document


def outcome_record(folder: Path) -> dict[str, Any]:
    receipt = read_receipt(folder / "receipt.json")
    (record,) = [
        rec for kind, rec in read_records(folder / "records.jsonl", receipt) if kind == "outcome"
    ]
    return record


def expected_of(market: Market, v3_pack: str, picks: str = "f" * 64) -> Expected:
    """What the rehearsal's verdict expects of the small world's cells."""
    data = run.data_record(market.pins)
    assert data is not None
    return Expected(
        "rehearsal",
        expected_cells("rehearsal"),
        run.window_record(market),
        {key: str(value) for key, value in data.items()},
        v3_pack,
        picks,
    )


def accepted(cell_folder: Path, cell: str, expected: Expected, tmp_path: Path):
    """The verdict's reading of a forced cell, as the scenarios hand it over: its summary and
    receipt in a ``v4-summary-<cell>-attempt-1`` folder."""
    folder = tmp_path / f"v4-summary-{cell}-attempt-1"
    folder.mkdir()
    for name in ("summary.json", "receipt.json"):
        shutil.copyfile(cell_folder / name, folder / name)
    return read_cell(folder, expected)


ORIGINALS = {
    (run, "liquidated"): safety.liquidated,
    (run, "ceiling_breached"): safety.ceiling_breached,
    (run, "_audit_failure"): run._audit_failure,
    (run, "_hourly_record"): run._hourly_record,
    (v3_as_built, "replay_v3_baseline"): v3_as_built.replay_v3_baseline,
}


def assert_engine_restored() -> None:
    for (module, name), original in ORIGINALS.items():
        assert vars(module)[name] is original, name


# ---- the constants -------------------------------------------------------------------------------


def test_the_constants():
    assert FORCED == (
        "liquidated",
        "limit_unrestorable",
        "accounting_failure",
        "engine_error",
        "v3_stop",
        "v3_accounting",
    )
    assert month_bounds_ms("2024-06")[0] == FORCE_FROM_MS
    assert dict(FORCED_CELL) == {"v3_stop": V3_CELL, "v3_accounting": V3_CELL}
    assert [v4_rehearsal.forced_cell(kind) for kind in FORCED] == [MAIN] * 4 + [V3_CELL] * 2
    assert SCENARIOS_FILE == "scenarios.json"
    assert dict(SCENARIOS) == {
        "base": "pass or fail",
        "main_liquidated": "fail",
        "main_limit": "fail",
        "main_accounting": "fail",
        "main_engine_error": "incomplete",
        "hold_missing": "incomplete",
        "v3_stop": "incomplete",
        "v3_accounting": "incomplete",
        "rerun": "incomplete",
        "relabelled": "incomplete",
        "liquidated_and_missing": "fail",
    }
    # The faults hit inside the rehearsal world's window, after V3's period has begun.
    assert month_start("2020-09") < v3_as_built.V3_START_MS < FORCE_FROM_MS < month_start("2025-01")


# ---- force ---------------------------------------------------------------------------------------


def test_the_small_world_is_short_at_force_from_ms(world, tmp_path):
    """Unforced, the cell runs to its window's end, and it holds a futures position at the hour a
    forced fault first may hit."""
    argv = ["run", "--data", str(world / DATA_DIR), "--arm", "v4_main", "--capital", "1000"]
    with contextlib.redirect_stdout(io.StringIO()):
        assert v4_cell.main([*argv, "--costs", "1", "--out", str(tmp_path)]) == 0
    folder = tmp_path / MAIN
    assert load(folder / "summary.json")["outcome"] == OUTCOME_COMPLETE
    receipt = read_receipt(folder / "receipt.json")
    hourly = {
        rec["open_ms"]: rec
        for kind, rec in read_records(folder / "records.jsonl", receipt)
        if kind == "hourly"
    }
    assert hourly[FORCE_FROM_MS]["margin_ratio"] is not None  # a futures leg is held


@pytest.mark.parametrize("kind", V4_KINDS)
def test_force_each_v4_kind_gives_its_outcome(world, market, tmp_path, kind):
    out = tmp_path / "forced"
    code, stdout, stderr = run_cli(force_argv(world, kind, out))
    assert (code, stderr) == (0, "")
    folder = out / MAIN
    raw = (folder / "summary.json").read_bytes()
    assert stdout == f"v4_rehearsal force: {MAIN}, summary sha256 {sha(raw)}: as expected\n"
    assert OUTCOME_WORDS.search(stdout) is None  # names, counts and pins only
    summary = load(folder / "summary.json")
    assert summary["cell"]["id"] == MAIN
    record = outcome_record(folder)
    if kind == "liquidated":
        assert (summary["outcome"], summary["reason"]) == (LIQUIDATED, None)
        assert summary["stop_ms"] == FORCE_FROM_MS
        assert record["check"] == "open_mark"  # the hour's first mark
    elif kind == "limit_unrestorable":
        assert (summary["outcome"], summary["reason"]) == (LIMIT_UNRESTORABLE, "ceiling")
        assert summary["stop_ms"] == FORCE_FROM_MS
    elif kind == "accounting_failure":
        assert (summary["outcome"], summary["identity"]) == (ACCOUNTING_FAILURE, "wallet")
        assert summary["hour_ms"] == FORCE_FROM_MS
    else:
        assert summary["outcome"] == ENGINE_ERROR
        assert (summary["type"], summary["message"]) == ("RuntimeError", "forced")
        assert summary["hour_ms"] == FORCE_FROM_MS
    if kind in ("liquidated", "limit_unrestorable"):
        assert record["mark"]["maintenance"] != "0"  # a futures position at the stop
    # The verdict's reader accepts the forced cell, so its outcome counts in the scenarios.
    facts = accepted(folder, MAIN, expected_of(market, "e" * 64), tmp_path)
    assert facts.outcome == summary["outcome"]
    assert_engine_restored()


def test_force_from_ms_is_read_when_the_cell_runs(world, tmp_path, monkeypatch):
    """The constant is looked up while the cell runs, so a fault can be moved (and a fault never
    hits before it)."""
    earlier = month_start("2024-05") + 14 * 24 * HOUR_MS + 7 * HOUR_MS
    monkeypatch.setattr(v4_rehearsal, "FORCE_FROM_MS", earlier)
    code, _, stderr = run_cli(force_argv(world, "liquidated", tmp_path))
    assert (code, stderr) == (0, "")
    assert load(tmp_path / MAIN / "summary.json")["stop_ms"] == earlier
    assert_engine_restored()


def test_force_fails_when_the_outcome_is_not_the_forced_one(world, tmp_path, monkeypatch):
    """A fault that never hits (it would hit after the window) leaves the cell complete: force
    exits 1 and says so without naming the outcome."""
    monkeypatch.setattr(v4_rehearsal, "FORCE_FROM_MS", month_start("2024-07"))
    code, stdout, stderr = run_cli(force_argv(world, "engine_error", tmp_path))
    assert (code, stdout) == (1, "")
    assert stderr == f"v4_rehearsal force: {MAIN}: NOT as expected\n"
    assert load(tmp_path / MAIN / "summary.json")["outcome"] == OUTCOME_COMPLETE
    assert_engine_restored()
    # A fault that fires, with a summary that is not the outcome asked for (here a stand-in
    # demand for another reason), is not as expected either.
    wanted = dict(v4_rehearsal._WANTED)
    wanted["liquidated"] = ({"outcome": LIQUIDATED, "reason": "ceiling"}, "stop_ms")
    monkeypatch.setattr(v4_rehearsal, "_WANTED", wanted)
    monkeypatch.setattr(v4_rehearsal, "FORCE_FROM_MS", FORCE_FROM_MS)
    code, stdout, stderr = run_cli(force_argv(world, "liquidated", tmp_path / "fired"))
    assert (code, stdout) == (1, "")
    assert stderr == f"v4_rehearsal force: {MAIN}: NOT as expected\n"
    assert load(tmp_path / "fired" / MAIN / "summary.json")["outcome"] == LIQUIDATED
    assert_engine_restored()


def forced_summary(kind: str) -> dict[str, object]:
    """The summary fields a forced cell of ``kind`` must carry."""
    summary: dict[str, object] = {"cell": {"id": v4_rehearsal.forced_cell(kind)}}
    fields, hour = v4_rehearsal._WANTED[kind]
    summary.update(fields)
    if hour is not None:
        summary[hour] = FORCE_FROM_MS
    return summary


@pytest.mark.parametrize("kind", FORCED)
def test_the_forced_outcome_is_checked_field_by_field(kind):
    cell = v4_rehearsal.forced_cell(kind)
    summary = forced_summary(kind)
    assert v4_rehearsal._is_forced(kind, cell, summary)
    assert not v4_rehearsal._is_forced(kind, "v4_main-10000-1x", summary)
    assert not v4_rehearsal._is_forced(kind, cell, summary | {"cell": {"id": "v4_main-10000-1x"}})
    for key in summary:
        if key == "cell":
            continue
        wrong = "other" if key != "stop_ms" and key != "hour_ms" else FORCE_FROM_MS - HOUR_MS
        assert not v4_rehearsal._is_forced(kind, cell, summary | {key: wrong}), key
        dropped = {name: value for name, value in summary.items() if name != key}
        assert not v4_rehearsal._is_forced(kind, cell, dropped), key
    for hour_key in ("stop_ms", "hour_ms"):
        if hour_key in summary:  # a bool is not an hour
            assert not v4_rehearsal._is_forced(kind, cell, summary | {hour_key: True})
    assert not v4_rehearsal._is_forced(kind, cell, [summary])
    # Each kind's outcome is its own: another kind's summary is not it.
    for other in FORCED:
        if other != kind and v4_rehearsal.forced_cell(other) == cell:
            assert not v4_rehearsal._is_forced(kind, cell, forced_summary(other)), other


def test_force_restores_the_engine(world, tmp_path, monkeypatch):
    # While the block runs exactly the kind's name is replaced; afterwards every name is the
    # original, after an exception too.
    replaced = {
        "liquidated": (run, "liquidated"),
        "limit_unrestorable": (run, "ceiling_breached"),
        "accounting_failure": (run, "_audit_failure"),
        "engine_error": (run, "_hourly_record"),
        "v3_stop": (v3_as_built, "replay_v3_baseline"),
        "v3_accounting": (v3_as_built, "replay_v3_baseline"),
    }
    for kind in FORCED:
        with pytest.raises(RuntimeError, match="inside"), v4_rehearsal.forcing(kind):
            for key, original in ORIGINALS.items():
                assert (vars(key[0])[key[1]] is original) == (key != replaced[kind]), kind
            raise RuntimeError("inside the block")
        assert_engine_restored()
    # The command, when the cell's CLI raises while the name is replaced.
    seen = []

    def broken(argv: Sequence[str]) -> int:
        seen.append(run.liquidated is not safety.liquidated)
        raise RuntimeError("secret detail 4242.5")

    runner = v4_rehearsal.v4_cell_main
    monkeypatch.setattr(v4_rehearsal, "v4_cell_main", broken)
    code, stdout, stderr = run_cli(force_argv(world, "liquidated", tmp_path / "broken"))
    assert (code, stdout, seen) == (1, "", [True])
    assert stderr == f"v4_rehearsal force: {MAIN}: the cell did not run: RuntimeError\n"
    assert_engine_restored()
    monkeypatch.setattr(v4_rehearsal, "v4_cell_main", runner)
    # And when the cell's CLI refuses (its folder already holds a summary).
    taken = tmp_path / "taken" / MAIN
    taken.mkdir(parents=True)
    (taken / "summary.json").write_bytes(b"{}")
    code, stdout, stderr = run_cli(force_argv(world, "liquidated", tmp_path / "taken"))
    assert (code, stdout) == (1, "")
    assert stderr.endswith(f"v4_rehearsal force: {MAIN}: the cell's CLI wrote no summary\n")
    assert_engine_restored()


def test_force_refuses_a_real_world(world, tmp_path):
    """A world whose data is a real config's, a timing world and V3.1's own pack are refused
    before anything runs: nothing is written and no name is replaced."""
    real = copy_world(world, tmp_path / "real")
    header = read_data_json(real / DATA_DIR)
    write_data_json(real / DATA_DIR, header | {"config_sha256": PRE2025_PIN})
    data = v4_rehearsal.read_world(real)["data"]
    assert isinstance(data, dict)
    claimed = copy_world(real, tmp_path / "claimed")  # rehearsal.json names the real config too
    write_world_file(claimed, data=data | {"config_sha256": PRE2025_PIN})
    timing = copy_world(world, tmp_path / "timing")
    write_world_file(timing, scale="timing", v3_pack_sha256=None)
    v31 = copy_world(world, tmp_path / "v31")
    write_world_file(v31, v3_pack_sha256=EXPECTED_PACK_SHA256)
    picks = ["--picks", str(tmp_path / "picks.json"), "--picks-sha256", "f" * 64]
    cases = [
        (real, "liquidated", [], "refused: the data pack is not synthetic: ValueError"),
        (claimed, "liquidated", [], "refused: rehearsal.json names data that is not synthetic"),
        (claimed, "v3_stop", picks, "refused: rehearsal.json names data that is not synthetic"),
        (timing, "engine_error", [], "refused: rehearsal.json is not a rehearsal world's"),
        (v31, "v3_accounting", picks, "refused: the world names V3.1's registered pack"),
        (world, "v3_stop", [], "refused: a v3 kind needs --picks and --picks-sha256"),
        (world, "liquidated", picks, "refused: --picks and --picks-sha256 go with a v3 kind"),
        (tmp_path / "nothing", "liquidated", [], "reading rehearsal.json failed: ValueError"),
    ]
    for index, (folder, kind, extra, line) in enumerate(cases):
        out = tmp_path / f"out{index}"
        code, stdout, stderr = run_cli(force_argv(folder, kind, out, *extra))
        assert (code, stdout) == (1, ""), line
        assert stderr == f"v4_rehearsal force: {line}\n"
        assert not out.exists()
        assert_engine_restored()
    assert read_data_json(world / DATA_DIR)["config_sha256"] == CONFIG_SHA256  # untouched


def test_force_v3_kinds(world, market, tmp_path, monkeypatch):
    """V3's stop and V3's failed reconciliation, through ``v4_v3_cell.py run`` on the small V3
    pack, V3's window moved onto its 72 hours (``tests/test_v4_v3_as_built.py``'s fixtures)."""
    for module in (v3_as_built, verdict_inputs):
        monkeypatch.setattr(module, "V3_START_MS", START)
        monkeypatch.setattr(module, "V3_END_MS", END)
    train(monkeypatch)
    v3_pin = v4_rehearsal.read_world(world)["v3_pack_sha256"]
    assert isinstance(v3_pin, str)
    pack = world / V3_DIR / PACK_FILE
    picks_sha = run_v3_picks(pack, v3_pin, tmp_path / "picks")
    picks = ["--picks", str(tmp_path / "picks" / "v3_picks.json"), "--picks-sha256", picks_sha]
    # Unforced, the cell is complete.
    argv = ["run", "--pack", str(pack), "--pack-sha256", v3_pin, *picks, "--capital", "1000"]
    with contextlib.redirect_stdout(io.StringIO()):
        assert v4_v3_cell.main([*argv, "--costs", "1", "--out", str(tmp_path / "plain")]) == 0
    assert load(tmp_path / "plain" / V3_CELL / "summary.json")["outcome"] == OUTCOME_COMPLETE
    expected = expected_of(market, v3_pin, picks_sha)
    for kind, kind_type, message in (
        ("v3_stop", "V3Stop", "forced"),
        ("v3_accounting", "V3Accounting", "accounting_explained"),
    ):
        out = tmp_path / kind
        code, stdout, stderr = run_cli(force_argv(world, kind, out, *picks))
        assert (code, stderr) == (0, "")
        raw = (out / V3_CELL / "summary.json").read_bytes()
        assert stdout == f"v4_rehearsal force: {V3_CELL}, summary sha256 {sha(raw)}: as expected\n"
        summary = load(out / V3_CELL / "summary.json")
        assert summary["outcome"] == ENGINE_ERROR
        assert (summary["type"], summary["message"]) == (kind_type, message)
        facts = accepted(out / V3_CELL, V3_CELL, expected, tmp_path / kind)
        assert (facts.outcome, facts.reason) == (ENGINE_ERROR, kind_type)
        assert_engine_restored()


# ---- scenarios and check -------------------------------------------------------------------------

FORCED_SUMMARIES: dict[str, dict[str, object]] = {
    "liquidated": {
        "outcome": LIQUIDATED,
        "marks": marks_for(MAIN)[:20],
        "final_after_close": None,
        "equity_2025": None,
    },
    "limit_unrestorable": {
        "outcome": LIMIT_UNRESTORABLE,
        "marks": marks_for(MAIN)[:20],
        "final_after_close": None,
        "equity_2025": None,
    },
    "accounting_failure": {"outcome": ACCOUNTING_FAILURE},
    "engine_error": {"outcome": ENGINE_ERROR, "message": "forced"},
    "v3_stop": {"outcome": ENGINE_ERROR, "message": "forced"},
    "v3_accounting": {
        "outcome": ENGINE_ERROR,
        "type": "V3Accounting",
        "message": "accounting_explained",
    },
}


def write_forced(forced: Path, expected: Expected) -> None:
    """The forced cells as ``force`` lays them out, ``forced/<kind>/<cell id>/``, hand-written to
    match the base set."""
    staging = forced.parent / "forced-staging"
    for kind, keywords in FORCED_SUMMARIES.items():
        cell = v4_rehearsal.forced_cell(kind)
        written = write_summary(staging / kind, cell, expected=expected, **keywords)
        (forced / kind).mkdir(parents=True)
        written.rename(forced / kind / cell)


def tree(folder: Path) -> dict[str, dict[str, bytes]]:
    """Every subfolder of ``folder`` and the bytes of its files."""
    return {
        sub.name: {item.name: item.read_bytes() for item in sorted(sub.iterdir())}
        for sub in sorted(folder.iterdir())
        if sub.is_dir()
    }


@dataclass(frozen=True)
class Judged:
    root: Path
    expected: Expected
    stdout: str

    @property
    def base(self) -> Path:
        return self.root / "summaries"

    @property
    def forced(self) -> Path:
        return self.root / "forced"

    @property
    def scenarios(self) -> Path:
        return self.root / "scenarios"

    @property
    def verdicts(self) -> Path:
        return self.root / "verdicts"


@contextlib.contextmanager
def short_v3_period() -> Iterator[None]:
    """V3's period moved onto the fixtures' 50 hours (``tests/test_v4_verdict_cli.py``)."""
    end = v4_verdict_fixtures.START_MS + HOURS * HOUR_MS
    with pytest.MonkeyPatch.context() as patch:
        for module in (v3_as_built, verdict_inputs, rule, v4_verdict_fixtures):
            patch.setattr(module, "V3_END_MS", end)
        yield


@pytest.fixture(scope="module")
def judged(module_network_blocked, tmp_path_factory) -> Judged:
    """The base set, the forced cells, the scenarios written by ``scenarios`` and the verdict
    step's verdict on each of them."""
    root = tmp_path_factory.mktemp("judged")
    with short_v3_period():
        expected = full_set(root / "summaries")
        write_expected(root / "expected.json", expected)
        write_forced(root / "forced", expected)
        argv = ["scenarios", "--base", str(root / "summaries"), "--forced", str(root / "forced")]
        code, stdout, stderr = run_cli([*argv, "--out", str(root / "scenarios")])
        assert (code, stderr) == (0, ""), stderr
        for name in SCENARIOS:
            step = [
                "--summaries",
                str(root / "scenarios" / name),
                "--expected",
                str(root / "expected.json"),
                "--progress",
                str(root / "progress" / name),
                "--out",
                str(root / "verdicts" / name),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                assert v4_verdict.main(step) == 0, name
    return Judged(root, expected, stdout)


def folder_of(cell: str, attempt: int = 1) -> str:
    return f"v4-summary-{cell}-attempt-{attempt}"


def test_scenarios_layout_and_expectations(judged):
    assert judged.stdout == (
        f"v4_rehearsal scenarios: {len(SCENARIOS)} scenarios of 48 base folders and "
        f"{len(FORCED)} forced cells\n"
    )
    raw = (judged.scenarios / SCENARIOS_FILE).read_bytes()
    assert raw == _canonical(dict(SCENARIOS))
    assert sorted(item.name for item in judged.scenarios.iterdir()) == sorted(
        [*SCENARIOS, SCENARIOS_FILE]
    )
    base = tree(judged.base)
    forced = {kind: tree(judged.forced / kind) for kind in FORCED}

    def with_forced(layout: dict[str, dict[str, bytes]], kind: str) -> None:
        cell = v4_rehearsal.forced_cell(kind)
        assert folder_of(cell) in layout
        layout[folder_of(cell)] = forced[kind][cell]

    for name in SCENARIOS:
        layout = dict(base)
        if name.startswith("main_") or name in ("v3_stop", "v3_accounting"):
            kind = {
                "main_liquidated": "liquidated",
                "main_limit": "limit_unrestorable",
                "main_accounting": "accounting_failure",
                "main_engine_error": "engine_error",
            }.get(name, name)
            with_forced(layout, kind)
        elif name == "hold_missing":
            del layout[folder_of("hold_universe-10000-1x")]
        elif name == "rerun":
            layout[folder_of("v4_main-10000-2x", 2)] = layout.pop(folder_of("v4_main-10000-2x"))
        elif name == "relabelled":
            layout[folder_of("hold_universe-10000-1x")] = base[folder_of("hold_universe-1000-1x")]
        elif name == "liquidated_and_missing":
            with_forced(layout, "liquidated")
            del layout[folder_of("hold_universe-10000-1x")]
        assert tree(judged.scenarios / name) == layout, name
    # The verdict step's own verdict on each scenario is the expected one.
    for name, wanted in SCENARIOS.items():
        verdict = load(judged.verdicts / name / "verdict.json")
        outcome = verdict["verdict"]["outcome"]
        assert outcome == ("pass" if name == "base" else wanted), name
    base_verdict = load(judged.verdicts / "base" / "verdict.json")
    assert (base_verdict["missing"], base_verdict["refused"]) == ([], [])
    # ... and check agrees, scenario by scenario.
    argv = ["check", "--scenarios", str(judged.scenarios), "--verdicts", str(judged.verdicts)]
    code, stdout, stderr = run_cli(argv)
    assert (code, stderr) == (0, "")
    assert stdout == "".join(f"{name}: as expected\n" for name in SCENARIOS)


def test_check_flags_a_scenario_not_as_expected(judged, tmp_path):
    verdicts = tmp_path / "verdicts"
    shutil.copytree(judged.verdicts, verdicts)
    argv = ["check", "--scenarios", str(judged.scenarios), "--verdicts", str(verdicts)]
    # A liquidated v4_main that the verdict did not fail.
    shutil.copyfile(
        verdicts / "hold_missing" / "verdict.json", verdicts / "main_liquidated" / "verdict.json"
    )
    # A base that passes with a missing cell is not the base asked for.
    base = load(verdicts / "base" / "verdict.json")
    (verdicts / "base" / "verdict.json").write_bytes(_canonical(base | {"missing": [MAIN]}))
    # A scenario the verdict step never judged.
    (verdicts / "rerun" / "verdict.json").unlink()
    code, stdout, stderr = run_cli(argv)
    assert code == 1
    flagged = {"base", "main_liquidated", "rerun"}
    assert stdout == "".join(
        f"{name}: {'NOT as expected' if name in flagged else 'as expected'}\n" for name in SCENARIOS
    )
    assert OUTCOME_WORDS.search(stdout) is None  # scenario names and the two phrases only
    assert stderr == "v4_rehearsal check: rerun: verdict.json cannot be read\n"
    # A refused cell in the base is not the base asked for either.
    (verdicts / "base" / "verdict.json").write_bytes(
        _canonical(base | {"refused": [{"folder": "x", "step": "json", "reason": "r"}]})
    )
    shutil.copyfile(judged.verdicts / "rerun" / "verdict.json", verdicts / "rerun" / "verdict.json")
    shutil.copyfile(
        judged.verdicts / "main_liquidated" / "verdict.json",
        verdicts / "main_liquidated" / "verdict.json",
    )
    code, stdout, _ = run_cli(argv)
    assert code == 1
    assert stdout.splitlines()[0] == "base: NOT as expected"
    assert stdout.count("NOT as expected") == 1
    # A scenarios file that is not this script's is refused: nothing is judged.
    changed = tmp_path / "scenarios"
    changed.mkdir()
    (changed / SCENARIOS_FILE).write_bytes(_canonical(dict(SCENARIOS) | {"base": "pass"}))
    code, stdout, stderr = run_cli(
        ["check", "--scenarios", str(changed), "--verdicts", str(verdicts)]
    )
    assert (code, stdout) == (1, "")
    assert stderr == "v4_rehearsal check: refused: scenarios.json is not this script's table\n"


def test_scenarios_refuses_what_it_cannot_alter(judged, tmp_path):
    """An output that exists, a base without a folder a scenario changes, and a forced set without
    one of its six cells are refused, with nothing written."""
    taken = tmp_path / "taken"
    taken.mkdir()
    argv = ["scenarios", "--base", str(judged.base), "--forced", str(judged.forced)]
    code, stdout, stderr = run_cli([*argv, "--out", str(taken)])
    assert (code, stdout) == (1, "")
    assert stderr == "v4_rehearsal scenarios: refused: the output folder already exists\n"
    assert list(taken.iterdir()) == []
    partial = tmp_path / "partial"
    shutil.copytree(judged.base, partial)
    shutil.rmtree(partial / folder_of("v4_main-10000-2x"))
    out = tmp_path / "out"
    argv = ["scenarios", "--base", str(partial), "--forced", str(judged.forced), "--out", str(out)]
    code, stdout, stderr = run_cli(argv)
    assert (code, stdout) == (1, "")
    assert stderr == (
        f"v4_rehearsal scenarios: refused: the base has no folder {folder_of('v4_main-10000-2x')}\n"
    )
    assert not out.exists()
    forced = tmp_path / "forced"
    shutil.copytree(judged.forced, forced)
    shutil.rmtree(forced / "v3_accounting")
    argv = ["scenarios", "--base", str(judged.base), "--forced", str(forced), "--out", str(out)]
    code, stdout, stderr = run_cli(argv)
    assert (code, stdout) == (1, "")
    assert stderr == (
        f"v4_rehearsal scenarios: refused: the forced cells have no v3_accounting/{V3_CELL}\n"
    )
    assert not out.exists()


# ---- the world's repository ----------------------------------------------------------------------


def test_world_tar_gates_as_rehearsal(world, tmp_path):
    """The world's repository, untarred as the plan job does, passes the job gate of a rehearsal
    with the registration ``rehearsal.json`` records, and pins the world's own data and pack."""
    assert sorted(item.name for item in world.iterdir()) == sorted(
        [DATA_DIR, V3_DIR, WORLD_FILE, WORLD_TAR]  # no staging folder is left behind
    )
    document = v4_rehearsal.read_world(world)
    registration = document["registration_sha256"]
    assert isinstance(registration, str)
    with tarfile.open(world / WORLD_TAR) as tar:
        assert {member.name.split("/")[0] for member in tar.getmembers()} == {"repo"}
        tar.extractall(tmp_path, filter="data")
    gated = v4_registration.gate(tmp_path / "repo", "rehearsal", registration)
    assert gated.registration_sha256 == registration
    data = document["data"]
    assert isinstance(data, dict)
    assert dict(gated.manifest.data) == {"config_path": REHEARSAL_CONFIG_PATH, **data}
    assert gated.manifest.v3_pack_sha256 == document["v3_pack_sha256"]
    assert data["config_sha256"] == CONFIG_SHA256
