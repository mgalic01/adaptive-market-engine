"""Full inventory orchestration with a fake transport and synthetic source metadata."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_build_inventory_adds_coverage_and_source_provenance_without_network(tmp_path):
    from fetch_v3_data import SYMBOLS, archive_path
    from v3_inventory import build_inventory, planned_requests

    rows = [
        {
            "symbol": symbol,
            "month": month,
            "interval": "1h",
            "status": "missing",
            "sha256": None,
            "url": "https://data.binance.vision" + archive_path(kind, symbol, month),
        }
        for kind, symbol, month in planned_requests()
        if kind == "spot" and symbol != "ADAUSDT"
    ]
    source = json.dumps({"files": rows}).encode()
    filters = [
        {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ]
    snapshot = json.dumps(
        {
            "symbols": [
                {
                    "symbol": symbol,
                    "quoteAsset": "USDT",
                    "contractType": "PERPETUAL",
                    "filters": filters,
                }
                for symbol in sorted(SYMBOLS)
            ]
        }
    ).encode()
    calls = []

    class Fake:
        def archive(self, path):
            calls.append(path)
            return None

        def spot_filters(self):
            calls.append("spot")
            return snapshot

        def futures_filters(self):
            calls.append("futures")
            return snapshot

    source_hash = hashlib.sha256(source).hexdigest()
    path = build_inventory(
        tmp_path / "output", tmp_path / "cache", source, source_hash, "a" * 64, Fake()
    )
    document = json.loads(path.read_bytes())
    assert len(document["entries"]) == 2710
    assert document["source_spot_manifest_sha256"] == source_hash
    assert document["coverage"]["coverage_review_required"] is True
    assert document["coverage"]["first_test_quarter_candidate"] is None
    assert document["replay_ready"] is False
    assert calls.count("spot") == calls.count("futures") == 1
    assert len(calls) == 2712
