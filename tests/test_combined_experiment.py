import math
from dataclasses import replace
from decimal import Decimal, localcontext

import combined_market_fixtures as fx
import pytest
from test_combined_baseline_minute import CONFIG, ENGINE, T0, candle, run_config

from crypto_grid_bot.combined.baseline_hold import HoldMarket, replay_hold_baseline
from crypto_grid_bot.combined.baseline_minute import MinuteJob, replay_grid_baseline
from crypto_grid_bot.combined.baseline_records import (
    BaselineEvidence,
    NativeMark,
    comparison_report,
)
from crypto_grid_bot.combined.common_series import FROZEN_REF
from crypto_grid_bot.combined.experiment import (
    SCENARIOS,
    Capital,
    Registration,
    ReportEvidence,
    RunIdentity,
    RunOutcome,
    Window,
    capital_label,
    evaluate,
)
from crypto_grid_bot.combined.observation_policy import POLICY_ID, Boundary, PolicyEvidence
from crypto_grid_bot.combined.outcomes import baseline_outcome
from crypto_grid_bot.combined.report import (
    CapitalObservation,
    Contribution,
    EquityPoint,
    UtilizationInterval,
    analyze,
)

D = Decimal

HOUR = 3_600_000
DAY = 86_400_000
PIN = "a" * 64
CODE = "b" * 40
V1_VARIANTS = ("a",)


def minute_baselines(variants=V1_VARIANTS):
    return tuple(
        name
        for mode in ("high_first", "low_first")
        for name in (
            f"matched_v0_grid_{mode}",
            *(f"matched_v1_{variant}_grid_{mode}" for variant in variants),
            f"matched_v2_grid_{mode}",
            f"matched_d_trend_{mode}",
        )
    )


V2 = "matched_v2_grid_high_first"
BASELINES = (
    "unchanged_v3_selector",
    *(f"unchanged_v3_r{i}_long_only" for i in range(1, 7)),
    "matched_spot_hold",
    *minute_baselines(),
)
ARMS = (
    *BASELINES,
    "spot_trend",
    "futures_trend",
    "futures_trend_long_only",
    "spot_grid",
    "combined",
    "combined_without_continuation",
    "combined_without_full_short_qualification",
    "combined_without_discretionary_trailing",
    "combined_without_funding_admission",
    "combined_without_recovery",
)


def registration() -> Registration:
    return Registration(
        ARMS,
        BASELINES,
        (Window("window", 0, 2 * DAY, PIN),),
        (
            Capital("research", D(10000), "USDT", D(10000)),
            Capital("owner_small", D(110), "EUR", D(100), D("1.1"), PIN),
        ),
        ((1, PIN), (2, "c" * 64)),
        CODE,
        PIN,
        observation_policy=POLICY_ID,
        adapter_pins=tuple((arm, PIN) for arm in ARMS),
        scenarios=SCENARIOS,
        v1_variants=V1_VARIANTS,
    )


def outcomes(reg: Registration) -> tuple[RunOutcome, ...]:
    rows = []
    for arm in reg.arms:
        for window in reg.windows:
            for capital in reg.capitals:
                for multiple, cost_pin in reg.cost_profiles:
                    for scenario in ("native",) if arm in reg.baseline_arms else SCENARIOS:
                        identity = RunIdentity(
                            arm,
                            window.id,
                            capital.id,
                            multiple,
                            window.data_pin,
                            cost_pin,
                            window.start_ms,
                            window.end_ms,
                            reg.code_pin,
                            reg.config_pin,
                            capital.fx_pin if capital.id == "owner_small" else None,
                            reg.observation_policy,
                            dict(reg.adapter_pins).get(arm),
                            scenario,
                        )
                        multiplier = D("1.4") if arm == "combined" else D("1.1")
                        rows.append(
                            RunOutcome(
                                identity,
                                capital.initial_equity,
                                capital.initial_equity * multiplier,
                                D(".2"),
                                0,
                                D(0),
                                True,
                                True,
                                False,
                                f"{arm}-{window.id}-{capital.id}-{multiple}-{scenario}",
                                True,
                            )
                        )
    return tuple(with_report(row) for row in rows)


def with_report(row, *, hourly=True, missing=(), marks=None, skipped=()):
    """``missing`` hours carry no mark; ``marks`` replaces the equity at given hours.

    ``skipped`` are the skipped hours the report is built against.
    """
    if not all(
        value.is_finite()
        for value in (
            row.initial_equity,
            row.final_equity,
            row.max_drawdown,
            row.accounting_residual,
        )
    ):
        return row
    start, end = row.identity.start_ms, row.identity.end_ms
    points = tuple(
        EquityPoint(
            timestamp,
            (marks or {}).get(
                timestamp,
                row.initial_equity
                if timestamp == start
                else row.final_equity
                if timestamp == end
                else row.initial_equity * (1 - row.max_drawdown),
            ),
            f"point-{timestamp}",
            ("synthetic-hourly",),
        )
        for timestamp in range(start, end + 1, 3_600_000 if hourly else DAY)
        if timestamp not in missing
    )
    with localcontext() as ctx:
        ctx.prec = 80
        gross = row.final_equity - row.initial_equity - row.accounting_residual
    contributions = (
        Contribution(
            "pnl",
            "trend",
            "BTC",
            "long",
            None,
            gross,
            D(0),
            D(0),
            D(1),
            "exit",
            start,
            "closed",
            end,
            source_refs=("synthetic-pnl",),
        ),
    )
    report = analyze(
        row.initial_equity,
        points,
        contributions,
        (),
        (),
        ("synthetic-source",),
        metrics_start_ms=start,
        daily_samples=tuple(p for p in points if (p.timestamp_ms - start) % DAY == 0),
        utilization=tuple(
            UtilizationInterval(
                point.timestamp_ms,
                following.timestamp_ms,
                D(0),
                D(0),
                point.equity,
                f"utilization-{index}",
                ("synthetic-capital",),
                observation_id=f"capital-{index}",
            )
            for index, (point, following) in enumerate(zip(points, points[1:], strict=False))
        ),
        capital_observations=tuple(
            CapitalObservation(
                point.timestamp_ms,
                point.equity,
                D(0),
                D(0),
                id=f"capital-{index}",
                phase_id=(
                    "opening"
                    if index == 0
                    else "terminal"
                    if index == len(points) - 1
                    else "settled"
                ),
                equity_observation_id=point.id,
                source_refs=("synthetic-capital",),
            )
            for index, point in enumerate(points)
        ),
        policy_evidence=PolicyEvidence(
            POLICY_ID,
            PIN,
            tuple(
                Boundary(
                    point.timestamp_ms,
                    (
                        "opening"
                        if index == 0
                        else "terminal"
                        if index == len(points) - 1
                        else "settled"
                    ),
                    (point.id,),
                    point.id,
                    f"capital-{index}",
                    ("synthetic-capital",),
                    point.timestamp_ms - (3_600_000 if index == len(points) - 1 else 0),
                    point.timestamp_ms + (0 if index == len(points) - 1 else 3_600_000),
                )
                for index, point in enumerate(points)
            ),
            scenario=row.identity.scenario,
        ),
        skipped_hours=skipped,
    )
    return replace(row, report_evidence=ReportEvidence(row.identity, row.attempt_id, report))


def change(rows, arm="combined", cost=1, capital="research", **updates):
    return tuple(
        with_report(replace(row, **updates))
        if (row.identity.arm, row.identity.cost_multiple, row.identity.capital)
        == (arm, cost, capital)
        and row.identity.scenario in (SCENARIOS[0], "native")
        else row
        for row in rows
    )


def test_complete_matrix_passes_and_all_results_are_retained() -> None:
    reg = registration()
    rows = outcomes(reg)
    result = evaluate(reg, rows)
    assert result.status == "pass"
    assert result.outcomes == rows and not result.failures and not result.incomplete_reasons


def test_registration_requires_approved_observation_policy_and_adapter_pins():
    reg = registration()
    result = evaluate(replace(reg, observation_policy=None, adapter_pins=()), outcomes(reg))
    assert result.status == "incomplete"
    assert any("observation policy" in issue for issue in result.incomplete_reasons)


def test_report_sampling_policy_cannot_differ_from_run_identity():
    reg = registration()
    rows = outcomes(reg)
    row = rows[0]
    evidence = row.report_evidence
    assert evidence is not None and evidence.report.policy_evidence is not None
    bad_policy = replace(evidence.report.policy_evidence, adapter_pin="e" * 64)
    bad_report = replace(evidence.report, policy_evidence=bad_policy)
    bad_row = replace(row, report_evidence=replace(evidence, report=bad_report))
    assert evaluate(reg, (bad_row, *rows[1:])).status == "incomplete"


@pytest.mark.parametrize("malformed", [False, True])
def test_missing_policy_retains_risk_but_explicit_foreign_policy_is_unattributable(malformed):
    reg = registration()
    rows = outcomes(reg)
    row = next(r for r in rows if r.identity.arm == "combined")
    adverse = with_report(replace(row, max_drawdown=D(".4")))
    report = adverse.report_evidence.report
    rebuilt = analyze(
        report.initial_equity,
        report.equity_points,
        report.contributions,
        report.opportunities,
        report.recovery,
        report.source_refs,
        metrics_start_ms=report.metrics_start_ms,
        daily_samples=report.daily_samples,
        utilization=report.utilization,
        capital_observations=report.capital_observations,
        policy_evidence={} if malformed else replace(report.policy_evidence, policy_id="invalid"),
    )
    # Missing policy cannot hide attributable raw risk; an explicitly different
    # policy identifies foreign evidence and cannot assign its risk to this run.
    adverse = replace(row, report_evidence=ReportEvidence(row.identity, row.attempt_id, rebuilt))
    result = evaluate(reg, tuple(adverse if r is row else r for r in rows))
    assert result.status == ("fail" if malformed else "incomplete")
    assert any("drawdown" in failure for failure in result.failures) is malformed


def test_full_must_beat_every_baseline_on_both_measures_not_best_ablation() -> None:
    reg = registration()
    rows = change(outcomes(reg), arm=V2, final_equity=D(15000))
    assert evaluate(reg, rows).status == "fail"
    rows = change(outcomes(reg), arm=V2, max_drawdown=D(".01"))
    assert evaluate(reg, rows).status == "fail"
    rows = change(outcomes(reg), final_equity=D(11000))
    assert evaluate(reg, rows).status == "fail"


@pytest.mark.parametrize("cost", [1, 2])
def test_full_drawdown_limit_inclusive_at_both_costs_and_never_reset(cost: int) -> None:
    reg = registration()
    assert evaluate(reg, change(outcomes(reg), cost=cost, max_drawdown=D(".30"))).status == "pass"
    assert (
        evaluate(reg, change(outcomes(reg), cost=cost, max_drawdown=D(".30000000001"))).status
        == "fail"
    )


def test_doubled_full_profit_must_be_strictly_positive_in_both_capitals() -> None:
    reg = registration()
    assert (
        evaluate(
            reg, change(outcomes(reg), cost=2, capital="owner_small", final_equity=D(110))
        ).status
        == "fail"
    )


@pytest.mark.parametrize(
    "updates",
    [
        {"liquidations": 1},
        {"wallet_quantity_exact": False},
        {"accounting_residual": D("1e-19"), "accounting_explained": False},
        {"accounting_residual": D("1.1e-18")},
    ],
)
def test_component_integrity_failure_is_not_hidden_by_full_profit(updates: dict) -> None:
    reg = registration()
    assert evaluate(reg, change(outcomes(reg), arm="spot_grid", **updates)).status == "fail"


def test_explained_residual_tolerance_is_only_for_trade_equity() -> None:
    reg = registration()
    rows = change(outcomes(reg), accounting_residual=D("-1e-18"))
    assert evaluate(reg, rows).status == "pass"
    rows = change(rows, wallet_quantity_exact=False)
    assert evaluate(reg, rows).status == "fail"


def test_historic_baseline_loss_and_drawdown_are_not_new_full_gates() -> None:
    reg = registration()
    rows = change(outcomes(reg), arm=V2, max_drawdown=D(".8"), final_equity=D(9000))
    assert evaluate(reg, rows).status == "pass"
    rows = change(rows, arm=V2, liquidations=1)
    assert evaluate(reg, rows).status == "incomplete"


@pytest.mark.parametrize("target", ["combined", V2])
def test_zero_drawdown_is_indeterminate_not_infinite_score(target: str) -> None:
    reg = registration()
    assert (
        evaluate(reg, change(outcomes(reg), arm=target, max_drawdown=D(0))).status == "incomplete"
    )


def test_missing_failed_and_duplicate_runs_are_preserved_without_selecting_retry() -> None:
    reg = registration()
    rows = outcomes(reg)
    assert evaluate(reg, rows[:-1]).status == "incomplete"
    failed = change(rows, failed=True, complete=False)
    result = evaluate(reg, failed)
    assert result.status == "incomplete" and result.outcomes == failed
    repeated = (*rows, replace(rows[0], attempt_id="retry"))
    result = evaluate(reg, repeated)
    assert result.status == "incomplete" and result.outcomes == repeated


@pytest.mark.parametrize(
    "field,value",
    [
        ("data_pin", "d" * 64),
        ("cost_profile_pin", "d" * 64),
        ("start_ms", 1),
        ("code_pin", "d" * 40),
        ("config_pin", "d" * 64),
    ],
)
def test_mismatched_identity_never_counts_as_matched_comparison(field: str, value: object) -> None:
    reg = registration()
    rows = list(outcomes(reg))
    rows[0] = replace(rows[0], identity=replace(rows[0].identity, **{field: value}))
    assert evaluate(reg, tuple(rows)).status == "incomplete"


def test_wrong_initial_capital_and_nonfinite_metrics_do_not_pass() -> None:
    reg = registration()
    assert evaluate(reg, change(outcomes(reg), initial_equity=D(100))).status == "incomplete"
    assert evaluate(reg, change(outcomes(reg), final_equity=D("NaN"))).status == "incomplete"


@pytest.mark.parametrize(
    "alter", ["fx", "arms", "baseline", "placeholder", "pending", "pin", "cost", "dates"]
)
def test_unfrozen_or_reduced_registration_cannot_pass(alter: str) -> None:
    reg = registration()
    rows = outcomes(reg)
    if alter == "fx":
        reg = replace(reg, capitals=(reg.capitals[0], replace(reg.capitals[1], fx_pin=None)))
    elif alter == "arms":
        reg = replace(reg, arms=tuple(a for a in reg.arms if a != "spot_grid"))
    elif alter == "baseline":
        reg = replace(reg, baseline_arms=())
    elif alter == "placeholder":
        reg = replace(reg, arms=(*reg.arms, "matched_spot_baselines"))
    elif alter == "pending":
        reg = replace(reg, pending=("unreviewed",))
    elif alter == "pin":
        reg = replace(reg, code_pin="short")
    elif alter == "cost":
        reg = replace(reg, cost_profiles=((1, PIN),))
    else:
        reg = replace(reg, windows=(replace(reg.windows[0], end_ms=1_735_689_600_001),))
    assert evaluate(reg, rows).status == "incomplete"


def test_known_failure_and_missing_matrix_both_remain_visible() -> None:
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))[:-1]
    result = evaluate(reg, rows)
    assert result.status == "fail"
    assert result.failures and result.incomplete_reasons


def test_boolean_timestamp_cannot_impersonate_registered_integer() -> None:
    reg = registration()
    rows = list(outcomes(reg))
    rows[0] = replace(rows[0], identity=replace(rows[0].identity, start_ms=False))
    assert evaluate(reg, tuple(rows)).status == "incomplete"


def test_reused_attempt_id_across_different_cells_is_not_independent_evidence() -> None:
    reg = registration()
    rows = list(outcomes(reg))
    rows[1] = replace(rows[1], attempt_id=rows[0].attempt_id)
    assert evaluate(reg, tuple(rows)).status == "incomplete"


@pytest.mark.parametrize(
    "updates",
    [
        {"failed": True, "liquidations": 1},
        {"complete": False, "max_drawdown": D(".5")},
    ],
)
def test_unfinished_attempt_preserves_known_failure(updates) -> None:
    reg = registration()
    result = evaluate(reg, change(outcomes(reg), **updates))
    assert result.status == "fail"
    assert result.failures and result.incomplete_reasons


def test_repeated_attempt_preserves_known_failure() -> None:
    reg = registration()
    rows = outcomes(reg)
    full = next(row for row in rows if row.identity.arm == "combined")
    result = evaluate(reg, rows + (replace(full, attempt_id="retry", max_drawdown=D(".5")),))
    assert result.status == "fail"
    assert result.failures and result.incomplete_reasons


def test_doubled_cost_must_beat_matched_baselines() -> None:
    reg = registration()
    result = evaluate(reg, change(outcomes(reg), arm=V2, cost=2, final_equity=D(20000)))
    assert result.status == "fail"


def test_doubled_cost_zero_drawdown_is_indeterminate() -> None:
    reg = registration()
    result = evaluate(reg, change(outcomes(reg), cost=2, max_drawdown=D(0)))
    assert result.status == "incomplete"


def test_partial_observation_does_not_fail_unfinished_profit() -> None:
    reg = registration()
    result = evaluate(reg, change(outcomes(reg), cost=2, complete=False, final_equity=D(9000)))
    assert result.status == "incomplete" and not result.failures


def test_partial_accounting_failure_survives_invalid_final_metric() -> None:
    reg = registration()
    result = evaluate(
        reg, change(outcomes(reg), complete=False, final_equity=D("NaN"), accounting_residual=D(1))
    )
    assert result.status == "fail" and result.incomplete_reasons


def test_mismatched_attempt_cannot_supply_attributable_failure() -> None:
    reg = registration()
    rows = outcomes(reg)
    full = next(row for row in rows if row.identity.arm == "combined")
    result = evaluate(
        reg,
        rows
        + (
            replace(
                full,
                attempt_id="foreign",
                identity=replace(full.identity, code_pin="d" * 40),
                max_drawdown=D(".5"),
            ),
        ),
    )
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize(
    "updates",
    [
        {"max_drawdown": D(".5")},
        {"liquidations": 1},
        {"accounting_residual": D(1)},
        {"wallet_quantity_exact": False},
    ],
)
def test_pending_registration_preserves_attributable_safety_failures(updates):
    reg = registration()
    result = evaluate(replace(reg, pending=("review",)), change(outcomes(reg), **updates))
    assert result.status == "fail"
    assert result.failures and result.incomplete_reasons


@pytest.mark.parametrize("alter", ["window", "capital", "arm", "profile", "identity"])
def test_incomplete_registration_does_not_attribute_ambiguous_or_invalid_identity(alter):
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    if alter == "window":
        reg = replace(reg, windows=reg.windows * 2)
    elif alter == "capital":
        reg = replace(reg, capitals=reg.capitals + (reg.capitals[0],))
    elif alter == "arm":
        reg = replace(reg, arms=reg.arms + ("combined",))
    elif alter == "profile":
        reg = replace(reg, cost_profiles=reg.cost_profiles + (reg.cost_profiles[0],))
    else:
        rows = tuple(
            replace(row, identity=replace(row.identity, code_pin="d" * 40)) for row in rows
        )
        reg = replace(reg, pending=("review",))
    result = evaluate(reg, rows)
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize("alter", ["pin", "boolean_time", "capital_mismatch"])
def test_registration_failure_does_not_promote_unattributable_safety_metrics(alter):
    reg = replace(registration(), pending=("review",))
    rows = change(outcomes(reg), max_drawdown=D(".5"), liquidations=1)
    if alter == "pin":
        reg = replace(reg, code_pin="invalid")
    elif alter == "boolean_time":
        rows = tuple(replace(row, identity=replace(row.identity, start_ms=False)) for row in rows)
    elif alter == "capital_mismatch":
        rows = change(rows, initial_equity=D(9999))
    result = evaluate(reg, rows)
    assert result.status == "incomplete" and not result.failures


def test_unrelated_duplicate_capital_does_not_erase_unique_research_failure():
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    result = evaluate(replace(reg, capitals=reg.capitals + (reg.capitals[1],)), rows)
    assert result.status == "fail" and result.incomplete_reasons


def test_scalar_completeness_cannot_replace_report_evidence():
    reg = registration()
    rows = tuple(replace(row, report_evidence=None) for row in outcomes(reg))
    assert evaluate(reg, rows).status == "incomplete"


def test_base_and_doubled_cost_profiles_must_have_distinct_pins():
    reg = replace(registration(), cost_profiles=((1, PIN), (2, PIN)))
    assert evaluate(reg, outcomes(reg)).status == "incomplete"


@pytest.mark.parametrize(
    "alter",
    [
        "complete_flag",
        "daily_samples",
        "utilization",
        "identity",
        "attempt",
        "window",
        "initial",
        "final",
        "drawdown",
        "residual",
        "forged_metrics",
    ],
)
def test_report_must_supply_matching_recomputable_evidence(alter):
    reg = registration()
    rows = list(outcomes(reg))
    row = rows[0]
    evidence = row.report_evidence
    report = evidence.report
    if alter == "complete_flag":
        report = replace(report, complete=False)
    elif alter == "daily_samples":
        report = replace(report, daily_samples=())
    elif alter == "utilization":
        report = replace(report, utilization=())
    elif alter == "identity":
        evidence = replace(evidence, identity=replace(evidence.identity, arm="combined"))
    elif alter == "attempt":
        evidence = replace(evidence, attempt_id="other-attempt")
    elif alter == "window":
        report = replace(report, metrics_start_ms=DAY)
    elif alter == "initial":
        report = replace(report, initial_equity=D(9999))
    elif alter == "final":
        report = replace(report, final_equity=D(11001))
    elif alter == "drawdown":
        report = replace(report, max_drawdown=D(".19"))
    elif alter == "residual":
        report = replace(report, reconciliation_residual=D("1e-19"))
    else:
        report = replace(
            report, metrics=tuple(replace(metric, value=D(42)) for metric in report.metrics)
        )
    rows[0] = replace(row, report_evidence=replace(evidence, report=report))
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures


def test_missing_report_preserves_observed_safety_failure():
    reg = registration()
    rows = tuple(
        replace(row, report_evidence=None) for row in change(outcomes(reg), max_drawdown=D(".5"))
    )
    result = evaluate(reg, rows)
    assert result.status == "fail" and result.incomplete_reasons


@pytest.mark.parametrize(
    "field,value",
    [("final_equity", D(11001)), ("max_drawdown", D(".19")), ("accounting_residual", D("1e-19"))],
)
def test_complete_unrelated_report_cannot_validate_scalar_results(field, value):
    reg = registration()
    rows = list(outcomes(reg))
    assert rows[0].report_evidence.report.complete
    rows[0] = replace(rows[0], **{field: value})
    assert evaluate(reg, tuple(rows)).status == "incomplete"


def test_recomputed_report_from_other_observation_window_is_incomplete():
    reg = registration()
    rows = list(outcomes(reg))
    row = rows[0]
    foreign = with_report(
        replace(row, identity=replace(row.identity, start_ms=DAY, end_ms=3 * DAY))
    )
    assert foreign.report_evidence.report.complete
    # Even relabeling the supplied wrapper cannot disguise different observation times.
    rows[0] = replace(
        row, report_evidence=replace(row.report_evidence, report=foreign.report_evidence.report)
    )
    assert evaluate(reg, tuple(rows)).status == "incomplete"


@pytest.mark.parametrize("complete", [False, True])
def test_omitted_wallet_verification_is_unknown_not_observed_mismatch(complete):
    reg = registration()
    rows = list(outcomes(reg))
    index = next(i for i, row in enumerate(rows) if row.identity.arm == "combined")
    old = rows[index]
    rows[index] = RunOutcome(
        old.identity,
        old.initial_equity,
        old.final_equity,
        old.max_drawdown,
        old.liquidations,
        old.accounting_residual,
        accounting_explained=True,
        complete=complete,
        attempt_id=old.attempt_id,
        report_evidence=old.report_evidence,
    )
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures
    assert rows[index].wallet_quantity_exact is None


@pytest.mark.parametrize(
    "updates", [{"liquidations": 1}, {"max_drawdown": D(".5")}, {"accounting_residual": D(1)}]
)
def test_unknown_wallet_verification_preserves_other_observed_failures(updates):
    reg = registration()
    rows = change(outcomes(reg), wallet_quantity_exact=None, complete=False, **updates)
    result = evaluate(reg, rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert not any("wallet/quantity" in reason for reason in result.failures)


@pytest.mark.parametrize(
    ("end", "valid"), [(1_735_689_600_000, True), (1_735_689_600_000 + 86_400_000, False)]
)
def test_a_window_may_end_at_but_never_after_the_reserved_boundary(end, valid):
    reg = registration()
    window = replace(reg.windows[0], end_ms=end)
    changed = replace(reg, windows=(window,))
    rows = tuple(
        replace(row, identity=replace(row.identity, end_ms=window.end_ms))
        for row in change(outcomes(reg), max_drawdown=D(".5"))
    )
    result = evaluate(changed, rows)
    invalid = "registration: invalid window dates or data pin" in result.incomplete_reasons
    assert invalid is not valid


@pytest.mark.parametrize("wallet", [None, False, True])
def test_unverified_terminal_loss_requires_report_but_observed_wallet_mismatch_does_not(wallet):
    reg = registration()
    rows = change(outcomes(reg), cost=2, final_equity=D(9000), wallet_quantity_exact=wallet)
    rows = tuple(replace(row, report_evidence=None) for row in rows)
    result = evaluate(reg, rows)
    assert result.status == ("fail" if wallet is False else "incomplete")
    assert not any("profit is not positive" in reason for reason in result.failures)


@pytest.mark.parametrize("equity", [D(0), D(-1)])
def test_component_recovery_cannot_hide_capital_exhaustion(equity):
    reg = registration()
    rows = list(outcomes(reg))
    index = next(i for i, row in enumerate(rows) if row.identity.arm != "combined")
    row = rows[index]
    evidence = row.report_evidence
    original = evidence.report
    points = (
        original.equity_points[0],
        EquityPoint(row.identity.start_ms + 1_800_000, equity, "exhaustion", ("synthetic",)),
        *original.equity_points[1:],
    )
    report = analyze(
        row.initial_equity,
        points,
        original.contributions,
        (),
        (),
        original.source_refs,
        metrics_start_ms=original.metrics_start_ms,
        daily_samples=original.daily_samples,
        utilization=original.utilization,
        capital_observations=original.capital_observations,
    )
    assert "nonpositive_equity_observation" in report.issues
    rows[index] = replace(
        row, max_drawdown=report.max_drawdown, report_evidence=replace(evidence, report=report)
    )
    assert evaluate(reg, tuple(rows)).status != "pass"


@pytest.mark.parametrize("start,end", [(1, 2 * DAY + 1), (0, DAY), (0, 2 * DAY + 1)])
def test_registration_rejects_windows_incompatible_with_required_daily_metrics(start, end):
    reg = registration()
    reg = replace(reg, windows=(replace(reg.windows[0], start_ms=start, end_ms=end),))
    result = evaluate(reg, ())
    assert (
        "registration: daily metrics require UTC day endpoints and at least two days"
        in result.incomplete_reasons
    )


@pytest.mark.parametrize("updates", [{"liquidations": 1}, {"wallet_quantity_exact": False}])
def test_one_observed_integrity_failure_has_one_message_even_with_complete_report(updates):
    reg = registration()
    complete = evaluate(reg, change(outcomes(reg), **updates))
    partial = evaluate(reg, change(outcomes(reg), complete=False, **updates))
    assert len(complete.failures) == len(partial.failures) == 1
    assert complete.failures == partial.failures


def concealed_report_failure(reg, *, arm="combined", report_updates=None, wrapper_updates=None):
    rows = list(outcomes(reg))
    index = next(i for i, row in enumerate(rows) if row.identity.arm == arm)
    observed = with_report(replace(rows[index], **(report_updates or {"max_drawdown": D(".5")})))
    rows[index] = replace(
        observed,
        **({"max_drawdown": D(".2"), "accounting_residual": D(0)} | (wrapper_updates or {})),
    )
    return tuple(rows), index


@pytest.mark.parametrize(
    "updates",
    [
        {},
        {"final_equity": D("NaN")},
        {"max_drawdown": D("NaN")},
        {"accounting_residual": D("NaN")},
        {"initial_equity": D("NaN")},
        {"initial_equity": D(9999)},
        {"complete": False},
        {"wallet_quantity_exact": None},
    ],
)
@pytest.mark.parametrize("pending", [False, True])
def test_matching_recomputed_report_breach_survives_wrapper_disagreement(updates, pending):
    reg = registration()
    rows, _ = concealed_report_failure(reg, wrapper_updates=updates)
    result = evaluate(replace(reg, pending=("review",)) if pending else reg, rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert len(result.failures) == 1 and "maximum drawdown" in result.failures[0]


@pytest.mark.parametrize("kind", ["accounting", "zero_equity", "negative_equity"])
def test_component_report_safety_evidence_survives_clean_wrapper(kind):
    reg = registration()
    updates = (
        {"accounting_residual": D(1)}
        if kind == "accounting"
        else {"max_drawdown": D(1) if kind == "zero_equity" else D("1.1")}
    )
    rows, _ = concealed_report_failure(reg, arm="spot_grid", report_updates=updates)
    result = evaluate(reg, rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert any(
        ("accounting" if kind == "accounting" else "capital exhaustion") in reason
        for reason in result.failures
    )


@pytest.mark.parametrize("alter", ["identity", "attempt", "window", "capital", "forged"])
def test_unattributable_report_cannot_introduce_safety_failure(alter):
    reg = registration()
    rows, index = concealed_report_failure(reg)
    rows = list(rows)
    row = rows[index]
    evidence = row.report_evidence
    if alter == "identity":
        evidence = replace(evidence, identity=replace(row.identity, code_pin="d" * 40))
    elif alter == "attempt":
        evidence = replace(evidence, attempt_id="foreign")
    elif alter == "window":
        foreign = with_report(
            replace(
                row,
                identity=replace(row.identity, start_ms=DAY, end_ms=3 * DAY),
                max_drawdown=D(".5"),
            )
        )
        evidence = replace(evidence, report=foreign.report_evidence.report)
    elif alter == "capital":
        foreign = with_report(replace(row, initial_equity=D(9999), max_drawdown=D(".5")))
        evidence = replace(evidence, report=foreign.report_evidence.report)
    else:
        evidence = replace(evidence, report=replace(evidence.report, max_drawdown=D(".6")))
    rows[index] = replace(row, report_evidence=evidence)
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures


def test_same_report_and_scalar_drawdown_breach_is_one_safety_category():
    reg = registration()
    result = evaluate(reg, change(outcomes(reg), max_drawdown=D(".5")))
    assert result.status == "fail" and len(result.failures) == 1


def test_duplicate_outcome_does_not_erase_report_breach():
    reg = registration()
    rows, index = concealed_report_failure(reg)
    result = evaluate(reg, (*rows, rows[index]))
    assert result.status == "fail" and result.incomplete_reasons


@pytest.mark.parametrize("pending", [False, True])
def test_unavailable_report_metrics_cannot_hide_observed_drawdown(pending):
    reg = registration()
    rows, index = concealed_report_failure(reg)
    rows = list(rows)
    evidence = rows[index].report_evidence
    report = evidence.report
    partial = analyze(
        report.initial_equity,
        report.equity_points,
        report.contributions,
        report.opportunities,
        report.recovery,
        report.source_refs,
        metrics_start_ms=report.metrics_start_ms,
        daily_samples=(),
        utilization=report.utilization,
        capital_observations=report.capital_observations,
    )
    assert not partial.complete
    rows[index] = replace(rows[index], report_evidence=replace(evidence, report=partial))
    result = evaluate(replace(reg, pending=("review",)) if pending else reg, tuple(rows))
    assert result.status == "fail" and any("maximum drawdown" in item for item in result.failures)


@pytest.mark.parametrize(
    "residual,explained,status",
    [(D("1e-18"), True, "incomplete"), (D("1e-18"), False, "fail"), (D("1.1e-18"), True, "fail")],
)
def test_report_accounting_observations_preserve_explained_tolerance(residual, explained, status):
    reg = registration()
    rows, _ = concealed_report_failure(
        reg,
        arm="spot_grid",
        report_updates={"accounting_residual": residual, "accounting_explained": explained},
    )
    assert evaluate(reg, rows).status == status


def test_baseline_report_drawdown_does_not_acquire_component_safety_threshold():
    reg = registration()
    rows, _ = concealed_report_failure(reg, arm=V2)
    result = evaluate(reg, rows)
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize("initial", [D(9999), D("NaN")])
@pytest.mark.parametrize("updates", [{"liquidations": 1}, {"wallet_quantity_exact": False}])
@pytest.mark.parametrize("pending", [False, True])
def test_wrong_capital_scalar_safety_is_retained_but_not_attributed(initial, updates, pending):
    reg = registration()
    rows = change(outcomes(reg), initial_equity=initial, **updates)
    rows = tuple(replace(row, report_evidence=None) for row in rows)
    result = evaluate(replace(reg, pending=("review",)) if pending else reg, rows)
    assert result.status == "incomplete" and not result.failures
    assert result.outcomes == rows


@pytest.mark.parametrize("window_id", [1, True, "   ", "\t", "", [], {}])
def test_window_identity_requires_nonblank_string(window_id):
    reg = registration()
    reg = replace(reg, windows=(replace(reg.windows[0], id=window_id),))
    result = evaluate(reg, outcomes(reg))
    assert result.status == "incomplete"
    assert "registration: invalid window dates or data pin" in result.incomplete_reasons


@pytest.mark.parametrize("equity", [D(0), D(-1)])
def test_scalar_terminal_exhaustion_survives_missing_report(equity):
    reg = registration()
    rows = change(outcomes(reg), arm="spot_trend", final_equity=equity)
    rows = tuple(replace(row, report_evidence=None) for row in rows)
    result = evaluate(reg, rows)
    assert result.status == "fail"
    assert any("observed capital exhaustion" in reason for reason in result.failures)


def test_malformed_baseline_classification_cannot_hide_component_failure():
    reg = registration()
    rows = change(outcomes(reg), liquidations=1, max_drawdown=D(".5"))
    malformed = replace(reg, baseline_arms=(*reg.baseline_arms, "combined"))
    result = evaluate(malformed, rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert any("observed liquidation" in reason for reason in result.failures)
    assert any("maximum drawdown" in reason for reason in result.failures)


@pytest.mark.parametrize("wrong_capital", [D(9999), D("NaN")])
def test_foreign_scalar_exhaustion_not_imported_through_matching_report(wrong_capital):
    reg = registration()
    rows = list(outcomes(reg))
    index = next(i for i, row in enumerate(rows) if row.identity.arm == "spot_trend")
    rows[index] = replace(rows[index], initial_equity=wrong_capital, final_equity=D(0))
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize(
    "bad", [(2, []), (2, {}), ([], PIN), None, (), (2,), (2, PIN, "extra"), "invalid"]
)
def test_malformed_cost_profile_returns_incomplete_without_crashing(bad):
    reg = registration()
    rows = outcomes(reg)
    malformed = replace(reg, cost_profiles=(reg.cost_profiles[0], bad))
    result = evaluate(malformed, rows)
    assert result.status == "incomplete" and result.outcomes == rows
    assert "registration: base and doubled cost profiles required" in result.incomplete_reasons


@pytest.mark.parametrize("profiles", [None, 1, "invalid"])
def test_malformed_cost_profile_collection_is_incomplete(profiles):
    reg = registration()
    result = evaluate(replace(reg, cost_profiles=profiles), outcomes(reg))
    assert result.status == "incomplete" and not result.failures


def test_owner_small_outcomes_cannot_cross_same_rate_different_fx_pins():
    reg = registration()
    foreign = replace(reg, capitals=(reg.capitals[0], replace(reg.capitals[1], fx_pin="d" * 64)))
    rows = outcomes(reg)
    result = evaluate(foreign, rows)
    assert result.status == "incomplete" and not result.failures


def test_foreign_fx_outcome_cannot_attribute_component_safety_failure():
    reg = registration()
    foreign = replace(
        reg,
        capitals=(reg.capitals[0], replace(reg.capitals[1], fx_pin="d" * 64)),
        pending=("review",),
    )
    rows = change(outcomes(reg), capital="owner_small", max_drawdown=D(".5"))
    result = evaluate(foreign, rows)
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize("bad", [(2, []), (2,), None, ()])
def test_malformed_other_cost_profile_keeps_unique_base_failure(bad):
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    result = evaluate(replace(reg, cost_profiles=(reg.cost_profiles[0], bad)), rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert len(result.failures) == 1


@pytest.mark.parametrize("bad", [(1, []), (1,), (True, PIN)])
def test_malformed_matching_cost_declaration_is_not_silently_dropped(bad):
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    result = evaluate(replace(reg, cost_profiles=(*reg.cost_profiles, bad)), rows)
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("fx_pin", [None, "d" * 64, [], 1])
def test_missing_or_foreign_owner_fx_identity_cannot_attribute_results(fx_pin, pending):
    reg = registration()
    rows = change(outcomes(reg), capital="owner_small", max_drawdown=D(".5"))
    rows = tuple(
        replace(row, identity=replace(row.identity, fx_pin=fx_pin))
        if row.identity.capital == "owner_small"
        else row
        for row in rows
    )
    result = evaluate(replace(reg, pending=("review",)) if pending else reg, rows)
    assert result.status == "incomplete" and not result.failures


def test_relabelled_owner_wrapper_cannot_import_foreign_fx_report_safety():
    reg = registration()
    original = replace(reg, capitals=(reg.capitals[0], replace(reg.capitals[1], fx_pin="d" * 64)))
    rows = list(outcomes(reg))
    foreign_rows = change(outcomes(original), capital="owner_small", max_drawdown=D(".5"))
    index = next(
        i
        for i, row in enumerate(rows)
        if row.identity.arm == "combined"
        and row.identity.capital == "owner_small"
        and row.identity.cost_multiple == 1
    )
    rows[index] = replace(rows[index], report_evidence=foreign_rows[index].report_evidence)
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures


def test_legacy_research_identity_needs_no_fx_conversion_pin():
    reg = registration()
    rows = outcomes(reg)
    assert all(row.identity.fx_pin is None for row in rows if row.identity.capital == "research")
    assert all(row.identity.fx_pin == PIN for row in rows if row.identity.capital == "owner_small")
    assert evaluate(reg, rows).status == "pass"


@pytest.mark.parametrize("field", ["windows", "capitals"])
@pytest.mark.parametrize("bad", [None, {}, [], 1, "record"])
def test_malformed_registration_record_is_retained_as_incomplete(field, bad):
    reg = registration()
    rows = outcomes(reg)
    malformed = replace(reg, **{field: (bad,)})
    result = evaluate(malformed, rows)
    assert result.status == "incomplete" and not result.failures
    assert result.outcomes == rows


@pytest.mark.parametrize("field", ["windows", "capitals"])
@pytest.mark.parametrize("bad", [None, 1, "records"])
def test_malformed_registration_record_collection_is_incomplete(field, bad):
    reg = registration()
    result = evaluate(replace(reg, **{field: bad}), outcomes(reg))
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize("field", ["windows", "capitals"])
def test_unrelated_malformed_registration_record_does_not_erase_known_failure(field):
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    malformed = replace(reg, **{field: (*getattr(reg, field), None)})
    result = evaluate(malformed, rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert any("maximum drawdown" in reason for reason in result.failures)


@pytest.mark.parametrize("flag", [None, 1, "yes", [], {}])
@pytest.mark.parametrize("pending", [False, True])
def test_only_exact_true_explanation_can_tolerate_observed_residual(flag, pending):
    reg = registration()
    rows = change(outcomes(reg), accounting_residual=D("1e-19"), accounting_explained=flag)
    result = evaluate(replace(reg, pending=("review",)) if pending else reg, rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert len(result.failures) == 1 and "invalid accounting" in result.failures[0]


@pytest.mark.parametrize("field", ["arms", "baseline_arms"])
@pytest.mark.parametrize("bad", [None, 1, "combined", {"combined"}, {"combined": True}])
def test_malformed_arm_menu_collection_is_incomplete(field, bad):
    reg = registration()
    rows = outcomes(reg)
    result = evaluate(replace(reg, **{field: bad}), rows)
    assert result.status == "incomplete" and not result.failures
    assert result.outcomes == rows


@pytest.mark.parametrize("field", ["arms", "baseline_arms"])
@pytest.mark.parametrize("bad", [None, [], {}, 1, "", "   "])
def test_malformed_arm_menu_entry_is_incomplete(field, bad):
    reg = registration()
    rows = outcomes(reg)
    result = evaluate(replace(reg, **{field: (*getattr(reg, field), bad)}), rows)
    assert result.status == "incomplete" and not result.failures
    assert result.outcomes == rows


@pytest.mark.parametrize("field", ["arms", "baseline_arms"])
@pytest.mark.parametrize("bad", [[], {}, "   "])
def test_malformed_arm_menu_entry_preserves_attributable_component_failure(field, bad):
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    result = evaluate(replace(reg, **{field: (*getattr(reg, field), bad)}), rows)
    assert result.status == "fail" and result.incomplete_reasons
    assert len(result.failures) == 1 and "maximum drawdown" in result.failures[0]


def test_malformed_arm_menu_does_not_make_duplicate_component_unambiguous():
    reg = registration()
    rows = change(outcomes(reg), max_drawdown=D(".5"))
    result = evaluate(replace(reg, arms=(*reg.arms, [], "combined")), rows)
    assert result.status == "incomplete" and not result.failures


@pytest.mark.parametrize("field", ["arms", "baseline_arms"])
@pytest.mark.parametrize("container", [set, dict.fromkeys])
def test_complete_arm_menu_in_unsupported_collection_is_incomplete(field, container):
    reg = registration()
    result = evaluate(replace(reg, **{field: container(getattr(reg, field))}), outcomes(reg))
    assert result.status == "incomplete" and not result.failures


def test_common_hourly_comparison_refuses_sparse_native_boundary_series():
    reg = registration()
    rows = outcomes(reg)
    changed = with_report(rows[0], hourly=False)
    result = evaluate(reg, (changed, *rows[1:]))
    assert result.status == "incomplete"
    assert any("common hourly" in issue for issue in result.incomplete_reasons)


def test_missing_common_hourly_series_does_not_hide_verified_doubled_cost_loss():
    reg = registration()
    rows = change(outcomes(reg), cost=2, final_equity=D(9000))
    rows = tuple(with_report(row, hourly=False) for row in rows)
    result = evaluate(reg, rows)
    assert result.status == "fail"
    assert any("profit is not positive" in reason for reason in result.failures)


def test_both_modeled_scenarios_are_mandatory_and_not_pooled():
    reg = registration()
    rows = outcomes(reg)
    assert {r.identity.scenario for r in rows if r.identity.arm == "combined"} == {
        "open_low_high_close",
        "open_high_low_close",
    }
    missing = tuple(r for r in rows if r.identity.scenario != "open_high_low_close")
    result = evaluate(reg, missing)
    assert result.status == "incomplete"
    assert any("open_high_low_close" in reason for reason in result.incomplete_reasons)


def test_other_scenario_cannot_hide_drawdown_or_doubled_cost_loss():
    reg = registration()
    rows = list(outcomes(reg))
    index = next(
        i
        for i, r in enumerate(rows)
        if r.identity.arm == "combined"
        and r.identity.scenario == SCENARIOS[1]
        and r.identity.cost_multiple == 2
    )
    rows[index] = with_report(
        replace(rows[index], max_drawdown=D(".4"), final_equity=rows[index].initial_equity)
    )
    result = evaluate(reg, tuple(rows))
    assert result.status == "fail"
    assert any(
        "maximum drawdown" in reason and SCENARIOS[1] in reason for reason in result.failures
    )
    assert any(
        "profit is not positive" in reason and SCENARIOS[1] in reason for reason in result.failures
    )


def test_report_cannot_be_reused_under_other_scenario_identity():
    reg = registration()
    rows = list(outcomes(reg))
    index = next(i for i, r in enumerate(rows) if r.identity.arm == "combined")
    row = rows[index]
    evidence = row.report_evidence
    policy = replace(evidence.report.policy_evidence, scenario=SCENARIOS[1])
    rows[index] = replace(
        row,
        report_evidence=replace(evidence, report=replace(evidence.report, policy_evidence=policy)),
    )
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete"
    assert any("report evidence" in reason for reason in result.incomplete_reasons)


@pytest.mark.parametrize("scenarios", [(), (SCENARIOS[0],), SCENARIOS[::-1], [*SCENARIOS]])
def test_registration_requires_explicit_fixed_scenario_menu(scenarios):
    reg = registration()
    result = evaluate(replace(reg, scenarios=scenarios), outcomes(reg))
    assert result.status == "incomplete"
    assert any("modeled scenarios" in reason for reason in result.incomplete_reasons)


@pytest.mark.parametrize("scenario", [None, [], "unknown"])
def test_malformed_scenario_identity_is_incomplete(scenario):
    reg = registration()
    rows = list(outcomes(reg))
    rows[0] = replace(rows[0], identity=replace(rows[0].identity, scenario=scenario))
    assert evaluate(reg, tuple(rows)).status == "incomplete"


def test_foreign_scenario_report_cannot_assign_its_drawdown_to_other_account():
    reg = registration()
    rows = list(outcomes(reg))
    index = next(i for i, row in enumerate(rows) if row.identity.arm == "combined")
    original = rows[index]
    adverse = with_report(replace(original, max_drawdown=D(".4"))).report_evidence
    foreign = replace(adverse.report.policy_evidence, scenario=SCENARIOS[1])
    rows[index] = replace(
        original,
        report_evidence=replace(adverse, report=replace(adverse.report, policy_evidence=foreign)),
    )
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete"
    assert not result.failures


@pytest.mark.parametrize("field", ["policy_id", "adapter_pin"])
def test_foreign_adapter_report_cannot_assign_safety(field):
    reg = registration()
    rows = list(outcomes(reg))
    index = next(i for i, row in enumerate(rows) if row.identity.arm == "combined")
    original = rows[index]
    adverse = with_report(replace(original, max_drawdown=D(".4"))).report_evidence
    foreign = replace(adverse.report.policy_evidence, **{field: "foreign"})
    rows[index] = replace(
        original,
        report_evidence=replace(adverse, report=replace(adverse.report, policy_evidence=foreign)),
    )
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete"
    assert not result.failures


@pytest.mark.parametrize("attempt", [1, True, [], "   "])
def test_malformed_attempt_id_is_incomplete(attempt):
    reg = registration()
    rows = list(outcomes(reg))
    row = rows[0]
    rows[0] = replace(
        row, attempt_id=attempt, report_evidence=replace(row.report_evidence, attempt_id=attempt)
    )
    assert evaluate(reg, tuple(rows)).status == "incomplete"


@pytest.mark.parametrize("field", ["observation_policy", "adapter_pin"])
def test_pending_registration_rejects_foreign_scalar_policy_identity(field):
    reg = replace(registration(), pending=("review",))
    row = next(row for row in outcomes(reg) if row.identity.arm == "combined")
    row = replace(
        row,
        report_evidence=None,
        liquidations=1,
        identity=replace(row.identity, **{field: "d" * 64}),
    )
    result = evaluate(reg, (row,))
    assert result.status == "incomplete"
    assert not result.failures


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        "identity=None",
        {"arm": []},
        {"window": []},
        {"capital": " "},
        {"cost_multiple": "1"},
        {"scenario": ["open_low_high_close"]},
    ],
)
@pytest.mark.parametrize("pending", [False, True])
def test_malformed_outcome_records_are_incomplete_not_crashes(malformed, pending):
    reg = registration()
    rows = outcomes(reg)
    assert evaluate(reg, rows).status == "pass"
    if malformed is None:
        bad = None
    elif malformed == "identity=None":
        bad = replace(rows[0], identity=None)
    else:
        bad = replace(rows[0], identity=replace(rows[0].identity, **malformed))
    if pending:
        reg = replace(reg, pending=("x",))
    result = evaluate(reg, (*rows, bad))
    assert result.status == "incomplete"
    assert "1 malformed outcome record(s) retained" in result.incomplete_reasons
    assert result.outcomes[-1] is bad


def drop_arms(reg, names):
    def kept(arms):
        return tuple(arm for arm in arms if arm not in names)

    return replace(
        reg,
        arms=kept(reg.arms),
        baseline_arms=kept(reg.baseline_arms),
        adapter_pins=tuple(pair for pair in reg.adapter_pins if pair[0] not in names),
    )


def add_arms(reg, names):
    return replace(
        reg,
        arms=(*reg.arms, *names),
        baseline_arms=(*reg.baseline_arms, *names),
        adapter_pins=(*reg.adapter_pins, *((name, PIN) for name in names)),
    )


V1_ARMS = ("matched_v1_a_grid_high_first", "matched_v1_a_grid_low_first")
VARIANTS_REASON = "registration: a nonempty list of unique V1 variant names required"


@pytest.mark.parametrize(
    "alter,reason",
    [
        ("no_v1", VARIANTS_REASON),
        ("v1_arms", "registration: baselines missing: " + ", ".join(V1_ARMS)),
        (
            "no_d",
            "registration: baselines missing: matched_d_trend_high_first, "
            "matched_d_trend_low_first",
        ),
        ("v0_one_mode", "registration: baselines missing: matched_v0_grid_low_first"),
        ("v1_one_mode", "registration: baselines missing: matched_v1_a_grid_low_first"),
        ("old_name", "registration: baselines outside the documented names: matched_v2"),
        (
            "unregistered_variant",
            "registration: baselines outside the documented names: "
            "matched_v1_b_grid_high_first, matched_v1_b_grid_low_first",
        ),
        ("upper_variant", VARIANTS_REASON),
        ("plus_variant", VARIANTS_REASON),
        ("repeated_variant", VARIANTS_REASON),
        ("list_variants", VARIANTS_REASON),
    ],
)
def test_registration_requires_every_baseline_family_in_both_path_modes(alter, reason):
    reg = registration()
    rows = outcomes(reg)
    if alter == "no_v1":
        reg = replace(drop_arms(reg, V1_ARMS), v1_variants=())
    elif alter == "v1_arms":
        reg = drop_arms(reg, V1_ARMS)
    elif alter == "no_d":
        reg = drop_arms(reg, {"matched_d_trend_high_first", "matched_d_trend_low_first"})
    elif alter == "v0_one_mode":
        reg = drop_arms(reg, {"matched_v0_grid_low_first"})
    elif alter == "v1_one_mode":
        reg = drop_arms(reg, {"matched_v1_a_grid_low_first"})
    elif alter == "old_name":
        reg = add_arms(reg, ("matched_v2",))
    elif alter == "unregistered_variant":
        reg = add_arms(reg, ("matched_v1_b_grid_high_first", "matched_v1_b_grid_low_first"))
    elif alter == "upper_variant":
        reg = replace(reg, v1_variants=("A",))
    elif alter == "plus_variant":
        reg = replace(reg, v1_variants=("c+g",))
    elif alter == "repeated_variant":
        reg = replace(reg, v1_variants=("a", "a"))
    else:
        reg = replace(reg, v1_variants=["a"])
    result = evaluate(reg, rows)
    assert result.status == "incomplete" and not result.failures
    assert reason in result.incomplete_reasons


def test_complete_matrix_with_every_family_and_two_v1_variants_passes():
    reg = registration()
    names = minute_baselines(("a", "cg"))
    reg = replace(
        add_arms(reg, tuple(name for name in names if name not in reg.baseline_arms)),
        v1_variants=("a", "cg"),
    )
    rows = outcomes(reg)
    result = evaluate(reg, rows)
    assert result.status == "pass", result.incomplete_reasons
    assert {row.identity.arm for row in rows} >= set(names)


SKIP = 5 * HOUR
SKIP_REASON = (
    "registration: skipped hours must be sorted hours strictly inside the window, "
    "never its first or last hour"
)


def skipping(reg, hours=(SKIP,)):
    return replace(reg, windows=tuple(replace(w, skipped_hours=hours) for w in reg.windows))


def remarked(row, **options):
    """Rebuild the report with ``options``, carrying its observed drawdown."""
    observed = with_report(row, **options)
    return replace(observed, max_drawdown=observed.report_evidence.report.max_drawdown)


def cell(rows, arm, capital="research", cost=1, scenario=SCENARIOS[0]):
    return next(
        index
        for index, row in enumerate(rows)
        if (row.identity.arm, row.identity.capital, row.identity.cost_multiple)
        == (arm, capital, cost)
        and row.identity.scenario in (scenario, "native")
    )


def test_skipped_hours_compare_every_arm_on_the_remaining_hours():
    reg = registration()
    rows = list(change(outcomes(reg), arm=V2, final_equity=D(13000)))
    full = cell(rows, "combined")
    # Compared at 05:00, the full arm's 28% dip leaves 0.40/0.28 below V2's 0.30/0.20.
    rows[full] = remarked(rows[full], marks={SKIP: D(7200)})
    assert rows[full].max_drawdown == D(".28")
    compared = evaluate(reg, tuple(rows))
    assert compared.status == "fail"
    assert any(V2 in reason and "return/drawdown" in reason for reason in compared.failures)
    skipped = evaluate(skipping(reg), tuple(rows))
    assert skipped.status == "pass", (skipped.failures, skipped.incomplete_reasons)
    assert skipped.skipped_hours == (("window", (SKIP,)),)


def test_an_unscheduled_missing_mark_does_not_make_the_comparison_incomplete():
    reg = registration()
    gapped = {"combined", "matched_spot_hold", "matched_d_trend_low_first"}
    rows = tuple(
        with_report(row, missing=(SKIP,)) if row.identity.arm in gapped else row
        for row in outcomes(reg)
    )
    result = evaluate(skipping(reg), rows)
    assert result.status == "pass", result.incomplete_reasons
    scheduled = evaluate(reg, rows)
    assert scheduled.status == "incomplete" and not scheduled.failures
    assert any("common hourly" in reason for reason in scheduled.incomplete_reasons)


def test_a_skipped_hour_keeps_its_native_mark_for_the_drawdown_gate():
    reg = skipping(registration())
    rows = list(outcomes(reg))
    full = cell(rows, "combined")
    rows[full] = remarked(rows[full], marks={SKIP: D(6500)})
    result = evaluate(reg, tuple(rows))
    assert result.status == "fail"
    assert any("maximum drawdown exceeds" in reason for reason in result.failures)


@pytest.mark.parametrize(
    "skipped",
    [
        (0,),  # the opening hour
        (2 * DAY - HOUR,),  # the last hour, whose close is the terminal mark
        (2 * DAY,),  # the terminal
        (6 * HOUR, SKIP),
        (SKIP, SKIP),
        (SKIP + 1,),
        (-HOUR,),
        (True,),
        [SKIP],
        None,
    ],
)
def test_registration_rejects_skipped_opening_last_or_unsorted_hours(skipped):
    reg = skipping(registration(), skipped)
    result = evaluate(reg, outcomes(reg))
    assert result.status == "incomplete" and not result.failures
    assert SKIP_REASON in result.incomplete_reasons


STOP_MS = 11 * HOUR - 1  # an intrabar mark late in the 10:00 hour


def frozen_baseline(
    reg, *, stop_equity, status="liquidation", liquidations=1, arm="unchanged_v3_r1_long_only"
):
    """Replace the research, base-cost cell of ``arm`` by a run stopped at ``STOP_MS``."""
    rows = list(outcomes(reg))
    index = cell(rows, arm)
    identity = rows[index].identity
    marks = (
        NativeMark(0, "open", D(10000), D(0), D(5000)),
        *(NativeMark(hour * HOUR, "open", D(9000), D(0), D(4500)) for hour in range(1, 11)),
        NativeMark(STOP_MS, "adverse", stop_equity, D(0), D(100)),
    )
    lifecycle = Contribution(
        "life",
        "unchanged_v3",
        "BTC",
        "long",
        None,
        stop_equity - D(10000),
        D(0),
        D(0),
        D(1),
        None,
        0,
        "open_marked",
        source_refs=("synthetic",),
    )
    report = comparison_report(
        arm,
        marks,
        (lifecycle,),
        initial=D(10000),
        start_ms=identity.start_ms,
        end_ms=identity.end_ms,
        source_refs=("synthetic",),
        adapter_pin=PIN,
        native_stop=status,
    )
    evidence = BaselineEvidence(
        arm, "v3-native", marks, report, status, liquidations, D(0), True, True, ()
    )
    rows[index] = baseline_outcome(evidence, identity, attempt_id=rows[index].attempt_id)
    return rows, index


def test_a_baseline_liquidated_mid_window_is_complete_frozen_and_must_be_beaten():
    reg = registration()
    rows, index = frozen_baseline(reg, stop_equity=D(4000))
    row = rows[index]
    assert row.complete and not row.failed
    assert row.native_stop == "liquidation" and row.liquidations == 1
    after = [p for p in row.report_evidence.report.equity_points if p.timestamp_ms > STOP_MS]
    assert [p.timestamp_ms for p in after] == list(range(11 * HOUR, 2 * DAY + 1, HOUR))
    assert all(p.equity == D(4000) for p in after)
    assert all(FROZEN_REF + "liquidation" in p.source_refs for p in after)
    assert evaluate(reg, tuple(rows)).status == "pass"
    rows, _ = frozen_baseline(reg, stop_equity=D(16000))
    result = evaluate(reg, tuple(rows))
    assert result.status == "fail"
    assert any(
        "unchanged_v3_r1_long_only" in reason and "full return does not strictly beat" in reason
        for reason in result.failures
    )
    assert any(
        "unchanged_v3_r1_long_only" in reason and "return/drawdown does not strictly" in reason
        for reason in result.failures
    )


@pytest.mark.parametrize("status", ["no_tradable_position", "leverage_not_restored"])
def test_every_native_v3_stop_is_a_finished_result(status):
    reg = registration()
    rows, index = frozen_baseline(reg, stop_equity=D(9500), status=status, liquidations=0)
    assert rows[index].native_stop == status and rows[index].complete
    assert evaluate(reg, tuple(rows)).status == "pass"


@pytest.mark.parametrize(
    "alter,reason",
    [
        ("no_stop", "frozen marks and native stop disagree"),
        ("other_stop", "frozen marks and native stop disagree"),
        ("liquidation_count", "liquidation or invalid accounting"),
        ("unknown_stop", "invalid metrics or initial capital"),
        ("component", "only a frozen V3 baseline can end at a native stop"),
    ],
)
def test_frozen_marks_need_the_matching_native_stop_of_a_baseline(alter, reason):
    reg = registration()
    rows, index = frozen_baseline(
        reg,
        stop_equity=D(4000),
        status="no_tradable_position",
        liquidations=int(alter == "liquidation_count"),
    )
    if alter == "no_stop":
        rows[index] = replace(rows[index], native_stop=None)
    elif alter == "other_stop":
        rows[index] = replace(rows[index], native_stop="leverage_not_restored")
    elif alter == "unknown_stop":
        rows[index] = replace(rows[index], native_stop="engine_failure")
    elif alter == "component":
        index = cell(rows, "spot_trend")
        rows[index] = replace(rows[index], native_stop="no_tradable_position")
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures
    assert any(reason in issue for issue in result.incomplete_reasons), result.incomplete_reasons


@pytest.mark.parametrize("arm", ["matched_spot_hold", V2, "matched_d_trend_low_first"])
def test_only_frozen_v3_baselines_can_end_at_a_native_stop(arm):
    reg = registration()
    rows, _ = frozen_baseline(
        reg, stop_equity=D(9500), status="no_tradable_position", liquidations=0, arm=arm
    )
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures
    assert any(
        arm in issue and "only a frozen V3 baseline can end at a native stop" in issue
        for issue in result.incomplete_reasons
    )


def test_a_report_cannot_claim_a_skipped_hour_the_registration_does_not_pin():
    reg = registration()
    rows = list(outcomes(reg))
    hold = cell(rows, "matched_spot_hold")
    rows[hold] = with_report(rows[hold], skipped=(DAY,))
    result = evaluate(reg, tuple(rows))
    assert result.status == "incomplete" and not result.failures
    assert any(
        "matched_spot_hold" in issue and "report evidence" in issue
        for issue in result.incomplete_reasons
    )
    assert evaluate(skipping(reg, (DAY,)), tuple(rows)).status == "pass"


MIDNIGHT = T0 + DAY  # 2024-02-05 00:00 UTC


def falling_minutes():
    """Three days of slowly swinging, 3% falling minutes without the 00:00 minute of day two."""
    fair = float(ENGINE.at(T0).fair_value)
    rows = []
    for index in range(3 * 1440):
        if index == 1440:
            continue
        price = fair * (1 + 0.02 * math.sin(index / 97.0)) * (1 - 0.03 * index / (3 * 1440))
        rows.append(candle(T0 + index * 60_000, price, price * 1.003, price * 0.997, price * 1.001))
    return tuple(rows)


def gap_registration(skipped=(MIDNIGHT,)):
    reg = registration()
    window = Window("window", T0, T0 + 3 * DAY, PIN, skipped_hours=skipped)
    return replace(reg, windows=(window,))


def adapter_cells(reg):
    """The research, base-cost hold and V0 grid cells, replayed by their adapters."""
    skipped = reg.windows[0].skipped_hours
    rows = list(outcomes(reg))
    hold = cell(rows, "matched_spot_hold")
    markets = {
        symbol: HoldMarket(
            tuple(b for b in fx.hourly(fx.downtrend, 72, start=T0) if b.open_ms != MIDNIGHT),
            fx.RULES,
            fx.COSTS,
        )
        for symbol in ("BTCUSDT", "ETHUSDT")
    }
    held = replay_hold_baseline(
        markets,
        start_ms=T0,
        end_ms=T0 + 3 * DAY,
        initial=D(10000),
        cost_multiple=1,
        source_refs=("synthetic:hold",),
        adapter_pin=PIN,
        skipped_hours=skipped,
    )
    rows[hold] = baseline_outcome(held, rows[hold].identity, attempt_id=rows[hold].attempt_id)
    grid = cell(rows, "matched_v0_grid_high_first")
    jobs = {
        symbol: MinuteJob(CONFIG, run_config(symbol), falling_minutes(), ENGINE)
        for symbol in ("AAAUSDT", "BBBUSDT")
    }
    gridded = replay_grid_baseline(
        "matched_v0_grid_high_first",
        jobs,
        start_ms=T0,
        end_ms=T0 + 3 * DAY,
        initial=D(10000),
        source_refs=("synthetic:grid",),
        adapter_pin=PIN,
        skipped_hours=skipped,
    )
    rows[grid] = baseline_outcome(gridded, rows[grid].identity, attempt_id=rows[grid].attempt_id)
    return rows, (hold, grid)


def test_a_skipped_midnight_keeps_the_hold_and_minute_baselines_complete():
    reg = gap_registration()
    rows, cells = adapter_cells(reg)
    for index in cells:
        row = rows[index]
        report = row.report_evidence.report
        assert row.complete and report.complete, report.issues
        assert MIDNIGHT not in {p.timestamp_ms for p in report.equity_points}
        sharpe = next(m for m in report.metrics if m.name == "sharpe")
        assert sharpe.value is not None and "2024-02-05" in sharpe.definition
    result = evaluate(reg, tuple(rows))
    assert result.status == "pass", (result.failures, result.incomplete_reasons)
    assert result.skipped_hours == (("window", (MIDNIGHT,)),)
    # Unregistered, the same gap leaves both cells incomplete.
    unregistered = evaluate(gap_registration(()), tuple(rows))
    assert unregistered.status == "incomplete" and not unregistered.failures
    for arm in ("matched_spot_hold", "matched_v0_grid_high_first"):
        assert any(arm in issue for issue in unregistered.incomplete_reasons)


def owner_small(rate, *, fx_pin=PIN):
    return Capital("owner_small", D(100) * D(rate), "EUR", D(100), D(rate), fx_pin)


@pytest.mark.parametrize("rate", ["1", "1.0", "0.49", "2.01", "100"])
def test_an_implausible_or_unit_fx_rate_never_labels_usdt_as_eur100(rate):
    # A rate of 1 would label 100 USDT as EUR100; outside 0.5-2.0 USD per EUR is no rate.
    reg = registration()
    reg = replace(reg, capitals=(reg.capitals[0], owner_small(rate)))
    result = evaluate(reg, outcomes(reg))
    assert result.status == "incomplete"
    assert any("plausible" in reason for reason in result.incomplete_reasons)
    with pytest.raises(ValueError):
        capital_label(owner_small(rate))


@pytest.mark.parametrize("rate", ["0.5", "1.08", "2.0"])
def test_a_plausible_fx_rate_registers_and_labels_currency_amount_rate_and_pin(rate):
    reg = registration()
    reg = replace(reg, capitals=(reg.capitals[0], owner_small(rate)))
    result = evaluate(reg, ())
    assert not any("plausible" in reason for reason in result.incomplete_reasons)
    assert (
        capital_label(owner_small(rate)) == f"owner_small:EUR:100:usdt_per_eur={rate}:fx_pin={PIN}"
    )


def test_the_research_label_and_a_missing_fx_pin():
    assert capital_label(registration().capitals[0]) == "research_10000_usdt"
    with pytest.raises(ValueError):
        capital_label(owner_small("1.1", fx_pin=None))
    with pytest.raises(ValueError):
        capital_label(Capital("research", D(100), "USDT", D(100)))
