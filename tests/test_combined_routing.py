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
