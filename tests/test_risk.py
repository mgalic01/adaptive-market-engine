from decimal import Decimal as D
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

    def test_an_equity_exactly_on_a_limit_is_on_it(self) -> None:
        # Each equity is exactly 12%, 8% or 3% below its reference. Through floats every
        # one of these ratios rounds a hair under its limit (e.g. 0.11999999999999990),
        # so the old float engine let each of them through.
        cases = [
            ((D("44.264"), D("44.264"), D("50.3")), RiskAction.EXIT, "hard drawdown"),
            ((D("46.276"), D("46.276"), D("50.3")), RiskAction.REDUCE, "soft drawdown"),
            ((D("49.276"), D("50.8"), D("50.8")), RiskAction.PAUSE, "daily loss"),
        ]
        for values, action, reason in cases:
            with self.subTest(values=values):
                self.assertLess(
                    (float(values[2]) - float(values[0])) / float(values[2]),
                    {"hard drawdown": 0.12, "soft drawdown": 0.08}.get(reason, 0.03),
                )
                decision = self.engine.evaluate(PortfolioSnapshot(*values, 1))
                self.assertEqual(action, decision.action)
                self.assertTrue(decision.reasons[0].startswith(reason))
        # One hundredth of a cent above each limit's equity is inside it.
        self.assertEqual(
            RiskAction.REDUCE,
            self.engine.evaluate(
                PortfolioSnapshot(D("44.2641"), D("44.2641"), D("50.3"), 1)
            ).action,
        )
        self.assertEqual(
            RiskAction.ALLOW,
            self.engine.evaluate(
                PortfolioSnapshot(D("46.2761"), D("46.2761"), D("50.3"), 1)
            ).action,
        )
        self.assertEqual(
            RiskAction.ALLOW,
            self.engine.evaluate(PortfolioSnapshot(D("49.2761"), D("50.8"), D("50.8"), 1)).action,
        )

    def test_reason_text_keeps_its_float_formatting(self) -> None:
        decision = self.engine.evaluate(PortfolioSnapshot(D("87.5"), D("100"), D("100"), 1))
        self.assertEqual(("hard drawdown reached: 12.50%",), decision.reasons)

    def test_invalid_risk_thresholds_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RiskEngine(
                daily_loss_pause_pct=0.1,
                soft_drawdown_pct=0.08,
                hard_drawdown_pct=0.12,
                maximum_data_age_seconds=30,
            )

    def test_equities_too_small_for_a_float_still_get_a_decision(self) -> None:
        # Codex review of #159: every float here is 0.0, and the reason text divided by it.
        snapshot = PortfolioSnapshot(D("1e-1000"), D("2e-1000"), D("2e-1000"), 1)
        decision = self.engine.evaluate(snapshot)
        self.assertEqual(RiskAction.EXIT, decision.action)
        self.assertEqual(("hard drawdown reached: 50.00%",), decision.reasons)

    def test_equities_beyond_a_float_are_invalid(self) -> None:
        # Codex review of #159: Decimal arithmetic on these raised decimal.Overflow.
        snapshot = PortfolioSnapshot(D("1e1000000"), D("2e1000000"), D("2e1000000"), 1)
        decision = self.engine.evaluate(snapshot)
        self.assertEqual(
            (RiskAction.PAUSE, ("invalid portfolio equity",)), (decision.action, decision.reasons)
        )
