# Claude: V4 step 4b, the run pipeline, the verdict step and the rehearsal (build record)

Index: 2026-10-24. V4 step 4b builds V4's official-run pipeline. One dispatch-only workflow, `v4-run.yml`, runs the 48 cells in three modes: rehearsal, timing and registered. A resumable verdict step judges them from their summaries and receipts only. V4's registration gate and dispatch check follow V3.1's. A synthetic rehearsal forces every stop outcome through the real CLIs and checks 11 scenarios. The step was built subagent-driven in 13 tasks, each reviewed, then given a whole-branch review and one fix wave. It stops before step 5's registration and run (v4-d15).

Written by Claude Code (session f7f187df). Plan: `docs/superpowers/plans/2026-10-24-v4-step4b-pipeline.md`. Spec: `docs/superpowers/specs/2026-10-17-v4-design.md`, which carries this step's amendment, "Amended in the V4 step-4b PR". It builds on step 4a (PR #296, 184be44) and on V3's own run on GitHub (run 40040422092: all four v3 cells complete, the pack pin V3.1's; the results are on the owner's PC).

## What it builds

| Piece | Where | What |
|---|---|---|
| Synthetic worlds | `v4/synthetic.py`, `scripts/v4_rehearsal.py world, picks` | The rehearsal world: 4 coins from 2020-09 to 2025-03, covering V3's period and 2025-01-01. The real-size timing world: 80 coins and about 7 million hourly rows. A synthetic V3 pack and stand-in picks. |
| The verdict's inputs | `v4/verdict/inputs.py` | One cell's summary is accepted or refused, with the step that failed. It checks the canonical bytes, the format, cell, window, data pins, keys, numbers, marks and receipt. Re-run and duplicate folders are refused. |
| The pass rule | `v4/verdict/rule.py` | Common boundaries, path measures and the zero-drawdown rule, the four conditions, the V6 rule for a liquidated V3, the listed skipped hours, and the precedence. |
| The verdict step | `scripts/v4_verdict.py`, `v4/verdict/report.py` | It reads one cell at a time, keeps a progress file and resumes with identical bytes. It holds at most two cells' marks at a time. It writes `verdict.json` and a plain-language `verdict.md`. |
| Registration | `scripts/v4_registration.py` | Registration and run-manifest readers, the job gate, the trial check, the rehearsal marker, the dispatch check and a builder for the rehearsal's git world. V3.1's generic helpers are imported unchanged. |
| The run's data guard | `scripts/v4_run_guard.py`, `v4_diagnose.py --manifest/--synthetic` | Registered data must carry the run manifest's pins. A rehearsal and a timing run accept synthetic data only. The full-config data run is checked through GitHub's API. The pre-2025 default is unchanged. |
| Forced outcomes | `scripts/v4_rehearsal.py force, scenarios, check` | It forces liquidated, limit_unrestorable, accounting_failure, engine_error, V3Stop and V3Accounting through the real CLIs. It builds 11 scenarios, each with its exact expected verdict, missing cells and refused cells. |
| Plan and status | `scripts/v4_run_plan.py`, `scripts/v4_run_status.py` | The matrices (44 V4 and hold cells, 4 V3 cells), the verdict's expected file, and `status.json`. |
| The workflow | `.github/workflows/v4-run.yml` | Jobs: plan, v3-pack, v3-picks, cell, v3-cell, scenarios, verdict, analysis and status. The gate comes first. Logs carry counts only, and every artifact is kept one day. |
| Step-4a carry-forwards | engine and v3 | One BTC daily feed (`signals.DailyFeed`), one `sign`, `arms.BTC` and two `ArmSpec` refusals. v3 writes clean up only what they created. The page shares its style. New tests. No result changed: every pin is identical. |

## Reviews

- **Every task** had its own spec and quality review: on the most capable model for Tasks 3, 4, 5, 7, 9, 10 and 11, otherwise on the standard model. Seven tasks needed one fix round. The reviews caught:
  - V3's pack pin compared against the gzip file instead of the JSON inside it. That would have failed every V3 job (Task 9).
  - No verdict written when V3's picks job does not succeed (Task 10).
  - The spec's "skipped hours are listed", which the plan had left out (Task 4).
  - Rehearsal scenarios that could pass for the wrong reason (Task 7).
  - Chained exceptions that could put a file's values into a public log (Task 2).
  - A cleanup that could delete another run's finished records (Task 12).
  - Registered mode not itself refusing synthetic data (Task 8).
  - One wrong test example in the plan, corrected (Task 3).
- **The whole-branch review** (most capable model) found no Critical issue: the integration is consistent end to end. It asked for two Important fixes. The first was documentation: the workflow header, comments and one spec sentence. The second was that the timing run would not measure the registered verdict job (a plan defect). The fix moves the dispatch check first, raises the verdict job's timeout to 180 minutes, times the `expected` step, and states how to scale the result. Twelve cheap minors went into the same wave. The wave's one re-review found every item addressed.
- **Locally,** only the test modules each task touched ran (owner rule: no heavy work on the owner's PC), plus ruff format and check, mypy strict, bandit and `check_reports`, all clean. The full suite runs in CI.

## Rulings made where the spec or plan was silent

Each ruling comes with its cost if it is wrong. Those that change what the run or the verdict does are also in the spec's step-4b amendment.

1. **The rehearsal world's `registration_sha256`** is in `rehearsal.json` from Task 1 on, null until Task 7 fills it. Cost: none.
2. **`REHEARSAL_PICKS`' last stamp** is the day before 2025-01-01, because V3's picks refuse any stamp from 2025 on. Cost: the synthetic v3 arm is flat on its last day.
3. **The verdict refuses summaries beyond V1's list:** V3 outcomes outside complete, liquidated and engine_error; a reason outside the limit reasons; an initial equity that is not the capital; malformed eras, years or disclosures; a Decimal exponent above 1000. Cost: a future change to the summary format must update `inputs.py` too.
4. **The plan's own test example for condition 1 was wrong.** Its hold path never falls, so its ratio is +Infinity under V5. The test now asserts that False, and the plan's True against a path with a dip. Cost: none.
5. **Wiring of `decide`.** Only accepted cells reach the fail precedence; refused and absent cells are missing (V2). Condition 1 and 2 are called only on the 1x pass-rule cells. Cost: none.
   - **Owner decision v4-d25: every cell of the run counts** (the owner's answer to Bob's review, which found the spec's "anything missing means incomplete" wider than V10's 8 required cells). After the fail precedence, any expected cell (48 in a registered run and a rehearsal, 44 in a timing run) that is missing, refused or `engine_error`, or, outside `v4_main`, `accounting_failure`, makes the verdict incomplete. A reported arm's liquidation or unrestorable limit is a result and does not. `decide` takes the expected cells; `REQUIRED` is retired. The spec's pass rule and step-4b amendment, and the plan's V10, say so. Cost: a glitch in any reported cell leaves the run without a passing verdict; the owner accepted that.
6. **A re-run folder** (attempt not 1) is refused and makes the verdict incomplete. The same cell's attempt-1 folder stays accepted, so a stopped `v4_main` in attempt 1 still fails, whatever else is missing. Cost: if a re-run should void the first attempt too, only `classify` changes.
7. **Skipped hours are listed** (the spec's "skipped ... and listed"). Each condition-1 and condition-2 check records `skipped_ms`, its hours that are not common boundaries. The page shows the counts. Cost: verdict.json grows by those hours only.
8. **The rehearsal's git world has four commits:** the spec, the registration event, the code pin and the registration files. `check_ready` needs the event to name the commit that holds its spec, as V3.1's layout does. Cost: none.
9. **The dispatch check follows V3.1's semantics.** `--judge-all` turns a failed check into a reason, so the verdict is still written, as incomplete. A registered run refuses `--report-only`; rehearsal and timing require it. Uncounted launches are only logged. Cost: none.
10. **The run guard adds no month bound.** The registered run is where 2025+ data is opened (v4-d03), and `--manifest` pins it exactly. `--manifest` also refuses the synthetic pin, as `expected` does in registered mode. Cost: none.
11. **`force` reads the forced hour from the engine's own `self._hour_ms`.** A rename fails mypy, or makes the cell an engine_error that `force` rejects. Cost: a refactor of `run.py`'s hour handling must keep the name.
12. **The rehearsal's check requires each scenario's exact missing and refused cells,** not only its outcome. Cost: none. Local verdicts already match.
13. **Every checkout uses `fetch-depth: 0`,** because the registered gate diffs against the code pin, which a shallow clone lacks. Cost: slower checkouts.
14. **When V3's picks job does not succeed,** the verdict is still written. The expected file takes a picks pin of 64 zeros, so every V3 summary is refused at step `data`, the V3 cells count as missing, and a `v4_main` stop still fails. Cost: one documented sentinel.
15. **A failed verdict or diagnosis in a timing run is still timed.** A signal kill (out of memory) is recorded as 128 + the signal, not as a clean exit. Cost: none.
16. **The timing run measures the registered verdict job as closely as it can.** The dispatch check runs first, the job's timeout is 180 minutes, and `expected` is timed. The timing verdict plans no V3 measures (46 against about 92), so its time is scaled by about two. The after-merge timing report adds the downloads and the `expected` step. Cost: an estimate, not a measurement, of the V3 half.
17. **The deferred step-4a hold test stubs `_ready`,** because a buy superseded while deferred cannot arise from data for `hold_btc_trend`. Cost: none.
18. **Bob was out from 01:24 to about 10:40 Zagreb time on 2026-10-24** (owner). Codex took his reviews for PR #296. The standing bar applies to this PR again. Cost: none.

## Deferred (non-blocking, parked in the build ledger)

The whole-branch review triaged every remaining minor as able to wait. These are:
- duplicated helpers: the run-check code, the matrix code and two regexes;
- a few hard-kept tables in `v4_rehearsal.py`;
- module sizes: `inputs.py`, `report.py`, `v4_verdict.py`, `v4_registration.py`, `v4_rehearsal.py` and `synthetic.py`;
- `escape()` leaving leading Markdown block syntax alone;
- git isolation from `GIT_*` environment variables;
- plain scenario copies, about 1.2 GB at rehearsal size;
- a few docstring nits, and a receipt race in the v3 cleanup;
- the comment and fit-rule wording points of the fix wave's re-review.

None changes a result or a verdict.

## After merge (operational)

1. **Dispatch the rehearsal** (`mode=rehearsal`) from main. Check:
   - every job's result;
   - that the gate ran on the world;
   - that all 11 scenario lines say "as expected";
   - the scenarios job's time (six sequential replays, two of them V3's 3.5-year replays).

   Then download to `E:/v4-run-<id>/`, check GitHub's digests and offer the owner the deletion.
2. **Dispatch the timing run** (`mode=timing`). Report:
   - the cell times, peak memory and output sizes;
   - the verdict's and `expected`'s times and memory, scaled as ruling 16 says, against 2 GB and the job's 180 minutes;
   - the analysis.

   Download only the `v4-timing-*` artifacts.
3. **Fix any failure** in a follow-up PR under the same review bar.
4. **Then stop.** Step 5 needs the owner: the registration files to review, and the owner's go. The owner has decided that V4.0's registered run is backed up on F:, after V3.0's and V3.1's run files are deleted. Their final record is PR #297.
