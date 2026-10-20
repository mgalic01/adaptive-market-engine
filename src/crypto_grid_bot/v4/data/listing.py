"""Archive listing and discovery for the V4 data step: which symbols and months Binance holds.

Binance publishes its archive tree as the S3 bucket ``data.binance.vision``. A listing of a
prefix (``delimiter=/``) names the sub-directories under it (``CommonPrefixes``) and the files
in it (``Contents``), at most 1000 entries a page. ``list_all`` follows the pages and merges
them; ``discover_spot_usdt_listing`` (and ``discover_spot_usdt_symbols``, its symbols) and
``discover_futures_usdt_symbols`` read the spot and USDT-M futures klines directories, delisted
symbols included, and ``discover_months`` reads one symbol's archive file names for one kind.
A spot name ending in USDT that ``archive_path`` cannot address, such as 币安人生USDT, is
returned apart as unsupported (ruling P33): counted and recorded, never fetched, never dropped
silently. ``perpetual_for`` names a coin's perpetual among the futures symbols, by the spec's
rule ("Data"): the plain ``XUSDT``, else the one symbol with a contract-multiplier prefix
(1000SHIBUSDT is 1000 SHIB); ``perpetual_names`` lists the names it considers, and
``checked_perpetual`` checks a recorded one against the same rule. The caller passes only
futures symbols with a monthly archive at or before ``end_month`` (ruling P34).

Everything here goes through a ``Transport``, so the only network access is the one
``archives.HttpTransport`` allows: the bucket listing query, nothing else. Each page request is
retried exactly as an archive request is (``archives.get_with_retries``: a transport failure
four tries in all, sleeping 1, 2 and 4 s; nothing else is retried). A listing is
untrusted input: it is size-capped, parsed as UTF-8 XML without a DTD, and read for the S3
elements only. The universe step, not this module, decides what to exclude (stablecoins,
leveraged tokens), so ``discover_spot_usdt_symbols`` keeps them.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from itertools import chain
from typing import TypeGuard
from urllib.parse import quote
from xml.etree import ElementTree  # nosec B405

from crypto_grid_bot.v4.data.archives import (
    LISTING_URL,
    MAX_LISTING_BYTES,
    Transport,
    archive_path,
    get_with_retries,
)
from crypto_grid_bot.v4.data.config import DataConfig, refuse_after_end

SPOT_KLINES_PREFIX = "data/spot/monthly/klines/"
FUTURES_KLINES_PREFIX = "data/futures/um/monthly/klines/"
# The contract-multiplier prefixes of USDT-M perpetuals, and how many coins one unit of each is
# (spec, "Data"): 1000SHIBUSDT is 1000 SHIB, 1MBABYDOGEUSDT a million BABYDOGE.
PERPETUAL_PREFIXES = (
    ("1000", 1_000),
    ("10000", 10_000),
    ("100000", 100_000),
    ("1000000", 1_000_000),
    ("1M", 1_000_000),
)
MULTIPLIERS = (1, 1_000, 10_000, 100_000, 1_000_000)
# The exclusion reason of a listed USDT name archive_path cannot address (ruling P33).
UNSUPPORTED_NAME = "unsupported_name"
# S3 lists 1000 entries a page, so this is ten million entries: far more than the bucket holds.
# A listing that needs more pages is refused instead of looped over.
MAX_LISTING_PAGES = 10_000

_S3 = "{http://s3.amazonaws.com/doc/2006-03-01/}"
# The same shapes archives.archive_path accepts: a listed name it would refuse is no use to
# a later request, so it is not discovered.
_SYMBOL = r"[A-Z0-9]{2,30}"
_MONTH = r"[0-9]{4}-(?:0[1-9]|1[0-2])"
_PREFIX = re.compile(r"data/[A-Za-z0-9._/-]*")
_SYMBOL_RE = re.compile(_SYMBOL)
_QUOTE = "USDT"
# A listed directory name (any characters but "/", bounded) that may be an unsupported name.
_LISTED_NAME = r"[^/]{1,100}"
_LISTED_NAME_RE = re.compile(_LISTED_NAME)
# A month used only to have archive_path spell out one kind's directory and file name.
_SAMPLE_MONTH = "2000-01"
# Never after any valid end_month, so refuse_after_end only ever objects to a bad end_month.
_FIRST_MONTH = "0000-01"


@dataclass(frozen=True)
class UsdtListing:
    """The USDT names under a klines prefix, sorted: ``symbols`` that ``archive_path`` accepts,
    and ``unsupported`` names that end in USDT after a base but which it cannot address."""

    symbols: tuple[str, ...]
    unsupported: tuple[str, ...]


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

    A page over ``MAX_LISTING_BYTES``, one that holds a NUL byte or is not UTF-8, carries a
    DOCTYPE or an ENTITY declaration, is not well-formed XML or is not a ``ListBucketResult`` in
    the S3 namespace is refused. So is a page without an ``IsTruncated`` element (real S3 always
    sends one, and a page that lacks it could be cut off) or with a value other than ``true`` or
    ``false``. ``next_marker`` is set only for a truncated page: the page's ``NextMarker``, else
    (as S3's V1 listing defines it) the last entry of the page. A truncated page that gives
    neither is refused, since nothing could continue it.
    """
    if type(xml) is not bytes:
        raise ValueError("the listing must be bytes")
    if len(xml) > MAX_LISTING_BYTES:
        raise ValueError(f"the listing exceeds the size limit of {MAX_LISTING_BYTES} bytes")
    # Expat finds a BOM-less UTF-16 or UTF-32 document by itself, and ASCII text in those is also
    # valid UTF-8 (a character and NULs), which the DOCTYPE scan below would not see. NUL is never
    # legal in XML 1.0, so a listing holding one is refused before it is read at all.
    if b"\x00" in xml:
        raise ValueError("the listing holds a NUL byte (UTF-16 or UTF-32?); it must be UTF-8")
    try:
        text = xml.decode("utf-8")
    except UnicodeError:
        raise ValueError("the listing must be UTF-8") from None
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("the listing carries a DOCTYPE or ENTITY declaration, which is refused")
    # The stdlib parser is safe here (bandit B405/B314): the checks above refuse a DOCTYPE, an
    # ENTITY declaration and NUL bytes before parsing, so there is no entity expansion, no
    # external entity and no UTF-16/32 bypass, and only the allowlisted S3 host over HTTPS is
    # read. defusedxml would be a new dependency.
    try:
        root = ElementTree.fromstring(xml)  # nosec B314
    except ElementTree.ParseError as exc:
        raise ValueError(f"the listing is not well-formed XML: {exc}") from None
    if root.tag != _S3 + "ListBucketResult":
        raise ValueError(
            f"the listing is not an S3 ListBucketResult document (root {root.tag!r:.100})"
        )

    prefixes: list[str] = []
    keys: list[str] = []
    truncated: bool | None = None
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

    if truncated is None:
        raise ValueError("the listing has no IsTruncated element, so it cannot be told complete")
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
    if marker is None:
        return url
    # quote() leaves "~" as it is, but the allowlist's marker characters have no "~".
    return f"{url}&marker={quote(marker, safe='/').replace('~', '%7E')}"


def list_all(
    transport: Transport,
    prefix: str,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> ListingPage:
    """Every sub-directory and key under ``prefix``, following the pages to the last.

    ``prefix`` is a path under ``data/``. Each page request is retried on a transport failure
    (``archives.get_with_retries``); a 4xx, a size breach and a guard refusal are not. A prefix
    the bucket does not answer (404), a page that is not a listing, a continuation that does
    not move forward and a listing of more than ``MAX_LISTING_PAGES`` pages are errors; without
    them a server could keep this asking for ever.
    """
    if not isinstance(prefix, str) or _PREFIX.fullmatch(prefix) is None or ".." in prefix:
        raise ValueError(
            f"prefix must be a path under data/ of plain key characters, got {prefix!r}"
        )
    prefixes: list[str] = []
    keys: list[str] = []
    marker: str | None = None
    for _ in range(MAX_LISTING_PAGES):
        url = _listing_url(prefix, marker)
        body = get_with_retries(transport, url, sleep=sleep, log=log)
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
    raise ValueError(f"the listing of {prefix} needs more than {MAX_LISTING_PAGES} pages")


def _is_usdt_symbol(symbol: object) -> TypeGuard[str]:
    """Whether ``symbol`` is a name ``archive_path`` accepts that ends in ``USDT`` after a base."""
    return (
        isinstance(symbol, str)
        and _SYMBOL_RE.fullmatch(symbol) is not None
        and symbol.endswith(_QUOTE)
        and len(symbol) > len(_QUOTE)
    )


def is_unsupported_usdt_name(name: object) -> bool:
    """Whether ``name`` ends in ``USDT`` after a base but is not a symbol ``archive_path``
    accepts (ruling P33): not made of ASCII capital letters and digits, or too long. Such a
    name is at most 100 characters and holds no "/"."""
    return (
        isinstance(name, str)
        and _LISTED_NAME_RE.fullmatch(name) is not None
        and name.endswith(_QUOTE)
        and len(name) > len(_QUOTE)
        and not _is_usdt_symbol(name)
    )


def _usdt_listing(
    transport: Transport,
    prefix: str,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> UsdtListing:
    """Every USDT name with a directory directly under ``prefix``, split into the symbols
    ``archive_path`` accepts and the unsupported names."""
    directory = re.compile(rf"{re.escape(prefix)}({_LISTED_NAME})/")
    symbols: set[str] = set()
    unsupported: set[str] = set()
    for entry in list_all(transport, prefix, sleep=sleep, log=log).prefixes:
        match = directory.fullmatch(entry)
        if match is None:
            continue
        if _is_usdt_symbol(match.group(1)):
            symbols.add(match.group(1))
        elif is_unsupported_usdt_name(match.group(1)):
            unsupported.add(match.group(1))
    return UsdtListing(tuple(sorted(symbols)), tuple(sorted(unsupported)))


def discover_spot_usdt_listing(
    transport: Transport,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> UsdtListing:
    """Every USDT-quoted spot name with a klines directory, delisted ones included: the
    symbols, sorted, and apart from them the unsupported names (ruling P33), sorted.

    A name counts if it ends in ``USDT`` and has a base (so ``USDTBRL`` and ``BTCBUSD`` go);
    leveraged tokens and stablecoins are kept, for the universe step to exclude. Page requests
    are retried as in ``list_all``.
    """
    return _usdt_listing(transport, SPOT_KLINES_PREFIX, sleep, log)


def discover_spot_usdt_symbols(
    transport: Transport,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> tuple[str, ...]:
    """The symbols of ``discover_spot_usdt_listing``: every USDT-quoted spot symbol with a
    klines directory that ``archive_path`` accepts, sorted; delisted ones included."""
    return discover_spot_usdt_listing(transport, sleep=sleep, log=log).symbols


def discover_futures_usdt_symbols(
    transport: Transport,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> tuple[str, ...]:
    """Every USDT-M futures symbol ending in ``USDT`` with a monthly klines directory, sorted;
    delisted ones and multiplier contracts (``1000SHIBUSDT``) included.

    The rule is the spot one: a name ``archive_path`` accepts, ending in ``USDT`` after a base.
    So a delivery contract (``BTCUSDT_240329``) and a USDC-margined perpetual go. Page requests
    are retried as in ``list_all``.
    """
    return _usdt_listing(transport, FUTURES_KLINES_PREFIX, sleep, log).symbols


def _perpetual_names(spot_symbol: object) -> tuple[str, tuple[tuple[str, int], ...]]:
    """A spot USDT symbol's plain perpetual name, and each multiplier name with its multiplier;
    every one is built from the coin's base, never found by stripping a prefix.

    A base that starts with ``0`` has no multiplier name (ruling P31, spec "Data"): prefixed,
    it could spell another coin's contract, since ``1000`` + ``0X`` is ``10000`` + ``X``."""
    if not _is_usdt_symbol(spot_symbol):
        raise ValueError(
            f"a spot USDT symbol is required (a base, then USDT, {_SYMBOL} in all), "
            f"got {spot_symbol!r:.80}"
        )
    base = spot_symbol.removesuffix(_QUOTE)
    if base.startswith("0"):
        return f"{base}{_QUOTE}", ()
    prefixed = tuple((f"{prefix}{base}{_QUOTE}", m) for prefix, m in PERPETUAL_PREFIXES)
    return f"{base}{_QUOTE}", prefixed


def perpetual_names(spot_symbol: str) -> tuple[str, ...]:
    """Every futures symbol ``perpetual_for`` considers for the coin: the plain name first,
    then each multiplier name (none for a base that starts with ``0``, ruling P31)."""
    plain, prefixed = _perpetual_names(spot_symbol)
    return (plain, *(name for name, _ in prefixed))


def perpetual_for(spot_symbol: str, futures_symbols: Collection[str]) -> tuple[str, int] | None:
    """The coin's USDT-M perpetual among ``futures_symbols`` and its multiplier, or None.

    The spec's rule ("Data"): the plain ``XUSDT`` if it is listed, multiplier 1. Otherwise the
    one listed ``P + X + "USDT"`` whose prefix P is one of ``PERPETUAL_PREFIXES`` (``1000`` to
    ``1000000``, or ``1M``), with that prefix's multiplier. With no such symbol, or more than
    one, the coin has no perpetual. A prefixed name is built from the coin's base, so
    ``1000XUSDT`` is X's perpetual, never XEC's, and a base that starts with ``0`` gets only
    its plain symbol (ruling P31: ``10000XUSDT`` is X's, never 0X's). The caller passes only
    symbols with a monthly archive at or before ``end_month`` (ruling P34), so a plain symbol
    listed only later does not shadow a multiplier one. A ``spot_symbol`` that is
    not a USDT symbol
    ``archive_path`` accepts (a base, then ``USDT``) is a ``ValueError``, and so is a string
    given as ``futures_symbols`` (``in`` would match substrings).
    """
    if isinstance(futures_symbols, str):
        raise ValueError("futures_symbols must be a collection of symbols, not one string")
    plain, prefixed = _perpetual_names(spot_symbol)
    if plain in futures_symbols:
        return plain, 1
    matches = [(name, multiplier) for name, multiplier in prefixed if name in futures_symbols]
    return matches[0] if len(matches) == 1 else None


def checked_perpetual(spot_symbol: str, entry: object) -> tuple[str, int]:
    """A coin's recorded perpetual, ``{"symbol": ..., "multiplier": ...}``, as (symbol,
    multiplier), once it is a name ``perpetual_for`` could give the coin.

    The multiplier is one of ``MULTIPLIERS`` (an int, never a bool); 1 goes with the plain name
    ``X + "USDT"``, and any other with ``P + X + "USDT"`` for a prefix P of that multiplier,
    for a base X that does not start with ``0`` (ruling P31). Anything else is a
    ``ValueError``. Whether the futures archive lists the name is not checked here.
    """
    if not isinstance(entry, Mapping) or set(entry) != {"symbol", "multiplier"}:
        raise ValueError(
            f"{spot_symbol}'s perpetual must be {{symbol, multiplier}}, got {entry!r:.80}"
        )
    symbol, multiplier = entry["symbol"], entry["multiplier"]
    if type(multiplier) is not int or multiplier not in MULTIPLIERS:
        raise ValueError(
            f"{spot_symbol}'s perpetual multiplier must be one of "
            f"{', '.join(map(str, MULTIPLIERS))}, got {multiplier!r:.40}"
        )
    plain, prefixed = _perpetual_names(spot_symbol)
    if (symbol, multiplier) != (plain, 1) and (symbol, multiplier) not in prefixed:
        raise ValueError(
            f"{symbol!r:.40} is not {spot_symbol}'s perpetual name for multiplier {multiplier}"
        )
    return symbol, multiplier


def discover_months(
    transport: Transport,
    kind: str,
    symbol: str,
    config: DataConfig,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> tuple[str, ...]:
    """The months ``symbol`` has a monthly archive of ``kind`` for, sorted, up to ``end_month``.

    ``kind`` is one of ``archives.KINDS``. Only keys named ``<SYMBOL>-<interval>-YYYY-MM.zip``
    (``<SYMBOL>-fundingRate-YYYY-MM.zip`` for funding) in the kind's own directory count:
    ``.CHECKSUM`` files, other symbols, other intervals and malformed months are ignored. A
    key for a month after ``config.end_month`` is left out, not refused: a listing is not a
    request, and nothing after ``end_month`` is ever asked for. An unknown kind, a bad symbol
    and a malformed ``end_month`` are errors raised before any request. Page requests are
    retried as in ``list_all``.
    """
    directory, name = archive_path(kind, symbol, _SAMPLE_MONTH).rsplit("/", 1)
    prefix = directory.lstrip("/") + "/"
    head, tail = name.split(_SAMPLE_MONTH)
    pattern = re.compile(re.escape(prefix + head) + f"({_MONTH})" + re.escape(tail))
    # Raises for a malformed end_month; otherwise every key would be silently left out.
    refuse_after_end(_FIRST_MONTH, config)

    months: set[str] = set()
    for key in list_all(transport, prefix, sleep=sleep, log=log).keys:
        match = pattern.fullmatch(key)
        # Both are zero-padded YYYY-MM, so the string order is the calendar order.
        if match is not None and match.group(1) <= config.end_month:
            months.add(match.group(1))
    return tuple(sorted(months))
