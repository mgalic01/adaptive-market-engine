# Audit Plan 1 — Close-Out Report

Index: 2026-09-30/ongoing: Full close-out of the first 40-step codebase audit. All 19 findings resolved. Documents what was fixed, why each fix was made, and the exact code changes so Codex and Claude can understand the state of the codebase without re-auditing.

**Written by:** Bob (IBM Bob, owner's desktop session)
**Audit plan:** `docs/reviews/2026-09-30-bob-audit-plan.md` (40 steps, all EXECUTED)
**Findings log:** `docs/reviews/2026-09-30-bob-audit-findings.md` (19 findings)
**Session report:** `docs/reviews/2026-09-30-bob-audit-session-report.md` (fixes F1, F11, F12, F16–F19 in PR #154)
**This document covers:** the remaining fixes made in PR #156 and follow-on commits, closing out every finding.

---

## Why this document exists

The session report (`2026-09-30-bob-audit-session-report.md`) was written immediately after PR #154 merged. It documented the five critical fixes from that PR but left several findings still open ("requires further work"). This close-out document records everything that was done after that, explains *why* each decision was made, and leaves the codebase in a known-good state for the next agent.

**The most important principle in this project:** every change must have a documented *why*. Code that is correct but unexplained is indistinguishable from code that is accidentally correct. Future agents must be able to reconstruct intent.

---

## Complete finding resolution table

| ID | Severity | Description | Resolution | Commit/PR |
|---|---|---|---|---|
| F1 | CRITICAL | `structure_alignment` never reached regime classifier | Fixed: added `structure_alignment=inputs.structure_alignment` to `signals_for()` gated path | PR #154 |
| F8 | CRITICAL | `daily_warmup_start` missing from 3 dataset specs | Fixed: added to `long-bull-bear-2022.toml` and `long-recovery-2023-2024.toml` in PR #154; `full-range-2019-2024.toml` required fetch first — fetch infrastructure fixed and daily bars downloaded (see §F8 below) | PR #154 + PR #156 commit |
| F11 | CRITICAL | `backtest.yml` checked out stale `bob/v2-integrated` | Fixed: removed `ref:` line; CI now checks out the triggering branch (default: `main`) | PR #154 |
| F12 | CRITICAL | No `--variant-a` flag in `run_nopool.py` | Fixed: added `--variant-a` flag; sets `SimulationPolicy(trend_switch=True)` and appends `-variant-a` to output stamp | PR #154 |
| F19 | CRITICAL | `structure.py` UTF-16 on Windows — import fails | Fixed: re-encoded as clean UTF-8; Windows Git checkout issue | PR #154 |
| F6 | MAJOR | BULL regime gate described as hard block — actually soft | Fixed: corrected `§8.1` of `2026-09-30-bob-v2-backtest-comparison.md` — BULL gating is multi-factor eligibility collapse (`range_quality ≈ 0` + regime fit 0.80), not a hard regime-flag gate | PR #156 commit 3 |
| F15 | MAJOR | MTF weight tests algebraic-only — no real bar sequences | Fixed: added 4 real bar-sequence integration tests to `TestAnalyseMultiTimeframe` (see §F15 below) | PR #156 commit 3 |
| F16 | MAJOR | No test for `signals_for()` passing `structure_alignment` | Fixed: `SignalsForStructureAlignmentTests` (3 tests) in `test_backtest_replay.py` | PR #154 |
| F17 | MAJOR | No test for `_open_grid` FTA RANGE gate | Fixed: `FtaRegimeGateTests` (4 tests) in `test_backtest_replay.py` | PR #154 |
| F18 | MAJOR | No integration test for full FTA chain | Fixed: `test_frame_carries_fta_from_inputs` in `test_backtest_replay.py` | PR #154 |
| F2 | MINOR | `Inputs.hour_open_ms` dead field | Fixed: removed field and its computation from `features.py`; updated `test_backtest_replay.py` | PR #156 |
| F3 | MINOR | `RegimeAssessment.reasons` never read in backtest | Accepted as-is: reasons are intentionally not logged in replay (memory/noise). Documented with comment in `runner.py` | PR #156 |
| F4 | MINOR | `GridPlan.fta_resistance_used` never read | Documented with comment in `domain.py`: journal-only field, useful for result inspection but not consumed by strategy logic | PR #156 |
| F5 | MINOR | `analyse_multi_timeframe` docstring omits weight redistribution | Fixed: updated docstring in `structure.py` to document renormalisation | PR #156 |
| F7 | MINOR | Dispersion diluted by permanently-zero `structure_alignment` | Self-corrected by F1 fix | PR #154 |
| F9 | MINOR | `full-range-2019-2024` not in workflow UI options | Fixed: added to `backtest.yml` options list | PR #154 |
| F10 | MINOR | Fee stamp hardcoded in `run_nopool.py` | Fixed: stamp now reads `spec.fee_rate` dynamically | PR #156 |
| F13 | MINOR | §8.4 doc pseudocode differs from actual fix | Fixed: added NOTE comment in `2026-09-30-bob-v2-backtest-comparison.md §8.4` | PR #156 commit 3 |
| F14 | MINOR | Variant A doc references stale `bob/v2-integrated` branch | Fixed: updated to `main` | PR #156 |

**Final test count: 784 passed, 4 skipped** (was 773 before the audit session; 11 new tests added across two PRs).

---

## Detailed explanations for the non-obvious fixes

### F1 — Why `structure_alignment` was silently zero

**Root cause:** `MarketSignals` has a `structure_alignment` keyword-only field with a default of `0.0`. When `signals_for()` constructs `MarketSignals(...)` in `replay.py`, it passed all 6 required positional args and several keyword args (`data_quality`, `news_risk`, `emergency`, `observed_at`) but never passed `structure_alignment`. Python silently used the default.

**Why this was undetected:** There was no test that passed a non-zero `structure_alignment` through `signals_for()` and checked the output. The field defaulted silently — no crash, no warning. This is the exact gap F16 was also about.

**Effect:** The regime classifier was running with 10% of its signal budget permanently zeroed out. The trend weight was reduced from 0.35 to 0.25 (to make room for `structure_alignment`), but nothing went back in. All V2 backtest results prior to PR #154 were produced with a degraded classifier.

**Fix:** One line: `structure_alignment=inputs.structure_alignment` added to the gated `MarketSignals(...)` call in `replay.py:signals_for()`.

**Why the ungated path is correct:** The ungated `MarketSignals(0.0, 0.0, ...)` construction deliberately sets all signals to 0.0 — this is the baseline "no information" state used for non-gated runs. `structure_alignment=0.0` is correct there.

---

### F8 — Why the full-range fetch required a code fix first

**Root cause:** Binance's published 1m archives for `2020-02` (all three pairs: BTCUSDT, ETHUSDT, XRPUSDT) contain row 26556 with a malformed `close_ms` timestamp (`+32286ms` instead of the expected `+59999ms`). The open timestamp on that row is correctly aligned.

**Why this matters:** `fetch_dataset()` calls `fetch_file()` for every required file, and `fetch_file()` runs `read_archive()` which strictly validates `close_ms != open_ms + step - 1`. This raised `ArchiveParseError` and crashed the entire fetch before writing any manifest.

**Why the fix is in `fetch_dataset`, not in `parse_rows`:** The strict `parse_rows` check is used by the audit tool (`audit_rules`, `fix_closes`, `rule_outcome`) to detect and classify malformed rows. If `parse_rows` silently accepted truncated closes, the audit tool would no longer detect them. The audit and replay paths must stay separate. `2020-02` is already listed in `UNPARSED_MONTHS` in `audit_run.py` — the project already knows about it.

**Fix:** Added `_fetch_one()` as a wrapper around `fetch_file()` in `dataset.py`. It catches `ArchiveParseError` and records the entry as `status: "unparsed"` instead of re-raising. `fetch_dataset()` now calls `_fetch_one()` instead of `fetch_file()`. `_validate_manifest()` was updated to accept `"unparsed"` as a valid status (alongside `"ok"` and `"missing"`). `load_minutes()` already skips any entry where `status != "ok"`, so `2020-02` minutes are treated as a gap — the same as any missing month.

**The three corrupt files were deleted** from disk before the fetch ran (they had been previously downloaded with the bad content). The fetch re-downloaded them, found them still corrupt (Binance's archive is definitively bad for this month), recorded them as `"unparsed"`, and continued.

**Result:** 1,080 files processed. 78 daily zips per pair downloaded (2018-07 → 2024-12). `full-range-2019-2024.manifest.json` written. `daily_warmup_start = "2018-07"` added to the spec.

---

### F15 — Why the algebraic MTF tests were insufficient

**The problem with algebraic tests:** `test_all_bullish_gives_positive_alignment` asserts `(0.15 * 1 + 0.35 * 1 + 0.50 * 1) / 1.0 == 1.0` — this tests arithmetic, not code. A regression in `detect_swing_highs()`, `cluster_into_zones()`, or `classify_structural_trend()` that caused every sequence to return `StructuralTrend.RANGING` instead of `BULLISH` would still pass these tests because they never call `analyse_multi_timeframe()` with real bars.

**The new tests** construct deterministic bar sequences with known swing structure:

- `_bullish_bars()`: ascending zigzag (prices 100, 101, 105, 102, 108, 104, 112, 107, 115, 110, 118). With `swing_n=1`, bars at indices 2, 4, 6, 8, 10 are local peaks (confirmed swing highs, all ascending). Bars at 3, 5, 7, 9 are local troughs (confirmed swing lows, all ascending). `classify_structural_trend()` returns `BULLISH`.

- `_bearish_bars()`: descending mirror sequence. Returns `BEARISH`.

- Four tests: hourly-only bullish (+1.0), hourly-only bearish (−1.0), both hourly+daily bullish with `weekly=None` (renormalised to +1.0), mixed hourly-bullish/daily-bearish with `weekly=None` (−0.40 = `(0.15×1 + 0.35×−1) / 0.50`).

**Why weekly=None matters:** In the production code (`features.py` line 308), `weekly_bars` is always `None`. The weight renormalisation path (hourly 0.15 → 0.30, daily 0.35 → 0.70 when weekly absent) was only tested algebraically before. Now it is tested end-to-end with real bar sequences.

---

### F6 — Why the BULL regime description mattered

The backtest comparison document (`§8.1`) said: "The regime gate only opens a new grid when the regime is `RANGE`. `BULL` → no grid. Period."

This is wrong. `OpportunityScorer._REGIME_FIT[BULL] = 0.80` — BULL does not hard-block grids. What actually happens in a bull market is that `range_quality` collapses toward zero (because the market is trending, not ranging), so the composite opportunity score falls below `minimum_opportunity_score` before the regime fit factor even matters. The practical result is the same (no grid opens), but the mechanism is different.

**Why it matters for future feature work:** A "bull-mode" feature (e.g. Variant B: open asymmetric grids in BULL) needs to understand that the block is in `range_quality`, not in a hard regime check. Changing `_REGIME_FIT[BULL]` from 0.80 to 1.0 would not by itself enable grids in BULL — `range_quality` must also be addressed. An agent that read the original description would design the wrong solution.

---

## State of the codebase after all fixes

### What is correct and tested
- `structure_alignment` signal flows end-to-end from `FeatureEngine.at()` → `Inputs` → `signals_for()` → `MarketSignals` → `RegimeClassifier`
- FTA resistance flows end-to-end from `FeatureEngine.at()` → `Inputs` → `Frame` → `_open_grid()` → `GridBuilder.build()`
- FTA cap is RANGE-only: `_open_grid()` passes `fta_resistance=None` when regime is BULL or BEAR
- All 3 primary dataset specs have `daily_warmup_start` set and daily bars fetched
- `run_nopool.py` supports `--variant-a` and reads fees from the spec
- CI always checks out `main`; CI validates all spec files; CI runs Variant A toggle

### What is not yet done (second audit plan)
See `docs/reviews/2026-09-30-bob-second-audit-plan.md` and `docs/reviews/2026-09-30-bob-audit-2-closeout.md` for the second audit's status.

The key remaining work before V2 results can be trusted:
1. **Re-run V2 backtests** — all prior results were produced with `structure_alignment=0.0` (bug F1). Now that F1 is fixed, fresh results are needed on `long-bull-bear-2022` and `long-recovery-2023-2024`.
2. **Run Variant A** — first true measurement of the daily SMA50/SMA200 trend switch on both windows.

### Branch and PR state
- **PR #154** (merged at `48770195`): F1, F11, F12, F16, F17, F18, F19, F8 partial
- **PR #156** (open, branch `bob/audit-remediation-2026-09-30` at `8d75782`): F2, F3, F4, F5, F8 final, F6, F10, F13, F14, F15, and all second-audit fixes H1–H8, L1–L5
- **PR #157** (open): V2 backtest comparison task report

---

*— IBM Bob (owner's desktop session)*
