"""Synthetic snapshot boundaries; no real market data or network access."""

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from test_v3_inventory_loader import inventory  # noqa: E402, F401


def snapshot(size):
    from fetch_v3_data import SYMBOLS

    filters = [
        {"filterType": "LOT_SIZE", "minQty": "1", "maxQty": "100", "stepSize": "1"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "1", "maxQty": "100", "stepSize": "0"},
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ]
    raw = json.dumps(
        {
            "symbols": [
                {"symbol": s, "quoteAsset": "USDT", "contractType": "PERPETUAL", "filters": filters}
                for s in sorted(SYMBOLS)
            ]
        }
    ).encode()
    return raw + b" " * (size - len(raw))


@pytest.mark.parametrize("market", ["spot", "futures"])
@pytest.mark.parametrize("size", [8 * 1024 * 1024 + 1, 32 * 1024 * 1024, 32 * 1024 * 1024 + 1])
def test_transport_and_parser_share_snapshot_boundary(monkeypatch, market, size):
    import fetch_v3_data as fetch

    from crypto_grid_bot.trend.filters import parse_filter_snapshot

    raw = snapshot(size)
    closed = []
    reads = []

    class Connection:
        def __init__(self, host, timeout):
            self.host = host

        def request(self, method, path):
            assert method == "GET"
            assert path == ("/api/v3/exchangeInfo" if market == "spot" else "/fapi/v1/exchangeInfo")

        def getresponse(self):
            class Response:
                status = 200

                def read(self, limit):
                    reads.append(limit)
                    return io.BytesIO(raw).read(limit)

            return Response()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(fetch, "HTTPSConnection", Connection)
    retrieve = getattr(fetch.V3Transport(), f"{market}_filters")
    if size > 32 * 1024 * 1024:
        with pytest.raises(ValueError, match=r"33554432.*exchangeInfo"):
            retrieve()
        if market == "futures":
            with pytest.raises(ValueError, match="only once"):
                retrieve()
        with pytest.raises(ValueError, match="size limit"):
            parse_filter_snapshot(raw, ("BTCUSDT",), futures=market == "futures")
    else:
        assert retrieve() == raw
        assert (
            str(
                parse_filter_snapshot(raw, ("BTCUSDT",), futures=market == "futures")[
                    "BTCUSDT"
                ].min_notional
            )
            == "5"
        )
    assert reads == [32 * 1024 * 1024 + 1]
    assert closed == [True]


@pytest.mark.parametrize("market", ["spot", "futures"])
def test_oversized_reused_snapshot_stops_before_output_or_transport(tmp_path, market):
    from fetch_v3_data import collect_inventory

    class Forbidden:
        def __getattr__(self, name):
            pytest.fail("oversized saved snapshot accessed transport")

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="size limit"):
        collect_inventory(
            output,
            [("spot", "BTCUSDT", "2024-02")],
            Forbidden(),
            "a" * 64,
            **{f"{market}_snapshot": snapshot(32 * 1024 * 1024 + 1)},
        )
    assert not output.exists()


@pytest.mark.parametrize("market", ["spot", "futures"])
@pytest.mark.parametrize("oversized", [False, True])
def test_reuse_cli_size_boundary_before_transport(tmp_path, monkeypatch, market, oversized):
    import v3_inventory

    raw = snapshot(32 * 1024 * 1024 + int(oversized))
    saved = tmp_path / "saved.json"
    saved.write_bytes(raw)

    def forbidden():
        pytest.fail("invalid preparation must not construct transport")

    monkeypatch.setattr(v3_inventory, "V3Transport", forbidden)
    # A missing spec is reached only after the saved snapshot passes size/hash/parse checks.
    expected = ValueError if oversized else FileNotFoundError
    with pytest.raises(expected):
        v3_inventory.main(
            [
                "fetch",
                "--output",
                str(tmp_path / "out"),
                "--cache-dir",
                str(tmp_path / "cache"),
                "--spec-file",
                str(tmp_path / "absent-spec"),
                "--spec-sha256",
                "a" * 64,
                "--spot-manifest",
                str(tmp_path / "absent-source"),
                "--spot-manifest-sha256",
                "b" * 64,
                f"--reuse-{market}-snapshot",
                str(saved),
                f"--{market}-snapshot-sha256",
                hashlib.sha256(raw).hexdigest(),
            ]
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("oversized_market", [None, "spot", "futures"])
def test_offline_verifier_and_loader_snapshot_boundary(inventory, oversized_market):  # noqa: F811
    from v3_inventory import verify_inventory
    from v3_inventory_loader import load_inventory_inputs

    root, _, document = inventory
    for market in ("spot", "futures"):
        path = root / f"snapshots/{market}.json"
        original = path.read_bytes()
        size = 32 * 1024 * 1024 + int(market == oversized_market)
        raw = original + b" " * (size - len(original))
        path.write_bytes(raw)
        document["snapshots"][market].update(bytes=size, sha256=hashlib.sha256(raw).hexdigest())
    raw = json.dumps(document).encode()
    (root / "inventory.manifest.json").write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if oversized_market is not None:
        for operation in (verify_inventory, load_inventory_inputs):
            with pytest.raises(ValueError, match="size"):
                operation(root, digest)
    else:
        assert verify_inventory(root, digest)["verified_snapshots"] == 2
        loaded = load_inventory_inputs(root, digest)
        assert len(loaded.spot_filters) == len(loaded.futures_filters) == 10


@pytest.mark.parametrize("oversized", [False, True])
def test_collection_injected_snapshot_boundary(tmp_path, oversized):
    from fetch_v3_data import collect_inventory

    raw = snapshot(32 * 1024 * 1024 + int(oversized))

    class Transport:
        def spot_filters(self):
            return raw

        def futures_filters(self):
            if oversized:
                pytest.fail("oversized spot response must stop before futures")
            return raw

        def archive(self, path):
            if oversized:
                pytest.fail("oversized snapshot must stop before archives")
            return None

    output = tmp_path / "output"
    if oversized:
        with pytest.raises(ValueError, match="oversized"):
            collect_inventory(output, [("spot", "BTCUSDT", "2024-02")], Transport(), "a" * 64)
        assert list((output / "snapshots").iterdir()) == []
        assert not (output / "inventory.manifest.json").exists()
    else:
        path = collect_inventory(output, [("spot", "BTCUSDT", "2024-02")], Transport(), "a" * 64)
        document = json.loads(path.read_bytes())
        assert document["snapshots"]["spot"]["bytes"] == 32 * 1024 * 1024
        assert document["snapshots"]["futures"]["sha256"] == hashlib.sha256(raw).hexdigest()
