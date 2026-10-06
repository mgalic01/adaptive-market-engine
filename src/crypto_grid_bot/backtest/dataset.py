"""Dataset specs, checksummed Binance archive downloads and reproducibility manifests.

Only ``https://data.binance.vision/data/spot/monthly/klines/...`` and the USDT-M monthly
funding archives (``.../futures/um/monthly/fundingRate/...``) are read. Every zip is
verified against Binance's published SHA-256 before it is stored, and the manifest
records what was used so a replay can prove it ran on identical inputs. A month
that Binance does not publish (for example before listing) is recorded as missing;
nothing is invented to fill it. A 1m or 1h archive that is published and verified but
that the strict parser rejects is read by the repairing reader (spec v1 section 5 rule 1):
a fetch records it as ok when that can read it, and as unreadable, with the reason,
when not.
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
from typing import Any, cast

from crypto_grid_bot.backtest.funding import read_funding_archive
from crypto_grid_bot.backtest.klines import (
    INTERVAL_MS,
    UNDECODABLE,
    month_bounds_ms,
    read_archive,
    read_archive_repaired,
)
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.client import FeedError, PublicClient, https_connection
from crypto_grid_bot.market_data.parsing import DataError, amount, parse_instrument, symbol_name

ARCHIVE_HOST = "data.binance.vision"
MAX_ZIP_BYTES = 64 * 1024 * 1024
MANIFEST_SCHEMA = 1
_CHECKSUM = re.compile(
    r"([0-9a-f]{64})  ([A-Z0-9]{2,24}-(?:1m|1h|1d|fundingRate)-\d{4}-\d{2}\.zip)\n?"
)

Fetcher = Callable[[str], bytes | None]
InstrumentSource = Callable[[str], dict[str, str]]


class ArchiveParseError(DataError):
    """A hash-verified archive failed parsing; download/integrity failures are distinct."""


@dataclass(frozen=True)
class BasketExclusion:
    """A documented absence of a breadth-basket symbol's hourly data (for example before
    its listing): hours in [start_ms, end_ms) may be missing without failing verify."""

    symbol: str
    start_ms: int
    end_ms: int
    reason: str


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
    # Optional daily history for daily-bar signals (spec v1 P3); None means no 1d files.
    daily_warmup_start: str | None = None
    basket_exclusions: tuple[BasketExclusion, ...] = ()

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
        if self.daily_warmup_start:
            daily = sorted({*self.traded, self.market_proxy})
            files += [(s, "1d", m) for s in daily for m in self.months(self.daily_warmup_start)]
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


_HOUR = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:00Z")


def _hour_ms(raw: object, name: str) -> int:
    if type(raw) is not str or not _HOUR.fullmatch(raw):
        raise DataError(f"{name} must be an hour as YYYY-MM-DDTHH:00Z")
    try:
        moment = datetime.strptime(raw, "%Y-%m-%dT%H:%MZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise DataError(f"{name} must be an hour as YYYY-MM-DDTHH:00Z") from exc
    return int(moment.timestamp() * 1000)


def _basket_exclusions(
    raw: object, basket: tuple[str, ...], covered: set[str]
) -> tuple[BasketExclusion, ...]:
    """Parse ``[[basket_exclusions]]``: symbol, from (inclusive), to (exclusive), reason."""
    if type(raw) is not list:
        raise DataError("basket_exclusions must be a list of tables")
    exclusions: list[BasketExclusion] = []
    for entry in raw:
        if type(entry) is not dict or set(entry) != {"symbol", "from", "to", "reason"}:
            raise DataError("each basket exclusion needs exactly symbol, from, to and reason")
        symbol = symbol_name(entry["symbol"]) if type(entry["symbol"]) is str else ""
        if symbol not in basket or symbol in covered:
            raise DataError("a basket exclusion must name an untraded, non-proxy basket symbol")
        start, end = _hour_ms(entry["from"], "from"), _hour_ms(entry["to"], "to")
        reason = entry["reason"]
        if start >= end or type(reason) is not str or not reason.strip():
            raise DataError("a basket exclusion needs from < to and a non-empty reason")
        exclusions.append(BasketExclusion(symbol, start, end, reason))
    for a in exclusions:
        for b in exclusions:
            overlap = a.start_ms < b.end_ms and b.start_ms < a.end_ms
            if a is not b and a.symbol == b.symbol and overlap:
                raise DataError("basket exclusions for one symbol must not overlap")
    return tuple(exclusions)


def load_spec(path: Path) -> DatasetSpec:
    with path.open("rb") as source:
        try:
            raw = tomllib.load(source)
        except tomllib.TOMLDecodeError as exc:
            raise DataError(f"invalid dataset TOML: {exc}") from exc
    daily_start = raw.pop("daily_warmup_start", None)
    raw_exclusions = raw.pop("basket_exclusions", [])
    if set(raw) != set(_SPEC_FIELDS):
        raise DataError("dataset spec contains missing or unknown fields")
    for key, expected in _SPEC_FIELDS.items():
        if type(raw[key]) is not expected:
            raise DataError(f"dataset field {key} has an invalid type")
    if daily_start is not None:
        if type(daily_start) is not str:
            raise DataError("dataset field daily_warmup_start has an invalid type")
        development_month(daily_start)
        if not daily_start <= raw["warmup_start"]:
            raise DataError("daily_warmup_start must not be after warmup_start")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", raw["name"]):
        raise DataError("dataset name must be lowercase letters, digits and hyphens")
    traded = tuple(symbol_name(s) for s in raw["traded"])
    basket = tuple(symbol_name(s) for s in raw["breadth_basket"])
    if not traded or len(set(traded)) != len(traded) or len(set(basket)) != len(basket):
        raise DataError("traded and basket symbols must be non-empty and distinct")
    for month in (raw["warmup_start"], raw["start"], raw["end"]):
        # development_month validates the YYYY-MM form and refuses the reserved window,
        # so a spec reaching 2025-01 or later is rejected here rather than downloaded.
        development_month(month)
    if not raw["warmup_start"] < raw["start"] <= raw["end"]:
        raise DataError("months must satisfy warmup_start < start <= end")
    proxy = symbol_name(raw["market_proxy"])
    exclusions = _basket_exclusions(raw_exclusions, basket, {*traded, proxy})
    return DatasetSpec(
        name=raw["name"],
        purpose=raw["purpose"],
        traded=traded,
        market_proxy=proxy,
        breadth_basket=basket,
        warmup_start=raw["warmup_start"],
        start=raw["start"],
        end=raw["end"],
        initial_quote=_positive(raw["initial_quote"], "initial_quote"),
        fee_rate=fee_rate(raw["fee_rate"], "fee_rate"),
        slippage_rate=_positive(raw["slippage_rate"], "slippage_rate", below=Decimal("0.1")),
        participation=_positive(raw["participation"], "participation", below=Decimal("1.01")),
        assumed_spread_pct=_positive(raw["assumed_spread_pct"], "assumed_spread_pct"),
        daily_warmup_start=daily_start,
        basket_exclusions=exclusions,
    )


def archive_path(symbol: str, interval: str, month: str) -> str:
    symbol_name(symbol)
    if interval not in INTERVAL_MS:
        raise DataError("unsupported kline interval")
    month_bounds_ms(month)
    return f"/data/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{month}.zip"


def local_path(data_dir: Path, symbol: str, interval: str, month: str) -> Path:
    return data_dir / "binance" / archive_path(symbol, interval, month).lstrip("/")


_MONTH_NAME = re.compile(r"\d{4}-\d{2}")


def funding_archive_path(symbol: str, month: str) -> str:
    """The USDT-M perpetual's monthly funding-rate archive (spec v1 P8, signal G)."""
    symbol_name(symbol)
    if _MONTH_NAME.fullmatch(month) is None:  # an unpadded month is not an archive name
        raise DataError(f"month must be YYYY-MM: {month}")
    month_bounds_ms(month)
    return f"/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip"


def funding_local_path(data_dir: Path, symbol: str, month: str) -> Path:
    return data_dir / "binance" / funding_archive_path(symbol, month).lstrip("/")


# A manifest entry for a funding archive carries this ``kind`` and no ``interval``; a kline
# entry carries no ``kind``.
FUNDING_KIND = "fundingRate"


def is_funding(entry: dict[str, Any]) -> bool:
    """Whether a manifest file entry is a funding archive's, not a kline archive's."""
    return entry.get("kind") == FUNDING_KIND


# The whole object path, not a suffix: an end-anchored month search accepts a reserved
# path carrying a development-looking query ("...-2025-01.zip?x=-2024-12.zip"). The
# back-references also force the file name to agree with its directories.
_ARCHIVE_PATH = re.compile(
    r"^/data/spot/monthly/klines/([A-Z0-9]{2,24})/(1m|1h|1d)/"
    r"\1-\2-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?$"
)
_FUNDING_PATH = re.compile(
    r"^/data/futures/um/monthly/fundingRate/([A-Z0-9]{2,24})/"
    r"\1-fundingRate-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?$"
)


def _archive_month(path: str) -> str:
    """The month of a canonical archive (or checksum) path; anything else is refused."""
    kline = _ARCHIVE_PATH.fullmatch(path)
    if kline is not None:
        return kline.group(3)
    funding = _FUNDING_PATH.fullmatch(path)
    if funding is not None:
        return funding.group(2)
    raise DataError(f"not a monthly spot kline archive or USDT-M funding archive path: {path}")


def archive_get(path: str) -> bytes | None:
    """GET one archive object from the fixed host; None only for HTTP 404.

    The whole path must match the canonical monthly spot kline or USDT-M funding archive
    (or checksum) shape, and its month must be in the development window. This is the
    lowest network call, so the window is enforced here and not only in ``fetch_file``
    and ``fetch_funding_file``. Any status other than 200 and 404 is an error: a
    redirect is never followed.
    """
    development_month(_archive_month(path))
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


def _fetch_verified(path: str, target: Path, fetcher: Fetcher) -> str | None:
    """Store the archive at ``path`` in ``target`` under Binance's published checksum.

    Returns the published SHA-256, or None when the archive is not published at all. A
    cached file is kept only while it matches the checksum. Every failure is a
    ``DataError``; the archive's content is not opened here.
    """
    checksum = fetcher(path + ".CHECKSUM")
    if checksum is None:
        if fetcher(path) is not None:
            raise DataError(f"{path} is published without a checksum")
        return None
    try:
        published = checksum.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        # A non-ASCII checksum body is a corrupt or hostile response, not a decode bug:
        # it must fail at this module's DataError boundary like every other bad checksum.
        raise DataError(f"unexpected checksum file for {path}") from exc
    match = _CHECKSUM.fullmatch(published)
    if match is None or match.group(2) != path.rsplit("/", 1)[1]:
        raise DataError(f"unexpected checksum file for {path}")
    expected = match.group(1)
    if not target.exists() or sha256_file(target) != expected:
        body = fetcher(path)
        if body is None:
            raise DataError(f"{path} has a checksum but no archive")
        if hashlib.sha256(body).hexdigest() != expected:
            raise DataError(f"{path} does not match Binance's published SHA-256")
        _write_atomic(target, body)
    return expected


def _kline_entry(symbol: str, interval: str, month: str) -> dict[str, Any]:
    """The identity every manifest entry of a kline archive starts with."""
    return {
        "symbol": symbol,
        "interval": interval,
        "month": month,
        "url": f"https://{ARCHIVE_HOST}{archive_path(symbol, interval, month)}",
    }


def _stored_kline(
    data_dir: Path, symbol: str, interval: str, month: str, fetcher: Fetcher
) -> tuple[dict[str, Any], Path, str | None]:
    """A kline archive's entry identity, its local path and its published SHA-256, once
    ``_fetch_verified`` has stored it (None when Binance does not publish it)."""
    development_month(month)  # refuse the reserved window before any network or cache access
    path = archive_path(symbol, interval, month)
    entry = _kline_entry(symbol, interval, month)
    target = local_path(data_dir, symbol, interval, month)
    return entry, target, _fetch_verified(path, target, fetcher)


def _strict_entry(
    entry: dict[str, Any], target: Path, expected: str, symbol: str, interval: str, month: str
) -> dict[str, Any]:
    """The ok entry of a stored, verified archive that ``read_archive`` parses."""
    try:
        _, stats = read_archive(target, symbol, interval, month)
    except DataError as exc:
        # Only this boundary is safe for an audit to inspect as unparsed content.
        # Checksum, missing-body and hash failures before it must never reach that path.
        raise ArchiveParseError(str(exc)) from exc
    return {
        **entry,
        "status": "ok",
        "sha256": expected,
        "bytes": target.stat().st_size,
        **asdict(stats),
    }


def fetch_file(
    data_dir: Path, symbol: str, interval: str, month: str, fetcher: Fetcher
) -> dict[str, Any]:
    entry, target, expected = _stored_kline(data_dir, symbol, interval, month, fetcher)
    if expected is None:
        return {**entry, "status": "missing"}
    return _strict_entry(entry, target, expected, symbol, interval, month)


# What the strict parse of a stored, verified archive can end in: ``_strict_entry`` converts
# a DataError into ``ArchiveParseError`` and lets ``read_member``'s decoding failures through.
# A FeedError is a RuntimeError too, which is why only the parse is ever caught with these.
_UNPARSED = (ArchiveParseError, *UNDECODABLE)


def _fetch_kline(
    data_dir: Path, symbol: str, interval: str, month: str, fetcher: Fetcher
) -> dict[str, Any]:
    """``fetch_file``, with spec v1 section 5 rule 1's reader for what its strict parse refuses.

    A 1m or 1h archive that is stored and verified against Binance's checksum but fails the
    strict parse is read by ``read_archive_repaired``. The manifest then records it as ok,
    with the repaired read's stats, or as unreadable, with its checksum, size and the
    reason. The entry of an archive that parses strictly is ``fetch_file``'s, unchanged.
    The fallback is here and not in ``fetch_file``, which the audit relies on to raise. A
    daily bar is never masked, so a daily archive that fails its parse stays fatal; so does
    any failure to download or verify one, which happens before the parse is tried.
    """
    entry, target, expected = _stored_kline(data_dir, symbol, interval, month, fetcher)
    if expected is None:
        return {**entry, "status": "missing"}
    try:
        return _strict_entry(entry, target, expected, symbol, interval, month)
    except _UNPARSED:
        if interval not in ("1m", "1h"):
            raise
    stored = {"sha256": expected, "bytes": target.stat().st_size}
    read = read_archive_repaired(target, symbol, interval, month)
    if read.unreadable:
        return {**entry, "status": "unreadable", **stored, "reason": read.unreadable}
    return {**entry, "status": "ok", **stored, **asdict(read.stats)}


def fetch_funding_file(data_dir: Path, symbol: str, month: str, fetcher: Fetcher) -> dict[str, Any]:
    """``fetch_file`` for one monthly funding-rate archive of a USDT-M perpetual.

    Same host, checksum rule, atomic write and cache rule; the stored archive is then
    parsed by ``read_funding_archive``, whose rejection is an ``ArchiveParseError``.
    """
    development_month(month)  # refuse the reserved window before any network or cache access
    path = funding_archive_path(symbol, month)
    entry: dict[str, Any] = {
        "kind": FUNDING_KIND,
        "symbol": symbol,
        "month": month,
        "url": f"https://{ARCHIVE_HOST}{path}",
    }
    target = funding_local_path(data_dir, symbol, month)
    expected = _fetch_verified(path, target, fetcher)
    if expected is None:
        return {**entry, "status": "missing"}
    try:
        records = read_funding_archive(target, symbol, month)
    except DataError as exc:
        raise ArchiveParseError(str(exc)) from exc
    return {
        **entry,
        "status": "ok",
        "sha256": expected,
        "bytes": target.stat().st_size,
        "records": len(records),
    }


def fetch_dataset(
    spec: DatasetSpec,
    data_dir: Path,
    *,
    fetcher: Fetcher = archive_get,
    instruments: InstrumentSource = exchange_filters,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The manifest of the spec's klines, each fetched and verified. ``previous`` is the
    manifest being refreshed, if any: the funding archives it lists (spec v1 P8, variant
    G), which the spec does not name, are fetched and verified again and kept after the
    klines, so a re-fetch never drops them."""
    files = [_fetch_kline(data_dir, s, i, m, fetcher) for s, i, m in spec.required()]
    kept = [entry for entry in previous["files"] if is_funding(entry)] if previous else []
    files += [fetch_funding_file(data_dir, f["symbol"], f["month"], fetcher) for f in kept]
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
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise DataError("invalid dataset manifest JSON") from exc
    _validate_manifest(manifest)
    return cast(dict[str, Any], manifest)


def _validate_manifest(manifest: Any) -> None:
    """Validate the fields consumed during verification before indexing them."""
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise DataError("unsupported dataset manifest")
    if not isinstance(manifest.get("dataset"), str):
        raise DataError("dataset manifest has an invalid dataset name")
    instruments = manifest.get("instruments")
    files = manifest.get("files")
    if not isinstance(instruments, dict) or not isinstance(files, list):
        raise DataError("dataset manifest has an invalid layout")
    # The replay reads these filters as Decimals (replay.rules_for), so a missing or
    # malformed one must fail here as DataError, not later as KeyError/InvalidOperation.
    for symbol, filters in instruments.items():
        if not isinstance(filters, dict):
            raise DataError("dataset manifest has an invalid instrument entry")
        try:
            symbol_name(symbol)
            for field in ("tick_size", "quantity_step", "min_notional"):
                amount(filters.get(field))
        except DataError as exc:
            raise DataError(
                f"dataset manifest has invalid exchange filters for {symbol!r}"
            ) from exc
    for entry in files:
        if not isinstance(entry, dict):
            raise DataError("dataset manifest has an invalid file entry")
        # A funding archive's entry (spec v1 P8, variant G) has a kind and no interval.
        funding = is_funding(entry)
        if "kind" in entry and not funding:
            raise DataError("dataset manifest file kind is invalid")
        try:
            symbol = entry["symbol"]
            interval = FUNDING_KIND if funding else entry["interval"]
            month = entry["month"]
            status = entry["status"]
        except KeyError as exc:
            raise DataError("dataset manifest file entry is incomplete") from exc
        if not all(isinstance(value, str) for value in (symbol, interval, month)):
            raise DataError("dataset manifest file identity is invalid")
        try:
            if funding:
                funding_archive_path(symbol, month)
            else:
                archive_path(symbol, interval, month)
        except (ValueError, OverflowError) as exc:
            raise DataError("dataset manifest file identity is invalid") from exc
        # The replay loaders read every file a manifest lists, so a hand-edited manifest
        # would otherwise bypass load_spec's window check. Refuse it here too.
        development_month(month)
        if status not in ("ok", "missing", "unreadable"):
            raise DataError("dataset manifest file status is invalid")
        if status in ("ok", "unreadable") and (
            not isinstance(entry.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
        ):
            raise DataError("dataset manifest file checksum is invalid")
        if status == "unreadable":
            # Spec v1 section 5 rule 1: only a 1m or 1h kline archive can be left unreadable;
            # a fetch fails on a daily or a funding archive that does not parse.
            if interval not in ("1m", "1h"):
                raise DataError("dataset manifest lists an unreadable archive that is not 1m or 1h")
            reason = entry.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise DataError("dataset manifest unreadable entry needs a reason")


def verify_dataset(spec: DatasetSpec, manifest: dict[str, Any], data_dir: Path) -> None:
    """Fail unless the manifest's klines cover exactly the spec and every local file
    matches it. Funding archives are optional: each may be listed once, and one listed
    is verified like a kline archive. An unreadable archive is checked against its SHA-256
    like an ok one: the loaders give no bars for it, so its hours are absent, then masked
    (spec v1 section 5 rule 1, "The reader")."""
    _validate_manifest(manifest)
    if manifest["dataset"] != spec.name:
        raise DataError("manifest belongs to a different dataset")
    klines = [f for f in manifest["files"] if not is_funding(f)]
    listed = [(f["symbol"], f["interval"], f["month"]) for f in klines]
    if sorted(listed) != sorted(spec.required()) or len(set(listed)) != len(listed):
        raise DataError("manifest files do not match the dataset spec")
    funding = [(f["symbol"], f["month"]) for f in manifest["files"] if is_funding(f)]
    if len(set(funding)) != len(funding):
        raise DataError("manifest lists a funding archive twice")
    for symbol in spec.traded:
        if symbol not in manifest["instruments"]:
            raise DataError(f"manifest lacks exchange filters for {symbol}")
    for entry in manifest["files"]:
        if entry["status"] == "missing":
            continue
        path = (
            funding_local_path(data_dir, entry["symbol"], entry["month"])
            if is_funding(entry)
            else local_path(data_dir, entry["symbol"], entry["interval"], entry["month"])
        )
        if not path.exists():
            raise DataError(f"missing local archive {path}; run fetch first")
        if sha256_file(path) != entry["sha256"]:
            raise DataError(f"local archive {path} does not match the manifest checksum")
