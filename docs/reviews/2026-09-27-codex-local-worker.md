# Codex → Claude handoff: separate local sceptical reviewer

2026-09-27. Writer Codex Desktop; branch codex/github-local-worker; isolated worktree
work/github-local-worker. Base bb76659c1eb12348cde75d9aa42aef3c4afa5538. Exact revised
head and check evidence are recorded in PR #94's Conversation. Activation is not
claimed until explicitly recorded there.

## Owner intent and correction

Owner requested GitHub events to start a separate worker without OpenAI keys in
GitHub, and chose a temporary tunnel. The role is a **critic and sceptic**: assess
work, challenge assumptions, resolve discussion with Claude/Bob, then an agent makes
an explicit merge decision. Owner rejected mechanical automatic merging. The first
implementation over-interpreted an earlier selection: that merge controller, launch
flag, verdict parser and protection proposal are now removed. No branch-protection
setting was changed. The controller rejects merge API writes.

See [operations](../LOCAL_WORKER.md). This is separate from Cloud reviews and does
not resume Desktop. Current base rules, immutable diff/full files and discussion/CI
are supplied to a bounded local reviewer. Model output alone is not merge authority.
No strategy/runtime/accounting change, data download/replay or specification freeze.

## Verification and security

- Initial test-first authentication/queue/HTTP tests failed before implementation,
  then passed. Tests use dummy secrets and no paid Bob jobs or real merges.
- Windows full suite at initial c7c00852e011a1fc6521c38bbf6db47651e6f106:
  417 passed, 2 skipped, 563 subtests. Linux CI found platform-specific mypy stubs;
  corrected using platform-safe lookup/imports and linux/win32 mypy verification.
- Queue regressions cover persistent dedup/budgets/capacity, interrupted runs,
  explicit connection closure/rollback and exclusive service lock.
- Review corrections: immutable comparison/full-file coverage, verified base ancestry
  before content, data metadata screening, head/base/discussion freshness, open/head
  recheck before comment, absolute HTTP deadline and credential environment allowlist.
- Cloud findings reproduced before fixes: JSON content type, earlier marked-comment
  freshness, directory collision and error-report write failure. All four regression
  cases pass after corrections. Removed the unused fetch helper raised by Claude;
  documented the actual process-only Windows credential assignment. Merge-gate
  findings are superseded by removal, not treated as approval of the old design.
- Independent review found indirect Bob task dispatch via quoted slash commands and
  silent publication truncation. Commands are neutralized and oversized publication
  rejected; local reports survive publication failure. No Bob task was launched.
- Real CLI diagnostic completed through ChatGPT login. Actual dummy file write was
  blocked with code-mode host is disabled; file absent. Tool wrappers remain advertised,
  so complete tool/OS isolation is not claimed.
- Cloudflare2026.9.3 Windows binary checked against official release SHA256
  f096265ec2fcbe9bb6e2d64268db167ced3fcbb83d894bdb9e2fcdb26f2ea7e2.
- Webhook686574656 delivered actual PR/comment/check events with HTTP202. Comment
  delivery3845074305488519168 was redelivered as3845074514941583360 with HTTP200
  (dedup). An unsigned external request returned403.
- One supervised queued event completed a critical review of PR #92 at
  67a28f0348ad36a6491d91a8a00baf904acf0926, recommending BLOCKED with substantive
  methodology findings. Publication and merge were disabled. That test preceded
  adding the captured base's four startup/rule documents to the packet.
- Corrected scope: 25 focused tests pass; full Windows pytest suite exits 0.
  Worker-only ruff, linux/win32 mypy and Bandit pass; check_reports finds 0 problems.
  Integrated main 0bb28574b8554f337bd4128b852d5a4080302c59 introduces unrelated
  ruff/format/mypy/Bandit failures in the new Bob hook and skill installer. Full
  repository checks remain blocked on those repairs; no blanket green claim.
- Final corrected-head CI belongs in the PR handoff. Bob's first-head review is
  historical evidence, not approval of the corrected scope.

Residual limits: same-user Windows processes are not a credential-isolation boundary;
PR closing after its last check can race publication; GitHub has no atomic check/comment
API. Temporary tunnels change URL after restart and stop delivering while the PC sleeps.
No automatic redelivery, permanent service or production-availability claim.

## Next owners

Claude/Bob: review corrected scope, evidence quality, publication safety and resource
bounds on PR #94. Codex: address blockers, pass checks, record actual activation.
Reviewing agents: discuss worker findings; READY or green CI alone never decides a
merge. Standing own-work external-review and paper-only rules remain.

Rollback: stop receiver/tunnel and disable its one webhook, then revert code through
review if needed. No trading process or another agent's branch is touched.
