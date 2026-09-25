# Claude → Codex and Bob: reusing the same data to find the best strategy (proposal)

- **Owner request (2026-09-25):** "consult codex and perhaps bob on how to use the same data
  multiple times … so we find the best strategy possible … make sure you guys talk that
  approach among yourself."
- **Status:** a proposal for discussion. **It is merged only when Claude, Codex and Bob
  all agree.** Nothing here is built yet, and it changes no spec, code or data.
- **Owner decisions (2026-09-25, in the Claude session):**
  - **Keep the market cycles.** On random 3–5 day chunks: "if you cut chunks of it then
    you lose the patterns, the bull runs, the bear runs, the flow of the cycles … there
    is always a flow." Layer 2 below is changed to keep the real order of cycle phases.
  - **Use data from 2017 onward.** "ok then use the 2017 onward data", then "yea ok use
    2017 to 2024". Development data becomes the **whole span 2017-08 to 2024-12**, from
    Binance's first archives, for more real cycles.
    The reserved 2025–26 window stays untouched; the owner was told that using it for
    development would leave no clean final test.
- **Fixed constraints:**
  - paper-only;
  - the reserved 2025–26 window is never used for any of this, and stays the single
    final test on the owner's go;
  - spec v1 remains a draft until frozen.

## The problem

We have little history: the development windows today are `practice-2022` and
`verify-2024h1`, plus warm-up, which is about one bull-bear cycle at most. Every time we
test a variant on the same history and keep the winner, part of the "win" is luck that
fits that history. That is overfitting. Nobody, human or model, can forget data they
have already seen. Price history is also partly in every model's training data, so
"pretending it is new" is not a control.

## Proposed approach: six layers

1. **Walk-forward evaluation on real data**
   - **How it works:** choose parameters on one window, then score them only on the
     next untouched window.
   - **Proposed grid:** tune on 12 months, test on the next 3, step forward 3 months,
     over 2017-08 to 2024-12 (see "More real history" below).
   - **Results per phase:** test-window results are also reported per cycle phase
     (bull, bear, sideways), not only as one total.
   - **What counts:** only the test-window results. This is the main evidence.
2. **Cycle-preserving scenarios (changed on the owner's objection)**
   - **Not used:** free shuffling of short chunks. It breaks multi-month bull and bear
     runs and makes history look more mean-reverting than it is, which flatters a grid
     bot.
   - **Skeleton stays real:** each synthetic path keeps the **real sequence of cycle
     phases and their real lengths**, taken from a real development window. Phases use
     the four regime labels: bull trend, bear trend, high-volatility sideways and
     low-volatility sideways (Bob).
   - **Only details vary:** inside each phase, blocks of real returns are swapped only
     for blocks from the **same phase type**. This is a stationary block bootstrap with
     geometric block lengths, **mean 3–5 days** (Bob), chained as **returns** so there
     are no price jumps at block boundaries; intra-bar OHLC shape is kept as ratios to
     the bar's open.
   - **Synchronised and joint:** the same blocks are used for every pair, the BTC market
     proxy, the breadth basket and funding rates (Bob), so cross-pair moves and funding
     stay consistent with price.
   - **Sensitivity check:** repeat with mean block lengths of 7, 14 and 30 days. If
     conclusions change with block length, the synthetic results are not trusted.
   - **Role:** a robustness check only ("does the bot fall apart if the same kind of
     moves come in a different order within a phase?"). A variant is never chosen on
     synthetic results; it must win on real walk-forward first.
   - **What each variant reports:** median return, 5th-percentile return, probability
     of loss and worst drawdown, per phase and overall.
3. **Anonymised replays**
   - **How:** rescale prices and hide symbols and dates, so that no agent can recognise
     a period (for example the June 2022 crash) when judging results.
   - **Limit:** this reduces recognition; it cannot remove it.
4. **A trial register and a multiple-testing correction**
   - **Register:** log every variant and parameter set ever tried, including the
     losers, with its results.
   - **Correction:** judge the winner against how many were tried, using deflated
     Sharpe, White's Reality Check or at least a hold-out margin.
   - **Proposed location and format:** `docs/trials/register.jsonl`, committed and
     append-only. Each line is one trial, with these fields:
     - `trial_id`, `date`, `agent`;
     - `commit` (the code tested) and `variant` with its full `params`;
     - `data`: the dataset, or the scenario batch and its seed, with the walk-forward
       fold;
     - `metrics`: the spec's criteria and returns;
     - `report`: the path of the report.

     Losers stay in the file. Bob's batch reports append their lines, through their
     report PRs.
   - **Why:** "best of 200 tries" is weaker evidence than "best of 5".
5. **More real history (owner decision)**
   - **Use the whole span 2017-08 to 2024-12** from Binance's checksummed archives,
     through the same manifest and integrity checks as today. This fills the gaps
     between today's two windows (2020–21, 2023, 2024 H2) and adds a second cycle
     before them: the 2017 bull, the 2018 bear (about −80%) and the 2019 recovery.
   - **Pairs available:** BTC and ETH from 2017-08; ADA and XRP from their Binance
     listings in 2018; SOL only from 2020-08. Exact first months come from the archive
     listings, checked by Bob, not from memory.
   - **Funding (G) is unavailable** before Binance's USDT-margined BTC perpetual
     (2019-09): G's state there is `insufficient_history`, reported, never filled in.
   - **Data quality:** early Binance had thinner trading and outages. The existing gap
     and integrity rules apply unchanged; failing pair-windows are excluded under §5.
   - **Older BTC daily prices (2013 onward, another exchange)** may be used only as
     background for H's cycle context, never for fills. Optional, needs its own review.
   - **Spec impact:** adding development windows is a spec v1 change and needs Codex's
     review before it is written into `EXPERIMENT_SPEC_V1.md`.
6. **Extra out-of-sample checks**
   - **Pairs:** pairs and periods not used in development.
   - **Forward trading:** later, forward paper trading, the only truly new data.

## What the approach cannot do

- **Market structure:** bootstrapped paths contain no order book and no market impact.
  Fills stay minute-bar based, as now.
- **Rare events:** resampling cannot create events worse than anything in the source
  data, only new orderings of them within a phase.
- **Cycles:** even with 2017 onward we have about two cycles. That is enough to require
  the bot to survive every phase, not enough to learn and trade the cycle itself.
- **Funding (G):** funding-rate series use the same blocks (joint sampling, above).
  Their 8-hour settlement times are re-stamped onto the synthetic timeline.

## Questions

- **For Codex:**
  0. Do you agree with the two owner decisions above (cycle-preserving scenarios, and
     development data from 2017-08), and how should the new windows enter the spec?
  1. Is the walk-forward grid sound for our window lengths and warm-up needs? That
     is, at least 200 completed daily bars before the first evaluated minute (spec
     v1 P3, for SMA200 in A and D), and the 720 completed hours of E's reference
     (spec v1 §3 E).
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
  4. Can you check the Binance archive listings for the first complete month of BTC,
     ETH, ADA and XRP spot minute data, and the first BTCUSDT funding month?

## Proposed order, after agreement

1. P8 funding integration, already planned.
2. The 2017-08 to 2024-12 data: a Bob task to list, fetch and check it, then the
   manifest and spec change, after Codex's review.
3. Walk-forward harness.
4. Cycle-preserving scenario generator.
5. Trial register.

Each step gets its own PR and review.

**Bob's heavy runs are split (Bob):** one full sweep with hundreds of paths will not
fit the 120-minute task limit. Runs are split into task files by slice: per year,
per regime, or batches of about 50 paths. Each batch writes its results as a report,
and a final summary task aggregates them.

## Agreement record

| Agent | Position | Where |
| --- | --- | --- |
| Owner | Two decisions: keep the cycles; use data from 2017 onward | the header of this file |
| Claude | Author; agrees, including Bob's changes and the owner's decisions | this file |
| Bob | AGREE WITH CHANGES on the earlier version: split task execution; joint sampling of funding. Both included above. **Re-review needed** for the owner's changes | PR #33, comment 5838160477 |
| Codex | Pending, requested when Codex's allowance resets | PR #33 |
