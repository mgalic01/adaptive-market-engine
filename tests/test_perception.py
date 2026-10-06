"""Three-timeframe perception (spec v2 §3): the 4h builder, the trend-state table, point in time.

A bar of length L that opens at ``o`` is visible only from ``o + L``; at time ``t`` the bar that
should have closed last opens at ``t // L * L - L``. The tests pin both sides of that boundary on
every timeframe, then the gap rules: a missing last bar is Unavailable, older gaps are skipped, and
a masked hour never touches the daily bars.
"""

from __future__ import annotations

import dataclasses
import random
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.strategy import perception
from crypto_grid_bot.strategy.indicators import (
    Bar,
    bollinger_width,
    rolling_median,
    sma,
    wilder_adx,
    wilder_atr,
    wilder_rsi,
)
from crypto_grid_bot.strategy.perception import (
    DailyPoint,
    Perception,
    Snapshot,
    TrendState,
    four_hour_bars,
    trend_state,
)

H1 = 3_600_000
H4 = 4 * H1
DAY = 24 * H1


def kline(open_ms: int, open_: D, high: D, low: D, close: D) -> Kline:
    return Kline(open_ms, open_, high, low, close, D(1), D(1), D(0))


def walk(count: int, step_ms: int, seed: int, start_ms: int = 0) -> list[Kline]:
    """A seeded random walk, one kline per ``step_ms``, every price at least 1."""
    rng = random.Random(seed)
    price = D(100)
    klines = []
    for i in range(count):
        close = max(price + D(rng.randint(-10, 10)) / 10, D(1))
        high = max(price, close) + D(rng.randint(0, 5)) / 10
        low = min(price, close) - D(rng.randint(0, 5)) / 10
        klines.append(kline(start_ms + i * step_ms, price, high, low, close))
        price = close
    return klines


def climb(count: int, step_ms: int, slope: D, start_ms: int = 0, start: D = D(100)) -> list[Kline]:
    """Every bar moves ``slope`` and pads its range by 0.5: ADX 100 and one-sided DI."""
    klines = []
    for i in range(count):
        open_ = start + slope * i
        close = open_ + slope
        high, low = max(open_, close) + D("0.5"), min(open_, close) - D("0.5")
        klines.append(kline(start_ms + i * step_ms, open_, high, low, close))
    return klines


def bars_of(klines: list[Kline]) -> list[Bar]:
    return [Bar(k.open_ms, k.high, k.low, k.close) for k in klines]


def states_of(bars: list[Bar]) -> list[TrendState]:
    """A trend state per bar, from fresh indicator runs over ``bars``."""
    closes = [bar.close for bar in bars]
    sma20, sma50 = sma(closes, 20), sma(closes, 50)
    adx, plus_di, minus_di = wilder_adx(bars)
    return [
        trend_state(closes[i], sma20[i], sma50[i], adx[i], plus_di[i], minus_di[i])
        for i in range(len(bars))
    ]


def daily_point_at_own_close(daily: list[Kline], index: int) -> DailyPoint:
    """Daily bar ``index`` as read with no later bar in existence."""
    seen = bars_of(daily[: index + 1])
    return DailyPoint(
        seen[-1].open_ms,
        states_of(seen)[-1],
        seen[-1].close,
        wilder_atr(seen)[-1],
    )


def test_four_hour_bars_need_all_four_hours():
    hourly = [
        kline(0, D(10), D(12), D(9), D(11)),
        kline(H1, D(11), D(15), D(10), D(14)),
        kline(2 * H1, D(14), D(14), D(8), D(9)),
        kline(3 * H1, D(9), D(13), D(9), D(12)),
        kline(4 * H1, D(12), D(20), D(12), D(19)),
        kline(5 * H1, D(19), D(19), D(5), D(6)),
        kline(6 * H1, D(6), D(9), D(4), D(8)),
        kline(7 * H1, D(8), D(10), D(7), D(9)),
    ]
    first, second = four_hour_bars(hourly)
    assert first == Bar(0, D(15), D(8), D(12))  # max high, min low, last hour's close
    assert second == Bar(4 * H1, D(20), D(4), D(9))
    # Hour 5 gone: its whole bucket goes with it, and the first bucket is untouched.
    assert four_hour_bars(hourly[:5] + hourly[6:]) == [first]


def test_four_hour_buckets_align_to_utc_multiples():
    # Hours 2..9: the first bucket has only hours 2 and 3, so only [4 h, 8 h) is whole.
    hourly = [kline(h * H1, D(10), D(11), D(9), D(10)) for h in range(2, 10)]
    assert [bar.open_ms for bar in four_hour_bars(hourly)] == [4 * H1]
    assert four_hour_bars([]) == []


def test_trend_state_boundaries():
    up = (D(110), D(105), D(100))  # close, sma20, sma50
    down = (D(90), D(95), D(100))
    assert trend_state(*up, D(20), D(30), D(10)) is TrendState.UP  # ADX exactly 20
    assert trend_state(*up, D("19.999"), D(30), D(10)) is TrendState.RANGE
    assert trend_state(*down, D(20), D(10), D(30)) is TrendState.DOWN
    assert trend_state(*down, D("19.999"), D(10), D(30)) is TrendState.RANGE
    # close == sma50 is neither above nor below it.
    assert trend_state(D(100), D(105), D(100), D(25), D(30), D(10)) is TrendState.UNCLEAR
    assert trend_state(D(100), D(95), D(100), D(25), D(10), D(30)) is TrendState.UNCLEAR
    # Every other strict comparison, one at a time.
    assert trend_state(D(110), D(100), D(100), D(25), D(30), D(10)) is TrendState.UNCLEAR
    assert trend_state(D(90), D(100), D(100), D(25), D(10), D(30)) is TrendState.UNCLEAR
    assert trend_state(*up, D(25), D(20), D(20)) is TrendState.UNCLEAR  # +DI == -DI
    assert trend_state(*up, D(25), D(10), D(30)) is TrendState.UNCLEAR  # -DI leads
    assert trend_state(*down, D(25), D(30), D(10)) is TrendState.UNCLEAR  # +DI leads
    assert trend_state(D(90), D(105), D(100), D(25), D(30), D(10)) is TrendState.UNCLEAR


@pytest.mark.parametrize("missing", range(6))
def test_trend_state_unavailable_when_any_input_is_none(missing):
    inputs: list[D | None] = [D(110), D(105), D(100), D(25), D(30), D(10)]
    assert trend_state(*inputs) is TrendState.UP
    inputs[missing] = None
    assert trend_state(*inputs) is TrendState.UNAVAILABLE


def test_trend_state_unavailable_wins_over_range():
    # The spec's example: ADX 15 would be Range, but an SMA50 without its bars gives Unavailable.
    state = trend_state(D(100), D(100), None, D(15), D(10), D(10))
    assert state is TrendState.UNAVAILABLE


def test_bar_visible_only_from_its_close():
    # 1h: at(k h) reads the hour that opened at (k-1) h, until the next hour closes.
    hourly = walk(60, H1, seed=3)
    rsi = wilder_rsi([k.close for k in hourly])
    adx = wilder_adx(bars_of(hourly))[0]
    k = 30
    assert rsi[k - 1] != rsi[k - 2] and adx[k - 1] != adx[k - 2]
    p = Perception(hourly, [])
    now, just_before = p.at(k * H1), p.at(k * H1 - 1)
    assert (now.h1_rsi, now.h1_adx) == (rsi[k - 1], adx[k - 1])
    assert (just_before.h1_rsi, just_before.h1_adx) == (rsi[k - 2], adx[k - 2])
    assert p.at((k + 1) * H1 - 1).h1_rsi == rsi[k - 1]

    # 4h: the last bucket crashes, so its state differs from the bucket before it.
    crash = climb(4, H1, D(-60), start_ms=236 * H1, start=D(336))
    hourly4 = climb(236, H1, D(1)) + crash
    states = states_of(four_hour_bars(hourly4))
    assert len(states) == 60 and states[58] is TrendState.UP and states[59] is TrendState.UNCLEAR
    p4 = Perception(hourly4, [])
    assert p4.at(240 * H1).h4_state is TrendState.UNCLEAR  # the bucket opened at 236 h
    assert p4.at(240 * H1 - 1).h4_state is TrendState.UP  # still the bucket opened at 232 h
    assert p4.at(236 * H1).h4_state is TrendState.UP
    assert p4.at(236 * H1 - 1).h4_state is states[57]

    # 1d: at(k d) reads the day that opened at (k-1) d.
    daily = climb(70, DAY, D(1))
    pd = Perception([], daily)
    now, just_before = pd.at(65 * DAY), pd.at(65 * DAY - 1)
    assert (now.d1_open_ms, now.d1_index, now.d1_close) == (64 * DAY, 64, daily[64].close)
    assert (just_before.d1_open_ms, just_before.d1_index) == (63 * DAY, 63)
    assert just_before.d1_close == daily[63].close
    assert pd.at(65 * DAY + DAY - 1).d1_open_ms == 64 * DAY


def test_masked_last_bar_is_unavailable_and_older_gaps_are_skipped():
    # Hour 762 is masked: the 4h bucket [760 h, 764 h) goes with it. Hours 0..799 exist otherwise.
    masked_hour = 762
    hourly = walk(800, H1, seed=11)
    with_gap = [k for k in hourly if k.open_ms != masked_hour * H1]
    p, full = Perception(with_gap, []), Perception(hourly, [])

    # at(763 h) wants hour 762, which is missing: nothing is read, nothing stale is returned.
    blind = p.at((masked_hour + 1) * H1)
    assert blind.h1_available is False
    assert (blind.h1_rsi, blind.h1_adx, blind.h1_width, blind.h1_width_median) == (None,) * 4
    assert full.at((masked_hour + 1) * H1).h1_available is True

    # at(764 h) wants hour 763: the gap is skipped, as in a fresh run over the bars that exist.
    seen = [k for k in with_gap if k.open_ms <= (masked_hour + 1) * H1]
    closes = [k.close for k in seen]
    widths = bollinger_width(closes)
    ahead = p.at((masked_hour + 2) * H1)
    assert ahead.h1_available is True
    assert ahead.h1_rsi == wilder_rsi(closes)[-1]
    assert ahead.h1_adx == wilder_adx(bars_of(seen))[0][-1]
    assert ahead.h1_width == widths[-1]
    assert ahead.h1_width_median == rolling_median(widths, 720)[-1]
    assert ahead.h1_rsi != full.at((masked_hour + 2) * H1).h1_rsi  # the missing hour mattered

    # The bucket holding the masked hour is absent, so the 4h timeframe is Unavailable at 764 h
    # (and not merely short of history), and the next bucket reads the buckets that exist.
    assert p.at(764 * H1).h4_state is TrendState.UNAVAILABLE
    assert full.at(764 * H1).h4_state is not TrendState.UNAVAILABLE
    later = [k for k in with_gap if k.open_ms < 768 * H1]
    assert p.at(768 * H1).h4_state is states_of(four_hour_bars(later))[-1]
    assert p.at(768 * H1).h4_state is not TrendState.UNAVAILABLE


def test_h1_needs_a_full_width_median():
    # 720 widths exist from the 739th bar (index 738) on.
    hourly = walk(760, H1, seed=9)
    p = Perception(hourly, [])
    short, whole = p.at(738 * H1), p.at(739 * H1)
    assert short.h1_width is not None and short.h1_width_median is None
    assert short.h1_available is False
    assert whole.h1_width_median is not None and whole.h1_available is True


def test_daily_state_needs_fifty_bars_even_when_adx_exists():
    daily = climb(50, DAY, D(1))
    p = Perception([], daily)
    short = p.at(49 * DAY)  # reads the 49th bar: ADX and RSI exist, SMA50 does not
    assert short.d1_state is TrendState.UNAVAILABLE
    assert short.d1_close == daily[48].close and short.d1_rsi is not None
    assert p.at(50 * DAY).d1_state is TrendState.UP


def test_missing_daily_bar_is_unavailable_and_keeps_the_old_open_time():
    daily = [k for k in climb(70, DAY, D(1)) if k.open_ms != 64 * DAY]
    p = Perception([], daily)
    blind = p.at(65 * DAY)  # wants day 64, which is missing
    assert blind.d1_state is TrendState.UNAVAILABLE
    assert (blind.d1_close, blind.d1_rsi, blind.d1_atr) == (None, None, None)
    assert blind.d1_open_ms == 63 * DAY and blind.d1_index == 63
    assert blind.d1_points[blind.d1_index].open_ms == 63 * DAY
    after = p.at(66 * DAY)  # day 65 exists: the gap is skipped
    assert after.d1_state is TrendState.UP and after.d1_open_ms == 65 * DAY
    assert after.d1_points[after.d1_index].open_ms == 65 * DAY


def test_daily_points_read_each_bar_at_its_own_close():
    # Up through day 61, then Unclear: the state changes between the two snapshots below.
    daily = climb(60, DAY, D(1)) + climb(12, DAY, D(-5), start_ms=60 * DAY, start=D(160))
    p = Perception([], daily)
    s = p.at(62 * DAY)  # reads day 61
    assert s.d1_index == 61 and s.d1_open_ms == 61 * DAY and s.d1_state is TrendState.UP
    point = s.d1_points[s.d1_index]
    assert (point.state, point.close, point.atr) == (s.d1_state, s.d1_close, s.d1_atr)
    assert s.d1_rsi is not None

    later = p.at(64 * DAY)  # two days on, reads day 63
    assert later.d1_index == 63 and later.d1_state is TrendState.UNCLEAR
    assert later.d1_points is s.d1_points  # one tuple, shared by every snapshot
    expected = tuple(daily_point_at_own_close(daily, i) for i in range(len(daily)))
    assert later.d1_points == expected  # each bar as it read at its own close
    # The two days the snapshot passed over keep what they read then, not today's state.
    assert later.d1_points[61].state is TrendState.UP
    assert later.d1_points[62].state is TrendState.UNCLEAR
    assert later.d1_points[61] == s.d1_points[s.d1_index]


def test_masked_hour_leaves_the_daily_state_in_use():
    hourly = walk(70 * 24, H1, seed=5)
    daily = walk(70, DAY, seed=6)
    masked_hour = 64 * DAY + 22 * H1  # inside the last completed day, and its last 4h bucket
    with_gap = [k for k in hourly if k.open_ms != masked_hour]
    now = 65 * DAY + H1  # the first hour after midnight
    full, masked = Perception(hourly, daily).at(now), Perception(with_gap, daily).at(now)
    assert masked.d1_state is not TrendState.UNAVAILABLE
    assert (masked.d1_state, masked.d1_close, masked.d1_atr) == (
        full.d1_state,
        full.d1_close,
        full.d1_atr,
    )
    assert masked.d1_close == daily[64].close and masked.d1_open_ms == 64 * DAY
    # The hourly timeframes do feel the mask, so the daily path is the one that ignores it.
    assert full.h4_state is not TrendState.UNAVAILABLE
    assert masked.h4_state is TrendState.UNAVAILABLE


def test_empty_history_is_unavailable_everywhere():
    s = Perception([], []).at(10 * DAY)
    assert s.h1_available is False
    assert (s.h1_rsi, s.h1_adx, s.h1_width, s.h1_width_median) == (None,) * 4
    assert s.h4_state is TrendState.UNAVAILABLE and s.d1_state is TrendState.UNAVAILABLE
    assert (s.d1_rsi, s.d1_close, s.d1_atr, s.d1_open_ms) == (None,) * 4
    assert s.d1_points == () and s.d1_index is None


def test_nothing_is_visible_before_the_first_bar_closes():
    daily = climb(70, DAY, D(1), start_ms=10 * DAY)
    p = Perception(walk(30, H1, seed=2, start_ms=10 * DAY), daily)
    s = p.at(11 * DAY - 1)  # the first day has not closed
    assert s.d1_index is None and s.d1_open_ms is None and s.d1_state is TrendState.UNAVAILABLE
    assert len(s.d1_points) == 70  # the points exist; none has closed yet
    assert p.at(11 * DAY).d1_index == 0


@pytest.mark.parametrize("which", ["hourly", "daily"])
@pytest.mark.parametrize("shape", ["duplicate", "backwards"])
def test_non_increasing_open_times_are_rejected(which, shape):
    step = H1 if which == "hourly" else DAY
    klines = walk(5, step, seed=1)
    klines[3] = klines[2] if shape == "duplicate" else klines[1]
    with pytest.raises(ValueError, match=which):
        if which == "hourly":
            Perception(klines, [])
        else:
            Perception([], klines)


def test_at_is_a_lookup_over_series_computed_once(monkeypatch):
    p = Perception(walk(800, H1, seed=4), climb(70, DAY, D(1)))
    expected = p.at(790 * H1)

    def refuse(*args, **kwargs):
        raise AssertionError("at() must not recompute")

    for name in (
        "sma",
        "wilder_rsi",
        "wilder_atr",
        "wilder_adx",
        "bollinger_width",
        "rolling_median",
        "four_hour_bars",
        "trend_state",
    ):
        monkeypatch.setattr(perception, name, refuse)
    assert p.at(790 * H1) == expected
    assert p.at(65 * DAY).d1_index == 64


def test_snapshot_and_daily_point_are_immutable():
    s = Perception([], climb(70, DAY, D(1))).at(65 * DAY)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.d1_state = TrendState.DOWN  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.d1_points[0].close = D(0)  # type: ignore[misc]
    assert isinstance(s, Snapshot) and isinstance(s.d1_points, tuple)
