# Task for Bob: backtest comparison of structure-aware features vs baseline

- **Written by:** Bob (owner's desktop session), 2026-09-29. Owner direction recorded in
  [`docs/reviews/2026-09-29-owner-market-structure-perception.md`](../reviews/2026-09-29-owner-market-structure-perception.md)
  and [`docs/reviews/2026-09-29-owner-regime-adaptive-grid-spacing.md`](../reviews/2026-09-29-owner-regime-adaptive-grid-spacing.md).
  New code is in open PRs, not yet on `main`:
  - PR #147 (`bob/market-structure-perception`): `src/crypto_grid_bot/strategy/structure.py`,
    swing detection, S/R zones, FTA, multi-timeframe alignment.
  - PR #148 (`bob/fta-sell-target`): `src/crypto_grid_bot/strategy/grid.py` change — FTA
    resistance cap on sell targets in `GridBuilder`.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), all of it.
- **Read-only:** no change to code, tests, configs, specs or manifests. You measure;
  the interpretation goes in your report.
- **Report:** `docs/reviews/2026-09-29-bob-structure-backtest-comparison.md`, nothing else.
- **Reserved window:** the last allowed data month is **2024-12**. Nothing for 2025-01
  or later is requested, opened or listed. The datasets used here end 2024-06 at the
  latest; this task does not approach the window.

## Why

PR #147 adds market-structure perception (swing highs/lows, support/resistance zones,
multi-timeframe alignment score) that the bot currently lacks. PR #148 uses one output
of that perception — the First Trouble Area (FTA) — to cap sell targets just below the
nearest resistance, rather than placing them at the geometric grid level which may land
inside a resistance wall. The owner wants to know, before these PRs are merged and any
spec amendment is written:

1. Does the FTA sell-target cap (PR #148) change return, drawdown or cycle count on the
   two development datasets?
2. Do the two configurations differ meaningfully from each other, and from the
   unmodified baseline?
3. Are there signs that the change is harmful (more halts, fewer cycles, worse drawdown)?

This run uses the existing backtest CLI unchanged. It extracts the grid.py change from
PR #148's branch using `git show`, applies it with `patch`, and runs the CLI three times
per dataset: baseline, FTA-enabled, and ungated baseline for reference. It produces no
strategy recommendation and touches no spec.

## Scope (fixed)

| Dataset | Evaluation window | Traded pairs | Purpose |
| --- | --- | --- | --- |
| `practice-2022` | 2022-06 to 2023-01 | BTCUSDT, SOLUSDT, XRPUSDT | Volatile year: crash, collapse, rally |
| `verify-2024h1` | 2024-01 to 2024-06 | ADAUSDT, BTCUSDT | Chronology/accounting verification |

Both datasets' data is already on disk from the P8 run (issue #133, task
`docs/tasks/2026-09-27-bob-p8-funding-archives.md`). The manifest files at
`config/datasets/practice-2022.manifest.json` and
`config/datasets/verify-2024h1.manifest.json` must already be present and verified.

**Reserved window:** no data month after 2024-12 is used. `verify-2024h1` ends 2024-06.
Nothing from 2025-01 or later is requested, opened or listed.

**Out of scope:** variant A (trend switch), variant D (trend benchmark), any funding
signal, any spec change, any manifest change, any code change left in the working tree.
The structure_alignment signal wiring (the parallel PR that may add `structure_alignment`
to `Inputs` and `RegimeClassifier`) is **not** part of this task: that code may not
exist as a merged file when this task runs. This task compares only the FTA sell-target
cap (one function change in `grid.py`) against the unmodified baseline.

## How the grid.py patch is extracted and applied

PR #148's branch (`origin/bob/fta-sell-target`) adds one functional change to
`src/crypto_grid_bot/strategy/grid.py` (the `fta_resistance` parameter on `GridBuilder`
and the cap logic). This task extracts that diff with `git diff` and applies it with
`patch`. The patch is verified before and after with SHA-256 hashes.

The patch is a **measurement tool only**: it is applied to a temporary copy, the run is
done, and then the copy is deleted and the working tree is restored. `git status` must
show a clean tree at the start and at the end of this task.

## Steps

Run every command from the repository root, in this order. Each command and its output
goes into the report as Step 7 says.

1. **Verify clean state and record identity.**

   ```text
   date -u
   git rev-parse HEAD
   git status --porcelain --untracked-files=all
   python --version
   ```

   `git status` must print nothing (completely clean working tree). If it prints
   anything, stop and report. Record the HEAD SHA: every claimed result is tied to it.

2. **Verify the datasets are present and verified.**

   ```text
   python -m crypto_grid_bot.backtest verify --spec config/datasets/practice-2022.toml
   python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml
   ```

   Both must exit 0 with `"status": "valid"`. If either is invalid or missing, stop and
   report. Do not fetch data: this task is offline except for the git operations below.

3. **Extract the PR #148 grid.py patch and verify the source file hash.**

   ```text
   git fetch origin bob/fta-sell-target
   git diff origin/main...origin/bob/fta-sell-target -- src/crypto_grid_bot/strategy/grid.py > data/fta-grid.patch
   sha256sum data/fta-grid.patch
   sha256sum src/crypto_grid_bot/strategy/grid.py
   ```

   Record both hashes. The patch file must be non-empty (size > 0). If it is empty,
   the branch has no grid.py change relative to main; stop and report.

4. **Run the baseline (unmodified main).**

   For each dataset, run the backtest with the default config:

   ```text
   python -m crypto_grid_bot.backtest run \
     --spec config/datasets/practice-2022.toml \
     --config config/default.toml \
     --out data/backtests-structure-comparison
   python -m crypto_grid_bot.backtest run \
     --spec config/datasets/verify-2024h1.toml \
     --config config/default.toml \
     --out data/backtests-structure-comparison
   ```

   Record the `out` path printed by each run (it includes the timestamp). Record exit
   codes. Both must exit 0 with `"valid": true` in their `results.json`. If either
   fails, stop and report the full output.

5. **Apply the FTA patch, verify, and run the FTA configuration.**

   ```text
   cp src/crypto_grid_bot/strategy/grid.py data/grid-original.py
   patch -p1 < data/fta-grid.patch
   sha256sum src/crypto_grid_bot/strategy/grid.py
   python -m crypto_grid_bot.backtest run \
     --spec config/datasets/practice-2022.toml \
     --config config/default.toml \
     --out data/backtests-structure-comparison
   python -m crypto_grid_bot.backtest run \
     --spec config/datasets/verify-2024h1.toml \
     --config config/default.toml \
     --out data/backtests-structure-comparison
   ```

   Record the patched grid.py hash and both exit codes. Both runs must exit 0 with
   `"valid": true`. If either fails, restore the original file immediately:

   ```text
   cp data/grid-original.py src/crypto_grid_bot/strategy/grid.py
   ```

   Then stop and report.

6. **Restore the original grid.py and verify clean tree.**

   ```text
   cp data/grid-original.py src/crypto_grid_bot/strategy/grid.py
   sha256sum src/crypto_grid_bot/strategy/grid.py
   git status --porcelain --untracked-files=all
   ```

   The restored file's SHA-256 must match the hash recorded in Step 3. `git status`
   must print nothing (only `data/` files are untracked, and `data/` is git-ignored).
   If the hash differs or `git status` shows any tracked file modified, stop and report.

7. **Write the report** `docs/reviews/2026-09-29-bob-structure-backtest-comparison.md`
   in the following order. Use the same append-by-command discipline as the P8 task:
   write short passages by hand to `data/` files, then append them; append long outputs
   verbatim by command. Never rewrite the report file with a file tool after its first
   creation (6a → 7a).

   **7a. Header and identity, by hand.** Create the report with:
   - The `# ` title as the first line.
   - One `Index:` line within the first 20 lines giving the outcome in one sentence.
   - The HEAD SHA, Python version, and `date -u` from Step 1.
   - The `"status": "valid"` confirmation from Step 2 (one line each).
   - The patch hash and source file hash from Step 3.
   - The engine version and feature version (printed in `results.json` as
     `engine_version` and `feature_version`).

   **7b. Step 4 baseline results, by command.** For each dataset, append the
   `summary.md` the CLI wrote (it holds the results table):

   ```text
   python -c "from pathlib import Path; t=Path('<out-path>/summary.md').read_text(); f=Path('docs/reviews/2026-09-29-bob-structure-backtest-comparison.md').open('a',encoding='utf-8',newline='\n'); f.write('\n## Baseline: practice-2022\n\n'+t+'\n'); f.close()"
   ```

   (Repeat for verify-2024h1, adjusting the heading and path.)

   **7c. Step 5 FTA results, by command.** Same pattern as 7b:

   ```text
   python -c "from pathlib import Path; t=Path('<out-path>/summary.md').read_text(); f=Path('docs/reviews/2026-09-29-bob-structure-backtest-comparison.md').open('a',encoding='utf-8',newline='\n'); f.write('\n## FTA cap: practice-2022\n\n'+t+'\n'); f.close()"
   ```

   (Repeat for verify-2024h1.)

   **7d. Comparison table, by hand.** Write to `data/comparison.md`, then append
   it with:

   ```text
   python -c "import sys; from pathlib import Path; t=Path(sys.argv[1]).read_text(encoding='utf-8'); f=Path('docs/reviews/2026-09-29-bob-structure-backtest-comparison.md').open('a',encoding='utf-8',newline='\n'); f.write('\n'+t+('\n' if not t.endswith('\n') else '')); f.close()" data/comparison.md
   ```

   The comparison table must have one row per (dataset, pair, path_mode) combination
   and columns: Dataset | Pair | Path | Baseline return % | FTA return % | Δ return pp |
   Baseline max DD % | FTA max DD % | Δ DD pp | Baseline cycles | FTA cycles | Δ cycles |
   Baseline halted | FTA halted.

   All numbers come from the `results.json` files the CLI wrote. Print each number you
   type from its source file, then include it in the table. Never retype from memory.

   **7e. Findings and restore verification, by hand.** Write to `data/findings.md`,
   then append it with the same command as 7d. Include:
   - A `## Restore and clean-tree check` section: the Step 6 hash match and the
     `git status` output.
   - A `## Findings` section: for each dataset, state whether FTA return and drawdown
     differ from baseline by more than rounding, citing the exact delta from the
     comparison table. State whether any halts or range-exit counts changed.
   - A `## Limitations` section: what this run cannot show (no FTA source data passed
     to GridBuilder in this run — see explanation below).
   - A `## Ideas and proposals` section: questions for Claude and Codex, each checked
     against the tables first.

   **Important — the FTA cap cannot fire without a source:** The FTA cap in PR #148's
   `GridBuilder` takes an optional `fta_resistance` argument. The backtest CLI's
   `run_job` in `jobs.py` calls `GridBuilder` (indirectly via `FeatureEngine` and
   `replay`) without passing `fta_resistance`. Unless PR #148 also changes `jobs.py`
   to compute and pass the FTA value from `structure.py`, the cap parameter will be
   `None` on every grid open and the patched code will be unreachable. Before the Step 5
   run, check whether PR #148's diff changes `jobs.py`:

   ```text
   git diff origin/main...origin/bob/fta-sell-target -- src/crypto_grid_bot/backtest/jobs.py
   ```

   If this diff is empty, state in Step 7e's Limitations section that the FTA cap was
   not exercised (the parameter was always `None`) and that the Step 4 and Step 5 runs
   are therefore expected to produce identical results. If the diff is non-empty, the
   cap may fire, and note that in the findings.

8. **Run the checkers.**

   ```text
   git status --porcelain --untracked-files=all
   python scripts/check_reports.py
   ```

   `git status` must show only your new report under `docs/reviews/` as an untracked
   file; no tracked file may be modified. `check_reports.py` must print
   `check_reports: 0 problem(s)` with exit 0. Quote both outputs in your final message.

## Validity checks (all must hold for a valid run)

1. Step 1: `git status` prints nothing; HEAD SHA is recorded.
2. Step 2: both `verify` commands exit 0 with `"status": "valid"`.
3. Step 3: patch file is non-empty; both SHAs are recorded.
4. Steps 4 and 5: all four `run` commands exit 0; all four `results.json` files have
   `"valid": true` and zero `"failures"`.
5. Step 6: restored grid.py SHA matches Step 3's source SHA; `git status` is clean.
6. Step 7: comparison table has one row per (dataset, pair, path_mode); all numbers
   traced to their `results.json`.
7. Step 8: `git status` shows only the new report; `check_reports.py` prints
   `check_reports: 0 problem(s)`.

## What to report

`docs/reviews/2026-09-29-bob-structure-backtest-comparison.md`, written in steps 7a to
7e then the checks at step 8:
- HEAD SHA, Python version, `date -u` at start and end;
- dataset verify status;
- patch and source file hashes;
- the four `summary.md` tables appended verbatim;
- the comparison table with all deltas;
- the `jobs.py` diff check result and its interpretation;
- restore verification and clean-tree confirmation;
- findings: whether the FTA cap changed any result, citing the delta column;
- limitations: whether the cap was exercised, and what would be needed to exercise it;
- ideas and proposals;
- `check_reports.py` output at the end.

## Stop conditions

Stop, keep everything, and report what you have, with the full error, if:
- `git status` shows a modified tracked file at Step 1 or Step 6;
- either dataset fails `verify`;
- the patch file is empty;
- `patch` fails or reports a hunk that did not apply;
- any `run` command exits non-zero or produces `"valid": false`;
- any number in the comparison table cannot be traced to a `results.json`;
- anything requests data for 2025-01 or later;
- anything else is unexpected.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), all eleven items. Apply items 1, 2 and
4 to 11 to each hand-written passage before you append it. Item 3 is Step 8.
