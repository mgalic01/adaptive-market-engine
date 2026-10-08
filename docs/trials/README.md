# Experiment register

`register.jsonl` is append-only research history. It currently contains retrospective
source summaries and V3 candidate registration, **not a completed registration**.
It does not authorize any strategy run. The frozen spec governs the experiment;
this document describes storage and validation, not new acceptance criteria.

## Events

Every UTF-8 JSON line ends in a newline and has schema_version=1, a unique event_id,
trial_id, event_type, UTC recorded_at ending in Z, agent, family, parent_trial_id,
nonempty sources and payload. Unknown common fields, duplicate keys, nonfinite
numbers and duplicate event IDs fail validation.

- `retrospective`: preregistered=false, scope, outcome, missing_fields. Records are
  source summaries, not a complete count of all inspected historical attempts.
- `registration`: preregistered=true, hypothesis, spec path/commit/SHA256, candidates,
  integer sizes, fees, folds, mask, integer seeds, budget, stopping and selection.
  Code and data are null until completion. Empty seeds means no stochastic search.
- `completion`: registration_id, code_commit, code_sha256, code_paths, manifest and
  config path/SHA256 objects, and review provenance. One per registered trial.
- `result`: completion_id, globally unique run_id, status (success, invalid, failed,
  cancelled), provenance, report, metrics and reason (null on success, nonempty
  otherwise). A failed attempt may have empty metrics but must have an explanation.
- `correction`: target_id, reason, details. Appends an annotation without modifying
  the target. A corrected trial cannot authorize new dispatch; register a new trial
  ID after review. Existing results remain visible, including losing attempts.

## Commands

From the repository root:

```text
python scripts/trial_register.py validate
python scripts/trial_register.py validate --base-ref FULL_BASE_COMMIT
python scripts/trial_register.py append --event event.json
python scripts/trial_register.py check-ready --trial-id TRIAL --revision FULL_COMMIT
```

Append validates the complete candidate document before an atomic replacement. It
uses an exclusive sibling `.lock`; a crash may leave that lock, which requires an
operator to verify no writer is active before removal. External editors must respect
that lock. No command commits, pushes, downloads data or launches a strategy.
The first append needs an existing parent directory. Invalid appends preserve history.

CI compares the register against the base commit's exact byte prefix (initial absence
is permitted). Do not reformat, delete, reorder or edit prior lines. Correction is
an event, not an in-place repair. Git review remains required; this checker is not a
security boundary against someone authorized to change the checker itself.

## Completion identity

Readiness reads only Git objects at the explicit full commit, never staged files or
working-tree content. Code and spec commits must be ancestors of that revision.
Spec bytes must match at both the registered spec commit and the dispatch revision;
config and manifest bytes must match their pins at the dispatch revision.

`code_paths` must enumerate every tracked file under `src/` and `scripts/`, plus
`pyproject.toml`, `requirements-dev.lock` and `requirements.txt` when present.
For each path sorted lexically, hash its UTF-8 path then raw Git blob bytes, each
prefixed by its unsigned 8-byte big-endian length. SHA256 is checked at both the code
commit and dispatch revision. Newly added implementation files invalidate the old
inventory. Registration is committed after the implementation, avoiding a hash of
its own completing event. Future runtime inputs outside these roots must be added
to the explicit manifest/config contract and reviewed before execution.

## Dispatch integration still required

There is no V3 runner or dispatcher in this batch. Future dispatch must invoke the
trusted checker before its first data read or worker launch, then run exactly the
checked revision with the pinned inputs. Readiness alone does not prove code review
occurred: reviewers must verify completion provenance before its commit is accepted.
The trusted controller must record every launched attempt, recover interrupted runs
and append success/failure/cancellation with matching provenance before accepting
reports. Bob's report-only publisher receives no additional write permissions.
Do not claim current V1/V2 workflows enforce this future V3 contract.
