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
