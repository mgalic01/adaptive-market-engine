# Owner decision: the three protocol amendments are adopted, with three merge-authority additions

Index: **Owner decision, 2026-09-28.** PR #89's three amendments (A: allowance exhausted vs request lapsed; B: findings carry across a base merge, verdicts do not; C: sender tags) are adopted by the owner's decision while Codex is out of credits, and their pending banners come off. Three additions the owner approved the same day: while Codex's allowance is exhausted, the author may merge its own PR on Bob's `NO ISSUES` plus the automated review's `APPROVE` plus green CI; the automated review is part of that gate; every such merge is queued for Codex in issue #134. Also: a Bob task run that fails on Bob's side is rerun once, a second failure is reported.

- **Date:** 2026-09-28. **Author:** Claude (session `012TnmLL`). **Owner:** decisions quoted
  below, given in Claude's session on 2026-09-28 between 07:40 and 07:55 UTC.
- **Scope.** Documentation only: `docs/AGENT_HANDOFF.md`, `docs/START_HERE.md`, the
  proposal's status line, this record, and issue #134. No code, spec, config or data.

## What the owner decided, in the owner's words

1. On whether to adopt PR #89 now, after Claude's summary of its content and of the
   agreement so far (Codex: B agree, C agree, A agree with the two changes revision 7
   made; Bob: `NO ISSUES` at `8547037`; automated review: `APPROVE`): **"ok sounds good,
   i agree."** The owner had said before: "Since Codex is out i will provide an approval
   or not."
2. On Claude's three additions ("Say yes to 1 to 3 or change them"): the same "i
   agree". They are:
   1. **Who merges when Codex is out.** The standing rule that Claude does not merge
      its own work gets one written exception: while Codex's allowance is exhausted,
      the author may merge its own PR after Bob's `NO ISSUES`, the automated review's
      `APPROVE` and green CI, with no unaddressed required fix; Codex reviews
      afterwards.
   2. **The automated Claude reviewer is part of the gate.** It exists at every head
      and costs nothing; a merge under the stop-gap needs its `APPROVE`.
   3. **A queue for Codex's post-merge reviews.** Issue #134 lists every merge made
      under the stop-gap, appended by the merging agent; Codex ticks rows on return.
3. Claude's fourth point, a Bob service failure (today's P8 run, "Connection Failed"
   after the task had completed): one rerun under the owner's blanket approval of paid
   Bob runs, a second failure is reported. Recorded in the handbook's Bob task rule, not
   in the amendments.

## What changed in the documents

| Where | Change |
| --- | --- |
| `docs/AGENT_HANDOFF.md`, quick reference | Merge authority names the automated review and issue #134; the pending note becomes the rule. Sender tags: "since 2026-09-28" instead of the pending banner. |
| `docs/AGENT_HANDOFF.md`, the two amendment sections | The pending banners are replaced by one adoption line each. |
| `docs/AGENT_HANDOFF.md`, new section "Merging while Codex's allowance is exhausted (owner instruction 2026-09-28)" | The five points above, including that a lapse is not exhaustion and that task-file merges also need the owner's go for the paid run. |
| `docs/AGENT_HANDOFF.md`, Bob task-file rule | The automated review joins the gate; the rerun rule for a failure on Bob's side. |
| `docs/START_HERE.md`, step 3 | The pending notes become the rule; the automated review joins the gate; the author may merge its own PR; append to issue #134. |
| `docs/reviews/2026-09-27-claude-protocol-amendments-proposal.md` | Status and `Index:` line say adopted, and how. |

## What this does not change

- Amendment A's text itself. Codex's acknowledgment of revision 7 is still owed, and
  a finding from Codex on return is a follow-up PR, not a reversal.
- Nothing about the bot, the data, the spec or the experiment. No parameter, criterion
  or dataset is touched.
- The owner's blanket approval of paid Bob runs (2026-09-27) is applied, not widened.

## Claude's assessment, given to the owner before the decision

Amendment A's expiry and its "silence never merges" line, and amendment C, are the
useful parts. Amendment B mattered most when every merge to `main` conflicted every open
PR on the review index; PR #116 removed that cause on 2026-09-28, so B is now a
convenience rather than the main pain. The cost is about 640 lines of process text that
every agent reads at session start. Nothing here makes the bot better or the experiment
faster; the three additions are what this week's work showed the amendments still
lacked.
