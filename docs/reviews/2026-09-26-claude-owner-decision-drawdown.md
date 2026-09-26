# Owner decision: the hard stop stays at 12%, C1 stays at 10%

- **Date:** 2026-09-26. **Recorded by:** Claude. **Decided by:** the owner.
- **Question.** Bob's V0 scorecard (PR #52) showed V0 failing C1 by small margins
  (total-equity drawdown, C1(a), 10.0008% to 10.9344%) with no hard-drawdown halt.
  The same five runs also fail C1(b), the active-equity drawdown, by slightly larger
  margins (10.0292% to 11.1611%); Bob's review of this record pointed that out. `config/default.toml`
  has `soft_drawdown_pct = 0.08` and `hard_drawdown_pct = 0.12`, while
  [experiment spec v1](../EXPERIMENT_SPEC_V1.md) §6 C1 requires a worst drop of at most
  10%. So the bot's own risk rules allow drops between 10% and 12% that C1 fails.
- **Options put to the owner:**
  1. keep the hard stop at 12% and C1 at 10%;
  2. raise C1 to 12%;
  3. lower the hard stop to 10%.
- **Decision:** option 1, "12 is ok". The emergency stop stays at 12%, and a strategy
  passes C1 only if its worst drop stays within 10%.
- **What it means:**
  - nothing changes in the spec or the default config;
  - V0 keeps failing C1 on the development windows, so a variant must show a smaller
    worst drop than V0 to pass;
  - the 10–12% band is an intended margin between the acceptance limit and the
    emergency stop, not an inconsistency to fix.
- **Why the question was not "fixed" by tuning:** changing a limit or a criterion
  after seeing development results would bias the later tests. The owner chose to
  change neither.
