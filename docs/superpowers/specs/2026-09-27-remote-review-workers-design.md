# Two GitHub-hosted review workers and failure alerts — proposed design

Status: design for owner and Claude/Bob review, not deployed. The owner subsequently
removed the hourly/daily start caps, superseding 40/day, and approved two separately
provisioned worker logins in GitHub secrets. The patch removes the existing start caps.

## Requested outcome

Two named workers run independently of the owner's PC with no custom hourly/daily
start caps. Actual provider limits or operational failures open a visible incident
PR and alert the owner and other agents. The owner requested GitHub,
the current Codex chat, and email; the private recipient address is kept out of this
public document and supplied through deployment configuration.

Workers remain critical reviewers, not automatic mergers. They preserve paper-only,
reserved-data restrictions, protected-profit accounting and external review rules.
Two workers on one ChatGPT account share its actual allowance; removing our start
caps does not create separate subscription quotas or bypass provider limits.

## Hosting choices

1. **GitHub-hosted Actions jobs — proposed for this request.** No PC/tunnel or rented
   server. Work is event-driven and visible in Actions. Each job is ephemeral, so
   queue state and refreshed authentication must survive outside the runner.
2. **Two persistent remote runners.** Easier authentication persistence, but require
   hosting, OS maintenance and uptime monitoring. Not assumed purchased or available.
3. **Existing Codex Cloud reviews.** Useful additional evidence, but do not expose the
   custom incident controls needed here. They do not implement
   this design merely because they are already enabled.

The recommendation is option 1, conditional on secure authentication provisioning
and end-to-end delivery tests. Nothing copies the current Desktop login automatically.

## Processing and state

- Identities `codex-worker-1` and `codex-worker-2`, running the same reviewed logic
  with separate state and authentication. No hourly or daily start-count ceilings.
- A trusted controller reads authenticated GitHub events, applies existing repo/sender
  checks and coalesces related PR events. It loads code only from reviewed default-branch
  revisions. It never checks out or executes PR code with credentials available.
- Each meaningful captured PR head/base/evidence revision is assigned once to an
  available worker. A fresh substantive discussion can justify another review, but
  the workers' own receipts and failure incidents must not trigger review loops.
- A dedicated `automation/codex-worker-state` branch holds only non-secret queue,
  claims, run and delivery metadata. Reserve work atomically before model execution;
  use compare-and-swap updates/retries, not a runner-local file or evictable cache as
  the authoritative state. Lost/corrupt state fails closed and raises an incident.
  This repository is public: this branch is public too, not a secrets store.
  Persist IDs, hashes, timestamps, states and public GitHub links only; never raw
  payloads, model transcripts, environment variables, recipient addresses or auth.
- Claims have owners and recoverable leases. Cancellation before/after reservation,
  crash recovery and publication uncertainty need explicit states. A failed start
  remains recorded; separately report model starts versus pre-model failures.
- Preserve queued work while provider allowance is exhausted. Use a reconciliation path for
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

Carry forward `local_worker.command()` and `child_environment()` as mandatory
containment: neutral temporary working directory, no PR checkout, no inherited user
configuration/rules, strict configuration, disabled shell, apps, browser, computer,
plugins, skills, web, code execution and subagent tools, and an explicit child
environment allowlist. Read-only filesystem mode alone is not credential isolation.
Use an empty per-job HOME and a worker-specific CODEX_HOME; only the CLI auth runtime
may use the restored session. No GitHub/storage/mail credential enters the model
process environment. Never offer the model a file-read or outbound tool that could
reach the session. Pin and validate the Linux CLI's actual supported controls before
activation; a missing control is a deployment failure, not a reason to drop a flag.
An adversarial test with dummy auth must attempt file reads, shell/browser/app calls,
config/MCP loading and exfiltration, and show no such tool executes. Do not infer
containment solely from a benign review's output or from source string assertions.

The model sees only bounded evidence and no GitHub write credential. The trusted
publisher retains comment-only operations. A separate non-model incident controller
gets narrowly scoped permission to create an incident branch/file/PR; it cannot merge
or edit workflows. Do not widen the reviewer's existing write allowlist for alerts.
Credential refresh write-back needs separately reviewed storage permission; no provider
OAuth endpoint is called directly and no OpenAI API key is required by this proposal.

Use two GitHub environments, `codex-worker-1` and `codex-worker-2`, restricted to
reviewed `main`. Each holds its own `CODEX_AUTH_JSON`; jobs for each identity are
serialized before environment secrets are loaded. The latest rotated login must be
saved back before releasing the worker. A narrowly scoped, separately provisioned
GitHub credential is needed for this write-back; the job's normal `GITHUB_TOKEN`
must not be assumed to have environment-secret administration permission. The owner
has approved worker-login storage, not copying Desktop credentials or the existing
local GitHub token. Codex specifies and Claude/Bob review the storage permission;
the owner provisions it through secure setup. If rotation persistence is uncertain,
disable that identity and raise an incident rather than reuse a stale login.

## Failure incident and notification contract

- Detect actual provider-quota/authentication/operational failures. Queue one durable
  incident per failure episode without requiring another model call. The earlier
  40-start incident is superseded because that application limit no longer exists.
- Open a documentation-only incident PR containing worker ID, usage, known reset time,
  pending work, failed/completed counts and recovery owner. Reconcile existing branch
  and PR after ambiguous publication; do not generate duplicate incident PRs.
- Keep a durable incident ID and status per worker/failure class. The controller
  atomically latches the first failure, creates a deterministic incident branch and
  reconciles its PR before any retry. Repeated failures update that episode. Only a
  confirmed successful recovery closes it; elapsed time, a guessed quota reset or
  one new queued job does not re-arm notifications. Test simultaneous detection,
  cancellation after PR creation and failure again before/after confirmed recovery.
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
  must work with provider allowance exhausted, missing model auth or model failures.
  GitHub/email outages can delay delivery; 'immediate' means enqueue/attempt upon
  detection, not an impossible guarantee of instant receipt across unavailable services.
- Emit visible failures for authentication, queue corruption, repeated collection
  errors and unavailable workers as well as provider limits. A remote health check
  must detect a dead controller; a dead process cannot reliably announce its own death.

## Required acceptance tests before activation

1. Both instances reuse the same code without hourly/daily caps and have independent
   authentication/state. Restart preserves history and single-run serialization.
2. Concurrent jobs, duplicates and cancellations do not duplicate reviews, drop queued work
   or publish duplicate results. Worker-generated events cannot create a feedback loop.
3. Dummy-auth tests prove secrets are absent from model input, logs and artifacts;
   refresh state persists per worker. Include the adversarial containment test above
   on the pinned Linux CLI. Never test with real tokens in fixtures.
4. Synthetic provider-quota failure creates exactly one real test incident PR, with the
   owner's authorization, even when no Codex call can run. Verify email receipt,
   agent request delivery and Desktop notification separately; receipt is not review.
5. Stop one worker and the PC: the other remote worker continues;
   outstanding work and recovery states remain visible. Test total GitHub outage as
   delayed recovery, not as guaranteed uptime.
6. No automatic merge, task-file creation, paid Bob task dispatch, market-data fetch,
   reserved-data access or trading operation is part of these tests.

## Next decisions and implementation boundary

Owner approved separate worker logins in GitHub secrets; provision each separately
when ready and configure an email sender without pasting credentials into chat.
The current Desktop session is not authorized for copying. Confirm a Desktop heartbeat
as a fallback if notification here is required.
Claude/Bob: critique credential isolation, state/claim races, incident loops and failure
recovery. Codex: write the implementation plan after design review, implement/test it,
request external review and activate only after checks and delivery tests pass.

The start-cap removal does not itself deploy either remote worker, restore the stopped
local service, implement incident PRs or deliver email. Existing queue history must
not be deleted or reset to manufacture capacity.

Sources checked 2026-09-27:
- [GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners)
- [Codex account authentication in CI/CD](https://learn.chatgpt.com/docs/auth/ci-cd-auth)
- [GitHub workflow notifications](https://docs.github.com/en/actions/concepts/workflows-and-actions/notifications-for-workflow-runs)
- [When GitHub reads secrets](https://docs.github.com/en/actions/reference/security/secrets#when-github-actions-reads-secrets)
- [Environment secret permissions](https://docs.github.com/en/rest/actions/secrets#create-or-update-an-environment-secret)
