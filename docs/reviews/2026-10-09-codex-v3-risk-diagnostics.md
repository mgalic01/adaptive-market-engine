# V3 drawdown, volatility and cap-day diagnostics

Index: Added supplied-evidence worst-drawdown dates, realized volatility and cap-binding-day share; fixed a missing-bar compatibility defect before publication.

The frozen report requires worst-drawdown dates, realized portfolio volatility
and the share of decision days with a binding cap. The helper recomputes the full
ordered equity path and preserves path indices/kinds for same-hour extremes.
It reports the first worst trough, using the latest equal peak before it; a
nondecreasing path has no episode. These are diagnostic tie conventions.

Realized volatility is sample standard deviation times sqrt(365), the same
annualization convention as Sharpe, with fewer than two returns unavailable.
The caller supplies the complete series including its terminal observation.
Cap share counts each day once, even with several binding caps, and includes
flat days. Consecutive days and explicit sizing-universe cap keys are required.
Source provenance and full run endpoints remain caller responsibilities.

Seven initial missing-API tests failed, then 43 focused checks passed. Independent
review found that valid missing-bar decisions omit executable targets but retain
the full sizing universe. A production DailyDecisions regression failed, then
passed after checking cap keys against sizing.weights instead of targets.
All 44 focused risk/metrics/decision tests, Ruff and mypy pass. Full CI and
substantive exact-head external review remain required. No source data, trading
rules, acceptance criteria, dependency or historical run changed.
