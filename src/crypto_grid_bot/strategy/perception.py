"""Three-timeframe perception for spec v2 (§3): what the mode selector may see at a minute.

``Perception`` runs every indicator once over the bars that exist (``indicators`` skips a missing
bar without resetting), and ``Perception.at`` is then a lookup by open time.

Point in time. A bar of length L that opens at ``o`` is visible only from ``o + L``. At time ``t``
the bar that should have closed last opens at ``t // L * L - L``. If that bar is absent, the
timeframe is unavailable at ``t``: its fields are ``None`` and its state ``UNAVAILABLE``, never the
last bar that did exist. A timeframe is also unavailable while an input it needs lacks its minimum
bars, which shows as a ``None`` input.

Timeframes. 1h reads the hourly klines. 4h is built from them, and a masked or missing hour removes
its whole bucket. Daily reads the daily klines alone and is never masked, so a missing hour inside a
day leaves that day's daily values in use (spec v2 §3). ``Bar`` carries no open price, so a 4h bar
keeps its first hour's open time but not its open price; no indicator reads it.

Daily points. ``Snapshot.d1_points`` holds every daily bar as it read at its own close. It is one
tuple shared by every snapshot, and ``d1_index`` marks the latest point closed at the minute, so the
uptrend engine can walk each daily close that a gap made it miss (spec v2 §5). When the daily bar
due is missing, ``d1_state`` is ``UNAVAILABLE`` and the readings are ``None``, but ``d1_open_ms``
and ``d1_index`` still name the latest bar that did close.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

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

_HOUR_MS = 3_600_000
_FOUR_HOUR_MS = 4 * _HOUR_MS
_DAY_MS = 24 * _HOUR_MS
_ADX_TREND = Decimal(20)
_WIDTH_MEDIAN_SIZE = 720  # 30 days of hourly widths


class TrendState(StrEnum):
    UP = "up"
    DOWN = "down"
    RANGE = "range"
    UNCLEAR = "unclear"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DailyPoint:
    """One daily bar as it reads at its own close."""

    open_ms: int
    state: TrendState
    close: Decimal
    atr: Decimal | None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything the mode selector and the uptrend engine read at one minute."""

    h1_available: bool
    h1_rsi: Decimal | None
    h1_adx: Decimal | None
    h1_width: Decimal | None
    h1_width_median: Decimal | None
    h4_state: TrendState
    d1_state: TrendState
    d1_rsi: Decimal | None
    d1_close: Decimal | None
    d1_atr: Decimal | None
    d1_open_ms: int | None
    d1_points: tuple[DailyPoint, ...]
    d1_index: int | None


def four_hour_bars(hourly: Sequence[Kline]) -> list[Bar]:
    """4h bars from hourly klines in time order, at multiples of 4 h UTC.

    A bucket is kept only when all four of its hours exist. Its high is the highest high, its low
    the lowest low and its close the last hour's close; a bucket with a missing hour is dropped.
    """
    buckets: dict[int, list[Kline]] = {}
    for kline in hourly:
        buckets.setdefault(kline.open_ms // _FOUR_HOUR_MS * _FOUR_HOUR_MS, []).append(kline)
    bars: list[Bar] = []
    for start in sorted(buckets):
        hours = buckets[start]
        if [k.open_ms for k in hours] != [start + i * _HOUR_MS for i in range(4)]:
            continue
        bars.append(
            Bar(start, max(k.high for k in hours), min(k.low for k in hours), hours[-1].close)
        )
    return bars


def trend_state(
    close: Decimal | None,
    sma20: Decimal | None,
    sma50: Decimal | None,
    adx: Decimal | None,
    plus_di: Decimal | None,
    minus_di: Decimal | None,
) -> TrendState:
    """The 4h or daily trend state (spec v2 §3). Any missing input is ``UNAVAILABLE``."""
    if (
        close is None
        or sma20 is None
        or sma50 is None
        or adx is None
        or plus_di is None
        or minus_di is None
    ):
        return TrendState.UNAVAILABLE
    if adx < _ADX_TREND:
        return TrendState.RANGE
    if close > sma50 and sma20 > sma50 and plus_di > minus_di:
        return TrendState.UP
    if close < sma50 and sma20 < sma50 and minus_di > plus_di:
        return TrendState.DOWN
    return TrendState.UNCLEAR


def _trend_states(bars: Sequence[Bar]) -> list[TrendState]:
    """A trend state for each bar, from the indicators run over ``bars`` as they exist."""
    closes = [bar.close for bar in bars]
    sma20, sma50 = sma(closes, 20), sma(closes, 50)
    adx, plus_di, minus_di = wilder_adx(bars)
    return [
        trend_state(closes[i], sma20[i], sma50[i], adx[i], plus_di[i], minus_di[i])
        for i in range(len(bars))
    ]


def _bar(kline: Kline) -> Bar:
    return Bar(kline.open_ms, kline.high, kline.low, kline.close)


def _require_increasing(name: str, klines: Sequence[Kline]) -> None:
    for i in range(1, len(klines)):
        if klines[i].open_ms <= klines[i - 1].open_ms:
            raise ValueError(f"{name} open times must be strictly increasing (index {i})")


def _index_of(open_times: Sequence[int], open_ms: int) -> int | None:
    i = bisect_left(open_times, open_ms)
    return i if i < len(open_times) and open_times[i] == open_ms else None


class Perception:
    """Precomputed three-timeframe series, read at any minute with ``at``."""

    def __init__(self, hourly: Sequence[Kline], daily: Sequence[Kline]) -> None:
        """``hourly`` and ``daily`` are the klines that exist, in strictly increasing open time."""
        _require_increasing("hourly", hourly)
        _require_increasing("daily", daily)

        hourly_bars = [_bar(k) for k in hourly]
        hourly_closes = [bar.close for bar in hourly_bars]
        widths = bollinger_width(hourly_closes)
        self._h1_open = [bar.open_ms for bar in hourly_bars]
        self._h1_rsi = wilder_rsi(hourly_closes)
        self._h1_adx = wilder_adx(hourly_bars)[0]
        self._h1_width = widths
        self._h1_width_median = rolling_median(widths, _WIDTH_MEDIAN_SIZE)

        four_hour = four_hour_bars(hourly)
        self._h4_open = [bar.open_ms for bar in four_hour]
        self._h4_state = _trend_states(four_hour)

        daily_bars = [_bar(k) for k in daily]
        atr = wilder_atr(daily_bars)
        states = _trend_states(daily_bars)
        self._d1_open = [bar.open_ms for bar in daily_bars]
        self._d1_rsi = wilder_rsi([bar.close for bar in daily_bars])
        self._d1_points = tuple(
            DailyPoint(bar.open_ms, states[i], bar.close, atr[i])
            for i, bar in enumerate(daily_bars)
        )

    def at(self, minute_ms: int) -> Snapshot:
        """What is visible at ``minute_ms``: only bars that closed at or before it."""
        h1 = _index_of(self._h1_open, minute_ms // _HOUR_MS * _HOUR_MS - _HOUR_MS)
        h1_values: tuple[Decimal | None, ...] = (None,) * 4
        if h1 is not None:
            h1_values = (
                self._h1_rsi[h1],
                self._h1_adx[h1],
                self._h1_width[h1],
                self._h1_width_median[h1],
            )
        h1_rsi, h1_adx, h1_width, h1_width_median = h1_values

        h4 = _index_of(self._h4_open, minute_ms // _FOUR_HOUR_MS * _FOUR_HOUR_MS - _FOUR_HOUR_MS)
        h4_state = TrendState.UNAVAILABLE if h4 is None else self._h4_state[h4]

        d1 = _index_of(self._d1_open, minute_ms // _DAY_MS * _DAY_MS - _DAY_MS)
        # The latest daily bar closed at the minute, whether or not it is the bar that was due.
        latest = bisect_right(self._d1_open, minute_ms - _DAY_MS) - 1
        d1_index = latest if latest >= 0 else None
        d1_point = None if d1 is None else self._d1_points[d1]
        return Snapshot(
            h1_available=None not in h1_values,
            h1_rsi=h1_rsi,
            h1_adx=h1_adx,
            h1_width=h1_width,
            h1_width_median=h1_width_median,
            h4_state=h4_state,
            d1_state=TrendState.UNAVAILABLE if d1_point is None else d1_point.state,
            d1_rsi=None if d1 is None else self._d1_rsi[d1],
            d1_close=None if d1_point is None else d1_point.close,
            d1_atr=None if d1_point is None else d1_point.atr,
            d1_open_ms=None if d1_index is None else self._d1_open[d1_index],
            d1_points=self._d1_points,
            d1_index=d1_index,
        )
