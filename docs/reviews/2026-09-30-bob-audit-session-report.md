# Audit session report: V2 codebase audit and critical fixes

Index: 2026-09-30: Comprehensive 40-step audit found 19 issues; 5 critical fixed in this session — structure_alignment signal, CI branch ref, Variant A in CI, structure.py encoding, 7 new tests.

- **Written by:** Bob (IBM Bob, owner's desktop session), 2026-09-30
- **Branch:** `bob/audit-fixes-2026-09-30`
- **Base:** `main` at `22c597d` (post PR merges #146–#151)
- **Tests after fixes:** 780 passed, 4 skipped, 0 failures (was 773 before this session)

---

## Part 1 — What was audited

A full 40-step audit of the entire codebase was executed against `main` immediately after merging all 6 open PRs (#146–#151). The audit covered:

1. **Codebase logic integrity** — signal data flow, FTA cap logic, cache invalidation, Variant A deadline, boundary conditions
2. **Domain model and data contracts** — all fields on `MarketSignals`, `Inputs`, `RegimeAssessment`, `Frame`, `GridPlan`
3. **Strategy rules and configuration** — weight sums, threshold calibration, spec files, fee handling
4. **Infrastructure and CI/CD** — `backtest.yml`, `run_nopool.py`, artifact paths, Python version
5. **Documentation vs reality** — every claim in every 2026-09-29 and 2026-09-30 review doc checked against code
6. **Cross-cutting conflicts** — post-merge integration gaps, fee consistency, eligibility gate correctness
7. **Test coverage and correctness** — gaps, algebraic-only tests, missing integration paths

Full audit plan: [`docs/reviews/2026-09-30-bob-audit-plan.md`](2026-09-30-bob-audit-plan.md)
Full findings log: [`docs/reviews/2026-09-30-bob-audit-findings.md`](2026-09-30-bob-audit-findings.md)

---

## Part 2 — All findings (19 total)

### 🔴 Critical (5)

| ID | File | Description |
|---|---|---|
| **F1** | `backtest/replay.py` | `structure_alignment` never passed to `MarketSignals` in `signals_for()` — regime classifier permanently running at 90% signal power |
| **F8** | `config/datasets/*.toml` | `daily_warmup_start` absent from 3 specs — FTA and Variant A silently inactive on primary research windows |
| **F11** | `.github/workflows/backtest.yml` | `ref: bob/v2-integrated` — CI runs stale pre-merge code, not `main` |
| **F12** | `scripts/run_nopool.py` | No `--variant-a` flag — Variant A completely inaccessible from CI |
| **F19** | `src/crypto_grid_bot/strategy/structure.py` | UTF-16 encoding on Windows — Python cannot import it, entire local test suite fails |

### 🟡 Major (5)

| ID | Description |
|---|---|
| **F6** | BULL regime fit=0.80 (not 0.0) — "bot sits flat in BULL" is multi-factor eligibility collapse, not a hard gate. Proposals are imprecise. |
| **F15** | `test_structure.py` MTF weight tests are algebraic-only — no real bar sequence calls |
| **F16** | No test verifying `signals_for(gated=True)` passes `structure_alignment` (gap that allowed F1) |
| **F17** | No test for `_open_grid` FTA RANGE-only gate (commit `7395b6a` untested at integration level) |
| **F18** | No integration test for full `Inputs → Frame → _open_grid → GridBuilder(fta_resistance)` chain |

### 🟡 Minor / Advisory (9)

| ID | Description |
|---|---|
| **F2** | `Inputs.hour_open_ms` populated but never consumed downstream |
| **F3** | `RegimeAssessment.reasons` produced but never read in backtest path |
| **F4** | `GridPlan.fta_resistance_used` set but never read by any caller |
| **F5** | `analyse_multi_timeframe` docstring omits weight redistribution when timeframes absent |
| **F7** | Dispersion formula diluted ~17% by permanently-zero `structure_alignment` (consequence of F1) |
| **F9** | `full-range-2019-2024` spec not in workflow UI options |
| **F10** | Fee stamp hardcoded in `run_nopool.py` — consistent today but future trap |
| **F13** | §8.4 doc proposed fix is aspirational pseudocode, not actual implementation |
| **F14** | Variant A integration doc references stale `bob/v2-integrated` branch |

---

## Part 3 — What was fixed in this session

### Fix 1 — F19: `structure.py` UTF-16 encoding (local import broken)

**File:** `src/crypto_grid_bot/strategy/structure.py`

The file was stored as UTF-16 on Windows due to a Git checkout encoding issue. Converted to clean UTF-8. Also cleaned up Windows-1252 mojibake sequences in docstrings (e.g. `ΓÇö` → `—`, `├ù` → `×`). The file is now valid Python and imports correctly. 55 structure tests pass.

---

### Fix 2 — F1: `structure_alignment` wired into regime classifier

**File:** `src/crypto_grid_bot/backtest/replay.py`, function `signals_for()`

Added `structure_alignment=inputs.structure_alignment` to the gated `MarketSignals(...)` constructor call. One line added.

**Before:**
```python
return MarketSignals(
    inputs.trend, inputs.breadth, inputs.momentum,
    inputs.volatility_health, inputs.liquidity_health, inputs.adx,
    data_quality=inputs.market_quality,
    news_risk=0.0,
    emergency=False,
    observed_at=observed_at,
)
```

**After:**
```python
return MarketSignals(
    inputs.trend, inputs.breadth, inputs.momentum,
    inputs.volatility_health, inputs.liquidity_health, inputs.adx,
    data_quality=inputs.market_quality,
    news_risk=0.0,
    emergency=False,
    structure_alignment=inputs.structure_alignment,  # ← FIXED
    observed_at=observed_at,
)
```

**Impact:** The `structure_alignment` signal now actually reaches `RegimeClassifier._WEIGHTS["structure_alignment"]=0.10`. The regime classifier now runs at full designed signal power. All V2 backtests run before this fix were measuring a partially broken classifier. A re-run of all 4 backtest windows is needed to establish the correct V2 baseline.

---

### Fix 3 — F11: `backtest.yml` branch ref updated to `main`

**File:** `.github/workflows/backtest.yml`

Removed `ref: bob/v2-integrated` from the `actions/checkout` step. The workflow now checks out whatever branch triggers it (for `workflow_dispatch`, this defaults to `main`). All CI runs now use current code.

---

### Fix 4 — F12: `run_nopool.py` gains `--variant-a` flag

**File:** `scripts/run_nopool.py`

Added `--variant-a` CLI flag. When present:
- `policy = SimulationPolicy(trend_switch=True)` is passed to every `run_job()` call
- Output stamp gets `-variant-a` suffix to distinguish results

Usage:
```
python scripts/run_nopool.py practice-2022 --variant-a
python scripts/run_nopool.py long-bull-bear-2022 --variant-a
```

**Note:** Variant A still requires `daily_warmup_start` to be present in the spec (F8 — not yet fixed; daily bars must be fetched first). Running with `--variant-a` on a spec without daily bars will raise `ValueError` at runtime.

---

### Fix 5 — F12 (part 2) / F9: `backtest.yml` workflow gains Variant A toggle and full-range spec

**File:** `.github/workflows/backtest.yml`

- Added `variant_a` input (choice: `false`/`true`) to the `workflow_dispatch` trigger
- Added `full-range-2019-2024` to the spec options list
- Updated the "Run backtest" step to pass `--variant-a` to `run_nopool.py` when selected

---

### Fix 6 — F16/F17/F18: 7 new tests covering the audit gaps

**File:** `tests/test_backtest_replay.py`

Added two new test classes at the end of the file:

**`SignalsForStructureAlignmentTests`** (3 tests — F16):
- `test_gated_signals_carries_structure_alignment` — verifies `structure_alignment=0.75` from `Inputs` reaches `MarketSignals` in the gated path
- `test_gated_signals_negative_structure_alignment` — same for negative values
- `test_ungated_signals_structure_alignment_is_zero` — verifies ungated path always returns 0.0 (by design)

**`FtaRegimeGateTests`** (4 tests — F17/F18):
- `test_fta_passed_in_range_regime` — FTA resistance is passed to `GridBuilder.build()` when regime is RANGE ✅
- `test_fta_suppressed_in_bull_regime` — FTA resistance is `None` when regime is BULL ✅
- `test_fta_suppressed_in_bear_regime` — FTA resistance is `None` when regime is BEAR ✅
- `test_frame_carries_fta_from_inputs` — `Inputs.fta_resistance` survives `Frame` construction unchanged ✅

---

## Part 4 — What is NOT yet fixed (requires further work)

| ID | What's needed | Blocker |
|---|---|---|
| **F8** | Fetch daily bars; add `daily_warmup_start` to 3 specs | Owner must trigger `python -m crypto_grid_bot.backtest fetch` for each spec, then re-add the field |
| **F6** | Update proposals to reflect actual BULL eligibility mechanism | Documentation-only change, low urgency |
| **F15** | Add real bar sequence tests to `test_structure.py` | No blocker — next cleanup PR |
| **F2, F3, F4** | Remove or use dead fields | No blocker — next cleanup PR |
| **F5, F7** | Update docstrings | No blocker — next cleanup PR |
| **F13, F14** | Update stale doc references | No blocker — next cleanup PR |

---

## Part 5 — Re-run needed

**F1's fix changes the regime classifier's actual input.** All V2 backtest results reported in `2026-09-30-bob-v2-backtest-comparison.md` were produced with `structure_alignment=0.0` always. Now that the signal is wired correctly:

1. Re-run `long-bull-bear-2022` to establish the corrected V2 baseline (replaces the F1-affected results)
2. Re-run `long-recovery-2023-2024` for the same reason
3. After fixing F8 (fetch daily bars): re-run both windows with `--variant-a` for the Variant A measurement

The backtest comparison document should not be treated as the definitive V2 result until these re-runs are complete.

---

## Part 6 — Commands for owner / next agent

```bash
# Fix F8: fetch daily bars for the two primary windows, then add daily_warmup_start
python -m crypto_grid_bot.backtest fetch --spec config/datasets/long-bull-bear-2022.toml --data-dir data
python -m crypto_grid_bot.backtest fetch --spec config/datasets/long-recovery-2023-2024.toml --data-dir data
# Then add to each .toml:
# long-bull-bear-2022.toml:       daily_warmup_start = "2021-07"
# long-recovery-2023-2024.toml:   daily_warmup_start = "2022-10"

# Re-run corrected V2 backtest (F1 fixed)
python scripts/run_nopool.py long-bull-bear-2022
python scripts/run_nopool.py long-recovery-2023-2024

# Run Variant A (after F8 is fixed)
python scripts/run_nopool.py long-bull-bear-2022 --variant-a
python scripts/run_nopool.py long-recovery-2023-2024 --variant-a
```

— IBM Bob (owner's desktop session)
