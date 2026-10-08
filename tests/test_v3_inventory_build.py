"""Full inventory orchestration with a fake transport and synthetic source metadata."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


@pytest.mark.parametrize("reuse_snapshot", [False, True])
@pytest.mark.parametrize("with_archive", [False, True])
def test_build_inventory_adds_coverage_and_source_provenance_without_network(
    tmp_path, with_archive, reuse_snapshot, monkeypatch
):
    from fetch_v3_data import SYMBOLS, archive_path
    from v3_inventory import build_inventory, main, planned_requests, verify_inventory

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
    archive_bytes = b"checksum-valid but unreadable synthetic archive"
    archive_digest = hashlib.sha256(archive_bytes).hexdigest()
    archive_request = archive_path("spot", "ADAUSDT", "2024-02")

    class Fake:
        def archive(self, path):
            calls.append(path)
            if with_archive and path == archive_request:
                return archive_bytes
            if with_archive and path == archive_request + ".CHECKSUM":
                return (archive_digest + "  " + archive_request.rsplit("/", 1)[1]).encode()
            return None

        def spot_filters(self):
            calls.append("spot")
            return snapshot

        def futures_filters(self):
            assert not reuse_snapshot, "saved futures snapshot must prevent a second GET"
            calls.append("futures")
            return snapshot

    source_hash = hashlib.sha256(source).hexdigest()
    if reuse_snapshot:
        import v3_inventory

        monkeypatch.setattr(v3_inventory, "V3Transport", Fake)
        saved = tmp_path / "saved-futures.json"
        saved.write_bytes(snapshot)
        spec = tmp_path / "spec.md"
        spec.write_bytes(b"pinned spec")
        source_file = tmp_path / "source.json"
        source_file.write_bytes(source)
        assert (
            main(
                [
                    "fetch",
                    "--output",
                    str(tmp_path / "output"),
                    "--cache-dir",
                    str(tmp_path / "cache"),
                    "--spec-file",
                    str(spec),
                    "--spec-sha256",
                    hashlib.sha256(spec.read_bytes()).hexdigest(),
                    "--spot-manifest",
                    str(source_file),
                    "--spot-manifest-sha256",
                    source_hash,
                    "--reuse-futures-snapshot",
                    str(saved),
                    "--futures-snapshot-sha256",
                    hashlib.sha256(snapshot).hexdigest(),
                ]
            )
            == 0
        )
        path = tmp_path / "output/inventory.manifest.json"
        assert (path.parent / "snapshots/futures.json").read_bytes() == snapshot
    else:
        path = build_inventory(
            tmp_path / "output", tmp_path / "cache", source, source_hash, "a" * 64, Fake()
        )
    document = json.loads(path.read_bytes())
    assert len(document["entries"]) == 2710
    assert document["source_spot_manifest_sha256"] == source_hash
    assert document["coverage"]["coverage_review_required"] is True
    assert document["coverage"]["first_test_quarter_candidate"] is None
    assert document["replay_ready"] is False
    assert calls.count("spot") == 1
    assert calls.count("futures") == int(not reuse_snapshot)
    assert len(calls) == 2001 + int(with_archive) - int(reuse_snapshot)
    assert not any("/spot/" in call and "ADAUSDT" not in call for call in calls)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    verified = verify_inventory(path.parent, digest)
    assert verified["verified_archives"] == int(with_archive)
    assert verified["verified_snapshots"] == 2
    assert verified["manifest_sha256"] == digest
    assert main(["verify", "--output", str(path.parent), "--manifest-sha256", digest]) == 0
    if with_archive:
        local = path.parent / "archives" / archive_request.lstrip("/")
        local.write_bytes(b"changed archive")
        with pytest.raises(ValueError, match="hash"):
            verify_inventory(path.parent, digest)
        local.write_bytes(archive_bytes)
    (path.parent / "snapshots/futures.json").write_bytes(b"changed snapshot")
    with pytest.raises(ValueError, match="hash"):
        verify_inventory(path.parent, digest)
