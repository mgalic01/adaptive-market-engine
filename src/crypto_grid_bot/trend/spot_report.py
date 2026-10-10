"""Audited spot benchmark diagnostics, without source or experiment certification."""

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from crypto_grid_bot.trend.bootstrap import sharpe_interval
from crypto_grid_bot.trend.metrics import cagr, sample_returns, sharpe, validate_sample_path
from crypto_grid_bot.trend.monthly import MonthlyDiagnostics, monthly_diagnostics
from crypto_grid_bot.trend.risk_diagnostics import (
    DrawdownEpisode,
    realized_volatility,
    worst_drawdown,
)
from crypto_grid_bot.trend.spot_benchmark import SpotRunner


@dataclass(frozen=True, slots=True)
class SpotRunReport:
    cost_multiple: int
    reason: str | None
    net_pnl: Decimal
    fees: Decimal
    slippage_cost: Decimal
    traded_notional: Decimal
    sharpe: Decimal | None
    cagr: Decimal | None
    realized_volatility: Decimal | None
    interval: tuple[Decimal, Decimal] | None
    monthly: MonthlyDiagnostics | None
    worst_drawdown: DrawdownEpisode | None
    samples: tuple[tuple[int, Decimal], ...]


def build_spot_report(runner: SpotRunner) -> SpotRunReport:
    """Report known finalized outcomes; accounting/engine errors abort.

    A null interval on a completed account means fewer than 60 daily returns.
    Invalid accounts retain partial values, never completed performance metrics.
    Benchmark identity and registered source linkage are upstream obligations.
    """
    if runner.stopped not in ("completed", "unavailable_exclusion_close"):
        raise ValueError("spot report requires known finalized outcome")
    if (
        not runner.audits
        or any(not a.exact for a in runner.audits)
        or not runner.account.audit().exact
    ):
        raise ValueError("spot accounting evidence failed")
    if (
        not runner.equity_path
        or not runner.samples
        or runner.equity_path[0].equity != runner.account.initial
        or runner.equity_path[-1].equity != runner.samples[-1][1]
        or runner.equity_path[-1].timestamp_ms != runner.samples[-1][0]
    ):
        raise ValueError("spot path and samples disagree")
    completed = runner.stopped == "completed"
    if completed:
        validate_sample_path(runner.samples, runner.equity_path)
    returns = sample_returns(runner.samples) if completed else ()
    with localcontext(Context(prec=60)):
        net = runner.equity_path[-1].equity - runner.account.initial
        fees = sum((f.fee for f in runner.account.fills), Decimal(0))
        slippage = sum(
            (f.quantity * (f.price - f.open_price) for f in runner.account.fills), Decimal(0)
        )
        notional = sum((abs(f.quantity) * f.price for f in runner.account.fills), Decimal(0))
    return SpotRunReport(
        runner.account.cost_multiple,
        None if completed else runner.stopped,
        net,
        fees,
        slippage,
        notional,
        sharpe(returns) if completed else None,
        cagr(runner.samples) if completed else None,
        realized_volatility(returns) if completed else None,
        sharpe_interval(returns) if completed else None,
        monthly_diagnostics(runner.samples) if completed else None,
        worst_drawdown(runner.equity_path),
        tuple(runner.samples),
    )
