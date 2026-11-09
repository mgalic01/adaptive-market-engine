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
- **What happens next.** The reviewers check this registration, then the owner decides. The owner's
  go covers the merge, the second data run, one dispatch and the download. Nothing starts before it.
- **Real money.** None. This is a historical simulation with no exchange account and no keys.

## The owner's go (dated record)

Not given yet. Step 7 of the plan records it here, in a docs-only commit, with the time and the
owner's exact words.

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
  `hold_btc_trend`. One of their cells at 1,000 or 10,000 USDT that is missing or refused, or ends in
  `engine_error` or `accounting_failure`, still makes the verdict incomplete (v4-d25).
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

`selection` says the other 11 arms decide nothing. That is about their results. `stopping` and v4-d25
add that a missing, refused, `engine_error` or `accounting_failure` cell of theirs at 1,000 or 10,000
USDT makes the verdict incomplete, and `stopping` and v4-d25 govern.

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
- **The dispatch check cannot read GitHub within its 55 minutes.** The verdict is incomplete.
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
1. Merge with a merge commit only, never squash or rebase.
2. Nothing else lands on main from B until the dispatch.
3. Review fixes touch only `docs/reviews/` or `docs/tasks/`. Anything else stops the PR and goes to
   the owner: a rebuild keeps this trial id before the merge and needs a new one after it.
4. One v4-run at a time.
5. Never cancel a registered dispatch.
6. Never re-run a cell, the picks, the pack, the plan job or the whole run. The one exception is the
   plan's step 12a, on the owner's word.
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
  reading them:
  - **The plan job:** the gate on the repository itself, the dispatch check's refusing mode, the data
    run's check, the data guard with the manifest, and the download of the data from another run. A
    bug here stops the plan job, which does not count, so it costs no run. `v4-cells.yml` has already
    used the same pinned download action from another run.
  - **The verdict job:** the dispatch check with `--judge-all --out reasons.json`, and `v4_verdict.py`
    with `--dispatch-reasons` and the manifest's pins. The rehearsal's and the timing run's verdicts
    pass neither option. The tests cover both on small inputs (`tests/test_v4_registration.py`,
    `tests/test_v4_verdict_cli.py`), and the rehearsal's plan job read GitHub's real records in the
    check's report-only mode. This is the exposed part: a bug here shows only after the cells have run.
    It gives an incomplete verdict or none, not a pass. The one re-run would repeat it, v4-d28's
    fallback on the owner's PC uses the same code, and it is not an infrastructure failure under step
    12a, so the owner would decide what follows.
  - **The analysis job:** `v4_diagnose.py` with `--manifest`, covered by `tests/test_v4_diagnose.py`. A
    failure here leaves the verdict unaffected.
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
