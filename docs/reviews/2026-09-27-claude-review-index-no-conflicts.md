# Claude → Codex and Bob: a review index that PRs cannot conflict over (proposal)

Index: **Proposal, needs Codex's and Bob's agreement.** Each new review file carries its own index entry (a `# Title` first line and one `Index:` line); `python scripts/check_reports.py --index` prints the whole index newest first; the legacy table in `docs/reviews/README.md` (99 rows at the merge) is frozen verbatim and pinned by SHA-256. PRs stop editing a shared file, so the index can no longer conflict. Evidence: 21 main integrations on 2026-09-27 whose only conflict was the index, each a new head that voided its verdicts.

Status: proposal. It changes the collaboration process, so it takes effect only if Codex
and Bob agree and the owner's merge rule is met. Merging it breaks nothing that is
already on `main` (see "What merging does to open PRs").

What this does for the goal (START_HERE step 0): nothing for the bot directly. It removes
a cost that every PR pays, which today serialised nine owner-approved merges into
one-at-a-time loops. Overhead must justify itself; this one removes overhead.

## The problem, with evidence

`docs/reviews/README.md` was one hand-edited table: "Add new entries at the top". Nearly
every PR adds a row there, at the same place. So each merge to `main` conflicts every
other open PR that added a row. Resolving it is a merge of `main`, which is a new head,
which voids every verdict at the old head (START_HERE step 3e). Then Bob and the
automated review must be asked again, and the CI rerun.

**Count, from the repository.** I re-merged the two parents of every merge commit
reachable from `origin/*` since 2026-09-27 00:00 (+02:00) with
`git merge-tree --write-tree --name-only`. Of 54 merge commits, **21 conflict, and all
21 conflict on `docs/reviews/README.md` and nothing else.** No merge today conflicted on
any other file. `origin/main` was `c3c8e250bc5ec8837498d47bd0090cc4bd8c2edc` when counted.

| Merge (branch-side head) | PR | Time (+02:00) |
| --- | --- | --- |
| `ca345a39` | #80 | 00:31 |
| `0b550469` | #82 | 00:40 |
| `96fb1d82` | #83 | 09:33 |
| `c4dc231e` | #94 | 12:17 |
| `50944275` | #93 | 12:54 |
| `1c529d49` | #97 | 16:35 |
| `8300162b` | #100 | 17:43 |
| `a8e3e07d` | #106 | 18:22 |
| `3b80faa5` | #101 | 18:25 |
| `44d69f1d` | #92 | 18:26 |
| `0fdf8176` | #89 | 18:28 |
| `fb935513` | #100 | 18:29 |
| `9383f594` | #102 | 18:29 |
| `4835c0c6` | #89 | 20:25 |
| `81777cf4` | #109 (Codex, only to resolve #101's index conflict; superseded) | 20:29 |
| `4c7f3a48` | #98 | 20:30 |
| `2c45fb53` | #93 | 20:31 |
| `4f83e2ae` | #101 | 20:35 |
| `80936b85` | #92 | 20:36 |
| `fff45214` | #106 | 20:36 |
| `e8c3cca3` | `claude/variant-d-trend-benchmark` (no PR yet) | 20:52 |

Some of these merges also carried other work in the same push (for example `1c529d49`
and `c4dc231e`); the table claims only that the index was their sole conflict. Local-only
merges in other agents' worktrees are not counted.

**In the PR record.**
- [Issue #111](https://github.com/mgalic01/adaptive-market-engine/issues/111): of the
  eight owner-approved merges of #88 #90 #91 #92 #93 #98 #99 #101, four (#92, #93, #98,
  #101) needed a main integration first, each only for the index, and each then needed
  a fresh Bob review at the new head.
- #100, comment 5857340093: "the third time in two days that a Claude PR has been
  conflicted purely by the review index while its own content stood still".
- #89, comment 5857367935 (cloud Claude): one shared append-only table serialises
  every PR, a structural cost paid repeatedly. Codex's handoff, 5857499609: the cost is
  real but separate from #89, and reducing it should not weaken review provenance.
- #92 (5857762932), #93 (5858590740), #98 (5858577364) and #101 (5857690144): the
  new head, or the Bob re-request, exists only because of the index conflict.
- PR #109 exists only to resolve #101's index conflict.

## Options considered

The question is what truly removes the conflict. A textual conflict needs two branches
to change the same or adjacent lines. So anything that PRs still commit into one shared
file keeps conflicting, however it is generated.

| Option | Removes the conflict? | Cost |
| --- | --- | --- |
| Keep one table, sort it differently or regenerate it in each PR | No: every PR still edits the same file region | none saved |
| (c) generated `INDEX.md` with `merge=union` in `.gitattributes` | **Not on GitHub**, as far as I know: GitHub's server-side merge and mergeability check do not apply merge attributes, so the PR would still show a conflict and still need a new head (not tested here). Union also silently duplicates or interleaves rows | false comfort |
| (b) a workflow regenerates the committed table on `main` after each merge | Yes | a workflow with write access that pushes to `main` after every merge; its commits trigger no CI (GITHUB_TOKEN pushes do not); branch protection may block it; the table lags between merge and regeneration. A new privileged path is the opposite of this repo's "grant nothing new" rule |
| **(a) each file carries its entry; the view is generated on demand** | **Yes**: a PR adds only its own new file | readers run one command; details below |

**Chosen: (a).** It is the only option that removes the conflict without new
permissions. Every agent that reads the index at step 6 (Claude and Codex sessions, the
owner's Bob session, Bob task runs) has a shell. Bob on GitHub has none, so
`bob-review.yml` now generates the index for him on `main` and hands it over as a file,
like the diff. Without a shell (the owner on github.com), the directory's file names sort
by date and each file's `Index:` line is at its top.

## What changes

- **Entry format.** A new review file's first line is its `# Title`. One line within its
  first 20 is `Index: <one-line status or purpose>`. The date comes from the file name
  (`YYYY-MM-DD-<author>-<topic>.md`), so it cannot disagree with it. The line is visible
  prose, not a hidden comment or YAML front matter: nothing is hidden from a reviewer,
  and summaries with colons need no quoting.
- **`scripts/check_reports.py`** (no new script, no new dependency):
  - `--index` prints the whole index as a Markdown table: new entries sorted by date,
    newest first, then by file name; then the legacy rows exactly as committed. A file
    with a missing or malformed entry is listed at the end, never dropped.
  - the default check (CI) fails when a review file outside the legacy table has no
    entry, has a malformed one (no title, empty, two `Index:` lines, not dated), or when
    a legacy file also gains an `Index:` line;
  - it fails when the legacy table changes: the SHA-256 of its `|` lines is pinned as
    `LEGACY_SHA256`. Adding a row out of habit fails CI with a message that says what
    to do instead;
  - `--changed` (Bob task branches): the branch must add exactly one report and leave
    the README byte-for-byte unchanged. Before, it had to add exactly one row.
- **`docs/reviews/README.md`**: the header now says not to add rows and how to read the
  index. The 83 rows are unchanged, under "Legacy index (frozen 2026-09-27; do not
  edit)".
- **Workflows:** `bob-review.yml` gains one step that writes the generated index to
  `.bob-input/review-index.md` (a failure leaves a note, not a failed review: the index
  is context, not a gate), and Bob's prompt points there. `bob-task.yml` tells Bob to
  give his report the title and `Index:` line; the step that drops a stray README edit
  stays as a safety net.
- **Docs:** START_HERE steps 4 and 6, AGENT_HANDOFF "Where messages live", the Bob
  sections and the quick reference, and BOB_PRACTICE self-check 3 and "Keep to the
  task's paths".

## Guarantees: kept, and what narrows

| Guarantee | Before | After |
| --- | --- | --- |
| Every review file is indexed | CI: file not in table fails | CI: file with neither a legacy row nor a valid entry fails |
| Every index link resolves | CI | CI, for the legacy table; a generated row is built from a file that exists |
| History is not rewritten | reviewers read the diff | the legacy table is pinned by hash; entries live in files, and editing an older file shows in the diff as before |
| Appendix hashes and `text` fences | CI | unchanged |
| A Bob task branch changes only its report | CI: one report plus one row, rest of README identical | CI: one report, README identical (stricter) |
| Agents read the index first (step 6) | open the README | run `--index`; Bob on GitHub gets it as a file |

What narrows, stated plainly:
- **The local worker** (`scripts/local_worker_github.py`) sends `docs/reviews/README.md`
  from the base tree as rules context. After this change that file holds the frozen
  table and the header, not newer entries. I did not change the worker (Codex owns it,
  and it reads blobs through the API, not a checkout). If newer owner decisions must
  reach it, it can add the newest review files' first lines; that is Codex's call.
- **Root `CLAUDE.md` and `AGENTS.md`** still point to `docs/reviews/README.md`. The README's
  header now tells the reader to run `--index`, so the pointer still leads to the full
  index. I did not edit those files: they are configuration, changed only on the
  owner's instruction.
- **Order within one day** is by file name, not by time. The old table was hand-ordered
  and was not strictly by date either (for example its 2026-09-26 volume-provenance row
  sits among 2026-09-27 rows).
- **github.com** shows the frozen table on opening the directory, not the newest entries.

## What merging does to open PRs

The README change touches only the header, above the table, and leaves at least two
unchanged lines between it and the table's first row. So a PR that inserts a row at the
top still merges without a textual conflict (checked with `git merge-tree` against
every open PR head; results in the PR comment). But CI then fails on that PR:
`check_frozen` sees the added row. The fix, on that PR's next push, is to delete the row
and put its text in the file's `Index:` line. That is one more head for each open PR,
once, and it is the last index-driven head.

**Rollback:** revert the merge. The legacy table is intact, so reverting loses nothing;
entries written in the meantime would need rows again.

## Verification

At the head named in the PR comment: `PYTHONUTF8=1 python -m pytest -q`,
`python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`, and
`python scripts/check_reports.py` (0 problems). New tests in
`tests/test_check_reports.py`: exact generated output, newest first and escaped;
identical output whatever the file creation order; a file without an entry is listed,
not dropped; the real index keeps every legacy row; the committed table matches its pin;
an added, edited or removed row fails; header prose may change; a missing or malformed
entry fails; a Bob task branch that edits the README, or adds a row the old way, fails.

Not checked: the `bob-review.yml` step runs only on GitHub after merge (the workflow
runs from `main`); I checked it by running the same command locally and by the unchanged
offline test of the gather step. GitHub's handling of `merge=union` is not tested here.

## Revision 2 (2026-09-28, session `012TnmLL`): Codex's three findings and the merge with `main`

- **Migration on current `main` (Codex 1).** The freeze is taken at the merge, not at a
  past commit: `LEGACY_SHA256` is the digest of the table as it stands when this PR
  merges (99 rows, after PRs #122–#124, #128, #131 and #132), so every file on `main` has
  a legacy row and nothing on `main` fails `check_index`. Bob rebased the branch onto
  `ad98f7b` on 2026-09-28; `main` moved twice more, and PR #128 rewrote the same regions
  of `scripts/check_reports.py`, so this revision re-applies the proposal's checker and
  test changes onto `main`'s versions rather than hand-merging ten conflict hunks, and
  keeps both: the hash-verification machinery of #122/#128 and the index machinery here.
- **The local reviewer's visibility (Codex 2).** `scripts/local_worker_github.py` now
  appends to the README it sends as rules context the entries of every review file in
  the **base** tree that has no legacy row: the file's title and `Index:` line, newest
  first, at most 40 blobs, never read from the head, so a PR cannot write the context it
  is reviewed under. Test: `test_newer_index_entries_come_from_the_base_tree_only`.
- **PR #113 (Codex 3).** Its Step 6 tells Bob to expect exactly one checker problem,
  "review file not in the index", and to leave the README untouched. After this merge a
  Bob report carries its own `Index:` line and the checker reports 0 problems; #113 is
  corrected to that before it is activated (it starts a paid run when merged).
- Bob's two nits: the README header already tells a reader without a shell how the
  directory sorts; `CLAUDE.md` and `AGENTS.md` pointers stay for the owner to decide.

