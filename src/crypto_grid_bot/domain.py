"""Core immutable domain objects used by strategy and risk modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class MarketRegime(StrEnum):
    RANGE = "range"
    BULL = "bull"
    BEAR = "bear"
    TRANSITION = "transition"
    STRESS = "stress"


class RiskAction(StrEnum):
    ALLOW = "allow"
    REDUCE = "reduce"
    PAUSE = "pause"
    EXIT = "exit"


@dataclass(frozen=True, slots=True)
class MarketSignals:
    """Normalized broad-market inputs.

    Signed signals use -1 (strongly bearish) to +1 (strongly bullish).
    Data quality and news risk use 0 to 1.
    """

    trend: float
    breadth: float
    momentum: float
    volatility_health: float
    liquidity_health: float
    adx: float
    data_quality: float = 1.0
    news_risk: float = 0.0
    emergency: bool = False
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class RegimeAssessment:
    regime: MarketRegime
    score: float
    confidence: float
    reasons: tuple[str, ...]
    input_quality_ok: bool = True


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    symbol: str
    range_quality: float
    net_grid_edge: float
    liquidity_quality: float
    downside_quality: float
    data_quality: float
    news_risk: float
    spread_pct: float
    depth_multiple: float


@dataclass(frozen=True, slots=True)
class CandidateScore:
    symbol: str
    score: float
    eligible: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshot:
    active_equity: float
    day_start_equity: float
    high_water_mark: float
    data_age_seconds: int
    balances_reconciled: bool = True
    orders_reconciled: bool = True
    emergency: bool = False


@dataclass(frozen=True, slots=True)
class RiskDecision:
    action: RiskAction
    capital_multiplier: float
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GridPlan:
    symbol: str
    lower_price: float
    upper_price: float
    levels: tuple[float, ...]
    capital: float
    estimated_spacing_pct: float
