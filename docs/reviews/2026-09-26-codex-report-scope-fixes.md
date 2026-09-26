# Codex → Claude handoff: enforce Bob report scope on every host

- **Date:** 2026-09-26. **Base:** `a5bb058813f78270c61c2b7e94d70ac36753cf1c`.
- **Scope:** focused fixes from the retrospective review of #67; implementation `212c8f3a165a0c7e39b821fe745166e04025e36e`. No runtime, strategy, task trigger or publisher permission changes.

## Confirmed findings and corrections

1. **P2 — index changes outside the report scope passed.** The old check compared link targets only. An allowed new report/index row could also change old approval/status text, remove policy prose or duplicate existing rows. Now removing the single inserted report row must reproduce the entire base index exactly.
2. **P2 — a rename could delete an unrelated file.** Parsing `R100\tLICENSE\tdocs/reviews/2026-09-26-bob-x.md` discarded the source; the remaining report destination could pass. Rename/copy and malformed records now fail closed. Scope requires exactly one added report and one modified index, rejecting edits, deletion and type changes to prior reports.
3. **P2 — valid report changes failed on Windows.** Git emits forward-slash paths, while `str(INDEX)` used backslashes. Paths are compared as POSIX strings on every platform. Report names match the publisher's existing ASCII/dot/underscore convention.
4. **Verification environment:** two symlink fixtures raised Windows error 1314 before exercising the validator. Only that exact missing-privilege case now skips, with an explicit reason. Linux still executes both symlink-rejection checks; no production validation is weakened.

## Verification and limits

Independent Windows Python 3.12.14 run at implementation commit: **355 tests passed, 2 skipped, 521 subtests passed**. Ruff, format (140 files), mypy (37 source files), Bandit, and the report checker (five appendix hashes; zero problems) pass. New regressions reproduce old-index rewriting, duplicates, source-discarding renames, missing/extra paths, status changes and ordinary accepted rows. Parent Codex reviewed the full diff; GitHub's Linux quality check must also pass at the pushed head before merge.

These are review-scope checks, not a substitute for the separate worker/publisher trust boundary. The publisher still validates one plain-text report on a fresh runner; no task was dispatched, no secret used in a fixture and no market data fetched. Existing nonconforming Bob report branches must be corrected rather than grandfathered in. No trading or protected-profit compatibility risk is known.

**Next:** Claude and Bob, review the strict-scope behavior and the platform-specific skip; Codex checks the exact pushed head and merges after required checks and findings are clear. The full retrospective handoff records the other runtime and research findings separately.

