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
