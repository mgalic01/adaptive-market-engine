"""Simulation-only settled-profit ledger; no exchange transfers are performed."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

ZERO = Decimal("0")


def _money(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < ZERO:
        raise ValueError(f"{name} must be a finite, non-negative Decimal")


@dataclass(slots=True)
class ProfitVaultState:
    active_high_water_mark: Decimal
    pending_reserve: Decimal = ZERO
    secured_reserve: Decimal = ZERO
    confirmed_transfers: dict[str, Decimal] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProfitAllocation:
    new_profit: Decimal
    compound_amount: Decimal
    reserve_amount: Decimal
    transfer_due: Decimal
    active_capital_after_allocation: Decimal
    new_active_high_water_mark: Decimal


class ProfitVault:
    """Split settled new profits, excluding all previously earmarked reserve.

    Input equity includes pending reserve, excludes transferred reserve, and
    must be settled quote cash after fees with no open orders or positions.
    Deposits/withdrawals require separate reconciliation and are unsupported.
    Calls and transfer confirmations must be serialized by a future executor.
    """

    def __init__(self, *, reserve_fraction: Decimal, minimum_transfer_quote: Decimal) -> None:
        _money(reserve_fraction, "reserve fraction")
        _money(minimum_transfer_quote, "minimum transfer")
        if reserve_fraction != Decimal("0.5"):
            raise ValueError("the agreed reserve fraction is exactly 50%")
        if minimum_transfer_quote == ZERO:
            raise ValueError("minimum_transfer_quote must be positive")
        self._reserve_fraction = reserve_fraction
        self._minimum_transfer_quote = minimum_transfer_quote

    @staticmethod
    def _validate_state(state: ProfitVaultState) -> None:
        _money(state.active_high_water_mark, "high water mark")
        _money(state.pending_reserve, "pending reserve")
        _money(state.secured_reserve, "secured reserve")
        if state.active_high_water_mark == ZERO:
            raise ValueError("high water mark must be positive")

    def allocate(
        self,
        state: ProfitVaultState,
        settled_account_equity: Decimal,
        *,
        positions_flat: bool,
        orders_reconciled: bool,
    ) -> ProfitAllocation:
        self._validate_state(state)
        _money(settled_account_equity, "settled account equity")
        if positions_flat is not True or orders_reconciled is not True:
            raise ValueError("allocation requires settled cash and no outstanding orders")
        active_equity = settled_account_equity - state.pending_reserve
        if active_equity < ZERO:
            raise ValueError("account equity cannot cover the protected pending reserve")
        new_profit = max(ZERO, active_equity - state.active_high_water_mark)
        reserve = new_profit * self._reserve_fraction
        compound = new_profit - reserve
        active_after = active_equity - reserve

        state.pending_reserve += reserve
        if new_profit > 0:
            state.active_high_water_mark += compound

        transfer_due = ZERO
        if state.pending_reserve >= self._minimum_transfer_quote:
            transfer_due = state.pending_reserve

        return ProfitAllocation(
            new_profit=new_profit,
            compound_amount=compound,
            reserve_amount=reserve,
            transfer_due=transfer_due,
            active_capital_after_allocation=active_after,
            new_active_high_water_mark=state.active_high_water_mark,
        )

    @classmethod
    def confirm_transfer(cls, state: ProfitVaultState, amount: Decimal, transfer_id: str) -> None:
        """Record an externally confirmed transfer once, keyed by exchange ID.

        Next allocation must use a fresh post-transfer cash balance. This only
        records a simulated confirmation; it does not move any money.
        """
        cls._validate_state(state)
        _money(amount, "transfer amount")
        if not transfer_id.strip() or amount == ZERO:
            raise ValueError("a transfer ID and positive amount are required")
        if transfer_id in state.confirmed_transfers:
            if state.confirmed_transfers[transfer_id] != amount:
                raise ValueError("transfer ID reused with a different amount")
            return
        if amount > state.pending_reserve:
            raise ValueError("transfer amount is not pending")
        state.pending_reserve -= amount
        state.secured_reserve += amount
        state.confirmed_transfers[transfer_id] = amount
