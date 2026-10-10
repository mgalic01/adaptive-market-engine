# V3 order planning implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans; implement test-first in this isolated worktree.

**Goal:** Translate frozen V3 target weights into valid market-order intents.
**Architecture:** Pure order plans from one symbol's target, held quantity, fill-hour equity/open and pinned filters. Account fills and event sequencing remain separate.
**Tech Stack:** Python Decimal and pytest, no dependencies.
**Spec:** `docs/EXPERIMENT_SPEC_V3.md` section5 steps4–5.

## Global constraints

- Decimal60 ROUND_HALF_EVEN; quantities round toward zero to market step.
- Band is strictly greater than0.01, or differing target/held signs; zero target closes.
- Open/increase checks minimum quantity and unslipped notional.
- Reductions ignore minimum notional, increase to minimum quantity or full position, and close residual dust.
- Flip closes first, then separately tests the new opening; refusal leaves flat.
- Above maximum, split into ceil(quantity/maximum) orders, distribute remaining steps to earliest chunks. Invalid splits fail explicitly.
- No market access, order submission, tuning or frozen-spec changes.

## Review focus

Strict band equality; tiny opposite-sign targets; negative quantity rounding; minimum-notional flip refusal; maximum splitting with awkward step/minimum combinations. Cover each in tests.

## Task1: Pure order planner

Create `src/crypto_grid_bot/trend/orders.py` and `tests/test_trend_orders.py`.
Consumes `OrderFilters` and Decimal target_weight, held_quantity, equity, open_price.
Produces `plan_rebalance(...) -> OrderPlan`: current_weight, rounded target_quantity, ordered signed `OrderIntent(quantity, reduce_only)` records, refusal reasons and reduction adjustment flags. No timestamps: the event runner supplies fill-hour inputs and ordering.

- [ ] Write tests: exactband .01 holds, .0101 trades, target0 closes, signflip belowband; floor positive/negative target; refused openings; dust reduction; valid split quantities and invalid split.
- [ ] Observe missing API failures.
- [ ] Implement fixed rules with validated finite inputs, positive equity/open and coherent filters; preserve full reduction even when held dust is below minimum.
- [ ] Verify tests, static checks and hand-computed examples; commit.
- [ ] Independent full-branch review, then publish with Bob exact-head review and full CI.

## Limits

The account must execute reductions before increases across symbols, use pre-fill-hour equity for quantity sizing and record refused/adjusted orders. This pure planner does not implement wallet/funding/liquidation, masked-hour deferral, WFO or live routing. Those remain required later.
