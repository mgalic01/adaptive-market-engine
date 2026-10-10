from dataclasses import replace
from decimal import Decimal as D
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
    inputs = replace(result.venue_inputs, rules=replace(result.venue_inputs.rules, tick=D(".3")))
    result = replace(result, venue_inputs=inputs)
    allocation = allocate_grid(result)
    assert allocation.accepted
    assert [child.limit for child in allocation.children] == [D("99"), D("97.8"), D("96.9")]
    bound = Fraction(D(".4"))
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
