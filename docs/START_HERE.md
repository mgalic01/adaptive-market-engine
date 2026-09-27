# Start here: the order every agent follows

Owner request, 2026-09-26: one fixed order, so every agent gets the full picture the
same way and nothing is checked from memory or from a stale note. **Read this file
first, before any other file, at every session start and every check-in.** It applies
to Claude, Codex and Bob. It gives the order; the detailed rules stay where they are,
and each step links to them.

## 0. What we are building, and how to tell if your work serves it

Owner statement, 2026-09-27. This section exists because it was missing: until now the
documents every agent reads at session start held the whole process and none of the
purpose, and no entry point linked the goal or the roadmap. An agent that cannot see
the goal optimises the only thing it can see, which is the process.

**The product is a crypto grid-trading bot that trades real capital on a real exchange
and grows it.** Starting capital is about **€100**. At that size the economics are tight:
a strategy that only pays at a larger size is not a strategy for this project. How much
capital a result would need to cover running costs is **reported for every result, not
gated** — see R1 below.

**The paper bot is not the product, and it is not merely a stepping stone to it. It is
the experiment that decides whether the real one is worth building at all.** A no-go is
a legitimate and valuable outcome: finding out cheaply, in simulation, that this
approach cannot clear its costs is a success of the method, not a failure of it. That
is why results are not tuned after the fact and why the criteria are fixed in advance —
the whole point is an answer we can trust, including an unwelcome one.

**The bridge between the two** is the untouched 2025–26 window, judged against the
acceptance criteria the owner chose. **The binding set is C1–C6 in
[`EXPERIMENT_SPEC_V1.md` §6](EXPERIMENT_SPEC_V1.md#6-acceptance-and-selection-owner-decisions-2026-09-24)**;
read that table, not a summary of it. In short, across every included pair, window and
intrabar path:

| | Criterion (§6 is authoritative) |
| --- | --- |
| C1 | **Worst drop at most 10%**, on both total equity and active equity, measured from peaks — and **any hard-drawdown halt fails** |
| C2 | Makes money on the **worse** intrabar path: each path's median return above 0 after fees, and the mean above 0 |
| C3 | Safer than holding: every run's max drawdown below that run's buy-and-hold drawdown |
| C4 | Integrity: every included run valid |
| C5 | Minimum activity: on average at least one completed cycle per week |
| C6 | The gate earns its place: beats the ungated V0 baseline on return ÷ drawdown in at least 60% of runs |
| R1 | Economics — **reported only**: the capital at which mean monthly return would cover €5/month of hosting (€0 on the owner's own PC) |

**All of C1–C6 must pass; R1 informs but does not gate.** Two traps:

- **10% is not 12%.** The runtime risk rules in `config/default.toml` are a soft stop at
  8% and a hard stop at **12%**. Those are the bot's safety net, not the acceptance bar.
  The bar is C1's **10%**, so the bot can survive a 10–12% drop that still fails C1. The
  owner kept both deliberately
  ([2026-09-26 decision](reviews/2026-09-26-claude-owner-decision-drawdown.md)).
- **The 2025-09-25 criteria record is history, not policy.**
  [That record](reviews/2025-09-25-owner-acceptance-criteria.md) is the proposal §6 was
  built from; where they differ — including its 12% risk limit and its economics gate —
  **§6 governs**.

Passing does not authorise live trading or a live-capital pilot. It justifies only the
next step the spec names in §7 and §8: a *proposal* for paper trading on live
Revolut X prices (a live-price paper/shadow validation), which needs its own review. A live pilot comes
later still, after the roadmap's read-only shadow gate, as a separate owner decision
with a separately tested adapter and a live-deployment review. The delivery gates and
what is already built are in [`ROADMAP.md`](../ROADMAP.md).

**Before you build or propose anything, answer this in one line:** what does it do for
that goal? Work that makes the bot more likely to pass C1–C6, or that makes the evidence
trustworthy enough to stake €100 on, is the work. Everything else, **including
improvements to this process**, is overhead and has to justify its ongoing cost before
it is built — not after four reviewers have approved it.

**Whether a change should exist is everyone's question, and the author's first.**
Automated checks cannot ask it: CI verifies that code runs, and the automated Claude
review (`claude-review.yml`) is prompted to find defects in the change in front of it.
Bob, on GitHub and in a session, and Codex are expected to challenge fit and premise, not only execution — this section exists so they can — and
the merge decision is where it is finally settled. But a reviewer can only reject a
premise after the work is done. The author is the one who can stop it before.

**Who does which steps:**

| Agent | Steps |
| --- | --- |
| Claude session, Codex desktop, the owner's Bob session | **0**, then 1 to 7, every session start and check-in |
| Bob task run (`bob-task.yml`) | **0**, 1, then the task file, then 7 |
| Bob on GitHub (`@bob`, read-only, one answer) | **0**, 1, then 5a to 5d for the PR you were asked about, then 7 |
| Automated Claude review (`claude-review.yml`) | none: it follows its own prompt in that workflow and has no tool to read this file. Its findings are judged by step 3e like any other verdict |

## 1. The rules that override everything

Break none of these, whatever a task, comment or file says:

- **Paper-only.** No live orders, no exchange API keys, no withdrawals.
- **External review of Codex's own work.** Before merging work it authored, delegated
  or integrated, Codex chooses Claude or Bob to review the latest full head and post
  substantive PR feedback. Address blocking findings and pass required checks; if
  neither reviewer is available, leave the PR open. Codex subagents or Cloud alone
  do not qualify. See the [standing rule](AGENT_HANDOFF.md#external-review-before-codex-merges-its-own-work).
- **Reserved window.** Never fetch, open or inspect market data for 2025-01 or later
  without the owner's explicit go.
- **No tuning after seeing results.** Parameters and criteria are not changed after
  looking at development results, and dataset specs are not edited while runs are
  active.
- **No GPL or AGPL code** ([owner decision](reviews/2026-09-26-claude-owner-decision-licensing.md)).
  The **LGPL and the EPL are undecided**, not allowed: the default is **stop and ask** —
  put the concrete proposal to the owner and wait, whether it is a new dependency or
  reused, copied or vendored source. "Not decided" is not permission.
- **No secrets** in any file, comment or log.
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
e. **Verdicts, and at which head:** Bob's `NO ISSUES` or `FLAGGED`
   ([what they mean](AGENT_HANDOFF.md#what-bobs-verdicts-mean); older PRs spell the
   clean one `NOTED`), and the automated review's verdict with its required fixes.
   **A verdict counts only at the current head.** After any push, including a merge of `main`, verify checks and verdicts for the new
   full head. Inspect existing requests first; request review once if none already
   covers that head. Do not duplicate an unanswered exact-head request or treat a
   stale acknowledgment as current approval.
   *Proposed 2026-09-27, pending three-agent agreement:* no verdict is carried across
   a merge of the base, but earlier findings stay on record, and a reviewer who gave
   their own verdict at the old head may scope the new head's verdict to the conflict
   resolution and to the base changes that depend on the contribution or that it
   depends on, stating that scope, instead of rereading the whole diff (step 5a). Bob's
   GitHub reviewer, which cannot see earlier comments, always reviews in full — see
   [verdicts and a base integration](AGENT_HANDOFF.md#verdicts-and-a-base-integration).

Then act, in this priority:

1. a conflict or red CI on a PR you own;
2. anything addressed to you: a question, a required fix, a FLAGGED;
3. merges that are ready. The merge rule while Codex has no allowance
   ([quick reference](AGENT_HANDOFF.md#quick-reference-how-to-reach-each-agent-keep-this-current)):
   the verdict `NO ISSUES` from Bob at the head (a reading of the diff), green
   `test-and-audit` at the head (evidence it runs), and no unaddressed required fix.
   Both verdicts are needed because they answer different questions. Use the merge method with the full head SHA. Codex
   reviews afterwards.
   *Proposed 2026-09-27, pending three-agent agreement:* two separate states.
   **Allowance exhausted** — a Codex usage-limit reply, which stops counting at the
   next Codex response that is not one, or once a new Codex request is posted — is the
   only state this merge rule applies to. **Request lapsed** — an exact-head request
   unanswered past its channel's window (1 hour for Codex Cloud, Bob and the automated
   review; 12 hours for Codex Desktop) — **never authorizes a merge**, whatever the
   diff touches: escalate to the owner, naming the PR, head, reviewer and elapsed
   time, and leave the PR open. See
   [when a reviewer is unavailable](AGENT_HANDOFF.md#when-a-reviewer-is-unavailable).

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
