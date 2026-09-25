# Task for Bob: V0's scorecard (C1–C6, R1) on the two development windows

- **Written by:** Claude, 2026-09-25. It covers the open item "check C1 and C5 against
  the V0 development runs" from the
  [closed-PR sweep](../reviews/2026-09-25-claude-closed-pr-sweep.md), and extends it to
  every criterion.
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-25-bob-v0-dev-scorecard.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), then
  [experiment spec v1](../EXPERIMENT_SPEC_V1.md) §5 (validity and the comparison mask)
  and §6 (C1–C6, R1).

## Why

No code scores the criteria yet. Computing them by hand for V0, the one variant that
exists, does three things:
- it shows where V0 stands on the development windows;
- it tests whether the criteria are well defined, since any ambiguity you hit is a
  finding;
- it gives an independent reference for the scoring code Claude will write later.

**This is a diagnostic on development windows, not a selection or a performance
claim.** Nothing is tuned or chosen from it.

## Fixed inputs

- **Commit:** the `main` you are running on. Record `git rev-parse HEAD`.
- **Datasets:** `config/datasets/practice-2022.toml` and
  `config/datasets/verify-2024h1.toml`, with their committed manifests.
- **Config:** `config/default.toml`.
- **Fees:**
  - **primary** (Revolut X): `--maker-fee 0 --taker-fee 0.0009`, which decides the
    criteria;
  - **reference** (Binance base): `--maker-fee 0.001 --taker-fee 0.001`, reported
    only.
- **V0** is the gated strategy (`"strategy": "gated grid (price-only-v1)"` in the
  results). The **ungated V0 baseline** (`"ungated grid baseline"`) is needed for C6.

## Step 1: data (the only allowed change to a tracked file)

`fetch` rewrites the dataset's manifest with today's timestamps and filters. Restore it
immediately; the replay must use the committed manifest.

```sh
set -euo pipefail
for ds in practice-2022 verify-2024h1; do
  python -m crypto_grid_bot.backtest fetch --spec config/datasets/$ds.toml --data-dir data
  git checkout -- config/datasets/$ds.manifest.json
  test -z "$(git status --porcelain)"
  python -m crypto_grid_bot.backtest verify --spec config/datasets/$ds.toml --data-dir data \
    > data/verify-$ds.json
done
```

`verify` exits 2 on any integrity failure. That is a stop condition.

## Step 2: runs

```sh
set -euo pipefail
for ds in practice-2022 verify-2024h1; do
  for fees in "0 0.0009" "0.001 0.001"; do
    set -- $fees
    python -m crypto_grid_bot.backtest run --spec config/datasets/$ds.toml \
      --data-dir data --out data/backtests --jobs 4 --maker-fee "$1" --taker-fee "$2" \
      | tee "data/run-$ds-m$1-t$2.log" || echo "exit $? for $ds $fees"
  done
done
find data/backtests -name results.json | sort | xargs sha256sum
```

`run` exits 2 when some results are invalid. That is expected for SOLUSDT in
`practice-2022` (see below), so it does not stop the task. Each dataset and fee level
writes one `results.json` with 20 (practice) or 8 (verify) results: pairs × 2 paths ×
gated/ungated.

## Step 3: the comparison mask (§5)

Before scoring, decide for each pair-window whether it is **included**, and give the
reason from the evidence:
- `verify` passed (Step 1), and the hourly cross-checks in `results.json` are clean;
- the run validity inputs (`accounting_problems`, rejected frames: see
  `src/crypto_grid_bot/backtest/replay.py` for how rejected frames are counted and
  reported);
- §5 says every `practice-2022` SOLUSDT pair-window fails the exchange-filter check
  until P4 sources historical filters. Confirm this from the results rather than
  taking it on trust.

If a mask rule cannot be decided from what the project records, say so. That is a
finding for Claude. Do not guess.

## Step 4: score (write `data/score.py`; give its SHA-256)

At **primary fees**, over V0's included runs:
- **C1 (a):** `max_drawdown_pct` ≤ 10 in every run. **C1 (b):**
  `active_max_drawdown_pct` ≤ 10 and `hard_drawdown_halts == 0` in every run. Show both
  per run.
- **C2:** for each path (`high_first`, `low_first`) the median `return_pct`, and the
  mean over all included runs. Use the §6 median rule.
- **C3:** `max_drawdown_pct` < `buy_and_hold_max_drawdown_pct` in every run. A zero
  buy-and-hold drawdown fails.
- **C4:** every included run is valid.
- **C5:** each run's rate = `completed_cycles` ÷ (window days ÷ 7). The window is
  `[first day of start, first day after end)` from the dataset spec. Compute the mean
  **exactly** with `fractions.Fraction`, from the integer counts, and print it as a
  fraction and as a decimal. Self-check: practice-2022 is 245 days and verify-2024h1
  is 182 days; if your figures differ, find out why before going on. Also report
  `time_with_inventory_pct` and the number of ISO weeks with at least one cycle.
- **C6:** for each included run, V0's `return_pct / max(max_drawdown_pct, 0.1)`
  against the ungated baseline's in the same pair, window and path. It passes if V0 is
  higher in at least 60% of runs.
- **R1:** the mean monthly return and 5 ÷ (mean monthly return fraction), or "not
  reachable". State how you converted window returns to monthly.

Then: pass or fail for each criterion, and the one-line verdict "V0 passes / fails the
development scorecard at primary fees". Repeat the table at reference fees, marked
"reported only".

**Verify beyond the minimum:** compare your return figures with
[`docs/backtests/fee-levels-2026-09.md`](../backtests/fee-levels-2026-09.md) (same
datasets, 0%/0.09% and 0.1%/0.1% columns). List any difference. The code has changed
since that report, so a difference is information, not an error, but it needs a
likely cause.

## Step 5: report

`docs/reviews/2026-09-25-bob-v0-dev-scorecard.md`:
- the commit, Python version, start and end time, every command, and the SHA-256 of
  each `results.json` and `data/score.py`;
- the mask, with reasons;
- a per-run table: dataset, pair, path, V0 return, max DD, active DD, halts,
  buy-and-hold DD, cycles, rate, and the ungated baseline's return and max DD;
- the per-criterion results and the verdict, at both fee levels;
- the comparison with the fee-level report;
- **ambiguities in the criteria** that you hit, each with the spec line and what you
  assumed;
- **Ideas and proposals** (separate): for example, what the scoring code must get
  right, what the spec should say more precisely, and which later check would be most
  useful. Each idea says why it would help. No parameter or strategy suggestions based
  on these results: this data must not steer the design.

## Stop conditions

- `verify` fails, a tracked file other than the restored manifest changes, or a run
  crashes with a traceback: stop and report.
- Anything under 2025-01 or later: never fetched here; stop if it appears.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish". Also check that
every criterion's number can be recomputed from your per-run table alone.
