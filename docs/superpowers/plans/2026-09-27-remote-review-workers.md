# Two remote reviewers implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan
> task by task. Keep this topic coordinated in PR #120 until its reviewed batch is
> complete; follow-up implementation must link it rather than silently expand scope.

**Goal:** Restore independent critical review when the owner's PC is off, without
discarding work at an arbitrary start count. This is review reliability overhead,
not a strategy improvement or evidence of profitability.

**Architecture:** Two GitHub-hosted identities reuse the existing evidence collector,
review prompt, CLI restrictions and publication checks. A trusted controller owns
non-secret durable claims and incidents; each serialized worker owns one separately
provisioned managed login in a main-only GitHub environment.

**Tech stack:** Existing Python standard-library worker; GitHub Actions, REST and
Git refs; pinned Codex CLI and GitHub CLI. No new OpenAI API key or trading component.

**Spec:** [Remote workers design](../specs/2026-09-27-remote-review-workers-design.md).
**Status:** Preparation, not deployed. Owner approved the hosting direction and
separate worker-login storage. Authentication provisioning, reviewed controller
permissions and delivery verification are prerequisites, not completed work.

## 1. Establish a deployable CLI boundary first

- [ ] Pin a distributable Linux CLI version and integrity digest. Do not assume the
  Desktop-bundled alpha build is the same product binary available on Actions.
- [ ] Exercise `local_worker.command()` against that CLI with dummy auth, an empty
  HOME/CODEX_HOME, neutral cwd and no repository credentials. Unsupported options or
  silently ignored containment settings block deployment.
- [ ] Add `tests/test_remote_worker_containment.py`: fake local model endpoint returns
  hostile file-read, shell, browser, app and code-execution requests. Assert no dummy
  auth content can be returned and no requested tool executes. Use no real login or
  billable model. Verify benign structured output still succeeds.
- [ ] Keep real logins unprovisioned until this test passes on Linux and Claude/Bob
  review the evidence. Do not weaken the existing flags merely to get a run started.

## 2. Durable claims and two identities

- [ ] Add `scripts/remote_worker_state.py` and `tests/test_remote_worker_state.py`.
  `claim(state, fingerprint, worker, run_id, now)` returns a new state or no claim.
  A fingerprint covers repository, PR, full base/head and substantive evidence digest.
  Worker IDs are exactly `codex-worker-1` and `codex-worker-2`.
- [ ] Persist only validated IDs, digests, timestamps, result states and public URLs
  in `automation/codex-worker-state`. No raw comments, outputs, recipient or credentials.
  Test schema rejection, duplicate events, restart, one active lease per identity,
  concurrent reservations and damaged/missing state. Missing established state is an
  incident; only an explicit first-deployment bootstrap creates empty state.
- [ ] Git ref updates use a commit whose parent is the captured state tip, with
  `force=false`. Retry conflicts by re-reading and reapplying, never overwrite another
  claim. Test two controllers racing and cancellation at each persisted transition.
- [ ] State machine: queued → reserved → model-started → publication-pending →
  completed; failures retain their phase. Expired pre-model reservations can be
  reassigned after verifying the old Actions run is terminal. Uncertain model or
  publication outcomes require reconciliation, not blind duplicate execution.

## 3. Reuse the reviewer in an event-driven controller

- [ ] Add `scripts/remote_worker.py` and tests. Import the existing collector,
  `command`, `child_environment`, schema and publication checks; do not fork a second
  review implementation. Add worker identity to the handoff while preserving the
  common self-comment marker and full head/base checks.
- [ ] Add `.github/workflows/codex-remote-review.yml`, initially disabled through an
  explicit repository activation variable. Use only reviewed default-branch code;
  never execute a PR branch, dependency installer from a PR or untrusted event text.
- [ ] Reuse sender/repository/event validation. Ignore both workers' receipts and
  incident branches. Reconcile substantive review/check changes without a self-trigger
  loop. Test head/base movement, stale discussion, incomplete evidence, closed PRs,
  unsupported paths, duplicate publication and oversized payloads.
- [ ] Dispatch work to either free identity; separate job concurrency groups with
  no cancellation of an active login stream. No hourly/daily start quota. Preserve
  the current per-call timeouts and bounded evidence. Record every failure visibly.
- [ ] A non-model reconciliation/health job recovers missed events and alerts on a
  stranded controller; it does not review unchanged PRs. Record GitHub scheduling and
  outage limitations, including that zero independent infrastructure cannot detect
  a total GitHub outage while it is happening.

## 4. Credential lifecycle and secure provisioning

- [ ] Two main-only environments each store `CODEX_AUTH_JSON`. Use environment secrets
  loaded at job start, not repository-secret snapshots captured when runs queue.
  Serialize each identity before its environment is entered.
- [ ] Add a trusted auth helper and dummy-secret tests. Restore to a private temporary
  directory, validate bounded JSON, run CLI, save any refreshed file back, then remove
  ephemeral files. Use GitHub CLI stdin for encrypted secret upload; never command
  arguments, output, cache or artifact. Suppress raw subprocess/HTTP error contents.
- [ ] The write-back credential is separately provisioned for this repository with
  environment-secret update permission. Document its actual broad environment scope;
  do not pretend GitHub can restrict it to one secret name. No existing Desktop or
  local GitHub credential is copied. Normal review publication uses the separate job
  token, excluded from the model process.
- [ ] Test cancelled job, rotation-success/write-back-failure and stale queued login.
  Persist an auth-uncertain latch before another job starts; that identity cannot
  run again until reconciliation or fresh login. Do not log token values or hashes.
- [ ] After external review, provision each fresh login interactively with the owner
  outside the Desktop CODEX_HOME, upload securely and destroy staging copies only
  after successful transfer. No login can be manufactured without owner sign-in.

## 5. Incidents and delivery

- [ ] Add `scripts/remote_worker_incidents.py` and dummy-service tests. Keep this writer
  separate from the model's comment-only GitHub adapter. Its allowlist creates only
  fixed-prefix incident branches, one report file and one PR; no merge/workflow edits.
- [ ] Atomically latch an episode before posting. Reconcile deterministic branch/PR
  after timeouts; update the existing episode on repeat failures. Only a confirmed
  healthy recovery re-arms. Test simultaneous failures and crash after publication.
- [ ] Notify Claude on the incident PR and explicitly request Bob once; ordinary
  GITHUB_TOKEN comments do not trigger other workflows, so test the actual trigger
  path instead of assuming a mention fires. Do not dispatch a paid Bob task.
- [ ] Configure a verified email sender and private recipient secret. Keep attempted,
  provider-accepted and owner-confirmed receipt distinct. No sender service exists
  yet; account/domain verification is an owner setup dependency.
- [ ] Configure the requested Desktop heartbeat through the app automation tool,
  quiet while unchanged. Document that it needs the app available and cannot promise
  instant delivery or wake an offline PC. No private resume endpoint or desktop-auth
  export is part of this plan.

## 6. Review and activation

- [ ] Run fixture tests, Ruff, mypy, report checks and Linux containment probe. Request
  Claude/Bob review at the full final SHA, address findings and verify required checks.
- [ ] Provision credentials only after containment/permission review. Verify both
  workers separately with bounded requests and the owner PC out of the execution path.
- [ ] Exercise one synthetic incident PR without a model call; verify agent requests,
  email receipt and Desktop delivery separately. Close the test incident deliberately.
- [ ] Enable event processing only after these gates; publish the final deployment
  SHA, worker identities, trigger rules, recovery procedure and remaining limitations.
  Preserve the old local queue; do not replay its 567 events blindly into production.

## Review focus

The highest-risk cases are an unsupported Linux CLI restriction, queued stale auth,
rotation followed by runner termination, duplicate publication after a timeout, and
alerts whose GitHub token suppresses downstream triggers. Each has an explicit test
above. This plan does not equate source fixtures with a successful remote deployment.
