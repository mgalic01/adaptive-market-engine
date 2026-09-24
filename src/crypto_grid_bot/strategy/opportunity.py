"""Coin eligibility and opportunity ranking."""

from __future__ import annotations

from math import isfinite

from crypto_grid_bot.domain import (
    CandidateMetrics,
    CandidateScore,
    MarketRegime,
    RegimeAssessment,
)


class OpportunityScorer:
    _WEIGHTS = {
        "range_quality": 0.30,
        "net_grid_edge": 0.25,
        "liquidity_quality": 0.20,
        "downside_quality": 0.15,
        "data_quality": 0.10,
    }
    _REGIME_FIT = {
        MarketRegime.RANGE: 1.00,
        MarketRegime.BULL: 0.80,
        MarketRegime.TRANSITION: 0.35,
        MarketRegime.BEAR: 0.20,
        MarketRegime.STRESS: 0.00,
    }

    def __init__(
        self,
        *,
        minimum_score: float,
        maximum_news_risk: float,
        maximum_spread_pct: float,
        minimum_depth_multiple: float,
    ) -> None:
        if not 0 < minimum_score <= 1 or not 0 <= maximum_news_risk <= 1:
            raise ValueError("invalid score or news threshold")
        if any(not isfinite(x) or x <= 0 for x in (maximum_spread_pct, minimum_depth_multiple)):
            raise ValueError("spread/depth thresholds must be finite and positive")
        self._minimum_score = minimum_score
        self._maximum_news_risk = maximum_news_risk
        self._maximum_spread_pct = maximum_spread_pct
        self._minimum_depth_multiple = minimum_depth_multiple

    def score(self, candidate: CandidateMetrics, regime: RegimeAssessment) -> CandidateScore:
        self._validate(candidate)
        failures: list[str] = []
        if candidate.news_risk > self._maximum_news_risk:
            failures.append("news risk exceeds the eligibility limit")
        if candidate.spread_pct > self._maximum_spread_pct:
            failures.append("spread exceeds the eligibility limit")
        if candidate.depth_multiple < self._minimum_depth_multiple:
            failures.append("order-book depth is insufficient")
        if regime.regime is MarketRegime.STRESS:
            failures.append("market is in stress mode")

        base = sum(getattr(candidate, name) * weight for name, weight in self._WEIGHTS.items())
        news_multiplier = 1.0 - candidate.news_risk
        score = base * self._REGIME_FIT[regime.regime] * news_multiplier
        if score < self._minimum_score:
            failures.append(f"opportunity score {score:.3f} is below minimum")
        reasons = (
            f"base quality {base:.3f}",
            f"regime fit {self._REGIME_FIT[regime.regime]:.2f}",
            f"news multiplier {news_multiplier:.2f}",
            *failures,
        )
        return CandidateScore(candidate.symbol, score, not failures, reasons)

    def rank(
        self, candidates: list[CandidateMetrics], regime: RegimeAssessment
    ) -> list[CandidateScore]:
        return sorted(
            (self.score(candidate, regime) for candidate in candidates),
            key=lambda result: result.score,
            reverse=True,
        )

    @staticmethod
    def _validate(candidate: CandidateMetrics) -> None:
        for name in OpportunityScorer._WEIGHTS:
            value = getattr(candidate, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0.0 <= candidate.news_risk <= 1.0:
            raise ValueError("news_risk must be between 0 and 1")
        if any(not isfinite(x) or x < 0 for x in (candidate.spread_pct, candidate.depth_multiple)):
            raise ValueError("spread and depth must be non-negative")
