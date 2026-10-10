# Task for Bob: fetch full-range-2017-2024 and full-range-2019-2024, stage 2's long windows

- **Status: to be run again with the owner's `/bob-run`.** The owner gave the go on
  2026-10-07, and the file merged in #193. Its first run (37591538301) passed the pins and
  the tests and started the fetch, then ended Bob's session after a `wait`, with no report
  (issue #195), so nothing was published. Step 4 now says that DONE is never the end of the
  task. Editing this file does not start a run: the owner comments
  `/bob-run docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md`. Before that, the pins
  must still hold: any change under `src` on `main` means updating them first (see
  "Pinned inputs").
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
lasts more than about 9 minutes and none needs more than `python`. From Step 3 on, the
script also does for the report what shell utilities would: the clock, a file's last
lines, sizes, the reserved-window check, appending to the report and moving it. Its
docstring lists these report tools.

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

The runner checks out whatever `main` is when the job starts. So Step 2 checks, before any
request, that the code and inputs are the ones reviewed here:
- **The whole package, by its git tree.** `git rev-parse HEAD:src` must print exactly
  `96de9766551d478883f3451bcaae261f165fd3d4`, the tree of `src` at `370229d`. That covers
  every module the run can import, not only the data path: `dataset`, `jobs`, `replay`,
  `masking`, `klines`, `funding`, `config`, `features`, `simulation/runner` and the rest.
  `git status` must also show no local change under `src`.
- **Six files by SHA-256:** the script and its test as this task's PR adds them, the two
  dataset specs, the committed filters, and `config/default.toml`, whose spread limit
  verify and mask-report read. Step 2 copies the block below out of this file:

```text
c41005ef04d10efdc72bb03033947e65e54116d18318973b41171b77fcc81dbd  scripts/fetch_full_range.py
e44a5cc4f9394f079ca69c619af15ac985d2823255a87614e4ed05c5e3b43dc5  tests/test_fetch_full_range.py
f4216524de089988a15fbddd72a9625a737f41be5a8dcb4bed6a36ccf8e0addb  config/datasets/full-range-2017-2024.toml
8dad70041f4423706b0eeba272595fb24af74cb83713b6316abb68e5a40dafcb  config/datasets/full-range-2019-2024.toml
349ce104be44d28d918b22dc99dd611f56d174011b50cb144393a97940c72374  config/datasets/long-bull-bear-2022.manifest.json
17e7cfc750a31c0f53b0c4be5b8aae8dc99c355bbf49de27c9c6fed53003344f  config/default.toml
```

If the tree hash differs, `git status` lists a change under `src`, or any `sha256sum` line
says `FAILED`, stop before Step 3 and report by the pin-failure path in "Stop conditions",
which runs no script.

This file cannot pin itself, and the runner reads it as `main` has it when the job starts.
So the pinned script checks it: Step 4's `start` reads this file's text, all of it but the
pin block above, and starts nothing unless its SHA-256 is the one the reviewed script
holds. It then prints `NOT STARTED: the task file ... is not the reviewed text`, a stop. **Any change under `src` on `main` before
this file merges changes the tree hash, so the pins must be updated in its PR before the
owner's go.**

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
   - `6 pins`;
   - six lines that each end in `OK`.

   ```text
   git rev-parse HEAD:src
   git status --porcelain --untracked-files=no -- src
   python -c "from pathlib import Path; t = Path('docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md').read_text(encoding='utf-8'); b = t.split('## Pinned inputs', 1)[1].split('\x60\x60\x60text\n', 1)[1].split('\x60\x60\x60', 1)[0]; Path('data/full-range-pins.txt').write_text(b, encoding='utf-8', newline='\n'); print(len(b.splitlines()), 'pins')"
   sha256sum -c data/full-range-pins.txt
   ```

3. The script's tests, offline (a fake host; about a minute):

   ```text
   python -m pytest -p no:cacheprovider tests/test_fetch_full_range.py > data/full-range-tests.log 2>&1
   python scripts/fetch_full_range.py tail data/full-range-tests.log
   ```

   The last line must report `27 passed`. Add no `-q`: `pyproject.toml` already passes
   one, and a second one hides that line.
4. The run: about 3,600 requests to data.binance.vision, `verify` on both windows and
   `mask-report` on the scored one. Expect about an hour; the job allows 240 minutes.
   That is longer than any single command on record here (about 19 minutes), so the
   script runs itself in the background, and you wait for it in steps of under 10
   minutes. Start it once:

   ```text
   python scripts/fetch_full_range.py start data/full-range
   ```

   It prints `STARTED pid <n>; log data/full-range/run.log; exit file
   data/full-range/run.exit` and returns at once. Then wait:

   ```text
   python scripts/fetch_full_range.py wait data/full-range
   ```

   It returns within about 9 minutes. Every outcome, these three and any error, ends with a
   line starting `NEXT:` that names the next step: follow it, whatever the exit status.
   The three run states exit 0, and it prints one of:
   - `RUNNING pid <n>; latest: <the log's last line>`: run the same `wait` again. The log
     stays quiet for long stretches: after `FUNDING`, nothing comes until the whole scored
     fetch is done.
   - `DONE exit=<status>`, then the log's last lines: the run has ended, and **the report
     is not written yet. DONE is never the end of the task:** go straight on to Step 5 in
     this session, then Step 6, and end with your signed final message. Do not read
     `data/full-range/run.log` whole (it is long): Steps 5 and 6 take what they need from
     it through the script.
   - `GONE pid <n>: no process and no exit file; ...`: the run was lost without ending
     (the script writes the exit file even after a traceback). Run the same `start` once
     more, unchanged: stored archives are reused while their checksum matches, so only
     `.CHECKSUM` requests repeat, and the first attempt's log is kept as
     `data/full-range/run-1.log`. Then `wait` again. That is the only restart: if it is lost
     a second time, `wait`'s `NEXT:` line says so, `start` refuses a third attempt, and you
     write the report with what exists (Steps 5 and 6).

   **Never end your session before Step 6 has written the report and you have given your
   signed final message,** whatever a command prints. The first run of this task (run
   37591538301, issue #195) ended right after a `wait`, with no report, and its work was
   lost.

   `start` refuses while a run is alive, and after one has ended, so it cannot start a
   second run by mistake. Say in 6b how many waits it took, and whether `start` ran twice.

5. The hashes of everything the run wrote, every log included, then the sizes and the
   reserved-window file check:

   ```text
   sha256sum data/full-range-tests.log data/full-range/run*.log data/full-range/run.exit data/full-range/*.toml data/full-range/*.json data/full-range/*.txt
   python scripts/fetch_full_range.py measure data/full-range data
   ```

   The second command prints the bytes of every run log and of the digest. The run logs
   are `run.log`, and one `run-<n>.log` for each lost attempt. Then it prints
   `RESERVED-WINDOW FILES 0`; any other count is a stop.
6. Write the report `docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md` in **five
   steps, 6a to 6e, in this order**. Complete each step before starting the next.

   **What you write by hand.** Only three short passages: 6a, 6b and 6d.
   - Create the report in 6a with your file-writing tool: the file is new and short.
   - For 6b and 6d, write the passage to its own new file (`data/fr-6b.md`,
     `data/fr-6d.md`), then append it with this command, giving the passage's file:

     ```text
     python scripts/fetch_full_range.py append docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md data/fr-6b.md
     ```

   - **After 6a, never write or edit the report with a file tool.** It holds the
     verbatim run logs and digest, and rewriting them by hand would change them.

   **Keep the report under 200,000 bytes.** `validate_bob_artifact.py` refuses a larger
   report, and then nothing is published.
   - **The run logs and the digest** take at most 190,000 bytes: 6c compresses them when
     they would take more.
   - **The hand-written passages** get about 8,000 bytes in all: about 3,000 for 6a (its
     six `OK` lines included), 2,000 for 6b and 3,000 for 6d.

   Keep the passages short this way:
   - quote only the part of a log line that shows the result (self-check 1 in
     `docs/BOB_PRACTICE.md`), for example `exit 0 status valid; failures 0`, never a
     whole long line: every line is already in the run log;
   - copy no table, list or log line a second time;
   - check each passage file's bytes before you append it, for example with
     `python scripts/fetch_full_range.py size data/fr-6b.md`.

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
     tree hash, empty status, `6 pins` and six `OK` lines, and the last line of Step 3.

   **6b. Steps 4 and 5, by hand** (about 15 lines). Write to `data/fr-6b.md`, then append
   it with the command above. It is a `## Steps 4 and 5` section with:
   - the Step 4 commands, the `STARTED` line, how many waits it took, and the `DONE` line;
   - each Step 5 command with its full output.

   **6c. The run logs and the digest, by command:**

   ```text
   python scripts/fetch_full_range.py append-results docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md data/full-range
   ```

   It appends every run log, then the digest, each under its own heading in a `text`
   fence: a lost attempt's log first (`Run log, attempt 1 (lost)`), then `Run log`, then
   `Digest`.
   - **Compression.** If together they would pass 190,000 bytes, it compresses the digest
     (zlib, then base64), and the logs too if that is still not enough. Each compressed
     block comes with its file's SHA-256 and the exact command that decodes it.
   - **Checks.** It then reads every block back from the report. It prints one `APPENDED
     ...; reads back: True` line for each block, then the total. Any `False`, or a
     `NOT APPENDED` line, is a stop.
   - **The digest always goes in,** whatever the `PROBLEM` lines say (see "Stop
     conditions"). Only a run with no digest file has none: one that ended with a `STOP`
     before the digest, or with a traceback.
   - Do not copy any appended line again.

   **6d. Results and ideas, by hand** (under about 50 lines). Write to `data/fr-6d.md`,
   then append it with the command above:
   - A `## Results` section:
     - the `RESULT` line, and for each validity check below whether it holds, quoting the
       part of the log line that shows it;
     - both `KLINES` lines, with each window's `missing` count against the 46 and 25
       expected above;
     - both `VERIFY` lines, and every excluded pair with its reason. An XRPUSDT exclusion
       under §5 rule 8 is a finding, not a stop, while the scored window keeps two
       pairs. The reported window's included pairs are a finding whatever their number:
       below two, the script logs a `VERIFY ... keeps` line and goes on (§5 rule 6);
     - the `MASK totals` line, XRPUSDT's quote-test line and the number of symbol-months
       listed;
     - the `REQUESTS` line, Step 5's `RESERVED-WINDOW FILES` count, and the `REPORT`
       line;
     - for each block 6c appended, whether it went in as text or compressed, and that it
       reads back;
     - the SHA-256 of the digest and of both manifests, from the `DIGEST` and `MANIFEST`
       lines;
     - the plain statement that this run commits no manifest: Claude rebuilds both from
       the digest in a reviewed PR.
   - A `## Ideas and proposals` section. Check each idea against the run log first.
     Questions for Claude and Codex go here, not in the results.
   - The clock at the end of the run, from `python scripts/fetch_full_range.py now`.

   **6e. The checks, by command.**
   1. Gather the checks into one file, then append it as the final section:

      ```text
      git status --porcelain --untracked-files=all > data/fr-git-status.txt
      python scripts/check_reports.py > data/fr-check-reports.log 2>&1
      python scripts/fetch_full_range.py check-log data/fr-git-status.txt data/fr-check-reports.log data/fr-checks.log
      python scripts/fetch_full_range.py append docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md data/fr-checks.log --heading Checks
      ```

      `check-log` leaves out the checker's `UNVERIFIABLE` lines on purpose. They are about
      other reports, and they name other scripts in backticks next to hashes. Copied into
      this report, they would read as pins and fail the checker.
   2. Then:

      ```text
      python scripts/check_reports.py
      python scripts/fetch_full_range.py size docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md
      ```

      The report is complete when the first ends with `check_reports: 0 problem(s)` and
      the second says `under the 200000-byte limit`. Quote both lines in your final
      message.
   3. **If the second says `AT OR OVER`,** the report would be refused. Write it again
      with the logs and digest compressed; do not cut or edit it by hand (self-check 10:
      the report is final text):

      ```text
      python scripts/fetch_full_range.py set-aside docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md data/fr-oversize.md
      ```

      - Redo 6a to 6e in order, from the same files, but add `--compressed` to the 6c
        command.
      - In 6d, give the oversize count from the `SET ASIDE` line, and say that the logs
        and the digest are compressed in this report.
      - Then run 2 again. The digest, in its compressed form, is still in the report.

   `data/fr-checks.log` must contain these lines, in any order the checker chooses, and a
   clock line at the end:
   - `?? docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md` (git status, nothing
     else);
   - `check_reports: 0 problem(s)`.

   Other `check_reports:` lines about other reports are expected: their `verified` and
   `corrected` lines, and the counts of stated hashes and script mentions. A line of this
   list that is missing, or any line that names a problem with this report, is a real
   problem: stop and report.

## Validity checks (all must hold for a valid run)

1. Step 2: the pinned tree hash, an empty `git status`, `6 pins` and six `OK` lines.
2. Step 3: `27 passed`.
3. Step 4: `wait` prints `DONE exit=0`, and the run log's last line is
   `RESULT 0 problem(s)`, which the script prints only when all of these hold:
   - `FUNDING 60 of 60 months ok`;
   - both `VERIFY` lines say `exit 0 status valid`, and the scored window's keeps at
     least 2 of the 3 pairs. The reported window's count is reported only: below 2, it
     decides nothing (§5 rule 6), so it is no problem;
   - `MASK symbol-months` lists no month with `excluded True`;
   - `COMPARE full-range-2019-2024: ... every entry equals full-range-2017-2024's: True`;
   - `DIGEST ... rebuilds both manifests byte for byte: True`;
   - no check raised.
4. Step 4: the `REQUESTS` line says `latest month 2024-12; after 2024-12: 0`, and there
   is no `OutOfScope` and no traceback.
5. Step 5: `RESERVED-WINDOW FILES 0`.
6. Step 6: every `APPENDED` line of 6c ends `reads back: True`, and `data/fr-checks.log`
   holds the lines listed at the end of Step 6.

## What to report

`docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md`, written in steps 6a to 6e
as above:
- the commit, the Python version, and the clock at the start and the end;
- every command with its output, the long ones appended by command;
- every run log and the digest (6c), each once, as text or compressed;
- the results (6d): the `RESULT` line and each validity check; the `KLINES`, `VERIFY`,
  `MASK`, `REQUESTS` and `REPORT` lines; how each block went in; the digest's and both
  manifests' SHA-256; and the statement that this run commits no manifest;
- the checks (6e);
- **Ideas and proposals** (6d, separate from the results), each checked against the run
  log first.

## Stop conditions

There are two kinds of stop:
- **The run ended with a `RESULT` line.** `wait` printed `DONE exit=0` or
  `DONE exit=1`, and the log's last line is `RESULT`.
  - Complete Steps 5 and 6 in full, 6c included, whatever the `PROBLEM` lines say: a 17%
    exclusion, a scored-window pair shortfall, `verify` not valid, or a check that raised.
  - The script writes the digest as soon as both manifests exist, before any check runs.
    The digest is what rebuilds the manifests, so it always reaches the report, compressed
    when it must be. (A `STOP` comes before the digest, so then there is none.)
  - "Stop" then means: no rerun, no change and no workaround.
- **Step 1 or Step 2 failed** (the clock, the commit, or any pin): the script and its
  tests are not the reviewed ones, so **run nothing else: not `scripts/fetch_full_range.py`
  in any form, not its report subcommands, and not `python -m pytest`.** An unreviewed
  script can read an argument it does not know as a data directory and start a fetch.
  Write the report file directly with your edit tool instead, as one new file
  `docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md`:
  - first line `# Bob: full-range-2017-2024 fetch stopped at the pins`;
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
- a funding month is not `ok` (a `STOP` line);
- `wait` prints `GONE` after the second `start` as well;
- either `verify` is not `valid`, or the scored window, `full-range-2017-2024`, is left
  with fewer than 2 included pairs. A shortfall in the reported window,
  `full-range-2019-2024`, is not a stop: spec v1 §5 rule 6 says it decides nothing.
  Report its count in the results and go on;
- `mask-report` excludes any symbol-month under the 17% rule.
  - The eligibility record found every one of its 772 measured pair-months under 17%.
  - The one unusable month here, DOGEUSDT 2020-02, has no expected hours, since both
    specs document it as an absence.
  - That record did not count incomplete hours, which this run's masks do (spec v1 §5
    rule 1, "Eligibility"). So an exclusion is new evidence against the record. Report
    it as a signal: no rule is tuned to it;
- a check that raised (a `PROBLEM` line naming `verify` or `mask-report` and the
  exception; its traceback is in the run log);
- 6c prints `NOT APPENDED`, or a block that does not read back;
- the run ends with `RESULT` other than `0 problem(s)`: report every `PROBLEM` line,
  facts only; do not rerun with changes or work around it;
- anything asks for a login or key, or anything else is unexpected.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items:
- apply items 1, 2 and 4 to 11 to each hand-written passage before you append it;
- item 3 is Step 6e.

Where that file names a shell command, use the script instead:
- for the clock (item 8), `python scripts/fetch_full_range.py now`;
- for a path check (item 2), `python scripts/fetch_full_range.py exists PATH ...`.

After a pin failure (Step 1 or Step 2), run neither: take the clock from Step 1's output,
and check paths by reading the files with your read tool.

From 6c on, change nothing already in the report; an error found later goes in your final
message. The one exception is 6e.3: a report of 200,000 bytes or more is written again,
whole, with the logs and digest compressed. Every count in the report is printed by the
script or by a command you ran.
