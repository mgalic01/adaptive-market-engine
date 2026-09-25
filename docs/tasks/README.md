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
| [Development data inventory, 2017-08 to 2024-12](2026-09-25-bob-dev-data-inventory.md) | **Owner's go (2026-09-25: "give bob as much grunt work as you possibly can"); runs when merged.** Every pair and month of the ten-pair basket: hash-checked, parsed, 1m against 1h, first clean month per pair. |
| [V0 development scorecard (C1–C6, R1)](2026-09-25-bob-v0-dev-scorecard.md) | **Owner's go; runs when merged.** V0's criteria computed by hand on both development windows; a diagnostic, not a selection. |
| [Test-suite audit](2026-09-25-bob-test-suite-audit.md) | **Owner's go; runs when merged.** Isolation, order, hash seeds, warnings, flakiness, untested public code. |
| [Documentation audit](2026-09-25-bob-docs-audit.md) | **Owner's go; runs when merged.** Links, anchors, indexes, stale statements, rules against workflows. |
| [V0 trace-hash cross-check](2026-09-25-bob-v0-trace-hash-crosscheck.md) | **Done:** 40/40 hashes and fill counts match ([report](../reviews/2026-09-25-bob-v0-trace-crosscheck.md), PR #40). |
| [V0 equivalence re-run](2026-09-24-bob-v0-equivalence.md) | Approved at `99996bc`. Bob: inputs and 40 baseline traces on Windows; **completed by Claude on Linux**: 40/40 identical ([results](../reviews/2026-09-25-claude-v0-equivalence-results.md)) |
| [P8 data survey (G, H)](2026-09-24-bob-p8-data-survey.md) | Approved at `99996bc`; **done** — report on `bob/p8-data-survey` (`761b2ee`) |
| [Funding cadence, all months (G)](2026-09-25-bob-funding-cadence.md) | **Done** by Bob: PR #19 (`fe60ec4`), exact 8-hour cadence in all 60 months |
