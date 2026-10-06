"""Parsing of Binance's monthly spot kline CSV archives: strict, and repairing.

Verified layout (2024-12 and 2025-01 ADAUSDT files): one headerless CSV per zip with
12 columns: open time, open, high, low, close, base volume, close time, quote
volume, trade count, taker-buy base volume, taker-buy quote volume, ignore.
Timestamps are milliseconds through 2024-12 and microseconds from 2025-01; both
are normalised to milliseconds here. Missing intervals are counted, never filled.

``parse_rows`` rejects an archive at its first defect. ``parse_rows_repaired`` is the
second reader, for the long-window data rules of spec v1 section 5: it keeps the rows it
can trust and reports the hours it cannot, instead of rejecting the archive.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import DataError, amount, symbol_name

INTERVAL_MS = {"1m": 60_000, "1h": 3_600_000, "1d": 86_400_000}
MAX_CSV_BYTES = 256 * 1024 * 1024
# Microsecond epoch values are >= 1e15 for any date after 2001; milliseconds stay below.
MICROSECOND_FLOOR = 10**15


@dataclass(frozen=True, slots=True)
class Kline:
    open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    taker_buy_base: Decimal


@dataclass(frozen=True, slots=True)
class FileStats:
    rows: int
    expected_rows: int
    missing_rows: int
    gaps: int
    first_open_ms: int | None
    last_open_ms: int | None
    timestamp_units: tuple[str, ...]


def month_bounds_ms(month: str) -> tuple[int, int]:
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError as exc:
        raise DataError("month must be YYYY-MM") from exc
    end = (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _timestamp(raw: str, *, closing: bool) -> tuple[int, str, bool]:
    """A timestamp in ms, its unit, and whether it is exact in that unit.

    Open times end in 000 us and close times in 999 us; anything else is not a
    millisecond-aligned candle boundary. A millisecond timestamp is always exact.
    """
    if not raw.isascii() or not raw.isdigit() or len(raw) > 17:
        raise DataError("timestamp must be a bounded unsigned integer")
    value = int(raw)
    if value >= MICROSECOND_FLOOR:
        return value // 1000, "us", value % 1000 == (999 if closing else 0)
    return value, "ms", True


def _time(raw: str, *, closing: bool) -> tuple[int, str]:
    value, unit, exact = _timestamp(raw, closing=closing)
    if not exact:
        raise DataError("microsecond timestamp is not a candle boundary")
    return value, unit


def _row_times(
    row: list[str], line_number: int, *, exact_close: bool = True
) -> tuple[int, int, str, bool]:
    """A row's open time, close time (both ms), their unit and whether the close is exact.

    With ``exact_close`` (``parse_rows``), a microsecond close must end in 999 us. Without
    it (the repairing reader), a close off that boundary comes back marked inexact: the
    repair rule, not the parser, decides the row. Every other check is DataError either way.
    """
    if len(row) != 12:
        raise DataError(f"line {line_number}: expected 12 columns (no header allowed)")
    open_ms, open_unit = _time(row[0], closing=False)
    if exact_close:
        (close_ms, close_unit), exact = _time(row[6], closing=True), True
    else:
        close_ms, close_unit, exact = _timestamp(row[6], closing=True)
    if open_unit != close_unit:
        raise DataError(f"line {line_number}: mixed timestamp units in one row")
    return open_ms, close_ms, open_unit, exact


def _check_candle(
    line_number: int, open_ms: int, close_ms: int, interval: str, start_ms: int, end_ms: int
) -> None:
    """DataError unless the candle sits on its ``interval`` boundary, inside the month."""
    step = INTERVAL_MS[interval]
    if open_ms % step or close_ms != open_ms + step - 1:
        raise DataError(f"line {line_number}: open/close time is not a {interval} boundary")
    if not start_ms <= open_ms < end_ms:
        raise DataError(f"line {line_number}: candle outside the archive month")


def _row_bar(row: list[str], line_number: int, open_ms: int) -> Kline:
    """The bar of a 12-column row, after checking its prices and volumes."""
    o, h, low, c = (amount(row[i]) for i in (1, 2, 3, 4))
    if not low <= min(o, c) <= max(o, c) <= h:
        raise DataError(f"line {line_number}: inconsistent OHLC prices")
    volume, quote_volume = amount(row[5], positive=False), amount(row[7], positive=False)
    if not row[8].isascii() or not row[8].isdigit():
        raise DataError(f"line {line_number}: invalid trade count")
    taker_base = amount(row[9], positive=False)
    taker_quote = amount(row[10], positive=False)
    if taker_base > volume or taker_quote > quote_volume:
        raise DataError(f"line {line_number}: taker volume exceeds total volume")
    return Kline(open_ms, o, h, low, c, volume, quote_volume, taker_base)


def _file_stats(
    rows: list[Kline], units: set[str], gaps: int, step: int, start_ms: int, end_ms: int
) -> FileStats:
    """The statistics of ``rows``, given the gaps counted between them."""
    expected = (end_ms - start_ms) // step
    if rows:
        # Leading/trailing absence (e.g. listing mid-month) also counts as a gap.
        gaps += int(rows[0].open_ms != start_ms) + int(rows[-1].open_ms != end_ms - step)
    else:
        gaps = 1
    return FileStats(
        rows=len(rows),
        expected_rows=expected,
        missing_rows=expected - len(rows),
        gaps=gaps,
        first_open_ms=rows[0].open_ms if rows else None,
        last_open_ms=rows[-1].open_ms if rows else None,
        timestamp_units=tuple(sorted(units)),
    )


def parse_rows(text: str, interval: str, month: str) -> tuple[list[Kline], FileStats]:
    step = INTERVAL_MS.get(interval)
    if step is None:
        raise DataError("unsupported kline interval")
    start_ms, end_ms = month_bounds_ms(month)
    rows: list[Kline] = []
    units: set[str] = set()
    gaps = 0
    previous: int | None = None
    for line_number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        open_ms, close_ms, unit, _ = _row_times(row, line_number)
        units.add(unit)
        _check_candle(line_number, open_ms, close_ms, interval, start_ms, end_ms)
        if previous is not None:
            if open_ms <= previous:
                raise DataError(f"line {line_number}: candles are duplicated or out of order")
            if open_ms != previous + step:
                gaps += 1
        previous = open_ms
        rows.append(_row_bar(row, line_number, open_ms))
    return rows, _file_stats(rows, units, gaps, step, start_ms, end_ms)


def read_archive(
    path: Path, symbol: str, interval: str, month: str
) -> tuple[list[Kline], FileStats]:
    """Parse the single expected CSV member of a verified archive zip."""
    symbol_name(symbol)
    development_month(month)
    return parse_rows(read_member(path, f"{symbol}-{interval}-{month}.csv"), interval, month)


_MEMBER_MONTH = re.compile(r"-(\d{4}-\d{2})\.csv$")

# What ``read_member`` lets through, besides its DataError, when a stored archive's member
# cannot be decoded: ``zlib.error`` and ``EOFError`` from a corrupt deflate stream, and
# ``RuntimeError`` from an encrypted member, whose subclass ``NotImplementedError`` is a
# compression method zipfile cannot read. A missing file is an ``OSError``, not one of them.
UNDECODABLE = (zlib.error, EOFError, RuntimeError)
_UNREADABLE = (DataError, *UNDECODABLE)


def read_member(path: Path, expected_member: str) -> str:
    """Return the ASCII text of the archive's only member, which must be named as given.

    The member name must end in its month (``...-YYYY-MM.csv``), and that month must be
    in the development window: this is the lowest reader, so the window is enforced
    here and not only in the wrappers that call it. The *content* is returned unchecked:
    ``parse_rows`` is what verifies that every row lies inside the named month.
    """
    month = _MEMBER_MONTH.search(expected_member)
    if month is None:
        raise DataError(f"archive member name carries no month: {expected_member}")
    development_month(month.group(1))
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) != 1 or members[0].filename != expected_member:
                raise DataError(f"archive must contain exactly {expected_member}")
            if members[0].file_size > MAX_CSV_BYTES:
                raise DataError("archive member exceeds the size limit")
            with archive.open(members[0]) as source:
                raw = source.read(MAX_CSV_BYTES + 1)
    except zipfile.BadZipFile as exc:
        raise DataError("invalid zip archive") from exc
    if len(raw) > MAX_CSV_BYTES:
        raise DataError("archive member exceeds the size limit")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise DataError("archive CSV must be ASCII") from exc
    return text


@dataclass(frozen=True, slots=True)
class RepairedRead:
    """What ``parse_rows_repaired`` could trust in one archive, and the hours it could not.

    ``stats`` are ``parse_rows``'s, computed over the kept ``bars`` (equal to the strict
    parser's when no row was dropped). ``repaired`` holds the opens of kept rows whose
    close time was repaired. ``masked_hours`` holds the opens of the hours that contain an
    untrusted row; the row is dropped, and each of those hours inside the month is the
    caller's to mask. The hour of a row outside the month lies outside the month and never
    counts; the row is dropped. ``unreadable`` is "" when the archive
    could be read, else why not; the archive then has no bars and no masked hours, so all
    its hours are absent.
    """

    bars: list[Kline]
    stats: FileStats
    repaired: frozenset[int]
    masked_hours: frozenset[int]
    unreadable: str


def _repairing_step(interval: str) -> int:
    """The step of a 1m or 1h archive; DataError for any other interval (daily is strict)."""
    if interval not in ("1m", "1h"):
        raise DataError("the repairing reader reads 1m and 1h archives only")
    return INTERVAL_MS[interval]


def _hour_of(open_ms: int) -> int:
    """The open of the hour that contains ``open_ms``."""
    return open_ms - open_ms % INTERVAL_MS["1h"]


def _why(exc: Exception) -> str:
    """The reason an archive is unreadable; never empty, since "" would mean readable."""
    return str(exc) or type(exc).__name__


def _unreadable(reason: str, interval: str, month: str) -> RepairedRead:
    """An archive that could not be read: no bars, no rows to mask, every hour absent."""
    step = _repairing_step(interval)
    start_ms, end_ms = month_bounds_ms(month)
    stats = _file_stats([], set(), 0, step, start_ms, end_ms)
    return RepairedRead([], stats, frozenset(), frozenset(), reason)


def _readable_open(row: list[str], line_number: int) -> int:
    """A row's open time in ms, or DataError if column 0 is absent or not an integer.

    Laxer than ``_time`` on purpose: a microsecond open off its boundary still says which
    hour the row falls in, so that row is merely untrusted (``_row_times`` rejects it)
    and the archive stays readable.
    """
    raw = row[0] if row else ""
    if not raw.isascii() or not raw.isdigit() or len(raw) > 17:
        raise DataError(f"line {line_number}: open time is absent or not an integer timestamp")
    value = int(raw)
    return value // 1000 if value >= MICROSECOND_FLOOR else value


def _rows_with_next_open(text: str) -> Iterator[tuple[int, list[str], int, int | None]]:
    """Each row as (line number, fields, open, the next row's open or None if last).

    Streams the rows with one row of look-ahead. A row whose open cannot be read raises
    DataError, which ends the iteration: it makes the whole archive unreadable.
    """
    pending: tuple[int, list[str], int] | None = None
    for line_number, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        open_ms = _readable_open(row, line_number)
        if pending is not None:
            yield (*pending, open_ms)
        pending = (line_number, row, open_ms)
    if pending is not None:
        yield (*pending, None)


def _repairable(open_ms: int, close_ms: int, exact: bool, following: int | None, step: int) -> bool:
    """The refined rule of ``audit.fix_closes`` (PR #65), adopted by spec v1 section 5 rule 1.

    A row's close is repaired to ``open + step - 1`` when it is off the boundary, the open
    is aligned, and the row is the file's last or its next row in file order opens at
    ``open + step`` or later (adjacent included). A microsecond close that does not end in
    999 us (``exact`` False) is off the boundary even when its millisecond is right.
    ``audit`` imports this module, so the rule is restated here, not imported.
    """
    return (
        (not exact or close_ms != open_ms + step - 1)
        and open_ms % step == 0
        and (following is None or following >= open_ms + step)
    )


def parse_rows_repaired(text: str, interval: str, month: str) -> RepairedRead:
    """Read a 1m or 1h archive, keeping the rows it can trust (spec v1 section 5, rule 1).

    A row whose open is not after the last kept row's (a duplicate or an out-of-order row)
    is dropped whatever else is wrong with it, and both its hour and the last kept row's hour
    are masked: the reader keeps one copy, and under-masking is the unsafe direction. Every
    other row gets ``parse_rows``'s checks. A close off the boundary is repaired, in memory
    only, under the refined rule; any other row ``parse_rows`` would reject is dropped and
    its hour masked. The row after a dropped one is judged against the last kept row. A row
    whose open cannot be read has no hour to mask, so the whole archive is unreadable.
    """
    step = _repairing_step(interval)
    start_ms, end_ms = month_bounds_ms(month)
    bars: list[Kline] = []
    units: set[str] = set()
    repaired: set[int] = set()
    masked: set[int] = set()
    gaps = 0
    try:
        for line_number, row, open_ms, following in _rows_with_next_open(text):
            if bars and open_ms <= bars[-1].open_ms:
                masked.update((_hour_of(open_ms), _hour_of(bars[-1].open_ms)))
                continue
            try:
                _, close_ms, unit, exact = _row_times(row, line_number, exact_close=False)
                repair = _repairable(open_ms, close_ms, exact, following, step)
                if not (repair or exact):
                    raise DataError(f"line {line_number}: microsecond close is not a boundary")
                close_ms = open_ms + step - 1 if repair else close_ms
                _check_candle(line_number, open_ms, close_ms, interval, start_ms, end_ms)
                bar = _row_bar(row, line_number, open_ms)
            except DataError:
                masked.add(_hour_of(open_ms))
                continue
            if bars and open_ms != bars[-1].open_ms + step:
                gaps += 1
            bars.append(bar)
            units.add(unit)
            if repair:
                repaired.add(open_ms)
    except (DataError, csv.Error) as exc:
        return _unreadable(_why(exc), interval, month)
    stats = _file_stats(bars, units, gaps, step, start_ms, end_ms)
    return RepairedRead(bars, stats, frozenset(repaired), frozenset(masked), "")


def read_archive_repaired(path: Path, symbol: str, interval: str, month: str) -> RepairedRead:
    """``parse_rows_repaired`` of the archive's single CSV member.

    An archive that ``read_member`` cannot open or decode is unreadable, not an error: a
    ``DataError``, or one of ``UNDECODABLE``. A missing file still raises, as does a bad
    symbol, a month outside the development window or an interval other than 1m and 1h:
    those are the caller's errors, as in ``read_archive``. Daily archives keep
    ``read_archive``: a daily bar is never masked.
    """
    symbol_name(symbol)
    development_month(month)
    _repairing_step(interval)
    try:
        text = read_member(path, f"{symbol}-{interval}-{month}.csv")
    except _UNREADABLE as exc:
        return _unreadable(_why(exc), interval, month)
    return parse_rows_repaired(text, interval, month)


def aggregate(minutes: Iterable[Kline], step_ms: int = INTERVAL_MS["1h"]) -> Iterator[Kline]:
    """Aggregate ordered 1m klines into larger boundary-aligned candles."""
    bucket: list[Kline] = []
    for kline in minutes:
        if bucket and kline.open_ms // step_ms != bucket[0].open_ms // step_ms:
            yield _merge(bucket, step_ms)
            bucket = []
        bucket.append(kline)
    if bucket:
        yield _merge(bucket, step_ms)


def _merge(bucket: list[Kline], step_ms: int) -> Kline:
    return Kline(
        bucket[0].open_ms // step_ms * step_ms,
        bucket[0].open,
        max(k.high for k in bucket),
        min(k.low for k in bucket),
        bucket[-1].close,
        sum((k.volume for k in bucket), Decimal(0)),
        sum((k.quote_volume for k in bucket), Decimal(0)),
        sum((k.taker_buy_base for k in bucket), Decimal(0)),
    )
