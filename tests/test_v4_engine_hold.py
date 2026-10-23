"""V4 engine task 13: the hold comparisons, ``hold_universe`` and ``hold_btc``, and step 4a's
``hold_btc_trend``.

Each test replays a small synthetic world from ``tests/v4_synthetic.py`` through
``hold.run_hold_cell`` and checks the records against the spec's hold rules ("Versions in the
run", the hold comparisons), recomputed here from the bars and from the fill records: a target of
``0.99 x equity / n`` at the open mark of the coin's own fill hour, sells before buys, a buy cut to
the cash it can pay for with its fee, the filters and dust, deferrals and a newer month's order,
the dead-market close and the window end. ``hold_btc_trend`` is tested the same way, with the
SMA(200) vote recomputed here from the market's daily bars. Expected quantities are exact Fractions
floored to the spot step. The network is blocked for every test (the autouse fixture) and no real
pack is read.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import socket
from collections.abc import Iterable, Sequence
from decimal import ROUND_DOWN, Context, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from v4_synthetic import (
    DAY,
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
    write_world,
)

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.v4.engine import hold, run
from crypto_grid_bot.v4.engine.arms import CellSpec
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.records import read_receipt, read_records
from crypto_grid_bot.v4.engine.summary import build_summary

D = Decimal
F = Fraction
T0 = month_start("2025-01")  # 2025-01-01 00:00 UTC
FEB = month_start("2025-02")
MAR = month_start("2025-03")
CAPITAL = 10000
UNIVERSE = CellSpec("hold_universe", CAPITAL, 1)
BTC_ONLY = CellSpec("hold_btc", CAPITAL, 1)
STEP = F(SPOT_RULES.step)
INVESTED = F(99, 100)
TRUNCATE = Context(prec=60, rounding=ROUND_DOWN)
HOLD_KINDS = {"hourly", "monthly", "fill", "event", "lifecycle", "outcome"}
START = F(CAPITAL)  # the starting cash of a 10,000 USDT cell

Rows = list[tuple[str, dict[str, Any]]]


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


def load(tmp_path: Path, world: World, name: str = "world") -> Market:
    return Market.load(write_world(tmp_path / name, world))


def cell_run(
    market: Market, tmp_path: Path, cell: CellSpec = UNIVERSE, name: str = "cell"
) -> tuple[run.CellResult, Rows]:
    """Run one hold cell into ``tmp_path / "out" / name`` and read its records back, verified."""
    out = tmp_path / "out" / name
    result = hold.run_hold_cell(market, cell, out)
    assert read_receipt(out / run.RECEIPT_FILE) == result.receipt
    rows = list(read_records(out / run.RECORDS_FILE, result.receipt))
    return result, rows


def of_kind(rows: Iterable[tuple[str, dict[str, Any]]], kind: str) -> list[dict[str, Any]]:
    return [record for name, record in rows if name == kind]


def events(rows: Rows, kind: str) -> list[dict[str, Any]]:
    return [r for r in of_kind(rows, "event") if r["type"] == kind]


def order_event(rows: Rows, hour_ms: int, coin: str) -> dict[str, Any]:
    (found,) = [r for r in events(rows, "order") if r["hour_ms"] == hour_ms and r["coin"] == coin]
    return found


def fills_at(rows: Rows, hour_ms: int) -> list[dict[str, Any]]:
    """The fill records of one hour, in the order they were booked."""
    return [r for r in of_kind(rows, "fill") if r["hour_ms"] == hour_ms]


def floor_step(value: Fraction) -> Fraction:
    """``value >= 0`` rounded toward zero to the spot step."""
    return (value // STEP) * STEP


def flat(price: str, first: str = "2025-01", last: str = "2025-01") -> tuple[Decimal, ...]:
    return path(price, (hours_in(first, last), "0"))


def coin(
    symbol: str,
    closes: Sequence[Decimal],
    *,
    start: int = T0,
    masked: Iterable[int] = (),
    perpetual: PerpetualSpec | None = None,
) -> CoinSpec:
    return CoinSpec(symbol, Series(start, closes, masked=tuple(masked)), perpetual)


def spot_open(market: Market, symbol: str, hour_ms: int) -> Decimal:
    bar = market.coin(symbol).spot.bar(hour_ms)
    assert bar is not None
    return bar.open


def spot_close(market: Market, symbol: str, hour_ms: int) -> Decimal:
    bar = market.coin(symbol).spot.bar(hour_ms)
    assert bar is not None
    return bar.close


def cash_after(rows: Rows, through_ms: int, start: Fraction = START) -> Fraction:
    """The wallet after every fill stamped at or before ``through_ms`` (spot only: a buy spends
    its notional and its fee, a sale adds its notional less its fee)."""
    cash = start
    for fill in of_kind(rows, "fill"):
        if fill["timestamp_ms"] <= through_ms:
            assert fill["venue"] == "spot"
            cash -= fill["side"] * F(D(fill["quantity"])) * F(D(fill["price"]))
            cash -= F(D(fill["fee"]))
    return cash


def holdings(rows: Rows, through_ms: int) -> dict[str, Fraction]:
    """Each coin's spot quantity once every fill stamped at or before ``through_ms`` is booked;
    coins at 0 are left out."""
    held: dict[str, Fraction] = {}
    for fill in of_kind(rows, "fill"):
        if fill["timestamp_ms"] <= through_ms:
            held[fill["symbol"]] = held.get(fill["symbol"], F(0)) + fill["side"] * F(
                D(fill["quantity"])
            )
    return {symbol: quantity for symbol, quantity in held.items() if quantity}


def mark_at(market: Market, rows: Rows, hour_ms: int, start: Fraction = START) -> Fraction:
    """The open mark at ``hour_ms`` rebuilt from the fills stamped before that hour (so for an
    hour without a synthetic close): the cash and each coin held at its bar's open or, without
    one, its carried mark, the last close."""
    total = cash_after(rows, hour_ms - 1, start)
    for symbol, quantity in holdings(rows, hour_ms - 1).items():
        store = market.coin(symbol).spot
        bar = store.bar(hour_ms)
        price = bar.open if bar is not None else store.last_close_before(hour_ms)
        assert price is not None
        total += quantity * F(price)
    return total


def open_equity(result: run.CellResult, hour_ms: int) -> Fraction:
    (equity,) = [equity for stamp, equity, _ in result.open_marks if stamp == hour_ms]
    return F(equity)


def check_fill(
    fill: dict[str, Any], side: int, quantity: Fraction, unslipped: Decimal, costs: Costs
) -> None:
    """A spot fill of ``quantity`` at the unslipped price moved by the slippage against the
    trade, with the spot fee on its own notional (spec "Costs (normal)")."""
    price = F(unslipped) * (1 + side * F(costs.slippage_rate))
    assert (fill["venue"], fill["side"]) == ("spot", side)
    assert F(D(fill["quantity"])) == quantity
    assert F(D(fill["price"])) == price
    assert F(D(fill["fee"])) == quantity * price * F(costs.fee_rate)
    assert D(fill["unslipped_price"]) == unslipped


def residuals_hold(rows: Rows) -> bool:
    return all(D(h["equity_residual"]).copy_abs() <= D("1e-18") for h in of_kind(rows, "hourly"))


def lifecycles_of(rows: Rows, symbol: str) -> list[dict[str, Any]]:
    return [r for r in of_kind(rows, "lifecycle") if r["coin"] == symbol]


SPOT = UNIVERSE.costs("spot")
NEED = (1 + F(SPOT.slippage_rate)) * (1 + F(SPOT.fee_rate))  # a buy's cost per unit of notional


# ---- hold_universe ------------------------------------------------------------------------


def universe_world() -> World:
    """Four coins over January and February. January selects CCC, AAA and BBB (rank order is not
    alphabetical); February drops AAA and adds DDD. BBB rises about 35% in January and CCC falls
    about 20%, so February's rebalance sells BBB down and buys CCC up. BBB has a perpetual with
    a funding rate that a futures holder would pay; a hold arm never holds futures."""
    hours = hours_in("2025-01", "2025-02")
    coins = (
        coin("AAAUSDT", path("100", (hours, "0"), noise="0.002", seed=1)),
        coin(
            "BBBUSDT",
            path("40", (hours, "0.0004"), noise="0.002", seed=2),
            perpetual=PerpetualSpec(funding_rate="0.0001"),
        ),
        coin("CCCUSDT", path("25", (hours, "-0.0003"), noise="0.002", seed=3)),
        coin("DDDUSDT", path("8", (hours, "0.0001"), noise="0.002", seed=4)),
    )
    universes = {
        "2025-01": ("CCCUSDT", "AAAUSDT", "BBBUSDT"),
        "2025-02": ("DDDUSDT", "BBBUSDT", "CCCUSDT"),
    }
    return World("2025-02", coins, universes)


def test_hold_universe_targets_0_99_equity_over_n(tmp_path):
    """Spec "Versions in the run", hold_universe: at each month's first 00:00 decision every coin
    of the month's universe gets ``0.99 x equity / n`` from the equity at the 01:00 open mark,
    before the fills, and a coin that left gets 0. There is no band: every coin trades to its
    target. The sells fill before the buys, each group alphabetical by symbol (not rank order).
    A rebalance that only resizes a holding keeps its lifecycle open."""
    market = load(tmp_path, universe_world())

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    january, february = T0 + HOUR, FEB + HOUR
    # January: three coins, each 0.33 x 10,000 at its 01:00 open.
    assert open_equity(result, january) == CAPITAL
    first = fills_at(rows, january)
    assert [(f["coin"], f["side"]) for f in first] == [
        ("AAAUSDT", 1),
        ("BBBUSDT", 1),
        ("CCCUSDT", 1),
    ]
    for fill in first:
        price = spot_open(market, fill["coin"], january)
        quantity = floor_step(INVESTED * CAPITAL / 3 / F(price))
        check_fill(fill, 1, quantity, price, SPOT)
        assert fill["timestamp_ms"] == january and fill["reason"] == "rebalance"
        order = order_event(rows, january, fill["coin"])
        assert order["source"] == "rebalance" and order["decision_ms"] == T0
        assert F(D(order["target"])) == F(33, 100) and F(D(order["equity"])) == CAPITAL
        assert F(D(order["state"]["target_notional"])) == 3300
        assert order["band"] is None and order["current"] is None and not order["eligible"]
        assert D(order["split"]["futures"]) == 0
    # February: the equity at the 01:00 open mark, before the fills, sizes every target.
    equity = open_equity(result, february)
    assert equity == mark_at(market, rows, february)
    held = holdings(rows, february - 1)
    target = {
        symbol: floor_step(INVESTED * equity / 3 / F(spot_open(market, symbol, february)))
        for symbol in ("BBBUSDT", "CCCUSDT", "DDDUSDT")
    }
    assert held["BBBUSDT"] > target["BBBUSDT"] and held["CCCUSDT"] < target["CCCUSDT"]
    expected = [
        ("AAAUSDT", -1, held["AAAUSDT"], "universe exit"),
        ("BBBUSDT", -1, held["BBBUSDT"] - target["BBBUSDT"], "rebalance"),
        ("CCCUSDT", 1, target["CCCUSDT"] - held["CCCUSDT"], "rebalance"),
        ("DDDUSDT", 1, target["DDDUSDT"], "rebalance"),
    ]
    second = fills_at(rows, february)
    assert [(f["coin"], f["side"], F(D(f["quantity"])), f["reason"]) for f in second] == expected
    for fill in second:
        check_fill(
            fill,
            fill["side"],
            F(D(fill["quantity"])),
            spot_open(market, fill["coin"], february),
            SPOT,
        )
    aaa = order_event(rows, february, "AAAUSDT")
    assert D(aaa["target"]) == 0 and D(aaa["state"]["target_notional"]) == 0
    assert aaa["decision_ms"] == FEB and D(aaa["legs"][0]["target"]) == 0
    assert F(D(order_event(rows, february, "DDDUSDT")["equity"])) == equity
    assert events(rows, "increase_cut") == []  # 1% of equity pays every fee and slippage here
    # One lifecycle per coin: AAA ends at its universe exit; the resized ones run to the end.
    lifecycles = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
    assert len(of_kind(rows, "lifecycle")) == 4
    assert lifecycles["AAAUSDT"]["exit_reason"] == "universe exit"
    assert lifecycles["AAAUSDT"]["exit_ms"] == february and not lifecycles["AAAUSDT"]["censored"]
    for symbol in ("BBBUSDT", "CCCUSDT"):
        assert lifecycles[symbol]["entry_ms"] == january
        assert lifecycles[symbol]["exit_reason"] == "window end"
    assert lifecycles["DDDUSDT"]["entry_ms"] == february
    monthly = of_kind(rows, "monthly")
    assert [m["universe"] for m in monthly] == [
        ["CCCUSDT", "AAAUSDT", "BBBUSDT"],
        ["DDDUSDT", "BBBUSDT", "CCCUSDT"],
    ]
    assert monthly[1]["entered"] == ["DDDUSDT"] and monthly[1]["left"] == ["AAAUSDT"]
    # Spot only: no futures fill, no funding, no daily signal record.
    assert of_kind(rows, "funding") == [] and of_kind(rows, "daily_coin") == []
    assert all(h["margin_ratio"] is None for h in of_kind(rows, "hourly"))
    last = month_start("2025-03") - HOUR
    assert result.final_after_close == result.final_equity
    assert F(result.final_after_close) == cash_after(rows, last + HOUR)
    assert holdings(rows, last + HOUR) == {}


def test_a_share_that_does_not_terminate_is_cut_toward_zero(tmp_path):
    """Seven coins: 0.99 / 7 has no finite decimal. The weight and the target notional are cut
    toward zero at 60 digits, never rounded up, and the quantity is the exact share floored to
    the step."""
    symbols = ("AAAUSDT", "BBBUSDT", "CCCUSDT", "DDDUSDT", "EEEUSDT", "FFFUSDT", "GGGUSDT")
    prices = ("3", "7", "11", "13", "17", "19", "23")
    coins = tuple(coin(s, flat(p)) for s, p in zip(symbols, prices, strict=True))
    market = load(tmp_path, World("2025-01", coins, {"2025-01": symbols}))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    weight = TRUNCATE.divide(D("0.99"), D(7))
    notional = TRUNCATE.divide(D(9900), D(7))
    assert F(notional) < INVESTED * CAPITAL / 7 < F(notional) + F(1, 10**50)
    fills = fills_at(rows, T0 + HOUR)
    assert [f["coin"] for f in fills] == list(symbols)
    for fill, price in zip(fills, prices, strict=True):
        order = order_event(rows, T0 + HOUR, fill["coin"])
        assert D(order["target"]) == weight
        assert D(order["state"]["target_notional"]) == notional
        quantity = floor_step(INVESTED * CAPITAL / 7 / F(D(price)))
        check_fill(fill, 1, quantity, D(price), SPOT)


def cut_world() -> World:
    """Flat coins. January holds AAA (100) and BBB (50); February's universe is CCC (20), DDD
    (10) and EEE (5). AAA's spot is masked at 01:00 on February 1, so its sale waits an hour and
    its cash is not there for February's buys."""
    hours = hours_in("2025-01", "2025-02")
    coins = (
        coin("AAAUSDT", path("100", (hours, "0")), masked=(FEB + HOUR,)),
        coin("BBBUSDT", path("50", (hours, "0"))),
        coin("CCCUSDT", path("20", (hours, "0"))),
        coin("DDDUSDT", path("10", (hours, "0"))),
        coin("EEEUSDT", path("5", (hours, "0"))),
    )
    universes = {"2025-01": ("AAAUSDT", "BBBUSDT"), "2025-02": ("CCCUSDT", "DDDUSDT", "EEEUSDT")}
    return World("2025-02", coins, universes)


def test_buys_are_cut_to_cash_fee_included(tmp_path):
    """Spec "the same cash rule": a buy larger than the cash then available (after the hour's
    sells and earlier buys) is cut to what that cash pays for at its slipped price with its fee,
    ``n (1 + s)(1 + f) <= cash``, then rounded down to the step. A buy cut below the filters is
    skipped and recorded. A deferred sale fills at its coin's own first hour with a bar."""
    market = load(tmp_path, cut_world())

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    at = FEB + HOUR
    equity = open_equity(result, at)
    assert equity == mark_at(market, rows, at)  # AAA at its carried mark, the last close
    share = INVESTED * equity / 3
    fills = fills_at(rows, at)
    assert [(f["coin"], f["side"]) for f in fills] == [
        ("BBBUSDT", -1),
        ("CCCUSDT", 1),
        ("DDDUSDT", 1),
    ]
    check_fill(fills[0], -1, F(99), D(50), SPOT)
    check_fill(fills[1], 1, floor_step(share / 20), D(20), SPOT)
    # DDD's buy meets the cash left after BBB's sale and CCC's buy.
    cash = cash_after(rows, at - 1)
    for fill in fills[:2]:
        cash -= fill["side"] * F(D(fill["quantity"])) * F(D(fill["price"])) + F(D(fill["fee"]))
    wanted = floor_step(share / 10)
    assert wanted * 10 * NEED > cash > 0
    quantity = floor_step(cash / (10 * NEED))
    check_fill(fills[2], 1, quantity, D(10), SPOT)
    left = cash - quantity * F(D(fills[2]["price"])) - F(D(fills[2]["fee"]))
    assert 0 <= left < STEP * 10 * NEED  # not one more step is paid for
    cuts = {e["coin"]: e for e in events(rows, "increase_cut")}
    assert set(cuts) == {"DDDUSDT", "EEEUSDT"}
    assert F(D(cuts["DDDUSDT"]["wanted"])) == wanted * 10
    assert F(D(cuts["DDDUSDT"]["admitted"])) <= cash / NEED
    assert F(D(cuts["DDDUSDT"]["quantity"])) == quantity and cuts["DDDUSDT"]["refusal"] is None
    # EEE's buy is cut below the filters: skipped, and recorded.
    assert cuts["EEEUSDT"]["refusal"] in ("min_qty", "min_notional", "cash")
    assert D(cuts["EEEUSDT"]["quantity"]) == 0
    assert not [f for f in of_kind(rows, "fill") if f["coin"] == "EEEUSDT"]
    # AAA's sale was deferred to its own first hour with a spot bar.
    (aaa,) = fills_at(rows, at + HOUR)
    assert (aaa["coin"], aaa["reason"]) == ("AAAUSDT", "universe exit")
    check_fill(aaa, -1, F(D("49.5")), D(100), SPOT)
    assert order_event(rows, at + HOUR, "AAAUSDT")["decision_ms"] == FEB
    assert not [e for e in events(rows, "order") if e["coin"] == "AAAUSDT" and e["hour_ms"] == at]
    # DDD is not topped up later: its order was used.
    last = MAR - HOUR
    ddd = [f for f in of_kind(rows, "fill") if f["coin"] == "DDDUSDT"]
    assert [f["hour_ms"] for f in ddd] == [at, last]


def test_empty_month_sells_what_it_can(tmp_path):
    """Spec: a month with an empty universe gives every coin a target of 0, so the account sells
    what it can and holds cash and dust. BBB and CCC crash 99% in January, so their holdings are
    worth less than the 5 USDT minimum: dust, valued at its mark. BBB doubles in February and is
    sold at the next decision (March's, also empty); CCC is dust to the window end, censored as
    "window end (dust)"."""
    hours = hours_in("2025-01", "2025-03")
    crash = 14 * 24  # the bar that opens at 00:00 on January 15
    rise = (month_start("2025-02") + 14 * DAY - T0) // HOUR  # 00:00 on February 15
    aaa = coin("AAAUSDT", path("100", (hours, "0")))
    bbb = coin(
        "BBBUSDT",
        path(
            "100",
            (crash, "0"),
            (1, "-0.99"),
            (rise - crash - 1, "0"),
            (1, "1"),
            (hours - rise - 1, "0"),
        ),
    )
    ccc = coin("CCCUSDT", path("100", (crash, "0"), (1, "-0.99"), (hours - crash - 1, "0")))
    world = World(
        "2025-03",
        (aaa, bbb, ccc),
        {"2025-01": ("AAAUSDT", "BBBUSDT", "CCCUSDT"), "2025-02": (), "2025-03": ()},
    )
    market = load(tmp_path, world)
    capital = F(1000)

    result, rows = cell_run(market, tmp_path, CellSpec("hold_universe", 1000, 1))

    assert result.outcome == "complete" and residuals_hold(rows)
    january, february, march = T0 + HOUR, FEB + HOUR, MAR + HOUR
    assert [F(D(f["quantity"])) for f in fills_at(rows, january)] == [F(D("3.3"))] * 3
    # February: AAA is sold; BBB and CCC are dust (3.3 at 1.0 is below 5 USDT) and stay.
    (sold,) = fills_at(rows, february)
    assert (sold["coin"], sold["reason"]) == ("AAAUSDT", "universe exit")
    check_fill(sold, -1, F(D("3.3")), D(100), SPOT)
    for symbol in ("BBBUSDT", "CCCUSDT"):
        order = order_event(rows, february, symbol)
        assert D(order["target"]) == 0 and order["legs"][0]["orders"] == []
        assert D(order["legs"][0]["dust"]) == D("3.3") and D(order["state"]["dust"]) == D("3.3")
    # Cash and dust, the dust at its mark.
    for hour in (february + HOUR, FEB + 10 * DAY):
        assert open_equity(result, hour) == cash_after(rows, hour, capital) + 2 * F(D("3.3"))
    assert not [f for f in of_kind(rows, "fill") if f["side"] == 1 and f["hour_ms"] > january]
    # March: BBB's 3.3 at 2.0 can be sold now; CCC's still cannot.
    (later,) = fills_at(rows, march)
    assert (later["coin"], later["reason"]) == ("BBBUSDT", "universe exit")
    check_fill(later, -1, F(D("3.3")), D(2), SPOT)
    assert order_event(rows, march, "CCCUSDT")["legs"][0]["orders"] == []
    lifecycles = {r["coin"]: r for r in of_kind(rows, "lifecycle")}
    assert (lifecycles["AAAUSDT"]["exit_reason"], lifecycles["AAAUSDT"]["exit_ms"]) == (
        "universe exit",
        february,
    )
    assert (lifecycles["BBBUSDT"]["exit_reason"], lifecycles["BBBUSDT"]["exit_ms"]) == (
        "universe exit",
        march,
    )
    assert lifecycles["CCCUSDT"]["exit_reason"] == "window end (dust)"
    assert lifecycles["CCCUSDT"]["censored"]
    # The window end sells nothing: CCC's dust stays at the last close.
    last = month_start("2025-04") - HOUR
    assert fills_at(rows, last) == []
    assert F(result.final_after_close) == cash_after(rows, last + HOUR, capital) + F(D("3.3"))
    monthly = of_kind(rows, "monthly")
    assert [m["universe"] for m in monthly] == [["AAAUSDT", "BBBUSDT", "CCCUSDT"], [], []]
    assert monthly[1]["left"] == ["AAAUSDT", "BBBUSDT", "CCCUSDT"] and monthly[2]["left"] == []


def test_a_deferred_coin_fills_at_its_own_first_usable_hour(tmp_path):
    """Spec: masked fill hours defer the order, as for V4. BBB's spot is masked from 01:00 to
    03:00 on January 1, so its buy waits for 04:00 and takes ``0.99 x equity / n`` from the open
    mark of 04:00, which AAA's rise since 01:00 has moved."""
    hours = hours_in("2025-01", "2025-01")
    aaa = coin("AAAUSDT", path("100", (hours, "0.001")))
    bbb = coin("BBBUSDT", flat("50"), masked=(T0 + HOUR, T0 + 2 * HOUR, T0 + 3 * HOUR))
    market = load(tmp_path, World("2025-01", (aaa, bbb), {"2025-01": ("AAAUSDT", "BBBUSDT")}))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    (first,) = fills_at(rows, T0 + HOUR)
    open_aaa = spot_open(market, "AAAUSDT", T0 + HOUR)
    check_fill(first, 1, floor_step(INVESTED * CAPITAL / 2 / F(open_aaa)), open_aaa, SPOT)
    later = T0 + 4 * HOUR
    equity = open_equity(result, later)
    assert equity == mark_at(market, rows, later) and equity != CAPITAL
    (fill,) = fills_at(rows, later)
    assert fill["coin"] == "BBBUSDT"
    check_fill(fill, 1, floor_step(INVESTED * equity / 2 / 50), D(50), SPOT)
    order = order_event(rows, later, "BBBUSDT")
    assert F(D(order["equity"])) == equity and order["decision_ms"] == T0
    assert [e["hour_ms"] for e in events(rows, "order") if e["coin"] == "BBBUSDT"] == [later]


def test_a_newer_months_order_replaces_one_still_deferred(tmp_path):
    """Spec "Sizing", deferrals (via the pending book): BBB and EEE have no spot bar in January,
    so their January orders wait all month. February's first decision replaces both
    (``order_superseded``). BBB's newer order fills at 01:00 with February's n of 3. EEE left the
    universe and holds nothing, so its order of 0 needs no bar (V4's deferral rule) and comes due
    at 01:00 with nothing to do, though EEE's spot is still masked then."""
    hours = hours_in("2025-01", "2025-02")
    aaa = coin("AAAUSDT", path("100", (hours, "0")))
    bbb = coin("BBBUSDT", flat("40", "2025-02", "2025-02"), start=FEB)
    ccc = coin("CCCUSDT", path("20", (hours, "0")))
    eee = coin("EEEUSDT", path("10", (hours, "0")), masked=range(T0, FEB + DAY, HOUR))
    universes = {
        "2025-01": ("AAAUSDT", "BBBUSDT", "EEEUSDT"),
        "2025-02": ("AAAUSDT", "BBBUSDT", "CCCUSDT"),
    }
    market = load(tmp_path, World("2025-02", (aaa, bbb, ccc, eee), universes))

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    assert {f["coin"] for f in of_kind(rows, "fill") if f["hour_ms"] < FEB} == {"AAAUSDT"}
    superseded = {e["coin"]: e for e in events(rows, "order_superseded")}
    assert set(superseded) == {"BBBUSDT", "EEEUSDT"}
    for record in superseded.values():
        assert (record["hour_ms"], record["decision_ms"]) == (FEB, T0)
        assert F(D(record["target"])) == F(33, 100)
    at = FEB + HOUR
    eee_order = order_event(rows, at, "EEEUSDT")
    assert D(eee_order["target"]) == 0 and eee_order["legs"] == []
    assert not [f for f in of_kind(rows, "fill") if f["coin"] == "EEEUSDT"]
    equity = open_equity(result, at)
    assert equity == mark_at(market, rows, at)
    (fill,) = [f for f in fills_at(rows, at) if f["coin"] == "BBBUSDT"]
    check_fill(fill, 1, floor_step(INVESTED * equity / 3 / 40), D(40), SPOT)
    order = order_event(rows, at, "BBBUSDT")
    assert order["decision_ms"] == FEB and F(D(order["target"])) == F(33, 100)
    assert not [
        e for e in events(rows, "order") if e["decision_ms"] == T0 and e["coin"] == "BBBUSDT"
    ]


def test_a_dead_market_closes_a_held_coin_and_cancels_its_deferred_order(tmp_path):
    """Spec "Delisting or a dead market", as for V4: BBB's spot has no bar from 00:00 on January
    28 to February 9. February's order for it defers, and 168 hours after its last bar, at 00:00
    on February 4, the whole holding closes synthetically at the last close less 10%, with the
    spot fee and no filter, as the hour's first event. The close cancels the deferred order, so
    BBB comes back only through March's decision. There is no liquidation check to stop it. The
    close's hour is incomplete (spec "Pass rule", Codex review of PR #293): BBB's source had no
    bar there, though the mark holds only cash and AAA, which has its bar."""
    hours = hours_in("2025-01", "2025-03")
    dark = range(T0 + 27 * DAY, T0 + 40 * DAY, HOUR)
    aaa = coin("AAAUSDT", path("100", (hours, "0")))
    bbb = coin("BBBUSDT", path("50", (hours, "0")), masked=dark)
    world = World("2025-03", (aaa, bbb), every_month("2025-01", "2025-03", ("AAAUSDT", "BBBUSDT")))
    market = load(tmp_path, world)

    result, rows = cell_run(market, tmp_path)

    assert result.outcome == "complete" and residuals_hold(rows)
    close_h = T0 + 27 * DAY + 168 * HOUR  # the last bar opens at 23:00 on January 27
    assert close_h == FEB + 3 * DAY
    bbb_fills = [f for f in of_kind(rows, "fill") if f["coin"] == "BBBUSDT"]
    window_last = month_start("2025-04") - HOUR
    assert [f["hour_ms"] for f in bbb_fills] == [T0 + HOUR, close_h, MAR + HOUR, window_last]
    close = bbb_fills[1]
    assert (close["timestamp_ms"], close["side"], close["reason"]) == (close_h, -1, "delisting")
    assert F(D(close["quantity"])) == 99  # 0.495 x 10,000 at 50, the whole holding
    assert F(D(close["price"])) == F(D(close["unslipped_price"])) == 45  # 50 less 10%, no slip
    assert F(D(close["fee"])) == 99 * 45 * F(SPOT.fee_rate)
    (batch,) = events(rows, "synthetic_closes")
    assert batch["hour_ms"] == close_h
    assert [(leg["coin"], leg["venue"], leg["reason"]) for leg in batch["legs"]] == [
        ("BBBUSDT", "spot", "delisting")
    ]
    assert D(batch["legs"][0]["last_close"]) == 50 and D(batch["legs"][0]["price"]) == 45
    (cancelled,) = events(rows, "order_cancelled")
    assert (cancelled["hour_ms"], cancelled["coin"], cancelled["reason"]) == (
        close_h,
        "BBBUSDT",
        "delisting",
    )
    assert cancelled["decision_ms"] == FEB and F(D(cancelled["target"])) == F(495, 1000)
    assert not [
        e for e in events(rows, "order") if e["coin"] == "BBBUSDT" and FEB <= e["hour_ms"] < MAR
    ]
    # The close is the hour's first event: its open mark holds only cash and AAA.
    assert (
        open_equity(result, close_h)
        == cash_after(rows, close_h) + holdings(rows, close_h)["AAAUSDT"] * 100
    )
    assert set(holdings(rows, close_h)) == {"AAAUSDT"}
    assert market.coin("BBBUSDT").spot.bar(close_h) is None
    assert market.coin("AAAUSDT").spot.bar(close_h) is not None
    flags = {stamp: complete for stamp, _, complete in result.open_marks}
    assert (flags[close_h - HOUR], flags[close_h], flags[close_h + HOUR]) == (False, False, True)
    (hourly,) = [r for r in of_kind(rows, "hourly") if r["open_ms"] == close_h]
    assert hourly["complete"] is False
    # February's rebalance of AAA valued BBB at its carried mark.
    assert open_equity(result, FEB + HOUR) == mark_at(market, rows, FEB + HOUR)
    first, second = lifecycles_of(rows, "BBBUSDT")
    assert (first["exit_reason"], first["exit_ms"], first["censored"]) == (
        "delisting",
        close_h,
        False,
    )
    assert (second["entry_ms"], second["exit_reason"]) == (MAR + HOUR, "window end")
    equity = open_equity(result, MAR + HOUR)
    check_fill(bbb_fills[2], 1, floor_step(INVESTED * equity / 2 / 50), D(50), SPOT)


def test_a_flat_coins_deferred_order_is_cancelled_when_its_market_dies(tmp_path):
    """Codex review of PR #293 (spec "Pending orders are cancelled"), for the hold arm: BBB's
    spot has a bar at 00:00 on January 1, the decision's hour, and none from its fill hour on, so
    its January order waits while it holds nothing. 168 hours after that bar, at 01:00 on
    January 8, its market has died, and its data comes back in that very hour: the order is
    cancelled before the hour's fills (``order_cancelled``, reason ``dead market``), where
    without the cancel (``_spot_died`` stubbed out) it fills on the pre-outage decision. BBB
    comes back only through February's decision. The selection leaves out a coin with no daily
    bar in the 7 days before it, so this is a coin that dies after the decision."""
    hours = hours_in("2025-01", "2025-02")
    back = T0 + 7 * DAY + HOUR  # the first hour with a bar again
    aaa = coin("AAAUSDT", path("100", (hours, "0")))
    bbb = coin("BBBUSDT", path("50", (hours, "0")), masked=range(T0 + HOUR, back, HOUR))
    world = World("2025-02", (aaa, bbb), every_month("2025-01", "2025-02", ("AAAUSDT", "BBBUSDT")))
    market = load(tmp_path, world)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(run, "_spot_died", lambda store, h: False)
        _, stale = cell_run(market, tmp_path, name="without_the_cancel")
    result, rows = cell_run(market, tmp_path)

    assert order_event(stale, back, "BBBUSDT")["decision_ms"] == T0
    assert [f["hour_ms"] for f in of_kind(stale, "fill") if f["coin"] == "BBBUSDT"][0] == back
    assert result.outcome == "complete" and residuals_hold(rows)
    (cancelled,) = events(rows, "order_cancelled")
    assert (cancelled["hour_ms"], cancelled["coin"], cancelled["reason"]) == (
        back,
        "BBBUSDT",
        "dead market",
    )
    assert cancelled["decision_ms"] == T0 and F(D(cancelled["target"])) == F(495, 1000)
    assert events(rows, "order_superseded") == []  # nothing was left for February to replace
    assert not [e for e in events(rows, "order") if e["coin"] == "BBBUSDT" and e["hour_ms"] < FEB]
    bbb_fills = [f for f in of_kind(rows, "fill") if f["coin"] == "BBBUSDT"]
    assert [f["hour_ms"] for f in bbb_fills] == [FEB + HOUR, MAR - HOUR]
    assert order_event(rows, FEB + HOUR, "BBBUSDT")["decision_ms"] == FEB
    equity = open_equity(result, FEB + HOUR)
    check_fill(bbb_fills[0], 1, floor_step(INVESTED * equity / 2 / 50), D(50), SPOT)


# ---- hold_btc -----------------------------------------------------------------------------


def btc_world(*, btc_masked: Iterable[int] = ()) -> World:
    """BTCUSDT (with a perpetual and its funding) and ETHUSDT over January and February; BTCUSDT
    leaves the universe in February, which hold_btc ignores."""
    hours = hours_in("2025-01", "2025-02")
    btc = coin(
        "BTCUSDT",
        path("50000", (hours, "0.0002"), noise="0.003", seed=7),
        masked=btc_masked,
        perpetual=PerpetualSpec(funding_rate="0.0001"),
    )
    eth = coin("ETHUSDT", path("3000", (hours, "-0.0002"), noise="0.003", seed=8))
    universes = {"2025-01": ("ETHUSDT", "BTCUSDT"), "2025-02": ("ETHUSDT",)}
    return World("2025-02", (btc, eth), universes)


@pytest.mark.parametrize("multiple", [1, 2])
def test_hold_btc_buys_once_and_holds_to_the_window_end(multiple, tmp_path):
    """Spec: hold_btc buys BTCUSDT at the window's first fill hour (01:00 on its first day) with
    ``0.99 x equity``, under the hold's cash rule, and holds it to the window end, where it is
    sold at the last hour's close with the cell's costs."""
    market = load(tmp_path, btc_world())
    cell = CellSpec("hold_btc", CAPITAL, multiple)
    costs = cell.costs("spot")

    result, rows = cell_run(market, tmp_path, cell)

    assert result.outcome == "complete" and residuals_hold(rows)
    at, last = T0 + HOUR, MAR - HOUR
    buy, sale = of_kind(rows, "fill")
    price = spot_open(market, "BTCUSDT", at)
    quantity = floor_step(INVESTED * CAPITAL / F(price))
    assert (buy["hour_ms"], buy["coin"], buy["reason"]) == (at, "BTCUSDT", "rebalance")
    check_fill(buy, 1, quantity, price, costs)
    assert (sale["hour_ms"], sale["timestamp_ms"], sale["reason"]) == (
        last,
        last + HOUR - 1,
        "window end",
    )
    check_fill(sale, -1, quantity, spot_close(market, "BTCUSDT", last), costs)
    (order,) = events(rows, "order")
    assert (order["hour_ms"], order["coin"], order["decision_ms"]) == (at, "BTCUSDT", T0)
    assert F(D(order["target"])) == INVESTED and F(D(order["equity"])) == CAPITAL
    for hour in (at + HOUR, FEB, FEB + 5 * HOUR, last):
        assert open_equity(result, hour) == cash_after(rows, hour) + quantity * F(
            spot_open(market, "BTCUSDT", hour)
        )
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["coin"], lifecycle["side"], lifecycle["exit_reason"]) == (
        "BTCUSDT",
        "long",
        "window end",
    )
    assert (lifecycle["entry_ms"], lifecycle["exit_ms"]) == (at, last)
    assert F(result.final_after_close) == cash_after(rows, last + HOUR)
    monthly = of_kind(rows, "monthly")
    assert [m["universe"] for m in monthly] == [["ETHUSDT", "BTCUSDT"], ["ETHUSDT"]]
    assert of_kind(rows, "funding") == [] and of_kind(rows, "daily_coin") == []
    assert {name for name, _ in rows} == HOLD_KINDS


def test_hold_btc_defers_its_buy_when_the_first_fill_hour_is_masked(tmp_path):
    """BTCUSDT's spot is masked at 01:00 and 02:00 on the window's first day, so the buy waits
    for BTC's first later hour with a spot bar, 03:00, sized from that hour's open mark."""
    market = load(tmp_path, btc_world(btc_masked=(T0 + HOUR, T0 + 2 * HOUR)))

    result, rows = cell_run(market, tmp_path, BTC_ONLY)

    assert result.outcome == "complete"
    at = T0 + 3 * HOUR
    buy = of_kind(rows, "fill")[0]
    price = spot_open(market, "BTCUSDT", at)
    assert buy["hour_ms"] == at
    check_fill(buy, 1, floor_step(INVESTED * open_equity(result, at) / F(price)), price, SPOT)
    (order,) = events(rows, "order")
    assert order["hour_ms"] == at and F(D(order["equity"])) == open_equity(result, at)


def test_hold_btc_without_btcusdt_is_an_engine_error(tmp_path):
    """A market without BTCUSDT cannot run hold_btc: a ValueError inside the loop, so the cell
    ends as ``engine_error`` with its records closed and its receipt written."""
    eth = coin("ETHUSDT", flat("3000"))
    market = load(tmp_path, World("2025-01", (eth,), {"2025-01": ("ETHUSDT",)}))

    result, rows = cell_run(market, tmp_path, BTC_ONLY)

    assert result.outcome == "engine_error"
    assert result.reason is not None and result.reason.startswith("ValueError: ")
    assert "BTCUSDT" in result.reason
    assert of_kind(rows, "fill") == [] and result.final_after_close is None
    assert [name for name, _ in rows].count("outcome") == 1 and rows[-1][0] == "outcome"


# ---- hold_btc_trend -----------------------------------------------------------------------

TREND = CellSpec("hold_btc_trend", CAPITAL, 1)
BTC_START = month_start("2024-05")
BTC_UP = T0 + 9 * DAY  # 2025-01-10: BTCUSDT's first daily close above its SMA(200)
BTC_DOWN = T0 + 19 * DAY  # 2025-01-20: its first daily close back below it
CROSSING = ((BTC_START, "100"), (BTC_UP, "120"), (BTC_DOWN, "90"))


def stepped(start: int, end: int, levels: Sequence[tuple[int, str]]) -> tuple[Decimal, ...]:
    """Hourly closes from ``start`` to ``end``: each hour closes at the price of the latest of
    ``levels`` (open, price) at or before its open. A bar opens at the previous close, so the
    hour of a step opens at the old price and every hour after it at the new one."""
    return tuple(
        D([price for at, price in levels if at <= open_ms][-1])
        for open_ms in range(start, end, HOUR)
    )


def btc_crossing(
    levels: Sequence[tuple[int, str]] = CROSSING, masked: Iterable[int] = ()
) -> CoinSpec:
    """BTCUSDT on spot only, from 2024-05 to the window's end. Flat at 100 its close ties its
    SMA(200), so it has no slow vote; it closes at 120 from BTC_UP (above the average) and at 90
    from BTC_DOWN (below it) unless ``levels`` say otherwise."""
    return coin("BTCUSDT", stepped(BTC_START, MAR, levels), start=BTC_START, masked=masked)


def crossing_world(btc: CoinSpec) -> World:
    """January and February with ETHUSDT (flat, spot only) as the only coin ever selected:
    ``btc`` is in the packs and never in a universe, which hold_btc_trend ignores."""
    eth = coin("ETHUSDT", flat("3000", "2025-01", "2025-02"))
    return World("2025-02", (btc, eth), every_month("2025-01", "2025-02", ("ETHUSDT",)))


def trend_changes(market: Market) -> list[tuple[int, bool]]:
    """Every 00:00 of the window at which hold_btc_trend should change state, and the state it
    changes to, from an SMA(200) recomputed here (spec: invested while BTC's last completed daily
    close is above the mean of its last 200 closes, cash otherwise and while fewer than 200 daily
    bars exist). The decision at ``h`` reads only the daily bars that open at or before ``h - 1
    day``; a day without a bar adds none."""
    bars = market.daily("BTCUSDT")
    state, changes = False, []
    for h in range(T0, MAR, DAY):
        seen = [bar for bar in bars if bar.open_ms <= h - DAY]
        mean = sum((F(bar.close) for bar in seen[-200:]), F(0)) / 200
        invested = len(seen) >= 200 and F(seen[-1].close) > mean
        if invested != state:
            state = invested
            changes.append((h, invested))
    return changes


def test_hold_btc_trend_buys_when_btc_closes_above_its_sma200_and_sells_when_it_closes_below(
    tmp_path,
):
    """Spec "hold_btc_trend", ruling R2: BTCUSDT ties its SMA(200) until BTC_UP, closes above it
    on BTC_UP and below it on BTC_DOWN. The decision at 00:00 the day after BTC_UP buys
    ``0.99 x equity`` of BTCUSDT at the next 01:00, from the equity of that open mark; the one
    after BTC_DOWN sells all of it at its 01:00. No other order is made, though ETHUSDT is the
    month's universe, and the one lifecycle ends with the reason ``signal``, as do the fills and
    the orders' source. Nothing is held at the window end, so nothing is sold there."""
    market = load(tmp_path, crossing_world(btc_crossing()))
    buy_h, sell_h = BTC_UP + DAY + HOUR, BTC_DOWN + DAY + HOUR
    assert trend_changes(market) == [(BTC_UP + DAY, True), (BTC_DOWN + DAY, False)]

    result, rows = cell_run(market, tmp_path, TREND)

    assert result.outcome == "complete" and residuals_hold(rows)
    buy, sale = of_kind(rows, "fill")  # these two fills and no other
    assert (buy["hour_ms"], buy["coin"], buy["reason"]) == (buy_h, "BTCUSDT", "signal")
    assert open_equity(result, buy_h) == CAPITAL
    quantity = floor_step(INVESTED * CAPITAL / 120)
    check_fill(buy, 1, quantity, D(120), SPOT)
    assert (sale["hour_ms"], sale["coin"], sale["reason"]) == (sell_h, "BTCUSDT", "signal")
    check_fill(sale, -1, quantity, D(90), SPOT)
    for hour in (buy_h + HOUR, BTC_UP + 5 * DAY, sell_h - HOUR):
        equity = open_equity(result, hour)
        assert equity == mark_at(market, rows, hour)
        assert equity == cash_after(rows, hour - 1) + quantity * F(
            spot_open(market, "BTCUSDT", hour)
        )
    assert open_equity(result, sell_h + HOUR) == cash_after(rows, sell_h)
    assert holdings(rows, MAR) == {}
    assert F(result.final_after_close) == cash_after(rows, MAR)
    first, second = events(rows, "order")  # and no other order event
    assert [e["type"] for e in of_kind(rows, "event")] == ["order", "order"]
    assert (first["hour_ms"], first["coin"]) == (buy_h, "BTCUSDT")
    assert first["decision_ms"] == BTC_UP + DAY and first["source"] == "signal"
    assert F(D(first["target"])) == INVESTED and F(D(first["equity"])) == CAPITAL
    assert not first["eligible"] and first["band"] is None
    assert (second["hour_ms"], second["decision_ms"]) == (sell_h, BTC_DOWN + DAY)
    assert second["source"] == "signal" and D(second["target"]) == 0
    assert F(D(second["equity"])) == open_equity(result, sell_h)
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["coin"], lifecycle["side"], lifecycle["exit_reason"]) == (
        "BTCUSDT",
        "long",
        "signal",
    )
    assert (lifecycle["entry_ms"], lifecycle["exit_ms"], lifecycle["censored"]) == (
        buy_h,
        sell_h,
        False,
    )
    monthly = of_kind(rows, "monthly")
    assert [(m["month"], m["open_ms"], m["universe"]) for m in monthly] == [
        ("2025-01", T0, ["ETHUSDT"]),
        ("2025-02", FEB, ["ETHUSDT"]),
    ]
    assert of_kind(rows, "funding") == [] and of_kind(rows, "daily_coin") == []
    assert {name for name, _ in rows} == HOLD_KINDS


@pytest.mark.parametrize(
    ("btc_start", "buys_at"),
    [(T0 - 170 * DAY, T0 + 30 * DAY), (T0 + 5 * DAY, None)],
    ids=["warms inside the window", "never warms inside the window"],
)
def test_hold_btc_trend_starts_in_cash_and_counts_a_warming_sma_as_cash(
    btc_start, buys_at, tmp_path
):
    """Ruling R2: the account starts in cash and a warming SMA is cash. BTCUSDT rises about 0.7% a
    day, so its close is above its own average from its first bar, yet the account holds nothing
    until a decision reads 200 daily bars (the 200th is the first with an SMA(200)): at 00:00 on
    January 31 for a first bar 170 days before the window, and never in the window for a first bar
    on January 6."""
    closes = path("50000", ((MAR - btc_start) // HOUR, "0.0003"), noise="0.003", seed=61)
    market = load(tmp_path, crossing_world(CoinSpec("BTCUSDT", Series(btc_start, closes))))
    warm = btc_start + 200 * DAY  # the first decision that reads 200 daily bars
    bars = market.daily("BTCUSDT")
    if buys_at is None:
        assert len(bars) < 200  # BTC never has 200 daily bars by the window's end
    else:
        assert sum(bar.open_ms <= warm - DAY for bar in bars) == 200
        assert sum(bar.open_ms <= warm - 2 * DAY for bar in bars) == 199
    assert trend_changes(market) == ([] if buys_at is None else [(warm, True)])

    result, rows = cell_run(market, tmp_path, TREND)

    assert result.outcome == "complete" and residuals_hold(rows)
    fills = of_kind(rows, "fill")
    if buys_at is None:
        assert fills == [] and events(rows, "order") == []
    else:
        assert warm == buys_at
        first, last = fills  # the buy, and the window end's sale
        assert (first["hour_ms"], first["side"], first["reason"]) == (warm + HOUR, 1, "signal")
        assert last["reason"] == "window end"
    # Cash until then: every open mark up to the buy's hour is the capital.
    assert all(F(equity) == CAPITAL for stamp, equity, _ in result.open_marks if stamp <= warm)


@pytest.mark.parametrize(
    ("masked_day", "buys_at", "sells_at"),
    [
        (BTC_UP, BTC_UP + 2 * DAY, BTC_DOWN + DAY),
        (BTC_DOWN, BTC_UP + DAY, BTC_DOWN + 2 * DAY),
    ],
    ids=["a day in cash", "a day invested"],
)
def test_hold_btc_trend_keeps_its_state_on_a_day_without_a_btc_bar(
    masked_day, buys_at, sells_at, tmp_path
):
    """Review Focus 1: BTCUSDT's hours 00:00 to 05:59 of one day are masked, so that day has no
    daily bar (less than 20 of 24 hours). The decision closing it reads the bar before it and
    keeps the state: a day in cash (BTC_UP) delays the buy by a day, and a day invested (BTC_DOWN)
    delays the sale by one, though the masked day's own closes would have voted the other way. No
    order is made on the day without a bar, and no later bar is read."""
    masked = day_hours(masked_day, range(6))
    market = load(tmp_path, crossing_world(btc_crossing(masked=masked)))
    days = {bar.open_ms for bar in market.daily("BTCUSDT")}
    assert masked_day not in days and masked_day - DAY in days and masked_day + DAY in days
    assert trend_changes(market) == [(buys_at, True), (sells_at, False)]

    result, rows = cell_run(market, tmp_path, TREND)

    assert result.outcome == "complete" and residuals_hold(rows)
    buy, sale = of_kind(rows, "fill")
    quantity = floor_step(INVESTED * CAPITAL / 120)
    check_fill(buy, 1, quantity, D(120), SPOT)
    check_fill(sale, -1, quantity, D(90), SPOT)
    assert (buy["hour_ms"], sale["hour_ms"]) == (buys_at + HOUR, sells_at + HOUR)
    assert [e["decision_ms"] for e in events(rows, "order")] == [buys_at, sells_at]
    (lifecycle,) = of_kind(rows, "lifecycle")
    assert (lifecycle["entry_ms"], lifecycle["exit_ms"]) == (buys_at + HOUR, sells_at + HOUR)
    assert lifecycle["exit_reason"] == "signal"


@pytest.mark.parametrize("side", ["buy", "sell"])
def test_hold_btc_trend_defers_a_fill_to_the_next_unmasked_hour(side, tmp_path):
    """Masked fill hours defer the order, as for the other hold arms. BTCUSDT's spot is masked at
    01:00 and 02:00 after the buy's decision (or the sale's), so the order waits for 03:00, sized
    and filled at that open, which differs from the one at 01:00: BTC moves from 120 to 126 in
    the 02:00 hour for the buy, and from 90 to 81 for the sale. Two masked hours leave that day
    22 usable ones, so it keeps its daily bar."""
    deciding = BTC_UP + DAY if side == "buy" else BTC_DOWN + DAY
    levels = sorted([*CROSSING, (deciding + 2 * HOUR, "126" if side == "buy" else "81")])
    masked = (deciding + HOUR, deciding + 2 * HOUR)
    market = load(tmp_path, crossing_world(btc_crossing(levels, masked)))
    buy_h = BTC_UP + DAY + (3 if side == "buy" else 1) * HOUR
    sell_h = BTC_DOWN + DAY + (3 if side == "sell" else 1) * HOUR
    assert trend_changes(market) == [(BTC_UP + DAY, True), (BTC_DOWN + DAY, False)]

    result, rows = cell_run(market, tmp_path, TREND)

    assert result.outcome == "complete" and residuals_hold(rows)
    assert fills_at(rows, deciding + HOUR) == [] and fills_at(rows, deciding + 2 * HOUR) == []
    buy, sale = of_kind(rows, "fill")
    assert (buy["hour_ms"], sale["hour_ms"]) == (buy_h, sell_h)
    price, sale_price = (D(126), D(90)) if side == "buy" else (D(120), D(81))
    bought = floor_step(INVESTED * open_equity(result, buy_h) / F(price))
    check_fill(buy, 1, bought, price, SPOT)
    check_fill(sale, -1, bought, sale_price, SPOT)
    first, second = events(rows, "order")  # one order event each, at its own fill hour
    assert [(e["decision_ms"], e["hour_ms"]) for e in (first, second)] == [
        (BTC_UP + DAY, buy_h),
        (BTC_DOWN + DAY, sell_h),
    ]
    assert F(D(first["equity"])) == open_equity(result, buy_h) == mark_at(market, rows, buy_h)
    assert F(D(second["equity"])) == open_equity(result, sell_h) == mark_at(market, rows, sell_h)
    assert [r["entry_ms"] for r in of_kind(rows, "lifecycle")] == [buy_h]


def test_hold_btc_trend_follows_the_hold_cash_rule_and_fees(tmp_path):
    """Spec "hold_btc_trend": the hold comparisons' cash rule, fees, filters and dust, at 1,000
    USDT and doubled costs. BTC steps from 100 to 123.456 and the buy is 0.99 x 1,000 at that
    open, floored to the step (the exact share is not a whole number of steps), with the slipped
    price and the fee on it. A spot buy of 0.99 of the equity always fits the cash (``0.99 x (1 +
    s)(1 + f)`` is below 1), so the account is never cut to its cash and the 1% reserve is what
    is left. BTC then crashes to 0.05: the holding is worth under the minimum notional, so the
    sale is refused and the whole holding stays as dust, valued at its mark, to the window end,
    where it is censored as ``window end (dust)`` without a sale."""
    levels = ((BTC_START, "100"), (BTC_UP, "123.456"), (BTC_DOWN, "0.05"))
    market = load(tmp_path, crossing_world(btc_crossing(levels)))
    cell = CellSpec("hold_btc_trend", 1000, 2)
    costs = cell.costs("spot")
    capital, price, low = F(1000), D("123.456"), D("0.05")
    buy_h, sell_h = BTC_UP + DAY + HOUR, BTC_DOWN + DAY + HOUR

    result, rows = cell_run(market, tmp_path, cell)

    assert result.outcome == "complete" and residuals_hold(rows)
    (buy,) = of_kind(rows, "fill")  # the sale is refused, and the window end sells no dust
    share = INVESTED * capital / F(price)
    assert share % STEP != 0
    quantity = floor_step(share)
    check_fill(buy, 1, quantity, price, costs)
    need = (1 + F(costs.slippage_rate)) * (1 + F(costs.fee_rate))
    assert INVESTED * need < 1
    assert quantity * F(price) * need <= capital  # the cash pays the whole buy
    cash = cash_after(rows, buy_h, capital)
    assert 0 < cash < capital * (1 - INVESTED)
    assert events(rows, "increase_cut") == []
    first, second = events(rows, "order")
    assert [e["hour_ms"] for e in (first, second)] == [buy_h, sell_h]
    assert D(second["target"]) == 0 and second["source"] == "signal"
    assert second["legs"][0]["orders"] == []  # nothing can be sold
    assert quantity * F(low) < 5  # below the minimum notional
    assert F(D(second["legs"][0]["dust"])) == F(D(second["state"]["dust"])) == quantity
    for hour in (sell_h, sell_h + 10 * HOUR, FEB + DAY):
        assert open_equity(result, hour) == cash_after(rows, hour, capital) + quantity * F(low)
    assert fills_at(rows, MAR - HOUR) == []
    (lifecycle,) = lifecycles_of(rows, "BTCUSDT")
    assert (lifecycle["entry_ms"], lifecycle["exit_reason"], lifecycle["censored"]) == (
        buy_h,
        "window end (dust)",
        True,
    )
    assert F(result.final_after_close) == cash_after(rows, MAR, capital) + quantity * F(low)


def test_hold_btc_trend_without_btcusdt_is_an_engine_error(tmp_path):
    """A market without BTCUSDT cannot run hold_btc_trend: a ValueError inside the loop, at its
    first decision, so the cell ends as ``engine_error`` with its records closed, as hold_btc's
    does."""
    eth = coin("ETHUSDT", flat("3000"))
    market = load(tmp_path, World("2025-01", (eth,), {"2025-01": ("ETHUSDT",)}))

    result, rows = cell_run(market, tmp_path, TREND)

    assert result.outcome == "engine_error"
    assert result.reason is not None and result.reason.startswith("ValueError: ")
    assert "BTCUSDT" in result.reason
    assert of_kind(rows, "fill") == [] and result.final_after_close is None
    assert [name for name, _ in rows].count("outcome") == 1 and rows[-1][0] == "outcome"
    assert rows[-1][1]["hour_ms"] == T0


# ---- both arms ----------------------------------------------------------------------------


def trend_world() -> World:
    """BTCUSDT rising, with its perpetual, and ETHUSDT falling, spot only, from October 2024 (the
    history the V4 signals need), both selected in January 2025."""
    start, hours = month_start("2024-10"), hours_in("2024-10", "2025-01")
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, path("50000", (hours, "0.0003"), noise="0.003", seed=1)),
        perpetual=PerpetualSpec(),
    )
    eth = CoinSpec(
        "ETHUSDT", Series(start, path("2000", (hours, "-0.0003"), noise="0.003", seed=2))
    )
    return World("2025-01", (btc, eth), {"2025-01": ("BTCUSDT", "ETHUSDT")})


def shapes(rows: Rows) -> dict[str, set[frozenset[str]]]:
    """Each record kind's key sets, and each event type's as ``event:<type>``."""
    found: dict[str, set[frozenset[str]]] = {}
    for kind, record in rows:
        name = f"event:{record['type']}" if kind == "event" else kind
        found.setdefault(name, set()).add(frozenset(record))
    return found


def test_hold_arms_write_the_same_record_shapes(tmp_path):
    """Controller ruling P4: the hold arms write the V4 arms' hourly, monthly, fill, event,
    lifecycle and outcome records in the same shapes (and no daily_coin, having no signals), and
    return the same ``CellResult``."""
    market = load(tmp_path, trend_world())
    crossing = load(tmp_path, crossing_world(btc_crossing()), "crossing")
    v4_out = tmp_path / "out" / "v4"
    v4 = run.run_v4_cell(market, CellSpec("v4_main", CAPITAL, 1), v4_out)
    v4_shapes = shapes(list(read_records(v4_out / run.RECORDS_FILE, v4.receipt)))

    # hold_btc_trend trades only in the world where BTC crosses its SMA(200).
    for cell, world in ((UNIVERSE, market), (BTC_ONLY, market), (TREND, crossing)):
        result, rows = cell_run(world, tmp_path, cell, cell.arm)

        assert type(result) is run.CellResult and result.outcome == "complete"
        assert [f.name for f in dataclasses.fields(result)] == [
            f.name for f in dataclasses.fields(run.CellResult)
        ]
        assert {name for name, _ in rows} == HOLD_KINDS
        found = shapes(rows)
        assert "event:order" in found
        for name, keys in found.items():
            assert name in v4_shapes, name
            assert keys == v4_shapes[name], name


UNCHANGED_WORLDS = {
    "universe": universe_world,
    "cut": cut_world,
    "btc": btc_world,
    "btc masked": lambda: btc_world(btc_masked=(T0 + HOUR, T0 + 2 * HOUR)),
    "trend": trend_world,
}

# Each hold arm's output on the step-3 worlds above at 1883d2a, the commit before hold_btc_trend
# (controller ruling F1): the SHA-256 of the records file, and of the canonical JSON of the
# summary without its receipt_sha256 (which follows from the records). Captured at that commit,
# before any change to hold.py, by the procedure this test follows.
BASE_PINS = (
    (
        ("universe", "hold_universe", 10000, 1),
        "7eb8fcd29a6d27f80ba6c98cb35b21dfefd1961714cd63b92c92c71c4b28063f",
        "8afb765703957d7a817ed81239caf5eb07360e9716cb5b039a8141153c20b6e2",
    ),
    (
        ("universe", "hold_universe", 1000, 2),
        "375f00a0b3d9f0e6a41ea9bea1403fc098fc9b60c2ef744915c54808dea2bc4d",
        "c6f1222583ef1e6d16079766ce84e0c714b67fe31d6f5d4f51840f5bc16145fb",
    ),
    (
        ("cut", "hold_universe", 10000, 1),
        "17a1d3d000b642341a59fe0ad742100de655e91deacd25c6e115a8aa17dce43b",
        "1433196f3f87883d6a1174bc95203fb2ed9e62fc7f7cb84b89a20e5e2a71a175",
    ),
    (
        ("btc", "hold_btc", 10000, 1),
        "441f2fe5506f0fef459df3c832d36256a3e190cf5b1e58256e8abc698a88fa81",
        "9adf8868371d6e19b919d8bae6e7faf3b6299e6156c402db74b99a971dd0da23",
    ),
    (
        ("btc", "hold_btc", 1000, 2),
        "0597e3c3c0803766607e03dc4670ca685e80699f5a52bd638f83e0cf9a254ae6",
        "a39c1c59ef672457bf378bdf9001e96df0cf0281b28693a20f699a9c2ab22570",
    ),
    (
        ("btc", "hold_universe", 10000, 1),
        "b581a261fd66d062a0d6c094afe295def5c6d15a1d4101098396e7cb78f404b9",
        "db67bc85eaf2d9df270df6c0b5c771fd62ed18da0edf852328b452f69b075ce6",
    ),
    (
        ("btc masked", "hold_btc", 10000, 1),
        "7119769406418ca201ad2320557cbd9c398734fddba0d1b12a5ab250f16746ce",
        "aaf87da7801e5c4726ac6a6953d436f6f9dfcbdefbaf9e46aaa6f3365b11fd23",
    ),
    (
        ("trend", "hold_universe", 10000, 1),
        "03a70c5044c4e02b870a3e56b9beede0e5db8395647c8a89ff76c9b57c20a0fb",
        "79631dff313bf37e80eeaeda28bbeb89dddf3e4df5603098952aa7bd769fb684",
    ),
    (
        ("trend", "hold_btc", 10000, 1),
        "978b5ca22fc443a4c664628f7436ab93343ff5527eea8791cd5c4b892ce6e818",
        "4712dfafca5e2b8ccd44a3818eb62a5ff2382e2438dc651ccd069bd229517bc3",
    ),
)


@pytest.mark.parametrize(
    ("which", "records_sha256", "summary_sha256"),
    BASE_PINS,
    ids=[f"{w}-{arm}-{capital}-{multiple}x" for (w, arm, capital, multiple), _, _ in BASE_PINS],
)
def test_hold_btc_and_hold_universe_are_unchanged(which, records_sha256, summary_sha256, tmp_path):
    """Controller ruling F1: adding hold_btc_trend changes nothing for the two older hold arms.
    On each world, their records are byte-identical to what 1883d2a wrote (no record key was
    added for them), and their summary, without ``receipt_sha256``, is the same document."""
    world, arm, capital, multiple = which
    market = load(tmp_path, UNCHANGED_WORLDS[world]())
    cell = CellSpec(arm, capital, multiple)

    result, _ = cell_run(market, tmp_path, cell)

    assert result.receipt.records_sha256 == records_sha256
    summary = build_summary(cell, result, tmp_path / "out" / "cell" / run.RECORDS_FILE)
    del summary["receipt_sha256"]
    document = json.dumps(summary, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(document.encode()).hexdigest() == summary_sha256


def test_v4_arms_are_not_run_here(tmp_path):
    market = load(tmp_path, btc_world())
    out = tmp_path / "v4"
    with pytest.raises(ValueError, match="not a hold arm"):
        hold.run_hold_cell(market, CellSpec("v4_main", CAPITAL, 1), out)
    assert not out.exists() or not any(out.iterdir())


def test_hold_imports_nothing_from_the_frozen_packages():
    """Constraints, frozen code and imports: hold.py imports only the V4 engine's own modules
    (and the standard library), so it can reach no 2024 guard."""
    tree = ast.parse(Path(hold.__file__).read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    modules |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    ours = {m for m in modules if m and m.startswith("crypto_grid_bot.")}
    assert ours and all(m.startswith("crypto_grid_bot.v4.engine.") for m in ours)
