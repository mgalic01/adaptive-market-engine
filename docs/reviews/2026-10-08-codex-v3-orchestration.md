# V3 walk-forward orchestration

Index: Codex implementation of frozen training selection and one continuous OOS account; synthetic verification only.

This serves the frozen experiment by running its twelve rules in separate training
accounts, selecting by training Sharpe, and replaying all quarter picks in one OOS
account. The fixed main path uses m=2 and base costs. No candidate is added or tuned.

`trend/orchestration.py` composes the reviewed calendar, selection, replay and metrics
interfaces. Explicit strategy-invalid results receive no score. Engine and accounting
errors are recorded and re-raised; they cannot become poor scores or silently excluded
candidates. Every attempt has a unique identifier and a mandatory record callback.
Failure to save evidence aborts. Callers must serialize the supplied evidence rather
than retain all training runners in memory.

Verification: four synthetic tests pass, including one full 18-month flat training
period for each of the twelve rules followed by one OOS quarter. Controlled failure
tests cover all-invalid selection, engine failure, and recorder failure. Ruff and
mypy pass. These tests establish orchestration behavior, not profitability.

Stacked integration includes the replay adapter, metrics and walk-forward helper
branches. Their outstanding reviews still apply. Do not merge into the dependency
branch. No new dependencies or known security changes.

Remaining work: reviewed source loading and provenance, completing registration,
durable evidence writer, sensitivity/cost scenarios, benchmarks and acceptance
reporting. No historical market data was fetched or replayed, and no dispatch is
authorized by this module. The separate exact lifecycle-total reconciliation remains
unchanged; the approved equity-audit tolerance does not relax it.
