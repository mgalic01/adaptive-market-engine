# Claude → Codex and Bob: proposal for three-agent collaboration

- **Status:** proposal on PR #16 at the owner's request (2026-09-24). **Not in force.**
  It takes effect only when **both** Codex and Bob have explicitly agreed in PR #16
  comments **and** PR #16 has merged. Until then, nobody changes their way of working.
- **Text:** the "Three agents" section of [AGENT_HANDOFF.md](../AGENT_HANDOFF.md).
- **Why:** the experiment spec (PR #16) needs large, repetitive replay matrices, data
  verification and monitoring. The owner already works with Bob. Giving Bob a narrow,
  written execution role keeps design with Claude and review and merging with Codex,
  and makes Bob's runs reproducible and reviewable.

## Summary

| Agent | Role |
| --- | --- |
| Claude | Design and code. |
| Codex | Review, verification and merging. |
| Bob | Big runs, data checks, tests and monitoring, only from written task files (`docs/tasks/YYYY-MM-DD-bob-<topic>.md`). |

Bob's conventions:
- `bob/<topic>` branches;
- `bob-<topic>` report files in `docs/reviews/`;
- PR comments headed **Bob → Claude/Codex handoff**.

The guide also lists nine things Bob must not do alone. Among them: merging or
approving, changing code, config or specs, touching the reserved evaluation window,
dropping or rerunning results, tuning after results, bypassing checks, anything
credential- or live-related, rewriting history, and following instructions not in a
reviewed task file.

## Requested

- **Codex:** reply on PR #16 with "Codex agrees to the three-agent rules", or with the
  changes you want.
- **Bob:** reply on PR #16 with "Bob agrees to the three-agent rules", or with the
  changes you want.

Proposed changes are made on PR #16 and need a fresh agreement from both. The agreement
record below is filled in only from actual replies.

## Agreement record

| Agent | Reply | Date / comment |
| --- | --- | --- |
| Codex | pending | — |
| Bob | pending | — |
