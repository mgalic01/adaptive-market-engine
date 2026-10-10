"""Frozen A5 timing comparison; no whole-experiment or historical verdict."""

from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.trend.metrics import (
    sample_returns,
    sharpe,
    summarize_runner,
    validate_sample_path,
)
from crypto_grid_bot.trend.runner import TrendRunner
from crypto_grid_bot.trend.spot_benchmark import SpotRunner


@dataclass(frozen=True, slots=True)
class HoldComparison:
    strategy_sharpe: Decimal
    hold_sharpe: Decimal
    return_count: int
    passes_a5: bool


def compare_hold(strategy: TrendRunner, hold: SpotRunner) -> HoldComparison:
    """Only completed, audited base-cost m=1 accounts may be compared for A5.

    Invalid runs need an explicit invalid outcome in the enclosing experiment
    report, not a fabricated Sharpe or a successful acceptance result.
    """
    if strategy.multiple != 1:
        raise ValueError("A5 requires the m=1 strategy")
    if strategy.account.cost_multiple != 1 or hold.account.cost_multiple != 1:
        raise ValueError("A5 requires base-cost accounts")
    if strategy.stopped != "completed" or hold.stopped != "completed":
        raise ValueError("A5 requires completed valid accounts")
    if (
        not hold.audits
        or any(not audit.exact for audit in hold.audits)
        or not hold.account.audit().exact
    ):
        raise ValueError("spot accounting evidence failed")
    if [stamp for stamp, _ in strategy.daily_samples] != [stamp for stamp, _ in hold.samples]:
        raise ValueError("A5 requires identical sample times")
    if (
        not hold.equity_path
        or not hold.samples
        or hold.equity_path[0].equity != hold.account.initial
        or hold.samples[0][1] != hold.account.initial
        or hold.equity_path[-1].equity != hold.samples[-1][1]
        or hold.equity_path[-1].timestamp_ms != hold.samples[-1][0]
    ):
        raise ValueError("spot path and samples disagree")
    strategy_metrics = summarize_runner(strategy)
    validate_sample_path(hold.samples, hold.equity_path)
    returns = sample_returns(hold.samples)
    hold_sharpe = sharpe(returns)
    return HoldComparison(
        strategy_metrics.sharpe, hold_sharpe, len(returns), strategy_metrics.sharpe > hold_sharpe
    )
