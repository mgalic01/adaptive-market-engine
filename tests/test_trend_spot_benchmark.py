"""Risk-matched hold decisions on synthetic spot history."""

from decimal import Decimal as D

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.trend.filters import OrderFilters

T, DAY = 1577836800000, 86400000
HOUR = 3600000
FILTERS = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))


def history(count):
    return [
        Kline(
            T + i * DAY,
            D(1000 - i * 2 - i % 3),
            D(1000 - i * 2 - i % 3),
            D(1000 - i * 2 - i % 3),
            D(1000 - i * 2 - i % 3),
            D(1),
            D(1),
            D(".5"),
        )
        for i in range(count)
    ]


def test_hold_stays_long_in_falling_market_and_ignores_future_bars():
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions

    a = HoldDecisions({"BTCUSDT": history(65)}, {"BTCUSDT": "2020-01"})
    b = HoldDecisions({"BTCUSDT": history(90)}, {"BTCUSDT": "2020-01"})
    decision = a.at(T + 65 * DAY)
    assert decision == b.at(T + 65 * DAY)
    assert decision.signals == {"BTCUSDT": D(1)}
    assert 0 < decision.targets["BTCUSDT"] <= D(".1")
    assert a.at(T + 66 * DAY).targets == {}


def test_hold_exclusion_overrides_missing_bar_but_not_after_run():
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions

    a = HoldDecisions(
        {"BTCUSDT": history(65)}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )
    assert a.at(T + 90 * DAY).targets == {"BTCUSDT": D(0)}
    assert a.at(T + 90 * DAY, run_end_ms=T + 91 * DAY).targets == {}


def test_spot_runner_delays_fills_and_samples_before_costs():
    from crypto_grid_bot.trend.spot_benchmark import SpotRunner

    r = SpotRunner({"BTCUSDT": FILTERS})
    bars = {"BTCUSDT": (D(100), D(90), D(110))}
    r.step(T, bars, {"BTCUSDT": D(".1")})
    assert not r.account.fills
    r.step(T + HOUR, bars)
    assert r.samples == [(T + HOUR, D(10000))]
    assert r.account.holdings == {"BTCUSDT": D(10)}
    assert r.account.cash == D("8998.4995")
    assert r.max_drawdown > D(".01")
    assert [point.kind for point in r.equity_path[-2:]] == ["favourable", "adverse"]
    assert r.equity_path[-1].timestamp_ms == T + 2 * HOUR - 1
    assert all(a.exact for a in r.audits)


def test_spot_runner_defers_masked_order_and_poisoned_runs_cannot_retry():
    import pytest

    from crypto_grid_bot.trend.spot_benchmark import SpotRunner

    r = SpotRunner({"BTCUSDT": FILTERS})
    r.step(T, {}, {"BTCUSDT": D(".1")})
    r.step(T + HOUR, {})
    assert not r.account.fills
    r.step(T + 2 * HOUR, {"BTCUSDT": (D(100), D(100), D(100))})
    assert r.account.holdings["BTCUSDT"] == 10
    r.account.cash += 1
    with pytest.raises(ValueError, match="accounting"):
        r.step(T + 3 * HOUR, {})
    with pytest.raises(ValueError, match="stopped"):
        r.step(T + 3 * HOUR, {})


def test_terminal_mark_keeps_holdings_and_charges_no_exit_fee():
    from crypto_grid_bot.trend.spot_benchmark import SpotRunner

    r = SpotRunner({"BTCUSDT": FILTERS})
    r.step(T, {}, {"BTCUSDT": D(".1")})
    r.step(T + HOUR, {"BTCUSDT": (D(100), D(100), D(100))})
    assert r.finish({"BTCUSDT": D(105)}) == D("10048.4995")
    assert len(r.account.fills) == 1
    assert r.account.holdings["BTCUSDT"] == 10
    assert r.samples[-1] == (T + 2 * HOUR, D("10048.4995"))
    assert r.stopped == "completed"
