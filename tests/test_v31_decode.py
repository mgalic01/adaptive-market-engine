"""Pinned archive months decoded into V3.1 inputs (synthetic archives only)."""

import hashlib
import io
import re
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.driver.decode import decode_minute_month, decode_month

HOUR = 3_600_000
MINUTE = 60_000
MONTH_HOURS = 672  # February 2021
KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)
FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate"


def month_start(month: str) -> int:
    return int(datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC).timestamp()) * 1000


def zipped(member: str, text: str) -> bytes:
    """A one-member zip with a fixed timestamp, so the same text always gives the same bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo(member, (2021, 3, 1, 0, 0, 0)), text)
    return buffer.getvalue()


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def candle(open_ms: int, step: int, price: int, *, close_ms: int | None = None) -> str:
    """A 12-column kline row; the close time is the step's last millisecond unless given."""
    close = open_ms + step - 1 if close_ms is None else close_ms
    return f"{open_ms},{price},{price + 1},{price - 1},{price},10,{close},1000,5,4,400,0"


def bad_candle(open_ms: int, step: int) -> str:
    """A row the reader cannot trust: its low is above its open."""
    return f"{open_ms},100,90,110,100,10,{open_ms + step - 1},1000,5,4,400,0"


def hourly_text(start: int, *, missing=(), repaired=(), bad=()) -> str:
    """February 2021's hours; ``missing`` have no row, ``bad`` an untrusted one and
    ``repaired`` a close time one millisecond late."""
    rows = []
    for i in range(MONTH_HOURS):
        open_ms = start + i * HOUR
        if i in missing:
            continue
        if i in bad:
            rows.append(bad_candle(open_ms, HOUR))
        elif i in repaired:
            rows.append(candle(open_ms, HOUR, 100 + i % 50, close_ms=open_ms + HOUR))
        else:
            rows.append(candle(open_ms, HOUR, 100 + i % 50))
    return "\n".join(rows) + "\n"


def kline_entry(kind, symbol, month, content, *, status="eligible", masked=(), repaired=()):
    market = "spot" if kind == "spot" else "futures/um"
    return {
        "kind": kind,
        "symbol": symbol,
        "month": month,
        "path": f"/data/{market}/monthly/klines/{symbol}/1h/{symbol}-1h-{month}.zip",
        "sha256": sha(content),
        "status": status,
        "masked_hours": sorted(masked),
        "repaired_hours": sorted(repaired),
    }


def funding_entry(symbol, month, content, *, status="eligible", rows=0):
    return {
        "kind": "funding",
        "symbol": symbol,
        "month": month,
        "path": f"/data/futures/um/monthly/fundingRate/{symbol}/{symbol}-fundingRate-{month}.zip",
        "sha256": sha(content),
        "status": status,
        "rows": rows,
        "interval_hours": 8,
        "expected_slots": 90,
        "reasons": [],
    }


def minute_entry(symbol, month, content, *, interval="1m", status="ok"):
    return {
        "symbol": symbol,
        "month": month,
        "interval": interval,
        "sha256": sha(content),
        "status": status,
        "url": f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/"
        f"{symbol}-1m-{month}.zip",
    }


def february_spot():
    """A spot month with one missing, one repaired and one untrusted hour."""
    start = month_start("2021-02")
    content = zipped(
        "BTCUSDT-1h-2021-02.csv", hourly_text(start, missing={5}, repaired={9}, bad={12})
    )
    absent = {start + i * HOUR for i in (5, 9, 12)}
    entry = kline_entry(
        "spot", "BTCUSDT", "2021-02", content, masked=absent, repaired={start + 9 * HOUR}
    )
    return entry, content, start, absent


@pytest.mark.parametrize("kind", ["spot", "futures"])
def test_hourly_month_drops_masked_and_repaired_hours(kind):
    start = month_start("2021-02")
    text = hourly_text(start, missing={5}, repaired={9}, bad={12})
    if kind == "futures":
        text = KLINE_HEADER + "\n" + text
    content = zipped("BTCUSDT-1h-2021-02.csv", text)
    absent = {start + i * HOUR for i in (5, 9, 12)}
    entry = kline_entry(
        kind, "BTCUSDT", "2021-02", content, masked=absent, repaired={start + 9 * HOUR}
    )

    month = decode_month(entry, content)

    assert (month.kind, month.symbol, month.month, month.status) == (
        kind,
        "BTCUSDT",
        "2021-02",
        "eligible",
    )
    opens = [bar.open_ms for bar in month.hourly]
    assert opens == sorted(set(range(start, start + MONTH_HOURS * HOUR, HOUR)) - absent)
    assert month.missing_hours == absent
    assert month.funding == ()
    assert month.hourly[0] == Kline(start, D(100), D(101), D(99), D(100), D(10), D(1000), D(4))
    assert all(type(bar.open) is D and type(bar.volume) is D for bar in month.hourly)


def test_excluded_hourly_month_is_decoded_and_keeps_its_status():
    start = month_start("2021-02")
    missing = set(range(0, 200))  # far past the 17% bound
    content = zipped("ETHUSDT-1h-2021-02.csv", hourly_text(start, missing=missing))
    absent = {start + i * HOUR for i in missing}
    entry = kline_entry("spot", "ETHUSDT", "2021-02", content, status="excluded", masked=absent)

    month = decode_month(entry, content)

    assert month.status == "excluded"
    assert len(month.hourly) == MONTH_HOURS - 200
    assert month.hourly[0].open_ms == start + 200 * HOUR
    assert month.missing_hours == absent


def test_excluded_funding_month_is_decoded_with_its_intervals():
    start = month_start("2022-11")
    settled = [
        (start + 4, 8, "0.00010000"),
        (start + 8 * HOUR + 3, 8, "-0.00005000"),
        (start + 16 * HOUR + 2, 8, "0.00020000"),
        (start + 24 * HOUR + 5, 4, "0.00003000"),
        (start + 28 * HOUR + 1, 4, "0.00001000"),
        (start + 32 * HOUR + 6, 4, "0.00002000"),
    ]
    text = "\n".join([FUNDING_HEADER, *(f"{t},{i},{r}" for t, i, r in settled)]) + "\n"
    content = zipped("SOLUSDT-fundingRate-2022-11.csv", text)
    entry = funding_entry("SOLUSDT", "2022-11", content, status="excluded", rows=len(settled))

    month = decode_month(entry, content)

    assert month.status == "excluded"
    assert month.funding == tuple(FundingRecord(t, i, D(r)) for t, i, r in settled)
    assert [record.interval_hours for record in month.funding] == [8, 8, 8, 4, 4, 4]
    assert month.hourly == ()
    assert month.missing_hours == frozenset()


def test_sha256_mismatch_is_refused():
    entry, content, _, _ = february_spot()

    with pytest.raises(ValueError, match=re.escape(str(entry["path"]))):
        decode_month(entry, content + b"\x00")


def test_content_must_be_bytes():
    entry, content, _, _ = february_spot()

    with pytest.raises(ValueError, match=re.escape(str(entry["path"]))):
        decode_month(entry, bytearray(content))  # type: ignore[arg-type]


@pytest.mark.parametrize("month", ["2025-01", "2025-02", "2026-10"])
def test_a_2025_month_entry_is_refused(month):
    entry = kline_entry("futures", "BTCUSDT", month, b"unread")
    entry["sha256"] = "0" * 64  # a hash check would say so instead

    with pytest.raises(ValueError, match="reserved boundary"):
        decode_month(entry, b"not an archive")


def test_a_missing_month_is_refused():
    entry = {
        "kind": "spot",
        "symbol": "DOGEUSDT",
        "month": "2018-06",
        "path": "/data/spot/monthly/klines/DOGEUSDT/1h/DOGEUSDT-1h-2018-06.zip",
        "sha256": None,
        "status": "missing",
    }

    with pytest.raises(ValueError, match=re.escape(entry["path"])):
        decode_month(entry, b"")


def test_an_archive_with_another_member_is_refused():
    start = month_start("2021-02")
    content = zipped("ETHUSDT-1h-2021-02.csv", hourly_text(start))
    entry = kline_entry("spot", "BTCUSDT", "2021-02", content)

    with pytest.raises(ValueError, match=re.escape(entry["path"])):
        decode_month(entry, content)


@pytest.mark.parametrize(
    ("key", "change"),
    [
        ("masked_hours", lambda hours: hours[1:]),
        ("masked_hours", lambda hours: [*hours, hours[-1] + HOUR]),
        ("repaired_hours", lambda hours: []),
    ],
)
def test_hours_that_differ_from_the_pinned_entry_are_refused(key, change):
    entry, content, _, _ = february_spot()
    entry[key] = change(entry[key])

    with pytest.raises(ValueError, match=re.escape(entry["path"])):
        decode_month(entry, content)


def test_the_same_bytes_decode_the_same():
    entry, content, _, _ = february_spot()

    assert decode_month(entry, content) == decode_month(dict(entry), bytes(content))


def minute_text(start: int, minutes: int, *, bad=(), repaired=()) -> str:
    rows = []
    for i in range(minutes):
        open_ms = start + i * MINUTE
        if i in bad:
            rows.append(bad_candle(open_ms, MINUTE))
        elif i in repaired:
            rows.append(candle(open_ms, MINUTE, 100 + i % 50, close_ms=open_ms + MINUTE))
        else:
            rows.append(candle(open_ms, MINUTE, 100 + i % 50))
    return "\n".join(rows) + "\n"


def test_minute_month_streams_in_order():
    start = month_start("2021-02")
    content = zipped("ADAUSDT-1m-2021-02.csv", minute_text(start, 90))
    entry = minute_entry("ADAUSDT", "2021-02", content)

    bars = decode_minute_month(entry, content)

    assert isinstance(bars, Iterator)
    first = next(bars)
    assert first == Kline(start, D(100), D(101), D(99), D(100), D(10), D(1000), D(4))
    assert [first.open_ms, *(bar.open_ms for bar in bars)] == [
        start + i * MINUTE for i in range(90)
    ]


def test_minute_month_drops_repaired_minutes_and_untrusted_hours():
    start = month_start("2021-02")
    text = minute_text(start, 180, bad={70}, repaired={130})
    content = zipped("ADAUSDT-1m-2021-02.csv", text)
    entry = minute_entry("ADAUSDT", "2021-02", content)

    opens = [bar.open_ms for bar in decode_minute_month(entry, content)]

    # Hour 1 holds the untrusted row, so none of its minutes survive; hour 2 loses one.
    assert opens == [start + i * MINUTE for i in [*range(60), *range(120, 130), *range(131, 180)]]


def test_minute_month_with_a_wrong_hash_is_refused_before_it_is_read():
    start = month_start("2021-02")
    content = zipped("ADAUSDT-1m-2021-02.csv", minute_text(start, 5))
    entry = minute_entry("ADAUSDT", "2021-02", content)

    with pytest.raises(ValueError, match=re.escape(entry["url"])):
        decode_minute_month(entry, content + b"\x00")  # raised by the call, not by iterating


@pytest.mark.parametrize("month", ["2025-01", "2025-06"])
def test_a_2025_minute_entry_is_refused_before_it_is_read(month):
    entry = minute_entry("ADAUSDT", month, b"unread")
    entry["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="reserved boundary"):
        decode_minute_month(entry, b"not an archive")


@pytest.mark.parametrize(("key", "value"), [("interval", "1h"), ("status", "missing")])
def test_only_an_ok_minute_archive_is_decoded(key, value):
    start = month_start("2021-02")
    content = zipped("ADAUSDT-1m-2021-02.csv", minute_text(start, 5))
    entry = minute_entry("ADAUSDT", "2021-02", content)
    entry[key] = value

    with pytest.raises(ValueError, match=re.escape(entry["url"])):
        decode_minute_month(entry, content)


def test_an_unreadable_minute_archive_is_refused():
    content = zipped("ADAUSDT-1m-2021-02.csv", "not,a,candle\n")
    entry = minute_entry("ADAUSDT", "2021-02", content)

    with pytest.raises(ValueError, match=re.escape(entry["url"])):
        list(decode_minute_month(entry, content))
