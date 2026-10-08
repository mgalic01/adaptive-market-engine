"""Frozen V3 sizing on synthetic daily histories, never market archives."""

from decimal import ROUND_DOWN, Decimal, localcontext

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms

D = Decimal
DAY = 86_400_000
START = month_bounds_ms("2020-01")[0]


def bar(day, close):
    value = D(close)
    return Kline(START + day * DAY, value, value, value, value, D(1), value, D("0.5"))


def test_daily_returns_omit_gaps_and_use_later_close_day():
    from crypto_grid_bot.trend.sizing import DailyReturn, daily_returns

    bars = [bar(0, 100), bar(1, 110), bar(3, 110), bar(4, 99)]
    expected = (DailyReturn(START + DAY, D("0.1")), DailyReturn(START + 4 * DAY, D("-0.1")))
    assert daily_returns(bars) == expected
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_DOWN
        assert daily_returns(bars) == expected
    assert daily_returns([]) == ()
    assert daily_returns([bar(0, 100)]) == ()


@pytest.mark.parametrize("bars", [
    [bar(0, 0)], [bar(0, -1)], [bar(0, "NaN")],
    [bar(1, 1), bar(1, 2)], [bar(1, 1), bar(0, 2)],
    [bar(1827, 1)],
])
def test_daily_returns_reject_invalid_inputs(bars):
    from crypto_grid_bot.trend.sizing import daily_returns

    with pytest.raises(ValueError):
        daily_returns(bars)
