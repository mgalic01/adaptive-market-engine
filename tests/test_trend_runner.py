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
    assert r.daily_samples[0][0] == T + H
    assert r.daily_samples[0][1] == 10000
    assert [state.kind for state in r.equity_path[-4:]] == [
        "open",
        "post_fill",
        "favourable",
        "adverse",
    ]
    assert all(
        left.peak <= right.peak
        for left, right in zip(r.equity_path, r.equity_path[1:], strict=False)
    )


def test_funding_path_preserves_raw_timestamp():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    r.step(T, {}, {}, {T + 30: {"BTCUSDT": D(".01")}})
    state = next(state for state in r.equity_path if state.kind == "funding")
    assert state.timestamp_ms == T + 30


def test_multiple_funding_marks_keep_each_raw_time_and_path_order():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    r.step(T, {}, {}, {T + 50: {"BTCUSDT": D(".02")}, T + 30: {"BTCUSDT": D(".01")}})
    assert [s.timestamp_ms for s in r.equity_path if s.kind == "funding"] == [T + 30, T + 50]
    assert [s.timestamp_ms for s in r.equity_path] == sorted(s.timestamp_ms for s in r.equity_path)


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


def test_runner_does_not_silently_adopt_proposed_rounding_tolerance():
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import AccountingFailure, TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    for quantity, price, reducing in [(1, 1, False), (6, 2, False), (-7, 2, True)]:
        r.account.fill("BTCUSDT", OrderIntent(D(quantity), reducing), D(price), T)
    with pytest.raises(AccountingFailure) as failure:
        r.step(T, {}, {}, {})
    assert failure.value.audit.equity_residual == D("-1e-59")
    assert r.stopped == "engine_failure"
    assert not r.hours


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


def test_terminal_sample_uses_supplied_in_window_closes_and_stops():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    last_hour = 1735686000000  # 2024-12-31 23:00; synthetic empty book.
    r.step(last_hour, {}, {}, {})
    mark = r.finish({})
    assert mark.equity == 10000
    assert r.daily_samples[-1] == (1735689600000, D(10000))
    assert r.equity_path[-1].kind == "terminal"
    assert r.stopped == "completed"
    with pytest.raises(ValueError, match="stopped"):
        r.finish({})


def test_terminal_mark_requires_all_held_close_prices():
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    r.account.fill("BTCUSDT", OrderIntent(D(1), False), D(100), T)
    r.step(T, {"BTCUSDT": (D(100), D(99), D(101))}, {}, {})
    with pytest.raises(ValueError, match="missing"):
        r.finish({})
    assert r.stopped == "engine_failure"
