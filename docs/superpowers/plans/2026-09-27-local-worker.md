# Local worker implementation plan

Goal: GitHub event delivery starts bounded local Codex triage without an OpenAI API key.
Spec: [design](../specs/2026-09-27-local-worker-design.md).
Writer: Codex Desktop, branch `codex/github-local-worker`, isolated sibling worktree
`work/github-local-worker`, base `bb76659c1eb12348cde75d9aa42aef3c4afa5538`.
Architecture: receiver/queue and worker modules under `scripts/`; standard library.

## Constraints and review focus

Read-only triage, no market access, no trading, no publication from the worker.
Retain body-hash dedup across restarts; never execute payload text. Validate malformed
JSON structures, fail closed on capacity/crash, serialize starts, count failed starts
against budget, and prove subprocess arguments do not load user/project integrations.

## Tasks

- [ ] Add `tests/test_local_worker.py` with signature/tamper/schema/event/allowlist,
  queue restart/concurrency/debounce/budget and HTTP boundary cases. Run red.
- [ ] Implement `scripts/local_worker_queue.py`: validate bytes into an optional
  integer PR number; persist deduplicated events and atomically claim bounded batches.
- [ ] Implement `scripts/local_worker.py`: loopback HTTP receiver, exclusive service
  lock, fixed public API reads, isolated CLI invocation, status and report output.
- [ ] Exercise dummy worker success/error/timeout and real local HTTP requests;
  run repository lint, format, mypy, Bandit and appropriate tests.
- [ ] Add operations guide, quick-reference entry and indexed Claude handoff; inspect
  whole diff, push one review batch and request Bob's substantive exact-head review.
- [ ] Once review/checks pass, test a temporary tunnel and signed GitHub delivery,
  prove a real bounded CLI report, record observed state and teardown/restart limits.

Native implementation in this session; independent final review supplements the
required Claude/Bob review. No changes to another agent's branch.
