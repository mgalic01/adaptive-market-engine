# Separate local sceptical reviewer design

Owner accepted a separate worker, GitHub events and a temporary tunnel on2026-09-27.
Owner clarified a critic and sceptic must examine/discuss work before an agent
explicitly decides any merge. No automatic merge controller or branch-policy change.

Python3.12 standard library: signed loopback HTTP receiver, SQLite queue, bounded
Codex CLI using local ChatGPT login. No OpenAI key in GitHub, no GitHub polling,
no desktop resumption. Operational bounds: docs/LOCAL_WORKER.md.

Authenticate raw bytes first; pin repo ID/name and sender allowlist; coalesce30 seconds,
one PR/run, six starts/hour,24/day,1,000 pending events. Durable body-hash dedup and
exclusive service lock; uncertain runs interrupted, never automatically retried.

Read immutable tree/commit metadata before content; verify base ancestry so screened
trees and three-dot comparison agree. Reject data changes before patches/blobs.
Supply base startup/rule docs, complete bounded changed files, discussions/checks.
Missing context means withhold recommendation. No repository checkout or execution.

Child shell/apps/browser/code-mode disabled; token environment excluded. Parent can
only read GitHub and post comments. No merge method/flag. Recheck head/base/discussions,
label stale findings, and recheck open/head immediately before comment. Residual
check/publication race is documented; no automatic retry of uncertain writes.

Temporary Cloudflare tunnel sees public repo webhook traffic; PC must remain awake.
No permanent service or availability claim. External Claude/Bob review and checks
precede unattended activation; supervised delivery probes/dummy tests are allowed.
Paper-only, protected profit and reserved-data restrictions remain.

Acceptance: signed GitHub event -> deduplicated queue -> critical review -> visible
feedback; unsigned rejection, safe failure/restart, bounded usage, no automatic merge.
