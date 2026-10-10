"""Gap-aware indicators for spec v2's perception (spec v2 §3): pure functions, exact ``Decimal``.

Contract: the caller passes only the bars that exist, in time order, so a missing or
masked bar is skipped by construction and every recursion continues with the next bar
that exists. ``Bar.open_ms`` is never read here. A true range uses the previous
element's close, whatever time that bar opened at.

Each function returns a list aligned with its input, one element per input element,
``None`` before the first defined value. All arithmetic runs at precision 50 and leaves
the caller's decimal context alone. Nothing here is a float.

The ADX and DI seeding and recursion are those of ``SeriesFeatures._wilder_adx``
(``backtest/features.py``), in ``Decimal``. That function computes nothing for a series
of ``2 × period`` bars or fewer; this one gives ADX from the ``2 × period``-th bar, the
28th at the default period, as spec v2 §3's minimum-bars table says. On longer series the
values agree.
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

_PRECISION = 50
_ZERO = Decimal(0)
_HUNDRED = Decimal(100)
_NEUTRAL_RSI = Decimal(50)


@dataclass(frozen=True, slots=True)
class Bar:
    """One completed bar. ``open_ms`` identifies it; the indicators read only prices."""

    open_ms: int
    high: Decimal
    low: Decimal
    close: Decimal


def _positive(name: str, value: int) -> None:
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got {value}")


def _true_range(bar: Bar, previous_close: Decimal) -> Decimal:
    return max(bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close))


def sma(closes: Sequence[Decimal], length: int) -> list[Decimal | None]:
    """Simple average of the last ``length`` closes; first defined at index ``length - 1``."""
    _positive("length", length)
    values: list[Decimal | None] = [None] * len(closes)
    with localcontext() as context:
        context.prec = _PRECISION
        for i in range(length - 1, len(closes)):
            values[i] = sum(closes[i - length + 1 : i + 1], _ZERO) / length
    return values


def wilder_rsi(closes: Sequence[Decimal], period: int = 14) -> list[Decimal | None]:
    """Wilder's RSI; first defined at index ``period``.

    The average gain and loss are seeded with the mean of the first ``period`` changes,
    then ``average = (average × (period − 1) + latest) ÷ period``. It is 50 when both
    averages are 0, and 100 when only the average loss is 0.
    """
    _positive("period", period)
    values: list[Decimal | None] = [None] * len(closes)
    if len(closes) <= period:
        return values
    with localcontext() as context:
        context.prec = _PRECISION
        gains = [max(closes[i] - closes[i - 1], _ZERO) for i in range(1, len(closes))]
        losses = [max(closes[i - 1] - closes[i], _ZERO) for i in range(1, len(closes))]
        gain = sum(gains[:period], _ZERO) / period
        loss = sum(losses[:period], _ZERO) / period
        for i in range(period, len(closes)):
            if i > period:
                gain = (gain * (period - 1) + gains[i - 1]) / period
                loss = (loss * (period - 1) + losses[i - 1]) / period
            total = gain + loss
            values[i] = _HUNDRED * gain / total if total else _NEUTRAL_RSI
    return values


def wilder_atr(bars: Sequence[Bar], period: int = 14) -> list[Decimal | None]:
    """Wilder's ATR; first defined at index ``period``, seeded with the mean of TR[1..period].

    Then ``ATR = (ATR × (period − 1) + TR) ÷ period``. The first bar has no previous
    close, so it has no true range.
    """
    _positive("period", period)
    values: list[Decimal | None] = [None] * len(bars)
    if len(bars) <= period:
        return values
    with localcontext() as context:
        context.prec = _PRECISION
        ranges = [_true_range(bars[i], bars[i - 1].close) for i in range(1, len(bars))]
        atr = sum(ranges[:period], _ZERO) / period
        values[period] = atr
        for i in range(period + 1, len(bars)):
            atr = (atr * (period - 1) + ranges[i - 1]) / period
            values[i] = atr
    return values


def wilder_adx(
    bars: Sequence[Bar], period: int = 14
) -> tuple[list[Decimal | None], list[Decimal | None], list[Decimal | None]]:
    """Wilder's ``(adx, plus_di, minus_di)``.

    DI is first defined at index ``period``, ADX at ``2 × period − 1``.

    The smoothed true range and directional movements are seeded with the sums over
    indices 1..period, then ``s = s + latest − s ÷ period``. ±DI is 0 when the smoothed
    true range is 0, and DX is 0 when +DI + −DI is 0. ADX is the mean of the first
    ``period`` DX values, then ``ADX = (ADX × (period − 1) + DX) ÷ period``. DX never
    exceeds 100, so neither does ADX.
    """
    _positive("period", period)
    n = len(bars)
    adx_values: list[Decimal | None] = [None] * n
    plus_values: list[Decimal | None] = [None] * n
    minus_values: list[Decimal | None] = [None] * n
    if n <= period:
        return adx_values, plus_values, minus_values
    with localcontext() as context:
        context.prec = _PRECISION
        tr, plus, minus = [_ZERO] * n, [_ZERO] * n, [_ZERO] * n
        for i in range(1, n):
            up = bars[i].high - bars[i - 1].high
            down = bars[i - 1].low - bars[i].low
            plus[i] = up if up > down and up > 0 else _ZERO
            minus[i] = down if down > up and down > 0 else _ZERO
            tr[i] = _true_range(bars[i], bars[i - 1].close)
        s_tr = sum(tr[1 : period + 1], _ZERO)
        s_plus = sum(plus[1 : period + 1], _ZERO)
        s_minus = sum(minus[1 : period + 1], _ZERO)
        dx: list[Decimal] = []
        adx: Decimal | None = None
        for i in range(period, n):
            if i > period:
                s_tr += tr[i] - s_tr / period
                s_plus += plus[i] - s_plus / period
                s_minus += minus[i] - s_minus / period
            plus_di = _HUNDRED * s_plus / s_tr if s_tr else _ZERO
            minus_di = _HUNDRED * s_minus / s_tr if s_tr else _ZERO
            total = plus_di + minus_di
            dx.append(_HUNDRED * abs(plus_di - minus_di) / total if total else _ZERO)
            if len(dx) == period:
                adx = sum(dx, _ZERO) / period
            elif adx is not None:
                adx = (adx * (period - 1) + dx[-1]) / period
            plus_values[i], minus_values[i] = plus_di, minus_di
            adx_values[i] = adx
    return adx_values, plus_values, minus_values


def bollinger_width(
    closes: Sequence[Decimal], length: int = 20, deviations: int = 2
) -> list[Decimal | None]:
    """Band width ``(upper − lower) ÷ middle``; first defined at index ``length - 1``.

    The middle is the SMA of ``length`` closes and the band sits ``deviations`` population
    standard deviations either side, so the width is ``2 × deviations × σ ÷ SMA``.
    ``None`` where the middle is 0.
    """
    _positive("length", length)
    _positive("deviations", deviations)
    values: list[Decimal | None] = [None] * len(closes)
    with localcontext() as context:
        context.prec = _PRECISION
        for i in range(length - 1, len(closes)):
            window = closes[i - length + 1 : i + 1]
            middle = sum(window, _ZERO) / length
            if not middle:
                continue
            variance = sum(((close - middle) ** 2 for close in window), _ZERO) / length
            values[i] = 2 * deviations * variance.sqrt() / middle
    return values


def rolling_median(values: Sequence[Decimal | None], size: int) -> list[Decimal | None]:
    """Median of the last ``size`` non-``None`` values up to each index.

    Looks back past ``None`` entries as far as needed, and keeps the previous median
    across one. ``None`` until ``size`` non-``None`` values exist, so first defined at
    index ``size - 1`` or later. An even count gives the mean of the two middle values.
    """
    _positive("size", size)
    medians: list[Decimal | None] = [None] * len(values)
    recent: deque[Decimal] = deque()  # the window, in arrival order
    ordered: list[Decimal] = []  # the same window, sorted
    half = size // 2
    with localcontext() as context:
        context.prec = _PRECISION
        for i, value in enumerate(values):
            if value is not None:
                recent.append(value)
                insort(ordered, value)
                if len(recent) > size:
                    del ordered[bisect_left(ordered, recent.popleft())]
            if len(recent) == size:
                medians[i] = ordered[half] if size % 2 else (ordered[half - 1] + ordered[half]) / 2
    return medians
