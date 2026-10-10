"""Pure regime qualification. Admission still checks funding, cash and venue filters.

No result here is permission to submit an order; the shared portfolio reservation
must succeed using the same event snapshot. Protective reductions bypass routing.
"""

from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.strategy.perception import TrendState


@dataclass(frozen=True, slots=True)
class RoutingContext:
    spot_executable: bool | None = None
    flow_allowed: bool = False
    spot_trend: bool = True
    futures_trend: bool = True
    spot_grid: bool = True
    futures_long_only: bool = False
    continuation: bool = True
    short_qualification: bool = True

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if field.name == "spot_executable" and value is None:
                continue
            if type(value) is not bool:
                raise ValueError("routing context requires exact Boolean flags")


@dataclass(frozen=True, slots=True)
class Qualification:
    symbol: str
    decision_ms: int
    allowed: bool
    owner: str | None
    side: int
    risk_multiplier: Decimal
    reasons: tuple[str, ...]
    schema: str = "combined-v1"


class FlowGate:
    """Hysteresis on externally verified 15 completed one-minute flow bars."""

    def __init__(self) -> None:
        self.allowed = False

    def update(self, ratio: Decimal | None) -> bool:
        if (
            not isinstance(ratio, Decimal)
            or not ratio.is_finite()
            or not Decimal("0.40") <= ratio <= 1
        ):
            self.allowed = False
        elif ratio >= Decimal("0.45"):
            self.allowed = True
        return self.allowed


def completed_flow(bars: Sequence[Kline], decision_ms: int) -> Decimal | None:
    """Volume-weighted taker buy share from the fifteen due completed minutes.

    Future values are never inspected; gaps, duplicates and zero volume are
    unavailable. This ratio must pass the hysteresis gate before a grid increase.
    """
    if type(decision_ms) is not int or decision_ms < 0:
        raise ValueError("nonnegative integer decision timestamp required")
    minute = 60_000
    end = decision_ms // minute * minute
    start = end - 15 * minute
    selected = [bar for bar in bars if start <= bar.open_ms < end]
    if [bar.open_ms for bar in selected] != list(range(start, end, minute)):
        return None
    for bar in selected:
        if (
            any(
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not 0 <= value <= Decimal("1e36")
                for value in (bar.volume, bar.taker_buy_base)
            )
            or bar.taker_buy_base > bar.volume
        ):
            return None
    total = sum((bar.volume for bar in selected), Decimal(0))
    if total == 0:
        return None
    return sum((bar.taker_buy_base for bar in selected), Decimal(0)) / total


def qualify(assessment: Assessment, context: RoutingContext) -> Qualification:
    """Return an explainable candidate; preserve independent price-side blockers."""
    reasons = list(assessment.reasons)
    if not assessment.available:
        reasons.append("assessment_unavailable")
    ratio, extension = assessment.volatility_ratio, assessment.extension
    if not isinstance(ratio, Decimal) or not ratio.is_finite() or ratio <= 0:
        reasons.append("volatility_unavailable")
    elif ratio >= 3:
        reasons.append("volatility_stress")
    owner: str | None = None
    side = 0
    multiplier = Decimal(1)
    up = assessment.daily == assessment.four_hour == TrendState.UP
    down = assessment.four_hour == TrendState.DOWN and (
        assessment.daily == TrendState.DOWN
        or (not context.short_qualification and assessment.daily == TrendState.UNCLEAR)
    )
    ranged = assessment.daily == assessment.four_hour == TrendState.RANGE
    if up or down:
        side = 1 if up else -1
        if assessment.structure not in {"breakout", "continuation", "pullback"}:
            reasons.append("structure_unqualified")
        if not isinstance(extension, Decimal) or not extension.is_finite() or extension < 0:
            reasons.append("extension_unavailable")
        elif extension > 3:
            reasons.append("extended_entry")
        elif extension > 2:
            multiplier = Decimal("0.5")
        if not context.continuation:
            rsi = assessment.rsi
            if not isinstance(rsi, Decimal) or not rsi.is_finite() or not 0 <= rsi <= 100:
                reasons.append("rsi_unavailable")
            elif (up and rsi >= 75) or (down and rsi <= 25):
                reasons.append("legacy_rsi_veto")
        if down:
            if context.futures_trend and not context.futures_long_only:
                owner = "futures_trend"
            else:
                reasons.append("short_component_disabled")
        elif context.spot_trend:
            if context.spot_executable is True:
                owner = "spot_trend"
            elif context.spot_executable is None:
                reasons.append("spot_executability_unknown")
            elif context.futures_trend:
                owner = "futures_trend"
            else:
                reasons.append("spot_unexecutable")
        elif context.futures_trend:
            owner = "futures_trend"
        else:
            reasons.append("trend_components_disabled")
    elif ranged:
        side = 1
        if not context.spot_grid:
            reasons.append("grid_component_disabled")
        else:
            owner = "spot_grid"
        if not context.flow_allowed:
            reasons.append("flow_blocked")
        if context.spot_executable is not True:
            reasons.append("spot_unexecutable")
    else:
        reasons.append("conflicting_direction")
    return Qualification(
        assessment.symbol,
        assessment.decision_ms,
        not reasons and owner is not None,
        owner,
        side,
        multiplier,
        tuple(dict.fromkeys(reasons)),
    )
