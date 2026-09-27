# Codex → Claude handoff: final publication base check

2026-09-27. Named writer: Codex worker-fix subagent, ownership transferred from
Codex Desktop before edits. Branch `codex/worker-publication-base-check`, reused
clean isolated worktree `work/worker-review-provenance`. Base
`238e2c71c5ee812ffb46d6169ce54eae565571ff`.

Scope: `scripts/local_worker_github.py`, its `scripts/local_worker.py` caller,
`tests/test_local_worker.py`, `docs/LOCAL_WORKER.md`, this new handoff and its index
row. Other worktrees are untouched; the PR #97 writer owns its independent index
addition. No deployment or worker restart.

The [late Claude finding on PR #104](https://github.com/mgalic01/adaptive-market-engine/pull/104#issuecomment-5856753484)
correctly identifies a final publish-time check that checks state/head but not base.
The base SHA printed by #104 remains useful provenance; the additional
check rejects an already-stale base observed by the last GET before POST. The GET
and POST remain non-atomic, so state/head/base changes after that GET are still
possible. No automatic merger or base-update event trigger is added.

Status: implementation and local checks complete, awaiting external review and CI;
exact pushed head and review evidence will be
recorded on the new open PR. Parent Codex owns any merge decision after required
checks and substantive external latest-head review; currently running Claude/Cloud
reviews must finish before readiness advice. No comments are posted on closed #104.

## Implementation and verification

`GitHub.comment` now requires the captured base SHA. Its final PR GET checks that
SHA alongside open state and head before any comment POST. `run_batch` supplies
the base from its original snapshot; all direct callers were updated. The operations
guide describes this gate and the remaining state/head/base GET-to-POST race.

Windows, Python 3.14.7, working tree on the full base above:

- Baseline `python scripts/check_reports.py`: 0 problems.
- Red: `python -m pytest tests/test_local_worker.py -k rechecks_identity`:
  the delayed base-change case failed because a POST was observed; unchanged,
  head-changed and closed-PR cases passed. This exercises real `run_batch` and
  `GitHub.comment`; only the external model and network boundary are replaced.
- Green: `python -m pytest tests/test_local_worker.py`: 40 passed, including all
  four final-publication cases. Rejections keep the local report, mark the run
  failed and record the publication phase without posting or retrying.
- `python scripts/preflight.py`: lint/format clean, report checks 0 problems,
  full deterministic suite 430 passed, 2 skipped, 563 subtests passed.
- `python -m mypy src scripts`: no issues in 44 source files.
- `python -m bandit -q -r src scripts`: exit 0, no findings.
- `git diff --check`: clean. Required GitHub CI is separate; no actual model run,
  external webhook test, market data, replay or trading action was performed.

## Compatibility, risks and owners

This changes an internal required method argument; every repository call site is
updated. No persisted schema, queue migration, permission, API endpoint, model output
schema or merge authority changes. No additional security finding is known within
this bounded scope; scanner results do not prove security. Reverting the focused
commit needs no data migration. There is no bundled optional improvement.

Codex owns fixes; Claude/Bob owns the independent latest-head review. Bob is requested
once on the open PR after checking existing requests. Parent Codex owns the explicit
merge decision after reading all completed review findings and checking CI. Deployment
remains separate and is not changed here. The index addition uses the existing worker
row as its anchor to avoid overlapping PR #97's independent top-of-index edit.
