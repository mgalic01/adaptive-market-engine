"""Bob's fetch of stage 2's long windows, full-range-2017-2024 and full-range-2019-2024.

    python scripts/fetch_full_range.py <data-dir> [--spec PATH] [--reported-spec PATH]
        [--jobs N]

Task:docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md (long-window data plan, Task
9). IBM Bob runs it on a GitHub Actions machine: Bob is the only actor allowed to reach
data.binance.vision. Every file it writes lands under ``<data-dir>``, which the task puts
in the git-ignored ``data/``, since bob-task.yml refuses any change but Bob's new report.
The defaults are the committed specs; ``--spec`` and ``--reported-spec`` exist for the
tests, which run it on small synthetic specs against a fake host. ``--jobs`` is the
backtest CLI's, for verify and mask-report.

What it does, in order (spec v1 sections 4 and 5; P8 for the funding archives):

1. **Plan, before any request.** Loads the scored spec and the reported one and stops
   unless the reported spec's kline files are all in the scored spec's, both need the same
   funding months, the committed filters cover every traded pair and no planned month is
   after 2024-12. Copies both specs into ``<data-dir>``, so that each manifest is written
   next to its copy (``jobs.manifest_path``) and never into config/datasets.
2. **Funding.** BTCUSDT's funding archives, with ``fetch_funding_file``: the evaluation
   months from 2020-01, where the archives begin (60 for the committed specs). Every month
   must be ok. A 404 gives a missing entry, which ``verify_dataset`` accepts and
   mask-report never exercises, while ``load_funding`` refuses it for G and the full
   stack. So a month that is not ok stops the run here, naming it, before any kline
   request and before any manifest is written.
3. **The scored manifest.** ``fetch_dataset`` fetches and verifies every kline file the
   spec's ``required()`` lists, with the exchange filters of the committed
   long-bull-bear-2022 manifest instead of an exchangeInfo request to
   data-api.binance.vision, which Bob's prompt forbids. ``fetch_dataset`` stamps the
   filters with the current time, so their committed ``fetched_at`` is restored. The
   funding entries go after the klines, where ``fetch_dataset`` keeps a manifest's funding
   entries, and ``write_manifest`` writes the whole atomically before anything reads it.
4. **Its checks.** ``verify`` and ``mask-report`` (the backtest CLI, in this process) load
   that manifest from disk. Their JSON stays under ``<data-dir>``. The log prints
   verify's status, failures and excluded pairs, and mask-report's totals, every
   symbol-month with a masked hour or an exclusion, and XRPUSDT's actual-quotes line.
5. **The reported manifest.** ``fetch_dataset`` for the reported spec on the same
   ``<data-dir>``, with the scored manifest as ``previous``, so its funding entries are
   kept. A stored archive whose SHA-256 matches its .CHECKSUM is reused, so only .CHECKSUM
   requests go out, besides the archive request of a file Binance does not publish. Every
   entry must equal the scored manifest's for the same file; only then is the manifest
   written and verified.
6. **The digest** of both manifests (format below). The script rebuilds both manifests
   from it (``rebuild``) and compares them with the written ones byte for byte.

Every request goes through ``Requests``. Only the planned archive and .CHECKSUM paths
pass; any other raises ``OutOfScope`` before the fetcher is called. A ``FeedError`` (a
transport failure, or an HTTP status other than 200 and 404) is retried with backoff, up
to ``ATTEMPTS`` attempts, as ``audit_run._fetch`` retries: ``archive_get`` retries
nothing, and one transient failure in about 2,450 requests would end the run. A checksum
mismatch is a ``DataError`` raised after the request has returned, so it is never retried
and ends the run with a traceback.

The log ends with one ``PROBLEM`` line per problem and ``RESULT <n> problem(s)``; the exit
status is 0 only with none. The problems: a stop (``STOP`` line), verify not valid, a
scored window left with fewer than 2 included pairs, a symbol-month that mask-report
excludes under the 17% rule, a digest that does not rebuild both manifests, and a run log
and digest over ``REPORT_LIMIT`` bytes together. The reported window's included pairs are
logged, but too few of them is no problem: that window decides nothing (spec v1 section 5
rule 6).

**The digest, format v1:** one line each, its fields separated by single spaces.

* ``digest of <scored> and <reported>, format v1 (scripts/fetch_full_range.py)``;
* ``manifest <dataset> created_at <time> files <n> sha256 <hex>``, once per manifest;
* one row per file of the scored manifest, in its order: the file name, then
  * ``missing``, for a missing archive: its entry has no SHA-256, size or statistics;
  * ``<sha256> unreadable <bytes> <reason>``, the reason as a JSON string;
  * ``<sha256> ok <bytes> full``, for a kline archive with a complete month's statistics:
    rows equal to the expected rows, no gaps, the first and last opens at the month's
    bounds, and timestamp units ``["ms"]``;
  * ``<sha256> ok <bytes> <field>=<value> ...`` for any other kline archive: each of
    ``STATS`` that differs from a complete month, its value as compact JSON. A complete
    month's ``expected_rows`` always holds, and ``missing_rows`` is expected less rows;
  * ``<sha256> ok <bytes> records=<n>``, for a funding archive.

The reported manifest holds the rows of its spec's ``required()`` files, in that order,
then the same funding rows. Every other field of both manifests follows from the specs and
the committed filters.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest import __main__ as backtest_cli
from crypto_grid_bot.backtest.dataset import (
    ARCHIVE_HOST,
    FUNDING_KIND,
    MANIFEST_SCHEMA,
    DatasetSpec,
    Fetcher,
    archive_get,
    archive_path,
    fetch_dataset,
    fetch_funding_file,
    funding_archive_path,
    is_funding,
    load_manifest,
    load_spec,
    sha256_file,
    write_manifest,
)
from crypto_grid_bot.backtest.funding import FIRST_ARCHIVE_MONTH
from crypto_grid_bot.backtest.jobs import manifest_path
from crypto_grid_bot.backtest.klines import INTERVAL_MS, month_bounds_ms
from crypto_grid_bot.backtest.window import DEVELOPMENT_END
from crypto_grid_bot.market_data.client import FeedError

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "config" / "datasets"
SCORED_SPEC = DATASETS / "full-range-2017-2024.toml"
REPORTED_SPEC = DATASETS / "full-range-2019-2024.toml"
# The committed exchange filters of BTCUSDT, ETHUSDT and XRPUSDT, with their fetched_at.
FILTERS = DATASETS / "long-bull-bear-2022.manifest.json"
CONFIG = ROOT / "config" / "default.toml"
FUNDING_SYMBOL = "BTCUSDT"  # variant G reads it for every pair (spec v1 section 3 G)
ATTEMPTS = 4
# Bob stops above this many bytes of run log and digest: validate_bob_artifact.py rejects
# a report over 200,000 bytes, and the hand-written passages need the rest.
REPORT_LIMIT = 190_000
MINIMUM_PAIRS = 2  # spec v1 section 5, "Minimum evidence"
# The statistics a digest row gives where they differ from a complete month's.
STATS = ("rows", "gaps", "first_open_ms", "last_open_ms", "timestamp_units")
_KLINE_NAME = re.compile(r"([A-Z0-9]{2,24})-(1m|1h|1d)-(\d{4}-\d{2})\.zip")
_FUNDING_NAME = re.compile(r"([A-Z0-9]{2,24})-fundingRate-(\d{4}-\d{2})\.zip")
_PATH_MONTH = re.compile(r"-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?$")


class OutOfScope(BaseException):
    """A request outside the plan. A BaseException, so that no handler for Exception,
    DataError or FeedError can swallow it."""


class Stop(Exception):
    """A condition that ends the run before its next step; the message says which."""


class Log:
    """Prints each line at once and counts the bytes printed, for the report's size."""

    def __init__(self) -> None:
        self.bytes = 0

    def __call__(self, line: str) -> None:
        print(line, flush=True)
        self.bytes += len(line.encode("utf-8")) + 1


class Requests:
    """The fetcher every request goes through: planned paths only, and bounded retries of a
    ``FeedError``. ``paths`` lists every attempt, in order."""

    def __init__(
        self,
        fetcher: Fetcher,
        planned: set[str],
        sleep: Callable[[float], None],
        log: Callable[[str], None],
    ) -> None:
        self.fetcher = fetcher
        self.planned = planned
        self.sleep = sleep
        self.log = log
        self.paths: list[str] = []

    def __call__(self, path: str) -> bytes | None:
        if path not in self.planned:
            raise OutOfScope(f"not a planned archive or checksum path: {path}")
        for attempt in range(1, ATTEMPTS + 1):
            self.paths.append(path)
            try:
                return self.fetcher(path)
            except FeedError as exc:
                self.log(f"RETRY attempt {attempt} of {ATTEMPTS} for {path}: {exc}")
                if attempt == ATTEMPTS:
                    raise
                self.sleep(2 ** (attempt - 1))
        raise AssertionError("unreachable")


@dataclass(frozen=True)
class Plan:
    scored: DatasetSpec
    reported: DatasetSpec
    # The specs' copies in <data-dir>; each manifest is written next to its copy.
    scored_copy: Path
    reported_copy: Path
    funding_months: list[str]
    filters: dict[str, dict[str, Any]]
    paths: set[str]


def funding_months(spec: DatasetSpec) -> list[str]:
    """BTCUSDT's funding months a window needs: its evaluation months from 2020-01, where
    the archives begin (spec v1 section 4 and P8), the months ``load_funding`` asks for."""
    return [month for month in spec.months(spec.start) if month >= FIRST_ARCHIVE_MONTH]


def committed_filters(path: Path) -> dict[str, dict[str, Any]]:
    """The exchange filters a committed manifest records, by symbol."""
    return dict(load_manifest(path)["instruments"])


def kline_file(symbol: str, interval: str, month: str) -> str:
    return archive_path(symbol, interval, month).rsplit("/", 1)[1]


def file_name(entry: dict[str, Any]) -> str:
    if is_funding(entry):
        return funding_archive_path(entry["symbol"], entry["month"]).rsplit("/", 1)[1]
    return kline_file(entry["symbol"], entry["interval"], entry["month"])


def identity(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        entry["kind"] if is_funding(entry) else entry["interval"],
        entry["symbol"],
        entry["month"],
    )


def complete_stats(interval: str, month: str) -> dict[str, Any]:
    """The statistics of a kline archive that holds every bar of its month, once."""
    start, end = month_bounds_ms(month)
    step = INTERVAL_MS[interval]
    return {
        "rows": (end - start) // step,
        "gaps": 0,
        "first_open_ms": start,
        "last_open_ms": end - step,
        "timestamp_units": ["ms"],
    }


def _compact(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def digest_row(entry: dict[str, Any]) -> str:
    """One manifest entry as a digest row (the module docstring's format)."""
    name = file_name(entry)
    if entry["status"] == "missing":
        return f"{name} missing"
    head = f"{name} {entry['sha256']} {entry['status']} {entry['bytes']}"
    if is_funding(entry):
        return f"{head} records={entry['records']}"
    if entry["status"] == "unreadable":
        return f"{head} {json.dumps(entry['reason'])}"
    complete = complete_stats(entry["interval"], entry["month"])
    # Compared in their JSON form, as the manifest file holds them (a tuple is a list).
    differing = [
        f"{field}={_compact(entry[field])}"
        for field in STATS
        if json.loads(_compact(entry[field])) != complete[field]
    ]
    return f"{head} {' '.join(differing) or 'full'}"


def entry_of(row: str) -> dict[str, Any]:
    """The manifest entry a digest row stands for; ValueError for a malformed row."""
    name, rest = row.split(" ", 1)
    kline, funding = _KLINE_NAME.fullmatch(name), _FUNDING_NAME.fullmatch(name)
    if kline is not None:
        symbol, interval, month = kline.groups()
        path = archive_path(symbol, interval, month)
        entry: dict[str, Any] = {"symbol": symbol, "interval": interval, "month": month}
    elif funding is not None:
        symbol, month = funding.groups()
        path = funding_archive_path(symbol, month)
        entry = {"kind": FUNDING_KIND, "symbol": symbol, "month": month}
    else:
        raise ValueError(f"not an archive name: {name!r}")
    entry["url"] = f"https://{ARCHIVE_HOST}{path}"
    if rest == "missing":
        return {**entry, "status": "missing"}
    sha256, status, size, tail = rest.split(" ", 3)
    entry |= {"status": status, "sha256": sha256, "bytes": int(size)}
    if funding is not None:
        if status != "ok" or not tail.startswith("records="):
            raise ValueError(f"not a funding row: {row!r}")
        return {**entry, "records": int(tail.removeprefix("records="))}
    if status == "unreadable":
        return {**entry, "reason": json.loads(tail)}
    if status != "ok":
        raise ValueError(f"unknown status in {row!r}")
    complete = complete_stats(entry["interval"], entry["month"])
    stats = dict(complete)
    if tail != "full":
        for token in tail.split(" "):
            field, _, value = token.partition("=")
            if field not in STATS:
                raise ValueError(f"unknown field {field!r} in {row!r}")
            stats[field] = json.loads(value)
    expected = complete["rows"]
    return {**entry, **stats, "expected_rows": expected, "missing_rows": expected - stats["rows"]}


def digest_text(first: dict[str, Any], second: dict[str, Any], hashes: dict[str, str]) -> str:
    """The digest of the scored manifest ``first`` and the reported ``second``, each as its
    file holds it; ``hashes`` are the two files' SHA-256, by dataset name."""
    lines = [
        f"digest of {first['dataset']} and {second['dataset']}, format v1 "
        "(scripts/fetch_full_range.py)"
    ]
    for manifest in (first, second):
        lines.append(
            f"manifest {manifest['dataset']} created_at {manifest['created_at']} "
            f"files {len(manifest['files'])} sha256 {hashes[manifest['dataset']]}"
        )
    lines += [digest_row(entry) for entry in first["files"]]
    return "\n".join(lines) + "\n"


def rebuild(
    digest: str, scored: DatasetSpec, reported: DatasetSpec, filters: dict[str, dict[str, Any]]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Both manifests from the digest, the specs and the committed filters."""
    created: dict[str, str] = {}
    rows: dict[str, dict[str, Any]] = {}
    for line in digest.splitlines()[1:]:
        if line.startswith("manifest "):
            fields = line.split(" ")
            created[fields[1]] = fields[3]
            continue
        name = line.split(" ", 1)[0]
        if name in rows:
            raise ValueError(f"the digest lists {name} twice")
        rows[name] = entry_of(line)
    funding = [entry for entry in rows.values() if is_funding(entry)]
    klines = {name for name, entry in rows.items() if not is_funding(entry)}
    if klines != {kline_file(*f) for f in scored.required()}:
        raise ValueError(f"the digest's kline rows are not {scored.name}'s files")

    def manifest(spec: DatasetSpec) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "dataset": spec.name,
            "source": f"https://{ARCHIVE_HOST}",
            "created_at": created[spec.name],
            "instruments": {symbol: dict(filters[symbol]) for symbol in spec.traded},
            "files": [rows[kline_file(*f)] for f in spec.required()] + funding,
        }

    return manifest(scored), manifest(reported)


def _kline_counts(spec: DatasetSpec) -> str:
    files = spec.required()
    counts = Counter(interval for _, interval, _ in files)
    return f"{len(files)} kline files ({', '.join(f'{i} {n}' for i, n in counts.items())})"


def _shown(path: Path) -> str:
    """A path as the log names it: relative to the repository when it lies inside."""
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def make_plan(args: argparse.Namespace, log: Log) -> Plan:
    """Everything decided before the first request (step 1 of the module docstring)."""
    scored, reported = load_spec(args.spec), load_spec(args.reported_spec)
    if scored.name == reported.name or args.spec.name == args.reported_spec.name:
        raise Stop("the scored and the reported spec need different names")
    if not set(reported.required()) <= set(scored.required()):
        raise Stop(f"{reported.name}'s kline files are not all in {scored.name}'s")
    months = funding_months(scored)
    if funding_months(reported) != months:
        raise Stop(f"{reported.name} and {scored.name} need different funding months")
    filters = committed_filters(FILTERS)
    lacking = sorted({*scored.traded, *reported.traded} - set(filters))
    if lacking:
        raise Stop(f"{_shown(FILTERS)} has no exchange filters for {', '.join(lacking)}")
    latest = max([month for _, _, month in scored.required()] + months)
    if latest > DEVELOPMENT_END:
        raise OutOfScope(f"planned month {latest} is after {DEVELOPMENT_END}")
    paths = {archive_path(*f) for f in scored.required()}
    paths |= {funding_archive_path(FUNDING_SYMBOL, month) for month in months}
    paths |= {path + ".CHECKSUM" for path in paths}
    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    copies = []
    for source in (args.spec, args.reported_spec):
        target = data_dir / source.name
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        copies.append(target)
    span = f"{months[0]}..{months[-1]}" if months else "none"
    log(
        f"PLAN {scored.name}: {_kline_counts(scored)} and {len(months)} {FUNDING_SYMBOL} funding "
        f"months {span}; spec {_shown(args.spec)} sha256 {sha256_file(args.spec)}"
    )
    log(
        f"PLAN {reported.name}: {_kline_counts(reported)}, all in {scored.name}'s, and the same "
        f"funding months; spec {_shown(args.reported_spec)} sha256 "
        f"{sha256_file(args.reported_spec)}"
    )
    log(f"PLAN latest month {latest}; {len(paths)} planned paths; data dir {data_dir.as_posix()}")
    stamps = sorted({filters[symbol]["fetched_at"] for symbol in scored.traded})
    log(
        f"FILTERS {_shown(FILTERS)} sha256 {sha256_file(FILTERS)}: "
        f"{', '.join(scored.traded)}, fetched_at {', '.join(stamps)}"
    )
    return Plan(scored, reported, copies[0], copies[1], months, filters, paths)


def restore_filters(manifest: dict[str, Any], filters: dict[str, dict[str, Any]]) -> None:
    """Give the manifest's filters back their committed ``fetched_at``; they must then be
    the committed filters exactly."""
    for symbol, recorded in manifest["instruments"].items():
        recorded["fetched_at"] = filters[symbol]["fetched_at"]
    if manifest["instruments"] != {symbol: filters[symbol] for symbol in manifest["instruments"]}:
        raise Stop(f"the manifest's exchange filters differ from {_shown(FILTERS)}'s")


def cli(command: str, spec_copy: Path, data_dir: Path, jobs: int) -> tuple[int, str]:
    """One backtest CLI command on a spec copy, its output captured."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = backtest_cli.main(
            [
                command,
                "--spec",
                str(spec_copy),
                "--data-dir",
                str(data_dir),
                "--config",
                str(CONFIG),
                "--jobs",
                str(jobs),
            ]
        )
    return code, out.getvalue()


def _kept(path: Path, text: str) -> str:
    """Write ``text`` to ``path`` (LF line ends on every host); its SHA-256."""
    path.write_bytes(text.encode("utf-8"))
    return sha256_file(path)


def written(spec: DatasetSpec, copy: Path, manifest: dict[str, Any], log: Log) -> dict[str, Any]:
    """Write the manifest next to the spec's copy; the manifest as its file holds it."""
    path = manifest_path(copy)
    write_manifest(path, manifest)
    loaded = load_manifest(path)
    klines = [entry for entry in loaded["files"] if not is_funding(entry)]
    statuses = Counter(entry["status"] for entry in klines)
    complete = sum(digest_row(entry).endswith(" full") for entry in klines)
    log(
        f"KLINES {spec.name}: {len(klines)} files; "
        + ", ".join(f"{status} {n}" for status, n in sorted(statuses.items()))
        + f"; complete months {complete}"
    )
    log(
        f"MANIFEST {spec.name} {path.as_posix()} files {len(loaded['files'])} created_at "
        f"{loaded['created_at']} sha256 {sha256_file(path)}"
    )
    return loaded


def verify(
    spec: DatasetSpec,
    copy: Path,
    data_dir: Path,
    jobs: int,
    log: Log,
    problems: list[str],
    *,
    scored: bool,
) -> None:
    """``verify`` on a spec copy, logged. Fewer than ``MINIMUM_PAIRS`` included pairs is a
    problem only in the ``scored`` window: in the reported one it decides nothing (spec v1
    section 5 rule 6), so its count is logged and the run goes on."""
    code, text = cli("verify", copy, data_dir, jobs)
    target = data_dir / f"{spec.name}.verify.json"
    digest = _kept(target, text)
    report = json.loads(text)
    excluded = report.get("excluded_pairs", {})
    included = [pair for pair in spec.traded if pair not in excluded]
    log(
        f"VERIFY {spec.name} exit {code} status {report['status']}; failures "
        f"{len(report['failures'])}; included pairs {len(included)} of {len(spec.traded)}: "
        f"{', '.join(included) or 'none'}; output {target.as_posix()} sha256 {digest}"
    )
    for failure in report["failures"]:
        log(f"VERIFY {spec.name} failure: {failure}")
    for pair, reasons in excluded.items():
        log(f"VERIFY {spec.name} excluded {pair}: {'; '.join(reasons)}")
    if code != 0 or report["status"] != "valid":
        problems.append(f"verify of {spec.name} is {report['status']} (exit {code})")
    if len(included) < MINIMUM_PAIRS and scored:
        problems.append(
            f"{spec.name} keeps {len(included)} included pair(s); spec v1 section 5 needs "
            f"{MINIMUM_PAIRS}"
        )
    elif len(included) < MINIMUM_PAIRS:
        log(
            f"VERIFY {spec.name} keeps {len(included)} included pair(s), fewer than "
            f"{MINIMUM_PAIRS}: reported, not a problem, since this window decides nothing "
            "(spec v1 section 5 rule 6)"
        )


def mask_report(
    spec: DatasetSpec, copy: Path, data_dir: Path, jobs: int, log: Log, problems: list[str]
) -> None:
    _, text = cli("mask-report", copy, data_dir, jobs)
    target = data_dir / f"{spec.name}.mask-report.json"
    digest = _kept(target, text)
    report = json.loads(text)
    log(f"MASK report {target.as_posix()} sha256 {digest}")
    log("MASK totals " + " ".join(f"{key}={value}" for key, value in report["totals"].items()))
    quote = report["xrp_quote_test"]
    shown = (
        "not run, XRPUSDT is not traded"
        if quote is None
        else " ".join(f"{key}={value}" for key, value in quote.items())
    )
    log(f"MASK XRPUSDT quote test: {shown}")
    months = [
        (symbol, month)
        for symbol, found in report["symbols"].items()
        for month in found["months"]
        if month["masked_hours"] or month["excluded"]
    ]
    log(f"MASK symbol-months with a masked hour or an exclusion: {len(months)}")
    for symbol, month in months:
        log(
            f"MASK {symbol} {month['month']} masked {month['masked_hours']} of "
            f"{month['expected_hours']}, open-only {month['open_only_hours']}, share "
            f"{month['real_defect_share']}, excluded {month['excluded']}"
        )
    excluded = [f"{symbol} {month['month']}" for symbol, month in months if month["excluded"]]
    if excluded:
        problems.append(
            f"mask-report excludes {len(excluded)} symbol-month(s) under the 17% rule: "
            + ", ".join(excluded)
        )


def fetch(
    plan: Plan, args: argparse.Namespace, requests: Requests, log: Log, problems: list[str]
) -> Path:
    """Steps 2 to 6 of the module docstring; the digest's path."""
    data_dir: Path = args.data_dir
    funding = [
        fetch_funding_file(data_dir, FUNDING_SYMBOL, month, requests)
        for month in plan.funding_months
    ]
    absent = [entry for entry in funding if entry["status"] != "ok"]
    for entry in absent:
        log(f"FUNDING {entry['month']} {entry['status']}")
    if absent:
        raise Stop(
            f"{FUNDING_SYMBOL} funding archives not ok, so no manifest is written: "
            + ", ".join(entry["month"] for entry in absent)
        )
    log(
        f"FUNDING {len(funding)} of {len(plan.funding_months)} months ok; records "
        f"{sum(entry['records'] for entry in funding)}"
    )

    def instruments(symbol: str) -> dict[str, Any]:
        return dict(plan.filters[symbol])

    scored = fetch_dataset(plan.scored, data_dir, fetcher=requests, instruments=instruments)
    restore_filters(scored, plan.filters)
    scored["files"] += funding
    first = written(plan.scored, plan.scored_copy, scored, log)
    verify(plan.scored, plan.scored_copy, data_dir, args.jobs, log, problems, scored=True)
    mask_report(plan.scored, plan.scored_copy, data_dir, args.jobs, log, problems)

    reported = fetch_dataset(
        plan.reported, data_dir, fetcher=requests, instruments=instruments, previous=first
    )
    restore_filters(reported, plan.filters)
    reported = json.loads(json.dumps(reported))  # as the file will hold it: tuples are lists
    by_file = {identity(entry): entry for entry in first["files"]}
    differing = [file_name(e) for e in reported["files"] if by_file.get(identity(e)) != e]
    log(
        f"COMPARE {plan.reported.name}: {len(reported['files'])} files; every entry equals "
        f"{plan.scored.name}'s: {not differing}"
    )
    if differing:
        raise Stop(
            f"{plan.reported.name}'s entries differ from {plan.scored.name}'s, so its manifest "
            f"is not written: {', '.join(differing)}"
        )
    second = written(plan.reported, plan.reported_copy, reported, log)
    verify(plan.reported, plan.reported_copy, data_dir, args.jobs, log, problems, scored=False)

    hashes = {
        plan.scored.name: sha256_file(manifest_path(plan.scored_copy)),
        plan.reported.name: sha256_file(manifest_path(plan.reported_copy)),
    }
    text = digest_text(first, second, hashes)
    digest = data_dir / f"{plan.scored.name}.digest.txt"
    digest_sha256 = _kept(digest, text)
    same = True
    rebuilt = rebuild(text, plan.scored, plan.reported, plan.filters)
    for manifest, copy in zip(rebuilt, (plan.scored_copy, plan.reported_copy), strict=True):
        target = data_dir / "rebuilt" / manifest_path(copy).name
        write_manifest(target, manifest)
        same = same and sha256_file(target) == sha256_file(manifest_path(copy))
    log(
        f"DIGEST {digest.as_posix()} lines {len(text.splitlines())} bytes "
        f"{digest.stat().st_size} sha256 {digest_sha256}; rebuilds both manifests byte for "
        f"byte: {same}"
    )
    if not same:
        problems.append("the digest does not rebuild both manifests byte for byte")
    return digest


def log_requests(requests: Requests, data_dir: Path, log: Log) -> None:
    target = data_dir / "requests.txt"
    digest = _kept(target, "".join(f"{path}\n" for path in requests.paths))
    months = [found.group(1) for p in requests.paths if (found := _PATH_MONTH.search(p))]
    checksums = sum(path.endswith(".CHECKSUM") for path in requests.paths)
    log(
        f"REQUESTS {len(requests.paths)} to {ARCHIVE_HOST}, {checksums} of them .CHECKSUM; "
        f"latest month {max(months, default='none')}; after {DEVELOPMENT_END}: "
        f"{sum(month > DEVELOPMENT_END for month in months)}; list {target.as_posix()} "
        f"sha256 {digest}"
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: Fetcher = archive_get,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path, help="where every file goes (data/full-range)")
    parser.add_argument("--spec", type=Path, default=SCORED_SPEC, help="the scored window")
    parser.add_argument(
        "--reported-spec",
        type=Path,
        default=REPORTED_SPEC,
        help="the reported window, whose kline files are all in the scored window's",
    )
    parser.add_argument(
        "--jobs", type=int, default=4, help="worker processes for verify and mask-report"
    )
    args = parser.parse_args(argv)
    log = Log()
    problems: list[str] = []
    requests: Requests | None = None
    digest: Path | None = None
    try:
        plan = make_plan(args, log)
        requests = Requests(fetcher, plan.paths, sleep, log)
        digest = fetch(plan, args, requests, log, problems)
    except Stop as stop:
        log(f"STOP {stop}")
        problems.append(f"the run stopped: {stop}")
    if requests is not None:
        log_requests(requests, args.data_dir, log)
    if digest is not None:
        size = digest.stat().st_size
        total = log.bytes + size
        log(
            f"REPORT run log {log.bytes} bytes before this line and digest {size} bytes: "
            f"{total} bytes (the task stops above {REPORT_LIMIT})"
        )
        if total > REPORT_LIMIT:
            problems.append(f"the run log and digest hold {total} bytes, over {REPORT_LIMIT}")
    for problem in problems:
        log(f"PROBLEM {problem}")
    log(f"RESULT {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
