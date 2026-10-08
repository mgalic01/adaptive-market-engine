"""Risk-matched hold decisions on synthetic spot history."""

from decimal import Decimal as D

from crypto_grid_bot.backtest.klines import Kline

T, DAY = 1577836800000, 86400000


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
