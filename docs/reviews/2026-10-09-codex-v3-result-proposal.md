# V3 read-only result proposal exporter

Index: Existing-schema result proposal bytes from observed attempt journals; no canonical history mutation, dispatch, acceptance decision or verdict.

Base: `c906216621da0e0f21f7768436b48c086a89a95b`. Named writer: Codex,
branch `codex/v3-result-proposal`, isolated worktree
`C:/Users/Marko/.codex/worktrees/v3-result-proposal`.

## Contract

`scripts/v3_result_proposal.py` adds a read-only `build_result_proposal` API taking
register bytes, supplied `RegisteredDocuments`, an existing evidence directory,
a canonical repository-relative proposed index path, evidence-source text, an
explicit recording timestamp/agent and exact pending dispositions. It returns
`ResultProposal(index: bytes, events: bytes)`. It neither saves a proposal nor calls
the canonical register writer. Register/journal/artifact bytes remain unchanged.

Completing registration, trial, spec, code, config and manifest identities must
match supplied documents; supplied manifest/config bytes must match their hashes.
The existing register parser and append validator enforce the unmodified schema,
references, run-ID uniqueness and append-only history. Matching supplied metadata
does not authenticate that it came from committed registration validation; that
validation and authorization remain upstream prerequisites.

Every observed start yields one event, sorted by run ID. Event IDs are
`v3-result-` followed by SHA-256 of compact JSON `[trial_id, completion_id, run_id]`.
The index pins the exact input register and journal/artifact bytes, identities,
classification and explicit disposition. Events pin the index digest and registered
identities in provenance text and reference its run entry. No performance metrics
are fabricated (`metrics` is empty). `recorded_at` records the proposal, not an
inferred execution time. Evidence-source and disposition-source strings are text;
they are never opened, executed or treated as authenticated authorization.

## Classification and boundaries

A nonempty recorded execution error maps to `failed`, even with a partial artifact.
Otherwise known futures reasons map to success/invalid, spot completion or unavailable
close maps to success/invalid, and full-size hold completion or unavailable first
purchase maps to success/invalid. Unknown phases, unsupported reason types, unknown
reasons, missing/duplicate phase-specific outcomes and corrupt identities/artifacts
block export. Full-size hold unavailable is only an unavailable/invalid diagnostic
run; it never decides A5 or an experiment verdict. Success means a recorded run
completed, never that acceptance criteria passed.

Pending starts require exactly matching caller-reviewed failed/cancelled claims,
with a reason and diagnosis source. Their artifact, if present, remains explicitly
unconfirmed; its existence cannot imply completion. The exporter does not diagnose
process state, infer cancellation/time, finish journals, recover or retry runs.
Callers must first establish quiescent exclusive ownership. Orphans without starts
block export. A final repeated observation rejects detected mid-export drift, but
cannot eliminate concurrent races or establish a security boundary.

This index covers observed local attempts only. It does not certify complete
historical attempt coverage, audit arithmetic, report derivation or final verdict.
No completing registration, data-access permission, canonical append or historical
run is authorized by a successful proposal. Separately reviewed append and
scenario/history reconciliation remain necessary.

## Verification and queue

TDD: the first 37 tests failed because the module did not exist; all 37 passed after
implementation. Additional tests cover invalid/extraneous pending claims, missing
artifacts/errors, absent input directories, empty journals, read denial and changing
evidence. Stable focused command:

`python -m pytest tests/test_v3_result_proposal.py tests/test_trial_register.py tests/test_trend_evidence_journal.py tests/test_trend_evidence_writer.py`

Result: **115 passed in 26.71 seconds**, Python 3.14.7, using synthetic metadata and
journal rows only. Ruff lint/format, mypy (115 source files), Bandit and
`git diff --check` passed. Initial mypy reported annotation inference mismatches,
and Bandit flagged an assertion; both were fixed before the final passing checks.
No full suite or dependency audit was run locally. Parent owns independent review,
CI, any integration and the later separately reviewed canonical append process.

Completed: implementation, deterministic mapping and byte-preservation tests.
Next: parent review and integration. Still separate: complete history/scenario
reconciliation and verdict. No push, PR, merge, market data, E: access or replay
was performed for this task. Revert removes this optional proposal API only.

## Attribution review clarification

Attempt journals have no trial/completion pins. Therefore the input directory's
association with the supplied registration is a caller-proposed, unverified claim.
The index and every result event's provenance carry
`attempt_registration_binding=caller_proposed_unverified`. Matching document hashes
and schema-valid events do not authenticate the actual run's registration. Another
otherwise valid registration can label the same observed directory only with this
explicit unverified attribution. The regression test exercises that case.

Before canonical append, a separately reviewed invocation record must establish
the evidence-directory identity and registration/code/manifest pins actually used.
The exporter neither creates that evidence nor approves an append. The future
registered launcher must retain that invocation linkage. No new association API or
journal schema is introduced in this proposal-only batch.

Follow-up validation: the alternative-registration regression failed first because
that explicit label was absent. After the fix, all 50 exporter tests passed in
3.91 seconds; Ruff lint/format, mypy, Bandit, report validation and diff checks
passed. No schema or journal changes were made.
