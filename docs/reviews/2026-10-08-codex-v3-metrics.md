# V3 core performance metrics

Index: Decimal60 Sharpe, CAGR, drawdown, Calmar, trade/daily profit factors and
runner summary integration tested synthetically; no performance claim or replay.

Purpose: compute the frozen evaluation statistics from inspectable runner evidence.
Owner: Codex Desktop. PR 220 targets main and includes the current PR 224 decisions dependency. Merge commits must preserve registration ancestry; no squash.

The implementation keeps trade profit factor separate from the daily diagnostic,
uses sample return variance and sqrt(365) for Sharpe, timestamp-derived duration
and 365.25 for CAGR, and the entire ordered equity path for drawdown. It handles
zero variance, no winning/losing trades, zero drawdown and nonpositive terminal
equity explicitly. Win rate includes zero-result trades in its denominator.

The runner summary requires completed state, no open lifecycles and accepted audit
evidence. Trade totals reconcile within the owner-approved inclusive absolute bound
of 1e-18 USDT, with the signed residual retained; wallet and quantity audits stay exact.
Every supplied sample must match the complete sequence of 01:00 open marks and the
terminal mark in the ordered equity path. Dataset/source completeness remains an
upstream obligation; these checks do not certify an experiment.

Current validation (2026-10-09): 25 metric cases pass. Two regressions first showed
that dropping a sample or using a different hour passed; both now fail explicitly.
A separate regression covers unordered path timestamps with otherwise matching
samples. Earlier test counts below are historical, not current-head claims.

Outstanding: Sortino and broader diagnostic definitions, bootstrap, benchmarks,
acceptance gates, walk-forward orchestration, report serialization and actual data
integration. No historical replay or market-data fetch occurred. No dependencies
or frozen parameters changed; high-return objectives remain unproven.

## Initial-equity review correction

Cloud's finding at 7f1ac293b36e9198af88ee965c061a7761116072 was reproduced with
samples 100 to 110, path 90 to 110 and trade PnL +20. Summary now rejects differing
initial equities as well as differing terminal equities. All 12 metric tests pass;
Ruff and mypy pass. Full CI and renewed review remain required.

The owner approved the equity-change audit amendment in PR #221, now integrated
with the lifecycle corrections. The summary audit gate uses accepted, preserving
the raw residual and exact status. A regression verifies the permitted tiny equity
residual passes reporting while a tiny wallet discrepancy still fails. All 76
metric/account/runner/lifecycle tests pass, with Ruff and mypy. Renewed full CI and
external review are required at the integrated head. The separate trade-total
reconciliation remains exact and is not covered by that approval.

Review follow-up: the summary tolerance test now covers both nonzero wallet and
nonzero quantity residuals. Both remain rejected. Current metric-only verification
is 14 test cases (13 functions, one parametrized), passing. Earlier 11/12 counts
refer to prior revisions; 159 and 76 refer to different broader stack suites, not
the metric-only count. Real lifecycle/equity grouping investigation remains open;
no relaxation of exact trade reconciliation is authorized or implemented.

Real lifecycle regression: a 50-hour synthetic run opens at price 1, changes target
at price 2, then closes at price 2. Every equity audit is accepted; nonexact audits
retain -5e-57. One uncensored completed lifecycle is present, but summarize_runner
raises 'trade results do not reconcile with account equity'. The regression locks
in the current strict rejection rather than silently relaxing it. This is confirmed
numerical/evidence friction, not a strategy loss or historical performance result.
All 15 metric cases pass. Quantify the separate trade residual before proposing an
owner-approved replacement; the existing equity-only approval does not cover it.

Owner-approved replacement implemented: trade-total reconciliation accepts inclusive
absolute residual <=1e-18 USDT and exposes trade_reconciliation_residual in every
PerformanceSummary. Out-of-bound errors include the signed residual. Trading
arithmetic and exact wallet/quantity audits remain unchanged. The preceding strict
rejection notes describe history, not the new approved policy. Spec e7ea68a precedes
replacement registration 7ee82e0 (v3-candidate-space-5), which precedes implementation.
All 70 metric/account/runner tests pass, including the real completed round trip,
both inclusive boundaries and just-outside values. Ruff and mypy pass. New summary
field is an output-schema addition; serializers must retain it. No historical run.

Current-main integration and metric evidence repair: merged main 4459964 and the
latest daily-decision branch, retargeting PR220 to main. The Cloud sample/path
finding reproduced: endpoint-only reconciliation accepted a fabricated interior
sample. summarize now takes timestamped EquityState records and requires every
daily sample to match an open or terminal mark at its own timestamp; unordered
paths are rejected. summarize_runner supplies the complete existing path directly.
This intentionally changes the new internal summarize API from bare Decimal paths;
all repository callers are updated. Tests also reject a real path value assigned
to the wrong sample time. Twenty-two metric tests pass; the prior combined batch
passed 96 tests before that additional timestamp regression. Ruff and mypy pass.
No historical result, spec change or new dependency. Fresh review/CI required.

Sample completeness follow-up: raw summarize and summarize_runner now enforce the
same exact sample sequence. Hand-calculated fixtures use 01:00 marks; their interior
non-sample peak is explicitly a favourable mark. No formulas, parameters or tolerances
changed. The initial exact-reconciliation discussion below is historical and was
superseded by the recorded owner approval. The registration pins were rechecked from
raw Git blobs before this push; no data or historical dispatch occurred.

Final focused check for this batch: 73 metrics/runner/lifecycle/decision/pending tests pass; full Ruff format/lint and mypy pass. A read-only internal reviewer independently passed 25 metric tests and checked the 01:00 terminal boundary. Raw spec blob SHA-256 at both e7ea68ad20d41aa6890fddc395b5698ac37463b3 and this branch is 1c541b38cb1858c8ac8262d9233813f31ef8c084bca74c017f8cf6bb23e42bca; the pinned commit is an ancestor. Full CI and Bob's latest-head review are still required.
