# V4 step 4b: the run pipeline, the verdict step and the rehearsal (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One dispatch-only GitHub workflow, `v4-run.yml`, runs V4's 48 cells, judges them with a resumable verdict step that reads only the cells' `summary.json` files and receipts, and can be rehearsed end to end on synthetic data, forced stop outcomes included, and timed at real size. The work stops before step 5's registration and run (v4-d15).

**Architecture:** The pass rule lives in a small pure library, `src/crypto_grid_bot/v4/verdict/`: one cell's summary accepted or refused, the common-boundary measures, the four conditions and the precedence. A CLI around it, `scripts/v4_verdict.py`, takes one cell at a time and keeps a progress file so it can resume. `scripts/v4_registration.py` holds V4's registration, job gate and dispatch check. It imports V3.1's generic GitHub, git and trial-register helpers unchanged and copies only V3.1's V3.1-specific decision layer. `scripts/v4_rehearsal.py` builds synthetic worlds: a V4 data pack, a V3 pack and a git world with a code pin and a registration. It also forces stop outcomes through the real cell CLIs and checks that every rehearsal scenario gets the verdict it should. `v4-run.yml` wires these into V3.1's job pattern: plan, V3 pack, picks, cells, V3 cells, scenarios, verdict, analysis, status.

**Tech Stack:** Python 3.12, standard library only (Decimal, json, hashlib, argparse, subprocess for git), pytest, GitHub Actions. It reuses the V4 engine (`v4/engine/*`), `scripts/v4_cell.py`, `scripts/v4_v3_cell.py`, `scripts/v4_v3_pack.py` and `scripts/v4_diagnose.py`, plus V3.1's `scripts/v31_driver.py`, `scripts/trial_register.py` and `combined/driver/run_cell.py` (imported, never edited).

**Spec:** `docs/superpowers/specs/2026-10-17-v4-design.md`. The sections that matter are "Versions in the run", "Pass rule (v4-d04)", "Records", "Reports", "Engineering", "Verification", "Delivery" item 4b and "Registration and the run", plus the step-4a amendment and owner decisions v4-d03, v4-d10, v4-d15, v4-d22 and v4-d23. This step builds on step 4a, PR #296 (merge 184be44); its build record is `docs/reviews/2026-10-24-claude-v4-step4a-arms.md`, whose "Deferred to step 4b" list is Tasks 11 and 12.

## Global Constraints

- Paper simulation only. No live trading, no API keys, no orders on any exchange.
- **v4-d03:** no market data from 2025-01 onward is executed before the registered run.
  - The rehearsal and timing modes use synthetic data only, and refuse real data.
  - The registered mode needs a registration that is not written until step 5.
- **Frozen code:**
  - Never edit `src/crypto_grid_bot/simulation/`, `trend/`, `strategy/`, `backtest/` or `combined/`.
  - Never edit V3.1's registered scripts (`scripts/v31_*.py`, `scripts/trial_register.py`). V4 imports them as they are.
- **Owner rule (2026-10-19): no CPU-heavy work on the owner's PC.**
  - Locally, run only the test modules a task names, plus `ruff format --check .`, `ruff check .`, `mypy src scripts` and `bandit -q -r src scripts`.
  - CI runs the full suite.
  - The real-size timing world is generated only on GitHub. Local tests use small worlds and scaled-down presets.
- **Public logs** carry counts, ids, sizes, times and pins only: never a price, an equity, a return, a cell's outcome or the verdict. In the workflow, a cell CLI's standard output goes to `/dev/null`.
- **Results stay on the owner's PC (v4-d10).**
  - Every artifact is kept 1 day (`retention-days: 1`).
  - After a run, download the artifacts to E:, check them against GitHub's digests, then offer the owner their deletion.
- **Workflows:**
  - Every action is pinned by its 40-hex SHA, using the same pins as `.github/workflows/v4-cells.yml`.
  - Checkouts use `persist-credentials: false`. Permissions are `contents: read`, plus `actions: read` only in jobs that read GitHub's run or job listings or another run's artifacts.
  - No `${{ }}` inside a `run:`. Inputs reach scripts through `env:` only.
- **JSON outputs** are written as V3.1's canonical JSON (`combined.artifacts._canonical`: sorted keys, no spaces, ASCII, no newline) and created exclusively, never over an existing file.
- **Numbers:**
  - Arithmetic is exact `Decimal` under `v4.engine.numbers.CONTEXT`. Maximum drawdown is `trend.metrics.maximum_drawdown`.
  - Every Decimal in JSON is a string.
- **Tests:** any test that could reach the network blocks it, with the `network_blocked` fixture pattern of `tests/test_v4_cell_cli.py`.
- **Reviews:** Bob is out (owner, 2026-10-24). Reviews go to Codex. Nothing addresses Bob.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Rulings (where the spec is silent)

Each ruling states the decision and what it costs if it is wrong. Tasks cite them by number.

**The verdict's inputs**

- **V1. An accepted summary.** A summary is accepted only if all of these hold:
  - it sits in a folder `v4-summary-<cell id>-attempt-<n>`;
  - its `summary.json` bytes are the canonical JSON of their own parse, with unique keys;
  - its format matches its arm: `v4-summary-v3-1` for `v3_as_built`, `v4-summary-1` for every other arm;
  - its `cell` is the folder's cell and one of the expected cells;
  - its `window` and `data` are the expected ones:
    - a V4 or hold cell must carry the expected window (`run.window_record` of the run's market) and the expected data (`run.data_record`);
    - a v3 cell must carry `{start_ms: V3_START_MS, end_ms: V3_END_MS - HOUR_MS}` and `{v3_pack_sha256, picks_sha256}`, both the expected pins;
  - its keys are exactly its outcome's key set;
  - every number is a finite Decimal string;
  - its open marks are `[int, str, bool]` with strictly increasing hours, and its first mark equals its capital;
  - for a full summary, `receipt.json` exists, reads with `records.read_receipt`, and its bytes hash to `receipt_sha256`.

  Anything else is a refusal with a named step. *Cost: a summary that is valid but oddly spelled is refused, and the verdict is incomplete.*
- **V2.** A refused summary counts as missing. Its outcome is never read, not even for the fail precedence. *Cost: a refused liquidated `v4_main` gives incomplete, not fail.*
- **V3. Re-runs and duplicates.**
  - A folder with attempt `n != 1` is a re-run. The cell is refused (step `rerun`), and the verdict is incomplete whatever the cell (V3.1's rule).
  - Two accepted folders for one cell refuse both (step `duplicate`).

  *Cost: an innocent re-run voids the verdict, by design.*

**The measures**

- **V4. Common boundaries.** The common boundaries of two arms are the hours at which both have an open mark flagged `complete`. If none remain, the condition cannot be computed, and the verdict is incomplete. *Cost: none.*
- **V5. A path's numbers.**
  - Compounded return is `last / first - 1` and maximum drawdown is `maximum_drawdown(path)`, both under `CONTEXT`.
  - If the first equity is not positive, the measure cannot be computed, and the verdict is incomplete.
  - Return over drawdown uses the zero-drawdown rule: with a drawdown of 0, it is `Decimal("Infinity")` when the return is positive and `Decimal(0)` otherwise. "Greater" is the plain Decimal `>`, so Infinity is not greater than Infinity.

  *Cost: none.*
- **V6. A liquidated `v3_as_built` in condition 2.** After its stop, the arm holds nothing. So at every hour after `stop_ms` up to 2024-12-31 23:00, its equity is its `final_equity` and its mark counts as complete. Only `v4_main`'s marks then decide which hours are common. *Cost: if the owner reads V3's stop otherwise, condition 2 changes for such a run only.*

**The conditions**

- **V7. Condition 1 path.** The path is each arm's equity at the common boundaries of `v4_main-<c>-1x` and `hold_universe-<c>-1x`, then each arm's `final_after_close` as the last point. Both must be `complete`; any other outcome of `hold_universe` is incomplete. *Cost: none.*
- **V8. Condition 2 range.** The common boundaries count from `V3_START_MS` (2021-07-01 00:00) to `V3_END_MS - HOUR_MS` (2024-12-31 23:00), both included. There is no final point. *Cost: none.*
- **V9. Conditions 3 and 4.**
  - Condition 3 is `final_after_close > initial_equity` for `v4_main-<c>-2x`.
  - Condition 4 is `final_after_close > equity_2025` for `v4_main-<c>-1x`. A null `equity_2025` cannot be computed, so the verdict is incomplete.

  *Cost: none.*
- **V10. Precedence.** The verdict is decided in this order:
  1. **fail** if an accepted `v4_main` summary, at either capital and either cost, is `liquidated`, `limit_unrestorable` or `accounting_failure`;
  2. otherwise **incomplete** if any of these holds:
     - one of the 8 required cells is missing, refused or `engine_error`. The required cells are `v4_main` at both capitals and both costs, and `hold_universe` and `v3_as_built` at both capitals at 1x;
     - a re-run or another dispatch of the same registration was found;
     - a condition cannot be computed;
  3. otherwise **pass** if all 8 checks hold (4 conditions x 2 capitals), else **fail**.

  *Cost: none, as the spec's precedence.*

**Reporting and resuming**

- **V11. Reported comparisons.** Every non-v3 arm, at each capital and cost, is reported against `hold_universe` and against `v3_as_built` at the same capital and cost. The first uses condition 1's measure, the second condition 2's. Each cell's own `compounded_return`, `max_drawdown`, eras and years are reported too. Variants and neighbours are grouped beside `v4_main`. None of this decides anything. *Cost: compute time only.*
- **V12. The run summary** is two pages:
  - the verdict step's `verdict.md`: the verdict, the conditions, the comparison table, the eras, the variants and neighbours, the disclosures and the plain-language headline;
  - the analysis step's `diagnosis.md` (`scripts/v4_diagnose.py`): long against short, and per coin, from the records.

  The verdict page names the analysis artifact. *Cost: the owner reads two pages, not one.*
- **V13. Resuming.**
  - `progress.json` records the digest of the inputs: the expected file, the list of summary folders with each `summary.json`'s SHA-256, and the dispatch reasons.
  - It also records every finished step: one per cell, one per pair measure. It is replaced atomically (a temporary file, then `os.replace`) after each step.
  - A resume with a different input digest is refused, and nothing is written.
  - At most two cells' marks are held at once. The progress holds numbers, never marks.

  *Cost: a changed input needs a fresh progress folder.*
- **V14.** `verdict.json` and `verdict.md` are created exclusively. If the second cannot be written, the first is removed. The CLI exits 0 once both are written, whatever the verdict, and 1 when nothing is written. *Cost: none.*

**Registration**

- **G1. The registration files.** The registration file and the run manifest:
  - `config/v4_registration.json` has exactly the keys `schema` (`v4-registration-1`), `code_pin` (40 hex), `run_manifest_sha256`, `spec` (`{path, sha256}`), `cells` (the 48 ids of `arms.all_cells()`, in order) and `trial_id`. It never holds its own hash; the dispatch passes it.
  - `config/v4_run_manifest.json` has exactly the keys `schema` (`v4-run-manifest-1`), `data` (`{config_path, config_sha256, end_month, daily_sha256, index_sha256}`) and `v3_pack_sha256`.
  - Both are canonical JSON.

  *Cost: step 5 writes them in this shape.*
- **G2. The job gate.**
  - The only files that may differ from the code pin are `config/v4_registration.json`, `config/v4_run_manifest.json` and `docs/trials/register.jsonl`, plus anything under `docs/reviews/` and `docs/tasks/`. The check is `run_cell._allowed`, with V4's own set.
  - The trial family is `spec-v4.0`. The completion's `config`, `manifest` and `code_commit` are checked exactly as V3.1's `trial_errors` checks them, through `trial_register.check_ready`.
- **G3. The rehearsal marker.**
  - `config/v4_rehearsal.json` with fixed bytes marks a rehearsal world. A rehearsal requires it, exactly, at the code pin and in the working tree.
  - A registered run refuses it in the working tree, at HEAD or at the code pin.
  - The repository itself never holds it.
- **G4. The dispatch check.**
  - It is V3.1's logic, copied with V4's workflow file `v4-run.yml`.
  - Its titles are `v4-run registered <sha>`, `v4-run rehearsal <sha>` and `v4-run timing <sha>`. The `run-name` is `v4-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}`.
  - Its job names are `plan`, `status`, the skipped jobs `v3-pack`, `v3-picks`, `scenarios`, `verdict` and `analysis`, and the matrix jobs `cell` and `v3-cell`.
  - Its job-start variable is `V4_JOB_STARTED`. Its budgets are 25 minutes for the plan job and 55 minutes for the verdict job, with V3.1's 20-minute deadline.
- **G5. The registered data.**
  - The data run must be a run of `.github/workflows/v4-data.yml` named `v4-data full config/v4_data.json`, whose conclusion is `success` and whose `head_sha` is this run's `github.sha`. That means the same ref, which the job gate holds to the code pin plus the registration files.
  - Its `data.json` pins must equal the manifest's `data`, and `config_sha256` must be the SHA-256 of the manifest's `config_path`. Step 2's packs are deterministic: run 39992748266 at 12f4e8f and run 40009104102 at 0cea879 have the same pins.

**The workflow**

- **W1. Artifact names.**
  - Each artifact carries `-attempt-<github.run_attempt>`, except `v4-data`, `v4-v3-pack` and `v4-rehearsal-world`. Those three have fixed names and are uploaded without `overwrite`, so re-running the whole workflow fails closed at the plan job.
  - The verdict job downloads only `v4-summary-*` (`summary.json` and `receipt.json`, about 3 MB a cell at real size). V3.1's aggregate died of a full disk; this keeps the verdict step far inside 5 GB.
  - The analysis job downloads `v4-cell-*`. V3 cells upload `v4-v3-cell-*`, so the analysis never downloads them.
- **W2. The timing mode** runs the 44 non-v3 cells on the real-size synthetic world, then the verdict step and the analysis over their outputs. It uploads only timing files: cell, verdict and analysis times, peak memory and output sizes. The v3 cells' times come from the `v4-v3` run (40040422092).
- **W3. The rehearsal mode** builds the world in its plan job and runs every job of the registered graph on it, with the real gate on the world's git repository.
  - It also forces six stop outcomes through the real CLIs: `liquidated`, `limit_unrestorable` and `accounting_failure` through `v4_cell.py`, `engine_error` likewise, and `V3Stop` and `V3Accounting` through `v4_v3_cell.py`.
  - It then judges eleven scenarios, the base set and ten altered sets, and requires each to get its expected verdict.
  - Its outputs carry rehearsal names, so a synthetic pass can never pass for the registered run's.

## Review Focus

1. **Relabelled or re-run summaries:**
   - an `attempt-2` folder;
   - one cell's summary placed in another cell's folder;
   - a 1,000 USDT summary in a 10,000 folder;
   - a summary carrying another data run's pins.

   Each must be refused, and the verdict must be incomplete. Tests are in Task 2 (`test_refuses_*`) and Task 7 (the `rerun` and `relabelled` scenarios).
2. **A resume after a summary was replaced between two runs** must be refused, with nothing written. Never mix the two. Test in Task 4: `test_resume_with_changed_inputs_is_refused`.
3. **Zero drawdown on both arms with a positive return:** Infinity against Infinity is not greater, so condition 1 is false and the verdict fails. Test in Task 3: `test_infinity_is_not_greater_than_itself`.
4. **`v3_as_built` stopped or unreconciled:**
   - a liquidated `v3_as_built` is measured under V6;
   - a `V3Accounting` is incomplete;
   - a `V3Stop` is incomplete.

   Tests in Task 3 (`test_condition_2_after_a_v3_liquidation`) and Task 7 (the `v3_stop` and `v3_accounting` scenarios).
5. **Registered data that is not the registered data:**
   - pins that differ from the manifest's, or a data run of another commit, must be refused before any cell runs;
   - the pre-2025 default of `v4_diagnose.py` must stay unchanged.

   Tests in Task 6 (`test_run_guard_refuses_other_pins`, `test_diagnose_default_still_refuses_2025`) and Task 10 (`test_cells_need_plan_and_guard_first`).

---

## File structure

| File | Task | Responsibility |
|---|---|---|
| `src/crypto_grid_bot/v4/synthetic.py` | 1 | The synthetic world writer, moved from `tests/v4_synthetic.py` unchanged, plus the rehearsal and timing presets and the synthetic V3 pack fields |
| `tests/v4_synthetic.py` | 1 | A shim that re-exports `crypto_grid_bot.v4.synthetic`, so existing tests are untouched |
| `scripts/v4_rehearsal.py` | 1, 7 | `world`, `picks` (Task 1); `force`, `scenarios`, `check` and the world repository (Task 7) |
| `src/crypto_grid_bot/v4/verdict/__init__.py` | 2 | The package marker |
| `src/crypto_grid_bot/v4/verdict/inputs.py` | 2 | `Expected`, `CellFacts`, `CellRefused`, `read_expected`, `read_cell`, `read_marks` |
| `src/crypto_grid_bot/v4/verdict/rule.py` | 3 | `common_boundaries`, `path_measure`, `ratio`, `after_stop`, the four conditions, `decide` |
| `src/crypto_grid_bot/v4/verdict/report.py` | 4 | `verdict_document`, `render_verdict_page` |
| `scripts/v4_verdict.py` | 4 | The resumable verdict step (CLI) |
| `scripts/v4_registration.py` | 5 | The registration and manifest readers, the world gate, the trial check, the job gate, the dispatch check, `build_rehearsal_repo` |
| `scripts/v4_run_guard.py` | 6 | The data guard of the run: the registered pins, synthetic worlds, the full-config data run |
| `scripts/v4_diagnose.py` | 6 | Modify: `--manifest` and `--synthetic` guard modes; the default is unchanged |
| `scripts/v4_cells_guard.py` | 6 | Modify: `check_data_run` gains a `title` keyword, whose default is unchanged |
| `scripts/v4_run_plan.py` | 8 | `matrix` and `expected` |
| `scripts/v4_run_status.py` | 8 | `status.json` |
| `.github/workflows/v4-run.yml` | 9, 10 | The run's workflow |
| `src/crypto_grid_bot/v4/engine/{run,hold,arms,numbers}.py` | 11 | The step-4a engine carry-forwards, with no change to any result |
| `src/crypto_grid_bot/v4/engine/v3_as_built.py`, `scripts/v4_v3_pack.py` | 12 | The step-4a v3 and pack carry-forwards |
| `docs/superpowers/specs/2026-10-17-v4-design.md` | 13 | "Amended in the V4 step-4b PR" |
| Tests | each task | `tests/test_v4_rehearsal_world.py`, `test_v4_verdict_inputs.py`, `test_v4_verdict_rule.py`, `test_v4_verdict_cli.py`, `test_v4_registration.py`, `test_v4_run_guard.py`, `test_v4_rehearsal_force.py`, `test_v4_run_plan.py`, `test_v4_run_workflow.py`, and additions to the existing engine, v3 and pack tests |

---

### Task 1: Synthetic worlds for the rehearsal and the timing run

**Files:**
- Create: `src/crypto_grid_bot/v4/synthetic.py`, which is the content of `tests/v4_synthetic.py` moved verbatim, then extended.
- Modify: `tests/v4_synthetic.py` becomes `from crypto_grid_bot.v4.synthetic import *` plus explicit imports of every private name the tests use (find them with `grep -rhoE "from v4_synthetic import[^)]*" tests`). Its `__all__` lists them.
- Create: `scripts/v4_rehearsal.py` with the `world` and `picks` subcommands.
- Test: `tests/test_v4_rehearsal_world.py`.

**Interfaces:**
- Produces (in `crypto_grid_bot.v4.synthetic`):
  - `rehearsal_world() -> World`;
  - `timing_world(coins: int = 80, first: str = "2017-08", window_first: str = "2018-04", last: str = "2026-09") -> World`;
  - `rehearsal_v3_fields() -> V3PackFields`;
  - `REHEARSAL_PICKS: dict[int, str | None]`;
  - `CONFIG_SHA256`, which already exists.
- Produces (in `scripts/v4_rehearsal.py`):
  - `WORLD_FILE = "rehearsal.json"`, `WORLD_FORMAT = "v4-rehearsal-world-1"`, `DATA_DIR = "v4data"`, `V3_DIR = "v3pack"`;
  - `read_world(root: Path) -> dict[str, object]`, which refuses a missing, non-canonical or wrongly shaped `rehearsal.json`;
  - `main(argv) -> int`.
- `rehearsal.json` holds `{"format", "scale": "rehearsal"|"timing", "data": <run.data_record of the written world>, "v3_pack_sha256": <pin> | null}`.

The world presets have these fixed shapes; the implementer picks the paths and seeds.
- **`rehearsal_world()`:**
  - Coins: `BTCUSDT` and `ETHUSDT` with perpetuals, `SOLUSDT` with a perpetual, and `XRPUSDT` spot-only, whose closes end at 2023-06-30 23:00 (a delisting, so a dead market).
  - Spot history starts at 2020-01-01. Universes run every month from 2020-09 to 2025-03 (`XRPUSDT` is in them until 2023-06), and `World.last` is `"2025-03"`. So the window runs from 2020-09-01 00:00 to 2025-03-31 23:00: it covers V3's period and 2025-01-01.
  - BTC rises from 2020-01 to 2021-11, falls from 2021-12 to 2022-12, and rises from 2023-01 to 2025-03, with noise. So its slow vote takes both signs: `v4_btc200_shorts` and `hold_btc_trend` both trade.
- **`timing_world()`:**
  - Coins: `BTCUSDT` plus `coins - 1` coins named `S01USDT`, `S02USDT` and so on.
  - Listings start at staggered months between `first` and 2024-06. About three quarters of the coins have perpetuals, 4 of them with multiplier 1000. One coin in eight has closes that end early.
  - Each month's universe is the 10 listed, still-trading coins with the highest score from a seeded random ranking.
  - At the defaults it writes about 7 million hourly rows, the size of the real pack (7.0M).
- **`rehearsal_v3_fields()`:**
  - `BTCUSDT` and `ETHUSDT` from 2020-10-01 00:00 to `V3_END_MS - HOUR_MS`, built as `scripts/v31_smoke.py`'s `v3_fields`, with bounded paths. A plain `1.0006 ** i` would overflow over four years.
  - `REHEARSAL_PICKS` holds four stamps, as `v31_smoke.PICKS` does: one before `V3_START_MS - 40 days`, one at `V3_START_MS - 1 day`, one change inside the window, and `None` after `V3_END_MS`.

The subcommands:
- **`world --scale {rehearsal,timing} --out O`:**
  - It refuses an `O` that exists.
  - It writes `O/v4data/` (`write_world`) and, for the rehearsal scale, `O/v3pack/v3-input.pack.json.gz` (`combined.driver.v3_pack.write_v3_pack`).
  - It writes `O/rehearsal.json` last. If anything fails, it removes `O`.
  - It prints one line: the scale, the coin count, the hourly row count and the pins.
- **`picks --world O --out P`:**
  - It refuses unless `rehearsal.json` names the rehearsal scale and the pack hashes to its `v3_pack_sha256`. It also refuses if that pin equals `v4_v3_pack.EXPECTED_PACK_SHA256` (V3.1's).
  - It then replaces `combined.baseline_v3.run_walk_forward` with a stand-in for the call, as `v31_smoke.stand_ins` does: two training attempts around one short frozen replay, returning `REHEARSAL_PICKS`. The original is restored afterwards, whatever happens.
  - Inside the call, it runs `v4_v3_cell.main(["picks", "--pack", ..., "--pack-sha256", pin, "--out", P])` and returns its exit status.

- [ ] **Step 1: Move the module.** Run `git mv tests/v4_synthetic.py src/crypto_grid_bot/v4/synthetic.py`, and write the shim `tests/v4_synthetic.py`. Then run every test module that imports it (`grep -l "v4_synthetic" tests/*.py`) and expect all PASS with no test edited.
- [ ] **Step 2: Write the failing tests** in `tests/test_v4_rehearsal_world.py`, using the `network_blocked` fixture:
  - `test_rehearsal_world_window_and_pins`: `Market.load` of the `world --scale rehearsal` output has `window_start_ms == month_start("2020-09")` and `window_end_ms == month_start("2025-04") - HOUR`. Its `data.json` `config_sha256 == CONFIG_SHA256`, and `rehearsal.json`'s `data == run.data_record(market.pins)`.
  - `test_rehearsal_world_btc_vote_takes_both_signs`: BTC's slow vote (`CoinSignals(MAIN_LOOKBACKS)` over the world's daily bars) is +1 on at least 90 days and -1 on at least 90 days of the window.
  - `test_world_refuses_an_existing_folder`, and `test_world_leaves_nothing_after_a_failure` (monkeypatch `write_v3_pack` to raise).
  - `test_timing_world_shape_scaled_down`: `timing_world(coins=12, first="2023-01", window_first="2023-03", last="2023-06")` has 12 coins, `BTCUSDT` first, 10 coins in every universe month and 3 perpetuals of 4 or more. It must not write the full-size world locally.
  - `test_picks_refuses_v31s_pin_and_an_unnamed_pack`, and `test_picks_writes_the_stand_in_picks`: the picks file is canonical JSON whose picks equal `REHEARSAL_PICKS`, and `run_walk_forward` is the original again afterwards.
- [ ] **Step 3: Run them and see them fail.** Run `python -m pytest tests/test_v4_rehearsal_world.py -q`. Expect FAIL, because nothing is defined yet.
- [ ] **Step 4: Implement** the presets, `rehearsal_v3_fields`, `REHEARSAL_PICKS` and the two subcommands.
- [ ] **Step 5: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_rehearsal_world.py tests/test_v4_cell_cli.py -q`. Expect PASS.
- [ ] **Step 6: Run the static checks:** `ruff format --check .`, `ruff check .`, `mypy src scripts` and `bandit -q -r src scripts`, all clean.
- [ ] **Step 7: Commit**: `v4 step 4b: synthetic rehearsal and timing worlds`.

### Task 2: The verdict's inputs: one cell's summary, accepted or refused

**Files:**
- Create: `src/crypto_grid_bot/v4/verdict/__init__.py` (a docstring only) and `src/crypto_grid_bot/v4/verdict/inputs.py`.
- Create: `tests/v4_verdict_fixtures.py`, the shared test helper of Tasks 2, 4 and 7. `write_summary(root: Path, cell_id: str, *, outcome: str = "complete", marks: Sequence[tuple[int, str, bool]], final_after_close: str | None, equity_2025: str | None, expected: Expected, attempt: int = 1, **extra) -> Path` writes a valid `v4-summary-<cell>-attempt-<n>/` with `summary.json` (canonical, the format and keys of its arm and outcome) and a `receipt.json` whose digest it names. `expected_for(cells, ...) -> Expected` builds a matching expected document. `full_set(root, hours=50) -> Expected` writes all 48 cells.
- Test: `tests/test_v4_verdict_inputs.py`.

**Interfaces:**
- Consumes:
  - from `summary`: `SUMMARY_FORMAT`, `SUMMARY_FILE`, `FULL_OUTCOMES` and `FAILURE_OUTCOMES`;
  - from `v3_as_built`: `V3_SUMMARY_FORMAT`, `V3_ARM`, `V3_START_MS` and `V3_END_MS`;
  - from `run`: `RECEIPT_FILE`, plus `read_receipt` from `records`;
  - from `arms`: `ARMS` and `CellSpec`;
  - `_canonical` from `combined.artifacts`.
- Produces:

```python
EXPECTED_FORMAT = "v4-verdict-expected-1"
MODES = ("rehearsal", "timing", "registered")
FOLDER = re.compile(r"v4-summary-(?P<cell>[a-z0-9_]+-[0-9]+-[12]x)-attempt-(?P<attempt>[1-9][0-9]*)")
FULL_KEYS: frozenset[str]     # V4 full summary keys (pinned against summary.build_summary, Step 1)
V3_FULL_KEYS: frozenset[str]  # FULL_KEYS | {"disclosures"}
FAILURE_KEYS: Mapping[str, frozenset[str]]  # by outcome: accounting_failure, engine_error

@dataclass(frozen=True, slots=True)
class Expected:
    mode: str
    cells: tuple[str, ...]
    window: Mapping[str, int]
    data: Mapping[str, str]
    v3_pack_sha256: str | None
    picks_sha256: str | None

@dataclass(frozen=True, slots=True)
class CellFacts:
    folder: str
    cell_id: str
    arm: str
    capital: int
    cost_multiple: int
    outcome: str
    reason: str | None          # failure type for engine_error ("V3Stop", ...), identity for accounting_failure
    stop_ms: int | None
    initial_equity: Decimal
    final_equity: Decimal | None
    equity_2025: Decimal | None
    final_after_close: Decimal | None
    compounded_return: Decimal | None
    max_drawdown: Decimal | None
    eras: tuple[Mapping[str, object], ...]
    years: tuple[Mapping[str, object], ...]
    disclosures: tuple[str, ...]
    summary_sha256: str
    marks: int                  # the number of open marks (0 for a failure summary)

class CellRefused(ValueError):
    def __init__(self, step: str, reason: str) -> None: ...   # .step, .reason; reason never quotes a value

def read_expected(path: Path) -> Expected
def read_cell(folder: Path, expected: Expected) -> CellFacts      # raises CellRefused
def read_marks(folder: Path) -> list[tuple[int, Decimal, bool]]  # an accepted full cell's open marks
def facts_record(facts: CellFacts) -> dict[str, object]           # canonical-JSON-ready (Decimals as str)
def facts_from_record(record: Mapping[str, object]) -> CellFacts  # the inverse, for the progress file
```

`read_cell` applies V1 to V3 in this order. Each check failed raises `CellRefused` with its step:
1. `folder`;
2. `rerun` (attempt is not 1);
3. `json` (not canonical, or duplicate keys);
4. `format`;
5. `cell`;
6. `window`;
7. `data`;
8. `keys`;
9. `numbers`;
10. `marks`;
11. `receipt`.

The `expected.cells` list has 48 ids in `all_cells()` order (44 for timing). In timing mode `data` is the synthetic world's `data_record`, and the v3 pins are None.

- [ ] **Step 1: Write the failing tests** in `tests/test_v4_verdict_inputs.py`:
  - `test_full_keys_match_a_real_summary`: run `v4_cell.main` on `v4_synthetic`'s `tiny_world` (copy it from `tests/test_v4_cell_cli.py`; it never trades and runs in seconds). Assert `FULL_KEYS == set(summary)`, and that `read_cell` accepts the cell's folder renamed `v4-summary-v4_main-10000-1x-attempt-1/`.
  - `test_v3_full_keys_match_a_real_v3_summary`: build one v3 summary with the fixtures of `tests/test_v4_v3_as_built.py`. Assert `V3_FULL_KEYS == set(summary)`.
  - `test_refuses_a_rerun_folder`: `-attempt-2` gives step `rerun`.
  - `test_refuses_another_cells_summary`: a `hold_universe-1000-1x` summary in `v4-summary-hold_universe-10000-1x-attempt-1` gives step `cell`.
  - `test_refuses_other_data_pins`: one pin changed in `expected.data` gives step `data`.
  - `test_refuses_a_v3_summary_with_another_picks_pin` gives step `data`.
  - `test_refuses_non_canonical_bytes`: the same document with a space added gives step `json`.
  - `test_refuses_a_missing_and_an_extra_key` gives step `keys`.
  - `test_refuses_non_finite_numbers`: `"NaN"`, `"Infinity"` and `"1E+999999"` give step `numbers`.
  - `test_refuses_marks_out_of_order_and_a_first_mark_not_the_capital` gives step `marks`.
  - `test_refuses_a_receipt_with_another_digest` gives step `receipt`.
  - `test_accepts_failure_summaries_without_a_receipt_check`: an `engine_error` and an `accounting_failure` summary are accepted, with `marks == 0`.
  - `test_facts_round_trip`: `facts_from_record(facts_record(f)) == f`.
  - `test_read_expected_refuses_unknown_mode_and_extra_keys`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_verdict_inputs.py -q`. Expect FAIL with an ImportError.
- [ ] **Step 3: Implement** `inputs.py`. Read `summary.json` once, as bytes. Compare it with `_canonical(json.loads(..., object_pairs_hook=unique))`. The digest is `hashlib.sha256` of the bytes.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_verdict_inputs.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the verdict's inputs, one summary accepted or refused`.

### Task 3: The pass rule: measures, conditions and precedence

**Files:**
- Create: `src/crypto_grid_bot/v4/verdict/rule.py`.
- Test: `tests/test_v4_verdict_rule.py`.

**Interfaces:**
- Consumes:
  - from Task 2: `CellFacts` and the marks list type;
  - from `trend.metrics`: `maximum_drawdown`;
  - from `numbers`: `CONTEXT`;
  - from `run`: `LIQUIDATED`, `LIMIT_UNRESTORABLE`, `ACCOUNTING_FAILURE`, `ENGINE_ERROR` and `OUTCOME_COMPLETE`;
  - from `v3_as_built`: `V3_START_MS` and `V3_END_MS`;
  - from `market`: `HOUR_MS`.
- Produces:

```python
Mark = tuple[int, Decimal, bool]
INFINITY = Decimal("Infinity")
STOP_FAILS = frozenset({LIQUIDATED, LIMIT_UNRESTORABLE, ACCOUNTING_FAILURE})
CAPITALS_JUDGED = (1000, 10000)
REQUIRED = ("v4_main-1000-1x", "v4_main-1000-2x", "v4_main-10000-1x", "v4_main-10000-2x",
            "hold_universe-1000-1x", "hold_universe-10000-1x",
            "v3_as_built-1000-1x", "v3_as_built-10000-1x")

class Incomputable(ValueError): ...

@dataclass(frozen=True, slots=True)
class PathMeasure:
    hours: int; first_ms: int; last_ms: int
    start_equity: Decimal; end_equity: Decimal
    compounded_return: Decimal; max_drawdown: Decimal; ratio: Decimal

@dataclass(frozen=True, slots=True)
class Check:
    condition: int          # 1..4
    capital: int
    holds: bool | None      # None: incomputable or a needed cell missing
    main: PathMeasure | Decimal | None
    other: PathMeasure | Decimal | None
    note: str | None        # why it is None, in words, never a value

@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: Literal["pass", "fail", "incomplete"]
    reasons: tuple[str, ...]
    checks: tuple[Check, ...]

def ratio(compounded: Decimal, drawdown: Decimal) -> Decimal
def common_boundaries(left: Sequence[Mark], right: Sequence[Mark], *,
                      start_ms: int | None = None, end_ms: int | None = None) -> tuple[int, ...]
def after_stop(marks: Sequence[Mark], stop_ms: int, final_equity: Decimal, until_ms: int) -> list[Mark]
def path_measure(marks: Sequence[Mark], hours: Sequence[int], final: Decimal | None) -> PathMeasure
def condition_1(main: CellFacts, main_marks: Sequence[Mark], hold: CellFacts, hold_marks: Sequence[Mark]) -> Check
def condition_2(main: CellFacts, main_marks: Sequence[Mark], v3: CellFacts, v3_marks: Sequence[Mark]) -> Check
def condition_3(main_2x: CellFacts) -> Check
def condition_4(main_1x: CellFacts) -> Check
def decide(accepted: Mapping[str, CellFacts], checks: Sequence[Check], *,
           missing: Collection[str], reruns: Collection[str], dispatches: Collection[str]) -> Verdict
```

`decide` implements V10. `checks` holds the 8 checks, or fewer when a required cell is missing; a missing check counts as incomputable. `reasons` lists, in words, every cause of fail or incomplete: the stop outcomes, the missing required cells, the re-runs, the other dispatches and the incomputable conditions.

- [ ] **Step 1: Write the failing tests** in `tests/test_v4_verdict_rule.py`. The values are exact Decimals.
  - `test_ratio_zero_drawdown_rule`: `ratio(D("0.5"), D(0)) == INFINITY`, `ratio(D(0), D(0)) == 0`, `ratio(D("-0.1"), D(0)) == 0` and `ratio(D("0.5"), D("0.25")) == 2`.
  - `test_infinity_is_not_greater_than_itself`: two flat-rising paths with no drawdown give `condition_1(...).holds is False`.
  - `test_common_boundaries_skip_an_hour_incomplete_on_either_side`.
  - `test_condition_1_ends_with_the_final_after_close`: the main path `[100, 110, 105]` plus final 120 against the hold path `[100, 101, 102]` plus final 103 gives a main return of `0.2`, a drawdown of `5/110`, and `holds is True`.
  - `test_condition_2_counts_only_v3s_period`: the marks before `V3_START_MS` and after `V3_END_MS - HOUR_MS` are ignored.
  - `test_condition_2_after_a_v3_liquidation`: V6, where v3's equity after `stop_ms` is its final equity.
  - `test_conditions_3_and_4`, including `equity_2025` null, which gives `holds is None`.
  - `test_empty_common_boundaries_are_incomputable`.
  - `test_a_stop_in_any_v4_main_cell_fails_whatever_is_missing`: `v4_main-1000-2x` liquidated, with `hold_universe-10000-1x` missing, gives `outcome == "fail"`.
  - `test_engine_error_or_missing_required_cell_is_incomplete`.
  - `test_rerun_or_dispatch_is_incomplete`.
  - `test_all_eight_checks_hold_is_pass_one_false_is_fail`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_verdict_rule.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** `rule.py`. Every division and subtraction runs under `localcontext(CONTEXT)`.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_verdict_rule.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the pass rule's measures, conditions and precedence`.

### Task 4: The resumable verdict step and the run summary page

**Files:**
- Create: `src/crypto_grid_bot/v4/verdict/report.py` and `scripts/v4_verdict.py`.
- Test: `tests/test_v4_verdict_cli.py`.

**Interfaces:**
- Consumes: Tasks 2 and 3.
- Produces:

```python
# report.py
VERDICT_FORMAT = "v4-verdict-1"
PROGRESS_FORMAT = "v4-verdict-progress-1"
def verdict_document(expected: Expected, verdict: Verdict, accepted: Mapping[str, CellFacts],
                     refused: Mapping[str, tuple[str, str]], missing: Sequence[str],
                     pairs: Mapping[str, Mapping[str, object]], dispatches: Sequence[str]) -> dict[str, object]
def render_verdict_page(document: Mapping[str, object]) -> str   # Markdown

# scripts/v4_verdict.py
def main(argv: Sequence[str] | None = None) -> int
```

The command line is `--summaries S --expected E --progress P --out O [--dispatch-reasons F]`. `F` is `v4_registration.py dispatch-check --judge-all`'s output (Task 5); without it there are no dispatches. The steps are:
1. Read `E`, and list the subfolders of `S` in sorted order. Compute the inputs digest of V13.
2. If `P/progress.json` exists, its digest must equal; otherwise refuse with exit 1 and write nothing. If it does not exist, create `P`.
3. For each folder not yet in the progress, run `read_cell`, record its facts or its refusal (step and reason), and save the progress.
4. Apply V3: the re-runs, the duplicates, and `missing = expected.cells` minus the accepted cells.
5. For each of the 8 checks and each V11 pair not yet in the progress:
   - load at most two cells' marks with `read_marks`;
   - compute the measure;
   - record the `PathMeasure`, or the reason it is `Incomputable`;
   - save the progress and drop the marks.
6. Call `decide`, then write `O/verdict.json` (`verdict_document`, canonical) and `O/verdict.md` (`render_verdict_page`) under V14.
7. Print one line per phase (accepted, refused, missing, pairs computed or resumed), with counts only. The verdict's outcome is never printed.

The page has these sections, in this order:
1. A title naming the mode. Rehearsal and timing pages open with "Synthetic data: this is a test of the pipeline, not a result".
2. The verdict and its reasons.
3. The four conditions at each capital, with both sides' numbers (return, drawdown, ratio).
4. The spec's note: "Only the third era, 2025-01-01 to the end, was unseen when V4 was designed, so a pass means promising, not proven."
5. The comparison table: every arm by capital by cost, with outcome, return, drawdown, return over drawdown, the condition-1 measure against `hold_universe` and the condition-2 return against `v3_as_built`.
6. The eras.
7. The variants and neighbours beside `v4_main` at 1x.
8. The disclosures: every `disclosures` entry of the v3 summaries, so that the 1,000 USDT adapter is named, and the synthetic world in a rehearsal.
9. The missing, refused and re-run cells, and other dispatches.
10. The analysis artifact's name (V12).

Every value is escaped for Markdown: `|`, backticks and line breaks.

- [ ] **Step 1: Write the failing tests** in `tests/test_v4_verdict_cli.py`. `tests/v4_verdict_fixtures.py`'s `full_set` writes hand-built summaries, valid by Task 2's checks, into `S`, with about 50 hours a cell so the tests stay fast.
  - `test_writes_the_verdict_and_the_page`: all 48 cells are accepted, `verdict.json` is canonical, and the page has every section.
  - `test_resume_gives_the_same_bytes`: monkeypatch the progress save to raise `KeyboardInterrupt` after the 10th step. The second run completes, and both output files are byte-equal to an uninterrupted run in a fresh folder.
  - `test_resume_with_changed_inputs_is_refused`: one `summary.json` is replaced between runs. Expect exit 1 and no output.
  - `test_never_holds_more_than_two_cells_marks`: monkeypatch `read_marks` as `v4_verdict` sees it, so that it returns the real marks wrapped in `class _Marks(list)`; a list subclass can hold weak references. Count the live wrappers with `weakref.finalize`. The maximum at any call is at most 2.
  - `test_outputs_are_exclusive_and_the_first_is_removed_if_the_second_fails`.
  - `test_stdout_names_no_outcome_and_no_number_but_counts`: a regex finds none of `pass|fail|incomplete`, no Decimal with a point, and no equity.
  - `test_dispatch_reasons_make_it_incomplete`.
  - `test_rehearsal_page_says_synthetic`, and `test_v3_adapter_disclosed`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_verdict_cli.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** `report.py` and `scripts/v4_verdict.py`. The module docstring follows `scripts/v4_diagnose.py`'s pattern: the arguments, the steps, the exit statuses and the output rule.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_verdict_cli.py tests/test_v4_verdict_rule.py tests/test_v4_verdict_inputs.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the resumable verdict step and its page`.

### Task 5: Registration, the job gate and the dispatch check

**Files:**
- Create: `scripts/v4_registration.py`.
- Test: `tests/test_v4_registration.py`.

**Interfaces:**
- Consumes these, imported, never edited:
  - from `v31_driver`: `canonical`, `file_sha256`, `strict_json`, `_sha`, `_committed`, `TransientGitHubError`, `CurrentRunMissing`, `GitHubNotFound`, `DeadlineExpired`, `_Deadline`, `EarlierLaunch`, `_run_fields`, `github_json`, `_listing`, `run_jobs`, `github_retry`, `_job_fields_error` and `job_listing_error`;
  - from `trial_register`: `check_ready`;
  - from `crypto_grid_bot.combined.driver.run_cell`: `changed_since`, `head_commit` and `_allowed`.
- Produces:

```python
REGISTRATION = "config/v4_registration.json"; RUN_MANIFEST = "config/v4_run_manifest.json"
TRIAL_REGISTER = "docs/trials/register.jsonl"; REHEARSAL_MARKER = "config/v4_rehearsal.json"
V4_FAMILY = "spec-v4.0"; WORKFLOW_FILE = "v4-run.yml"
REGISTRATION_SCHEMA = "v4-registration-1"; MANIFEST_SCHEMA = "v4-run-manifest-1"
DISPATCH_CHECK_SCHEMA = "v4-dispatch-check-1"
ALLOWED = frozenset({REGISTRATION, RUN_MANIFEST, TRIAL_REGISTER})
JOB_STARTED = "V4_JOB_STARTED"; PLAN_JOB_BUDGET = 25 * 60; VERDICT_JOB_BUDGET = 55 * 60
PLAN_JOB = "plan"; STATUS_JOB = "status"
SKIPPED_JOBS = ("v3-pack", "v3-picks", "scenarios", "verdict", "analysis")
SKIPPED_MATRIX_JOBS = ("cell", "v3-cell")

@dataclass(frozen=True, slots=True)
class RunManifest:
    data: Mapping[str, str]   # config_path, config_sha256, end_month, daily_sha256, index_sha256
    v3_pack_sha256: str
@dataclass(frozen=True, slots=True)
class Registration:
    code_pin: str; run_manifest_sha256: str; spec: Mapping[str, str]
    cells: tuple[str, ...]; trial_id: str
@dataclass(frozen=True, slots=True)
class Gated:
    head: str; registration: Registration; manifest: RunManifest; registration_sha256: str

class GateError(ValueError): ...     # .errors: tuple[str, ...]
def read_manifest(raw: bytes) -> RunManifest
def read_registration(raw: bytes) -> Registration
def marker_bytes() -> bytes
def world_errors(repo: Path, mode: str, code_pin: str) -> list[str]
def trial_errors(repo: Path, head: str, *, code_pin: str, registration_sha256: str,
                 manifest_sha256: str) -> list[str]
def gate(repo: Path, mode: Literal["registered", "rehearsal"], registration_sha256: str) -> Gated
def registered_title(registration_sha256: str) -> str
def run_titles(mode: str, registration_sha256: str) -> tuple[str, ...]
def workflow_runs(repository: str, token: str, opener: object) -> list[object]
def other_dispatches(runs: Sequence[object], current: int, registration_sha256: str, *,
                     mode: str = "registered") -> tuple[int, ...]
def launch_decision(run: object, jobs: object) -> tuple[str | None, bool]
def dispatch_check(registration_sha256: str, opener: object | None = None, *, mode: str,
                   sleep: Callable[[float], None], clock: Callable[[], float], wall: Callable[[], float],
                   job_budget: int, log: Callable[[str], None], report_only: bool,
                   judge_all: bool) -> tuple[EarlierLaunch, ...]
def build_rehearsal_repo(root: Path, checkout: Path, manifest: RunManifest) -> tuple[Path, str]
def main(argv: Sequence[str] | None = None) -> int
```

The subcommands:
- **`gate --repo R --mode M --registration-sha256 S [--github-output F]`:**
  - runs `gate`;
  - writes `code_pin`, `v3_pack_sha256` and the manifest's data pins to `F` as `key=value` lines;
  - prints one accepted line, or the errors one per line, then exits 1.
- **`dispatch-check --mode M --registration-sha256 S [--report-only] [--judge-all] [--out F]`:**
  - mirrors `v31_driver.dispatch_check_command` with V4's constants;
  - `--out` writes `{"format": DISPATCH_CHECK_SCHEMA, "earlier": [<one line per counted launch>]}`.

Every function that V3.1 hard-codes is copied with V4's constants, and its docstring names the V3.1 original it copies, by function and line: `trial_errors`, `world_gate`, `job_gate`, `workflow_runs`, `registered_title`, `run_titles`, `other_dispatches`, `_job_kind`, `launch_decision`, `launch_reason`, `_judge`, `dispatch_check`, `dispatch_reasons` and `dispatch_check_command`.

`build_rehearsal_repo` builds a git repository in `root/repo` with three commits, as `v31_smoke.build_world` does:
1. The spec file at its real path, plus `docs/trials/register.jsonl` with the checkout's events and one synthetic `registration` event: trial `v4-0-synthetic`, family `spec-v4.0`, with `spec` pinned to the copied spec.
2. The code pin: the checkout's tracked `src/**`, `scripts/**`, `pyproject.toml` and `requirements-dev.lock`, plus `REHEARSAL_MARKER` with `marker_bytes()`.
3. `RUN_MANIFEST` (from `manifest`), `REGISTRATION` (code pin, the manifest's SHA-256, the spec, the 48 cells, trial `v4-0-synthetic`) and the `completion` event.

It returns the repository's path and the registration's SHA-256. It runs `git` with `-c user.name=v4-rehearsal -c user.email=rehearsal@invalid` and no global config.

- [ ] **Step 1: Write the failing tests** in `tests/test_v4_registration.py`. Model them on `tests/test_v31_driver_cli.py`'s gate and dispatch-check tests; GitHub is a fake opener and the network is blocked.
  - `test_read_registration_and_manifest_exact_keys`: one missing key and one extra key are each refused, and so are cells not equal to `all_cells()`.
  - `test_gate_accepts_the_rehearsal_repo`: use `build_rehearsal_repo` with a manifest of synthetic pins.
  - `test_gate_refuses_a_changed_file_outside_the_allowed_set`: an edit to `scripts/v4_cell.py` after the code pin.
  - `test_gate_refuses_a_wrong_registration_sha`, and `test_gate_refuses_a_manifest_that_is_not_the_registrations`.
  - `test_registered_mode_refuses_the_marker`: the rehearsal repo gated as `registered`.
  - `test_rehearsal_mode_requires_the_marker`.
  - `test_trial_errors_need_one_completion_of_family_spec_v4`.
  - `test_registered_title`: `registered_title("ab"*32) == "v4-run registered " + "ab"*32`. The check against the workflow's `run-name` is Task 9's `test_run_name_matches_registration_titles`.
  - `test_other_dispatches_counts_an_earlier_and_a_same_second_run`.
  - `test_launch_decision_uncounted_only_when_plan_failed_and_the_rest_skipped`: with V4's job names.
  - `test_dispatch_check_retries_transient_errors_then_fails_closed`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_registration.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** `scripts/v4_registration.py`.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_registration.py tests/test_v31_driver_cli.py -q`. Expect PASS, with V3.1's tests unchanged.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: registration, job gate and dispatch check`.

### Task 6: The run guard and the analysis on the run's data

**Files:**
- Create: `scripts/v4_run_guard.py`.
- Modify:
  - `scripts/v4_cells_guard.py`: `check_data_run(run, run_id, head_sha, *, title: str = DATA_RUN_TITLE)`. The default and every existing call are unchanged.
  - `scripts/v4_diagnose.py`: a mutually exclusive `--manifest M` | `--synthetic` option; update the docstring's step 2.
- Test: `tests/test_v4_run_guard.py`, and additions to `tests/test_v4_diagnose.py`.

**Interfaces:**
- Consumes:
  - Task 5's `read_manifest`;
  - `v4_cells_guard`'s `DATA_FORMAT`, `DATA_FILE`, `_unique_keys` and `check_data_run`;
  - `synthetic.CONFIG_SHA256`.
- Produces:

```python
FULL_DATA_RUN_TITLE = "v4-data full config/v4_data.json"
def check_registered_data(data_dir: Path, manifest: RunManifest, repo: Path) -> dict[str, str]
def check_synthetic_data(data_dir: Path) -> dict[str, str]
def main(argv: Sequence[str] | None = None) -> int
```

The command line:
- **`--data D --manifest M [--repo R]`:**
  - `data.json`'s `config_sha256`, `end_month` and the `daily` and `hourly_index` pins must equal `M`'s `data`;
  - `R/config_path` must hash to `config_sha256`;
  - it prints `v4_run_guard: data end_month <m>, config_sha256 <pin>: accepted (registered pins)`.
- **`--data D --synthetic`:** `config_sha256` must be `CONFIG_SHA256`.
- **`--data-run ID --commit C`:** the run's JSON on standard input, checked by `check_data_run(..., title=FULL_DATA_RUN_TITLE)`.

The `--latest-month` bound does not exist here, because the registered run is where 2025+ data is opened (v4-d03). `v4_diagnose.py --manifest M` and `--synthetic` call `v4_run_guard`'s checks instead of `v4_cells_guard.main` and skip the `LATEST_ALLOWED` check. With neither option, its behavior is byte-for-byte today's.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_guard_accepts_the_manifests_pins`;
  - `test_run_guard_refuses_other_pins`: each of the 4 pins changed in turn;
  - `test_run_guard_refuses_a_config_file_with_another_hash`;
  - `test_run_guard_synthetic_accepts_only_the_synthetic_pin`: the real pre-2025 config's pin is refused;
  - `test_full_data_run_check`: the right title, another title, a failed conclusion, another `head_sha`;
  - `test_diagnose_default_still_refuses_2025`: `v4_synthetic`'s `cli_world` reaches 2025-02, and with no option it is refused as today;
  - `test_diagnose_synthetic_accepts_a_2025_world`;
  - `test_diagnose_manifest_refuses_other_pins`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_run_guard.py tests/test_v4_diagnose.py -q`. Expect FAIL in the new tests only.
- [ ] **Step 3: Implement** the guard and the two small modifications.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_run_guard.py tests/test_v4_diagnose.py tests/test_v4_cells_guard.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the run's data guard and the analysis on the run's data`.

### Task 7: The rehearsal world repository, forced outcomes and scenario checks

**Files:**
- Modify: `scripts/v4_rehearsal.py`. `world --scale rehearsal` also writes `O/world.tar`, the repository of Task 5's `build_rehearsal_repo` with the manifest of `rehearsal.json`'s pins, and records `registration_sha256` in `rehearsal.json`. Add the `force`, `scenarios` and `check` subcommands.
- Test: `tests/test_v4_rehearsal_force.py`.

**Interfaces:**
- Consumes:
  - Task 1's world;
  - Task 5's `build_rehearsal_repo` and `RunManifest`;
  - the `main` functions of `v4_cell` and `v4_v3_cell`;
  - Task 2's `FOLDER`.
- Produces:

```python
FORCED = (
    "liquidated",
    "limit_unrestorable",
    "accounting_failure",
    "engine_error",
    "v3_stop",
    "v3_accounting",
)
FORCE_FROM_MS = month_bounds_ms("2024-06")[0]  # the first hour a forced fault may hit
FORCED_CELL = {
    "v3_stop": "v3_as_built-1000-1x",
    "v3_accounting": "v3_as_built-1000-1x",
}  # others: "v4_main-1000-1x"
SCENARIOS: Mapping[str, str]  # name -> expected verdict outcome, see below
SCENARIOS_FILE = "scenarios.json"
```

**`force --world O --kind K --out F [--picks P --picks-sha256 T]`.** It refuses a world whose `rehearsal.json` is not the rehearsal scale, or whose data's `config_sha256` is not `CONFIG_SHA256`. While the cell runs, it replaces one name; the original is restored afterwards, whatever happens:
- `liquidated`: `run.liquidated` returns True for the first mark at or after `FORCE_FROM_MS`.
- `limit_unrestorable`: `run.ceiling_breached` returns True at every check at or after `FORCE_FROM_MS`, so the cut cannot restore it.
- `accounting_failure`: `run._audit_failure` returns `"wallet"` for the first audit at or after `FORCE_FROM_MS`.
- `engine_error`: `run._hourly_record` raises `RuntimeError("forced")` at `FORCE_FROM_MS`.
- `v3_stop` and `v3_accounting`: the result returned through `v3_as_built.replay_v3_baseline` gets a stop status other than `liquidation`, or `accounting_explained` False, respectively.

It then runs `v4_cell.main` or `v4_v3_cell.main run` for the forced cell into `F`, reads back the summary, and requires the forced outcome:
- `limit_unrestorable` must have reason `ceiling`;
- `engine_error` must be type `RuntimeError`, `v3_stop` type `V3Stop` and `v3_accounting` type `V3Accounting`;
- otherwise it exits 1.

**`scenarios --base S --forced F --out X`.** `S` is the downloaded `v4-summary-*` folders; `F` holds the forced cells. It writes one folder per scenario, `X/<name>/`, made of copies of `S`'s folders with these changes, and `X/scenarios.json` (`{name: expected}`):

| Scenario | Change | Expected |
|---|---|---|
| `base` | none | `pass` or `fail`, with nothing missing or refused |
| `main_liquidated` | `v4_main-1000-1x` replaced by the forced `liquidated` cell | `fail` |
| `main_limit` | likewise, `limit_unrestorable` | `fail` |
| `main_accounting` | likewise, `accounting_failure` | `fail` |
| `main_engine_error` | likewise, `engine_error` | `incomplete` |
| `hold_missing` | `hold_universe-10000-1x` removed | `incomplete` |
| `v3_stop` | `v3_as_built-1000-1x` replaced by the forced `v3_stop` cell | `incomplete` |
| `v3_accounting` | likewise, `v3_accounting` | `incomplete` |
| `rerun` | `v4_main-10000-2x`'s folder renamed `-attempt-2` | `incomplete` |
| `relabelled` | `hold_universe-1000-1x`'s files copied into `hold_universe-10000-1x`'s folder | `incomplete` |
| `liquidated_and_missing` | `main_liquidated` plus `hold_missing` | `fail` |

**`check --scenarios X --verdicts V`.** It reads `V/<name>/verdict.json` for every scenario and compares the outcome with the expected one. For `base`, it also requires no missing and no refused cell. It prints one line per scenario, `<name>: as expected` or `<name>: NOT as expected`, and exits 1 if any is not.

- [ ] **Step 1: Write the failing tests** in `tests/test_v4_rehearsal_force.py`. They use a small world: Task 1's `rehearsal_world` would replay four years per forced cell, so the tests use a `v4_synthetic` world of three months with `FORCE_FROM_MS` monkeypatched into it.
  - `test_force_each_v4_kind_gives_its_outcome`: liquidated, limit_unrestorable (reason ceiling), accounting_failure, engine_error.
  - `test_force_restores_the_engine`: after `force`, `run.liquidated` and the others are the originals.
  - `test_force_refuses_a_real_world`: a data dir whose `config_sha256` is the pre-2025 config's.
  - `test_force_v3_kinds`: using `tests/test_v4_v3_as_built.py`'s fixtures for a small v3 pack.
  - `test_scenarios_layout_and_expectations`: on `v4_verdict_fixtures.full_set`'s summaries. Then run `v4_verdict.main` on each scenario folder, and require `check` to report every scenario "as expected". This is the local proof of the scenario expectations; the GitHub rehearsal repeats it on real cells.
  - `test_check_flags_a_scenario_not_as_expected`.
  - `test_world_tar_gates_as_rehearsal`: Task 5's `gate` on the untarred `world.tar` accepts.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_rehearsal_force.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** the three subcommands and `world.tar`.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_rehearsal_force.py tests/test_v4_rehearsal_world.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: forced outcomes and rehearsal scenarios`.

### Task 8: The run plan and the status record

**Files:**
- Create: `scripts/v4_run_plan.py` and `scripts/v4_run_status.py`.
- Test: `tests/test_v4_run_plan.py`.

**Interfaces:**
- Consumes:
  - `arms.all_cells`;
  - `Market.load`, plus `run.window_record` and `run.data_record`;
  - Task 2's `Expected` format;
  - Task 5's `read_manifest`;
  - Task 1's `read_world`.
- Produces:

```python
def matrix(mode: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]  # (cells, v3 cells)
def write_expected(mode: str, data_dir: Path, out: Path, *, manifest: RunManifest | None,
                   world: Mapping[str, object] | None, picks_sha256: str | None) -> None
STATUS_FORMAT = "v4-run-status-1"
```

The subcommands:
- **`matrix --mode M --github-output F`:**
  - writes `cells`: the matrix JSON `{"include": [{"cell", "arm", "capital", "costs"}, ...]}` of the 44 non-v3 cells, in `all_cells()` order;
  - writes `v3_cells`: the 4 v3 cells, empty for timing;
  - writes `cell_ids` (comma-separated), `cells_count` and `v3_count`;
  - refuses a mode outside `MODES`.
- **`expected --mode M --data D --out E [--manifest M] [--world O] [--picks-sha256 T]`:**
  - writes Task 2's expected file;
  - `cells` holds 48 ids (44 for timing);
  - `window` and `data` come from `Market.load(D)`;
  - the v3 pins are the manifest's in registered mode, `rehearsal.json`'s in rehearsal, and none for timing;
  - `T` must be 64 lowercase hex when the mode has v3 cells.
- **`v4_run_status.py --mode M --registration-sha256 S --out F`:**
  - reads `RUN_ID`, `RUN_ATTEMPT` and `NEEDS` (the JSON of `toJSON(needs)`) from the environment;
  - writes `status.json`: `{format, mode, run_id, run_attempt, registration_sha256, jobs: {name: result}, verdict_ran: result in {success, failure}}`;
  - prints one line of counts.

- [ ] **Step 1: Write the failing tests:**
  - `test_matrix_has_44_cells_and_4_v3_cells_in_run_order`;
  - `test_matrix_timing_has_no_v3_cells`;
  - `test_expected_from_a_synthetic_world`: rehearsal mode, with `rehearsal.json` pins;
  - `test_expected_refuses_a_bad_picks_pin`;
  - `test_status_reads_needs_from_the_environment_and_writes_canonical_json`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_run_plan.py -q`. Expect FAIL.
- [ ] **Step 3: Implement** both scripts.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_run_plan.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the run plan and the status record`.

### Task 9: The workflow, part 1: plan, V3 pack, picks, cells and V3 cells

**Files:**
- Create: `.github/workflows/v4-run.yml`.
- Test: `tests/test_v4_run_workflow.py`.

**Interfaces:**
- Consumes: Tasks 1, 5, 6 and 8, plus `scripts/v4_cell.py`, `scripts/v4_v3_cell.py`, `scripts/v4_v3_pack.py` and `scripts/v4_cells_timing.py`.

The header comment follows `v31-run.yml`'s and `v4-cells.yml`'s. It covers:
- the modes;
- the operating rule: one `v4-run` at a time, never cancel or re-run a registered dispatch;
- the dispatch ref: a registered or timing run is dispatched from the registration's ref;
- the matrices, the artifacts (W1) and the re-run rule;
- v4-d03 and v4-d10.

The settings:
- `name: v4-run`, and `run-name: v4-run ${{ inputs.mode }} ${{ inputs.registration_sha256 }}`.
- `on: workflow_dispatch`, with these inputs:
  - `mode`: a choice of `rehearsal`, `timing` or `registered`, default `rehearsal`;
  - `registration_sha256`: a string, default `""`;
  - `data_run`: a string, default `""`.
- `permissions: contents: read`.
- `concurrency: {group: v4-run, cancel-in-progress: false}`.
- `env`: `MODE`, `REGISTRATION_SHA256`, `DATA_RUN`, and `V3_PACK_SHA256` (the constant of `v4-v3.yml`, the same value).
- `defaults.run.shell: bash`.

The jobs. Each one checks out with `persist-credentials: false` and runs the same 5 setup steps as `v4-cells.yml`.
- **`plan`** (60 minutes; `actions: read`). Its first step writes `V4_JOB_STARTED`. Its outputs are `cells`, `v3_cells`, `cell_ids`, `v3_pack_sha256` and `registration_sha256`.
  - `v4_run_plan.py matrix`.
  - Registered:
    1. `v4_registration.py gate --repo . --mode registered --registration-sha256 "$REGISTRATION_SHA256" --github-output "$GITHUB_OUTPUT"`;
    2. `dispatch-check --mode registered`;
    3. `gh api .../runs/$DATA_RUN | python scripts/v4_run_guard.py --data-run "$DATA_RUN" --commit "$COMMIT"`;
    4. the download of `v4-data` with `run-id` set to the data run;
    5. `v4_run_guard.py --data v4data --manifest config/v4_run_manifest.json`;
    6. the upload of `v4-data`, with a fixed name and no overwrite.
  - Rehearsal:
    1. `v4_rehearsal.py world --scale rehearsal --out world`;
    2. untar `world/world.tar`;
    3. `v4_registration.py gate --repo world/repo --mode rehearsal --registration-sha256 <from rehearsal.json>`;
    4. `dispatch-check --mode rehearsal --report-only`;
    5. `v4_run_guard.py --data world/v4data --synthetic`;
    6. the uploads of `v4-data` (from `world/v4data`), `v4-v3-pack` and `v4-rehearsal-world`.
  - Timing:
    1. `world --scale timing`;
    2. `v4_run_guard.py --synthetic`;
    3. the upload of `v4-data`.
- **`v3-pack`** (registered only; 120 minutes): `python scripts/v4_v3_pack.py --work work --out out`, then the upload of `v4-v3-pack`. Its pin must equal both the plan's `v3_pack_sha256` and `V3_PACK_SHA256`.
- **`v3-picks`** (registered and rehearsal; 300 minutes). Its output is `picks_sha256`, taken from the file it wrote, as `v4-v3.yml` takes it.
  - Registered: `v4_v3_cell.py picks`.
  - Rehearsal: `v4_rehearsal.py picks --world world`, after downloading the world artifacts.
  - It uploads `v4-v3-picks-attempt-<n>`.
- **`cell`** (a matrix of `needs.plan.outputs.cells`; `fail-fast: false`; `max-parallel: 20`; 60 minutes):
  1. download `v4-data`;
  2. run the mode's guard;
  3. registered: the gate again on `.`; rehearsal: the gate again on the untarred world;
  4. GNU time check;
  5. `/usr/bin/time -v -o "out/$CELL.time" python scripts/v4_cell.py run --data v4data --arm "$ARM" --capital "$CAPITAL" --costs "$COSTS" --out out > /dev/null`;
  6. `v4_cells_timing.py`;
  7. uploads:
     - in every mode: `v4-cell-<cell>-attempt-<n>` (the whole folder) and `v4-summary-<cell>-attempt-<n>` (the folder's `summary.json` and `receipt.json` only);
     - timing also uploads `v4-timing-cell-<cell>-attempt-<n>` (`timing.json` only). Only the `v4-timing-*` artifacts are downloaded after a timing run; the synthetic cells' own artifacts simply expire.

  Every upload uses `if: ${{ success() || steps.timing.outcome == 'failure' }}`, as `v4-cells.yml` does.
- **`v3-cell`** (registered and rehearsal; a matrix of `needs.plan.outputs.v3_cells`; 60 minutes): `v4-v3.yml`'s cells job, with the pack pin from the plan's output and the picks pin from `needs.v3-picks.outputs.picks_sha256`, checked against the file before anything runs. It uploads `v4-v3-cell-<cell>-attempt-<n>` and `v4-summary-<cell>-attempt-<n>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_v4_run_workflow.py`, modelled on `tests/test_v4_workflows.py`. Load the YAML with `yaml.safe_load`, as that file does, and reuse its regexes:
  - `test_dispatch_only_inputs_and_permissions`;
  - `test_run_name_matches_registration_titles`: the `run-name` with `registered` and `S` substituted equals `v4_registration.registered_title(S)`, and the file's name is `v4_registration.WORKFLOW_FILE`;
  - `test_every_action_pinned_and_checkout_without_credentials`;
  - `test_no_expression_inside_a_run_script`;
  - `test_every_upload_kept_one_day_and_named_per_W1`;
  - `test_registered_steps_never_call_the_rehearsal_script`: every step whose `run` mentions `v4_rehearsal.py` has an `if` that excludes `registered`;
  - `test_cells_need_plan_and_guard_first`: in `cell`, the guard step comes before the replay, and `needs` holds `plan`;
  - `test_cell_stdout_goes_to_dev_null_under_gnu_time`;
  - `test_v3_pack_pin_equals_v4_v3_and_the_pack_script`;
  - `test_plan_runs_gate_dispatch_check_and_data_run_check_before_any_download_in_registered_mode`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_run_workflow.py -q`. Expect FAIL, because the file is missing.
- [ ] **Step 3: Write** the five jobs.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_run_workflow.py tests/test_v4_workflows.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the run workflow's plan, V3 and cell jobs`.

### Task 10: The workflow, part 2: scenarios, verdict, analysis and status

**Files:**
- Modify: `.github/workflows/v4-run.yml`.
- Test: `tests/test_v4_run_workflow.py`.

The jobs:
- **`scenarios`** (rehearsal only; `needs: [plan, v3-picks]`; 60 minutes):
  - download the world;
  - `v4_rehearsal.py force` for each of the 6 kinds (`v3_*` with the picks job's pin);
  - upload `v4-forced-attempt-<n>`, one folder per kind.
- **`verdict`** (`needs: [plan, cell, v3-cell, v3-picks, scenarios]`; `if: ${{ !cancelled() && needs.plan.result == 'success' }}`; 60 minutes; `actions: read`):
  1. download `v4-data`, and `v4-summary-*` into `summaries/` (`merge-multiple: false`);
  2. `mkdir -p summaries`;
  3. `v4_run_plan.py expected`;
  4. registered: `v4_registration.py dispatch-check --mode registered --judge-all --out reasons.json`;
  5. GNU time check;
  6. `/usr/bin/time -v -o verdict.time python scripts/v4_verdict.py --summaries summaries --expected expected.json --progress progress --out verdict`, plus `--dispatch-reasons reasons.json` in registered mode;
  7. rehearsal:
     - download `v4-forced-*`;
     - run `v4_rehearsal.py scenarios --base summaries --forced forced --out scenarios`;
     - run `v4_verdict.py` once per scenario, each into its own progress and output folders;
     - run `v4_rehearsal.py check`;
  8. keep the verdict's wall time and peak memory with `v4_cells_timing.py --time-file verdict.time --verdict-dir verdict`. Add this new option to `scripts/v4_cells_timing.py`'s mutually exclusive group. It works as `--diagnosis-dir` does: it writes `<verdict dir>/verdict-timing.json` with `step` (`verdict`), `wall_seconds`, `peak_rss_mb` and `exit_status`. Test it in `tests/test_v4_cells_timing.py` (`test_verdict_dir_writes_verdict_timing`);
  9. upload:
     - registered: `v4-verdict-attempt-<n>`;
     - rehearsal: `v4-rehearsal-verdict-attempt-<n>`, holding the verdict, the scenarios' verdicts and the check's output;
     - timing: `v4-timing-verdict-attempt-<n>`, holding the timing only.
- **`analysis`** (`needs: [plan, cell]`; the same `if`; 120 minutes):
  1. download `v4-data` and `v4-cell-*`;
  2. run the mode's guard;
  3. `/usr/bin/time -v -o diagnose.time python scripts/v4_diagnose.py --data v4data --cells cells --planned "$PLANNED_CELLS" --out diagnosis`, with `--manifest config/v4_run_manifest.json` in registered mode and `--synthetic` in rehearsal and timing;
  4. timing;
  5. upload `v4-analysis-attempt-<n>`; in rehearsal, `v4-rehearsal-analysis-...`; in timing, `v4-timing-analysis-...` with the timing only.

  In timing mode the analysis reads the timing cells' `v4-cell-*` artifacts (Task 9), so the analysis is timed at real size (W2).
- **`status`** (`needs`: every job; `if: always()`; 15 minutes):
  - `v4_run_status.py`, with `NEEDS: ${{ toJSON(needs) }}` in `env`;
  - upload `v4-status-attempt-<n>` (rehearsal: `v4-rehearsal-status-...`; timing: `v4-timing-status-...`).

- [ ] **Step 1: Write the failing tests:**
  - `test_verdict_downloads_only_summaries`;
  - `test_verdict_runs_after_failed_cells_but_not_after_a_failed_plan`;
  - `test_rehearsal_verdict_checks_every_scenario`;
  - `test_registered_verdict_rechecks_other_dispatches`;
  - `test_analysis_downloads_cells_not_v3_cells`: no step downloads `v4-v3-cell-*`;
  - `test_mode_names_its_outputs`: no artifact named for registered is uploaded in rehearsal or timing, and the reverse;
  - `test_status_always_runs_and_reads_needs_through_env`;
  - `test_logs_counts_only`: every `run` of a CLI that prints an outcome redirects its standard output;
  - `test_header_says_what_the_jobs_do`.
- [ ] **Step 2: Run them and see them fail.** Run `python -m pytest tests/test_v4_run_workflow.py -q`. Expect FAIL in the new tests.
- [ ] **Step 3: Write** the four jobs.
- [ ] **Step 4: Run the tests and see them pass.** Run `python -m pytest tests/test_v4_run_workflow.py tests/test_v4_cells_timing.py -q`. Expect PASS.
- [ ] **Step 5: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 6: Commit**: `v4 step 4b: the run workflow's verdict, analysis and status`.

### Task 11: Step-4a carry-forwards: the engine

**Files:**
- Modify: `src/crypto_grid_bot/v4/engine/run.py`, `hold.py`, `arms.py` and `numbers.py`.
- Test: `tests/test_v4_engine_run.py`, `test_v4_engine_hold.py`, `test_v4_engine_arms.py` and `test_v4_cell_cli.py`.

Every result stays the same. The pins `MAIN_SUMMARY_SHA256`, `MAIN_RECORDS_SHA256` and `MAIN_FILTER_RECORDS_SHA256` in `tests/test_v4_cell_cli.py`, and the hold cells' base pins in `tests/test_v4_engine_hold.py`, must pass unchanged.

The changes:
1. One BTC daily feed:
   - Today there are three copies: `run._feed_btc`, `hold._BtcVote`'s feed, and the third the build record names. Find it with `grep -n "open_ms <= " src/crypto_grid_bot/v4/engine/*.py`.
   - Replace them with one helper, `signals.feed_completed_days(store, signals, day_ms, fed_through_ms) -> int`, or a better-fitting name and module chosen after reading the three.
2. One `_sign` helper, in `numbers.py`, in place of the three copies.
3. `arms.BTC = "BTCUSDT"`, replacing `SHORT_FILTER_COIN` and `HOLD_BTC_COIN`. Both old names stay as aliases only if a test imports them; otherwise update the tests.
4. In `_btc_shorts_allowed`, the unreachable `reading.day_ms <= day` conjunct becomes an `assert` with a message.
5. `ArmSpec.__post_init__` refuses `long_only=True` together with `confirm_readings` set, and refuses `short_filter` on a long-only arm.
6. Fix the stale docstrings the build record names.

The new tests:
- `test_confirm3_on_a_spot_only_coin`;
- `test_btc_decided_and_crossing_its_sma_on_the_same_day`;
- `test_the_no_bar_held_short_keeps_its_position_until_its_next_bar`;
- `test_hold_btc_trend_after_a_dead_market_close`;
- `test_hold_btc_trend_deferred_buy_superseded_by_a_sale`;
- CLI runs of the three new arms on `cli_world`, in `tests/test_v4_cell_cli.py`. They verify; their outcomes are not pinned.

- [ ] **Step 1: Write the new tests.** Run them, and expect PASS for the behavior tests: they pin current behavior. Expect FAIL for the `ArmSpec` refusals.
- [ ] **Step 2: Make the refactors** one at a time. After each, run `python -m pytest tests/test_v4_engine_run.py tests/test_v4_engine_hold.py tests/test_v4_engine_arms.py tests/test_v4_cell_cli.py -q` and expect PASS, with every pin unchanged.
- [ ] **Step 3: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 4: Commit**: `v4 step 4b: step-4a engine carry-forwards (no result changes)`.

### Task 12: Step-4a carry-forwards: v3_as_built and the V3 pack

**Files:**
- Modify: `src/crypto_grid_bot/v4/engine/v3_as_built.py` and `scripts/v4_v3_pack.py`.
- Test: `tests/test_v4_v3_as_built.py` and `tests/test_v4_v3_pack.py`.

The changes:
1. `test_full_agrees_with_summary_py_on_one_path`: one set of open marks and one final equity, given to `v3_as_built._full`'s period, drawdown and return rules and to `summary.py`'s `_Ending` and `maximum_drawdown`, give the same eras, years, drawdown and return.
2. A failed write leaves no partial `records.jsonl`. Remove the cell's folder on any failure after the first write, and test this with a write that raises.
3. The page head shares `summary.py`'s `_STYLE` and Content-Security-Policy by import, not a copy.
4. Add tests for the paths that lack them:
   - the `V3Stop` with a terminal event;
   - the `ReplayExecutionError` path;
   - in `v4_v3_pack.py`: the fetch of a 404, a re-run over an existing work folder, and an existing output;
   - the manifest layout assertion.

   Every one of them blocks the network.
5. Each opaque digest pin in the v3 and pack tests gets a one-line comment on how to recompute it.

- [ ] **Step 1: Write the tests.** Run `python -m pytest tests/test_v4_v3_as_built.py tests/test_v4_v3_pack.py -q` and expect FAIL only for item 2's test.
- [ ] **Step 2: Make the fixes.** Run the same command and expect PASS.
- [ ] **Step 3: Run the static checks**, as in Task 1 Step 6.
- [ ] **Step 4: Commit**: `v4 step 4b: step-4a v3 and pack carry-forwards`.

### Task 13: Spec amendment and operating notes

**Files:**
- Modify: `docs/superpowers/specs/2026-10-17-v4-design.md`, `docs/RUN_ARCHIVE.md`.

The changes:
- **The spec:**
  - add "Amended in the V4 step-4b PR (the pipeline and the verdict step)" after the step-4a amendment. It states rulings V1 to V14, G1 to G5 and W1 to W3 in the spec's own words, and that V3.1's helpers are imported unchanged;
  - under "Delivery", mark item 4 as built, with the after-merge rehearsal and timing still owed;
  - "Verification"'s review bar names Bob, so add "(Bob is out from 2026-10-24: Codex holds his reviews; owner instruction)".
- **`docs/RUN_ARCHIVE.md`:** add a "V4 run" section. It says where each `v4-run` artifact goes on E: (`E:/v4-run-<run id>/`, one folder per artifact) and that it is checked against GitHub's digests, as for the cells runs.
- [ ] **Step 1: Write** both changes. Run `python scripts/check_reports.py` and expect 0 problems.
- [ ] **Step 2: Commit**: `v4 step 4b: spec amendment and run archive notes`.

---

## After the merge (operational, the controller)

1. **Dispatch the rehearsal:** `v4-run.yml` with `mode=rehearsal`, from main.
   - Check every job's result, the scenario check's lines ("as expected" for all 11), and that the gate ran on the world.
   - Download every artifact to `E:/v4-run-<id>/`, verify GitHub's digests, and offer the owner their deletion.
2. **Dispatch the timing run:** `mode=timing`.
   - Report the cell times, peak memory and output sizes, and the verdict's and the analysis's.
   - The verdict must stay under 2 GB of memory, and its job's downloads well under 5 GB.
   - Download, then offer deletion.
3. Fix any failure in a follow-up PR, under the same review bar.
4. Record both runs in the step-4b build record.
5. **Stop.** Step 5 (registration and the registered run) waits for the owner (v4-d15).
