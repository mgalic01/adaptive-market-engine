# Historical replay method (harness v1, features `price-only-v1`)

This documents exactly what the replay does, so results can be reproduced and
challenged. It implements the "first deliverable" of [BACKTEST_PLAN.md](BACKTEST_PLAN.md).
Nothing here was tuned on results; every constant below was fixed before the first
real run.

## Commands

```bash
PYTHONPATH=src python -m crypto_grid_bot.backtest fetch  --spec config/datasets/verify-2024h1.toml
PYTHONPATH=src python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml
PYTHONPATH=src python -m crypto_grid_bot.backtest run    --spec config/datasets/verify-2024h1.toml
# Fee scenario, e.g. Revolut X: 0% maker (resting fills), 0.09% taker (exits).
PYTHONPATH=src python -m crypto_grid_bot.backtest run    --spec config/datasets/verify-2024h1.toml \
    --maker-fee 0 --taker-fee 0.0009
```

Without `--taker-fee` the taker fee equals the maker fee. The fees used are recorded in
`results.json` and in the output directory name. `--fill-trigger RATE` is for the
missed-fill sensitivity sweep only (spec v1 §4, owner decision D9): it sets how far a quote
must cross a resting limit, which otherwise equals the slippage. Exits and marks keep the
slippage, and the run records the setting in `results.json` and as `-fill<RATE>` in its
directory name.

`fetch` is the only command that uses the network: it reads public archive files from
`https://data.binance.vision` and the current exchange filters from the public data
API. `verify` and `run` are offline. `run` refuses to start unless every local file
matches the committed manifest's SHA-256. Results go to `data/backtests/<dataset>/<UTC
time>/` (`results.json` and `summary.md`), which is not committed.

## Data

- **Source:** Binance monthly spot kline archives (`data/spot/monthly/klines/<SYMBOL>/<1m|1h|1d>/`).
- **Format** (verified 2026-09-24 on real files): one headerless 12-column CSV per zip.
  Timestamps are milliseconds up to 2024-12 and microseconds from 2025-01; both are
  normalised to milliseconds and checked to be exact candle boundaries.
- **Integrity:**
  - Every zip is checked against Binance's published `.CHECKSUM` before it is stored.
  - The dataset manifest (`config/datasets/<name>.manifest.json`, committed) records
    each file's URL, SHA-256, size, row count, missing rows, gaps, timestamp unit and
    the download date.
  - A month Binance does not publish (for example before a pair was listed) is recorded
    as `missing` and never filled in.
- **Files per dataset:** 1m klines for traded pairs cover the evaluation window only;
  1h klines for traded pairs, the market proxy and the breadth basket also cover the
  warm-up months. When a spec declares `daily_warmup_start`, 1d klines for the traded
  pairs and the market proxy cover that month onward (spec v1 P3).
- **Exchange filters** (tick size, quantity step, minimum notional) are today's values
  from the public API, applied historically. This is an approximation and is recorded
  as such in the manifest.
- **Chronology cross-check:** `verify` aggregates every traded pair's 1m bars into hours
  and compares them with Binance's own 1h archive. Open, high, low and close must match
  exactly. **Volume is compared within a 0.1% tolerance** (`VOLUME_DRIFT_TOLERANCE`, rules
  `drift-tolerance-v1`, an owner decision recorded in spec v1 §5); an hour inside it is
  counted as `hours_volume_drift` and is not a failure. `--strict-volume` restores exact
  matching and records the rules as strict. Results record which rules were used.

## From klines to simulator quotes

Klines contain trades, not quotes. The adapter in `backtest/replay.py` is explicit:

- **Price points:**
  - Each 1m bar becomes four quotes: open, first extreme, second extreme, close. They
    are stamped at +0, +9, +19 and +29 seconds, so every quote falls within the
    engine's 30-second data-age limit.
  - `high_first` visits the high before the low; `low_first` the reverse. The true order
    is unknown, so both are run and reported.
- **Bid and ask:**
  - OHLC does not say whether an extreme was buyer- or seller-initiated. The adapter
    *assumes* a trade at the high lifted the ask (ask = high, bid one assumed spread
    lower) and a trade at the low hit the bid (bid = low, ask one spread higher).
  - Open and close are mid prices.
  - Every price, the extremes included, rounds outward to today's tick.
  - The assumed spread is a dataset parameter (`assumed_spread_pct`; 0.05% in
    `verify-2024h1`).
- **Crossing:** the unchanged engine still requires a limit to be crossed by the slippage
  rate (the fill trigger, which only the missed-fill sweep sets apart, D9). Touching a
  level never fills.
- **Liquidity:**
  - Taker-sell volume can fill resting buys; taker-buy volume can fill resting sells.
  - Each side's bar volume is split evenly over the four quotes, and the engine's
    participation cap (10%) applies to each share. A bar's volume is never spent twice.
  - The even split is an assumption, not volume observed at those prices.
- **Scenarios, not bounds** (clarified after Codex's review of PR #9):
  - The two paths are plausible scenarios, and the worse of them is not a worst case.
  - The adapter is not proven conservative.
  - The +0/9/19/29 s stamps are simulation times that compress a minute into 29 s. That
    can shift recovery and range timers.
  - Spread, participation, path, missed-fill and timing sensitivity must be reported
    before any result counts as acceptance evidence.
- **No invented round trips:** all four quotes share one *epoch*. An order created inside
  a bar (a grid buy, a child sell or a re-entry buy) cannot fill until a later bar, so
  a buy and its child sell never both fill on an assumed favourable path inside one
  minute. A regression test fails without this rule.
- **Costs:**
  - Fees are charged in quote currency. The spec's fee (default 0.1%, the Binance base
    rate without the BNB discount) is the **maker** fee; `--maker-fee` overrides it.
  - Resting limit fills (grid buys and sells) pay the maker fee and are booked at the
    limit price. The engine's 0.05% slippage is a crossing buffer, not an extra cash
    debit.
  - Marketable exits (range exits, liquidation), the buy-and-hold baseline and every
    equity mark pay the **taker** fee and do apply price haircuts.
  - Equity marks use the unrounded bid × (1 − slippage), while an actual exit fill floors
    that price to the tick, so a mark can exceed what an exit realises by at most one
    tick per unit held.
  - The grid cost rule uses two maker fees: `2 × (maker + slippage) + spread`.
- **Order-request budget:** each step's placements plus cancellations are counted per
  UTC day. Results report the total, the busiest day and the days above 1,000 requests,
  which is Revolut X's documented daily limit for placing orders. Counting
  cancellations too is conservative if the exchange meters them separately. The budget
  is measured, not enforced.

## Strategy inputs: hypothesis `price-only-v1`

All inputs for the minute starting at `m` use only hourly candles that closed before
`m`. A test changes every unfinished and future candle and checks that the decision
inputs are unchanged, and that changing the last completed candle does change them.

**Broad market** (market proxy `M`, BTCUSDT in `verify-2024h1`):

| Signal | Formula |
| --- | --- |
| trend | `tanh((SMA20/SMA50 − 1) / 0.02)` |
| momentum | `tanh(24h return / 0.05)` |
| breadth | `2 × share of basket markets with close > SMA50 − 1`; needs ≥ 5 fresh markets, otherwise the regime is vetoed |
| volatility_health | `−tanh(max(0, ATR%/median(ATR%, 30 d) − 1))`: 0 when volatility is at or below its 30-day median, negative when elevated |
| liquidity_health | `−tanh(2 × max(0, 1 − QV24/median(QV24, 30 d)))`: 0 when volume is normal, negative when it dries up |
| adx | Wilder ADX(14) on hourly candles |
| data_quality | share of the last 168 hours present, the lower of `M` and the traded pair; 0 when the latest candle is over 2 h old |
| news_risk | **0: component ABSENT.** There is no historical news source. Every result states this; it is not evidence that there was no news risk. |
| emergency | always false. There is no price-only emergency detector in v1. |

The health signals only ever vote *negative*. This avoids the pathology noted in
review 2: a perfectly healthy market would otherwise vote bullish and block RANGE.

**Traded pair** (`P`):

| Metric | Formula |
| --- | --- |
| range_quality | `1 − efficiency ratio(20 h)` |
| net_grid_edge | `clamp((S/K − 1) / (2 × 3 − 1))`, where `S` is the geometric spacing of an 8-level grid over `SMA20 ± 2 × ATR14` and `K` is the round-trip cost `2 × (fee + slippage) + spread` |
| liquidity_quality | `clamp(log10(24h quote volume / 100,000) / 2)` |
| downside_quality | `1 − clamp(max drawdown over 168 h / 20%)` |
| data_quality | share of the last 168 hours present; 0 when stale |
| spread_pct | the assumed spread |
| depth_multiple | `(24h quote volume / 1440) / max(0.8 × releasable cash, minimum notional)`, recomputed before every quote. Releasable cash = cash − pending reserve + every resting sell at its limit + unreserved inventory at the current bid. That covers a step that sells, settles and reopens (Codex's R2 follow-up) and uses no later price in the bar. This upper-bounds any single buy the engine could place: `_open_grid` gives one pair all 80% of unprotected cash. It tracks reinvestment and excludes protected reserve. Volume is a liquidity proxy, not observed book depth. This is R2 from Codex's review; earlier versions assumed 8, then 4, orders and overstated depth. |
| fair value | SMA20 of hourly closes |
| ATR | simple ATR(14) of hourly candles |

**Degenerate history:**
- A zero 30-day ATR or volume median, or a zero pair ATR (a flat or zero-volume
  history), makes the ratios undefined.
- The inputs are then marked `degenerate`: data quality 0, which the quality veto turns
  into no new entries, in the gated and ungated runs alike.
- Bars are not skipped, so existing inventory is still marked, drained and
  risk-managed.
- The engine rejects a zero ATR, so a tick-sized placeholder is passed. The veto means
  it can never size a grid.

**Window semantics:** gaps are skipped, not filled. "24h", "168h" and "30 d" therefore
mean *observation counts*, which can span a longer elapsed time when hours are missing.

Warm-up: the current feature set first becomes ready after 743 completed hourly
observations (zero-based index 742). The 24-hour volume series begins at index 23,
and its baseline needs 720 defined observations. Every dataset includes at least
two hourly warm-up months before `start`; readiness is still checked from the actual
available observations, not inferred from the calendar span.

**Variant A's daily bar:** with `--variant-a` or `--variant-c`, each observation reads the
trend state of the previous UTC day's completed daily bar (`TrendSchedule.at()`,
`effective_state()`). If that bar is missing, the state is Unavailable, which spec v1 §3 A
treats as Middle: no new grid, while an existing grid keeps running (its sells, reentries
and range exit as in V0) and no fill is forced. A missing daily bar inside the window
therefore blocks new grids, and since SMA200 needs 200 consecutive days (D6), it does so
for up to 200 days; it is not an error. A registered run cannot reach this state: P3's
integrity check rejects a daily archive with a gap.

**Variants E to H** (`--variant-e`, `-f`, `-g`, `-h`, `-cg` and `-ch`, spec v1 §3) read only
what was complete at the decision: E the pair's own hourly and 1m bars, F its 1m bars, G
the BTCUSDT funding records already usable at the quote, and H its daily bars, with the
observation's own halving phase. Their rows add the spec's "Reported" values for E, G and
H (each variant's fields are named after it). Notes on each:
- **E** keeps its milestones on the clock from the episode's first outside observation
  `t0`, whatever gaps pause V0's accumulated outside time: it decides once, at the first
  valid observation at or after `t0 + 6 h`, and an extended episode exits at the first
  one at or after `t0 + 12 h`. Otherwise V0's own range exit applies unchanged.
- **F** holds a fragment below the minimum notional for its target's own sell: the
  ordinary drain of unpaired inventory leaves it, while a V0 drain, a range exit and a
  halt's liquidation sell it like any inventory. Once its grid has ended (harvested after
  a range exit, a drain or its last sell, or left with no order once F stops blocking, so
  that the account re-centres), it is ordinary unpaired inventory, which the drain sells
  once a price makes it sellable. At the end of a run a held fragment is reported as dust.
- **G**'s funding archives may be listed in a manifest beside the klines (a `kind` of
  `fundingRate` and no `interval`); they are checksum-verified like them, and `fetch`
  fetches and keeps them. A G or C+G run needs BTCUSDT's archive for every evaluation
  month and is refused without it, rather than blocking every new grid. No committed
  manifest lists any yet, so until P8's entries are added, G and C+G cannot run.
- **H3** relaxes the opportunity-score minimum (0.70 to 0.60) only for the decision to
  open a new grid, while the account holds no grid. A grid that exists is judged by V0's
  minimum, so a grid opened only because of H3 pauses, and drains, at its next frame scored
  below 0.70: the spec's "new grids only", not a defect. H3's all-time high needs daily
  history from the most recent halving, which only P8's extended history provides, so
  without it H3 never relaxes an entry.

**The full stack** (`--variant-full`, spec v1 §3, test-plan amendment of 2026-10-05) is
C+F+G+H with the V2 structure features, which the flag turns on itself: its gated rows
name the variant `C+F+G+H` and carry the `price-only-v1+structure-v2` label, as every
`--structure` row does. Each part keeps its own rules. A new grid opens only when A, F, G
and H2 all allow it, and at grid open V2's level filter runs before B's cap. The policy
refuses C+F+G+H without the structure features, which the spec does not declare. V2 alone
is V0 with `--structure`.

E and F keep account state that is never saved, so they run in historical replay only
([PAPER_SIMULATION.md](PAPER_SIMULATION.md)).

The unchanged engine then applies:
- the regime classifier;
- the opportunity scorer;
- the grid builder's rule that spacing must be at least 3× round-trip costs;
- risk limits: 3% daily pause, 8% soft and 12% hard drawdown, with the drawdown recovery
  of [spec v1 amendment 1](EXPERIMENT_SPEC_V1.md) §3 (engine `drawdown-recovery-v1`; its
  24 h values were set after development results had been seen, as the spec discloses),
  and since engine `drawdown-recovery-v2` the owner's decisions of 2026-10-02 (D7 and
  amendments 2 and 3):
  - a soft-drawdown episode ends once at least 24 h of observed time have passed since
    it began and the normal `recovery_frames` confirmations are in: it closes without a
    rebase if the account is already back under the 8% soft limit (D7; exactly 8% still
    counts as soft), and otherwise rebases `risk_high` to the current active equity.
    Results count both (`soft_drawdown_closes`, `soft_drawdown_rebases`);
  - a hard-drawdown (`drawdown`) halt restarts automatically, at most once per halt, on
    the first valid frame at least 24 h after the halt began once the forced liquidation
    is complete (an unsellable `dust` remainder does not block it) and the risk check
    passes on a tentative rebase to the current active equity; the account then pauses
    for the normal `recovery_frames` confirmations before a new grid;
  - `emergency` and `integrity` halts stay latched until an explicit resume, and an
    `exhaustion` halt is final;
- range exit after 6 h of observed time outside the band and re-centring after 24 h. The
  outside-range clock stands still while the account is halted (amendment 3), and an
  account left flat with no orders and no exit pending clears its old band at once
  (amendment 2), so a halted account, or one left flat with no orders, never times out
  into a range exit;
- the 50/50 reserve with transfers batched at 10 quote units.

## Baselines

Every run uses the same capital, window, fee, slippage and assumed spread:

- **Cash:** 0% return.
- **Buy-and-hold:**
  - buys once at the first evaluated bar's ask, plus slippage and fee;
  - is marked at every simulated quote, on the same four-quote schedule as strategy
    equity, at bid × (1 − slippage) × (1 − fee), i.e. what an exit would realise.
- **Ungated grid:**
  - identical engine, quotes and risk limits;
  - the regime and eligibility gate are removed (a quiet, fully trusted range and an
    always-eligible pair).
  - This isolates what the gate adds or costs.
  - Because the engine re-centres at every flat point, it is not a never-moved
    static grid. A true static grid baseline is still to do.

## Verification in every run

- Every file matches the manifest before the run starts.
- **Chronology gate** (R1 of Codex's review), resolved *before* any replay starts:
  - aggregated 1m bars match Binance's 1h archive: prices exactly, volume within the
    tolerance above (exactly under `--strict-volume`);
  - no official hour in the window lacks minute data;
  - no hour is missing from both sources;
  - no hour is missing individual minutes. Bar equality cannot reveal a missing
    zero-volume minute, so these are counted directly.
  - when the spec declares daily history, **two different checks** run, because the
    daily window normally starts earlier than the hourly one (`verify-2024h1`: daily
    from 2023-05, hourly from 2023-11):
    - over the **whole daily window**, every UTC day appears exactly once
      (`daily_days_missing`, `_duplicated`), with enough completed days of warm-up
      (`daily_warmup_short`);
    - over the **overlap with the hourly window only**, each day must also equal the
      aggregation of its 24 unique hourly bars (`daily_days_mismatched`,
      `_hours_incomplete`). Prices must match exactly; volume within the same 0.1%
      tolerance, reported as `daily_days_volume_drift`. Days before the hourly window
      are checked for presence, never for equality.
  - Any non-zero count of those fields makes `verify` and `run` exit with code 2, and
    nothing replays. `hours_volume_drift` and `daily_days_volume_drift` are reported but
    are not among them.
  - Gaps from a genuine listing or delisting are not exempted yet; such a dataset must
    first declare them explicitly.
- **Run validity:** accounting problems, rejected frames, zero evaluation bars, or a
  run that ends still unable to exit because the bid is too thin mark the run
  `"valid": false`, and `run` exits 2. The results are kept for diagnosis but are
  not performance evidence.
- **Refused exits:** an exit order below the exchange's minimum notional is refused, as
  an exchange would refuse it, and every refusal is counted (`exit_blocked_frames`,
  split by kind, the longest streak, and `final_exit_blocked`):
  - `depth`: this frame's share of the bid is too small; only a deeper bid clears it.
  - `dust`: the whole unsold remainder is worth less than one minimum order at this
    bid; only a higher price clears it. It is reported, not failed. It no longer blocks
    profit settlement or a new grid, and it stays marked in equity at the bid
    (`max_unsellable_notional` and `final_unsellable_notional` show how much).
- **The end of a run** is judged from the account at the last quote, not from the last
  refusal, so a partial fill or an idle frame cannot hide an unfinished exit.
  `final_exit_blocked` is `incomplete` when an exit was owed (liquidation, range exit or
  drain) and inventory the market would still accept is unsold — that **fails the run** —
  `dust` when only an unsellable remainder is held, which is reported, or absent.
- **Identity:** `results.json` records the SHA-256 of the dataset spec, the manifest and
  the config, and the `engine_version`. Results from different engine versions are
  different trials and are never pooled; results without the field predate
  `exit-residue-v1`.
- Exact Decimal identities between the fill journal and the final account:
  - cash = initial − buys − buy fees + sells − sell fees − secured reserve;
  - inventory = bought − sold;
  - fees match;
  - the transfer journal reconciles to the secured reserve.
- `transient_pauses` counts any frame the engine rejected as stale or out of order;
  with correct chronology it must be 0.

## Acceptance scoring (spec v1 §6)

```bash
PYTHONPATH=src python -m crypto_grid_bot.backtest.acceptance \
    data/backtests/verify-2024h1/<stamp>/ data/backtests/practice-2022/<stamp>/ ... \
    --out data/acceptance/verdict.json
```

`backtest/acceptance.py` turns the `results.json` files of the §4 matrix into the §6
verdict. It runs no replay and reads no market data. Besides those files it reads only
the frozen inputs, which every run must match:

- **The code.** Each run must record a clean `code_commit`, the same for every run, and
  a `code_sha256` equal to the scorer's own source identity. The scorer must run from
  that same clean commit.
  - Variant runs and `--trend-benchmark` runs record both anyway. A plain V0 run records
    them only with `--record-commit`.
  - So run the whole batch with `--record-commit` from one clean checkout of the frozen
    commit, and score it from that same checkout.
- **The committed files.** `config/default.toml`, and each window's dataset spec and
  manifest in `config/datasets`, must hash to the `config_sha256`, `spec_sha256` and
  `manifest_sha256` each run recorded.
  - A batch run on a tuned copy of any of them is refused, however well its files agree.
  - Either line-ending form is accepted, since Git checks the same files out with LF on
    Linux and CRLF on Windows.

It prints a table and writes the verdict as JSON, with every figure behind it and the
scorer's own commit and source hash. The JSON numbers are exact: a decimal where it
terminates, otherwise `p/q`.

- **Inputs.** Pass one run per variant and window. Every `run` writes the ungated V0
  rows that C6 compares against, and D comes from V0's file (`run --trend-benchmark`).
  Each input must be an acceptance run:
  - engine `drawdown-recovery-v2`, features `price-only-v1` (no `--structure`) and
    integrity rules `drift-tolerance-v1`;
  - the primary fees (maker 0, taker 0.0009) and §4's slippage, participation, spread
    and capital, with no fill trigger;
  - the frozen code and committed files above.

  Anything else is refused with exit code 2, and nothing is scored: a sensitivity run,
  an unknown variant, the same run twice, another commit or code, or a changed config,
  dataset spec or manifest.
- **The verdict file.** `--out` never keeps an earlier verdict. Until a run finishes it
  holds "not scored", and a refused run leaves "refused" there with the reasons. Neither
  names a winner. `--out` may not be one of the results files.
- **Comparison mask (§5).** A pair-window is excluded for every variant alike in three
  cases:
  - a recorded check fails on the market proxy or on an untraded basket symbol, which
    feed every pair, so every pair is excluded;
  - the pair's own minute, hourly or daily check fails, which excludes that pair only,
    even when it also votes in the basket;
  - the pair fails the filter check (P4: `practice-2022` SOLUSDT).

  Results exist only where the manifest and checksums passed. Every file of a window
  must give the same mask. A window left with fewer than 2 included pairs gives
  "insufficient evidence".
- **Criteria,** over each variant's included runs (both windows, both paths):
  - C1: `max_drawdown_pct` and `active_max_drawdown_pct` ≤ 10 in every run, and
    `hard_drawdown_halts` 0.
  - C2: each path's median return > 0, and the mean over all runs > 0. The return is
    exact, from `final_total_equity` ÷ `initial_quote`; `return_pct` is a float.
  - C3: `max_drawdown_pct` < `buy_and_hold_max_drawdown_pct` in every run.
  - C4: every run valid. A run is invalid by `run`'s own rule (accounting problems,
    rejected frames, no evaluation bars, an exit left incomplete), or when its whole
    file failed, such as a checkout that changed during the run. A run missing from the
    matrix also fails C4.
  - C5: the mean of `completed_cycles` × 7 ÷ the spec window's days, at least 1. The
    window is 182 days for `verify-2024h1` and 245 for `practice-2022`.
  - C6: in at least 60% of runs, return ÷ max(`max_drawdown_pct`, 0.1) beats the
    ungated baseline's from the same file. A missing or invalid baseline counts against.
  - R1, reported only: 5 ÷ the mean monthly return fraction, where a run's monthly
    return is its window return ÷ the window's calendar months. It is "not reachable" at
    or below 0.
- **Verdict.** A variant passes only if all of C1–C6 pass.
- **Selection.** It runs only over the whole §4 matrix: both windows, all eleven
  variants and no missing run. Anything less gives "incomplete matrix".
  - It follows §6 steps 1–5. The means are rounded to 6 decimals, half away from zero,
    before any comparison, and the 0.25-point tie set is inclusive.
  - D is never selected. E is not eligible until Codex has reviewed it (`E_ELIGIBLE` in
    the module).
  - The outcome is a winner, "no winner", "insufficient evidence" or "incomplete
    matrix". C7 is not evaluated: it is unsettled and selects nothing.
- **Limits.**
  - The drawdowns in `results.json` are floats rounded from exact Decimals. The scorer
    compares them exactly as written.
  - The mask is derived here until the runner writes it into the results.
  - The reserved window cannot be scored yet, because `load_spec` refuses months after
    2024-12.

## Known limitations of harness v1

- **Survivorship:** `verify-2024h1` trades BTC and ADA, which still exist today. The
  expansion must include pairs that were later delisted, and must use only months the
  archive publishes.
- **Market microstructure:** 1m OHLCV hides the intrabar path, queue position and the
  real spread. Results are only as good as the stated assumptions; spread and path
  sensitivity must be reported.
- **Exchange filters and fees:** today's Binance filters are applied historically, also
  in fee scenarios for other exchanges. Buy fees are charged in quote currency rather
  than in the asset received. A 0% maker fee makes the fill model matter more: fills
  still require the quote to cross the limit, but queue position is not modelled.
- **Single market per run:** there is no rotation between markets and no
  multi-grid portfolio.
- **Currency:** results are in quote-currency units (USDT). There is no EUR
  conversion and no hosting cost.
- **Sampling:** strategy and buy-and-hold drawdown both use all four simulated quotes
  per minute bar. These sampled paths still cannot recover actual intraminute prices.
  Historical results from before this common-sampling correction retain their original
  code/measurement provenance; this documentation update does not recompute them.
- **Performance:** about 200 µs per engine step, or roughly 3.5 minutes per pair,
  path and variant for six months on one core.

## Proposed acceptance criteria (NOT yet agreed; owner decision)

> **Superseded by the draft [experiment specification v1](EXPERIMENT_SPEC_V1.md) §6,**
> which records the owner's decisions of 2026-09-24. The list below is kept as history.

Proposed for the go/no-go screen on an untouched test window. Suggested window:
2025-01 to the latest complete month, 10-20 markets including later-delisted ones.
They are fixed before that window is run.

1. **Integrity:** zero accounting problems and zero chronology rejections in every run.
2. **Beats cash robustly:** the gated strategy's median return across markets is above
   0% after all costs, in *both* path modes. The worse path decides.
3. **Risk:** no market exceeds the 12% hard-drawdown limit by more than slippage, and
   the gated strategy's median max drawdown is below buy-and-hold's.
4. **The gate earns its place:** the gated strategy beats the ungated grid on
   return ÷ max drawdown in at least 60% of markets.
5. **Economics:** report the capital needed for grid profit to cover €5/month hosting.
   If that exceeds the owner's intended capital, the result is a no-go at that size,
   whatever the percentage returns.

If the screen fails, the recommendation is to change or stop the strategy before
building news, CoinMarketCap or live-trading infrastructure.
