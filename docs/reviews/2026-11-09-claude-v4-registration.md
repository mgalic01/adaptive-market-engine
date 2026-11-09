# Claude: the V4.0 registration, the locked plan of the one registered run

Index: 2026-11-09. The exact, locked registration of the one registered V4.0 run: trial `v4-0-registered-1` (family `spec-v4.0`), base `0c87fdd`, code pin `40e5ba8`, registration SHA-256 `2309be5a8cc5`, 72 cells (48 judged, 24 at 100 USDT reported only). Nothing has been dispatched

Written by Claude Code (session c5f98f3b) on branch `claude/v4-registration`, under the plan
`docs/superpowers/plans/2026-10-24-v4-step5-registration.md`. Nothing here holds a result. From the
pinning data run's log, only pins and counts were read.

## In plain words

- **What this is.** The one historical test of V4.0 is now written down exactly: the program version
  and the data by fingerprint, the 72 cells, and the pass rule. Every job of the run checks these
  fingerprints and refuses to run if any differs.
- **What is tested.** `v4_main` must pass all four conditions at both 1,000 and 10,000 USDT:
  1. a better return over maximum drawdown than holding the universe;
  2. a better return than V3 as built, over their common period;
  3. a profit at doubled costs;
  4. higher equity at the window's end than at 2025-01-01.
- **The 100 USDT cells.** They run and are reported, but they cannot change the verdict. A V4 pass
  approves nothing at EUR 100 (v4-d31).
- **What a pass means.** Promising, not proven: only the period from 2025 on was unseen when V4 was
  designed.
- **What happens next.** The reviewers check this registration, then the owner decides. The owner's
  go covers the merge, the second data run, one dispatch and the download. Nothing starts before it.
- **Real money.** None. This is a historical simulation with no exchange account and no keys.

## The owner's go (dated record)

Not given yet. Step 7 of the plan records it here, in a docs-only commit, with the time and the
owner's exact words.

## What is registered

- **The trial.** `v4-0-registered-1`, family `spec-v4.0`, no parent. The event's `hypothesis` is the
  pass rule v4-d04 with its precedence.
- **The cells.** 12 arms x 3 capitals (100, 1,000, 10,000 USDT) x 2 cost levels = 72, each run once in
  one dispatch. The 48 at 1,000 and 10,000 USDT are judged, and the 24 at 100 USDT are reported only
  (v4-d30). The run also makes one V3 pack build and one V3 picks job.
- **The arms.** `v4_main` is the only judged arm. `hold_universe` and `v3_as_built` are the comparisons
  of conditions 1 and 2. The others are reported and decide nothing: `v4_long_only`, `v4_vol25`,
  `v4_vol60`, `v4_faster`, `v4_slower`, `v4_btc200_shorts`, `v4_confirm3`, `hold_btc` and
  `hold_btc_trend`.
- **The commits.** Three on main at B, integrated with a merge commit:

| Commit | SHA | Changes |
| --- | --- | --- |
| R, the event | `f7fbfd3de944fa27dd6f5ab6536cedaa33e19438` | `docs/trials/register.jsonl` |
| P, the code pin | `40e5ba8cad74c07083bf7583d2a3e7e1a7b017cb` | `tests/test_v4_registration_committed.py` |
| C, the files | the commit that adds this review | the two JSON files, the register and this review |

Later commits on this branch change only this review.

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

The docs-only commit after this one records them, since the gate reads the commit that adds this file.

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

The run counts as the one execution as soon as its plan job passes, or if it is cancelled. None of
these can give a false pass:
- **The v3-pack or picks job fails.** The six v3 cells are skipped. The four judged ones count as
  missing, so the verdict is incomplete, or fail if a `v4_main` cell stopped.
- **A cell runs out of time or memory.** It is missing: incomplete at 1,000 or 10,000 USDT, reported
  only at 100 USDT. The other cells still run.
- **The verdict job fails.** There is no verdict until the one allowed re-run. If that fails too, it
  is computed on the owner's PC with the run's own code and recorded as a deviation (v4-d28).
- **The dispatch check cannot read GitHub within its 55 minutes.** The verdict is incomplete.
- **A cancel, another re-run, a third attempt, or a second v4-run while this one is queued.** The
  verdict is incomplete.
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

## Limits of this review

- **The second data run can still stop this.** Step 9's run at the merge commit must reproduce these
  pins. If Binance changes an archive in between, the plan job refuses, and a new registration needs
  a new trial id, since the completion would then be on main.
- **Real 2025+ data is new to the cells.** The rehearsal and the timing run used synthetic data, so
  the cells' times and memory on the real window are estimates. The six v3 cells, `v4_btc200_shorts`,
  `v4_confirm3` and the 100 USDT cells have not run on real data before this run.
- **The image can move.** The jobs pin the label `ubuntu-24.04`, and GitHub updates the image behind
  it. The verdict record states the image and Python patch of the registered run.
- **The checks on the PC use Python 3.14,** while CI and the run use 3.12. The full test suite does not
  run on the PC (the owner's rule), so CI's run at the PR's merge ref governs.
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
