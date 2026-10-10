"""Synthetic spot settlement and cash constraints for the V3 benchmark."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.filters import OrderFilters

T = 1609459200000
FILTERS = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


@pytest.mark.parametrize("method", ["fill", "execute"])
def test_zero_market_minimum_allows_settlement_and_keeps_notional_guard(method):
    from dataclasses import replace

    from crypto_grid_bot.trend.spot_account import SpotAccount

    filters = replace(FILTERS, min_quantity=D(0))
    account = SpotAccount()
    getattr(account, method)("BTCUSDT", D(10), D(100), filters, T)
    assert account.holdings["BTCUSDT"] == 10
    getattr(account, method)("BTCUSDT", D(-10), D(100), filters, T + 1)
    assert account.cash == D(9997)
    getattr(account, method)("BTCUSDT", D(1), D(1), filters, T + 2)
    assert account.fills[-1].reason == "minimum_notional"
    assert account.fills[-1].quantity == 0
    assert account.audit().exact


@pytest.mark.parametrize("method", ["fill", "execute"])
def test_negative_market_minimum_is_rejected_without_mutation(method):
    from dataclasses import replace

    from crypto_grid_bot.trend.spot_account import SpotAccount

    account = SpotAccount()
    with pytest.raises(ValueError):
        getattr(account, method)("BTCUSDT", D(10), D(100), replace(FILTERS, min_quantity=D(-1)), T)
    assert account.cash == 10000 and not account.fills and not account.holdings


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


def test_balanced_maximum_quantity_split_preserves_total_and_audit():
    from crypto_grid_bot.trend.spot_account import SpotAccount

    filters = OrderFilters(*map(D, ("1", "5", "1", "5", "1", "5", "1", "1")))
    a = SpotAccount()
    fills = a.execute("BTCUSDT", D(13), D(100), filters, T)
    assert [f.quantity for f in fills] == [D(5), D(4), D(4)]
    assert a.holdings["BTCUSDT"] == 13
    assert a.audit().exact
    with pytest.raises(ValueError, match="unowned"):
        a.execute("BTCUSDT", D(-14), D(100), filters, T + 1)
    assert len(a.fills) == 3


def test_low_ambient_precision_does_not_change_settlement():
    from decimal import localcontext

    from crypto_grid_bot.trend.spot_account import SpotAccount

    expected = SpotAccount()
    expected.fill("BTCUSDT", D(13), D("123.456789"), FILTERS, T)
    with localcontext() as ctx:
        ctx.prec = 3
        actual = SpotAccount()
        actual.fill("BTCUSDT", D(13), D("123.456789"), FILTERS, T)
        assert actual.cash == expected.cash
        assert actual.audit().exact
