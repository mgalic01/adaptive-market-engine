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


@pytest.mark.parametrize(
    "bars",
    [
        [bar(0, 0)],
        [bar(0, -1)],
        [bar(0, "NaN")],
        [bar(1, 1), bar(1, 2)],
        [bar(1, 1), bar(0, 2)],
        [bar(1827, 1)],
    ],
)
def test_daily_returns_reject_invalid_inputs(bars):
    from crypto_grid_bot.trend.sizing import daily_returns

    with pytest.raises(ValueError):
        daily_returns(bars)


def history(days=range(100), amplitude="0.5"):
    from crypto_grid_bot.trend.sizing import DailyReturn

    value = D(amplitude)
    return tuple(DailyReturn(START + day * DAY, value if day % 2 else -value) for day in days)


def test_sample_volatility_and_target_have_hand_calculated_values():
    from crypto_grid_bot.trend.sizing import size_portfolio

    result = size_portfolio({"BTCUSDT": D(1)}, {"BTCUSDT": history()}, START + 99 * DAY)
    # Last60: 30 of +0.5, 30 of -0.5; sample variance=15/59.
    assert abs(
        result.volatility["BTCUSDT"]
        - D("9.63309971761382346709657932997827642496520374382991792029492")
    ) < D("1e-55")
    assert abs(
        result.weights["BTCUSDT"]
        - D("0.0415234983261527367714117392123264518044162207039974544144219")
    ) < D("1e-55")
    assert len(result.common_days) == 60
    assert result.flat_reason is None


@pytest.mark.parametrize("count", [59, 60])
def test_individual_return_warmup_boundary(count):
    from crypto_grid_bot.trend.sizing import size_portfolio

    result = size_portfolio(
        {"BTCUSDT": D(1)}, {"BTCUSDT": history(range(count))}, START + (count - 1) * DAY
    )
    assert (result.weights["BTCUSDT"] > 0) == (count == 60)


@pytest.mark.parametrize("common", [39, 40])
def test_covariance_calendar_overlap_boundary(common):
    from crypto_grid_bot.trend.sizing import size_portfolio

    sparse = history([*range(40), *range(100 - common, 100)])
    result = size_portfolio(
        {"BTCUSDT": D(1), "ETHUSDT": D(1)},
        {"BTCUSDT": history(), "ETHUSDT": sparse},
        START + 99 * DAY,
    )
    assert len(result.common_days) == common
    assert (result.weights["BTCUSDT"] > 0) == (common == 40)
    if common == 39:
        assert result.flat_reason == "insufficient_common_days"


def test_zero_and_excluded_signals_do_not_reduce_covariance_overlap():
    from crypto_grid_bot.trend.sizing import size_portfolio

    expected = size_portfolio({"BTCUSDT": D(1)}, {"BTCUSDT": history()}, START + 99 * DAY)
    result = size_portfolio(
        {"BTCUSDT": D(1), "ETHUSDT": D(1), "ADAUSDT": D(0)},
        {"BTCUSDT": history(), "ETHUSDT": history(range(60)), "ADAUSDT": ()},
        START + 99 * DAY,
        excluded=frozenset({"ETHUSDT"}),
    )
    assert result.weights["BTCUSDT"] == expected.weights["BTCUSDT"]
    assert result.weights["ETHUSDT"] == result.weights["ADAUSDT"] == 0
    assert len(result.common_days) == 60


def test_zero_volatility_and_exact_offset_singular_book_are_flat():
    from crypto_grid_bot.trend.sizing import size_portfolio

    zero = size_portfolio({"BTCUSDT": D(1)}, {"BTCUSDT": history(amplitude="0")}, START + 99 * DAY)
    assert zero.weights == {"BTCUSDT": D(0)}
    result = size_portfolio(
        {"BTCUSDT": D(1), "ETHUSDT": D(-1)},
        {"BTCUSDT": history(), "ETHUSDT": history()},
        START + 99 * DAY,
    )
    assert result.weights == {"BTCUSDT": D(0), "ETHUSDT": D(0)}
    assert result.flat_reason == "zero_portfolio_volatility"


@pytest.mark.parametrize("multiple", [1, 2, 3])
def test_coin_cap_then_proportional_gross_cap(multiple):
    from crypto_grid_bot.trend.sizing import size_portfolio

    symbols = (
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "LTCUSDT",
        "LINKUSDT",
        "TRXUSDT",
    )
    one = size_portfolio(
        {symbols[0]: D(-1)},
        {symbols[0]: history(amplitude=".001")},
        START + 99 * DAY,
        multiple=multiple,
    )
    assert one.weights[symbols[0]] == -D(".1") * multiple
    result = size_portfolio(
        dict.fromkeys(symbols, D(1)),
        dict.fromkeys(symbols, history(amplitude=".001")),
        START + 99 * DAY,
        multiple=multiple,
    )
    assert set(result.weights.values()) == {D(".08") * multiple}
    assert sum(result.weights.values()) == D(".8") * multiple


def test_prefix_mapping_order_and_ambient_context_do_not_change_weights():
    from crypto_grid_bot.trend.sizing import size_portfolio

    signals = {"BTCUSDT": D(".6"), "ETHUSDT": D("-.2")}
    returns = {"BTCUSDT": history(), "ETHUSDT": history(amplitude=".1")}
    expected = size_portfolio(signals, returns, START + 79 * DAY)
    with localcontext() as context:
        context.prec = 3
        context.rounding = ROUND_DOWN
        context.Emax = 4
        context.Emin = -4
        actual = size_portfolio(
            dict(reversed(list(signals.items()))),
            {key: rows[:80] for key, rows in returns.items()},
            START + 79 * DAY,
        )
    assert actual == expected


@pytest.mark.parametrize(
    "multiple,signal", [(0, "1"), (4, "1"), (True, "1"), (2, "NaN"), (2, "1.1")]
)
def test_sizing_rejects_invalid_configuration(multiple, signal):
    from crypto_grid_bot.trend.sizing import size_portfolio

    with pytest.raises(ValueError):
        size_portfolio(
            {"BTCUSDT": D(signal)}, {"BTCUSDT": history()}, START + 99 * DAY, multiple=multiple
        )


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "-1.1"])
def test_invalid_return_values_fail_closed(bad):
    from crypto_grid_bot.trend.sizing import DailyReturn, size_portfolio

    with pytest.raises(ValueError):
        size_portfolio({"BTCUSDT": D(1)}, {"BTCUSDT": [DailyReturn(START, D(bad))]}, START)


def test_duplicate_return_dates_and_reserved_decision_are_rejected():
    from crypto_grid_bot.trend.sizing import size_portfolio

    rows = history(range(60))
    with pytest.raises(ValueError, match="ordered"):
        size_portfolio({"BTCUSDT": D(1)}, {"BTCUSDT": [*rows, rows[-1]]}, START + 59 * DAY)
    with pytest.raises(ValueError):
        size_portfolio({}, {}, month_bounds_ms("2025-01")[0])


def test_old_individual_returns_do_not_extend_covariance_calendar_window():
    from crypto_grid_bot.trend.sizing import size_portfolio

    result = size_portfolio({"BTCUSDT": D(1)}, {"BTCUSDT": history(range(60))}, START + 119 * DAY)
    assert result.raw_weights["BTCUSDT"] > 0
    assert result.common_days == ()
    assert result.weights["BTCUSDT"] == 0


def test_positive_singular_covariance_needs_no_inverse():
    from crypto_grid_bot.trend.sizing import size_portfolio

    result = size_portfolio(
        {"BTCUSDT": D(1), "ETHUSDT": D(1)},
        {"BTCUSDT": history(), "ETHUSDT": history()},
        START + 99 * DAY,
    )
    expected = D("0.02076174916307636838570586960616322590220811035199872720721095")
    assert abs(result.weights["BTCUSDT"] - expected) < D("1e-55")
    assert result.weights["BTCUSDT"] == result.weights["ETHUSDT"]
