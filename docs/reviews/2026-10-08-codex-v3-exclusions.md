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

## Review correction

Bob identified malformed execution-hour timestamps being mistaken for unavailable
closes. Preflight now rejects booleans, negative, off-hour and reserved-window
stamps as input errors before close selection. The regression first failed with
UnavailableClose; all 29 exclusion/runner/pending tests now pass, with Ruff/mypy.

Dependency evidence: pending.py at f56cee1c95f258abd38c579f86c1e92f7db11cae defines
advance(hour_ms, new_targets, tradable, exit_reasons=None) and stores immutable
exit reasons on PendingDecision. That lifecycle commit is an ancestor of this
branch, and the runner cancellation/delayed-fill regression exercises that actual
interface. Replacing reasons with excluded_month is intentional because it is the
first priority exit reason. The future dispatcher must catch UnavailableClose
separately from input errors; dispatcher implementation is still outstanding.

Cloud run-end finding reproduced: an excluded month beginning exactly at the
exclusive run end incorrectly demanded a prior-day closing hour. Preflight now
requires the excluded month's boundary strictly inside the run. Thirty exclusion/
runner/pending tests and Ruff pass. This is only the preflight correction: the
replay adapter and daily decision calendar still need run-end scoping so they do
not force a post-run exclusion close. Do not merge this partial fix alone.
