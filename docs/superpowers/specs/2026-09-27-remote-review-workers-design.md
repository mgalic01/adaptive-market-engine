# Two GitHub-hosted review workers and budget alerts — proposed design

Status: design for owner and Claude/Bob review, not deployed. The same PR changes
the existing local worker's rolling daily start limit to the owner-requested 40.

## Requested outcome

Two named workers run independently of the owner's PC, each with a separate limit
of 40 review starts per rolling 24 hours. Reaching either limit opens a visible
incident PR and alerts the owner and the other agents. The owner requested GitHub,
the current Codex chat, and email; the private recipient address is kept out of this
public document and supplied through deployment configuration.

Workers remain critical reviewers, not automatic mergers. They preserve paper-only,
reserved-data restrictions, protected-profit accounting and external review rules.
Two workers on one ChatGPT account share the account's actual allowance: independent
local counters do not create separate subscription quotas or bypass provider limits.

## Hosting choices

1. **GitHub-hosted Actions jobs — proposed for this request.** No PC/tunnel or rented
   server. Work is event-driven and visible in Actions. Each job is ephemeral, so
   counters, queue state and refreshed authentication must survive outside the runner.
2. **Two persistent remote runners.** Easier authentication persistence, but require
   hosting, OS maintenance and uptime monitoring. Not assumed purchased or available.
3. **Existing Codex Cloud reviews.** Useful additional evidence, but do not expose the
   custom per-worker counters and incident controls needed here. They do not implement
   this design merely because they are already enabled.

The recommendation is option 1, conditional on secure authentication provisioning
and end-to-end delivery tests. Nothing copies the current Desktop login automatically.

## Processing and state

- Identities `codex-worker-1` and `codex-worker-2`; separate rolling 24-hour ledgers,
  40 starts each, retaining six starts/hour per worker unless the owner changes it.
- A trusted controller reads authenticated GitHub events, applies existing repo/sender
  checks and coalesces related PR events. It loads code only from reviewed default-branch
  revisions. It never checks out or executes PR code with credentials available.
- Each meaningful captured PR head/base/evidence revision is assigned once to an
  available worker. A fresh substantive discussion can justify another review, but
  the workers' own receipts and budget incidents must not trigger review loops.
- A private-state or tightly controlled state branch holds only non-secret queue,
  claims, budget and delivery metadata. Reserve a start atomically before model work;
  use compare-and-swap updates/retries, not a runner-local file or evictable cache as
  the authoritative budget. Lost/corrupt state fails closed and raises an incident.
- Claims have owners and recoverable leases. Cancellation before/after reservation,
  crash recovery and publication uncertainty need explicit states. A failed start
  still consumes budget; separately report model starts versus pre-model failures.
- Preserve queued work while budgets are exhausted. Use a reconciliation path for
  missed events/canceled workflow jobs without repeatedly reviewing unchanged PRs.
- Every output names worker, full head/base, evidence limits, findings and next owner.
  Shared checks never substitute for critical review. Publishing rechecks current
  state; a final check/comment race remains disclosed.

## Authentication and permissions

OpenAI documents ChatGPT-managed auth on ephemeral CI: restore the latest session,
run Codex, then securely persist refreshed credentials. It requires one session per
runner or serialized stream, and forbids sharing it concurrently across machines.
Use two separately provisioned sessions, isolated from Desktop and each other.
Credentials stay in protected secrets storage, never Git, logs, caches or artifacts.

The model sees only bounded evidence and no GitHub write credential. The trusted
publisher retains comment-only operations. A separate non-model incident controller
gets narrowly scoped permission to create an incident branch/file/PR; it cannot merge
or edit workflows. Do not widen the reviewer's existing write allowlist for alerts.
Credential refresh write-back needs separately reviewed storage permission; no provider
OAuth endpoint is called directly and no OpenAI API key is required by this proposal.

## Limit incident and notification contract

- Detect the transition to 40 reserved starts, without waiting for a 41st request.
  Queue one durable incident per worker/budget episode, outside model budgets.
- Open a documentation-only incident PR containing worker ID, usage, reset time,
  pending work, failed/completed counts and recovery owner. Reconcile existing branch
  and PR after ambiguous publication; do not generate duplicate incident PRs.
- A single incident links all delivery states. Notify Claude/Bob on that open PR and
  request they surface it in their active owner conversations. Trigger at most one
  authorized notification request per agent; do not create reciprocal mention loops.
- Send email through a configured, verified delivery service. GitHub notification
  email can supplement it but is not a guaranteed substitute: recipients/settings
  and which actor triggered a workflow affect delivery. Confirm receipt in a test.
- The current Desktop chat has no webhook ingress in this deployment. A separately
  configured app heartbeat can inspect incident state and surface it here when the app
  is available; it is not an instant remote wake-up guarantee. A closed/offline app or
  quota-limited agent cannot be promised to respond. Record pending acknowledgment
  instead of claiming all agents/all channels were notified.
- Retry failed notification delivery with bounded backoff and idempotency. Alerting
  must work with both model budgets exhausted, missing model auth or model failures.
  GitHub/email outages can delay delivery; 'immediate' means enqueue/attempt upon
  detection, not an impossible guarantee of instant receipt across unavailable services.
- Emit visible failures for authentication, queue corruption, repeated collection
  errors and unavailable workers as well as budget exhaustion. A remote health check
  must detect a dead controller; a dead process cannot reliably announce its own death.

## Required acceptance tests before activation

1. Each worker permits exactly 40 starts, blocks 41, survives restart and releases
   capacity at the rolling-window boundary; one worker cannot spend the other's budget.
2. Concurrent jobs, duplicates and cancellations do not overspend, drop queued work
   or publish duplicate results. Worker-generated events cannot create a feedback loop.
3. Dummy-auth tests prove secrets are absent from model input, logs and artifacts;
   refresh state persists per worker. Never test with real tokens in fixtures.
4. Synthetic limit transition creates exactly one real test incident PR, with the
   owner's authorization, even when no Codex call can run. Verify email receipt,
   agent request delivery and Desktop notification separately; receipt is not review.
5. Stop one worker and the PC: the other remote worker continues within its own cap;
   outstanding work and recovery states remain visible. Test total GitHub outage as
   delayed recovery, not as guaranteed uptime.
6. No automatic merge, task-file creation, paid Bob task dispatch, market-data fetch,
   reserved-data access or trading operation is part of these tests.

## Next decisions and implementation boundary

Owner: approve the GitHub-hosted design and secret-storage location; separately log in
each worker when ready, and configure an email sender without pasting credentials into
chat. Confirm a Desktop heartbeat as a fallback if notification here is required.
Claude/Bob: critique credential isolation, state/claim races, incident loops and failure
recovery. Codex: write the implementation plan after design review, implement/test it,
request external review and activate only after checks and delivery tests pass.

The 40-start patch does not itself deploy either remote worker, restore the stopped
local service, implement incident PRs or deliver email. Existing queue history must
not be deleted or reset to manufacture capacity.

Sources checked 2026-09-27:
- [GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
- [Codex account authentication in CI/CD](https://learn.chatgpt.com/docs/auth/ci-cd-auth)
- [GitHub workflow notifications](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)
