"""V4 engine task 3: the per-coin signal state (three speeds, downtrend, L, S and s).

Hand-checkable cases use small lookbacks, so a rule can be read off a few bars. The main,
faster and slower lookbacks are checked against a slow from-scratch reference, and the main
lookbacks against V3's ``trend.signals.signal_series`` on pre-2025 bars (the only place a test
may call V3's guarded code). Every bar here is synthetic; no network, no real data.
"""

from __future__ import annotations

import itertools
import random
from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_DOWN, Decimal, localcontext
from typing import Any

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.v4.engine.arms import (
    FASTER_LOOKBACKS,
    MAIN_LOOKBACKS,
    SLOWER_LOOKBACKS,
    Lookbacks,
)
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.signals import (
    CoinSignals,
    SignalReading,
    long_fraction,
    medium_vote,
    short_fraction,
)

D = Decimal
DAY = 86_400_000
START = month_bounds_ms("2021-01")[0]

# Small windows, so a few bars warm everything: fast 3, EMAs 3 and 6, Donchian 5 and 3, slow 12,
# trend SMA 5 with a 3-bar slope, and 3-bar highs and lows.
SCENARIO = Lookbacks(
    fast=3,
    ema_fast=3,
    ema_slow=6,
    donchian_entry=5,
    donchian_exit=3,
    slow=12,
    trend_sma=5,
    trend_slope=3,
    trend_window=3,
)
# Medium warms at bar 6, but the downtrend needs 40 bars.
LATE_TREND = replace(SCENARIO, trend_sma=30, trend_slope=10)
EMA_LOOKBACKS = Lookbacks(
    fast=2,
    ema_fast=3,
    ema_slow=7,
    donchian_entry=4,
    donchian_exit=2,
    slow=6,
    trend_sma=3,
    trend_slope=2,
    trend_window=2,
)
DONCHIAN_LOOKBACKS = Lookbacks(
    fast=2,
    ema_fast=2,
    ema_slow=3,
    donchian_entry=4,
    donchian_exit=2,
    slow=3,
    trend_sma=3,
    trend_slope=2,
    trend_window=2,
)


def bar(day: int, close: Any, high: Any = None, low: Any = None) -> Kline:
    value = D(str(close))
    top = value if high is None else D(str(high))
    bottom = value if low is None else D(str(low))
    return Kline(START + day * DAY, value, top, bottom, value, D(0), D(0), D(0))


def ranged(closes: list[int], first_day: int = 0) -> list[Kline]:
    """Bars that close at each value and range half a point either way."""
    return [
        bar(first_day + i, close, D(close) + D("0.5"), D(close) - D("0.5"))
        for i, close in enumerate(closes)
    ]


def feed(lookbacks: Lookbacks, bars: list[Kline]) -> list[SignalReading]:
    signals = CoinSignals(lookbacks)
    return [signals.update(item) for item in bars]


DRIFTS = (70, -70, 90, -90, 50, -50, 80)


def walk(count: int, seed: int, regime: int = 60, wick: int = 100) -> list[Kline]:
    """A seeded random walk of UTC daily bars with trending regimes, from 2021-01-01.

    ``wick`` is the most, in basis points, that a high or low may stick out past the open-close
    range.
    """
    rng = random.Random(seed)
    close = D("100")
    out = []
    for day in range(count):
        bps = DRIFTS[(day // regime) % len(DRIFTS)] + rng.randint(-250, 250)
        new = max(D(1), (close * (10000 + bps) / 10000).quantize(D("0.0001")))
        up = D(rng.randint(0, wick)) / 10000
        down = D(rng.randint(0, wick)) / 10000
        high = (max(close, new) * (1 + up)).quantize(D("0.0001"))
        low = (min(close, new) * (1 - down)).quantize(D("0.0001"))
        out.append(Kline(START + day * DAY, close, high, low, new, D(0), D(0), D(0)))
        close = new
    return out


def reference(bars: list[Kline], lb: Lookbacks) -> list[SignalReading]:
    """Every reading recomputed from scratch with plain list slices: slow, and obviously right.

    "Prior n" is the n bars ending the bar before (V3: ``self._bars[-n:]`` before the new bar is
    appended); a downtrend window includes the current bar.
    """
    out = []
    state = 0
    with localcontext(CONTEXT):
        for i, current in enumerate(bars):
            seen = bars[: i + 1]
            prior = bars[:i]
            closes = [item.close for item in seen]
            n = len(seen)

            def sma(length: int, upto: int = n, closes: list[Decimal] = closes) -> Decimal | None:
                if upto < length:
                    return None
                return sum(closes[upto - length : upto], D(0)) / D(length)

            def ema(length: int, n: int = n, closes: list[Decimal] = closes) -> Decimal | None:
                if n < length:
                    return None
                value = sum(closes[:length], D(0)) / D(length)
                alpha = D(2) / D(length + 1)
                for close in closes[length:]:
                    value = alpha * close + (D(1) - alpha) * value
                return value

            donchian = None
            if len(prior) >= lb.donchian_entry:
                high = max(item.high for item in prior[-lb.donchian_entry :])
                low = min(item.low for item in prior[-lb.donchian_entry :])
                if current.close > high:
                    state = 1
                elif current.close < low:
                    state = -1
                elif (
                    state > 0
                    and current.close < min(item.low for item in prior[-lb.donchian_exit :])
                    or state < 0
                    and current.close > max(item.high for item in prior[-lb.donchian_exit :])
                ):
                    state = 0
                donchian = state

            def side(line: Decimal | None, close: Decimal = current.close) -> int | None:
                if line is None or close == line:
                    return None
                return 1 if close > line else -1

            sma_trend = sma(lb.trend_sma)
            lagged = sma(lb.trend_sma, n - lb.trend_slope)
            tw = lb.trend_window
            high_recent = max(item.high for item in seen[-tw:]) if n >= tw else None
            high_prior = max(item.high for item in seen[-2 * tw : -tw]) if n >= 2 * tw else None
            low_recent = min(item.low for item in seen[-tw:]) if n >= tw else None
            low_prior = min(item.low for item in seen[-2 * tw : -tw]) if n >= 2 * tw else None
            downtrend = None
            if None not in (sma_trend, lagged, high_recent, high_prior, low_recent, low_prior):
                downtrend = bool(
                    current.close < sma_trend
                    and sma_trend < lagged
                    and high_recent < high_prior
                    and low_recent < low_prior
                )

            sma_fast, sma_slow = sma(lb.fast), sma(lb.slow)
            ema_fast, ema_slow = ema(lb.ema_fast), ema(lb.ema_slow)
            fast, slow = side(sma_fast), side(sma_slow)
            medium = None
            if ema_fast is not None and ema_slow is not None and donchian is not None:
                ema_vote = 0 if ema_fast == ema_slow else (1 if ema_fast > ema_slow else -1)
                mean = D(ema_vote + donchian) / D(2)
                medium = 1 if mean > 0 else (-1 if mean < 0 else None)

            short = D(0)
            if medium == -1 and downtrend is True:
                short = (D("0.5") if fast == -1 else D("0.25")) * (D(2) if slow == -1 else D(1))
            long = D(sum(vote == 1 for vote in (fast, medium, slow))) / D(3)
            out.append(
                SignalReading(
                    day_ms=current.open_ms,
                    close=current.close,
                    sma_fast=sma_fast,
                    sma_slow=sma_slow,
                    ema_fast=ema_fast,
                    ema_slow=ema_slow,
                    donchian=donchian,
                    sma_trend=sma_trend,
                    sma_trend_lagged=lagged,
                    high_recent=high_recent,
                    high_prior=high_prior,
                    low_recent=low_recent,
                    low_prior=low_prior,
                    fast=fast,
                    medium=medium,
                    slow=slow,
                    downtrend=downtrend,
                    L=long,
                    S=short,
                    s=-short if short > 0 else long,
                    s_long_only=long,
                )
            )
    return out


# --- EMA, SMA and Donchian -----------------------------------------------------------------


def test_ema_seeds_with_the_simple_mean_then_recurses() -> None:
    closes = [10, 12, 11, 14, 13, 16, 15, 17, 18, 16]
    readings = feed(EMA_LOOKBACKS, [bar(i, c) for i, c in enumerate(closes)])
    # EMA(3) seeds at bar 3 with (10 + 12 + 11) / 3 = 11, then 0.5 x close + 0.5 x previous.
    assert [r.ema_fast for r in readings] == [
        None,
        None,
        D(11),
        D("12.5"),
        D("12.75"),
        D("14.375"),
        D("14.6875"),
        D("15.84375"),
        D("16.921875"),
        D("16.4609375"),
    ]
    # EMA(7) seeds at bar 7 with 91 / 7 = 13, then 0.25 x close + 0.75 x previous.
    assert [r.ema_slow for r in readings] == [None] * 6 + [D(13), D(14), D(15), D("15.25")]
    # The simple means are the last n closes, whatever came before.
    assert [r.sma_fast for r in readings[:5]] == [None, D(11), D("11.5"), D("12.5"), D("13.5")]
    assert readings[4].sma_slow is None
    assert readings[6].sma_slow == D("13.5")  # (12 + 11 + 14 + 13 + 16 + 15) / 6


# Each row: close, high, low. Donchian 4 (entry) and 2 (exit); needs 5 bars.
DONCHIAN_BARS = [
    (10, 11, 9),
    (10, 11, 9),
    (10, 11, 9),
    (10, 11, 9),
    (10, 11, 9),  # i4: first warm bar, inside the channel: flat
    (12, 12.5, 10),  # i5: above the prior 4 highs (11): long
    (12.6, 13, 12),  # i6: above 12.5: still long
    (13, 13.5, 12.5),  # i7: equal to the prior high 13, not above it: unchanged
    (12.1, 12.4, 11.5),  # i8: above the prior 2 lows (12 and 12.5, min 12): the long stays
    (11.4, 12.0, 11.0),  # i9: below the prior 2 lows (min 11.5), above the 4-bar low (10): exit
    (11.0, 11.6, 10.8),  # i10: equal to the prior 4 lows' min (11.0), not below it: flat
    (10.9, 11.2, 10.5),  # i11: above the prior 4 lows' min (10.8): flat
    (10.0, 11.0, 9.8),  # i12: below the prior 4 lows' min (10.5): short
    (10.2, 10.6, 9.9),  # i13: below the prior 2 highs' max (11.2): the short stays
    (11.5, 11.8, 10.9),  # i14: above the prior 2 highs (11.0), below the 4-bar high (11.6): exit
    (13.0, 13.2, 11.4),  # i15: above the prior 4 highs (11.8): long
    (9.0, 12.5, 8.8),  # i16: breaks the long's exit and the 4-bar low (9.8): reverses to short
    (14.0, 14.2, 9.5),  # i17: breaks the short's exit and the 4-bar high (13.2): reverses to long
]
EXPECTED_DONCHIAN = [None] * 4 + [0, 1, 1, 1, 1, 0, 0, 0, -1, -1, 0, 1, -1, 1]


def test_donchian_enters_exits_and_reverses_as_v3_r3() -> None:
    bars = [bar(i, *row) for i, row in enumerate(DONCHIAN_BARS)]
    readings = feed(DONCHIAN_LOOKBACKS, bars)
    assert [r.donchian for r in readings] == EXPECTED_DONCHIAN


def test_donchian_needs_entry_plus_one_bars_and_starts_flat() -> None:
    readings = feed(MAIN_LOOKBACKS, [bar(i, 10) for i in range(57)])
    assert all(r.donchian is None for r in readings[:55])
    assert readings[55].donchian == 0
    assert readings[56].donchian == 0


def test_donchian_prior_window_excludes_the_current_bar_and_is_strict() -> None:
    # 55 flat bars, then a close at the prior high: no entry. A close above it: entry.
    flat = [bar(i, 10) for i in range(55)]
    tie = feed(MAIN_LOOKBACKS, flat + [bar(55, 10)])
    assert tie[-1].donchian == 0
    breakout = feed(MAIN_LOOKBACKS, flat + [bar(55, 11)])
    assert breakout[-1].donchian == 1
    # A high older than 55 bars is out of the window; one 55 bars back is in.
    old_high = [bar(0, 10, 12, 10)] + [bar(i, 10) for i in range(1, 56)]
    assert feed(MAIN_LOOKBACKS, old_high + [bar(56, 11)])[-1].donchian == 1
    in_window = [bar(0, 10), bar(1, 10, 12, 10)] + [bar(i, 10) for i in range(2, 56)]
    assert feed(MAIN_LOOKBACKS, in_window + [bar(56, 11)])[-1].donchian == 0


def test_donchian_matches_v3_on_the_scripted_reversal() -> None:
    from crypto_grid_bot.trend.signals import signal_series

    # V3's own case: a breakout, a 70-day gap (no state reset), then a close under the prior
    # 55 and 20 lows, which reverses a long straight to short.
    bars = [bar(i, 10) for i in range(55)] + [bar(55, 11), bar(70, 10), bar(71, 9)]
    mine = [r.donchian for r in feed(MAIN_LOOKBACKS, bars)][-3:]
    assert mine == [1, 1, -1]
    assert [int(p.rule("R3")) for p in signal_series(bars)][-3:] == mine


FLAT_ROW = (10, 11, 9)
# name: head rows, filler row, marker row, probe row, filler count, {marker distance: state}.
# The marker bar sits `distance` bars before the probe bar. Each Donchian window holds exactly
# the prior n bars (entry 4, exit 2): a marker n bars back still counts, one n + 1 back does not.
WINDOW_CASES = {
    "entry high": (
        [FLAT_ROW] * 5,
        FLAT_ROW,
        (10, 15, 9),
        (12, 12.5, 10),
        5,
        {1: 0, 4: 0, 5: 1},
    ),
    "entry low": (
        [FLAT_ROW] * 5,
        FLAT_ROW,
        (10, 11, 5),
        (8, 9, 7.5),
        5,
        {1: 0, 4: 0, 5: -1},
    ),
    "long exit": (
        [*[FLAT_ROW] * 5, (12, 12.5, 10)],
        (12, 12.5, 11.9),
        (12, 12.5, 10.5),
        (11, 11.5, 10.8),
        3,
        {1: 1, 2: 1, 3: 0},
    ),
    "short exit": (
        [*[FLAT_ROW] * 5, (8, 8.5, 7.5)],
        (8, 8.1, 7.9),
        (8, 9.9, 7.9),
        (9, 9.2, 8.8),
        3,
        {1: -1, 2: -1, 3: 0},
    ),
}


@pytest.mark.parametrize(
    ("case", "distance", "expected"),
    [(case, d, state) for case, row in WINDOW_CASES.items() for d, state in row[5].items()],
)
def test_donchian_windows_hold_exactly_the_prior_n_bars(
    case: str, distance: int, expected: int
) -> None:
    head, filler, marker, probe, gap, _ = WINDOW_CASES[case]
    middle = [filler] * gap
    middle[gap - distance] = marker
    rows = [*head, *middle, probe]
    readings = feed(DONCHIAN_LOOKBACKS, [bar(i, *row) for i, row in enumerate(rows)])
    assert readings[-1].donchian == expected


# --- gaps and bad bars ---------------------------------------------------------------------


def test_a_missing_day_adds_no_observation_and_resets_nothing() -> None:
    source = walk(70, seed=11)
    contiguous = feed(SCENARIO, source)
    # Drop days at several places, one of them a long hole: the bars that remain are the
    # same observations, so every value matches the contiguous run's value for that bar.
    days = [i + (i // 7) * 3 + (40 if i >= 50 else 0) for i in range(len(source))]
    gapped_bars = [
        replace(item, open_ms=START + day * DAY) for item, day in zip(source, days, strict=True)
    ]
    gapped = feed(SCENARIO, gapped_bars)
    assert [r.day_ms for r in gapped] == [START + day * DAY for day in days]
    assert [replace(r, day_ms=0) for r in gapped] == [replace(r, day_ms=0) for r in contiguous]


def test_bad_bars_are_refused_before_changing_state() -> None:
    good = [bar(3, 10), bar(4, 11)]
    signals = CoinSignals(SCENARIO)
    signals.update(good[0])
    base = bar(4, 11)
    for bad in (
        bar(3, 11),  # the same day
        bar(2, 11),  # an earlier day
        replace(base, open_ms=START + 4 * DAY + 1),  # not midnight
        replace(base, open_ms=START + 4 * DAY + 3_600_000),  # an hour into the day
        replace(base, open_ms=-DAY),
        replace(base, open_ms=True),
        replace(base, open_ms=float(START + 4 * DAY)),
        bar(4, "NaN"),
        bar(4, "Infinity"),
        bar(4, 0),
        bar(4, -1),
        bar(4, "1e19"),
        bar(4, "0.0000000000000000001"),
        replace(base, close=11.0),  # a float is not a Decimal
        replace(base, high=D(1)),  # high under the close
        replace(base, low=D(12)),  # low over the close
    ):
        with pytest.raises(ValueError):
            signals.update(bad)
    assert signals.update(good[1]) == feed(SCENARIO, good)[1]


@pytest.mark.parametrize(
    "bad",
    [
        {"fast": 0},
        {"slow": -1},
        {"ema_fast": 2.0},
        {"donchian_entry": True},
        {"trend_slope": 0},
        {"trend_window": 0},
        {"donchian_exit": 6},  # longer than the entry window
    ],
)
def test_lookbacks_must_be_positive_ints_with_exit_not_over_entry(bad: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CoinSignals(replace(SCENARIO, **bad))


# --- L, S and s ----------------------------------------------------------------------------


def _short_expected(fast: Any, medium: Any, slow: Any, downtrend: Any) -> Decimal:
    if medium != -1 or downtrend is not True:
        return D(0)
    return (D("0.5") if fast == -1 else D("0.25")) * (D(2) if slow == -1 else D(1))


def test_short_fraction_values_0_25_0_5_and_1() -> None:
    votes = (1, -1, None)
    for fast, medium, slow, downtrend in itertools.product(
        votes, votes, votes, (True, False, None)
    ):
        assert short_fraction(fast, medium, slow, downtrend) == _short_expected(
            fast, medium, slow, downtrend
        )
    # The four values with the medium down and the downtrend confirmed.
    assert short_fraction(1, -1, 1, True) == D("0.25")
    assert short_fraction(None, -1, None, True) == D("0.25")
    assert short_fraction(-1, -1, 1, True) == D("0.5")
    assert short_fraction(1, -1, -1, True) == D("0.5")
    assert short_fraction(-1, -1, -1, True) == D(1)
    # None and False both mean the downtrend is not confirmed.
    assert short_fraction(-1, -1, -1, None) == D(0) == short_fraction(-1, -1, -1, False)

    # The same values from real bars: a steady fall of two points a day.
    fall = [100 - 2 * k for k in range(13)]  # 100, 98, ..., 76
    readings = feed(SCENARIO, ranged(fall[:8]))
    last = readings[7]  # bar 8: slow (12) still warming, fast down
    assert (last.fast, last.medium, last.slow, last.downtrend) == (-1, -1, None, True)
    assert D("0.5") == last.S

    readings = feed(SCENARIO, ranged(fall[:8] + [88]))  # bar 9 rallies above its fast SMA
    last = readings[8]
    assert last.close == D(88)
    assert (last.fast, last.medium, last.slow, last.downtrend) == (1, -1, None, True)
    assert D("0.25") == last.S

    readings = feed(SCENARIO, ranged(fall[:12]))  # bar 12: every speed is down
    last = readings[11]
    assert (last.fast, last.medium, last.slow, last.downtrend) == (-1, -1, -1, True)
    assert D(1) == last.S
    assert (last.L, last.s, last.s_long_only) == (D(0), D(-1), D(0))

    readings = feed(SCENARIO, ranged(fall[:11] + [82]))  # fast up, slow down
    last = readings[11]
    assert (last.fast, last.medium, last.slow, last.downtrend) == (1, -1, -1, True)
    assert D("0.5") == last.S
    assert last.s == D("-0.5")


def test_a_fast_rally_halves_a_short_and_medium_up_closes_it() -> None:
    fall = [100 - 2 * k for k in range(12)]  # bar 12 closes at 78
    readings = feed(SCENARIO, ranged(fall + [80, 100]))
    short, halved, closed = readings[11], readings[12], readings[13]

    assert (short.fast, short.medium, short.slow, short.downtrend) == (-1, -1, -1, True)
    assert D(1) == short.S
    assert short.s == D(-1)

    # A one-point bounce lifts the close over its fast SMA only: the short halves.
    assert (halved.fast, halved.medium, halved.slow, halved.downtrend) == (1, -1, -1, True)
    assert D("0.5") == halved.S
    assert halved.S == short.S / 2

    # A jump over the prior highs turns the medium up: no short, and s is the long fraction.
    assert closed.medium == 1
    assert D(0) == closed.S
    assert closed.s == closed.L == closed.s_long_only == D(1)

    # The medium alone closes a short, even with the fast and slow still down and a downtrend.
    assert short_fraction(-1, 1, -1, True) == D(0)
    assert short_fraction(-1, None, -1, True) == D(0)  # a tie closes it as well


def test_medium_is_the_mean_of_the_ema_vote_and_the_donchian_state() -> None:
    for ema, donchian, expected in [
        (1, 1, 1),
        (1, 0, 1),
        (0, 1, 1),
        (1, -1, None),
        (0, 0, None),
        (-1, 1, None),
        (0, -1, -1),
        (-1, 0, -1),
        (-1, -1, -1),
    ]:
        assert medium_vote(ema, donchian) == expected
    # Warm only when both votes are.
    assert medium_vote(None, 1) is None
    assert medium_vote(1, None) is None
    assert medium_vote(None, None) is None


def test_long_fraction_counts_speeds_up() -> None:
    votes = (1, -1, None)
    with localcontext(CONTEXT):
        thirds = [D(0), D(1) / D(3), D(2) / D(3), D(1)]
    for fast, medium, slow in itertools.product(votes, votes, votes):
        up = sum(vote == 1 for vote in (fast, medium, slow))
        assert long_fraction(fast, medium, slow) == thirds[up]

    # A steady rise of two points a day: the fast speed warms first, then the medium, then slow.
    rise = [100 + 2 * k for k in range(1, 15)]
    readings = feed(SCENARIO, ranged(rise))
    expected = [0, 0] + [1] * 3 + [2] * 6 + [3] * 3
    assert [r.L for r in readings] == [thirds[k] for k in expected]
    assert [r.s for r in readings] == [r.L for r in readings]
    assert [r.s_long_only for r in readings] == [r.L for r in readings]
    assert all(r.S == 0 for r in readings)
    assert (readings[2].fast, readings[2].medium, readings[2].slow) == (1, None, None)
    assert (readings[5].fast, readings[5].medium, readings[5].slow) == (1, 1, None)
    assert (readings[11].fast, readings[11].medium, readings[11].slow) == (1, 1, 1)

    # A steady fall counts no speed up.
    fall = feed(SCENARIO, ranged([100 - 2 * k for k in range(14)]))
    assert all(r.L == 0 for r in fall)


def test_warming_speeds_count_as_neither() -> None:
    readings = feed(SCENARIO, ranged([100, 98]))
    for r in readings:
        assert (r.fast, r.medium, r.slow, r.downtrend) == (None, None, None, None)
        assert (r.sma_fast, r.sma_slow, r.ema_fast, r.ema_slow, r.donchian) == (None,) * 5
        assert (r.sma_trend, r.sma_trend_lagged) == (None, None)
        assert (r.high_recent, r.high_prior, r.low_recent, r.low_prior) == (None,) * 4
        assert (r.L, r.S, r.s, r.s_long_only) == (D(0), D(0), D(0), D(0))

    # The medium is down from bar 6 but the downtrend needs 40 bars: S stays 0 while it warms,
    # and None counts as unconfirmed.
    readings = feed(LATE_TREND, ranged([100 - 2 * k for k in range(13)]))
    assert readings[5].medium == -1
    assert all(r.downtrend is None and r.S == 0 and r.s == r.L for r in readings)
    assert readings[11].slow == -1  # all three down, still no short
    assert readings[11].s == D(0)

    # A tie is neither up nor down: a flat series has no vote anywhere, and a confirmed
    # downtrend is False (warm but not met), never True.
    flat = feed(SCENARIO, [bar(i, 10) for i in range(14)])
    last = flat[-1]
    assert (last.fast, last.medium, last.slow) == (None, None, None)
    assert last.downtrend is False
    assert (last.L, last.S, last.s) == (D(0), D(0), D(0))


def _downtrend_reading(rows: list[tuple[Any, ...]]) -> SignalReading:
    return feed(SCENARIO, [bar(i, *row) for i, row in enumerate(rows)])[-1]


def _conditions(r: SignalReading) -> tuple[bool, ...]:
    """The four parts of a confirmed downtrend, read off the reading's own fields."""
    assert r.sma_trend is not None and r.sma_trend_lagged is not None
    assert r.high_recent is not None and r.high_prior is not None
    assert r.low_recent is not None and r.low_prior is not None
    return (
        r.close < r.sma_trend,
        r.sma_trend < r.sma_trend_lagged,
        r.high_recent < r.high_prior,
        r.low_recent < r.low_prior,
    )


def _falling(closes: list[Any]) -> list[tuple[Any, ...]]:
    return [(c, D(str(c)) + D("0.5"), D(str(c)) - D("0.5")) for c in closes]


FALL = _falling([100, 99, 98, 97, 96, 95, 94, 93])


def _with(rows: list[tuple[Any, ...]], index: int, row: tuple[Any, ...]) -> list[tuple[Any, ...]]:
    return [*rows[:index], row, *rows[index + 1 :]]


def test_downtrend_windows_include_the_current_bar() -> None:
    r = _downtrend_reading(FALL)
    # SMA(5) of the last five closes, and of the five ending three bars earlier.
    assert (r.sma_trend, r.sma_trend_lagged) == (D(95), D(98))
    # The highs and lows of the last three bars (6 to 8) and of the three before them (3 to 5).
    assert (r.high_recent, r.high_prior) == (D("95.5"), D("98.5"))
    assert (r.low_recent, r.low_prior) == (D("92.5"), D("95.5"))
    assert _conditions(r) == (True, True, True, True)
    assert r.downtrend is True
    # Seven bars: SMA(5) needs eight to have a value three bars ago. Still warming.
    assert _downtrend_reading(FALL[:7]).downtrend is None


@pytest.mark.parametrize(
    ("name", "rows", "expected"),
    [
        # Only the close fails: above the SMA, and equal to it (SMA 95.5 = close 95.5).
        ("close above SMA", _with(FALL, 7, (96, 96.5, 95.5)), (False, True, True, True)),
        ("close at SMA", _with(FALL, 7, (95.5, 96, 95)), (False, True, True, True)),
        # Only the slope fails: SMA(5) now equal to, and above, its value three bars ago.
        (
            "SMA flat",
            _falling([100, 100, 100, 110, 110, 105, 100, 95]),
            (True, False, True, True),
        ),
        (
            "SMA rising",
            _falling([96, 96, 96, 110, 110, 105, 100, 95]),
            (True, False, True, True),
        ),
        # Only the highs fail: a recent high above, and equal to, the earlier three bars' 98.5.
        ("higher high", _with(FALL, 7, (93, 99, 92.5)), (True, True, False, True)),
        ("equal high", _with(FALL, 7, (93, 98.5, 92.5)), (True, True, False, True)),
        # Only the lows fail: an earlier low under, and equal to, the recent 92.5.
        ("lower earlier low", _with(FALL, 3, (97, 97.5, 90)), (True, True, True, False)),
        ("equal low", _with(FALL, 3, (97, 97.5, 92.5)), (True, True, True, False)),
    ],
)
def test_each_downtrend_condition_is_required_and_strict(
    name: str, rows: list[tuple[Any, ...]], expected: tuple[bool, ...]
) -> None:
    r = _downtrend_reading(rows)
    assert _conditions(r) == expected
    assert r.downtrend is False
    assert r.S == 0


# --- neighbours, the reference and V3 -------------------------------------------------------


def _first_warm(readings: list[SignalReading], name: str) -> int:
    return next(i + 1 for i, r in enumerate(readings) if getattr(r, name) is not None)


@pytest.mark.parametrize(
    ("lookbacks", "warm"),
    [
        # sma_fast, sma_slow, ema_fast, ema_slow, donchian, sma_trend, sma_trend_lagged,
        # high_recent, high_prior, downtrend: the bar on which each first has a value.
        (MAIN_LOOKBACKS, (20, 200, 21, 55, 56, 50, 60, 20, 40, 60)),
        (FASTER_LOOKBACKS, (15, 150, 16, 41, 42, 38, 46, 15, 30, 46)),
        (SLOWER_LOOKBACKS, (25, 250, 26, 69, 70, 62, 74, 25, 50, 74)),
    ],
)
def test_neighbour_lookbacks_change_only_the_windows(
    lookbacks: Lookbacks, warm: tuple[int, ...]
) -> None:
    bars = walk(700, seed=3, regime=45)
    readings = feed(lookbacks, bars)
    names = (
        "sma_fast",
        "sma_slow",
        "ema_fast",
        "ema_slow",
        "donchian",
        "sma_trend",
        "sma_trend_lagged",
        "high_recent",
        "high_prior",
        "downtrend",
    )
    assert tuple(_first_warm(readings, name) for name in names) == warm
    # The same rules at other windows: every reading equals the from-scratch reference.
    assert readings == reference(bars, lookbacks)
    # And the run is not vacuous: each speed goes both ways, a downtrend is confirmed and
    # refused, and shorts open.
    for speed in ("fast", "medium", "slow"):
        assert {getattr(r, speed) for r in readings} >= {1, -1}
    assert {r.downtrend for r in readings} == {None, True, False}
    assert any(r.S > 0 for r in readings)
    assert {r.donchian for r in readings} == {None, 1, 0, -1}


@pytest.mark.parametrize("seed", [3, 4, 8])
def test_matches_v3_on_pre_2025_bars(seed: int) -> None:
    from crypto_grid_bot.trend.signals import signal_series

    bars = walk(400, seed=seed, wick=300)
    assert bars[-1].open_ms < month_bounds_ms("2025-01")[0]
    v3 = signal_series(bars)
    mine = feed(MAIN_LOOKBACKS, bars)
    for i, (reading, point) in enumerate(zip(mine, v3, strict=True)):
        assert reading.day_ms == point.day_ms
        assert reading.ema_fast == point.ema21
        assert reading.ema_slow == point.ema55
        assert reading.sma_trend == point.sma50
        if i + 1 >= 56:
            assert reading.donchian == int(point.rule("R3"))
        else:
            assert reading.donchian is None
            assert point.rule("R3") == 0
    # The lagged SMA is V3's SMA(50) ten bars earlier.
    assert mine[58].sma_trend_lagged is None
    assert [r.sma_trend_lagged for r in mine[59:]] == [p.sma50 for p in v3[49:-10]]
    # V3's Donchian takes every kind of step on this path, so the match is not a flat line.
    r3 = [int(p.rule("R3")) for p in v3]
    steps = {(a, b) for a, b in itertools.pairwise(r3) if a != b}
    assert {(0, 1), (1, 0), (0, -1), (-1, 0)} <= steps
    # The reference reads V3's semantics the same way.
    assert mine == reference(bars, MAIN_LOOKBACKS)


# --- state, immutability and cost ----------------------------------------------------------


def test_history_is_bounded_by_the_windows_not_the_run_length() -> None:
    bars = walk(1300, seed=5)
    signals = CoinSignals(MAIN_LOOKBACKS)
    sizes = []
    for item in bars:
        signals.update(item)
        sizes.append(signals.history_size)
    assert sizes[250] == sizes[-1] == max(sizes)
    assert sizes[-1] < 600


def test_readings_are_frozen_and_ignore_the_callers_decimal_context() -> None:
    bars = walk(80, seed=2)
    expected = feed(SCENARIO, bars)
    with pytest.raises(FrozenInstanceError):
        expected[-1].L = D(1)  # type: ignore[misc]
    with localcontext() as context:
        context.prec = 7
        context.rounding = ROUND_DOWN
        assert feed(SCENARIO, bars) == expected
