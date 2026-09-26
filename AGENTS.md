# Repository collaboration instructions

**Codex, first action when you next start (owner request, 2026-09-25):** review
everything merged while you were unavailable (PRs #20 onward; each is listed), using
[the catch-up note](docs/reviews/2026-09-25-claude-handoff-to-codex.md), before any
other work. Post your findings as a Codex → Claude handoff **in a new PR** (not as
comments on the merged PRs), then remove this paragraph in the same PR.

**How to reach Claude, Bob and Codex** (`@bob`, `/bob-run`, task-file merges,
`@codex review`) is in the quick reference at the top of
[docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md#quick-reference-how-to-reach-each-agent-keep-this-current).
**Never post on a closed or merged PR or a closed issue: nobody is notified.** Use a
new PR or the open PR concerned, and link back (same section).
**At every start, list the open PRs and read what is new since your last visit before
other work; do not rely on notifications** (same section).

Read [docs/AGENT_HANDOFF.md](docs/AGENT_HANDOFF.md) and
[docs/reviews/README.md](docs/reviews/README.md) before continuing work.
Read the current PR discussion and verify its head before acting on older notes.

The owner authorized Codex to push and merge routine project changes after tests,
required checks and blocking review findings are addressed. Existing repository
protections still apply. Every push and merge must leave a visible Claude handoff
using the shared guide. Include relevant fixes, security findings, improvements,
verification evidence and compatibility risks; say explicitly when none are known.

Keep changes focused and preserve established behavior through appropriate
regression checks. Coordinate edits to shared modules in the PR before starting
overlapping work. The project remains paper-only under its existing scope.

A third agent, Bob, does large runs, data checks, tests and monitoring from written task
files. Its rules are in the "Three agents" section of the guide, in force since PR #16
merged with Codex's and Bob's agreement (see
`docs/reviews/2026-09-25-codex-pr16-final-review.md`).
