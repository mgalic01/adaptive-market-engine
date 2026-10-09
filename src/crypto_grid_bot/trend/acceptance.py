"""Frozen A1-A5 account checks; experiment readiness and verdict remain upstream."""

from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.benchmark_comparison import compare_hold
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.exclusions import ExclusionCalendar
from crypto_grid_bot.trend.metrics import summarize_runner
from crypto_grid_bot.trend.orchestration import reconcile_replay
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.runner import FuturesDecisionInput, TrendRunner
from crypto_grid_bot.trend.signals import RULES
from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, SpotDecisionInput, SpotRunner


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    observed: Decimal
    threshold: Decimal
    strict: bool
    passed: bool


def validate_exclusion_calendar(
    runner: TrendRunner,
    first_months: Mapping[str, str],
    exclusions: Mapping[str, frozenset[str]],
    end_ms_exclusive: int,
) -> None:
    """Bind effective runtime overrides to the replay's reviewed calendar.

    Replay trims exclusions before a coin joins and beyond the window. Compare
    each retained midnight's override, including pre-exclusion close days;
    submitted input receipts alone precede these runtime overrides.
    """
    expected = ExclusionCalendar(
        {
            symbol: frozenset(
                month
                for month in months
                if month >= first_months[symbol]
                and month_bounds_ms(month)[0] < end_ms_exclusive
            )
            for symbol, months in exclusions.items()
        }
    )
    if any(
        runner.exclusions.zero_symbols(stamp) != expected.zero_symbols(stamp)
        for stamp, _, _ in runner.hours
        if stamp % 86400000 == 0
    ):
        raise ValueError("runner exclusion calendar differs from supplied source")


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
    expected_picks: Mapping[int, str | None],
    futures_exclusions: Mapping[str, frozenset[str]] | None = None,
    spot_exclusions: Mapping[str, frozenset[str]] | None = None,
) -> tuple[Criterion, ...]:
    """Validate the three criterion accounts, then report their five checks.

    This does not certify full experiment dates, registration, source provenance,
    or accounting in the other required training/report scenarios. All remain
    mandatory before any whole-experiment development verdict. Known invalid
    accounts must be classified by that enclosing report, not scored here.

    In particular, hourly execution bars, funding, masking and each market's
    filters must be linked upstream to the registered manifest. This helper
    does not authenticate those inputs. Futures and spot prices/filters are
    intentionally distinct; only the two futures filter sets must be equal.
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
    boundaries = []
    for stamp, _ in schedules[0]:
        date = datetime.fromtimestamp(stamp // 1000, UTC)
        if date.day == 1 and date.month in (1, 4, 7, 10):
            boundaries.append(stamp)
    if (
        not boundaries
        or set(expected_picks) != set(boundaries)
        or boundaries[0] != main.runner.hours[0][0]
        or any(rule is not None and rule not in RULES for rule in expected_picks.values())
    ):
        raise ValueError("expected quarterly picks must cover account quarters")
    if any(
        rule != expected_picks[boundaries[bisect_right(boundaries, stamp) - 1]]
        for stamp, rule in schedules[0]
    ):
        raise ValueError("account rules disagree with expected quarterly picks")
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
        if result.runner is None:
            raise ValueError("criterion account evidence missing")
        validate_exclusion_calendar(result.runner, first_months, union, end)
        previous = result.daily_decisions[0][1] if result.daily_decisions else None
        expected_strategy = {}
        for stamp, rule, recorded in result.daily_decisions:
            expected = source.at(
                stamp, rule, multiple=multiple, pick_changed=rule != previous, run_end_ms=end
            )
            if recorded != expected:
                raise ValueError("strategy decisions do not match supplied frozen source")
            expected_strategy[stamp] = expected
            previous = rule
        if result.runner is None:
            raise ValueError("criterion account evidence missing")
        submitted = tuple(
            FuturesDecisionInput(
                stamp,
                tuple(sorted(expected_strategy[stamp].targets.items()))
                if stamp in expected_strategy
                else (),
                tuple(sorted(expected_strategy[stamp].exit_reasons.items()))
                if stamp in expected_strategy
                else (),
            )
            for stamp, _, _ in result.runner.hours
        )
        if result.runner.decision_inputs != submitted:
            raise ValueError("strategy submitted targets do not match frozen decisions")
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
