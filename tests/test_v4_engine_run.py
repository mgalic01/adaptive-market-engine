"""V4 engine task 12: the hour loop of the V4 arms (part 12a: the loop, the open marks, the
records, the 00:00 decisions, the audit and the error paths; part 12b: the fill phase and the
window-end close; part 12c: the synthetic closes, the post-fill and funding checks and cuts,
funding, the adverse-extreme liquidation and the stops).

Each test replays a small synthetic world from ``tests/v4_synthetic.py`` through
``run_v4_cell``. ``seed`` books fills into the cell's ledger and opens their lifecycles before
the first hour, through the module's ``Ledger`` and ``Lifecycles`` names, for a test that needs a
position the rules would not make on their own (a dust holding, a profitable short). The 12a
tests check only hours and records that the fills cannot change (an open mark comes before the
hour's fills, and a daily record is the decision's, not the fill's). Every world trading in a
12b test has a funding rate of 0, so part 12c's funding cannot move what these tests pin. The 12c
tests mostly use "static" coins: a coin whose spot hours 00:00 to 04:59 are masked every day has
no daily bar (fewer than 20 usable hours), so it never gets a target and keeps exactly the legs
``seed`` gives it, which lets a test put the account where a safety rule acts.

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
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
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
    read_data_json,
    write_world,
)

from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.bars import FundingRow
from crypto_grid_bot.v4.engine import run
from crypto_grid_bot.v4.engine.allocation import clip_increases
from crypto_grid_bot.v4.engine.arms import ARMS, ArmSpec, CellSpec
from crypto_grid_bot.v4.engine.ledger import Fill, Ledger
from crypto_grid_bot.v4.engine.lifecycle import Lifecycles
from crypto_grid_bot.v4.engine.market import HourBar, Market
from crypto_grid_bot.v4.engine.numbers import to_decimal
from crypto_grid_bot.v4.engine.pending import PendingBook
from crypto_grid_bot.v4.engine.records import read_receipt, read_records
from crypto_grid_bot.v4.engine.safety import DeadMarkets, ceiling_factor, cushion_factor
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


def rising_world(*, luna_end_ms: int | None = None, eth_missing: Sequence[int] = ()) -> World:
    """BTCUSDT (with its perpetual), ETHUSDT and LUNAUSDT rising from 2024-10, all selected in
    January 2025. LUNAUSDT's data stops at ``luna_end_ms`` (a delisting); ETHUSDT's spot has no
    row at the ``eth_missing`` opens (an outage)."""
    start, hours = month_start("2024-10"), hours_in("2024-10", "2025-01")
    luna_hours = hours if luna_end_ms is None else (luna_end_ms - start) // HOUR
    coins = (
        CoinSpec(
            "BTCUSDT",
            Series(start, path("50000", (hours, "0.0002"), noise="0.002", seed=41)),
            perpetual=PerpetualSpec(),
        ),
        CoinSpec(
            "ETHUSDT",
            Series(
                start,
                path("3000", (hours, "0.0002"), noise="0.002", seed=42),
                missing=tuple(eth_missing),
            ),
        ),
        CoinSpec(
            "LUNAUSDT",
            Series(start, path("5", (luna_hours, "0.0002"), noise="0.002", seed=43)),
        ),
    )
    return World("2025-01", coins, {"2025-01": ("BTCUSDT", "ETHUSDT", "LUNAUSDT")})


def plain_book(
    market: Market, h: int, readings: dict[str, dict[int, SignalReading]], dead: Collection[str]
) -> SizingResult:
    """``size_book`` for v4_main at the decision ``h`` on the plain inputs: each coin's latest
    reading (its signal max(s, 0) without an eligible perpetual), a coin in ``dead`` at 0."""
    day, book = h - DAY, {}
    for coin, by_day in readings.items():
        reading = latest(by_day, day)
        s = D(0) if reading is None else reading.s
        s = s if market.perpetual_eligible(coin, h) else max(s, D(0))
        book[coin] = D(0) if coin in dead else s
    returns = {coin: daily_returns(market.daily(coin)) for coin in readings}
    return size_book(book, returns, day, vol_target=D("0.40"))


def test_a_dead_universe_coin_leaves_the_sizing_book_and_the_others_keep_trading(tmp_path):
    """Controller ruling (Task 15, fix 1): LUNAUSDT's data stops at 00:00 on 2025-01-08 and it
    stays in January's universe. Until the decision 168 hours after its last bar (23:00 on
    January 7), the no-bar rule keeps its signal in the book. From 00:00 on January 15 it is a
    dead market: signal 0, so full 0 and out of the common days, and no target. Read literally,
    its kept signal would hold its missing returns in the intersection, and the common days of
    the last 60 would fall below 40 on January 29, flattening BTCUSDT and ETHUSDT too; they keep
    their targets instead."""
    end = T0 + 7 * DAY
    market = load(tmp_path, rising_world(luna_end_ms=end))
    coins = ("BTCUSDT", "ETHUSDT", "LUNAUSDT")
    readings = {coin: readings_by_day(market, coin, ARMS["v4_main"]) for coin in coins}

    _, rows = cell_run(market, tmp_path)

    daily = daily_by(rows)
    first_dead = end - HOUR + 168 * HOUR + HOUR  # the last bar's open + 168 h, at 00:00
    assert first_dead == T0 + 14 * DAY
    literal_flat = 0
    for h in range(T0, month_start("2025-02"), DAY):
        luna = daily[(h, "LUNAUSDT")]
        dead = h >= first_dead
        assert luna["dead_market"] is dead and luna["in_universe"]
        assert daily[(h, "BTCUSDT")]["dead_market"] is daily[(h, "ETHUSDT")]["dead_market"] is False
        sizing = plain_book(market, h, readings, {"LUNAUSDT"} if dead else set())
        for coin in ("BTCUSDT", "ETHUSDT"):
            check_sizing(daily[(h, coin)], sizing)
            assert daily[(h, coin)]["target"] == text(sizing.weights[coin])
        if dead:
            assert (luna["signal"], luna["full"], luna["target"]) == ("0", "0", None)
            assert luna["no_bar"] and luna["no_target"] == "no_bar"
            literal = plain_book(market, h, readings, set())
            if literal.flat_reason == "insufficient_common_days":
                literal_flat += 1
                assert sizing.flat_reason is None and sizing.common_days >= 40
                assert all(D(daily[(h, c)]["target"]) > 0 for c in ("BTCUSDT", "ETHUSDT"))
        elif h > end:
            # Missing days, not yet 168 hours: the kept signal stays in the book.
            assert luna["no_bar"] and luna["target"] is None
            assert luna["signal"] == text(max(latest(readings["LUNAUSDT"], h - DAY).s, D(0)))
            assert D(luna["full"]) > 0
    assert literal_flat == 3  # January 29 to 31 would have been flat


def test_a_coin_missing_three_days_stays_in_the_sizing_book_with_its_kept_signal(tmp_path):
    """The no-bar rule for missing days, under the dead-market ruling: ETHUSDT's spot has no row
    from 00:00 on 2025-01-10 to 23:00 on January 12, 72 hours, fewer than 168. The decisions of
    January 11 to 13 give it no target, keep its signal (positive) and its full weight in the
    book, and its missing returns thin the common days that BTCUSDT's weight is sized on."""
    gap = T0 + 9 * DAY
    market = load(tmp_path, rising_world(eth_missing=range(gap, gap + 72 * HOUR, HOUR)))
    coins = ("BTCUSDT", "ETHUSDT", "LUNAUSDT")
    readings = {coin: readings_by_day(market, coin, ARMS["v4_main"]) for coin in coins}

    _, rows = cell_run(market, tmp_path)

    daily = daily_by(rows)
    for h in (gap + DAY, gap + 2 * DAY, gap + 3 * DAY):
        eth = daily[(h, "ETHUSDT")]
        assert eth["no_bar"] and not eth["dead_market"] and eth["target"] is None
        assert eth["reading_day_ms"] == gap - DAY
        assert D(eth["signal"]) > 0 and D(eth["full"]) > 0
        sizing = plain_book(market, h, readings, set())
        assert sizing.common_days is not None and sizing.common_days < 60
        check_sizing(daily[(h, "BTCUSDT")], sizing)
        assert daily[(h, "BTCUSDT")]["target"] == text(sizing.weights["BTCUSDT"])
    assert not any(record["dead_market"] for record in daily.values())


@pytest.mark.parametrize("status", ["missing_slot", "missing_file", "unreadable_file"])
def test_the_last_day_before_an_incomplete_funding_month_bars_the_perpetual(status, tmp_path):
    """Spec "Data": no futures exposure is held in an incomplete funding month (any status
    that is present and not ``complete``). The decision at 00:00 of the previous month's last
    day already has no eligible perpetual, so its signal is max(s, 0); the month itself has none
    (point in time), and futures return from the first decision whose fill falls after it. The
    window's last month has no next month to judge: the window end closes everything."""
    hours = hours_in("2024-10", "2025-03")
    btc = CoinSpec(
        "BTCUSDT",
        Series(month_start("2024-10"), path("50000", (hours, "-0.0003"), noise="0.003", seed=6)),
        perpetual=PerpetualSpec(months={"2025-02": status}),
    )
    world = World("2025-03", (btc,), every_month("2025-01", "2025-03", ("BTCUSDT",)))
    market = load(tmp_path, world)
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


def test_a_missing_next_month_status_does_not_bar_the_perpetual_at_the_last_day_decision(
    tmp_path,
):
    """Controller ruling (the look-ahead fix): the data step lists funding months only through
    the month of the perpetual's last bar, so a missing status means the perpetual has no bars
    and no slots in that month. It counts as complete, as the spec's slot rule says; reading it
    as incomplete would reveal at the last-day decision that the perpetual stops trading. The
    perpetual here has its last bar at 09:00 on January 31 and no February status, while spot
    trades on. The decision at 00:00 on January 31 keeps the perpetual eligible (a short signal
    stays short), records no status, and schedules no funding-month exit and no synthetic
    funding-month close at the February midnight."""
    hours = hours_in("2024-10", "2025-02")
    start = month_start("2024-10")
    closes = path("50000", (hours, "-0.0003"), noise="0.003", seed=6)
    dies = LAST_JAN + 10 * HOUR  # the perpetual's first hour without a bar
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, closes),
        perpetual=PerpetualSpec(series=Series(start, closes[: (dies - start) // HOUR])),
    )
    world = World("2025-02", (btc,), every_month("2025-01", "2025-02", ("BTCUSDT",)))
    market = load(tmp_path, world)
    perpetual = market.coin("BTCUSDT").perpetual
    assert perpetual is not None and perpetual.store.last_open_at_or_before(FEB) == dies - HOUR
    assert market.funding_month("BTCUSDT", "2025-01") == "complete"
    assert market.funding_month("BTCUSDT", "2025-02") is None

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    at = daily_by(rows)[(LAST_JAN, "BTCUSDT")]
    assert at["next_month"] == "2025-02" and at["next_month_status"] is None
    assert at["perpetual_eligible"] and at["eligible"] and not at["funding_month_exit"]
    assert D(at["s"]) < 0 and at["signal"] == at["s"]  # not clamped to max(s, 0)
    # February has no status either, so its eligibility is the 168-hour bar test alone: the last
    # bar opens at 09:00 on January 31, which is within 168 hours of the decision on February 7
    # (00:00) and not of the one on February 8.
    daily = daily_by(rows)
    assert daily[(FEB, "BTCUSDT")]["perpetual_eligible"]
    assert daily[(FEB + 6 * DAY, "BTCUSDT")]["perpetual_eligible"]
    assert not daily[(FEB + 7 * DAY, "BTCUSDT")]["perpetual_eligible"]
    assert events(rows, "exit_scheduled") == []
    assert not [f for f in of_kind(rows, "fill") if f["reason"] == "funding-month exit"]
    assert not [e for e in events(rows, "synthetic_closes") if e["hour_ms"] == FEB]


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
    assert order["decision_ms"] == LAST_JAN  # the decision whose target the buy uses
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
    # The record names the coin's perpetual and its multiplier, null without one.
    expected = ("BTCUSDT", 1) if with_perpetual else (None, None)
    assert (lifecycle["perpetual"], lifecycle["multiplier"]) == expected


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
    # Its futures quantities are in contracts of the perpetual the record names.
    assert (lifecycles[0]["perpetual"], lifecycles[0]["multiplier"]) == (
        perpetual.symbol,
        multiplier,
    )


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
    variant's records, but for the cell its outcome record names, and each parameter does change
    them. The long-only arm never shorts where v4_main does."""

    def unlabelled(rows: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, dict[str, Any]]]:
        """The records with the outcome's cell label set aside (Task 14: it names the cell)."""
        return [(kind, {**r, "cell": None} if kind == "outcome" else r) for kind, r in rows]

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
        out = tmp_path / "out" / f"main-as-{name}"
        result = run._run(state, out)
        rows = list(read_records(out / run.RECORDS_FILE, result.receipt))
        assert rows[-1][1]["cell"] == run.cell_record(MAIN)
        assert runs[name][1][-1][1]["cell"] == run.cell_record(CellSpec(name, CAPITAL, 1))
        assert unlabelled(rows) == unlabelled(runs[name][1]), name
        assert unlabelled(rows) != unlabelled(runs["v4_main"][1]), name
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


# ---- 12c: synthetic closes, funding, cuts and stops ---------------------------------------

DEC = month_start("2024-12")
JAN_END = month_start("2025-02")  # the open after January's last hour
CRASH = T0 + 9 * DAY + 10 * HOUR  # 2025-01-10 10:00, the bar in which a static price jumps
AFTER = CRASH + HOUR  # the first open that shows the jump
FUND_HOUR = T0 + 9 * DAY + 8 * HOUR  # 2025-01-10 08:00
FUNDED = FUND_HOUR + 30_000  # a funding record 30 seconds after that slot
FEE = {venue: F(COSTS[venue].fee_rate) for venue in ("spot", "futures")}
PENALTY_LONG, PENALTY_SHORT = F(9, 10), F(11, 10)  # spec "Delisting": 10% against the leg


def static_mask(end: str) -> tuple[int, ...]:
    """Hours 00:00 to 04:59 of every day from December to the end of ``end``: a coin masked so
    has fewer than 20 usable hours a day, so no daily bar and never a target."""
    days = range(DEC, DEC + hours_in("2024-12", end) * HOUR, DAY)
    return tuple(stamp for day in days for stamp in day_hours(day, range(5)))


def flat(price: str, end: str = "2025-01") -> tuple[Decimal, ...]:
    """Hourly closes at ``price`` from December to the end of ``end``."""
    return path(price, (hours_in("2024-12", end), "0"))


def jump(price: str, at_ms: int, rate: str, end: str = "2025-01") -> tuple[Decimal, ...]:
    """Closes at a flat ``price`` from December; the bar that opens at ``at_ms`` closes ``rate``
    away from it, and the price stays there."""
    before = (at_ms - DEC) // HOUR
    return path(price, (before, "0"), (1, rate), (hours_in("2024-12", end) - before - 1, "0"))


def static_coin(
    symbol: str,
    closes: Sequence[Decimal],
    *,
    perpetual: bool = False,
    funding: str = "0",
    months: Mapping[str, str] | None = None,
    perp_masked: Sequence[int] = (),
    perp_hours: int | None = None,
    perp_extremes: Mapping[int, tuple[str, str]] | None = None,
    funding_rows: Sequence[FundingRow] | None = None,
    spot_dark: Sequence[int] = (),
    spot_extremes: Mapping[int, tuple[str, str]] | None = None,
    spot_rules: VenueRules = SPOT_RULES,
    end: str = "2025-01",
) -> CoinSpec:
    """A static coin from December (module docstring) at ``closes``, with ``spot_rules``. With
    ``perpetual``, its perpetual has the same closes (only the first ``perp_hours``, for one that
    dies early), its own masks and extremes, the funding rate ``funding`` at every slot (or
    exactly the records ``funding_rows``) and the given month statuses."""
    masked = sorted(set(static_mask(end)) | set(spot_dark))
    spot = Series(DEC, closes, masked=tuple(masked), extremes=dict(spot_extremes or {}))
    if not perpetual:
        return CoinSpec(symbol, spot, spot_rules=spot_rules)
    perp_closes = closes if perp_hours is None else closes[:perp_hours]
    series = Series(DEC, perp_closes, masked=tuple(perp_masked), extremes=dict(perp_extremes or {}))
    spec = PerpetualSpec(
        series=series,
        funding_rate=funding,
        funding=None if funding_rows is None else tuple(funding_rows),
        months=dict(months or {}),
    )
    return CoinSpec(symbol, spot, spec, spot_rules=spot_rules)


def static_world(coins: Sequence[CoinSpec]) -> World:
    """January 2025, every coin selected."""
    return World("2025-01", tuple(coins), {"2025-01": tuple(coin.symbol for coin in coins)})


def hourly_at(rows: Iterable[tuple[str, dict[str, Any]]], hour_ms: int) -> dict[str, Any]:
    (found,) = [h for h in of_kind(rows, "hourly") if h["open_ms"] == hour_ms]
    return found


def residuals_hold(rows: Iterable[tuple[str, dict[str, Any]]]) -> bool:
    return all(D(h["equity_residual"]).copy_abs() <= D("1e-18") for h in of_kind(rows, "hourly"))


def downtrend(start: str = "2024-10", end: str = "2025-01") -> tuple[Decimal, ...]:
    """BTCUSDT's falling closes: shorted on its perpetual from 01:00 on January 1, at -0.30."""
    return path("50000", (hours_in(start, end), "-0.0003"), noise="0.002", seed=12)


def test_funding_is_charged_on_the_held_quantity_at_the_open(monkeypatch, tmp_path):
    """Spec "Shorts on futures": each funding record is charged on the contracts held at its
    time, times the published rate, times the perpetual's open of the settlement hour (its
    carried mark, the last close, when that hour is masked), after the hour's trading. Longs pay
    a positive rate and shorts receive it. BTCUSDT shorts from 01:00 on January 1, so January
    1's 00:00 record finds it flat and charges nothing; its perpetual is masked at 08:00 on
    January 5. ETHUSDT (static) holds a seeded long. The wallet and the lifecycles carry every
    payment."""
    start = month_start("2024-10")
    masked_slot = T0 + 4 * DAY + 8 * HOUR
    closes = downtrend()
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, closes),
        PerpetualSpec(series=Series(start, closes, masked=(masked_slot,)), funding_rate="0.0003"),
    )
    eth = static_coin("ETHUSDT", flat("100"), perpetual=True, funding="0.0002")
    market = load(tmp_path, static_world((btc, eth)))
    seeded = [("futures", "ETHUSDT", "2")]
    seed(
        monkeypatch,
        T0 - HOUR,
        [("ETHUSDT", seed_fill(T0 - HOUR, "futures", "ETHUSDT", 1, "2", "100"))],
    )

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    records = {(r["perpetual"], r["timestamp_ms"]): r for r in of_kind(rows, "funding")}
    charged = 0
    for hour in range(T0, JAN_END, HOUR):
        for perpetual, time_ms, rate in market.funding_events(hour):
            held = holdings(rows, time_ms, seeded).get(("futures", perpetual), F(0))
            if held == 0:
                assert (perpetual, time_ms) not in records  # a flat leg is not charged
                continue
            record = records[perpetual, time_ms]
            spec = market.coin(perpetual).perpetual
            assert spec is not None
            bar = spec.store.bar(hour)
            price = bar.open if bar is not None else spec.store.last_close_before(hour)
            assert price is not None
            assert (record["hour_ms"], record["coin"]) == (hour, perpetual)
            assert F(D(record["quantity"])) == held and D(record["rate"]) == rate
            assert D(record["price"]) == price and record["carried"] is (bar is None)
            assert F(D(record["amount"])) == -held * F(rate) * F(price)
            charged += 1
    assert len(records) == charged
    assert ("BTCUSDT", T0) not in records and ("ETHUSDT", T0) in records
    assert records["BTCUSDT", masked_slot]["carried"] is True
    btc_paid = [D(r["amount"]) for r in records.values() if r["coin"] == "BTCUSDT"]
    eth_paid = [D(r["amount"]) for r in records.values() if r["coin"] == "ETHUSDT"]
    assert btc_paid and all(amount > 0 for amount in btc_paid)  # the short receives
    assert eth_paid and all(amount < 0 for amount in eth_paid)  # the long pays
    total = F(0)
    for coin, paid in (("BTCUSDT", btc_paid), ("ETHUSDT", eth_paid)):
        lifecycles = [r for r in of_kind(rows, "lifecycle") if r["coin"] == coin]
        assert sum(F(D(r["funding"])) for r in lifecycles) == sum(map(F, paid))
        assert sum(F(D(r["venues"]["futures"]["funding"])) for r in lifecycles) == sum(map(F, paid))
        total += sum(map(F, paid))
    assert F(result.final_after_close) == cash_after(rows, JAN_END, F(CAPITAL)) + total


@pytest.mark.parametrize("case", ["margin cut", "ceiling cut", "funding cut", "liquidation"])
def test_a_crash_at_3x_cuts_or_liquidates_as_specified(case, monkeypatch, tmp_path):
    """Spec "Safety", on hedged accounts of static coins: spot held (spot does not back futures),
    a BTCUSDT short on its perpetual, and the wallet's rest, all seeded.
    * margin cut: BTCUSDT jumps 17% in the bar at CRASH. At the next open the margin ratio is
      below 3, but the account is not liquidated and gross is under 3. The post-fill check cuts
      the tradable futures to ``held x k``, ``k = (backing / 4 - untradable maintenance) /
      tradable maintenance`` (SOLUSDT's small short is masked there, so untradable and kept),
      computed exactly and floored to the step, by a reduce-only buy at that open with slippage
      and fee. The new mark is back near 4.
    * ceiling cut: a bigger short and a 5% jump take gross exposure above 3 (the ratio is fine).
      Every tradable position is cut by ``k' = (2.7 x equity - untradable gross) / tradable
      gross``: the short by a buy and ETHUSDT's spot by a sale, alphabetical, at that open.
      SOLUSDT's spot (masked then) and DOGEUSDT's unsellable dust are untradable and stay.
    * funding cut: the price never moves, but a funding record of -18% on the short, 30 seconds
      after 08:00 on January 10, takes the ratio below 3. The checks after the payment cut the
      short at that hour's open, stamped at the record's time.
    * liquidation: the short's bar at CRASH has a high of 120 though it opens and closes at 100,
      so only the adverse-extreme check sees it, every leg at its extreme at once (spot at its
      low of 95 too). Backing at or below maintenance there ends the cell at those prices."""
    rate = {"margin cut": "0.17", "ceiling cut": "0.05"}.get(case, "0")
    high = {CRASH: ("120", "100")} if case == "liquidation" else {}
    low = {CRASH: ("100", "95")} if case == "liquidation" else {}
    records = [FundingRow(FUNDED, D("-0.18"), 8)] if case == "funding cut" else None
    btc = static_coin(
        "BTCUSDT",
        jump("100", CRASH, rate),
        perpetual=True,
        perp_extremes=high,
        funding_rows=records,
    )
    coins = [btc]
    if case == "ceiling cut":
        spot = {"ETHUSDT": ("50", "100"), "SOLUSDT": ("10", "100"), "DOGEUSDT": ("20", "0.1")}
        short = "220"
        coins += [
            static_coin("ETHUSDT", flat("100")),
            static_coin("SOLUSDT", flat("100"), spot_dark=(AFTER,)),
            static_coin("DOGEUSDT", flat("0.1")),
        ]
    else:
        spot, short = {"ETHUSDT": ("90", "100")}, "50"
        coins.append(static_coin("ETHUSDT", flat("100"), spot_extremes=low))
    fills = [(c, seed_fill(T0 - HOUR, "spot", c, 1, qty, p)) for c, (qty, p) in spot.items()]
    fills.append(("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, short, "100")))
    if case == "margin cut":
        coins.append(static_coin("SOLUSDT", flat("100"), perpetual=True, perp_masked=(AFTER,)))
        fills.append(("SOLUSDT", seed_fill(T0 - HOUR, "futures", "SOLUSDT", -1, "5", "100")))
    market = load(tmp_path, static_world(coins))
    seed(monkeypatch, T0 - HOUR, fills)

    result, rows = cell_run(market, tmp_path)

    q = F(D(short))
    value = {coin: F(D(qty)) * F(D(p)) for coin, (qty, p) in spot.items()}  # flat prices
    cash = F(CAPITAL) - sum(value.values())
    assert residuals_hold(rows)
    if case == "liquidation":
        final = cash + 90 * 95 + q * (100 - 120)
        assert result.outcome == "liquidated" and result.reason is None
        assert result.stop_ms == CRASH and F(result.final_equity) == final
        assert result.final_after_close is None and of_kind(rows, "fill") == []
        assert result.open_marks[-1] == (CRASH, D(CAPITAL), True)  # the open saw nothing
        outcome = rows[-1][1]
        assert outcome["check"] == "adverse_extremes" and F(D(outcome["mark"]["equity"])) == final
        assert F(D(outcome["mark"]["backing"])) <= F(D(outcome["mark"]["maintenance"]))
        assert F(D(hourly_at(rows, CRASH)["equity"])) == final
        ended = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
        assert all(r["exit_reason"] == "liquidation" and r["censored"] for r in ended.values())
        assert {r["exit_ms"] for r in ended.values()} == {CRASH}
        assert F(D(ended["BTCUSDT"]["unrealised"])) == q * (100 - 120)
        assert F(D(ended["ETHUSDT"]["unrealised"])) == 90 * (95 - 100)
        return
    assert result.outcome == "complete"
    kind = "ceiling_cut" if case == "ceiling cut" else "margin_cut"
    hour, point, stamp = (
        (FUND_HOUR, "funding", FUNDED) if case == "funding cut" else (AFTER, "post_fill", AFTER)
    )
    cuts = [e for e in of_kind(rows, "event") if e["type"] in ("margin_cut", "ceiling_cut")]
    assert [(e["type"], e["hour_ms"], e["check"], e["timestamp_ms"]) for e in cuts] == [
        (kind, hour, point, stamp)
    ]
    (cut,) = cuts
    booked = fills_at(rows, stamp)
    price = (1 + F(D(rate))) * 100  # BTCUSDT's open at the cut: 117, 105 or 100
    backing = cash + q * (100 - price)
    if case == "funding cut":
        (payment,) = of_kind(rows, "funding")
        assert F(D(payment["amount"])) == q * F(D("-0.18")) * 100  # the short pays -18%
        backing += F(D(payment["amount"]))
    maintenance = F(D("0.01")) * q * price
    if case == "ceiling cut":
        equity = backing + sum(value.values())
        untradable = value["SOLUSDT"] + value["DOGEUSDT"]
        tradable = value["ETHUSDT"] + q * price
        assert untradable + tradable > 3 * equity and backing > 3 * maintenance
        k = ceiling_factor(to_decimal(equity), to_decimal(untradable), to_decimal(tradable))
        assert k is not None and 0 < k < 1
        futures, sale = booked  # BTCUSDT before ETHUSDT
        check_fill(futures, "futures", 1, q - floor_to(q * F(k), FUTURES_STEP), to_decimal(price))
        check_fill(sale, "spot", -1, 50 - floor_to(50 * F(k), SPOT_STEP), D(100))
        assert sale["coin"] == "ETHUSDT"
        assert futures["reason"] == sale["reason"] == "ceiling cut"
        assert D(cut["factor"]) == k and F(D(cut["equity"])) == equity
        assert F(D(cut["tradable_gross"])) == tradable
        assert F(D(cut["untradable_gross"])) == untradable
        assert cut["untradable"] == [["spot", "DOGEUSDT"], ["spot", "SOLUSDT"]]
        assert D(hourly_at(rows, AFTER)["gross"]) < D("2.71")  # 2.7 before the cut's costs
    else:
        untradable = F(D("0.01")) * 5 * 100 if case == "margin cut" else F(0)
        assert maintenance + untradable < backing < 3 * (maintenance + untradable)
        k = cushion_factor(to_decimal(backing), to_decimal(untradable), to_decimal(maintenance))
        assert k is not None and 0 < k < 1
        (fill,) = booked
        check_fill(fill, "futures", 1, q - floor_to(q * F(k), FUTURES_STEP), to_decimal(price))
        assert (fill["coin"], fill["reason"], fill["hour_ms"]) == ("BTCUSDT", "margin cut", hour)
        assert D(cut["factor"]) == k and F(D(cut["backing"])) == backing
        assert F(D(cut["tradable_maintenance"])) == maintenance
        assert F(D(cut["untradable_maintenance"])) == untradable
        assert cut["untradable"] == ([["futures", "SOLUSDT"]] if case == "margin cut" else [])
        assert 3 < D(hourly_at(rows, hour)["margin_ratio"]) < 4  # near 4, less the cut's costs
    assert [(leg["coin"], leg["venue"]) for leg in cut["legs"]] == [
        (f["coin"], f["venue"]) for f in booked
    ]
    # A partial cut ends no lifecycle: each runs to the window end.
    assert {r["exit_reason"] for r in of_kind(rows, "lifecycle")} <= {
        "window end",
        "window end (dust)",
    }


@pytest.mark.parametrize("case", ["nothing tradable", "still breached"])
def test_a_margin_cushion_that_cannot_be_restored_ends_the_cell(case, monkeypatch, tmp_path):
    """Spec "Safety", the cushion cannot be restored. As in the margin-cut case, BTCUSDT's short
    jumps 17% at CRASH, but its perpetual is masked at the next open: it cannot trade there and
    is valued at its carried mark, the jump's close.
    * nothing tradable: no futures position can trade, so the post-fill check ends the cell with
      ``limit_unrestorable``, reason ``margin_cushion``, before any cut.
    * still breached: a small SOLUSDT short can trade, but the masked leg's maintenance alone
      exceeds backing / 4, so k <= 0 closes every tradable futures position, and the ratio is
      still below 3 at the new mark. SOLUSDT's lifecycle ends with the cut ("margin cut").
    The others are censored at the stopping check's prices, and that mark is the final equity."""
    eth = static_coin("ETHUSDT", flat("100"))
    btc = static_coin("BTCUSDT", jump("100", CRASH, "0.17"), perpetual=True, perp_masked=(AFTER,))
    coins = [btc, eth]
    fills = [
        ("ETHUSDT", seed_fill(T0 - HOUR, "spot", "ETHUSDT", 1, "90", "100")),
        ("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "50", "100")),
    ]
    if case == "still breached":
        coins.append(static_coin("SOLUSDT", flat("100"), perpetual=True))
        fills.append(("SOLUSDT", seed_fill(T0 - HOUR, "futures", "SOLUSDT", -1, "5", "100")))
    market = load(tmp_path, static_world(coins))
    seed(monkeypatch, T0 - HOUR, fills)

    result, rows = cell_run(market, tmp_path)

    cash, untradable = F(1000), F(D("0.01")) * 50 * 117
    assert result.outcome == "limit_unrestorable" and result.reason == "margin_cushion"
    assert result.stop_ms == AFTER and result.final_after_close is None
    assert result.open_marks[-1][0] == AFTER and result.open_marks[-1][2] is False  # carried
    (cut,) = events(rows, "margin_cut")
    assert cut["hour_ms"] == AFTER and cut["untradable"] == [["futures", "BTCUSDT"]]
    assert F(D(cut["untradable_maintenance"])) == untradable
    outcome = rows[-1][1]
    ended = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
    if case == "nothing tradable":
        assert cut["factor"] is None and cut["legs"] == []
        assert of_kind(rows, "fill") == [] and outcome["check"] == "post_fill"
        final = cash + 90 * 100 + 50 * (100 - 117)
    else:
        backing = cash + 50 * (100 - 117)
        k = cushion_factor(to_decimal(backing), to_decimal(untradable), D(5))
        assert k is not None and k <= 0 and D(cut["factor"]) == k
        (fill,) = of_kind(rows, "fill")
        check_fill(fill, "futures", 1, F(5), D(100))  # the whole tradable short
        assert (fill["coin"], fill["reason"], fill["hour_ms"]) == ("SOLUSDT", "margin cut", AFTER)
        assert outcome["check"] == "post_fill_margin_cut"
        sol = ended.pop("SOLUSDT")
        assert (sol["exit_reason"], sol["exit_ms"], sol["censored"]) == ("margin cut", AFTER, False)
        final = cash_after(rows, AFTER, cash) + 90 * 100 + 50 * (100 - 117)
        assert F(D(outcome["mark"]["backing"])) < 3 * F(D(outcome["mark"]["maintenance"]))
    assert F(result.final_equity) == final and F(D(outcome["mark"]["equity"])) == final
    assert set(ended) == {"BTCUSDT", "ETHUSDT"}
    assert all(r["censored"] and r["exit_reason"] == "limit_unrestorable" for r in ended.values())
    assert F(D(ended["BTCUSDT"]["unrealised"])) == 50 * (100 - 117)
    assert residuals_hold(rows)


@pytest.mark.parametrize("case", ["nothing tradable", "still breached"])
def test_a_ceiling_that_cannot_be_restored_ends_the_cell(case, monkeypatch, tmp_path):
    """Spec "Safety", the 3x limit cannot be restored. BTCUSDT's large short (static) jumps 10% in
    the bar at CRASH and its perpetual is masked at the next open, where gross is above 3 while the
    margin ratio is fine. SOLUSDT holds a small short.
    * nothing tradable: SOLUSDT's perpetual is masked too, so no position can trade, and the
      post-fill check ends the cell with ``limit_unrestorable``, reason ``ceiling``, before any
      cut.
    * still breached: SOLUSDT can trade, but BTCUSDT's untradable gross alone exceeds 2.7 x
      equity, so k' <= 0 closes every tradable position, and gross is still above 3 at the new
      mark. SOLUSDT's lifecycle ends with the cut ("ceiling cut")."""
    btc = static_coin("BTCUSDT", jump("100", CRASH, "0.10"), perpetual=True, perp_masked=(AFTER,))
    sol_masked = (AFTER,) if case == "nothing tradable" else ()
    sol = static_coin("SOLUSDT", flat("100"), perpetual=True, perp_masked=sol_masked)
    market = load(tmp_path, static_world((btc, sol)))
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "250", "100")),
            ("SOLUSDT", seed_fill(T0 - HOUR, "futures", "SOLUSDT", -1, "10", "100")),
        ],
    )

    result, rows = cell_run(market, tmp_path)

    equity, untradable = F(CAPITAL) + 250 * (100 - 110), F(250 * 110)
    assert result.outcome == "limit_unrestorable" and result.reason == "ceiling"
    assert result.stop_ms == AFTER and result.final_after_close is None
    assert not events(rows, "margin_cut")  # the ratio was fine
    (cut,) = events(rows, "ceiling_cut")
    assert cut["hour_ms"] == AFTER and F(D(cut["equity"])) == equity
    assert F(D(cut["untradable_gross"])) >= untradable
    outcome = rows[-1][1]
    ended = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
    if case == "nothing tradable":
        assert cut["factor"] is None and cut["legs"] == []
        assert cut["untradable"] == [["futures", "BTCUSDT"], ["futures", "SOLUSDT"]]
        assert of_kind(rows, "fill") == [] and outcome["check"] == "post_fill"
        final = equity
    else:
        k = ceiling_factor(to_decimal(equity), to_decimal(untradable), D(1000))
        assert k is not None and k <= 0 and D(cut["factor"]) == k
        (fill,) = of_kind(rows, "fill")
        check_fill(fill, "futures", 1, F(10), D(100))  # the whole tradable short
        assert (fill["coin"], fill["reason"], fill["hour_ms"]) == ("SOLUSDT", "ceiling cut", AFTER)
        assert outcome["check"] == "post_fill_ceiling_cut"
        sol_life = ended.pop("SOLUSDT")
        assert (sol_life["exit_reason"], sol_life["censored"]) == ("ceiling cut", False)
        final = cash_after(rows, AFTER, F(CAPITAL)) + 250 * (100 - 110)
        assert F(D(outcome["mark"]["gross_notional"])) > 3 * final  # still above 3
    assert F(result.final_equity) == final == F(D(outcome["mark"]["equity"]))
    assert set(ended) == {"BTCUSDT"} | ({"SOLUSDT"} if case == "nothing tradable" else set())
    assert all(r["exit_reason"] == "limit_unrestorable" and r["censored"] for r in ended.values())
    assert residuals_hold(rows)


@pytest.mark.parametrize("case", ["still breached", "restored anyway"])
def test_a_cut_sale_the_filters_refuse_is_a_required_fill_if_the_limit_stays_breached(
    case, monkeypatch, tmp_path
):
    """Spec "Safety": the limit is also unrestorable when "a fill the rules require" cannot be
    made. ETHUSDT's spot (static) has a minimum notional of 3,000 USDT: its 5,000 USDT holding can
    be sold, but the ceiling cut's sale of part of it, under 3,000, cannot, so the leg stays held,
    not as dust. BTCUSDT's short (static) jumps at CRASH and takes gross above 3 at the next open.
    * still breached: BTCUSDT's perpetual is masked there, so ETHUSDT is the only tradable leg;
      its refused sale leaves gross above 3, and the cell ends ``limit_unrestorable`` with reason
      ``required_fill``.
    * restored anyway: BTCUSDT can trade, and its cut alone brings gross under 3, so the refused
      sale stops nothing."""
    eth = static_coin("ETHUSDT", flat("100"), spot_rules=replace(SPOT_RULES, min_notional=D(3000)))
    if case == "still breached":
        short, rate, masked = "180", "0.10", (AFTER,)
    else:
        short, rate, masked = "220", "0.05", ()
    btc = static_coin("BTCUSDT", jump("100", CRASH, rate), perpetual=True, perp_masked=masked)
    market = load(tmp_path, static_world((btc, eth)))
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("ETHUSDT", seed_fill(T0 - HOUR, "spot", "ETHUSDT", 1, "50", "100")),
            ("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, short, "100")),
        ],
    )

    result, rows = cell_run(market, tmp_path)

    q, price = F(D(short)), (1 + F(D(rate))) * 100
    equity = F(5000) + 50 * 100 + q * (100 - price)
    (cut,) = events(rows, "ceiling_cut")
    assert cut["hour_ms"] == AFTER and F(D(cut["equity"])) == equity
    (eth_leg,) = [leg for leg in cut["legs"] if leg["coin"] == "ETHUSDT"]
    kept = F(D(eth_leg["target"]))
    assert 0 < kept < 50 and (50 - kept) * 100 < 3000  # a required sale below the minimum
    assert eth_leg["orders"] == [] and eth_leg["unfilled"] is True
    assert eth_leg["refusal"] is None and D(eth_leg["dust"]) == 0  # held, not dust
    assert not [f for f in fills_at(rows, AFTER) if f["coin"] == "ETHUSDT"]
    if case == "still breached":
        assert cut["untradable"] == [["futures", "BTCUSDT"]]
        assert result.outcome == "limit_unrestorable" and result.reason == "required_fill"
        assert result.stop_ms == AFTER and rows[-1][1]["check"] == "post_fill_ceiling_cut"
        assert of_kind(rows, "fill") == [] and F(result.final_equity) == equity
        assert F(D(rows[-1][1]["mark"]["gross_notional"])) > 3 * equity
    else:
        (btc_leg,) = [leg for leg in cut["legs"] if leg["coin"] == "BTCUSDT"]
        assert btc_leg["unfilled"] is False and btc_leg["orders"]
        assert result.outcome == "complete" and D(hourly_at(rows, AFTER)["gross"]) < 3
    assert residuals_hold(rows)


@pytest.mark.parametrize("close", ["at 01:00", "synthetic, no bar"])
def test_a_funding_month_close_is_replaced_when_the_latest_target_is_long(close, tmp_path):
    """Spec "Data" and "Sizing": a long's target moves to spot, and only the latest target ever
    produces the replacement buy, whichever side the closed futures leg was on. BTCUSDT falls and
    is short on its perpetual through January, then jumps 60% at 12:00 on January 30, so the
    decision at 00:00 on January 31 (no eligible perpetual: February's funding month is
    incomplete) gives it a long target. Its funding-month exit closes the short, and the spot buy
    follows from that target:
    * at 01:00: the short closes at 01:00 on January 31 and the buy fills in the same batch;
    * synthetic, no bar: the perpetual has no bar before February, so the short closes in the
      synthetic batch at 00:00 on February 1; January 31 has no daily bar, so February 1's
      decision gives no newer target, and the buy is placed at 00:00 from January 31's target."""
    start = month_start("2024-10")
    before = (LAST_JAN - DAY + 12 * HOUR - start) // HOUR
    rest = hours_in("2024-10", "2025-02") - before - 1
    legs = ((before, "-0.0003"), (1, "0.6"), (rest, "0.0001"))
    closes = path("50000", *legs, noise="0.002", seed=12)
    synthetic = close != "at 01:00"
    spot_masked = day_hours(LAST_JAN, range(18, 24)) if synthetic else ()
    perp_masked = day_hours(LAST_JAN, range(1, 24)) if synthetic else ()
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, closes, masked=spot_masked),
        PerpetualSpec(
            series=Series(start, closes, masked=perp_masked),
            months={"2025-02": "missing_slot"},
            funding_rate="0",
        ),
    )
    universes = every_month("2025-01", "2025-02", ("BTCUSDT",))
    market = load(tmp_path, World("2025-02", (btc,), universes))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    daily = daily_by(rows)
    assert D(daily[(LAST_JAN - DAY, "BTCUSDT")]["target"]) < 0  # short until the jump
    last_day = daily[(LAST_JAN, "BTCUSDT")]
    assert last_day["funding_month_exit"] and not last_day["eligible"]
    assert D(last_day["target"]) > 0
    held = holdings(rows, LAST_JAN)[("futures", "BTCUSDT")]
    assert held < 0  # the leg the funding-month exit closes is a short
    at = FEB if synthetic else LAST_JAN + HOUR
    (closed,) = [
        f for f in of_kind(rows, "fill") if f["venue"] == "futures" and f["hour_ms"] >= LAST_JAN
    ]
    assert (closed["hour_ms"], closed["side"], closed["reason"]) == (at, 1, "funding-month exit")
    assert F(D(closed["quantity"])) == -held
    assert [e["hour_ms"] for e in events(rows, "replacement_scheduled")] == [at]
    assert events(rows, "replacement_not_needed") == []
    order = order_event(rows, at, "BTCUSDT")
    assert (order["source"], order["decision_ms"]) == ("replacement buy", LAST_JAN)
    assert order["target"] == last_day["target"]
    (buy,) = [f for f in fills_at(rows, at) if f["venue"] == "spot"]
    assert (buy["side"], buy["reason"]) == (1, "replacement buy")
    if synthetic:
        assert daily[(FEB, "BTCUSDT")]["no_bar"] and daily[(FEB, "BTCUSDT")]["target"] is None


def test_a_dead_market_at_an_incomplete_months_first_midnight_closes_once_as_a_delisting(
    monkeypatch, tmp_path
):
    """A leg due on both counts at one instant: BTCUSDT's perpetual (static, a seeded short) has
    its last bar at 23:00 on January 24, so its dead-market close is due at 00:00 on February 1,
    the instant of the synthetic close of February's incomplete funding month as well. The leg
    closes once, as a delisting, and the coin takes the dead market's rule only: no replacement
    event of any kind."""
    dies = FEB - 7 * DAY  # the perpetual's first hour without a bar: 00:00 on January 25
    btc = static_coin(
        "BTCUSDT",
        flat("100", end="2025-02"),
        perpetual=True,
        perp_hours=(dies - DEC) // HOUR,
        months={"2025-02": "missing_slot"},
        end="2025-02",
    )
    market = load(
        tmp_path, World("2025-02", (btc,), every_month("2025-01", "2025-02", ("BTCUSDT",)))
    )
    seed(
        monkeypatch,
        T0 - HOUR,
        [("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "10", "100"))],
    )

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    assert daily_by(rows)[(LAST_JAN, "BTCUSDT")]["funding_month_exit"]  # the second count
    (batch,) = events(rows, "synthetic_closes")
    assert batch["hour_ms"] == FEB
    assert [(leg["coin"], leg["venue"], leg["reason"]) for leg in batch["legs"]] == [
        ("BTCUSDT", "futures", "delisting")
    ]
    (fill,) = of_kind(rows, "fill")
    assert (fill["hour_ms"], fill["side"], fill["reason"]) == (FEB, 1, "delisting")
    assert F(D(fill["price"])) == 100 * PENALTY_SHORT
    assert not [e for e in of_kind(rows, "event") if e["type"].startswith("replacement")]
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["exit_reason"], lifecycle["exit_ms"]) == ("delisting", FEB)


def test_a_perpetual_that_ends_in_the_month_before_has_no_funding_month_exit(monkeypatch, tmp_path):
    """Regression for the look-ahead fix: a delisting is the dead-market rule's alone. BTCUSDT's
    perpetual (static, a seeded short of 10) has its last bar at 09:00 on January 31, so the
    data step lists no status for February, and a missing status counts as complete. The leg is
    not closed at 01:00 on January 31 as a funding-month exit at normal costs, nor synthetically
    at 00:00 on February 1; it is held through both, and closes after 168 hours without a bar,
    at 10:00 on February 7, as a delisting at the last close plus the 10% penalty, with no
    slippage and the normal fee."""
    dies = LAST_JAN + 10 * HOUR  # the perpetual's first hour without a bar
    close_h = dies + 168 * HOUR  # 10:00 on February 7
    btc = static_coin(
        "BTCUSDT",
        flat("100", end="2025-02"),
        perpetual=True,
        perp_hours=(dies - DEC) // HOUR,
        end="2025-02",
    )
    market = load(
        tmp_path, World("2025-02", (btc,), every_month("2025-01", "2025-02", ("BTCUSDT",)))
    )
    perp = market.coin("BTCUSDT").perpetual
    assert perp is not None and perp.store.last_open_at_or_before(FEB) == dies - HOUR
    assert market.funding_month("BTCUSDT", "2025-01") == "complete"
    assert market.funding_month("BTCUSDT", "2025-02") is None
    seed(
        monkeypatch,
        T0 - HOUR,
        [("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "10", "100"))],
    )

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    decision = daily_by(rows)[(LAST_JAN, "BTCUSDT")]
    assert decision["next_month"] == "2025-02" and decision["next_month_status"] is None
    assert decision["eligible"] and not decision["funding_month_exit"]
    assert events(rows, "exit_scheduled") == []
    # Held through 01:00 on January 31 and the February midnight, and closed only by the rule.
    assert holdings(rows, close_h - HOUR, [("futures", "BTCUSDT", "-10")]) == {
        ("futures", "BTCUSDT"): F(-10)
    }
    assert not [f for f in of_kind(rows, "fill") if f["reason"] == "funding-month exit"]
    (batch,) = events(rows, "synthetic_closes")
    assert batch["hour_ms"] == close_h
    assert [(leg["coin"], leg["venue"], leg["reason"]) for leg in batch["legs"]] == [
        ("BTCUSDT", "futures", "delisting")
    ]
    (fill,) = of_kind(rows, "fill")
    assert (fill["hour_ms"], fill["timestamp_ms"], fill["side"]) == (close_h, close_h, 1)
    assert fill["reason"] == "delisting" and F(D(fill["quantity"])) == 10
    last_close = perp.store.last_close_before(close_h)
    last_bar = perp.store.bar(dies - HOUR)
    assert last_bar is not None and last_close == last_bar.close
    price = F(last_close) * PENALTY_SHORT
    assert F(D(fill["price"])) == F(D(fill["unslipped_price"])) == price  # no slippage
    assert F(D(fill["fee"])) == 10 * price * FEE["futures"]
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["exit_reason"], lifecycle["exit_ms"]) == ("delisting", close_h)
    assert not lifecycle["censored"]


def test_a_perpetual_that_dies_is_closed_after_168_hours_with_the_penalty(tmp_path):
    """Spec "Delisting or a dead market": BTCUSDT is short on its perpetual from January 1, and
    the perpetual's last bar opens at 23:00 on January 14 while spot trades on. After 168 hours
    with no bar on its own venue, the short closes at the open time of the next hour, 00:00 on
    January 22, as that hour's first event: at the last close plus the 10% penalty, with no
    slippage and the normal futures fee. The coin's deferred order (January 21's short, which
    needed the perpetual) is cancelled before that hour's decision, whose own order (target 0,
    as the perpetual is no longer eligible) survives and comes due at 01:00. The lifecycle ends
    as "delisting"."""
    dies = T0 + 14 * DAY
    close_h = dies + 168 * HOUR
    start = month_start("2024-10")
    closes = downtrend()
    perpetual = PerpetualSpec(
        series=Series(start, closes[: (dies - start) // HOUR]), funding_rate="0"
    )
    market = load(
        tmp_path,
        World(
            "2025-01",
            (CoinSpec("BTCUSDT", Series(start, closes), perpetual),),
            {"2025-01": ("BTCUSDT",)},
        ),
    )
    perp = market.coin("BTCUSDT").perpetual
    assert perp is not None

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    held = holdings(rows, dies - HOUR)[("futures", "BTCUSDT")]
    assert held < 0  # short when the perpetual dies
    # The dead-market rule read off the store: due at close_h, not an hour earlier.
    assert perp.store.last_open_at_or_before(close_h - 1) == dies - HOUR
    assert dies - HOUR < close_h - 168 * HOUR and not dies - HOUR < close_h - HOUR - 168 * HOUR
    futures = [f for f in of_kind(rows, "fill") if f["venue"] == "futures"]
    assert [f["hour_ms"] for f in futures if f["hour_ms"] >= dies] == [close_h]
    (fill,) = [f for f in futures if f["hour_ms"] == close_h]
    last_close = perp.store.last_close_before(close_h)
    last_bar = perp.store.bar(dies - HOUR)
    assert last_bar is not None and last_close == last_bar.close
    price = F(last_close) * PENALTY_SHORT
    assert (fill["side"], F(D(fill["quantity"]))) == (1, -held)
    assert F(D(fill["price"])) == F(D(fill["unslipped_price"])) == price  # no slippage
    assert F(D(fill["fee"])) == -held * price * FEE["futures"]
    assert (fill["timestamp_ms"], fill["reason"]) == (close_h, "delisting")
    (batch,) = events(rows, "synthetic_closes")
    assert batch["hour_ms"] == close_h
    assert [(leg["coin"], leg["venue"], leg["symbol"], leg["reason"]) for leg in batch["legs"]] == [
        ("BTCUSDT", "futures", "BTCUSDT", "delisting")
    ]
    assert D(batch["legs"][0]["last_close"]) == last_close
    assert F(D(batch["legs"][0]["price"])) == price
    # The pending short is cancelled before January 22's decision, whose order survives.
    (cancelled,) = events(rows, "order_cancelled")
    assert (cancelled["hour_ms"], cancelled["decision_ms"]) == (close_h, close_h - DAY)
    assert cancelled["reason"] == "delisting" and D(cancelled["target"]) < 0
    decision = daily_by(rows)[(close_h, "BTCUSDT")]
    assert decision["target"] == "0" and not decision["eligible"]
    assert order_event(rows, close_h + HOUR, "BTCUSDT")["decision_ms"] == close_h
    assert not [e for e in events(rows, "order") if e["decision_ms"] == close_h - DAY]
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["side"], lifecycle["exit_reason"]) == ("short", "delisting")
    assert lifecycle["exit_ms"] == close_h and not lifecycle["censored"]
    # The close comes first in the hour: that hour's open mark already holds only cash.
    assert open_equity(result, close_h) == cash_after(rows, close_h, F(CAPITAL))


@pytest.mark.parametrize("close", ["at 01:00", "synthetic", "synthetic, no bar"])
def test_an_incomplete_funding_month_moves_the_long_to_spot_before_it_starts(
    close, monkeypatch, tmp_path
):
    """Spec "Data": February is incomplete for both perpetuals, so no futures exposure is held in
    it. BTCUSDT (rising, target 0.30) holds a seeded futures long that the band keeps through
    January; ETHUSDT (static) holds a seeded short. At the decision at 00:00 on January 31 the
    precondition holds for both: no eligible perpetual, BTCUSDT's order cancelled, each futures
    leg scheduled to close from 01:00.
    * at 01:00: both perpetuals have that bar, so both legs close then. Only BTCUSDT, whose
      latest target is long, gets a replacement buy, placed on spot in the same batch from
      January 31's target; ETHUSDT, with no target, records that it needs none.
    * synthetic: both perpetuals are masked from 01:00 to 23:00, so no bar comes before February.
      At 00:00 on February 1, before anything else and before any of February's funding, both
      legs close in one synthetic batch at the last close with the 10% penalty, the normal fee
      and no slippage. Only BTCUSDT schedules a replacement buy; February 1's decision gives
      BTCUSDT a newer target (spot-only), which supersedes it, and the long is bought on spot at
      01:00. The stale exits come due at 00:00 on flat legs and are no-ops.
    * synthetic, no bar: the same, but BTCUSDT has no daily bar for January 31, so February 1's
      decision gives it no target: the replacement buy is placed at 00:00, from January 31's
      target."""
    start = month_start("2024-10")
    closes = path("50000", (hours_in("2024-10", "2025-02"), "0.0002"), noise="0.002", seed=70)
    perp_masked = () if close == "at 01:00" else day_hours(LAST_JAN, range(1, 24))
    spot_masked = day_hours(LAST_JAN, range(18, 24)) if close == "synthetic, no bar" else ()
    incomplete = {"2025-02": "missing_slot"}
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, closes, masked=spot_masked),
        PerpetualSpec(
            series=Series(start, closes, masked=perp_masked),
            months=incomplete,
            funding_rate="0.0001",
        ),
    )
    eth = static_coin(
        "ETHUSDT",
        flat("100", end="2025-02"),
        perpetual=True,
        funding="0.0001",
        months=incomplete,
        perp_masked=perp_masked,
        end="2025-02",
    )
    universes = every_month("2025-01", "2025-02", ("BTCUSDT", "ETHUSDT"))
    market = load(tmp_path, World("2025-02", (btc, eth), universes))
    seed_price = closes[(T0 - HOUR - start) // HOUR]
    long = to_decimal(floor_to(F(3000) / F(seed_price), FUTURES_STEP))  # about 0.30 of equity
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("BTCUSDT", Fill(T0 - HOUR, "futures", "BTCUSDT", 1, long, seed_price, D(0), "seed")),
            ("ETHUSDT", seed_fill(T0 - HOUR, "futures", "ETHUSDT", -1, "30", "100")),
        ],
    )

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    daily = daily_by(rows)
    for coin in ("BTCUSDT", "ETHUSDT"):
        assert daily[(LAST_JAN, coin)]["funding_month_exit"]
        assert not daily[(LAST_JAN, coin)]["eligible"]
    assert D(daily[(LAST_JAN, "BTCUSDT")]["target"]) == D("0.30")
    (cancelled,) = events(rows, "order_cancelled")
    assert (cancelled["coin"], cancelled["hour_ms"]) == ("BTCUSDT", LAST_JAN)
    assert cancelled["reason"] == "funding-month exit"
    assert [(e["coin"], e["venue"], e["after_ms"]) for e in events(rows, "exit_scheduled")] == [
        ("BTCUSDT", "futures", LAST_JAN + HOUR),
        ("ETHUSDT", "futures", LAST_JAN + HOUR),
    ]
    assert not [
        o
        for o in events(rows, "order")
        if o["coin"] == "BTCUSDT" and o["band"] == "trade" and o["hour_ms"] < LAST_JAN
    ]
    futures = [f for f in of_kind(rows, "fill") if f["venue"] == "futures"]
    (btc_close,) = [f for f in futures if f["coin"] == "BTCUSDT"]
    (eth_close,) = [f for f in futures if f["coin"] == "ETHUSDT"]
    assert btc_close["reason"] == eth_close["reason"] == "funding-month exit"
    # Only a coin whose latest target is long is replaced (BTCUSDT's 0.30).
    assert [e["coin"] for e in events(rows, "replacement_scheduled")] == ["BTCUSDT"]
    # ETHUSDT has no target at all (static), so its close needs no replacement, and says so.
    replacement = [e for e in of_kind(rows, "event") if e["type"].startswith("replacement")]
    assert [
        (e["type"], e["target"], e["decision_ms"]) for e in replacement if e["coin"] == "ETHUSDT"
    ] == [("replacement_not_needed", None, None)]
    # No futures exposure in February: no funding charged from its first instant on.
    assert not [r for r in of_kind(rows, "funding") if r["timestamp_ms"] >= FEB]
    lifecycles = of_kind(rows, "lifecycle")
    (eth_life,) = [r for r in lifecycles if r["coin"] == "ETHUSDT"]
    assert eth_life["exit_reason"] == "funding-month exit"
    assert eth_life["exit_ms"] == btc_close["hour_ms"]
    spot_buys = [f for f in of_kind(rows, "fill") if f["venue"] == "spot" and f["side"] == 1]
    if close == "at 01:00":
        at = LAST_JAN + HOUR
        check_fill(btc_close, "futures", -1, F(long), perp_bar(market, "BTCUSDT", at).open)
        check_fill(eth_close, "futures", 1, F(30), D(100))
        assert btc_close["hour_ms"] == eth_close["hour_ms"] == at
        assert events(rows, "synthetic_closes") == []
        order = order_event(rows, at, "BTCUSDT")
        assert (order["source"], order["decision_ms"]) == ("replacement buy", LAST_JAN)
        assert [(f["hour_ms"], f["reason"]) for f in spot_buys] == [(at, "replacement buy")]
        (btc_life,) = [r for r in lifecycles if r["coin"] == "BTCUSDT"]
        assert btc_life["exit_reason"] == "window end"  # the move to spot is one lifecycle
        return
    perps = {coin: market.coin(coin).perpetual for coin in ("BTCUSDT", "ETHUSDT")}
    for fill, coin, side, quantity, penalty in (
        (btc_close, "BTCUSDT", -1, F(long), PENALTY_LONG),
        (eth_close, "ETHUSDT", 1, F(30), PENALTY_SHORT),
    ):
        perp = perps[coin]
        assert perp is not None and perp.store.bar(FEB) is not None
        last_close = perp.store.last_close_before(FEB)
        assert last_close is not None and last_close == perp_bar(market, coin, LAST_JAN).close
        price = F(last_close) * penalty
        assert (fill["hour_ms"], fill["timestamp_ms"], fill["side"]) == (FEB, FEB, side)
        assert F(D(fill["quantity"])) == quantity
        assert F(D(fill["price"])) == F(D(fill["unslipped_price"])) == price
        assert F(D(fill["fee"])) == quantity * price * FEE["futures"]
    (batch,) = events(rows, "synthetic_closes")
    assert batch["hour_ms"] == FEB
    assert [(leg["coin"], leg["reason"]) for leg in batch["legs"]] == [
        ("BTCUSDT", "funding-month exit"),
        ("ETHUSDT", "funding-month exit"),
    ]
    skipped = events(rows, "exit_skipped")
    assert [(e["coin"], e["hour_ms"], e["why"]) for e in skipped] == [
        ("BTCUSDT", FEB, "flat"),
        ("ETHUSDT", FEB, "flat"),
    ]
    assert events(rows, "replacement_scheduled")[0]["hour_ms"] == FEB
    # January 31's funding met masked perpetuals: their carried marks.
    for coin in ("BTCUSDT", "ETHUSDT"):
        (record,) = [
            r
            for r in of_kind(rows, "funding")
            if r["coin"] == coin and r["hour_ms"] == LAST_JAN + 8 * HOUR
        ]
        assert record["carried"] is True
    btc_lives = [r for r in lifecycles if r["coin"] == "BTCUSDT"]
    assert [(r["exit_ms"], r["exit_reason"]) for r in btc_lives] == [
        (FEB, "funding-month exit"),
        (LAST_HOUR, "window end"),
    ]
    if close == "synthetic":
        assert [e["coin"] for e in events(rows, "replacement_superseded")] == ["BTCUSDT"]
        decision = daily[(FEB, "BTCUSDT")]
        assert D(decision["target"]) > 0 and not decision["eligible"]
        order = order_event(rows, FEB + HOUR, "BTCUSDT")
        assert (order["source"], order["decision_ms"], order["band"]) == ("signal", FEB, "trade")
        assert [(f["hour_ms"], f["reason"]) for f in spot_buys] == [(FEB + HOUR, "signal")]
    else:
        assert events(rows, "replacement_superseded") == []
        assert daily[(FEB, "BTCUSDT")]["no_bar"] and daily[(FEB, "BTCUSDT")]["target"] is None
        order = order_event(rows, FEB, "BTCUSDT")
        assert (order["source"], order["decision_ms"]) == ("replacement buy", LAST_JAN)
        assert order["target"] == daily[(LAST_JAN, "BTCUSDT")]["target"]
        assert [(f["hour_ms"], f["reason"]) for f in spot_buys] == [(FEB, "replacement buy")]


@pytest.mark.parametrize("short", ["45", "40"])
def test_the_synthetic_closes_of_one_instant_are_one_batch_with_one_liquidation_check(
    short, monkeypatch, tmp_path
):
    """Spec "Solvency at the penalised price": BTCUSDT's and ETHUSDT's perpetuals both die at
    00:00 on January 10, so their shorts are due together at 00:00 on January 17. The check
    values both at their penalised prices at once, SOLUSDT's live short and XRPUSDT's spot at
    their marks.
    * 45 contracts each: backing is then at or below maintenance, so the cell is liquidated
      there, before its open mark, with no fill at all; either leg penalised alone would not
      have done it.
    * 40 each: the account survives, and both closes are booked together at that instant."""
    dies = T0 + 9 * DAY
    close_h = dies + 168 * HOUR
    perp_hours = (dies - DEC) // HOUR
    coins = (
        static_coin("BTCUSDT", flat("100"), perpetual=True, perp_hours=perp_hours),
        static_coin("ETHUSDT", flat("100"), perpetual=True, perp_hours=perp_hours),
        static_coin("SOLUSDT", flat("100"), perpetual=True),
        static_coin("XRPUSDT", flat("100")),
    )
    market = load(tmp_path, static_world(coins))
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, short, "100")),
            ("ETHUSDT", seed_fill(T0 - HOUR, "futures", "ETHUSDT", -1, short, "100")),
            ("SOLUSDT", seed_fill(T0 - HOUR, "futures", "SOLUSDT", -1, "10", "100")),
            ("XRPUSDT", seed_fill(T0 - HOUR, "spot", "XRPUSDT", 1, "90", "100")),
        ],
    )

    result, rows = cell_run(market, tmp_path)

    q, cash, penalised = F(D(short)), F(1000), 100 * PENALTY_SHORT
    (batch,) = events(rows, "synthetic_closes")
    assert batch["hour_ms"] == close_h
    assert [(leg["coin"], leg["reason"], F(D(leg["price"]))) for leg in batch["legs"]] == [
        ("BTCUSDT", "delisting", penalised),
        ("ETHUSDT", "delisting", penalised),
    ]
    backing = cash + 2 * q * (100 - penalised)
    maintenance = F(D("0.01")) * (2 * q * penalised + 10 * 100)
    assert F(D(batch["mark"]["backing"])) == backing
    assert F(D(batch["mark"]["maintenance"])) == maintenance
    assert residuals_hold(rows)
    if short == "45":
        assert backing <= maintenance  # the batch at its penalised prices is liquidated
        alone = cash + q * (100 - penalised)
        assert alone > F(D("0.01")) * (q * penalised + q * 100 + 10 * 100)  # one leg alone: not
        assert result.outcome == "liquidated" and result.stop_ms == close_h
        assert rows[-1][1]["check"] == "synthetic_closes" and of_kind(rows, "fill") == []
        assert F(result.final_equity) == backing + 90 * 100
        assert result.open_marks[-1][0] == close_h - HOUR  # the stop came before the open mark
        assert hourly_at(rows, close_h)["open_equity"] is None
        ended = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
        assert set(ended) == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
        assert all(r["exit_reason"] == "liquidation" and r["censored"] for r in ended.values())
        assert F(D(ended["BTCUSDT"]["unrealised"])) == q * (100 - penalised)
        return
    assert backing > maintenance and result.outcome == "complete"
    booked = fills_at(rows, close_h)
    assert [(f["coin"], f["side"], F(D(f["quantity"])), F(D(f["price"]))) for f in booked] == [
        ("BTCUSDT", 1, q, penalised),
        ("ETHUSDT", 1, q, penalised),
    ]
    assert all(F(D(f["fee"])) == q * penalised * FEE["futures"] for f in booked)
    assert {f["reason"] for f in booked} == {"delisting"}
    ended = [r for r in of_kind(rows, "lifecycle") if r["exit_ms"] == close_h]
    assert sorted((r["coin"], r["exit_reason"]) for r in ended) == [
        ("BTCUSDT", "delisting"),
        ("ETHUSDT", "delisting"),
    ]
    assert open_equity(result, close_h) == cash_after(rows, close_h, cash) + 90 * 100


def test_an_account_at_or_below_zero_after_the_synthetic_batch_is_liquidated(monkeypatch, tmp_path):
    """Spec "Solvency at the penalised price": after the batch is booked, equity at or below zero
    also ends the cell as liquidated. At the spec's costs a batch that passes the check always
    leaves equity above zero (a fee is far below the 1% maintenance), so this test charges every
    fill a fee of 10,000 USDT; only the two closes of the 40-contract batch above pay it."""
    dies = T0 + 9 * DAY
    close_h = dies + 168 * HOUR
    perp_hours = (dies - DEC) // HOUR
    coins = (
        static_coin("BTCUSDT", flat("100"), perpetual=True, perp_hours=perp_hours),
        static_coin("ETHUSDT", flat("100"), perpetual=True, perp_hours=perp_hours),
        static_coin("SOLUSDT", flat("100"), perpetual=True),
        static_coin("XRPUSDT", flat("100")),
    )
    market = load(tmp_path, static_world(coins))
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("BTCUSDT", seed_fill(T0 - HOUR, "futures", "BTCUSDT", -1, "40", "100")),
            ("ETHUSDT", seed_fill(T0 - HOUR, "futures", "ETHUSDT", -1, "40", "100")),
            ("SOLUSDT", seed_fill(T0 - HOUR, "futures", "SOLUSDT", -1, "10", "100")),
            ("XRPUSDT", seed_fill(T0 - HOUR, "spot", "XRPUSDT", 1, "90", "100")),
        ],
    )
    monkeypatch.setattr(run, "fee", lambda quantity, price, costs: D(10000))

    result, rows = cell_run(market, tmp_path)

    final = F(1000) + 2 * 40 * (100 - 110) - 2 * 10000 + 90 * 100  # SOLUSDT at its open of 100
    assert result.outcome == "liquidated" and result.stop_ms == close_h
    assert rows[-1][1]["check"] == "synthetic_closes_booked"
    assert F(result.final_equity) == final < 0
    assert [(f["coin"], f["reason"]) for f in of_kind(rows, "fill")] == [
        ("BTCUSDT", "delisting"),
        ("ETHUSDT", "delisting"),
    ]
    ended = {r["coin"]: r["exit_reason"] for r in of_kind(rows, "lifecycle")}
    assert ended == {
        "BTCUSDT": "delisting",
        "ETHUSDT": "delisting",
        "SOLUSDT": "liquidation",
        "XRPUSDT": "liquidation",
    }


def test_dead_markets_close_only_held_legs_and_are_asked_before_each_hours_observations(
    monkeypatch, tmp_path
):
    """Loop-level ``DeadMarkets``. BTCUSDT's seeded spot is outside January's universe, so it is
    sold at 01:00 on January 1; its venue then has no bar for 300 hours. A flat leg is forgotten,
    so it never comes due and is never closed. ETHUSDT (static) keeps its seeded spot, an amount
    off the step's grid, and its venue goes dark from January 10: 168 hours after its last bar the
    whole holding closes at the last close less 10%, with the spot fee and no filter. Each hour
    ``due`` is asked once, before any of that hour's observations."""
    btc_dark = tuple(range(T0 + 2 * HOUR, T0 + 302 * HOUR, HOUR))
    btc = CoinSpec("BTCUSDT", Series(DEC, flat("50000"), masked=btc_dark))
    eth = static_coin("ETHUSDT", flat("2000"), spot_dark=tuple(range(T0 + 9 * DAY, JAN_END, HOUR)))
    market = load(tmp_path, World("2025-01", (btc, eth), {"2025-01": ("ETHUSDT",)}))
    seed(
        monkeypatch,
        T0 - HOUR,
        [
            ("BTCUSDT", seed_fill(T0 - HOUR, "spot", "BTCUSDT", 1, "0.1", "50000")),
            ("ETHUSDT", seed_fill(T0 - HOUR, "spot", "ETHUSDT", 1, "1.000005", "2000")),
        ],
    )
    calls: list[tuple[str, int, Any]] = []

    class Watched(DeadMarkets):
        def due(self, hour_ms):
            legs = super().due(hour_ms)
            calls.append(("due", hour_ms, legs))
            return legs

        def observe(self, hour_ms, venue, symbol, has_bar):
            calls.append(("observe", hour_ms, (venue, symbol)))
            super().observe(hour_ms, venue, symbol, has_bar)

    monkeypatch.setattr(run, "DeadMarkets", Watched)

    result, rows = cell_run(market, tmp_path)

    close_h = T0 + 9 * DAY - HOUR + 169 * HOUR  # the last bar opens at 23:00 on January 9
    assert result.outcome == "complete" and residuals_hold(rows)
    asked = [hour for kind, hour, _ in calls if kind == "due"]
    assert asked == [stamp for stamp, _, _ in result.open_marks]  # once an hour, every hour
    seen: set[int] = set()
    for kind, hour, _ in calls:
        if kind == "due":
            seen.add(hour)
        else:
            assert hour in seen  # the hour's due came first
    listed = [(hour, legs) for kind, hour, legs in calls if kind == "due" and legs]
    assert listed == [(close_h, (("spot", "ETHUSDT"),))]
    btc_fills = [f for f in of_kind(rows, "fill") if f["coin"] == "BTCUSDT"]
    assert [(f["hour_ms"], f["reason"]) for f in btc_fills] == [(T0 + HOUR, "universe exit")]
    (fill,) = [f for f in of_kind(rows, "fill") if f["coin"] == "ETHUSDT"]
    assert (fill["hour_ms"], fill["timestamp_ms"], fill["side"]) == (close_h, close_h, -1)
    assert fill["reason"] == "delisting" and D(fill["quantity"]) == D("1.000005")
    assert F(D(fill["price"])) == F(D(fill["unslipped_price"])) == 2000 * PENALTY_LONG
    assert F(D(fill["fee"])) == F(D("1.000005")) * 2000 * PENALTY_LONG * FEE["spot"]
    lifecycles = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
    assert lifecycles["ETHUSDT"]["exit_reason"] == "delisting"
    assert lifecycles["ETHUSDT"]["exit_ms"] == close_h


def test_the_audit_holds_every_hour(monkeypatch, tmp_path):
    """Spec "Safety", accounting: the wallet and quantity identities hold exactly and the equity
    residual stays within 1e-18 at the end of every hour, over a world with trades, funding and
    cuts. SOLUSDT's seeded short (static) jumped from 100 to 195 just before the window: at the
    first post-fill check the margin ratio is below 3 and gross far above 3, so the cushion cut
    and then the ceiling cut fill at that open. BTCUSDT then trades its downtrend on its
    perpetual, and both shorts take funding every eight hours."""
    start = month_start("2024-10")
    btc = CoinSpec("BTCUSDT", Series(start, downtrend()), PerpetualSpec(funding_rate="0.0003"))
    sol = static_coin("SOLUSDT", jump("100", T0 - HOUR, "0.95"), perpetual=True, funding="0.0003")
    market = load(tmp_path, static_world((btc, sol)))
    seed(
        monkeypatch,
        T0 - HOUR,
        [("SOLUSDT", seed_fill(T0 - HOUR, "futures", "SOLUSDT", -1, "100", "100"))],
    )

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    hourly = of_kind(rows, "hourly")
    assert len(hourly) == len(result.open_marks) == hours_in("2025-01", "2025-01")
    assert residuals_hold(rows)
    assert result.audit.wallet_residual == 0
    assert not any(result.audit.quantity_residuals.values())
    reasons = {f["reason"] for f in of_kind(rows, "fill")}
    assert {"margin cut", "ceiling cut", "signal", "window end"} <= reasons
    cuts = [
        (e["type"], e["hour_ms"])
        for e in of_kind(rows, "event")
        if e["type"] in ("margin_cut", "ceiling_cut")
    ]
    assert cuts[:2] == [("margin_cut", T0), ("ceiling_cut", T0)]
    # The ceiling is judged on the mark after the cushion's cut: SOLUSDT at 195 throughout.
    margin_fills = [f for f in fills_at(rows, T0) if f["reason"] == "margin cut"]
    cash = F(CAPITAL) + sum(F(D(f["realised"])) - F(D(f["fee"])) for f in margin_fills)
    left = 100 - sum(F(D(f["quantity"])) for f in margin_fills)
    (ceiling,) = [e for e in events(rows, "ceiling_cut") if e["hour_ms"] == T0]
    assert F(D(ceiling["equity"])) == cash + left * (100 - 195)
    funding = of_kind(rows, "funding")
    assert {r["coin"] for r in funding if D(r["amount"]) != 0} == {"BTCUSDT", "SOLUSDT"}


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


# ---- the final review: two loop-level paths of real data ----------------------------------


def check_conservation(rows: list[tuple[str, dict[str, Any]]], final: Decimal) -> None:
    """Every fill and every funding payment belongs to one lifecycle: over the lifecycles,
    ``gross - fees + funding`` is ``final - capital`` exactly, and their fees and funding are the
    fill and funding records'."""
    lives = of_kind(rows, "lifecycle")
    net = sum((F(D(r["gross_pnl"])) - F(D(r["fees"])) + F(D(r["funding"])) for r in lives), F(0))
    assert net == F(final) - CAPITAL
    assert sum(F(D(r["fees"])) for r in lives) == sum(F(D(f["fee"])) for f in of_kind(rows, "fill"))
    paid = sum((F(D(p["amount"])) for p in of_kind(rows, "funding")), F(0))
    assert sum((F(D(r["funding"])) for r in lives), F(0)) == paid


def test_a_coin_that_leaves_and_reenters_catches_up_its_signals_on_every_bar(monkeypatch, tmp_path):
    """Spec "Signals" and "Universe": ETHUSDT is in January's universe, not February's, and
    back in March's. Its February 1 decision is a universe exit (target 0, its spot sells at
    01:00), and once it is flat and outside the universe it is not decided again until March 1.
    That decision feeds its signal state every daily bar of February at once (``_feed``'s
    catch-up): each one, once and in order, so its reading and the book's weights are those of
    one plain pass over the market's daily bars, and it is bought again at 01:00."""
    start, hours = month_start("2024-10"), hours_in("2024-10", "2025-03")
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, path("50000", (hours, "0.0002"), noise="0.002", seed=31)),
        perpetual=PerpetualSpec(funding_rate="0"),
    )
    eth = CoinSpec(
        "ETHUSDT", Series(start, path("2000", (hours, "0.0002"), noise="0.002", seed=32))
    )
    both = ("BTCUSDT", "ETHUSDT")
    universes = {"2025-01": both, "2025-02": ("BTCUSDT",), "2025-03": both}
    market = load(tmp_path, World("2025-03", (btc, eth), universes))
    made: list[Any] = []

    class SpySignals(CoinSignals):
        """Records every daily bar the engine feeds one coin's signal state."""

        def __init__(self, lookbacks: Any) -> None:
            super().__init__(lookbacks)
            self.fed: list[Any] = []
            made.append(self)

        def update(self, bar: Any) -> SignalReading:
            self.fed.append(bar)
            return super().update(bar)

    monkeypatch.setattr(run, "CoinSignals", SpySignals)

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    mar, apr = month_start("2025-03"), month_start("2025-04")
    eth_days = sorted(h for h, coin in daily_by(rows) if coin == "ETHUSDT")
    assert eth_days == [*range(T0, FEB + DAY, DAY), *range(mar, apr, DAY)]
    daily = daily_by(rows)
    assert daily[(FEB, "ETHUSDT")]["universe_exit"] and daily[(FEB, "ETHUSDT")]["target"] == "0"
    eth_fills = [f for f in of_kind(rows, "fill") if f["coin"] == "ETHUSDT"]
    (sold,) = [f for f in eth_fills if FEB <= f["hour_ms"] < mar]
    assert (sold["hour_ms"], sold["side"], sold["reason"]) == (FEB + HOUR, -1, "universe exit")
    assert F(D(sold["quantity"])) == holdings(rows, FEB)[("spot", "ETHUSDT")]  # all of it
    # Every bar up to the last decision's day, once and in order: February's at March 1.
    bars = market.daily("ETHUSDT")
    (state,) = [m for m in made if m.fed and m.fed[0] == bars[0]]
    assert state.fed == [bar for bar in bars if bar.open_ms <= apr - 2 * DAY]
    assert any(FEB <= bar.open_ms < mar for bar in state.fed)
    readings = {coin: readings_by_day(market, coin, ARMS["v4_main"]) for coin in both}
    for h in range(mar, apr, DAY):
        sizing = expected_book(
            market, ARMS["v4_main"], h, both, readings, market.perpetual_eligible
        )
        for coin in both:
            record = daily[(h, coin)]
            check_reading(record, latest(readings[coin], h - DAY))
            check_sizing(record, sizing)
            assert record["target"] == text(sizing.weights[coin])
    assert daily[(mar, "ETHUSDT")]["reading_day_ms"] == mar - DAY
    assert D(daily[(mar, "ETHUSDT")]["target"]) > 0
    (bought,) = [f for f in eth_fills if f["hour_ms"] == mar + HOUR]
    assert (bought["venue"], bought["side"], bought["reason"]) == ("spot", 1, "signal")
    ended = [r for r in of_kind(rows, "lifecycle") if r["coin"] == "ETHUSDT"]
    assert [(r["entry_ms"], r["exit_ms"], r["exit_reason"]) for r in ended] == [
        (T0 + HOUR, FEB + HOUR, "universe exit"),
        (mar + HOUR, apr - HOUR, "window end"),
    ]
    check_conservation(rows, result.final_equity)


def test_a_long_on_spot_flips_to_a_short_on_futures_in_one_batch(tmp_path):
    """Spec "Longs on spot first", "Shorts on futures" and "Records": BTCUSDT rises for ten
    months, so its slow speed stays up, and falls from 2025-01-01. It is long on spot (L > 0)
    until the downtrend is confirmed with the medium speed down; the next decision's target is
    short. At its fill hour one batch sells the whole spot leg (a reduction, first) and opens
    the short on the perpetual (an increase, after it). The long's lifecycle ends there with
    reason ``signal``, holding the spot fills only, and the short's begins there with the
    futures fill; money is conserved over the two."""
    start = month_start("2024-03")
    up, down = (T0 - start) // HOUR, hours_in("2025-01", "2025-02")
    closes = path("50000", (up, "0.0002"), (down, "-0.0006"), noise="0.002", seed=21)
    btc = CoinSpec("BTCUSDT", Series(start, closes), perpetual=PerpetualSpec(funding_rate="0"))
    both = {"2025-01": ("BTCUSDT",), "2025-02": ("BTCUSDT",)}
    market = load(tmp_path, World("2025-02", (btc,), both))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete"
    decisions = sorted((h, r) for (h, _), r in daily_by(rows).items())
    flips = [
        (before[1], after[1])
        for before, after in zip(decisions, decisions[1:], strict=False)
        if D(before[1]["target"]) > 0 > D(after[1]["target"])
    ]
    ((long_day, short_day),) = flips
    assert D(long_day["L"]) > 0 and D(long_day["S"]) == 0  # long on its kept speeds
    assert D(short_day["S"]) > 0 and short_day["downtrend"]["confirmed"]
    at = short_day["decision_ms"] + HOUR
    held = holdings(rows, at - 1)
    spot_held = held[("spot", "BTCUSDT")]
    assert spot_held > 0 and ("futures", "BTCUSDT") not in held  # long on spot only
    # The batch: the spot sale (a reduction) first, then the short (an increase).
    batch = fills_at(rows, at)
    assert [(f["venue"], f["side"], f["reason"]) for f in batch] == [
        ("spot", -1, "signal"),
        ("futures", -1, "signal"),
    ]
    check_fill(batch[0], "spot", -1, spot_held, spot_bar(market, "BTCUSDT", at).open)
    contract = perp_bar(market, "BTCUSDT", at).open
    target = F(D(short_day["target"]))
    quantity = floor_to(-target * open_equity(result, at) / F(contract), FUTURES_STEP)
    check_fill(batch[1], "futures", -1, quantity, contract)
    order = order_event(rows, at, "BTCUSDT")
    assert order["band"] == "trade" and D(order["current"]) > 0
    assert D(order["split"]["spot"]) == 0 and F(D(order["split"]["futures"])) == target * F(
        open_equity(result, at)
    )
    # Two lifecycles, split at the batch: the long holds the spot fills, the short the futures.
    long, short = of_kind(rows, "lifecycle")
    assert (long["side"], long["exit_ms"], long["exit_reason"]) == ("long", at, "signal")
    assert (short["side"], short["entry_ms"], short["exit_reason"]) == ("short", at, "window end")
    spot_fills = [f for f in of_kind(rows, "fill") if f["venue"] == "spot"]
    futures_fills = [f for f in of_kind(rows, "fill") if f["venue"] == "futures"]
    assert all(f["hour_ms"] <= at for f in spot_fills)
    assert F(D(long["fees"])) == sum(F(D(f["fee"])) for f in spot_fills)
    assert F(D(long["gross_pnl"])) == sum(F(D(f["realised"])) for f in spot_fills)
    assert D(long["venues"]["spot"]["bought_quantity"]) == D(
        long["venues"]["spot"]["sold_quantity"]
    )
    assert D(long["venues"]["futures"]["sold_quantity"]) == 0
    assert F(D(short["fees"])) == sum(F(D(f["fee"])) for f in futures_fills)
    assert F(D(short["venues"]["futures"]["sold_quantity"])) >= quantity
    assert D(short["venues"]["spot"]["bought_quantity"]) == 0
    check_conservation(rows, result.final_equity)


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
    # Task 14: the outcome record binds the records to their cell and the data replayed.
    header = read_data_json(tmp_path / "world" / "data")
    assert outcome[0]["cell"] == {
        "id": "v4_main-10000-1x",
        "arm": "v4_main",
        "capital": 10000,
        "cost_multiple": 1,
    }
    assert outcome[0]["data"] == {
        "config_sha256": header["config_sha256"],
        "end_month": "2025-01",
        "daily_sha256": header["packs"]["daily"]["sha256"],
        "index_sha256": header["packs"]["hourly_index"]["sha256"],
    }
    assert run.data_record(None) is None  # a market built in memory names no data
    # The final review: it names the window too, the opens of its first and last hour.
    assert outcome[0]["window"] == {"start_ms": T0, "end_ms": FEB - HOUR}
    assert (market.window_start_ms, market.window_end_ms) == (T0, FEB - HOUR)
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
