# V3.1 Combined System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Implement an explainable shared-capital spot trend/grid and futures system.
**Architecture:** New combined package around unchanged causal primitives. Pure
assessment and strategy intent are separated from serialized portfolio admission,
ledger/execution events and read-only evidence analysis.
**Tech Stack:** Python3.12, Decimal60, standard library, pytest; offline HTML/SVG.
**Spec:** ../specs/2026-10-10-v3-1-design.md

## Global constraints

- Frozen V0–V3 code, results and configuration remain unchanged.
- No live trading, new dependencies, 2025+ data, historical retry or unapproved run.
- Lifetime observed maximum drawdown<=30% for acceptance; trigger is not a ceiling.
- Recovery24h minimum, qualified25% risk,3% episode stop, half below15%, full below10%.
- Wallet/quantity exact; trade/equity reconciliation tolerance<=1e-18 USDT, retain residuals.
- Latest-full-head Bob/Claude substantive review and required checks before merge.

## Review focus

1. Two simultaneous intents competing for the same remaining cash/risk must not both pass.
2. Partial liquidation and unsellable dust must not prematurely permit asset reassignment.
3. Same timestamp funding, exit and entry must not evade payment or duplicate fees.
4. Stale but numerically valid indicators must not admit a trade.
5. A profitable recovery must not erase an earlier failed lifetime risk test.

## Task 1: Package A documents and register

Files: specification above; docs/V3_1_SOURCE_INVENTORY.md;
config/v3_1_experiment_menu.json; this plan.
Interfaces: named immutable arm IDs and explicit blocked execution status; no launcher.
- [ ] Save approved architecture and fixed engineering preset with source inventory.
- [ ] Enumerate all arms, cost multiples1/2, both capital scenarios and incomplete pins.
- [ ] Check parse, unique IDs, matching spec menu, no executable authorization.
- [ ] Run `python -B scripts/check_reports.py` and `git diff --check`; expect zero problems.
- [ ] Commit documents and obtain independent review before strategy implementation.

## Task 2: Assessment and evidence contracts

Create combined/models.py, assessment.py, evidence.py; tests/test_combined_assessment.py.
Consumes: Kline, indicators.Bar, perception.trend_state (unchanged).
Produces: assess(symbol: str, decision_ms: int, hourly: Sequence[Kline],
 daily: Sequence[Kline], quote_ms: int) -> Assessment; frozen dataclass Assessment
 with schema, source times, direction, structure, atr, extension, volatility and reasons.
MarketAssessment is price-only. AdmissionContext explicitly carries funding rate,
publication time/cadence, fifteen flow bars, quote costs/filters, correlation snapshot
and PortfolioView; qualification(assessment: Assessment, context: AdmissionContext)
-> QualifiedAssessment combines them without globals. Strategy consumes this combined record.
Evidence.record(event: DecisionEvent) -> None; append-only stable event ID and schema.
- [ ] Test future-bar suffix leaves assessment unchanged; missing due hour unavailable;
  inadequate120 ATR history unavailable; UP continuation not vetoed solely by RSI75.
- [ ] Run focused tests; expect missing-module/implementation failure first.
- [ ] Implement causal assessment and serialization; validate finite/aligned input.
- [ ] Rerun focused tests, ruff and mypy; expect all pass; commit.

## Task 3: Shared risk and recovery

Create combined/risk.py, recovery.py; tests/test_combined_risk.py and recovery.py.
Consumes Assessment and immutable portfolio view (equity, cash, positions,
 reservations, maintenance); produces Admission(reason, approved_quantity,
 reserved_cash, reserved_risk) and RecoveryDecision(state, risk_fraction, close).
Recovery.update(timestamp_ms: int, equity: Decimal, tradable_flat: bool,
 qualified: bool, integrity_ok: bool) -> RecoveryDecision.
PortfolioRisk.reserve(intent: Intent, view: PortfolioView) -> Admission serializes
 accepted reservations; release only after cancellation/fill acknowledgement.
- [ ] Test equity100->70 closes, unfinished flatten blocks timer, verified dust permits
  cooldown but preserves valuation/ownership; flat+24h+qualified
  gives0.25; equity peak71->68.87 closes; lifetimepeak remains100; integrity never resets.
- [ ] Test half/full at strict15%/10%; unqualified upgrade refused; maxDD persists.
- [ ] Test simultaneous asset ownership/cash/risk reservations, unknown-correlation
  group, minimum quantity, adverse funding, Decimal NaN rejection and tiny capital.
- [ ] Run tests RED; implement rules; run GREEN, ruff/mypy; commit.

## Task 4: Strategy intents

Create combined/strategies.py; tests/test_combined_strategies.py.
Consumes Assessment, PortfolioView and fixed preset. Produces immutable Intent
(symbol, owner, venue, signed quantity, stop, targets, decision timestamp, source IDs).
route(assessment: Assessment, enabled: frozenset[str]) -> tuple[str, ...].
- [ ] Test UP prefers spot, proven non-executable spot permits futures; DOWN needs
  affirmative structure; no UP short in any arm; conflict/stress no increase.
- [ ] Test extension2/3 boundaries,2ATR stop,2R/3ATR non-widening trail, equal-risk
  grid spacing/cost floor, F hysteresis and missing-flow refusal; range exit sells.
- [ ] Run RED; implement; run GREEN with assessment/risk suite; commit.

## Task 5: Ledger and event execution

Create combined/account.py, execution.py; tests/test_combined_account.py, execution.py.
Consumes admitted Intent, immutable fill/funding events and pinned filters/costs.
CombinedAccount.apply(event: AccountEvent) -> AccountSnapshot; engine.step(event:
 MarketEvent) -> tuple[DecisionEvent, ...]. Duplicate ID same content is idempotent;
 conflicting duplicate is integrity failure. Shared free cash and collateral explicit.
- [ ] Test spot purchase and futures collateral cannot each spend same100; fees,
  realized/unrealized P&L and funding reconcile; partial fills retain reservations.
- [ ] Test adverse gap before target, funding before simultaneous exit, no same-bar
  optimistic trail, missing price keeps close obligation, dust preserves ownership.
- [ ] Test account exhaustion and maintenance liquidation fail evaluation.
- [ ] Run RED; implement; run GREEN with all combined tests; commit.

## Task 6: Replay adapter and acceptance

Create combined/replay.py, experiment.py; tests/test_combined_replay.py, experiment.py.
Consumes completed-time input streams, config arm, declared sources; produces
ReplayResult with immutable evidence and complete/failed outcomes. No download.
Acceptance.evaluate(result: ReplayResult, comparisons: tuple[ReplayResult,...])
 returns pass/fail/incomplete and all reasons, never silently reduces matrix.
- [ ] Test no-lookahead suffix invariance, deterministic event order, disabled new
  components preserve frozen baseline on synthetic inputs; no2025 accepted.
- [ ] Test missing mandatory baseline incomplete; doubled-cost nonpositive fail;
  recovery breach30% remains fail; FX missing makes EUR scenario incomplete.
- [ ] Run RED; implement; run GREEN and full preflight; commit.

## Task 7: Evidence analysis and local dashboard

Create combined/report.py, dashboard.py; tests/test_combined_report.py, dashboard.py.
Consumes evidence only; produces loss/return attribution and offline HTML with SVG
curves/tables/source links. render_report(results: Sequence[ReplayResult]) -> str.
- [ ] Test episode aggregation does not count each hour as independent opportunity;
  strategy/direction/asset/regime totals reconcile; recovery incremental P&L and
  fees/funding/giveback shown; absent source marked incomplete.
- [ ] Test malicious symbol/text escaped, no remote resources; inspect local render
  at normal and narrow width with synthetic evidence labelled synthetic.
- [ ] Run RED; implement; run GREEN and full preflight; commit.

## Task 8: Review and execution handoff

- [ ] Review complete diff, use fresh independent critic, resolve findings with tests.
- [ ] Obtain Bob/Claude latest-full-head substantive review and green required CI.
- [ ] Merge only reviewed ready packages; no mechanical auto-merge.
- [ ] Produce exact finite registration and compare coverage with mandatory menu.
- [ ] Ask owner for historical-run authorization visibly with exact pins and scope.
- [ ] Only after go, execute once; retain every failure, diagnose and publish pass/fail.

## Parallel repository queue

PR265: current external reviewer timeout diagnosed; retry review pending. Merge only
at reviewed full head. PR169: research consolidation on its own branch; preserve
208/177 docs and links before closing them. PR194: fixture-tested activity-after
verification, substantive Bob review and explicit owner merge approval; no remote
workflow trial dispatched. Those gates do not block independent offline preparation.
