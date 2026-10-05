# Task for Bob: P8 archives for G and H, development months only

- **Status: done; do not rerun.** Run 36560170480 on 2026-09-29; report merged in PR #164
  (closing #133). The hashes pinned below describe that run. A new fetch needs a new task file.
- **Written by:** Claude, 2026-09-27, while spec v1 prerequisite P8 (§2, §3 G and §3 H) was open.
- **Revised** after Codex's review of PR #113 (Codex Desktop comment 5858830916 and
  the Cloud findings): the Step 6 checker condition, pinned inputs, and daily
  completeness. **Revised again on 2026-09-28** (Codex's Cloud P1: a tested project
  fetcher before this task runs): the script now calls
  `crypto_grid_bot.backtest.dataset.fetch_funding_file`, which PR #113 adds with its
  tests; Step 6 follows PR #116's index scheme; the pins are the files as PR #113
  merges them. **Revised again on 2026-09-28 (revision 4, by Bob):** Step 6 split into
  sequential appends after two runs failed while writing the report (issue #133).
  **Revision 5 (2026-09-28, Claude session `e0b16be3`, after the owner reassigned
  PR #138):** the logs, the tables and the script are appended to the report by
  commands, byte for byte, and never retyped. Only three short passages and a two-line
  check are written by hand, each to a file under `data/` and appended by command. The
  script is unchanged (same SHA-256). Its line range in this file moved, and
  Step 2 names the new one. The expected checker lines are the ones the checker prints.
- **Review:** editing this file does not start a run. After this revision merges, the
  run is started with `/bob-run docs/tasks/2026-09-27-bob-p8-funding-archives.md`
  under the owner's go (2026-09-28, PR #138).
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
  month before connecting. Both then call the project's `archive_get`, which accepts
  only a canonical spot kline or USDT-M funding archive path and refuses a reserved
  month again on its own (`development_month`), so the guard holds twice.
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

## Pinned inputs

The runner checks out whatever `main` is when the job starts, which may be later than
the commit reviewed here. So the script's first action, before any request, compares
the SHA-256 of ten inputs with the values reviewed in this task (`INPUTS`, git blobs at
`main` `58edafe`):
- the two dataset specs and their manifests;
- your PR #19 cadence report, whose table the script compares against;
- `backtest/dataset.py`, `backtest/funding.py`, `backtest/klines.py`,
  `market_data/client.py` and `market_data/parsing.py`.

It prints one `INPUT ok` or `INPUT CHANGED` line per file. If any input changed, it
prints `RESULT 1 problem(s)` and exits 1 without a single request: stop and report.
Record `git rev-parse HEAD` in Step 1 as well.

## Data access

- Daily archives: `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol,
  "1d", month, kline_get)`, where `kline_get` checks the path and then calls the
  project's `archive_get`. It verifies each zip against Binance's `.CHECKSUM` and parses
  it with `read_archive`, as in PRs #59, #60, #65 and #66. A hash-verified month the
  strict parser rejects raises `ArchiveParseError`; the script records it as
  `unparsed` with the error and continues.
- **Daily completeness (P3):** every expected day must be present once and contiguous.
  A daily file that is `unparsed`, or `ok` with `missing_rows` or `gaps` other than 0,
  is an `INCOMPLETE` line and a `PROBLEM`. The only exceptions are SOLUSDT before its
  listing: 2020-05 to 2020-07 must be `missing`, and 2020-08 must start at 2020-08-11
  00:00 UTC with exactly 10 missing days and 1 gap (the leading absence).
- Funding archives: `crypto_grid_bot.backtest.dataset.fetch_funding_file(Path("data"),
  "BTCUSDT", month, funding_get)`, the project's fetcher (added by PR #113 with
  network-free tests: allowed and forbidden paths, every HTTP status, checksum failure,
  the reserved-month guard). It shares `fetch_file`'s code for the checksum rule:
  - the same host `data.binance.vision`, through the project's `archive_get`;
  - 404 means missing; any other non-200 status is an error, and redirects are never
    followed;
  - the published `.CHECKSUM` must name the file, and the SHA-256 of the body must match
    before the file is written (atomically); a cached file is reused only while it
    matches;
  - the local path is `funding_local_path`:
    `data/binance/data/futures/um/monthly/fundingRate/BTCUSDT/<file>`.

  The fetcher parses each stored archive with
  `crypto_grid_bot.backtest.funding.read_funding_archive(path, "BTCUSDT", month)` (a
  rejection is `ArchiveParseError`); the script opens it again with `open_funding` for
  the per-month measures.
- A transport error (`FeedError`) is retried at most twice, 10 s apart, and every
  attempt is printed (`RETRY` lines). A third failure is a traceback: stop.
- Data files stay under `data/`, which git ignores. Nothing under `data/` is committed.

## Steps

Run every command from the repository root, in this order. Each command and its output
goes into the report as Step 6 says: short output by hand, long output appended by
command.

1. `date -u`, `git rev-parse HEAD`, `python --version`.
2. Copy the script out of this file, byte for byte, and check its hash:

   ```text
   mkdir -p data
   sed -n '423,900p' docs/tasks/2026-09-27-bob-p8-funding-archives.md > data/p8_archives.py
   sha256sum data/p8_archives.py
   ```

   The hash must be exactly:

   `35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e`

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
6. Write the report `docs/reviews/2026-09-27-bob-p8-funding-archives.md` in **seven
   steps, 6a to 6g, in this order**. Complete each step before starting the next.

   **What you write by hand.** Only three short passages (6a, 6c and 6e, each under
   about 50 lines) and the two-line check in 6f.
   - Create the report in 6a with your file-writing tool: the file is new and short.
   - For 6c, 6e and 6f, write the passage to its own new file (`data/p8-6c.md`,
     `data/p8-6e.md`, `data/p8-6f.md`), then append it with this command, giving the
     file name as the argument:

     ```text
     python -c "import sys; from pathlib import Path; t = Path(sys.argv[1]).read_text(encoding='utf-8'); f = Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md').open('a', encoding='utf-8', newline='\n'); f.write('\n' + t + ('' if t.endswith('\n') else '\n')); f.close()" data/p8-6c.md
     ```

   - **After 6a, never write or edit the report with a file tool.** It holds the
     verbatim logs, and rewriting it is the long generation that failed twice (issue
     #133).

   **What is appended by command.** Everything long goes in byte for byte and is never
   retyped: the self-test log, the run log with all its tables, the script, and the
   checker output. A retyped script would also fail its hash.

   **Rules for everything you write by hand:**
   - **Only append.** Nothing is ever inserted above text that is already in the
     report.
   - **Name no `*.py` path in backticks other than `` `data/p8_archives.py` ``,** and
     write no SHA-256 near a backticked `*.py` path, except for 6a's pin. Write
     repository paths and log lines without backticks, or quote whole log lines in a
     `text` fence. The checker reads a backticked `*.py` name with a 64-hex value near
     it as a pin, and would report a problem.
   - Do **not** edit `docs/reviews/README.md`. Since PR #116 that table is frozen and
     pinned by hash, and every new review file carries its own index entry.

   **6a. Header and Steps 1–3, by hand** (about 30 lines). Create the report with:
   - The `# ` title as the first line.
   - One `Index: ` line within the first 20 lines, giving the outcome in one paragraph
     (`python scripts/check_reports.py --index` prints the whole index).
   - A line that names `` `data/p8_archives.py` `` in backticks and puts its SHA-256
     **on the same line, right after it**:
     `35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e`
     (`scripts/check_reports.py` takes the first 64-hex value within 200 characters of
     the first backticked mention).
   - The commit, the Python version and `date -u` at the start.
   - A `## Steps 1 to 3` section with the Step 1 and Step 2 commands and their output,
     and the Step 3 command with its `exit` line.

   **6b. The self-test log, by command:**

   ```text
   python -c "import sys; from pathlib import Path; t = Path(sys.argv[1]).read_text(encoding='utf-8'); f = Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md').open('a', encoding='utf-8', newline='\n'); f.write('\n\x60\x60\x60text\n' + t + ('' if t.endswith('\n') else '\n') + '\x60\x60\x60\n'); f.close()" data/p8-selftest.log
   ```

   **6c. Steps 4 and 5, by hand** (about 15 lines). Write to `data/p8-6c.md`, then
   append it with the command at the top of Step 6:
   - a `## Steps 4 and 5` section: the Step 4 command and its `exit` line, and every
     Step 5 command with its full output (the `sha256sum` lines and the `find` count);
   - one sentence saying that the run log follows verbatim, with every table in it.

   **6d. The run log, by command.** This is the same command as 6b, with the run log:

   ```text
   python -c "import sys; from pathlib import Path; t = Path(sys.argv[1]).read_text(encoding='utf-8'); f = Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md').open('a', encoding='utf-8', newline='\n'); f.write('\n\x60\x60\x60text\n' + t + ('' if t.endswith('\n') else '\n') + '\x60\x60\x60\n'); f.close()" data/p8-run.log
   ```

   The run log holds every table this task asks for:
   - the funding per-month table and the `FUNDING` lines;
   - the PR #19 comparison;
   - the daily table, with the `DAILY`, `UNPARSED` and `INCOMPLETE` lines;
   - the known values;
   - the proposed manifest additions;
   - the `INPUT`, `RETRY`, `REQUESTS`, `CONFIG`, `PROBLEM` and `RESULT` lines.

   Do not copy any of them again.

   **6e. Results and ideas, by hand** (under about 50 lines). Write to `data/p8-6e.md`,
   then append it with the command at the top of Step 6:
   - A `## Results` section:
     - the `RESULT` line;
     - for each of Validity checks 1 to 4, whether it holds, quoting the log line that
       shows it;
     - the `REQUESTS` line and the `find` count from Step 5;
     - `CONFIG config/datasets unchanged: True`;
     - the SHA-256 of each `data/p8/<dataset>.additions.json` (from Step 5);
     - the plain statement that the manifest additions are a **proposal**. Funding
       entries have no `interval` and a new `kind`, and an `unparsed` status is not in
       the manifest schema, so `load_manifest` would reject them today.
   - A `## Ideas and proposals` section. Check each idea against the tables in the run
     log first. Questions for Claude and Codex go here, not in the results.
   - `date -u` at the end of the run.

   **6f. The script appendix, by command, then its check.**
   1. Append the heading and the script:

      ```text
      python -c "from pathlib import Path; s = Path('data/p8_archives.py').read_text(encoding='utf-8'); f = Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md').open('a', encoding='utf-8', newline='\n'); f.write('\n## Appendix: \x60data/p8_archives.py\x60\n\n\x60\x60\x60text\n' + s + '\x60\x60\x60\n'); f.close()"
      ```

   2. Print the check command for the appendix, with its line numbers filled in:

      ```text
      python -c "from pathlib import Path; L = Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md').read_text(encoding='utf-8').split('\n'); F = [i for i, l in enumerate(L, 1) if l.startswith('\x60\x60\x60')]; print(f\"sed -n '{F[-2] + 1},{F[-1] - 1}p' docs/reviews/2026-09-27-bob-p8-funding-archives.md | sha256sum\")"
      ```

   3. Run the command it prints. It must print
      `35a4ea2cf36cae67339784fada62063880a41455d1a60316902f93c52363c75e`.
   4. Write two lines to `data/p8-6f.md`, that command and its output, then append the
      file with the command at the top of Step 6.

   **6g. The checks, by command.**
   1. Run the checkers, with their output in one file:

      ```text
      ( git status --porcelain --untracked-files=all; python scripts/check_reports.py > data/p8-check-reports.log 2>&1; s=$?; grep -v '^check_reports: UNVERIFIABLE ' data/p8-check-reports.log; echo "exit $s"; python -c "import sys; sys.path.insert(0, 'scripts'); from pathlib import Path; import check_reports as c; checked = []; problems = c.check_report(Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md'), checked); print('appendix problems:', problems); print('appendix checked:', checked)"; date -u ) > data/p8-checks.log 2>&1
      ```

      The `UNVERIFIABLE` lines are left out on purpose. They are about other reports,
      and they name other scripts in backticks next to hashes. Copied into this
      report, they would read as pins and fail the checker.
   2. Append a final `## Checks` section with that file, byte for byte:

      ```text
      python -c "from pathlib import Path; t = Path('data/p8-checks.log').read_text(encoding='utf-8'); f = Path('docs/reviews/2026-09-27-bob-p8-funding-archives.md').open('a', encoding='utf-8', newline='\n'); f.write('\n## Checks\n\n\x60\x60\x60text\n' + t + ('' if t.endswith('\n') else '\n') + '\x60\x60\x60\n'); f.close()"
      ```

   3. Run `python scripts/check_reports.py; echo "exit $?"` once more. The report is
      complete when that output ends with the two lines `check_reports: 0 problem(s)`
      and `exit 0`. Quote those two lines in your final message, nothing else of it.

   `data/p8-checks.log` must contain these lines, in any order the checker chooses,
   plus one `date -u` line:
   - `?? docs/reviews/2026-09-27-bob-p8-funding-archives.md` (git status, nothing else);
   - `check_reports: verified 2026-09-27-bob-p8-funding-archives.md:data/p8_archives.py`;
   - `check_reports: 0 problem(s)`;
   - `exit 0`;
   - `appendix problems: []`;
   - `appendix checked: ['verified 2026-09-27-bob-p8-funding-archives.md:data/p8_archives.py']`.

   Other `check_reports:` lines about other reports are expected: their `verified` and
   `corrected` lines, and the counts of stated hashes and script mentions.
   `UNVERIFIABLE` lines are filtered out. A line of this list that is missing, or any
   line that names a problem with this report, is a real problem: stop and report.

## Validity checks (all must hold for a valid run)

1. Step 2: the script's SHA-256 is exactly the one stated there.
2. Step 3: `exit 0`, 17 `SELFTEST` case lines each showing its expected outcome,
   `SELFTEST requests that reached the (disabled) network: 2` and
   `SELFTEST wrong outcomes: 0`.
3. Step 4: `exit 0` and the last line `RESULT 0 problem(s)`, which the script prints
   only when all of these hold:
   - all ten pinned inputs print `INPUT ok`;
   - all 60 funding archives match their published checksums (a mismatch is already a
     traceback);
   - every month's record count, first and last `calc_time` equal your PR #19 table
     (`docs/reviews/2026-09-25-bob-funding-cadence.md`), and every count is 3 per day;
   - the known values: 5,481 records, `funding_interval_hours` 8 for all of them, 0
     invalid records, 0 steps other than 8 hours, the largest offset past the hour
     47 ms at `calc_time` 1631865600047 (PR #19); SOLUSDT daily 2020-05 to 2020-07
     missing and 2020-08 first open 1597104000000 (2020-08-11 00:00 UTC, your P8
     survey); no other daily file missing; the latest daily month 2023-04;
   - every daily file is complete (`DAILY incomplete or unparsed ...: 0`), with the
     SOLUSDT listing exceptions above;
   - `FundingSignal` builds over all 5,481 records without a duplicate scheduled time;
   - no planned daily file is already in a committed manifest;
   - `REQUESTS ...; latest month 2024-12; after 2024-12: 0`;
   - `CONFIG config/datasets unchanged: True`.
4. Step 5: the `find | grep -c` count is `0`.
5. Step 6: `data/p8-checks.log` holds the lines listed at the end of Step 6.
   That means:
   - `git status` shows only your report as new, and nothing modified;
   - `check_reports.py` prints `check_reports: 0 problem(s)` with exit 0;
   - the appendix check prints `appendix problems: []` and names the report and
     `data/p8_archives.py`.

   The final `check_reports.py` run after 6g also prints `0 problem(s)`. Before the
   appendix exists, the checker reports one problem: the script is "pinned ... with no
   appendix in this review". That is why the checks run only at the end.

## What to report

`docs/reviews/2026-09-27-bob-p8-funding-archives.md`, written in steps 6a to 6g as
above:
- the commit, Python version, and `date -u` at the start and end;
- every command with its output, the long ones appended verbatim;
- **the first time the report names `data/p8_archives.py` in backticks, its SHA-256 on
  the same line right after it** (6a);
- the self-test log (6b) and the run log (6d), verbatim. The run log holds:
  - **Funding, per month:** the table (records, expected, first and last `calc_time`,
    `funding_interval_hours` distribution, invalid records, largest offset, bytes,
    SHA-256), the `FUNDING` summary lines and the PR #19 comparison table;
  - **Daily, per file:** the table (status, rows, expected, missing, gaps, first and
    last open, bytes, SHA-256), the `DAILY` lines, and every `UNPARSED` and
    `INCOMPLETE` line;
  - the known-values table;
  - the proposed manifest additions;
  - the `INPUT`, `REQUESTS`, `CONFIG` and `RESULT` lines.

  Long tables appear once, in the run log.
- the results (6e):
  - the `RESULT` line and each validity check;
  - the `REQUESTS` line and the `find` count;
  - the SHA-256 of each `data/p8/<dataset>.additions.json`;
  - the plain statement that the manifest additions are a proposal. Funding entries
    have no `interval` and a new `kind`, and an `unparsed` status is not in the
    manifest schema, so `load_manifest` would reject them today;
- the script appendix and its `sed … | sha256sum` check (6f);
- the checks (6g);
- **Ideas and proposals** (6e, separate from the results), each checked against the run
  log's tables first. Examples: the manifest schema that the funding entries need, or
  what an `unparsed` daily month means for H. Report facts in the results; questions
  for Claude and Codex go here.

## Stop conditions

Stop, keep everything, and report what you have, with the full error, if:
- the script's hash differs from Step 2, any `INPUT CHANGED` line appears, or any
  `OutOfScope` is raised in the real run;
- any request, file or read would touch 2025-01 or later, or anything lists a
  directory;
- a checksum is missing or mismatches, or a funding archive fails to parse (a
  traceback);
- a transport error persists after two retries;
- the run ends with `RESULT` other than `0 problem(s)`: report every `PROBLEM` line,
  facts only; do not rerun with changes or work around it;
- anything asks for a login or key, or anything else is unexpected.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items:
apply items 1, 2 and 4 to 11 to each hand-written passage before you append it; item 3
is Step 6g. From 6f on, change nothing already in the report; an error found later
goes in your final message. Every count in the report is printed by the script or by a
command you ran.

## The script (`data/p8_archives.py`, lines 423 to 900 of this file)

```text
"""P8 archives for G and H, development months only.

Task: docs/tasks/2026-09-27-bob-p8-funding-archives.md. Run from the repository root:
python data/p8_archives.py --self-test, then python data/p8_archives.py
"""

import collections
import json
import re
import sys
import time
from pathlib import Path

from crypto_grid_bot.backtest.dataset import (
    ArchiveParseError,
    archive_get,
    fetch_file,
    fetch_funding_file,
    funding_archive_path,
    funding_local_path,
    load_manifest,
    load_spec,
    local_path,
    sha256_file,
)
from crypto_grid_bot.backtest.funding import FundingSignal, read_funding_archive
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.market_data.client import FeedError
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
PR19 = Path("docs/reviews/2026-09-25-bob-funding-cadence.md")
PR19_ROW = re.compile(r"^\| (\d{4}-\d{2}) \| [^|]+ \| (\d+) \| (\d+) \| (\d+) \| (\S+) \|$", re.M)
REQUESTED: list[str] = []
# The reviewed inputs: main at 3b94378 (PR #116), with dataset.py as PR #113 merges it
# (its fetch_funding_file). Any other content stops the run before any request, so the
# evidence cannot come from specs, manifests or code nobody reviewed.
INPUTS = {
    "config/datasets/practice-2022.toml": (
        "f259445fd78d840a5c758026c6ee6bd717ea47656cee228111a397d9fa1d7bdd"
    ),
    "config/datasets/practice-2022.manifest.json": (
        "e8665c9a9e2b3117f4e825989b81a0bfe98dfa42eca84ae81fd236d8092ae288"
    ),
    "config/datasets/verify-2024h1.toml": (
        "a5fda6c8a8c2a78fce986634279890314c94f46523ac8dd1356d0e991df653e4"
    ),
    "config/datasets/verify-2024h1.manifest.json": (
        "48a239f4dfbe923b5a3c9c29336c884c40435617206d5c75b76b8461b0aaa9cf"
    ),
    "docs/reviews/2026-09-25-bob-funding-cadence.md": (
        "b9d3ec73f3f2f7ac39ff1dc4ee85098388dea19659d9e881b91e40844b919d21"
    ),
    "src/crypto_grid_bot/backtest/dataset.py": (
        "9c3b6b5a84b3c58037c85bf32caadf7ae63622bfa612c10beb6f49f9f99150a5"
    ),
    "src/crypto_grid_bot/backtest/funding.py": (
        "34b0558761c9861782351833df5d3f645730a4011fe3be90d70de36082357aee"
    ),
    "src/crypto_grid_bot/backtest/klines.py": (
        "ce12820936efe09f55658c418e8ef65e393f2f56882b320077efef99408491cb"
    ),
    "src/crypto_grid_bot/market_data/client.py": (
        "c6ee5a25a1572957c1115bb56cdab2c5ba714d56d26036b59b6246e1dd8c97a7"
    ),
    "src/crypto_grid_bot/market_data/parsing.py": (
        "5dfb8e837b24e38a95beefccc4efddcc10571f786ee5b563e8f3a60e0bd587c9"
    ),
}
# SOLUSDT was listed on 2020-08-11 (P8 survey): its first daily month is partial.
SOL_FIRST_OPEN_MS = 1597104000000


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
    return archive_get(path)  # the project's fetcher: it refuses the month again itself


def funding_path(month: str) -> str:
    return funding_archive_path("BTCUSDT", allowed(month))


def funding_file(month: str) -> dict:
    """The project's fetch_funding_file (same rules as fetch_file), through funding_get."""
    return fetch_funding_file(DATA, "BTCUSDT", allowed(month), funding_get)


def open_funding(month: str) -> list:
    path = funding_local_path(DATA, "BTCUSDT", allowed(month))
    return read_funding_archive(path, "BTCUSDT", month)


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

    globals()["archive_get"] = no_network
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


def inputs_match() -> bool:
    ok = True
    for path, expected in INPUTS.items():
        actual = sha256_file(Path(path)) if Path(path).is_file() else "absent"
        print(f"INPUT {'ok' if actual == expected else 'CHANGED'} {actual}  {path}")
        ok = ok and actual == expected
    return ok


def main() -> int:
    if not inputs_match():
        print("PROBLEM an input differs from the reviewed one; nothing was requested")
        print("RESULT 1 problem(s)")
        return 1
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
    # P3: every expected day present once and contiguous. The only allowed exceptions are
    # SOLUSDT before its listing: 2020-05..07 missing, 2020-08 starting on 2020-08-11.
    incomplete = []
    for (symbol, month), e in daily.items():
        if symbol == "SOLUSDT" and month in ("2020-05", "2020-06", "2020-07"):
            continue  # checked as known values below
        if symbol == "SOLUSDT" and month == "2020-08" and e["status"] == "ok":
            listing = e["first_open_ms"] == SOL_FIRST_OPEN_MS
            start_ms = month_bounds_ms(month)[0]
            if listing and e["missing_rows"] == (SOL_FIRST_OPEN_MS - start_ms) // 86_400_000:
                if e["gaps"] == 1:  # the leading absence before the listing only
                    continue
        if e["status"] != "ok" or e["missing_rows"] != 0 or e["gaps"] != 0:
            incomplete.append(
                f"{symbol} {month} {e['status']} "
                f"missing {e.get('missing_rows')} gaps {e.get('gaps')}"
            )
    for line in incomplete:
        print(f"INCOMPLETE {line}")
        problems.append(f"daily file incomplete or unparsed: {line}")
    print(f"DAILY incomplete or unparsed (SOLUSDT's listing month excepted): {len(incomplete)}")

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
