# Repository collaboration instructions

**First, every session start and check-in: follow [docs/START_HERE.md](docs/START_HERE.md) step by step** (owner request, 2026-09-26). The rest of this file is detail for Codex.

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

**Owner rule, 2026-09-26: Codex must not merge its own work until Claude or Bob has
reviewed the latest full commit SHA and posted substantive feedback on the PR.**
Codex chooses the reviewer, addresses blocking findings and verifies required checks.
Codex self-review, Codex subagents and Codex Cloud alone do not satisfy this rule.
If neither Claude nor Bob is available, leave the PR open. This includes work Codex
delegates or integrates and documentation-only changes. See the
[external-review rule](docs/AGENT_HANDOFF.md#external-review-before-codex-merges-its-own-work).

The owner authorized Codex to push and merge routine project changes once tests and
required checks pass, the external-review rule is satisfied and blocking findings are
addressed. Existing repository
protections still apply. Every push and merge must leave a visible Claude handoff
using the shared guide. Include relevant fixes, security findings, improvements,
verification evidence and compatibility risks; say explicitly when none are known.

Keep changes focused and preserve established behavior through appropriate
regression checks. Coordinate edits to shared modules in the PR before starting
overlapping work. Follow the [named-writer and batching rules](docs/AGENT_HANDOFF.md#branch-ownership-local-checks-and-review-batches):
parallel writers use separate branches/worktrees; reviewers do not commit to another
writer's tree. The project remains paper-only under its existing scope.

A third agent, Bob, does large runs, data checks, tests and monitoring from written task
files. Its rules are in the "Three agents" section of the guide, in force since PR #16
merged with Codex's and Bob's agreement (see
`docs/reviews/2026-09-25-codex-pr16-final-review.md`).
