"""V4 engine task 13: the hold comparisons, ``hold_universe`` and ``hold_btc``.

Each test replays a small synthetic world from ``tests/v4_synthetic.py`` through
``hold.run_hold_cell`` and checks the records against the spec's hold rules ("Versions in the
run", the hold comparisons), recomputed here from the bars and from the fill records: a target of
``0.99 x equity / n`` at the open mark of the coin's own fill hour, sells before buys, a buy cut to
the cash it can pay for with its fee, the filters and dust, deferrals and a newer month's order,
the dead-market close and the window end. Expected quantities are exact Fractions floored to the
spot step. The network is blocked for every test (the autouse fixture) and no real pack is read.
"""

from __future__ import annotations

import ast
import dataclasses
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
    BBB comes back only through March's decision. There is no liquidation check to stop it."""
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
    v4_out = tmp_path / "out" / "v4"
    v4 = run.run_v4_cell(market, CellSpec("v4_main", CAPITAL, 1), v4_out)
    v4_shapes = shapes(list(read_records(v4_out / run.RECORDS_FILE, v4.receipt)))

    for cell in (UNIVERSE, BTC_ONLY):
        result, rows = cell_run(market, tmp_path, cell, cell.arm)

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
