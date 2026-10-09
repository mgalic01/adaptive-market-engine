"""Frozen A1-A5 account checks; experiment readiness and verdict remain upstream."""

from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.trend.benchmark_comparison import compare_hold
from crypto_grid_bot.trend.metrics import summarize_runner
from crypto_grid_bot.trend.orchestration import reconcile_replay
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.signals import RULES
from crypto_grid_bot.trend.spot_benchmark import SpotRunner


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    observed: Decimal
    threshold: Decimal
    strict: bool
    passed: bool


def _score(
    sharpe: Decimal,
    profit_factor: Decimal,
    calmar: Decimal,
    cagr: Decimal,
    smaller_sharpe: Decimal,
    hold_sharpe: Decimal,
) -> tuple[Criterion, ...]:
    values = (sharpe, profit_factor, calmar, cagr, smaller_sharpe, hold_sharpe)
    if any(value.is_nan() for value in values):
        raise ValueError("undefined criterion value")
    rows = (
        ("A1", sharpe, Decimal("1"), False),
        ("A2", profit_factor, Decimal("1.3"), False),
        ("A3", calmar, Decimal("0.5"), False),
        ("A4", cagr, Decimal("0.08"), False),
        ("A5", smaller_sharpe, hold_sharpe, True),
    )
    return tuple(
        Criterion(
            name, value, threshold, strict, value > threshold if strict else value >= threshold
        )
        for name, value, threshold, strict in rows
    )


def evaluate_accounts(
    main: ReplayResult,
    smaller: ReplayResult,
    hold: SpotRunner,
) -> tuple[Criterion, ...]:
    """Validate the three criterion accounts, then report their five checks.

    This does not certify full experiment dates, registration, source provenance,
    or accounting in the other required training/report scenarios. All remain
    mandatory before any whole-experiment development verdict. Known invalid
    accounts must be classified by that enclosing report, not scored here.
    """
    schedules = []
    for result, multiple in ((main, 2), (smaller, 1)):
        if result.reason is not None:
            raise ValueError("criteria require completed valid accounts")
        result = reconcile_replay(result)
        runner = result.runner
        if runner is None:
            raise ValueError("criterion account evidence missing")
        if (
            runner.multiple != multiple
            or runner.account.cost_multiple != 1
            or runner.account.initial != Decimal(10000)
        ):
            raise ValueError("criteria require base-cost 10000-USDT m=2 and m=1 accounts")
        schedule = tuple((stamp, rule) for stamp, rule, _ in result.daily_decisions)
        if tuple(stamp for stamp, _ in schedule) != tuple(
            stamp for stamp, _, _ in runner.hours if stamp % 86400000 == 0
        ) or any(rule is not None and rule not in RULES for _, rule in schedule):
            raise ValueError("complete known daily rule decisions required")
        schedules.append(schedule)
    if schedules[0] != schedules[1]:
        raise ValueError("m=1 must retain the main account's rule picks")
    if main.runner is None or smaller.runner is None:
        raise ValueError("criterion account evidence missing")
    if [stamp for stamp, _ in main.runner.daily_samples] != [
        stamp for stamp, _ in smaller.runner.daily_samples
    ]:
        raise ValueError("criterion accounts require identical sample times")
    if hold.account.initial != Decimal(10000):
        raise ValueError("hold account must start with 10000 USDT")
    metrics = summarize_runner(main.runner)
    comparison = compare_hold(smaller.runner, hold)
    return _score(
        metrics.sharpe,
        metrics.trade_profit_factor,
        metrics.calmar,
        metrics.cagr,
        comparison.strategy_sharpe,
        comparison.hold_sharpe,
    )
