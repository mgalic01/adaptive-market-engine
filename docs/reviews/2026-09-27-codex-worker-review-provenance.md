# Codex → Claude handoff: local worker review provenance

2026-09-27. Named writer: Codex worker-fix subagent, delegated by Codex Desktop.
Branch: `codex/worker-review-provenance`. Isolated worktree:
`work/worker-review-provenance`. Ownership recorded before implementation edits.
Base: `de38fdb27e3e094061c69f8ecc7530761120f9f4`.

Scope: the two post-merge PR #94 findings: include the captured base SHA in
published recommendations and document the mandatory `/github` webhook path.
Owned files: `scripts/local_worker.py`, `tests/test_local_worker.py`,
`docs/LOCAL_WORKER.md`, this handoff and its index row. No other writer's tree
is touched. No deployment change or worker restart is authorized by this fix.

Status: ready for external review; the exact pushed head and review evidence are
recorded in this branch's open PR Conversation. Claude/Bob must substantively
review the latest full head before any merge. No automatic merge path is introduced.

Baseline: `python scripts/check_reports.py` reports 0 problems;
`python -m pytest tests/test_local_worker.py` reports 35 passed on Windows.
Synthetic fixtures only; no market-data download, inspection, replay or strategy
change.

## Findings and correction

The [missing base identity](https://github.com/mgalic01/adaptive-market-engine/pull/94#discussion_r4115018328)
made an old recommendation indistinguishable from one against a later base while
the head stayed unchanged. Every new report now names the captured full base and
head SHAs and says either changing invalidates its recommendation. The controller
supplies the base directly from its evidence snapshot; model output cannot choose
it. Regression coverage exercises READY, STALE and BLOCKED publication and verifies
the local report is identical to the body handed to the comment publisher.

The [missing webhook suffix](https://github.com/mgalic01/adaptive-market-engine/pull/94#discussion_r4115018334)
is corrected in [operations](../LOCAL_WORKER.md): Payload URL must use the tunnel
HTTPS origin plus `/github`, including after a tunnel URL change. The handler
accepts POSTs only at that path; an origin-only webhook returns 404.

## Verification

Windows, Python 3.14.7; changed working tree on the full base named above, with no
implementation changes after these checks:

- Red: `python -m pytest tests/test_local_worker.py -k binds_recommendation`
  failed in all three cases specifically because the published body lacked base.
- Green: `python -m pytest tests/test_local_worker.py`: 36 passed.
- Initial `python scripts/preflight.py` stopped at formatting because patch edits
  mixed line endings. `python -m ruff format scripts/local_worker.py
  tests/test_local_worker.py` normalized the two files.
- Final `python scripts/preflight.py`: lint and format clean, report checker
  0 problems, full deterministic suite 426 passed, 2 skipped, 563 subtests passed.
- `python -m mypy src scripts`: no issues in 44 source files.
- `python -m bandit -q -r src scripts`: exit 0, no findings.
- `git diff --check`: clean. Required GitHub CI and independent review remain
  separate gates. No actual model run, tunnel change or external webhook delivery
  was performed for this fix; the existing loopback HTTP test passed.

## Compatibility, limits and owners

Report wording gains the base SHA and expiry notice; no schema, queue migration,
API permission, merge function or accounting/risk behavior changes. Historical
published reports are not rewritten, base-only pushes do not gain an event trigger,
and the existing publication race remains. Reviewers must compare both SHAs with
current PR state even when no replacement report appears. No additional security
finding is known within this narrow scope; scanner success is not proof of security.
Reverting this commit restores the prior formatting and documentation without a
data migration. No optional improvement is bundled.

Codex owns fixes and the visible exact-head handoff. Bob is requested once to
critically inspect both corrections and the regression fixture; Claude may review
in the same open PR. Until substantive latest-head external feedback and required
checks exist, merge remains blocked. Deployment refresh is a separate owner/Codex
action after review and is not performed by this branch.
