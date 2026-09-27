# Task for Bob: masked fraction of the months the repair rule rescues

- **Written by:** Claude, 2026-09-27, from the post-merge corrections to the
  [eligibility thresholds](../reviews/2026-09-27-claude-eligibility-thresholds.md).
  Owner's go for paid Bob runs, 2026-09-27: "i approve al paid bob reruns".
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-27-bob-rescued-month-masking.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md).

## Why

The proposed cap (at most 2% of a month's expected hours with a real defect) was measured
on the 674 pair-months that parse without repair. 106 pair-months fail the strict parser.
Your refined repair rule (PR #65) makes 98 of them usable, and those 98 are in no band.
A 7-month exploratory run found two of them above 2%: BTCUSDT 2017-09 at 4.31% and
ETHUSDT 2017-09 at 10.14%. So the cap stays provisional until all 98 are measured. This
task measures them. It changes nothing.

## Scope

- **Pairs and months:** the same ten pairs, 2017-08 to 2024-12 only. Call
  `crypto_grid_bot.backtest.audit.development_month(month)` on every month before use.
  Never fetch or open 2025-01 or later.
- **Data:** spot 1m and 1h archives, fetched and hash-checked only through
  `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol, interval, month,
  archive_get)`, as in PR #66.
- **Out of scope:** code, spec or manifest changes; backtests; choosing a cap.

## Step 1: the script (write `data/rescued_masking.py`)

Start from `data/masked_fraction.py` in the eligibility record's appendix. Copy it
exactly and check that its SHA-256 is the one stated there before you change anything.
Then change only these four things:

1. **Repair before parsing.** For a month where `read_archive` raises `DataError`, read
   the raw rows of both files with `crypto_grid_bot.backtest.klines.read_member` and the
   `csv` module. Call `crypto_grid_bot.backtest.audit.rule_outcome(minute_rows, hour_rows,
   month, "refined")`. If it is not usable, record `{"status": "unusable", "reason": ...}`.
   If it is usable, parse the texts that
   `crypto_grid_bot.backtest.audit.fix_closes(rows, interval, "refined")` returns with
   `crypto_grid_bot.backtest.klines.parse_rows`, and measure that month exactly as an
   `ok` month, with status `repaired`.
2. **Listing hour.** Take it from the first row of the pair's earliest **present** 1m
   archive, parseable or not, as your outage task did. The eligibility script takes it
   from the earliest month that parses, which is wrong for LTCUSDT.
3. **No `ok` row without expected hours.** If a month has zero expected hours, record
   status `pre_listing` instead of `ok`.
4. **Fetch what the cache lacks.** The appendix script reads `local_path` directly and
   records `not_cached` when a file is absent, because it ran on a full cache. Your
   machine will not have one. Before reading a pair-month, call
   `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol, interval, month,
   archive_get)` for both the 1m and the 1h archive, so every file is hash-checked, and
   catch `DataError` per file exactly as in PR #66. A month Binance does not publish
   stays `not_cached`; it must not become `unusable`.

Months that parse without repair are measured exactly as before.

## Step 2: output

- One JSON line per pair-month, as before, with the new statuses.
- For `repaired` months: pair, month, expected, masked, open-only, real defects (`hard`),
  and both fractions.
- The count of `repaired` and `unusable` months, and the eight `unusable` ones with their
  reasons.
- How many `repaired` months exceed 1%, 2%, 3% and 5% on real defects, and a list of every
  one above 2%.
- The same band table as the eligibility record's second appendix script, first for the
  674 months that parse without repair and then for all 772 (674 + 98), so the two can be
  compared.

## Step 3: check against known values (self-verification)

| Figure | Claude |
| --- | --- |
| pair-months that parse without repair | 674 |
| pair-months with no archive upstream (pre-listing) | 110 |
| `repaired` months | 98 |
| `unusable` months | 8: BTC, ETH, BNB 2017-12; BTC, ETH, BNB, LTC 2018-02; DOGE 2020-02 |
| BTCUSDT 2017-09, real defects | 4.31% |
| ETHUSDT 2017-09, real defects | 10.14% |
| LTCUSDT listing hour | 2017-12-13 03:00 UTC |

Recompute each one and compare, as a table: figure, Claude, you, equal? Any difference
must be explained before you go on. If you cannot explain one, stop and report.

## Step 4: report

`docs/reviews/2026-09-27-bob-rescued-month-masking.md`:
- the commit, Python version, `date -u` at the start and end, and every command;
- the SHA-256 of `data/rescued_masking.py`, computed after its last edit, and its source
  in an appendix in a `text` fence (not `python`), then the check
  `sed -n '<first>,<last>p' <report> | sha256sum` showing the same hash;
- the Step 2 tables and the Step 3 table;
- **Ideas and proposals** (separate), each checked against your own tables first.

## Stop conditions

- A Python traceback, not a per-file `DataError`: stop and report it in full.
- Any file for 2025-01 or later: stop.
- A Step 3 difference you cannot explain: stop and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all items. Every
count in the report is printed by the script.
