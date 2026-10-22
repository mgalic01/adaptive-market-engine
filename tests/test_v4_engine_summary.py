"""V4 engine task 14: each cell's ``summary.json``, its self-verification and its HTML page.

A summary is built from the cell's records alone, plus the cell spec, and ``verify_summary``
rebuilds it from them. Most tests replay small synthetic worlds from ``tests/v4_synthetic.py``
through the real engine (``run_v4_cell`` and ``run_hold_cell``). The era and year boundaries from
2020 to 2025 use hand-written records in the engine's ``hourly`` and ``outcome`` shapes, written
through the engine's own ``RecordWriter``, so that no test replays 35,000 hours. Expected values
are recomputed here from the records, the cell result and exact Fractions. ``seed`` books fills
into a cell's ledger before its first hour, as in the run tests, for a position the rules would
not make on their own. The network is blocked for every test and no real pack is read.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import re
import shutil
import socket
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from v4_synthetic import (
    DAY,
    HOUR,
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    every_month,
    hours_in,
    month_start,
    path,
    write_world,
)

from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.v4.engine import hold, run
from crypto_grid_bot.v4.engine import summary as summary_module
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec
from crypto_grid_bot.v4.engine.ledger import Audit, Fill, Ledger
from crypto_grid_bot.v4.engine.lifecycle import Lifecycles
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.records import Receipt, RecordWriter, read_records, write_receipt
from crypto_grid_bot.v4.engine.sizing import size_book
from crypto_grid_bot.v4.engine.summary import (
    SUMMARY_FORMAT,
    build_summary,
    render_page,
    verify_summary,
    write_cell_outputs,
)

D = Decimal
F = Fraction
T0 = month_start("2025-01")  # 2025-01-01 00:00 UTC
FEB = month_start("2025-02")
NOV = month_start("2024-11")
DEC = month_start("2024-12")
Y2021 = month_start("2021-01")
CAPITAL = 10000
MAIN = CellSpec("v4_main", CAPITAL, 1)
FULL_KEYS = {
    "format",
    "cell",
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
DECIMAL_FIELDS = (
    "initial_equity",
    "final_equity",
    "equity_2025",
    "final_after_close",
    "max_drawdown",
    "compounded_return",
    "accounting_residual",
)
PERIOD_KEYS = ("start_ms", "end_ms", "start_equity", "end_equity", "return")
ERA_NAMES = ("start-2020", "2021-2024", "2025-end")
# What a self-contained page with no script and no fetch never holds.
FORBIDDEN = (
    "<script",
    "javascript:",
    "http:",
    "https:",
    "src=",
    "href=",
    "url(",
    "@import",
    "@font-face",
    "<link",
    "<iframe",
    "<img",
    "<object",
    "<embed",
)

Rows = list[tuple[str, dict[str, Any]]]


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


def block_network(patch: pytest.MonkeyPatch) -> None:
    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    for owner, name in [
        (socket, "getaddrinfo"),
        (socket, "create_connection"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
    ]:
        patch.setattr(owner, name, refuse)


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""
    block_network(monkeypatch)


# ---- helpers ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Replay:
    """One cell replayed by the engine: its spec, result, directory and verified records."""

    cell: CellSpec
    result: run.CellResult
    out: Path
    rows: Rows

    @property
    def records(self) -> Path:
        return self.out / run.RECORDS_FILE

    def summary(self) -> dict[str, Any]:
        return build_summary(self.cell, self.result, self.records)


def load(root: Path, world: World, name: str = "world") -> Market:
    return Market.load(write_world(root / name, world))


def replay(market: Market, root: Path, cell: CellSpec) -> Replay:
    """Run ``cell`` into ``root / cell_id`` with the arm's own loop and read its records."""
    out = root / cell.cell_id
    runner = hold.run_hold_cell if ARMS[cell.arm].family == "hold" else run.run_v4_cell
    result = runner(market, cell, out)
    return Replay(cell, result, out, list(read_records(out / run.RECORDS_FILE, result.receipt)))


def of_kind(rows: Iterable[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [record for name, record in rows if name == kind]


def seed(monkeypatch, at_ms: int, fills: Sequence[tuple[str, Fill]]) -> None:
    """Make every cell start with ``fills`` (each with its coin) booked at ``at_ms``, through
    run.py's ``Ledger`` and ``Lifecycles`` names, as the run tests do."""
    made: dict[str, Ledger] = {}

    def make_ledger(initial: Decimal) -> Ledger:
        ledger = Ledger(initial)
        made["ledger"] = ledger
        return ledger

    def make_lifecycles() -> Lifecycles:
        ledger, lifecycles = made["ledger"], Lifecycles()
        by_coin: dict[str, list[tuple[Fill, Decimal]]] = {}
        for coin, item in fills:
            by_coin.setdefault(coin, []).append((item, ledger.fill(item)))
        for coin, booked in by_coin.items():
            spot = ledger.quantity("spot", coin)
            perpetuals = {f.symbol for f, _ in booked if f.venue == "futures"}
            futures = sum((ledger.quantity("futures", symbol) for symbol in perpetuals), D(0))
            notional = sum((f.side * f.quantity * f.price for f, _ in booked), D(0))
            lifecycles.after_batch(at_ms, coin, notional, spot, futures, False, booked, "signal")
        return lifecycles

    monkeypatch.setattr(run, "Ledger", make_ledger)
    monkeypatch.setattr(run, "Lifecycles", make_lifecycles)


def seed_fill(at_ms: int, venue: str, symbol: str, side: int, quantity: str, price: str) -> Fill:
    return Fill(at_ms, venue, symbol, side, D(quantity), D(price), D(0), "seed")


class _BrokenAudit(Ledger):
    """A ledger whose audit reports ``changes`` from its first call on."""

    changes: dict[str, Any] = {}

    def audit(self, prices):
        return replace(super().audit(prices), **type(self).changes)


def broken_audit(monkeypatch, changes: dict[str, Any]) -> None:
    monkeypatch.setattr(run, "Ledger", type("Broken", (_BrokenAudit,), {"changes": changes}))


def ratio(end: str, start: str) -> str:
    """``end / start - 1`` under the engine's context, as the summary writes it."""
    with localcontext(CONTEXT):
        return str(D(end) / D(start) - 1)


def span(start_ms: int, end_ms: int, start_equity: str, end_equity: str) -> dict[str, Any]:
    return {
        "start_ms": start_ms,
        "end_ms": end_ms,
        "start_equity": start_equity,
        "end_equity": end_equity,
        "return": ratio(end_equity, start_equity),
    }


def era(name: str, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, **(dict.fromkeys(PERIOD_KEYS) if values is None else values)}


def year(number: int, values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"year": number, **(dict.fromkeys(PERIOD_KEYS) if values is None else values)}


def exact_drawdown(equities: Sequence[Decimal]) -> Fraction:
    """The largest fall from a running peak, as a fraction of the peak, exactly."""
    peak, worst = F(equities[0]), F(0)
    for equity in equities:
        peak = max(peak, F(equity))
        worst = max(worst, (peak - F(equity)) / peak)
    return worst


def leaves(value: object) -> Iterable[object]:
    if isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item)
    else:
        yield value


def keys(value: object) -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from keys(item)


def shape(value: object) -> object:
    """The keys and value types of a summary, with a list as the set of its items' shapes."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        return ("list", tuple(sorted({json.dumps(shape(item), sort_keys=True) for item in value})))
    return type(value).__name__


def cell_json(cell: CellSpec) -> dict[str, Any]:
    return {
        "id": cell.cell_id,
        "arm": cell.arm,
        "capital": cell.capital,
        "cost_multiple": cell.cost_multiple,
    }


def static_mask(first_ms: int, hours: int) -> tuple[int, ...]:
    """Hours 00:00 to 04:59 of every day: a spot series masked so has no daily bar, so its coin
    never gets a target and keeps exactly the legs ``seed`` gives it."""
    return tuple(
        stamp for stamp in range(first_ms, first_ms + hours * HOUR, HOUR) if stamp % DAY < 5 * HOUR
    )


# ---- worlds -------------------------------------------------------------------------------


def trend_world() -> World:
    """BTCUSDT rising, with its perpetual, and ETHUSDT falling, spot only: history from
    2024-10, both selected in 2025-01 (the window)."""
    start = month_start("2024-10")
    hours = hours_in("2024-10", "2025-01")
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, path("50000", (hours, "0.0003"), noise="0.003", seed=1)),
        perpetual=PerpetualSpec(),
    )
    eth = CoinSpec(
        "ETHUSDT", Series(start, path("2000", (hours, "-0.0003"), noise="0.003", seed=2))
    )
    return World("2025-01", (btc, eth), every_month("2025-01", "2025-01", ("BTCUSDT", "ETHUSDT")))


def flat_world() -> World:
    """BTCUSDT at a flat 100 (sigma 0, so no weight ever), spot only, in 2025-01."""
    btc = CoinSpec("BTCUSDT", Series(T0, ("100",) * hours_in("2025-01", "2025-01")))
    return World("2025-01", (btc,), {"2025-01": ("BTCUSDT",)})


@pytest.fixture(scope="module")
def trend(tmp_path_factory) -> dict[str, Replay]:
    """``v4_main``, ``hold_universe`` and ``hold_btc`` over ``trend_world``, each run once."""
    root = tmp_path_factory.mktemp("trend")
    with pytest.MonkeyPatch.context() as patch:
        # The autouse block is per test; this module-wide run blocks the network itself.
        block_network(patch)
        market = load(root, trend_world())
        return {
            arm: replay(market, root, CellSpec(arm, CAPITAL, 1))
            for arm in ("v4_main", "hold_universe", "hold_btc")
        }


def fake_rows(
    first_ms: int,
    equities: Sequence[str | None],
    final: str,
    *,
    outcome: str = "complete",
    reason: str | None = None,
    residuals: Mapping[int, str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """A cell's records by hand, in the engine's ``hourly`` and ``outcome`` shapes: one hour
    from ``first_ms`` per entry of ``equities``, each that hour's open mark (None for an hour
    stopped before its open mark, which can only be the last), then the outcome."""
    rows: list[tuple[str, dict[str, Any]]] = []
    for index, equity in enumerate(equities):
        stamp = first_ms + index * HOUR
        hourly = {
            "open_ms": stamp,
            "open_equity": None if equity is None else D(equity),
            "complete": None if equity is None else True,
            "equity": D(final if equity is None else equity),
            "gross_notional": D(0),
            "gross": D(0),
            "margin_ratio": None,
            "equity_residual": D((residuals or {}).get(stamp, "0")),
        }
        rows.append(("hourly", hourly))
    last = first_ms + (len(equities) - 1) * HOUR
    at_2025 = [equity for index, equity in enumerate(equities) if first_ms + index * HOUR == T0]
    record: dict[str, Any] = {
        "outcome": outcome,
        "reason": reason,
        "stop_ms": None if outcome == "complete" else last,
        "hours": sum(equity is not None for equity in equities),
        "final_equity": D(final),
        "equity_2025": D(at_2025[0]) if at_2025 and at_2025[0] is not None else None,
        "final_after_close": D(final) if outcome == "complete" else None,
        "audit": {"wallet_residual": D(0), "equity_residual": D(0), "quantity_residuals": []},
    }
    if outcome != "complete":
        record["check"] = "adverse_extremes"
    rows.append(("outcome", record))
    return rows


def write_records(out: Path, rows: Sequence[tuple[str, Mapping[str, Any]]]) -> Receipt:
    """Write ``rows`` through the engine's ``RecordWriter`` into ``out``, with the receipt."""
    out.mkdir(parents=True)
    with RecordWriter(out / run.RECORDS_FILE) as writer:
        for kind, record in rows:
            writer.append(kind, record)
        receipt = writer.close()
    write_receipt(out / run.RECEIPT_FILE, receipt)
    return receipt


def fake_cell(
    out: Path,
    first_ms: int,
    equities: Sequence[str | None],
    final: str,
    **options: Any,
) -> run.CellResult:
    """``fake_rows`` written into ``out``, and the ``CellResult`` the engine would return."""
    rows = fake_rows(first_ms, equities, final, **options)
    receipt = write_records(out, rows)
    hourly = [record for kind, record in rows if kind == "hourly"]
    outcome = rows[-1][1]
    return run.CellResult(
        outcome["outcome"],
        outcome["reason"],
        outcome["stop_ms"],
        tuple(
            (h["open_ms"], h["open_equity"], True) for h in hourly if h["open_equity"] is not None
        ),
        outcome["final_equity"],
        outcome["equity_2025"],
        outcome["final_after_close"],
        Audit(D(0), {}, D(0)),
        receipt,
    )


# ---- the full summary -----------------------------------------------------------------------


def test_full_summary_has_every_field_with_exact_decimals(trend):
    """Spec "Reports": a complete cell's summary holds exactly the full summary's fields, every
    number a string of the exact Decimal, each one rebuilt here from the records."""
    cell = trend["v4_main"]
    result = cell.result
    assert result.outcome == "complete"
    built = cell.summary()

    assert set(built) == FULL_KEYS
    assert built["format"] == SUMMARY_FORMAT == "v4-summary-1"
    assert built["cell"] == cell_json(MAIN)
    assert (built["outcome"], built["reason"], built["stop_ms"]) == ("complete", None, None)
    final = result.final_equity
    assert built["initial_equity"] == "10000"
    assert built["final_equity"] == built["final_after_close"] == str(final)
    # The window opens at 2025-01-01 00:00, so equity at 2025-01-01 is the first open mark.
    assert built["equity_2025"] == str(result.equity_2025) == str(result.open_marks[0][1])
    assert F(D(built["compounded_return"])) == F(final) / CAPITAL - 1
    equities = [equity for _, equity, _ in result.open_marks] + [final]
    assert built["max_drawdown"] == str(maximum_drawdown(equities))
    worst = exact_drawdown(equities)
    assert worst > 0 and abs(F(D(built["max_drawdown"])) - worst) < F(1, 10**50)

    hourly = of_kind(cell.rows, "hourly")
    assert built["open_marks"] == [
        [ms, str(equity), flag] for ms, equity, flag in result.open_marks
    ]
    assert built["open_marks"] == [[h["open_ms"], h["open_equity"], h["complete"]] for h in hourly]
    assert len(built["open_marks"]) == hours_in("2025-01", "2025-01")
    assert all(flag is True for _, _, flag in built["open_marks"])  # bars every hour

    whole = span(T0, FEB, str(result.open_marks[0][1]), str(final))
    assert F(D(whole["return"])) == F(final) / F(result.open_marks[0][1]) - 1
    assert built["eras"] == [era("start-2020"), era("2021-2024"), era("2025-end", whole)]
    assert built["years"] == [year(2025, whole)]
    assert built["liquidations"] == 0
    largest = max(D(h["equity_residual"]).copy_abs() for h in hourly)
    assert D(built["accounting_residual"]) == largest
    receipt = (cell.out / run.RECEIPT_FILE).read_bytes()
    assert built["receipt_sha256"] == hashlib.sha256(receipt).hexdigest()

    # Exact JSON: no float anywhere, every number of the account a string of a finite Decimal.
    assert not any(isinstance(leaf, float) for leaf in leaves(built))
    for field in DECIMAL_FIELDS:
        assert type(built[field]) is str and D(built[field]).is_finite(), field
    assert json.loads(json.dumps(built)) == built
    verify_summary(built, cell.records, result.receipt)


def test_a_liquidated_cell_writes_a_full_summary_to_the_stop(monkeypatch, tmp_path):
    """Review Focus 5: a cell liquidated on 2024-12-10 still writes a full summary, up to the
    stop. A seeded BTCUSDT short of 10 at 100 on a 1,000 USDT cell; the coin is static (no daily
    bar, so no target) and its perpetual's bar at 10:00 has a high of 199. The adverse-extreme
    check there finds backing 1000 - 990 = 10 at or below maintenance 0.01 x 10 x 199 = 19.9.
    Equity at 2025-01-01 is null (the stop came earlier), and so is the equity after the
    window-end close; the final equity is the stop's mark, and the open marks run to the stop.
    The era and the year of the stop end at it; the later era is null."""
    crash = DEC + 9 * DAY + 10 * HOUR  # 2024-12-10 10:00
    hours = hours_in("2024-11", "2025-01")
    closes = path("100", (hours, "0"))
    btc = CoinSpec(
        "BTCUSDT",
        Series(NOV, closes, masked=static_mask(NOV, hours)),
        PerpetualSpec(
            series=Series(NOV, closes, extremes={crash: ("199", "100")}), funding_rate="0"
        ),
    )
    market = load(
        tmp_path, World("2025-01", (btc,), {"2024-12": ("BTCUSDT",), "2025-01": ("BTCUSDT",)})
    )
    seed(
        monkeypatch,
        DEC - HOUR,
        [("BTCUSDT", seed_fill(DEC - HOUR, "futures", "BTCUSDT", -1, "10", "100"))],
    )
    cell_spec = CellSpec("v4_main", 1000, 1)

    cell = replay(market, tmp_path / "out", cell_spec)
    built = cell.summary()

    result = cell.result
    assert result.outcome == "liquidated" and result.stop_ms == crash
    assert set(built) == FULL_KEYS
    assert built["cell"] == cell_json(cell_spec)
    assert (built["outcome"], built["reason"], built["stop_ms"]) == ("liquidated", None, crash)
    assert built["initial_equity"] == "1000"
    assert F(D(built["final_equity"])) == 10 and built["final_equity"] == str(result.final_equity)
    assert built["equity_2025"] is None and built["final_after_close"] is None
    assert built["liquidations"] == 1
    marks = built["open_marks"]
    assert [ms for ms, _, _ in marks] == list(range(DEC, crash + HOUR, HOUR))
    assert {F(D(equity)) for _, equity, _ in marks} == {F(1000)}
    assert all(flag is True for _, _, flag in marks)
    assert F(D(built["max_drawdown"])) == F(99, 100)
    assert F(D(built["compounded_return"])) == F(-99, 100)
    to_stop = span(DEC, crash, marks[0][1], built["final_equity"])
    assert F(D(to_stop["return"])) == F(-99, 100)
    assert built["eras"] == [era("start-2020"), era("2021-2024", to_stop), era("2025-end")]
    assert built["years"] == [year(2024, to_stop)]
    assert D(built["accounting_residual"]) == 0
    verify_summary(built, cell.records, result.receipt)
    assert "liquidated" in render_page(built)


FAILURES = {
    "wallet": {"wallet_residual": D("1E-40")},
    "quantity": {"quantity_residuals": {("spot", "BTCUSDT"): D("-1E-40")}},
    "equity": {"equity_residual": D("1.1E-18")},
}


@pytest.mark.parametrize("case", [*FAILURES, "engine_error"])
def test_failure_summaries_hold_the_failure_only(case, monkeypatch, tmp_path):
    """Spec "Reports": an ``accounting_failure`` summary holds the identity that failed, its
    hour and the values; an ``engine_error`` summary the exception's type and message and the
    hour. Nothing else: no equity, no marks, and no audit residuals for an engine error (a
    result's audit is a fresh ledger's zeros before the first one, so it would read as clean)."""
    if case == "engine_error":
        market = load(tmp_path, trend_world())
        calls: list[int] = []

        def failing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("injected")
            return size_book(*args, **kwargs)

        monkeypatch.setattr(run, "size_book", failing)
    else:
        market = load(tmp_path, flat_world())
        broken_audit(monkeypatch, FAILURES[case])

    cell = replay(market, tmp_path / "out", MAIN)
    built = cell.summary()

    outcome = cell.rows[-1][1]
    if case == "engine_error":
        assert cell.result.outcome == "engine_error"
        details: dict[str, Any] = {
            "type": "RuntimeError",
            "message": "injected",
            "hour_ms": T0 + 2 * DAY,
        }
        assert not any("residual" in key or "audit" in key for key in keys(built))
    else:
        assert cell.result.outcome == "accounting_failure" and cell.result.reason == case
        details = {"identity": case, "hour_ms": T0, "values": outcome["values"]}
        audit = cell.result.audit
        assert outcome["values"]["wallet_residual"] == str(audit.wallet_residual)
        assert outcome["values"]["equity_residual"] == str(audit.equity_residual)
    assert built == {
        "format": SUMMARY_FORMAT,
        "cell": cell_json(MAIN),
        "outcome": cell.result.outcome,
        **details,
    }
    verify_summary(built, cell.records, cell.result.receipt)
    page = render_page(built)
    assert cell.result.outcome in page and "<svg" not in page
    assert ("injected" if case == "engine_error" else case) in page


# ---- verification ---------------------------------------------------------------------------


def changed(summary: dict[str, Any], where: Sequence[str | int], value: object) -> dict[str, Any]:
    """A deep copy of ``summary`` with the value at ``where`` replaced."""
    copied = copy.deepcopy(summary)
    target: Any = copied
    for step in where[:-1]:
        target = target[step]
    target[where[-1]] = value
    return copied


def test_verify_summary_rebuilds_and_detects_a_changed_number(trend, tmp_path):
    """``verify_summary`` rebuilds the summary from the records and requires equality: a changed
    number, a missing or extra field, a summary of another cell, another receipt or a changed
    records file is a ValueError, naming the first field that differs."""
    cell = trend["v4_main"]
    built = cell.summary()
    receipt = cell.result.receipt
    verify_summary(built, cell.records, receipt)
    verify_summary(json.loads(json.dumps(built)), cell.records, receipt)  # as read back

    bump: Callable[[str], str] = lambda value: str(D(value) + D("1E-30"))  # noqa: E731
    cases: list[tuple[str, Sequence[str | int], object]] = [
        ("final_equity", ["final_equity"], bump(built["final_equity"])),
        ("compounded_return", ["compounded_return"], bump(built["compounded_return"])),
        ("max_drawdown", ["max_drawdown"], bump(built["max_drawdown"])),
        ("equity_2025", ["equity_2025"], None),
        ("initial_equity", ["initial_equity"], "10000.0"),
        (r"eras\[2\]\.return", ["eras", 2, "return"], bump(built["eras"][2]["return"])),
        (r"eras\[0\]\.start_ms", ["eras", 0, "start_ms"], T0),
        (r"years\[0\]\.end_equity", ["years", 0, "end_equity"], "1"),
        ("liquidations", ["liquidations"], 1),
        ("accounting_residual", ["accounting_residual"], "1E-19"),
        ("receipt_sha256", ["receipt_sha256"], "0" * 64),
        ("outcome", ["outcome"], "liquidated"),
        ("stop_ms", ["stop_ms"], T0),
    ]
    for name, where, value in cases:
        with pytest.raises(ValueError, match=name):
            verify_summary(changed(built, where, value), cell.records, receipt)
    missing = copy.deepcopy(built)
    del missing["years"]
    with pytest.raises(ValueError, match="years"):
        verify_summary(missing, cell.records, receipt)
    with pytest.raises(ValueError, match="extra"):
        verify_summary({**built, "extra": 1}, cell.records, receipt)
    with pytest.raises(ValueError, match="cell"):
        verify_summary(changed(built, ["cell", "capital"], 1000), cell.records, receipt)
    # Another cell's summary fails on its first number (the records do not name their cell),
    # and another cell's receipt is not the one next to these records.
    with pytest.raises(ValueError, match=r"summary field final_equity does not match"):
        verify_summary(trend["hold_btc"].summary(), cell.records, receipt)
    with pytest.raises(ValueError, match="receipt"):
        verify_summary(built, cell.records, trend["hold_btc"].result.receipt)
    # The receipt must also be the receipt.json next to the records.
    swapped = tmp_path / "swapped"
    shutil.copytree(cell.out, swapped)
    shutil.copyfile(trend["hold_btc"].out / run.RECEIPT_FILE, swapped / run.RECEIPT_FILE)
    with pytest.raises(ValueError, match="next to the records"):
        verify_summary(built, swapped / run.RECORDS_FILE, receipt)
    # A records file changed in one digit no longer matches its receipt.
    copied = tmp_path / "copied"
    shutil.copytree(cell.out, copied)
    raw = (copied / run.RECORDS_FILE).read_bytes()
    at = raw.index(b'"open_equity":"') + len(b'"open_equity":"')
    digit = b"2" if raw[at : at + 1] == b"1" else b"1"
    (copied / run.RECORDS_FILE).write_bytes(raw[:at] + digit + raw[at + 1 :])
    with pytest.raises(ValueError, match="SHA-256"):
        verify_summary(built, copied / run.RECORDS_FILE, receipt)


def test_verify_summary_detects_a_changed_open_mark(trend):
    """An open mark changed in its equity (even to an equal number spelled otherwise), its
    completeness flag (even to the integer 1) or its hour, or a row dropped, is named."""
    cell = trend["v4_main"]
    built = cell.summary()
    receipt = cell.result.receipt
    equity = built["open_marks"][100][1]
    respelled = equity + "0" if "." in equity else equity + ".0"
    assert D(respelled) == D(equity)
    for index, position, value in [
        (100, 1, str(D(equity) + D("1E-40"))),
        (100, 1, respelled),
        (5, 2, False),
        (5, 2, 1),
        (7, 0, built["open_marks"][7][0] + HOUR),
    ]:
        with pytest.raises(ValueError, match=rf"open_marks\[{index}\]\[{position}\]"):
            verify_summary(
                changed(built, ["open_marks", index, position], value), cell.records, receipt
            )
    dropped = copy.deepcopy(built)
    last = len(dropped["open_marks"]) - 1
    del dropped["open_marks"][-1]
    with pytest.raises(ValueError, match=rf"open_marks\[{last}\]"):
        verify_summary(dropped, cell.records, receipt)


def test_build_summary_cross_checks_the_cell_result(trend):
    """``build_summary`` takes every number from the records; a cell result that disagrees with
    them, or whose receipt is not the cell's ``receipt.json``, is a ValueError naming the field."""
    cell = trend["v4_main"]
    result = cell.result
    assert result.equity_2025 is not None and result.final_after_close is not None
    for name, change in [
        ("outcome", {"outcome": "liquidated"}),
        ("reason", {"reason": "ceiling"}),
        ("stop_ms", {"stop_ms": T0}),
        ("final_equity", {"final_equity": result.final_equity + 1}),
        ("equity_2025", {"equity_2025": result.equity_2025 + 1}),
        ("final_after_close", {"final_after_close": None}),
        ("open_marks", {"open_marks": result.open_marks[:-1]}),
    ]:
        with pytest.raises(ValueError, match=name):
            build_summary(cell.cell, replace(result, **change), cell.records)
    with pytest.raises(ValueError, match="receipt"):
        build_summary(
            cell.cell, replace(result, receipt=trend["hold_btc"].result.receipt), cell.records
        )


# ---- open marks, eras and years -------------------------------------------------------------


def test_open_marks_carry_the_completeness_flag(monkeypatch, tmp_path):
    """Spec "Reports": each open mark is flagged complete when every price source the arm uses
    then has that hour's bar. ETHUSDT's spot is masked from 00:00 to 04:59 every day and a
    seeded spot long holds it all month (no daily bar, so no target): those hours are carried
    marks and incomplete, every other hour complete."""
    hours = hours_in("2024-12", "2025-01")
    eth = CoinSpec(
        "ETHUSDT", Series(DEC, path("100", (hours, "0")), masked=static_mask(DEC, hours))
    )
    market = load(tmp_path, World("2025-01", (eth,), {"2025-01": ("ETHUSDT",)}))
    seed(
        monkeypatch,
        T0 - HOUR,
        [("ETHUSDT", seed_fill(T0 - HOUR, "spot", "ETHUSDT", 1, "10", "100"))],
    )

    cell = replay(market, tmp_path / "out", MAIN)
    built = cell.summary()

    assert cell.result.outcome == "complete"
    marks = built["open_marks"]
    assert [(ms, flag) for ms, _, flag in marks] == [
        (ms, ms % DAY >= 5 * HOUR) for ms in range(T0, FEB, HOUR)
    ]
    assert sum(flag is False for _, _, flag in marks) == 31 * 5
    assert all(type(ms) is int and type(e) is str and type(flag) is bool for ms, e, flag in marks)
    assert marks == [
        [h["open_ms"], h["open_equity"], h["complete"]] for h in of_kind(cell.rows, "hourly")
    ]
    assert {F(D(equity)) for _, equity, _ in marks} == {F(CAPITAL)}  # 9,000 cash and 10 x 100
    verify_summary(built, cell.records, cell.result.receipt)


def test_eras_and_years_split_at_their_boundaries(tmp_path):
    """The eras run from the window start to 2020-12-31, 2021-01-01 to 2024-12-31 and 2025-01-01
    to the end, the years by calendar year. Each starts at the open mark of its first hour and
    ends at the next one's first open mark (00:00 on 2021-01-01 or 2025-01-01, or a new year),
    the last at the final equity, at the window's end. Hand-written records from 2020-12-31
    22:00 to 2025-01-01 01:00, with one dip and two small equity residuals."""
    first, last = Y2021 - 2 * HOUR, T0 + HOUR
    hours = (last - first) // HOUR + 1
    equities = [f"{1000 + index}.25" for index in range(hours)]
    equities[100] = "500.5"
    final = "50000.75"
    residuals = {first + 5 * HOUR: "-3E-19", first + 7 * HOUR: "2E-19"}
    cell_spec = CellSpec("v4_main", 1000, 1)
    result = fake_cell(tmp_path / "cell", first, equities, final, residuals=residuals)
    records = tmp_path / "cell" / run.RECORDS_FILE

    built = build_summary(cell_spec, result, records)

    def at(ms: int) -> str:
        return equities[(ms - first) // HOUR]

    end = last + HOUR
    assert built["eras"] == [
        era("start-2020", span(first, Y2021, at(first), at(Y2021))),
        era("2021-2024", span(Y2021, T0, at(Y2021), at(T0))),
        era("2025-end", span(T0, end, at(T0), final)),
    ]
    starts = {number: month_start(f"{number}-01") for number in range(2021, 2026)}
    assert built["years"] == [
        year(2020, span(first, starts[2021], at(first), at(starts[2021]))),
        *(
            year(n, span(starts[n], starts[n + 1], at(starts[n]), at(starts[n + 1])))
            for n in range(2021, 2025)
        ),
        year(2025, span(T0, end, at(T0), final)),
    ]
    for period in [*built["eras"], *built["years"]]:
        exact = F(D(period["end_equity"])) / F(D(period["start_equity"])) - 1
        assert abs(F(D(period["return"])) - exact) < F(1, 10**55)
    assert built["equity_2025"] == at(T0) and built["final_after_close"] == final
    assert F(D(built["compounded_return"])) == F(D(final)) / 1000 - 1
    path_ = [D(e) for e in equities] + [D(final)]
    assert built["max_drawdown"] == str(maximum_drawdown(path_))
    assert abs(F(D(built["max_drawdown"])) - exact_drawdown(path_)) < F(1, 10**55)
    assert built["accounting_residual"] == "3E-19"
    assert len(built["open_marks"]) == hours
    verify_summary(built, records, result.receipt)


@pytest.mark.parametrize(
    "case",
    ["liquidated in 2024", "ceiling in 2024", "liquidated in 2025", "stopped before 2025's mark"],
)
def test_a_stop_ends_its_era_and_year_and_nulls_the_later_ones(case, tmp_path):
    """Spec "Safety" and "Reports": the era (and year) holding a stop ends at the stop's final
    equity; one the cell never reached, or one wholly after the stop, is null.
    * in 2024: era 2 ends at the stop, era 3 is null, equity at 2025-01-01 is null;
    * in 2025: era 2 ends at the 2025-01-01 open mark, and era 3 runs from it to the stop;
    * a stop at 2025-01-01 00:00 before its open mark (a synthetic close batch): era 2 and 2024
      end at the stop, and era 3 and 2025, which never had an open mark, are null."""
    outcome, reason = (
        ("limit_unrestorable", "ceiling")
        if case.startswith("ceiling")
        else (
            "liquidated",
            None,
        )
    )
    if case.endswith("in 2024"):
        first, equities, final = T0 - 4 * HOUR, ["1000", "990", "980"], "400"
    elif case == "liquidated in 2025":
        first, equities, final = T0 - 2 * HOUR, ["1000", "1010", "1020", "1030", "1040"], "700"
    else:
        first, equities, final = T0 - 2 * HOUR, ["1000", "1010", None], "300"
    stop = first + (len(equities) - 1) * HOUR
    result = fake_cell(tmp_path / "cell", first, equities, final, outcome=outcome, reason=reason)
    records = tmp_path / "cell" / run.RECORDS_FILE

    built = build_summary(CellSpec("v4_main", 1000, 1), result, records)

    assert set(built) == FULL_KEYS
    assert (built["outcome"], built["reason"], built["stop_ms"]) == (outcome, reason, stop)
    assert built["liquidations"] == (1 if outcome == "liquidated" else 0)
    assert built["final_equity"] == final and built["final_after_close"] is None
    if case == "liquidated in 2025":
        before, after = span(first, T0, "1000", "1020"), span(T0, stop, "1020", final)
        assert built["eras"] == [
            era("start-2020"),
            era("2021-2024", before),
            era("2025-end", after),
        ]
        assert built["years"] == [year(2024, before), year(2025, after)]
        assert built["equity_2025"] == "1020"
    else:
        to_stop = span(first, stop, "1000", final)
        assert built["eras"] == [era("start-2020"), era("2021-2024", to_stop), era("2025-end")]
        expected_years = [year(2024, to_stop)]
        if stop == T0:
            expected_years.append(year(2025))  # simulated, but it never had an open mark
        assert built["years"] == expected_years
        assert built["equity_2025"] is None
    marks = [e for e in equities if e is not None]
    assert [row[1] for row in built["open_marks"]] == marks
    assert built["max_drawdown"] == str(maximum_drawdown([D(e) for e in [*marks, final]]))
    verify_summary(built, records, result.receipt)


def corrupt_open_equity(rows: Rows) -> None:
    rows[1][1]["open_equity"] = "1e3"  # 1000, but not as str(Decimal) spells it


def corrupt_gap(rows: Rows) -> None:
    del rows[2]


def corrupt_null_mark(rows: Rows) -> None:
    rows[1][1].update(open_equity=None, complete=None)


def corrupt_complete_without_mark(rows: Rows) -> None:
    rows[3][1].update(open_equity=None, complete=None)
    rows[-1][1]["hours"] -= 1


def corrupt_after_outcome(rows: Rows) -> None:
    rows.append(("event", {"type": "late", "hour_ms": T0, "coin": None}))


def corrupt_no_outcome(rows: Rows) -> None:
    del rows[-1]


def corrupt_hours(rows: Rows) -> None:
    rows[-1][1]["hours"] += 1


def corrupt_equity_2025(rows: Rows) -> None:
    rows[-1][1]["equity_2025"] = D("1")


def corrupt_after_close(rows: Rows) -> None:
    rows[-1][1]["final_after_close"] = None


def corrupt_stop(rows: Rows) -> None:
    rows[-1][1].update(outcome="liquidated", stop_ms=T0, final_after_close=None)


def corrupt_outcome(rows: Rows) -> None:
    rows[-1][1]["outcome"] = "finished"


@pytest.mark.parametrize(
    ("corrupt", "message"),
    [
        (corrupt_open_equity, "as the records write it"),
        (corrupt_gap, "not the hour after"),
        (corrupt_null_mark, "without an open mark is not last"),
        (corrupt_complete_without_mark, "every hour of a complete cell has an open mark"),
        (corrupt_after_outcome, "follows the outcome record"),
        (corrupt_no_outcome, "no outcome record"),
        (corrupt_hours, "hours is not the"),
        (corrupt_equity_2025, "equity_2025 is not the 2025-01-01 open mark"),
        (corrupt_after_close, "after the close"),
        (corrupt_stop, "is not the last hour"),
        (corrupt_outcome, "unknown outcome"),
    ],
)
def test_records_the_engine_would_not_write_are_refused(corrupt, message, tmp_path):
    """The rebuild reads only what the engine writes: consecutive hours, an open mark on every
    hour but a stop's last, Decimals spelled as ``str`` spells them, one outcome record last, and
    an outcome that agrees with the hourly records. Anything else is a ValueError, before any
    comparison."""
    rows = fake_rows(T0 - 2 * HOUR, ["1000", "1010", "1020", "1030"], "1040")
    corrupt(rows)
    receipt = write_records(tmp_path / "cell", rows)
    stub = {"format": SUMMARY_FORMAT, "cell": cell_json(CellSpec("v4_main", 1000, 1))}
    with pytest.raises(ValueError, match=message):
        verify_summary(stub, tmp_path / "cell" / run.RECORDS_FILE, receipt)


# ---- the page and the files -----------------------------------------------------------------


def test_page_has_no_script_and_states_promising_not_proven(trend):
    """The page is self-contained HTML with no script and nothing fetched: the outcome, the
    headline numbers, the eras, the years and the equity path as an inline SVG, and the plain
    statement that only the third era was unseen when V4 was designed, so a pass means
    "promising", not "proven"."""
    built = trend["v4_main"].summary()
    page = render_page(built)

    assert page == render_page(copy.deepcopy(built))
    assert page.lower().startswith("<!doctype html>")
    lowered = page.lower()
    for token in FORBIDDEN:
        assert token not in lowered, token
    assert re.search(r"\son[a-z]+\s*=", lowered) is None  # no event handlers
    assert "promising, not proven" in page and "only the third era" in lowered
    assert "complete" in page and MAIN.cell_id in page
    for name in ERA_NAMES:
        assert name in page
    assert "2025" in page and page.count("<table") >= 3
    assert page.count("<svg") == 1 and page.count("<polyline") == 1


def test_the_page_escapes_every_text_value(trend):
    """Every text value on the page is escaped, so a message holding markup shows as text."""
    message = '<script>alert("x")</script> & <b>'
    failure = {
        "format": SUMMARY_FORMAT,
        "cell": cell_json(MAIN),
        "outcome": "engine_error",
        "type": "ValueError<i>",
        "message": message,
        "hour_ms": T0,
    }
    page = render_page(failure)
    assert "<script" not in page.lower() and "<b>" not in page and "<i>" not in page
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; &lt;b&gt;" in page
    assert "ValueError&lt;i&gt;" in page and "2025-01-01 00:00 UTC" in page
    assert "promising, not proven" in page


def test_the_sparkline_draws_about_1000_points_of_70000_deterministically(trend):
    """A real cell has about 70,000 open marks; the sparkline draws about 1,000 of them, the
    same ones every time, from the first to the last."""
    built = copy.deepcopy(trend["v4_main"].summary())
    built["open_marks"] = [
        [T0 + index * HOUR, str(10000 + index % 977), index % 13 != 0] for index in range(70000)
    ]
    built["open_marks"][0][1] = "99999"  # the only high: the first point drawn
    built["final_equity"] = "1"  # the only low: the last point drawn
    page = render_page(built)

    assert page == render_page(copy.deepcopy(built))
    (points,) = re.findall(r'points="([^"]*)"', page)
    pairs = [pair.split(",") for pair in points.split()]
    assert 900 <= len(pairs) <= 1001
    xs = [D(x) for x, _ in pairs]
    assert xs == sorted(xs) and len(set(xs)) == len(xs)
    assert all(D(y).is_finite() for _, y in pairs)
    (width,) = re.findall(r'viewBox="0 0 ([0-9]+) [0-9]+"', page)
    assert xs[0] == 0 and xs[-1] == D(width)
    ys = [D(y) for _, y in pairs]  # SVG's y grows downwards
    assert ys.count(min(ys)) == 1 and ys[0] == min(ys)  # the first open mark is drawn
    assert ys.count(max(ys)) == 1 and ys[-1] == max(ys)  # and so is the final equity


def test_hold_cells_build_the_same_summary_shape(trend):
    """Controller ruling P4: a hold cell's summary has the same keys and value shapes as a V4
    cell's, and verifies the same way."""
    shapes = {arm: shape(cell.summary()) for arm, cell in trend.items()}
    assert shapes["hold_universe"] == shapes["v4_main"]
    assert shapes["hold_btc"] == shapes["v4_main"]
    for cell in trend.values():
        built = cell.summary()
        assert built["outcome"] == "complete" and built["cell"] == cell_json(cell.cell)
        verify_summary(built, cell.records, cell.result.receipt)


def test_write_cell_outputs_writes_both_files_once_and_returns_the_summary_sha256(trend, tmp_path):
    """``summary.json`` holds the summary's canonical JSON (sorted keys, no spaces, ASCII), so its
    bytes and SHA-256 are deterministic; ``report.html`` holds the page. Both are created
    exclusively: an existing file of either name is refused and nothing is written."""
    built = trend["v4_main"].summary()
    page = render_page(built)
    out = tmp_path / "cell"

    digest = write_cell_outputs(out, built, page)

    raw = (out / "summary.json").read_bytes()
    assert (
        raw == json.dumps(built, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    )
    assert digest == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == built
    assert (out / "report.html").read_bytes() == page.encode("utf-8")
    assert write_cell_outputs(tmp_path / "again", copy.deepcopy(built), page) == digest
    before = {item.name: item.read_bytes() for item in out.iterdir()}
    with pytest.raises(ValueError, match="already exists"):
        write_cell_outputs(out, built, page)
    assert {item.name: item.read_bytes() for item in out.iterdir()} == before
    for name in ("summary.json", "report.html"):
        alone = tmp_path / f"only-{name}"
        alone.mkdir()
        (alone / name).write_bytes(b"x")
        with pytest.raises(ValueError, match="already exists"):
            write_cell_outputs(alone, built, page)
        assert [item.name for item in alone.iterdir()] == [name]
    with pytest.raises(ValueError, match="summary"):
        write_cell_outputs(tmp_path / "not-a-summary", {"format": "other"}, page)


def test_summary_imports_only_what_the_constraints_allow():
    """Constraints, frozen code and imports: summary.py imports the V4 engine's own modules,
    ``trend.metrics.maximum_drawdown``, ``combined.artifacts`` and ``backtest.klines`` only."""
    tree = ast.parse(Path(summary_module.__file__).read_text(encoding="utf-8"))
    imported = {
        (node.module, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert not any(
        isinstance(node, ast.Import) and "crypto_grid_bot" in ast.dump(node)
        for node in ast.walk(tree)
    )
    ours = {(module, name) for module, name in imported if module.startswith("crypto_grid_bot.")}
    allowed = {
        ("crypto_grid_bot.trend.metrics", "maximum_drawdown"),
        ("crypto_grid_bot.combined.artifacts", "_canonical"),
        ("crypto_grid_bot.combined.artifacts", "_digest"),
        ("crypto_grid_bot.backtest.klines", "month_bounds_ms"),
    }
    assert ours and all(
        module.startswith("crypto_grid_bot.v4.engine.") or (module, name) in allowed
        for module, name in ours
    )
    assert ("crypto_grid_bot.trend.metrics", "maximum_drawdown") in ours
