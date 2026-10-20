"""Readers for the V4 data step: kline and funding archive bytes to bars, masks and funding rows.

``read_daily`` and ``read_hourly`` turn the bytes of one monthly kline archive (spot daily,
spot hourly, USDT-M perpetual hourly) into bars. They are the repairing reader of spec v1
section 5 rule 1, which the V4 spec adopts on both venues and for daily archives, and they
follow ``backtest.klines.parse_rows_repaired`` rule for rule:

* a row whose open is not after the last kept row's is dropped, and both its interval and the
  last kept row's interval are masked;
* a close off the boundary is repaired to ``open + step - 1`` under the refined rule
  (``_repairable``); the repaired interval is recorded in ``repaired`` and, because the spec
  masks repaired hours, in ``masked`` too, and its bar stays in ``bars``;
* any other row the strict checks reject (boundary, inside the month, the candle's numbers) is
  dropped and its interval masked;
* a row whose open cannot be read has no interval to mask, so the whole archive is unreadable.

``masked`` holds the interval of every dropped row, as the reference does, including one
outside the month; the caller keeps the intervals inside it. A missing interval is a gap, not a
mask. Timestamps are microseconds from 2025-01 and are normalised to milliseconds. The step is
one hour for hourly archives and one day for daily ones.

``read_funding`` reads a monthly funding archive, and ``funding_month_status`` judges whether a
month's rows are the exact funding schedule (V3 section 2, with V4's listing span).

The row-level helpers are the reference's own, imported because they are pure: they never call
its 2024 guard (``development_month``), which only its ``read_member``, ``read_archive`` and
``read_archive_repaired`` run. None of those is used here, so any month is readable.
"""

from __future__ import annotations

import csv
import io
import lzma
import re
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

from crypto_grid_bot.backtest.klines import (
    INTERVAL_MS,
    MAX_CSV_BYTES,
    MICROSECOND_FLOOR,
    Kline,
    _check_candle,
    _repairable,
    _row_bar,
    _row_times,
    _rows_with_next_open,
    month_bounds_ms,
)
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.v4.data.archives import archive_path

# The header of a USDT-M perpetual kline CSV (spot CSVs have none). The text of
# scripts/fetch_v3_data.py::KLINE_HEADER, which a test compares.
FUTURES_KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)
_FUNDING_HEADER = ("calc_time", "funding_interval_hours", "last_funding_rate")
_FUNDING_HEADER_WITHOUT_INTERVAL = ("calc_time", "last_funding_rate")
# A funding file without the interval column is read as 8 hours (the spec's rule).
DEFAULT_FUNDING_INTERVAL_HOURS = 8
# A settlement is recorded this long after its slot, at most.
SLOT_TOLERANCE_MS = 60_000
_HOUR_MS = INTERVAL_MS["1h"]

_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_RATE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
# Every way a zip member can fail to decode. The archive is read from memory, so an OSError
# cannot be the file system's; it is bzip2's "Invalid data stream". RuntimeError is an encrypted
# member, and its subclass NotImplementedError a compression method zipfile cannot read.
_UNDECODABLE = (zipfile.BadZipFile, zlib.error, lzma.LZMAError, EOFError, RuntimeError, OSError)


@dataclass(frozen=True, slots=True)
class DailyBar:
    open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    quote_volume: Decimal


@dataclass(frozen=True, slots=True)
class HourBar:
    """A daily bar's fields and the base volume.

    ``volume`` and ``quote_volume`` are both Decimals, so ``volume`` is keyword-only: a
    positional seventh argument could swap them without a type error.
    """

    open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    quote_volume: Decimal
    volume: Decimal = field(kw_only=True)


@dataclass(frozen=True, slots=True)
class FundingRow:
    """One settlement. ``interval_hours`` is None when the file has no such column."""

    time_ms: int
    rate: Decimal
    interval_hours: int | None


@dataclass(frozen=True, slots=True)
class KlineRead[B: (DailyBar, HourBar)]:
    """What could be trusted in one kline archive, and the intervals that could not.

    ``masked`` and ``repaired`` hold interval opens in ms; ``repaired`` is a subset of
    ``masked``. ``unreadable`` is "" when the archive could be read, else why not: ``bars`` is
    then empty and the caller masks the whole month.
    """

    bars: tuple[B, ...]
    masked: frozenset[int]
    repaired: frozenset[int]
    unreadable: str


class _Parsed(NamedTuple):
    bars: list[Kline]
    masked: frozenset[int]
    repaired: frozenset[int]
    unreadable: str


def _why(exc: Exception) -> str:
    """The reason an archive is unreadable; never empty, since "" would mean readable."""
    return str(exc) or type(exc).__name__


def _member(kind: str, symbol: str, month: str) -> str:
    """The one CSV an archive holds: the archive's file name, ``.csv`` for ``.zip``.

    ``archive_path`` checks the kind, the symbol and the month: ``ValueError`` for a bad one.
    """
    return archive_path(kind, symbol, month).rsplit("/", 1)[1].removesuffix(".zip") + ".csv"


def _member_text(content: bytes, member: str) -> str:
    """The ASCII text of the zip's only member, which must be named ``member``; else DataError."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != member:
                raise DataError(f"archive must contain exactly {member}")
            if members[0].file_size > MAX_CSV_BYTES:
                raise DataError("archive member exceeds the size limit")
            with archive.open(members[0]) as source:
                raw = source.read(MAX_CSV_BYTES + 1)
    except _UNDECODABLE as exc:
        raise DataError(f"archive cannot be read: {_why(exc)}") from exc
    if len(raw) > MAX_CSV_BYTES:
        raise DataError("archive member exceeds the size limit")
    try:
        return raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DataError("archive CSV must be ASCII") from exc


def _interval_open(open_ms: int, step: int) -> int:
    """The open of the interval that contains ``open_ms``."""
    return open_ms - open_ms % step


def _parse(
    content: bytes, kind: str, symbol: str, month: str, interval: str, *, drop_header: bool
) -> _Parsed:
    """The reference's ``parse_rows_repaired`` over the archive's CSV, for a 1h or 1d step."""
    member = _member(kind, symbol, month)
    try:
        text = _member_text(content, member)
    except DataError as exc:
        return _Parsed([], frozenset(), frozenset(), _why(exc))
    if drop_header and text.partition("\n")[0].rstrip("\r") == FUTURES_KLINE_HEADER:
        text = text.partition("\n")[2]
    step = INTERVAL_MS[interval]
    start_ms, end_ms = month_bounds_ms(month)
    bars: list[Kline] = []
    repaired: set[int] = set()
    masked: set[int] = set()
    try:
        for line_number, row, open_ms, following in _rows_with_next_open(text):
            if bars and open_ms <= bars[-1].open_ms:
                masked.update(
                    (_interval_open(open_ms, step), _interval_open(bars[-1].open_ms, step))
                )
                continue
            try:
                _, close_ms, _, exact = _row_times(row, line_number, exact_close=False)
                repair = _repairable(open_ms, close_ms, exact, following, step)
                if not (repair or exact):
                    raise DataError(f"line {line_number}: microsecond close is not a boundary")
                close_ms = open_ms + step - 1 if repair else close_ms
                _check_candle(line_number, open_ms, close_ms, interval, start_ms, end_ms)
                bar = _row_bar(row, line_number, open_ms)
            except DataError:
                masked.add(_interval_open(open_ms, step))
                continue
            bars.append(bar)
            if repair:
                repaired.add(open_ms)
    except (DataError, csv.Error) as exc:
        return _Parsed([], frozenset(), frozenset(), _why(exc))
    return _Parsed(bars, frozenset(masked | repaired), frozenset(repaired), "")


def read_daily(content: bytes, symbol: str, month: str) -> KlineRead[DailyBar]:
    """The daily bars of one spot archive (``spot_1d``); intervals are day opens."""
    parsed = _parse(content, "spot_1d", symbol, month, "1d", drop_header=False)
    bars = tuple(
        DailyBar(k.open_ms, k.open, k.high, k.low, k.close, k.quote_volume) for k in parsed.bars
    )
    return KlineRead(bars, parsed.masked, parsed.repaired, parsed.unreadable)


def read_hourly(content: bytes, symbol: str, month: str, *, futures: bool) -> KlineRead[HourBar]:
    """The hourly bars of one spot or USDT-M perpetual archive; intervals are hour opens.

    A futures CSV may start with its header line, which is dropped; a spot CSV has none, so its
    first line is always a row.
    """
    parsed = _parse(
        content,
        "futures_1h" if futures else "spot_1h",
        symbol,
        month,
        "1h",
        drop_header=futures,
    )
    bars = tuple(
        HourBar(k.open_ms, k.open, k.high, k.low, k.close, k.quote_volume, volume=k.volume)
        for k in parsed.bars
    )
    return KlineRead(bars, parsed.masked, parsed.repaired, parsed.unreadable)


def _unsigned(raw: str, name: str, line_number: int) -> int:
    if not raw.isascii() or not raw.isdigit() or len(raw) > 17:
        raise DataError(f"line {line_number}: {name} must be a bounded unsigned integer")
    return int(raw)


def _rate(raw: str, line_number: int) -> Decimal:
    """A finite rate of at most 64 characters, with the exponent bound ``parsing.amount`` uses
    (a rate may be negative, which ``amount`` does not allow)."""
    try:
        number = Decimal(raw) if len(raw) <= 64 and _RATE.fullmatch(raw) else None
    except InvalidOperation:  # an exponent beyond Decimal's own range
        number = None
    if number is not None:
        exponent = number.as_tuple().exponent
        if isinstance(exponent, int) and -18 <= exponent <= 18:
            return number
    raise DataError(f"line {line_number}: last_funding_rate is not a finite decimal")


def read_funding(content: bytes, symbol: str, month: str) -> tuple[FundingRow, ...]:
    """The rows of one monthly funding archive, in file order.

    Structure is strict: the header must be ``calc_time,funding_interval_hours,
    last_funding_rate`` (or without the interval column, giving ``interval_hours=None``), every
    row must have that many columns, and a time, interval or rate must parse; else ``DataError``
    (a ``ValueError``). A row outside the month or off its slot is not an error here: it is
    ``funding_month_status``'s ``"off_slot"``. A time in microseconds becomes milliseconds.
    """
    text = _member_text(content, _member("funding", symbol, month))
    try:
        table = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise DataError(f"funding CSV cannot be parsed: {exc}") from exc
    header = tuple(table[0]) if table else ()
    if header == _FUNDING_HEADER:
        width = 3
    elif header == _FUNDING_HEADER_WITHOUT_INTERVAL:
        width = 2
    else:
        raise DataError(
            "funding header must be calc_time,funding_interval_hours,last_funding_rate "
            "(or calc_time,last_funding_rate)"
        )
    rows: list[FundingRow] = []
    for line_number, row in enumerate(table[1:], start=2):
        if len(row) != width:
            raise DataError(f"line {line_number}: expected {width} columns")
        time = _unsigned(row[0], "calc_time", line_number)
        interval = _unsigned(row[1], "funding_interval_hours", line_number) if width == 3 else None
        rows.append(
            FundingRow(
                time // 1000 if time >= MICROSECOND_FLOOR else time,
                _rate(row[-1], line_number),
                interval,
            )
        )
    return tuple(rows)


def funding_month_status(
    rows: Sequence[FundingRow], month: str, *, first_ms: int, last_ms: int
) -> str:
    """``"complete"``, or the first reason a month's funding rows are not the exact schedule.

    ``first_ms`` and ``last_ms`` bound the perpetual's trading span from its klines, over its
    whole history: ``first_ms`` is its first hourly bar's open and ``last_ms`` its last hourly
    bar's close (open + 3,600,000 - 1). They never come from the funding file being judged. A
    listing or delisting month is judged only while listed. The reasons, in the order they are
    checked:

    * ``"interval_mixed"``: the rows declare more than one interval (a row without the column
      counts as 8 hours);
    * ``"interval_not_divisor_of_24"``: the interval I does not divide 24;
    * ``"off_slot"``: a row is not within 60,000 ms after an expected slot, at or after the
      slot itself. The expected slots are 00:00 UTC + k x I hours inside the month, from the
      first slot at or after ``first_ms`` (or the month's first slot, if later) to the last
      slot at or before ``last_ms`` (or the month's last, if earlier). A row in another
      month, before the first expected slot or after the last is off slot;
    * ``"duplicate_slot"``: an expected slot has more than one row;
    * ``"missing_slot"``: an expected slot has no row. A month with no rows is missing them all.

    A span can touch a month yet hold no slot in it (listed at 17:00 and delisted at 23:00 on
    a day with 8-hour slots): the month then expects no rows, so no rows is ``"complete"``.
    A month without a file inside the span is the caller's ``"missing_file"``; a month the span
    does not touch is a ``ValueError``, as is a bad month or ``first_ms`` after ``last_ms``.
    """
    if not isinstance(month, str) or _MONTH.fullmatch(month) is None:
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    start, end = month_bounds_ms(month)
    if first_ms > last_ms:
        raise ValueError(f"first_ms {first_ms} is after last_ms {last_ms}")
    first, last = max(first_ms, start), min(last_ms, end - 1)
    if first > last:
        raise ValueError(f"the listing span {first_ms}..{last_ms} does not touch month {month}")
    intervals = {
        DEFAULT_FUNDING_INTERVAL_HOURS if row.interval_hours is None else row.interval_hours
        for row in rows
    }
    if len(intervals) > 1:
        return "interval_mixed"
    hours = next(iter(intervals), DEFAULT_FUNDING_INTERVAL_HOURS)
    if hours <= 0 or 24 % hours:
        return "interval_not_divisor_of_24"
    step = hours * _HOUR_MS
    # The first slot at or after the span's start (ceiling) and the last at or before its end.
    first_slot, last_slot = -((start - first) // step), (last - start) // step
    seen: dict[int, int] = {}
    for row in rows:
        slot, offset = divmod(row.time_ms - start, step)
        if offset > SLOT_TOLERANCE_MS or not first_slot <= slot <= last_slot:
            return "off_slot"
        seen[slot] = seen.get(slot, 0) + 1
    if any(count > 1 for count in seen.values()):
        return "duplicate_slot"
    if len(seen) != last_slot - first_slot + 1:
        return "missing_slot"
    return "complete"
