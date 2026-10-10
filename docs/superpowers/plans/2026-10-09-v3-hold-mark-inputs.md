# Full-size hold valuation inputs

Frozen V3 section 8 says full-size hold ignores excluded months and marks at the
last unmasked spot price. Monthly decoding currently omits all excluded-month
records. Preserve a separate `hold_hourly` series for valid unmasked spot rows,
including months excluded by the 17% threshold; leave strategy hourly/daily
series excluded. Missing/corrupt archives supply no diagnostic prices. Futures
and funding never supply spot hold prices.

Test excluded spot months, eligible spot repair masks, and corrupt/missing input
first. Implement only the decoder extension, then run decoder/loader checks,
static checks and independent/Bob review. No purchase-time behavior, historical
data access, full-size account, new eligibility or authorization changes.

Review focus: never unmask repaired hours or resurrect corrupt rows; never feed
diagnostic bars to strategy signals. Subsequent full-size assembly must use the
separate field explicitly.
