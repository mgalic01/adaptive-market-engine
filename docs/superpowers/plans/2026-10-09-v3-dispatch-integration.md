# V3 Registered Dispatch Integration Plan

> **For agentic workers:** Use superpowers:executing-plans for this integration; use synthetic fixtures only until the separately reviewed execution task authorizes historical access.

**Goal:** Invoke the existing frozen experiment once with committed, reviewed inputs and preserve its outcome without granting a final verdict.

**Architecture:** A small registered module composes the existing runtime preflight, document reader, inventory loader, input binder, runner, evidence reconciler and publisher. An explicit-file bootstrap loads the runtime checker in a fresh interpreter before project paths are inserted. Invocation records live outside the source checkout and outside the attempt journal directory.

**Tech stack:** Python 3.12+, standard library and existing project modules.

**Spec:** `docs/EXPERIMENT_SPEC_V3.md`, especially sections 8 and 9; `docs/tasks/2026-10-09-codex-v3-local-data-recovery.md` does not authorize replay.

## Constraints

- No strategy, fee, leverage, date, seed, calendar or selection overrides.
- No 2025+ market data, network fetching, live orders or exchange credentials.
- Completing registration must be committed before dispatch and pin the final integrated implementation.
- Reviewed execution authorization is required separately from collection approval.
- Fresh output only; preserve all partial evidence. No resume, automatic retry or replacement invocation.
- Publication remains explicitly uncertified; exit zero means diagnostics were published, not that A1–A5 passed.
- The runtime checker is cooperative error detection, not a security sandbox or protection against hostile in-memory modification.

## Review focus

1. Missing authorization or completion must be rejected before any archive is opened.
2. A conventional script launch must not accidentally bypass or fail origin auditing; use the explicit-file bootstrap and canonical module import.
3. The distinct unmasked full-size-hold stream must not be replaced by the strategy-eligible stream.
4. Interruptions before the first attempt, during replay and after receipt creation must leave an inspectable invocation outcome without rerunning anything.
5. Semantic evidence reconciliation must cover the prescribed menu without silently dropping invalid, failed or pending attempts.

## Task 1: Registered invocation and synthetic failure tests

Create `scripts/v3_dispatch.py`, `tests/test_v3_dispatch.py` and an indexed handoff. This module may be implemented only after the prerequisite API contracts are integrated and reviewed: runtime preflight (PR 255), report publication (PR 256), and training/scenario evidence reconciliation.

Concrete entry point: `dispatch_registered(snapshot: RuntimeSnapshot, *,
inventory_root: Path, output_root: Path, execution_task: str,
execution_task_sha256: str) -> str`, returning the publication receipt SHA-256.
The caller bootstraps and obtains the runtime snapshot before importing this
module; directly running it as an ordinary script is not supported.

The committed task JSON has exactly `schema_version` (integer 1), `trial_id`,
`code_sha256`, `manifest_sha256`, `config_sha256`, `inventory_root`, `output_root`,
`owner_approval_reference` and `review_reference`. Paths are absolute resolved
paths matching this invocation, outside the source checkout, and output cannot
contain or be contained by the inventory. References are inspectable operator
claims, not machine-authenticated approval. A separately reviewed human-readable
execution task explains these pins and grants the procedural go.

Invocation files: `execution-task.json` (exact committed bytes), `started.json`
(document/runtime/task identities), `bindings.json` (compact semantic bindings),
`finished.json` (success/failed/interrupted, receipt pin when available, unset
verdict). Attempt journals live exclusively in `attempts/`. Every file is created
exclusively and fsynced; the root is never reused. No power-loss guarantee or
automatic recovery is claimed. If terminal metadata itself cannot be written,
preserve the root for explicit inspection.

- [ ] Integrate the reviewed `reconcile_experiment_evidence(directory, training, picks, first_months) -> tuple[EvidenceBinding, ...]`. Flatten training rows and derive quarter picks from the returned report's selection, then retain the semantic bindings beside invocation metadata. No placeholder implementation or silent bypass; nontraining report metric derivation remains a stated limitation of this bounded checker.
- [ ] Define a narrow invocation entry point accepting root, full revision, trial ID, inventory directory, fresh invocation directory and the committed reviewed execution-task path/hash. Check the task bytes and declared invocation identities before archive access. External review and owner approval remain procedural prerequisites established by the operator; a task hash or arbitrary nonempty reference is not itself authorization and must never be described as proof of approval.
- [ ] Write synthetic tests for rejection before archive open, wrong revision/completion, one-call runner invocation, explicit input mapping, and refusal of an existing invocation directory.
- [ ] Implement the ordered composition: preflight; committed document read; dependency origin audit; local inventory load; registered input binding; runtime recheck; invocation start; one runner call; evidence reconciliation; runtime recheck; publication; separately preserved receipt pin and terminal invocation record.
- [ ] Keep `attempts/` separate from invocation metadata so the existing journal's strict JSON-name validation remains unchanged.
- [ ] Test exception and interruption paths, including an exception after receipt publication. Preserve evidence and record ambiguity; never rerun.
- [ ] Verify with focused synthetic tests, static checks and independent review, then commit the ready batch. No historical access during development.

## Task 2: Reviewed launch preparation

- [ ] After data delivery review, commit the reviewed calendar/configuration and manifest pins.
- [ ] After all implementation is merged, append the completing registration with the final code inventory and digest; preserve the original candidate registration.
- [ ] Prepare a concrete execution task naming the immutable revision, trial, data/output paths, runtime, disk requirements, one invocation command, error handling and result-event export procedure.
- [ ] Obtain required external review and any still-missing owner authorization for the local replay executor. Collection approval is not replay approval.
- [ ] Only then dispatch once. Inspect every terminal outcome and prepare the required trial result events through the separately reviewed exporter; do not mutate the canonical register inside the runtime checkout.

Current status: Task 1 is implemented with 26 passing synthetic tests, including
the isolated Python 3.12 bootstrap. Its external review and full CI remain pending.
The execution-task schema and reconciler interface above are implemented; the
concrete approved task, completing registration and historical replay are not.
