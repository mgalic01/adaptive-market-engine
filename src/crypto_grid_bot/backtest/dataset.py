"""Dataset specs, checksummed Binance archive downloads and reproducibility manifests.

Only ``https://data.binance.vision/data/spot/monthly/klines/...`` is read. Every zip is
verified against Binance's published SHA-256 before it is stored, and the manifest
records what was used so a replay can prove it ran on identical inputs. A month
that Binance does not publish (for example before listing) is recorded as missing;
nothing is invented to fill it.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.klines import INTERVAL_MS, month_bounds_ms, read_archive
from crypto_grid_bot.market_data.client import FeedError, PublicClient, https_connection
from crypto_grid_bot.market_data.parsing import DataError, parse_instrument, symbol_name

ARCHIVE_HOST = "data.binance.vision"
MAX_ZIP_BYTES = 64 * 1024 * 1024
MANIFEST_SCHEMA = 1
_CHECKSUM = re.compile(r"([0-9a-f]{64})  ([A-Z0-9]{2,24}-(?:1m|1h)-\d{4}-\d{2}\.zip)\n?")

Fetcher = Callable[[str], bytes | None]
InstrumentSource = Callable[[str], dict[str, str]]


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    purpose: str
    traded: tuple[str, ...]
    market_proxy: str
    breadth_basket: tuple[str, ...]
    warmup_start: str
    start: str
    end: str
    initial_quote: Decimal
    fee_rate: Decimal
    slippage_rate: Decimal
    participation: Decimal
    assumed_spread_pct: Decimal

    def months(self, first: str | None = None) -> list[str]:
        """Inclusive YYYY-MM list from ``first`` (default warm-up start) to end."""
        month, stop = first or self.warmup_start, self.end
        result: list[str] = []
        while month <= stop:
            result.append(month)
            year, number = int(month[:4]), int(month[5:])
            month = f"{year + number // 12}-{number % 12 + 1:02d}"
        return result

    def required(self) -> list[tuple[str, str, str]]:
        """Every (symbol, interval, month) the replay needs.

        1m klines drive fills inside the evaluation window only; 1h klines feed
        point-in-time signals and also cover the warm-up months.
        """
        hourly = sorted({*self.traded, self.market_proxy, *self.breadth_basket})
        files = [(s, "1m", m) for s in self.traded for m in self.months(self.start)]
        files += [(s, "1h", m) for s in hourly for m in self.months()]
        return files


_SPEC_FIELDS: dict[str, type] = {
    "name": str,
    "purpose": str,
    "traded": list,
    "market_proxy": str,
    "breadth_basket": list,
    "warmup_start": str,
    "start": str,
    "end": str,
    "initial_quote": str,
    "fee_rate": str,
    "slippage_rate": str,
    "participation": str,
    "assumed_spread_pct": str,
}


def _positive(
    raw: str, name: str, *, below: Decimal | None = None, allow_zero: bool = False
) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise DataError(f"{name} must be a decimal string") from exc
    # NaN cannot be ordered (sNaN even raises), so reject non-finite values first.
    if not value.is_finite():
        raise DataError(f"{name} is out of range")
    too_low = value < 0 if allow_zero else value <= 0
    if too_low or (below is not None and value >= below):
        raise DataError(f"{name} is out of range")
    return value


def fee_rate(raw: str, name: str) -> Decimal:
    """A fee fraction in [0, 0.1); zero is valid (e.g. a 0% maker fee)."""
    return _positive(raw, name, below=Decimal("0.1"), allow_zero=True)


def load_spec(path: Path) -> DatasetSpec:
    with path.open("rb") as source:
        try:
            raw = tomllib.load(source)
        except tomllib.TOMLDecodeError as exc:
            raise DataError(f"invalid dataset TOML: {exc}") from exc
    if set(raw) != set(_SPEC_FIELDS):
        raise DataError("dataset spec contains missing or unknown fields")
    for key, expected in _SPEC_FIELDS.items():
        if type(raw[key]) is not expected:
            raise DataError(f"dataset field {key} has an invalid type")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", raw["name"]):
        raise DataError("dataset name must be lowercase letters, digits and hyphens")
    traded = tuple(symbol_name(s) for s in raw["traded"])
    basket = tuple(symbol_name(s) for s in raw["breadth_basket"])
    if not traded or len(set(traded)) != len(traded) or len(set(basket)) != len(basket):
        raise DataError("traded and basket symbols must be non-empty and distinct")
    for month in (raw["warmup_start"], raw["start"], raw["end"]):
        month_bounds_ms(month)
    if not raw["warmup_start"] < raw["start"] <= raw["end"]:
        raise DataError("months must satisfy warmup_start < start <= end")
    return DatasetSpec(
        name=raw["name"],
        purpose=raw["purpose"],
        traded=traded,
        market_proxy=symbol_name(raw["market_proxy"]),
        breadth_basket=basket,
        warmup_start=raw["warmup_start"],
        start=raw["start"],
        end=raw["end"],
        initial_quote=_positive(raw["initial_quote"], "initial_quote"),
        fee_rate=fee_rate(raw["fee_rate"], "fee_rate"),
        slippage_rate=_positive(raw["slippage_rate"], "slippage_rate", below=Decimal("0.1")),
        participation=_positive(raw["participation"], "participation", below=Decimal("1.01")),
        assumed_spread_pct=_positive(raw["assumed_spread_pct"], "assumed_spread_pct"),
    )


def archive_path(symbol: str, interval: str, month: str) -> str:
    symbol_name(symbol)
    if interval not in INTERVAL_MS:
        raise DataError("unsupported kline interval")
    month_bounds_ms(month)
    return f"/data/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"


def local_path(data_dir: Path, symbol: str, interval: str, month: str) -> Path:
    return data_dir / "binance" / archive_path(symbol, interval, month).lstrip("/")


def archive_get(path: str) -> bytes | None:
    """GET one archive object from the fixed host; None only for HTTP 404."""
    if not path.startswith("/data/spot/monthly/klines/"):
        raise DataError("path is outside the spot kline archive")
    connection = https_connection(ARCHIVE_HOST, timeout=60)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read(MAX_ZIP_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise FeedError(f"archive transport failed for {path}") from exc
    finally:
        connection.close()
    if response.status == 404:
        return None
    if response.status != 200:
        raise FeedError(f"archive returned HTTP {response.status} for {path}")
    if len(body) > MAX_ZIP_BYTES:
        raise FeedError("archive object exceeded the size limit")
    return body


def exchange_filters(symbol: str) -> dict[str, str]:
    """Current public exchange filters; applied historically as a documented approximation."""
    instrument = parse_instrument(
        PublicClient().get("/api/v3/exchangeInfo", {"symbol": symbol}), symbol
    )
    return {
        "base": instrument.base,
        "quote": instrument.quote,
        "tick_size": str(instrument.tick_size),
        "quantity_step": str(instrument.quantity_step),
        "min_notional": str(instrument.min_notional),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".partial-")
    try:
        with os.fdopen(handle, "wb") as target:
            target.write(data)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def fetch_file(
    data_dir: Path, symbol: str, interval: str, month: str, fetcher: Fetcher
) -> dict[str, Any]:
    path = archive_path(symbol, interval, month)
    entry: dict[str, Any] = {
        "symbol": symbol,
        "interval": interval,
        "month": month,
        "url": f"https://{ARCHIVE_HOST}{path}",
    }
    checksum = fetcher(path + ".CHECKSUM")
    if checksum is None:
        if fetcher(path) is not None:
            raise DataError(f"{path} is published without a checksum")
        return {**entry, "status": "missing"}
    match = _CHECKSUM.fullmatch(checksum.decode("ascii", errors="strict"))
    if match is None or match.group(2) != path.rsplit("/", 1)[1]:
        raise DataError(f"unexpected checksum file for {path}")
    expected = match.group(1)
    target = local_path(data_dir, symbol, interval, month)
    if not target.exists() or sha256_file(target) != expected:
        body = fetcher(path)
        if body is None:
            raise DataError(f"{path} has a checksum but no archive")
        if hashlib.sha256(body).hexdigest() != expected:
            raise DataError(f"{path} does not match Binance's published SHA-256")
        _write_atomic(target, body)
    _, stats = read_archive(target, symbol, interval, month)
    return {
        **entry,
        "status": "ok",
        "sha256": expected,
        "bytes": target.stat().st_size,
        **asdict(stats),
    }


def fetch_dataset(
    spec: DatasetSpec,
    data_dir: Path,
    *,
    fetcher: Fetcher = archive_get,
    instruments: InstrumentSource = exchange_filters,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    files = [fetch_file(data_dir, s, i, m, fetcher) for s, i, m in spec.required()]
    fetched_at = now().isoformat(timespec="seconds")
    return {
        "schema": MANIFEST_SCHEMA,
        "dataset": spec.name,
        "source": f"https://{ARCHIVE_HOST}",
        "created_at": fetched_at,
        "instruments": {
            symbol: {
                **instruments(symbol),
                "fetched_at": fetched_at,
                "note": "current exchange filters applied to historical replay (approximation)",
            }
            for symbol in spec.traded
        },
        "files": files,
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    _write_atomic(path, (json.dumps(manifest, indent=1, sort_keys=True) + "\n").encode())


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise DataError("unsupported dataset manifest")
    return manifest


def verify_dataset(spec: DatasetSpec, manifest: dict[str, Any], data_dir: Path) -> None:
    """Fail unless the manifest covers exactly the spec and every local file matches it."""
    if manifest["dataset"] != spec.name:
        raise DataError("manifest belongs to a different dataset")
    listed = [(f["symbol"], f["interval"], f["month"]) for f in manifest["files"]]
    if sorted(listed) != sorted(spec.required()) or len(set(listed)) != len(listed):
        raise DataError("manifest files do not match the dataset spec")
    for symbol in spec.traded:
        if symbol not in manifest["instruments"]:
            raise DataError(f"manifest lacks exchange filters for {symbol}")
    for entry in manifest["files"]:
        if entry["status"] == "missing":
            continue
        path = local_path(data_dir, entry["symbol"], entry["interval"], entry["month"])
        if not path.exists():
            raise DataError(f"missing local archive {path}; run fetch first")
        if sha256_file(path) != entry["sha256"]:
            raise DataError(f"local archive {path} does not match the manifest checksum")
