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
