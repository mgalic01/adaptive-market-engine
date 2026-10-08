"""Continuous synthetic hours; no historical data or dispatch."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.filters import OrderFilters

T = 1609459200000
H = 3600000
RULES = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def test_runner_carries_last_open_and_counts_masked_held_hours():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    bar = {"BTCUSDT": (D(100), D(99), D(101))}
    r.step(T, bar, {"BTCUSDT": D(".1")}, {})
    r.step(T + H, bar, {}, {})
    result = r.step(T + 2 * H, {}, {}, {})
    assert result.marks[0][1].prices["BTCUSDT"] == 100
    assert r.masked_held_hours == {"BTCUSDT": 1}
    assert r.account.positions["BTCUSDT"].quantity == 10
    assert r.peak > 10000
    assert r.max_drawdown > 0


def test_runner_does_not_skip_hours_or_continue_after_engine_failure():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    r.step(T, {}, {}, {})
    with pytest.raises(ValueError, match="consecutive"):
        r.step(T + 2 * H, {}, {}, {})
    with pytest.raises(ValueError, match="stopped"):
        r.step(T + H, {}, {}, {})


def test_runner_stops_on_corrupt_account_instead_of_classifying_strategy():
    from crypto_grid_bot.trend.runner import AccountingFailure, TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    r.account._fees = D(1)
    with pytest.raises(AccountingFailure):
        r.step(T, {}, {}, {})
    assert r.stopped == "engine_failure"


def test_runner_next_unmasked_open_catches_gap_and_stops():
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=2)
    r.account.fill("BTCUSDT", OrderIntent(D(150), False), D(100), T)
    r.step(T, {"BTCUSDT": (D(100), D(100), D(100))}, {}, {})
    r.step(T + H, {}, {}, {})
    result = r.step(T + 2 * H, {"BTCUSDT": (D(1), D(1), D(1))}, {}, {})
    assert result.reason == "liquidation"
    assert r.stopped == "liquidation"
    with pytest.raises(ValueError, match="stopped"):
        r.step(T + 3 * H, {}, {}, {})
