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


class ConfiguredBoundaryTests(TestCase):
    """Claude review #2: configured limits must be the actual decision boundaries."""

    def setUp(self) -> None:
        self.thresholds = RegimeThresholds()
        self.classifier = RegimeClassifier(self.thresholds)

    def test_range_is_reachable_everywhere_inside_the_configured_box(self) -> None:
        for quality in (0.70, 0.72, 0.85, 1.0):
            for step in range(-24, 25, 4):
                x = step / 100  # uniform votes: score == x, dispersion == |x|
                for adx in (0.0, 11.0, 21.9):
                    with self.subTest(quality=quality, score=x, adx=adx):
                        result = self.classifier.classify(
                            MarketSignals(x, x, x, x, x, adx=adx, data_quality=quality)
                        )
                        self.assertEqual(MarketRegime.RANGE, result.regime)
                        self.assertGreaterEqual(
                            result.confidence, self.thresholds.minimum_confidence
                        )

    def test_review_table_cases_reach_range_above_the_quality_floor(self) -> None:
        for data_quality, news_risk in ((1.0, 0.0), (0.95, 0.1), (0.9, 0.2)):
            with self.subTest(data_quality=data_quality, news_risk=news_risk):
                result = self.classifier.classify(
                    MarketSignals(
                        0, 0, 0, 0, 0, adx=15, data_quality=data_quality, news_risk=news_risk
                    )
                )
                self.assertEqual(MarketRegime.RANGE, result.regime)

    def test_just_outside_each_range_limit_is_not_range(self) -> None:
        cases = {
            "score": MarketSignals(0.26, 0.26, 0.26, 0.26, 0.26, adx=10),
            "adx": MarketSignals(0, 0, 0, 0, 0, adx=22.1),
            "dispersion": MarketSignals(1.0, -1.0, -1.0, 0.0, 0.0, adx=10),
        }
        for limit, signals in cases.items():
            with self.subTest(limit=limit):
                result = self.classifier.classify(signals)
                self.assertEqual(MarketRegime.TRANSITION, result.regime)
                self.assertLess(result.confidence, self.thresholds.minimum_confidence)

    def test_quality_floor_is_a_veto_with_continuous_confidence(self) -> None:
        below = self.classifier.classify(MarketSignals(0, 0, 0, 0, 0, adx=10, data_quality=0.699))
        above = self.classifier.classify(MarketSignals(0, 0, 0, 0, 0, adx=10, data_quality=0.701))
        self.assertEqual(MarketRegime.TRANSITION, below.regime)
        self.assertEqual(MarketRegime.RANGE, above.regime)
        self.assertLess(abs(above.confidence - below.confidence), 0.01)
        self.assertTrue(any("below the floor" in reason for reason in below.reasons))

    def test_directional_boundary_follows_configured_thresholds(self) -> None:
        classifier = RegimeClassifier(
            RegimeThresholds(bull=0.45, bear=-0.45, minimum_confidence=0.8)
        )
        for x, expected in (
            (0.449, MarketRegime.TRANSITION),
            (0.451, MarketRegime.BULL),
            (-0.449, MarketRegime.TRANSITION),
            (-0.451, MarketRegime.BEAR),
        ):
            with self.subTest(score=x):
                result = classifier.classify(MarketSignals(x, x, x, x, x, adx=30))
                self.assertEqual(expected, result.regime)

    def test_default_directional_evidence_matches_the_previous_formula(self) -> None:
        # The retired hard-coded 0.50 equals bull / minimum_confidence at the defaults.
        for x in (0.1, 0.3, 0.35, 0.42, 0.5, 0.8):
            for values in ((x, x, x, x, x), (x, x, x, -x / 2, 0.0)):
                named = dict(zip(RegimeClassifier._WEIGHTS, values, strict=True))
                score = sum(named[k] * w for k, w in RegimeClassifier._WEIGHTS.items())
                magnitude = sum(abs(named[k]) * w for k, w in RegimeClassifier._WEIGHTS.items())
                previous = min(1.0, abs(score) / 0.50) * (0.65 + 0.35 * abs(score) / magnitude)
                self.assertAlmostEqual(
                    previous, self.classifier._directional_evidence(named, score)
                )

    def test_strong_conflicting_votes_are_neither_range_nor_trend(self) -> None:
        cancelled = self.classifier.classify(MarketSignals(1.0, -1.0, -1.0, 0.0, 0.0, adx=15))
        unhealthy_trend = self.classifier.classify(MarketSignals(1.0, 1.0, 1.0, -1.0, -1.0, adx=30))
        self.assertEqual(MarketRegime.TRANSITION, cancelled.regime)
        self.assertEqual(MarketRegime.TRANSITION, unhealthy_trend.regime)
        self.assertTrue(any("dominant:" in reason for reason in unhealthy_trend.reasons))

    def test_invalid_thresholds_are_rejected(self) -> None:
        for kwargs in (
            {"minimum_input_quality": 0.0},
            {"minimum_input_quality": 1.1},
            {"range_dispersion_limit": 0.0},
            {"coherence_weight": 1.0},
            {"minimum_confidence": 1.0},
            {"minimum_confidence": float("nan")},
            {"range_score_limit": 0.4},
        ):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                RegimeThresholds(**kwargs)
