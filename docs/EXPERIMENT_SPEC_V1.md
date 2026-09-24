# Experiment specification v1 (DRAFT for review, not yet frozen)

**Status:** draft by Claude. It becomes frozen only when Codex has reviewed it and the
owner has confirmed the acceptance criteria in §6. After that, a change requires a new
version (v2), and results under v1 stay reported. **No strategy code exists for these
variants yet.** This document fixes what will be built and how it will be judged,
*before* any variant is run.

The scope is paper trading and historical replay only. Nothing here authorises live
trading, API keys or withdrawals. The default risk limits (3% daily pause, 8% soft and
12% hard drawdown, latched halt), the 50/50 profit vault and the paper-only boundary
are unchanged by every **grid** variant (V0, A, B, C, F). The benchmark D is the one
labelled exception (§3 D): it is a replay-only calculation with its own sizing and no
risk controls or vault, and it never touches persisted paper state.

## 1. Question

Starting from `price-only-v1` (V0), do any of the pre-registered mechanisms reduce
forced-exit losses enough to make money after Revolut X fees, with a smaller worst drop
than simply holding? The diagnostic
[fee-levels-2026-09.md](backtests/fee-levels-2026-09.md) motivates the question: resting
grid sells realised gains, and forced marketable exits realised as much or more in
losses.

## 2. Prerequisites (implemented and reviewed before any variant run)

These are measurement and data changes, with two qualified exceptions:
- **P4 can change V0 decisions** on formerly invalid SOL runs. Those runs become a
  newly labelled scenario, "SOL with sourced historical filters". Today's filters are
  never backdated as historical ones.
- **P5 changes how invalid CLI input is handled:** an empty fee value is rejected.

**Equivalence requirement:** on every existing valid default run (`verify-2024h1` ADA and
BTC, `practice-2022` BTC and XRP, both paths), V0's fills, returns and accounting must be
identical before and after P1–P7. Valuation sampling (P2) must not change V0's engine
risk logic or fills. It records marks from the same actual quote, after that quote's
fills, for both the strategy and buy-and-hold.

| # | Change | Why |
| --- | --- | --- |
| P1 | **Record the exit reason** on every `exit/` fill: `range_exit`, `drain` (the engine's `draining` state), `liquidation` (halt or emergency) and, for variant A, `trend_exit`. Report the realised P&L per reason. | Codex (PR #14): losses cannot be attributed to range exits without it. |
| P2 | **Common drawdown sampling:** strategy total equity and buy-and-hold equity are sampled on the same schedule: every quote of every bar, after that quote's fills. For C1(b), active equity and the reserve-adjusted `risk_high` are also recorded at every pre-fill and post-fill risk evaluation the engine performs, together with any hard-drawdown halt. | Criterion C3 compares the two drawdowns; they must be measured the same way. |
| P3 | **Daily history:** dataset specs gain `daily_warmup_start`. Binance `1d` archives are fetched from that month and checksummed. Over the overlap, every expected day must be present exactly once and contiguous, and must match the aggregation of its 24 unique contiguous `1h` bars, not just an aggregate OHLCV match. | Variants A and D need at least 200 completed daily bars before the evaluation starts. |
| P4 | **Historical exchange filters for SOL:** use dated, sourced point-in-time tick and step sizes if available. If they cannot be sourced, SOL runs stay invalid for every variant (§5). No synthetic spread model in the primary comparison. **Result (2026-09-24):** no dated official spot filter history was found. The archives themselves show that every SOLUSDT open, high, low and close from 2022-06 to 2023-01 has at most 2 decimals (lowest price 8.00), which is consistent with today's 0.01 tick. The invalidity therefore comes from the adapter's assumed spread with outward rounding at low prices (2 ticks ≈ 0.25% > 0.15%), not from a wrong filter. **SOL stays invalid in the primary comparison.** A one-tick spread model may only ever be a separately labelled sensitivity scenario; it is not part of v1. | Codex §4.1 answer on PR #15. |
| P5 | Carried nits: `--maker-fee`/`--taker-fee` use `is not None`, so an empty value is rejected; `replay()` asserts the order book is empty before wrapping it for request counting. | Automated reviews on PR #14. |
| P6 | **P&L reconciliation:** realised P&L by sell type, plus unrealised P&L of the remaining inventory at the final mark, must equal the final total equity minus the initial capital. | Codex (PR #15): attribution must reconcile with the account. |
| P7 | **Completed-cycle count (for C5):** a completed cycle is a grid sell (a child `…/sell` order placed when its buy filled completely) that itself fills completely. It is reported per run and per week. It is a count only, independent of the P1 P&L-by-exit-reason and the average-cost resting-sell attribution, and neither of those counts cycles. | Codex (PR #16): the metric must be defined before it is promised. |

## 3. Variants

Every variant is V0 plus exactly the mechanism described. They are selected by config
flags that default to off, so V0 and existing paper accounts are unaffected. Timing rules
common to all:
- Signals use **completed** bars only.
- A daily signal computed from the UTC day ending at 00:00 takes effect at the **first
  valid replay observation at or after 00:00:00 UTC** of the next day, never within the
  bar that produced it. A rejected or stale frame never executes a signal; the next
  valid observation does.
- For every grid variant (V0, A, B, C, F), every existing V0 control keeps its trigger
  and deadline: emergency exit, hard-drawdown halt, daily-loss pause, soft-drawdown
  reduction, range exit (6 h), drain and eligibility pauses. **No variant delays,
  suppresses or clears any of them.** A variant can only add restrictions (fewer buys)
  or add an exit with its own later deadline. D is the one exception: it is a benchmark
  without these controls (§3 D).

### V0: baseline (`price-only-v1`)
- **Code:** the commit that merges the prerequisites; it is recorded in every
  `results.json`.
- **Unchanged:** default config, fills, costs, data identities and the common mark
  cadence (P2).

### A: trend/cycle switch (daily SMA50 and SMA200)
Inputs are the completed daily close `C`, `SMA50` and `SMA200` of the traded pair. The
state machine runs over the whole daily history from the first day on which SMA200 is
defined, including the warm-up. The state at the first evaluated minute is therefore
already determined. The initial state, before the first classified day, is Middle.

The state is updated once per completed daily bar, from the previous state and `C`:

| State | Entered when | Behaviour |
| --- | --- | --- |
| **Up** | From Up: `C > SMA200`. From Recovering: a second consecutive `C > SMA200`. | Grids allowed, as in V0. |
| **Recovering** | From Middle, Down or Unavailable: the first `C > SMA200`. | Same as Middle. |
| **Middle** | From any state: `C ≤ SMA200` and `C > SMA50`. | No new grid. An existing grid keeps running: its sells, reentries within the grid and range exit behave as in V0. Reentries are allowed deliberately: they only rebuy levels the grid already sold, inside its existing range, and B's cap bounds the exposure in C. |
| **Down** | From any state: `C ≤ SMA200` and `C ≤ SMA50`. | No new grid, and a **Down sequence** starts unless one is already running (see below). |
| **Unavailable** | A daily bar is missing or SMA50/SMA200 is undefined. | Same as Middle: no new grid, and no fill is forced. The two-close count restarts. |

**Down sequence:**
- **Start:** it starts at the effective time of the first Down classification (`T0`).
  Resting buys are cancelled at `T0`, and resting sells stay in place.
- **Deadline:** the trend deadline is `T0 + 24 h`. Further Down days do **not** reset
  it.
- **Existing exits are not postponed:** the deadline is only an **additional upper
  bound**. A range exit, drain, halt or emergency exit that falls due earlier happens on
  its own V0 schedule; the sequence then ends early if the account is flat.
- **At the deadline:** remaining sells are cancelled, then the remaining inventory is
  liquidated with marketable `trend_exit` sells. These are bounded by the same bid-size
  participation limit as V0's liquidation. Unfilled residuals are retried at each
  following valid observation under the same limits until the account is flat.
- **A started sequence completes** even if a later close moves the state to Recovering,
  Middle or Up. A new grid requires both the Up state and no running Down sequence.

**Other rules:**
- **Hysteresis:** Up is reached only through Recovering, so it takes two consecutive
  completed closes above SMA200. Leaving Up takes one close at or below SMA200.
- **Same-step labelling:** if several exits are due at the same observation, the fills
  take the label of the highest-ranked one: halt/emergency `liquidation` >
  daily-loss/soft-drawdown actions (as in V0) > `range_exit` > `drain` > `trend_exit`.
  The ranking changes labels only, never timing.
- **Warm-up:** at least 200 completed daily bars before the first evaluated minute (P3).

### B: inventory cap
- **Definitions:**
  - **Active equity** = cash − pending reserve + inventory × mark. The secured reserve is
    already outside cash, so both reserves are excluded.
  - **Mark** = bid × (1 − slippage) × (1 − taker).
  - **Committed exposure** = inventory × mark + Σ over **every** resting buy of
    (limit price × remaining quantity × (1 + maker fee)) + the proposed buy, valued the
    same way. Resting buys are valued at their cost including the maker fee. This is
    conservative relative to ignoring pending commitments; together with the
    prospective-equity deduction below, it charges each pending buy its full cash cost.
  - **Prospective active equity** = active equity − Σ over every resting buy and the
    proposed buy of limit × quantity × [(1 + maker) − (1 − slippage)(1 − taker)]. This
    is the equity left if all of them filled at their limits and were immediately marked
    at the limit price with the exit haircut, so it deducts their fees and haircuts.
- **Cap:** committed exposure (including the proposed buy) ≤ **40% of prospective active
  equity**.
  - The rule bounds new commitments under this stated valuation.
  - It is **not** a guarantee that the ratio holds afterwards: price moves after a
    fill, or a fill at a better price, can still lift the measured ratio.
- **Placement order:** a new grid places its buy levels from the highest price down.
  - The first level that does not fit completely is **resized** to the largest quantity
    that fits, floored to the lot step.
  - If the resized quantity is below the minimum notional, that level is skipped.
  - Either way, every **lower** level is skipped. Resized and skipped levels are recorded
    in the report.
  - Reentry buys pass the same check when they are created, with the same resize or skip
    rule.
- **Rounding and fills:**
  - A capped quantity is floored to the lot step. If it is then below the minimum
    notional, the buy is not placed.
  - Partial fills do not change the check: the unfilled remainder is still counted.
  - Sell targets are unchanged, and no reserve is ever spent.
- **Price drift:** if rising prices push committed exposure above 40%, this is allowed.
  There is no forced sale, but no new buy is placed until exposure is below the cap
  again.
- **What it does not do:** it never forces a sale and never delays a sell. The cap
  constrains new buy commitments; it does not guarantee the ratio at all times.
- **40% is an experiment parameter,** not a new default, and it gives no authority to
  use protected funds.
- **Required tests:** the prospective-equity arithmetic with fees; the resize-then-skip
  boundary; concurrent resting buys that each fit alone but not together;
  reentry creation at the cap; a partial fill followed by a new buy; a price-driven
  breach (no sale, no new buy, then resumption below the cap); lot flooring below the
  minimum notional.
- **Deferred:** quote skewing by inventory (Avellaneda–Stoikov style) is not in v1. It
  would need its own spec.

### C: A + B, a declared interaction
- **Mechanism:** both mechanisms at once, with A's priority rules.
- **Reporting:** C is reported as an interaction. It is not claimed as a single
  mechanism.

### D: trend benchmark (not a grid)
- **Signal:** each traded pair is held while its completed daily close is above its
  SMA50, and cash is held otherwise. Missing, undefined, zero or negative values mean
  cash.
- **Sizing:** at each entry, all of the run's cash goes into the pair. The quantity is
  floored to the lot step, and a buy is skipped if it is below the minimum notional.
  D keeps no profit vault or reserves: all equity is one pot.
- **Execution:** entries and exits are marketable at the next valid observation, at
  ask × (1 + slippage) for buys and bid × (1 − slippage) for sells, paying the taker
  fee. Each observation fills at most the ask- or bid-size participation limit (10%),
  as V0's liquidation does.
  - **Entry residual = the remaining quote budget, not a fixed base quantity.** At each
    observation, D buys the smallest of (1) the participation limit and (2) the
    remaining cash ÷ (ask × (1 + slippage) × (1 + taker)), floored to the lot step. The
    entry ends when that quantity is below the minimum notional. So a retry can never
    spend more cash than is left.
  - **Exit residual = the fixed base quantity held.** Each observation sells up to the
    participation limit. An unsold remainder below the minimum notional stays as
    reported dust.
  - **Signal reversal while filling:** at the effective observation of a reversal, the
    unfinished side is abandoned and the new side starts at that same observation. An
    entry in progress stops, and the quantity already bought is exited. An exit in
    progress stops; the unsold inventory stays held and marked, and the new entry adds
    to it using the cash on hand.
- **Unchanged from A:** capital, marks, warm-up, timing and fees.
- **Risk controls:** D is **exempt** from the common rule in §3. It has no daily-loss
  pause, soft or hard drawdown halt or emergency exit; it only follows its signal. Its
  return and drawdown are reported as they are, clearly labelled as a benchmark with a
  different risk policy.
- **State:** D is a replay-only calculation and never writes shared or persisted paper
  state.
- **C1 for D:** D has one pot with no reserves, so its active equity equals its total
  equity, and C1(b) reduces to C1(a) measured against its own peak. D has no halts, so
  the hard-halt veto cannot trigger.

### E: volume-confirmed exit (deferred)
Not part of v1. Extending the 6-hour exit timer increases loss exposure, so it needs a
separate risk review first (Codex, PR #15).

### F: order-flow entry block
F blocks new buys only. It is **not** a V0 pause: it never sets `draining`, never
market-sells inventory and never clears or delays any other pause, halt or exit.
- **Signal:** `share` = taker-buy **base** volume ÷ base volume over the last 15
  **completed, consecutive** one-minute bars.
  - `share` is **unavailable** if any of those 15 bars is missing, which is not the
    same as a zero-volume bar, or if the aggregate base volume over the 15 bars is
    zero.
  - A single zero-volume minute inside an otherwise complete window is valid input.
- **Block:** F's own flag `flow_block` turns on when `share < 0.40` (strict) or `share`
  is unavailable.
  - While it is on, resting buys are cancelled, and no new grid or reentry buy is placed.
  - A buy cancelled after a partial fill leaves its filled quantity unpaired. That
    quantity gets a resting grid sell at the cancelled buy's target, exactly as a
    complete fill would, so it pays the maker fee and needs no drain.
  - **Fragments below the minimum notional** at their target cannot be placed as a
    sell. They are **accumulated per target price**. When the accumulated quantity at a
    target reaches the minimum notional, one resting sell is placed for it.
  - Until then, the fragments are held unreserved and marked in equity like any other
    inventory. They remain subject to V0's range exit, liquidation and, in variants
    combining A, `trend_exit`.
  - Anything still below the minimum at the end of a run is reported as dust, as V0
    already does.
  - When the originating grid ends (range exit or re-centre), its buckets are handled
    like other unreserved inventory: they go through that exit, and only a remainder
    below the minimum becomes dust.
- **Unblock:** `flow_block` turns off when `share ≥ 0.45` (inclusive). Turning it off
  only lifts F's own restriction. Any other active pause, halt, drain or eligibility
  veto stays in force.
- **Startup:** `flow_block` starts on, so it fails closed. A start inside the
  0.40–0.45 band stays blocked until `share ≥ 0.45`.
- **Unaffected:** resting sells, range exits, drain and every risk exit continue as in
  V0.
- **Request budget:** cancellations count against it. The per-day request maximum is
  reported for F specifically.
- **Required tests:**
  - cancellation counts;
  - a partial fill then a block (the resting sell for the unpaired quantity);
  - a below-minimum fragment, then accumulation to the minimum, then a single sell;
  - threshold equalities at exactly 0.40 and 0.45;
  - a missing minute versus a zero-volume minute;
  - an F unblock while a V0 eligibility pause is active (the pause must remain);
  - overlapping F and range-exit states.

## 4. Matrix

| Axis | Values |
| --- | --- |
| Variants | V0, A, B, C, D, F |
| Fees | **Primary:** Revolut X, maker 0 / taker 0.0009. **Sensitivity** (reported, not used for acceptance): 0.001 / 0.001. |
| Windows and pairs | `verify-2024h1` (ADA, BTC) and `practice-2022` (BTC, XRP, SOL), each extended with daily warm-up (P3). |
| Intrabar paths | `high_first` and `low_first`, both always reported. No path is chosen after seeing results. |
| Capital | 100 quote units per run, independent per pair. |

- **Unchanged inputs:** slippage 0.05%, assumed spread 0.05% and participation 10%.
- **Reporting:** every attempted run is reported, including invalid runs, halts and zero
  trades.

## 5. Validity and the comparison mask

**Comparison mask, fixed before any variant runs.** For each pair-window, the following
variant-independent checks are run first:
- the manifest and checksums;
- the hourly/minute and daily/hourly cross-checks;
- warm-up sufficiency;
- the availability of sourced exchange filters (P4).

A pair-window that fails any of them is **excluded for every variant alike** and listed
with the reason. Exclusion is per pair-window: a pair can be excluded from one window
and kept in another. The mask is written to the results before scoring and cannot
change afterwards. Every current `practice-2022` SOL pair-window fails the filter check
unless P4 sources historical filters
([fee-levels-2026-09.md](backtests/fee-levels-2026-09.md), tick-size mismatch).

**Minimum evidence:** each development window must keep at least 2 included pairs.
Otherwise the outcome is "insufficient evidence", not a winner.

**Run validity:** a run in the mask is valid when:
- there are zero accounting problems, including the P6 reconciliation;
- there are zero rejected frames.

An invalid run **fails its variant** (C4). A failure in one variant never removes the
pair for the other variants.

## 6. Acceptance and selection (owner decisions, 2026-09-24)

Acceptance is judged at the primary fees. A variant passes when **all** of the
following hold across its included runs, that is every pair, window and path:

| # | Criterion | Owner choice |
| --- | --- | --- |
| C1 | **Worst drop,** on two bases in every run. **(a)** The max drawdown of **total equity**: active equity (§3 B, the engine's `Account.equity`, which marks inventory at bid × (1 − slippage) × (1 − taker)) plus the pending reserve plus the secured reserve, is ≤ **10%** of its running peak. **(b) Confirmed by the owner on 2026-09-24, as a deliberate tightening of the earlier total-equity-only wording:** the drawdown of **active equity** against the runtime's **reserve-adjusted risk high-water mark** (`risk_high`, which `_settle` scales down after reserve allocations, so a reserve transfer is not a trading drawdown) is ≤ **10%**. It is sampled at every pre-fill and post-fill risk evaluation the engine performs. The engine updates `risk_high` from the same `Account.equity` valuation, so C1(b) compares like with like. In addition, **any hard-drawdown halt in a run fails C1(b)** outright, whatever the samples show. Both drawdowns are measured from peaks, so after growth 10% can exceed 10 quote units. | 10%; €10 is only the illustration at the starting €100 |
| C2 | **Makes money:** the mean return across included runs is > 0 after fees, and so is the median. All runs have equal weight, and the median of an even count is the mean of the two middle values. | Beat cash |
| C3 | **Safer than holding:** in every included run, max total-equity drawdown < that run's buy-and-hold max drawdown (common sampling, P2). This is strict, as recorded; it is not relaxed to the median because it is hard to pass. A run where buy-and-hold has zero drawdown fails C3 and is reported, not exempted. | Less drop than holding |
| C4 | **Integrity:** every included run is valid (§5). | — |
| C5 | **Activity:** no minimum. Completed cycles (P7) per week are reported for information. | No minimum |

**Selection (deterministic):**
1. The **eligible set** is the passing variants among V0, A, B, C and F. D is excluded
   before ranking.
2. Let `M` be the highest mean return in the eligible set, in percentage points rounded
   to 6 decimals. The **tie set** is every eligible variant with mean return ≥ `M − 0.25`
   (inclusive).
3. Within the tie set, pick the lowest mean total-equity max drawdown, rounded the same
   way.
4. If still tied, pick the first in the fixed simplicity order V0, A, B, F, C.
5. D **cannot be selected.** C1–C5 are still computed and reported for D, for
   information only, next to the winner.

**No winner:** if no variant passes, v1 ends with "no winner". Nothing runs on the
reserved window, and the report says so.

## 7. Reserved evaluation (run exactly once)

**What "untouched" means here:** no replay has been run on this window. It is **not** an
unseen regime:
- While researching the Bitcoin cycle with the owner (2026-09-24), Claude read reports
  of the peak on 2025-10-06, the roughly 50% decline and the June 2026 low. That
  knowledge motivated variant A.
- The window is therefore a prospectively reserved replay window, and its result is
  weaker evidence than a truly unseen period.
- Failures on it are recorded as they are. No variant is retuned and rerun on the same
  window, and a failed attempt is never replaced or reused as a fresh evaluation.

**Prior exposure record (as of this draft):**
- **Seen in chat:** Claude read public reports of the 2025–26 BTC regime (the peak on
  2025-10-06, the roughly 50% decline and the June 2026 low).
- **Not done:** no 2025–26 archive data has been downloaded, and no 2025–26 replay,
  feature or statistic has been computed.
- **Outside the window:** the live-stream and Revolut X order-book checks of September
  2026 fall after it.

Any later exposure before the run is added to this record.

**Frozen before access:** the following are frozen and recorded before the window's data
is fetched:
- the code commit, config, spec version and dataset spec;
- the universe (the pairs listed below);
- the comparison-mask rules (§5);
- the scoring (§6);
- the execution conventions.

Fetching and verifying the data are part of the run and happen only after the owner's
go. The manifest hashes are recorded at that moment and are then fixed.

**Technical reruns:**
- **Allowed** only when a run is invalid because of a harness defect that does not
  change strategy, parameters or data. The fix must be reviewed by Codex, and both the
  failed and the rerun artifacts are kept.
- **Not allowed** for data invalidity: that pair-window is excluded under §5.
- **Not allowed** for a strategy result the owner dislikes.

**Holdout mask:** the §5 rules apply. If fewer than 3 of the 5 pairs are included, the
outcome is "insufficient evidence", not a pass. There is no silent averaging over the
surviving pairs, and every exclusion is listed.

**Owner gate:** this run starts only after the owner explicitly says go in the
conversation. That go is recorded in the report with its date. Finishing §2–§6 does not
start it automatically. Before asking, Claude reports:
- the practice-matrix results;
- the winner, or that there is none;
- the exact code commit, config, dataset specs and manifests to be used, all frozen.

- **Window:** 2025-01 to 2026-08. This is the latest complete month before this spec. It
  includes the October 2025 peak and the decline that followed.
- **Pairs:** BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT and ADAUSDT as Binance proxies for the
  Revolut X EUR pairs, fixed now. The daily warm-up starts in 2024-04.
  - The set is wider than the development windows on purpose: it is the five
    EUR-quoted coins the owner is likely to trade on Revolut X.
  - ETH is absent from the development windows only because of archive defects in
    `practice-2022` (see that spec).
- **Runs:** the winner, V0 and D, at the primary fees, on both paths.
- **Data problems:** a pair that fails integrity is reported as invalid and is **not**
  replaced by another pair.
- **Judging:** the result is judged against C1–C4 on the included runs and reported
  whether it passes or not.
  A pass does not authorise live trading; it only justifies the next step, a proposal
  for paper trading on live Revolut X prices, which needs its own review.

## 8. Scope of the evidence

- The simulation replays **Binance USDT** market data with **Revolut X fees**. It is a
  cost-sensitivity experiment, not a backtest of Revolut X EUR execution: Revolut X
  prices, spreads, queue positions, depth and post-only behaviour are not simulated.
- A pass justifies at most a proposal for paper trading against live Revolut X prices.

## 9. Sources

Venue terms and research claims that motivated this spec. They were checked on
2026-09-24 and may change.
- Revolut X fees: <https://www.revolut.com/legal/crypto-exchange-fees/>
- Revolut X API, including post-only orders and rate limits:
  <https://developer.revolut.com/docs/x-api/revolut-x-crypto-exchange-rest-api>,
  <https://developer.revolut.com/docs/x-api/place-order>
- Inventory-aware market making (Avellaneda–Stoikov):
  <https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/>
- Short-horizon crypto mean reversion (about 1.3 bp gross per trade):
  <https://arxiv.org/abs/2608.21888>
- Trend following in crypto: <https://arxiv.org/pdf/2009.12155>,
  <https://research.grayscale.com/reports/the-trend-is-your-friend-managing-bitcoins-volatility-with-momentum-signals>
- Bitcoin four-year cycle, 2025 peak and 2026 status:
  <https://www.fidelity.com/learning-center/trading-investing/four-year-bitcoin-and-crypto-cycles>,
  <https://coinmarketcap.com/academy/article/%20bitcoin-4-year-cycle-october-2026>

## 10. Not decided in v1

These stay open; each needs its own specification:
- the policy after a large loss (cool-off or permanent stop);
- quote skewing;
- variant E;
- a Revolut X price feed;
- any live-trading work;
- a README change to the "Binance spot only" operating rule. Revolut X is named here
  only as the fee scenario and as the venue for a possible later paper-trading
  proposal, which needs its own review.
