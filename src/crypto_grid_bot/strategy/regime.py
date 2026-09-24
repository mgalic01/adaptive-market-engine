"""Explainable broad-market regime classifier."""

from __future__ import annotations

from dataclasses import dataclass

from crypto_grid_bot.domain import MarketRegime, MarketSignals, RegimeAssessment


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    bull: float = 0.35
    bear: float = -0.35
    range_score_limit: float = 0.25
    range_adx_limit: float = 22.0
    minimum_confidence: float = 0.70


class RegimeClassifier:
    """Classify market state using a transparent weighted vote."""

    _WEIGHTS = {
        "trend": 0.35,
        "breadth": 0.20,
        "momentum": 0.15,
        "volatility_health": 0.15,
        "liquidity_health": 0.15,
    }

    def __init__(self, thresholds: RegimeThresholds | None = None) -> None:
        self._thresholds = thresholds or RegimeThresholds()

    def classify(self, signals: MarketSignals) -> RegimeAssessment:
        self._validate(signals)
        if signals.emergency:
            return RegimeAssessment(
                MarketRegime.STRESS,
                score=-1.0,
                confidence=1.0,
                reasons=("emergency market flag is active",),
            )

        values = {name: getattr(signals, name) for name in self._WEIGHTS}
        score = sum(values[name] * weight for name, weight in self._WEIGHTS.items())
        directional_confidence = self._directional_confidence(values, score)
        confidence = min(signals.data_quality, directional_confidence) * (1.0 - signals.news_risk)
        reasons = self._reasons(values, score, signals)

        if confidence < self._thresholds.minimum_confidence:
            return RegimeAssessment(MarketRegime.TRANSITION, score, confidence, reasons)
        if (
            signals.adx <= self._thresholds.range_adx_limit
            and abs(score) <= self._thresholds.range_score_limit
        ):
            return RegimeAssessment(MarketRegime.RANGE, score, confidence, reasons)
        if score >= self._thresholds.bull and signals.adx > self._thresholds.range_adx_limit:
            return RegimeAssessment(MarketRegime.BULL, score, confidence, reasons)
        if score <= self._thresholds.bear and signals.adx > self._thresholds.range_adx_limit:
            return RegimeAssessment(MarketRegime.BEAR, score, confidence, reasons)
        return RegimeAssessment(MarketRegime.TRANSITION, score, confidence, reasons)

    @staticmethod
    def _directional_confidence(values: dict[str, float], score: float) -> float:
        if abs(score) < 0.05:
            dispersion = sum(abs(value) for value in values.values()) / len(values)
            return max(0.0, 1.0 - dispersion)
        direction = 1 if score > 0 else -1
        agreeing_weight = sum(
            RegimeClassifier._WEIGHTS[name]
            for name, value in values.items()
            if value == 0 or (value > 0) == (direction > 0)
        )
        strength = min(1.0, abs(score) / 0.50)
        return min(1.0, 0.65 * agreeing_weight + 0.35 * strength)

    @staticmethod
    def _reasons(values: dict[str, float], score: float, signals: MarketSignals) -> tuple[str, ...]:
        strongest = sorted(values.items(), key=lambda item: abs(item[1]), reverse=True)[:2]
        reasons = [f"weighted market score {score:+.3f}"]
        reasons.extend(f"{name} signal {value:+.2f}" for name, value in strongest)
        if signals.news_risk > 0:
            reasons.append(f"news risk reduced confidence by {signals.news_risk:.0%}")
        if signals.data_quality < 1:
            reasons.append(f"data quality is {signals.data_quality:.0%}")
        return tuple(reasons)

    @staticmethod
    def _validate(signals: MarketSignals) -> None:
        for name in RegimeClassifier._WEIGHTS:
            value = getattr(signals, name)
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between -1 and 1")
        if not 0.0 <= signals.data_quality <= 1.0:
            raise ValueError("data_quality must be between 0 and 1")
        if not 0.0 <= signals.news_risk <= 1.0:
            raise ValueError("news_risk must be between 0 and 1")
        if not 0.0 <= signals.adx <= 100.0:
            raise ValueError("adx must be between 0 and 100")
