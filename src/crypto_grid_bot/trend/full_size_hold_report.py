"""Audited reported-only drawdown comparison, never an A5 benchmark."""

from dataclasses import dataclass
from decimal import Context, Decimal, localcontext

from crypto_grid_bot.trend.full_size_hold import FullSizeHoldResult
from crypto_grid_bot.trend.metrics import validate_sample_path
from crypto_grid_bot.trend.risk_diagnostics import worst_drawdown


@dataclass(frozen=True, slots=True)
class FullSizeHoldReport:
    reason: str | None
    scheduled_ms: int
    attempt_times: dict[str, int]
    missing_symbols: tuple[str, ...]
    cash: Decimal
    fees: Decimal
    net_pnl: Decimal | None
    max_drawdown: Decimal | None


def build_full_size_hold_report(result: FullSizeHoldResult) -> FullSizeHoldReport:
    """Reject partial/unaudited outcomes; provenance remains upstream."""
    if result.reason not in (None, "unavailable_first_purchase"):
        raise ValueError("full-size diagnostic requires a finalized outcome")
    if (
        not result.audits
        or any(not a.exact for a in result.audits)
        or not result.account.audit().exact
    ):
        raise ValueError("full-size diagnostic accounting failed")
    path = result.equity_path
    if (
        not path
        or not result.samples
        or path[0].timestamp_ms != result.start_ms
        or path[0].equity != 10000
        or result.account.initial != 10000
        or result.account.cost_multiple != 1
        or path[-1].kind != "terminal"
        or path[-1].timestamp_ms != result.end_ms_exclusive
        or result.scheduled_ms != result.start_ms + 3600000
        or set(result.missing_symbols) != set(result.budgets) - set(result.purchase_times)
        or bool(result.missing_symbols) != (result.reason is not None)
    ):
        raise ValueError("full-size diagnostic identity or boundaries disagree")
    validate_sample_path(result.samples, path)
    episode = worst_drawdown(path)
    with localcontext(Context(prec=60)):
        fees = sum((f.fee for f in result.account.fills), Decimal(0))
        net = path[-1].equity - result.account.initial
    return FullSizeHoldReport(
        result.reason,
        result.scheduled_ms,
        dict(result.purchase_times),
        result.missing_symbols,
        result.account.cash,
        fees,
        net if result.reason is None else None,
        (episode.fraction if episode else Decimal(0)) if result.reason is None else None,
    )
