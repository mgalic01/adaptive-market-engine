from unittest import TestCase

from crypto_grid_bot.domain import (
    CandidateMetrics,
    MarketRegime,
    MarketSignals,
    RegimeAssessment,
)
from crypto_grid_bot.strategy.opportunity import OpportunityScorer
from crypto_grid_bot.strategy.regime import RegimeClassifier


class OpportunityScorerTests(TestCase):
    def setUp(self) -> None:
        self.scorer = OpportunityScorer(
            minimum_score=0.70,
            maximum_news_risk=0.30,
            maximum_spread_pct=0.15,
            minimum_depth_multiple=50.0,
        )
        self.range_regime = RegimeAssessment(MarketRegime.RANGE, 0.0, 0.9, ())

    def test_good_range_candidate_is_eligible(self) -> None:
        candidate = CandidateMetrics("NIGHTUSDT", 0.9, 0.9, 0.9, 0.8, 1.0, 0.1, 0.05, 80)
        result = self.scorer.score(candidate, self.range_regime)
        self.assertTrue(result.eligible)

    def test_news_risk_vetoes_candidate(self) -> None:
        candidate = CandidateMetrics("COINUSDT", 1, 1, 1, 1, 1, 0.8, 0.01, 100)
        result = self.scorer.score(candidate, self.range_regime)
        self.assertFalse(result.eligible)
        self.assertTrue(any("news risk" in reason for reason in result.reasons))

    def test_quality_veto_is_distinct_from_healthy_transition(self) -> None:
        scorer = OpportunityScorer(
            minimum_score=0.30,
            maximum_news_risk=0.30,
            maximum_spread_pct=0.15,
            minimum_depth_multiple=50,
        )
        candidate = CandidateMetrics("NIGHTUSDT", 1, 1, 1, 1, 1, 0, 0.01, 100)
        for quality, eligible in ((0.69, False), (0.70, True), (1.0, True)):
            with self.subTest(quality=quality):
                regime = RegimeClassifier().classify(
                    MarketSignals(0.30, 0.30, 0.30, 0.30, 0.30, 14, data_quality=quality)
                )
                self.assertEqual(MarketRegime.TRANSITION, regime.regime)
                self.assertEqual(eligible, regime.input_quality_ok)
                self.assertEqual(eligible, scorer.score(candidate, regime).eligible)

    def test_bad_spread_or_depth_cannot_pass(self) -> None:
        for spread, depth in [(float("nan"), 100), (0.1, float("inf")), (-1, 100)]:
            candidate = CandidateMetrics("TESTUSDT", 1, 1, 1, 1, 1, 0, spread, depth)
            with self.assertRaises(ValueError):
                self.scorer.score(candidate, self.range_regime)
