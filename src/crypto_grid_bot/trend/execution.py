"""Frozen V3 execution checkpoints; the scheduler supplies unmasked prices/rules."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.account import AccountMark, Fill, FuturesAccount
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orders import OrderPlan, plan_rebalance, plan_reduction


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


@dataclass(frozen=True, slots=True)
class HourResult:
    marks: tuple[tuple[str, AccountMark], ...]
    plans: tuple[tuple[str, OrderPlan], ...]
    checkpoints: tuple[LeverageCheckpoint, ...]
    reason: str | None


def execute_hour(
    account: FuturesAccount,
    hour_ms: int,
    prices: Mapping[str, Decimal],
    extremes: Mapping[str, tuple[Decimal, Decimal]],
    tradable: Mapping[str, OrderFilters],
    targets: Mapping[str, Decimal],
    funding: Mapping[int, Mapping[str, Decimal]],
    *,
    multiple: int,
) -> HourResult:
    """Execute already-scheduled targets and complete funding groups for one hour.

    The caller supplies carried opens for masked coins and only unmasked coins in
    tradable/extremes. Deferred decisions and lifecycle attribution belong to the
    scheduler. A terminal result must stop it. Marks retain every risk checkpoint.
    """
    if type(hour_ms) is not int or hour_ms % 3600000:
        raise ValueError("hour must be aligned")
    if type(multiple) is not int or multiple not in (1, 2, 3):
        raise ValueError("multiple must be 1, 2 or 3")
    if not set(targets) <= set(tradable) or set(extremes) != set(tradable):
        raise ValueError("targets and extremes must match tradable coins")
    for symbol in tradable:
        low, high = extremes[symbol]
        if (
            symbol not in prices
            or not (low.is_finite() and high.is_finite())
            or not (0 < low <= prices[symbol] <= high)
        ):
            raise ValueError("invalid hourly prices")
    for stamp, rates in funding.items():
        if type(stamp) is not int or not hour_ms <= stamp < hour_ms + 3600000 or not rates:
            raise ValueError("invalid hourly funding group")
        for symbol, rate in rates.items():
            symbol_name(symbol)
            if (
                not isinstance(rate, Decimal)
                or not rate.is_finite()
                or rate.copy_abs() > Decimal("1e36")
            ):
                raise ValueError("invalid funding rate")
    marks = []
    checkpoints = []
    plans: list[tuple[str, OrderPlan]] = []
    opened = account.check_liquidation(prices, hour_ms)
    marks.append(("open", opened))
    if account.liquidation is not None:
        return HourResult(tuple(marks), (), (), "liquidation")
    for symbol in sorted(targets):
        held = account.positions.get(symbol)
        plans.append(
            (
                symbol,
                plan_rebalance(
                    targets[symbol],
                    held.quantity if held else Decimal(0),
                    opened.equity,
                    prices[symbol],
                    tradable[symbol],
                ),
            )
        )
    for reducing in (True, False):
        for symbol, plan in plans:
            for intent in plan.orders:
                if intent.reduce_only == reducing:
                    account.fill(symbol, intent, prices[symbol], hour_ms)

    def checkpoint(label: str, stamp: int) -> str | None:
        check = leverage_checkpoint(account, prices, tradable, stamp, multiple=multiple)
        checkpoints.append(check)
        marks.append((label, check.before))
        if check.fills:
            marks.append((label + "_delevered", check.after))
        return check.reason

    reason = checkpoint("post_fill", hour_ms)
    if reason is None:
        for stamp in sorted(funding):
            account.fund(stamp, funding[stamp], prices)
            reason = checkpoint("funding", stamp)
            if reason is not None:
                break
    if reason is None:
        adverse = dict(prices)
        for symbol, position in account.positions.items():
            if position.quantity != 0 and symbol in extremes:
                low, high = extremes[symbol]
                adverse[symbol] = low if position.quantity > 0 else high
        mark = account.check_liquidation(adverse, hour_ms + 3599999)
        marks.append(("adverse", mark))
        if account.liquidation is not None:
            reason = "liquidation"
    return HourResult(tuple(marks), tuple(plans), tuple(checkpoints), reason)
