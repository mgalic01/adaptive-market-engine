from dataclasses import replace
from decimal import Decimal as D

import pytest
from test_combined_engine import QUOTES, RULES, candidate
from test_combined_ohlc_path import bar
from test_combined_risk import intent

from crypto_grid_bot.combined.account import FillEvent
from crypto_grid_bot.combined.engine import PortfolioEngine


def portfolio():
    engine = PortfolioEngine(D(10000))
    for symbol, side, stop in (("BTCUSDT", 1, 98), ("ETHUSDT", -1, 102)):
        order = intent(
            key=symbol,
            symbol=symbol,
            owner="futures_trend",
            venue="futures",
            side=side,
            stop=D(stop),
            requested_quantity=D(1),
            fee_rate=D(0),
            slippage_rate=D(0),
            funding_rate=D(0),
            funding_age_ms=0,
            funding_interval_ms=28_800_000,
        )
        assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
        engine.settle(
            symbol,
            0,
            QUOTES,
            RULES,
            increases=(
                (
                    order.intent_id,
                    FillEvent(
                        symbol, 0, symbol, order.owner, order.venue, side, D(1), D(100), D(0)
                    ),
                ),
            ),
        )
    return engine


@pytest.mark.parametrize("scenario", ["open_low_high_close", "open_high_low_close"])
def test_synchronized_portfolio_stops_remove_exited_inventory(scenario):
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()
    rows = (("ETHUSDT", bar(high=10000000, low=90)), ("BTCUSDT", bar(low=1)))
    result = replay_held_portfolio(engine, rows, RULES, scenario, source_refs=("synthetic",))
    assert result.failure is None
    assert {fill.symbol for fill in result.fills} == {"BTCUSDT", "ETHUSDT"}
    assert result.observations[-1].snapshot.account.equity == 9996
    assert result.observations[-1].snapshot.account.positions == ()
    assert not any(row.snapshot.liquidation for row in result.observations)


def test_missing_held_asset_bar_rejected_before_mutation():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()
    with pytest.raises(ValueError):
        replay_held_portfolio(
            engine, (("BTCUSDT", bar()),), RULES, "open_low_high_close", source_refs=("synthetic",)
        )
    assert engine.clock == 0
    assert len(engine.held_execution_terms()) == 2


def test_existing_portfolio_close_executes_at_open_before_old_stop():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()
    engine.request_close("BTCUSDT", "futures_trend", 1, reason="reversal")
    rows = (("BTCUSDT", bar(low=90)), ("ETHUSDT", bar(high=101, low=99, close=100)))
    result = replay_held_portfolio(
        engine, rows, RULES, "open_low_high_close", source_refs=("synthetic",)
    )
    assert result.failure is None
    assert result.fills[0].symbol == "BTCUSDT"
    assert result.fills[0].price == 100
    assert result.observations[-1].snapshot.account.equity == 10000


def test_venue_maximum_splits_close_without_dropping_remainder():
    from dataclasses import replace

    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()
    rules = {name: replace(rule, max_qty=D(".5")) for name, rule in RULES.items()}
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar()), ("ETHUSDT", bar())),
        rules,
        "open_low_high_close",
        source_refs=("s",),
    )
    assert result.failure is None
    assert len(result.fills) == 4
    assert all(fill.quantity == D(".5") for fill in result.fills)
    assert result.observations[-1].snapshot.account.positions == ()


def test_input_symbol_order_cannot_change_economic_outcome():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    rows = (("BTCUSDT", bar()), ("ETHUSDT", bar()))
    first = replay_held_portfolio(
        portfolio(), rows, RULES, "open_low_high_close", source_refs=("s",)
    )
    second = replay_held_portfolio(
        portfolio(), rows[::-1], RULES, "open_low_high_close", source_refs=("s",)
    )
    assert first == second


def test_duplicate_bars_rejected_before_mutation():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()
    with pytest.raises(ValueError):
        replay_held_portfolio(
            engine,
            (("BTCUSDT", bar()), ("BTCUSDT", bar())),
            RULES,
            "open_low_high_close",
            source_refs=("s",),
        )
    assert engine.clock == 0


def test_unsellable_remainders_stay_valued_and_owned():
    from dataclasses import replace

    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    rules = {name: replace(rule, min_notional=D(200)) for name, rule in RULES.items()}
    result = replay_held_portfolio(
        portfolio(),
        (("BTCUSDT", bar()), ("ETHUSDT", bar())),
        rules,
        "open_low_high_close",
        source_refs=("s",),
    )
    # Verified unsellable inventory keeps its obligation and value; it is not a failure.
    assert result.failure is None
    assert result.retained_dust == ("BTCUSDT", "ETHUSDT")
    assert result.observations[-1].snapshot.close_required == ("BTCUSDT", "ETHUSDT")
    assert not result.fills
    assert len(result.observations[-1].snapshot.account.positions) == 2
    assert all(p.mark == 105 for p in result.observations[-1].snapshot.account.positions)


def test_post_booking_failure_retains_actual_reduction(monkeypatch):
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()
    original = engine.observe
    calls = 0

    def broken(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ValueError("post booking mark")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "observe", broken)
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar()), ("ETHUSDT", bar())),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
    )
    assert result.failure == "execution_failure:ValueError"
    assert len(result.fills) == 1
    assert result.fills[0].symbol == "BTCUSDT"
    assert result.observations[-1].id.endswith(":before")
    assert [row[0].symbol for row in engine.held_execution_terms()] == ["ETHUSDT"]


def test_true_opening_gap_liquidation_is_not_erased_by_exit():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    result = replay_held_portfolio(
        portfolio(),
        (("BTCUSDT", bar()), ("ETHUSDT", bar(open=10000000, high=10000000))),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
    )
    assert result.failure == "portfolio_safety_failure"
    assert result.observations[0].snapshot.liquidation


def grid_portfolio():
    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="spot_grid", requested_quantity=D(2), stop=D(95), fee_rate=D(0), slippage_rate=D(0)
    )
    assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
    for lot, price in (("lot-one", 100), ("lot-two", 99)):
        engine.settle(
            lot,
            0,
            QUOTES,
            RULES,
            increases=(
                (
                    order.intent_id,
                    FillEvent(lot, 0, "BTCUSDT", "spot_grid", "spot", 1, D(1), D(price), D(0), lot),
                ),
            ),
        )
    return engine


def test_grid_target_closes_matching_lot_using_its_actual_fill_price():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    result = replay_held_portfolio(
        grid_portfolio(),
        (("BTCUSDT", bar(high="101.5", low=97, close="100.5")),),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
        grid_spacing=(("BTCUSDT", D(2)),),
    )
    assert result.failure is None
    assert len(result.fills) == 1
    assert result.fills[0].lot_id == "lot-two"
    assert result.fills[0].price == 101
    held = result.observations[-1].snapshot.account.positions[0]
    assert held.lots[0].lot_id == "lot-one"
    assert held.entry_cost == 100
    assert result.observations[-1].snapshot.account.equity == D("10002.5")


def test_grid_old_stop_suppresses_all_favorable_lot_targets():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    result = replay_held_portfolio(
        grid_portfolio(),
        (("BTCUSDT", bar(low=90)),),
        RULES,
        "open_high_low_close",
        source_refs=("s",),
        grid_spacing=(("BTCUSDT", D(2)),),
    )
    assert result.failure is None
    assert [fill.price for fill in result.fills] == [95]
    assert result.observations[-1].snapshot.account.equity == 9991


def test_grid_spacing_is_mandatory_before_any_mutation():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = grid_portfolio()
    with pytest.raises(ValueError):
        replay_held_portfolio(
            engine, (("BTCUSDT", bar()),), RULES, "open_low_high_close", source_refs=("s",)
        )
    assert engine.clock == 0


def test_open_gap_target_does_not_reprice_remaining_inventory_to_limit():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    result = replay_held_portfolio(
        grid_portfolio(),
        (("BTCUSDT", bar(open=110, high=110, low=100)),),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
        grid_spacing=(("BTCUSDT", D(2)),),
    )
    reduced = [row for row in result.observations if row.id.endswith(":reduction")]
    assert reduced[0].snapshot.account.positions[0].mark == 110
    assert [fill.price for fill in result.fills] == [101, 102]


def grid_basket():
    engine = PortfolioEngine(D(10000))
    order = intent(
        key="grid",
        owner="spot_grid",
        venue="spot",
        side=1,
        price=D(100),
        stop=D(90),
        requested_quantity=D(3),
        fee_rate=D(0),
        slippage_rate=D(0),
    )
    admission = engine.submit(order, candidate(order), QUOTES, RULES)
    assert admission.accepted and admission.quantity == 3
    return engine, order


def children(order, limits=(99, 98, 97)):
    from crypto_grid_bot.combined.portfolio_path import RestingBuy

    return tuple(
        RestingBuy(
            order.intent_id, f"child:{n}", "BTCUSDT", D(limit), D(1), order.fee_rate, order.stop
        )
        for n, limit in enumerate(limits, start=1)
    )


@pytest.mark.parametrize("scenario", ["open_low_high_close", "open_high_low_close"])
def test_resting_grid_buys_fill_at_their_limits_and_earn_no_same_bar_target(scenario):
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine, order = grid_basket()
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar(open=100, high=105, low="97.5", close=101)),),
        RULES,
        scenario,
        source_refs=("s",),
        resting=children(order),
    )
    assert result.failure is None
    assert result.filled_children == ("child:1", "child:2")
    assert [(f.lot_id, f.price, f.side) for f in result.fills] == [
        ("child:1", D(99), 1),
        ("child:2", D(98), 1),
    ]
    held = result.observations[-1].snapshot.account.positions[0]
    assert held.quantity == 2 and held.owner == "spot_grid"
    # The third child still rests: an active pending order is not an obligation.
    assert result.observations[-1].snapshot.unresolved_execution == (order.intent_id,)


@pytest.mark.parametrize("scenario", ["open_low_high_close", "open_high_low_close"])
def test_intrabar_grid_purchases_are_stopped_in_the_same_bar(scenario):
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine, order = grid_basket()
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar(open=100, high=101, low=85, close=88)),),
        RULES,
        scenario,
        source_refs=("s",),
        resting=children(order),
    )
    assert result.failure is None
    assert [(f.side, f.quantity, f.price) for f in result.fills] == [
        (1, D(1), D(99)),
        (1, D(1), D(98)),
        (1, D(1), D(97)),
        (-1, D(3), D(90)),
    ]
    assert not result.observations[-1].snapshot.account.positions


def test_gap_open_below_the_limits_fills_at_the_limits_without_gap_credit():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine, order = grid_basket()
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar(open=96, high=97, low=95, close="96.5")),),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
        resting=children(order),
    )
    assert result.failure is None
    assert [f.price for f in result.fills] == [D(99), D(98), D(97)]
    assert {row.phase for row in result.observations if ":buy:" in row.id} == {"open:buy"}


def test_a_canceled_basket_no_longer_rests():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine, order = grid_basket()
    engine.request_close("BTCUSDT", "spot_grid", 1, reason="grid_left_range")
    engine.acknowledge_finality(order.intent_id, source_refs=("replay:cancel",))
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar(low=85)),),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
        resting=children(order),
    )
    assert result.failure is None
    assert result.fills == () and result.filled_children == ()


def test_unreconciled_canceled_basket_remains_an_obligation():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine, order = grid_basket()
    engine.request_close("BTCUSDT", "spot_grid", 1, reason="grid_left_range")
    result = replay_held_portfolio(
        engine,
        (("BTCUSDT", bar(low=99)),),
        RULES,
        "open_low_high_close",
        source_refs=("s",),
        resting=children(order),
    )
    assert result.fills == ()
    assert result.failure == "unresolved_execution_obligations"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: (rows[0], rows[0]),  # duplicate child
        lambda rows: (replace(rows[0], stop=D(99)),),  # stop not below the limit
        lambda rows: (rows[0], replace(rows[1], stop=D(80))),  # two basket stops
        lambda rows: (replace(rows[0], quantity=D(0)),),
        lambda rows: (replace(rows[0], fee_rate=D(1)),),
        lambda rows: [rows[0]],  # not an immutable tuple
    ],
)
def test_malformed_resting_buys_are_refused_before_mutation(mutate):
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine, order = grid_basket()
    with pytest.raises(ValueError):
        replay_held_portfolio(
            engine,
            (("BTCUSDT", bar()),),
            RULES,
            "open_low_high_close",
            source_refs=("s",),
            resting=mutate(children(order)),
        )
    assert engine.clock == 0


def test_resting_buys_need_their_own_bar_and_a_grid_owner():
    from crypto_grid_bot.combined.portfolio_path import replay_held_portfolio

    engine = portfolio()  # futures holdings of BTCUSDT and ETHUSDT
    order = intent(key="grid", owner="spot_grid", venue="spot", stop=D(90))
    rows = children(order)
    with pytest.raises(ValueError):
        replay_held_portfolio(
            engine,
            (("BTCUSDT", bar()), ("ETHUSDT", bar())),
            RULES,
            "open_low_high_close",
            source_refs=("s",),
            resting=rows,
        )
    engine, order = grid_basket()
    with pytest.raises(ValueError):
        replay_held_portfolio(
            engine,
            (("ETHUSDT", bar()),),
            RULES,
            "open_low_high_close",
            source_refs=("s",),
            resting=children(order),
        )


def test_unallocated_basket_share_is_released_with_evidence():
    engine, order = grid_basket()
    engine.release_unallocated(order.intent_id, D("2.4"), source_refs=("grid:allocation",))
    assert [a.quantity for a in engine.reservations] == [D("2.4")]
    with pytest.raises(ValueError):
        engine.release_unallocated(order.intent_id, D(3), source_refs=("grid:allocation",))
    with pytest.raises(ValueError):
        engine.release_unallocated(order.intent_id, D(1), source_refs=())
    engine.release_unallocated(order.intent_id, D(0), source_refs=("grid:cancel",))
    assert engine.reservations == ()
    assert engine.observe(0, QUOTES, RULES).unresolved_execution == ()
    assert engine.release_evidence == (
        (order.intent_id, ((D("2.4"), ("grid:allocation",)), (D(0), ("grid:cancel",)))),
    )
    with pytest.raises(ValueError):
        engine.release_unallocated(order.intent_id, D(0), source_refs=("again",))
