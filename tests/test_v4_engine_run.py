"""V4 engine task 12: the hour loop of the V4 arms (part 12a: the loop, the open marks, the
records, the 00:00 decisions, the audit and the error paths; part 12b: the fill phase and the
window-end close).

Each test replays a small synthetic world from ``tests/v4_synthetic.py`` through
``run_v4_cell``. ``seed`` books fills into the cell's ledger and opens their lifecycles before
the first hour, through the module's ``Ledger`` and ``Lifecycles`` names, for a test that needs a
position the rules would not make on their own (a dust holding, a profitable short). The 12a
tests check only hours and records that the fills cannot change (an open mark comes before the
hour's fills, and a daily record is the decision's, not the fill's). Every world trading in a
12b test has a funding rate of 0, so part 12c's funding cannot move what these tests pin.

Expected signals and weights are recomputed here the plain way: one ``CoinSignals`` pass over
the market's daily bars, and ``size_book`` on each coin's whole return series. So the engine's
lazy feeding and trailing return slices are checked against the straightforward computation.
Expected fills are recomputed from the spec's formulas on the holdings the fill records add up
to. The network is blocked for every test (the autouse fixture) and no real pack is read.
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
    FUTURES_RULES,
    HOUR,
    SPOT_RULES,
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
from crypto_grid_bot.v4.engine.allocation import clip_increases
from crypto_grid_bot.v4.engine.arms import ARMS, ArmSpec, CellSpec
from crypto_grid_bot.v4.engine.ledger import Fill, Ledger
from crypto_grid_bot.v4.engine.lifecycle import Lifecycles
from crypto_grid_bot.v4.engine.market import HourBar, Market
from crypto_grid_bot.v4.engine.numbers import to_decimal
from crypto_grid_bot.v4.engine.pending import PendingBook
from crypto_grid_bot.v4.engine.records import read_receipt, read_records
from crypto_grid_bot.v4.engine.safety import DeadMarkets
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


# ---- 12b: the fill phase and the window-end close -----------------------------------------

SPOT_STEP = SPOT_RULES.step
FUTURES_STEP = FUTURES_RULES.step
COSTS = {"spot": MAIN.costs("spot"), "futures": MAIN.costs("futures")}
F = Fraction


def floor_to(value: Fraction, step: Decimal) -> Fraction:
    """``value >= 0`` rounded toward zero to ``step``."""
    unit = F(step)
    return (value // unit) * unit


def events(rows: Iterable[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [r for r in of_kind(rows, "event") if r["type"] == kind]


def fills_at(rows: Iterable[tuple[str, dict[str, Any]]], timestamp_ms: int) -> list[dict[str, Any]]:
    return [r for r in of_kind(rows, "fill") if r["timestamp_ms"] == timestamp_ms]


def order_event(rows: Iterable[tuple[str, dict[str, Any]]], hour_ms: int, coin: str) -> dict:
    (found,) = [r for r in events(rows, "order") if r["hour_ms"] == hour_ms and r["coin"] == coin]
    return found


def holdings(
    rows: Iterable[tuple[str, dict[str, Any]]],
    through_ms: int,
    seeded: Sequence[tuple[str, str, str]] = (),
) -> dict[tuple[str, str], Fraction]:
    """Each leg's quantity once every fill stamped at or before ``through_ms`` is booked, from
    the seeded ``(venue, symbol, quantity)`` on; legs at 0 are left out."""
    held: dict[tuple[str, str], Fraction] = {}
    for venue, symbol, quantity in seeded:
        held[venue, symbol] = held.get((venue, symbol), F(0)) + F(D(quantity))
    for fill in of_kind(rows, "fill"):
        if fill["timestamp_ms"] <= through_ms:
            key = (fill["venue"], fill["symbol"])
            held[key] = held.get(key, F(0)) + fill["side"] * F(D(fill["quantity"]))
    return {key: quantity for key, quantity in held.items() if quantity}


def cash_after(
    rows: Iterable[tuple[str, dict[str, Any]]], through_ms: int, start: Fraction
) -> Fraction:
    """The wallet after every fill stamped at or before ``through_ms`` (spec "One wallet")."""
    cash = start
    for fill in of_kind(rows, "fill"):
        if fill["timestamp_ms"] > through_ms:
            continue
        notional = F(D(fill["quantity"])) * F(D(fill["price"]))
        if fill["venue"] == "spot":
            cash += -fill["side"] * notional
        else:
            cash += F(D(fill["realised"]))
        cash -= F(D(fill["fee"]))
    return cash


def check_fill(
    fill: dict[str, Any], venue: str, side: int, quantity: Fraction, unslipped: Decimal
) -> None:
    """The fill is ``quantity`` at the unslipped price moved by the slippage against the trade,
    with the venue's fee on its own notional (spec "Costs (normal)", ruling R3)."""
    costs = COSTS[venue]
    price = F(unslipped) * (1 + side * F(costs.slippage_rate))
    assert (fill["venue"], fill["side"]) == (venue, side)
    assert F(D(fill["quantity"])) == quantity
    assert F(D(fill["price"])) == price
    assert F(D(fill["fee"])) == quantity * price * F(costs.fee_rate)
    assert D(fill["unslipped_price"]) == unslipped


def spot_bar(market: Market, coin: str, hour_ms: int) -> HourBar:
    bar = market.coin(coin).spot.bar(hour_ms)
    assert bar is not None
    return bar


def perp_bar(market: Market, coin: str, hour_ms: int) -> HourBar:
    perpetual = market.coin(coin).perpetual
    assert perpetual is not None
    bar = perpetual.store.bar(hour_ms)
    assert bar is not None
    return bar


def open_equity(result: run.CellResult, hour_ms: int) -> Fraction:
    (equity,) = [equity for stamp, equity, _ in result.open_marks if stamp == hour_ms]
    return F(equity)


def one_coin(
    symbol: str,
    price: str,
    rate: str,
    seed: int,
    *,
    perpetual: PerpetualSpec | None = None,
    noise: str = "0.002",
    places: int = 8,
    start: str = "2024-10",
    end: str = "2025-01",
    spot_masked: Sequence[int] = (),
) -> CoinSpec:
    closes = path(price, (hours_in(start, end), rate), noise=noise, seed=seed, places=places)
    return CoinSpec(symbol, Series(month_start(start), closes, masked=spot_masked), perpetual)


# The four-coin world: four rising coins at the 0.30 cap need more room than spot has.
FOUR = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
FEB = month_start("2025-02")
LAST_JAN = FEB - DAY  # 00:00 on 2025-01-31, the decision before February
LAST_HOUR = month_start("2025-03") - HOUR  # the window's last hour
WINDOW_END_FILL = LAST_HOUR + HOUR - 1
DOGE_SEED = ("spot", "DOGEUSDT", "20")  # 20 DOGE at 0.1: 2 USDT, below the 5 USDT minimum
FOUR_CASH = F(CAPITAL) - F(20) * F(D("0.1"))  # the seeded DOGE was bought without a fee


def four_world() -> World:
    """BTCUSDT, ETHUSDT, SOLUSDT and XRPUSDT rising from 2024-10, each with a perpetual of its
    own name and a funding rate of 0, selected in January; XRPUSDT leaves in February. SOLUSDT's
    February funding month is incomplete; XRPUSDT's perpetual is masked at 01:00 on February 1
    and ETHUSDT's in the window's last hour. DOGEUSDT, in no universe, is the dust a test seeds."""
    start, hours = month_start("2024-10"), hours_in("2024-10", "2025-02")
    prices = {"BTCUSDT": "50000", "ETHUSDT": "3000", "SOLUSDT": "150", "XRPUSDT": "2"}
    masked = {"XRPUSDT": (FEB + HOUR,), "ETHUSDT": (LAST_HOUR,)}
    coins = []
    for seed_, symbol in enumerate(FOUR, start=20):
        closes = path(prices[symbol], (hours, "0.0002"), noise="0.002", seed=seed_)
        perpetual = PerpetualSpec(
            series=Series(start, closes, masked=masked.get(symbol, ())),
            months={"2025-02": "missing_slot"} if symbol == "SOLUSDT" else {},
            funding_rate="0",
        )
        coins.append(CoinSpec(symbol, Series(start, closes), perpetual=perpetual))
    doge = CoinSpec("DOGEUSDT", Series(start, path("0.1", (hours, "0"), noise="0.001", seed=30)))
    return World("2025-02", (*coins, doge), {"2025-01": FOUR, "2025-02": FOUR[:3]})


@dataclasses.dataclass
class FourRun:
    market: Market
    result: run.CellResult
    rows: list[tuple[str, dict[str, Any]]]
    observed: list[tuple[int, str, str, bool]]
    forgotten: list[tuple[str, str]]
    clips: list[tuple[tuple[Any, ...], tuple[tuple[str, str, Decimal], ...]]]


@pytest.fixture(scope="module")
def four(tmp_path_factory) -> FourRun:
    """One v4_main cell over ``four_world``, with DOGEUSDT's dust seeded, run once for the tests
    that read it; ``DeadMarkets`` and ``clip_increases`` are wrapped to record their calls."""
    root = tmp_path_factory.mktemp("four")
    market = Market.load(write_world(root / "world", four_world()))
    observed: list[tuple[int, str, str, bool]] = []
    forgotten: list[tuple[str, str]] = []
    clips: list[tuple[tuple[Any, ...], tuple[tuple[str, str, Decimal], ...]]] = []

    class Watched(DeadMarkets):
        def observe(self, hour_ms, venue, symbol, has_bar):
            observed.append((hour_ms, venue, symbol, has_bar))
            super().observe(hour_ms, venue, symbol, has_bar)

        def forget(self, venue, symbol):
            forgotten.append((venue, symbol))
            super().forget(venue, symbol)

    def clip(*args):
        admitted = clip_increases(*args)
        clips.append((args, admitted))
        return admitted

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    with pytest.MonkeyPatch.context() as patch:
        # The autouse block is per test; this module-wide run blocks the network itself.
        for owner, name in [
            (socket, "getaddrinfo"),
            (socket, "create_connection"),
            (socket.socket, "connect"),
            (socket.socket, "connect_ex"),
        ]:
            patch.setattr(owner, name, refuse)
        seed(
            patch,
            T0 - HOUR,
            [("DOGEUSDT", seed_fill(T0 - HOUR, "spot", "DOGEUSDT", 1, "20", "0.1"))],
        )
        patch.setattr(run, "DeadMarkets", Watched)
        patch.setattr(run, "clip_increases", clip)
        result, rows = cell_run(market, root)
    return FourRun(market, result, rows, observed, forgotten, clips)


def test_one_coin_holds_its_spot_and_futures_legs_under_one_name(four):
    """Review Focus 1 at the loop level, and spec "Longs on spot first": four longs at the 0.30
    cap need 1.2 x equity, more than the room R = 0.98 x equity - D (D is the seeded DOGEUSDT
    dust). Spot takes s_max = 1.5 x (R - G_L / 3), shared pro rata, and each coin's rest goes on
    its perpetual, which carries the coin's own name: every coin holds both legs at once, booked
    in one batch, spot before futures and alphabetically, all at the 01:00 open."""
    market, rows, at = four.market, four.rows, T0 + HOUR
    daily = daily_by(rows)
    assert {daily[(T0, coin)]["target"] for coin in FOUR} == {"0.30"}  # all at the coin cap
    equity = open_equity(four.result, at)
    dust = F(20) * F(spot_bar(market, "DOGEUSDT", at).open)
    target = F(D("0.30")) * equity
    room = F(D("0.98")) * equity - dust
    capacity = F(3, 2) * (room - 4 * target / 3)
    assert 0 < capacity < 4 * target  # spot cannot hold it all
    spot_share, futures_share = capacity / 4, target - capacity / 4

    booked = fills_at(rows, at)
    assert [(f["coin"], f["venue"]) for f in booked] == [
        (coin, venue) for coin in FOUR for venue in ("spot", "futures")
    ]
    for coin in FOUR:
        spot, futures = (f for f in booked if f["coin"] == coin)
        assert spot["symbol"] == futures["symbol"] == coin  # one name, two legs
        spot_open, perp_open = spot_bar(market, coin, at).open, perp_bar(market, coin, at).open
        check_fill(spot, "spot", 1, floor_to(spot_share / F(spot_open), SPOT_STEP), spot_open)
        quantity = floor_to(futures_share / F(perp_open), FUTURES_STEP)
        check_fill(futures, "futures", 1, quantity, perp_open)
        assert spot["reason"] == futures["reason"] == "signal" and spot["hour_ms"] == at
        order = order_event(rows, at, coin)
        assert order["source"] == "signal" and order["band"] == "trade"
        assert order["decision_ms"] == T0 and order["current"] == "0"
        assert abs(F(D(order["split"]["spot"])) - spot_share) < F(1, 10**40)
        assert abs(F(D(order["split"]["futures"])) - futures_share) < F(1, 10**40)
        assert [leg["venue"] for leg in order["legs"]] == ["spot", "futures"]
    held = holdings(rows, at, [DOGE_SEED])
    assert all(held["spot", coin] > 0 and held["futures", coin] > 0 for coin in FOUR)
    # The next open mark values both legs of each coin, each at its own venue's open.
    after = T0 + 2 * HOUR
    cash = cash_after(rows, at, FOUR_CASH)
    value = cash + F(20) * F(spot_bar(market, "DOGEUSDT", after).open)
    for coin in FOUR:
        (futures,) = (f for f in booked if f["coin"] == coin and f["venue"] == "futures")
        value += held["spot", coin] * F(spot_bar(market, coin, after).open)
        value += held["futures", coin] * (
            F(perp_bar(market, coin, after).open) - F(D(futures["price"]))
        )
    assert open_equity(four.result, after) == value
    assert all(D(h["equity_residual"]).copy_abs() <= D("1e-18") for h in of_kind(rows, "hourly"))


def test_leaving_the_top_10_exits_at_the_next_open(four):
    """Spec "Universe", leaving the top 10, and the band paragraph's mandatory exits: XRPUSDT
    leaves at February's selection. February's first decision gives it 0 and cancels that order;
    each leg then closes on its own venue at the first hour from 01:00 that has a bar: spot at
    01:00, the perpetual (masked at 01:00) at 02:00. Closing the last leg ends the lifecycle as a
    universe exit, and the coin is not decided again."""
    market, rows = four.market, four.rows
    record = daily_by(rows)[(FEB, "XRPUSDT")]
    assert record["universe_exit"] and record["target"] == "0"
    (cancelled,) = [e for e in events(rows, "order_cancelled") if e["coin"] == "XRPUSDT"]
    assert cancelled == {
        "type": "order_cancelled",
        "hour_ms": FEB,
        "coin": "XRPUSDT",
        "decision_ms": FEB,
        "target": "0",
        "reason": "universe exit",
    }
    scheduled = [e for e in events(rows, "exit_scheduled") if e["coin"] == "XRPUSDT"]
    assert [(e["venue"], e["reason"], e["after_ms"]) for e in scheduled] == [
        ("spot", "universe exit", FEB + HOUR),
        ("futures", "universe exit", FEB + HOUR),
    ]
    held = holdings(rows, FEB, [DOGE_SEED])
    spot_fill = [f for f in fills_at(rows, FEB + HOUR) if f["coin"] == "XRPUSDT"]
    futures_fill = [f for f in fills_at(rows, FEB + 2 * HOUR) if f["coin"] == "XRPUSDT"]
    assert len(spot_fill) == len(futures_fill) == 1
    check_fill(
        spot_fill[0],
        "spot",
        -1,
        held["spot", "XRPUSDT"],
        spot_bar(market, "XRPUSDT", FEB + HOUR).open,
    )
    check_fill(
        futures_fill[0],
        "futures",
        -1,
        held["futures", "XRPUSDT"],
        perp_bar(market, "XRPUSDT", FEB + 2 * HOUR).open,
    )
    assert spot_fill[0]["reason"] == futures_fill[0]["reason"] == "universe exit"
    first, second = (
        order_event(rows, FEB + HOUR, "XRPUSDT"),
        order_event(rows, FEB + 2 * HOUR, "XRPUSDT"),
    )
    assert first["source"] == second["source"] == "exit"
    assert first["exits"] == [["spot", "universe exit"]]
    assert second["exits"] == [["futures", "universe exit"]]
    assert D(first["split"]["spot"]) == 0 and D(first["split"]["futures"]) > 0  # kept as held
    (lifecycle,) = [r for r in of_kind(rows, "lifecycle") if r["coin"] == "XRPUSDT"]
    assert lifecycle["exit_reason"] == "universe exit" and lifecycle["exit_ms"] == FEB + 2 * HOUR
    assert not lifecycle["censored"] and lifecycle["entry_ms"] == T0 + HOUR
    assert not [
        f for f in of_kind(rows, "fill") if f["coin"] == "XRPUSDT" and f["hour_ms"] > FEB + 2 * HOUR
    ]
    assert (
        max(r["decision_ms"] for r in of_kind(rows, "daily_coin") if r["coin"] == "XRPUSDT") == FEB
    )


def test_a_funding_month_exit_closes_the_futures_and_places_the_replacement_buy(four):
    """Spec "Data" and the band paragraph: SOLUSDT's February funding month is incomplete. At
    00:00 on January 31 its perpetual is ineligible, the order of that decision is cancelled and
    its futures leg is scheduled to close at 01:00. The close is followed by the replacement spot
    buy, placed in the same hour (spot has its bar) and sized there from the coin's latest target
    as a spot-only coin, in the hour's one allocation: the room R left by the coins that keep
    their legs scales it by k = R / G_N. The buy, an increase, then meets the cash clip after the
    close: the wallet minus the other coins' initial margin pays for less, so it is cut. One
    lifecycle carries the long through the move."""
    market, rows, at = four.market, four.rows, LAST_JAN + HOUR
    view = daily_by(rows)[(LAST_JAN, "SOLUSDT")]
    assert view["funding_month_exit"] and not view["eligible"] and view["target"] == "0.30"
    (cancelled,) = [e for e in events(rows, "order_cancelled") if e["coin"] == "SOLUSDT"]
    assert (cancelled["hour_ms"], cancelled["reason"]) == (LAST_JAN, "funding-month exit")
    (scheduled,) = [e for e in events(rows, "exit_scheduled") if e["coin"] == "SOLUSDT"]
    assert (scheduled["venue"], scheduled["after_ms"]) == ("futures", at)
    assert [e["coin"] for e in events(rows, "replacement_scheduled")] == ["SOLUSDT"]
    assert events(rows, "replacement_scheduled")[0]["hour_ms"] == at

    held = holdings(rows, at - HOUR, [DOGE_SEED])
    equity = open_equity(four.result, at)
    kept = ("BTCUSDT", "ETHUSDT", "XRPUSDT")
    for coin in kept:
        assert order_event(rows, at, coin)["band"] == "keep"  # these keep their legs
    spot_kept = sum(held["spot", c] * F(spot_bar(market, c, at).open) for c in kept)
    futures_kept = sum(held["futures", c] * F(perp_bar(market, c, at).open) for c in kept)
    dust = F(20) * F(spot_bar(market, "DOGEUSDT", at).open)
    room = F(D("0.98")) * equity - spot_kept - dust - futures_kept / 3
    wanted = F(D("0.30")) * equity  # G_N: the latest target, on spot only
    capacity = max(F(0), min(wanted, F(3, 2) * (room - wanted / 3)))
    assert capacity < wanted  # the room binds: every eligible long is on futures, N scales
    spot_target = min(F(1), max(F(0), room) / wanted) * wanted
    sol_open = spot_bar(market, "SOLUSDT", at).open
    planned = floor_to(spot_target / F(sol_open), SPOT_STEP) - held["spot", "SOLUSDT"]
    assert planned > 0
    order = order_event(rows, at, "SOLUSDT")
    assert order["source"] == "replacement buy" and order["eligible"] is False
    assert order["exits"] == [["futures", "funding-month exit"]] and order["target"] == "0.30"
    assert abs(F(D(order["split"]["spot"])) - spot_target) < F(1, 10**40)
    assert D(order["split"]["futures"]) == 0
    spot_leg, futures_leg = order["legs"]
    assert [F(D(o["quantity"])) for o in spot_leg["orders"]] == [planned]
    assert [(o["side"], F(D(o["quantity"])), o["reduce_only"]) for o in futures_leg["orders"]] == [
        (-1, held["futures", "SOLUSDT"], True)
    ]

    booked = [f for f in fills_at(rows, at) if f["coin"] == "SOLUSDT"]
    assert [(f["venue"], f["side"], f["reason"]) for f in booked] == [
        ("futures", -1, "funding-month exit"),
        ("spot", 1, "replacement buy"),
    ]  # the reduction first, then the increase
    sol_perp = perp_bar(market, "SOLUSDT", at).open
    check_fill(booked[0], "futures", -1, held["futures", "SOLUSDT"], sol_perp)
    # The clip sees the account after the close: the wallet, less the initial margin of the
    # futures still open, and the backing less 4 x their maintenance.
    cash = cash_after(rows, at - HOUR, FOUR_CASH) + F(D(booked[0]["realised"]))
    cash -= F(D(booked[0]["fee"]))
    notional = upnl = F(0)
    for coin in kept:
        buys = [
            f
            for f in of_kind(rows, "fill")
            if f["symbol"] == coin and f["venue"] == "futures" and f["timestamp_ms"] < at
        ]
        assert all(f["side"] == 1 for f in buys)  # one long, never reduced: its lots are its buys
        perp_open = F(perp_bar(market, coin, at).open)
        notional += held["futures", coin] * perp_open
        upnl += sum(F(D(f["quantity"])) * (perp_open - F(D(f["price"]))) for f in buys)
    free = min(cash - notional / 3, cash + upnl - 4 * F(D("0.01")) * notional)
    need = (1 + F(COSTS["spot"].slippage_rate)) * (1 + F(COSTS["spot"].fee_rate))
    assert free / need < planned * F(sol_open)  # the wallet pays for less than planned
    check_fill(booked[1], "spot", 1, floor_to(free / need / F(sol_open), SPOT_STEP), sol_open)
    (cut,) = [e for e in events(rows, "increase_cut") if e["hour_ms"] == at]
    assert (cut["coin"], cut["venue"], cut["refusal"]) == ("SOLUSDT", "spot", None)
    assert F(D(cut["wanted"])) == planned * F(sol_open)
    # No futures for SOLUSDT in February, and one long lifecycle to the window end.
    assert not [
        f
        for f in of_kind(rows, "fill")
        if f["coin"] == "SOLUSDT" and f["venue"] == "futures" and f["hour_ms"] > at
    ]
    (lifecycle,) = [r for r in of_kind(rows, "lifecycle") if r["coin"] == "SOLUSDT"]
    assert (lifecycle["side"], lifecycle["exit_reason"]) == ("long", "window end")
    assert lifecycle["entry_ms"] == T0 + HOUR
    futures_leg = lifecycle["venues"]["futures"]
    assert D(futures_leg["bought_quantity"]) == D(futures_leg["sold_quantity"]) > 0


def test_window_end_closes_everything_with_costs_and_censors_dust(four):
    """Spec "Window end": at the last hour's close every position closes with the cell's fees
    and slippage, ETHUSDT's perpetual (masked in that hour) at its carried mark, the last close
    before it. DOGEUSDT's dust cannot be sold: it stays, valued at that close, and its lifecycle
    is censored as "window end (dust)". Final equity is taken after those fills."""
    market, rows, result = four.market, four.rows, four.result
    assert result.outcome == "complete" and result.stop_ms is None
    held = holdings(rows, LAST_HOUR, [DOGE_SEED])
    closing = fills_at(rows, WINDOW_END_FILL)
    expected_legs = sorted(key for key in held if key[1] != "DOGEUSDT")
    assert sorted((f["venue"], f["symbol"]) for f in closing) == expected_legs
    perp = market.coin("ETHUSDT").perpetual
    assert perp is not None and perp.store.bar(LAST_HOUR) is None
    for fill in closing:
        key = (fill["venue"], fill["symbol"])
        if key == ("futures", "ETHUSDT"):
            price = perp.store.last_close_before(LAST_HOUR)
            assert price is not None
        elif fill["venue"] == "spot":
            price = spot_bar(market, fill["symbol"], LAST_HOUR).close
        else:
            price = perp_bar(market, fill["symbol"], LAST_HOUR).close
        check_fill(fill, fill["venue"], -1, held[key], price)  # every leg here is long
        assert fill["reason"] == "window end" and fill["hour_ms"] == LAST_HOUR
    doge_close = spot_bar(market, "DOGEUSDT", LAST_HOUR).close
    final = cash_after(rows, WINDOW_END_FILL, FOUR_CASH) + F(20) * F(doge_close)
    assert F(result.final_after_close) == final and result.final_equity == result.final_after_close
    hourly = of_kind(rows, "hourly")[-1]
    assert hourly["open_ms"] == LAST_HOUR and F(D(hourly["equity"])) == final
    assert hourly["complete"] is False  # ETHUSDT's perpetual took its carried mark at the open
    ended = {r["coin"]: r for r in of_kind(rows, "lifecycle") if r["exit_ms"] == LAST_HOUR}
    assert set(ended) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"}
    for coin in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        assert ended[coin]["exit_reason"] == "window end" and not ended[coin]["censored"]
    dust = ended["DOGEUSDT"]
    assert dust["exit_reason"] == "window end (dust)" and dust["censored"]
    assert F(D(dust["unrealised"])) == F(20) * (F(doge_close) - F(D("0.1")))
    outcome = rows[-1][1]
    assert outcome["outcome"] == "complete" and F(D(outcome["final_after_close"])) == final


def test_the_cash_clip_takes_one_increase_at_a_time_on_the_account_after_each_fill(four):
    """Controller ruling (Task 8): the loop calls the clip one increase at a time, on the
    ledger's state after the previous real fill: the wallet, the open futures' initial margin at
    the open (rounded up, never down), and the backing and maintenance of a mark at the opens."""
    at = T0 + HOUR
    calls = [(args, admitted) for args, admitted in four.clips if len(args[0]) == 1]
    assert len(calls) == len(four.clips) > 0  # never a batch
    booked = fills_at(four.rows, at)
    first_hour = four.clips[: len(booked)]
    cash, margin = FOUR_CASH, F(0)
    for (args, admitted), fill in zip(first_hour, booked, strict=True):
        ((coin, venue, notional),) = args[0]
        assert (coin, venue) == (fill["coin"], fill["venue"])
        assert admitted[0][2] == notional  # nothing was cut in this hour
        assert F(args[1]) == cash
        assert F(args[2]) >= margin / 3 and F(args[2]) - margin / 3 < F(1, 10**50)
        price, quantity = F(D(fill["price"])), F(D(fill["quantity"]))
        if venue == "spot":
            cash -= quantity * price
        else:
            margin += quantity * F(D(fill["unslipped_price"]))
        cash -= F(D(fill["fee"]))


def test_dead_markets_observe_every_held_leg_each_hour_and_forget_a_closed_one(four):
    """Every hour each held leg's venue is reported to ``DeadMarkets`` once, with whether it had
    a bar; a leg that goes flat is forgotten (12c asks ``due`` before these observations)."""
    market, rows = four.market, four.rows
    by_hour: dict[int, list[tuple[str, str, bool]]] = {}
    for hour_ms, venue, symbol, has_bar in four.observed:
        by_hour.setdefault(hour_ms, []).append((venue, symbol, has_bar))
    assert sorted(by_hour) == [stamp for stamp, _, _ in four.result.open_marks]
    stores = {("spot", s): market.coin(s).spot for s in (*FOUR, "DOGEUSDT")}
    for symbol in FOUR:
        perpetual = market.coin(symbol).perpetual
        assert perpetual is not None
        stores["futures", symbol] = perpetual.store
    for hour_ms, seen in by_hour.items():
        held = holdings(rows, hour_ms, [DOGE_SEED])
        assert sorted((v, s) for v, s, _ in seen) == sorted(held)
        assert all(bar == (stores[v, s].bar(hour_ms) is not None) for v, s, bar in seen)
    assert ("futures", "XRPUSDT", False) in by_hour[FEB + HOUR]  # masked, still held
    assert {("spot", "XRPUSDT"), ("futures", "XRPUSDT"), ("futures", "SOLUSDT")} <= set(
        four.forgotten
    )


def test_the_monthly_record_holds_the_full_selection(four):
    """Spec "Universe": the selection is recorded every month (the ranked list with the mean
    quote volumes and bar counts, the exclusions, who entered and who left)."""
    monthly = of_kind(four.rows, "monthly")
    assert [m["month"] for m in monthly] == ["2025-01", "2025-02"]
    for record in monthly:
        selection = four.market.selection(record["month"])
        assert selection is not None
        assert record["selection"] == {
            "ranked": [[s, str(mean), bars] for s, mean, bars in selection.ranked],
            "excluded": [list(pair) for pair in selection.excluded],
            "entered": list(selection.entered),
            "left": list(selection.left),
        }
    assert monthly[1]["selection"]["left"] == ["XRPUSDT"]


@pytest.mark.parametrize("with_perpetual", [False, True])
def test_a_steady_uptrend_goes_long_on_spot_first(with_perpetual, tmp_path):
    """Spec "Longs on spot first": a rising coin's long is held on spot, with a perpetual or
    without one. The 00:00 decision fills at 01:00: a spot buy of the target's notional at the
    open, floored to the step, at the open plus slippage and with the spot fee; no futures order
    is ever made, and the long ends at the window end."""
    perpetual = PerpetualSpec(funding_rate="0") if with_perpetual else None
    btc = one_coin("BTCUSDT", "50000", "0.0003", 11, perpetual=perpetual)
    market = load(tmp_path, World("2025-01", (btc,), {"2025-01": ("BTCUSDT",)}))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    target = F(D(daily_by(rows)[(T0, "BTCUSDT")]["target"]))
    assert target > 0
    assert {f["venue"] for f in of_kind(rows, "fill")} == {"spot"}
    first = of_kind(rows, "fill")[0]
    at = T0 + HOUR
    open_ = spot_bar(market, "BTCUSDT", at).open
    quantity = floor_to(target * CAPITAL / F(open_), SPOT_STEP)
    assert first["timestamp_ms"] == first["hour_ms"] == at and first["coin"] == "BTCUSDT"
    check_fill(first, "spot", 1, quantity, open_)
    order = order_event(rows, at, "BTCUSDT")
    assert order["band"] == "trade" and order["eligible"] is with_perpetual
    assert F(D(order["split"]["spot"])) == target * CAPITAL and D(order["split"]["futures"]) == 0
    cash = F(CAPITAL) - quantity * F(D(first["price"])) - F(D(first["fee"]))
    later = T0 + 2 * HOUR
    assert open_equity(result, later) == cash + quantity * F(
        spot_bar(market, "BTCUSDT", later).open
    )
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["side"], lifecycle["exit_reason"]) == ("long", "window end")
    assert lifecycle["entry_ms"] == at and not lifecycle["censored"]


@pytest.mark.parametrize(
    ("symbol", "multiplier", "price", "places"),
    [("BTCUSDT", 1, "50000", 8), ("SHIBUSDT", 1000, "0.00002", 12)],
)
def test_a_confirmed_downtrend_shorts_on_futures(symbol, multiplier, price, places, tmp_path):
    """Spec "Shorts on futures": a falling coin with an eligible perpetual is shorted on it,
    never on spot. Review Focus 2 at the loop level: on a multiplier perpetual (1000SHIBUSDT for
    SHIBUSDT) the target notional becomes contracts at the contract price, while the records and
    the lifecycle keep the coin's own name."""
    coin = one_coin(
        symbol,
        price,
        "-0.0003",
        12,
        perpetual=PerpetualSpec(multiplier=multiplier, funding_rate="0"),
        places=places,
    )
    market = load(tmp_path, World("2025-01", (coin,), {"2025-01": (symbol,)}))
    perpetual = market.coin(symbol).perpetual
    assert perpetual is not None

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    daily = of_kind(rows, "daily_coin")
    decision = next(r for r in daily if r["target"] not in (None, "0"))
    target = F(D(decision["target"]))
    assert target < 0 and decision["downtrend"]["confirmed"]
    fills = of_kind(rows, "fill")
    assert {f["venue"] for f in fills} == {"futures"}
    assert {(f["coin"], f["symbol"]) for f in fills} == {(symbol, perpetual.symbol)}
    at = decision["decision_ms"] + HOUR
    contract = perp_bar(market, symbol, at).open
    if multiplier != 1:
        assert contract == spot_bar(market, symbol, at).open * multiplier
    quantity = floor_to(-target * open_equity(result, at) / F(contract), FUTURES_STEP)
    assert fills[0]["hour_ms"] == at
    check_fill(fills[0], "futures", -1, quantity, contract)
    lifecycles = of_kind(rows, "lifecycle")
    assert lifecycles[0]["coin"] == symbol and lifecycles[0]["side"] == "short"
    assert lifecycles[0]["entry_ms"] == at


def test_a_masked_fill_hour_defers_the_order_and_a_newer_decision_replaces_it(tmp_path):
    """Review Focus 3 at the loop level (spec "Sizing", the band paragraph). A long with an
    eligible perpetual needs both venues' fill-hour bars, even though it is held on spot:
    * January 1: the perpetual is masked from 01:00 to 23:00, so the 00:00 order defers all day.
      January 2's decision (January 1 has its daily bar) replaces it, and the new order cannot
      fill in its own hour: it fills at 01:00;
    * January 3: the perpetual is masked at 01:00 only, so the order comes due at 02:00;
    * January 5: spot is masked from 01:00 to 23:00, so there is no daily bar for January 5 and
      January 6's decision keeps the deferred order, which comes due at 00:00 on January 6."""
    day1, day3, day5 = T0, T0 + 2 * DAY, T0 + 4 * DAY
    start = month_start("2024-10")
    closes = path("50000", (hours_in("2024-10", "2025-01"), "0.0003"), noise="0.002", seed=13)
    perp_masked = day_hours(day1, range(1, 24)) + (day3 + HOUR,)
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, closes, masked=day_hours(day5, range(1, 24))),
        perpetual=PerpetualSpec(series=Series(start, closes, masked=perp_masked), funding_rate="0"),
    )
    market = load(tmp_path, World("2025-01", (btc,), {"2025-01": ("BTCUSDT",)}))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    assert not [f for f in of_kind(rows, "fill") if f["hour_ms"] < day1 + DAY]
    (superseded,) = [e for e in events(rows, "order_superseded") if e["decision_ms"] == day1]
    assert superseded["hour_ms"] == day1 + DAY
    first = of_kind(rows, "fill")[0]
    assert first["hour_ms"] == day1 + DAY + HOUR and first["venue"] == "spot"
    target = F(D(daily_by(rows)[(day1 + DAY, "BTCUSDT")]["target"]))
    open_ = spot_bar(market, "BTCUSDT", first["hour_ms"]).open
    check_fill(first, "spot", 1, floor_to(target * CAPITAL / F(open_), SPOT_STEP), open_)
    orders = {(e["decision_ms"], e["hour_ms"]) for e in events(rows, "order")}
    assert (day1 + DAY, day1 + DAY + HOUR) in orders  # the newer order, at 01:00
    assert (day3, day3 + 2 * HOUR) in orders  # deferred one hour
    assert (day5, day5 + DAY) in orders  # kept by a no-bar decision, due at 00:00
    assert daily_by(rows)[(day5 + DAY, "BTCUSDT")]["no_bar"]
    assert not [d for d, _ in orders if d == day1]  # the replaced order never filled


def two_way_world() -> World:
    """BTCUSDT rising and ETHUSDT falling, both with perpetuals (funding 0), noisy enough that
    the volatility target moves the weights below the caps."""
    perpetual = PerpetualSpec(funding_rate="0")
    btc = one_coin("BTCUSDT", "50000", "0.0003", 41, perpetual=perpetual, noise="0.008")
    eth = one_coin("ETHUSDT", "2000", "-0.0004", 42, perpetual=perpetual, noise="0.008")
    return World("2025-01", (btc, eth), {"2025-01": ("BTCUSDT", "ETHUSDT")})


def test_long_only_and_vol_variants_change_only_their_parameters(tmp_path):
    """Spec "Versions in the run": each variant is v4_main with one parameter changed. A
    v4_main cell given a variant's volatility target, signal or lookbacks writes exactly the
    variant's records (the same receipt), and each parameter does change them. The long-only arm
    never shorts where v4_main does."""
    market = load(tmp_path, two_way_world())
    variants = ("v4_long_only", "v4_vol25", "v4_vol60", "v4_faster", "v4_slower")
    runs = {
        name: cell_run(market, tmp_path, CellSpec(name, CAPITAL, 1), name=name)
        for name in ("v4_main", *variants)
    }
    main = ARMS["v4_main"]
    for name in variants:
        spec = ARMS[name]
        arm = replace(
            main, vol_target=spec.vol_target, long_only=spec.long_only, lookbacks=spec.lookbacks
        )
        assert arm.vol_target is not None and arm.lookbacks is not None
        state = run._V4Cell(market, MAIN, arm, arm.vol_target, arm.lookbacks)
        result = run._run(state, tmp_path / "out" / f"main-as-{name}")
        assert result.receipt == runs[name][0].receipt, name
        assert result.receipt != runs["v4_main"][0].receipt, name
    main_rows, long_rows = runs["v4_main"][1], runs["v4_long_only"][1]
    assert any(f["venue"] == "futures" and f["side"] == -1 for f in of_kind(main_rows, "fill"))
    assert any(r["side"] == "short" for r in of_kind(main_rows, "lifecycle"))
    assert not any(r["side"] == "short" for r in of_kind(long_rows, "lifecycle"))
    assert all(D(r["target"]) >= 0 for r in of_kind(long_rows, "daily_coin") if r["target"])


def test_the_cash_clip_cuts_an_increase_to_what_the_wallet_still_pays_for(monkeypatch, tmp_path):
    """Spec "Cash clip": free cash is the smaller of wallet USDT minus the open futures' initial
    margin and backing minus 4 x maintenance. ADAUSDT's seeded short (sold at 1000, its perpetual
    near 500, and no daily bar ever, so it keeps its leg) has about 5000 USDT of unrealised profit:
    backing and equity, not wallet USDT. The allocation puts both longs, BTCUSDT and ETHUSDT
    (spot-only), fully on spot; BTCUSDT's buy fits, and ETHUSDT's, which follows it, is cut to
    what the wallet then pays for, floored to the step and recorded."""
    start = month_start("2024-10")
    hours = hours_in("2024-10", "2025-01")
    every_day = tuple(
        stamp
        for day in range(start, month_start("2025-02"), DAY)
        for stamp in day_hours(day, range(5))
    )
    ada = CoinSpec(
        "ADAUSDT",
        Series(start, path("500", (hours, "0"), noise="0.001", seed=50), masked=every_day),
        perpetual=PerpetualSpec(funding_rate="0"),
    )
    btc = one_coin("BTCUSDT", "50000", "0.0003", 51)
    eth = one_coin("ETHUSDT", "3000", "0.0003", 52)
    universe = ("ADAUSDT", "BTCUSDT", "ETHUSDT")
    market = load(tmp_path, World("2025-01", (ada, btc, eth), {"2025-01": universe}))
    seed(
        monkeypatch,
        T0 - HOUR,
        [("ADAUSDT", seed_fill(T0 - HOUR, "futures", "ADAUSDT", -1, "10", "1000"))],
    )

    result, rows = cell_run(market, tmp_path)

    at = T0 + HOUR
    assert result.outcome == "complete"
    daily = daily_by(rows)
    assert daily[(T0, "ADAUSDT")]["no_target"] == "warming"
    assert daily[(T0, "BTCUSDT")]["target"] == daily[(T0, "ETHUSDT")]["target"] == "0.30"
    btc_fill, eth_fill = fills_at(rows, at)
    assert (btc_fill["coin"], eth_fill["coin"]) == ("BTCUSDT", "ETHUSDT")
    equity = open_equity(result, at)
    btc_open, eth_open = spot_bar(market, "BTCUSDT", at).open, spot_bar(market, "ETHUSDT", at).open
    check_fill(
        btc_fill, "spot", 1, floor_to(F(D("0.3")) * equity / F(btc_open), SPOT_STEP), btc_open
    )
    # The account the clip sees for ETHUSDT: after BTCUSDT's real fill.
    perp_open = F(perp_bar(market, "ADAUSDT", at).open)
    cash = F(CAPITAL) - F(D(btc_fill["quantity"])) * F(D(btc_fill["price"])) - F(D(btc_fill["fee"]))
    margin = 10 * perp_open / 3
    backing = cash + 10 * (1000 - perp_open)
    maintenance = F(D("0.01")) * 10 * perp_open
    free = min(cash - margin, backing - 4 * maintenance)
    need = (1 + F(COSTS["spot"].slippage_rate)) * (1 + F(COSTS["spot"].fee_rate))
    planned = floor_to(F(D("0.3")) * equity / F(eth_open), SPOT_STEP)
    assert free / need < planned * F(eth_open)  # the wallet cannot pay for the whole buy
    quantity = floor_to(free / need / F(eth_open), SPOT_STEP)
    check_fill(eth_fill, "spot", 1, quantity, eth_open)
    (cut,) = events(rows, "increase_cut")
    assert (cut["hour_ms"], cut["coin"], cut["venue"], cut["refusal"]) == (
        at,
        "ETHUSDT",
        "spot",
        None,
    )
    assert F(D(cut["wanted"])) == planned * F(eth_open)
    assert abs(F(D(cut["admitted"])) - free / need) < F(1, 10**40)
    assert F(D(cut["quantity"])) == quantity


def test_dust_back_in_the_universe_keeps_its_leg_and_its_offset_order_waits_for_the_perpetual(
    monkeypatch, tmp_path
):
    """ETHUSDT holds 2 USDT of dust (seeded), outside January's universe and inside February's.
    * Each January decision is a universe exit whose spot leg cannot be sold: a no-op. On
      January 31 spot is masked from 01:00 to 01:00 on February 1, so that day's exit is still
      pending when ETHUSDT re-enters; due at 02:00, it is skipped (``in_universe``): the
      decisions since then supersede it, and February 1 has no target (no daily bar).
    * February 2's target is 0 (fewer than 60 returns), so the order offsets the dust with a
      futures short on the eligible perpetual: it needs the perpetual, masked at 01:00, and
      waits for 02:00 (the spec's general deferral rule). The offset is below the minimum
      notional, so it is refused and recorded."""
    eth_start, end = T0, month_start("2025-03")
    closes = path("2000", ((end - eth_start) // HOUR, "0.00005"), noise="0.001", seed=60)
    jan31, feb1, feb2 = FEB - DAY, FEB, FEB + DAY
    spot_masked = day_hours(jan31, range(1, 24)) + (feb1, feb1 + HOUR)
    eth = CoinSpec(
        "ETHUSDT",
        Series(eth_start, closes, masked=spot_masked),
        perpetual=PerpetualSpec(
            series=Series(eth_start, closes, masked=(feb2 + HOUR,)), funding_rate="0"
        ),
    )
    btc = CoinSpec(
        "BTCUSDT", Series(month_start("2024-12"), ("100",) * hours_in("2024-12", "2025-02"))
    )
    universes = {"2025-01": ("BTCUSDT",), "2025-02": ("BTCUSDT", "ETHUSDT")}
    market = load(tmp_path, World("2025-02", (btc, eth), universes))
    seed(
        monkeypatch,
        T0 - HOUR,
        [("ETHUSDT", seed_fill(T0 - HOUR, "spot", "ETHUSDT", 1, "0.001", "2000"))],
    )

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    assert not [f for f in of_kind(rows, "fill") if f["timestamp_ms"] < LAST_HOUR]  # dust only
    january = [e for e in events(rows, "order") if e["coin"] == "ETHUSDT" and e["hour_ms"] < jan31]
    assert len(january) == 30 and all(e["source"] == "exit" for e in january)
    assert all(e["legs"][0]["orders"] == [] and e["legs"][0]["dust"] == "0.001" for e in january)
    (skipped,) = events(rows, "exit_skipped")
    assert skipped == {
        "type": "exit_skipped",
        "hour_ms": feb1 + 2 * HOUR,
        "coin": "ETHUSDT",
        "venue": "spot",
        "reason": "universe exit",
        "why": "in_universe",
    }
    daily = daily_by(rows)
    assert daily[(feb1, "ETHUSDT")]["no_bar"] and daily[(feb1, "ETHUSDT")]["in_universe"]
    assert daily[(feb2, "ETHUSDT")]["target"] == "0" and daily[(feb2, "ETHUSDT")]["eligible"]
    order = order_event(rows, feb2 + 2 * HOUR, "ETHUSDT")  # deferred from 01:00
    assert (order["decision_ms"], order["band"], order["eligible"]) == (feb2, "trade", True)
    assert D(order["state"]["dust"]) == D("0.001") and D(order["split"]["futures"]) < 0
    spot_leg, futures_leg = order["legs"]
    assert spot_leg["orders"] == [] and D(spot_leg["target"]) == D("0.001")  # it holds its dust
    assert futures_leg["orders"] == [] and futures_leg["refusal"] == "min_notional"
    assert D(futures_leg["target"]) == D("-0.001")


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
    # The last mark taken is the failing hour's open mark (12b: the fills have moved it).
    assert result.final_equity == result.open_marks[-1][1]
    assert of_kind(rows, "fill") != []
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
