"""Checksum-verified archive fetch for the V4 data step; the only module here that opens a socket.

``fetch_verified`` downloads one monthly archive from data.binance.vision, downloads its
``.CHECKSUM`` and accepts the bytes only if their SHA-256 is the one that file states for
this archive. The result is a ``ManifestEntry`` pinning those bytes, so that
``fetch_pinned`` can later fetch them again and refuse anything else. A missing checksum,
one that names another file and one that does not match are errors, never a skip.

The network is reached through a ``Transport`` (``get(url) -> bytes | None``, None for an
HTTP 404). ``HttpTransport`` is the real one: an allowlist of exactly four archive shapes
(and their checksums) on ``data.binance.vision``, plus the bucket listing query on
``s3-ap-northeast-1.amazonaws.com``. Any other URL is refused before a connection is opened,
redirects are never followed and no proxy is used, so no other host is ever contacted.

A month after the config's ``end_month`` is refused before any request. A transport failure
(a connection error, a timeout or an HTTP 5xx) is tried four times in all, sleeping 1, 2 and
4 seconds between the tries; nothing else is ever retried.
"""

from __future__ import annotations

import hashlib
import math
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException, HTTPMessage
from typing import IO, Protocol

from crypto_grid_bot.v4.data.config import DataConfig, refuse_after_end

ARCHIVE_URL = "https://data.binance.vision"
LISTING_URL = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_CHECKSUM_BYTES = 1024
MAX_LISTING_BYTES = 4 * 1024 * 1024
# A transport failure is tried this many times in all, sleeping 1, 2 and 4 s in between.
ATTEMPTS = 4

# The archive layouts, one per kind; the only paths the allowlist lets through.
_TEMPLATES = {
    "spot_1d": "/data/spot/monthly/klines/{symbol}/1d/{symbol}-1d-{month}.zip",
    "spot_1h": "/data/spot/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip",
    "futures_1h": "/data/futures/um/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip",
    "funding": "/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip",
}
KINDS = tuple(_TEMPLATES)

_SYMBOL = r"[A-Z0-9]{2,30}"
_MONTH = r"[0-9]{4}-(?:0[1-9]|1[0-2])"
_SYMBOL_RE = re.compile(_SYMBOL)
_MONTH_RE = re.compile(_MONTH)
_SHA256 = re.compile(r"[0-9a-f]{64}")
# "<64 hex>  <filename>", as the sha256sum tool writes it; the filename may follow a "*".
_CHECKSUM_LINE = re.compile(r"([0-9a-fA-F]{64})[ \t]+\*?([^\s]+)")
_HTTP_STATUS = re.compile(r"\bHTTP ([0-9]{3})\b")
# Every character a URL may hold; no "@", "#", space, backslash or control character. The
# allowlist matches the whole string against fixed shapes, so no URL parser can disagree
# with it about the host.
_SAFE_URL = re.compile(r"[A-Za-z0-9:/?&=._%-]+")
_KEY = r"[A-Za-z0-9._/-]"
# The listing query Task 3 sends: a prefix under data/, optionally continued from a marker
# (a key, which may be percent-encoded). Nothing else is a listing.
_LISTING_QUERY = re.compile(
    rf"(?!.*\.\.)delimiter=/&prefix=data/{_KEY}*(?:&marker=data/(?:{_KEY}|%[0-9A-Fa-f]{{2}})*)?"
)


def _request_pattern(template: str) -> re.Pattern[str]:
    """The path regex for one layout, with ``.CHECKSUM`` optional; the symbol and the month
    each appear once as a group and again as a back-reference, so they must agree."""
    seen: set[str] = set()
    parts: list[str] = []
    for index, part in enumerate(re.split(r"\{(symbol|month)\}", template)):
        if index % 2 == 0:
            parts.append(re.escape(part))
        elif part in seen:
            parts.append(f"(?P={part})")
        else:
            seen.add(part)
            parts.append(f"(?P<{part}>{_SYMBOL if part == 'symbol' else _MONTH})")
    return re.compile("".join(parts) + r"(?P<checksum>\.CHECKSUM)?")


_REQUESTS = tuple(_request_pattern(template) for template in _TEMPLATES.values())


class Transport(Protocol):
    def get(self, url: str) -> bytes | None:
        """The body at ``url``; None for HTTP 404. A failure raises."""
        ...


def archive_path(kind: str, symbol: str, month: str) -> str:
    """The path of one monthly archive on data.binance.vision."""
    template = _TEMPLATES.get(kind) if isinstance(kind, str) else None
    if template is None:
        raise ValueError(f"unknown archive kind {kind!r}; expected one of {', '.join(KINDS)}")
    if not isinstance(symbol, str) or _SYMBOL_RE.fullmatch(symbol) is None:
        raise ValueError(f"symbol must match {_SYMBOL}, got {symbol!r}")
    if not isinstance(month, str) or _MONTH_RE.fullmatch(month) is None:
        raise ValueError(f"month must be YYYY-MM, got {month!r}")
    return template.format(symbol=symbol, month=month)


def _size_limit(url: object) -> int:
    """The most bytes a response from ``url`` may have, or a ValueError if ``url`` is not one
    the transport may request."""
    if type(url) is str and _SAFE_URL.fullmatch(url) is not None:
        if url.startswith(ARCHIVE_URL + "/"):
            path = url[len(ARCHIVE_URL) :]
            for pattern in _REQUESTS:
                match = pattern.fullmatch(path)
                if match is not None:
                    return MAX_CHECKSUM_BYTES if match.group("checksum") else MAX_ARCHIVE_BYTES
        elif url.startswith(LISTING_URL + "?"):
            if _LISTING_QUERY.fullmatch(url[len(LISTING_URL) + 1 :]) is not None:
                return MAX_LISTING_BYTES
    raise ValueError(f"{url!r:.200} is not an allowed URL: only Binance archives and listings")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an error: it could lead to a host outside the allowlist."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class HttpTransport:
    """Public GETs over ``urllib.request``, for the allowlisted URLs only; no credentials.

    A URL outside the allowlist raises ``ValueError`` before any connection is opened. HTTP
    404 is None. Any other HTTP status raises a ``ValueError`` naming it; a connection error,
    a timeout or an interrupted read raises one caused by the underlying error. Both are what
    ``fetch_verified`` classifies, so only a 5xx or a network error is retried.
    """

    def __init__(self, timeout: float = 30) -> None:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError(f"timeout must be a positive number of seconds, got {timeout!r}")
        self._timeout = timeout
        # An empty ProxyHandler: the connection goes to the host in the URL, not to a proxy.
        self._opener = urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler({}))

    def get(self, url: str) -> bytes | None:
        limit = _size_limit(url)
        request = urllib.request.Request(
            url, method="GET", headers={"User-Agent": "crypto-grid-bot-v4-research"}
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                status = response.status
                body: bytes = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code == 404:
                return None
            raise ValueError(
                f"public data returned HTTP {exc.code}; a redirect is never followed"
            ) from None
        except (OSError, HTTPException) as exc:
            raise ValueError("public data transport failed") from exc
        if status != 200:
            raise ValueError(f"public data returned HTTP {status} where 200 was expected")
        if len(body) > limit:
            raise ValueError(
                f"the response for {url} exceeded the size limit of {limit} bytes; "
                "its complete size is unknown"
            )
        return body


@dataclass(frozen=True)
class ManifestEntry:
    """One archive pinned by the SHA-256 of its bytes."""

    kind: str
    symbol: str
    month: str
    path: str
    sha256: str
    bytes: int


def _transport_failure(error: Exception) -> bool:
    """Whether ``error`` is worth another attempt: a connection error, a timeout or an HTTP
    5xx. ``HttpTransport`` reports these as a ValueError caused by an OSError or an
    HTTPException (or naming the 5xx status); a transport of another kind may raise the
    OSError itself. Any other HTTP status, a size limit and a guard refusal are refusals,
    and a retry cannot change them."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500
    status = _HTTP_STATUS.search(str(error))
    if status is not None:
        return status.group(1).startswith("5")
    if isinstance(error, ValueError):
        return isinstance(error.__cause__, OSError | HTTPException)
    return isinstance(error, OSError | HTTPException)


def _get_with_retries(
    transport: Transport,
    url: str,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> bytes | None:
    """One response from ``transport``, trying a transport failure ``ATTEMPTS`` times in all."""
    attempt = 1
    while True:
        try:
            return transport.get(url)
        except Exception as exc:
            if not _transport_failure(exc):
                raise
            log(f"RETRY attempt {attempt} of {ATTEMPTS} for {url}: {exc}")
            if attempt == ATTEMPTS:
                raise
            sleep(1 << (attempt - 1))
            attempt += 1


def _download(
    transport: Transport,
    url: str,
    what: str,
    limit: int,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> bytes | None:
    """``url``'s body (None for a 404), once it is known to be bytes within ``limit``."""
    content = _get_with_retries(transport, url, sleep, log)
    if content is None:
        return None
    if type(content) is not bytes:
        raise ValueError(f"the {what} from {url} is not bytes")
    if len(content) > limit:
        raise ValueError(f"the {what} from {url} exceeds the size limit of {limit} bytes")
    return content


def _expected_digest(checksum: bytes, filename: str) -> str:
    """The lower-case SHA-256 a ``.CHECKSUM`` file states for ``filename``; a file that is
    not ASCII, is not one "<64 hex>  <name>" line or names another file is an error."""
    try:
        text = checksum.decode("ascii").strip()
    except UnicodeError:
        raise ValueError("the checksum file must be ASCII") from None
    match = _CHECKSUM_LINE.fullmatch(text)
    if match is None or match.group(2) != filename:
        raise ValueError(
            f"the checksum file's format or filename does not match the archive {filename}"
        )
    return match.group(1).lower()


def fetch_verified(
    transport: Transport,
    kind: str,
    symbol: str,
    month: str,
    config: DataConfig,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> tuple[ManifestEntry, bytes] | None:
    """One archive and the entry that pins it, or None if the host has no such archive.

    The month must not be after ``config.end_month``; that, the kind, the symbol and the
    month are checked before any request. The archive's ``.CHECKSUM`` is then fetched and the
    bytes must hash to the SHA-256 it states for this archive's name. An archive whose
    checksum is missing (404), unreadable, for another file or different from the bytes' own
    raises ``ValueError`` and is never retried.
    """
    path = archive_path(kind, symbol, month)
    refuse_after_end(month, config)
    url = ARCHIVE_URL + path
    content = _download(transport, url, "archive", MAX_ARCHIVE_BYTES, sleep, log)
    if content is None:
        return None
    checksum = _download(transport, url + ".CHECKSUM", "checksum", MAX_CHECKSUM_BYTES, sleep, log)
    if checksum is None:
        raise ValueError(f"{path}: the archive exists but its checksum file is missing (HTTP 404)")
    expected = _expected_digest(checksum, path.rsplit("/", 1)[1])
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected:
        raise ValueError(
            f"{path}: archive checksum mismatch: the checksum file says {expected}, "
            f"the downloaded bytes hash to {digest}"
        )
    return ManifestEntry(kind, symbol, month, path, digest, len(content)), content


def fetch_pinned(
    transport: Transport,
    entry: ManifestEntry,
    *,
    sleep: Callable[[float], None],
    log: Callable[[str], None],
) -> bytes:
    """The archive ``entry`` pins, downloaded again; bytes with any other SHA-256 are refused.

    The entry is the authority, so no ``.CHECKSUM`` is requested. An entry whose path is not
    the archive path of its own kind, symbol and month, or whose sha256 is not 64 lower-case
    hex digits, is refused before any request. A 404 is an error, since the entry says the
    archive exists; a mismatch is never retried.
    """
    path = archive_path(entry.kind, entry.symbol, entry.month)
    if entry.path != path:
        raise ValueError(f"{entry.path}: the entry's path is not {path}")
    if not isinstance(entry.sha256, str) or _SHA256.fullmatch(entry.sha256) is None:
        raise ValueError(f"{path}: the entry's sha256 must be 64 lowercase hex digits")
    content = _download(transport, ARCHIVE_URL + path, "archive", MAX_ARCHIVE_BYTES, sleep, log)
    if content is None:
        raise ValueError(f"{path}: the entry pins this archive but the host has none (HTTP 404)")
    digest = hashlib.sha256(content).hexdigest()
    if digest != entry.sha256:
        raise ValueError(
            f"{path}: the host's bytes do not match the pinned sha256: "
            f"expected {entry.sha256}, got {digest}"
        )
    return content
