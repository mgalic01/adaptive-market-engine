# Readable V3 account report

Index: Added Markdown tables for supplied account reports, preserving invalid status, units, exact reconciliation residuals and the JSON precision companion.

The renderer displays performance, monthly returns and hosting economics, costs,
exposure/cap coverage, drawdown dates and coin/side profit. It labels the account
status and explicitly leaves the experiment verdict unevaluated. Invalid runs
show unavailable completed-run metrics and keep their failure reason.

Display numbers use at most six decimal places, with percentages labelled. The
JSON companion remains exact, and signed reconciliation residuals are printed
without rounding. Positive Infinity is explicit. Table text escapes HTML, pipes
and line breaks. Same-hour drawdown extremes preserve their path indices/kinds.

Three missing-API tests failed before implementation. All eight renderer/report
tests pass, including invalid states, Infinity, tiny residuals, escaped coin text
and same-hour drawdown dates. Independent read-only review reran all eight and
found no actionable issue. Ruff, mypy and Bandit pass; full CI and substantive
current-head external review remain required before merge.

The renderer trusts the supplied audited report and does not fetch data, write
files, execute a strategy or certify historical provenance. It does not replace
the whole-experiment report, spot comparisons, trial links or frozen A1-A5.
No dependency or trading change. Codex owns the remaining report integration.
