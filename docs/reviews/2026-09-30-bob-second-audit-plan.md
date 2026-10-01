# Second Comprehensive Audit — Remediation Plan

Index: 2026-09-30: Second full codebase audit, post-PR-#154 merge. New findings across strategy logic, backtest methodology, CI/CD, configuration, and agent documentation. Prioritized remediation plan in four tiers.

**Written by:** Bob (IBM Bob, owner's desktop session)
**Audit base:** `main` at `48770195` (post PR #154 merge)
**Session context:** The first audit (plan `2026-09-30-bob-audit-plan.md`, findings `2026-09-30-bob-audit-findings.md`, session report `2026-09-30-bob-audit-session-report.md`) fixed 5 critical issues. This second audit is a fresh sweep of the whole codebase — strategy, infrastructure, CI/CD, config, and all agent-facing documentation — looking for what the first audit did not cover.

---

## Scope

Files audited in full:
- All source files under `src/crypto_grid_bot/` (strategy, backtest, simulation, config, domain)
- All scripts under `scripts/`
- All CI/CD workflows under `.github/workflows/`
- All dataset specs and manifests under `config/datasets/`
- `config/default.toml`
- All agent-facing documentation: `docs/START_HERE.md`, `docs/AGENT_HANDOFF.md`, `docs/ROADMAP.md`, `docs/EXPERIMENT_SPEC_V1.md`, `docs/BACKTEST_METHOD.md`, `docs/tasks/README.md`, `docs/reviews/2026-09-30-bob-audit-session-report.md`, `docs/reviews/2026-09-30-bob-audit-findings.md`

---

## Findings

### CRITICAL findings

---

#### C1 — `full-range-2019-2024.toml` still missing `daily_warmup_start` (F8 partially fixed)

**File:** `config/datasets/full-range-2019-2024.toml`
**Status of prior finding F8:** Partially fixed. `daily_warmup_start = "2021-07"` was added to `long-bull-bear-2022.toml` and `daily_warmup_start = "2022-10"` was added to `long-recovery-2023-2024.toml`. But `full-range-2019-2024.toml` still lacks `daily_warmup_start`. The comment in that file says `# Re-add daily_warmup_start = "2018-07" after running fetch`.

**Why it matters:**
- Without `daily_warmup_start`, `daily_bars=None` for `FeatureEngine` on this spec.
- `fta_resistance` is always `None` for all runs on this window; the V2 FTA signal is completely inactive.
- Variant A raises `ValueError: variant A needs the pair's daily history` for this spec.
- The 5.5-year window is the broadest available development window — V2 features are silently absent from any run on it.

**Fix required:**
1. Fetch daily bars: `python -m crypto_grid_bot.backtest fetch --spec config/datasets/full-range-2019-2024.toml --data-dir data`
2. Add `daily_warmup_start = "2018-07"` to `config/datasets/full-range-2019-2024.toml` (the comment in the file already documents this exact value).

---

#### C2 — No manifests exist for any dataset spec

**Files:** `config/datasets/` (all `.manifest.json` files)
**Current state:** `glob("config/datasets/*.json")` returns nothing. No manifest files exist on disk in the workspace.

**Why it matters:**
- `run_nopool.py` calls `load_manifest(manifest_path(SPEC_PATH))` at startup — this will raise `FileNotFoundError` immediately on any run.
- `run_job()` in `jobs.py` calls `load_manifest(manifest_path(spec_path))` — same fatal failure.
- No backtest of any kind can run locally until manifests are fetched.
- The prior audit session report (`2026-09-30-bob-audit-session-report.md`) listed commands to re-run backtests, but those commands require manifests that do not exist on the local workspace.

**Why manifests may be missing:** Manifests are created by `python -m crypto_grid_bot.backtest fetch --spec ...`. They are not committed to the repository (correctly — they record data download state). But they must exist locally before any run. The workspace `data/` directory presumably has no fetched data and no manifests.

**Fix required:**
For each spec needed for the next run:
```bash
python -m crypto_grid_bot.backtest fetch --spec config/datasets/long-bull-bear-2022.toml --data-dir data
python -m crypto_grid_bot.backtest fetch --spec config/datasets/long-recovery-2023-2024.toml --data-dir data
python -m crypto_grid_bot.backtest fetch --spec config/datasets/full-range-2019-2024.toml --data-dir data
```
These also download all required klines (1m, 1h, 1d where declared). The manifest is then written to `config/datasets/<spec>.manifest.json`.

**Note:** This is an operational blocker, not a code defect. The code correctly errors on missing manifests. But no agent handoff has explicitly called out that the local workspace is in a state where no run can proceed without this step first.

---

#### C3 — `verify-2024h1.toml` and `practice-2022.toml` breadth basket mismatch vs `long-*` specs

**Files:** `config/datasets/verify-2024h1.toml`, `config/datasets/practice-2022.toml`, `config/datasets/long-bull-bear-2022.toml`, `config/datasets/long-recovery-2023-2024.toml`

**Issue:**
`verify-2024h1.toml` has:
```toml
breadth_basket = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"]
```
(10 symbols including ADAUSDT)

`long-bull-bear-2022.toml` and `long-recovery-2023-2024.toml` have:
```toml
breadth_basket = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"]
```
(9 symbols, no ADAUSDT)

**Why it matters for backtest correctness:**
The breadth score is computed as `2 * sum(votes) / len(votes) - 1`. A different basket size changes the breadth vote count normalization. If ADAUSDT was included in verify-2024h1 because it is one of the *traded* symbols (for a 2-pair verification window), its presence in the breadth basket adds an additional vote that is directionally correlated with its own traded outcome. Across different specs, regime decisions during overlapping evaluation windows (2024-01 to 2024-06) will differ because the breadth calculation uses different symbols and different normalizations.

**Impact:** Results from `verify-2024h1` and `long-recovery-2023-2024` cannot be directly compared over their 6-month overlap: the regime classifier sees a different breadth signal in each.

**Severity assessment:** This may be intentional (the `verify-2024h1` spec was built for "chronology/accounting verification", not performance comparison) — but it is undocumented and could mislead an agent comparing runs across windows. The `ADAUSDT` addition to the basket when it is also a traded symbol is particularly worth flagging: it creates a correlation between the breadth signal and the pair being traded.

**Fix required:**
Document the basket difference explicitly in `verify-2024h1.toml`'s `purpose` field, or align baskets if comparability across windows is desired. Owner decision required: is the verify-2024h1 basket intentionally different?

---

### HIGH findings

---

#### H1 — `run_nopool.py` fee stamp is hardcoded and describes taker fee as "0.001" when taker fee is actually derived from the spec

**File:** `scripts/run_nopool.py`, line 69 and lines 81–82

**Issue:**
```python
stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-m0.001-t0.001" + _variant_suffix
...
"fees": {"maker": "0.001", "taker": "0.001"},
```

The `run_job()` function receives `fees=None`, which causes it to fall back to `(spec.fee_rate, None)`. With `taker=None`, `rules_for()` receives `taker_fee=None`, which causes `MarketRules` to use `taker_fee_rate = maker` (the maker fee). So the taker fee is correctly derived from the spec. However, the output document hardcodes `"taker": "0.001"` as a literal string regardless of what the spec contains. If a spec ever uses a different `fee_rate`, the output document will be wrong — the stamp and the `fees` field in `results.json` will not match what was actually used.

**More importantly:** the stamp suffix `-m0.001-t0.001` is used as part of the output directory name. This means output directories will always say `m0.001-t0.001` even if fees were different, making it impossible to distinguish results from different fee configurations just from the path.

**Fix required:**
Read the fee from the spec dynamically:
```python
maker_fee = str(spec.fee_rate)
stamp = ... + f"-m{maker_fee}-t{maker_fee}" + _variant_suffix
"fees": {"maker": maker_fee, "taker": maker_fee},
```

---

#### H2 — `quality.yml` does not run `mypy` before `pytest` — type errors in test files go undetected until runtime

**File:** `.github/workflows/quality.yml`, lines 29–33

**Current order:**
```yaml
- run: ruff check .
- run: ruff format --check .
- run: mypy src scripts
- run: pytest
```

`mypy` is run only on `src scripts`, not on `tests/`. Type errors in test files (wrong argument types, missing parameters) are not caught by the type checker. The test suite has 38 test files with complex fixture setup. A type error in a test helper could produce a passing test that is measuring the wrong thing.

**Fix required:**
Either add `tests` to the mypy scope (`mypy src scripts tests`) or document why tests are excluded from type checking. Excluding tests from mypy is a common and defensible choice, but it should be documented.

---

#### H3 — `bob/task-2026-09-29-bob-structure-backtest-comparison` branch exists on origin with no PR

**Source:** Session history (conversation summary) and git status showing `bob/audit-fixes-2026-09-30` as the current branch.

**Issue:** The task report branch `bob/task-2026-09-29-bob-structure-backtest-comparison` was created by the Bob task runner and was noted in the prior session as "exists, needs a PR opened." As of the current session start, no PR has been confirmed open for this branch. Per `docs/tasks/README.md`: "a 'Bob task report ready' issue means a report branch waits for its PR. Open the PR, and let the merge close the issue."

**Why it matters:**
- An unmerged task report leaves its `Index:` line out of the handoff index that `check_reports.py --index` builds. Future agents will not see that report when sweeping the index.
- The report documents V2 backtest comparison results. If those results are referenced from documents on `main` but the report itself is not on `main`, any agent that reads the reference but cannot find the file will be confused.

**Fix required:**
Open a PR for `origin/bob/task-2026-09-29-bob-structure-backtest-comparison` targeting `main`. The PR description should note the report's `Index:` line.

---

#### H4 — `docs/reviews/2026-09-30-bob-audit-session-report.md` references the wrong merge SHA in its header

**File:** `docs/reviews/2026-09-30-bob-audit-session-report.md`, line 8

**Issue:**
The session report states:
> **Base:** `main` at `22c597d` (post PR merges #146–#151)

But the fixes from this session were merged as PR #154 at SHA `48770195`. The base SHA `22c597d` is correct for what was audited, but there is no mention that the fixes now live at `48770195` on `main`. Any agent reading this report will see the correct base for the audit but will not know what SHA the fixes are actually at without separately checking GitHub.

**Fix required:**
Add to the session report's header section: "Fixes merged as PR #154 at SHA `48770195cf162f870d689de45c029e68dedcb820`."

---

#### H5 — `full-range-2019-2024` is not in the `quality.yml` CI gate — a break only appears when running backtest.yml

**Files:** `.github/workflows/quality.yml`, `.github/workflows/backtest.yml`

**Issue:**
`quality.yml` runs `--self-check` and `--paper-demo` but does not validate any dataset spec. If a dataset spec file becomes syntactically invalid, has a missing required field, or contradicts the code's expectations, this failure is only visible when `backtest.yml` is manually triggered. Routine CI pushes will be green even if the spec file is broken.

**Fix required:**
Add a CI step in `quality.yml` that validates all dataset spec files using `load_spec()` for each `.toml` in `config/datasets/`. This is a pure parse/validate call — it does not require fetched data and runs instantly:
```bash
python -c "
from pathlib import Path
from crypto_grid_bot.backtest.dataset import load_spec
for p in sorted(Path('config/datasets').glob('*.toml')):
    load_spec(p)
    print(f'OK: {p.name}')
"
```

---

#### H6 — Variant A `effective_state()` returns `UNAVAILABLE` when the daily bar is from two days ago — this is stricter than documented

**File:** `src/crypto_grid_bot/simulation/trend_switch.py`, lines 176–182

**Code:**
```python
def effective_state(signal: TrendSignal | None, observed_at: str) -> str:
    if signal is None:
        return UNAVAILABLE
    yesterday = timestamp(observed_at).date() - timedelta(days=1)
    return signal.state if signal.day == yesterday.isoformat() else UNAVAILABLE
```

**Issue:**
The function only accepts a signal from exactly "yesterday" (the day before the observation). If daily bars are delayed by even one day (e.g., Binance takes more than 24 hours to publish a day's bar), the state becomes `UNAVAILABLE`. In backtest replay, this means any day where the daily bar for `d-1` was not present in the archive will gate as `UNAVAILABLE`, and no grid can open.

**Why this matters for backtest results:**
The `MINIMUM_DAILY_WARMUP = 200` check in `replay.py` ensures 200 days exist before evaluation. But `effective_state()` being strict means that if any single daily bar is missing during evaluation (an outage day), the entire observation is treated as `UNAVAILABLE` for Variant A gating. The bot will remain in cash on those days.

**Documentation gap:** `BACKTEST_METHOD.md` does not document that a single missing daily bar causes `UNAVAILABLE` for Variant A, or how this interacts with the cross_check_daily completeness report.

**Fix required (documentation):**
Add a note to `BACKTEST_METHOD.md` and `EXPERIMENT_SPEC_V1.md §3 A` stating that Variant A gates as `UNAVAILABLE` on any day where the previous daily bar is missing from the archive, and that this is conservative by design.

---

#### H7 — `docs/tasks/README.md` task status table is out of date post-PR-#154

**File:** `docs/tasks/README.md`

**Issue:**
The tasks table shows `P8 archives for G and H` as "Awaiting Codex's review" and two other tasks as "Queued." These tasks appear to predate the PR #154 audit work and may no longer be the most relevant next steps. The table does not reflect:
- That a comprehensive audit was completed on 2026-09-30
- That all 5 critical findings from the first audit have been fixed
- That the next required actions are: open PR for the structure-backtest-comparison report, fetch daily bars, re-run V2 backtests

The table functions as the "current task state" for Bob, so it being stale causes agents to act on outdated priorities.

**Fix required:**
Update `docs/tasks/README.md` to add a new entry for the audit session work and reflect the current status of pending tasks. (This requires its own PR and review.)

---

#### H8 — `EXPERIMENT_SPEC_V1.md` states spec v1 is a "DRAFT" but the acceptance criteria (C1–C6) are documented as frozen (owner decision 2026-09-24)

**File:** `docs/EXPERIMENT_SPEC_V1.md`

**Issue:**
The document header says "DRAFT" but:
- C1–C6 were frozen by owner decision 2026-09-24 (documented in `docs/reviews/2026-09-24-owner-decisions-confirmed.md`)
- The ROADMAP says "spec v1 is still a draft and is not yet frozen"

This creates a contradictory state for agents: the criteria are frozen but the spec is still a draft. The distinction matters because "frozen criteria" and "frozen spec" are different: a spec could still be a draft (not all sections finalized) while its acceptance criteria are already locked. The current state is ambiguous — an agent reading only `EXPERIMENT_SPEC_V1.md` would not know which sections are frozen.

**Fix required:**
Add a header note to `EXPERIMENT_SPEC_V1.md` clarifying: "§6 (acceptance criteria C1–C6) is frozen per owner decision 2026-09-24. §§1–5 are still draft and may change. §§7–8 govern the reserved window and are locked once C7 is settled."

---

### MEDIUM findings

---

#### M1 — `analyse_multi_timeframe()` docstring weights (0.5/0.35/0.15) are wrong when weekly=None

**File:** `src/crypto_grid_bot/strategy/structure.py`, module docstring line 37

**Issue (confirmed from first audit as F5):**
The docstring states "weights: weekly 0.5, daily 0.35, hourly 0.15" without noting weight redistribution. Since `weekly_bars=None` in all current calls (line 311 of `features.py`), the effective weights are daily 70% / hourly 30%. An agent or reviewer reading the docstring believes hourly has 15% weight when it actually has 30%.

**Fix required:**
Update the docstring:
```
Multi-timeframe alignment score: mean of per-timeframe scores where BULL=+1,
BEAR=-1, RANGE=0, UNKNOWN=0. Nominal weights: weekly 0.5, daily 0.35, hourly 0.15.
When a timeframe is absent (weekly is currently always None), its weight is
redistributed proportionally to the remaining timeframes: with only daily+hourly,
effective weights are daily ~70% / hourly ~30%.
```

---

#### M2 — `RegimeAssessment.reasons` produced but never logged or persisted in the backtest path

**File:** `src/crypto_grid_bot/strategy/regime.py`, `src/crypto_grid_bot/simulation/runner.py`

**Issue (confirmed from first audit as F3):**
`RegimeAssessment.reasons` contains detailed explanations of every regime decision. In `runner.py`, the result of `classify()` is stored as `regime`, and `regime.regime.value` is written to `report["regime"]`. But `regime.reasons` is never written to the report and is never logged. This is useful diagnostic information that disappears silently on every backtest step.

**Fix required (medium, not critical):**
Either add `regime_reasons` to the report for backtest runs, or document that reasons are intentionally not logged in replay to save memory. If the latter, add a comment in `runner.py` explaining why.

---

#### M3 — `Inputs.hour_open_ms` is a dead field — never consumed downstream

**File:** `src/crypto_grid_bot/backtest/features.py`, line 184

**Issue (confirmed from first audit as F2):**
`hour_open_ms` is populated by `FeatureEngine.at()` and stored on `Inputs`, but no consumer in `replay.py`, `runner.py`, or any test reads it.

**Fix required:**
Either remove the field and the computation (simplification) or document why it exists (future use). If it is kept for future use, add a comment saying so.

---

#### M4 — `GridPlan.fta_resistance_used` is never read by any caller

**File:** `src/crypto_grid_bot/domain.py`, line 103

**Issue (confirmed from first audit as F4):**
`GridBuilder.build()` sets `fta_used` and returns it as `GridPlan.fta_resistance_used`, but `_open_grid()` in `runner.py` never reads this field from the returned `GridPlan`. It is computed and thrown away.

**Fix required:**
Either add `fta_resistance_used` to the `report["opened"]` output (so it appears in backtest results), or remove the field if it adds no value. The field would be useful for verifying in backtest output whether the FTA cap was active for each grid.

---

#### M5 — `test_structure.py` MTF weight tests are algebraic-only — no real bar sequences

**File:** `tests/test_structure.py`

**Issue (confirmed from first audit as F15):**
The tests `test_all_bullish_gives_positive_alignment` and `test_mixed_alignment_is_weighted` verify the weight redistribution formula algebraically without constructing real bar sequences and calling `analyse_multi_timeframe()`. A regression in swing detection or zone classification logic that still passes the algebraic weight formula would go undetected.

**Fix required:**
Add integration tests with real OHLC bar sequences (can be synthetic) that exercise the full `analyse_multi_timeframe()` path including swing detection.

---

#### M6 — No integration test for the complete `Inputs → Frame → _open_grid → GridBuilder(fta_resistance)` FTA chain

**File:** Tests directory, `tests/test_simulation_runner.py` or `tests/test_backtest_replay.py`

**Issue (confirmed from first audit as F17/F18):**
There is no end-to-end test that constructs `Inputs` with a non-None `fta_resistance`, passes through `replay.py`'s `Frame` construction, through `_step()`, and into `_open_grid()`, verifying that the FTA cap is applied correctly in RANGE regime and suppressed in BULL/BEAR.

**Fix required:**
Add integration tests. These were identified in the first audit and are still not present.

---

#### M7 — `verify-2024h1.toml` lists `ADAUSDT` in both `traded` and `breadth_basket` — potential double-counting in breadth score

**File:** `config/datasets/verify-2024h1.toml`

**Current state:**
```toml
traded = ["ADAUSDT", "BTCUSDT"]
breadth_basket = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"]
```

**Issue:**
ADAUSDT is in both `traded` and `breadth_basket`. The breadth score is computed from basket market closes vs their SMA50. Including a traded pair in the basket means its own directional signal (is it above its SMA50?) influences the regime decision that gates whether to open a grid in it. In a bull-trending ADA environment, the breadth score will be inflated by ADA's own trend, making it slightly more likely the regime is classified as BULL, which slightly reduces eligibility (regime fit 0.80 vs 1.0 for RANGE). This is a second-order effect but is worth noting.

**Fix required:**
Document this as a known characteristic of the `verify-2024h1` spec in its `purpose` field, or remove ADAUSDT from the basket and document why.

---

### LOW findings

---

#### L1 — `docs/reviews/2026-09-30-bob-audit-findings.md` minor count error in the severity table

**File:** `docs/reviews/2026-09-30-bob-audit-findings.md`, lines 19–22

**Current table:**
```
| 🟡 MINOR | 5 (F2, F3, F4, F5, F7, F9, F13, F14) |
```
The parenthetical lists 8 finding IDs but the count says 5.

**Fix required:** Correct the count to 8.

---

#### L2 — `docs/reviews/2026-09-30-bob-audit-session-report.md` says F8 is "not yet fixed" — but two of the three specs now have `daily_warmup_start`

**File:** `docs/reviews/2026-09-30-bob-audit-session-report.md`, Part 4 table

The table says:
> F8 | Fetch daily bars; add `daily_warmup_start` to 3 specs | Owner must trigger ...

But as of the PR #154 merge, `long-bull-bear-2022.toml` and `long-recovery-2023-2024.toml` now have `daily_warmup_start`. Only `full-range-2019-2024.toml` is still missing it. The "3 specs" count is now wrong.

**Fix required:** Update the table to say "1 remaining spec (`full-range-2019-2024.toml`)."

---

#### L3 — `docs/reviews/2026-09-29-bob-variant-a-v2-integration.md` still references stale `bob/v2-integrated` branch

**File:** `docs/reviews/2026-09-29-bob-variant-a-v2-integration.md`

**Issue (confirmed from first audit as F14):**
This was identified in the first audit and not yet fixed.

**Fix required:** Update the reference to `main`.

---

#### L4 — `docs/reviews/2026-09-30-bob-audit-plan.md` has status "awaiting owner approval" — but the plan was fully executed

**File:** `docs/reviews/2026-09-30-bob-audit-plan.md`, line 12

The plan file says "PLAN ONLY — awaiting owner approval before execution" but the plan was fully executed (40/40 steps). This misleads future agents into thinking the plan was never run.

**Fix required:** Update status to "EXECUTED — see 2026-09-30-bob-audit-findings.md for results."

---

#### L5 — `CLAUDE.md` and `AGENTS.md` at project root — content not audited; may be stale

**Files:** `CLAUDE.md`, `AGENTS.md` at project root

These files are read by Claude Code and Codex at session start as their per-project instructions. They have not been included in any documented audit. Given the pace of project evolution (schema 6, amendment 1, drawdown-recovery-v1, structure alignment), they may contain outdated context.

**Fix required:** Read and audit both files in the next cleanup pass.

---

## Summary Table

| ID | Tier | File(s) | Description | Action |
|---|---|---|---|---|
| C1 | CRITICAL | `full-range-2019-2024.toml` | `daily_warmup_start` still missing; F8 partially fixed | Fetch daily bars; add field |
| C2 | CRITICAL | Local workspace | No manifest files exist; all runs fail immediately | Run `backtest fetch` for each spec before running |
| C3 | CRITICAL | `verify-2024h1.toml` vs `long-*` specs | Breadth basket mismatch; verify-2024h1 results not directly comparable | Document or align basket |
| H1 | HIGH | `run_nopool.py` | Fee stamp hardcoded; will mislabel output if spec fees differ | Read fee from spec dynamically |
| H2 | HIGH | `quality.yml` | Tests excluded from mypy; type errors in test helpers undetected | Add `tests` to mypy scope or document exclusion |
| H3 | HIGH | GitHub | Task report branch `bob/task-2026-09-29-bob-structure-backtest-comparison` has no PR | Open PR |
| H4 | HIGH | `2026-09-30-bob-audit-session-report.md` | Missing post-merge SHA of fixes | Add PR #154 merge SHA to header |
| H5 | HIGH | `quality.yml` | Dataset spec files not validated in CI | Add spec validation step |
| H6 | HIGH | `trend_switch.py` + docs | `effective_state()` strict one-day-only rule undocumented | Document in `BACKTEST_METHOD.md` |
| H7 | HIGH | `docs/tasks/README.md` | Task status table stale post-PR-#154 | Update table |
| H8 | HIGH | `EXPERIMENT_SPEC_V1.md` | "DRAFT" vs frozen C1–C6 contradiction | Add section-level freeze status note |
| M1 | MEDIUM | `structure.py` docstring | Weight redistribution not documented; effective weights wrong in docstring | Update docstring |
| M2 | MEDIUM | `runner.py` | `RegimeAssessment.reasons` never logged | Add to report or document why not |
| M3 | MEDIUM | `features.py` | `Inputs.hour_open_ms` dead field | Remove or document |
| M4 | MEDIUM | `domain.py` | `GridPlan.fta_resistance_used` never read | Add to report output or remove |
| M5 | MEDIUM | `test_structure.py` | MTF weight tests algebraic-only | Add real bar sequence tests |
| M6 | MEDIUM | tests | No integration test for full FTA chain | Add integration tests |
| M7 | MEDIUM | `verify-2024h1.toml` | ADAUSDT in both traded and basket | Document or remove from basket |
| L1 | LOW | `2026-09-30-bob-audit-findings.md` | Minor count off in severity table | Fix count |
| L2 | LOW | `2026-09-30-bob-audit-session-report.md` | F8 fix count wrong ("3 specs" → "1 remaining") | Update table |
| L3 | LOW | `2026-09-29-bob-variant-a-v2-integration.md` | Stale branch reference | Update to `main` |
| L4 | LOW | `2026-09-30-bob-audit-plan.md` | Status still says "awaiting approval" | Update status |
| L5 | LOW | `CLAUDE.md`, `AGENTS.md` | Not audited; may be stale | Audit in cleanup pass |

---

## Implementation Sub-Tasks

This plan is intended for agent-mode implementation. Each sub-task is self-contained.

---

### Sub-Task 1 — Operational: Fetch manifests and daily bars (prerequisite for all runs)

**Intent:** No backtest run of any kind can proceed without manifests. This sub-task ensures the local workspace is in a runnable state.

**Expected Outcomes:**
- `config/datasets/long-bull-bear-2022.manifest.json` exists
- `config/datasets/long-recovery-2023-2024.manifest.json` exists
- `config/datasets/full-range-2019-2024.manifest.json` exists
- `full-range-2019-2024.toml` has `daily_warmup_start = "2018-07"`

**Todo List:**
1. Run `python -m crypto_grid_bot.backtest fetch --spec config/datasets/long-bull-bear-2022.toml --data-dir data`
2. Run `python -m crypto_grid_bot.backtest fetch --spec config/datasets/long-recovery-2023-2024.toml --data-dir data`
3. Run `python -m crypto_grid_bot.backtest fetch --spec config/datasets/full-range-2019-2024.toml --data-dir data`
4. After step 3 completes: add `daily_warmup_start = "2018-07"` to `full-range-2019-2024.toml`

**Relevant Context:** C1 and C2 above. The `daily_warmup_start` value is already documented in the TOML comment.

**Status:** [ ] pending

---

### Sub-Task 2 — Re-run V2 backtests with corrected classifier (F1 fixed)

**Intent:** All prior V2 backtest results were produced with `structure_alignment=0.0` always (bug F1). Now that the signal is correctly wired, a clean baseline must be established before comparing variants.

**Expected Outcomes:**
- Fresh `results.json` and `summary.md` for `long-bull-bear-2022` (V0 baseline, gated + ungated, both paths)
- Fresh results for `long-recovery-2023-2024` (same)
- Results stored in `data/backtests/<spec>/<timestamp>/`

**Todo List:**
1. (Requires Sub-Task 1 complete) Run `python scripts/run_nopool.py long-bull-bear-2022`
2. Run `python scripts/run_nopool.py long-recovery-2023-2024`
3. Verify both produce `"valid": true` in `results.json`

**Relevant Context:** `2026-09-30-bob-audit-session-report.md` Part 5. Bug F1 in `replay.py:signals_for()`.

**Status:** [ ] pending (requires Sub-Task 1)

---

### Sub-Task 3 — Run Variant A on corrected baseline

**Intent:** Measure the first true V2 Variant A (daily SMA50/SMA200 trend switch) result on both primary windows, now that F1 and F8 are fixed.

**Expected Outcomes:**
- Fresh Variant A results for `long-bull-bear-2022`
- Fresh Variant A results for `long-recovery-2023-2024`

**Todo List:**
1. (Requires Sub-Tasks 1 and 2 complete) Run `python scripts/run_nopool.py long-bull-bear-2022 --variant-a`
2. Run `python scripts/run_nopool.py long-recovery-2023-2024 --variant-a`
3. Verify results are valid

**Status:** [ ] pending (requires Sub-Tasks 1 and 2)

---

### Sub-Task 4 — Open PR for task report branch

**Intent:** The Bob task report branch `bob/task-2026-09-29-bob-structure-backtest-comparison` must become a PR so its `Index:` line enters the handoff index on merge.

**Todo List:**
1. Check current head of `origin/bob/task-2026-09-29-bob-structure-backtest-comparison`
2. Open a PR targeting `main`, with a description referencing the task file and report
3. Append the PR to the Codex-review-owed issue #134

**Status:** [ ] pending

---

### Sub-Task 5 — Fix HIGH infrastructure and CI issues (H1, H2, H5)

**Intent:** Fix the three infrastructure issues that reduce CI reliability and output accuracy.

**Todo List:**
1. Fix H1: Update `run_nopool.py` to read fee from spec dynamically (not hardcoded)
2. Fix H2: Add `tests` to `mypy` scope in `quality.yml` OR add a comment explaining why tests are excluded
3. Fix H5: Add a dataset spec validation step to `quality.yml`
4. Run preflight: `python scripts/preflight.py`
5. Push and open PR

**Status:** [ ] pending

---

### Sub-Task 6 — Update agent-facing documentation (H3, H4, H6, H7, H8)

**Intent:** Bring all agent-facing documents into alignment with actual current state so future agents start from correct context.

**Todo List:**
1. Fix H4: Add PR #154 merge SHA `48770195` to `2026-09-30-bob-audit-session-report.md` header
2. Fix H6: Add Variant A `effective_state()` strict rule note to `BACKTEST_METHOD.md`
3. Fix H7: Update `docs/tasks/README.md` to add new entry and reflect current task state
4. Fix H8: Add section-level freeze status note to `EXPERIMENT_SPEC_V1.md`
5. Run `python scripts/check_reports.py` to verify 0 problems
6. Push and open PR

**Status:** [ ] pending

---

### Sub-Task 7 — Medium cleanup: docstrings, dead fields, and test gaps (M1–M7)

**Intent:** Address the medium-priority issues that accumulate technical debt and reduce auditability.

**Todo List:**
1. Fix M1: Update `structure.py` docstring for weight redistribution
2. Fix M3: Remove `Inputs.hour_open_ms` or add a consumer/documentation comment
3. Fix M4: Add `fta_resistance_used` to `report["opened"]` output, or remove the field
4. Fix M5: Add real bar sequence integration tests to `test_structure.py`
5. Fix M6: Add FTA chain integration test in `test_simulation_runner.py` or `test_backtest_replay.py`
6. Fix M7: Add note to `verify-2024h1.toml` about ADAUSDT in both traded and basket
7. Run preflight and open PR

**Status:** [ ] pending

---

### Sub-Task 8 — Low cleanup pass (L1–L5)

**Intent:** Clean up minor inconsistencies in documentation.

**Todo List:**
1. Fix L1: Correct severity count in `2026-09-30-bob-audit-findings.md`
2. Fix L2: Update F8 status in `2026-09-30-bob-audit-session-report.md`
3. Fix L3: Update stale branch reference in `2026-09-29-bob-variant-a-v2-integration.md`
4. Fix L4: Update audit plan status in `2026-09-30-bob-audit-plan.md`
5. Fix L5: Read and audit `CLAUDE.md` and `AGENTS.md`
6. Run `python scripts/check_reports.py` to verify 0 problems

**Status:** [ ] pending

---

*— IBM Bob (owner's desktop session), 2026-09-30*
