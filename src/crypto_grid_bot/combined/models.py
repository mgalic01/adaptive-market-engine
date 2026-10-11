"""Immutable records passed between V3.1 assessment and admission."""

from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.strategy.perception import TrendState


@dataclass(frozen=True, slots=True)
class Assessment:
    symbol: str
    decision_ms: int
    quote_ms: int
    available: bool
    reasons: tuple[str, ...]
    daily: TrendState
    four_hour: TrendState
    structure: str
    close: Decimal | None
    atr: Decimal | None
    rsi: Decimal | None
    extension: Decimal | None
    volatility_ratio: Decimal | None
    prior_high: Decimal | None
    prior_low: Decimal | None
    high_distance_atr: Decimal | None
    low_distance_atr: Decimal | None
    hourly_closed_ms: int | None
    four_hour_closed_ms: int | None
    daily_closed_ms: int | None
    hourly_gaps: tuple[tuple[int, int], ...] = ()
    four_hour_gaps: tuple[tuple[int, int], ...] = ()
    daily_gaps: tuple[tuple[int, int], ...] = ()
    invalid_hourly_open_ms: tuple[int, ...] = ()
    invalid_daily_open_ms: tuple[int, ...] = ()
    schema: str = "combined-v1"


def assessment_source_reasons(assessment: Assessment) -> tuple[str, ...]:
    """Check causal due-source timestamps independently of cached availability.

    Closing boundaries, not bar opens, must equal the latest due UTC boundary.
    Before a timeframe's first complete bar there is no valid nonnegative-open
    source. The original assessment quote also remains subject to the one-hour
    freshness bound; a separate fresh execution quote cannot repair stale context.
    """
    now = assessment.decision_ms
    if type(now) is not int or now < 0:
        return ("assessment_decision_time_invalid",)
    reasons = []
    for field, step in (
        ("hourly_closed_ms", 3_600_000),
        ("four_hour_closed_ms", 14_400_000),
        ("daily_closed_ms", 86_400_000),
    ):
        closed = getattr(assessment, field)
        due = now // step * step
        if type(closed) is not int or due < step or closed != due:
            reasons.append(f"{field}_not_due")
    if (
        type(assessment.quote_ms) is not int
        or assessment.quote_ms < 0
        or not 0 <= now - assessment.quote_ms <= 3_600_000
    ):
        reasons.append("assessment_quote_unavailable")
    return tuple(reasons)
