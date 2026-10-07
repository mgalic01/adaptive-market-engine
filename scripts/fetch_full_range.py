"""Bob's fetch of stage 2's long windows, full-range-2017-2024 and full-range-2019-2024.

    python scripts/fetch_full_range.py <data-dir> [--spec PATH] [--reported-spec PATH]
        [--jobs N]
    python scripts/fetch_full_range.py start <data-dir> [the same options]
    python scripts/fetch_full_range.py wait <data-dir>
    python scripts/fetch_full_range.py <report tool> ...   (see "The report tools")

Task: docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md (long-window data plan, Task
9). IBM Bob runs it on a GitHub Actions machine: Bob is the only actor allowed to reach
data.binance.vision. Every file it writes lands under ``<data-dir>``, which the task puts
in the git-ignored ``data/``, since bob-task.yml refuses any change but Bob's new report.
The defaults are the committed specs; ``--spec`` and ``--reported-spec`` exist for the
tests, which run it on small synthetic specs against a fake host. ``--jobs`` is the
backtest CLI's, for verify and mask-report.

**Running in the background, with Python only.** The run takes about an hour, longer than
one command of Bob's is known to last, and Bob's prompt allows python but no shell job
control. So ``start`` launches the same run as a detached child process of this script
(a new session on POSIX, a new process group on Windows), with its output in
``<data-dir>/run.log``, its pid in ``run.pid`` and, when it ends, its exit status in
``run.exit``, written even when the run ends in a traceback. ``start`` returns at once;
it refuses while a run is alive, and after one has ended, so a data dir holds one run. A
log from an earlier attempt is kept as ``run-<n>.log``. ``wait`` returns within
``WAIT_SECONDS`` and prints ``DONE exit=<status>`` with the log's last lines, ``RUNNING``
with its latest line, or ``GONE`` when the process has vanished without an exit file.
Without a subcommand, the run happens in the foreground, as the tests run it.

**The report tools.** For the same reason, every step of the task that a shell utility
would do is a subcommand: ``now`` (the UTC clock), ``tail``, ``exists``, ``measure``
(file sizes and the reserved-window file check), ``size``, ``set-aside`` (a move),
``append`` (a hand-written passage, or a file in a ``text`` fence), ``append-results``
and ``check-log``. ``append-results`` appends every run log (earlier, lost attempts first)
and the digest, within ``REPORT_LIMIT`` bytes: as text when they fit, else the digest,
then the logs too, compressed (zlib, then base64), each with the raw file's SHA-256 and
the exact ``python -c`` command that decodes it (``DECODE``). It then reads each block
back from the report and checks that it gives the file's bytes. So the digest reaches the
report whatever its size.

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
4. **The reported manifest.** ``fetch_dataset`` for the reported spec on the same
   ``<data-dir>``, with the scored manifest as ``previous``, so its funding entries are
   kept. A stored archive whose SHA-256 matches its .CHECKSUM is reused, so only .CHECKSUM
   requests go out, besides the archive request of a file Binance does not publish. Every
   entry must equal the scored manifest's for the same file; only then is the manifest
   written.
5. **The digest** of both manifests (format below), written as soon as both manifests are,
   so that no later failure can lose it: it is what rebuilds them. The script rebuilds
   both manifests from it (``rebuild``) and compares them with the written ones byte for
   byte.
6. **The checks.** ``verify`` on both windows and ``mask-report`` on the scored one (the
   backtest CLI, in this process), each loading its manifest from disk. Their JSON stays
   under ``<data-dir>``. The log prints verify's status, failures and excluded pairs, and
   mask-report's totals, every symbol-month with a masked hour or an exclusion, and
   XRPUSDT's actual-quotes line. A check that raises is a problem naming it, with its
   traceback in the log; the next check still runs.

Every request goes through ``Requests``. Only the planned archive and .CHECKSUM paths
pass; any other raises ``OutOfScope`` before the fetcher is called. A ``FeedError`` (a
transport failure, or an HTTP status other than 200 and 404) is retried with backoff, up
to ``ATTEMPTS`` attempts, as ``audit_run._fetch`` retries: ``archive_get`` retries
nothing, and one transient failure in about 2,450 requests would end the run. A checksum
mismatch is a ``DataError`` raised after the request has returned, so it is never retried
and ends the run with a traceback. The ``REQUESTS`` line (the count, the host, the latest
month) and ``<data-dir>/requests.txt`` are written even then.

The log ends with one ``PROBLEM`` line per problem and ``RESULT <n> problem(s)``; the exit
status is 0 only with none. The problems: a stop (``STOP`` line), a check that raised,
verify not valid, a scored window left with fewer than 2 included pairs, a symbol-month
that mask-report excludes under the 17% rule, and a digest that does not rebuild both
manifests. The reported window's included pairs are logged, but too few of them is no
problem: that window decides nothing (spec v1 section 5 rule 6). The ``REPORT`` line gives
the run log's and digest's bytes; above ``REPORT_LIMIT`` the report takes the digest
compressed, which is no problem either.

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
import base64
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import time
import traceback
import zlib
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
TASK = ROOT / "docs" / "tasks" / "2026-10-07-bob-full-range-2017-2024-fetch.md"
# The reviewed task file's text, read as task_digest reads it. Bob's workflow checks out main
# as it is when the job starts, so a later edit to the task would otherwise run unnoticed
# (Codex's review of #193); start refuses any other text. The pin block, which holds this
# script's own SHA-256, is left out of the digest, so the two pins do not refer in a circle.
TASK_SHA256 = "5dce48317dde6c3960054cfe726564dce184c072b2adab5ed1815ff55804bdf4"
FUNDING_SYMBOL = "BTCUSDT"  # variant G reads it for every pair (spec v1 section 3 G)
ATTEMPTS = 4
# The bytes of run logs and digest the report takes as text; above it, append-results
# compresses them. validate_bob_artifact.py rejects a report over REPORT_MAX_BYTES, and the
# hand-written passages need the rest.
REPORT_LIMIT = 190_000
REPORT_MAX_BYTES = 200_000  # validate_bob_artifact.py's REPORT_MAX_BYTES
MINIMUM_PAIRS = 2  # spec v1 section 5, "Minimum evidence"
# start and wait (the module docstring): one wait returns within about 9 minutes, under the
# 10 the task allows a command, and looks for the exit file every 10 seconds.
WAIT_SECONDS = 540.0
POLL_SECONDS = 10.0
TAIL_LINES = 5
# wait's last line names the next step. Run 37591538301 (issue #195) ended Bob's session
# right after a wait, with no report, so no outcome leaves the next step to inference.
NEXT_DONE = (
    "NEXT: the run has ended and the report is not written yet. Go on to Step 5 now, then "
    "Step 6, and end with your signed final message. DONE is never the end of the task."
)
NEXT_GONE = (
    "NEXT: run Step 4's start once more, unchanged, then wait again. If wait says GONE a "
    "second time, write the report (Steps 5 and 6) with what exists."
)
NEXT_RUNNING = "NEXT: run the same wait again."
RECORD = "_run"  # the hidden subcommand of the child that start launches
# The children start launched, kept so that this process never collects one while it
# runs: Popen would then warn that it is still running (ResourceWarning).
_LAUNCHED: list[subprocess.Popen[bytes]] = []
STILL_ACTIVE = 259  # GetExitCodeProcess of a Windows process that has not ended
FENCE = chr(96) * 3  # a Markdown code fence
WRAP = 76  # the width of a compressed block's lines
# An archive or checksum file of the reserved window, as bob-task.yml looks for one.
RESERVED_NAME = re.compile(r"-20(2[5-9]|[3-9][0-9])-[0-9]{2}\.(zip|csv|zip\.CHECKSUM)$")
# The command that decodes a compressed block of a report, given the report, the block's
# heading and an output file: standalone, so a reader needs neither this script nor its
# version. It splits the section as _block does.
DECODE = (
    r"""python -c "import base64, sys, zlib; from pathlib import Path; """
    r"""t = Path(sys.argv[1]).read_text(encoding='utf-8'); """
    r"""t = t.split('\n## ' + sys.argv[2] + '\n', 1)[1]; """
    r"""b = t.split('\x60\x60\x60text\n')[2].split('\x60\x60\x60')[0]; """
    r'''Path(sys.argv[3]).write_bytes(zlib.decompress(base64.b64decode(''.join(b.split()))))"'''
)
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
            f"MASK {symbol} {month['month']} masked {month['masked_hours']}/"
            f"{month['expected_hours']} open-only {month['open_only_hours']} share "
            f"{month['real_defect_share']} excluded {month['excluded']}"
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
    """Steps 2 to 5 of the module docstring; the digest's path."""
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


def checks(plan: Plan, args: argparse.Namespace, log: Log, problems: list[str]) -> None:
    """Step 6 of the module docstring, after the digest is written. A check that raises is
    a problem naming it, with its traceback in the log, and the next check still runs."""
    data_dir: Path = args.data_dir
    steps: list[tuple[str, DatasetSpec, Callable[[], None]]] = [
        (
            "verify",
            plan.scored,
            lambda: verify(
                plan.scored, plan.scored_copy, data_dir, args.jobs, log, problems, scored=True
            ),
        ),
        (
            "mask-report",
            plan.scored,
            lambda: mask_report(plan.scored, plan.scored_copy, data_dir, args.jobs, log, problems),
        ),
        (
            "verify",
            plan.reported,
            lambda: verify(
                plan.reported, plan.reported_copy, data_dir, args.jobs, log, problems, scored=False
            ),
        ),
    ]
    for command, spec, step in steps:
        try:
            step()
        except Exception as exc:
            log(traceback.format_exc().rstrip())
            problems.append(f"{command} of {spec.name} raised {type(exc).__name__}: {exc}")


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


def _parser() -> argparse.ArgumentParser:
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
    # For the tests of start and wait only: sleep that long, then end, fetching nothing.
    parser.add_argument("--fake-run", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--fake-raise", action="store_true", help=argparse.SUPPRESS)
    return parser


@dataclass(frozen=True)
class RunFiles:
    """The files of a background run, all in its data dir."""

    log: Path
    pid: Path
    exit: Path


def run_files(data_dir: Path) -> RunFiles:
    return RunFiles(data_dir / "run.log", data_dir / "run.pid", data_dir / "run.exit")


def _alive(pid: int) -> bool:
    """Whether process ``pid`` exists and has not ended. Windows has no signal 0: there
    ``os.kill`` would end the process, so its exit code is asked for instead."""
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and (
                code.value == STILL_ACTIVE
            )
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _lines(path: Path) -> list[str]:
    """The non-empty lines of a log, or none if it does not exist yet."""
    if not path.exists():
        return []
    return [line for line in path.read_text("utf-8", "replace").splitlines() if line.strip()]


def _pid(path: Path) -> int | None:
    """The pid in a run's pid file; None while there is none yet (no file, or an empty one,
    as between start's launch and its write). ValueError for anything but a number."""
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    if not text:
        return None
    if not text.isdigit():
        raise ValueError(f"{path.as_posix()} holds {text[:40]!r}, not a process id")
    return int(text)


def _detached() -> dict[str, Any]:
    """Popen's arguments that let the child outlive the command that started it."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def task_digest(path: Path) -> str:
    """The SHA-256 of the task file with LF line ends and the lines of its pin block (the
    ``text`` block under "## Pinned inputs") left out."""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    head, rest = text.split("## Pinned inputs", 1)
    before, block = rest.split(FENCE + "text\n", 1)
    after = block.split(FENCE, 1)[1]
    kept = head + "## Pinned inputs" + before + FENCE + "text\n" + FENCE + after
    return hashlib.sha256(kept.encode("utf-8")).hexdigest()


def start(arguments: list[str]) -> int:
    """Launch the run (the same options as a foreground run) as a detached child, once, and
    only from the reviewed task text (``TASK_SHA256``)."""
    args = _parser().parse_args(arguments)  # a mistyped option fails here, not in the child
    digest = task_digest(TASK)
    if digest != TASK_SHA256:
        print(
            f"NOT STARTED: the task file {TASK.name} is not the reviewed text (its SHA-256 "
            f"without the pin block is {digest}); report it, and start nothing"
        )
        return 1
    data_dir: Path = args.data_dir
    files = run_files(data_dir)
    if files.exit.exists():
        print(f"NOT STARTED: the run in {data_dir.as_posix()} has ended ({files.exit.as_posix()})")
        return 1
    try:
        pid = _pid(files.pid)
    except ValueError as exc:
        print(f"NOT STARTED: {exc}; report it, and start nothing")
        return 1
    if pid is not None and _alive(pid):
        print(f"NOT STARTED: the run in {data_dir.as_posix()} is still running")
        return 1
    data_dir.mkdir(parents=True, exist_ok=True)
    if files.log.exists():  # an earlier attempt that was lost (wait said GONE): keep its log
        attempt = 1
        while (data_dir / f"run-{attempt}.log").exists():
            attempt += 1
        files.log.replace(data_dir / f"run-{attempt}.log")
    # The child imports the same crypto_grid_bot as this process, whatever else is installed.
    source = str(Path(backtest_cli.__file__).resolve().parents[2])
    paths = [source, *filter(None, [os.environ.get("PYTHONPATH")])]
    command = [sys.executable, str(Path(__file__).resolve()), RECORD, *arguments]
    with files.log.open("wb") as log:
        # This script with its own arguments, and no shell.
        child = subprocess.Popen(  # nosec B603
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": os.pathsep.join(paths)},
            **_detached(),
        )
    _LAUNCHED.append(child)
    files.pid.write_text(f"{child.pid}\n", encoding="utf-8")
    print(f"STARTED pid {child.pid}; log {files.log.as_posix()}; exit file {files.exit.as_posix()}")
    return 0


def wait(arguments: list[str]) -> int:
    """Wait up to ``WAIT_SECONDS`` for the background run; say how it stands."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py wait")
    parser.add_argument("data_dir", type=Path)
    data_dir: Path = parser.parse_args(arguments).data_dir
    files = run_files(data_dir)
    if not files.pid.exists() and not files.exit.exists():
        print(f"NOT STARTED: no run in {data_dir.as_posix()}")
        return 1
    deadline = time.monotonic() + WAIT_SECONDS
    while True:
        if files.exit.exists():
            print(f"DONE exit={files.exit.read_text(encoding='utf-8').strip()}")
            for line in _lines(files.log)[-TAIL_LINES:]:
                print(line)
            print(NEXT_DONE)
            return 0
        try:
            pid = _pid(files.pid)
        except ValueError as exc:
            print(f"UNREADABLE: {exc}")
            return 1
        latest = (_lines(files.log) or ["no output yet"])[-1]
        if pid is None:  # start has launched the child and not yet written its pid
            if time.monotonic() >= deadline:
                print(f"NOT STARTED: {files.pid.as_posix()} is still empty; latest: {latest}")
                return 1
            time.sleep(POLL_SECONDS)
            continue
        if not _alive(pid):
            if files.exit.exists():  # it ended between the two looks
                continue
            print(f"GONE pid {pid}: no process and no exit file; latest: {latest}")
            print(NEXT_GONE)
            return 0  # an expected outcome with its own next step, not a failed command
        if time.monotonic() >= deadline:
            print(f"RUNNING pid {pid}; latest: {latest}")
            print(NEXT_RUNNING)
            return 0
        time.sleep(POLL_SECONDS)


def record(arguments: list[str], *, fetcher: Fetcher, sleep: Callable[[float], None]) -> int:
    """The child that start launches: the run, then its exit status in the exit file, also
    after a traceback, which goes to the log."""
    files = run_files(_parser().parse_args(arguments).data_dir)
    code = 1
    try:
        code = run(arguments, fetcher=fetcher, sleep=sleep)
    except SystemExit as stop:
        code = stop.code if isinstance(stop.code, int) else 1
    except BaseException:
        traceback.print_exc()
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        partial = files.exit.with_name(files.exit.name + ".partial")
        partial.write_text(f"{code}\n", encoding="utf-8")
        partial.replace(files.exit)
    return code


# --- The report tools (the module docstring): what Bob runs instead of shell utilities ----


def _utc() -> str:
    """The time as the shell's UTC clock prints it."""
    return time.strftime("%a %b %d %H:%M:%S UTC %Y", time.gmtime())


def now(arguments: list[str]) -> int:
    argparse.ArgumentParser(prog="fetch_full_range.py now").parse_args(arguments)
    print(_utc())
    return 0


def tail(arguments: list[str]) -> int:
    """A file's last lines."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py tail")
    parser.add_argument("file", type=Path)
    parser.add_argument("--lines", type=int, default=3)
    args = parser.parse_args(arguments)
    for line in args.file.read_text("utf-8", "replace").splitlines()[-args.lines :]:
        print(line)
    return 0


def exists(arguments: list[str]) -> int:
    """Whether each path exists (BOB_PRACTICE self-check 2); exit 1 if any does not."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py exists")
    parser.add_argument("paths", type=Path, nargs="+")
    paths = parser.parse_args(arguments).paths
    for path in paths:
        print(f"{'EXISTS' if path.exists() else 'MISSING'} {path.as_posix()}")
    return 0 if all(path.exists() for path in paths) else 1


def measure(arguments: list[str]) -> int:
    """The bytes of each run log and digest in a run's data dir, and every file under a tree
    named as an archive of the reserved window (2025-01 or later); exit 1 if there is one."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py measure")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("tree", type=Path)
    args = parser.parse_args(arguments)
    for path in [
        *sorted(args.run_dir.glob("run*.log")),
        *sorted(args.run_dir.glob("*.digest.txt")),
    ]:
        print(f"SIZE {path.stat().st_size} {path.as_posix()}")
    reserved = sorted(
        path for path in args.tree.rglob("*") if path.is_file() and RESERVED_NAME.search(path.name)
    )
    for path in reserved:
        print(f"RESERVED {path.as_posix()}")
    print(f"RESERVED-WINDOW FILES {len(reserved)}")
    return 1 if reserved else 0


def size(arguments: list[str]) -> int:
    """A report's bytes against validate_bob_artifact.py's limit; exit 1 at or over it."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py size")
    parser.add_argument("report", type=Path)
    report: Path = parser.parse_args(arguments).report
    count = report.stat().st_size
    verdict = "under" if count < REPORT_MAX_BYTES else "AT OR OVER"
    print(f"SIZE {count} {report.as_posix()}: {verdict} the {REPORT_MAX_BYTES}-byte limit")
    return 0 if count < REPORT_MAX_BYTES else 1


def set_aside(arguments: list[str]) -> int:
    """Move a file (a report too large to publish) to a new path that does not exist yet."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py set-aside")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args(arguments)
    if args.target.exists():
        print(f"NOT MOVED: {args.target.as_posix()} exists")
        return 1
    count = args.source.stat().st_size
    args.source.replace(args.target)
    print(f"SET ASIDE {args.source.as_posix()} -> {args.target.as_posix()}, {count} bytes")
    return 0


def _text_section(title: str, data: bytes) -> str:
    text = data.decode("utf-8")
    return (
        f"\n## {title}\n\n{FENCE}text\n{text}{'' if text.endswith(chr(10)) else chr(10)}{FENCE}\n"
    )


def packed(data: bytes) -> str:
    """``data`` compressed (zlib, level 9) and base64-encoded, in lines of ``WRAP``."""
    text = base64.b64encode(zlib.compress(data, 9)).decode("ascii")
    return "".join(text[at : at + WRAP] + "\n" for at in range(0, len(text), WRAP))


def unpacked(block: str) -> bytes:
    return zlib.decompress(base64.b64decode("".join(block.split())))


def _packed_section(title: str, data: bytes, source: Path) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return (
        f"\n## {title}\n\n"
        f"{source.name}, {len(data)} bytes, SHA-256 {digest}, is too large for this report as "
        "text, so it is compressed (zlib, then base64) below. To get its bytes back, give the "
        "report, this heading and an output file to:\n\n"
        f'{FENCE}text\n{DECODE} REPORT "{title}" OUTPUT\n{FENCE}\n\n'
        f"{FENCE}text\n{packed(data)}{FENCE}\n"
    )


def _block(report: str, title: str, packed_form: bool) -> str:
    """The fenced block of a section appended by append-results, as ``DECODE`` finds it."""
    section = report.split(f"\n## {title}\n", 1)[1]
    return section.split(f"{FENCE}text\n")[2 if packed_form else 1].split(FENCE)[0]


def _results(run_dir: Path) -> list[tuple[str, Path]]:
    """(heading, file) for every run log, earlier attempts first, then the digest."""
    earlier = sorted(
        (int(path.stem.removeprefix("run-")), path)
        for path in run_dir.glob("run-*.log")
        if path.stem.removeprefix("run-").isdigit()
    )
    found = [(f"Run log, attempt {n} (lost)", path) for n, path in earlier]
    if run_files(run_dir).log.exists():
        found.append(("Run log", run_files(run_dir).log))
    found += [("Digest", path) for path in sorted(run_dir.glob("*.digest.txt"))]
    return found


def append_results(arguments: list[str]) -> int:
    """Append every run log and the digest to the report, within ``--limit`` bytes: as text
    when they fit, else the digest compressed, else everything compressed. Each block is
    then read back from the report and checked against its file."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py append-results")
    parser.add_argument("report", type=Path)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--limit", type=int, default=REPORT_LIMIT)
    parser.add_argument("--compressed", action="store_true", help="compress everything")
    args = parser.parse_args(arguments)
    found = [(title, path, path.read_bytes()) for title, path in _results(args.run_dir)]
    if not found:
        print(f"NOT APPENDED: no run log or digest in {args.run_dir.as_posix()}")
        return 1
    choices = [(True, True)] if args.compressed else [(False, False), (False, True), (True, True)]
    for logs_packed, digest_packed in choices:
        sections = []
        for title, path, data in found:
            pack = digest_packed if title == "Digest" else logs_packed
            heading = f"{title} (zlib, base64)" if pack else title
            built = _packed_section(heading, data, path) if pack else _text_section(heading, data)
            sections.append((heading, path, data, pack, built))
        total = sum(len(section[4].encode("utf-8")) for section in sections)
        if total <= args.limit:
            break
    else:
        print(f"NOT APPENDED: even compressed, they take {total} bytes, over {args.limit}")
        return 1
    with args.report.open("a", encoding="utf-8", newline="\n") as report:
        report.write("".join(section[4] for section in sections))
    written = args.report.read_bytes().decode("utf-8")  # exact bytes: no newline translation
    good = True
    for heading, path, data, pack, built in sections:
        block = _block(written, heading, pack)
        expected = data if data.endswith(b"\n") or pack else data + b"\n"
        back = unpacked(block) if pack else block.encode("utf-8")
        same = back == expected
        good = good and same
        form = "compressed" if pack else "text"
        print(
            f"APPENDED {heading}: {form}, {len(built.encode('utf-8'))} bytes; "
            f"{path.as_posix()} sha256 {hashlib.sha256(data).hexdigest()}; reads back: {same}"
        )
    print(f"APPENDED {total} bytes in all (limit {args.limit})")
    return 0 if good else 1


def append(arguments: list[str]) -> int:
    """Append a hand-written passage to the report, or with ``--heading`` a file in a text
    fence under that heading."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py append")
    parser.add_argument("report", type=Path)
    parser.add_argument("file", type=Path)
    parser.add_argument("--heading")
    args = parser.parse_args(arguments)
    data = args.file.read_bytes()
    if args.heading:
        added = _text_section(args.heading, data)
    else:
        text = data.decode("utf-8")
        added = "\n" + text + ("" if text.endswith("\n") else "\n")
    with args.report.open("a", encoding="utf-8", newline="\n") as report:
        report.write(added)
    print(f"APPENDED {args.file.as_posix()}: {len(added.encode('utf-8'))} bytes")
    return 0


def check_log(arguments: list[str]) -> int:
    """The checks file of the report: git status's lines, then check_reports.py's without
    its UNVERIFIABLE lines (about other reports, and naming scripts next to hashes, which
    would read as pins here), then the time."""
    parser = argparse.ArgumentParser(prog="fetch_full_range.py check-log")
    parser.add_argument("status", type=Path)
    parser.add_argument("check_reports_log", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args(arguments)
    lines = args.status.read_text(encoding="utf-8").splitlines()
    lines += [
        line
        for line in args.check_reports_log.read_text(encoding="utf-8").splitlines()
        if not line.startswith("check_reports: UNVERIFIABLE ")
    ]
    lines.append(_utc())
    args.out.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    print(f"WROTE {args.out.as_posix()}: {len(lines)} lines")
    return 0


TOOLS: dict[str, Callable[[list[str]], int]] = {
    "start": start,
    "wait": wait,
    "now": now,
    "tail": tail,
    "exists": exists,
    "measure": measure,
    "size": size,
    "set-aside": set_aside,
    "append": append,
    "append-results": append_results,
    "check-log": check_log,
}


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: Fetcher = archive_get,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """A subcommand (the background run's, or a report tool), or the run in the foreground."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = arguments[0] if arguments else ""
    if command in TOOLS:
        return TOOLS[command](arguments[1:])
    if command == RECORD:
        return record(arguments[1:], fetcher=fetcher, sleep=sleep)
    return run(arguments, fetcher=fetcher, sleep=sleep)


def run(
    argv: Sequence[str],
    *,
    fetcher: Fetcher = archive_get,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """The whole run (the module docstring's steps), in this process."""
    args = _parser().parse_args(argv)
    if args.fake_run is not None:
        print(f"FAKE run: {args.fake_run} s", flush=True)
        time.sleep(args.fake_run)
        if args.fake_raise:
            raise RuntimeError("fake run failure")
        print("RESULT 0 problem(s)", flush=True)
        return 0
    log = Log()
    problems: list[str] = []
    requests: Requests | None = None
    digest: Path | None = None
    try:
        try:
            plan = make_plan(args, log)
            requests = Requests(fetcher, plan.paths, sleep, log)
            digest = fetch(plan, args, requests, log, problems)
            checks(plan, args, log, problems)
        except Stop as stop:
            log(f"STOP {stop}")
            problems.append(f"the run stopped: {stop}")
    finally:
        # Even after a traceback (a checksum failure, a lasting FeedError, OutOfScope), the
        # log must say how many requests went out, and to which months.
        if requests is not None:
            log_requests(requests, args.data_dir, log)
    if digest is not None:
        digest_bytes = digest.stat().st_size
        total = log.bytes + digest_bytes
        form = "as text" if total <= REPORT_LIMIT else "compressed (append-results)"
        log(
            f"REPORT run log {log.bytes} bytes before this line and digest {digest_bytes} "
            f"bytes: {total} bytes; the report takes them {form} (limit {REPORT_LIMIT})"
        )
    for problem in problems:
        log(f"PROBLEM {problem}")
    log(f"RESULT {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
