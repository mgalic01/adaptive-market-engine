# V3 futures run-report assembly

Index: Assembled individual futures-account diagnostics and exact JSON; preserves invalid outcomes without completed metrics and issues no experiment verdict.

The report combines reconciled lifecycle totals, performance, monthly returns,
realized/target volatility, costs, coin/side profit, exposure, cap days, drawdown
dates and retained daily samples. Decision-day timestamps must match retained
midnight hours. Unknown outcomes and failed lifecycle reconciliation abort.

Known strategy-invalid outcomes retain their reason and available cost, trade,
exposure, cap, drawdown and sample evidence. Their completed-run performance,
monthly and volatility fields are null; an early-stopped account must not be
mistaken for a complete-period result. No experiment verdict is generated.

JSON uses exact Decimal strings, explicitly including legitimate Infinity for
profit factor/Calmar. NaN and unsupported values are rejected. Coin/side totals
are rows with separate coin and side fields rather than invalid JSON tuple keys.

Before this assembly, the combined branch containing PR235 and PR236 passed the
entire trend test selection, Ruff and mypy (28 source modules). Three missing-API
tests failed before implementation. Four assembly tests now pass, including a
real synthetic funded liquidation, retained diagnostics, rejection of corrupted
lifecycle fees, missing decision evidence and NaN, and explicit Infinity JSON.
Independent read-only review reran all four and found no actionable issue.

This is one account's report. It does not verify committed registration, input
provenance, full experiment endpoints, the full menu's presence or A1-A5 together.
Full experiment assembly still needs spot/full-size comparisons, fixed-rule and
sensitivity tables, bootstrap intervals, minimum-capital reporting and trial links.
Those omissions are not represented as completed work. No historical data fetch,
market replay, dependency or trading behavior changed. Codex owns the remaining
integration. Full CI and substantive current-head external review precede merge.

CI follow-up: the full test stage passed, but Bandit rejected the production
assertion used for the reconciled result's type narrowing. Replaced it with an
explicit ValueError guard, which remains present under optimized Python.
