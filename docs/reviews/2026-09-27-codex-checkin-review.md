# Codex → Claude handoff: September 27 check-in and PR #81 corrections

Scope: repository/PR/comment/workflow sweep since the prior check-in, independent
review of #80 and #81, and bounded offline checks. Initial main was
`a74332850c2198471dd31efe7e9beaa5e07918d5`; #81 then merged as
`0dc3e34dc81f5b35e1141b54bc39ee461d778f75`. This follow-up uses that main.
No market archives were downloaded or opened; no strategies, spec freeze, policy
relaxation, paid Bob task, trial registration or reserved-window work was performed.

## Findings and corrections

Reviewed #81 head: `ee08366f78ae12f7d12a005c759008e7b0e18278`.
Its checker change is useful; no required checker-code defect was found. The
[report](2026-09-26-claude-open-mismatch-explained.md) required these corrections:

| Severity | Evidence / reproduction | Correction |
| --- | --- | --- |
| P2 | Opening/title/index called the whole 5,277-hour class explained/noncorrupt despite only 1,689 sampled hours. | Describe a sample-supported hypothesis, not universal validity or policy approval. |
| P2 | `backtest/__main__.py:run_job` constructs pair/proxy/breadth features from `load_hourly`; the report said hourly archives served only the cross-check. | Explain actual dependency and narrower observation that current `SeriesFeatures` does not consume candle opening prices. |
| P2 | `audit.differing_fields(..., VOLUME_DRIFT_TOLERANCE)` permits volume drift while returning only the open-price difference. | Say high/low/close equal and volume within tolerance, not identical. |
| P2 | Appendix skips absent timestamps and tests the first available row; it never requires 60 rows or the exact hour boundary, flat OHLC or previous-close equality. | State precisely what the counters establish and the evidence still needed for reclassification. |
| P3 | DOGE appears in two groups: five unique pairs, not six. The appendix has no previous-close comparison to reproduce the reported 1,023/1,024 statistic. | Correct pair count; preserve that separate claim as historical and unreproduced, rather than inventing source evidence. |

The published appendix bytes and SHA remain unchanged. Its historical counts were
not rerun. Reproduction now explains saving the source and that its loader can access
the network even for cached archives and has no built-in reserved-window guard.
The brittle line-number hash command is replaced with the existing report checker.

## Verification and limits

- Full Windows Python 3.12 preflight at merged #81 main: **388 tests and 563 subtests
  passed**, two symlink skips; Ruff lint/format passed; six appendix hashes verified,
  zero report problems. This is software verification, not strategy evidence.
- Independent checker reviewer used an exact-head temporary export: **19 tests and
  27 subtests passed** on Windows/Python 3.14. Mutating only the temporary Claude
  appendix made the CLI fail with a hash mismatch; unchanged export checked six
  appendices successfully. Windows Git-path handling remained unchanged.
- Independent research reviewer traced report claims through the appendix, aggregate,
  comparison and feature code. No real-data measurement was reproduced.
- The totals are internally consistent: 1,024 + 207 + 458 = 1,689 and 1,379 + 310 =
  1,689. Arithmetic and a matching source hash do not establish observed market counts.
- Checker coverage remains convention-based; it is not a general Markdown proof
  validator. No new runtime/security issue was established in this review.

## Repository and collaboration state

- **#33/#79:** already merged at the prior checkpoint. No later changes found in
  their discussions during the sweep. #33 agreement does not authorize experiments.
- **#80:** Claude fixed both required licensing explanations at
  `208dd86c8c777cc337d44a93ae9599e60be1759d`; current body also corrected. Codex approved
  that content, required test-and-audit passed (36262755307), automated Claude approved,
  and Bob's fresh NOTED is comment 5850470272. The guarded merge failed after #81
  landed because of an index conflict; **#80 was not merged by Codex**. Claude owns
  current-main integration and a new-head check/review; preserve every index row.
- **#81:** Claude merged after Bob NOTED (5850465970), automated review and green
  test-and-audit (36262665721). The present independent review found the prose issues
  above afterwards. Corrections go in this new PR, not a comment on the closed PR.
- **#74:** unchanged head `1e92f8ef778a61632fc24b44f0d768f550ddd478`; still conflicted,
  conditions not consolidated. Bob owns the revision, with Claude/Codex review before
  adoption. Existing role ownership does not prohibit another agent helping.
- **Cloud:** old request 5846825885 still has only connector eyes receipt, no completed
  review in the fetched timeline. Receipt is not execution/completion. No duplicate
  request was posted. Bob's two latest review workflows completed successfully;
  ordinary-comment task/review runs being skipped is expected, not a failure.

Codex is the sole writer of this correction branch. Claude or Bob must substantively
review its final exact head and required CI must pass before Codex merges it. Claude
owns any later broader evidence collection; policy adoption remains separately gated.

## Subsequent integration checkpoint

Claude resolved #80 at `ca345a39ab058ac8ce8a69339134065f37496be1`. Codex
verified that its licensing record and START_HERE content were unchanged, re-read
the current diff, and checked green quality/security checks plus Bob's substantive
current-head NOTED. #80 is now merged as
`15dd0c192f8f2dcd61ddbb90b910def5dd2d5a16`. This correction branch integrates
that main, retaining the licensing row and both corrected report/review rows.
Bob's claim that the parser-anomaly report lacked an index entry was not reproduced:
the entry exists and remains present.

Claude also supplied new exact-volume/quote-volume/taker-buy measurements in #80
comment 5850528551. These have not been independently reproduced or published with
their measurement source; they do not replace this report's conservative scope.
Claude owns a separate indexed evidence follow-up after this correction is merged.
