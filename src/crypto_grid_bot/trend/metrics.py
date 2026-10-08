"""Frozen V3 evaluation arithmetic on supplied evidence, without data access."""

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

ZERO = Decimal(0)


def _validate(values: Sequence[Decimal]) -> None:
    if any(not isinstance(value, Decimal) or not value.is_finite() for value in values):
        raise ValueError("metrics require finite Decimal observations")


def profit_factor(net_results: Sequence[Decimal]) -> Decimal:
    """Use trade net results for A2; daily changes are a separate diagnostic."""
    _validate(net_results)
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        gains = sum((value for value in net_results if value > ZERO), ZERO)
        losses = -sum((value for value in net_results if value < ZERO), ZERO)
        if gains == ZERO:
            return ZERO
        return gains / losses if losses else Decimal("Infinity")


def sharpe(daily_returns: Sequence[Decimal]) -> Decimal:
    _validate(daily_returns)
    if len(daily_returns) < 2:
        return ZERO
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        mean = sum(daily_returns, ZERO) / len(daily_returns)
        variance = sum(((value - mean) ** 2 for value in daily_returns), ZERO) / (
            len(daily_returns) - 1
        )
        return mean / variance.sqrt() * Decimal(365).sqrt() if variance else ZERO


def maximum_drawdown(equities: Sequence[Decimal]) -> Decimal:
    """Consume the full ordered path, including favourable/adverse and terminal marks."""
    _validate(equities)
    if not equities or equities[0] <= ZERO:
        raise ValueError("equity path must begin with positive equity")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        peak = equities[0]
        worst = ZERO
        for equity in equities:
            peak = max(peak, equity)
            worst = max(worst, (peak - equity) / peak)
        return worst
