# Codex → Claude/Bob: remove start caps and reuse two remote instances

Latest owner instruction, 2026-09-27: remove hourly/daily start caps, superseding the
earlier 40-start request, and reuse one reviewer implementation for two remote
instances. GitHub-hosted workers and two separately provisioned worker login sessions
in GitHub secrets are approved; active Desktop auth must not be copied. Failure
incident PRs and GitHub/chat/private-email notification remain requested.

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

Claude/Bob: review this code patch at its full SHA, then critique the proposed design.
Codex must not merge its own patch before that external review and passing checks.
Remote activation additionally needs approved design, auth provisioning and verified
notification delivery. No secrets or recipient address belong in the public design.

No new trading/security permissions are introduced by the limit patch. It increases
possible review spend by removing both application start caps, as the owner requested;
actual account quotas remain shared. Reverting the removal restores the ceilings without deleting state.
The offline regression validates code only; the stopped immutable deployment has not
been updated or restarted by this change.
