# V3 Durable Evidence Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, task by task.

**Goal:** Preserve every dispatched V3 attempt and its exact evidence through interruption.

**Architecture:** A local single-writer journal publishes immutable started and finished
JSON records. Started identity is durable before replay. A later adapter streams full
replay evidence and pins its digest in the finished record. Recovery lists unfinished
attempts; it never infers success or silently retries a historical run.

**Tech Stack:** Python standard library, JSON, Decimal text, SHA-256, flush/fsync.

**Spec:** docs/EXPERIMENT_SPEC_V3.md sections 8–9; orchestration.Attempt contract.

## Constraints

No historical dispatch, no reserved data, no new dependency. Preserve invalid,
failed and interrupted attempts. Never overwrite prior evidence. File fsync does
not establish a guarantee against every filesystem or power failure; test process
interruption and explicitly document platform limits.

## Task 1: Immutable local journal

- [x] Add evidence_journal.py with record(run_id, state, payload) and pending().
- [x] Test unsafe IDs, duplicate records, missing starts and interrupted starts.
- [x] Publish fully flushed temporary files atomically without replacing an existing
  destination. Reject malformed recovery records. Support exact Decimal strings;
  reject floats/nonfinite values rather than quietly rounding evidence.
- [x] Verify tests, lint and typing; record limitations and commit.

## Task 2: Replay evidence adapter

- [ ] Stream account state, events, fills, funding, lifecycle records, audits,
  decisions, equity path, samples and residuals into a separately hashed artifact.
- [x] Connect Attempt callbacks: start before replay; completed evidence before finish.
- [ ] Test invalid outcomes, corrupt evidence, serialization failures and termination.
- [ ] Recover unfinished attempts explicitly; do not auto-rerun historical work.

## Task 3: Reports and integration

- [ ] Add spot evidence and acceptance/report serializers with declared schemas.
- [ ] Confirm hashes and read-back metrics; review full artifacts before dispatch.
- [ ] Register reviewed code and data only after the existing owner/data gates clear.

Review focus: interrupted publication, duplicate concurrent names, Decimal fidelity,
orphan evidence, partial writes, unknown outcomes and bounded memory. Task 1 alone
is not a complete evidence writer or permission to run the experiment.
