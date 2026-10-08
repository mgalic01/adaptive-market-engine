"""V3 archive preparation helpers for a separately reviewed owner-started Bob task.

No CLI dispatch yet. Retrieval is injected so tests cannot fetch real market data.
The legacy spot/funding downloader and its URL boundary remain unchanged.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass

from crypto_grid_bot.backtest.window import development_month

SYMBOLS = frozenset(
    {
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "ADAUSDT",
        "DOGEUSDT",
        "LTCUSDT",
        "LINKUSDT",
        "TRXUSDT",
    }
)
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
Fetcher = Callable[[str], bytes | None]


@dataclass(frozen=True, slots=True)
class ArchiveObject:
    path: str
    sha256: str
    content: bytes


def archive_path(kind: str, symbol: str, month: str) -> str:
    """Only the frozen universe and canonical development-month archive names."""
    if symbol not in SYMBOLS or re.fullmatch(r"[0-9]{4}-[0-9]{2}", month) is None:
        raise ValueError("invalid symbol or canonical month")
    development_month(month)
    if kind == "funding":
        return f"/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"
    if kind not in {"spot", "futures"}:
        raise ValueError("invalid archive kind")
    market = "spot" if kind == "spot" else "futures/um"
    return f"/data/{market}/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip"


def fetch_verified_archive(
    kind: str, symbol: str, month: str, fetch: Fetcher
) -> ArchiveObject | None:
    """Absent archive is None; missing/invalid checksum is an error, never eligibility."""
    path = archive_path(kind, symbol, month)
    content = fetch(path)
    if content is None:
        return None
    if not isinstance(content, bytes) or len(content) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive exceeds byte limit or transport returned wrong type")
    checksum = fetch(path + ".CHECKSUM")
    if not isinstance(checksum, bytes) or len(checksum) > 1024:
        raise ValueError("missing or oversized checksum")
    try:
        text = checksum.decode("ascii").strip()
    except UnicodeError as exc:
        raise ValueError("checksum must be ASCII") from exc
    match = re.fullmatch(r"([0-9a-fA-F]{64})[ \t]+\*?([^\s]+)", text)
    if match is None or match.group(2) != path.rsplit("/", 1)[1]:
        raise ValueError("checksum filename or format does not match requested archive")
    digest = hashlib.sha256(content).hexdigest()
    if match.group(1).lower() != digest:
        raise ValueError("archive checksum mismatch")
    return ArchiveObject(path, digest, content)
