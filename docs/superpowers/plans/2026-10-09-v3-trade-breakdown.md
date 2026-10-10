# V3 lifecycle profit breakdown

Goal: implement the frozen section 8 long/short and coin profit breakdown from
finalized lifecycle evidence, so the experiment can explain its outcome.

- Write failing tests using actual synthetic account/lifecycle events for closed
  and terminal-censored positions, fees, paid/received funding and short profits.
- Implement immutable totals grouped by coin, side and coin/side; include an
  overall total, zero-result lifecycles and censored counts. Use Decimal context
  60 / half-even. Reject unfinished, malformed or nonfinite lifecycle input.
- This is supplied-evidence aggregation, not account reconciliation or acceptance.
  A fixed-rule report may label its entire account with its known rule. Do not
  assign a changing quarterly rule to a lifecycle that can span pick changes.
- Verify focused regressions, lint/types, independent review, then push for
  substantive exact-head external review and full CI before merge.

No market data, dependency, trading behavior or frozen criterion changes.
