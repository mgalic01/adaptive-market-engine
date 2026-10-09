"""Assemble supplied V3 accounts; never certify registration or authorize dispatch."""

import json
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend import bootstrap
from crypto_grid_bot.trend.acceptance import (
    Criterion,
    evaluate_accounts,
    validate_exclusion_calendar,
)
from crypto_grid_bot.trend.cost_diagnostics import MinimumAccountSize, minimum_account_size
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.metrics import sample_returns
from crypto_grid_bot.trend.orchestration import WalkForwardResult
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.report_markdown import _cell, _number, report_markdown
from crypto_grid_bot.trend.run_report import FuturesRunReport, _plain, build_futures_report
from crypto_grid_bot.trend.runner import FuturesDecisionInput
from crypto_grid_bot.trend.selection_report import SelectionReport, selection_report
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotDecisionInput, SpotRunner
from crypto_grid_bot.trend.spot_report import SpotRunReport, build_spot_report
from crypto_grid_bot.trend.walk_forward import RULES

SENSITIVITIES = frozenset({(1, 1), (3, 1), (1, 2), (2, 2), (3, 2)})
REQUIRED = (
    "Committed completing registration and matching code/manifest/trial identities",
    "Registered hourly bars, funding, masks and both market filter snapshots",
    "All training score artifacts and attempt history, including failed attempts",
    "Full-size equal-weight hold diagnostic (missing first purchase bar decision pending)",
)


@dataclass(frozen=True, slots=True)
class HistoricalComparison:
    source: str
    windows: tuple[str, ...]
    engine: str
    mean_annualised_percent: Decimal
    mean_return_percent: Decimal
    mean_max_drawdown_percent: Decimal
    verdict: str


VARIANT_D = HistoricalComparison(
    "https://github.com/mgalic01/adaptive-market-engine/blob/"
    "46e09d8b8e31868fcf6d09c0742bda5e261a6b87/docs/backtests/2026-10-06-spec-v1-stage-1.md",
    ("practice-2022", "verify-2024h1"),
    "drawdown-recovery-v2",
    Decimal("4.6615"),
    Decimal("-1.1720"),
    Decimal("31.0627"),
    "FAIL",
)


@dataclass(frozen=True, slots=True)
class ExperimentReport:
    start_ms: int
    end_ms_exclusive: int
    selection: SelectionReport
    futures: dict[str, FuturesRunReport]
    fixed_rules: dict[str, FuturesRunReport]
    holds: dict[str, SpotRunReport]
    account_checks: tuple[Criterion, ...]
    invalid_criterion_accounts: tuple[str, ...]
    intervals: dict[str, tuple[Decimal, Decimal] | None]
    minimum_account_size: MinimumAccountSize | None
    variant_d: HistoricalComparison = VARIANT_D
    required_before_verdict: tuple[str, ...] = REQUIRED
    verdict: None = None


def _futures_report(
    result: ReplayResult,
    multiple: int,
    cost: int,
    start: int,
    end: int,
    picks: Mapping[int, str | None],
    source: DailyDecisions,
) -> FuturesRunReport:
    report = build_futures_report(result)  # all accounting/engine failures abort
    runner = result.runner
    if runner is None:
        raise ValueError("missing futures account")
    if (
        runner.multiple != multiple
        or runner.account.cost_multiple != cost
        or runner.account.initial != 10000
        or not runner.hours
        or runner.equity_path[0].timestamp_ms != start
    ):
        raise ValueError("futures scenario settings or start disagree")
    terminal = runner.equity_path[-1].timestamp_ms
    if not start <= terminal <= end or (result.reason is None and terminal != end):
        raise ValueError("futures scenario does not cover its required period")
    validate_exclusion_calendar(runner, source.first_months, source.excluded_months, end)
    boundaries = sorted(picks)
    previous = picks[boundaries[0]]
    by_day = {}
    for stamp, rule, decision in result.daily_decisions:
        expected_rule = picks[boundaries[bisect_right(boundaries, stamp) - 1]]
        expected = source.at(
            stamp,
            expected_rule,
            multiple=multiple,
            pick_changed=expected_rule != previous,
            run_end_ms=end,
        )
        if rule != expected_rule or decision != expected:
            raise ValueError("futures scenario decisions disagree with prescribed picks")
        by_day[stamp] = expected
        previous = expected_rule
    submitted = tuple(
        FuturesDecisionInput(
            stamp,
            tuple(sorted(by_day[stamp].targets.items())) if stamp in by_day else (),
            tuple(sorted(by_day[stamp].exit_reasons.items())) if stamp in by_day else (),
        )
        for stamp, _, _ in runner.hours
    )
    if runner.decision_inputs != submitted:
        raise ValueError("futures scenario submitted targets disagree")
    return report


def build_experiment_report(
    walk: WalkForwardResult,
    sensitivities: Mapping[tuple[int, int], ReplayResult],
    fixed_rules: Mapping[str, ReplayResult],
    holds: Mapping[int, SpotRunner],
    *,
    spot_bars: Mapping[str, Sequence[Kline]],
    first_months: Mapping[str, str],
    futures_exclusions: Mapping[str, frozenset[str]] | None = None,
    spot_exclusions: Mapping[str, frozenset[str]] | None = None,
) -> ExperimentReport:
    """Require all report scenarios and frozen calendar, but leave verdict unset.

    This consumes already executed results. Training score provenance, registered
    execution inputs and the additional required diagnostics remain explicit
    prerequisites. A complete in-memory menu is not historical certification.
    """
    if (
        set(sensitivities) != SENSITIVITIES
        or set(fixed_rules) != set(RULES)
        or set(holds) != {1, 2}
    ):
        raise ValueError("complete exact futures, fixed-rule and hold menus required")
    if not (set(futures_exclusions or {}) | set(spot_exclusions or {})) <= set(first_months):
        raise ValueError("unknown exclusion symbol")
    union = {
        s: (futures_exclusions or {}).get(s, frozenset())
        | (spot_exclusions or {}).get(s, frozenset())
        for s in first_months
    }
    selection = selection_report(walk.training, walk.picks, first_months, union)
    start, end = min(walk.picks), month_bounds_ms("2025-01")[0]
    source = DailyDecisions(spot_bars, first_months, union)
    all_results = {(2, 1): walk.out_of_sample, **sensitivities}
    main = walk.out_of_sample.runner
    if main is None or set(main.filters) != set(first_months):
        raise ValueError("main futures universe disagrees")
    futures = {}
    for (multiple, cost), result in sorted(all_results.items()):
        if result.runner is None or result.runner.filters != main.filters:
            raise ValueError("all futures scenarios require identical filters")
        futures[f"m{multiple}-cost{cost}"] = _futures_report(
            result, multiple, cost, start, end, walk.picks, source
        )
    fixed = {}
    for rule in RULES:
        result = fixed_rules[rule]
        if result.runner is None or result.runner.filters != main.filters:
            raise ValueError("fixed-rule futures filters disagree")
        fixed[rule] = _futures_report(
            result, 2, 1, start, end, {stamp: rule for stamp in walk.picks}, source
        )
    hold_source = HoldDecisions(spot_bars, first_months, union)
    spot = {}
    for cost, runner in sorted(holds.items()):
        if (
            runner.account.cost_multiple != cost
            or runner.account.initial != 10000
            or set(runner.filters) != set(first_months)
            or runner.filters != holds[1].filters
        ):
            raise ValueError("hold scenario settings disagree")
        report = build_spot_report(runner)
        terminal = runner.equity_path[-1].timestamp_ms
        if (
            runner.equity_path[0].timestamp_ms != start
            or not start <= terminal <= end
            or (report.reason is None and terminal != end)
        ):
            raise ValueError("hold scenario does not cover required period")
        expected = [
            (stamp, hold_source.at(stamp, run_end_ms=end))
            for stamp, _ in runner.dispatches
            if stamp % 86400000 == 0
        ]
        if runner.daily_decisions != expected:
            raise ValueError("hold decisions disagree")
        days = dict(expected)
        receipts = tuple(
            SpotDecisionInput(
                stamp,
                tuple(sorted(days[stamp].targets.items())) if stamp in days else (),
                tuple(sorted(days[stamp].exit_reasons.items())) if stamp in days else (),
            )
            for stamp, _ in runner.dispatches
        )
        if runner.decision_inputs != receipts:
            raise ValueError("hold submitted targets disagree")
        spot[f"cost{cost}"] = report
    invalid = tuple(
        name
        for name, reason in (
            ("main", futures["m2-cost1"].reason),
            ("m1", futures["m1-cost1"].reason),
            ("hold", spot["cost1"].reason),
        )
        if reason is not None
    )
    checks = (
        ()
        if invalid
        else evaluate_accounts(
            walk.out_of_sample,
            sensitivities[1, 1],
            holds[1],
            spot_bars=spot_bars,
            first_months=first_months,
            expected_picks=walk.picks,
            futures_exclusions=futures_exclusions,
            spot_exclusions=spot_exclusions,
        )
    )
    intervals = {
        name: bootstrap.sharpe_interval(sample_returns(futures[key].samples))
        if futures[key].reason is None
        else None
        for name, key in (("main", "m2-cost1"), ("m1", "m1-cost1"))
    }
    intervals["hold"] = spot["cost1"].interval
    return ExperimentReport(
        start,
        end,
        selection,
        futures,
        fixed,
        spot,
        checks,
        invalid,
        intervals,
        minimum_account_size(main) if walk.out_of_sample.reason is None else None,
    )


def experiment_json(report: ExperimentReport) -> str:
    return json.dumps(_plain(report), sort_keys=True, allow_nan=False, indent=2) + "\n"


def experiment_markdown(report: ExperimentReport) -> str:
    experiment_json(report)  # rejects NaN/unsupported values before display
    lines = [
        "# V3 experiment diagnostics",
        "",
        "**Experiment verdict: not evaluated.**",
        "",
        "This report compares supplied accounts. "
        "It does not certify a registered historical experiment.",
        "",
        "## Required before a verdict",
        "",
    ]
    lines += [f"- {_cell(item)}" for item in report.required_before_verdict]
    lines += [
        "",
        "## Account checks",
        "",
        "| Check | Observed | Threshold | Result |",
        "|---|---:|---:|---|",
    ]
    for c in report.account_checks:
        lines.append(
            f"| {c.name} | {_number(c.observed)} | "
            f"{'>' if c.strict else '>='} {_number(c.threshold)} | "
            f"{'Pass' if c.passed else 'Fail'} |"
        )
    if report.invalid_criterion_accounts:
        lines += ["", "Invalid criterion accounts: " + ", ".join(report.invalid_criterion_accounts)]
    lines += [
        "",
        "## Futures comparisons",
        "",
        "| Account/rule | Status | Sharpe | CAGR | Trade PF |",
        "|---|---|---:|---:|---:|",
    ]
    for name, r in (*report.futures.items(), *report.fixed_rules.items()):
        p = r.performance
        lines.append(
            f"| {_cell(name)} | {_cell(r.reason or 'Completed')} | "
            f"{_number(p.sharpe if p else None)} | "
            f"{_number(p.cagr if p else None, percent=True)} | "
            f"{_number(p.trade_profit_factor if p else None)} |"
        )
    lines += [
        "",
        "## Spot comparisons",
        "",
        "| Account | Status | Sharpe | CAGR | Net PnL (USDT) | Fees (USDT) | "
        "Slippage (USDT) | Traded notional (USDT) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in report.holds.items():
        lines.append(
            f"| {name} | {_cell(s.reason or 'Completed')} | {_number(s.sharpe)} | "
            f"{_number(s.cagr, percent=True)} | {_number(s.net_pnl)} | {_number(s.fees)} | "
            f"{_number(s.slippage_cost)} | {_number(s.traded_notional)} |"
        )
    lines += [
        "",
        "Slippage is already embedded in fill prices; it is not deducted again from net PnL.",
        "",
        "## Selections",
        "",
        "| Test quarter starts | Pick | Monthly portfolio coin counts |",
        "|---|---|---|",
    ]
    for q in report.selection.quarters:
        counts = "; ".join(f"{m}: {n}" for m, n in q.monthly_coin_counts)
        lines.append(f"| {q.test_month} | {q.picked_rule or 'Flat: all invalid'} | {counts} |")
    lines += [
        "",
        "### Training scores",
        "",
        "| Test quarter | Rule | Run ID | Sharpe | Invalid reason |",
        "|---|---|---|---:|---|",
    ]
    for q in report.selection.quarters:
        for score in q.training:
            lines.append(
                f"| {q.test_month} | {score.rule} | {_cell(score.run_id)} | "
                f"{_number(score.sharpe)} | {_cell(score.invalid_reason or 'None')} |"
            )
    lines += [
        "",
        f"Long-only picks: {report.selection.long_only_quarters}/"
        f"{len(report.selection.quarters)} quarters (flat quarters included).",
        "",
        "## Sharpe uncertainty",
        "",
        "95% stationary block-bootstrap intervals: 10,000 resamples, mean block 20 days, "
        "fresh seed 20261008 for each series. These are diagnostics, not profit guarantees.",
    ]
    for name, interval in report.intervals.items():
        value = (
            "Unavailable: invalid account or fewer than 60 returns"
            if interval is None
            else f"[{_number(interval[0])}, {_number(interval[1])}]"
        )
        lines.append(f"- {name}: {value}")
    size = report.minimum_account_size
    d = report.variant_d
    lines += [
        "",
        "## Published variant D comparison",
        "",
        f"Quoted from [spec v1 stage 1]({d.source}); D is not rerun. "
        f"Windows: {', '.join(d.windows)}. Engine: {d.engine}. "
        "Its windows and engine differ from V3; R1L is V3's like-for-like comparison.",
        "",
        "| Mean annualised return % | Mean return % | Mean maximum drawdown % | V1 verdict |",
        "|---:|---:|---:|---|",
        f"| {d.mean_annualised_percent} | {d.mean_return_percent} | "
        f"{d.mean_max_drawdown_percent} | {d.verdict} |",
    ]
    lines += [
        "",
        "Minimum account-size scaling estimate: "
        + (
            f"{_number(size.required_usdt)} USDT"
            if size
            else (
                "Unavailable: main account is invalid; full-period intentions are unknown."
                if report.futures["m2-cost1"].reason is not None
                else "No intended opening/increase; no estimate."
            )
        ),
        "Scaling ignores changed rounding/refusals and their effect on the later path.",
        "",
        "## Detailed account diagnostics",
        "",
    ]
    for name, r in (*report.futures.items(), *report.fixed_rules.items()):
        lines += [
            f"### {name}",
            "",
            report_markdown(r).replace("# V3 futures account report", "#### Account report"),
        ]
    return "\n".join(lines) + "\n"
