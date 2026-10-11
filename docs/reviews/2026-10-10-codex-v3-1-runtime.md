# Codex: V3.1 account, execution and evidence integration

Index: Combined-system runtime engineering after PR268: shared account, strategy geometry, conservative execution and protection, event kernel, acceptance, reporting, offline dashboard and preserved evidence. Synthetic verification only; historical strategy replay and registration remain incomplete.

This package makes the reviewed combined strategy measurable without changing any
frozen V0–V3 implementation. All runtime additions are under `combined/`; there is
no exchange connection, historical launcher or new dependency.

## Scope

- Exact shared-wallet spot and futures accounting, FIFO lots, partial reductions,
  funding, collateral and idempotent event identity. Already executed adverse
  fills are booked honestly, then flagged for reduction.
- Separate component geometry for spot/futures trends and equal-risk grid levels.
  Fixed arm switches implement the registered component comparisons and ablations;
  mandatory accounting and liquidation safeguards have no disable switch.
- Decision coordination records the sourced entry funnel and proves spot minimum
  infeasibility before futures fallback. Candidate venue quotes/filters are separate
  from held-position marks/filters, preventing cross-venue revaluation or false dust.
  Three grid child instructions fit inside one aggregate reservation; invalid or
  undersized children refuse the entire basket rather than changing the preset.
- Conservative order execution, venue filters, adverse gap/stop handling and
  completed-bar trailing protection. Protective obligations survive missing prices
  and partial fills; tightening never widens a stop or creates an execution.
- One serialized account/reservation/recovery kernel with funding before exits,
  reductions before increases, and checks before and after each event. Shared
  futures backing excludes spot inventory. Automatic recovery has an explicit
  disabled control while mandatory shutdown remains active.
- Fixed-matrix acceptance retains failures, incomplete cells and repeated attempts;
  every matched baseline is compared at both cost profiles. Missing evidence cannot
  silently reduce the required matrix or erase known drawdown/accounting failures.
- Read-only attribution and an offline HTML/SVG dashboard. Open marked positions
  are explicit. Missing MFE/giveback remain unknown; recovery endpoint changes are
  not claims of causal benefit. Inconsistent timestamps or recovery equity evidence
  prevent complete reporting.
- Exclusive evidence bundles, receipt/file/journal hashes and strict validation.
  Partial writes remain on disk; existing invocation directories are never reused.
  Hashes establish integrity relative to an independently retained receipt digest,
  not authenticity, write-once storage or protection from a hostile concurrent OS.
- A finite settled-event adapter preserves prior snapshots and terminal wallet
  state on failure. It is not the full OHLC strategy replay or experiment launcher.
- Pure lifecycle management cancels increases independently of entry admission;
  unverified range requests grid closure, while missing trend evidence cannot
  manufacture a reversal. Close requests are obligations, never fictional fills.

## Validation and limits

At integrated revision `7e7a722`, the focused preflight passed 351 synthetic tests,
repository-wide lint/format, mypy, Bandit and report checks. A separate full suite
at that unchanged revision subsequently passed 2,928 tests, with eight skips and
1,595 subtests, in 802 seconds. This is not current-head CI. Later integration
additions require their own focused checks and required full-suite CI.

Regressions cover real review findings: narrow Decimal contexts, duplicate events,
pre-exit liquidation, recovery with dust, stop preservation across partial entries,
out-of-window contributions and contradictory recovery endpoints. The dashboard's
automated escaping/offline tests pass; visual inspection remains separately tracked.

The final integrated focused preflight at `1a76f7a` passes 456 tests with one
native-symlink privilege skip. The Windows junction test passes. Lint, format,
mypy, Bandit and report checks pass. Browser tooling could not produce screenshots,
so visual verification is explicitly unfinished. Read-only local critics also
checked bundle integrity and replay failure preservation; malformed reached rows
now retain the successful prefix and safe unavailable identity labels.

The fresh whole-package critic then reproduced three important integration defects:
automatic close obligations left pending increases active; entry coordination could
trust stale assessment source timestamps; and malformed symbol types could bypass
settlement integrity shutdown and replay failure preservation. Regressions reproduced
each before fixes. Automatic stale/margin/post-fill protection now cancels portfolio
increases while retaining late-fill identities; entry checks completed source
boundaries; malformed account fields normalize to validation failures and replay
retains the booked terminal wallet. At `e1470ca`, 482 focused tests pass with one
OS permission skip, plus all static/report checks. A fresh review of this batch and
external latest-full-head review remain required before merge.

Full market replay, baseline adapters, exact data/config/code
registration and external full-head review are still delivery obligations. None of
these synthetic results demonstrate improved returns. Historical execution requires
the separately authorized registered run; reserved 2025+ data and live trading
remain prohibited.

The subsequent GitHub review also identified understated grid stop tick costs,
known failures hidden by an incomplete registration, and omitted mandatory report
metrics. The revised allocator includes adverse sell tick rounding in stop costs
and refuses insufficient bounds. Acceptance retains uniquely attributable safety
failures alongside registration errors without permitting incomplete comparisons.
Reports now include CAGR, return/drawdown, daily Sharpe and time-weighted committed
capital utilization, each with its definition and unavailable reason. Explicit
opening-time, daily sampling and utilization evidence is required; arbitrary event
marks and turnover cannot substitute for those inputs. Missing mandatory metrics
prevent a complete report even when its narrower structural checks pass.

Existing report callers must supply the new sampling evidence before claiming
metric completeness. This is an intentional compatibility change, not a strategy
or acceptance-threshold change. Grid stop-reference bounds do not guarantee a
maximum loss through an adverse gap; actual worse fills must still be booked.

Adjacent-risk inspection then reproduced the same tick omission in trend admission
and held-position reserves: entry100, stop98 and tick10 admitted20 units with40
reserved loss although the executable stop90 implied200. Intent now requires an
explicit tick verified against candidate venue rules. Planned entry, stop, fees,
cash and held exit reserves use adverse tick rounding; the example now admits5
units with50 planned risk. Actual fills remain booked and worse-than-admitted
entries request protection. At `70eab91`, 534 focused tests pass with one OS skip,
plus static/report checks; a separate critic passed138 risk/engine/allocation/
decision tests. This does not replace current-head external review and CI.

The next Cloud review found a canceled admission could surrender ownership before
its remaining fills were reconciled. Canceled nonzero remainders now quarantine the
asset against replacement entries, including the same strategy or opposite side.
Explicit `acknowledge_finality` requires immutable source references and attests all
fills reconciled with zero remaining executable quantity; a cancel request or ack
alone is insufficient. Original admission/remainder provenance remains retained.
A contradictory later novel fill fails integrity rather than being ignored; the
terminal wallet is the booked prefix, not a valid reconciliation of that contradictory
execution. Replay adapters must preserve the supplied failed batch as evidence.
Duplicate booked fills remain idempotent. Post-fill breach reasons are no longer
duplicated in settlement snapshots. Five new regression cases reproduced failure
before the fix; 539 focused tests and static/report checks pass, with one OS skip.
The delegated writer was interrupted by a usage limit; Codex Desktop recovered its
saved tests and completed the implementation. New external review and CI are needed.

The separate intrabar proposal in this branch is pending an owner decision. It
does not amend the approved specification or silently change acceptance metrics.

The all-inline review sweep found three further evidence blockers. Acceptance now
requires an explicitly attributed ReportEvidence for the same attempt and identity,
recomputes the report from retained inputs, and matches the registered observation
window, capital, return, drawdown and residual. A caller-set complete flag or forged
summary is insufficient. Every required metric must be available; only the already
approved explained residual at or below 1e-18 may remain a report issue. Observed
safety failures survive missing report evidence. Base and doubled execution-cost
profile pins must differ; the registration layer must still verify their contents.

Every equity, contribution, opportunity, recovery, daily-sample and utilization
record now preserves its own stable identity and immutable source references.
Missing provenance prevents structural completeness; duplicate identities/references
are rejected. Daily samples must be exact retained equity records, including their
identity and sources. Grouped opportunities retain all contributing identities.
The offline dashboard exposes safe, escaped per-record source links. References
and caller-attributed run identities are not independently authenticated here;
exact registration and artifact verification remain mandatory later integration.
Existing callers without provenance remain readable but incomplete.

The integrated batch passes 568 focused tests with one OS skip, plus repository-wide
Ruff, format, mypy, Bandit and report checks. A separate critic independently passed
71 acceptance and 56 report/dashboard tests and identified the daily-identity gap
before its fix. Browser visual QA remains unavailable because both UI tool entry
points fail kernel initialization. No historical execution was performed.
Execution-finality acknowledgement wiring and artifact retention of that evidence
remain obligations of the unfinished full replay adapter; until then canceled
remainders intentionally block replacement entries.

Bob's next review (19ace5f) and Cloud recovery review found three implementation
issues and one unresolved observation-policy gap. Wallet/quantity verification is
now tri-state: None means not checked and incomplete, False means a demonstrated
mismatch and failure, True means verified exact. Observed liquidation/drawdown
failures still survive missing evidence. Terminal profitability requires a valid
complete report; an unverified terminal amount cannot establish a profit verdict.
Registration now refuses a terminal event at the reserved-data boundary, matching
the current engine's supported timestamp range. This does not authorize a shortened
replacement trial or reserved-data access.

Recovery flatness now includes canceled, nonzero remainders awaiting finality.
Closing cannot enter cooldown merely because the currently held quantity was sold;
finality starts the full cooldown. Fully settled late remainders need no separate
cancel acknowledgement, while verified dust retains ownership. Three RED recovery
cases passed after the correction. Integrated preflight:580 passed,1 OS skip, all
static/report checks passed; independent critic80 acceptance and47 engine tests pass.

Bob's same-time observation concern remains OPEN, not dismissed or fixed by those
checks. Several funding/fill balances at one timestamp cannot establish the intended
daily or utilization boundary by ID alone. The pending intrabar proposal now states
proposed interior/opening/terminal/utilization phases, preserving all event marks
for drawdown. Owner approval, reviewed phase-policy registration binding and adapter
implementation are required before ambiguous reports can be complete. PR269 must
not be treated as clear of this blocker merely because other fixes pass tests.

## Fill identity and capital-observation review corrections

The integrated follow-up binds duplicate fills to their original execution role,
admission key and full event. Contradictory repeats latch integrity failure while
preserving the booked prefix. Opportunities outside the retained equity window
remain visible but make the report incomplete. Utilization intervals now reference
retained capital observations with exact equity-record identity and capital values;
an interval cannot skip an intervening capital observation. Acceptance recomputation
retains these observations, and the dashboard exposes their source links.

Verification: 612 combined tests passed, one OS skip; repository static and report
checks passed. Independent critics ran 54 engine and 81 report/dashboard tests.
These are structural consistency checks, not source authentication. Same-time
observation ambiguity remains unavailable pending the owner's phase-policy decision.
No historical execution occurred; the OHLC adapter, baseline adapters, visual QA
and exact registration remain unfinished. This adds mandatory report evidence for
complete utilization and stricter duplicate-fill handling; callers must supply the
new links. No additional security finding is known beyond the evidence defects fixed.

## Retained-history integrity corrections

The next report review found that recovered positive balances could hide a zero or
negative intermediate equity observation. Every such observation now makes evidence
structurally incomplete. Utilization must split at every retained equity or capital
observation; an omitted capital record cannot justify a stale denominator.
Unknown opportunity stages, impossible local stage order and exit reasons on open
lifecycles remain in the archive but invalidate completeness. Sparse episode
summaries permit repeated detections and partial fills; they do not prove a complete
six-stage DecisionEvent journal, now explicitly stated in the dashboard.

Verification: 629 combined tests passed, one OS skip, with repository static and
report checks passing. The independent critic passed 96 report/dashboard tests.
Two acceptance regressions reproduced hidden zero/negative capital exhaustion before
the fix and pass afterward. Existing acceptance fixtures now provide each retained
observation's capital evidence. No strategy or sampling policy changed, no historical
execution occurred, and the owner observation-policy decision remains outstanding.

## Terminal identity, recovery sequence and attributable failures

Terminal completeness now requires one sourced equity observation and one matching
phase-qualified capital observation; equal equity values do not collapse distinct
terminal phases. Recovery records must be chronological and non-overlapping; open
episodes prevent a following episode. Invalid records remain visible.

Registration rejects windows unable to support the existing mandatory UTC-daily
metrics (day-aligned endpoints, at least two days). This does not select the pending
same-time convention. Acceptance separately recomputes identity-, attempt-, window-
and registered-capital-matched reports to retain observed drawdown, exhaustion and
accounting breaches despite contradictory wrapper scalars. A wrong-capital scalar
wrapper is incomplete, not attributed to another capital scenario; a correct-capital
report still preserves its breach. Duplicate umbrella failure messages are removed.

Verification:686 combined tests passed,one OS skip; repository static/report checks
passed. Independent critic108report/dashboard tests,123experiment tests plus16 final
wrapper cases passed; writer127experiment tests passed. No historical execution or
sampling-policy choice. Source authentication remains outside these structural
checks. The owner policy decision, final full-head external review, replay adapters,
visual QA and exact registration remain required before the historical-run gate.
