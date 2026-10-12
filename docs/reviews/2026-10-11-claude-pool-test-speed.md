# Claude: why the pool-size test took four minutes, and the six-day fix

Index: `PoolSizeTests` replayed a whole synthetic month six times inline and six times in the pool; the per-step cost is flat, so there is no production bug. Six replayed days, the rest of the month open-only and masked, keep the run valid and every row trading: 242.6 s to 65.8 s locally. Test and script only; the byte-identity datasets are unchanged.

- **Date and author:** 2026-10-11, Claude (session `fddeae28`), at the owner's request.
- **What it serves:** CI. The `test-and-audit` job has a 10-minute limit, its `pytest`
  step took 8 min 43 s on `main` at `5a97a3e`, and PR #269's head `59bca32` was cancelled
  twice at the limit. This test was the largest single part of that step.
- **Changed:** `tests/test_backtest_pool.py` (`PoolSizeTests`) and
  `scripts/byte_identity.py` (`build_dataset` takes an optional `replayed_days`; a new
  helper `open_only`). No file under `src/` changes.

## Why it was slow

Measured on Windows, CPython 3.14.7, 4 CPUs, with network access blocked in the probes:

| Phase of the test | Time |
| --- | --- |
| `byte_identity.build_dataset(work, "up")` | 5.7 s |
| `run_cli(...)`, `--jobs 1` (in process) | 201.8 s |
| `run_cli(...)`, `--jobs 4` (spawn pool) | 78.2 s |
| `pytest --durations` for the test, same machine | 242.6 s |

The `--mode-switch --trend-benchmark` run submits six replays (MS and ungated V0 on each
intrabar path, and D on each). The four grid replays each step `PaperSimulator.step`
178,560 times, four quotes for each of January's 44,640 minutes. Under `cProfile` each
grid replay took 97 to 106 s, each D replay 12 s, and the six masks and six cross-checks
9 s together. The profile is flat: the call counts follow the steps (714,240 `step`
calls, 4 × 178,560), the time spreads over the engine's per-step validation, risk and
regime code with no hotspot, and the inline time grows about linearly with the days
replayed (table below). The pool run is about two rounds of the same
replays on four workers. So the time is the month of replay, done twice, not a defect in
the pool or the engine, and nothing in `src/` is changed.

## The fix

The spec's unit is a month, and a traded pair's evaluation month must be complete (every
hour expected, `masking.traded_month_mask`), so the minutes cannot be shortened. The
masks can drop most of them validly: an hour whose 1h bar differs from its minutes in the
`open` alone is masked as `open-only difference`, and that convention class does not count
toward the 17% rule (`masking.real_defect_share` counts only `defects`). With
`replayed_days=6`, every BTCUSDT 1h bar from 2024-01-07 on opens at its own close. Every
archive is still complete, the run is valid (`valid: true`, no failures), and the replays
step only 2024-01-01 to 2024-01-06.

Six days is the fewest checked in which every row trades and the mode switcher holds all
three modes:

| Days replayed | `--jobs 1` | What the rows show |
| --- | --- | --- |
| 3 | 28.9 s | MS never fills; its two path rows are identical |
| 5 | 39.3 s | MS fills and range-exits, paths differ, but never enters uptrend |
| 6 | 44.2 s | MS: cash, grid and uptrend, 9 switches, 3 buys, a range exit, and a held position of 7.17599 or 7.20223 by path; V0: 11 cycles; D: 2 buys |
| 7 | 48.7 s | as 6 |
| 31 (before) | 201.8 s | |

The test now also asserts that the run is valid, that its mask is exactly BTCUSDT's
open-only span, that every row buys, and that the mode switcher spends time in each mode.
A change that makes six days too short fails there, with a message saying to raise
`REPLAYED_DAYS` rather than weaken the check.

## What the test verifies, before and after

Unchanged: one run that submits every kind of replay job, executed once in process and
once in a pool of four, and the two `results.json` documents compared whole (identity
keys set aside).

Changed, deliberately: the synthetic month used to have no masked hour, so the CLI
submitted `run_job` and `trend_job` bare. It now has a mask, so it submits them as
`functools.partial(..., masks=...)`, carrying every symbol's mask into the workers, as a
run on archives with any masked hour does. Pickling the bare jobs into a spawned worker
stays covered by `PoolJobReferenceTests`. Reviewers who want an unmasked month checked
end to end as well should say so; it costs the old four minutes.

## Evidence

- Before: `python -m pytest -p no:cacheprovider --durations=25 tests/test_backtest_pool.py`
  on `main` `5a97a3e`: 242.63 s for the test, 4 min 9.6 s for the file.
- After, same command on this branch: 65.77 s for the test, 70.9 s for the file, 8 passed.
- The byte-identity check's datasets are byte-identical: SHA-256 over every file
  `build_dataset` writes (path and bytes, sorted), before and after the change:
  `up` `ef7baa4a…6470c`, `down` `c84d4862…5110e`, `nod` `80512e4f…be42d`, the same three
  digests. `scripts/byte_identity.py check` itself was not rerun (about 20 minutes on four
  cores); its runs read only these datasets and the unchanged `run_cli`.
- It still catches a pool-only defect that keeps every label: in a temporary worktree of
  `92527e0`, `replay` was made to step the `high_first` quotes in any pool worker
  (`multiprocessing.parent_process()` set) while each row kept its job's path. The test
  failed at the final comparison: the pool's `low_first` mode-switcher row returned
  -5.7828%, the `high_first` figure, against -5.4382% in process. With three replayed
  days it could not have shown this for the mode switcher, whose two path rows were
  identical. The worktree was removed; nothing of it was committed.
- `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy src scripts`:
  clean.
