"""Synthetic monthly archives only; no network or historical dataset reads."""

import hashlib
import io
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from fetch_v3_data import KLINE_HEADER, ArchiveObject, archive_path, inspect_archive  # noqa: E402

from crypto_grid_bot.backtest.klines import month_bounds_ms  # noqa: E402


def fixture(kind="futures", *, missing=0, repaired=False, header=False):
    start, end = month_bounds_ms("2024-02")
    if kind == "funding":
        text = "calc_time,funding_interval_hours,last_funding_rate\n" + "".join(
            f"{stamp + 47},8,0.0001\n" for stamp in range(start + missing * 28800000, end, 28800000)
        )
        member = "BTCUSDT-fundingRate-2024-02.csv"
    else:
        text = KLINE_HEADER + "\n" if header else ""
        for stamp in range(start + missing * 3600000, end, 3600000):
            close = stamp + (3599998 if repaired and stamp == start else 3599999)
            text += f"{stamp},10,12,9,11,1,{close},10,1,0.5,5,0\n"
        member = "BTCUSDT-1h-2024-02.csv"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    raw = stream.getvalue()
    obj = ArchiveObject(
        archive_path(kind, "BTCUSDT", "2024-02"), hashlib.sha256(raw).hexdigest(), raw
    )
    return inspect_archive(obj, kind, "BTCUSDT", "2024-02"), raw


@pytest.mark.parametrize("kind,header", [("spot", False), ("futures", False), ("futures", True)])
def test_verified_month_keeps_exact_bars_and_aggregates(kind, header):
    from v3_replay_inputs import decode_inventory_archive

    entry, raw = fixture(kind, header=header)
    result = decode_inventory_archive(entry, raw)
    assert len(result.hourly) == 696 and len(result.daily) == 29
    assert result.daily[0].volume == Decimal(24)
    assert result.daily[0].high == Decimal(12)
    assert not result.funding and not result.masked_hours
    assert result.status == "eligible"


def test_missing_and_repaired_hours_are_not_executable():
    from v3_replay_inputs import decode_inventory_archive

    entry, raw = fixture(missing=5)
    result = decode_inventory_archive(entry, raw)
    assert len(result.hourly) == 691 and len(result.daily) == 28
    assert len(result.masked_hours) == 5
    entry, raw = fixture(repaired=True)
    result = decode_inventory_archive(entry, raw)
    assert len(result.hourly) == 695
    assert len(result.masked_hours) == 1
    assert result.daily[0].volume == Decimal(23)


def test_funding_preserves_raw_millisecond_timestamps():
    from v3_replay_inputs import decode_inventory_archive

    entry, raw = fixture("funding")
    result = decode_inventory_archive(entry, raw)
    assert len(result.funding) == 87
    assert result.funding[0].calc_time_ms == month_bounds_ms("2024-02")[0] + 47
    assert result.funding[0].rate == Decimal("0.0001")
    assert not result.hourly and not result.daily


@pytest.mark.parametrize("kind,missing", [("futures", 200), ("spot", 200), ("funding", 1)])
def test_excluded_month_never_supplies_replay_records(kind, missing):
    from v3_replay_inputs import decode_inventory_archive

    entry, raw = fixture(kind, missing=missing)
    result = decode_inventory_archive(entry, raw)
    assert result.status == "excluded"
    assert not result.hourly and not result.daily and not result.funding


@pytest.mark.parametrize("damage", ["hash", "statistics", "reserved", "missing_bytes"])
def test_mismatched_or_reserved_input_is_rejected(damage):
    from v3_replay_inputs import decode_inventory_archive

    entry, raw = fixture()
    if damage == "hash":
        raw += b"changed"
    elif damage == "statistics":
        entry["daily_bars"] = 28
    elif damage == "reserved":
        entry["month"] = "2025-01"
    else:
        raw = None
    with pytest.raises(ValueError):
        decode_inventory_archive(entry, raw)


def test_missing_entry_is_explicit_and_cannot_hide_bytes():
    from v3_replay_inputs import decode_inventory_archive

    entry = inspect_archive(None, "spot", "BTCUSDT", "2024-02")
    result = decode_inventory_archive(entry, None)
    assert result.status == "missing" and not result.hourly
    with pytest.raises(ValueError):
        decode_inventory_archive(entry, b"unexpected")
