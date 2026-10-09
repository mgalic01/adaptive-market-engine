# V3 fixed-rule comparison menu

Index: Implemented the twelve frozen full-period fixed-rule reporting scenarios with independent accounts and durable attempt evidence; synthetic-only, no historical dispatch.

Section 8 requires results for all twelve rules as if each were picked every
quarter. `replay_fixed_rules` uses the supplied main test's quarter boundaries and
substitutes the same rule at every boundary. Every rule gets a fresh m=2,
base-cost account. The main picks are untouched, and no new winner is selected.
Return order is the frozen R1–R6, then R1L–R6L order.

The start record contains the full fixed schedule before execution. The existing
sensitivity replay's record/reconcile/error handling is shared in one private
helper: reconciled strategy-invalid results remain reportable; an engine error
retains available partial evidence and aborts the remaining menu. KeyboardInterrupt
leaves an unfinished start. A publication failure is not turned into successful
completion or an automatic retry. Walk-forward training itself is unchanged.

Three initial tests failed before implementation. All 31 fixed-rule,
orchestration and evidence-writer tests pass, including an actual synthetic
twelve-account run recorded through AttemptRecorder, twelve published artifacts
and successful read-back verification. The pre-existing sensitivity tests cover
independent accounts, invalid outcomes, reconciliation errors and engine aborts
through the extracted helper. Ruff lint/format and mypy pass.

Independent read-only review found no actionable defect in the implementation.
The subsequent test enhancement connected the twelve-account test to the actual
durable writer and was rerun successfully; no source changed after that review.
Full CI and substantive exact-head Bob/Claude review remain required before merge.

These are supplied-input helpers. Their synthetic execution did not load market
archives or authorize historical runs. The enclosing dispatch must validate data,
quarter boundaries and registration before use. No dependency, strategy, cost,
selection criterion or permission changed. Codex owns the final report and
registered integration, which remain separate work.

Bob identified a direct coverage gap in the partial execution-error branch.
Two new regressions now raise ReplayExecutionError through each menu, assert
the same partial result reaches the finished attempt, and verify persisted hour
and account rows alongside the error. Reopening the recorder verifies the linked
artifact and leaves no pending attempt. All 33 focused tests pass. This is a
test-only follow-up; no production behavior changed. The earlier 31-test coverage
did not directly exercise partial ReplayExecutionError retention in both menus.
