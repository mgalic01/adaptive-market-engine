from decimal import Decimal as D
from unittest import TestCase

from crypto_grid_bot.portfolio.profit_vault import ProfitVault, ProfitVaultState


class ProfitVaultTests(TestCase):
    def setUp(self) -> None:
        self.vault = ProfitVault(reserve_fraction=D("0.5"), minimum_transfer_quote=D("10"))

    def allocate(self, state: ProfitVaultState, equity: str):
        return self.vault.allocate(state, D(equity), positions_flat=True, orders_reconciled=True)

    def test_splits_new_profit_and_updates_high_water_mark(self) -> None:
        state = ProfitVaultState(active_high_water_mark=D("100"))
        allocation = self.allocate(state, "120")
        self.assertEqual(10, allocation.reserve_amount)
        self.assertEqual(10, allocation.compound_amount)
        self.assertEqual(110, allocation.new_active_high_water_mark)
        self.assertEqual(10, allocation.transfer_due)

    def test_recovery_does_not_count_as_new_profit(self) -> None:
        state = ProfitVaultState(active_high_water_mark=D("110"))
        allocation = self.allocate(state, "105")
        self.assertEqual(0, allocation.new_profit)
        self.assertEqual(110, state.active_high_water_mark)

    def test_confirmed_transfer_becomes_secured(self) -> None:
        state = ProfitVaultState(active_high_water_mark=D("100"))
        allocation = self.allocate(state, "120")
        self.vault.confirm_transfer(state, allocation.transfer_due, "transfer-1")
        self.assertEqual(0, state.pending_reserve)
        self.assertEqual(10, state.secured_reserve)

    def test_repeated_balance_is_not_new_profit(self) -> None:
        state = ProfitVaultState(D("100"))
        self.allocate(state, "120")
        for _ in range(10):
            self.assertEqual(0, self.allocate(state, "120").new_profit)
        self.assertEqual(10, state.pending_reserve)
        self.assertEqual(110, state.active_high_water_mark)

    def test_profit_loop_and_transfer_retry(self) -> None:
        state = ProfitVaultState(D("100"))
        first = self.allocate(state, "200")
        self.assertEqual(150, first.active_capital_after_allocation)
        self.assertEqual(50, state.pending_reserve)
        self.vault.confirm_transfer(state, D("50"), "one")
        self.vault.confirm_transfer(state, D("50"), "one")
        self.assertEqual(0, self.allocate(state, "150").new_profit)
        second = self.allocate(state, "180")
        self.assertEqual(15, second.reserve_amount)
        self.assertEqual(165, second.active_capital_after_allocation)
        self.assertEqual(50, state.secured_reserve)

    def test_partial_transfer_and_loss_recovery(self) -> None:
        state = ProfitVaultState(D("100"))
        self.allocate(state, "120")
        self.vault.confirm_transfer(state, D("4"), "partial")
        self.assertEqual(0, self.allocate(state, "116").new_profit)
        self.assertEqual(0, self.allocate(state, "106").new_profit)
        self.assertEqual(0, self.allocate(state, "116").new_profit)
        self.assertEqual(6, state.pending_reserve)

    def test_transfer_id_amount_mismatch_is_rejected(self) -> None:
        state = ProfitVaultState(D("100"), pending_reserve=D("20"))
        self.vault.confirm_transfer(state, D("10"), "one")
        with self.assertRaises(ValueError):
            self.vault.confirm_transfer(state, D("5"), "one")
        self.assertEqual(10, state.pending_reserve)

    def test_unrealized_or_unreconciled_allocation_is_rejected(self) -> None:
        state = ProfitVaultState(D("100"))
        for flat, reconciled in [(False, True), (True, False)]:
            with self.assertRaises(ValueError):
                self.vault.allocate(
                    state, D("200"), positions_flat=flat, orders_reconciled=reconciled
                )
        self.assertEqual(0, state.pending_reserve)

    def test_invalid_equity_is_rejected_without_mutation(self) -> None:
        state = ProfitVaultState(D("100"))
        for value in ["NaN", "Infinity", "-1"]:
            with self.assertRaises(ValueError):
                self.allocate(state, value)
        self.assertEqual(100, state.active_high_water_mark)

    def test_reserve_cannot_cover_trading_loss(self) -> None:
        state = ProfitVaultState(D("100"), pending_reserve=D("10"))
        with self.assertRaises(ValueError):
            self.allocate(state, "5")
        self.assertEqual(10, state.pending_reserve)

    def test_small_profits_accumulate_below_transfer_threshold(self) -> None:
        state = ProfitVaultState(D("100"))
        first = self.allocate(state, "100.10")
        self.assertEqual(D("0.05"), first.reserve_amount)
        self.assertEqual(0, first.transfer_due)
        self.assertEqual(0, self.allocate(state, "100.10").new_profit)
