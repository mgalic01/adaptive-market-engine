# V3 Spot Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the frozen section 8 risk-matched spot hold comparison needed for A5, plus its doubled-cost run.

**Architecture:** A separate spot cash ledger settles buys and sells without borrowing or funding. A benchmark runner shares validated source calendars and the m=1 sizing mathematics, but uses constant +1 signals, spot prices and spot filters. No historical dispatch is part of these implementation tasks.

**Tech Stack:** Python, Decimal60 ROUND_HALF_EVEN, existing OrderFilters, PendingDecisions, sizing helpers and pytest. No new dependency. The older simulation execution uses precision 50 and is not a drop-in implementation of this frozen arithmetic.

## Files and responsibilities

- `src/crypto_grid_bot/trend/spot_account.py`: immutable fill records; initial cash 10,000; holdings, cash, fees, marks and exact cash/quantity audits.
- `src/crypto_grid_bot/trend/spot_benchmark.py`: bounded daily history, constant signals, eligibility, exclusions, pending orders, sells-before-buys and terminal valuation.
- `tests/test_trend_spot_account.py`: hand-calculated settlement, insufficent cash, step/minimum constraints and audit corruption.
- `tests/test_trend_spot_benchmark.py`: synthetic multi-coin replay, deferrals, exclusions, dust, shared comparison window and cost scenarios.
- `docs/reviews/2026-10-08-codex-v3-spot-benchmark.md`: indexed review handoff and actual validation evidence.

## Task 1: Spot ledger and executable quantities

- [ ] Write failing tests for `SpotAccount.fill(symbol, signed_quantity, open_price, filters, timestamp_ms)` and `mark(prices)`. Buys spend slipped notional plus 0.10% fee, sells receive slipped notional minus fee. Slippage is 0.05%; cost multiplier 2 doubles both rates.
- [ ] Verify failing tests, then implement chronological, finite, bounded Decimal60 settlement and immutable fill evidence. Buy quantities are clipped to cash including fees then floored to the spot step. Never sell more than holdings.
- [ ] Test buy and sell minimum notional, minimum/maximum quantity and max-order splitting. A skipped dust sell preserves the holding and evidence; do not borrow or manufacture liquidation events.
- [ ] Test exact cash = initial - buys + sells - fees and quantity = buys - sells. Preserve raw residuals and fail on any nonzero cash/quantity residual. Account marks include all retained dust.
- [ ] Verify focused tests, Ruff and mypy; commit with handoff. No performance claims from these fixtures.

## Task 2: Risk-matched continuous hold replay

- [ ] Write failing end-to-end tests for a fresh account at the first OOS quarter, constant +1 eligible signals, m=1 volatility sizing/caps, >1% rebalance band, daily 00:00 decisions and earliest 01:00 fills.
- [ ] Implement `replay_spot_benchmark` on supplied prevalidated inputs. Use no futures funding. Both futures eligibility exclusions and spot exclusions apply; pass the exclusive run end to exclusion decisions so future months cannot force an in-window close.
- [ ] Test sells-before-buys and deterministic coin ordering, cash clipping, masked-hour deferral, replacement cancellations, no-spot-bar behavior and exclusion overrides. Unavailable futures close invalidity is not copied blindly: spot dust that cannot meet minimum notional remains marked and reported, as section 8 requires.
- [ ] Test one continuous account across quarters, no terminal closing fee, last-unmasked close valuation, initial/terminal sample conventions and whole-path drawdown marks. Compare identical timestamps to the strategy's m=1 samples before computing A5.
- [ ] Execute base and double costs in independent accounts with identical eligibility and signals. Report skip/dust/cash-shortfall evidence. Verify tests, Ruff and mypy; request exact-head external review.

## Task 3: Reporting and later integration

- [ ] Preserve all fills, cancellations, skipped orders, dust, equity samples/path and accounting audits in the durable evidence format when that writer exists. Keep spot accounting checks independent from futures reconciliation.
- [ ] Feed validated daily equity into common metrics and bootstrap. Clearly label the risk-matched hold benchmark separately from the full-size, non-rebalancing equal-weight buy-and-hold diagnostic, which needs its own allocation logic.
- [ ] Wire base/double benchmark runs into registered dispatch only after reviewed manifests, completing registration and the data-delivery route are ready. Keep 2025+ data untouched.

Completion requires the implementation and evidence above; this plan alone does not satisfy A5 or authorize a historical run. Any discrepancy with the frozen spec is resolved before implementation, not by changing acceptance thresholds after results.
