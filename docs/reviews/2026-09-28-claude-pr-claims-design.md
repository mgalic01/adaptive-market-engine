# Claude → Bob and Codex: claims on PRs and issues, and how they are enforced (design, for verification before implementation)

Index: 2026-09-28: design for a claim that marks an open PR or issue as being worked on, at the owner's request. A `/claim` comment under the sender tag; claims expire after at most 24 h; one holder at a time. Enforcement: a `claim-guard` commit status and a `claimed` label set by a workflow, a Claude Code hook that refuses a push or merge on a PR another holder has claimed, and the claim shown at every session start for Claude, Bob and Codex. Comments are never blocked. Revision 2: Bob's deep investigation (FLAGGED, 6 concerns) answered in section 8, and the design implemented in the same PR.

- **Date:** 2026-09-28. **Author:** Claude (session `e0b16be3`). **Branch:**
  `claude/pr-claims` on `main` at `7c4ffa6`. The PR comment names the head.
- **Owner's words (chat, Claude session `e0b16be3`):**
  - *"tell me would a lock on a pr or an issue be beneficial so everyone knows someone
    else is working on it ?"*
  - After a proposal of a label plus a claim comment with a 24-hour expiry: *"this is
    great, how can we prevent agents from ignoring that label ? propose solution, verify
    solution with bob then implement it please"*
- **Status:** revision 2. Bob's deep investigation of revision 1 (`1d7f79a`) was
  FLAGGED with 6 concerns and no objection to the design. Section 8 answers each one,
  and the design is implemented in this PR. The implementation is the
  authority where the two differ, and section 8 names every difference.

## 1. The problem, with today's evidence

Several agents and sessions work on the same PRs, and nothing says who is doing what:

- **PR #137 on 2026-09-28.** Two Claude sessions posted on #137 within the hour. Bob's
  10:56 hand-off addressed "Claude" without saying which session, and repeated fixes
  that an earlier head had already settled.
- **PR #139.** The automated review and a Claude session reviewed the same head
  independently. That was harmless here, but it is duplicate work.
- **The shared checkout** was switched to other branches by other sessions while a
  session was using it. This is a local problem, and a claim does not fix it. The
  named-writer rule and private worktrees already cover it.

Two constraints shape every option:

1. **Every agent posts as `mgalic01` and holds the owner's token.** GitHub cannot tell
   the agents apart. The sender tag (amendment C, `AGENT_HANDOFF.md` "Who posted what")
   is declared attribution, not an authenticated identity. **Nothing can make ignoring
   a claim impossible.** A design can only make it hard to do by accident, visible when
   it happens, and blocked in the tools agents actually use.
2. **The handbook adds no polling service or scheduled watcher** (`AGENT_HANDOFF.md`,
   "Review delivery states"). A claim expiry cannot rely on a timer.

## 2. What a claim is

A claim is a PR or issue comment whose **first line is the sender tag** (amendment C)
and whose **second line is the command**:

```
[Claude Code e0b16be3]
/claim 24h review of head 76a7561
```

| Rule | Detail |
| --- | --- |
| **Holder** | The tag on the first line: `[Claude Code <session-id>]`, `[Codex Desktop]` or `[Bob]`. Each Claude session is a separate holder. |
| **Who can claim** | Only comments whose GitHub author is `mgalic01` (`author_association` `OWNER`). The repository is public, so any other login is ignored and cannot block a merge. |
| **Duration** | `1h` to `24h`. The default and the maximum are `24h`. The expiry is the comment's GitHub `created_at` plus the duration, so no agent's clock is involved. |
| **Renew** | The holder posts a new `/claim`, which replaces the old one. |
| **Release** | The holder posts `/release` under its tag. A holder releases as soon as its work is posted. |
| **One holder at a time** | A `/claim` from a different holder while a claim is active is **rejected**. The workflow says so on the PR at once, naming the current holder and the expiry. |
| **Owner override** | `/release all`, typed by the owner only. Agents never post it. This rule is declared, not enforced, like the tag itself. |
| **Scope** | The whole PR or issue. On a PR it covers pushing to the PR's branch and merging. It never covers comments, reviews or requests. |

**When to claim.** Before any work on a PR that will end in a push, a merge or a
review you are about to write, and that takes more than a few minutes. The branch's
named writer (the branch-ownership rules) does not need a claim to push its own branch
while no one else holds one. A claim by a reviewer, however, **also stops the writer
from pushing** until the reviewer releases. That is intended: a push in the middle of a
review makes the review stale.

**Comments are never blocked.** A comment is how an agent reaches the holder, asks for
a release or the owner's override, or requests a review.

## 3. Enforcement, in layers

The layers are ordered from the one that cannot be skipped to the ones that rely on
the agent. Each covers a different way to ignore a claim.

### L1: the `claim-guard` status and `claimed` label (GitHub, every agent)

A new workflow, `claims.yml`:

- **Runs on:** `pull_request` (`opened`, `synchronize`, `reopened`) and on
  `issue_comment` `created`. A step-level prefilter skips comments containing neither
  `/claim`, `/release` nor `/claims`. It runs no agent and uses no allowance.
- **Always checks out `main`**, never the PR head, and runs `scripts/claims.py` from
  it. A PR cannot change how its own claims are judged. The comment bodies are passed
  in environment variables and parsed in Python, never interpolated into the shell.
- **Evaluates** the claims from the PR's comments, with the rules in section 2.
- **Sets a commit status `claim-guard` on the PR's head SHA:**
  - `success`, "no active claim";
  - or `failure`, "claimed by [Claude Code e0b16be3] until 2026-09-29 11:00 UTC: review
    of head 76a7561".
- **Adds or removes the label `claimed`,** so a claim shows in the PR list. The label is
  derived by the workflow; agents never set it by hand, so it cannot go stale by
  someone forgetting it.
- **Rejects a conflicting claim** with a comment on the PR, posted as
  `github-actions[bot]`.
- **Permissions:** `statuses: write`, `issues: write`, `pull-requests: read`,
  `contents: read`.

**Expiry without a timer.** The status is recomputed at every event: a push, any
comment containing `/claims`, a `/claim` or a `/release`. After the stated expiry the
red status is stale until the next event. Posting `/claims` refreshes it. The merge
gate treats a `claim-guard` failure whose stated expiry has passed as needing a
refresh, not as a claim.

**The merge gates gain one condition:** `claim-guard` green at the full head. It goes
into the task-file bullet, the "Merging while Codex's allowance is exhausted" item 1,
the quick reference's "Merge authority" and START_HERE step 3.

**Binding on GitHub (the owner's decision, not implemented here).** `main` has no
branch protection today. A red `claim-guard` is visible but does not stop GitHub from
merging. The owner can make it binding with a ruleset that requires `claim-guard` on
`main` and allows no bypass. That is a repository setting only the owner should change;
section 6 describes the steps.

### L2: a hook in every Claude Code session (local and cloud)

A committed `.claude/settings.json` adds a **PreToolUse hook on Bash** that runs
`scripts/claims.py hook`. It acts only on:
- `gh pr merge`;
- a REST call to a PR's `/merge`;
- `git push`.

For each of these it finds the PR: the number in the command, or the open PR whose
head branch is the one pushed. It then evaluates the claims. If a holder other than
`[Claude Code <this session's id>]` has an active claim, it **denies** the command and
names the holder, the expiry and the way to reach them.

- **Session id:** the hook's input carries `session_id`. The tag uses its first 8
  characters, as today.
- **If GitHub cannot be read:** a merge is refused (fail closed). A push is allowed
  with a warning (fail open), because L1 still guards the merge.
- **Where it applies:** committed in the repository, so it covers every Claude Code
  session in any checkout of this repository, including cloud sessions. It needs a
  `.gitignore` change: `.claude/` becomes `.claude/*` with `!.claude/settings.json`,
  so worktrees and local state stay ignored.
- **Also:** the user-level PR sweep, which is outside the repository, shows each open
  PR's claim next to its head.

### L3: Bob (the owner's own Bob session)

- **`.bob/hooks/check_github_tasks.py`** (Bob's SessionStart hook) lists the active
  claims on open PRs.
- **`.bob/rules/agent-protocol.md`** gains three lines:
  1. claim before starting work on a PR;
  2. run `python scripts/claims.py check <PR> --as "[Bob]"` before a push or a merge,
     and stop if it refuses;
  3. release when done.
- If Bob's tooling supports a pre-command hook like Claude Code's, the L2 hook is added
  there too. **This is a question for Bob** (section 7).
- Bob's GitHub reviewer (`bob-review.yml`) only answers requests. It never pushes or
  merges, so it is exempt.

### L4: Codex

- **`AGENTS.md`** gets the same three lines as Bob, with `--as "[Codex Desktop]"`.
- The Codex Cloud connector only reviews, so it is exempt.
- Codex's acknowledgement is owed on return (issue #134).

### L5: every agent at session start

START_HERE step 3 gains a check between the merge state and CI:

> **Claim:** read `claim-guard` and the `claimed` label. If another holder has an
> active claim, do not push to the branch or merge. Comment to coordinate instead.

The automated review (`claude[bot]`), Bob's GitHub answers (`github-actions[bot]`) and
the Codex connector never claim and are never blocked. They only review.

## 4. What the design does not do

- **It cannot stop an agent that decides to ignore it.** Every agent has the owner's
  token and could merge through the web page or a raw API call that the hook does not
  parse. What it does:
  - it puts the claim in front of every agent at every session start;
  - it blocks the two harmful actions in Claude Code;
  - it makes any merge over a claim visible as a red status, and, if the owner adds the
    ruleset, impossible without a bypass.
- **It does not block comments or duplicate reviews.** A claim makes a duplicate
  review unlikely, not impossible.
- **It does not authenticate anyone.** A claim is as trustworthy as the tag.
- **After expiry, the status stays red until the next event.** This is the price of
  having no timer.
- **Issues get the label but no status.** An issue has no commits to put a status on.

## 5. Implementation plan (after Bob's verification)

| File | Change |
| --- | --- |
| `scripts/claims.py` | New: claim parsing and evaluation; CLI `status`, `check`, `hook` and `workflow`. Standard library only. |
| `tests/test_claims.py` | New tests:<br>• parsing: tag, login, duration bounds, default;<br>• expiry measured from GitHub's time;<br>• renew and release;<br>• conflict rejection;<br>• the owner override;<br>• a non-owner login ignored;<br>• a quoted `/claim` that is not on the second line ignored;<br>• the hook's decisions for merge, the REST merge and push (including refspecs and the current branch);<br>• fail closed for merge and open for push. |
| `.github/workflows/claims.yml` | New: section 3, L1. |
| `.claude/settings.json`, `.gitignore` | New hook and the ignore exception. |
| `.bob/hooks/check_github_tasks.py`, `.bob/rules/agent-protocol.md` | Show claims; the three rules. |
| `AGENTS.md`, `docs/AGENT_HANDOFF.md`, `docs/START_HERE.md` | The rule in section 2, the merge-gate condition, the step-3 check and pointers. |

After implementation this PR goes through Bob's deep investigation at the final head,
the automated review, green `test-and-audit` and the owner's merge rules in force.

## 6. For the owner: making it binding (optional, owner action)

Settings → Rules → Rulesets → New branch ruleset for `main`:
- "Require status checks to pass", adding `claim-guard`;
- an empty bypass list.

This also means **a PR cannot merge while its `claim-guard` status is missing**. The
workflow sets it on every PR event, so older open PRs need one comment containing
`/claims` first. I will not change repository settings myself.

## 7. Questions for Bob's deep investigation

1. **Exclusivity.** Is one holder per PR right? Should the branch's writer be allowed
   to push during a reviewer's claim?
2. **Security.** Consider:
   - the OWNER-only rule;
   - running `main`'s script with `statuses: write` and `issues: write`;
   - comment bodies passed through environment variables;
   - whether a PR can influence its own `claim-guard` result;
   - whether a quoted `/claim` inside a longer comment can create a claim.
3. **The no-polling rule.** Is lazy expiry (recomputed at the next event, or refreshed
   with `/claims`) consistent with "no polling service or scheduled watcher"?
4. **Your tooling.** Does IBM Bob support a pre-command hook like Claude Code's
   PreToolUse? If so, how is it configured?
5. **Failure modes.** Consider:
   - GitHub unreachable;
   - `git push` forms the hook could misparse;
   - a stale red status blocking a ready merge;
   - whether the automated review would read a red `claim-guard` as failing CI;
   - interaction with `quality.yml` and the Bob workflows.
6. **Contradictions.** Does anything here contradict the handbook? In particular:
   - the named-writer rule;
   - "Review delivery states";
   - the merge rules while Codex is out;
   - "What Bob must not do alone".
7. **Anything missing** that would let an agent ignore a claim by accident.

## 8. Bob's verification and the answers (revision 2)

Bob's deep investigation of revision 1 at `1d7f79a272010e2576ee7c0ec8c95766fce7e396`
was posted as a PR #141 comment: **FLAGGED, 6 concerns**. Bob found the design worth
building and proportionate. The answers are below. Everything is implemented at the
head named in the PR comment.

| # | Bob's concern | Answer, and where it lives |
| --- | --- | --- |
| 1 | The parsing rule for a quoted or fenced `/claim` is unspecified. | The command counts only when **line 2, stripped, is the command itself**. A `>` quote, a fence, a command on line 3 or later, a missing tag, the PR description and `/claims` do not count. An **edited comment no longer counts**; this closes the edit path Bob noted, because the evaluation reads the current bodies. Implemented in `parse_command`, with tests in `ParseTest`. |
| 2 | `git push` parsing is unspecified for force pushes, other remotes and full refspecs. | Parsed:<br>• `-f`, `--force` and `--force-with-lease[=…]`;<br>• `+ref`, `src:dst`, `HEAD:refs/heads/x` and `HEAD`;<br>• `--delete x` and `:x`;<br>• `--all`, `--branches` and `--mirror` (every open PR);<br>• `git -C dir`, a preceding `cd`, and redirections.<br>Skipped: `--dry-run`, `--tags` alone, and a remote whose URL is known to be another repository. An unknown remote counts as this one. If the branch cannot be read, the push is **not silently skipped**: the hook warns. Tests in `TargetTest`. |
| 3 | A stale red status must be distinguishable from an active claim without running commands. | The status description states the expiry. START_HERE step 3f and the handbook's "Reading `claim-guard`" say: past the stated expiry, the status is stale, not a claim, so post `/claims` to refresh it. They also say `claim-guard` is not CI, and `test-and-audit` stays the CI gate. |
| 4 | The exception to the named-writer rule must be explicit. | Added to rule 1 of "Branch ownership, local checks and review batches": while another agent holds an active claim, the named writer does not push either. |
| 5 | Record that IBM Bob has no pre-command hook. | Recorded here and in the handbook's "Claims" layer 3. Bob's enforcement is his session-start hook, which now lists the claims, plus the three rules in `.bob/rules/agent-protocol.md`. |
| 6 | The `.gitignore` change must land with the implementation. | It does: `.claude/*` with `!.claude/settings.json`. Worktrees and local settings stay ignored, as checked with `git check-ignore`. |

Bob's other notes, for the record:
- **The race between two near-simultaneous claims:** the earlier by GitHub's `created_at`
  (then the comment id) wins, and the later is rejected.
- **Issues:** they have no status. The handbook says to read the label and the claim
  comment.
- **A comment that contains both `@bob` and a claim:** it starts both workflows. That is
  harmless, as Bob noted.

**Differences from revision 1:**
- The workflow's comment trigger also requires `author_association == OWNER`, so a
  stranger's comment starts no run.
- The workflow skips cleanly while `main` has no `scripts/claims.py` (this PR's own
  runs).
- An owner comment whose first line is exactly `/release all` needs no tag.
- The hook also watches PowerShell commands, because Claude sessions on the owner's
  machine use both shells.
- A GraphQL `mergePullRequest` is refused unless it is done with `gh pr merge <N>`,
  because its PR cannot be read from the command.
