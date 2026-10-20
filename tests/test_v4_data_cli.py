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
* 牛来USDT: a real Binance listing whose name the archive paths cannot address, so it is
  excluded as "unsupported_name", recorded and counted, and never fetched (ruling P33);
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
from collections import Counter
from datetime import UTC, datetime, timedelta, timezone
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
DAILY_PACK_FILE = "daily.pack.json.gz"
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
SPOT_DIRS += ("LATEUSDT", "USDCUSDT", "牛来USDT")
UNSUPPORTED = "牛来USDT"
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
    directories are those of the world's futures archives. A path in ``refusals`` raises its
    exception instead of answering, and one in ``no_checksum`` has no ``.CHECKSUM`` (404).
    """

    def __init__(self, files: dict[str, bytes]):
        self.files = files  # archive path -> bytes
        self.listed_only: set[str] = set()
        self.spot_dirs = list(SPOT_DIRS)
        self.refusals: dict[str, Exception] = {}
        self.no_checksum: set[str] = set()
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
        if path in self.refusals:
            raise self.refusals[path]
        if path.endswith(".CHECKSUM"):
            if path.removesuffix(".CHECKSUM") in self.no_checksum:
                return None
            content = self.files.get(path.removesuffix(".CHECKSUM"))
            name = path.removesuffix(".CHECKSUM").rsplit("/", 1)[1]
            return None if content is None else f"{sha(content)}  {name}\n".encode("ascii")
        return self.files.get(path)

    def archive_requests(self) -> list[str]:
        return [url for url in self.requests if url.startswith(ARCHIVE)]


def zipped(path: str, text: str) -> bytes:
    """A zip archive holding ``text`` as the CSV member Binance names after ``path``."""
    member = path.rsplit("/", 1)[1].removesuffix(".zip") + ".csv"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, text)
    return stream.getvalue()


def build_world(*, spot_january_days: int = 31) -> FakeBinance:
    """The world above. With ``spot_january_days`` below 25, AAA's, BBB's and EEE's January
    spot hourly bars stop more than 168 hours before 2024-02-01, so no candidate passes that
    month's hourly check."""
    files: dict[str, bytes] = {}

    def put(kind: str, symbol: str, month: str, text: str | None = None) -> None:
        path = archive_path(kind, symbol, month)
        files[path] = GARBAGE if text is None else zipped(path, text)

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
        self.clock = lambda: datetime(2024, 4, 1, tzinfo=UTC)  # 2024-03 is complete

    def cli(self, *argv: object, expect: int = 0) -> None:
        code = v4_data.main(
            ["--config", str(self.config), *map(str, argv)],
            transport=self.world,
            sleep=lambda seconds: None,
            clock=self.clock,
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


def hourly_view(data_dir: Path) -> dict:
    """Every coin pack, each read with its pin from the index read with its pin from data.json,
    gathered into one view keyed as the assertions want: ``spot`` by coin; ``futures``,
    ``funding`` by perpetual; ``masks`` and ``rules`` by "SYMBOL|venue"; ``funding_months`` by
    "PERPETUAL|YYYY-MM"; ``perpetuals`` and ``coins`` from the index; ``manifest`` every coin
    pack's; ``packs`` coin -> its pack."""
    data = json.loads((data_dir / "data.json").read_text())
    record = data["packs"]["hourly_index"]
    index = read_canonical(data_dir / record["file"], record["sha256"])
    view: dict = {key: {} for key in ("spot", "futures", "masks", "funding", "rules", "packs")}
    view |= {"funding_months": {}, "manifest": [], "perpetuals": index["perpetuals"]}
    view["coins"] = index["coins"]
    for coin, pinned in index["coins"].items():
        pack = read_canonical(data_dir / pinned["file"], pinned["sha256"])
        assert pack["coin"] == coin and pack["perpetual"] == index["perpetuals"].get(coin)
        view["packs"][coin] = pack
        view["manifest"] += pack["manifest"]
        names = {"spot": coin}
        if pack["perpetual"] is not None:
            name = names["futures"] = pack["perpetual"]["symbol"]
            view["futures"][name], view["funding"][name] = pack["futures"], pack["funding"]
            view["funding_months"] |= {f"{name}|{m}": s for m, s in pack["funding_months"].items()}
        else:
            assert pack["futures"] == pack["funding"] == [] and pack["funding_months"] == {}
        view["spot"][coin] = pack["spot"]
        for venue, symbol in names.items():
            view["masks"][f"{symbol}|{venue}"] = pack["masks"][venue]
            view["rules"][f"{symbol}|{venue}"] = pack["rules"][venue]
        assert set(pack["masks"]) == set(pack["rules"]) == set(names)
    return view


# --- the CLI ---------------------------------------------------------------------------------


def test_end_to_end_on_a_fake_world_produces_both_packs_and_pins(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    assert data["config_sha256"] == sha(pipeline.config.read_bytes())
    assert data["end_month"] == END_MONTH
    daily_record, index_record = data["packs"]["daily"], data["packs"]["hourly_index"]
    daily = read_canonical(pipeline.data / daily_record["file"], daily_record["sha256"])
    index = read_canonical(pipeline.data / index_record["file"], index_record["sha256"])
    hourly = hourly_view(pipeline.data)
    with gzip.open(pipeline.data / index_record["file"]) as stream:
        assert index_record["json_bytes"] == len(stream.read())
    for document in (daily, index, *hourly["packs"].values()):
        assert document["config_sha256"] == data["config_sha256"]
        assert document["end_month"] == END_MONTH

    # The daily pack: every candidate's daily bars, the static exclusions, the final universes.
    assert sorted(daily["daily"]) == sorted(DAILY_QUOTE_VOLUMES)
    assert daily["exclusions"] == {
        "AAAUPUSDT": "leveraged",
        "USDCUSDT": "stablecoin",
        UNSUPPORTED: "unsupported_name",  # ruling P33
    }
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
    assert daily["masks"]["AAAUSDT"] == {"masked": [REPAIRED_DAY], "unreadable": {}, "absent": []}
    assert daily["masks"]["BBBUSDT"] == {"masked": [], "unreadable": {}, "absent": []}
    assert len(daily["daily"]["AAAUSDT"]) == 31 + 29
    window_bars = {symbol: bars for symbol, _, bars in universes["2024-02"]["ranked"]}
    assert (window_bars["AAAUSDT"], window_bars["BBBUSDT"]) == (29, 30)
    assert {entry["kind"] for entry in daily["manifest"]} == {"spot_1d", "spot_1h"}

    # The coin packs: whole histories of the symbols ever selected, one pack each, each futures
    # series under its perpetual's own symbol.
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
    assert hourly["masks"]["AAAUSDT|spot"] == {
        "masked": [duplicate],
        "unreadable": {},
        "absent": [],
    }
    assert hourly["masks"]["BBBUSDT|futures"] == {"masked": [], "unreadable": {}, "absent": []}
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


def test_the_packs_record_each_series_absent_months(tmp_path, capsys):
    # December 2023 is listed for BBB's daily archives, AAA's spot hourly ones and 1000FFFUSDT's
    # futures ones, but the host answers 404: each series records it as absent, carried from
    # the manifest pieces, beside its masks.
    world = build_world()
    for kind, symbol in (
        ("spot_1d", "BBBUSDT"),
        ("spot_1h", "AAAUSDT"),
        ("futures_1h", "1000FFFUSDT"),
    ):
        world.listed_only.add(archive_path(kind, symbol, "2023-12"))
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    daily = read_canonical(pipeline.data / DAILY_PACK_FILE, data["packs"]["daily"]["sha256"])
    hourly = hourly_view(pipeline.data)
    assert daily["masks"]["BBBUSDT"]["absent"] == ["2023-12"]
    assert hourly["masks"]["AAAUSDT|spot"]["absent"] == ["2023-12"]
    assert hourly["masks"]["1000FFFUSDT|futures"]["absent"] == ["2023-12"]
    others = [
        m
        for key, m in hourly["masks"].items()
        if key not in ("AAAUSDT|spot", "1000FFFUSDT|futures")
    ]
    assert all(mask["absent"] == [] for mask in others)
    assert daily["masks"]["AAAUSDT"]["absent"] == []


def test_a_fetch_shard_reports_every_failing_archive_and_writes_no_piece(tmp_path, capsys):
    # Two anomalies in one shard: AAA's January archive has no checksum file, and LATE's
    # February archive answers HTTP 403 (a 4xx, never retried). The shard goes on past the
    # first, then refuses with both, and writes no manifest piece (it still fails closed).
    world = build_world()
    missing, forbidden = (
        archive_path("spot_1d", "AAAUSDT", JAN),
        archive_path("spot_1d", "LATEUSDT", FEB),
    )
    world.no_checksum.add(missing)
    world.refusals[forbidden] = ValueError("public data returned HTTP 403")
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.discover()
    pipeline.cli(
        "fetch", "--kind", "spot_1d", "--discovery", pipeline.discovery, "--shard", "0/1",
        "--cache", pipeline.cache, "--out", pipeline.manifests, expect=1,
    )  # fmt: skip

    err = pipeline.err[-1]
    assert "fetch spot_1d shard 0/1: 2 archives failed, so no manifest piece is written" in err
    assert f"AAAUSDT spot_1d {JAN}: {missing}: the archive exists but its checksum" in err
    assert f"LATEUSDT spot_1d {FEB}: public data returned HTTP 403" in err
    assert not pipeline.manifest_files("spot_1d")
    assert world.requests.count(ARCHIVE + forbidden) == 1  # not retried
    # Every archive of the shard was tried, before and after the failures.
    tried = {url for url in world.archive_requests() if not url.endswith(".CHECKSUM")}
    assert tried == {
        ARCHIVE + archive_path("spot_1d", symbol, month)
        for symbol in DAILY_QUOTE_VOLUMES
        for month in (JAN, FEB)
    }


def test_a_fetch_shard_stops_at_the_failure_cap(tmp_path, capsys, monkeypatch):
    # A systemic failure (every archive refused) stops at the cap instead of trying them all.
    monkeypatch.setattr(v4_data, "MAX_FETCH_FAILURES", 3)
    world = build_world()
    for symbol in DAILY_QUOTE_VOLUMES:
        for month in (JAN, FEB):
            world.refusals[archive_path("spot_1d", symbol, month)] = ValueError(
                "public data returned HTTP 403"
            )
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.discover()
    pipeline.cli(
        "fetch", "--kind", "spot_1d", "--discovery", pipeline.discovery, "--shard", "0/1",
        "--cache", pipeline.cache, "--out", pipeline.manifests, expect=1,
    )  # fmt: skip
    assert "3 archives failed (stopped at 3 failures), so no manifest piece" in pipeline.err[-1]
    assert len(world.archive_requests()) == 3 and not pipeline.manifest_files("spot_1d")


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


def test_pack_decodes_each_hourly_archive_at_most_twice(tmp_path, capsys, monkeypatch):
    # Ruling P32: no series is kept from one coin to the next, so a selected coin's spot
    # archives are decoded for the usable hours and again for its coin pack, and a perpetual's
    # for the pre-flight count and again for its coin pack. A candidate never selected (CCC)
    # has its spot archives decoded once, for the usable hours.
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    decoded: list[tuple[str, str, bool]] = []
    read_hourly = inputs.read_hourly

    def counting(content, symbol, month, *, futures):
        decoded.append((symbol, month, futures))
        return read_hourly(content, symbol, month, futures=futures)

    monkeypatch.setattr(inputs, "read_hourly", counting)
    pipeline.pack()
    selected = {"AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT", "LATEUSDT"}
    for (symbol, month, futures), times in Counter(decoded).items():
        assert times == (2 if futures or symbol in selected else 1), (symbol, month, futures)
    spot = {(symbol, month) for symbol, month, futures in decoded if not futures}
    assert len(spot) == 11  # every candidate's spot hourly archive
    assert ("EEEUSDT", JAN, True) in decoded and ("CCCUSDT", JAN, True) not in decoded
    assert ("1000FFFUSDT", FEB, True) in decoded  # a perpetual is read under its own symbol


def test_pack_writes_one_pack_per_coin_and_an_index_that_pins_them(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    assert sorted(data["packs"]) == ["daily", "hourly_index"]
    record = data["packs"]["hourly_index"]
    index = read_canonical(pipeline.data / record["file"], record["sha256"])
    assert index["format"] == "v4-hourly-index/1" and record["file"] == "hourly-index.json.gz"
    selected = ["AAAUSDT", "BBBUSDT", "EEEUSDT", "FFFUSDT", "LATEUSDT"]
    files = sorted(path.name for path in pipeline.data.glob("v4-coin-*.json.gz"))
    assert files == [f"v4-coin-{coin}.json.gz" for coin in selected]  # one file per coin
    assert sorted(index["coins"]) == selected
    sizes = []
    for coin, pinned in index["coins"].items():
        path = pipeline.data / pinned["file"]
        pack = read_canonical(path, pinned["sha256"])  # its index pin is its pin
        with gzip.open(path) as stream:
            content = stream.read()
        assert sha(content) == pinned["sha256"] and len(content) == pinned["json_bytes"]
        assert pack["format"] == "v4-coin-pack/1" and pack["coin"] == coin
        assert {e["symbol"] for e in pack["manifest"] if e["kind"] == "spot_1h"} == {coin}
        sizes.append(pinned["json_bytes"])
    assert index["perpetuals"] == {coin: PERPETUALS[coin] for coin in selected if coin != "EEEUSDT"}
    # The pre-flight before the coin packs, and the largest coin pack after them.
    view = hourly_view(pipeline.data)
    rows = sum(len(view["spot"][c]) for c in selected) + sum(map(len, view["futures"].values()))
    spot_rows = sum(len(view["spot"][c]) for c in selected)
    out = pipeline.out[-1]
    assert (
        f"pack pre-flight: 5 coin packs to build, {rows} hourly rows as read ({spot_rows} spot, "
        f"{rows - spot_rows} futures)"
    ) in out
    assert out.index("pack pre-flight") < out.index("pack coin pack 1/5")
    assert f"pack: 5 coin packs, the largest {max(sizes)} bytes of canonical JSON" in out
    assert (data["coin_packs"], data["largest_coin_pack_json_bytes"]) == (5, max(sizes))
    assert data["hourly_rows"] == rows
    assert not (pipeline.data / "hourly.pack.json.gz").exists()  # no single hourly pack


def test_pack_builds_and_writes_the_coin_packs_one_coin_at_a_time(tmp_path, capsys, monkeypatch):
    # Ruling P32, structurally: after the pre-flight, a coin's series are read, its pack is
    # written, and only then is the next coin's first series read. So no two coins' series
    # are alive together, and nothing is read after the last coin pack.
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.until_final()
    events: list[tuple[str, str]] = []
    read_hourly, write, say = inputs.read_hourly, v4_data.write_canonical, v4_data._say

    def reading(content, symbol, month, *, futures):
        events.append(("read", symbol))
        return read_hourly(content, symbol, month, futures=futures)

    def writing(document, path):
        events.append(("write", Path(path).name))
        return write(document, path)

    def saying(line):
        events.append(("say", line))
        say(line)

    monkeypatch.setattr(inputs, "read_hourly", reading)
    monkeypatch.setattr(v4_data, "write_canonical", writing)
    monkeypatch.setattr(v4_data, "_say", saying)
    pipeline.pack()

    start = next(i for i, (kind, text) in enumerate(events) if text.startswith("pack pre-flight"))
    groups: list[tuple[str, list[str]]] = []
    reads: list[str] = []
    for kind, text in events[start + 1 :]:
        if kind == "read":
            reads.append(text)
        elif kind == "write":
            groups.append((text, reads))
            reads = []
    assert reads == []  # nothing read after the last write (the index)
    owners = {coin: {coin} for coin in ("AAAUSDT", "BBBUSDT", "EEEUSDT", "LATEUSDT")}
    owners["FFFUSDT"] = {"FFFUSDT", "1000FFFUSDT"}  # its spot series, and its perpetual's
    assert [name for name, _ in groups] == [
        *(f"v4-coin-{coin}.json.gz" for coin in sorted(owners)),
        "hourly-index.json.gz",
    ]
    for (_, read), coin in zip(groups, sorted(owners), strict=False):
        assert read and set(read) <= owners[coin], (coin, read)
    assert groups[-1][1] == []  # the index reads no series


def test_a_stray_funding_row_is_not_stored_but_still_makes_its_month_off_slot(tmp_path, capsys):
    # AAA's February funding file also holds a row at 00:00 on 1 March, outside its month: the
    # coin pack stores only rows inside each file's month, while the month status still sees
    # the stray row and is "off_slot".
    world = build_world()
    path = archive_path("funding", "AAAUSDT", FEB)
    stray = month_start("2024-03")
    world.files[path] = zipped(
        path, funding_csv(month_start(FEB), stray) + f"{stray},8,{FUNDING_RATE}\n"
    )
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.run()

    hourly = hourly_view(pipeline.data)
    assert hourly["funding_months"]["AAAUSDT|2024-02"] == "off_slot"
    assert hourly["funding_months"]["AAAUSDT|2024-01"] == "complete"
    times = [row[0] for row in hourly["funding"]["AAAUSDT"]]
    assert stray not in times and len(times) == 93 + 87


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
    assert {coin["sha256"] for coin in hourly_view(pipeline.data)["coins"].values()} <= set(pins)
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
    # Ruling P23 for 1000FFFUSDT: both its futures archives are unreadable, so FFFUSDT's coin
    # pack holds no futures series, and so no futures rules, masks, funding, funding months or
    # perpetual, nor does the index; FFFUSDT's spot series stays.
    world = build_world()
    for month in (JAN, FEB):
        world.files[archive_path("futures_1h", "1000FFFUSDT", month)] = GARBAGE
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.run()

    data = json.loads((pipeline.data / "data.json").read_text())
    hourly = hourly_view(pipeline.data)
    assert "FFFUSDT" in hourly["spot"] and "FFFUSDT|spot" in hourly["rules"]
    assert hourly["packs"]["FFFUSDT"]["perpetual"] is None  # its coin pack has none
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
    hourly = hourly_view(pipeline.data)
    assert hourly["perpetuals"]["FFFUSDT"] == {"symbol": "1000FFFUSDT", "multiplier": 1000}
    assert hourly["packs"]["FFFUSDT"]["perpetual"] == hourly["perpetuals"]["FFFUSDT"]
    assert "FFFUSDT" in hourly["spot"] and "FFFUSDT" not in hourly["futures"]
    assert len(hourly["futures"]["1000FFFUSDT"]) == 744 + 696
    assert hourly["masks"]["1000FFFUSDT|futures"] == {"masked": [], "unreadable": {}, "absent": []}
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
        (  # ruling P34: the mapping is re-derived from the recorded futures symbols
            lambda d: d["futures_symbols"].remove("1000FFFUSDT"),
            r"the perpetuals do not follow from futures_symbols \(ruling P34\)",
        ),
        (lambda d: d.pop("futures_symbols"), "futures_symbols must be a sorted list"),
        (
            lambda d: d["months"]["futures_1h"].update(AAAUSDT=[]),
            r"AAAUSDT has no futures_1h month, so it is no perpetual \(ruling P34\)",
        ),
        (  # ruling P33: only a name the archive paths cannot address is unsupported
            lambda d: d["exclusions"].update(ZZZUSDT="unsupported_name"),
            "'ZZZUSDT' is not an unsupported USDT name",
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


def test_an_unsupported_name_is_recorded_and_counted_but_never_fetched(tmp_path, capsys):
    # Ruling P33: 牛来USDT ends in USDT but the archive paths cannot address it.
    pipeline = Pipeline(tmp_path, capsys)
    pipeline.run()

    discovery = json.loads(pipeline.discovery.read_text(encoding="ascii"))
    assert discovery["exclusions"][UNSUPPORTED] == "unsupported_name"
    assert UNSUPPORTED not in discovery["symbols"] + discovery["candidates"]
    assert all(UNSUPPORTED not in per_symbol for per_symbol in discovery["months"].values())
    # Every request is ASCII (the transport's allowlist), so none names it, escaped or not.
    assert not [url for url in pipeline.world.requests if "%E7" in url.upper() or "牛" in url]
    assert (
        "3 excluded whatever their prices (1 leveraged, 1 stablecoin, 1 unsupported_name)"
        in (pipeline.out[0])
    )
    assert "1 more with an unsupported name" in pipeline.out[0] and UNSUPPORTED not in (
        pipeline.stdout()
    )


def test_a_plain_perpetual_listed_only_after_end_month_does_not_shadow_a_multiplier_one(
    tmp_path, capsys
):
    # Ruling P34: FFFUSDT has a futures archive only for 2024-04, after end_month 2024-03, so
    # it does not count: FFF's perpetual is still 1000FFFUSDT. Its months are listed, its
    # archives never requested.
    world = build_world()
    world.files[archive_path("futures_1h", "FFFUSDT", "2024-04")] = GARBAGE  # never read
    pipeline = Pipeline(tmp_path, capsys, world)
    pipeline.discover()

    discovery = json.loads(pipeline.discovery.read_text())
    assert discovery["perpetuals"]["FFFUSDT"] == {"symbol": "1000FFFUSDT", "multiplier": 1000}
    assert "FFFUSDT" not in discovery["futures_symbols"]
    assert "1000FFFUSDT" in discovery["futures_symbols"]
    listing = f"{LISTING}?delimiter=/&prefix=data/futures/um/monthly/klines/FFFUSDT/1h/"
    assert listing in pipeline.world.requests
    assert not [url for url in world.archive_requests() if "/FFFUSDT/" in url]
    assert "6 futures USDT symbols, 5 of them possible perpetuals" in pipeline.out[0]


def test_discover_refuses_an_end_month_that_is_not_yet_complete(tmp_path, capsys):
    pipeline = Pipeline(tmp_path, capsys)
    for now in (
        datetime(2024, 3, 31, 23, 59, tzinfo=UTC),  # end_month 2024-03 is still running
        datetime(2024, 4, 1, 1, 0, tzinfo=timezone(timedelta(hours=2))),  # 23:00 UTC 31 March
    ):
        pipeline.clock = lambda now=now: now
        pipeline.cli("discover", "--out", pipeline.discovery.parent, expect=1)
        assert (
            "end_month 2024-03 is not before the current UTC month 2024-03: it must be the last "
            "complete calendar month"
        ) in pipeline.err[-1]
        assert pipeline.world.requests == [] and not pipeline.discovery.exists()
    pipeline.clock = lambda: datetime(2024, 3, 1, tzinfo=UTC).replace(tzinfo=None)
    pipeline.cli("discover", "--out", pipeline.discovery.parent, expect=1)
    assert "timezone-aware" in pipeline.err[-1]
    pipeline.clock = lambda: datetime(2024, 4, 1, tzinfo=UTC)
    pipeline.discover()


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
    assert uploads["v4-data"]["path"].split() == [
        "v4/data/daily.pack.json.gz",
        "v4/data/hourly-index.json.gz",
        "v4/data/v4-coin-*.json.gz",
        "v4/data/data.json",
    ]
