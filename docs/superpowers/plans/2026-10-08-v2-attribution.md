# V2 attribution implementation plan

> Execute inline using superpowers:executing-plans, with test-first verification.

Goal: explain selected-but-unfilled Uptrend entries without changing trading behavior.

Architecture: additive frame diagnostics produced at existing decision branches; replay retains
one record per selected opportunity and counts subsequent entry buy attempts separately.
No diagnostic becomes account state or a strategy input. Standard-library Python only.

Spec: owner's approved Experiment 0 in the 2026-10-08 diagnosis proposal. This first
independently reviewable batch implements the entry funnel. Position excursion and full grid
lifecycle attribution follow as a separate batch; they are not claimed by these records.

Constraints: paper only; no market downloads, reserved data, parameter changes or new trials.
Existing V0 output remains unchanged. Existing MS numeric and decision digests must remain
unchanged after removing only the explicitly added diagnostic fields.

Review focus: overlapping blockers; partial fills and repeated depth refusals; minimum-size
budget refusal; recovery completing on a decision frame; old reports without new fields.

## Task 1: Selected-entry diagnostics

- [ ] Add runner tests for filled selection, blocked selection and depth/budget outcomes.
- [ ] Run tests and observe missing-field failures.
- [ ] Add `uptrend_entry` output at existing branches: selected flag, timestamp, blockers,
  outcome, cash/risk context, stop and actual buy result. Preserve original decision order.
- [ ] Pass runner tests and the frozen behavior digest, excluding only new output.

## Task 2: Replay reporting

- [ ] Add tests for aggregation of selected opportunities versus continuation attempts.
- [ ] Add a reporting-only collector with selected records and separate attempt counts.
- [ ] Publish it as `modes.entries`; old reports without diagnostics remain accepted.
- [ ] Run replay equivalence, type/lint checks and full tests; document units and limits.

## Delivery

- [ ] Review the diff independently, record verification and remaining scope, commit and
  push the isolated branch with an open PR. Do not merge.
