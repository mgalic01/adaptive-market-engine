"""Bob's minute-bars fetch (scripts/fetch_minute_bars.py), against a fake archive host.

The committed spec's 301 archives cannot be synthesized in a unit test, so the script runs
with ``--spec`` on a small synthetic spec: three of the seven symbols, two months, 2023-02
and 2023-03. A fake host serves complete, flat synthetic archives under matching
``.CHECKSUM`` files. Nothing touches the network, nothing is dated after 2024-12, and
nothing here is market data or evidence.

Four features of the real fetch are built in: one archive has a three-minute hole (ok, with
its statistics, and no problem); one transport failure is retried; one month is not
published (a 404: missing); one archive holds two zip members (checksum-valid, unreadable).
The last two are problems, as they would be for the seven coins.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
import shlex
import socket
import subprocess  # nosec B404: a stand-in child, and pytest's own collection
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.backtest import dataset
from crypto_grid_bot.backtest.dataset import archive_path, load_manifest, local_path
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "config" / "datasets"
SCRIPT = ROOT / "scripts" / "fetch_minute_bars.py"
sys.path.insert(0, str(SCRIPT.parent))

import fetch_full_range  # noqa: E402
import fetch_minute_bars  # noqa: E402
import fetch_v3_data  # noqa: E402

MINUTE_MS = 60_000
OWNER_APPROVED = ("ADAUSDT", "BNBUSDT", "DOGEUSDT", "LINKUSDT", "LTCUSDT", "SOLUSDT", "TRXUSDT")
SYMBOLS = ("ADAUSDT", "LINKUSDT", "SOLUSDT")
MONTHS = ("2023-02", "2023-03")
NOW = datetime(2026, 10, 12, 8, 30, 0, tzinfo=UTC)
SYNTHETIC_SPEC = f"""name = "synthetic-minutes"
purpose = "fetch_minute_bars test: three symbols, two months"
interval = "1m"
symbols = [{", ".join(f'"{s}"' for s in SYMBOLS)}]
start = "{MONTHS[0]}"
end = "{MONTHS[1]}"
"""
TRANSIENT = archive_path("LINKUSDT", "1m", "2023-02")  # fails once in the happy run
GAPPED = ("ADAUSDT", "1m", "2023-03")  # three minutes missing from the middle
ABSENT = ("SOLUSDT", "1m", "2023-02")  # not published: a 404 in the problem run
TWO_MEMBERS = ("LINKUSDT", "1m", "2023-03")  # checksum-valid, unreadable in the problem run


def csv_text(bars: list[Kline]) -> str:
    """Binance's 12-column CSV rows of one-minute ``bars``, each closing on its boundary."""
    return "".join(
        f"{k.open_ms},{k.open},{k.high},{k.low},{k.close},{k.volume},"
        f"{k.open_ms + MINUTE_MS - 1},{k.quote_volume},10,{k.taker_buy_base},"
        f"{k.taker_buy_base * k.close},0\n"
        for k in bars
    )


def zip_of(*members: tuple[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in members:
            archive.writestr(name, text)
    return buffer.getvalue()


def serve(objects: dict[str, bytes], path: str, body: bytes, checksum: str | None = None) -> None:
    """Publish ``body`` at ``path`` with its .CHECKSUM, Binance's two-space format."""
    objects[path] = body
    digest = checksum or hashlib.sha256(body).hexdigest()
    objects[path + ".CHECKSUM"] = f"{digest}  {path.rsplit('/', 1)[1]}".encode()


def minute_bars(month: str, price: str, hole: range | None = None) -> list[Kline]:
    """Flat one-minute bars of the month, without the bars at the indexes of ``hole``."""
    start, end = month_bounds_ms(month)
    p, volume, taker = Decimal(price), Decimal(10), Decimal(4)
    return [
        Kline(t, p, p, p, p, volume, volume * p, taker)
        for index, t in enumerate(range(start, end, MINUTE_MS))
        if hole is None or index not in hole
    ]


@pytest.fixture(scope="module")
def archives() -> dict[str, bytes]:
    """Every object the fake host publishes, by archive path."""
    objects: dict[str, bytes] = {}
    for symbol in SYMBOLS:
        for month in MONTHS:
            hole = range(100, 103) if (symbol, "1m", month) == GAPPED else None
            text = csv_text(minute_bars(month, "10", hole))
            serve(
                objects,
                archive_path(symbol, "1m", month),
                zip_of((f"{symbol}-1m-{month}.csv", text)),
            )
    return objects


def refuse_network(*args: object, **kwargs: object) -> None:
    raise AssertionError("a test of fetch_minute_bars tried to reach the network")


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No test here can reach any host, and none writes in the working directory: the fetch
    code's connection, the exchange client and the socket layer raise, and each test runs
    from its own temporary directory."""
    monkeypatch.setattr(dataset, "https_connection", refuse_network)
    monkeypatch.setattr(dataset, "PublicClient", refuse_network)
    monkeypatch.setattr(socket.socket, "connect", refuse_network)
    monkeypatch.setattr(socket, "create_connection", refuse_network)
    monkeypatch.chdir(tmp_path)


class Host:
    """A fake data.binance.vision: objects by path, None (a 404) otherwise. It records every
    request, raises FeedError the first time each path in ``fail_once`` is requested, and
    every time for a path in ``fail_always``."""

    def __init__(
        self, objects: dict[str, bytes], fail_once: set[str], fail_always: set[str]
    ) -> None:
        self.objects = objects
        self.fail_once = set(fail_once)
        self.fail_always = fail_always
        self.requests: list[str] = []

    def __call__(self, path: str) -> bytes | None:
        self.requests.append(path)
        if path in self.fail_always or path in self.fail_once:
            self.fail_once.discard(path)
            raise FeedError(f"synthetic transport failure for {path}")
        return self.objects.get(path)


def snapshot(roots: list[Path], skip: Path) -> dict[str, str]:
    """Every file under ``roots`` except those under ``skip``, with its SHA-256."""
    return {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest()
        for root in roots
        for path in sorted(root.rglob("*"))
        if path.is_file() and skip not in path.parents
    }


@dataclass
class Run:
    """What one run of the script did."""

    code: int | None  # None when main raised
    error: BaseException | None
    out: str
    data: Path
    spec: Path
    host: Host
    sleeps: list[float]
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)

    @property
    def lines(self) -> list[str]:
        return self.out.splitlines()

    def manifest(self) -> dict[str, Any]:
        return load_manifest(self.data / "synthetic-minutes.manifest.json")

    def digest(self) -> str:
        return (self.data / "synthetic-minutes.digest.txt").read_text(encoding="utf-8")

    def row(self, symbol: str, month: str) -> str:
        name = f"{symbol}-1m-{month}.zip"
        (row,) = [r for r in self.digest().splitlines() if r.split(" ", 1)[0] == name]
        return row


def run_script(
    tmp: Path,
    objects: dict[str, bytes],
    fail_once: set[str] | None = None,
    fail_always: set[str] | None = None,
    *,
    data: Path | None = None,
) -> Run:
    """The script's ``main`` with the fake host, from an empty working directory, with every
    network route of the fetch code replaced by an error. ``data`` reuses a data dir."""
    specs, cwd = tmp / "specs", tmp / "cwd"
    specs.mkdir(parents=True, exist_ok=True)
    cwd.mkdir(parents=True, exist_ok=True)
    data = data or tmp / "data"
    spec = specs / "synthetic-minutes.toml"
    spec.write_text(SYNTHETIC_SPEC, encoding="utf-8")
    host = Host(objects, fail_once or set(), fail_always or set())
    run = Run(None, None, "", data, spec, host, [])
    roots = [tmp, ROOT / "config"]
    run.before = snapshot(roots, data)
    out = io.StringIO()
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(cwd)
        for name in ("https_connection", "PublicClient", "exchange_filters", "archive_get"):
            patch.setattr(dataset, name, refuse_network)
        patch.setattr(socket.socket, "connect", refuse_network)
        patch.setattr(socket, "create_connection", refuse_network)
        with contextlib.redirect_stdout(out):
            try:
                run.code = fetch_minute_bars.main(
                    [str(data), "--spec", str(spec)],
                    fetcher=host,
                    sleep=run.sleeps.append,
                    now=lambda: NOW,
                )
            except Exception as exc:
                run.error = exc
    run.out = out.getvalue()
    run.after = snapshot(roots, data)
    return run


@pytest.fixture(scope="module")
def happy(archives: dict[str, bytes], tmp_path_factory: pytest.TempPathFactory) -> Run:
    """The whole run, with one transient transport failure on the way."""
    return run_script(tmp_path_factory.mktemp("happy"), archives, {TRANSIENT})


@pytest.fixture(scope="module")
def problems(archives: dict[str, bytes], tmp_path_factory: pytest.TempPathFactory) -> Run:
    """The run in which one month is not published and one archive is unreadable."""
    objects = {
        path: body for path, body in archives.items() if not path.startswith(archive_path(*ABSENT))
    }
    symbol, interval, month = TWO_MEMBERS
    text = csv_text(minute_bars(month, "10"))
    serve(
        objects,
        archive_path(*TWO_MEMBERS),
        zip_of((f"{symbol}-{interval}-{month}.csv", text), ("README.txt", "second\n")),
    )
    return run_script(tmp_path_factory.mktemp("problems"), objects)


# --- the committed spec is the owner's approved scope ----------------------------------------


def test_the_committed_spec_is_exactly_the_approved_fetch() -> None:
    path = fetch_minute_bars.SPEC
    assert path.parent == DATASETS / "v3-1-minute-bars"  # not a backtest dataset spec
    spec = fetch_minute_bars.load_minute_spec(path)
    assert spec.name == path.stem == "v3-1-minute-bars-2021-2024"
    assert spec.purpose == "V3.1 grid flow gate"
    assert spec.symbols == OWNER_APPROVED
    assert (spec.start, spec.end) == ("2021-06", "2024-12")
    months = spec.months(spec.start)
    assert (len(months), months[0], months[-1]) == (43, "2021-06", "2024-12")
    files = spec.required()
    assert len(files) == len(set(files)) == 7 * 43 == 301
    assert {interval for _, interval, _ in files} == {"1m"}
    assert max(month for _, _, month in files) == "2024-12"  # nothing at or after 2025-01
    assert spec.traded == () and spec.breadth_basket == ()  # bars only: no hourly, no filters
    text = path.read_text(encoding="utf-8")
    assert "Nothing at or after 2025-01 is in scope" in text


def test_the_seven_coins_complete_the_ten_coin_universe_with_the_minute_bars_we_hold() -> None:
    held = load_manifest(DATASETS / "full-range-2017-2024.manifest.json")["files"]
    have_minutes = {e["symbol"] for e in held if e.get("interval") == "1m"}
    assert have_minutes == {"BTCUSDT", "ETHUSDT", "XRPUSDT"}
    assert not have_minutes & set(OWNER_APPROVED)
    assert have_minutes | set(OWNER_APPROVED) == set(fetch_v3_data.SYMBOLS)


def test_the_plan_lists_301_archives_and_their_checksums_and_nothing_else(
    tmp_path: Path,
) -> None:
    lines: list[str] = []
    args = fetch_minute_bars._parser().parse_args([str(tmp_path / "data")])
    plan = fetch_minute_bars.make_plan(args, lines.append)
    assert len(plan.paths) == 602
    assert sum(path.endswith(".CHECKSUM") for path in plan.paths) == 301
    for path in plan.paths:
        assert re.fullmatch(
            r"/data/spot/monthly/klines/([A-Z]+)/1m/\1-1m-20(2[1-4])-\d\d\.zip(\.CHECKSUM)?",
            path,
        ), path
    assert plan.paths == {
        archive_path(s, "1m", m) + suffix
        for s, _, m in plan.spec.required()
        for suffix in ("", ".CHECKSUM")
    }
    assert (tmp_path / "data" / "v3-1-minute-bars-2021-2024.toml").read_bytes() == (
        fetch_minute_bars.SPEC.read_bytes()
    )
    symbols = ", ".join(OWNER_APPROVED)
    assert lines[0].startswith(
        f"PLAN v3-1-minute-bars-2021-2024: 301 1m kline files, 7 symbols ({symbols}) x 43 "
        "months 2021-06..2024-12; spec "
    )
    assert lines[1].startswith(
        "PLAN latest month 2024-12; 602 planned paths: 301 archives and 301 .CHECKSUM, so 602 "
        "requests if nothing is retried or stored already; data dir "
    )
    assert len(lines) == 2


def test_the_spec_loader_is_strict(tmp_path: Path) -> None:
    good = fetch_minute_bars.SPEC.read_text(encoding="utf-8")
    spec = tmp_path / "spec.toml"
    spec.write_text(good, encoding="utf-8")
    assert fetch_minute_bars.load_minute_spec(spec).symbols == OWNER_APPROVED
    bad = {
        "an unknown field": good + 'surprise = "x"\n',
        "a missing field": good.replace('purpose = "V3.1 grid flow gate"\n', ""),
        "another interval": good.replace('interval = "1m"', 'interval = "1h"'),
        "a symbol list that is a string": re.sub(
            r"symbols = \[.*?\]", 'symbols = "ADAUSDT"', good, flags=re.S
        ),
        "a lowercase symbol": good.replace('"ADAUSDT"', '"adausdt"'),
        "a duplicate symbol": good.replace('"BNBUSDT"', '"ADAUSDT"'),
        "no symbol": re.sub(r"symbols = \[.*?\]", "symbols = []", good, flags=re.S),
        "a number as a symbol": good.replace('"ADAUSDT"', "7"),
        "the reserved month as the end": good.replace('end = "2024-12"', 'end = "2025-01"'),
        "a later year as the end": good.replace('end = "2024-12"', 'end = "2026-10"'),
        "an unpadded month": good.replace('start = "2021-06"', 'start = "2021-6"'),
        "an end before the start": good.replace('end = "2024-12"', 'end = "2021-05"'),
        "an empty purpose": good.replace('purpose = "V3.1 grid flow gate"', 'purpose = " "'),
        "an upper-case name": good.replace('name = "v3-1-minute-bars-2021-2024"', 'name = "V3-1"'),
        "broken TOML": good + "\n[",
    }
    for what, text in bad.items():
        spec.write_text(text, encoding="utf-8")
        try:
            fetch_minute_bars.load_minute_spec(spec)
        except DataError:
            continue
        pytest.fail(f"the loader accepted {what}")


# --- the run ---------------------------------------------------------------------------------


def test_a_run_writes_only_under_data_and_asks_only_for_planned_paths(happy: Run) -> None:
    assert (happy.code, happy.error) == (0, None), happy.out
    assert happy.lines[-1] == "RESULT 0 problem(s)"
    # No file outside <data-dir> changed or was added, and config/ is untouched.
    assert happy.after == happy.before
    planned = {
        archive_path(s, "1m", m) + suffix
        for s in SYMBOLS
        for m in MONTHS
        for suffix in ("", ".CHECKSUM")
    }
    assert set(happy.host.requests) == planned
    # 6 archives and 6 checksums, and the one request that failed and was asked again.
    assert len(happy.host.requests) == 12 + 1
    (requests,) = [line for line in happy.lines if line.startswith("REQUESTS ")]
    assert requests.startswith("REQUESTS 13 to data.binance.vision, 6 of them .CHECKSUM; ")
    assert "latest month 2023-03; after 2024-12: 0" in requests
    listed = (happy.data / "requests.txt").read_text(encoding="utf-8").splitlines()
    assert listed == happy.host.requests
    # The spec is copied into <data-dir>, and the manifest is written next to the copy.
    assert (happy.data / happy.spec.name).read_bytes() == happy.spec.read_bytes()
    assert (happy.data / "synthetic-minutes.manifest.json").is_file()
    assert not list(happy.data.glob("*exchange*"))  # no exchangeInfo, no filters file
    plan = [line for line in happy.lines if line.startswith("PLAN")]
    assert plan[0].startswith(
        "PLAN synthetic-minutes: 6 1m kline files, 3 symbols (ADAUSDT, LINKUSDT, SOLUSDT) x 2 "
        "months 2023-02..2023-03; spec "
    )
    assert "12 planned paths: 6 archives and 6 .CHECKSUM, so 12 requests" in plan[1]


def test_the_manifest_lists_exactly_the_specs_archives_in_its_order(happy: Run) -> None:
    manifest = happy.manifest()
    spec = fetch_minute_bars.load_minute_spec(happy.spec)
    assert (manifest["schema"], manifest["dataset"]) == (1, "synthetic-minutes")
    assert manifest["source"] == "https://data.binance.vision"
    assert manifest["created_at"] == "2026-10-12T08:30:00+00:00"
    assert manifest["instruments"] == {}  # bars only: no exchange filters
    assert [(e["symbol"], e["interval"], e["month"]) for e in manifest["files"]] == (
        spec.required()
    )
    assert {e["status"] for e in manifest["files"]} == {"ok"}
    for entry in manifest["files"]:
        assert (
            entry["url"]
            == f"https://data.binance.vision{archive_path(entry['symbol'], '1m', entry['month'])}"
        )
        local = local_path(happy.data, entry["symbol"], "1m", entry["month"])
        assert hashlib.sha256(local.read_bytes()).hexdigest() == entry["sha256"]
        assert entry["timestamp_units"] == ["ms"]
    assert "VERIFY synthetic-minutes valid: 6 files match the spec, and 6 local archives" in (
        happy.out
    )
    assert "KLINES synthetic-minutes: 6 files; ok 6; complete months 5" in happy.out


def test_a_transient_feed_error_is_retried_and_the_run_completes(happy: Run) -> None:
    assert happy.code == 0
    assert happy.host.requests.count(TRANSIENT + ".CHECKSUM") == 1
    assert happy.host.requests.count(TRANSIENT) == 2  # the checksum came first, then it failed
    assert happy.sleeps == [1]
    assert f"RETRY attempt 1 of 4 for {TRANSIENT}: synthetic transport failure" in happy.out


def test_a_month_with_a_hole_is_ok_and_its_digest_row_gives_the_difference(happy: Run) -> None:
    (entry,) = [
        e for e in happy.manifest()["files"] if (e["symbol"], e["interval"], e["month"]) == GAPPED
    ]
    assert (entry["status"], entry["gaps"]) == ("ok", 1)
    assert entry["missing_rows"] == 3 and entry["rows"] == entry["expected_rows"] - 3
    name = f"{GAPPED[0]}-1m-{GAPPED[2]}.zip"
    assert happy.row(GAPPED[0], GAPPED[2]) == (
        f"{name} {entry['sha256']} ok {entry['bytes']} rows={entry['rows']} gaps=1"
    )
    # A complete month's row says only that.
    assert happy.row("ADAUSDT", "2023-02").endswith(
        " ok " + happy.row("ADAUSDT", "2023-02").split(" ")[3] + " full"
    )
    # The hole is reported in the coverage line, and is no problem.
    coverage = "COVERAGE ADAUSDT: 2 files 2023-02..2023-03; ok 2, missing 0, unreadable 0; "
    assert coverage + "complete months 1; rows " in happy.out
    assert not [line for line in happy.lines if line.startswith(("PROBLEM", "ABSENT"))]


def test_the_digest_rebuilds_the_manifest_byte_for_byte(happy: Run, tmp_path: Path) -> None:
    spec = fetch_minute_bars.load_minute_spec(happy.spec)
    digest = happy.digest()
    lines = digest.splitlines()
    assert lines[0] == "digest of synthetic-minutes, format v1 (scripts/fetch_minute_bars.py)"
    path = happy.data / "synthetic-minutes.manifest.json"
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    assert lines[1] == (
        f"manifest synthetic-minutes created_at 2026-10-12T08:30:00+00:00 files 6 sha256 {sha256}"
    )
    assert len(lines) == 2 + 6 and digest.endswith("\n")
    # What the script checked, redone here from the digest text alone.
    rebuilt = fetch_minute_bars.rebuild(digest, spec)
    target = tmp_path / "rebuilt.json"
    dataset.write_manifest(target, rebuilt)
    assert target.read_bytes() == path.read_bytes()
    (line,) = [line for line in happy.lines if line.startswith("DIGEST ")]
    digest_sha256 = hashlib.sha256((happy.data / "synthetic-minutes.digest.txt").read_bytes())
    assert f"sha256 {digest_sha256.hexdigest()}; rebuilds the manifest byte for byte: True" in line
    # The digest is written before any check runs.
    order = [line.split(" ", 1)[0] for line in happy.lines]
    assert order.index("DIGEST") < order.index("VERIFY") < order.index("COVERAGE")
    # A digest that does not list the spec's archives, once each, is refused.
    with pytest.raises(ValueError, match="not synthetic-minutes's archives"):
        fetch_minute_bars.rebuild("\n".join(lines[:-1]) + "\n", spec)
    with pytest.raises(ValueError, match="twice"):
        fetch_minute_bars.rebuild("\n".join([*lines, lines[-1]]) + "\n", spec)
    with pytest.raises(ValueError, match="is not synthetic-minutes's"):
        fetch_minute_bars.rebuild("digest\nmanifest other created_at x files 6 sha256 y\n", spec)


def test_a_missing_month_and_an_unreadable_archive_are_rows_that_rebuild_and_problems(
    problems: Run,
) -> None:
    run = problems
    assert (run.code, run.error) == (1, None), run.out
    manifest = run.manifest()
    by_id = {(e["symbol"], e["interval"], e["month"]): e for e in manifest["files"]}
    assert by_id[ABSENT]["status"] == "missing"
    assert run.row(ABSENT[0], ABSENT[2]) == f"{ABSENT[0]}-1m-{ABSENT[2]}.zip missing"
    unreadable = by_id[TWO_MEMBERS]
    reason = "archive must contain exactly LINKUSDT-1m-2023-03.csv"
    assert (unreadable["status"], unreadable["reason"]) == ("unreadable", reason)
    name = f"{TWO_MEMBERS[0]}-1m-{TWO_MEMBERS[2]}.zip"
    assert run.row(TWO_MEMBERS[0], TWO_MEMBERS[2]) == (
        f'{name} {unreadable["sha256"]} unreadable {unreadable["bytes"]} "{reason}"'
    )
    # A missing month costs the same two requests as a published one: .CHECKSUM, then the
    # archive, to be sure that it is absent too.
    assert [p for p in run.host.requests if "SOLUSDT-1m-2023-02" in p] == [
        archive_path(*ABSENT) + ".CHECKSUM",
        archive_path(*ABSENT),
    ]
    assert len(run.host.requests) == 12
    assert run.lines[-3:-1] == [
        "PROBLEM 1 archive(s) missing: SOLUSDT 2023-02",
        "PROBLEM 1 archive(s) unreadable: LINKUSDT 2023-03",
    ]
    assert run.lines[-1] == "RESULT 2 problem(s)"
    assert f"ABSENT {name} unreadable: {reason}" in run.out
    assert "ABSENT SOLUSDT-1m-2023-02.zip missing" in run.out
    assert "COVERAGE SOLUSDT: 2 files 2023-02..2023-03; ok 1, missing 1, unreadable 0" in run.out
    # The digest is complete and rebuilds the manifest whole, the problems notwithstanding.
    spec = fetch_minute_bars.load_minute_spec(run.spec)
    assert fetch_minute_bars.rebuild(run.digest(), spec) == manifest
    assert "rebuilds the manifest byte for byte: True" in run.out
    assert "VERIFY synthetic-minutes valid: 6 files match the spec, and 5 local archives" in (
        run.out
    )


def test_a_checksum_mismatch_is_not_retried_and_stops_the_run(
    archives: dict[str, bytes], tmp_path: Path
) -> None:
    objects = dict(archives)
    path = archive_path("ADAUSDT", "1m", "2023-02")
    serve(objects, path, objects[path], checksum="0" * 64)
    run = run_script(tmp_path, objects)
    assert isinstance(run.error, DataError)
    assert "does not match Binance's published SHA-256" in str(run.error)
    assert run.host.requests.count(path) == 1
    assert run.sleeps == []
    assert not list(run.data.glob("*.manifest.json"))
    assert not list(run.data.glob("*.digest.txt"))
    assert not local_path(run.data, "ADAUSDT", "1m", "2023-02").exists()
    # The traceback still leaves the request count and list behind (a finally).
    (requests,) = [line for line in run.lines if line.startswith("REQUESTS ")]
    assert requests.startswith(f"REQUESTS {len(run.host.requests)} to data.binance.vision")
    listed = (run.data / "requests.txt").read_text(encoding="utf-8").splitlines()
    assert listed == run.host.requests


def test_a_transport_failure_that_lasts_ends_after_four_attempts(
    archives: dict[str, bytes], tmp_path: Path
) -> None:
    path = archive_path("SOLUSDT", "1m", "2023-02") + ".CHECKSUM"
    run = run_script(tmp_path, archives, fail_always={path})
    assert isinstance(run.error, FeedError)
    assert run.host.requests.count(path) == 4
    assert run.sleeps == [1, 2, 4]
    retries = [line.split(":")[0] for line in run.lines if line.startswith("RETRY")]
    assert retries == [f"RETRY attempt {n} of 4 for {path}" for n in (1, 2, 3, 4)]
    assert not list(run.data.glob("*.manifest.json"))
    assert (run.data / "requests.txt").is_file()


def test_requests_outside_the_plan_are_refused(tmp_path: Path) -> None:
    args = fetch_minute_bars._parser().parse_args([str(tmp_path / "data")])
    plan = fetch_minute_bars.make_plan(args, fetch_full_range.Log())
    reached: list[str] = []

    def host(path: str) -> bytes | None:
        reached.append(path)
        return None

    requests = fetch_full_range.Requests(host, plan.paths, lambda s: None, lambda line: None)
    refused = [
        archive_path("ADAUSDT", "1m", "2025-01"),  # the reserved window
        archive_path("ADAUSDT", "1m", "2025-01") + ".CHECKSUM",
        archive_path("ADAUSDT", "1h", "2022-01"),  # an hourly archive
        archive_path("ADAUSDT", "1d", "2022-01"),  # a daily archive
        archive_path("BTCUSDT", "1m", "2022-01"),  # a coin whose minutes the project holds
        archive_path("ADAUSDT", "1m", "2021-05"),  # before the spec's first month
        "/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2022-01.zip",
        "/data/spot/monthly/klines/ADAUSDT/1m/",  # a directory listing
        "/api/v3/exchangeInfo",
    ]
    for path in refused:
        with pytest.raises(fetch_full_range.OutOfScope):
            requests(path)
    assert reached == [] and requests.paths == []
    # The downloader itself still refuses the reserved window, below this script's plan.
    with pytest.raises(DataError, match="reserved window"):
        dataset.archive_get(archive_path("ADAUSDT", "1m", "2025-01"))
    # And so does the spec, before a plan exists.
    late = tmp_path / "late.toml"
    late.write_text(
        fetch_minute_bars.SPEC.read_text(encoding="utf-8").replace(
            'end = "2024-12"', 'end = "2025-01"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(DataError, match="reserved window"):
        fetch_minute_bars.load_minute_spec(late)


def test_no_exchange_filters_are_ever_asked_for() -> None:
    with pytest.raises(fetch_full_range.OutOfScope):
        fetch_minute_bars.no_filters("ADAUSDT")


def test_a_second_run_in_the_same_data_dir_asks_only_for_checksums_and_changes_nothing(
    archives: dict[str, bytes], tmp_path: Path
) -> None:
    """The restart path: stored archives that match their checksum are not downloaded
    again, and the manifest and digest come out byte for byte the same."""
    first = run_script(tmp_path / "a", archives)
    again = run_script(tmp_path / "a", archives, data=first.data)
    assert (first.code, again.code) == (0, 0), again.out
    assert sorted(again.host.requests) == sorted(
        archive_path(s, "1m", m) + ".CHECKSUM" for s in SYMBOLS for m in MONTHS
    )
    for name in ("synthetic-minutes.manifest.json", "synthetic-minutes.digest.txt"):
        assert (again.data / name).read_bytes() == (first.data / name).read_bytes()


# --- start and wait: the script runs itself in the background (Step 4 of the task) ----------
# Each test starts real child processes of the script with its hidden --fake-run option, so
# the child sleeps briefly and exits instead of fetching anything: no network.


def background(monkeypatch: pytest.MonkeyPatch, wait_seconds: float) -> None:
    monkeypatch.setattr(fetch_full_range, "WAIT_SECONDS", wait_seconds)
    monkeypatch.setattr(fetch_full_range, "POLL_SECONDS", 0.1)


def test_start_runs_the_script_detached_and_wait_reports_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    background(monkeypatch, 60)
    data = tmp_path / "data"
    run = fetch_minute_bars.main
    assert run(["wait", str(data)]) == 1
    not_started = capsys.readouterr().out.splitlines()
    assert not_started[0].startswith("NOT STARTED")
    assert not_started[-1] == fetch_full_range.NEXT_NOT_STARTED
    assert run(["start", str(data), "--fake-run", "0.2"]) == 0
    pid = int((data / "run.pid").read_text(encoding="utf-8"))
    log, exit_file = (data / "run.log").as_posix(), (data / "run.exit").as_posix()
    assert capsys.readouterr().out == f"STARTED pid {pid}; log {log}; exit file {exit_file}\n"
    assert run(["wait", str(data)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (lines[0], lines[-2]) == ("DONE exit=0", "RESULT 0 problem(s)")
    # Issue #195: the last line names the next step, so DONE never reads as the end.
    assert lines[-1] == fetch_full_range.NEXT_DONE
    assert (data / "run.exit").read_text(encoding="utf-8") == "0\n"
    # A run that has ended is never started again in the same data dir.
    assert run(["start", str(data), "--fake-run", "0.2"]) == 1
    assert capsys.readouterr().out.startswith("NOT STARTED")


def test_a_run_that_ends_in_a_traceback_still_writes_its_exit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert fetch_minute_bars.main(["start", str(data), "--fake-run", "0.3", "--fake-raise"]) == 0
    capsys.readouterr()
    background(monkeypatch, 60)
    assert fetch_minute_bars.main(["wait", str(data)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "DONE exit=1"  # DONE, not GONE
    assert lines[-2] == "RuntimeError: fake run failure"
    assert lines[-1] == fetch_full_range.NEXT_DONE
    # A second start while a run is alive is refused.
    data2 = tmp_path / "data2"
    assert fetch_minute_bars.main(["start", str(data2), "--fake-run", "2"]) == 0
    capsys.readouterr()
    assert fetch_minute_bars.main(["start", str(data2), "--fake-run", "0.2"]) == 1
    assert "still running" in capsys.readouterr().out
    assert fetch_minute_bars.main(["wait", str(data2)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "DONE exit=0"


def test_a_lost_run_is_restarted_once_and_a_second_loss_names_the_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    background(monkeypatch, 60)
    data = tmp_path / "data"
    data.mkdir()
    ended = subprocess.Popen([sys.executable, "-c", "pass"])  # nosec B603: a fixed command
    ended.wait()
    (data / "run.pid").write_text(f"{ended.pid}\n", encoding="utf-8")
    (data / "run.log").write_text("PLAN first attempt\n", encoding="utf-8")
    assert fetch_minute_bars.main(["wait", str(data)]) == 0
    assert capsys.readouterr().out == (
        f"GONE pid {ended.pid}: no process and no exit file; latest: PLAN first attempt\n"
        f"{fetch_full_range.NEXT_GONE}\n"
    )
    # start runs it once more, unchanged, and keeps the first attempt's log.
    assert fetch_minute_bars.main(["start", str(data), "--fake-run", "0.1"]) == 0
    capsys.readouterr()
    assert (data / "run-1.log").read_text(encoding="utf-8") == "PLAN first attempt\n"
    assert fetch_minute_bars.main(["wait", str(data)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "DONE exit=0"
    # Lost a second time: no third attempt.
    other = tmp_path / "other"
    other.mkdir()
    (other / "run-1.log").write_text("PLAN first attempt\n", encoding="utf-8")
    (other / "run.pid").write_text(f"{ended.pid}\n", encoding="utf-8")
    (other / "run.log").write_text("PLAN second attempt\n", encoding="utf-8")
    assert fetch_minute_bars.main(["wait", str(other)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == fetch_full_range.NEXT_GONE_AGAIN
    assert fetch_minute_bars.main(["start", str(other), "--fake-run", "0.1"]) == 1
    assert "was already restarted once" in capsys.readouterr().out
    assert (other / "run.log").read_text(encoding="utf-8") == "PLAN second attempt\n"
    assert not (other / "run-2.log").exists()


def test_start_refuses_a_task_file_that_is_not_the_reviewed_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bob's workflow checks out main as it is when the job starts, so an edit to the task
    while its run is queued would run unnoticed. The committed task file reads as the
    script's TASK_SHA256; one changed line makes start refuse before it writes or launches
    anything. The pin block is left out of the digest, so changing a pin (as every new
    SHA-256 of this script does) leaves it as it was."""
    text = fetch_minute_bars.TASK.read_text(encoding="utf-8")
    assert fetch_full_range.task_digest(fetch_minute_bars.TASK) == fetch_minute_bars.TASK_SHA256
    edited = tmp_path / "edited.md"
    edited.write_text(
        text.replace("## Stop conditions", "## Stop conditions\n\nGo on.", 1), encoding="utf-8"
    )
    monkeypatch.setattr(fetch_minute_bars, "TASK", edited)
    data = tmp_path / "data"
    assert fetch_minute_bars.main(["start", str(data), "--fake-run", "0.1"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("NOT STARTED: the task file edited.md is not the reviewed text"), out
    assert not data.exists()  # nothing written, nothing launched
    script_pin = re.compile(r"(?m)^[0-9a-f]{64}(  scripts/fetch_minute_bars\.py)$")
    assert script_pin.search(text)
    repinned = tmp_path / "repinned.md"
    repinned.write_text(script_pin.sub("f" * 64 + r"\1", text), encoding="utf-8")
    assert fetch_full_range.task_digest(repinned) == fetch_minute_bars.TASK_SHA256


def test_the_report_tools_and_wait_are_the_long_window_fetchs_and_start_is_this_scripts() -> None:
    tools = fetch_minute_bars.TOOLS
    assert set(tools) == set(fetch_full_range.TOOLS)
    assert tools["start"] is fetch_minute_bars.start
    assert fetch_full_range.TOOLS["start"] is not tools["start"]
    for name, tool in fetch_full_range.TOOLS.items():
        if name != "start":
            assert tools[name] is tool, name
    # One of them, through this script's main: the clock, as the shell prints it.
    assert fetch_minute_bars.main(["now"]) == 0


# --- the task file ----------------------------------------------------------------------------

TASK_FILE = fetch_minute_bars.TASK
# bob-task.yml's prompt: "python, the installed project CLIs, pytest, sha256sum and read-only
# git commands"; the project CLIs run as python -m.
ALLOWED_COMMANDS = {"python", "pytest", "sha256sum", "git"}
READ_ONLY_GIT = {"rev-parse", "show", "ls-files", "diff", "log", "cat-file", "status"}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")"}
SHELL_UTILITIES = {
    "date", "mkdir", "sed", "wc", "tail", "head", "find", "grep", "mv", "cp", "rm", "cat",
    "echo", "ls", "sleep", "nohup", "setsid", "pgrep", "sh", "bash", "test", "touch", "awk",
    "xargs", "tee", "env", "printenv", "set",
}  # fmt: skip
FENCED = re.compile(r"^ *```text\n(.*?)^ *```$", re.S | re.M)


def task_commands() -> list[tuple[str, list[str]]]:
    """(line, words) for every command in the task file's fenced blocks, split at the shell's
    separators; a line of the pin block is a SHA-256 and a path, not a command."""
    found = []
    for block in FENCED.findall(TASK_FILE.read_text(encoding="utf-8")):
        for raw in block.splitlines():
            line = raw.strip()
            if not line or re.fullmatch(r"[0-9a-f]{64}  \S+", line):
                continue
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            words: list[str] = []
            for token in [*lexer, ";"]:
                if token in SEPARATORS:
                    if words:
                        found.append((line, words))
                    words = []
                else:
                    words.append(token)
    return found


def test_the_task_file_asks_bob_only_for_commands_his_prompt_allows() -> None:
    """bob-task.yml's rules override everything else Bob reads, and a task that cannot be
    done as written makes him stop, so every command in the task must be one the prompt
    allows."""
    found = task_commands()
    assert len(found) >= 20, found  # the blocks were found
    for line, words in found:
        assert words[0] in ALLOWED_COMMANDS, line
        if words[0] == "git":
            assert words[1] in READ_ONLY_GIT, line
        for shell in ("$(", "<<", "`"):
            assert shell not in line, line
    # Commands named in the prose are held to it too: none is a shell utility.
    prose = FENCED.sub("", TASK_FILE.read_text(encoding="utf-8"))
    for span in re.findall(r"`([^`\n]+)`", prose):
        words = span.split()
        assert not words or words[0] not in SHELL_UTILITIES, span


def test_a_pin_failure_runs_no_script() -> None:
    """After a failed pin the script and its tests are not the reviewed ones, and an older
    script can read an argument it does not know as a data directory and start a fetch. So
    the pin-failure path writes the report with Bob's edit tool and runs nothing."""
    text = TASK_FILE.read_text(encoding="utf-8")
    stops = text.split("## Stop conditions", 1)[1]
    pin_path = stops.split("- **Step 1 or Step 2 failed**", 1)[1].split("\n- **", 1)[0]
    assert "run nothing else" in pin_path and "edit tool" in pin_path
    assert "```" not in pin_path  # not one command to run on this path
    pins = text.split("## Pinned inputs", 1)[1].split("## Steps", 1)[0]
    assert "pin-failure path" in pins
    self_check = text.split("## Self-check", 1)[1]
    assert "After a pin failure (Step 1 or Step 2), run neither" in self_check


def test_the_task_file_states_the_scope_and_the_pins_name_real_files() -> None:
    text = TASK_FILE.read_text(encoding="utf-8")
    # The scope table's numbers are the spec's, computed here.
    spec = fetch_minute_bars.load_minute_spec(fetch_minute_bars.SPEC)
    files = len(spec.required())
    for fact in (
        f"{files} archives",
        f"{2 * files} requests",
        f"{len(spec.symbols)} symbols x {len(spec.months(spec.start))} months",
        "docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md",
        "2025-01",
    ):
        assert fact in text, fact
    block = text.split("## Pinned inputs", 1)[1].split("```text\n", 1)[1].split("```", 1)[0]
    pinned = [line.split("  ", 1)[1] for line in block.splitlines()]
    assert pinned == [
        "scripts/fetch_minute_bars.py",
        "tests/test_fetch_minute_bars.py",
        "scripts/fetch_full_range.py",
        "config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.toml",
    ]
    for path in pinned:
        assert (ROOT / path).is_file(), path
    # The Step 3 count is the number of tests in this module, as pytest collects them.
    result = subprocess.run(  # nosec B603: pytest's own collection of this file
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         str(Path(__file__).resolve())],
        capture_output=True, text=True, check=False, cwd=ROOT,
    )  # fmt: skip
    collected = re.search(r"(\d+) tests? collected|: (\d+)$", result.stdout, re.M)
    assert collected, result.stdout
    count = int(collected.group(1) or collected.group(2))
    assert f"`{count} passed`" in text


def test_step_4_starts_and_waits_in_the_data_dir_that_step_5_measures() -> None:
    commands = [" ".join(words) for _, words in task_commands()]
    assert "python scripts/fetch_minute_bars.py start data/v3-1-minute-bars" in commands
    assert "python scripts/fetch_minute_bars.py wait data/v3-1-minute-bars" in commands
    assert "python scripts/fetch_minute_bars.py measure data/v3-1-minute-bars data" in commands
