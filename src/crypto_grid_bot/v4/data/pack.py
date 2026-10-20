"""The V4 data packs: canonical gzip JSON, pinned by the SHA-256 of the JSON text.

What the engine replays is the daily pack (spot daily bars, the universe), one coin pack per
coin ever selected (its spot hourly bars and, if it has one, its USDT-M perpetual's hourly bars,
funding and funding months, with the masks and order rules of each series), and the hourly
index, which pins every coin pack (ruling P32: no step holds every coin's whole history at
once). Each is one JSON object, written canonically (sorted keys, separators ``(",", ":")``,
ASCII, no NaN), gzipped with mtime 0 and no file name, and pinned by the SHA-256 of that JSON,
not of the gzip bytes: the same document has the same pin on any machine, while the gzip around
it may differ between zlib builds. This is the ``combined/driver/packs.py`` convention, restated
here because that module also carries the 2024 guard. ``write_canonical`` refuses an existing
file, a document the reader would not hand back unchanged (a float, a non-string key, a tuple)
and never leaves a partial file at the final path (it links a finished temporary file into
place); ``read_canonical`` refuses a wrong pin, a duplicate key, a float, NaN or Infinity, a
document that is not an object, and anything that decompresses to more than 2 GiB, hashing
the JSON as it decompresses. Pure file I/O: nothing here touches the network.

Every Decimal is written as its ``str()`` (ruling P21), under a fresh default context: the CSV's
own text, ``"0.09865000"``, and ``"1E-7"`` for a small inferred tick. ``Decimal(text)`` rebuilds
the same Decimal, exponent included. Timestamps are plain ints (ms), and ``interval_hours`` is an
int or null. The reader hands rows back as written, strings and ints.

Every document holds ``format``, ``config_sha256`` (the SHA-256 of the raw bytes of
``config/v4_data.json``, which the caller computes; it is why ``.gitattributes`` keeps that file
LF) and ``end_month``. The daily pack and each coin pack also hold ``manifest``, every archive
the pack was built from as ``{kind, symbol, month, path, sha256, bytes}``, sorted by (kind,
symbol, month). The rest, by document:

* daily (``"v4-daily-pack/1"``): ``daily`` (symbol -> rows ``[open_ms, open, high, low, close,
  quote_volume]``), ``exclusions`` (symbol -> reason; a name ``archive_path`` cannot address,
  such as 币安人生USDT, is ``"unsupported_name"``, ruling P33), ``masks`` (by symbol) and
  ``universes`` (one object per month with the fields of ``MonthlyUniverse``; a ``ranked``
  entry is ``[symbol, mean quote volume, bars]``);
* coin (``"v4-coin-pack/1"``, the file ``coin_pack_file(coin)``): ``coin`` (its spot symbol),
  ``perpetual`` (``{"symbol": perpetual, "multiplier": int}``, or null), ``spot`` and
  ``futures`` (rows ``[open_ms, open, high, low, close, volume, quote_volume]``; ``futures`` is
  empty without a perpetual), ``funding`` (rows ``[time_ms, rate, interval_hours]``),
  ``funding_months`` (``"YYYY-MM"`` -> ``"complete"``, a failure reason of
  ``funding_month_status``, ``"missing_file"`` or ``"unreadable_file"``), and ``masks`` and
  ``rules`` by venue (``"spot"``, and ``"futures"`` with a perpetual; a rule is ``{source, step,
  min_qty, max_qty, min_notional, tick}`` with ``source`` ``"present_day"`` or ``"inferred"``).
  The futures series, funding and futures rules are the perpetual's own, named by its symbol
  (the name of its archives), which for a multiplier contract is not the coin's: 1000SHIBUSDT
  is SHIBUSDT's perpetual, one unit 1000 SHIB, its prices and filters in those units;
* hourly index (``"v4-hourly-index/1"``): ``coins`` (coin -> ``{file, sha256, json_bytes}`` of
  its coin pack) and ``perpetuals`` (coin -> ``{"symbol", "multiplier"}``, for each coin whose
  pack has a perpetual).

``masks`` maps each series to ``{"masked": [sorted unique interval opens, ms], "unreadable":
{"YYYY-MM": reason}, "absent": [sorted unique "YYYY-MM"]}``. The caller passes the intervals
inside each month only (ruling P12), with every interval of an unreadable month included, and as
``absent`` the months the archive listing named but the host answered 404, carried from the
manifest pieces' ``absent``; a month is never both unreadable and absent. Every series of a pack
has a mask entry, empty for a clean one, so a missing entry is an error, never "clean"; every
hourly series also has its rules. Months are never after ``end_month``.

The contract with the engine (step 3), for every series:

* the rows include masked bars: a repaired row and the one copy of a duplicated open that the
  reader keeps are in the rows and in ``masked``. The engine drops every masked open;
* an interval missing between a series' first and last bar is masked by the spec but not
  listed in ``masked``: the engine treats an open with no row as masked;
* a month whose archive was listed but answered 404 is in ``absent``, and one that could not be
  read is in ``unreadable`` with every interval of it in ``masked``.

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
from crypto_grid_bot.v4.data.listing import (
    UNSUPPORTED_NAME,
    checked_perpetual,
    is_unsupported_usdt_name,
    perpetual_names,
)
from crypto_grid_bot.v4.data.universe import MonthlyUniverse

DAILY_FORMAT = "v4-daily-pack/1"
COIN_FORMAT = "v4-coin-pack/1"
INDEX_FORMAT = "v4-hourly-index/1"
MAX_CONTENT_BYTES = 2 * 1024**3  # read_canonical refuses a pack that decompresses to more
_CHUNK = 1 << 20

_SHA256 = re.compile(r"[0-9a-f]{64}")
# The symbol shape archives.py lets through; it holds no "|", which joins the keys below.
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")
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

# A series' mask: (masked opens, unreadable months -> reason, absent months).
Mask = tuple[Sequence[int], Mapping[str, str], Sequence[str]]
DailyMasks = Mapping[str, Mask]  # symbol -> mask
CoinMasks = Mapping[str, Mask]  # venue -> mask
CoinRules = Mapping[str, tuple[VenueRules, str]]  # venue -> (rules, source)


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

    The file is decompressed with a cap of ``MAX_CONTENT_BYTES`` into one buffer, its JSON
    hashed chunk by chunk as it comes, and the pin checked before anything is parsed; any gzip
    bytes of that JSON are accepted. The buffer is released once decoded, so the peak is the
    JSON's bytes and its text, never a list of chunks beside a joined copy. A duplicate key, a
    float, NaN or Infinity, non-ASCII text, malformed JSON or a top level that is not an object
    is refused.
    """
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(expected_sha256) is None:
        raise ValueError("the expected pack sha256 must be 64 lowercase hex digits")
    content, actual = _decompressed(path)
    if actual != expected_sha256:
        raise ValueError(f"{path}: pack sha256 {actual} differs from the pinned {expected_sha256}")
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: a pack is ASCII JSON ({exc})") from exc
    del content  # the parser needs only the text
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


def coin_pack_file(coin: str) -> str:
    """The file name of ``coin``'s pack: ``v4-coin-<SYMBOL>.json.gz``."""
    return f"v4-coin-{_symbol(coin, 'coin')}.json.gz"


def coin_pack_document(
    config: DataConfig,
    manifest: Sequence[ManifestEntry],
    *,
    coin: str,
    spot: Sequence[HourBar],
    perpetual: Mapping[str, object] | None,
    futures: Sequence[HourBar],
    masks: CoinMasks,
    funding: Sequence[FundingRow],
    funding_months: Mapping[str, str],
    rules: CoinRules,
    config_sha256: str,
) -> dict[str, Any]:
    """One coin's hourly pack (``"v4-coin-pack/1"``; the module docstring has the layout).

    ``coin`` is the spot symbol and ``spot`` its bars. ``perpetual`` is the coin's perpetual,
    ``{"symbol": ..., "multiplier": ...}``, a name the spec's rule gives the coin
    (``listing.checked_perpetual``), or None; without one, ``futures``, ``funding`` and
    ``funding_months`` are empty. With one, ``futures`` holds at least one bar (a perpetual with
    none is left out, entry and all: ruling P23), ``funding`` its rows and ``funding_months``
    month -> status for each month of its kline span. ``masks`` and ``rules`` are keyed by venue:
    ``"spot"`` and, with a perpetual, ``"futures"``. ``manifest`` lists exactly the archives
    read for the pack: the coin's ``spot_1h`` ones, the ``futures_1h`` ones of one name
    ``perpetual_for`` considers for the coin (the perpetual's if there is one; one left out by
    P23 was still read) and, with a perpetual, its ``funding`` ones.
    """
    with localcontext(Context()):  # str() reads the context's exponent letter case
        header = _header(config, config_sha256, manifest)
        _symbol(coin, "coin")
        entry: dict[str, object] | None = None
        if perpetual is None:
            if futures or funding or funding_months:
                raise ValueError(
                    f"coin {coin}: futures, funding and funding months need a perpetual"
                )
        else:
            try:
                symbol, multiplier = checked_perpetual(coin, perpetual)
            except ValueError as exc:
                raise ValueError(f"coin {coin}: {exc}") from exc
            if not futures:
                raise ValueError(
                    f"coin {coin}: a perpetual with no futures bar is left out, entry and all "
                    "(ruling P23)"
                )
            entry = {"symbol": symbol, "multiplier": multiplier}
        name = None if entry is None else str(entry["symbol"])
        _coin_manifest(header["manifest"], coin, name)
        venues = {"spot"} if entry is None else {"spot", "futures"}
        return {
            "format": COIN_FORMAT,
            **header,
            "coin": coin,
            "perpetual": entry,
            "spot": _bar_rows(f"spot {coin}", spot, HourBar, _HOURLY_VALUES),
            "futures": _bar_rows(f"futures {name}", futures, HourBar, _HOURLY_VALUES),
            "masks": _masks(masks, venues, config),
            "funding": _funding_rows(funding, f"funding {name}"),
            "funding_months": _funding_months(funding_months, config),
            "rules": _rules(rules, venues),
        }


def hourly_index_document(
    config: DataConfig,
    *,
    coins: Mapping[str, tuple[str, str, int]],
    perpetuals: Mapping[str, Mapping[str, object]],
    config_sha256: str,
) -> dict[str, Any]:
    """The hourly index (``"v4-hourly-index/1"``; the module docstring has the layout).

    ``coins`` maps each coin to its pack as written: (the pin ``write_canonical`` returned, the
    file name ``coin_pack_file(coin)``, the bytes of its canonical JSON). ``perpetuals`` maps a
    coin of ``coins`` whose pack has a perpetual to it, ``{"symbol", "multiplier"}``, by the
    spec's rule, no perpetual being two coins'. ``end_month`` is the config's.
    """
    if not isinstance(coins, Mapping):
        raise ValueError("coins: a mapping of coin -> (sha256, file, json bytes) required")
    pinned: dict[str, dict[str, object]] = {}
    for coin, record in coins.items():
        _symbol(coin, "coins")
        if not isinstance(record, tuple | list) or len(record) != 3:
            raise ValueError(f"coins {coin}: (sha256, file, json bytes) required")
        pin, file, size = record
        if not isinstance(pin, str) or _SHA256.fullmatch(pin) is None:
            raise ValueError(f"coins {coin}: sha256 must be 64 lowercase hex digits")
        if file != coin_pack_file(coin):
            raise ValueError(f"coins {coin}: the file must be {coin_pack_file(coin)}, got {file!r}")
        if _int(size, f"coins {coin} json bytes") < 0:
            raise ValueError(f"coins {coin}: json bytes must not be negative")
        pinned[coin] = {"file": file, "sha256": pin, "json_bytes": size}
    return {
        "format": INDEX_FORMAT,
        **_pins(config, config_sha256),
        "coins": pinned,
        "perpetuals": _perpetuals(perpetuals, pinned),
    }


def _decompressed(path: Path) -> tuple[bytearray, str]:
    """The bytes the gzip file at ``path`` holds, and their SHA-256 (hex), hashed chunk by
    chunk as they are decompressed into one growing buffer. At most ``MAX_CONTENT_BYTES`` + 1
    are ever decompressed, so an oversized stream is refused without exhausting memory; the
    compressed file is streamed, not read whole. A missing file is the ``OSError`` of opening
    it; a file that is not a whole gzip stream is a ``ValueError``."""
    cap = MAX_CONTENT_BYTES
    content = bytearray()
    digest = hashlib.sha256()
    with Path(path).open("rb") as compressed:
        try:
            with gzip.GzipFile(fileobj=compressed, mode="rb") as archive:
                while chunk := archive.read(min(_CHUNK, cap + 1 - len(content))):
                    if len(content) + len(chunk) > cap:
                        raise ValueError(f"{path}: the pack decompresses to more than {cap} bytes")
                    digest.update(chunk)
                    content += chunk
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError(f"{path}: not a readable gzip pack ({exc})") from exc
    return content, digest.hexdigest()


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


def _pins(config: DataConfig, config_sha256: str) -> dict[str, Any]:
    refuse_after_end(config.end_month, config)  # the config's own end month is a month
    if not isinstance(config_sha256, str) or _SHA256.fullmatch(config_sha256) is None:
        raise ValueError("config_sha256 must be 64 lowercase hex digits")
    return {"config_sha256": config_sha256, "end_month": config.end_month}


def _header(
    config: DataConfig, config_sha256: str, manifest: Sequence[ManifestEntry]
) -> dict[str, Any]:
    return {**_pins(config, config_sha256), "manifest": _manifest(manifest, config)}


def _coin_manifest(manifest: Sequence[Mapping[str, Any]], coin: str, perpetual: str | None) -> None:
    """Refuse an entry that is not one of this coin pack's archives: the coin's ``spot_1h``,
    the ``futures_1h`` of one name (the perpetual's, or without one any name ``perpetual_for``
    considers for the coin, read before P23 left it out) and the perpetual's ``funding``."""
    considered = set(perpetual_names(coin)) if perpetual is None else {perpetual}
    futures: set[str] = set()
    for item in manifest:
        kind, symbol = item["kind"], item["symbol"]
        if kind == "futures_1h" and symbol in considered:
            futures.add(symbol)
        elif not (
            (kind == "spot_1h" and symbol == coin)
            or (kind == "funding" and perpetual is not None and symbol == perpetual)
        ):
            raise ValueError(
                f"coin {coin}: the manifest entry {kind} {symbol} {item['month']} is not one of "
                "its archives"
            )
    if len(futures) > 1:
        raise ValueError(f"coin {coin}: futures archives of more than one name {sorted(futures)}")


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
    """Symbol -> reason; a name with the reason ``"unsupported_name"`` is one ``archive_path``
    cannot address (ruling P33), such as 币安人生USDT, which the ASCII JSON escapes."""
    for symbol, reason in exclusions.items():
        if not isinstance(reason, str) or not reason:
            raise ValueError(f"exclusions {symbol!r:.40}: a reason is required")
        if reason != UNSUPPORTED_NAME:
            _symbol(symbol, "exclusions")
        elif not is_unsupported_usdt_name(symbol):
            raise ValueError(f"exclusions: {symbol!r:.40} is not an unsupported USDT name")
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


def _masks(masks: Mapping[str, Any], expected: set[str], config: DataConfig) -> dict[str, Any]:
    """Each series' mask as ``{"masked": [...], "unreadable": {...}, "absent": [...]}``; one
    per series, keyed by symbol (daily) or venue (coin)."""
    _same_keys("masks", set(masks), expected)
    document: dict[str, Any] = {}
    for key, entry in masks.items():
        if not isinstance(entry, tuple | list) or len(entry) != 3:
            raise ValueError(
                f"masks {key}: (masked opens, unreadable months, absent months) required"
            )
        opens, unreadable, absent = entry
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
        if isinstance(absent, str) or not isinstance(absent, Sequence):
            raise ValueError(f"masks {key}: absent months must be a list of months")
        for month in absent:
            _check_month(month, config, f"masks {key} absent month")
        if list(absent) != sorted(set(absent)):
            raise ValueError(f"masks {key}: absent months must be sorted and unique")
        if set(absent) & set(unreadable):
            raise ValueError(f"masks {key}: a month cannot be both absent and unreadable")
        document[key] = {"masked": masked, "unreadable": dict(unreadable), "absent": list(absent)}
    return document


def _funding_rows(rows: Sequence[FundingRow], what: str) -> list[list[object]]:
    """``[time_ms, rate, interval_hours]`` per row, in the order given."""
    document: list[list[object]] = []
    for row in rows:
        if not isinstance(row, FundingRow):
            raise ValueError(f"{what}: FundingRow required, got {row!r}")
        interval = row.interval_hours
        if interval is not None:
            _int(interval, f"{what} interval_hours (an int or null)")
        document.append([_int(row.time_ms, f"{what} time"), _text(row.rate), interval])
    return document


def _funding_months(funding_months: Mapping[str, str], config: DataConfig) -> dict[str, str]:
    """``"YYYY-MM"`` -> the month's status."""
    document: dict[str, str] = {}
    for month, status in funding_months.items():
        if not isinstance(month, str):
            raise ValueError(f"funding_months: a YYYY-MM month required, got {month!r}")
        _check_month(month, config, "funding_months month")
        if not isinstance(status, str) or status not in _FUNDING_STATUSES:
            raise ValueError(
                f"funding_months {month}: status {status!r} is not one of "
                f"{', '.join(sorted(_FUNDING_STATUSES))}"
            )
        document[month] = status
    return document


def _perpetuals(
    perpetuals: Mapping[str, Mapping[str, object]], coins: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    """Each coin's perpetual as ``{"symbol": ..., "multiplier": ...}``: the coin is one of
    ``coins``, the name is one the spec's rule gives it, and no perpetual is two coins'."""
    if not isinstance(perpetuals, Mapping):
        raise ValueError("perpetuals: a mapping of coin -> {symbol, multiplier} required")
    document: dict[str, dict[str, object]] = {}
    owners: dict[str, str] = {}  # perpetual -> the coin it was first mapped from
    for coin, entry in perpetuals.items():
        _symbol(coin, "perpetuals")
        if coin not in coins:
            raise ValueError(f"perpetuals: {coin} is not a coin of the index")
        try:
            symbol, multiplier = checked_perpetual(coin, entry)
        except ValueError as exc:
            raise ValueError(f"perpetuals: {exc}") from exc
        if symbol in owners:
            both = " and ".join(sorted((owners[symbol], coin)))
            raise ValueError(f"perpetuals: {symbol} is the perpetual of both {both}")
        owners[symbol] = coin
        document[coin] = {"symbol": symbol, "multiplier": multiplier}
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
