"""Routing uses affirmative evidence and never invents futures fallback."""

from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_combined_assessment import DAY, HOUR, bars

from crypto_grid_bot.combined.assessment import assess
from crypto_grid_bot.combined.routing import RoutingContext, qualify
from crypto_grid_bot.strategy.perception import TrendState


def market():
    return assess("BTCUSDT", 60 * DAY, bars(60 * 24, HOUR), bars(60, DAY, "0.24"), 60 * DAY)


def test_strong_high_rsi_trend_prefers_spot():
    result = qualify(market(), RoutingContext(spot_executable=True))
    assert result.owner == "spot_trend"
    assert result.side == 1
    assert result.allowed


def test_unknown_spot_executability_cannot_create_futures_fallback():
    result = qualify(market(), RoutingContext())
    assert not result.allowed
    assert "spot_executability_unknown" in result.reasons


def test_futures_fallback_requires_explicit_spot_failure():
    result = qualify(market(), RoutingContext(spot_executable=False))
    assert result.allowed and result.owner == "futures_trend"


def test_continuation_ablation_restores_rsi_veto():
    result = qualify(market(), RoutingContext(spot_executable=True, continuation=False))
    assert not result.allowed
    assert "legacy_rsi_veto" in result.reasons


@pytest.mark.parametrize(
    "trend,daily_rsi,four_hour_rsi,vetoed",
    [
        (TrendState.UP, D(76), D(60), True),
        (TrendState.UP, D(60), D(80), False),
        (TrendState.DOWN, D(24), D(40), True),
        (TrendState.DOWN, D(40), D(24), False),
    ],
)
def test_continuation_ablation_veto_reads_daily_rsi_not_four_hour(
    trend, daily_rsi, four_hour_rsi, vetoed
):
    # Ruling on spec lines 84-85: the restored frozen veto read the daily RSI(14).
    assessment = replace(
        market(), daily=trend, four_hour=trend, daily_rsi=daily_rsi, rsi=four_hour_rsi
    )
    result = qualify(assessment, RoutingContext(spot_executable=True, continuation=False))
    assert ("legacy_rsi_veto" in result.reasons) is vetoed
    assert result.allowed is not vetoed


def test_continuation_ablation_refuses_without_daily_rsi_even_with_four_hour_rsi():
    warming = replace(market(), daily_rsi=None, rsi=D(50))
    ablation = qualify(warming, RoutingContext(spot_executable=True, continuation=False))
    assert not ablation.allowed and "rsi_unavailable" in ablation.reasons
    assert qualify(warming, RoutingContext(spot_executable=True)).allowed


def test_short_needs_both_bearish_timeframes_and_structure():
    bearish = replace(market(), daily=TrendState.DOWN, four_hour=TrendState.DOWN)
    result = qualify(bearish, RoutingContext())
    assert result.allowed and result.side == -1 and result.owner == "futures_trend"
    assert not qualify(replace(bearish, structure="conflict"), RoutingContext()).allowed


def test_short_ablation_never_allows_bullish_daily_context():
    context = RoutingContext(short_qualification=False)
    bearish = replace(market(), daily=TrendState.UNCLEAR, four_hour=TrendState.DOWN)
    assert qualify(bearish, context).allowed
    assert not qualify(replace(bearish, daily=TrendState.UP), context).allowed


def test_independent_blockers_preserved_and_extended_risk_halved():
    context = RoutingContext(spot_executable=True)
    assert qualify(replace(market(), extension=D("2.1")), context).risk_multiplier == D("0.5")
    result = qualify(replace(market(), extension=D(4), volatility_ratio=D(3)), context)
    assert not result.allowed
    assert {"extended_entry", "volatility_stress"} <= set(result.reasons)


def test_grid_flow_has_hysteresis_and_missing_flow_blocks():
    from crypto_grid_bot.combined.routing import FlowGate

    gate = FlowGate()
    assert not gate.update(D("0.44"))
    assert gate.update(D("0.45"))
    assert gate.update(D("0.41"))
    assert not gate.update(None)
    assert not gate.update(D("0.44"))


def test_range_grid_requires_available_flow_and_spot_size():
    ranged = replace(
        market(), daily=TrendState.RANGE, four_hour=TrendState.RANGE, structure="range"
    )
    assert not qualify(ranged, RoutingContext(spot_executable=True)).allowed
    result = qualify(ranged, RoutingContext(spot_executable=True, flow_allowed=True))
    assert result.allowed and result.owner == "spot_grid"


def test_unavailable_and_disabled_components_never_admitted():
    context = RoutingContext(spot_executable=True, spot_trend=False, futures_trend=False)
    assert not qualify(market(), context).allowed
    assert not qualify(
        replace(market(), available=False, reasons=("missing_hourly_bar",)), context
    ).allowed


@pytest.mark.parametrize(
    "field,value",
    [("spot_executable", "unknown"), ("short_qualification", None), ("flow_allowed", "false")],
)
def test_malformed_context_is_rejected(field, value):
    with pytest.raises(ValueError, match="context"):
        qualify(market(), RoutingContext(**{field: value}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("extension", D(-1)),
        ("volatility_ratio", D(-1)),
        ("volatility_ratio", "1"),
        ("extension", D("sNaN")),
    ],
)
def test_malformed_measurements_fail_closed(field, value):
    assert not qualify(
        replace(market(), **{field: value}), RoutingContext(spot_executable=True)
    ).allowed


def test_flow_uses_only_fifteen_contiguous_completed_minutes():
    from crypto_grid_bot.combined.routing import completed_flow

    history = bars(20, 60_000)
    assert completed_flow(history, 15 * 60_000) == D("0.5")
    corrupted_future = history[:15] + [replace(history[15], volume=D("NaN"))]
    assert completed_flow(corrupted_future, 15 * 60_000) == D("0.5")
    assert completed_flow(history[:14], 15 * 60_000) is None
    assert completed_flow(history[:7] + history[8:], 15 * 60_000) is None
    assert (
        completed_flow([replace(b, volume=D(0), taker_buy_base=D(0)) for b in history], 15 * 60_000)
        is None
    )


def test_flow_is_volume_weighted_and_rejects_bad_completed_data():
    from crypto_grid_bot.combined.routing import completed_flow

    history = bars(15, 60_000)
    history[-1] = replace(history[-1], volume=D(2), taker_buy_base=D(2))
    assert completed_flow(history, 15 * 60_000) == D(9) / 16
    assert completed_flow(history + [history[-1]], 15 * 60_000) is None
    history[-1] = replace(history[-1], taker_buy_base=D(3))
    assert completed_flow(history, 15 * 60_000) is None


MINUTE = 60_000


def flow_minutes(first_ms, *spans):
    """One-minute flow bars from ``first_ms``: ``(count, share)`` spans, volume 10 each;
    a ``None`` share leaves its minutes missing."""
    from crypto_grid_bot.backtest.klines import Kline

    rows, stamp = {}, first_ms
    for count, share in spans:
        for _ in range(count):
            if share is not None:
                buy = D(10) * D(share)
                rows[stamp] = Kline(stamp, D(1), D(1), D(1), D(1), D(10), D(10), buy)
            stamp += MINUTE
    return rows


def test_the_minute_flow_gate_keeps_its_hysteresis_minute_by_minute():
    from crypto_grid_bot.combined.routing import MinuteFlowGate

    # A minute's value is the taker-buy share of the fifteen completed minutes before it.
    start = 15 * MINUTE
    gate = MinuteFlowGate(flow_minutes(0, (15, ".42"), (20, ".6"), (20, ".42"), (5, ".1")), start)
    # Starts blocked, and .42 never unblocks it; nor do one or two .6 minutes (.432, .444).
    assert [gate.advance(start + k * MINUTE) for k in range(3)] == [True] * 3
    assert not gate.allowed
    # Three .6 minutes lift the share to (12 * .42 + 3 * .6) / 15 = .456 >= .45.
    assert not gate.advance(start + 3 * MINUTE) and gate.allowed
    # Back to .42 for twenty minutes: never below .40, so it stays open.
    assert not gate.advance(start + 40 * MINUTE) and gate.allowed
    # One .1 minute in the window gives (.1 + 14 * .42) / 15 < .40: blocked at once.
    assert gate.advance(start + 41 * MINUTE) and not gate.allowed


def test_the_minute_flow_gate_reports_a_block_anywhere_in_what_it_fed():
    from crypto_grid_bot.combined.routing import MinuteFlowGate

    gate = MinuteFlowGate(flow_minutes(0, (40, ".6"), (11, ".1"), (40, ".6")), 15 * MINUTE)
    assert not gate.advance(40 * MINUTE) and gate.allowed
    # Seven .1 minutes of fifteen block it at 47:00; at 62:00 only four remain and it is
    # open again. Fed through 70:00 it reports the block although it ends open.
    assert not gate.advance(46 * MINUTE) and gate.allowed
    assert gate.advance(47 * MINUTE) and not gate.allowed
    assert gate.advance(61 * MINUTE) and not gate.allowed
    assert not gate.advance(62 * MINUTE) and gate.allowed
    assert not gate.advance(80 * MINUTE)


def test_the_minute_flow_gate_refuses_a_call_that_feeds_nothing_new():
    from crypto_grid_bot.combined.routing import MinuteFlowGate

    # Nothing fed is nothing checked: a repeat must not read as "not blocked".
    gate = MinuteFlowGate(flow_minutes(0, (40, ".1")), 15 * MINUTE)
    assert gate.advance(20 * MINUTE) and not gate.allowed
    for through in (20 * MINUTE, 20 * MINUTE + 30_000, 19 * MINUTE, 0):
        with pytest.raises(ValueError, match="feeds no new minute"):
            gate.advance(through)
    assert gate.advance(21 * MINUTE)  # the refusals left the gate where it was
    empty = MinuteFlowGate({}, 15 * MINUTE)
    with pytest.raises(ValueError, match="feeds no new minute"):
        empty.advance(14 * MINUTE)
    assert empty.advance(30 * MINUTE)
    with pytest.raises(ValueError, match="feeds no new minute"):
        empty.advance(30 * MINUTE)


def test_a_missing_minute_blocks_every_minute_whose_window_it_falls_in():
    from crypto_grid_bot.combined.routing import MinuteFlowGate

    gate = MinuteFlowGate(flow_minutes(0, (30, ".6"), (1, None), (30, ".6")), 15 * MINUTE)
    assert not gate.advance(30 * MINUTE) and gate.allowed
    assert gate.advance(45 * MINUTE) and not gate.allowed  # 31:00-45:00 read the gap
    assert not gate.advance(46 * MINUTE) and gate.allowed
    empty = MinuteFlowGate({}, 15 * MINUTE)
    assert empty.advance(60 * MINUTE) and not empty.allowed


def test_the_rolling_flow_equals_completed_flow_minute_by_minute():
    # A synthetic stretch with every kind of minute: ordinary shares at varying decimals,
    # missing minutes, invalid ones (taker above volume, NaN, negative, above 1e36), a
    # zero-volume stretch, and sums too long for the context or for exact rolling sums.
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.combined.routing import RollingFlow, completed_flow

    def bar(stamp, volume, taker):
        return Kline(stamp, D(1), D(1), D(1), D(1), volume, D(1), taker)

    rows = {}
    for index in range(400):
        stamp = index * MINUTE
        volume = D(10 + index % 7) + D(index % 13) / D(10**8)
        taker = volume * D(index % 10) / D(10)
        rows[stamp] = bar(stamp, volume, taker)
    for index in (40, 41, 120):  # missing minutes
        del rows[index * MINUTE]
    invalid = {
        60: (D(5), D(6)),  # taker above volume
        61: (D("NaN"), D(1)),
        90: (D(-1), D(0)),
        91: (D("1e37"), D(1)),
    }
    for index, (volume, taker) in invalid.items():
        rows[index * MINUTE] = bar(index * MINUTE, volume, taker)
    for index in range(150, 170):  # no volume at all: unavailable
        rows[index * MINUTE] = bar(index * MINUTE, D(0), D(0))
    # Sums longer than 28 digits (completed_flow rounds them) and than exact 60-digit sums.
    rows[200 * MINUTE] = bar(200 * MINUTE, D("123456789012345678901234.5678901"), D(3))
    rows[260 * MINUTE] = bar(260 * MINUTE, D("1e35"), D("1e34"))
    rows[261 * MINUTE] = bar(261 * MINUTE, D("1e-30"), D("1e-31"))
    # One many-decimal minute, then ordinary ones: the sums keep its exponent once it leaves.
    rows[330 * MINUTE] = bar(330 * MINUTE, D("10.1234567890123456789012345678901"), D(3))
    first = 15 * MINUTE
    flow = RollingFlow(rows, first)
    shares = []
    for stamp in range(first, 400 * MINUTE, MINUTE):
        window = [rows[t] for t in range(stamp - 15 * MINUTE, stamp, MINUTE) if t in rows]
        expected = completed_flow(window, stamp)
        observed = flow.next()
        assert observed == expected and (observed is None) == (expected is None), stamp
        shares.append(observed)
    assert None in shares and sum(share is not None for share in shares) > 200


def test_the_rolling_flow_returns_to_its_fast_path_after_a_many_decimal_minute(monkeypatch):
    # A minute with more digits than the context holds sends the fifteen windows around it to
    # completed_flow. Once it has left, the sums are recomputed and the fast path serves again.
    from crypto_grid_bot.backtest.klines import Kline
    from crypto_grid_bot.combined import routing

    exact = routing.completed_flow
    fallbacks = []

    def counted(bars, decision_ms):
        fallbacks.append(decision_ms)
        return exact(bars, decision_ms)

    monkeypatch.setattr(routing, "completed_flow", counted)
    rows = {}
    for index in range(100):
        stamp = index * MINUTE
        volume = D(10 + index % 7)
        taker = volume * D(index % 10) / D(10)
        rows[stamp] = Kline(stamp, D(1), D(1), D(1), D(1), volume, D(1), taker)
    wide = 30 * MINUTE
    rows[wide] = Kline(
        wide, D(1), D(1), D(1), D(1), D("10.0000000000000000000000000000001"), D(1), D(5)
    )
    first = 15 * MINUTE
    flow = routing.RollingFlow(rows, first)
    for stamp in range(first, 100 * MINUTE, MINUTE):
        window = [rows[t] for t in range(stamp - 15 * MINUTE, stamp, MINUTE)]
        assert flow.next() == exact(window, stamp), stamp
    # Only the windows holding the wide minute (stamps 31:00 to 45:00) read completed_flow.
    assert fallbacks == list(range(31 * MINUTE, 46 * MINUTE, MINUTE))
