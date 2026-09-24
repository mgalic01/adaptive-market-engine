"""Explainable broad-market regime classifier.

The configured limits are the actual decision boundaries:

* ``RANGE`` iff input quality >= ``minimum_input_quality`` and ``|score|``, ADX and
  signal dispersion are all within their configured range limits.
* ``BULL``/``BEAR`` iff input quality >= ``minimum_input_quality``, ADX is above the
  range limit and coherence-adjusted directional evidence reaches
  ``minimum_confidence``. For fully coherent votes that is exactly
  ``score >= bull`` or ``score <= bear``; conflicting votes need a larger score.
* ``STRESS`` when the emergency flag is set, otherwise ``TRANSITION``.

Evidence values are continuous and equal ``minimum_confidence`` on each boundary.
Input quality is a veto, not a multiplier stacked on the confidence gate. Evidence
is a heuristic strength, not a calibrated probability of any market outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING

from crypto_grid_bot.domain import MarketRegime, MarketSignals, RegimeAssessment

if TYPE_CHECKING:
    from crypto_grid_bot.config import BotConfig


@dataclass(frozen=True, slots=True)
class RegimeThresholds:
    bull: float = 0.35
    bear: float = -0.35
    range_score_limit: float = 0.25
    range_adx_limit: float = 22.0
    minimum_confidence: float = 0.70
    minimum_input_quality: float = 0.70
    range_dispersion_limit: float = 0.50
    # Model constant: share of directional evidence that depends on vote coherence.
    coherence_weight: float = 0.35

    def __post_init__(self) -> None:
        values = (
            self.bull,
            self.bear,
            self.range_score_limit,
            self.range_adx_limit,
            self.minimum_confidence,
            self.minimum_input_quality,
            self.range_dispersion_limit,
            self.coherence_weight,
        )
        if (
            not all(isfinite(value) for value in values)
            or not -1 <= self.bear < -self.range_score_limit < 0
            or not 0 < self.range_score_limit < self.bull <= 1
            or not 0 < self.range_adx_limit < 100
            or not 0 < self.minimum_confidence < 1
            or not 0 < self.minimum_input_quality <= 1
            or not 0 < self.range_dispersion_limit <= 1
            or not 0 <= self.coherence_weight < 1
        ):
            raise ValueError("invalid regime thresholds")


def thresholds_from_config(config: BotConfig) -> RegimeThresholds:
    return RegimeThresholds(
        bull=config.bull_threshold,
        bear=config.bear_threshold,
        range_score_limit=config.range_score_limit,
        range_adx_limit=config.range_adx_limit,
        minimum_confidence=config.minimum_confidence,
        minimum_input_quality=config.minimum_input_quality,
        range_dispersion_limit=config.range_dispersion_limit,
    )


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

    @property
    def thresholds(self) -> RegimeThresholds:
        return self._thresholds

    def classify(self, signals: MarketSignals) -> RegimeAssessment:
        self._validate(signals)
        if signals.emergency:
            return RegimeAssessment(
                MarketRegime.STRESS,
                score=-1.0,
                confidence=1.0,
                reasons=("emergency market flag is active",),
            )

        t = self._thresholds
        values = {name: getattr(signals, name) for name in self._WEIGHTS}
        score = sum(values[name] * weight for name, weight in self._WEIGHTS.items())
        dispersion = sum(abs(value) for value in values.values()) / len(values)
        quality = signals.data_quality * (1.0 - signals.news_risk)

        # Largest fraction of any configured range limit; <= 1 means inside the box.
        range_load = max(
            abs(score) / t.range_score_limit,
            signals.adx / t.range_adx_limit,
            dispersion / t.range_dispersion_limit,
        )
        range_evidence = _unit(1.0 - (1.0 - t.minimum_confidence) * range_load)
        directional_evidence = self._directional_evidence(values, score)

        # Continuous reporting; the decision itself uses the quality floor as a veto.
        quality_factor = min(1.0, quality / t.minimum_input_quality)
        range_confidence = range_evidence * quality_factor
        directional_confidence = directional_evidence * quality_factor
        confidence = max(range_confidence, directional_confidence)
        quality_ok = quality >= t.minimum_input_quality

        reasons = self._reasons(values, score, signals) + (
            f"range evidence {range_evidence:.3f} (load {range_load:.2f} of limits); "
            f"directional evidence {directional_evidence:.3f}; "
            f"dominant: {'range' if range_evidence >= directional_evidence else 'directional'}",
            f"input quality {quality:.2f} (floor {t.minimum_input_quality:.2f})",
        )
        if not quality_ok:
            reasons += ("input quality is below the floor; regime vetoed",)
            return RegimeAssessment(
                MarketRegime.TRANSITION, score, confidence, reasons, input_quality_ok=False
            )
        if range_load <= 1.0:
            return RegimeAssessment(MarketRegime.RANGE, score, confidence, reasons)
        if signals.adx > t.range_adx_limit and directional_evidence >= t.minimum_confidence:
            if score >= t.bull:
                return RegimeAssessment(MarketRegime.BULL, score, confidence, reasons)
            if score <= t.bear:
                return RegimeAssessment(MarketRegime.BEAR, score, confidence, reasons)
        return RegimeAssessment(MarketRegime.TRANSITION, score, confidence, reasons)

    def _directional_evidence(self, values: dict[str, float], score: float) -> float:
        t = self._thresholds
        threshold = t.bull if score >= 0 else -t.bear
        # Equals minimum_confidence exactly at the configured bull/bear threshold.
        strength = min(1.0, t.minimum_confidence * abs(score) / threshold)
        magnitude = sum(abs(values[name]) * weight for name, weight in self._WEIGHTS.items())
        coherence = abs(score) / magnitude if magnitude else 0.0
        return strength * (1.0 - t.coherence_weight + t.coherence_weight * coherence)

    @staticmethod
    def _reasons(values: dict[str, float], score: float, signals: MarketSignals) -> tuple[str, ...]:
        strongest = sorted(values.items(), key=lambda item: abs(item[1]), reverse=True)[:2]
        reasons = [f"weighted market score {score:+.3f}"]
        reasons.extend(f"{name} signal {value:+.2f}" for name, value in strongest)
        if signals.news_risk > 0:
            reasons.append(f"news risk {signals.news_risk:.0%}")
        if signals.data_quality < 1:
            reasons.append(f"data quality is {signals.data_quality:.0%}")
        return tuple(reasons)

    @staticmethod
    def _validate(signals: MarketSignals) -> None:
        for name in RegimeClassifier._WEIGHTS:
            value = getattr(signals, name)
            if not isfinite(value) or not -1.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between -1 and 1")
        if not isfinite(signals.data_quality) or not 0.0 <= signals.data_quality <= 1.0:
            raise ValueError("data_quality must be between 0 and 1")
        if not isfinite(signals.news_risk) or not 0.0 <= signals.news_risk <= 1.0:
            raise ValueError("news_risk must be between 0 and 1")
        if not isfinite(signals.adx) or not 0.0 <= signals.adx <= 100.0:
            raise ValueError("adx must be between 0 and 100")


def _unit(value: float) -> float:
    return max(0.0, min(1.0, value))
