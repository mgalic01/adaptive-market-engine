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
    spot = VenueInputs(rules, costs, quote=Quote(D(100), now))
    futures = VenueInputs(
        rules, costs, FundingEstimate(D(0), now, 28_800_000), quote=Quote(D(100), now)
    )
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


def test_tiny_capital_below_spot_minimum_before_commitments_still_falls_back(setup):
    _, _, _, args = setup
    engine, journal = PortfolioEngine(D(100)), Evidence()
    # Even uncommitted, 0.5% risk of 100 buys about 11.6 of spot notional, under 20.
    args["spot"] = replace(args["spot"], rules=replace(args["spot"].rules, min_notional=D(20)))
    result = DecisionCoordinator(engine, journal).decide(**args)
    assert result.admission.accepted and result.plan.owner == "futures_trend"
    assert len(engine.reservations) == 1
    assert dict(journal.events[1].details)["spot_refusal"] == "spot_normal_size_below_venue_minimum"


def test_spot_cut_below_minimum_by_committed_cash_is_refused_not_moved_to_futures(setup):
    # Owner decision 2026-10-11: committed cash, not the venue minimum, is the cause here.
    coordinator, engine, journal, args = setup
    others = ("ETHUSDT", "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT")
    groups = tuple((symbol, symbol) for symbol in ("BTCUSDT", *others))
    spot = replace(args["spot"], rules=replace(args["spot"].rules, min_notional=D(1100)))
    uncommitted = DecisionCoordinator(PortfolioEngine(D(10000)), Evidence()).decide(
        **{**args, "spot": spot, "groups": groups}
    )
    assert uncommitted.admission.accepted and uncommitted.intent.venue == "spot"
    small = replace(args["spot"], rules=replace(args["spot"].rules, max_qty=D(18)))
    for symbol in others:
        pending = coordinator.decide(
            symbol,
            replace(args["assessment"], symbol=symbol, atr=D("0.5")),
            RoutingContext(),
            {},
            small,
            None,
            args["source_refs"],
            groups=groups,
        )
        assert pending.admission.accepted
    result = coordinator.decide(**{**args, "spot": spot, "groups": groups})
    assert result.plan.owner == "spot_trend" and result.intent.venue == "spot"
    assert not result.admission.accepted
    assert result.admission.reason == "spot_capacity_committed"
    assert result.events[1].phase == "qualified" and result.events[1].details == ()
    assert len(engine.reservations) == len(others)
    assert all(a.intent_id.endswith(":intent:spot") for a in engine.reservations)


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


def test_fallback_uses_its_own_futures_quote_even_if_older_than_spot_quote(setup):
    coordinator, engine, _, args = setup
    now = args["assessment"].decision_ms
    args["spot"] = replace(
        args["spot"],
        quote=Quote(D(100), now),
        rules=replace(args["spot"].rules, min_notional=D(3000)),
    )
    args["futures"] = replace(args["futures"], quote=Quote(D(105), now - 1000))
    args["quotes"] = {}  # no held assets; candidate quotes are venue-specific
    result = coordinator.decide(**args)
    assert result.admission.accepted
    assert result.intent.price == result.plan.reference_price == D(105)
    assert result.plan.quote_ms == now - 1000
    assert result.plan.stop == D(101)
    assert len(engine.reservations) == 1


@pytest.mark.parametrize("quote", [None, Quote(D(100), 0)])
def test_missing_or_stale_selected_venue_quote_refuses_even_with_fresh_symbol_mark(setup, quote):
    coordinator, engine, _, args = setup
    args["routing"] = RoutingContext(spot_trend=False)
    args["futures"] = replace(args["futures"], quote=quote)
    result = coordinator.decide(**args)
    assert result.admission is None
    assert "venue_quote_unavailable" in result.qualification.reasons
    assert engine.reservations == ()


def test_missing_spot_quote_cannot_be_used_as_fallback_proof(setup):
    coordinator, engine, _, args = setup
    args["spot"] = replace(args["spot"], quote=None)
    result = coordinator.decide(**args)
    assert result.admission is None
    assert result.qualification.owner == "spot_trend"
    assert "venue_quote_unavailable" in result.qualification.reasons
    assert engine.reservations == ()


@pytest.mark.parametrize(
    "field,step",
    [
        ("hourly_closed_ms", 3_600_000),
        ("four_hour_closed_ms", 14_400_000),
        ("daily_closed_ms", 86_400_000),
    ],
)
@pytest.mark.parametrize("defect", ["stale", "future", "missing", "boolean"])
def test_source_boundaries_must_be_exactly_due_even_when_available_is_true(
    setup, field, step, defect
):
    coordinator, engine, journal, args = setup
    now = args["assessment"].decision_ms
    bad = {"stale": now - step, "future": now + step, "missing": None, "boolean": True}[defect]
    args["assessment"] = replace(args["assessment"], **{field: bad})
    result = coordinator.decide(**args)
    assert result.admission is None
    assert not result.qualification.allowed
    assert f"{field}_not_due" in result.qualification.reasons
    assert journal.events[-1].phase == "qualified" and not journal.events[-1].accepted
    assert engine.reservations == ()


@pytest.mark.parametrize("defect", ["stale", "future", "missing", "boolean"])
def test_assessment_quote_timestamp_must_be_causal_despite_fresh_venue_quote(setup, defect):
    coordinator, engine, _, args = setup
    now = args["assessment"].decision_ms
    bad = {"stale": now - 3_600_001, "future": now + 1, "missing": None, "boolean": True}[defect]
    args["assessment"] = replace(args["assessment"], quote_ms=bad)
    result = coordinator.decide(**args)
    assert result.admission is None
    assert "assessment_quote_unavailable" in result.qualification.reasons
    assert engine.reservations == ()


def test_intraperiod_decision_uses_latest_due_boundaries_not_decision_timestamp(setup):
    coordinator, engine, _, args = setup
    now = args["assessment"].decision_ms + 37 * 60_000
    args["assessment"] = replace(args["assessment"], decision_ms=now)
    result = coordinator.decide(**args)
    assert result.admission.accepted
    assert len(engine.reservations) == 1


def test_all_missing_sources_preserve_independent_reasons(setup):
    coordinator, engine, _, args = setup
    args["assessment"] = replace(
        args["assessment"], hourly_closed_ms=None, four_hour_closed_ms=None, daily_closed_ms=None
    )
    result = coordinator.decide(**args)
    assert {
        "hourly_closed_ms_not_due",
        "four_hour_closed_ms_not_due",
        "daily_closed_ms_not_due",
    } <= set(result.qualification.reasons)
    assert engine.reservations == ()


def test_futures_candidate_cannot_revalue_existing_spot_inventory(setup):
    from crypto_grid_bot.combined.account import FillEvent

    coordinator, engine, _, args = setup
    args["spot"] = replace(args["spot"], quote=args["quotes"]["BTCUSDT"])
    entry = coordinator.decide(**args)
    now = args["assessment"].decision_ms + 1
    fill = FillEvent("entry", now, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0))
    engine.settle(
        "entry",
        now,
        args["quotes"],
        {"BTCUSDT": args["spot"].rules},
        increases=((entry.intent.intent_id, fill),),
    )
    engine.cancel(entry.intent.intent_id)
    held = {"BTCUSDT": Quote(D(110), now)}
    args.update(
        opportunity_id="other",
        assessment=replace(args["assessment"], decision_ms=now),
        routing=RoutingContext(spot_trend=False),
        quotes=held,
        futures=replace(args["futures"], quote=Quote(D(200), now)),
        position_rules={"BTCUSDT": args["spot"].rules},
    )
    result = coordinator.decide(**args)
    assert result.admission.reason == "asset_owned"
    state = engine.observe(now, {}, args["position_rules"])
    assert state.account.positions[0].mark == D(110)
    assert state.account.equity == D(10010)


def test_unavailable_assessment_retains_independent_blockers(setup):
    coordinator, engine, journal, args = setup
    args["assessment"] = replace(
        args["assessment"], available=False, reasons=("missing_daily_bar",)
    )
    result = coordinator.decide(**args)
    assert result.admission is None
    assert {"missing_daily_bar", "assessment_unavailable"} <= set(journal.events[-1].reasons)
    assert engine.reservations == ()


def test_tick_cost_cannot_be_hidden_by_zero_fee_and_slippage(setup):
    coordinator, engine, _, args = setup
    args["spot"] = replace(
        args["spot"], rules=replace(args["spot"].rules, tick=D(10)), costs=Costs(D(0), D(0), D(0))
    )
    result = coordinator.decide(**args)
    assert result.admission is None
    assert "round_trip_cost_understated" in result.qualification.reasons
    assert engine.reservations == ()


def test_opening_execution_books_admitted_trend_and_filled_evidence(setup):
    coordinator, engine, journal, args = setup
    decision = coordinator.decide(**args)
    result = coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert result.failure is None
    assert result.fill.quantity == decision.admission.quantity
    assert result.fill.price == D("100.05")
    assert engine.held_execution_terms()[0][1] == decision.intent.stop
    assert journal.events[-1].phase == "filled"
    assert (
        coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
        == result
    )
    assert len([event for event in journal.events if event.phase == "filled"]) == 1


def test_opening_execution_does_not_invent_canceled_late_fill(setup):
    coordinator, engine, journal, args = setup
    decision = coordinator.decide(**args)
    engine.cancel(decision.intent.intent_id)
    result = coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert result.failure == "opening_admission_no_longer_active"
    assert result.fill is None
    assert not engine.held_execution_terms()


def test_opening_execution_retains_booked_fill_when_following_mark_fails(setup, monkeypatch):
    coordinator, engine, journal, args = setup
    coordinator.decide(**args)
    original = engine.observe
    calls = 0

    def failing(*a, **kw):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("synthetic after booking")
        return original(*a, **kw)

    monkeypatch.setattr(engine, "observe", failing)
    result = coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert result.failure is not None
    assert result.fill is not None
    assert journal.events[-1].phase == "filled"
    assert (
        coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
        == result
    )
    assert calls == 3


def test_opening_execution_uses_selected_futures_quote(setup):
    coordinator, engine, journal, args = setup
    args["routing"] = RoutingContext(spot_trend=False, spot_grid=False)
    args["futures"] = replace(args["futures"], quote=Quote(D(120), args["assessment"].decision_ms))
    decision = coordinator.decide(**args)
    assert decision.intent.venue == "futures"
    result = coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert result.failure is None
    assert result.fill.price == D("120.06")
    assert engine.held_execution_terms()[0][1] == decision.intent.stop
    assert result.observations[-1].snapshot.account.positions[0].mark == D(120)


def test_opening_execution_refuses_grid_basket(setup):
    coordinator, engine, journal, args = setup
    args["assessment"] = replace(
        args["assessment"], daily=TrendState.RANGE, four_hour=TrendState.RANGE
    )
    args["routing"] = RoutingContext(flow_allowed=True)
    coordinator.decide(**args)
    with pytest.raises(ValueError, match="accepted trend"):
        coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert not engine.held_execution_terms()


def test_opening_execution_cannot_move_to_later_boundary(setup):
    coordinator, engine, journal, args = setup
    coordinator.decide(**args)
    now = args["assessment"].decision_ms + 1
    engine.observe(now, {"BTCUSDT": Quote(D(100), now)}, {"BTCUSDT": args["spot"].rules})
    with pytest.raises(ValueError, match="original decision boundary"):
        coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert not engine.held_execution_terms()


def test_opening_execution_requires_current_held_venue_marks(setup):
    coordinator, engine, journal, args = setup
    coordinator.decide(**args)
    coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    now = args["assessment"].decision_ms + 3_600_000
    assessment = replace(
        args["assessment"], symbol="ETHUSDT", decision_ms=now, quote_ms=now, hourly_closed_ms=now
    )
    spot = replace(args["spot"], quote=Quote(D(100), now))
    second = coordinator.decide(
        "two",
        assessment,
        RoutingContext(),
        args["quotes"],
        spot,
        None,
        args["source_refs"],
        position_rules={"BTCUSDT": spot.rules},
    )
    assert second.admission.accepted
    result = coordinator.execute_opening("two", args["quotes"], {"BTCUSDT": spot.rules})
    assert result.failure == "opening_current_held_market_required"
    assert result.fill is None


@pytest.mark.parametrize("scenario", ["open_low_high_close", "open_high_low_close"])
def test_signal_to_opening_fill_to_intrabar_stop(setup, scenario):
    from test_combined_ohlc_path import bar

    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    coordinator, engine, journal, args = setup
    decision = coordinator.decide(**args)
    opening = coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    assert opening.failure is None
    interval = replace(bar(), open_ms=args["assessment"].decision_ms)
    replay = replay_held_portfolio(
        engine,
        (("BTCUSDT", interval),),
        {"BTCUSDT": args["spot"].rules},
        scenario,
        source_refs=("synthetic:ohlc",),
    )
    assert replay.failure is None
    assert len(replay.fills) == 1
    assert replay.fills[0].side == -1
    assert replay.fills[0].quantity == decision.admission.quantity
    assert not engine.held_execution_terms()
    assert not any(row.snapshot.liquidation for row in replay.observations)
    assert [event.phase for event in journal.events][-2:] == ["submitted", "filled"]


def test_verified_dust_obligation_does_not_block_a_new_trend_opening(setup):
    # Critic M4: unsellable dust keeps its close obligation, but blocks no new asset.
    coordinator, engine, journal, args = setup
    coordinator.decide(**args)
    coordinator.execute_opening("one", args["quotes"], {"BTCUSDT": args["spot"].rules})
    now = args["assessment"].decision_ms + 3_600_000
    quotes = {"BTCUSDT": Quote(D(100), now)}
    unsellable = {"BTCUSDT": replace(args["spot"].rules, min_notional=D(1000000))}
    engine.request_close("BTCUSDT", "spot_trend", 1, reason="trend_reversal")
    assessment = replace(
        args["assessment"], symbol="ETHUSDT", decision_ms=now, quote_ms=now, hourly_closed_ms=now
    )
    spot = replace(args["spot"], quote=Quote(D(100), now))
    second = coordinator.decide(
        "two",
        assessment,
        RoutingContext(),
        quotes,
        spot,
        None,
        args["source_refs"],
        position_rules=unsellable,
    )
    assert second.admission.accepted
    assert engine.close_dust(unsellable) == ("BTCUSDT",)
    result = coordinator.execute_opening("two", quotes, unsellable)
    assert result.failure is None and result.fill is not None
    assert result.fill.symbol == "ETHUSDT"
