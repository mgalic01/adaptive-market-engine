# Owner decision: strategy variants A–F approved for pre-registration

- **Date:** 2025-09-25
- **Author:** Owner (mgalic01), recorded by IBM Bob (observer/consultant)
- **Recipient:** Codex and Claude
- **Context:** Following the fee-level diagnostic report
  ([`fee-levels-2026-09.md`](../backtests/fee-levels-2026-09.md)) and Claude's
  strategy plan ([`2026-09-24-claude-fees-and-strategy-plan.md`](2026-09-24-claude-fees-and-strategy-plan.md)),
  the owner reviewed variants A–F and has made the following decisions.

## Owner direction

The owner's stated goal is a bot that **actively trades and tries to profit**,
not one that stays in cash most of the time. The diagnostic confirmed that the
grid mechanism itself realises gains on resting sells; the problem is forced exits
when price trends away. The variants below are intended to address that.

## Variant decisions

| ID | Mechanism | Decision | Notes |
| --- | --- | --- | --- |
| A | Cycle/trend filter (SMA200) | ✅ **Approved** | Highest priority. Directly addresses the "one crash ends the strategy" problem. No new grids below daily SMA200; exit inventory when below both SMA200 and SMA50. |
| B | Inventory cap + level skew | ✅ **Approved** | The 40% inventory cap and half-spacing skew are approved as a starting hypothesis, not a proven optimal number. |
| C | A + B combined | ✅ **Approved** | Run as a separate variant to measure whether A and B compound or interfere. |
| D | Pure trend benchmark | ✅ **Approved** | Keep as an honest comparison baseline. If D beats C, the grid approach needs rethinking before further infrastructure is built. |
| E | Volume-confirmed exit | ✅ **Approved** | Sound logic. The 2× median volume threshold is a starting hypothesis. Watch whether it reduces losses or merely delays them. |
| F | Order-flow pause | ✅ **Approved (lowest priority)** | Most speculative of the six. The 40%/15-bar thresholds are arbitrary. Risk of making an already-inactive strategy even less active. Run it, but do not let it block the others. |

## Pre-registration rules

The owner accepts Claude's proposed pre-registration rules:
- Every variant runs with both Revolut X fees (0% maker / 0.09% taker) and 0.1% flat fees.
- Windows: `verify-2024h1` (bull) and `practice-2022` (bear, after the tick-size fix).
- Each variant is compared to V0, cash and buy-and-hold with no tuning after the first run.
- The single best-supported variant, plus V0, then gets **one** run on the untouched
  2025–26 window.

## What remains open

The following decisions are **not yet made** and will be addressed separately:

1. **Tick-size fix method for SOL** (historical filters vs. single-tick rounding fallback) — next decision.
2. **Archive volume drift tolerance** — next decision.
3. **Acceptance criteria for the untouched 2025–26 window** — next decision.

## Next action

Codex and Claude: please proceed with implementing variants A–F behind config flags
(default off), using the frozen pre-registration rules above, once the remaining
harness decisions (tick-size fix and volume-drift tolerance) are also recorded.
Do not run the untouched window until acceptance criteria are agreed.
