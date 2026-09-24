# Owner decision: Variant H — Bitcoin cycle context layer

- **Date:** 2025-09-25
- **Author:** Owner (mgalic01), recorded by IBM Bob (observer/consultant)
- **Recipient:** Codex and Claude
- **Context:** The Bitcoin 4-year halving cycle is a legitimate structural feature
  of Bitcoin — each halving mathematically cuts new supply in half, creating
  documented upward price pressure. All three complete cycles (2012, 2016, 2020)
  and the current partial cycle (2024) confirm the pattern. This variant encodes
  cycle awareness using price-based and on-chain measurements, not calendar
  predictions. Calendar dates are NOT hard-coded; the cycle phase is derived
  from price position and the known halving block number.

## What Variant H does

Three cycle-aware rules, all applied simultaneously:

### Rule H1 — Halving phase tracker
Track months elapsed since the last confirmed halving block:
- **2024 halving:** block 840,000, approximately April 2024 (exact timestamp
  from on-chain data; not a calendar guess)
- **Phase mapping** (from historical pattern across 3 complete cycles):
  - Month 0–6 post-halving: accumulation phase — normal grid activity allowed
  - Month 6–18 post-halving: expansion phase — normal grid activity allowed
  - Month 18–30 post-halving: late-cycle / peak risk window — apply H2 overextension guard
  - Month 30–48 post-halving: bear / accumulation — apply H3 deep discount signal
- Phase is **context only** — it adjusts the sensitivity of H2 and H3, it is
  not a standalone entry or exit trigger

### Rule H2 — Overextension guard (late-cycle)
If price is more than 60% above its 200-day SMA **and** the halving phase
tracker is in the peak risk window (month 18–30):
- No new grids open
- Existing grids tighten their range exit: outside-range timer reduced from
  6 hours to 2 hours
- This captures the historical pattern of parabolic blow-offs ending abruptly

The 60% threshold is fixed here and must not be changed after the first run.

### Rule H3 — Deep discount signal (bear phase)
If price is more than 50% below its previous cycle ATH **and** the halving
phase tracker is in the bear/accumulation window (month 30–48):
- The opportunity score threshold is reduced by 0.10 (e.g. from 0.70 to 0.60)
  to allow more grid activity in historically favourable accumulation conditions
- This must still pass all other regime and risk checks — it relaxes one gate
  slightly, it does not override risk controls

The 50% threshold and 0.10 score relaxation are fixed here and must not be
changed after the first run.

## Why price-based, not calendar-based

Historical cycle peaks occurred at:
- 2013: ~12 months post-halving
- 2017: ~18 months post-halving
- 2021: ~18 months post-halving

The timing varies by up to 6 months. Hard-coding "peak = October 2025" would be
wrong if the peak arrives in April 2025 or March 2026. Measuring from price
position (H2: overextension above SMA200) catches the condition regardless of
exact calendar timing. The halving phase tracker provides context that sharpens
H2 and H3 — it does not replace them.

## What is NOT done

- No calendar dates are hard-coded anywhere
- The phase tracker does not override risk controls (daily loss limit, drawdown
  circuit breakers, hard halt policy)
- The cycle model does not predict future price — it adjusts gate sensitivity
  based on historically observed phase characteristics
- The n=3.5 sample size limitation is acknowledged: H2 and H3 thresholds are
  starting hypotheses, not validated optimal values

## Data sources

- **Halving block timestamp:** Available from any Bitcoin block explorer API
  (e.g. blockchain.info public API, no key required) or from a committed
  constant in the dataset spec (the block timestamp is a historical fact,
  not a prediction)
- **Previous cycle ATH:** Derived from the same Binance kline archive already
  in use — the maximum closing price in the prior cycle window
- **Current price vs SMA200:** Already computed by the existing strategy engine

## Pre-registration rules

- Variant H runs with the same windows, fee levels and comparison baselines as
  Variants A–F and G
- All three thresholds (60% overextension, 50% ATH discount, 0.10 score
  relaxation) are fixed here and must not be changed after the first run
- Variant H is tested both standalone (V0 + H) and combined with Variant C
  (trend filter + inventory cap), which is the most promising combination
  from the approved variants
- Compared to V0, cash and buy-and-hold with no tuning after the first run

## What to measure

- How often does H2 block a grid that would otherwise open?
- How often does H3 allow a grid that would otherwise be blocked?
- In the `practice-2022` bear window, does H3 increase activity in the
  post-crash accumulation period (Oct 2022 – Jan 2023)?
- In the `verify-2024h1` bull window, does H2 reduce exposure during the
  late-cycle months (May–Jun 2024)?

## Failure modes to watch

- **Phase mismatch:** If the current cycle deviates significantly from the
  3-cycle historical pattern (e.g. cycle compresses to 2 years or extends to
  6), the phase tracker will be wrong. Monitor and report phase vs actual
  price behaviour.
- **H3 relaxation in a continuing bear:** H3 allows slightly more activity
  near historical accumulation zones. If the bear extends beyond 48 months
  (unprecedented but possible), H3 could increase exposure in a still-falling
  market. The existing risk controls (drawdown limits) remain the last line
  of defence.

## Next action

Codex and Claude: commit the 2024 halving block timestamp as a dataset
constant. Implement H1 (phase tracker), H2 (overextension guard) and H3
(deep discount signal) behind a single config flag (default off). Run the
variant matrix after Variants A–F and G are assessed. Report phase assignment
for every evaluated bar in results.json.
