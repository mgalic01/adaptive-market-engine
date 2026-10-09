# Owner decision: local V3 data collector

Index: Owner approved Codex Desktop as the local E: collector with Bob review; final reviewed download start remains separate.

On 2026-10-09 the owner answered "ok do it" after Codex presented the recommended
executor exception from PR #250 and an approval option explicitly limited to that
exception, not starting the download. Codex accepts this as approval to implement
the recommended local-executor change and continue preparation.

For this one V3 historical collection task, Codex Desktop may run the reviewed,
pinned collector locally under `E:/adaptive-market-engine/v3`. Bob independently
reviews the task and the delivered manifest/coverage. A local Bob installation or
a transfer from a temporary GitHub runner is therefore unnecessary.

The disclosed downside remains: Codex prepares and executes the collector, reducing
separation of implementation and execution. Independent Bob review and retained
byte hashes provide an audit trail but do not eliminate that loss of independence.

All original restrictions remain: owner start of the final reviewed task, a pinned
collector and inputs, public development archives through 2024-12 only, the narrow
one-time filter endpoint exception, retained raw responses, no credentials/orders,
fresh attempt directories, failure evidence, and no automatic retry or replacement
snapshots. No archive request or historical replay is authorized by this record.

Version the frozen spec and append a successor candidate registration before
execution. This changes the executor only, not the twelve rules, sizing, funding,
fees, folds, seed, budget, A1-A5 or the sealed reserved window. The final reviewed
download task will be presented to the owner for its separate start.
