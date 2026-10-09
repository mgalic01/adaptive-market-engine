"""Offline loading of verified collection inputs, without historical dispatch."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fetch_v3_data import MAX_ARCHIVE_BYTES, SYMBOLS
from v3_inventory import _local, _object, _read_pinned, verify_inventory
from v3_replay_inputs import DecodedMonth, decode_inventory_archive

from crypto_grid_bot.trend.filters import OrderFilters, parse_filter_snapshot


@dataclass(frozen=True, slots=True)
class InventoryInputs:
    manifest_sha256: str
    spec_sha256: str
    months: tuple[DecodedMonth, ...]
    spot_filters: dict[str, OrderFilters]
    futures_filters: dict[str, OrderFilters]
    coverage: dict[str, Any]
    replay_ready: Literal[False] = False


def load_inventory_inputs(root: Path, manifest_sha256: str) -> InventoryInputs:
    """Load a complete hash-pinned collection from local files only.

    Reinspection validates all 2710 identities and every present archive before
    returning anything. Re-read bytes are checked again against the same pins.
    Coverage remains a review candidate, not an approved portfolio calendar.
    The caller must own data-access authorization. This function never registers
    a trial, creates a replay-ready manifest, fetches data or starts a replay.
    """
    verify_inventory(root, manifest_sha256)
    document = json.loads(
        _read_pinned(_local(root, "inventory.manifest.json"), manifest_sha256, 32 * 1024 * 1024),
        object_pairs_hook=_object,
    )
    if document.get("schema_version") != 1 or document.get("experiment") != "v3":
        raise ValueError("unsupported V3 collection inventory")
    filters = {}
    for market in ("spot", "futures"):
        pin = document["snapshots"][market]
        raw = _read_pinned(_local(root, pin["path"]), pin["sha256"], 8 * 1024 * 1024)
        filters[market] = parse_filter_snapshot(
            raw, tuple(sorted(SYMBOLS)), futures=market == "futures"
        )
    months = []
    for entry in document["entries"]:
        archive_content = None
        if entry["status"] != "missing":
            archive_content = _read_pinned(
                _local(root, entry["local_path"]), entry["sha256"], MAX_ARCHIVE_BYTES
            )
        months.append(decode_inventory_archive(entry, archive_content))
    return InventoryInputs(
        manifest_sha256,
        document["spec_sha256"],
        tuple(months),
        filters["spot"],
        filters["futures"],
        document["coverage"],
    )
