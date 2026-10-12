"""Bob's fetch of V3.1's flow-gate minute bars: spot 1m klines of seven coins, 2021-06 to 2024-12.

    python scripts/fetch_minute_bars.py <data-dir> [--spec PATH]
    python scripts/fetch_minute_bars.py start <data-dir> [--spec PATH]
    python scripts/fetch_minute_bars.py wait <data-dir>
    python scripts/fetch_minute_bars.py <report tool> ...   (see "The report tools")

Task: docs/tasks/2026-10-11-bob-v3-1-minute-bars-fetch.md. IBM Bob runs it on a GitHub
Actions machine, where Bob is the only actor allowed to reach data.binance.vision. Every
file it writes lands under ``<data-dir>``, which the task puts in the git-ignored ``data/``.
The default spec is config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.toml;
``--spec`` exists for the tests, which run it on a small synthetic spec against a fake host.

No existing fetch script can fetch this set. ``fetch_full_range.py`` fetches two backtest
windows: every spec it takes also lists hourly archives and BTCUSDT's funding archives, and
it has exchange filters for three pairs only. ``fetch_v3_data.py`` fetches 1h archives and
the venues' filters. This script reuses what both build on: ``fetch_dataset``, the
checksum rule, the repairing reader and the manifest of ``crypto_grid_bot.backtest.dataset``;
``Requests``, the digest rows and the report tools of ``fetch_full_range.py``. Nothing in
``src`` or in that script changed. What is new is the one-interval spec, and the plan, the
checks and the digest that go with it.

**The run,** in this order:

1. **Plan, before any request.** Loads the spec, which refuses any month after 2024-12, and
   lists its archives: for each symbol, each month, one 1m archive and its .CHECKSUM (a
   request budget of twice the archive count). Copies the spec into ``<data-dir>``, so that
   the manifest is written next to its copy and never into config/datasets.
2. **Fetch,** one symbol at a time, with ``fetch_dataset`` on a ``MinuteBars`` spec. Each
   archive is stored only if it matches Binance's published SHA-256, then read: strictly,
   and on a failure by the repairing reader (spec v1 section 5 rule 1), so it is recorded as
   ok with its statistics or as unreadable with the reason. A month Binance does not publish
   is recorded as missing. A symbol is logged as soon as it is done.
3. **The manifest,** in the dataset manifest format (schema 1) with no exchange filters:
   bars only, no replay parameters. ``write_manifest`` writes it atomically, and it is
   loaded again from disk.
4. **The digest** (format below), written as soon as the manifest is, so that no later
   failure can lose it: it is what rebuilds the manifest. The script rebuilds the manifest
   from it (``rebuild``) and compares the two byte for byte.
5. **The checks.** ``verify_dataset``, with every local archive against its SHA-256; one
   coverage line per symbol; and the months that are missing or unreadable. A check that
   raises is a problem naming it, with its traceback in the log, and the next one still runs.

**Requests.** Every one goes through ``Requests``: only the planned archive and .CHECKSUM
paths pass; any other raises ``OutOfScope`` before the fetcher is called. A ``FeedError``
is retried with backoff, 4 attempts in all, as in ``fetch_full_range.py``. A checksum
mismatch is a ``DataError`` and ends the run with a traceback. ``archive_get`` still
refuses a month after 2024-12 and any path that is not a monthly spot kline archive. The
``REQUESTS`` line and ``<data-dir>/requests.txt`` are written even after a traceback.

The log ends with one ``PROBLEM`` line per problem and ``RESULT <n> problem(s)``; the exit
status is 0 only with none. The problems: a check that raised, ``verify_dataset`` failing,
a missing or an unreadable archive (none is expected), and a digest that does not rebuild
the manifest. A month with gaps is no problem: Binance's minute archives have some, and
the digest records their statistics.

**The digest, format v1** (one manifest; ``fetch_full_range.py``'s digest format with a
single manifest and no funding rows): one line each, its fields separated by single spaces.

* ``digest of <dataset>, format v1 (scripts/fetch_minute_bars.py)``;
* ``manifest <dataset> created_at <time> files <n> sha256 <hex>``;
* one row per file of the manifest, in its order, as ``fetch_full_range.digest_row`` writes
  it: ``<name> missing``; ``<name> <sha256> unreadable <bytes> <reason as a JSON string>``;
  ``<name> <sha256> ok <bytes> full`` for a complete month; or ``<name> <sha256> ok <bytes>
  <field>=<value> ...`` with each statistic that differs from a complete month's.

Every other field of the manifest follows from the spec.

**Running in the background, with Python only.** As in ``fetch_full_range.py``: ``start``
launches the same run as a detached child (output in ``<data-dir>/run.log``, pid in
``run.pid``, exit status in ``run.exit``, written even after a traceback), and returns at
once; it starts nothing unless the task file's text, the pin block left out, is the one
this script holds (``TASK_SHA256``). ``wait``, in ``fetch_full_range.py``, answers within
about 9 minutes with ``DONE``, ``RUNNING`` or ``GONE``.

**The report tools** are ``fetch_full_range.py``'s, unchanged: ``now``, ``tail``,
``exists``, ``measure``, ``size``, ``set-aside``, ``append``, ``append-results``,
``check-log`` and ``wait``. They take a data dir, a report or a file, never a spec, so they
serve this task as they served that one.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess  # nosec B404
import sys
import time
import tomllib
import traceback
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import fetch_full_range

from crypto_grid_bot.backtest import dataset
from crypto_grid_bot.backtest.dataset import (
    ARCHIVE_HOST,
    MANIFEST_SCHEMA,
    DatasetSpec,
    Fetcher,
    archive_get,
    archive_path,
    fetch_dataset,
    sha256_file,
    verify_dataset,
    write_manifest,
)
from crypto_grid_bot.backtest.jobs import manifest_path
from crypto_grid_bot.backtest.window import DEVELOPMENT_END, development_month
from crypto_grid_bot.market_data.parsing import DataError, symbol_name

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "config" / "datasets" / "v3-1-minute-bars" / "v3-1-minute-bars-2021-2024.toml"
TASK = ROOT / "docs" / "tasks" / "2026-10-11-bob-v3-1-minute-bars-fetch.md"
# The reviewed task file's text, read as fetch_full_range.task_digest reads it: Bob's
# workflow checks out main as it is when the job starts, so a later edit to the task would
# otherwise run unnoticed. start refuses any other text. The pin block, which holds this
# script's own SHA-256, is left out of the digest, so the two pins do not refer in a circle.
TASK_SHA256 = "8e11396f36cc628ab4e0608dba3eb88e53265fa5be15516b462ca2f884796612"
INTERVAL = "1m"
RECORD = "_run"  # the hidden subcommand of the child that start launches
# The children start launched, kept so that this process never collects one while it runs.
_LAUNCHED: list[subprocess.Popen[bytes]] = []
_FIELDS: dict[str, type] = {
    "name": str,
    "purpose": str,
    "interval": str,
    "symbols": list,
    "start": str,
    "end": str,
}


@dataclass(frozen=True)
class MinuteBars(DatasetSpec):
    """One-interval bars of ``symbols``, as the backtest's ``DatasetSpec`` machinery takes
    them: ``required()`` lists only each symbol's 1m archives from ``start`` to ``end``, so
    ``fetch_dataset`` and ``verify_dataset`` fetch and check exactly those. The replay
    fields of a ``DatasetSpec`` do not apply to bars: no traded pair (so no exchange
    filters), no basket, no pricing."""

    symbols: tuple[str, ...] = ()

    def required(self) -> list[tuple[str, str, str]]:
        return [
            (symbol, INTERVAL, month)
            for symbol in self.symbols
            for month in self.months(self.start)
        ]


def load_minute_spec(path: Path) -> MinuteBars:
    """The spec file, strictly: exactly its six fields, the interval 1m, distinct symbols,
    and months inside the development window (``development_month`` refuses 2025-01 and
    later, so a spec reaching it is rejected here and nothing is requested)."""
    with path.open("rb") as source:
        try:
            raw = tomllib.load(source)
        except tomllib.TOMLDecodeError as exc:
            raise DataError(f"invalid minute-bars TOML: {exc}") from exc
    if set(raw) != set(_FIELDS):
        raise DataError("minute-bars spec contains missing or unknown fields")
    for key, expected in _FIELDS.items():
        if type(raw[key]) is not expected:
            raise DataError(f"minute-bars field {key} has an invalid type")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", raw["name"]):
        raise DataError("minute-bars name must be lowercase letters, digits and hyphens")
    if not raw["purpose"].strip():
        raise DataError("minute-bars purpose must not be empty")
    if raw["interval"] != INTERVAL:
        raise DataError(f"minute-bars interval must be {INTERVAL}")
    if not all(type(symbol) is str for symbol in raw["symbols"]):
        raise DataError("minute-bars symbols must be strings")
    symbols = tuple(symbol_name(symbol) for symbol in raw["symbols"])
    if not symbols or len(set(symbols)) != len(symbols):
        raise DataError("minute-bars symbols must be non-empty and distinct")
    start, end = development_month(raw["start"]), development_month(raw["end"])
    if not start <= end:
        raise DataError("minute-bars months must satisfy start <= end")
    zero = Decimal(0)
    return MinuteBars(
        name=raw["name"],
        purpose=raw["purpose"],
        traded=(),
        market_proxy="",
        breadth_basket=(),
        warmup_start=start,
        start=start,
        end=end,
        initial_quote=zero,
        fee_rate=zero,
        slippage_rate=zero,
        participation=zero,
        assumed_spread_pct=zero,
        symbols=symbols,
    )


@dataclass(frozen=True)
class Plan:
    spec: MinuteBars
    # The spec's copy in <data-dir>; the manifest is written next to it.
    copy: Path
    paths: set[str]


def no_filters(symbol: str) -> dict[str, str]:
    """``fetch_dataset``'s source of exchange filters. A MinuteBars spec traded nothing, so
    it is never called; if it were, the request it stands for is not in the plan."""
    raise fetch_full_range.OutOfScope(f"exchange filters of {symbol} are not requested")


def make_plan(args: argparse.Namespace, log: fetch_full_range.Log) -> Plan:
    """Everything decided before the first request (step 1 of the module docstring)."""
    spec = load_minute_spec(args.spec)
    files = spec.required()
    latest = max(month for _, _, month in files)
    if latest > DEVELOPMENT_END:
        raise fetch_full_range.OutOfScope(f"planned month {latest} is after {DEVELOPMENT_END}")
    paths = {archive_path(*file) for file in files}
    paths |= {path + ".CHECKSUM" for path in paths}
    data_dir: Path = args.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    copy = data_dir / args.spec.name
    if args.spec.resolve() != copy.resolve():
        shutil.copyfile(args.spec, copy)
    months = spec.months(spec.start)
    log(
        f"PLAN {spec.name}: {len(files)} {INTERVAL} kline files, {len(spec.symbols)} symbols "
        f"({', '.join(spec.symbols)}) x {len(months)} months {months[0]}..{months[-1]}; "
        f"spec {fetch_full_range._shown(args.spec)} sha256 {sha256_file(args.spec)}"
    )
    log(
        f"PLAN latest month {latest}; {len(paths)} planned paths: {len(files)} archives and "
        f"{len(files)} .CHECKSUM, so {2 * len(files)} requests if nothing is retried or stored "
        f"already; data dir {data_dir.as_posix()}"
    )
    return Plan(spec, copy, paths)


def digest_text(manifest: dict[str, Any], manifest_sha256: str) -> str:
    """The digest of ``manifest`` as its file holds it (the module docstring's format)."""
    lines = [
        f"digest of {manifest['dataset']}, format v1 (scripts/fetch_minute_bars.py)",
        f"manifest {manifest['dataset']} created_at {manifest['created_at']} "
        f"files {len(manifest['files'])} sha256 {manifest_sha256}",
    ]
    return "\n".join(lines + [fetch_full_range.digest_row(e) for e in manifest["files"]]) + "\n"


def rebuild(digest: str, spec: MinuteBars) -> dict[str, Any]:
    """The manifest from the digest and the spec; ValueError for a digest that does not
    list exactly the spec's archives, once each."""
    lines = digest.splitlines()
    if len(lines) < 2 or not lines[1].startswith(f"manifest {spec.name} created_at "):
        raise ValueError(f"the digest is not {spec.name}'s")
    created_at = lines[1].split(" ")[3]
    rows: dict[str, dict[str, Any]] = {}
    for line in lines[2:]:
        name = line.split(" ", 1)[0]
        if name in rows:
            raise ValueError(f"the digest lists {name} twice")
        rows[name] = fetch_full_range.entry_of(line)
    wanted = [fetch_full_range.kline_file(*file) for file in spec.required()]
    if sorted(rows) != sorted(wanted):
        raise ValueError(f"the digest's rows are not {spec.name}'s archives")
    return {
        "schema": MANIFEST_SCHEMA,
        "dataset": spec.name,
        "source": f"https://{ARCHIVE_HOST}",
        "created_at": created_at,
        "instruments": {},
        "files": [rows[name] for name in wanted],
    }


def fetch(
    plan: Plan,
    args: argparse.Namespace,
    requests: fetch_full_range.Requests,
    log: fetch_full_range.Log,
    problems: list[str],
    now: Callable[[], datetime],
) -> tuple[Path, dict[str, Any]]:
    """Steps 2 to 4 of the module docstring; the digest's path and the loaded manifest."""
    data_dir: Path = args.data_dir
    spec = plan.spec
    files: list[dict[str, Any]] = []
    for symbol in spec.symbols:
        part = fetch_dataset(
            replace(spec, symbols=(symbol,)),
            data_dir,
            fetcher=requests,
            instruments=no_filters,
            now=now,
        )
        files += part["files"]
        found = Counter(entry["status"] for entry in part["files"])
        log(
            f"FETCHED {symbol}: {len(part['files'])} files; "
            + ", ".join(f"{status} {n}" for status, n in sorted(found.items()))
            + f"; requests so far {len(requests.paths)}"
        )
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "dataset": spec.name,
        "source": f"https://{ARCHIVE_HOST}",
        "created_at": now().isoformat(timespec="seconds"),
        "instruments": {},
        "files": files,
    }
    loaded = fetch_full_range.written(spec, plan.copy, manifest, log)
    path = manifest_path(plan.copy)
    text = digest_text(loaded, sha256_file(path))
    digest = data_dir / f"{spec.name}.digest.txt"
    digest_sha256 = fetch_full_range._kept(digest, text)
    target = data_dir / "rebuilt" / path.name
    write_manifest(target, rebuild(text, spec))
    same = sha256_file(target) == sha256_file(path)
    log(
        f"DIGEST {digest.as_posix()} lines {len(text.splitlines())} bytes "
        f"{digest.stat().st_size} sha256 {digest_sha256}; rebuilds the manifest byte for "
        f"byte: {same}"
    )
    if not same:
        problems.append("the digest does not rebuild the manifest byte for byte")
    return digest, loaded


def verify(
    plan: Plan,
    manifest: dict[str, Any],
    data_dir: Path,
    log: fetch_full_range.Log,
    problems: list[str],
) -> None:
    """``verify_dataset``: the manifest lists exactly the spec's archives, and every local
    archive it lists exists and matches its SHA-256."""
    name = plan.spec.name
    try:
        verify_dataset(plan.spec, manifest, data_dir)
    except DataError as exc:
        log(f"VERIFY {name} invalid: {exc}")
        problems.append(f"verify of {name} is invalid: {exc}")
        return
    local = sum(entry["status"] != "missing" for entry in manifest["files"])
    log(
        f"VERIFY {name} valid: {len(manifest['files'])} files match the spec, and "
        f"{local} local archives match their SHA-256"
    )


def coverage(
    plan: Plan, manifest: dict[str, Any], log: fetch_full_range.Log, problems: list[str]
) -> None:
    """One line per symbol, then each archive that is missing or unreadable, which are
    problems: none of the seven coins is expected to lack a month. Months with gaps are
    reported in the line's counts, not as problems."""
    for symbol in plan.spec.symbols:
        entries = [e for e in manifest["files"] if e["symbol"] == symbol]
        found = Counter(entry["status"] for entry in entries)
        present = [e for e in entries if e["status"] == "ok"]
        expected = sum(
            fetch_full_range.complete_stats(INTERVAL, e["month"])["rows"] for e in entries
        )
        rows = sum(entry["rows"] for entry in present)
        complete = sum(fetch_full_range.digest_row(e).endswith(" full") for e in present)
        log(
            f"COVERAGE {symbol}: {len(entries)} files {entries[0]['month']}..{entries[-1]['month']}"
            f"; ok {found['ok']}, missing {found['missing']}, unreadable {found['unreadable']}"
            f"; complete months {complete}; rows {rows} of {expected} expected"
        )
    absent = [e for e in manifest["files"] if e["status"] != "ok"]
    for entry in absent:
        name = fetch_full_range.file_name(entry)
        reason = f": {entry['reason']}" if entry["status"] == "unreadable" else ""
        log(f"ABSENT {name} {entry['status']}{reason}")
    for status in ("missing", "unreadable"):
        months = [f"{e['symbol']} {e['month']}" for e in absent if e["status"] == status]
        if months:
            problems.append(f"{len(months)} archive(s) {status}: {', '.join(months)}")


def checks(
    plan: Plan,
    manifest: dict[str, Any],
    args: argparse.Namespace,
    log: fetch_full_range.Log,
    problems: list[str],
) -> None:
    """Step 5 of the module docstring, after the digest is written. A check that raises is
    a problem naming it, with its traceback in the log, and the next check still runs."""
    steps: list[tuple[str, Callable[[], None]]] = [
        ("verify", lambda: verify(plan, manifest, args.data_dir, log, problems)),
        ("coverage", lambda: coverage(plan, manifest, log, problems)),
    ]
    for command, step in steps:
        try:
            step()
        except Exception as exc:
            log(traceback.format_exc().rstrip())
            problems.append(f"{command} of {plan.spec.name} raised {type(exc).__name__}: {exc}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_dir", type=Path, help="where every file goes (data/v3-1-minute-bars)")
    parser.add_argument("--spec", type=Path, default=SPEC, help="the minute-bars spec")
    # For the tests of start and wait only: sleep that long, then end, fetching nothing.
    parser.add_argument("--fake-run", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--fake-raise", action="store_true", help=argparse.SUPPRESS)
    return parser


def start(arguments: list[str]) -> int:
    """Launch the run (the same options as a foreground run) as a detached child, once, and
    only from the reviewed task text (``TASK_SHA256``). ``fetch_full_range.start`` with this
    script's task and child: it would launch that script's run."""
    args = _parser().parse_args(arguments)  # a mistyped option fails here, not in the child
    digest = fetch_full_range.task_digest(TASK)
    if digest != TASK_SHA256:
        print(
            f"NOT STARTED: the task file {TASK.name} is not the reviewed text (its SHA-256 "
            f"without the pin block is {digest}); report it, and start nothing"
        )
        return 1
    data_dir: Path = args.data_dir
    files = fetch_full_range.run_files(data_dir)
    if files.exit.exists():
        print(f"NOT STARTED: the run in {data_dir.as_posix()} has ended ({files.exit.as_posix()})")
        return 1
    try:
        pid = fetch_full_range._pid(files.pid)
    except ValueError as exc:
        print(f"NOT STARTED: {exc}; report it, and start nothing")
        return 1
    if pid is not None and fetch_full_range._alive(pid):
        print(f"NOT STARTED: the run in {data_dir.as_posix()} is still running")
        return 1
    data_dir.mkdir(parents=True, exist_ok=True)
    if files.log.exists() and (data_dir / "run-1.log").exists():
        # The task allows one restart: a third attempt would fetch everything a third time.
        print(
            f"NOT STARTED: the run in {data_dir.as_posix()} was already restarted once. "
            f"{fetch_full_range.NEXT_GONE_AGAIN.removeprefix('NEXT: ')}"
        )
        return 1
    if files.log.exists():  # an earlier attempt that was lost (wait said GONE): keep its log
        attempt = 1
        while (data_dir / f"run-{attempt}.log").exists():
            attempt += 1
        files.log.replace(data_dir / f"run-{attempt}.log")
    # The child imports the same crypto_grid_bot as this process, whatever else is installed.
    source = str(Path(dataset.__file__).resolve().parents[2])
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
            **fetch_full_range._detached(),
        )
    _LAUNCHED.append(child)
    files.pid.write_text(f"{child.pid}\n", encoding="utf-8")
    print(f"STARTED pid {child.pid}; log {files.log.as_posix()}; exit file {files.exit.as_posix()}")
    return 0


def _now() -> datetime:
    return datetime.now(UTC)


def record(
    arguments: list[str],
    *,
    fetcher: Fetcher,
    sleep: Callable[[float], None],
    now: Callable[[], datetime],
) -> int:
    """The child that start launches: the run, then its exit status in the exit file, also
    after a traceback, which goes to the log."""
    files = fetch_full_range.run_files(_parser().parse_args(arguments).data_dir)
    code = 1
    try:
        code = run(arguments, fetcher=fetcher, sleep=sleep, now=now)
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


# The report tools and wait are fetch_full_range.py's; only start is this script's own.
TOOLS: dict[str, Callable[[list[str]], int]] = {
    **fetch_full_range.TOOLS,
    "start": start,
}


def main(
    argv: Sequence[str] | None = None,
    *,
    fetcher: Fetcher = archive_get,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _now,
) -> int:
    """A subcommand (the background run's, or a report tool), or the run in the foreground."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = arguments[0] if arguments else ""
    if command in TOOLS:
        return TOOLS[command](arguments[1:])
    if command == RECORD:
        return record(arguments[1:], fetcher=fetcher, sleep=sleep, now=now)
    return run(arguments, fetcher=fetcher, sleep=sleep, now=now)


def run(
    argv: Sequence[str],
    *,
    fetcher: Fetcher = archive_get,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = _now,
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
    log = fetch_full_range.Log()
    problems: list[str] = []
    requests: fetch_full_range.Requests | None = None
    digest: Path | None = None
    try:
        plan = make_plan(args, log)
        requests = fetch_full_range.Requests(fetcher, plan.paths, sleep, log)
        digest, manifest = fetch(plan, args, requests, log, problems, now)
        checks(plan, manifest, args, log, problems)
    finally:
        # Even after a traceback (a checksum failure, a lasting FeedError, OutOfScope), the
        # log must say how many requests went out, and to which months.
        if requests is not None:
            fetch_full_range.log_requests(requests, args.data_dir, log)
    digest_bytes = digest.stat().st_size
    total = log.bytes + digest_bytes
    form = "as text" if total <= fetch_full_range.REPORT_LIMIT else "compressed (append-results)"
    log(
        f"REPORT run log {log.bytes} bytes before this line and digest {digest_bytes} "
        f"bytes: {total} bytes; the report takes them {form} (limit "
        f"{fetch_full_range.REPORT_LIMIT})"
    )
    for problem in problems:
        log(f"PROBLEM {problem}")
    log(f"RESULT {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
