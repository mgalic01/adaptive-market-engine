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

## The runs repeated on the final code, 2026-11-09

PR #304 (100 USDT, v4-d30, and the runner pin) merged at `5e3ed10`. On that commit, rehearsal 42581586528 and timing run 42583987899 both succeeded on the pinned `ubuntu-24.04` machines, and every timing number is inside its limit. Both are archived on the BACKUPS disk: each zip equals GitHub's digest and `sha256sum -c SHA256SUMS.txt` passed after writing. The 221 copied artifacts were then deleted from GitHub, under the owner's decision of 2026-11-08. The timing run's other 133 artifacts are synthetic, were not copied, and expire by themselves on 2026-11-10.

A first artifact count of the rehearsal, 390 MB, read only GitHub's first page of 100. The real total is 578 MB. The status board was corrected, and the numbers in this PR come from the full listing.

## Owner decisions of 2026-11-09

- **v4-d31:** a V4 pass approves nothing at EUR 100. Moving forward at that size takes a separate owner decision, made on the reported 100 USDT numbers.
- Codex Desktop and the local reviewer are not set up on Kali for now. The cloud reviewers carry the work.

## What this PR changes

Documents only, before the new B: this note, the step-5 plan's amendment and its counts and times, the run archive's Kali section and the new runs, v4-d31 in the V4 spec, and short corrections in `START_HERE`, `AGENT_HANDOFF` and `LOCAL_WORKER`. Nothing under `src/`, `scripts/`, `tests/`, `.github/` or `config/` changes. The spec is pinned at the new B, so v4-d31 has to land here.
