# Claude: agent-loop check after the move to Kali Linux

Index: 2026-11-08. The owner's PC was reinstalled and work moved to Kali Linux. This note records the state found on return and is the test PR for the loop: Bob's review, the automated Claude review, claims and CI.

Written by Claude Code (session c5f98f3b), on `main` at `c45f284`.

## State found

- No open PRs. The last merged PR is #301 (2026-10-24, the V4 step-5 plan).
- All 13 workflows are active. The last runs on 2026-10-24 succeeded.
- On #301, Bob answered `NO ISSUES` and the automated review `APPROVE`. Codex Cloud's review showed "running" for over two hours and was waived for #301 only.
- `python scripts/check_reports.py` reports 0 problems.
- The old Windows worktree copies on the backup drive equal `main` apart from CRLF line endings, so no unpushed work was lost.

## Linux notes

- `.bob/hooks/check_github_tasks.py` runs `python`, which Kali only provides inside the project's virtual environment (`.venv`).
- `scripts/claims.py` read `GITHUB_TOKEN` from the Windows registry. On Linux it needs the `GITHUB_TOKEN` environment variable.
- Python here is 3.14; the project targets 3.12. A single-core run reached about 75% of the tests with no failure before it was stopped for heat; the rest is unchecked.

## What this PR checks

It changes only this file. It asks `@bob` for a review, to confirm Bob, the automated review and `claim-guard` still respond.
