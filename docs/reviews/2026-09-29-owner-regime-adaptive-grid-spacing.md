# Owner direction: regime-adaptive grid spacing (v2 research question)

Index: 2026-09-29: The owner's strategic direction — grid spacing should adapt to the
detected market regime. Recorded from a conversation with Bob (owner's desktop session).
Not a spec change; a research question and design direction for v2.

- **Recorded by:** Bob (owner's desktop IBM Bob session), 2026-09-29.
- **Owner's words (paraphrased from conversation):**
  - "Shouldn't it depend on the trend — if we go sideways then a small tight grid is
    better, and if we are not moving sideways then a wide grid is better?"
  - "Instead of trading and gaining 6% in one go, perhaps we should evaluate the trend
    then put orders for 1%, then again 1% etc — trade small profits but a lot of them."
- **Status:** Owner direction. Not yet a spec change, not a registered trial. Claude
  and Codex should treat this as a confirmed research question for v2 planning.

## What the owner is describing

The bot currently builds a grid with fixed spacing for the life of that grid, sized by
ATR (roughly 5–10% per level on a volatile coin). The owner's direction is that spacing
should be a function of the current market regime:

| Regime | Preferred grid | Reasoning |
| --- | --- | --- |
| **RANGE** (sideways, low ADX) | Tight grid (~1–2% spacing) | Price oscillates frequently through small moves; many fast cycles beat fewer large ones |
| **BULL / BEAR** (trending) | Wide grid or pause | A tight grid is blown through in a single directional move; wide spacing or no new buys survives the trend |
| **TRANSITION** | Hold current grid | Unclear signal; do not rebuild |

## What already exists in the codebase

- `RegimeClassifier` (`src/crypto_grid_bot/strategy/regime.py`) already detects RANGE,
  BULL, BEAR and TRANSITION using a weighted score across trend, breadth, momentum,
  volatility health and liquidity health, with ADX as the directional separator.
- `GridBuilder` (`src/crypto_grid_bot/strategy/grid.py`) already accepts
  `range_atr_multiple` and level count as inputs and enforces a minimum spacing floor
  of `round_trip_cost_pct × minimum_cost_multiple` (currently 3.0×, floor ~0.84%).
- The regime classifier is currently used as a binary gate: open a grid only in RANGE;
  once open, spacing is fixed.

## What is missing

The current design does not feed regime back into grid sizing after opening. The missing
piece is:

1. **Regime → spacing mapping:** a rule (or config parameters) that maps each regime to
   a target `range_atr_multiple` or level count — tighter in RANGE, wider in BULL/BEAR.
2. **Rebuild trigger:** when regime changes, rebuild the grid with new spacing rather
   than keeping the original.
3. **Safety constraint:** any new spacing must still clear the fee floor (≥ 0.84% with
   current defaults). Spacing below fees guarantees a loss per cycle.

## Why this matters

The downtrend research (PR #137, `docs/reviews/2026-09-28-claude-v2-downtrend-research.md`)
confirms that the oscillation inside downtrends is large and real — 1,960% of travel
across 801 Down days, 145 rallies of 3% or more. Tighter grids in a recognised sideways
regime would harvest that oscillation more efficiently. The V0 versus variant A comparison
already in the spec answers part of this question (does a trend filter let the grid run
more safely); regime-adaptive spacing is the natural next step.

## Open questions for v2

1. What spacing targets are right for each regime? This needs measurement on historical
   data, not assumption.
2. How quickly should the grid rebuild on a regime change? Immediate rebuild has
   transaction cost (cancel orders, re-place); delayed rebuild keeps the wrong spacing
   for longer.
3. Does adaptive spacing interact with the drawdown recovery logic (amendment 1)?
   A grid rebuild resets the order ladder; the recovery `measure_high` must not be
   affected.

## Owner's decisions still needed

- [ ] Whether to schedule this as a formal v2 research task (with a Bob task file and
  measured backtest comparison) or keep it as an open direction until v1 is complete.
- [ ] What regime-to-spacing mapping to test first (e.g. RANGE → 1× ATR, BULL/BEAR →
  3× ATR, or a different parameterisation).

— IBM Bob (owner's desktop session)
