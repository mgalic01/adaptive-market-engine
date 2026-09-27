# Task for Bob: P8 archives for G and H, development months only

- **Written by:** Claude, 2026-09-27. Spec v1 prerequisite P8
  ([`EXPERIMENT_SPEC_V1.md`](../EXPERIMENT_SPEC_V1.md) §2, §3 G and §3 H) is still open:
  "Not yet done" in [the G signal handoff](../reviews/2026-09-25-claude-g-funding-signal.md).
- **Review:** starts automatically when this file is merged, so **Codex reviews it
  first**. The merge is the go.
- **Report:** `docs/reviews/2026-09-27-bob-p8-funding-archives.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), all of it.
- **Read-only:** no change to code, tests, configs, dataset specs or manifests. You
  fetch, verify and measure; the manifest change is proposed in your report and made
  later in a reviewed code PR.

## Why

G needs the BTCUSDT USDⓈ-M funding-rate archives, checksummed and in each dataset's
manifest. H needs each traded pair's daily closes from the 2020-05-11 halving, but the
two development datasets hold daily bars only from their `daily_warmup_start` (P3):
2021-09 for `practice-2022` and 2023-05 for `verify-2024h1`. This run fetches and
verifies both, with the project's own parser and checksum conventions, and reports the
exact manifest entries they would add. It runs no replay and produces no strategy
result.

## Scope (fixed)

| Data | Files | Months |
| --- | --- | --- |
| Funding: `/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-YYYY-MM.zip` and its `.CHECKSUM` | 60 | 2020-01 to 2024-12, the same 60 months as your cadence report (PR #19) |
| Daily for H, `practice-2022`: BTCUSDT, SOLUSDT, XRPUSDT (traded and proxy) | 48 | 2020-05 to 2021-08 |
| Daily for H, `verify-2024h1`: ADAUSDT, BTCUSDT (traded and proxy) | 72 | 2020-05 to 2023-04 |

- **Daily** months end the month before each dataset's `daily_warmup_start`, so no
  planned file is already in a committed manifest (the script checks this). BTCUSDT is
  in both datasets; its 16 shared months are fetched once: **104** distinct daily files.
- **Proposed manifest entries:** funding for each dataset's hourly span, the months
  of `DatasetSpec.months()` (warm-up start to end): 2022-04 to 2023-01 for
  `practice-2022` (10), 2023-11 to 2024-06 for `verify-2024h1` (8). Daily as above.
- **Reserved window, out of scope:**
  - The **last month allowed is 2024-12**. Nothing for 2025-01 or later is requested,
    opened or listed. No directory listing of any kind is requested.
  - The reserved window's funding is **out of scope**.
  - Spec P8 also names daily history from 2024-04 for the reserved window. This task
    **leaves that part out entirely**, the stricter of the two options: no
    reserved-window dataset, manifest or entry is created or proposed, and no daily
    month after 2023-04 is requested.
- **Out of scope:** any replay or backtest run (`python -m crypto_grid_bot.backtest`),
  any variant, and any G decision: the script builds `FundingSignal` only as an
  integrity check (it raises on a duplicate scheduled time) and **never calls
  `FundingSignal.state()`**. Also out: code, spec or manifest changes, and deciding the
  manifest schema.

## How the 2024-12 limit is enforced in code

The script in the last section of this file, copied unchanged:
- `allowed(month)` raises `OutOfScope` for any month after `LAST_MONTH = "2024-12"`
  (or before 2020-01, or not `YYYY-MM`). `OutOfScope` is a `BaseException`, so no
  `except Exception` or `except DataError` can swallow it.
- Every month is passed through `allowed` when the plan is built, before any request.
  The script also stops if the plan's latest month is after 2024-12.
- **Requested:** the only two network functions, `kline_get` and `funding_get`, accept
  only a full archive or `.CHECKSUM` path for one of the planned symbols
  (`re.fullmatch`, so no directory, prefix or query string), and call `allowed` on its
  month before connecting.
- **Opened:** `open_funding` calls `allowed` before reading. `fetch_file` opens a
  daily archive only after `kline_get` has passed its checksum request.
- **Listed:** no path that is not a single file can pass the two patterns.
- `--self-test` proves the guard with the network disabled: 2025-01 is refused by
  `allowed`, by both network functions (zip and `.CHECKSUM`), by `funding_file`, by
  `open_funding` and by `month_range`, and a directory and a query-string path are
  refused. Only the two 2024-12 cases reach the (disabled) network.
- At the end of the real run, every requested path is written to `data/p8/requests.txt`,
  and the script reports the latest requested month and the count after 2024-12, which
  must be 0.
- After the run, a `find` over `data/` must show no file for 2025 or later. The
  workflow runs the same check and fails the run if one exists.

## Data access

- Daily archives: `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol,
  "1d", month, kline_get)`, where `kline_get` checks the path and then calls the
  project's `archive_get`. It verifies each zip against Binance's `.CHECKSUM` and parses
  it with `read_archive`, as in PRs #59, #60, #65 and #66. A hash-verified month the
  strict parser rejects raises `ArchiveParseError`; the script records it as
  `unparsed` with the error and continues.
- Funding archives: the project has no funding fetcher yet (`archive_get` accepts only
  spot kline paths). `funding_file` follows `fetch_file`'s conventions exactly:
  - the same host `data.binance.vision`, through the project's `https_connection`;
  - 404 means missing; any other non-200 status is an error, and redirects are never
    followed;
  - the published `.CHECKSUM` must name the file, and the SHA-256 of the body must match
    before the file is written (atomically, with `dataset._write_atomic`);
  - the local path mirrors `local_path`:
    `data/binance/data/futures/um/monthly/fundingRate/BTCUSDT/<file>`.

  Each archive is then parsed with
  `crypto_grid_bot.backtest.funding.read_funding_archive(path, "BTCUSDT", month)`.
- A transport error (`FeedError`) is retried at most twice, 10 s apart, and every
  attempt is printed (`RETRY` lines). A third failure is a traceback: stop.
- Data files stay under `data/`, which git ignores. Nothing under `data/` is committed.

## Steps

Run every command from the repository root, in this order. Paste each command and its
output into the report.

1. `date -u`, `git rev-parse HEAD`, `python --version`.
2. Copy the script out of this file, byte for byte, and check its hash:

   ```text
   mkdir -p data
   sed -n '228,676p' docs/tasks/2026-09-27-bob-p8-funding-archives.md > data/p8_archives.py
   sha256sum data/p8_archives.py
   ```

   The hash must be exactly:

   `0cd92cfd4f3f8de606593cdcbd23dcfc22808af656aa128104cfd471ca58a3e5`

   Do not edit the script. If the hash differs, or the script fails in a way this task
   does not describe, stop and report; never patch it.
3. The guard self-test, with the network disabled inside the script:

   ```text
   python data/p8_archives.py --self-test > data/p8-selftest.log 2>&1; echo "exit $?"
   cat data/p8-selftest.log
   ```

4. The real run (about 330 requests to `data.binance.vision`; a few minutes):

   ```text
   python data/p8_archives.py > data/p8-run.log 2>&1; echo "exit $?"
   cat data/p8-run.log
   ```

5. Hashes of what the run produced, and the reserved-window file check:

   ```text
   sha256sum data/p8_archives.py data/p8-selftest.log data/p8-run.log data/p8/requests.txt data/p8/*.additions.json
   find data -type f | grep -cE -- '-20(2[5-9]|[3-9][0-9])-[0-9]{2}\.(zip|csv|zip\.CHECKSUM)$'
   ```

   The `grep -c` must print `0` (its exit status is then 1, which is expected).
6. Write the report (below), then:

   ```text
   git status --porcelain --untracked-files=all
   python scripts/check_reports.py
   date -u
   ```

## Validity checks (all must hold for a valid run)

1. Step 2: the script's SHA-256 is exactly the one stated there.
2. Step 3: `exit 0`, 17 `SELFTEST` case lines each showing its expected outcome,
   `SELFTEST requests that reached the (disabled) network: 2` and
   `SELFTEST wrong outcomes: 0`.
3. Step 4: `exit 0` and the last line `RESULT 0 problem(s)`, which the script prints
   only when all of these hold:
   - all 60 funding archives match their published checksums (a mismatch is already a
     traceback);
   - every month's record count, first and last `calc_time` equal your PR #19 table
     (`docs/reviews/2026-09-25-bob-funding-cadence.md`), and every count is 3 per day;
   - the known values: 5,481 records, `funding_interval_hours` 8 for all of them, 0
     invalid records, 0 steps other than 8 hours, the largest offset past the hour
     47 ms at `calc_time` 1631865600047 (PR #19); SOLUSDT daily 2020-05 to 2020-07
     missing and 2020-08 first open 1597104000000 (2020-08-11 00:00 UTC, your P8
     survey); no other daily file missing; the latest daily month 2023-04;
   - `FundingSignal` builds over all 5,481 records without a duplicate scheduled time;
   - no planned daily file is already in a committed manifest;
   - `REQUESTS ...; latest month 2024-12; after 2024-12: 0`;
   - `CONFIG config/datasets unchanged: True`.
4. Step 5: the `find | grep -c` count is `0`.
5. Step 6: `git status` shows only your report; `check_reports.py` prints
   `0 problem(s)`.

A daily file recorded as `unparsed` is a finding, not a failure: report it with its
error line.

## What to report

`docs/reviews/2026-09-27-bob-p8-funding-archives.md`:
- the commit, Python version, `date -u` at the start and end, and every command with
  its output (long tables once, in their sections below);
- **the first time the report names `data/p8_archives.py` in backticks, put its SHA-256
  on the same line right after it** (`scripts/check_reports.py` takes the first 64-hex
  value within 200 characters of that name). Put its source in an appendix, under a
  level-2 heading that names `data/p8_archives.py` in backticks, in a `text` fence,
  then the check `sed -n '<first>,<last>p' <report> | sha256sum` showing the same hash;
- the self-test output;
- **Funding, per month:** the script's table (records, expected, first and last
  `calc_time`, `funding_interval_hours` distribution, invalid records, largest offset,
  bytes, SHA-256), the `FUNDING` summary lines, and the PR #19 comparison table;
- **Daily, per file:** the script's table (status, rows, expected, missing, gaps, first
  and last open, bytes, SHA-256), the `DAILY` line and every `UNPARSED` line;
- the known-values table;
- **Manifest diff:** the script's "Proposed manifest additions" table, the SHA-256 of
  each `data/p8/<dataset>.additions.json`, and the `CONFIG` lines showing that the
  committed specs and manifests did not change. State plainly that the additions are
  a proposal: funding entries have no `interval` and a new `kind`, and an `unparsed`
  status is not in the manifest schema, so `load_manifest` would reject them today;
- the `REQUESTS` line and the `find` count;
- **Ideas and proposals** (separate), each checked against your own tables first, for
  example the manifest schema the funding entries need, or what an `unparsed` daily
  month means for H. Report facts in the results; questions for Claude and Codex go
  here.

## Stop conditions

Stop, keep everything, and report what you have, with the full error, if:
- the script's hash differs from Step 2, or any `OutOfScope` is raised in the real run;
- any request, file or read would touch 2025-01 or later, or anything lists a
  directory;
- a checksum is missing or mismatches, or a funding archive fails to parse (a
  traceback);
- a transport error persists after two retries;
- the run ends with `RESULT` other than `0 problem(s)`: report every `PROBLEM` line,
  facts only; do not rerun with changes or work around it;
- anything asks for a login or key, or anything else is unexpected.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items.
Every count in the report is printed by the script or by a command you ran.

## The script (`data/p8_archives.py`, lines 228 to 676 of this file)

```text
"""P8 archives for G and H, development months only.

Task: docs/tasks/2026-09-27-bob-p8-funding-archives.md. Run from the repository root:
python data/p8_archives.py --self-test, then python data/p8_archives.py
"""

import collections
import hashlib
import http.client
import json
import re
import sys
import time
from pathlib import Path

from crypto_grid_bot.backtest.dataset import (
    ARCHIVE_HOST,
    MAX_ZIP_BYTES,
    ArchiveParseError,
    _write_atomic,
    archive_get,
    fetch_file,
    load_manifest,
    load_spec,
    local_path,
    sha256_file,
)
from crypto_grid_bot.backtest.funding import FundingSignal, read_funding_archive
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.market_data.client import FeedError, https_connection
from crypto_grid_bot.market_data.parsing import DataError

LAST_MONTH = "2024-12"  # the reserved window starts 2025-01 and is out of scope
FIRST_MONTH = "2020-01"
H_FIRST = "2020-05"  # month of the 2020-05-11 halving (spec section 3 H)
DATASETS = ("practice-2022", "verify-2024h1")
DATA = Path("data")
OUT = DATA / "p8"
HOUR_MS = 3_600_000
KLINE = re.compile(
    r"/data/spot/monthly/klines/(ADAUSDT|BTCUSDT|SOLUSDT|XRPUSDT)/1d/"
    r"\1-1d-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?"
)
FUNDING = re.compile(
    r"/data/futures/um/monthly/fundingRate/BTCUSDT/"
    r"BTCUSDT-fundingRate-(\d{4}-\d{2})\.zip(?:\.CHECKSUM)?"
)
FUNDING_SUM = re.compile(r"([0-9a-f]{64})  (BTCUSDT-fundingRate-\d{4}-\d{2}\.zip)\n?")
PR19 = Path("docs/reviews/2026-09-25-bob-funding-cadence.md")
PR19_ROW = re.compile(r"^\| (\d{4}-\d{2}) \| [^|]+ \| (\d+) \| (\d+) \| (\d+) \| (\S+) \|$", re.M)
REQUESTED: list[str] = []


class OutOfScope(BaseException):
    """A BaseException, so no handler for Exception or DataError can swallow it."""


def allowed(month: str) -> str:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise OutOfScope(f"not a YYYY-MM month: {month!r}")
    if not FIRST_MONTH <= month <= LAST_MONTH:
        raise OutOfScope(f"month {month} is outside {FIRST_MONTH}..{LAST_MONTH}")
    return month


def month_range(first: str, last: str) -> list[str]:
    months, month = [], first
    while month <= last:
        months.append(allowed(month))
        year, number = int(month[:4]), int(month[5:])
        month = f"{year + number // 12}-{number % 12 + 1:02d}"
    return months


def previous(month: str) -> str:
    year, number = int(month[:4]), int(month[5:])
    return f"{year - (number == 1)}-{(number - 2) % 12 + 1:02d}"


def kline_get(path: str) -> bytes | None:
    found = KLINE.fullmatch(path)
    if found is None:
        raise OutOfScope(f"not a planned 1d archive path: {path}")
    allowed(found.group(2))
    REQUESTED.append(path)
    return archive_get(path)


def funding_get(path: str) -> bytes | None:
    found = FUNDING.fullmatch(path)
    if found is None:
        raise OutOfScope(f"not a planned funding archive path: {path}")
    allowed(found.group(1))
    REQUESTED.append(path)
    connection = https_connection(ARCHIVE_HOST, timeout=60)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read(MAX_ZIP_BYTES + 1)
    except (OSError, http.client.HTTPException) as exc:
        raise FeedError(f"transport failed for {path}") from exc
    finally:
        connection.close()
    if response.status == 404:
        return None
    if response.status != 200:  # a redirect (3xx) is an error too, never followed
        raise FeedError(f"HTTP {response.status} for {path}")
    if len(body) > MAX_ZIP_BYTES:
        raise FeedError(f"size limit exceeded for {path}")
    return body


def funding_path(month: str) -> str:
    return f"/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{allowed(month)}.zip"


def funding_file(month: str) -> dict:
    """fetch_file's checksum convention, for one BTCUSDT funding archive."""
    path = funding_path(month)
    name = path.rsplit("/", 1)[1]
    target = DATA / "binance" / path.lstrip("/")
    entry = {"kind": "fundingRate", "symbol": "BTCUSDT", "month": month}
    entry["url"] = f"https://{ARCHIVE_HOST}{path}"
    checksum = funding_get(path + ".CHECKSUM")
    if checksum is None:
        if funding_get(path) is not None:
            raise DataError(f"{path} is published without a checksum")
        return {**entry, "status": "missing"}
    match = FUNDING_SUM.fullmatch(checksum.decode("ascii"))
    if match is None or match.group(2) != name:
        raise DataError(f"unexpected checksum file for {path}")
    expected = match.group(1)
    if not target.exists() or sha256_file(target) != expected:
        body = funding_get(path)
        if body is None:
            raise DataError(f"{path} has a checksum but no archive")
        if hashlib.sha256(body).hexdigest() != expected:
            raise DataError(f"{path} does not match Binance's published SHA-256")
        _write_atomic(target, body)
    if sha256_file(target) != expected:
        raise DataError(f"{target} does not match its checksum after writing")
    return {**entry, "status": "ok", "sha256": expected, "bytes": target.stat().st_size}


def open_funding(month: str) -> list:
    return read_funding_archive(
        DATA / "binance" / funding_path(month).lstrip("/"), "BTCUSDT", month
    )


def retried(call, *args):
    for attempt in (1, 2, 3):
        try:
            return call(*args)
        except FeedError as exc:
            print(f"RETRY attempt {attempt} of {call.__name__}{args[-2:]}: {exc}", flush=True)
            if attempt == 3:
                raise
            time.sleep(10)
    raise AssertionError("unreachable")


def self_test() -> int:
    class Network(Exception):
        pass

    def no_network(*_args, **_kwargs):
        raise Network

    globals()["https_connection"] = globals()["archive_get"] = no_network
    kline = "/data/spot/monthly/klines/BTCUSDT/1d/BTCUSDT-1d-{}.zip"
    funding = "/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-{}.zip"
    cases = [
        (allowed, "2024-12", "allowed"),
        (allowed, "2020-01", "allowed"),
        (allowed, "2025-01", "OutOfScope"),
        (allowed, "2019-12", "OutOfScope"),
        (allowed, "2024-1", "OutOfScope"),
        (kline_get, kline.format("2024-12"), "network"),
        (kline_get, kline.format("2025-01"), "OutOfScope"),
        (kline_get, kline.format("2025-01") + ".CHECKSUM", "OutOfScope"),
        (kline_get, "/data/spot/monthly/klines/BTCUSDT/1d/", "OutOfScope"),
        (funding_get, funding.format("2024-12") + ".CHECKSUM", "network"),
        (funding_get, funding.format("2025-01"), "OutOfScope"),
        (funding_get, funding.format("2025-01") + ".CHECKSUM", "OutOfScope"),
        (funding_get, "/data/futures/um/monthly/fundingRate/BTCUSDT/", "OutOfScope"),
        (funding_get, funding.format("2024-12") + "?prefix=x", "OutOfScope"),
        (funding_file, "2025-01", "OutOfScope"),
        (open_funding, "2025-01", "OutOfScope"),
        (month_range, "2024-11", "OutOfScope"),  # second argument below: 2025-02
    ]
    wrong = 0
    for call, argument, want in cases:
        args = (argument, "2025-02") if call is month_range else (argument,)
        try:
            call(*args)
            got = "allowed"
        except OutOfScope:
            got = "OutOfScope"
        except Network:
            got = "network"
        wrong += got != want
        print(f"SELFTEST {call.__name__}{args} -> {got} (expected {want})")
    print(f"SELFTEST requests that reached the (disabled) network: {len(REQUESTED)}")
    print(f"SELFTEST wrong outcomes: {wrong}")
    return 1 if wrong else 0


def config_hashes() -> dict:
    return {p.as_posix(): sha256_file(p) for p in sorted(Path("config/datasets").glob("*.*"))}


def main() -> int:
    problems: list[str] = []
    hashes_before = config_hashes()
    OUT.mkdir(parents=True, exist_ok=True)
    specs = {name: load_spec(Path(f"config/datasets/{name}.toml")) for name in DATASETS}
    funding_months = month_range(FIRST_MONTH, LAST_MONTH)
    plan_daily, plan_funding = {}, {}
    for name, spec in specs.items():
        pairs = sorted({*spec.traded, spec.market_proxy})
        months = month_range(H_FIRST, previous(spec.daily_warmup_start))
        plan_daily[name] = [(pair, month) for pair in pairs for month in months]
        plan_funding[name] = [allowed(month) for month in spec.months()]
        existing = {
            (f["symbol"], f["interval"], f["month"])
            for f in load_manifest(Path(f"config/datasets/{name}.manifest.json"))["files"]
        }
        overlap = [x for x in plan_daily[name] if (x[0], "1d", x[1]) in existing]
        print(
            f"PLAN {name}: 1d {pairs} {months[0]}..{months[-1]} = {len(plan_daily[name])} files, "
            f"already in manifest {len(overlap)}; funding {plan_funding[name][0]}.."
            f"{plan_funding[name][-1]} = {len(plan_funding[name])} months"
        )
        if overlap:
            problems.append(f"{name}: planned 1d files already in the manifest: {overlap}")
    unique_daily = sorted({x for plan in plan_daily.values() for x in plan})
    every = funding_months + [m for _, m in unique_daily]
    print(
        f"PLAN funding months {len(funding_months)}, unique 1d files {len(unique_daily)}, "
        f"latest month {max(every)}"
    )
    if max(every) > LAST_MONTH:
        raise OutOfScope(f"planned month {max(every)} is after {LAST_MONTH}")

    funding, records_all = {}, []
    for month in funding_months:
        entry = retried(funding_file, month)
        if entry["status"] != "ok":
            problems.append(f"funding {month}: {entry['status']}")
            funding[month] = entry
            continue
        records = open_funding(month)
        start, end = month_bounds_ms(month)
        intervals = collections.Counter(
            "empty" if r.interval_hours is None else str(r.interval_hours) for r in records
        )
        entry.update(
            records=len(records),
            expected_records=3 * (end - start) // 86_400_000,
            first_calc_time_ms=records[0].calc_time_ms if records else None,
            last_calc_time_ms=records[-1].calc_time_ms if records else None,
            interval_hours=dict(sorted(intervals.items())),
            invalid_records=sum(not r.valid for r in records),
            max_offset_ms=max((r.calc_time_ms - r.scheduled_ms for r in records), default=None),
        )
        funding[month] = entry
        records_all += records

    steps = [
        (a, b, b.scheduled_ms - a.scheduled_ms)
        for a, b in zip(records_all, records_all[1:], strict=False)
    ]
    not_8h = [
        (a.calc_time_ms, b.calc_time_ms, s // HOUR_MS) for a, b, s in steps if s != 8 * HOUR_MS
    ]
    not_previous = sum(
        a.interval_hours is None or s != a.interval_hours * HOUR_MS for a, _, s in steps
    )
    offset = max(records_all, key=lambda r: r.calc_time_ms - r.scheduled_ms)
    try:
        FundingSignal(records_all)
        signal = "constructed; no duplicate scheduled time"
    except DataError as exc:
        signal = f"DataError: {exc}"
        problems.append(f"FundingSignal: {exc}")

    daily = {}
    for symbol, month in unique_daily:
        try:
            daily[symbol, month] = retried(fetch_file, DATA, symbol, "1d", month, kline_get)
        except ArchiveParseError as exc:
            daily[symbol, month] = {
                "symbol": symbol,
                "interval": "1d",
                "month": month,
                "status": "unparsed",
                "error": str(exc),
                "sha256": sha256_file(local_path(DATA, symbol, "1d", month)),
            }

    print("\n## Funding archives, BTCUSDT, per month\n")
    print(
        "| Month | Status | Records | Expected (3 per day) | First calc_time | Last calc_time "
        "| funding_interval_hours | Invalid | Max offset ms | Bytes | SHA-256 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for month, e in funding.items():
        print(
            f"| {month} | {e['status']} | {e.get('records')} | {e.get('expected_records')} | "
            f"{e.get('first_calc_time_ms')} | {e.get('last_calc_time_ms')} | "
            f"{e.get('interval_hours')} | {e.get('invalid_records')} | {e.get('max_offset_ms')} | "
            f"{e.get('bytes')} | {e.get('sha256')} |"
        )
    totals = collections.Counter()
    for e in funding.values():
        totals.update(e.get("interval_hours", {}))
    ok_months = sum(e["status"] == "ok" for e in funding.values())
    print(
        f"\nFUNDING months ok {ok_months} of {len(funding)}; "
        f"records {len(records_all)}; interval_hours {dict(totals)}; "
        f"invalid {sum(e.get('invalid_records', 0) for e in funding.values())}"
    )
    print(
        f"FUNDING steps {len(steps)}; not 8 h {len(not_8h)} {not_8h[:20]}; "
        f"not equal to the previous record's interval {not_previous}; "
        f"duplicates {sum(s == 0 for _, _, s in steps)}"
    )
    print(
        f"FUNDING largest offset past the hour {offset.calc_time_ms - offset.scheduled_ms} ms "
        f"at calc_time {offset.calc_time_ms}; FundingSignal {signal}"
    )

    pr19 = {
        m: (int(r), int(f), int(la)) for m, r, f, la, _ in PR19_ROW.findall(PR19.read_text("utf-8"))
    }
    print(f"\n## Comparison with PR #19 ({PR19}, {len(pr19)} month rows)\n")
    print("| Month | Records | PR #19 rows | First equal | Last equal | Records = expected |")
    print("| --- | --- | --- | --- | --- | --- |")
    for month, e in funding.items():
        mine = (e.get("records"), e.get("first_calc_time_ms"), e.get("last_calc_time_ms"))
        theirs = pr19.get(month, (None, None, None))
        row = (
            mine[0] == theirs[0],
            mine[1] == theirs[1],
            mine[2] == theirs[2],
            e.get("records") == e.get("expected_records"),
        )
        print(f"| {month} | {mine[0]} | {theirs[0]} | {row[1]} | {row[2]} | {row[3]} |")
        if not all(row):
            problems.append(
                f"funding {month} differs from PR #19 or from 3 per day: {mine} {theirs}"
            )

    print("\n## Daily (1d) archives, 2020-05 up to each dataset's daily_warmup_start\n")
    print(
        "| Pair | Month | Status | Rows | Expected | Missing | Gaps | First open ms | Last open ms "
        "| Bytes | SHA-256 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for (symbol, month), e in daily.items():
        print(
            f"| {symbol} | {month} | {e['status']} | {e.get('rows')} | {e.get('expected_rows')} | "
            f"{e.get('missing_rows')} | {e.get('gaps')} | {e.get('first_open_ms')} | "
            f"{e.get('last_open_ms')} | {e.get('bytes')} | {e.get('sha256')} |"
        )
        if e["status"] == "unparsed":
            print(f"UNPARSED {symbol} {month}: {e['error']}")
    statuses = collections.Counter(e["status"] for e in daily.values())
    print(f"\nDAILY files {len(daily)}; by status {dict(statuses)}")

    print("\n## Known values\n")
    sol_missing = [daily["SOLUSDT", m]["status"] for m in ("2020-05", "2020-06", "2020-07")]
    known = [
        ("funding months ok", ok_months, 60),
        ("funding records, all months", len(records_all), 5481),
        ("funding interval_hours values", dict(totals), {"8": 5481}),
        ("funding invalid records", sum(e.get("invalid_records", 0) for e in funding.values()), 0),
        ("funding steps not 8 h", len(not_8h), 0),
        ("funding largest offset ms", offset.calc_time_ms - offset.scheduled_ms, 47),
        ("funding largest offset calc_time", offset.calc_time_ms, 1631865600047),
        ("SOLUSDT 1d 2020-05..2020-07 status", sol_missing, ["missing"] * 3),
        (
            "SOLUSDT 1d 2020-08 first open ms",
            daily["SOLUSDT", "2020-08"].get("first_open_ms"),
            1597104000000,
        ),
        ("latest 1d month planned", max(m for _, m in unique_daily), "2023-04"),
        (
            "1d files missing other than SOLUSDT 2020-05..07",
            sum(e["status"] == "missing" for e in daily.values()) - sol_missing.count("missing"),
            0,
        ),
    ]
    print("| Figure | Measured | Known | Equal |")
    print("| --- | --- | --- | --- |")
    for figure, measured, expected in known:
        print(f"| {figure} | {measured} | {expected} | {measured == expected} |")
        if measured != expected:
            problems.append(f"known value differs: {figure}: {measured} != {expected}")

    print("\n## Proposed manifest additions (the committed manifests are not changed)\n")
    print(
        "| Dataset | 1d entries | 1d by status | 1d months | Funding entries | Funding months "
        "| Additions file SHA-256 |"
    )
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name in DATASETS:
        additions = {
            "dataset": name,
            "assumes": {"daily_warmup_start": H_FIRST},
            "manifest_sha256": hashes_before[f"config/datasets/{name}.manifest.json"],
            "daily": [daily[x] for x in plan_daily[name]],
            "funding": [funding[m] for m in plan_funding[name]],
        }
        path = OUT / f"{name}.additions.json"
        path.write_text(json.dumps(additions, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        by_status = dict(collections.Counter(e["status"] for e in additions["daily"]))
        months = sorted({m for _, m in plan_daily[name]})
        print(
            f"| {name} | {len(additions['daily'])} | {by_status} | {months[0]}..{months[-1]} | "
            f"{len(additions['funding'])} | {plan_funding[name][0]}..{plan_funding[name][-1]} | "
            f"{sha256_file(path)} |"
        )

    (OUT / "requests.txt").write_text("\n".join(REQUESTED) + "\n", encoding="utf-8")
    requested_months = [re.search(r"-(\d{4}-\d{2})\.zip", p).group(1) for p in REQUESTED]
    late = [p for p, m in zip(REQUESTED, requested_months, strict=True) if m > LAST_MONTH]
    print(
        f"\nREQUESTS {len(REQUESTED)}; latest month {max(requested_months)}; "
        f"after {LAST_MONTH}: {len(late)}; list in {OUT / 'requests.txt'} "
        f"sha256 {sha256_file(OUT / 'requests.txt')}"
    )
    if late:
        problems.append(f"requests after {LAST_MONTH}: {late}")
    unchanged = config_hashes() == hashes_before
    print(f"CONFIG config/datasets unchanged: {unchanged}")
    for path, digest in hashes_before.items():
        print(f"CONFIG {digest}  {path}")
    if not unchanged:
        problems.append("config/datasets changed during the run")
    for problem in problems:
        print(f"PROBLEM {problem}")
    print(f"RESULT {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(self_test() if sys.argv[1:] == ["--self-test"] else main())
```
