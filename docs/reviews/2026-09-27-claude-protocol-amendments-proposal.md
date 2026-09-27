# Claude: three protocol amendments (proposal)

- **Date:** 2026-09-27. **Author:** Claude. **Run:** Claude Code desktop session, Windows, Python 3.14.
- **Status: proposal, not adopted. Merged only when Claude, Codex and Bob all agree**,
  following the precedent of [the data-reuse proposal](2026-09-25-claude-data-reuse-proposal.md).
  All three amended passages carry a pending banner in the handbook that names the rule
  still in force, so if this merges before agreement the old rules still govern until
  the banners are removed. It is not a merge exception for any PR.
- **Owner request, 2026-09-27:** fix the protocol gaps found during the PR #83–#88 work,
  and make sure the other agents agree so the rules are clear to everyone.
- **Scope.** Documentation only: `docs/AGENT_HANDOFF.md`, `docs/START_HERE.md`, this
  file and the index row. No runtime, checker, integrity rule, parser, spec, mask,
  config or strategy change. No archive was opened and no reserved-window access.
- **Current revision: 6** (see [Revisions](#revisions)). Revision 3 reconciled Codex's
  audit checklist, Bob's `FLAGGED` and the narrowed agreement from a second Claude
  session, and changed amendment B from carrying verdicts to carrying findings.
  Revision 4 answers the review of revision 3: a pending note at the Bob task-file
  merge rule, the same-reviewer condition on a scoped verdict, a quiet `remerge-diff`
  command, and sender tags bound to the owner login. Revision 5 answers the review of
  revision 4: a reverse-dependency search, no scoped verdicts from Bob's GitHub
  reviewer, and a lapse clock that starts when an automatic review can actually run.
  Revision 6 adopts Codex Desktop's minimal repair to B (a scoped review reads the whole
  incoming base delta; the symbol search is dropped), ties usage-limit evidence to the
  required channel, calls the windows escalation defaults, calls sender tags declared
  attribution, and corrects the claim that no reviewer asks whether a change should
  exist.

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

### Gap 3 — waiting destroys the review you are waiting for

A verdict counts only at the head it names. The longer a PR waits for a reviewer, the
likelier it needs a merge of the base, and each merge used to restart review from
nothing.

It happened at PR #83. `main` advanced eight commits; the only conflict was one row in
`docs/reviews/README.md`; the resolution changed no prose. Bob's `NO ISSUES` at
`e5d5ff5e1231e3082909162c025aa6aa52eab5a7` died to it, and a full re-review cycle
followed. During that cycle a correction Codex had required at 00:28:01Z — the
`fetch_file` network wording — was lost track of and survived three heads before the
automated review caught it at `96fb1d82b6da4d66e42d3ebccc2e30958a0dad60`.

Revision 3 keeps the diagnosis but not the first cure. The problem worth solving is
that findings got lost and re-review was unbounded, not that verdicts died: a verdict
*should* die when the program it judged has changed, and a base merge can change it
without touching a line of the PR (see the counterexample below).

## The amendments

All three are written into the handbook by this PR, each under a pending banner.

### A. Two named states: allowance exhausted, and request lapsed

The first two revisions redefined one word, "unavailable", to cover both a usage-limit
reply and an unanswered request. That word also opens the stop-gap merge path, so a
lapse leaked into a merge path the text said it never reached. Revision 3 names two
states instead:

| State | What establishes it | When it ends | What it allows |
| --- | --- | --- | --- |
| **Allowance exhausted** | a usage-limit reply from the Codex channel whose review is required | at the first later Codex response that is not a usage-limit reply, or as soon as any new Codex request is posted after it | the owner's existing stop-gap only: Bob's `NO ISSUES` at the full head, green `test-and-audit` at that head, no unaddressed required fix; Codex reviews afterwards |
| **Request lapsed** | an exact-head review unanswered past its channel's window | when the reviewer answers at that head, or the head changes | escalation to the owner only; **never a merge** |

Every place the handbook uses Codex being unavailable as a reason to merge — the quick
reference's merge authority, START_HERE step 3's merge rule, and a Bob task-file PR —
means allowance exhausted, never lapsed. The two operative bullets that the first
revision had changed to "unavailable" are restored to the literal "has no allowance",
with the proposal in a pending note beside them.

**Exhaustion belongs to one channel.** A Codex Cloud usage limit does not establish
that Codex Desktop is unavailable, nor the reverse. The stop-gap needs a usage-limit
reply from the channel whose review is actually required. Expiry stays broad: any later
Codex response or request ends it, so the stop-gap is used less, never more.

**Exhaustion expires.** A usage-limit reply is evidence about one moment. It stops
counting at the next Codex response that is not a usage-limit reply, on any PR, and as
soon as a new request is posted after it; from then on, the answer to that request
decides. An unanswered new request is a lapse, not exhaustion.

**Lapse windows**, per channel: **1 hour** for Codex Cloud, Bob and the automated
review, which answer in minutes (Cloud answered exact-head requests in under three
minutes twice on 2026-09-27: PR #83 at 23:31:12, PR #87 at 00:50:53); **12 hours** for
Codex Desktop, which runs only when the owner opens it. No window is defined for other
channels, including the opt-in local Codex reviewer added on `main` since revision 2;
an unanswered request there is reported at the next check-in. Both figures are
judgements rather than findings, and the owner's to set. They are **escalation
defaults**: when silence is worth telling the owner about. A lapsed window is not proof
that a reviewer has failed, and never permission to merge.

**The clock** starts at the exact-head request, or, for a review that starts on its own
(the automated review, or a Codex Cloud review already pending, where the event-driven
rules say not to post a request), when that review became able to run at that head: the
latest of a push while the PR was not a draft, the PR opened as ready, marked ready for
review, or reopened. A push to a draft starts nothing, since `claude-review.yml` skips
drafts. Reposting
does not restart it. **A new head always restarts it**, including a merge of the base,
and needs a new exact-head request naming the new SHA (or a confirmed automatic
review). Revision 2 carried the elapsed time across a base merge; that is dropped,
because the old request named the old head and no verdict is carried any more.

**A lapse never authorizes a merge**, whatever the diff touches. The action is always
to escalate to the owner, naming the PR, the full head, the reviewer being waited on,
when the request was posted or the head pushed, and how long it has waited. The PR
stays open.

The owner's reason, which applies beyond this rule: whether a change should exist, and
what it costs the project to carry, is a judgement every reviewer is expected to
challenge (START_HERE step 0), and the merge is where it is finally made, deliberately.
**A green check, a clean verdict or an elapsed window does not replace that judgement.**
Revisions 1 to 5 said instead that no reviewer asks the question; that contradicted
START_HERE step 0, and Codex Desktop corrected it at revision 5.

### B. Findings, not verdicts, carry across a base integration

**No verdict is carried, and no mechanical check can make one carry.** After a merge of
the base:

1. **Prior findings stay on record as evidence.** The new request links the old head's
   verdicts and findings. A required fix open at the old head stays open; a merge never
   discharges it. This is the part of gap 3 that cost the most.
2. **A new verdict at the new full head is still required**, with `test-and-audit`
   green at that head. The reviewer may scope it, instead of rereading the whole diff,
   to **the entire incoming base delta** and **the conflict resolution**, relying for
   the unchanged contribution only on their own earlier reading of it. Two commands
   enumerate what to read:
   `git diff $(git merge-base <new-head>^1 <new-head>^2) <new-head>^2` (everything the
   base brought in) and `git show --format= --remerge-diff <new-head>` (Git 2.36 or
   later: where the recorded merge differs from Git's own automatic merge, including
   any edit slipped into the merge commit; `--format=` hides the commit header, so a
   clean merge prints nothing). **The commands enumerate evidence; they never certify
   safety.** The reviewer judges how the base delta and the contribution behave
   together; if that cannot be bounded with confidence, the verdict is a full review.
3. **The verdict states its scope**: old and new heads, the reviewer's own old verdict,
   both commands, and that the whole base delta and the resolution were read.
4. **Scoping is allowed only** for one merge of the base whose first parent is the
   reviewed old head, with no other commit, and only to a reviewer who gave a
   substantive verdict of their own at that old head. A reviewer leans only on their
   own earlier reading: otherwise one reviewer's old verdict could stand in for another
   reviewer's review of the contribution, and the external-review rule would be met by
   nobody reading the authored change. Anything else means a full review.
5. **Bob's GitHub reviewer never scopes.** It reads only the triggering comment, the PR
   description, the diff and the index, never other comments, so it cannot see its own
   earlier verdict or the open findings. It always reviews in full. The owner's desktop
   Bob session reads the thread and may scope like any other reviewer. The other option
   — quoting every open finding verbatim in the request — was rejected as the less safe
   of the two: a finding left out of the quote would vanish silently, which is the gap
   3 failure again.

**Why the whole base delta.** Revisions 3 to 5 tried to select which base changes to
read: first those the contribution depends on, then also base files naming a symbol the
contribution changes. Each selection was refuted by the next counterexample (below),
and a dependency analysis written in prose would keep inviting one. Reading the whole
base delta covers forward, reverse and transitive dependencies and coupling through
data, configuration or reflection, without a rule for each. It is still a bounded
review: the base delta and the resolution, not the contribution again.

On PR #83's integration both commands were run at revision 3. `git show --format=
--remerge-diff 96fb1d8` shows exactly the one resolved index row. The base delta from
`94b07a8ca7bf7092f4e5a2c57a167218d2bbb60a` to `3f83cb46553faa41e2971346c70413f1f8af31e4`
is nine files, 227 insertions and 11 deletions (`.github/workflows/bob-review.yml`,
`AGENTS.md`, three handbook files, one review file, the index, `pyproject.toml`, one
test). Under revision 6 the scoped review reads all of it plus the one resolved row,
and relies on the reviewer's own earlier reading of the two contributed review files.
That is a short, bounded review — the saving gap 3 wanted — without claiming the old
verdict still holds.

### C. Every agent comment names its sender in a machine-readable tag

Claude sessions, Codex Desktop and the owner's Bob session all post as `mgalic01`, so
the GitHub author identifies nothing. Each agent comment would open with a tag on its
own first line — `[Claude Code <session-id>]`, `[Codex Desktop]`, `[Bob]`. A tag is
plain text that anyone who can comment could type, so it counts only on a comment
authored by `mgalic01`; on any other login it is ignored, and that comment is never
Claude, Codex or Bob review evidence. On a `mgalic01` comment, the tag says which agent
claims to have written it. **A tag is declared attribution, not an authenticated
identity**: anything that posts as `mgalic01` can write any tag. The bot accounts need
no tag; their logins already differ. **Until all three agree, the existing rule stands:** every message starts with
its sender ("Claude → Codex" and the like), and no tag is required.

Added after a misattribution on 2026-09-27: a Claude session's review of this very PR
was reported to the owner as Codex Desktop's, by an agent that read `mgalic01` instead
of the first line, which said exactly which session wrote it.

Distinct GitHub accounts would make attribution authoritative rather than declared, and
were considered. They are rejected here because two of Bob's triggers gate on
`author_association == 'OWNER'` and `github.actor == github.repository_owner`
(`bob-task.yml`), so moving an agent off the owner account would break `/bob-run` and
the task-file-merge trigger. Widening those gates would reopen the hole they close.

## Dependency counterexample and disposition

**Codex, 2026-09-27T16:04Z**, rechecking revision 2 at
`f015f6a6e56c1b6450ee86a59393ba13aa424c60`:

1. Base: `limits.py` has `LIMIT = 5`; `strategy.py` imports `LIMIT`, and `accept(n)`
   returns `False`.
2. Feature: `accept(n)` becomes `return n <= LIMIT`. It is the only contributed file.
3. `main`: only `limits.py` changes, to `LIMIT = 50`.
4. Merge `main` into the feature.
5. Both merge-base contribution diffs are identical, and so is the `strategy.py` blob,
   yet `accept(10)` turns from `False` to `True`.

**Reproduced here independently**, in a throwaway repository in the session scratch
area (no project inputs, no network), Git 2.55.0.windows.3, Python 3.14:

```
merge-base contribution diffs: IDENTICAL
strategy.py blob old=107ff8c3508e11ecd30b43cf48386a6f87119373 new=107ff8c3508e11ecd30b43cf48386a6f87119373
remerge-diff of new head: (empty: clean merge)
base delta:  limits.py | 2 +-
accept(10) at old head: False
accept(10) at new head: True
```

**What it shows.** Revision 2's condition (2) — patch equality of the contribution —
would have carried a behavioural verdict across a behavioural change. So would the
alternative a second Claude session named on 15:47Z, tree equality of the contributed
paths: the blob is identical too. Equality of the PR's own text can show the text is
unchanged; it cannot show the program the reviewer judged is unchanged. The same holds
for documentation that describes `src/` when the base changes that source (Codex
Cloud's P1 on this PR). Codex also corrected the direction of the patch-text
weaknesses: both hunk context and `index` lines cause false refusals, and neither is
itself the unsafe direction; the unsafe direction is the dependency case.

**Disposition (revision 3).** Codex's recommendation, adopted: preserve prior findings
as evidence; require a bounded fresh review of the incoming base dependencies and
configuration and of the conflict resolution; require an explicit verdict at the
resulting full head with current checks. No mechanical carry of any kind. The rule's
scoped review catches this case, since `limits.py` appears in the base delta and the
contribution imports it. Any future mechanical exception needs adversarial fixtures
like this one and all three agreements.

**Reverse-dependency counterexample (Codex Cloud, 18:33Z, on revision 4).** The
feature changes `normalize()` in `metrics.py` from a percentage (`100 * x / total`) to a
fraction (`x / total`). The base adds `alerts.py`, which imports `normalize()` and
returns `normalize(x, total) > 50`. Reproduced here the same way, Git 2.55.0.windows.3,
Python 3.14.7:

```
remerge-diff lines: 0
base delta:  alerts.py | 5 +++++
forward rule (contribution imports from base delta): none: alerts.py looks unrelated
reverse rule, git grep -w -e normalize -e metrics over the base's files at the new head:
  alerts.py:1:from metrics import normalize
  alerts.py:5:    return normalize(x, total) > 50
alert(80, 100) on base-new: True
alert(80, 100) at merged head: False
```

**Disposition (revision 5, superseded).** Revision 4 followed only the edges from the
contribution to the base, so it would have judged `alerts.py` unrelated. Revision 5
added a search of the base's files for each symbol the contribution changes.

**Transitive counterexample (Bob, 18:59Z, on revision 5).** The same feature; the base
changes `alerts.py` to call `normalize()` and adds `router.py`, which imports `alert`
and never names `normalize`. Reproduced here the same way:

```
remerge-diff lines: 0
whole base delta:  alerts.py | 5 ++++-   router.py | 5 +++++
revision 5 symbol grep (normalize, metrics) over the base's files:
  alerts.py:1:from metrics import normalize
  alerts.py:5:    return normalize(x, total) > 50
route(80, 100) on base-new: page
route(80, 100) at merged head: log
```

The grep reports `alerts.py` only; `router.py` changes behaviour and is not reported.

**Disposition (revision 6).** Codex Desktop's minimal repair, adopted: the symbol search
is dropped, and a scoped review reads the whole incoming base delta plus the conflict
resolution. Both `alerts.py` and `router.py` are in the base delta, so both are read.
The three counterexamples stay here as the evidence for why no selection rule is
written down.

## Revisions

| Rev | Head | What changed |
| --- | --- | --- |
| 1 | `88c801e6804d8770d2d1eb72f3946bd4709209fa` | A: one "unavailable" state, 12-hour window, documentation-only lapse merge. B: carry verdicts when `git diff <old-head> <new-head>` outside the conflicted paths is empty. |
| 2 | `f015f6a6e56c1b6450ee86a59393ba13aa424c60` | B's check replaced by a merge-base patch comparison, since the first could never pass. A: owner decision, a lapse never merges; per-channel windows; elapsed time carried with carried verdicts. C added. |
| 3 | `e6d321f8dddc8be63518530aa79617d00cb04839` | Reconciles the eight-item checklist below, Bob's `FLAGGED` and Cloud Claude's narrowed agreement. B carries findings, not verdicts. A names two states with separate consequences, and exhaustion expires. Merges `main` at `15ab9cf822501ea74a2bf7a614c180336cdfce3a`. |
| 4 | `353188a1baeed569d19b28c874d4ee762ae18ed6` | Answers the review of revision 3 (table below). Merges `main` again, at `b7a857b337c538311f754046542f5e7f5be56272`. |
| 5 | `2c01fd5346d0abc31a369e4ff3be10b64330e6a8` | Answers the review of revision 4 (table below). Merges `main` a third time, at `c3c8e250bc5ec8837498d47bd0090cc4bd8c2edc`. |
| 6 | this revision | Answers the review of revision 5 (table below). Merges `main` a fourth time, at `58edafe82de5d2a675515df32b009c405b90a0d6`. |

**Revision 3, item by item.** The eight Codex Cloud inline threads that Codex's audit
(14:28Z) named as the checklist, then the other findings open at revision 2:

| Finding | Disposition |
| --- | --- |
| No-carry wording vs carry (Cloud, `AGENT_HANDOFF.md:98`) | **Fixed by removing the carry.** B no longer carries verdicts, so the three no-carry passages (what Bob's verdicts mean, branch-ownership item 5, the external-review rule) now agree with it and stay as written. B names them. |
| Undefined automatic-review lapse clock (Cloud) | **Fixed.** For a review that starts on its own at a push, the clock starts at the push of that head, since the event-driven rules tell agents not to post a request then. |
| Lapse entering the merge shortcut (Cloud P1, `:31`) and Bob's required fix 1 | **Fixed.** Two named states. Only allowance exhausted opens the stop-gap; request lapsed escalates only. The quick-reference bullet and START_HERE step 3 keep the literal "has no allowance", with a pending note that says a lapse never opens that path. The Bob task-file merge is named as covered too. |
| Raw patch equality retaining context and `index` lines (Cloud, `:107`) | **Fixed by removing the comparison as a gate.** Normalising the patch would not help: the counterexample defeats exact equality. Scope is now found with `git show --remerge-diff` and the base delta. |
| Missing review of relevant base changes (Cloud P1, `:102`) | **Fixed.** Item 2.2 of B requires review of every base change the contribution depends on, and of configuration changes regardless. Bob called this pre-existing rather than new; it is still a gap a carry rule would have widened, so it is closed here. |
| Timer carried without a current-head request (Cloud, `:169`) | **Fixed.** A new head always restarts the clock and needs a new exact-head request. No elapsed time carries. |
| Stale bypass rationale in the agreement section (Cloud, this file `:159`) | **Fixed.** [Agreement](#agreement) rewritten for the escalation-only amendment. |
| Unbounded allowance-exhaustion status (Cloud P1, `:155`) and Bob's required fix 2 | **Fixed.** Exhaustion ends at the next Codex response that is not a usage-limit reply, or once a new Codex request is posted; an unanswered new request is a lapse. |
| Patch-text equality is a proxy (Cloud Claude, 15:47Z, AGREE narrowed to AGREE WITH CHANGES) | **Agreed and superseded.** The proxy is gone; the counterexample shows tree equality would not have been enough either. |
| Dependency counterexample (Codex, 16:04Z) | **Adopted** — see the section above. |
| Automated review at revision 2: "Both amended sections" stale; C lacked a fallback | **Fixed.** Header says all three; C's banner now names the rule in force until agreement. |
| Automated review nit, revision 1: non-pending bullets said "unavailable" | **Fixed** with the literal "has no allowance" restored. |

**Revision 4, item by item.** The review of revision 3 at
`e6d321f8dddc8be63518530aa79617d00cb04839`. Bob returned `NO ISSUES` there on the
checklist question; that verdict is void at the new head.

| Finding | Disposition |
| --- | --- |
| Automated review, CHANGES NEEDED: the section claims to cover the Bob task-file merge, but that rule had no pending note | **Fixed.** The task-file rule now carries the same pending note and link as the quick reference and START_HERE step 3. |
| Cloud P2: `git show --remerge-diff` always prints the commit header, so "empty output" is unreachable | **Fixed.** The command is now `git show --format= --remerge-diff`. Checked on the synthetic clean merge: 6 lines without `--format=`, 0 with it. |
| Cloud P1: a scoped verdict could lean on another reviewer's old verdict | **Fixed.** Only a reviewer who gave their own substantive verdict at the old head may scope; anyone else reviews in full. |
| Cloud P1: sender tags are forgeable plain text | **Fixed.** A tag counts only on a comment authored by `mgalic01`; on any other login it is ignored and the comment is never agent review evidence. |

**Revision 5, item by item.** The review of revision 4 at
`353188a1baeed569d19b28c874d4ee762ae18ed6`. Bob returned `NO ISSUES` there twice and
the automated review returned `APPROVE`; Bob's desktop session (18:51Z) agreed to A and
C and agreed to B with the first two items below noted as real but not blocking. All of
those are void at the new head.

| Finding | Disposition |
| --- | --- |
| Cloud P1: B follows only contribution-to-base edges; a new base caller of a changed function is missed | **Fixed.** Item 2.3 requires a search of the base's files for every symbol the contribution changes. Reproduced above. |
| Cloud P1: Bob's GitHub reviewer never reads other comments, so a scoped Bob verdict cannot see old findings | **Fixed.** Bob's GitHub reviewer never scopes; it always reviews in full. The desktop session may scope. Quoting findings in the request was rejected as less safe. |
| Cloud P2: the automatic-review clock should start when the review can run, not at a push to a draft | **Fixed.** The clock starts at the latest of a non-draft push, opened as ready, marked ready for review, or reopened, following the triggers and draft condition in `claude-review.yml`. |

**Revision 6, item by item.** The review of revision 5 at
`2c01fd5346d0abc31a369e4ff3be10b64330e6a8`: Bob's GitHub reviewer `FLAGGED` (18:59Z),
the automated review `APPROVE` (19:02Z), and Codex Desktop **AGREE WITH CHANGES**
(19:04Z: A agree, B agree with changes, C agree). All are void at the new head.

| Finding | Disposition |
| --- | --- |
| Bob, FLAGGED: the symbol search in B 2.3 finds direct callers, not transitive ones | **Fixed by Codex's repair.** Reproduced above; the search is dropped and the whole base delta is read. |
| Codex Desktop, B: replace selective scoping with the minimal repair; commands enumerate, never certify | **Adopted** as written: whole base delta plus conflict resolution, same reviewer's earlier reading of the unchanged contribution, full review if combined behaviour cannot be bounded. |
| Codex Desktop, A: usage-limit evidence applies only to the required channel | **Fixed.** A Cloud limit does not make Desktop unavailable, nor the reverse; expiry stays broad. |
| Codex Desktop, A: 1h/12h are escalation defaults, not proof of failure or permission to merge | **Fixed**, in the handbook, START_HERE step 3 and here. |
| Codex Desktop, C: tags are declared attribution, not authenticated identities | **Fixed**, in the handbook and here. |
| Codex Desktop: "none of them asks whether the change should exist" contradicts START_HERE step 0 | **Fixed.** Now says every reviewer is expected to challenge that, the merge makes the decision deliberately, and automated success does not replace it. |
| Automated review nit: add `SECURITY.md` to the always-reviewed list | **Superseded.** The whole base delta is read, so no list is needed. |

## A separate observation, not a proposal

The review index, `docs/reviews/README.md`, is one append-only table with the newest
rows at the top, and every PR adds a row there. So each merge to `main` conflicts every
other open PR on the same lines. This PR is one example: its only conflict at revision
3 was that table, and after that push PR #100 merged and conflicted it
again on the same table, so revision 4 carries a second index-only merge, revision 5
a third and revision 6 a fourth. Cloud Claude reported the same for PR #100, the third Claude PR in
two days conflicted purely by the index. The cost is structural and paid by every PR,
and it is independent of amendment B. Codex's view, recorded here: keep the one-topic
PR workflow and the named-writer rule, and do not weaken review provenance to reduce
index contention. No change is proposed in this PR.

## What I am not proposing, and what I could not check

- **No tier by blast radius and no merge on a lapse**, for any kind of change.
- **No mechanical carry of verdicts or of lapse time.**
- **No new automation, trigger or scheduler.** Nothing here touches the Codex review
  protocol or introduces polling.
- **Neither amendment has been exercised in operation.** The evidence is what happened
  under the old rules, the PR #83 worked example and the synthetic counterexample;
  whether the new rules behave well is a prediction. The first real lapse, exhaustion
  expiry and scoped review should be reported back here.
- **How the base delta and the contribution behave together is a reviewer's
  judgement**, not a command. The commands enumerate what must be read; they certify
  nothing. When the combined behaviour cannot be bounded, the review is full.

## Agreement

- **Claude:** proposes. Agreed by authorship, at revision 6.
- **Codex:** AGREE WITH CHANGES at revision 5 (Codex Desktop, 19:04Z): A agree, B agree
  with changes, C agree. Revision 6 applies those changes; Codex's acknowledgment of
  the resulting head is still needed. Amendment A lets nothing bypass Codex's merge
  authority: it bounds the existing owner stop-gap to a current usage-limit reply from
  the required channel and adds an escalation-only lapse. Amendment B follows Codex's
  recommendation of 16:04Z and its minimal repair of 19:04Z.
- **Bob:** the desktop session agreed at revision 4 (18:51Z); the GitHub reviewer
  flagged revision 5 on transitive dependencies (18:59Z), which revision 6 answers.
  Both are void at the new head, so his agreement is needed again. His verdict carries
  no new weight here: no lapse path leans on it, and the stop-gap that uses his
  `NO ISSUES` is the owner's existing rule, now with an end. The PR #83 evidence above
  concerns a verdict of his — included as reasoning about the protocol, not as
  criticism of that review.

Nothing here advances the open-only reclassification, the spec freeze or any acceptance
condition, and no owner decision recorded elsewhere is altered.
