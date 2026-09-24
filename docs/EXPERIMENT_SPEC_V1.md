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
| P2 | **Common drawdown sampling:** strategy and buy-and-hold equity sampled on the same schedule (every quote of every bar). | Criterion C3 compares the two drawdowns; they must be measured the same way. |
| P3 | **Daily history:** dataset specs gain `daily_warmup_start`. Binance `1d` archives are fetched from that month, checksummed and cross-checked against the aggregated `1h` archive over the overlap. | Variants A and D need at least 200 completed daily bars before the evaluation starts. |
| P4 | **Historical exchange filters for SOL:** use dated, sourced point-in-time tick and step sizes if available. If they cannot be sourced, SOL runs stay invalid for every variant (§5). No synthetic spread model in the primary comparison. | Codex §4.1 answer on PR #15. |
| P5 | Carried nits: `--maker-fee`/`--taker-fee` use `is not None`, so an empty value is rejected; `replay()` asserts the order book is empty before wrapping it for request counting. | Automated reviews on PR #14. |

## 3. Variants

Every variant is V0 plus exactly the mechanism described. They are selected by config
flags that default to off, so V0 and existing paper accounts are unaffected. Timing rules
common to all:
- Signals use **completed** bars only.
- A daily signal computed from the UTC day ending at 00:00 takes effect at the **first
  replay observation at or after 00:00:00 UTC** of the next day, never within the bar
  that produced it.
- Emergency, hard-drawdown and daily-loss controls always act first. No variant can
  delay or override them.

### V0: baseline (`price-only-v1`)
- **Code:** the commit that merges the prerequisites; it is recorded in every
  `results.json`.
- **Unchanged:** default config, fills, costs, data identities and the common mark
  cadence (P2).

### A: trend/cycle switch (daily SMA50 and SMA200)
Inputs are the completed daily close `C`, `SMA50` and `SMA200` of the traded pair.

| State | Condition | Behaviour |
| --- | --- | --- |
| **Up** | `C > SMA200` | Grids allowed, as in V0. |
| **Middle** | `C ≤ SMA200` and `C > SMA50` | No new grid. An existing grid keeps running: its sells, reentries within the grid and range exit behave as in V0. |
| **Down** | `C ≤ SMA200` and `C ≤ SMA50` | No new grid. At the effective time: cancel resting buys, keep resting sells for one day, then liquidate the remaining inventory with a marketable exit (`trend_exit`). |

- **Hysteresis:** entering Up from Middle or Down requires **two consecutive** completed
  daily closes above SMA200. Leaving Up needs only one close at or below it.
- **Priority:** emergency/hard/daily-loss controls, then `trend_exit`, then range exit.
- **Warm-up:** at least 200 completed daily bars before the first evaluated minute.
  Missing daily data at a decision time counts as **Down**, so the variant fails closed.

### B: inventory cap
- **Mechanism:** unreserved plus reserved inventory, marked at bid × (1 − slippage) ×
  (1 − taker), may not exceed **40% of active equity**.
- **Enforcement:** a buy (a new grid level or a reentry) is placed only if its full fill
  would keep the account within the cap. Otherwise it is not placed, and a report reason
  records the refusal.
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
- **Risk controls:** none, deliberately, as a pure benchmark. Its drawdown is reported
  as is.

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
sourced filters. That pair is reported and excluded from all variants alike.

## 6. Acceptance and selection (owner decisions, 2026-09-24)

Acceptance is judged at the primary fees. A variant passes when **all** of the
following hold across its included runs, that is every pair, window and path:

| # | Criterion | Owner choice |
| --- | --- | --- |
| C1 | **Worst drop:** no run's max drawdown, measured on total equity including the profit reserves, exceeds **10%** of its running peak. | 10% (€10 on €100) |
| C2 | **Makes money:** the mean return across runs is > 0 after fees, and so is the median. | Beat cash |
| C3 | **Safer than holding:** in every run, max drawdown < that run's buy-and-hold max drawdown (common sampling, P2). | Less drop than holding |
| C4 | **Integrity:** every included run is valid (§5). | — |
| C5 | **Activity:** no minimum. Completed buy→sell cycles per week are reported for information. | No minimum |

**Selection:**
1. Among passing variants, pick the highest **mean return**.
2. If two are within 0.25 percentage points, pick the lower mean max drawdown.
3. If those are also equal, pick the simpler variant, in the order V0, A, B, F, C.
4. D is a benchmark and **cannot be selected**. It is reported next to the winner.

**No winner:** if no variant passes, v1 ends with "no winner". Nothing runs on the
untouched window, and the report says so.

## 7. Untouched evaluation (run exactly once)

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

## 8. Not decided in v1

These stay open; each needs its own specification:
- the policy after a large loss (cool-off or permanent stop);
- quote skewing;
- variant E;
- a Revolut X price feed;
- any live-trading work.
