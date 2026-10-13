"""Synthetic OHLC execution/valuation ordering; no historical replay."""

from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.ohlc_path import plan_held_path


def bar(open=100, high=110, low=80, close=105):
    return Kline(0, D(open), D(high), D(low), D(close), D(1), D(100), D(".5"))


@pytest.mark.parametrize("scenario", ["open_low_high_close", "open_high_low_close"])
def test_stop_precedes_adverse_vertex_and_suppresses_same_bar_target(scenario):
    plan = plan_held_path(
        bar(), scenario, side=1, stop=D(95), target=D(108), source_refs=("synthetic",)
    )
    exits = [event for event in plan.events if event.kind != "valuation"]
    assert [(e.kind, e.price) for e in exits] == [("stop", D(95))]
    low = next(i for i, e in enumerate(plan.events) if e.phase == "low" and e.kind == "valuation")
    assert plan.events.index(exits[0]) < low
    assert plan.interval_start_ms == 0 and plan.interval_end_ms == 3600000
    assert not hasattr(exits[0], "timestamp_ms")


def test_high_first_retains_high_before_later_stop_without_favorable_target():
    plan = plan_held_path(
        bar(), "open_high_low_close", side=1, stop=D(95), target=D(108), source_refs=("s",)
    )
    assert [(e.phase, e.kind) for e in plan.events] == [
        ("open", "valuation"),
        ("high", "valuation"),
        ("low", "stop"),
        ("low", "valuation"),
        ("close", "valuation"),
    ]


def test_gap_stop_uses_actual_open_before_remaining_extremes():
    plan = plan_held_path(
        bar(open=90), "open_high_low_close", side=1, stop=D(95), source_refs=("s",)
    )
    assert plan.events[1].kind == "stop" and plan.events[1].price == 90
    assert plan.events[1].phase == "open"


@pytest.mark.parametrize("eligible,expected", [(True, 1), (False, 0)])
def test_intrabar_grid_purchase_cannot_receive_unproven_target(eligible, expected):
    plan = plan_held_path(
        bar(low=99),
        "open_low_high_close",
        side=1,
        stop=D(95),
        target=D(108),
        target_eligible=eligible,
        source_refs=("s",),
    )
    assert sum(e.kind == "target" for e in plan.events) == expected


def test_short_stop_precedes_high_and_no_low_target_credit():
    plan = plan_held_path(
        bar(), "open_low_high_close", side=-1, stop=D(108), target=D(90), source_refs=("s",)
    )
    assert [(e.kind, e.price) for e in plan.events if e.kind != "valuation"] == [("stop", D(108))]
    assert plan.events[-3].kind == "stop"


@pytest.mark.parametrize("scenario", ["native", "unknown"])
def test_only_registered_modeled_scenarios_are_accepted(scenario):
    with pytest.raises(ValueError):
        plan_held_path(bar(), scenario, side=1, stop=D(95), source_refs=("s",))


def test_path_keeps_all_vertices_even_after_exit_request_because_only_fills_remove_inventory():
    plan = plan_held_path(bar(), "open_low_high_close", side=1, stop=D(95), source_refs=("s",))
    assert [e.phase for e in plan.events if e.kind == "valuation"] == [
        "open",
        "low",
        "high",
        "close",
    ]


def held_short():
    from test_combined_engine import QUOTES, RULES, candidate
    from test_combined_risk import intent

    from crypto_grid_bot.combined.account import FillEvent
    from crypto_grid_bot.combined.engine import PortfolioEngine

    engine = PortfolioEngine(D(10000))
    order = intent(
        owner="futures_trend",
        venue="futures",
        side=-1,
        stop=D(102),
        requested_quantity=D(1),
        fee_rate=D(0),
        slippage_rate=D(0),
        funding_rate=D(0),
        funding_age_ms=0,
        funding_interval_ms=28800000,
    )
    assert engine.submit(order, candidate(order), QUOTES, RULES).accepted
    engine.settle(
        "entry",
        0,
        QUOTES,
        RULES,
        increases=(
            (
                order.intent_id,
                FillEvent(
                    "entry-fill", 0, "BTCUSDT", order.owner, order.venue, -1, D(1), D(100), D(0)
                ),
            ),
        ),
    )
    return engine


def test_short_stop_execution_removes_inventory_before_extreme_mark():
    from test_combined_engine import RULES

    from crypto_grid_bot.combined.protected_replay import replay_protected_interval

    engine = held_short()
    result = replay_protected_interval(
        engine,
        (("BTCUSDT", bar(high=10000000, low=90)),),
        RULES,
        "open_low_high_close",
        source_refs=("synthetic",),
    )
    assert result.failure is None
    assert result.fills[0].price == 102
    assert result.observations[-1].snapshot.account.positions == ()
    assert result.observations[-1].snapshot.account.equity == 9998
    assert not any(o.snapshot.liquidation for o in result.observations)
    assert all(o.available_ms == 3600000 for o in result.observations)
    assert all(not hasattr(o, "event_timestamp_ms") for o in result.observations)
    with pytest.raises(ValueError):
        replay_protected_interval(
            engine, (("BTCUSDT", bar()),), RULES, "open_low_high_close", source_refs=("synthetic",)
        )


def test_failed_post_booking_mark_retains_fill_and_settlement_prefix(monkeypatch):
    from test_combined_engine import RULES

    from crypto_grid_bot.combined.protected_replay import replay_protected_interval

    engine = held_short()
    original = engine.observe
    calls = 0

    def broken(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise ValueError("post booking mark")
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, "observe", broken)
    result = replay_protected_interval(
        engine, (("BTCUSDT", bar()),), RULES, "open_low_high_close", source_refs=("synthetic",)
    )
    assert result.failure == "execution_failure:ValueError"
    assert len(result.fills) == 1
    assert result.observations[-1].phase == "high:before"
    assert engine.held_execution_terms() == ()


def test_partial_stop_preserves_inventory_and_failure():
    from dataclasses import replace

    from test_combined_engine import RULES

    from crypto_grid_bot.combined.protected_replay import replay_protected_interval

    engine = held_short()
    rules = {"BTCUSDT": replace(RULES["BTCUSDT"], max_qty=D(".5"))}
    result = replay_protected_interval(
        engine, (("BTCUSDT", bar()),), rules, "open_low_high_close", source_refs=("synthetic",)
    )
    assert result.failure == "unresolved_protective_close"
    assert result.fills[0].quantity == D(".5")
    assert result.observations[-1].snapshot.account.positions[0].quantity == D("-.5")
    assert result.observations[-1].phase == "close"
