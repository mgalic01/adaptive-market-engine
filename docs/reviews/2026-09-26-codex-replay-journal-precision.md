# Codex → Claude handoff: replay fill-journal precision

- **Date:** 2026-09-26. **Base:** `a5bb058813f78270c61c2b7e94d70ac36753cf1c`.
- **Implementation:** `8ebf466f25a2076c6d8da30a89af820a07b1e738`; found during the owner's expanded retrospective review. This is a pre-existing runtime defect, not attributed to a particular recent merge.

## Finding and fix

**P2:** `PaperSimulator.step` updates balances at Decimal precision 50, but replay `_record_fills` used the caller's default precision 28. Valid high-precision price/quantity inputs consequently round differently in the journal and falsely fail cash and fee reconciliation. A synthetic fill produced account fees `0.002895899852004268860190519987501905210` versus journal fees `0.002895899852004268860190519988`.

The journal now uses its own precision-50 context, matching account updates without changing the caller's context. No execution, order selection, fees, risk limits, reserve transfers or protected-profit policy changes.

## Verification and limits

- Parent Codex independently reproduced the failure and reviewed the full fix.
- The regression exercises real order matching: buy, partial maker sell, and a final taker exit with a different fee rate. All three reconciliation checks fail on the original and pass after the fix. The caller's precision remains 28.
- All 39 replay tests pass. Two 600-bar synthetic V0 replays, each with 38 fills, preserve byte-identical complete account state and equal metrics on both intrabar paths.
- Full Windows suite at the original base: 349 tests / 497 subtests pass, with three unrelated existing failures (scope checker path comparison and two unavailable symlink fixtures), separately addressed by #71. Ruff, formatting, mypy, Bandit and report hashes pass. This is not a claim of a wholly green Windows run before #71 integrates.
- No real archive fetched or large replay matrix run. Published historical lower-precision results are not claimed affected. High-precision journal output can correctly change; old rounded journal artifacts should not be mixed into a new comparison as if identical.

**Next:** Claude/Bob review the local context and reconciliation regression at the pushed head; Codex verifies required Linux checks and integration with #71 before merge. The broader audit and #70's separate checksum-failure blocker remain tracked on their own PRs.

