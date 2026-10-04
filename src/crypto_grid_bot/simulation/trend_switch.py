"""Variant A of experiment spec v1 (§3 A): the daily SMA50/SMA200 trend/cycle switch.

Off unless ``SimulationPolicy.trend_switch`` is set. It has two halves:

* ``TrendSchedule`` classifies the traded pair's completed daily bars, over the whole
  daily history including the warm-up, and answers for a decision time the state that
  the latest daily bar **closed by then** produced. A bar for UTC day ``d`` closes at
  00:00:00 UTC of ``d + 1``; before that instant it is never read.
* ``TrendSignal`` carries that answer on a ``Frame``. The engine (``runner.py``) turns it
  into restrictions only: a new grid needs the Up state and no running Down sequence,
  and a Down sequence cancels resting buys at once and liquidates what is left at its
  deadline (P1 exit reason ``trend_exit``). No V0 control is delayed or removed.

Everything here is Decimal and pure; nothing reads files or the clock.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Protocol

from crypto_grid_bot.simulation.models import timestamp
from crypto_grid_bot.strategy.daily_sma import DailyCloses

UP = "up"
RECOVERING = "recovering"
MIDDLE = "middle"
DOWN = "down"
UNAVAILABLE = "unavailable"
STATES = (UP, RECOVERING, MIDDLE, DOWN, UNAVAILABLE)

DAY_MS = 86_400_000
SHORT_WINDOW = 50
LONG_WINDOW = 200
# Spec §3 A: at least 200 completed daily bars before the first evaluated minute (P3).
MINIMUM_DAILY_WARMUP = 200
# Spec §3 A: the trend deadline is T0 + 24 h; further Down days do not reset it.
DOWN_DEADLINE_SECONDS = 86_400
_EPOCH = date(1970, 1, 1)


class DailyBar(Protocol):
    """A completed UTC daily bar; ``backtest.klines.Kline`` satisfies it."""

    @property
    def open_ms(self) -> int: ...

    @property
    def close(self) -> Decimal: ...


def day_of(day_number: int) -> str:
    """ISO date of the UTC day ``day_number`` days after 1970-01-01."""
    return (_EPOCH + timedelta(days=day_number)).isoformat()


def next_state(
    previous: str, close: Decimal | None, sma50: Decimal | None, sma200: Decimal | None
) -> str:
    """One completed daily bar's transition (the table in spec §3 A)."""
    if previous not in STATES:
        raise ValueError(f"unknown trend state {previous!r}")
    if close is None or sma50 is None or sma200 is None:
        return UNAVAILABLE  # a missing bar or an undefined average; the count restarts
    if close > sma200:
        # Up is reached only through Recovering: two consecutive closes above SMA200.
        return UP if previous in (UP, RECOVERING) else RECOVERING
    if close > sma50:
        return MIDDLE
    return DOWN


@dataclass(frozen=True)
class DailyClassification:
    day: str  # UTC date of the daily bar (its open day)
    close: Decimal | None
    sma50: Decimal | None
    sma200: Decimal | None
    state: str


def classify_days(bars: Sequence[DailyBar]) -> list[DailyClassification]:
    """Run the state machine over the daily history, from the first day on which
    SMA200 is defined. The state before that day is Middle.

    Every calendar day between the first and last bar is visited; a day without a bar
    (or with a non-positive close) is missing and classifies as Unavailable. The closes
    and averages are variant D's (``strategy.daily_sma``), so both variants share one
    rule: a missing day inside a window leaves its average undefined.
    """
    numbers: list[int] = []
    for bar in bars:
        if bar.open_ms % DAY_MS:
            raise ValueError("daily bars must open at 00:00 UTC")
        numbers.append(bar.open_ms // DAY_MS)
    if any(b <= a for a, b in zip(numbers, numbers[1:], strict=False)):
        raise ValueError("daily bars must be strictly increasing, each day at most once")
    if not numbers:
        return []
    closes = DailyCloses((bar.open_ms, bar.close) for bar in bars)
    result: list[DailyClassification] = []
    state = MIDDLE
    for number in range(numbers[0], numbers[-1] + 1):
        day_ms = number * DAY_MS
        sma200 = closes.sma(day_ms, LONG_WINDOW)
        if not result and sma200 is None:
            continue  # the machine starts on the first day SMA200 is defined
        close, sma50 = closes.close(day_ms), closes.sma(day_ms, SHORT_WINDOW)
        state = next_state(state, close, sma50, sma200)
        result.append(DailyClassification(day_of(number), close, sma50, sma200, state))
    return result


def _midnight_after(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time(), UTC)


@dataclass(frozen=True)
class TrendSignal:
    """The variant A state for one decision, from the latest completed daily bar.

    ``day`` is the UTC date of the bar the state comes from; that bar closed at 00:00
    UTC of the next day. ``last_down`` is the latest classified day, up to ``day``,
    whose state was Down; the engine uses it to start a Down sequence.
    """

    day: str
    state: str
    last_down: str | None = None

    def validate(self, observed_at: str) -> None:
        """Reject a malformed signal, or one read from a bar that had not yet closed at
        ``observed_at`` (lookahead)."""
        if type(self.day) is not str or self.state not in STATES:
            raise ValueError("invalid daily trend signal")
        day = date.fromisoformat(self.day)
        # Canonical ISO form only: the engine orders days as text, and "2026-1-5"
        # would parse yet sort wrongly against "2026-01-05".
        if day.isoformat() != self.day:
            raise ValueError("invalid daily trend signal")
        if self.last_down is not None and (
            type(self.last_down) is not str
            or date.fromisoformat(self.last_down).isoformat() != self.last_down
            or date.fromisoformat(self.last_down) > day
        ):
            raise ValueError("invalid daily trend signal")
        if timestamp(observed_at) < _midnight_after(day):
            raise ValueError("daily trend signal uses a bar that had not closed yet")


def effective_state(signal: TrendSignal | None, observed_at: str) -> str:
    """The state that gates this observation. No signal, or one not from the day before
    the observation's UTC day (a missing or stale daily bar), is Unavailable."""
    if signal is None:
        return UNAVAILABLE
    yesterday = timestamp(observed_at).date() - timedelta(days=1)
    return signal.state if signal.day == yesterday.isoformat() else UNAVAILABLE


def starts_down_sequence(signal: TrendSignal, applied_day: str) -> bool:
    """Whether a Down classification became effective since the account last applied a
    signal (``applied_day``, empty before its first). On the first signal only a Down
    state on the signal's own day counts; older Down days predate the account's run."""
    if signal.last_down is None:
        return False
    if not applied_day:
        return signal.last_down == signal.day
    return signal.last_down > applied_day


class TrendSchedule:
    """Point-in-time daily states for one pair, from its completed daily bars."""

    def __init__(self, bars: Sequence[DailyBar]) -> None:
        self.days = classify_days(bars)
        self._opens = [bar.open_ms for bar in bars]
        self._index = {entry.day: index for index, entry in enumerate(self.days)}
        self._last_down: list[str | None] = []
        latest: str | None = None
        for entry in self.days:
            if entry.state == DOWN:
                latest = entry.day
            self._last_down.append(latest)

    def completed_bars(self, when_ms: int) -> int:
        """Daily bars that had closed at ``when_ms`` (open + one day <= when_ms)."""
        return bisect_right(self._opens, when_ms - DAY_MS)

    def at(self, when_ms: int) -> TrendSignal:
        """The signal for a decision at ``when_ms`` (Unix ms, UTC).

        Only the bar of the previous UTC day is read, which closed at 00:00 UTC of the
        decision's day, so no bar closing after ``when_ms`` can influence the result.
        """
        target = day_of(when_ms // DAY_MS - 1)
        if not self.days or target < self.days[0].day:
            return TrendSignal(target, MIDDLE)  # before the first classified day
        index = self._index.get(target)
        if index is None:
            # After the last daily bar: that day's bar is missing.
            return TrendSignal(target, UNAVAILABLE, self._last_down[-1])
        return TrendSignal(target, self.days[index].state, self._last_down[index])
