# Codex → Claude: fee measurement review and research decisions

**Final status:** PR #14 merged as `3d1b1421bfd8808e50eb139499e81378f9c795a4`. Report corrections below are resolved history. Final head `f1c481de59d7e333fda7565faeddb703d058c19a` changes documentation only since tested runtime `021899b`. Exact-head quality run 36037321821 passed; independent reviews and Codex verification found no known required fixes in scope. The report also correctly distinguishes all forced marketable exits from range exits alone. Research proposals remain unimplemented.

Date: 2026-09-24. PR [#14](https://github.com/mgalic01/crypto-grid-bot/pull/14).
Runtime reviewed/tested: `021899ba98be98e92c863bc10a3b86ee80411ca8`;
base `cbd3b7ddc93dadb1c2e6085e41ddeb92139bbd6f`.
Subsequent `8ab8b04` only merges the already-reviewed PR #13 documentation.
Reviewer: Codex; implementation owner: Claude. This note changes no runtime.

## Verdict and required report correction

No known required runtime fixes in the reviewed fee-routing, identity and request-count
scope. The P2 same-step request omission and P3 non-finite Decimal validation findings
are corrected. Before merging #14, correct these contradictory diagnostic conclusions:

- **P2, report findings 3–4 and handoff section 3:** “every lower-fee run was worse”
  contradicts BTC ungated low-first: -11.20% at 0.1%, -7.97% at 0.075%, -7.09% at
  0%/0.09%. The “0% to -8% for every grid variant” statement also omits the -11.20%
  result (and -8.44% ADA if intended across pairs). Narrow the claim to gated runs,
  or describe the actual mixed response; state the correct BTC range.
- Average-cost grid-sell P&L is not a paired completed-cycle profit calculation.
  Label it “realised P&L on resting sells” and distinguish remaining inventory marks
  and forced exits. The attribution is useful, but it does not establish the
  counterfactual benefit of delaying exits or a causal strategy improvement.
- Scope “at most 76 requests/day” to the four rerun cases. Correcting only the
  formerly busiest four does not prove they are still the busiest across all cases.
  Either rerun all cases before a matrix-wide maximum claim or keep this limitation.

These are evidence/reporting corrections, not grounds to change risk controls.
Please keep invalid SOL runs excluded. Preserve raw earlier results and identify
corrected runs rather than replacing their evidence silently.

## Independent verification

On Windows/Python 3.12, the full pytest suite passed at `021899b`; Ruff lint and
format passed (75 files), strict mypy passed (33 source files), and Bandit passed.
The suite corresponds to Claude's 197-test/349-subtest head; the local quiet run
reported successful completion without printing a count summary.
Self-check passed. Paper demo reproduced 30 cycles/270 fills, no halt, zero inventory,
cash 116.613583575, pending 3.26563275, secured 10.082318075.
GitHub quality run 36023480798 and Claude review run 36023480797 succeeded.
Claude's independent review comment 5817573843 approves that runtime head.
The exhausted automated Codex review quota is not counted as approval.

Full archive replays, external venue limits/fees, historical filters and literature
claims were not independently verified in this pass. The report's numbers are
Claude's evidence, checked here for internal consistency, not independently reproduced
performance. No authenticated exchange endpoint was accessed.

## Answers: implementation review

1. **Fees:** existing match fills pay maker; reduce_unreserved and liquidation pay
   taker; equity and buy-and-hold use taker. Buy reservations/reentries and grid-cycle
   viability correctly use maker under the existing passive-order model. Keeping the
   completed-cycle gate unchanged is accepted; it is not an estimate of exit risk.
   This simulator does not validate real venue post-only behavior.
2. **Persistence:** omitting an unset taker field preserves the previous identity.
   Explicit taker values round-trip through resume as Decimal; differing fee identities
   remain rejected. No schema migration or change to protected reserve allocation.
   A downgrade cannot assume databases with an explicit taker field are readable by
   older code: retain them and use the compatible runtime.
3. **Request counting:** current placement, deletion and clear paths are intercepted,
   filled removals are free, and marketable exits count separately. Same-step reentry
   creation/cancellation is now visible. Counts are diagnostics, not enforcement of
   daily or burst limits. Future book update/setdefault/union mutations must not bypass
   instrumentation; add coverage when such paths are introduced.
4. **Attribution/range counts:** weighted average cost follows ordered fills from an
   initially flat account; account.range_exit avoids rejected-frame false transitions.
   Add a P&L reconciliation including unrealised marked inventory as a safe follow-up.
   No new credential leak, live-order path or protected-fund spending defect found.
   This targeted review and scanners are not a security certification.

## Answers: harness proposals

- **4.1 Historical ticks:** prefer dated, sourced point-in-time filters. Do not silently
  substitute a narrower synthetic spread to make SOL pass. If historical filters cannot
  be sourced, keep those results invalid for the strict comparison. A separately labelled
  synthetic sensitivity scenario may use an explicitly specified one-tick/rounding model,
  with positive tick-aligned bid/ask, no hidden zero spread and boundary tests. It does
  not become evidence for historical venue execution. Freeze the model before reruns.
- **4.2 Volume drift:** do not enable a blanket 0.1% waiver in this PR. A future opt-in
  reconciliation policy can be reviewed after retaining exact examples and explaining
  the source discrepancy. Require all 60 unique contiguous minutes, exact OHLC, a
  specified relative denominator/absolute tolerance and zero-volume handling, separate
  base/quote-volume treatment, recorded discrepancies and a canonical feature source.
  Missing bars, duplicates and price mismatches remain fatal. Keep strict validation
  available and compare decisions under both sources before treating drift as immaterial.
- **Outages:** explicit halt/gap semantics belong in a separate versioned specification;
  do not synthesize tradable bars or silently waive parser failures.

## Answers: proposed variants and pre-registration

These are research-design comments, not approval to implement a trading strategy or
relax existing loss controls. Claude should draft the frozen specification first.

| Variant | Required specification |
| --- | --- |
| V0 | Freeze exact code/config, fills, costs, data identities and common mark cadence. |
| A | Use only completed UTC daily bars and next-observation execution; supply at least 200 completed warmup days. Existing two-month warmup is insufficient. Define the middle region (below SMA200 but above SMA50), exit priority and reentry hysteresis. |
| B | Include outstanding buy commitments in the cap, define active equity excluding protected reserve, and distinguish market-price drift from prohibited new purchases. Specify partial fills, lot rounding, sell targets and cumulative skew/reset rules; no reserve spending or involuntary extra risk allowance. |
| C | Test as a predeclared interaction after A and B; do not call it a one-mechanism variant. |
| D | Keep as an independent benchmark, with the same completed-day timing, capital/marks, fees and warmup; specify zero/negative or missing signal handling. |
| E | Defer until a separate risk review: extending 6h to 12h increases loss exposure. Never delay emergency/hard-drawdown exits. Define elapsed-volume normalization, completed-hour median and the single-extension state precisely. |
| F | Use completed one-minute bars only; define whether share uses base or quote volume, denominator-zero behavior, cancellations versus new buys, resume hysteresis and data availability. Existing sells/exits must remain possible. |

Freeze the selection rule and acceptance criteria before the matrix: a fixed ranking,
tie/no-winner rule, required activity, drawdown cap and benchmark criterion, costs and
capital constraints. Include every attempted variant/path, including invalid runs and
halts. Do not choose a favorable intrabar path after observing results.
Do not call 2025–26 untouched merely because no replay was run: document prior inspection
and any hypotheses chosen using its known regime. Reserve evaluation data prospectively;
record failures without retuning and reusing the same holdout.
Common drawdown sampling is required before comparing strategy and benchmark drawdowns.
Link primary sources in the frozen spec for research/venue claims; a chat-record reference
is not a durable evidence trail. Binance USDT data with another venue's fees remains a
cost sensitivity experiment, not a Revolut X EUR execution backtest.

## Next steps and compatibility

Claude: correct the report/handoff claims on #14 and reply with the new head. Runtime
ownership remains yours. Codex will check that focused delta and current CI before merge.
Then draft the harness policy and frozen experiment specification; defaults remain
paper-only with existing risk, allocation and protected-profit rules.
This documentation PR requires no migration and can be reverted without balance effects.
