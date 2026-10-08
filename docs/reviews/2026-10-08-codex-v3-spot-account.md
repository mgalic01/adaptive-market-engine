# V3 spot benchmark cash ledger

Index: Draft spot benchmark and A5 comparison; current validation and open work are recorded in the dated follow-ups below.

Stack dependency: PR228 is based on PR226 (codex/v3-wfo-orchestration), which
contains PR225 replay, PR224 daily decisions and PR223 exclusions. The full PR228
tree includes exclusions.py; it is not intended for independent cherry-picking
onto main. Merge only after dependency integration and fresh review.

Implements Decimal60 spot settlement with 10,000 initial cash, 0.10% fee and 0.05%
slippage, doubled together in cost stress. Buys clip to cash including fees and
floor to quantity step. Minimum notional applies to buys and sells; unsellable dust
stays marked. Overselling and oversized single orders are rejected before mutation;
the later runner must split orders above the maximum. No borrowing or funding.

Five tests cover hand-calculated round trips at base/double cost, cash clipping,
dust, atomic rejection and detection of corrupted cash/quantity. Ruff and mypy
pass. Fill records retain requested/executed quantities, slipped price, fee and skip
reason. Cash and quantity audits replay the journal exactly.

Remaining plan work: max-order splitting in benchmark execution, further precision
and filter-boundary tests, continuous risk-matched benchmark runner, comparison
metrics and durable serialization. This ledger alone does not implement A5. No
historical source, live execution, new dependency or known security change.

Spot execution follow-up: balanced child quantities respect the maximum while
preserving the stepped total; spot settlement still enforces cash and notional on
each child, stopping when cash clips or a child cannot execute. Overselling is
rejected before any child settles. Seven tests now pass, including 13 split into
5/4/4 and low ambient precision. Ruff and mypy pass. Benchmark runner and broader
input/resource limits remain pending; this draft is not merge-ready.

Daily decision follow-up: `HoldDecisions` uses constant +1 signals, m=1 frozen
volatility sizing, eligible months and bounded closed return history. Missing spot
bars suppress targets except mandatory exclusions; the exclusive run end suppresses
an exclusion beyond the experiment. Two tests cover falling prices, future-history
independence, missing bars and exclusion boundaries. Nine combined spot tests pass;
Ruff and mypy pass for the new decision module. The continuous execution runner,
benchmark metrics and durable evidence remain pending. No historical results or
merge readiness are claimed.

Hourly runner foundation: `SpotRunner` now consumes deferred daily targets,
computes all quantity changes from the same pre-fill equity, settles sells before
buys and records pre/post exact audits. It retains 01:00 pre-fill samples and the
frozen favourable-before-adverse drawdown path. Final supplied in-window closes
mark retained holdings without a terminal trade or fee. An exception permanently
stops the runner. Twelve synthetic spot tests pass, including masked deferral,
account corruption refusal, drawdown ordering and terminal valuation; Ruff and
mypy pass. Data-window adapter, complete decision/skip evidence, masked-held-hour
counts, multi-asset boundary coverage and reporting remain unfinished. Draft only;
the earlier full-suite result belongs to orchestration, not these new changes.

Window adapter follow-up: `replay_spot_benchmark` now runs one fresh account over
supplied masked hourly bars, respecting eligibility/excluded months and exclusive
run-end decisions. It validates aligned development-only inventory, rejects duplicate
hours and uses only in-window terminal closes. Tests compare independent base/double
cost accounts, verify sells precede buys in a two-coin rotation and retain missing
held-hour counts. Fifteen combined spot tests, Ruff and mypy pass. Historical source
validation, pre-exclusion unavailable-close versus retained-dust classification,
complete per-decision/skip evidence and durable reporting still need completion
before this draft can be considered for merge or historical dispatch.

Decision evidence follow-up: integrated the latest exclusion/orchestration repairs.
Immutable SpotRebalance records retain original decision/fill timestamps, target
and current weights, requested quantity change, journal slice and outcome reason.
Band skips and rounded-no-change outcomes are distinct; actual fills carry cash
clipping/minimum refusal reasons into the decision record. Sixteen spot tests pass;
63 combined spot/replay/orchestration/metrics tests pass excluding the separately
slow training-menu test. Ruff and mypy pass for the new module/tests. Durable
serialization, spot exclusion/dust classification and acceptance integration remain
pending; this is still a draft, with no historical performance or merge claim.

Spot exclusion classification: predeclared missing-close requirements are retained.
At the mandatory decision, a held sellable quantity makes the run invalid; the
account stops at prior in-window closes, audited, without an invented trade. A
quantity below minimum quantity or slipped minimum notional at its last usable
open is retained as dust, recording timestamp, symbol, quantity and that mark.
No unseen future price is inferred. Flat accounts continue. This carried-price
dust classification needs explicit external scrutiny against section 8; source
validation and complete evidence serialization remain unfinished.
Seventeen spot tests and 64 combined focused tests pass, plus Ruff/mypy. The new
regression covers sellable-invalid versus dust-retained outcomes from the same
missing-hour inventory. Draft only; no historical run or performance claim.

A5 comparison follow-up: benchmark_comparison.compare_hold requires completed,
audited base-cost accounts, strategy m=1, identical sample times and consistent
spot path endpoints. It uses the existing sample_returns/Sharpe calculation and
strict strategy Sharpe > hold Sharpe. Invalid runs raise for the enclosing verdict
report to classify; this helper never declares the whole experiment passed.
Four comparison tests cover ties, real spot fee drag, size/time mismatch and
corrupted/invalid spot accounts. Twenty-one combined comparison/spot tests pass;
Ruff and mypy pass. Durable reports, source provenance, full-size equal-weight
hold diagnostic and the complete A1-A5 report remain pending. No historical run.

Review response (Bob at 55c0d55): the unmasked 00:00 decision-bar case reproduced
stale dust classification and is fixed by using that available open; otherwise the
last usable open is carried. Regression covers price movements both into and out
of dust and asserts the stored dust mark is plain, not sell-slipped. Twenty-one
comparison/spot tests, Ruff and mypy pass. Bob concerns 2/3 misread the source:
slipped is used only for sellability, while exclusion_dust stores price. Concern 5
is handled by replay's every-hour range and the consecutive-step guard, not a
coincidence; normal terminal time is exactly the exclusive end. Early invalid
termination deliberately uses the prior processed-hour boundary. Dependency and
index clarity corrected above. This remains a draft pending full verification,
durable evidence and complete experiment reporting.

Integration follow-up (2026-10-09): integrated f8c28db (metrics, evidence writer and startup recovery validation) and replay formatting correction 831d8a2. Thirty-seven spot account/benchmark/comparison and journal/writer tests pass, as do full Ruff lint/format and mypy. The earlier full-suite result at c9b7d36 does not validate this new combined head; full integrated validation remains pending. No spot trading-rule change, new dependency or known security regression in the merge. Evidence writer findings still listed on PR 226 remain open.

Second integration batch (2026-10-09): includes PR226 46f4d2a daily/partial evidence, PR220 214b3cb sample completeness, and PR224 eb5aa15 missing-spot attribution. The decisions.py conflict was resolved by keeping both cause-only pick events and all-rule signal evidence. All 127 focused integration tests passed before the diagnostic follow-up below. Bandit B311 was reproduced on the frozen statistical random.Random seed; a line-specific nosec B311 with its non-security rationale preserves the required algorithm and passes Bandit. No security check is globally disabled.

Diagnostic follow-up from internal review: volatility is now measured for every coin with sufficient history even when its signal is zero or it is excluded. Unavailable volatility is null, distinguishable from an actually measured zero. All-invalid decisions also retain flat sizing diagnostics; targets remain zero. Four regression cases failed before correction; 87 focused sizing/decision/replay/evidence/spot/comparison checks now pass, with Ruff lint/format and mypy. Compatibility: SizingResult.volatility values may be null when fewer than 60 observations exist; serialized evidence must preserve that distinction. No active-weight formula or trading parameter changed. Full integrated CI and external review remain pending; no historical dispatch.

## 2026-10-09 benchmark sample integrity follow-up

Bob identified that A5 checked hold timestamps but not interior equity values.
The new regression changed only the second hold sample's equity and incorrectly
received a verdict before this fix. Both account types now call the shared
validate_sample_path routine, preserving complete 01:00/terminal coverage,
chronological order, matching values and initial-equity equality. Trade-level
reconciliation remains futures-specific. No sizing, execution or metric formula
changed. The metrics docstring clarifies that the equality guard prohibits any
omitted initial-to-first-sample gain or loss.

An actual published JSONL regression uses computed daily decisions to verify
unavailable ETH volatility is JSON null, measured BTC zero is an exact Decimal
string, and the all-invalid selected rule is null. This was existing serializer
behavior; no encoding change was necessary.

Validation: the forged-equity regression failed before the fix; 58 focused
comparison, metrics, writer, spot runner and spot ledger tests pass afterwards.
Ruff and mypy pass. Independent Codex reviewer found no actionable delta defects,
ran 41 focused tests and checked a legitimate 01:00 terminal. Full current-head
CI and Bob review remain required. No new dependencies or known security risks.
Compatibility: corrupted spot evidence now raises instead of producing A5.
Historical registration, spot artifact/reporting and recovery work remain open.

## 2026-10-09 final evidence integration

Merged metrics71d9422 and the current recovery/pick-schedule work from PR226.
Resolved the metrics conflict by retaining the shared validator and placing the
new terminal timestamp/kind guard inside it, protecting both strategy and hold.
Retained both independently added writer test groups in the test-only conflict.
82 focused metrics/comparison/spot/orchestration/journal/writer tests pass after
resolution; Ruff lint/format, mypy and Bandit pass. A final docs-only upstream
merge was followed by 47 metrics/comparison/writer checks, all passing.

No known behavior divergence from either reviewed component. New integrated head
still requires Bob review and full CI. Spot-specific durable artifact/report
work, full-size diagnostic hold and registration remain open; no historical run.

## 2026-10-09 durable spot evidence and failure records

Added write_spot_replay using the shared immutable, fsynced JSONL publisher.
Spot artifacts retain cash/holdings, fills, audits, rebalances, dispatches, dust,
actual daily decisions, equity and samples without converting Decimal values.
Added replay_spot_recorded: publishes start before replay, then artifact before
finish metadata; full or partial outcomes remain explicitly identified by stopped
reason and error. Completion of recording is not acceptance of a strategy.

Execution exceptions are chained SpotReplayExecutionError objects retaining the
partial runner; preflight exceptions keep their original types. KeyboardInterrupt
and publication failure leave a pending start and never trigger a retry. This is
an intentional exception-interface extension for replay_spot_benchmark callers.
Historical source/provenance and registration gates remain the caller's obligation.

Validation: eight new spot evidence scenarios, including actual JSON readback,
non-overwrite, real adapter decisions, execution failure, preflight error,
interruption and publication failure. 52 combined spot/evidence/comparison tests
pass; Ruff and mypy pass. Independent Codex reviewer ran45 focused tests and found
no actionable defects. Bob review/full CI pending. No dependencies, live data or
strategy changes. Acceptance reports, full-size diagnostic hold and registered
historical dispatch still remain incomplete.

Prior Bob comments on private intra-package helpers and overlapping validation
were explicitly non-blocking maintainability notes. These helpers are internal
implementation details covered by integration tests; no public API guarantee is
claimed. Extra spot initial-account checks additionally bind samples to the
actual account initial balance. No speculative renaming is included in this batch.

Integrated the upstream late-orphan detection regression without conflict.
53 combined spot/evidence/comparison checks now pass; Ruff lint/format, mypy and
Bandit pass on the combined tree. This includes detection of same-run evidence
appearing after a finish that declared no artifact.
