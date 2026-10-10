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
was started at that unchanged revision; its result must be recorded before claiming
full-suite success. Later integration additions require their own focused checks.

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

Full market replay, baseline adapters, exact data/config/code
registration and external full-head review are still delivery obligations. None of
these synthetic results demonstrate improved returns. Historical execution requires
the separately authorized registered run; reserved 2025+ data and live trading
remain prohibited.

The separate intrabar proposal in this branch is pending an owner decision. It
does not amend the approved specification or silently change acceptance metrics.
