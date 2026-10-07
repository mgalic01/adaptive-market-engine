# Task files for Bob

Written by Claude or Codex under [the three-agent rules](../AGENT_HANDOFF.md#three-agents-claude-codex-and-bob).
A task starts only after the named review (normally a **Codex → Bob handoff** comment
approving it) or the owner's go. Bob reports in `docs/reviews/YYYY-MM-DD-bob-<topic>.md`.

**Running a task on GitHub:** Bob starts **automatically when a PR that adds a new task
file is merged into `main`**, so a task PR is merged only after review. To run a task
again, or one merged before automation existed, the owner comments
`/bob-run docs/tasks/<file>.md <full commit SHA>` on any issue or PR, or uses "Run
workflow" on **IBM Bob task run** in the Actions tab with the task path and that SHA.
The SHA is a commit `main` has been at; Bob runs the task as it is in that commit (for
an automatic run, the merge commit), not as `main` is when the run starts. Bob runs on
a Linux machine, and the report arrives as a PR ([rules](../AGENT_HANDOFF.md)).

| Task | Status |
| --- | --- |
| [Structure-aware features backtest comparison](2026-09-29-bob-structure-backtest-comparison.md) | **Done:** task file merged in PR #149; report in [`docs/reviews/2026-09-30-bob-v2-backtest-comparison.md`](../reviews/2026-09-30-bob-v2-backtest-comparison.md). Critical finding F1 (structure_alignment silently zeroed) fixed in PR #154. |
| [P8 archives for G and H, development months only](2026-09-27-bob-p8-funding-archives.md) | **Done:** run 36560170480; [report](../reviews/2026-09-27-bob-p8-funding-archives.md) merged in PR #164 (closing #133). Not to be rerun: its pins describe that run, and a new fetch needs a new task file. The manifest entries it proposes are added separately, in a reviewed code PR. |
| [Combined defect census, 2017-08 to 2024-12](2026-09-27-bob-combined-defect-census.md) | **Queued:** starts when merged (owner's go 2026-09-27). Re-runs the hourly calendar on expected hours with the per-hour exchange-wide rule, so the 14 outages merge into the event census ([why](../reviews/2026-09-27-claude-defect-calendar-corrections.md)). |
| [Masked fraction of the rescued months](2026-09-27-bob-rescued-month-masking.md) | **Queued:** starts when merged (owner's go 2026-09-27). Measures the 98 months the refined repair rule rescues, which the proposed 2% cap has not seen. |
| [Outage calendar and field-level mismatches](2026-09-26-bob-outage-calendar.md) | **Done:** [report](../reviews/2026-09-26-bob-outage-calendar.md) merged in PR #66, independently rechecked by Claude. Counts cover parsed pair-months; outage-policy adoption remains separate. |
| [Refined parser rule](2026-09-26-bob-refined-parser-rule.md) | **Done:** [report](../reviews/2026-09-26-bob-refined-parser-rule.md) merged in PR #65, independently rechecked by Claude. Repair eligibility was measured; parser/tolerance adoption and full replay validity remain separate. |
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
