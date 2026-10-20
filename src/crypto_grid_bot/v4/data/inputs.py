"""The V4 data CLI's input loading, for ``scripts/v4_data.py``.

The discovery (``symbols.json``: candidates, exclusions, each candidate's perpetual and the
futures symbols it was chosen from, the months per kind), the manifest pieces, the archives
(from the cache, or fetched again by their pin), the series read from them, the funding months,
the usable hours and the universes. Split out of the script (ruling P28), which keeps the
stages, the argument parser and ``main``; the script's docstring states the rules applied here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeGuard

from crypto_grid_bot.backtest.klines import INTERVAL_MS, month_bounds_ms
from crypto_grid_bot.v4.data.archives import (
    KINDS,
    ManifestEntry,
    Transport,
    archive_path,
    fetch_pinned,
)
from crypto_grid_bot.v4.data.bars import (
    DailyBar,
    FundingRow,
    HourBar,
    KlineRead,
    funding_month_status,
    read_daily,
    read_funding,
    read_hourly,
)
from crypto_grid_bot.v4.data.config import DataConfig, months, refuse_after_end
from crypto_grid_bot.v4.data.listing import (
    UNSUPPORTED_NAME,
    checked_perpetual,
    is_unsupported_usdt_name,
    perpetual_for,
)
from crypto_grid_bot.v4.data.universe import (
    HOURLY_RANK_DEPTH,
    MonthlyUniverse,
    select_universe,
    static_exclusion,
)

DISCOVERY_FORMAT = "v4-symbols/1"
MANIFEST_FORMAT = "v4-manifest/1"
UNIVERSE_FORMAT = "v4-universe/1"
# The kinds whose archives are under a coin's perpetual's symbol, not its spot symbol.
FUTURES_KINDS = ("futures_1h", "funding")

_HOUR_MS = INTERVAL_MS["1h"]
_DAY_MS = INTERVAL_MS["1d"]
_SHARD = re.compile(r"(0|[1-9][0-9]*)/([1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENTRY_FIELDS = frozenset(field.name for field in fields(ManifestEntry))


@dataclass(frozen=True)
class _Run:
    """What every stage shares: the config, its pin, the network and the clock (UTC-aware)."""

    config: DataConfig
    config_sha256: str
    transport: Transport
    sleep: Callable[[float], None]
    clock: Callable[[], datetime]


@dataclass(frozen=True)
class _Discovery:
    """``symbols.json``: every discovered symbol, the candidates, the exclusions, the months,
    and each candidate's perpetual with its multiplier (for those that have one). The months of
    a futures kind are keyed by the perpetual's symbol."""

    symbols: tuple[str, ...]
    candidates: tuple[str, ...]
    exclusions: dict[str, str]
    months: dict[str, dict[str, tuple[str, ...]]]
    perpetuals: dict[str, tuple[str, int]]


@dataclass(frozen=True)
class _Manifests:
    """A complete set of manifest pieces: the entries, and the symbols each kind's pieces cover."""

    entries: list[ManifestEntry]
    covered: dict[str, frozenset[str]]


@dataclass(frozen=True)
class _Series[B: (DailyBar, HourBar)]:
    """One symbol's bars of one kind, as read, with its in-month masks and unreadable months."""

    bars: tuple[B, ...]
    masked: frozenset[int]
    unreadable: dict[str, str]

    def unmasked(self) -> list[B]:
        return [bar for bar in self.bars if bar.open_ms not in self.masked]

    def masks(self) -> tuple[list[int], dict[str, str]]:
        return sorted(self.masked), dict(self.unreadable)


def _log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_shard(text: str) -> tuple[int, int]:
    """``"i/n"`` as (i, n), with 0 <= i < n."""
    match = _SHARD.fullmatch(text)
    if match is None or int(match.group(1)) >= int(match.group(2)):
        raise ValueError(f"--shard must be i/n with 0 <= i < n, got {text!r}")
    return int(match.group(1)), int(match.group(2))


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: a JSON object is required")
    return document


def _store(target: Path, content: bytes) -> None:
    """``content`` to ``target`` atomically: a temporary file beside it, then a rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=target.parent, prefix=f"{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.replace(name, target)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def _sorted_strings(value: object) -> TypeGuard[list[str]]:
    """Whether ``value`` is a list of strings, sorted and without duplicates."""
    return (
        isinstance(value, list)
        and all(isinstance(item, str) for item in value)
        and value == sorted(set(value))
    )


def _static_exclusions(symbols: Sequence[str], config: DataConfig) -> dict[str, str]:
    bases = frozenset(symbol.removesuffix("USDT") for symbol in symbols)
    reasons = {symbol: static_exclusion(symbol, bases, config) for symbol in symbols}
    return {symbol: reason for symbol, reason in reasons.items() if reason is not None}


def _archive_symbols(
    kind: str, symbols: Iterable[str], perpetuals: Mapping[str, tuple[str, int]]
) -> list[str]:
    """The symbols ``kind``'s archives of these candidates are under: their own for a spot
    kind; for a futures kind their perpetuals', a candidate without one having none."""
    if kind not in FUTURES_KINDS:
        return list(symbols)
    return [perpetuals[symbol][0] for symbol in symbols if symbol in perpetuals]


def _unshared(perpetuals: Mapping[str, tuple[str, int]]) -> None:
    """Refuse a perpetual that is two candidates' (say SHIBUSDT x1000 and a spot 1000SHIBUSDT
    x1): the futures pieces hold each perpetual's archives once, under one candidate."""
    owners: dict[str, list[str]] = {}
    for symbol, (perpetual, _) in sorted(perpetuals.items()):
        owners.setdefault(perpetual, []).append(symbol)
    for perpetual, symbols in sorted(owners.items()):
        if len(symbols) > 1:
            raise ValueError(
                f"{perpetual} is the perpetual of both {' and '.join(symbols)}: one perpetual "
                "for two coins needs a ruling"
            )


def _perpetuals_from(
    candidates: Iterable[str], futures_symbols: Iterable[str]
) -> dict[str, tuple[str, int]]:
    """Each candidate's perpetual among ``futures_symbols`` (those with a monthly archive at or
    before ``end_month``, ruling P34), for the candidates that have one."""
    listed = frozenset(futures_symbols)
    found = {symbol: perpetual_for(symbol, listed) for symbol in candidates}
    return {symbol: perpetual for symbol, perpetual in found.items() if perpetual is not None}


def _load_perpetuals(
    path: Path, document: Mapping[str, Any], candidates: Sequence[str]
) -> dict[str, tuple[str, int]]:
    """``symbols.json``'s ``perpetuals``: candidate -> ``{"symbol", "multiplier"}``, each a
    name the spec's rule gives the candidate (``checked_perpetual``), no two sharing one, and
    exactly what ``perpetual_for`` gives the candidates from the recorded ``futures_symbols``
    (ruling P34)."""
    raw, futures_symbols = document.get("perpetuals"), document.get("futures_symbols")
    if not isinstance(raw, dict) or not set(raw) <= set(candidates):
        raise ValueError(f"{path}: perpetuals must map candidates to their perpetuals")
    if not _sorted_strings(futures_symbols):
        raise ValueError(f"{path}: futures_symbols must be a sorted list without duplicates")
    perpetuals: dict[str, tuple[str, int]] = {}
    for symbol in sorted(raw):
        try:
            perpetuals[symbol] = checked_perpetual(symbol, raw[symbol])
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
    try:
        _unshared(perpetuals)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    expected = _perpetuals_from(candidates, futures_symbols)
    if perpetuals != expected:
        wrong = sorted(set(perpetuals.items()) ^ set(expected.items()))
        raise ValueError(
            f"{path}: the perpetuals do not follow from futures_symbols (ruling P34): {wrong}"
        )
    return perpetuals


def _load_exclusions(
    path: Path, raw: object, symbols: Sequence[str], config: DataConfig
) -> dict[str, str]:
    """``symbols.json``'s ``exclusions``: the static exclusions of the symbols as the config
    gives them, and each unsupported name with ``UNSUPPORTED_NAME`` (ruling P33), a name that is
    not one of the symbols and that ``archive_path`` cannot address."""
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: exclusions must map a name to a reason")
    unsupported = {name for name, reason in raw.items() if reason == UNSUPPORTED_NAME}
    for name in sorted(unsupported, key=repr):
        if not is_unsupported_usdt_name(name) or name in symbols:
            raise ValueError(f"{path}: {name!r:.40} is not an unsupported USDT name")
    expected = _static_exclusions(symbols, config) | dict.fromkeys(unsupported, UNSUPPORTED_NAME)
    if raw != expected:
        raise ValueError(f"{path}: the exclusions and candidates do not follow from the config")
    return expected


def _load_discovery(path: Path, config: DataConfig) -> _Discovery:
    """``symbols.json``, refused unless it is this config's: its end month, its exclusions
    and candidates as the config gives them (unsupported names excluded, ruling P33),
    perpetuals the spec's rule gives the candidates from the recorded futures symbols (P34),
    the months of each kind for exactly the candidates (a futures kind: their perpetuals, each
    with a ``futures_1h`` month), and no month after ``end_month``."""
    document = _read_json(path)
    if document.get("format") != DISCOVERY_FORMAT:
        raise ValueError(f"{path}: not a {DISCOVERY_FORMAT} document")
    if document.get("end_month") != config.end_month:
        raise ValueError(f"{path}: discovered up to {document.get('end_month')!r}, not end_month")
    symbols = document.get("symbols")
    if not _sorted_strings(symbols):
        raise ValueError(f"{path}: symbols must be a sorted list without duplicates")
    exclusions = _load_exclusions(path, document.get("exclusions"), symbols, config)
    candidates = [symbol for symbol in symbols if symbol not in exclusions]
    if document.get("candidates") != candidates:
        raise ValueError(f"{path}: the exclusions and candidates do not follow from the config")
    perpetuals = _load_perpetuals(path, document, candidates)
    listed = document.get("months")
    if not isinstance(listed, dict) or set(listed) != set(KINDS):
        raise ValueError(f"{path}: months must hold exactly the kinds {', '.join(KINDS)}")
    found: dict[str, dict[str, tuple[str, ...]]] = {}
    for kind in KINDS:
        per_symbol = listed[kind]
        names = _archive_symbols(kind, candidates, perpetuals)
        if not isinstance(per_symbol, dict) or set(per_symbol) != set(names):
            whose = "candidates' perpetuals" if kind in FUTURES_KINDS else "candidates"
            raise ValueError(f"{path}: months[{kind}] must name exactly the {whose}")
        for symbol, values in per_symbol.items():
            if not _sorted_strings(values):
                raise ValueError(f"{path}: months[{kind}][{symbol}] must be sorted and unique")
            for month in values:
                refuse_after_end(month, config)
        found[kind] = {symbol: tuple(values) for symbol, values in per_symbol.items()}
    for perpetual, _ in perpetuals.values():
        if not found["futures_1h"][perpetual]:
            raise ValueError(
                f"{path}: {perpetual} has no futures_1h month, so it is no perpetual (ruling P34)"
            )
    return _Discovery(tuple(symbols), tuple(candidates), exclusions, found, perpetuals)


def _entry(path: Path, kind: str, raw: object, config: DataConfig) -> ManifestEntry:
    """One manifest entry: the ``kind`` archive of its symbol and month, at its own path, for
    a month not after ``end_month`` (ruling P7), with a well-formed pin."""
    if not isinstance(raw, dict) or set(raw) != _ENTRY_FIELDS:
        raise ValueError(f"{path}: an entry must hold exactly {sorted(_ENTRY_FIELDS)}")
    entry = ManifestEntry(**raw)
    label = f"{path}: {entry.path!r}"
    if entry.kind != kind or archive_path(kind, entry.symbol, entry.month) != entry.path:
        raise ValueError(f"{label} is not the {kind} archive of its symbol and month")
    try:
        refuse_after_end(entry.month, config)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc
    if not isinstance(entry.sha256, str) or _SHA256.fullmatch(entry.sha256) is None:
        raise ValueError(f"{label}: sha256 must be 64 lowercase hex digits")
    if type(entry.bytes) is not int or entry.bytes < 0:
        raise ValueError(f"{label}: bytes must be a non-negative int")
    return entry


def _absent(path: Path, item: object, config: DataConfig) -> tuple[str, str]:
    """One absent month, ``{"symbol": str, "month": "YYYY-MM"}`` with a month not after
    ``end_month``, as (symbol, month); any other shape is a ``ValueError``."""
    if (
        not isinstance(item, dict)
        or set(item) != {"symbol", "month"}
        or not isinstance(item["symbol"], str)
        or not isinstance(item["month"], str)
    ):
        raise ValueError(
            f"{path}: an absent month must be {{symbol, month}}, both strings, got {item!r:.80}"
        )
    try:
        refuse_after_end(item["month"], config)
    except ValueError as exc:
        raise ValueError(f"{path}: absent {item['symbol']} {item['month']!r}: {exc}") from exc
    return item["symbol"], item["month"]


def _load_piece(
    path: Path,
    kinds: Sequence[str],
    config: DataConfig,
    discovery: _Discovery,
    found: dict[tuple[str, str, str], ManifestEntry],
    shards: dict[str, dict[int, tuple[int, tuple[str, ...]]]],
) -> None:
    """One piece: its shard and symbols go into ``shards``, its entries into ``found``.

    Its shard count is that of the kind's other pieces and no other piece holds its shard
    (checked first, the likeliest cause of any later mismatch); its symbols are sorted, unique
    candidates, every entry and absent month is for one of them (for a futures kind, for one of
    their perpetuals, under the perpetual's symbol), no archive is listed twice, and each
    symbol's (or perpetual's) entries and absent months are exactly its discovered months of
    the kind.
    """
    piece = _read_json(path)
    kind, shard, symbols = piece.get("kind"), piece.get("shard"), piece.get("symbols")
    if (
        piece.get("format") != MANIFEST_FORMAT
        or not isinstance(kind, str)
        or kind not in kinds
        or not isinstance(shard, str)
    ):
        raise ValueError(f"{path}: not a {MANIFEST_FORMAT} piece of {', '.join(kinds)}")
    index, count = parse_shard(shard)
    pieces = shards[kind]
    counts = {other for other, _ in pieces.values()} | {count}
    if len(counts) > 1:
        raise ValueError(f"{path}: the {kind} pieces mix shard counts {sorted(counts)}")
    if index in pieces:
        raise ValueError(f"{path}: a second {kind} piece for shard {index}/{count}")
    if not _sorted_strings(symbols) or not set(symbols) <= set(discovery.candidates):
        raise ValueError(f"{path}: symbols must be sorted, unique candidates of the discovery")
    raw_entries, absent = piece.get("entries"), piece.get("absent")
    if not isinstance(raw_entries, list) or not isinstance(absent, list):
        raise ValueError(f"{path}: entries and absent must be lists")
    names = _archive_symbols(kind, symbols, discovery.perpetuals)
    held: dict[str, list[str]] = {name: [] for name in names}
    for raw in raw_entries:
        entry = _entry(path, kind, raw, config)
        key = (entry.kind, entry.symbol, entry.month)
        if entry.symbol not in held or key in found:
            raise ValueError(f"{path}: {entry.path!r} is outside the piece's symbols or twice")
        found[key] = entry
        held[entry.symbol].append(entry.month)
    for item in absent:
        symbol, month = _absent(path, item, config)
        if symbol not in held:
            raise ValueError(f"{path}: absent {symbol!r} is outside the piece's symbols")
        held[symbol].append(month)
    for symbol, held_months in held.items():
        discovered = discovery.months[kind][symbol]
        if len(held_months) != len(set(held_months)) or sorted(held_months) != list(discovered):
            raise ValueError(
                f"{path}: {symbol}'s {kind} entries and absent months are not its discovered "
                f"months: missing {sorted(set(discovered) - set(held_months))}, unexpected "
                f"{sorted(set(held_months) - set(discovered))}"
            )
    pieces[index] = (count, tuple(symbols))


def _load_manifests(
    paths: Sequence[Path], kinds: Sequence[str], config: DataConfig, discovery: _Discovery
) -> _Manifests:
    """The entries of the manifest pieces, sorted by (kind, symbol, month), once every piece
    passes ``_load_piece`` and the pieces are complete; all before any request or read.

    Every one of ``kinds`` needs pieces, and only those kinds are accepted. A kind's pieces are
    shards 0 to n-1 of one n, and piece i holds symbols i, i+n, i+2n, ... of their sorted
    union, as ``fetch`` shards them. A missing shard, two shard counts, a second piece for a
    shard or a piece that holds another shard's symbols is refused.
    """
    found: dict[tuple[str, str, str], ManifestEntry] = {}
    shards: dict[str, dict[int, tuple[int, tuple[str, ...]]]] = {kind: {} for kind in kinds}
    for path in paths:
        _load_piece(path, kinds, config, discovery, found, shards)
    covered: dict[str, frozenset[str]] = {}
    for kind, pieces in shards.items():
        if not pieces:
            raise ValueError(f"no {kind} manifest piece was given")
        count = next(iter(pieces.values()))[0]
        missing = [f"{index}/{count}" for index in range(count) if index not in pieces]
        if missing:
            raise ValueError(f"the {kind} manifest pieces lack shard {', '.join(missing)}")
        union = sorted({symbol for _, symbols in pieces.values() for symbol in symbols})
        for index, (_, symbols) in sorted(pieces.items()):
            if list(symbols) != union[index::count]:
                raise ValueError(f"the {kind} piece {index}/{count} does not hold that shard")
        covered[kind] = frozenset(union)
    return _Manifests([found[key] for key in sorted(found)], covered)


def _require_coverage(manifests: _Manifests, kind: str, expected: Iterable[str], what: str) -> None:
    """Refuse ``kind``'s pieces unless they cover exactly the ``expected`` symbols."""
    covered, wanted = manifests.covered[kind], frozenset(expected)
    if covered != wanted:
        raise ValueError(
            f"the {kind} manifest pieces cover {len(covered)} symbols, not the {len(wanted)} "
            f"{what}: missing {sorted(wanted - covered)}, unexpected {sorted(covered - wanted)}"
        )


def _ranked(universes: Iterable[MonthlyUniverse]) -> list[str]:
    """Every symbol ranked in a top ``HOURLY_RANK_DEPTH`` in any month, sorted."""
    return sorted({s for u in universes for s, _, _ in u.ranked[:HOURLY_RANK_DEPTH]})


def _grouped(entries: Iterable[ManifestEntry], kind: str) -> dict[str, list[ManifestEntry]]:
    """Kind ``kind``'s entries by symbol; ``_load_manifests``' order (symbol, then month) holds."""
    groups: dict[str, list[ManifestEntry]] = {}
    for entry in entries:
        if entry.kind == kind:
            groups.setdefault(entry.symbol, []).append(entry)
    return groups


def _archive(entry: ManifestEntry, cache: Path, run: _Run) -> bytes:
    """The bytes ``entry`` pins: the cached file, which must match the pin, or else fetched
    again by the pin (``fetch_pinned``) and cached."""
    refuse_after_end(entry.month, run.config)  # ruling P7, again where the archive is used
    target = cache.joinpath(*entry.path.strip("/").split("/"))
    if target.is_file():
        content = target.read_bytes()
        if _sha256(content) != entry.sha256 or len(content) != entry.bytes:
            raise ValueError(f"{entry.path}: the cached archive does not match its manifest pin")
        return content
    content = fetch_pinned(run.transport, entry, sleep=run.sleep, log=_log)
    _store(target, content)
    return content


def _read_series[B: (DailyBar, HourBar)](
    entries: Sequence[ManifestEntry],
    cache: Path,
    run: _Run,
    read: Callable[[bytes, str, str], KlineRead[B]],
    step: int,
) -> _Series[B]:
    """One symbol's archives of one kind, by month: masks inside each month only (ruling
    P12), and every interval of an unreadable month masked, with its reason."""
    bars: list[B] = []
    masked: set[int] = set()
    unreadable: dict[str, str] = {}
    for entry in entries:
        start, end = month_bounds_ms(entry.month)
        result = read(_archive(entry, cache, run), entry.symbol, entry.month)
        if result.unreadable:
            unreadable[entry.month] = result.unreadable
            masked.update(range(start, end, step))
        else:
            bars.extend(result.bars)
            masked.update(open_ms for open_ms in result.masked if start <= open_ms < end)
    return _Series(tuple(bars), frozenset(masked), unreadable)


def _read_spot_hours(content: bytes, symbol: str, month: str) -> KlineRead[HourBar]:
    return read_hourly(content, symbol, month, futures=False)


def _read_futures_hours(content: bytes, symbol: str, month: str) -> KlineRead[HourBar]:
    return read_hourly(content, symbol, month, futures=True)


def _daily_series(
    entries: Sequence[ManifestEntry], cache: Path, run: _Run
) -> dict[str, _Series[DailyBar]]:
    return {
        symbol: _read_series(group, cache, run, read_daily, _DAY_MS)
        for symbol, group in _grouped(entries, "spot_1d").items()
    }


def _usable_hours(
    entries: Sequence[ManifestEntry], cache: Path, run: _Run, keep: frozenset[str] = frozenset()
) -> tuple[dict[str, list[int]], dict[str, _Series[HourBar]]]:
    """Per symbol, the sorted opens of its unmasked spot hourly bars (ruling P24), and the
    whole series of the symbols in ``keep``, so that no archive is decoded twice."""
    usable: dict[str, list[int]] = {}
    kept: dict[str, _Series[HourBar]] = {}
    for symbol, group in _grouped(entries, "spot_1h").items():
        series = _read_series(group, cache, run, _read_spot_hours, _HOUR_MS)
        usable[symbol] = [bar.open_ms for bar in series.unmasked()]
        if symbol in keep:
            kept[symbol] = series
    return usable, kept


def _universes(
    discovery: _Discovery,
    daily: Mapping[str, _Series[DailyBar]],
    config: DataConfig,
    usable_hours: Mapping[str, Sequence[int]] | None,
) -> tuple[MonthlyUniverse, ...]:
    """``select_universe`` over every discovered symbol, bars or none (its base counts for the
    leveraged-token rule), with masked days left out (rulings P18, P24)."""
    bars: dict[str, tuple[DailyBar, ...]] = {symbol: () for symbol in discovery.symbols}
    bars.update((symbol, tuple(series.unmasked())) for symbol, series in daily.items())
    return select_universe(dict(sorted(bars.items())), config, usable_hours=usable_hours)


def _universe_document(universes: Sequence[MonthlyUniverse]) -> list[dict[str, Any]]:
    return [
        {
            "month": universe.month,
            "selected": list(universe.selected),
            "ranked": [[symbol, str(mean), bars] for symbol, mean, bars in universe.ranked],
            "excluded": [list(pair) for pair in universe.excluded],
            "entered": list(universe.entered),
            "left": list(universe.left),
        }
        for universe in universes
    ]


def _load_universe(path: Path, config: DataConfig) -> list[dict[str, Any]]:
    """The ``universes`` of ``select --stage final``'s ``universe.json``, for this end month."""
    document = _read_json(path)
    universes = document.get("universes")
    if (
        document.get("format") != UNIVERSE_FORMAT
        or document.get("end_month") != config.end_month
        or not isinstance(universes, list)
        or not all(
            isinstance(u, dict)
            and isinstance(u.get("selected"), list)
            and all(isinstance(symbol, str) for symbol in u["selected"])
            for u in universes
        )
    ):
        raise ValueError(f"{path}: not a {UNIVERSE_FORMAT} document for end_month")
    return universes


def _month_of(ms: int) -> str:
    return datetime.fromtimestamp(ms // 1000, tz=UTC).strftime("%Y-%m")


def _funding(
    symbol: str,
    futures: _Series[HourBar],
    entries: Sequence[ManifestEntry],
    cache: Path,
    run: _Run,
) -> tuple[list[FundingRow], dict[tuple[str, str], str]]:
    """A perpetual's funding rows (every readable file, by month) and its month statuses.

    The span runs from the open of its first unmasked hourly bar to the close of its last
    (ruling P15); every month it touches is judged: a file ``read_funding`` refuses is
    ``"unreadable_file"`` (P13), a missing file ``"complete"`` if the month holds no slot in
    the span and ``"missing_file"`` otherwise (P16).
    """
    files: dict[str, tuple[FundingRow, ...] | None] = {}
    for entry in entries:
        content = _archive(entry, cache, run)  # a pin mismatch is an error, not unreadable
        try:
            files[entry.month] = read_funding(content, symbol, entry.month)
        except ValueError:
            files[entry.month] = None
    rows = [row for month in sorted(files) for row in files[month] or ()]
    unmasked = futures.unmasked()
    if not unmasked:
        return rows, {}
    first_ms, last_ms = unmasked[0].open_ms, unmasked[-1].open_ms + _HOUR_MS - 1
    statuses: dict[tuple[str, str], str] = {}
    for month in months(_month_of(first_ms), _month_of(last_ms)):
        found = files.get(month, ())
        if found is None:
            status = "unreadable_file"
        else:
            status = funding_month_status(found, month, first_ms=first_ms, last_ms=last_ms)
            if month not in files and status != "complete":
                status = "missing_file"
        statuses[(symbol, month)] = status
    return rows, statuses
