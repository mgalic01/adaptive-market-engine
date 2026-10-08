"""Request planning and reuse provenance, using manifest metadata only."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def test_fixed_request_plan_covers_universe_and_never_reserved_months():
    from fetch_v3_data import SYMBOLS
    from v3_inventory import planned_requests

    requests = planned_requests()
    assert len(requests) == len(set(requests)) == 2710
    assert {symbol for _, symbol, _ in requests} == SYMBOLS
    for kind, symbol, month in requests:
        assert "2017-01" <= month <= "2024-12"
        if kind == "spot":
            assert month >= "2018-06"
        assert (kind, symbol, "2024-12") in requests


def manifest_bytes(**changes):
    row = {
        "symbol": "BTCUSDT",
        "month": "2024-02",
        "interval": "1h",
        "status": "ok",
        "sha256": "a" * 64,
        "url": "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2024-02.zip",
    }
    row.update(changes)
    return json.dumps({"files": [row]}).encode()


def test_spot_reuse_map_preserves_committed_checksum_and_cache_layout(tmp_path):
    from v3_inventory import spot_reuse_pins

    raw = manifest_bytes()
    requests = [("spot", "BTCUSDT", "2024-02"), ("spot", "ADAUSDT", "2024-02")]
    pins = spot_reuse_pins(raw, hashlib.sha256(raw).hexdigest(), tmp_path, requests)
    assert len(pins) == 1
    path, pin = next(iter(pins.items()))
    assert pin.sha256 == "a" * 64
    assert pin.local_path == tmp_path / "binance" / path.lstrip("/")
    assert not pin.local_path.exists()  # Metadata loading does not read/download archives.


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "https://evil.test/archive.zip"},
        {"sha256": "bad"},
        {"status": "unknown"},
        {"interval": "1m"},
        {"symbol": "ETHUSDT"},
    ],
)
def test_spot_reuse_rejects_unpinned_or_missing_requested_existing_rows(tmp_path, changes):
    from v3_inventory import spot_reuse_pins

    raw = manifest_bytes(**changes)
    with pytest.raises(ValueError):
        spot_reuse_pins(
            raw, hashlib.sha256(raw).hexdigest(), tmp_path, [("spot", "BTCUSDT", "2024-02")]
        )


def test_spot_reuse_rejects_wrong_manifest_digest_and_duplicate_identity(tmp_path):
    from v3_inventory import spot_reuse_pins

    raw = manifest_bytes()
    requests = [("spot", "BTCUSDT", "2024-02")]
    with pytest.raises(ValueError, match="manifest hash"):
        spot_reuse_pins(raw, "b" * 64, tmp_path, requests)
    doc = json.loads(raw)
    doc["files"] *= 2
    raw = json.dumps(doc).encode()
    with pytest.raises(ValueError, match="duplicate"):
        spot_reuse_pins(raw, hashlib.sha256(raw).hexdigest(), tmp_path, requests)


def test_spot_reuse_records_missing_as_no_pin_and_rejects_reserved_request(tmp_path):
    from v3_inventory import spot_reuse_pins

    raw = manifest_bytes(status="missing", sha256=None)
    digest = hashlib.sha256(raw).hexdigest()
    assert spot_reuse_pins(raw, digest, tmp_path, [("spot", "BTCUSDT", "2024-02")]) == {}
    with pytest.raises(ValueError):
        spot_reuse_pins(raw, digest, tmp_path, [("spot", "BTCUSDT", "2025-01")])
