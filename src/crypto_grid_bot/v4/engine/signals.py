"""The per-coin daily signal state of V4: three speeds, the confirmed downtrend, and the long
fraction L, the short fraction S and the net signal s.

Implements the spec's "Signals: three speeds from daily closes". The input is one ``Kline`` per
completed UTC day of a coin; a day with no bar is simply not passed, adds no observation and
resets nothing. Every lookback counts available bars (V3 section 4).

The math is V3's, copied, not called: ``trend.signals`` refuses every month after 2024-12. The
differential test against V3 on pre-2025 bars is the check that the copy agrees.

* **SMA** over the last n closes, including the current bar. Running sums are exact: the
  inputs are bounded (at most 1e18, at most 18 decimals) and a sum of a few hundred of them
  needs well under ``CONTEXT.prec`` digits.
* **EMA(n)** starts at bar n as the simple mean of the first n closes, then follows
  ``a x close + (1 - a) x previous`` with ``a = 2 / (n + 1)`` (V3 ``SignalState.update``).
* **Donchian** is V3's rule R3: "prior n" is the n bars ending the bar before the current one
  (V3 slices ``self._bars[-n:]`` before appending the new bar). In order: a close above the
  prior ``entry`` highs is +1; else below the prior ``entry`` lows is -1; else a long whose
  close is below the prior ``exit`` lows is 0; else a short whose close is above the prior
  ``exit`` highs is 0; else unchanged. It starts flat and is warm from bar ``entry + 1``.
* **Downtrend** windows include the current bar. "The last ``trend_window`` bars" are the
  current bar and the ones before it; "the ``trend_window`` bars before them" are the next
  ``trend_window`` back. ``SMA(trend_sma)`` is compared with its own value ``trend_slope`` bars
  earlier, so it needs ``trend_sma + trend_slope`` bars.

A speed that is warming up, or whose comparison is exactly equal, is ``None``: neither up nor
down. The downtrend is ``None`` while any of its parts is warming; ``None`` and ``False`` both
mean "not confirmed" for S.

``update`` is O(window) per bar: bounded deques and running sums, never the whole history.

``DailyFeed`` is the engine's one way of feeding a coin's daily bars to its state: in order, each
bar once, up to a decision's day and never past it. Each V4 coin's trading state, the BTC state
of ``short_filter`` and hold_btc_trend's vote are all fed by one.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, fields
from decimal import Decimal, localcontext
from itertools import islice
from typing import Literal

from crypto_grid_bot.backtest.klines import INTERVAL_MS, Kline
from crypto_grid_bot.v4.engine.arms import Lookbacks
from crypto_grid_bot.v4.engine.numbers import CONTEXT

DAY_MS = INTERVAL_MS["1d"]
Vote = Literal[1, -1]

_ZERO = Decimal(0)
_ONE = Decimal(1)
# The bounds of the data layer's price reader. Inside them every sum below is exact.
_MAX_PRICE = Decimal("1e18")
_MAX_EXPONENT = 18

with localcontext(CONTEXT):
    # L = (number of speeds up) / 3, as Decimals under the one engine context.
    _LONG_FRACTIONS = tuple(Decimal(up) / Decimal(3) for up in range(4))
    # S = (0.5 if fast is down else 0.25) x (2 if slow is down else 1), keyed (fast down,
    # slow down).
    _SHORT_FRACTIONS = {
        (fast_down, slow_down): (Decimal("0.5") if fast_down else Decimal("0.25"))
        * (Decimal(2) if slow_down else Decimal(1))
        for fast_down in (False, True)
        for slow_down in (False, True)
    }


@dataclass(frozen=True, slots=True)
class SignalReading:
    """One coin's signal state after one daily close.

    The indicator values are ``None`` while their window is warming up. ``fast``, ``medium``
    and ``slow`` are +1 (up), -1 (down) or ``None`` (warming up, or an exact tie). ``L``, ``S``,
    ``s`` and ``s_long_only`` are always numbers: a speed that is not up or down adds nothing,
    so a coin with nothing to say has L = S = s = 0.
    """

    day_ms: int
    close: Decimal
    sma_fast: Decimal | None
    sma_slow: Decimal | None
    ema_fast: Decimal | None
    ema_slow: Decimal | None
    donchian: int | None
    sma_trend: Decimal | None
    sma_trend_lagged: Decimal | None
    high_recent: Decimal | None
    high_prior: Decimal | None
    low_recent: Decimal | None
    low_prior: Decimal | None
    fast: Vote | None
    medium: Vote | None
    slow: Vote | None
    downtrend: bool | None
    L: Decimal
    S: Decimal
    s: Decimal
    s_long_only: Decimal


def medium_vote(ema: int | None, donchian: int | None) -> Vote | None:
    """The medium speed: the mean of the EMA vote and the Donchian state, up if above zero.

    Both are -1, 0 or +1. The medium is warm only when both votes are; a mean of exactly zero
    is a tie.
    """
    if ema is None or donchian is None:
        return None
    total = ema + donchian
    if total > 0:
        return 1
    if total < 0:
        return -1
    return None


def short_fraction(
    fast: Vote | None, medium: Vote | None, slow: Vote | None, downtrend: bool | None
) -> Decimal:
    """S: 0 unless the medium is down and the downtrend is confirmed (``None`` is unconfirmed).

    Otherwise (0.5 if fast is down, else 0.25) x (2 if slow is down, else 1), so 0.25, 0.5 or 1.
    """
    if medium != -1 or downtrend is not True:
        return _ZERO
    return _SHORT_FRACTIONS[(fast == -1, slow == -1)]


def long_fraction(fast: Vote | None, medium: Vote | None, slow: Vote | None) -> Decimal:
    """L: the number of speeds that are up, divided by 3."""
    return _LONG_FRACTIONS[sum(vote == 1 for vote in (fast, medium, slow))]


def _side(value: Decimal, line: Decimal | None) -> Vote | None:
    """+1 above the line, -1 below it, ``None`` on a tie or while the line is warming up."""
    if line is None or value == line:
        return None
    return 1 if value > line else -1


class _Sma:
    """A simple moving average over the last n values, by a running sum."""

    __slots__ = ("_length", "_total", "_window")

    def __init__(self, length: int) -> None:
        self._length = length
        self._window: deque[Decimal] = deque(maxlen=length)
        self._total = _ZERO

    def push(self, value: Decimal) -> Decimal | None:
        if len(self._window) == self._length:
            self._total -= self._window[0]
        self._window.append(value)
        self._total += value
        if len(self._window) < self._length:
            return None
        return self._total / Decimal(self._length)

    def __len__(self) -> int:
        return len(self._window)


class _Ema:
    """An EMA seeded with the simple mean of the first n values (V3's seeding)."""

    __slots__ = ("_alpha", "_length", "_seen", "_total", "_value")

    def __init__(self, length: int) -> None:
        self._length = length
        self._alpha = Decimal(2) / Decimal(length + 1)
        self._seen = 0
        self._total = _ZERO
        self._value: Decimal | None = None

    def push(self, value: Decimal) -> Decimal | None:
        self._seen += 1
        if self._seen <= self._length:
            self._total += value
            if self._seen == self._length:
                self._value = self._total / Decimal(self._length)
        elif self._value is not None:
            self._value = self._alpha * value + (_ONE - self._alpha) * self._value
        return self._value


class _Tail:
    """The last ``size`` values of a series, newest last, with window extremes."""

    __slots__ = ("_values",)

    def __init__(self, size: int) -> None:
        self._values: deque[Decimal] = deque(maxlen=size)

    def push(self, value: Decimal) -> None:
        self._values.append(value)

    def holds(self, count: int, skip: int = 0) -> bool:
        return len(self._values) >= count + skip

    def _window(self, count: int, skip: int) -> islice[Decimal]:
        if not self.holds(count, skip):
            raise ValueError(f"window of {count} after skipping {skip} is not yet available")
        return islice(reversed(self._values), skip, skip + count)

    def maximum(self, count: int, skip: int = 0) -> Decimal:
        """The largest of ``count`` values, the newest ``skip`` values left out."""
        return max(self._window(count, skip))

    def minimum(self, count: int, skip: int = 0) -> Decimal:
        """The smallest of ``count`` values, the newest ``skip`` values left out."""
        return min(self._window(count, skip))

    def __len__(self) -> int:
        return len(self._values)


def _check_lookbacks(lookbacks: Lookbacks) -> None:
    for field in fields(lookbacks):
        value = getattr(lookbacks, field.name)
        if type(value) is not int or value < 1:
            raise ValueError(f"lookback {field.name} must be a positive int, got {value!r}")
    if lookbacks.donchian_exit > lookbacks.donchian_entry:
        raise ValueError("donchian_exit must not exceed donchian_entry")


def _check_price(name: str, value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"daily bar {name} must be a finite Decimal, got {value!r}")
    exponent = value.as_tuple().exponent
    if (
        not isinstance(exponent, int)
        or not -_MAX_EXPONENT <= exponent <= _MAX_EXPONENT
        or not _ZERO < value <= _MAX_PRICE
    ):
        raise ValueError(f"daily bar {name} is outside the data layer's numeric bounds: {value}")
    return value


class CoinSignals:
    """One coin's continuous signal series. Feed it each completed UTC day, oldest first."""

    def __init__(self, lookbacks: Lookbacks) -> None:
        _check_lookbacks(lookbacks)
        self._lookbacks = lookbacks
        self._last_ms: int | None = None
        self._sma_fast = _Sma(lookbacks.fast)
        self._sma_slow = _Sma(lookbacks.slow)
        self._sma_trend = _Sma(lookbacks.trend_sma)
        with localcontext(CONTEXT):
            self._ema_fast = _Ema(lookbacks.ema_fast)
            self._ema_slow = _Ema(lookbacks.ema_slow)
        # The trend SMA now and trend_slope bars ago: the oldest of slope + 1 values.
        self._trend_history: deque[Decimal] = deque(maxlen=lookbacks.trend_slope + 1)
        # Donchian reads the prior entry bars, the downtrend the last two trend windows.
        size = max(lookbacks.donchian_entry, 2 * lookbacks.trend_window)
        self._highs = _Tail(size)
        self._lows = _Tail(size)
        self._donchian = 0

    @property
    def lookbacks(self) -> Lookbacks:
        return self._lookbacks

    @property
    def history_size(self) -> int:
        """How many values the state keeps: bounded by the windows, whatever the run length."""
        return (
            len(self._sma_fast)
            + len(self._sma_slow)
            + len(self._sma_trend)
            + len(self._trend_history)
            + len(self._highs)
            + len(self._lows)
        )

    def _check_bar(self, bar: Kline) -> None:
        if type(bar.open_ms) is not int or bar.open_ms < 0 or bar.open_ms % DAY_MS:
            raise ValueError("a daily bar must open at UTC midnight")
        if self._last_ms is not None and bar.open_ms <= self._last_ms:
            raise ValueError("daily bars must be strictly increasing in time")
        prices = {
            name: _check_price(name, getattr(bar, name))
            for name in ("open", "high", "low", "close")
        }
        if not (
            prices["low"]
            <= min(prices["open"], prices["close"])
            <= max(prices["open"], prices["close"])
            <= prices["high"]
        ):
            raise ValueError("daily bar prices must satisfy low <= open, close <= high")

    def _step_donchian(self, close: Decimal) -> int | None:
        """V3's R3 against the prior bars; the current bar is not in the windows yet."""
        entry, leave = self._lookbacks.donchian_entry, self._lookbacks.donchian_exit
        if not self._highs.holds(entry):
            return None
        if close > self._highs.maximum(entry):
            self._donchian = 1
        elif close < self._lows.minimum(entry):
            self._donchian = -1
        elif (
            self._donchian > 0
            and close < self._lows.minimum(leave)
            or self._donchian < 0
            and close > self._highs.maximum(leave)
        ):
            self._donchian = 0
        return self._donchian

    def update(self, bar: Kline) -> SignalReading:
        """Take the next completed UTC day and return the signal state after its close."""
        self._check_bar(bar)
        lb = self._lookbacks
        close = bar.close
        with localcontext(CONTEXT):
            donchian = self._step_donchian(close)
            self._highs.push(bar.high)
            self._lows.push(bar.low)
            self._last_ms = bar.open_ms

            sma_fast = self._sma_fast.push(close)
            sma_slow = self._sma_slow.push(close)
            sma_trend = self._sma_trend.push(close)
            ema_fast = self._ema_fast.push(close)
            ema_slow = self._ema_slow.push(close)
            sma_trend_lagged: Decimal | None = None
            if sma_trend is not None:
                self._trend_history.append(sma_trend)
                if len(self._trend_history) == self._trend_history.maxlen:
                    sma_trend_lagged = self._trend_history[0]

            window = lb.trend_window
            high_recent = self._highs.maximum(window) if self._highs.holds(window) else None
            low_recent = self._lows.minimum(window) if self._lows.holds(window) else None
            high_prior = (
                self._highs.maximum(window, window) if self._highs.holds(window, window) else None
            )
            low_prior = (
                self._lows.minimum(window, window) if self._lows.holds(window, window) else None
            )
            downtrend: bool | None = None
            if (
                sma_trend is not None
                and sma_trend_lagged is not None
                and high_recent is not None
                and high_prior is not None
                and low_recent is not None
                and low_prior is not None
            ):
                downtrend = (
                    close < sma_trend
                    and sma_trend < sma_trend_lagged
                    and high_recent < high_prior
                    and low_recent < low_prior
                )

            fast = _side(close, sma_fast)
            slow = _side(close, sma_slow)
            ema_vote = None
            if ema_fast is not None and ema_slow is not None:
                ema_vote = 0 if ema_fast == ema_slow else (1 if ema_fast > ema_slow else -1)
            medium = medium_vote(ema_vote, donchian)

            long = long_fraction(fast, medium, slow)
            short = short_fraction(fast, medium, slow, downtrend)
            return SignalReading(
                day_ms=bar.open_ms,
                close=close,
                sma_fast=sma_fast,
                sma_slow=sma_slow,
                ema_fast=ema_fast,
                ema_slow=ema_slow,
                donchian=donchian,
                sma_trend=sma_trend,
                sma_trend_lagged=sma_trend_lagged,
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


class DailyFeed:
    """One coin's daily bars, fed to its signal state in order, each bar once, up to a
    decision's day and never past it. ``bars`` are the coin's daily bars, oldest first
    (``Market.daily``), and ``signals`` its ``CoinSignals``, made by the caller. A day without a
    bar adds no reading, so ``reading`` stays the one before it."""

    __slots__ = ("_bars", "_fed", "_reading", "_signals")

    def __init__(self, bars: Sequence[Kline], signals: CoinSignals) -> None:
        self._bars = bars
        self._signals = signals
        self._fed = 0  # how many of the bars the state has seen
        self._reading: SignalReading | None = None

    @property
    def reading(self) -> SignalReading | None:
        """The latest reading, None before the first bar is fed."""
        return self._reading

    def feed_through(self, day_ms: int) -> tuple[SignalReading, ...]:
        """Feed every bar not fed yet that opens at or before ``day_ms``, oldest first, and
        return their readings in that order: none for a day without a new bar, every one of a
        catch-up's. ``reading`` is then the last of them."""
        bars, index = self._bars, self._fed
        readings: list[SignalReading] = []
        while index < len(bars) and bars[index].open_ms <= day_ms:
            readings.append(self._signals.update(bars[index]))
            index += 1
        self._fed = index
        if readings:
            self._reading = readings[-1]
        return tuple(readings)
