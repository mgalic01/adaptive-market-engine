"""Variant H of experiment spec v1 (§3 H): Bitcoin cycle context.

Off unless ``SimulationPolicy.cycle_gate`` is set. ``CycleSchedule`` reads the traded
pair's completed daily bars and answers, for a decision time, the daily values of the
latest bar **closed by then** (``daily_sma.signal_day``): whether its close C is above
1.60 × SMA200, and whether C is below 0.50 × ATH. ``CycleSignal`` carries them on a
``Frame``; the engine (``runner.py``) rejects one whose bar had not closed (lookahead
fails closed) and combines it with the observation's own phase (``phase``):

* H2, phase in [18, 30) and C > 1.60 × SMA200: no new grid, and a 2-hour outside-range
  threshold instead of 6 hours;
* H3, phase in [30, 48) and C < 0.50 × ATH: an opportunity-score minimum of 0.60 instead
  of 0.70 in the entry check, whose other conditions all still apply.

SMA200 refuses gaps, as variant A's does (D6). ATH is the highest close from the bar of
the most recent halving's UTC day, which closes after the halving instant, through the
signal day. It is unavailable when the history does not reach back to that bar or misses
a day since, and from a halving until its day's bar closes; H3 then never relaxes.

Everything here is Decimal and pure; nothing reads files or the clock.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, localcontext

from crypto_grid_bot.strategy.daily_sma import DAY_MS, DailyCloses, signal_day

# Spec v1 §3 H: the halvings are historical facts, fixed in the spec (UTC).
HALVINGS = (
    datetime(2016, 7, 9, 16, 46, 13, tzinfo=UTC),  # block 420,000
    datetime(2020, 5, 11, 19, 23, 43, tzinfo=UTC),  # block 630,000
    datetime(2024, 4, 20, 0, 9, 27, tzinfo=UTC),  # block 840,000
)
# The halving instants, and the open times of the daily bars that contain them (UTC ms).
HALVING_MS = tuple(int(h.timestamp()) * 1000 for h in HALVINGS)
HALVING_DAYS = frozenset((h.date() - date(1970, 1, 1)).days * DAY_MS for h in HALVINGS)
H2, H3 = "h2", "h3"
# Phase bands in whole months since the halving, half-open.
H2_PHASES = range(18, 30)
H3_PHASES = range(30, 48)
H2_MULTIPLE = Decimal("1.60")
H3_MULTIPLE = Decimal("0.50")
SMA_WINDOW = 200
# H2's outside-range threshold for existing grids, instead of V0's 6 hours.
H2_OUTSIDE_RANGE_SECONDS = 7_200
# H3 lowers the opportunity-score minimum by this much (0.70 to 0.60) for new grids.
H3_SCORE_RELAXATION = 0.10
# Exact: daily closes and their averages need far fewer digits than this.
_PRECISION = 60


def phase(when: datetime) -> int | None:
    """Whole calendar months since the most recent halving at or before ``when`` (UTC);
    None before the first. ``(year − year_h) × 12 + (month − month_h)``, less 1 while
    ``when``'s day of the month and time of day are earlier than the halving's."""
    halving = next((h for h in reversed(HALVINGS) if h <= when), None)
    if halving is None:
        return None
    months = (when.year - halving.year) * 12 + when.month - halving.month
    if (when.day, when.time()) < (halving.day, halving.time()):
        months -= 1
    return months


def _day(day_ms: int) -> str:
    """ISO date of the UTC day that starts at ``day_ms``."""
    return datetime.fromtimestamp(day_ms / 1000, UTC).date().isoformat()


@dataclass(frozen=True)
class CycleSignal:
    """Variant H's daily values for one decision, from the latest completed daily bar.

    ``day`` is the UTC date of that bar, which closed at 00:00 UTC of the next day.
    ``discounted`` is None when the ATH is unavailable.
    """

    day: str
    overextended: bool = False
    discounted: bool | None = None

    def validate(self, observed: datetime) -> None:
        """Reject a malformed signal, or one read from a bar that had not yet closed at
        ``observed`` (lookahead)."""
        if (
            type(self.day) is not str
            or type(self.overextended) is not bool
            or not (self.discounted is None or type(self.discounted) is bool)
        ):
            raise ValueError("invalid cycle signal")
        day = date.fromisoformat(self.day)
        if day.isoformat() != self.day:  # canonical ISO form only, as for variant A
            raise ValueError("invalid cycle signal")
        if observed < datetime.combine(day + timedelta(days=1), time(), UTC):
            raise ValueError("cycle signal uses a daily bar that had not closed yet")

    def rule(self, observed: datetime) -> str | None:
        """The H rule in force at ``observed``: H2, H3 or None, which changes nothing. A
        signal not from the day before ``observed``'s UTC day (a missing or stale daily
        bar) is None."""
        if self.day != (observed.date() - timedelta(days=1)).isoformat():
            return None
        months = phase(observed)
        if months in H2_PHASES and self.overextended:
            return H2
        if months in H3_PHASES and self.discounted:
            return H3
        return None


class CycleSchedule:
    """Point-in-time variant H values for one pair: one signal per UTC day of its daily
    history, given as (open time in UTC ms, close) pairs."""

    def __init__(self, bars: Iterable[tuple[int, Decimal]]) -> None:
        bars = list(bars)
        closes = DailyCloses(bars)
        opens = [open_ms for open_ms, _ in bars]
        first, last = (min(opens), max(opens)) if opens else (0, -DAY_MS)
        self._signals: dict[int, CycleSignal] = {}
        ath: Decimal | None = None
        with localcontext() as context:
            context.prec = _PRECISION
            for day_ms in range(first, last + DAY_MS, DAY_MS):
                close = closes.close(day_ms)
                if day_ms in HALVING_DAYS:
                    ath = close  # the first close after the halving opens a new cycle
                elif ath is not None:
                    ath = None if close is None else max(ath, close)  # a missing day ends it
                sma200 = closes.sma(day_ms, SMA_WINDOW, precision=_PRECISION)
                self._signals[day_ms] = CycleSignal(
                    _day(day_ms),
                    close is not None and sma200 is not None and close > H2_MULTIPLE * sma200,
                    None if close is None or ath is None else close < H3_MULTIPLE * ath,
                )

    def at(self, when_ms: int) -> CycleSignal:
        """The signal for a decision at ``when_ms`` (Unix ms, UTC).

        Only the bar of the previous UTC day is read, which closed at 00:00 UTC of the
        decision's day, so no bar closing after ``when_ms`` can influence the result.
        Outside the daily history there is nothing to read: no H2, and no ATH.

        A halving at or after that bar's close, and at or before ``when_ms``, has no
        completed close since it until its own day's bar closes at the next midnight: the
        ATH, "the highest completed daily close since the most recent halving" (spec v1
        §3 H), is unavailable until then. SMA200 does not depend on the cycle.
        """
        day_ms = signal_day(when_ms)
        signal = self._signals.get(day_ms) or CycleSignal(_day(day_ms))
        if any(day_ms + DAY_MS <= halving <= when_ms for halving in HALVING_MS):
            return replace(signal, discounted=None)
        return signal
