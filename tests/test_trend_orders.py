"""Order plans on hand-computed synthetic account states."""

from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from crypto_grid_bot.trend.filters import OrderFilters

D = Decimal


def filters(minimum="1", maximum="100", step="1", notional="5"):
    return OrderFilters(
        D(minimum), D(maximum), D(step), D(notional), D(minimum), D(maximum), D(step), D(step)
    )


def plan(target, held="0", equity="1000", price="10", rules=None):
    from crypto_grid_bot.trend.orders import plan_rebalance

    return plan_rebalance(D(target), D(held), D(equity), D(price), rules or filters())


def quantities(result):
    return [(order.quantity, order.reduce_only) for order in result.orders]


def test_band_is_strict_and_target_zero_always_closes():
    assert quantities(plan(".11", held="10")) == []
    assert quantities(plan(".1101", held="10")) == [(D(1), False)]
    assert quantities(plan("0", held="1")) == [(D(-1), True)]


def test_sign_flip_bypasses_band_and_refused_open_leaves_flat():
    result = plan("-.001", held=".1", rules=filters(minimum=".01", step=".01", notional="5"))
    assert quantities(result) == [(D("-.1"), True)]
    assert result.refusals == ("minimum_notional",)


@pytest.mark.parametrize("target,expected", [(".129", "12"), ("-.129", "-12")])
def test_target_rounds_toward_zero(target, expected):
    result = plan(target)
    assert result.target_quantity == D(expected)
    assert quantities(result) == [(D(expected), False)]


def test_flip_is_two_separate_orders():
    assert quantities(plan("-.2", held="10")) == [(D(-10), True), (D(-20), False)]
    assert quantities(plan(".2", held="-10")) == [(D(10), True), (D(20), False)]


@pytest.mark.parametrize(
    "rules,reason",
    [(filters(minimum="2"), "minimum_quantity"), (filters(notional="20"), "minimum_notional")],
)
def test_opening_refusals_are_recorded(rules, reason):
    result = plan(".01", rules=rules)
    assert not result.orders
    assert result.refusals == (reason,)


def test_reduction_ignores_notional_and_enlarges_small_remainder():
    result = plan(".02", held="5", rules=filters(minimum="3", notional="1000"))
    assert quantities(result) == [(D(-5), True)]
    assert "dust_close" in result.adjustments
    result = plan(".04", held="6", rules=filters(minimum="3", notional="1000"))
    assert quantities(result) == [(D(-3), True)]
    assert "minimum_quantity_reduction" in result.adjustments
    assert quantities(plan("0", held="1", rules=filters(minimum="3"))) == [(D(-1), True)]


def test_split_distributes_leftover_steps_to_earliest_orders():
    result = plan(".25", rules=filters(maximum="10"))
    assert quantities(result) == [(D(9), False), (D(8), False), (D(8), False)]
    assert quantities(plan("0", held="25", rules=filters(maximum="10"))) == [
        (D(-9), True),
        (D(-8), True),
        (D(-8), True),
    ]


def test_impossible_prescribed_split_is_invalid():
    with pytest.raises(ValueError, match="split"):
        plan(".06", rules=filters(minimum="4", maximum="5"))
    with pytest.raises(ValueError, match="split"):
        plan(".1", rules=filters(maximum="5", step="2"))


def test_ambient_context_does_not_change_order_plan():
    expected = plan(".1299", equity="1234.5678", price="12.3456")
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        assert plan(".1299", equity="1234.5678", price="12.3456") == expected


@pytest.mark.parametrize(
    "target,held,equity,price",
    [
        ("NaN", "0", "100", "10"),
        ("1", "0", "0", "10"),
        ("1", "0", "100", "0"),
        ("1", "0", "100", "Infinity"),
    ],
)
def test_bad_financial_inputs_fail_before_planning(target, held, equity, price):
    with pytest.raises(ValueError):
        plan(target, held, equity, price)


def test_band_uses_weight_before_quantity_rounding():
    result = plan(".0001", held="1")
    assert result.target_quantity == 0
    assert not result.orders  # Same sign and within band: rounding cannot force a trade.
    assert quantities(plan(".0001", held="5")) == [(D(-5), True)]
    assert quantities(plan(".001", price="1", rules=filters(notional="1"))) == [(D(1), False)]


def test_minimum_threshold_equality_and_maximum_equality_are_accepted():
    assert quantities(plan(".05", rules=filters(minimum="5", maximum="5", notional="50"))) == [
        (D(5), False)
    ]


def test_reduction_minimum_rounds_up_to_a_valid_quantity_step():
    result = plan(".03", held="5", rules=filters(minimum="2.5"))
    assert quantities(result) == [(D(-5), True)]  # Raise to3, then residual2 is dust.
    assert result.adjustments == ("minimum_quantity_reduction", "dust_close")


@pytest.mark.parametrize(
    "rules", [filters(step="0"), filters(minimum="6", maximum="5"), filters(notional="-1")]
)
def test_invalid_filters_are_rejected(rules):
    with pytest.raises(ValueError):
        plan(".2", rules=rules)


def test_non_step_held_quantity_is_rejected():
    with pytest.raises(ValueError, match="market step"):
        plan(".2", held="1.5")
