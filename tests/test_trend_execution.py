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


def test_hour_fills_before_same_time_funding_and_preserves_open_sample():
    from crypto_grid_bot.trend.execution import execute_hour

    a = FuturesAccount()
    result = execute_hour(
        a,
        T,
        {"BTCUSDT": D(100)},
        {"BTCUSDT": (D(99), D(101))},
        {"BTCUSDT": RULES},
        {"BTCUSDT": D(".1")},
        {T: {"BTCUSDT": D(".01")}},
        multiple=1,
    )
    assert result.marks[0][1].equity == 10000
    assert a.funding[0].payments[0].quantity == 10
    assert a.funding[0].payments[0].payment == 10
    assert result.reason is None


def test_hour_gap_liquidation_prevents_daily_fills_and_funding():
    from crypto_grid_bot.trend.execution import execute_hour

    a = book()
    result = execute_hour(
        a,
        T + 3600000,
        {"BTCUSDT": D(1)},
        {"BTCUSDT": (D(1), D(1))},
        {"BTCUSDT": RULES},
        {"BTCUSDT": D(0)},
        {T + 3600000: {"BTCUSDT": D(".01")}},
        multiple=1,
    )
    assert result.reason == "liquidation"
    assert len(a.fills) == 1
    assert not a.funding


def test_hour_adverse_extremes_can_liquidate_without_a_close_fill():
    from crypto_grid_bot.trend.execution import execute_hour

    a = FuturesAccount()
    result = execute_hour(
        a,
        T,
        {"BTCUSDT": D(100)},
        {"BTCUSDT": (D(1), D(101))},
        {"BTCUSDT": RULES},
        {"BTCUSDT": D("1.5")},
        {},
        multiple=2,
    )
    assert result.reason == "liquidation"
    assert len(a.fills) == 1
    assert result.marks[-1][1].prices["BTCUSDT"] == 1


def test_daily_batch_closes_all_coins_before_alphabetical_openings():
    from crypto_grid_bot.trend.execution import execute_hour

    a = FuturesAccount()
    a.fill("BTCUSDT", OrderIntent(D(10), False), D(100), T)
    a.fill("ETHUSDT", OrderIntent(D(-10), False), D(100), T)
    prices = {"BTCUSDT": D(100), "ETHUSDT": D(100)}
    before = a.mark(prices)
    result = execute_hour(
        a,
        T + 3600000,
        prices,
        {s: (D(100), D(100)) for s in prices},
        {s: RULES for s in prices},
        {"ETHUSDT": D(".2"), "BTCUSDT": D("-.2")},
        {},
        multiple=1,
    )
    assert [(f.symbol, f.reduce_only) for f in a.fills[2:]] == [
        ("BTCUSDT", True),
        ("ETHUSDT", True),
        ("BTCUSDT", False),
        ("ETHUSDT", False),
    ]
    assert result.marks[0][1] == before
    assert [p.target_quantity for _, p in result.plans] == [D(-19), D(19)]


def test_funding_times_are_sorted_and_each_has_its_own_check():
    from crypto_grid_bot.trend.execution import execute_hour

    a = FuturesAccount()
    result = execute_hour(
        a,
        T,
        {"BTCUSDT": D(100)},
        {"BTCUSDT": (D(100), D(100))},
        {"BTCUSDT": RULES},
        {"BTCUSDT": D(".1")},
        {T + 100: {"BTCUSDT": D(".001")}, T: {"BTCUSDT": D("-.001")}},
        multiple=1,
    )
    assert [event.timestamp_ms for event in a.funding] == [T, T + 100]
    assert len(result.checkpoints) == 3
    assert [label for label, _ in result.marks] == [
        "open",
        "post_fill",
        "funding",
        "funding",
        "adverse",
    ]
