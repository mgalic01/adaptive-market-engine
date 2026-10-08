"""Synthetic risk checkpoints, independent of historical datasets."""

from decimal import Decimal as D

from crypto_grid_bot.trend.account import FuturesAccount
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orders import OrderIntent

T = 1609459200000
RULES = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def book():
    a = FuturesAccount()
    a.fill("BTCUSDT", OrderIntent(D(150), False), D(100), T)
    return a


def test_leverage_reduction_uses_post_fee_equity_and_one_batch():
    from crypto_grid_bot.trend.execution import leverage_checkpoint

    a = book()
    result = leverage_checkpoint(a, {"BTCUSDT": D(100)}, {"BTCUSDT": RULES}, T, multiple=1)
    assert result.reason is None
    assert a.positions["BTCUSDT"].quantity == 79
    assert len(result.fills) == 1
    assert result.after.gross_leverage < 1


def test_masked_book_cannot_delever():
    from crypto_grid_bot.trend.execution import leverage_checkpoint

    a = book()
    result = leverage_checkpoint(a, {"BTCUSDT": D(100)}, {}, T, multiple=1)
    assert result.reason == "no_tradable_position"
    assert not result.fills


def test_liquidation_precedes_reduction():
    from crypto_grid_bot.trend.execution import leverage_checkpoint

    a = book()
    result = leverage_checkpoint(a, {"BTCUSDT": D(1)}, {"BTCUSDT": RULES}, T, multiple=1)
    assert result.reason == "liquidation"
    assert not result.fills
    assert len(a.fills) == 1


def test_masked_exposure_can_make_closing_all_tradable_insufficient():
    from crypto_grid_bot.trend.execution import leverage_checkpoint

    a = book()
    a.fill("ETHUSDT", OrderIntent(D(10), False), D(100), T)
    result = leverage_checkpoint(
        a, {"BTCUSDT": D(100), "ETHUSDT": D(100)}, {"ETHUSDT": RULES}, T, multiple=1
    )
    assert a.positions["ETHUSDT"].quantity == 0
    assert a.positions["BTCUSDT"].quantity == 150
    assert result.reason == "leverage_not_restored"
