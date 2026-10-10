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


def candidate(order):
    return Qualification(order.symbol, 0, True, order.owner, order.side, D(1), ())


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
    assert state.available_cash == D("9899.753049")


def test_pre_exit_liquidation_at_new_mark_cannot_be_hidden_by_close():
    engine = PortfolioEngine(D(10000))
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
    now = 86_400_002
    quotes = {symbol: Quote(D(100), now) for symbol in QUOTES}
    other = intent("eth", "ETHUSDT")
    admitted = engine.submit(other, replace(candidate(other), decision_ms=now), quotes, RULES)
    assert admitted.accepted
    state = engine.observe(now, quotes, RULES)
    assert state.recovery.risk_fraction == D(".25")
    assert state.account.positions[0].quantity == D(".001")
