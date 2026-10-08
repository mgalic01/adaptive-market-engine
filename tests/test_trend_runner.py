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


def test_runner_stops_and_retains_equity_residual_above_approved_bound(monkeypatch):
    from crypto_grid_bot.trend.account import AccountingAudit
    from crypto_grid_bot.trend.runner import AccountingFailure, TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    audit = AccountingAudit(D(0), {}, D("-1.0000000000000000001e-18"))
    monkeypatch.setattr(r.account, "audit", lambda prices: audit)
    with pytest.raises(AccountingFailure) as failure:
        r.step(T, {}, {}, {})
    assert failure.value.audit == audit
    assert r.audits == [audit]
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


def test_runner_double_cost_mode_changes_fill_price_and_fee():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1, cost_multiple=2)
    bar = {"BTCUSDT": (D(100), D(100), D(100))}
    r.step(T, bar, {"BTCUSDT": D(".1")}, {})
    r.step(T + H, bar, {}, {})
    assert r.account.fills[0].price == D("100.1")
    assert r.account.fills[0].fee == D("1.001")


def test_foreign_funding_symbol_fails_before_account_mutation():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    with pytest.raises(ValueError, match="funding symbol"):
        r.step(T, {}, {}, {T: {"BTXUSDT": D(".01")}})
    assert r.account._clock == -1
    assert not r.account.funding


def test_runner_tracks_funding_and_censors_open_trade_at_finish():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    bar = {"BTCUSDT": (D(100), D(99), D(101))}
    r.step(T, bar, {"BTCUSDT": D(".1")}, {})
    r.step(T + H, bar, {}, {T + H: {"BTCUSDT": D(".01")}})
    r.finish({"BTCUSDT": D(100)})
    life = r.lifecycles.completed[0]
    assert life.funding_paid == 10
    assert life.censored
    assert life.favourable == D("9.5")
    assert life.adverse == D("-10.5")
    assert len(life.fills) == 1


def test_deferred_close_retains_original_decision_reason():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    bar = {"BTCUSDT": (D(100), D(100), D(100))}
    r.step(T, bar, {"BTCUSDT": D(".1")}, {})
    for hour in range(1, 24):
        r.step(T + hour * H, bar, {}, {})
    r.step(
        T + 24 * H, bar, {"BTCUSDT": D(0)}, {}, exit_reasons={"BTCUSDT": frozenset({"signal_zero"})}
    )
    r.step(T + 25 * H, {}, {}, {})
    assert not r.lifecycles.completed
    r.step(T + 26 * H, bar, {}, {})
    assert r.lifecycles.completed[0].exit_reason == "signal_zero"
    assert r.lifecycles.completed[0].end_ms == T + 26 * H


def test_runner_flip_closes_old_trade_and_starts_new_trade():
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    bar = {"BTCUSDT": (D(100), D(100), D(100))}
    r.step(T, bar, {"BTCUSDT": D(".1")}, {})
    for hour in range(1, 24):
        r.step(T + hour * H, bar, {}, {})
    r.step(T + 24 * H, bar, {"BTCUSDT": D("-.1")}, {})
    r.step(T + 25 * H, bar, {}, {})
    assert r.lifecycles.completed[0].exit_reason == "flip"
    assert r.lifecycles.active["BTCUSDT"].side == "short"


@pytest.mark.parametrize(
    "tradable_eth,reason", [(False, "no_tradable_position"), (True, "leverage_not_restored")]
)
def test_terminal_leverage_failure_censors_remaining_positions(tradable_eth, reason):
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES, "ETHUSDT": RULES}, multiple=1)
    r.account.fill("BTCUSDT", OrderIntent(D(80), False), D(100), T)
    bars = {"BTCUSDT": (D(100), D(100), D(100))}
    if tradable_eth:
        r.account.fill("ETHUSDT", OrderIntent(D(10), False), D(100), T)
        bars["ETHUSDT"] = (D(100), D(100), D(100))
    r.step(T, bars, {}, {})
    stamp = T + H + 30
    result = r.step(
        T + H,
        {"ETHUSDT": bars["ETHUSDT"]} if tradable_eth else {},
        {},
        {stamp: {"BTCUSDT": D(".4")}},
    )
    assert result.reason == reason
    assert not r.lifecycles.active
    btc = next(life for life in r.lifecycles.completed if life.symbol == "BTCUSDT")
    assert btc.censored
    assert btc.exit_reason == reason
    assert btc.end_ms == stamp
    assert btc.unrealized == D(-4)
    assert btc.funding_paid == D(3200)
    assert btc.duration_ms == H + 30


def test_runner_consumes_event_suffix_without_reading_full_journal(monkeypatch):
    from crypto_grid_bot.trend.account import FuturesAccount
    from crypto_grid_bot.trend.runner import TrendRunner

    def forbidden_full_snapshot(self):
        raise AssertionError("runner must not copy the historical journal")

    monkeypatch.setattr(FuturesAccount, "events", property(forbidden_full_snapshot))
    r = TrendRunner({"BTCUSDT": RULES}, multiple=1)
    bar = {"BTCUSDT": (D(100), D(100), D(100))}
    r.step(T, bar, {"BTCUSDT": D(".1")}, {})
    r.step(T + H, bar, {}, {})
    r.step(T + 2 * H, bar, {}, {T + 2 * H: {"BTCUSDT": D(".01")}})
    assert r.lifecycles.event_count == 2
    assert r.lifecycles.active["BTCUSDT"].funding_paid == 10


def test_runner_accepts_and_retains_approved_equity_rounding_residual():
    from crypto_grid_bot.trend.orders import OrderIntent
    from crypto_grid_bot.trend.runner import TrendRunner

    r = TrendRunner({"BTCUSDT": RULES})
    for quantity, price in ((1, 1), (6, 2), (-7, 2)):
        r.account.fill("BTCUSDT", OrderIntent(D(quantity), quantity < 0), D(price), T)
    r.lifecycles.consume(r.account.events, {2: {"signal_zero"}})
    r.step(T, {}, {}, {})
    r.finish({})
    assert r.stopped == "completed"
    assert len(r.audits) == 3
    assert all(a.accepted and not a.exact for a in r.audits)
    assert all(a.equity_residual == D("-1e-59") for a in r.audits)
