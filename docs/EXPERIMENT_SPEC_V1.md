# Experiment specification v1 (DRAFT for review, not yet frozen)

**Status:** draft by Claude. It becomes frozen only when Codex has reviewed it and the
owner has confirmed the acceptance criteria in §6. After that, a change requires a new
version (v2), and results under v1 stay reported. **No strategy code exists for these
variants yet.** This document fixes what will be built and how it will be judged,
*before* any variant is run.

The scope is paper trading and historical replay only. Nothing here authorises live
trading, API keys or withdrawals. The default risk limits (3% daily pause, 8% soft and
12% hard drawdown, latched halt), the 50/50 profit vault and the paper-only boundary
are unchanged by every variant.

## 1. Question

Starting from `price-only-v1` (V0), do any of the pre-registered mechanisms reduce
forced-exit losses enough to make money after Revolut X fees, with a smaller worst drop
than simply holding? The diagnostic
[fee-levels-2026-09.md](backtests/fee-levels-2026-09.md) motivates the question: resting
grid sells realised gains, and forced marketable exits realised as much or more in
losses.

## 2. Prerequisites (implemented and reviewed before any variant run)

These are measurement changes only. None changes a decision made by V0.

| # | Change | Why |
| --- | --- | --- |
| P1 | **Record the exit reason** on every `exit/` fill: `range_exit`, `drain`, `liquidation` (halt or emergency) and, for variant A, `trend_exit`. Report the realised P&L per reason. | Codex (PR #14): losses cannot be attributed to range exits without it. |
| P2 | **Common drawdown sampling:** strategy total equity, strategy active equity (C1b) and buy-and-hold equity are all sampled on the same schedule (every quote of every bar). | Criterion C3 compares the two drawdowns; they must be measured the same way. |
| P3 | **Daily history:** dataset specs gain `daily_warmup_start`. Binance `1d` archives are fetched from that month, checksummed and cross-checked against the aggregated `1h` archive over the overlap. | Variants A and D need at least 200 completed daily bars before the evaluation starts. |
| P4 | **Historical exchange filters for SOL:** use dated, sourced point-in-time tick and step sizes if available. If they cannot be sourced, SOL runs stay invalid for every variant (§5). No synthetic spread model in the primary comparison. | Codex §4.1 answer on PR #15. |
| P5 | Carried nits: `--maker-fee`/`--taker-fee` use `is not None`, so an empty value is rejected; `replay()` asserts the order book is empty before wrapping it for request counting. | Automated reviews on PR #14. |
| P6 | **P&L reconciliation:** realised P&L by sell type, plus unrealised P&L of the remaining inventory at the final mark, must equal the final total equity minus the initial capital. | Codex (PR #15): attribution must reconcile with the account. |

## 3. Variants

Every variant is V0 plus exactly the mechanism described. They are selected by config
flags that default to off, so V0 and existing paper accounts are unaffected. Timing rules
common to all:
- Signals use **completed** bars only.
- A daily signal computed from the UTC day ending at 00:00 takes effect at the **first
  replay observation at or after 00:00:00 UTC** of the next day, never within the bar
  that produced it.
- For every grid variant (V0, A, B, C, F), emergency, hard-drawdown and daily-loss
  controls always act first. No variant can delay or override them. D is the one
  exception: it is a benchmark without these controls (§3 D).

### V0: baseline (`price-only-v1`)
- **Code:** the commit that merges the prerequisites; it is recorded in every
  `results.json`.
- **Unchanged:** default config, fills, costs, data identities and the common mark
  cadence (P2).

### A: trend/cycle switch (daily SMA50 and SMA200)
Inputs are the completed daily close `C`, `SMA50` and `SMA200` of the traded pair.

| State | Condition | Behaviour |
| --- | --- | --- |
The state is updated once per completed daily bar, from the previous state and `C`:

| State | Entered when | Behaviour |
| --- | --- | --- |
| **Up** | From Up: `C > SMA200`. From Recovering: a second consecutive `C > SMA200`. | Grids allowed, as in V0. |
| **Recovering** | From Middle or Down: the first `C > SMA200`. | Same as Middle: no new grid, and an existing grid keeps running. A `trend_exit` already started completes (see below). |
| **Middle** | From any state: `C ≤ SMA200` and `C > SMA50`. | No new grid. An existing grid keeps running: its sells, reentries within the grid and range exit behave as in V0. Reentries are allowed deliberately: they only rebuy levels the grid already sold, inside its existing range, and B's cap bounds the exposure in C. |
| **Down** | From any state: `C ≤ SMA200` and `C ≤ SMA50`. | No new grid. At the effective time, resting buys are cancelled and resting sells are kept for one day (24 h). After that, the remaining inventory is liquidated with a marketable exit (`trend_exit`). |

- **Hysteresis:** Up is reached only through Recovering, so it takes two consecutive
  completed closes above SMA200. Leaving Up takes one close at or below SMA200.
- **Started exits finish:** once Down has begun (buys cancelled, 24-hour sell window
  open), the sequence completes even if a later close moves the state to Recovering or
  Middle. A new grid needs the Up state.
- **Initial state:** Middle, until the first classified daily bar.
- **Priority:** emergency/hard/daily-loss controls, then `trend_exit`, then range exit.
- **Warm-up:** at least 200 completed daily bars before the first evaluated minute.
  Missing daily data at a decision time counts as **Down**, so the variant fails closed.

### B: inventory cap
- **Definitions:**
  - **Active equity** = cash − pending reserve + inventory × mark. The secured reserve is
    already outside cash, so both reserves are excluded.
  - **Mark** = bid × (1 − slippage) × (1 − taker).
  - **Committed exposure** = (inventory + remaining quantity of **every** resting buy) ×
    mark.
- **Cap:** committed exposure including a new buy may not exceed **40% of active
  equity**. Because resting buys are already counted, their later fills can never breach
  the cap. At most, price moves can lift the inventory's value above it.
- **Placement order:** a new grid places its buy levels from the highest price down. It
  stops at the first level that would breach the cap, and the refused levels are
  recorded in the report. Reentry buys pass the same check when they are created.
- **Rounding and fills:**
  - A capped quantity is floored to the lot step. If it is then below the minimum
    notional, the buy is not placed.
  - Partial fills do not change the check: the unfilled remainder is still counted.
  - Sell targets are unchanged, and no reserve is ever spent.
- **Price drift:** if rising prices push committed exposure above 40%, this is allowed.
  There is no forced sale, but no new buy is placed until exposure is below the cap
  again.
- **What it does not do:** it never forces a sale and never delays a sell.
- **Deferred:** quote skewing by inventory (Avellaneda–Stoikov style) is not in v1. It
  would need its own spec.

### C: A + B, a declared interaction
- **Mechanism:** both mechanisms at once, with A's priority rules.
- **Reporting:** C is reported as an interaction. It is not claimed as a single
  mechanism.

### D: trend benchmark (not a grid)
- **Signal:** each traded pair is held when its completed daily close is above its
  SMA50, and cash is held otherwise.
- **Execution:** entries and exits are marketable at the next observation, paying the
  taker fee plus slippage. Capital, marks, warm-up, timing and fees are identical to A.
- **Missing or undefined signal:** cash.
- **Risk controls:** D is **exempt** from the common rule in §3. It has no daily-loss
  pause, soft or hard drawdown halt or emergency exit; it only follows its signal. Its
  return and drawdown are reported as they are, as a pure benchmark.

### E: volume-confirmed exit (deferred)
Not part of v1. Extending the 6-hour exit timer increases loss exposure, so it needs a
separate risk review first (Codex, PR #15).

### F: order-flow pause
- **Signal:** `share` = taker-buy **base** volume ÷ base volume over the last 15
  **completed** one-minute bars.
- **Pause:** if `share < 0.40`, the grid pauses new buys. Resting buys are cancelled, and
  no new grid or reentry buy is placed.
- **Resume:** buys resume after `share ≥ 0.45`, a hysteresis gap between 0.40 and 0.45.
- **Zero or missing volume** in the window counts as `share` unavailable, and buys pause.
  This fails closed.
- **Unaffected:** resting sells, range exits and every risk exit continue as normal.
- **Request budget:** cancellations count against it. The per-day request maximum is
  reported for F specifically.

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

## 5. Validity

A run is valid when all hold:
- the integrity gates pass;
- there are zero accounting problems;
- there are zero rejected frames;
- the warm-up is sufficient.

An invalid run counts as a **failure** for its variant in §6. The one exception is a
pair that is invalid for **every** variant for the same data reason, such as SOL without
sourced filters. That pair is reported and excluded from all variants alike. This is
not hypothetical: every `practice-2022` SOL run is currently invalid
([fee-levels-2026-09.md](backtests/fee-levels-2026-09.md), tick-size mismatch).

## 6. Acceptance and selection (owner decisions, 2026-09-24)

Acceptance is judged at the primary fees. A variant passes when **all** of the
following hold across its included runs, that is every pair, window and path:

| # | Criterion | Owner choice |
| --- | --- | --- |
| C1 | **Worst drop,** on two bases in every run: (a) max drawdown of **total equity** (including both profit reserves) ≤ **10%** of its running peak; (b) max drawdown of **active equity** (excluding the reserves, the basis of the runtime's 8%/12% breakers) ≤ **10%** of its own high-water mark. By (b), a passing run can never have triggered the 12% hard-drawdown halt. Once profit has moved to the reserve, (a) alone would understate losses on the capital still trading. | 10% (€10 on €100) |
| C2 | **Makes money:** the mean return across runs is > 0 after fees, and so is the median. | Beat cash |
| C3 | **Safer than holding:** in every run, max drawdown < that run's buy-and-hold max drawdown (common sampling, P2). | Less drop than holding |
| C4 | **Integrity:** every included run is valid (§5). | — |
| C5 | **Activity:** no minimum. Completed buy→sell cycles per week are reported for information. | No minimum |

**Selection:**
1. Among passing variants, pick the highest **mean return**.
2. If two are within 0.25 percentage points, pick the lower mean max drawdown.
3. If those are also equal, pick the simpler variant, in the order V0, A, B, F, C.
4. D is a benchmark and **cannot be selected**. C1–C5 are still computed and reported for D, for information only. It is reported next to the winner.

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
  window.

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
- **Runs:** the winner, V0 and D, at the primary fees, on both paths.
- **Data problems:** a pair that fails integrity is reported as invalid and is **not**
  replaced by another pair.
- **Judging:** the result is judged against C1–C4 and reported whether it passes or not.
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
- any live-trading work.
