# V3 A1-A5 checks implementation plan

> Use superpowers:executing-plans, inline with fail-first tests.

**Goal:** evaluate frozen A1-A5 on completed, reconciled main m=2, unchanged-pick
m=1 and risk-matched spot accounts, without issuing a whole-experiment verdict.

**Architecture:** immutable criterion rows retain observed values, thresholds,
strictness and outcomes. Main and m=1 must have matching complete decision
schedules and sample times. Existing reconciliation and A5 evidence validation
run before scoring. Invalid/engine-failed accounts require the enclosing
experiment's separate outcome handling, not fabricated metrics.

- [ ] Test threshold equality, below-threshold values and legitimate positive
  Infinity; A5 remains strictly greater, even when both Sharpes equal zero.
- [ ] Test actual synthetic flat accounts plus wrong size/cost, missing or
  different picks and mismatched dates. Implement minimal calculator/wrapper.
- [ ] Run focused tests, lint, types, Bandit and independent review before push.
- [ ] Require full CI and substantive external full-head review before merge.

Registration, full required scenario coverage and historical data provenance
remain mandatory checks upstream. No market data or criterion change.
