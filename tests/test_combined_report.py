from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.combined.report import (
    Contribution,
    EquityPoint,
    Opportunity,
    RecoveryEpisode,
    UtilizationInterval,
    analyze,
)

D = Decimal
HOUR = 3_600_000


def contributions():
    return (
        Contribution(
            "closed",
            "spot_trend",
            "BTCUSDT",
            "long",
            "up",
            D(10),
            D(2),
            D(-1),
            D(30),
            "trail",
            0,
            "closed",
            2,
            D(15),
            D(4),
        ),
        Contribution(
            "open",
            "futures_trend",
            "ETHUSDT",
            "short",
            None,
            D(-1),
            D(1),
            D(0),
            D(10),
            None,
            1,
            "open_marked",
        ),
    )


def curve():
    return (EquityPoint(0, D(100)), EquityPoint(1, D(110)), EquityPoint(2, D(105)))


def test_accounting_and_dimensions_include_open_marks_with_signed_funding() -> None:
    report = analyze(D(100), curve(), contributions(), (), (), ("artifact-pin",))
    assert report.structural_complete
    assert report.net_profit == 5 and report.net_return == D(".05")
    assert report.fees == 3 and report.funding_signed == -1 and report.turnover == 40
    assert report.reconciliation_residual == 0
    assert report.closed_count == 1 and report.open_marked_count == 1
    assert sum(row.net_pnl for row in report.by_strategy) == 5
    assert sum(row.net_pnl for row in report.by_asset) == 5
    assert sum(row.net_pnl for row in report.by_direction) == 5
    assert sum(row.net_pnl for row in report.by_regime) == 5
    assert report.largest_positive_asset_share == 1
    assert report.by_regime[0].key is None
    assert report.contributions == contributions()


def test_lifetime_drawdown_never_resets_at_recovery() -> None:
    points = (
        EquityPoint(0, D(100)),
        EquityPoint(1, D(200)),
        EquityPoint(2, D(100)),
        EquityPoint(3, D(150)),
    )
    row = replace(contributions()[0], gross_pnl=D(50), fees=D(0), funding_signed=D(0))
    recovery = (RecoveryEpisode(2, 3, D(100), D(150)),)
    report = analyze(D(100), points, (row,), (), recovery, ("source",))
    assert report.max_drawdown == D(".5")
    assert report.recovery_changes[0].marked_change == 50
    assert report.recovery_changes[0].return_fraction == D(".5")
    assert len(report.bad_intervals) == 1
    assert report.bad_intervals[0].net_change == -100
    assert (report.bad_intervals[0].start_ms, report.bad_intervals[0].end_ms) == (1, 2)


def test_opportunity_episodes_not_hourly_samples_with_gaps_and_direction_changes() -> None:
    events = (
        Opportunity(0, "BTCUSDT", "long", "breakout", "detected", None),
        Opportunity(HOUR, "BTCUSDT", "long", "breakout", "qualified", None),
        Opportunity(2 * HOUR, "BTCUSDT", "long", "breakout", "filled", None),
        Opportunity(4 * HOUR, "BTCUSDT", "long", "breakout", "detected", None),
        Opportunity(5 * HOUR, "BTCUSDT", "short", "breakout", "blocked", "cost"),
        Opportunity(6 * HOUR, "BTCUSDT", "short", "pullback", "detected", None),
        Opportunity(HOUR, "ETHUSDT", "long", "breakout", "filled", None),
    )
    report = analyze(D(100), curve(), contributions(), events, (), ("source",))
    assert len(report.opportunity_episodes) == 5
    first = report.opportunity_episodes[0]
    assert first.observation_count == 3 and first.entry_delay_ms == 2 * HOUR
    assert report.opportunity_episodes[-1].entry_delay_ms is None
    assert report.observation_gap_ms == HOUR


def test_unknown_excursion_and_giveback_are_not_invented_from_pnl() -> None:
    report = analyze(D(100), curve(), contributions(), (), (), ("source",))
    assert report.mfe_available == 1 and report.giveback_available == 1
    assert report.contributions[1].mfe is None and report.contributions[1].giveback is None
    assert report.exit_reason_counts == (("trail", 1),)


def test_missing_sources_equity_and_residuals_are_explicit_incomplete() -> None:
    report = analyze(D(100), curve(), contributions(), (), (), ())
    assert not report.complete and "missing_source_refs" in report.issues
    report = analyze(D(100), (), contributions(), (), (), ("source",))
    assert not report.complete and report.final_equity is None and report.max_drawdown is None
    assert report.net_return is None and report.reconciliation_residual is None
    report = analyze(D(100), curve(), contributions()[:1], (), (), ("source",))
    assert not report.complete and report.reconciliation_residual == -2


def test_duplicate_ids_raise_without_silent_deduplication() -> None:
    rows = contributions()
    with pytest.raises(ValueError):
        analyze(D(100), curve(), (*rows, rows[0]), (), (), ("source",))
    assert len(rows) == 2


@pytest.mark.parametrize(
    "alter",
    [
        "nan",
        "negative_fee",
        "status",
        "closed_missing_exit",
        "open_has_exit",
        "negative_excursion",
        "earlier_exit",
    ],
)
def test_malformed_contributions_are_refused(alter: str) -> None:
    rows = list(contributions())
    if alter == "nan":
        rows[0] = replace(rows[0], gross_pnl=D("NaN"))
    elif alter == "negative_fee":
        rows[0] = replace(rows[0], fees=D(-1))
    elif alter == "status":
        rows[0] = replace(rows[0], status="unknown")
    elif alter == "closed_missing_exit":
        rows[0] = replace(rows[0], exit_ms=None)
    elif alter == "open_has_exit":
        rows[1] = replace(rows[1], exit_ms=2)
    elif alter == "negative_excursion":
        rows[0] = replace(rows[0], mfe=D(-1))
    else:
        rows[0] = replace(rows[0], entry_ms=3, exit_ms=2)
    with pytest.raises(ValueError):
        analyze(D(100), curve(), tuple(rows), (), (), ("source",))


def test_recovery_open_endpoint_is_unknown_not_zero_profit() -> None:
    report = analyze(
        D(100), curve(), contributions(), (), (RecoveryEpisode(1, None, D(100), None),), ("source",)
    )
    assert report.recovery_changes[0].marked_change is None
    assert report.recovery_changes[0].return_fraction is None


def test_caller_precision_does_not_round_accounting_and_zero_initial_is_rejected() -> None:
    with localcontext() as context:
        context.prec = 2
        report = analyze(D(100), curve(), contributions(), (), (), ("source",))
    assert report.max_drawdown == D(
        "0.0454545454545454545454545454545454545454545454545454545454545"
    )
    assert report.reconciliation_residual == 0
    with pytest.raises(ValueError):
        analyze(D(0), (), (), (), (), ("source",))


def test_equity_order_invalid_sources_and_observation_gap_are_not_silently_repaired() -> None:
    with pytest.raises(ValueError):
        analyze(D(100), tuple(reversed(curve())), (), (), (), ("source",))
    with pytest.raises(ValueError):
        analyze(D(100), curve(), contributions(), (), (), ("",))
    with pytest.raises(ValueError):
        analyze(D(100), curve(), contributions(), (), (), ("source",), opportunity_gap_ms=0)


def test_future_contributions_cannot_produce_complete_report() -> None:
    rows = tuple(
        replace(row, entry_ms=100, exit_ms=101 if row.status == "closed" else None)
        for row in contributions()
    )
    report = analyze(D(100), curve(), rows, (), (), ("source",))
    assert not report.complete
    assert "contribution_outside_equity_window" in report.issues


@pytest.mark.parametrize(
    "episode",
    [
        RecoveryEpisode(1, 2, D(100), D(150)),
        RecoveryEpisode(1, 3, D(110), D(105)),
    ],
)
def test_recovery_unverified_or_contradictory_endpoints_have_no_attribution(episode) -> None:
    report = analyze(D(100), curve(), contributions(), (), (episode,), ("source",))
    assert not report.complete
    assert report.recovery_changes[0].marked_change is None
    assert report.recovery_changes[0].return_fraction is None
    assert "recovery_endpoint" in report.unknown_fields


def test_recovery_exact_observed_endpoints_preserve_actual_loss() -> None:
    report = analyze(
        D(100), curve(), contributions(), (), (RecoveryEpisode(1, 2, D(110), D(105)),), ("source",)
    )
    assert report.structural_complete
    assert report.recovery_changes[0].marked_change == -5


def test_recovery_does_not_choose_between_different_same_timestamp_marks() -> None:
    points = (
        EquityPoint(0, D(100)),
        EquityPoint(1, D(110)),
        EquityPoint(1, D(109)),
        EquityPoint(2, D(105)),
    )
    report = analyze(
        D(100), points, contributions(), (), (RecoveryEpisode(1, 2, D(110), D(105)),), ("source",)
    )
    assert not report.complete
    assert report.recovery_changes[0].marked_change is None


def test_recovery_missing_start_mark_is_not_interpolated() -> None:
    report = analyze(
        D(100),
        (curve()[0], curve()[2]),
        contributions(),
        (),
        (RecoveryEpisode(1, 2, D(110), D(105)),),
        ("source",),
    )
    assert not report.complete
    assert report.recovery_changes[0].marked_change is None


# Required performance metrics use explicitly supplied evidence, never event-count annualization.

DAY = 86_400_000


def metrics_report(points, **kwargs):
    return analyze(D(100), points, (), (), (), ("synthetic",), **kwargs)


def metric(report, name):
    return next(item for item in report.metrics if item.name == name)


def test_cagr_requires_verified_opening_time_and_uses_365_25_days():
    points = (EquityPoint(0, D(100)), EquityPoint(31_557_600_000, D(121)))
    result = metrics_report(points, metrics_start_ms=0)
    assert metric(result, "cagr").value == D(".21")
    assert metric(metrics_report(points), "cagr").unavailable_reason == "opening_time_unavailable"
    bad = (EquityPoint(0, D(99)), points[-1])
    assert metric(metrics_report(bad, metrics_start_ms=0), "cagr").value is None


def test_return_drawdown_zero_is_indeterminate_not_infinite():
    up = (EquityPoint(0, D(100)), EquityPoint(DAY, D(110)))
    assert metric(metrics_report(up), "return_drawdown").unavailable_reason == "zero_drawdown"
    down = (EquityPoint(0, D(100)), EquityPoint(DAY, D(90)))
    assert metric(metrics_report(down), "return_drawdown").value == -1


def test_sharpe_uses_only_explicit_regular_daily_samples_and_sample_sd():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(110)), EquityPoint(2 * DAY, D(99)))
    result = metrics_report(points, metrics_start_ms=0, daily_samples=points)
    assert metric(result, "sharpe").value == 0
    assert "sample standard deviation" in metric(result, "sharpe").definition
    assert metric(metrics_report(points), "sharpe").value is None
    gapped = (points[0], points[-1])
    assert (
        metric(metrics_report(points, metrics_start_ms=0, daily_samples=gapped), "sharpe").value
        is None
    )
    repeated = (points[0], points[1], points[1], points[-1])
    assert (
        metric(metrics_report(points, metrics_start_ms=0, daily_samples=repeated), "sharpe").value
        is None
    )


def test_constant_returns_and_zero_duration_are_indeterminate():
    points = tuple(EquityPoint(i * DAY, D(100)) for i in range(3))
    result = metrics_report(points, metrics_start_ms=0, daily_samples=points)
    assert metric(result, "sharpe").unavailable_reason == "zero_variance"
    result = metrics_report((EquityPoint(0, D(100)),), metrics_start_ms=0)
    assert metric(result, "cagr").value is None


def test_utilization_is_duration_weighted_capital_not_futures_notional():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(100)), EquityPoint(3 * DAY, D(100)))
    supplied = (
        UtilizationInterval(0, DAY, D(20), D(30), D(100)),
        UtilizationInterval(DAY, 3 * DAY, D(10), D(15), D(100)),
    )
    result = metrics_report(points, metrics_start_ms=0, utilization=supplied)
    assert abs(metric(result, "utilization").value - D(1) / D(3)) < D("1e-27")
    assert result.utilization == supplied
    assert (
        metric(
            metrics_report(points, metrics_start_ms=0, utilization=supplied[1:]), "utilization"
        ).value
        is None
    )


def test_missing_required_metrics_prevents_complete_report_but_keeps_structural_status():
    result = metrics_report((EquityPoint(0, D(100)),))
    assert result.structural_complete and not result.complete
    assert any("metric_unavailable" in issue for issue in result.issues)


def test_supplied_metrics_can_make_reconciled_report_complete():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(110)), EquityPoint(2 * DAY, D(100)))
    utilization = (UtilizationInterval(0, 2 * DAY, D(0), D(0), D(100)),)
    result = metrics_report(
        points, metrics_start_ms=0, daily_samples=points, utilization=utilization
    )
    assert result.complete and all(item.value is not None for item in result.metrics)


def test_nonpositive_equity_metrics_and_invalid_utilization_values():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(0)), EquityPoint(2 * DAY, D(-1)))
    result = metrics_report(points, metrics_start_ms=0, daily_samples=points)
    assert metric(result, "cagr").value is None and metric(result, "sharpe").value is None
    with pytest.raises(ValueError):
        metrics_report(
            points,
            metrics_start_ms=0,
            utilization=(UtilizationInterval(0, DAY, D(-1), D(0), D(100)),),
        )


def test_nonzero_sharpe_matches_analytical_sample_variance():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(110)), EquityPoint(2 * DAY, D(132)))
    result = metrics_report(points, metrics_start_ms=0, daily_samples=points)
    with localcontext() as ctx:
        ctx.prec = 60
        expected = D(".15") / D(".005").sqrt() * D(365).sqrt()
    assert metric(result, "sharpe").value == expected
    unmatched = (points[0], EquityPoint(DAY, D(109)), points[-1])
    result = metrics_report(points, metrics_start_ms=0, daily_samples=unmatched)
    assert metric(result, "sharpe").value is None


def test_utilization_gap_overlap_and_unknown_mark_do_not_get_interpolated():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(100)), EquityPoint(2 * DAY, D(100)))
    for intervals in (
        (
            UtilizationInterval(0, DAY - 1, D(20), D(0), D(100)),
            UtilizationInterval(DAY, 2 * DAY, D(20), D(0), D(100)),
        ),
        (
            UtilizationInterval(0, DAY + 1, D(20), D(0), D(100)),
            UtilizationInterval(DAY, 2 * DAY, D(20), D(0), D(100)),
        ),
        (UtilizationInterval(0, 2 * DAY, D(20), D(0), D(101)),),
    ):
        result = metrics_report(points, metrics_start_ms=0, utilization=intervals)
        assert metric(result, "utilization").value is None


def test_millisecond_cagr_overflow_is_unavailable_without_crashing_report():
    points = (EquityPoint(0, D(100)), EquityPoint(1, D(200)))
    result = metrics_report(points, metrics_start_ms=0)
    assert metric(result, "cagr").value is None
    assert metric(result, "cagr").unavailable_reason == "numeric_range"
    assert result.final_equity == 200 and result.net_return == 1


def test_missing_daily_endpoint_is_unavailable_without_using_partial_period():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(110)), EquityPoint(2 * DAY, D(99)))
    result = metrics_report(points, metrics_start_ms=0, daily_samples=points[:-1])
    assert metric(result, "sharpe").value is None
    assert metric(result, "sharpe").unavailable_reason == "incomplete_or_unmatched_daily_samples"


def test_ambiguous_daily_marks_cannot_select_favorable_sharpe_or_utilization():
    points = (
        EquityPoint(0, D(100)),
        EquityPoint(DAY, D(110)),
        EquityPoint(DAY, D(90)),
        EquityPoint(2 * DAY, D(100)),
    )
    for selected in (D(110), D(90)):
        samples = (points[0], EquityPoint(DAY, selected), points[-1])
        intervals = (
            UtilizationInterval(0, DAY, D(20), D(0), D(100)),
            UtilizationInterval(DAY, 2 * DAY, D(20), D(0), selected),
        )
        result = metrics_report(
            points, metrics_start_ms=0, daily_samples=samples, utilization=intervals
        )
        assert metric(result, "sharpe").value is None
        assert metric(result, "utilization").value is None
        assert not result.complete


def test_equal_value_duplicate_daily_marks_remain_unambiguous():
    points = (
        EquityPoint(0, D(100)),
        EquityPoint(DAY, D(110)),
        EquityPoint(DAY, D(110)),
        EquityPoint(2 * DAY, D(100)),
    )
    samples = (points[0], points[1], points[-1])
    intervals = (
        UtilizationInterval(0, DAY, D(20), D(0), D(100)),
        UtilizationInterval(DAY, 2 * DAY, D(20), D(0), D(110)),
    )
    result = metrics_report(
        points, metrics_start_ms=0, daily_samples=samples, utilization=intervals
    )
    assert result.complete
