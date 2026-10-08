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

Combined integration verification: latest replay run-end correction, bounded daily
sizing, deferred pick attribution, and both owner clarifications are integrated.
All 65 orchestration/replay/metrics/pending/decisions/exclusions tests pass, including
the complete twelve-account synthetic training test. Ruff passes; mypy checks all
17 trend modules; trial register validates. Current trial is v3-candidate-space-5.
Earlier exact trade-total reconciliation wording above is historical: the owner's
separate approved bound now applies, with signed residual retained in summaries.
No historical source or replay was used. Dependency reviews and completing
registration remain required; this synthetic integration is not a profitability test.

Sensitivity replay added: fixed main picks drive five fresh futures accounts,
(m,cost)=(1,1),(3,1),(1,2),(2,2),(3,2). Main (2,1) already exists. No retraining;
invalid outcomes retain evidence and engine errors abort. Attempt records now name
multiple and cost_multiple. Three new tests cover menu/picks/evidence, engine-error
abort, and five real independent flat synthetic accounts. Six fast orchestration
tests pass; the earlier full training test was not rerun for this additive helper.
Ruff and mypy pass. Spot benchmark/cost replay and historical dispatch still pending.

Cancellation evidence fix: every training, OOS and sensitivity replay now first
calls the mandatory recorder with state=started and its run ID, bounds and scenario.
The recorder must durably persist before returning; failure prevents dispatch.
Normal/error completion emits state=finished with the same ID. A process kill or
BaseException may leave only started, which the supervising dispatcher must finalize
as interrupted/cancelled after confirming termination. This module does not claim
to implement that durable writer or recovery supervisor. Seven fast tests pass,
including KeyboardInterrupt after the start record and zero dispatch on save failure;
Ruff and mypy pass. Lifecycle reconciliation for all invalid/OOS runs remains an
open Cloud finding and must be addressed before merge.
