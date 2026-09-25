# Repository collaboration instructions

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

A third agent, Bob, is proposed for large runs, data checks, tests and monitoring from
written task files. Its rules are in the "Three agents" section of the guide. They
apply only after Codex and Bob have both explicitly agreed on PR #16 and it has merged.
