"""Frozen V3 evaluation arithmetic on supplied evidence, without data access."""

from collections.abc import Sequence
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

ZERO = Decimal(0)


def _samples(samples: Sequence[tuple[int, Decimal]]) -> None:
    _validate([equity for _, equity in samples])
    if len(samples) < 2 or samples[0][1] <= ZERO:
        raise ValueError("need two samples beginning with positive equity")
    previous = -1
    for stamp, _ in samples:
        if type(stamp) is not int or stamp <= previous:
            raise ValueError("sample times must be nonnegative and strictly increasing")
        previous = stamp


def sample_returns(samples: Sequence[tuple[int, Decimal]]) -> tuple[Decimal, ...]:
    """Simple returns; the terminal partial day is one observation, as frozen."""
    _samples(samples)
    if any(equity <= ZERO for _, equity in samples[:-1]):
        raise ValueError("nonpositive equity before terminal sample")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        return tuple(samples[i][1] / samples[i - 1][1] - 1 for i in range(1, len(samples)))


def cagr(samples: Sequence[tuple[int, Decimal]]) -> Decimal:
    _samples(samples)
    if samples[-1][1] <= ZERO:
        return Decimal(-1)
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        days = Decimal(samples[-1][0] - samples[0][0]) / Decimal(86400000)
        return (samples[-1][1] / samples[0][1]) ** (Decimal("365.25") / days) - 1


def calmar(annual_return: Decimal, drawdown: Decimal) -> Decimal:
    _validate([annual_return, drawdown])
    if drawdown < ZERO:
        raise ValueError("drawdown cannot be negative")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        if drawdown == ZERO:
            return Decimal("Infinity") if annual_return > ZERO else ZERO
        return annual_return / drawdown


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
