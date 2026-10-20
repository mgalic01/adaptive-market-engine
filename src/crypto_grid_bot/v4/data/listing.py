"""Archive listing and discovery for the V4 data step: which symbols and months Binance holds.

Binance publishes its archive tree as the S3 bucket ``data.binance.vision``. A listing of a
prefix (``delimiter=/``) names the sub-directories under it (``CommonPrefixes``) and the files
in it (``Contents``), at most 1000 entries a page. ``list_all`` follows the pages and merges
them; ``discover_spot_usdt_symbols`` reads the spot klines directories, delisted symbols
included, and ``discover_months`` reads one symbol's archive file names for one kind.

Everything here goes through a ``Transport``, so the only network access is the one
``archives.HttpTransport`` allows: the bucket listing query, nothing else. A listing is
untrusted input: it is size-capped, parsed as UTF-8 XML without a DTD, and read for the S3
elements only. The universe step, not this module, decides what to exclude (stablecoins,
leveraged tokens), so ``discover_spot_usdt_symbols`` keeps them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import chain
from urllib.parse import quote
from xml.etree import ElementTree

from crypto_grid_bot.v4.data.archives import (
    LISTING_URL,
    MAX_LISTING_BYTES,
    Transport,
    archive_path,
)
from crypto_grid_bot.v4.data.config import DataConfig, refuse_after_end

SPOT_KLINES_PREFIX = "data/spot/monthly/klines/"

_S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
# The same shapes archives.archive_path accepts: a listed name it would refuse is no use to
# a later request, so it is not discovered.
_SYMBOL = r"[A-Z0-9]{2,30}"
_MONTH = r"[0-9]{4}-(?:0[1-9]|1[0-2])"
_PREFIX = re.compile(r"data/[A-Za-z0-9._/-]*")
_SPOT_SYMBOL_DIR = re.compile(rf"{re.escape(SPOT_KLINES_PREFIX)}({_SYMBOL})/")
_QUOTE = "USDT"
# A month used only to have archive_path spell out one kind's directory and file name.
_SAMPLE_MONTH = "2000-01"
# Never after any valid end_month, so refuse_after_end only ever objects to a bad end_month.
_FIRST_MONTH = "0000-01"


@dataclass(frozen=True)
class ListingPage:
    """The entries of one listing page, or of a whole prefix once ``list_all`` has merged it.

    ``next_marker`` is where the next page continues, or None once the listing is complete.
    """

    prefixes: tuple[str, ...]
    keys: tuple[str, ...]
    next_marker: str | None


def _entry_text(parent: ElementTree.Element, parent_name: str, child_name: str) -> str:
    """The text of ``parent``'s ``child_name`` element; an entry without it is malformed."""
    child = parent.find(_S3 + child_name)
    text = child.text if child is not None else None
    if not text:
        raise ValueError(f"the listing has a {parent_name} entry with no {child_name} text")
    return text


def _flag(text: str | None) -> bool:
    if text not in ("true", "false"):
        raise ValueError(f"the listing's IsTruncated must be true or false, got {text!r}")
    return text == "true"


def parse_listing(xml: bytes) -> ListingPage:
    """One S3 ``ListBucketResult`` page: its sub-directories, its keys and where it goes on.

    A page over ``MAX_LISTING_BYTES``, one that is not UTF-8, carries a DOCTYPE or an ENTITY
    declaration, is not well-formed XML or is not a ``ListBucketResult`` in the S3 namespace is
    refused. ``next_marker`` is set only for a truncated page: the page's ``NextMarker``, else
    (as S3's V1 listing defines it) the last entry of the page. A truncated page that gives
    neither is refused, since nothing could continue it.
    """
    if type(xml) is not bytes:
        raise ValueError("the listing must be bytes")
    if len(xml) > MAX_LISTING_BYTES:
        raise ValueError(f"the listing exceeds the size limit of {MAX_LISTING_BYTES} bytes")
    try:
        text = xml.decode("utf-8")
    except UnicodeError:
        raise ValueError("the listing must be UTF-8") from None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("the listing carries a DOCTYPE or ENTITY declaration, which is refused")
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ValueError(f"the listing is not well-formed XML: {exc}") from None
    if root.tag != _S3 + "ListBucketResult":
        raise ValueError(
            f"the listing is not an S3 ListBucketResult document (root {root.tag!r:.100})"
        )

    prefixes: list[str] = []
    keys: list[str] = []
    truncated = False
    named_marker: str | None = None
    # Only the root's own children: its <Prefix> element is the request's, not an entry.
    for child in root:
        if child.tag == _S3 + "CommonPrefixes":
            prefixes.append(_entry_text(child, "CommonPrefixes", "Prefix"))
        elif child.tag == _S3 + "Contents":
            keys.append(_entry_text(child, "Contents", "Key"))
        elif child.tag == _S3 + "IsTruncated":
            truncated = _flag(child.text)
        elif child.tag == _S3 + "NextMarker":
            named_marker = child.text or None

    next_marker: str | None = None
    if truncated:
        next_marker = named_marker or max(chain(prefixes, keys), default=None)
        if next_marker is None:
            raise ValueError(
                "the listing is truncated and yields no marker to continue from: "
                "it names no NextMarker and has no entry"
            )
    return ListingPage(tuple(prefixes), tuple(keys), next_marker)


def _listing_url(prefix: str, marker: str | None) -> str:
    """The one query the transport's allowlist lets through: bucket, delimiter, prefix and,
    after the first page, a marker (the server's text, percent-encoded)."""
    url = f"{LISTING_URL}?delimiter=/&prefix={prefix}"
    return url if marker is None else f"{url}&marker={quote(marker, safe='/')}"


def list_all(transport: Transport, prefix: str) -> ListingPage:
    """Every sub-directory and key under ``prefix``, following the pages to the last.

    ``prefix`` is a path under ``data/``. A prefix the bucket does not answer (404), a page
    that is not a listing and a continuation that does not move forward are errors; the last
    would otherwise ask for the same page for ever.
    """
    if not isinstance(prefix, str) or _PREFIX.fullmatch(prefix) is None or ".." in prefix:
        raise ValueError(
            f"prefix must be a path under data/ of plain key characters, got {prefix!r}"
        )
    prefixes: list[str] = []
    keys: list[str] = []
    marker: str | None = None
    while True:
        url = _listing_url(prefix, marker)
        body = transport.get(url)
        if body is None:
            raise ValueError(f"{url} was not found (HTTP 404) where a listing was expected")
        page = parse_listing(body)
        prefixes.extend(page.prefixes)
        keys.extend(page.keys)
        if page.next_marker is None:
            return ListingPage(tuple(prefixes), tuple(keys), None)
        if marker is not None and page.next_marker <= marker:
            raise ValueError(
                f"the listing of {prefix} does not advance: it went on after {marker!r} "
                f"with {page.next_marker!r}"
            )
        marker = page.next_marker


def discover_spot_usdt_symbols(transport: Transport) -> tuple[str, ...]:
    """Every USDT-quoted spot symbol with a klines directory, sorted; delisted ones included.

    A symbol is kept if it ends in ``USDT`` and has a base (so ``USDTBRL`` and ``BTCBUSD`` go);
    leveraged tokens and stablecoins are kept, for the universe step to exclude.
    """
    symbols: set[str] = set()
    for directory in list_all(transport, SPOT_KLINES_PREFIX).prefixes:
        match = _SPOT_SYMBOL_DIR.fullmatch(directory)
        if match is not None:
            symbol = match.group(1)
            if symbol.endswith(_QUOTE) and len(symbol) > len(_QUOTE):
                symbols.add(symbol)
    return tuple(sorted(symbols))


def discover_months(
    transport: Transport, kind: str, symbol: str, config: DataConfig
) -> tuple[str, ...]:
    """The months ``symbol`` has a monthly archive of ``kind`` for, sorted, up to ``end_month``.

    ``kind`` is one of ``archives.KINDS``. Only keys named ``<SYMBOL>-<interval>-YYYY-MM.zip``
    (``<SYMBOL>-fundingRate-YYYY-MM.zip`` for funding) in the kind's own directory count:
    ``.CHECKSUM`` files, other symbols, other intervals and malformed months are ignored. A
    key for a month after ``config.end_month`` is left out, not refused: a listing is not a
    request, and nothing after ``end_month`` is ever asked for. An unknown kind, a bad symbol
    and a malformed ``end_month`` are errors raised before any request.
    """
    directory, name = archive_path(kind, symbol, _SAMPLE_MONTH).rsplit("/", 1)
    prefix = directory.lstrip("/") + "/"
    head, tail = name.split(_SAMPLE_MONTH)
    pattern = re.compile(re.escape(prefix + head) + f"({_MONTH})" + re.escape(tail))
    # Raises for a malformed end_month; otherwise every key would be silently left out.
    refuse_after_end(_FIRST_MONTH, config)

    months: set[str] = set()
    for key in list_all(transport, prefix).keys:
        match = pattern.fullmatch(key)
        # Both are zero-padded YYYY-MM, so the string order is the calendar order.
        if match is not None and match.group(1) <= config.end_month:
            months.add(match.group(1))
    return tuple(sorted(months))
