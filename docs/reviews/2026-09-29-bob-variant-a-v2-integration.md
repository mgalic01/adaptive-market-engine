# Bob report: Variant A trend filter wired into V2 integrated branch

Index: 2026-09-29: Variant A (daily SMA50/SMA200 trend switch) activated in `bob/v2-integrated` via `--variant-a` CLI flag.

**Date:** 2026-09-29
**Branch:** bob/v2-integrated (merged to `main` via PR #151; see also PR #154 for subsequent fixes)
**Author:** IBM Bob (owner's desktop session)
**Related:** spec v1 §3 A, `simulation/trend_switch.py`, PR #151 (v2-integrated)

---

## What was changed

### `src/crypto_grid_bot/backtest/jobs.py`

- `run_job()` gains an optional `policy: SimulationPolicy | None = None` parameter.
- `replay()` is now called with `policy=policy` and `daily=pair_daily`.
- `pair_daily` is already loaded (from the previous V2 wiring commit) when the spec
  declares `daily_warmup_start`; it is passed to both `FeatureEngine` (for structure
  analysis) and `replay()` (for Variant A's `TrendSchedule`).
- Default `policy=None` preserves V0 behaviour — existing callers are unaffected.

### `src/crypto_grid_bot/backtest/__main__.py`

- New `--variant-a` flag (`action="store_true"`).
- When set, constructs `SimulationPolicy(trend_switch=True)` and passes it to every
  `run_job` submission via the process pool.
- When not set, `policy=None` is passed — exactly V0 behaviour.

### `tests/test_backtest_cli.py`

- `fake_run()` updated to accept the new `policy=None` keyword argument so existing
  CLI tests are not broken by the extra positional arg.

---

## How Variant A works (summary for reviewers)

`TrendSchedule` (in `trend_switch.py`) classifies the traded pair's completed daily bars
into five states: **Up**, **Recovering**, **Middle**, **Down**, **Unavailable**, using the
SMA50/SMA200 cross-over state machine from spec v1 §3 A.

At each decision minute the engine receives a `TrendSignal` on the `Frame`. The signal
comes from the daily bar that closed at 00:00 UTC of the *previous* UTC day — strictly
no look-ahead. The engine enforces:

- **Up only**: new grids may only open when the state is Up.
- **Down sequence**: a Down state cancels resting buys immediately and liquidates
  inventory within 24 h (P1 exit reason `trend_exit`).
- **Minimum warm-up**: 200 completed daily bars must precede the first evaluated minute.
  The replay engine raises `ValueError` if this is not satisfied.

---

## Usage

To run the V2 backtest with Variant A enabled:

```
python -m crypto_grid_bot.backtest run \
  --spec config/datasets/practice-2022.toml \
  --config config/default.toml \
  --variant-a
```

The spec must declare `daily_warmup_start` (practice-2022 and verify-2024h1 both do).
Without `--variant-a` the run is identical to V0 (no trend filter).

---

## What this does NOT change

- The `SimulationPolicy` identity. `trend_switch=True` is already handled correctly by
  `SimulationPolicy.identity()` — it is included in the persisted form when set.
- The `Frame` structure — `trend: TrendSignal | None` was already present before this
  branch.
- Any live-trading code — `runner.py`'s `PaperSimulator` already had full Variant A
  support; this wiring only activates it in the backtest path.

---

## Test result

```
773 passed, 4 skipped, 696 subtests passed
```

— IBM Bob (owner's desktop session)
