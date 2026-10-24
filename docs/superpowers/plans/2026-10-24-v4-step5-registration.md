# V4.0 step 5: the registration and the one registered run (plan)

**Status: a plan for the owner's review. Nothing in it has been done.** Writing it registered no
trial, appended nothing to the trial register, created no registration file and dispatched no
workflow. Each step below starts only after the step before it passed its check, and the
registered run starts only on the owner's go (owner decision v4-d15).

Written 2026-10-24 by Claude Code (session f7f187df), on branch `claude/v4-step5-plan` from main
`19e3190`. Times for the owner are given in Zagreb time (CET, UTC+1, from 2026-10-25); machine
stamps stay UTC.

**Binding sources:**
- the V4 spec, `docs/superpowers/specs/2026-10-17-v4-design.md`:
  - "Registration and the run";
  - the "Amended in the V4 step-4b PR" block, rulings G1 to G5 and W1 to W3;
  - owner decisions v4-d03, v4-d10, v4-d15, v4-d24 and v4-d25;
- V3.1's precedent: `docs/reviews/2026-10-15-claude-v3-1-registration.md`, the register's lines
  228 to 230, and PR #285's commits (below);
- V4's machinery:
  - `scripts/v4_registration.py` and `scripts/trial_register.py`;
  - `.github/workflows/v4-run.yml` and `.github/workflows/v4-data.yml`;
  - `config/v4_data.json`;
  - `docs/RUN_ARCHIVE.md`, its "V4 run" section.

## In plain words

- **What step 5 does.** It writes down, before the run, exactly what the one historical test of
  V4.0 is:
  - the program version and the data, by fingerprint;
  - the 48 cells: 12 versions x 2 capitals x 2 cost levels;
  - the pass rule.
- **The run.** It starts the test once on GitHub, never cancels it and never repeats it. One
  exception: the final verdict step alone may be run again once, if GitHub's machines (not the
  code) broke it.
- **Afterwards.** The results come to your PC (E:, with a checked copy on F:). Only you decide
  what is said about them in public.
- **Who does what.** Claude prepares every file and check. The reviewers check them. You give
  the go. GitHub runs the test.
- **How long.**
  - Preparation and review: about one to two days.
  - Merge to archived results: about 7 to 8 hours (a data run of about 75 minutes, then the run
    itself, about 4.5 to 5.5 hours, then the download).
  - Main is frozen from the start of step 5 until the run ends.

## How V3.1 did it, and how V4 follows

V3.1's registration was one PR, #285, with four commits on top of main `5357674`:

1. `50691a5`: the trial's registration event;
2. `615b7a7`: the code pin;
3. `0c5f2a1`: the registration files, the completion and the review;
4. `e51207f`: a docs-only revision of the review.

It was merged with a merge commit, `d4a4f09` (parents `5357674` and `e51207f`), at
2026-10-15 08:11:03 UTC. The registered run, 38703911852, was dispatched 29 seconds later from
main at `d4a4f09`. `git diff --name-only 615b7a7 d4a4f09` lists only the two registration files,
the trial register and the review.

V4 uses the same layout. B is main where step 5 starts, M the merge commit:

```
main:  ... B ---------------------------------------------------- M  (merge commit)
            \                                                    /
             R (event) --- P (code pin) --- C (files) --- D... (docs only)
```

- **Why this order.** `trial_register.check_ready` needs three things:
  - the registration event as an unchanged prefix of the register in `P^1` (so R comes before
    P);
  - the spec commit (B) and P to be ancestors of the run's commit;
  - the code at P to equal the code at the run's commit, file for file.
- **The run's commit.** The registered run is dispatched from main at M. M differs from P only by
  the files the job gate allows (ruling G2).

## Step 0. Preconditions

**Who:** Claude checks; the owner confirms.

1. **The timing run is done and inside its limits.** Run 40108602725 (`mode=timing`, main
   `19e3190`) finished. Its `v4-timing-*` artifacts are downloaded to `E:\v4-run-40108602725\`,
   with GitHub's digests checked. Its numbers are inside every limit of the workflow:
   - each cell's wall time inside the cell job's 60 minutes, with room;
   - each cell's peak memory inside the runner's;
   - the verdict's time, scaled by about two (ruling W2), plus the dispatch check's 55 minutes,
     inside the verdict job's 180 minutes;
   - the verdict's and the expected step's peak memory inside the spec's 2 GB;
   - the analysis inside its 120 minutes.
2. **Any fix is merged and re-tested.** A fix it needs is merged under the full review bar. Then
   the rehearsal and the timing run are run again on the fixed main: a timing run must time the
   code the code pin will hold (header of `v4-run.yml`).
3. **No PR can move main.**
   - No open PR touches `src/`, `scripts/`, `tests/`, `.github/`, `config/` or the V4 spec.
   - PR #300 (docs, which edits the V4 spec) is merged or closed first. The spec is pinned at
     B, and from then on it may not change until the run ends.
   - From B to the run's end nothing lands on main except the registration PR. That includes
     docs PRs, Bob task PRs and Codex's PRs.
4. **This plan is reviewed by the owner and merged before B.**
   - It lives under `docs/superpowers/plans/`, which may not change on main between B and the
     run's end.
   - The same PR adds the owner's F: backup decision of 2026-10-24 to `docs/RUN_ARCHIVE.md`'s
     "V4 run" section. That section does not hold it yet.
5. **Earlier artifacts are handled.** The rehearsal 40106774107 is downloaded
   (`E:\v4-run-40106774107\`, verified). The deletion of its GitHub copies is offered.

**Stops if:** any limit is missed. Then the fix comes first, as a normal PR, and step 5 waits.

## Step 1. The pinning data run, from main at B

**Who:** Claude dispatches, on the owner's approval of this plan. GitHub runs it in about
75 minutes (run 39403004530 took 1 h 13 min).

**Why.** The run manifest (step 4) must hold the data pins before commit C exists. A data run
at C or M cannot supply them, because the manifest is inside those commits. So the pins come
from a run of the same code:
- B's code equals P's: step 3 adds no file under `src/` or `scripts/`;
- the data code (`scripts/v4_data.py`, `src/crypto_grid_bot/v4/data/`, the config and the
  filter snapshots) is unchanged since step 2's full run on `35d4d3e`. Only the workflow file
  changed: its config input (`2731a5d`) and a comment (`876f9f5`).

```
gh workflow run v4-data.yml -R mgalic01/adaptive-market-engine --ref main \
  -f stage=full -f config=config/v4_data.json
```

**Check:**
- every job succeeded;
- the run's `head_sha` is B, and its title is exactly `v4-data full config/v4_data.json`;
- the pack job's "Print data.json" step shows pins and counts only. Read it from the log;
  nothing of 2025 or later is downloaded. Its values must be:

| Field | Expected (step 2's full run 39403004530) |
| --- | --- |
| `config_sha256` | `7868b35a21db5e725db3febf61f4d7d8c1cee7d6729bffb939de5d4a1ea36659` |
| `end_month` | `2026-09` |
| daily pack | `69268e3fac006199746442486e1de38da1dc8bb1f78680c427dc474ffa8be138` |
| hourly index | `b364ccd2c3f0cbe938f1972c3706733f10ddad2b8c146cd847a068e12fc4afe3` |
| counts | 102 universe months, 81 coins, 78 perpetuals (4 multiplier) |
| hourly rows | 7,003,893 |

The daily pack's pin is `packs.daily.sha256`, and the hourly index's is
`packs.hourly_index.sha256`.

`config_sha256` is also `sha256sum config/v4_data.json` at B, the file's raw bytes.

The run's artifacts are not downloaded: the pins are in the log. They expire after a day, and
their deletion is offered.

**Stops if:**
- **the pins differ from step 2's.** Binance may have replaced or removed an archive since
  2026-10-20 (`docs/RUN_ARCHIVE.md` warns of this), or the code may have changed. Claude
  reports to the owner, who decides whether the new pins are registered;
- **a job failed.** The data run may be re-run or dispatched again: it is data preparation,
  not the experiment.

## Step 2. The trial's registration event (commit R)

**Who:** Claude.

**Where:** branch `claude/v4-registration` from B, in a new worktree `E:/v4-registration-wt`.

**How:**
- write the event to a scratch file outside the repository;
- append it with `python scripts/trial_register.py append --event <file>`. That command
  validates the event and the whole register, and keeps the old bytes as an unchanged prefix;
- the commit changes `docs/trials/register.jsonl` only. Message: "trials: register the V4.0
  trial v4-0-registered-1 (spec-v4.0)".

**The event**, in the schema of V3.1's line 228:
- `event_id` `v4-0-registered-1-record`, `trial_id` `v4-0-registered-1`;
- `event_type` `registration`, `family` `spec-v4.0`, `parent_trial_id` null;
- `agent` "Claude Code", `recorded_at` the UTC time of writing;
- `sources`: GitHub links at B to the spec, to this plan and to the step-4b plan; and the
  rehearsal (40106774107), timing (40108602725) and pinning data run URLs.

The trial id follows V3.1's `v3-1-registered-1` and the rehearsal world's `v4-0-synthetic`.
The completion is
`v4-0-registered-1-complete` and the result `v4-0-registered-1-result`.

**The payload**, field by field:
- **`preregistered`:** `true`.
- **`hypothesis`:** the pass rule v4-d04, in full (below).
- **`spec`:**
  - `path` `docs/superpowers/specs/2026-10-17-v4-design.md`, and `commit` B;
  - `sha256`, of the git blob at B (LF, as `check_ready` hashes it):
    `git show B:<path> | sha256sum`.
- **`candidates`:** the 12 arms, one line each with its role (below).
- **`sizes`:** `[1000, 10000]` (USDT).
- **`fees`:**
  - normal costs: spot fee 0.10%, futures fee 0.05% and slippage 0.05% per fill (V3.1's
    profile);
  - every cell also at doubled costs, all three doubled;
  - funding charged at the records' timestamps.
- **`folds`:** no folds.
  - One window: from 00:00 UTC of the first month with an eligible candidate (2018-04 in the
    packs) to the end of the end month, 2026-09, which the run manifest pins.
  - `v3_as_built` runs on V3's window, 2021-07-01 00:00 to the open of 2024-12-31 23:00, with
    V3's terminal mark at 2025-01-01 00:00.
  - Eras reported: to 2020-12-31, 2021 to 2024, and 2025-01-01 to the end.
- **`mask`:**
  - V3's hourly masking (spec, "Data"). A masked hour has no bar, and nothing is
    interpolated;
  - conditions 1 and 2 use each pair's common hourly boundaries, and `verdict.json` lists every
    hour skipped;
  - no market data from 2025-01 onward was executed before this run (v4-d03). The diagnostic
    run used data to 2024-12; the rehearsal and the timing run used synthetic data.
- **`seeds`:** `[]`. No V4 code draws a random number.
- **`budget`:**
  - exactly 48 cells (12 arms x 2 capitals x 2 cost levels), each run once in one registered
    dispatch of `v4-run.yml`, plus one V3 pack build and one V3 picks job;
  - no parameter search, and no extra arm, capital, cost or window;
  - only transport retries are allowed: checksummed archive fetches and GitHub API reads;
  - a single verdict-only re-run is allowed after an infrastructure failure.
- **`stopping`:**
  - every cell runs once, from one dispatch, never cancelled, and every outcome is kept;
  - a missing, refused or `engine_error` cell, or `accounting_failure` outside `v4_main`, makes
    the verdict incomplete (v4-d25). So does a re-run or a second dispatch;
  - no early stop and no tuning on results: a fail or an incomplete verdict needs a new bounded
    hypothesis.
- **`selection`:** none. `scripts/v4_verdict.py` judges `v4_main` alone, from the cells'
  summaries and receipts, with the precedence of rulings V1 to V10. The other 11 arms decide
  nothing.
- **`data` and `code`:** both `null`. The register's schema requires that of a first
  registration; the completion pins them.

**The hypothesis** (v4-d04 with its precedence):

> `v4_main` (long and short, 40% volatility target) passes, at both capitals (1,000 and 10,000
> USDT), all four conditions:
>
> 1. its compounded return over maximum drawdown is greater than `hold_universe`'s (normal
>    costs);
> 2. its compounded return is greater than `v3_as_built`'s over their common period,
>    2021-07-01 00:00 to 2024-12-31 23:00 UTC (normal costs);
> 3. its net profit is positive at doubled costs;
> 4. its equity at the window's end is greater than at 2025-01-01 00:00 UTC (normal costs).
>
> Returns and drawdowns are measured on the common hourly boundaries. The precedence:
> - **fail** if any `v4_main` cell is `liquidated`, `limit_unrestorable` or
>   `accounting_failure`;
> - otherwise **incomplete** if any of the 48 cells is missing, refused or `engine_error`
>   (or `accounting_failure` outside `v4_main`), if a re-run or a second dispatch is found, or
>   if a condition cannot be computed;
> - otherwise **pass** only if all 8 checks hold.

**The candidates:**
- `v4_main`, the only judged arm;
- `v4_long_only`, `v4_vol25`, `v4_vol60`, `v4_faster` and `v4_slower`, reported;
- `v4_btc200_shorts` (v4-d22, v4-d23) and `v4_confirm3` (v4-d22), reported, first run here;
- `hold_universe`, the comparison of condition 1;
- `hold_btc`, and `hold_btc_trend` (v4-d20), reported;
- `v3_as_built`, the comparison of condition 2.

**Check:**
- `python scripts/trial_register.py validate` passes, and so does `validate --base-ref B`;
- `git show --name-only R` lists the register alone.

**Stops if:** validation fails, or the spec at B is not the one the owner approved.

## Step 3. The code pin (commit P)

**Who:** Claude writes it; the PR's reviewers check it (step 6).

**What it holds.** B's code, unchanged. V3.1's code pin also carried a test, the CI's full
history and the experiment menu's status. V4 has no menu, and every V4 checkout already fetches
the whole history. Recommended content, as V3.1's ruling TC-5 had it:
- **`tests/test_v4_registration_committed.py`**, the committed-registration test:
  - it skips while HEAD commits no `config/v4_registration.json`. That is the case at P itself;
  - once that file is committed, it never skips;
  - it checks the commit that last changed the file, never the moving HEAD, in a subprocess on
    a scratch checkout of that commit, with that commit's own code;
  - it checks that:
    - `v4_registration.gate` accepts the commit in registered mode, with the file's own
      SHA-256;
    - `check_ready` passes for the trial;
    - the manifest holds step 1's pins and V3's pack pin, which are hard-coded in the test;
    - P's parent holds the event, and that parent's parent is B;
    - the spec pin is B's.

  So GitHub's CI checks the registration on Linux at the PR's merge ref, before the merge,
  while a fix can still keep the trial id.
- **Or, if the owner prefers, an empty commit** (`git commit --allow-empty`), which
  `check_ready` accepts. Then no CI check of the registration runs before the merge: the first
  check on GitHub is the registered run's plan job.

**Why nothing may change after P** except the files of ruling G2:
- the job gate, in the plan job and again in every cell job, refuses any path changed since P
  other than `config/v4_registration.json`, `config/v4_run_manifest.json`,
  `docs/trials/register.jsonl` and anything under `docs/reviews/` or `docs/tasks/`;
- `check_ready` requires P's code inventory and digest at the run's commit too. That covers
  every tracked file under `src/` and `scripts/`, `pyproject.toml`, `requirements-dev.lock` and
  `requirements.txt`;
- the spec must still hash to its pin there.

So `tests/`, `.github/`, the rest of `config/`, the spec and every other doc are frozen until the
run ends.

**Check:**
- `git diff --name-only R P` lists the test alone;
- `git diff --quiet B P -- src scripts pyproject.toml requirements-dev.lock requirements.txt`
  succeeds;
- `python -m ruff format --check .` and `python -m ruff check .` pass;
- the new test file, run alone, skips. That is light.

**Stops if:** anything under `src/` or `scripts/` needs a change. That is not step 5: it goes back
to a normal PR before B, and this plan restarts at step 0.

## Step 4. The registration files, the completion and the review (commit C)

**Who:** Claude.

**The files**, both canonical JSON (ruling G1: sorted keys, no spaces, ASCII, no final newline;
`.gitattributes` keeps `config/v4_*.json` LF):

- **`config/v4_run_manifest.json`** has exactly:
  - `schema` `v4-run-manifest-1`;
  - `data`: `config_path` `config/v4_data.json`, `config_sha256` (step 1), `end_month`
    `2026-09`, and `daily_sha256` and `index_sha256` (step 1);
  - `v3_pack_sha256`, V3.1's pin, which is the workflow's `V3_PACK_SHA256`:
    `8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee`.
- **`config/v4_registration.json`** has exactly:
  - `schema` `v4-registration-1`, and `code_pin` P;
  - `run_manifest_sha256`, the manifest file's SHA-256;
  - `spec`, its `path` and `sha256` as the event's;
  - `cells`, the 48 ids of `arms.all_cells()`, in order;
  - `trial_id` `v4-0-registered-1`.

No V4 command writes the real files: `scripts/v4_registration.py` only reads them, and builds
the rehearsal world's.
- A new script under `scripts/` would change the code inventory, so the files are written by a
  short one-off script kept outside the repository.
- It uses `combined.artifacts._canonical` and reads both files back through `read_manifest` and
  `read_registration`.
- Its text goes into the review file, so anyone can rebuild the bytes.

The registration's SHA-256 is called S below. The file never holds S itself: the dispatch
passes it.

**The completion event**, appended with `trial_register.py append`, as V3.1's line 229:
- `event_id` `v4-0-registered-1-complete`, `event_type` `completion`, `family` `spec-v4.0`;
- `registration_id` `v4-0-registered-1-record` and `code_commit` P;
- `code_paths` and `code_sha256`: every tracked file under `src/` and `scripts/` at P, plus
  `pyproject.toml`, `requirements-dev.lock` and `requirements.txt` where tracked, and their
  `trial_register.code_digest`, exactly as `check_ready` computes them;
- `manifest` `{path, sha256}` and `config` `{path: config/v4_registration.json, sha256: S}`;
- `review`, the review file's path;
- `sources`: the review file, and the pinning data run's URL.

**The review file**, `docs/reviews/<date>-claude-v4-registration.md`, dated the day it is
written, has V3.1's sections:
- "In plain words";
- "The owner's go (dated record)", empty until step 7;
- "What is registered" and "Every pin": B, R, P, the code digest and path count, S, the
  manifest, the data and V3 pack pins, and the spec;
- "The checks, run on this branch", and the evidence: the rehearsal, the timing run and the
  pinning data run;
- "Expected run length";
- "Outcomes that use up the run without a verdict";
- "Operating rules", and "Limits of this review";
- the one-off script.

It indexes itself with its `Index:` line. No row is added to `docs/reviews/README.md`, whose table
is frozen.

**Commit message:** "v4: the registration of the one registered run (trial v4-0-registered-1)".

## Step 5. The checks, run locally

**Who:** Claude. All of them are light (git, hashing, the register's validation), so nothing
heavy runs on the owner's PC. The full test suite runs in CI on the PR.

Each check, and what it must give:
1. **The register.** `python scripts/trial_register.py validate`, and the same with
   `--base-ref B`, print `trial register: valid`.
2. **The trial.** `python scripts/trial_register.py check-ready --trial-id v4-0-registered-1
   --revision <head>` exits 0.
3. **The job gate.** `python scripts/v4_registration.py gate --repo <worktree>
   --mode registered --registration-sha256 S` prints its accepted line and exits 0, on a clean
   worktree at the head.
4. **The integration, rehearsed.** In a scratch clone, the head is merged into B with
   `git merge --no-ff`, as V3.1 rehearsed its own. The same gate accepts that merge commit, and
   the committed test passes there.
5. **The changes.** `git diff --name-only P <head>` lists only the two files, the register and
   files under `docs/reviews/`.
6. **The pins.**
   - `sha256sum config/v4_registration.json` gives S;
   - the manifest's pins equal step 1's log, field by field;
   - `config/v4_rehearsal.json` is absent at every commit (the gate's world check).
7. **No earlier dispatch.** `gh run list -R mgalic01/adaptive-market-engine --workflow
   v4-run.yml --limit 50` shows no run titled `v4-run registered S`.
8. **The docs and the format.** `python scripts/check_reports.py` gives 0 problems, and
   `python -m ruff format --check .` and `python -m ruff check .` are clean.

**Stops if:** any check fails. The branch is then rebuilt as clean commits with the same trial id
(nothing is on main yet), and every check runs again.

## Step 6. The PR and its reviews

**Who:** Claude opens and tends the PR. The reviewers review it, and GitHub runs CI.

**The PR:**
- push `claude/v4-registration`, then open "V4.0 registration: trial v4-0-registered-1";
- the body says "merge commit only, never squash or rebase", lists every pin, and links the
  review file;
- claim it (the claims rule of `docs/AGENT_HANDOFF.md`).

**The review bar:**
- an independent review, by a fresh reviewer given the files, not this plan's conclusions;
- Bob's deep review, NO ISSUES. If the owner still has Bob out (owner, 2026-10-24), Codex's
  deep review with Bob's questions stands in, per the owner's rule (open question 3);
- Codex: no open P1, and every thread answered. If no 👀 appears within 5 minutes of a push,
  post `@codex review`;
- claude[bot]: APPROVE. The diff is small: two register lines, two JSON files, a test and a
  review file;
- CI green, with the committed test passing, not skipping;
- the owner's own review of the registration (step 7).

**Fixes.** Here "fixed in the next PR" is impossible, because nothing else may land on main.
- A finding about the review file is fixed in a docs-only commit under `docs/reviews/`.
- A finding that needs any other change stops the PR and goes to the owner. That includes the
  two JSON files, the register, `tests/`, `src/`, `scripts/`, `.github/`, `config/` and the
  spec.
- A rebuild of every commit, with the same trial id while unmerged, follows only on the
  owner's word.

**CI headroom.** If the CI job times out, it may simply be re-run: that is CI, not an
experiment re-run. Raising its limit would be a `.github/` change after P, so a rebuild.

## Step 7. The owner's go

**Who:** the owner, in chat, after step 6's bar is met. Claude asks, stating:
- S, P and the data pins;
- the expected run length;
- the proposed dispatch time (Zagreb);
- what the go covers:
  1. the merge with a merge commit;
  2. the registered data run;
  3. one registered dispatch;
  4. the download of every artifact to E: and the verified copy on F:.

  The deletion of GitHub's copies is not covered: it is asked separately.

**The record.** Claude writes "The owner's go (dated record)" into the review file in a
docs-only commit:
- the time in UTC and in Zagreb time;
- the owner's exact words and any conditions.

Then Claude re-reads the whole PR thread and checks CI and the reviewers at that head, right
before merging. The go must be in the PR: after the merge, nothing may land on main until the run
ends.

**Stops if:** there is no go, or its conditions are not met.

## Step 8. The merge

**Who:** Claude, on the go.

`gh pr merge <number> -R mgalic01/adaptive-market-engine --merge`. A squash or rebase would
rewrite R and P, leaving the code pin outside main's history, and every registered job would
refuse.

**Check:**
- `gh api repos/mgalic01/adaptive-market-engine/commits/main --jq '.sha, [.parents[].sha]'`
  gives M, with the parents B and the PR head;
- `git fetch origin && git diff --name-only P origin/main` lists only the allowed files;
- `git show origin/main:config/v4_registration.json | sha256sum` gives S.

**Stops if:** main had moved (M's first parent is not B, or the diff lists another file). Then do
not dispatch. The completion is now on main, so a rebuild needs a new trial id. The abandoned
trial gets a recorded correction or result, as the owner decides.

## Step 9. The registered data run, from main at M

**Who:** Claude dispatches it right after the merge. GitHub runs it in about 75 minutes.

**Why a second data run.** The plan job accepts only a successful
`v4-data full config/v4_data.json` run whose `head_sha` is the registered run's own commit, M
(ruling G5). Step 1's run is of B, so it does not qualify.

Same command as step 1, after the merge (`--ref main`, `-f stage=full`,
`-f config=config/v4_data.json`).

**Check:**
- the run succeeded, its `head_sha` is M and its title is exact;
- its log's `data.json` pins equal the manifest's, field by field.

**Stops if:**
- **the pins differ.** Binance's archive changed between step 1 and now, and the plan job
  would refuse. Do not dispatch: report to the owner. A new registration (a new trial id)
  would be needed;
- **a job failed** (network). The data run may be re-run, or dispatched again, still from
  main at M.

## Step 10. The dispatch

**Who:** Claude, once, on the go. GitHub runs it.

**The 24-hour window.** The data run's `v4-data` artifact is kept one day (`retention-days: 1`).
- Dispatch less than about 20 hours after it finished.
- If it is older, first make a fresh data run from main at M (step 9 again), and use its id.

**Read-only checks first**, each of which must hold:
- main's head is still M, and the diff and S checks of step 8 still hold;
- the data run checks of step 9 hold, and it finished less than about 20 hours ago;
- `gh run list ... --workflow v4-run.yml` shows no v4-run queued or in progress, and none titled
  `v4-run registered S`.

**Then, once:**

```
gh workflow run v4-run.yml -R mgalic01/adaptive-market-engine --ref main \
  -f mode=registered -f registration_sha256=S -f data_run=<step 9's run id>
```

**Check:**
- one run titled `v4-run registered S` appears, with head M;
- its plan job passes:
  - the gate;
  - the dispatch check;
  - the data run's check and download;
  - the data guard against the manifest.

**Stops if:** the plan job refuses.
- Once GitHub shows the run completed, with the plan failed and every other job skipped, the
  launch does not count (layer L2 of the dispatch check).
- Claude tells the owner and finds the cause, for example an expired data run.
- A new dispatch happens only on the owner's word.
- Never cancel the refused run: a cancelled launch counts.

## Step 11. While it runs

**Who:** GitHub runs it; Claude watches with `gh run view`.

- Claude reports progress to the owner as job counts and times only. The public logs hold no
  results, and nothing about outcomes is posted anywhere.
- No one cancels, re-runs or dispatches anything (operating rules below).
- The one allowed act is step 12a.
- The owner's PC and Claude's session stay on until steps 12b and 12c are done, because the
  artifacts last one day.

## Step 12. After the run

**a. Only if the verdict job failed from an infrastructure failure** (a runner lost, a full disk,
a GitHub outage; not a code bug):
- Claude asks the owner;
- on the owner's word, Claude re-runs the verdict job alone: GitHub's "Re-run job" on `verdict`,
  which takes the `status` job with it;
- once, and only while the cells' summaries still exist: they expire a day after their upload,
  from about the first hour of the run;
- never "Re-run failed jobs" and never "Re-run all jobs". The verdict counts any other re-run
  from the run's attempts, and makes the verdict incomplete.

**b. Download every artifact the same day**, about 102 of them, to `E:\v4-run-<id>\`:
- with the rehearsal's `scripts\fetch_v4_cells.py` (from `E:\v4-run-40106774107\scripts\`);
- the layout of `docs/RUN_ARCHIVE.md`'s "V4 run" section: `zips\`, one folder per artifact,
  `meta\artifacts.json`, `scripts\` and `SHA256SUMS.txt`;
- each zip's SHA-256 must equal GitHub's upload digest, or the download stops.

**c. A verified backup on F:,** in `F:\v4-run-<id>-backup\`:
- `sha256sum -c SHA256SUMS.txt` passes there;
- the file list equals E:'s.

**d. Read the verdict on the owner's PC only.**
- Open `verdict.md`, `verdict.json` and `diagnosis.md` with `python -I` scripts kept outside the
  archive.
- Tell the owner the verdict in chat.
- Nothing from the results goes into a log, a PR comment or a commit beyond what the owner
  allows (open question 7).

**e. A post-run PR, once the run has ended** (main is free again), under the normal review bar:
- **the result event** `v4-0-registered-1-result`, in V3.1's line-230 shape:
  - `completion_id`, and `run_id` (the run's id);
  - `status`: pass `success`, fail `failed`, incomplete or no verdict `invalid` (open question
    8);
  - `provenance`, a JSON string: the archive, the digest check, P, M as `dispatched_from`, S,
    the manifest's SHA-256, the data run's id and `verdict.json`'s SHA-256;
  - `report`, the verdict record;
  - `metrics` and `reason`;
- **a "V4 registered run <id>" section** in `docs/RUN_ARCHIVE.md`, with both copies and their
  status;
- **the verdict record**, `docs/reviews/<date>-claude-v4-verdict.md`.

**f. Offer the deletion** of the run's GitHub artifacts, and of the two data runs', once both
local copies are verified. Delete only on the owner's confirmation. They also expire on their
own after a day.

## Outcomes that use up the run without a verdict

The run counts as the registration's one execution as soon as its plan job passes, or if it is
cancelled. Then these outcomes end it without a pass, or with an incomplete verdict. None can give
a false pass.
- **The v3-pack job fails.** It fetches V3's archives from Binance. The picks and the four v3
  cells are skipped, and every v3 cell counts as missing: incomplete, or fail if a `v4_main`
  cell stopped. The verdict is still written.
- **The picks job fails, or runs past its 300 minutes.** It took 210.7 minutes in run
  40040422092, 70% of its limit. Same result as above.
- **A cell runs past its job's 60 minutes, or out of memory.** That cell is missing:
  incomplete. The other cells still run, since the matrix does not fail fast.
- **The verdict job fails** (memory, disk, a crash, its 180 minutes). There is no verdict until
  the one verdict-only re-run (step 12a). If that fails too, the run is used up with no verdict.
  Computing the verdict on the owner's PC instead would be a deviation, needing the owner's
  decision beforehand (open question 6), as V3.1's v31-d30 to v31-d32 were.
- **The verdict's dispatch check cannot read GitHub within its 55 minutes.** The verdict is
  incomplete.
- **A cancel, any re-run other than the verdict-only one, or a third attempt.** The verdict is
  incomplete, by design.
- **A second v4-run dispatched while this one is queued.** GitHub drops the queued run, which
  then counts as cancelled.
- **The artifacts expire before the download.** The evidence is then lost to the owner's PC,
  even with a verdict on GitHub. So the download (step 12b) is the same day.
- **The analysis job fails.** There is no diagnosis page, but the verdict is unaffected: the
  analysis decides nothing.

## Expected run length

**Measured so far:**
- **the rehearsal 40106774107** (synthetic, four coins): 17 minutes end to end. The plan job took
  37 s, the scenarios 9 min, the analysis 2.7 min and the verdict 5.8 min;
- **V3's path, from the `v4-v3` run 40040422092**: pack 9 min, picks 210.7 min (about 3.5 hours),
  the four v3 cells 8.4 to 14.6 min;
- **data runs**: 1 h 13 min for the full one (39403004530), about 1 h for the pre-2025 ones.

**From the timing run 40108602725,** to be filled in when it finishes:
- the 44 cells' wall times (longest and median) and peak memory: [ ];
- their output sizes: [ ];
- the verdict's time and memory, x2: [ ];
- the expected step's time and memory: [ ];
- the analysis' time and memory: [ ].

**Estimate:**
- the run itself takes about 4.5 to 5.5 hours, set by V3's picks: plan, pack, about 3.5 hours of
  picks, the v3 cells, then the verdict;
- the 44 other cells run beside it, at most 20 at a time, and should finish well before;
- while 20 cells run, GitHub's limit of 20 concurrent jobs may hold the v3-pack job back by up to
  one cell's time;
- the registered data run (about 75 minutes) comes before, and the download after.

So the whole takes about 7 to 8 hours from the merge to an archived result. Best dispatched in the
Zagreb morning, so that the same-day download is certain.

## Operating rules

The code does not enforce these. The people who merge and dispatch must follow them.
1. **Merge with a merge commit only.**
2. **Nothing else lands on main** from B until the run ends. If main moved before the merge,
   rebuild; never rebase.
3. **Review fixes touch only `docs/reviews/**` or `docs/tasks/**`.** Anything else means a
   rebuild, on the owner's word: the same trial id before the merge, a new one after.
4. **One v4-run at a time.** Never dispatch one while another is queued or running.
5. **Never cancel a registered dispatch.** A cancelled launch counts.
6. **Never re-run** a cell, the picks, the pack or the plan job, and never the whole run. The one
   exception is step 12a.
7. **One dispatch.** The dispatch check refuses a second one. But two dispatches made in the same
   second void each other, and a run deleted by an admin is invisible to the check.

## Where V4's machinery cannot follow V3.1's precedent as written

1. **Two data runs, not one.**
   - V3.1's prepare job ran inside the registered run and reproduced the pinned packs.
   - V4's data comes from a separate `v4-data` run, which must be of the dispatch commit M
     (G5). But the manifest holding the pins is inside M.
   - So the pins come from step 1's run at B. Step 9's run at M must reproduce them, which holds
     only while Binance's archive does not change in between.
2. **No dispatch right after the merge.** V3.1 dispatched 29 seconds after its merge. V4 needs
   step 9's data run, about 75 minutes, in between, with main frozen.
3. **One-day artifacts.**
   - V3.1's artifacts stayed on GitHub for 90 days, as the owner then wanted. V4's are kept one
     day (W1, v4-d10).
   - So the dispatch must follow the data run within a day, the download must be the same day,
     and the verdict-only re-run is possible only within that day.
4. **No skipped hours in the registration.** V3.1's prepare step derived them before the
   registration, which pinned them. V4's registration (G1) has no such field: the verdict finds
   them and lists them in `verdict.json` (`skipped_ms`).
5. **No content for V3.1's commit 2.** V3.1's code pin flipped the experiment menu and deepened
   the CI's checkout. V4 has no menu, and every V4 checkout already fetches the whole history.
   The code pin holds the committed test or nothing (open question 2).
6. **No writer for the real files.** V3.1's driver had helpers for its manifest and its trial;
   V4 has only readers. So a one-off script outside the repository writes them (step 4).
7. **Canonical JSON.** V3.1's registration was indented JSON. V4's must be canonical, or the gate
   refuses it.
8. **A narrower public record.** V3.1's verdict record and result event gave aggregated results.
   v4-d10 keeps V4's results on the owner's PC, so the owner decides what is published (open
   question 7).

## Open questions for the owner

1. **Approve this plan,** the trial id `v4-0-registered-1`, and step 1's pinning data run. That
   run takes about 75 minutes on GitHub and reads 2025+ data for data preparation, as v4-d03
   allows.
2. **The code pin's content:** the committed-registration test (recommended, as V3.1's TC-5), so
   that CI checks the registration before the merge; or an empty commit.
3. **Reviewers:** if Bob is still out when the PR opens, does Codex's deep review stand in for
   Bob's on the registration PR, or does the registration wait for Bob?
4. **The main freeze:** from B to the run's end, about two days, nothing else lands on main.
   Other PRs wait, Codex's and Bob's included. Is that acceptable?
5. **The go and the dispatch time:**
   - should the go cover the merge, step 9's data run, the one dispatch, the download to E: and
     the backup on F:?
   - at what Zagreb time should the run be dispatched?
6. **If the verdict job and its one re-run both fail:**
   - should the run stop with no verdict;
   - or may the verdict be computed on the owner's PC from the downloaded summaries, with the
     same code (V3.1's v31-d30 precedent)?

   Deciding now, before any result, keeps it unbiased. In the same vein: may the analysis job,
   which decides nothing, also be re-run once after an infrastructure failure? The code allows
   it (`RERUN_JOBS`), but the spec names only the verdict job.
7. **The public record after the run** (v4-d10):
   - the verdict word and fingerprints only;
   - or also aggregated numbers, as V3.1's record gave?
8. **The result event's status:** pass `success`, fail `failed`, incomplete or no verdict
   `invalid`. Is that acceptable?
