"""Recovery records of one replay: the liquidation, each cooldown, each restart's episode.

The traces carry recovery states produced by the real controller from scripted equity,
so the records are judged against the transitions the engine can actually make.
"""

from dataclasses import replace
from decimal import Context, localcontext
from decimal import Decimal as D
from fractions import Fraction

import combined_market_fixtures as fx
from test_combined_engine import RULE, candidate
from test_combined_risk import intent

from crypto_grid_bot.combined.account import AccountSnapshot, FillEvent, PositionSnapshot
from crypto_grid_bot.combined.engine import EngineSnapshot, PortfolioEngine, Quote
from crypto_grid_bot.combined.recovery import Recovery, RecoveryState
from crypto_grid_bot.combined.replay_records import (
    gross_leverage,
    lifecycle_contributions,
    recovery_episodes,
    strategy_disclosures,
    strategy_report,
)
from crypto_grid_bot.combined.report import EquityPoint, analyze
from crypto_grid_bot.combined.strategy_replay import (
    NativeObservation,
    ReplayRun,
    StrategyTrace,
    TraceFill,
    replay_strategy,
)

HOUR = 3_600_000
REFS = ("sha256:run",)


def step(hours, equity, *, flat=True, ok=True):
    """One scripted mark: when, equity, whether positions are flat, accounting integrity."""
    return hours * HOUR, D(equity), flat, ok


def trace_of(*steps):
    controller = Recovery()
    observations = []
    for index, (stamp, equity, flat, ok) in enumerate(steps):
        decision = controller.update(stamp, equity, flat, True, ok)
        account = AccountSnapshot(equity, (), equity, D(0), D(0), D(0), D(0), ok, ())
        snapshot = EngineSnapshot(stamp, account, decision, (), (), False, equity)
        observations.append(
            NativeObservation(stamp, f"obs-{index}", "frame", "phase", f"event-{index}", snapshot)
        )
    run = ReplayRun("combined", "synthetic", D(100), 0, steps[-1][0], REFS)
    return StrategyTrace(
        run, tuple(observations), (), (), (), (), (), (), (), (), (), (), (), (), (), (), (), None
    )


# Two restarts: a 30% trigger with positions open, their liquidation, a 24h cooldown,
# a restart whose 3% stop falls from its own peak, another cooldown and restart, then
# a half allowance and normal restoration.
SEQUENCE = (
    step(0, 100),  # obs-0 Normal; the lifetime peak
    step(1, 90),  # obs-1 Normal
    step(2, 70, flat=False),  # obs-2 lifetime drawdown 30%: Closing
    step(3, 69, flat=False),  # obs-3 still liquidating
    step(4, 68),  # obs-4 flat: Cooldown begins
    step(16, 68),  # obs-5 Cooldown
    step(28, 68),  # obs-6 24 hours flat, qualified: restart at the 25% allowance
    step(29, 80),  # obs-7 the episode's own peak
    step(30, "77.6"),  # obs-8 3% below that peak: stop, Cooldown
    step(40, "77.6"),  # obs-9 Cooldown
    step(54, "77.6"),  # obs-10 restart at the 25% allowance
    step(55, 86),  # obs-11 lifetime drawdown 14%: half allowance
    step(56, 91),  # obs-12 lifetime drawdown 9%: normal restored
    step(57, 92),  # obs-13 Normal
)


def shape(rows):
    return [
        (r.kind, r.start_observation_id, r.end_observation_id, r.end_reason)
        for r in recovery_episodes(trace_of(*rows))
    ]


def test_each_restart_is_its_own_episode_beside_the_liquidation_and_both_cooldowns():
    assert shape(SEQUENCE) == [
        ("liquidation", "obs-2", "obs-4", "liquidated"),
        ("cooldown", "obs-4", "obs-6", "restarted"),
        ("episode", "obs-6", "obs-8", "episode_stop"),
        ("cooldown", "obs-8", "obs-10", "restarted"),
        ("episode", "obs-10", "obs-12", "normal_restored"),
    ]


def test_every_record_is_priced_from_its_start_to_its_end_observation():
    trace = trace_of(*SEQUENCE)
    rows = recovery_episodes(trace)
    assert [(r.start_ms // HOUR, r.end_ms // HOUR) for r in rows] == [
        (2, 4),
        (4, 28),
        (28, 30),
        (30, 54),
        (54, 56),
    ]
    points = tuple(
        EquityPoint(o.timestamp_ms, o.snapshot.account.equity, o.id, REFS)
        for o in trace.observations
    )
    report = analyze(D(100), points, (), (), rows, REFS)
    assert not [issue for issue in report.issues if "recovery" in issue]
    assert [(c.episode.kind, c.marked_change) for c in report.recovery_changes] == [
        ("liquidation", D(-2)),
        ("cooldown", D(0)),
        ("episode", D("9.6")),
        ("cooldown", D(0)),
        ("episode", D("13.4")),
    ]


def test_the_half_allowance_stays_inside_the_episode_that_earned_it():
    trace = trace_of(*SEQUENCE)
    assert trace.observations[11].snapshot.recovery.state == RecoveryState.RECOVERY50
    episodes = [r for r in recovery_episodes(trace) if r.kind == "episode"]
    assert len(episodes) == 2
    second = episodes[1]
    assert (second.start_observation_id, second.end_observation_id) == ("obs-10", "obs-12")
    assert (second.equity_start, second.equity_end) == (D("77.6"), D(91))


def test_records_have_unique_ids_and_cite_the_run_sources():
    rows = recovery_episodes(trace_of(*SEQUENCE))
    ids = [r.id for r in rows]
    assert len(set(ids)) == len(ids) == 5
    assert ids[0] == "recovery:liquidation:obs-2" and ids[2] == "recovery:episode:obs-6"
    assert all(r.source_refs == REFS for r in rows)


def test_an_episode_running_at_the_window_end_ends_at_the_last_observation():
    rows = recovery_episodes(trace_of(*SEQUENCE[:12]))
    last = rows[-1]
    assert (last.kind, last.start_observation_id, last.end_observation_id) == (
        "episode",
        "obs-10",
        "obs-11",
    )
    assert last.end_reason == "window_end"
    assert (last.end_ms, last.equity_end) == (55 * HOUR, D(86))


def test_a_stretch_begun_at_the_last_observation_is_still_a_record():
    rows = recovery_episodes(trace_of(*SEQUENCE[:3]))
    assert [(r.kind, r.start_observation_id, r.end_observation_id) for r in rows] == [
        ("liquidation", "obs-2", "obs-2")
    ]
    assert rows[0].end_reason == "window_end" and rows[0].equity_end == rows[0].equity_start


def test_a_trigger_while_flat_has_nothing_to_liquidate():
    rows = recovery_episodes(trace_of(step(0, 100), step(1, 70), step(2, 70)))
    assert [(r.kind, r.start_observation_id, r.end_reason) for r in rows] == [
        ("cooldown", "obs-1", "window_end")
    ]


def test_positions_reappearing_in_a_cooldown_start_another_liquidation():
    rows = shape(
        (step(0, 100), step(1, 70, flat=False), step(2, 70), step(3, 70, flat=False), step(4, 70))
    )
    assert rows == [
        ("liquidation", "obs-1", "obs-2", "liquidated"),
        ("cooldown", "obs-2", "obs-3", "liquidation_incomplete"),
        ("liquidation", "obs-3", "obs-4", "liquidated"),
        ("cooldown", "obs-4", "obs-4", "window_end"),
    ]


def test_a_terminal_failure_ends_what_it_interrupts_and_stays_recorded():
    rows = shape(
        (step(0, 100), step(1, 70, flat=False), step(2, 69, flat=False, ok=False), step(3, 69))
    )
    assert rows == [
        ("liquidation", "obs-1", "obs-2", "terminal"),
        ("terminal", "obs-2", "obs-3", "window_end"),
    ]


def test_capital_exhaustion_is_a_terminal_record_opened_at_the_exhausted_mark():
    trace = trace_of(step(0, 100), step(1, 40, flat=False), step(2, -5, flat=False), step(3, -5))
    assert trace.observations[2].snapshot.recovery.reason == "capital_exhausted"
    rows = recovery_episodes(trace)
    assert [(r.kind, r.start_observation_id, r.end_observation_id, r.end_reason) for r in rows] == [
        ("liquidation", "obs-1", "obs-2", "terminal"),
        ("terminal", "obs-2", "obs-3", "window_end"),
    ]
    assert rows[1].equity_start == D(-5)
    points = tuple(
        EquityPoint(o.timestamp_ms, o.snapshot.account.equity, o.id, REFS)
        for o in trace.observations
    )
    report = analyze(D(100), points, (), (), rows, REFS)
    assert not [issue for issue in report.issues if "recovery" in issue]
    # The liquidation into exhaustion keeps its return; the terminal stretch has none.
    assert [(c.marked_change, c.return_fraction) for c in report.recovery_changes] == [
        (D(-45), D("-1.125")),
        (D(0), None),
    ]


def exhausted_trace():
    """A futures short whose mark gaps up thirteenfold at hour 30: equity below zero."""
    from test_combined_strategy_replay import gapped_market

    market = gapped_market("BTCUSDT", fx.downtrend, 2, 30, -12, futures=True)
    return replay_strategy(fx.run("futures_trend", 2), (market,))


def test_a_replay_that_exhausts_capital_reports_its_terminal_record():
    trace = exhausted_trace()
    # The replay itself stops at the exhausting boundary, as it always did.
    assert trace.failure == "boundary_safety_failure"
    exhausted = next(o for o in trace.observations if o.snapshot.account.equity <= 0)
    assert exhausted.snapshot.recovery.state == RecoveryState.TERMINAL
    assert any(o.snapshot.liquidation for o in trace.observations)
    (terminal,) = recovery_episodes(trace)
    assert (terminal.kind, terminal.start_observation_id, terminal.end_reason) == (
        "terminal",
        exhausted.id,
        "window_end",
    )
    assert terminal.equity_start == exhausted.snapshot.account.equity < 0
    # The report keeps the record instead of refusing its nonpositive opening.
    report = strategy_report(trace, adapter_pin="0" * 64)
    (change,) = report.recovery_changes
    assert change.episode == terminal and change.return_fraction is None
    assert Fraction(change.marked_change) == Fraction(terminal.equity_end) - Fraction(
        terminal.equity_start
    )
    assert report.final_equity < 0 and not report.complete
    assert {"replay_failure:boundary_safety_failure", "nonpositive_equity_observation"} <= set(
        report.issues
    )
    assert not [issue for issue in report.issues if "recovery" in issue]


def test_a_run_that_never_left_normal_has_no_recovery_records():
    assert recovery_episodes(trace_of(step(0, 100), step(1, 99), step(2, 100))) == ()


# Excursions: each lifecycle's peak marked gross P&L over its own retained marks.


def held(index, holdings):
    """Observation ``obs-<index>`` holding ``{symbol: (signed quantity, mark)}``."""
    positions = tuple(
        PositionSnapshot(
            symbol, "spot_trend", "spot", D(q), D(0), D(0), D(m), "caller", None, D(0), ()
        )
        for symbol, (q, m) in sorted(holdings.items())
    )
    account = AccountSnapshot(D(0), positions, D(100), D(0), D(0), D(0), D(0), True, ())
    decision = Recovery().update(index * HOUR, D(100), not positions, True, True)
    snapshot = EngineSnapshot(index * HOUR, account, decision, (), (), False, D(100))
    return NativeObservation(index * HOUR, f"obs-{index}", "path", "low", f"e-{index}", snapshot)


def fill(name, index, symbol, side, quantity, price, *, increase):
    event = FillEvent(
        name, index * HOUR, symbol, "spot_trend", "spot", side, D(quantity), D(price), D(0)
    )
    return TraceFill(event, increase, None if increase else "stop", None)


def traded(observations, events):
    run = ReplayRun("spot_trend", "synthetic", D(100), 0, len(observations) * HOUR, REFS)
    return StrategyTrace(
        run,
        tuple(observations),
        (),
        tuple(events),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        None,
    )


# BTC: long 2 at 100, marks 110 / 125 / 105, sold at 108; later long 1 at 200, marked 190.
# ETH: short 1 at 50, marks 45 / 48 / 55, bought back at 55: it surrenders its whole gain.
TRADES = (
    (held(0, {}), None),
    (held(1, {"BTCUSDT": (2, 100)}), fill("b1", 1, "BTCUSDT", 1, 2, 100, increase=True)),
    (
        held(2, {"BTCUSDT": (2, 110), "ETHUSDT": (-1, 50)}),
        fill("e1", 2, "ETHUSDT", -1, 1, 50, increase=True),
    ),
    (held(3, {"BTCUSDT": (2, 125), "ETHUSDT": (-1, 45)}), None),
    (held(4, {"BTCUSDT": (2, 105), "ETHUSDT": (-1, 48)}), None),
    (held(5, {"ETHUSDT": (-1, 55)}), fill("b2", 5, "BTCUSDT", -1, 2, 108, increase=False)),
    (held(6, {}), fill("e2", 6, "ETHUSDT", 1, 1, 55, increase=False)),
    (held(7, {"BTCUSDT": (1, 200)}), fill("b3", 7, "BTCUSDT", 1, 1, 200, increase=True)),
    (held(8, {"BTCUSDT": (1, 190)}), None),
)


def trades(count=None):
    """Every booked fill, with the first ``count`` observations (all by default)."""
    rows = TRADES[:count]
    return traded([o for o, _ in rows], [e for _, e in TRADES if e is not None])


def excursions(trace, issues=None):
    return {
        row.id: (row.gross_pnl, row.mfe, row.giveback)
        for row in lifecycle_contributions(trace, issues)
    }


def test_excursion_is_the_peak_marked_gross_and_surrender_what_the_exit_gave_back():
    assert excursions(trades()) == {
        # Peak 2 x (125 - 100) = 50; sold for a gross 16, so 34 of the peak is surrendered.
        "lifecycle:BTCUSDT:b1": (D(16), D(50), D(34)),
        # Peak 50 - 45 = 5; bought back at a loss: the whole gain is surrendered, not 10.
        "lifecycle:ETHUSDT:e1": (D(-5), D(5), D(5)),
        # Never above its entry: no excursion and nothing surrendered; still open.
        "lifecycle:BTCUSDT:b3": (D(-10), D(0), D(0)),
    }


def test_marks_outside_a_lifecycle_never_reach_its_excursion():
    # The later BTC lifecycle's marks (200, 190) are above the first one's peak mark.
    _, mfe, _ = excursions(trades())["lifecycle:BTCUSDT:b1"]
    assert mfe == D(50) < 2 * (D(200) - 100)


def test_a_fill_no_retained_mark_shows_leaves_its_excursion_unknown():
    issues: list[str] = []
    rows = excursions(trades(count=7), issues)  # b3 booked, but no mark holds it
    assert rows["lifecycle:BTCUSDT:b3"][1:] == (None, None)
    assert issues == ["unmarked_open_lifecycle:lifecycle:BTCUSDT:b3"]
    assert rows["lifecycle:BTCUSDT:b1"][1:] == (D(50), D(34))


def test_a_replayed_stop_trade_reports_its_excursion_from_its_own_marks():
    import combined_market_fixtures as fx
    from test_combined_strategy_replay import crash_after

    trace = replay_strategy(
        fx.run("spot_trend", 2), (fx.market("BTCUSDT", crash_after(fx.uptrend, 12, 0.15), 2),)
    )
    report = strategy_report(trace, adapter_pin="0" * 64)
    row = report.contributions[0]
    assert row.status == "closed" and row.exit_reason == "stop"
    assert "mfe" not in report.unknown_fields and "giveback" not in report.unknown_fields
    # Independently: the best mark of the first contiguous holding, entry to exit.
    entry = next(e.fill for e in trace.events if isinstance(e, TraceFill) and e.increase)
    marks = [
        next((p.mark for p in o.snapshot.account.positions if p.symbol == "BTCUSDT"), None)
        for o in trace.observations
    ]
    first = next(i for i, mark in enumerate(marks) if mark is not None)
    last = next(i for i in range(first, len(marks)) if marks[i] is None)
    peak = max(D(0), entry.quantity * (max(marks[first:last]) - entry.price))
    assert row.mfe == peak > 0
    assert Fraction(row.giveback) == Fraction(row.mfe) - max(Fraction(row.gross_pnl), 0) > 0


# Maximum observed gross leverage: gross notional over equity at every engine mark.

SHORTS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LINKUSDT", "DOTUSDT")


def gapped_shorts():
    """Reviewer probe: eight futures shorts of 20 at 100 (1.6x gross), then a 20% gap up.

    The two engine marks: right after the entries, and the gap's opening valuation, the
    mark a path records before it drains anything.
    """
    engine = PortfolioEngine(D(10000))
    groups = tuple((symbol, symbol) for symbol in SHORTS)
    rules = {symbol: RULE for symbol in SHORTS}
    quotes = {symbol: Quote(D(100), 0) for symbol in SHORTS}
    entries = []
    for symbol in SHORTS:
        order = intent(
            symbol,
            symbol,
            owner="futures_trend",
            venue="futures",
            side=-1,
            stop=D(101),
            requested_quantity=D(20),
            fee_rate=D(0),
            slippage_rate=D(0),
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
            correlation_group=symbol,
        )
        assert engine.submit(order, candidate(order), quotes, rules, groups).quantity == 20
        sold = FillEvent(symbol, 0, symbol, order.owner, order.venue, -1, D(20), D(100), D(0))
        entries.append((order.intent_id, sold))
    entered = engine.settle("entries", 0, quotes, rules, increases=tuple(entries))
    gap = engine.observe(HOUR, {symbol: Quote(D(120), HOUR) for symbol in SHORTS}, rules)
    return traded(
        [
            NativeObservation(0, "obs-0", "frame", "settled", "entries", entered),
            NativeObservation(HOUR, "obs-1", "path", "open", "gap", gap),
        ],
        (),
    )


def test_the_maximum_gross_leverage_counts_a_gap_mark_before_any_drain():
    # 8 * 20 * 120 = 19200 of gross against 10000 - 8 * 20 * 20 = 6800 of equity: 48/17.
    assert gross_leverage(gapped_shorts()) == (Fraction(48, 17), HOUR)


def test_gross_above_the_absolute_cap_is_disclosed_with_its_first_mark():
    notes = [n for n in strategy_disclosures(gapped_shorts()) if n.startswith("gross_above")]
    with localcontext(Context(prec=60)):
        shown = D(48) / D(17)  # a ratio as reports render one: 60 significant digits
    assert notes == [f"gross_above_absolute_cap:{shown}:{HOUR}"]


def test_a_mark_with_exposure_and_no_positive_equity_has_unbounded_leverage():
    healthy, later = held(0, {"BTCUSDT": (1, 100)}), held(1, {"BTCUSDT": (1, 100)})
    account = replace(later.snapshot.account, free_cash=D(-100), equity=D(0))
    broke = replace(later, snapshot=replace(later.snapshot, account=account))
    trace = traded([healthy, broke], ())
    assert gross_leverage(trace) == (None, HOUR)
    assert f"gross_above_absolute_cap:unbounded:{HOUR}" in strategy_disclosures(trace)


def test_a_replay_report_carries_its_maximum_gross_leverage_over_every_mark():
    trace = replay_strategy(fx.run("spot_trend", 2), (fx.market("BTCUSDT", fx.uptrend, 2),))
    report = strategy_report(trace, adapter_pin="0" * 64)
    expected = max(
        sum(
            (abs(Fraction(p.quantity)) * Fraction(p.mark) for p in o.snapshot.account.positions),
            Fraction(0),
        )
        / Fraction(o.snapshot.account.equity)
        for o in trace.observations
    )
    assert report.max_gross_leverage == expected and 0 < expected <= Fraction(8, 5)
    assert not [n for n in report.disclosures if n.startswith("gross_above_absolute_cap")]
    assert report.complete, report.issues
