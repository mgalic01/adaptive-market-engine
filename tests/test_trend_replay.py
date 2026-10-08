"""Synthetic in-memory replay wiring, with no files or network."""

from decimal import Decimal as D

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.trend.filters import OrderFilters

T = 1577836800000
DAY, HOUR = 86400000, 3600000
FILTER = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def bar(t, price=100):
    p = D(price)
    return Kline(t, p, p, p, p, D(1), p, D(".5"))


def decisions():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    return DailyDecisions(
        {"BTCUSDT": [bar(T + i * DAY, 100 + i * 2 + i % 3) for i in range(65)]},
        {"BTCUSDT": "2020-01"},
    )


def test_replay_wires_daily_fills_raw_funding_and_terminal_in_window_close():
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 65 * DAY
    result = replay_window(
        decisions(),
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start + i * HOUR) for i in range(24)]},
        {start + 8 * HOUR + 47: {"BTCUSDT": D(".001")}},
        start,
        start + DAY,
        {start: "R1"},
    )
    assert result.reason is None
    r = result.runner
    assert r.stopped == "completed"
    assert r.account.fills[0].timestamp_ms == start + HOUR
    assert r.account.funding[0].timestamp_ms == start + 8 * HOUR + 47
    assert r.daily_samples[-1][0] == start + DAY
    assert r.lifecycles.completed[0].censored


def test_two_replays_get_fresh_accounts_and_missing_hours_are_processed():
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 65 * DAY
    book = decisions()
    args = (
        book,
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start), bar(start + 2 * HOUR)]},
        {},
        start,
        start + DAY,
        {start: "R1"},
    )
    a, b = replay_window(*args), replay_window(*args)
    assert a.runner is not b.runner
    assert len(a.runner.hours) == 24
    assert a.runner.account.fills[0].timestamp_ms == start + 2 * HOUR
    assert a.runner.daily_samples == b.runner.daily_samples


def test_unavailable_exclusion_close_returns_invalid_before_creating_account():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 90 * DAY
    book = DailyDecisions(
        {"BTCUSDT": []}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    result = replay_window(
        book,
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start)]},
        {},
        start,
        start + 2 * DAY,
        {start: "R1"},
    )
    assert result.runner is None
    assert result.reason == "unavailable_exclusion_close"
    assert result.close_requirements[0].fill_ms is None


def test_funding_liquidation_stops_replay_without_following_hours():
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 65 * DAY
    result = replay_window(
        decisions(),
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start + i * HOUR) for i in range(24)]},
        {start + 8 * HOUR + 47: {"BTCUSDT": D(100)}},
        start,
        start + DAY,
        {start: "R1"},
    )
    assert result.reason == "liquidation"
    assert len(result.runner.hours) == 9
    assert result.runner.lifecycles.completed[0].exit_reason == "liquidation"


def test_duplicate_execution_hours_are_engine_input_errors():
    import pytest

    from crypto_grid_bot.trend.replay import replay_window

    start = T + 65 * DAY
    with pytest.raises(ValueError, match="unique"):
        replay_window(
            decisions(),
            {"BTCUSDT": FILTER},
            {"BTCUSDT": [bar(start), bar(start)]},
            {},
            start,
            start + DAY,
            {start: "R1"},
        )
