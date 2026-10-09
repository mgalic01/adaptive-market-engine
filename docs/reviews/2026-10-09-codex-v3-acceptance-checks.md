# Frozen V3 criterion checks

Index: Implemented A1-A5 checks on reconciled matched-size accounts with complete matching rule schedules; no whole-experiment verdict or historical run.

A1-A4 use the main m=2 base-cost account's Sharpe >=1, trade profit factor
>=1.3, Calmar >=0.5 and CAGR >=0.08. A5 compares base-cost m=1 strategy Sharpe
strictly above the risk-matched spot hold account on identical samples.
All three accounts must start with 10000 USDT. Existing account reconciliation,
completed metrics and spot audit checks run before scoring. Main and m=1 daily
rule schedules must be complete against retained hours and match one another.

Immutable rows preserve each observed value, threshold, strictness and result.
Legitimate positive infinite trade profit factor or Calmar remains supported.
Invalid account outcomes are not assigned fabricated scores; the enclosing
experiment report must classify them. This calculator does not certify full
experiment dates, committed registration, source provenance, or accounting and
coverage of all other required training/sensitivity/fixed-rule accounts.

Nine missing-API tests failed before implementation. All 41 focused acceptance,
benchmark-comparison and metrics tests pass, including actual flat accounts,
threshold equality/below-boundary cases, infinite ratios and mismatched account
settings or rule evidence. Independent read-only review reran those 41 and found
no actionable defect. Ruff, mypy and Bandit pass. Full CI and substantive external
review at the exact head remain required before merge.

No criterion, strategy, dependency or data-access change. Codex owns the remaining
experiment assembly and registration. No historical performance claim is made.
