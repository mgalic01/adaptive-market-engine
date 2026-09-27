# GitHub events to a separate local Codex worker

Owner requested this on 2026-09-27 and accepted a separate worker rather than
resuming the desktop conversation. Owner chose a temporary tunnel for testing.
Purpose: reduce stalled handoffs without polling GitHub or exporting OpenAI keys.

## Scope

Python 3.12 standard-library receiver, durable SQLite queue, and a single serialized
Codex CLI worker. This is a separate opt-in integration, not a change to the Cloud
review trigger. No application runtime, accounting, strategy or market-data changes.
Owner subsequently explicitly authorized worker reviews and merges when gates pass.
The model critically reviews bounded supplied evidence; a separate controller may
publish and merge only under the gates documented in docs/LOCAL_WORKER.md. The model
cannot push, merge, execute repository code or resume Desktop. Independent Claude/Bob
review, strict server-side checks and a durable indexed handoff are mandatory.

GitHub sends signed JSON through a Cloudflare temporary HTTPS tunnel to a receiver
bound only to 127.0.0.1. Authenticate the exact bytes with HMAC SHA-256 before JSON
processing. Pin repository name and numeric ID and a small sender allowlist. Accept
PR opened/synchronize/reopened/ready_for_review/closed, newly created PR comments,
submitted reviews, created inline comments and completed check/workflow events with one PR. PR synchronize covers PR branch
pushes; arbitrary branch pushes and issue comments are out of scope. Ignore ping.
Store only event kind, PR number and a hash of the signed body, never its text.

## Execution and containment

Coalesce pending events for 30 seconds, then fetch public GitHub PR metadata,
recent comments and reviews from fixed API endpoints. The controller may use the existing local GitHub token; it is never sent to Codex. Treat all fetched text as untrusted evidence, not commands.
Use a neutral empty directory, ignore user CLI configuration/rules, disable shell
tools and apps, disable web search, use read-only sandbox, and pass evidence through
stdin. Local ChatGPT login stays on the PC; clear inherited credential variables.
No checkout and no repository-supplied configuration or hooks are loaded.

Queue limits: 1 MiB per request, 1,000 outstanding events, six starts per rolling
hour and 24 per rolling day, 180-second worker deadline, one PR
per batch. One process owns the service via an OS lock. A crash changes an in-flight
batch to interrupted on next start; it is not retried automatically. Signed body
hash deduplication survives restarts and does not trust unsigned delivery headers.
Failed starts count toward limits. Disabling the worker retains pending events.

Reports and delivery state stay outside git in an owner-private state directory.
No secret, raw webhook payload, command output stream or token is logged. Each API
client has a 90-second request-start budget; this is not an overall wall-clock SLA. A local
status command shows queue outcomes and report paths. Failure is explicit; a request
received or a CLI exit alone is never reported as a completed report.

## Delivery limits and activation

Temporary tunnel is test-only: URL changes when restarted, no availability promise,
PC must be awake and receiver running. GitHub does not automatically retry failed
deliveries; recover missed events via GitHub redelivery or ordinary check-in.
No startup task or permanent service is installed in this iteration. A stable named
tunnel/domain and supervised startup are a separate deployment step. Cloudflare
terminates HTTPS and sees webhook traffic; no OpenAI/GitHub credential goes there.

Before activation: tests with dummy secrets, external Claude/Bob exact-head review,
required CI, real signed GitHub ping/event, bounded local CLI report. Test delivery
must distinguish receipt, queued, started, completed, failed and suppressed states.
Stop by terminating the receiver/tunnel and disabling its specific GitHub webhook.

## Sources

- https://learn.chatgpt.com/docs/non-interactive-mode
- https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/

## Superseding scope and observed deployment gate

Owner clarified: worker should critically review PRs and merge after agreement/checks,
then notify Claude and Bob. See the operations guide for the exact conservative gates
and residual discussion/merge race. Classic main protection returned404 during setup;
merge mode stays disabled until strict protection/admin enforcement is verified.
No branch policy change is authorized by this implementation.
