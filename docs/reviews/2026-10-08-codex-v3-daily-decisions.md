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

Cloud performance follow-up: daily sizing now receives at most the last 60 return
observations. These include every available return in the last 60 calendar days,
because each coin has at most one return per day. A sparse 300-day regression first
failed with 264 rows, then passed with 60 and identical full-history SizingResult.
All 37 decision/sizing tests, Ruff and mypy pass. No strategy formula changes.
Other review concerns (deferred pick-change attribution, all-invalid/no-bar
interpretation and excluded-signal reporting) remain open; not merge-ready.

Excluded-signal reporting fix: the recorded effective signal is now zero before
sizing for a forced exclusion. The regression first reproduced the stale +1 signal,
then passed. Candidate exit reasons are explicitly documented as inputs to the
lifecycle ledger's single priority-selected final reason. All 50 decision/sizing/
lifecycle tests, Ruff and mypy pass. Signal-series state itself remains continuous.
Deferred pick attribution and the all-invalid missing-bar interpretation remain
open; this does not claim those review concerns are resolved.

Deferred zero-target close attribution: replacing a pending zero target with another
zero target now retains its initiating pick_change candidate. Dispatch consumes it;
a nonzero replacement cancels that closing intention and does not inherit the cause.
Regression reproduced lost attribution before the fix; all 32 pending/runner/decision
tests, Ruff and mypy pass. This covers explicit zero-target closes, not a nonzero
replacement that eventually rounds or reduces to zero; that broader case still needs
review. All-invalid/no-bar specification interpretation also remains open.

Deferred attribution completion supersedes the earlier zero-only restriction:
pick_change now survives every still-pending replacement until the first execution
attempt. A nonzero target can round to zero or undergo minimum-quantity enlargement,
so clearing the cause merely on a nonzero replacement was incorrect. Three signed/
tiny-target regressions reproduced the loss. A real 50-hour runner regression opens,
defers a pick close, replaces with a tiny nonzero target and verifies the eventual
rounding close records pick_change. All 35 pending/runner/decision tests pass;
Ruff and mypy pass. No target, execution time or accounting arithmetic changes.

Main integration after PR223: merged main 4459964ceba3fe8c6280ad0cf23f71288891ad84
and retargeted PR224 to main. Forty-three decision/pending/runner/exclusion tests
pass; check_reports reports zero problems (historical unverifiable entries remain
explicitly labeled). Bob's registration concern is resolved by direct Git evidence:
df78b799c6e0b9c414712dc9cce2c7bdfa25e158 is an ancestor, and its tree contains both
the spec amendment and owner record. SHA-256 of the raw spec blob at that commit is
bed8bc2ee71788549659d1679c75921f8727736e5e71b7084fc9834499173e88, exactly the register
pin. No registration change is needed. Fresh full-head review and CI required.
