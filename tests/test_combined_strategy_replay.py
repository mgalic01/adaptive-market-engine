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
    market = fx.market("BTCUSDT", crash_after(fx.uptrend, 20 * 24, 0.09), 21, futures=True)
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
    assert first.failure is None and again.failure is None and reordered.failure is None
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
        # A settlement missing inside the window is never assumed to be zero.
        lambda m, r: (
            replace(m, funding=tuple(f for f in m.funding if f.calc_time_ms != fx.START + DAY)),
            r,
        ),
        # A futures-enabled arm judges its whole universe: no silent spot-only symbol.
        lambda m, r: (replace(m, futures=None, funding=()), r),
        # Windows are whole UTC days, as the daily report samples require.
        lambda m, r: (m, replace(r, start_ms=r.start_ms + HOUR)),
        lambda m, r: (replace(m, funding=()), r),
        lambda m, r: (replace(m, futures=None), r),  # funding without futures inputs
        lambda m, r: ((m, m), r),
        lambda m, r: (m, replace(r, arm="unchanged_v3_selector")),
        lambda m, r: (m, replace(r, arm="no_such_arm")),
        lambda m, r: (m, replace(r, end_ms=1_735_689_600_000 + 86_400_000)),
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


RESERVED = 1_735_689_600_000


def reserved_market(path, days: int, **options):
    """A synthetic market whose window ends exactly at the reserved boundary.

    No bar, funding record or minute at or after the boundary is supplied, so any
    attempt to read a 2025 price fails loudly instead of passing silently.
    """
    start = RESERVED - (fx.HISTORY_DAYS + days) * DAY
    hours = (fx.HISTORY_DAYS + days) * 24
    spot = fx.hourly(path, hours, start=start)
    futures = fx.hourly(path, hours, start=start) if options.get("futures") else None
    return fx.SymbolMarket(
        "BTCUSDT",
        fx.VenueMarket(spot, fx.RULES, fx.COSTS),
        fx.daily(spot),
        fx.VenueMarket(futures, fx.RULES, fx.COSTS) if futures else None,
        tuple(r for r in fx.funding(start, RESERVED) if r.calc_time_ms < RESERVED)
        if futures
        else (),
        tuple(m for m in fx.minutes(start, RESERVED) if m.open_ms < RESERVED)
        if options.get("flow")
        else (),
    )


@pytest.mark.parametrize(
    ("arm", "path", "options"),
    [
        ("spot_trend", fx.uptrend, {}),
        ("futures_trend", fx.downtrend, {"futures": True}),
        ("combined", fx.ranging, {"futures": True, "flow": True}),
    ],
)
def test_a_window_ending_at_the_reserved_boundary_marks_the_last_close_only(arm, path, options):
    market = reserved_market(path, 3, **options)
    run = replace(fx.run(arm, 3), start_ms=RESERVED - 3 * DAY, end_ms=RESERVED)
    trace = replay_strategy(run, (market,))
    assert trace.failure is None
    last_bar = market.spot.hourly[-1]
    assert last_bar.open_ms == RESERVED - HOUR
    terminal = [o for o in trace.observations if o.kind == "terminal"]
    assert terminal and all(o.timestamp_ms == RESERVED for o in terminal)
    # No frame, funding, management or entry at the boundary itself.
    assert not [o for o in trace.observations if o.kind == "frame" and o.timestamp_ms >= RESERVED]
    assert all(e.timestamp_ms < RESERVED for e in trace.events if isinstance(e, FundingEvent))
    assert all(d.assessment.decision_ms < RESERVED for d in trace.decisions)
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete, report.issues
    assert report.policy_evidence.boundaries[-1].timestamp_ms == RESERVED
    assert report.policy_evidence.boundaries[-1].role == "terminal"


def test_any_input_at_or_after_the_reserved_boundary_is_refused():
    market = reserved_market(fx.uptrend, 3)
    extra = replace(market.spot.hourly[-1], open_ms=RESERVED)
    leaked = replace(market, spot=replace(market.spot, hourly=(*market.spot.hourly, extra)))
    run = replace(fx.run("spot_trend", 3), start_ms=RESERVED - 3 * DAY, end_ms=RESERVED)
    with pytest.raises(ValueError, match="reserved"):
        replay_strategy(run, (leaked,))


def gapped_market(symbol, path, days, gap_hour, drop, **options):
    """``path``, with every bar from ``gap_hour`` hours into the window scaled down by
    ``drop``: the bar at ``gap_hour`` OPENS below the previous close (a true gap)."""
    from crypto_grid_bot.backtest.klines import Kline

    base = fx.market(symbol, path, days, **options)
    cut = fx.START + gap_hour * HOUR

    def scaled(rows):
        factor = D(str(1 - drop))
        return tuple(
            row
            if row.open_ms < cut
            else Kline(
                row.open_ms,
                (row.open * factor).quantize(D(".01")),
                (row.high * factor).quantize(D(".01")),
                (row.low * factor).quantize(D(".01")),
                (row.close * factor).quantize(D(".01")),
                row.volume,
                row.quote_volume,
                row.taker_buy_base,
            )
            for row in rows
        )

    spot = scaled(base.spot.hourly)
    futures = replace(base.futures, hourly=scaled(base.futures.hourly)) if base.futures else None
    return replace(
        base, spot=replace(base.spot, hourly=spot), daily=fx.daily(spot), futures=futures
    )


def test_a_resting_grid_basket_beside_another_holding_does_not_end_the_run():
    # Critic B1: a cap-driven cancel of a resting basket is final at once in replay.
    markets = (
        fx.market("BTCUSDT", fx.uptrend, 4, futures=True, flow=True),
        fx.market("ETHUSDT", fx.ranging, 4, futures=True, flow=True),
    )
    for scenario in ("open_low_high_close", "open_high_low_close"):
        trace = replay_strategy(fx.run("combined", 4, scenario=scenario), markets)
        assert trace.failure is None
        report = strategy_report(trace, adapter_pin=PIN)
        assert report.complete, report.issues
        assert report.reconciliation_residual == 0
        assert {c.strategy for c in report.contributions} >= {"spot_trend"}


def test_a_stop_crossed_by_the_opening_quote_executes_in_that_frame():
    # Critic M1: before any entry at that boundary, at the gapped open.
    market = gapped_market("BTCUSDT", fx.uptrend, 2, 24, 0.2)
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None
    exits = [e for e in fills(trace) if not e.increase]
    assert exits and exits[0].exit_reason == "stop"
    stop_fill = exits[0].fill
    gap_hour = fx.START + 24 * HOUR
    assert stop_fill.timestamp_ms == gap_hour and stop_fill.event_id.startswith("boundary:")
    gap_open = next(b.open for b in market.spot.hourly if b.open_ms == gap_hour)
    assert stop_fill.price <= gap_open  # adverse at the gap, never at the better stop
    later_entries = [e.fill for e in fills(trace) if e.increase and e.fill.timestamp_ms == gap_hour]
    booked = [e.fill.event_id for e in fills(trace)]
    assert all(
        booked.index(entry.event_id) > booked.index(stop_fill.event_id) for entry in later_entries
    )
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete and report.reconciliation_residual == 0


def test_grid_child_fills_complete_their_opportunity_funnel():
    trace = replay_strategy(
        fx.run("spot_grid", 10), (fx.market("BTCUSDT", fx.ranging, 10, flow=True),)
    )
    assert trace.failure is None
    filled = [e for e in trace.evidence if e.phase == "filled"]
    assert filled and all(e.accepted and dict(e.details)["child_id"] for e in filled)
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete, report.issues
    delays = [g.entry_delay_ms for g in report.opportunity_episodes if "filled" in g.stages]
    assert delays and all(delay is not None and delay > 0 for delay in delays)


def test_a_refused_grid_allocation_is_withdrawn_and_visible(monkeypatch):
    from crypto_grid_bot.combined import strategy_replay
    from crypto_grid_bot.combined.allocation import GridAllocation

    def refuse(result):
        return GridAllocation(
            False, "child_below_minimum", result.intent.intent_id, (), *(D(0),) * 8
        )

    monkeypatch.setattr(strategy_replay, "allocate_grid", refuse)
    trace = replay_strategy(
        fx.run("spot_grid", 3), (fx.market("BTCUSDT", fx.ranging, 3, flow=True),)
    )
    assert trace.failure is None and fills(trace) == []
    refused = [e for e in trace.evidence if e.phase == "filled" and not e.accepted]
    assert refused and all(e.reasons == ("child_below_minimum",) for e in refused)
    assert trace.finality  # each withdrawn basket's cancel is final, with its record
    report = strategy_report(trace, adapter_pin=PIN)
    # No trade means zero drawdown, an indeterminate return/drawdown: incomplete by
    # rule. The refusals themselves are well-formed funnel evidence.
    assert not any("opportunity" in issue for issue in report.issues)
    assert "blocked" in {stage for g in report.opportunity_episodes for stage in g.stages}


def test_admission_marks_outside_settlements_are_retained():
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    assert trace.failure is None
    decision_marks = [o for o in trace.observations if o.phase == "decision"]
    assert decision_marks and all(o.kind == "frame" for o in decision_marks)
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete, report.issues


def test_funding_records_after_the_window_are_never_read():
    from crypto_grid_bot.backtest.funding import FundingRecord

    market = fx.market("BTCUSDT", fx.downtrend, 2, futures=True)
    later = FundingRecord(fx.START + 30 * DAY, 4, D("NaN"))
    trace = replay_strategy(
        fx.run("futures_trend", 2), (replace(market, funding=(*market.funding, later)),)
    )
    baseline = replay_strategy(fx.run("futures_trend", 2), (market,))
    assert trace.failure is None
    assert comparable(trace) == comparable(baseline)


def test_a_failed_trace_is_an_explicitly_incomplete_report(monkeypatch):
    from crypto_grid_bot.combined import strategy_replay

    original = strategy_replay.replay_held_portfolio

    def failing(*args, **kwargs):
        return replace(original(*args, **kwargs), failure="portfolio_safety_failure")

    monkeypatch.setattr(strategy_replay, "replay_held_portfolio", failing)
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    report = strategy_report(trace, adapter_pin=PIN)
    assert "replay_failure:portfolio_safety_failure" in report.issues
    assert report.producer_issues == ("replay_failure:portfolio_safety_failure",)
    assert not report.complete


def test_duplicate_minute_bars_are_refused_before_any_replay():
    market = fx.market("BTCUSDT", fx.ranging, 2, flow=True)
    duplicated = replace(market, minutes=(*market.minutes, market.minutes[100]))
    with pytest.raises(ValueError, match="minute"):
        replay_strategy(fx.run("spot_grid", 2), (duplicated,))
