# Claude: two protocol amendments (proposal)

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

### A. "Unavailable" becomes a defined state, with a tiered consequence

Unavailable means the reviewer said its allowance is exhausted, **or** an exact-head
request has gone unanswered for **12 hours**. Reposting does not restart the clock; a
new head does.

On a lapse, the consequence depends on what the diff touches:

| The diff touches | On lapse |
| --- | --- |
| Documentation only | Stop-gap merge applies, requiring **both** Bob's `NO ISSUES` **and** the automated review's `APPROVE` at the full head, plus green `test-and-audit`. |
| `src/`, `tests/`, `scripts/`, `.github/`, `pyproject.toml`, `SECURITY.md` | **Never** a merge. Escalate to the owner naming the PR, head, waiting reviewer and elapsed time. |

The 12-hour figure is the one number here that is a judgement rather than a finding.
It is proposed, not derived; the owner should set it.

**Why both verdicts, not just Bob's.** I first proposed letting documentation merge on
Bob's verdict alone, then withdrew it the same day. At PR #83 Bob returned `NO ISSUES`
on a documentation change that still contained an already-required, silently dropped
correction. He was not careless — his three points were index integrity, ordering and
the core `compare_bars` claim, and the dropped text was prose he had cleared at an
earlier head. The automated review caught it by re-reading `dataset.py` against the
prose at the current head. A reading-level verdict and a fresh source-versus-prose check
answer different questions. For documentation whose purpose is describing code, one does
not substitute for the other.

### B. A verdict may be carried across a base integration

Verdicts recorded at the previous head stay valid when all four conditions hold: the new
head is a merge of the base and nothing else; the diff between old and new heads outside
the conflicted paths is **verifiably empty**, by a command whose output is quoted; each
conflict resolution is reviewed at the new head; and the carrying agent states the old
head, new head, conflicted paths, command and empty output.

This shortens an accounting loop. It does not lower the bar for what gets read — the
resolution itself is always reviewed, and any rebase, squash or extra commit voids
everything exactly as before.

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
