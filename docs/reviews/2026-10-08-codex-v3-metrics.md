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

The runner summary requires completed state, no open lifecycles and exact audit
evidence. Trade totals must reconcile exactly with total equity change; failure is
an engine/evidence error, not a strategy rejection. This strict check may expose
the same Decimal rounding issue already awaiting owner decision. No tolerance is
introduced. Timestamp/path provenance and full window coverage remain upstream
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

The owner has since approved the equity-change audit amendment in PR #221.
This metrics branch has not yet integrated that dependency; its audit gate must
be aligned with the approved accepted predicate during integration. The separate
trade-total reconciliation remains exact and is not covered by that approval.
