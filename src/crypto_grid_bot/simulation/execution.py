"""Conservative limit fills with shared volume budgets and quote-denominated fees.

Resting limit fills pay the maker fee; marketable exits pay the taker fee.
"""

from __future__ import annotations

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
) -> list[Fill]:
    """Orders present before this quote only; child orders wait for a later event.

    Price/time priority approximates an exchange queue. Crossing quotes are
    required; touching limits and candle extrema are not enough. Executions are
    charged at the limit (no optimistic price improvement). Slippage must fit
    inside that limit, and per-side liquidity is shared across all orders.

    ``epoch`` groups several quotes that replay one historical bar. Orders created
    under an epoch cannot fill until a later epoch, so a buy and its child sell never
    both fill on an invented favourable path inside a single bar.
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
                reentry = LimitOrder(
                    f"{quote.event_id}/reentry/{account.fill_count}",
                    "buy",
                    order.reentry,
                    order.quantity,
                    order.quantity,
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


def reduce_unreserved(
    account: Account,
    quote: Quote,
    rules: MarketRules,
    *,
    consumed: Decimal = ZERO,
) -> list[Fill]:
    """Exit residual inventory without spending liquidity used by existing sells.

    The exit crosses the bid, so it pays the taker fee.
    """
    quote.validate(rules)
    account.validate(rules)
    nonnegative(consumed)
    capacity = max(ZERO, quote.bid_size * rules.participation - consumed)
    quantity = floor_step(
        min(account.inventory - account.reserved_base(), capacity), rules.quantity_step
    )
    price = floor_step(quote.bid * (ONE - rules.slippage_rate), rules.tick_size)
    if quantity == ZERO or price * quantity < rules.minimum_notional:
        return []
    order = LimitOrder("exit/" + quote.event_id, "sell", price, quantity, quantity)
    fill = _apply_fill(account, order, quantity, price, rules.taker_fee)
    account.validate(rules)
    return [fill]


def liquidate(account: Account, quote: Quote, rules: MarketRules) -> list[Fill]:
    """Bounded simulated emergency sell, after existing orders are cancelled."""
    if account.orders:
        raise ValueError("cancel resting orders before liquidation")
    return reduce_unreserved(account, quote, rules)
