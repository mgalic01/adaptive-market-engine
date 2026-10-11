# Task for Bob: fetch V3.1's flow-gate minute bars, seven coins, 2021-06 to 2024-12

- **Status: not yet run.** It starts when the owner merges the PR that adds this file to
  `main`, or comments `/bob-run docs/tasks/2026-10-11-bob-v3-1-minute-bars-fetch.md`.
  Editing this file never starts a run. Before it starts, the pins must still hold: any
  change under `src` on `main` after the PR's last commit means updating them first (see
  "Pinned inputs").
- **Written by:** Claude, 2026-10-11. The owner approved the fetch itself on 2026-10-11:
  the symbols, interval and months below, each archive checked against Binance's published
  `.CHECKSUM`, and nothing from 2025-01 or later requested, opened or listed. The decision
  is recorded in `docs/V3_1_SOURCE_INVENTORY.md` on PR #269.
- **Report:** `docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), all of it.
- **Read-only:** no change to code, tests, configs, dataset specs or manifests. You fetch,
  verify and measure. Every file the run writes goes under `data/`, which git ignores. The
  manifest is committed later by Claude, in a reviewed PR: Claude rebuilds it from the
  digest in your report and makes no request to Binance.

## Why

V3.1's grid has an order-flow gate, F, that reads the last 15 completed one-minute bars of
each coin and blocks grid buys below a taker-buy share of 0.40 (V3.1 design, Package C). A
coin without those bars cannot open grid buys at all. The experiment covers ten coins.
BTCUSDT, ETHUSDT and XRPUSDT already have their minute bars, 2019-01 to 2024-12, in
`config/datasets/full-range-2017-2024.manifest.json`. The other seven do not.

This run fetches the seven coins' monthly spot 1m archives from data.binance.vision,
through the project's own fetch code, and checks each against Binance's published
`.CHECKSUM`. It writes a manifest and a compact digest under `data/v3-1-minute-bars/`, from
which the manifest can be rebuilt byte for byte, and runs `verify_dataset` on it. It runs no
replay and produces no strategy result.

## Scope (fixed)

| Item | Value |
| --- | --- |
| Symbols | ADAUSDT, BNBUSDT, DOGEUSDT, LINKUSDT, LTCUSDT, SOLUSDT, TRXUSDT |
| Interval | 1m, spot, monthly archives |
| Months | 2021-06 to 2024-12 inclusive: 43 |
| Archives | 7 symbols x 43 months = 301 archives (the spec's `required()`) |
| Requests | 602 requests: a `.CHECKSUM` and an archive for each of the 301 files |

- **Request count.** `REQUESTS` says 602 plus one for each `RETRY` line: a failed attempt
  is asked again, and every attempt is counted. A month Binance does not publish costs the
  same two requests, a `.CHECKSUM` and then the archive, which must be a 404 too. The script
  refuses every other path.
- **Expected `missing` files: none.** The committed hourly inventory
  (`config/datasets/v3-20261009/inventory.manifest.json`) holds a published spot archive for
  each of the seven coins from 2020-08 at the latest (SOLUSDT), before this window starts.
  If an archive is missing anyway, the digest row is `<name> missing`, the log has a `KLINES`
  count, an `ABSENT` line and a `PROBLEM` line naming the symbol and month, and `RESULT` is
  not 0. That is a finding to report, not a stop: Steps 5 and 6 still run, and nothing is
  substituted or fetched in its place. An archive that is published but unreadable is
  reported the same way, with its reason.
- **Months with holes are expected and are no problem.** In the committed digest of the
  three coins already held, 165 of the 216 minute months are complete, and the others
  lack some minutes. The digest row of such a month says how many (`rows=...`, `gaps=...`).
  The flow gate treats a missing minute as unavailable flow, so the holes matter later, not
  to this run.
- **Reserved window, out of scope:** the last month allowed is 2024-12. Nothing for
  2025-01 or later is requested, opened or listed. No directory listing of any kind is
  requested.
- **Out of scope:** any replay or backtest run, hourly, daily or funding archives, exchange
  filters and `exchangeInfo` (data-api.binance.vision and the futures host), BTCUSDT,
  ETHUSDT and XRPUSDT, any change to code, specs or manifests, and any request to another
  host.

## The script

`scripts/fetch_minute_bars.py` is committed with its tests
(`tests/test_fetch_minute_bars.py`, which run it against a fake host with the network
blocked). Its docstring says what it does, step by step, and defines the digest's format. No
existing script could fetch this set: `scripts/fetch_full_range.py` fetches two backtest
windows whose specs also list hourly and funding archives, with filters for three pairs
only, and `scripts/fetch_v3_data.py` fetches 1h archives. The new script reuses what they
build on, unchanged: `fetch_dataset`, the checksum rule and the repairing reader of
`crypto_grid_bot.backtest.dataset`, and `fetch_full_range.py`'s `Requests`, digest rows,
`wait` and report tools. In short:
1. **Plan.** It loads the spec,
   `config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.toml`, which refuses any month
   after 2024-12, lists its 301 archives and 602 paths, and copies the spec into
   `data/v3-1-minute-bars/`, where the manifest is written next to the copy.
2. **Fetch,** one symbol at a time, logging each as `FETCHED`. An archive is stored only if
   it matches Binance's published SHA-256. It is then read strictly, and if that fails by
   the repairing reader (spec v1 section 5 rule 1), so it is recorded as `ok` with its
   statistics or as `unreadable` with the reason. A month Binance does not publish is
   `missing`.
3. **The manifest,** in the dataset manifest format with no exchange filters, written
   atomically and loaded again from disk (`KLINES`, `MANIFEST`).
4. **The digest:** `data/v3-1-minute-bars/v3-1-minute-bars-2021-2024.digest.txt`, written as
   soon as the manifest is, before any check runs, so that no later failure can lose it. The
   script rebuilds the manifest from it and compares the two byte for byte (`DIGEST`).
5. **The checks.** `verify_dataset` (`VERIFY`: the manifest lists exactly the spec's
   archives, and every local archive matches its SHA-256), one `COVERAGE` line per symbol,
   and an `ABSENT` line for each archive that is missing or unreadable. A check that raises
   is a `PROBLEM` naming it, with its traceback in the log, and the next check still runs.

The run takes the background route of the earlier fetch: `start` launches it as a detached
child process, and `wait` reports on it, so that no single command lasts more than about 9
minutes and none needs more than `python`. The script also does for the report what shell
utilities would: the clock, a file's last lines, sizes, the reserved-window check,
appending to the report. `fetch_full_range.py`'s docstring lists these report tools.

How the limits hold in code:
- Every request goes through the script's `Requests`. It passes only the 602 planned
  archive and `.CHECKSUM` paths. Any other path raises `OutOfScope`, a `BaseException`,
  before any connection. A planned request then goes to the project's `archive_get`. Its
  host is fixed (data.binance.vision), it accepts only canonical monthly spot kline paths,
  and it refuses a month after 2024-12 again on its own.
- The spec loader refuses a spec that reaches 2025-01, and the plan refuses a planned
  month after 2024-12. The `REQUESTS` line gives the latest month requested and the count
  after 2024-12, which must be 0.
- A transport failure, or an HTTP status other than 200 and 404, is a `FeedError`. It is
  retried, 4 attempts in all, 1, 2 and 4 seconds apart, and each failed attempt prints a
  `RETRY` line. A fourth failure is a traceback.
- A checksum mismatch is never retried. It raises a `DataError`, and the run ends with a
  traceback.
- The `REQUESTS` line, and `data/v3-1-minute-bars/requests.txt`, are written even when the
  run ends in a traceback.

## Pinned inputs

The runner checks out whatever `main` is when the job starts. So Step 2 checks, before any
request, that the code and inputs are the ones reviewed here:
- **The whole package, by its git tree.** `git rev-parse HEAD:src` must print exactly
  `d7b4fa9f4b09c43b9f6a8eadcf12f7a823ad307f`, the tree of `src` at `1eacae1`, the commit of
  `main` this task was written on. That covers every module the run can import, not only
  the data path: `dataset`, `klines`, `window`, `jobs`, `config` and the rest. `git status`
  must also show no local change under `src`.
- **Four files by SHA-256:** the script and its test as this task's PR adds them,
  `scripts/fetch_full_range.py`, which the script imports, and the spec. Step 2 copies the
  block below out of this file:

```text
424dd2a092838bd8219540350959f18d9f7de693029ed979cd913d5f6cf3f795  scripts/fetch_minute_bars.py
df652ca79f4ce7083cc7e17b71fcf42bcd720b8b28f3850b8b6bee87705405b3  tests/test_fetch_minute_bars.py
c41005ef04d10efdc72bb03033947e65e54116d18318973b41171b77fcc81dbd  scripts/fetch_full_range.py
24c021daa5eab53335a66828601423bfadf7c7effff8f80d6ef5dfd4984c61d3  config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.toml
```

If the tree hash differs, `git status` lists a change under `src`, or any `sha256sum` line
says `FAILED`, stop before Step 3 and report by the pin-failure path in "Stop conditions",
which runs no script.

This file cannot pin itself, and the runner reads it as `main` has it when the job starts.
So the pinned script checks it: Step 4's `start` reads this file's text, all of it but the
pin block above, and starts nothing unless its SHA-256 is the one the reviewed script
holds. It then prints `NOT STARTED: the task file ... is not the reviewed text`, a stop.
**Any change under `src` on `main` before this file merges changes the tree hash, so the
pins must be updated in its PR before the owner's go.**

## Steps

Run every command from the repository root, in this order, and no other command.
bob-task.yml allows `python`, the project's CLIs, `pytest`, `sha256sum` and read-only
`git`, so every command below is one of those:
- Steps 1 and 2 run before the script is checked, so they use only `python -c`, `git`
  and `sha256sum`.
- From Step 3 on, the script's own subcommands do what shell utilities would.

Your tool shows each command's exit status: a non-zero status where this task expects
success is a stop (see "Stop conditions").

1. The clock, the commit, the Python version, and the `data` directory:

   ```text
   python -c "import time; print(time.strftime('%a %b %d %H:%M:%S UTC %Y', time.gmtime()))"
   git rev-parse HEAD
   python --version
   python -c "import pathlib; pathlib.Path('data').mkdir(exist_ok=True); print('data ready')"
   ```

2. The pins (see "Pinned inputs"). These four commands must print, in order:
   - the tree hash given there;
   - nothing at all;
   - `4 pins`;
   - four lines that each end in `OK`.

   ```text
   git rev-parse HEAD:src
   git status --porcelain --untracked-files=no -- src
   python -c "from pathlib import Path; t = Path('docs/tasks/2026-10-11-bob-v3-1-minute-bars-fetch.md').read_text(encoding='utf-8'); b = t.split('## Pinned inputs', 1)[1].split('\x60\x60\x60text\n', 1)[1].split('\x60\x60\x60', 1)[0]; Path('data/minute-bars-pins.txt').write_text(b, encoding='utf-8', newline='\n'); print(len(b.splitlines()), 'pins')"
   sha256sum -c data/minute-bars-pins.txt
   ```

3. The script's tests, offline (a fake host; about a minute):

   ```text
   python -m pytest -p no:cacheprovider tests/test_fetch_minute_bars.py > data/minute-bars-tests.log 2>&1
   python scripts/fetch_minute_bars.py tail data/minute-bars-tests.log
   ```

   The last line must report `24 passed`. Add no `-q`: `pyproject.toml` already passes
   one, and a second one hides that line.
4. The run: 602 requests to data.binance.vision, then `verify_dataset`. The archives
   total roughly 600 MB (the 216 minute archives in the committed digest average 2 MB).
   Expect roughly 15 to 30 minutes, an estimate and not a measurement; the job allows 240.
   That may be longer than one command should last, so the script runs itself in the
   background, and you wait for it in steps of under 10 minutes. Start it once:

   ```text
   python scripts/fetch_minute_bars.py start data/v3-1-minute-bars
   ```

   It prints `STARTED pid <n>; log data/v3-1-minute-bars/run.log; exit file
   data/v3-1-minute-bars/run.exit` and returns at once. Then wait:

   ```text
   python scripts/fetch_minute_bars.py wait data/v3-1-minute-bars
   ```

   It returns within about 9 minutes. Every outcome, these three and any error, ends with a
   line starting `NEXT:` that names the next step: follow it, whatever the exit status.
   The three run states exit 0, and it prints one of:
   - `RUNNING pid <n>; latest: <the log's last line>`: run the same `wait` again. The log
     gets a `FETCHED` line as each symbol is done, and is quiet between them.
   - `DONE exit=<status>`, then the log's last lines: the run has ended, and **the report
     is not written yet. DONE is never the end of the task:** go straight on to Step 5 in
     this session, then Step 6, and end with your signed final message. Do not read
     `data/v3-1-minute-bars/run.log` whole: Steps 5 and 6 take what they need from it
     through the script.
   - `GONE pid <n>: no process and no exit file; ...`: the run was lost without ending
     (the script writes the exit file even after a traceback). Run the same `start` once
     more, unchanged: stored archives are reused while their checksum matches, so only
     `.CHECKSUM` requests repeat, and the first attempt's log is kept as
     `data/v3-1-minute-bars/run-1.log`. Then `wait` again. That is the only restart: if it
     is lost a second time, `wait`'s `NEXT:` line says so, `start` refuses a third attempt,
     and you write the report with what exists (Steps 5 and 6).

   **Never end your session before Step 6 has written the report and you have given your
   signed final message,** whatever a command prints. An earlier fetch of this kind (run
   37591538301, issue #195) ended right after a `wait`, with no report, and its work was
   lost.

   `start` refuses while a run is alive, and after one has ended, so it cannot start a
   second run by mistake. Say in 6b how many waits it took, and whether `start` ran twice.

5. The hashes of everything the run wrote, every log included, then the sizes and the
   reserved-window file check:

   ```text
   sha256sum data/minute-bars-tests.log data/v3-1-minute-bars/run*.log data/v3-1-minute-bars/run.exit data/v3-1-minute-bars/*.toml data/v3-1-minute-bars/*.json data/v3-1-minute-bars/*.txt data/v3-1-minute-bars/rebuilt/*.json
   python scripts/fetch_minute_bars.py measure data/v3-1-minute-bars data
   ```

   The second command prints the bytes of every run log and of the digest. The run logs
   are `run.log`, and one `run-<n>.log` for each lost attempt. Then it prints
   `RESERVED-WINDOW FILES 0`; any other count is a stop.
6. Write the report `docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md` in **five
   steps, 6a to 6e, in this order**. Complete each step before starting the next.

   **What you write by hand.** Only three short passages: 6a, 6b and 6d.
   - Create the report in 6a with your file-writing tool: the file is new and short.
   - For 6b and 6d, write the passage to its own new file (`data/mb-6b.md`,
     `data/mb-6d.md`), then append it with this command, giving the passage's file:

     ```text
     python scripts/fetch_minute_bars.py append docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md data/mb-6b.md
     ```

   - **After 6a, never write or edit the report with a file tool.** It holds the
     verbatim run logs and digest, and rewriting them by hand would change them.

   **Keep the report under 200,000 bytes.** `validate_bob_artifact.py` refuses a larger
   report, and then nothing is published. The run log and digest are expected to take about
   70,000 bytes in all, and the three hand-written passages about 8,000: about 3,000 for
   6a (its four `OK` lines included), 2,000 for 6b and 3,000 for 6d. Keep the passages
   short this way:
   - quote only the part of a log line that shows the result (self-check 1 in
     `docs/BOB_PRACTICE.md`), never a whole long line: every line is already in the run log;
   - copy no table, list or log line a second time;
   - check each passage file's bytes before you append it, for example with
     `python scripts/fetch_minute_bars.py size data/mb-6b.md`.

   **Rules for everything you write by hand:**
   - **Only append.** Nothing is ever inserted above text that is already in the report.
   - **Write no `*.py` path in backticks.** Write repository paths without backticks, or
     quote whole log lines in a `text` fence. `scripts/check_reports.py` reads a
     backticked `*.py` path with a 64-hex value near it as a pinned script, and would
     report a problem: the script is in the repository, not in an appendix.
   - Do **not** edit `docs/reviews/README.md`. Every new review file carries its own
     index entry.

   **6a. Header and Steps 1 to 3, by hand** (about 40 lines). Create the report with:
   - the `# ` title as the first line;
   - one `Index: ` line within the first 20 lines, giving the outcome in one line;
   - the commit, the Python version and the clock at the start;
   - a `## Steps 1 to 3` section with each command and its output: Step 1's, Step 2's
     tree hash, empty status, `4 pins` and four `OK` lines, and the last line of Step 3.

   **6b. Steps 4 and 5, by hand** (about 15 lines). Write to `data/mb-6b.md`, then append
   it with the command above. It is a `## Steps 4 and 5` section with:
   - the Step 4 commands, the `STARTED` line, how many waits it took, and the `DONE` line;
   - each Step 5 command with its full output.

   **6c. The run logs and the digest, by command:**

   ```text
   python scripts/fetch_minute_bars.py append-results docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md data/v3-1-minute-bars
   ```

   It appends every run log, then the digest, each under its own heading in a `text`
   fence: a lost attempt's log first (`Run log, attempt 1 (lost)`), then `Run log`, then
   `Digest`.
   - **Compression.** It appends them as text when they fit within 190,000 bytes, which
     they should. If not, it compresses the digest (zlib, then base64), and the logs too if
     that is still not enough, each compressed block with its file's SHA-256 and the exact
     command that decodes it.
   - **Checks.** It then reads every block back from the report. It prints one `APPENDED
     ...; reads back: True` line for each block, then the total. Any `False`, or a
     `NOT APPENDED` line, is a stop.
   - **The digest always goes in,** whatever the `PROBLEM` lines say (see "Stop
     conditions"). Only a run with no digest file has none: one that ended with a
     traceback.
   - Do not copy any appended line again.

   **6d. Results and ideas, by hand** (under about 50 lines). Write to `data/mb-6d.md`,
   then append it with the command above:
   - A `## Results` section:
     - the `RESULT` line, and for each validity check below whether it holds, quoting the
       part of the log line that shows it;
     - the `PLAN` lines (301 files, 602 paths) and the seven `FETCHED` lines;
     - the `KLINES` line, with its `missing` count against the 0 expected, and whether
       any `unreadable` appears;
     - the `VERIFY` line;
     - the seven `COVERAGE` lines, and every `ABSENT` line;
     - the `REQUESTS` line against 602 plus the number of `RETRY` lines (count them with
       the run log, not by eye), Step 5's `RESERVED-WINDOW FILES` count, and the `REPORT`
       line;
     - for each block 6c appended, whether it went in as text or compressed, and that it
       reads back;
     - the SHA-256 of the digest and of the manifest, from the `DIGEST` and `MANIFEST`
       lines, and that the rebuilt manifest's SHA-256 in Step 5 is the same;
     - the plain statement that this run commits no manifest: Claude rebuilds it from the
       digest in a reviewed PR, with no request to Binance.
   - A `## Ideas and proposals` section. Check each idea against the run log first.
     Questions for Claude and Codex go here, not in the results.
   - The clock at the end of the run, from `python scripts/fetch_minute_bars.py now`.

   **6e. The checks, by command.**
   1. Gather the checks into one file, then append it as the final section:

      ```text
      git status --porcelain --untracked-files=all > data/mb-git-status.txt
      python scripts/check_reports.py > data/mb-check-reports.log 2>&1
      python scripts/fetch_minute_bars.py check-log data/mb-git-status.txt data/mb-check-reports.log data/mb-checks.log
      python scripts/fetch_minute_bars.py append docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md data/mb-checks.log --heading Checks
      ```

      `check-log` leaves out the checker's `UNVERIFIABLE` lines on purpose. They are about
      other reports, and they name other scripts in backticks next to hashes. Copied into
      this report, they would read as pins and fail the checker.
   2. Then:

      ```text
      python scripts/check_reports.py
      python scripts/fetch_minute_bars.py size docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md
      ```

      The report is complete when the first ends with `check_reports: 0 problem(s)` and
      the second says `under the 200000-byte limit`. Quote both lines in your final
      message. If the second says `AT OR OVER`, the report would be refused: say so in your
      final message and change nothing (self-check 10).

   `data/mb-checks.log` must contain these lines, in any order the checker chooses, and a
   clock line at the end:
   - `?? docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md` (git status, nothing
     else);
   - `check_reports: 0 problem(s)`.

   Other `check_reports:` lines about other reports are expected: their `verified` and
   `corrected` lines, and the counts of stated hashes and script mentions. A line of this
   list that is missing, or any line that names a problem with this report, is a real
   problem: stop and report.

## Validity checks (all must hold for a valid run)

1. Step 2: the pinned tree hash, an empty `git status`, `4 pins` and four `OK` lines.
2. Step 3: `24 passed`.
3. Step 4: `wait` prints `DONE exit=0`, and the run log's last line is
   `RESULT 0 problem(s)`, which the script prints only when all of these hold:
   - `PLAN` names 301 files and 602 planned paths, and seven `FETCHED` lines each say
     `43 files; ok 43`;
   - the `KLINES` line says `301 files; ok 301`, with no `missing` and no `unreadable`;
   - `VERIFY ... valid: 301 files match the spec, and 301 local archives match their
     SHA-256`;
   - `DIGEST ... rebuilds the manifest byte for byte: True`;
   - no check raised.
4. Step 4: the `REQUESTS` line says `latest month 2024-12; after 2024-12: 0`, its count is
   602 plus the number of `RETRY` lines, and there is no `OutOfScope` and no traceback.
5. Step 5: `RESERVED-WINDOW FILES 0`.
6. Step 6: every `APPENDED` line of 6c ends `reads back: True`, and `data/mb-checks.log`
   holds the lines listed at the end of Step 6.

## What to report

`docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md`, written in steps 6a to 6e as above:
- the commit, the Python version, and the clock at the start and the end;
- every command with its output, the long ones appended by command;
- every run log and the digest (6c), each once;
- the results (6d): the `RESULT` line and each validity check; the `PLAN`, `FETCHED`,
  `KLINES`, `VERIFY`, `COVERAGE`, `REQUESTS` and `REPORT` lines; how each block went in;
  the digest's and the manifest's SHA-256; and the statement that this run commits no
  manifest;
- the checks (6e);
- **Ideas and proposals** (6d, separate from the results), each checked against the run
  log first.

## Hand-back to Claude

Nothing of this run is committed by Bob. What Claude needs is in the report:
- the digest, verbatim (6c), and its SHA-256 and the manifest's, in the `DIGEST` and
  `MANIFEST` lines (6d);
- from them, Claude rebuilds the manifest in a later reviewed PR, with `rebuild` from the
  pinned script and the committed spec, writes it with `write_manifest`, and checks that its
  SHA-256 is the one in the `MANIFEST` line. The digest and the manifest are then committed
  as `config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.digest.txt` and
  `.manifest.json`, which `.gitattributes` already keeps LF. That PR makes no request to
  Binance.
- the archives themselves stay on the runner, under the git-ignored `data/`, and are gone
  with it. The manifest records each archive's SHA-256, so a later fetch can be checked
  against it. How the replay obtains the bars is a later decision, and not part of this task.

## Stop conditions

There are three kinds of stop:
- **The run ended with a `RESULT` line.** `wait` printed `DONE exit=0` or
  `DONE exit=1`, and the log's last line is `RESULT`.
  - Complete Steps 5 and 6 in full, 6c included, whatever the `PROBLEM` lines say: a
    missing archive, an unreadable archive, `verify_dataset` not valid, a digest that does
    not rebuild, or a check that raised.
  - The script writes the digest as soon as the manifest exists, before any check runs.
    The digest is what rebuilds the manifest, so it always reaches the report.
  - "Stop" then means: no rerun, no change and no workaround. A missing or unreadable
    month is reported with its symbol and month; nothing is fetched in its place.
- **Step 1 or Step 2 failed** (the clock, the commit, or any pin): the script and its tests
  are not the reviewed ones, so **run nothing else: not `scripts/fetch_minute_bars.py` in
  any form, not its report subcommands, and not `python -m pytest`.** An unreviewed script
  can read an argument it does not know as a data directory and start a fetch. Write the
  report file directly with your edit tool instead, as one new file
  `docs/reviews/2026-10-11-bob-v3-1-minute-bars-fetch.md`:
  - first line `# Bob: v3-1-minute-bars fetch stopped at the pins`;
  - within the first 20 lines, a line starting `Index: ` that names the failed check;
  - every Step 1 and Step 2 command with its output, verbatim, the failing line included;
  - one sentence saying that nothing was fetched and the pins need updating in a new PR.
- **Anything else after Step 2 passed** (the tests, a traceback with no `RESULT` line):
  stop where you are. Keep everything, and write the report with what you have, by the
  same steps: 6a, 6b, 6c if a run log exists, 6d and 6e, with the full error.

Report each of these:
- the tree hash differs, `git status` lists a change under `src`, any pin says `FAILED`,
  or the tests in Step 3 fail;
- a checksum mismatches or is missing: a traceback naming "does not match Binance's
  published SHA-256", "unexpected checksum file", "published without a checksum" or "has
  a checksum but no archive";
- any request would go to another host, any `OutOfScope` is raised, or any request, file
  or read would touch 2025-01 or later, or anything lists a directory;
- a transport error persists through 4 attempts (a traceback after
  `RETRY attempt 4 of 4`);
- `wait` prints `GONE` after the second `start` as well;
- an archive is `missing` or `unreadable` (a `PROBLEM` line and an `ABSENT` line): none is
  expected, so name each symbol and month and its reason, facts only;
- `verify_dataset` is not valid, or a check raised (a `PROBLEM` line naming `verify` or
  `coverage` and the exception; its traceback is in the run log);
- 6c prints `NOT APPENDED`, or a block that does not read back;
- the run ends with `RESULT` other than `0 problem(s)`: report every `PROBLEM` line,
  facts only; do not rerun with changes or work around it;
- anything asks for a login or key, or anything else is unexpected.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items:
- apply items 1, 2 and 4 to 11 to each hand-written passage before you append it;
- item 3 is Step 6e.

Where that file names a shell command, use the script instead:
- for the clock (item 8), `python scripts/fetch_minute_bars.py now`;
- for a path check (item 2), `python scripts/fetch_minute_bars.py exists PATH ...`.

After a pin failure (Step 1 or Step 2), run neither: take the clock from Step 1's output,
and check paths by reading the files with your read tool.

From 6c on, change nothing already in the report; an error found later goes in your final
message. Every count in the report is printed by the script or by a command you ran.
