# Codex → Claude handoff: standing external-review rule

**Owner instruction:** 2026-09-26. **Base:**
`d7b2856193ebd0c210df827469be534e67ca9596`.

The owner explicitly instructed Codex not to merge its own work until another agent
reviews and comments, critiques or approves it, with Codex choosing the reviewer.
The owner then requested durable project documentation so this survives a new chat.

The rule is now explicit in root `AGENTS.md`, the mandatory `docs/START_HERE.md`
checklist and the shared `docs/AGENT_HANDOFF.md` guide. Claude or Bob must post a
substantive review at the latest full head before Codex merges its own, delegated or
integrated work, including documentation. Codex-only reviews do not qualify. If neither
reviewer is available, the PR remains open. Blocking findings, required checks and
additional proposal agreement gates still apply. A new push requires current-head review.

This documentation PR follows that rule itself: Codex requests Bob's bounded review
and records the review and required-check evidence in the PR before merge. Publication
and merge SHAs are recorded there; this file does not predeclare approval or success.

Scope is documentation only. No new technical branch protection, permissions, triggers,
task files or runtime behavior are introduced. Paper-only operation and protected-profit
accounting are unchanged; no known new security issue or compatibility risk is introduced
within this documentation scope. Reverting needs no data migration, but would remove
the startup reminders. Report/link/diff checks and required CI are recorded in the PR.

**Next owners:** Codex requests and evaluates external review before any self-authored
merge; Claude or Bob supplies the review. Existing #33/#74 agreement requirements remain
separate. This rule records the owner's instruction directly and does not wait for #74
to adopt it.
