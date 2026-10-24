"""V3's input pack, rebuilt on GitHub and pinned to V3.1's digest: the ``v3_as_built`` arm's inputs.

V4's registered run compares itself with V3's frozen walk-forward selector, run unchanged on
V3's own inputs. V3.1's registered prepare built those inputs from V3's pinned archive inventory
and recorded the pack's pin as ``v3_pack_sha256`` in ``config/v3_1_run_manifest.json``. This
script rebuilds the same pack, reusing V3.1's reviewed code, and refuses anything that is not
exactly that pin. ``.github/workflows/v4-v3.yml`` (job ``pack``) runs it, so that no heavy work
runs on the owner's PC (owner rule 2026-10-19).

``--work W --out O [--repo R]`` (``R`` is the checkout, ``.`` by default):

1. Reads V3's inventory manifest ``config/datasets/v3-20261009/inventory.manifest.json`` and
   refuses it unless its SHA-256 is ``MANIFEST_SHA256``. It also refuses a snapshot that is not
   the one the manifest records and a month at or after 2025-01 (owner decision v4-d03: nothing
   from 2025 on is fetched before the registered run), all before the first request.
2. Lays out V3's collection under ``W/inventory`` as V3's own loader reads it, the layout of
   ``v31_driver.place_inventory``: the manifest's pinned bytes as ``inventory.manifest.json``,
   ``snapshots/{spot,futures}.json`` and the archives under ``archives/``.
3. Fetches every manifest entry whose status is not ``missing`` into ``W/inventory/archives/``
   with ``v31_fetch.fetch_entries``, as V3.1's prepare does (``V3Transport``, V3's own
   transport, against https://data.binance.vision), each archive verified against the SHA-256
   its entry pins.
4. Builds the pack ``O/v3-input.pack.json.gz`` with ``v31_v3_pack.build_v3_pack``, V3's frozen
   loader and assembly, over the calendar of ``config/v3-development-run.json``.
5. Exits 0 only if the pack's pin equals ``EXPECTED_PACK_SHA256``. Otherwise it removes the
   pack and exits 1. The pin covers the pack's whole content, the calendar included.

It refuses, writing no pack and exiting 1: a manifest, snapshot or calendar that is not the
registered one, an archive that is not as pinned (or that the host does not have), a month from
2025 on, a pack that already exists (it is left alone), a loader or assembly refusal, and any
other pin. A refusal is one line on standard error, naming no price.

Standard output carries the archive count, the bytes fetched and the pack's pin: counts, sizes
and a digest only, never a price (the logs are public).
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fetch_v3_data import V3Transport
from v31_driver import (
    INVENTORY_DIR,
    INVENTORY_KINDS,
    V3_PACK_FILE,
    place,
    present_entries,
    strict_json,
)
from v31_fetch import ArchiveTransport, fetch_entries
from v31_v3_pack import build_v3_pack

from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.trend.filters import MAX_SNAPSHOT_BYTES

# V3's inventory manifest, as committed, and the SHA-256 of its bytes (V3's registered pin;
# recompute it with ``sha256sum config/datasets/v3-20261009/inventory.manifest.json``).
COLLECTION_DIR = "config/datasets/v3-20261009"
MANIFEST_PATH = f"{COLLECTION_DIR}/inventory.manifest.json"
MANIFEST_SHA256 = "78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a"
# The calendar V3's run was registered with (``first_months``).
CONFIG_PATH = "config/v3-development-run.json"
# The pack V3.1's registered prepare built: ``v3_pack_sha256`` of config/v3_1_run_manifest.json
# (read it there; ``.github/workflows/v4-v3.yml``'s pack job prints the pin of the pack it builds).
EXPECTED_PACK_SHA256 = "8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee"
PACK_FILE = V3_PACK_FILE
SNAPSHOT_MARKETS = ("spot", "futures")
MAX_MANIFEST_BYTES = 32 * 1024 * 1024  # V3's loader reads the manifest with this limit
MAX_CONFIG_BYTES = 1024 * 1024


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v4_v3_pack.py", description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."), help="the checkout (default: .)")
    parser.add_argument(
        "--work", type=Path, required=True, help="where V3's collection is laid out and fetched"
    )
    parser.add_argument("--out", type=Path, required=True, help=f"the folder that gets {PACK_FILE}")
    return parser


def log(line: str) -> None:
    """Fetch progress, retries and refusals go to standard error; standard output is the
    result."""
    print(line, file=sys.stderr, flush=True)


def _read(path: Path, limit: int, what: str) -> bytes:
    """The bytes of ``path``, at most ``limit`` of them."""
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"{what}: larger than {limit} bytes")
    return raw


def _first_months(raw: bytes) -> dict[str, str]:
    """``first_months`` of V3's registered configuration, with the schema V3's
    ``bind_registered_inputs`` accepts (and V3.1's ``v3_registered_inputs`` checks)."""
    config = strict_json(raw, CONFIG_PATH)
    months = config.get("first_months") if isinstance(config, dict) else None
    if (
        not isinstance(config, dict)
        or set(config) != {"schema_version", "experiment", "first_months"}
        or type(config["schema_version"]) is not int
        or config["schema_version"] != 1
        or config["experiment"] != "v3"
        or not isinstance(months, dict)
        or any(
            type(symbol) is not str or type(month) is not str for symbol, month in months.items()
        )
    ):
        raise ValueError(f"{CONFIG_PATH}: not V3's registered run configuration")
    return dict(months)


def _snapshot_pin(inventory: dict[str, Any], market: str) -> str:
    """The SHA-256 the inventory manifest records for ``market``'s filter snapshot."""
    snapshots = inventory.get("snapshots")
    pin = snapshots.get(market) if isinstance(snapshots, dict) else None
    recorded = pin.get("sha256") if isinstance(pin, dict) else None
    if not isinstance(recorded, str):
        raise ValueError(f"{MANIFEST_PATH}: no SHA-256 recorded for the {market} filter snapshot")
    return recorded


def main(argv: Sequence[str] | None = None, *, transport: ArchiveTransport | None = None) -> int:
    """Build V3's input pack and check its pin; 0 with the counts and the pin on standard
    output, 1 on a refusal (on standard error). ``transport`` replaces ``V3Transport`` (tests)."""
    args = build_parser().parse_args(argv)
    try:
        return _run(args.repo, args.work, args.out, transport)
    except (ValueError, OSError, FeedError) as exc:  # OSError: a missing or existing path
        print(f"::error::v4_v3_pack: refused: {exc}", file=sys.stderr, flush=True)
        return 1


def _run(repo: Path, work: Path, out: Path, transport: ArchiveTransport | None) -> int:
    # Everything that can be refused offline is refused first: nothing is created or requested.
    manifest_raw = _read(repo / MANIFEST_PATH, MAX_MANIFEST_BYTES, "the inventory manifest")
    actual = hashlib.sha256(manifest_raw).hexdigest()
    if actual != MANIFEST_SHA256:
        raise ValueError(
            f"the inventory manifest {MANIFEST_PATH} has SHA-256 {actual}; "
            f"V3's registered manifest is {MANIFEST_SHA256}"
        )
    inventory = strict_json(manifest_raw, MANIFEST_PATH)
    if not isinstance(inventory, dict) or "entries" not in inventory or "files" in inventory:
        raise ValueError(f"{MANIFEST_PATH}: V3's inventory manifest (entries) required")
    snapshots: dict[str, bytes] = {}
    for market in SNAPSHOT_MARKETS:
        relative = f"{COLLECTION_DIR}/snapshots/{market}.json"
        raw = _read(repo / relative, MAX_SNAPSHOT_BYTES, f"the {market} filter snapshot")
        recorded = _snapshot_pin(inventory, market)
        if hashlib.sha256(raw).hexdigest() != recorded:
            raise ValueError(
                f"the {market} filter snapshot {relative} is not the one {MANIFEST_PATH} "
                f"records ({recorded})"
            )
        snapshots[market] = raw
    first_months = _first_months(_read(repo / CONFIG_PATH, MAX_CONFIG_BYTES, CONFIG_PATH))
    # Every entry that is not missing; a month at or after 2025-01 anywhere is refused.
    entries = present_entries(inventory, MANIFEST_PATH, INVENTORY_KINDS)
    pack = out / PACK_FILE
    if pack.exists() or pack.is_symlink():
        raise FileExistsError(f"{pack} exists; the pack is written once and this one is left alone")

    root = work / INVENTORY_DIR  # V3's collection layout (v31_driver.place_inventory)
    place(root / "inventory.manifest.json", manifest_raw)
    for market, raw in snapshots.items():
        place(root / "snapshots" / f"{market}.json", raw)
    host = V3Transport() if transport is None else transport
    count = total = 0
    for _entry, content in fetch_entries(entries, root / "archives", transport=host, log=log):
        count += 1
        total += len(content)
    print(f"v4_v3_pack: {count} archives, {total} bytes, each verified against its pinned SHA-256")
    sys.stdout.flush()

    out.mkdir(parents=True, exist_ok=True)
    try:
        pin = build_v3_pack(root, MANIFEST_SHA256, first_months, pack)
        if pin != EXPECTED_PACK_SHA256:
            raise ValueError(
                f"the V3 input pack's SHA-256 is {pin}; V3.1's registered pack pin is "
                f"{EXPECTED_PACK_SHA256}"
            )
    except BaseException:
        pack.unlink(missing_ok=True)  # the pack did not exist before this run
        raise
    print(f"v4_v3_pack: {PACK_FILE} {pack.stat().st_size} bytes, pin {pin}")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
