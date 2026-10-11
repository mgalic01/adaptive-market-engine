"""Pure held-position protection, independent of entry admission and execution.

A close reason is an obligation for the next executable quote, never a fill.
Stops, margin checks and recovery management remain enabled for every result.
"""

from dataclasses import dataclass
from decimal import Decimal

from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.strategy.perception import TrendState


@dataclass(frozen=True, slots=True)
class ManagementDecision:
    cancel_increases: bool
    close_reason: str | None


def _reliable(assessment: Assessment) -> bool:
    if assessment.available is not True or assessment.reasons or assessment.schema != "combined-v1":
        return False
    now = assessment.decision_ms
    if type(now) is not int or now < 0:
        return False
    timestamps = (
        assessment.quote_ms,
        assessment.hourly_closed_ms,
        assessment.four_hour_closed_ms,
        assessment.daily_closed_ms,
    )
    if any(type(stamp) is not int or not 0 <= stamp <= now for stamp in timestamps):
        return False
    # Assessment timestamps are exclusive completion boundaries, not bar opens.
    if (
        assessment.quote_ms < now - 3_600_000
        or assessment.hourly_closed_ms != now // 3_600_000 * 3_600_000
        or assessment.four_hour_closed_ms != now // 14_400_000 * 14_400_000
        or assessment.daily_closed_ms != now // 86_400_000 * 86_400_000
    ):
        return False
    if any(
        not isinstance(value, Decimal) or not value.is_finite() or value <= 0
        for value in (assessment.close, assessment.atr, assessment.volatility_ratio)
    ):
        return False
    ratio = assessment.volatility_ratio
    return (
        isinstance(ratio, Decimal)
        and ratio < 3
        and isinstance(assessment.daily, TrendState)
        and isinstance(assessment.four_hour, TrendState)
    )


def manage(
    assessment: Assessment, owner: str, side: int, *, short_qualification: bool = True
) -> ManagementDecision:
    """Decide cancellation/close obligations from the supplied causal assessment.

    Grid inventory requires verified non-stress RANGE on both timeframes. When
    availability is lost, request a close conservatively: the reviewed rules require
    range-only inventory and protective reductions when unavailable. This request
    persists upstream until an executable reduction; it never erases missing-price
    inventory. Trend unavailability cancels increases but cannot prove a reversal.

    Short-qualification ablation permits daily UNCLEAR with bearish 4h structure,
    including when evaluating an opposite signal for an existing long. Daily UP
    with bearish 4h is still conflict. RSI and extension entry gates do not veto exits.
    """
    if (
        owner not in {"spot_grid", "spot_trend", "futures_trend"}
        or type(side) is not int
        or side not in {-1, 1}
        or (owner != "futures_trend" and side != 1)
    ):
        raise ValueError("valid held owner and side required")
    if type(short_qualification) is not bool:
        raise ValueError("short_qualification requires exact Boolean")
    if not _reliable(assessment):
        return ManagementDecision(True, "grid_range_unverified" if owner == "spot_grid" else None)
    if owner == "spot_grid":
        ranged = assessment.daily == assessment.four_hour == TrendState.RANGE
        return ManagementDecision(not ranged, None if ranged else "grid_left_range")
    up = assessment.daily == assessment.four_hour == TrendState.UP
    down = assessment.four_hour == TrendState.DOWN and (
        assessment.daily == TrendState.DOWN
        or (not short_qualification and assessment.daily == TrendState.UNCLEAR)
    )
    structured = assessment.structure in {"breakout", "continuation", "pullback"}
    direction = 1 if up else -1 if down else 0
    if structured and direction == -side:
        return ManagementDecision(True, "trend_reversal")
    return ManagementDecision(not (structured and direction == side), None)
