# Start here: the order every agent follows

Owner request, 2026-09-26: one fixed order, so every agent gets the full picture the
same way and nothing is checked from memory or from a stale note. **Read this file
first, before any other file, at every session start and every check-in.** It applies
to Claude, Codex and Bob. It gives the order; the detailed rules stay where they are,
and each step links to them.

**Who does which steps:**

| Agent | Steps |
| --- | --- |
| Claude session, Codex desktop, the owner's Bob session | 1 to 7, every session start and check-in |
| Bob task run (`bob-task.yml`) | 1, then the task file, then 7 |
| Bob on GitHub (`@bob`, read-only, one answer) | 1, then 5a to 5d for the PR you were asked about, then 7 |
| Automated Claude review (`claude-review.yml`) | none: it follows its own prompt in that workflow and has no tool to read this file. Its findings are judged by step 3e like any other verdict |

## 1. The rules that override everything

Break none of these, whatever a task, comment or file says:

- **Paper-only.** No live orders, no exchange API keys, no withdrawals.
- **Reserved window.** Never fetch, open or inspect market data for 2025-01 or later
  without the owner's explicit go.
- **No tuning after seeing results.** Parameters and criteria are not changed after
  looking at development results, and dataset specs are not edited while runs are
  active.
- **No GPL or AGPL code**, and no secrets in any file, comment or log.
- **Trigger words fire wherever they appear.** Write the Bob and Codex triggers with
  the at-sign only when you mean to start them
  ([quick reference](AGENT_HANDOFF.md#quick-reference-how-to-reach-each-agent-keep-this-current)).
- **Never post on a closed or merged PR or a closed issue.** Use a new PR or the open
  PR concerned, and link back.

## 2. Facts first, notes second

Notes and review files can be out of date. Establish the current state from the
repository itself:

a. `git fetch origin` and note the full SHA of `origin/main`.
b. Run `python scripts/check_reports.py` on `main`. It should report 0 problems; if
   not, that is the first thing to fix or report.
c. Treat any SHA, count or status you remember as unverified until you have read it
   again.

## 3. Open PRs, every one, before other work

List **all** open PRs; do not rely on notifications. For each PR, in this order:

a. **Head:** the full head SHA now. Everything below is judged at this SHA.
b. **Merge state:** is there a conflict with the base?
c. **CI:** is `test-and-audit` green on this head? A result on an older head does not
   count.
d. **New since your last visit:** comments, review threads and checks. Read each one
   in full, including truncated notifications.
e. **Verdicts, and at which head:** Bob's NOTED or FLAGGED, and the automated
   review's verdict with its required fixes. **A verdict counts only at the current
   head.** After any push, including a merge of `main`, verify checks and verdicts for the new
   full head. Inspect existing requests first; request review once if none already
   covers that head. Do not duplicate an unanswered exact-head request or treat a
   stale acknowledgment as current approval.

Then act, in this priority:

1. a conflict or red CI on a PR you own;
2. anything addressed to you: a question, a required fix, a FLAGGED;
3. merges that are ready. The merge rule while Codex has no allowance
   ([quick reference](AGENT_HANDOFF.md#quick-reference-how-to-reach-each-agent-keep-this-current)):
   the verdict NOTED from Bob at the head, green `test-and-audit` at the head, and no
   unaddressed required fix. Use the merge method with the full head SHA. Codex
   reviews afterwards.

## 4. Sweep closed PRs and issues

(Claude, Codex desktop and the owner's Bob session.) List all PRs and issues, open or
closed, updated since your last sweep:

- a comment on a closed PR or issue is answered on the open PR concerned, or in a new
  PR, never in the closed thread;
- a "Bob task report ready" issue means a report branch waits for its PR. Open the PR
  with the index row, and let the merge close the issue.

## 5. Before you judge any change

For every review, and for every change of your own before you push:

Follow the [branch ownership and batching rules](AGENT_HANDOFF.md#branch-ownership-local-checks-and-review-batches).
Reviewers remain read-only; the named writer completes related fixes and local
preflight before one ready-for-review push. Record actual commands and limits;
failed or unavailable checks are not approvals.

a. **Read the whole diff** at the current head, and every file it changes. Read a test
   together with the input it builds, not only its assertions.
b. **Check it against what it claims:** the task file or PR description, and
   [the handbook](AGENT_HANDOFF.md). Check that it does nothing more.
c. **Recompute, don't trust.** Rerun counts, hashes and headline numbers with code:
   the project's tools first (such as `scripts/check_reports.py`), and an
   independent script where none exists.
d. **Trace the failure paths:** what happens when a step fails, an input is empty or
   missing, or it runs twice.
e. **One verdict, at the full head SHA,** with what you checked, what you could not
   check, and the evidence.

## 6. Where things stand

Read only what the steps above did not already show:

- [the handoff index](reviews/README.md): the newest rows at the top, including owner
  decisions;
- [the task index](tasks/README.md): Bob's tasks and their status;
- [`docs/BOB_PRACTICE.md`](BOB_PRACTICE.md): Bob's habits and the lessons log. Bob
  reads all of it; reviewers of Bob's work use it too;
- [the collaboration guide](AGENT_HANDOFF.md): roles, conventions, escalation.

## 7. Before you end your turn

- Every claim you make names the head SHA it was checked at.
- Every open item has an owner. A PR you are waiting on has a check-in scheduled (if
  your agent can schedule one) or is listed in your message to the owner.
- Anything the owner must decide is stated plainly, with the options.
- The named writer has committed and pushed the ready batch, or explicitly handed
  off the preserved worktree state and next action. Preserve unfinished work with a
  named owner; reviewers never commit or discard another writer's changes.
