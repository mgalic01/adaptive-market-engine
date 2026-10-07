# Task for Bob: fetch full-range-2017-2024 and full-range-2019-2024, stage 2's long windows

- **Status: awaiting the owner's go.** Merging this file into `main` starts the run:
  bob-task.yml runs a task file as soon as a merge adds it. So it merges only on the
  owner's go, after review, and after Tasks 1 to 7 of the long-window data plan are on
  `main` (they are, at `370229d`: the repairing reader, hour masks, the damaged-archive
  fetch, `mask-report` and XRP's quote test).
- **Written by:** Claude, 2026-10-07, as Task 9 of the long-window data plan. Spec v1 §4
  says the two stage-2 windows are not yet runnable until "Bob's re-fetch with daily and
  funding archives" and their manifests exist.
- **Report:** `docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), all of it.
- **Read-only:** no change to code, tests, configs, dataset specs or manifests. You fetch,
  verify and measure. Every file the run writes goes under `data/`, which git ignores.
  The two manifests are committed later by Claude, in a reviewed PR: Claude rebuilds them
  from the digest in your report and makes no request to Binance.

## Why

Spec v1 §4 freezes stage 2's two windows: `full-range-2017-2024`, which is scored, and
`full-range-2019-2024`, which is run and reported only (§5 rule 6). Their dataset specs
are on `main`; their manifests are not. This run fetches every archive both windows need
from data.binance.vision, through the project's own fetch code, and checks each against
Binance's published `.CHECKSUM`. It writes both manifests under `data/full-range/`, runs
`verify` and `mask-report` on them, and writes a compact digest from which both manifests
can be rebuilt byte for byte. It runs no replay and produces no strategy result.

## Scope (fixed)

| Window | Kline files (the spec's `required()`) | BTCUSDT funding archives |
| --- | --- | --- |
| `full-range-2017-2024` (scored) | 1,164: 216 1m (BTCUSDT, ETHUSDT, XRPUSDT, 2019-01 to 2024-12), 711 1h (the nine basket symbols, 2018-06 to 2024-12), 237 1d (the three traded pairs, 2018-06 to 2024-12) | 60: 2020-01 to 2024-12 |
| `full-range-2019-2024` (reported) | 1,080: 198 1m (from 2019-07), 648 1h (from 2019-01), 234 1d (from 2018-07); each is also one of the scored window's 1,164 | the same 60 |

- **Requests:** about 2,450 for the scored window (a `.CHECKSUM` and an archive per
  file), then about 1,165 for the reported window. Its files are already stored by then,
  so these are `.CHECKSUM` requests, besides the archive request of each file Binance
  does not publish. The script refuses every other path.
- **Expected `missing` files,** from #156's manifest at `65a7eb0` (metadata only): the
  hourly months before each listing of SOLUSDT (2018-06 to 2020-07), DOGEUSDT (2018-06
  to 2019-06) and LINKUSDT (2018-06 to 2018-12). That is 46 in the scored window and 25 in
  the reported one, each inside a documented basket absence of its spec. #156's fetch also
  left 108 archives `unparsed` (82 1h and 26 1m, 2018-07 to 2023-03). The fetch now reads
  each of them with the repairing reader and records it as `ok` or `unreadable`.
- **Reserved window, out of scope:** the last month allowed is 2024-12. Nothing for
  2025-01 or later is requested, opened or listed. No directory listing of any kind is
  requested.
- **Out of scope:** any replay or backtest run, any variant, any change to code, specs or
  manifests, and any request to another host. That includes `exchangeInfo`
  (data-api.binance.vision): the exchange filters come from the committed
  `config/datasets/long-bull-bear-2022.manifest.json`, with its `fetched_at`.

## The script

`scripts/fetch_full_range.py` is committed with its tests (`tests/test_fetch_full_range.py`,
which run it against a fake host). Its docstring says what it does, step by step, and
defines the digest's format. In short:
1. **Plan.** It loads both specs. The reported window's files must all be in the scored
   window's, with the same funding months, and no planned month may be after 2024-12. It
   copies both specs into `data/full-range/`, and writes each manifest next to its copy.
2. **Funding.** The 60 funding archives, with `fetch_funding_file`. Every month must be
   `ok`. Otherwise the run prints a `STOP` line naming the months, before any kline
   request and before any manifest is written.
3. **The scored manifest.** `fetch_dataset`, with the committed filters, whose
   `fetched_at` is then restored. The funding entries follow the klines, and
   `write_manifest` writes the file.
4. **The reported manifest.** `fetch_dataset` again, with the scored manifest as
   `previous`, so its funding entries are kept. Every entry must equal the scored
   manifest's entry for the same file.
5. **The digest:** `data/full-range/full-range-2017-2024.digest.txt`, written as soon as
   both manifests are, before any check runs, so that no later failure can lose it. The
   script rebuilds both manifests from it and compares them with the written ones, byte
   for byte.
6. **The checks.** `verify` on both windows and `mask-report` on the scored one, each
   reading its manifest from disk. Their full JSON stays under `data/full-range/`; the
   run log prints a summary of each. A check that raises is a `PROBLEM` naming it, with
   its traceback in the log, and the next check still runs.

Step 4 runs all of this in the background through the script itself: `start` launches
it as a detached child process, and `wait` reports on it, so that no single command
lasts more than about 9 minutes and none needs more than `python`.

How the limits hold in code:
- Every request goes through the script's `Requests`. It passes only the planned archive
  and `.CHECKSUM` paths of the scored window, which include the reported window's. Any
  other path raises `OutOfScope`, a `BaseException`, before any connection. A planned
  request then goes to the project's `archive_get`. Its host is fixed
  (data.binance.vision), it accepts only canonical archive paths, and it refuses a month
  after 2024-12 again on its own.
- `load_spec` refuses a spec that reaches 2025-01, and the plan refuses a planned month
  after 2024-12. The `REQUESTS` line gives the latest month requested and the count after
  2024-12, which must be 0.
- A transport failure, or an HTTP status other than 200 and 404, is a `FeedError`. It is
  retried, 4 attempts in all, 1, 2 and 4 seconds apart, and each failed attempt prints a
  `RETRY` line. A fourth failure is a traceback.
- A checksum mismatch is never retried. `fetch_file`'s rule raises a `DataError`, and the
  run ends with a traceback.
- The `REQUESTS` line, and `data/full-range/requests.txt`, are written even when the run
  ends in a traceback.

## Pinned inputs

The runner checks out whatever `main` is when the job starts. So Step 2 compares the
SHA-256 of 16 files with the values reviewed here: the script and its test as this task's
PR adds them, and the specs, filters, config and data code as they are at `370229d`. If
any line says `FAILED`, stop before Step 3 and report. Step 2 copies the 16 lines of this
block out of this file, byte for byte:

```text
667410f175ad2b4b1d9c132543a23d06f27244296f4a1caf0747ba711637a5cf  scripts/fetch_full_range.py
643f05ba508eddd0a7aeb5f44faea1ef0f5e83c1a0ae49ce22e55a9175422a14  tests/test_fetch_full_range.py
f4216524de089988a15fbddd72a9625a737f41be5a8dcb4bed6a36ccf8e0addb  config/datasets/full-range-2017-2024.toml
8dad70041f4423706b0eeba272595fb24af74cb83713b6316abb68e5a40dafcb  config/datasets/full-range-2019-2024.toml
349ce104be44d28d918b22dc99dd611f56d174011b50cb144393a97940c72374  config/datasets/long-bull-bear-2022.manifest.json
17e7cfc750a31c0f53b0c4be5b8aae8dc99c355bbf49de27c9c6fed53003344f  config/default.toml
4e6396273a22f3877a2ced8d571a2cab9cbb258eb569abebbf5e0785e1e0ab72  src/crypto_grid_bot/backtest/__main__.py
1f392f769210b589c579b3c53b1f775e392ab78928d64a70cf37e39cd78a2716  src/crypto_grid_bot/backtest/dataset.py
9c7ad730491111889bc465487ef700ffd972d0d0706f6ed98c86129bcf0caa04  src/crypto_grid_bot/backtest/funding.py
757dd3f7bd4f93b0f316c69e1e22577b8fa8744f40e41d703974e7fb2af4f30e  src/crypto_grid_bot/backtest/jobs.py
901607255a5b064f107addaa74189bc149e08e6b3b7fd52884fe59ccaf768b10  src/crypto_grid_bot/backtest/klines.py
9e2395fb606f04b34d16ae4c0f6e8a280ded31abf9d9dbd59d9dd11a95a2d96f  src/crypto_grid_bot/backtest/masking.py
fd6527ce5f3d16c43bfd2e7634ea1425ec0fca9b071f5b264c07d01baeaaaefd  src/crypto_grid_bot/backtest/replay.py
9843a785195095233a375563a18628721dca8f05f1a28e7ba4e76ec5124ca533  src/crypto_grid_bot/backtest/window.py
c6ee5a25a1572957c1115bb56cdab2c5ba714d56d26036b59b6246e1dd8c97a7  src/crypto_grid_bot/market_data/client.py
5dfb8e837b24e38a95beefccc4efddcc10571f786ee5b563e8f3a60e0bd587c9  src/crypto_grid_bot/market_data/parsing.py
```

## Steps

Run every command from the repository root, in this order. Step 6 says how each command
and its output go into the report.

1. `date -u`, `git rev-parse HEAD`, `python --version`, and then `mkdir -p data`.
2. The pins, from the block in "Pinned inputs" above. `wc -l` must print 16, every
   `sha256sum` line must end in `OK`, and the last line must be `exit 0`:

   ```text
   sed -n '110,125p' docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md > data/full-range-pins.txt
   wc -l data/full-range-pins.txt
   sha256sum -c data/full-range-pins.txt; echo "exit $?"
   ```

3. The script's tests, offline (a fake host; about a minute):

   ```text
   python -m pytest -p no:cacheprovider tests/test_fetch_full_range.py > data/full-range-tests.log 2>&1; echo "exit $?"
   tail -n 3 data/full-range-tests.log
   ```

   It must print `exit 0`, and the log's last line must report `18 passed`. (Add no `-q`:
   `pyproject.toml` already passes one, and a second one hides that line.)
4. The run: about 3,600 requests to data.binance.vision, `verify` on both windows and
   `mask-report` on the scored one. Expect about an hour; the job allows 240 minutes.
   That is longer than any single command on record here (about 19 minutes), so the
   script runs itself in the background, and you wait for it in steps of under 10
   minutes, with `python` only. Start it once:

   ```text
   python scripts/fetch_full_range.py start data/full-range
   ```

   It prints `STARTED pid <n>; log data/full-range/run.log; exit file
   data/full-range/run.exit` and returns at once. Then wait:

   ```text
   python scripts/fetch_full_range.py wait data/full-range
   ```

   It returns within about 9 minutes and prints one of:
   - `RUNNING pid <n>; latest: <the log's last line>`: run the same `wait` again. The log
     stays quiet for long stretches: after `FUNDING`, nothing comes until the whole scored
     fetch is done.
   - `DONE exit=<status>`, then the log's last lines: the run has ended. Read
     `data/full-range/run.log` in full, then go to Step 5.
   - `GONE pid <n>: no process and no exit file; ...`: the run was lost without ending
     (the script writes the exit file even after a traceback). Run the same `start` once
     more, unchanged: stored archives are reused while their checksum matches, so only
     `.CHECKSUM` requests repeat, and the first attempt's log is kept as
     `data/full-range/run-1.log`. Then `wait` again. If it is lost a second time, stop and
     report.

   `start` refuses while a run is alive, and after one has ended, so it cannot start a
   second run by mistake. Say in 6b how many waits it took, and whether `start` ran twice.

5. The hashes of what the run wrote, the sizes, and the reserved-window file check:

   ```text
   sha256sum data/full-range-tests.log data/full-range/run.* data/full-range/*.toml data/full-range/*.json data/full-range/*.txt
   wc -c data/full-range/run.log data/full-range/full-range-2017-2024.digest.txt
   find data -type f | grep -cE -- '-20(2[5-9]|[3-9][0-9])-[0-9]{2}\.(zip|csv|zip\.CHECKSUM)$'
   ```

   The `grep -c` must print `0` (its exit status is then 1, which is expected).
6. Write the report `docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md` in **six
   steps, 6a to 6f, in this order**. Complete each step before starting the next.

   **What you write by hand.** Only three short passages (6a, 6b and 6e, each under about
   50 lines) and the two-line digest check in 6d.
   - Create the report in 6a with your file-writing tool: the file is new and short.
   - For 6b, 6d and 6e, write the passage to its own new file (`data/fr-6b.md`,
     `data/fr-6d.md`, `data/fr-6e.md`), then append it with this command, giving the
     file name as the argument:

     ```text
     python -c "import sys; from pathlib import Path; t = Path(sys.argv[1]).read_text(encoding='utf-8'); f = Path('docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md').open('a', encoding='utf-8', newline='\n'); f.write('\n' + t + ('' if t.endswith('\n') else '\n')); f.close()" data/fr-6b.md
     ```

   - **After 6a, never write or edit the report with a file tool.** It holds the
     verbatim run log and digest, and rewriting them by hand would change them.

   **Keep the report under 200,000 bytes.** `validate_bob_artifact.py` refuses a larger
   report, and then nothing is published. The run log and the digest can take up to
   190,000 of them, so the hand-written passages get about 8,000 bytes in all: about
   3,000 for 6a (its 16 `OK` lines included), 2,000 for 6b and 3,000 for 6e. Keep them
   short this way:
   - quote only the part of a log line that shows the result (self-check 1 in
     `docs/BOB_PRACTICE.md`), for example `exit 0 status valid; failures 0`, never a
     whole long line: every line is already in the run log above;
   - copy no table, list or log line a second time;
   - run `wc -c` on each passage file before you append it.

   **What is appended by command.** The run log and the digest go in byte for byte, each
   under its own heading in a `text` fence, with this command, giving the heading and the
   file as the arguments:

   ```text
   python -c "import sys; from pathlib import Path; h, t = sys.argv[1], Path(sys.argv[2]).read_text(encoding='utf-8'); f = Path('docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md').open('a', encoding='utf-8', newline='\n'); f.write('\n## ' + h + '\n\n\x60\x60\x60text\n' + t + ('' if t.endswith('\n') else '\n') + '\x60\x60\x60\n'); f.close()" "Run log" data/full-range/run.log
   ```

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
   - the commit, the Python version and `date -u` at the start;
   - a `## Steps 1 to 3` section with each command and its output: Step 1's, Step 2's 16
     `OK` lines and its `exit` line, and Step 3's `exit` line and the tests log's last
     line.

   **6b. Steps 4 and 5, by hand** (about 15 lines). Write to `data/fr-6b.md`, then append
   it with the command at the top of Step 6: a `## Steps 4 and 5` section with the Step 4
   commands, the `STARTED` line, how many waits it took, the `DONE` line, and each Step 5
   command with its full output.

   **6c. The run log, by command:** the command above, with the heading `Run log` and
   `data/full-range/run.log`. The run log holds every summary this task asks for: the
   `PLAN`, `FILTERS`, `FUNDING`, `RETRY`, `KLINES`, `MANIFEST`, `VERIFY`, `MASK`,
   `COMPARE`, `DIGEST`, `REQUESTS`, `REPORT`, `STOP`, `PROBLEM` and `RESULT` lines, the
   traceback of any check that raised, and a traceback if the run ended in one. Do not
   copy any of them again.

   **6d. The digest, by command, then its check.** Whenever the run log has a `DIGEST`
   line and a `REPORT` line whose total is at most 190,000 bytes, whatever `PROBLEM`
   lines the run printed: the digest is what rebuilds the manifests. Without a `DIGEST`
   line (a `STOP` before it, or a traceback), skip 6d. With a `REPORT` total over
   190,000, skip 6d too: 6e gives the count, and the run counts as stopped.
   1. Append it: the command above, with the heading `Digest` and
      `data/full-range/full-range-2017-2024.digest.txt`.
   2. Print the check command for it, with its line numbers filled in:

      ```text
      python -c "from pathlib import Path; L = Path('docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md').read_text(encoding='utf-8').split('\n'); F = [i for i, l in enumerate(L, 1) if l.startswith('\x60\x60\x60')]; print(f\"sed -n '{F[-2] + 1},{F[-1] - 1}p' docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md | sha256sum\")"
      ```

   3. Run the command it prints. It must print the SHA-256 of the run log's `DIGEST`
      line, which Step 5 printed for the digest file too.
   4. Write two lines to `data/fr-6d.md`, that command and its output, then append the
      file with the command at the top of Step 6.

   **6e. Results and ideas, by hand** (under about 50 lines). Write to `data/fr-6e.md`,
   then append it with the command at the top of Step 6:
   - A `## Results` section:
     - the `RESULT` line, and for each validity check below whether it holds, quoting
       the log line that shows it;
     - both `KLINES` lines, with each window's `missing` count against the 46 and 25
       expected above;
     - both `VERIFY` lines, and every excluded pair with its reason. An XRPUSDT exclusion
       under §5 rule 8 is a finding, not a stop, while the scored window keeps two
       pairs. The reported window's included pairs are a finding whatever their number:
       below two, the script logs a `VERIFY ... keeps` line and goes on (§5 rule 6);
     - the `MASK totals` line, XRPUSDT's quote-test line and the number of symbol-months
       listed;
     - the `REQUESTS` line, the `find` count from Step 5, and the `REPORT` line;
     - the SHA-256 of the digest and of both manifests, from the `DIGEST` and `MANIFEST`
       lines;
     - the plain statement that this run commits no manifest: Claude rebuilds both from
       the digest in a reviewed PR.
   - A `## Ideas and proposals` section. Check each idea against the run log first.
     Questions for Claude and Codex go here, not in the results.
   - `date -u` at the end of the run.

   **6f. The checks, by command.**
   1. Run the checker, with its output in one file:

      ```text
      ( git status --porcelain --untracked-files=all; python scripts/check_reports.py > data/fr-check-reports.log 2>&1; s=$?; grep -v '^check_reports: UNVERIFIABLE ' data/fr-check-reports.log; echo "exit $s"; date -u ) > data/fr-checks.log 2>&1
      ```

      The `UNVERIFIABLE` lines are left out on purpose. They are about other reports,
      and they name other scripts in backticks next to hashes. Copied into this report,
      they would read as pins and fail the checker.
   2. Append a final `## Checks` section with that file, byte for byte: the command above
      with the heading `Checks` and `data/fr-checks.log`.
   3. Run `python scripts/check_reports.py; echo "exit $?"` and then
      `wc -c docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md`. The report is
      complete when the first ends with the two lines `check_reports: 0 problem(s)` and
      `exit 0`, and the count is below 200,000 (`validate_bob_artifact.py` rejects a
      larger report). Quote those lines in your final message.
   4. **If the count is 200,000 or more,** the report would be refused. Write it again
      without the digest; do not cut or edit it by hand (self-check 10: the report is
      final text):
      - move it aside: `mv docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md data/fr-oversize.md`;
      - redo 6a to 6f in order, from the same files, but skip 6d;
      - in 6e, give the oversize count (`wc -c data/fr-oversize.md`), the SHA-256 of the
        run log and of the digest (Step 5 and the `DIGEST` line), the counts from the
        `KLINES` and `MANIFEST` lines, the stop reason ("the report with the digest held
        N bytes, over 200,000"), and that a second run is needed to deliver the digest;
      - run 3 again; the new count must be below 200,000.

   `data/fr-checks.log` must contain these lines, in any order the checker chooses, plus
   one `date -u` line:
   - `?? docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md` (git status, nothing
     else);
   - `check_reports: 0 problem(s)`;
   - `exit 0`.

   Other `check_reports:` lines about other reports are expected: their `verified` and
   `corrected` lines, and the counts of stated hashes and script mentions. A line of this
   list that is missing, or any line that names a problem with this report, is a real
   problem: stop and report.

## Validity checks (all must hold for a valid run)

1. Step 2: 16 `OK` lines and `exit 0`.
2. Step 3: `exit 0` and `18 passed`.
3. Step 4: `wait` prints `DONE exit=0`, and the run log's last line is
   `RESULT 0 problem(s)`, which the script prints only when all of these hold:
   - `FUNDING 60 of 60 months ok`;
   - both `VERIFY` lines say `exit 0 status valid`, and the scored window's keeps at
     least 2 of the 3 pairs. The reported window's count is reported only: below 2, it
     decides nothing (§5 rule 6), so it is no problem;
   - `MASK symbol-months` lists no month with `excluded True`;
   - `COMPARE full-range-2019-2024: ... every entry equals full-range-2017-2024's: True`;
   - `DIGEST ... rebuilds both manifests byte for byte: True`;
   - no check raised;
   - `REPORT ... ` at most 190,000 bytes.
4. Step 4: the `REQUESTS` line says `latest month 2024-12; after 2024-12: 0`, and there
   is no `OutOfScope` and no traceback.
5. Step 5: the `find | grep -c` count is `0`.
6. Step 6: the digest check in 6d prints the `DIGEST` line's SHA-256, and
   `data/fr-checks.log` holds the lines listed at the end of Step 6.

## What to report

`docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md`, written in steps 6a to 6f
as above:
- the commit, the Python version, and `date -u` at the start and the end;
- every command with its output, the long ones appended verbatim;
- the run log (6c) and the digest (6d), verbatim, each once;
- the results (6e): the `RESULT` line and each validity check; the `KLINES`, `VERIFY`,
  `MASK`, `REQUESTS` and `REPORT` lines; the digest's and both manifests' SHA-256; and
  the statement that this run commits no manifest;
- the checks (6f);
- **Ideas and proposals** (6e, separate from the results), each checked against the run
  log first.

## Stop conditions

There are two kinds of stop:
- **The run ended with a `RESULT` line** (`wait` printed `DONE exit=0` or `DONE exit=1`,
  and the log's last line is `RESULT`). Complete Steps 5 and 6 in full, the digest included (6d) whenever the log
  has a `DIGEST` line, whatever the `PROBLEM` lines say: a 17% exclusion, a
  scored-window pair shortfall, `verify` not valid, or a check that raised. (A `STOP`
  comes before the digest, so there is none to append.) The script writes the digest as
  soon as both manifests exist, before any check runs, and the digest is what rebuilds
  the manifests, so it must reach the report. Only the size limits (6d and 6f.4) keep it
  out. "Stop" then means: no rerun, no change and no workaround.
- **Anything else** (a pin, the tests, a traceback with no `RESULT` line): stop where
  you are. Keep everything, and write the report with what you have, by the same steps:
  6a, 6b, 6c if a run log exists, 6e and 6f, with the full error.

Report each of these:
- any pin in Step 2 says `FAILED`, or the tests in Step 3 fail;
- a checksum mismatches or is missing: a traceback naming "does not match Binance's
  published SHA-256", "unexpected checksum file", "published without a checksum" or "has
  a checksum but no archive";
- any request would go to another host, any `OutOfScope` is raised, or any request, file
  or read would touch 2025-01 or later, or anything lists a directory;
- a transport error persists through 4 attempts (a traceback after
  `RETRY attempt 4 of 4`);
- a funding month is not `ok` (a `STOP` line);
- `wait` prints `GONE` after the second `start` as well;
- either `verify` is not `valid`, or the scored window, `full-range-2017-2024`, is left
  with fewer than 2 included pairs. A shortfall in the reported window,
  `full-range-2019-2024`, is not a stop: spec v1 §5 rule 6 says it decides nothing.
  Report its count in the results and go on;
- `mask-report` excludes any symbol-month under the 17% rule. The eligibility record found
  every one of its 772 measured pair-months under 17%. The one unusable month here,
  DOGEUSDT 2020-02, has no expected hours, since both specs document it as an absence.
  That record did not count incomplete hours, which this run's masks do (spec v1 §5 rule
  1, "Eligibility"), so an exclusion is new evidence against it. Report it as a signal: no
  rule is tuned to it;
- the `REPORT` line's total is over 190,000 bytes: append the run log but not the digest,
  and give the count in the results; the same if the final report reaches 200,000 bytes
  (6f.4). Either way, say that a second run is needed to deliver the digest;
- a check that raised (a `PROBLEM` line naming `verify` or `mask-report` and the
  exception; its traceback is in the run log);
- the run ends with `RESULT` other than `0 problem(s)`: report every `PROBLEM` line,
  facts only; do not rerun with changes or work around it;
- anything asks for a login or key, or anything else is unexpected.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items: apply
items 1, 2 and 4 to 11 to each hand-written passage before you append it; item 3 is
Step 6f. From 6d on, change nothing already in the report; an error found later goes in
your final message. The one exception is 6f.4: a report of 200,000 bytes or more is
written again, whole, without the digest. Every count in the report is printed by the
script or by a command you ran.
