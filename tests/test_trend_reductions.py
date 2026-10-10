"""Mandatory risk reductions must not inherit the daily turnover band."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.filters import OrderFilters


def rules(minimum="1", maximum="100", step="1"):
    return OrderFilters(*map(D, (minimum, maximum, step, "1000000", minimum, maximum, step, step)))


@pytest.mark.parametrize("held,target,expected", [("10", "9.99", "-1"), ("-10", "-9.99", "1")])
def test_mandatory_reduction_rounds_target_and_ignores_notional(held, target, expected):
    from crypto_grid_bot.trend.orders import plan_reduction

    orders, adjustments = plan_reduction(D(held), D(target), rules())
    assert [(o.quantity, o.reduce_only) for o in orders] == [(D(expected), True)]


def test_mandatory_reduction_reports_minimum_and_dust():
    from crypto_grid_bot.trend.orders import plan_reduction

    orders, adjustments = plan_reduction(D(5), D(4), rules(minimum="3"))
    assert [o.quantity for o in orders] == [D(-5)]
    assert adjustments == ("minimum_quantity_reduction", "dust_close")


def test_mandatory_reduction_splits_and_closes_below_minimum():
    from crypto_grid_bot.trend.orders import plan_reduction

    assert [o.quantity for o in plan_reduction(D(25), D(0), rules(maximum="10"))[0]] == [
        D(-9),
        D(-8),
        D(-8),
    ]
    assert plan_reduction(D(1), D(0), rules(minimum="3"))[0][0].quantity == -1


@pytest.mark.parametrize(
    "held,target", [("10", "11"), ("10", "-1"), ("0", "1"), ("1.5", "0"), ("NaN", "0")]
)
def test_invalid_reduction_fails(held, target):
    from crypto_grid_bot.trend.orders import plan_reduction

    with pytest.raises(ValueError):
        plan_reduction(D(held), D(target), rules())
