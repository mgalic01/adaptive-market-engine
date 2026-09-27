# Task for Bob: combined defect census, 2017-08 to 2024-12

- **Written by:** Claude, 2026-09-27, from the
  [defect calendar corrections](../reviews/2026-09-27-claude-defect-calendar-corrections.md).
  Owner's go for paid Bob runs, 2026-09-27: "i approve al paid bob reruns".
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-27-bob-combined-defect-census.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), especially "Implement
  every definition in the task" and "Enumerate what should exist, not what you found".

## Why

Your hour-level calendar (PR #60) had two errors, now measured by Claude:

1. An hour missing from **both** archives was in neither the numerator nor the
   denominator of the per-pair table. Your outage calendar (PR #66) counted those hours,
   but as a separate computation.
2. "Exchange-wide" was defined as "at least 80% of listed pairs at that time", but the
   script divided unions over the whole event. Hour by hour, 27 of the 78 events meet
   the definition.

Claude could correct each one separately. Fixing both together changes which hours merge
into one event, and that needs the full census, which only you can run. This task
computes it once, with one script and one set of hour statuses. It changes nothing; it
measures.

## Scope

- **Pairs:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LTCUSDT,
  LINKUSDT, TRXUSDT.
- **Months:** 2017-08 to 2024-12 only. Never fetch or open 2025-01 or later. Call
  `crypto_grid_bot.backtest.audit.development_month(month)` on every month before you
  use it.
- **Data:** spot 1m and 1h archives, fetched and hash-checked only through
  `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol, interval, month,
  archive_get)`, and read with `crypto_grid_bot.backtest.klines.read_archive(path,
  symbol, interval, month)`, as in PR #66. The path is
  `crypto_grid_bot.backtest.dataset.local_path(Path("data"), symbol, interval, month)`.
- **Unparsed months:** the 14 months that raise `DataError` are recorded as unparsed and
  skipped, as in PRs #60 and #66.
- **Out of scope:** code, spec or manifest changes; backtests; policy decisions.

## Step 1: one status per expected hour (write `data/defect_census.py`)

For each pair, exactly as in your outage task:
1. The **listing hour** is the UTC hour containing the first row of the pair's earliest
   1m archive, whether or not that month parses.
2. For every parsed month, the expected hours are
   `crypto_grid_bot.backtest.audit.expected_hours(listing_hour_ms, month)`. Do not build
   them from the bars you found.
3. Statuses come from `crypto_grid_bot.backtest.audit.hour_statuses(minute_open_ms,
   official_open_ms, expected)`. For each `present_both` hour, also compare with
   `crypto_grid_bot.backtest.replay.compare_bars(ours, theirs, VOLUME_DRIFT_TOLERANCE)`,
   where `ours` comes from `crypto_grid_bot.backtest.klines.aggregate(minutes, 3_600_000)`.
4. A **defect hour** is any expected hour that is `absent_minutes`, `absent_hourly` or
   `absent_both`, or `present_both` with a `compare_bars` result other than `match` or
   `drift`.

## Step 2: the per-pair table, on expected hours

For every pair and year: defect hours / expected hours, and the rate. Then the totals per
pair and for all ten. Also print, per pair and year, how many defect hours are
`absent_both`.

## Step 3: events, with the rule applied hour by hour

- A pair is **listed at** hour h when h is one of its expected hours from Step 1.
- Merge consecutive UTC hours in which **at least one** listed pair has a defect hour into
  one **event**, as your events script did, now including `absent_both` hours.
- For every hour of every event, record `affected at h / listed at h`, where "affected"
  counts only pairs listed at h.
- Classify each event under three rules and print all three:
  - `breadth-per-hour-v1`: the ratio is at least 0.8 **in every hour** of the event;
  - the same, and additionally at least 5 pairs listed in every hour;
  - `union-v0`, your PR #60 rule (union of affected / union of listed over the event, at
    least 0.8), for comparison only.
- Print, per year: events and hours meeting each rule, and all other events and hours.
- Print every event meeting `breadth-per-hour-v1` with its per-hour ratios.
- For each of the 14 outages in your PR #66 report, say which Step 3 event now contains
  it, that event's start, end and per-hour ratios, and whether it still meets
  `breadth-per-hour-v1`.

## Step 4: check against known values (self-verification)

Claude computed these with the same library functions. Recompute them and compare, as a
table: figure, Claude, you, equal?

| Figure | Claude |
| --- | --- |
| all ten pairs, defect hours / expected hours | 7,114 / 490,786 |
| BTCUSDT 2019 | 28 / 8,040 |
| XRPUSDT 2020 | 6 / 6,600 |
| TRXUSDT 2018 | 22 / 4,141 |
| DOGEUSDT 2019 | 2,287 / 4,308 |
| `absent_both` pair-hours, all pairs and years | 468 |
| 2019-11-13 02:00 to 05:00 per-hour ratios | 9/9, 9/9, 8/9, 1/9 |

Any difference must be explained before you go on. If you cannot explain one, stop and
report. A disagreement is a finding, not something to adjust away.

## Step 5: report

`docs/reviews/2026-09-27-bob-combined-defect-census.md`:
- the commit, Python version, `date -u` at the start and end, and every command;
- the SHA-256 of `data/defect_census.py`, computed after its last edit, and its source in
  an appendix in a `text` fence (not `python`), then the check
  `sed -n '<first>,<last>p' <report> | sha256sum` showing the same hash;
- the Step 2 table, the Step 3 per-year tables and event lists, and the Step 4 table;
- every count named with its rule: `breadth-per-hour-v1`, with or without the 5-pair
  floor, or `union-v0`. Do not write "exchange-wide" without one of those names next to
  it;
- **Ideas and proposals** (separate), each checked against your own tables first.

## Stop conditions

- A Python traceback, not a per-file `DataError`: stop and report it in full.
- Any file for 2025-01 or later: stop.
- A Step 4 difference you cannot explain: stop and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all items. Every
count in the report is printed by the script.
