"""Comparison reports of frozen baselines that stop natively; synthetic marks only."""

from decimal import Decimal as D
from fractions import Fraction

import pytest

from crypto_grid_bot.combined.baseline_records import (
    NATIVE_STOPS,
    BaselineEvidence,
    NativeMark,
    comparison_report,
    native_diagnostics,
)
from crypto_grid_bot.combined.common_series import FROZEN_REF, common_hourly_series
from crypto_grid_bot.combined.report import Contribution, analyze, utc_text

HOUR = 3_600_000
DAY = 24 * HOUR
STOP = 30 * HOUR + 1_800_000  # an intrabar stop mark in the 06:00 hour of day two


def report(native_stop, producer_issues=(), **options):
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
        **options,
    )


def test_only_a_liquidation_is_a_native_stop():
    # Owner, 2026-10-12: only a real market event finishes a baseline. V3's
    # no_tradable_position and leverage_not_restored come from masked or untradable
    # coins (terminal invalid-run outcomes) and are never frozen.
    assert {"liquidation"} == NATIVE_STOPS


@pytest.mark.parametrize("stop", ["no_tradable_position", "leverage_not_restored"])
def test_an_untradable_v3_stop_is_never_frozen(stop):
    with pytest.raises(ValueError, match="unknown native stop"):
        report(stop)
    result = report(None, producer_issues=(f"baseline_stop:{stop}",))
    assert not result.complete and f"baseline_stop:{stop}" in result.issues
    assert not any(
        ref.startswith(FROZEN_REF) for p in result.equity_points for ref in p.source_refs
    )


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


@pytest.mark.parametrize("stop", sorted(NATIVE_STOPS))
def test_the_adapter_notes_skipped_hours_and_frozen_stop_reach_the_report(stop):
    result = report(
        stop,
        disclosures=("adapter_note",),
        skipped_hours=(10 * HOUR,),
        capital_label="research_10000_usdt",
    )
    assert result.complete, result.issues
    assert result.disclosures == (
        "adapter_note",
        f"registered_skipped_hours: count=1 at={utc_text(10 * HOUR)}",
        f"frozen_after_native_stop:{stop}: hours=18 first={utc_text(31 * HOUR)} "
        f"last={utc_text(2 * DAY)}",
    )
    assert result.capital_label == "research_10000_usdt"


def test_a_run_without_a_stop_or_skipped_hour_discloses_only_its_adapter_notes():
    assert report(None).disclosures == ()
    assert report(None, disclosures=("adapter_note",)).disclosures == ("adapter_note",)


def native_evidence(marks, status=None):
    return BaselineEvidence(
        "unchanged_v3_selector",
        "v3-native",
        marks,
        analyze(D(10000), (), (), (), (), ("s",)),
        status,
        0,
        D(0),
        True,
        True,
        (),
    )


def test_native_diagnostics_measure_every_native_mark_under_its_version_label():
    marks = (
        NativeMark(0, "open", D(10000), D(0), D(0)),
        NativeMark(HOUR // 2, "adverse", D(9000), D(0), D(0)),  # intrabar, off the hour
        NativeMark(HOUR, "open", D(11000), D(0), D(0)),
        NativeMark(3 * HOUR // 2, "adverse", D(8800), D(0), D(0)),  # 20% below 11000
        NativeMark(2 * HOUR, "close", D(10450), D(0), D(0)),
    )
    result = native_diagnostics(native_evidence(marks, "liquidation"))
    assert (result.arm, result.native_label, result.status) == (
        "unchanged_v3_selector",
        "v3-native",
        "liquidation",
    )
    assert (result.mark_count, result.first_ms, result.last_ms) == (5, 0, 2 * HOUR)
    assert result.net_return == Fraction(9, 200) and result.max_drawdown == Fraction(1, 5)


def test_a_baseline_without_native_marks_has_unavailable_diagnostics():
    result = native_diagnostics(native_evidence((), "no_selector_pick"))
    assert result.mark_count == 0 and result.status == "no_selector_pick"
    assert (result.first_ms, result.last_ms, result.net_return, result.max_drawdown) == (
        None,
        None,
        None,
        None,
    )
