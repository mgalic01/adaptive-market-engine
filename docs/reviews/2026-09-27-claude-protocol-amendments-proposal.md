# Claude: three protocol amendments (proposal)

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **Status: proposal. Merged only when Claude, Codex and Bob all agree**, following the
  precedent of [the data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md).
  Both amended sections carry a pending banner in the handbook, so if this merges before
  agreement the old rules still govern until the banners are removed.
- **Owner request, 2026-09-27:** fix the protocol gaps found during the PR #83–#88 work,
  and make sure the other agents agree so the rules are clear to everyone.
- **Scope.** Documentation only: `docs/AGENT_HANDOFF.md`, `docs/START_HERE.md`, this
  file and the index row. No runtime, checker, integrity rule, parser, spec, mask,
  config or strategy change. No archive was opened and no reserved-window access.

## Why: three gaps, all observed rather than theorised

Each of these cost real time on 2026-09-27. None is hypothetical.

### Gap 1 — the stop-gap keys on the wrong variable

The rule read *"while Codex has no allowance"*. That is a statement about **quota**. The
condition that actually stalled the queue was different: Codex Desktop had quota and was
simply not **running**. It has no inbound channel — no comment, mention or webhook starts
it — so only the owner can. The handbook never named that state, so an agent reading the
rule literally concludes it is blocked, and an agent reading it loosely merges on a
condition the owner never wrote down. Both happened in one session.

### Gap 2 — a stated intention never expires

At PR #83 Codex wrote *"I will review that final head for merge."* Nothing in the
protocol said what happens if that reviewer never runs. No timeout, no fallback, no
escalation. One sentence from one agent could hold a PR open indefinitely with no
documented way forward, and the agent that wrote it was not at fault — the case was
simply unspecified.

### Gap 3 — waiting destroys the approvals you are waiting for

A verdict counts only at the head it names. Merging the base into a long-running PR
changes the head while changing nothing a reviewer judged. So the longer a PR waits for
a reviewer, the likelier it needs an integration, and the integration voids the verdicts
it was waiting to collect. This is a loop, not a one-off cost.

It ran to completion at PR #83. `main` advanced eight commits; the only conflict was one
row in `docs/reviews/README.md`; the resolution changed no prose. Bob's `NO ISSUES` at
`e5d5ff5e1231e3082909162c025aa6aa52eab5a7` died to it, and a full re-review cycle
followed. During that cycle a correction Codex had required at 00:28:01Z — the
`fetch_file` network wording — was lost track of and survived three heads before the
automated review caught it at `96fb1d82b6da4d66e42d3ebccc2e30958a0dad60`. **The rule
meant to protect review integrity measurably cost it.**

## The amendments

Both are written into the handbook by this PR, each under a pending banner.

### A. "Unavailable" becomes a defined state, and a lapse escalates

Unavailable means the reviewer said its allowance is exhausted, **or** an exact-head
request has gone unanswered past its channel's window: **1 hour** for Codex Cloud, Bob
and the automated review, which answer in minutes; **12 hours** for Codex Desktop,
which runs only when the owner opens it. A single threshold across both was the wrong
shape — Cloud answered exact-head requests in under three minutes twice on 2026-09-27
(PR #83 at 23:31:12, PR #87 at 00:50:53), while the stall that prompted this rule was
Desktop. Both figures are still judgements rather than findings, and the owner's to set.

Reposting does not restart the clock. A new head does, **except** where the verdicts
were carried under amendment B, in which case the elapsed time carries with them.
Without that exception A and B fight: a base integration creates a new head, so a PR
that had waited eleven hours would restart at zero, rebuilding the loop B exists to
break. Found in review by a second Claude cloud session.

**A lapse never authorizes a merge**, whatever the diff touches. The action is always
to escalate to the owner, naming the PR, the full head, the reviewer being waited on,
when the request was posted and how long it has waited. The PR stays open.

**This is narrower than my first draft, and deliberately so.** That draft let a
documentation-only diff merge on Bob's `NO ISSUES` plus the automated review's
`APPROVE`. The owner rejected it, and the reasoning is worth recording because it
applies beyond this rule: every check in the chain — CI, Bob, the automated review,
Codex Cloud — takes the PR's premise as given and verifies its execution. **None asks
whether the change should exist at all, or what it costs the project to carry.** That
judgement is made once, at the merge. Automating it away on the strength of checks that
never ask the question would remove the only place it happens.

So naming a lapse does not unblock a merge. It gives an agent waiting on a reviewer a
defined action other than waiting silently or inventing its own licence to proceed —
the two failures this rule was written after, both committed on 2026-09-27.

### B. A verdict may be carried across a base integration

Verdicts recorded at the previous head stay valid when all four conditions hold: the new
head is a merge of the base and nothing else; **the PR's own contribution is unchanged**,
verified by the commands below; each conflict resolution is reviewed at the new head;
and the carrying agent states the old and new heads, both bases, the conflicted paths
and the commands with their output.

```
git diff $(git merge-base <base-old> <old-head>) <old-head> -- . ':!<conflicted paths>' > before.diff
git diff $(git merge-base <base-new> <new-head>) <new-head> -- . ':!<conflicted paths>' > after.diff
diff before.diff after.diff        # must be empty
```

**The first version of this condition could never pass, and review caught it.** It said
`git diff <old-head> <new-head> -- . ':!<conflicted paths>'` must print nothing. After a
base integration that diff shows everything the base brought in, so excluding the
conflicted paths still leaves every commit that landed on the base meanwhile. Run
verbatim on PR #83 it reports 8 changed files and 226 insertions, because `main` had
advanced eight commits — the condition failed on the exact PR it was written to rescue,
and would fail on nearly any PR whose base moved. A second Claude cloud session found it
by running it rather than reasoning about it, and proposed the merge-base form; I
confirmed both results here before changing the wording. On PR #83 the merge-base form
produces two 264-line diffs that compare identical.

A narrower form — restricting the diff to the PR's own paths — also works but needs a
correct file list, and a wrong list silently widens the exclusion. The merge-base form
needs no list, so it is the one written down.

This shortens an accounting loop. It does not lower the bar for what gets read — the
resolution itself is always reviewed, and any rebase, squash or extra commit voids
everything exactly as before.

### C. Every agent comment names its sender in a machine-readable tag

Claude sessions, Codex Desktop and the owner's Bob session all post as `mgalic01`, so
the GitHub author identifies nothing. Each agent comment now opens with a tag on its
own first line — `[Claude Code <session-id>]`, `[Codex Desktop]`, `[Bob]` — and readers
use the tag, never the login. The bot accounts need no tag; their logins already differ.

Added after a misattribution on 2026-09-27: a Claude session's review of this very PR
was reported to the owner as Codex Desktop's, by an agent that read `mgalic01` instead
of the first line, which said exactly which session wrote it.

Distinct GitHub accounts would make attribution authoritative rather than declared, and
were considered. They are rejected here because two of Bob's triggers gate on
`author_association == 'OWNER'` and `github.actor == github.repository_owner`
(`bob-task.yml`), so moving an agent off the owner account would break `/bob-run` and
the task-file-merge trigger. Widening those gates would reopen the hole they close.

## What I am not proposing, and what I could not check

- **No general tier by blast radius.** Tiering appears only as a *restriction* on the
  lapse path, never as a shortcut in the normal path. The ordinary gate is unchanged for
  every kind of change.
- **No new automation, trigger or scheduler.** Nothing here touches the Codex review
  protocol or introduces polling.
- **I could not test either amendment in operation**, because both govern situations
  that have not recurred since they were written. The evidence above is what happened
  under the *old* rules; whether the new ones behave well is a prediction, and the first
  real lapse or carried verdict should be reported back here.
- **A carried verdict is only as good as its check.** Condition (2) is a command, not a
  judgement, precisely so it cannot drift into "it looked the same to me". If agreement
  is reached, a script asserting it mechanically would be a sound follow-up; I have not
  written one, to keep this change reviewable as documentation.

## Agreement

- **Claude:** proposes. Agreed by authorship.
- **Codex:** to agree, or to name what it would change. It holds merge authority and
  amendment A changes when that authority may be bypassed, so its view governs.
- **Bob:** to agree, or to flag. Amendment A leans on his verdict for the documentation
  lapse path, and the PR #83 evidence above concerns a verdict of his — included as
  reasoning about the protocol, not as criticism of that review.

Nothing here advances the open-only reclassification, the spec freeze or any acceptance
condition, and no owner decision recorded elsewhere is altered.
