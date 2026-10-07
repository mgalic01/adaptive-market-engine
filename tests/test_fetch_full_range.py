"""Bob's long-window fetch (scripts/fetch_full_range.py), against a fake archive host.

Long-window data plan, Task 9. The committed spec's 1,164 archives cannot be synthesized
complete in a unit test, and incomplete ones would mask every hour and make ``verify`` exit
2. So the script runs with ``--spec`` and ``--reported-spec`` on two small synthetic specs
with the committed specs' traded pairs, proxy, basket and pricing: one evaluation month,
2023-02, with its hourly and daily warm-ups. The second spec's files are a subset of the
first's, as ``full-range-2019-2024``'s are of ``full-range-2017-2024``'s. A fake host serves
complete, flat synthetic archives under matching ``.CHECKSUM`` files, and one BTCUSDT
funding month. Nothing touches the network, nothing is dated after 2024-12, and nothing
here is market data or evidence.

The synthetic data has three features of the real fetch: SOLUSDT has no archive before its
(synthetic) listing, so its warm-up months are 404s and ``missing``; LINKUSDT's first
hourly archive holds two zip members, so it is checksum-valid and ``unreadable``; both lie
inside the spec's documented basket absences, so ``verify`` still passes.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess  # nosec B404: a stand-in child
import sys
import time
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.backtest import dataset
from crypto_grid_bot.backtest.dataset import (
    archive_path,
    funding_archive_path,
    is_funding,
    load_manifest,
    load_spec,
    local_path,
)
from crypto_grid_bot.backtest.jobs import manifest_path
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "config" / "datasets"
SCRIPT = ROOT / "scripts" / "fetch_full_range.py"
sys.path.insert(0, str(SCRIPT.parent))

import fetch_full_range  # noqa: E402

MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
TRADED = ("BTCUSDT", "ETHUSDT", "XRPUSDT")
BASKET = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "TRXUSDT",
)
EVALUATION = "2023-02"
HOURLY_MONTHS = ("2022-12", "2023-01", "2023-02")
DAILY_MONTHS = tuple(f"2022-{m:02d}" for m in range(6, 13)) + ("2023-01", "2023-02")
# Flat prices: XRPUSDT at 1.0 keeps its synthesized quotes inside the 0.15% spread limit
# (bid 0.9997, ask 1.0003), so rule 8's test passes; the others are on a 0.01 tick.
PRICES = {"BTCUSDT": "100", "ETHUSDT": "100", "XRPUSDT": "1"}
PRICING = """initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""
SYMBOLS = """traded = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = [
  "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
  "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT",
]
"""
# 245 completed daily bars before 2023-02 (P3 needs 200); hourly warm-up 2022-12 and 2023-01.
SCORED_SPEC = (
    'name = "synthetic-scored"\n'
    'purpose = "fetch_full_range test: one evaluation month"\n'
    + SYMBOLS
    + 'daily_warmup_start = "2022-06"\n'
    'warmup_start = "2022-12"\n'
    'start = "2023-02"\n'
    'end = "2023-02"\n'
    + PRICING
    + """
[[basket_exclusions]]
symbol = "SOLUSDT"
from = "2022-12-01T00:00Z"
to = "2023-02-01T00:00Z"
reason = "synthetic listing: no SOLUSDT archive before 2023-02"

[[basket_exclusions]]
symbol = "LINKUSDT"
from = "2022-12-01T00:00Z"
to = "2023-01-01T00:00Z"
reason = "synthetic: LINKUSDT's 2022-12 archive holds two members"
"""
)
# The subset: 214 completed daily bars before 2023-02, hourly warm-up 2023-01 only.
REPORTED_SPEC = (
    'name = "synthetic-reported"\n'
    'purpose = "fetch_full_range test: the reported subset"\n'
    + SYMBOLS
    + 'daily_warmup_start = "2022-07"\n'
    'warmup_start = "2023-01"\n'
    'start = "2023-02"\n'
    'end = "2023-02"\n'
    + PRICING
    + """
[[basket_exclusions]]
symbol = "SOLUSDT"
from = "2023-01-01T00:00Z"
to = "2023-02-01T00:00Z"
reason = "synthetic listing: no SOLUSDT archive before 2023-02"
"""
)
TRANSIENT = archive_path("ETHUSDT", "1h", "2023-01")  # fails once in the happy run
MISSING = ("SOLUSDT", "1h", "2022-12")
UNREADABLE = ("LINKUSDT", "1h", "2022-12")
FUNDING = funding_archive_path("BTCUSDT", EVALUATION)


def flat_bars(start_ms: int, end_ms: int, step: int, price: str) -> list[Kline]:
    """Flat bars at ``price``; the volumes scale with the bar's minutes, so every hour is
    the exact aggregate of its minutes and every day of its hours."""
    p, minutes = Decimal(price), step // MINUTE_MS
    volume = Decimal(10 * minutes)
    taker = Decimal(4 * minutes)
    return [Kline(t, p, p, p, p, volume, volume * p, taker) for t in range(start_ms, end_ms, step)]


def csv_text(bars: list[Kline], step: int) -> str:
    """Binance's 12-column CSV rows of ``bars``, each closing on its boundary."""
    return "".join(
        f"{k.open_ms},{k.open},{k.high},{k.low},{k.close},{k.volume},{k.open_ms + step - 1},"
        f"{k.quote_volume},10,{k.taker_buy_base},{k.taker_buy_base * k.close},0\n"
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


def kline_archive(symbol: str, interval: str, month: str, step: int) -> bytes:
    start, end = month_bounds_ms(month)
    text = csv_text(flat_bars(start, end, step, PRICES.get(symbol, "10")), step)
    return zip_of((f"{symbol}-{interval}-{month}.csv", text))


@pytest.fixture(scope="module")
def archives() -> dict[str, bytes]:
    """Every object the fake host publishes, by archive path."""
    objects: dict[str, bytes] = {}
    for symbol in BASKET:
        for month in HOURLY_MONTHS:
            if symbol == "SOLUSDT" and month != EVALUATION:
                continue  # not published before its synthetic listing: a 404
            start, end = month_bounds_ms(month)
            text = csv_text(flat_bars(start, end, HOUR_MS, PRICES.get(symbol, "10")), HOUR_MS)
            # LINKUSDT's first month holds a second member: checksum-valid, but unreadable.
            extra = [("README.txt", "second\n")] if (symbol, "1h", month) == UNREADABLE else []
            body = zip_of((f"{symbol}-1h-{month}.csv", text), *extra)
            serve(objects, archive_path(symbol, "1h", month), body)
    for symbol in TRADED:
        serve(
            objects,
            archive_path(symbol, "1m", EVALUATION),
            kline_archive(symbol, "1m", EVALUATION, MINUTE_MS),
        )
        for month in DAILY_MONTHS:
            serve(
                objects,
                archive_path(symbol, "1d", month),
                kline_archive(symbol, "1d", month, DAY_MS),
            )
    start, end = month_bounds_ms(EVALUATION)
    funding = "calc_time,funding_interval_hours,last_funding_rate\n" + "".join(
        f"{t},8,0.0001\n" for t in range(start, end, 8 * HOUR_MS)
    )
    serve(objects, FUNDING, zip_of((f"BTCUSDT-fundingRate-{EVALUATION}.csv", funding)))
    return objects


class Host:
    """A fake data.binance.vision: objects by path, None (a 404) otherwise. It records every
    request, and raises FeedError the first time each path in ``fail_once`` is requested."""

    def __init__(self, objects: dict[str, bytes], fail_once: set[str]) -> None:
        self.objects = objects
        self.fail_once = set(fail_once)
        self.requests: list[str] = []

    def __call__(self, path: str) -> bytes | None:
        self.requests.append(path)
        if path in self.fail_once:
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
    error: Exception | None
    out: str
    data: Path
    scored: Path
    reported: Path
    host: Host
    sleeps: list[float]
    # (command, spec path, whether its manifest existed) for each backtest CLI call
    cli_calls: list[tuple[str, Path, bool]] = field(default_factory=list)
    # whether the digest file existed when each backtest CLI call started
    digest_before_cli: list[bool] = field(default_factory=list)
    # (dataset, index of its first request, index after its last) for each fetch_dataset
    fetches: list[tuple[str, int, int]] = field(default_factory=list)
    # (dataset, whether it is the scored window) for each verify the script runs
    verified: list[tuple[str, bool]] = field(default_factory=list)
    before: dict[str, str] = field(default_factory=dict)
    after: dict[str, str] = field(default_factory=dict)

    def manifest(self, name: str) -> dict[str, Any]:
        return load_manifest(self.data / f"{name}.manifest.json")

    def fetched(self, name: str) -> list[str]:
        (first, end) = next((a, b) for n, a, b in self.fetches if n == name)
        return self.host.requests[first:end]


def run_script(
    tmp: Path,
    objects: dict[str, bytes],
    fail_once: set[str] | None = None,
    *,
    cli_error: bool = False,
) -> Run:
    """The script's ``main`` with the fake host, from an empty working directory, with every
    network route of the fetch code replaced by an error. With ``cli_error`` every backtest
    CLI call (verify, mask-report) raises instead of running."""
    specs, data, cwd = tmp / "specs", tmp / "data", tmp / "cwd"
    specs.mkdir()
    cwd.mkdir()
    scored, reported = specs / "synthetic-scored.toml", specs / "synthetic-reported.toml"
    scored.write_text(SCORED_SPEC, encoding="utf-8")
    reported.write_text(REPORTED_SPEC, encoding="utf-8")
    run = Run(None, None, "", data, scored, reported, Host(objects, fail_once or set()), [])
    real_cli, real_fetch = fetch_full_range.backtest_cli.main, fetch_full_range.fetch_dataset
    real_verify = fetch_full_range.verify

    def spy_cli(argv: list[str]) -> int:
        spec = Path(argv[argv.index("--spec") + 1])
        run.cli_calls.append((argv[0], spec, manifest_path(spec).is_file()))
        run.digest_before_cli.append((data / "synthetic-scored.digest.txt").is_file())
        if cli_error:
            raise RuntimeError(f"synthetic {argv[0]} failure")
        return real_cli(argv)

    def spy_verify(spec: Any, *args: Any, scored: bool) -> None:
        run.verified.append((spec.name, scored))
        real_verify(spec, *args, scored=scored)

    def spy_fetch(spec: Any, data_dir: Path, **kwargs: Any) -> dict[str, Any]:
        first = len(run.host.requests)
        try:
            return real_fetch(spec, data_dir, **kwargs)
        finally:
            run.fetches.append((spec.name, first, len(run.host.requests)))

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("the fetch code tried to reach the network")

    roots = [tmp, ROOT / "config"]
    run.before = snapshot(roots, data)
    out = io.StringIO()
    argv = [str(data), "--spec", str(scored), "--reported-spec", str(reported), "--jobs", "1"]
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(cwd)
        patch.setattr(fetch_full_range.backtest_cli, "main", spy_cli)
        patch.setattr(fetch_full_range, "fetch_dataset", spy_fetch)
        patch.setattr(fetch_full_range, "verify", spy_verify)
        for name in ("https_connection", "PublicClient", "exchange_filters", "archive_get"):
            patch.setattr(dataset, name, no_network)
        with contextlib.redirect_stdout(out):
            try:
                run.code = fetch_full_range.main(argv, fetcher=run.host, sleep=run.sleeps.append)
            except Exception as exc:
                run.error = exc
    run.out = out.getvalue()
    run.after = snapshot(roots, data)
    return run


@pytest.fixture(scope="module")
def happy(archives: dict[str, bytes], tmp_path_factory: pytest.TempPathFactory) -> Run:
    """The whole run, with one transient transport failure on the way."""
    return run_script(tmp_path_factory.mktemp("happy"), archives, {TRANSIENT})


def identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (entry.get("kind") or entry["interval"], entry["symbol"], entry["month"])


def file_name(symbol: str, interval: str, month: str) -> str:
    return archive_path(symbol, interval, month).rsplit("/", 1)[1]


def digest_row(run: Run, name: str) -> str:
    digest = (run.data / "synthetic-scored.digest.txt").read_text(encoding="utf-8")
    (row,) = [line for line in digest.splitlines() if line.split(" ", 1)[0] == name]
    return row


def committed_filters() -> dict[str, Any]:
    filters = load_manifest(DATASETS / "long-bull-bear-2022.manifest.json")["instruments"]
    return {symbol: filters[symbol] for symbol in TRADED}


def test_the_synthetic_specs_have_the_committed_symbols_basket_and_pricing(tmp_path: Path) -> None:
    committed = load_spec(DATASETS / "full-range-2017-2024.toml")
    for text in (SCORED_SPEC, REPORTED_SPEC):
        path = tmp_path / "spec.toml"
        path.write_text(text, encoding="utf-8")
        spec = load_spec(path)
        for name in ("traded", "market_proxy", "breadth_basket", "initial_quote", "fee_rate"):
            assert getattr(spec, name) == getattr(committed, name)
        for name in ("slippage_rate", "participation", "assumed_spread_pct"):
            assert getattr(spec, name) == getattr(committed, name)
        assert spec.months(spec.start) == [EVALUATION]


def test_fetch_full_range_writes_only_under_data_and_uses_committed_filters(happy: Run) -> None:
    assert (happy.code, happy.error) == (0, None), happy.out
    assert happy.out.splitlines()[-1] == "RESULT 0 problem(s)"
    # No file outside <data-dir> changed, none was added (the working directory stays
    # empty), and the committed specs and manifests are untouched.
    assert happy.after == happy.before
    # Every request is a canonical archive or checksum path of the first spec's plan, for
    # archive_get's fixed host; nothing else was asked for.
    scored = load_spec(happy.scored)
    planned = {archive_path(*f) for f in scored.required()} | {FUNDING}
    planned |= {path + ".CHECKSUM" for path in planned}
    assert set(happy.host.requests) <= planned
    # Every funding month the spec covers is fetched: the evaluation months from 2020-01.
    assert {FUNDING, FUNDING + ".CHECKSUM"} <= set(happy.host.requests)
    # The specs are copied into <data-dir>, and each manifest is written next to its copy
    # before verify and mask-report read it from there.
    for spec in (happy.scored, happy.reported):
        assert (happy.data / spec.name).read_bytes() == spec.read_bytes()
    assert happy.cli_calls == [
        ("verify", happy.data / "synthetic-scored.toml", True),
        ("mask-report", happy.data / "synthetic-scored.toml", True),
        ("verify", happy.data / "synthetic-reported.toml", True),
    ]
    manifest = happy.manifest("synthetic-scored")
    klines = [identity(e) for e in manifest["files"] if not is_funding(e)]
    assert klines == [(i, s, m) for s, i, m in scored.required()]
    funding = [e for e in manifest["files"] if is_funding(e)]
    assert [(e["month"], e["status"], e["records"]) for e in funding] == [(EVALUATION, "ok", 84)]
    assert manifest["files"][-1] == funding[0]  # after the klines, where fetch_dataset keeps them
    # The committed filters, their fetched_at included: no exchangeInfo request was made.
    assert manifest["instruments"] == committed_filters()
    # verify prints "valid", and mask-report prints its JSON; both are kept under <data-dir>.
    verified = json.loads((happy.data / "synthetic-scored.verify.json").read_text("utf-8"))
    assert verified["status"] == "valid"
    assert "VERIFY synthetic-scored exit 0 status valid" in happy.out
    report = json.loads((happy.data / "synthetic-scored.mask-report.json").read_text("utf-8"))
    assert set(report) == {"dataset", "comparison_mask", "xrp_quote_test", "symbols", "totals"}
    assert (report["dataset"], report["totals"]["excluded_months"]) == ("synthetic-scored", 0)
    assert report["xrp_quote_test"]["breaches"] is False
    assert "MASK totals" in happy.out
    assert "MASK XRPUSDT quote test" in happy.out
    # The digest is written once both manifests are, before any check can fail.
    assert happy.digest_before_cli == [True, True, True]
    order = [line.split(" ", 1)[0] for line in happy.out.splitlines()]
    assert order.index("DIGEST") < order.index("VERIFY") < order.index("MASK")


def test_the_committed_specs_are_the_default_plan() -> None:
    assert fetch_full_range.SCORED_SPEC == DATASETS / "full-range-2017-2024.toml"
    assert fetch_full_range.REPORTED_SPEC == DATASETS / "full-range-2019-2024.toml"
    assert fetch_full_range.FILTERS == DATASETS / "long-bull-bear-2022.manifest.json"
    scored = load_spec(fetch_full_range.SCORED_SPEC)
    reported = load_spec(fetch_full_range.REPORTED_SPEC)
    months = fetch_full_range.funding_months(scored)
    assert (len(months), months[0], months[-1]) == (60, "2020-01", "2024-12")
    assert fetch_full_range.funding_months(reported) == months
    assert len(scored.required()) == 1164
    assert len(reported.required()) == 1080
    assert set(reported.required()) <= set(scored.required())
    assert set(fetch_full_range.committed_filters(fetch_full_range.FILTERS)) >= set(TRADED)


def test_a_transient_feed_error_is_retried_and_the_run_completes(happy: Run) -> None:
    assert happy.code == 0
    assert happy.fetched("synthetic-scored").count(TRANSIENT) == 2
    assert happy.sleeps == [1]
    assert f"RETRY attempt 1 of 4 for {TRANSIENT}: synthetic transport failure" in happy.out


def test_a_checksum_mismatch_is_not_retried_and_stops_the_run(
    archives: dict[str, bytes], tmp_path: Path
) -> None:
    objects = dict(archives)
    path = archive_path("BTCUSDT", "1m", EVALUATION)
    serve(objects, path, objects[path], checksum="0" * 64)
    run = run_script(tmp_path, objects)
    assert isinstance(run.error, DataError)
    assert "does not match Binance's published SHA-256" in str(run.error)
    assert run.host.requests.count(path) == 1
    assert run.sleeps == []
    assert not list(run.data.glob("*.manifest.json"))
    assert not local_path(run.data, "BTCUSDT", "1m", EVALUATION).exists()
    # The traceback still leaves the request count and list behind (a finally).
    (requests,) = [line for line in run.out.splitlines() if line.startswith("REQUESTS ")]
    assert requests.startswith(f"REQUESTS {len(run.host.requests)} to data.binance.vision")
    listed = (run.data / "requests.txt").read_text(encoding="utf-8").splitlines()
    assert listed == run.host.requests
    assert "RESULT" not in run.out


def test_a_check_that_raises_keeps_the_digest_and_is_a_problem(
    archives: dict[str, bytes], tmp_path: Path
) -> None:
    """An exception inside verify or mask-report (the backtest CLI) must not lose the
    digest, which is what rebuilds the manifests: it is written before the checks run, and
    each failed check is a PROBLEM naming the step and the exception."""
    run = run_script(tmp_path, archives, cli_error=True)
    assert (run.code, run.error) == (1, None), run.out
    assert [(command, spec.name) for command, spec, _ in run.cli_calls] == [
        ("verify", "synthetic-scored.toml"),
        ("mask-report", "synthetic-scored.toml"),
        ("verify", "synthetic-reported.toml"),
    ]
    digest = run.data / "synthetic-scored.digest.txt"
    assert run.digest_before_cli == [True, True, True]
    sha256 = hashlib.sha256(digest.read_bytes()).hexdigest()
    (line,) = [line for line in run.out.splitlines() if line.startswith("DIGEST ")]
    assert f"sha256 {sha256}; rebuilds both manifests byte for byte: True" in line
    lines = run.out.splitlines()
    assert [line for line in lines if line.startswith("PROBLEM ")] == [
        "PROBLEM verify of synthetic-scored raised RuntimeError: synthetic verify failure",
        "PROBLEM mask-report of synthetic-scored raised RuntimeError: synthetic mask-report "
        "failure",
        "PROBLEM verify of synthetic-reported raised RuntimeError: synthetic verify failure",
    ]
    assert any(line.startswith("REQUESTS ") for line in lines)
    assert any(line.startswith("REPORT ") for line in lines)
    assert lines[-1] == "RESULT 3 problem(s)"
    # Each failure's traceback is in the log, for the report.
    assert run.out.count("Traceback (most recent call last):") == 3


def test_a_missing_funding_month_stops_before_any_manifest_is_written(
    archives: dict[str, bytes], tmp_path: Path
) -> None:
    objects = {p: b for p, b in archives.items() if not p.startswith(FUNDING)}
    run = run_script(tmp_path, objects)
    assert (run.code, run.error) == (1, None)
    assert f"FUNDING {EVALUATION} missing" in run.out
    stop = [line for line in run.out.splitlines() if line.startswith("STOP")]
    assert len(stop) == 1 and EVALUATION in stop[0]
    assert not list(run.data.glob("*.manifest.json"))
    assert run.fetches == []  # no kline was requested
    assert run.out.splitlines()[-1] == "RESULT 1 problem(s)"


def test_a_pre_listing_404_is_a_missing_row_that_rebuilds(happy: Run) -> None:
    name = file_name(*MISSING)
    assert digest_row(happy, name) == f"{name} missing"
    rebuilt = fetch_full_range.rebuild(
        (happy.data / "synthetic-scored.digest.txt").read_text("utf-8"),
        load_spec(happy.scored),
        load_spec(happy.reported),
        committed_filters(),
    )
    (entry,) = [
        e
        for e in happy.manifest("synthetic-scored")["files"]
        if identity(e) == ("1h", "SOLUSDT", "2022-12")
    ]
    assert entry["status"] == "missing"
    assert [e for e in rebuilt[0]["files"] if identity(e) == identity(entry)] == [entry]


def test_a_two_member_archive_is_an_unreadable_row_that_rebuilds(happy: Run) -> None:
    files = happy.manifest("synthetic-scored")["files"]
    (entry,) = [e for e in files if identity(e) == ("1h", "LINKUSDT", "2022-12")]
    reason = "archive must contain exactly LINKUSDT-1h-2022-12.csv"
    assert (entry["status"], entry["reason"]) == ("unreadable", reason)
    name = file_name(*UNREADABLE)
    assert digest_row(happy, name) == (
        f'{name} {entry["sha256"]} unreadable {entry["bytes"]} "{reason}"'
    )
    scored, reported = load_spec(happy.scored), load_spec(happy.reported)
    digest = (happy.data / "synthetic-scored.digest.txt").read_text("utf-8")
    first, second = fetch_full_range.rebuild(digest, scored, reported, committed_filters())
    assert [e for e in first["files"] if identity(e) == identity(entry)] == [entry]
    dataset._validate_manifest(first)
    dataset._validate_manifest(second)
    # The digest rebuilds both manifests whole, as the script checks byte for byte.
    assert first == happy.manifest("synthetic-scored")
    assert second == happy.manifest("synthetic-reported")
    assert "rebuilds both manifests byte for byte: True" in happy.out


def test_the_reported_manifest_is_a_subset_with_nothing_downloaded_again(happy: Run) -> None:
    first, second = happy.manifest("synthetic-scored"), happy.manifest("synthetic-reported")
    reported = load_spec(happy.reported)
    klines = [identity(e) for e in second["files"] if not is_funding(e)]
    assert klines == [(i, s, m) for s, i, m in reported.required()]
    by_file = {identity(e): e for e in first["files"]}
    assert all(entry == by_file[identity(entry)] for entry in second["files"])
    assert [e for e in second["files"] if is_funding(e)] == [
        e for e in first["files"] if is_funding(e)
    ]
    # Only .CHECKSUM requests, besides the archive of a file Binance does not publish (its
    # checksum is a 404, so _fetch_verified asks for the archive too): no stored archive is
    # downloaded again.
    missing = {
        archive_path(e["symbol"], e["interval"], e["month"])
        for e in second["files"]
        if e["status"] == "missing"
    }
    assert missing == {archive_path("SOLUSDT", "1h", "2023-01")}
    requests = happy.fetched("synthetic-reported")
    assert {p for p in requests if not p.endswith(".CHECKSUM")} == missing
    assert len([p for p in requests if p.endswith(".CHECKSUM")]) == len(second["files"])
    verified = json.loads((happy.data / "synthetic-reported.verify.json").read_text("utf-8"))
    assert verified["status"] == "valid"
    assert "every entry equals synthetic-scored's: True" in happy.out
    # Only the scored window's pair shortfall can stop the run (spec v1 section 5 rule 6).
    assert happy.verified == [("synthetic-scored", True), ("synthetic-reported", False)]


def test_mask_report_summary_lists_each_masked_month_and_flags_an_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec_path = tmp_path / "synthetic-scored.toml"
    spec_path.write_text(SCORED_SPEC, encoding="utf-8")
    hours = {"expected_hours": 672, "open_only_hours": 0, "excluded": False}
    clean = {**hours, "month": "2023-01", "masked_hours": 0, "real_defect_share": "0"}
    masked = {**hours, "month": "2023-02", "masked_hours": 3, "real_defect_share": "1/224"}
    excluded = {**masked, "masked_hours": 672, "real_defect_share": "1/4", "excluded": True}
    report = {
        "dataset": "synthetic-scored",
        "comparison_mask": {},
        "xrp_quote_test": None,
        "symbols": {"BTCUSDT": {"months": [clean, masked]}, "BNBUSDT": {"months": [excluded]}},
        "totals": {"symbols_with_a_mask": 2, "masked_hours": 675, "excluded_months": 1},
    }
    monkeypatch.setattr(fetch_full_range, "cli", lambda *args: (0, json.dumps(report)))
    lines: list[str] = []
    problems: list[str] = []
    spec = load_spec(spec_path)
    fetch_full_range.mask_report(spec, spec_path, tmp_path, 1, lines.append, problems)
    assert lines[1:] == [
        "MASK totals symbols_with_a_mask=2 masked_hours=675 excluded_months=1",
        "MASK XRPUSDT quote test: not run, XRPUSDT is not traded",
        "MASK symbol-months with a masked hour or an exclusion: 2",
        "MASK BTCUSDT 2023-02 masked 3/672 open-only 0 share 1/224 excluded False",
        "MASK BNBUSDT 2023-02 masked 672/672 open-only 0 share 1/4 excluded True",
    ]
    assert problems == [
        "mask-report excludes 1 symbol-month(s) under the 17% rule: BNBUSDT 2023-02"
    ]


def test_too_few_pairs_is_a_problem_in_the_scored_window_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec v1 section 5: each window must keep 2 included pairs, but rule 6 says the
    reported window falling short decides nothing. So a shortfall there is logged and the
    run goes on, while the scored window's is a problem, which stops Bob."""
    spec_path = tmp_path / "synthetic-scored.toml"
    spec_path.write_text(SCORED_SPEC, encoding="utf-8")
    spec = load_spec(spec_path)
    rule_8 = {"XRPUSDT": ["XRPUSDT: tick_limit_quotes=2"]}
    shortfall = {**rule_8, "ETHUSDT": ["ETHUSDT: hours_mismatched=3"]}
    outcomes = {}
    for excluded in (rule_8, shortfall):
        text = json.dumps({"status": "valid", "failures": [], "excluded_pairs": excluded})
        monkeypatch.setattr(fetch_full_range, "cli", lambda *args, text=text: (0, text))
        for scored in (True, False):
            lines: list[str] = []
            problems: list[str] = []
            fetch_full_range.verify(
                spec, spec_path, tmp_path, 1, lines.append, problems, scored=scored
            )
            outcomes[len(excluded), scored] = (lines, problems)
            for pair, reasons in excluded.items():
                assert f"VERIFY synthetic-scored excluded {pair}: {reasons[0]}" in lines
    # XRPUSDT alone excluded under rule 8 leaves BTC and ETH: a finding in either window.
    for scored in (True, False):
        lines, problems = outcomes[1, scored]
        assert problems == []
        assert "included pairs 2 of 3: BTCUSDT, ETHUSDT;" in lines[0]
        assert len(lines) == 2  # the VERIFY line and XRPUSDT's exclusion
    lines, problems = outcomes[2, True]
    assert problems == ["synthetic-scored keeps 1 included pair(s); spec v1 section 5 needs 2"]
    assert "included pairs 1 of 3: BTCUSDT;" in lines[0]
    lines, problems = outcomes[2, False]
    assert problems == []
    assert "included pairs 1 of 3: BTCUSDT;" in lines[0]
    assert lines[-1] == (
        "VERIFY synthetic-scored keeps 1 included pair(s), fewer than 2: reported, not a "
        "problem, since this window decides nothing (spec v1 section 5 rule 6)"
    )


def test_the_digest_rows_name_each_file_and_only_what_differs_from_a_complete_month() -> None:
    feb_start, feb_end = month_bounds_ms("2023-02")
    base = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "month": "2023-02",
        "url": "https://data.binance.vision" + archive_path("BTCUSDT", "1h", "2023-02"),
        "status": "ok",
        "sha256": "a" * 64,
        "bytes": 41234,
        "rows": 672,
        "expected_rows": 672,
        "missing_rows": 0,
        "gaps": 0,
        "first_open_ms": feb_start,
        "last_open_ms": feb_end - HOUR_MS,
        "timestamp_units": ["ms"],
    }
    row = fetch_full_range.digest_row
    assert row(base) == f"BTCUSDT-1h-2023-02.zip {'a' * 64} ok 41234 full"
    partial = {
        **base,
        "rows": 670,
        "missing_rows": 2,
        "gaps": 1,
        "first_open_ms": feb_start + 2 * HOUR_MS,
    }
    assert row(partial) == (
        f"BTCUSDT-1h-2023-02.zip {'a' * 64} ok 41234 rows=670 gaps=1 "
        f"first_open_ms={feb_start + 2 * HOUR_MS}"
    )
    mixed = {**base, "timestamp_units": ["ms", "us"]}
    assert row(mixed).endswith(' ok 41234 timestamp_units=["ms","us"]')
    empty = {
        **base,
        "rows": 0,
        "missing_rows": 672,
        "gaps": 1,
        "first_open_ms": None,
        "last_open_ms": None,
        "timestamp_units": [],
    }
    assert row(empty).endswith(
        " rows=0 gaps=1 first_open_ms=null last_open_ms=null timestamp_units=[]"
    )
    identity_only = {k: base[k] for k in ("symbol", "interval", "month", "url")}
    assert row({**identity_only, "status": "missing"}) == "BTCUSDT-1h-2023-02.zip missing"
    unreadable = {
        **identity_only,
        "status": "unreadable",
        "sha256": "b" * 64,
        "bytes": 9,
        "reason": 'bad "zip"\n',
    }
    assert row(unreadable) == f'BTCUSDT-1h-2023-02.zip {"b" * 64} unreadable 9 "bad \\"zip\\"\\n"'
    funding = {
        "kind": "fundingRate",
        "symbol": "BTCUSDT",
        "month": "2020-01",
        "url": "https://data.binance.vision" + funding_archive_path("BTCUSDT", "2020-01"),
        "status": "ok",
        "sha256": "c" * 64,
        "bytes": 2817,
        "records": 93,
    }
    assert row(funding) == f"BTCUSDT-fundingRate-2020-01.zip {'c' * 64} ok 2817 records=93"
    for entry in (
        base,
        partial,
        mixed,
        empty,
        unreadable,
        {**identity_only, "status": "missing"},
        funding,
    ):
        assert fetch_full_range.entry_of(row(entry)) == entry


def full_size_manifests() -> tuple[dict[str, Any], dict[str, Any]]:
    """Both committed windows' manifests as a real fetch could write them, for the digest's
    size: every archive has a SHA-256 and a byte count of its interval's typical width (7
    digits for 1m, 5 for 1h, 4 for 1d and funding). The pre-listing months of SOLUSDT,
    DOGEUSDT and LINKUSDT are missing, the four listing months are partial, and 108 more
    archives (82 1h and 26 1m, as #156's unparsed ones) differ from a complete month in
    every field but the units, the longest row the format writes."""
    scored = load_spec(fetch_full_range.SCORED_SPEC)
    reported = load_spec(fetch_full_range.REPORTED_SPEC)
    listing = {"SOLUSDT": "2020-08", "DOGEUSDT": "2019-07", "LINKUSDT": "2019-01"}
    listing["TRXUSDT"] = "2018-06"
    required = scored.required()
    missing = {f for f in required if f[1] == "1h" and f[2] < listing.get(f[0], "0000-00")}
    partial = {f for f in required if f[1] == "1h" and f[2] == listing.get(f[0])}
    hourly = [f for f in required if f[1] == "1h" and f not in missing | partial]
    minute = [f for f in required if f[1] == "1m"]
    damaged = set(hourly[::8][:82]) | set(minute[::8][:26])
    assert (len(missing), len(partial), len(damaged)) == (46, 4, 108)
    width = {"1m": 2_345_678, "1h": 45_678, "1d": 2_345}
    files = []
    for number, (symbol, interval, month) in enumerate(required):
        entry: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "month": month,
            "url": "https://data.binance.vision" + archive_path(symbol, interval, month),
        }
        if (symbol, interval, month) in missing:
            files.append({**entry, "status": "missing"})
            continue
        start, end = month_bounds_ms(month)
        step = {"1m": MINUTE_MS, "1h": HOUR_MS, "1d": DAY_MS}[interval]
        rows = (end - start) // step
        stats = {"rows": rows, "gaps": 0, "first_open_ms": start, "last_open_ms": end - step}
        if (symbol, interval, month) in partial | damaged:
            stats = {
                "rows": rows - 17,
                "gaps": 3,
                "first_open_ms": start + step,
                "last_open_ms": end - 2 * step,
            }
        files.append(
            {
                **entry,
                "status": "ok",
                "sha256": hashlib.sha256(f"{symbol}{interval}{month}".encode()).hexdigest(),
                "bytes": width[interval] + number,
                "expected_rows": rows,
                "missing_rows": rows - stats["rows"],
                "timestamp_units": ["ms"],
                **stats,
            }
        )
    funding = [
        {
            "kind": "fundingRate",
            "symbol": "BTCUSDT",
            "month": month,
            "url": "https://data.binance.vision" + funding_archive_path("BTCUSDT", month),
            "status": "ok",
            "sha256": hashlib.sha256(month.encode()).hexdigest(),
            "bytes": 2_800 + number,
            "records": 93,
        }
        for number, month in enumerate(fetch_full_range.funding_months(scored))
    ]
    by_file = {(e["symbol"], e["interval"], e["month"]): e for e in files}
    filters = committed_filters()

    def manifest(spec: Any, kline: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schema": 1,
            "dataset": spec.name,
            "source": "https://data.binance.vision",
            "created_at": "2026-10-08T12:34:56+00:00",
            "instruments": filters,
            "files": kline + funding,
        }

    return manifest(scored, files), manifest(reported, [by_file[f] for f in reported.required()])


def test_a_full_size_digest_rebuilds_both_manifests_and_fits_the_report() -> None:
    first, second = full_size_manifests()
    assert (len(first["files"]), len(second["files"])) == (1164 + 60, 1080 + 60)
    hashes = {first["dataset"]: "d" * 64, second["dataset"]: "e" * 64}
    digest = fetch_full_range.digest_text(first, second, hashes)
    scored = load_spec(fetch_full_range.SCORED_SPEC)
    reported = load_spec(fetch_full_range.REPORTED_SPEC)
    assert fetch_full_range.rebuild(digest, scored, reported, committed_filters()) == (
        first,
        second,
    )
    lines = digest.splitlines()
    assert len(lines) == 3 + 1164 + 60
    assert lines[1] == (
        f"manifest full-range-2017-2024 created_at 2026-10-08T12:34:56+00:00 files 1224 "
        f"sha256 {'d' * 64}"
    )
    # Well inside the 190,000 bytes above which Bob stops (validate_bob_artifact.py rejects
    # a report over 200,000), with room for the run log and the hand-written passages.
    assert len(digest.encode("utf-8")) < 150_000


def test_requests_outside_the_plan_are_refused_and_retries_are_bounded() -> None:
    planned = archive_path("BTCUSDT", "1h", "2024-12")
    outages: list[str] = []

    def down(path: str) -> bytes | None:
        outages.append(path)
        raise FeedError("down")

    sleeps: list[float] = []
    lines: list[str] = []
    requests = fetch_full_range.Requests(down, {planned}, sleeps.append, lines.append)
    with pytest.raises(FeedError):
        requests(planned)
    assert (outages, sleeps) == ([planned] * 4, [1, 2, 4])
    assert [line.split(":")[0] for line in lines] == [
        f"RETRY attempt {n} of 4 for {planned}" for n in (1, 2, 3, 4)
    ]
    for path in (archive_path("BTCUSDT", "1h", "2025-01"), "/data/spot/monthly/klines/BTCUSDT/1h/"):
        with pytest.raises(fetch_full_range.OutOfScope):
            requests(path)
    assert outages == [planned] * 4  # a refused path never reaches the fetcher
    assert requests.paths == [planned] * 4


# --- start and wait: the script runs itself in the background (Step 4) ---------------------
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
    assert fetch_full_range.main(["wait", str(data)]) == 1
    assert capsys.readouterr().out.startswith("NOT STARTED")
    assert fetch_full_range.main(["start", str(data), "--fake-run", "0.2"]) == 0
    pid = int((data / "run.pid").read_text(encoding="utf-8"))
    log, exit_file = (data / "run.log").as_posix(), (data / "run.exit").as_posix()
    assert capsys.readouterr().out == f"STARTED pid {pid}; log {log}; exit file {exit_file}\n"
    assert fetch_full_range.main(["wait", str(data)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert (lines[0], lines[-1]) == ("DONE exit=0", "RESULT 0 problem(s)")
    assert (data / "run.exit").read_text(encoding="utf-8") == "0\n"
    # A run that has ended is never started again in the same data dir.
    assert fetch_full_range.main(["start", str(data), "--fake-run", "0.2"]) == 1
    assert capsys.readouterr().out.startswith("NOT STARTED")


def test_wait_returns_running_within_its_limit_then_done_with_the_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    data = tmp_path / "data"
    assert fetch_full_range.main(["start", str(data), "--fake-run", "4", "--fake-raise"]) == 0
    capsys.readouterr()
    background(monkeypatch, 0.5)
    began = time.monotonic()
    assert fetch_full_range.main(["wait", str(data)]) == 0
    assert time.monotonic() - began < 3.5  # it returns at its limit, not when the run ends
    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("RUNNING pid ")
    assert line.endswith("latest: FAKE run: 4.0 s") or line.endswith("latest: no output yet")
    # A second start while the first runs is refused.
    assert fetch_full_range.main(["start", str(data), "--fake-run", "0.2"]) == 1
    assert "still running" in capsys.readouterr().out
    background(monkeypatch, 60)
    assert fetch_full_range.main(["wait", str(data)]) == 0
    lines = capsys.readouterr().out.splitlines()
    # A run that ends in a traceback still writes its exit file: DONE, not GONE.
    assert lines[0] == "DONE exit=1"
    assert lines[-1] == "RuntimeError: fake run failure"


def test_wait_reports_a_run_gone_without_an_exit_file_and_start_runs_once_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    background(monkeypatch, 60)
    data = tmp_path / "data"
    data.mkdir()
    ended = subprocess.Popen([sys.executable, "-c", "pass"])  # nosec B603: a fixed command
    ended.wait()
    (data / "run.pid").write_text(f"{ended.pid}\n", encoding="utf-8")
    (data / "run.log").write_text("PLAN first attempt\n", encoding="utf-8")
    assert fetch_full_range.main(["wait", str(data)]) == 1
    assert capsys.readouterr().out == (
        f"GONE pid {ended.pid}: no process and no exit file; latest: PLAN first attempt\n"
    )
    # start runs it once more, unchanged, and keeps the first attempt's log.
    assert fetch_full_range.main(["start", str(data), "--fake-run", "0.2"]) == 0
    capsys.readouterr()
    assert (data / "run-1.log").read_text(encoding="utf-8") == "PLAN first attempt\n"
    assert fetch_full_range.main(["wait", str(data)]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "DONE exit=0"
