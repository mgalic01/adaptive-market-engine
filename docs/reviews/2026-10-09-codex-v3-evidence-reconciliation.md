# V3 training and scenario evidence reconciliation

Index: Offline exact-menu and training-Sharpe reconciliation implemented and tested; bindings remain uncertified and do not establish market or registration provenance.

Goal: prevent a supplied training score or omitted/swapped scenario from silently
entering the V3 diagnostic report. The new optional reader checks the exact frozen
menu of 12 training attempts per quarter plus 21 other attempts, derives roles
from journal fields rather than filenames, and returns compact artifact bindings.
Existing runners, serializers, parameters and acceptance criteria are unchanged.

`reconcile_experiment_evidence(directory, training, picks, first_months)` rejects
pending/failed attempts on its completed-menu path, duplicate/missing roles, wrong
settings/boundaries/schedules, malformed headers, rejected audits, active futures
lifecycles, changed artifact bytes and orphan published artifacts. Training scores
are recomputed with existing Decimal Sharpe/sample arithmetic from saved path and
sample evidence. Known invalid strategies retain their reasons; unavailable
full-size hold remains a diagnostic availability outcome, not an A5 failure.

The reader hashes the same bounded rows it interprets and retains at most one
training path/sample set alongside compact metadata. It does not retain full
runners or open market archives. Initial equity, training boundaries and full-size
hold membership/budgets are cross-checked without changing the frozen rules.

Limits: hashes bind supplied bytes, not truthful execution. This does not prove
registration linkage, market provenance, nontraining report-metric derivation or
history outside the supplied directory. Caller owns a quiescent directory and
must call before publication adds its report subdirectory. No report prerequisite
or final verdict is changed. Unknown temporary files are not authenticated as
historical attempts; interrupted evidence needs separate inspection.

The implementing agent hit its usage limit after writing the code/tests. Parent
Codex inspected the preserved implementation and reran validation, without relying
on the agent's unfinished test session. A second agent's independent review also
hit its limit and is not counted as a completed review. External Bob review is
therefore explicitly required before merge.

Parent validation:

- Reconciliation plus journal/writer/selection/experiment-runner regressions:
  **83 passed** on Python 3.14.7.
- New reconciliation tests independently on Python 3.12.14: **42 passed**.
- Changed-file Ruff lint/format, mypy and Bandit passed.
- No historical replay, archive access, registration mutation or network access
  occurs in these tests. Full CI remains pending.

Next: external review and integration into the registered dispatcher. The API
alone grants no execution authorization and does not certify the experiment.
