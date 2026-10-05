# Code audit of the whole project: findings, fixes and limits (2026-10-04)

Index: 2026-10-04 code audit of all project code. 11 independent reviewers plus a completeness critic; every finding attacked by adversarial verifiers. 44 confirmed and 19 nits; 25 refuted. Fixed in this PR: a journal gap (orders partly filled and cancelled in one frame were lost), three bypasses of the claims hook (PowerShell call operator, shell wrappers, letter case), CI that ran the suite twice per push and an unbounded automated-review job, a Bob session hook that fed public comments into Bob's context (and had silently stopped working on current gh), 6 Windows-only test failures, a 1 GB tick buffer in the live stream, and dead code and duplication across the engine. Replays are 35-40% faster and byte-identical to main.

- **Date:** 2026-10-04. **Author:** Claude (session `b9db01ca`, continuing `e0b16be3`).
- **Base:** the audit read origin/main `344f9ae`. The fixes were rebuilt on main `96d4aab`, after a week of V2 work had landed. The branch is `claude/code-audit-2026-10`.
- **Scope rule:** this PR changes **no trading behaviour**. Every engine change was proved byte-identical, as described below. Anything that changes behaviour belongs to the strategy PR or to an owner decision.

## How the audit was run
- **Finders:** 11 finders, one per subsystem or lens:
  - subsystems: simulation core, risk and recovery, backtest data, replay, market data, scripts, workers and CI;
  - lenses: architecture and spaghetti, efficiency, security, test-suite quality, config consistency.
- **Verifiers:** each finding went to adversarial verifiers told to refute it. Major findings got two, with correctness and consequence lenses, and stood only on a majority. Then a completeness critic looked for gaps.
- **Implementation:** six slices in separate worktrees, then merged. Each engine slice proved byte-identity on synthetic data.

## Evidence that behaviour is unchanged
- **Combined branch against main `96d4aab`:** identical `results.json` (SHA-256 `bf270d2720979683ebf04077f2c263746ae176ce2df7cffffb145bdf5923308a` on both sides) for:
  - V0 gated (both path modes) and V0 ungated;
  - variant D (both paths);
  - variant A through `SimulationPolicy(trend_switch=True)`.

  The synthetic data is 11,520 evaluated minutes with 245 days of daily warm-up and a 5-symbol basket, built through the real `run_job` and `trend_job` setup, so main's V2 structure inputs are active.
- **Simulation-core slice:** its own 6-case check (120,960 frames each, including a hard-drawdown halt, liquidation, restart and variant A Down periods) was identical at every commit.
- **Preflight on the combined branch:** 823 passed, 4 skipped; ruff, format, mypy (src and scripts) and bandit clean. `check_reports`: 0 problems.
- **P8:** none of the ten files the P8 task pins were touched.

## What this PR fixes

### Correctness
- **Order journal** (`simulation/runner.py`, `execution.py`, `models.py`): an order that filled in part and was cancelled in the same frame appeared neither as open nor as cancelled. That happens on crash frames, where the audit trail matters most.
  - `Fill` now carries `remaining`.
  - Only fills that completed their order are left out of `cancelled`.
  - The regression test builds the real path: a partial fill pushes the daily loss past 3%, and the risk recheck then cancels the rest of the order.
- **Exact risk thresholds: moved to #163.** Comparing the 3%, 8% and 12% limits exactly, instead of through float-converted equity, changes decisions for an equity exactly on a limit. A semantic change belongs under a new engine identity (Codex review of #159), and #163 already bumps both, to `drawdown-recovery-v2` and schema 8. This PR keeps main's comparisons, so it stays free of behaviour changes.
- **Journal shape:** a reentry refused by the affordability check is recorded (`reentry_refused`). `capped` is present on every frame of a capped run. A no-op settlement on a flat frame no longer increments `settlement_count` or journals an empty allocation.
- **Config:** `include_assets` entries are checked as asset names, and duplicates are refused. Options a chosen mode would ignore are rejected instead of silently dropped.

### Security and CI
- **Claims hook** (`scripts/claims.py`), which guards pushes and merges on claimed PRs:
  - It now sees through the PowerShell call operator, through `bash -c` / `pwsh -Command` / `cmd /c` (parsed recursively), and through `env`, `timeout`, `nohup` and similar wrappers.
  - Repository names are compared case-insensitively.
  - A merge it cannot resolve statically (`eval`, a command held in a variable, a computed PR number) is refused.
  - 74 everyday command forms parse exactly as before.
- **Automated review workflow:** a 30-minute timeout, one run per PR at a time, and no write token left in `.git/config`. Its secrets, prompt and tools are unchanged. Residual risk: fork PRs get no secrets, so only push-capable authors could reach them.
- **quality.yml:** the full suite no longer runs twice per PR push. Superseded PR runs are cancelled; main runs never are.
- **Bob's session hook:**
  - Its comment query was refused by current `gh`, so it showed Bob nothing.
  - It now uses GraphQL and includes only the owner's and the project bots' comments, fenced as data and not instructions.
- **install_superpowers.py:** pinned to an upstream commit, with SHA-256 checked per file.

### Efficiency
- **Validation:** `Account.validate` ran about 3 times per replay frame, roughly 85% of the bar-loop cost. It now runs about once, and the end-of-frame and store-level validation stay. Replays take 35-40% less time.
- **Feature engine:** the 720-hour rolling medians are incremental. Inputs are cached per stable span, cutting about 33% of the feature engine's time, and variant D's warm-up check no longer builds full Inputs.
- **Integrity checks** in the backtest CLI now really run in parallel. Before, `.result()` inside the submit loop serialised them.
- **Live price stream:** it no longer buffers up to 2 million ticks (0.2-1.2 GB) to compute three statistics. Its summary output is unchanged, proved by a reference test.

### Structure (pure refactors)
- One shared run setup for the grid job and variant D's job, including the round-trip-cost formula.
- One archive-loader helper instead of three copies, and one fill-journal function instead of two.
- `_restart` and `resume()` share one halt-clearing helper.
- The harvest branch of `_step` is now its own method.
- Variant A's SMA reuses `daily_sma`.
- `place()` and `Account.validate` share one link-validity check.
- Dead code removed: `RiskDecision.capital_multiplier` (REDUCE is pause plus drain under amendment 1), `OpportunityScorer.rank`, `execution.cancel()`, the unused `capital_utilization` parameter of `GridBuilder` (the 0.8 is now named once), the claims workflow's stale fallback, and others.

### Tests and docs
- The 6 `test_preflight` failures on Windows with Python 3.14 are fixed by warming the platform cache before the mocks.
- The Bob-review workflow tests build their remote once per module, cutting fixture time from 5.7 s to 2.1 s.
- `BACKTEST_METHOD.md` no longer says drawdown halts never resume automatically. It also notes that marks are unrounded while exit fills are tick-floored.

## Deferred, with reasons
- **Findings in files the P8 task pins by SHA-256** (`backtest/dataset.py`, `klines.py`, `funding.py`, `market_data/client.py`, `parsing.py`, the two registered dataset specs and their manifests). Changing them would stop the owner's pending P8 run. Example: the zero-padded-month guard missing from `archive_path`.
- **Consolidating duplicated test fixtures into `tests/conftest.py`:** a large cross-file move best done on its own.
- **Deduplicating the pinned Bob Shell install block** shared by two workflows: security-sensitive, best changed with its own review.
- **Remaining claims-hook gaps:** PowerShell script blocks, `Start-Process`, `xargs`, encoded commands. The hook guards against accidents; it was never meant to be an absolute barrier.
- **The stream summary's 200,000-ticks-per-symbol cap** is kept so the output stays identical. Lifting it is a one-line change.

## Not in this PR: strategy
The strategy audit, including a critical lookahead in the V2 structure code on main (issue #158), is handled in the separate strategy PR. That PR changes behaviour on purpose and is stacked on this one.

## Refuted findings (25)
- `src/crypto_grid_bot/strategy/grid.py:52`: GridBuilder picks the level count from capital alone and never tries fewer levels when spacing fails, so it refuses grids that are viable at a coarser *Refuted:* The finding describes the code correctly but is not a real defect, and the fix it proposes cannot be applied as written.
- `src/crypto_grid_bot/simulation/models.py:209`: The liquidation-mark formula bid*(1-slippage)*(1-taker_fee) is written independently in three modules that must agree to the digit. *Refuted:* The formula is duplicated, but the finding's case for acting on it is wrong.
- `src/crypto_grid_bot/simulation/execution.py:165`: A reentry buy resized by the inventory cap is journaled as "resized" even when match then drops it on the affordability check, and an affordability-dr *Refuted:* The phantom "resized" row can't happen.
- `src/crypto_grid_bot/backtest/jobs.py:96`: Warm-up hourly integrity for a traded symbol (including a traded market proxy) is only enforced as a side effect of the optional daily cross-check, so *Refuted:* One narrow point is true.
- `src/crypto_grid_bot/backtest/jobs.py:62`: Each of the 4 run jobs per traded symbol (2 path modes x gated/ungated) independently re-parses the same ~12 symbols' hourly zip archives and recomput *Refuted:* The finding describes the code correctly but gets the fix mechanism wrong, and the saving is too small to act on.
- `src/crypto_grid_bot/backtest/audit_run.py:129`: audit_outages records a pair-month whose 1h archive is missing (unpublished) in the 'unparsed' list, mislabeling absence as a parse failure in the rep *Refuted:* The code does what the finding says, but the problem can't happen on the data this tool is limited to, so there is nothing to act on.
- `src/crypto_grid_bot/backtest/audit.py:180`: fix_closes crashes with an uncaught IndexError/ValueError on any structural defect other than a bad close (short row, non-digit timestamp), killing th *Refuted:* The code does what the finding says, but the failure can't be reached with any data the project is allowed to read.
- `src/crypto_grid_bot/backtest/replay.py:106`: The kline adapter's liquidity mapping is inverted for marketable (taker) orders: liquidations/drains are capacity-bounded by taker-BUY flow and varian *Refuted:* The code does what the finding says, but the claimed effect doesn't hold at the configured scale, so this isn't a major correctness defect.
- `src/crypto_grid_bot/backtest/replay.py:358`: _BuyAndHold computes and marks at the ambient Decimal precision (28) while every other money path pins precision 50 — the exact defect class the modul *Refuted:* One narrow part of the claim is true: _BuyAndHold.__init__ and mark (replay.py:358-376) run at the ambient precision.
- `src/crypto_grid_bot/market_data/stream.py:244`: Silence teardown plus the stability window starves quiet symbols: backoff escalates to 300 s and the price book stays empty for any pair whose bookTic *Refuted:* The finding's central claims do not hold up against the code.
- `src/crypto_grid_bot/market_data/store.py:60`: check_cooldown full-scans the failures table on every capture; the table has no index on blocked_until_ms and is never pruned. *Refuted:* The literal facts check out.
- `src/crypto_grid_bot/market_data/stream.py:222`: A 418/429 ban stops the stream process but is not persisted, unlike the REST path, so an immediate CLI rerun reconnects during an active IP ban. *Refuted:* The code does what the finding says, but it is a known, reviewed and accepted limitation of a manual diagnostic tool, not a new defect worth acting on.
- `scripts/check_reports.py:301`: sections() builds its fenced-block guard from the wrong offsets, so a short '#' line at the end of a fenced block is treated as a real heading. *Refuted:* The offset mistake is real, but the harm the finding claims does not happen, and I showed that by running the checker.
- `scripts/check_reports.py:449`: Each review is regex-scanned 3-5 times and sections() is recomputed once per pin; check_allow_list re-reads files the main loop just parsed. *Refuted:* The code does what the finding says, but it isn't worth changing.
- `.github/workflows/bob-task.yml:350`: If the resolve job itself fails, the whole bob-task run dies silently: the owner-alert step is inside the publish job, which is gated on resolve succe *Refuted:* The gating is as described: publish (bob-task.yml:346-351) needs `needs.resolve.result == 'success'`, and the alert step (line 493) sits inside publish.
- `.github/workflows/bob-task.yml:289`: The reserved-window guard only catches files literally named `*-YYYY-MM.zip` or `*-YYYY-MM.csv`, so 2025+ data fetched or extracted under any other na *Refuted:* The finding describes the regex correctly but gets its role wrong, and the proposed fix would break normal runs.
- `.github/workflows/bob-task.yml:202`: The bob-data cache restore step can never hit: no workflow ever saves a cache under the `bob-data-*` key, so every task run re-downloads all archives  *Refuted:* The core fact holds, but the finding overstates it and is not worth acting on.
- `scripts/local_worker_queue.py:102`: Only pending events are capped; processed events and runs rows accumulate forever, so the 'bounded' queue database grows monotonically for a long-runn *Refuted:* The literal code claim is correct, but the finding is not a defect worth acting on, and several of its supporting claims are wrong or overstated.
- `src/crypto_grid_bot/strategy/rotation.py:18`: The whole rotation subsystem is unwired: RotationPolicy is constructed only by its own test, and the four rotation_* config fields plus maximum_active *Refuted:* The core observation is true, but one piece of evidence is wrong and the code is left out of the loop on purpose.
- `src/crypto_grid_bot/backtest/jobs.py:83`: Each traded symbol's minute archives are re-parsed from CSV five times per backtest (4 run jobs + 1 cross-check). *Refuted:* The mechanics are right, but the redundancy costs too little to act on, and neither proposed fix is a clear win.
- `src/crypto_grid_bot/backtest/features.py:103`: 30-day baseline medians recompute a full 720-element slice-scan-and-sort per hourly index: O(n * 720 log 720). *Refuted:* The mechanics are described correctly, but the fix isn't worth making.
- `.github/workflows/bob-task.yml:436`: Bob's untrusted summary.md is forwarded verbatim into PR bodies and issue comments without the @-mention/trigger neutralization that the local worker  *Refuted:* The literal observation is accurate, but the finding compares two cases that differ in the way that matters, and its fix would not close the risk it describes.
- `pyproject.toml:45`: Six test files repeat the same sys.path.insert boilerplate to reach scripts/, although pyproject already centralizes path setup with pythonpath = ["sr *Refuted:* The duplication is real.
- `src/crypto_grid_bot/config.py:43`: The entire [rotation] section and universe.maximum_active_grids are parsed and validated but consumed by no production code, yet they are baked into t *Refuted:* The facts are right, but the finding is not worth acting on as stated.
- `src/crypto_grid_bot/backtest/dataset.py:407`: fetch_funding_file is production-dead and emits manifest entries whose shape _validate_manifest categorically rejects, so funding archives cannot be r *Refuted:* The code facts are right.
