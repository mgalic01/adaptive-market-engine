# Claude: agent-loop check after the move to Kali Linux

Index: 2026-11-08. The owner's PC was reinstalled and work moved to Kali Linux. This note records the state found on return, the loop test (Bob, Codex Cloud, the automated review, claims, CI), the docs changed for Linux, and why V4 step 5 restarts from a new B.

Written by Claude Code (session c5f98f3b). The state below was found on `main` at `c45f284`.

## State found

- No open PRs. The last merged PR is #301 (2026-10-24, the V4 step-5 plan).
- All 13 workflows are active. The last runs on 2026-10-24 succeeded.
- On #301, Bob answered `NO ISSUES` and the automated review `APPROVE`. Codex Cloud's review showed "running" for over two hours and was waived for #301 only.
- `python scripts/check_reports.py` reports 0 problems.
- The two old Windows worktree copies on the backup drive (`v4-registration-wt`, `v4-step5-wt`) equal `main` apart from CRLF line endings, so they hold no unpushed work. The old main repository on `C:` is gone, so commits that existed only there cannot be checked.
- V4 step 5 had started: data run 40122823348 succeeded at `c45f284`, and step 2 had not started. The freeze held; `main` had not moved.
- The owner confirmed that the other disks were formatted on purpose, so `F:`'s copies are gone.

## Linux notes

- `.bob/hooks/check_github_tasks.py` runs `python`, which Kali only provides inside the project's virtual environment (`.venv`).
- `scripts/claims.py` read `GITHUB_TOKEN` from the Windows registry. On Linux it needs the `GITHUB_TOKEN` environment variable.
- Python here is 3.14; the project targets 3.12. A single-core run reached about 75% of the tests with no failure before it was stopped for heat; the rest is unchecked.

## The loop test, at head `f6852e3`

- Bob answered `NO ISSUES`, Codex Cloud completed with no findings, the automated review posted `APPROVE`, and `claim-guard` was green.
- `test-and-audit` failed only on `pip-audit` (CVE-2026-114613 in `msgpack` 1.2.2); pytest passed, with 8710 passed and 4 skipped. PR #303 fixed it. The owner gave the go to merge and repeat the checks.
- Not tested: Codex Desktop on Kali and the separate local reviewer.

## A corrupted file on the PC

The first clone's pack file failed `git verify-pack` (`inflate returned -3`), and its content no longer matched the checksum in its own trailer. The bytes read back the same each time, so the damage was stored on disk. The kernel logged no I/O error and the system disk's SMART check passed. A new clone verified clean, the pack was replaced from it, `git fsck --full` then passed, and every working file matched. The cause is unknown; the RAM is untested. The registered run does not depend on this PC, but the copies of its results do, so the plan now says to check each copy after writing it.

## What this PR changes

Documents only, before the new B: this note, the step-5 plan's amendment, the run archive's Kali section and the two repeated runs, and short corrections in `START_HERE`, `AGENT_HANDOFF` and `LOCAL_WORKER`. Nothing under `src/`, `scripts/`, `tests/`, `.github/` or `config/` changes, and neither does the V4 spec.
