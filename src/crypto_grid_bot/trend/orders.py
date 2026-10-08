"""Frozen V3 market-order planning; no exchange calls or account mutations."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_HALF_EVEN, Context, Decimal, localcontext

from crypto_grid_bot.trend.filters import OrderFilters

ZERO = Decimal(0)


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


@dataclass(frozen=True, slots=True)
class OrderIntent:
    quantity: Decimal
    reduce_only: bool


@dataclass(frozen=True, slots=True)
class OrderPlan:
    current_weight: Decimal
    target_quantity: Decimal
    orders: tuple[OrderIntent, ...]
    refusals: tuple[str, ...]
    adjustments: tuple[str, ...]


def _split(quantity: Decimal, reduce_only: bool, filters: OrderFilters) -> tuple[OrderIntent, ...]:
    magnitude = abs(quantity)
    if magnitude <= filters.max_quantity:
        return (OrderIntent(quantity, reduce_only),)
    count = int((magnitude / filters.max_quantity).to_integral_value(rounding=ROUND_CEILING))
    base = (magnitude / count / filters.step_size).to_integral_value(rounding=ROUND_DOWN)
    steps = magnitude / filters.step_size
    leftover = int(steps - base * count)
    sizes = tuple((base + (1 if i < leftover else 0)) * filters.step_size for i in range(count))
    if any(size < filters.min_quantity or size > filters.max_quantity for size in sizes):
        raise ValueError("no valid prescribed market-order split")
    return tuple(OrderIntent(size * _sign(quantity), reduce_only) for size in sizes)


def plan_rebalance(
    target_weight: Decimal,
    held_quantity: Decimal,
    equity: Decimal,
    open_price: Decimal,
    filters: OrderFilters,
) -> OrderPlan:
    """Plan section 5 steps4–5 at the actual fill hour's pre-fill mark.

    A flip emits reduction intents before opening intents. The account must group
    all coins' reductions before all increases and execute each at its slipped price.
    """
    values = (
        target_weight,
        held_quantity,
        equity,
        open_price,
        filters.min_quantity,
        filters.max_quantity,
        filters.step_size,
        filters.min_notional,
    )
    if any(not value.is_finite() for value in values):
        raise ValueError("order inputs must be finite")
    if (
        equity <= 0
        or open_price <= 0
        or filters.step_size <= 0
        or filters.min_quantity < 0
        or filters.max_quantity <= 0
        or filters.min_quantity > filters.max_quantity
        or filters.min_notional < 0
    ):
        raise ValueError("invalid equity, price or order filters")
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        step = filters.step_size
        held_steps = held_quantity / step
        if held_steps != held_steps.to_integral_value(rounding=ROUND_DOWN):
            raise ValueError("held quantity must be a multiple of the market step")
        current = held_quantity * open_price / equity
        target = (target_weight * equity / open_price / step).to_integral_value(
            rounding=ROUND_DOWN
        ) * step
        if _sign(target_weight) == _sign(held_quantity) and abs(target_weight - current) <= Decimal(
            ".01"
        ):
            return OrderPlan(current, target, (), (), ())
        orders: list[OrderIntent] = []
        refusals: list[str] = []
        adjustments: list[str] = []

        def reduce(magnitude: Decimal) -> None:
            minimum = (filters.min_quantity / step).to_integral_value(rounding=ROUND_CEILING) * step
            if magnitude < minimum:
                magnitude = min(minimum, abs(held_quantity))
                adjustments.append("minimum_quantity_reduction")
            remaining = abs(held_quantity) - magnitude
            if ZERO < remaining < filters.min_quantity:
                magnitude = abs(held_quantity)
                adjustments.append("dust_close")
            orders.extend(_split(-_sign(held_quantity) * magnitude, True, filters))

        def increase(quantity: Decimal) -> None:
            if quantity == ZERO:
                return
            if abs(quantity) < filters.min_quantity:
                refusals.append("minimum_quantity")
            elif abs(quantity) * open_price < filters.min_notional:
                refusals.append("minimum_notional")
            else:
                orders.extend(_split(quantity, False, filters))

        if held_quantity != ZERO and _sign(target) != _sign(held_quantity):
            reduce(abs(held_quantity))
            increase(target)
        elif abs(target) < abs(held_quantity):
            reduce(abs(held_quantity) - abs(target))
        else:
            increase(target - held_quantity)
        return OrderPlan(current, target, tuple(orders), tuple(refusals), tuple(adjustments))
