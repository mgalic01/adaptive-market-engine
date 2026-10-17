# Claude: the V3.1 verdict, FAIL, and how it was computed

Index: V3.1 verdict record, written 2026-10-17 UTC. Registered run 38703911852 (trial `v3-1-registered-1`): all 324 cells completed on GitHub, the run's aggregate job failed (disk full), and the verdict was computed on the owner's PC with the frozen code under three owner decisions (v31-d30/31/32). Verdict **FAIL**: the combined arm lost 5-28% on W1, drew down up to 38%, lost at doubled costs and beat none of 32 baselines. Result files stay local ([run archive](../RUN_ARCHIVE.md)).

Author: Claude Code (session f7f187df), 2026-10-17 UTC. Branch
`claude/v3-1-verdict-record` on main `d4a4f09`. Documents only. No market data was
fetched for this record; it reads the run's own artifacts on the owner's PC.

## The run

- Dispatched once from main `d4a4f09` at 2026-10-15T08:11:32Z: "v31-run registered
  05b83150…". It was never cancelled and never re-run.
- plan, prepare, picks, run-main 174/174, run-minute 144/144 and run-v3 6/6: all
  succeeded (last cell about 18:37Z).
- **aggregate (job 116602181861) failed at 18:49:44Z**: the runner reported
  `System.IO.IOException: No space left on device` during the first `download-artifact`
  step. The 328 artifacts are 6.14 GB zipped and 107 GB unpacked. The status job
  succeeded, and the run's conclusion is failure.

## How the verdict was computed (deviations, all owner decisions)

1. **v31-d30 (2026-10-15T18:57Z): compute the verdict on the owner's PC.** The one
   aggregate-only re-run that v31-d28 allows was not used. It would run the same workflow
   on the same runner type and fail the same way.
   - All 328 artifacts were downloaded. Every zip's SHA-256 equals the digest GitHub
     recorded at upload (328/328).
   - The cells were unpacked in download-artifact's layout. No file is named for 2025 or
     later.
   - The frozen aggregate ran at `d4a4f09`, in a checkout re-made with LF line endings:
     the registered mode, `--attempt-id 38703911852-attempt-1`, and `GITHUB_RUN_ID` set to
     the run.
   - Python 3.14.7 on the PC; the workflow used 3.12. The aggregation is standard library
     and Decimal.
2. **v31-d31: more virtual memory.** The frozen aggregate holds every cell's decoded
   outcome and report at once: outcome.json totals 34.6 GB, measured at about 2.4-2.9
   bytes kept per byte. Attempt 1 hit a MemoryError at a 35.8 GB commit limit. The owner
   enlarged the page file. Attempt 2 was killed by a Windows Update restart. Attempt 3
   read everything in about 8 hours.
3. **v31-d32 (2026-10-16): skip the report rebuild.** In attempt 3, acceptance spent more
   than 30 minutes per judged cell in `experiment._matching_report`. That function
   rebuilds each saved report with `report.analyze`, using Fraction arithmetic with huge
   denominators, at least twice per cell; at that pace it would take one to two weeks.
   Attempt 4 ran the same command through a wrapper that replaces only that function,
   with the frozen body minus the rebuild and the equality test. The saved report is used
   after every other check. No frozen file was edited. The wrapper and the exact command
   are in the archive's `summary-out-4\DEVIATION.md`.
   - **Spot-check:** the full frozen rebuild was run on the 12 judged W1 `combined` cells.
     In 11, the saved report equals its rebuild. In `w1.combined.olhc.c1.research` the
     report also equals its rebuild (checked with `analyze` directly), but the cell fails
     the end-point check, because its replay stopped early
     (`replay_failure:execution_failure:ValueError`). The wrapper keeps that check, so both
     versions treat all 12 cells identically.
   - **What was not re-verified.** The saved reports of the other 300 judged cells were
     not rebuilt. They are the 192 baseline cells (42 V3, 6 hold and 144 minute grid) and
     the 108 other V3.1 component and ablation cells, which are explanatory only. The
     comparisons against baselines rest on those unrebuilt reports. Every other frozen
     check still ran on every cell:
     - each `outcome.json` decodes and re-encodes to its exact bytes;
     - each `report.json` equals the outcome's report evidence;
     - each V3.1 bundle verifies against its receipt;
     - identity and attempt pins match.
   - **The FAIL does not depend on them.** It stands on the 12 fully re-verified combined
     cells alone: 9 exceed the 30% maximum drawdown, and 6 are not profitable at doubled
     costs. Each of those is by itself a failure under the registered acceptance code
     (see the ruling under "Verdict").

**Scale finding:** the frozen aggregate could not have produced a verdict on GitHub at
real scale. It needs disk (107 GB), memory (about 75 GB) and time beyond the 335-minute
step limit. The rehearsals used three-day synthetic windows and never showed this.

## Verdict: FAIL

`verdict.json` SHA-256 `38e76612b712a7e064c3b21ef081d618701d17017f58e543db3d9d862510881d`
(attempt 4, finished 2026-10-16T21:51:51Z); `summary.md`
`68e94b678334b11e3a5fe9905102c95fe3e3690fcae0a7f58bdb6698b4c85847`.

- No re-run detected. No other dispatch.
- **Cell artifacts:** 312 W1 and 12 W0 cells are `completed`, in the aggregate's sense:
  the job wrote its completion marker `outcome.json`, and its artifacts hold together.
  0 are failed, killed, missing or invalid. A completed cell can still carry an
  **incomplete outcome**, meaning its replay or baseline did not cover the whole window.
  48 do (below).
- 535 acceptance failures:
  - 9 x full maximum drawdown above 30%;
  - 6 x doubled-cost profit not positive;
  - the rest: the combined arm does not strictly beat a baseline.

The combined arm beats 0 of 32 baselines on return in every cell.

| Full combined cell (W1) | Return | Max drawdown |
| --- | --- | --- |
| `olhc.c1.research` | incomplete (replay stopped early) | - |
| `olhc.c1.medium` / `ohlc.c1.medium` | -22.48% / -23.60% | 35.93% / 36.57% |
| `olhc.c1.small` / `ohlc.c1.small` | -17.83% / -17.83% | 30.20% / 30.21% |
| `olhc.c2.research` / `ohlc.c2.research` | -27.67% / -26.60% | 37.88% / 37.71% |
| `olhc.c2.medium` / `ohlc.c2.medium` | -27.11% / -27.01% | 37.97% / 37.99% |
| `olhc.c2.small` / `ohlc.c2.small` | -4.84% / -4.84% | 19.24% / 19.24% |
| `ohlc.c1.research` | -21.35% | 35.28% |

On the same window: `unchanged_v3_selector` +19% to +35%; V3 long-only rules +75% to
+186%; `matched_spot_hold` about +120% (an 81% drawdown); `matched_d_trend` +68% to +87%;
V0-V2 grids about -11% to +3%.

Incomplete outcomes (reported): 48 acceptance reasons, all "failed or incomplete
attempt retained":
- 40 small-capital minute-grid baseline cells;
- 8 V3.1 cells at research capital whose replay stopped with the same ValueError.

**Ruling: why the verdict is FAIL and not incomplete.** These are two different levels.
- The registration's stopping rule says "a missing, failed or invalid cell leaves the
  verdict incomplete". That rule is about cell artifacts, and all 324 completed. The
  frozen aggregate found no cell problem: `cell_reasons` is empty, and `summary.md` says
  "No cell problem beyond what acceptance sees".
- The 48 incomplete outcomes are judged by acceptance. In the registered acceptance code
  (`combined/experiment.py` at code pin `615b7a7`, the line
  `status = "fail" if failures else "incomplete" if incomplete else "pass"`), a failure
  takes precedence over missing evidence. The aggregate keeps that order: it returns
  `fail` when acceptance returns `fail`, unless a re-run or a second dispatch was
  detected, and here neither was. The registration's own selection text agrees: "a pass
  needs every comparison strictly won … else fail or incomplete".
- Incomplete outcomes can only block a pass. They cannot undo a failure that was
  observed.

This ordering is part of the registered, reviewed code that the owner's go (v31-d26)
approved. It is not a new reading, so no further owner decision was needed.

## What the analysis found (local, read-only)

Details are in the archive's `analysis\findings-2026-10-17.md`. In brief:
- every V3.1 component lost money, spot trend most;
- most trades ended at the initial two-four-hour-ATR stop;
- pullback entries were the worst entry type;
- the grid lost every year;
- the 30% shutdown fired in March-April 2023 in 9 of 12 combined cells;
- removing the trailing stop helped most (-19% to -4% at 10,000 USDT).

These findings fed the V4.0 design. It is not part of this PR or of `main`: it is
commit `9764d84` on the unpushed branch `claude/v4-design`
(`docs/superpowers/specs/2026-10-17-v4-design.md` there) and awaits the owner's review.

## The register

This PR appends one `result` event for `v3-1-registered-1`:
- run ID `38703911852`;
- status **`failed`**: the GitHub run's own conclusion, because its aggregate job
  failed;
- a reason that names the failure, the locally computed verdict FAIL and the deviations;
- the report is this file.

Ruling: `failed` is the conservative record of the registered pipeline. A verdict exists
only through owner-approved deviations. It is not recorded as `success`, which would
hide them, nor as `invalid`, which would wrongly suggest the cell results are unusable.

## Follow-ups (owed, not in this PR)

- Root cause of `replay_failure:execution_failure:ValueError` (8 V3.1 cells). The 2026-10-10
  V3 failed invocation's register entry shows a similar
  `SpotReplayExecutionError: ValueError: positive value required`. Diagnosis is step 1 of
  the V4 delivery plan.
- Any future aggregate must be resumable and memory-light, and must verify reports
  inside the cell jobs (V4 design, "Engineering").
- `docs/V3_1_SOURCE_INVENTORY.md` now says the pins are registered and points here.
