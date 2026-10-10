# Full-size hold spot valuation inputs

Index: Codex preserves separate unmasked spot prices for the full-size hold diagnostic, including completeness-excluded months.

Frozen V3 section 8 makes full-size hold ignore excluded months and value its
holdings at the last unmasked spot price. The strategy decoder deliberately omitted
excluded-month records. `DecodedMonth.hold_hourly` now separately retains unmasked
spot bars in both eligible months and months excluded by the 17% completeness rule.
Strategy hourly/daily bars remain empty in excluded months. Futures and funding
never populate the new field; missing/corrupt archives supply no hold prices.

The decoder still rechecks raw bytes against all inventory diagnostics first.
The `masked_hours` diagnostic exists only after a successful price-reader pass;
failed ZIP/CSV reads are not resurrected. Repairs and individual missing-hour masks
apply to hold prices too. The existing field order is preserved by adding a final
defaulted field, and eligible spot tuples are shared rather than copied.

Three tests failed for the missing field before implementation. All 59 focused
decoder/loader/fetch tests, Ruff and focused mypy passed afterwards. Independent
read-only review found no actionable defects. Required Bob review and CI precede
merge. No historical data, fetch, dependency or trading-rule change occurred.

This prepares inputs only. The full-size account still needs implementation and
the owner's first-purchase missing-bar ruling. No fallback timing is chosen here.
Subsequent diagnostic assembly must explicitly consume `hold_hourly`; strategy
assembly continues to consume the existing eligible-only fields.
