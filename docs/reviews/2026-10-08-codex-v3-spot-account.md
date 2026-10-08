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
