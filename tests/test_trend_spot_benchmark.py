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


def test_replay_uses_window_closes_and_independent_cost_accounts():
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, replay_spot_benchmark

    start = T + 65 * DAY
    rows = [
        Kline(start + i * HOUR, D(100), D(100), D(100), D(100), D(1), D(1), D(".5"))
        for i in range(48)
    ]
    rows.append(Kline(start + 48 * HOUR, D(999), D(999), D(999), D(999), D(1), D(1), D(".5")))
    decisions = HoldDecisions({"BTCUSDT": history(67)}, {"BTCUSDT": "2020-01"})
    a = replay_spot_benchmark(
        decisions, {"BTCUSDT": FILTERS}, {"BTCUSDT": rows}, start, start + 48 * HOUR
    )
    b = replay_spot_benchmark(
        decisions,
        {"BTCUSDT": FILTERS},
        {"BTCUSDT": rows},
        start,
        start + 48 * HOUR,
        cost_multiple=2,
    )
    assert a.stopped == b.stopped == "completed"
    assert a.account.holdings["BTCUSDT"] == b.account.holdings["BTCUSDT"] == 10
    assert a.samples[-1] == (start + 48 * HOUR, D("9998.4995"))
    assert b.samples[-1][1] < a.samples[-1][1]
    assert len(a.account.fills) == 1  # second day's tiny weight drift stays inside band
    assert a.rebalances[-1].reason == "inside_band"
    assert a.rebalances[-1].fill_start == a.rebalances[-1].fill_end == 1
    assert a.rebalances[0].requested_change == 10
    assert a.rebalances[0].fill_end - a.rebalances[0].fill_start == 1


def test_rounded_no_change_is_reported_separately_from_band_skip():
    from crypto_grid_bot.trend.spot_benchmark import SpotRunner

    rules = OrderFilters(*map(D, ("10", "100000", "10", "5", "10", "100000", "10", "1")))
    r = SpotRunner({"BTCUSDT": rules})
    r.step(T, {}, {"BTCUSDT": D(".011")})
    r.step(T + HOUR, {"BTCUSDT": (D(100), D(100), D(100))})
    assert not r.account.fills
    record = r.rebalances[0]
    assert record.reason == "rounded_no_change"
    assert record.target_weight == D(".011")
    assert record.current_weight == 0
    assert record.requested_change == 0


def test_rotation_sells_before_buys_and_counts_missing_held_hours():
    from crypto_grid_bot.trend.spot_benchmark import SpotRunner

    r = SpotRunner({"BTCUSDT": FILTERS, "ETHUSDT": FILTERS})
    bars = {s: (D(100), D(100), D(100)) for s in r.filters}
    r.step(T, bars, {"ETHUSDT": D(".1")})
    r.step(T + HOUR, bars)
    r.step(T + 2 * HOUR, {"BTCUSDT": bars["BTCUSDT"]})
    assert r.masked_held_hours == {"ETHUSDT": 1}
    for hour in range(3, 24):
        r.step(T + hour * HOUR, bars)
    r.step(T + DAY, bars, {"ETHUSDT": D(0), "BTCUSDT": D(".1")})
    r.step(T + DAY + HOUR, bars)
    assert [f.symbol for f in r.account.fills[-2:]] == ["ETHUSDT", "BTCUSDT"]
    assert r.account.holdings["ETHUSDT"] == 0
    assert r.account.audit().exact


def test_replay_rejects_reserved_and_duplicate_hour_inventory():
    import pytest

    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, replay_spot_benchmark

    decisions = HoldDecisions({"BTCUSDT": history(65)}, {"BTCUSDT": "2020-01"})
    bar = Kline(T, D(100), D(100), D(100), D(100), D(1), D(1), D(".5"))
    with pytest.raises(ValueError, match="unique"):
        replay_spot_benchmark(decisions, {"BTCUSDT": FILTERS}, {"BTCUSDT": [bar, bar]}, T, T + DAY)
    reserved = Kline(1735689600000, D(100), D(100), D(100), D(100), D(1), D(1), D(".5"))
    with pytest.raises(ValueError, match="inventory"):
        replay_spot_benchmark(decisions, {"BTCUSDT": FILTERS}, {"BTCUSDT": [reserved]}, T, T + DAY)


def test_exclusion_missing_fill_invalidates_held_position_but_retains_dust():
    from crypto_grid_bot.trend.spot_benchmark import HoldDecisions, replay_spot_benchmark

    start = T + 89 * DAY
    decisions = HoldDecisions(
        {"BTCUSDT": history(90)}, {"BTCUSDT": "2020-01"}, {"BTCUSDT": frozenset({"2020-04"})}
    )

    def run(final_price):
        rows = [
            Kline(start + i * HOUR, D(100), D(100), D(100), D(100), D(1), D(1), D(".5"))
            for i in range(23)
        ]
        p = D(final_price)
        rows.append(Kline(start + 23 * HOUR, p, p, p, p, D(1), D(1), D(".5")))
        return replay_spot_benchmark(
            decisions, {"BTCUSDT": FILTERS}, {"BTCUSDT": rows}, start, start + 3 * DAY
        )

    held = run(100)
    assert held.stopped == "unavailable_exclusion_close"
    assert held.samples[-1][0] == start + DAY
    assert len(held.account.fills) == 1
    assert held.close_requirements[0].fill_ms is None
    dust = run(".1")
    assert dust.stopped == "completed"
    assert dust.account.holdings["BTCUSDT"] == 10
    assert dust.exclusion_dust[0][1] == "BTCUSDT"
    assert dust.samples[-1][1] == dust.account.cash + 1
    assert all(a.exact for a in dust.audits)
