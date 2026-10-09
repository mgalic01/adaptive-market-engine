# Owner decision: one local V3 development replay

Index: Owner authorizes one local V3 development replay after required reviews, through calculations and results; no reserved-window or live-trading approval.

On 2026-10-09, in response to the explicit question asking permission for one
reviewed V3 development backtest on E:, the owner answered: "yes, you have my
approval to go ahead and to finish everything all the tests, calculations etc.."
The owner also requested that any future required question remain visible in the
chat rather than appearing only in a disappearing control.

This grants the proposed one-run procedural exception to frozen spec section 9,
step 6: Codex Desktop executes locally instead of the backtest workflow, after
external review and required checks. Bob independently reviews the task and
results. No further start confirmation is required once those gates pass.

The disclosed downside is reduced separation between implementation and execution,
and reliance on the owner's available PC. Pinned evidence and independent review
reduce but do not eliminate that limitation.

This is an executor-only waiver attached to the existing candidate-space-7 trial,
not a change to its strategy, dataset, candidate menu, fees, folds, sizing, seed,
selection, stopping or A1-A5. Preserve the frozen spec and raw collected manifest
bytes. The proposed registration treatment is to reference this waiver explicitly
in completing-event provenance, rather than claim a new strategy was preregistered
after its implementation. Bob must review this treatment before launch.

Exactly one fresh invocation is authorized, with failed/interrupted evidence
retained and no automatic retry. Data ends at 2024-12. Reserved-window testing,
credentials and live trading remain separately gated. Results are not guaranteed
to pass; an honest failed experiment is retained and reported without tuning.
