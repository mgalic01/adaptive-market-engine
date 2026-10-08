# V3 daily signal-to-target integration

Index: Continuous spot signal history and closed-day volatility sizing produce
eligible daily futures targets, with missing-bar behavior and exit provenance.

Purpose: connect the frozen strategy signals and risk sizing to the hourly runner.
Named writer: Codex Desktop. Stacked on exclusions (#223), not for merge into it.

DailyDecisions computes each coin's signal history once and its one-day returns
from supplied, already-masked spot bars. Each decision reads only bars up to the
previous UTC day and return observations up to that day. Queries are independent
of account state, so fresh training windows and quarterly picks share continuous
signal state without resetting it or reading future prices.

Portfolio membership starts at the manifest-supplied first month. Exclusions set
raw sizing weight to zero, including the mandatory pre-exclusion closing day.
A missing spot bar retains the signal but emits no ordinary target, preserving
any pending order. Mandatory exclusions override that absence. An all-invalid
quarter emits zero targets for every eligible coin, attributed to pick_change on
every day, so a deferred close retains its cause when the daily target is replaced.

Targets and exit reasons feed TrendRunner.step directly. Signal-zero, sizing,
exclusion and pick-change provenance is supplied here; execution still determines
flips, rounding and minimum-quantity outcomes. The caller states whether the pick
changed. No trading arithmetic or strategy parameters are altered.

Validation: six decision tests and 73 total decision/signal/sizing/runner/exclusion
tests pass, with Ruff and mypy. Synthetic checks cover future-history independence,
missing bars, membership, all-invalid flat periods, exit reasons, exclusions and
an actual next-hour runner fill. Full CI and external review are pending.

Input boundary: the manifest adapter must verify source checksums, spot masks,
portfolio start months and exclusion calendar. It is not implemented by this class.
Historical dispatcher, continuous OOS orchestration and completion registration
remain unfinished. No market data fetch or historical replay occurred. No new
dependency or known security finding. Return targets remain unproven.
