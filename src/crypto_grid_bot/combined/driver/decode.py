"""One pinned archive month decoded into the inputs V3.1 packs: hourly bars, funding
records or minute bars.

Pure decoding: the bytes arrive already fetched, and nothing here opens a path or touches
the network. Each month is checked against its manifest entry first (the reserved
boundary, the status, the pinned SHA-256 and, for hourly bars, the masked and repaired
hours the inventory recorded), and every refusal is a ``ValueError`` that names the entry.
``scripts/v3_replay_inputs.decode_inventory_archive`` is the reference decoder; this one
serves the inventory's spot, futures and funding months and the legacy minute manifests.
"""

import hashlib
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from crypto_grid_bot.backtest.funding import FundingRecord, parse_funding_rows
from crypto_grid_bot.backtest.klines import (
    Kline,
    member_compression,
    month_bounds_ms,
    parse_rows_repaired,
    read_member,
    undecodable,
)
from crypto_grid_bot.combined.baseline_records import refuse_sealed
from crypto_grid_bot.combined.driver.flow_schedule import HOUR
from crypto_grid_bot.market_data.parsing import DataError, symbol_name
from crypto_grid_bot.trend.data import repaired_month

_RESERVED = 1_735_689_600_000
_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_KINDS = frozenset({"spot", "futures", "funding"})
# The header of Binance's futures kline CSVs; the spot ones have none.
_KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)


@dataclass(frozen=True, slots=True)
class DecodedV31Month:
    """One inventory month. ``status`` is the entry's: an ``excluded`` month is decoded
    all the same, and what it means is the caller's to decide.

    ``hourly`` holds the kline months' bars outside the masked and repaired hours;
    ``missing_hours`` every hour of the month with no bar in ``hourly``. A funding month
    has ``funding`` instead, every record with the interval its own row carries.
    """

    kind: str
    symbol: str
    month: str
    status: str
    hourly: tuple[Kline, ...] = ()
    funding: tuple[FundingRecord, ...] = ()
    missing_hours: frozenset[int] = frozenset()


def decode_month(entry: Mapping[str, object], content: bytes) -> DecodedV31Month:
    """Decode one eligible or excluded inventory month from its pinned archive bytes.

    Refuses, before any byte is read, a month at or after the reserved boundary; then a
    missing month, bytes whose SHA-256 differs from the entry's and, for kline months, an
    entry whose masked or repaired hours differ from the ones the bytes give.
    """
    label = _label(entry)
    month = _month(entry, label)
    kind, status = entry.get("kind"), entry.get("status")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError(f"{label}: kind must be spot, futures or funding")
    if status == "missing":
        raise ValueError(f"{label}: a missing month has no archive to decode")
    if not isinstance(status, str) or status not in ("eligible", "excluded"):
        raise ValueError(f"{label}: status must be eligible or excluded")
    symbol = _symbol(entry, label)
    _verify(entry, content, label)
    text = _member_text(
        label, content, f"{symbol}-{'fundingRate' if kind == 'funding' else '1h'}-{month}.csv"
    )
    if kind == "funding":
        with _refusing(label):
            records = parse_funding_rows(text, month)
        return DecodedV31Month(kind, symbol, month, status, funding=tuple(records))
    hourly, missing = _hourly(entry, label, kind, month, text)
    return DecodedV31Month(kind, symbol, month, status, hourly=hourly, missing_hours=missing)


def decode_minute_month(entry: Mapping[str, object], content: bytes) -> Iterator[Kline]:
    """The minute bars of one ``ok`` 1m month of a legacy minute manifest, in ascending
    ``open_ms``, less every repaired minute and every minute of an hour the reader
    distrusts: the flow gate reads a dropped minute as unavailable, the conservative side.

    The entry's reserved boundary, status and SHA-256 are refused by the call itself; the
    archive is read when the first bar is requested, and one month is held while it runs.
    """
    label = _label(entry)
    month = _month(entry, label)
    symbol = _symbol(entry, label)
    if entry.get("interval") != "1m" or entry.get("status") != "ok":
        raise ValueError(f"{label}: only an ok 1m archive is decoded as minute bars")
    _verify(entry, content, label)
    return _minute_bars(label, symbol, month, content)


def _label(entry: Mapping[str, object]) -> str:
    """How refusals name ``entry``: its archive path or URL, else its symbol and month."""
    for key in ("path", "url"):
        name = entry.get(key)
        if isinstance(name, str):
            return name
    return f"{entry.get('symbol')} {entry.get('month')}"


def _month(entry: Mapping[str, object], label: str) -> str:
    """The entry's month, which must be canonical and before the reserved boundary."""
    month = entry.get("month")
    if not isinstance(month, str) or _MONTH.fullmatch(month) is None:
        raise ValueError(f"{label}: month must be YYYY-MM")
    refuse_sealed([month_bounds_ms(month)[0]], label)
    return month


def _symbol(entry: Mapping[str, object], label: str) -> str:
    symbol = entry.get("symbol")
    if not isinstance(symbol, str):
        raise ValueError(f"{label}: symbol must be a string")
    with _refusing(label):
        return symbol_name(symbol)


def _verify(entry: Mapping[str, object], content: bytes, label: str) -> None:
    digest = entry.get("sha256")
    if type(content) is not bytes or hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"{label}: the archive bytes do not match the pinned sha256")


@contextmanager
def _refusing(label: str) -> Iterator[None]:
    """Re-raise a reader's ValueError, which never names its archive, with ``label``."""
    try:
        yield
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc


def _member_text(label: str, content: bytes, member: str) -> str:
    """The ASCII text of the archive's only member, which must be named ``member``."""
    with TemporaryDirectory(prefix="v31-decode-") as directory:
        local = Path(directory) / "archive.zip"
        local.write_bytes(content)
        try:
            return read_member(local, member)
        except Exception as exc:
            if not isinstance(exc, DataError) and not undecodable(exc, member_compression(local)):
                raise
            raise ValueError(f"{label}: {exc}") from exc


def _hours(entry: Mapping[str, object], key: str, label: str) -> frozenset[int]:
    value = entry.get(key)
    if not isinstance(value, list | tuple) or not all(type(hour) is int for hour in value):
        raise ValueError(f"{label}: {key} must be a list of hour stamps")
    return frozenset(value)


def _hourly(
    entry: Mapping[str, object], label: str, kind: str, month: str, text: str
) -> tuple[tuple[Kline, ...], frozenset[int]]:
    """The month's bars outside its masked and repaired hours, and the hours with no bar.

    The entry's ``masked_hours`` is the inventory's whole mask, the repaired and untrusted
    hours and the absent ones together (``repaired_month``); ``repaired_hours`` is the
    reader's repaired opens alone. Each is compared with the same set recomputed here.
    """
    if kind == "futures" and text.partition("\n")[0].rstrip("\r") == _KLINE_HEADER:
        text = text.partition("\n")[2]
    with _refusing(label):
        read = parse_rows_repaired(text, "1h", month)
        masked = repaired_month(read, month).masked_hours
    if masked != _hours(entry, "masked_hours", label):
        raise ValueError(f"{label}: the masked hours differ from the pinned entry's")
    if read.repaired != _hours(entry, "repaired_hours", label):
        raise ValueError(f"{label}: the repaired hours differ from the pinned entry's")
    hourly = tuple(bar for bar in read.bars if bar.open_ms not in masked)
    present = {bar.open_ms for bar in hourly}
    start, end = month_bounds_ms(month)
    absent = frozenset(h for h in range(start, min(end, _RESERVED), HOUR) if h not in present)
    return hourly, absent


def _minute_bars(label: str, symbol: str, month: str, content: bytes) -> Iterator[Kline]:
    text = _member_text(label, content, f"{symbol}-1m-{month}.csv")
    with _refusing(label):
        read = parse_rows_repaired(text, "1m", month)
    if read.unreadable:
        raise ValueError(f"{label}: unreadable: {read.unreadable}")
    for bar in read.bars:
        if (
            bar.open_ms not in read.repaired
            and bar.open_ms - bar.open_ms % HOUR not in read.masked_hours
        ):
            yield bar
