# Owner decision: tick-size fix method for historical replay

- **Date:** 2025-09-25
- **Author:** Owner (mgalic01), recorded by IBM Bob (observer/consultant)
- **Recipient:** Codex and Claude
- **Context:** The `practice-2022` SOL runs are currently invalid because today's SOL
  tick size (0.01), applied to 2022 prices of $10–14 and rounded outward on both sides,
  inflates the simulated spread above the 0.15% eligibility limit. 82,792 frames were
  rejected and all SOL runs were correctly marked invalid. This decision resolves
  harness problem 4.1 from
  [`2026-09-24-claude-fees-and-strategy-plan.md`](2026-09-24-claude-fees-and-strategy-plan.md).

## Decision

Use **both options, in priority order**:

1. **Primary (Option A): historical filters per month.** Where Binance's API or
   archives provide the tick size, quantity step and minimum notional that were in
   effect at the time, use those historically correct values during replay. This fixes
   the root cause and correctly represents what was actually tradeable.

2. **Fallback (Option B): round the assumed spread to at least one tick in total.**
   Where historical filter data is not available for a given pair and month, round the
   total assumed spread to at least one tick rather than rounding both the bid and ask
   outward by a full tick each. Document clearly in the manifest and results which
   method was applied to each run.

## Rationale

Option A is the right long-term answer — backtests should reflect what was actually
tradeable at the time, not today's exchange rules applied to historical prices. Option B
is a practical fallback for gaps in historical data availability. Applying both, with
clear per-run documentation, is more accurate than either alone.

## What this unlocks

Once implemented, the `practice-2022` SOL runs should become valid, giving the
variant matrix a bear-market result for a third pair (SOL, June 2022 – January 2023,
including the June crash and the FTX collapse period).

## What remains open

1. **Archive volume drift tolerance** — next decision.
2. **Acceptance criteria for the untouched 2025–26 window** — next decision.

## Next action

Codex and Claude: implement the historical-filter fetch (Option A) with Option B as
a documented fallback. Record which method was applied in the dataset manifest and
in `results.json`. Re-run the `practice-2022` SOL replays after the fix and confirm
they are no longer marked invalid before proceeding to the variant matrix.
