"""Synthetic in-memory replay wiring, with no files or network."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.trend.filters import OrderFilters

T = 1577836800000
DAY, HOUR = 86400000, 3600000
FILTER = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def test_execution_error_exposes_partial_runner_without_terminal_mark(monkeypatch):
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window
    from crypto_grid_bot.trend.runner import TrendRunner

    original = TrendRunner.step

    def broken(self, stamp, *args, **kwargs):
        if stamp == T + HOUR:
            raise ArithmeticError("synthetic account failure")
        return original(self, stamp, *args, **kwargs)

    monkeypatch.setattr(TrendRunner, "step", broken)
    with pytest.raises(Exception, match="synthetic account failure") as caught:
        replay_window(DailyDecisions({}, {}), {}, {}, {}, T, T + DAY, {T: None})
    partial = getattr(caught.value, "partial_result", None)
    assert partial is not None
    assert len(partial.runner.hours) == 1
    assert partial.runner.stopped == "engine_failure"
    assert all(state.kind != "terminal" for state in partial.runner.equity_path)
    assert isinstance(caught.value.__cause__, ArithmeticError)


@pytest.mark.parametrize("knobs", [{"multiple": 4}, {"cost_multiple": 3}])
def test_invalid_configuration_precedes_unavailable_close(knobs):
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 90 * DAY
    book = DailyDecisions(
        {"BTCUSDT": []}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    with pytest.raises(ValueError, match="multiple"):
        replay_window(
            book,
            {"BTCUSDT": FILTER},
            {"BTCUSDT": []},
            {},
            start,
            start + 2 * DAY,
            {start: "R1"},
            **knobs,
        )


def bar(t, price=100):
    p = D(price)
    return Kline(t, p, p, p, p, D(1), p, D(".5"))


def decisions():
    from crypto_grid_bot.trend.decisions import DailyDecisions

    return DailyDecisions(
        {"BTCUSDT": [bar(T + i * DAY, 100 + i * 2 + i % 3) for i in range(65)]},
        {"BTCUSDT": "2020-01"},
    )


@pytest.mark.parametrize("end_delta", [DAY + 1, DAY + HOUR])
def test_non_midnight_end_is_rejected_by_preflight(end_delta):
    from crypto_grid_bot.trend.replay import replay_window

    with pytest.raises(ValueError, match="exclusive run end"):
        replay_window(
            decisions(), {"BTCUSDT": FILTER}, {"BTCUSDT": []}, {}, T, T + end_delta, {T: "R1"}
        )


def test_off_hour_inventory_is_rejected_by_preflight():
    from crypto_grid_bot.trend.replay import replay_window

    with pytest.raises(ValueError, match="inventory timestamp"):
        replay_window(
            decisions(), {"BTCUSDT": FILTER}, {"BTCUSDT": [bar(T + 1)]}, {}, T, T + DAY, {T: "R1"}
        )


def test_pick_change_closes_position_in_same_account_with_masked_final_hour():
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 65 * DAY
    result = replay_window(
        decisions(),
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start + i * HOUR) for i in range(47)]},
        {},
        start,
        start + 2 * DAY,
        {start: "R1", start + DAY: None},
    )
    assert result.reason is None
    r = result.runner
    assert len(r.hours) == 48
    assert len(r.lifecycles.completed) == 1
    assert r.lifecycles.completed[0].exit_reason == "pick_change"
    assert not r.lifecycles.completed[0].censored
    assert r.account.fills[-1].timestamp_ms == start + DAY + HOUR
    assert r.account.wallet < r.account.initial  # Both fills' costs survive the pick change.


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


def test_unavailable_close_does_not_invalidate_flat_rule():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 89 * DAY
    book = DailyDecisions(
        {"BTCUSDT": []}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    result = replay_window(
        book,
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start)]},
        {},
        start,
        start + 3 * DAY,
        {start: "R1"},
    )
    assert result.runner.stopped == "completed"
    assert result.reason is None
    assert result.close_requirements[0].fill_ms is None


def test_missing_mandatory_fill_stops_only_a_held_position_with_audits():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 89 * DAY
    book = DailyDecisions(
        {"BTCUSDT": [bar(T + i * DAY, 100 + i * 2 + i % 3) for i in range(90)]},
        {"BTCUSDT": "2020-01"},
        {"BTCUSDT": frozenset({"2020-04"})},
    )
    result = replay_window(
        book,
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start + i * HOUR) for i in range(24)]},
        {},
        start,
        start + 3 * DAY,
        {start: "R1"},
    )
    assert result.reason == "unavailable_exclusion_close"
    r = result.runner
    assert r.stopped == result.reason
    assert len(r.hours) == 24
    assert r.account.positions["BTCUSDT"].quantity > 0
    assert not r.lifecycles.active
    assert r.lifecycles.completed[0].exit_reason == result.reason
    assert r.lifecycles.completed[0].censored
    assert all(a.accepted for a in r.audits)


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


def test_pre_portfolio_exclusion_does_not_invalidate_fresh_window():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 90 * DAY
    book = DailyDecisions(
        {"BTCUSDT": []}, {"BTCUSDT": "2020-05"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    result = replay_window(
        book, {"BTCUSDT": FILTER}, {"BTCUSDT": []}, {}, start, start + 2 * DAY, {start: "R1"}
    )
    assert result.reason is None
    assert result.runner.account.fills == ()
    assert result.close_requirements == ()


def test_invalid_funding_is_not_hidden_by_unavailable_close():
    import pytest

    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 90 * DAY
    book = DailyDecisions(
        {"BTCUSDT": []}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    with pytest.raises(ValueError, match="funding"):
        replay_window(
            book,
            {"BTCUSDT": FILTER},
            {"BTCUSDT": []},
            {start: {"BTCUSDT": D("NaN")}},
            start,
            start + 2 * DAY,
            {start: "R1"},
        )


def test_held_position_closes_before_excluded_month_and_its_funding():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 89 * DAY  # March 30; March 31 is the mandatory decision day.
    book = DailyDecisions(
        {"BTCUSDT": [bar(T + i * DAY, 100 + i * 2 + i % 3) for i in range(92)]},
        {"BTCUSDT": "2020-01"},
        {"BTCUSDT": frozenset({"2020-04"})},
    )
    result = replay_window(
        book,
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start + i * HOUR) for i in range(72)]},
        {start + 2 * DAY: {"BTCUSDT": D(100)}},
        start,
        start + 3 * DAY,
        {start: "R1"},
    )
    assert result.reason is None
    r = result.runner
    assert len(r.account.fills) == 2
    assert r.account.fills[-1].timestamp_ms == start + DAY + HOUR
    assert r.lifecycles.completed[0].exit_reason == "excluded_month"
    assert r.account.funding == ()
    assert all(p.quantity == 0 for p in r.account.positions.values())


def test_exclusion_after_run_does_not_close_or_charge_terminal_trade():
    from crypto_grid_bot.trend.decisions import DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 89 * DAY
    rows = [bar(T + i * DAY, 100 + i * 2 + i % 3) for i in range(92)]
    common = (
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start + i * HOUR) for i in range(48)]},
        {},
        start,
        start + 2 * DAY,
        {start: "R1"},
    )
    plain = replay_window(DailyDecisions({"BTCUSDT": rows}, {"BTCUSDT": "2020-01"}), *common)
    excluded = replay_window(
        DailyDecisions(
            {"BTCUSDT": rows}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
        ),
        *common,
    )
    assert excluded.reason is None
    assert excluded.close_requirements == ()
    assert excluded.runner.account.fills == plain.runner.account.fills
    assert excluded.runner.daily_samples == plain.runner.daily_samples
    assert excluded.runner.lifecycles.completed[0].censored


def test_terminal_mark_uses_last_unmasked_close_without_future_bar():
    from crypto_grid_bot.trend.replay import replay_window

    start = T + 65 * DAY
    last = Kline(start + 5 * HOUR, D(100), D(110), D(100), D(110), D(1), D(110), D(".5"))
    result = replay_window(
        decisions(),
        {"BTCUSDT": FILTER},
        {"BTCUSDT": [bar(start), bar(start + HOUR), last, bar(start + DAY, 999)]},
        {},
        start,
        start + DAY,
        {start: "R1"},
    )
    assert result.reason is None
    r = result.runner
    trade = r.lifecycles.completed[0]
    position = r.account.positions["BTCUSDT"]
    assert trade.censored
    assert trade.unrealized == position.quantity * (D(110) - position.average_entry)
    assert trade.end_ms == start + DAY


def test_adapter_stops_and_preserves_terminal_leverage_failure(monkeypatch):
    from crypto_grid_bot.trend.decisions import DailyDecision, DailyDecisions
    from crypto_grid_bot.trend.replay import replay_window

    # Scripted targets isolate adapter event forwarding from the signal/sizing tests.
    book = DailyDecisions(
        {s: [] for s in ("BTCUSDT", "ETHUSDT")}, {s: "2020-01" for s in ("BTCUSDT", "ETHUSDT")}
    )
    monkeypatch.setattr(
        book,
        "at",
        lambda *a, **k: DailyDecision({"BTCUSDT": D(".7"), "ETHUSDT": D(".1")}, {}, {}, None),
    )
    stamp = T + 2 * HOUR + 30
    result = replay_window(
        book,
        {s: FILTER for s in ("BTCUSDT", "ETHUSDT")},
        {"BTCUSDT": [bar(T), bar(T + HOUR)], "ETHUSDT": [bar(T + i * HOUR) for i in range(24)]},
        {stamp: {"BTCUSDT": D(".9")}},
        T,
        T + DAY,
        {T: "R1"},
        multiple=1,
    )
    assert result.reason == "leverage_not_restored"
    assert len(result.runner.hours) == 3
    assert not result.runner.lifecycles.active
    btc = next(t for t in result.runner.lifecycles.completed if t.symbol == "BTCUSDT")
    assert btc.censored and btc.exit_reason == result.reason
    assert btc.end_ms == stamp
