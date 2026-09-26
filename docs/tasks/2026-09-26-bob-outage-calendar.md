# Task for Bob: outage calendar and field-level mismatches, 2017-08 to 2024-12

- **Written by:** Claude, 2026-09-26, from the review of your defect calendar
  ([PR #60](https://github.com/mgalic01/adaptive-market-engine/pull/60)). Owner's go:
  "give bob as much grunt work as you possibly can".
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-26-bob-outage-calendar.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), especially "Implement
  every definition in the task", "Enumerate what should exist, not what you found" and
  "Say which fields differ", added after your batch-2 reports.

## Why

Your calendar (PR #60) found every hour that exists in one archive but not the other.
An hour missing from **both** the 1m and the 1h archive got no status, so the real
outages, which your idea 2 named, are in no table. That gap was partly in my task
text. This task fills it, and it breaks each mismatch down by field, so a volume-only
difference (as on 2021-01-21) is no longer reported as a price difference. It changes
nothing; it measures.

## Scope

- **Pairs:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LTCUSDT,
  LINKUSDT, TRXUSDT.
- **Months:** 2017-08 to 2024-12 only. Never fetch or open 2025-01 or later; the script
  refuses any month after 2024-12.
- **Data:** spot 1m and 1h archives (and the one 1d archive in Step 4, interval
  string `"1d"`), fetched and hash-checked only through
  `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol, interval, month,
  archive_get)`, and read with `crypto_grid_bot.backtest.klines.read_archive(path,
  symbol, interval, month)`.
  The file's path on disk is `crypto_grid_bot.backtest.dataset.local_path(Path("data"),
  symbol, interval, month)`; `fetch_file` returns a record, not the path. For a month
  the strict parser rejects, `fetch_file` has already checked the hash and written the
  zip before it raises `DataError`: catch it, record the month as unparsed, and
  continue, as in PRs #59 and #60.
- **Unparsed months:** the 14 months that raise `DataError` (listed in PR #60) are
  recorded as unparsed and skipped, as before.
- **Out of scope:** code, spec or manifest changes; backtests; policy decisions.

## Step 1: expected hours (write `data/outages.py`; its source goes in the appendix)

For each pair:
1. The pair's **listed span** starts at the UTC hour containing the first row of its
   earliest 1m archive, whether or not that month parses. For an unparsed month, read
   that first row with `read_member(path, f"{symbol}-1m-{month}.csv")` and the `csv`
   module. The span ends at 2024-12-31 23:00 UTC.
2. Build the **expected** hours for every parsed month inside that span, one month at
   a time, with `range(max(first_hour_ms, month_start_ms), month_end_ms, 3_600_000)`,
   where `month_start_ms, month_end_ms = crypto_grid_bot.backtest.klines.month_bounds_ms(month)`
   (end exclusive). Do not build them
   from the bars you found.
3. Give every expected hour one status:
   - `present_both`: minutes and an official 1h bar;
   - `absent_minutes`: an official 1h bar, no minutes;
   - `absent_hourly`: minutes, no official 1h bar;
   - `absent_both`: neither. **This is the new status.**

   "Minutes" means at least one 1m bar in the hour: an hour with 3 of 60 minutes is
   `present_both` or `absent_hourly`. Record the minute count too, as in PR #60.
4. Check that the counts add up for every pair and month: the four statuses sum to the
   expected hours. Print the check.

## Step 2: outage events (same script)

- A pair is **listed at** hour h when h is one of its expected hours from Step 1: its
  span has started, and h is not in one of its unparsed months. "Pairs listed" at h is
  the count of such pairs.
- Group `absent_both` hours by identical UTC hour across pairs, and merge consecutive
  hours into one **event**. For each event: start, end, hours, pairs affected, and the
  number of pairs listed at that time.
- **All-pairs outage:** every listed pair is `absent_both`, **and** at least 5 pairs are
  listed. Mark an event where every listed pair is affected but fewer than 5 are
  listed as "all listed pairs (few)". Anything else is pair-specific.
- Print the all-pairs outages with 3 or more consecutive hours as their own table.

## Step 3: field-level mismatches (same script)

For every `present_both` hour whose `crypto_grid_bot.backtest.replay.compare_bars(ours,
theirs, VOLUME_DRIFT_TOLERANCE)`
result is `mismatch`, record which of open, high, low, close and volume differ, and by
how much (absolute and relative). Report counts per field combination (for example
"volume only", "open only", "open+close") per year.

## Step 4: check against known values (self-verification)

Claude computed these with the same library functions during the review of PR #60.
Recompute them from your data and compare, as a table: pair, month, figure, Claude,
you, equal?

| Figure | Pair, month | Claude |
| --- | --- | --- |
| `absent_both` hours | BTCUSDT 2018-06 | 11 |
| `absent_both` hours | ETHUSDT 2018-06 | 11 |
| `absent_both` hours | BNBUSDT 2018-06 | 11 |
| `absent_both` hours | LTCUSDT 2018-06 | 11 |
| `absent_both` hours | BTCUSDT 2019-05 | 10 |
| `absent_both` hours | ETHUSDT 2019-05 | 10 |
| `absent_both` hours | BNBUSDT 2019-05 | 10 |
| `absent_both` hours | LTCUSDT 2019-05 | 10 |
| first `absent_both` hour | BTCUSDT 2019-05 | 2019-05-15 03:00 |
| fields differing | BTCUSDT 1h→1d, 2021-01-21 | volume only |

The last row needs one extra step: aggregate that month's official 1h bars to days with
`crypto_grid_bot.backtest.klines.aggregate(hours, 86_400_000)` and compare with the 1d bar, fetched the same way.

Also say whether 2018-06's 11 hours are one event or more, with their times. Any
difference from Claude's figures must be explained before you go on. If you cannot
explain one, stop and report.

## Step 5: report

`docs/reviews/2026-09-26-bob-outage-calendar.md`:
- the commit, Python version, `date -u` at the start and end, and every command;
- the SHA-256 of `data/outages.py`, computed after its last edit, and its source in
  an appendix in a `text` fence (not `python`), then the check
  `sed -n '<first>,<last>p' <report> | sha256sum` showing the same hash;
- the Step 1 status counts per pair and year, and the add-up check;
- the all-pairs outage table (3 or more hours), sorted by time, then the full event
  counts per year by kind;
- the Step 3 field table;
- the Step 4 table;
- **Ideas and proposals** (separate), each checked against your own tables first: for
  example, which outages should start or end a fold, and whether any mismatch kind
  matters to a strategy that uses only prices.

## Stop conditions

- A Python traceback, not a per-file `DataError`: stop and report it in full.
- Any file for 2025-01 or later: stop.
- A Step 1 add-up check that fails, or a Step 4 difference you cannot explain: stop
  and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items.
Every count in the report is printed by the script.
