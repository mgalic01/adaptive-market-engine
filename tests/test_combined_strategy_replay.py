"""Complete V3.1 strategy replay over synthetic inputs (never market data)."""

from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
import pytest

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.account import FundingEvent
from crypto_grid_bot.combined.replay_records import evidence_records, strategy_report
from crypto_grid_bot.combined.report import utc_text
from crypto_grid_bot.combined.strategy_replay import TraceFill, replay_strategy

PIN = "0" * 64
HOUR = fx.HOUR
DAY = fx.DAY


def fills(trace):
    return [event for event in trace.events if isinstance(event, TraceFill)]


def payments(trace):
    return [event for event in trace.events if isinstance(event, FundingEvent)]


def window_hours(stamps):
    return [(stamp - fx.START) // HOUR for stamp in stamps]


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
    assert trace.data_gaps == () and trace.stale_terminal_marks == ()
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
    # A grid run without the coin's minute input is named, and its report is incomplete.
    assert trace.missing_grid_inputs == ("BTCUSDT",)
    report = strategy_report(trace, adapter_pin=PIN)
    assert not report.complete and "missing_grid_input:BTCUSDT" in report.issues


def flow_market(days: int, steps):
    """A ranging market whose minute taker-buy share steps at window hours.

    ``steps`` is ``((from_hour, share), ...)``; the first starts at hour -1, the
    fixture's first minute. The gate reads the fifteen minutes before each hour, so at
    the frame of hour h it sees the step in force just before h: a step at hour K
    leaves every frame up to K on the old share and every frame after K on the new.
    """
    base = fx.market("BTCUSDT", fx.ranging, days)
    edges = [fx.START + hour * HOUR for hour, _ in steps] + [fx.START + days * DAY]
    minutes = tuple(
        bar
        for (_, share), start, stop in zip(steps, edges, edges[1:], strict=False)
        for bar in fx.minutes(start, stop, share)
    )
    return replace(base, minutes=minutes)


def grid_buys(trace):
    return [e.fill for e in fills(trace) if e.increase]


def test_a_blocked_flow_gate_withholds_the_resting_grid_buys():
    # Probe: flow is healthy at hour 0, so a basket is admitted, and blocked from the
    # frame of hour 3 on. The control (flow always healthy) fills a buy at hour 26.
    control = replay_strategy(
        fx.run("spot_grid", 3), (fx.market("BTCUSDT", fx.ranging, 3, flow=True),)
    )
    blocked = replay_strategy(fx.run("spot_grid", 3), (flow_market(3, ((-1, ".6"), (2, ".3"))),))
    assert control.failure is None and blocked.failure is None
    assert grid_buys(control)[0].timestamp_ms == fx.START + 26 * HOUR
    first = blocked.decisions[0]
    assert first.assessment.decision_ms == fx.START and first.result.admission.accepted
    # No interval that opens with the gate blocked contains a fill of the resting buys.
    assert grid_buys(blocked) == []
    withheld = dict(blocked.withheld_buys)["BTCUSDT"]
    assert withheld == tuple(fx.START + hour * HOUR for hour in range(3, 72))
    # Withheld, not canceled: the basket and its reservation are still standing.
    assert blocked.finality == () and len(blocked.decisions) == 1
    last = blocked.observations[-1].snapshot
    assert last.available_cash < last.account.free_cash


def test_withheld_grid_buys_fill_again_at_their_levels_once_flow_recovers():
    control = replay_strategy(
        fx.run("spot_grid", 4), (fx.market("BTCUSDT", fx.ranging, 4, flow=True),)
    )
    # Blocked for the frames of hours 3-30, healthy again from the frame of hour 31.
    recovered = replay_strategy(
        fx.run("spot_grid", 4), (flow_market(4, ((-1, ".6"), (2, ".3"), (30, ".6"))),)
    )
    assert recovered.failure is None
    resumed = grid_buys(recovered)
    assert resumed and min(f.timestamp_ms for f in resumed) > fx.START + 31 * HOUR
    # The same untouched level of the same hour-0 basket, not a rebuild at a new price.
    first, level = resumed[0], grid_buys(control)[0]
    assert (first.lot_id, first.price) == (level.lot_id, level.price)
    placed = [d for d in recovered.decisions if d.assessment.decision_ms < first.timestamp_ms]
    assert len(placed) == 1
    assert dict(recovered.withheld_buys)["BTCUSDT"] == tuple(
        fx.START + hour * HOUR for hour in range(3, 31)
    )
    report = strategy_report(recovered, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


def test_a_held_grid_lot_still_sells_at_its_target_while_flow_is_blocked():
    # Healthy through the frame of hour 25 (the buy fills in bar 25), blocked after.
    trace = replay_strategy(fx.run("spot_grid", 3), (flow_market(3, ((-1, ".6"), (25, ".3"))),))
    assert trace.failure is None
    assert [f.timestamp_ms for f in grid_buys(trace)] == [fx.START + 26 * HOUR]
    sells = [e for e in fills(trace) if not e.increase]
    assert [(e.exit_reason, e.fill.timestamp_ms) for e in sells] == [
        ("grid_target", fx.START + 27 * HOUR)
    ]
    # The target sold in an interval whose other resting buys were withheld.
    assert fx.START + 26 * HOUR in dict(trace.withheld_buys)["BTCUSDT"]
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


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
        # A missing window hour is a data gap; a duplicated one is a defect.
        lambda m, r: (
            replace(m, spot=replace(m.spot, hourly=(*m.spot.hourly, m.spot.hourly[-1]))),
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


GRID_ARMS = [
    "spot_grid",
    "combined",
    "combined_without_continuation",
    "combined_without_full_short_qualification",
    "combined_without_discretionary_trailing",
    "combined_without_funding_admission",
    "combined_without_recovery",
]


def without_minutes(market, keep=lambda bar: False):
    """``market`` with only the minute bars ``keep`` accepts (none by default)."""
    return replace(market, minutes=tuple(bar for bar in market.minutes if keep(bar)))


def issue_names(report):
    return [issue for issue in report.issues if issue.startswith("missing_grid_input:")]


@pytest.mark.parametrize("arm", GRID_ARMS)
def test_a_grid_arm_without_a_coins_minute_input_is_an_incomplete_run(arm):
    # Probe: the grid runs on BTC; ETH has no minute input at all.
    btc = fx.market("BTCUSDT", fx.ranging, 3, futures=True, flow=True)
    eth = fx.market("ETHUSDT", fx.ranging, 3, futures=True)
    for markets in ((btc, eth), (eth, btc)):
        trace = replay_strategy(fx.run(arm, 3), markets)
        assert trace.failure is None
        assert trace.missing_grid_inputs == ("ETHUSDT",)
        report = strategy_report(trace, adapter_pin=PIN)
        assert not report.complete
        assert issue_names(report) == ["missing_grid_input:ETHUSDT"]
        assert "missing_grid_input:ETHUSDT" in report.producer_issues


def test_every_coin_without_minutes_is_named_in_symbol_order():
    markets = (
        fx.market("ETHUSDT", fx.ranging, 2, futures=True),
        fx.market("BTCUSDT", fx.ranging, 2, futures=True),
        fx.market("SOLUSDT", fx.ranging, 2, futures=True, flow=True),
    )
    trace = replay_strategy(fx.run("combined", 2), markets)
    assert trace.failure is None
    assert trace.missing_grid_inputs == ("BTCUSDT", "ETHUSDT")
    report = strategy_report(trace, adapter_pin=PIN)
    assert issue_names(report) == ["missing_grid_input:BTCUSDT", "missing_grid_input:ETHUSDT"]


def test_a_spot_grid_run_missing_one_coins_minutes_is_incomplete():
    markets = (
        fx.market("BTCUSDT", fx.ranging, 3, flow=True),
        fx.market("ETHUSDT", fx.ranging, 3),
    )
    trace = replay_strategy(fx.run("spot_grid", 3), markets)
    assert trace.failure is None and trace.missing_grid_inputs == ("ETHUSDT",)
    # The coin that has its input still trades its grid; only the run is incomplete.
    assert {e.fill.symbol for e in fills(trace)} == {"BTCUSDT"}
    report = strategy_report(trace, adapter_pin=PIN)
    assert not report.complete and "missing_grid_input:ETHUSDT" in report.issues


@pytest.mark.parametrize(
    ("arm", "path", "options"),
    [
        ("spot_trend", fx.uptrend, {}),
        ("futures_trend", fx.downtrend, {"futures": True}),
        ("futures_trend_long_only", fx.uptrend, {"futures": True}),
    ],
)
def test_a_trend_only_arm_needs_no_minute_input(arm, path, options):
    trace = replay_strategy(fx.run(arm, 3), (fx.market("BTCUSDT", path, 3, **options),))
    assert trace.failure is None and fills(trace)
    assert trace.missing_grid_inputs == ()
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete, report.issues
    assert issue_names(report) == []


def test_the_trend_components_of_a_coin_without_minutes_are_unaffected():
    flowing = fx.market("BTCUSDT", fx.uptrend, 3, futures=True, flow=True)
    bare = without_minutes(flowing)
    with_flow = replay_strategy(fx.run("combined", 3), (flowing,))
    without = replay_strategy(fx.run("combined", 3), (bare,))
    assert with_flow.failure is None and without.failure is None
    assert with_flow.missing_grid_inputs == () and without.missing_grid_inputs == ("BTCUSDT",)
    assert fills(without) and comparable(without) == comparable(with_flow)


def test_sparse_missing_minutes_are_not_a_missing_input():
    market = fx.market("BTCUSDT", fx.ranging, 3, flow=True)
    # The fifteen minutes before hour 40 are gone; every other minute is present.
    hole = range(fx.START + 40 * HOUR - 15 * 60_000, fx.START + 40 * HOUR, 60_000)
    gapped = without_minutes(market, lambda bar: bar.open_ms not in hole)
    assert len(gapped.minutes) == len(market.minutes) - 15
    trace = replay_strategy(fx.run("spot_grid", 3), (gapped,))
    assert trace.failure is None and trace.missing_grid_inputs == ()
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.complete, report.issues
    assert issue_names(report) == []


@pytest.mark.parametrize(
    ("minute_offset_ms", "missing"),
    [
        (-15 * 60_000, False),  # the first minute the gate reads
        (-16 * 60_000, True),  # just before the read range
        (3 * DAY - 60_000, False),  # the last minute before the window ends
        (3 * DAY, True),  # the window's end is exclusive
    ],
)
def test_a_single_minute_inside_the_read_range_is_a_present_input(minute_offset_ms, missing):
    stamp = fx.START + minute_offset_ms
    only = replace(fx.market("BTCUSDT", fx.ranging, 3), minutes=fx.minutes(stamp, stamp + 60_000))
    trace = replay_strategy(fx.run("spot_grid", 3), (only,))
    assert trace.failure is None
    assert trace.missing_grid_inputs == (("BTCUSDT",) if missing else ())


def masked(market, venue, hours):
    """``market`` without the ``venue`` bars opening ``hours`` hours into the window.

    Spot daily bars follow their remaining hours under the frozen rule, as registered
    daily bars do.
    """
    gone = {fx.START + hour * HOUR for hour in hours}
    source = getattr(market, venue)
    kept = tuple(bar for bar in source.hourly if bar.open_ms not in gone)
    changed = replace(market, **{venue: replace(source, hourly=kept)})
    return replace(changed, daily=fx.daily(kept)) if venue == "spot" else changed


def bar_at(rows, stamp):
    return next(bar for bar in rows if bar.open_ms == stamp)


def test_a_held_coin_without_its_bar_closes_at_the_next_opening_quote():
    # Probe: spot bar 30 is missing while the hour-0 spot trend is held.
    market = masked(fx.market("BTCUSDT", fx.uptrend, 2), "spot", (30,))
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    gap = fx.START + 30 * HOUR
    assert trace.data_gaps == (("BTCUSDT", "spot", (gap,)),)
    # At the masked boundary the holding keeps its last mark and its close is carried.
    carried = [o for o in trace.observations if o.timestamp_ms == gap][-1].snapshot
    assert carried.close_required == ("BTCUSDT",)
    assert carried.account.positions[0].mark == bar_at(market.spot.hourly, gap - HOUR).close
    # Nothing fills at that boundary or inside the masked bar; the close executes at
    # the next bar's opening quote, with the held slippage.
    booked = fills(trace)
    assert not [e for e in booked if e.fill.timestamp_ms == gap]
    assert [e.fill.event_id.split(":")[0] for e in booked if e.fill.timestamp_ms == gap + HOUR] == [
        "boundary"
    ]
    exit_fill = next(e for e in booked if not e.increase)
    assert exit_fill.fill.timestamp_ms == gap + HOUR
    assert "stale_position_or_missing_filters" in exit_fill.exit_reason
    assert exit_fill.fill.price <= bar_at(market.spot.hourly, gap + HOUR).open
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


def test_a_coin_without_its_bar_buys_nothing_from_its_resting_basket():
    btc = fx.market("BTCUSDT", fx.ranging, 3, flow=True)
    eth = fx.market("ETHUSDT", fx.ranging, 3, flow=True)
    filled = fx.START + 26 * HOUR
    control = replay_strategy(fx.run("spot_grid", 3), (btc, eth))
    assert [(f.symbol, f.timestamp_ms) for f in grid_buys(control)][:2] == [
        ("BTCUSDT", filled),
        ("ETHUSDT", filled),
    ]
    # Probe: BTCUSDT's bar 25, in which both first buys filled, is missing.
    trace = replay_strategy(fx.run("spot_grid", 3), (masked(btc, "spot", (25,)), eth))
    assert trace.failure is None
    assert trace.data_gaps == (("BTCUSDT", "spot", (fx.START + 25 * HOUR,)),)
    admitted = [d for d in trace.decisions if d.assessment.decision_ms == fx.START]
    assert len(admitted) == 2 and all(d.result.admission.accepted for d in admitted)
    # The interval still runs for ETHUSDT; BTCUSDT's resting basket sits it out.
    assert [f.symbol for f in grid_buys(trace) if f.timestamp_ms == filled] == ["ETHUSDT"]
    # A data gap is not a flow-gate withholding.
    assert fx.START + 25 * HOUR not in dict(trace.withheld_buys).get("BTCUSDT", ())
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


def test_a_held_futures_position_waits_out_a_72_hour_gap():
    market = masked(fx.market("BTCUSDT", fx.downtrend, 6, futures=True), "futures", range(24, 96))
    trace = replay_strategy(fx.run("futures_trend", 6), (market,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    first, back = fx.START + 24 * HOUR, fx.START + 96 * HOUR
    assert trace.data_gaps == (("BTCUSDT", "futures", tuple(range(first, back, HOUR))),)
    # Every slot inside the gap is still charged, at bar 23's close as a stale mark.
    in_gap = [p for p in payments(trace) if first <= p.timestamp_ms < back]
    assert [p.timestamp_ms for p in in_gap] == list(range(first, back, 8 * HOUR))
    assert all(p.stale_mark_ms == first for p in in_gap)
    booked = fills(trace)
    assert booked[0].increase and booked[0].fill.timestamp_ms == fx.START + HOUR
    # No fill while the bars are missing; the carried close executes at the first
    # returning opening quote (a short buys back at or above it).
    assert not [e for e in booked if first <= e.fill.timestamp_ms < back]
    exit_fill = next(e for e in booked if not e.increase)
    assert exit_fill.fill.timestamp_ms == back
    assert exit_fill.fill.event_id.startswith("boundary:")
    assert "stale_position_or_missing_filters" in exit_fill.exit_reason
    assert exit_fill.fill.price >= bar_at(market.futures.hourly, back).open
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


@pytest.mark.parametrize(("venue", "owner"), [("spot", "spot_trend"), ("futures", "futures_trend")])
def test_a_decision_without_its_venue_quote_is_refused_and_never_rerouted(venue, owner):
    # Spot is below the venue minimum, so with both quotes the hour-1 long falls back
    # to futures (control). Without the spot quote it is refused, not routed to futures;
    # without the futures quote the fallback itself is refused.
    base = fx.market("BTCUSDT", fx.uptrend, 2, futures=True)
    unexecutable = replace(
        base, spot=replace(base.spot, rules=replace(fx.RULES, min_notional=D("1e9")))
    )
    hour = fx.START + HOUR
    control = replay_strategy(fx.run("combined", 2), (unexecutable,))
    assert [(e.fill.timestamp_ms, e.fill.venue) for e in fills(control)][:1] == [(hour, "futures")]
    trace = replay_strategy(fx.run("combined", 2), (masked(unexecutable, venue, (1,)),))
    assert trace.failure is None
    assert trace.data_gaps == (("BTCUSDT", venue, (hour,)),)
    refused = next(d.result for d in trace.decisions if d.assessment.decision_ms == hour)
    assert refused.qualification.owner == owner and not refused.qualification.allowed
    assert "venue_quote_unavailable" in refused.qualification.reasons
    assert refused.intent is None and refused.admission is None
    assert not [e for e in fills(trace) if e.fill.timestamp_ms == hour]


def test_a_holding_without_the_last_bar_is_marked_at_its_last_close_as_stale():
    market = masked(fx.market("BTCUSDT", fx.uptrend, 2), "spot", (47,))
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    end = fx.START + 2 * DAY
    assert trace.data_gaps == (("BTCUSDT", "spot", (end - HOUR,)),)
    # Valued at bar 46's close, available at end - 1h, and named as a stale mark.
    assert trace.stale_terminal_marks == (("BTCUSDT", end - HOUR),)
    last_close = bar_at(market.spot.hourly, end - 2 * HOUR).close
    terminal = [o.snapshot for o in trace.observations if o.kind == "terminal"]
    assert terminal and all(s.account.positions[0].mark == last_close for s in terminal)
    assert all(s.stale == ("BTCUSDT",) for s in terminal)
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


def futures_open(market, stamp):
    return bar_at(market.futures.hourly, stamp).open


def test_a_funding_slot_inside_a_futures_gap_is_charged_at_the_last_close_as_stale():
    # Futures bars 6-17 are missing while the hour-1 short is held: slots 8 and 16 have
    # no bar, so each is still charged, valued at bar 5's close, available at hour 6.
    market = masked(fx.market("BTCUSDT", fx.downtrend, 2, futures=True), "futures", range(6, 18))
    trace = replay_strategy(fx.run("futures_trend", 2), (market,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    entry = fills(trace)[0].fill
    assert entry.timestamp_ms == fx.START + HOUR
    stale_since = fx.START + 6 * HOUR
    last_close = bar_at(market.futures.hourly, fx.START + 5 * HOUR).close
    charged = payments(trace)
    in_gap = [p for p in charged if p.stale_mark_ms is not None]
    assert window_hours(p.timestamp_ms for p in in_gap) == [8, 16]
    assert all(p.stale_mark_ms == stale_since for p in in_gap)
    # A short receives a positive rate on its full quantity at that stale mark.
    assert all(p.amount == entry.quantity * D(".0001") * last_close for p in in_gap)
    assert all(p.scheduled_ms is None for p in charged)
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


def test_a_funding_slot_without_a_futures_bar_on_an_unheld_coin_charges_nothing():
    # Futures bars 0-8 are missing: slots 0 and 8 have no bar and no earlier window
    # close, but nothing is held there, so nothing is due. Entries wait for a quote.
    market = masked(fx.market("BTCUSDT", fx.downtrend, 2, futures=True), "futures", range(9))
    trace = replay_strategy(fx.run("futures_trend", 2), (market,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    assert fills(trace)[0].fill.timestamp_ms == fx.START + 9 * HOUR
    assert window_hours(p.timestamp_ms for p in payments(trace)) == [16, 24, 32, 40]


def hour_ms(hour):
    return fx.START + hour * HOUR


def funding_records(*spans, rate=".001"):
    """Records over ``(first, stop, interval)`` spans, in hours into the window."""
    return tuple(
        FundingRecord(hour_ms(hour), interval, D(rate))
        for first, stop, interval in spans
        for hour in range(first, stop, interval)
    )


def move_record(market, hour, offset_ms):
    """``market`` with the record settled at ``hour`` moved by ``offset_ms``."""
    return replace(
        market,
        funding=tuple(
            replace(r, calc_time_ms=r.calc_time_ms + offset_ms)
            if r.calc_time_ms == hour_ms(hour)
            else r
            for r in market.funding
        ),
    )


def test_a_cadence_change_charges_every_record_and_refuses_increases_after_it():
    # A spike in bar 40 stops the hour-1 short out at hour 41. With an eight-hour
    # cadence throughout, the short is re-entered at once (control). With 8-hour
    # records until hour 16 and 4-hour records from hour 20, every record is charged
    # while the short is held, and no increase is admitted after the change.
    base = fx.market("BTCUSDT", crash_after(fx.downtrend, 40, -0.15), 3, futures=True)
    control = replay_strategy(
        fx.run("futures_trend", 3), (replace(base, funding=funding_records((-8, 80, 8))),)
    )
    changed = replace(base, funding=funding_records((-8, 17, 8), (20, 80, 4)))
    trace = replay_strategy(fx.run("futures_trend", 3), (changed,))
    assert control.failure is None and trace.failure is None
    stopped = fx.START + 41 * HOUR
    assert [(e.fill.timestamp_ms, e.increase) for e in fills(control)][:3] == [
        (fx.START + HOUR, True),
        (stopped, False),
        (stopped, True),
    ]
    assert [(e.fill.timestamp_ms, e.increase) for e in fills(trace)] == [
        (fx.START + HOUR, True),
        (stopped, False),
    ]
    entry = fills(trace)[0].fill
    charged = payments(trace)
    assert window_hours(p.timestamp_ms for p in charged) == [8, 16, 20, 24, 28, 32, 36, 40]
    for payment in charged:
        expected = entry.quantity * D(".001") * futures_open(changed, payment.timestamp_ms)
        assert payment.amount == expected
    # 8h at 16 then 4h at 20 matches only one of the two intervals: irregular, not missing.
    assert trace.funding_schedule_irregular == (("BTCUSDT", hour_ms(16), 8, hour_ms(20), 4),)
    # The latest published record now declares a 4-hour cadence: every re-entry the
    # control admitted at hour 41 is refused, then and at each later decision.
    after = [d for d in trace.decisions if d.assessment.decision_ms >= stopped]
    assert after and after[0].assessment.decision_ms == stopped
    assert all(d.result.admission.reason == "funding_unavailable" for d in after)
    report = strategy_report(trace, adapter_pin=PIN)
    assert report.reconciliation_residual == 0


def test_a_lengthening_cadence_change_on_a_held_short_is_irregular_not_missing():
    # 8-hour records to hour 8, 4-hour records from 12 to 24, 8-hour again from 32, all
    # while the hour-1 short is held. Whichever end of the interval ``interval_hours``
    # names, 4h at 24 then 8h at 32 leaves no slot missing (no 28h settlement owed).
    market = fx.market("BTCUSDT", fx.downtrend, 3, futures=True)
    changed = replace(market, funding=funding_records((-8, 9, 8), (12, 25, 4), (32, 80, 8)))
    trace = replay_strategy(fx.run("futures_trend", 3), (changed,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    assert [e.increase for e in fills(trace)] == [True]
    assert window_hours(p.timestamp_ms for p in payments(trace)) == [
        *(8, 12, 16, 20, 24),
        *(32, 40, 48, 56, 64),
    ]
    assert trace.funding_schedule_irregular == (
        ("BTCUSDT", hour_ms(8), 8, hour_ms(12), 4),
        ("BTCUSDT", hour_ms(24), 4, hour_ms(32), 8),
    )


def test_a_funding_gap_on_a_flat_book_refuses_entries_and_charges_nothing():
    # The records at hours -8 and 0 are missing; nothing is held at either slot.
    market = fx.market("BTCUSDT", fx.downtrend, 2, futures=True)
    gone = {fx.START - 8 * HOUR, fx.START}
    gapped = replace(market, funding=tuple(r for r in market.funding if r.calc_time_ms not in gone))
    trace = replay_strategy(fx.run("futures_trend", 2), (gapped,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    # The latest published record is older than eight hours until hour 8's is usable.
    early = [d for d in trace.decisions if d.assessment.decision_ms <= fx.START + 8 * HOUR]
    assert window_hours(d.assessment.decision_ms for d in early) == list(range(9))
    assert all(d.result.admission.reason == "funding_unavailable" for d in early)
    assert fills(trace)[0].fill.timestamp_ms == fx.START + 9 * HOUR
    assert window_hours(p.timestamp_ms for p in payments(trace)) == [16, 24, 32, 40]


def test_a_missing_settlement_without_a_futures_holding_does_not_stop_the_run():
    # The combined arm holds the uptrend on spot; the hour-24 futures record is missing.
    market = fx.market("BTCUSDT", fx.uptrend, 2, futures=True)
    gapped = replace(
        market, funding=tuple(r for r in market.funding if r.calc_time_ms != fx.START + DAY)
    )
    trace = replay_strategy(fx.run("combined", 2), (gapped,))
    assert trace.failure is None and trace.boundaries[-1].role == "terminal"
    assert fills(trace) and all(e.fill.venue == "spot" for e in fills(trace))
    assert payments(trace) == []


@pytest.mark.parametrize(
    "records",
    [
        # One slot missing inside the window: 16h and 32h are 16 hours apart.
        lambda rs: tuple(r for r in rs if r.calc_time_ms != hour_ms(24)),
        # Records end before the window does: the last one's own interval applies.
        lambda rs: tuple(r for r in rs if r.calc_time_ms < hour_ms(24)),
        # 8h at 16h then 4h at 28h: 12 hours exceed both intervals, so 24h is missing.
        lambda rs: funding_records((-8, 17, 8), (28, 56, 4), rate=".0001"),
    ],
)
def test_a_missing_settlement_on_a_held_futures_position_stops_the_run(records):
    market = fx.market("BTCUSDT", fx.downtrend, 2, futures=True)
    gapped = replace(market, funding=records(market.funding))
    trace = replay_strategy(fx.run("futures_trend", 2), (gapped,))
    slot = fx.START + DAY
    # Never assumed zero: the run stops at the slot, keeping everything before it.
    assert trace.failure == f"funding_record_missing:BTCUSDT:{slot}"
    assert window_hours(p.timestamp_ms for p in payments(trace)) == [8, 16]
    assert (trace.boundaries[-1].timestamp_ms, trace.boundaries[-1].role) == (slot, "settled")
    report = strategy_report(trace, adapter_pin=PIN)
    assert not report.complete and f"replay_failure:{trace.failure}" in report.issues
    assert report.reconciliation_residual == 0


@pytest.mark.parametrize(
    ("offset_ms", "booked_hour", "off_hour"),
    [
        (30_000, 16, False),  # within a minute after its hour: settled on that hour
        (-2, 16, False),  # 15:59:59.998, within a minute before 16:00: settled at 16:00
        (15 * 60_000, 17, True),  # off the hour: booked at the next hourly boundary
        (-2 * 60_000, 16, True),  # 15:58, off the hour: booked at 16:00
    ],
)
def test_an_off_hour_record_is_charged_at_the_next_boundary_with_both_times(
    offset_ms, booked_hour, off_hour
):
    # The 16h record of the held short's 8-hour schedule settles early or late.
    market = move_record(fx.market("BTCUSDT", fx.downtrend, 2, futures=True), 16, offset_ms)
    trace = replay_strategy(fx.run("futures_trend", 2), (market,))
    assert trace.failure is None
    entry = fills(trace)[0].fill
    charged = payments(trace)
    assert window_hours(p.timestamp_ms for p in charged) == [8, booked_hour, 24, 32, 40]
    late = charged[1]
    # Charged on the holdings that survived to the booking boundary, at its mark.
    assert late.amount == entry.quantity * D(".0001") * futures_open(market, late.timestamp_ms)
    assert late.scheduled_ms == (hour_ms(16) + offset_ms if off_hour else None)
    assert all(p.scheduled_ms is None for p in charged if p is not late)


def test_an_off_hour_record_without_its_booking_bar_keeps_both_times_and_a_stale_mark():
    # The 16h record settles at 16:15 and books at 17h, whose futures bar is missing:
    # it is valued at bar 16's close, available at 17h.
    base = masked(fx.market("BTCUSDT", fx.downtrend, 2, futures=True), "futures", (17,))
    market = move_record(base, 16, 15 * 60_000)
    trace = replay_strategy(fx.run("futures_trend", 2), (market,))
    assert trace.failure is None
    entry = fills(trace)[0].fill
    late = next(p for p in payments(trace) if p.scheduled_ms is not None)
    assert (late.timestamp_ms, late.scheduled_ms, late.stale_mark_ms) == (
        hour_ms(17),
        hour_ms(16) + 15 * 60_000,
        hour_ms(17),
    )
    last_close = bar_at(market.futures.hourly, hour_ms(16)).close
    assert late.amount == entry.quantity * D(".0001") * last_close


def test_an_off_hour_record_after_its_holding_exited_is_kept_as_evidence():
    # A spike in bar 40 stops the hour-1 short out intrabar (at 41h). The 40h record,
    # settled at 40:15, books at 41h, when the short is gone: never charged, recorded.
    base = fx.market("BTCUSDT", crash_after(fx.downtrend, 40, -0.15), 3, futures=True)
    market = move_record(base, 40, 15 * 60_000)
    trace = replay_strategy(fx.run("futures_trend", 3), (market,))
    assert trace.failure is None
    assert [(e.fill.timestamp_ms, e.increase) for e in fills(trace)][:2] == [
        (hour_ms(1), True),
        (hour_ms(41), False),
    ]
    assert trace.funding_records_unbooked_after_exit == (
        ("BTCUSDT", hour_ms(40) + 15 * 60_000, hour_ms(41)),
    )
    assert hour_ms(41) not in [p.timestamp_ms for p in payments(trace)]


@pytest.mark.parametrize("spike", [False, True])
def test_an_off_hour_record_due_at_the_terminal_boundary_stops_a_held_run(spike):
    # The terminal boundary books no funding, so a record settled in the last hour
    # cannot be charged there: with the short still held, the run stops. If a spike in
    # that last bar stopped the short out first, the record is evidence instead.
    path = crash_after(fx.downtrend, 47, -0.15) if spike else fx.downtrend
    market = fx.market("BTCUSDT", path, 2, futures=True)
    late = FundingRecord(hour_ms(48) - 45 * 60_000, 8, D(".0001"))
    trace = replay_strategy(
        fx.run("futures_trend", 2), (replace(market, funding=(*market.funding, late)),)
    )
    if spike:
        assert trace.failure is None and trace.boundaries[-1].role == "terminal"
        assert trace.funding_records_unbooked_after_exit == (
            ("BTCUSDT", late.calc_time_ms, hour_ms(48)),
        )
    else:
        assert trace.failure == f"funding_record_unbooked:BTCUSDT:{late.calc_time_ms}"
        assert trace.boundaries[-1].role != "terminal"


@pytest.mark.parametrize(
    ("arm", "path", "failure"),
    [
        ("futures_trend", fx.downtrend, f"funding_records_collide:BTCUSDT:{hour_ms(24)}"),
        ("combined", fx.uptrend, None),  # held on spot: nothing is due, nothing fails
    ],
)
def test_two_records_booked_at_one_boundary_stop_only_a_held_run(arm, path, failure):
    # An off-hour record at 23:15 books at hour 24, where the next record settles.
    market = fx.market("BTCUSDT", path, 2, futures=True)
    early = FundingRecord(hour_ms(24) - 45 * 60_000, 8, D(".0001"))
    trace = replay_strategy(fx.run(arm, 2), (replace(market, funding=(*market.funding, early)),))
    assert trace.failure == failure
    if failure is None:
        assert trace.boundaries[-1].role == "terminal" and payments(trace) == []
    else:
        assert window_hours(p.timestamp_ms for p in payments(trace)) == [8, 16]


@pytest.mark.parametrize("collide", [False, True])
def test_a_four_hour_cadence_books_an_off_hour_record_without_a_collision(collide):
    # The held short's schedule turns 4-hourly at 20h; the 28h record settles at 28:30
    # and books at 29h, an hour clear of the 32h record. Only a record that truly books
    # at 32h beside it (one at 31:30) collides, and the held run stops there.
    market = fx.market("BTCUSDT", fx.downtrend, 3, futures=True)
    records = funding_records((-8, 17, 8), (20, 80, 4), rate=".0001")
    if collide:
        records = (*records, FundingRecord(hour_ms(32) - 30 * 60_000, 4, D(".0001")))
    trace = replay_strategy(
        fx.run("futures_trend", 3),
        (move_record(replace(market, funding=records), 28, 30 * 60_000),),
    )
    charged = payments(trace)
    if collide:
        assert trace.failure == f"funding_records_collide:BTCUSDT:{hour_ms(32)}"
        assert window_hours(p.timestamp_ms for p in charged) == [8, 16, 20, 24, 29]
    else:
        assert trace.failure is None
        assert window_hours(p.timestamp_ms for p in charged) == [
            *(8, 16, 20, 24, 29),
            *range(32, 72, 4),
        ]
    late = next(p for p in charged if p.timestamp_ms == hour_ms(29))
    assert late.scheduled_ms == hour_ms(28) + 30 * 60_000


RULINGS = (
    "present_day_saved_exchange_filters_on_historical_data",
    "v3_1_held_coin_without_bar_closed_at_next_bar_pending_orders_canceled",
)


def disclosed(report, prefix):
    return [note for note in report.disclosures if note.startswith(prefix)]


def rendered(report):
    """Every disclosure and the capital label appear in the page's Disclosures section."""
    from test_combined_dashboard import Elements, disclosure_section

    from crypto_grid_bot.combined.dashboard import render_report

    text = " ".join(Elements(disclosure_section(render_report(report))).text)
    assert all(note in text for note in report.disclosures)
    assert report.capital_label is None or report.capital_label in text
    return text


def test_every_v3_1_report_discloses_the_saved_filters_and_the_stale_close_rule():
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    report = strategy_report(trace, adapter_pin=PIN, capital_label="research_10000_usdt")
    assert report.complete, report.issues
    assert report.disclosures == RULINGS
    assert report.capital_label == "research_10000_usdt"
    rendered(report)


def test_a_gapped_run_stays_complete_and_discloses_the_gap_and_the_skipped_hour():
    market = masked(fx.market("BTCUSDT", fx.uptrend, 2), "spot", (30,))
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    report = strategy_report(trace, adapter_pin=PIN, skipped_hours=(hour_ms(30),))
    assert report.complete, report.issues
    gap = utc_text(hour_ms(30))
    assert report.disclosures == (
        *RULINGS,
        f"registered_skipped_hours: count=1 at={gap}",
        f"data_gap:BTCUSDT:spot: hours=1 first={gap} last={gap}",
    )
    rendered(report)


def test_a_stale_terminal_mark_is_disclosed():
    market = masked(fx.market("BTCUSDT", fx.uptrend, 2), "spot", (47,))
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    report = strategy_report(trace, adapter_pin=PIN)
    last = utc_text(hour_ms(47))
    assert disclosed(report, "stale_terminal_mark:") == [
        f"stale_terminal_mark:BTCUSDT: last_close_available={last}"
    ]
    rendered(report)


def test_withheld_grid_buys_are_disclosed_per_symbol_as_a_span():
    trace = replay_strategy(fx.run("spot_grid", 3), (flow_market(3, ((-1, ".6"), (2, ".3"))),))
    report = strategy_report(trace, adapter_pin=PIN)
    assert disclosed(report, "flow_gate_withheld_grid_buys:") == [
        f"flow_gate_withheld_grid_buys:BTCUSDT: intervals=69 first={utc_text(hour_ms(3))} "
        f"last={utc_text(hour_ms(71))}"
    ]
    rendered(report)


def test_an_off_hour_record_and_a_stale_fixing_mark_are_disclosed():
    base = masked(fx.market("BTCUSDT", fx.downtrend, 2, futures=True), "futures", (17,))
    trace = replay_strategy(fx.run("futures_trend", 2), (move_record(base, 16, 15 * 60_000),))
    report = strategy_report(trace, adapter_pin=PIN)
    record, booked = utc_text(hour_ms(16) + 15 * 60_000), utc_text(hour_ms(17))
    assert disclosed(report, "funding_off_hour_record_booked_next_hour:") == [
        f"funding_off_hour_record_booked_next_hour:BTCUSDT: records=1 first={record} last={record}"
    ]
    # Bar 16's close, available at 17h, values the 17h booking: stale by zero hours.
    assert disclosed(report, "funding_settled_at_stale_mark:") == [
        f"funding_settled_at_stale_mark:BTCUSDT: settlements=1 first={booked} last={booked} "
        f"oldest_mark={booked} max_staleness=0h"
    ]
    assert disclosed(report, "data_gap:") == [
        f"data_gap:BTCUSDT:futures: hours=1 first={booked} last={booked}"
    ]
    rendered(report)


def test_irregular_funding_pairs_are_each_disclosed():
    market = fx.market("BTCUSDT", fx.downtrend, 3, futures=True)
    changed = replace(market, funding=funding_records((-8, 9, 8), (12, 25, 4), (32, 80, 8)))
    report = strategy_report(
        replay_strategy(fx.run("futures_trend", 3), (changed,)), adapter_pin=PIN
    )
    assert disclosed(report, "funding_schedule_irregular:") == [
        f"funding_schedule_irregular:BTCUSDT: earlier={utc_text(hour_ms(8))}/8h "
        f"later={utc_text(hour_ms(12))}/4h",
        f"funding_schedule_irregular:BTCUSDT: earlier={utc_text(hour_ms(24))}/4h "
        f"later={utc_text(hour_ms(32))}/8h",
    ]
    rendered(report)


def test_an_off_hour_record_unbooked_after_its_holding_exited_is_disclosed():
    base = fx.market("BTCUSDT", crash_after(fx.downtrend, 40, -0.15), 3, futures=True)
    trace = replay_strategy(fx.run("futures_trend", 3), (move_record(base, 40, 15 * 60_000),))
    report = strategy_report(trace, adapter_pin=PIN)
    record = utc_text(hour_ms(40) + 15 * 60_000)
    assert disclosed(report, "funding_record_unbooked_after_exit:") == [
        f"funding_record_unbooked_after_exit:BTCUSDT: records=1 first={record} last={record}"
    ]
    rendered(report)


def test_the_engines_worse_fills_reach_the_trace_and_the_report(monkeypatch):
    from crypto_grid_bot.combined.engine import PortfolioEngine, WorseFill

    worse = (
        WorseFill("synthetic-1", "BTCUSDT", D("0.5"), D("-0.25")),
        WorseFill("synthetic-2", "BTCUSDT", D(0), D("0.75")),
    )
    monkeypatch.setattr(PortfolioEngine, "worse_fill_evidence", property(lambda self: worse))
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    assert trace.worse_fills == worse
    report = strategy_report(trace, adapter_pin=PIN)
    # Mixed signs are kept apart, never netted.
    assert disclosed(report, "worse_fill:") == [
        "worse_fill:BTCUSDT: fills=2 excess_risk=0.5 positive_extra_cost_fills=1 "
        "positive_extra_cost=0.75 negative_extra_cost_fills=1 negative_extra_cost=-0.25"
    ]
    rendered(report)


def test_a_stale_fixing_mark_discloses_its_oldest_mark_and_largest_staleness():
    # Futures bars 6-17 are missing under the held short: the 8h and 16h settlements are
    # valued at bar 5's close, available at 6h, so the 16h one is ten hours stale.
    market = masked(fx.market("BTCUSDT", fx.downtrend, 2, futures=True), "futures", range(6, 18))
    trace = replay_strategy(fx.run("futures_trend", 2), (market,))
    report = strategy_report(trace, adapter_pin=PIN)
    assert disclosed(report, "funding_settled_at_stale_mark:") == [
        f"funding_settled_at_stale_mark:BTCUSDT: settlements=2 first={utc_text(hour_ms(8))} "
        f"last={utc_text(hour_ms(16))} oldest_mark={utc_text(hour_ms(6))} max_staleness=10h"
    ]
    rendered(report)


EVE = fx.START - DAY  # the last history day before the window
SHORT_EVE = range(-24, -19)  # without these hours the eve keeps 19 of its 24


def read_daily(monkeypatch):
    """Record the daily bars the replay hands the assessment and each correlation snapshot."""
    from crypto_grid_bot.combined import strategy_replay

    seen = {"assessment": {}, "correlation": []}
    series, groups = strategy_replay.AssessmentSeries, strategy_replay.correlation_groups

    def assessed(symbol, hourly, daily, **kwargs):
        seen["assessment"][symbol] = tuple(daily)
        return series(symbol, hourly, daily, **kwargs)

    def grouped(daily, decision_ms):
        seen["correlation"].append({symbol: tuple(rows) for symbol, rows in daily.items()})
        return groups(daily, decision_ms)

    monkeypatch.setattr(strategy_replay, "AssessmentSeries", assessed)
    monkeypatch.setattr(strategy_replay, "correlation_groups", grouped)
    return seen


def with_volume(rows, day, extra):
    return tuple(replace(b, volume=b.volume + extra) if b.open_ms == day else b for b in rows)


@pytest.mark.parametrize(
    ("removed", "supplied"),
    [
        # The last day a two-day window reads (its first) does not sum its hours' volume.
        ((), lambda market, full: with_volume(market.daily, fx.START, 1)),
        # A history day of 24 hours without its bar.
        ((), lambda market, full: tuple(b for b in market.daily if b.open_ms != EVE)),
        # A close that cannot even be compared.
        (
            (),
            lambda market, full: tuple(
                replace(b, close=D("sNaN")) if b.open_ms == EVE else b for b in market.daily
            ),
        ),
        # A bar for an eve of 19 hours, which the rule gives none.
        (SHORT_EVE, lambda market, full: full.daily),
        # The 24-hour bar of an eve that keeps 23 hours.
        ((-19,), lambda market, full: full.daily),
    ],
)
def test_a_supplied_daily_bar_that_differs_from_its_hours_is_refused(removed, supplied):
    full = fx.market("BTCUSDT", fx.uptrend, 2)
    market = masked(full, "spot", removed)
    with pytest.raises(ValueError, match="BTCUSDT daily"):
        replay_strategy(fx.run("spot_trend", 2), (replace(market, daily=supplied(market, full)),))


def test_a_supplied_daily_bar_the_run_never_reads_is_not_checked():
    # A two-day window's last decision, at 47h, reads the days closed by then; its second
    # day closes at the window's end and is never read.
    market = fx.market("BTCUSDT", fx.uptrend, 2)
    changed = replace(market, daily=with_volume(market.daily, fx.START + DAY, 1))
    assert changed.daily != market.daily
    trace = replay_strategy(fx.run("spot_trend", 2), (changed,))
    assert trace.failure is None
    assert comparable(trace) == comparable(replay_strategy(fx.run("spot_trend", 2), (market,)))


def test_a_day_of_23_hours_is_read_as_their_aggregate(monkeypatch):
    seen = read_daily(monkeypatch)
    market = masked(fx.market("BTCUSDT", fx.downtrend, 2), "spot", (-19,))
    hours = [bar for bar in market.spot.hourly if EVE <= bar.open_ms < fx.START]
    assert len(hours) == 23
    aggregate = Kline(
        EVE,
        hours[0].open,
        max(bar.high for bar in hours),
        min(bar.low for bar in hours),
        hours[-1].close,
        sum((bar.volume for bar in hours), D(0)),
        sum((bar.quote_volume for bar in hours), D(0)),
        sum((bar.taker_buy_base for bar in hours), D(0)),
    )
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None
    read = seen["assessment"]["BTCUSDT"]
    assert {bar.open_ms: bar for bar in read}[EVE] == aggregate
    # The correlation groups read the very same bars.
    assert seen["correlation"] and all(c == {"BTCUSDT": read} for c in seen["correlation"])
    first = trace.decisions[0].assessment
    assert (first.decision_ms, first.daily_closed_ms) == (fx.START, fx.START)
    assert f"BTCUSDT:1d:{EVE}" in first.source_refs


def test_a_day_of_19_hours_has_no_bar_and_the_next_days_decisions_miss_it(monkeypatch):
    seen = read_daily(monkeypatch)
    market = masked(fx.market("BTCUSDT", fx.downtrend, 2), "spot", SHORT_EVE)
    assert EVE not in {bar.open_ms for bar in market.daily}
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    assert trace.failure is None
    assert EVE not in {bar.open_ms for bar in seen["assessment"]["BTCUSDT"]}
    # Every decision of the window's first day is due to read the eve's bar.
    (episode,) = trace.unavailable
    assert (episode.record.first_ms, episode.record.last_ms) == (fx.START, fx.START + DAY - HOUR)
    assert "missing_daily_bar" in episode.record.reasons
    assert episode.assessment.daily_gaps == ((EVE, fx.START),)
    # The next day reads its own due bar again.
    assert trace.decisions and all(
        d.assessment.daily_closed_ms == fx.START + DAY for d in trace.decisions
    )


def test_a_missing_due_daily_bar_is_one_refused_detection_per_episode():
    # The window's second day keeps 19 of its 24 hours, so it has no daily bar.
    missing = fx.START + DAY
    market = masked(fx.market("BTCUSDT", fx.downtrend, 4), "spot", range(24, 29))
    trace = replay_strategy(fx.run("spot_trend", 4), (market,))
    assert trace.failure is None
    first = missing + DAY  # every decision of the next day reads the missing bar as due
    # The hours gone from the second day leave its own hourly and 4h refusals too.
    refused = [
        e
        for e in trace.evidence
        if e.phase == "detected" and not e.accepted and "missing_daily_bar" in e.reasons
    ]
    assert [e.timestamp_ms for e in refused] == [first]
    (episode,) = [e for e in trace.unavailable if "missing_daily_bar" in e.record.reasons]
    record = episode.record
    assert (record.first_ms, record.last_ms) == (first, first + DAY - HOUR)
    assert record.reasons == refused[0].reasons == episode.assessment.reasons
    assert record.opportunity_id == refused[0].opportunity_id
    assert record.assessment_id == episode.assessment.assessment_id
    assert record.size_unavailable == "no_signal" and record.spot_fee_rate == fx.COSTS.fee_rate
    # The short signals on either side stay ordinary refused decisions.
    days = {d.assessment.decision_ms // DAY * DAY for d in trace.decisions}
    assert first not in days and {fx.START, first + DAY} <= days
    # A flat run has no drawdown or return variance to measure; its structure is whole.
    assert strategy_report(trace, adapter_pin=PIN).structural_complete


def test_opportunity_records_keep_every_refusal_reason():
    hole = fx.START + 8 * HOUR
    market = masked(fx.market("BTCUSDT", fx.downtrend, 2), "spot", (8,))
    trace = replay_strategy(fx.run("spot_trend", 2), (market,))
    report = strategy_report(trace, adapter_pin=PIN)
    (row,) = [o for o in report.opportunities if o.timestamp_ms == hole + HOUR and o.reason]
    event = next(e for e in trace.evidence if e.event_id == row.id)
    assert "missing_hourly_bar" in event.reasons and len(event.reasons) > 1
    assert row.reasons == event.reasons and row.reason == event.reasons[0]
    assert set(row.reasons) <= {r for g in report.opportunity_episodes for r in g.reasons}
    # The 4h bucket with the hole is dropped: the four hours reading it have no signal.
    (episode,) = trace.unavailable
    assert (episode.record.first_ms, episode.record.last_ms) == (hole + 4 * HOUR, hole + 7 * HOUR)
    assert "missing_four_hour_bar" in episode.record.reasons
    # The bundle keeps one record per run of identical refusals; any change of the
    # disposition, or an hour with another record, closes a run.
    spans = [
        ((r.first_ms - fx.START) // HOUR, (r.last_ms - fx.START) // HOUR, r.reasons[0])
        for r in evidence_records(trace).decisions
    ]
    assert spans == [
        (0, 8, "short_component_disabled"),
        (9, 9, "missing_hourly_bar"),
        (10, 11, "short_component_disabled"),
        (12, 15, "missing_four_hour_bar"),
        (16, 47, "short_component_disabled"),
    ]


def journal_of(trace):
    from crypto_grid_bot.combined.evidence import Evidence

    journal = Evidence()
    for event in trace.evidence:
        journal.record(event)
    return journal


def test_replay_evidence_records_round_trip_through_the_bundle(tmp_path):
    from crypto_grid_bot.combined.artifacts import read_bundle, write_bundle

    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    records = evidence_records(trace)
    assert records.assessments and records.intents and records.decisions and records.lifecycles
    decided = trace.decisions[0]
    assert records.intents[0].intent == decided.result.intent
    assert records.intents[0].assessment_id == decided.assessment.assessment_id
    assert records.decisions[0] == replace(decided.result.record, source_refs=(records.run.ref,))
    assert records.run.source_refs == trace.run.source_refs and records.run.issues == ()
    receipt = write_bundle(
        tmp_path, "replay", journal_of(trace), {"synthetic": True}, records=records
    )
    bundle = read_bundle(receipt.directory, expected_receipt_sha256=receipt.receipt_sha256)
    assert bundle.records == records and bundle.events == trace.evidence


def test_identical_hourly_refusals_are_one_compact_record(tmp_path):
    from crypto_grid_bot.combined.artifacts import write_bundle

    # Long registered source refs would dominate if every record repeated them.
    refs = tuple(f"sha256:{i:064x}" for i in range(20))
    run = replace(fx.run("spot_trend", 6), source_refs=refs)
    trace = replay_strategy(run, (fx.market("BTCUSDT", fx.downtrend, 6),))
    assert trace.failure is None and len(trace.decisions) == 6 * 24
    assert {(d.result.record.phase, d.result.record.reasons) for d in trace.decisions} == {
        ("qualified", ("short_component_disabled",))
    }
    records = evidence_records(trace)
    (record,) = records.decisions
    (assessment,) = records.assessments
    assert (record.first_ms, record.last_ms) == (fx.START, fx.START + 6 * DAY - HOUR)
    assert record == replace(
        trace.decisions[0].result.record, last_ms=record.last_ms, source_refs=(records.run.ref,)
    )
    assert assessment.assessment_id == record.assessment_id and records.intents == ()
    assert assessment.source_refs[0] == records.run.ref and refs[0] not in assessment.source_refs
    # The funnel journal still keeps every hour.
    assert len(trace.evidence) == 2 * 6 * 24
    receipt = write_bundle(tmp_path, "compact", journal_of(trace), {}, records=records)
    names = (
        "assessments",
        "decision_records",
        "intents",
        "lifecycles",
        "recoveries",
        "symbol_gaps",
    )
    lines = [
        line
        for name in names
        for line in (receipt.directory / f"{name}.jsonl").read_bytes().splitlines()
    ]
    assert len(lines) == 3  # one assessment, one decision record, one gap table
    assert max(len(line) for line in lines) < 1500
    assert len((receipt.directory / "run.jsonl").read_bytes().splitlines()) == 1


def test_a_no_signal_record_and_its_gap_table_round_trip(tmp_path):
    from crypto_grid_bot.combined.artifacts import read_bundle, write_bundle

    # The window's second day keeps 19 of its 24 hours, so it has no daily bar.
    missing = fx.START + DAY
    market = masked(fx.market("BTCUSDT", fx.downtrend, 4), "spot", range(24, 29))
    trace = replay_strategy(fx.run("spot_trend", 4), (market,))
    records = evidence_records(trace)
    (gap,) = [
        r
        for r in records.decisions
        if r.size_unavailable == "no_signal" and "missing_daily_bar" in r.reasons
    ]
    assert (gap.side, gap.owner, gap.executable_quantity) == (0, None, None)
    assert (gap.first_ms, gap.last_ms) == (missing + DAY, missing + 2 * DAY - HOUR)
    first = next(a for a in records.assessments if a.assessment_id == gap.assessment_id)
    assert not first.available and "missing_daily_bar" in first.reasons
    # The assessment's own gaps were moved to the symbol's table, saved once.
    (table,) = records.symbol_gaps
    (episode,) = [e for e in trace.unavailable if "missing_daily_bar" in e.record.reasons]
    assert episode.assessment.daily_gaps == ((missing, missing + DAY),)
    assert first.daily_gaps == () and table.daily_gaps == ((missing, missing + DAY),)
    receipt = write_bundle(tmp_path, "gap", journal_of(trace), {}, records=records)
    assert read_bundle(receipt.directory).records == records


def test_an_unmarked_open_lifecycle_stays_marked_in_the_saved_records():
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    # Without retained marks the open lifecycle is valued at its last fill price.
    records = evidence_records(replace(trace, observations=()))
    (life,) = records.lifecycles
    assert life.status == "open_marked"
    assert records.run.issues == (f"unmarked_open_lifecycle:{life.id}",)
