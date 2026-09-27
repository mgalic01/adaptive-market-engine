"""Conservative limit fills with shared volume budgets and quote-denominated fees.

Resting limit fills pay the maker fee; marketable exits pay the taker fee.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

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
)


def place(account: Account, order: LimitOrder, rules: MarketRules) -> None:
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
    if order.target is not None:
        nonnegative(order.target)
        if order.side != "buy" or order.target <= order.price or order.target % rules.tick_size:
            raise ValueError("invalid grid sell target")
    if order.reentry is not None:
        nonnegative(order.reentry)
        if (
            order.side != "sell"
            or not ZERO < order.reentry < order.price
            or order.reentry % rules.tick_size
        ):
            raise ValueError("invalid grid reentry level")
    if order.side == "buy":
        required = order.price * order.quantity * (ONE + rules.fee_rate)
        if required > account.available_quote(rules):
            raise ValueError("insufficient unprotected quote balance including fees")
    elif order.quantity > account.inventory - account.reserved_base():
        raise ValueError("insufficient unreserved inventory")
    account.orders[order.order_id] = order


def cancel(account: Account, order_id: str) -> None:
    if order_id not in account.orders:
        raise ValueError("unknown order")
    del account.orders[order_id]


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
    return Fill(order.order_id, order.side, price, quantity, fee)


def match(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    *,
    recycle: bool = True,
    epoch: str | None = None,
    reentry_quantity: Callable[[str, Decimal, Decimal], Decimal] | None = None,
) -> list[Fill]:
    """Orders present before this quote only; child orders wait for a later event.

    Price/time priority approximates an exchange queue. Crossing quotes are
    required; touching limits and candle extrema are not enough. Executions are
    charged at the limit (no optimistic price improvement). Slippage must fit
    inside that limit, and per-side liquidity is shared across all orders.

    ``epoch`` groups several quotes that replay one historical bar. Orders created
    under an epoch cannot fill until a later epoch, so a buy and its child sell never
    both fill on an invented favourable path inside a single bar.

    ``reentry_quantity`` (order ID, price, quantity) may shrink a reentry buy when it
    is created; ZERO skips it. Unset, every reentry keeps the sold quantity.
    """
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
    for order in orders:
        if epoch is not None and order.epoch == epoch:
            continue
        crossed = (
            quote.ask * (ONE + rules.slippage_rate) < order.price
            if order.side == "buy"
            else quote.bid * (ONE - rules.slippage_rate) > order.price
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
                if (
                    cost <= account.available_quote(rules)
                    and reentry.price * reentry.quantity >= rules.minimum_notional
                ):
                    place(account, reentry, rules)
    account.validate(rules)
    return fills


def exit_price(quote: Quote, rules: MarketRules) -> Decimal:
    """The price a marketable exit would get at this bid, after slippage and rounding."""
    return floor_step(quote.bid * (ONE - rules.slippage_rate), rules.tick_size)


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
    * ``dust`` - the whole unreserved position is below the minimum notional at this
      bid. No later frame and no extra depth can clear it; only a higher price can.
    * ``reserved`` - every unit of inventory is already reserved by a resting sell, so
      there is nothing for this exit to do. Not a minimum-notional refusal.
    """

    fills: list[Fill] = field(default_factory=list)
    blocked: str = ""
    # The chunk this frame could have sold, and its value at the exit price.
    quantity: Decimal = ZERO
    notional: Decimal = ZERO
    # Inventory not reserved by a resting sell, and its value at the exit price.
    unreserved: Decimal = ZERO
    unreserved_notional: Decimal = ZERO


def reduce_unreserved(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    *,
    consumed: Decimal = ZERO,
    maximum: Decimal | None = None,
) -> Reduction:
    """Exit residual inventory without spending liquidity used by existing sells.

    The exit crosses the bid, so it pays the taker fee. An exchange rejects an order
    below the minimum notional, so such an exit is refused rather than forced; the
    refusal is returned (see ``Reduction``) and never swallowed.
    """
    quote.validate(rules)
    account.validate(rules)
    nonnegative(consumed)
    price = floor_step(quote.bid * (ONE - rules.slippage_rate), rules.tick_size)
    unreserved = account.inventory - account.reserved_base()
    # ``maximum`` limits the exit to one part of the unreserved inventory, such as a
    # residue, when the rest belongs to a buy still resting on the book.
    target = unreserved if maximum is None else min(unreserved, maximum)
    sellable = floor_step(target, rules.quantity_step)
    capacity = max(ZERO, quote.bid_size * rules.participation - consumed)
    quantity = floor_step(min(target, capacity), rules.quantity_step)

    def outcome(blocked: str, fills: list[Fill] | None = None) -> Reduction:
        return Reduction(
            fills or [], blocked, quantity, price * quantity, unreserved, price * unreserved
        )

    if target <= ZERO:
        return outcome("reserved" if account.inventory > ZERO else "")
    if quantity == ZERO or price * quantity < rules.minimum_notional:
        # Distinguish a position no exchange will ever let us sell at this price from
        # one that is merely too large for this frame's share of the displayed bid.
        return outcome("dust" if price * sellable < rules.minimum_notional else "depth")
    order = LimitOrder("exit/" + quote.event_id, "sell", price, quantity, quantity)
    fill = _apply_fill(account, order, quantity, price, rules.taker_fee)
    account.validate(rules)
    return outcome("", [fill])


def liquidate(account: Account, quote: Quote, rules: MarketRules) -> Reduction:
    """Bounded simulated emergency sell, after existing orders are cancelled."""
    if account.orders:
        raise ValueError("cancel resting orders before liquidation")
    return reduce_unreserved(account, quote, rules)


def exit_state(account: Account, quote: Quote, rules: MarketRules) -> tuple[str, Decimal]:
    """Where the account's exits stand at this quote, from the account itself.

    Judged on ``unpaired_inventory``, the same quantity the runner drains, and never on
    a flag: a healthy account with resting buys still owes an exit for an old residue,
    and the filled part of a resting buy must not make that residue look sellable.

    * ``("incomplete", value)``: unpaired inventory the market would still accept is
      unsold, so the run never showed it could exit.
    * ``("dust", value)``: what is left is below an exchange filter at this bid; only a
      higher price clears it. Reported, not a failure.
    * ``("", 0)``: nothing is owed.

    ``value`` is the unpaired inventory at the exit price.
    """
    unpaired = unpaired_inventory(account)
    if unpaired <= ZERO:
        return "", ZERO
    value = exit_price(quote, rules) * unpaired
    if marketable(unpaired, quote, rules) == ZERO:
        return "dust", value
    return "incomplete", value
