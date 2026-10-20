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
must cover every candidate, and the hourly ones every symbol the candidates stage ranked in a
top 20 (``candidates.txt``), checked from the daily archives before any hourly one is read. A
symbol excluded whatever its prices is fetched for no kind; the daily pack records its reason.
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
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict
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
    MANIFEST_FORMAT,
    UNIVERSE_FORMAT,
    _daily_series,
    _funding,
    _grouped,
    _load_discovery,
    _load_manifests,
    _load_universe,
    _log,
    _ranked,
    _read_futures_hours,
    _read_series,
    _require_coverage,
    _Run,
    _sha256,
    _static_exclusions,
    _store,
    _universe_document,
    _universes,
    _usable_hours,
    parse_shard,
)
from crypto_grid_bot.v4.data.listing import discover_months, discover_spot_usdt_symbols
from crypto_grid_bot.v4.data.pack import daily_pack_document, hourly_pack_document, write_canonical
from crypto_grid_bot.v4.data.universe import HOURLY_RANK_DEPTH

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "v4_data.json"
# A pack whose canonical JSON is larger stops for a ruling on splitting it (ruling P23); the
# reader refuses anything over 2 GiB.
MAX_PACK_JSON_BYTES = 1_610_612_736
HOURLY_KINDS = ("spot_1h", "futures_1h", "funding")
VENUES = ("spot", "futures")
DATA_FORMAT = "v4-data/1"
DAILY_PACK = "daily.pack.json.gz"
HOURLY_PACK = "hourly.pack.json.gz"

# What the hourly pieces must cover: candidates.txt, the candidates stage's ranking. The final
# universes' ranking can be narrower, since their window can open later (the hourly check).
_RANKED = "symbols the candidates stage ranked in a top 20"


def _say(line: str) -> None:
    """A line of standard output: counts, sizes and pins only."""
    print(line, flush=True)


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
    daily = _daily_series(entries, cache, run)
    ranked = _ranked(_universes(discovery, daily, config, None))  # the candidates stage's
    for kind in HOURLY_KINDS:
        _require_coverage(pieces, kind, ranked, _RANKED)
    # The spot hourly series of the symbols select-final selected are kept from the one read
    # that gives every candidate's usable hours; they are used only if the universes match.
    keep = frozenset(symbol for universe in expected for symbol in universe["selected"])
    usable, spot_series = _usable_hours(entries, cache, run, keep)
    universes = _universes(discovery, daily, config, usable)
    del usable
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
