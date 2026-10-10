from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.combined.report import (
    Contribution,
    EquityPoint,
    Opportunity,
    RecoveryEpisode,
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
    assert report.complete
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
    assert report.complete
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
