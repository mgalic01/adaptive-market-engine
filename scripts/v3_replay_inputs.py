"""Offline monthly decoding; no historical dispatch or data-access authorization."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from fetch_v3_data import KLINE_HEADER, ArchiveObject, archive_path, inspect_archive

from crypto_grid_bot.backtest.funding import FundingRecord, parse_funding_rows
from crypto_grid_bot.backtest.klines import Kline, parse_rows_repaired, read_member
from crypto_grid_bot.trend.data import repaired_month


@dataclass(frozen=True, slots=True)
class DecodedMonth:
    kind: str
    symbol: str
    month: str
    status: str
    hourly: tuple[Kline, ...] = ()
    daily: tuple[Kline, ...] = ()
    funding: tuple[FundingRecord, ...] = ()
    masked_hours: frozenset[int] = frozenset()
    # Full-size hold ignores monthly exclusions, but never individual hour masks.
    hold_hourly: tuple[Kline, ...] = ()


def decode_inventory_archive(entry: Mapping[str, object], content: bytes | None) -> DecodedMonth:
    """Recheck one pinned entry and expose eligible strategy records.

    Separate hold_hourly spot prices also retain unmasked rows in a month
    excluded by completeness. They must never replace strategy hourly/daily bars.

    The complete inventory, cross-market exclusions, coverage, registration and
    code identity still require validation by the enclosing historical adapter.
    Input bytes must already have been obtained through an authorized data task.
    This helper never opens a supplied path, fetches data or launches a replay.
    """
    kind, symbol, month = entry.get("kind"), entry.get("symbol"), entry.get("month")
    if not isinstance(kind, str) or not isinstance(symbol, str) or not isinstance(month, str):
        raise ValueError("invalid inventory identity")
    path = archive_path(kind, symbol, month)  # reject reserved dates before decoding
    if "local_path" in entry and entry["local_path"] != "archives/" + path.lstrip("/"):
        raise ValueError("noncanonical local inventory path")
    archive = None
    if content is not None:
        digest = entry.get("sha256")
        if not isinstance(content, bytes) or not isinstance(digest, str):
            raise ValueError("present archive requires bytes and content hash")
        archive = ArchiveObject(path, digest, content)
    checked = inspect_archive(archive, kind, symbol, month)
    if checked != {key: value for key, value in entry.items() if key != "local_path"}:
        raise ValueError("inventory diagnostics differ from pinned bytes")
    status = str(checked["status"])
    hold_only = kind == "spot" and status == "excluded" and "masked_hours" in checked
    if status != "eligible" and not hold_only:
        return DecodedMonth(kind, symbol, month, status)
    if content is None:
        raise ValueError("eligible archive bytes missing")
    member = f"{symbol}-{'fundingRate' if kind == 'funding' else '1h'}-{month}.csv"
    with TemporaryDirectory(prefix="v3-decode-") as directory:
        local = Path(directory) / "archive.zip"
        local.write_bytes(content)
        text = read_member(local, member)
    if kind == "funding":
        return DecodedMonth(
            kind, symbol, month, status, funding=tuple(parse_funding_rows(text, month))
        )
    if kind == "futures" and text.partition("\n")[0].rstrip("\r") == KLINE_HEADER:
        text = text.partition("\n")[2]
    read = parse_rows_repaired(text, "1h", month)
    checked_month = repaired_month(read, month)
    unmasked = tuple(bar for bar in read.bars if bar.open_ms not in checked_month.masked_hours)
    return DecodedMonth(
        kind,
        symbol,
        month,
        status,
        hourly=() if hold_only else unmasked,
        daily=checked_month.daily_bars,
        masked_hours=checked_month.masked_hours,
        hold_hourly=unmasked if kind == "spot" else (),
    )
