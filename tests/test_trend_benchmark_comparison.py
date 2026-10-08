"""A5 compares audited base-cost m=1 accounts over identical sample times."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.runner import TrendRunner
from crypto_grid_bot.trend.spot_benchmark import SpotRunner

T, HOUR = 1577836800000, 3600000


def accounts(multiple=1):
    strategy = TrendRunner({}, multiple=multiple)
    hold = SpotRunner({})
    for i in range(48):
        strategy.step(T + i * HOUR, {}, {}, {})
        hold.step(T + i * HOUR, {})
    strategy.finish({})
    hold.finish({})
    return strategy, hold


def test_equal_flat_performance_does_not_pass_strict_a5():
    from crypto_grid_bot.trend.benchmark_comparison import compare_hold

    result = compare_hold(*accounts())
    assert result.strategy_sharpe == result.hold_sharpe == 0
    assert not result.passes_a5
    assert result.return_count == 2


def test_comparison_uses_cost_inclusive_daily_returns():
    from crypto_grid_bot.trend.benchmark_comparison import compare_hold
    from crypto_grid_bot.trend.filters import OrderFilters

    strategy, _ = accounts()
    rules = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    hold = SpotRunner({"BTCUSDT": rules})
    for i in range(48):
        hold.step(
            T + i * HOUR,
            {"BTCUSDT": (D(100), D(100), D(100))},
            {"BTCUSDT": D(".1")} if i == 0 else {},
        )
    hold.finish({"BTCUSDT": D(100)})
    result = compare_hold(strategy, hold)
    assert result.strategy_sharpe == 0
    assert result.hold_sharpe < 0  # one loss from costs, then a flat return
    assert result.passes_a5


def test_mismatched_size_or_sample_times_are_not_a_comparison():
    from crypto_grid_bot.trend.benchmark_comparison import compare_hold

    with pytest.raises(ValueError, match="m=1"):
        compare_hold(*accounts(multiple=2))
    strategy, hold = accounts()
    hold.samples[1] = (hold.samples[1][0] + HOUR, hold.samples[1][1])
    with pytest.raises(ValueError, match="sample times"):
        compare_hold(strategy, hold)


def test_invalid_or_corrupted_spot_account_cannot_receive_a5_verdict():
    from crypto_grid_bot.trend.benchmark_comparison import compare_hold

    strategy, hold = accounts()
    hold.account.cash += 1
    with pytest.raises(ValueError, match="accounting"):
        compare_hold(strategy, hold)
    strategy, hold = accounts()
    hold.stopped = "unavailable_exclusion_close"
    with pytest.raises(ValueError, match="completed"):
        compare_hold(strategy, hold)
