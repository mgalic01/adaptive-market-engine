"""Conservative limit fills with shared volume budgets and quote-denominated fees.

Resting limit fills pay the maker fee; marketable exits, and the uptrend's marketable
buy (``market_buy``), pay the taker fee.

Each entry point validates the quote and the whole account first by default. The paper
engine passes ``check=False``: it validates the frame's quote first thing in its step
and the whole account at every frame boundary (``PaperSimulator.step``, and
``StateStore.transact`` before saving and on every read), so the per-call checks would
only repeat work on a state validated moments before. ``place``'s checks of the new
order itself always run. ``market_buy`` takes no ``check``: its caller validates the
quote and the account, as the paper engine does every frame.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, Decimal, localcontext
from typing import Any

from crypto_grid_bot.simulation.models import (
    ONE,
    ZERO,
    Account,
    Fill,
    LimitOrder,
    MarketRules,
    Quote,
    floor_step,
    nonnegative,
    validate_grid_links,
)

# The simulator settles fills at precision 50 (``PaperSimulator.step``), and the trend
# benchmark prices and sizes its buys at the same precision. The market buy below runs at
# this one precision whatever the ambient context is, so a quantity sized at one precision
# is never settled at another.
_PRECISION = 50


def place(account: Account, order: LimitOrder, rules: MarketRules, *, check: bool = True) -> None:
    if check:
        account.validate(rules)
    if order.order_id in account.orders or not order.order_id:
        raise ValueError("order ID must be unique")
    if order.side not in ("buy", "sell"):
        raise ValueError("unknown order side")
    for value in (order.price, order.quantity):
        nonnegative(value)
        if value == ZERO:
            raise ValueError("order price and quantity must be positive")
    if order.quantity != order.remaining:
        raise ValueError("new order must not already be filled")
    if order.price % rules.tick_size or order.quantity % rules.quantity_step:
        raise ValueError("price or quantity violates market precision")
    if order.price * order.quantity < rules.minimum_notional:
        raise ValueError("order is below minimum notional")
    validate_grid_links(order, rules, "grid")
    if order.side == "buy":
        required = order.price * order.quantity * (ONE + rules.fee_rate)
        if required > account.available_quote(rules):
            raise ValueError("insufficient unprotected quote balance including fees")
    elif order.quantity > account.inventory - account.reserved_base():
        raise ValueError("insufficient unreserved inventory")
    account.orders[order.order_id] = order


def _apply_fill(
    account: Account, order: LimitOrder, quantity: Decimal, price: Decimal, fee_rate: Decimal
) -> Fill:
    notional = price * quantity
    fee = notional * fee_rate
    if order.side == "buy":
        account.cash -= notional + fee
        account.inventory += quantity
    else:
        account.cash += notional - fee
        account.inventory -= quantity
    account.fees += fee
    account.fill_count += 1
    order.remaining -= quantity
    return Fill(order.order_id, order.side, price, quantity, fee, order.remaining)


def match(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    *,
    recycle: bool = True,
    epoch: str | None = None,
    reentry_quantity: Callable[[str, Decimal, Decimal], Decimal] | None = None,
    refused: list[dict[str, Any]] | None = None,
    check: bool = True,
) -> list[Fill]:
    """Orders present before this quote only; child orders wait for a later event.

    Price/time priority approximates an exchange queue. Crossing quotes are
    required; touching limits and candle extrema are not enough. Executions are
    charged at the limit (no optimistic price improvement). The quote must cross the
    limit by the fill trigger, which is the slippage unless a labelled sensitivity run
    sets ``MarketRules.fill_trigger_rate`` (D9), and per-side liquidity is shared
    across all orders.

    ``epoch`` groups several quotes that replay one historical bar. Orders created
    under an epoch cannot fill until a later epoch, so a buy and its child sell never
    both fill on an invented favourable path inside a single bar.

    ``reentry_quantity`` (order ID, price, quantity) may shrink a reentry buy when it
    is created; ZERO skips it. Unset, every reentry keeps the sold quantity.

    ``refused`` receives a record of each reentry buy that the affordability or the
    minimum-notional check declines, so a level that leaves the grid stays visible.
    """
    if check:
        quote.validate(rules)
        account.validate(rules)
    capacities = {
        "buy": floor_step(quote.ask_size * rules.participation, rules.quantity_step),
        "sell": floor_step(quote.bid_size * rules.participation, rules.quantity_step),
    }
    orders = sorted(
        account.orders.values(), key=lambda o: (o.side, -o.price if o.side == "buy" else o.price)
    )
    fills: list[Fill] = []
    # The resting-fill test is the only use of the fill trigger; exits and marks keep
    # the slippage as their cash cost.
    trigger = rules.fill_trigger
    for order in orders:
        if epoch is not None and order.epoch == epoch:
            continue
        crossed = (
            quote.ask * (ONE + trigger) < order.price
            if order.side == "buy"
            else quote.bid * (ONE - trigger) > order.price
        )
        quantity = min(order.remaining, capacities[order.side])
        if not crossed or quantity <= ZERO:
            continue
        fills.append(_apply_fill(account, order, quantity, order.price, rules.fee_rate))
        capacities[order.side] -= quantity
        if order.remaining == ZERO:
            del account.orders[order.order_id]
            if order.side == "buy" and order.target is not None:
                place(
                    account,
                    LimitOrder(
                        order.order_id + "/sell",
                        "sell",
                        order.target,
                        order.quantity,
                        order.quantity,
                        reentry=order.price,
                        epoch=epoch,
                    ),
                    rules,
                    check=check,
                )
            elif order.side == "sell" and order.reentry is not None and recycle:
                reentry_id = f"{quote.event_id}/reentry/{account.fill_count}"
                quantity = order.quantity
                if reentry_quantity is not None:
                    quantity = reentry_quantity(reentry_id, order.reentry, quantity)
                if quantity == ZERO:
                    continue
                reentry = LimitOrder(
                    reentry_id,
                    "buy",
                    order.reentry,
                    quantity,
                    quantity,
                    target=order.price,
                    epoch=epoch,
                )
                cost = reentry.price * reentry.quantity * (ONE + rules.fee_rate)
                if cost > account.available_quote(rules):
                    reason = "insufficient unprotected quote balance including fees"
                elif reentry.price * reentry.quantity < rules.minimum_notional:
                    reason = "order is below minimum notional"
                else:
                    place(account, reentry, rules, check=check)
                    continue
                if refused is not None:
                    refused.append(
                        {
                            "order_id": reentry_id,
                            "price": reentry.price,
                            "quantity": reentry.quantity,
                            "reason": reason,
                        }
                    )
    if check:
        account.validate(rules)
    return fills


def exit_price(quote: Quote, rules: MarketRules) -> Decimal:
    """The price a marketable exit would get at this bid, after slippage and rounding."""
    return floor_step(quote.bid * (ONE - rules.slippage_rate), rules.tick_size)


def buy_price(quote: Quote, rules: MarketRules) -> Decimal:
    """The price a marketable buy would pay at this ask: ``ask * (1 + slippage)``, rounded
    up to the tick, against the buyer, as ``exit_price`` rounds a sell down.

    The same rule as ``trend_benchmark.buy_price`` (variant D), at the same precision.
    """
    with localcontext() as context:
        context.prec = _PRECISION
        ticks = (quote.ask * (ONE + rules.slippage_rate) / rules.tick_size).to_integral_value(
            rounding=ROUND_CEILING
        )
        return ticks * rules.tick_size


def marketable(quantity: Decimal, quote: Quote, rules: MarketRules) -> Decimal:
    """``quantity`` if the market filters would accept selling it at this bid, else ZERO.

    Deliberately liquidity-independent: it answers "can this ever be sold at this
    price", not "does this frame have the depth for it". ZERO therefore means a residue
    below the quantity step or the minimum notional -- an exchange filter no later frame
    at this price can satisfy -- and never merely a thin book.
    """
    step = floor_step(quantity, rules.quantity_step)
    if step <= ZERO or exit_price(quote, rules) * step < rules.minimum_notional:
        return ZERO
    return step


def unpaired_inventory(account: Account) -> Decimal:
    """Inventory with no sell to clear it: not reserved by a resting sell, and not the
    part of a resting buy that has already filled, whose own child sell will pair it
    when the buy completes. This is exactly what a drain has to exit, so the runner's
    drain trigger and the end-of-run classifier must both use it.
    """
    held_by_buys = sum(
        (o.quantity - o.remaining for o in account.orders.values() if o.side == "buy"), ZERO
    )
    return account.inventory - account.reserved_base() - held_by_buys


def exitable(account: Account, quote: Quote, rules: MarketRules) -> Decimal:
    """Unreserved inventory the market filters would allow an exit to sell at this bid."""
    return marketable(account.inventory - account.reserved_base(), quote, rules)


@dataclass(frozen=True)
class Reduction:
    """One marketable-exit attempt: what filled, and if nothing did, exactly why.

    ``blocked`` is the refusal an exchange would have produced, or "" when the attempt
    was not refused (it either traded, or there was nothing unreserved to sell):

    * ``depth`` - the per-frame participation chunk is below the minimum notional
      although the unreserved position is not. Waiting for a deeper bid is the only
      lawful course; the wait may never end, so it is reported on every frame.
    * ``dust`` - the whole outstanding position is below the minimum notional at this
      bid. No later frame and no extra depth can clear it; only a higher price can.
    * ``reserved`` - every unit of inventory is already reserved by a resting sell, so
      there is nothing for this exit to do. Not a minimum-notional refusal.
    """

    fills: list[Fill] = field(default_factory=list)
    blocked: str = ""
    # The chunk this frame could have sold, and its value at the exit price.
    quantity: Decimal = ZERO
    notional: Decimal = ZERO
    # What this attempt was asked to clear, and its value at the exit price: the
    # unreserved inventory, or the ``maximum`` bound when the caller drains only part of
    # it. Never the whole unreserved balance when a bound was given -- the excluded part
    # belongs to a resting buy and is not stuck, so reporting it would overstate how
    # much value an exit cannot shift.
    outstanding: Decimal = ZERO
    outstanding_notional: Decimal = ZERO


def reduce_unreserved(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    *,
    consumed: Decimal = ZERO,
    maximum: Decimal | None = None,
    check: bool = True,
) -> Reduction:
    """Exit residual inventory without spending liquidity used by existing sells.

    The exit crosses the bid, so it pays the taker fee. An exchange rejects an order
    below the minimum notional, so such an exit is refused rather than forced; the
    refusal is returned (see ``Reduction``) and never swallowed.
    """
    if check:
        quote.validate(rules)
        account.validate(rules)
    nonnegative(consumed)
    if maximum is not None and maximum <= ZERO:
        # A bound of zero or less would report a negative or empty target as "owed".
        raise ValueError("maximum must be positive when given")
    price = exit_price(quote, rules)
    unreserved = account.inventory - account.reserved_base()
    # ``maximum`` limits the exit to one part of the unreserved inventory, such as a
    # residue, when the rest belongs to a buy still resting on the book.
    target = unreserved if maximum is None else min(unreserved, maximum)
    sellable = floor_step(target, rules.quantity_step)
    capacity = max(ZERO, quote.bid_size * rules.participation - consumed)
    quantity = floor_step(min(target, capacity), rules.quantity_step)

    def outcome(blocked: str, fills: list[Fill] | None = None) -> Reduction:
        # ``target``, not ``unreserved``: what a bounded drain leaves behind is what it
        # was asked to clear, never the resting buy's filled inventory it deliberately
        # excluded.
        return Reduction(fills or [], blocked, quantity, price * quantity, target, price * target)

    if target <= ZERO:
        return outcome("reserved" if account.inventory > ZERO else "")
    if quantity == ZERO or price * quantity < rules.minimum_notional:
        # Distinguish a position no exchange will ever let us sell at this price from
        # one that is merely too large for this frame's share of the displayed bid.
        return outcome("dust" if price * sellable < rules.minimum_notional else "depth")
    order = LimitOrder("exit/" + quote.event_id, "sell", price, quantity, quantity)
    fill = _apply_fill(account, order, quantity, price, rules.taker_fee)
    if check:
        account.validate(rules)
    return outcome("", [fill])


def liquidate(
    account: Account, quote: Quote, rules: MarketRules, *, check: bool = True
) -> Reduction:
    """Bounded simulated emergency sell, after existing orders are cancelled."""
    if account.orders:
        raise ValueError("cancel resting orders before liquidation")
    return reduce_unreserved(account, quote, rules, check=check)


@dataclass(frozen=True)
class BuyResult:
    """One marketable-buy attempt: the fill, or if nothing filled, exactly why.

    ``refusal`` is "" when the buy filled, and otherwise one of two reasons the caller
    reads differently (spec v2 section 5):

    * ``budget`` - what is left of the cash cap, the risk allowance or the account's own
      spendable cash buys less than the minimum notional at this price. No later quote
      at this price can change that, so the entry ends.
    * ``depth`` - only the participation limit on this quote's ask size keeps the buy
      below the minimum notional. A deeper ask may allow it, so the entry waits for the
      next quote.
    """

    fill: Fill | None
    refusal: str


def market_buy(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    *,
    cash_left: Decimal,
    risk_left: Decimal,
    stop: Decimal,
) -> BuyResult:
    """Buy at the ask, marketable, at the taker fee, bounded by three limits (spec v2 section 5).

    ``cash_left`` is what remains of the entry's cash cap and ``risk_left`` of its risk
    allowance, the loss at ``stop`` before fees. The quantity is the least of:

    * depth: the participation limit on the ask size;
    * cash: ``min(cash_left, account.available_quote)`` at the all-in unit cost
      ``price * (1 + taker fee)``. The account's own spendable cash bounds it as well,
      since dust or held fragments can leave less than the cap, and a buy never drives
      ``account.cash`` below zero;
    * risk: ``risk_left`` at the loss per unit ``price - stop``.

    Each quotient is floored to the lot step and then lowered one step at a time while it
    still overshoots its limit, a quotient having been rounded up at the last digit
    (``trend_benchmark.entry_quantity``'s guard). So no fill uses more than what is left
    of either limit. A limit that is negative, by a last digit, bounds the quantity at
    zero or below, which is refused as ``budget``.

    The caller validates the quote and the account, as the paper engine does at every
    frame; and calls this only with a buy price above ``stop``, which a stop-out check on
    the same quote's bid guarantees. A price at or below it leaves the risk bound no loss
    per unit to divide by, so it raises rather than sizing a buy without one.
    """
    with localcontext() as context:
        context.prec = _PRECISION
        price = buy_price(quote, rules)
        loss = price - stop
        if loss <= ZERO:
            raise ValueError("a buy must be priced above its stop")
        step = rules.quantity_step
        depth = floor_step(quote.ask_size * rules.participation, step)
        spendable = min(cash_left, account.available_quote(rules))
        unit_cost = price * (ONE + rules.taker_fee)
        by_cash = floor_step(spendable / unit_cost, step)
        while by_cash > ZERO and by_cash * unit_cost > spendable:
            by_cash -= step
        by_risk = floor_step(risk_left / loss, step)
        while by_risk > ZERO and by_risk * loss > risk_left:
            by_risk -= step
        affordable = min(by_cash, by_risk)
        if price * affordable < rules.minimum_notional:
            return BuyResult(None, "budget")
        quantity = min(depth, affordable)
        if price * quantity < rules.minimum_notional:
            return BuyResult(None, "depth")
        order = LimitOrder("uptrend/buy/" + quote.event_id, "buy", price, quantity, quantity)
        return BuyResult(_apply_fill(account, order, quantity, price, rules.taker_fee), "")


def exit_state(
    account: Account, quote: Quote, rules: MarketRules, held: Decimal = ZERO
) -> tuple[str, Decimal]:
    """Where the account's exits stand at this quote, from the account itself.

    Judged on ``unpaired_inventory``, the same quantity the runner drains, and never on
    a flag: a healthy account with resting buys still owes an exit for an old residue,
    and the filled part of a resting buy must not make that residue look sellable.

    * ``("incomplete", value)``: unpaired inventory the market would still accept is
      unsold, so the run never showed it could exit.
    * ``("dust", value)``: what is left is below an exchange filter at this bid; only a
      higher price clears it. Reported, not a failure.
    * ``("", 0)``: nothing is owed.

    ``value`` is the unpaired inventory at the exit price. ``held`` is the part no exit
    owes yet, variant F's fragments waiting for their own sell: it is reported with the
    rest, as dust, and never makes the exit incomplete.
    """
    unpaired = unpaired_inventory(account)
    if unpaired <= ZERO:
        return "", ZERO
    value = exit_price(quote, rules) * unpaired
    if marketable(unpaired - held, quote, rules) == ZERO:
        return "dust", value
    return "incomplete", value
