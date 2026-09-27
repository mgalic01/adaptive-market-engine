# Separate local Codex worker

This opt-in integration receives GitHub webhooks and starts a separate local Codex
reviewer. It does **not** resume the owner's desktop chat or replace Cloud reviews.
The owner authorized event-driven reviews and merges when all gates pass on
2026-09-27, and chose a temporary tunnel for the first test.

## What runs

`scripts/local_worker.py` binds `127.0.0.1:8765`. Cloudflare supplies a temporary HTTPS
endpoint; GitHub sends signed JSON to `/github`. The receiver checks the HMAC before
parsing, pins repository ID **1384347674** and name **mgalic01/adaptive-market-engine**,
and accepts only the owner, GitHub Actions, Claude bot and Codex connector as senders.
It stores body hashes and PR numbers in SQLite, not webhook text. There is no GitHub
polling: the one-second loop checks the **local queue** only.

Events: PR opened/synchronize/reopened/ready_for_review/closed, created PR comments
and inline comments, submitted reviews, completed check suites and workflow runs
that identify exactly one PR. Other issues, draft edits, arbitrary branch pushes,
and check events without a unique PR do not start work. A synchronize event covers
pushes to an open PR. The worker's own marked comments are ignored to avoid loops.

After 30 quiet seconds for that PR, one process claims one review. Maximum six starts
per hour and 24 per day, including failed starts. Pending events wait locally when
budget is exhausted. A crash marks an in-flight run interrupted on restart and never
automatically retries it. Duplicate signed bodies remain suppressed after restart.
The queue rejects more than 1,000 outstanding events; requests over 1 MiB are refused.

The controller fetches GitHub evidence using fixed HTTPS endpoints. It checks tree
metadata before fetching changed data-file content, supplies bounded complete changed
files and patches, and refuses oversized/truncated collections. Repository code is
never checked out or executed. Codex receives GitHub text as untrusted evidence via
stdin, uses local ChatGPT login and a neutral directory, ignores user config/rules,
disables shell/apps/plugins/browser/image tools, and uses read-only mode. Code-mode
execution is disabled as an additional control. This is not a claim that every tool
name disappears: the installed build still advertises some tool wrappers; an actual
negative write probe was rejected with `code-mode host is disabled`.

No OpenAI API key is created or sent to GitHub. Codex uses the local ChatGPT allowance.
The controller may use the owner's local GitHub token for API reads/comments/merges;
the child process receives an environment allowlist that excludes tokens and webhook
secrets. Windows same-user processes are not an OS credential-isolation boundary.
Do not configure project-specific MCP servers or hooks into this worker.

## What permits a merge

Codex must return READY at the exact head after critically reading the supplied
evidence. The controller independently requires all of these:

- Open, non-draft, same-repository PR into main, clean GitHub merge state.
- Complete bounded patch/context, and an indexed durable handoff among changed files.
- Substantive Bob `NO ISSUES` with SCOPE at the full head, and automated Claude
  `APPROVE` explicitly identifying that reviewed head. Later malformed or negative
  output from those reviewers invalidates the earlier verdict. Human Claude feedback
  is read as evidence but does not satisfy the machine-parsed gate.
- Successful `test-and-audit`, every returned check/status successful, no pending
  checks, no changes-requested review, no current-head inline findings. Inline
  resolution is conservatively left to Desktop, even if GitHub shows it resolved.
- Strict required `test-and-audit` protection on main, enforced for administrators.
  This closes the base-advance race at the merge API. Unknown/missing protection
  blocks unattended merging. Equivalent rulesets are not yet recognized.
- No task/config/data/spec changes or renamed former protected paths; no proposal
  or agreement PR title. These are escalated for Desktop/owner coordination.
- Head/base and relevant discussions unchanged through review and final recheck.
  GitHub's merge endpoint receives the expected head SHA; no bypass option is used.

The model cannot override these gates. CI provides execution evidence; the model
does not independently run tests. Reading supplied files cannot establish correctness
of every unchanged dependency: the reviewer must block when it needs more context.
There is an unavoidable small window for a new comment after the last API read;
GitHub does not offer transactional comment/merge checks. Strict CI protection and
head CAS do not eliminate that discussion race. Do not describe it as atomic.

The worker publishes a marked review comment only on an open PR. After a merge it
records the merge SHA locally first, then opens a focused Claude handoff issue, never
comments on the closed PR. Publication failure is recorded as failure and must be
reconciled against GitHub before retry. No automatic retry of uncertain writes.

## Operation on this PC

Use an owner-private directory outside the repository, for example
`%LOCALAPPDATA%/AME-LocalWorker/state`. Restrict its ACL to the owner and SYSTEM.
Generate a random secret of at least 32 bytes there; use its exact text as the GitHub
webhook secret. Never put it in git, shell command arguments, comments or logs.

```powershell
# Receiver only: safe initial delivery test; no Codex launches or GitHub writes.
python scripts/local_worker.py serve --state <private-state> --secret-file <private-secret>
# Add --run-worker for local review reports; --publish for visible PR feedback.
# Add --allow-merge only after external review and server-side protection verification.
python scripts/local_worker.py status --state <private-state>
```

When publishing, the launcher reads the existing User variable `Codex_token` into
the receiver process as `LOCAL_WORKER_GITHUB_TOKEN`; no value is printed or persisted
by the integration. Stop restores no global variables because none are changed.

Tunnel command (verified Cloudflare binary):

```powershell
cloudflared tunnel --url http://127.0.0.1:8765 --no-autoupdate
```

Configure a repository webhook with content type JSON, SSL verification enabled,
the random secret, and the listed event types. Temporary tunnels terminate HTTPS at
Cloudflare, which sees the public repository webhook content. Expose only this
receiver, never Codex App Server, a shell, or a filesystem server.

Run state: `queue.sqlite`, `run-N/result.json`, `run-N/report.md`, and `merge.json`
when a merge happened. `status` shows pending count and the last 20 outcomes.
Keep reports local unless deliberately reviewed for publication. No raw stdout or
stderr streams are logged. Failures identify phase/class, not potentially secret
exception text. The CLI has a 180-second deadline; each GitHub client has a 90-second
request-start budget and bounded socket waits. This is not a single wall-clock SLA.

Stop receiver and tunnel, then disable/delete **only this integration's webhook**.
No startup service or scheduled task is installed. PC sleep or stopped processes
means no delivery; GitHub does not automatically redeliver failed webhooks. Redeliver
explicitly in GitHub after recovery or perform the ordinary session-start sweep.
Temporary URLs change on restart; update the webhook endpoint before relying on it.
A stable named tunnel/domain and supervised startup remain a later deployment step.

## Verification and next owners

See the [indexed handoff](reviews/2026-09-27-codex-local-worker.md) for the actual
pushed head, verification limits and activation status. A merged implementation is
not proof the receiver is running. Claude/Bob must review the exact implementation
head before Codex merges its own integration.
