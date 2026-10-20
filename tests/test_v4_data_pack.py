"""V4 data step: the canonical gzip JSON packs, pinned by the SHA-256 of their JSON text.

Everything here is pure file I/O under pytest's ``tmp_path`` (the network is blocked for every
test in this file, the autouse fixture below, as in ``test_v4_data_filters.py``). Bars, rules and
universes are small objects built in memory; the config is the committed ``config/v4_data.json``.
"""

from __future__ import annotations

import gzip
import hashlib
import socket
from collections.abc import Mapping, Sequence
from dataclasses import replace
from decimal import Context, localcontext
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data import pack
from crypto_grid_bot.v4.data.archives import ManifestEntry, archive_path
from crypto_grid_bot.v4.data.bars import DailyBar, FundingRow, HourBar, funding_month_status
from crypto_grid_bot.v4.data.config import load_data_config
from crypto_grid_bot.v4.data.pack import (
    daily_pack_document,
    hourly_pack_document,
    read_canonical,
    write_canonical,
)
from crypto_grid_bot.v4.data.universe import MonthlyUniverse

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "v4_data.json"
END_MONTH = "2026-09"  # pinned here: no test depends on the committed config's end_month
CONFIG = replace(load_data_config(CONFIG_PATH), end_month=END_MONTH)
CONFIG_SHA = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
HOUR = 3_600_000
DAY = 24 * HOUR
T0 = 1_735_689_600_000  # 2025-01-01 00:00 UTC, in milliseconds
FEB = 1_738_368_000_000  # 2025-02-01 00:00 UTC


def month_after(month: str) -> str:
    year, number = (int(part) for part in month.split("-"))
    year, number = (year + 1, 1) if number == 12 else (year, number + 1)
    return f"{year:04d}-{number:02d}"


AFTER_END = month_after(END_MONTH)


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


# ---- builders of small inputs ----


def entry(kind: str, symbol: str, month: str) -> ManifestEntry:
    digest = hashlib.sha256(f"{kind}|{symbol}|{month}".encode()).hexdigest()
    return ManifestEntry(kind, symbol, month, archive_path(kind, symbol, month), digest, 1234)


def day_bar(k: int, close: str = "94050.50") -> DailyBar:
    return DailyBar(
        T0 + k * DAY, D("94000.00"), D("94100.00"), D("93900.00"), D(close), D("1175000.12345678")
    )


def hour_bar(k: int, close: str = "94050.50") -> HourBar:
    return HourBar(
        T0 + k * HOUR,
        D("94000.00"),
        D("94100.00"),
        D("93900.00"),
        D(close),
        D("1175000.12345678"),
        volume=D("12.50000000"),
    )


def universe(month: str = "2025-01") -> MonthlyUniverse:
    return MonthlyUniverse(
        month=month,
        selected=("BTCUSDT", "ETHUSDT"),
        ranked=(("BTCUSDT", D("9.5E+9"), 30), ("ETHUSDT", D("4123456789.12345678"), 29)),
        excluded=(("USDCUSDT", "stablecoin"), ("WBTCUSDT", "wrapped")),
        entered=("ETHUSDT",),
        left=("XRPUSDT",),
    )


def rules(tick: str = "0.01000000") -> VenueRules:
    return VenueRules(
        step=D("0.00001000"),
        min_qty=D("0.00001000"),
        max_qty=D("9000.00000000"),
        min_notional=D("5.00000000"),
        tick=D(tick),
    )


def daily_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "config": CONFIG,
        "manifest": [
            entry("spot_1d", "BTCUSDT", "2025-01"),
            entry("spot_1d", "ETHUSDT", "2025-01"),
        ],
        "daily": {
            "BTCUSDT": [day_bar(0), day_bar(1, "94100.25")],
            "ETHUSDT": [day_bar(0, "3300.10")],
        },
        "exclusions": {"USDCUSDT": "stablecoin", "WBTCUSDT": "wrapped"},
        "universes": [universe()],
        "masks": {"BTCUSDT": ([], {}), "ETHUSDT": ([T0 + DAY], {})},
        "config_sha256": CONFIG_SHA,
    }
    return args | overrides


def hourly_args(**overrides: Any) -> dict[str, Any]:
    args: dict[str, Any] = {
        "config": CONFIG,
        "manifest": [
            entry("spot_1h", "BTCUSDT", "2025-01"),
            entry("futures_1h", "BTCUSDT", "2025-01"),
            entry("funding", "BTCUSDT", "2025-01"),
        ],
        "spot": {"BTCUSDT": [hour_bar(0), hour_bar(1, "94075.00")], "ETHUSDT": [hour_bar(0)]},
        "futures": {"BTCUSDT": [hour_bar(0, "94060.00")]},
        "masks": {
            ("BTCUSDT", "spot"): ([T0 + 5 * HOUR, T0 + 7 * HOUR], {}),
            ("ETHUSDT", "spot"): ([], {}),
            ("BTCUSDT", "futures"): ([], {}),
        },
        "funding": {
            "BTCUSDT": [
                FundingRow(T0, D("0.00010000"), 8),
                FundingRow(T0 + 8 * HOUR, D("-0.00005000"), None),
            ]
        },
        "funding_months": {("BTCUSDT", "2025-01"): "complete"},
        "rules": {
            ("BTCUSDT", "spot"): (rules(), "present_day"),
            ("ETHUSDT", "spot"): (rules("1E-7"), "inferred"),
            ("BTCUSDT", "futures"): (rules("0.10"), "present_day"),
        },
        "perpetuals": {"BTCUSDT": {"symbol": "BTCUSDT", "multiplier": 1}},
        "config_sha256": CONFIG_SHA,
    }
    return args | overrides


def daily_doc(**overrides: Any) -> dict[str, Any]:
    return daily_pack_document(**daily_args(**overrides))


def hourly_doc(**overrides: Any) -> dict[str, Any]:
    return hourly_pack_document(**hourly_args(**overrides))


def raw_pack(path: Path, text: str | bytes) -> str:
    """Write ``text`` gzipped as a pack file, and return the pin (its SHA-256)."""
    data = text if isinstance(text, bytes) else text.encode("ascii")
    path.write_bytes(gzip.compress(data))
    return hashlib.sha256(data).hexdigest()


def reversed_dict(mapping: Mapping[Any, Any]) -> dict[Any, Any]:
    return dict(reversed(list(mapping.items())))


# ---- write_canonical ----


def test_pin_is_sha256_of_canonical_json_not_gzip_bytes(tmp_path):
    document = {"b": [1, "x"], "a": {"z": None, "y": True}}
    path = tmp_path / "pack.json.gz"
    pin = write_canonical(document, path)
    canonical = b'{"a":{"y":true,"z":null},"b":[1,"x"]}'
    on_disk = path.read_bytes()
    assert pin == hashlib.sha256(canonical).hexdigest()
    assert gzip.decompress(on_disk) == canonical
    assert pin != hashlib.sha256(on_disk).hexdigest()
    # mtime 0 and no file name in the gzip header, so the file does not depend on the clock
    assert on_disk[:3] == b"\x1f\x8b\x08" and on_disk[3] == 0 and on_disk[4:8] == bytes(4)


def test_the_same_document_written_twice_has_the_same_pin_and_gzip_bytes(tmp_path):
    document = daily_doc()
    first, second = tmp_path / "one.json.gz", tmp_path / "two.json.gz"
    assert write_canonical(document, first) == write_canonical(document, second)
    assert first.read_bytes() == second.read_bytes()


def test_dict_insertion_order_does_not_change_the_pin(tmp_path):
    daily = daily_args()
    shuffled = daily_args(
        manifest=list(reversed(daily["manifest"])),
        daily=reversed_dict(daily["daily"]),
        exclusions=reversed_dict(daily["exclusions"]),
        masks=reversed_dict(daily["masks"]),
    )
    hourly = hourly_args()
    reordered = hourly_args(
        manifest=list(reversed(hourly["manifest"])),
        spot=reversed_dict(hourly["spot"]),
        masks=reversed_dict(hourly["masks"]),
        rules=reversed_dict(hourly["rules"]),
    )
    assert write_canonical(daily_pack_document(**daily), tmp_path / "d1") == write_canonical(
        daily_pack_document(**shuffled), tmp_path / "d2"
    )
    assert write_canonical(hourly_pack_document(**hourly), tmp_path / "h1") == write_canonical(
        hourly_pack_document(**reordered), tmp_path / "h2"
    )
    other = write_canonical(daily_doc(exclusions={"USDCUSDT": "stablecoin"}), tmp_path / "d3")
    assert other != write_canonical(daily_doc(), tmp_path / "d4")  # a real change moves the pin


def test_existing_file_is_refused(tmp_path):
    path = tmp_path / "pack.json.gz"
    path.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        write_canonical({"a": 1}, path)
    assert path.read_bytes() == b"precious"
    assert list(tmp_path.iterdir()) == [path]  # and no temporary file was left beside it


def test_a_missing_parent_folder_is_not_created(tmp_path):
    path = tmp_path / "nowhere" / "pack.json.gz"
    with pytest.raises(FileNotFoundError):
        write_canonical({"a": 1}, path)
    assert not path.parent.exists()


def circular() -> list[Any]:
    loop: list[Any] = []
    loop.append(loop)
    return loop


@pytest.mark.parametrize(
    ("document", "why"),
    [
        ({"a": 1.5}, "float"),
        ({"a": 1.0}, "float"),
        ({"a": float("nan")}, "float"),
        ({"a": float("inf")}, "float"),
        ({"a": [[1, 2.5]]}, r"\[.a.\]\[0\]\[1\]"),
        ({1: "x"}, "key 1 is not a string"),
        ({"a": {2: "x"}}, "key 2 is not a string"),
        ({"a": {None: 1}}, "key None is not a string"),
        ({"a": (1, 2)}, "tuple"),
        ({"a": {1, 2}}, "set"),
        ({"a": D("1.5")}, "Decimal"),
        ({"a": b"x"}, "bytes"),
        ({"a": circular()}, "circular"),
        ([1, 2], "mapping"),
    ],
)
def test_writer_refuses_what_the_reader_would_refuse_or_change(tmp_path, document, why):
    path = tmp_path / "pack.json.gz"
    with pytest.raises(ValueError, match=why):
        write_canonical(document, path)
    assert list(tmp_path.iterdir()) == []  # refused before any file, temporary or final


def test_writer_accepts_everything_the_reader_returns_unchanged(tmp_path):
    document = {"s": "café", "i": -5, "b": [True, False], "n": None, "d": {"x": [[], {}]}}
    path = tmp_path / "pack.json.gz"
    assert read_canonical(path, write_canonical(document, path)) == document


def test_a_failed_write_leaves_no_file_at_the_final_path(tmp_path, monkeypatch):
    path = tmp_path / "pack.json.gz"

    def broken_write(self, data):
        raise OSError("disk full")

    monkeypatch.setattr(gzip.GzipFile, "write", broken_write)
    with pytest.raises(OSError, match="disk full"):
        write_canonical({"a": 1}, path)
    assert list(tmp_path.iterdir()) == []


def test_a_write_that_fails_after_the_temporary_file_is_written_leaves_nothing(
    tmp_path, monkeypatch
):
    path = tmp_path / "pack.json.gz"
    seen: list[list[str]] = []

    def broken_sync(fd):
        seen.append(sorted(f.name for f in tmp_path.iterdir()))  # the temporary file exists now
        raise OSError("sync failed")

    monkeypatch.setattr(pack.os, "fsync", broken_sync)
    with pytest.raises(OSError, match="sync failed"):
        write_canonical({"a": 1}, path)
    assert len(seen) == 1 and len(seen[0]) == 1 and seen[0][0].endswith(".tmp")
    assert list(tmp_path.iterdir()) == []  # the temporary file is gone, the final never was


def test_the_pack_appears_at_the_final_path_complete(tmp_path, monkeypatch):
    path = tmp_path / "pack.json.gz"
    at_link: list[bool] = []
    real_link = pack.os.link

    def watching_link(source, destination):
        at_link.append(Path(destination).exists())  # nothing is at the final path yet
        real_link(source, destination)

    monkeypatch.setattr(pack.os, "link", watching_link)
    pin = write_canonical({"a": 1}, path)
    assert at_link == [False]
    assert read_canonical(path, pin) == {"a": 1}
    assert list(tmp_path.iterdir()) == [path]


def test_without_hard_links_the_pack_is_renamed_into_place(tmp_path, monkeypatch):
    def no_links(source, destination):
        raise OSError("hard links are not supported")

    monkeypatch.setattr(pack.os, "link", no_links)
    path = tmp_path / "pack.json.gz"
    pin = write_canonical({"a": 1}, path)
    assert read_canonical(path, pin) == {"a": 1}
    assert list(tmp_path.iterdir()) == [path]
    # an existing file is still refused, and left as it was
    path.write_bytes(b"precious")
    with pytest.raises(FileExistsError):
        write_canonical({"a": 2}, path)
    assert path.read_bytes() == b"precious"
    assert list(tmp_path.iterdir()) == [path]


def test_a_failing_link_and_rename_leave_nothing(tmp_path, monkeypatch):
    def boom(source, destination):
        raise OSError("no")

    monkeypatch.setattr(pack.os, "link", boom)
    monkeypatch.setattr(pack.os, "replace", boom)
    with pytest.raises(OSError, match="no"):
        write_canonical({"a": 1}, tmp_path / "pack.json.gz")
    assert list(tmp_path.iterdir()) == []


# ---- read_canonical ----


def test_reads_back_what_was_written(tmp_path):
    path = tmp_path / "pack.json.gz"
    pin = write_canonical({"a": [1, 2], "b": {"c": "d"}}, path)
    assert read_canonical(path, pin) == {"a": [1, 2], "b": {"c": "d"}}


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ('{"a":1,"a":2}', "duplicate"),
        ('{"x":{"b":1,"b":1}}', "duplicate"),
        ('{"x":[{"b":1,"b":2}]}', "duplicate"),
        ('{"a":1.5}', "not an integer"),
        ('{"a":[0.0]}', "not an integer"),
        ('{"a":1e3}', "not an integer"),
        ('{"a":NaN}', "not an integer"),
        ('{"a":Infinity}', "not an integer"),
        ('{"a":-Infinity}', "not an integer"),
        ('{"a":', "JSON"),
        ("[1]", "object"),
        ("null", "object"),
    ],
)
def test_reader_refuses_a_wrong_pin_duplicate_keys_floats_and_nan(tmp_path, text, why):
    path = tmp_path / "pack.json.gz"
    pin = raw_pack(path, text)  # the pin is right, so only the content can be refused
    with pytest.raises(ValueError, match=why):
        read_canonical(path, pin)
    # and the same file under a pin that is not its own is refused before it is parsed
    with pytest.raises(ValueError, match="differs from the pinned"):
        read_canonical(path, "0" * 64)


def test_reader_refuses_a_wrong_pin_and_a_malformed_pin(tmp_path):
    path = tmp_path / "pack.json.gz"
    pin = write_canonical({"a": 1}, path)
    with pytest.raises(ValueError, match="differs from the pinned"):
        read_canonical(path, "f" * 64)
    # the pin of the gzip bytes is not the pin of the JSON
    with pytest.raises(ValueError, match="differs from the pinned"):
        read_canonical(path, hashlib.sha256(path.read_bytes()).hexdigest())
    for bad in (pin.upper(), pin[:-1], "", 7):
        with pytest.raises(ValueError, match="64 lowercase hex"):
            read_canonical(path, bad)


def test_reader_accepts_other_gzip_bytes_of_the_same_json(tmp_path):
    document = {"a": [1, 2, 3]}
    pin = write_canonical(document, tmp_path / "one.json.gz")
    other = tmp_path / "two.json.gz"
    other.write_bytes(gzip.compress(b'{"a":[1,2,3]}', compresslevel=1, mtime=12345))
    assert other.read_bytes() != (tmp_path / "one.json.gz").read_bytes()
    assert read_canonical(other, pin) == document


def test_reader_refuses_non_gzip_and_truncated_gzip(tmp_path):
    path = tmp_path / "pack.json.gz"
    path.write_bytes(b'{"a":1}')  # the JSON itself, not gzipped
    with pytest.raises(ValueError, match="gzip"):
        read_canonical(path, hashlib.sha256(b'{"a":1}').hexdigest())
    good = gzip.compress(b'{"a":"' + b"x" * 500 + b'"}')
    path.write_bytes(good[: len(good) // 2])
    with pytest.raises(ValueError, match="gzip"):
        read_canonical(path, "a" * 64)


def test_reader_refuses_content_over_the_size_cap(tmp_path, monkeypatch):
    path = tmp_path / "pack.json.gz"
    pin = raw_pack(path, '{"a":1234}')  # 10 bytes
    monkeypatch.setattr(pack, "MAX_CONTENT_BYTES", 10)
    assert read_canonical(path, pin) == {"a": 1234}  # exactly at the cap
    monkeypatch.setattr(pack, "MAX_CONTENT_BYTES", 9)
    with pytest.raises(ValueError, match="more than 9 bytes"):
        read_canonical(path, pin)


def test_reader_hashes_and_reads_a_pack_in_many_small_chunks(tmp_path, monkeypatch):
    # The pin is hashed chunk by chunk as the gzip is decompressed; the result is the same
    # document, and a wrong pin is still refused before anything is parsed.
    monkeypatch.setattr(pack, "_CHUNK", 7)
    document = daily_doc()
    path = tmp_path / "daily.json.gz"
    pin = write_canonical(document, path)
    assert read_canonical(path, pin) == document
    with pytest.raises(ValueError, match="differs from the pinned"):
        read_canonical(path, "0" * 64)


def test_reader_refuses_a_missing_file_as_an_os_error(tmp_path):
    with pytest.raises(OSError):
        read_canonical(tmp_path / "absent.json.gz", "0" * 64)


def test_the_size_cap_is_two_gibibytes():
    assert pack.MAX_CONTENT_BYTES == 2 * 1024**3


def test_reader_refuses_non_ascii_json(tmp_path):
    path = tmp_path / "pack.json.gz"
    pin = raw_pack(path, '{"a":"café"}'.encode())
    with pytest.raises(ValueError, match="ASCII"):
        read_canonical(path, pin)


# ---- the documents ----


def test_round_trip_keeps_decimals_as_strings(tmp_path):
    zoo = [D("0.09865000"), D("1E-7"), D("1E+2"), D("100"), D("0.00000001"), D("-0.00005000")]
    bars = [
        DailyBar(T0 + i * DAY, zoo[i], zoo[(i + 1) % 6], zoo[(i + 2) % 6], zoo[(i + 3) % 6], zoo[i])
        for i in range(6)
    ]
    document = daily_doc(
        daily={"BTCUSDT": bars, "ETHUSDT": []}, masks={"BTCUSDT": ([], {}), "ETHUSDT": ([], {})}
    )
    path = tmp_path / "daily.json.gz"
    back = read_canonical(path, write_canonical(document, path))
    assert back == document  # exactly what was built: lists, strings and ints
    for stored, bar in zip(back["daily"]["BTCUSDT"], bars, strict=True):
        assert type(stored[0]) is int and stored[0] == bar.open_ms
        values = [bar.open, bar.high, bar.low, bar.close, bar.quote_volume]
        assert all(type(text) is str for text in stored[1:])
        # the CSV's own text comes back, and it rebuilds the same Decimal, exponent included
        assert [D(text).as_tuple() for text in stored[1:]] == [v.as_tuple() for v in values]
    assert back["daily"]["BTCUSDT"][0][1:] == ["0.09865000", "1E-7", "1E+2", "100", "0.09865000"]


def test_round_trip_of_the_hourly_pack(tmp_path):
    document = hourly_doc()
    path = tmp_path / "hourly.json.gz"
    back = read_canonical(path, write_canonical(document, path))
    assert back == document
    rule = back["rules"]["ETHUSDT|spot"]
    assert rule["tick"] == "1E-7" and D(rule["tick"]) == D("1E-7")
    assert back["funding"]["BTCUSDT"][1] == [T0 + 8 * HOUR, "-0.00005000", None]


def test_a_2025_open_is_a_plain_int(tmp_path):
    open_ms = 1_735_689_600_000_000 // 1000  # a 2025 microsecond open, normalised to ms
    bar = DailyBar(open_ms, D("1"), D("2"), D("1"), D("2"), D("3"))
    document = daily_doc(
        daily={"BTCUSDT": [bar], "ETHUSDT": []}, masks={"BTCUSDT": ([], {}), "ETHUSDT": ([], {})}
    )
    path = tmp_path / "daily.json.gz"
    stored = read_canonical(path, write_canonical(document, path))["daily"]["BTCUSDT"][0]
    assert type(stored[0]) is int and stored[0] == 1_735_689_600_000


def test_decimal_text_does_not_depend_on_the_callers_context():
    with localcontext(Context(capitals=0, prec=3)):
        document = hourly_doc()
    assert document["rules"]["ETHUSDT|spot"]["tick"] == "1E-7"
    assert document["spot"]["BTCUSDT"][0][6] == "1175000.12345678"


def test_daily_pack_layout():
    document = daily_doc()
    assert document["format"] == "v4-daily-pack/1"
    assert document["daily"]["BTCUSDT"][1] == [
        T0 + DAY,
        "94000.00",
        "94100.00",
        "93900.00",
        "94100.25",
        "1175000.12345678",
    ]
    assert document["exclusions"] == {"USDCUSDT": "stablecoin", "WBTCUSDT": "wrapped"}
    assert document["universes"] == [
        {
            "month": "2025-01",
            "selected": ["BTCUSDT", "ETHUSDT"],
            "ranked": [["BTCUSDT", "9.5E+9", 30], ["ETHUSDT", "4123456789.12345678", 29]],
            "excluded": [["USDCUSDT", "stablecoin"], ["WBTCUSDT", "wrapped"]],
            "entered": ["ETHUSDT"],
            "left": ["XRPUSDT"],
        }
    ]
    assert set(document) == {
        "format",
        "config_sha256",
        "end_month",
        "manifest",
        "daily",
        "exclusions",
        "masks",
        "universes",
    }


def test_hourly_pack_layout():
    document = hourly_doc()
    assert document["format"] == "v4-hourly-pack/1"
    # volume comes before quote_volume, and the two differ here
    assert document["spot"]["BTCUSDT"][1] == [
        T0 + HOUR,
        "94000.00",
        "94100.00",
        "93900.00",
        "94075.00",
        "12.50000000",
        "1175000.12345678",
    ]
    assert document["futures"]["BTCUSDT"][0][4] == "94060.00"
    assert document["funding"]["BTCUSDT"] == [
        [T0, "0.00010000", 8],
        [T0 + 8 * HOUR, "-0.00005000", None],
    ]
    assert document["rules"]["BTCUSDT|futures"] == {
        "source": "present_day",
        "step": "0.00001000",
        "min_qty": "0.00001000",
        "max_qty": "9000.00000000",
        "min_notional": "5.00000000",
        "tick": "0.10",
    }
    assert document["rules"]["ETHUSDT|spot"]["source"] == "inferred"
    assert set(document) == {
        "format",
        "config_sha256",
        "end_month",
        "manifest",
        "spot",
        "futures",
        "masks",
        "funding",
        "funding_months",
        "rules",
        "perpetuals",
    }
    assert document["perpetuals"] == {"BTCUSDT": {"symbol": "BTCUSDT", "multiplier": 1}}


def multiplier_args(**overrides: Any) -> dict[str, Any]:
    """BTC with its plain perpetual, SHIB with 1000SHIBUSDT and BABYDOGE with 1MBABYDOGEUSDT;
    ETH has none. Every futures structure is keyed by the perpetual's own symbol."""
    clean: tuple[list[int], dict[str, str]] = ([], {})
    args = hourly_args()
    args["manifest"] = [
        *args["manifest"],
        entry("futures_1h", "1000SHIBUSDT", "2025-01"),
        entry("funding", "1000SHIBUSDT", "2025-01"),
        entry("futures_1h", "1MBABYDOGEUSDT", "2025-01"),
    ]
    args["spot"] |= {"SHIBUSDT": [hour_bar(0, "0.00001234")], "BABYDOGEUSDT": [hour_bar(0)]}
    args["futures"] |= {"1000SHIBUSDT": [hour_bar(0, "0.01234")], "1MBABYDOGEUSDT": [hour_bar(0)]}
    for symbol, venue in [
        ("SHIBUSDT", "spot"),
        ("BABYDOGEUSDT", "spot"),
        ("1000SHIBUSDT", "futures"),
        ("1MBABYDOGEUSDT", "futures"),
    ]:
        args["masks"][(symbol, venue)] = clean
        args["rules"][(symbol, venue)] = (rules(), "present_day")
    args["funding"]["1000SHIBUSDT"] = [FundingRow(T0, D("0.00010000"), 8)]
    args["funding_months"][("1000SHIBUSDT", "2025-01")] = "complete"
    args["perpetuals"] = {
        "BTCUSDT": {"symbol": "BTCUSDT", "multiplier": 1},
        "SHIBUSDT": {"symbol": "1000SHIBUSDT", "multiplier": 1000},
        "BABYDOGEUSDT": {"symbol": "1MBABYDOGEUSDT", "multiplier": 1_000_000},
    }
    return args | overrides


def test_hourly_pack_records_each_perpetual_and_its_multiplier(tmp_path):
    document = hourly_pack_document(**multiplier_args())

    assert document["perpetuals"] == {
        "BTCUSDT": {"symbol": "BTCUSDT", "multiplier": 1},
        "SHIBUSDT": {"symbol": "1000SHIBUSDT", "multiplier": 1000},
        "BABYDOGEUSDT": {"symbol": "1MBABYDOGEUSDT", "multiplier": 1_000_000},
    }
    assert sorted(document["spot"]) == ["BABYDOGEUSDT", "BTCUSDT", "ETHUSDT", "SHIBUSDT"]
    assert sorted(document["futures"]) == ["1000SHIBUSDT", "1MBABYDOGEUSDT", "BTCUSDT"]
    assert document["futures"]["1000SHIBUSDT"][0][4] == "0.01234"  # the perpetual's own price
    assert {"1000SHIBUSDT|futures", "SHIBUSDT|spot"} <= set(document["masks"])
    assert {"1000SHIBUSDT|futures", "SHIBUSDT|spot"} <= set(document["rules"])
    assert document["funding_months"]["1000SHIBUSDT|2025-01"] == "complete"
    path = tmp_path / "hourly.json.gz"
    assert (
        read_canonical(path, write_canonical(document, path))["perpetuals"]
        == (document["perpetuals"])
    )


def shib(symbol: object = "1000SHIBUSDT", multiplier: object = 1000) -> dict[str, Any]:
    """multiplier_args' perpetuals with SHIB's entry replaced."""
    perpetuals = dict(multiplier_args()["perpetuals"])
    perpetuals["SHIBUSDT"] = {"symbol": symbol, "multiplier": multiplier}
    return perpetuals


@pytest.mark.parametrize(
    ("perpetuals", "why"),
    [
        (shib(multiplier=100), "multiplier must be one of"),
        (shib(multiplier=True), "multiplier must be one of"),
        (shib(multiplier="1000"), "multiplier must be one of"),
        (shib(multiplier=1000.0), "multiplier must be one of"),
        (shib("1MSHIBUSDT", 1000), "not SHIBUSDT's perpetual name for multiplier 1000"),
        (shib("SHIBUSDT", 1000), "not SHIBUSDT's perpetual name for multiplier 1000"),
        (shib("1000SHIBUSDT", 1), "not SHIBUSDT's perpetual name for multiplier 1"),
        (shib("1000000SHIBUSDT", 10_000), "not SHIBUSDT's perpetual name for multiplier 10000"),
        (shib(["1000SHIBUSDT"], 1000), "not SHIBUSDT's perpetual name"),
        (
            {
                "BTCUSDT": {"symbol": "BTCUSDT", "multiplier": 1},
                "SHIBUSDT": {"symbol": "1000SHIBUSDT", "multiplier": 1000},
            },
            r"futures series without a perpetual entry: \['1MBABYDOGEUSDT'\]",
        ),
        (
            shib() | {"ETHUSDT": {"symbol": "ETHUSDT", "multiplier": 1}},
            r"perpetual entries without a futures series: \['ETHUSDT'\]",
        ),
        (
            shib() | {"XRPUSDT": {"symbol": "XRPUSDT", "multiplier": 1}},
            "XRPUSDT is not a spot symbol of the pack",
        ),
        ({**shib(), "SHIBUSDT": ("1000SHIBUSDT", 1000)}, r"\{symbol, multiplier\}"),
        (
            {**shib(), "SHIBUSDT": {"symbol": "1000SHIBUSDT", "multiplier": 1000, "x": 1}},
            r"\{symbol, multiplier\}",
        ),
        ([("SHIBUSDT", "1000SHIBUSDT")], "mapping"),
    ],
)
def test_hourly_pack_refuses_a_perpetual_entry_that_breaks_the_naming_rule(perpetuals, why):
    with pytest.raises(ValueError, match=why):
        hourly_pack_document(**multiplier_args(perpetuals=perpetuals))


def test_hourly_pack_refuses_one_perpetual_for_two_coins():
    # SHIBUSDT x1000 and a spot 1000SHIBUSDT x1 each name 1000SHIBUSDT by the rule; compared as
    # a set with the futures series, the second entry would pass unseen.
    args = multiplier_args()
    args["spot"]["1000SHIBUSDT"] = [hour_bar(0)]
    args["masks"][("1000SHIBUSDT", "spot")] = ([], {})
    args["rules"][("1000SHIBUSDT", "spot")] = (rules(), "inferred")
    args["perpetuals"]["1000SHIBUSDT"] = {"symbol": "1000SHIBUSDT", "multiplier": 1}
    with pytest.raises(
        ValueError, match="1000SHIBUSDT is the perpetual of both 1000SHIBUSDT and SHIBUSDT"
    ):
        hourly_pack_document(**args)


def test_a_perpetual_left_out_of_the_pack_leaves_out_its_entry():
    # Ruling P23: a perpetual with no readable bar is omitted, with its rules, masks, funding
    # and its perpetuals entry; the coin's spot series stays.
    args = multiplier_args()
    del args["futures"]["1MBABYDOGEUSDT"]
    del args["masks"][("1MBABYDOGEUSDT", "futures")]
    del args["rules"][("1MBABYDOGEUSDT", "futures")]
    with pytest.raises(
        ValueError, match=r"perpetual entries without a futures series: \['1MBABYDOGEUSDT'\]"
    ):
        hourly_pack_document(**args)
    del args["perpetuals"]["BABYDOGEUSDT"]
    document = hourly_pack_document(**args)
    assert "BABYDOGEUSDT" in document["spot"] and "BABYDOGEUSDT" not in document["perpetuals"]


def test_documents_record_config_sha256_end_month_and_every_manifest_entry():
    raw_sha = hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest()
    for document, args in ((daily_doc(), daily_args()), (hourly_doc(), hourly_args())):
        assert document["config_sha256"] == raw_sha
        assert document["end_month"] == CONFIG.end_month == END_MONTH
        originals = sorted(args["manifest"], key=lambda e: (e.kind, e.symbol, e.month))
        assert len(document["manifest"]) == len(args["manifest"]) > 1
        for stored, original in zip(document["manifest"], originals, strict=True):
            assert stored == {
                "kind": original.kind,
                "symbol": original.symbol,
                "month": original.month,
                "path": original.path,
                "sha256": original.sha256,
                "bytes": original.bytes,
            }


def test_manifest_is_sorted_by_kind_symbol_and_month():
    entries = [
        entry("spot_1h", "ETHUSDT", "2025-01"),
        entry("funding", "BTCUSDT", "2025-02"),
        entry("spot_1h", "BTCUSDT", "2025-02"),
        entry("funding", "BTCUSDT", "2025-01"),
        entry("futures_1h", "BTCUSDT", "2025-01"),
        entry("spot_1h", "BTCUSDT", "2025-01"),
    ]
    stored = hourly_doc(manifest=entries)["manifest"]
    assert [(e["kind"], e["symbol"], e["month"]) for e in stored] == [
        ("funding", "BTCUSDT", "2025-01"),
        ("funding", "BTCUSDT", "2025-02"),
        ("futures_1h", "BTCUSDT", "2025-01"),
        ("spot_1h", "BTCUSDT", "2025-01"),
        ("spot_1h", "BTCUSDT", "2025-02"),
        ("spot_1h", "ETHUSDT", "2025-01"),
    ]


def test_packs_record_masks_and_unreadable_months():
    feb_hours = list(range(FEB, FEB + 28 * DAY, HOUR))
    reason = "archive cannot be read: File is not a zip file"
    document = hourly_doc(
        spot={"BTCUSDT": [hour_bar(0)], "ETHUSDT": [hour_bar(0)]},
        masks={
            # one masked hour (a dropped row) and one repaired hour (masked too, spec rule)
            ("BTCUSDT", "spot"): ([T0 + 5 * HOUR, T0 + 7 * HOUR], {}),
            ("ETHUSDT", "spot"): ([], {}),  # a clean symbol
            # an unreadable month masks every hour of it
            ("BTCUSDT", "futures"): (feb_hours, {"2025-02": reason}),
        },
    )
    assert document["masks"] == {
        "BTCUSDT|spot": {"masked": [T0 + 5 * HOUR, T0 + 7 * HOUR], "unreadable": {}},
        "ETHUSDT|spot": {"masked": [], "unreadable": {}},
        "BTCUSDT|futures": {"masked": feb_hours, "unreadable": {"2025-02": reason}},
    }
    daily = daily_doc(masks={"BTCUSDT": ([T0 + 3 * DAY], {"2025-02": "boom"}), "ETHUSDT": ([], {})})
    assert daily["masks"] == {
        "BTCUSDT": {"masked": [T0 + 3 * DAY], "unreadable": {"2025-02": "boom"}},
        "ETHUSDT": {"masked": [], "unreadable": {}},
    }


def test_hourly_pack_records_every_funding_month_status():
    document = hourly_doc(
        funding_months={
            ("BTCUSDT", "2025-01"): "complete",
            ("BTCUSDT", "2025-02"): "missing_slot",
            ("BTCUSDT", "2025-03"): "missing_file",
        }
    )
    assert document["funding_months"] == {
        "BTCUSDT|2025-01": "complete",
        "BTCUSDT|2025-02": "missing_slot",
        "BTCUSDT|2025-03": "missing_file",
    }
    # the funding rows keep interval_hours, a missing column included
    assert [row[2] for row in document["funding"]["BTCUSDT"]] == [8, None]


def funding_month(interval: int = 8, *, skip: int | None = None) -> list[FundingRow]:
    """One row per slot of January 2025, none at index ``skip``."""
    slots = range(T0, FEB, interval * HOUR)
    return [FundingRow(t, D("0.0001"), interval) for i, t in enumerate(slots) if i != skip]


def test_every_status_the_funding_check_returns_is_accepted():
    """The reasons come from ``funding_month_status`` itself, so the pack cannot drift from it."""
    full = funding_month()
    rows = {
        "complete": full,
        "missing_slot": funding_month(skip=3),
        "duplicate_slot": [*full, FundingRow(T0 + 8 * HOUR + 1000, D("0.0001"), 8)],
        "off_slot": [*full, FundingRow(T0 + HOUR, D("0.0001"), 8)],
        "interval_mixed": [*full[:-1], FundingRow(full[-1].time_ms, D("0.0001"), 4)],
        "interval_not_divisor_of_24": funding_month(5),
    }
    for expected, month_rows in rows.items():
        status = funding_month_status(month_rows, "2025-01", first_ms=T0, last_ms=FEB - 1)
        assert status == expected
        document = hourly_doc(funding_months={("BTCUSDT", "2025-01"): status})
        assert document["funding_months"] == {"BTCUSDT|2025-01": expected}
    for status in ("missing_file", "unreadable_file"):  # recorded by the caller (ruling P13)
        document = hourly_doc(funding_months={("BTCUSDT", "2025-01"): status})
        assert document["funding_months"] == {"BTCUSDT|2025-01": status}


def test_config_json_is_lf_in_gitattributes():
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert "config/v4_*.json text eol=lf" in lines
    # the config's raw-byte SHA-256 is the same on Windows and CI only if no CR is in it
    assert b"\r" not in CONFIG_PATH.read_bytes()


# ---- refusals ----


def no_masks_for(*symbols: str) -> dict[str, tuple[list[int], dict[str, str]]]:
    return {symbol: ([], {}) for symbol in symbols}


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"config_sha256": "A" * 64}, "config_sha256"),
        ({"config_sha256": "a" * 63}, "config_sha256"),
        ({"config_sha256": None}, "config_sha256"),
        ({"masks": {"BTCUSDT": ([T0 + DAY, T0], {}), "ETHUSDT": ([], {})}}, "sorted"),
        ({"masks": {"BTCUSDT": ([T0, T0], {}), "ETHUSDT": ([], {})}}, "unique"),
        ({"masks": {"BTCUSDT": ([1.5], {}), "ETHUSDT": ([], {})}}, "int"),
        ({"masks": {"BTCUSDT": ([True], {}), "ETHUSDT": ([], {})}}, "int"),
        ({"masks": {"BTCUSDT": ([], {"2025-13": "x"}), "ETHUSDT": ([], {})}}, "YYYY-MM"),
        ({"masks": {"BTCUSDT": ([], {AFTER_END: "x"}), "ETHUSDT": ([], {})}}, "after end_month"),
        ({"masks": {"BTCUSDT": ([], {"2025-02": ""}), "ETHUSDT": ([], {})}}, "reason"),
        ({"masks": no_masks_for("BTCUSDT")}, "ETHUSDT"),
        ({"masks": no_masks_for("BTCUSDT", "ETHUSDT", "XRPUSDT")}, "XRPUSDT"),
        ({"exclusions": {"usdcusdt": "stablecoin"}}, "symbol"),
        ({"exclusions": {"USDCUSDT": ""}}, "reason"),
        ({"daily": {"BTCUSDT": [day_bar(1), day_bar(0)], "ETHUSDT": []}}, "increasing"),
        ({"daily": {"BTCUSDT": [day_bar(0), day_bar(0)], "ETHUSDT": []}}, "increasing"),
        ({"daily": {"BTCUSDT": [replace(day_bar(0), open_ms=float(T0))], "ETHUSDT": []}}, "int"),
        ({"daily": {"BTCUSDT": [replace(day_bar(0), close=94050.5)], "ETHUSDT": []}}, "Decimal"),
        (
            {"daily": {"BTCUSDT": [replace(day_bar(0), close=D("NaN"))], "ETHUSDT": []}},
            "finite",
        ),
        ({"universes": [universe(AFTER_END)]}, "after end_month"),
        ({"universes": ["2025-01"]}, "MonthlyUniverse"),
        ({"universes": [universe("2025-02"), universe("2025-01")]}, "strictly increasing"),
        ({"universes": [universe("2025-01"), universe("2025-01")]}, "no duplicate"),
        (
            {"universes": [universe("2025-01"), universe("2025-03"), universe("2025-02")]},
            "2025-02 after 2025-03",
        ),
    ],
)
def test_daily_pack_document_refuses_bad_input(overrides, why):
    with pytest.raises(ValueError, match=why):
        daily_doc(**overrides)


def test_universe_months_may_skip_but_must_increase():
    months = [universe("2024-12"), universe("2025-01"), universe("2025-03"), universe(END_MONTH)]
    stored = daily_doc(universes=months)["universes"]
    assert [u["month"] for u in stored] == ["2024-12", "2025-01", "2025-03", END_MONTH]


def test_the_end_month_itself_is_allowed_and_the_next_month_is_refused():
    config = replace(CONFIG, end_month="2025-02")
    allowed = hourly_doc(config=config, manifest=[entry("spot_1h", "BTCUSDT", "2025-02")])
    assert allowed["end_month"] == "2025-02"
    with pytest.raises(ValueError, match="after end_month"):
        hourly_doc(config=config, manifest=[entry("spot_1h", "BTCUSDT", "2025-03")])
    with pytest.raises(ValueError, match="after end_month"):
        daily_doc(config=config, universes=[universe("2025-03")])


def test_a_universe_mean_that_is_not_a_decimal_is_refused():
    bad = replace(universe(), ranked=(("BTCUSDT", 9.5, 30),))
    with pytest.raises(ValueError, match="Decimal"):
        daily_doc(universes=[bad])
    bad = replace(universe(), ranked=(("BTCUSDT", D("9.5"), 30.0),))
    with pytest.raises(ValueError, match="int"):
        daily_doc(universes=[bad])


@pytest.mark.parametrize(
    ("overrides", "why"),
    [
        ({"manifest": [entry("spot_1h", "BTCUSDT", AFTER_END)]}, "after end_month"),
        (
            {"manifest": [entry("spot_1h", "BTCUSDT", "2025-01")] * 2},
            "twice",
        ),
        (
            {"manifest": [replace(entry("spot_1h", "BTCUSDT", "2025-01"), path="/x.zip")]},
            "path",
        ),
        (
            {"manifest": [replace(entry("spot_1h", "BTCUSDT", "2025-01"), sha256="AB" * 32)]},
            "sha256",
        ),
        (
            {"manifest": [replace(entry("spot_1h", "BTCUSDT", "2025-01"), bytes=-1)]},
            "bytes",
        ),
        ({"manifest": ["BTCUSDT"]}, "ManifestEntry"),
        ({"funding_months": {("BTCUSDT", "2025-01"): "partial"}}, "status"),
        ({"funding_months": {("BTCUSDT", "2025-1"): "complete"}}, "YYYY-MM"),
        ({"funding_months": {("BTCUSDT", AFTER_END): "complete"}}, "after end_month"),
        ({"funding_months": {("ETHUSDT", "2025-01"): "complete"}}, "futures"),
        ({"funding_months": {"BTCUSDT": "complete"}}, "pair"),
        ({"funding": {"ETHUSDT": []}}, "futures"),
        ({"funding": {"BTCUSDT": [(T0, D("0.0001"), 8)]}}, "FundingRow"),
        ({"funding": {"BTCUSDT": [FundingRow(T0, 0.0001, 8)]}}, "Decimal"),
        ({"funding": {"BTCUSDT": [FundingRow(T0, D("0.0001"), 8.0)]}}, "int"),
        ({"funding": {"BTCUSDT": [FundingRow(float(T0), D("0.0001"), 8)]}}, "int"),
        (
            {"masks": {("BTCUSDT", "spot"): ([], {}), ("ETHUSDT", "spot"): ([], {})}},
            r"masks: missing \['BTCUSDT\|futures'\]",
        ),
        ({"masks": no_masks_for("BTCUSDT")}, "pair"),
        (
            {
                "masks": {
                    ("BTCUSDT", "margin"): ([], {}),
                    ("ETHUSDT", "spot"): ([], {}),
                    ("BTCUSDT", "futures"): ([], {}),
                }
            },
            "venue",
        ),
        (
            {
                "masks": {
                    ("BTCUSDT", "spot"): ([T0 + HOUR, T0], {}),
                    ("ETHUSDT", "spot"): ([], {}),
                    ("BTCUSDT", "futures"): ([], {}),
                }
            },
            "sorted",
        ),
        (
            {
                "masks": {
                    ("BTCUSDT", "spot"): ([], {AFTER_END: "x"}),
                    ("ETHUSDT", "spot"): ([], {}),
                    ("BTCUSDT", "futures"): ([], {}),
                }
            },
            "after end_month",
        ),
        (
            {"rules": {("BTCUSDT", "spot"): (rules(), "present_day")}},
            "rules",
        ),
        (
            {
                "rules": {
                    ("BTCUSDT", "spot"): (rules(), "guessed"),
                    ("ETHUSDT", "spot"): (rules(), "inferred"),
                    ("BTCUSDT", "futures"): (rules(), "present_day"),
                }
            },
            "source",
        ),
        (
            {
                "rules": {
                    ("BTCUSDT", "spot"): ("rules", "present_day"),
                    ("ETHUSDT", "spot"): (rules(), "inferred"),
                    ("BTCUSDT", "futures"): (rules(), "present_day"),
                }
            },
            "VenueRules",
        ),
        ({"spot": {"btcusdt": [hour_bar(0)], "ETHUSDT": [hour_bar(0)]}}, "symbol"),
        ({"spot": {"BTCUSDT": [hour_bar(1), hour_bar(0)], "ETHUSDT": [hour_bar(0)]}}, "increasing"),
        ({"spot": {"BTCUSDT": [hour_bar(0)], "ETHUSDT": [day_bar(0)]}}, "HourBar"),
        ({"config_sha256": "not a hash"}, "config_sha256"),
    ],
)
def test_hourly_pack_document_refuses_bad_input(overrides, why):
    with pytest.raises(ValueError, match=why):
        hourly_doc(**overrides)


def test_a_mask_or_rule_for_a_series_the_pack_does_not_hold_is_refused():
    extra = hourly_args()
    extra["masks"][("XRPUSDT", "spot")] = ([], {})
    with pytest.raises(ValueError, match="XRPUSDT"):
        hourly_pack_document(**extra)
    extra = hourly_args()
    extra["rules"][("XRPUSDT", "futures")] = (rules(), "inferred")
    with pytest.raises(ValueError, match="XRPUSDT"):
        hourly_pack_document(**extra)


def test_the_hourly_pack_keeps_a_symbol_in_both_venues_apart():
    document = hourly_doc()
    assert {"BTCUSDT|spot", "BTCUSDT|futures"} <= set(document["masks"])
    assert {"BTCUSDT|spot", "BTCUSDT|futures"} <= set(document["rules"])


def test_documents_are_built_from_sequences_of_any_kind():
    bars: Sequence[DailyBar] = tuple(day_bar(k) for k in range(3))
    document = daily_doc(
        daily={"BTCUSDT": bars, "ETHUSDT": ()},
        masks={"BTCUSDT": ((T0, T0 + DAY), {}), "ETHUSDT": ((), {})},
    )
    assert len(document["daily"]["BTCUSDT"]) == 3 and document["daily"]["ETHUSDT"] == []
    assert document["masks"]["BTCUSDT"]["masked"] == [T0, T0 + DAY]
