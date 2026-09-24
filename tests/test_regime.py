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


class ContinuousRegimeTests(TestCase):
    def test_old_point_zero_five_boundary_has_no_confidence_cliff(self):
        classifier = RegimeClassifier()
        results = [
            classifier.classify(MarketSignals(x, x, x, x, x, adx=14)) for x in (0.049, 0.050, 0.051)
        ]
        self.assertTrue(all(r.regime == MarketRegime.RANGE for r in results))
        self.assertLess(
            max(r.confidence for r in results) - min(r.confidence for r in results), 0.01
        )

    def test_mixed_low_trend_signals_can_classify_as_range(self):
        result = RegimeClassifier().classify(MarketSignals(0.1, -0.05, 0.1, 0.1, 0.1, adx=14))
        self.assertEqual(MarketRegime.RANGE, result.regime)

    def test_low_quality_and_news_still_veto_range(self):
        for kwargs in ({"data_quality": 0.3}, {"news_risk": 0.8}):
            result = RegimeClassifier().classify(MarketSignals(0, 0, 0, 0, 0, adx=10, **kwargs))
            self.assertEqual(MarketRegime.TRANSITION, result.regime)
            self.assertLess(result.confidence, 0.7)

    def test_directional_evidence_is_sign_symmetric_and_continuous(self):
        classifier = RegimeClassifier()
        previous = None
        for i in range(-1000, 1001):
            x = i / 1000
            result = classifier.classify(MarketSignals(x, x, x, x, x, adx=30))
            if previous is not None:
                self.assertLess(abs(previous - result.confidence), 0.01)
            previous = result.confidence
            mirror = classifier.classify(MarketSignals(-x, -x, -x, -x, -x, adx=30))
            self.assertAlmostEqual(result.confidence, mirror.confidence)
        self.assertEqual(
            MarketRegime.BEAR,
            classifier.classify(MarketSignals(-0.9, -0.8, -0.8, -0.7, -0.8, 31)).regime,
        )
