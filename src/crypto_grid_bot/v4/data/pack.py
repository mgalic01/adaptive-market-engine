"""The V4 data packs: canonical gzip JSON, pinned by the SHA-256 of the JSON text.

Two packs hold what the engine replays, the daily one (spot daily bars, the universe) and the
hourly one (spot and USDT-M hourly bars, funding, order rules). Each is one JSON object, written
canonically (sorted keys, separators ``(",", ":")``, ASCII, no NaN), gzipped with mtime 0 and no
file name, and pinned by the SHA-256 of that JSON, not of the gzip bytes: the same document has
the same pin on any machine, while the gzip around it may differ between zlib builds. This is
the ``combined/driver/packs.py`` convention, restated here because that module also carries the
2024 guard. ``write_canonical`` refuses an existing file, a document the reader would not hand
back unchanged (a float, a non-string key, a tuple) and never leaves a partial file at the final
path (it links a finished temporary file into place); ``read_canonical`` refuses a wrong pin,
a duplicate key, a float, NaN or Infinity, a document that is not an object, and anything that
decompresses to more than 2 GiB. Pure file I/O: nothing here touches the network.

Every Decimal is written as its ``str()`` (ruling P21), under a fresh default context: the CSV's
own text, ``"0.09865000"``, and ``"1E-7"`` for a small inferred tick. ``Decimal(text)`` rebuilds
the same Decimal, exponent included. Timestamps are plain ints (ms), and ``interval_hours`` is an
int or null. The reader hands rows back as written, strings and ints.

Both documents hold ``format`` (``"v4-daily-pack/1"`` or ``"v4-hourly-pack/1"``),
``config_sha256`` (the SHA-256 of the raw bytes of ``config/v4_data.json``, which the caller
computes; it is why ``.gitattributes`` keeps that file LF), ``end_month`` and ``manifest``, every
archive the pack was built from as ``{kind, symbol, month, path, sha256, bytes}``, sorted by
(kind, symbol, month). The rest, by pack:

* daily: ``daily`` (symbol -> rows ``[open_ms, open, high, low, close, quote_volume]``),
  ``exclusions`` (symbol -> reason), ``masks`` and ``universes`` (one object per month with the
  fields of ``MonthlyUniverse``; a ``ranked`` entry is ``[symbol, mean quote volume, bars]``);
* hourly: ``spot`` and ``futures`` (symbol -> rows ``[open_ms, open, high, low, close, volume,
  quote_volume]``), ``masks``, ``funding`` (symbol -> rows ``[time_ms, rate, interval_hours]``),
  ``funding_months`` (``"SYMBOL|YYYY-MM"`` -> ``"complete"``, a failure reason of
  ``funding_month_status``, ``"missing_file"`` or ``"unreadable_file"``), ``rules``
  (``"SYMBOL|venue"`` -> ``{source, step, min_qty, max_qty, min_notional, tick}`` with
  ``source`` ``"present_day"`` or ``"inferred"``) and ``perpetuals`` (spot symbol ->
  ``{"symbol": perpetual, "multiplier": int}`` for every coin of the pack with a futures
  series). ``spot`` is keyed by the coin's spot symbol; ``futures``, ``funding``,
  ``funding_months`` and the futures ``masks`` and ``rules`` by the perpetual's own symbol, the
  name of its archives, which for a multiplier contract is not the coin's (1000SHIBUSDT is
  SHIBUSDT's perpetual, one unit 1000 SHIB, its prices and filters in those units).

``masks`` maps each series to ``{"masked": [sorted unique interval opens, ms], "unreadable":
{"YYYY-MM": reason}}``: by symbol in the daily pack, by ``"SYMBOL|venue"`` in the hourly one
(venue ``"spot"`` or ``"futures"``). The caller passes the intervals inside each month only
(ruling P12), with every interval of an unreadable month included. Every series of the pack
has a mask entry, empty for a clean one, so a missing entry is an error, never "clean"; every
hourly series also has its rules. Months are never after ``end_month``.

The builders check what they write: Decimals are finite, timestamps are ints (never floats or
bools), bar opens strictly increase within a series and universe months across ``universes``
(funding rows keep the order given, since a duplicate slot is a status, not an error), symbols
and months are well formed, and masked opens are sorted and unique. Any refusal is a
``ValueError``.
"""

from __future__ import annotations

import errno
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, fields
from decimal import Context, Decimal, localcontext
from operator import attrgetter
from pathlib import Path
from typing import Any, get_args

from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.archives import ManifestEntry, archive_path
from crypto_grid_bot.v4.data.bars import DailyBar, FundingRow, HourBar
from crypto_grid_bot.v4.data.config import DataConfig, refuse_after_end
from crypto_grid_bot.v4.data.filters import Source
from crypto_grid_bot.v4.data.listing import checked_perpetual
from crypto_grid_bot.v4.data.universe import MonthlyUniverse

DAILY_FORMAT = "v4-daily-pack/1"
HOURLY_FORMAT = "v4-hourly-pack/1"
MAX_CONTENT_BYTES = 2 * 1024**3  # read_canonical refuses a pack that decompresses to more
_CHUNK = 1 << 20

_SHA256 = re.compile(r"[0-9a-f]{64}")
# The symbol shape archives.py lets through; it holds no "|", which joins the keys below.
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")
_VENUES = ("spot", "futures")
_SOURCES = get_args(Source)
# The reasons funding_month_status can give, and the two the caller records for a month it
# could not judge (rulings P13, P16).
_FUNDING_STATUSES = frozenset(
    {
        "complete",
        "interval_mixed",
        "interval_not_divisor_of_24",
        "off_slot",
        "duplicate_slot",
        "missing_slot",
        "missing_file",
        "unreadable_file",
    }
)
_RULE_FIELDS = tuple(field.name for field in fields(VenueRules))
_DAILY_VALUES = attrgetter("open", "high", "low", "close", "quote_volume")
_HOURLY_VALUES = attrgetter("open", "high", "low", "close", "volume", "quote_volume")

DailyMasks = Mapping[str, tuple[Sequence[int], Mapping[str, str]]]
HourlyMasks = Mapping[tuple[str, str], tuple[Sequence[int], Mapping[str, str]]]


def write_canonical(document: Mapping[str, Any], path: Path) -> str:
    """Write ``document`` to a new file at ``path`` and return its pin: the SHA-256 (hex) of
    the canonical JSON the file compresses.

    The document holds only what ``read_canonical`` hands back unchanged: dicts with string
    keys, lists, strings, ints, bools and None. A float (NaN and Infinity included), a
    non-string key, a tuple or any other type is a ``ValueError``, raised before any file is
    created. The gzip has mtime 0 and no file name.

    The bytes go to a temporary file in the same folder, which is hard-linked to ``path`` only
    once it is complete, so ``path`` never holds a partial pack. An existing file is refused
    (``FileExistsError``), never replaced, and no parent folder is created. The temporary file
    is removed whether or not the write succeeds.
    """
    if not isinstance(document, Mapping):
        raise ValueError("a pack document must be a mapping")
    plain = dict(document)
    try:
        _check_json(plain, [])
    except RecursionError as exc:
        raise ValueError("pack document: nested too deeply, or circular") from exc
    text = json.dumps(plain, sort_keys=True, separators=(",", ":"), allow_nan=False)
    content = text.encode("ascii")
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as archive:
        archive.write(content)
    _create_new(buffer.getvalue(), Path(path))
    return hashlib.sha256(content).hexdigest()


def read_canonical(path: Path, expected_sha256: str) -> dict[str, Any]:
    """The document in the gzip file at ``path``, once the SHA-256 of its JSON equals
    ``expected_sha256``.

    The file is decompressed with a cap of ``MAX_CONTENT_BYTES`` and its JSON hashed before
    it is parsed; any gzip bytes of that JSON are accepted. A duplicate key, a float, NaN or
    Infinity, non-ASCII text, malformed JSON or a top level that is not an object is refused.
    """
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("the expected pack sha256 must be 64 lowercase hex digits")
    content = _decompressed(path)
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected_sha256:
        raise ValueError(f"{path}: pack sha256 {actual} differs from the pinned {expected_sha256}")
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: a pack is ASCII JSON ({exc})") from exc
    try:
        document = json.loads(
            text,
            object_pairs_hook=_unique_keys,
            parse_float=_not_an_integer,
            parse_constant=_not_an_integer,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path}: the top level of a pack must be a JSON object")
    return document


def daily_pack_document(
    config: DataConfig,
    manifest: Sequence[ManifestEntry],
    daily: Mapping[str, Sequence[DailyBar]],
    exclusions: Mapping[str, str],
    universes: Sequence[MonthlyUniverse],
    *,
    masks: DailyMasks,
    config_sha256: str,
) -> dict[str, Any]:
    """The daily pack's document (``"v4-daily-pack/1"``; the module docstring has the layout).

    ``daily`` maps each symbol to its bars and ``masks`` each of them to its masked day opens
    and unreadable months; the two must name the same symbols. ``exclusions`` maps a symbol
    to the reason it is out whatever its prices.
    """
    with localcontext(Context()):  # str() reads the context's exponent letter case
        header = _header(config, config_sha256, manifest)
        return {
            "format": DAILY_FORMAT,
            **header,
            "daily": {
                _symbol(symbol, "daily"): _bar_rows(
                    f"daily {symbol}", bars, DailyBar, _DAILY_VALUES
                )
                for symbol, bars in daily.items()
            },
            "exclusions": _exclusions(exclusions),
            "masks": _masks(masks, {_symbol(symbol, "daily") for symbol in daily}, config),
            "universes": _universes(universes, config),
        }


def hourly_pack_document(
    config: DataConfig,
    manifest: Sequence[ManifestEntry],
    spot: Mapping[str, Sequence[HourBar]],
    futures: Mapping[str, Sequence[HourBar]],
    masks: HourlyMasks,
    funding: Mapping[str, Sequence[FundingRow]],
    funding_months: Mapping[tuple[str, str], str],
    rules: Mapping[tuple[str, str], tuple[VenueRules, str]],
    *,
    perpetuals: Mapping[str, Mapping[str, object]],
    config_sha256: str,
) -> dict[str, Any]:
    """The hourly pack's document (``"v4-hourly-pack/1"``; the module docstring has the layout).

    ``masks`` and ``rules`` are keyed by (symbol, venue) and must name exactly the series of
    ``spot`` and ``futures``. ``funding`` and ``funding_months`` (keyed by (symbol, month),
    one per month of the perpetual's kline trading span) are for symbols that have futures.
    ``perpetuals`` maps a coin of ``spot`` to its perpetual, ``{"symbol": ..., "multiplier":
    ...}``, a name the spec's rule gives it (``listing.checked_perpetual``); its perpetuals are
    exactly the symbols of ``futures``, so every futures key of ``futures``, ``masks``,
    ``rules``, ``funding`` and ``funding_months`` has an entry.
    """
    with localcontext(Context()):  # str() reads the context's exponent letter case
        header = _header(config, config_sha256, manifest)
        spot_rows = {
            _symbol(symbol, "spot"): _bar_rows(f"spot {symbol}", bars, HourBar, _HOURLY_VALUES)
            for symbol, bars in spot.items()
        }
        futures_rows = {
            _symbol(symbol, "futures"): _bar_rows(
                f"futures {symbol}", bars, HourBar, _HOURLY_VALUES
            )
            for symbol, bars in futures.items()
        }
        series = {f"{symbol}|spot" for symbol in spot} | {f"{symbol}|futures" for symbol in futures}
        return {
            "format": HOURLY_FORMAT,
            **header,
            "spot": spot_rows,
            "futures": futures_rows,
            "masks": _masks(_by_series(masks, "masks"), series, config),
            "funding": _funding(funding, futures),
            "funding_months": _funding_months(funding_months, futures, config),
            "rules": _rules(_by_series(rules, "rules"), series),
            "perpetuals": _perpetuals(perpetuals, spot, futures),
        }


def _decompressed(path: Path) -> bytes:
    """The bytes the gzip file at ``path`` holds; at most ``MAX_CONTENT_BYTES`` + 1 are ever
    decompressed, so an oversized stream is refused without exhausting memory."""
    cap = MAX_CONTENT_BYTES
    compressed = io.BytesIO(Path(path).read_bytes())
    chunks: list[bytes] = []
    total = 0
    try:
        with gzip.GzipFile(fileobj=compressed, mode="rb") as archive:
            while chunk := archive.read(min(_CHUNK, cap + 1 - total)):
                total += len(chunk)
                if total > cap:
                    raise ValueError(f"{path}: the pack decompresses to more than {cap} bytes")
                chunks.append(chunk)
    except (OSError, EOFError, zlib.error) as exc:
        raise ValueError(f"{path}: not a readable gzip pack ({exc})") from exc
    return b"".join(chunks)


_JSON_SCALARS = frozenset({str, int, bool, type(None)})


def _check_json(value: object, trail: list[object]) -> None:
    """``ValueError`` unless ``value`` is dicts with string keys, lists, strings, ints, bools
    and None, all by exact type: what ``read_canonical`` returns unchanged. ``trail`` is the
    path to ``value``, for the message."""
    if type(value) is list:
        for index, item in enumerate(value):
            if type(item) not in _JSON_SCALARS:
                trail.append(index)
                _check_json(item, trail)
                trail.pop()
    elif type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(f"pack document {_where(trail)}: key {key!r} is not a string")
            if type(item) not in _JSON_SCALARS:
                trail.append(key)
                _check_json(item, trail)
                trail.pop()
    elif type(value) not in _JSON_SCALARS:
        raise ValueError(
            f"pack document {_where(trail)}: a {type(value).__name__} ({value!r:.40}) is not "
            "JSON the reader returns unchanged (dicts with string keys, lists, strings, ints, "
            "bools, None)"
        )


def _where(trail: Sequence[object]) -> str:
    return "".join(f"[{step!r}]" for step in trail) or "at the top level"


def _create_new(data: bytes, final: Path) -> None:
    """Create ``final`` holding ``data``, or raise: a file that exists is ``FileExistsError``.

    ``data`` is written, flushed and synced to a uniquely named file beside ``final`` (opened
    ``xb``), which is then hard-linked to ``final``; the link fails if ``final`` exists, which
    keeps ``xb``'s refusal while ``final`` only ever appears complete. The temporary file is
    removed in every case.
    """
    temporary = final.with_name(f".{final.name}.{secrets.token_hex(8)}.tmp")
    created = False
    try:
        with open(temporary, "xb") as handle:
            created = True
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        _link_new(temporary, final)
    finally:
        if created:  # a failed open made no file, and the name is not ours to remove
            temporary.unlink(missing_ok=True)


def _link_new(source: Path, final: Path) -> None:
    """Hard-link ``source`` to ``final``, failing if ``final`` exists. Where the file system or
    platform cannot link, ``source`` is renamed over ``final`` after checking that nothing is
    there."""
    try:
        os.link(source, final)
        return
    except FileExistsError:
        raise
    except (OSError, NotImplementedError, AttributeError):
        pass  # no hard links here; fall back to a checked rename
    if os.path.lexists(final):
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(final))
    os.replace(source, final)


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"pack: duplicate JSON key {key!r}")
        result[key] = value
    return result


def _not_an_integer(text: str) -> object:
    raise ValueError(f"pack: number {text} is not an integer")


def _int(value: object, what: str) -> int:
    # `type(...) is int` keeps out bools and floats, which would not read back.
    if type(value) is not int:
        raise ValueError(f"{what}: an int required, got {value!r}")
    return value


def _text(value: object) -> str:
    """A finite Decimal as its ``str()``; the caller holds a default Decimal context."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"pack values must be finite Decimals, got {value!r}")
    return str(value)


def _symbol(value: object, what: str) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{what}: symbol must match [A-Z0-9]{{2,30}}, got {value!r}")
    return value


def _check_month(month: str, config: DataConfig, what: str) -> None:
    """``ValueError`` unless ``month`` is a ``YYYY-MM`` month not after ``config.end_month``."""
    try:
        refuse_after_end(month, config)
    except ValueError as exc:
        raise ValueError(f"{what}: {exc}") from exc


def _same_keys(what: str, given: set[str], expected: set[str]) -> None:
    if given != expected:
        raise ValueError(
            f"{what}: missing {sorted(expected - given)}, unexpected {sorted(given - expected)}"
        )


def _header(
    config: DataConfig, config_sha256: str, manifest: Sequence[ManifestEntry]
) -> dict[str, Any]:
    refuse_after_end(config.end_month, config)  # the config's own end month is a month
    if not isinstance(config_sha256, str) or _SHA256.fullmatch(config_sha256) is None:
        raise ValueError("config_sha256 must be 64 lowercase hex digits")
    return {
        "config_sha256": config_sha256,
        "end_month": config.end_month,
        "manifest": _manifest(manifest, config),
    }


def _manifest(manifest: Sequence[ManifestEntry], config: DataConfig) -> list[dict[str, Any]]:
    """Every entry as an object of its six fields, sorted by (kind, symbol, month)."""
    keyed: dict[tuple[str, str, str], ManifestEntry] = {}
    for item in manifest:
        if not isinstance(item, ManifestEntry):
            raise ValueError(f"manifest: ManifestEntry required, got {item!r}")
        path = archive_path(
            item.kind, item.symbol, item.month
        )  # kind, symbol and month are well formed
        refuse_after_end(item.month, config)
        label = f"manifest {item.kind} {item.symbol} {item.month}"
        if item.path != path:
            raise ValueError(f"{label}: the entry's path is not {path}")
        if not isinstance(item.sha256, str) or _SHA256.fullmatch(item.sha256) is None:
            raise ValueError(f"{label}: sha256 must be 64 lowercase hex digits")
        if _int(item.bytes, f"{label}: bytes") < 0:
            raise ValueError(f"{label}: bytes must not be negative")
        key = (item.kind, item.symbol, item.month)
        if key in keyed:
            raise ValueError(f"{label}: listed twice")
        keyed[key] = item
    return [asdict(keyed[key]) for key in sorted(keyed)]


def _bar_rows(
    label: str,
    bars: Iterable[object],
    bar_type: type[DailyBar] | type[HourBar],
    values: Callable[[Any], Sequence[Decimal]],
) -> list[list[object]]:
    """``[open_ms, *values]`` per bar: the opens are ints and strictly increase."""
    rows: list[list[object]] = []
    previous = -1
    for bar in bars:
        if not isinstance(bar, bar_type):
            raise ValueError(f"{label}: {bar_type.__name__} required")
        open_ms = _int(bar.open_ms, f"{label} open")
        if open_ms <= previous:
            raise ValueError(f"{label}: bar opens must be strictly increasing (at {open_ms})")
        previous = open_ms
        rows.append([open_ms, *map(_text, values(bar))])
    return rows


def _exclusions(exclusions: Mapping[str, str]) -> dict[str, str]:
    for symbol, reason in exclusions.items():
        _symbol(symbol, "exclusions")
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"exclusions {symbol}: a reason is required")
    return dict(exclusions)


def _universes(universes: Sequence[MonthlyUniverse], config: DataConfig) -> list[dict[str, Any]]:
    """One object per month; the months strictly increase (so a month appears once)."""
    documents: list[dict[str, Any]] = []
    for universe in universes:
        document = _universe(universe, config)
        # YYYY-MM strings order like the months they name
        if documents and document["month"] <= documents[-1]["month"]:
            raise ValueError(
                f"universes: months must be strictly increasing, with no duplicate "
                f"({document['month']} after {documents[-1]['month']})"
            )
        documents.append(document)
    return documents


def _universe(universe: MonthlyUniverse, config: DataConfig) -> dict[str, Any]:
    if not isinstance(universe, MonthlyUniverse):
        raise ValueError(f"universes: MonthlyUniverse required, got {universe!r}")
    _check_month(universe.month, config, "universes month")
    what = f"universe {universe.month}"
    return {
        "month": universe.month,
        "selected": list(universe.selected),
        "ranked": [
            [symbol, _text(mean), _int(bars, f"{what} ranked bars")]
            for symbol, mean, bars in universe.ranked
        ],
        "excluded": [list(pair) for pair in universe.excluded],
        "entered": list(universe.entered),
        "left": list(universe.left),
    }


def _by_series[V](entries: Mapping[tuple[str, str], V], what: str) -> dict[str, V]:
    """``entries`` keyed ``"SYMBOL|venue"`` instead of by (symbol, venue)."""
    keyed: dict[str, V] = {}
    for key, entry in entries.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError(f"{what}: a (symbol, venue) pair required, got {key!r}")
        symbol, venue = key
        _symbol(symbol, what)
        if venue not in _VENUES:
            raise ValueError(
                f"{what} {symbol}: venue must be one of {', '.join(_VENUES)}, got {venue!r}"
            )
        keyed[f"{symbol}|{venue}"] = entry
    return keyed


def _masks(masks: Mapping[str, Any], expected: set[str], config: DataConfig) -> dict[str, Any]:
    """Each series' mask as ``{"masked": [...], "unreadable": {...}}``; one per series."""
    _same_keys("masks", set(masks), expected)
    document: dict[str, Any] = {}
    for key, entry in masks.items():
        if not isinstance(entry, tuple | list) or len(entry) != 2:
            raise ValueError(f"masks {key}: (masked opens, unreadable months) required")
        opens, unreadable = entry
        masked: list[int] = []
        for open_ms in opens:
            _int(open_ms, f"masks {key} masked open")
            if masked and open_ms <= masked[-1]:
                raise ValueError(f"masks {key}: masked opens must be sorted and unique ({open_ms})")
            masked.append(open_ms)
        if not isinstance(unreadable, Mapping):
            raise ValueError(f"masks {key}: unreadable months must map a month to a reason")
        for month, reason in unreadable.items():
            _check_month(month, config, f"masks {key} unreadable month")
            if not isinstance(reason, str) or not reason:
                raise ValueError(f"masks {key}: unreadable month {month} needs a reason")
        document[key] = {"masked": masked, "unreadable": dict(unreadable)}
    return document


def _funding(
    funding: Mapping[str, Sequence[FundingRow]], futures: Mapping[str, Sequence[HourBar]]
) -> dict[str, list[list[object]]]:
    """``[time_ms, rate, interval_hours]`` per row, in the order given."""
    document: dict[str, list[list[object]]] = {}
    for symbol, rows in funding.items():
        _symbol(symbol, "funding")
        if symbol not in futures:
            raise ValueError(f"funding {symbol}: funding is for symbols that have futures")
        document[symbol] = []
        for row in rows:
            if not isinstance(row, FundingRow):
                raise ValueError(f"funding {symbol}: FundingRow required, got {row!r}")
            interval = row.interval_hours
            if interval is not None:
                _int(interval, f"funding {symbol} interval_hours (an int or null)")
            document[symbol].append(
                [_int(row.time_ms, f"funding {symbol} time"), _text(row.rate), interval]
            )
    return document


def _funding_months(
    funding_months: Mapping[tuple[str, str], str],
    futures: Mapping[str, Sequence[HourBar]],
    config: DataConfig,
) -> dict[str, str]:
    """``"SYMBOL|YYYY-MM"`` -> the month's status."""
    document: dict[str, str] = {}
    for key, status in funding_months.items():
        if not isinstance(key, tuple) or len(key) != 2:
            raise ValueError(f"funding_months: a (symbol, month) pair required, got {key!r}")
        symbol, month = key
        _symbol(symbol, "funding_months")
        _check_month(month, config, f"funding_months {symbol} month")
        if not isinstance(status, str) or status not in _FUNDING_STATUSES:
            raise ValueError(
                f"funding_months {symbol} {month}: status {status!r} is not one of "
                f"{', '.join(sorted(_FUNDING_STATUSES))}"
            )
        if symbol not in futures:
            raise ValueError(f"funding_months {symbol}: funding is for symbols that have futures")
        document[f"{symbol}|{month}"] = status
    return document


def _perpetuals(
    perpetuals: Mapping[str, Mapping[str, object]],
    spot: Mapping[str, Sequence[HourBar]],
    futures: Mapping[str, Sequence[HourBar]],
) -> dict[str, dict[str, object]]:
    """Each coin's perpetual as ``{"symbol": ..., "multiplier": ...}``: the coin is a spot
    symbol of the pack, the name is one the spec's rule gives it, no perpetual is two coins',
    and the perpetuals are exactly the futures series (a perpetual left out of the pack leaves
    out its entry)."""
    if not isinstance(perpetuals, Mapping):
        raise ValueError("perpetuals: a mapping of spot symbol -> {symbol, multiplier} required")
    document: dict[str, dict[str, object]] = {}
    owners: dict[str, str] = {}  # perpetual -> the coin it was first mapped from
    for coin, entry in perpetuals.items():
        _symbol(coin, "perpetuals")
        if coin not in spot:
            raise ValueError(f"perpetuals: {coin} is not a spot symbol of the pack")
        try:
            symbol, multiplier = checked_perpetual(coin, entry)
        except ValueError as exc:
            raise ValueError(f"perpetuals: {exc}") from exc
        if symbol in owners:  # the set comparison below would hide the second coin
            both = " and ".join(sorted((owners[symbol], coin)))
            raise ValueError(f"perpetuals: {symbol} is the perpetual of both {both}")
        owners[symbol] = coin
        document[coin] = {"symbol": symbol, "multiplier": multiplier}
    held = set(owners)
    if held != set(futures):
        raise ValueError(
            f"perpetuals: futures series without a perpetual entry: "
            f"{sorted(set(futures) - held)}; perpetual entries without a futures series: "
            f"{sorted(held - set(futures))}"
        )
    return document


def _rules(
    rules: Mapping[str, tuple[VenueRules, str]], expected: set[str]
) -> dict[str, dict[str, str]]:
    """Each series' rules as ``{"source": ..., "step": ..., ...}``; one per series."""
    _same_keys("rules", set(rules), expected)
    document: dict[str, dict[str, str]] = {}
    for key, entry in rules.items():
        if not isinstance(entry, tuple | list) or len(entry) != 2:
            raise ValueError(f"rules {key}: (VenueRules, source) required")
        venue_rules, source = entry
        if not isinstance(venue_rules, VenueRules):
            raise ValueError(f"rules {key}: VenueRules required, got {venue_rules!r}")
        if source not in _SOURCES:
            raise ValueError(
                f"rules {key}: source must be one of {', '.join(_SOURCES)}, got {source!r}"
            )
        document[key] = {
            "source": source,
            **{name: _text(getattr(venue_rules, name)) for name in _RULE_FIELDS},
        }
    return document
