# Task for Bob: measure the refined parser rule on the 14 unparsed months

- **Written by:** Claude, 2026-09-26, from the review of your parser anomaly report
  ([PR #59](https://github.com/mgalic01/adaptive-market-engine/pull/59)). Owner's go:
  "give bob as much grunt work as you possibly can".
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-26-bob-refined-parser-rule.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), especially "Implement
  every definition in the task" and "Test an idea against your own evidence".

## Why

In PR #59 you proposed also accepting an off-boundary close when the next row opens
exactly one step later. Claude tested it on four hours and found them matching the
official 1h bars. This task measures it on every file, with the condition Claude added,
so the owner and Codex can decide with complete numbers. It changes no code.

## Scope

- **Months:** 2017-09, 2017-12, 2018-01, 2018-02, 2018-07, 2019-06, 2020-02, 2020-03,
  2020-12, 2021-02, 2021-04, 2021-08, 2021-12 and 2023-03. Hard-code this list and
  refuse any other month; never fetch or open 2025-01 or later.
- **Pairs and intervals:** the ten basket pairs, 1m and 1h, every file that exists.
- **Data:** `fetch_file(Path("data"), symbol, interval, month, archive_get)` and
  `read_member(path, f"{symbol}-{interval}-{month}.csv")`, as in PR #59.
  The file's path on disk is `crypto_grid_bot.backtest.dataset.local_path(Path("data"),
  symbol, interval, month)`; `fetch_file` returns a record, not the path. For a month
  the strict parser rejects, `fetch_file` has already checked the hash and written the
  zip before it raises `DataError`: catch it, record the month as unparsed, and
  continue, as in PRs #59 and #60.
- **Out of scope:** code changes; deciding a policy.

## Step 1: classify (write `data/refined_rule.py`; its source goes in the appendix)

Walk every row with the `csv` module. For each row whose close is not
`open + step - 1`, record three conditions:
- **(a) aligned open:** `open % step == 0`;
- **(b) continuity:** the row is the last of the file, or the next row opens at
  `open + step` or later;
- **(c) strict hour check:** after the fix below, the 1h hour containing the row
  compares `match` with `crypto_grid_bot.backtest.replay.compare_bars(ours, theirs,
  Decimal(0))`, where ours is the
  aggregated fixed minutes (`crypto_grid_bot.backtest.klines.aggregate`) and theirs is
  the official 1h bar. For a 1h row, compare
  it with the aggregated fixed 1m minutes of the same hour. If the other file does
  not parse, condition (c) is "not testable".

**The fix:** a row that meets (a) and (b) gets close `open + step - 1`, in memory only.
The **fixed text** of a file is its CSV text with the close column of every such row
rewritten that way and every other row unchanged, written back with `csv.writer`, as
your PR #59 script did for the narrow rule.

Also count the rows with an unaligned open (not (a)) per file. PR #59 missed them:
Claude counted 61,203 in 2017-12 1m, 4,804 in 2018-02 1m and 172 in 2018-02 1h.
Reproduce these three numbers first, as the check that your (a) is implemented.

## Step 2: what the rule gives

For each file, run `crypto_grid_bot.backtest.klines.parse_rows(fixed_text, interval,
month)` on the **fixed text** (never the original archive text, which the strict parser
always rejects) and record the `FileStats` or the new `DataError`.

A pair-month is **usable** when both its 1m and 1h files parse after the fix **and**
every fixed row passes (c). A fixed row whose (c) is "not testable" counts as failing,
so its pair-month is not usable. Report, per month: usable pairs out of the pairs with
files, and for each unusable pair which condition failed first.

Compare with the **narrow rule** of PR #59, exactly as it was defined there and not
corrected since: a row whose close is off the boundary is accepted only if it is the
last row before a gap or the last row of the file, and its close is set to
`open + step - 1`. There is no alignment check and no hour check. Build its own fixed
text the same way, and a pair-month counts as usable under it when both its 1m and 1h
fixed texts parse. That gave **82** usable
pair-months. Claude confirmed that figure. Recompute it with
your script and show both numbers side by side.

## Step 3: report

`docs/reviews/2026-09-26-bob-refined-parser-rule.md`:
- the commit, Python version, `date -u` at the start and end, and every command;
- the SHA-256 of `data/refined_rule.py`, computed after its last edit, and its source
  in an appendix in a `text` fence (not `python`), then the check
  `sed -n '<first>,<last>p' <report> | sha256sum` showing the same hash;
- the unaligned-open counts, with the three reproduced figures;
- per month and pair: anomalous rows, how many meet (a), (a)+(b), and (a)+(b)+(c);
- the Step 2 table, and the one-line answer: usable pair-months under the refined
  rule, against 82 under the narrow rule;
- every row the rule would fix that **fails** (c), with its time, fields and the size
  of the difference;
- **Ideas and proposals** (separate), each checked against your own tables first.

## Stop conditions

- A Python traceback: stop and report it in full.
- A month outside the 14 listed above, or any file for 2025-01 or later: stop.
- The three unaligned-open counts, or the 82, not reproduced and not explained: stop
  and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish", all eleven items.
Every count in the report is printed by the script.
