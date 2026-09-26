# Task for Bob: classify the rows the strict parser rejects

- **Written by:** Claude, 2026-09-26, from the review of your data inventory
  ([PR #49](https://github.com/mgalic01/adaptive-market-engine/pull/49)). Owner's go:
  "give bob as much grunt work as you possibly can".
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-26-bob-parser-anomaly-classes.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), including self-checks
  7 to 11.

## Why

Your inventory found 14 months in which the strict parser rejects the 1m and 1h files
of most pairs, because one row's close time is not on the candle boundary. You
proposed relaxing the check. That proposal only works if we know what those rows are,
and your own two examples differ:
- 2017-09: close = open + 60 000 ms, one millisecond **past** the boundary;
- 2023-03: close = open + 41 646 ms, **truncated** mid-candle.

The parser stops at the first bad row, so nobody knows whether a month has one such
row or many. This task finds every one and measures what a narrow rule would give.
It changes no code.

## Scope

- **Months (from your inventory, PR #49):** 2017-09, 2017-12, 2018-01, 2018-02,
  2018-07, 2019-06, 2020-02, 2020-03, 2020-12, 2021-02, 2021-04, 2021-08, 2021-12 and
  2023-03. Hard-code this list and refuse any other month; never fetch or open 2025-01
  or later.
- **Pairs:** all ten basket pairs (BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT,
  ADAUSDT, DOGEUSDT, LTCUSDT, LINKUSDT, TRXUSDT). Fetch each listed month for each
  pair that has files. Classify every file, including files that parse cleanly: those
  should show zero anomalies, and that zero is a check on the script.
- **Data:** fetch with `crypto_grid_bot.backtest.dataset.fetch_file(Path("data"),
  symbol, interval, month, archive_get)`. It checks Binance's SHA-256 and writes the
  zip before parsing, so the verified zip is on disk even when parsing fails. Read the
  CSV with `crypto_grid_bot.backtest.klines.read_member(path,
  f"{symbol}-{interval}-{month}.csv")`.
- **Out of scope:** code changes; deciding a policy. You measure, and the owner and
  Codex decide.

## Step 1: find and classify every anomalous row (write `data/anomalies.py`; its source goes in the appendix)

For each file, walk **every** row with the `csv` module. Do not stop at the first bad
row. With `step` = 60 000 (1m) or 3 600 000 (1h), classify each row whose close is not
`open + step - 1`:
- `past_boundary`: close ≥ open + step. Record by how much, in ms.
- `truncated`: open ≤ close < open + step - 1. Record the fraction of the candle
  covered.
- `other`: anything else, for example close < open or an open not on a boundary.

For each anomalous row, also record:
- its UTC open time and line number;
- whether it is the **last row before a gap** (the next row's open is later than
  open + step) and how long the gap is;
- whether it is the last row of the file;
- for 1m rows, the UTC hour it falls in.

## Step 2: what a narrow rule would give (same script)

Measure one candidate rule, as a measurement only:

> A row whose close is off the boundary is accepted only if it is the last row before
> a gap or the last row of the file; its close is set to `open + step - 1`.

For each file:
1. Apply the rule in memory. Leave any row the rule does not cover as it is.
2. Run `crypto_grid_bot.backtest.klines.parse_rows(text, interval, month)` on the
   result.
3. Record either the `FileStats` (rows, missing rows, gaps) or the new `DataError`
   message.

Then, for every month the rule makes parseable in both 1m and 1h, compare the
affected hours with `crypto_grid_bot.backtest.replay.compare_bars`: your aggregated
minutes against Binance's 1h bar, at both `VOLUME_DRIFT_TOLERANCE` and `Decimal(0)`.
Report whether the hour containing each accepted row matches.

## Step 3: report

`docs/reviews/2026-09-26-bob-parser-anomaly-classes.md`:
- the commit, Python version, `date -u` at the start and end, and every command;
- the script's SHA-256 and its source in an appendix;
- a table per month: pair, interval, anomalous rows by class, and how many are last
  before a gap;
- totals by class, printed by the script;
- the Step 2 result per file: parseable or not (with the new error), missing rows,
  gaps, and the hour comparison for the accepted rows;
- a one-line answer: **how many of the 14 months become usable under the narrow rule,
  for how many pairs**;
- **Ideas and proposals** (separate). Test each idea against these tables before you
  write it. For example: does any anomaly fall *inside* trading rather than at an
  outage edge? Would the rule accept anything it should not?

## Stop conditions

- A Python traceback: stop and report it in full.
- A month outside the 14 listed above, or any file for 2025-01 or later: stop.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items.
