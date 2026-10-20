"""V4.0's data step, stage by stage: discover, fetch, select and pack.

``.github/workflows/v4-data.yml`` runs these stages on GitHub's machines (no heavy work runs on
the owner's PC); each stage reads the files the stages before it wrote:

* ``discover --out D`` refuses an ``end_month`` that is not before the current UTC month
  (the last complete calendar month), lists every spot and USDT-M futures USDT symbol the
  archive holds, delisted ones included, and writes ``D/symbols.json``: the symbols, the
  candidates (those ``static_exclusion`` does not exclude), the exclusions (symbol -> reason;
  a spot name ``archive_path`` cannot address, such as 币安人生USDT, is ``"unsupported_name"``,
  never fetched: ruling P33), the futures symbols with a ``futures_1h`` month at or before
  ``end_month`` that could be a candidate's perpetual (``futures_symbols``, ruling P34), each
  candidate's perpetual among them (candidate -> ``{"symbol", "multiplier"}``, by
  ``perpetual_for``: the plain ``XUSDT``, else the one multiplier contract such as
  1000SHIBUSDT; only for candidates that have one) and, per kind, the months the archive lists
  up to ``end_month``: for each candidate under its own symbol for the spot kinds, and under
  its perpetual's symbol for ``futures_1h`` and ``funding``.
* ``fetch --kind K --discovery D/symbols.json [--symbols-file F] --shard i/n --cache C --out O``
  downloads and verifies (``fetch_verified``: Binance's ``.CHECKSUM``) every listed month of
  kind K for shard i of n of the symbols, stores each archive at ``C/<archive path>`` and
  writes the manifest piece ``O/manifest-K-i.json``: the shard's symbols, the entries, and
  under ``absent`` each listed month the host does not have (404). The symbols are those in F,
  one per line (``candidates.txt``), which an hourly kind requires; ``spot_1d`` takes every
  candidate without F. A shard is every n-th symbol of the sorted list, from index i, for every
  kind, so the pieces of all kinds line up. For ``futures_1h`` and ``funding`` each symbol's
  archives are its perpetual's, fetched and recorded (entries and absent months) under the
  perpetual's symbol; a symbol without a perpetual has none. A shard with any archive it
  cannot fetch (no or a mismatched ``.CHECKSUM``, a 4xx, a size breach, a transport failure
  after its retries) goes on with the others, then writes no piece and exits 1 listing every
  failure as symbol, kind, month and reason, stopping at ``MAX_FETCH_FAILURES``.
* ``select --stage candidates`` writes ``candidates.txt``: every symbol ranked in a top 20
  (``HOURLY_RANK_DEPTH``) in any month, from the daily archives with no hourly check. The
  hourly fetch takes every listed month of each, its whole history.
* ``select --stage final`` adds the hourly check (``usable_hours`` from the spot hourly
  archives) and writes ``universe.json`` and ``selected.txt`` (every symbol ever selected).
* ``pack --universe U`` writes ``daily.pack.json.gz``, one coin pack ``v4-coin-<SYMBOL>.json.gz``
  per symbol ever selected, ``hourly-index.json.gz`` (every coin pack's pin, and each coin's
  perpetual) and ``data.json`` (the pins of the daily pack and the index). It recomputes the
  final universes from the same archives and stops unless they equal ``select --stage
  final``'s ``universe.json`` (U). Before building the coin packs it prints the rows they will
  hold, bars as read (a pre-flight). Then, coin by coin in sorted order (ruling P32: the
  memory peak is one coin's history, never every coin's), it reads the coin's whole spot
  history and, if it has a perpetual, the perpetual's futures history, funding and funding
  months, under the perpetual's own symbol (under which the present-day filters are looked
  up), writes the coin's pack and releases it all before the next coin. Each pack's manifest
  lists exactly the archives read for it: the daily pack's includes every candidate's spot
  hourly archives, which the universes' hourly check read, and the funding archives of a
  perpetual left out of its coin pack are read by neither.

A stage refuses an incomplete or inconsistent set of manifest pieces: for each kind, the pieces
must be shards 0 to n-1 of one n, partitioning their symbols as ``fetch`` does, and each
symbol's entries and absent months must be exactly its discovered months (for a futures kind,
each perpetual's, under its own symbol). The daily pieces must cover every candidate, and the
hourly ones every symbol the candidates stage ranked in a top 20 (``candidates.txt``), checked
from the daily archives before any hourly one is read. A symbol excluded whatever its prices
is fetched for no kind; the daily pack records its reason.
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
futures series with no readable bar is left out of its coin pack with its rules, masks,
funding and perpetual, and any pack whose canonical JSON exceeds 1.5 GiB stops for a ruling on
splitting it (P23); order rules come only for the coin packs' series, and a refusal stops the
pack (P20); the filter snapshots must match their pins (R3). Two candidates with the same
perpetual stop ``discover`` for a ruling. The loading helpers are in
``crypto_grid_bot.v4.data.inputs``.

Standard output carries counts, sizes and pins only, never a bar value (owner rule: public
logs); retries are logged to standard error. A refusal exits 1 with its reason on standard
error.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.archives import (
    KINDS,
    HttpTransport,
    ManifestEntry,
    Transport,
    fetch_verified,
)
from crypto_grid_bot.v4.data.bars import FundingRow, HourBar
from crypto_grid_bot.v4.data.config import DataConfig, load_data_config
from crypto_grid_bot.v4.data.filters import rules_for
from crypto_grid_bot.v4.data.inputs import (
    _HOUR_MS,
    DISCOVERY_FORMAT,
    FUTURES_KINDS,
    MANIFEST_FORMAT,
    UNIVERSE_FORMAT,
    _archive_symbols,
    _daily_series,
    _funding,
    _grouped,
    _load_discovery,
    _load_manifests,
    _load_universe,
    _log,
    _perpetuals_from,
    _ranked,
    _read_futures_hours,
    _read_series,
    _read_spot_hours,
    _require_coverage,
    _Run,
    _Series,
    _sha256,
    _static_exclusions,
    _store,
    _universe_document,
    _universes,
    _unshared,
    _usable_hours,
    parse_shard,
)
from crypto_grid_bot.v4.data.listing import (
    UNSUPPORTED_NAME,
    discover_futures_usdt_symbols,
    discover_months,
    discover_spot_usdt_listing,
    perpetual_names,
)
from crypto_grid_bot.v4.data.pack import (
    coin_pack_document,
    coin_pack_file,
    daily_pack_document,
    hourly_index_document,
    write_canonical,
)
from crypto_grid_bot.v4.data.universe import HOURLY_RANK_DEPTH

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "v4_data.json"
# A pack whose canonical JSON is larger stops for a ruling on splitting it (ruling P23); the
# reader refuses anything over 2 GiB.
MAX_PACK_JSON_BYTES = 1_610_612_736
# A fetch shard reports every archive it could not fetch, up to this many: a systemic failure
# (the network down) then stops in minutes instead of retrying every archive of the shard.
MAX_FETCH_FAILURES = 50
HOURLY_KINDS = ("spot_1h", "futures_1h", "funding")
VENUES = ("spot", "futures")
DATA_FORMAT = "v4-data/1"
DAILY_PACK = "daily.pack.json.gz"
HOURLY_INDEX = "hourly-index.json.gz"

# What the hourly pieces must cover: candidates.txt, the candidates stage's ranking. The final
# universes' ranking can be narrower, since their window can open later (the hourly check).
_RANKED = "symbols the candidates stage ranked in a top 20"


def _say(line: str) -> None:
    """A line of standard output: counts, sizes and pins only."""
    print(line, flush=True)


def _multipliers(count: int) -> str:
    """How many of the perpetuals just counted are multiplier contracts, as words."""
    return f"{count} of them " + ("a multiplier contract" if count == 1 else "multiplier contracts")


def shard_symbols(symbols: Iterable[str], index: int, count: int) -> list[str]:
    """Shard ``index`` of ``count``: every ``count``-th symbol of the sorted list from ``index``.
    The shards of one list partition it, with no symbol in two and none left out."""
    return sorted(set(symbols))[index::count]


def _write_new(path: Path, text: str) -> None:
    """``text`` to a new file; an existing one is refused, never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="ascii", newline="\n") as handle:
        handle.write(text)


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    _write_new(path, json.dumps(document, indent=1, sort_keys=True) + "\n")


def _write_lines(path: Path, lines: Sequence[str]) -> None:
    _write_new(path, "".join(line + "\n" for line in lines))


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


def _write_pack(path: Path, document: Mapping[str, Any], label: str) -> dict[str, Any]:
    """Write one pack, print its size and pin under ``label`` (never a symbol), and return its
    record: file, pin and size.

    The size is the length of the JSON the written file compresses, read back and checked
    against the pin; over ``MAX_PACK_JSON_BYTES`` it raises ``PackTooLarge`` (ruling P23, for
    each pack: the daily pack, every coin pack and the index).
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
    _say(f"pack {label}: {size} bytes of canonical JSON, sha256 {pin}")
    if size > MAX_PACK_JSON_BYTES:
        raise PackTooLarge(
            f"the {label}'s canonical JSON is {size} bytes, over the {MAX_PACK_JSON_BYTES}"
            "-byte limit (1.5 GiB): a ruling on splitting the pack is needed (ruling P23)"
        )
    return {"file": path.name, "sha256": pin, "json_bytes": size}


@dataclass(frozen=True)
class _Hourly:
    """What every coin pack is built from: the hourly archives by kind and symbol (a futures
    kind by the perpetual's symbol), the absent months by (kind, symbol), the filter snapshots,
    the cache and the run."""

    spot: dict[str, list[ManifestEntry]]
    futures: dict[str, list[ManifestEntry]]
    funding: dict[str, list[ManifestEntry]]
    absent: dict[tuple[str, str], tuple[str, ...]]
    snapshots: dict[str, Mapping[str, object]]
    cache: Path
    run: _Run


def _futures_read(name: str, hourly: _Hourly) -> _Series[HourBar]:
    entries, absent = hourly.futures.get(name, []), hourly.absent.get(("futures_1h", name), ())
    return _read_series(
        entries, hourly.cache, hourly.run, _read_futures_hours, _HOUR_MS, absent=absent
    )


def _coin_pack(
    coin: str, perpetual: tuple[str, int] | None, hourly: _Hourly, out: Path, label: str
) -> tuple[tuple[str, str, int], dict[str, object] | None]:
    """Build and write one coin's pack, and return its (pin, file, bytes) and its perpetual
    entry, if any. Everything read for it is local here, so it is released on return, before
    the next coin's (ruling P32). A perpetual with no readable bar is left out (P23)."""
    run = hourly.run
    used = list(hourly.spot.get(coin, []))
    absent = hourly.absent.get(("spot_1h", coin), ())
    spot = _read_series(used, hourly.cache, run, _read_spot_hours, _HOUR_MS, absent=absent)
    masks = {"spot": spot.masks()}
    rules = {"spot": _rules(coin, "spot", hourly.snapshots["spot"], spot.bars)}
    entry: dict[str, object] | None = None
    futures: tuple[HourBar, ...] = ()
    funding: list[FundingRow] = []
    funding_months: dict[str, str] = {}
    if perpetual is not None:
        name, multiplier = perpetual
        used += hourly.futures.get(name, [])
        futures_read = _futures_read(name, hourly)
        if futures_read.bars:  # else no futures market in the data (ruling P23)
            funding_entries = hourly.funding.get(name, [])
            used += funding_entries
            funding, statuses = _funding(name, futures_read, funding_entries, hourly.cache, run)
            funding_months = {month: status for (_, month), status in statuses.items()}
            futures, masks["futures"] = futures_read.bars, futures_read.masks()
            rules["futures"] = _rules(name, "futures", hourly.snapshots["futures"], futures)
            entry = {"symbol": name, "multiplier": multiplier}
    document = coin_pack_document(
        run.config,
        used,
        coin=coin,
        spot=spot.bars,
        perpetual=entry,
        futures=futures,
        masks=masks,
        funding=funding,
        funding_months=funding_months,
        rules=rules,
        config_sha256=run.config_sha256,
    )
    record = _write_pack(out / coin_pack_file(coin), document, label)
    return (record["sha256"], record["file"], record["json_bytes"]), entry


def _refuse_an_incomplete_end_month(run: _Run) -> None:
    """``end_month`` must be before the current UTC month: the last complete calendar month
    (spec, "Data"), so that no month still being written is discovered."""
    now = run.clock()
    if now.tzinfo is None:
        raise ValueError("the clock must give a timezone-aware time")
    current = now.astimezone(UTC).strftime("%Y-%m")
    if not run.config.end_month < current:
        raise ValueError(
            f"end_month {run.config.end_month} is not before the current UTC month {current}: "
            "it must be the last complete calendar month"
        )


def discover(args: argparse.Namespace, run: _Run) -> int:
    _refuse_an_incomplete_end_month(run)
    listing = discover_spot_usdt_listing(run.transport, sleep=run.sleep, log=_log)
    symbols = listing.symbols
    static = _static_exclusions(symbols, run.config)
    candidates = [symbol for symbol in symbols if symbol not in static]
    # Ruling P33: a name archive_path cannot address is recorded and counted, never fetched.
    exclusions = static | dict.fromkeys(listing.unsupported, UNSUPPORTED_NAME)
    listed_futures = frozenset(
        discover_futures_usdt_symbols(run.transport, sleep=run.sleep, log=_log)
    )
    # Ruling P34: a futures symbol counts only with a futures_1h month at or before end_month.
    # The months of each name a candidate's perpetual could be are listed once, and reused.
    considered = sorted({n for s in candidates for n in perpetual_names(s) if n in listed_futures})
    futures_months = {
        name: discover_months(
            run.transport, "futures_1h", name, run.config, sleep=run.sleep, log=_log
        )
        for name in considered
    }
    futures_symbols = sorted(name for name, found in futures_months.items() if found)
    perpetuals = _perpetuals_from(candidates, futures_symbols)
    _unshared(perpetuals)
    listed = {
        kind: {
            name: list(
                futures_months[name]
                if kind == "futures_1h"
                else discover_months(
                    run.transport, kind, name, run.config, sleep=run.sleep, log=_log
                )
            )
            for name in _archive_symbols(kind, candidates, perpetuals)
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
            "futures_symbols": futures_symbols,
            "perpetuals": {
                symbol: {"symbol": perpetual, "multiplier": multiplier}
                for symbol, (perpetual, multiplier) in perpetuals.items()
            },
            "months": listed,
        },
    )
    reasons = sorted(set(exclusions.values()))
    counts = ", ".join(f"{list(exclusions.values()).count(r)} {r}" for r in reasons)
    _say(
        f"discover: {len(symbols)} spot USDT symbols and {len(listing.unsupported)} more with an "
        f"unsupported name, {len(candidates)} candidates, {len(exclusions)} excluded whatever "
        f"their prices ({counts or 'none'})"
    )
    multipliers = sum(multiplier != 1 for _, multiplier in perpetuals.values())
    _say(
        f"discover: {len(listed_futures)} futures USDT symbols, {len(futures_symbols)} of them "
        f"possible perpetuals with an archive by end_month, {len(perpetuals)} candidates with a "
        f"perpetual, {_multipliers(multipliers)}"
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
    names = _archive_symbols(args.kind, mine, discovery.perpetuals)  # a perpetual's own name
    entries: list[ManifestEntry] = []
    absent: list[dict[str, str]] = []
    failures: list[str] = []  # every refused archive of the shard, up to MAX_FETCH_FAILURES
    archives = [
        (symbol, month) for symbol in names for month in discovery.months[args.kind][symbol]
    ]
    for symbol, month in archives:
        try:
            result = fetch_verified(
                run.transport, args.kind, symbol, month, run.config, sleep=run.sleep, log=_log
            )
        except (ValueError, OSError) as exc:  # a checksum, a 4xx, a size breach, a transport
            failures.append(f"{symbol} {args.kind} {month}: {exc}")
            if len(failures) == MAX_FETCH_FAILURES:
                break
            continue
        if result is None:
            absent.append({"symbol": symbol, "month": month})
            continue
        entry, content = result
        _store(args.cache.joinpath(*entry.path.strip("/").split("/")), content)
        entries.append(entry)
    if failures:  # fail closed: no piece, so no later stage can take the shard as complete
        stopped = (
            f" (stopped at {MAX_FETCH_FAILURES} failures)"
            if len(failures) == MAX_FETCH_FAILURES
            else ""
        )
        raise ValueError(
            f"fetch {args.kind} shard {index}/{count}: {len(failures)} archives failed{stopped}, "
            "so no manifest piece is written:\n" + "\n".join(f"  {line}" for line in failures)
        )
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
    held = f" ({len(names)} with a perpetual)" if args.kind in FUTURES_KINDS else ""
    _say(
        f"fetch {args.kind} shard {index}/{count}: {len(mine)} symbols{held}, "
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
    daily = _daily_series(daily_pieces.entries, args.cache, run, daily_pieces.absent)
    ranked = _ranked(_universes(discovery, daily, config, None))  # the candidates stage's
    if hourly_pieces is None:
        _write_lines(args.out / "candidates.txt", ranked)
        _say(f"select candidates: {len(ranked)} symbols ranked in a top {HOURLY_RANK_DEPTH}")
        return 0
    _require_coverage(hourly_pieces, "spot_1h", ranked, _RANKED)
    usable, _ = _usable_hours(hourly_pieces.entries, args.cache, run)
    universes = _universes(discovery, daily, config, usable)
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
    daily = _daily_series(entries, cache, run, pieces.absent)
    ranked = _ranked(_universes(discovery, daily, config, None))  # the candidates stage's
    for kind in HOURLY_KINDS:
        _require_coverage(pieces, kind, ranked, _RANKED)
    # The read that gives every candidate's usable hours also counts the selected symbols'
    # spot rows for the pre-flight; their series are read again for their coin packs (P32).
    selected = sorted({symbol for universe in expected for symbol in universe["selected"]})
    usable, spot_rows = _usable_hours(entries, cache, run, frozenset(selected))
    universes = _universes(discovery, daily, config, usable)
    del usable
    if _universe_document(universes) != expected:
        raise ValueError(
            f"{args.universe}: the universes recomputed here differ from select-final's, so "
            "the archives or the code differ between the two jobs"
        )

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
        "daily pack",
    )
    del daily  # the daily bars are not needed past their pack

    # Futures and funding archives, and so every futures structure, are keyed by the perpetual.
    hourly = _Hourly(
        spot=_grouped(entries, "spot_1h"),
        futures=_grouped(entries, "futures_1h"),
        funding=_grouped(entries, "funding"),
        absent=pieces.absent,
        snapshots=snapshots,
        cache=cache,
        run=run,
    )
    perpetuals = {s: discovery.perpetuals[s] for s in selected if s in discovery.perpetuals}
    # The pre-flight: the coin packs' rows, bars as read, one futures series at a time.
    spot_total = sum(spot_rows.values())
    futures_total = sum(len(_futures_read(name, hourly).bars) for name, _ in perpetuals.values())
    _say(
        f"pack pre-flight: {len(selected)} coin packs to build, {spot_total + futures_total} "
        f"hourly rows as read ({spot_total} spot, {futures_total} futures)"
    )
    coins: dict[str, tuple[str, str, int]] = {}
    packed: dict[str, dict[str, object]] = {}  # coin -> its perpetual, for the index
    for number, coin in enumerate(selected, start=1):
        label = f"coin pack {number}/{len(selected)}"
        coins[coin], entry = _coin_pack(coin, perpetuals.get(coin), hourly, args.out, label)
        if entry is not None:
            packed[coin] = entry
    packs["hourly_index"] = _write_pack(
        args.out / HOURLY_INDEX,
        hourly_index_document(
            config, coins=coins, perpetuals=packed, config_sha256=run.config_sha256
        ),
        "hourly index",
    )
    largest = max((size for _, _, size in coins.values()), default=0)
    multipliers = sum(entry["multiplier"] != 1 for entry in packed.values())
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
            "coin_packs": len(coins),
            "largest_coin_pack_json_bytes": largest,
            "hourly_rows": spot_total + futures_total,
            "perpetuals": len(packed),
            "multiplier_perpetuals": multipliers,
        },
    )
    _say(f"pack: {len(coins)} coin packs, the largest {largest} bytes of canonical JSON")
    _say(
        f"pack: {len(universes)} universe months, {len(selected)} symbols ever selected, "
        f"{len(packed)} with a perpetual, {_multipliers(multipliers)}, {len(entries)} archives"
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


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    transport: Transport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], datetime] = _utc_now,
) -> int:
    """Run one stage: 0 on success, 1 on a refusal (its reason on standard error).

    ``transport``, ``sleep`` and ``clock`` replace the guarded ``HttpTransport``, the retry
    sleep and the UTC clock (tests)."""
    args = build_parser().parse_args(argv)
    try:
        config = load_data_config(args.config)
        run = _Run(
            config=config,
            config_sha256=_sha256(args.config.read_bytes()),
            transport=HttpTransport() if transport is None else transport,
            sleep=sleep,
            clock=clock,
        )
        return COMMANDS[args.command](args, run)
    except (ValueError, OSError) as exc:  # OSError: a missing input or an existing output
        _log(f"v4_data {args.command}: refused: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
