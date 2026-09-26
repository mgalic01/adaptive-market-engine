# Codex → Claude handoff: current-state review

**Date:** 2026-09-26. **Author:** Codex desktop with three independent reviewers.
**Reviewed main:** `25d4c4bdef0fdfabd458b6314eabec97f107e8eb` (PR #76).
The associated PR discussion records the correction head, required checks and merge.

The owner asked to check the work in Git again after enabling Superpowers. This pass
combines fresh regression checks and independent runtime, workflow and research reviews
with the earlier [retrospective](2026-09-26-codex-retrospective-review.md) and
[closure ledger](2026-09-26-codex-audit-closure.md). It found two workflow defects and
three documentation corrections. It found no new required runtime/accounting fix in
the inspected paths. It does not claim every possible input or historical result has
been independently reproduced.

## Findings and corrections

| ID / severity | Reproduction and impact | Correction / verification |
| --- | --- | --- |
| W1 / **P2**: review SHA can identify different code from the diff | `bob-review.yml` obtains PR head metadata, then separately requests the mutable PR diff. A push between those calls can label B's diff as A's review. The original finding is source-traced; the correction uses a local Git fixture with a dummy GitHub command, not a live race. | Capture base/head together and generate the diff from those immutable commits, with external diff/text conversion disabled. Validate identifiers and fail when required history is unavailable. This preserves exact-version evidence; a later push still needs a new review before merge. |
| W2 / **P2**: summary-only task disappears without delivery | A dummy artifact containing only valid `summary.md` is accepted by the old validator with an empty report name. On push/manual triggers, both publication and reply are skipped, and the green job has no failure alert. | Require a report as well as a final summary. Missing-report validation fails and enters the existing owner-alert path. A stopped task can write an honest incomplete report; a summary alone is not completion. No new task is launched to test this. |
| D1 / **P2**: current method describes obsolete baseline sampling | `BACKTEST_METHOD.md` says buy-and-hold uses only minute closes and common sampling is planned. Current `replay.py` calls `hold.mark` inside the same four-quote loop as strategy equity. This misstates comparability of current drawdown measurements. | Describe the implemented shared sampling and its intraminute limits. Preserve old results' original code/measurement provenance; no historical result is regenerated. The existing intrabar-dip regression passes. |
| D2 / **P3**: warm-up off by one | The method and a test comment say 742 hours. The first defined 24-hour volume is at index 23; 720 defined values put the first median at index 742, requiring 743 completed observations. | Correct both descriptions. A synthetic parent probe confirms unavailable after 742 observations and available after 743. Runtime readiness already behaved correctly; no runtime change. |
| D3 / **P3**: completed task entries appear pending | The task index still says the outage and refined-parser tasks will run when merged, despite reports merged in #66/#65. | Mark the measurement work done and link its reports, while preserving separate outage/parser/tolerance policy decisions. This edits the index only and does not add a runnable task file. |

The final PR discussion identifies the exact correction commit and executable
regression results for W1/W2. No passing live-service or end-to-end notification test
is inferred from the offline fixtures.

## Fresh verification and provenance

- **Parent, Windows/Python 3.12, reviewed main:** actual `python scripts/preflight.py`
  passed **381 tests and 563 subtests**, with two Windows symlink-privilege skips;
  pytest took 23.82 seconds. Lint, formatting and five embedded appendix hashes passed
  with zero report problems. `python -m mypy src scripts` passed for 40 source files;
  `python -m bandit -q -r src scripts` passed. These are software/scanner results,
  not security proof or investment-performance evidence.
- **Independent runtime reviewer, same main:** **205 tests and 192 subtests passed**
  in 19.98 seconds across ten modules covering profit vault, simulator execution and
  persistence/recovery, replay, data/loaders/CLI/audit, and funding. Read-only inspection
  found no new required correction in these paths. Funding remains standalone; this
  does not verify unimplemented strategy variants.
- **Independent workflow reviewer, same main:** **86 helper tests and 38 subtests
  passed**, two Windows symlink skips, using Python 3.14. The review covered triggers,
  authorization, worker/publisher separation, output extraction, publication scope,
  failures and local preflight. The two findings above were not covered by those
  existing passing tests; new reproductions are required for the corrections.
- **Independent research reviewer:** read current methods/specifications, relevant code,
  owner decisions, handoffs and proposal refs #33/#74. No new substantive method or
  protected-profit contradiction was established beyond D1/D2/D3. No economic-result
  recomputation or external-source verification was performed.
- **Parent history check:** all **39 historical ledger rows** have both their recorded
  merge commit and merged head in current main's ancestry. This verifies the recorded
  commit relationships, not a fresh rerun of every historical check or market matrix.
- **Parent documentation check:** 89 tracked Markdown files were scanned for relative
  file links, excluding fenced/inline code and fragment-only links. After the method/task
  corrections, 210 file-link occurrences resolved, all review files were indexed and
  there were no duplicate index targets. Heading anchors and external URLs were not
  validated by that scan. The final report/index additions are checked again before push.

The final correction head receives its own required Linux CI and independent review;
the baseline results above are not substituted for changed-code verification.

## Open proposals and communication

At this audit, only these proposals were open:

- **#33:** `3a893d9a3955f3e320f53b495aa66183a002f392`. Required quality run
  `36244684588` passed. Codex and Bob's agreement at that head is recorded; Claude's
  revised-method acknowledgment remains pending. Codex owns final integration, including
  the review-index-only conflict with current main. A new integrated head needs current
  checks and acknowledgments; old evidence must remain version-specific.
- **#74:** `1e92f8ef778a61632fc24b44f0d768f550ddd478`. Required quality run
  `36245628024` passed. The existing Q1–Q4 conditions remain unincorporated, and the review
  index conflicts with main. Bob owns revision/integration; Claude and Codex then review
  the resulting exact head. No role/model/hook/test-group proposal is silently adopted.

The owner has now endorsed giving Bob bounded first-pass preparation and verification:
change/question inventories, authorized tests, report counts/hashes/links, and concrete
reproductions. Reports must identify the actual code version, evidence and verification
limits. Primary roles remain nonexclusive: Claude leads design/implementation, Codex
independent review, and Bob preparation/verification. Record this direction in #74's
revision; it does not waive task authorization or the three-agent agreement gate.

The Cloud integration test still has connector receipt but no visible completed review
in the inspected discussion. Private task-log access remains unavailable from the
signed-out browser; no cause is inferred and no duplicate trigger was sent. The failed
automated Claude jobs on the proposal heads are a separate path and count as unavailable
review, never approval. See the [return brief](2026-09-26-codex-claude-return-brief.md).

## Boundaries, compatibility and next owners

No live orders, credentials, reserved market archives, new strategy trials, large replay
matrices, paid Bob task jobs or data downloads were used. The worker's own-key and open
network exposure remain owner-accepted risks documented in the guide; the residual
Actions-token risk is not solved by these fixes. Live vendor internals, branch-protection
configuration, actual notification delivery, live market feeds and unimplemented variants
were outside this pass and remain unverified.

The fixes change workflow evidence/delivery and documentation, not runtime APIs, database
formats, trading policy or protected-profit accounting. Reverting needs no data migration,
but would reintroduce the two workflow defects. Missing-report artifacts now fail
intentionally; callers must provide a report rather than rely on empty-report success.

**Codex:** finish correction review/checks and publish merge feedback; integrate #33 when
the agreement conditions are satisfied. **Bob:** revise #74 and incorporate the owner's
bounded-preparation direction. **Claude:** read this update and the return brief, acknowledge
the revised #33 method and review #74 once corrected. Repair/tolerance adoption, outage
policy, license-rule provenance, spec freeze and the pre-experiment trial register remain
separate unfinished decisions/work, not approvals created by this audit.
