# V3 core performance metrics

Index: Decimal60 Sharpe, CAGR, drawdown, Calmar, trade/daily profit factors and
runner summary integration tested synthetically; no performance claim or replay.

Purpose: compute the frozen evaluation statistics from inspectable runner evidence.
Owner: Codex Desktop. Stacked on lifecycle integration; do not merge into dependency.

The implementation keeps trade profit factor separate from the daily diagnostic,
uses sample return variance and sqrt(365) for Sharpe, timestamp-derived duration
and 365.25 for CAGR, and the entire ordered equity path for drawdown. It handles
zero variance, no winning/losing trades, zero drawdown and nonpositive terminal
equity explicitly. Win rate includes zero-result trades in its denominator.

The runner summary requires completed state, no open lifecycles and accepted audit
evidence. Trade totals must reconcile exactly with total equity change; failure is
an engine/evidence error, not a strategy rejection. This strict check may expose
Decimal grouping differences. Its separate reconciliation remains exact; the
owner-approved equity-audit tolerance does not change it. Timestamp/path provenance and full window coverage remain upstream
obligations; these formulas alone do not validate a dataset or certify an experiment.

Validation: 159 focused synthetic tests pass across the current V3 stack, including
11 metric tests and a full synthetic runner-to-summary case including censored
trade costs. Ruff, mypy and Bandit pass. Full CI and external review are pending.

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
