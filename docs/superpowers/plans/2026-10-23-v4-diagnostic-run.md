# V4 Diagnostic Run (2018-2024) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the merged V4 engine on GitHub over real data that ends at 2024-12. The owner's request (2026-10-22) is to diagnose why V4 lost money in 2021 and 2023, looking at the market's trend and the bot's own trades. The run doubles as the spec's timing run before registration.

**Architecture:** Three pieces:
- a second data config whose end month is 2024-12, chosen by a new `config` input of the existing `v4-data` workflow;
- a new `v4-cells` workflow that downloads a `v4-data` run's packs, refuses any data whose end month is 2025-01 or later, and runs `scripts/v4_cell.py` once per requested cell in a matrix;
- `scripts/v4_diagnose.py`, run in that workflow, which turns the cells' records and the packs into a diagnosis: the market regime per month, and the bot's results broken down by month, side, exit reason, coin and cost.

Every artifact is kept 1 day, and public logs carry counts only.

**Tech Stack:** Python 3.12 standard library, pytest, GitHub Actions. No new dependency.

**Spec:** `docs/superpowers/specs/2026-10-17-v4-design.md`. See:
- "Verification": the timing run, "on real data before 2025-01 only. No market data from 2025 onward is executed before the registered run";
- "Pass rule": eras and years;
- "Records";
- "Reports".

## Global Constraints

- **Paper only.** Nothing places an order, and no keys are used.
- **The reserved window (v4-d03) is absolute.**
  - No step of this plan reads, executes or uploads market data from 2025-01 onward.
  - The pre-2025 config's `end_month` is `2024-12`.
  - The `v4-cells` workflow refuses a data run whose `data.json` `end_month` is `2025-01` or later, before any cell runs.
  - Tests never open `E:` or `F:`.
- **The owner's PC stays light.** Run only each task's focused tests locally. Then run `python -m ruff format --check .`, `python -m ruff check .`, `python -m mypy src scripts` and `python -m bandit -q -r src scripts`. The full suite runs in CI.
- **Never edit the frozen directories**: `src/crypto_grid_bot/simulation/`, `trend/`, `strategy/`, `backtest/` and `combined/`.
- **Results stay on the owner's PC.** Artifacts use `retention-days: 1`. Logs print counts only, never prices, equity or returns.
- **Workflows:** actions are pinned by SHA (copy the pins in `.github/workflows/v4-data.yml`), with `permissions: contents: read` (plus `actions: read` where a job downloads another run's artifact) and `workflow_dispatch` only.
- **Commits** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A data run that reaches 2025 or later is refused** before any cell runs, at the guard and in the workflow. Pinned in Task 2, `test_guard_refuses_a_data_run_reaching_2025`.
2. **The diagnosis never needs the whole records file in memory** (about 135 MB per V4 cell). Pinned in Task 3, `test_diagnose_streams_the_records` (a large synthetic file with a bounded peak, or a streaming-reader spy).
3. **Month and year boundaries use the open marks exactly as `summary.py` does,** so the diagnosis's year returns equal the summary's years. Pinned in Task 3, `test_year_returns_equal_the_summary`.

---

### Task 1: The pre-2025 data config

**Files:**
- Create: `config/v4_data_pre2025.json`
- Modify: `.github/workflows/v4-data.yml`
- Test: `tests/test_v4_data_config.py`, plus a new `tests/test_v4_workflows.py`

- [ ] **Step 1: Write the failing tests.**
  - `test_pre2025_config_differs_only_in_end_month`: loading both configs with the data layer's own loader gives equal values except `end_month`, which is `"2024-12"` in the new file.
  - `test_data_workflow_takes_a_config_input`: parse `.github/workflows/v4-data.yml` as text, or with the standard library only (no PyYAML; check what the repo's existing workflow tests do and follow them). Assert:
    - a `workflow_dispatch` input `config`, a choice of exactly the two config paths, defaulting to `config/v4_data.json`;
    - every `scripts/v4_data.py` call and every `v4_data_month_guard.py` call passes `--config` from that input;
    - no hard-coded `config/v4_data.json` remains outside the input's default and choices.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
  - Create the new config as a byte copy of `config/v4_data.json` with `end_month` changed. Check that `.gitattributes` keeps it LF (`config/v4_*.json`).
  - Add the input, and pass it through an env var (`CONFIG: ${{ inputs.config }}`) to every call. Put the config's basename in `run-name`.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 data: a pre-2025 config for the diagnostic run`.

### Task 2: The cells workflow and the reserved-window guard

**Files:**
- Create: `scripts/v4_cells_guard.py`, `.github/workflows/v4-cells.yml`
- Test: `tests/test_v4_cells_guard.py`, plus additions to `tests/test_v4_workflows.py`

**Interfaces:**
- `scripts/v4_cells_guard.py` has `main(argv) -> int`, called as `--data D [--latest-month YYYY-MM]` (default `2024-12`).
  - It reads `D/data.json` (format `v4-data/1`).
  - It exits 0 only if `end_month <= latest-month`, and refuses any `latest-month` after `2024-12`.
  - It prints only the end month and the verdict.
  - Bad JSON, a missing file or a wrong format exits 1.
- `v4-cells.yml`:
  - `workflow_dispatch` inputs:
    - `data_run`: the id of a `v4-data` run;
    - `arms`: comma-separated, default all eight from `arms.ARMS`;
    - `capitals`: default `10000`;
    - `costs`: default `1`.
  - Job `plan`:
    - download the `v4-data` artifact of `data_run` (`actions/download-artifact` with `run-id` and `github-token`);
    - run the guard;
    - build the matrix of cells, refusing unknown arms, capitals and costs;
    - output the matrix as JSON.
  - Job `cell`, one per matrix entry:
    - download the data again and run the guard again;
    - run `python scripts/v4_cell.py run --data v4data --arm A --capital C --costs K --out out` under `/usr/bin/time -v`, keeping its wall time and peak memory in `out/<cell_id>/timing.json` (seconds, MB, and the records size in bytes);
    - upload `v4-cell-<cell_id>` with retention 1 day.
  - Job `diagnose` (`needs: cell`):
    - download every `v4-cell-*` artifact and the data;
    - run `python scripts/v4_diagnose.py --data v4data --cells cells --planned "$PLANNED_CELLS" --out diagnosis` (amended after Codex's review of #294: `--planned` is the plan job's `cell_ids`, the cells the dispatch asked for, so only those are listed as missing);
    - upload `v4-diagnosis` with retention 1 day;
    - print counts only.

- [ ] **Step 1: Write the failing tests.**
  - `test_guard_refuses_a_data_run_reaching_2025`: a synthetic `data.json` with end month `2025-01`, and another with `2026-09`, each exit 1 with no file written.
  - `test_guard_accepts_2024_12_and_earlier`.
  - `test_guard_refuses_a_latest_month_after_2024_12`.
  - `test_guard_refuses_bad_data_json` (parametrized: missing, invalid JSON, wrong format, missing `end_month`).
  - `test_cells_workflow_guards_before_every_cell`: in `v4-cells.yml`, the guard runs in `plan` and in `cell` before `v4_cell.py`, and every upload has `retention-days: 1`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 cells: a diagnostic workflow that refuses data past 2024-12`.

### Task 3: The diagnosis

**Files:**
- Create: `scripts/v4_diagnose.py`
- Test: `tests/test_v4_diagnose.py`

**Interfaces:**
- `main(argv) -> int`, called as `--data D --cells C --planned IDS --out O` (`--planned` added after Codex's review of #294). For each cell directory under `C` it checks:
  - the receipt, through `read_receipt`;
  - the records, through `read_records`, streaming them;
  - the summary, through `summary.verify_summary`.

  It refuses a cell that fails verification.
- It writes `O/diagnosis.json` (exact Decimals as strings) and `O/diagnosis.md` (readable tables), and prints counts only.

**Contents of the diagnosis, per cell:**
- **Per calendar year and per month:**
  - the start and end open marks, the return, and the largest drawdown inside the period;
  - lifecycles opened and closed, split long and short;
  - win rate, gross profit and loss, fees, funding and profit given back;
  - the total slippage cost (sum over fills of |fill price - unslipped price| × quantity);
  - the counts of margin cuts, ceiling cuts, synthetic closes (dead market and funding month), deferrals, refused orders, cash-clip cuts and band skips.
- **Per exit reason and per coin, per year:** lifecycle count, gross P&L, fees and funding.
- **Signal behaviour per year:**
  - for each speed (fast, medium, slow), the share of coin-days up, down or warming, and the number of flips;
  - the share of coin-days with a confirmed downtrend;
  - the share of coin-days with S > 0, and with L at each of 0, 1/3, 2/3 and 1;
  - the mean number of coins with a nonzero target.

**The market regime per month**, from the packs alone, so it is the same for every cell:
- BTCUSDT's monthly return;
- its close against SMA200 at month end;
- its 30-day realised volatility, annualised;
- its SMA20-crossing count in the month, as a measure of choppiness;
- the median monthly return of the month's universe coins.

These come from `Market.daily`, using only bars of the month and before it.

- [ ] **Step 1: Write the failing tests**, on synthetic worlds from `tests/v4_synthetic.py` run through `scripts/v4_cell.py`:
  - `test_year_returns_equal_the_summary` (Review Focus 3);
  - `test_side_and_exit_breakdowns_add_up_to_the_lifecycles`: each breakdown's totals equal the sum over the lifecycle records;
  - `test_costs_add_up_to_the_fills_and_funding_records`;
  - `test_market_regime_of_a_known_path`: a steady uptrend gives "above SMA200" and a positive return, and a sawtooth path gives a high crossing count;
  - `test_diagnose_streams_the_records` (Review Focus 2);
  - `test_diagnose_refuses_a_cell_that_fails_verification`;
  - `test_output_prints_no_prices`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Use only allowed imports, and reuse `summary.py`'s helpers for open marks and periods where they exist.
- [ ] **Step 4: Run them to see them pass.** Commit: `v4 diagnose: the market regime and the bot's breakdown per year and month`.

- [ ] **Step 5: Push and open the PR.**
