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


KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)


def inspect_archive(
    archive: ArchiveObject | None, kind: str, symbol: str, month: str
) -> dict[str, object]:
    """Build a deterministic manifest entry from verified bytes; no network access."""
    import tempfile
    import zipfile
    from pathlib import Path

    from crypto_grid_bot.backtest.funding import parse_funding_rows
    from crypto_grid_bot.backtest.klines import parse_rows_repaired, read_member
    from crypto_grid_bot.market_data.parsing import DataError
    from crypto_grid_bot.trend.data import funding_schedule, repaired_month

    path = archive_path(kind, symbol, month)
    entry: dict[str, object] = {
        "kind": kind,
        "symbol": symbol,
        "month": month,
        "path": path,
        "sha256": None,
        "status": "missing",
    }
    if archive is None:
        return entry
    if archive.path != path or hashlib.sha256(archive.content).hexdigest() != archive.sha256:
        raise ValueError("archive path or hash does not match inspected bytes")
    if len(archive.content) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive exceeds size limit")
    entry["sha256"] = archive.sha256
    member = f"{symbol}-{'fundingRate' if kind == 'funding' else '1h'}-{month}.csv"
    with tempfile.TemporaryDirectory(prefix="v3-inspect-") as folder:
        local = Path(folder) / "archive.zip"
        local.write_bytes(archive.content)
        try:
            text = read_member(local, member)
            if kind == "funding":
                records = parse_funding_rows(text, month)
                schedule = funding_schedule(records, month)
                entry.update(
                    status="eligible" if schedule.eligible else "excluded",
                    rows=len(records),
                    interval_hours=schedule.interval_hours,
                    expected_slots=schedule.expected_slots,
                    reasons=list(schedule.reasons),
                )
            else:
                header_removed = False
                if kind == "futures" and text.partition("\n")[0].rstrip("\r") == KLINE_HEADER:
                    text = text.partition("\n")[2]
                    header_removed = True
                read = parse_rows_repaired(text, "1h", month)
                checked = repaired_month(read, month)
                entry.update(
                    status="excluded" if checked.excluded else "eligible",
                    rows=read.stats.rows,
                    expected_rows=read.stats.expected_rows,
                    masked_hours=sorted(checked.masked_hours),
                    repaired_hours=sorted(read.repaired),
                    daily_bars=len(checked.daily_bars),
                    unreadable=read.unreadable,
                    header_removed=header_removed,
                )
        except (DataError, zipfile.BadZipFile) as exc:
            entry.update(status="excluded", rows=0, reasons=[str(exc)])
    return entry


def assemble_manifest(
    entries: list[dict[str, object]],
    spot_snapshot: bytes,
    futures_snapshot: bytes,
    spec_sha256: str,
) -> bytes:
    """Canonical inventory artifact; coverage/close diagnostics must precede replay readiness."""
    import json
    from dataclasses import asdict

    from crypto_grid_bot.trend.filters import parse_filter_snapshot

    if re.fullmatch(r"[0-9a-f]{64}", spec_sha256) is None:
        raise ValueError("invalid spec hash")
    seen: set[tuple[str, str, str]] = set()
    for entry in entries:
        kind, symbol, month = entry.get("kind"), entry.get("symbol"), entry.get("month")
        if not isinstance(kind, str) or not isinstance(symbol, str) or not isinstance(month, str):
            raise ValueError("invalid manifest entry identity")
        identity = (kind, symbol, month)
        if identity in seen:
            raise ValueError("duplicate manifest entry")
        seen.add(identity)
        if entry.get("path") != archive_path(kind, symbol, month):
            raise ValueError("manifest archive path mismatch")
        status = entry.get("status")
        if status not in {"eligible", "excluded", "missing"}:
            raise ValueError("invalid manifest entry status")
        digest = entry.get("sha256")
        if status == "missing":
            if digest is not None:
                raise ValueError("missing archive cannot have a content hash")
        elif not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("present archive requires SHA256")
    snapshots = {"spot": spot_snapshot, "futures": futures_snapshot}
    parsed = {
        market: {
            symbol: {key: str(value) for key, value in asdict(filters).items()}
            for symbol, filters in parse_filter_snapshot(
                raw, tuple(sorted(SYMBOLS)), futures=market == "futures"
            ).items()
        }
        for market, raw in snapshots.items()
    }
    document = {
        "schema_version": 1,
        "experiment": "v3",
        "spec_sha256": spec_sha256,
        "replay_ready": False,
        "pending": [
            "reviewed first-full-month coverage",
            "mandatory-close diagnostics",
            "committed snapshot paths and verified local file inventory",
        ],
        "entries": sorted(
            entries, key=lambda item: (str(item["symbol"]), str(item["month"]), str(item["kind"]))
        ),
        "snapshots": {
            market: {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
            for market, raw in snapshots.items()
        },
        "filters": parsed,
    }
    return (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
