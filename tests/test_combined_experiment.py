from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from crypto_grid_bot.combined.experiment import (
    Capital,
    Registration,
    ReportEvidence,
    RunIdentity,
    RunOutcome,
    Window,
    evaluate,
)
from crypto_grid_bot.combined.report import Contribution, EquityPoint, UtilizationInterval, analyze

D = Decimal
DAY = 86_400_000
PIN = "a" * 64
CODE = "b" * 40
BASELINES = (
    "unchanged_v3_selector",
    *(f"unchanged_v3_r{i}_long_only" for i in range(1, 7)),
    "matched_spot_hold",
    "matched_v2",
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
    )


def outcomes(reg: Registration) -> tuple[RunOutcome, ...]:
    rows = []
    for arm in reg.arms:
        for window in reg.windows:
            for capital in reg.capitals:
                for multiple, cost_pin in reg.cost_profiles:
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
                            f"{arm}-{window.id}-{capital.id}-{multiple}",
                            True,
                        )
                    )
    return tuple(with_report(row) for row in rows)


def with_report(row):
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
    points = (
        EquityPoint(start, row.initial_equity, "opening", ("synthetic-opening",)),
        EquityPoint(
            start + DAY,
            row.initial_equity * (1 - row.max_drawdown),
            "trough",
            ("synthetic-trough",),
        ),
        EquityPoint(end, row.final_equity, "closing", ("synthetic-closing",)),
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
        daily_samples=points,
        utilization=(
            UtilizationInterval(
                start, end, D(0), D(0), row.initial_equity, "utilization", ("synthetic-capital",)
            ),
        ),
    )
    return replace(row, report_evidence=ReportEvidence(row.identity, row.attempt_id, report))


def change(rows, arm="combined", cost=1, capital="research", **updates):
    return tuple(
        with_report(replace(row, **updates))
        if (row.identity.arm, row.identity.cost_multiple, row.identity.capital)
        == (arm, cost, capital)
        else row
        for row in rows
    )


def test_complete_matrix_passes_and_all_results_are_retained() -> None:
    reg = registration()
    rows = outcomes(reg)
    result = evaluate(reg, rows)
    assert result.status == "pass"
    assert result.outcomes == rows and not result.failures and not result.incomplete_reasons


def test_full_must_beat_every_baseline_on_both_measures_not_best_ablation() -> None:
    reg = registration()
    rows = change(outcomes(reg), arm="matched_v2", final_equity=D(15000))
    assert evaluate(reg, rows).status == "fail"
    rows = change(outcomes(reg), arm="matched_v2", max_drawdown=D(".01"))
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
    rows = change(outcomes(reg), arm="matched_v2", max_drawdown=D(".8"), final_equity=D(9000))
    assert evaluate(reg, rows).status == "pass"
    rows = change(rows, arm="matched_v2", liquidations=1)
    assert evaluate(reg, rows).status == "incomplete"


@pytest.mark.parametrize("target", ["combined", "matched_v2"])
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
    result = evaluate(reg, change(outcomes(reg), arm="matched_v2", cost=2, final_equity=D(20000)))
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


@pytest.mark.parametrize("alter", ["pin", "boolean_time", "capital_mismatch", "baseline"])
def test_registration_failure_does_not_promote_unattributable_safety_metrics(alter):
    reg = replace(registration(), pending=("review",))
    rows = change(outcomes(reg), max_drawdown=D(".5"), liquidations=1)
    if alter == "pin":
        reg = replace(reg, code_pin="invalid")
    elif alter == "boolean_time":
        rows = tuple(replace(row, identity=replace(row.identity, start_ms=False)) for row in rows)
    elif alter == "capital_mismatch":
        rows = change(rows, initial_equity=D(9999))
    else:
        reg = replace(reg, baseline_arms=(*reg.baseline_arms, "combined"))
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
