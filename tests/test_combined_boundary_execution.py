from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_combined_engine import QUOTES, RULE, RULES, candidate
from test_combined_ohlc_path import held_short
from test_combined_risk import intent

from crypto_grid_bot.combined.account import FillEvent
from crypto_grid_bot.combined.boundary_execution import BoundaryExecutor, FundingFixing
from crypto_grid_bot.combined.engine import PortfolioEngine, Quote

AT_ONE = {"BTCUSDT": Quote(D(100), 1), "ETHUSDT": Quote(D(100), 1)}


def held(*positions):
    """Engine holding (symbol, owner, venue, side) lots of one unit bought at 100."""
    engine = PortfolioEngine(D(10000))
    for symbol, owner, venue, side in positions:
        futures = (
            {"funding_rate": D(0), "funding_age_ms": 0, "funding_interval_ms": 28_800_000}
            if venue == "futures"
            else {}
        )
        order = intent(
            key=symbol,
            symbol=symbol,
            owner=owner,
            venue=venue,
            side=side,
            stop=D(98) if side == 1 else D(102),
            requested_quantity=D(1),
            fee_rate=D(0),
            slippage_rate=D(0),
            **futures,
        )
        assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
        fill = FillEvent(symbol, 0, symbol, owner, venue, side, D(1), D(100), D(0))
        engine.settle(symbol, 0, QUOTES, RULES, increases=((order.intent_id, fill),))
    return engine


def settle(engine, *, batch="boundary:one", at=1, quotes=None, rules=RULES, fixings=()):
    return BoundaryExecutor(engine).settle(
        batch,
        at,
        AT_ONE if quotes is None else quotes,
        rules,
        due_funding=tuple(f.symbol for f in fixings),
        fixings=tuple(fixings),
        source_refs=("fixture:funding",),
    )


def fixing(symbol="BTCUSDT", rate=".01", mark=100, event_id=None, at=1):
    return FundingFixing(event_id or f"funding:{symbol}:{at}", symbol, at, D(rate), D(mark))


def test_funding_precedes_simultaneous_protective_exit():
    engine = held_short()
    engine.request_close("BTCUSDT", "futures_trend", -1, reason="reversal")
    executor = BoundaryExecutor(engine)
    one = FundingFixing("funding:one", "BTCUSDT", 1, D(".01"), D(100))
    result = executor.settle(
        "boundary:one",
        1,
        {"BTCUSDT": Quote(D(100), 1)},
        RULES,
        due_funding=("BTCUSDT",),
        fixings=(one,),
        source_refs=("fixture:funding",),
    )
    assert result.failure is None
    assert result.funding[0].amount == D(1)
    assert len(result.fills) == 1
    assert not result.final.account.positions
    assert result.final.account.free_cash == D(10001)
    # The payment is booked on pre-boundary holdings before the exit's own batch.
    assert [row.phase for row in result.observations] == [
        "before",
        "funding",
        "settled",
        "before",
        "reduction",
        "settled",
    ]
    assert (
        executor.settle(
            "boundary:one",
            1,
            {"BTCUSDT": Quote(D(100), 1)},
            RULES,
            due_funding=("BTCUSDT",),
            fixings=(one,),
            source_refs=("fixture:funding",),
        )
        == result
    )


def test_missing_due_funding_never_substitutes_zero():
    engine = held_short()
    result = BoundaryExecutor(engine).settle(
        "boundary:one",
        1,
        {"BTCUSDT": Quote(D(100), 1)},
        RULES,
        due_funding=("BTCUSDT",),
        fixings=(),
        source_refs=("fixture:funding",),
    )
    assert result.failure == "invalid_boundary_inputs"
    assert not result.funding and not result.fills
    assert engine.clock == 0


def test_positive_rate_long_pays_and_short_receives_at_the_fixing_mark():
    engine = held(
        ("BTCUSDT", "futures_trend", "futures", 1), ("ETHUSDT", "futures_trend", "futures", -1)
    )
    before = engine.observe(0, QUOTES, RULES).account.free_cash
    result = settle(engine, fixings=(fixing("BTCUSDT", mark=120), fixing("ETHUSDT", mark=120)))
    assert result.failure is None
    # The source fixing's own mark prices the payment, not the boundary quote.
    assert [(e.symbol, e.amount) for e in result.funding] == [
        ("BTCUSDT", D("-1.2")),
        ("ETHUSDT", D("1.2")),
    ]
    assert result.final.account.free_cash == before
    assert result.final.account.funding == 0


def test_spot_holding_and_unheld_symbols_never_pay_futures_funding():
    engine = held(("BTCUSDT", "spot_trend", "spot", 1))
    before = engine.observe(0, QUOTES, RULES).account.free_cash
    result = settle(engine, fixings=(fixing("BTCUSDT"), fixing("ETHUSDT")))
    assert result.failure is None
    assert result.funding == ()
    assert result.final.account.free_cash == before
    assert result.final.account.funding == 0


@pytest.mark.parametrize(
    "fixings",
    [
        (fixing("BTCUSDT", event_id="same"), fixing("ETHUSDT", event_id="same")),
        (fixing("BTCUSDT", at=0),),
        (fixing("BTCUSDT", rate="1.5"),),
        (fixing("BTCUSDT", mark=0),),
        (replace(fixing("BTCUSDT"), rate=D("NaN")),),
        (replace(fixing("BTCUSDT"), event_id=" "),),
    ],
)
def test_malformed_fixings_are_refused_before_any_mutation(fixings):
    engine = held_short()
    result = settle(engine, fixings=fixings)
    assert result.failure == "invalid_boundary_inputs"
    assert result.funding == () and result.fills == () and result.observations == ()
    assert engine.clock == 0


def test_due_list_must_match_fixings_exactly():
    engine = held_short()
    result = BoundaryExecutor(engine).settle(
        "boundary:one",
        1,
        AT_ONE,
        RULES,
        due_funding=("BTCUSDT", "BTCUSDT"),
        fixings=(fixing("BTCUSDT"),),
        source_refs=("fixture:funding",),
    )
    assert result.failure == "invalid_boundary_inputs"
    assert engine.clock == 0


@pytest.mark.parametrize(
    ("quotes", "rules"),
    [
        ({"BTCUSDT": Quote(D(100), 0)}, RULES),  # stale held mark
        ({}, RULES),  # missing held mark
        (AT_ONE, {"ETHUSDT": RULE}),  # missing held filters
    ],
)
def test_held_market_must_be_current_before_mutation(quotes, rules):
    engine = held_short()
    result = settle(engine, quotes=quotes, rules=rules, fixings=(fixing("BTCUSDT"),))
    assert result.failure == "invalid_boundary_inputs"
    assert result.funding == () and result.observations == ()
    assert engine.clock == 0


def test_a_holding_without_a_price_carries_its_close_without_failing():
    engine = held(("BTCUSDT", "spot_trend", "spot", 1), ("ETHUSDT", "futures_trend", "futures", -1))
    engine.request_close("BTCUSDT", "spot_trend", 1, reason="reversal")
    engine.request_close("ETHUSDT", "futures_trend", -1, reason="reversal")
    result = BoundaryExecutor(engine).settle(
        "boundary:one",
        1,
        {"ETHUSDT": Quote(D(100), 1)},
        {"ETHUSDT": RULE},
        due_funding=(),
        fixings=(),
        source_refs=("fixture:funding",),
        unpriced=("BTCUSDT",),
    )
    assert result.failure is None
    # The priced close executes; the unpriced one waits, owned, at its last mark.
    assert [fill.symbol for fill in result.fills] == ["ETHUSDT"]
    assert [(p.symbol, p.mark) for p in result.final.account.positions] == [("BTCUSDT", D(100))]
    assert result.final.close_required == ("BTCUSDT",)


@pytest.mark.parametrize(
    ("quotes", "unpriced"),
    [
        ({"BTCUSDT": Quote(D(100), 1)}, ("BTCUSDT",)),  # an unpriced holding has no quote
        ({"BTCUSDT": Quote(D(100), 1)}, ("ETHUSDT",)),  # not a holding
        ({}, ("BTCUSDT", "BTCUSDT")),
        ({}, ["BTCUSDT"]),  # not an immutable tuple
    ],
)
def test_unpriced_names_only_distinct_holdings_without_quotes(quotes, unpriced):
    engine = held_short()
    result = BoundaryExecutor(engine).settle(
        "boundary:one",
        1,
        quotes,
        RULES,
        due_funding=(),
        fixings=(),
        source_refs=("fixture:funding",),
        unpriced=unpriced,
    )
    assert result.failure == "invalid_boundary_inputs"
    assert result.observations == () and engine.clock == 0


def test_reused_funding_identity_fails_without_a_second_payment():
    engine = held_short()
    first = settle(engine, fixings=(fixing("BTCUSDT", event_id="funding:x"),))
    assert first.failure is None and first.funding[0].amount == D(1)
    cash = first.final.account.free_cash
    second = settle(
        engine,
        batch="boundary:two",
        at=2,
        quotes={"BTCUSDT": Quote(D(100), 2)},
        fixings=(fixing("BTCUSDT", event_id="funding:x", at=2),),
    )
    assert second.failure == "boundary_execution_failure:ValueError"
    assert second.funding == () and second.final is None
    state = engine.observe(2, {"BTCUSDT": Quote(D(100), 2)}, RULES)
    assert state.account.free_cash == cash
    assert "execution_integrity_failure" not in state.reasons


def test_failed_post_funding_mark_retains_payment_and_observed_prefix(monkeypatch):
    engine = held_short()
    original = PortfolioEngine._cap_reductions
    calls = []

    def broken(self, account, fraction):
        calls.append(1)
        if len(calls) >= 2:
            raise ArithmeticError("synthetic valuation failure")
        return original(self, account, fraction)

    monkeypatch.setattr(PortfolioEngine, "_cap_reductions", broken)
    result = settle(engine, fixings=(fixing("BTCUSDT"),))
    assert result.failure == "boundary_execution_failure:ArithmeticError"
    assert result.final is None
    # The payment really happened and stays booked; only its following mark failed.
    assert [e.amount for e in result.funding] == [D(1)]
    assert [row.phase for row in result.observations] == ["before"]
    monkeypatch.setattr(PortfolioEngine, "_cap_reductions", original)
    state = engine.observe(1, {"BTCUSDT": Quote(D(100), 1)}, RULES)
    assert state.account.funding == D(1)
    assert "execution_integrity_failure" in state.reasons


def test_boundary_attempt_cannot_be_retried_or_reset_by_a_new_executor():
    engine = held_short()
    empty = settle(engine, fixings=())
    assert empty.failure is None  # nothing due: a valid, empty funding boundary
    with pytest.raises(ValueError, match="conflicting or unfinished attempt"):
        settle(engine, fixings=(fixing("BTCUSDT"),))
    assert settle(engine, fixings=()) == empty
    invalid = settle(
        engine, batch="boundary:bad", at=2, quotes={}, fixings=(fixing("BTCUSDT", at=2),)
    )
    assert invalid.failure == "invalid_boundary_inputs"
    # Correcting the inputs of a failed attempt does not authorize a retry.
    with pytest.raises(ValueError, match="conflicting or unfinished attempt"):
        settle(
            engine,
            batch="boundary:bad",
            at=2,
            quotes={"BTCUSDT": Quote(D(100), 2)},
            fixings=(fixing("BTCUSDT", at=2),),
        )
    assert (
        settle(engine, batch="boundary:bad", at=2, quotes={}, fixings=(fixing("BTCUSDT", at=2),))
        == invalid
    )


def test_completed_boundary_is_returned_not_rebooked_by_another_executor():
    engine = held_short()
    result = settle(engine, fixings=(fixing("BTCUSDT"),))
    again = settle(engine, fixings=(fixing("BTCUSDT"),))
    assert again == result
    assert engine.observe(1, AT_ONE, RULES).account.funding == D(1)


def test_venue_maximum_splits_the_boundary_close_without_dropping_inventory():
    engine = held_short()
    engine.request_close("BTCUSDT", "futures_trend", -1, reason="reversal")
    rules = {"BTCUSDT": replace(RULE, max_qty=D(".4"))}
    result = settle(engine, rules=rules)
    assert result.failure is None and result.retained_dust == ()
    assert [fill.quantity for fill in result.fills] == [D(".4"), D(".4"), D(".2")]
    assert not result.final.account.positions


def test_unsellable_inventory_keeps_its_obligation_as_retained_dust():
    engine = held_short()
    engine.request_close("BTCUSDT", "futures_trend", -1, reason="reversal")
    result = settle(engine, rules={"BTCUSDT": replace(RULE, min_notional=D(200))})
    assert result.failure is None
    assert result.fills == ()
    assert result.retained_dust == ("BTCUSDT",)
    assert result.final.close_required == ("BTCUSDT",)
    position = result.final.account.positions[0]
    assert position.quantity == D(-1) and position.mark == D(100)


def test_partial_close_leaves_only_a_dust_remainder():
    engine = held_short()
    engine.request_close("BTCUSDT", "futures_trend", -1, reason="reversal")
    rules = {"BTCUSDT": replace(RULE, max_qty=D(".4"), min_notional=D(30))}
    result = settle(engine, rules=rules)
    assert result.failure is None
    assert [fill.quantity for fill in result.fills] == [D(".4"), D(".4")]
    assert result.retained_dust == ("BTCUSDT",)
    assert result.final.account.positions[0].quantity == D("-.2")


def test_boundary_liquidation_is_a_safety_failure():
    engine = held_short()
    result = settle(engine, quotes={"BTCUSDT": Quote(D(10000), 1)})
    assert result.failure == "boundary_safety_failure"
    assert any(row.snapshot.liquidation for row in result.observations)


def test_funding_beyond_free_cash_is_a_safety_failure_not_a_silent_debit():
    engine = held_short()
    result = settle(engine, fixings=(fixing("BTCUSDT", rate="-1", mark=20000),))
    assert result.failure == "boundary_safety_failure"
    assert result.funding[0].amount == D(-20000)
    assert not result.final.account.integrity_ok


def test_empty_boundary_only_marks_the_settled_state():
    engine = held_short()
    result = settle(engine)
    assert result.failure is None
    assert result.fills == () and result.funding == ()
    assert [row.phase for row in result.observations] == ["before", "settled"]
    assert result.final.timestamp_ms == 1


def test_boundary_cuts_a_position_back_to_its_size_limit():
    engine = held_short()
    engine.observe(0, QUOTES, RULES)
    # The short's notional is 100; a 2x price spike makes it exceed 20% of equity
    # only for a tiny account, so impose the cut-back obligation directly.
    with engine.exclusive():
        engine._trims["BTCUSDT"] = D(".4")
        engine._trim_reasons["BTCUSDT"] = {"portfolio_cap_reduction"}
    result = settle(engine)
    assert result.failure is None
    assert [fill.quantity for fill in result.fills] == [D(".6")]
    assert result.final.account.positions[0].quantity == D("-.4")
    assert result.final.reduce_to == ()
