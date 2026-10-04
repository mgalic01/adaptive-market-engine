"""Completed daily bars and their simple moving averages (experiment spec v1, §3).

Pure functions, exact ``Decimal`` arithmetic, no I/O. Variant D uses them for its
SMA50 signal; variant A (``simulation.trend_switch``) uses the same closes and averages
for its SMA50 and SMA200.

Timing (spec v1 §3, "Timing rules common to all"): the daily bar that opens at UTC
midnight of day ``d`` closes at midnight of ``d + 1``. Its close is used from the
first observation at or after that instant, never inside the bar that produced it.
So an observation at time ``t`` may use the bar that opened on the previous UTC day
(:func:`signal_day`), and nothing newer.

A value is **undefined** (``None``) when the bar for that day is missing, when fewer
than ``length`` consecutive days end at it, or when any close in the window is zero
or negative. A missing day is never filled and never skipped over: an older bar is
not substituted for it.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal, localcontext

DAY_MS = 86_400_000
ZERO = Decimal(0)
# Exact: a sum of daily closes needs far fewer digits than this.
_PRECISION = 60


def signal_day(observed_ms: int) -> int:
    """Open time (UTC ms) of the latest daily bar completed at ``observed_ms``.

    That is the previous UTC day: at 00:00:00.000 of day ``d + 1`` the bar of day ``d``
    has just closed, and one millisecond earlier only the bar of ``d - 1`` had.
    """
    return observed_ms // DAY_MS * DAY_MS - DAY_MS


class DailyCloses:
    """One symbol's completed daily closes, keyed by the bar's UTC-midnight open time."""

    def __init__(self, bars: Iterable[tuple[int, Decimal]]) -> None:
        closes: dict[int, Decimal] = {}
        for open_ms, close in bars:
            if open_ms % DAY_MS:
                raise ValueError(f"daily bar at {open_ms} does not open at UTC midnight")
            if open_ms in closes:
                raise ValueError(f"duplicate daily bar at {open_ms}")
            if not isinstance(close, Decimal) or not close.is_finite():
                raise ValueError(f"daily close at {open_ms} must be a finite Decimal")
            closes[open_ms] = close
        self._closes = closes

    def close(self, day_ms: int) -> Decimal | None:
        """The close of the bar that opened at ``day_ms``; None if missing or not positive."""
        value = self._closes.get(day_ms)
        return value if value is not None and value > ZERO else None

    def window(self, day_ms: int, length: int) -> list[Decimal] | None:
        """The ``length`` closes of consecutive days ending at ``day_ms``, oldest first.

        None if any of those days is missing or has a zero or negative close.
        """
        if length < 1:
            raise ValueError("an SMA length must be at least 1")
        values = []
        for offset in range(length - 1, -1, -1):
            value = self.close(day_ms - offset * DAY_MS)
            if value is None:
                return None
            values.append(value)
        return values

    def sma(self, day_ms: int, length: int) -> Decimal | None:
        """Simple moving average of the ``length`` closes ending at ``day_ms``, or None."""
        values = self.window(day_ms, length)
        if values is None:
            return None
        with localcontext() as context:
            context.prec = _PRECISION
            return sum(values, ZERO) / length


def close_above_sma(closes: DailyCloses, day_ms: int, length: int) -> bool | None:
    """Whether the close of ``day_ms`` is strictly above its SMA of ``length`` days.

    True: above. False: at or below. None: undefined (see the module docstring). The
    comparison is exact: ``close * length > sum(window)``, with no division.
    """
    values = closes.window(day_ms, length)
    if values is None:
        return None
    with localcontext() as context:
        context.prec = _PRECISION
        return values[-1] * length > sum(values, ZERO)
