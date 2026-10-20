"""V4.0's data step, stage by stage: discover, fetch, select and pack.

``.github/workflows/v4-data.yml`` runs these stages on GitHub's machines (no heavy work runs on
the owner's PC); each stage reads the files the stages before it wrote:

* ``discover --out D`` lists every spot USDT symbol the archive holds, delisted ones included,
  and writes ``D/symbols.json``: the symbols, the candidates (those ``static_exclusion`` does
  not exclude), the exclusions (symbol -> reason) and, per kind and candidate, the months the
  archive lists up to ``end_month``.
* ``fetch --kind K --discovery D/symbols.json [--symbols-file F] --shard i/n --cache C --out O``
  downloads and verifies (``fetch_verified``: Binance's ``.CHECKSUM``) every listed month of
  kind K for shard i of n of the symbols, stores each archive at ``C/<archive path>`` and
  writes the manifest piece ``O/manifest-K-i.json``: the shard's symbols, the entries, and
  under ``absent`` each listed month the host does not have (404). The symbols are those in F,
  one per line (``candidates.txt``), which an hourly kind requires; ``spot_1d`` takes every
  candidate without F. A shard is every n-th symbol of the sorted list, from index i.
* ``select --stage candidates`` writes ``candidates.txt``: every symbol ranked in a top 20
  (``HOURLY_RANK_DEPTH``) in any month, from the daily archives with no hourly check. The
  hourly fetch takes every listed month of each, its whole history.
* ``select --stage final`` adds the hourly check (``usable_hours`` from the spot hourly
  archives) and writes ``universe.json`` and ``selected.txt`` (every symbol ever selected).
* ``pack --universe U`` writes ``daily.pack.json.gz``, ``hourly.pack.json.gz`` and
  ``data.json`` (the pins). It recomputes the final universes from the same archives and
  stops unless they equal ``select --stage final``'s ``universe.json`` (U). The hourly pack
  holds the whole history of every symbol ever selected. Each pack's manifest lists exactly
  the archives read for it: the daily pack's includes every candidate's spot hourly archives,
  which the universes' hourly check read, and the funding archives of a perpetual left out
  of the hourly pack are read by neither.

A stage refuses an incomplete or inconsistent set of manifest pieces: for each kind, the pieces
must be shards 0 to n-1 of one n, partitioning their symbols as ``fetch`` does, and each
symbol's entries and absent months must be exactly its discovered months. The daily pieces
must cover every candidate and the hourly ones every symbol ranked in a top 20. A symbol
excluded whatever its prices is fetched for no kind; the daily pack records its reason.
``select`` and ``pack`` read each archive from ``--cache`` only once it matches its manifest
entry's SHA-256 and size; one missing from the cache is fetched again by that pin
(``fetch_pinned``). Every stage but ``discover`` takes ``--discovery``. ``--config`` (before
the stage) names the data config, ``config/v4_data.json`` by default, and the packs record the
SHA-256 of its raw bytes (ruling P22). The rulings applied here: every manifest entry passes
``refuse_after_end`` before any archive is requested or read (P7); the daily bars and usable
hours given to ``select_universe`` leave out masked intervals, while the packs hold the bars as
read with their masks (P24), of which only those inside each archive's month count, and an
unreadable archive masks its whole month (P12); every discovered symbol is a key of the daily
input (Task 5) and the input is sorted (P18); a funding file that cannot be read is
``"unreadable_file"`` (P13), and the funding months run over the perpetual's span of unmasked
hourly bars, a month without a file being ``"complete"`` only if it holds no slot (P15, P16); a
futures series with no readable bar is left out with its rules, masks and funding, and a pack
whose canonical JSON exceeds 1.5 GiB stops for a ruling on splitting it (P23); order rules come
only for the hourly pack's series, and a refusal stops the pack (P20); the filter snapshots must
match their pins (R3).

Standard output carries counts, sizes and pins only, never a bar value (owner rule: public
logs); retries are logged to standard error. A refusal exits 1 with its reason on standard
error.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.klines import INTERVAL_MS, month_bounds_ms
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.archives import (
    KINDS,
    HttpTransport,
    ManifestEntry,
    Transport,
    archive_path,
    fetch_pinned,
    fetch_verified,
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
from crypto_grid_bot.v4.data.config import DataConfig, load_data_config, months, refuse_after_end
from crypto_grid_bot.v4.data.filters import rules_for
from crypto_grid_bot.v4.data.listing import discover_months, discover_spot_usdt_symbols
from crypto_grid_bot.v4.data.pack import daily_pack_document, hourly_pack_document, write_canonical
from crypto_grid_bot.v4.data.universe import (
    HOURLY_RANK_DEPTH,
    MonthlyUniverse,
    select_universe,
    static_exclusion,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "v4_data.json"
# A pack whose canonical JSON is larger stops for a ruling on splitting it (ruling P23); the
# reader refuses anything over 2 GiB.
MAX_PACK_JSON_BYTES = 1_610_612_736
HOURLY_KINDS = ("spot_1h", "futures_1h", "funding")
VENUES = ("spot", "futures")
DISCOVERY_FORMAT = "v4-symbols/1"
MANIFEST_FORMAT = "v4-manifest/1"
UNIVERSE_FORMAT = "v4-universe/1"
DATA_FORMAT = "v4-data/1"
DAILY_PACK = "daily.pack.json.gz"
HOURLY_PACK = "hourly.pack.json.gz"

_HOUR_MS = INTERVAL_MS["1h"]
_DAY_MS = INTERVAL_MS["1d"]
_SHARD = re.compile(r"(0|[1-9][0-9]*)/([1-9][0-9]*)")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENTRY_FIELDS = frozenset(field.name for field in fields(ManifestEntry))


@dataclass(frozen=True)
class _Run:
    """What every stage shares: the config, its pin and the network."""

    config: DataConfig
    config_sha256: str
    transport: Transport
    sleep: Callable[[float], None]


@dataclass(frozen=True)
class _Discovery:
    """``symbols.json``: every discovered symbol, the candidates, the exclusions, the months."""

    symbols: tuple[str, ...]
    candidates: tuple[str, ...]
    exclusions: dict[str, str]
    months: dict[str, dict[str, tuple[str, ...]]]


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


def _say(line: str) -> None:
    """A line of standard output: counts, sizes and pins only."""
    print(line, flush=True)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_shard(text: str) -> tuple[int, int]:
    """``"i/n"`` as (i, n), with 0 <= i < n."""
    match = _SHARD.fullmatch(text)
    if match is None or int(match.group(1)) >= int(match.group(2)):
        raise ValueError(f"--shard must be i/n with 0 <= i < n, got {text!r}")
    return int(match.group(1)), int(match.group(2))


def shard_symbols(symbols: Iterable[str], index: int, count: int) -> list[str]:
    """Shard ``index`` of ``count``: every ``count``-th symbol of the sorted list from ``index``.
    The shards of one list partition it, with no symbol in two and none left out."""
    return sorted(set(symbols))[index::count]


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: a JSON object is required")
    return document


def _write_new(path: Path, text: str) -> None:
    """``text`` to a new file; an existing one is refused, never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="ascii", newline="\n") as handle:
        handle.write(text)


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    _write_new(path, json.dumps(document, indent=1, sort_keys=True) + "\n")


def _write_lines(path: Path, lines: Sequence[str]) -> None:
    _write_new(path, "".join(line + "\n" for line in lines))


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


def _static_exclusions(symbols: Sequence[str], config: DataConfig) -> dict[str, str]:
    bases = frozenset(symbol.removesuffix("USDT") for symbol in symbols)
    reasons = {symbol: static_exclusion(symbol, bases, config) for symbol in symbols}
    return {symbol: reason for symbol, reason in reasons.items() if reason is not None}


def _load_discovery(path: Path, config: DataConfig) -> _Discovery:
    """``symbols.json``, refused unless it is this config's: its end month, its exclusions
    and candidates as the config gives them, and no month after ``end_month``."""
    document = _read_json(path)
    if document.get("format") != DISCOVERY_FORMAT:
        raise ValueError(f"{path}: not a {DISCOVERY_FORMAT} document")
    if document.get("end_month") != config.end_month:
        raise ValueError(f"{path}: discovered up to {document.get('end_month')!r}, not end_month")
    symbols = document.get("symbols")
    if not isinstance(symbols, list) or symbols != sorted(set(symbols)):
        raise ValueError(f"{path}: symbols must be a sorted list without duplicates")
    exclusions = _static_exclusions(symbols, config)
    candidates = [symbol for symbol in symbols if symbol not in exclusions]
    if document.get("exclusions") != exclusions or document.get("candidates") != candidates:
        raise ValueError(f"{path}: the exclusions and candidates do not follow from the config")
    listed = document.get("months")
    if not isinstance(listed, dict) or set(listed) != set(KINDS):
        raise ValueError(f"{path}: months must hold exactly the kinds {', '.join(KINDS)}")
    found: dict[str, dict[str, tuple[str, ...]]] = {}
    for kind in KINDS:
        per_symbol = listed[kind]
        if not isinstance(per_symbol, dict) or set(per_symbol) != set(candidates):
            raise ValueError(f"{path}: months[{kind}] must name exactly the candidates")
        for symbol, values in per_symbol.items():
            if not isinstance(values, list) or values != sorted(set(values)):
                raise ValueError(f"{path}: months[{kind}][{symbol}] must be sorted and unique")
            for month in values:
                refuse_after_end(month, config)
        found[kind] = {symbol: tuple(values) for symbol, values in per_symbol.items()}
    return _Discovery(tuple(symbols), tuple(candidates), exclusions, found)


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
    candidates, every entry and absent month is for one of them, no archive is listed twice,
    and each symbol's entries and absent months are exactly its discovered months of the kind.
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
    if (
        not isinstance(symbols, list)
        or symbols != sorted(set(symbols))
        or not set(symbols) <= set(discovery.candidates)
    ):
        raise ValueError(f"{path}: symbols must be sorted, unique candidates of the discovery")
    raw_entries, absent = piece.get("entries"), piece.get("absent")
    if not isinstance(raw_entries, list) or not isinstance(absent, list):
        raise ValueError(f"{path}: entries and absent must be lists")
    held: dict[str, list[str]] = {symbol: [] for symbol in symbols}
    for raw in raw_entries:
        entry = _entry(path, kind, raw, config)
        key = (entry.kind, entry.symbol, entry.month)
        if entry.symbol not in held or key in found:
            raise ValueError(f"{path}: {entry.path!r} is outside the piece's symbols or twice")
        found[key] = entry
        held[entry.symbol].append(entry.month)
    for item in absent:
        if not isinstance(item, dict) or set(item) != {"symbol", "month"}:
            raise ValueError(f"{path}: an absent month must be exactly {{symbol, month}}")
        if item["symbol"] not in held:
            raise ValueError(f"{path}: absent {item['symbol']!r} is outside the piece's symbols")
        held[item["symbol"]].append(item["month"])
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


def _snapshots(config: DataConfig) -> dict[str, Mapping[str, object]]:
    """The present-day filter snapshots (ruling R3), each refused unless it matches its pin."""
    snapshots: dict[str, Mapping[str, object]] = {}
    for venue in VENUES:
        pin = config.filter_snapshots.get(venue)
        if pin is None:
            raise ValueError(f"filter_snapshots has no {venue} snapshot (ruling R3)")
        raw = (ROOT / pin["path"]).read_bytes()
        if _sha256(raw) != pin["sha256"]:
            raise ValueError(
                f"the {venue} filter snapshot {pin['path']} has SHA-256 {_sha256(raw)}, "
                f"not the pinned {pin['sha256']}"
            )
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError(f"the {venue} filter snapshot is not a JSON object")
        snapshots[venue] = document
    return snapshots


def _rules(
    symbol: str, venue: str, snapshot: Mapping[str, object], bars: Sequence[HourBar]
) -> tuple[VenueRules, str]:
    try:
        return rules_for(symbol, venue, snapshot, bars)
    except ValueError as exc:
        raise ValueError(
            f"order rules for {symbol} on {venue}: {exc}. This is a hard stop (ruling P20): "
            "nothing is inferred for a symbol the snapshot lists; it needs a ruling"
        ) from exc


class PackTooLarge(ValueError):
    """A pack's canonical JSON is over ``MAX_PACK_JSON_BYTES``: splitting it needs a ruling."""


def _write_pack(path: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    """Write one pack, print its size and pin, and return its ``data.json`` record.

    The size is the length of the JSON the written file compresses, read back and checked
    against the pin; over ``MAX_PACK_JSON_BYTES`` it raises ``PackTooLarge`` (ruling P23).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    pin = write_canonical(document, path)
    digest, size = hashlib.sha256(), 0
    with gzip.open(path, "rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
            size += len(chunk)
    if digest.hexdigest() != pin:
        raise ValueError(f"{path}: the written pack does not hash to its pin {pin}")
    name = path.name.split(".")[0]
    _say(f"pack {name} pack: {size} bytes of canonical JSON, sha256 {pin}")
    if size > MAX_PACK_JSON_BYTES:
        raise PackTooLarge(
            f"the {name} pack's canonical JSON is {size} bytes, over the {MAX_PACK_JSON_BYTES}"
            "-byte limit (1.5 GiB): a ruling on splitting the pack is needed (ruling P23)"
        )
    return {"file": path.name, "sha256": pin, "json_bytes": size}


def discover(args: argparse.Namespace, run: _Run) -> int:
    symbols = discover_spot_usdt_symbols(run.transport, sleep=run.sleep, log=_log)
    exclusions = _static_exclusions(symbols, run.config)
    candidates = [symbol for symbol in symbols if symbol not in exclusions]
    listed = {
        kind: {
            symbol: list(
                discover_months(run.transport, kind, symbol, run.config, sleep=run.sleep, log=_log)
            )
            for symbol in candidates
        }
        for kind in KINDS
    }
    _write_json(
        args.out / "symbols.json",
        {
            "format": DISCOVERY_FORMAT,
            "end_month": run.config.end_month,
            "symbols": list(symbols),
            "candidates": candidates,
            "exclusions": exclusions,
            "months": listed,
        },
    )
    reasons = sorted(set(exclusions.values()))
    counts = ", ".join(f"{list(exclusions.values()).count(r)} {r}" for r in reasons)
    _say(
        f"discover: {len(symbols)} spot USDT symbols, {len(candidates)} candidates, "
        f"{len(exclusions)} excluded whatever their prices ({counts or 'none'})"
    )
    for kind in KINDS:
        holding = [values for values in listed[kind].values() if values]
        archives = sum(len(values) for values in holding)
        _say(f"discover {kind}: {len(holding)} candidates with archives, {archives} archives")
    return 0


def fetch(args: argparse.Namespace, run: _Run) -> int:
    index, count = parse_shard(args.shard)
    if args.symbols_file is None and args.kind != "spot_1d":
        raise ValueError(f"--symbols-file (candidates.txt) is required for {args.kind}")
    discovery = _load_discovery(args.discovery, run.config)
    symbols: Sequence[str] = discovery.candidates
    if args.symbols_file is not None:
        symbols = args.symbols_file.read_text(encoding="ascii").split()
        unknown = sorted(set(symbols) - set(discovery.candidates))
        if len(set(symbols)) != len(symbols) or unknown:
            raise ValueError(f"{args.symbols_file}: duplicate or non-candidate symbols {unknown}")
    mine = shard_symbols(symbols, index, count)
    entries: list[ManifestEntry] = []
    absent: list[dict[str, str]] = []
    for symbol in mine:
        for month in discovery.months[args.kind][symbol]:
            result = fetch_verified(
                run.transport, args.kind, symbol, month, run.config, sleep=run.sleep, log=_log
            )
            if result is None:
                absent.append({"symbol": symbol, "month": month})
                continue
            entry, content = result
            _store(args.cache.joinpath(*entry.path.strip("/").split("/")), content)
            entries.append(entry)
    _write_json(
        args.out / f"manifest-{args.kind}-{index}.json",
        {
            "format": MANIFEST_FORMAT,
            "kind": args.kind,
            "shard": f"{index}/{count}",
            "symbols": mine,
            "entries": [asdict(entry) for entry in entries],
            "absent": absent,
        },
    )
    size = sum(entry.bytes for entry in entries)
    _say(
        f"fetch {args.kind} shard {index}/{count}: {len(mine)} symbols, "
        f"{len(entries)} archives ({size} bytes), {len(absent)} absent"
    )
    return 0


def select(args: argparse.Namespace, run: _Run) -> int:
    final = args.stage == "final"
    if final != bool(args.hourly_manifests):
        raise ValueError("--hourly-manifests is required by the final stage and only by it")
    config = run.config
    discovery = _load_discovery(args.discovery, config)
    daily_pieces = _load_manifests(args.daily_manifests, ("spot_1d",), config, discovery)
    hourly_pieces = (
        _load_manifests(args.hourly_manifests, ("spot_1h",), config, discovery) if final else None
    )
    _require_coverage(daily_pieces, "spot_1d", discovery.candidates, "candidates")
    daily = _daily_series(daily_pieces.entries, args.cache, run)
    if hourly_pieces is None:
        ranked = _ranked(_universes(discovery, daily, config, None))
        _write_lines(args.out / "candidates.txt", ranked)
        _say(f"select candidates: {len(ranked)} symbols ranked in a top {HOURLY_RANK_DEPTH}")
        return 0
    usable, _ = _usable_hours(hourly_pieces.entries, args.cache, run)
    universes = _universes(discovery, daily, config, usable)
    _require_coverage(hourly_pieces, "spot_1h", _ranked(universes), "symbols ranked in a top 20")
    selected = sorted({symbol for universe in universes for symbol in universe.selected})
    _write_json(
        args.out / "universe.json",
        {
            "format": UNIVERSE_FORMAT,
            "end_month": run.config.end_month,
            "universes": _universe_document(universes),
        },
    )
    _write_lines(args.out / "selected.txt", selected)
    _say(f"select final: {len(universes)} universe months, {len(selected)} symbols ever selected")
    return 0


def pack(args: argparse.Namespace, run: _Run) -> int:
    config, cache = run.config, args.cache
    discovery = _load_discovery(args.discovery, config)
    pieces = _load_manifests(args.manifests, KINDS, config, discovery)
    expected = _load_universe(args.universe, config)
    snapshots = _snapshots(config)
    _require_coverage(pieces, "spot_1d", discovery.candidates, "candidates")
    entries = pieces.entries
    daily = _daily_series(entries, cache, run)
    # The spot hourly series of the symbols select-final selected are kept from the one read
    # that gives every candidate's usable hours; they are used only if the universes match.
    keep = frozenset(symbol for universe in expected for symbol in universe["selected"])
    usable, spot_series = _usable_hours(entries, cache, run, keep)
    universes = _universes(discovery, daily, config, usable)
    for kind in HOURLY_KINDS:
        _require_coverage(pieces, kind, _ranked(universes), "symbols ranked in a top 20")
    if _universe_document(universes) != expected:
        raise ValueError(
            f"{args.universe}: the universes recomputed here differ from select-final's, so "
            "the archives or the code differ between the two jobs"
        )
    selected = sorted(keep)

    # The universes were built from every candidate's spot hourly archives too.
    packs: dict[str, dict[str, Any]] = {}
    packs["daily"] = _write_pack(
        args.out / DAILY_PACK,
        daily_pack_document(
            config,
            [e for e in entries if e.kind in ("spot_1d", "spot_1h")],
            {symbol: series.bars for symbol, series in daily.items()},
            discovery.exclusions,
            universes,
            masks={symbol: series.masks() for symbol, series in daily.items()},
            config_sha256=run.config_sha256,
        ),
    )
    del daily  # the daily bars are not needed past their pack

    futures_entries, funding_entries = _grouped(entries, "futures_1h"), _grouped(entries, "funding")
    spot: dict[str, tuple[HourBar, ...]] = {}
    futures: dict[str, tuple[HourBar, ...]] = {}
    masks: dict[tuple[str, str], tuple[list[int], dict[str, str]]] = {}
    funding: dict[str, list[FundingRow]] = {}
    funding_months: dict[tuple[str, str], str] = {}
    for symbol in selected:
        spot_read = spot_series.pop(symbol)
        spot[symbol], masks[(symbol, "spot")] = spot_read.bars, spot_read.masks()
        perpetual = _read_series(
            futures_entries.get(symbol, []), cache, run, _read_futures_hours, _HOUR_MS
        )
        if not perpetual.bars:  # no futures market in the data (ruling P23)
            continue
        futures[symbol], masks[(symbol, "futures")] = perpetual.bars, perpetual.masks()
        funding[symbol], statuses = _funding(
            symbol, perpetual, funding_entries.get(symbol, []), cache, run
        )
        funding_months |= statuses
    rules = {
        (symbol, venue): _rules(symbol, venue, snapshots[venue], bars)
        for venue, series in (("spot", spot), ("futures", futures))
        for symbol, bars in series.items()
    }
    # Exactly the archives read for this pack: an omitted perpetual's funding files never are.
    hourly_manifest = [
        e
        for e in entries
        if (e.kind in ("spot_1h", "futures_1h") and e.symbol in spot)
        or (e.kind == "funding" and e.symbol in futures)
    ]
    packs["hourly"] = _write_pack(
        args.out / HOURLY_PACK,
        hourly_pack_document(
            config,
            hourly_manifest,
            spot,
            futures,
            masks,
            funding,
            funding_months,
            rules,
            config_sha256=run.config_sha256,
        ),
    )
    _write_json(
        args.out / "data.json",
        {
            "format": DATA_FORMAT,
            "config_sha256": run.config_sha256,
            "end_month": config.end_month,
            "packs": packs,
            "archives": {kind: sum(e.kind == kind for e in entries) for kind in KINDS},
            "universe_months": len(universes),
            "selected_symbols": len(selected),
            "perpetuals": len(futures),
        },
    )
    _say(
        f"pack: {len(universes)} universe months, {len(selected)} symbols ever selected, "
        f"{len(futures)} with a perpetual, {len(entries)} archives"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_data.py", description="V4.0's data step (see the module docstring)."
    )
    parser.add_argument("--config", type=Path, default=CONFIG, help="the data config")
    commands = parser.add_subparsers(dest="command", required=True)

    command = commands.add_parser("discover", help="list symbols and their monthly archives")
    command.add_argument("--out", type=Path, required=True)

    command = commands.add_parser("fetch", help="fetch and verify one shard of one kind")
    command.add_argument("--kind", choices=KINDS, required=True)
    command.add_argument("--discovery", type=Path, required=True, help="discover's symbols.json")
    command.add_argument(
        "--symbols-file",
        type=Path,
        help="one symbol per line; required for an hourly kind, spot_1d takes every candidate",
    )
    command.add_argument("--shard", required=True, help="i/n: shard i (from 0) of n")
    command.add_argument("--cache", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = commands.add_parser("select", help="the candidates, or the final universes")
    command.add_argument("--stage", choices=("candidates", "final"), required=True)
    command.add_argument("--discovery", type=Path, required=True)
    command.add_argument("--daily-manifests", type=Path, nargs="+", required=True)
    command.add_argument("--hourly-manifests", type=Path, nargs="+", default=[])
    command.add_argument("--cache", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)

    command = commands.add_parser("pack", help="write both packs and data.json")
    command.add_argument("--discovery", type=Path, required=True)
    command.add_argument("--manifests", type=Path, nargs="+", required=True)
    command.add_argument(
        "--universe", type=Path, required=True, help="select --stage final's universe.json"
    )
    command.add_argument("--cache", type=Path, required=True)
    command.add_argument("--out", type=Path, required=True)
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace, _Run], int]] = {
    "discover": discover,
    "fetch": fetch,
    "select": select,
    "pack": pack,
}


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one stage: 0 on success, 1 on a refusal (its reason on standard error).

    ``transport`` and ``sleep`` replace the guarded ``HttpTransport`` and the retry sleep
    (tests)."""
    args = build_parser().parse_args(argv)
    try:
        config = load_data_config(args.config)
        run = _Run(
            config=config,
            config_sha256=_sha256(args.config.read_bytes()),
            transport=HttpTransport() if transport is None else transport,
            sleep=sleep,
        )
        return COMMANDS[args.command](args, run)
    except (ValueError, OSError) as exc:  # OSError: a missing input or an existing output
        _log(f"v4_data {args.command}: refused: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
