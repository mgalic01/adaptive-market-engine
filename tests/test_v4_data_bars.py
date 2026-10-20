"""V4 data step: the readers of kline and funding archives, and the funding month rule.

Archives are small zips built in memory. The network is blocked for every test in this file
(the autouse fixture below), as in ``test_v4_data_archives.py``. The kline reader is the
repairing reader of spec v1 section 5 rule 1 (``backtest.klines.parse_rows_repaired``),
re-implemented for 2017 onward without the 2024 guard; one test replays seeded random
archives through both and compares them.
"""

from __future__ import annotations

import io
import random
import socket
import zipfile
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from crypto_grid_bot.backtest.klines import parse_rows_repaired
from crypto_grid_bot.v4.data.bars import (
    DailyBar,
    FundingRow,
    HourBar,
    KlineRead,
    funding_month_status,
    read_daily,
    read_funding,
    read_hourly,
)

HOUR = 3_600_000
DAY = 24 * HOUR
FEB = "2024-02"
SYMBOL = "BTCUSDT"
# The futures CSV header text; scripts/fetch_v3_data.py::KLINE_HEADER (checked below).
KLINE_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)
FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate"


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket; each attempt is counted."""
    attempts: list[str] = []

    def refuse(*args, **kwargs):
        attempts.append("socket")
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return attempts


# --- builders -----------------------------------------------------------------------------


def month_start(month: str) -> int:
    year, number = (int(part) for part in month.split("-"))
    return int(datetime(year, number, 1, tzinfo=UTC).timestamp()) * 1000


def month_end(month: str) -> int:
    year, number = (int(part) for part in month.split("-"))
    year, number = (year + 1, 1) if number == 12 else (year, number + 1)
    return int(datetime(year, number, 1, tzinfo=UTC).timestamp()) * 1000


def kline(
    open_ms: int,
    *,
    step: int = HOUR,
    us: bool = False,
    close: int | None = None,
    prices: tuple[str, str, str, str] = ("100", "110", "90", "105"),
    volume: str = "10",
    quote_volume: str = "1050",
    taker_base: str = "4",
) -> str:
    """One 12-column CSV row; ``close`` (in the file's unit) overrides the close time."""
    scale = 1000 if us else 1
    close_time = (open_ms + step) * scale - 1 if close is None else close
    o, h, low, c = prices
    return ",".join(
        [
            str(open_ms * scale),
            o,
            h,
            low,
            c,
            volume,
            str(close_time),
            quote_volume,
            "5",
            taker_base,
            "0.1",
            "0",
        ]
    )


def with_field(line: str, index: int, value: str) -> str:
    columns = line.split(",")
    columns[index] = value
    return ",".join(columns)


def csv_text(lines: list[str]) -> str:
    return "".join(line + "\n" for line in lines)


def zipped(member: str, text: str) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    return stream.getvalue()


def hourly_zip(text: str, month: str = FEB, symbol: str = SYMBOL) -> bytes:
    return zipped(f"{symbol}-1h-{month}.csv", text)


def daily_zip(text: str, month: str = FEB, symbol: str = SYMBOL) -> bytes:
    return zipped(f"{symbol}-1d-{month}.csv", text)


def funding_zip(text: str, month: str = FEB, symbol: str = SYMBOL) -> bytes:
    return zipped(f"{symbol}-fundingRate-{month}.csv", text)


def hours(month: str, indexes: list[int], **kwargs) -> list[str]:
    start = month_start(month)
    return [kline(start + i * HOUR, **kwargs) for i in indexes]


def opens(read: KlineRead) -> list[int]:
    return [bar.open_ms for bar in read.bars]


def read_text(text: str, month: str = FEB, *, futures: bool = False) -> KlineRead:
    return read_hourly(hourly_zip(text, month), SYMBOL, month, futures=futures)


def empty_read() -> tuple[tuple[()], frozenset[int], frozenset[int]]:
    return (), frozenset(), frozenset()


# --- hourly reader: units, headers, defects --------------------------------------------------


@pytest.mark.parametrize("futures", [False, True])
@pytest.mark.parametrize("month", ["2025-01", "2025-12", "2026-03"])
def test_2025_microsecond_rows_normalise_to_milliseconds(month, futures):
    start, end = month_start(month), month_end(month)
    lines = [kline(start + i * HOUR, us=True) for i in (0, 1, 2)]
    lines.append(kline(end - HOUR, us=True))  # the month's last hour stays inside it
    text = ("\n".join([KLINE_HEADER] + lines) if futures else "\n".join(lines)) + "\n"

    read = read_text(text, month, futures=futures)

    assert read.unreadable == ""
    assert opens(read) == [start, start + HOUR, start + 2 * HOUR, end - HOUR]
    assert read.masked == frozenset() and read.repaired == frozenset()
    assert read.bars[0] == HourBar(
        start,
        Decimal("100"),
        Decimal("110"),
        Decimal("90"),
        Decimal("105"),
        quote_volume=Decimal("1050"),
        volume=Decimal("10"),
    )


def test_futures_header_is_dropped_and_spot_first_row_kept():
    lines = hours(FEB, [0, 1, 2])
    start = month_start(FEB)

    futures = read_text(KLINE_HEADER + "\n" + csv_text(lines), futures=True)
    spot = read_text(csv_text(lines), futures=False)
    futures_without_header = read_text(csv_text(lines), futures=True)

    assert opens(futures) == opens(spot) == opens(futures_without_header)
    assert opens(spot) == [start, start + HOUR, start + 2 * HOUR]
    for read in (futures, spot, futures_without_header):
        assert read.unreadable == "" and read.masked == frozenset()


def test_a_header_on_a_spot_file_is_not_dropped_so_the_archive_is_unreadable():
    text = KLINE_HEADER + "\n" + csv_text(hours(FEB, [0, 1]))

    read = read_text(text, futures=False)

    assert read.unreadable != ""
    assert (read.bars, read.masked, read.repaired) == empty_read()


def test_a_futures_header_with_crlf_line_endings_is_dropped():
    text = KLINE_HEADER + "\r\n" + "\r\n".join(hours(FEB, [0, 1])) + "\r\n"

    read = read_text(text, futures=True)

    assert read.unreadable == ""
    assert len(read.bars) == 2


def test_the_header_text_equals_the_v3_fetch_scripts(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import fetch_v3_data

    from crypto_grid_bot.v4.data import bars

    assert fetch_v3_data.KLINE_HEADER == KLINE_HEADER == bars.FUTURES_KLINE_HEADER


def test_a_duplicate_or_out_of_order_row_is_dropped_and_both_hours_masked():
    start = month_start(FEB)
    h = [start + i * HOUR for i in range(5)]

    duplicate = read_text(csv_text(hours(FEB, [0, 1, 1, 2])))
    out_of_order = read_text(csv_text(hours(FEB, [0, 2, 1, 3])))

    # The first copy is kept; the duplicate's hour is the kept row's hour.
    assert opens(duplicate) == [h[0], h[1], h[2]]
    assert duplicate.masked == frozenset({h[1]})
    # The late row is dropped and so is the kept row it fell behind: both hours are masked.
    # The row after the dropped one is judged against the last kept row, so hour 3 stays.
    assert opens(out_of_order) == [h[0], h[2], h[3]]
    assert out_of_order.masked == frozenset({h[1], h[2]})
    assert out_of_order.repaired == frozenset()


def test_a_duplicate_keeps_the_first_copys_numbers():
    first = kline(month_start(FEB), prices=("1", "2", "1", "2"))
    second = kline(month_start(FEB), prices=("5", "6", "5", "6"))

    read = read_text(csv_text([first, second]))

    assert [bar.open for bar in read.bars] == [Decimal("1")]


def test_a_duplicate_is_dropped_whatever_else_is_wrong_with_it():
    start = month_start(FEB)
    broken = kline(start, prices=("abc", "2", "1", "2"))

    read = read_text(csv_text([kline(start), broken]))

    assert opens(read) == [start]
    assert read.masked == frozenset({start})


def test_an_off_boundary_close_is_repaired_and_masked():
    start = month_start(FEB)
    h = [start + i * HOUR for i in range(4)]
    lines = [
        kline(h[0]),
        kline(h[1], close=h[1] + HOUR - 2),  # one millisecond short
        kline(h[2], close=h[2] + HOUR),  # one millisecond long
        kline(h[3], close=h[3] + 30_000),  # the last row's close is cut off
    ]

    read = read_text(csv_text(lines))

    assert read.unreadable == ""
    # A repaired row stays in the bars; the spec masks its hour, so it is also in the mask.
    assert opens(read) == h
    assert read.repaired == frozenset({h[1], h[2], h[3]})
    assert read.masked == read.repaired


def test_a_microsecond_close_off_its_999_is_repaired_and_masked():
    start = month_start("2025-01")
    lines = [
        kline(start, us=True),
        kline(start + HOUR, us=True, close=(start + 2 * HOUR) * 1000 - 2),  # ...998 us
        kline(start + 2 * HOUR, us=True),
    ]

    read = read_text(csv_text(lines), "2025-01")

    assert opens(read) == [start, start + HOUR, start + 2 * HOUR]
    assert read.repaired == read.masked == frozenset({start + HOUR})


def test_a_bad_close_followed_by_a_row_inside_its_hour_is_not_repaired():
    start = month_start(FEB)
    lines = [
        kline(start, close=start + HOUR - 2),
        kline(start + HOUR // 2),  # opens inside the first row's hour: blocks its repair
        kline(start + HOUR),
    ]

    read = read_text(csv_text(lines))

    assert opens(read) == [start + HOUR]
    assert read.repaired == frozenset()
    assert read.masked == frozenset({start})


BAD_ROWS = {
    "high below low": lambda t: kline(t, prices=("100", "80", "90", "105")),
    "price not a number": lambda t: kline(t, prices=("abc", "110", "90", "105")),
    "zero price": lambda t: kline(t, prices=("0", "110", "0", "105")),
    "negative volume": lambda t: kline(t, volume="-1"),
    "taker volume above total": lambda t: kline(t, taker_base="11"),
    "eleven columns": lambda t: ",".join(kline(t).split(",")[:11]),
    "open off the hour": lambda t: kline(t + 1000),
    "microsecond open off its boundary": lambda t: with_field(
        kline(t, us=True), 0, str(t * 1000 + 1)
    ),
}


@pytest.mark.parametrize("name", list(BAD_ROWS))
def test_a_row_with_bad_numbers_or_boundary_is_dropped_and_masked(name):
    start = month_start(FEB)
    bad = BAD_ROWS[name](start + 2 * HOUR)
    lines = hours(FEB, [0, 1]) + [bad] + hours(FEB, [3])

    read = read_text(csv_text(lines))

    assert read.unreadable == ""
    assert opens(read) == [start, start + HOUR, start + 3 * HOUR]
    assert read.masked == frozenset({start + 2 * HOUR})
    assert read.repaired == frozenset()


def test_a_row_outside_its_month_or_with_bad_numbers_is_dropped_and_masked():
    start, end = month_start(FEB), month_end(FEB)
    before = kline(start - HOUR)
    after = kline(end)
    bad_numbers = kline(start + 3 * HOUR, prices=("100", "80", "90", "105"))
    lines = [before, kline(start), kline(start + HOUR), bad_numbers, after]

    read = read_text(csv_text(lines))

    assert read.unreadable == ""
    assert opens(read) == [start, start + HOUR]
    assert read.repaired == frozenset()
    # As the reference does, the mask holds the hour of every dropped row, including the
    # two outside the month; a caller keeps only the hours inside it.
    assert read.masked == frozenset({start - HOUR, start + 3 * HOUR, end})


@pytest.mark.parametrize(
    "bad_open",
    [
        "",
        "abc",
        "-5",
        "1.5",
        "1e12",
        "12345678901234567890",
        " 12",
        # Arabic-Indic digits: str.isdigit() is true, so only the archive's ASCII gate
        # (_member_text) refuses this file, before any row is read.
        chr(0x661) + chr(0x662),
    ],
)
def test_an_unreadable_open_makes_the_whole_archive_unreadable(bad_open):
    good = hours(FEB, [0, 1, 3])
    bad = with_field(kline(month_start(FEB) + 2 * HOUR), 0, bad_open)
    for lines in (good[:2] + [bad] + good[2:], [bad] + good, good + [bad]):
        read = read_text(csv_text(lines))

        assert read.unreadable != ""
        assert (read.bars, read.masked, read.repaired) == empty_read()


def test_a_blank_line_makes_the_archive_unreadable_but_a_trailing_newline_does_not():
    lines = hours(FEB, [0, 1])

    blank = read_text(lines[0] + "\n\n" + lines[1] + "\n")
    trailing = read_text("\n".join(lines) + "\n")
    no_newline = read_text("\n".join(lines))

    assert blank.unreadable != ""
    assert trailing.unreadable == "" and len(trailing.bars) == 2
    assert no_newline.unreadable == "" and len(no_newline.bars) == 2


def test_a_clean_archive_has_no_masks():
    start = month_start(FEB)
    lines = []
    for i in range(48):
        low = 90 + i
        lines.append(
            kline(
                start + i * HOUR,
                prices=(str(low + 5), str(low + 20), str(low), str(low + 10)),
                volume=f"{i}.5",
                quote_volume=f"{i}0.25",
                taker_base="0",
            )
        )

    read = read_text(csv_text(lines))

    assert read.unreadable == ""
    assert read.masked == frozenset() and read.repaired == frozenset()
    assert isinstance(read.bars, tuple) and len(read.bars) == 48
    assert read.bars[7] == HourBar(
        start + 7 * HOUR,
        Decimal("102"),
        Decimal("117"),
        Decimal("97"),
        Decimal("107"),
        quote_volume=Decimal("70.25"),
        volume=Decimal("7.5"),
    )
    assert all(isinstance(bar, HourBar) for bar in read.bars)


def test_a_missing_hour_is_a_gap_not_a_mask():
    read = read_text(csv_text(hours(FEB, [0, 1, 4, 5])))

    assert len(read.bars) == 4
    assert read.masked == frozenset() and read.repaired == frozenset()


def test_an_empty_csv_and_a_header_only_futures_csv_are_readable_and_empty():
    for text, futures in (
        ("", False),
        ("", True),
        (KLINE_HEADER, True),
        (KLINE_HEADER + "\n", True),
    ):
        read = read_text(text, futures=futures)

        assert read.unreadable == ""
        assert (read.bars, read.masked, read.repaired) == empty_read()


def test_readers_work_far_beyond_2024_and_never_call_the_2024_guard(monkeypatch):
    calls: list[str] = []

    def spy(month: str) -> str:
        calls.append(month)
        return month

    monkeypatch.setattr("crypto_grid_bot.backtest.klines.development_month", spy)
    monkeypatch.setattr("crypto_grid_bot.backtest.window.development_month", spy)
    month = "2031-08"
    start = month_start(month)

    hourly = read_text(csv_text(hours(month, [0, 1])), month)
    daily = read_daily(daily_zip(csv_text(day_lines(month, [0])), month), SYMBOL, month)
    rows = read_funding(funding_zip(funding_text([f"{start + 3},8,0.0001"]), month), SYMBOL, month)

    assert hourly.unreadable == "" and len(hourly.bars) == 2
    assert daily.unreadable == "" and len(daily.bars) == 1
    assert rows == (FundingRow(start + 3, Decimal("0.0001"), 8),)
    assert funding_month_status(rows, month, first_ms=start, last_ms=start + 3) == "complete"
    assert funding_month_status(rows, month, first_ms=start, last_ms=start + 9 * HOUR) == (
        "missing_slot"
    )
    assert calls == []  # neither name of the 2024 guard was ever called


def test_a_kline_read_is_a_frozen_record_with_a_tuple_of_bars():
    read = read_text(csv_text(hours(FEB, [0])))

    assert isinstance(read.bars, tuple) and isinstance(read.masked, frozenset)
    with pytest.raises(FrozenInstanceError):
        read.unreadable = "x"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        read.bars[0].open_ms = 1  # type: ignore[misc]


def test_an_hour_bar_has_the_daily_fields_plus_a_keyword_only_volume():
    d = Decimal(1)
    daily = DailyBar(0, d, d, d, d, d)
    hourly = HourBar(0, d, d, d, d, d, volume=d)

    daily_fields = [field.name for field in fields(DailyBar)]
    assert daily_fields == ["open_ms", "open", "high", "low", "close", "quote_volume"]
    assert sorted(field.name for field in fields(HourBar)) == sorted([*daily_fields, "volume"])
    assert not hasattr(daily, "volume") and hourly.volume == d
    # Volume and quote volume are both Decimals: a positional seventh argument could swap them
    # without a type error, so it is refused.
    with pytest.raises(TypeError):
        HourBar(0, d, d, d, d, d, d)  # type: ignore[misc]


def test_the_symbol_and_month_are_checked_like_an_archive_path():
    for symbol, month in (("btc", FEB), (SYMBOL, "2024-2"), (SYMBOL, "2024-13"), ("", FEB)):
        with pytest.raises(ValueError, match="symbol|month"):
            read_hourly(b"", symbol, month, futures=False)
        with pytest.raises(ValueError, match="symbol|month"):
            read_daily(b"", symbol, month)
        with pytest.raises(ValueError, match="symbol|month"):
            read_funding(b"", symbol, month)


# --- daily reader ---------------------------------------------------------------------------


def day_lines(month: str, indexes: list[int], **kwargs) -> list[str]:
    start = month_start(month)
    return [kline(start + i * DAY, step=DAY, **kwargs) for i in indexes]


def test_daily_archives_use_the_same_reader():
    start, end = month_start(FEB), month_end(FEB)
    d = [start + i * DAY for i in range(8)]
    lines = [
        kline(start - DAY, step=DAY),  # before the month
        kline(d[0], step=DAY),
        kline(d[1], step=DAY),
        kline(d[1], step=DAY),  # a duplicate
        kline(d[2], step=DAY, close=d[2] + DAY - 2),  # a short close, repairable
        kline(d[3], step=DAY, prices=("100", "80", "90", "105")),  # high below low
        kline(d[4], step=DAY),
        kline(d[4] + HOUR, step=DAY),  # opens inside the previous day, off the day boundary
        kline(d[6], step=DAY),
        kline(end, step=DAY),  # after the month
    ]

    read = read_daily(daily_zip(csv_text(lines)), SYMBOL, FEB)

    assert read.unreadable == ""
    assert all(isinstance(bar, DailyBar) for bar in read.bars)
    assert opens(read) == [d[0], d[1], d[2], d[4], d[6]]
    assert read.repaired == frozenset({d[2]})
    # Masks are day opens: the duplicate's day, the repaired day, the day with bad numbers,
    # the day of the off-boundary row, and the two days outside the month.
    assert read.masked == frozenset({d[1], d[2], d[3], d[4], start - DAY, end})


def test_daily_microsecond_rows_in_2025_normalise_to_milliseconds():
    start = month_start("2025-01")
    lines = [kline(start + i * DAY, step=DAY, us=True) for i in range(3)]

    read = read_daily(daily_zip(csv_text(lines), "2025-01"), SYMBOL, "2025-01")

    assert opens(read) == [start, start + DAY, start + 2 * DAY]
    assert read.masked == frozenset() and read.unreadable == ""


def test_a_daily_reader_masks_the_day_not_the_hour():
    start = month_start(FEB)
    lines = day_lines(FEB, [0, 2]) + day_lines(FEB, [1])  # day 1 arrives after day 2

    read = read_daily(daily_zip(csv_text(lines)), SYMBOL, FEB)

    assert opens(read) == [start, start + 2 * DAY]
    assert read.masked == frozenset({start + DAY, start + 2 * DAY})


def test_an_unreadable_daily_open_makes_the_archive_unreadable():
    lines = day_lines(FEB, [0]) + [with_field(day_lines(FEB, [1])[0], 0, "x")]

    read = read_daily(daily_zip(csv_text(lines)), SYMBOL, FEB)

    assert read.unreadable != ""
    assert (read.bars, read.masked, read.repaired) == empty_read()


def test_quote_volume_is_csv_column_7():
    start = month_start(FEB)
    line = kline(start, volume="12.5", quote_volume="1312.5", taker_base="3")
    columns = line.split(",")
    assert columns[5] == "12.5" and columns[7] == "1312.5"

    hourly = read_text(csv_text([line]))
    daily = read_daily(
        daily_zip(
            csv_text([kline(start, step=DAY, volume="12.5", quote_volume="1312.5", taker_base="3")])
        ),
        SYMBOL,
        FEB,
    )

    assert hourly.bars[0].quote_volume == Decimal("1312.5")
    assert hourly.bars[0].volume == Decimal("12.5")
    assert daily.bars[0].quote_volume == Decimal("1312.5")


# --- archive container ----------------------------------------------------------------------


def test_member_name_must_match_the_archive():
    text = csv_text(hours(FEB, [0, 1]))
    good = hourly_zip(text)
    assert read_hourly(good, SYMBOL, FEB, futures=False).unreadable == ""
    assert read_hourly(good, SYMBOL, FEB, futures=True).unreadable == ""

    wrong_members = [
        f"ETHUSDT-1h-{FEB}.csv",  # another symbol
        f"{SYMBOL}-1h-2024-03.csv",  # another month
        f"{SYMBOL}-1d-{FEB}.csv",  # another interval
        f"{SYMBOL}-1h-{FEB}.txt",
        f"{SYMBOL}-1h-{FEB}.CSV",
        f"nested/{SYMBOL}-1h-{FEB}.csv",
        f"{SYMBOL}-1h-{FEB}.csv/",
    ]
    for member in wrong_members:
        read = read_hourly(zipped(member, text), SYMBOL, FEB, futures=False)
        assert read.unreadable != "", member
        assert f"{SYMBOL}-1h-{FEB}.csv" in read.unreadable
        assert (read.bars, read.masked, read.repaired) == empty_read()

    # The same archive read as another symbol, month or interval is refused too.
    assert read_hourly(good, "ETHUSDT", FEB, futures=False).unreadable != ""
    assert read_hourly(good, SYMBOL, "2024-03", futures=False).unreadable != ""
    assert read_daily(good, SYMBOL, FEB).unreadable != ""

    # Two members, even with the right one among them, are not an archive.
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(f"{SYMBOL}-1h-{FEB}.csv", text)
        archive.writestr("README.txt", "extra")
    assert read_hourly(stream.getvalue(), SYMBOL, FEB, futures=False).unreadable != ""
    twice = io.BytesIO()
    with zipfile.ZipFile(twice, "w") as archive:
        archive.writestr(f"{SYMBOL}-1h-{FEB}.csv", text)
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr(f"{SYMBOL}-1h-{FEB}.csv", text)
    assert read_hourly(twice.getvalue(), SYMBOL, FEB, futures=False).unreadable != ""

    # The daily and funding readers name their own files.
    assert read_daily(daily_zip(csv_text(day_lines(FEB, [0]))), SYMBOL, FEB).unreadable == ""
    with pytest.raises(ValueError, match=f"{SYMBOL}-fundingRate-{FEB}.csv"):
        read_funding(
            zipped(f"{SYMBOL}-fundingRate-2024-03.csv", FUNDING_HEADER + "\n"), SYMBOL, FEB
        )
    with pytest.raises(ValueError, match="exactly"):
        read_funding(good, SYMBOL, FEB)
    both = io.BytesIO()
    with zipfile.ZipFile(both, "w") as archive:
        archive.writestr(f"{SYMBOL}-fundingRate-{FEB}.csv", FUNDING_HEADER + "\n")
        archive.writestr("extra.csv", "")
    with pytest.raises(ValueError, match="exactly"):
        read_funding(both.getvalue(), SYMBOL, FEB)


def test_bytes_that_are_not_a_readable_zip_are_unreadable_not_an_error():
    good = hourly_zip(csv_text(hours(FEB, [0, 1, 2])))
    flipped = bytearray(good)
    flipped[30 + len(f"{SYMBOL}-1h-{FEB}.csv") + 2] ^= 0xFF  # inside the compressed data

    for content in (b"", b"not a zip", good[:-10], bytes(flipped)):
        read = read_hourly(content, SYMBOL, FEB, futures=False)

        assert read.unreadable != ""
        assert (read.bars, read.masked, read.repaired) == empty_read()
        assert read_daily(content, SYMBOL, FEB).unreadable != ""
        with pytest.raises(ValueError):
            read_funding(content, SYMBOL, FEB)


def test_a_non_ascii_byte_makes_a_csv_unreadable_even_in_a_column_nothing_reads():
    e_acute = chr(0xE9)
    lines = hours(FEB, [0, 1])
    lines[1] = with_field(lines[1], 11, e_acute)
    day = with_field(day_lines(FEB, [0])[0], 11, e_acute)
    start = month_start(FEB)

    read = read_text(csv_text(lines))
    daily = read_daily(daily_zip(csv_text([day])), SYMBOL, FEB)

    assert "ASCII" in read.unreadable and "ASCII" in daily.unreadable
    assert (read.bars, read.masked, read.repaired) == empty_read()
    with pytest.raises(ValueError, match="ASCII"):
        read_funding(funding_zip(funding_text([f"{start},8,0.0001", e_acute])), SYMBOL, FEB)


@pytest.mark.parametrize(
    "method", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA, zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED]
)
def test_any_zip_compression_the_standard_library_reads_is_read(method):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", method) as archive:
        archive.writestr(f"{SYMBOL}-1h-{FEB}.csv", csv_text(hours(FEB, [0, 1])))

    read = read_hourly(stream.getvalue(), SYMBOL, FEB, futures=False)

    assert read.unreadable == "" and len(read.bars) == 2


def test_a_csv_with_a_field_beyond_the_csv_limit_is_unreadable():
    huge = "9" * 200_000
    text = csv_text(
        hours(FEB, [0]) + [kline(month_start(FEB) + HOUR, prices=("1", "2", "1", huge))]
    )

    read = read_text(text)

    assert read.unreadable != ""


# --- differential test against the reference reader ----------------------------------------


def random_archive(rng: random.Random, month: str, *, us: bool) -> str:
    """Rows with a random sample of the defects the reference reader tells apart."""
    start = month_start(month)
    lines: list[str] = []
    index = 0
    for _ in range(rng.randrange(0, 40)):
        index += rng.choice((1, 1, 1, 1, 2, 3))
        open_ms = start + index * HOUR
        roll = rng.random()
        if roll < 0.05:
            open_ms = start + rng.randrange(-3, 6) * HOUR  # out of order or duplicate
        elif roll < 0.08:
            open_ms += rng.randrange(1, HOUR, 997)  # inside an hour: off the boundary
        elif roll < 0.10:
            open_ms = month_end(month) + rng.randrange(-2, 3) * HOUR
        close: int | None = None
        scale = 1000 if us else 1
        roll = rng.random()
        if roll < 0.10:
            close = (open_ms + HOUR) * scale - 1 + rng.choice((-1, 1, -30, HOUR))
        elif roll < 0.13:
            close = open_ms * scale + 5  # the close is nowhere near
        line = kline(open_ms, us=us, close=close)
        roll = rng.random()
        if roll < 0.04:
            line = with_field(
                line, rng.choice((1, 2, 3, 4)), rng.choice(("abc", "0", "-1", "9e99"))
            )
        elif roll < 0.06:
            line = ",".join(line.split(",")[: rng.randrange(5, 12)])
        elif roll < 0.07:
            line = with_field(line, 9, "99999")
        elif roll < 0.08:
            line = with_field(line, 0, rng.choice(("", "x", "1.5", "-3")))
        lines.append(line)
    return csv_text(lines)


@pytest.mark.parametrize(("month", "us"), [(FEB, False), ("2024-12", False), ("2025-03", True)])
def test_the_reader_agrees_with_the_reference_on_seeded_random_archives(month, us):
    rng = random.Random(f"{month}-{us}")
    reached = {"kept": 0, "readable": 0, "repaired": 0, "dropped": 0}
    for _ in range(250):
        text = random_archive(rng, month, us=us)

        ours = read_text(text, month)
        reference = parse_rows_repaired(text, "1h", month)

        assert ours.unreadable == reference.unreadable
        assert ours.repaired == reference.repaired
        # The spec masks repaired hours too, so they are in ours and in the reference's union.
        assert ours.masked == reference.masked_hours | reference.repaired
        assert [
            (b.open_ms, b.open, b.high, b.low, b.close, b.volume, b.quote_volume) for b in ours.bars
        ] == [
            (b.open_ms, b.open, b.high, b.low, b.close, b.volume, b.quote_volume)
            for b in reference.bars
        ]
        reached["kept"] += len(ours.bars)
        reached["readable"] += not ours.unreadable
        reached["repaired"] += bool(ours.repaired)
        reached["dropped"] += bool(ours.masked - ours.repaired)
    # The generator reaches the branches: archives that read, with repaired and dropped rows.
    assert reached["readable"] > 150 and reached["kept"] > 1500
    assert reached["repaired"] > 50 and reached["dropped"] > 50
    assert reached["readable"] < 250  # and some archives are unreadable


# --- funding reader -------------------------------------------------------------------------


def funding_text(rows: list[str], header: str = FUNDING_HEADER) -> str:
    return header + "\n" + "".join(row + "\n" for row in rows)


def test_funding_reads_calc_time_and_rate():
    start = month_start(FEB)
    text = funding_text(
        [
            f"{start + 12},8,0.00010000",
            f"{start + 8 * HOUR + 3},8,-0.00005",
            f"{start + 16 * HOUR},8,0",
        ]
    )

    rows = read_funding(funding_zip(text), SYMBOL, FEB)

    assert rows == (
        FundingRow(start + 12, Decimal("0.00010000"), 8),
        FundingRow(start + 8 * HOUR + 3, Decimal("-0.00005"), 8),
        FundingRow(start + 16 * HOUR, Decimal("0"), 8),
    )
    assert isinstance(rows, tuple)
    assert str(rows[0].rate) == "0.00010000"  # parsed from the text, never through a float
    with pytest.raises(FrozenInstanceError):
        rows[0].rate = Decimal(1)  # type: ignore[misc]


def test_funding_microsecond_times_normalise_to_milliseconds_and_rows_keep_file_order():
    start = month_start("2025-01")
    text = funding_text([f"{(start + 8 * HOUR) * 1000 + 123},8,0.0001", f"{start + 3},8,0.0002"])

    rows = read_funding(funding_zip(text, "2025-01"), SYMBOL, "2025-01")

    assert [row.time_ms for row in rows] == [start + 8 * HOUR, start + 3]
    assert [row.interval_hours for row in rows] == [8, 8]


def test_funding_file_without_interval_column_reads_as_8_hours():
    start = month_start(FEB)
    text = funding_text(
        [f"{start + 5},0.0001", f"{start + 8 * HOUR + 5},0.0002"], "calc_time,last_funding_rate"
    )

    rows = read_funding(funding_zip(text), SYMBOL, FEB)

    assert rows == (
        FundingRow(start + 5, Decimal("0.0001"), None),
        FundingRow(start + 8 * HOUR + 5, Decimal("0.0002"), None),
    )
    full_month = [FundingRow(slot + 5, Decimal("0.0001"), None) for slot in slots(FEB, 8)]
    assert judge(full_month) == "complete"
    # Read as 8 h, a 4-hourly schedule has rows off the 8-hourly slots.
    four_hourly = [FundingRow(slot + 5, Decimal("0.0001"), None) for slot in slots(FEB, 4)]
    assert judge(four_hourly) == "off_slot"


def test_a_header_only_funding_file_has_no_rows():
    assert read_funding(funding_zip(FUNDING_HEADER + "\n"), SYMBOL, FEB) == ()
    assert read_funding(funding_zip(FUNDING_HEADER), SYMBOL, FEB) == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "header"),
        ("calc_time,rate,interval\n", "header"),
        ("1,8,0.0001\n", "header"),
        (FUNDING_HEADER + "\n1,8\n", "line 2"),
        (FUNDING_HEADER + "\n1,8,0.1,0\n", "line 2"),
        (FUNDING_HEADER + "\n\n", "line 2"),
        (FUNDING_HEADER + "\nabc,8,0.0001\n", "calc_time"),
        (FUNDING_HEADER + "\n-1,8,0.0001\n", "calc_time"),
        (FUNDING_HEADER + "\n" + "9" * 18 + ",8,0.0001\n", "calc_time"),
        (FUNDING_HEADER + "\n1,x,0.0001\n", "interval"),
        (FUNDING_HEADER + "\n1,,0.0001\n", "interval"),
        (FUNDING_HEADER + "\n1,8,abc\n", "rate"),
        (FUNDING_HEADER + "\n1,8,NaN\n", "rate"),
        (FUNDING_HEADER + "\n1,8,Infinity\n", "rate"),
        (FUNDING_HEADER + "\n1,8,1E-9999\n", "rate"),
        (FUNDING_HEADER + "\n1,8," + "1" * 70 + "\n", "rate"),
    ],
)
def test_a_malformed_funding_file_is_an_error(text, message):
    with pytest.raises(ValueError, match=message):
        read_funding(funding_zip(text), SYMBOL, FEB)


# --- funding month status -------------------------------------------------------------------


def slots(month: str, interval: int) -> list[int]:
    step = interval * HOUR
    return list(range(month_start(month), month_end(month), step))


def funding(month: str, interval: int = 8) -> list[FundingRow]:
    """One row per slot, each 0-47 ms after its slot."""
    return [
        FundingRow(slot + (index * 7) % 48, Decimal("0.0001"), interval)
        for index, slot in enumerate(slots(month, interval))
    ]


def judge(rows: list[FundingRow], month: str = FEB) -> str:
    """The status over the whole month: listed before it and after it."""
    return funding_month_status(rows, month, first_ms=0, last_ms=10**15)


def test_funding_month_complete_on_an_exact_8h_schedule_with_ms_offsets():
    rows = funding(FEB)
    offsets = [row.time_ms - slot for row, slot in zip(rows, slots(FEB, 8), strict=True)]

    assert len(rows) == 87  # 29 days x 3
    assert min(offsets) == 0 and max(offsets) == 47
    assert judge(rows) == "complete"
    # A perpetual trading all month: its first bar opens at the month start, its last closes at
    # the month end.
    assert (
        funding_month_status(rows, FEB, first_ms=month_start(FEB), last_ms=month_end(FEB) - 1)
        == "complete"
    )


@pytest.mark.parametrize("interval", [1, 2, 3, 4, 6, 8, 12, 24])
def test_funding_month_is_complete_at_any_interval_that_divides_24(interval):
    assert judge(funding(FEB, interval)) == "complete"
    assert judge(funding("2023-12", interval), "2023-12") == "complete"


def test_funding_rows_may_arrive_in_any_order():
    rows = funding(FEB)
    random.Random(5).shuffle(rows)

    assert judge(rows) == "complete"


def test_a_row_exactly_60_000_ms_after_its_slot_is_on_the_slot():
    rows = funding(FEB)
    rows[10] = replace(rows[10], time_ms=slots(FEB, 8)[10] + 60_000)

    assert judge(rows) == "complete"


def mixed(rows: list[FundingRow]) -> list[FundingRow]:
    rows[5] = replace(rows[5], interval_hours=4)
    return rows


def interval_five(rows: list[FundingRow]) -> list[FundingRow]:
    return [replace(row, interval_hours=5) for row in rows]


def late(rows: list[FundingRow]) -> list[FundingRow]:
    rows[10] = replace(rows[10], time_ms=slots(FEB, 8)[10] + 60_001)
    return rows


def early(rows: list[FundingRow]) -> list[FundingRow]:
    rows[10] = replace(rows[10], time_ms=slots(FEB, 8)[10] - 1)
    return rows


def duplicated(rows: list[FundingRow]) -> list[FundingRow]:
    rows.insert(11, replace(rows[10], time_ms=rows[10].time_ms + 1))
    return rows


def dropped(rows: list[FundingRow]) -> list[FundingRow]:
    del rows[10]
    return rows


def dropped_first(rows: list[FundingRow]) -> list[FundingRow]:
    del rows[0]
    return rows


def dropped_last(rows: list[FundingRow]) -> list[FundingRow]:
    del rows[-1]
    return rows


def next_month_row(rows: list[FundingRow]) -> list[FundingRow]:
    rows.append(FundingRow(month_end(FEB) + 1, Decimal("0.0001"), 8))
    return rows


def previous_month_row(rows: list[FundingRow]) -> list[FundingRow]:
    rows.insert(0, FundingRow(month_start(FEB) - 8 * HOUR + 1, Decimal("0.0001"), 8))
    return rows


@pytest.mark.parametrize(
    ("damage", "reason"),
    [
        (mixed, "interval_mixed"),
        (interval_five, "interval_not_divisor_of_24"),
        (late, "off_slot"),
        (early, "off_slot"),
        (next_month_row, "off_slot"),
        (previous_month_row, "off_slot"),
        (duplicated, "duplicate_slot"),
        (dropped, "missing_slot"),
        (dropped_first, "missing_slot"),
        (dropped_last, "missing_slot"),
    ],
)
def test_funding_month_failures_name_their_reason(damage, reason):
    assert judge(damage(funding(FEB))) == reason


def test_an_interval_of_zero_or_a_negative_one_does_not_divide_24():
    for interval in (0, -8, 25, 48):
        rows = [replace(row, interval_hours=interval) for row in funding(FEB)]

        assert judge(rows) == "interval_not_divisor_of_24"


def test_funding_month_reasons_are_reported_in_the_listed_order():
    def damaged(*, mix=False, five=False, off=False, dup=False, drop=False) -> list[FundingRow]:
        """A month with each requested defect on a row of its own."""
        rows = funding(FEB)
        all_slots = slots(FEB, 8)
        if off:
            rows[30] = replace(rows[30], time_ms=all_slots[30] + 60_001)
        if dup:
            rows.insert(21, replace(rows[20], time_ms=rows[20].time_ms + 1))
        if drop:
            del rows[10]
        if mix:
            rows[5] = replace(rows[5], interval_hours=4)
        if five:
            rows = [replace(row, interval_hours=5) for row in rows]
        return rows

    assert judge(damaged(off=True, dup=True, drop=True)) == "off_slot"
    assert judge(damaged(dup=True, drop=True)) == "duplicate_slot"
    assert judge(damaged(drop=True)) == "missing_slot"
    assert judge(damaged(mix=True, off=True, dup=True, drop=True)) == "interval_mixed"
    assert judge(damaged(five=True, off=True, dup=True, drop=True)) == "interval_not_divisor_of_24"
    # Each defect alone gives its own reason, so the combinations above are decided by order.
    assert judge(damaged(off=True)) == "off_slot"
    assert judge(damaged(dup=True)) == "duplicate_slot"
    assert judge(damaged()) == "complete"


def test_a_row_without_an_interval_counts_as_8_hours_beside_rows_that_say_8():
    rows = funding(FEB)
    rows[3] = replace(rows[3], interval_hours=None)

    assert judge(rows) == "complete"
    rows[4] = replace(rows[4], interval_hours=4)
    assert judge(rows) == "interval_mixed"


def test_a_month_with_no_rows_inside_the_listing_span_is_missing_every_slot():
    assert judge([]) == "missing_slot"
    start = month_start(FEB)
    assert funding_month_status([], FEB, first_ms=start, last_ms=start + 1) == "missing_slot"


def at(day: int, hour: int) -> int:
    """The ``hour`` o'clock UTC of ``day`` of February 2024, in ms."""
    return month_start(FEB) + (day - 1) * DAY + hour * HOUR


def settlement(day: int, hour: int) -> int:
    """The index in ``funding(FEB)`` of the 8-hour settlement at ``hour`` on ``day``."""
    return (day - 1) * 3 + hour // 8


def judge_listed_from(rows: list[FundingRow], first_open: int) -> str:
    """Listed from the hour bar that opens at ``first_open``, and trading to the month's end."""
    return funding_month_status(rows, FEB, first_ms=first_open, last_ms=10**15)


def judge_listed_until(rows: list[FundingRow], last_open: int) -> str:
    """Trading from before the month to the hour bar that opens at ``last_open``, whose close
    (open + 3,600,000 - 1) is the span's end."""
    return funding_month_status(rows, FEB, first_ms=0, last_ms=last_open + HOUR - 1)


def test_listing_and_delisting_months_are_judged_only_while_listed():
    rows = funding(FEB)
    for day, hour in ((10, 8), (16, 0), (15, 16)):
        assert 0 <= rows[settlement(day, hour)].time_ms - at(day, hour) < 48

    # Listed at 17:00 on the 15th: its first hour bar opens then, so the first expected slot is
    # 00:00 on the 16th, the first at or after it. The 16:00 slot of the 15th is not expected.
    from_16th = rows[settlement(16, 0) :]
    assert len(from_16th) == 14 * 3
    assert judge_listed_from(from_16th, at(15, 17)) == "complete"
    assert judge_listed_from(rows[settlement(15, 16) :], at(15, 17)) == "off_slot"
    assert judge_listed_from(from_16th[1:], at(15, 17)) == "missing_slot"
    assert judge_listed_from(from_16th, at(15, 0)) == "missing_slot"  # listed earlier: more due

    # Listed exactly on a slot, 00:00 on the 15th: that slot is expected.
    from_15th = rows[settlement(15, 0) :]
    assert judge_listed_from(from_15th, at(15, 0)) == "complete"
    assert judge_listed_from(from_15th[1:], at(15, 0)) == "missing_slot"
    # One millisecond later the slot is no longer expected, and a row on it is off slot.
    assert judge_listed_from(from_15th[1:], at(15, 0) + 1) == "complete"
    assert judge_listed_from(from_15th, at(15, 0) + 1) == "off_slot"

    # Delisted after a last bar that opens at 15:00 on the 10th and closes at 15:59:59.999: the
    # last expected slot is 08:00, and a 16:00 row is off slot.
    until_0800 = rows[: settlement(10, 8) + 1]
    assert judge_listed_until(until_0800, at(10, 15)) == "complete"
    assert judge_listed_until(rows[: settlement(10, 16) + 1], at(10, 15)) == "off_slot"
    assert judge_listed_until(until_0800[:-1], at(10, 15)) == "missing_slot"
    # A last bar opening at 16:00 expects the 16:00 slot; one opening at 07:00 stops at 00:00.
    assert judge_listed_until(rows[: settlement(10, 16) + 1], at(10, 16)) == "complete"
    assert judge_listed_until(rows[: settlement(10, 0) + 1], at(10, 7)) == "complete"
    assert judge_listed_until(until_0800, at(10, 7)) == "off_slot"
    # "At or before": a span that ends exactly on a slot expects it; one millisecond sooner not.
    assert funding_month_status(until_0800, FEB, first_ms=0, last_ms=at(10, 8)) == "complete"
    assert funding_month_status(until_0800, FEB, first_ms=0, last_ms=at(10, 8) - 1) == "off_slot"
    # The close of the last bar is the end: one opening at 23:00 still expects 16:00 only.
    assert judge_listed_until(rows[: settlement(10, 16) + 1], at(10, 23)) == "complete"

    # Listed and delisted in the one month.
    both = rows[settlement(16, 0) : settlement(20, 8) + 1]
    assert (
        funding_month_status(both, FEB, first_ms=at(15, 17), last_ms=at(20, 15) + HOUR - 1)
        == "complete"
    )

    # The same rows do not make a complete month for a perpetual that traded all month.
    assert judge(from_16th) == "missing_slot"
    assert judge(until_0800) == "missing_slot"

    # One slot dropped inside the span is still missing: first, middle or last.
    for index in (0, 5, len(from_16th) - 1):
        damaged = from_16th[:index] + from_16th[index + 1 :]
        assert judge_listed_from(damaged, at(15, 17)) == "missing_slot", index
    for index in (0, 5, len(until_0800) - 1):
        damaged = until_0800[:index] + until_0800[index + 1 :]
        assert judge_listed_until(damaged, at(10, 15)) == "missing_slot", index


def test_a_span_can_touch_a_month_without_holding_a_slot_in_it():
    rows = funding(FEB)
    # Listed at 17:00 and delisted after the bar of 22:00 on the 10th: no 8-hour slot between.
    span = {"first_ms": at(10, 17), "last_ms": at(10, 22) + HOUR - 1}

    assert funding_month_status([], FEB, **span) == "complete"
    assert funding_month_status([rows[settlement(10, 16)]], FEB, **span) == "off_slot"
    assert funding_month_status([rows[settlement(11, 0)]], FEB, **span) == "off_slot"
    # Listed at 17:00 on the month's last day: the first slot at or after it is next month's.
    last_day = {"first_ms": at(29, 17), "last_ms": 10**15}
    assert funding_month_status([], FEB, **last_day) == "complete"
    assert funding_month_status([rows[-1]], FEB, **last_day) == "off_slot"


def test_rows_outside_the_listing_span_are_not_on_an_expected_slot():
    rows = funding(FEB)
    first = slots(FEB, 8)[3]
    last = slots(FEB, 8)[20] + HOUR - 1  # the close of a bar that opened on the slot

    assert funding_month_status(rows[3:21], FEB, first_ms=first, last_ms=last) == "complete"
    assert funding_month_status(rows[2:21], FEB, first_ms=first, last_ms=last) == "off_slot"
    assert funding_month_status(rows[3:22], FEB, first_ms=first, last_ms=last) == "off_slot"


def test_a_month_the_listing_span_does_not_touch_is_an_error():
    start, end = month_start(FEB), month_end(FEB)

    with pytest.raises(ValueError, match="span"):
        funding_month_status([], FEB, first_ms=end, last_ms=end + HOUR)
    with pytest.raises(ValueError, match="span"):
        funding_month_status([], FEB, first_ms=start - HOUR, last_ms=start - 1)
    with pytest.raises(ValueError, match="first_ms"):
        funding_month_status([], FEB, first_ms=start + 5, last_ms=start + 4)


@pytest.mark.parametrize("month", ["2024-2", "2024-13", "24-02", "", "2024-02-01"])
def test_funding_month_status_refuses_a_bad_month(month):
    with pytest.raises(ValueError, match="month"):
        funding_month_status([], month, first_ms=0, last_ms=1)


def test_month_lengths_decide_the_slot_count():
    # 2023-02 has 28 days (84 slots at 8 h), 2024-02 has 29 (87), 2024-12 has 31 (93).
    for month, count in (("2023-02", 84), (FEB, 87), ("2024-12", 93), ("2024-04", 90)):
        rows = funding(month)
        assert len(rows) == count
        assert judge(rows, month) == "complete"
        assert judge(rows[:-1], month) == "missing_slot"
