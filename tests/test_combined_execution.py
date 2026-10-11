"""Offline venue/fill arithmetic; timing uncertainty is explicit."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D
from decimal import localcontext

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.account import PositionSnapshot
from crypto_grid_bot.combined.execution import (
    LimitOrder,
    MarketOrder,
    VenueRules,
    adverse_price,
    executable_reduction,
    floor_quantity,
    funding_cashflow,
    futures_margin,
    simulate_order,
)


def rules(**changes):
    return replace(VenueRules(D(".1"), D(".1"), D(10), D(5), D(".01")), **changes)


def bar(open="100", high="110", low="90", close="105", time=3600000):
    return Kline(time, D(open), D(high), D(low), D(close), D(1), D(100), D(".5"))


def position(qty="1", venue="futures", symbol="BTCUSDT", mark="100"):
    quantity = D(qty)
    cost = abs(quantity) * D(100)
    return PositionSnapshot(
        symbol,
        "futures_trend" if venue == "futures" else "spot_trend",
        venue,
        quantity,
        cost,
        cost / 2 if venue == "futures" else D(0),
        D(mark),
        "caller",
        None,
        quantity * (D(mark) - 100),
        (),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("step", D(0)),
        ("tick", D(0)),
        ("min_qty", D(-1)),
        ("max_qty", D(".01")),
        ("min_notional", D("NaN")),
    ],
)
def test_invalid_rules_rejected(field, value):
    with pytest.raises(ValueError):
        rules(**{field: value})


def test_rules_are_frozen_and_rounding_never_adds_quantity_or_improves_price():
    venue = rules()
    with pytest.raises(FrozenInstanceError):
        venue.step = D(1)
    assert floor_quantity(D("1.29"), venue) == D("1.2")
    assert adverse_price(D("100.001"), 1, venue) == D("100.01")
    assert adverse_price(D("100.001"), -1, venue) == D("100.00")


def test_reduction_caps_venue_maximum_without_marking_remaining_position_dust():
    result = executable_reduction(D("20.09"), D(100), rules())
    assert result.quantity == D(10) and not result.dust


@pytest.mark.parametrize("qty,price", [(".09", "100"), (".1", "40")])
def test_only_valid_fresh_quote_can_establish_dust(qty, price):
    result = executable_reduction(D(qty), D(price), rules())
    assert result.quantity == 0 and result.dust
    for missing in (None, D("NaN"), D(0)):
        with pytest.raises(ValueError):
            executable_reduction(D(qty), missing, rules())


def test_flat_is_not_dust():
    result = executable_reduction(D(0), D(100), rules())
    assert result.quantity == 0 and not result.dust and result.reason == "flat"


@pytest.mark.parametrize("side,expected", [(1, "101.00"), (-1, "99.00")])
def test_market_at_next_open_with_adverse_slippage(side, expected):
    order = MarketOrder(3600000, side, D(1))
    fill = simulate_order(order, bar(), rules(), slippage=D(".01"))
    assert fill.price == D(expected) and fill.quantity == 1 and fill.remaining_quantity == 0
    assert fill.at_open and fill.bar_open_ms == 3600000
    assert simulate_order(replace(order, decision_ms=3600001), bar(), rules()) is None
    assert simulate_order(order, None, rules()) is None


@pytest.mark.parametrize(
    "side,limit,ohlc,at_open",
    [
        (1, "95", bar("94", "100", "90", "96"), True),
        (1, "95", bar(), False),
        (-1, "105", bar("106", "110", "100", "104"), True),
        (-1, "105", bar(), False),
    ],
)
def test_limit_fills_at_limit_without_gap_credit_or_limit_violating_slippage(
    side, limit, ohlc, at_open
):
    order = LimitOrder(0, side, D(1), D(limit))
    fill = simulate_order(order, ohlc, rules(), slippage=D(".1"))
    assert fill.price == D(limit) and fill.at_open is at_open
    assert fill.bar_open_ms == ohlc.open_ms


def test_untouched_limit_has_no_fill():
    assert simulate_order(LimitOrder(0, 1, D(1), D(89)), bar(), rules()) is None
    assert simulate_order(LimitOrder(0, -1, D(1), D(111)), bar(), rules()) is None


def test_partial_fill_cap_preserves_remainder_and_does_not_reapply_submission_minimum():
    venue = rules(min_notional=D(50))
    order = MarketOrder(0, 1, D(1))
    fill = simulate_order(order, bar(), venue, max_quantity_available=D(".29"))
    assert fill.quantity == D(".2") and fill.remaining_quantity == D(".8")
    assert fill.quantity * fill.price < venue.min_notional
    assert simulate_order(order, bar(), venue, max_quantity_available=D(0)) is None
    assert simulate_order(order, bar(), venue, max_quantity_available=D(".09")) is None


@pytest.mark.parametrize(
    "order",
    [MarketOrder(0, 1, D(".11")), MarketOrder(0, 1, D(11)), LimitOrder(0, 1, D(1), D("95.001"))],
)
def test_off_step_oversized_or_off_tick_scheduled_orders_rejected(order):
    with pytest.raises(ValueError):
        simulate_order(order, bar(), rules())


def test_below_submission_minimum_never_fills():
    assert simulate_order(MarketOrder(0, 1, D(".1")), bar(), rules(min_notional=D(50))) is None


@pytest.mark.parametrize(
    "qty,rate,amount",
    [("2", ".001", "-.2"), ("-2", ".001", ".2"), ("2", "-.001", ".2"), ("-2", "-.001", "-.2")],
)
def test_funding_uses_signed_pre_event_holdings_and_wallet_cashflow_sign(qty, rate, amount):
    assert funding_cashflow(position(qty), D(rate), D(100)) == D(amount)
    with pytest.raises(ValueError):
        funding_cashflow(position(qty="1", venue="spot"), D(rate), D(100))


def test_margin_uses_shared_futures_wallet_and_pinned_one_percent_maintenance():
    positions = (
        position("1", mark="90"),
        position("-2", symbol="ETHUSDT", mark="90"),
        position("100", venue="spot", symbol="SOLUSDT"),
    )
    margin = futures_margin(D(20), positions)
    # cash20 + collateral50+100 + PnL(-10+20); spot10000 excluded.
    assert margin.backing == D(180) and margin.maintenance == D("2.7")
    assert margin.ratio > 66
    distressed = futures_margin(D(-160), positions)
    assert distressed.backing == 0 and distressed.ratio == 0


def test_empty_futures_book_has_no_margin_ratio_or_spot_collateral():
    result = futures_margin(D(20), (position("100", venue="spot"),))
    assert result.backing == 20 and result.maintenance == 0 and result.ratio is None


@pytest.mark.parametrize("cash,ratio", [("-149.2", "4"), ("-151.9", "3"), ("-157.3", "1")])
def test_shared_margin_threshold_boundaries_are_exact(cash, ratio):
    result = futures_margin(
        D(cash), (position("1", mark="90"), position("-2", symbol="ETHUSDT", mark="90"))
    )
    assert result.ratio == D(ratio)
    assert result.backing == D(ratio) * result.maintenance


@pytest.mark.parametrize(
    "decision,side,quantity",
    [(-1, 1, D(1)), (True, 1, D(1)), (0, True, D(1)), (0, 0, D(1)), (0, 1, D("NaN")), (0, 1, D(0))],
)
def test_invalid_order_contracts_never_schedule(decision, side, quantity):
    with pytest.raises(ValueError):
        MarketOrder(decision, side, quantity)


def test_invalid_bar_and_liquidity_cannot_create_a_fill():
    order = MarketOrder(0, 1, D(1))
    with pytest.raises(ValueError):
        simulate_order(order, replace(bar(), low=D("NaN")), rules())
    with pytest.raises(ValueError):
        simulate_order(order, bar(), rules(), max_quantity_available=D(-1))


def test_low_decimal_precision_does_not_round_funding_or_quantity():
    p = position(".123456789123456789")
    with localcontext() as context:
        context.prec = 8
        assert funding_cashflow(p, D(".0001"), D(100)) == D("-.00123456789123456789")
        assert floor_quantity(D("1.234567891234567891"), rules(step=D(".000000000000000001"))) == D(
            "1.234567891234567891"
        )
