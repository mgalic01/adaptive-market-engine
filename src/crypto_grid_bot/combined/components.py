"""Pure trend/grid geometry. Plans are not orders or portfolio reservations.

The supplied complete round-trip rate is a conservative cost bound per unit of
reference quote price, including entry and adverse stop-exit fees/spread/slippage.
For shorts it must cover the higher stop-exit price too. Each grid level uses the
same conservative cost bound when allocating equal stop risk. Execution owns tick
rounding, lot sizing and shared reservation at the decision quote/common stop.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.combined.models import Assessment
from crypto_grid_bot.combined.routing import Qualification
from crypto_grid_bot.strategy.perception import TrendState


@dataclass(frozen=True, slots=True)
class Level:
    price: Decimal
    risk_weight: Fraction


@dataclass(frozen=True, slots=True)
class ComponentPlan:
    symbol: str
    decision_ms: int
    quote_ms: int
    owner: str
    venue: str
    side: int
    reference_price: Decimal
    stop: Decimal
    levels: tuple[Level, ...]
    spacing: Decimal | None
    risk_multiplier: Decimal


def _finite(value: Decimal | None, *, positive: bool = True) -> bool:
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and (value > 0 if positive else value >= 0)
        and value <= Decimal("1e36")
    )


def _decimal(value: Fraction) -> Decimal:
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
        return Decimal(value.numerator) / Decimal(value.denominator)


def _consistent(assessment: Assessment, qualification: Qualification) -> bool:
    owner, side = qualification.owner, qualification.side
    if type(side) is not int or side not in {-1, 1}:
        return False
    if qualification.risk_multiplier not in (Decimal(".5"), Decimal(1)):
        return False
    ratio = assessment.volatility_ratio
    if not _finite(ratio) or ratio is None or ratio >= 3:
        return False
    if owner == "spot_grid":
        return side == 1 and assessment.daily == assessment.four_hour == TrendState.RANGE
    if owner not in {"spot_trend", "futures_trend"}:
        return False
    if assessment.structure not in {"breakout", "continuation", "pullback"}:
        return False
    extension = assessment.extension
    if not _finite(extension, positive=False) or extension is None or extension > 3:
        return False
    if extension > 2 and qualification.risk_multiplier != Decimal(".5"):
        return False
    if side == 1:
        return assessment.daily == assessment.four_hour == TrendState.UP
    # UNCLEAR daily is allowed only by the explicitly granted routing ablation;
    # this geometry layer cannot itself grant qualification.
    return (
        owner == "futures_trend"
        and assessment.four_hour == TrendState.DOWN
        and assessment.daily in {TrendState.DOWN, TrendState.UNCLEAR}
    )


def component_plan(
    assessment: Assessment,
    qualification: Qualification,
    quote_price: Decimal | None,
    quote_ms: int | None,
    round_trip_cost_rate: Decimal,
) -> ComponentPlan | None:
    """Return geometry only for coherent qualification and current usable inputs.

    Identity mismatch is a programming error. Missing/invalid inputs return no plan.
    Qualification remains necessary, not sufficient: risk admission is external.
    Weights are exact normalized inverse cash risk, not independently spendable cash.
    """
    if (
        qualification.symbol != assessment.symbol
        or qualification.decision_ms != assessment.decision_ms
        or qualification.schema != assessment.schema
        or assessment.schema != "combined-v1"
    ):
        raise ValueError("qualification and assessment identity must match")
    if (
        qualification.allowed is not True
        or assessment.available is not True
        or qualification.reasons
        or assessment.reasons
        or type(qualification.decision_ms) is not int
        or type(assessment.decision_ms) is not int
        or assessment.decision_ms < 0
        or type(quote_ms) is not int
        or quote_ms < 0
        or not 0 <= assessment.decision_ms - quote_ms <= 3_600_000
        or not _finite(quote_price)
        or not _finite(assessment.atr)
        or not _finite(round_trip_cost_rate, positive=False)
        or round_trip_cost_rate >= 1
        or not _finite(qualification.risk_multiplier)
        or not _consistent(assessment, qualification)
    ):
        return None
    assert quote_price is not None and assessment.atr is not None
    assert qualification.owner is not None
    price, atr = Fraction(quote_price), Fraction(assessment.atr)
    cost = price * Fraction(round_trip_cost_rate)
    owner = qualification.owner
    spacing: Fraction | None = None
    if owner == "spot_grid":
        spacing = max(atr / 2, 2 * cost)
        prices = tuple(price - i * spacing for i in (1, 2, 3))
        stop = prices[-1] - 2 * atr
        if stop <= 0:
            return None
        inverse = tuple(1 / (level - stop + cost) for level in prices)
        total = sum(inverse)
        levels = tuple(
            Level(_decimal(level), weight / total)
            for level, weight in zip(prices, inverse, strict=True)
        )
    else:
        stop = price - qualification.side * 2 * atr
        if stop <= 0:
            return None
        levels = (Level(quote_price, Fraction(1)),)
    return ComponentPlan(
        assessment.symbol,
        assessment.decision_ms,
        quote_ms,
        owner,
        "futures" if owner == "futures_trend" else "spot",
        qualification.side,
        quote_price,
        _decimal(stop),
        levels,
        _decimal(spacing) if spacing is not None else None,
        qualification.risk_multiplier,
    )


def grid_target(plan: ComponentPlan, actual_fill: Decimal) -> Decimal:
    """Target follows actual fill, never the original unfilled limit price."""
    if (
        plan.owner != "spot_grid"
        or plan.venue != "spot"
        or plan.side != 1
        or not _finite(plan.spacing)
        or not _finite(actual_fill)
    ):
        raise ValueError("positive fill and valid spot grid required")
    assert plan.spacing is not None
    return _decimal(Fraction(actual_fill) + Fraction(plan.spacing))
