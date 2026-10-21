"""V4 engine task 6: the shared spot and USDT-M futures ledger, keyed by venue and symbol.

The ledger is driven by hand with synthetic fills and prices; no pack and no network is
involved. V3.1's ``combined.execution.funding_cashflow`` is the oracle for the funding sign
convention only: the engine never calls V3.1's account.
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError
from decimal import Decimal, localcontext
from typing import Any, get_args

import pytest

from crypto_grid_bot.combined.account import PositionSnapshot
from crypto_grid_bot.combined.execution import funding_cashflow
from crypto_grid_bot.v4.engine.ledger import Audit, Fill, Ledger, Mark, Venue
from crypto_grid_bot.v4.engine.numbers import CONTEXT

D = Decimal
HOUR = 3_600_000
T = 1_735_689_600_000  # 2025-01-01 00:00 UTC: synthetic, any date is allowed
BTC = "BTCUSDT"
ETH = "ETHUSDT"


def fill(
    venue: Venue,
    symbol: str,
    side: int,
    quantity: str,
    price: str,
    fee: str = "0",
    *,
    at: int = T,
    reason: str = "signal",
) -> Fill:
    return Fill(at, venue, symbol, side, D(quantity), D(price), D(fee), reason)


def assert_exact(ledger: Ledger, prices: dict[tuple[Venue, str], Decimal]) -> Audit:
    audit = ledger.audit(prices)
    assert audit.wallet_residual == 0
    assert all(residual == 0 for residual in audit.quantity_residuals.values())
    assert abs(audit.equity_residual) <= D("1e-18")
    return audit


# ---------------------------------------------------------------------------------------
# Positions by venue and symbol
# ---------------------------------------------------------------------------------------


def test_one_coin_holds_a_spot_and_a_futures_leg_under_one_name() -> None:
    ledger = Ledger(D(10000))
    ledger.fill(fill("spot", BTC, 1, "0.5", "20000", "10"))
    ledger.fill(fill("futures", BTC, -1, "0.3", "20010", "3.0015"))
    assert ledger.quantity("spot", BTC) == D("0.5")
    assert ledger.quantity("futures", BTC) == D("-0.3")
    assert dict(ledger.positions()) == {("futures", BTC): D("-0.3"), ("spot", BTC): D("0.5")}
    assert list(ledger.positions()) == [("futures", BTC), ("spot", BTC)]
    # Each leg needs its own price: the two legs are two positions.
    with pytest.raises(ValueError, match="futures"):
        ledger.mark({("spot", BTC): D(20000)})
    with pytest.raises(ValueError, match="spot"):
        ledger.mark({("futures", BTC): D(20000)})
    # Selling the spot leg leaves the futures leg alone, and the reverse.
    ledger.fill(fill("spot", BTC, -1, "0.2", "20100", "4.02"))
    assert ledger.quantity("spot", BTC) == D("0.3")
    assert ledger.quantity("futures", BTC) == D("-0.3")
    ledger.fill(fill("futures", BTC, 1, "0.3", "20000", "3"))
    assert ledger.quantity("futures", BTC) == 0
    assert ledger.quantity("spot", BTC) == D("0.3")
    assert dict(ledger.positions()) == {("spot", BTC): D("0.3")}
    assert_exact(ledger, {("spot", BTC): D(20500), ("futures", BTC): D(20500)})


def test_the_venue_literal_names_the_two_venues() -> None:
    assert get_args(Venue) == ("spot", "futures")


def test_positions_holds_only_open_legs_sorted_and_signed() -> None:
    ledger = Ledger(D(10000))
    assert dict(ledger.positions()) == {}
    ledger.fill(fill("spot", ETH, 1, "1", "2000"))
    ledger.fill(fill("futures", ETH, -1, "2", "2000"))
    ledger.fill(fill("spot", BTC, 1, "0.1", "20000"))
    ledger.fill(fill("futures", BTC, 1, "0.1", "20000"))
    ledger.fill(fill("futures", BTC, -1, "0.1", "20000"))
    positions = ledger.positions()
    assert list(positions.items()) == [
        (("futures", ETH), D(-2)),
        (("spot", BTC), D("0.1")),
        (("spot", ETH), D(1)),
    ]
    with pytest.raises(TypeError):
        positions[("spot", BTC)] = D(0)  # type: ignore[index]
    assert ledger.quantity("futures", BTC) == 0
    assert ledger.quantity("spot", "XRPUSDT") == 0


# ---------------------------------------------------------------------------------------
# Spot: notional and fee, FIFO lots
# ---------------------------------------------------------------------------------------


def test_spot_buy_and_sell_move_cash_by_notional_and_fee() -> None:
    ledger = Ledger(D(1000))
    assert ledger.cash == D(1000)
    assert ledger.fill(fill("spot", ETH, 1, "2", "100", "0.2")) == 0
    assert ledger.cash == D("799.8")
    assert ledger.fill(fill("spot", ETH, -1, "1.5", "110", "0.165")) == D(15)
    assert ledger.cash == D("964.635")
    assert ledger.quantity("spot", ETH) == D("0.5")
    # A sell may not exceed the held quantity, and spot never goes short.
    with pytest.raises(ValueError, match="exceeds"):
        ledger.fill(fill("spot", ETH, -1, "0.6", "110"))
    with pytest.raises(ValueError, match="exceeds"):
        ledger.fill(fill("spot", BTC, -1, "0.1", "20000"))
    assert ledger.cash == D("964.635")
    assert ledger.quantity("spot", ETH) == D("0.5")
    assert ledger.fill(fill("spot", ETH, -1, "0.5", "90", "0.045")) == D(-5)
    assert ledger.cash == D("1009.59")
    assert dict(ledger.positions()) == {}
    assert_exact(ledger, {})


def test_spot_sells_realise_fifo_and_the_rest_is_unrealised() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("spot", ETH, 1, "1", "100"))
    ledger.fill(fill("spot", ETH, 1, "1", "120"))
    # FIFO: the first lot (100) goes whole, then half of the second (120).
    assert ledger.fill(fill("spot", ETH, -1, "1.5", "130")) == D(35)
    assert ledger.unrealised("spot", ETH, D(130)) == D(5)
    assert ledger.unrealised("spot", ETH, D(110)) == D(-5)
    assert ledger.unrealised("spot", BTC, D(1)) == 0
    mark = ledger.mark({("spot", ETH): D(130)})
    assert mark.spot_value == D(65)
    assert mark.equity == ledger.cash + D(65)
    assert_exact(ledger, {("spot", ETH): D(130)})


# ---------------------------------------------------------------------------------------
# Futures: realised P&L minus fee moves cash, FIFO lots, no crossing of zero
# ---------------------------------------------------------------------------------------


def test_futures_open_reduce_close_realise_fifo_pnl() -> None:
    ledger = Ledger(D(1000))
    # Opening moves cash by the fee only: no margin is booked (Ruling R2).
    assert ledger.fill(fill("futures", ETH, 1, "1", "100", "0.05")) == 0
    assert ledger.cash == D("999.95")
    assert ledger.fill(fill("futures", ETH, 1, "1", "110", "0.055")) == 0
    assert ledger.cash == D("999.895")
    assert ledger.quantity("futures", ETH) == D(2)
    # FIFO: the first lot (100) closes whole, then half of the second (110).
    assert ledger.fill(fill("futures", ETH, -1, "1.5", "120", "0.09")) == D(25)
    assert ledger.cash == D("1024.805")
    assert ledger.quantity("futures", ETH) == D("0.5")
    assert ledger.unrealised("futures", ETH, D(130)) == D(10)
    assert ledger.fill(fill("futures", ETH, -1, "0.5", "90", "0.0225")) == D(-10)
    assert ledger.cash == D("1014.7825")
    assert ledger.quantity("futures", ETH) == 0
    # A short gains when the price falls.
    assert ledger.fill(fill("futures", BTC, -1, "2", "50", "0.05")) == 0
    assert ledger.quantity("futures", BTC) == D(-2)
    assert ledger.unrealised("futures", BTC, D(45)) == D(10)
    assert ledger.fill(fill("futures", BTC, -1, "1", "60", "0.03")) == 0
    assert ledger.fill(fill("futures", BTC, 1, "2.5", "40", "0.05")) == D(20 + 10)
    assert ledger.quantity("futures", BTC) == D("-0.5")
    assert ledger.unrealised("futures", BTC, D(70)) == D(-5)
    assert ledger.cash == D("1014.7825") - D("0.13") + D(30)
    assert_exact(ledger, {("futures", BTC): D(70)})


def test_a_futures_fill_crossing_zero_is_refused() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("futures", ETH, 1, "1", "100", "0.05"))
    before = (ledger.cash, dict(ledger.positions()), ledger.audit({("futures", ETH): D(100)}))
    with pytest.raises(ValueError, match="flip"):
        ledger.fill(fill("futures", ETH, -1, "1.5", "100", "0.075", at=T + HOUR))
    after = (ledger.cash, dict(ledger.positions()), ledger.audit({("futures", ETH): D(100)}))
    assert after == before
    # The refused fill did not move the clock: a fill at the earlier hour is still booked.
    ledger.fill(fill("futures", ETH, -1, "1", "105", "0.0525"))
    ledger.fill(fill("futures", ETH, -1, "0.5", "105", "0.02625"))
    assert ledger.quantity("futures", ETH) == D("-0.5")
    assert_exact(ledger, {("futures", ETH): D(101)})


# ---------------------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------------------


def test_funding_moves_cash_only() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("spot", BTC, 1, "0.01", "20000", "0.2"))
    ledger.fill(fill("futures", BTC, -1, "0.02", "20000", "0.2"))
    prices = {("spot", BTC): D(21000), ("futures", BTC): D(21000)}
    before = ledger.mark(prices)
    ledger.funding(T + 8 * HOUR, BTC, D("0.042"))
    after = ledger.mark(prices)
    assert after.cash == before.cash + D("0.042")
    assert after.equity == before.equity + D("0.042")
    assert after.backing == before.backing + D("0.042")
    assert (after.spot_value, after.futures_upnl) == (before.spot_value, before.futures_upnl)
    assert (after.maintenance, after.gross_notional) == (before.maintenance, before.gross_notional)
    assert ledger.quantity("futures", BTC) == D("-0.02")
    assert ledger.unrealised("futures", BTC, D(21000)) == D(-20)
    ledger.funding(T + 16 * HOUR, BTC, D("-0.0105"))
    assert ledger.cash == before.cash + D("0.0315")
    assert_exact(ledger, prices)


def test_funding_needs_an_open_futures_leg() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("spot", BTC, 1, "0.01", "20000"))
    # A spot leg of the same name does not take funding.
    with pytest.raises(ValueError, match="futures"):
        ledger.funding(T, BTC, D("0.01"))
    ledger.fill(fill("futures", BTC, 1, "0.01", "20000"))
    ledger.fill(fill("futures", BTC, -1, "0.01", "20000"))
    with pytest.raises(ValueError, match="futures"):
        ledger.funding(T, BTC, D("0.01"))
    assert ledger.cash == D(800)


def test_matches_v31_funding_cashflow_sign_convention() -> None:
    price = D("25000.5")
    for side in (1, -1):
        for rate in (D("0.0001"), D("-0.000375")):
            ledger = Ledger(D(10000))
            ledger.fill(fill("futures", BTC, side, "0.3", "25000"))
            quantity = ledger.quantity("futures", BTC)
            with localcontext(CONTEXT):
                amount = -quantity * rate * price
            snapshot = PositionSnapshot(
                BTC,
                "futures_trend",
                "futures",
                quantity,
                D(0),
                D(0),
                price,
                "caller",
                None,
                D(0),
                (),
            )
            assert amount == funding_cashflow(snapshot, rate, price)
            # Longs pay a positive rate and shorts receive it.
            assert (amount < 0) == (side * rate > 0)
            cash = ledger.cash
            ledger.funding(T + 8 * HOUR, BTC, amount)
            assert ledger.cash == cash + amount


# ---------------------------------------------------------------------------------------
# Marks: backing, maintenance, ratio and gross
# ---------------------------------------------------------------------------------------


def test_backing_excludes_spot_and_ratio_is_none_without_futures() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("spot", ETH, 1, "5", "100", "0.5"))
    spot_only = ledger.mark({("spot", ETH): D(120)})
    with localcontext(CONTEXT):
        gross = D(600) / D("1099.5")
    assert spot_only == Mark(
        equity=D("1099.5"),
        cash=D("499.5"),
        spot_value=D(600),
        futures_upnl=D(0),
        backing=D("499.5"),
        maintenance=D(0),
        ratio=None,
        gross_notional=D(600),
        gross=gross,
    )
    ledger.fill(fill("futures", BTC, 1, "1", "200", "0.1"))
    low = ledger.mark({("spot", ETH): D(50), ("futures", BTC): D(210)})
    high = ledger.mark({("spot", ETH): D(150), ("futures", BTC): D(210)})
    assert low.futures_upnl == high.futures_upnl == D(10)
    assert low.backing == high.backing == D("499.4") + D(10)
    assert low.equity != high.equity
    assert low.maintenance == high.maintenance == D("2.1")
    with localcontext(CONTEXT):
        assert low.ratio == D("509.4") / D("2.1")
    assert low.ratio == high.ratio
    # A futures loss lowers the backing; spot does not hold it up.
    falling = ledger.mark({("spot", ETH): D(1000), ("futures", BTC): D(150)})
    assert falling.backing == D("499.4") - D(50)
    assert falling.maintenance == D("1.5")


def test_gross_counts_spot_and_futures_notional() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("spot", ETH, 1, "2", "100"))
    ledger.fill(fill("futures", BTC, -1, "3", "50"))
    mark = ledger.mark({("spot", ETH): D(100), ("futures", BTC): D(50)})
    assert mark.gross_notional == D(350)
    assert mark.equity == D(1000)
    with localcontext(CONTEXT):
        assert mark.gross == D(350) / D(1000)
    up = ledger.mark({("spot", ETH): D(90), ("futures", BTC): D(60)})
    assert up.gross_notional == D(180 + 180)
    assert up.equity == D(1000 - 20 - 30)
    with localcontext(CONTEXT):
        assert up.gross == D(360) / D(950)


def test_gross_is_none_when_equity_is_at_or_below_zero() -> None:
    ledger = Ledger(D(100))
    ledger.fill(fill("futures", BTC, 1, "10", "100"))
    zero = ledger.mark({("futures", BTC): D(90)})
    assert zero.equity == 0
    assert zero.gross is None
    assert zero.gross_notional == D(900)
    below = ledger.mark({("futures", BTC): D(89)})
    assert below.equity == D(-10)
    assert below.gross is None
    with localcontext(CONTEXT):
        assert below.ratio == D(-10) / D("8.9")


def test_mark_needs_a_price_for_every_open_position_and_ignores_extras() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("spot", ETH, 1, "1", "100"))
    with pytest.raises(ValueError, match=ETH):
        ledger.mark({})
    with pytest.raises(ValueError, match=ETH):
        ledger.audit({("futures", ETH): D(100)})
    extra = {("spot", ETH): D(100), ("futures", BTC): D(-1), ("spot", "XRPUSDT"): D(1)}
    assert ledger.mark(extra) == ledger.mark({("spot", ETH): D(100)})
    for bad in (D(0), D(-1), D("NaN"), D("Infinity"), 100, 100.0):
        with pytest.raises(ValueError):
            ledger.mark({("spot", ETH): bad})  # type: ignore[dict-item]
        with pytest.raises(ValueError):
            ledger.unrealised("spot", ETH, bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ledger.mark([(("spot", ETH), D(100))])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------
# Validation, the clock and immutability
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp_ms": -1},
        {"timestamp_ms": 1.0},
        {"timestamp_ms": True},
        {"venue": "margin"},
        {"symbol": "btcusdt"},
        {"symbol": "B"},
        {"symbol": "B" * 31},
        {"side": 0},
        {"side": 2},
        {"side": True},
        {"side": 1.0},
        {"quantity": D(0)},
        {"quantity": D(-1)},
        {"quantity": D("NaN")},
        {"quantity": 1},
        {"price": D(0)},
        {"price": D("-Infinity")},
        {"price": 100.0},
        {"fee": D("-0.01")},
        {"fee": D("sNaN")},
        {"fee": 0},
        {"reason": ""},
        {"reason": None},
    ],
)
def test_a_malformed_fill_is_refused(changes: dict[str, Any]) -> None:
    fields: dict[str, Any] = {
        "timestamp_ms": T,
        "venue": "spot",
        "symbol": BTC,
        "side": 1,
        "quantity": D(1),
        "price": D(100),
        "fee": D(0),
        "reason": "signal",
    }
    fields.update(changes)
    with pytest.raises(ValueError):
        Fill(**fields)


@pytest.mark.parametrize("bad", [D("NaN"), D("Infinity"), 1, 0.5, "1"])
def test_malformed_funding_and_initial_cash_are_refused(bad: Any) -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("futures", BTC, 1, "1", "100"))
    with pytest.raises(ValueError):
        ledger.funding(T, BTC, bad)
    with pytest.raises(ValueError):
        Ledger(bad)
    assert ledger.cash == D(1000)


def test_initial_cash_must_be_positive_and_inputs_must_be_well_formed() -> None:
    for bad in (D(0), D(-1)):
        with pytest.raises(ValueError):
            Ledger(bad)
    ledger = Ledger(D(1000))
    ledger.fill(fill("futures", BTC, 1, "1", "100"))
    with pytest.raises(ValueError):
        ledger.fill("not a fill")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ledger.funding(-1, BTC, D(1))
    with pytest.raises(ValueError):
        ledger.funding(T, "btc", D(1))
    with pytest.raises(ValueError):
        ledger.quantity("margin", BTC)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ledger.quantity("spot", "btc")
    with pytest.raises(ValueError):
        ledger.unrealised("margin", BTC, D(1))  # type: ignore[arg-type]
    assert ledger.cash == D(1000)


def test_timestamps_must_not_go_backwards() -> None:
    ledger = Ledger(D(1000))
    ledger.fill(fill("futures", BTC, 1, "1", "100", at=T + HOUR))
    with pytest.raises(ValueError, match="backwards"):
        ledger.fill(fill("futures", BTC, 1, "1", "100", at=T))
    with pytest.raises(ValueError, match="backwards"):
        ledger.funding(T, BTC, D("-0.01"))
    # Many events share an hour.
    ledger.fill(fill("futures", BTC, 1, "1", "100", at=T + HOUR))
    ledger.funding(T + HOUR, BTC, D("-0.01"))
    # A refused funding call does not move the clock.
    with pytest.raises(ValueError):
        ledger.funding(T + 3 * HOUR, ETH, D("-0.01"))
    ledger.fill(fill("futures", BTC, -1, "1", "100", at=T + HOUR))
    # A booked funding call does.
    ledger.funding(T + 2 * HOUR, BTC, D("-0.01"))
    with pytest.raises(ValueError, match="backwards"):
        ledger.fill(fill("futures", BTC, -1, "1", "100", at=T + HOUR))
    ledger.fill(fill("futures", BTC, -1, "1", "100", at=T + 2 * HOUR))
    assert ledger.cash == D("999.98")
    assert dict(ledger.positions()) == {}


def test_records_are_frozen() -> None:
    ledger = Ledger(D(1000))
    record = fill("spot", BTC, 1, "1", "100")
    ledger.fill(record)
    mark = ledger.mark({("spot", BTC): D(100)})
    audit = ledger.audit({("spot", BTC): D(100)})
    with pytest.raises(FrozenInstanceError):
        record.price = D(1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        mark.equity = D(1)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        audit.wallet_residual = D(1)  # type: ignore[misc]
    with pytest.raises(TypeError):
        audit.quantity_residuals[("spot", BTC)] = D(1)  # type: ignore[index]


# ---------------------------------------------------------------------------------------
# The audit over a long random sequence
# ---------------------------------------------------------------------------------------

# Symbol: (price decimals, start price in those units, quantity decimals, typical quantity).
SCALES = {
    "BTCUSDT": (2, 2_500_000, 3, 200),
    "ETHUSDT": (2, 180_000, 3, 3_000),
    "DOGEUSDT": (5, 8_000, 0, 30_000),
    "1000SHIBUSDT": (6, 9_500, 0, 300_000),
}
FEE = {"spot": D("0.001"), "futures": D("0.0005")}


def test_audit_identities_hold_exactly_over_a_random_fill_sequence() -> None:
    rng = random.Random(20261021)
    ledger = Ledger(D(100000))
    keys: list[tuple[Venue, str]] = [
        (venue, symbol) for symbol in SCALES for venue in ("spot", "futures")
    ]
    units = {key: SCALES[key[1]][1] for key in keys}
    held = {key: D(0) for key in keys}
    kinds: dict[str, int] = {}
    fills = 0
    now = T

    def price(key: tuple[Venue, str]) -> Decimal:
        return D(units[key]).scaleb(-SCALES[key[1]][0])

    def prices() -> dict[tuple[Venue, str], Decimal]:
        return {key: price(key) for key in keys}

    def book(key: tuple[Venue, str], side: int, quantity: Decimal, kind: str) -> None:
        nonlocal fills
        venue, symbol = key
        with localcontext(CONTEXT):
            fee = quantity * price(key) * FEE[venue]
        ledger.fill(Fill(now, venue, symbol, side, quantity, price(key), fee, kind))
        held[key] += side * quantity
        fills += 1
        kinds[kind] = kinds.get(kind, 0) + 1
        check()

    def check() -> None:
        assert_exact(ledger, prices())
        assert dict(ledger.positions()) == {key: q for key, q in sorted(held.items()) if q}
        mark = ledger.mark(prices())
        assert mark.equity == mark.cash + mark.spot_value + mark.futures_upnl
        assert mark.backing == mark.cash + mark.futures_upnl

    def some(symbol: str) -> Decimal:
        places, typical = SCALES[symbol][2], SCALES[symbol][3]
        return D(rng.randint(1, 2 * typical)).scaleb(-places)

    def part(symbol: str, quantity: Decimal) -> Decimal:
        places = SCALES[symbol][2]
        steps = int(quantity.scaleb(places))
        return D(rng.randint(1, steps)).scaleb(-places)

    while fills < 500:
        now += HOUR
        for key in keys:
            step = max(1, units[key] // 40)
            units[key] = max(1, units[key] + rng.randint(-step, step))
        symbol = rng.choice(list(SCALES))
        spot, futures = ("spot", symbol), ("futures", symbol)
        action = rng.choice(["spot", "spot", "futures", "futures", "flip", "funding"])
        if action == "spot":
            if held[spot] and rng.random() < 0.5:
                whole = rng.random() < 0.3
                book(spot, -1, held[spot] if whole else part(symbol, held[spot]), "spot sell")
            else:
                book(spot, 1, some(symbol), "spot buy")
        elif action == "futures":
            position = held[futures]
            if position and rng.random() < 0.5:
                side = -1 if position > 0 else 1
                if rng.random() < 0.3:
                    book(futures, side, abs(position), "futures close")
                else:
                    book(futures, side, part(symbol, abs(position)), "futures reduce")
            else:
                side = (1 if position > 0 else -1) if position else rng.choice((1, -1))
                book(futures, side, some(symbol), "futures open")
        elif action == "flip":
            position = held[futures]
            if position:
                side = -1 if position > 0 else 1
                book(futures, side, abs(position), "flip close")
                book(futures, side, some(symbol), "flip open")
        else:
            open_legs = [key for key in keys if key[0] == "futures" and held[key]]
            if open_legs:
                leg = rng.choice(open_legs)
                rate = D(rng.choice((1, -1)) * rng.randint(1, 4000)).scaleb(-7)
                with localcontext(CONTEXT):
                    amount = -ledger.quantity(*leg) * rate * price(leg)
                ledger.funding(now, leg[1], amount)
                kinds["funding+" if amount > 0 else "funding-"] = (
                    kinds.get("funding+" if amount > 0 else "funding-", 0) + 1
                )
                check()

    for kind in (
        "spot buy",
        "spot sell",
        "futures open",
        "futures reduce",
        "futures close",
        "flip close",
        "flip open",
        "funding+",
        "funding-",
    ):
        assert kinds.get(kind, 0) > 0, kind
    # Closing everything at the mark with no fee turns the marked equity into cash.
    equity = ledger.mark(prices()).equity
    for key, quantity in list(ledger.positions().items()):
        side = -1 if quantity > 0 else 1
        ledger.fill(Fill(now, key[0], key[1], side, abs(quantity), price(key), D(0), "end"))
    assert dict(ledger.positions()) == {}
    assert ledger.cash == equity
    assert_exact(ledger, {})
