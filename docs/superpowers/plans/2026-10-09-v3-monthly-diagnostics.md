# V3 monthly diagnostics

Implements frozen section 8's monthly returns, target counts and hosting-capital
calculation, so the final report can answer the owner's return question from
evidence. No strategies, thresholds, acceptance gates or data access change.

Use Superpowers executing-plans inline. Inputs are supplied 01:00 daily equity
samples and their terminal sample; outputs are typed Decimal monthly rows and
summary counts. This arithmetic does not certify provenance or account validity.

- [x] Reproduce boundary tests before implementation: month-to-month 01:00 samples,
  terminal midnight in the following month, partial first/last months, target
  equality, nonpositive mean and malformed/gapped samples.
- [x] Implement Decimal60 returns and arithmetic mean; count months at least 20%
  and at least 30%. Hosting capital is 5 divided by mean monthly return, or None
  when unreachable; it treats USDT returns as EUR and excludes order-size effects.
- [ ] Verify focused tests, lint, types and report checks; independent review and
  full CI before merge. Preserve the full report/registration work as outstanding.
