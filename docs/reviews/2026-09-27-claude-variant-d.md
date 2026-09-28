# Claude → Codex and Bob: variant D, the trend benchmark, as code (off by default)

Index: 2026-09-27: spec v1 §3 D as code, **off by default** (`--trend-benchmark`), in its own module (`backtest/trend_benchmark.py`), separate from the grid runner, the risk engine and the paper store. Shared pure daily-SMA module `strategy/daily_sma.py`. Same quotes, evaluated minutes, marks, buy-and-hold and P2 sampling as V0; hand-computed synthetic tests. **No replay run, nothing downloaded.** Nine questions for Codex, all answered in Codex's review (AGREE WITH CHANGES at `e8c3cca`); **Revision 2** (2026-09-28) fixes Codex's precision defect (sizing and settlement at one explicit precision on both sides, with the supported-input regression), records the tick-rounding convention beside the price formulas, and adds the end-to-end fail-closed test the automated reviewer asked for.

2026-09-27. Named writer: Claude (subagent of the desktop session `a05e63c8`, isolated
worktree). Branch `claude/variant-d-trend-benchmark`, created from `origin/main` at
`b7a857b337c538311f754046542f5e7f5be56272`; the code commit was then merged with `main`
at `c3c8e250bc5ec8837498d47bd0090cc4bd8c2edc` (which includes variant B, PR #99). The
PR comment for the push names the head.

Scope: `src/crypto_grid_bot/strategy/daily_sma.py` (new),
`src/crypto_grid_bot/backtest/trend_benchmark.py` (new), one opt-in flag in
`src/crypto_grid_bot/backtest/__main__.py`, `tests/test_trend_benchmark.py` (new),
this file and its index row. No change to V0, the grid replay (`replay.py`), the pool
jobs (`jobs.py`), the simulator, the risk engine, any parameter, any dataset spec or
the integrity rules.

**No replay or backtest was run, nothing was downloaded, and no 2025+ data was
touched.** Every test uses synthetic bars.

## What D does

Spec v1 §3 D: hold the traded pair while its completed daily close is above its SMA50,
hold cash otherwise. It is a benchmark, not a grid, exempt from the §3 common risk rule,
and it cannot be selected (§6).

- **Separate path.** D never goes through `PaperSimulator`, the risk engine, the profit
  vault or the paper store. `replay_trend` runs on the replay's own quotes
  (`bar_quotes`) with its own one-pot account (`TrendAccount`: cash and inventory, no
  reserves). It writes no shared or persisted state.
- **Shared signal module.** `strategy/daily_sma.py` holds pure, exact-`Decimal`
  functions: `signal_day` (the latest daily bar completed at an observation),
  `DailyCloses` (closes keyed by UTC-midnight open, with `close`, `window`, `sma`) and
  `close_above_sma` (exact `close × n > sum(window)`, no division). Variant A needs the
  same completed-bar timing with SMA50 and SMA200; **the A branch
  (`claude/variant-a-trend-switch`) may reuse this module** instead of writing its own.
  Nothing else imports it yet, so it cannot conflict with A or with B (PR #99).
- **Wiring for a registered run.** `python -m crypto_grid_bot.backtest run ...
  --trend-benchmark` adds one D run per traded pair and path, with the same fees as the
  grid runs. The flag is off by default. Without it, the CLI submits the same jobs and
  writes the same `results.json` layout as before. With it, D rows carry
  `"variant": "D"`, `"benchmark": true`, `"selectable": false` and a `risk_policy`
  label, and the document gains `"trend_benchmark"`. **The flag was added and tested
  with a mocked pool; it was not used on real data.**

## Spec mapping, line by line (§3 D)

| Spec text | Where | How |
| --- | --- | --- |
| Held while the completed daily close is above its SMA50, cash otherwise | `replay_trend`, `close_above_sma(closes, signal_day(t), 50)` | strict `>`; equal is cash |
| Missing, undefined, zero or negative values mean cash | `DailyCloses.close/window` | a missing day in the 50, fewer than 50 days, or a close ≤ 0 makes the value `None`, which is cash; no older bar is substituted |
| Completed bars only; effect at the first valid observation at or after 00:00:00 UTC of the next day (§3 timing) | `signal_day(observed_ms) = floor_day(t) − 1 day` | the observation at 00:00:00.000 uses the bar that just closed; 1 ms earlier it does not |
| All cash goes in at each entry; floored to the lot step; skipped below the minimum notional | `entry_quantity`, `enter` | `floor_step(min(capacity, cash ÷ (price × (1 + taker))))` |
| No profit vault or reserves; one pot | `TrendAccount` | equity = cash + inventory × mark |
| Marketable at the next valid observation: ask × (1 + slippage) buys, bid × (1 − slippage) sells, taker fee | `buy_price`, `sell_price`, `enter`, `exit_step` | fee = notional × taker; see question 2 on tick rounding |
| At most the 10% ask- or bid-size participation limit per observation, as V0's liquidation | `entry_quantity` (ask size), `exit_step` (bid size) | same fields and flooring as `reduce_unreserved` |
| Entry residual = the remaining quote budget; ends when the quantity is below the minimum | `enter` | literal reading, see question 1 |
| Exit residual = the base quantity held; unsold remainder below the minimum stays as reported dust | `exit_step` | a participation-limited observation retries; the exit ends when the whole remainder is below the minimum; `exits_ended_with_dust` is reported |
| Reversal while filling: the unfinished side is abandoned; the new side starts at that same observation | `replay_trend` | entries/exits abandoned are counted; an exit abandoned keeps its inventory and the new entry adds with the cash on hand |
| Unchanged from A: capital, marks, warm-up, timing, fees | `trend_job`, `exit_value` | capital from the spec; mark = bid × (1 − slippage) × (1 − taker) as `Account.equity`; same fees as the grid runs; see question 3 on warm-up |
| Exempt from the risk controls | whole module | no pause, halt or emergency exit exists in D's path; `halted_at` is always null |
| Replay-only, never writes shared or persisted state | whole module | no store, no file writes |
| C1 for D: active = total equity, C1(b) reduces to C1(a) against its own peak; no halts | `summarise_trend` | `active_max_drawdown_pct` = `max_drawdown_pct`; `hard_drawdown_halts` = 0 |
| P2: common sampling, every quote of every bar after that quote's fills, for strategy and buy-and-hold | `replay_trend` | same `_BuyAndHold` object from `replay.py`, started at the same first evaluated bar and marked at the same quotes; `hourly_equity` has V0's shape and schedule |
| §5 mask | not in D | the mask is variant-independent and written before scoring; D uses the same pair-windows. A spec with no `daily_warmup_start` makes a D run invalid rather than silently all-cash |

## Ambiguities: questions for Codex

Each is implemented with the reading stated, which I take as the most conservative. None
changes V0.

1. **Does a thin observation end an entry?** The spec says "the entry ends when that
   quantity is below the minimum notional", where "that quantity" is the smaller of the
   participation limit and the cash bound. Read literally, a zero-volume first
   observation ends the entry with the cash unspent until the next reversal. The other
   reading ends the entry only when the *cash* bound is below the minimum and retries a
   participation-limited observation, as the exit does. **Implemented: the literal
   reading** (test `test_literal_reading_a_thin_entry_observation_ends_the_entry`). With
   100 quote units the cash bound is almost always the smaller, so the two readings
   differ only in a minute with near-zero volume. Please confirm or choose the other.
2. **Tick rounding of D's execution prices.** The spec writes `ask × (1 + slippage)` and
   `bid × (1 − slippage)` without rounding. V0's liquidation floors its sell price to
   the tick. **Implemented: sells floored (as V0), buys rounded up**, both against D. The
   unrounded alternative would make D slightly cheaper to run. Please confirm.
3. **Which minutes D evaluates.** "Unchanged from A: warm-up" is read as: D evaluates
   exactly V0's evaluated minutes. A minute that the grid replay skips because its
   hourly features are not ready is skipped by D too, so D's first bar, its buy-and-hold
   and its hourly samples coincide with V0's (checked in
   `test_same_evaluated_bars_hourly_schedule_and_buy_and_hold_as_v0` and end to end in
   `TrendJobTests`). The alternative is to start D at the first minute of the window
   regardless. With the current specs both start at the first minute, because the
   hourly warm-up finishes in the warm-up months, so the difference is theoretical.
4. **Start in the market?** At the first evaluated observation D starts in cash. If the
   signal already says hold, the entry starts at that observation; D does not wait for a
   fresh cash-to-hold crossing. This follows "held while", but please confirm.
5. **SMA50 includes the day's own close.** `SMA50` is the mean of the 50 completed closes
   ending at `C`, as A's table uses `C` with `SMA50` and `SMA200` of the same day. Please
   confirm this is also A's definition, so the shared module means the same thing for
   both.
6. **200-day warm-up.** D needs only 50 days itself. The 200-day requirement is enforced
   by the variant-independent §5 mask (`daily_warmup_short`), not again inside D. D
   refuses a spec with no daily history at all. Is that division acceptable?
7. **C5 for D.** P7 counts grid sells only, so D reports `completed_cycles: 0` and fails
   C5 trivially. Since D's C1–C6 are for information only (§6.5), I left it that way
   rather than inventing a D cycle. Please confirm.
8. **Valid observations for D.** D has no engine, so no frame is ever rejected
   (`transient_pauses` is 0). A missing minute simply means the next present minute is
   the next observation. The §5 data checks still exclude a pair-window with gaps.
9. **Request counting.** Each D fill is counted as one marketable order request; an
   observation that fills nothing sends nothing. This only feeds the reported
   per-day request maximum.

## Tests

`tests/test_trend_benchmark.py`, 25 tests, synthetic data only. Prices, quantities and
fees are computed by hand from the adapter's rounding and written as literals.

- **Signal:** `signal_day` at 00:00:00.000 and one millisecond earlier; SMA by hand
  (1.02, 1, 0.9998, 5); strict comparison at equality; short history, a missing day, a
  missing current bar, zero and negative closes are all undefined; a later bar never
  changes an earlier value; malformed series rejected.
- **Fills with fees:** one entry fill (price 1.0009, 99.8 units, fee 0.089900838, cash
  0.020279162); entry then exit (sell 1.1991, fee 0.107703162, cash and equity
  119.582756, realised 19.582756); a participation-limited entry over four quotes sized
  from the remaining budget; a retry that never spends more than the cash left; dust
  below the minimum; a thin exit observation retries; the literal entry-end reading.
- **No lookahead:** the first fill is at 00:00:00 after the signal bar closes, not in
  the minutes before; the bar still forming during a day cannot change that day's fills
  whatever its value.
- **Warm-up:** 49 daily bars means no position all run; minutes the grid replay skips
  are skipped, and the entry starts at the first evaluated one.
- **Reversals:** an entry abandoned and the exit started at the same quote; an exit
  abandoned, inventory kept, and the new entry adds to it.
- **P2 alignment:** against a real V0 `replay` on the same minutes and feature engine,
  D has the same warm-up count, bars, first and last bar, hourly timestamps and
  identical buy-and-hold values; one sample per quote; an intrabar dip is caught.
- **Accounting:** cash, inventory and fee identities, final-equity identity and the P6
  reconciliation; tampering detected; a spec with no daily history is invalid.
- **V0 unchanged:** without `--trend-benchmark` no D job is submitted and
  `results.json` has no new key and the same eight rows; with it, one D job per pair
  and path with the CLI's fees. `trend_job` pickles by reference for spawn workers.
- **End to end:** `trend_job` and V0's `run_job` on a tiny synthetic archive
  (hash-checked zips, no network) share the window, bar count, hourly timestamps and
  buy-and-hold values.

## Verification actually run

Windows 10, Python 3.14.7, in the isolated worktree, on the merge with `main`
`c3c8e25`, before the push:

- `PYTHONUTF8=1 python -m pytest -q`: 482 passed, 2 skipped (the existing Windows
  symlink skips), 571 subtests; 25 of the passes are the new tests. Before the merge,
  on base `b7a857b`: 433 passed without this change, 458 with it.
- `python -m ruff check .`, `python -m ruff format --check .`: clean.
- `python -m mypy` (strict, `src`): no issues in 40 files.
- `python scripts/check_reports.py`: 0 problems.

## Limits

- No real-data run. Whether D behaves sensibly on `verify-2024h1` or `practice-2022` is
  unmeasured; only the arithmetic and the wiring are tested.
- The scorer that computes C1–C6 does not exist yet. D's rows carry the fields it will
  need (`return_pct`, `max_drawdown_pct`, `active_max_drawdown_pct`,
  `buy_and_hold_max_drawdown_pct`, `hourly_equity`), named as in the grid rows.
- `trend_job` builds its warm-up gate from the pair and market-proxy hourly series only.
  `FeatureEngine.at` returns `None` exactly when one of those two is not ready; the
  basket and sizing parameters change values, never that gate. The end-to-end test
  checks this on one synthetic dataset, not on the real ones.
- The questions above are open; a different answer changes a few lines in
  `trend_benchmark.py` and the tests named with them.

## Compatibility, security, rollback

- **Compatibility:** V0 and the grid replay are untouched (`git diff` shows no change in
  `replay.py`, `jobs.py` or `simulation/`). The CLI is unchanged unless the new flag is
  passed.
- **Security:** no network access, no credentials, no file writes in D's path. The flag
  only adds jobs of the same kind as the existing ones.
- **Rollback:** revert the PR's commit. Nothing persisted depends on D.

## Safe next steps

1. Codex answers questions 1–9 on the PR (or in a reply file); Claude adjusts the
   stated lines if needed.
2. Bob checks the code against §3 D line by line (requested on the PR).
3. The A branch decides whether to import `strategy/daily_sma.py`.
4. D runs only inside a registered practice-matrix run with `--trend-benchmark`, after
   the prerequisites and the owner's go for that run.
