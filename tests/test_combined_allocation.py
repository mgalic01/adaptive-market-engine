from dataclasses import replace
from decimal import Decimal as D
from decimal import localcontext
from fractions import Fraction

import pytest
from test_combined_decisions import setup as decision_setup  # noqa: F401

from crypto_grid_bot.combined.allocation import allocate_grid
from crypto_grid_bot.combined.routing import RoutingContext
from crypto_grid_bot.strategy.perception import TrendState


@pytest.fixture
def basket(request):
    coordinator, engine, _, args = request.getfixturevalue("decision_setup")
    args["assessment"] = replace(
        args["assessment"], daily=TrendState.RANGE, four_hour=TrendState.RANGE
    )
    args["routing"] = RoutingContext(flow_allowed=True)
    result = coordinator.decide(**args)
    assert result.admission.accepted
    return result, engine


def test_three_children_share_exactly_one_reservation_and_report_rounding_residue(basket):
    result, engine = basket
    before = engine.reservations
    allocation = allocate_grid(result)
    assert allocation.accepted and len(allocation.children) == 3
    assert engine.reservations == before
    assert sum(child.weight for child in allocation.children) == 1
    assert sum(child.quantity for child in allocation.children) <= result.admission.quantity
    assert allocation.quantity + allocation.unused_quantity == result.admission.quantity
    assert allocation.risk + allocation.unused_risk == result.admission.risk
    assert allocation.cash + allocation.unused_cash == result.admission.cash
    assert allocation.notional + allocation.unused_notional == result.admission.notional
    assert all(child.quantity % D(".001") == 0 for child in allocation.children)
    assert len(engine.reservations) == 1


def test_tick_floor_preserves_below_quote_limits_and_reweights_risk(basket):
    result, _ = basket
    inputs = replace(
        result.venue_inputs,
        rules=replace(result.venue_inputs.rules, tick=D(".3")),
        costs=replace(result.venue_inputs.costs, round_trip_cost_rate=D(".006")),
    )
    result = replace(result, venue_inputs=inputs)
    allocation = allocate_grid(result)
    assert allocation.accepted
    assert [child.limit for child in allocation.children] == [D("99"), D("97.8"), D("96.9")]
    bound = Fraction(D(".6"))
    weighted_risks = [
        child.weight * (Fraction(child.limit - result.plan.stop) + bound)
        for child in allocation.children
    ]
    assert len(set(weighted_risks)) == 1
    for child in allocation.children:
        assert child.actual_stop_risk > 0
        assert child.risk_bound >= child.actual_stop_risk


def test_one_child_below_minimum_rejects_whole_basket_without_dropping_levels(basket):
    result, engine = basket
    rule = replace(result.venue_inputs.rules, min_notional=D(1000))
    result = replace(
        result,
        venue_inputs=replace(result.venue_inputs, rules=rule),
        intent=replace(result.intent, min_notional=D(1000)),
    )
    allocation = allocate_grid(result)
    assert not allocation.accepted and allocation.children == ()
    assert allocation.reason == "child_below_minimum"
    assert allocation.unused_quantity == result.admission.quantity
    assert engine.reservations[0] == result.admission


@pytest.mark.parametrize("tick", [D(5), D(100), D(98)])
def test_duplicate_nonpositive_or_stop_crossing_tick_levels_refuse_entire_basket(basket, tick):
    result, _ = basket
    inputs = replace(result.venue_inputs, rules=replace(result.venue_inputs.rules, tick=tick))
    allocation = allocate_grid(replace(result, venue_inputs=inputs))
    assert not allocation.accepted and allocation.children == ()
    assert allocation.reason == "invalid_rounded_levels"


@pytest.mark.parametrize("field", ["risk", "cash", "notional"])
def test_allocation_cannot_exceed_any_recorded_basket_budget(basket, field):
    result, _ = basket
    result = replace(result, admission=replace(result.admission, **{field: D(".01")}))
    allocation = allocate_grid(result)
    assert not allocation.accepted
    assert allocation.reason == "basket_budget_exceeded"


def test_non_grid_or_unapproved_result_cannot_allocate(basket):
    result, _ = basket
    for bad in (
        replace(result, admission=None),
        replace(result, admission=replace(result.admission, accepted=False)),
        replace(result, plan=replace(result.plan, owner="spot_trend")),
    ):
        with pytest.raises(ValueError):
            allocate_grid(bad)


def coarse_stop_basket(result, bound_rate, slip="0"):
    return replace(
        result,
        plan=replace(
            result.plan,
            reference_price=D(150),
            stop=D(98),
            levels=tuple(
                replace(level, price=D(price))
                for level, price in zip(result.plan.levels, (140, 130, 120), strict=True)
            ),
        ),
        intent=replace(
            result.intent, price=D(150), stop=D(98), fee_rate=D(".001"), slippage_rate=D(slip)
        ),
        venue_inputs=replace(
            result.venue_inputs,
            rules=replace(result.venue_inputs.rules, tick=D(10)),
            costs=replace(
                result.venue_inputs.costs,
                fee_rate=D(".001"),
                slippage_rate=D(slip),
                round_trip_cost_rate=D(bound_rate),
            ),
        ),
        admission=replace(result.admission, risk=D(10000), cash=D(10000), notional=D(10000)),
    )


def test_coarse_stop_tick_refuses_understated_execution_bound(basket):
    result, engine = basket
    before = engine.reservations
    allocation = allocate_grid(coarse_stop_basket(result, ".01"))
    assert not allocation.accepted
    assert allocation.reason == "round_trip_cost_understated"
    assert allocation.children == ()
    assert engine.reservations == before


@pytest.mark.parametrize("slip", ["0", ".01"])
def test_coarse_stop_tick_costs_use_actual_sell_price_independent_of_context(basket, slip):
    result = coarse_stop_basket(basket[0], ".1", slip)
    allocation = allocate_grid(result)
    assert allocation.accepted
    for child in allocation.children:
        price, quantity = Fraction(child.limit), Fraction(child.quantity)
        exit_price = Fraction(90)
        cost = 98 - exit_price + (price + exit_price) * Fraction(1, 1000)
        assert Fraction(child.actual_stop_risk) == quantity * (price - 98 + cost)
        assert Fraction(child.cash) == quantity * (price + cost)
        assert child.actual_stop_risk <= child.risk_bound
    with localcontext() as context:
        context.prec = 2
        context.Emax = 1
        context.Emin = -1
        for signal in context.traps:
            context.traps[signal] = True
        assert allocate_grid(result) == allocation


def test_stop_below_first_executable_tick_refuses_basket(basket):
    result = coarse_stop_basket(basket[0], ".1")
    result = replace(
        result,
        plan=replace(result.plan, stop=D(8)),
        intent=replace(result.intent, stop=D(8)),
    )
    allocation = allocate_grid(result)
    assert not allocation.accepted
    assert allocation.reason == "invalid_stop_execution_price"
    assert allocation.children == ()


def test_normal_tick_stop_risk_matches_execution_price(basket):
    allocation = allocate_grid(basket[0])
    assert allocation.accepted
    # Stop 93, 5 bp slippage => 92.9535, rounded down to 92.95.
    exit_price = Fraction(9295, 100)
    for child in allocation.children:
        price, quantity = Fraction(child.limit), Fraction(child.quantity)
        fees = (price + exit_price) * Fraction(1, 1000)
        assert Fraction(child.actual_stop_risk) == quantity * (price - exit_price + fees)
