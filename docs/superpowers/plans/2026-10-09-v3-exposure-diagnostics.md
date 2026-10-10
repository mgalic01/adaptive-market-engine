# V3 exposure diagnostics

Implements frozen section 8's time invested, mean gross/net exposure and lowest
margin ratio. This makes the experiment's use of risk visible without changing
execution, sizing or acceptance rules. Use Superpowers executing-plans inline.

- [x] Reproduce missing signed-notional and diagnostic API failures with synthetic
  mixed long/short books, post-fill delevering, later funding and flat hours.
- [x] Append nullable signed notional to immutable account marks for compatibility;
  production marks always populate it. Never treat absent legacy evidence as zero.
- [x] Aggregate the final step-4 mark per observed hour, retain coverage counts,
  and derive minimum margin from liquidation-check marks (not favourable marks).
  Undefined exposure at nonpositive equity remains explicitly unavailable.
- [ ] Run account/execution/evidence regression checks, lint/types and independent
  review, then full CI and exact-head external review before merge.
