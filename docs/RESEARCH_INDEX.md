# Maintained research index

Updated 2026-10-10. Writer: Codex Desktop. Consolidation baseline:
`5fd961cace769bdfda9eed2fb5c86316247648e7`.

This index separates evidence, approved work and hypotheses. Merging research
preserves knowledge; it does **not** authorize every experiment in it. Frozen
specifications continue to govern their own results. V3.1 approval is for the
combined design and implementation preparation below, not a historical launch,
reserved-window access, a live-price paper run or live trading.

## Implemented capabilities and observed evidence

| Area | Established state | Boundary |
| --- | --- | --- |
| V1 grid/variants | Replay, controls, diagnostics and [completed comparison](backtests/2026-10-06-spec-v1-stage-1.md) exist; no winner, every variant failed C2 | Historical V1 criteria remain unchanged |
| V2 mode switcher | Spot trend/grid selection and replay exist; [verdict](backtests/2026-10-07-spec-v2-verdict.md) failed C1 | Closed experiment; the preserved entry-attribution branch is not current implementation |
| V3 futures | Frozen [specification](EXPERIMENT_SPEC_V3.md), signals, sizing, signed funding/accounting, daily decisions, hourly execution, lifecycle/evidence journals and reporting are implemented | Their existence does not establish profitability, combined spot/futures routing or live readiness |
| V3 primary evidence | [Return diagnosis](reviews/2026-10-10-codex-v3-return-diagnosis.md): 34.47% total marked gain, 8.82% CAGR and 66.82% maximum drawdown; A1–A3 below thresholds | Overall invocation failed at the benchmark; A5/final experiment receipt unavailable; no complete passing verdict |
| Cross-version diagnosis | [PR #265](https://github.com/mgalic01/adaptive-market-engine/pull/265), reviewed reference head `5253387d434a5a4c8cb2dc64a41f4e848c247c4a` | Pending, not merged at this consolidation; do not describe its report as current-main evidence |

V3's positive terminal marked result includes unrealized PnL and does not prove
realizable live profit. Shorts lost even before explicit fees/funding; aggregate
results hide large period differences. Cost attribution is not a counterfactual
replay. No completed V1–V3 result is rescored against V3.1's new budget.

## Approved V3.1 commitments

The owner approved a **full combined spot trend/grid and futures long/short
system**, rather than selecting a smaller product from the historical roadmap.
The design must specify and then verify these contracts before any run:

- Deterministic causal routing between spot trend, range grid, futures long,
  futures short and cash. Signals use completed, available information; define
  transition persistence, stale-input behavior and deterministic tie resolution.
- Affirmative short qualification: absence of a long signal does not authorize a
  short. Preserve distinct long/short attribution and explicit abstention.
- Volatility- and cost-aware sizing, including fees, spread/slippage and expected
  funding available at decision time. Model realized funding separately; never
  insert future realized costs into earlier decisions.
- Shared portfolio risk and asset ownership across all engines, including pending
  intents, partial fills, cancellations and uncertain execution. An engine cannot
  independently spend or reserve capital already owned by another. Apply shared
  gross/net, concentration, collateral and liquidation-buffer constraints.
- Lifetime maximum-drawdown acceptance ceiling **30%**, measured against a lifetime
  equity high-water mark that recovery never resets. Runtime recovery is a separate
  control, not permission to forgive an acceptance failure.
- At **30% drawdown**, exit and enter a **24-hour cooldown**. Qualified restart uses
  **25% size** with a **3% episode stop**; allow **half size below 15%** lifetime
  drawdown and **full size below 10%**. Recovery does not reset lifetime drawdown.
  The detailed spec must freeze qualification, equity denominators, episode-stop
  reference, event ordering, gap/slippage handling and repeated-stop behavior
  before implementation is treated as executable policy. These thresholds alone
  are not a complete state machine or a guarantee that realized drawdown stays
  below 30% through gaps.

This is the approved direction, not a claim these combined capabilities already
exist. The detailed V3.1 spec and preregistration must define the finite trial
budget, comparisons, costs, timing and acceptance calculations before evaluation.
No historical run is authorized, and 2025-onward market data remains reserved.
There is no guaranteed 10–20% monthly target. Approximately EUR 100 economics,
minimum order sizes and operational cost still need reporting.

## Research retained, with dispositions

| Reference | What remains useful | Disposition |
| --- | --- | --- |
| [Historical strategy roadmap](HIGH_PERFORMANCE_CRYPTO_STRATEGY_ROADMAP.md) | I–M proposals, exit/re-entry comparisons, portfolio and evaluation contracts | Historical proposals; approved commitments above take precedence over old ordering/settings |
| [External research and build decisions](EXTERNAL_RESEARCH_AND_BUILD_DECISIONS.md) | Pinned Jesse/MDRAP/Fenix/trend-switcher/strategy-library findings, dependency and licensing caveats | Research questions and engineering patterns, not approved platform adoption |
| [V2 diagnosis](backtests/2026-10-08-spec-v2-diagnosis.md), [entry schema](backtests/ENTRY_ATTRIBUTION.md), [implementation record](reviews/2026-10-08-codex-entry-attribution.md) | Loss mechanisms, selection versus attempts, historical test/equivalence record | PR #208 superseded once this documentation consolidation merges; no obsolete V2 code imported |
| [OpenTraderWorld evaluation](reviews/2026-10-06-codex-opentraderworld-evaluation.md) | Pinned source/security observations, dependency boundary, FSL licensing, one-artifact fidelity probe | PR #177 deferred once this documentation consolidation merges; exporter remains outside this PR |

PR #208 source head: `558c86dc6a0cec1d496a007ea58d050d0099369a`.
PR #177 source head: `5a120555a17f1cc6b0cbdf66f400771e040149c7`.
Its [pinned probe README](https://github.com/mgalic01/adaptive-market-engine/blob/5a120555a17f1cc6b0cbdf66f400771e040149c7/experiments/opentraderworld/README.md)
retains instructions without importing the exporter or its dependencies.
Historical verification claims in these records belong to their source branches;
this consolidation neither reruns nor certifies them. Both PRs stay open until the
documentation preservation has actually merged and the coordinating agent records
their dispositions. This index does not claim they are already closed.

Deferred hypotheses include alternative I/J/K/M parameters, OI/basis/session-time
filters, ML/AI memory, leverage escalation, profit-vault sensitivity and external
platform integrations. A shared architectural theme does not approve all its
historical parameter values. Each requires a concrete incremental benefit and
separate bounded specification/authorization; negative results remain visible.

## Work queue and ownership

| State | Item | Owner / next action |
| --- | --- | --- |
| Completed in this batch | Main reconciliation; preserved #208/#177 documentation; current/historical separation | Codex Desktop publishes one verified documentation batch |
| Active | PR #169 review and documentation merge gate | Bob/Claude substantive review of latest full head; coordinating Codex assesses feedback/checks |
| Next, after merge | Record #208 superseded and #177 deferred without losing their branch references | Coordinating Codex; no closure before preservation merges |
| Pending independently | PR #265 cross-version report | Its named writer/reviewer; update this index only after verified merge |
| Next implementation work | Detailed approved combined V3.1 specification and causal/risk contracts | Coordinating Codex assigns writer; this research merge is not a launch trigger |
| Blocked by explicit run authorization | Any historical execution or reserved data | Owner; no launch inferred from design approval |
