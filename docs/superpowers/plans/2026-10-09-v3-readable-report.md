# Readable V3 account-report plan

> Execute inline with superpowers:executing-plans and test-first verification.

**Goal:** turn the existing reconciled account report into readable Markdown
tables for the frozen report output, retaining clear scope and invalid status.

**Architecture:** a pure renderer consumes FuturesRunReport, preserving exact
JSON as the precision companion. Display values use six decimal places; the
reconciliation residual stays exact. No writes, execution or data access.

- [ ] Test completed and invalid reports, actual month/cost/coin-side rows,
  unavailable values and positive Infinity. Escape table text.
- [ ] Render performance, months/economics, costs, exposure/caps, drawdown dates
  and coin/side profit with units and an explicit unevaluated experiment verdict.
- [ ] Run focused tests, lint/types/Bandit and independent review. Then publish
  with exact-head external review and full CI required before merge.
