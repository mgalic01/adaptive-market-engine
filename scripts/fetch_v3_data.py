"""V3 archive preparation helpers for a separately reviewed owner-started Bob task.

No CLI dispatch yet. Retrieval is injected so tests cannot fetch real market data.
The legacy spot/funding downloader and its URL boundary remain unchanged.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException, HTTPSConnection

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


ARCHIVE_HOST = "data.binance.vision"
FUTURES_FILTER_HOST = "fapi.binance.com"
SPOT_FILTER_HOST = "data-api.binance.vision"


def _guard_archive(path: str) -> None:
    patterns = (
        (
            r"/data/(spot|futures/um)/monthly/klines/([A-Z0-9]+)/1h/"
            r"\2-1h-([0-9]{4}-[0-9]{2})\.zip(\.CHECKSUM)?",
            False,
        ),
        (
            r"/data/(futures/um)/monthly/fundingRate/([A-Z0-9]+)/"
            r"\2-fundingRate-([0-9]{4}-[0-9]{2})\.zip(\.CHECKSUM)?",
            True,
        ),
    )
    for pattern, funding in patterns:
        match = re.fullmatch(pattern, path)
        if match:
            kind = "funding" if funding else ("spot" if match.group(1) == "spot" else "futures")
            canonical = archive_path(kind, match.group(2), match.group(3))
            if path == canonical + (match.group(4) or ""):
                return
    raise ValueError("noncanonical archive path")


class V3Transport:
    """Fixed public GET endpoints for one owner-started fetch; no credentials."""

    def __init__(self) -> None:
        self._futures_requested = False

    @staticmethod
    def _get(host: str, path: str, limit: int, missing_ok: bool = False) -> bytes | None:
        connection = HTTPSConnection(host, timeout=60)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status == 404 and missing_ok:
                return None
            if response.status != 200:
                raise ValueError(
                    f"public data returned HTTP {response.status}; redirects forbidden"
                )
            content = response.read(limit + 1)
            if len(content) > limit:
                raise ValueError("public response exceeded size limit")
            return content
        except (OSError, HTTPException) as exc:
            raise ValueError("public data transport failed") from exc
        finally:
            connection.close()

    def archive(self, path: str) -> bytes | None:
        _guard_archive(path)  # Before constructing a connection, including checksum requests.
        limit = 1024 if path.endswith(".CHECKSUM") else MAX_ARCHIVE_BYTES
        return self._get(ARCHIVE_HOST, path, limit, missing_ok=True)

    def futures_filters(self) -> bytes:
        if self._futures_requested:
            raise ValueError("futures filters may be requested only once per fetch")
        self._futures_requested = True  # Failed requests do not authorize retries.
        content = self._get(FUTURES_FILTER_HOST, "/fapi/v1/exchangeInfo", 8 * 1024 * 1024)
        if content is None:
            raise ValueError("missing futures filter snapshot")
        return content

    def spot_filters(self) -> bytes:
        content = self._get(SPOT_FILTER_HOST, "/api/v3/exchangeInfo", 8 * 1024 * 1024)
        if content is None:
            raise ValueError("missing spot filter snapshot")
        return content
