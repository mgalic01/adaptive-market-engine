"""V4 data step: the CLI (``scripts/v4_data.py``) end to end, and its GitHub workflow.

The network is blocked for every test in this file (the autouse fixture below). The CLI runs
against ``FakeBinance``, a small two-month world (archives for 2024-01 and 2024-02) served as
S3 listing XML, zips and ``.CHECKSUM`` files. It records every URL it is asked for and answers
only URLs the real transport's allowlist accepts. ``end_month`` is 2024-03, so the universe has
two selections (2024-02 and 2024-03, each judged on the months before it), and the world also
lists an archive for 2024-04, which must never be requested.

The world, symbol by symbol (quote volumes rank them in this order):

* AAAUSDT: every kind, complete; listed in both filter snapshots (present-day rules). Its
  daily row of 15 January is repaired (kept in the pack, masked, so not counted by the
  selection: ruling P24). Its February spot archive starts with a stray January row (a mask
  outside the month, ruling P12) and repeats the 05:00 row of 10 February (a masked hour);
* BBBUSDT: every kind; its February funding file is missing (``"missing_file"``);
* CCCUSDT: spot hourly bars only until 10 January, so it ranks but is always skipped for want
  of recent hourly bars;
* EEEUSDT: its February daily archive is unreadable (a dead market at 2024-03), and its only
  futures archive is unreadable too (no futures market in the data, ruling P23);
* FFFUSDT: every kind, complete, but its perpetual is the multiplier contract 1000FFFUSDT (one
  unit is 1000 coins): Binance lists no FFFUSDT perpetual. Its futures and funding archives are
  under the perpetual's name, which the futures filter snapshot lists;
* LATEUSDT: daily bars from 20 January only (too little history at 2024-02, ranked at
  2024-03); its perpetual opens at 17:00 on 31 January, so January expects no funding slot
  (ruling P16), and its February funding file is unreadable (ruling P13);
* USDCUSDT and AAAUPUSDT: excluded whatever their prices (stablecoin, leveraged token);
* AAABTC: not quoted in USDT, so not discovered.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import socket
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from crypto_grid_bot.v4.data import archives, inputs
from crypto_grid_bot.v4.data.archives import archive_path
from crypto_grid_bot.v4.data.pack import read_canonical

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import v4_data  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "v4-data.yml"
LISTING = archives.LISTING_URL
ARCHIVE = archives.ARCHIVE_URL
NS = "http://s3.amazonaws.com/doc/2006-03-01/"
HOUR = 3_600_000
DAY = 24 * HOUR
END_MONTH = "2024-03"
JAN, FEB = "2024-01", "2024-02"
HOURLY_KINDS = ("spot_1h", "futures_1h", "funding")
HOURLY_PACK_FILE = "hourly.pack.json.gz"
FUTURES_HEADER = (
    "open_time,open,high,low,close,volume,close_time,quote_volume,count,"
    "taker_buy_volume,taker_buy_quote_volume,ignore"
)
# Distinctive bar values, so a test can tell whether any of them reached the output.
PRICES = ("4321.9871", "4329.1234", "4310.5555", "4325.4321")
VOLUME = "77.777"
HOURLY_QUOTE_VOLUME = "336633.21"
FUNDING_RATE = "0.00012345"
DAILY_QUOTE_VOLUMES = {
    "AAAUSDT": "900000.11",
    "BBBUSDT": "500000.22",
    "CCCUSDT": "300000.33",
    "EEEUSDT": "200000.44",
    "FFFUSDT": "150000.66",
    "LATEUSDT": "100000.55",
}
BAR_VALUES = (*PRICES, VOLUME, HOURLY_QUOTE_VOLUME, FUNDING_RATE, *DAILY_QUOTE_VOLUMES.values())
GARBAGE = b"this is not a zip archive"
REPAIRED_DAY = int(datetime(2024, 1, 15, tzinfo=UTC).timestamp()) * 1000  # AAAUSDT's
SPOT_DIRS = ("AAABTC", "AAAUPUSDT", "AAAUSDT", "BBBUSDT", "CCCUSDT", "EEEUSDT", "FFFUSDT")
SPOT_DIRS += ("LATEUSDT", "USDCUSDT")
SPOT_KLINES = "data/spot/monthly/klines/"
FUTURES_KLINES = "data/futures/um/monthly/klines/"


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


# --- the fake world --------------------------------------------------------------------------


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def month_start(month: str) -> int:
    year, number = (int(part) for part in month.split("-"))
    return int(datetime(year, number, 1, tzinfo=UTC).timestamp()) * 1000


def kline_csv(
    opens, step: int, quote_volume: str, *, header: bool = False, repaired: int | None = None
) -> str:
    """Kline rows; the row opening at ``repaired`` closes 1 ms early, which the reader repairs
    (the bar is kept) and masks."""
    o, h, low, c = PRICES
    lines = [FUTURES_HEADER] if header else []
    for t in opens:
        close = t + step - (2 if t == repaired else 1)
        lines.append(f"{t},{o},{h},{low},{c},{VOLUME},{close},{quote_volume},5,0.25,0.5,0")
    return "".join(line + "\n" for line in lines)


def funding_csv(start: int, end: int) -> str:
    rows = [f"{slot},8,{FUNDING_RATE}" for slot in range(start, end, 8 * HOUR)]
    return "".join(
        line + "\n" for line in ["calc_time,funding_interval_hours,last_funding_rate"] + rows
    )


def listing_xml(prefixes=(), keys=()) -> bytes:
    parts = [f'<?xml version="1.0" encoding="UTF-8"?><ListBucketResult xmlns="{NS}">']
    parts.append("<Name>data.binance.vision</Name><IsTruncated>false</IsTruncated>")
    parts += [f"<Contents><Key>{key}</Key><Size>1</Size></Contents>" for key in keys]
    parts += [f"<CommonPrefixes><Prefix>{p}</Prefix></CommonPrefixes>" for p in prefixes]
    parts.append("</ListBucketResult>")
    return "".join(parts).encode("utf-8")


class FakeBinance:
    """Serves the world's listings, archives and checksums; records each URL it is asked for.

    Every URL first goes through the real ``HttpTransport`` allowlist, so a URL the real
    transport would refuse fails the test here too. A path in ``listed_only`` is listed but
    answered with a 404. The spot klines directories are ``spot_dirs``; the futures klines
    directories are those of the world's futures archives.
    """

    def __init__(self, files: dict[str, bytes]):
        self.files = files  # archive path -> bytes
        self.listed_only: set[str] = set()
        self.spot_dirs = list(SPOT_DIRS)
        self.requests: list[str] = []

    def get(self, url: str) -> bytes | None:
        archives._size_limit(url)  # raises for any URL HttpTransport would not request
        self.requests.append(url)
        if url.startswith(LISTING + "?"):
            prefix = url[len(LISTING) + 1 :].removeprefix("delimiter=/&prefix=")
            assert "&" not in prefix, "the world's listings fit on one page"
            paths = [path.lstrip("/") for path in [*self.files, *self.listed_only]]
            if prefix == SPOT_KLINES:
                return listing_xml(prefixes=[f"{prefix}{name}/" for name in self.spot_dirs])
            if prefix == FUTURES_KLINES:
                names = {path.split("/")[5] for path in paths if path.startswith(prefix)}
                return listing_xml(prefixes=[f"{prefix}{name}/" for name in sorted(names)])
            keys = [
                key
                for path in paths
                if path.rsplit("/", 1)[0] + "/" == prefix
                for key in (path, path + ".CHECKSUM")
            ]
            return listing_xml(keys=sorted(keys))
        path = url[len(ARCHIVE) :]
        if path.endswith(".CHECKSUM"):
            content = self.files.get(path.removesuffix(".CHECKSUM"))
            name = path.removesuffix(".CHECKSUM").rsplit("/", 1)[1]
            return None if content is None else f"{sha(content)}  {name}\n".encode("ascii")
        return self.files.get(path)

    def archive_requests(self) -> list[str]:
        return [url for url in self.requests if url.startswith(ARCHIVE)]


def build_world(*, spot_january_days: int = 31) -> FakeBinance:
    """The world above. With ``spot_january_days`` below 25, AAA's, BBB's and EEE's January
    spot hourly bars stop more than 168 hours before 2024-02-01, so no candidate passes that
    month's hourly check."""
    files: dict[str, bytes] = {}

    def put(kind: str, symbol: str, month: str, text: str | None = None) -> None:
        path = archive_path(kind, symbol, month)
        if text is None:
            files[path] = GARBAGE
            return
        member = path.rsplit("/", 1)[1].removesuffix(".zip") + ".csv"
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member, text)
        files[path] = stream.getvalue()

    j0, f0, m0 = month_start(JAN), month_start(FEB), month_start("2024-03")
    for symbol, volume in DAILY_QUOTE_VOLUMES.items():
        first = j0 + 19 * DAY if symbol == "LATEUSDT" else j0
        repaired = REPAIRED_DAY if symbol == "AAAUSDT" else None
        jan = kline_csv(range(first, f0, DAY), DAY, volume, repaired=repaired)
        put("spot_1d", symbol, JAN, jan)
        feb = None if symbol == "EEEUSDT" else kline_csv(range(f0, m0, DAY), DAY, volume)
        put("spot_1d", symbol, FEB, feb)
    for symbol in ("USDCUSDT", "AAAUPUSDT"):
        put("spot_1d", symbol, JAN, kline_csv(range(j0, f0, DAY), DAY, "999.99"))
    april = month_start("2024-04")
    put("spot_1d", "AAAUSDT", "2024-04", kline_csv(range(april, april + DAY, DAY), DAY, "1.5"))

    full_jan, full_feb = range(j0, f0, HOUR), range(f0, m0, HOUR)
    spot_jan = range(j0, j0 + spot_january_days * DAY, HOUR)
    for symbol in ("AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT"):
        put("spot_1h", symbol, JAN, kline_csv(spot_jan, HOUR, HOURLY_QUOTE_VOLUME))
    duplicate = f0 + 9 * DAY + 5 * HOUR
    aaa_feb = [f0 - HOUR] + sorted([*full_feb, duplicate])
    put("spot_1h", "AAAUSDT", FEB, kline_csv(aaa_feb, HOUR, HOURLY_QUOTE_VOLUME))
    for symbol in ("BBBUSDT", "EEEUSDT", "FFFUSDT", "LATEUSDT"):
        put("spot_1h", symbol, FEB, kline_csv(full_feb, HOUR, HOURLY_QUOTE_VOLUME))
    put(
        "spot_1h",
        "CCCUSDT",
        JAN,
        kline_csv(range(j0, j0 + 10 * DAY, HOUR), HOUR, HOURLY_QUOTE_VOLUME),
    )
    late_jan = range(j0 + 19 * DAY, f0, HOUR)
    put("spot_1h", "LATEUSDT", JAN, kline_csv(late_jan, HOUR, HOURLY_QUOTE_VOLUME))

    for symbol in ("AAAUSDT", "BBBUSDT", "1000FFFUSDT"):
        put("futures_1h", symbol, JAN, kline_csv(full_jan, HOUR, HOURLY_QUOTE_VOLUME, header=True))
        put("futures_1h", symbol, FEB, kline_csv(full_feb, HOUR, HOURLY_QUOTE_VOLUME, header=True))
        put("funding", symbol, JAN, funding_csv(j0, f0))
    put("funding", "AAAUSDT", FEB, funding_csv(f0, m0))
    put("funding", "1000FFFUSDT", FEB, funding_csv(f0, m0))
    put("futures_1h", "EEEUSDT", JAN)  # unreadable
    put("funding", "EEEUSDT", JAN, funding_csv(j0, f0))
    late_futures = range(f0 - 7 * HOUR, f0, HOUR)  # 17:00 to 23:00 on 31 January
    put(
        "futures_1h",
        "LATEUSDT",
        JAN,
        kline_csv(late_futures, HOUR, HOURLY_QUOTE_VOLUME, header=True),
    )
    put("futures_1h", "LATEUSDT", FEB, kline_csv(full_feb, HOUR, HOURLY_QUOTE_VOLUME, header=True))
    put("funding", "LATEUSDT", FEB)  # unreadable
    return FakeBinance(files)


# --- the configuration and the filter snapshots ------------------------------------------------


def spot_entry(symbol: str, quote: str = "USDT") -> dict:
    return {
        "symbol": symbol,
        "status": "TRADING",
        "baseAsset": symbol.removesuffix("USDT"),
        "quoteAsset": quote,
        "filters": [
            {"filterType": "PRICE_FILTER", "minPrice": "0.01", "tickSize": "0.01"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "9000", "stepSize": "0.001"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }


def futures_entry(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "contractType": "PERPETUAL",
        "status": "TRADING",
        "quoteAsset": "USDT",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "1000", "stepSize": "0.001"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }


def write_config(tmp_path: Path, *, spot: dict | None = None) -> Path:
    """The committed config, cut to the fake world, with snapshots pinned in ``tmp_path``."""
    snapshots = {
        "spot": {"symbols": [spot or spot_entry("AAAUSDT")]},
        "futures": {"symbols": [futures_entry("AAAUSDT"), futures_entry("1000FFFUSDT")]},
    }
    pins = {}
    for venue, document in snapshots.items():
        path = tmp_path / f"{venue}-snapshot.json"
        path.write_bytes(json.dumps(document).encode("ascii"))
        pins[venue] = {"path": str(path), "sha256": sha(path.read_bytes())}
    config = json.loads((ROOT / "config" / "v4_data.json").read_text(encoding="utf-8"))
    config |= {
        "start_day": "2024-01-01",
        "end_month": END_MONTH,
        "min_daily_bars": 20,
        "filter_snapshots": pins,
    }
    path = tmp_path / "v4_data.json"
    path.write_bytes(json.dumps(config, indent=2).encode("ascii"))
    return path


class Pipeline:
    """Runs the CLI's stages as the workflow does, in folders under ``tmp_path``."""

    def __init__(self, tmp_path: Path, capsys, world: FakeBinance | None = None):
        self.tmp_path = tmp_path
        self.capsys = capsys
        self.world = world or build_world()
        self.config = write_config(tmp_path)
        work = tmp_path / "v4"
        self.discovery = work / "discover" / "symbols.json"
        self.cache = work / "fetched" / "cache"
        self.manifests = work / "fetched" / "manifests"
        self.candidates = work / "candidates" / "candidates.txt"
        self.final = work / "final"
        self.data = work / "data"
        self.out: list[str] = []
        self.err: list[str] = []

    def cli(self, *argv: object, expect: int = 0) -> None:
        code = v4_data.main(
            ["--config", str(self.config), *map(str, argv)],
            transport=self.world,
            sleep=lambda seconds: None,
        )
        captured = self.capsys.readouterr()
        self.out.append(captured.out)
        self.err.append(captured.err)
        assert code == expect, captured.err

    def manifest_files(self, kind: str) -> list[Path]:
        return sorted(self.manifests.glob(f"manifest-{kind}-*.json"))

    def discover(self) -> None:
        self.cli("discover", "--out", self.discovery.parent)

    def fetch(self, kind: str, shards: int) -> None:
        extra = [] if kind == "spot_1d" else ["--symbols-file", self.candidates]
        for index in range(shards):
            self.cli(
                "fetch", "--kind", kind, "--discovery", self.discovery, *extra,
                "--shard", f"{index}/{shards}", "--cache", self.cache, "--out", self.manifests,
            )  # fmt: skip

    def select_candidates(self, pieces: list[Path] | None = None, expect: int = 0) -> None:
        self.cli(
            "select", "--stage", "candidates", "--discovery", self.discovery,
            "--daily-manifests", *(pieces or self.manifest_files("spot_1d")),
            "--cache", self.cache, "--out", self.candidates.parent, expect=expect,
        )  # fmt: skip

    def select_final(self, expect: int = 0) -> None:
        self.cli(
            "select", "--stage", "final", "--discovery", self.discovery,
            "--daily-manifests", *self.manifest_files("spot_1d"),
            "--hourly-manifests", *self.manifest_files("spot_1h"),
            "--cache", self.cache, "--out", self.final, expect=expect,
        )  # fmt: skip

    def pack(self, expect: int = 0) -> None:
        self.cli(
            "pack", "--discovery", self.discovery,
            "--manifests", *sorted(self.manifests.glob("manifest-*.json")),
            "--universe", self.final / "universe.json",
            "--cache", self.cache, "--out", self.data, expect=expect,
        )  # fmt: skip

    def until_hourly(self) -> None:
        self.discover()
        self.fetch("spot_1d", 2)
        self.select_candidates()
        for kind in HOURLY_KINDS:
            self.fetch(kind, 2)

    def until_final(self) -> None:
        self.until_hourly()
        self.select_final()

    def run(self) -> None:
        self.until_final()
        self.pack()

    def stdout(self) -> str:
        return "".join(self.out)


def manifest_months(paths: list[Path], symbol: str) -> list[str]:
    entries = [entry for path in paths for entry in json.loads(path.read_text())["entries"]]
    return sorted(entry["month"] for entry in entries if entry["symbol"] == symbol)


def months_named(url: str) -> list[str]:
    return re.findall(r"(?<![0-9])([0-9]{4}-[0-9]{2})(?![0-9])", url)


# --- the CLI ---------------------------------------------------------------------------------


def test_end_to_end_on_a_fake_world_produces_both_packs_and_pins(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    assert data["config_sha256"] == sha(pipeline.config.read_bytes())
    assert data["end_month"] == END_MONTH
    daily_pin, hourly_pin = data["packs"]["daily"]["sha256"], data["packs"]["hourly"]["sha256"]
    daily = read_canonical(pipeline.data / data["packs"]["daily"]["file"], daily_pin)
    hourly = read_canonical(pipeline.data / data["packs"]["hourly"]["file"], hourly_pin)
    with gzip.open(pipeline.data / data["packs"]["hourly"]["file"]) as stream:
        assert data["packs"]["hourly"]["json_bytes"] == len(stream.read())
    for document in (daily, hourly):
        assert document["config_sha256"] == data["config_sha256"]
        assert document["end_month"] == END_MONTH

    # The daily pack: every candidate's daily bars, the static exclusions, the final universes.
    assert sorted(daily["daily"]) == sorted(DAILY_QUOTE_VOLUMES)
    assert daily["exclusions"] == {"AAAUPUSDT": "leveraged", "USDCUSDT": "stablecoin"}
    universes = {u["month"]: u for u in daily["universes"]}
    assert sorted(universes) == ["2024-02", END_MONTH]
    assert universes["2024-02"]["selected"] == ["AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT"]
    assert universes[END_MONTH]["selected"] == ["AAAUSDT", "BBBUSDT", "FFFUSDT", "LATEUSDT"]
    assert (universes[END_MONTH]["entered"], universes[END_MONTH]["left"]) == (
        ["LATEUSDT"],
        ["EEEUSDT"],
    )
    assert ["EEEUSDT", "dead_market"] in universes[END_MONTH]["excluded"]
    february_days = list(range(month_start(FEB), month_start("2024-03"), DAY))
    assert daily["masks"]["EEEUSDT"]["masked"] == february_days
    assert list(daily["masks"]["EEEUSDT"]["unreadable"]) == [FEB]
    # A repaired day stays in the pack with its mask but is not counted by the selection (P24).
    assert daily["masks"]["AAAUSDT"] == {"masked": [REPAIRED_DAY], "unreadable": {}}
    assert daily["masks"]["BBBUSDT"] == {"masked": [], "unreadable": {}}
    assert len(daily["daily"]["AAAUSDT"]) == 31 + 29
    window_bars = {symbol: bars for symbol, _, bars in universes["2024-02"]["ranked"]}
    assert (window_bars["AAAUSDT"], window_bars["BBBUSDT"]) == (29, 30)
    assert {entry["kind"] for entry in daily["manifest"]} == {"spot_1d", "spot_1h"}

    # The hourly pack: whole histories of the symbols ever selected, each futures series under
    # its perpetual's own symbol.
    assert sorted(hourly["spot"]) == ["AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT", "LATEUSDT"]
    assert sorted(hourly["futures"]) == ["1000FFFUSDT", "AAAUSDT", "BBBUSDT", "LATEUSDT"]
    assert hourly["perpetuals"] == {  # EEE: none readable, so no entry (ruling P23)
        "AAAUSDT": {"symbol": "AAAUSDT", "multiplier": 1},
        "BBBUSDT": {"symbol": "BBBUSDT", "multiplier": 1},
        "FFFUSDT": {"symbol": "1000FFFUSDT", "multiplier": 1000},
        "LATEUSDT": {"symbol": "LATEUSDT", "multiplier": 1},
    }
    assert len(hourly["spot"]["AAAUSDT"]) == 744 + 696  # bars as read
    duplicate = month_start(FEB) + 9 * DAY + 5 * HOUR
    assert hourly["masks"]["AAAUSDT|spot"] == {"masked": [duplicate], "unreadable": {}}
    assert hourly["masks"]["BBBUSDT|futures"] == {"masked": [], "unreadable": {}}
    assert "EEEUSDT|futures" not in hourly["masks"] and "EEEUSDT" not in hourly["funding"]
    assert hourly["funding_months"] == {
        "1000FFFUSDT|2024-01": "complete",
        "1000FFFUSDT|2024-02": "complete",
        "AAAUSDT|2024-01": "complete",
        "AAAUSDT|2024-02": "complete",
        "BBBUSDT|2024-01": "complete",
        "BBBUSDT|2024-02": "missing_file",
        "LATEUSDT|2024-01": "complete",
        "LATEUSDT|2024-02": "unreadable_file",
    }
    assert len(hourly["funding"]["AAAUSDT"]) == 93 + 87
    rules = hourly["rules"]
    series = {f"{s}|spot" for s in hourly["spot"]} | {f"{s}|futures" for s in hourly["futures"]}
    assert set(rules) == series
    assert (rules["AAAUSDT|spot"]["source"], rules["AAAUSDT|spot"]["tick"]) == (
        "present_day",
        "0.01",
    )
    assert rules["AAAUSDT|futures"]["source"] == "present_day"
    assert rules["BBBUSDT|spot"] == {
        "source": "inferred",
        "tick": "0.0001",
        "step": "0.001",
        "min_qty": "0.001",
        "max_qty": "9000000000",
        "min_notional": "5",
    }
    # Each manifest lists exactly the archives read for its pack: EEE's futures archive was
    # read (it decided that EEE has no perpetual), its funding file never was.
    read = {(e["kind"], e["symbol"], e["month"]) for e in hourly["manifest"]}
    assert ("futures_1h", "EEEUSDT", JAN) in read and ("funding", "EEEUSDT", JAN) not in read
    assert {symbol for kind, symbol, _ in read if kind == "funding"} == {
        "1000FFFUSDT",
        "AAAUSDT",
        "BBBUSDT",
        "LATEUSDT",
    }
    assert {symbol for kind, symbol, _ in read if kind == "spot_1h"} == set(hourly["spot"])
    assert {symbol for kind, symbol, _ in read if kind == "futures_1h"} == {
        "1000FFFUSDT",
        "AAAUSDT",
        "BBBUSDT",
        "EEEUSDT",
        "LATEUSDT",
    }  # no CCC: never selected, and without a perpetual anyway
    assert len(daily["manifest"]) == 12 + 11  # every daily archive and every spot hourly one

    # Nothing after end_month was asked for, and nothing statically excluded was fetched.
    assert all(month <= END_MONTH for url in pipeline.world.requests for month in months_named(url))
    assert not [url for url in pipeline.world.archive_requests() if "USDC" in url or "UP" in url]


def test_shards_partition_symbols_without_overlap_or_gap(tmp_path, capsys):
    symbols = [f"S{index:02d}USDT" for index in range(37)]
    for count in (1, 2, 3, 16):
        shards = [v4_data.shard_symbols(symbols[::-1], index, count) for index in range(count)]
        flat = [symbol for shard in shards for symbol in shard]
        assert sorted(flat) == symbols and len(flat) == len(set(flat)), count
    for bad in ("3/3", "-1/2", "1/0", "01/2", "a/b", "1"):
        with pytest.raises(ValueError):
            v4_data.parse_shard(bad)

    # The fetch: three shards' manifests hold each candidate's archives exactly once.
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.discover()
    pipeline.fetch("spot_1d", 3)
    pieces = [json.loads(path.read_text()) for path in pipeline.manifest_files("spot_1d")]
    assert [piece["shard"] for piece in pieces] == ["0/3", "1/3", "2/3"]
    owners = [{entry["symbol"] for entry in piece["entries"]} for piece in pieces]
    assert sum(len(owner) for owner in owners) == len(set().union(*owners))
    assert set().union(*owners) == set(DAILY_QUOTE_VOLUMES)
    paths = [entry["path"] for piece in pieces for entry in piece["entries"]]
    assert len(paths) == len(set(paths)) == 2 * len(DAILY_QUOTE_VOLUMES)
    assert [piece["symbols"] for piece in pieces] == [
        sorted(DAILY_QUOTE_VOLUMES)[index::3] for index in range(3)
    ]
    pipeline.cli(
        "fetch", "--kind", "spot_1d", "--discovery", pipeline.discovery, "--shard", "3/3",
        "--cache", pipeline.cache, "--out", pipeline.manifests, expect=1,
    )  # fmt: skip
    # An hourly kind takes candidates.txt, never every candidate by default.
    pipeline.cli(
        "fetch", "--kind", "spot_1h", "--discovery", pipeline.discovery, "--shard", "0/1",
        "--cache", pipeline.cache, "--out", pipeline.manifests, expect=1,
    )  # fmt: skip
    assert "--symbols-file (candidates.txt) is required for spot_1h" in pipeline.err[-1]
    assert not pipeline.manifest_files("spot_1h")


def test_a_listed_month_the_host_does_not_have_is_recorded_absent(tmp_path, capsys):
    world = build_world()
    world.listed_only.add(archive_path("spot_1d", "BBBUSDT", "2023-12"))
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.discover()
    pipeline.fetch("spot_1d", 1)
    (piece,) = [json.loads(path.read_text()) for path in pipeline.manifest_files("spot_1d")]
    assert piece["absent"] == [{"symbol": "BBBUSDT", "month": "2023-12"}]
    assert ("BBBUSDT", "2023-12") not in {(e["symbol"], e["month"]) for e in piece["entries"]}
    assert "1 absent" in pipeline.out[-1]
    pipeline.select_candidates()  # entries and absent months together are the listed months


def test_select_refuses_an_incomplete_or_inconsistent_set_of_pieces(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.discover()
    pipeline.fetch("spot_1d", 2)
    first, second = pipeline.manifest_files("spot_1d")

    # A missing shard.
    pipeline.select_candidates([first], expect=1)
    assert "the spot_1d manifest pieces lack shard 1/2" in pipeline.err[-1]

    # Two shard counts.
    (tmp_path / "other").mkdir()
    other = Pipeline(tmp_path / "other", capsys, pipeline.world)
    other.config, other.discovery, other.cache = pipeline.config, pipeline.discovery, pipeline.cache
    other.fetch("spot_1d", 3)
    pipeline.select_candidates([first, *other.manifest_files("spot_1d")[1:]], expect=1)
    assert "the spot_1d pieces mix shard counts [2, 3]" in pipeline.err[-1]

    # A symbol missing a month.
    piece = json.loads(second.read_text())
    dropped = piece["entries"].pop()
    second.write_text(json.dumps(piece))
    pipeline.select_candidates(expect=1)
    message = pipeline.err[-1]
    assert f"{dropped['symbol']}'s spot_1d entries and absent months" in message
    assert f"missing ['{dropped['month']}']" in message
    assert not pipeline.candidates.exists()


def test_hourly_pieces_must_cover_every_symbol_ranked_in_a_top_20(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.discover()
    pipeline.fetch("spot_1d", 2)
    pipeline.select_candidates()
    ranked = pipeline.candidates.read_text().split()
    pipeline.candidates.write_text("".join(s + "\n" for s in ranked if s != "LATEUSDT"))
    for kind in HOURLY_KINDS:
        pipeline.fetch(kind, 2)
    pipeline.select_final(expect=1)
    assert "the spot_1h manifest pieces cover 5 symbols, not the 6" in pipeline.err[-1]
    assert "missing ['LATEUSDT']" in pipeline.err[-1]


def test_hourly_pieces_cover_the_candidates_stage_ranking_not_the_final_one(tmp_path, capsys):
    # No candidate passes the hourly check at 2024-02, so the final window opens at 2024-03,
    # a month after the candidates stage's. EEE ranks in a top 20 only at 2024-02 (a dead
    # market at 2024-03): it is in candidates.txt and the hourly pieces, but in no final
    # ranking. A complete set of pieces must still be accepted.
    pipeline = Pipeline(tmp_path, capsys, build_world(spot_january_days=20))
    pipeline.run()
    assert "EEEUSDT" in pipeline.candidates.read_text().split()
    universes = json.loads((pipeline.final / "universe.json").read_text())["universes"]
    assert [universe["month"] for universe in universes] == [END_MONTH]
    assert "EEEUSDT" not in [symbol for symbol, _, _ in universes[0]["ranked"]]
    assert manifest_months(pipeline.manifest_files("spot_1h"), "EEEUSDT") == [JAN, FEB]
    data = json.loads((pipeline.data / "data.json").read_text())
    assert data["universe_months"] == 1 and data["selected_symbols"] == 4


@pytest.mark.parametrize(
    "absent",
    [
        [{"symbol": ["BBBUSDT"], "month": "2024-01"}],  # an unhashable symbol
        [{"symbol": "BBBUSDT", "month": 202401}],  # a month that is not a string
        [{"symbol": "BBBUSDT", "month": "2024-13"}],  # not a month
        [{"symbol": "BBBUSDT", "month": "2024-04"}],  # after end_month
        [["BBBUSDT", "2024-01"]],  # not an object
        ["BBBUSDT"],
    ],
)
def test_a_malformed_absent_month_is_refused_with_a_clear_message(tmp_path, capsys, absent):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.discover()
    pipeline.fetch("spot_1d", 1)
    (path,) = pipeline.manifest_files("spot_1d")
    piece = json.loads(path.read_text())
    piece["absent"] = absent
    path.write_text(json.dumps(piece))
    pipeline.select_candidates(expect=1)
    assert pipeline.err[-1].startswith("v4_data select: refused: ")
    assert "absent" in pipeline.err[-1]


def test_a_tampered_cached_archive_is_refused_not_reused(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_hourly()
    path = archive_path("spot_1d", "AAAUSDT", JAN)
    cached = pipeline.cache.joinpath(*path.strip("/").split("/"))
    cached.write_bytes(cached.read_bytes() + b"\0")
    pipeline.world.requests.clear()
    pipeline.select_final(expect=1)
    assert f"{path}: the cached archive does not match its manifest pin" in pipeline.err[-1]
    assert pipeline.world.requests == []  # refused, neither re-used nor fetched again


def test_an_archive_missing_from_the_cache_is_fetched_again_by_its_pin(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_hourly()
    path = archive_path("spot_1d", "AAAUSDT", JAN)
    cached = pipeline.cache.joinpath(*path.strip("/").split("/"))
    original = cached.read_bytes()
    cached.unlink()
    pipeline.world.requests.clear()
    pipeline.select_final()
    # fetch_pinned: the archive alone, no .CHECKSUM (the manifest's pin is the authority).
    assert pipeline.world.requests == [archives.ARCHIVE_URL + path]
    assert cached.read_bytes() == original


def test_pack_decodes_each_hourly_archive_once(tmp_path, capsys, monkeypatch):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    decoded: list[tuple[str, str, bool]] = []
    read_hourly = inputs.read_hourly

    def counting(content, symbol, month, *, futures):
        decoded.append((symbol, month, futures))
        return read_hourly(content, symbol, month, futures=futures)

    monkeypatch.setattr(inputs, "read_hourly", counting)
    pipeline.pack()
    assert len(decoded) == len(set(decoded))  # the selected symbols' spot series are reused
    spot = {(symbol, month) for symbol, month, futures in decoded if not futures}
    assert len(spot) == 11  # every candidate's spot hourly archive, once
    assert ("EEEUSDT", JAN, True) in decoded and ("CCCUSDT", JAN, True) not in decoded
    assert ("1000FFFUSDT", FEB, True) in decoded  # a perpetual is read under its own symbol


def test_pack_refuses_universes_that_differ_from_select_finals(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    universe_path = pipeline.final / "universe.json"
    universe = json.loads(universe_path.read_text())
    universe["universes"][-1]["selected"] = ["AAAUSDT", "BBBUSDT"]
    universe_path.write_text(json.dumps(universe))
    pipeline.pack(expect=1)
    assert "the universes recomputed here differ" in pipeline.err[-1]
    assert not pipeline.data.exists() or not any(pipeline.data.iterdir())


def test_no_output_prints_bar_values(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.run()
    out, err = pipeline.stdout(), "".join(pipeline.err)
    assert out.strip()
    for value in BAR_VALUES:
        assert value not in out and value not in err, value
    pins = re.findall(r"\b[0-9a-f]{64}\b", out)
    data = json.loads((pipeline.data / "data.json").read_text())
    assert {pack["sha256"] for pack in data["packs"].values()} <= set(pins)
    # Counts and pins only: no number with a fraction, and nothing that is not a word, a
    # count, a pin or punctuation.
    without_pins = re.sub(r"\b[0-9a-f]{64}\b", "PIN", out)
    assert not re.search(r"[0-9]\.[0-9]", without_pins)
    for line in without_pins.splitlines():
        assert re.fullmatch(r"[A-Za-z0-9 _:,/()|.-]+", line), line


def test_hourly_fetch_covers_each_candidates_whole_history(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_hourly()
    pipeline.select_final()

    candidates = pipeline.candidates.read_text().split()
    assert candidates == ["AAAUSDT", "BBBUSDT", "CCCUSDT", "EEEUSDT", "FFFUSDT", "LATEUSDT"]
    universes = json.loads((pipeline.final / "universe.json").read_text())["universes"]
    first, last = universes
    assert ["LATEUSDT", "history"] in first["excluded"]
    assert "LATEUSDT" not in [symbol for symbol, _, _ in first["ranked"]]
    assert "LATEUSDT" in [symbol for symbol, _, _ in last["ranked"]]
    # Ranked only in the last month, it still gets every discovered hourly month: January,
    # before it first ranks, included.
    discovered = json.loads(pipeline.discovery.read_text())["months"]
    for kind in HOURLY_KINDS:
        assert (
            manifest_months(pipeline.manifest_files(kind), "LATEUSDT")
            == (discovered[kind]["LATEUSDT"])
        ), kind
    assert discovered["spot_1h"]["LATEUSDT"] == [JAN, FEB]
    assert discovered["futures_1h"]["LATEUSDT"] == [JAN, FEB]
    assert discovered["funding"]["LATEUSDT"] == [FEB]
    # A symbol never ranked gets no hourly archive at all.
    assert all(
        "USDC" not in url and "AAAUP" not in url for url in pipeline.world.archive_requests()
    )


PERPETUALS = {
    "AAAUSDT": {"symbol": "AAAUSDT", "multiplier": 1},
    "BBBUSDT": {"symbol": "BBBUSDT", "multiplier": 1},
    "EEEUSDT": {"symbol": "EEEUSDT", "multiplier": 1},
    "FFFUSDT": {"symbol": "1000FFFUSDT", "multiplier": 1000},
    "LATEUSDT": {"symbol": "LATEUSDT", "multiplier": 1},
}


def test_cli_fetches_futures_and_funding_under_the_perpetual_symbol(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_hourly()

    # discover: each candidate's perpetual (CCC has none), and the futures and funding months
    # listed under the perpetual's symbol.
    discovery = json.loads(pipeline.discovery.read_text())
    assert discovery["perpetuals"] == PERPETUALS
    perpetuals = {"AAAUSDT", "BBBUSDT", "EEEUSDT", "1000FFFUSDT", "LATEUSDT"}
    for kind in ("futures_1h", "funding"):
        assert set(discovery["months"][kind]) == perpetuals, kind
        assert discovery["months"][kind]["1000FFFUSDT"] == [JAN, FEB], kind
    assert discovery["months"]["spot_1h"]["FFFUSDT"] == [JAN, FEB]
    assert "5 candidates with a perpetual, 1 of them a multiplier contract" in pipeline.out[0]

    # fetch: under the perpetual's name only. Nothing was listed or fetched for a futures or
    # funding archive under FFF's own name, nor for CCC, which has no perpetual.
    futures_urls = [url for url in pipeline.world.requests if "/futures/" in url]
    assert not [url for url in futures_urls if re.search(r"/(FFF|CCC)USDT[/-]", url)]
    fetched = {url for url in futures_urls if url.startswith(ARCHIVE) and "FFF" in url}
    assert fetched == {
        ARCHIVE + archive_path(kind, "1000FFFUSDT", month) + suffix
        for kind in ("futures_1h", "funding")
        for month in (JAN, FEB)
        for suffix in ("", ".CHECKSUM")
    }
    candidates = pipeline.candidates.read_text().split()
    for kind in ("futures_1h", "funding"):
        paths = pipeline.manifest_files(kind)
        pieces = [json.loads(path.read_text()) for path in paths]
        # The shards partition the coins, as for every kind; the entries are the perpetual's.
        assert [piece["symbols"] for piece in pieces] == [candidates[0::2], candidates[1::2]]
        assert manifest_months(paths, "1000FFFUSDT") == [JAN, FEB]
        assert manifest_months(paths, "FFFUSDT") == []
        path = archive_path(kind, "1000FFFUSDT", JAN)
        assert pipeline.cache.joinpath(*path.strip("/").split("/")).is_file()


def test_fetch_prints_how_many_of_the_shards_symbols_have_a_perpetual(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_hourly()
    lines = [
        re.sub(r"\([0-9]+ bytes\)", "(N bytes)", line)
        for out in pipeline.out
        for line in out.splitlines()
        if line.startswith("fetch ")
    ]
    # Shard 0 of 2 is AAA, CCC and FFF: AAA's perpetual and FFF's (1000FFFUSDT), CCC none.
    # Shard 1 is BBB, EEE and LATE, each with a perpetual. Counts only; the spot kinds as before.
    tail = "archives (N bytes), 0 absent"
    assert [line for line in lines if "futures_1h" in line or "funding" in line] == [
        f"fetch futures_1h shard 0/2: 3 symbols (2 with a perpetual), 4 {tail}",
        f"fetch futures_1h shard 1/2: 3 symbols (3 with a perpetual), 5 {tail}",
        f"fetch funding shard 0/2: 3 symbols (2 with a perpetual), 4 {tail}",
        f"fetch funding shard 1/2: 3 symbols (3 with a perpetual), 3 {tail}",
    ]
    assert f"fetch spot_1h shard 0/2: 3 symbols, 5 {tail}" in lines


def test_a_multiplier_perpetual_without_a_readable_bar_is_left_out_with_its_entry(tmp_path, capsys):
    # Ruling P23 for 1000FFFUSDT: both its futures archives are unreadable, so the hourly pack
    # holds no futures series for it, and so no rules, masks, funding, funding months or
    # perpetuals entry; FFFUSDT's spot series stays.
    world = build_world()
    for month in (JAN, FEB):
        world.files[archive_path("futures_1h", "1000FFFUSDT", month)] = GARBAGE
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    hourly = read_canonical(pipeline.data / HOURLY_PACK_FILE, data["packs"]["hourly"]["sha256"])
    assert "FFFUSDT" in hourly["spot"] and "FFFUSDT|spot" in hourly["rules"]
    assert "1000FFFUSDT" not in hourly["futures"] and "1000FFFUSDT" not in hourly["funding"]
    keyed = [*hourly["rules"], *hourly["masks"], *hourly["funding_months"]]
    assert not [key for key in keyed if key.startswith("1000FFFUSDT|")]
    assert sorted(hourly["perpetuals"]) == ["AAAUSDT", "BBBUSDT", "LATEUSDT"]
    # Its futures archives were read (they decided it), its funding files never were.
    read = {(entry["kind"], entry["symbol"]) for entry in hourly["manifest"]}
    assert ("futures_1h", "1000FFFUSDT") in read and ("funding", "1000FFFUSDT") not in read
    assert (data["perpetuals"], data["multiplier_perpetuals"]) == (3, 0)
    assert "3 with a perpetual, 0 of them multiplier contracts" in pipeline.out[-1]


def test_cli_packs_a_multiplier_perpetual_under_its_own_symbol(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    hourly = read_canonical(pipeline.data / HOURLY_PACK_FILE, data["packs"]["hourly"]["sha256"])
    assert hourly["perpetuals"]["FFFUSDT"] == {"symbol": "1000FFFUSDT", "multiplier": 1000}
    assert "FFFUSDT" in hourly["spot"] and "FFFUSDT" not in hourly["futures"]
    assert len(hourly["futures"]["1000FFFUSDT"]) == 744 + 696
    assert hourly["masks"]["1000FFFUSDT|futures"] == {"masked": [], "unreadable": {}}
    assert len(hourly["funding"]["1000FFFUSDT"]) == 93 + 87
    # The present-day filters are looked up under the perpetual's own name, which the futures
    # snapshot lists; the coin's spot filters are inferred (the spot snapshot has only AAA).
    assert hourly["rules"]["1000FFFUSDT|futures"]["source"] == "present_day"
    assert hourly["rules"]["1000FFFUSDT|futures"]["tick"] == "0.10"
    assert hourly["rules"]["FFFUSDT|spot"]["source"] == "inferred"
    assert (data["perpetuals"], data["multiplier_perpetuals"]) == (4, 1)
    assert "4 with a perpetual, 1 of them a multiplier contract" in pipeline.out[-1]


def piece_holding(paths: list[Path], symbol: str) -> tuple[Path, dict]:
    """The one manifest piece with an entry for ``symbol``, and its document."""
    (found,) = [
        (path, piece)
        for path in paths
        for piece in [json.loads(path.read_text())]
        if any(entry["symbol"] == symbol for entry in piece["entries"])
    ]
    return found


def test_futures_pieces_must_hold_each_perpetuals_discovered_months(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    path, piece = piece_holding(pipeline.manifest_files("futures_1h"), "1000FFFUSDT")
    (february,) = [
        entry
        for entry in piece["entries"]
        if (entry["symbol"], entry["month"]) == ("1000FFFUSDT", FEB)
    ]

    # The perpetual's February archive left out.
    piece["entries"].remove(february)
    path.write_text(json.dumps(piece))
    pipeline.pack(expect=1)
    assert (
        "1000FFFUSDT's futures_1h entries and absent months are not its discovered months: "
        "missing ['2024-02']"
    ) in pipeline.err[-1]

    # The month recorded absent under the coin's own name, or an entry for an archive under it.
    path.write_text(json.dumps(piece | {"absent": [{"symbol": "FFFUSDT", "month": FEB}]}))
    pipeline.pack(expect=1)
    assert "absent 'FFFUSDT' is outside the piece's symbols" in pipeline.err[-1]
    own_name = archive_path("futures_1h", "FFFUSDT", FEB)
    wrong = february | {"symbol": "FFFUSDT", "path": own_name}
    path.write_text(json.dumps(piece | {"entries": [*piece["entries"], wrong]}))
    pipeline.pack(expect=1)
    assert f"{own_name!r} is outside the piece's symbols" in pipeline.err[-1]
    assert not pipeline.data.exists() or not any(pipeline.data.iterdir())

    # Recorded absent under the perpetual's own name, the month is accounted for.
    path.write_text(json.dumps(piece | {"absent": [{"symbol": "1000FFFUSDT", "month": FEB}]}))
    pipeline.pack()


def move_funding_months_to_the_coin(document: dict) -> None:
    funding = document["months"]["funding"]
    funding["FFFUSDT"] = funding.pop("1000FFFUSDT")


def share_fffs_perpetual(document: dict) -> None:
    """A hand-made candidate 1000FFFUSDT whose plain perpetual is FFFUSDT's x1000 one."""
    document["symbols"] = sorted([*document["symbols"], "1000FFFUSDT"])
    document["candidates"] = sorted([*document["candidates"], "1000FFFUSDT"])
    for kind in ("spot_1d", "spot_1h"):
        document["months"][kind]["1000FFFUSDT"] = []
    document["perpetuals"]["1000FFFUSDT"] = {"symbol": "1000FFFUSDT", "multiplier": 1}


@pytest.mark.parametrize(
    ("change", "why"),
    [
        (
            lambda d: d["perpetuals"]["FFFUSDT"].update(multiplier=1),
            "not FFFUSDT's perpetual name for multiplier 1",
        ),
        (
            lambda d: d["perpetuals"]["FFFUSDT"].update(symbol="1MFFFUSDT"),
            "not FFFUSDT's perpetual name for multiplier 1000",
        ),
        (
            lambda d: d["perpetuals"].update(CCCUSDT={"symbol": "AAAUSDT", "multiplier": 1}),
            "not CCCUSDT's perpetual name",
        ),
        (
            lambda d: d["perpetuals"].update(USDCUSDT={"symbol": "USDCUSDT", "multiplier": 1}),
            "perpetuals must map candidates",
        ),
        (lambda d: d.pop("perpetuals"), "perpetuals must map candidates"),
        (
            move_funding_months_to_the_coin,
            r"months\[funding\] must name exactly the candidates' perpetuals",
        ),
        (
            share_fffs_perpetual,
            "1000FFFUSDT is the perpetual of both 1000FFFUSDT and FFFUSDT",
        ),
    ],
)
def test_a_discovery_whose_perpetuals_do_not_hold_is_refused(tmp_path, capsys, change, why):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.discover()
    document = json.loads(pipeline.discovery.read_text())
    change(document)
    pipeline.discovery.write_text(json.dumps(document))
    pipeline.cli(
        "fetch", "--kind", "spot_1d", "--discovery", pipeline.discovery, "--shard", "0/1",
        "--cache", pipeline.cache, "--out", pipeline.manifests, expect=1,
    )  # fmt: skip
    assert re.search(why, pipeline.err[-1]), pipeline.err[-1]


def test_discover_refuses_two_coins_that_share_a_perpetual(tmp_path, capsys):
    # FFFUSDT's perpetual is 1000FFFUSDT (x1000); a spot coin named 1000FFFUSDT would have the
    # same perpetual as its own plain one (x1). Neither is chosen: that needs a ruling.
    world = build_world()
    world.spot_dirs.append("1000FFFUSDT")
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.cli("discover", "--out", pipeline.discovery.parent, expect=1)
    assert "1000FFFUSDT is the perpetual of both 1000FFFUSDT and FFFUSDT" in pipeline.err[-1]
    assert not pipeline.discovery.exists()


def test_final_selection_skips_a_candidate_without_recent_hourly_bars(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_hourly()
    pipeline.select_final()

    assert "CCCUSDT" in pipeline.candidates.read_text().split()
    selected = (pipeline.final / "selected.txt").read_text().split()
    assert selected == ["AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT", "LATEUSDT"]
    universe = json.loads((pipeline.final / "universe.json").read_text())
    assert universe["format"] == "v4-universe/1" and universe["end_month"] == END_MONTH
    for month in universe["universes"]:
        assert "CCCUSDT" in [symbol for symbol, _, _ in month["ranked"]]
        assert ["CCCUSDT", "no_recent_hourly"] in month["excluded"]
        assert "CCCUSDT" not in month["selected"]


def test_pack_refuses_a_manifest_entry_after_end_month_before_any_request(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.discover()
    pipeline.world.requests.clear()

    def entry(month: str) -> dict:
        path = archive_path("spot_1d", "AAAUSDT", month)
        return dict(
            kind="spot_1d", symbol="AAAUSDT", month=month, path=path, sha256="0" * 64, bytes=1
        )

    # The first entry is in the window and absent from the cache: reading it would need a
    # request. The second is after end_month. Nothing may be requested or read.
    pipeline.manifests.mkdir(parents=True)
    piece = {
        "format": "v4-manifest/1",
        "kind": "spot_1d",
        "shard": "0/1",
        "symbols": ["AAAUSDT"],
        "entries": [entry(JAN), entry("2024-04")],
        "absent": [],
    }
    (pipeline.manifests / "manifest-spot_1d-0.json").write_text(json.dumps(piece))
    pipeline.pack(expect=1)

    assert pipeline.world.requests == []
    assert "2024-04 is after end_month 2024-03" in pipeline.err[-1]
    assert not pipeline.data.exists() or not any(pipeline.data.iterdir())


def test_pack_stops_for_a_split_ruling_when_a_pack_is_too_large(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(v4_data, "MAX_PACK_JSON_BYTES", 1000)
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    pipeline.pack(expect=1)
    assert "ruling on splitting" in pipeline.err[-1]
    assert re.search(r"daily pack: [0-9]+ bytes of canonical JSON", pipeline.out[-1])
    assert not (pipeline.data / "data.json").exists()


def test_pack_refuses_a_filter_snapshot_that_does_not_match_its_pin(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    snapshot = tmp_path / "spot-snapshot.json"
    snapshot.write_bytes(snapshot.read_bytes() + b" ")
    pipeline.pack(expect=1)
    assert "spot filter snapshot" in pipeline.err[-1] and "pinned" in pipeline.err[-1]
    assert not pipeline.data.exists() or not any(pipeline.data.iterdir())


def test_a_listed_symbol_whose_rules_are_unusable_is_a_hard_stop(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.config = write_config(tmp_path, spot=spot_entry("AAAUSDT", quote="BTC"))
    pipeline.until_final()
    pipeline.pack(expect=1)
    assert "AAAUSDT on spot" in pipeline.err[-1] and "ruling P20" in pipeline.err[-1]
    assert not (pipeline.data / "data.json").exists()


def test_security_names_the_listing_host_beside_the_archive_host():
    policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    block = policy[
        policy.index("<!-- allowed-hosts:begin") : policy.index("<!-- allowed-hosts:end")
    ]
    hosts = re.findall(r"^\s*- `([a-z0-9.-]+)`", block, re.M)
    archive = hosts.index("data.binance.vision")
    assert hosts[archive + 1] == "s3-ap-northeast-1.amazonaws.com"
    line = next(line for line in block.splitlines() if "s3-ap-northeast-1" in line)
    assert "listing only" in block[block.index(line) :]


# --- the workflow ----------------------------------------------------------------------------


def workflow() -> dict:
    # PyYAML follows YAML 1.1, which reads the bare key `on` as the boolean True.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps_using(job: dict, action: str) -> list[dict]:
    return [step for step in job["steps"] if step.get("uses", "").startswith(action + "@")]


def test_workflow_has_the_expected_jobs_and_no_cache_of_results():
    document = workflow()
    assert list(document[True]) == ["workflow_dispatch"]
    stage = document[True]["workflow_dispatch"]["inputs"]["stage"]
    assert stage["type"] == "choice" and stage["options"] == ["discover", "full"]
    assert document["permissions"] == {"contents": "read"}

    jobs = document["jobs"]
    assert list(jobs) == [
        "discover",
        "fetch-daily",
        "select-candidates",
        "fetch-hourly",
        "select-final",
        "pack",
    ]
    assert "if" not in jobs["discover"]  # stage discover runs it alone
    for name, job in jobs.items():
        assert job["runs-on"] == "ubuntu-latest" and job["timeout-minutes"] == 300, name
        if name != "discover":
            assert job["if"].replace(" ", "") == "${{inputs.stage=='full'}}", name
            assert "discover" in job["needs"], name
    assert jobs["select-candidates"]["needs"] == ["discover", "fetch-daily"]
    assert jobs["fetch-hourly"]["needs"] == ["discover", "select-candidates"]
    assert jobs["select-final"]["needs"] == ["discover", "fetch-daily", "fetch-hourly"]
    assert jobs["pack"]["needs"] == ["discover", "fetch-daily", "fetch-hourly", "select-final"]

    daily, hourly = jobs["fetch-daily"], jobs["fetch-hourly"]
    assert daily["strategy"]["matrix"] == {"shard": list(range(16))}
    assert daily["env"]["SHARDS"] == "16"
    assert hourly["strategy"]["matrix"] == {"kind": list(HOURLY_KINDS), "shard": list(range(8))}
    assert hourly["env"]["SHARDS"] == "8"

    commands = {
        name: "\n".join(step.get("run", "") for step in job["steps"]) for name, job in jobs.items()
    }
    assert "v4_data.py discover" in commands["discover"]
    assert "--kind spot_1d" in commands["fetch-daily"]
    assert "--stage candidates" in commands["select-candidates"]
    assert '--kind "$KIND"' in commands["fetch-hourly"]
    assert "--symbols-file v4/candidates/candidates.txt" in commands["fetch-hourly"]
    assert "--stage final" in commands["select-final"]
    assert (
        "--hourly-manifests v4/fetched/manifests/manifest-spot_1h-*.json"
        in commands["select-final"]
    )
    assert "v4_data.py pack" in commands["pack"]
    assert "--universe v4/final/universe.json" in commands["pack"]

    # What each job downloads, and where: the folders the commands above read.
    discovery = ("v4-discover", "v4/discover", False)
    daily_archives = ("v4-daily-*", "v4/fetched", True)
    downloads = {
        name: [
            (step["with"].get("pattern", step["with"].get("name")), step["with"]["path"],
             step["with"].get("merge-multiple", False))
            for step in steps_using(job, "actions/download-artifact")
        ]
        for name, job in jobs.items()
    }  # fmt: skip
    assert downloads == {
        "discover": [],
        "fetch-daily": [discovery],
        "select-candidates": [discovery, daily_archives],
        "fetch-hourly": [discovery, ("v4-candidates", "v4/candidates", False)],
        "select-final": [discovery, daily_archives, ("v4-hourly-spot_1h-*", "v4/fetched", True)],
        "pack": [
            discovery,
            daily_archives,
            ("v4-hourly-*", "v4/fetched", True),
            ("v4-final", "v4/final", False),
        ],
    }

    guard = "python scripts/v4_data_month_guard.py --config config/v4_data.json --root v4"
    uploads: dict[str, dict] = {}
    for name, job in jobs.items():
        for step in job["steps"]:
            uses = step.get("uses")
            if uses:  # every action pinned by its full commit SHA
                assert re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", uses), uses
            assert not (uses or "").startswith("actions/cache@"), name  # nothing cached
        for step in steps_using(job, "actions/setup-python"):
            assert step["with"]["python-version"] == "3.12"
            assert step["with"].get("cache") in (None, "pip")  # pip's wheels only
        for step in steps_using(job, "actions/checkout"):
            assert step["with"]["persist-credentials"] is False
        names = [step.get("name", "") for step in job["steps"]]
        scan = names.index("Refuse any file named for a month after end_month")
        assert job["steps"][scan]["run"].strip() == guard, name  # the one guard script
        assert sum(guard in step.get("run", "") for step in job["steps"]) == 1, name
        for index, step in enumerate(job["steps"]):
            if step.get("uses", "").startswith("actions/upload-artifact@"):
                assert index > scan, name  # the scan runs after every fetch and before uploads
                assert step["with"]["retention-days"] == 1, name  # owner rule, ruling P25
                assert step["with"]["if-no-files-found"] == "error", name
                assert step["with"]["overwrite"] is True, name  # re-running all jobs works
                uploads[step["with"]["name"]] = step["with"]
            if "v4_data.py" in step.get("run", ""):
                assert index < scan, name
    assert set(uploads) == {
        "v4-discover",
        "v4-daily-${{ matrix.shard }}",
        "v4-candidates",
        "v4-hourly-${{ matrix.kind }}-${{ matrix.shard }}",
        "v4-final",
        "v4-data",
    }
    assert uploads["v4-data"]["path"].rstrip("/") == "v4/data"
