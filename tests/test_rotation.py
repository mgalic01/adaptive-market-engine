from datetime import UTC, datetime, timedelta
from unittest import TestCase

from crypto_grid_bot.strategy.rotation import RotationPolicy, RotationState


class RotationPolicyTests(TestCase):
    def setUp(self) -> None:
        self.policy = RotationPolicy(
            minimum_relative_improvement=0.20,
            confirmation_cycles=2,
            minimum_cost_multiple=3,
            cooldown_hours=24,
        )

    def test_requires_two_confirmations(self) -> None:
        state = RotationState()
        now = datetime.now(UTC)
        inputs = dict(
            state=state,
            incumbent_symbol="AAAUSDT",
            incumbent_score=0.50,
            challenger_symbol="BBBUSDT",
            challenger_score=0.70,
            expected_improvement_quote=4,
            switching_cost_quote=1,
        )
        self.assertFalse(self.policy.should_rotate(now=now, **inputs))
        self.assertTrue(self.policy.should_rotate(now=now + timedelta(hours=4), **inputs))

    def test_cooldown_blocks_rotation(self) -> None:
        now = datetime.now(UTC)
        state = RotationState(last_rotation_at=now - timedelta(hours=2))
        result = self.policy.should_rotate(
            state=state,
            incumbent_symbol="AAAUSDT",
            incumbent_score=0.50,
            challenger_symbol="BBBUSDT",
            challenger_score=0.90,
            expected_improvement_quote=10,
            switching_cost_quote=1,
            now=now,
        )
        self.assertFalse(result)

    def test_repeated_scan_cannot_count_twice(self) -> None:
        state = RotationState()
        now = datetime.now(UTC)
        inputs = dict(
            state=state,
            incumbent_symbol="AAA",
            incumbent_score=0.5,
            challenger_symbol="BBB",
            challenger_score=0.8,
            expected_improvement_quote=4,
            switching_cost_quote=1,
            now=now,
        )
        self.assertFalse(self.policy.should_rotate(**inputs))
        self.assertFalse(self.policy.should_rotate(**inputs))
        self.assertEqual(1, state.consecutive_wins)

    def test_cooldown_starts_only_after_confirmed_rotation(self) -> None:
        state = RotationState()
        now = datetime.now(UTC)
        inputs = dict(
            state=state,
            incumbent_symbol="AAA",
            incumbent_score=0.5,
            challenger_symbol="BBB",
            challenger_score=0.8,
            expected_improvement_quote=4,
            switching_cost_quote=1,
        )
        self.assertFalse(self.policy.should_rotate(**inputs, now=now))
        later = now + timedelta(hours=1)
        self.assertTrue(self.policy.should_rotate(**inputs, now=later))
        self.assertIsNone(state.last_rotation_at)
        self.policy.confirm_rotation(state, later)
        self.assertEqual(later, state.last_rotation_at)
        self.assertFalse(self.policy.should_rotate(**inputs, now=later + timedelta(hours=1)))

    def test_invalid_costs_and_non_improvements_do_not_rotate(self) -> None:
        now = datetime.now(UTC)
        for benefit, cost in [(0, 0), (3, 1), (10, -1), (float("nan"), 1)]:
            state = RotationState()
            for cycle in range(3):
                self.assertFalse(
                    self.policy.should_rotate(
                        state=state,
                        incumbent_symbol="AAA",
                        incumbent_score=0.5,
                        challenger_symbol="BBB",
                        challenger_score=0.8,
                        expected_improvement_quote=benefit,
                        switching_cost_quote=cost,
                        now=now + timedelta(hours=cycle),
                    )
                )
