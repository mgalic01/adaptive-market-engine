"""Frozen monthly return diagnostics on supplied evidence, without a verdict."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.metrics import sample_returns

DAY = 86400000
HOUR = 3600000


@dataclass(frozen=True, slots=True)
class MonthlyReturn:
    month: str
    start_ms: int
    end_ms: int
    initial_equity: Decimal
    terminal_equity: Decimal
    return_fraction: Decimal


@dataclass(frozen=True, slots=True)
class MonthlyDiagnostics:
    months: tuple[MonthlyReturn, ...]
    mean_return: Decimal
    months_at_least_20_percent: int
    months_at_least_30_percent: int
    hosting_capital_eur_proxy: Decimal | None


def monthly_diagnostics(samples: Sequence[tuple[int, Decimal]]) -> MonthlyDiagnostics:
    """Section 8 month boundaries and reported-only economics, in Decimal60.

    Input is a consecutive 01:00 UTC series followed by one terminal sample.
    The terminal may end a partial day/month but never starts an extra month.
    Callers must separately validate source/account evidence and run validity.
    Hosting capital assumes USDT returns represent EUR returns and ignores how
    order filters change results at a different account size. None is unreachable.
    """
    sample_returns(samples)  # finite, ordered, positive before terminal
    daily = samples[:-1]
    if any(stamp % DAY != HOUR for stamp, _ in daily):
        raise ValueError("daily samples must be at 01:00 UTC")
    if any(b[0] - a[0] != DAY for a, b in zip(daily, daily[1:], strict=False)):
        raise ValueError("daily samples must be consecutive")
    if samples[-1][0] - daily[-1][0] > DAY:
        raise ValueError("terminal sample leaves a missing daily observation")
    boundaries = [0]
    months = [datetime.fromtimestamp(stamp // 1000, UTC).strftime("%Y-%m") for stamp, _ in daily]
    boundaries.extend(i for i in range(1, len(daily)) if months[i] != months[i - 1])
    boundaries.append(len(samples) - 1)
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        rows = tuple(
            MonthlyReturn(
                months[first],
                samples[first][0],
                samples[last][0],
                samples[first][1],
                samples[last][1],
                samples[last][1] / samples[first][1] - 1,
            )
            for first, last in zip(boundaries, boundaries[1:], strict=False)
        )
        mean = sum((row.return_fraction for row in rows), Decimal(0)) / len(rows)
        return MonthlyDiagnostics(
            rows,
            mean,
            sum(row.return_fraction >= Decimal(".2") for row in rows),
            sum(row.return_fraction >= Decimal(".3") for row in rows),
            Decimal(5) / mean if mean > 0 else None,
        )
