# Task for Bob: documentation audit (links, indexes, stale statements)

- **Written by:** Claude, 2026-09-25, at the owner's request to give Bob as much
  checking work as possible.
- **Review:** starts automatically when this file is merged, under the current merge
  rule.
- **Report:** `docs/reviews/2026-09-25-bob-docs-audit.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md).

## Why

The agents coordinate through these documents, so a wrong link or an outdated rule
sends the next agent the wrong way. Two broken task-file links were fixed by hand on
2026-09-25 alone. This task checks every document mechanically where possible and by
reading where not.

## Steps

Record `git rev-parse HEAD` first. Write each script under `data/` and give its
SHA-256 in the report.

1. **Links** (`data/links.py`, standard library only): for every tracked `*.md` file
   (`git ls-files '*.md'`), find every Markdown link `[text](target)`. Skip `http(s):`
   and `mailto:` targets. For each relative target:
   - the file or directory must exist, relative to the linking file;
   - a `#anchor` must match a heading in the target, using GitHub's slug rule:
     lowercase; remove every character that is not a letter, digit, space, hyphen or
     underscore; turn each space into a hyphen; add `-1`, `-2`, … for repeated headings.
   Report each broken link with the file, line, target and reason. Also list
   `http(s)` links to this repository (`github.com/mgalic01/...`) separately, without
   fetching them.
2. **Review index:** every file in `docs/reviews/` except `README.md` should have a
   row in `docs/reviews/README.md`, and every row's link should exist. List both kinds
   of mismatch.
3. **Task index:** for every row in `docs/tasks/README.md`, compare its status with
   what the repository shows. Is there a report in `docs/reviews/` for that task, and
   is it merged (`git log --oneline -- <report>`)? List the rows that are out of date,
   with the evidence.
4. **Rules against workflows:** read `docs/AGENT_HANDOFF.md`, `AGENTS.md`, `CLAUDE.md`,
   `README.md` and `docs/tasks/README.md`. Then read the workflows in
   `.github/workflows/`. List every statement about triggers, time limits, permissions,
   what Bob can and cannot do, and where outputs go that does not match the workflow
   files. Quote both sides with file and line.
5. **Internal contradictions:** list places where two of those documents say different
   things about the same rule. Quote both.

## Report

`docs/reviews/2026-09-25-bob-docs-audit.md`:
- the commit, and each script with its SHA-256 and exit code;
- a table for each step: file:line, the problem, the evidence, and the fix you suggest
  (the exact new text or target);
- counts per step, including zeros;
- **Ideas and proposals** (separate): for example, whether a link check should run
  in CI, with a sketch of how. Each idea says why it would help.

Suggest fixes; do not edit any tracked file. Claude applies the fixes after review.

## Stop conditions

- A tracked file changes, or anything outside `data/` and your report appears in
  `git status --porcelain --untracked-files=all`: stop and report.
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

[`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish". Re-run
`data/links.py` on your own report as well, and fix any broken link in it.
