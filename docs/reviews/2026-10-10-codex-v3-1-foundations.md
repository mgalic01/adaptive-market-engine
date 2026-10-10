# Codex: V3.1 assessment and portfolio foundations

Index: First runtime package for the reviewed combined specification: causal assessment/correlation, routing and flow qualification, immutable decision evidence, shared reservations and pure recovery. Synthetic verification only; account/execution/strategy integration remains next.

This package serves the approved combined strategy by preventing stale or conflicting
signals, duplicate exposure and recovery resets before orders reach execution.
Frozen V0-V3 modules and historical runs are unchanged. The specification merged in
PR266; this implements foundations, not a runnable experiment or a profitability claim.

## Implemented and verified

- Completed daily/4h assessment with prior-band exclusion, volatility/extension,
  explicit missing/warmup states and causal gap metadata. Future malformed numeric
  bars cannot poison earlier assessments.
- Deterministic routing, spot preference with explicit executability fallback,
  affirmative bearish qualification and exact ablations. Grid flow uses fifteen
  contiguous completed minutes, volume weighting and 0.40/0.45 hysteresis.
- Sixty common completed daily-return correlation groups, exact absolute Pearson
  threshold and conservative union for unknown relations; future suffix excluded.
- Immutable decision funnel with duplicate/conflicting IDs and hash-linked export.
- Serialized portfolio reservation with shared cash, pending exposure, asset/group
  and portfolio caps, funding/cadence and margin checks. Separate adverse entry and
  stop-exit costs are reserved; notional caps use conservative execution bounds.
- Recovery tracks lifetime and episode peaks separately, requires liquidation before
  cooldown, restarts at quarter risk, and cannot reset the lifetime acceptance loss.

Local critic reviews found future-invalid-data poisoning, missing gap metadata,
understated short exit costs, missing exit cash reserves, slippage notional bounds,
and malformed routing flags/measurements. Regression tests reproduced these before
fixes. Synthetic verification: 106 focused tests pass, plus repository-wide lint,
formatting, mypy, Bandit and check_reports (0 problems). The initial preflight stopped
on an import-order lint issue; it was corrected before the successful preflight.
Command: python -B scripts/preflight.py --tests tests/test_combined_assessment.py
 tests/test_combined_evidence.py tests/test_combined_recovery.py
 tests/test_combined_risk.py tests/test_combined_correlation.py tests/test_combined_routing.py.
Full-suite CI and external full-head review remain required; local focused success
is not a full-suite pass. An older isolated risk-branch full-suite run is incomplete.

Integration follow-up: the admission maintenance default is corrected to 1% of
gross, matching the frozen V3 liquidation model, rather than 0.5%. A new regression
failed before this correction and passes after it; the focused total is now107.
This corrects implementation against the pinned model before execution, not tuning.

The subsequent review batch makes future timestamp defects causal, requires
nonempty source references in every decision record, and compares funding against
cost-inclusive stop risk. Shared futures backing now bounds both entry maintenance
and stressed-stop maintenance, including held and pending positions. Spot spending
must preserve those same buffers: admission order cannot let spot consume cash
already supporting futures. This uses the existing cross-margin model, not an
assumed isolated-margin liquidation price. The integrating account must supply
free cash plus futures collateral and marked P&L as backing, excluding spot assets.
The conservative fallback counts free cash only.

The six-file focused preflight above now passes 133 tests, repository-wide lint,
format, types, security and report checks. This remains synthetic engineering
evidence, not a historical result. The older isolated full-suite run had one
Windows shell-resolution failure; that test passes with Git Bash on PATH, but
this is not claimed as a successful full-suite rerun.

## Integration obligations and limits

The engine must provide the same authoritative account/correlation snapshot under
its event lock, transfer partial fills from reservations to holdings atomically,
and deduplicate submitted order IDs. A reservation result is not an order. Routing
is not portfolio approval. The recovery controller's tradable_flat flag must come
from acknowledged reductions and verified filters/prices; it cannot invent dust.
The evidence serializer is in-memory only; durable writes and report consumption
are a later package. Funding cash events, the shared account, stop execution,
three strategy components and the dashboard are not implemented by this PR.

No new dependency, network runtime, historical execution, parameter search,
reserved-data access or live orders. Known compatibility risk: none to frozen
engines; these new interfaces are not integrated yet. Historical authorization
remains separately gated on exact reviewed registration and owner go.
