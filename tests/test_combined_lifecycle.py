"""Protective decisions do not depend on admission and never invent execution."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D

import pytest
from test_combined_routing import market

from crypto_grid_bot.combined.lifecycle import ManagementDecision, manage
from crypto_grid_bot.strategy.perception import TrendState as T


def test_verified_range_keeps_grid_and_decision_is_immutable():
    assessment = replace(market(), daily=T.RANGE, four_hour=T.RANGE)
    result = manage(assessment, "spot_grid", 1)
    assert result == ManagementDecision(False, None)
    with pytest.raises(FrozenInstanceError):
        result.cancel_increases = True


@pytest.mark.parametrize(
    "daily,four_hour", [(T.UP, T.UP), (T.DOWN, T.DOWN), (T.RANGE, T.UP), (T.UNCLEAR, T.RANGE)]
)
def test_grid_leaving_range_requests_close(daily, four_hour):
    result = manage(replace(market(), daily=daily, four_hour=four_hour), "spot_grid", 1)
    assert result == ManagementDecision(True, "grid_left_range")


@pytest.mark.parametrize(
    "changes",
    [
        dict(available=False),
        dict(reasons=("hourly_gap",)),
        dict(close=None),
        dict(atr=D("NaN")),
        dict(volatility_ratio=D(3)),
        dict(hourly_closed_ms=None),
        dict(quote_ms=0),
    ],
)
def test_unverified_grid_requests_protection_not_a_fill(changes):
    assessment = replace(market(), daily=T.RANGE, four_hour=T.RANGE, **changes)
    assert manage(assessment, "spot_grid", 1) == ManagementDecision(True, "grid_range_unverified")
    assert manage(assessment, "spot_trend", 1) == ManagementDecision(True, None)


@pytest.mark.parametrize(
    "owner,side,daily,four_hour",
    [
        ("spot_trend", 1, T.DOWN, T.DOWN),
        ("futures_trend", 1, T.DOWN, T.DOWN),
        ("futures_trend", -1, T.UP, T.UP),
    ],
)
def test_opposite_qualified_structure_closes_trend(owner, side, daily, four_hour):
    assessment = replace(market(), daily=daily, four_hour=four_hour)
    assert manage(assessment, owner, side) == ManagementDecision(True, "trend_reversal")
    assert manage(replace(assessment, structure="none"), owner, side) == ManagementDecision(
        True, None
    )


def test_conflict_and_unavailable_never_invent_trend_reversal():
    assessment = replace(market(), daily=T.UP, four_hour=T.DOWN)
    assert manage(assessment, "spot_trend", 1) == ManagementDecision(True, None)
    opposite = replace(assessment, daily=T.DOWN, available=False)
    assert manage(opposite, "spot_trend", 1) == ManagementDecision(True, None)


@pytest.mark.parametrize("rsi", [D(0), D(100)])
def test_rsi_alone_does_not_exit_aligned_trend(rsi):
    assert manage(replace(market(), rsi=rsi), "spot_trend", 1) == ManagementDecision(False, None)


def test_short_ablation_accepts_unclear_daily_but_never_daily_up():
    assessment = replace(market(), daily=T.UNCLEAR, four_hour=T.DOWN)
    assert manage(assessment, "futures_trend", -1, short_qualification=False) == (
        ManagementDecision(False, None)
    )
    assert manage(assessment, "futures_trend", -1) == ManagementDecision(True, None)
    assert manage(assessment, "spot_trend", 1, short_qualification=False) == (
        ManagementDecision(True, "trend_reversal")
    )
    assert manage(
        replace(assessment, daily=T.UP), "futures_trend", -1, short_qualification=False
    ) == ManagementDecision(True, None)


@pytest.mark.parametrize(
    "field", ["quote_ms", "hourly_closed_ms", "four_hour_closed_ms", "daily_closed_ms"]
)
def test_future_source_timestamp_is_unreliable_not_a_reversal(field):
    a = market()
    a = replace(a, daily=T.DOWN, four_hour=T.DOWN, **{field: a.decision_ms + 1})
    assert manage(a, "spot_trend", 1) == ManagementDecision(True, None)


@pytest.mark.parametrize(
    "owner,side",
    [
        ("unknown", 1),
        ("spot_grid", -1),
        ("spot_trend", -1),
        ("futures_trend", True),
        ("futures_trend", 0),
    ],
)
def test_invalid_held_identity_rejected(owner, side):
    with pytest.raises(ValueError):
        manage(market(), owner, side)


def test_malformed_boolean_and_schema_never_permit_increases():
    with pytest.raises(ValueError):
        manage(market(), "futures_trend", -1, short_qualification="false")
    assert manage(replace(market(), available=1), "spot_grid", 1).cancel_increases
    assert manage(replace(market(), schema="other"), "spot_grid", 1).cancel_increases
