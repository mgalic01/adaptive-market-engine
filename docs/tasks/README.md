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
| [Outage calendar and field-level mismatches](2026-09-26-bob-outage-calendar.md) | **Owner's go; runs when merged.** Hours missing from both archives (the real outages), grouped into events, and which fields differ in each mismatch. Follows PR #60. |
| [Refined parser rule](2026-09-26-bob-refined-parser-rule.md) | **Owner's go; runs when merged.** Bob's refined rule from PR #59, with an aligned open, continuity and a strict hour check, measured on every file of the 14 months. |
| [Hour-level defect calendar, 2017-08 to 2024-12](2026-09-26-bob-hourly-defect-calendar.md) | **Done:** run 36221539727; report merged in PR #60, rechecked by Claude. |
| [Parser anomaly classes](2026-09-26-bob-parser-anomaly-classes.md) | **Done:** run 36221539727; report merged in PR #59, rechecked by Claude. |
| [Development data inventory, 2017-08 to 2024-12](2026-09-25-bob-dev-data-inventory.md) | **Done:** run 36203721612; report merged in PR #49, rechecked by Claude. |
| [V0 development scorecard (C1–C6, R1)](2026-09-25-bob-v0-dev-scorecard.md) | **Done:** run 36203721612; report merged in PR #52, rechecked by Claude. |
| [Test-suite audit](2026-09-25-bob-test-suite-audit.md) | **Done:** run 36203721612; report merged in PR #51, rechecked by Claude. |
| [Documentation audit](2026-09-25-bob-docs-audit.md) | **Done:** run 36203721612; report merged in PR #50, rechecked by Claude. |
| [V0 trace-hash cross-check](2026-09-25-bob-v0-trace-hash-crosscheck.md) | **Done:** 40/40 hashes and fill counts match ([report](../reviews/2026-09-25-bob-v0-trace-crosscheck.md), PR #40). |
| [V0 equivalence re-run](2026-09-24-bob-v0-equivalence.md) | Approved at `99996bc`. Bob: inputs and 40 baseline traces on Windows; **completed by Claude on Linux**: 40/40 identical ([results](../reviews/2026-09-25-claude-v0-equivalence-results.md)) |
| [P8 data survey (G, H)](2026-09-24-bob-p8-data-survey.md) | Approved at `99996bc`; **done**. The report stays on branch `bob/p8-data-survey` (`761b2ee`) and was never merged to `main` (found by Bob's documentation audit, PR #50). |
| [Funding cadence, all months (G)](2026-09-25-bob-funding-cadence.md) | **Done** by Bob: PR #19 (`fe60ec4`), exact 8-hour cadence in all 60 months |
