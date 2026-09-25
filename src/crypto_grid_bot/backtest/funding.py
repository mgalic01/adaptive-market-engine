"""Funding-rate archives and the G gate's signal (spec v1 §3 G, draft).

Parses Binance's monthly USDⓈ-M ``fundingRate`` CSV archives strictly and decides, at
an observation time, whether G blocks a new grid under the uniform-cadence rule:
the newest usable record and the two usable records before it must all carry finite
rates, the same accepted interval ``I``, exact ``I``-hour steps, and the newest must
not be overdue (``t < scheduled(r3) + I + 60 s``). Anything else is unavailable, and
unavailable blocks. Invalid records are never skipped to reach older valid ones.

Conventions, not verified facts: ``calc_time`` floored to the UTC hour is the
scheduled time, and a record becomes usable 60 s after ``calc_time`` (truncated to
the second). A record's successor is assumed to follow after its own interval.
"""

from __future__ import annotations

import csv
import io
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from crypto_grid_bot.backtest.klines import MICROSECOND_FLOOR, month_bounds_ms, read_member
from crypto_grid_bot.market_data.parsing import DataError, symbol_name

HEADER = ("calc_time", "funding_interval_hours", "last_funding_rate")
ACCEPTED_INTERVAL_HOURS = frozenset({1, 2, 4, 8})
HOUR_MS = 3_600_000
PUBLICATION_ALLOWANCE_MS = 60_000
BLOCK_RATE = Decimal("0.0005")


@dataclass(frozen=True, slots=True)
class FundingRecord:
    """One settlement. ``interval_hours`` is None when the field is empty or not an integer;
    ``rate`` may be non-finite or of unsupported precision (a decimal exponent outside
    -18..18, the bound ``parsing.amount`` uses). Such records are kept, and make G
    unavailable."""

    calc_time_ms: int
    interval_hours: int | None
    rate: Decimal

    @property
    def scheduled_ms(self) -> int:
        return self.calc_time_ms - self.calc_time_ms % HOUR_MS

    @property
    def usable_ms(self) -> int:
        return self.calc_time_ms - self.calc_time_ms % 1000 + PUBLICATION_ALLOWANCE_MS

    @property
    def valid(self) -> bool:
        if self.interval_hours not in ACCEPTED_INTERVAL_HOURS or not self.rate.is_finite():
            return False
        # Extreme exponents (e.g. "1E-9999") can exhaust Decimal operations downstream.
        exponent = self.rate.as_tuple().exponent
        return isinstance(exponent, int) and -18 <= exponent <= 18


@dataclass(frozen=True, slots=True)
class FundingState:
    available: bool
    blocks: bool
    reason: str


def _calc_time(raw: str) -> int:
    if not raw.isascii() or not raw.isdigit() or len(raw) > 17:
        raise DataError("calc_time must be a bounded unsigned integer")
    value = int(raw)
    return value // 1000 if value >= MICROSECOND_FLOOR else value


def _interval(raw: str) -> int | None:
    raw = raw.strip()
    if not raw.isascii() or not raw.isdigit() or len(raw) > 3:
        return None
    return int(raw)


def _rate(raw: str) -> Decimal:
    if len(raw) > 64:
        raise DataError("funding rate is too long")
    try:
        return Decimal(raw.strip())
    except InvalidOperation as exc:
        raise DataError("funding rate is not a number") from exc


def parse_funding_rows(text: str, month: str) -> list[FundingRecord]:
    """Parse one month. Structure errors raise; an invalid interval or rate is kept."""
    start_ms, end_ms = month_bounds_ms(month)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or tuple(rows[0]) != HEADER:
        raise DataError(f"funding header must be {','.join(HEADER)}")
    records: list[FundingRecord] = []
    for line_number, row in enumerate(rows[1:], start=2):
        if len(row) != 3:
            raise DataError(f"line {line_number}: expected 3 columns")
        record = FundingRecord(_calc_time(row[0]), _interval(row[1]), _rate(row[2]))
        if not start_ms <= record.calc_time_ms < end_ms:
            raise DataError(f"line {line_number}: settlement outside the archive month")
        if records and record.calc_time_ms <= records[-1].calc_time_ms:
            raise DataError(f"line {line_number}: settlements are duplicated or out of order")
        records.append(record)
    return records


def read_funding_archive(path: Path, symbol: str, month: str) -> list[FundingRecord]:
    symbol_name(symbol)
    return parse_funding_rows(read_member(path, f"{symbol}-fundingRate-{month}.csv"), month)


class FundingSignal:
    """Point-in-time G decisions over a whole funding history."""

    def __init__(self, records: Iterable[FundingRecord]) -> None:
        ordered = sorted(records, key=lambda record: record.calc_time_ms)
        for before, after in zip(ordered, ordered[1:], strict=False):
            if before.scheduled_ms == after.scheduled_ms:
                # Spec §5: an integrity failure for the window, never collapsed.
                raise DataError("two funding records share a scheduled time")
        self._records: Sequence[FundingRecord] = ordered
        self._usable = [record.usable_ms for record in ordered]

    def state(self, t_ms: int) -> FundingState:
        count = bisect_right(self._usable, t_ms)
        if count < 3:
            return FundingState(False, True, "insufficient_history")
        r1, r2, r3 = self._records[count - 3 : count]
        if not r3.valid:
            return FundingState(False, True, "invalid_newest")
        if not (r1.valid and r2.valid):
            return FundingState(False, True, "invalid_older")
        interval = r3.interval_hours
        if interval is None:  # unreachable: r3.valid implies an accepted interval
            return FundingState(False, True, "invalid_newest")
        if not r1.interval_hours == r2.interval_hours == interval:
            return FundingState(False, True, "mixed_interval")
        step = interval * HOUR_MS
        if r2.scheduled_ms - r1.scheduled_ms != step or r3.scheduled_ms - r2.scheduled_ms != step:
            return FundingState(False, True, "step_mismatch")
        if t_ms >= r3.scheduled_ms + step + PUBLICATION_ALLOWANCE_MS:
            return FundingState(False, True, "overdue")
        high = all(record.rate > BLOCK_RATE for record in (r1, r2, r3))
        return FundingState(True, high, "high_funding" if high else "clear")
