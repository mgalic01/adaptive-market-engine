"""Shared event ordering and reservation transfer across the combined wallet."""

from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_combined_risk import intent

from crypto_grid_bot.combined.account import FillEvent, FundingEvent
from crypto_grid_bot.combined.engine import PortfolioEngine, Quote
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.combined.routing import Qualification

RULE = VenueRules(D(".001"), D(0), D(1000), D(5), D(".01"))
RULES = {"BTCUSDT": RULE, "ETHUSDT": RULE}
QUOTES = {"BTCUSDT": Quote(D(100), 0), "ETHUSDT": Quote(D(100), 0)}


def test_preview_validates_normal_capacity_without_reserving_or_restarting():
    engine = PortfolioEngine(D(10000))
    order = intent()
    answer = engine.preview(order, candidate(order), QUOTES, RULES)
    assert answer.accepted
    assert engine.reservations == ()
    assert engine.observe(0, QUOTES, RULES).account.free_cash == 10000
    assert engine.submit(order, candidate(order), QUOTES, RULES).quantity == answer.quantity


def test_venue_candidate_quote_does_not_require_or_populate_a_held_mark():
    engine = PortfolioEngine(D(10000))
    order = intent()
    assert engine.preview(
        order, candidate(order), {}, RULES, candidate_quote=Quote(D(100), 0)
    ).accepted
    stale = replace(candidate(order), decision_ms=3_600_001)
    assert engine.preview(order, stale, {}, RULES).reason == "stale_or_missing_quote"
    assert engine.reservations == ()


def test_candidate_filters_cannot_classify_an_existing_holding_as_dust():
    engine = PortfolioEngine(D(10000))
    order, _, _ = open_partial(engine)
    engine.cancel(order.intent_id)
    engine.observe(2, {"BTCUSDT": Quote(D(10000), 2)}, RULES)
    current = {"BTCUSDT": Quote(D(100), 3)}
    assert engine.observe(3, current, RULES).recovery.close
    future = intent(
        "future",
        owner="futures_trend",
        venue="futures",
        min_notional=D(100000),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    result = engine.preview(
        future,
        replace(candidate(future), decision_ms=3),
        current,
        RULES,
        candidate_quote=Quote(D(101), 3),
        candidate_rules=replace(RULE, min_notional=D(100000)),
    )
    assert result.reason == "asset_owned"
    assert engine.observe(3, {}, RULES).recovery.close


def candidate(order):
    return Qualification(order.symbol, 0, True, order.owner, order.side, D(1), ())


def test_settlement_retains_intermediate_observations_and_duplicate_does_not_append():
    engine = PortfolioEngine(D(10000))
    state = engine.settle("boundary", 0, QUOTES, RULES)
    trace = engine.settlement_observations("boundary")
    assert tuple(row.phase for row in trace) == ("before", "settled")
    assert trace[-1].snapshot == state
    assert engine.settle("boundary", 0, QUOTES, RULES) == state
    assert engine.settlement_observations("boundary") == trace
    assert engine.settlement_observations("missing") == ()


def test_failed_settlement_retains_prefix_and_cannot_be_retried():
    engine = PortfolioEngine(D(10000))
    fill = FillEvent("unknown", 0, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0))
    with pytest.raises(ValueError, match="no recorded admission"):
        engine.settle("failed", 0, QUOTES, RULES, increases=(("absent", fill),))
    prefix = engine.settlement_observations("failed")
    assert tuple(row.phase for row in prefix) == ("before",)
    with pytest.raises(ValueError, match="cannot be retried"):
        engine.settle("failed", 0, QUOTES, RULES)
    assert engine.settlement_observations("failed") == prefix


def test_snapshot_retains_active_and_canceled_execution_obligations():
    engine = PortfolioEngine(D(10000))
    order = intent()
    assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
    active = engine.observe(0, QUOTES, RULES)
    assert active.unresolved_execution == (order.intent_id,)
    engine.cancel(order.intent_id)
    canceled = engine.observe(0, QUOTES, RULES)
    assert canceled.unresolved_execution == active.unresolved_execution
    engine.acknowledge_finality(order.intent_id, source_refs=("synthetic-cancel-final",))
    assert engine.observe(0, QUOTES, RULES).unresolved_execution == ()
    assert canceled.unresolved_execution == (order.intent_id,)  # No retroactive rewrite.


def test_worse_partial_fill_cancels_remainder_and_late_fill_stays_flagged():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("worse-partial", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(150), D(0))
    state = engine.settle("worse", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert "BTCUSDT" in state.close_required
    assert engine.reservations == ()
    late = replace(fill, event_id="late-partial", timestamp_ms=2, price=D(100))
    state = engine.settle("late", 2, QUOTES, RULES, increases=((order.intent_id, late),))
    assert state.account.positions[0].quantity == D(2)
    assert "post_fill_risk_breach" in state.reasons
    assert engine.reservations == ()


def test_stale_held_quote_cancels_remaining_increase():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent(
        "partial-before-stale", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0)
    )
    engine.settle("partial", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    state = engine.observe(3_600_001, {}, RULES)
    assert state.close_required == ("BTCUSDT",)
    assert engine.reservations == ()
    restored = engine.observe(3_600_002, {"BTCUSDT": Quote(D(100), 3_600_002)}, RULES)
    assert restored.close_required == ("BTCUSDT",)
    assert "stale_position_or_missing_filters" in restored.reasons


def test_margin_close_cancels_all_pending_increases_without_drawdown_halt():
    engine = PortfolioEngine(D(10000))
    # Leave planned-cost headroom: this test targets cancellation/identity, not sizing.
    future = intent(
        owner="futures_trend",
        venue="futures",
        side=-1,
        stop=D(102),
        requested_quantity=D(10),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    spot = intent(intent_id="spot", symbol="ETHUSDT")
    engine.submit(future, candidate(future), QUOTES, RULES)
    engine.submit(spot, candidate(spot), QUOTES, RULES)
    f = FillEvent("f", 1, "BTCUSDT", "futures_trend", "futures", -1, D(1), D(100), D(0))
    s = FillEvent("s", 1, "ETHUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0))
    engine.settle(
        "entries", 1, QUOTES, RULES, increases=((future.intent_id, f), (spot.intent_id, s))
    )
    state = engine.observe(2, {"BTCUSDT": Quote(D(9900), 2), "ETHUSDT": Quote(D(10000), 2)}, RULES)
    assert state.account.equity == D(10100)
    assert state.recovery.risk_fraction == 1 and not state.liquidation
    assert "margin_reduction" in state.reasons
    assert engine.reservations == ()


def test_admission_snapshot_includes_futures_collateral_but_not_spot_inventory():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent(
        "margin-entry", 1, "BTCUSDT", "futures_trend", "futures", 1, D(1), D(100), D(0)
    )
    state = engine.settle("margin-batch", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    view = engine._view(state.account, D(1), ())
    assert view.futures_backing == D(10000)
    assert view.free_cash < view.futures_backing


def test_filled_quantity_transfers_from_reservation_to_real_wallet():
    engine = PortfolioEngine(D(10000))
    order = intent()
    admitted = engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("fill1", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(".1"))
    state = engine.settle("batch1", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert state.account.free_cash == D("9899.9")
    assert engine.reservations[0].quantity == admitted.quantity - 1
    duplicate = engine.settle("batch1", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert duplicate == state
    with pytest.raises(ValueError):
        engine.settle("batch1", 1, QUOTES, RULES)
    engine.cancel(order.intent_id)
    assert engine.reservations == ()
    refused = engine.submit(
        replace(order, intent_id="two"), replace(candidate(order), decision_ms=2), QUOTES, RULES
    )
    assert not refused.accepted


def test_funding_precedes_simultaneous_close_and_cannot_be_avoided():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "futures_trend", "futures", 1, D(1), D(100), D(0))
    engine.settle("entrybatch", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    engine.cancel(order.intent_id)
    close = replace(fill, event_id="exit", timestamp_ms=2, side=-1)
    funding = FundingEvent("funding", 2, "BTCUSDT", D(-2))
    state = engine.settle("exitbatch", 2, QUOTES, RULES, funding=(funding,), reductions=(close,))
    trace = engine.settlement_observations("exitbatch")
    assert tuple(row.phase for row in trace) == ("before", "funding", "reduction", "settled")
    assert trace[1].snapshot.account.equity == trace[0].snapshot.account.equity - 2
    assert trace[1].snapshot.account.positions
    assert not trace[2].snapshot.account.positions
    assert state.account.equity == 9998
    assert state.account.funding == -2
    assert state.account.positions == ()


def test_unexpected_worse_fill_is_booked_and_requires_reduction():
    engine = PortfolioEngine(D(10000))
    order = intent()
    answer = engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent(
        "badfill", 1, "BTCUSDT", "spot_trend", "spot", 1, answer.quantity, D(150), D(0)
    )
    quotes = {"BTCUSDT": Quote(D(150), 1), "ETHUSDT": Quote(D(100), 1)}
    state = engine.settle("badbatch", 1, quotes, RULES, increases=((order.intent_id, fill),))
    assert state.account.positions[0].entry_cost == answer.quantity * 150
    assert "BTCUSDT" in state.close_required
    assert "post_fill_risk_breach" in state.reasons


def test_stale_quote_cannot_admit_or_classify_dust_as_flat():
    engine = PortfolioEngine(D(10000))
    order = intent()
    qualified = replace(candidate(order), decision_ms=3_600_001)
    answer = engine.submit(order, qualified, QUOTES, RULES)
    assert not answer.accepted and answer.reason == "stale_or_missing_quote"


def test_cancelled_order_id_cannot_reserve_again():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    engine.cancel(order.intent_id)
    answer = engine.submit(order, candidate(order), QUOTES, RULES)
    assert not answer.accepted and answer.reason == "intent_already_processed"
    assert engine.reservations == ()


def test_funding_liquidation_is_not_erased_by_profitable_same_time_exit():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "futures_trend", "futures", 1, D(1), D(100), D(0))
    engine.settle("entrybatch", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    engine.cancel(order.intent_id)
    close = replace(fill, event_id="exit", timestamp_ms=2, side=-1, price=D(1000))
    funding = FundingEvent("funding", 2, "BTCUSDT", D("-9999.5"))
    result = engine.settle("batch", 2, QUOTES, RULES, funding=(funding,), reductions=(close,))
    assert result.liquidation
    assert result.recovery.max_drawdown > D(".99")


def test_acknowledged_cancel_racing_an_actual_fill_books_and_closes():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    engine.cancel(order.intent_id)
    fill = FillEvent("late", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0))
    result = engine.settle("batch", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert result.account.positions[0].quantity == 1
    assert "BTCUSDT" in result.close_required


def test_duplicate_reduction_is_idempotent_across_batches():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(0))
    engine.settle("entrybatch", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    close = replace(fill, event_id="exit", timestamp_ms=2, side=-1)
    first = engine.settle("exit1", 2, QUOTES, RULES, reductions=(close,))
    second = engine.settle("exit2", 2, QUOTES, RULES, reductions=(close,))
    assert second.account == first.account


def test_execution_integrity_error_permanently_blocks_new_entries():
    engine = PortfolioEngine(D(10000))
    engine.settle("batch", 0, QUOTES, RULES)
    with pytest.raises(ValueError):
        engine.settle("batch", 1, QUOTES, RULES)
    answer = engine.submit(intent(), candidate(intent()), QUOTES, RULES)
    assert not answer.accepted


def test_filled_positions_keep_exit_cost_cash_reserved():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(".1"))
    engine.settle("batch", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    engine.cancel(order.intent_id)
    state = engine.observe(2, QUOTES, RULES)
    assert state.available_cash == D("9899.75205")


def open_partial(engine, *, side=1):
    order = (
        intent()
        if side == 1
        else intent(
            owner="futures_trend",
            venue="futures",
            side=-1,
            stop=D(102),
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
        )
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, order.symbol, order.owner, order.venue, side, D(1), D(100), D(0))
    state = engine.settle("entry", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    return order, fill, state


def test_requested_close_cancels_asset_increases_and_survives_partial_and_missing_prices():
    engine = PortfolioEngine(D(10000))
    order, fill, before = open_partial(engine)
    engine.request_close(order.symbol, order.owner, 1, reason="regime_exit")
    assert engine.reservations == ()
    state = engine.observe(2, {}, RULES)
    assert state.account == before.account
    assert state.close_required == ("BTCUSDT",)
    assert "regime_exit" in state.reasons
    engine.request_close(order.symbol, order.owner, 1, reason="regime_exit")
    state = engine.settle(
        "part",
        3,
        QUOTES,
        RULES,
        reductions=(replace(fill, event_id="part", timestamp_ms=3, side=-1, quantity=D(".5")),),
    )
    assert state.close_required == ("BTCUSDT",)
    state = engine.settle(
        "flat",
        4,
        QUOTES,
        RULES,
        reductions=(replace(fill, event_id="flat", timestamp_ms=4, side=-1, quantity=D(".5")),),
    )
    assert state.close_required == ()
    assert "regime_exit" not in state.reasons


@pytest.mark.parametrize("side,stop,wider", [(1, D(99), D(98)), (-1, D(101), D(102))])
def test_tightened_stop_survives_later_partial_entry_fill(side, stop, wider):
    engine = PortfolioEngine(D(10000))
    order, fill, _ = open_partial(engine, side=side)
    engine.tighten_stop(order.symbol, order.owner, side, stop)
    engine.tighten_stop(order.symbol, order.owner, side, stop)
    engine.settle(
        "more",
        2,
        QUOTES,
        RULES,
        increases=(
            (
                order.intent_id,
                replace(fill, event_id="more", timestamp_ms=2),
            ),
        ),
    )
    with pytest.raises(ValueError, match="widen"):
        engine.tighten_stop(order.symbol, order.owner, side, wider)


@pytest.mark.parametrize("api", ["close", "stop"])
def test_protective_api_rejects_wrong_owner_or_side_without_cancelling_orders(api):
    engine = PortfolioEngine(D(10000))
    order, _, before = open_partial(engine)
    pending = engine.reservations
    for owner, side in (("spot_grid", 1), (order.owner, -1), (order.owner, True)):
        with pytest.raises(ValueError):
            if api == "close":
                engine.request_close(order.symbol, owner, side, reason="exit")
            else:
                engine.tighten_stop(order.symbol, owner, side, D(99))
    assert engine.reservations == pending
    assert engine.observe(2, {}, RULES).account == before.account


def test_tightening_through_observed_mark_requests_close_without_a_fill():
    engine = PortfolioEngine(D(10000))
    order, _, before = open_partial(engine)
    engine.tighten_stop(order.symbol, order.owner, 1, D(101))
    state = engine.observe(2, {}, RULES)
    assert state.account == before.account
    assert state.close_required == (order.symbol,)
    assert engine.reservations == ()


def test_disabling_automatic_recovery_keeps_stop_and_prevents_qualified_restart():
    engine = PortfolioEngine(D(10000), automatic_recovery=False)
    order, fill, _ = open_partial(engine)
    engine.cancel(order.intent_id)
    engine.observe(2, {"BTCUSDT": Quote(D(10000), 2)}, RULES)
    stopped = engine.observe(3, {"BTCUSDT": Quote(D(100), 3)}, RULES)
    assert stopped.close_required == (order.symbol,)
    closed = engine.settle(
        "flat", 4, {}, RULES, reductions=(replace(fill, event_id="exit", timestamp_ms=4, side=-1),)
    )
    now = 86_400_004
    fresh = {symbol: Quote(D(100), now) for symbol in QUOTES}
    other = intent("other", "ETHUSDT")
    result = engine.submit(other, replace(candidate(other), decision_ms=now), fresh, RULES)
    assert not result.accepted
    state = engine.observe(now, fresh, RULES, qualified=True)
    assert state.recovery.risk_fraction == 0
    assert state.recovery.max_drawdown == closed.recovery.max_drawdown


def test_automatic_recovery_option_requires_a_boolean():
    with pytest.raises(ValueError):
        PortfolioEngine(D(10000), automatic_recovery=0)


def test_explicit_close_keeps_dust_owned_without_blocking_an_unrelated_asset():
    engine = PortfolioEngine(D(10000))
    order, fill, _ = open_partial(engine)
    engine.request_close(order.symbol, order.owner, 1, reason="range_exit")
    state = engine.settle(
        "dust",
        2,
        QUOTES,
        RULES,
        reductions=(replace(fill, event_id="dust", timestamp_ms=2, side=-1, quantity=D(".999")),),
    )
    assert state.account.positions[0].quantity == D(".001")
    assert state.close_required == (order.symbol,)
    assert "range_exit" in state.reasons
    engine.acknowledge_finality(order.intent_id, source_refs=("synthetic:final",))
    other = intent("other", "ETHUSDT")
    assert engine.submit(other, replace(candidate(other), decision_ms=3), QUOTES, RULES).accepted


def test_pending_only_close_cancels_only_its_asset_and_late_fill_is_honestly_booked():
    engine = PortfolioEngine(D(10000))
    # Leave planned-cost headroom: this test targets cancellation/identity, not sizing.
    order, other = intent(requested_quantity=D(10)), intent("other", "ETHUSDT")
    engine.submit(order, candidate(order), QUOTES, RULES)
    engine.submit(other, candidate(other), QUOTES, RULES)
    engine.request_close(order.symbol, order.owner, 1, reason="signal_lost")
    assert [a.intent_id for a in engine.reservations] == [other.intent_id]
    fill = FillEvent("late", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(0))
    state = engine.settle("late", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert state.account.positions[0].quantity == 1
    assert state.close_required == (order.symbol,)


@pytest.mark.parametrize("stop", [D("NaN"), D("Infinity"), D(0), D(-1)])
def test_invalid_tightening_does_not_release_reservations_or_change_account(stop):
    engine = PortfolioEngine(D(10000))
    order, _, before = open_partial(engine)
    pending = engine.reservations
    with pytest.raises(ValueError):
        engine.tighten_stop(order.symbol, order.owner, 1, stop)
    assert engine.reservations == pending
    assert engine.observe(2, {}, RULES).account == before.account


@pytest.mark.parametrize("automatic_recovery", [True, False])
def test_pre_exit_liquidation_at_new_mark_cannot_be_hidden_by_close(automatic_recovery):
    engine = PortfolioEngine(D(10000), automatic_recovery=automatic_recovery)
    order = intent(
        owner="futures_trend",
        venue="futures",
        side=-1,
        stop=D(102),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    answer = engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent(
        "short", 1, "BTCUSDT", "futures_trend", "futures", -1, answer.quantity, D(100), D(0)
    )
    engine.settle("open", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    quote = {"BTCUSDT": Quote(D(595), 2)}
    close = replace(fill, event_id="close", timestamp_ms=2, side=1, price=D(595))
    result = engine.settle("close", 2, quote, RULES, reductions=(close,))
    assert result.liquidation


def test_verified_dust_preserves_ownership_without_blocking_other_asset_recovery():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, "BTCUSDT", "spot_trend", "spot", 1, D(1), D(100), D(3000))
    engine.settle("open", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    close = replace(fill, event_id="close", timestamp_ms=2, side=-1, quantity=D(".999"), fee=D(0))
    engine.settle("close", 2, QUOTES, RULES, reductions=(close,))
    engine.acknowledge_finality(order.intent_id, source_refs=("sim:cancel:dust",))
    engine.observe(2, QUOTES, RULES)
    now = 86_400_002
    quotes = {symbol: Quote(D(100), now) for symbol in QUOTES}
    other = intent("eth", "ETHUSDT")
    preview = engine.preview(other, replace(candidate(other), decision_ms=now), quotes, RULES)
    assert preview.accepted
    assert engine.reservations == ()
    assert engine.observe(now, quotes, RULES).recovery.risk_fraction == 0
    admitted = engine.submit(other, replace(candidate(other), decision_ms=now), quotes, RULES)
    assert admitted.accepted
    state = engine.observe(now, quotes, RULES)
    assert state.recovery.risk_fraction == D(".25")
    assert state.account.positions[0].quantity == D(".001")


def test_engine_reserves_verified_tick_and_held_exit_cost():
    engine = PortfolioEngine(D(10000))
    order = intent(fee_rate=D(0), slippage_rate=D(0), tick=D(10))
    rules = {"BTCUSDT": replace(RULE, tick=D(10))}
    answer = engine.submit(order, candidate(order), QUOTES, rules)
    assert answer.quantity == 5
    assert answer.risk == 50
    fill = FillEvent("tick-fill", 1, "BTCUSDT", "spot_trend", "spot", 1, D(5), D(100), D(0))
    state = engine.settle("tick-batch", 1, QUOTES, rules, increases=((order.intent_id, fill),))
    assert state.available_cash == 9460
    assert engine._view(state.account, D(1), ()).exposures[0].stop_risk == 50


def test_engine_refuses_explicit_tick_mismatch():
    engine = PortfolioEngine(D(10000))
    order = intent(tick=D(".01"))
    with pytest.raises(ValueError, match="venue rules"):
        engine.submit(order, candidate(order), QUOTES, {"BTCUSDT": replace(RULE, tick=D(10))})
    assert engine.reservations == ()


@pytest.mark.parametrize("side,stop,entry", [(1, "98", "110"), (-1, "102", "90")])
def test_rounded_entry_bound_and_authoritative_held_tick(side, stop, entry):
    engine = PortfolioEngine(D(10000))
    order = intent(
        side=side,
        stop=D(stop),
        venue="futures",
        owner="futures_trend",
        fee_rate=D(0),
        slippage_rate=D(".001"),
        tick=D(10),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
    )
    rules = {"BTCUSDT": replace(RULE, tick=D(10))}
    answer = engine.submit(order, candidate(order), QUOTES, rules)
    assert answer.accepted
    fill = FillEvent(
        "rounded", 1, "BTCUSDT", "futures_trend", "futures", side, D(1), D(entry), D(0)
    )
    state = engine.settle("rounded-batch", 1, QUOTES, rules, increases=((order.intent_id, fill),))
    assert "post_fill_risk_breach" not in state.reasons
    assert engine._view(state.account, D(1), ()).exposures[0].stop_risk == 10
    # Held rules update the held exit; candidate filters cannot override them.
    engine.observe(2, QUOTES, {"BTCUSDT": replace(RULE, tick=D(20))})
    expected = D(20)
    assert engine._view(state.account, D(1), ()).exposures[0].stop_risk == expected


def test_tick_aware_engine_settlement_ignores_restrictive_decimal_context():
    from decimal import localcontext

    order = intent(fee_rate=D(0), slippage_rate=D(0), tick=D(10))
    rules = {"BTCUSDT": replace(RULE, tick=D(10))}
    engine = PortfolioEngine(D(10000))
    qualification = candidate(order)
    fill = FillEvent("context-fill", 1, "BTCUSDT", "spot_trend", "spot", 1, D(5), D(100), D(0))
    with localcontext() as context:
        context.prec = 2
        context.Emax = 1
        context.Emin = -1
        for signal in context.traps:
            context.traps[signal] = True
        answer = engine.submit(order, qualification, QUOTES, rules)
        state = engine.settle(
            "context-batch", 1, QUOTES, rules, increases=((order.intent_id, fill),)
        )
    assert answer.quantity == 5
    assert state.available_cash == 9460


@pytest.mark.parametrize("replacement", ["grid", "futures", "opposite", "same"])
def test_canceled_remainder_quarantines_symbol_before_new_owner_can_fill(replacement):
    engine = PortfolioEngine(D(10000))
    old = intent()
    if replacement == "opposite":
        old = replace(
            old,
            owner="futures_trend",
            venue="futures",
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
        )
    engine.submit(old, candidate(old), QUOTES, RULES)
    engine.cancel(old.intent_id)
    new = replace(old, intent_id="replacement")
    if replacement == "grid":
        new = replace(new, owner="spot_grid")
    elif replacement == "futures":
        new = replace(
            new,
            owner="futures_trend",
            venue="futures",
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
        )
    elif replacement == "opposite":
        new = replace(new, side=-1, stop=D(102))
    answer = engine.submit(new, candidate(new), QUOTES, RULES)
    assert not answer.accepted
    assert answer.reason == "canceled_fill_finality_pending"
    late = FillEvent(
        "late-owner", 1, old.symbol, old.owner, old.venue, old.side, D(1), D(100), D(0)
    )
    state = engine.settle("late-owner-batch", 1, QUOTES, RULES, increases=((old.intent_id, late),))
    assert state.account.positions[0].owner == old.owner
    assert state.account.positions[0].quantity == old.side
    assert state.reasons.count("post_fill_risk_breach") == 1
    assert engine.observe(1, QUOTES, RULES).reasons == state.reasons


def test_cancel_finality_requires_evidence_and_preserves_conflicting_fill_identity():
    engine = PortfolioEngine(D(10000))
    old = intent()
    engine.submit(old, candidate(old), QUOTES, RULES)
    with pytest.raises(ValueError):
        engine.acknowledge_finality(old.intent_id, source_refs=("sim:cancel:one",))
    engine.cancel(old.intent_id)
    for refs in ((), ("",), ["sim:cancel:one"]):
        with pytest.raises(ValueError):
            engine.acknowledge_finality(old.intent_id, source_refs=refs)
    engine.acknowledge_finality(old.intent_id, source_refs=("sim:cancel:one",))
    engine.acknowledge_finality(old.intent_id, source_refs=("sim:cancel:one",))
    replacement = intent("new", owner="spot_grid")
    assert engine.submit(replacement, candidate(replacement), QUOTES, RULES).accepted
    new_fill = FillEvent("new-fill", 1, old.symbol, "spot_grid", "spot", 1, D(1), D(100), D(0))
    engine.settle(
        "new-fill-batch", 1, QUOTES, RULES, increases=((replacement.intent_id, new_fill),)
    )
    late = replace(new_fill, event_id="contradiction", owner=old.owner, timestamp_ms=2)
    with pytest.raises(ValueError, match="contradicts acknowledged finality"):
        engine.settle("false-finality", 2, QUOTES, RULES, increases=((old.intent_id, late),))
    assert "execution_integrity_failure" in engine.observe(2, QUOTES, RULES).reasons


@pytest.mark.parametrize("dust", [D(0), D(".001")])
def test_recovery_cooldown_waits_for_canceled_remainder_finality(dust):
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(3000))
    state = engine.settle("open", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert state.recovery.state == "Closing"
    close = replace(fill, event_id="close", timestamp_ms=2, side=-1, quantity=D(1) - dust, fee=D(0))
    state = engine.settle("close", 2, QUOTES, RULES, reductions=(close,))
    assert state.recovery.state == "Closing"
    now = 86_400_002
    quotes = {symbol: Quote(D(100), now) for symbol in QUOTES}
    other = intent("eth", "ETHUSDT")
    assert not engine.submit(
        other, replace(candidate(other), decision_ms=now), quotes, RULES
    ).accepted
    assert engine.observe(now, quotes, RULES).recovery.state == "Closing"
    engine.acknowledge_finality(order.intent_id, source_refs=("sim:cancel:complete",))
    assert engine.observe(now, quotes, RULES).recovery.state == "Cooldown"
    other = replace(other, intent_id="eth-during-cooldown")
    assert not engine.submit(
        other, replace(candidate(other), decision_ms=now), quotes, RULES
    ).accepted
    now += 86_400_000
    quotes = {symbol: Quote(D(100), now) for symbol in QUOTES}
    other = replace(other, intent_id="eth-after-cooldown")
    assert engine.submit(other, replace(candidate(other), decision_ms=now), quotes, RULES).accepted


def test_fully_settled_late_remainder_needs_no_cancel_finality_for_recovery():
    engine = PortfolioEngine(D(10000))
    order = intent()
    admission = engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent("entry", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(3000))
    engine.settle("open", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    close = replace(fill, event_id="close", timestamp_ms=2, side=-1, fee=D(0))
    assert engine.settle("close", 2, QUOTES, RULES, reductions=(close,)).recovery.state == "Closing"
    late = replace(
        fill, event_id="late", timestamp_ms=3, quantity=admission.quantity - D(1), fee=D(0)
    )
    state = engine.settle("late", 3, QUOTES, RULES, increases=((order.intent_id, late),))
    assert state.recovery.state == "Closing"
    close_late = replace(late, event_id="close-late", timestamp_ms=4, side=-1)
    state = engine.settle("close-late", 4, QUOTES, RULES, reductions=(close_late,))
    assert state.recovery.state == "Cooldown"
    assert engine.finality_evidence == ()


@pytest.mark.parametrize("same_batch", [True, False])
@pytest.mark.parametrize("conflict", ["role", "admission"])
def test_duplicate_fill_rejects_changed_role_or_admission_and_retains_prefix(same_batch, conflict):
    engine = PortfolioEngine(D(10000))
    # Leave planned-cost headroom: this test targets cancellation/identity, not sizing.
    order = intent(requested_quantity=D(10))
    other = intent("eth-pending", "ETHUSDT")
    assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
    assert engine.submit(other, candidate(other), QUOTES, RULES).accepted
    fill = FillEvent("entry", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(0))
    if conflict == "role":
        engine.settle("entry", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
        event = replace(fill, event_id="close", timestamp_ms=2, side=-1, quantity=D(".5"))
        prefix = {"reductions": (event,)}
        duplicate = ((order.intent_id, event),)
        expected_quantity, expected_cash = D(".5"), D(9950)
    else:
        event = fill
        prefix = {"increases": ((order.intent_id, event),)}
        duplicate = ((other.intent_id, event),)
        expected_quantity, expected_cash = D(1), D(9900)
    if same_batch:
        payload = dict(prefix)
        payload["increases"] = payload.get("increases", ()) + duplicate
    else:
        engine.settle("prefix", event.timestamp_ms, QUOTES, RULES, **prefix)
        payload = {"increases": duplicate}
    with pytest.raises(ValueError, match="conflicting fill ID"):
        engine.settle("conflict", event.timestamp_ms, QUOTES, RULES, **payload)
    state = engine.observe(event.timestamp_ms, QUOTES, RULES)
    assert state.account.positions[0].quantity == expected_quantity
    assert state.account.free_cash == expected_cash
    assert "execution_integrity_failure" in state.reasons
    assert state.recovery.state == "Terminal"
    assert engine.reservations == ()


def test_duplicate_increase_cannot_be_replayed_as_reduction():
    engine = PortfolioEngine(D(10000))
    order, fill, first = open_partial(engine)
    with pytest.raises(ValueError, match="conflicting fill ID"):
        engine.settle("wrong-role", 1, QUOTES, RULES, reductions=(fill,))
    state = engine.observe(1, QUOTES, RULES)
    assert state.account == first.account
    assert "execution_integrity_failure" in state.reasons
    assert engine.reservations == ()


@pytest.mark.parametrize("role", ["increase", "reduction"])
def test_same_fill_role_and_admission_remain_idempotent_within_and_across_batches(role):
    engine = PortfolioEngine(D(10000))
    order = intent()
    assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
    fill = FillEvent("entry", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(0))
    if role == "increase":
        payload = {"increases": ((order.intent_id, fill), (order.intent_id, fill))}
        expected_quantity = D(1)
    else:
        engine.settle("entry", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
        fill = replace(fill, event_id="close", timestamp_ms=2, side=-1, quantity=D(".5"))
        payload = {"reductions": (fill, fill)}
        expected_quantity = D(".5")
    first = engine.settle("first", fill.timestamp_ms, QUOTES, RULES, **payload)
    reservations = engine.reservations
    same = engine.settle("first", fill.timestamp_ms, QUOTES, RULES, **payload)
    across = engine.settle("retry", fill.timestamp_ms, QUOTES, RULES, **payload)
    assert first == same == across
    assert across.account.positions[0].quantity == expected_quantity
    assert engine.reservations == reservations
    assert "execution_integrity_failure" not in across.reasons


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("owner", ["spot_trend", "spot_grid"])
def test_canceled_unfinalized_remainder_blocks_all_new_asset_increases(partial, owner):
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    if partial:
        fill = FillEvent(
            "partial", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(0)
        )
        engine.settle("partial", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    engine.cancel(order.intent_id)
    other = intent("other", "ETHUSDT", owner=owner)
    qualification = replace(candidate(other), decision_ms=2)
    assert (
        engine.preview(other, qualification, QUOTES, RULES).reason
        == "canceled_fill_finality_pending"
    )
    assert (
        engine.submit(other, qualification, QUOTES, RULES).reason
        == "canceled_fill_finality_pending"
    )
    assert engine.reservations == ()
    if partial:
        close = replace(fill, event_id="close", timestamp_ms=2, side=-1)
        state = engine.settle("close", 2, QUOTES, RULES, reductions=(close,))
        assert state.account.positions == ()
    engine.acknowledge_finality(order.intent_id, source_refs=("synthetic:final",))
    assert engine.submit(other, qualification, QUOTES, RULES).accepted


@pytest.mark.parametrize(
    "side,mark,minimum,slip,tick,expected",
    [
        (-1, "9.99", "10", "0", "1", "Closing"),
        (1, "10.1", "10.05", "0", "1", "Cooldown"),
        (1, "10", "10", ".01", ".01", "Cooldown"),
    ],
)
def test_recovery_dust_uses_held_side_slippage_and_venue_tick(
    side, mark, minimum, slip, tick, expected
):
    engine = PortfolioEngine(D(10000))
    order = (
        intent(slippage_rate=D(slip))
        if side == 1
        else intent(
            owner="futures_trend",
            venue="futures",
            side=-1,
            stop=D(102),
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
            slippage_rate=D(slip),
        )
    )
    engine.submit(order, candidate(order), QUOTES, RULES)
    fill = FillEvent(
        "entry", 1, order.symbol, order.owner, order.venue, side, D(1), D(100), D(4000)
    )
    engine.settle("open", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    engine.acknowledge_finality(order.intent_id, source_refs=("synthetic:final",))
    quotes = {**QUOTES, "BTCUSDT": Quote(D(mark), 2)}
    rules = {**RULES, "BTCUSDT": replace(RULE, tick=D(tick), min_notional=D(minimum))}
    state = engine.observe(2, quotes, rules)
    assert state.recovery.state == expected
    other = intent("other", "ETHUSDT", slippage_rate=D(0))
    preview = engine.preview(other, replace(candidate(other), decision_ms=2), quotes, rules)
    assert preview.accepted == (expected == "Cooldown")


def test_fully_settled_canceled_remainder_releases_global_block_after_protective_close():
    engine = PortfolioEngine(D(10000))
    order = intent()
    admission = engine.submit(order, candidate(order), QUOTES, RULES)
    engine.cancel(order.intent_id)
    fill = FillEvent(
        "late", 1, order.symbol, order.owner, order.venue, 1, admission.quantity, D(100), D(0)
    )
    state = engine.settle("late", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert state.close_required == (order.symbol,)
    other = intent("other", "ETHUSDT")
    qualification = replace(candidate(other), decision_ms=2)
    assert (
        engine.preview(other, qualification, QUOTES, RULES).reason == "protective_reduction_pending"
    )
    close = replace(fill, event_id="close", timestamp_ms=2, side=-1)
    engine.settle("close", 2, QUOTES, RULES, reductions=(close,))
    assert engine.finality_evidence == ()
    assert engine.submit(other, qualification, QUOTES, RULES).accepted


def cap_scenario(cap, *, canceled=False):
    symbols = (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "LINKUSDT",
        "AVAXUSDT",
        "DOTUSDT",
    )
    quantities, stop = {
        "asset_risk": ([1, 10], "95"),
        "old_asset_risk": ([10, 1], "95"),
        "asset_gross": ([1, 20], "99"),
        "risk": ([9] * 6 + [6], "95"),
        "gross": ([18] * 8 + [16], "99.9"),
        "correlation": ([16] * 5, "99.9"),
    }[cap]
    symbols = symbols[: len(quantities)]
    quotes = {symbol: Quote(D(100), 0) for symbol in symbols}
    rules = {symbol: RULE for symbol in symbols}
    groups = tuple((symbol, symbol if cap == "gross" else "common") for symbol in symbols)
    engine = PortfolioEngine(D(10000))
    orders, fills = [], []
    for symbol, quantity in zip(symbols, quantities, strict=True):
        order = intent(
            symbol,
            symbol,
            owner="futures_trend",
            venue="futures",
            stop=D(stop),
            requested_quantity=D(quantity),
            fee_rate=D(0),
            slippage_rate=D(0),
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
            correlation_group=dict(groups)[symbol],
        )
        answer = engine.submit(order, candidate(order), quotes, rules, groups)
        assert answer.accepted and answer.quantity == quantity
        orders.append(order)
        fills.append(
            FillEvent(symbol, 1, symbol, order.owner, order.venue, 1, D(quantity), D(100), D(0))
        )
    prefix = len(orders) - (2 if canceled else 1)
    state = engine.settle(
        "prefix",
        1,
        quotes,
        rules,
        increases=tuple(
            (o.intent_id, f) for o, f in zip(orders[:prefix], fills[:prefix], strict=True)
        ),
    )
    assert state.close_required == ()
    if canceled:
        engine.cancel(orders[-2].intent_id)
    return engine, orders, fills, quotes, rules, groups


@pytest.mark.parametrize("cap", ["asset_risk", "asset_gross", "risk", "gross", "correlation"])
def test_expected_price_fill_rechecks_current_equity_caps(cap):
    engine, orders, fills, quotes, rules, _ = cap_scenario(cap)
    loss = FundingEvent("funding-loss", 2, orders[0].symbol, D(-500))
    fill = replace(fills[-1], timestamp_ms=2)
    state = engine.settle(
        "after-decay", 2, quotes, rules, funding=(loss,), increases=((orders[-1].intent_id, fill),)
    )
    assert state.account.equity == 9500
    assert orders[-1].symbol in state.close_required
    assert "post_fill_risk_breach" in state.reasons
    assert engine.reservations == ()
    if cap in {"risk", "gross", "correlation"}:
        assert set(state.close_required) == {p.symbol for p in state.account.positions}
    closes = tuple(
        replace(f, event_id=f"close-{f.event_id}", timestamp_ms=3, side=-1) for f in fills
    )
    assert engine.settle("protect", 3, quotes, rules, reductions=closes).account.positions == ()


def test_post_fill_caps_include_canceled_unfinalized_potential_fills():
    engine, orders, fills, quotes, rules, _ = cap_scenario("risk", canceled=True)
    state = engine.settle(
        "after-decay",
        2,
        quotes,
        rules,
        funding=(FundingEvent("loss", 2, orders[0].symbol, D(-500)),),
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    assert "post_fill_risk_breach" in state.reasons
    assert engine.finality_evidence == ()


@pytest.mark.parametrize("partial", [False, True])
def test_exact_cap_fee_free_fill_does_not_double_count_remaining_reservation(partial):
    engine = PortfolioEngine(D(10000))
    order = intent(requested_quantity=D(20), fee_rate=D(0), slippage_rate=D(0))
    answer = engine.submit(order, candidate(order), QUOTES, RULES)
    assert answer.quantity == 20
    fill = FillEvent(
        "fill",
        1,
        order.symbol,
        order.owner,
        order.venue,
        1,
        D(1) if partial else D(20),
        D(100),
        D(0),
    )
    state = engine.settle("fill", 1, QUOTES, RULES, increases=((order.intent_id, fill),))
    assert "post_fill_risk_breach" not in state.reasons and state.close_required == ()
    if partial:
        assert engine.reservations[0].quantity == 19
    else:
        assert engine.reservations == ()


def test_post_fill_recheck_marks_preexisting_overlimit_asset_for_close():
    engine, orders, fills, quotes, rules, _ = cap_scenario("old_asset_risk")
    state = engine.settle(
        "after-decay",
        2,
        quotes,
        rules,
        funding=(FundingEvent("loss", 2, orders[0].symbol, D(-500)),),
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    # Funding now cancels increases immediately: the later supplied fill is still
    # booked, but it is a late canceled execution and must also be closed.
    assert set(state.close_required) == {order.symbol for order in orders}
    assert {"portfolio_cap_reduction", "post_fill_risk_breach"} <= set(state.reasons)


def test_duplicate_submit_cannot_replace_retained_authoritative_groups():
    engine, orders, fills, quotes, rules, groups = cap_scenario("gross")
    conflicting = tuple((symbol, "common") for symbol, _ in groups)
    answer = engine.submit(
        orders[0], replace(candidate(orders[0]), decision_ms=1), quotes, rules, conflicting
    )
    assert answer.reason == "intent_already_processed"
    state = engine.settle(
        "last",
        2,
        quotes,
        rules,
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    assert state.close_required == () and "post_fill_risk_breach" not in state.reasons


def test_post_fill_recheck_uses_extended_entry_half_risk_multiplier():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        stop=D(95),
        requested_quantity=D(5),
        fee_rate=D(0),
        slippage_rate=D(0),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28_800_000,
        risk_multiplier=D(".5"),
    )
    qualification = replace(candidate(order), risk_multiplier=D(".5"))
    admission = engine.submit(order, qualification, QUOTES, RULES)
    assert admission.quantity == 5
    first = FillEvent("partial", 1, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(0))
    state = engine.settle("partial", 1, QUOTES, RULES, increases=((order.intent_id, first),))
    assert state.close_required == ()
    rest = replace(first, event_id="rest", timestamp_ms=2, quantity=D(4))
    state = engine.settle(
        "rest",
        2,
        QUOTES,
        RULES,
        funding=(FundingEvent("loss", 2, order.symbol, D(-500)),),
        increases=((order.intent_id, rest),),
    )
    assert state.close_required == (order.symbol,)


def test_finality_excludes_canceled_remainder_from_post_fill_risk_totals():
    engine, orders, fills, quotes, rules, _ = cap_scenario("risk", canceled=True)
    engine.acknowledge_finality(orders[-2].intent_id, source_refs=("synthetic:final",))
    state = engine.settle(
        "after-decay",
        2,
        quotes,
        rules,
        funding=(FundingEvent("loss", 2, orders[0].symbol, D(-500)),),
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    assert state.close_required == () and "post_fill_risk_breach" not in state.reasons


@pytest.mark.parametrize("event_kind", ["funding", "quote", "reduction_fee"])
def test_nonincrease_events_enforce_current_portfolio_caps(event_kind):
    cap = "old_asset_risk" if event_kind == "reduction_fee" else "asset_risk"
    engine, orders, fills, quotes, rules, _ = cap_scenario(cap)
    engine.settle(
        "last",
        2,
        quotes,
        rules,
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    if event_kind == "funding":
        state = engine.settle(
            "funding-only",
            3,
            quotes,
            rules,
            funding=(FundingEvent("loss", 3, orders[0].symbol, D(-500)),),
        )
        affected = orders[-1].symbol
    elif event_kind == "quote":
        quotes = {**quotes, orders[-1].symbol: Quote(D(101), 3)}
        state = engine.observe(3, quotes, rules)
        affected = orders[-1].symbol
    else:
        close = replace(fills[-1], event_id="expensive-close", timestamp_ms=3, side=-1, fee=D(500))
        state = engine.settle("reduction-only", 3, quotes, rules, reductions=(close,))
        affected = orders[0].symbol
    assert affected in state.close_required
    assert "portfolio_cap_reduction" in state.reasons
    assert "post_fill_risk_breach" not in state.reasons


def test_transient_funding_cap_breach_is_not_erased_by_later_cashflow():
    engine, orders, fills, quotes, rules, _ = cap_scenario("asset_risk")
    engine.settle(
        "last",
        2,
        quotes,
        rules,
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    state = engine.settle(
        "funding-only",
        3,
        quotes,
        rules,
        funding=(
            FundingEvent("loss", 3, orders[0].symbol, D(-500)),
            FundingEvent("restore", 3, orders[0].symbol, D(500)),
        ),
    )
    assert state.account.equity == 10000
    assert orders[-1].symbol in state.close_required
    assert "portfolio_cap_reduction" in state.reasons


def test_pending_close_reason_survives_observation_and_repeated_disposition_before_late_fill():
    engine = PortfolioEngine(D(10000))
    order = intent()
    engine.submit(order, candidate(order), QUOTES, RULES)
    engine.request_close(order.symbol, order.owner, order.side, reason="trend_reversal")
    engine.observe(1, QUOTES, RULES)
    engine.request_close(order.symbol, order.owner, order.side, reason="regime_exit")
    late = FillEvent("late", 2, order.symbol, order.owner, order.venue, 1, D(1), D(100), D(0))
    state = engine.settle("late", 2, QUOTES, RULES, increases=((order.intent_id, late),))
    assert state.close_required == (order.symbol,)
    assert {"trend_reversal", "regime_exit", "post_fill_risk_breach"} <= set(state.reasons)
    partial = replace(late, event_id="partial-close", timestamp_ms=3, side=-1, quantity=D(".5"))
    state = engine.settle("partial-close", 3, QUOTES, RULES, reductions=(partial,))
    assert {"trend_reversal", "regime_exit"} <= set(state.reasons)


def test_pending_close_reason_is_not_inherited_by_new_admission_after_finality():
    engine = PortfolioEngine(D(10000))
    old = intent()
    engine.submit(old, candidate(old), QUOTES, RULES)
    engine.request_close(old.symbol, old.owner, old.side, reason="old_reversal")
    engine.acknowledge_finality(old.intent_id, source_refs=("synthetic:final",))
    new = replace(old, intent_id="new")
    engine.submit(new, candidate(new), QUOTES, RULES)
    fill = FillEvent("new-fill", 1, new.symbol, new.owner, new.venue, 1, D(1), D(100), D(0))
    state = engine.settle("new-fill", 1, QUOTES, RULES, increases=((new.intent_id, fill),))
    assert "old_reversal" not in state.reasons


@pytest.mark.parametrize("cause", ["quote", "funding"])
def test_routine_cap_reduction_is_not_replay_engineering_failure(cause):
    from crypto_grid_bot.combined.replay_events import SettledBatch, replay_events

    engine, orders, fills, quotes, rules, _ = cap_scenario("asset_risk")
    engine.settle(
        "last",
        2,
        quotes,
        rules,
        increases=((orders[-1].intent_id, replace(fills[-1], timestamp_ms=2)),),
    )
    if cause == "quote":
        quotes = {**quotes, orders[-1].symbol: Quote(D(101), 3)}
        funding = ()
    else:
        funding = (FundingEvent("loss", 3, orders[0].symbol, D(-500)),)
    close = replace(
        fills[-1], event_id="close", timestamp_ms=4, side=-1, price=quotes[orders[-1].symbol].price
    )
    result = replay_events(
        engine,
        (
            SettledBatch(
                "valuation",
                3,
                tuple(quotes.items()),
                tuple(rules.items()),
                funding=funding,
                source_refs=("synthetic:valuation",),
            ),
            SettledBatch(
                "reduction",
                4,
                tuple(quotes.items()),
                tuple(rules.items()),
                reductions=(close,),
                source_refs=("synthetic:reduction",),
            ),
        ),
    )
    assert result.failure is None
    assert "portfolio_cap_reduction" in result.snapshots[0].snapshot.reasons
    assert "post_fill_risk_breach" not in result.snapshots[0].snapshot.reasons
    assert result.snapshots[-1].snapshot.close_required == ()


def test_pending_reversal_survives_full_close_before_late_remainder_fill():
    engine = PortfolioEngine(D(10000))
    order, first, _ = open_partial(engine)
    engine.request_close(order.symbol, order.owner, order.side, reason="trend_reversal")
    close = replace(first, event_id="close", timestamp_ms=2, side=-1)
    state = engine.settle("close", 2, QUOTES, RULES, reductions=(close,))
    assert state.account.positions == () and state.close_required == ()
    late = replace(first, event_id="late", timestamp_ms=3)
    state = engine.settle("late", 3, QUOTES, RULES, increases=((order.intent_id, late),))
    assert state.close_required == (order.symbol,)
    assert "trend_reversal" in state.reasons


@pytest.mark.parametrize("partial", [False, True])
def test_planned_fee_paying_cap_entry_remains_accepted_after_settlement(partial):
    engine = PortfolioEngine(D(10000))
    order = intent(stop=D(99), fee_rate=D(".001"), slippage_rate=D(0))
    admission = engine.submit(order, candidate(order), QUOTES, RULES)
    assert admission.accepted
    quantities = (admission.quantity / 2,) * 2 if partial else (admission.quantity,)
    for index, quantity in enumerate(quantities, 1):
        fill = FillEvent(
            str(index),
            index,
            order.symbol,
            order.owner,
            order.venue,
            order.side,
            quantity,
            D(100),
            quantity * D(".1"),
        )
        state = engine.settle(
            str(index), index, QUOTES, RULES, increases=((order.intent_id, fill),)
        )
        assert state.close_required == ()
        assert "post_fill_risk_breach" not in state.reasons
        assert "portfolio_cap_reduction" not in state.reasons


def test_fee_entry_preserves_existing_half_multiplier_asset_risk_cap():
    engine = PortfolioEngine(D(10000))
    held = intent(
        stop=D(95),
        requested_quantity=D(5),
        fee_rate=D(0),
        slippage_rate=D(0),
        risk_multiplier=D(".5"),
    )
    answer = engine.submit(held, replace(candidate(held), risk_multiplier=D(".5")), QUOTES, RULES)
    assert answer.quantity == 5
    fill = FillEvent(
        "held", 1, held.symbol, held.owner, held.venue, held.side, answer.quantity, D(100), D(0)
    )
    engine.settle("held", 1, QUOTES, RULES, increases=((held.intent_id, fill),))
    new = intent("other", "ETHUSDT", stop=D(99), fee_rate=D(".001"), slippage_rate=D(0))
    assert not engine.submit(new, replace(candidate(new), decision_ms=1), QUOTES, RULES).accepted
