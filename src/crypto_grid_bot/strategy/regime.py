"""Explainable broad-market regime classifier."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

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
        t = self._thresholds
        if (
            not all(
                isfinite(x)
                for x in (
                    t.bull,
                    t.bear,
                    t.range_score_limit,
                    t.range_adx_limit,
                    t.minimum_confidence,
                )
            )
            or not -1 <= t.bear < -t.range_score_limit < 0
            or not 0 < t.range_score_limit < t.bull <= 1
            or not 0 < t.range_adx_limit < 100
            or not 0 < t.minimum_confidence <= 1
        ):
            raise ValueError("invalid regime thresholds")

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
        directional = self._directional_confidence(values, score)
        dispersion = sum(abs(value) for value in values.values()) / len(values)
        range_evidence = max(
            0.0,
            min(
                1.0,
                1.0
                - 0.5 * abs(score) / self._thresholds.range_score_limit
                - 0.25 * (signals.adx / self._thresholds.range_adx_limit) ** 2
                - 0.1 * dispersion,
            ),
        )
        quality = signals.data_quality * (1.0 - signals.news_risk)
        range_confidence = range_evidence * quality
        directional_confidence = directional * quality
        # The maximum of continuous evidence functions remains continuous, even when
        # the discrete regime label changes. This is evidence strength, not probability.
        confidence = max(range_confidence, directional_confidence)
        reasons = self._reasons(values, score, signals) + (
            f"range evidence {range_confidence:.3f}; "
            f"directional evidence {directional_confidence:.3f}",
        )
        if (
            signals.adx <= self._thresholds.range_adx_limit
            and abs(score) <= self._thresholds.range_score_limit
            and range_confidence >= self._thresholds.minimum_confidence
        ):
            return RegimeAssessment(MarketRegime.RANGE, score, confidence, reasons)
        if (
            directional_confidence >= self._thresholds.minimum_confidence
            and signals.adx > self._thresholds.range_adx_limit
        ):
            if score >= self._thresholds.bull:
                return RegimeAssessment(MarketRegime.BULL, score, confidence, reasons)
            if score <= self._thresholds.bear:
                return RegimeAssessment(MarketRegime.BEAR, score, confidence, reasons)
        return RegimeAssessment(MarketRegime.TRANSITION, score, confidence, reasons)

    @staticmethod
    def _directional_confidence(values: dict[str, float], score: float) -> float:
        magnitude = sum(
            abs(values[name]) * weight for name, weight in RegimeClassifier._WEIGHTS.items()
        )
        coherence = abs(score) / magnitude if magnitude else 0.0
        strength = min(1.0, abs(score) / 0.50)
        return strength * (0.65 + 0.35 * coherence)

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
