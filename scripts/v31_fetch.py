"""Checksum-verified archive fetch for the V3.1 prepare job, the only job that uses the network.

``entries_for`` picks manifest entries; ``fetch_entries`` hands back each one's archive bytes,
read from a local cache or downloaded, only after they match the SHA-256 the entry pins. The
manifests are the authority: no ``.CHECKSUM`` file is requested, nothing is decoded here, and
a month at or after the reserved boundary is refused before any request, cache read or write.

The transport is anything with ``archive(path) -> bytes | None``: ``fetch_v3_data.V3Transport``
for the inventory's paths, ``LegacyTransport`` for the legacy monthly spot kline archives
(1m included). Both reach one fixed host; the host is never taken from a manifest.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import time
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Protocol

from crypto_grid_bot.backtest.dataset import archive_get
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.combined.baseline_records import refuse_sealed
from crypto_grid_bot.market_data.client import FeedError

ARCHIVE_PREFIX = "https://data.binance.vision"
# The kind ``entries_for`` gives a legacy funding file, which has no interval.
LEGACY_FUNDING_KIND = "fundingRate"
# A transport failure is tried this many times in all, as fetch_full_range.Requests does.
ATTEMPTS = 4
_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_SHA256 = re.compile(r"[0-9a-f]{64}")
# Under /data, segments that start with a letter or digit (so no "." or ".."), and a name
# that ends in the archive's month. The month is group 1.
_ARCHIVE_PATH = re.compile(r"/data(?:/[A-Za-z0-9][A-Za-z0-9._-]*)+-([0-9]{4}-[0-9]{2})\.zip")
_HTTP_STATUS = re.compile(r"\bHTTP ([0-9]{3})\b")


class ArchiveTransport(Protocol):
    def archive(self, path: str) -> bytes | None: ...


class LegacyTransport:
    """``archive(path)`` over ``backtest.dataset.archive_get``: the legacy monthly spot kline
    archives. Its path guard, development window, fixed host and size limit are
    ``archive_get``'s own; a transport failure is a ``FeedError``."""

    def archive(self, path: str) -> bytes | None:
        return archive_get(path)


@dataclass(frozen=True, slots=True)
class _Planned:
    entry: Mapping[str, object]
    label: str
    path: str
    sha256: str


def entries_for(
    manifest: Mapping[str, object],
    *,
    symbols: Collection[str],
    kinds: Collection[str],
    start_month: str,
    end_month: str,
) -> list[dict[str, object]]:
    """Copies of the manifest entries for ``symbols`` and ``kinds`` whose month lies in
    ``start_month``..``end_month`` (inclusive), sorted by (symbol, kind or interval, month).

    An inventory manifest (``entries``) is matched on each entry's ``kind``; a legacy one
    (``files``) on its ``interval``. A legacy file with no interval is selected only as kind
    ``"fundingRate"``, and only when its ``url`` holds ``/fundingRate/`` (a monthly funding
    archive); any other legacy file with no interval is never selected. Every match comes
    back, ``missing`` ones included: filtering them is the caller's choice. An ``end_month``
    (or ``start_month``) at or after 2025-01 is refused.
    """
    if isinstance(symbols, str) or isinstance(kinds, str):
        raise ValueError("symbols and kinds must be collections of names, not one string")
    start = _month(start_month, "start_month")
    end = _month(end_month, "end_month")
    listed, field = _manifest_entries(manifest)
    chosen: list[tuple[tuple[str, str, str], dict[str, object]]] = []
    for entry in listed:
        symbol, kind, month = entry.get("symbol"), entry.get(field), entry.get("month")
        if field == "interval" and "interval" not in entry and _legacy_funding(entry):
            kind = LEGACY_FUNDING_KIND
        if (
            isinstance(symbol, str)
            and isinstance(kind, str)
            and isinstance(month, str)
            and symbol in symbols
            and kind in kinds
            and start <= month <= end
        ):
            chosen.append(((symbol, kind, month), dict(entry)))
    chosen.sort(key=lambda pair: pair[0])
    return [entry for _, entry in chosen]


def fetch_entries(
    entries: Sequence[Mapping[str, object]],
    cache_dir: Path,
    *,
    transport: ArchiveTransport,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda line: print(line, flush=True),
) -> Iterator[tuple[Mapping[str, object], bytes]]:
    """Yield each entry with archive bytes whose SHA-256 is the entry's, one entry at a time.

    Before the first request every entry is planned: a month at or after 2025-01 (the
    entry's or its path's), a legacy ``url`` off ``https://data.binance.vision``, a path
    outside ``/data`` and an entry with no ``sha256`` raise a ``ValueError`` naming it, with
    the transport untouched. Only the paths so planned are ever requested.

    The cache holds ``cache_dir / <path without its leading slash>``. A cached file is used
    only if it hashes to the entry's SHA-256; otherwise the archive is fetched again and the
    verified bytes replace it atomically (a temp file beside it, then ``os.replace``). Bytes
    from the host that do not match raise a ``ValueError`` naming the path and both hashes
    before the entry is yielded; nothing is written and no file is deleted.

    A transport failure (see ``_transport_failure``) is tried ``ATTEMPTS`` times in all with
    exponential backoff (``sleep``), each failure logged. A mismatch, a 404 (the entry says
    the archive exists), a size-limit or path-guard refusal and any other HTTP status are
    never retried. Retried bytes are verified like any other.
    """
    plans = [_plan(entry) for entry in entries]
    for plan in plans:
        target = cache_dir.joinpath(*plan.path.strip("/").split("/"))
        if target.is_file():
            cached = target.read_bytes()
            if hashlib.sha256(cached).hexdigest() == plan.sha256:
                yield plan.entry, cached
                continue
            log(f"CACHE {plan.path}: the cached file does not match the manifest; fetching again")
        content = _download(plan, transport, sleep, log)
        if content is None:
            raise ValueError(
                f"{plan.label}: the manifest lists this archive but the host has none (HTTP 404)"
            )
        if type(content) is not bytes:
            raise ValueError(f"{plan.label}: the transport returned something other than bytes")
        digest = hashlib.sha256(content).hexdigest()
        if digest != plan.sha256:
            raise ValueError(
                f"{plan.label}: the host's bytes do not match the pinned sha256: "
                f"expected {plan.sha256}, got {digest}"
            )
        _store(target, content)
        yield plan.entry, content


def _month(value: object, label: str) -> str:
    """``value`` if it is a canonical ``YYYY-MM`` before the reserved boundary (2025-01)."""
    if not isinstance(value, str) or _MONTH.fullmatch(value) is None:
        raise ValueError(f"{label}: month must be YYYY-MM")
    refuse_sealed([month_bounds_ms(value)[0]], label)
    return value


def _manifest_entries(manifest: Mapping[str, object]) -> tuple[list[Mapping[str, object]], str]:
    """The manifest's entries and the field that names their kind."""
    inventory, legacy = manifest.get("entries"), manifest.get("files")
    if (inventory is None) == (legacy is None):
        raise ValueError("a manifest has exactly one of entries (inventory) or files (legacy)")
    listed, field = (inventory, "kind") if inventory is not None else (legacy, "interval")
    if not isinstance(listed, list) or not all(isinstance(entry, Mapping) for entry in listed):
        raise ValueError("the manifest's entries must be a list of objects")
    return listed, field


def _legacy_funding(entry: Mapping[str, object]) -> bool:
    """Whether a legacy file is a monthly funding archive: its url holds ``/fundingRate/``."""
    url = entry.get("url")
    return isinstance(url, str) and "/fundingRate/" in url


def _label(entry: Mapping[str, object]) -> str:
    """How refusals name ``entry``: its archive path or URL, else its symbol and month."""
    for key in ("path", "url"):
        name = entry.get(key)
        if isinstance(name, str):
            return name
    return f"{entry.get('symbol')} {entry.get('month')}"


def _plan(entry: Mapping[str, object]) -> _Planned:
    """The path to request for ``entry`` and the hash to expect; every refusal names it."""
    label = _label(entry)
    month = _month(entry.get("month"), label)
    if entry.get("status") == "missing":
        raise ValueError(f"{label}: a missing month has no archive to fetch")
    digest = entry.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError(f"{label}: sha256 must be 64 lowercase hex digits")
    path, url = entry.get("path"), entry.get("url")
    if (path is None) == (url is None):
        raise ValueError(f"{label}: an entry names exactly one of path and url")
    if url is not None:
        # Exactly the prefix and a slash: no other scheme, host, port or userinfo gets through.
        if not isinstance(url, str) or not url.startswith(ARCHIVE_PREFIX + "/"):
            raise ValueError(f"{label}: a url must start with {ARCHIVE_PREFIX}/")
        path = url[len(ARCHIVE_PREFIX) :]
    match = _ARCHIVE_PATH.fullmatch(path) if isinstance(path, str) else None
    if match is None:
        raise ValueError(f"{label}: not a zip archive path under /data")
    path_month = _month(match.group(1), label)
    if path_month != month:
        raise ValueError(f"{label}: the path is for {path_month} but the entry says {month}")
    return _Planned(entry, label, match.group(0), digest)


def _download(
    plan: _Planned,
    transport: ArchiveTransport,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> bytes | None:
    """One archive from ``transport``, trying a transport failure ``ATTEMPTS`` times in all."""
    attempt = 1
    while True:
        try:
            return transport.archive(plan.path)
        except (FeedError, ValueError) as exc:
            if not _transport_failure(exc):
                raise
            log(f"RETRY attempt {attempt} of {ATTEMPTS} for {plan.path}: {exc}")
            if attempt == ATTEMPTS:
                raise
            sleep(1 << (attempt - 1))
            attempt += 1


def _transport_failure(error: Exception) -> bool:
    """Whether ``error`` is worth another attempt: a connection error, a timeout or an HTTP
    5xx. ``V3Transport`` reports these as a ValueError caused by an OSError or HTTPException
    (or naming the 5xx status); ``archive_get`` as a FeedError. Any other HTTP status, a size
    limit and a path or window guard are refusals, and a retry cannot change them."""
    status = _HTTP_STATUS.search(str(error))
    if status is not None:
        return status.group(1).startswith("5")
    if isinstance(error, FeedError):
        return "size limit" not in str(error)
    return isinstance(error.__cause__, OSError | HTTPException)


def _store(target: Path, content: bytes) -> None:
    """Write ``content`` to ``target`` atomically: a temp file in the same directory first."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
