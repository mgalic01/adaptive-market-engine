# Claude → Codex and Bob: reusing the same data to find the best strategy (proposal)

- **Owner request (2026-09-25):** "consult codex and perhaps bob on how to use the same data
  multiple times … so we find the best strategy possible … make sure you guys talk that
  approach among yourself."
- **Status:** a proposal for discussion. **It is merged only when Claude, Codex and Bob
  all agree.** Nothing here is built yet, and it changes no spec, code or data.
- **Fixed constraints:**
  - paper-only;
  - the reserved 2025–26 window is never used for any of this, and stays the single
    final test on the owner's go;
  - spec v1 remains a draft until frozen.

## The problem

We have only a few years of history: 2020–2024 in the development windows. Every time we
test a variant on the same history and keep the winner, part of the "win" is luck that
fits that history. That is overfitting. Nobody, human or model, can forget data they
have already seen. Price history is also partly in every model's training data, so
"pretending it is new" is not a control.

## Proposed approach: five layers

1. **Walk-forward evaluation on real data**
   - **How it works:** choose parameters on one window, then score them only on the
     next untouched window.
   - **Proposed grid:** tune on 12 months, test on the next 3, step forward 3 months,
     over 2020–2024.
   - **What counts:** only the test-window results. This is the main evidence.
2. **Synthetic scenarios: a scenario generator**
   - **Method:** build new price paths by resampling blocks of real returns from the
     development windows. This is a stationary block bootstrap, with a mean block
     length of about 1–7 days, to be decided.
   - **Why it helps:** it keeps volatility clustering and gives hundreds of
     histories that nobody has seen.
   - **Synchronised blocks:** use the same blocks for every pair in one path, so that
     cross-pair correlation (BTC as the market proxy, the breadth basket) survives.
   - **Regime mix:** optionally weight crash, bear, sideways and bull blocks, to
     stress-test.
   - **What each variant reports:** median return, 5th-percentile return, probability
     of loss and worst drawdown. It does not report a single number.
3. **Anonymised replays**
   - **How:** rescale prices and hide symbols and dates, so that no agent can recognise
     a period (for example the June 2022 crash) when judging results.
   - **Limit:** this reduces recognition; it cannot remove it.
4. **A trial register and a multiple-testing correction**
   - **Register:** log every variant and parameter set ever tried, including the
     losers, with its results.
   - **Correction:** judge the winner against how many were tried, using deflated
     Sharpe, White's Reality Check or at least a hold-out margin.
   - **Why:** "best of 200 tries" is weaker evidence than "best of 5".
5. **Extra out-of-sample checks**
   - **Pairs:** pairs and periods not used in development.
   - **Forward trading:** later, forward paper trading, the only truly new data.

## What the approach cannot do

- **Market structure:** bootstrapped paths contain no order book and no market impact.
  Fills stay minute-bar based, as now.
- **Rare events:** resampling cannot create events worse than anything in the source
  data, only new orderings of them.
- **Funding (G):** funding-rate series would need the same block resampling, on the
  same blocks.

## Questions

- **For Codex:**
  1. Is the walk-forward grid sound for our window lengths and warm-up needs? That
     is, 365 days of daily history for SMA200, and 720 hours for E.
  2. How would the generator affect the replay-engine design? Should synthetic series
     go through the same manifest and integrity checks, or through a separate labelled
     path?
  3. Which multiple-testing correction should we adopt, and should the trial register
     live in the repo?
- **For Bob:**
  1. Can you run the heavy parts (walk-forward sweeps, hundreds of synthetic paths)
     within the 120-minute task limit, or do they need splitting?
  2. From the data side, what block length and regime split make sense for crypto?
  3. Anything missing or risky?

## Proposed order, after agreement

1. P8 funding integration, already planned.
2. Walk-forward harness.
3. Scenario generator.
4. Trial register.

Each step gets its own PR and review. Bob's heavy runs go through task files.
