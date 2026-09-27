# Codex → Claude handoff: separate local GitHub worker

Date: 2026-09-27. Named writer: Codex Desktop. Branch: `codex/github-local-worker`.
Worktree: `work/github-local-worker`. Base: `bb76659c1eb12348cde75d9aa42aef3c4afa5538`.
Exact pushed head is recorded in the PR Conversation handoff (this file cannot embed
its own commit SHA). Status: implementation under review; not production activated.

## Owner request and purpose

Owner asked for a separate event integration after the desktop resume probe failed,
accepted a separate worker and temporary tunnel, and explicitly directed that the
worker critically assess PRs and merge once agreement/checks pass. Owner also asked
that Claude and Bob be notified. This reduces handoffs waiting for a manual Desktop
check-in; it does not change the market experiment or its acceptance criteria.

The earlier prohibition on adding a relay applied to the existing Cloud-review
protocol. This separately requested opt-in integration does not replace that protocol
or authorize OpenAI API keys in GitHub. It does not wake the existing Desktop chat.

## Implementation and limitations

See [operations and merge gates](../LOCAL_WORKER.md). Three standard-library scripts:
authenticated receiver/durable queue, bounded Codex subprocess, deterministic GitHub
controller. No bot runtime/accounting/protected-profit changes, no reserved-window
access, no strategy implementation/freeze, no Bob task file or new GitHub workflow.

Substantive Bob and automated Claude verdicts at the exact head are both required by
the unattended controller. Unknown/malformed later verdicts invalidate earlier ones.
No own-work exception, no bypass, no self-review-as-approval. Indexed handoff and
successful checks required. Owner-gated/proposal changes remain with Desktop.

**Deployment blocker:** reading classic `branches/main/protection` using the owner's
local credential returned 404. No classic strict protection was verified. Therefore
unattended merges must remain disabled unless strict checks/admin enforcement are
verified. Do not silently change branch policy. Review-only operation is possible.

Security review found and corrected: Bob FLAGGED suffix parsing, stale discussions,
missing full-file evidence, ambiguous Claude head binding, base/check race via strict
server-side gate, renamed protected paths, and pre-content data scope screening.
The remaining comment/merge race is explicit in the operations guide; GitHub offers
no atomic comment-and-merge operation. Same-user local processes are not a credential
isolation boundary. CLI advertised tool wrappers remain even with features disabled;
an actual attempted dummy write was blocked by disabled code-mode execution.

## Verification evidence

- Baseline Windows Python 3.12 suite passed before implementation.
- Test-first receiver/queue tests initially failed for absent implementation, then
  passed. HTTP tests use real loopback requests and dummy secrets, never paid jobs.
- Targeted tests cover authentication/tampering, malformed JSON, pinned repo/sender,
  event selection, dedup/restart/debounce/capacity/budget, interrupted runs, isolated
  child environment/argv, missing outputs, stale/negative reviewer results, protection
  gates, renamed paths, partial patches, data metadata screening and discussion drift.
- Local CLI login reports ChatGPT. A bounded real CLI probe returned a structured
  diagnostic; a negative dummy-write probe left no file and reported
  `code-mode host is disabled`. No repository code or market commands were run.
- Cloudflare 2026.9.3 Windows amd64 binary downloaded from the official release and
  checked against its published SHA-256
  `f096265ec2fcbe9bb6e2d64268db167ced3fcbb83d894bdb9e2fcdb26f2ea7e2`.
- Final test counts/checks and actual GitHub delivery evidence belong in the PR
  handoff. No claim of production availability, successful unattended merge, complete
  sandbox isolation, or permanent-tunnel recovery is made here.

## Review request and next owners

Bob: review queue/signature boundaries, credential separation, stale or negative
verdict handling and fail-closed merges. Automated Claude is independent additional
review. Claude session: assess whether these bounded reviews and narrow merge gates
fit the project and coordinate the unresolved strict-protection deployment decision.
Codex Desktop: fix blockers, verify checks, then complete temporary delivery testing
and report activation state. Preserve other agents' branches.

Every actual merge must create its visible Claude handoff with exact merge SHA and
limits on an open follow-up issue. Revert this integration through a reviewed PR;
stop local processes and disable its one webhook independently of code rollback.
