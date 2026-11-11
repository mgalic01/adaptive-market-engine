# Claude: the V4.0 registration, the locked plan of the one registered run

Index: 2026-11-09. The exact, locked registration of the one registered V4.0 run: trial `v4-0-registered-1` (family `spec-v4.0`), base `0c87fdd`, code pin `40e5ba8`, registration SHA-256 `2309be5a8cc5`, 72 cells (48 judged, 24 at 100 USDT reported only). Nothing has been dispatched

Written by Claude Code (session c5f98f3b) on branch `claude/v4-registration`, under the plan
`docs/superpowers/plans/2026-10-24-v4-step5-registration.md`. Nothing here holds a result. From the
pinning data run's log, only pins and counts were read.

## In plain words

- **What this is.** The one historical test of V4.0 is now written down exactly: the program version
  and the data by fingerprint, the 72 cells, and the pass rule. The plan job and every cell job
  check these fingerprints and refuse to run if any differs. The other jobs check out the same
  commit.
- **What is tested.** `v4_main` must pass all four conditions at both 1,000 and 10,000 USDT:
  1. a better return over maximum drawdown than holding the universe;
  2. a better return than V3 as built, over their common period;
  3. a profit at doubled costs;
  4. higher equity at the window's end than at 2025-01-01.
- **The 100 USDT cells.** They run and are reported, and their results cannot change the verdict.
  Breaking the one-shot rule still counts at any capital: a re-run of a 100 USDT cell makes the
  verdict incomplete, and a summary changed after it was accepted stops the verdict step. A V4 pass
  approves nothing at EUR 100 (v4-d31).
- **What a pass means.** Promising, not proven: only the period from 2025 on was unseen when V4 was
  designed.
- **What happens next.** The reviewers checked this registration, and the owner gave the go on
  2026-11-09. It covers the merge, the second data run, one dispatch and the download. The owner
  moved them to the night of 2026-11-11, from about 01:30 UTC (see the record).
- **Real money.** None. This is a historical simulation with no exchange account and no keys.

## The owner's go (dated record)

Given on 2026-11-09 at about 19:37 UTC (20:37 in Zagreb), in a dialog in chat. Claude asked
after Bob's `NO ISSUES`, claude[bot]'s `APPROVE` and Codex's clean review at `cf1e107`, while CI
was still running there. Claude stated S, P and the data pins, the expected run length, what the go
covers, and the outcomes that use up the run. The owner chose these four answers, each the
recommended option. The labels are copied exactly:
1. **"Go (Recommended)"**, for the official V4.0 run of registration `2309be5a`. It covers the merge
   of this PR with a merge commit, step 9's registered data run, one registered dispatch, and the
   download of every artifact to `/mnt/backups/` and its check (steps 8 to 12). Claude merges only
   if everything is green at the final head.
2. **"Tomorrow morning (Recommended)"**: the merge at about 08:00 in Zagreb on 2026-11-10, and the
   dispatch at about 09:30, after step 9's data run. Tonight stays free for the owner's MemTest86+.
3. **"Allow it (Recommended)"**: if the verdict job writes an incomplete verdict only because its
   dispatch check could not read GitHub, that counts as an infrastructure failure under step 12a.
   The verdict job may then take the run's one re-run attempt, on the owner's word at the time and
   once only. This widens step 12a, which as written covers only a job that failed. It was decided
   before any result exists. `budget` in the event already allows the one re-run after an
   infrastructure failure, and the code accepts it.
4. **"Accept both (Recommended)"**: main stays frozen from B until the dispatch, so other PRs wait.
   The result event's `status` is `success` for a pass, `failed` for a fail, and `invalid` for an
   incomplete verdict or none.

Conditions: everything green at the final head, and operating rule 8 before the merge. If the merge
cannot happen on 2026-11-10, or step 9's data run does not match, or a check is red, the dispatch
waits for the owner's word.

**2026-11-11, the new time.** The merge did not happen on 2026-11-10, so by the condition above the
run waited for the owner's word. On 2026-11-11 at about 00:47 UTC (01:47 in Zagreb), in a dialog in
chat, the owner chose these answers, the labels copied exactly:
- **"This morning, 11 Nov (Recommended)"**: the merge at about 09:00 in Zagreb on 2026-11-11, and the
  dispatch at about 10:30, after step 9's data run. The same conditions apply, and the go is otherwise
  unchanged.
- **"Not run yet"**, asked whether MemTest86+ had run: the PC's RAM is still untested (see "The PC's
  hardware" under "Limits of this review").
- **"Full Windows shutdown (Recommended)"**: the BACKUPS disk mounted read-only after a reboot,
  because Windows had left its NTFS volume in a fast-startup state. Before that, the owner had chosen
  to force it from Kali and accepted the risk, but ntfs-3g refused the force and nothing was written.
  The owner then chose a full Windows shutdown before the merge, so step 10's preflight finds the disk
  read-write.

**2026-11-11, the start moved to now.** At about 01:03 UTC (02:03 in Zagreb), the BACKUPS disk
mounted read-write after the full Windows shutdown, and Claude asked whether to start then or keep
09:00. The owner chose **"Keep 09:00 (Recommended)"**, then asked in chat why not start right away.
Claude answered that waiting buys little: no one can re-run a failed cell, any mismatch or red check
stops and waits for the owner whatever the hour, and a run ending about 09:00 leaves more of the
artifacts' day for the download. Its cost is a PC and a session left on overnight. Claude asked
"Should I start now?", and at about 01:07 UTC (02:07 in Zagreb) the owner wrote, exactly: "im fine
with PC running overnight". Claude takes that as a yes. The start is now: the merge after this
commit's reviews, step 9's data run, and the dispatch once it matches, at about 04:15 in Zagreb.
The conditions and the rest of the go are unchanged.

**Who judges answer 3.** Whether a verdict is incomplete only because the dispatch check could not
read GitHub shows in the verdict's reasons, which are read on the owner's PC only (step 12d). Claude
reads them there and reports them, and the owner decides. The event's `stopping` says a re-run makes
the verdict incomplete. The one re-run that `RERUN_JOBS` allows is not counted as one, as for the
analysis job.

## Owner decisions of 2026-11-09

The independent review raised two questions before the go, and the owner answered both in a dialog
in chat, at about 13:45 UTC (14:45 in Zagreb):
- **The end month, "Keep 2026-09".** v4-d03 says "the latest complete month". The config pinned
  2026-09 on 2026-10-20, and the owner approved the plan on 2026-10-24. Today 2026-10 is complete
  too, so one complete month is left out of the unseen era, which stays 21 months. Moving it would
  have needed a new B and every step again.
- **A comparison before the go, "Compare first".** Condition 2 uses only data that was seen, so its
  answer could be estimated without touching 2025 or later. See "Limits of this review".

## What is registered

- **The trial.** `v4-0-registered-1`, family `spec-v4.0`, no parent. The event's `hypothesis` is the
  pass rule v4-d04 with its precedence.
- **The cells.** 12 arms x 3 capitals (100, 1,000, 10,000 USDT) x 2 cost levels = 72, each run once in
  one dispatch. The 48 at 1,000 and 10,000 USDT are judged, and the 24 at 100 USDT are reported only
  (v4-d30). The run also makes one V3 pack build and one V3 picks job.
- **The arms.** `v4_main` is the only judged arm. `hold_universe` and `v3_as_built` are the comparisons
  of conditions 1 and 2. The others are reported, and their results decide nothing: `v4_long_only`,
  `v4_vol25`, `v4_vol60`, `v4_faster`, `v4_slower`, `v4_btc200_shorts`, `v4_confirm3`, `hold_btc` and
  `hold_btc_trend`. A cell of theirs or of the two comparisons at 1,000 or 10,000 USDT that is missing
  or refused, or ends in `engine_error` or `accounting_failure`, still makes the verdict incomplete
  (v4-d25).
- **The commits.** Three on main at B, integrated with a merge commit:

| Commit | SHA | Changes |
| --- | --- | --- |
| R, the event | `f7fbfd3de944fa27dd6f5ab6536cedaa33e19438` | `docs/trials/register.jsonl` |
| P, the code pin | `40e5ba8cad74c07083bf7583d2a3e7e1a7b017cb` | `tests/test_v4_registration_committed.py` |
| C, the files | the commit that adds this review | the two JSON files, the register and this review |

Later commits on this branch change only this review.

## The event's text

The event is one long line of the register, so these fields are copied from line 231 by script, for
reading. The line itself is what counts. `data` and `code` are null, as the register requires of a
first registration, and `seeds` is empty.

- **`hypothesis`:** v4_main (long and short, 40% volatility target) passes, at both capitals (1,000 and 10,000 USDT),
  all four conditions: (1) its compounded return over maximum drawdown is greater than
  hold_universe's (normal costs); (2) its compounded return is greater than v3_as_built's over
  their common period, 2021-07-01 00:00 to 2024-12-31 23:00 UTC (normal costs); (3) its net profit
  is positive at doubled costs; (4) its equity at the window's end is greater than at 2025-01-01
  00:00 UTC (normal costs). Returns and drawdowns are measured on the common hourly boundaries.
  The precedence: fail if any v4_main cell at 1,000 or 10,000 USDT is liquidated,
  limit_unrestorable or accounting_failure; otherwise incomplete if any of the 48 cells at 1,000
  and 10,000 USDT is missing, refused or engine_error (or accounting_failure outside v4_main), if
  a re-run or a second dispatch is found, or if a condition cannot be computed; otherwise pass
  only if all 8 checks hold.
- **`fees`:** Normal costs: spot fee 0.10%, futures fee 0.05% and slippage 0.05% per fill (V3.1's profile).
  Every cell also at doubled costs, all three doubled. Funding charged at the records' timestamps.
- **`folds`:** No folds. One window: from 00:00 UTC of the first month with an eligible candidate (2018-04 in the
  packs) to the end of the end month, 2026-09, which the run manifest pins. v3_as_built runs on
  V3's window, 2021-07-01 00:00 to the open of 2024-12-31 23:00, with V3's terminal mark at
  2025-01-01 00:00. Eras reported: to 2020-12-31, 2021 to 2024, and 2025-01-01 to the end.
- **`mask`:** V3's hourly masking (spec, Data). A masked hour has no bar, and nothing is interpolated.
  Conditions 1 and 2 use each pair's common hourly boundaries, and verdict.json lists every hour
  skipped. No market data from 2025-01 onward was executed before this run (v4-d03). The
  diagnostic run used data to 2024-12; the rehearsal and the timing run used synthetic data.
- **`budget`:** Exactly 72 cells (12 arms x 3 capitals x 2 cost levels), each run once in one registered dispatch
  of v4-run.yml, plus one V3 pack build and one V3 picks job. The 48 at 1,000 and 10,000 USDT are
  judged, and the 24 at 100 USDT are reported only (v4-d30). No parameter search, and no extra
  arm, capital, cost or window. Only transport retries are allowed: checksummed archive fetches
  and GitHub API reads. A single verdict-only re-run is allowed after an infrastructure failure.
- **`stopping`:** Every cell runs once, from one dispatch, never cancelled, and every outcome is kept. At 1,000 or
  10,000 USDT, a missing, refused or engine_error cell, or accounting_failure outside v4_main,
  makes the verdict incomplete (v4-d25, v4-d30). So does a re-run or a second dispatch, at any
  capital. No early stop and no tuning on results: a fail or an incomplete verdict needs a new
  bounded hypothesis.
- **`selection`:** None. scripts/v4_verdict.py judges v4_main alone, from the cells' summaries and receipts, with the
  precedence of rulings V1 to V10. The other 11 arms decide nothing.
- **`sizes`:** [100, 1000, 10000]
- **`candidates`:**
  - v4_main: the only judged arm
  - v4_long_only: reported
  - v4_vol25: reported
  - v4_vol60: reported
  - v4_faster: reported
  - v4_slower: reported
  - v4_btc200_shorts: reported, first run here (v4-d22, v4-d23)
  - v4_confirm3: reported, first run here (v4-d22)
  - hold_universe: the comparison of condition 1
  - hold_btc: reported
  - hold_btc_trend: reported (v4-d20)
  - v3_as_built: the comparison of condition 2

`budget` says "a single verdict-only re-run", as the plan's step 2 does. v4-d28, the plan's step 12a
and `RERUN_JOBS` also allow that one re-run attempt to be the analysis job, if it alone failed. That
is the same one attempt, the analysis decides nothing, and those rules govern.

`selection` says the other 11 arms decide nothing. That means no arm but `v4_main` is judged:
`hold_universe` and `v3_as_built` still supply the comparisons of conditions 1 and 2. `stopping` and
v4-d25 add that a missing, refused, `engine_error` or `accounting_failure` cell of any of the 11 at
1,000 or 10,000 USDT makes the verdict incomplete, and `stopping` and v4-d25 govern.

## Every pin

| Pin | Value |
| --- | --- |
| B, main and the spec commit | `0c87fdde51e4a55dfaa5a7cab52fa79133bff406` |
| Spec, `docs/superpowers/specs/2026-10-17-v4-design.md` | `ada8b856c45fc4be5a31e870e154884286013d5184a1c4f23ccb7871ca2b4e06` |
| Code pin P | `40e5ba8cad74c07083bf7583d2a3e7e1a7b017cb` |
| Code digest (`trial_register.code_digest`, 223 paths) | `515a4e91ef0c9b83116ab98104dac48c454b6490f212f9876e72b3afa54c21f9` |
| S, `config/v4_registration.json` | `2309be5a8cc5e44e9cfd4adc2d01880c902e88b556e1c1cb434db6c9681d42fe` |
| `config/v4_run_manifest.json` | `128f82e820cc735773f51600502de90f6e8539679004473b5bb5fa3387bcdd35` |
| Data config, `config/v4_data.json` | `7868b35a21db5e725db3febf61f4d7d8c1cee7d6729bffb939de5d4a1ea36659` |
| End month | `2026-09` |
| Daily pack | `69268e3fac006199746442486e1de38da1dc8bb1f78680c427dc474ffa8be138` |
| Hourly index | `b364ccd2c3f0cbe938f1972c3706733f10ddad2b8c146cd847a068e12fc4afe3` |
| V3 pack, the workflow's `V3_PACK_SHA256` | `8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee` |

The data run's counts, which the files do not pin but the plan's step 1 checks: 102 universe months,
81 coins, 78 perpetuals (4 of them multiplier contracts) and 7,003,893 hourly rows.

## The checks, run on this branch

All at C, `be2794195d5f81d3264d60950973fb31d9fddc6a`, on a clean worktree, on the PC (Python 3.14), on 2026-11-09 from about 13:30 UTC. Only
this review changed after them, in docs-only commits:

1. **The register.** `trial_register.py validate`, and the same with `--base-ref` B: `trial register:
   valid`.
2. **The trial.** `trial_register.py check-ready --trial-id v4-0-registered-1 --revision` C: exit 0.
3. **The job gate.** `v4_registration.py gate --mode registered` with S: accepted, naming the head, P,
   S, the manifest, the trial and 72 cells. Exit 0.
4. **The integration, rehearsed.** In a scratch clone, C was merged into B with `git merge --no-ff`.
   The same gate accepted that merge commit, and all 10 tests of
   `tests/test_v4_registration_committed.py` passed there, not skipped.
5. **The changes.** `git diff --name-only` P C lists the two JSON files, this review and the register.
6. **The pins.** `sha256sum` gives S and the manifest's pin above, the manifest's data pins equal the
   pinning data run's log field by field, and `config/v4_rehearsal.json` is absent at B, P and C and
   in the worktree.
7. **No earlier dispatch.** GitHub lists 5 `v4-run` runs, none titled `v4-run registered S`, none
   active.
8. **The docs and the format.** `check_reports.py` gives 0 problems, and `ruff format --check .` and
   `ruff check .` are clean.

**The test fails when it should.** On the scratch merge:
- a later commit changing code under `src/`: the test still passes, since it reads C and not HEAD, and
  the gate refuses that head;
- a later commit changing the trial id in `config/v4_registration.json`: 4 of the tests fail;
- a shallow clone (`--depth 2`): the test fails with a message naming the cause.

At P itself, the test skips. `git diff --quiet` B P over `src`, `scripts`, `pyproject.toml`,
`requirements-dev.lock` and `requirements.txt` finds no change.

**Not run on the PC:** the full test suite, `mypy`, `bandit` and `pip-audit`. CI runs them on the PR.

## Evidence

All three runs are on GitHub:
- **The rehearsal** [42581586528](https://github.com/mgalic01/adaptive-market-engine/actions/runs/42581586528),
  main `5e3ed10`, synthetic data, four coins, 72 cells: succeeded in 20 min 42 s, and archived at
  `/mnt/backups/v4-run-42581586528/`.
- **The timing run** [42583987899](https://github.com/mgalic01/adaptive-market-engine/actions/runs/42583987899),
  main `5e3ed10`, real size on synthetic data, no v3 cell: succeeded in 32 min 24 s, and archived at
  `/mnt/backups/v4-run-42583987899/`.
- **The pinning data run** [42614834522](https://github.com/mgalic01/adaptive-market-engine/actions/runs/42614834522),
  at B, title `v4-data full config/v4_data.json`: all 44 jobs succeeded in 1 h 15 min, from
  2026-11-09T12:10:46Z to 13:26:04Z. Image `ubuntu24/20261101.360`, Python 3.12.16. Its printed pins
  equal the table above and the plan's step 1, field by field, and its artifacts were not downloaded.

No code changed between `5e3ed10`, where the rehearsal and the timing run ran, and B: `src/`,
`scripts/`, `tests/`, `.github/`, `config/`, `pyproject.toml` and the lock files are the same.

## Expected run length

The plan's "Expected run length" has the measured figures. In short:
- the registered data run takes about 75 minutes, after the merge;
- the run itself takes about 4 to 4.5 hours, set by V3's picks (210.7 minutes in run 40040422092,
  against the job's 300);
- the 66 cells other than V3's run in about 15 minutes, at most 20 at a time. In the timing run each
  took 53 to 345 seconds against its job's 60 minutes, with 485 to 651 MB at peak;
- the verdict step took 57 seconds and the analysis 819 seconds in the timing run. The analysis
  unpacks 8.12 GB of records on a runner with 14 GB.

So the whole takes about 6 to 7 hours from the merge to an archived result. Dispatching in the Zagreb
morning leaves room for the same-day download.

## Outcomes that use up the run without a verdict

The run counts as the one execution as soon as its plan job passes, or if it is cancelled. A plan job
that fails, with every later job skipped, does not count, so it uses up nothing, and a new dispatch
then takes the owner's word. None of these can give a false pass:
- **The v3-pack or picks job fails.** The six v3 cells are skipped. The four judged ones count as
  missing, so the verdict is incomplete, or fail if a `v4_main` cell stopped.
- **A cell job fails.** That means time, memory, a lost runner, or a failed checkout, install, gate,
  data check, replay or artifact upload. The cell is missing: incomplete at 1,000 or 10,000 USDT,
  reported only at 100 USDT. The other cells still run. It may not be re-run, so one GitHub outage in
  any of the 48 judged cell jobs, or in the pack or picks job, uses up the run with an incomplete
  verdict. The one exception is a failed timing step alone: the uploads still run, so the job is red
  but the cell counts.
- **The verdict job fails.** There is no verdict until the one allowed re-run. If that fails too, it
  is computed on the owner's PC with the run's own code and recorded as a deviation (v4-d28).
- **The dispatch check cannot read GitHub.** The verdict is incomplete. Each read has five attempts,
  which take about 4 to 6 minutes (waits of 15, 30, 60 and 120 seconds, and up to 30 seconds per read),
  or about 10 at most if GitHub asks for longer waits. The whole check has 20 minutes from its start
  (`DISPATCH_DEADLINE`), and no later than 55 minutes after the job's start (`VERDICT_JOB_BUDGET`). The
  workflow's comments and the plan say 55 minutes, and the code governs. So a GitHub API outage of about
  five minutes at that moment is enough. The job does not fail in that case: it writes the incomplete
  verdict. The plan's step 12a covers a job that failed, so as written it allows no re-run here, although
  the code would accept one. The owner's answer 3 in the record above allows that one re-run.
- **The plan job hangs until its 60-minute timeout.** Only the dispatch check inside it has its own limit
  (25 minutes). The repository's comments say GitHub may report a timed-out job as cancelled, and a
  cancelled plan job counts, so this would use up the registration with no verdict. I did not check how
  GitHub reports it.
- **A cancel before the verdict job has finished, or a second v4-run while this one is queued.** GitHub
  drops a queued run, which counts as cancelled. The run writes no verdict, since the verdict job does
  not start after a cancel and a running one is stopped. It still counts as the one execution, so a
  later dispatch is refused in its plan job and writes no verdict either. Only a new trial is left.
- **A cancel after the verdict job has finished.** The verdict stands as written. Its dispatch check
  ran earlier, so it does not record the cancel, and the post-run record must state it by hand.
- **Another re-run, or a third attempt.** The verdict is incomplete.
- **The artifacts expire before the download.** They last one day, so the evidence would be lost to
  the owner's PC even with a verdict on GitHub.
- **The analysis job fails.** The verdict is unaffected, because the analysis decides nothing.

## Operating rules

The code does not enforce these, so the people who merge and dispatch must follow them:
1. Merge with a merge commit only, never squash or rebase. A flattened history loses the code pin as an
   ancestor, and the gate then refuses: checked on a fresh clone, where the gate accepts the head and a
   real merge commit into B, and refuses the same changes squashed onto B.
2. Nothing else lands on main from B until the dispatch.
3. Review fixes touch only `docs/reviews/` or `docs/tasks/`. Anything else stops the PR and goes to
   the owner: a rebuild keeps this trial id before the merge and needs a new one after it.
4. One v4-run at a time.
5. Never cancel a registered dispatch.
6. Never re-run a cell, the picks, the pack, the plan job or the whole run. The one exception is the
   plan's step 12a, on the owner's word, widened by the owner's answer 3 in the record above to a
   verdict made incomplete only by the dispatch check's failure to read GitHub.
7. One dispatch. The dispatch check refuses a second, but two made in the same second void each other,
   and a run an admin deleted is invisible to it.
8. Right before the merge, after the commit that records the owner's go, merge the final head into B
   in a scratch clone with `git merge --no-ff`, and run the job gate on that merge commit. It must
   accept. The committed test reads C, not the merge, so CI does not catch a later commit on this
   branch that touches a forbidden path, and after the merge such a slip needs a new trial id.

## Limits of this review

- **Most of the pass rule reads data already seen.** Condition 2 covers 2021-07 to 2024-12 only, and
  conditions 1 and 3 run over the whole window, mostly seen data. Only condition 4 is mainly about the
  unseen era. `v4_main` at 10,000 USDT had run on data to 2024-12 (runs 40001349425 and 40017107630),
  and V3's cells on V3's window (run 40040422092).
- **The comparison made before the go.** At the owner's word, condition 2's measure was computed with
  `verdict/rule.py` from those summaries, on the PC, and told to the owner in chat. It did not show
  condition 2 failing at 10,000 USDT. Its numbers are not given here (v4-d10). It is only an estimate
  and no part of the verdict: the engine has changed since those runs, and no `v4_main` cell at 1,000
  USDT has run on real data, so there is no estimate at that capital.
- **The second data run can still stop this.** Step 9's run at the merge commit must reproduce these
  pins. If Binance changes an archive in between, the plan job refuses, and a new registration needs
  a new trial id, since the completion would then be on main.
- **Real 2025+ data is new to the cells.** The rehearsal and the timing run used synthetic data, so
  the cells' times and memory on the real window are estimates. `v4_btc200_shorts`, `v4_confirm3`,
  `hold_btc_trend` and every 100 USDT cell, V3's included, have not run on real data before this run.
  The other arms ran on real data only to 2024-12, in the diagnostic run, and V3's four judged cells
  ran on V3's own window in run 40040422092.
- **The image can move.** The jobs pin the label `ubuntu-24.04`, and GitHub updates the image behind
  it. The verdict record states the image and Python patch of the registered run.
- **Paths the run has never taken on GitHub.** The rehearsal gates a synthetic world, and the timing
  run has no v3 cell, so these run for the first time in the registered run. No defect was found by
  reading them, and nothing has run them for real:
  - **The plan job:** the gate on the repository itself, the dispatch check's refusing mode, the data
    run's check, the data guard with the manifest, and the download of the data from another run.
    `v4-cells.yml` has already used the same pinned download action from another run. A bug here stops
    the plan job, which does not count, so it uses up no run. It still ends this trial: the code is
    pinned, so a fix needs new code, and after the merge that needs a new trial id (operating rule 3).
  - **The cell and v3-cell jobs:** the cell job runs the same gate and data guard as the plan job, in a
    job of its own. The v3-cell job runs the gate and checks the pack's and the picks' pins, with no data
    guard. A failure specific to one of these jobs comes after the plan job has passed, so it does use up
    the run.
  - **The v3-pack job and the registered picks step.** They have run only as their `v4-v3.yml`
    equivalents, in run 40040422092. A failure here also comes after the plan job has passed.
  - **The verdict job:** the dispatch check with `--judge-all --out reasons.json`,
    `v4_run_plan.py expected --mode registered`, and `v4_verdict.py --dispatch-reasons`. The rehearsal's
    and the timing run's verdict jobs take none of these. The tests cover them on small inputs
    (`tests/test_v4_registration.py`, `tests/test_v4_run_plan.py`, `tests/test_v4_verdict_cli.py`), and
    the rehearsal's plan job read GitHub's real records in the check's report-only mode. This is the
    most exposed part, since a bug here shows only after the cells have run. A crash or a refusal gives
    an incomplete verdict or none, not a pass. The one re-run would repeat it, v4-d28's fallback on the
    owner's PC uses the same code, and it is not an infrastructure failure under step 12a, so the owner
    would decide what follows.
  - **The analysis job:** `v4_diagnose.py` with `--manifest`. `tests/test_v4_diagnose.py` covers it with
    an explicit `--repo`, while the workflow leaves that option at its default, the current folder. A
    failure here leaves the verdict unaffected.
- **A silent logic bug is not ruled out.** "Cannot give a false pass" holds for the outcomes listed
  above: each of them fails or stops a step. A bug that finds nothing would not fail closed: a dispatch
  judgement that misses a re-run, a dropped reason, or a wrong expected file. Only the tests, the
  reviews by reading, and the plan job's earlier refusal and the verdict's own check of cell attempts
  stand against that.
- **V3's picks are not pinned in advance.** They come from the run's own job, and nothing compares them
  with run 40040422092.
- **The checks on the PC use Python 3.14,** while CI and the run use 3.12. The full test suite does not
  run on the PC (the owner's rule). CI runs it at the PR's merge ref and governs for the tests. For the
  merge's list of changed paths, see operating rule 8.
- **The PC's hardware.** A git pack was found corrupted on 2026-11-08, cause unknown, and the RAM has
  not been tested. The pins and git's own hashes catch a change in what was committed, and CI repeats
  the checks on another machine.
- **Who saw what.** V4 was designed after the data to 2024 had been seen, so only the third era is
  unseen. I did not audit independently that no one read data from 2025 on. The records say that no
  run executed it (v4-d03), and the data runs' logs were read for pins and counts only.
- **One copy.** After the run, the BACKUPS disk holds the only copy, by the owner's decision (v4-d32).

## The one-off script

`config/v4_run_manifest.json`, `config/v4_registration.json` and the completion event were written by
this script, kept outside the repository, with the worktree at P plus the event: SHA-256
`1fbba1708424c94f3db07b4cb06f166e67039dfc9751a4f61dfeac8e52585144`. Only the event's `recorded_at` depends on when it ran.

```text
"""One-off writer of V4.0's registration files and completion event (step-5 plan, step 4).

Usage: python write_registration.py REPO CODE_PIN EVENT_OUT
Writes config/v4_run_manifest.json and config/v4_registration.json in REPO, and the completion
event to EVENT_OUT, for `trial_register.py append`. It is kept outside the repository, because a
new file under scripts/ would change the code inventory. No market data is read.
"""

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
CODE_PIN = sys.argv[2]
EVENT_OUT = Path(sys.argv[3])
sys.path[:0] = [str(REPO / "src"), str(REPO / "scripts")]

import trial_register  # noqa: E402
import v4_registration as reg  # noqa: E402

from crypto_grid_bot.combined.artifacts import _canonical  # noqa: E402

TRIAL = "v4-0-registered-1"
REVIEW = "docs/reviews/2026-11-09-claude-v4-registration.md"
DATA_RUN = "https://github.com/mgalic01/adaptive-market-engine/actions/runs/42614834522"
DATA = {
    "config_path": "config/v4_data.json",
    "config_sha256": "7868b35a21db5e725db3febf61f4d7d8c1cee7d6729bffb939de5d4a1ea36659",
    "end_month": "2026-09",
    "daily_sha256": "69268e3fac006199746442486e1de38da1dc8bb1f78680c427dc474ffa8be138",
    "index_sha256": "b364ccd2c3f0cbe938f1972c3706733f10ddad2b8c146cd847a068e12fc4afe3",
}
V3_PACK = "8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee"


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True).stdout


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


events = trial_register.load_events(REPO / reg.TRIAL_REGISTER)
registered = next(event for event in events if event["event_id"] == f"{TRIAL}-record")
spec = registered["payload"]["spec"]

manifest = _canonical(
    {"schema": reg.MANIFEST_SCHEMA, "data": DATA, "v3_pack_sha256": V3_PACK},
)
registration = _canonical(
    {
        "schema": reg.REGISTRATION_SCHEMA,
        "code_pin": CODE_PIN,
        "run_manifest_sha256": sha(manifest),
        "spec": {"path": spec["path"], "sha256": spec["sha256"]},
        "cells": list(reg.registered_cells()),
        "trial_id": TRIAL,
    }
)
reg.read_manifest(manifest)
reg.read_registration(registration)
(REPO / reg.RUN_MANIFEST).write_bytes(manifest)
(REPO / reg.REGISTRATION).write_bytes(registration)

tracked = git("ls-tree", "-r", "--name-only", "-z", CODE_PIN).decode().split("\0")
paths = sorted(
    path
    for path in tracked
    if path.startswith(("src/", "scripts/"))
    or path in {"pyproject.toml", "requirements-dev.lock", "requirements.txt"}
)
blobs = {path: git("show", f"{CODE_PIN}:{path}") for path in paths}
event = {
    "schema_version": 1,
    "event_id": f"{TRIAL}-complete",
    "trial_id": TRIAL,
    "event_type": "completion",
    "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "agent": "Claude Code",
    "family": reg.V4_FAMILY,
    "parent_trial_id": None,
    "sources": [REVIEW, DATA_RUN],
    "payload": {
        "registration_id": f"{TRIAL}-record",
        "code_commit": CODE_PIN,
        "code_sha256": trial_register.code_digest(blobs),
        "code_paths": paths,
        "manifest": {"path": reg.RUN_MANIFEST, "sha256": sha(manifest)},
        "config": {"path": reg.REGISTRATION, "sha256": sha(registration)},
        "review": REVIEW,
    },
}
EVENT_OUT.write_text(json.dumps(event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"S {sha(registration)}")
print(f"manifest {sha(manifest)}")
print(f"code_sha256 {event['payload']['code_sha256']} paths {len(paths)}")
```
