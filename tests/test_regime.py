from unittest import TestCase

from crypto_grid_bot.domain import MarketRegime, MarketSignals
from crypto_grid_bot.strategy.regime import RegimeClassifier, RegimeThresholds


class RegimeClassifierTests(TestCase):
    def setUp(self) -> None:
        self.classifier = RegimeClassifier(RegimeThresholds(minimum_confidence=0.60))

    def test_classifies_confirmed_bull(self) -> None:
        result = self.classifier.classify(MarketSignals(0.9, 0.8, 0.8, 0.7, 0.8, adx=31.0))
        self.assertEqual(MarketRegime.BULL, result.regime)

    def test_classifies_quiet_range(self) -> None:
        result = self.classifier.classify(MarketSignals(0.02, -0.01, 0.01, 0.02, 0.01, adx=14.0))
        self.assertEqual(MarketRegime.RANGE, result.regime)

    def test_emergency_overrides_other_signals(self) -> None:
        result = self.classifier.classify(
            MarketSignals(1.0, 1.0, 1.0, 1.0, 1.0, adx=60.0, emergency=True)
        )
        self.assertEqual(MarketRegime.STRESS, result.regime)
