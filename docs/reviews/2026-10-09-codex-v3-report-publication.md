# V3 offline report publication handoff

Index: Uncertified JSON/Markdown publication and hash-pinned completion receipt prepared; no dispatcher, verdict or data access.

Base: `c906216621da0e0f21f7768436b48c086a89a95b`. Named writer: Codex,
branch `codex/v3-report-publication`, isolated worktree
`C:/Users/Marko/.codex/worktrees/v3-report-publication`.

`scripts/v3_report_publication.py` adds `publish_experiment_report` and
`verify_published_report`, returning `PublishedReport`. The publisher accepts an
existing exclusively owned evidence directory, supplied `ExperimentReport` and
`RegisteredDocuments`. It keeps the existing JSON/Markdown serializers and runner
unchanged. It checks supplied document hashes and identity shapes, retains
`verdict=None` and all applicable report prerequisites, validates observed attempt
journals/artifacts, rejects pending attempts and orphan published artifacts, and
preserves recorded errors as errors.

It exclusively creates `report/`, writes and fsyncs `experiment.json` and
`experiment.md`, rechecks observed evidence and report bytes, then publishes
`publication.json` through an atomic create-if-absent hard link. The receipt
contains identity fields, report hashes/counts and a sorted observed attempt index
with journal hashes and artifact references. Root-level journal JSON names remain
unchanged. Partial files stay on failure; existing publications cannot be overwritten
or resumed. The reader requires a separately retained receipt digest and matching
supplied registered documents, and rechecks report and attempt evidence. Files
without a verified receipt are incomplete, irrespective of their filenames.

The caller must obtain documents from committed registration validation and perform
runtime rechecks and authorization gates. Merely supplying structurally correct
metadata does not prove provenance, report derivation or complete historical attempt
coverage. Reconciliation of every prescribed scenario/training score and all prior
attempts remains separate, as does final verdict certification. This is cooperative
single-writer persistence, not a security sandbox or universal power-loss guarantee.
No directory fsync guarantee is claimed; unsupported hard links fail closed.

## Verification

TDD: 19 new tests first failed because the publication module did not exist; all 19
passed after implementation. Added reader identity/incomplete-publication tests,
serialization failure, later fsync failures and symlink coverage. Stable focused run:
`python -m pytest tests/test_v3_report_publication.py tests/test_trend_evidence_journal.py tests/test_trend_evidence_writer.py`
reported **48 passed, 1 skipped** in 11.55 seconds on Python 3.14.7. The skip was
Windows source symlink creation unavailable. Fixtures contain synthetic report
objects and journal rows; no strategy replay or market input was used.

`python -m mypy src scripts` passed (115 source files). Ruff lint and formatting
checks passed; Bandit passed; append-only trial validation against the full base
commit and `git diff --check` passed. An earlier mypy invocation restricted to the
single new script resolved installed packages rather than source and reported
untyped-import errors; the proper repository-scope command above passed. No full
suite or dependency audit was run locally; CI and independent review remain pending.

Queue: implementation and focused verification complete; parent Codex owns review,
any fixes, publication integration and the separate scenario/history reconciliation
work. No push, PR, merge, download, retry, run dispatch or final verdict was performed.
Revert removes this new optional API; retain any published/partial report evidence.

## Review follow-up: ambiguous cleanup outcome

If atomic receipt publication succeeds, any later exception (temporary cleanup
or final verification, including a read error or evidence drift) can leave a
receipt despite the API raising. Preserve every remaining file and the report;
do not delete evidence or retry publication. Receipt presence alone does not mean
verification succeeded. Inspect the
receipt and establish its digest deliberately, then call `verify_published_report`
with the same registered documents. An inspection-derived digest checks current
internal consistency, not the authenticity of a previously retained independent
pin. Runtime/provenance gates still apply. A verified receipt remains uncertified
diagnostics. This behavior is covered by injected cleanup failure after link success.

A second synthetic test covers the full-size-hold branch: JSON and receipt retain
all remaining prerequisites and an unset verdict, and Markdown includes that
diagnostic. No replay is used. Follow-up focused result: **26 passed, 1 skipped**
for `tests/test_v3_report_publication.py` (4.01 seconds, Python 3.14.7); the existing
Windows symlink-permission skip remains. Production behavior is unchanged.

Bob's review at `156cae3d2044d5bd3ab2639e229cba3a754e0e35` prompted an additional
injected final-verification failure test and the broader wording above. The reader
verifies the named report files and observed published journals/artifacts; it does
not enumerate unrelated files in `report/` or pin unpublished `.journal-*` and
`.evidence-*` temporaries. Preserve and inspect those separately after interruption.
This receipt therefore does not certify that its directory has no other evidence
or that every historical attempt is represented. The future invocation/history
reconciliation owns that wider accounting. No cleanup or new rejection policy was
introduced. The full-size-hold unavailable outcome remains the owner's accepted
diagnostic exception, not an A5 failure.

Parent follow-up validation: 27 passed, 1 Windows symlink skip on Python 3.12.14; changed-file Ruff lint/format and whitespace checks passed. No production behavior changed.
