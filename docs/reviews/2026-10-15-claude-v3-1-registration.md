# Claude: the V3.1 registration, the locked plan of the one historical run

Index: Task 11, written 2026-10-15 UTC. The exact, locked registration of the one historical V3.1 run: trial `v3-1-registered-1` (family `spec-v3.1`), code pin `615b7a7` (main `5357674`'s code, plus tests, the CI history depth and the menu status), registration SHA-256 `05b8315054ce`, 324 cells, three USDT capitals (10,000, 1,000, 100), W1 140 and W0 159 skipped hours. Every registered gate passes on it. The owner's go of 2026-10-15T00:56Z is recorded with its conditions, and the menu status is set at it: dispatch once, from main, after review and a merge-commit integration.

Author: Claude Code (registration implementer, Task 11), 2026-10-15 UTC. Branch
`claude/v3-1-registration`, three commits on main `5357674`. Nothing was pushed or run;
no market data was fetched or read. (An earlier build of the same registration, four
commits with another code pin, is kept locally as `claude/v3-1-registration-draft1` and
was never pushed; this rebuild replaces it.)

## In plain words

- **What this is.** The one historical test of the V3.1 bot is now written down exactly:
  which coins, which dates, which starting amounts, which strategies it must beat, which
  data files (by fingerprint) and which program version (by fingerprint). After the test
  starts none of this can change, and the program checks every fingerprint before every
  step. If anything differs, the step refuses to run.
- **What is tested.** The full V3.1 bot (`combined`) must beat 32 earlier strategies (the
  old V3 picker, V3's six long-only rules, simply buying and holding the coins, and the
  older grid bots V0, V1 in all nine versions, V2 and comparator D) on profit and on profit
  per unit of worst loss. It must do this from 2021-07-01 to 2025-01-01, on ten coins, at
  each of three starting amounts (10,000, 1,000 and 100 USDT), at normal and at double
  trading costs, in both price-path scenarios. Its worst fall must stay at or under 30%, it
  must still make money at double costs, and nothing may be liquidated or unexplained.
  Every one of those comparisons must exist: one missing comparison anywhere means "not
  decided" (incomplete), never a pass.
- **How big it is.** 324 separate runs ("cells"), each run once. About 14 to 17 hours on
  GitHub's machines, 20 at a time; the longest measured job (V3's picks, about 3.7 hours)
  stays under GitHub's 6-hour job limit.
- **Your go.** You approved the run on 2026-10-15 at 00:56 UTC, before these files were
  final. The experiment menu now says `AUTHORIZED_FOR_ONE_REGISTERED_EXECUTION` because of
  it. The run starts only after this registration passes its reviews and is put on main
  with a merge commit; then it is started once and never cancelled or re-run.
- **What can still go wrong (honestly).** At 100 USDT the buy-and-hold baseline keeps a
  coin in cash when its 10 USDT share is below an exchange minimum (said in the report),
  and the old V3 picker may stop early, which makes that comparison "not decided" and so
  blocks a pass. That is the cautious side, by design.
- **Real money.** None. This is a historical simulation with no trading, no exchange
  account and no keys. A pass would still need the reserved-data step and live paper
  trading before any real money.

## The owner's go (dated record)

- **When and what.** In chat at **2026-10-15T00:56Z** the owner wrote: "Ok, in that
  case.... go, i approve, start everything". It came after the coordinator explained that
  the run is about 330 separate GitHub jobs, each under GitHub's 6-hour per-job limit (a
  workflow run may last up to 35 days), taking 14 to 17 hours of wall-clock in all.
  Dashboard decision v31-d26; SDD ledger entry of the same time.
- **Given before the registration was final.** The go was given while this registration
  was being written, so it approves the plan described here, under these conditions:
  1. this registration passes the independent review, Bob (NO ISSUES), Codex (no open
     P1), CI (green) and the automated review (APPROVE), under the standing merge bar;
  2. any finding that needs a change outside the allowed registration artifacts (or any
     code change on main) stops the dispatch and goes back to the owner;
  3. the registration PR is integrated with a merge commit, and the run is dispatched
     **once, from main**, after that integration; never cancelled, never re-run, every
     outcome kept.
- **The menu status.** At this go, the code pin sets `config/v3_1_experiment_menu.json`'s
  status to `AUTHORIZED_FOR_ONE_REGISTERED_EXECUTION` (it was
  `NOT_AUTHORIZED_FOR_EXECUTION`; the run driver's plan said it stays so "until the owner's
  go"), under the conditions above. If this PR is never integrated, main never carries
  the flip.
- **After the run** (owner, 2026-10-15 ~01:05Z): every run artifact is to be saved
  permanently on GitHub (artifacts expire after 90 days), then analysed read-only. Not
  part of this registration.

## What is registered

| Item | Value |
| --- | --- |
| Judged window W1 | 2021-07-01 00:00 to 2025-01-01 00:00 UTC (1625097600000 to 1735689600000 ms), half-open |
| W1 coins (10) | BTC, ETH, BNB, SOL, XRP, ADA, DOGE, LTC, LINK, TRX (USDT pairs) |
| Reported window W0 | 2020-03-01 00:00 to 2025-01-01 00:00 UTC (1583020800000 to 1735689600000 ms); `combined` only, no acceptance |
| W0 coins (8) | BTC, ETH, BNB, XRP, ADA, LINK, LTC, TRX |
| Capitals | `research` 10000 USDT, `medium` 1000 USDT, `small` 100 USDT, each opening at exactly its amount; no FX, no euro capital |
| Costs | cost multiple 1 (spot fee 0.10%, futures fee 0.05%, slippage 0.05% each) and 2 (all doubled) |
| Scenarios | `open_low_high_close`, `open_high_low_close` (V3.1 arms); baselines run `native` |
| V3.1 arms (10) | `combined` (judged), `spot_trend`, `futures_trend`, `futures_trend_long_only`, `spot_grid` and five `combined_without_*` ablations (explanatory) |
| Baselines (32) | `unchanged_v3_selector`, `unchanged_v3_r1_long_only` to `r6`, `matched_spot_hold`, and V0, V1 `a b c e f g cg h ch`, V2 and D grids/trend in both path modes (24 minute arms) |
| Observation policy | `v3.1-owner-2026-10-11-settlement-v1` |

**The 324 cells** (`required_cells`, checked equal to the file): W1 120 V3.1 (10 arms x 2
scenarios x 2 costs x 3 capitals), 42 V3 (7 x 2 x 3), 6 hold, 144 minute (24 x 2 x 3);
W0 12 reported-only `combined` cells. 108 per capital. The workflow's matrices: run-v3 6
(the selector, which waits for the picks job), run-minute 144, run-main 174.

## Every pin

| Pin | Value |
| --- | --- |
| Main at the branch base | `5357674bc3f612b7970e0a356113e8aef2032e7f` |
| Commit 1, the trial's registration event and the V3 seed test's fix | `50691a5af2179ab9d61c2e44112cb2bed7a23907` |
| **Code pin** (commit 2: the committed-registration test, the CI fetch depth, the menu status) | `615b7a78fe71e5582ac87df32d50b28d9c091bc2` |
| Commit 3, the registration | the commit holding this file (a file cannot name its own commit) |
| Code digest (`check_ready`'s, 176 paths: every tracked file under src/ and scripts/, pyproject.toml, requirements-dev.lock) | `af9fc72e213d32bac73e679f186d8ccf7d2556e98bf39376fdbe48ba95df0ff1`, identical at the code pin and at main 5357674 |
| **Registration** `config/v3_1_registration.json` (config pin) | `05b8315054ce12cdf3da8c818b1d8144f5f65a60a54e04e0d5a89bfe5867efa3` |
| **Run-manifest** `config/v3_1_run_manifest.json` (every window's data pin) | `41d841244d906019f2c512133a5e883902b4d05f6923159b714265d907d74254` |
| Prepare config `config/v3_1_prepare.json` | `71954170e9ebd35be5af1b199147df6f18e4b905912642e9d8ea961a02ce8293` |
| Window pack W1 | `1bc5feea67af4aa978e11ed6deb6947d35721c8de24008665b65e2b75f3341fd` |
| Window pack W0 | `16e4cce6c426944c3a38a411baa136ef5f6126412adbe31db38a43e6be44683c` |
| V3 input pack | `8a4780009bfe580995396b60fd30e52bbc21888a470e49eedb84910087a55dee` |
| Data manifest `config/datasets/full-range-2017-2024.manifest.json` | `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e` |
| Data manifest `config/datasets/v3-1-minute-bars/v3-1-minute-bars-2020-2021.manifest.json` | `c2582815d56b3eec2fd3468002c0e3fe6c09914fb967ac7faba31392b109966a` |
| Data manifest `config/datasets/v3-1-minute-bars/v3-1-minute-bars-2021-2024.manifest.json` | `589b9a8c493240e24f24900e8c9b81f43a4330bd652c4c8ebf628c7c5403444d` |
| Data manifest `config/datasets/v3-20261009/inventory.manifest.json` | `78d997a2f0a6e83705df339cc2ec0a0421faebdc18ee4337de8f07400a4b013a` |
| Spot filter snapshot `config/datasets/v3-20261009/snapshots/spot.json` | `d5dbeeb908dde49269e7e654359b59981e7958636b2ed61103999bdec826b05d` |
| Futures filter snapshot `config/datasets/v3-20261009/snapshots/futures.json` | `db6a0c5bde5fc247224826f26be78729da74eecd2bc419a93728f255fd9244f4` |
| Cost profile, multiple 1 | `080ebaee2ff778dd082d3a15e868da3c2e55d6dbb20e7f718706e2e394e41c76` |
| Cost profile, multiple 2 | `b99eb4ad4f3458f8d501be30fe53aab695906117478884bdcdff2e42a5c3af1e` |
| Adapter pin, the 10 V3.1 arms | `e225c7c722df0a7aacfa75178311e72aac7c80bed8bae5091569383d7ccb3606` |
| Adapter pin, the 7 V3 arms | `b984d8391c97ec8d13185269f10a8e0ddd20ab1d80c4e29e389e404ef40858f8` |
| Adapter pin, `matched_spot_hold` | `5645f020d0de45d15b711d60e90dfbd8de1c7ba5fb949b9d318f9ac7bdc83fd7` |
| Adapter pin, the 24 minute arms | `47c81d0ae4ff20d0afa2e7d61b164208eabc3cf29ba1472e2bcb84d44137c4af` |
| Skipped hours W1 (140), SHA-256 of the compact JSON list | `da437e05e9cae6cf85e50342fe5cabdaec8bad363b5ea52b14c115196564917c` |
| Skipped hours W0 (159), likewise | `21a621d5bef899136cdfe7ce4ed7f5f92a19685b19418d110573d9a904fda769` |
| Spec pin `docs/superpowers/specs/2026-10-10-v3-1-design.md` at `5357674` | `dbf3b23222cef3eb36e5e8f337cb424b1917d3b23a2ce34a5f1bead64cbfca5d` (the git blob, LF) |
| Trial | `v3-1-registered-1`: events `v3-1-registered-1-record` (registration) and `v3-1-registered-1-complete` (completion) |

The adapter pins are the same at the code pin and at main 5357674 (both read with
`adapter_pins` from git blob ids). The completion pins the code pin, the code digest and
path list above, the run-manifest and the registration by path and SHA-256, and this file
as its review.

## Skipped hours

Derived by the prepare step, not chosen: every window hour at which any registered price
source lacks its bar is skipped for every arm alike (owner decision 2026-10-11, Rulings
P16 and P17). The 30% drawdown gate still uses every native mark; nothing is interpolated.

**W1, 140 hours:**

- 2022-02-26 00:00 to 2022-02-28 23:00 (72 h) and 2022-04-01 00:00 to 2022-04-02 23:00
  (48 h): no futures bar for LTC, SOL, TRX and XRP (120 hours, the largest gaps);
- exchange-wide spot outages, every coin without a spot bar and an opening minute:
  2021-08-13 01:00-06:00 (6 h), 2021-09-29 07:00-08:00 (2 h), 2023-03-24 12:00-13:00
  (2 h); and 2021-12-24 04:00 (1 h, nine coins without a spot bar, XRP had one);
- the minute baselines' own masked hours (frozen V1 masks, BTC 15, ETH 13, XRP 16 hours,
  partly inside the outages above), adding 9 single hours: 2021-10-23 05:00,
  2021-12-26 22:00, 2021-12-27 05:00, 2021-12-31 00:00, 2022-02-05 06:00,
  2022-02-23 06:00, 2022-04-13 06:00, 2022-04-28 01:00, 2022-04-29 09:00;
- XRP rule-8 opening quotes (Ruling P17): the test ran and found none (0 hours).

**W0, 159 hours:** the same futures gaps (72 h + 48 h on LTC, TRX, XRP; SOL is not in W0),
the four W1 spot outages above, which W0 spans too (11 h; on 2021-12-24 seven coins),
and the earlier spot outages of 2020-03-04 (3 h), 2020-04-25 (3 h), 2020-06-28 (4 h), 2020-11-30 (1 h),
2020-12-21 (4 h), 2020-12-25 (1 h), 2021-02-11 (2 h), 2021-03-06 (2 h), 2021-04-20
(3 h) and 2021-04-25 (5 h). W0 carries no minute-baseline hours (the minute baselines run
in W1 only).

## The checks, run on this branch

On Windows with Python 3.14 (CI runs 3.12). Before commit 3 was made, every check below
ran on commit 3's content in a scratch clone holding the same commits 1 and 2: there,
commit 3 differs from this one only in the completion's `recorded_at` and this file's
text, and the registration and run-manifest bytes are identical (compared byte for byte).
The full suite and the same checks then run at this commit once it exists; a file cannot
record a run of its own commit, so those counts are in the implementer's report and the
PR's handoff.

| Check | Result |
| --- | --- |
| `load_registration` and `check_registration` on the committed files | pass |
| `owner_plan_errors(prepare, registration)` | `[]` |
| `plan_gate("registered", ...)` | pass |
| `trial_errors(repo, head)` (scripts/v31_driver.py) | `[]` |
| `trial_register.py validate`, and `validate --base-ref 5357674` | `trial register: valid` |
| `trial_register.check_ready` for `v3-1-registered-1` at the head | pass |
| `job_gate`: changes since the code pin | only `config/v3_1_registration.json`, `config/v3_1_run_manifest.json`, `docs/trials/register.jsonl` and this file; `_path_errors` empty; returns the head |
| `world_gate("registered")` | pass (no rehearsal marker anywhere) |
| `v31_driver.py plan --registration-sha256 <pin>` | 324 cells planned: v3 6, minute 144, main 174 |
| Adapter pins at the head | equal to the registered ones (42 arms) |
| Run-manifest pins equal the prepare output | equal, field by field; skipped hours equal, W1 140 and W0 159 |
| `tests/test_v31_registration_committed.py` | 7 skipped at commit 2 (no registration yet); 7 passed at commit 3's content |
| tests/test_trial_register.py at commit 1 | 42 passed (the seed test reads V3's own registration) |
| tests/test_v31_registration.py, the new test and tests/test_v31_workflow.py at commit 2 | 161 passed, 7 skipped (the new test) |
| `ruff check .`, `ruff format --check`, `mypy src scripts`, `bandit -q -r src scripts` | clean (mypy: no issues in 173 source files; bandit exit 0); the code is main's |
| `python scripts/check_reports.py` | 0 problems |

The 9 tests of tests/test_bob_task_workflow.py fail on this machine only (no `jq`).

**A rehearsal of the integration.** In the scratch clone, the three commits were
integrated into main 5357674 with a merge commit. The plan job (`v31_driver.py plan`,
which runs `job_gate`, `world_gate` and `plan_gate`) passed at that merge commit with all
324 cells, and so did the committed-registration test. In an earlier scratch build, after
a further code change on the scratch main, the committed-registration test still passed,
as it must; a later commit that altered the registration's skipped hours made it fail, as
it must; and a two-commit (shallow) clone made it fail with a message naming the cause.

**An earlier build** (`claude/v3-1-registration-draft1`, never pushed) ran the v31 test
files, the trial-register and review checks and every suite that reads the repository's
docs, config or register at its commit 3: 1650 passed, 4 skipped (symbolic links), 0
failed. It found the V3 seed-test coupling that commit 1 now fixes.

## Evidence gathered before registration

- **Timing** (timing mode, results discarded): prepare 2647 s; one W1 minute cell (V2's
  grid) 5534 s at 6.2 GB peak memory; V3's selector picks 13319 s at 1.4 GB. All inside
  the 335-minute step timeout (20,100 s) and the 360-minute job limit.
- **Rehearsals** (synthetic worlds only): runs 38577845546 and 38578159507, 6 cells at
  `e56b1a4`; and the full 324-cell rehearsal, run 38654503645 at `5357674`, which proved
  the 6 / 144 / 174 matrix split on GitHub: success in 10 minutes, 331 jobs; run-main 174,
  run-minute 144 and run-v3 6 all succeeded; aggregate judged all 324 cells (synthetic
  verdict `fail`, verdict_sha256
  `53c731d08c2a3ba838a13b3d63ad4337093c933daddec799d9a7eec3c035d424`); status
  `v3.1-status-2` with 6/144/174; the report-only dispatch check read the jobs endpoint
  (3 records, shape valid).
- **Prepare-only, twice.** Run 38620166885 at `780636f` (2026-10-14) and run 38655808728
  at `5357674` (2026-10-14, 63 min): every field of the second prepare output equals the
  first's except `code_commit`. Data manifests, filter snapshots, pack files, window packs,
  V3 pack, skipped hours and `prepare_sha256` are identical, so the code of #284 (which did
  not touch the packing code) reproduces the packs this registration pins. I compared the
  two saved documents field by field; the 5357674 copy is a reformatted (indented) copy of
  prepare.json, so the comparison is of values, which is what the pins hash.

## Expected run length

About 14 to 17 hours of wall-clock at GitHub's 20 concurrent jobs: 324 cells, of which the
144 minute cells take about 92 minutes each (about 11 hours of the run on their own), plus
prepare (about 44 minutes) and the V3 picks job (about 3.7 hours, which only the six
selector cells wait for). No single job should run longer than the timing measurements
above.

## Known effects at the small capitals

- **Hold at 100 USDT** puts 10 USDT into each of the ten coins. A coin whose share is below
  the exchange minimum stays in cash, and the report says so. At 1,000 USDT each coin gets
  100 USDT.
- **Minute baselines** split the capital over BTC, ETH and XRP, floored to 8 decimals; the
  remainder (0.00000001 USDT at 1,000 and 100) stays as disclosed cash.
- **V3 at the small capitals** may stop with `leverage_not_restored` because of exchange
  step sizes. Under the owner's 2026-10-12 rule that makes the comparison incomplete, so a
  pass at 100 USDT (and with it the whole verdict, which needs every capital) can be
  blocked. That is the cautious side, by design; 1,000 USDT is less exposed.
- **V3.1 itself** meets the same exchange minimums at 100 USDT; how it copes with them is
  part of what the test measures.

## Operating rules

1. **Integrate with a merge commit only** (GitHub's "Create a merge commit", `gh pr`'s
   `--merge` method). A squash or rebase rewrites the commits, so the code pin would not be
   in main's history and every registered job's trial gate would refuse.
2. **Nothing else lands on main** between this branch's creation and the registered run.
   The merge commit must bring only commit 3's artifacts on top of the code pin. If main
   has moved, the registration is rebuilt, not rebased.
3. **Review fixes** may touch only allowed registration artifacts. Note the narrow scope:
   only this review file (and other files under docs/reviews/ or docs/tasks/) can change
   freely. A change to `config/v3_1_registration.json` or `config/v3_1_run_manifest.json`
   breaks the completion's pins, and the register allows one completion per trial and no
   corrected trial, so it means rebuilding every commit of this PR (with the same trial id
   before integration, a new one after). A fix under src/, scripts/ or tests/ means a new
   code pin, likewise a rebuild.
4. **One dispatch**, from main, with `mode=registered` and `registration_sha256` set to the
   registration pin above. Never dispatch while another v31-run is queued or running.
5. **Never cancel** a registered dispatch: a cancelled launch counts as an execution.
6. **Never re-run** any job of it: a re-run makes the verdict incomplete.
7. **No change under src/ or scripts/ (or anything else outside the registration
   artifacts) on main until the run is done**, or the gate refuses.

**Rules the code does not enforce.** The people who integrate and dispatch must follow
these; the code at most refuses afterwards:

- **Never cancel** a registered dispatch: nothing stops it, and a cancelled launch counts as
  the registration's one execution.
- **One dispatch**: the dispatch check refuses a second one, but two dispatches created in
  the same second void each other, and a run deleted by an admin is invisible to it.
- **Nothing else lands on main** before the run: nothing prevents it; any change outside
  the registration artifacts makes every registered job refuse, so the registration must
  be rebuilt.
- **The PR is integrated with a merge commit**: nothing forces it; a squash or rebase
  leaves the code pin outside main's history, and the trial gate refuses.
- **Review fixes may only touch `docs/reviews/**` or `docs/tasks/**`**: anything else, the
  registration and run-manifest included, means a rebuild.
- Before the PR is integrated, a change to the registration can be rebuilt with the same
  trial id, because main's register does not hold it yet; after integration, any change
  needs a new trial id.

Where the code does act: `job_gate` refuses at the plan job (a launch stopped there with
nothing run does not count); the dispatch check (Ruling R4-2) refuses a second dispatch;
a re-run makes the verdict incomplete. This registration changes no GitHub setting.

## The experiment menu's status

The code pin (commit 2) sets `config/v3_1_experiment_menu.json`'s `"status"` to
`AUTHORIZED_FOR_ONE_REGISTERED_EXECUTION` at the owner's go, and changes nothing else in
the menu. What the code does with it:

- **No code reads the status.** `load_registration` reads only the menu's `arms` list
  (`_menu_arms`), checked against the registration's arms; the arms are unchanged (checked
  against main 5357674). No code pins the menu file's bytes: it is in neither the
  registration, the run-manifest, the completion nor the code digest.
- **The only check of the status is a test**: tests/test_v31_registration.py
  (`test_the_menu_states_the_owners_three_usdt_capitals`) now asserts exactly
  `AUTHORIZED_FOR_ONE_REGISTERED_EXECUTION`. No code expects any value.
- **Why in the code pin.** The menu is a registration artifact, so it could change after
  the pin; but its test is under tests/, which may not change after the pin. With both in
  commit 2, the code pin's own tree passes its own tests.
- **After the run**, setting the status back (or to a "done" value) needs the test changed
  in the same commit; that is ordinary work once the run is finished.

## Rulings of this task (Task 11)

- **T11-1 (code over brief): the allowed set is a list, not a glob.**
  `run_cell.REGISTRATION_ARTIFACTS` names exactly `config/v3_1_registration.json`,
  `config/v3_1_run_manifest.json`, `config/v3_1_prepare.json`,
  `config/v3_1_experiment_menu.json` and `docs/trials/register.jsonl`, plus anything under
  `docs/reviews/` and `docs/tasks/` (`_allowed`). Any other `config/v3_1_*.json` after
  the pin would refuse. Commit 3 holds only listed files. A tests/ file after the pin
  refuses: confirmed against `_path_errors`.
- **T11-2: the CI quality job fetches the whole history** (fetch-depth 0, was 2), in
  commit 2. The committed-registration test reads the code pin and its parent, which a
  two-commit checkout of the PR's merge commit does not hold, and once the registration
  exists it must not skip. The change is before the code pin, so no gate is affected; it
  touches nothing under src/ or scripts/ and no code digest.
- **T11-3: the run-manifest is in commit 3, not in the code pin.** Nothing in it depends on
  the code pin, so either works; commit 3 keeps the code pin to "main's code plus tests" and
  puts both pinned files with the completion that pins them.
- **T11-4: no row in docs/reviews/README.md.** The handbook forbids new rows (the table is
  frozen and pinned by check_reports.py); this file indexes itself with its `Index:` line.
- **T11-5: the spec pin** is the design spec at main `5357674` (the last commit that
  changed it, `8787026`, holds the same bytes), hashed as its git blob (LF), as
  `check_ready` hashes it, not as the CRLF working-tree copy.
- **T11-6: registration payload choices.** `candidates` are the ten V3.1 arms (only
  `combined` judged); the 32 baselines are hurdles, named in the hypothesis and selection.
  `sizes` are the three capitals in USDT, `[10000, 1000, 100]`. `seeds` is empty: no V3.1
  or driver code draws a random seed (the V3 walk-forward's uuid4 run-id prefix is not a
  seed and does not change results).
- **T11-7: the committed-registration test runs the registration commit's own code**, in a
  subprocess on a scratch checkout of that commit (git alternates, no copy of the
  objects), so later code on main can neither break nor weaken it. It hard-codes the
  prepare output's pins, main `5357674` and the spec pin, which were known before commit 2.
- **T11-8: file formats.** The run-manifest is canonical JSON (the loader requires it,
  written by `write_run_manifest`); the registration is indented JSON with sorted keys, as
  the rehearsal world's registration (`v31_smoke.register`). Both are LF by
  .gitattributes.
- **T11-9: this file's date** is 2026-10-15, the day it was written (controller ruling R-C;
  the completion's `review` names this path). Per the handbook the file indexes itself
  with its `Index:` line; no row is added to docs/reviews/README.md (T11-4).
- **T11-10: the prepare output used** is the 5357674 run's (`prepare-only-5357674.json`);
  its values equal the 780636f run's in every field but `code_commit`.
- **T11-11: the V3 seed test is fixed in commit 1.** tests/test_trial_register.py's
  `test_registered_v3_bootstrap_seed_matches_frozen_spec` read the register's last
  registration of any family and expected V3's bootstrap seed; commit 1's V3.1 event, with
  no seed, would break it. It now reads V3's own last registration (family `spec-v3`) and
  also asserts that it is V3's `v3-candidate-space-7-record`: the same assertion, plus one.
  With the fix in commit 1, the suite is green at every commit, and no tests/ file changes
  after the code pin.
- **T11-12: the menu status is set in the code pin** (controller ruling R-B), as described
  in "The experiment menu's status".

## The SDD ledger's rulings, in plain words

From the run driver's SDD ledger (`.superpowers/sdd/2026-10-12-v3-1-run-driver/progress.md`
in the controller's workspace), every line starting "Ruling" and every owner decision, in
order. "Superseded" or "amended" names the later entry that replaced it.

**Pre-flight (2026-10-12)**

- **P1.** Prepare reads its own committed file, `config/v3_1_prepare.json` (windows, coins,
  data manifests, filter snapshots), so it can run before a registration exists; it derives
  the packs and skipped hours, and the registration then pins the prepare file and copies
  the skipped hours. A registered prepare must reproduce every pinned pack or stop.
- **P2.** Only the prepare job uses the network: it fetches and checks every archive the
  minute baselines need, and the run jobs read them from the run's own artifact and check
  them again. (Extended by P14 and P19.)
- **P3.** The precomputed minute flow schedule is proved equal to feeding minutes into the
  replay: old expected values unchanged, plus a test in the replay's own call pattern.
- **P4.** Spot hourly bars for all ten coins come from the V3 inventory with one decoder and
  strict checks (no 2025+, no missing month, checksums, masks recomputed).
- **P5, amended (Task 3 ruling).** Quantity limits take the stricter of the two exchange
  lot-size filters; a partly missing market filter is refused (fail closed).
- **P6, with the Task 4 ruling.** "No retries" means no repeated experiment attempt; a
  failed archive download (connection, timeout, server error) is retried up to 4 times and
  logged, never a checksum mismatch, a missing file or a 2025+ month. Logging each failed
  attempt counts as logging every attempt.
- **P7.** Each coin's indicator history in a pack starts up to 365 days before the window
  (after its last excluded month) and is pinned in the pack.
- **P8.** Two functions assemble a pack, derive its skipped hours and refuse a window with
  a missing funding settlement.
- **P9, refined by P15.** The V3 selector gets its own input pack over V3's full history,
  so its frozen picks are not truncated; pinned in the run-manifest.
- **P10.** The pins: (a) the config pin is the registration file's SHA-256; (b) every
  window's data pin is the run-manifest's SHA-256; (c) the code pin is a commit before the
  registration commit, after which only registration artifacts may change; (d) cost
  profiles from the venue module; (e) one adapter pin per arm; (f) an FX record pin.
  **(f) is superseded** by the owner's decision of 2026-10-14 (three USDT capitals, no FX).
- **P11.** A pack's pin is the hash of its uncompressed canonical content, so it is the
  same on every machine.
- **Task 5 ruling.** A partial history month is judged on the hours held (stricter).
- **P12.** Adapter pins hash git blob ids of fixed module sets per arm kind, independent of
  line endings.
- **P13, amended by R2.** Each V3.1 run job writes its own evidence bundle once; the
  aggregate renders the pages and records each bundle's receipt.
- **P14.** Task 8 split in two; minute cells run from a verified legacy dataset.
- **P15.** The V3 input pack is built with V3's own frozen loader and assembly.
- **P16.** W1 also skips the minute baselines' own masked hours (BTC, ETH, XRP), so the
  minute comparisons are not incomplete by construction.
- **P17, narrowed by P17-precise.** XRP hours whose opening quote breaks frozen V1 rule 8
  are skipped too; precisely, only when the hour's opening quote breaches.
- **P18.** The frozen grids run at V3.1's base costs, not their own frozen fees (disclosed).
- **P19.** Prepare fetches all 216 legacy minute archives the frozen masks read.
- **P20.** Task 10 split into the command line (10a) and the workflow (10b).
- **Task 2 ruling.** An unreadable minute archive stops the job (fail closed).
- **Task 8b ruling.** Minute cells use only the repository's own pinned dataset spec and
  bot config, bound by git blob ids.

**Tasks 9 and 10 (2026-10-12/13)**

- **R1 (Task 9).** The aggregate accepts one fixed artifact layout; duplicates are refused.
- **R2 (Task 9), amends P13.** One folder per report page.
- **R3 (Task 9).** An invalid W1 outcome counts as missing (incomplete), never as evidence
  for a verdict.
- **R4 (Task 9).** Tests prove missing, failed, killed or invalid cells and an incomplete
  picks job turn a pass into incomplete.
- **P21, superseded by R4-1 for the code pin.** The registration follows in its own PR
  after #269 (owner-approved 2026-10-13 ~00:55Z); the code pin was to be #269's merge.
- **P17-precise.** See P17.
- **Attempt-id ruling.** Each cell records its own attempt id.
- **Task 10b rulings R1 to R4.** Run jobs always upload their folder; a queue keeps every
  dispatch and the operating rule forbids a second one; summaries are named per attempt; the
  2025 guard tolerates only "no match" and runs again before every upload.
- **Task 10b ruling.** An upload is skipped only when the pre-upload 2025 scan failed.

**Final review and fixes (2026-10-13)**

- **F1, with the F1-concern ruling.** Any re-run makes the verdict incomplete ("re-run
  detected"); a re-run turns a FAIL into INCOMPLETE while the fail stays recorded.
- **F2.** Long steps time out at 335 minutes, inside the 360-minute job limit.
- **F3.** A rehearsal mode runs the registered job graph on a synthetic world.
- **F4, with the F4-concern ruling.** A timing mode measures the heavy steps with results
  discarded; it uploads a stripped attempts log only.
- **F5.** Pinned V3.1 files stay LF in every checkout.
- **F6.** The dispatch-ref rule is documented, and the plan job checks it first.
- **F7, with C1.** Only the selector's cells wait for the picks job; the long-only V3 cells
  need no picks.
- **F8.** A minute or V3 cell drops the window pack after its gate.
- **F9.** Every workflow action is pinned to a commit SHA.
- **F10.** Wording of the "no artifact" state.
- **F11.** An always-run status job records every job's result.
- **F12.** Tests for V3's attempt-log shapes and the aggregate's branches.
- **F13, superseded in part.** Owner-plan constants were left to this review; superseded
  by the Codex round-3 ruling, which enforces them in code in every real mode.
- **Process ruling.** One corrective fix outside the single final fix wave (the wave had
  broken F7).
- **C2.** The verdict names its mode; rehearsal artifacts have rehearsal names.

**External reviews of #269 (2026-10-13)**

- **Ruling.** Fix Bob's upload condition and Codex's empty-aggregate case before the code
  freeze.
- **Ruling.** Name the 0.5% / 3% / 20% / 160% / 80% risk limits as constants with a pin test.
- **Ruling.** Fix Codex's P1 (capital exhaustion must be a FAIL, not incomplete) and P2
  (stale gap records); and the misleading wallet message on exhaustion-only runs.
- **Ruling, supersedes F13 in part.** The owner's windows, coins and (then) FX date are
  enforced in code in every real mode; smoke and rehearsal are exempt by mode.
- **Rulings.** A test-only stand-in for the owner plan in synthetic CLI tests is accepted;
  no extra pack-coin check in run-cell (the pack's content hash closes the chain); the FX
  date was checked only where a registration exists (moot since 2026-10-14).
- **Ruling.** Wait for a running Codex review before integrating.
- **R4-1, supersedes P21's code pin.** Every registered job and cell checks the V3.1 trial's
  committed completion (`check_ready`) and that it binds this code pin, registration and
  run-manifest; so the code pin follows the registration event (this PR's commit order).
- **R4-2, amended by the owner decision of 2026-10-13 ~18:25Z.** One dispatch per
  registration, enforced through GitHub's run titles. Amended: transient GitHub read
  errors are retried; an earlier launch that stopped at the plan job with nothing run does
  not count; the rehearsal runs the same check report-only.
- **R4-3.** The dashboard shows unbounded leverage as above the 2x cap.
- **Rulings.** A test seam in one run-cell test accepted; two extra fail-closed checks kept;
  bounded retries moved to the follow-up (done under the owner decision of 18:25Z).
- **R5-1, supersedes the "exactly one registration" rule.** The trial is picked by its
  completion's pins, so a re-registration is possible.
- **R5-2.** Header wording: only a dispatch a second or more later never voids an earlier.

**Owner decisions**

- **2026-10-12 ~22:58Z.** Codex out for a few days; its reviews go to others.
- **2026-10-13 ~00:55Z.** Sequencing: finish Task 10 and reviews, integrate #269, then this
  registration in its own PR, then a separate go for the run.
- **2026-10-13 ~10:40Z (go to integrate #269 on CI and the automated APPROVE),
  superseded** by the decisions of 20:31Z and 23:15Z.
- **2026-10-13 ~18:25Z.** The dispatch check's three layers (amends R4-2).
- **2026-10-13T18:43Z.** A trailing stop crossed at a completed close executes at the next
  real price, never during missing data (Codex P1s answered as by design).
- **2026-10-13 20:31Z, superseded at 23:15Z.** Fix the automated review bot before
  integrating #269.
- **2026-10-13T23:15Z.** Integrate #269 on CI green, Bob NO ISSUES, Codex +1 and
  independent re-checks.
- **2026-10-14T20:08Z.** Three capitals, all USDT: 100, 1,000 and 10,000. Supersedes the
  EUR 100 capital, its ECB FX pin (owner decision of 2026-10-12) and P10(f).
- **2026-10-15T00:56Z.** The go for the registered run, with the conditions above.
- **2026-10-15 ~01:05Z.** Save every run artifact permanently on GitHub after the run.

**Three capitals (2026-10-14)**

- **TC-1.** No schema bump of the outcome or cell metadata after dropping the FX pin.
- **TC-2.** Plan and status schemas bumped to `v3.1-plan-2` and `v3.1-status-2`.
- **TC-3.** A full 324-cell rehearsal before registration (done: run 38654503645).
- **TC-4.** Prepare-only re-run at 5357674 before registering (done: run 38655808728).
- **TC-5.** The committed-registration test goes in the code pin and checks the commit that
  introduced the registration, not HEAD (this PR).
- **TC-6.** Integration with a merge commit only, and nothing else on main until the run.

## Deferred items disclosed

From the ledger and the reviews of #269 and #284; none blocks the run, and the run code is
frozen, so they are disclosed rather than fixed:

- When the capital is exhausted, the recovery record's reason reads `integrity_failure`
  (the account's integrity check is false at equity at or below zero), not exhaustion.
- After capital exhaustion, cash going negative is excused whatever its cause; the run
  still fails, and the exhaustion is named.
- No test feeds a decoded outcome.json into acceptance end to end.
- Some limits are hard-coded without a name or a boundary test: the funding 25% cap, the
  margin-ratio 3 and 1 boundaries, the margin buffer and the replay records' 2x cap.
- A V3.1 cell judged invalid is withheld, so a liquidation in it reads as incomplete, not
  as a fail (to be disclosed in the run's report); a message typo ("exceeds30%").
- `changed_since` does not list untracked files (a shadowing file could slip past the
  change check); the CI checkout is fresh, so none exists there.
- With no data gap, the spot trend can re-enter the same coin at the same boundary right
  after a tightened-stop exit (fee drag); not changed, to be checked in the report.
- A registered dispatch deleted by an admin would hide from the dispatch check; two
  dispatches created in the same second void each other; a 10,000-run page cap.
- Two completions with byte-identical registration files would refuse each other (only
  one exists).
- Deferred and checked here: a whole minute month missing from the stream is not refused
  (it would add about 720 skipped hours; W1 has 140, so none is missing); `window_extras`
  would drop P17 silently if the quote test could not run (it ran: the
  `quote_test:XRPUSDT` source is present, with 0 hours); SOL's 2022-11 funding month could
  trip the missing-settlement refusal (prepare passed twice).
- About 70 minor deferred items (test gaps, docstring nits, refactors) are listed in the
  ledger; none changes a result.

## Limits of this review

- The development order: the V3.1 code was written before this registration event was
  recorded (R4-1 requires the event before the code pin, and the code was frozen first).
  What guards against tuning on results is that, per the ledger and the timing mode's
  design, no V3.1 result on real data was computed or seen before registration (timing
  discards results; prepare-only builds inputs only; rehearsals are synthetic). I did not
  independently audit that no earlier real-data V3.1 run exists.
- `docs/V3_1_SOURCE_INVENTORY.md` still says the pins are "not registered yet". It is
  updated after the run: documents outside docs/reviews/ and docs/tasks/ cannot change
  before then without every registered job refusing. The menu's `pending_registration`
  list is left as it is; only the status changed (R-B).
- I did not read GitHub's run records for the timing and rehearsal figures; they are the
  coordinator's and the ledger's.
