"""V4 step 4b, task 2: the verdict's inputs (``v4.verdict.inputs``): one cell's summary, accepted
or refused, and the expected file.

Three kinds of test. Two pin the format constants to real summaries: ``FULL_KEYS`` to the one a
real ``v4_cell`` run writes (on a world that never trades), and ``V3_FULL_KEYS`` to a real v3
summary (V3.1's synthetic inputs, as ``tests/test_v4_v3_as_built.py`` builds it), and both are
then read back through ``read_cell``. The rest write hand-built summaries (``v4_verdict_fixtures``)
and change one thing at a time, for each step of V1 to V3 of the plan's rulings, in the order the
steps are applied. The last test reads every cell of the fixtures' standard sets, so the fixtures
that tasks 4 and 7 build on are valid by this task's checks.

The network is blocked for every test (the autouse fixture). Only synthetic data is read.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import socket
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from test_combined_baseline_v3 import END, START
from test_v4_v3_as_built import run_cell, summary_of, world
from v4_synthetic import (
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    every_month,
    hours_in,
    month_start,
    write_world,
)
from v4_verdict_fixtures import (
    DATA,
    DROP,
    PICKS,
    START_MS,
    V3_PACK,
    edit_summary,
    equity_at,
    expected_for,
    full_set,
    load_summary,
    marks_for,
    spec_of,
    standard_cell,
    store_summary,
    write_expected,
    write_summary,
)

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine import run, v3_as_built
from crypto_grid_bot.v4.engine.arms import all_cells
from crypto_grid_bot.v4.engine.ledger import Ledger
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.run import data_record, window_record
from crypto_grid_bot.v4.verdict import inputs
from crypto_grid_bot.v4.verdict.inputs import (
    EXPECTED_FORMAT,
    FAILURE_KEYS,
    FOLDER,
    FULL_KEYS,
    MODES,
    V3_FULL_KEYS,
    CellFacts,
    CellRefused,
    Expected,
    expected_record,
    facts_from_record,
    facts_record,
    read_cell,
    read_expected,
    read_marks,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_cell  # noqa: E402

CELL = "v4_main-10000-1x"
SMALL = "hold_universe-1000-1x"
V3_CELL = "v3_as_built-1000-1x"
JAN = month_start("2025-01")


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def _refuse(*args: object, **kwargs: object) -> None:
    raise NetworkBlocked("the network is blocked in tests")


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    for owner, name in [
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ]:
        monkeypatch.setattr(owner, name, _refuse)


def tiny_world() -> World:
    """BTCUSDT flat at 100 with its perpetual, January 2025 only: a world that never trades
    (``tests/test_v4_cell_cli.py``'s, copied)."""
    hours = hours_in("2025-01", "2025-01")
    btc = CoinSpec("BTCUSDT", Series(JAN, ("100",) * hours), perpetual=PerpetualSpec())
    return World("2025-01", (btc,), every_month("2025-01", "2025-01", ("BTCUSDT",)))


def put(root, cell_id=CELL, *, expected=None, **keywords):
    """A standard cell written under ``root``; the keywords replace the standard ones. Returns
    the folder and the expected document it matches."""
    expected = expected if expected is not None else expected_for()
    return write_summary(
        root, cell_id, expected=expected, **{**standard_cell(cell_id), **keywords}
    ), expected


def refusal(folder, expected) -> CellRefused:
    with pytest.raises(CellRefused) as caught:
        read_cell(folder, expected)
    return caught.value


def step_of(folder, expected) -> str:
    return refusal(folder, expected).step


# ---- the formats are the real ones ----------------------------------------------------------


def test_full_keys_match_a_real_summary(tmp_path):
    """A real ``v4_cell`` run on a world that never trades writes a summary whose keys are
    ``FULL_KEYS``; renamed as the verdict's folder, with its receipt, it is accepted."""
    data = write_world(tmp_path / "world", tiny_world())
    out = tmp_path / "out"
    argv = ["run", "--data", str(data), "--arm", "v4_main", "--capital", "10000"]
    argv += ["--costs", "1", "--out", str(out)]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert v4_cell.main(argv) == 0
    made = out / "v4_main-10000-1x"
    summary = json.loads((made / "summary.json").read_bytes())
    assert set(summary) == FULL_KEYS

    folder = tmp_path / "summaries" / "v4-summary-v4_main-10000-1x-attempt-1"
    folder.mkdir(parents=True)
    for name in ("summary.json", "receipt.json"):
        shutil.copyfile(made / name, folder / name)
    market = Market.load(data)
    expected = Expected(
        "timing", (CELL,), window_record(market), data_record(market.pins), None, None
    )

    facts = read_cell(folder, expected)

    assert (facts.cell_id, facts.arm, facts.capital, facts.cost_multiple) == (
        CELL,
        "v4_main",
        10000,
        1,
    )
    assert (facts.outcome, facts.reason, facts.stop_ms) == ("complete", None, None)
    assert facts.initial_equity == Decimal(10000)
    assert facts.marks == len(summary["open_marks"]) == hours_in("2025-01", "2025-01")
    assert facts.summary_sha256 == hashlib.sha256((made / "summary.json").read_bytes()).hexdigest()
    assert facts.disclosures == ()
    assert [era["name"] for era in facts.eras] == ["start-2020", "2021-2024", "2025-end"]
    assert [year["year"] for year in facts.years] == [2025]


class _BrokenAudit(Ledger):
    """A ledger whose audit reports ``changes`` from its first call on
    (``tests/test_v4_engine_summary.py``'s, copied)."""

    changes: dict = {}

    def audit(self, prices):
        return replace(super().audit(prices), **type(self).changes)


def real_cell(tmp_path, arm="v4_main"):
    """``v4_cell.main`` on the world that never trades: the cell's summary and receipt as the
    verdict's folder, and the expected document of its world."""
    data = write_world(tmp_path / "world", tiny_world())
    argv = ["run", "--data", str(data), "--arm", arm, "--capital", "10000"]
    argv += ["--costs", "1", "--out", str(tmp_path / "out")]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert v4_cell.main(argv) == 0
    cell_id = f"{arm}-10000-1x"
    folder = tmp_path / "summaries" / f"v4-summary-{cell_id}-attempt-1"
    folder.mkdir(parents=True)
    for name in ("summary.json", "receipt.json"):
        shutil.copyfile(tmp_path / "out" / cell_id / name, folder / name)
    market = Market.load(data)
    expected = Expected(
        "timing", (cell_id,), window_record(market), data_record(market.pins), None, None
    )
    return folder, expected


def test_a_real_hold_summary_is_accepted(tmp_path):
    folder, expected = real_cell(tmp_path, "hold_universe")
    facts = read_cell(folder, expected)
    assert (facts.arm, facts.outcome, facts.marks) == ("hold_universe", "complete", 744)


@pytest.mark.parametrize(
    ("case", "changes"),
    [
        ("wallet", {"wallet_residual": Decimal("1E-40")}),
        ("quantity", {"quantity_residuals": {("spot", "BTCUSDT"): Decimal("-1E-40")}}),
        ("equity", {"equity_residual": Decimal("1.1E-18")}),
    ],
)
def test_a_real_accounting_failure_summary_is_accepted(case, changes, monkeypatch, tmp_path):
    """The failure summaries the engine writes (the identity and the audit's residuals as
    strings, ``1E-40`` among them) are accepted: they have no marks and no receipt check."""
    monkeypatch.setattr(run, "Ledger", type("Broken", (_BrokenAudit,), {"changes": changes}))
    folder, expected = real_cell(tmp_path)
    summary = json.loads((folder / "summary.json").read_bytes())
    assert set(summary) == FAILURE_KEYS["accounting_failure"]

    facts = read_cell(folder, expected)

    assert (facts.outcome, facts.reason, facts.marks) == ("accounting_failure", case, 0)
    assert facts.final_equity is None and facts.stop_ms is None
    (folder / "receipt.json").unlink()
    assert read_cell(folder, expected).outcome == "accounting_failure"


def test_a_real_engine_error_summary_is_accepted(monkeypatch, tmp_path):
    original = run._V4Cell._fills

    def fills_then_fail(self, h):
        if h >= JAN + 2 * 3600000:
            raise RuntimeError("injected failure")
        return original(self, h)

    monkeypatch.setattr(run._V4Cell, "_fills", fills_then_fail)
    folder, expected = real_cell(tmp_path)
    summary = json.loads((folder / "summary.json").read_bytes())
    assert set(summary) == FAILURE_KEYS["engine_error"]

    facts = read_cell(folder, expected)

    assert (facts.outcome, facts.reason, facts.marks) == ("engine_error", "RuntimeError", 0)
    assert summary["hour_ms"] == JAN + 2 * 3600000 and "injected" not in facts.reason


@pytest.mark.parametrize("capital", [10000, 1000])
def test_v3_full_keys_match_a_real_v3_summary(capital, tmp_path, monkeypatch):
    """A v3 summary built by ``build_v3_summary`` on V3.1's synthetic inputs has the keys
    ``V3_FULL_KEYS`` (V4's and ``disclosures``) and, with the window moved onto the synthetic
    world's as ``tests/test_v4_v3_as_built.py`` does, is accepted: its window, its two pins and its
    receipt are what the format says. At 1,000 USDT the capital adapter is among its disclosures."""
    for module in (v3_as_built, inputs):
        monkeypatch.setattr(module, "V3_START_MS", START)
        monkeypatch.setattr(module, "V3_END_MS", END)
    w = world(tmp_path, monkeypatch)
    made, receipt = run_cell(w, capital=capital)
    summary = summary_of(made, receipt, capital=capital)
    assert set(summary) == V3_FULL_KEYS

    cell_id = f"v3_as_built-{capital}-1x"
    folder = tmp_path / "summaries" / f"v4-summary-{cell_id}-attempt-1"
    folder.mkdir(parents=True)
    (folder / "summary.json").write_bytes(_canonical(summary))
    shutil.copyfile(made / "receipt.json", folder / "receipt.json")
    expected = Expected("rehearsal", (cell_id,), {}, DATA, w.pack_sha256, w.picks_sha256)

    facts = read_cell(folder, expected)

    assert (facts.arm, facts.capital, facts.outcome) == ("v3_as_built", capital, "complete")
    assert facts.marks == len(summary["open_marks"])
    assert facts.equity_2025 is None and facts.final_after_close is None
    assert facts.disclosures == tuple(summary["disclosures"])
    assert (v3_as_built.V3_CAPITAL_ADAPTER in facts.disclosures) == (capital != 10000)
    assert facts.final_equity == Decimal(summary["final_equity"])


# ---- accepted: what the facts are -----------------------------------------------------------


def test_an_accepted_complete_cell_gives_its_facts(tmp_path):
    folder, expected = put(tmp_path)
    document = load_summary(folder)

    facts = read_cell(folder, expected)

    assert facts == CellFacts(
        folder=folder.name,
        cell_id=CELL,
        arm="v4_main",
        capital=10000,
        cost_multiple=1,
        outcome="complete",
        reason=None,
        stop_ms=None,
        initial_equity=Decimal(10000),
        final_equity=Decimal(document["final_equity"]),
        equity_2025=Decimal(document["equity_2025"]),
        final_after_close=Decimal(document["final_after_close"]),
        compounded_return=Decimal(document["compounded_return"]),
        max_drawdown=Decimal(document["max_drawdown"]),
        eras=tuple(document["eras"]),
        years=tuple(document["years"]),
        disclosures=(),
        summary_sha256=hashlib.sha256((folder / "summary.json").read_bytes()).hexdigest(),
        marks=50,
    )
    assert facts.final_equity == equity_at(CELL, 50)
    assert facts.max_drawdown == 0 and facts.compounded_return == Decimal("0.1")


@pytest.mark.parametrize(
    ("outcome", "reason"), [("liquidated", None), ("limit_unrestorable", "ceiling")]
)
def test_an_accepted_stopped_cell_gives_its_stop(outcome, reason, tmp_path):
    marks = marks_for(CELL, 20)
    folder, expected = put(tmp_path, outcome=outcome, marks=marks, final_after_close=None)

    facts = read_cell(folder, expected)

    assert (facts.outcome, facts.reason, facts.stop_ms) == (outcome, reason, marks[-1][0])
    assert facts.final_after_close is None and facts.marks == 20
    assert facts.final_equity == Decimal(marks[-1][1])


def test_read_marks_returns_the_open_marks_as_decimals(tmp_path):
    folder, expected = put(
        tmp_path, marks=[*marks_for(CELL, 3)[:2], (START_MS + 7200000, "9999.5", False)]
    )
    read_cell(folder, expected)

    assert read_marks(folder) == [
        (START_MS, Decimal(10000), True),
        (START_MS + 3600000, Decimal(10020), True),
        (START_MS + 7200000, Decimal("9999.5"), False),
    ]


def test_read_marks_refuses_a_file_changed_after_it_was_accepted(tmp_path):
    folder, expected = put(tmp_path)
    read_cell(folder, expected)
    (folder / "summary.json").write_bytes((folder / "summary.json").read_bytes() + b"\n")
    with pytest.raises(CellRefused) as caught:
        read_marks(folder)
    assert caught.value.step == "json"


# ---- step 1, folder; step 2, rerun ----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "v4-summary-v4_main-10000-1x",
        "v4-summary-v4_main-10000-1x-attempt-0",
        "v4-summary-v4_main-10000-1x-attempt-01",
        "v4-summary-v4_main-10000-3x-attempt-1",
        "v4-summary-V4_main-10000-1x-attempt-1",
        "v4-cell-v4_main-10000-1x-attempt-1",
        "v4-summary-v4_main-10000-1x-attempt-1.bak",
    ],
)
def test_refuses_a_folder_not_named_for_a_cell_and_an_attempt(name, tmp_path):
    folder, expected = put(tmp_path)
    renamed = folder.rename(tmp_path / name)
    assert step_of(renamed, expected) == "folder"


def test_refuses_a_path_that_is_not_a_folder(tmp_path):
    expected = expected_for()
    plain = tmp_path / "v4-summary-v4_main-10000-1x-attempt-1"
    plain.write_bytes(b"{}")
    assert step_of(plain, expected) == "folder"
    assert step_of(tmp_path / "v4-summary-v4_main-1000-1x-attempt-1", expected) == "folder"


def test_folder_pattern_names_a_cell_and_an_attempt():
    found = FOLDER.fullmatch("v4-summary-v4_main-10000-1x-attempt-12")
    assert found is not None and (found["cell"], found["attempt"]) == (CELL, "12")
    assert FOLDER.fullmatch("v4-summary-v4_main-10000-1x-attempt-0") is None


def test_refuses_a_rerun_folder(tmp_path):
    folder, expected = put(tmp_path, attempt=2)
    assert step_of(folder, expected) == "rerun"


def test_a_rerun_is_refused_before_its_file_is_read(tmp_path):
    folder, expected = put(tmp_path, attempt=3)
    (folder / "summary.json").write_bytes(b"not json at all")
    assert step_of(folder, expected) == "rerun"


# ---- step 3, json ---------------------------------------------------------------------------


def corrupt(folder: Path, change) -> None:
    raw = (folder / "summary.json").read_bytes()
    (folder / "summary.json").write_bytes(change(raw))


def reversed_keys(raw: bytes) -> bytes:
    document = json.loads(raw)
    return json.dumps(dict(reversed(list(document.items()))), separators=(",", ":")).encode()


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.replace(b'"cell":', b'"cell": ', 1),
        lambda raw: raw + b"\n",
        lambda raw: b" " + raw,
        reversed_keys,
        lambda raw: raw[:1] + b'"format":"v4-summary-1",' + raw[1:],
        lambda raw: raw.replace(b'"liquidations":0', b'"liquidations":0.0', 1),
        lambda raw: raw.replace(b'"stop_ms":null', b'"stop_ms":NaN', 1),
        lambda raw: raw.replace(b'"reason":null', b'"reason":"\xc3\xa9"', 1),
        lambda raw: raw.replace(b'"outcome":"complete"', b'"outcome":"\\u0063omplete"', 1),
        lambda raw: b"\xff" + raw,
        lambda raw: b"[]",
        lambda raw: b"",
    ],
    ids=[
        "a space",
        "a newline",
        "a leading space",
        "keys out of order",
        "a duplicate key",
        "a float",
        "NaN",
        "raw non-ASCII",
        "an escaped letter",
        "bad UTF-8",
        "an array",
        "empty",
    ],
)
def test_refuses_non_canonical_bytes(change, tmp_path):
    """The same document with a space added, a newline, another key order, a duplicate key, a
    float, NaN, a spelling the canonical form does not use or bytes that are not JSON objects."""
    folder, expected = put(tmp_path)
    corrupt(folder, change)
    assert step_of(folder, expected) == "json"


def test_refuses_a_missing_summary_file(tmp_path):
    folder, expected = put(tmp_path)
    (folder / "summary.json").unlink()
    assert step_of(folder, expected) == "json"


def test_refuses_a_summary_too_large_to_be_one(tmp_path, monkeypatch):
    folder, expected = put(tmp_path)
    monkeypatch.setattr(inputs, "MAX_SUMMARY_BYTES", 1000)
    assert step_of(folder, expected) == "json"


# ---- step 4, format ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cell_id", "wrong"),
    [
        (CELL, "v4-summary-v3-1"),
        (CELL, "v4-summary-2"),
        (V3_CELL, "v4-summary-1"),
        (V3_CELL, None),
    ],
)
def test_refuses_the_format_of_another_arm(cell_id, wrong, tmp_path):
    folder, expected = put(tmp_path, cell_id)
    edit_summary(folder, format=DROP if wrong is None else wrong)
    assert step_of(folder, expected) == "format"


# ---- step 5, cell ---------------------------------------------------------------------------


def test_refuses_another_cells_summary(tmp_path):
    """A ``hold_universe-1000-1x`` summary in ``v4-summary-hold_universe-10000-1x-attempt-1``."""
    folder, expected = put(tmp_path, SMALL)
    moved = folder.rename(tmp_path / "v4-summary-hold_universe-10000-1x-attempt-1")
    assert step_of(moved, expected) == "cell"


@pytest.mark.parametrize(
    "cell",
    [
        None,
        [],
        {"id": CELL},
        {"id": CELL, "arm": "v4_main", "capital": 10000, "cost_multiple": 1, "extra": 1},
        {"id": CELL, "arm": "v4_main", "capital": True, "cost_multiple": 1},
        {"id": CELL, "arm": "v4_main", "capital": 5000, "cost_multiple": 1},
        {"id": CELL, "arm": "v5_main", "capital": 10000, "cost_multiple": 1},
        {"id": "v4_main-10000-2x", "arm": "v4_main", "capital": 10000, "cost_multiple": 1},
        {"id": CELL, "arm": ["v4_main"], "capital": 10000, "cost_multiple": 1},
    ],
)
def test_refuses_a_cell_record_that_is_not_the_folders(cell, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, cell=cell)
    assert step_of(folder, expected) == "cell"


def test_refuses_a_cell_that_the_expected_file_does_not_list(tmp_path):
    expected = expected_for([c for c in expected_for().cells if c != CELL])
    folder, _ = put(tmp_path, expected=expected)
    assert step_of(folder, expected) == "cell"


def test_a_v3_cell_is_not_expected_in_timing_mode(tmp_path):
    expected = expected_for(mode="timing")
    folder, _ = put(tmp_path, V3_CELL, expected=expected_for())
    assert step_of(folder, expected) == "cell"


# ---- step 6, window -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "window",
    [
        None,
        {},
        {"start_ms": START_MS},
        {"start_ms": START_MS + 3600000, "end_ms": START_MS + 49 * 3600000},
        {"start_ms": START_MS, "end_ms": START_MS + 50 * 3600000},
        {"start_ms": True, "end_ms": START_MS + 49 * 3600000},
        {"start_ms": START_MS, "end_ms": START_MS + 49 * 3600000, "more": 1},
    ],
)
def test_refuses_a_window_other_than_the_expected(window, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, window=window)
    assert step_of(folder, expected) == "window"


def test_a_window_is_compared_with_exact_types(tmp_path):
    """``False`` is not 0: a window that equals the expected one only as Python compares
    booleans and integers is refused."""
    expected = expected_for(window={"start_ms": 0, "end_ms": 3600000})
    folder, _ = put(tmp_path, expected=expected)
    assert read_cell(folder, expected).cell_id == CELL
    edit_summary(folder, window={"start_ms": False, "end_ms": 3600000})
    assert step_of(folder, expected) == "window"


def test_a_v3_cell_carries_v3s_window_and_a_v4_cell_does_not(tmp_path):
    folder, expected = put(tmp_path / "a", V3_CELL)
    edit_summary(folder, window=dict(expected.window))
    assert step_of(folder, expected) == "window"

    folder, expected = put(tmp_path / "b")
    edit_summary(folder, window=v3_as_built.v3_window())
    assert step_of(folder, expected) == "window"


# ---- step 7, data ---------------------------------------------------------------------------


@pytest.mark.parametrize("pin", sorted(DATA))
def test_refuses_other_data_pins(pin, tmp_path):
    """One pin changed in ``expected.data``."""
    folder, expected = put(tmp_path)
    other = replace(
        expected, data={**expected.data, pin: "2025-04" if pin == "end_month" else "f" * 64}
    )
    assert step_of(folder, other) == "data"


@pytest.mark.parametrize("data", [None, {}, {"config_sha256": DATA["config_sha256"]}, "pins"])
def test_refuses_data_that_is_not_the_four_pins(data, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, data=data)
    assert step_of(folder, expected) == "data"


def test_refuses_a_v3_summary_with_another_picks_pin(tmp_path):
    folder, expected = put(tmp_path, V3_CELL)
    assert read_cell(folder, expected).arm == "v3_as_built"
    assert step_of(folder, replace(expected, picks_sha256="e" * 64)) == "data"
    assert step_of(folder, replace(expected, v3_pack_sha256="e" * 64)) == "data"


def test_a_v3_cell_carries_its_two_pins_and_a_v4_cell_the_four(tmp_path):
    folder, expected = put(tmp_path / "a", V3_CELL)
    edit_summary(folder, data=dict(DATA))
    assert step_of(folder, expected) == "data"

    folder, expected = put(tmp_path / "b")
    edit_summary(folder, data={"v3_pack_sha256": V3_PACK, "picks_sha256": PICKS})
    assert step_of(folder, expected) == "data"


# ---- step 8, keys ---------------------------------------------------------------------------

# A missing field of the first four is refused by the step that reads it, before ``keys``.
EARLIER = {"format": "format", "cell": "cell", "window": "window", "data": "data"}


@pytest.mark.parametrize("key", sorted(FULL_KEYS))
def test_refuses_a_missing_key(key, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, **{key: DROP})
    assert step_of(folder, expected) == EARLIER.get(key, "keys")


def test_refuses_a_missing_and_an_extra_key(tmp_path):
    folder, expected = put(tmp_path / "missing")
    edit_summary(folder, final_equity=DROP)
    assert step_of(folder, expected) == "keys"
    folder, expected = put(tmp_path / "extra")
    edit_summary(folder, extra=1)
    assert step_of(folder, expected) == "keys"


@pytest.mark.parametrize("key", ["extra", "disclosures", "type", "x8675309"])
def test_refuses_an_extra_key(key, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, **{key: []})
    assert step_of(folder, expected) == "keys"


def test_a_v3_cell_has_disclosures_and_a_v4_cell_does_not(tmp_path):
    folder, expected = put(tmp_path / "a", V3_CELL)
    edit_summary(folder, disclosures=DROP)
    assert step_of(folder, expected) == "keys"
    folder, expected = put(tmp_path / "b")
    edit_summary(folder, disclosures=[])
    assert step_of(folder, expected) == "keys"


@pytest.mark.parametrize(
    ("outcome", "keys"),
    [
        ("engine_error", FAILURE_KEYS["engine_error"]),
        ("accounting_failure", FAILURE_KEYS["accounting_failure"]),
    ],
)
def test_a_failure_summary_has_its_outcomes_keys_only(outcome, keys, tmp_path):
    folder, expected = put(tmp_path, outcome=outcome)
    assert set(load_summary(folder)) == keys
    read_cell(folder, expected)
    edit_summary(folder, final_equity="1")
    assert step_of(folder, expected) == "keys"
    folder, expected = put(tmp_path / "again", outcome=outcome)
    missing = sorted(keys - {"format", "cell", "window", "data", "outcome"})[0]
    edit_summary(folder, **{missing: DROP})
    assert step_of(folder, expected) == "keys"


def test_failure_keys_are_the_documented_ones():
    head = {"format", "cell", "window", "data", "outcome"}
    assert FAILURE_KEYS["accounting_failure"] == head | {"identity", "hour_ms", "values"}
    assert FAILURE_KEYS["engine_error"] == head | {"type", "message", "hour_ms"}
    assert set(FAILURE_KEYS) == {"accounting_failure", "engine_error"}
    assert FULL_KEYS | {"disclosures"} == V3_FULL_KEYS


@pytest.mark.parametrize(
    "outcome",
    ["unknown", None, 1, "Complete", ["complete"], "accounting_failure", "limit_unrestorable"],
)
def test_refuses_an_outcome_the_arm_does_not_have(outcome, tmp_path):
    cell = V3_CELL if outcome in ("accounting_failure", "limit_unrestorable") else CELL
    folder, expected = put(tmp_path, cell)
    edit_summary(folder, outcome=outcome)
    assert step_of(folder, expected) == "keys"


@pytest.mark.parametrize("outcome", ["limit_unrestorable", "accounting_failure"])
def test_a_v3_cell_has_only_the_outcomes_v3_writes(outcome, tmp_path):
    """V3's arm writes ``complete``, ``liquidated`` and ``engine_error``: a v3 summary of the
    others is well formed for its outcome and still refused."""
    marks = marks_for(V3_CELL, 10)
    folder, expected = put(tmp_path, V3_CELL, outcome=outcome, marks=marks)
    assert step_of(folder, expected) == "keys"
    folder, expected = put(tmp_path / "v4", CELL, outcome=outcome, marks=marks_for(CELL, 10))
    assert read_cell(folder, expected).outcome == outcome


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("eras", None),
        ("eras", []),
        ("eras", [{}, {}, {}]),
        ("years", []),
        ("years", [1]),
        ("reason", 5),
        ("reason", ["ceiling"]),
    ],
)
def test_refuses_a_nested_field_of_the_wrong_shape(field, value, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, **{field: value})
    assert step_of(folder, expected) == "keys"


@pytest.mark.parametrize(
    ("outcome", "reason", "accepted"),
    [
        ("complete", None, True),
        ("complete", "ceiling", False),
        ("liquidated", None, True),
        ("liquidated", "stopped", False),
        ("limit_unrestorable", "margin_cushion", True),
        ("limit_unrestorable", "ceiling", True),
        ("limit_unrestorable", "required_fill", True),
        ("limit_unrestorable", None, False),
        ("limit_unrestorable", "stopped", False),
    ],
)
def test_a_reason_is_null_except_for_a_limit_stop_which_has_one_of_the_limits(
    outcome, reason, accepted, tmp_path
):
    marks = marks_for(CELL, 10) if outcome != "complete" else marks_for(CELL)
    folder, expected = put(tmp_path, outcome=outcome, marks=marks)
    edit_summary(folder, reason=reason)
    if accepted:
        assert read_cell(folder, expected).reason == reason
    else:
        assert step_of(folder, expected) == "keys"


def test_refuses_eras_that_are_not_the_formats(tmp_path):
    folder, expected = put(tmp_path)
    document = load_summary(folder)
    document["eras"][0]["name"] = "another"
    store_summary(folder, document)
    assert step_of(folder, expected) == "keys"
    document = load_summary(folder)
    document["eras"][0]["name"] = "start-2020"
    del document["eras"][1]["return"]
    store_summary(folder, document)
    assert step_of(folder, expected) == "keys"


def test_refuses_a_disclosures_list_of_the_wrong_shape(tmp_path):
    for number, value in enumerate(["none", [1], [""], None]):
        folder, expected = put(tmp_path / str(number), V3_CELL)
        edit_summary(folder, disclosures=value)
        assert step_of(folder, expected) == "keys"


@pytest.mark.parametrize(
    ("outcome", "field", "value"),
    [
        ("engine_error", "type", 5),
        ("engine_error", "message", None),
        ("accounting_failure", "identity", "cash"),
        ("accounting_failure", "identity", 5),
        ("accounting_failure", "values", None),
        ("accounting_failure", "values", {"wallet_residual": "0"}),
    ],
)
def test_refuses_a_failure_detail_of_the_wrong_shape(outcome, field, value, tmp_path):
    folder, expected = put(tmp_path, outcome=outcome)
    edit_summary(folder, **{field: value})
    assert step_of(folder, expected) == "keys"


# ---- step 9, numbers ------------------------------------------------------------------------

BAD_NUMBERS = [
    "NaN",
    "Infinity",
    "-Infinity",
    "sNaN",
    "1E+999999",
    "1E-999999",
    "0E+999999",
    "",
    " 1",
    "+1",
    "1_0",
    "1.",
    "١",  # an Arabic-Indic digit, which Decimal reads as 1
    "abc",
    5,
    True,
    [],
]
PLACES = [
    ("final_equity",),
    ("initial_equity",),
    ("compounded_return",),
    ("max_drawdown",),
    ("accounting_residual",),
    ("equity_2025",),
    ("final_after_close",),
    ("open_marks", 3, 1),
    ("open_marks", 49, 1),
    ("eras", 0, "start_equity"),
    ("eras", 0, "end_equity"),
    ("eras", 0, "return"),
    ("years", 0, "start_equity"),
]


def assign(document, place, value):
    target = document
    for step in place[:-1]:
        target = target[step]
    target[place[-1]] = value


@pytest.mark.parametrize("place", PLACES, ids=lambda place: ".".join(map(str, place)))
@pytest.mark.parametrize("value", BAD_NUMBERS, ids=lambda value: repr(value))
def test_refuses_non_finite_numbers(place, value, tmp_path):
    """``"NaN"``, ``"Infinity"`` and ``"1E+999999"`` among others, in every number of a summary."""
    folder, expected = put(tmp_path)
    document = load_summary(folder)
    assign(document, place, value)
    store_summary(folder, document)
    assert step_of(folder, expected) == "numbers"


@pytest.mark.parametrize("value", ["1E-40", "-0", "0", "1E+27", "123.456000", "-5"])
def test_accepts_the_spellings_the_engine_writes(value, tmp_path):
    """Residuals are written as ``1E-40``: an exponent is not what is refused, a huge one is."""
    folder, expected = put(tmp_path)
    edit_summary(folder, accounting_residual=value)
    assert read_cell(folder, expected).cell_id == CELL


@pytest.mark.parametrize("place", [("equity_2025",), ("final_after_close",), ("eras", 2, "return")])
def test_a_null_is_accepted_where_the_format_allows_one(place, tmp_path):
    folder, expected = put(tmp_path)
    document = load_summary(folder)
    assign(document, place, None)
    store_summary(folder, document)
    assert read_cell(folder, expected).cell_id == CELL


@pytest.mark.parametrize("place", [("final_equity",), ("initial_equity",), ("max_drawdown",)])
def test_a_null_is_refused_where_the_format_gives_a_number(place, tmp_path):
    folder, expected = put(tmp_path)
    document = load_summary(folder)
    assign(document, place, None)
    store_summary(folder, document)
    assert step_of(folder, expected) == "numbers"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stop_ms", -1),
        ("stop_ms", True),
        ("stop_ms", "5"),
        ("liquidations", True),
        ("liquidations", "0"),
        ("liquidations", -1),
        ("initial_equity", "10001"),
        ("initial_equity", "9999.99"),
    ],
)
def test_refuses_an_integer_that_is_not_one_and_an_initial_equity_that_is_not_the_capital(
    field, value, tmp_path
):
    folder, expected = put(tmp_path)
    edit_summary(folder, **{field: value})
    assert step_of(folder, expected) == "numbers"


@pytest.mark.parametrize(
    ("place", "value"),
    [
        (("eras", 0, "start_ms"), -1),
        (("eras", 0, "end_ms"), "5"),
        (("eras", 0, "start_ms"), True),
        (("years", 0, "year"), "2021"),
        (("years", 0, "year"), None),
    ],
)
def test_refuses_a_period_integer_that_is_not_one(place, value, tmp_path):
    folder, expected = put(tmp_path)
    document = load_summary(folder)
    assign(document, place, value)
    store_summary(folder, document)
    assert step_of(folder, expected) == "numbers"


@pytest.mark.parametrize(
    "place",
    [
        ("values", "wallet_residual"),
        ("values", "equity_residual"),
        ("values", "quantity_residuals", 0, 2),
    ],
)
@pytest.mark.parametrize("value", ["NaN", "1E+999999", 5, None])
def test_refuses_a_non_finite_residual_in_an_accounting_failure(place, value, tmp_path):
    folder, expected = put(tmp_path, outcome="accounting_failure")
    document = load_summary(folder)
    document["values"]["quantity_residuals"] = [["spot", "BTCUSDT", "0"]]
    assign(document, place, value)
    store_summary(folder, document)
    assert step_of(folder, expected) == "numbers"


@pytest.mark.parametrize("hour", ["5", -1, True, None])
def test_refuses_a_failures_hour_that_is_not_one(hour, tmp_path):
    folder, expected = put(tmp_path, outcome="accounting_failure")
    edit_summary(folder, hour_ms=hour)
    assert step_of(folder, expected) == "numbers"


def test_an_engine_error_has_an_hour_or_none(tmp_path):
    folder, expected = put(tmp_path / "a", outcome="engine_error")
    assert load_summary(folder)["hour_ms"] is None
    assert read_cell(folder, expected).outcome == "engine_error"
    folder, expected = put(tmp_path / "b", outcome="engine_error")
    edit_summary(folder, hour_ms=START_MS)
    assert read_cell(folder, expected).outcome == "engine_error"


# ---- step 10, marks -------------------------------------------------------------------------


def with_marks(folder: Path, marks) -> None:
    edit_summary(folder, open_marks=marks)


def test_refuses_marks_out_of_order_and_a_first_mark_not_the_capital(tmp_path):
    """Out of order, repeated, and a first mark that is not the capital, each at step marks."""
    expected = expected_for()
    rows = [list(row) for row in marks_for(CELL, 6)]
    swapped = [rows[0], rows[2], rows[1], *rows[3:]]
    repeated = [rows[0], rows[1], rows[1], *rows[3:]]
    reversed_rows = list(reversed(rows))
    first_off = [[rows[0][0], "10001", True], *rows[1:]]
    for number, marks in enumerate([swapped, repeated, reversed_rows, first_off]):
        folder, _ = put(tmp_path / str(number))
        with_marks(folder, marks)
        assert step_of(folder, expected) == "marks"


@pytest.mark.parametrize(
    "marks",
    [
        [],
        {},
        "marks",
        None,
        [[START_MS, "10000"]],
        [[START_MS, "10000", True, 1]],
        [[START_MS, "10000", 1]],
        [[START_MS, "10000", None]],
        [[str(START_MS), "10000", True]],
        [[True, "10000", True]],
        [[START_MS, "10000", True], 5],
        [{"hour": START_MS}],
    ],
    ids=lambda marks: repr(marks)[:40],
)
def test_refuses_an_open_mark_that_is_not_an_int_a_decimal_and_a_flag(marks, tmp_path):
    folder, expected = put(tmp_path)
    with_marks(folder, marks)
    assert step_of(folder, expected) == "marks"


def test_a_first_mark_equal_to_the_capital_by_value_is_the_capital(tmp_path):
    folder, expected = put(tmp_path)
    rows = [list(row) for row in marks_for(CELL, 4)]
    rows[0][1] = "10000.00"
    with_marks(folder, rows)
    assert read_cell(folder, expected).marks == 4


def test_the_first_mark_is_the_cells_own_capital(tmp_path):
    folder, expected = put(tmp_path, SMALL)
    rows = [list(row) for row in marks_for(CELL, 4)]  # 10000, but the cell's is 1000
    with_marks(folder, rows)
    assert step_of(folder, expected) == "marks"


def test_a_failure_summary_has_no_marks_to_check(tmp_path):
    folder, expected = put(tmp_path, outcome="engine_error")
    assert read_cell(folder, expected).marks == 0


# ---- step 11, receipt -----------------------------------------------------------------------


def test_refuses_a_receipt_with_another_digest(tmp_path):
    """The summary names a digest that is not the receipt's, and a receipt replaced by another."""
    folder, expected = put(tmp_path / "a")
    edit_summary(folder, receipt_sha256="0" * 64)
    assert step_of(folder, expected) == "receipt"

    folder, expected = put(tmp_path / "b")
    other, _ = put(tmp_path / "c", SMALL)
    shutil.copyfile(other / "receipt.json", folder / "receipt.json")
    assert step_of(folder, expected) == "receipt"


@pytest.mark.parametrize("value", [None, 5, "", "A" * 64, ["0" * 64]])
def test_refuses_a_receipt_digest_that_is_not_a_digest(value, tmp_path):
    folder, expected = put(tmp_path)
    edit_summary(folder, receipt_sha256=value)
    assert step_of(folder, expected) == "receipt"


@pytest.mark.parametrize(
    "spoil",
    [
        lambda path: path.unlink(),
        lambda path: path.write_bytes(path.read_bytes() + b"\n"),
        lambda path: path.write_bytes(b"{}"),
        lambda path: path.write_bytes(b""),
    ],
    ids=["missing", "not canonical", "not a receipt", "empty"],
)
def test_refuses_a_missing_or_malformed_receipt(spoil, tmp_path):
    folder, expected = put(tmp_path)
    spoil(folder / "receipt.json")
    assert step_of(folder, expected) == "receipt"


@pytest.mark.parametrize("outcome", ["engine_error", "accounting_failure"])
def test_accepts_failure_summaries_without_a_receipt_check(outcome, tmp_path):
    """An ``engine_error`` and an ``accounting_failure`` summary are accepted with no receipt,
    with a malformed one and with a good one, and have no marks."""
    for number, spoil in enumerate(
        [
            lambda path: path.unlink(),
            lambda path: path.write_bytes(b"not a receipt"),
            lambda path: None,
        ]
    ):
        folder, expected = put(tmp_path / str(number), outcome=outcome)
        spoil(folder / "receipt.json")
        facts = read_cell(folder, expected)
        assert (facts.outcome, facts.marks) == (outcome, 0)
        assert facts.final_equity is None and facts.final_after_close is None
        assert facts.equity_2025 is None
        assert facts.compounded_return is None and facts.max_drawdown is None
        assert facts.initial_equity == Decimal(10000)
        assert facts.eras == () and facts.years == () and facts.stop_ms is None


def test_a_failure_summarys_reason_is_its_type_or_its_identity(tmp_path):
    folder, expected = put(tmp_path / "a", outcome="engine_error")
    assert read_cell(folder, expected).reason == "RuntimeError"
    folder, expected = put(tmp_path / "b", outcome="accounting_failure")
    assert read_cell(folder, expected).reason == "wallet"
    folder, expected = put(tmp_path / "c", V3_CELL, outcome="engine_error")
    facts = read_cell(folder, expected)
    assert (facts.arm, facts.outcome, facts.reason) == ("v3_as_built", "engine_error", "V3Stop")


def test_a_v3_liquidation_is_accepted_with_its_stop(tmp_path):
    marks = marks_for(V3_CELL, 12)
    folder, expected = put(tmp_path, V3_CELL, outcome="liquidated", marks=marks)
    facts = read_cell(folder, expected)
    assert (facts.outcome, facts.stop_ms, facts.marks) == ("liquidated", marks[-1][0], 12)
    assert facts.disclosures == (v3_as_built.V3_CAPITAL_ADAPTER,)


# ---- the order of the steps, and what a reason never holds ----------------------------------


def test_the_steps_are_applied_in_order(tmp_path):
    """A summary wrong at every step is refused at the first; mend that one and the next one
    refuses, down to the receipt, then the whole is accepted. The folder of a re-run is refused
    before anything in it is read."""
    folder, expected = put(tmp_path)
    good = load_summary(folder)
    other = load_summary(put(tmp_path / "other", SMALL)[0])["cell"]
    wrong = {
        "format": "x",
        "cell": other,
        "window": None,
        "data": None,
        "extra": 1,
        "final_equity": "NaN",
        "open_marks": [],
        "receipt_sha256": "0" * 64,
    }
    document = {**good, **wrong}
    store_summary(folder, document)
    (folder / "summary.json").write_bytes((folder / "summary.json").read_bytes() + b" ")
    assert step_of(folder, expected) == "json"

    store_summary(folder, document)
    for step, name in [
        ("format", "format"),
        ("cell", "cell"),
        ("window", "window"),
        ("data", "data"),
        ("keys", "extra"),
        ("numbers", "final_equity"),
        ("marks", "open_marks"),
        ("receipt", "receipt_sha256"),
    ]:
        assert step_of(folder, expected) == step
        if name == "extra":
            del document[name]
        else:
            document[name] = good[name]
        store_summary(folder, document)
    assert read_cell(folder, expected).cell_id == CELL

    again = folder.rename(tmp_path / f"v4-summary-{CELL}-attempt-2")
    (again / "summary.json").write_bytes(b"not json at all")
    assert step_of(again, expected) == "rerun"


SECRET = "8675309.42"


def test_a_refusal_never_quotes_a_value_of_the_file(tmp_path):
    """Public logs carry no prices or equities: every reason names what was wrong in words. Each
    spoilt file below holds a value (a number, a pin, a key, a name) that must not come back."""
    expected = expected_for()
    cases = []
    for number, (field, value) in enumerate(
        [
            ("final_equity", SECRET + "x"),
            ("compounded_return", "NaN" + SECRET.replace(".", "")),
            ("initial_equity", SECRET),
            ("reason", SECRET),
            ("stop_ms", SECRET),
            ("window", {"start_ms": 8675309, "end_ms": 8675309}),
            ("data", {"config_sha256": SECRET}),
            ("cell", {"id": SECRET, "arm": SECRET, "capital": 1, "cost_multiple": 1}),
            ("format", SECRET),
            ("outcome", SECRET),
            ("receipt_sha256", SECRET),
            ("x" + SECRET.replace(".", ""), 1),
            ("eras", [{"name": SECRET}]),
            ("open_marks", [[START_MS, SECRET, True]]),
            ("open_marks", [[START_MS, "10000", True], [START_MS, SECRET, True]]),
        ]
    ):
        folder, _ = put(tmp_path / str(number))
        edit_summary(folder, **{field: value})
        cases.append(folder)
    for folder in cases:
        reason = refusal(folder, expected).reason
        assert "8675309" not in reason, reason
        assert "NaN" not in reason, reason
    other = replace(expected, data={**expected.data, "daily_sha256": "f" * 64})
    folder, _ = put(tmp_path / "pins")
    assert DATA["config_sha256"] not in refusal(folder, other).reason
    assert "f" * 64 not in refusal(folder, other).reason


def test_a_refusal_carries_its_step_and_its_reason():
    refused = CellRefused("keys", "a key is missing")
    assert (refused.step, refused.reason) == ("keys", "a key is missing")
    assert isinstance(refused, ValueError) and "keys" in str(refused)


# ---- facts and their record -----------------------------------------------------------------


def each_kind_of_facts(root: Path) -> list[CellFacts]:
    expected = expected_for()
    found = []
    for number, (cell, outcome) in enumerate(
        [
            (CELL, "complete"),
            (SMALL, "liquidated"),
            (CELL, "limit_unrestorable"),
            ("v4_main-10000-2x", "engine_error"),
            ("hold_universe-10000-1x", "accounting_failure"),
            (V3_CELL, "complete"),
            ("v3_as_built-10000-1x", "engine_error"),
        ]
    ):
        folder, _ = put(root / str(number), cell, expected=expected, outcome=outcome)
        found.append(read_cell(folder, expected))
    return found


def test_facts_round_trip(tmp_path):
    """``facts_from_record(facts_record(f)) == f`` for every kind of cell, through the canonical
    JSON a progress file holds."""
    kinds = each_kind_of_facts(tmp_path)
    assert {fact.outcome for fact in kinds} == {
        "complete",
        "liquidated",
        "limit_unrestorable",
        "engine_error",
        "accounting_failure",
    }
    for facts in kinds:
        record = facts_record(facts)
        raw = _canonical(record)  # JSON-ready: strings, ints, booleans, null, lists, objects
        assert facts_from_record(json.loads(raw)) == facts
        assert facts_from_record(record) == facts
        for key in ("initial_equity", "final_equity", "max_drawdown"):
            assert record[key] is None or isinstance(record[key], str)


def test_facts_record_spells_decimals_as_strings_and_names_every_field(tmp_path):
    facts = each_kind_of_facts(tmp_path)[0]
    record = facts_record(facts)
    assert record["initial_equity"] == "10000"
    assert record["final_equity"] == str(facts.final_equity)
    assert record["capital"] == 10000 and record["marks"] == 50
    assert set(record) == {
        "folder",
        "cell_id",
        "arm",
        "capital",
        "cost_multiple",
        "outcome",
        "reason",
        "stop_ms",
        "initial_equity",
        "final_equity",
        "equity_2025",
        "final_after_close",
        "compounded_return",
        "max_drawdown",
        "eras",
        "years",
        "disclosures",
        "summary_sha256",
        "marks",
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda record: record.pop("marks"),
        lambda record: record.update(extra=1),
        lambda record: record.update(initial_equity="NaN"),
        lambda record: record.update(initial_equity=10000),
        lambda record: record.update(final_equity="1E+999999"),
        lambda record: record.update(capital="10000"),
        lambda record: record.update(capital=5000),
        lambda record: record.update(marks=True),
        lambda record: record.update(marks=-1),
        lambda record: record.update(eras="none"),
        lambda record: record.update(years=[1]),
        lambda record: record.update(disclosures="adapter"),
        lambda record: record.update(summary_sha256="x"),
        lambda record: record.update(cell_id="v4_main-1000-1x"),
        lambda record: record.update(folder="elsewhere"),
        lambda record: record.update(outcome=None),
        lambda record: record.update(stop_ms="1"),
    ],
)
def test_facts_from_record_refuses_a_malformed_record(change, tmp_path):
    record = facts_record(each_kind_of_facts(tmp_path)[0])
    change(record)
    with pytest.raises(ValueError):
        facts_from_record(record)


# ---- the expected file ----------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_read_expected_reads_what_it_is_given(mode, tmp_path):
    expected = expected_for(mode=mode)
    path = write_expected(tmp_path / "expected.json", expected)

    got = read_expected(path)

    assert got == expected
    assert got.mode == mode
    assert len(got.cells) == (44 if mode == "timing" else 48)
    assert got.cells == tuple(
        c.cell_id for c in all_cells() if mode != "timing" or c.arm != "v3_as_built"
    )
    assert (got.v3_pack_sha256 is None) == (mode == "timing")
    assert expected_record(expected)["format"] == EXPECTED_FORMAT
    assert set(expected_record(expected)) == {
        "format",
        "mode",
        "cells",
        "window",
        "data",
        "v3_pack_sha256",
        "picks_sha256",
    }


def rewrite(path: Path, change) -> Path:
    document = json.loads(path.read_bytes())
    change(document)
    path.write_bytes(_canonical(document))
    return path


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(mode="live"),
        lambda d: d.update(mode="Rehearsal"),
        lambda d: d.update(mode=None),
        lambda d: d.update(extra=1),
        lambda d: d.pop("window"),
        lambda d: d.pop("picks_sha256"),
        lambda d: d.update(format="v4-verdict-expected-2"),
        lambda d: d.update(cells=d["cells"][:-1]),
        lambda d: d.update(cells=list(reversed(d["cells"]))),
        lambda d: d.update(cells=[*d["cells"], "v4_main-10000-1x"]),
        lambda d: d.update(cells="all"),
        lambda d: d.update(window={"start_ms": 1}),
        lambda d: d.update(window={"start_ms": 7, "end_ms": 3600000}),
        lambda d: d.update(window={"start_ms": 7200000, "end_ms": 3600000}),
        lambda d: d.update(window={"start_ms": True, "end_ms": 3600000}),
        lambda d: d.update(window={"start_ms": 0, "end_ms": 3600000, "more": 1}),
        lambda d: d.update(data=None),
        lambda d: d.update(data={}),
        lambda d: d["data"].update(extra="x"),
        lambda d: d["data"].update(index_sha256="XYZ"),
        lambda d: d["data"].update(daily_sha256=5),
        lambda d: d["data"].update(end_month="2025-3"),
        lambda d: d["data"].update(config_sha256=""),
        lambda d: d.update(v3_pack_sha256=None),
        lambda d: d.update(picks_sha256=None),
        lambda d: d.update(picks_sha256="nothex"),
        lambda d: d.update(v3_pack_sha256=5),
    ],
)
def test_read_expected_refuses_unknown_mode_and_extra_keys(change, tmp_path):
    """An unknown mode, an extra or a missing key, and the other ways a file is not the format."""
    path = write_expected(tmp_path / "expected.json", expected_for())
    rewrite(path, change)
    with pytest.raises(ValueError):
        read_expected(path)


def test_read_expected_in_timing_mode_has_no_v3_cells_and_no_v3_pins(tmp_path):
    path = write_expected(tmp_path / "expected.json", expected_for(mode="timing"))
    rewrite(path, lambda d: d.update(cells=expected_record(expected_for())["cells"]))
    with pytest.raises(ValueError):
        read_expected(path)
    path = write_expected(tmp_path / "again.json", expected_for(mode="timing"))
    rewrite(path, lambda d: d.update(v3_pack_sha256=V3_PACK, picks_sha256=PICKS))
    with pytest.raises(ValueError):
        read_expected(path)


@pytest.mark.parametrize(
    "mangle",
    [
        lambda raw: raw + b"\n",
        lambda raw: raw.replace(b'"mode":', b'"mode": ', 1),
        lambda raw: raw[:1] + b'"mode":"timing",' + raw[1:],
        lambda raw: raw.replace(b'"start_ms":', b'"start_ms":1.0e0,"x":', 1),
        lambda raw: b"\xff" + raw,
        lambda raw: b"[]",
        lambda raw: b"",
    ],
    ids=["newline", "a space", "a duplicate key", "a float", "bad UTF-8", "an array", "empty"],
)
def test_read_expected_refuses_bytes_that_are_not_canonical_json(mangle, tmp_path):
    path = write_expected(tmp_path / "expected.json", expected_for())
    path.write_bytes(mangle(path.read_bytes()))
    with pytest.raises(ValueError):
        read_expected(path)


def test_read_expected_refuses_a_missing_file_and_a_huge_one(tmp_path, monkeypatch):
    with pytest.raises(ValueError):
        read_expected(tmp_path / "missing.json")
    path = write_expected(tmp_path / "expected.json", expected_for())
    monkeypatch.setattr(inputs, "MAX_EXPECTED_BYTES", 100)
    with pytest.raises(ValueError):
        read_expected(path)


# ---- the fixtures' own sets are valid -------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_every_cell_of_the_standard_sets_is_accepted(mode, tmp_path):
    """The fixtures that tasks 4 and 7 build on write what ``read_cell`` accepts: 48 cells (44
    for timing), each with its own facts, and the standard paths have the shape the fixtures
    claim."""
    expected = full_set(tmp_path, hours=50, mode=mode)
    folders = sorted(tmp_path.iterdir())
    assert len(folders) == len(expected.cells) == (44 if mode == "timing" else 48)
    facts = {read_cell(folder, expected).cell_id: read_cell(folder, expected) for folder in folders}
    assert list(facts) == sorted(expected.cells)
    assert all(item.outcome == "complete" and item.marks == 50 for item in facts.values())
    main = facts["v4_main-10000-1x"]
    hold = facts["hold_universe-10000-1x"]
    assert main.max_drawdown == 0 and main.compounded_return > hold.compounded_return > 0
    assert hold.max_drawdown > 0
    assert facts["v4_main-10000-2x"].final_equity < main.final_equity
    assert main.equity_2025 < main.final_after_close
    assert all(
        item.final_after_close is None for item in facts.values() if item.arm == "v3_as_built"
    )
    assert spec_of(CELL).cell_id == CELL
    if mode != "timing":
        assert facts["v3_as_built-1000-1x"].disclosures == (v3_as_built.V3_CAPITAL_ADAPTER,)
        assert facts["v3_as_built-10000-1x"].disclosures == ()


def test_full_set_overrides_and_omissions(tmp_path):
    expected = full_set(
        tmp_path,
        hours=20,
        overrides={
            "v4_main-1000-1x": {"outcome": "liquidated", "final_after_close": None},
            "hold_universe-10000-1x": {"outcome": "engine_error"},
        },
        omit={"hold_universe-1000-1x"},
    )
    assert not (tmp_path / "v4-summary-hold_universe-1000-1x-attempt-1").exists()
    assert len(list(tmp_path.iterdir())) == 47
    liquidated = read_cell(tmp_path / "v4-summary-v4_main-1000-1x-attempt-1", expected)
    assert (liquidated.outcome, liquidated.marks) == ("liquidated", 20)
    errored = read_cell(tmp_path / "v4-summary-hold_universe-10000-1x-attempt-1", expected)
    assert (errored.outcome, errored.marks) == ("engine_error", 0)
