"""Complete V3.1 strategy replay over synthetic inputs (never market data)."""

from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
import pytest

from crypto_grid_bot.combined.account import FundingEvent
from crypto_grid_bot.combined.replay_records import strategy_report
from crypto_grid_bot.combined.strategy_replay import TraceFill, replay_strategy

PIN = "0" * 64
HOUR = fx.HOUR
DAY = fx.DAY


def fills(trace):
    return [event for event in trace.events if isinstance(event, TraceFill)]


def comparable(trace):
    return [(o.timestamp_ms, o.id, o.snapshot.account.equity) for o in trace.observations]


def crash_after(path, start_hour: int, drop: float):
    """``path`` until ``start_hour`` hours into the window, then one bar falls ``drop``."""
    pivot = fx.HISTORY_DAYS * 24 + start_hour

    def shifted(i: int) -> float:
        return path(i) if i <= pivot else path(i) * (1 - drop)

    return shifted


def reverse_after(path, start_hour: int):
    """``path`` until ``start_hour`` hours into the window, then a mirrored decline."""
    pivot = fx.HISTORY_DAYS * 24 + start_hour

    def mirrored(i: int) -> float:
        return path(i) if i <= pivot else path(2 * pivot - i)

    return mirrored


@pytest.mark.parametrize(
    ("arm", "path", "options"),
    [
        ("spot_trend", fx.uptrend, {}),
        ("futures_trend", fx.downtrend, {"futures": True}),
        ("spot_grid", fx.ranging, {"flow": True}),
    ],
)
def test_each_component_produces_a_complete_exactly_reconciled_report(arm, path, options):
    trace = replay_strategy(fx.run(arm, 3), (fx.market("BTCUSDT", path, 3, **options),))
    assert trace.failure is None
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete, report.issues
    assert report.reconciliation_residual == 0
    assert len(report.policy_evidence.boundaries) == 3 * 24 + 1
    assert [b.role for b in report.policy_evidence.boundaries[:: 3 * 24]] == [
        "opening",
        "terminal",
    ]
    assert all(metric.value is not None for metric in report.metrics)


def test_spot_trend_opens_once_at_the_admitted_stop_and_holds_its_winner():
    trace = replay_strategy(fx.run("spot_trend", 5), (fx.market("BTCUSDT", fx.uptrend, 5),))
    booked = fills(trace)
    assert len(booked) == 1 and booked[0].increase
    opening = booked[0].fill
    assert opening.event_id.startswith("opening:")
    decision = trace.decisions[0].result
    # Protection starts from the admitted stop, not one recomputed from the fill.
    assert decision.intent.stop < decision.intent.price < opening.price
    report = strategy_report(trace, adapter_pin=PIN)
    assert [c.status for c in report.contributions] == ["open_marked"]
    assert report.contributions[0].gross_pnl > 0


def test_old_stop_executes_intrabar_and_is_never_executed_again():
    market = fx.market("BTCUSDT", crash_after(fx.uptrend, 12, 0.15), 2)
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None
    exits = [event for event in fills(trace) if not event.increase]
    assert len(exits) == 1
    assert exits[0].exit_reason == "stop" and ":fill:" in exits[0].fill.event_id
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete and report.reconciliation_residual == 0
    assert report.contributions[0].exit_reason == "stop"


@pytest.mark.parametrize("scenario", ["open_low_high_close", "open_high_low_close"])
def test_trailing_stop_exits_a_pullback_the_initial_stop_would_hold(scenario):
    market = fx.market("BTCUSDT", crash_after(fx.uptrend, 20 * 24, 0.09), 21)
    trailing = replay_strategy(fx.run("combined", 21, scenario=scenario), (market,))
    fixed = replay_strategy(
        fx.run("combined_without_discretionary_trailing", 21, scenario=scenario), (market,)
    )
    assert trailing.failure is None and fixed.failure is None
    trailing_exits = [e for e in fills(trailing) if not e.increase]
    assert trailing_exits and all("stop" in (e.exit_reason or "") for e in trailing_exits)
    assert [e for e in fills(fixed) if not e.increase] == []


def test_a_completed_bar_reversal_closes_at_the_next_opening_quote(monkeypatch):
    from crypto_grid_bot.combined import strategy_replay
    from crypto_grid_bot.combined.lifecycle import ManagementDecision

    original = strategy_replay.manage
    reversal_hour = fx.START + 30 * HOUR

    def reversing(assessment, owner, side, **kwargs):
        if assessment.decision_ms == reversal_hour and owner == "spot_trend":
            return ManagementDecision(True, "trend_reversal")
        return original(assessment, owner, side, **kwargs)

    monkeypatch.setattr(strategy_replay, "manage", reversing)
    market = fx.market("BTCUSDT", fx.uptrend, 2)
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None
    exits = [event for event in fills(trace) if not event.increase]
    assert [e.exit_reason for e in exits[:1]] == ["trend_reversal"]
    exit_fill = exits[0].fill
    # Decided on the completed bar at 30h; executed by that hour's boundary frame
    # at the next bar's opening quote, with the held slippage and tick.
    assert exit_fill.event_id.startswith("boundary:") and exit_fill.timestamp_ms == reversal_hour
    opening = next(bar.open for bar in market.spot.hourly if bar.open_ms == reversal_hour)
    assert exit_fill.price <= opening
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0
    assert report.contributions[0].exit_reason == "trend_reversal"


def test_futures_funding_is_paid_by_holdings_surviving_each_settlement():
    market = fx.market("BTCUSDT", fx.downtrend, 3, futures=True)
    market = replace(
        market, funding=fx.funding(fx.START - fx.HISTORY_DAYS * DAY, fx.START + 3 * DAY, ".001")
    )
    trace = replay_strategy(fx.run("futures_trend", 3), (market,))
    assert trace.failure is None
    entry = fills(trace)[0].fill
    payments = [event for event in trace.events if isinstance(event, FundingEvent)]
    end = fx.START + 3 * DAY
    expected = [t for t in range(entry.timestamp_ms + HOUR, end, HOUR) if t % (8 * HOUR) == 0]
    assert [p.timestamp_ms for p in payments] == expected
    futures_open = {bar.open_ms: bar.open for bar in market.futures.hourly}
    for payment in payments:
        # A short receives a positive rate on its full quantity at the hour's open.
        assert payment.amount == entry.quantity * D(".001") * futures_open[payment.timestamp_ms]
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.contributions[0].funding_signed == sum((p.amount for p in payments), D(0))
    assert report.reconciliation_residual == 0


def test_grid_lots_bought_intrabar_never_exit_in_the_same_bar():
    trace = replay_strategy(
        fx.run("spot_grid", 10), (fx.market("BTCUSDT", fx.ranging, 10, flow=True),)
    )
    assert trace.failure is None
    report = strategy_report(trace, adapter_pin=PIN)
    closed = [c for c in report.contributions if c.status == "closed"]
    assert closed and all(c.exit_reason == "grid_target" for c in closed)
    assert all(c.exit_ms > c.entry_ms for c in closed)
    buys = [e.fill for e in fills(trace) if e.increase]
    assert buys and all(fill.lot_id and fill.owner == "spot_grid" for fill in buys)


def test_grid_without_minute_flow_is_unavailable_not_ungated():
    trace = replay_strategy(fx.run("spot_grid", 3), (fx.market("BTCUSDT", fx.ranging, 3),))
    assert trace.failure is None and fills(trace) == []
    reasons = {r for d in trace.decisions for r in d.result.qualification.reasons}
    assert "flow_blocked" in reasons


def test_replay_is_deterministic_and_independent_of_input_order():
    markets = (
        fx.market("BTCUSDT", fx.uptrend, 2, futures=True, flow=True),
        fx.market("ETHUSDT", fx.ranging, 2, futures=True, flow=True),
    )
    first = replay_strategy(fx.run("combined", 2), markets)
    again = replay_strategy(fx.run("combined", 2), markets)
    reordered = replay_strategy(fx.run("combined", 2), markets[::-1])
    assert comparable(first) == comparable(again) == comparable(reordered)
    assert first.events == reordered.events


def test_a_longer_window_never_changes_what_a_shorter_one_observed():
    markets = (fx.market("BTCUSDT", reverse_after(fx.uptrend, 30), 3, futures=True),)
    short = replay_strategy(fx.run("combined", 2), markets)
    long = replay_strategy(fx.run("combined", 3), markets)
    cut = fx.START + 2 * DAY
    prefix = [row for row in comparable(short) if row[0] < cut]
    assert prefix == [row for row in comparable(long) if row[0] < cut]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m, r: (replace(m, spot=replace(m.spot, hourly=m.spot.hourly[:-30])), r),
        lambda m, r: (replace(m, futures=m.futures, funding=m.funding[:3] + m.funding[4:]), r),
        lambda m, r: (replace(m, funding=()), r),
        lambda m, r: (replace(m, futures=None), r),  # funding without futures inputs
        lambda m, r: ((m, m), r),
        lambda m, r: (m, replace(r, arm="unchanged_v3_selector")),
        lambda m, r: (m, replace(r, arm="no_such_arm")),
        lambda m, r: (m, replace(r, end_ms=1_735_689_600_000)),
        lambda m, r: (m, replace(r, start_ms=r.start_ms + 1)),
        lambda m, r: (m, replace(r, source_refs=())),
    ],
)
def test_input_defects_are_refused_before_any_replay(mutate):
    market = fx.market("BTCUSDT", fx.uptrend, 2, futures=True)
    markets, run = mutate(market, fx.run("combined", 2))
    with pytest.raises(ValueError):
        replay_strategy(run, markets if isinstance(markets, tuple) else (markets,))


def test_a_failed_interval_stops_the_run_and_keeps_everything_observed(monkeypatch):
    from crypto_grid_bot.combined import strategy_replay

    original = strategy_replay.replay_held_portfolio
    calls = []

    def failing(*args, **kwargs):
        calls.append(1)
        result = original(*args, **kwargs)
        return replace(result, failure="portfolio_safety_failure") if len(calls) == 5 else result

    monkeypatch.setattr(strategy_replay, "replay_held_portfolio", failing)
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    assert trace.failure == "portfolio_safety_failure"
    assert len(calls) == 5
    assert trace.boundaries[-1].role != "terminal"
    report = strategy_report(trace, adapter_pin=PIN)
    assert not report.complete
    assert report.reconciliation_residual == 0


def test_each_scenario_is_its_own_account():
    market = fx.market("BTCUSDT", crash_after(fx.uptrend, 12, 0.04), 2)
    low_first = replay_strategy(fx.run("spot_trend", 2, scenario="open_low_high_close"), (market,))
    high_first = replay_strategy(fx.run("spot_trend", 2, scenario="open_high_low_close"), (market,))
    assert low_first.failure is None and high_first.failure is None
    for trace in (low_first, high_first):
        report = strategy_report(trace, adapter_pin=PIN)
        assert report.complete and report.policy_evidence.scenario == trace.run.scenario
