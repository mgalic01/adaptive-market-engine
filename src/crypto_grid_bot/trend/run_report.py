"""One futures account's descriptive report; never a whole-experiment verdict."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Any

from crypto_grid_bot.trend.cost_diagnostics import CostDiagnostics, cost_diagnostics
from crypto_grid_bot.trend.exposure import ExposureDiagnostics, exposure_diagnostics
from crypto_grid_bot.trend.metrics import PerformanceSummary, sample_returns, summarize_runner
from crypto_grid_bot.trend.monthly import MonthlyDiagnostics, monthly_diagnostics
from crypto_grid_bot.trend.orchestration import INVALID, reconcile_replay
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.risk_diagnostics import (
    CapDiagnostics,
    DrawdownEpisode,
    cap_diagnostics,
    realized_volatility,
    worst_drawdown,
)
from crypto_grid_bot.trend.trade_breakdown import TradeBreakdown, trade_breakdown

DAY = 86400000


@dataclass(frozen=True, slots=True)
class FuturesRunReport:
    multiple: int
    cost_multiple: int
    reason: str | None
    reconciliation_residual: Decimal
    performance: PerformanceSummary | None
    monthly: MonthlyDiagnostics | None
    realized_volatility: Decimal | None
    target_volatility: Decimal
    costs: CostDiagnostics
    trades: TradeBreakdown
    exposure: ExposureDiagnostics
    caps: CapDiagnostics
    worst_drawdown: DrawdownEpisode | None
    samples: tuple[tuple[int, Decimal], ...]


def build_futures_report(result: ReplayResult) -> FuturesRunReport:
    """Reconcile supplied evidence before classifying completed/invalid outcomes.

    Invalid runs retain partial diagnostics and samples, never completed-run
    metrics. This is not proof of registration, source provenance, full-period
    coverage or presence of the other required scenarios. Those are mandatory
    checks in the enclosing experiment report before it can issue a verdict.
    """
    if result.reason is not None and result.reason not in INVALID:
        raise ValueError("unknown or engine-failed run cannot receive a strategy report")
    result = reconcile_replay(result)
    runner = result.runner
    assert runner is not None and result.trade_reconciliation_residual is not None
    days = [(stamp, decision) for stamp, _, decision in result.daily_decisions]
    expected_days = [stamp for stamp, _, _ in runner.hours if stamp % DAY == 0]
    if [stamp for stamp, _ in days] != expected_days:
        raise ValueError("daily decision evidence does not match retained hours")
    completed = result.reason is None
    performance = summarize_runner(runner) if completed else None
    monthly = monthly_diagnostics(runner.daily_samples) if completed else None
    volatility = realized_volatility(sample_returns(runner.daily_samples)) if completed else None
    return FuturesRunReport(
        runner.multiple,
        runner.account.cost_multiple,
        result.reason,
        result.trade_reconciliation_residual,
        performance,
        monthly,
        volatility,
        Decimal("0.2") * runner.multiple,
        cost_diagnostics(runner.account),
        trade_breakdown(runner.lifecycles.completed),
        exposure_diagnostics([hour for _, _, hour in runner.hours]),
        cap_diagnostics(days),
        worst_drawdown(runner.equity_path),
        tuple(runner.daily_samples),
    )


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value.is_nan():
            raise ValueError("NaN cannot be published in a report")
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        if all(isinstance(key, str) for key in value):
            return {key: _plain(item) for key, item in value.items()}
        return [{"key": _plain(key), "value": _plain(item)} for key, item in value.items()]
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if value is None or type(value) in (str, bool, int):
        return value
    raise ValueError("unsupported report value")


def report_json(report: FuturesRunReport) -> str:
    """Exact Decimal strings; Infinity is explicit, never a nonstandard JSON number."""
    value = _plain(report)
    # Tuple keys become explicit coin/side rows, including the empty case.
    value["trades"]["by_coin_side"] = [
        {"coin": coin, "side": side, "totals": _plain(totals)}
        for (coin, side), totals in report.trades.by_coin_side.items()
    ]
    return json.dumps(value, sort_keys=True, allow_nan=False, indent=2) + "\n"
