"""Common economic-boundary series, using synthetic retained observations only."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pytest

from crypto_grid_bot.combined.common_series import FROZEN_REF, common_hourly_series
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


def hourly(values, *, refs=None):
    """One mark per hour from 0; ``None`` leaves that hour without a mark."""
    points = tuple(
        EquityPoint(index * HOUR, Decimal(value), f"p{index}", (refs or {}).get(index, ("s",)))
        for index, value in enumerate(values)
        if value is not None
    )
    final = len(points) - 1
    boundaries = tuple(
        Boundary(
            point.timestamp_ms,
            "opening" if position == 0 else "terminal" if position == final else "settled",
            (point.id,),
            point.id,
            f"c{point.timestamp_ms}",
            ("s",),
            point.timestamp_ms - (HOUR if position == final else 0),
            point.timestamp_ms + (0 if position == final else HOUR),
        )
        for position, point in enumerate(points)
    )
    return points, PolicyEvidence(POLICY_ID, "a" * 64, boundaries), (len(values) - 1) * HOUR


def test_skipped_hours_are_left_out_of_the_comparison():
    points, policy, end = hourly((100, 100, 50, 110, 105, 120))
    result = common_hourly_series(points, policy, start_ms=0, end_ms=end, skipped_hours=(2 * HOUR,))
    assert [p.timestamp_ms for p in result.points] == [0, HOUR, 3 * HOUR, 4 * HOUR, 5 * HOUR]
    assert result.max_drawdown == Fraction(5, 110)  # the native 50% dip is not compared
    assert result.skipped_hours == (2 * HOUR,)
    assert points[2].equity == 50  # retained as native evidence


def test_a_skipped_hour_needs_no_mark_but_a_scheduled_hour_does():
    points, policy, end = hourly((100, 100, None, 110, 105, 120))
    result = common_hourly_series(points, policy, start_ms=0, end_ms=end, skipped_hours=(2 * HOUR,))
    assert result.net_return == Fraction(1, 5)
    with pytest.raises(ValueError, match="every hourly economic boundary on the schedule"):
        common_hourly_series(points, policy, start_ms=0, end_ms=end)
    points, policy, end = hourly((100, 100, 90, None, 105, 120))
    with pytest.raises(ValueError, match="every hourly economic boundary on the schedule"):
        common_hourly_series(points, policy, start_ms=0, end_ms=end, skipped_hours=(2 * HOUR,))


@pytest.mark.parametrize(
    "skipped",
    [
        (0,),  # the opening
        (4 * HOUR,),  # the last hour, whose close is the terminal mark
        (5 * HOUR,),  # the terminal
        (3 * HOUR, 2 * HOUR),
        (2 * HOUR, 2 * HOUR),
        (2 * HOUR + 1,),
        (True,),
        [2 * HOUR],
    ],
)
def test_skipped_hours_are_sorted_hours_strictly_inside_never_first_or_last(skipped):
    points, policy, end = hourly((100, 100, 90, 110, 105, 120))
    with pytest.raises(ValueError, match="skipped hours"):
        common_hourly_series(points, policy, start_ms=0, end_ms=end, skipped_hours=skipped)


FROZEN = (FROZEN_REF + "liquidation",)


def test_frozen_marks_after_a_native_stop_are_labelled_in_the_series():
    points, policy, end = hourly((100, 90, 95, 40, 40, 40), refs={3: FROZEN, 4: FROZEN, 5: FROZEN})
    result = common_hourly_series(points, policy, start_ms=0, end_ms=end, skipped_hours=(3 * HOUR,))
    assert result.frozen_hours == (4 * HOUR, 5 * HOUR)
    assert result.native_stop == "liquidation"
    assert result.net_return == Fraction(-3, 5)
    plain = common_hourly_series(*hourly((100, 90, 95, 40, 40, 40))[:2], start_ms=0, end_ms=end)
    assert plain.frozen_hours == () and plain.native_stop is None


@pytest.mark.parametrize(
    "values,refs",
    [
        ((100, 90, 40, 95, 40, 40), {2: FROZEN, 4: FROZEN, 5: FROZEN}),  # not the series' end
        ((100, 90, 95, 40, 41, 40), {3: FROZEN, 4: FROZEN, 5: FROZEN}),  # equity moved
        (
            (100, 90, 95, 40, 40, 40),
            {3: FROZEN, 4: FROZEN, 5: (FROZEN_REF + "no_tradable_position",)},
        ),
        ((100, 90, 95, 40, 40, 40), {5: (FROZEN_REF,)}),  # no stop named
    ],
)
def test_frozen_marks_must_close_the_series_holding_one_stop_equity(values, refs):
    points, policy, end = hourly(values, refs=refs)
    with pytest.raises(ValueError, match="frozen"):
        common_hourly_series(points, policy, start_ms=0, end_ms=end)
