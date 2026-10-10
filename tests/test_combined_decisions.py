from dataclasses import replace
from decimal import Decimal as D
from fractions import Fraction

import pytest
from test_combined_routing import market

from crypto_grid_bot.combined.decisions import (
    Costs,
    DecisionCoordinator,
    FundingEstimate,
    VenueInputs,
)
from crypto_grid_bot.combined.engine import PortfolioEngine, Quote
from crypto_grid_bot.combined.evidence import Evidence
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.routing import RoutingContext
from crypto_grid_bot.strategy.perception import TrendState


@pytest.fixture
def setup():
    assessment = replace(market(), atr=D(2), extension=D(1))
    rules = VenueRules(D(".001"), D(0), D(1000), D(5), D(".01"))
    costs = Costs(D(".001"), D(".0005"), D(".004"))
    now = assessment.decision_ms
    spot = VenueInputs(rules, costs)
    futures = VenueInputs(rules, costs, FundingEstimate(D(0), now, 28_800_000))
    engine, journal = PortfolioEngine(D(10000)), Evidence()
    coordinator = DecisionCoordinator(engine, journal)
    args = dict(
        opportunity_id="one",
        assessment=assessment,
        routing=RoutingContext(),
        quotes={"BTCUSDT": Quote(D(100), now)},
        spot=spot,
        futures=futures,
        source_refs=("fixture:assessment", "fixture:quote", "fixture:filters-costs-funding"),
    )
    return coordinator, engine, journal, args


def test_spot_preference_records_complete_local_submission_funnel(setup):
    coordinator, engine, journal, args = setup
    result = coordinator.decide(**args)
    assert result.admission.accepted
    assert result.plan.owner == "spot_trend"
    assert len(engine.reservations) == 1
    assert [e.phase for e in journal.events] == [
        "detected",
        "qualified",
        "risk_approved",
        "executable_size",
        "submitted",
    ]
    assert all(e.source_refs == args["source_refs"] for e in journal.events)
    assert dict(journal.events[-1].details)["destination"] == "replay_queue"


def test_only_proven_spot_minimum_failure_enables_futures_fallback(setup):
    coordinator, engine, journal, args = setup
    args["spot"] = replace(args["spot"], rules=replace(args["spot"].rules, min_notional=D(3000)))
    result = coordinator.decide(**args)
    assert result.admission.accepted and result.plan.owner == "futures_trend"
    assert len(engine.reservations) == 1
    assert dict(journal.events[1].details)["spot_refusal"] == "spot_normal_size_below_venue_minimum"


def test_unknown_spot_cannot_fallback_even_if_caller_claims_false(setup):
    coordinator, engine, journal, args = setup
    args.update(spot=None, routing=RoutingContext(spot_executable=False))
    result = coordinator.decide(**args)
    assert result.admission is None
    assert "spot_executability_unknown" in result.qualification.reasons
    assert not journal.events[-1].accepted and engine.reservations == ()


def test_owned_asset_risk_refusal_never_falls_back(setup):
    coordinator, engine, journal, args = setup
    coordinator.decide(**args)
    result = coordinator.decide(**{**args, "opportunity_id": "two"})
    assert not result.admission.accepted
    assert result.admission.reason == "asset_owned"
    assert result.plan.owner == "spot_trend"
    assert len(engine.reservations) == 1


def test_grid_reserves_one_basket_and_returns_three_equal_risk_geometry_levels(setup):
    coordinator, engine, journal, args = setup
    args["assessment"] = replace(
        args["assessment"], daily=TrendState.RANGE, four_hour=TrendState.RANGE
    )
    args["routing"] = RoutingContext(flow_allowed=True)
    result = coordinator.decide(**args)
    assert result.admission.accepted
    assert result.plan.owner == "spot_grid" and len(result.plan.levels) == 3
    assert sum(level.risk_weight for level in result.plan.levels) == 1
    risks = [
        level.risk_weight * Fraction(level.price - result.plan.stop + D(".4"))
        for level in result.plan.levels
    ]
    assert risks[0] == risks[1] == risks[2]
    assert len(engine.reservations) == 1
    assert dict(journal.events[-1].details)["allocation"] == "aggregate_grid_basket"


def test_duplicate_decision_is_idempotent_and_conflict_fails_before_reserving(setup):
    coordinator, engine, journal, args = setup
    first = coordinator.decide(**args)
    count = len(journal.events)
    assert coordinator.decide(**args) == first
    assert len(journal.events) == count and len(engine.reservations) == 1
    with pytest.raises(ValueError, match="conflicting"):
        coordinator.decide(**{**args, "source_refs": ("other",)})


def test_missing_source_references_fail_before_engine_or_evidence_mutation(setup):
    coordinator, engine, journal, args = setup
    with pytest.raises(ValueError, match="source"):
        coordinator.decide(**{**args, "source_refs": ()})
    assert engine.reservations == () and journal.events == ()


def test_future_funding_is_refused_before_submission(setup):
    coordinator, engine, journal, args = setup
    args["routing"] = RoutingContext(spot_trend=False)
    args["futures"] = replace(
        args["futures"],
        funding=FundingEstimate(D(0), args["assessment"].decision_ms + 1, 28_800_000),
    )
    result = coordinator.decide(**args)
    assert result.admission.reason == "funding_unavailable"
    assert journal.events[-1].phase == "risk_approved" and not journal.events[-1].accepted
    assert engine.reservations == ()


def test_understated_complete_cost_refuses_before_reservation(setup):
    coordinator, engine, journal, args = setup
    args["spot"] = replace(args["spot"], costs=Costs(D(".01"), D(".01"), D(".001")))
    result = coordinator.decide(**args)
    assert result.admission is None
    assert "round_trip_cost_understated" in result.qualification.reasons
    assert engine.reservations == ()


def test_zero_complete_grid_cost_cannot_override_positive_execution_costs(setup):
    coordinator, engine, journal, args = setup
    args["assessment"] = replace(
        args["assessment"], daily=TrendState.RANGE, four_hour=TrendState.RANGE
    )
    args["routing"] = RoutingContext(flow_allowed=True)
    args["spot"] = replace(args["spot"], costs=Costs(D(".001"), D(".0005"), D(0)))
    result = coordinator.decide(**args)
    assert result.admission is None
    assert "round_trip_cost_understated" in result.qualification.reasons
    assert engine.reservations == ()


def test_unavailable_assessment_retains_independent_blockers(setup):
    coordinator, engine, journal, args = setup
    args["assessment"] = replace(
        args["assessment"], available=False, reasons=("missing_daily_bar",)
    )
    result = coordinator.decide(**args)
    assert result.admission is None
    assert {"missing_daily_bar", "assessment_unavailable"} <= set(journal.events[-1].reasons)
    assert engine.reservations == ()
