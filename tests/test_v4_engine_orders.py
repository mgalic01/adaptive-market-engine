"""V4 engine task 7: the orders of one leg (step rounding, filters, splits, reduce-only
reductions, spot dust) and the fill price and fee of one fill.

Everything here is driven by hand with synthetic quantities and prices; no pack, no ledger and
no network is involved. Quantities are in venue units (Ruling R5).
"""

from __future__ import annotations

import random
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

import pytest

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.driver.venues import cost_profile
from crypto_grid_bot.combined.execution import VenueRules, floor_quantity
from crypto_grid_bot.v4.engine.ledger import Venue
from crypto_grid_bot.v4.engine.numbers import to_fraction
from crypto_grid_bot.v4.engine.orders import LegPlan, Order, fee, fill_price, plan_leg

D = Decimal
PRICE = D(100)

# Step 0.001, minimum 0.001, maximum 100, minimum notional 5: 0.05 coins at 100 just pays 5.
RULES = VenueRules(D("0.001"), D("0.001"), D(100), D(5), D("0.01"))
# Coarse filters for the futures reduction rules: step 0.1, minimum 0.3, a notional nobody meets.
COARSE = VenueRules(D("0.1"), D("0.3"), D(100), D(1000), D("0.01"))


def made(plan: LegPlan) -> list[tuple[int, Decimal, bool]]:
    """The plan's orders as (side, quantity, reduce_only) tuples."""
    return [(order.side, order.quantity, order.reduce_only) for order in plan.orders]


class FakeCosts:
    """A cost object with arbitrary rates, to reach the rate checks Costs itself would stop."""

    def __init__(self, **rates: Any) -> None:
        self.fee_rate: Any = D("0.001")
        self.slippage_rate: Any = D("0.0005")
        self.round_trip_cost_rate: Any = D("0.004")
        for name, value in rates.items():
            setattr(self, name, value)


def plan(
    venue: Venue,
    held: str,
    target: str,
    rules: VenueRules = RULES,
    price: Decimal = PRICE,
) -> LegPlan:
    return plan_leg(venue, D(held), D(target), price, rules)


# ---------------------------------------------------------------------------------------
# Step rounding
# ---------------------------------------------------------------------------------------


def test_rounds_toward_zero_to_the_step() -> None:
    # Opening orders round |target| down, long and short.
    assert made(plan("spot", "0", "1.2349")) == [(1, D("1.234"), False)]
    assert made(plan("futures", "0", "1.2349")) == [(1, D("1.234"), False)]
    assert made(plan("futures", "0", "-2.3456")) == [(-1, D("2.345"), False)]
    # An increase rounds the difference |target| - |held|, not the target.
    assert made(plan("futures", "1", "1.2349")) == [(1, D("0.234"), False)]
    assert made(plan("futures", "-1", "-1.2349")) == [(-1, D("0.234"), False)]
    # A reduction rounds the amount sold toward zero, so it never sells past the target.
    assert made(plan("spot", "3", "1.2349")) == [(-1, D("1.765"), True)]
    assert made(plan("futures", "3", "1.2349")) == [(-1, D("1.765"), True)]
    assert made(plan("futures", "-3", "-1.2349")) == [(1, D("1.765"), True)]
    # It is V3.1's own flooring.
    assert D("1.765") == floor_quantity(D("1.7651"), RULES)


def test_a_leg_at_its_target_makes_no_order_and_no_dust() -> None:
    for venue in ("spot", "futures"):
        for held in ("0", "1.5"):
            result = plan(venue, held, held)  # type: ignore[arg-type]
            assert result == LegPlan((), None, D(0))
    assert plan("futures", "-1.5", "-1.5") == LegPlan((), None, D(0))
    # A difference below one step rounds to nothing and is refused as an increase.
    assert plan("futures", "1", "1.0004") == LegPlan((), "min_qty", D(0))


# ---------------------------------------------------------------------------------------
# Opening and increasing orders: the minimum quantity and notional
# ---------------------------------------------------------------------------------------


def test_opening_order_refused_below_min_qty_or_notional_with_reason() -> None:
    # 0.04 coins at 100 is 4 USDT, below the 5 minimum notional.
    assert plan("spot", "0", "0.04") == LegPlan((), "min_notional", D(0))
    assert plan("futures", "0", "0.04") == LegPlan((), "min_notional", D(0))
    assert plan("futures", "0", "-0.04") == LegPlan((), "min_notional", D(0))
    # Exactly the minimum notional is made (the test is strict below).
    assert made(plan("spot", "0", "0.05")) == [(1, D("0.05"), False)]
    assert made(plan("futures", "0", "-0.05")) == [(-1, D("0.05"), False)]
    # 0.0009 rounds to nothing, which is below the minimum quantity.
    assert plan("spot", "0", "0.0009") == LegPlan((), "min_qty", D(0))
    assert plan("futures", "0", "-0.0009") == LegPlan((), "min_qty", D(0))

    # An increase is held to the same filters, on the difference.
    assert plan("futures", "1", "1.04") == LegPlan((), "min_notional", D(0))
    assert plan("futures", "-1", "-1.04") == LegPlan((), "min_notional", D(0))
    assert plan("spot", "2", "2.04") == LegPlan((), "min_notional", D(0))
    assert made(plan("futures", "1", "1.05")) == [(1, D("0.05"), False)]

    # The minimum quantity is checked first: both filters fail here, and the reason is min_qty.
    wide = VenueRules(D("0.001"), D("0.01"), D(100), D(5), D("0.01"))
    assert plan("spot", "0", "0.005", wide).refusal == "min_qty"
    assert plan("spot", "0", "0.01", wide).refusal == "min_notional"
    assert made(plan("spot", "0", "0.01", wide, price=D(1000))) == [(1, D("0.01"), False)]

    # The notional is taken at the price given, the unslipped open.
    assert plan("spot", "0", "0.05", price=D("99.99")).refusal == "min_notional"
    assert plan("spot", "0", "0.05", price=D("100.01")).refusal is None

    # A refusal changes nothing: the held position stays and there is no dust to report.
    assert plan("spot", "2", "2.04").dust == 0


# ---------------------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------------------


def test_large_order_splits_into_the_fewest_orders() -> None:
    # 250 coins over a 100 maximum: three orders. 250000 steps = 83334 + 83333 + 83333.
    result = plan("spot", "0", "250")
    assert made(result) == [
        (1, D("83.334"), False),
        (1, D("83.333"), False),
        (1, D("83.333"), False),
    ]
    # Exactly the maximum is one order; one step more is two, as equal as whole steps allow.
    assert made(plan("spot", "0", "100")) == [(1, D(100), False)]
    assert made(plan("spot", "0", "100.001")) == [(1, D("50.001"), False), (1, D("50.000"), False)]
    # 400.5 needs five orders of 80.1: the fewest for 400500 steps is 5 (4 x 100000 is too few).
    assert made(plan("futures", "0", "-400.5")) == [(-1, D("80.1"), False)] * 5
    # Futures increases split too, on the increase only.
    assert made(plan("futures", "5", "105.002")) == [
        (1, D("50.001"), False),
        (1, D("50.001"), False),
    ]
    # A maximum that is not a whole number of steps counts whole steps only (100.0005 -> 100).
    odd = VenueRules(D("0.001"), D("0.001"), D("100.0005"), D(5), D("0.01"))
    assert made(plan("spot", "0", "100.001", odd)) == [
        (1, D("50.001"), False),
        (1, D("50.000"), False),
    ]


def test_split_pieces_keep_the_reduce_only_flag() -> None:
    reduction = plan("futures", "250", "0")
    assert made(reduction) == [
        (-1, D("83.334"), True),
        (-1, D("83.333"), True),
        (-1, D("83.333"), True),
    ]
    assert all(order.reduce_only for order in plan("futures", "-250", "-10").orders)
    assert all(order.reduce_only for order in plan("spot", "250", "0").orders)
    assert len(plan("spot", "250", "0").orders) == 3
    # A flip splits the close and the open, each keeping its own flag, the close first.
    flip = made(plan("futures", "150", "-150"))
    assert flip == [
        (-1, D(75), True),
        (-1, D(75), True),
        (-1, D(75), False),
        (-1, D(75), False),
    ]


def test_every_split_is_the_fewest_orders_as_equal_as_whole_steps() -> None:
    rng = random.Random(20261021)
    for _ in range(400):
        maximum = rng.randint(1, 60)
        steps = rng.randint(1, 60 * 40)
        quantity = steps * D("0.001")
        rules = VenueRules(D("0.001"), D("0.001"), maximum * D("0.001"), D(0), D("0.01"))
        orders = plan_leg("spot", D(0), quantity, PRICE, rules).orders
        expected = -(-steps // maximum)  # ceil(steps / maximum)
        sizes = [int(order.quantity / D("0.001")) for order in orders]
        assert len(sizes) == expected
        assert sum(sizes) == steps
        assert max(sizes) <= maximum
        assert max(sizes) - min(sizes) <= 1
        assert sizes == sorted(sizes, reverse=True)  # the larger orders come first


def test_a_split_that_would_not_end_refuses() -> None:
    tiny = VenueRules(D("0.001"), D("0.001"), D("0.001"), D(0), D("0.01"))
    with pytest.raises(ValueError, match="orders"):
        plan_leg("spot", D(0), D(50), PRICE, tiny)  # 50000 orders of one step
    # Closing a futures position that is not a whole number of steps cannot be split.
    with pytest.raises(ValueError, match="whole steps"):
        plan("futures", "150.0005", "0")
    # It can be sent as one order when it fits under the maximum.
    assert made(plan("futures", "1.0005", "0")) == [(-1, D("1.0005"), True)]


# ---------------------------------------------------------------------------------------
# Futures reductions
# ---------------------------------------------------------------------------------------


def test_futures_reduction_raised_to_min_qty_or_whole_and_ignores_notional() -> None:
    # No order here meets the 1000 USDT minimum notional (1 USDT price), and none is refused.
    one = D(1)
    # Zero after rounding, and 0.2 (below 0.3), are both raised to the 0.3 minimum.
    assert made(plan("futures", "5", "4.95", COARSE, one)) == [(-1, D("0.3"), True)]
    assert made(plan("futures", "5", "4.8", COARSE, one)) == [(-1, D("0.3"), True)]
    assert made(plan("futures", "-5", "-4.95", COARSE, one)) == [(1, D("0.3"), True)]
    # At or above the minimum it is left alone.
    assert made(plan("futures", "5", "4.7", COARSE, one)) == [(-1, D("0.3"), True)]
    assert made(plan("futures", "5", "4.6", COARSE, one)) == [(-1, D("0.4"), True)]
    # A position smaller than the minimum is raised to the whole position.
    assert made(plan("futures", "0.2", "0.1", COARSE, one)) == [(-1, D("0.2"), True)]
    assert made(plan("futures", "-0.2", "-0.1", COARSE, one)) == [(1, D("0.2"), True)]
    # A raised reduction that would leave less than the minimum closes the whole position.
    assert made(plan("futures", "0.5", "0.45", COARSE, one)) == [(-1, D("0.5"), True)]
    # With a minimum that is not a whole number of steps, the raise is the smallest legal order.
    off = VenueRules(D("0.1"), D("0.25"), D(100), D(1000), D("0.01"))
    assert made(plan("futures", "5", "4.95", off, one)) == [(-1, D("0.3"), True)]
    # A zero minimum quantity has nothing to raise to: a reduction below a step is no order.
    free = VenueRules(D("0.1"), D(0), D(100), D(0), D("0.01"))
    assert plan("futures", "5", "4.95", free, one) == LegPlan((), None, D(0))
    # The same reductions are never refused, whatever the notional.
    assert plan("futures", "5", "4.95", COARSE, one).refusal is None


def test_reduction_leaving_less_than_min_qty_closes_the_whole_position() -> None:
    one = D(1)
    # 1.0 -> 0.55: reduce 0.4, leaving 0.6, which is at least 0.3: partial.
    assert made(plan("futures", "1", "0.55", COARSE, one)) == [(-1, D("0.4"), True)]
    # 1.0 -> 0.25: reduce 0.7, leaving exactly 0.3 (not less): partial.
    assert made(plan("futures", "1", "0.25", COARSE, one)) == [(-1, D("0.7"), True)]
    # 1.0 -> 0.15: reduce 0.8, leaving 0.2 < 0.3: the whole position goes.
    assert made(plan("futures", "1", "0.15", COARSE, one)) == [(-1, D(1), True)]
    assert made(plan("futures", "-1", "-0.15", COARSE, one)) == [(1, D(1), True)]
    # A zero target closes exactly the position, even below the minimum quantity and notional.
    assert made(plan("futures", "0.7", "0", COARSE, one)) == [(-1, D("0.7"), True)]
    assert made(plan("futures", "-0.7", "0", COARSE, one)) == [(1, D("0.7"), True)]
    assert made(plan("futures", "0.2", "0", COARSE, one)) == [(-1, D("0.2"), True)]
    # A close above the maximum is several reduce-only orders that sum to the position.
    closing = plan("futures", "-250", "0")
    assert made(closing) == [
        (1, D("83.334"), True),
        (1, D("83.333"), True),
        (1, D("83.333"), True),
    ]
    assert closing.refusal is None
    assert closing.dust == 0


# ---------------------------------------------------------------------------------------
# Flips
# ---------------------------------------------------------------------------------------


def test_flip_is_close_then_open() -> None:
    # Long to short: a reduce-only sell of exactly the position, then a sell that opens.
    assert made(plan("futures", "2", "-3")) == [(-1, D(2), True), (-1, D(3), False)]
    # Short to long: a reduce-only buy, then a buy.
    assert made(plan("futures", "-2", "3")) == [(1, D(2), True), (1, D(3), False)]
    # The close is exactly |held| and the open is |target| rounded, not the difference.
    assert made(plan("futures", "2.5", "-0.7777")) == [
        (-1, D("2.5"), True),
        (-1, D("0.777"), False),
    ]
    # The open is held to the increase filters; its refusal is reported and the close stands.
    refused = plan("futures", "2", "-0.04")
    assert made(refused) == [(-1, D(2), True)]
    assert refused.refusal == "min_notional"
    assert refused.dust == 0
    refused = plan("futures", "-2", "0.0009")
    assert made(refused) == [(1, D(2), True)]
    assert refused.refusal == "min_qty"
    # A flip's close ignores the filters, as any reduction does.
    assert made(plan("futures", "0.2", "-5", COARSE, D(1000))) == [
        (-1, D("0.2"), True),
        (-1, D(5), False),
    ]
    # A flip is made even when the position is below the minimum quantity.
    assert made(plan("futures", "0.0005", "-1")) == [(-1, D("0.0005"), True), (-1, D(1), False)]


# ---------------------------------------------------------------------------------------
# Spot sales and dust
# ---------------------------------------------------------------------------------------


def test_spot_remainder_below_filters_becomes_dust() -> None:
    # A full exit sells the floored part; a rest below one step is unsellable dust.
    result = plan("spot", "1.0004", "0")
    assert made(result) == [(-1, D(1), True)]
    assert result.refusal is None
    assert result.dust == D("0.0004")
    # A holding that is entirely unsellable, sold to 0, makes no order and is all dust.
    for held in ("0.0004", "0.04"):  # below the minimum quantity; below the minimum notional
        entire = plan("spot", held, "0")
        assert entire == LegPlan((), None, D(held))
    # A cut that leaves a remainder below the filters leaves dust: 0.96 sells, 0.04 (4 USDT) stays.
    cut = plan("spot", "1", "0.04")
    assert made(cut) == [(-1, D("0.96"), True)]
    assert cut.dust == D("0.04")
    # A cut that leaves a sellable remainder leaves no dust.
    assert plan("spot", "1", "0.5").dust == 0
    assert made(plan("spot", "1", "0.5")) == [(-1, D("0.5"), True)]
    # A sale below the minimum notional is not made. The holding itself could be sold, so it
    # stays held and is not dust.
    small = plan("spot", "10", "9.96")  # 0.04 coins = 4 USDT
    assert small == LegPlan((), None, D(0))
    # A sale that rounds to nothing is the same.
    assert plan("spot", "10", "9.9995") == LegPlan((), None, D(0))
    # A sale at exactly the minimum notional is made.
    assert made(plan("spot", "10", "9.95")) == [(-1, D("0.05"), True)]
    # A sale below the minimum quantity is not made (minimum 0.01, notional 0).
    wide = VenueRules(D("0.001"), D("0.01"), D(100), D(0), D("0.01"))
    assert plan("spot", "10", "9.995", wide) == LegPlan((), None, D(0))
    assert made(plan("spot", "10", "9.99", wide)) == [(-1, D("0.01"), True)]
    # A refused sale of a holding that cannot itself be sold leaves the whole holding as dust.
    assert plan("spot", "0.04", "0.01") == LegPlan((), None, D("0.04"))
    # Dust is judged on what is left in total: the dust joins a buy, and 4.9994 is sellable.
    merged = plan("spot", "0.0004", "5")
    assert made(merged) == [(1, D("4.999"), False)]
    assert merged.dust == 0
    # A refused buy leaves the unsellable holding as dust, and reports the refusal.
    kept = plan("spot", "0.0004", "0.0007")
    assert kept == LegPlan((), "min_qty", D("0.0004"))


def test_spot_sale_splits_above_the_maximum_and_keeps_the_dust() -> None:
    result = plan("spot", "250.0004", "0")
    assert made(result) == [
        (-1, D("83.334"), True),
        (-1, D("83.333"), True),
        (-1, D("83.333"), True),
    ]
    assert result.dust == D("0.0004")


def test_spot_never_goes_short() -> None:
    with pytest.raises(ValueError, match="spot"):
        plan("spot", "1", "-0.5")
    with pytest.raises(ValueError, match="spot"):
        plan("spot", "-1", "0")
    # Futures take both signs.
    assert made(plan("futures", "0", "-0.5")) == [(-1, D("0.5"), False)]


# ---------------------------------------------------------------------------------------
# Fill price and fee
# ---------------------------------------------------------------------------------------


def test_fill_price_and_fee_follow_the_cost_profile() -> None:
    spot = cost_profile(1, "spot")
    futures = cost_profile(1, "futures")
    # open x (1 + side x slippage): a buy pays up, a sale receives less, and nothing is rounded
    # to the tick.
    assert fill_price(D(100), 1, spot) == D("100.05")
    assert fill_price(D(100), -1, spot) == D("99.95")
    assert fill_price(D("123.456789"), 1, futures) == D("123.456789") * D("1.0005")
    assert fill_price(D("0.00001234"), -1, futures) == D("0.00001234") * D("0.9995")
    assert fill_price(D(100), 1, spot) == fill_price(D(100), 1, futures)  # same slippage
    # fee = quantity x fill price x fee rate.
    assert fee(D(2), D("100.05"), spot) == D("0.2001")
    assert fee(D(2), D("100.05"), futures) == D("0.10005")
    assert fee(D("0.123"), D("99.95"), spot) == D("0.123") * D("99.95") * D("0.001")
    # Doubled costs double all three.
    doubled = cost_profile(2, "spot")
    assert fill_price(D(100), 1, doubled) == D("100.1")
    assert fill_price(D(100), -1, doubled) == D("99.9")
    assert fee(D(2), D("100.1"), doubled) == D("0.4004")  # fee 0.002
    # A zero cost profile changes nothing.
    free = Costs(D(0), D(0), D(0))
    assert fill_price(D("100.37"), 1, free) == D("100.37")
    assert fee(D(2), D("100.37"), free) == 0


def test_fill_price_and_fee_are_exact() -> None:
    rng = random.Random(7)
    for multiple in (1, 2):
        for venue in ("spot", "futures"):
            costs = cost_profile(multiple, venue)  # type: ignore[arg-type]
            for _ in range(200):
                open_price = D(rng.randint(1, 10**9)) / D(10 ** rng.randint(0, 9))
                quantity = D(rng.randint(1, 10**7)) / D(10 ** rng.randint(0, 7))
                side = rng.choice((1, -1))
                filled = fill_price(open_price, side, costs)
                assert to_fraction(filled) == to_fraction(open_price) * (
                    1 + side * to_fraction(costs.slippage_rate)
                )
                paid = fee(quantity, filled, costs)
                assert to_fraction(paid) == (
                    to_fraction(quantity) * to_fraction(filled) * to_fraction(costs.fee_rate)
                )
    # The result is the number itself, not a 60-digit rounding of it: it refuses instead.
    long_price = D("1." + "1" * 58)
    with pytest.raises(ValueError, match="exact"):
        fill_price(long_price, 1, cost_profile(1, "spot"))
    with pytest.raises(ValueError, match="exact"):
        fee(D("1.234567"), D("1." + "7" * 58), cost_profile(1, "spot"))
    # A product that fits in 60 digits is returned in full, however many it uses.
    wide = D("1." + "1" * 50)
    assert to_fraction(fill_price(wide, -1, cost_profile(1, "spot"))) == to_fraction(wide) * (
        1 - to_fraction(D("0.0005"))
    )


def test_fill_price_and_fee_refuse_bad_input() -> None:
    costs = cost_profile(1, "spot")
    bad_numbers: list[Any] = [100, 100.0, "100", None, D("NaN"), D("Infinity"), D(0), D(-1)]
    for bad in bad_numbers:
        with pytest.raises(ValueError, match="open_price"):
            fill_price(bad, 1, costs)
        with pytest.raises(ValueError, match="price"):
            fee(D(1), bad, costs)
        with pytest.raises(ValueError, match="quantity"):
            fee(bad, D(100), costs)
    for side in (0, 2, -2, True, False, 1.0, "1", None):
        with pytest.raises(ValueError, match="side"):
            fill_price(D(100), side, costs)  # type: ignore[arg-type]
    # Rates come from a Costs object: a rate outside [0, 1) or not a Decimal is refused.
    for bad in (D("1"), D("-0.1"), D("NaN"), 0.0005, None):
        with pytest.raises(ValueError, match="slippage_rate"):
            fill_price(D(100), 1, FakeCosts(slippage_rate=bad))  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="fee_rate"):
            fee(D(1), D(100), FakeCosts(fee_rate=bad))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="open_price"):
        fill_price(D("1E+400"), 1, costs)


# ---------------------------------------------------------------------------------------
# Inputs and the value objects
# ---------------------------------------------------------------------------------------


def test_plan_leg_refuses_bad_input() -> None:
    bad_numbers: list[Any] = [1, 1.0, "1", None, D("NaN"), D("Infinity"), D("-Infinity")]
    for bad in bad_numbers:
        with pytest.raises(ValueError, match="held"):
            plan_leg("futures", bad, D(1), PRICE, RULES)
        with pytest.raises(ValueError, match="target"):
            plan_leg("futures", D(1), bad, PRICE, RULES)
        with pytest.raises(ValueError, match="price"):
            plan_leg("futures", D(1), D(2), bad, RULES)
    for price in (D(0), D(-5)):
        with pytest.raises(ValueError, match="price"):
            plan_leg("futures", D(1), D(2), price, RULES)
    for venue in ("margin", "Spot", "", None, 1):
        with pytest.raises(ValueError, match="venue"):
            plan_leg(venue, D(1), D(2), PRICE, RULES)  # type: ignore[arg-type]
    for rules in (None, (D("0.001"),), "rules"):
        with pytest.raises(ValueError, match="rules"):
            plan_leg("futures", D(1), D(2), PRICE, rules)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="held"):
        plan_leg("futures", D("1E+40"), D(0), PRICE, RULES)
    with pytest.raises(ValueError, match="target"):
        plan_leg("futures", D(0), D("1E-200"), PRICE, RULES)


def test_order_and_plan_are_validated_frozen_values() -> None:
    order = Order(1, D("0.5"), True)
    with pytest.raises(FrozenInstanceError):
        order.side = -1  # type: ignore[misc]
    assert order == Order(1, D("0.50"), True)
    for side in (0, 2, True, 1.0, "1"):
        with pytest.raises(ValueError, match="side"):
            Order(side, D(1), False)  # type: ignore[arg-type]
    for quantity in (D(0), D(-1), D("NaN"), 1, 1.5, None):
        with pytest.raises(ValueError, match="quantity"):
            Order(1, quantity, False)  # type: ignore[arg-type]
    for flag in (0, 1, "yes", None):
        with pytest.raises(ValueError, match="reduce_only"):
            Order(1, D(1), flag)  # type: ignore[arg-type]

    leg = LegPlan((order,), "min_qty", D("0.1"))
    with pytest.raises(FrozenInstanceError):
        leg.dust = D(0)  # type: ignore[misc]
    with pytest.raises(ValueError, match="orders"):
        LegPlan([order], None, D(0))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="orders"):
        LegPlan((order, "order"), None, D(0))  # type: ignore[arg-type]
    for refusal in ("size", "", 1):
        with pytest.raises(ValueError, match="refusal"):
            LegPlan((), refusal, D(0))  # type: ignore[arg-type]
    for dust in (D(-1), D("NaN"), 0, None):
        with pytest.raises(ValueError, match="dust"):
            LegPlan((), None, dust)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------
# Invariants over random legs
# ---------------------------------------------------------------------------------------


def sellable(quantity: Decimal, price: Decimal, rules: VenueRules) -> bool:
    """An independent restatement of the sale test, on an amount already floored."""
    return quantity > 0 and quantity >= rules.min_qty and quantity * price >= rules.min_notional


def test_random_legs_keep_their_invariants() -> None:
    rng = random.Random(4242)
    step = D("0.01")
    for _ in range(4000):
        rules = VenueRules(
            step,
            D(rng.choice(("0", "0.01", "0.05", "0.2"))),
            D(rng.choice(("1", "3", "10"))),
            D(rng.choice(("0", "5", "50"))),
            D("0.01"),
        )
        price = D(rng.choice(("0.5", "10", "100")))
        venue: Venue = rng.choice(("spot", "futures"))
        held = rng.randint(0, 3000) * step
        target = D(rng.randint(0, 3000)) / D(rng.choice((1, 10, 1000)))
        if venue == "futures":
            held *= rng.choice((1, -1))
            target *= rng.choice((1, -1))
        result = plan_leg(venue, held, target, price, rules)

        reduce_only_done = False
        position = held
        reduced = D(0)
        for order in result.orders:
            assert order.quantity > 0
            assert order.quantity % step == 0
            assert order.quantity <= rules.max_qty
            if order.reduce_only:
                # Reductions come first, shrink |position| and never cross zero.
                assert not reduce_only_done
                assert order.side == (-1 if position > 0 else 1)
                position += order.side * order.quantity
                assert position == 0 or (position > 0) == (held > 0)
                reduced += order.quantity
            else:
                reduce_only_done = True
                assert order.side == (1 if target > 0 else -1)
                position += order.side * order.quantity
        assert reduced <= abs(held)

        if target == held:
            assert result.orders == () and result.refusal is None
        if result.refusal is not None:
            # Only an increase is ever refused, and then it makes no opening order.
            assert all(order.reduce_only for order in result.orders)
            assert abs(target) > 0
        if venue == "spot":
            assert position >= 0
            assert all(order.reduce_only == (order.side == -1) for order in result.orders)
            floored = floor_quantity(position, rules)
            if position > 0 and not sellable(floored, price, rules):
                assert result.dust == position
            else:
                assert result.dust == 0
        else:
            assert result.dust == 0
            if result.refusal is None and target != 0 and result.orders:
                # A made order moves the leg to the target's side, never past zero.
                assert position == 0 or (position > 0) == (target > 0)
        # An opening order, when one is made, is not below the filters as a whole (its split
        # pieces may be).
        opened = sum((order.quantity for order in result.orders if not order.reduce_only), D(0))
        if opened:
            assert opened >= rules.min_qty
            assert opened * price >= rules.min_notional
