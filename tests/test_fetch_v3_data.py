"""No real network requests: validate the exact V3 fetch boundary with fake transport."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_v3_data import archive_path, fetch_verified_archive  # noqa: E402


@pytest.mark.parametrize(
    "kind,segment,suffix",
    [
        ("futures", "futures/um/monthly/klines/BTCUSDT/1h", "1h"),
        ("spot", "spot/monthly/klines/BTCUSDT/1h", "1h"),
        ("funding", "futures/um/monthly/fundingRate/BTCUSDT", "fundingRate"),
    ],
)
def test_canonical_paths(kind, segment, suffix):
    assert (
        archive_path(kind, "BTCUSDT", "2024-12") == f"/data/{segment}/BTCUSDT-{suffix}-2024-12.zip"
    )


def test_verified_archive_with_fake_transport():
    payload = b"synthetic archive bytes"
    path = archive_path("futures", "BTCUSDT", "2024-12")
    checksum = hashlib.sha256(payload).hexdigest()
    calls = []

    def fetch(request):
        calls.append(request)
        return (
            (checksum + "  " + path.rsplit("/", 1)[1] + "\n").encode()
            if request.endswith(".CHECKSUM")
            else payload
        )

    result = fetch_verified_archive("futures", "BTCUSDT", "2024-12", fetch)
    assert result.sha256 == checksum
    assert result.content == payload
    assert set(calls) == {path, path + ".CHECKSUM"}


@pytest.mark.parametrize(
    "kind,symbol,month",
    [
        ("futures", "BTCUSDT", "2025-01"),
        ("futures", "BTCUSDT", "2024-1"),
        ("futures", "../BTCUSDT", "2024-12"),
        ("futures", "UNKNOWN", "2024-12"),
        ("bad", "BTCUSDT", "2024-12"),
    ],
)
def test_bad_request_rejected_before_transport(kind, symbol, month):
    def forbidden(_):
        pytest.fail("transport called on invalid request")

    with pytest.raises(ValueError):
        fetch_verified_archive(kind, symbol, month, forbidden)


@pytest.mark.parametrize(
    "checksum", [None, b"bad", b"0" * 64 + b"  BTCUSDT-1h-2024-12.zip", b"0" * 64 + b"  other.zip"]
)
def test_missing_or_mismatched_checksum_rejected(checksum):
    with pytest.raises(ValueError):
        fetch_verified_archive(
            "futures",
            "BTCUSDT",
            "2024-12",
            lambda path: checksum if path.endswith(".CHECKSUM") else b"archive",
        )


def test_absent_archive_is_explicit():
    assert fetch_verified_archive("futures", "BTCUSDT", "2024-12", lambda _: None) is None


def test_archive_transport_rejects_reserved_or_noncanonical_before_connection(monkeypatch):
    import fetch_v3_data as module

    def forbidden(*args, **kwargs):
        pytest.fail("network connection attempted")

    monkeypatch.setattr(module, "HTTPSConnection", forbidden)
    transport = module.V3Transport()
    for path in [
        "https://evil.invalid",
        "/data/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2025-01.zip",
        archive_path("futures", "BTCUSDT", "2024-12") + "?month=2024-12",
    ]:
        with pytest.raises(ValueError):
            transport.archive(path)


@pytest.mark.parametrize(
    "status,expected", [(200, b"body"), (404, None), (302, "error"), (500, "error")]
)
def test_transport_status_and_cleanup(monkeypatch, status, expected):
    import fetch_v3_data as module

    calls = []

    class Response:
        def __init__(self):
            self.status = status

        def read(self, limit):
            assert limit > 0
            return b"body"

    class Connection:
        def __init__(self, host, timeout):
            calls.append((host, timeout))

        def request(self, method, path):
            calls.append((method, path))

        def getresponse(self):
            return Response()

        def close(self):
            calls.append("closed")

    monkeypatch.setattr(module, "HTTPSConnection", Connection)
    path = archive_path("futures", "BTCUSDT", "2024-12")
    if expected == "error":
        with pytest.raises(ValueError):
            module.V3Transport().archive(path)
    else:
        assert module.V3Transport().archive(path) == expected
    assert calls[0][0] == "data.binance.vision"
    assert calls[1] == ("GET", path)
    assert calls[-1] == "closed"


def test_futures_filters_requested_at_most_once(monkeypatch):
    import fetch_v3_data as module

    calls = []

    class Connection:
        def __init__(self, host, timeout):
            calls.append(host)

        def request(self, method, path):
            calls.append(path)

        def getresponse(self):
            class Response:
                status = 200

                def read(self, limit):
                    return b'{"symbols": []}'

            return Response()

        def close(self):
            pass

    monkeypatch.setattr(module, "HTTPSConnection", Connection)
    transport = module.V3Transport()
    assert transport.futures_filters() == b'{"symbols": []}'
    with pytest.raises(ValueError, match="once"):
        transport.futures_filters()
    assert calls == ["fapi.binance.com", "/fapi/v1/exchangeInfo"]


def test_transport_size_limit_is_enforced(monkeypatch):
    import fetch_v3_data as module

    closed = []

    class Connection:
        def __init__(self, host, timeout):
            pass

        def request(self, method, path):
            pass

        def getresponse(self):
            class Response:
                status = 200

                def read(self, limit):
                    return b"x" * limit

            return Response()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(module, "HTTPSConnection", Connection)
    monkeypatch.setattr(module, "MAX_ARCHIVE_BYTES", 3)
    with pytest.raises(ValueError, match="size limit"):
        module.V3Transport().archive(archive_path("futures", "BTCUSDT", "2024-12"))
    assert closed == [True]


def synthetic_archive(kind, header=False):
    import io
    import zipfile

    from fetch_v3_data import ArchiveObject

    from crypto_grid_bot.backtest.klines import month_bounds_ms

    start, end = month_bounds_ms("2024-02")
    if kind == "funding":
        text = "calc_time,funding_interval_hours,last_funding_rate\n" + "".join(
            f"{stamp},8,0.0001\n" for stamp in range(start, end, 8 * 3_600_000)
        )
        member = "BTCUSDT-fundingRate-2024-02.csv"
    else:
        text = "".join(
            f"{t},10,12,9,11,1,{t + 3599999},10,1,0.5,5,0\n" for t in range(start, end, 3_600_000)
        )
        if header:
            text = (
                "open_time,open,high,low,close,volume,close_time,quote_volume,count,taker_buy_volume,taker_buy_quote_volume,ignore\n"
                + text
            )
        member = "BTCUSDT-1h-2024-02.csv"
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    raw = out.getvalue()
    return ArchiveObject(
        archive_path(kind, "BTCUSDT", "2024-02"), hashlib.sha256(raw).hexdigest(), raw
    )


@pytest.mark.parametrize(
    "kind,header", [("futures", False), ("futures", True), ("spot", False), ("funding", False)]
)
def test_manifest_inspection_from_synthetic_archive(kind, header):
    from fetch_v3_data import inspect_archive

    archive = synthetic_archive(kind, header)
    entry = inspect_archive(archive, kind, "BTCUSDT", "2024-02")
    assert entry["status"] == "eligible"
    assert entry["sha256"] == archive.sha256
    assert entry["rows"] == (87 if kind == "funding" else 696)
    if kind != "funding":
        assert entry["daily_bars"] == 29
        assert entry["masked_hours"] == []


def test_manifest_missing_and_corrupt_are_distinct():
    from dataclasses import replace

    from fetch_v3_data import inspect_archive

    assert inspect_archive(None, "futures", "BTCUSDT", "2024-02")["status"] == "missing"
    archive = synthetic_archive("futures")
    with pytest.raises(ValueError, match="hash"):
        inspect_archive(replace(archive, sha256="0" * 64), "futures", "BTCUSDT", "2024-02")


def test_manifest_assembly_is_deterministic_and_pins_snapshots():
    import json

    from fetch_v3_data import SYMBOLS, assemble_manifest, inspect_archive

    symbols = [
        {
            "symbol": symbol,
            "quoteAsset": "USDT",
            "contractType": "PERPETUAL",
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                {
                    "filterType": "MARKET_LOT_SIZE",
                    "minQty": "0.001",
                    "maxQty": "100",
                    "stepSize": "0",
                },
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }
        for symbol in sorted(SYMBOLS)
    ]
    snapshot = json.dumps({"symbols": symbols}).encode()
    entries = [
        inspect_archive(synthetic_archive(kind), kind, "BTCUSDT", "2024-02")
        for kind in ("spot", "futures", "funding")
    ]
    a = assemble_manifest(entries, snapshot, snapshot, "a" * 64)
    b = assemble_manifest(list(reversed(entries)), snapshot, snapshot, "a" * 64)
    assert a == b
    doc = json.loads(a)
    assert doc["snapshots"]["futures"]["sha256"] == hashlib.sha256(snapshot).hexdigest()
    assert len(doc["filters"]["futures"]) == 10
    assert doc["filters"]["futures"]["BTCUSDT"]["step_size"] == "0.001"
    assert doc["replay_ready"] is False
    with pytest.raises(ValueError, match="duplicate"):
        assemble_manifest([*entries, entries[0]], snapshot, snapshot, "a" * 64)
