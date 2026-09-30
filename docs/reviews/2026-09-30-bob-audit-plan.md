# Comprehensive Codebase Audit Plan — 2026-09-30

Index: 2026-09-30: 40-step audit plan covering logic integrity, domain model, strategy rules, CI/CD, docs, cross-cutting conflicts, and test coverage.

**Written by:** Bob (IBM Bob, owner's desktop session)
**Status:** PLAN ONLY — awaiting owner approval before execution
**Scope:** Full codebase, all strategy logic, all documentation, all infrastructure, all rules and conventions
**Branch at time of writing:** `main` at `22c597d` (post all PR merges)

---

## Severity Classification Scheme

Every finding produced during execution will be tagged with one of:

| Severity | Definition |
|---|---|
| **CRITICAL** | Causes incorrect simulation results, data corruption, silent wrong answers, or will crash production. Must fix before any further backtest or development work. |
| **MAJOR** | Causes measurable behavioural deviation from documented intent, test coverage gap for core logic, or infrastructure failure that blocks correct runs. Fix before reserved window testing. |
| **MINOR** | Cosmetic inconsistency, documentation mismatch, default that could mask a bug but doesn't under current usage, or non-blocking technical debt. Fix in next cleanup pass. |
| **ADVISORY** | Observation that is not wrong today but creates future risk or confusion. Capture for awareness; no immediate action required. |

---

## Dimension 1 — Codebase Logic Integrity

### Step 1.1
- **Examining:** `structure_alignment` data flow end-to-end
- **Method:** Read `features.py:at()` (lines 287–318), `replay.py:signals_for()` (lines 140–165), `runner.py:_step()` classify call (line 506)
- **Hunting for:** Does `Inputs.structure_alignment` actually reach `MarketSignals.structure_alignment` in the gated path? In the ungated path, `signals_for()` constructs `MarketSignals(0.0, 0.0, ...)` directly — is `structure_alignment` passed or silently dropped to its default 0.0?

### Step 1.2
- **Examining:** `fta_resistance` data flow end-to-end
- **Method:** Trace `Inputs.fta_resistance` → `Frame.fta_resistance` (replay.py line 449) → `_open_grid()` (runner.py lines 915–928)
- **Hunting for:** Is the value correctly passed positionally in `Frame(...)` at replay.py line 449? Verify the positional argument order matches the `Frame` dataclass field order. Confirm `_open_grid` uses `regime` correctly for the RANGE-only FTA gate.

### Step 1.3
- **Examining:** `Frame` constructor positional arguments in replay.py
- **Method:** Read `Frame` dataclass definition (runner.py lines 140–164), compare field order against the call site `Frame(quote, signals, candidate, inputs.fair_value, atr, True, epoch, trend, inputs.fta_resistance)` (replay.py line 449)
- **Hunting for:** Positional argument mismatch — a field inserted in the wrong position would silently assign the wrong value to a field (e.g. `fta_resistance` landing in `epoch`'s slot).

### Step 1.4
- **Examining:** `_open_grid` FTA-cap RANGE-only guard (the fix from commit `7395b6a`)
- **Method:** Read runner.py lines 906–928 in full; verify the `regime` parameter default (`None`) and the condition `regime is None or regime.regime == MarketRegime.RANGE`
- **Hunting for:** When `regime is None` (the default), the FTA cap is applied unconditionally — is this the intended behaviour? Is `regime` always passed from `_step()` at the call site? Check what value `regime` holds if the classify call raises before reaching `_open_grid`.

### Step 1.5
- **Examining:** `signals_for()` ungated path — structure_alignment dropped
- **Method:** Read replay.py lines 140–165, compare `MarketSignals(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, ...)` against `MarketSignals` field list in domain.py
- **Hunting for:** The ungated `MarketSignals` construction uses positional args for 5 signals + adx. `structure_alignment` is a keyword-only field with default 0.0. Confirm it is actually 0.0 in ungated (correct, by design) vs whether the positional count matches the required positional fields.

### Step 1.6
- **Examining:** `GridBuilder.build()` — FTA cap boundary conditions
- **Method:** Read grid.py lines 89–106; trace all four edge cases (None, above upper, below/equal lower, exactly at upper)
- **Hunting for:** Off-by-one: condition is `lower < fta_resistance <= upper`. When `fta_resistance == lower` exactly, no cap — is this correct? When all levels are capped to the same value (FTA just above lower), does the `len(set(levels)) != len(levels)` check in `_open_grid` correctly reject the degenerate grid?

### Step 1.7
- **Examining:** `_structure_cache` invalidation logic
- **Method:** Read features.py lines 287–318; trace what happens when `_hourly_candles` is empty (no daily warmup) vs populated
- **Hunting for:** Cache key is `p` (pair hourly index). If `p` does not advance (e.g. data gap), the cache returns stale structure. If `p` decreases (impossible given sorted candles, but verify), cache would never invalidate. Also: `_structure_cache` is initialised as `None` in `__init__` but the type is not annotated — verify it doesn't collide with the `(p, alignment, fta)` tuple check.

### Step 1.8
- **Examining:** Swing detection look-ahead constraint in `structure.py`
- **Method:** Read structure.py (navigating encoded content) to find `detect_swing_highs`/`detect_swing_lows` — specifically: the last `n` bars are never classified because they lack the forward confirmation window
- **Hunting for:** Does the 500-bar window cap in `features.py` interact badly with the swing detection tail? With `n=3` (default), the last 3 bars of the 500-bar window are unconfirmed. This is correct. But: if the window shrinks below `2n+1` bars (e.g. early in warmup), does `analyse_multi_timeframe` handle None gracefully?

### Step 1.9
- **Examining:** `analyse_multi_timeframe` weights when weekly bars are None
- **Method:** Search structure.py for the multi-timeframe weighting logic (hourly: 0.15, daily: 0.35, weekly: 0.50)
- **Hunting for:** Weekly bars are always `None` (features.py line 308). If the function does not redistribute the 0.50 weekly weight to the other timeframes when weekly is absent, the alignment score is permanently compressed to at most ±0.50, and the effective weight of `structure_alignment` in the regime classifier is 0.05 rather than 0.10. This is a silent signal dilution.

### Step 1.10
- **Examining:** `TrendSchedule.at()` — lookahead prevention
- **Method:** Read trend_switch.py `effective_state()` and `at()` (lines 176–227); trace what timestamp it reads and what "yesterday" means in UTC
- **Hunting for:** If `at(when_ms)` reads the bar whose close is "before `when_ms`", it should return the prior UTC day's classification. Confirm there is no off-by-one where the current day's incomplete bar is returned.

### Step 1.11
- **Examining:** Variant A Down deadline logic
- **Method:** Read runner.py lines 600–650; trace `account.down_since` assignment, `DOWN_DEADLINE_SECONDS`, and the `trend_due` cancellation
- **Hunting for:** `trend_due` is computed once per frame. The deadline cancels ALL resting orders (line 609: `account.orders.clear()`). But `match()` is called immediately after (line 610). Confirm `match()` does not re-place the cancelled buys within the same frame — if `recycle=True` and the account looks flat, a new grid could open on the very frame that should be exiting.

### Step 1.12
- **Examining:** Regime gate and grid open — the BULL/BEAR gate interaction
- **Method:** Read runner.py `_step()` lines 590–695, focusing on the `score.eligible` → `account.pause` → new grid path
- **Hunting for:** In `BULL` regime, `score.eligible` is False (gate refuses). The account enters `pause`. A new grid is never opened. This is correct design. But: confirm that `account.pause` is also set when `score.eligible` is False AND `account.halt` is False — not just when the account is already paused.

---

## Dimension 2 — Domain Model and Data Contracts

### Step 2.1
- **Examining:** All fields in `MarketSignals` — used vs populated downstream
- **Method:** `grep -r "MarketSignals" src/` and `grep -r "signals\." src/` to find every field read site; cross-reference against every field defined in domain.py
- **Hunting for:** Any field defined on `MarketSignals` that is populated but never read (dead field), or read but always assigned its default (never actually used). In particular: `news_risk` is always 0.0 in replay.py line 162 ("ABSENT") — is it used anywhere in the risk or regime path?

### Step 2.2
- **Examining:** `Inputs` dataclass fields — populated vs consumed
- **Method:** Trace every field in `Inputs` from where it is computed (`features.py:at()`) to where it is consumed (replay.py `signals_for`, `candidate_for`, `Frame` construction)
- **Hunting for:** Fields computed but never placed into the `Frame` or `MarketSignals`. Specifically: `market_quality`, `pair_quality`, `minute_quote_volume` — are all used? `structure_alignment` is on `Inputs` but must travel via `MarketSignals` to reach the regime classifier — confirm this chain.

### Step 2.3
- **Examining:** `RegimeAssessment` fields — used vs produced
- **Method:** `grep -r "RegimeAssessment\|regime\." src/` to find read sites; check `score`, `confidence`, `reasons`, `input_quality_ok` are all consumed
- **Hunting for:** Fields on `RegimeAssessment` that are produced by `RegimeClassifier.classify()` but never read downstream.

### Step 2.4
- **Examining:** Optional field `fta_resistance: float | None` on `Frame` — payload omission
- **Method:** Read `Frame.payload()` (runner.py lines 155–164); confirm omitting `fta_resistance` from the journal when None does not break any downstream reader
- **Hunting for:** If any code reads `frame_dict["fta_resistance"]` without a `.get()` default, it would KeyError when structure is unavailable.

### Step 2.5
- **Examining:** `GridPlan.fta_resistance_used` — is it read anywhere?
- **Method:** `grep -r "fta_resistance_used" src/ tests/`
- **Hunting for:** Field added to `GridPlan` in PR #148 but never read — it would be a dead field contributing no value but adding to the serialisation surface.

---

## Dimension 3 — Strategy Rules and Configuration

### Step 3.1
- **Examining:** Regime classifier weight sum invariant
- **Method:** Sum `RegimeClassifier._WEIGHTS` values: `0.25 + 0.20 + 0.15 + 0.15 + 0.15 + 0.10`
- **Hunting for:** Weights must sum exactly to 1.0. Any floating-point rounding that causes the sum to deviate from 1.0 would affect the regime score scale and break the `bull_threshold=0.35` boundary comparisons.

### Step 3.2
- **Examining:** `RegimeThresholds` defaults vs the new 6-signal weight distribution
- **Method:** Check `RegimeThresholds` defaults (regime.py lines 30–63) against the updated `_WEIGHTS`. Specifically: `range_score_limit=0.25` and `bull=0.35`
- **Hunting for:** With 6 signals each averaging moderate positive values, does the range score limit still create a reachable range regime? With `trend` weight reduced from 0.35 to 0.25, a strong-trend-only signal set that used to score above 0.35 may now score below it, changing regime boundaries.

### Step 3.3
- **Examining:** `daily_warmup_start` missing from two dataset specs
- **Method:** Read `long-bull-bear-2022.toml` and `long-recovery-2023-2024.toml`
- **Hunting for:** Both specs lack `daily_warmup_start`. This means `daily_bars=None` in `FeatureEngine`, which means `structure_alignment=0.0` always and `fta_resistance=None` always for these two windows. The V2 features are silently inactive for the two most important test windows. The Variant A backtest cannot run on these windows at all (it raises `ValueError: variant A needs the pair's daily history`).

### Step 3.4
- **Examining:** `full-range-2019-2024.toml` — listed in `backtest.yml` options or not?
- **Method:** Read `backtest.yml` spec choice list; compare to files in `config/datasets/`
- **Hunting for:** `full-range-2019-2024` is in the filesystem but NOT listed as a workflow option. Also: it has no `daily_warmup_start` and a comment saying to add it after fetching. If someone runs it via CLI without daily data, Variant A will crash.

### Step 3.5
- **Examining:** Parameters defined in multiple places with different values
- **Method:** `grep -r "0.001\|0.0009\|taker_fee\|maker_fee" config/ scripts/ .github/`
- **Hunting for:** `run_nopool.py` hardcodes the output stamp as `-m0.001-t0.001` regardless of what fees were actually used. If fees are overridden, the stamp is wrong. Also: `backtest.yml` does not pass `--maker-fee` or `--taker-fee` to `run_nopool.py` — there is no fee override mechanism in `run_nopool.py`.

### Step 3.6
- **Examining:** `SimulationPolicy` default vs Variant A
- **Method:** Read `__main__.py` lines 217–220; check how policy is passed to `run_job` and then to `replay()`
- **Hunting for:** When `--variant-a` is not passed, `policy=None`. `run_job` receives `policy=None` and passes it to `replay()`. `replay()` receives `None` and creates `PaperSimulator` with `SimulationPolicy()` defaults. Confirm that `policy=None` in `run_job` does not bypass the policy entirely — or that `run_nopool.py` correctly uses `None` for standard runs.

### Step 3.7
- **Examining:** `run_nopool.py` — no `--variant-a` support
- **Method:** Read run_nopool.py lines 44–56
- **Hunting for:** `run_nopool.py` always calls `run_job(..., policy=None)` with no way to pass `policy=SimulationPolicy(trend_switch=True)`. Variant A can only be triggered from the CLI (`python -m crypto_grid_bot.backtest run --variant-a`), not from `run_nopool.py`. Since CI uses `run_nopool.py`, **Variant A cannot run in CI**.

---

## Dimension 4 — Infrastructure and CI/CD

### Step 4.1
- **Examining:** `backtest.yml` — hardcoded branch ref
- **Method:** Read `.github/workflows/backtest.yml` line 28
- **Hunting for:** The workflow checks out `bob/v2-integrated`. That branch is now behind `main` (all PRs merged). Any run will use the pre-merge code, not the current `main`. This is the most immediately impactful infrastructure finding.

### Step 4.2
- **Examining:** `backtest.yml` — artifact upload path
- **Method:** Read backtest.yml lines 47–53; trace what `run_nopool.py` actually writes vs what the upload action expects
- **Hunting for:** `run_nopool.py` writes to `data/backtests/<spec.name>/<stamp>/`. The upload action expects `data/backtests/${{ github.event.inputs.spec }}/`. If `spec.name` in the TOML differs from `github.event.inputs.spec` (the CLI argument), the artifact path won't match and the upload will be empty.

### Step 4.3
- **Examining:** `backtest.yml` — `full-range-2019-2024` not in options
- **Method:** Read backtest.yml `options` list; compare to `config/datasets/` directory listing
- **Hunting for:** `full-range-2019-2024.toml` exists but is absent from the workflow options. It cannot be triggered via the UI. If someone adds it to options without fetching daily bars first, Variant A will crash mid-run.

### Step 4.4
- **Examining:** `run_nopool.py` — path resolution when called from CI
- **Method:** Read run_nopool.py lines 26–33; check `SPEC_PATH`, `CONFIG_PATH`, `DATA_DIR` — all use relative paths
- **Hunting for:** Relative paths assume the working directory is the repo root. GitHub Actions `run:` steps default to the workspace root, so this should be correct — but if the `cd` ever changes, all paths break silently.

### Step 4.5
- **Examining:** Python version consistency
- **Method:** Read `backtest.yml` python-version; `grep -r "python_requires\|python-version" pyproject.toml setup.cfg`
- **Hunting for:** CI uses Python 3.12. If `pyproject.toml` specifies a different minimum, there may be syntax or API mismatches.

---

## Dimension 5 — Documentation vs Reality

### Step 5.1
- **Examining:** `2026-09-30-bob-v2-backtest-comparison.md` §8.4 FTA cap diagnosis vs actual fix
- **Method:** Read §8.4 of the backtest comparison doc; compare the proposed fix to the actual implementation in runner.py lines 911–919
- **Hunting for:** The doc proposes `fta = frame.fta_resistance if signals_regime == MarketRegime.RANGE else None`. The actual code uses `regime is None or regime.regime == MarketRegime.RANGE`. Confirm whether the `regime is None` arm was documented and whether it represents the correct fallback.

### Step 5.2
- **Examining:** `2026-09-29-bob-market-structure-implementation.md` — multi-timeframe weights
- **Method:** Read the implementation doc's weight table; compare to actual `analyse_multi_timeframe` weights in structure.py
- **Hunting for:** Doc states hourly: 0.15, daily: 0.35, weekly: 0.50. Weekly is never loaded (features.py line 308). If the code does not redistribute weights, the documented behaviour (full multi-timeframe) never occurs and the doc is misleading.

### Step 5.3
- **Examining:** `2026-09-29-bob-fta-sell-target-integration.md` — `Index:` line requirement
- **Method:** Read the doc; check if `Index:` line is present (PR #151 body says it was added)
- **Hunting for:** Missing `Index:` line causes `check_reports.py` to flag the file as invalid.

### Step 5.4
- **Examining:** `2026-09-29-bob-variant-a-v2-integration.md` — describes Variant A integration
- **Method:** Read the doc; compare described integration steps to what actually exists in `__main__.py` and `replay.py`
- **Hunting for:** Outdated claims — e.g. if the doc says "daily bars are fetched from X" but the actual fetch path differs.

### Step 5.5
- **Examining:** `2026-09-30-owner-v2-master-strategy-proposal.md` §11 PR merge order
- **Method:** Read §11; compare to the actual merge order just executed
- **Hunting for:** §11 specifies `#146 → #147 → (#148 + #150 in either order) → #149 → #151`. The actual order was #146, #147, #148, then #150 (after rebase), then #149, then #151. Confirm the doc's merge order was respected.

### Step 5.6
- **Examining:** `AGENT_HANDOFF.md` — current branch and latest commit references
- **Method:** Read `docs/AGENT_HANDOFF.md`
- **Hunting for:** The handoff doc likely still references `bob/v2-integrated` as the active branch and `7395b6a` as the latest commit. After all merges, `main` at `22c597d` is the correct reference.

---

## Dimension 6 — Cross-Cutting Conflicts

### Step 6.1
- **Examining:** Post-merge integration conflict — `structure_alignment` signal path
- **Method:** Trace the complete signal path: `FeatureEngine.at()` → `Inputs.structure_alignment` → `signals_for()` → `MarketSignals` → `RegimeClassifier.classify()`
- **Hunting for:** `signals_for()` in replay.py constructs `MarketSignals` **without** passing `structure_alignment`. The field has a default of 0.0, so no crash — but the structure signal is **permanently zeroed out** in the actual backtest loop, even when `features.py` correctly computed it. This is the most likely integration-level bug introduced by merging #150 (signal added to domain + classifier) and #151 (wiring) as separate operations.

### Step 6.2
- **Examining:** Interaction between FTA cap (PR #148) and structure_alignment weight change (PR #150)
- **Method:** Determine whether both changes are active simultaneously and whether they conflict
- **Hunting for:** PR #148 adds FTA cap to GridBuilder. PR #150 reduces trend weight from 0.35→0.25. Both are now in main. The `long-bull-bear-2022` backtest comparison was run on `bob/v2-integrated` at commit `9abb1f3` which had both. The FTA fix was at `7395b6a`. Verify that the `run_nopool.py` stamp of `-m0.001-t0.001` is not used to look up results from a different fee level.

### Step 6.3
- **Examining:** `run_nopool.py` fee hardcoding vs `run_job()` fee source
- **Method:** Read `run_job()` signature in jobs.py; trace where fees come from when `fees=None`
- **Hunting for:** `run_job(..., fees=None)` reads fees from the spec TOML (all specs have `fee_rate = "0.001"`). `run_nopool.py` hardcodes `-m0.001-t0.001` in the output stamp. These are consistent today — but if a spec uses different fees, the stamp is wrong. Not a current bug, but a future trap.

### Step 6.4
- **Examining:** `_open_grid` called only when `score.eligible` is True (gated) or always (ungated)
- **Method:** Read runner.py lines 590–695 for the full condition chain leading to `_open_grid`
- **Hunting for:** In the gated path, `score.eligible` must be True. In the ungated path, `candidate_for()` returns all-1.0 metrics, so `score.eligible` is always True. Confirm that `_open_grid` is never called with a `BULL` or `BEAR` regime on the gated path — i.e. that the `score.eligible` gate and the regime gate are consistent.

### Step 6.5
- **Examining:** Merge history — does PR #149 (task doc) add a file that was externally deleted?
- **Method:** Check whether `docs/tasks/2026-09-29-bob-structure-backtest-comparison.md` exists on current `main`
- **Hunting for:** The file was externally deleted in the workspace, but PR #149 added it. Since we merged via GitHub, the file should be in `main`'s tree even if the local workspace doesn't have it.

---

## Dimension 7 — Test Coverage and Correctness

### Step 7.1
- **Examining:** `test_regime.py` — tests updated for 6-signal _WEIGHTS
- **Method:** Read test_regime.py in full; verify test values are consistent with the new weights (trend 0.25, not 0.35)
- **Hunting for:** Tests that were updated during PR #150 to accommodate the new weights but may have been updated incorrectly (e.g. `x*0.90` in the boundary test — does this match the actual score formula for 5 identical signals + structure_alignment=0.0?).

### Step 7.2
- **Examining:** `test_structure.py` — coverage of `analyse_multi_timeframe` with weekly=None
- **Method:** Read test_structure.py `TestAnalyseMultiTimeframe` methods
- **Hunting for:** Tests for `test_all_none_returns_zero_alignment` and `test_single_timeframe_alignment_matches_trend` — do any tests pass `weekly_bars=None` and verify the weight redistribution is correct? Or do all tests pass all three timeframes?

### Step 7.3
- **Examining:** `test_grid.py` — FTA cap tests
- **Method:** Read test_grid.py FTA tests in full (5 new tests)
- **Hunting for:** Test `test_fta_within_grid_caps_top_levels` uses `fair_value=1.0, atr=0.1 → lower=0.8, upper=1.2`. Verify this is consistent with `GridBuilder.__init__` params used in `setUp` (range_atr_multiple=2 → half_range=0.2 → lower=0.8, upper=1.2 ✓). Check that the test doesn't use the same `_std` dict that the `setUp` builds, and that the builder params in `setUp` match.

### Step 7.4
- **Examining:** Missing test: `signals_for()` with `structure_alignment`
- **Method:** `grep -r "signals_for\|structure_alignment" tests/`
- **Hunting for:** No test verifies that `structure_alignment` survives the `signals_for()` path into `MarketSignals`. If Step 6.1 finds that structure_alignment is silently zeroed, this is the test gap that allowed it.

### Step 7.5
- **Examining:** Missing test: `_open_grid` with RANGE vs BULL/BEAR FTA gate
- **Method:** `grep -r "_open_grid\|fta.*regime\|regime.*fta" tests/`
- **Hunting for:** No test verifies that the FTA cap is disabled in BULL/BEAR but enabled in RANGE. The fix in `7395b6a` is untested at the integration level.

### Step 7.6
- **Examining:** `test_backtest_replay.py` — Frame construction test
- **Method:** Read test_backtest_replay.py; check if any test constructs a `Frame` with `fta_resistance` populated and verifies it is passed to `_open_grid`
- **Hunting for:** No integration test covering the full `Inputs → Frame → _open_grid → GridBuilder.build(fta_resistance=...)` chain.

### Step 7.7
- **Examining:** `test_trend_switch.py` — lookahead prevention
- **Method:** Read test_trend_switch.py; check for tests on `effective_state()` and `starts_down_sequence()`
- **Hunting for:** Confirm there is a test that `effective_state()` returns UNAVAILABLE for a bar whose day equals today (not yesterday).

### Step 7.8
- **Examining:** Overall test run — verify 773 tests still pass on current main
- **Method:** Inspect the latest GitHub Actions run or note that no test run has been triggered against `main` post-merge
- **Hunting for:** The 773-test count was from `bob/v2-integrated`. After rebasing and squash-merging, the code on `main` may differ subtly (especially the `backtest.yml` conflict resolution that kept the old workflow format). No CI run has validated `main`.

---

## Execution Order

The steps above should be executed in this order to maximise finding propagation:

1. Steps 1.3, 1.2 — Frame construction correctness (foundational data-flow)
2. Step 6.1 — structure_alignment silent zeroing (likely critical)
3. Steps 1.1, 1.4, 1.5 — remaining signal flow
4. Steps 2.1–2.5 — domain model audit
5. Steps 1.6–1.12 — remaining logic integrity
6. Steps 3.1–3.7 — strategy and configuration
7. Steps 4.1–4.5 — infrastructure (start with 4.1 — the branch ref bug)
8. Steps 5.1–5.6 — documentation vs reality
9. Steps 6.2–6.5 — remaining cross-cutting
10. Steps 7.1–7.8 — test coverage

**Total steps: 40**

---

*Plan written 2026-09-30. Awaiting owner approval before execution in agent mode.*

— IBM Bob (owner's desktop session)
