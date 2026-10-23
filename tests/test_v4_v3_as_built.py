"""V4 step 4a, task 6: ``v3_as_built``, its picks and its cells (``v4.engine.v3_as_built`` and
``scripts/v4_v3_cell.py``), on V3.1's synthetic V3 inputs, never market data.

The world is ``tests/test_combined_baseline_v3.py``'s: BTCUSDT and ETHUSDT, daily bars from
2019-01-01 and 72 hourly bars from 2020-05-01 00:00 UTC, written to a V3 pack with
``write_v3_pack`` and read back through ``read_v3_pack`` and its pin. Two things are patched in
every test, and nothing else of V3:

* the window: ruling R3's runs from 2021-07-01 to V3's terminal mark at 2025-01-01, where the
  synthetic world has no bars, so ``V3_START_MS`` and ``V3_END_MS`` are set to the world's 72
  hours (the autouse fixture ``window``);
* the training: V3's real walk-forward needs quarters of history the world does not have, and is
  slow (2 h 32 min on V3's data), so ``run_walk_forward`` follows V3.1's ``fake_walk_forward``
  pattern (``train``): it returns fixed picks and notes the starting capital its runners get.

The cells run V3's frozen replay unchanged, through ``replay_v3_baseline``; a test that needs a
V3 stop makes it as V3.1's own tests do (a price spike for a real liquidation, a patched
``execute_hour`` for the untradable stops). The network is not used: nothing here opens a socket.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal as D
from decimal import localcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_combined_baseline_v3 import DAY, END, HOUR, PIN, START, SYMBOLS, _daily, inputs

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.combined.baseline_records import BaselineEvidence
from crypto_grid_bot.combined.baseline_v3 import SELECTOR, replay_v3_baseline
from crypto_grid_bot.combined.driver.v3_pack import V3PackFields, read_v3_pack, write_v3_pack
from crypto_grid_bot.trend import replay as v3_replay
from crypto_grid_bot.trend import runner as v3_runner
from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.v4.engine import v3_as_built
from crypto_grid_bot.v4.engine.arms import CellSpec
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.records import Receipt, RecordWriter, read_receipt, read_records
from crypto_grid_bot.v4.engine.records import write_receipt as write_receipt_file
from crypto_grid_bot.v4.engine.v3_as_built import (
    ACCOUNTING_FLAGS,
    PICKS_FILE,
    V3_SUMMARY_FORMAT,
    build_v3_summary,
    read_v3_picks,
    render_v3_page,
    run_v3_cell,
    run_v3_picks,
    verify_v3_summary,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_v3_cell  # noqa: E402

ARM = "v3_as_built"
REAL_WINDOW = (v3_as_built.V3_START_MS, v3_as_built.V3_END_MS)  # before any fixture runs
RECORDS = "records.jsonl"
RECEIPT = "receipt.json"
OUTPUT_FILES = (RECORDS, RECEIPT, "summary.json", "report.html")
OTHER_PIN = "0" * 64
ADAPTER = "v3_capital_adapter_sets_only_starting_capital"
# The keys of a full summary of summary.py (its module docstring).
FULL_KEYS = {
    "format",
    "cell",
    "window",
    "data",
    "outcome",
    "reason",
    "stop_ms",
    "initial_equity",
    "final_equity",
    "equity_2025",
    "final_after_close",
    "max_drawdown",
    "compounded_return",
    "liquidations",
    "accounting_residual",
    "receipt_sha256",
    "eras",
    "years",
    "open_marks",
}
# A full v3 summary has them and one more: V3's own disclosures (the adapter's, at 1,000 USDT).
V3_FULL_KEYS = FULL_KEYS | {"disclosures"}


@pytest.fixture(autouse=True)
def window(monkeypatch: pytest.MonkeyPatch) -> None:
    """R3's window, moved onto the synthetic world's 72 hours (module docstring)."""
    monkeypatch.setattr(v3_as_built, "V3_START_MS", START)
    monkeypatch.setattr(v3_as_built, "V3_END_MS", END)


# ---- the world ----------------------------------------------------------------------------


def fields(hourly: Mapping[str, Sequence[Kline]] | None = None) -> V3PackFields:
    """V3.1's synthetic inputs as the fields of a V3 pack, with other hourly bars if given."""
    data = inputs()
    return V3PackFields(
        first_months={symbol: "2020-01" for symbol in SYMBOLS},
        spot_bars={symbol: _daily(symbol) for symbol in SYMBOLS},
        spot_exclusions={},
        futures_exclusions={},
        futures_filters=dict(data.filters),
        futures_hourly=dict(data.hourly if hourly is None else hourly),
        funding=dict(data.funding),
    )


def write_pack(
    folder: Path, hourly: Mapping[str, Sequence[Kline]] | None = None
) -> tuple[Path, str]:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "v3-input.pack.json.gz"
    return path, write_v3_pack(fields(hourly), path)


def train(
    monkeypatch: pytest.MonkeyPatch, rule: str = "R2L", picks: dict[int, str] | None = None
) -> list[D]:
    """V3.1's ``fake_walk_forward`` pattern: the frozen training returns ``{START: rule}`` (or
    ``picks``) and notes the starting capital of the runners it would replay with."""
    seen: list[D] = []

    def walk(
        decisions: object, filters: object, hourly: object, funding: object, *, record: object
    ):
        seen.append(vars(v3_replay)["TrendRunner"](filters).account.initial)
        return SimpleNamespace(picks=picks or {START: rule}, out_of_sample="oos")

    monkeypatch.setattr(baseline_v3, "run_walk_forward", walk)
    return seen


@dataclass(frozen=True)
class World:
    pack: Path
    pack_sha256: str
    picks: Path
    picks_sha256: str
    rule: str


def world(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rule: str = "R2L",
    hourly: Mapping[str, Sequence[Kline]] | None = None,
    picks: dict[int, str] | None = None,
) -> World:
    """A V3 pack, and its picks computed once with ``run_v3_picks``."""
    pack, pack_sha256 = write_pack(folder / "pack", hourly)
    train(monkeypatch, rule, picks)
    digest = run_v3_picks(pack, pack_sha256, folder / "picks")
    return World(pack, pack_sha256, folder / "picks" / PICKS_FILE, digest, rule)


def run_cell(
    w: World, capital: int = 10000, costs: int = 1, folder: Path | None = None
) -> tuple[Path, Receipt]:
    cell = CellSpec(ARM, capital, costs)
    out = folder if folder is not None else w.pack.parent.parent / "cells" / cell.cell_id
    return out, run_v3_cell(w.pack, w.pack_sha256, w.picks, w.picks_sha256, cell, out)


def rows(folder: Path, receipt: Receipt) -> list[tuple[str, dict[str, Any]]]:
    return list(read_records(folder / RECORDS, receipt))


def of_kind(found: list[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [record for name, record in found if name == kind]


def reference(w: World, *, initial: int = 10000, cost_multiple: int = 1) -> BaselineEvidence:
    """V3.1's own replay of the selector over the window, on the same pack and picks."""
    return replay_v3_baseline(
        SELECTOR,
        read_v3_pack(w.pack, w.pack_sha256),
        start_ms=START,
        end_ms=END,
        initial=D(initial),
        cost_multiple=cost_multiple,
        source_refs=("synthetic:v3",),
        adapter_pin=PIN,
        picks={START: w.rule},
    )


def open_marks(evidence: BaselineEvidence) -> list[tuple[int, str]]:
    return [(m.timestamp_ms, str(m.equity)) for m in evidence.native if m.kind == "open"]


def summary_of(folder: Path, receipt: Receipt, capital: int = 10000, costs: int = 1) -> dict:
    return build_v3_summary(CellSpec(ARM, capital, costs), folder / RECORDS, receipt)


def cell_json(capital: int = 10000, costs: int = 1) -> dict[str, object]:
    spec = CellSpec(ARM, capital, costs)
    return {"id": spec.cell_id, "arm": ARM, "capital": capital, "cost_multiple": costs}


def pins(w: World) -> dict[str, str]:
    return {"v3_pack_sha256": w.pack_sha256, "picks_sha256": w.picks_sha256}


def spiked(at: int, factor: int) -> dict[str, list[Kline]]:
    """The synthetic hourly bars with both coins' highs at ``at`` raised ``factor``-fold."""
    return {
        symbol: [replace(bar, high=bar.open * factor) if bar.open_ms == at else bar for bar in bars]
        for symbol, bars in inputs().hourly.items()
    }


# ---- the cells are V3's own replay ----------------------------------------------------------


def test_v3_window_constants_are_r3s():
    """R3: from V3's first out-of-sample quarter, 2021-07-01 00:00 UTC, to its terminal mark at
    2025-01-01 00:00 UTC (as imported, before the fixture moves them for the other tests). The
    adapter pin passed to V3.1's runner is V3.1's registered one for the selector."""
    start, end = REAL_WINDOW
    assert (start, end) == (1625097600000, 1735689600000)
    assert (start, end) == (month_bounds_ms("2021-07")[0], month_bounds_ms("2025-01")[0])
    assert (V3_SUMMARY_FORMAT, PICKS_FILE) == ("v4-summary-v3-1", "v3_picks.json")
    registration = Path(__file__).resolve().parents[1] / "config" / "v3_1_registration.json"
    registered = json.loads(registration.read_text("utf-8"))["adapter_pins"][SELECTOR]
    assert registered == v3_as_built.V3_ADAPTER_PIN


def test_v3_cell_at_10000_is_v3s_own_replay(tmp_path, monkeypatch):
    """At 10,000 USDT and base costs the cell is V3's replay: every hourly record is V3's ``open``
    native mark at the same stamp, one per hour of the window, and the final equity is V3's
    terminal mark at the window's end (no closing trade, so no equity after a close)."""
    w = world(tmp_path, monkeypatch)
    folder, receipt = run_cell(w)
    evidence = reference(w)
    found = rows(folder, receipt)
    hourly = of_kind(found, "hourly")

    assert [(r["open_ms"], r["open_equity"]) for r in hourly] == open_marks(evidence)
    assert [r["open_ms"] for r in hourly] == list(range(START, END, HOUR))
    assert all(set(r) == {"open_ms", "open_equity", "complete"} for r in hourly)
    assert all(r["complete"] is True for r in hourly)  # every coin has every bar
    terminal = evidence.native[-1]
    assert (terminal.kind, terminal.timestamp_ms) == ("terminal", END)
    assert of_kind(found, "event") == [
        {
            "type": "terminal",
            "hour_ms": END,
            "coin": None,
            "timestamp_ms": END,
            "equity": str(terminal.equity),
        }
    ]
    assert [name for name, _ in found][-1] == "outcome"

    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert set(summary) == V3_FULL_KEYS
    final = str(terminal.equity)
    assert final != "10000"  # R2L traded
    with localcontext(CONTEXT):
        change = str(terminal.equity / 10000 - 1)
    path = [D(equity) for _, equity in open_marks(evidence)] + [terminal.equity]
    assert ADAPTER not in summary["disclosures"]  # V3's own capital: no adapter
    assert {key: summary[key] for key in V3_FULL_KEYS - {"eras", "years", "open_marks"}} == {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_json(),
        "window": {"start_ms": START, "end_ms": END - HOUR},
        "data": pins(w),
        "outcome": "complete",
        "reason": None,
        "stop_ms": None,
        "initial_equity": "10000",
        "final_equity": final,
        "equity_2025": None,
        "final_after_close": None,
        "max_drawdown": str(maximum_drawdown(path)),
        "compounded_return": change,
        "liquidations": 0,
        "accounting_residual": str(abs(evidence.accounting_residual)),
        "receipt_sha256": hashlib.sha256((folder / RECEIPT).read_bytes()).hexdigest(),
        "disclosures": list(evidence.disclosures),
    }
    assert summary["open_marks"] == [[ms, equity, True] for ms, equity in open_marks(evidence)]
    # The world lies in the first era; the period ends at the terminal mark, the window's end.
    period = {
        "start_ms": START,
        "end_ms": END,
        "start_equity": "10000",
        "end_equity": final,
        "return": change,
    }
    unreached = dict.fromkeys(period)
    assert summary["eras"] == [
        {"name": "start-2020", **period},
        {"name": "2021-2024", **unreached},
        {"name": "2025-end", **unreached},
    ]
    assert summary["years"] == [{"year": 2020, **period}]


def test_v3_cell_at_1000_runs_through_the_capital_adapter_and_says_so(tmp_path, monkeypatch):
    """At 1,000 USDT the replay runs through ``v3_capital`` (inside ``replay_v3_baseline``): the
    first open mark is 1000, the marks are V3.1's own at that capital, the outcome record keeps
    V3's disclosure that the adapter sets only the starting capital, and the frozen runner is
    restored afterwards. The 10,000 cell has no such disclosure."""
    original = vars(v3_replay)["TrendRunner"]
    w = world(tmp_path, monkeypatch)
    folder, receipt = run_cell(w, capital=1000)
    evidence = reference(w, initial=1000)
    found = rows(folder, receipt)
    hourly = of_kind(found, "hourly")

    assert vars(v3_replay)["TrendRunner"] is original
    assert hourly[0]["open_equity"] == "1000"
    assert [(r["open_ms"], r["open_equity"]) for r in hourly] == open_marks(evidence)
    (outcome,) = of_kind(found, "outcome")
    assert ADAPTER in outcome["disclosures"]
    assert outcome["disclosures"] == list(evidence.disclosures)
    summary = summary_of(folder, receipt, capital=1000)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert summary["initial_equity"] == "1000"
    assert summary["final_equity"] == str(evidence.native[-1].equity)
    # M8: the summary, which the run summary reads alone, carries the adapter's disclosure.
    assert set(summary) == V3_FULL_KEYS
    assert ADAPTER in summary["disclosures"]
    assert summary["disclosures"] == list(evidence.disclosures) == outcome["disclosures"]

    big_folder, big_receipt = run_cell(w)
    (big,) = of_kind(rows(big_folder, big_receipt), "outcome")
    assert ADAPTER not in big["disclosures"]
    assert ADAPTER not in summary_of(big_folder, big_receipt)["disclosures"]


def test_the_v3_summary_verifies_its_disclosures_against_the_records_and_the_cell(
    tmp_path, monkeypatch
):
    """M8: ``disclosures`` is built from the outcome record and verified like every other field.
    A summary without the key, or with another list (the adapter's disclosure dropped or another
    added, reordered or altered), does not verify against the records. Records whose
    disclosures are not a list of nonempty strings, or whose adapter disclosure does not match
    the cell (missing at 1,000 USDT, present at V3's own 10,000), are refused when the summary is
    built, so a 1,000 cell can never be summarised without the disclosure, nor a 10,000 cell
    with one. A short failure summary has none."""
    w = world(tmp_path, monkeypatch)
    folder, receipt = run_cell(w, capital=1000)
    records = folder / RECORDS
    summary = summary_of(folder, receipt, capital=1000)
    disclosures = summary["disclosures"]
    verify_v3_summary(summary, records, receipt)
    without_adapter = [item for item in disclosures if item != ADAPTER]
    assert without_adapter != disclosures
    forged_lists = {
        "adapter dropped": without_adapter,
        "another added": [*disclosures, "another_disclosure"],
        "reordered": list(reversed(disclosures)),
        "altered": [*disclosures[:-1], disclosures[-1] + "x"],
        "empty": [],
    }
    for forged_list in forged_lists.values():
        forged = {**summary, "disclosures": forged_list}
        with pytest.raises(ValueError, match="disclosures"):
            verify_v3_summary(forged, records, receipt)
    without_key = {key: value for key, value in summary.items() if key != "disclosures"}
    with pytest.raises(ValueError, match="disclosures"):
        verify_v3_summary(without_key, records, receipt)

    def edit(value: object) -> Callable[[dict], None]:
        return lambda record: record.update(disclosures=value)

    bad_records: dict[str, tuple[int, object]] = {
        "no adapter at 1000": (1000, without_adapter),
        "not a list": (1000, "v3_funding_after_fills_is_native_timing"),
        "null": (1000, None),
        "a non-string": (1000, [*disclosures, 7]),
        "an empty string": (1000, [*disclosures, ""]),
        "adapter at 10000": (10000, disclosures),
    }
    for name, (capital, value) in bad_records.items():
        base_folder, base_receipt = (folder, receipt) if capital == 1000 else run_cell(w)
        target = tmp_path / "forged" / name.replace(" ", "_")
        forged_receipt = rewrite(base_folder, base_receipt, target, edit(value))
        with pytest.raises(ValueError, match="disclosures|adapter"):
            build_v3_summary(CellSpec(ARM, capital, 1), target / RECORDS, forged_receipt)
    # The short failure summary of a cell that did not run to its end has no disclosures.
    failed = world(tmp_path / "failed", monkeypatch, picks={START + DAY: "R2L"})
    failed_folder, failed_receipt = run_cell(failed, capital=1000)
    failure = summary_of(failed_folder, failed_receipt, capital=1000)
    assert failure["outcome"] == "engine_error" and "disclosures" not in failure


def test_v3_cell_at_doubled_costs_uses_v3s_cost_multiple_2(tmp_path, monkeypatch):
    """The 2x cell replays V3 at its own native cost multiple 2, with V3's size multiple 2: the
    frozen ``replay_window`` is called so, and the marks are V3.1's at doubled costs, below the
    base-cost cell's."""
    w = world(tmp_path, monkeypatch)
    real = baseline_v3.replay_window
    calls: list[tuple[object, object]] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append((kwargs.get("multiple"), kwargs.get("cost_multiple")))
        return real(*args, **kwargs)

    monkeypatch.setattr(baseline_v3, "replay_window", spy)
    folder, receipt = run_cell(w, costs=2)
    assert calls == [(2, 2)]
    monkeypatch.setattr(baseline_v3, "replay_window", real)

    doubled = summary_of(folder, receipt, costs=2)
    verify_v3_summary(doubled, folder / RECORDS, receipt)
    evidence = reference(w, cost_multiple=2)
    assert [(ms, equity) for ms, equity, _ in doubled["open_marks"]] == open_marks(evidence)
    assert doubled["cell"] == cell_json(costs=2)
    base_folder, base_receipt = run_cell(w)
    base = summary_of(base_folder, base_receipt)
    assert D(doubled["final_equity"]) < D(base["final_equity"])


def test_an_hour_missing_any_v3_coins_bar_is_not_complete(tmp_path, monkeypatch):
    """An hour's open mark is complete iff every one of V3's coins (read from its pack) has its
    hourly bar that hour. ETHUSDT's bar at 10:00 and BTCUSDT's at 20:00 of the first day are
    removed: V3 still marks both hours (at carried prices), and only those two are incomplete."""
    masked = {"ETHUSDT": START + 10 * HOUR, "BTCUSDT": START + 20 * HOUR}
    hourly = {
        symbol: [bar for bar in bars if bar.open_ms != masked[symbol]]
        for symbol, bars in inputs().hourly.items()
    }
    w = world(tmp_path, monkeypatch, hourly=hourly)
    folder, receipt = run_cell(w)
    found = rows(folder, receipt)
    flags = {r["open_ms"]: r["complete"] for r in of_kind(found, "hourly")}

    assert list(flags) == list(range(START, END, HOUR))
    assert [ms for ms, complete in flags.items() if complete is not True] == sorted(masked.values())
    assert all(type(complete) is bool for complete in flags.values())
    (outcome,) = of_kind(found, "outcome")
    assert outcome["coins"] == sorted(SYMBOLS)
    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert [ms for ms, _, complete in summary["open_marks"] if not complete] == sorted(
        masked.values()
    )


def test_v3_stops_map_to_v4_outcomes(tmp_path, monkeypatch):
    """R3's outcomes. A liquidation, V3's one native stop, is ``liquidated``, with the stop at its
    mark's hour and that mark as the final equity: R1 holds shorts, and both coins' highs at 06:00
    on day two spike 100-fold. Every other V3 stop, here the untradable ones (patched as in
    V3.1's ``test_an_untradable_v3_stop_is_an_incomplete_result_never_frozen``), is an
    ``engine_error`` of type ``V3Stop`` with the status as its message: incomplete, never a
    pass."""
    spike = START + 30 * HOUR
    w = world(tmp_path / "liquidation", monkeypatch, rule="R1", hourly=spiked(spike, 100))
    folder, receipt = run_cell(w)
    evidence = reference(w)
    stop = evidence.native[-1]
    assert evidence.status == "liquidation" and stop.kind == "adverse"

    found = rows(folder, receipt)
    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert (summary["outcome"], summary["reason"], summary["stop_ms"]) == (
        "liquidated",
        None,
        spike,
    )
    assert stop.timestamp_ms - stop.timestamp_ms % HOUR == spike
    assert summary["final_equity"] == str(stop.equity)
    assert summary["liquidations"] == 1
    assert summary["open_marks"][-1][0] == spike and len(summary["open_marks"]) == 31
    assert of_kind(found, "event") == []  # no terminal mark after a stop
    assert (summary["equity_2025"], summary["final_after_close"]) == (None, None)

    original = v3_runner.execute_hour
    for status in ("no_tradable_position", "leverage_not_restored"):

        def stopping(account: Any, hour_ms: int, *args: Any, status: str = status, **kw: Any):
            result = original(account, hour_ms, *args, **kw)
            return replace(result, reason=status) if hour_ms == spike else result

        u = world(tmp_path / status, monkeypatch)
        with monkeypatch.context() as patch:
            patch.setattr(v3_runner, "execute_hour", stopping)
            folder, receipt = run_cell(u)
        found = rows(folder, receipt)
        (outcome,) = of_kind(found, "outcome")
        assert (outcome["outcome"], outcome["reason"], outcome["stop_ms"]) == (
            "engine_error",
            f"V3Stop: {status}",
            None,
        )
        assert outcome["liquidations"] == 0
        assert of_kind(found, "hourly")[-1]["open_ms"] == spike
        summary = summary_of(folder, receipt)
        verify_v3_summary(summary, folder / RECORDS, receipt)
        assert summary == {
            "format": V3_SUMMARY_FORMAT,
            "cell": cell_json(),
            "window": {"start_ms": START, "end_ms": END - HOUR},
            "data": pins(u),
            "outcome": "engine_error",
            "type": "V3Stop",
            "message": status,
            "hour_ms": spike,
        }
    # A stop's hour is null only when V3 marked no hour; nor is its type anything but V3Stop.
    for index, (key, value) in enumerate([("hour_ms", None), ("type", "RuntimeError")]):
        target = tmp_path / "forged" / str(index)
        forged = rewrite(
            folder, receipt, target, lambda record, k=key, v=value: record.update({k: v})
        )
        with pytest.raises(ValueError):
            summary_of(target, forged)


def test_a_v3_cell_without_a_pick_before_its_window_is_an_engine_error(tmp_path, monkeypatch):
    """The picks hold no pick at or before the window's start (the first is a day later), so
    ``replay_v3_baseline`` replays nothing and returns ``no_selector_pick``: an ``engine_error``
    of type ``V3Stop`` with that status as its message, no hourly record, no terminal event and a
    null hour, its final equity the capital."""
    w = world(tmp_path, monkeypatch, picks={START + DAY: "R2L"})
    folder, receipt = run_cell(w)
    found = rows(folder, receipt)

    assert [kind for kind, _ in found] == ["outcome"]
    (outcome,) = of_kind(found, "outcome")
    assert {key: outcome[key] for key in ("reason", "stop_ms", "hours", "final_equity")} == {
        "reason": "V3Stop: no_selector_pick",
        "stop_ms": None,
        "hours": 0,
        "final_equity": "10000",
    }
    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert summary == {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_json(),
        "window": {"start_ms": START, "end_ms": END - HOUR},
        "data": pins(w),
        "outcome": "engine_error",
        "type": "V3Stop",
        "message": "no_selector_pick",
        "hour_ms": None,
    }


def unreconciled(monkeypatch: pytest.MonkeyPatch) -> None:
    """V3.1's ``test_a_missing_residual_is_not_explained`` patch: V3's comparison report without
    a reconciliation residual, so V3's own ``accounting_explained`` is false."""
    original = baseline_v3.comparison_report

    def report(*args: Any, **kwargs: Any) -> Any:
        return replace(original(*args, **kwargs), reconciliation_residual=None)

    monkeypatch.setattr(baseline_v3, "comparison_report", report)


def flagged(**flags: object) -> Callable[[pytest.MonkeyPatch], None]:
    """V3's evidence for the cell with ``flags`` set, the rest of it V3's own."""

    def patch(monkeypatch: pytest.MonkeyPatch) -> None:
        real = v3_as_built.replay_v3_baseline

        def replay(*args: Any, **kwargs: Any) -> BaselineEvidence:
            evidence = real(*args, **kwargs)
            assert evidence.status in (None, "liquidation")
            assert evidence.accounting_explained is True  # the synthetic runs reconcile
            assert evidence.wallet_quantity_exact is True
            return replace(evidence, **flags)

        monkeypatch.setattr(v3_as_built, "replay_v3_baseline", replay)

    return patch


@pytest.mark.parametrize(
    ("unexplain", "failed"),
    [
        (unreconciled, "accounting_explained"),
        (flagged(accounting_explained=False), "accounting_explained"),
        (flagged(wallet_quantity_exact=False), "wallet_quantity_exact"),
        (flagged(wallet_quantity_exact=None), "wallet_quantity_exact"),
        (flagged(accounting_explained=False, wallet_quantity_exact=False), "accounting_explained"),
    ],
    ids=["residual missing", "explained false", "wallet false", "wallet null", "both false"],
)
def test_an_unexplained_v3_accounting_result_is_an_engine_error_not_complete(
    unexplain, failed, tmp_path, monkeypatch
):
    """Controller ruling: a V3 run that completed (status None) but whose own reconciliation
    failed, ``accounting_explained`` or ``wallet_quantity_exact`` not true, is never
    ``complete``: it is an ``engine_error`` of type ``V3Accounting`` whose message names the
    first failed flag, with the short failure summary. Its records keep every open mark and the
    terminal event. A summary naming another flag, or without the terminal event, is refused."""
    w = world(tmp_path, monkeypatch)
    unexplain(monkeypatch)
    folder, receipt = run_cell(w)
    found = rows(folder, receipt)

    (outcome,) = of_kind(found, "outcome")
    assert (outcome["outcome"], outcome["type"], outcome["message"], outcome["reason"]) == (
        "engine_error",
        "V3Accounting",
        failed,
        f"V3Accounting: {failed}",
    )
    assert outcome["stop_ms"] is None
    assert len(of_kind(found, "hourly")) == 72 and len(of_kind(found, "event")) == 1
    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert summary == {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_json(),
        "window": {"start_ms": START, "end_ms": END - HOUR},
        "data": pins(w),
        "outcome": "engine_error",
        "type": "V3Accounting",
        "message": failed,
        "hour_ms": END,
    }
    other = next(flag for flag in ACCOUNTING_FLAGS if flag != failed)

    def rename(record: dict) -> None:
        record.update(message=other, reason=f"V3Accounting: {other}")

    forged = rewrite(folder, receipt, tmp_path / "other_flag", rename)
    with pytest.raises(ValueError, match="flag"):
        summary_of(tmp_path / "other_flag", forged)
    forged = rewrite_rows(
        folder, receipt, tmp_path / "no_terminal", lambda rs: [r for r in rs if r[0] != "event"]
    )
    with pytest.raises(ValueError, match="terminal"):
        summary_of(tmp_path / "no_terminal", forged)
    forged = rewrite(
        folder, receipt, tmp_path / "other_hour", lambda record: record.update(hour_ms=END - HOUR)
    )
    with pytest.raises(ValueError, match="hour"):
        summary_of(tmp_path / "other_hour", forged)


@pytest.mark.parametrize(
    ("flags", "failed"),
    [
        ({"accounting_explained": False}, "accounting_explained"),
        ({"wallet_quantity_exact": False}, "wallet_quantity_exact"),
        ({"accounting_explained": False, "wallet_quantity_exact": None}, "accounting_explained"),
    ],
    ids=["explained false", "wallet false", "both failed"],
)
def test_a_liquidation_with_unexplained_accounting_is_an_engine_error_not_liquidated(
    flags, failed, tmp_path, monkeypatch
):
    """Controller ruling: V3's accounting flags bind a liquidation too. A liquidated V3 run (R1's
    shorts and the 100-fold spike at 06:00 on day two) whose ``accounting_explained`` or
    ``wallet_quantity_exact`` is not true is an ``engine_error`` of type ``V3Accounting``, its
    message the first failed flag, its hour the liquidation's, with no terminal event and the
    short failure summary. A forgery naming another hour, no liquidation or another flag is
    refused."""
    spike = START + 30 * HOUR
    w = world(tmp_path, monkeypatch, rule="R1", hourly=spiked(spike, 100))
    flagged(**flags)(monkeypatch)
    folder, receipt = run_cell(w)
    found = rows(folder, receipt)

    (outcome,) = of_kind(found, "outcome")
    assert {key: outcome[key] for key in ("outcome", "type", "message", "reason", "stop_ms")} == {
        "outcome": "engine_error",
        "type": "V3Accounting",
        "message": failed,
        "reason": f"V3Accounting: {failed}",
        "stop_ms": None,
    }
    assert (outcome["liquidations"], outcome["hour_ms"]) == (1, spike)
    assert len(of_kind(found, "hourly")) == 31 and of_kind(found, "event") == []
    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert summary == {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_json(),
        "window": {"start_ms": START, "end_ms": END - HOUR},
        "data": pins(w),
        "outcome": "engine_error",
        "type": "V3Accounting",
        "message": failed,
        "hour_ms": spike,
    }
    other = next(flag for flag in ACCOUNTING_FLAGS if flag != failed)
    forgeries: dict[str, tuple[dict[str, object], str]] = {
        "another hour": ({"hour_ms": spike - HOUR}, "liquidation"),
        "no liquidation": ({"liquidations": 0}, "liquidations"),
        "another flag": ({"message": other, "reason": f"V3Accounting: {other}"}, "flag"),
    }
    for name, (change, match) in forgeries.items():
        target = tmp_path / "forged" / name.replace(" ", "_")
        forged = rewrite(folder, receipt, target, lambda record, c=change: record.update(c))
        with pytest.raises(ValueError, match=match):
            summary_of(target, forged)


def test_a_full_v3_summary_needs_v3s_accounting_flags_and_no_engine_error_keys(
    tmp_path, monkeypatch
):
    """Review finding: a full summary binds V3's accounting flags. The records of a complete and
    of a liquidated cell, re-chained with ``accounting_explained`` or ``wallet_quantity_exact``
    not true, or with an engine error's ``type``, ``message`` or ``hour_ms`` added to the outcome
    record, are refused by ``build_v3_summary``, and the true summary does not verify against
    them."""
    complete = world(tmp_path / "complete", monkeypatch)
    spike = START + 30 * HOUR
    liquidated = world(tmp_path / "liquidated", monkeypatch, rule="R1", hourly=spiked(spike, 100))
    changes: dict[str, tuple[dict[str, object], str]] = {
        "explained false": ({"accounting_explained": False}, "accounting_explained"),
        "wallet false": ({"wallet_quantity_exact": False}, "wallet_quantity_exact"),
        "wallet null": ({"wallet_quantity_exact": None}, "wallet_quantity_exact"),
        "a type": ({"type": "V3Accounting"}, "has no type"),
        "a message": ({"message": "accounting_explained"}, "has no message"),
        "an hour": ({"hour_ms": END}, "has no hour_ms"),
    }
    for label, w in (("complete", complete), ("liquidated", liquidated)):
        folder, receipt = run_cell(w)
        summary = summary_of(folder, receipt)
        assert summary["outcome"] == label
        verify_v3_summary(summary, folder / RECORDS, receipt)
        for name, (change, match) in changes.items():
            target = tmp_path / "forged" / label / name.replace(" ", "_")
            forged = rewrite(folder, receipt, target, lambda record, c=change: record.update(c))
            with pytest.raises(ValueError, match=match):
                build_v3_summary(CellSpec(ARM, 10000, 1), target / RECORDS, forged)
            with pytest.raises(ValueError):
                verify_v3_summary(summary, target / RECORDS, forged)


def test_a_complete_v3_cell_reads_its_final_equity_from_its_one_terminal_event(
    tmp_path, monkeypatch
):
    """Controller ruling: V3's terminal mark stays an ``event`` of type ``terminal``
    (``records.KINDS`` unchanged), and the summary reads a complete cell's final equity from it.
    Records of a complete cell with no such event, two of them, one at another time, or one whose
    equity is not the outcome's are refused; so are a liquidated cell's records with one."""
    w = world(tmp_path / "complete", monkeypatch)
    folder, receipt = run_cell(w)
    summary = summary_of(folder, receipt)
    (event,) = of_kind(rows(folder, receipt), "event")
    assert event["type"] == "terminal" and summary["final_equity"] == event["equity"]

    def before_outcome(extra: Callable[[dict], list[dict]]) -> Callable[[Rows], Rows]:
        def transform(found: Rows) -> Rows:
            kept = [(kind, record) for kind, record in found if kind != "event"]
            events = [record for kind, record in found if kind == "event"]
            new = [("event", record) for item in events for record in extra(dict(item))]
            return [*kept[:-1], *new, kept[-1]]

        return transform

    def moved(record: dict) -> list[dict]:
        return [{**record, "timestamp_ms": END - HOUR, "hour_ms": END - HOUR}]

    forgeries = {
        "none": before_outcome(lambda record: []),
        "two": before_outcome(lambda record: [record, record]),
        "another time": before_outcome(moved),
        "another equity": before_outcome(lambda record: [{**record, "equity": "10000.5"}]),
        "another type": before_outcome(lambda record: [{**record, "type": "terminal_mark"}]),
    }
    for name, transform in forgeries.items():
        target = tmp_path / "forged" / name.replace(" ", "_")
        forged = rewrite_rows(folder, receipt, target, transform)
        with pytest.raises(ValueError):
            summary_of(target, forged)

    spike = START + 30 * HOUR
    liquidated = world(tmp_path / "liquidated", monkeypatch, rule="R1", hourly=spiked(spike, 100))
    stop_folder, stop_receipt = run_cell(liquidated)
    assert summary_of(stop_folder, stop_receipt)["outcome"] == "liquidated"
    terminal = {**event, "equity": "1"}

    def with_terminal(found: Rows) -> Rows:
        return [*found[:-1], ("event", terminal), found[-1]]

    target = tmp_path / "forged" / "liquidated"
    forged = rewrite_rows(stop_folder, stop_receipt, target, with_terminal)
    with pytest.raises(ValueError, match="terminal"):
        summary_of(target, forged)


# ---- the summary binds its cell, window, pack and picks -------------------------------------


Rows = list[tuple[str, dict[str, Any]]]


def rewrite_rows(
    folder: Path, receipt: Receipt, target: Path, transform: Callable[[Rows], Rows]
) -> Receipt:
    """The cell's records as ``transform`` changes them, re-chained into ``target`` with a
    receipt of their own: a forgery a reader cannot tell by its hashes."""
    target.mkdir(parents=True)
    with RecordWriter(target / RECORDS) as writer:
        for kind, record in transform(rows(folder, receipt)):
            writer.append(kind, record)
        forged = writer.close()
    write_receipt_file(target / RECEIPT, forged)
    return forged


def rewrite(
    folder: Path, receipt: Receipt, target: Path, change: Callable[[dict], None]
) -> Receipt:
    """The cell's records with ``change`` applied to the outcome record, re-chained."""

    def transform(found: Rows) -> Rows:
        for kind, record in found:
            if kind == "outcome":
                change(record)
        return found

    return rewrite_rows(folder, receipt, target, transform)


def test_v3_summary_verifies_and_refuses_another_cell_window_pack_or_picks(tmp_path, monkeypatch):
    """``verify_v3_summary`` rebuilds the summary from the records and requires equality: a
    summary relabelled to another capital, cost level, window, V3 pack or picks does not verify,
    nor does the true summary against records whose outcome names another cell, window, pack or
    picks (re-chained, with their own receipt). Records of another window than R3's, of another
    cell than the one asked for, or whose data is not exactly the two pins, are refused when the
    summary is built."""
    w = world(tmp_path, monkeypatch)
    folder, receipt = run_cell(w)
    records = folder / RECORDS
    summary = summary_of(folder, receipt)
    verify_v3_summary(summary, records, receipt)

    def relabel(path: str, value: object) -> Callable[[dict], None]:
        def apply(document: dict) -> None:
            *parents, last = path.split(".")
            inner = document
            for name in parents:
                inner = inner[name]
            inner[last] = value

        return apply

    def recell(capital: int, costs: int) -> Callable[[dict], None]:
        def apply(document: dict) -> None:
            document["cell"] = cell_json(capital, costs)

        return apply

    changes = {
        "capital": recell(1000, 1),
        "costs": recell(10000, 2),
        "window start": relabel("window.start_ms", START + HOUR),
        "window end": relabel("window.end_ms", END),
        "pack": relabel("data.v3_pack_sha256", OTHER_PIN),
        "picks": relabel("data.picks_sha256", OTHER_PIN),
    }
    for name, change in changes.items():
        forged = copy.deepcopy(summary)
        change(forged)
        with pytest.raises(ValueError):
            verify_v3_summary(forged, records, receipt)
        target = tmp_path / "forged" / name.replace(" ", "_")
        forged_receipt = rewrite(folder, receipt, target, change)
        with pytest.raises(ValueError):
            verify_v3_summary(summary, target / RECORDS, forged_receipt)
    with pytest.raises(ValueError, match="window"):
        build_v3_summary(
            CellSpec(ARM, 10000, 1),
            tmp_path / "forged" / "window_end" / RECORDS,
            read_receipt(tmp_path / "forged" / "window_end" / RECEIPT),
        )
    # The data must be exactly the two pins: not one of them, not V4's four, not a short pin.
    bad_data = [
        {"v3_pack_sha256": w.pack_sha256},
        {**pins(w), "config_sha256": OTHER_PIN},
        {**pins(w), "picks_sha256": "abc"},
        None,
    ]
    for index, data in enumerate(bad_data):
        target = tmp_path / "forged" / f"data_{index}"
        forged_receipt = rewrite(folder, receipt, target, relabel("data", data))
        with pytest.raises(ValueError, match="data"):
            build_v3_summary(CellSpec(ARM, 10000, 1), target / RECORDS, forged_receipt)
    with pytest.raises(ValueError, match="cell"):
        build_v3_summary(CellSpec(ARM, 1000, 1), records, receipt)
    with pytest.raises(ValueError):
        build_v3_summary(CellSpec("v4_main", 10000, 1), records, receipt)
    with pytest.raises(ValueError):
        verify_v3_summary({**summary, "format": "v4-summary-1"}, records, receipt)


# ---- the picks ------------------------------------------------------------------------------


def test_v3_picks_are_pinned_and_a_cell_refuses_other_picks(tmp_path, monkeypatch):
    """``run_v3_picks`` trains V3's selector once at 10,000 USDT and writes the picks as canonical
    JSON, never over an existing file, returning its SHA-256; a cell reads them only through that
    pin, before anything is written: other picks, another spelling of the same picks, malformed
    picks or another pack pin are refused and leave nothing behind."""
    pack, pack_sha256 = write_pack(tmp_path / "pack")
    seen = train(monkeypatch, "R2L")
    out = tmp_path / "picks"
    digest = run_v3_picks(pack, pack_sha256, out)
    path = out / PICKS_FILE
    raw = path.read_bytes()
    assert raw == b'{"picks":{"%d":"R2L"}}' % START
    assert digest == hashlib.sha256(raw).hexdigest()
    assert seen == [D(10000)]  # V3's own training capital
    assert read_v3_picks(path, digest) == {START: "R2L"}
    with pytest.raises(ValueError, match="already"):
        run_v3_picks(pack, pack_sha256, out)
    assert path.read_bytes() == raw and seen == [D(10000)]

    cell = CellSpec(ARM, 10000, 1)
    cell_dir = tmp_path / "cell"

    def refused(
        picks_path: Path, picks_sha256: str, *, pack_pin: str = pack_sha256, spec: CellSpec = cell
    ) -> None:
        with pytest.raises(ValueError):
            run_v3_cell(pack, pack_pin, picks_path, picks_sha256, spec, cell_dir)
        assert not cell_dir.exists()

    refused(path, OTHER_PIN)  # the picks are not the pinned ones
    other = tmp_path / "other" / PICKS_FILE
    other.parent.mkdir()
    other.write_bytes(b'{"picks":{"%d":"R3L"}}' % START)
    refused(other, digest)  # other picks under the pinned picks' pin
    bad_files = {
        "spaced": b'{"picks": {"%d": "R2L"}}' % START,
        "extra key": b'{"picks":{"%d":"R2L"},"rule":"R2L"}' % START,
        "unknown rule": b'{"picks":{"%d":"R9"}}' % START,
        "sealed time": b'{"picks":{"1735689600000":"R2L"}}',
        "not a time": b'{"picks":{"0%d":"R2L"}}' % START,
        "no picks": b'{"picks":{}}',
        "a list": b'{"picks":[]}',
    }
    for name, bad in bad_files.items():
        spoiled = tmp_path / "bad" / name.replace(" ", "_") / PICKS_FILE
        spoiled.parent.mkdir(parents=True)
        spoiled.write_bytes(bad)
        pin = hashlib.sha256(bad).hexdigest()
        with pytest.raises(ValueError):
            read_v3_picks(spoiled, pin)
        refused(spoiled, pin)  # pinned, but not picks a cell reads
    refused(path, digest, pack_pin=OTHER_PIN)  # the V3 pack is not the pinned one
    refused(path, digest, spec=CellSpec("v4_main", 10000, 1))  # not V3's arm
    run_v3_cell(pack, pack_sha256, path, digest, cell, cell_dir)  # the pinned picks run
    assert sorted(item.name for item in cell_dir.iterdir()) == [RECEIPT, RECORDS]
    with pytest.raises(ValueError, match="already"):
        run_v3_cell(pack, pack_sha256, path, digest, cell, cell_dir)


# ---- the CLI and the page -------------------------------------------------------------------


def run_cli(argv: Sequence[str]) -> tuple[int, str, str]:
    """``v4_v3_cell.main(argv)`` with its standard output and error captured."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = v4_v3_cell.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def test_v3_cli_prints_no_price_and_names_only_the_exception_type(tmp_path, monkeypatch):
    """``picks`` prints the count and the pin; ``run`` prints, as ``v4_cell.py`` does, the cell's
    id, outcome, record count, hours and the summary's SHA-256, no price or equity; it writes the
    verified summary (as canonical JSON) and the page. A failure is exit 1 with one line on
    standard error naming the step and the exception's type, never its message (which may hold a
    price); bad arguments are argparse's exit 2."""
    pack, pack_sha256 = write_pack(tmp_path / "pack")
    train(monkeypatch)
    picks_dir = tmp_path / "picks"
    picks_argv = ["picks", "--pack", str(pack), "--pack-sha256", pack_sha256]
    code, out, err = run_cli([*picks_argv, "--out", str(picks_dir)])
    picks = picks_dir / PICKS_FILE
    digest = hashlib.sha256(picks.read_bytes()).hexdigest()
    assert (code, out, err) == (0, f"v4_v3_cell picks: 1 picks, {PICKS_FILE} sha256 {digest}\n", "")
    code, out, err = run_cli([*picks_argv, "--out", str(picks_dir)])
    assert (code, out) == (1, "")
    assert err == f"v4_v3_cell picks: refused: the folder already holds {PICKS_FILE}\n"
    bad_pack = ["picks", "--pack", str(pack), "--pack-sha256", OTHER_PIN]
    code, out, err = run_cli([*bad_pack, "--out", str(tmp_path / "no_picks")])
    assert (code, out, err) == (1, "", "v4_v3_cell picks: computing the picks failed: ValueError\n")
    assert not (tmp_path / "no_picks").exists()

    def argv(capital: int = 10000, costs: int = 1, picks_sha256: str = digest) -> list[str]:
        return [
            "run",
            "--pack",
            str(pack),
            "--pack-sha256",
            pack_sha256,
            "--picks",
            str(picks),
            "--picks-sha256",
            picks_sha256,
            "--capital",
            str(capital),
            "--costs",
            str(costs),
            "--out",
            str(tmp_path / "cells"),
        ]

    code, out, err = run_cli(argv())
    folder = tmp_path / "cells" / f"{ARM}-10000-1x"
    receipt = read_receipt(folder / RECEIPT)
    raw = (folder / "summary.json").read_bytes()
    summary = json.loads(raw)
    assert (code, err) == (0, "")
    assert out == (
        f"v4_v3_cell run: {ARM}-10000-1x: outcome complete, {receipt.record_count} records, "
        f"72 hours, summary sha256 {hashlib.sha256(raw).hexdigest()}\n"
    )
    assert re.search(r"[0-9]\.[0-9]", out) is None
    assert summary["final_equity"] not in out
    assert raw == _canonical(summary)
    verify_v3_summary(summary, folder / RECORDS, receipt)
    assert sorted(item.name for item in folder.iterdir()) == sorted(OUTPUT_FILES)
    assert (folder / "report.html").read_text("utf-8") == render_v3_page(summary)

    code, out, err = run_cli(argv())  # a cell's files are never replaced
    assert (code, out) == (1, "")
    assert err == (
        f"v4_v3_cell run: {ARM}-10000-1x: refused: the cell's folder already holds "
        f"{', '.join(OUTPUT_FILES)}\n"
    )

    code, out, err = run_cli(argv(costs=2, picks_sha256=OTHER_PIN))
    assert (code, out, err) == (
        1,
        "",
        f"v4_v3_cell run: {ARM}-10000-2x: the cell did not run: ValueError\n",
    )
    assert not (tmp_path / "cells" / f"{ARM}-10000-2x").exists()

    def broken(*args: object) -> dict[str, object]:
        raise ValueError("the first open mark, 10234.56, is not the capital")

    monkeypatch.setattr(v4_v3_cell, "build_v3_summary", broken)
    code, out, err = run_cli(argv(capital=1000))
    assert (code, out) == (1, "")
    assert err == f"v4_v3_cell run: {ARM}-1000-1x: building the summary failed: ValueError\n"
    assert sorted(item.name for item in (tmp_path / "cells" / f"{ARM}-1000-1x").iterdir()) == [
        RECEIPT,
        RECORDS,
    ]

    for change, value in (("--capital", "5000"), ("--costs", "3")):
        bad = argv()
        bad[bad.index(change) + 1] = value
        with pytest.raises(SystemExit) as stopped, contextlib.redirect_stderr(io.StringIO()):
            v4_v3_cell.main(bad)
        assert stopped.value.code == 2


def test_v3_page_is_self_contained_and_escapes_every_value(tmp_path, monkeypatch):
    """F2: ``render_page`` takes only V4's summary format, so ``v3_as_built`` renders its own page
    with the same rules: no script, nothing fetched, a Content-Security-Policy, every text value
    escaped. A full summary shows its headline and periods; a failure its details."""
    w = world(tmp_path, monkeypatch)
    folder, receipt = run_cell(w)
    page = render_v3_page(summary_of(folder, receipt))
    assert page.startswith("<!doctype html>")
    assert "default-src 'none'; style-src 'unsafe-inline'" in page
    assert "<script" not in page and "http" not in page.replace('http-equiv="', "")
    assert f"V4 cell {ARM}-10000-1x" in page and "terminal mark" in page
    assert ADAPTER not in page  # V3's own capital runs without the adapter
    # M8: a 1,000 USDT cell's page lists V3's disclosures, the adapter's among them, escaped.
    small_folder, small_receipt = run_cell(w, capital=1000)
    small = summary_of(small_folder, small_receipt, capital=1000)
    small_page = render_v3_page(small)
    assert "<h2>Disclosures</h2>" in small_page and ADAPTER in small_page
    marked = render_v3_page({**small, "disclosures": ['<script>alert("d")</script>']})
    assert "<script>" not in marked
    assert "&lt;script&gt;alert(&quot;d&quot;)&lt;/script&gt;" in marked
    failure = {
        "format": V3_SUMMARY_FORMAT,
        "cell": cell_json(),
        "window": {"start_ms": START, "end_ms": END - HOUR},
        "data": pins(w),
        "outcome": "engine_error",
        "type": "V3Stop",
        "message": '<script>alert("x")</script>&',
        "hour_ms": None,
    }
    shown = render_v3_page(failure)
    assert "<script>" not in shown
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;&amp;" in shown
    with pytest.raises(ValueError):
        render_v3_page({**failure, "format": "v4-summary-1"})
    assert "V3 stopped before its window's end" in shown
    # M2: a V3Accounting is worded by case. A completed run's hour is its terminal mark's.
    accounting = render_v3_page(
        {**failure, "type": "V3Accounting", "message": "<b>", "hour_ms": END}
    )
    assert (
        "V3 ran to its window's end, but its own accounting did not reconcile (&lt;b&gt;)"
        in accounting
    )
    assert "V3 stopped before" not in accounting and "liquidated" not in accounting
    # A liquidation's is the hour of its mark: it did not run to its window's end.
    liquidation = render_v3_page(
        {**failure, "type": "V3Accounting", "message": "<b>", "hour_ms": END - HOUR}
    )
    assert "V3 was liquidated, and its own accounting did not reconcile (&lt;b&gt;)" in liquidation
    assert "ran to its window's end" not in liquidation
    assert "V3 stopped before" not in liquidation
