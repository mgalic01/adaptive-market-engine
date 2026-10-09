# V3 fixed-rule reporting scenarios

Frozen section 8 requires full-period results for each of the twelve rules,
separate from walk-forward selection. Implement a reported-only menu over supplied
inputs and the main test's quarter boundaries, with base costs and m=2.
Use Superpowers executing-plans inline.

- [x] Reproduce missing API and test twelve independent accounts, complete fixed
  schedules, start-before-execution, interruption and engine-failure abort.
- [x] Share existing recorded sensitivity replay handling with the fixed menu;
  preserve reconciliation, partial evidence and strategy-invalid outcomes.
- [ ] Verify synthetic orchestration/evidence checks and independent review;
  exact-head external review and full CI gate merge. No historical dispatch or
  candidate selection is performed while building this component.
