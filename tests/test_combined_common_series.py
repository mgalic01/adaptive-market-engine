"""Common economic-boundary series, using synthetic retained observations only."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest

from crypto_grid_bot.combined.common_series import common_hourly_series
from crypto_grid_bot.combined.observation_policy import POLICY_ID, Boundary, PolicyEvidence
from crypto_grid_bot.combined.report import EquityPoint

HOUR = 3_600_000


def fixture():
    points = tuple(
        EquityPoint(t, Decimal(value), identity, ("synthetic",))
        for t, value, identity in (
            (0, 100, "initial"),
            (0, 99, "opening-cost"),
            (HOUR, 60, "intrabar-loss"),
            (HOUR, 90, "settled"),
            (2 * HOUR, 120, "terminal"),
        )
    )
    policy = PolicyEvidence(
        POLICY_ID,
        "a" * 64,
        (
            Boundary(0, "opening", ("initial", "opening-cost"), "initial", "c0", ("s",), 0, HOUR),
            Boundary(
                HOUR,
                "settled",
                ("intrabar-loss", "settled"),
                "settled",
                "c1",
                ("s",),
                HOUR,
                2 * HOUR,
            ),
            Boundary(2 * HOUR, "terminal", ("terminal",), "terminal", "c2", ("s",), HOUR, 2 * HOUR),
        ),
    )
    return points, policy


def test_common_series_selects_approved_marks_without_mutating_native_observations():
    points, policy = fixture()
    result = common_hourly_series(points, policy, start_ms=0, end_ms=2 * HOUR)
    assert result.points == (points[0], points[3], points[4])
    assert result.net_return == Fraction(1, 5)
    assert result.max_drawdown == Fraction(1, 10)
    assert points[2].equity == 60  # Native 40% breach remains separate evidence.
    assert result.policy_id == POLICY_ID
    assert result.adapter_pin == policy.adapter_pin


def test_missing_hour_cannot_be_interpolated_or_relabelled():
    points, policy = fixture()
    policy = replace(policy, boundaries=(policy.boundaries[0], policy.boundaries[-1]))
    with pytest.raises(ValueError, match="every hourly"):
        common_hourly_series(points, policy, start_ms=0, end_ms=2 * HOUR)


@pytest.mark.parametrize("start,end", [(1, 2 * HOUR), (0, HOUR), (True, 2 * HOUR)])
def test_window_must_match_exact_observed_endpoints(start, end):
    points, policy = fixture()
    with pytest.raises(ValueError):
        common_hourly_series(points, policy, start_ms=start, end_ms=end)


def test_nonfinite_or_nonpositive_opening_cannot_create_ratios():
    points, policy = fixture()
    for value in (Decimal("NaN"), Decimal(0), Decimal(-1)):
        changed = (replace(points[0], equity=value), *points[1:])
        with pytest.raises(ValueError):
            common_hourly_series(changed, policy, start_ms=0, end_ms=2 * HOUR)


def test_negative_equity_is_retained_as_exhaustion_not_filtered():
    points, policy = fixture()
    points = (*points[:-1], replace(points[-1], equity=Decimal(-10)))
    result = common_hourly_series(points, policy, start_ms=0, end_ms=2 * HOUR)
    assert result.net_return == Fraction(-11, 10)
    assert result.max_drawdown == Fraction(11, 10)
