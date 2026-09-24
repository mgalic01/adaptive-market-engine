"""Strict parsing of Binance's monthly spot kline CSV archives.

Verified layout (2024-12 and 2025-01 ADAUSDT files): one headerless CSV per zip with
12 columns: open time, open, high, low, close, base volume, close time, quote
volume, trade count, taker-buy base volume, taker-buy quote volume, ignore.
Timestamps are milliseconds through 2024-12 and microseconds from 2025-01; both
are normalised to milliseconds here. Missing intervals are counted, never filled.
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from crypto_grid_bot.market_data.parsing import DataError, amount, symbol_name

INTERVAL_MS = {"1m": 60_000, "1h": 3_600_000}
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


def _time(raw: str, *, closing: bool) -> tuple[int, str]:
    if not raw.isascii() or not raw.isdigit() or len(raw) > 17:
        raise DataError("timestamp must be a bounded unsigned integer")
    value = int(raw)
    if value >= MICROSECOND_FLOOR:
        # Open times end in 000 us and close times in 999 us; anything else is not a
        # millisecond-aligned candle boundary.
        if value % 1000 != (999 if closing else 0):
            raise DataError("microsecond timestamp is not a candle boundary")
        return value // 1000, "us"
    return value, "ms"


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
        if len(row) != 12:
            raise DataError(f"line {line_number}: expected 12 columns (no header allowed)")
        open_ms, open_unit = _time(row[0], closing=False)
        close_ms, close_unit = _time(row[6], closing=True)
        if open_unit != close_unit:
            raise DataError(f"line {line_number}: mixed timestamp units in one row")
        units.add(open_unit)
        if open_ms % step or close_ms != open_ms + step - 1:
            raise DataError(f"line {line_number}: open/close time is not a {interval} boundary")
        if not start_ms <= open_ms < end_ms:
            raise DataError(f"line {line_number}: candle outside the archive month")
        if previous is not None:
            if open_ms <= previous:
                raise DataError(f"line {line_number}: candles are duplicated or out of order")
            if open_ms != previous + step:
                gaps += 1
        previous = open_ms
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
        rows.append(Kline(open_ms, o, h, low, c, volume, quote_volume, taker_base))
    expected = (end_ms - start_ms) // step
    if rows:
        # Leading/trailing absence (e.g. listing mid-month) also counts as a gap.
        gaps += int(rows[0].open_ms != start_ms) + int(rows[-1].open_ms != end_ms - step)
    else:
        gaps = 1
    stats = FileStats(
        rows=len(rows),
        expected_rows=expected,
        missing_rows=expected - len(rows),
        gaps=gaps,
        first_open_ms=rows[0].open_ms if rows else None,
        last_open_ms=rows[-1].open_ms if rows else None,
        timestamp_units=tuple(sorted(units)),
    )
    return rows, stats


def read_archive(
    path: Path, symbol: str, interval: str, month: str
) -> tuple[list[Kline], FileStats]:
    """Parse the single expected CSV member of a verified archive zip."""
    symbol_name(symbol)
    expected_member = f"{symbol}-{interval}-{month}.csv"
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
    return parse_rows(text, interval, month)


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
