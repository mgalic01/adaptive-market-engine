# Separate local Codex reviewer

Owner requested event-driven, sceptical PR review on 2026-09-27. This integration
starts a separate local Codex worker; it does not resume Desktop or replace Cloud.
Its job is to challenge assumptions, inspect evidence, and discuss findings with
Claude and Bob. **There is no automatic merge function or merge flag.** A reviewing
agent must explicitly decide a merge after resolving discussion and satisfying the
standing review/check/owner rules. Green checks or a READY recommendation never merge.

## Delivery and review

GitHub sends signed JSON through a temporary Cloudflare HTTPS tunnel to a receiver
bound only to 127.0.0.1:8765. HMAC SHA-256 validates raw bytes before parsing. Repository
ID 1384347674 and name mgalic01/adaptive-market-engine are pinned. Sender allowlist:
owner mgalic01, GitHub Actions bot, Claude bot, Codex connector bot.

PR opened/synchronize/reopened/ready_for_review/closed/edited, created/edited/deleted
PR/inline comments, submitted/edited/dismissed reviews, and completed check-suite/workflow events identifying exactly one
PR can queue review. Other issues and arbitrary branch pushes do not. The receiver
ignores newly created marked worker comments; edits to old reports still queue review. Only event hashes and PR numbers enter SQLite.
There is no GitHub polling; the one-second loop checks the local queue.

Thirty quiet seconds coalesce activity for one PR. Maximum six starts/hour, 24/day,
1,000 pending events, 1 MiB/request. Failed starts consume budget. SQLite dedup survives
restart; an interrupted in-flight run is not automatically retried. An exclusive OS
lock prevents multiple service owners. HTTP connections have an absolute ten-second
lifetime and five-second inactivity timeout; this is not production DoS protection.

The controller fetches startup/rule documents at the captured base, immutable changed
files/diff, comments, reviews and checks from fixed GitHub endpoints. Tree metadata
screens all changed paths before content: only explicit source/test-code, workflow,
configuration and Markdown-document paths/types are allowed; data/dataset/fixture
components and unclassified paths are refused anywhere in the tree. This is a path/
type boundary, not a semantic detector for data disguised inside source or prose. The current base must be a verified ancestor of
the head within a 32-commit search, so the screened trees and three-dot diff agree.
Outdated/complex branches go to Desktop rather than risking access to unscreened data.
Truncated/oversized evidence fails closed; missing unchanged dependencies are a reason
for the reviewer to withhold a recommendation. No repository checkout/code execution.

The model receives evidence through stdin, treats GitHub text as untrusted, critically
assesses correctness/methodology/security and disagreements, and names limits/next
owners. It runs no tests: CI and other reviewers are third-party execution evidence.
The report names the exact head. A head/base change invalidates it; changed discussion or check/status evidence
is marked STALE. Publication rechecks open state/head and neutralizes mention and Bob task-command triggers. Oversized reports remain local;
publication rejects them rather than truncating findings.
GitHub cannot atomically check a comment/PR state and publish; the small remaining race
is acknowledged. There is no automatic retry after uncertain publication.

## Credentials and containment

Codex uses the PC's existing ChatGPT login/allowance. No OpenAI API key goes to GitHub.
A controller-only local GitHub token is required for review reads and publication,
avoiding the small anonymous REST allowance. The child environment
allowlist excludes that token and webhook secrets. User config/rules are ignored;
shell/apps/plugins/browser/image tools and code-mode execution are disabled, with
read-only sandbox and a neutral working directory. Some tool wrappers remain advertised
by the installed build; an actual dummy write was rejected because code-mode execution
was disabled. This is not proof of complete OS or same-user credential isolation.
The controller rejects all writes except POST to PR-comment endpoints, including a
request to the merge endpoint. No changes to branch protection are included.

## Start, inspect, stop

Use an owner-private directory outside git, e.g. `%LOCALAPPDATA%/AME-LocalWorker/state`,
with ACL restricted to the owner and SYSTEM. Generate a random secret of at least
32 bytes there; use its exact text in the GitHub webhook. Never log it or put it in git
or process arguments. Cloudflare terminates HTTPS and sees public repo webhook traffic.

```powershell
# Delivery test only, no model or publication:
python scripts/local_worker.py serve --state <private-state> --secret-file <private-secret>
# Add --run-worker to review, and --publish to post PR feedback.
python scripts/local_worker.py status --state <private-state>
cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate
```

For any review run (with or without publication), explicitly map the existing Windows User variable without printing
or persisting its value. Run from the reviewed deployment directory; use absolute
paths for Python, state and secret in an unattended launcher:

```powershell
$previousWorkerToken = $env:LOCAL_WORKER_GITHUB_TOKEN
try {
    $env:LOCAL_WORKER_GITHUB_TOKEN = [Environment]::GetEnvironmentVariable('Codex_token', 'User')
    if (-not $env:LOCAL_WORKER_GITHUB_TOKEN) { throw 'Codex_token is missing' }
    python scripts/local_worker.py serve --state <private-state> --secret-file <private-secret> --run-worker --publish
} finally {
    $env:LOCAL_WORKER_GITHUB_TOKEN = $previousWorkerToken
}
```

The token is available only to the controller process and excluded from the model's
child environment.
GitHub webhook: JSON, SSL verification on, configured secret, events listed above.
Use a reviewed immutable deployment copy; don't run unattended code from a branch
another agent is editing. No startup service or scheduled task is installed.

Local records: queue.sqlite and run-N/{result.json,report.md,failure.md}. Status shows pending
count and latest 20 outcomes. CLI deadline 180 seconds; each API client has a 90-second
request-start budget and bounded socket waits, not an overall wall-clock SLA. Errors
record phase/class, not raw exceptions/stdout/stderr that might contain secrets.

Stop the receiver/tunnel and disable only this integration's webhook. Temporary URL
changes on restart; PC sleep/stopped processes mean no deliveries. GitHub does not
automatically redeliver failed webhooks: explicitly redeliver after recovery or do the
ordinary check-in sweep.

For a failed/interrupted **review run** (different from a failed webhook delivery),
inspect status, its local report/failure and the current PR comments first. If posting
might have succeeded, identify that result before deciding whether another review is
needed. Then create one new PR Conversation comment, for example: "Codex local
reviewer: inspected run N and its publication outcome; please review this PR again."
That new signed event deliberately queues a new review under the normal budgets.
Redelivery of an already accepted body remains deduplicated, even after run failure;
it is not a retry command. No automatic uncertain-publication retry is introduced.

Stable named tunnel/startup supervision are later deployment
work, not a claim about this temporary test.

## Evidence and owners

The [indexed handoff](reviews/2026-09-27-codex-local-worker.md) records review and test
status. Receiver delivery, completed review, publication, and agent decision are
separate states. Claude/Bob review this implementation; Codex fixes findings and
reports activation. The owner expressly rejected a mechanical automatic merge gate.
