"""The orders of one leg and the price and fee of one fill: step rounding, the exchange filters,
splits, reduce-only reductions and spot dust.

Implements the spec's "Account and execution" (the bullets "Costs (normal)", "Exchange filters"
and "Reductions are never refused for size") and the "Safety" rule that a spot remainder a cut
leaves below the filters becomes dust, with the plan's Ruling R3 for the fill price. One leg is
one coin's position on one venue. ``plan_leg`` turns a held quantity and a target into orders.
The module is pure: it sees no ledger, no market and no clock.

Quantities are in the venue's own units (coins on spot, contracts on the perpetual; Ruling R5)
and ``price`` is the unslipped open, which the notional filters use. Spot is long only
(``held >= 0``, ``target >= 0``); futures are signed.

* **The target is rounded first,** as V3 does (``trend.orders.plan_reduction``): every leg
  rounds ``|target|`` toward zero to the step, and the order is the difference to ``held``. So a
  reduction ends at or below its target, never above it.
* **Increases** open or grow ``|position|``. The quantity is ``floor(|target|) - |held|``. Below
  the minimum quantity, or below the minimum notional at ``price``, no order is made and
  ``refusal`` names the filter, the quantity checked first.
* **Splits.** An order above the maximum quantity becomes the fewest orders, as equal as whole
  steps allow: ``T`` steps over ``M = max_qty // step`` make ``n = ceil(T / M)`` orders, and
  ``T % n`` of them are one step larger, the larger ones first. Every piece keeps its parent's
  flag. The filters judge the whole order, not its pieces.
* **Futures reductions** (same sign, ``|target| < |held|``, or target 0) are reduce-only and
  never refused. Target 0 closes exactly ``|held|``. Otherwise the reduction is ``|held| -
  floor(|target|)``; if that is 0 or below the minimum quantity it is raised to the minimum
  quantity (on a whole number of steps), or to the whole position when that is smaller; and a
  reduction that would leave less than the minimum quantity closes the whole position.
* **A flip** (a target of the opposite sign) is a reduce-only close of exactly ``|held|``, then
  an opening order under the increase filters. A refusal of the opening order is reported and
  the close still stands.
* **Spot sales** (target below held) sell ``held - floor(target)`` when that is at least the
  minimum quantity and notional, and make no order otherwise.
* **Dust** is the spot quantity left after the plan, when it is above 0 and cannot be sold
  because it rounds below the minimum quantity or notional. A refused sale of a holding that
  could itself be sold leaves it held, not dust. A leg at its target makes no order, and its
  holding is dust only if it cannot be sold. Futures never have dust.

A ``held`` that is not a whole number of steps (spot dust) is handled as before: every order but
an exact full close is a whole number of steps, so the difference is rounded down once more
(``floor(held - floor(target))``). A spot sale or a futures reduction then leaves the sub-step
part of ``held`` in place, as dust on spot; an increase whose floored target is not above
``held`` is a zero quantity and is refused as ``"min_qty"``.

An order is ``reduce_only`` when it only shrinks the leg: every futures reduction, close and flip
close, and every spot sale. Openings and increases are not. The reduce-only orders of a plan come
first. A plan has no refusal unless an increase was refused.

``fill_price`` and ``fee`` are exact Decimal products: they are checked against the exact
fractions and refuse a result a 60-digit context would have rounded.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from typing import get_args

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.execution import VenueRules, floor_quantity
from crypto_grid_bot.v4.engine.ledger import Venue
from crypto_grid_bot.v4.engine.numbers import CONTEXT, sign, to_decimal, to_fraction

_VENUES: tuple[str, ...] = get_args(Venue)
_REFUSALS = (None, "min_qty", "min_notional")

# Bounds of V3.1's execution helpers: |value| up to 1e36, at most 100 decimal places.
_MAX_ADJUSTED = 36
_MIN_EXPONENT = -100
# A guard against a rules object that would split an order into a flood of pieces.
_MAX_ORDERS = 10_000

_ZERO = Fraction(0)


@dataclass(frozen=True, slots=True)
class Order:
    """One market order: ``side`` +1 buys and -1 sells ``quantity`` (venue units).
    ``reduce_only`` marks an order that only shrinks the leg."""

    side: int
    quantity: Decimal
    reduce_only: bool

    def __post_init__(self) -> None:
        _side(self.side)
        _amount(self.quantity, "quantity", positive=True)
        if type(self.reduce_only) is not bool:
            raise ValueError(f"reduce_only must be a bool, got {self.reduce_only!r:.40}")


@dataclass(frozen=True, slots=True)
class LegPlan:
    """The orders of one leg, in fill order (reduce-only ones first); the ``refusal`` of an
    increase below the filters (``"min_qty"`` or ``"min_notional"``), else None; and the spot
    ``dust`` left after the plan."""

    orders: tuple[Order, ...]
    refusal: str | None
    dust: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.orders, tuple) or not all(
            isinstance(order, Order) for order in self.orders
        ):
            raise ValueError(f"orders must be a tuple of Order, got {self.orders!r:.60}")
        if self.refusal not in _REFUSALS:
            raise ValueError(f"refusal must be one of {_REFUSALS}, got {self.refusal!r:.40}")
        _amount(self.dust, "dust")


def plan_leg(
    venue: Venue, held: Decimal, target: Decimal, price: Decimal, rules: VenueRules
) -> LegPlan:
    """The orders that move one leg from ``held`` to ``target``, in venue units.

    ``price`` is the unslipped open, used for the notional filters. Refuses a venue other than
    ``"spot"`` or ``"futures"``, a non-finite or non-Decimal quantity or price, a price at or
    below zero, a negative spot ``held`` or ``target``, and rules that are not ``VenueRules``.
    A futures close above the maximum quantity needs the position in whole steps to split it.
    """
    kind = _venue(venue)
    signed = kind == "futures"
    current = _amount(held, "held" if signed else "spot held", signed=signed)
    wanted = _amount(target, "target" if signed else "spot target", signed=signed)
    unit_price = _amount(price, "price", positive=True)
    if not isinstance(rules, VenueRules):
        raise ValueError(f"rules must be VenueRules, got {rules!r:.60}")
    if kind == "spot":
        return _plan_spot(current, wanted, unit_price, rules)
    return _plan_futures(current, wanted, unit_price, rules)


def fill_price(open_price: Decimal, side: int, costs: Costs) -> Decimal:
    """``open x (1 + side x slippage)``: a buy fills above the open and a sale below it. Not
    rounded to the tick (Ruling R3). Refuses a result a 60-digit context would round."""
    opening = _amount(open_price, "open_price", positive=True)
    _side(side)
    slippage = _rate(costs.slippage_rate, "slippage_rate")
    with localcontext(CONTEXT):
        result = open_price * (1 + side * costs.slippage_rate)
    return _exact(result, opening * (1 + side * slippage), "fill price")


def fee(quantity: Decimal, price: Decimal, costs: Costs) -> Decimal:
    """``quantity x price x fee rate``, with ``price`` the fill price. Refuses a result a
    60-digit context would round."""
    amount = _amount(quantity, "quantity", positive=True)
    unit_price = _amount(price, "price", positive=True)
    rate = _rate(costs.fee_rate, "fee_rate")
    with localcontext(CONTEXT):
        result = quantity * price * costs.fee_rate
    return _exact(result, amount * unit_price * rate, "fee")


def _plan_spot(held: Fraction, target: Fraction, price: Fraction, rules: VenueRules) -> LegPlan:
    orders: list[Order] = []
    refusal: str | None = None
    left = held
    if target > held:
        quantity, refusal = _increase(target, held, price, rules)
        orders.extend(_pieces(1, quantity, False, rules))
        left += quantity
    elif target < held:
        sale = _floor(held - _floor(target, rules), rules)
        if _sellable(sale, price, rules):
            orders.extend(_pieces(-1, sale, True, rules))
            left -= sale
    unsellable = left > 0 and not _sellable(_floor(left, rules), price, rules)
    return LegPlan(tuple(orders), refusal, to_decimal(left) if unsellable else Decimal(0))


def _plan_futures(held: Fraction, target: Fraction, price: Fraction, rules: VenueRules) -> LegPlan:
    if target == held:
        return LegPlan((), None, Decimal(0))
    orders: list[Order] = []
    refusal: str | None = None
    base = abs(held)  # what the leg already holds on the target's side
    if held != 0 and sign(target) != sign(held):
        # A close, or the first half of a flip: exactly the position, whatever the filters say.
        orders.extend(_pieces(-sign(held), abs(held), True, rules))
        base = _ZERO
    elif abs(target) < abs(held):
        quantity = _reduction(abs(held), abs(target), rules)
        orders.extend(_pieces(-sign(held), quantity, True, rules))
        return LegPlan(tuple(orders), None, Decimal(0))
    if target != 0:
        quantity, refusal = _increase(abs(target), base, price, rules)
        orders.extend(_pieces(sign(target), quantity, False, rules))
    return LegPlan(tuple(orders), refusal, Decimal(0))


def _increase(
    target: Fraction, held: Fraction, price: Fraction, rules: VenueRules
) -> tuple[Fraction, str | None]:
    """The quantity of an opening or increasing order from ``held`` up to ``floor(target)``
    (both absolute), and its refusal. The quantity is 0 when the order is refused."""
    quantity = _floor(max(_floor(target, rules) - held, _ZERO), rules)
    if quantity < to_fraction(rules.min_qty):
        return _ZERO, "min_qty"
    if quantity * price < to_fraction(rules.min_notional):
        return _ZERO, "min_notional"
    if quantity <= 0:  # no filter at all, and still nothing smaller than a step to order
        return _ZERO, "min_qty"
    return quantity, None


def _reduction(held: Fraction, target: Fraction, rules: VenueRules) -> Fraction:
    """The quantity of a futures reduction from ``held`` down to ``floor(target)``, both
    absolute and ``0 < target < held``. Never refused: raised to the minimum, or to the whole
    position."""
    min_qty = to_fraction(rules.min_qty)
    quantity = _floor(held - _floor(target, rules), rules)
    if quantity == 0 or quantity < min_qty:
        # The smallest legal order: the minimum quantity, on a whole number of steps.
        step = to_fraction(rules.step)
        quantity = min(-((-min_qty) // step) * step, held)
    if 0 < held - quantity < min_qty:
        quantity = held
    return quantity


def _sellable(quantity: Fraction, price: Fraction, rules: VenueRules) -> bool:
    """Whether a spot quantity, already rounded to the step, may be sold."""
    return (
        quantity > 0
        and quantity >= to_fraction(rules.min_qty)
        and quantity * price >= to_fraction(rules.min_notional)
    )


def _pieces(side: int, quantity: Fraction, reduce_only: bool, rules: VenueRules) -> list[Order]:
    """The orders of one quantity: a single order, or the fewest that stay within the maximum
    quantity, as equal as whole steps allow and the larger ones first. None for 0."""
    if quantity == 0:
        return []
    step = to_fraction(rules.step)
    if quantity <= to_fraction(rules.max_qty):
        return [Order(side, to_decimal(quantity), reduce_only)]
    steps, remainder = divmod(quantity, step)
    if remainder:
        raise ValueError(
            f"{to_decimal(quantity)} is above the maximum and not whole steps to split"
        )
    per_order = int(to_fraction(rules.max_qty) // step)  # M >= 1: VenueRules keeps step <= max
    count = -(-steps // per_order)
    if count > _MAX_ORDERS:
        raise ValueError(f"the order would split into {count} orders, more than {_MAX_ORDERS}")
    size, larger = divmod(steps, count)
    sizes = [size + 1] * larger + [size] * (count - larger)
    return [Order(side, to_decimal(piece * step), reduce_only) for piece in sizes]


def _floor(amount: Fraction, rules: VenueRules) -> Fraction:
    """``amount >= 0`` rounded toward zero to the step, by V3.1's ``floor_quantity``."""
    floored = to_fraction(floor_quantity(to_decimal(amount), rules))
    step = to_fraction(rules.step)
    if floored % step or not 0 <= amount - floored < step:
        raise ValueError(f"{to_decimal(amount)} did not round to the step {rules.step}")
    return floored


def _venue(value: object) -> Venue:
    if isinstance(value, str):
        if value == "spot":
            return "spot"
        if value == "futures":
            return "futures"
    raise ValueError(f"venue must be one of {_VENUES}, got {value!r:.40}")


def _side(value: object) -> int:
    if type(value) is not int or value not in (1, -1):
        raise ValueError(f"side must be +1 or -1, got {value!r:.40}")
    return value


def _amount(value: object, what: str, *, positive: bool = False, signed: bool = False) -> Fraction:
    """The exact value of a bounded finite Decimal: positive, signed, or (the default) at
    least 0."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} must be a finite Decimal, got {value!r:.40}")
    exponent = value.as_tuple().exponent
    if (
        value.adjusted() > _MAX_ADJUSTED
        or not isinstance(exponent, int)
        or exponent < _MIN_EXPONENT
    ):
        raise ValueError(f"{what} must be below 1e36 with at most 100 decimals, got {value!r:.40}")
    if positive and value <= 0:
        raise ValueError(f"{what} must be positive, got {value}")
    if not positive and not signed and value < 0:
        raise ValueError(f"{what} must not be negative, got {value}")
    return to_fraction(value)


def _rate(value: object, what: str) -> Fraction:
    rate = _amount(value, what)
    if rate >= 1:
        raise ValueError(f"{what} must be below 1, got {value}")
    return rate


def _exact(result: Decimal, expected: Fraction, what: str) -> Decimal:
    if to_fraction(result) != expected:
        raise ValueError(f"the {what} is not exact in {CONTEXT.prec} digits: {result}")
    return result
