# Codex and Claude collaboration guide

## Where messages live

1. **Start here:** root `CLAUDE.md` and `AGENTS.md` point to this guide and
   [the review index](reviews/README.md). Read both on opening a session.
2. **Durable handoffs:** write a new file under `docs/reviews/`, named
   `YYYY-MM-DD-codex-<topic>.md` or `YYYY-MM-DD-claude-<topic>.md`.
   Use a distinct topic (and suffix when needed); preserve earlier reviews.
   Add the file to the index in the same PR.
3. **Push notification:** after each push, post or update a PR Conversation comment
   headed **Codex → Claude handoff** (or the reverse). Link the handoff at that
   branch/commit, name the new head SHA, summarize changes since the previous push,
   and state exactly which review or next action is requested.
4. **Merge notification:** after merging, post a final comment on that PR with the
   merge commit, link to the handoff on `main`, checks actually completed, remaining
   work and any rollback or compatibility notes.
5. **Replies:** respond on the same PR and, for substantial feedback, in a new review
   file added to the index. Address each finding as fixed, agreed/planned, disputed
   with evidence, or deferred with a reason. Link the implementing commit or PR.

Claude should check both the repository files and GitHub PR comments/inline threads.
Files on an unmerged branch are visible through the PR link but not yet on `main`.
A posted handoff means **available**, not **read**. Only a reply establishes
acknowledgment. No direct agent-to-agent delivery is assumed.

The optional Claude review Action can add PR feedback when configured successfully.
Its last inspected run for PR #7 failed because no Anthropic credential was supplied.
The repository currently references the Actions secret `CLAUDE_CODE_OAUTH_TOKEN`.
Treat unavailable automation as unavailable review, never as approval. Check the
current run rather than assuming the earlier failure or a later success persists.
Never put credentials in a review, source file or log.

## Event-driven Codex cloud reviews (owner instruction, 2026-09-25)

The owner chose GitHub-triggered Codex cloud reviews for Claude and Bob's ready
handoffs. This starts a separate cloud review; it does not wake or resume the
owner's existing desktop conversation. Do not poll GitHub every five minutes.

After pushing a batch of changes and completing its local checks, Claude or Bob:

1. Opens or updates a non-draft PR and posts the normal indexed handoff with the
   full head SHA, verification results and requested review scope.
2. Checks whether Codex already has a pending or completed review for that exact
   head (automatic review may already have started). If so, do not duplicate it.
3. Otherwise posts a new PR Conversation comment containing `@codex review`, the
   full head SHA and the handoff link. Merely naming Codex in a heading or pushing
   a branch without a PR is not an explicit review request. Do not rely on editing
   an old comment to start a new review.
4. Records the reaction/review link when available. Posting the request is not
   proof of delivery, successful execution or approval. If the integration does
   not respond, report that limitation to the owner; do not repeatedly repost.

Use the existing connected GitHub/Codex integration. Do not introduce API keys,
PATs, scheduled polling or a relay workflow for this protocol. Review-only bot
jobs do not request another review, and status-only replies do not retrigger one.
Batch corrections into a new head before requesting another review.

Cloud review is additional evidence, not a substitute for required checks, the
full independent review, explicit owner gates or repository protections. It never
authorizes a merge by itself. Paper-only scope and protected-profit rules apply.

Reference: [official Codex GitHub review documentation](https://learn.chatgpt.com/docs/third-party/github).

## What every handoff contains

- **Scope and status:** author, recipient, date, branch/PR, exact base and reviewed
  head; distinguish pushed, awaiting checks, reviewed and merged.
- **What changed and why:** observable behavior, affected components, and relevant
  decisions or constraints.
- **Verification:** commands/checks, outcomes, tested commit, and what was not tested.
  Distinguish software regressions, security scans and strategy-performance evidence.
- **Required fixes:** severity, affected file/component, reproduction or supporting
  evidence, impact, proposed correction and a regression check. If none were found,
  say “No known required fixes in the reviewed scope”; do not imply the whole product
  is proven correct.
- **Security:** concrete findings or unverified concerns, their impact, suggested
  mitigation and how it would be checked. State the review's limits. Do not invent
  findings or claim that passing a scanner proves security.
- **Optional improvements:** prioritize useful changes; explain their benefit,
  effort, compatibility risks and verification. Separate observations and hypotheses
  from established defects.
- **Safe next steps:** a small ordered set, intended owner, dependencies, and acceptance
  evidence. Preserve working behavior, APIs, persisted data, accounting and risk
  constraints unless a deliberate change is justified and documented.
- **Question for the other agent:** specify the files/behavior to examine and the
  expected reply location.

## Working without disrupting the product

Use focused branches/PRs, refresh `main` before starting, and coordinate ownership
before editing modules another agent is changing. Prefer the smallest effective fix.
Keep speculative strategy changes separate from correctness fixes.

Use regression checks appropriate to the affected behavior. For engine refactors
or replay optimizations, require equivalence, deterministic replay and restart/
accounting evidence where relevant. For persisted-format changes, explain migration
or explicit incompatibility before merge and preserve original data. Describe a
practical revert path; reverting code alone may not reverse a data migration.

The owner authorized Codex to push and merge routine work without another approval
request once tests, required GitHub checks and blocking findings are addressed.
Respect required reviews and repository protections. Seek independent agent review
for substantive engine, accounting, security or strategy changes; report honestly
when it has not occurred. Never mark a failed reviewer job as an approval.

Avoid weakening risk controls or changing product scope merely to improve a backtest.
New strategy hypotheses need their own specifications and evaluation. Preserve the
current paper-only boundary and the protected-profit accounting requirements.

## Copyable handoff outline

- Status / PR / base / head:
- Changes and reasons:
- Checks passed / failed / not run:
- Required fixes and proposed corrections:
- Security findings, mitigations and review limits:
- Optional improvements and compatibility risks:
- Next steps and intended owner:
- Claude/Codex: please check ... and reply on PR ...; longer reply goes in
  `docs/reviews/YYYY-MM-DD-<agent>-<topic>.md`.
- After merge: merge SHA / final checks / remaining items / revert or migration notes.
