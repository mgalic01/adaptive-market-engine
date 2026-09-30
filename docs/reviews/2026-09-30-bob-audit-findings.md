# Comprehensive Codebase Audit — Master Findings Log

Index: 2026-09-30: Full codebase audit — 19 findings (5 critical, 5 major, 9 minor/advisory) across 40 steps.

**Written by:** Bob (IBM Bob, owner's desktop session)
**Date:** 2026-09-30
**Branch audited:** `main` at `22c597d` (post all PR merges #146–#151)
**Plan file:** `docs/reviews/audit-plan-2026-09-30.md`
**Steps completed:** 40 / 40
**Status:** COMPLETE

---

## Severity Classification

| Severity | Count |
|---|---|
| 🔴 CRITICAL | 5 (F1, F8, F11, F12, F19) |
| 🟡 MAJOR | 5 (F6, F15, F16, F17, F18) |
| 🟡 MINOR | 5 (F2, F3, F4, F5, F7, F9, F13, F14) |
| ⚪ ADVISORY | 3 (F10, and documented absences in news_risk/emergency) |

---

## CRITICAL Findings

### F1 — `structure_alignment` never reaches the regime classifier
**File:** `src/crypto_grid_bot/backtest/replay.py`, function `signals_for()`, lines 154–165
**Severity:** 🔴 CRITICAL
**Description:** `features.py` correctly computes `structure_alignment` from `analyse_multi_timeframe()` and stores it on `Inputs.structure_alignment`. However, `signals_for()` constructs `MarketSignals` using positional arguments for the 6 required fields (`trend, breadth, momentum, volatility_health, liquidity_health, adx`) and keyword arguments for `data_quality`, `news_risk`, `emergency`, `observed_at`. The field `structure_alignment` is never passed — it defaults to `0.0` on every frame.

**Effect:** The entire V2 `structure_alignment` signal is permanently neutralised. `RegimeClassifier._WEIGHTS["structure_alignment"] = 0.10` contributes nothing. The `trend` weight reduction from 0.35→0.25 stands, but gives nothing in return. The regime classifier effectively runs at 90% designed signal power with 10% wasted weight budget. All V2 backtests run to date have been measuring a partially broken classifier.

**Fix:** Add `structure_alignment=inputs.structure_alignment` to the gated `MarketSignals(...)` call in `signals_for()`:
```python
return MarketSignals(
    inputs.trend,
    inputs.breadth,
    inputs.momentum,
    inputs.volatility_health,
    inputs.liquidity_health,
    inputs.adx,
    data_quality=inputs.market_quality,
    news_risk=0.0,
    emergency=False,
    structure_alignment=inputs.structure_alignment,  # ADD THIS LINE
    observed_at=observed_at,
)
```

---

### F8 — `daily_warmup_start` missing from two primary V2 research windows
**Files:** `config/datasets/long-bull-bear-2022.toml`, `config/datasets/long-recovery-2023-2024.toml`, `config/datasets/full-range-2019-2024.toml`
**Severity:** 🔴 CRITICAL
**Description:** `daily_warmup_start` is commented out in all three specs. This causes:
1. `daily_bars=None` in `FeatureEngine` for these windows
2. `fta_resistance=None` always (FTA signal completely inactive on these windows)
3. Variant A crashes with `ValueError: variant A needs the pair's daily history`

**Effect:** V2 features (FTA resistance cap, structure-aligned grid placement) are silently inactive for the two most important test windows (`long-bull-bear-2022` and `long-recovery-2023-2024`). The V2 backtest comparison report was produced with these features inactive. Variant A cannot be tested on these windows at all.

**Fix:** Fetch daily bars for these specs and add the `daily_warmup_start` field as documented in the comment of each file:
- `long-bull-bear-2022.toml`: `daily_warmup_start = "2021-07"`
- `long-recovery-2023-2024.toml`: `daily_warmup_start = "2022-10"`
- `full-range-2019-2024.toml`: `daily_warmup_start = "2018-07"`

---

### F11 — `backtest.yml` checks out stale branch instead of `main`
**File:** `.github/workflows/backtest.yml`, line 28
**Severity:** 🔴 CRITICAL
**Description:** The workflow contains `ref: bob/v2-integrated`. That branch is now behind `main` — it does not contain the FTA fix (`7395b6a`), the post-merge documentation, or the squash commits from PRs #146–#151. Any CI run executes stale pre-merge code.

**Effect:** Every GitHub Actions backtest run produces results from the old code, not the current `main`. The FTA cap RANGE-only fix is not present in CI runs.

**Fix:** Change line 28 to:
```yaml
ref: main
```
Or remove the `ref:` line entirely (defaults to the triggering branch, which for `workflow_dispatch` is the default branch `main`).

---

### F12 — Variant A cannot run in CI
**File:** `scripts/run_nopool.py`
**Severity:** 🔴 CRITICAL
**Description:** `run_nopool.py` always calls `run_job(..., policy=None)`. There is no mechanism to pass `SimulationPolicy(trend_switch=True)`. The `--variant-a` flag exists only in the CLI (`__main__.py`) which uses `ProcessPoolExecutor` — broken on Windows. Since CI uses `run_nopool.py`, Variant A is inaccessible from all CI runs.

**Effect:** The single most important unmeasured test (Variant A: daily SMA50/SMA200 trend switch that could capture bull-market returns) cannot run via the workflow. It also requires F8 to be fixed first (daily bars must be fetched).

**Fix:** Add an optional `--variant-a` flag to `run_nopool.py` that sets `policy=SimulationPolicy(trend_switch=True)` for all `run_job()` calls.

---

### F19 — `structure.py` is UTF-16 encoded locally; Python cannot import it
**File:** `src/crypto_grid_bot/strategy/structure.py`
**Severity:** 🔴 CRITICAL
**Description:** The local copy of `structure.py` is UTF-16 encoded (BOM `\xff\xfe`). Python's import system cannot handle this — `SyntaxError: source code string cannot contain null bytes`. The file on `origin/main` is valid UTF-8 with BOM and imports correctly on Linux (GitHub Actions). This is a Windows Git checkout encoding issue.

**Effect:** The entire local test suite fails to collect. 9+ test modules that directly or transitively import `structure.py` (all backtest, replay, structure, and trend modules) produce `ERROR` during collection. No local testing is possible until this is fixed.

**Fix:** Re-checkout the file from origin:
```
git checkout origin/main -- src/crypto_grid_bot/strategy/structure.py
```
Or configure `.gitattributes` to force `text eol=lf` for all `.py` files to prevent future recurrence.

---

## MAJOR Findings

### F6 — BULL regime does not hard-block grid opening
**File:** `src/crypto_grid_bot/strategy/opportunity.py`, lines 23–29
**Severity:** 🟡 MAJOR
**Description:** `OpportunityScorer._REGIME_FIT[MarketRegime.BULL] = 0.80`. In a BULL regime, a grid CAN open if the composite opportunity score (range_quality × net_grid_edge × liquidity_quality × ...) × 0.80 exceeds `minimum_opportunity_score`. The gate is not hard-closed in BULL — it is a 20% penalty.

**Effect:** Documentation and proposals describing "gated BULL → no grid" as a hard rule are imprecise. In practice, the 0% gated returns in BULL windows (BTC +245%, ETH +99%) result from multi-factor eligibility collapse (`range_quality` near 0 in a trend, not from the BULL regime flag alone). This matters for future Mode design: any "bull-market participation" feature must account for the fact that eligibility, not just regime, drives the gate.

---

### F15 — `test_structure.py` multi-timeframe weight tests are algebraic-only
**File:** `tests/test_structure.py`, lines 459–474
**Severity:** 🟡 MAJOR
**Description:** Tests `test_all_bullish_gives_positive_alignment` and `test_mixed_alignment_is_weighted` verify the weight redistribution formula algebraically without calling `analyse_multi_timeframe()` with real bar sequences. No test constructs bullish/bearish bar data and passes `weekly_bars=None` to verify the code actually performs redistribution.

**Fix:** Add integration tests that construct known-bullish or known-bearish hourly and daily bar sequences and verify `analyse_multi_timeframe(hourly=..., daily=..., weekly=None)` returns the expected alignment score.

---

### F16 — No test for `signals_for()` passing `structure_alignment` to `MarketSignals`
**Files:** `tests/test_backtest_replay.py`
**Severity:** 🟡 MAJOR
**Description:** No test calls `signals_for(inputs, when, gated=True)` and verifies that `structure_alignment` from `Inputs` appears in the returned `MarketSignals`. This is the exact gap that allowed F1 (structure_alignment silent zeroing) to exist undetected.

**Fix:** Add a test to `test_backtest_replay.py` that constructs an `Inputs` with a non-zero `structure_alignment`, calls `signals_for(..., gated=True)`, and asserts `result.structure_alignment == inputs.structure_alignment`.

---

### F17 — No test for `_open_grid` FTA regime gate
**Severity:** 🟡 MAJOR
**Description:** The fix from `7395b6a` (FTA cap disabled in BULL/BEAR) is tested only at the `GridBuilder.build()` unit level. No test verifies that `PaperSimulator._open_grid()` correctly passes `fta_resistance=None` when `regime.regime != RANGE` and passes the actual FTA value when `regime.regime == RANGE`.

**Fix:** Add an integration test in `test_simulation_runner.py` that opens a grid in a RANGE regime with FTA set and verifies the cap is applied, then opens in a BULL regime and verifies no cap.

---

### F18 — No integration test for full `Inputs → Frame → _open_grid → GridBuilder` FTA chain
**Severity:** 🟡 MAJOR
**Description:** No test covers the complete path: `FeatureEngine.at()` returning `Inputs(fta_resistance=X)` → `Frame(fta_resistance=X)` → `_open_grid` → `GridBuilder.build(fta_resistance=X)`. A drop anywhere in this chain would be undetected.

---

## MINOR Findings

### F2 — `Inputs.hour_open_ms` is a dead output field
**File:** `src/crypto_grid_bot/backtest/features.py`, line 184
**Severity:** 🟡 MINOR
**Description:** `hour_open_ms` is computed and stored on `Inputs` but never read downstream (not passed to `signals_for`, `candidate_for`, `Frame`, or any other consumer). Dead field.

---

### F3 — `RegimeAssessment.reasons` is produced but never read in backtest
**File:** `src/crypto_grid_bot/strategy/regime.py`
**Severity:** 🟡 MINOR
**Description:** `RegimeAssessment.reasons` (a tuple of diagnostic strings) is produced by `classify()` but never read in `runner.py` or `replay.py`. The `result.reasons` references in runner.py are from `RiskDecision`, not `RegimeAssessment`. The field is available for live trading diagnostics but is dead in the backtest path.

---

### F4 — `GridPlan.fta_resistance_used` is never read
**File:** `src/crypto_grid_bot/domain.py`, line 103
**Severity:** 🟡 MINOR
**Description:** `GridPlan.fta_resistance_used` is set by `GridBuilder.build()` but never read by any caller (runner, replay, or tests). Useful for diagnostics but currently contributes nothing.

---

### F5 — `analyse_multi_timeframe` docstring omits weight redistribution
**File:** `src/crypto_grid_bot/strategy/structure.py`
**Severity:** 🟡 MINOR
**Description:** Docstring states "weights: weekly 0.5, daily 0.35, hourly 0.15" without noting that weights are redistributed when timeframes are absent. When weekly=None (always currently), effective weights become hourly 30% / daily 70%. Code is correct; docstring is misleading.

---

### F7 — Dispersion formula diluted by permanently-zero `structure_alignment`
**File:** `src/crypto_grid_bot/strategy/regime.py`, line 111
**Severity:** 🟡 MINOR
**Description:** `dispersion = sum(abs(value) for value in values.values()) / len(values)` uses `len(values)=6`. Since `structure_alignment=0.0` always (F1), dispersion is diluted ~17% vs the 5-signal baseline. Range classification is slightly easier than intended. This is a consequence of F1 — will self-correct when F1 is fixed.

---

### F9 — `full-range-2019-2024` spec not in workflow options
**File:** `.github/workflows/backtest.yml`, lines 10–15
**Severity:** 🟡 MINOR
**Description:** `full-range-2019-2024.toml` exists but cannot be triggered via the CI workflow UI. Must be run manually via CLI.

---

### F13 — §8.4 proposed fix pseudocode differs from actual implementation
**File:** `docs/reviews/2026-09-30-bob-v2-backtest-comparison.md`, lines 273–274
**Severity:** 🟡 MINOR
**Description:** The proposed fix creates a `frame_with_fta` object that is never used in the actual implementation. Actual fix computes `fta` locally and passes it directly to `builder.build()`. Intent is correct; code snippet is aspirational/pseudocode.

---

### F14 — Variant A integration doc references stale branch
**File:** `docs/reviews/2026-09-29-bob-variant-a-v2-integration.md`
**Severity:** 🟡 MINOR
**Description:** References `bob/v2-integrated` branch. That branch is now behind `main`.

---

## Steps with No Findings (PASS)

| Step | Result |
|---|---|
| 1.3 Frame positional args | PASS |
| 1.2 fta_resistance data flow | PASS |
| 1.4 _open_grid FTA RANGE guard | PASS |
| 1.5 signals_for ungated arg count | PASS (by design) |
| 1.6 GridBuilder boundary conditions | PASS |
| 1.7 _structure_cache invalidation | PASS |
| 1.8 swing detection + 500-bar window | PASS |
| 1.10 TrendSchedule lookahead prevention | PASS |
| 1.11 Variant A Down deadline logic | PASS |
| 1.12 Regime gate / grid open | PASS |
| 2.4 Frame.payload fta omission safety | PASS |
| 3.1 Classifier weight sum = 1.0 | PASS |
| 3.5 Fee hardcoding (consistent today) | ADVISORY |
| 3.6 SimulationPolicy default vs Variant A | PASS |
| 4.2 Artifact upload path | PASS |
| 4.4 run_nopool relative paths in CI | PASS |
| 4.5 Python version consistency | PASS |
| 5.1 §8.4 doc vs actual fix intent | PASS (minor wording) |
| 5.3 fta-integration doc Index: line | PASS |
| 5.5 master proposal §11 merge order | PASS |
| 5.6 AGENT_HANDOFF.md current state | PASS |
| 6.2 FTA + structure_alignment interaction | No additional conflict |
| 6.3 Fee hardcoding vs run_job | ADVISORY |
| 6.4 _open_grid only when eligible | PASS |
| 6.5 PR #149 doc on main | PASS |
| 7.1 test_regime 6-signal math | PASS |
| 7.3 test_grid FTA cap setup | PASS |
| 7.7 test_trend_switch lookahead | PASS |

---

## Recommended Fix Order

| Priority | Finding | Action |
|---|---|---|
| **1 (IMMEDIATE)** | F19 | Re-checkout `structure.py` from origin to fix local UTF-16 encoding |
| **2 (IMMEDIATE)** | F1 | Add `structure_alignment=inputs.structure_alignment` to `signals_for()` gated path |
| **3 (IMMEDIATE)** | F11 | Change `backtest.yml` `ref: bob/v2-integrated` → `ref: main` |
| **4 (BEFORE VARIANT A)** | F8 | Fetch daily bars; add `daily_warmup_start` to 3 specs |
| **5 (BEFORE VARIANT A)** | F12 | Add `--variant-a` flag to `run_nopool.py` |
| **6 (NEXT PR)** | F16 | Add test for `signals_for()` gated path passing `structure_alignment` |
| **7 (NEXT PR)** | F17/F18 | Add integration tests for FTA regime gate and full FTA chain |
| **8 (CLEANUP)** | F15 | Add real bar sequence tests to `test_structure.py` MTF section |
| **9 (CLEANUP)** | F6 | Update proposals/docs to reflect actual eligibility mechanism |
| **10 (CLEANUP)** | F2–F5, F7, F9, F13, F14 | Minor doc and dead-field cleanup |

— IBM Bob (owner's desktop session)
