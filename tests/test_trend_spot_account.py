"""Synthetic spot settlement and cash constraints for the V3 benchmark."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.filters import OrderFilters

T = 1609459200000
FILTERS = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def test_round_trip_uses_spot_fee_and_never_borrows():
    from crypto_grid_bot.trend.spot_account import SpotAccount

    a = SpotAccount()
    buy = a.fill("BTCUSDT", D(10), D(100), FILTERS, T)
    assert buy.price == D("100.05")
    assert buy.fee == D("1.0005")
    assert a.cash == D("8998.4995")
    sell = a.fill("BTCUSDT", D(-10), D(100), FILTERS, T + 1)
    assert sell.fee == D(".9995")
    assert a.cash == D(9997)
    assert a.holdings["BTCUSDT"] == 0
    assert a.audit().exact


def test_buy_is_clipped_to_cash_fee_included():
    from crypto_grid_bot.trend.spot_account import SpotAccount

    a = SpotAccount()
    fill = a.fill("BTCUSDT", D(1000), D(100), FILTERS, T)
    assert fill.quantity == 99
    assert fill.reason == "cash_clipped"
    assert a.cash >= 0
    assert a.audit().exact


def test_dust_sell_is_retained_and_marked():
    from crypto_grid_bot.trend.spot_account import SpotAccount

    a = SpotAccount()
    a.fill("BTCUSDT", D(1), D(10), FILTERS, T)
    fill = a.fill("BTCUSDT", D(-1), D(1), FILTERS, T + 1)
    assert fill.quantity == 0 and fill.reason == "minimum_notional"
    assert a.holdings["BTCUSDT"] == 1
    assert a.mark({"BTCUSDT": D(1)}) == a.cash + 1
    assert a.audit().exact


def test_double_costs_change_fees_and_slippage():
    from crypto_grid_bot.trend.spot_account import SpotAccount

    a = SpotAccount(cost_multiple=2)
    a.fill("BTCUSDT", D(10), D(100), FILTERS, T)
    a.fill("BTCUSDT", D(-10), D(100), FILTERS, T + 1)
    assert a.cash == D(9994)
    assert a.audit().exact


def test_rejected_orders_preserve_state_and_audit_detects_corruption():
    from crypto_grid_bot.trend.spot_account import SpotAccount

    a = SpotAccount()
    with pytest.raises(ValueError, match="unowned"):
        a.fill("BTCUSDT", D(-1), D(100), FILTERS, T)
    with pytest.raises(ValueError):
        a.fill("BTCUSDT", D("NaN"), D(100), FILTERS, T)
    assert a.cash == 10000 and not a.fills and not a.holdings
    a.fill("BTCUSDT", D(1), D(100), FILTERS, T)
    a.cash += 1
    assert not a.audit().exact
    a.cash -= 1
    a.holdings["BTCUSDT"] += 1
    assert not a.audit().exact
