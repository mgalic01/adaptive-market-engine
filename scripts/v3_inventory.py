"""Offline V3 fetch planning and committed spot-manifest reuse provenance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from fetch_v3_data import (
    MAX_ARCHIVE_BYTES,
    SYMBOLS,
    ArchiveObject,
    InventoryTransport,
    PinnedArchive,
    V3Transport,
    archive_path,
    assemble_manifest,
    collect_inventory,
    inspect_archive,
)

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.data import mandatory_close_hour


def planned_requests() -> list[tuple[str, str, str]]:
    """Probe a fixed pre-launch horizon; absence is recorded, never inferred.

    Futures/funding discovery covers 2017-01..2024-12. This deliberately exceeds
    the experiment's eventual first-full-month range. Spot starts at the frozen
    2018-06 warmup bound. No discovery request is itself evidence of eligibility.
    """
    return [
        (kind, symbol, month)
        for kind in ("spot", "futures", "funding")
        for symbol in sorted(SYMBOLS)
        for year in range(2017, 2025)
        for number in range(1, 13)
        for month in [f"{year:04d}-{number:02d}"]
        if kind != "spot" or month >= "2018-06"
    ]


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate manifest JSON key")
        result[key] = value
    return result


def spot_reuse_pins(
    raw: bytes,
    expected_sha256: str,
    cache_root: Path,
    requests: list[tuple[str, str, str]],
) -> dict[str, PinnedArchive]:
    """Read metadata only; every requested non-ADA spot row must be accounted for.

    The caller must supply the hash of the committed source manifest. Missing
    archives have no byte pin. Present archives retain their original digest even
    if unreadable. Canonical cache paths are derived, never accepted from JSON.
    """
    if len(raw) > 32 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("source manifest hash or size mismatch")
    wanted = set()
    for kind, symbol, month in requests:
        archive_path(kind, symbol, month)
        if kind == "spot" and symbol != "ADAUSDT":
            wanted.add((symbol, month))
    document = json.loads(raw, object_pairs_hook=_object)
    if not isinstance(document, dict) or not isinstance(document.get("files"), list):
        raise ValueError("source manifest must contain files")
    seen: set[tuple[str, str]] = set()
    pins: dict[str, PinnedArchive] = {}
    for row in document["files"]:
        if not isinstance(row, dict):
            raise ValueError("invalid source manifest row")
        row_symbol, row_month = row.get("symbol"), row.get("month")
        if not isinstance(row_symbol, str) or not isinstance(row_month, str):
            raise ValueError("invalid source row identity")
        identity = (row_symbol, row_month)
        if row.get("interval") != "1h" or identity not in wanted:
            continue
        if identity in seen:
            raise ValueError("duplicate requested source row")
        seen.add(identity)
        path = archive_path("spot", row_symbol, row_month)
        if row.get("url") != "https://data.binance.vision" + path:
            raise ValueError("source row URL is not canonical spot archive")
        status, digest = row.get("status"), row.get("sha256")
        if status == "missing" and digest is None:
            continue
        if (
            status not in {"ok", "unreadable"}
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("present source archive requires recognized status and SHA256")
        pins[path] = PinnedArchive(cache_root / "binance" / path.lstrip("/"), digest)
    if seen != wanted:
        raise ValueError("requested existing spot archive is absent from source manifest")
    return pins


def _month_number(month: str) -> int:
    year, number = map(int, month.split("-"))
    return year * 12 + number - 1


def _month_name(number: int) -> str:
    year, month = divmod(number, 12)
    return f"{year:04d}-{month + 1:02d}"


def _first_full(rows: list[dict[str, Any]]) -> str | None:
    observed = [row for row in rows if type(row.get("first_open_ms")) is int]
    if not observed:
        return None
    first = min(observed, key=lambda row: row["first_open_ms"])
    month = str(first["month"])
    start, _ = month_bounds_ms(month)
    # A partial initial archive cannot establish a full initial calendar month.
    return month if first["first_open_ms"] == start else _month_name(_month_number(month) + 1)


def _unmasked(row: dict[str, Any]) -> frozenset[int]:
    first, last, masks = row.get("first_open_ms"), row.get("last_open_ms"), row.get("masked_hours")
    if type(first) is not int or type(last) is not int or not isinstance(masks, list):
        return frozenset()
    start, end = month_bounds_ms(row["month"])
    return frozenset(range(max(start, first), min(end, last + 3_600_000), 3_600_000)) - set(masks)


def coverage_diagnostics(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive review candidates from a complete fixed inventory, never authorize replay.

    The earliest observed candle establishes a conservative candidate first full
    month. An unavailable initial archive can hide earlier history; the raw inventory
    and candidates require review. These diagnostics do not claim a listing date.
    Missing close hours invalidate a run only when that run needs to close a position.
    Futures and spot-hold execution availability are reported separately.
    """
    expected = set(planned_requests())
    indexed: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in entries:
        identity = (row.get("kind"), row.get("symbol"), row.get("month"))
        if identity not in expected:
            raise ValueError("unexpected inventory identity")
        if identity in indexed:
            raise ValueError("duplicate inventory identity")
        kind, symbol, month = identity
        if row.get("path") != archive_path(kind, symbol, month):
            raise ValueError("noncanonical inventory path")
        if row.get("status") not in {"eligible", "excluded", "missing"}:
            raise ValueError("invalid inventory status")
        start, end = month_bounds_ms(month)
        for field in ("first_open_ms", "last_open_ms"):
            stamp = row.get(field)
            if stamp is not None and (
                type(stamp) is not int or stamp % 3_600_000 or not start <= stamp < end
            ):
                raise ValueError("invalid observed archive hour")
        masks = row.get("masked_hours", [])
        if not isinstance(masks, list) or any(
            type(t) is not int or t % 3_600_000 or not start <= t < end for t in masks
        ):
            raise ValueError("invalid archive masks")
        indexed[identity] = row
    if set(indexed) != expected:
        raise ValueError("coverage requires complete fixed request inventory")
    coins: dict[str, Any] = {}
    months = sorted({month for kind, _, month in expected if kind == "futures"})
    for symbol in sorted(SYMBOLS):
        spot_start = _first_full(
            [row for (kind, coin, _), row in indexed.items() if kind == "spot" and coin == symbol]
        )
        futures_start = _first_full(
            [
                row
                for (kind, coin, _), row in indexed.items()
                if kind == "futures" and coin == symbol
            ]
        )
        eligible = {
            month
            for month in months
            if spot_start is not None
            and futures_start is not None
            and month >= max(spot_start, futures_start)
            and all(
                indexed.get((kind, symbol, month), {}).get("status") == "eligible"
                for kind in ("spot", "futures", "funding")
            )
        }
        joined = min(eligible) if eligible else None
        days = None
        if spot_start is not None and futures_start is not None:
            days = max(
                0,
                (month_bounds_ms(futures_start)[0] - month_bounds_ms(spot_start)[0]) // 86_400_000,
            )
        exclusions = []
        for month in months:
            if joined is None or month <= joined or month in eligible:
                continue
            previous = _month_name(_month_number(month) - 1)
            exclusions.append(
                {
                    "month": month,
                    "causes": [
                        kind
                        for kind in ("spot", "futures", "funding")
                        if indexed.get((kind, symbol, month), {}).get("status") != "eligible"
                    ],
                    "previous_month_eligible": previous in eligible,
                    "futures_close_ms": mandatory_close_hour(
                        month, _unmasked(indexed[("futures", symbol, previous)])
                    ),
                    "hold_close_ms": mandatory_close_hour(
                        month, _unmasked(indexed[("spot", symbol, previous)])
                    ),
                }
            )
        coins[symbol] = {
            "first_full_spot_month_candidate": spot_start,
            "first_full_futures_month_candidate": futures_start,
            "first_portfolio_month_candidate": joined,
            "spot_history_calendar_days": days,
            "less_than_year_of_spot_history": days < 365 if days is not None else None,
            "eligible_months": sorted(eligible),
            "excluded_months": exclusions,
        }
    btc_start = coins["BTCUSDT"]["first_portfolio_month_candidate"]
    first_quarter = None
    count = 0
    if btc_start is not None:
        number = ((_month_number(btc_start) + 18 + 2) // 3) * 3
        if number <= _month_number("2024-10"):
            first_quarter = _month_name(number)
            count = (_month_number("2024-10") - number) // 3 + 1
    return {
        "coverage_review_required": True,
        "coins": coins,
        "first_test_quarter_candidate": first_quarter,
        "test_quarters_candidate": count,
    }


def build_inventory(
    output_dir: Path,
    cache_root: Path,
    source_spot_manifest: bytes,
    source_spot_sha256: str,
    spec_sha256: str,
    transport: InventoryTransport,
) -> Path:
    """Complete the collection diagnostics, leaving reviewed replay pins outstanding."""
    requests = planned_requests()
    reuse = spot_reuse_pins(source_spot_manifest, source_spot_sha256, cache_root, requests)
    path = collect_inventory(output_dir, requests, transport, spec_sha256, reuse=reuse)
    document = json.loads(path.read_bytes())
    document["source_spot_manifest_sha256"] = source_spot_sha256
    document["coverage"] = coverage_diagnostics(document["entries"])
    document["pending"] = [
        "reviewed first-full-month coverage and mandatory-close diagnostics",
        "committed snapshots, manifest and completing trial registration",
    ]
    temporary = output_dir / "inventory.manifest.json.tmp"
    temporary.write_bytes(
        (json.dumps(document, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    )
    temporary.replace(path)
    return path


def _read_pinned(path: Path, digest: str, limit: int) -> bytes:
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("invalid expected content hash")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("pinned input hash or size mismatch")
    return raw


def _local(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("inventory file must stay inside its output directory")
    return path


def verify_inventory(output_dir: Path, expected_sha256: str) -> dict[str, Any]:
    """Rehash and reinspect the saved inventory offline before evidence publication."""
    raw = _read_pinned(
        _local(output_dir, "inventory.manifest.json"), expected_sha256, 32 * 1024 * 1024
    )
    document = json.loads(raw, object_pairs_hook=_object)
    if document.get("replay_ready") is not False:
        raise ValueError("fetch inventory must remain unready for replay")
    snapshots = {}
    for market in ("spot", "futures"):
        pin = document["snapshots"][market]
        relative = f"snapshots/{market}.json"
        if pin.get("path") != relative:
            raise ValueError("noncanonical snapshot path")
        snapshots[market] = _read_pinned(
            _local(output_dir, relative), pin["sha256"], 8 * 1024 * 1024
        )
        if pin["bytes"] != len(snapshots[market]):
            raise ValueError("snapshot byte count mismatch")
    # Validate every identity/month/hash before opening any archive file.
    rebuilt = json.loads(
        assemble_manifest(
            document["entries"], snapshots["spot"], snapshots["futures"], document["spec_sha256"]
        )
    )
    if document["filters"] != rebuilt["filters"]:
        raise ValueError("parsed filter metadata mismatch")
    if document["coverage"] != coverage_diagnostics(document["entries"]):
        raise ValueError("coverage diagnostics mismatch")
    count = 0
    for entry in document["entries"]:
        archive = None
        if entry["status"] != "missing":
            relative = "archives/" + entry["path"].lstrip("/")
            if entry.get("local_path") != relative:
                raise ValueError("noncanonical local archive path")
            content = _read_pinned(_local(output_dir, relative), entry["sha256"], MAX_ARCHIVE_BYTES)
            archive = ArchiveObject(entry["path"], entry["sha256"], content)
            count += 1
        elif "local_path" in entry:
            raise ValueError("missing archive cannot have local path")
        checked = inspect_archive(archive, entry["kind"], entry["symbol"], entry["month"])
        recorded = {key: value for key, value in entry.items() if key != "local_path"}
        if checked != recorded:
            raise ValueError("archive diagnostics do not match verified bytes")
    return {"manifest_sha256": expected_sha256, "verified_archives": count, "verified_snapshots": 2}


def main(argv: list[str] | None = None) -> int:
    """Explicit fetch command is only for the separately reviewed owner-started task."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("plan", help="print discovery scope without opening any archives")
    verify = commands.add_parser("verify", help="reinspect a hash-pinned local inventory offline")
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--manifest-sha256", required=True)
    fetch = commands.add_parser(
        "fetch", help="owner-started task only: collect public development data"
    )
    fetch.add_argument("--output", type=Path, required=True)
    fetch.add_argument("--cache-dir", type=Path, required=True)
    fetch.add_argument("--spec-file", type=Path, required=True)
    fetch.add_argument("--spec-sha256", required=True)
    fetch.add_argument("--spot-manifest", type=Path, required=True)
    fetch.add_argument("--spot-manifest-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "verify":
        print(json.dumps(verify_inventory(args.output, args.manifest_sha256), sort_keys=True))
        return 0
    if args.command == "plan":
        requests = planned_requests()
        encoded = json.dumps(requests, separators=(",", ":")).encode("utf-8")
        print(
            json.dumps(
                {
                    "request_count": len(requests),
                    "symbols": sorted(SYMBOLS),
                    "spot_start": "2018-06",
                    "futures_discovery_start": "2017-01",
                    "last_month": "2024-12",
                    "request_plan_sha256": hashlib.sha256(encoded).hexdigest(),
                    "fetch_authorized": False,
                },
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    _read_pinned(args.spec_file, args.spec_sha256, 1024 * 1024)
    source = _read_pinned(args.spot_manifest, args.spot_manifest_sha256, 32 * 1024 * 1024)
    # Validate the complete reuse map before constructing the concrete transport.
    spot_reuse_pins(source, args.spot_manifest_sha256, args.cache_dir, planned_requests())
    path = build_inventory(
        args.output,
        args.cache_dir,
        source,
        args.spot_manifest_sha256,
        args.spec_sha256,
        V3Transport(),
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
