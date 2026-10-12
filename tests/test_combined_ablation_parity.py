"""Each ablation replays combined exactly until its own switch binds (synthetic inputs).

In the parity window no ablation's switch binds, so every ablation's trace equals the
combined trace apart from the arm's name. Each binding window shows the one difference
its switch makes.
"""

import math
from dataclasses import replace
from decimal import Decimal as D

import combined_market_fixtures as fx
import pytest
from test_combined_strategy_replay import crash_after, fills, payments, reverse_after

from crypto_grid_bot.combined.assessment import AssessmentSeries
from crypto_grid_bot.combined.recovery import RecoveryState
from crypto_grid_bot.combined.strategy_replay import replay_strategy
from crypto_grid_bot.strategy.perception import TrendState

HOUR = fx.HOUR
DAY = fx.DAY
TREND = frozenset({"spot_trend", "futures_trend"})
PARITY_DAYS = 4


def relabeled(trace):
    """``trace`` under the combined arm's name, the only identity an arm sets."""
    return replace(trace, run=replace(trace.run, arm="combined"))


def with_funding_admission(trace):
    """``trace`` with the funding switch that its intents carry to admission set back on."""

    def restored(result):
        intent, inputs = result.intent, result.venue_inputs
        return replace(
            result,
            intent=None if intent is None else replace(intent, funding_admission=True),
            venue_inputs=None if inputs is None else replace(inputs, funding_admission=True),
        )

    return replace(
        trace, decisions=tuple(replace(d, result=restored(d.result)) for d in trace.decisions)
    )


def hour_of(stamp):
    return (stamp - fx.START) // HOUR


def trend_with_pullbacks(rate, pullback, base=100.0):
    """``rate`` per hour for 108 hours, then ``pullback`` per hour for 36, repeating.

    The pullbacks hold the daily RSI(14) between 25 and 75 while each 108-hour leg
    drives the 4h RSI beyond that band.
    """

    def path(i: int) -> float:
        cycles, hour = divmod(i, 144)
        legs = cycles * 108 + min(hour, 108)
        pullbacks = cycles * 36 + max(0, hour - 108)
        return base * (1 + rate) ** legs * (1 + pullback) ** pullbacks

    return path


def parity_markets():
    """A long, a short and a grid that trade without binding any ablation's switch."""
    return (
        fx.market(
            "BTCUSDT", trend_with_pullbacks(0.0006, -0.001), PARITY_DAYS, futures=True, flow=True
        ),
        fx.market(
            "ETHUSDT",
            trend_with_pullbacks(-0.0006, 0.001, 400.0),
            PARITY_DAYS,
            futures=True,
            flow=True,
        ),
        fx.market("SOLUSDT", fx.ranging, PARITY_DAYS, futures=True, flow=True),
    )


@pytest.fixture(scope="module")
def parity():
    markets = parity_markets()
    return markets, replay_strategy(fx.run("combined", PARITY_DAYS), markets)


def window_assessments(market, days):
    series = AssessmentSeries(market.symbol, market.spot.hourly, market.daily)
    return [series.at(t, t) for t in range(fx.START, fx.START + days * DAY, HOUR)]


def test_the_parity_window_trades_every_component_and_binds_no_switch(parity):
    markets, combined = parity
    assert combined.failure is None
    booked = {(e.fill.owner, e.fill.side, e.increase) for e in fills(combined)}
    assert booked >= {
        ("spot_trend", 1, True),
        ("futures_trend", -1, True),
        ("spot_grid", 1, True),
        ("spot_grid", -1, False),
    }
    # The held futures short settles funding, so the parity comparisons include it.
    assert payments(combined)
    # Continuation: every trend decision reads a daily RSI(14) inside the restored veto's
    # band, although a veto on the 4h RSI would refuse both the long and the short.
    trend = [d.assessment for d in combined.decisions if d.result.qualification.owner in TREND]
    assert trend and all(25 < a.daily_rsi < 75 for a in trend)
    assert any(a.daily == TrendState.UP and a.rsi >= 75 for a in trend)
    assert any(a.daily == TrendState.DOWN and a.rsi <= 25 for a in trend)
    # Short qualification: no coin ever reads a daily UNCLEAR with a 4h DOWN.
    assert not [
        a
        for market in markets
        for a in window_assessments(market, PARITY_DAYS)
        if a.daily == TrendState.UNCLEAR and a.four_hour == TrendState.DOWN
    ]
    admitted = [
        d.result.intent
        for d in combined.decisions
        if d.result.admission is not None and d.result.admission.accepted
    ]
    by_symbol = {market.symbol: market for market in markets}
    end = fx.START + PARITY_DAYS * DAY
    for intent in (i for i in admitted if i.owner in TREND):
        # Trailing: no trend holding moves two initial risks in its favor, where its
        # trail would activate, before the window ends.
        entry = next(
            e.fill for e in fills(combined) if e.increase and e.fill.symbol == intent.symbol
        )
        bars = [
            bar
            for bar in getattr(by_symbol[intent.symbol], intent.venue).hourly
            if entry.timestamp_ms <= bar.open_ms < end
        ]
        best = max(b.high for b in bars) if intent.side == 1 else min(b.low for b in bars)
        assert (best - entry.price) * intent.side < 2 * abs(entry.price - intent.stop)
    # Funding admission: each admitted futures intent receives the published funding.
    futures = [i for i in admitted if i.venue == "futures"]
    assert futures and all(i.funding_rate * i.side < 0 for i in futures)
    # Recovery: the drawdown never reaches the 30% lifetime stop.
    assert {o.snapshot.recovery.state for o in combined.observations} == {RecoveryState.NORMAL}


@pytest.mark.parametrize(
    "arm",
    [
        "combined_without_continuation",
        "combined_without_full_short_qualification",
        "combined_without_discretionary_trailing",
        "combined_without_recovery",
    ],
)
def test_an_ablation_whose_switch_never_binds_replays_combined_exactly(parity, arm):
    markets, combined = parity
    trace = replay_strategy(fx.run(arm, PARITY_DAYS), markets)
    assert trace.run.arm == arm
    # Every fill, mark, decision and evidence record, under the combined arm's name.
    assert relabeled(trace) == combined


def test_without_funding_admission_differs_from_combined_only_in_the_switch_it_carries(parity):
    markets, combined = parity
    arm = "combined_without_funding_admission"
    trace = relabeled(replay_strategy(fx.run(arm, PARITY_DAYS), markets))
    # Each futures decision carries the switch to its admission; nothing else differs.
    carried = [
        d.result
        for d in trace.decisions
        if d.result.intent is not None and d.result.intent.venue == "futures"
    ]
    assert carried
    assert not any(r.intent.funding_admission or r.venue_inputs.funding_admission for r in carried)
    assert trace != combined
    assert with_funding_admission(trace) == combined


def intraday_swing(i: int) -> float:
    """The fixture uptrend with a 2% swing over each UTC day: every daily close is higher
    (a daily RSI of 100) while the swing keeps the 4h RSI near 60."""
    return fx.uptrend(i) * (1 + 0.02 * math.sin(i * 2 * math.pi / 24))


def test_without_continuation_the_daily_rsi_vetoes_a_long_combined_takes():
    market = fx.market("BTCUSDT", intraday_swing, 3, futures=True)
    combined = replay_strategy(fx.run("combined", 3), (market,))
    vetoed = replay_strategy(fx.run("combined_without_continuation", 3), (market,))
    assert combined.failure is None and vetoed.failure is None
    taken, refused = combined.decisions[0], vetoed.decisions[0]
    assert taken.assessment == refused.assessment
    first = taken.assessment
    assert first.decision_ms == fx.START and first.daily == first.four_hour == TrendState.UP
    # The daily RSI(14) is beyond the veto; the 4h RSI is not.
    assert first.daily_rsi >= 75 > first.rsi
    assert taken.result.admission.accepted
    assert [(e.fill.owner, e.fill.timestamp_ms) for e in fills(combined)][:1] == [
        ("spot_trend", fx.START)
    ]
    # The restored veto refuses that long, and every later one, for that reason alone.
    assert {d.result.qualification.reasons for d in vetoed.decisions} == {("legacy_rsi_veto",)}
    assert len(vetoed.decisions) == 3 * 24 and fills(vetoed) == []


def test_without_full_short_qualification_a_daily_unclear_4h_down_hour_is_shorted():
    # Nine days into a mirrored decline the 4h trend reads DOWN and the daily trend,
    # still UP at the window's start, turns UNCLEAR a day later.
    market = fx.market("BTCUSDT", reverse_after(fx.uptrend, -9 * 24), 2, futures=True)
    combined = replay_strategy(fx.run("combined", 2), (market,))
    ablated = replay_strategy(fx.run("combined_without_full_short_qualification", 2), (market,))
    assert combined.failure is None and ablated.failure is None
    # Combined reads every hour as conflicting directions: nothing is detected or traded.
    assert combined.decisions == () and fills(combined) == []
    (short,) = ablated.decisions
    unclear = short.assessment
    assert hour_of(unclear.decision_ms) == 24
    assert (unclear.daily, unclear.four_hour) == (TrendState.UNCLEAR, TrendState.DOWN)
    qualification = short.result.qualification
    assert (qualification.owner, qualification.side) == ("futures_trend", -1)
    assert qualification.allowed and short.result.admission.accepted
    assert [(e.fill.timestamp_ms, e.fill.venue, e.fill.side) for e in fills(ablated)] == [
        (unclear.decision_ms, "futures", -1)
    ]
    # Until that hour the two traces are the same.
    assert [o for o in combined.observations if o.timestamp_ms < unclear.decision_ms] == [
        o for o in ablated.observations if o.timestamp_ms < unclear.decision_ms
    ]


def test_without_discretionary_trailing_the_stop_never_trails():
    # A steep uptrend carries the hour-0 long past two initial risks, where the trail
    # activates; a 10% fall in bar 96 then reaches the trailed stop but not the initial.
    path = crash_after(lambda i: 100 * 1.002**i, 4 * 24, 0.1)
    market = fx.market("BTCUSDT", path, 5, futures=True)
    trailed = replay_strategy(fx.run("combined", 5), (market,))
    fixed = replay_strategy(fx.run("combined_without_discretionary_trailing", 5), (market,))
    assert trailed.failure is None and fixed.failure is None
    entry = fills(trailed)[0].fill
    initial_stop = trailed.decisions[0].result.intent.stop
    assert entry.owner == "spot_trend" and entry.timestamp_ms == fx.START
    # Combined exits at a stop above the initial one: the stop it executed had trailed.
    exit_fill = next(e for e in fills(trailed) if not e.increase)
    assert exit_fill.exit_reason == "stop" and exit_fill.fill.price > initial_stop
    # Without the trail the long keeps its initial stop, which no later price reaches.
    assert [e.fill for e in fills(fixed)] == [entry]
    end = fx.START + 5 * DAY
    assert min(b.low for b in market.spot.hourly if fx.START <= b.open_ms < end) > initial_stop


def test_without_funding_admission_a_short_paying_adverse_funding_is_admitted():
    # The short pays 1% of its notional every eight hours: three such settlements cost
    # more than a quarter of its stop risk.
    base = fx.market("ETHUSDT", fx.downtrend, 3, futures=True)
    market = replace(
        base, funding=fx.funding(fx.START - fx.HISTORY_DAYS * DAY, fx.START + 3 * DAY, "-.01")
    )
    filtered = replay_strategy(fx.run("combined", 3), (market,))
    admitted = replay_strategy(fx.run("combined_without_funding_admission", 3), (market,))
    assert filtered.failure is None and admitted.failure is None
    # At hour 0 no published record is recent enough: both arms refuse, filter or not.
    for trace in (filtered, admitted):
        assert trace.decisions[0].result.admission.reasons == ("funding_unavailable",)
    # From hour 1 the filter alone refuses every short; without it the first is admitted.
    assert {d.result.admission.reasons for d in filtered.decisions[1:]} == {("adverse_funding",)}
    assert fills(filtered) == []
    short = admitted.decisions[1]
    assert hour_of(short.assessment.decision_ms) == 1 and short.result.admission.accepted
    assert short.result.intent.funding_rate == D("-.01")
    assert [(e.fill.venue, e.fill.side, hour_of(e.fill.timestamp_ms)) for e in fills(admitted)] == [
        ("futures", -1, 1)
    ]
    # Held, it pays that funding at every settlement.
    assert payments(admitted) and all(p.amount < 0 for p in payments(admitted))


def gap_spike(market, hour, factor):
    """``market`` with both venues' bar at ``hour`` into the window scaled by ``factor``.

    That bar opens ``factor`` times the previous close, and the next bar opens back on
    the path. Spot daily bars follow their hours under the frozen rule.
    """
    stamp, scale = fx.START + hour * HOUR, D(factor)

    def spiked(rows):
        return tuple(
            replace(
                bar,
                open=bar.open * scale,
                high=bar.high * scale,
                low=bar.low * scale,
                close=bar.close * scale,
            )
            if bar.open_ms == stamp
            else bar
            for bar in rows
        )

    spot = spiked(market.spot.hourly)
    return replace(
        market,
        spot=replace(market.spot, hourly=spot),
        daily=fx.daily(spot),
        futures=replace(market.futures, hourly=spiked(market.futures.hourly)),
    )


def test_without_recovery_the_cooldown_never_restarts():
    # A 5x gap against the hour-1 futures short costs about 40% of equity at hour 12:
    # the 30% lifetime stop liquidates both holdings and a 24-hour cooldown begins.
    markets = (
        fx.market("BTCUSDT", fx.uptrend, 3, futures=True),
        gap_spike(fx.market("ETHUSDT", fx.downtrend, 3, futures=True), 12, 5),
    )
    restarted = replay_strategy(fx.run("combined", 3), markets)
    halted = replay_strategy(fx.run("combined_without_recovery", 3), markets)
    assert restarted.failure is None and halted.failure is None
    spike, restart = fx.START + 12 * HOUR, fx.START + 36 * HOUR
    # The same liquidation in both arms: every fill before the restart is identical.
    assert [e for e in fills(restarted) if e.fill.timestamp_ms < restart] == fills(halted)
    exits = [e for e in fills(halted) if not e.increase]
    assert {e.fill.symbol for e in exits} == {"BTCUSDT", "ETHUSDT"}
    assert all(e.fill.timestamp_ms == spike and "lifetime_stop" in e.exit_reason for e in exits)
    # Every mark before the restart is the same, its recovery reason included: a submit
    # that repeats the last input (no automatic recovery) reports the cooldown it is in,
    # exactly as a qualified submit that re-reads it does.
    assert [o for o in restarted.observations if o.timestamp_ms < restart] == [
        o for o in halted.observations if o.timestamp_ms < restart
    ]
    at_spike = {
        (o.snapshot.recovery.state, o.snapshot.recovery.reason)
        for o in halted.observations
        if o.timestamp_ms == spike
    }
    assert (RecoveryState.COOLDOWN, "cooldown") in at_spike
    assert (RecoveryState.COOLDOWN, "awaiting_liquidation") not in at_spike
    # A day into the cooldown combined restarts at a quarter allowance and buys again.
    at_restart = {
        (o.snapshot.recovery.state, o.snapshot.recovery.reason)
        for o in restarted.observations
        if o.timestamp_ms == restart
    }
    assert (RecoveryState.RECOVERY25, "qualified_restart") in at_restart
    increases = [e.fill for e in fills(restarted) if e.increase and e.fill.timestamp_ms > spike]
    assert [(f.symbol, f.timestamp_ms) for f in increases] == [("BTCUSDT", restart)]
    # Without recovery the account never restarts: it stays in cooldown to the window's
    # end, and the risk check refuses every entry after the spike, to the last hour.
    later = {
        (o.snapshot.recovery.state, o.snapshot.recovery.reason)
        for o in halted.observations
        if o.timestamp_ms >= restart
    }
    assert later == {(RecoveryState.COOLDOWN, "restart_unqualified")}
    assert not [e for e in fills(halted) if e.increase and e.fill.timestamp_ms > spike]
    checked = [
        d
        for d in halted.decisions
        if d.assessment.decision_ms > spike and d.result.admission is not None
    ]
    assert hour_of(checked[-1].assessment.decision_ms) == 3 * 24 - 1
    assert all(d.result.admission.reasons == ("risk_halted",) for d in checked)
