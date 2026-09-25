# Claude: sweep of every PR and issue for unanswered comments (2026-09-25)

- **Owner request:** "check and visit all PRs and check are there any unanswered
  questions or what is the status, perhaps some PRs need to be reopened."
- **Why:** comments on closed PRs notify nobody. The new rule (quick reference,
  "Never post on a closed or merged PR") stops new ones. This sweep catches the old
  ones.
- **Method:**
  - listed all 36 PRs and all issues;
  - compared each PR's last update with its close time;
  - read every comment posted after closing on PRs #6, #7, #9, #12, #16, #19, #21
    to #25, #27 to #30, #32 and #34;
  - PRs updated within a minute of closing had only the merge event, and
    #17, #20, #35 and #36 had no later update.
- **Result:** no PR needs reopening. Everything below is answered here or moves to a
  new PR, linked back.

## 1. Unanswered: Bob's owner-goals message on closed PR #21 (comment 5839515688)

Bob recorded the owner's goals:
- grow €100 over 1–3 years by compounding;
- losing the €100 active stake is acceptable; losing more is not;
- top-ups are possible.

He then asked four things. Answers:

| Bob's point | Status | Answer |
| --- | --- | --- |
| **G successor rule** (the backward convention on a cadence change) | Already settled | Spec v1 §3 G's uniform-cadence rule (PR #20, merged) gives the same fail-closed result as Bob's proposal: any mixed window is unavailable until three uniform records with exact steps exist. No spec change is needed. |
| **G tests implemented?** | **Yes** | PR #25 (merged) implements the parser and signal with 17 tests, one per required test in §3 G (8→4, 4→8, hidden gap, overdue boundary and the rest). Only "existing grids and exits unchanged" waits for the replay wiring (P8). |
| **H implemented?** | **No** | §3 H is specified, but no code exists yet. It is the next Claude implementation item and needs no new data for the development windows beyond P8's daily history. |
| **C1 (≤ 10% drawdown) and C5 (≥ 1 completed cycle a week) calibration** | Open, answerable now | Both can be checked on the existing V0 development runs without new data. Claude will report how many runs sit near each boundary and why, before any threshold is touched. A change to C1 or C5 remains an owner decision and a spec change. |

## 2. Required fixes posted by the automated review after a merge

The automated review runs on each push and sometimes finished after I merged on
Bob's NOTED. These findings were never answered:

| PR | Finding | Status |
| --- | --- | --- |
| #21 (5837081026) | `_validate_manifest` checks only that `instruments` is a dict. A missing or non-numeric `tick_size`, `quantity_step` or `min_notional` raises `KeyError` or `InvalidOperation` in `rules_for`, not `DataError`. It still aborts the run and never computes wrong numbers. | **Valid.** Fix in a new PR: validate each instrument entry, with tests. |
| #25 (5837121505, optional) | The funding-rate parser does not cap the exponent, unlike `amount()` (`"1E-9999"` passes). Inert until G is wired into replay. | **Valid.** Fix in the same PR, before P8 wires G in. |
| #34 (5838239671) | A failed download could be cached forever. | **Does not reproduce.** `actions/cache@v4` saves only when the job succeeds (`post-if: success()` in its `action.yml`), and the hash check fails the job first. `bob-task.yml` now saves only a hash-verified package, before Bob starts (#36). |
| #30 (5837894534) and #24 (5836974880) | Text written **after** Bob's signature makes the extraction drop the real answer. The extraction also has no regression tests. The other #30 finding was withdrawn by its author. | **Valid. Owner go to fix now:** PR #39, a shared and tested extractor (Codex's point 2). |
| #27 (5837619746) | The rule that Bob never touches the reserved 2025–26 window is enforced by the prompt and a filename check only. Egress is open, `data/` files with other extensions are not checked, and Bob's summary is not scanned for reserved dates. | **Valid. Owner decision (2026-09-25): accepted as a documented risk; Bob's internet access stays open.** Recorded in the handbook's Bob task-run rules. |
| #22 (5836367347) | The claim that Bob's reads stay inside the workspace rests on the vendor default, not on a test in this repo. | Covered by Codex's audit: his read-only reviews see only what the workflow gathered. It stays on Codex's review list. |
| #28 (5837622236) | A blank line broke the catch-up table. | Already fixed in #32. |
| #9 (5813725083) | Integrity gates and the depth bound. | Fixed as R1–R4 in #12. |

## 3. Everything else

All other late comments were handoffs, merge notes, approvals or optional nits that
are already done or recorded. Issue #31 (the Bob task run) is open, and its restarted
run is in progress.

## Next

1. PR #38: instrument validation in manifests and the funding-rate exponent cap,
   with tests.
2. PR #39: the shared, tested answer extractor (owner go).
3. Claude: check C1 and C5 against the V0 development runs and report.
4. Claude: implement H (§3 H) on its own PR.
5. Owner decision recorded: Bob's internet access stays open; the reserved-window
   risk is accepted and documented.
