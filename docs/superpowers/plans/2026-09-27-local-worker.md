# Local reviewer implementation plan

Goal: start sceptical PR review from GitHub events using local ChatGPT login.
Spec: [design](../specs/2026-09-27-local-worker-design.md).
Writer Codex, isolated work/github-local-worker branch codex/github-local-worker.

- [x] Test authentication, selection, dedup, queue and budgets before implementation.
- [x] Implement receiver/queue and isolated model runner; no repository execution.
- [x] Supply immutable files/diff, base rules and current PR evidence.
- [x] Remove automatic merging after owner clarified role; restrict writes to comments.
- [x] Add restart/closure/locking, stale evidence and scope-screen regressions.
- [x] Test signed delivery, dedup redelivery, unsigned rejection and one real local review.
- [ ] Pass final corrected-head CI and Claude/Bob substantive review.
- [ ] Activate reviewed immutable code copy for bounded reviews/comments; record
  actual state and notify agents. No automatic merger or branch-policy change.
