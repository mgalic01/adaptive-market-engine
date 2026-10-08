# V3 exclusion targets and closing-hour preflight

Index: Mandatory zero targets cancel deferred entries before excluded months;
preflight lists closing hours and rejects unavailable closes on synthetic masks.

Purpose: avoid carrying positions into data months the frozen experiment excludes.
Named writer: Codex Desktop. Stacked on the approved audit amendment (#221).

The calendar copies and validates declared excluded months. At midnight on the
previous month's last day, and throughout each excluded month, it forces target
zero and the excluded-month exit reason. This overrides a missing signal bar and
replaces any deferred entry. The existing pending-order engine waits until the
first unmasked hour from 01:00, preserving normal fills and costs.

The close-availability preflight accepts a fresh flat run's daily boundaries and
validated execution-hour inventory. It returns each required close's symbol,
excluded month, decision time and first unmasked fill hour. No usable hour raises
UnavailableClose carrying the full evidence list; missing inventory is an input
error. The historical dispatcher must distinguish these outcomes.

Interpretation for review: a fresh flat run starting inside an exclusion has no
prior position to close; consecutive excluded months create no new close because
targets remain zero. The caller restricts exclusions to portfolio eligibility.
This implements the spec's open-position closing obligation without inventing
trades for already-flat periods.

Validation: 28 exclusion/runner/pending tests pass, including deferred entry
cancellation, missing signal-day override, delayed fill and lifecycle exit reason,
missing close, missing inventory and invalid daily bounds. Ruff and mypy pass.
Full CI and external review required; no market data or replay was used.

Remaining integration: the validated manifest adapter must call this preflight
before creating historical runs, supply the same masks to hourly execution, and
record all unavailable-close cases. The constructor alone does not certify masks.
This PR does not implement that adapter or authorize a historical run. Continuous
signal/sizing linkage, walk-forward orchestration and reporting remain unfinished.
No new dependency or known security finding; no frozen parameter changes.
