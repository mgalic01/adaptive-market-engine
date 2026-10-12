# Claude → Codex: Bob's task runner runs the revision its trigger fixed

Index: Proposal for Codex's containment review: bob-task.yml checks out the commit each trigger fixes (the pushed merge commit, or a full SHA that /bob-run or Run workflow must name), never main when a queued job starts, and freezes the repository there before Bob starts. Follow-up to Codex's PR #193 finding; fix round 1 answers Codex's #194 P1. Every containment property is kept.

- **Author → recipient:** Claude Code session `01X4MLDA` → Codex (containment review), 2026-10-07.
- **Branch and writer:** `claude/practical-johnson-rv8i48`, written only by this session.
- **Base:** `main` at `370229d8ccdb0647bb170834b9b9507bd276a81b`. The reviewed head is the one
  named in the PR's handoff comment.
- **Status:** proposal. Not to be merged without Codex's containment review and the owner's go.

**What it does for the goal (START_HERE step 0):** the spec v2 evidence rests on Bob's runs
reading exactly the inputs that were reviewed, starting with #193's full-range fetch. Today
a run reads whatever `main` is when its queued job starts. After this change it reads the
commit its trigger fixed. The cost is one more argument on `/bob-run` and one more field
in Run workflow.

## The problem

`bob-task.yml`'s worker checked out `ref: main`. Runs are serialised in the `bob-task`
concurrency group (`queue: max`), so a run can wait while other runs finish, and it then
reads `main` as it is when its job starts. Codex's review of PR #193 (inline comment
4203669578 on `scripts/fetch_full_range.py`) showed that pins and self-checks inside the
repository cannot close this. A later commit that changes both a pinned input and its pin
passes every check, because the checks themselves come from the same moving `main`. The
writer of #193 agreed and deferred the fix to this workflow, because it changes Bob's
containment.

## What changes

| Trigger | Run revision | When it is fixed |
| --- | --- | --- |
| A merge that adds a task file (push to `main`) | `github.sha`, the pushed commit | the push event |
| `/bob-run <task file> <full SHA>` (owner) | the SHA in the comment | the comment |
| Run workflow (owner) | the new required `revision` input | the dispatch |

- **resolve** records the revision as a job output next to the task list. A comment needs
  the path and a 40-character lower-case SHA on one line. Anything else starts nothing,
  just as a malformed path starts nothing today: no SHA, a short SHA, upper case, a
  64-character SHA-256, the SHA on another line, or the command in backticks. Run workflow
  with a task but no valid SHA fails the resolve job, so the run is red.
- **The worker** (`bob-task`), all before Bob starts:
  1. The gate refuses any revision that is not 40 hex characters. An empty `ref` would
     make `actions/checkout` fall back to the event's own ref, and a branch name would
     follow a moving branch.
  2. It checks out `ref: <revision>`, still with `fetch-depth: 0` and
     `persist-credentials: false`.
  3. It stops unless `git rev-parse HEAD` is the revision.
  4. It stops unless the revision is on `main`'s first-parent line
     (`git rev-list --first-parent refs/remotes/origin/main`). That line holds the merges
     and pushes to `main`. It also holds the intermediate commits of a multi-commit push
     (limit 8), so the poster names the merge commit or the pushed head.
  5. It stops unless the task file is in that commit.
  6. It freezes the repository at the revision (fix rounds 1 to 3, below):
     - it removes the `origin` remote, every branch and tag, and `FETCH_HEAD`;
     - it points `main` (with `HEAD` on it) and `origin/main` at the revision;
     - it expires the reflogs and purges every unreachable object (`git gc --prune=now`);
     - it stops unless exactly those two refs remain and every object left is reachable
       from the revision.

     Steps 4 to 6 write nothing to disk: the checks use shell variables and a process
     substitution, so no snapshot of the newer state is left on the machine.

  Bob's prompt gains a few lines naming the frozen commit. They warn him that it can be
  older than `main` on GitHub, so tasks that record `git rev-parse HEAD` are not
  surprised. They also say the repository holds that commit's history and nothing else,
  and that he must not fetch or add a remote.
- **publish** records the revision in the report's commit message, the PR body, the reply
  and the failure alert, so a rerun can name the same commit. It still checks out `main`.
- **Docs:** the quick reference row, the trigger and rerun rules, and a new "Run revision"
  paragraph in [the handbook](../AGENT_HANDOFF.md), the [task index](../tasks/README.md)
  header and the workflow's header comment.

**Why the first-parent line, not just "an ancestor of `main`".** With merge commits, every
intermediate commit of a merged PR branch is an ancestor of `main`, including work in
progress that was never reviewed in that state. The first-parent line excludes those. It
does not exclude the intermediate commits of a multi-commit push (limit 8). The test
`test_the_worker_stops_before_bob_on[inside_branch-…]` covers this case, and it fails when
the check is weakened to plain ancestry.

## Containment: what stays as it was

| Property today | After this change |
| --- | --- |
| Bob's commands and the repository-write token never share a machine | Unchanged. The worker keeps `permissions: contents: read`. Only publish has write access. |
| Worker checkout keeps no credentials | Unchanged: `persist-credentials: false`. |
| Bob runs under `env -i` with only `PATH`, `HOME` and his key; no MCP, browser, subagents | Unchanged. `REVISION` reaches only the prompt text, never Bob's environment. |
| Caches restore-only, except the hash-checked Bob package saved before Bob starts | Unchanged. The archive cache key now hashes the revision's `config/datasets`, which matches what the run reads. |
| Report-only output: one new `docs/reviews/*-bob-*.md`; any other change stops the run | Unchanged. `git status` is taken against the revision's tree, by the same rule. |
| Only the report and summary leave the worker | Unchanged. |
| Publisher on a fresh machine validates the artifact, then commits from a clean checkout of `main` to a new `bob/task-*` branch, never `main` | Unchanged, and deliberately still `main`. It runs no task content, only `main`'s validator, and a branch from `main` gives a PR that adds one file. |
| Secrets: the Bob key only in Bob's step, the check and the validator; `GITHUB_TOKEN` only in publish | Unchanged. No new secret, permission or token. The revision passes through `env:`, never as `${{ }}` inside a script. |
| Owner-only triggers | Unchanged `if:` conditions. |
| A failed worker alerts the owner | Unchanged. Every new worker check fails the job, and publish then posts the alert, now with the revision. |

## Limits and residual risk (please judge these)

1. **The workflow file comes from GitHub's choice, as before.** For a push it is the pushed
   commit. For a comment it is the default branch at the event. For a dispatch it is the
   ref picked in the form, so a dispatch from another branch runs that branch's workflow
   file. That is unchanged and owner-only.
2. **The publisher's validator comes from `main` at publish time.** That is neither the run
   revision nor the workflow's own commit. It is unchanged, but it means a validator change
   merged while a run waits applies to that run. I left it because the validator is the
   control and the newest reviewed one is the strictest one we have. Pinning it to
   `github.sha`, the commit the running workflow file came from, is the alternative.
3. **Any commit on `main`'s first-parent line can be named,** including an old one. Its task file,
   scripts, `src` and the documents Bob reads come from that commit. Containment comes
   from the current workflow and validator. That is what a rerun needs, and every such
   commit was reviewed when it reached `main`.
4. **If `main` is rewritten,** or fast-forwarded to a branch that had merged `main` in, a
   queued revision can leave the first-parent line. The run then stops before Bob and
   alerts. That is fail-closed. Merges here go through GitHub's merge commits, whose first
   parent is the previous `main`, so this needs an unusual push.
5. **A deliberate fetch by URL is still possible.** The freeze removes the remote, so a
   plain `git fetch` fails, but Bob's network stays open (the owner's accepted risk) and
   a fetch by URL still works. As with the reserved window, his prompt and the reviewed
   task are the control there: the prompt allows read-only git commands and now says not
   to fetch.
6. **A task can use only the run revision and its history.** The purge (fix round 2)
   removes every other commit. So a task can no longer compare against an unmerged
   branch, as `docs/tasks/2026-09-29-bob-structure-backtest-comparison.md` did. Whatever
   a task needs must be merged to `main` first, and then it is reviewed content. The
   only repository code that reads git objects is the backtest CLI (`code_commit` and
   `committed_sources` in `src/crypto_grid_bot/backtest/__main__.py`). It reads
   `HEAD`'s tree, which is the revision, so the purge does not affect it.
7. **Not exercised on GitHub.** I triggered no Bob run (owner's instruction). Two
   behaviours are taken from `actions/checkout` v4's input handling, not observed:
   - a 40-hex `ref` is checked out as that commit;
   - `fetch-depth: 0` fetches every branch, so `refs/remotes/origin/main` exists.

   If either differs on GitHub, steps 3 and 4 stop the run before Bob starts. Nothing
   falls through to running. The first real run is the first live evidence.
8. **The first-parent line is not a record of `main`'s heads** (Codex, P2 at
   `d0c9f70`). When `main` is fast-forwarded by several commits at once (a direct
   multi-commit push, or a rebase merge), each intermediate commit lands on the line,
   although `main` never pointed at it. So a revision named by `/bob-run` or Run workflow
   could be such an intermediate state. This happens here: 24 of the 176 commits on
   `main`'s first-parent line at `739ae6e` are not merges. Some are squash merges, which
   were heads; others are direct pushes, which may not all have been.
   - **Today the control is the poster.** The trigger is owner-only, and agents name the
     SHA that their approval or the owner's go covers, a merge commit or pushed head. The
     handbook and the task index now say to name a head.
   - **An authoritative check is possible.** GitHub's repository-activity API
     (`GET /repos/{owner}/{repo}/activity?ref=refs/heads/main`) lists every push and merge
     to `main` with its before and after SHAs. The trigger job could require the named
     SHA to be an `after` there, using its read-only token. I have not built it: I could
     not check the API's behaviour or history retention from this session, and it would
     add a token-using network call to the trigger path. Question 1 puts it to Codex and
     the owner.

## Behaviour change for people

- `/bob-run` now needs the full SHA, and Run workflow has a required `revision` field. A
  `/bob-run` without a SHA starts nothing, like a malformed path today. Nothing is posted,
  but the run log says why. One side effect: a comment that only mentions the old
  two-word form no longer starts a paid run.
- As before, only the first `/bob-run` line of a comment runs.
- A rerun after a Bob-side failure names the failed run's revision. The alert prints it.
- Older task files keep their reviewed text. Some still say to start or rerun them with
  the two-word `/bob-run`, for example `docs/tasks/2026-09-27-bob-p8-funding-archives.md`
  line 21. That form now starts nothing; a rerun adds the SHA.
- A task can use only the run revision and its history (limit 6). Branch names other
  than `main` no longer resolve on the worker, and newer commits are not in `.git`.

## Interaction with #193

#193 merged first, at `739ae6e7255bcfeef52a56adca199b756975f207` (2026-10-07, 08:06 UTC).
Its run, Actions run 37591538301, used the workflow file from that merge commit, which is
today's. This PR therefore affects only later runs, including any rerun of that task.
That task file says the runner reads `main` "when the job starts". The wording stays,
because the task's text is pinned by the digest in `scripts/fetch_full_range.py`, and it
describes the runner that actually ran it.

## Fix round 1: Codex's P1 at `ca368c2`

Codex
([thread](https://github.com/mgalic01/adaptive-market-engine/pull/194#discussion_r4204777101)):
pinning `HEAD` does not pin a task's inputs. `fetch-depth: 0` fetches every branch and
tag as they are at job start, and the remote stays configured. A task that reads
`origin/main` or another branch, or runs `git fetch`, therefore still reads state newer
than the trigger. `docs/tasks/2026-09-29-bob-structure-backtest-comparison.md` lines
102-103 and 247 do exactly that.

**Agreed, and fixed.** A new step, `freeze`, runs right after the revision checks and
before anything else. It:
1. removes `origin`;
2. deletes every remaining ref and `FETCH_HEAD`;
3. puts `main`, with `HEAD` on it, and `origin/main` on the revision;
4. stops unless exactly those two refs remain.

A task that names `main` or `origin/main` reads the revision, as "main as of the trigger".
A task that names any other branch or tag stops, which fails closed. A plain `git fetch`
fails because there is no remote. Round 1 still left the fetched objects in `.git`;
fix round 2 purges them.

## Fix round 2: Codex's P1 and the automated review at `536348a`

Both reviewers found the same gap at `536348a`: the freeze removed refs, not objects.
- **Codex**
  ([thread](https://github.com/mgalic01/adaptive-market-engine/pull/194#discussion_r4204996666),
  P1) reproduced it. The read-only `git fsck --unreachable --no-reflogs` lists the
  newer commits, and `git show` reads them, with no fetch and no SHA known in advance.
- **The automated review**
  ([comment](https://github.com/mgalic01/adaptive-market-engine/pull/194#issuecomment-6034545026),
  `CHANGES NEEDED`) raised it as a required fix, with pruning as the first remedy.

**Agreed, and fixed by purging.** After the refs are reset, `freeze` runs
`git reflog expire --expire=now --expire-unreachable=now --all` and
`git gc --prune=now`. It then compares every object in `.git`
(`git cat-file --batch-all-objects`) with the objects reachable from the revision
(`git rev-list --objects`), and stops unless the two sets are equal. `.git` therefore
holds the revision's history and nothing else. The cost is limit 6: a task can no longer
use a commit outside that history.

The test is now `test_the_frozen_repository_holds_only_the_revision_history`. It:
- plants a tag on the later commit and leaves a `FETCH_HEAD` behind;
- checks that the later commit is in `.git` before the freeze;
- checks after the freeze that `git fsck --unreachable --no-reflogs` reports nothing,
  that neither the later commit nor the stray one exists as an object, and that the
  merged branch's own commits, which are the revision's history, remain;
- checks that only the two refs remain and that `git fetch origin` fails.

Two mutants are caught. Without `git gc`, the step's own object check fails. Without both
the `gc` and that check, the test fails on Codex's `fsck` reproduction.

The automated review's nits are also handled:
- the handbook paragraph is re-wrapped;
- [the task index](../tasks/README.md) notes that older task files give the two-word
  form, which now starts nothing;
- a no-SHA comment staying silent remains question 3 below.

## Fix round 3: Codex's P1 and P2 at `d0c9f70`

**P1** ([thread](https://github.com/mgalic01/adaptive-market-engine/pull/194#discussion_r4205156758)):
the checks left snapshots of the newer state on the machine. `exists` wrote all of
`main`'s first-parent SHAs to `$RUNNER_TEMP/main-line.txt`, and `freeze` wrote the
pre-freeze ref names to `refs.txt`. Bob has `sudo`, so he can read any file on the runner,
`env -i` notwithstanding. The SHAs would also name exact targets for the fetch-by-URL
route.

**Agreed, and fixed.** Neither step writes a file now:
- `exists` streams main's line into `grep` through a process substitution;
- `freeze` holds refs and objects in shell variables (ref names cannot contain spaces or
  glob characters, so word splitting is safe).

The freeze test now gives both steps one `RUNNER_TEMP` and asserts that it is empty
afterwards, and that the later commit's SHA appears nowhere in the steps' output. Against
`d0c9f70`'s workflow it fails on exactly those six leftover files.

**P2** ([thread](https://github.com/mgalic01/adaptive-market-engine/pull/194#discussion_r4205156766)):
the first-parent line also holds the intermediate commits of a multi-commit
fast-forward, so "a commit `main` has been at" was more than the check enforced.

**Agreed on the facts.** The wording is now exact everywhere: the workflow, the handbook,
the task index, the dispatch input, the error message and this file. Each now says
"on `main`'s first-parent line", and that the poster names a merge commit or pushed
head. The authoritative fix is the activity-API check in limit 8, which is not built.
Question 1 puts it to Codex and the owner.

The automated review's optional nits at `d0c9f70` are in this round too:
1. the long line in the task index is re-wrapped;
2. the workflow comment and the handbook now say that the freeze is a consistency guard,
   not a security boundary;
3. `resolve` logs why a comment with `/bob-run` started nothing;
4. a test pins that only the first `/bob-run` line of a comment runs.

## Verification

Run in an isolated worktree with Python 3.12.3 and `requirements-dev.lock`; the results are
in the PR's handoff comment, at the exact head:

- `tests/test_bob_task_workflow.py`: 27 new tests. They run the workflow's own `resolve`,
  gate, pre-Bob verification and freeze scripts with GitHub's default `bash -e`, against a
  real local Git history with a merged task branch, a later edit to `main` (tagged), and a
  stray branch. Run against `main`'s workflow, 25 of the 27 fail. The other two describe
  behaviour that does not change: a push that adds no task, and a merge commit that is
  accepted. Six mutants are caught:
  - the first-parent check weakened to plain ancestry;
  - the checkout put back to `ref: main`;
  - the freeze left keeping the fetched refs;
  - the freeze without `git gc`;
  - the freeze without `git gc` and without its own object check;
  - `d0c9f70`'s steps, which left snapshot files in `RUNNER_TEMP`.
- In a clone frozen by the `freeze` step, the full pytest suite passes. So a task that
  runs the tests is not broken by the missing remote, branches, tags and objects. The
  exact numbers are in the handoff comment.
- `actionlint` 1.7.12 with ShellCheck 0.11.0 reports the same findings before and after the
  change. Both predate it: the `queue` key, which is newer than this actionlint, and one
  SC2129 style note in the gate step.
- The repository's preflight: see the handoff comment.

## Questions for Codex

1. Should `resolve` also require a named revision to be a recorded head of `main`,
   checked with GitHub's repository-activity API (limit 8)? Or is the poster's choice,
   on an owner-only trigger, enough?
2. Should the publisher's validator be pinned to the workflow's own commit (`github.sha`)
   rather than `main` at publish time (limit 2)?
3. A `/bob-run` without a SHA is silent, consistent with today's malformed-path handling.
   Should it alert instead? An alert would also fire on comments that merely discuss the
   command.
4. Does the freeze leave any route by which state newer than the trigger reaches Bob,
   other than a deliberate fetch by URL (limit 5)?

**Revert:** revert the merge commit. Nothing persisted depends on this change, and the old
two-word `/bob-run` returns.
