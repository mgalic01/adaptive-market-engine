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
- Verification: report/index checker, local Markdown link checks and diff whitespace
  checks; exact results recorded in the push handoff. No runtime tests or market runs
  needed for these documentation-only edits; no claim of current worker health.
- Required fixes/security: no known required fixes or new security findings in this
  documentation scope. The guide preserves the worker's bounded evidence and
  credential limitations by linking its operations document.
- Compatibility: paper-only behavior, protected-profit accounting, reserved-data
  gates and current-head external review remain unchanged. Revert these docs to undo.
- Next action: Claude or Bob, review the diagram and role descriptions against the
  implemented workflows, especially the distinction between notification, completed
  review and deliberate merge. Reply substantively at the full PR head before merge.
