"""Gap-aware Wilder indicators (spec v2 §3): warm-up indices, zero cases, recursions.

Every index below is pinned by the spec's minimum-bars table. The ADX parity test holds
the module to V0's float ``SeriesFeatures._wilder_adx`` on a long series.
"""

from __future__ import annotations

import random
from decimal import Decimal as D
from decimal import getcontext

import pytest

from crypto_grid_bot.backtest.features import SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.strategy.indicators import (
    Bar,
    bollinger_width,
    rolling_median,
    sma,
    wilder_adx,
    wilder_atr,
    wilder_rsi,
)


def test_sma_values_and_warmup():
    assert sma([D(1), D(2), D(3), D(4), D(5)], 3) == [None, None, D(2), D(3), D(4)]


def test_rsi_first_value_index_and_extremes():
    rising = [D(i) for i in range(1, 17)]
    assert wilder_rsi(rising)[13] is None and wilder_rsi(rising)[14] == D(100)
    alternating = [D(10 + (i % 2)) for i in range(30)]
    rsi = wilder_rsi(alternating)
    assert rsi[14] == D(50)  # the seed: 7 gains and 7 losses of 1
    # The Wilder recursion, not a rolling mean (which would stay at 50):
    assert rsi[15].quantize(D("0.0001")) == D("53.5714")
    assert rsi[29].quantize(D("0.0001")) == D("52.4612")


def test_atr_constant_true_range():
    bars = [Bar(i, D(12), D(10), D(11)) for i in range(20)]
    assert wilder_atr(bars)[13] is None and wilder_atr(bars)[14] == D(2)


def test_adx_first_indices_and_perfect_trend():
    bars = [Bar(i, D(100 + i), D(99 + i), D("99.5") + i) for i in range(40)]
    adx, plus_di, minus_di = wilder_adx(bars)
    assert plus_di[13] is None and plus_di[14] is not None
    assert adx[26] is None and adx[27] == D(100)
    assert minus_di[30] == D(0)


def test_flat_series_zero_cases():
    assert wilder_rsi([D(5)] * 20)[14] == D(50)  # no gains and no losses
    adx, plus_di, minus_di = wilder_adx([Bar(i, D(5), D(5), D(5)) for i in range(40)])
    assert plus_di[14] == D(0) and minus_di[14] == D(0) and adx[27] == D(0)


def test_bollinger_width_zero_on_flat_closes():
    assert bollinger_width([D(5)] * 20)[19] == D(0)


def test_rolling_median_skips_none_and_averages_even_middle():
    assert rolling_median([D(1), None, D(3), D(2), D(4)], 4)[4] == D("2.5")


# ---------------------------------------------------------------------------
# Warm-up indices and alignment


def test_outputs_align_with_input_and_warm_up_exactly():
    closes = [D(100 + (i * 7) % 11) for i in range(60)]
    bars = [Bar(i, c + 1, c - 1, c) for i, c in enumerate(closes)]
    adx, plus_di, minus_di = wilder_adx(bars)
    series = {
        "sma": (sma(closes, 5), 4),
        "rsi": (wilder_rsi(closes), 14),
        "atr": (wilder_atr(bars), 14),
        "plus_di": (plus_di, 14),
        "minus_di": (minus_di, 14),
        "adx": (adx, 27),
        "bollinger": (bollinger_width(closes), 19),
        "median": (rolling_median(sma(closes, 5), 10), 13),  # 10 values, the first at index 4
    }
    for name, (values, first) in series.items():
        assert len(values) == 60, name
        assert all(v is None for v in values[:first]), name
        assert all(v is not None for v in values[first:]), name


def test_series_shorter_than_the_minimum_give_only_none():
    closes = [D(i + 1) for i in range(14)]  # RSI and ATR need 15 bars
    bars = [Bar(i, c + 1, c - 1, c) for i, c in enumerate(closes)]
    assert wilder_rsi(closes) == [None] * 14
    assert wilder_atr(bars) == [None] * 14
    assert wilder_adx(bars) == ([None] * 14,) * 3
    assert sma(closes[:4], 5) == [None] * 4
    assert bollinger_width([D(i + 1) for i in range(19)]) == [None] * 19  # needs 20
    assert wilder_rsi([]) == [] and wilder_adx([]) == ([], [], [])


def test_adx_needs_28_bars_where_v0_waits_for_a_29th():
    bars = [Bar(i, D(100 + i), D(99 + i), D("99.5") + i) for i in range(28)]
    adx, plus_di, _ = wilder_adx(bars)
    assert adx[26] is None and adx[27] == D(100)
    assert plus_di[14] is not None
    klines = [Kline(b.open_ms, b.close, b.high, b.low, b.close, D(1), D(1), D(0)) for b in bars]
    assert SeriesFeatures("TEST", klines).adx14 == [None] * 28  # features.py:154, n <= 2 × period


# ---------------------------------------------------------------------------
# Definitions


def test_rsi_of_falling_closes_is_zero():
    falling = [D(30 - i) for i in range(20)]
    assert wilder_rsi(falling)[14] == D(0)


def test_atr_true_range_uses_the_previous_elements_close():
    # H-L = 1, |H - prev close| = 5.5, |L - prev close| = 4.5: the gap up decides.
    bars = [Bar(0, D(10), D(9), D("9.5")), Bar(1, D(15), D(14), D("14.5"))]
    assert wilder_atr(bars, period=1)[1] == D("5.5")


def test_atr_wilder_recursion_after_the_seed():
    bars = [Bar(i, D(12), D(10), D(11)) for i in range(15)]  # TR = 2 from index 1
    bars.append(Bar(15, D(27), D(11), D(20)))  # TR = 16
    bars.append(Bar(16, D(21), D(19), D(20)))  # TR = 2
    atr = wilder_atr(bars)
    assert atr[14] == D(2)
    assert atr[15] == D(3)  # (2 × 13 + 16) ÷ 14
    # (3 × 13 + 2) ÷ 14, where a rolling mean of the last 14 true ranges would give 3.
    assert atr[16].quantize(D("0.000000001")) == (D(41) / 14).quantize(D("0.000000001"))


def test_indicators_ignore_open_times_so_a_gap_is_skipped_by_construction():
    prices = [D(100 + (i * 5) % 9) for i in range(45)]
    contiguous = [Bar(i * 3_600_000, c + 2, c - 1, c) for i, c in enumerate(prices)]
    gapped = [
        Bar(i * 3_600_000 + (i >= 20) * 7_200_000, c + 2, c - 1, c) for i, c in enumerate(prices)
    ]
    assert wilder_atr(gapped) == wilder_atr(contiguous)
    assert wilder_adx(gapped) == wilder_adx(contiguous)


def test_adx_and_di_recursions_by_hand_with_period_two():
    # (high, low, close): TR = 3, 4, 5, 4 and +DM = 2, 0, 2, 0 and -DM = 0, 2, 0, 1 from index 1.
    rows = [(10, 8, 9), (12, 9, 11), (11, 7, 8), (13, 10, 12), (13, 9, 10)]
    bars = [Bar(i, D(h), D(low), D(c)) for i, (h, low, c) in enumerate(rows)]
    adx, plus_di, minus_di = wilder_adx(bars, period=2)
    # i=2: sums 7, 2, 2 (the seed over indices 1..2).
    # i=3: 7 + 5 − 7÷2 = 8.5; 2 + 2 − 1 = 3; 2 + 0 − 1 = 1; DX = 50, the first ADX is 25.
    # i=4: 8.5 + 4 − 4.25 = 8.25; 3 + 0 − 1.5 = 1.5; 1 + 1 − 0.5 = 1.5; DX = 0, ADX = 12.5.
    assert plus_di[:2] == [None, None] and minus_di[:2] == [None, None]
    assert adx[:3] == [None, None, None]
    places = D("0.0000001")
    assert [v.quantize(places) for v in plus_di[2:]] == [
        (D(200) / 7).quantize(places),
        (D(600) / 17).quantize(places),
        (D(200) / 11).quantize(places),
    ]
    assert [v.quantize(places) for v in minus_di[2:]] == [
        (D(200) / 7).quantize(places),
        (D(200) / 17).quantize(places),
        (D(200) / 11).quantize(places),
    ]
    assert adx[3] == D(25) and adx[4] == D("12.5")


def test_rsi_with_period_one_is_the_latest_change_alone():
    # The seed is the first change and the recursion keeps nothing of the earlier ones.
    rsi = wilder_rsi([D(10), D(11), D(10), D(10), D(12)], period=1)
    assert rsi == [None, D(100), D(0), D(50), D(100)]


def test_adx_with_period_one_starts_at_index_one_and_is_each_bars_dx():
    # (high, low, close): bar 1 moves up, bar 2 is an inside-equal bar, bar 3 moves down.
    rows = [(10, 8, 9), (12, 9, 11), (12, 9, 10), (11, 7, 8)]
    bars = [Bar(i, D(h), D(low), D(c)) for i, (h, low, c) in enumerate(rows)]
    adx, plus_di, minus_di = wilder_adx(bars, period=1)
    assert adx[0] is None and plus_di[0] is None and minus_di[0] is None
    assert adx[1:] == [D(100), D(0), D(100)]  # ADX is first defined at 2 × 1 − 1 = 1
    places = D("0.0000001")
    assert plus_di[1].quantize(places) == (D(200) / 3).quantize(places)  # 100 × 2 ÷ TR 3
    assert minus_di[1] == D(0)
    assert plus_di[2] == D(0) and minus_di[2] == D(0)  # no movement, a true range of 3
    assert plus_di[3] == D(0) and minus_di[3] == D(50)  # 100 × 2 ÷ TR 4


def test_downtrend_mirrors_the_perfect_uptrend():
    bars = [Bar(i, D(200 - i), D(199 - i), D("199.5") - i) for i in range(40)]
    adx, plus_di, minus_di = wilder_adx(bars)
    assert plus_di[30] == D(0)
    assert minus_di[30] > D(0)
    assert adx[27] == D(100)


def _random_walk(count: int) -> tuple[list[Bar], list[Kline]]:
    """The same seeded pseudo-random OHLC series as Bars and as V0's Klines."""
    rng = random.Random(2026)
    price, bars, klines = D(100), [], []
    for i in range(count):
        price += D(rng.randint(-300, 320)) / D(100)
        high, low = price + D(rng.randint(0, 150)) / D(100), price - D(rng.randint(0, 150)) / D(100)
        close = low + (high - low) * D(rng.randint(0, 100)) / D(100)
        bars.append(Bar(i, high, low, close))
        klines.append(Kline(i, close, high, low, close, D(1), D(1), D(0)))
    return bars, klines


def test_adx_matches_v0_float_implementation_on_a_long_series():
    bars, klines = _random_walk(400)
    adx, _, _ = wilder_adx(bars)
    v0 = SeriesFeatures("TEST", klines).adx14
    assert all(v is None for v in adx[:27]) and all(v is None for v in v0[:27])
    for i in range(27, 400):  # 373 values, from the 28th bar
        assert adx[i] is not None and v0[i] is not None
        assert float(adx[i]) == pytest.approx(v0[i], abs=1e-9)


def test_adx_stays_within_zero_and_one_hundred_and_reaches_both_bounds_exactly():
    # V0 clamps its float ADX to [0, 100]; exact Decimal arithmetic needs no clamp, because
    # DX = 100 × |+DI − −DI| ÷ (+DI + −DI) cannot pass 100 and every ADX is an average of DX.
    perfect = [Bar(i, D(100 + i), D(99 + i), D("99.5") + i) for i in range(60)]
    adx, _, _ = wilder_adx(perfect)
    assert all(v == D(100) for v in adx[27:])  # exactly 100, never above
    flat = [Bar(i, D(5), D(5), D(5)) for i in range(60)]
    adx, _, _ = wilder_adx(flat)
    assert all(v == D(0) for v in adx[27:])  # exactly 0, never below
    bars, _ = _random_walk(400)
    adx, plus_di, minus_di = wilder_adx(bars)
    assert all(v is not None and D(0) <= v <= D(100) for v in adx[27:])
    assert all(v is not None and D(0) <= v <= D(100) for v in plus_di[14:] + minus_di[14:])


def test_sma_equal_closes_and_exact_division():
    assert sma([D("1.5")] * 3, 3)[2] == D("1.5")
    assert sma([D(1), D(2)], 2) == [None, D("1.5")]


def test_bollinger_width_is_the_population_band_over_the_middle():
    closes = [D(1), D(3)] * 10  # middle 2, population sigma 1 (a sample sigma would not be 1)
    assert bollinger_width(closes)[19] == D(2)  # 2 × 2 × 1 ÷ 2
    assert bollinger_width(closes, deviations=3)[19] == D(3)
    assert bollinger_width(closes)[18] is None


def test_bollinger_width_none_where_the_middle_is_zero():
    assert bollinger_width([D(0)] * 20)[19] is None


def test_rolling_median_window_and_warmup():
    values = [D(5), D(1), D(3), D(2), D(4)]
    # size 3 (odd): the middle value of the last three
    assert rolling_median(values, 3) == [None, None, D(3), D(2), D(3)]
    # size 4 (even): the mean of the two middle values
    assert rolling_median(values, 4) == [None, None, None, D("2.5"), D("2.5")]
    assert rolling_median([D(2), D(2), D(2), D(2), D(7)], 4)[4] == D(2)


def test_rolling_median_looks_back_past_none_and_carries_across_it():
    values = [D(1), None, None, D(3), D(2), None, D(4)]
    medians = rolling_median(values, 3)
    assert medians[:4] == [None, None, None, None]  # only 2 values exist at index 3
    assert medians[4] == D(2)  # 1, 3, 2
    assert medians[5] == D(2)  # no new value: the same last three
    assert medians[6] == D(3)  # 3, 2, 4


def test_rolling_median_drops_the_oldest_of_equal_values():
    values = [D(1), D(1), D(1), D(9), D(9), D(9)]
    assert rolling_median(values, 3) == [None, None, D(1), D(1), D(9), D(9)]


@pytest.mark.parametrize(
    "call",
    [
        lambda: sma([D(1)], 0),
        lambda: wilder_rsi([D(1)], period=0),
        lambda: wilder_atr([], period=0),
        lambda: wilder_adx([], period=0),
        lambda: bollinger_width([D(1)], length=0),
        lambda: bollinger_width([D(1)], deviations=0),
        lambda: bollinger_width([D(1)], deviations=-2),
        lambda: rolling_median([D(1)], 0),
    ],
)
def test_non_positive_parameters_are_rejected(call):
    with pytest.raises(ValueError):
        call()


def test_results_are_decimal_and_leave_the_callers_precision_alone():
    before = getcontext().prec
    closes = [D(100 + (i * 7) % 11) / D(3) for i in range(40)]
    bars = [Bar(i, c + 1, c - 1, c) for i, c in enumerate(closes)]
    adx, plus_di, minus_di = wilder_adx(bars)
    for series in (
        sma(closes, 20),
        wilder_rsi(closes),
        wilder_atr(bars),
        adx,
        plus_di,
        minus_di,
        bollinger_width(closes),
        rolling_median(closes, 7),
    ):
        assert all(v is None or isinstance(v, D) for v in series)
    assert getcontext().prec == before
