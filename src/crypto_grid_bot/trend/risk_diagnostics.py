"""Descriptive V3 risk measurements on supplied evidence; no acceptance verdict."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.decisions import DailyDecision
from crypto_grid_bot.trend.runner import EquityState

ZERO = Decimal(0)
DAY = 86400000


@dataclass(frozen=True, slots=True)
class DrawdownEpisode:
    fraction: Decimal
    peak_ms: int
    trough_ms: int
    peak_index: int
    trough_index: int
    peak_kind: str
    trough_kind: str


@dataclass(frozen=True, slots=True)
class CapDiagnostics:
    decision_days: int
    bound_days: int
    bound_share: Decimal | None


def worst_drawdown(path: Sequence[EquityState]) -> DrawdownEpisode | None:
    """Recompute the full path; first worst trough and latest tied peak win.

    Same-hour states retain their input order and indices. A nondecreasing path
    has no drawdown episode. Caller establishes completeness and provenance;
    stored peak/drawdown fields are not used to derive the reported episode.
    """
    if not path or not path[0].equity.is_finite() or path[0].equity <= ZERO:
        raise ValueError("positive initial equity path required")
    previous = -1
    for state in path:
        if (
            type(state.timestamp_ms) is not int
            or state.timestamp_ms < previous
            or not state.equity.is_finite()
        ):
            raise ValueError("finite ordered equity path required")
        previous = state.timestamp_ms
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        peak_index = 0
        result = None
        maximum = ZERO
        for index, state in enumerate(path):
            if state.equity >= path[peak_index].equity:
                peak_index = index
            peak = path[peak_index]
            decline = (peak.equity - state.equity) / peak.equity
            if decline > maximum:
                maximum = decline
                result = DrawdownEpisode(
                    decline,
                    peak.timestamp_ms,
                    state.timestamp_ms,
                    peak_index,
                    index,
                    peak.kind,
                    state.kind,
                )
        return result


def realized_volatility(returns: Sequence[Decimal]) -> Decimal | None:
    """Annualized sample deviation, using the same sqrt(365) basis as Sharpe.

    The caller supplies the complete daily return series, including the terminal
    partial-day observation. Less than two observations cannot estimate deviation.
    """
    if any(not value.is_finite() for value in returns):
        raise ValueError("finite daily returns required")
    if len(returns) < 2:
        return None
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        mean = sum(returns, ZERO) / len(returns)
        variance = sum(((r - mean) ** 2 for r in returns), ZERO) / (len(returns) - 1)
        return variance.sqrt() * Decimal(365).sqrt()


def cap_diagnostics(days: Sequence[tuple[int, DailyDecision]]) -> CapDiagnostics:
    """Count all decision days once, including flat days, with explicit evidence.

    Consecutive timestamps detect missing interior days. The enclosing run must
    establish first/last boundaries; this function cannot detect trimmed ends.
    """
    previous = None
    bound = 0
    for stamp, decision in days:
        sizing = decision.sizing
        if (
            type(stamp) is not int
            or stamp < 0
            or stamp % DAY
            or (previous is not None and stamp != previous + DAY)
        ):
            raise ValueError("consecutive daily decisions required")
        if (
            sizing is None
            or set(sizing.binding_caps) != set(sizing.weights)
            or any(not caps <= {"coin", "gross"} for caps in sizing.binding_caps.values())
        ):
            raise ValueError("complete known cap evidence required")
        bound += any(sizing.binding_caps.values())
        previous = stamp
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        return CapDiagnostics(len(days), bound, Decimal(bound) / len(days) if days else None)
