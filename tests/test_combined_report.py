from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.combined.report import (
    CapitalObservation,
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
            source_refs=("synthetic#closed",),
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
            source_refs=("synthetic#open",),
        ),
    )


def curve():
    return tuple(
        EquityPoint(t, D(v), f"mark-{t}", (f"synthetic#mark-{t}",))
        for t, v in ((0, 100), (1, 110), (2, 105))
    )


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
        D(100),
        curve(),
        contributions(),
        (),
        (RecoveryEpisode(1, 2, D(110), D(105), "recovery-1", ("synthetic#recovery",)),),
        ("source",),
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
        D(100),
        points,
        contributions(),
        (),
        (RecoveryEpisode(1, 2, D(110), D(105), "recovery-1", ("synthetic#recovery",)),),
        ("source",),
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
    points = tuple(
        replace(p, id=f"mark-{i}", source_refs=(f"synthetic#mark-{i}",))
        for i, p in enumerate(points)
    )
    observations = (
        CapitalObservation(
            0, D(100), D(20), D(30), "account-0", "phase-0", "mark-0", ("source-0",)
        ),
        CapitalObservation(
            DAY, D(100), D(10), D(15), "account-1", "phase-1", "mark-1", ("source-1",)
        ),
    )
    observations += (
        CapitalObservation(
            3 * DAY, D(100), D(10), D(15), "terminal", "terminal", "mark-2", ("source-terminal",)
        ),
    )
    supplied = tuple(replace(row, observation_id=f"account-{i}") for i, row in enumerate(supplied))
    result = metrics_report(
        points, metrics_start_ms=0, utilization=supplied, capital_observations=observations
    )
    assert abs(metric(result, "utilization").value - D(1) / D(3)) < D("1e-27")
    assert result.utilization == supplied
    assert (
        metric(
            metrics_report(points, metrics_start_ms=0, utilization=supplied[1:]), "utilization"
        ).value
        is None
    )


def test_missing_required_metrics_prevents_complete_report_but_keeps_structural_status():
    result = metrics_report((EquityPoint(0, D(100), "opening", ("synthetic#opening",)),))
    assert result.structural_complete and not result.complete
    assert any("metric_unavailable" in issue for issue in result.issues)


def test_supplied_metrics_can_make_reconciled_report_complete():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(110)), EquityPoint(2 * DAY, D(100)))
    utilization = (UtilizationInterval(0, 2 * DAY, D(0), D(0), D(100)),)
    points = tuple(
        replace(p, id=f"mark-{i}", source_refs=(f"synthetic#mark-{i}",))
        for i, p in enumerate(points)
    )
    utilization = tuple(
        replace(p, id=f"capital-{i}", source_refs=(f"synthetic#capital-{i}",))
        for i, p in enumerate(utilization)
    )
    observation = CapitalObservation(
        0, D(100), D(0), D(0), "account-0", "phase-0", "mark-0", ("source",)
    )
    later = replace(
        observation,
        id="account-1",
        timestamp_ms=DAY,
        equity=D(110),
        phase_id="phase-1",
        equity_observation_id="mark-1",
    )
    utilization = (
        replace(utilization[0], end_ms=DAY, observation_id="account-0"),
        replace(
            utilization[0], id="interval-1", start_ms=DAY, equity=D(110), observation_id="account-1"
        ),
    )
    terminal = replace(
        observation,
        id="terminal",
        timestamp_ms=2 * DAY,
        phase_id="terminal",
        equity_observation_id="mark-2",
    )
    result = metrics_report(
        points,
        metrics_start_ms=0,
        daily_samples=points,
        utilization=utilization,
        capital_observations=(observation, later, terminal),
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
    originals = points
    points = tuple(
        replace(p, id=f"mark-{i}", source_refs=(f"synthetic#mark-{i}",))
        for i, p in enumerate(points)
    )
    samples = tuple(
        points[next(i for i, p in enumerate(originals) if p is sample)] for sample in samples
    )
    intervals = tuple(
        replace(p, id=f"capital-{i}", source_refs=(f"synthetic#capital-{i}",))
        for i, p in enumerate(intervals)
    )
    result = metrics_report(
        points, metrics_start_ms=0, daily_samples=samples, utilization=intervals
    )
    assert metric(result, "sharpe").value is not None
    assert not result.complete  # Capital phase ambiguity is not resolved by equal equity.


def test_global_reference_cannot_substitute_for_record_provenance():
    result = analyze(D(100), (EquityPoint(0, D(100)),), (), (), (), ("global",))
    assert not result.structural_complete
    assert "missing_equity_id:0" in result.issues
    assert "missing_equity_source_refs:0" in result.issues


@pytest.mark.parametrize(
    "kind", ["equity", "contribution", "opportunity", "recovery", "utilization", "daily_sample"]
)
def test_each_record_requires_immutable_identity_and_unique_nonempty_refs(kind):
    records = {
        "equity": EquityPoint(0, D(100)),
        "contribution": contributions()[0],
        "opportunity": Opportunity(0, "BTCUSDT", "long", "breakout", "detected", None),
        "recovery": RecoveryEpisode(0, 0, D(100), D(100)),
        "utilization": UtilizationInterval(0, 1, D(0), D(0), D(100)),
        "daily_sample": EquityPoint(0, D(100)),
    }

    def build(record, duplicate=False):
        values = (record, record) if duplicate else (record,)
        return analyze(
            D(100),
            values if kind == "equity" else curve(),
            values if kind == "contribution" else (),
            values if kind == "opportunity" else (),
            values if kind == "recovery" else (),
            ("global",),
            daily_samples=values if kind == "daily_sample" else (),
            utilization=values if kind == "utilization" else (),
        )

    refs = ["artifact#row-1"]
    record = replace(records[kind], id="record-1", source_refs=refs)
    refs.append("later mutation")
    assert record.source_refs == ("artifact#row-1",)
    assert f"missing_{kind}_source_refs:record-1" not in build(record).issues
    assert f"missing_{kind}_source_refs:record-1" in build(replace(record, source_refs=())).issues
    for malformed in (("",), ("source", "source")):
        with pytest.raises(ValueError):
            build(replace(record, source_refs=malformed))
    with pytest.raises(ValueError):
        build(replace(record, id=" "))
    with pytest.raises(ValueError):
        build(record, duplicate=True)


def test_grouped_opportunities_retain_source_observation_identity():
    events = tuple(
        Opportunity(
            i, "BTCUSDT", "long", "breakout", stage, None, f"event-{i}", (f"synthetic#event-{i}",)
        )
        for i, stage in enumerate(("detected", "filled"))
    )
    result = analyze(D(100), curve(), contributions(), events, (), ("global",))
    group = result.opportunity_episodes[0]
    assert group.observation_ids == ("event-0", "event-1")
    assert group.source_refs == ("synthetic#event-0", "synthetic#event-1")


@pytest.mark.parametrize("change", [{"id": "unrelated"}, {"source_refs": ("different-source",)}])
def test_daily_samples_bind_to_exact_retained_equity_records(change):
    points = tuple(
        EquityPoint(i * DAY, D(v), f"mark-{i}", (f"synthetic#mark-{i}",))
        for i, v in enumerate((100, 110, 100))
    )
    samples = (points[0], replace(points[1], **change), points[-1])
    result = metrics_report(points, metrics_start_ms=0, daily_samples=samples)
    assert metric(result, "sharpe").value is None
    assert metric(result, "sharpe").unavailable_reason == "incomplete_or_unmatched_daily_samples"


@pytest.mark.parametrize("timestamp", [0, 3])
def test_opportunity_outside_equity_window_is_retained_but_incomplete(timestamp):
    points = curve()[1:]
    event = Opportunity(
        timestamp, "BTCUSDT", "long", "breakout", "detected", None, "event", ("synthetic#event",)
    )
    result = analyze(D(100), points, (), (event,), (), ("source",))
    assert "opportunity_outside_equity_window" in result.issues
    assert not result.structural_complete and result.opportunities == (event,)


def test_utilization_cannot_be_calculated_from_equity_only():
    points = (EquityPoint(0, D(100)), EquityPoint(DAY, D(100)))
    interval = UtilizationInterval(0, DAY, D(50), D(0), D(100))
    result = metrics_report(points, metrics_start_ms=0, utilization=(interval,))
    assert metric(result, "utilization").value is None
    assert (
        metric(result, "utilization").unavailable_reason
        == "unverified_terminal_capital_observation"
    )


def capital_fixture():
    points = tuple(
        EquityPoint(i * DAY, D(v), f"equity-{i}", (f"synthetic#equity-{i}",))
        for i, v in enumerate((100, 110, 100))
    )
    observation = CapitalObservation(
        0,
        D(100),
        D(20),
        D(30),
        id="capital-0",
        phase_id="synthetic-source-event-0",
        equity_observation_id="equity-0",
        source_refs=("synthetic#capital-0",),
    )
    interval = UtilizationInterval(
        0,
        DAY,
        D(20),
        D(30),
        D(100),
        "interval-0",
        ("synthetic#interval-0",),
        observation_id="capital-0",
    )
    later = replace(
        observation,
        timestamp_ms=DAY,
        equity=D(110),
        spot_value=D(22),
        futures_collateral=D(33),
        id="capital-1",
        phase_id="phase-1",
        equity_observation_id="equity-1",
        source_refs=("synthetic#capital-1",),
    )
    second = replace(
        interval,
        start_ms=DAY,
        end_ms=2 * DAY,
        equity=D(110),
        spot_value=D(22),
        futures_collateral=D(33),
        id="interval-1",
        observation_id="capital-1",
        source_refs=("synthetic#interval-1",),
    )
    terminal = replace(
        observation,
        timestamp_ms=2 * DAY,
        id="capital-terminal",
        phase_id="terminal",
        equity_observation_id="equity-2",
        source_refs=("synthetic#terminal",),
    )
    return points, observation, interval, later, second, terminal


def capital_report(points, observations, intervals):
    return metrics_report(
        points,
        metrics_start_ms=0,
        daily_samples=points,
        utilization=intervals,
        capital_observations=observations,
    )


def test_exact_capital_observation_allows_utilization_and_is_retained():
    points, observation, interval, later, second, terminal = capital_fixture()
    result = capital_report(points, (observation, later, terminal), (interval, second))
    assert result.complete
    assert metric(result, "utilization").value == D(".5")
    assert result.capital_observations == (observation, later, terminal)


@pytest.mark.parametrize(
    "change",
    [
        {"observation_id": None},
        {"observation_id": "foreign"},
        {"spot_value": D(21)},
        {"futures_collateral": D(31)},
        {"equity": D(101)},
    ],
)
def test_utilization_rejects_unlinked_or_altered_capital_components(change):
    points, observation, interval, later, second, terminal = capital_fixture()
    result = capital_report(
        points, (observation, later, terminal), (replace(interval, **change), second)
    )
    assert not result.complete and metric(result, "utilization").value is None


@pytest.mark.parametrize(
    "change",
    [
        {"equity_observation_id": "foreign"},
        {"phase_id": None},
        {"source_refs": ()},
        {"timestamp_ms": 1},
        {"equity": D(101)},
    ],
)
def test_capital_observation_requires_exact_equity_identity_and_provenance(change):
    points, observation, interval, later, second, terminal = capital_fixture()
    result = capital_report(
        points, (replace(observation, **change), later, terminal), (interval, second)
    )
    assert not result.complete and metric(result, "utilization").value is None


def test_equal_equity_capital_phase_ambiguity_remains_incomplete():
    points, observation, interval, later, second, terminal = capital_fixture()
    after = replace(points[0], id="after-buy", source_refs=("synthetic#after-buy",))
    after_capital = replace(
        observation,
        id="capital-after",
        phase_id="after-buy",
        equity_observation_id=after.id,
        spot_value=D(70),
    )
    retained = (points[0], after, *points[1:])
    for observations in ((observation,), (observation, after_capital)):
        result = capital_report(retained, (*observations, later, terminal), (interval, second))
        assert metric(result, "utilization").value is None
        assert not result.complete


@pytest.mark.parametrize(
    "change",
    [{"id": ""}, {"phase_id": " "}, {"spot_value": D(-1)}, {"source_refs": ("same", "same")}],
)
def test_invalid_capital_observation_is_rejected(change):
    points, observation, interval, later, second, terminal = capital_fixture()
    with pytest.raises(ValueError):
        capital_report(
            points, (replace(observation, **change), later, terminal), (interval, second)
        )


def test_capital_observation_duplicate_ids_are_not_deduplicated():
    points, observation, interval, later, second, terminal = capital_fixture()
    with pytest.raises(ValueError):
        capital_report(points, (observation, observation), (interval,))


def test_utilization_interval_cannot_skip_an_intervening_capital_observation():
    points, observation, interval, later, second, terminal = capital_fixture()
    later = replace(
        observation,
        timestamp_ms=DAY,
        equity=D(110),
        spot_value=D(70),
        id="capital-1",
        phase_id="phase-1",
        equity_observation_id="equity-1",
    )
    result = capital_report(
        points, (observation, later, terminal), (replace(interval, end_ms=2 * DAY),)
    )
    assert metric(result, "utilization").value is None and not result.complete


def test_complete_report_cannot_hide_out_of_window_opportunity():
    points, observation, interval, later, second, terminal = capital_fixture()
    assert capital_report(points, (observation, later, terminal), (interval, second)).complete
    event = Opportunity(
        2 * DAY + 1, "BTCUSDT", "long", "breakout", "detected", None, "event", ("source",)
    )
    result = analyze(
        D(100),
        points,
        (),
        (event,),
        (),
        ("global",),
        metrics_start_ms=0,
        daily_samples=points,
        utilization=(interval, second),
        capital_observations=(observation, later, terminal),
    )
    assert "opportunity_outside_equity_window" in result.issues
    assert not result.complete and result.opportunities == (event,)


def test_same_time_capital_phases_are_ambiguous_even_with_one_equity_record():
    points, observation, interval, later, second, terminal = capital_fixture()
    other = replace(observation, id="other", phase_id="other-phase", spot_value=D(70))
    result = capital_report(points, (observation, other, later, terminal), (interval, second))
    assert not result.complete and metric(result, "utilization").value is None


def test_capital_source_refs_are_immutable_and_opportunities_without_equity_are_incomplete():
    points, observation, interval, later, second, terminal = capital_fixture()
    refs = ["source"]
    observation = replace(observation, source_refs=refs)
    refs.append("mutated")
    assert observation.source_refs == ("source",)
    event = Opportunity(0, "BTCUSDT", "long", "breakout", "detected", None, "event", ("source",))
    result = analyze(D(100), (), (), (event,), (), ("global",))
    assert not result.complete and "missing_equity_observations" in result.issues
    assert result.opportunities == (event,)


@pytest.mark.parametrize("equity", [D(0), D(-1)])
def test_recovered_equity_cannot_hide_nonpositive_retained_mark(equity):
    points = (
        EquityPoint(0, D(100), "start", ("source",)),
        EquityPoint(1, equity, "failure", ("source",)),
        EquityPoint(2, D(100), "end", ("source",)),
    )
    result = analyze(D(100), points, (), (), (), ("global",))
    assert "nonpositive_equity_observation" in result.issues
    assert not result.structural_complete and result.final_equity == 100


def test_utilization_interval_cannot_skip_equity_without_capital_observation():
    points, observation, interval, later, second, terminal = capital_fixture()
    result = capital_report(points, (observation,), (replace(interval, end_ms=2 * DAY),))
    assert metric(result, "utilization").value is None


@pytest.mark.parametrize(
    "stages",
    [
        ("filled", "detected"),
        ("detected", "submitted", "qualified"),
        ("detected", "blocked", "filled"),
        ("invented",),
    ],
)
def test_invalid_opportunity_stages_remain_visible_but_incomplete(stages):
    events = tuple(
        Opportunity(
            i,
            "BTCUSDT",
            "long",
            "breakout",
            stage,
            "cost" if stage == "blocked" else None,
            f"event-{i}",
            ("source",),
        )
        for i, stage in enumerate(stages)
    )
    points = (curve()[0], replace(curve()[-1], timestamp_ms=len(stages)))
    result = analyze(D(100), points, contributions(), events, (), ("global",))
    assert any(issue.startswith("invalid_opportunity_") for issue in result.issues)
    assert not result.structural_complete and result.opportunities == events


def test_repeated_detections_restart_local_funnel_without_splitting_episode():
    stages = ("detected", "qualified", "detected", "detected", "qualified", "filled", "filled")
    events = tuple(
        Opportunity(i, "BTCUSDT", "long", "breakout", stage, None, f"event-{i}", ("source",))
        for i, stage in enumerate(stages)
    )
    points = (curve()[0], replace(curve()[-1], timestamp_ms=len(stages)))
    result = analyze(D(100), points, contributions(), events, (), ("global",))
    assert result.structural_complete and len(result.opportunity_episodes) == 1


def test_open_marked_lifecycle_with_exit_reason_is_incomplete():
    rows = (contributions()[0], replace(contributions()[1], exit_reason="trail"))
    result = analyze(D(100), curve(), rows, (), (), ("global",))
    assert "open_marked_exit_reason" in result.issues
    assert not result.structural_complete and result.contributions == rows


@pytest.mark.parametrize("equity", [D(0), D(-1)])
def test_nonpositive_interior_mark_is_not_hidden_by_positive_daily_samples(equity):
    daily, observation, interval, later, second, terminal = capital_fixture()
    failed = EquityPoint(DAY // 2, equity, "failed", ("source",))
    points = (daily[0], failed, *daily[1:])
    result = analyze(
        D(100),
        points,
        (),
        (),
        (),
        ("global",),
        metrics_start_ms=0,
        daily_samples=daily,
        utilization=(interval, second),
        capital_observations=(observation, later, terminal),
    )
    assert metric(result, "sharpe").value is not None
    assert result.final_equity == 100 and "nonpositive_equity_observation" in result.issues
    assert not result.complete and not result.structural_complete


@pytest.mark.parametrize(
    "stages,reasons",
    [
        (("filled", "detected"), (None, None)),
        (("blocked",), ("cost",)),
        (("detected", "blocked"), (None, None)),
    ],
)
def test_same_time_reversed_or_unexplained_blocked_observations_are_incomplete(stages, reasons):
    events = tuple(
        Opportunity(0, "BTCUSDT", "long", "breakout", stage, reason, f"event-{i}", ("source",))
        for i, (stage, reason) in enumerate(zip(stages, reasons, strict=True))
    )
    result = analyze(D(100), curve(), contributions(), events, (), ("source",))
    assert not result.structural_complete and result.opportunities == events
    assert any(issue.startswith("invalid_opportunity_stage_order") for issue in result.issues)


def test_new_detection_can_follow_blocked_disposition_in_same_episode():
    stages = ("detected", "blocked", "detected", "filled")
    events = tuple(
        Opportunity(
            0,
            "BTCUSDT",
            "long",
            "breakout",
            stage,
            "cost" if stage == "blocked" else None,
            f"event-{i}",
            ("source",),
        )
        for i, stage in enumerate(stages)
    )
    result = analyze(D(100), curve(), contributions(), events, (), ("source",))
    assert result.structural_complete and len(result.opportunity_episodes) == 1


def test_terminal_capital_state_is_required_even_when_equity_is_unique():
    points, observation, interval, later, second, terminal = capital_fixture()
    result = capital_report(points, (observation, later), (interval, second))
    assert not result.complete
    assert (
        metric(result, "utilization").unavailable_reason
        == "unverified_terminal_capital_observation"
    )


def test_equal_equity_terminal_phases_cannot_select_a_complete_report():
    points, observation, interval, later, second, terminal = capital_fixture()
    after = replace(points[-1], id="terminal-after", source_refs=("source-after",))
    terminal = replace(
        observation,
        timestamp_ms=2 * DAY,
        id="terminal-capital",
        phase_id="after",
        equity_observation_id=after.id,
    )
    retained = (*points, after)
    result = metrics_report(
        retained,
        metrics_start_ms=0,
        daily_samples=(*points[:-1], after),
        utilization=(interval, second),
        capital_observations=(observation, later, terminal),
    )
    assert not result.complete
    assert (
        metric(result, "utilization").unavailable_reason
        == "unverified_terminal_capital_observation"
    )


@pytest.mark.parametrize(
    "bounds,expected",
    [
        (((0, 2), (1, 2)), "overlapping_recovery_episodes"),
        (((1, 2), (0, 1)), "nonchronological_recovery_episodes"),
        (((0, None), (1, 2)), "overlapping_recovery_episodes"),
        (((0, 1), (0, 1)), "overlapping_recovery_episodes"),
    ],
)
def test_recovery_sequence_preserves_but_rejects_impossible_episodes(bounds, expected):
    points = curve()
    episodes = tuple(
        RecoveryEpisode(
            start,
            end,
            points[start].equity,
            points[end].equity if end is not None else None,
            f"recovery-{i}",
            ("source",),
        )
        for i, (start, end) in enumerate(bounds)
    )
    result = analyze(D(100), points, contributions(), (), episodes, ("source",))
    assert expected in result.issues and not result.structural_complete
    assert result.recovery == episodes


def test_adjacent_recovery_episodes_are_not_overlap():
    points = curve()
    episodes = tuple(
        RecoveryEpisode(
            i, i + 1, points[i].equity, points[i + 1].equity, f"recovery-{i}", ("source",)
        )
        for i in range(2)
    )
    result = analyze(D(100), points, contributions(), (), episodes, ("source",))
    assert result.structural_complete


@pytest.mark.parametrize(
    "change",
    [{"phase_id": None}, {"source_refs": ()}, {"equity_observation_id": "equity-0"}, {"id": None}],
)
def test_terminal_capital_requires_phase_provenance_and_exact_equity_link(change):
    points, observation, interval, later, second, terminal = capital_fixture()
    result = capital_report(
        points, (observation, later, replace(terminal, **change)), (interval, second)
    )
    assert not result.complete
    assert (
        metric(result, "utilization").unavailable_reason
        == "unverified_terminal_capital_observation"
    )


def test_multiple_terminal_capital_phases_are_not_selected_by_equal_equity():
    points, observation, interval, later, second, terminal = capital_fixture()
    after = replace(terminal, id="terminal-after", phase_id="after", spot_value=D(80))
    result = capital_report(points, (observation, later, terminal, after), (interval, second))
    assert not result.complete
    assert (
        metric(result, "utilization").unavailable_reason
        == "unverified_terminal_capital_observation"
    )
