"""Comparison reports of frozen baselines that stop natively; synthetic marks only."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.combined.baseline_records import (
    NATIVE_STOPS,
    NativeMark,
    comparison_report,
)
from crypto_grid_bot.combined.common_series import FROZEN_REF, common_hourly_series
from crypto_grid_bot.combined.report import Contribution

HOUR = 3_600_000
DAY = 24 * HOUR
STOP = 30 * HOUR + 1_800_000  # an intrabar stop mark in the 06:00 hour of day two


def report(native_stop, producer_issues=()):
    marks = (
        NativeMark(0, "open", D(10000), D(0), D(3000)),
        *(NativeMark(hour * HOUR, "open", D(9500), D(0), D(3000)) for hour in range(1, 31)),
        NativeMark(STOP, "adverse", D(8000), D(0), D(2500)),
    )
    lifecycle = Contribution(
        "life",
        "unchanged_v3",
        "BTC",
        "long",
        None,
        D(-2000),
        D(0),
        D(0),
        D(1),
        None,
        0,
        "open_marked",
        source_refs=("s",),
    )
    return comparison_report(
        "unchanged_v3_r2_long_only",
        marks,
        (lifecycle,),
        initial=D(10000),
        start_ms=0,
        end_ms=2 * DAY,
        source_refs=("s",),
        adapter_pin="a" * 64,
        producer_issues=producer_issues,
        native_stop=native_stop,
    )


def test_native_stops_are_the_frozen_v3_stops():
    assert {"liquidation", "no_tradable_position", "leverage_not_restored"} == NATIVE_STOPS


@pytest.mark.parametrize("stop", sorted(NATIVE_STOPS))
def test_a_native_stop_holds_its_last_equity_labelled_frozen_to_the_window_end(stop):
    result = report(stop)
    assert result.complete, result.issues
    frozen = [p for p in result.equity_points if p.timestamp_ms > STOP]
    hours = tuple(range(31 * HOUR, 2 * DAY + 1, HOUR))
    assert tuple(p.timestamp_ms for p in frozen) == hours
    assert all(p.equity == D(8000) and FROZEN_REF + stop in p.source_refs for p in frozen)
    assert result.final_equity == D(8000) and result.reconciliation_residual == 0
    # Nothing is deployed once the run has ended.
    after = [c for c in result.capital_observations if c.timestamp_ms > STOP]
    assert after and all(c.spot_value == c.futures_collateral == 0 for c in after)
    series = common_hourly_series(
        result.equity_points, result.policy_evidence, start_ms=0, end_ms=2 * DAY
    )
    assert series.native_stop == stop and series.frozen_hours == hours


def test_a_run_ending_early_without_a_native_stop_stays_incomplete():
    result = report(None, producer_issues=("baseline_stop:engine_failure",))
    assert not result.complete
    assert result.equity_points[-1].timestamp_ms == 30 * HOUR
    with pytest.raises(ValueError):
        common_hourly_series(
            result.equity_points, result.policy_evidence, start_ms=0, end_ms=2 * DAY
        )


@pytest.mark.parametrize(
    "stop", ["engine_failure", "unavailable_exclusion_close", "no_selector_pick", ""]
)
def test_only_a_native_stop_freezes_equity(stop):
    with pytest.raises(ValueError, match="native stop"):
        report(stop)
