"""V4 engine task 12: the hour loop of the V4 arms (part 12a: the loop, the open marks, the
records, the 00:00 decisions, the audit and the error paths).

Each test replays a small synthetic world from ``tests/v4_synthetic.py`` through
``run_v4_cell``. Part 12a books no fills yet, so a position exists only where a test seeds one:
``seed`` books fills into the cell's ledger and opens their lifecycles before the first hour,
through the module's ``Ledger`` and ``Lifecycles`` names. A seeded test checks only hours and
records that later parts' fills cannot change (an open mark comes before the hour's fills, and a
daily record is the decision's, not the fill's).

Expected signals and weights are recomputed here the plain way: one ``CoinSignals`` pass over
the market's daily bars, and ``size_book`` on each coin's whole return series. So the engine's
lazy feeding and trailing return slices are checked against the straightforward computation.
The network is blocked for every test (the autouse fixture) and no real pack is read.
"""

from __future__ import annotations

import ast
import dataclasses
import socket
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from decimal import Decimal
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
    day_hours,
    every_month,
    hours_in,
    month_start,
    path,
    repack,
    write_world,
)

from crypto_grid_bot.v4.data.pack import coin_pack_file
from crypto_grid_bot.v4.engine import run
from crypto_grid_bot.v4.engine.arms import ARMS, ArmSpec, CellSpec
from crypto_grid_bot.v4.engine.ledger import Fill, Ledger
from crypto_grid_bot.v4.engine.lifecycle import Lifecycles
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.numbers import to_decimal
from crypto_grid_bot.v4.engine.pending import PendingBook
from crypto_grid_bot.v4.engine.records import read_receipt, read_records
from crypto_grid_bot.v4.engine.signals import CoinSignals, SignalReading
from crypto_grid_bot.v4.engine.sizing import SizingResult, daily_returns, size_book

D = Decimal
T0 = month_start("2025-01")  # 2025-01-01 00:00 UTC
CAPITAL = 10000
MAIN = CellSpec("v4_main", CAPITAL, 1)


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


# ---- helpers ------------------------------------------------------------------------------


def text(value: Decimal | None) -> str | None:
    """A Decimal as the records write it (``str``), None as null."""
    return None if value is None else str(value)


def cell_run(
    market: Market, tmp_path: Path, cell: CellSpec = MAIN, name: str = "cell"
) -> tuple[run.CellResult, list[tuple[str, dict[str, Any]]]]:
    """Run one cell into ``tmp_path / "out" / name`` and read its records back, verified."""
    out = tmp_path / "out" / name
    result = run.run_v4_cell(market, cell, out)
    assert read_receipt(out / run.RECEIPT_FILE) == result.receipt
    rows = list(read_records(out / run.RECORDS_FILE, result.receipt))
    return result, rows


def of_kind(rows: Iterable[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [record for name, record in rows if name == kind]


def daily_by(rows: Iterable[tuple[str, dict[str, Any]]]) -> dict[tuple[int, str], dict[str, Any]]:
    """The ``daily_coin`` records keyed by (decision hour, coin)."""
    return {(r["decision_ms"], r["coin"]): r for r in of_kind(rows, "daily_coin")}


def load(tmp_path: Path, world: World, name: str = "world") -> Market:
    return Market.load(write_world(tmp_path / name, world))


def seed(monkeypatch, at_ms: int, fills: Sequence[tuple[str, Fill]]) -> None:
    """Make every cell start with ``fills`` (each with its coin) booked at ``at_ms``.

    The cell builds its ledger and its lifecycles through ``run.Ledger`` and ``run.Lifecycles``
    (in that order); these stand-ins book the fills into the ledger and open each coin's
    lifecycle on them, so the open marks and the lifecycles agree with the ledger."""
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


def readings_by_day(market: Market, coin: str, arm: ArmSpec) -> dict[int, SignalReading]:
    """The coin's reading after each of its daily bars, from one plain pass."""
    assert arm.lookbacks is not None
    signals = CoinSignals(arm.lookbacks)
    return {bar.open_ms: signals.update(bar) for bar in market.daily(coin)}


def latest(readings: dict[int, SignalReading], day: int) -> SignalReading | None:
    days = [stamp for stamp in readings if stamp <= day]
    return readings[max(days)] if days else None


def expected_book(
    market: Market,
    arm: ArmSpec,
    decision_ms: int,
    coins: Sequence[str],
    readings: dict[str, dict[int, SignalReading]],
    eligible: Callable[[str, int], bool],
) -> SizingResult:
    """``size_book`` on the plain inputs: each coin's latest reading (its signal used as the spec
    says) and its whole return series."""
    day = decision_ms - DAY
    book: dict[str, Decimal] = {}
    for coin in coins:
        reading = latest(readings[coin], day)
        s = D(0) if reading is None else (reading.s_long_only if arm.long_only else reading.s)
        book[coin] = s if eligible(coin, decision_ms) else max(s, D(0))
    returns = {coin: daily_returns(market.daily(coin)) for coin in coins}
    assert arm.vol_target is not None
    return size_book(book, returns, day, vol_target=arm.vol_target)


def check_reading(record: dict[str, Any], reading: SignalReading | None) -> None:
    """The record's signal fields are exactly the reading's."""
    if reading is None:
        assert record["reading_day_ms"] is None
        assert record["speeds"] is None and record["downtrend"] is None
        assert record["L"] is None and record["S"] is None and record["s"] is None
        return
    assert record["reading_day_ms"] == reading.day_ms
    assert record["close"] == text(reading.close)
    assert record["speeds"] == {
        "fast": {"sma": text(reading.sma_fast), "vote": reading.fast},
        "medium": {
            "ema_fast": text(reading.ema_fast),
            "ema_slow": text(reading.ema_slow),
            "donchian": reading.donchian,
            "vote": reading.medium,
        },
        "slow": {"sma": text(reading.sma_slow), "vote": reading.slow},
    }
    assert record["downtrend"] == {
        "confirmed": reading.downtrend,
        "close_below_sma": [text(reading.close), text(reading.sma_trend)],
        "sma_falling": [text(reading.sma_trend), text(reading.sma_trend_lagged)],
        "lower_highs": [text(reading.high_recent), text(reading.high_prior)],
        "lower_lows": [text(reading.low_recent), text(reading.low_prior)],
    }
    assert (record["L"], record["S"], record["s"], record["s_long_only"]) == (
        text(reading.L),
        text(reading.S),
        text(reading.s),
        text(reading.s_long_only),
    )


def check_sizing(record: dict[str, Any], sizing: SizingResult) -> None:
    coin = sizing.coins[record["coin"]]
    assert record["sigma"] == text(coin.sigma)
    assert (record["raw"], record["full"], record["scaled"]) == (
        text(coin.raw),
        text(coin.full),
        text(coin.scaled),
    )
    assert record["after_coin_cap"] == text(coin.after_coin_cap)
    assert record["after_total_cap"] == text(coin.after_total_cap)
    assert record["scale"] == text(sizing.scale)
    assert record["common_days"] == sizing.common_days
    assert record["flat_reason"] == sizing.flat_reason


# ---- worlds -------------------------------------------------------------------------------


def trend_world(
    *, eth_masked: Sequence[int] = (), start: str = "2024-10", end: str = "2025-01"
) -> World:
    """BTCUSDT rising, with its perpetual, and ETHUSDT falling, spot only, from ``start`` (the
    history) to ``end``; both selected every month from 2025-01 on."""
    hours = hours_in(start, end)
    btc = CoinSpec(
        "BTCUSDT",
        Series(month_start(start), path("50000", (hours, "0.0003"), noise="0.003", seed=1)),
        perpetual=PerpetualSpec(),
    )
    eth = CoinSpec(
        "ETHUSDT",
        Series(
            month_start(start),
            path("2000", (hours, "-0.0003"), noise="0.003", seed=2),
            masked=tuple(eth_masked),
        ),
    )
    return World(end, (btc, eth), every_month("2025-01", end, ("BTCUSDT", "ETHUSDT")))


def flat_world(first: str = "2025-01", end: str = "2025-01", history: str | None = None) -> World:
    """BTCUSDT at a flat 100 (sigma 0, so no weight ever), spot only, selected from ``first``."""
    start = history or first
    btc = CoinSpec("BTCUSDT", Series(month_start(start), ("100",) * hours_in(start, end)))
    return World(end, (btc,), every_month(first, end, ("BTCUSDT",)))


# ---- the loop and its records -------------------------------------------------------------


def test_an_empty_universe_month_holds_cash_and_trades_nothing(tmp_path):
    """Review Focus 4: a first month whose coins cannot size yet (fewer than 60 returns), one of
    them without a perpetual, then a month with an empty universe. Every target is 0 or absent,
    nothing divides by zero, nothing trades, and the account holds its cash to the end."""
    hours = hours_in("2025-01", "2025-02")
    btc = CoinSpec("BTCUSDT", Series(T0, path("100", (hours, "0.0005"), noise="0.004", seed=3)))
    eth = CoinSpec(
        "ETHUSDT",
        Series(T0, path("50", (hours, "-0.0005"), noise="0.004", seed=4)),
        perpetual=PerpetualSpec(),
    )
    universes = {"2025-01": ("ETHUSDT", "BTCUSDT"), "2025-02": ()}
    market = load(tmp_path, World("2025-02", (btc, eth), universes))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and result.reason is None and result.stop_ms is None
    assert [stamp for stamp, _, _ in result.open_marks] == list(
        range(T0, month_start("2025-03"), HOUR)
    )
    assert {(equity, complete) for _, equity, complete in result.open_marks} == {(D(CAPITAL), True)}
    assert result.final_equity == result.final_after_close == D(CAPITAL)
    assert result.equity_2025 == D(CAPITAL)  # the window opens at 2025-01-01 00:00
    assert result.audit.wallet_residual == 0 and result.audit.equity_residual == 0
    assert of_kind(rows, "fill") == [] and of_kind(rows, "funding") == []
    assert of_kind(rows, "lifecycle") == []

    monthly = of_kind(rows, "monthly")
    assert [m["month"] for m in monthly] == ["2025-01", "2025-02"]
    assert monthly[0]["universe"] == ["ETHUSDT", "BTCUSDT"]  # rank order, as selected
    assert monthly[0]["entered"] == ["ETHUSDT", "BTCUSDT"] and monthly[0]["left"] == []
    assert monthly[1]["universe"] == [] and monthly[1]["entered"] == []
    assert monthly[1]["left"] == ["ETHUSDT", "BTCUSDT"] and monthly[1]["perpetuals"] == []

    daily = of_kind(rows, "daily_coin")
    january = [r for r in daily if r["decision_ms"] < month_start("2025-02")]
    assert {r["decision_ms"] for r in january} == set(range(T0, month_start("2025-02"), DAY))
    assert all(r["target"] in ("0", None) for r in daily)
    # Fewer than 60 returns: no sigma, so the book is flat and nothing is sized.
    assert all(r["sigma"] is None and r["flat_reason"] == "no_nonzero_raw_weights" for r in january)
    # BTCUSDT has no perpetual: spot-only and long-only, so its signal is never negative.
    assert all(not r["eligible"] and D(r["signal"]) >= 0 for r in january if r["coin"] == "BTCUSDT")
    # The empty month decides only the two coins leaving, once, on its first day, with target 0.
    february = [r for r in daily if r["decision_ms"] >= month_start("2025-02")]
    assert [(r["decision_ms"], r["coin"]) for r in february] == [
        (month_start("2025-02"), "BTCUSDT"),
        (month_start("2025-02"), "ETHUSDT"),
    ]
    assert all(r["universe_exit"] and r["target"] == "0" and r["signal"] == "0" for r in february)

    hourly = of_kind(rows, "hourly")
    assert len(hourly) == len(result.open_marks)
    assert all(h["margin_ratio"] is None and D(h["gross"]) == 0 for h in hourly)  # null: +inf
    assert rows[-1][0] == "outcome" and rows[-1][1]["outcome"] == "complete"


def test_the_engine_never_calls_a_2024_guard_on_2026_data(monkeypatch, tmp_path):
    calls: list[str] = []

    def spy(month: str) -> str:
        calls.append(month)
        return month

    monkeypatch.setattr("crypto_grid_bot.backtest.klines.development_month", spy)
    monkeypatch.setattr("crypto_grid_bot.backtest.window.development_month", spy)
    for name, module in list(sys.modules.items()):  # every other module that imported it
        if name.startswith("crypto_grid_bot.") and hasattr(module, "development_month"):
            monkeypatch.setattr(module, "development_month", spy)
    hours = hours_in("2026-03", "2026-07")
    btc = CoinSpec(
        "BTCUSDT",
        Series(month_start("2026-03"), path("90000", (hours, "0.0003"), noise="0.003", seed=5)),
        perpetual=PerpetualSpec(),
    )
    market = load(
        tmp_path, World("2026-07", (btc,), every_month("2026-06", "2026-07", ("BTCUSDT",)))
    )

    result, rows = cell_run(market, tmp_path)

    assert calls == []  # no name of the 2024 guard was ever called
    assert result.outcome == "complete"
    assert result.open_marks[0][0] == month_start("2026-06")
    assert result.equity_2025 is None  # the window opens after 2025-01-01 00:00
    assert any(r["target"] not in (None, "0") for r in of_kind(rows, "daily_coin"))
    # run.py imports none of the guarded modules (constraints: frozen code and imports).
    tree = ast.parse(Path(run.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    guarded = {
        "crypto_grid_bot.trend.signals",
        "crypto_grid_bot.trend.pending",
        "crypto_grid_bot.trend.account",
        "crypto_grid_bot.trend.execution",
        "crypto_grid_bot.combined.engine",
        "crypto_grid_bot.combined.account",
    }
    assert not imported & guarded
    from_sizing = {
        a.name
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module == "crypto_grid_bot.trend.sizing"
        for a in n.names
    }
    assert from_sizing <= {"DailyReturn"}


@pytest.mark.parametrize("arm", ["v4_main", "v4_long_only", "v4_vol60", "v4_slower"])
def test_daily_records_carry_the_signals_and_the_sizing(arm, tmp_path):
    """Every decision's record holds the plain computation's reading, signal and weights, under
    the arm's own lookbacks, volatility target and signal (s, or L for long-only). ETHUSDT has
    no perpetual, so its signal is max(s, 0); its masked day exercises the no-bar rule too."""
    masked = day_hours(month_start("2025-01") + 9 * DAY, range(6))  # 2025-01-10: 18 hours left
    market = load(tmp_path, trend_world(eth_masked=masked))
    spec = ARMS[arm]

    _, rows = cell_run(market, tmp_path, CellSpec(arm, CAPITAL, 1))

    coins = ("BTCUSDT", "ETHUSDT")
    readings = {coin: readings_by_day(market, coin, spec) for coin in coins}
    daily = daily_by(rows)
    decisions = sorted({stamp for stamp, _ in daily})
    assert decisions == list(range(T0, month_start("2025-02"), DAY))
    negative_eth = 0
    for h in decisions:
        sizing = expected_book(market, spec, h, coins, readings, market.perpetual_eligible)
        for coin in coins:
            record = daily[(h, coin)]
            reading = latest(readings[coin], h - DAY)
            check_reading(record, reading)
            check_sizing(record, sizing)
            no_bar = reading is None or reading.day_ms != h - DAY
            assert record["no_bar"] is no_bar
            assert record["in_universe"] and not record["universe_exit"]
            assert record["eligible"] is market.perpetual_eligible(coin, h)
            assert record["perpetual"] == ("BTCUSDT" if coin == "BTCUSDT" else None)
            s = reading.s_long_only if spec.long_only else reading.s
            assert record["signal"] == text(s if record["eligible"] else max(s, D(0)))
            if no_bar:
                assert record["target"] is None and record["no_target"] == "no_bar"
            else:
                assert record["target"] == text(sizing.weights[coin])
                assert record["no_target"] is None
            negative_eth += coin == "ETHUSDT" and reading.s < 0
    assert negative_eth > 0  # the spot-only clamp max(s, 0) was exercised
    assert any(r["target"] not in (None, "0") for r in daily.values())


def test_a_coin_without_a_daily_bar_keeps_its_signal_and_takes_no_target(monkeypatch, tmp_path):
    """Spec "Signals", no-bar rule: after 2025-01-10, a day without a daily bar for ETHUSDT, the
    decision keeps ETHUSDT's reading of 2025-01-09 and gives it no target (it is absent from the
    targets the pending book receives), while BTCUSDT is decided with ETHUSDT's previous signal
    and its returns as they are."""
    day10 = T0 + 9 * DAY
    market = load(tmp_path, trend_world(eth_masked=day_hours(day10, range(6))))
    seen: list[tuple[int, dict[str, Decimal]]] = []

    class SpyBook(PendingBook):
        def decide(self, decision_ms, targets):
            seen.append((decision_ms, dict(targets)))
            return super().decide(decision_ms, targets)

    monkeypatch.setattr(run, "PendingBook", SpyBook)
    _, rows = cell_run(market, tmp_path)

    targets = dict(seen)
    after, before, later = day10 + DAY, day10, day10 + 2 * DAY
    assert set(targets[after]) == {"BTCUSDT"}
    assert set(targets[before]) == set(targets[later]) == {"BTCUSDT", "ETHUSDT"}
    daily = daily_by(rows)
    kept, fresh = daily[(after, "ETHUSDT")], daily[(before, "ETHUSDT")]
    assert kept["no_bar"] and kept["target"] is None and kept["no_target"] == "no_bar"
    assert kept["reading_day_ms"] == fresh["reading_day_ms"] == day10 - DAY
    for field in ("speeds", "downtrend", "L", "S", "s", "signal"):
        assert kept[field] == fresh[field]
    assert daily[(later, "ETHUSDT")]["reading_day_ms"] == day10 + DAY
    # BTCUSDT's weight at `after`: the book holds ETHUSDT's kept signal, and ETHUSDT's returns
    # lack 2025-01-10 and 2025-01-11 (no return spans a missing day).
    coins = ("BTCUSDT", "ETHUSDT")
    readings = {coin: readings_by_day(market, coin, ARMS["v4_main"]) for coin in coins}
    sizing = expected_book(
        market, ARMS["v4_main"], after, coins, readings, market.perpetual_eligible
    )
    assert targets[after]["BTCUSDT"] == sizing.weights["BTCUSDT"]
    assert daily[(after, "BTCUSDT")]["target"] == text(sizing.weights["BTCUSDT"])


@pytest.mark.parametrize("status", ["missing_slot", None])
def test_the_last_day_before_an_incomplete_funding_month_bars_the_perpetual(status, tmp_path):
    """Spec "Data": no futures exposure is held in an incomplete funding month (a missing status
    counts as incomplete). The decision at 00:00 of the previous month's last day already has no
    eligible perpetual, so its signal is max(s, 0); the month itself has none (point in time),
    and futures return from the first decision whose fill falls after it. The window's last
    month has no next month to judge: the window end closes everything."""
    hours = hours_in("2024-10", "2025-03")
    months = {} if status is None else {"2025-02": status}
    btc = CoinSpec(
        "BTCUSDT",
        Series(month_start("2024-10"), path("50000", (hours, "-0.0003"), noise="0.003", seed=6)),
        perpetual=PerpetualSpec(months=months),
    )
    world = World("2025-03", (btc,), every_month("2025-01", "2025-03", ("BTCUSDT",)))
    data_dir = write_world(tmp_path / "world", world)
    if status is None:

        def drop_february(document: dict[str, Any]) -> None:
            del document["funding_months"]["2025-02"]

        repack(data_dir, coin_pack_file("BTCUSDT"), drop_february)
    market = Market.load(data_dir)
    assert market.funding_month("BTCUSDT", "2025-02") == status

    _, rows = cell_run(market, tmp_path)

    daily = daily_by(rows)
    feb, mar = month_start("2025-02"), month_start("2025-03")
    last_jan, last_feb, last_mar = feb - DAY, mar - DAY, month_start("2025-04") - DAY

    def row(h: int) -> dict[str, Any]:
        return daily[(h, "BTCUSDT")]

    assert row(last_jan - DAY)["eligible"] and row(last_jan - DAY)["next_month"] is None
    blocked = row(last_jan)
    assert blocked["next_month"] == "2025-02" and blocked["next_month_status"] == status
    assert blocked["perpetual_eligible"] and not blocked["eligible"]
    assert blocked["signal"] == text(max(D(blocked["s"]), D(0)))
    assert any(D(row(h)["s"]) < 0 for h in range(T0, feb, DAY))  # the clamp matters here
    for h in range(feb, mar, DAY):  # inside the month: no eligible perpetual, point in time
        assert not row(h)["perpetual_eligible"] and not row(h)["eligible"]
    assert row(last_feb)["next_month"] == "2025-03"
    assert row(last_feb)["next_month_status"] == "complete"
    assert row(mar)["eligible"] and row(mar)["signal"] == row(mar)["s"]
    assert row(last_mar)["next_month"] is None and row(last_mar)["eligible"]


def test_a_held_futures_leg_meets_the_funding_month_exit_precondition(monkeypatch, tmp_path):
    """The funding-month exit's precondition, at the last-day decision itself: the coin holds a
    futures leg and the next month is incomplete. It overrides the no-bar rule (the spot series
    stop before the window, so neither coin has a daily bar in it, and neither gets a target)
    and leaves no eligible perpetual. ETHUSDT, the same but holding nothing, has no exit."""
    spot_hours, perp_hours = hours_in("2024-10", "2024-12"), hours_in("2024-10", "2025-02")
    start = month_start("2024-10")

    def coin(symbol: str, price: str, seed: int) -> CoinSpec:
        return CoinSpec(
            symbol,
            Series(start, path(price, (spot_hours, "0.0002"), noise="0.003", seed=seed)),
            perpetual=PerpetualSpec(
                series=Series(start, path(price, (perp_hours, "0.0002"), noise="0.003", seed=seed)),
                months={"2025-02": "missing_slot"},
                funding_rate="0",
            ),
        )

    universes = every_month("2025-01", "2025-02", ("BTCUSDT", "ETHUSDT"))
    market = load(
        tmp_path,
        World("2025-02", (coin("BTCUSDT", "50000", 7), coin("ETHUSDT", "2000", 8)), universes),
    )
    seed(
        monkeypatch,
        T0 - HOUR,
        [("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "0.01", "50000"))],
    )

    _, rows = cell_run(market, tmp_path)

    daily = daily_by(rows)
    last_jan = month_start("2025-02") - DAY
    before, at = daily[(last_jan - DAY, "BTCUSDT")], daily[(last_jan, "BTCUSDT")]
    assert not before["funding_month_exit"] and before["eligible"]
    assert at["funding_month_exit"] and at["next_month_status"] == "missing_slot"
    assert at["perpetual_eligible"] and not at["eligible"]
    assert at["no_bar"] and at["target"] is None and at["no_target"] == "no_bar"
    flat = daily[(last_jan, "ETHUSDT")]
    assert flat["next_month_status"] == "missing_slot" and not flat["eligible"]
    assert not flat["funding_month_exit"]  # nothing held on futures, so nothing to close


def test_open_marks_flag_an_hour_complete_only_when_every_held_leg_has_its_bar(
    monkeypatch, tmp_path
):
    """An open mark prices each held leg at its venue's open, or at its carried mark (the last
    close before the hour) when the hour is masked, and is complete only when no held leg needs
    a carried mark. A masked bar of a leg not held changes nothing. A coin held outside the
    universe is decided as a universe exit, with target 0."""
    start, hours = month_start("2024-12"), hours_in("2024-12", "2025-01")
    closes = path("50000", (hours, "0.0001"), noise="0.002", seed=8)
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, closes, masked=(T0 + HOUR,)),  # spot masked at 01:00; spot is not held
        perpetual=PerpetualSpec(series=Series(start, closes, masked=(T0,)), funding_rate="0"),
    )
    eth = CoinSpec("ETHUSDT", Series(start, path("2000", (hours, "0.0001"), noise="0.002", seed=9)))
    market = load(tmp_path, World("2025-01", (btc, eth), {"2025-01": ("BTCUSDT",)}))
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "0.01", "50000")),
            ("ETHUSDT", seed_fill(T0 - HOUR, "spot", "ETHUSDT", 1, "0.5", "2000")),
        ],
    )

    result, rows = cell_run(market, tmp_path)

    perp = market.coin("BTCUSDT").perpetual
    assert perp is not None
    eth_spot = market.coin("ETHUSDT").spot
    carried = perp.store.last_close_before(T0)
    assert perp.store.bar(T0) is None and carried is not None
    cash = Fraction(CAPITAL) - Fraction(D("0.5") * D("2000"))

    def equity(eth_price: Decimal, perp_price: Decimal) -> Decimal:
        value = cash + Fraction(D("0.5")) * Fraction(eth_price)
        return to_decimal(value + Fraction(D("0.01")) * (Fraction(50000) - Fraction(perp_price)))

    bar0, bar1, perp1 = eth_spot.bar(T0), eth_spot.bar(T0 + HOUR), perp.store.bar(T0 + HOUR)
    assert bar0 is not None and bar1 is not None and perp1 is not None
    assert result.open_marks[0] == (T0, equity(bar0.open, carried), False)
    assert result.open_marks[1] == (T0 + HOUR, equity(bar1.open, perp1.open), True)
    hourly = of_kind(rows, "hourly")
    assert hourly[0]["open_ms"] == T0 and hourly[0]["complete"] is False
    assert hourly[0]["open_equity"] == str(result.open_marks[0][1])
    assert hourly[0]["margin_ratio"] is not None  # a futures leg is held
    daily = daily_by(rows)
    assert daily[(T0, "ETHUSDT")]["universe_exit"] and daily[(T0, "ETHUSDT")]["target"] == "0"
    assert not daily[(T0, "ETHUSDT")]["in_universe"]
    assert daily[(T0, "BTCUSDT")]["in_universe"] and not daily[(T0, "BTCUSDT")]["universe_exit"]


def test_equity_2025_is_the_open_mark_at_2025_01_01(tmp_path):
    market = load(tmp_path, flat_world(first="2024-12", end="2025-01"))

    result, rows = cell_run(market, tmp_path)

    marks = {stamp: equity for stamp, equity, _ in result.open_marks}
    assert result.equity_2025 == marks[T0] == D(CAPITAL)
    assert D(of_kind(rows, "outcome")[0]["equity_2025"]) == D(CAPITAL)
    before = load(tmp_path, flat_world(first="2024-11", end="2024-12"), name="before")
    assert cell_run(before, tmp_path, name="before")[0].equity_2025 is None


# ---- stops, failures and errors -----------------------------------------------------------


def test_a_liquidation_at_the_open_mark_stops_the_cell(monkeypatch, tmp_path):
    """The pre-fill liquidation check: a short whose backing is at or below its maintenance at
    the open mark ends the cell there. No later event, no decision; the lifecycle is censored at
    the open mark's prices, and the mark is the final equity."""
    t0 = month_start("2024-12")
    hours = hours_in("2024-11", "2024-12")
    btc = CoinSpec(
        "BTCUSDT",
        Series(month_start("2024-11"), path("2000", (hours, "0.0001"), noise="0.001", seed=10)),
        perpetual=PerpetualSpec(funding_rate="0"),
    )
    market = load(tmp_path, World("2024-12", (btc,), {"2024-12": ("BTCUSDT",)}))
    seed(
        monkeypatch,
        t0 - HOUR,
        [("BTCUSDT", seed_fill(t0 - HOUR, "futures", "BTCUSDT", -1, "1", "1000"))],
    )

    result, rows = cell_run(market, tmp_path, CellSpec("v4_main", 1000, 1))

    perp = market.coin("BTCUSDT").perpetual
    assert perp is not None
    bar = perp.store.bar(t0)
    assert bar is not None
    final = D(1000) + (D(1000) - bar.open)  # cash + a short's unrealised P&L at the open
    assert result.outcome == "liquidated" and result.reason is None and result.stop_ms == t0
    assert result.open_marks == ((t0, final, True),)
    assert result.final_equity == final and result.final_after_close is None
    assert result.equity_2025 is None  # the stop came before 2025-01-01
    assert of_kind(rows, "daily_coin") == [] and of_kind(rows, "monthly") == []
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert lifecycle["coin"] == "BTCUSDT" and lifecycle["side"] == "short"
    assert lifecycle["censored"] and lifecycle["exit_reason"] == "liquidation"
    assert D(lifecycle["unrealised"]) == D(1000) - bar.open
    assert [kind for kind, _ in rows] == ["hourly", "lifecycle", "outcome"]
    outcome = rows[-1][1]
    assert outcome["outcome"] == "liquidated" and outcome["stop_ms"] == t0
    assert outcome["check"] == "open_mark" and outcome["final_after_close"] is None
    assert D(outcome["mark"]["equity"]) == final


def test_an_exception_becomes_an_engine_error_with_closed_records(monkeypatch, tmp_path):
    """Ruling P5: an exception in the loop is the cell's outcome ``engine_error``; the records
    end with that outcome, the writer is closed, the receipt written and the fields are as of
    the failure (here, the third daily decision)."""
    market = load(tmp_path, trend_world())
    calls: list[int] = []

    def failing(*args, **kwargs):
        calls.append(1)
        if len(calls) == 3:
            raise RuntimeError("injected")
        return size_book(*args, **kwargs)

    monkeypatch.setattr(run, "size_book", failing)

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "engine_error" and result.reason == "RuntimeError: injected"
    assert result.stop_ms is None and result.final_after_close is None
    assert len(result.open_marks) == 2 * 24 + 1  # the failing hour's open mark was taken
    assert result.final_equity == D(CAPITAL)
    kind, outcome = rows[-1]
    assert kind == "outcome" and outcome["outcome"] == "engine_error"
    assert outcome["type"] == "RuntimeError" and outcome["message"] == "injected"
    assert outcome["hour_ms"] == T0 + 2 * DAY
    assert len(of_kind(rows, "hourly")) == 2 * 24  # no record for the failing hour
    assert len(of_kind(rows, "outcome")) == 1


class _BrokenAudit(Ledger):
    """A ledger whose audit reports ``changes`` from the ``fail_from``-th call on."""

    changes: dict[str, Any] = {}
    fail_from = 1
    calls = 0

    def audit(self, prices):
        audit = super().audit(prices)
        type(self).calls += 1
        if type(self).calls >= type(self).fail_from:
            return replace(audit, **type(self).changes)
        return audit


def broken_audit(monkeypatch, changes: dict[str, Any], fail_from: int = 1) -> None:
    broken = type("Broken", (_BrokenAudit,), {"changes": changes, "fail_from": fail_from})
    monkeypatch.setattr(run, "Ledger", broken)


@pytest.mark.parametrize(
    ("changes", "identity"),
    [
        ({"wallet_residual": D("1E-40")}, "wallet"),
        ({"quantity_residuals": {("spot", "BTCUSDT"): D("-1E-40")}}, "quantity"),
        ({"equity_residual": D("1.1E-18")}, "equity"),
        ({"equity_residual": D("-1.1E-18")}, "equity"),
    ],
)
def test_a_failed_audit_stops_the_cell_as_an_accounting_failure(
    changes, identity, monkeypatch, tmp_path
):
    """Spec "Safety", accounting: the wallet and quantity identities are exact and the equity
    residual is at most 1e-18. A failure at the end of an hour stops the cell at that hour."""
    market = load(tmp_path, flat_world())
    broken_audit(monkeypatch, changes)

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "accounting_failure" and result.reason == identity
    assert result.stop_ms == T0 and len(result.open_marks) == 1
    assert result.final_after_close is None and result.final_equity == D(CAPITAL)
    outcome = rows[-1][1]
    assert rows[-1][0] == "outcome" and outcome["outcome"] == "accounting_failure"
    assert outcome["reason"] == identity and outcome["stop_ms"] == T0
    values = outcome["values"]
    assert values["wallet_residual"] == str(result.audit.wallet_residual)
    assert values["equity_residual"] == str(result.audit.equity_residual)
    assert values["quantity_residuals"] == [
        [venue, symbol, str(value)]
        for (venue, symbol), value in result.audit.quantity_residuals.items()
    ]
    assert [kind for kind, _ in rows] == ["monthly", "daily_coin", "hourly", "outcome"]


def test_the_audit_stops_the_loop_at_the_hour_it_fails(monkeypatch, tmp_path):
    market = load(tmp_path, flat_world())
    broken_audit(monkeypatch, {"wallet_residual": D("1E-30")}, fail_from=3)  # one audit an hour

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "accounting_failure" and result.stop_ms == T0 + 2 * HOUR
    assert [stamp for stamp, _, _ in result.open_marks] == [T0, T0 + HOUR, T0 + 2 * HOUR]
    assert [D(h["equity_residual"]) for h in of_kind(rows, "hourly")] == [0, 0, 0]
    assert rows[-1][1]["values"]["wallet_residual"] == "1E-30"


@pytest.mark.parametrize("residual", ["1E-18", "-1E-18", "0"])
def test_an_equity_residual_within_1e_18_passes(residual, monkeypatch, tmp_path):
    market = load(tmp_path, flat_world())
    broken_audit(monkeypatch, {"equity_residual": D(residual)})

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and result.audit.equity_residual == D(residual)
    assert {h["equity_residual"] for h in of_kind(rows, "hourly")} == {residual}


# ---- outputs ------------------------------------------------------------------------------


def test_the_outputs_are_the_records_and_the_receipt(tmp_path):
    """``out_dir`` is created when missing and holds ``records.jsonl`` and ``receipt.json``; a
    cell never replaces either, so a second run into the same directory is refused."""
    market = load(tmp_path, trend_world())
    out = tmp_path / "nested" / "v4_main-10000-1x"

    result = run.run_v4_cell(market, MAIN, out)

    assert sorted(p.name for p in out.iterdir()) == [run.RECEIPT_FILE, run.RECORDS_FILE]
    assert read_receipt(out / run.RECEIPT_FILE) == result.receipt
    rows = list(read_records(out / run.RECORDS_FILE, result.receipt))
    assert result.receipt.record_count == len(rows)
    hourly = of_kind(rows, "hourly")
    assert [h["open_ms"] for h in hourly] == [stamp for stamp, _, _ in result.open_marks]
    assert set(hourly[0]) == {
        "open_ms",
        "open_equity",
        "complete",
        "equity",
        "gross_notional",
        "gross",
        "margin_ratio",
        "equity_residual",
    }
    (monthly,) = of_kind(rows, "monthly")
    assert monthly["open_ms"] == T0 and monthly["universe"] == ["BTCUSDT", "ETHUSDT"]
    assert monthly["perpetuals"] == [
        {
            "coin": "BTCUSDT",
            "perpetual": "BTCUSDT",
            "multiplier": 1,
            "status": "complete",
            "next_month": "2025-02",
            "next_status": None,
        }
    ]
    outcome = of_kind(rows, "outcome")
    assert outcome == [rows[-1][1]] and outcome[0]["outcome"] == "complete"
    assert D(outcome[0]["final_after_close"]) == result.final_after_close
    assert outcome[0]["hours"] == len(result.open_marks)
    before = (out / run.RECORDS_FILE).read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        run.run_v4_cell(market, MAIN, out)
    assert (out / run.RECORDS_FILE).read_bytes() == before
    alone = tmp_path / "receipt-only"
    alone.mkdir()
    (alone / run.RECEIPT_FILE).write_bytes(b"{}")
    with pytest.raises(ValueError, match="already exists"):
        run.run_v4_cell(market, MAIN, alone)
    assert not (alone / run.RECORDS_FILE).exists()


def test_the_hold_arms_are_not_run_here(tmp_path):
    market = load(tmp_path, flat_world())
    out = tmp_path / "hold"
    for arm in ("hold_universe", "hold_btc"):
        with pytest.raises(ValueError, match="not a V4 arm"):
            run.run_v4_cell(market, CellSpec(arm, CAPITAL, 1), out)
    assert not out.exists() or not any(out.iterdir())


def test_cell_result_holds_the_plans_fields():
    assert [field.name for field in dataclasses.fields(run.CellResult)] == [
        "outcome",
        "reason",
        "stop_ms",
        "open_marks",
        "final_equity",
        "equity_2025",
        "final_after_close",
        "audit",
        "receipt",
    ]
