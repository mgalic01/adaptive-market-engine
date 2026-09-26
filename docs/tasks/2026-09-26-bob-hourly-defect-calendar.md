# Task for Bob: hour-level defect calendar, 2017-08 to 2024-12

- **Written by:** Claude, 2026-09-26, from the review of your data inventory
  ([PR #49](https://github.com/mgalic01/adaptive-market-engine/pull/49)). Owner's go:
  "give bob as much grunt work as you possibly can".
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-26-bob-hourly-defect-calendar.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), including self-checks
  7 to 11 added after batch 1.

## Why

Your inventory marked whole months "not clean". One bad hour then discards 744
hours, and you noticed that the defects hit every pair in the same months. The fold
design needs the defects at **hour** resolution, grouped into **events** across pairs:
an exchange-wide outage is one event, not ten pair-months. This task builds that
calendar. It changes nothing; it measures.

## Scope

- **Pairs:** BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LTCUSDT,
  LINKUSDT, TRXUSDT.
- **Months:** 2017-08 to 2024-12 only. Never fetch or open 2025-01 or later; your
  script must refuse any month after 2024-12, as `inventory.py` did.
- **Data:** spot 1m, 1h and 1d archives, fetched and hash-checked only through
  `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"), symbol, interval, month,
  archive_get)`.
- **Out of scope:** code, spec or manifest changes; backtests; funding data.

## Step 1: collect (write `data/calendar.py`; its source goes in the report's appendix)

For each pair and month where the pair has files:
1. Fetch 1m, 1h and 1d with `fetch_file`. A month whose file raises `DataError` from
   the parser (the "not a 1m/1h boundary" months) is recorded as **unparsed**, with
   the message, and skipped for steps 2 and 3. Task
   [`2026-09-26-bob-parser-anomaly-classes.md`](2026-09-26-bob-parser-anomaly-classes.md)
   covers those months.
2. **Minute gaps:** from `read_archive(...)` on the 1m file, every run of missing
   minutes inside the pair's listed span: first missing minute (UTC), length.
3. **Hour status:** aggregate the minutes with
   `crypto_grid_bot.backtest.klines.aggregate(minutes)`, and compare each hour with
   Binance's 1h bar using `crypto_grid_bot.backtest.replay.compare_bars(ours, theirs,
   tolerance)` twice:
   - with `VOLUME_DRIFT_TOLERANCE`;
   - with `Decimal(0)`, which is strict. Do not pass `None`: that selects the
     tolerant default.

   `compare_bars` returns only `match`, `drift` or `mismatch`, and it can only be
   called for an hour that has both minutes and an official bar. Your script decides
   the other three statuses itself, **before** calling it:
   - `absent_minutes`: an official hour with no minutes;
   - `absent_hourly`: minutes but no official hour;
   - `incomplete`: fewer than 60 minutes. Record this, **and** still compare the hour
     with `compare_bars`, keeping both results.

   Also record the minute count per hour.
4. **Day status:** aggregate the official 1h bars to days with `aggregate(hours,
   86_400_000)`, and compare each with the 1d bar in the same way.

Keep the raw per-hour records in `data/calendar.jsonl`, and give its SHA-256.

## Step 2: events (write `data/events.py`; its source goes in the appendix)

- A **defect hour** is any hour whose tolerant status is not `match` or `drift`.
- Group defect hours across pairs by identical UTC hour. Merge consecutive hours into
  one **event**. For each event, record:
  - its start and end hour (UTC);
  - the number of hours;
  - the kinds involved;
  - the pairs affected, and how many of the pairs listed at that time that is.
- **Exchange-wide** means at least 80% of the listed pairs are affected; anything
  else is **pair-specific**.
- Also list every unparsed month as an event, and mark it "unparsed".

## Step 3: check against your inventory (self-verification)

Your batch-1 report (PR #49) gives per-month figures. Recompute from the calendar and
compare, as a table: pair, month, figure, batch 1, now, equal?

| Figure | Pair, month | Batch 1 |
| --- | --- | --- |
| 1m missing rows | BTCUSDT 2018-06 | 705 |
| 1m missing rows | BTCUSDT 2019-05 | 600 |
| tolerant mismatched hours | ADAUSDT 2019-12 | 66 |
| tolerant mismatched hours | ADAUSDT 2019-09 | 27 |
| tolerant mismatched hours | XRPUSDT 2019-12 | 10 |
| tolerant mismatched hours | LINKUSDT 2023-08 | 1 |
| tolerant mismatched hours | BTCUSDT 2022-04 | 2 |

Any difference must be explained before you go on. If you cannot explain one, stop
and report.

## Step 4: report

`docs/reviews/2026-09-26-bob-hourly-defect-calendar.md`:
- the commit, Python version, `date -u` at the start and end, and every command;
- the SHA-256 of each script and of `data/calendar.jsonl`, and each script's source
  in an appendix;
- **the event table**, sorted by time: start, end, hours, kind, exchange-wide or
  pair-specific, pairs. Exchange-wide events come first in a separate table;
- counts per year: exchange-wide events and hours, pair-specific events and hours,
  and unparsed months;
- **defect hours per pair and year** as a share of listed hours, so the owner can
  see how much data a month-level rule throws away compared with an hour-level rule;
- the day-level defects (1h compared with 1d), listed separately;
- the Step 3 table;
- **Ideas and proposals** (separate): for example, how folds could start and end
  around exchange-wide events, and which events look like outages (bars missing for
  every pair) rather than data errors. Each idea says why it helps and how to test it,
  and is checked against your own tables first. These are proposals for the owner and
  Codex, not decisions.

## Stop conditions

- A Python traceback, not a per-file `DataError`: stop and report it in full.
- Any file for 2025-01 or later: stop.
- A Step 3 difference you cannot explain: stop and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items.
Every count in the report is printed by a script.
