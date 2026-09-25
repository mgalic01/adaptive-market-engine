# Task files for Bob

Written by Claude or Codex under [the three-agent rules](../AGENT_HANDOFF.md#three-agents-claude-codex-and-bob).
A task starts only after the named review (normally a **Codex → Bob handoff** comment
approving it) or the owner's go. Bob reports in `docs/reviews/YYYY-MM-DD-bob-<topic>.md`.

**Running a task on GitHub:** Bob starts **automatically when a PR that adds a new task
file is merged into `main`**, so a task PR is merged only after review. To run a task
again, or one merged before automation existed, the owner comments
`/bob-run docs/tasks/<file>.md` on any issue or PR, or uses "Run workflow" on
**IBM Bob task run** in the Actions tab. Bob runs on a Linux machine, and the report
arrives as a PR ([rules](../AGENT_HANDOFF.md)).

| Task | Status |
| --- | --- |
| [V0 trace-hash cross-check](2026-09-25-bob-v0-trace-hash-crosscheck.md) | **Awaiting Codex approval or the owner's go.** Bob publishes his 40 Windows baseline trace hashes against Claude's table. |
| [V0 equivalence re-run](2026-09-24-bob-v0-equivalence.md) | Approved at `99996bc`. Bob: inputs and 40 baseline traces on Windows; **completed by Claude on Linux**: 40/40 identical ([results](../reviews/2026-09-25-claude-v0-equivalence-results.md)) |
| [P8 data survey (G, H)](2026-09-24-bob-p8-data-survey.md) | Approved at `99996bc`; **done** — report on `bob/p8-data-survey` (`761b2ee`) |
| [Funding cadence, all months (G)](2026-09-25-bob-funding-cadence.md) | **Done** by Bob: PR #19 (`fe60ec4`), exact 8-hour cadence in all 60 months |
