from unittest import TestCase

from crypto_grid_bot.domain import PortfolioSnapshot, RiskAction
from crypto_grid_bot.risk.engine import RiskEngine


class RiskEngineTests(TestCase):
    def setUp(self) -> None:
        self.engine = RiskEngine(
            daily_loss_pause_pct=0.03,
            soft_drawdown_pct=0.08,
            hard_drawdown_pct=0.12,
            maximum_data_age_seconds=30,
        )

    def test_stale_data_pauses(self) -> None:
        decision = self.engine.evaluate(PortfolioSnapshot(100, 100, 100, 31))
        self.assertEqual(RiskAction.PAUSE, decision.action)

    def test_hard_drawdown_exits(self) -> None:
        decision = self.engine.evaluate(PortfolioSnapshot(87, 100, 100, 1))
        self.assertEqual(RiskAction.EXIT, decision.action)

    def test_safe_portfolio_is_allowed(self) -> None:
        decision = self.engine.evaluate(PortfolioSnapshot(101, 100, 101, 1))
        self.assertEqual(RiskAction.ALLOW, decision.action)

    def test_daily_pause_takes_precedence_over_soft_drawdown(self) -> None:
        decision = self.engine.evaluate(PortfolioSnapshot(91, 100, 100, 1))
        self.assertEqual(RiskAction.PAUSE, decision.action)

    def test_soft_drawdown_without_daily_loss_reduces(self) -> None:
        decision = self.engine.evaluate(PortfolioSnapshot(91, 91, 100, 1))
        self.assertEqual(RiskAction.REDUCE, decision.action)

    def test_bad_numbers_fail_closed(self) -> None:
        for bad in [float("nan"), float("inf"), -1]:
            for values in [(bad, 100, 100), (100, bad, 100), (100, 100, bad)]:
                with self.subTest(values=values):
                    decision = self.engine.evaluate(PortfolioSnapshot(*values, 1))
                    self.assertEqual(RiskAction.PAUSE, decision.action)

    def test_invalid_data_age_pauses(self) -> None:
        for age in [-1, float("nan"), float("inf")]:
            self.assertEqual(
                RiskAction.PAUSE,
                self.engine.evaluate(PortfolioSnapshot(100, 100, 100, age)).action,
            )

    def test_unknown_orders_block_emergency_execution(self) -> None:
        snapshot = PortfolioSnapshot(100, 100, 100, 1, orders_reconciled=False, emergency=True)
        self.assertEqual(RiskAction.PAUSE, self.engine.evaluate(snapshot).action)

    def test_invalid_risk_thresholds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RiskEngine(
                daily_loss_pause_pct=0.1,
                soft_drawdown_pct=0.08,
                hard_drawdown_pct=0.12,
                maximum_data_age_seconds=30,
            )
