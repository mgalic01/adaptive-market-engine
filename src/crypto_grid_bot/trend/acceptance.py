"""Frozen A1-A5 account checks; experiment readiness and verdict remain upstream."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.trend.benchmark_comparison import compare_hold
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.metrics import summarize_runner
from crypto_grid_bot.trend.orchestration import reconcile_replay
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.signals import RULES
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotDecisionInput, SpotRunner


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
    *,
    spot_bars: Mapping[str, Sequence[Kline]],
    first_months: Mapping[str, str],
    futures_exclusions: Mapping[str, frozenset[str]] | None = None,
    spot_exclusions: Mapping[str, frozenset[str]] | None = None,
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
    if main.runner.filters != smaller.runner.filters:
        raise ValueError("futures accounts require identical filters")
    if [stamp for stamp, _ in main.runner.daily_samples] != [
        stamp for stamp, _ in smaller.runner.daily_samples
    ]:
        raise ValueError("criterion accounts require identical sample times")
    if hold.account.initial != Decimal(10000):
        raise ValueError("hold account must start with 10000 USDT")
    if not (set(spot_exclusions or {}) | set(futures_exclusions or {})) <= set(first_months):
        raise ValueError("unknown exclusion symbol")
    union = {
        symbol: (futures_exclusions or {}).get(symbol, frozenset())
        | (spot_exclusions or {}).get(symbol, frozenset())
        for symbol in first_months
    }
    source = DailyDecisions(spot_bars, first_months, union)
    benchmark = HoldDecisions(spot_bars, first_months, union)
    universe = set(first_months)
    if any(set(runner.filters) != universe for runner in (main.runner, smaller.runner, hold)):
        raise ValueError("criterion benchmark and strategy universes disagree")
    end = main.runner.equity_path[-1].timestamp_ms
    for result, multiple in ((main, 2), (smaller, 1)):
        previous = result.daily_decisions[0][1] if result.daily_decisions else None
        for stamp, rule, recorded in result.daily_decisions:
            expected = source.at(
                stamp, rule, multiple=multiple, pick_changed=rule != previous, run_end_ms=end
            )
            if recorded != expected:
                raise ValueError("strategy decisions do not match supplied frozen source")
            previous = rule
    expected_hold = [(stamp, benchmark.at(stamp, run_end_ms=end)) for stamp, _ in schedules[0]]
    if hold.daily_decisions != expected_hold:
        raise ValueError("hold benchmark decisions do not match frozen source")
    expected_by_day = dict(expected_hold)
    expected_inputs = []
    for stamp, _, _ in main.runner.hours:
        decision = expected_by_day.get(stamp)
        expected_inputs.append(
            SpotDecisionInput(
                stamp,
                tuple(sorted(decision.targets.items())) if decision else (),
                tuple(sorted(decision.exit_reasons.items())) if decision else (),
            )
        )
    if hold.decision_inputs != tuple(expected_inputs):
        raise ValueError("hold submitted targets do not match frozen benchmark decisions")
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
