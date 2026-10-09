"""Reported cost drag and filter-based capital floor, on synthetic accounts."""

from decimal import Decimal as D

from crypto_grid_bot.trend.account import FuturesAccount
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orders import OrderIntent, plan_rebalance
from crypto_grid_bot.trend.runner import TrendRunner

T = 1577836800000
HOUR = 3600000
FILTERS = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def test_refused_or_rounded_intention_retains_actual_unrounded_notional():
    plan = plan_rebalance(D(".001"), D(0), D(10000), D(100), FILTERS)
    assert not plan.orders
    assert plan.intended_increase_quantity == D(".1")
    assert plan.intended_increase_notional == D(10)


def test_costs_include_both_sides_and_signed_funding_without_double_charging_slippage():
    from crypto_grid_bot.trend.cost_diagnostics import cost_diagnostics

    a = FuturesAccount()
    a.fill("BTCUSDT", OrderIntent(D(2), False), D(100), T)
    a.fill("ETHUSDT", OrderIntent(D(-1), False), D(100), T)
    a.fund(T, {"BTCUSDT": D(".01"), "ETHUSDT": D(".02")}, {"BTCUSDT": D(100), "ETHUSDT": D(100)})
    a.fill("BTCUSDT", OrderIntent(D(-2), True), D(110), T + HOUR)
    result = cost_diagnostics(a)
    assert result.fill_count == 3
    assert result.funding_paid == 2
    assert result.funding_received == 2
    assert result.slippage_cost == D(".26")
    assert result.traded_notional == D("519.94")
    assert result.fees == D(".259970")
    assert a.audit({"ETHUSDT": D(100)}).accepted


def test_capital_floor_includes_an_order_that_rounded_to_zero():
    from crypto_grid_bot.trend.cost_diagnostics import minimum_account_size

    runner = TrendRunner({"BTCUSDT": FILTERS})
    bars = {"BTCUSDT": (D(100), D(100), D(100))}
    runner.step(T, bars, {"BTCUSDT": D(".001")}, {})
    runner.step(T + HOUR, bars, {}, {})
    assert not runner.account.fills
    result = minimum_account_size(runner)
    assert result.required_usdt == D(100000)
    assert result.symbol == "BTCUSDT"
    assert result.timestamp_ms == T + HOUR
    assert result.intended_quantity == D(".1")


def test_no_opening_intention_has_no_capital_floor():
    from crypto_grid_bot.trend.cost_diagnostics import minimum_account_size

    runner = TrendRunner({"BTCUSDT": FILTERS})
    runner.step(T, {"BTCUSDT": (D(100), D(100), D(100))}, {}, {})
    assert minimum_account_size(runner) is None


def test_capital_floor_rounds_up_and_rejects_missing_legacy_evidence():
    from dataclasses import replace

    import pytest

    from crypto_grid_bot.trend.cost_diagnostics import minimum_account_size

    filters = replace(FILTERS, min_notional=D(1000))
    runner = TrendRunner({"BTCUSDT": filters})
    bars = {"BTCUSDT": (D(100), D(100), D(100))}
    runner.step(T, bars, {"BTCUSDT": D(".129")}, {})
    runner.step(T + HOUR, bars, {}, {})
    assert minimum_account_size(runner).required_usdt == D(7760)
    stamp, dispatch, hour = runner.hours[-1]
    symbol, plan = hour.plans[0]
    runner.hours[-1] = (
        stamp,
        dispatch,
        replace(hour, plans=((symbol, replace(plan, intended_increase_notional=None)),)),
    )
    with pytest.raises(ValueError, match="notional"):
        minimum_account_size(runner)


def test_legacy_missing_quantity_is_not_silently_reported_as_no_openings():
    from dataclasses import replace

    import pytest

    from crypto_grid_bot.trend.cost_diagnostics import minimum_account_size

    runner = TrendRunner({"BTCUSDT": FILTERS})
    bars = {"BTCUSDT": (D(100), D(100), D(100))}
    runner.step(T, bars, {"BTCUSDT": D(".1")}, {})
    runner.step(T + HOUR, bars, {}, {})
    assert runner.account.fills
    stamp, dispatch, hour = runner.hours[-1]
    symbol, plan = hour.plans[0]
    legacy = replace(plan, intended_increase_quantity=None, intended_increase_notional=None)
    runner.hours[-1] = (stamp, dispatch, replace(hour, plans=((symbol, legacy),)))
    with pytest.raises(ValueError, match="intention"):
        minimum_account_size(runner)


def test_no_increase_has_explicit_zero_notional_instead_of_unknown_evidence():
    skipped = plan_rebalance(D(".1"), D(10), D(10000), D(100), FILTERS)
    reduced = plan_rebalance(D(".02"), D(10), D(10000), D(100), FILTERS)
    assert skipped.intended_increase_quantity is None
    assert reduced.intended_increase_quantity is None
    assert skipped.intended_increase_notional == reduced.intended_increase_notional == 0
