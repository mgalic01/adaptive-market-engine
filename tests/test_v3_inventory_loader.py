"""Load only generated inventory files; never retrieve market data."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.fixture
def inventory(tmp_path):
    from fetch_v3_data import SYMBOLS, assemble_manifest, inspect_archive
    from test_v3_replay_inputs import fixture
    from v3_inventory import coverage_diagnostics, planned_requests

    filters = [
        {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ]
    snapshot = json.dumps(
        {
            "symbols": [
                {"symbol": s, "quoteAsset": "USDT", "contractType": "PERPETUAL", "filters": filters}
                for s in sorted(SYMBOLS)
            ]
        }
    ).encode()
    entries = []
    for kind, symbol, month in planned_requests():
        if symbol == "BTCUSDT" and month == "2024-02":
            entry, raw = fixture(kind)
            entry["local_path"] = "archives/" + entry["path"].lstrip("/")
            path = tmp_path / entry["local_path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        else:
            entry = inspect_archive(None, kind, symbol, month)
        entries.append(entry)
    document = json.loads(assemble_manifest(entries, snapshot, snapshot, "a" * 64))
    document["coverage"] = coverage_diagnostics(entries)
    for market in ("spot", "futures"):
        relative = f"snapshots/{market}.json"
        document["snapshots"][market]["path"] = relative
        path = tmp_path / relative
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(snapshot)
    raw = (json.dumps(document) + "\n").encode()
    (tmp_path / "inventory.manifest.json").write_bytes(raw)
    return tmp_path, hashlib.sha256(raw).hexdigest(), document


def test_complete_inventory_is_bound_to_bytes_without_granting_replay_readiness(inventory):
    from v3_inventory_loader import load_inventory_inputs

    root, digest, _ = inventory
    loaded = load_inventory_inputs(root, digest)
    assert loaded.manifest_sha256 == digest and loaded.spec_sha256 == "a" * 64
    assert len(loaded.months) == 2710
    assert sum(len(m.hourly) for m in loaded.months) == 1392
    assert sum(len(m.funding) for m in loaded.months) == 87
    assert len(loaded.spot_filters) == len(loaded.futures_filters) == 10
    assert loaded.coverage["coverage_review_required"] is True
    assert loaded.replay_ready is False


@pytest.mark.parametrize("damage", ["archive", "snapshot", "manifest", "coverage", "reserved"])
def test_tampered_inputs_abort_before_any_dataset_is_returned(inventory, damage):
    from v3_inventory_loader import load_inventory_inputs

    root, digest, document = inventory
    if damage == "archive":
        entry = next(e for e in document["entries"] if e["status"] == "eligible")
        (root / entry["local_path"]).write_bytes(b"changed")
    elif damage == "snapshot":
        (root / "snapshots/futures.json").write_bytes(b"changed")
    elif damage == "manifest":
        (root / "inventory.manifest.json").write_bytes(b"changed")
    else:
        if damage == "coverage":
            document["coverage"]["first_test_quarter_candidate"] = "2020-01"
        else:
            document["entries"][0]["month"] = "2025-01"
        raw = json.dumps(document).encode()
        (root / "inventory.manifest.json").write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):
        load_inventory_inputs(root, digest)
