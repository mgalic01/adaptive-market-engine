"""Frozen V3 execution checkpoints; the scheduler supplies unmasked prices/rules."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.account import AccountMark, Fill, FuturesAccount
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orders import plan_reduction


@dataclass(frozen=True, slots=True)
class LeverageCheckpoint:
    before: AccountMark
    after: AccountMark
    fills: tuple[Fill, ...]
    adjustments: tuple[tuple[str, tuple[str, ...]], ...]
    reason: str | None


def leverage_checkpoint(
    account: FuturesAccount,
    prices: Mapping[str, Decimal],
    tradable: Mapping[str, OrderFilters],
    timestamp_ms: int,
    *,
    multiple: int,
) -> LeverageCheckpoint:
    """Liquidation first, at most one delevering batch, then a post-cost check.

    `tradable` contains only coins with an unmasked bar at this hour. Prices must
    include the carried marks of masked held positions. A non-None reason is a
    terminal invalid-run outcome; the future scheduler must stop immediately.
    """
    if type(multiple) is not int or multiple not in (1, 2, 3):
        raise ValueError("multiple must be 1, 2 or 3")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        before = account.check_liquidation(prices, timestamp_ms)
        if account.liquidation is not None:
            return LeverageCheckpoint(before, before, (), (), "liquidation")
        if before.gross_notional == 0:
            return LeverageCheckpoint(before, before, (), (), None)
        assert before.gross_leverage is not None
        if before.gross_leverage <= multiple:
            return LeverageCheckpoint(before, before, (), (), None)
        positions = account.positions
        tradable_gross = sum(
            (
                abs(p.quantity) * prices[s]
                for s, p in sorted(positions.items())
                if p.quantity != 0 and s in tradable
            ),
            Decimal(0),
        )
        if tradable_gross == 0:
            return LeverageCheckpoint(before, before, (), (), "no_tradable_position")
        masked_gross = sum(
            (
                abs(p.quantity) * prices[s]
                for s, p in sorted(positions.items())
                if p.quantity != 0 and s not in tradable
            ),
            Decimal(0),
        )
        factor = (Decimal(".80") * multiple * before.equity - masked_gross) / tradable_gross
        factor = max(Decimal(0), factor)
        # Plan every reduction before mutating any position: invalid filters or
        # an impossible prescribed split must not leave a partially filled batch.
        plans = [
            (
                symbol,
                plan_reduction(position.quantity, position.quantity * factor, tradable[symbol]),
            )
            for symbol, position in sorted(positions.items())
            if position.quantity != 0 and symbol in tradable
        ]
        fills = []
        adjustments = []
        for symbol, (orders, changes) in plans:
            adjustments.append((symbol, changes))
            for order in orders:
                fills.append(account.fill(symbol, order, prices[symbol], timestamp_ms))
        after = account.check_liquidation(prices, timestamp_ms)
        reason = None
        if account.liquidation is not None:
            reason = "liquidation"
        elif after.gross_notional and (
            after.gross_leverage is None or after.gross_leverage > multiple
        ):
            reason = "leverage_not_restored"
        return LeverageCheckpoint(before, after, tuple(fills), tuple(adjustments), reason)
