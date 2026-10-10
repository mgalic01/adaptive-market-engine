# V3 costs and minimum capital

Implement frozen section 8's fee/funding/slippage/turnover report and minimum
account-size scaling, so results can explain cost drag and the owner's small
capital constraint. Use Superpowers executing-plans inline; no strategy changes.

- [x] Reproduce missing intended-notional evidence and reporting APIs in tests.
- [x] Retain unrounded intended increase notional, including refused/zero-rounded
  orders and flip openings, without changing executable orders.
- [x] Compute fee/funding/slippage totals and clearly labelled gross traded
  notional. Slippage is already in fill prices and must not be subtracted twice.
- [x] Compute the maximum frozen filter ratio times 10,000, rounded up to 10 USDT;
  preserve the limiting intention and no-opening case. No account-size reruns.
- [ ] Verify focused regressions, lint/types, independent and exact-head external
  review, with full CI before merge. Wire into the full report separately.
