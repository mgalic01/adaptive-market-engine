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
     (`git rev-list --first-parent refs/remotes/origin/main`). That line holds the commits
     `main` itself has been at.
  5. It stops unless the task file is in that commit.
  6. It freezes the repository at the revision (fix round 1, below). It removes the
     `origin` remote, every branch and tag, and `FETCH_HEAD`, then points `main` (with
     `HEAD` on it) and `origin/main` at the revision. It stops unless exactly those two
     refs remain.

  Bob's prompt gains a few lines naming the frozen commit. They warn him that it can be
  older than `main` on GitHub, so tasks that record `git rev-parse HEAD` are not
  surprised, and tell him not to fetch or add a remote.
- **publish** records the revision in the report's commit message, the PR body, the reply
  and the failure alert, so a rerun can name the same commit. It still checks out `main`.
- **Docs:** the quick reference row, the trigger and rerun rules, and a new "Run revision"
  paragraph in [the handbook](../AGENT_HANDOFF.md), the [task index](../tasks/README.md)
  header and the workflow's header comment.

**Why the first-parent line, not just "an ancestor of `main`".** With merge commits, every
intermediate commit of a merged PR branch is an ancestor of `main`, including work in
progress that was never reviewed in that state. On the first-parent line are only the
merges and pushes that `main` actually pointed to. The test
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
3. **Any commit `main` has been at can be named,** including an old one. Its task file,
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
6. **Not exercised on GitHub.** I triggered no Bob run (owner's instruction). Two
   behaviours are taken from `actions/checkout` v4's input handling, not observed:
   - a 40-hex `ref` is checked out as that commit;
   - `fetch-depth: 0` fetches every branch, so `refs/remotes/origin/main` exists.

   If either differs on GitHub, steps 3 and 4 stop the run before Bob starts. Nothing
   falls through to running. The first real run is the first live evidence.

## Behaviour change for people

- `/bob-run` now needs the full SHA, and Run workflow has a required `revision` field. A
  `/bob-run` without a SHA starts nothing and says nothing, like a malformed path today.
  One side effect: a comment that only mentions the old two-word form no longer starts a
  paid run.
- A rerun after a Bob-side failure names the failed run's revision. The alert prints it.
- Older task files keep their reviewed text. Some still say to start or rerun them with
  the two-word `/bob-run`, for example `docs/tasks/2026-09-27-bob-p8-funding-archives.md`
  line 21. That form now starts nothing; a rerun adds the SHA.
- A task that needs a commit other than the run revision names its SHA. Branch names
  other than `main` no longer resolve on the worker.

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
fails because there is no remote. The commits that `fetch-depth: 0` brought in stay in
the object store but are reachable from no ref, so only a SHA that a reviewed task names
explicitly reaches them, and a SHA's content cannot move. The test
`test_the_frozen_repository_holds_only_the_revision` covers this case. It plants a tag
on the later commit, leaves a `FETCH_HEAD` behind, and checks that only the two refs at
the revision remain, that neither the later commit nor the stray commit is reachable,
and that `git fetch origin` fails.

## Verification

Run in an isolated worktree with Python 3.12.3 and `requirements-dev.lock`; the results are
in the PR's handoff comment, at the exact head:

- `tests/test_bob_task_workflow.py`: 26 new tests. They run the workflow's own `resolve`,
  gate, pre-Bob verification and freeze scripts with GitHub's default `bash -e`, against a
  real local Git history with a merged task branch, a later edit to `main` (tagged), and a
  stray branch. Run against the unchanged workflow, 24 of the 26 fail. The other two
  describe behaviour that does not change: a push that adds no task, and a merge commit
  that is accepted. Three mutants are caught:
  - the first-parent check weakened to plain ancestry;
  - the checkout put back to `ref: main`;
  - the freeze left keeping the fetched refs.
- In a clone frozen by the `freeze` step, the full pytest suite passes. So a task that
  runs the tests is not broken by the missing remote, branches and tags. The exact
  numbers are in the handoff comment.
- `actionlint` 1.7.12 with ShellCheck 0.11.0 reports the same findings before and after the
  change. Both predate it: the `queue` key, which is newer than this actionlint, and one
  SC2129 style note in the gate step.
- The repository's preflight: see the handoff comment.

## Questions for Codex

1. Is the first-parent rule the right line for "a commit `main` has been at"?
2. Should the publisher's validator be pinned to the workflow's own commit (`github.sha`)
   rather than `main` at publish time (limit 2)?
3. A `/bob-run` without a SHA is silent, consistent with today's malformed-path handling.
   Should it alert instead? An alert would also fire on comments that merely discuss the
   command.

**Revert:** revert the merge commit. Nothing persisted depends on this change, and the old
two-word `/bob-run` returns.
