# V3 experiment report assembly plan

> Execute inline with superpowers:executing-plans and test-first verification.

**Goal:** assemble the frozen experiment evidence into one inspectable report,
without granting a historical verdict before source/registration validation.

**Architecture:** pure report builders consume supplied replay results and training
scores. They verify complete scenario menus, shared account boundaries/settings,
training picks and accounting. They never run strategies or fetch data. JSON keeps
exact decimals and Markdown presents side-by-side comparisons. Historical dispatch
and full-size hold remain separate dependencies; missing evidence is explicit.

**Spec:** docs/EXPERIMENT_SPEC_V3.md sections 7-9.
**Stack:** Python standard library, existing Decimal60 report/metrics modules.

## Constraints
- No market data access, 2025+ data, parameter changes or order execution.
- Engine/accounting failure raises rather than becoming a strategy verdict.
- Known strategy-invalid results retain partial diagnostics and no fabricated metrics.
- Reporting has no whole-experiment pass while provenance, registration, full-period
  coverage or required full-size diagnostic remains uncertified.

## Tasks
- [ ] Add selection diagnostics: every quarter has all 12 scores, unique run IDs,
  known invalid reasons, recomputed frozen pick, and month-labelled coin counts.
  Tests cover ties, all-invalid, duplicates, missing/extra results and false picks.
- [ ] Add audited spot summary and independent seeded Sharpe intervals beside the
  main/m1/hold accounts; retain explicit unavailable intervals below 60 returns.
- [ ] Assemble all six futures scenarios, twelve fixed rules and both spot costs;
  validate settings and shared boundaries, retain invalid results and reject engine
  errors. Include minimum account size, training, picks and diagnostic limitations.
- [ ] Render exact JSON and readable experiment tables, with explicit remaining
  provenance/registration/full-size-hold requirements and no certification claim.
- [ ] Run focused checks, independent critical review and full CI; publish one
  coherent report assembly PR for Bob review before merge.

## Review focus
- A missing scenario must never silently disappear from a comparison table.
- A training engine error cannot be treated as an invalid strategy.
- A cached pick must match the complete training score menu and tie ordering.
- Invalid accounts must not receive completed-run performance metrics.
- Futures and spot execution prices/filters are distinct; source identity remains
  a registered-manifest obligation, never inferred from matching symbol names.
