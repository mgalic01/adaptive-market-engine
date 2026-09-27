# Codex → Claude/Bob: remove start caps and reuse two remote instances

Latest owner instruction, 2026-09-27: remove hourly/daily start caps, superseding the
earlier 40-start request, and reuse one reviewer implementation for two remote
instances. GitHub-hosted workers and two separately provisioned worker login sessions
in GitHub secrets are approved; active Desktop auth must not be copied. Failure
incident PRs and GitHub/chat/private-email notification remain requested.

## Evidence checkpoint

- PR: [#120](https://github.com/mgalic01/adaptive-market-engine/pull/120),
  branch `codex/worker-budget-alerts`.
- Base: `5c79ad52f491ea1d0fc2f0344f1abc09de067744`.
- Initial cap-removal tested head: `3a85b4a10d0b33c4200e6f38e7dbd17a68b9652b`:
  41 Windows worker tests, Ruff/format and report checks passed.
- Final reviewed and tested head: `b60513c51167b3c71866917a557397b66816b4bb`.
  This adds executable containment tests and their workflow, not just documentation.
  Windows: 43 targeted tests. Linux: [2 CLI fixture tests passed](https://github.com/mgalic01/adaptive-market-engine/actions/runs/36346375070).
  Both test-and-audit runs, CodeQL and automated review passed at this head.
  [Bob's NO ISSUES](https://github.com/mgalic01/adaptive-market-engine/pull/120#issuecomment-5859343056)
  and [Claude's APPROVE](https://github.com/mgalic01/adaptive-market-engine/pull/120#issuecomment-5859369245)
  explicitly name this same full head. [Push handoff](https://github.com/mgalic01/adaptive-market-engine/pull/120#issuecomment-5859337528).
- Merge: `8a45cb540ce9a75153e16f7e23bb57efa9ea5fa7`. The review-before-merge gate was
  met for the final head; this post-merge correction makes the durable record explicit.

Cloud review at `0c6ed43a28ce094e0609aed25995b6056f481a6d` identified the missing
checkpoint and missing explicit remote credential-containment requirements. Both
are addressed in this revision. Its rolling-cap incident finding is superseded by
removing those caps; provider failures still need a durable incident lifecycle.
The unrelated SHA quoted in the first finding is not this PR's tested head.

## Implemented in this change

The existing queue no longer has hourly or daily start-count checks. Persisted history,
failed/completed outcomes, single active run, deduplication, quiet period, queue and
request/evidence bounds and no automatic merge remain unchanged. Current operational
docs match. The original local-worker design is historical, superseded on start caps.

A regression first failed at the old hourly boundary. It now verifies 81 starts in
less than one synthetic hour, alternating failed/completed outcomes and a restart at
start 40; all 81 remain recorded. All 41 worker tests pass on Windows Python 3.12.14; focused Ruff and diff
checks pass. No real model call, market-data access or workflow dispatch was used.

## What the stopped deployment actually did

Read-only inspection of local queue and GitHub comments: 24 starts total, 12 completed
and 12 failed. Latest three starts completed and published:

| Run | PR | Published result (UTC) |
| --- | --- | --- |
| 22 | #98 | [READY, 13:23:56](https://github.com/mgalic01/adaptive-market-engine/pull/98#issuecomment-5856247945) |
| 23 | #102 | [BLOCKED with substantive findings, 13:25:30](https://github.com/mgalic01/adaptive-market-engine/pull/102#issuecomment-5856258558) |
| 24 | #103 | [READY, 13:26:15](https://github.com/mgalic01/adaptive-market-engine/pull/103#issuecomment-5856263773) |

Runs 19–21 failed before a review could complete. At inspection the queue contained
567 pending events across 20 PRs, both receiver/tunnel processes were absent, and
GitHub deliveries returned HTTP 502. The cause of process termination is not yet
established. The 24-start cap explains why starts stopped earlier; it does not explain
why those processes later stopped. No queue history was reset.

## Design requiring review, not implemented

[Two GitHub-hosted workers and failure alerts](../superpowers/specs/2026-09-27-remote-review-workers-design.md)
describes the requested deployment, separate worker state, credential persistence,
duplicate-work avoidance, incident publication outside model budgets and delivery
tests. The owner selected workers independent of the PC and asked whether GitHub can
host them. The proposed answer is GitHub-hosted Actions with per-worker managed auth.
This is not a claim that two workers, email or Desktop wake-up already exist.

[Implementation plan](../superpowers/plans/2026-09-27-remote-review-workers.md)
turns that design into containment, durable-state, credential and delivery gates.
Public Codex CLI 0.157.1 on Windows accepted the existing isolation switches with
`exec --help`; this only verifies option parsing, not Linux tool containment or a
real authenticated review. It was installed in an isolated tooling directory with
package scripts disabled. No Desktop login was read or copied.

The final `b60513c` batch added `tests/test_remote_worker_containment.py` and a Linux-only
GitHub containment check using pinned public CLI 0.157.1, a locally simulated model
endpoint and dummy auth. On Windows both tests passed: six hostile tool requests
were rejected, the dummy auth did not appear in model traffic/output, configured MCP
startup did not happen, and a deliberately enabled-shell negative control exposed
the weakened tool boundary. This is a CLI fixture test with a synthetic model;
it does not prove operating-system isolation or all possible runtime configurations.
Normal pytest skips these two tests without `CODEX_TEST_EXECUTABLE`; the dedicated
job supplies it. No real Codex login, paid model call or remote reviewer is activated.

Claude/Bob: review this code patch at its full SHA, then critique the proposed design.
Codex must not merge its own patch before that external review and passing checks.
Remote activation additionally needs approved design, auth provisioning and verified
notification delivery. No secrets or recipient address belong in the public design.

No new trading/security permissions are introduced by the limit patch. It increases
possible review spend by removing both application start caps, as the owner requested;
actual account quotas remain shared. Reverting the removal restores the ceilings without deleting state.
The offline regression validates code only; the stopped immutable deployment has not
been updated or restarted by this change.
