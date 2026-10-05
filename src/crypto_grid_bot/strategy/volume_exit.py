"""Variant E of experiment spec v1 (§3 E): the volume check of a volume-confirmed exit.

At the first valid observation at or after ``t0 + 6 h``, where ``t0`` is the episode's
first outside observation, E compares the base volume of the 1m bars that opened in
``[floor_minute(t0), floor_minute(t0 + 6 h))`` with 2 × the median base volume of the 720
hourly bars before ``t0``'s hour × 6. Below it, the exit waits until the first valid
observation at or after ``t0 + 12 h``; at or above it, V0's own range exit applies. A
missing reference hour or measured minute, or a zero median, makes the comparison
unavailable, and V0's exit applies then too. Both milestones are on the clock from the
original ``t0``: a later decision still measures the same span, and the deadline never
moves. The engine (``runner.py``) asks once per episode.

Pure and Decimal; nothing reads files or the clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

HOUR_MS = 3_600_000
MINUTE_MS = 60_000
REFERENCE_HOURS = 720
# E decides at t0 + 6 h, over the 6 hours of 1m bars from t0's minute, and an extended
# episode exits at t0 + 12 h.
DECISION = timedelta(hours=6)
DEADLINE = timedelta(hours=12)
MEASURED_MS = DECISION // timedelta(milliseconds=1)
ZERO = Decimal(0)
# Exact: sums of bar volumes need far fewer digits than this.
_PRECISION = 60
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _ms(when: datetime) -> int:
    return (when - _EPOCH) // timedelta(milliseconds=1)


def _span(volumes: dict[int, Decimal], opens: range) -> list[Decimal] | None:
    """The volume of the bar at every open time in ``opens``; None if any is missing."""
    found = [volumes[open_ms] for open_ms in opens if open_ms in volumes]
    return found if len(found) == len(opens) else None


class VolumeHistory:
    """One pair's base volumes: its hourly bars, all given at the start, and the 1m bars
    a replay has finished stepping through, recorded as it goes."""

    def __init__(self, hourly: Iterable[tuple[int, Decimal]]) -> None:
        self._hours = dict(hourly)
        self._minutes: dict[int, Decimal] = {}

    def record(self, open_ms: int, volume: Decimal) -> None:
        """Add the 1m bar that opened at ``open_ms``, once it has closed."""
        self._minutes[open_ms] = volume

    def extends(self, t0: datetime, observed: datetime) -> bool | None:
        """Whether E extends the episode that left the range at ``t0``, decided at
        ``observed``: True when the measured volume is below the threshold, False at or
        above it (equality exits), None when the comparison is unavailable.

        Only bars closed by both instants are read: the reference hours closed by ``t0``,
        and the measured minutes by ``observed``; a span not yet closed is unavailable.
        """
        t0_ms = _ms(t0)
        start, hour = t0_ms - t0_ms % MINUTE_MS, t0_ms - t0_ms % HOUR_MS
        if start + MEASURED_MS > _ms(observed):
            return None
        reference = _span(self._hours, range(hour - REFERENCE_HOURS * HOUR_MS, hour, HOUR_MS))
        measured = _span(self._minutes, range(start, start + MEASURED_MS, MINUTE_MS))
        if reference is None or measured is None:
            return None
        with localcontext() as context:
            context.prec = _PRECISION
            ordered = sorted(reference)
            half = REFERENCE_HOURS // 2  # an even count: the mean of the two middle values
            median = (ordered[half - 1] + ordered[half]) / 2
            if median <= ZERO:
                return None
            return sum(measured, ZERO) < 2 * median * 6
