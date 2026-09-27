# Codex → Claude handoff: agent workflow guide

- Date: 2026-09-27. Writer: Codex Desktop. Branch: `codex/agent-workflow-guide`.
- Base: `f937d6756b5ce54fff4456348902d2fd2cfee870`.
- Isolated worktree: `work/github-local-worker`, reused after PR #94 merged;
  the deployed worker uses its separate immutable release directory.
- Scope: owner requested a durable GitHub copy of the diagram and role descriptions
  explained in chat. [The guide](../AGENT_WORKFLOW.md) records roles, review flow,
  notification boundaries and explicit merge decisions; linked from the handoff guide.
- Status: documentation publication; latest pushed SHA and review status are in the
  PR Conversation handoff. No new automation or authority is introduced.
- Verification: the original publication used report/index, local Markdown link and
  diff whitespace checks. Follow-up verification is recorded below; no market runs
  or claim of current worker health.
- Required fixes/security: the original publication's known review findings are
  addressed below. The guide preserves the worker's bounded evidence and credential
  limitations by linking its operations document.
- Compatibility: paper-only behavior, protected-profit accounting, reserved-data
  gates and current-head external review remain unchanged. Revert these docs to undo.
- Next action: Claude or Bob, review the diagram and role descriptions against the
  implemented workflows, especially the distinction between notification, completed
  review and deliberate merge. Reply substantively at the full PR head before merge.

## Follow-up: review trigger safety and canonical request rules

- Reviewed the full PR #97 discussion at
  `949560d42bf16f320ffbf02c78366546b8a769b2`, including the
  [Cloud inline finding](https://github.com/mgalic01/adaptive-market-engine/pull/97#discussion_r4115052995)
  and the [local review's two P2 findings](https://github.com/mgalic01/adaptive-market-engine/pull/97#issuecomment-5855782975).
- Fixed both reviewer rows in the secondary overview to link the canonical quick
  reference/request procedure. The overview no longer reproduces executable review
  trigger phrases. Request mechanics, including both existing-request and
  pending/completed-review deduplication conditions, remain in the canonical guide.
- Did not adopt the automated Claude review's suggested current-outage caveat:
  its conditional allowance fallback is not evidence of a current outage. Its
  reported test results remain attributed claims. The diagram intentionally has a
  changes-needed feedback cycle; the review's description of it as a DAG is inaccurate.
- Writer transfer: Codex Desktop delegated this correction to a named Codex subagent
  in the same clean worktree at the full head above, stopped writing, and received
  the incoming writer's acknowledgment. Codex Desktop retains the later merge
  decision. Subagent checks do not satisfy the external-review requirement.
- Local verification on Windows with `C:\Python314\python.exe`, against the worktree
  based on that head plus the overview correction: `python scripts/preflight.py`
  passed lint, format (192 files), report/index checks (0 problems), and the full
  deterministic suite: **425 passed, 2 skipped, 563 subtests passed**. The skips are
  not passing coverage; this preflight does not run full CI/security/type checks.
  No market-data fetch, strategy-performance run, diagram render, live-service
  health check or deployment was performed.
- Added the coordinating session's [Cloud findings audit](2026-09-27-codex-cloud-findings-followup.md)
  and index row after preflight. Reran `python scripts/check_reports.py`: 0 problems.
  A Python inline check verified 85 relative file/anchor targets across the overview,
  both publication handoffs and review index, balanced code fences, and no executable
  review trigger phrases in the overview or either handoff. `git diff --check` passed.
  The broader audit's runtime results are supplied by the coordinating session,
  not independently reproduced by the documentation writer.
- The final pushed SHA is recorded in the PR Conversation handoff. Required GitHub
  checks and substantive Claude/Bob review
  must cover that new full head; the prior clean verdicts do not carry forward.
- No known remaining required fixes or new security findings in this documentation
  correction. Compatibility and rollback remain a documentation-only revert.

## 2026-09-27 main integration

- Starting head: `ce8dfb13732ebf54caf0e5a1bc6da1bc3259da42`; merged main
  `238e2c71c5ee812ffb46d6169ce54eae565571ff` without rebasing. The sole conflict
  was the review index; both PR #97 entries and PR #104's worker-provenance entry
  are retained. The worker source, tests and operations document match that main
  commit; PR #97's change relative to main remains documentation only.
- Codex Desktop explicitly transferred this clean worktree back to the documentation
  writer and stopped editing before integration. The incoming writer acknowledged
  ownership. The coordinating session retains the later merge decision.
- On the combined tree, `python scripts/preflight.py` passed on Windows/Python 3.14:
  lint, format (194 files), report/index checks (0 problems), **426 passed,
  2 skipped, 563 subtests passed**. This is one full preflight after integration,
  not a claim that the two skipped checks ran. Later edits only record these results
  and the integration addendum; documentation checks are recorded in the push handoff.
- The audit preserves captured-head history and adds the #104 merge, historical Bob
  review, Claude notifications and separately assigned late worker finding. No
  deployment or worker restart occurred. No new market-data or strategy check was
  performed; full GitHub checks/security/type validation and substantive peer review
  must cover the new full head. Older reviews are historical.
