"""Variant B of experiment spec v1 (§3 B): a cap on new buy commitments.

Off unless ``SimulationPolicy.inventory_cap`` is set. The cap only ever shrinks or skips
a buy when it is created: it never sells, never delays a sell and never spends a reserve.
It bounds new commitments under the stated valuation; price moves after a fill can still
lift the measured ratio above the cap, and then no new buy fits until it falls back.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_grid_bot.simulation.models import (
    ONE,
    ZERO,
    Account,
    MarketRules,
    Quote,
    floor_step,
)


def mark(quote: Quote, rules: MarketRules) -> Decimal:
    """Exit value of one unit: bid less slippage and the taker fee."""
    return quote.bid * (ONE - rules.slippage_rate) * (ONE - rules.taker_fee)


def _haircut(rules: MarketRules) -> Decimal:
    """Per unit of limit notional: cost with the maker fee less its exit value."""
    return (ONE + rules.fee_rate) - (ONE - rules.slippage_rate) * (ONE - rules.taker_fee)


def _resting_buy_notional(account: Account) -> Decimal:
    # Remaining quantity: a partial fill has moved the filled part into inventory.
    return sum(
        (order.price * order.remaining for order in account.orders.values() if order.side == "buy"),
        ZERO,
    )


def committed_exposure(
    account: Account, quote: Quote, rules: MarketRules, proposed: Decimal = ZERO
) -> Decimal:
    """Inventory at the mark plus every resting buy and the proposed buy notional,
    both at their cost including the maker fee."""
    buys = _resting_buy_notional(account) + proposed
    return account.inventory * mark(quote, rules) + buys * (ONE + rules.fee_rate)


def prospective_active_equity(
    account: Account, quote: Quote, rules: MarketRules, proposed: Decimal = ZERO
) -> Decimal:
    """Active equity if every resting buy and the proposed buy filled at its limit and
    was marked at that limit with the exit haircut."""
    buys = _resting_buy_notional(account) + proposed
    return account.equity(quote, rules) - buys * _haircut(rules)


def fits(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    cap: Decimal,
    proposed: Decimal = ZERO,
) -> bool:
    return committed_exposure(account, quote, rules, proposed) <= cap * prospective_active_equity(
        account, quote, rules, proposed
    )


def capped_quantity(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    cap: Decimal,
    price: Decimal,
    quantity: Decimal,
) -> Decimal:
    """The largest lot-floored quantity, at most ``quantity``, of a buy at ``price``
    that keeps committed exposure within ``cap`` of prospective active equity.

    ZERO means the buy is skipped: nothing fits, or what fits is below the minimum
    notional after flooring.
    """
    if fits(account, quote, rules, cap, price * quantity):
        return quantity
    # committed(x) <= cap * prospective(x) is linear in the proposed notional p*x:
    # p*x * ((1 + maker) + cap * haircut) <= cap * prospective(0) - committed(0).
    room = cap * prospective_active_equity(account, quote, rules) - committed_exposure(
        account, quote, rules
    )
    per_unit = price * ((ONE + rules.fee_rate) + cap * _haircut(rules))
    result = floor_step(max(ZERO, room) / per_unit, rules.quantity_step)
    # Guard the division's rounding with the defining inequality.
    while result > ZERO and not fits(account, quote, rules, cap, price * result):
        result -= rules.quantity_step
    if result * price < rules.minimum_notional:
        return ZERO
    return result
