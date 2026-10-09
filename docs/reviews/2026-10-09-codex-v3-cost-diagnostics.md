# V3 costs and minimum account size

Index: Implemented reported cost totals and the frozen filter-based capital estimate; retained unrounded intention notional; missing legacy evidence blocks estimates.

The cost report separates fees, funding paid, funding received and slippage.
Slippage uses signed quantity times slipped-minus-open price, so ordinary buys
and sells both incur positive cost. It is already embedded in net trading PnL
and is not deducted a second time. Turnover is explicitly labelled gross traded
notional: absolute filled quantity times slipped fill price, in USDT, without
annualization or normalization. These helpers do not certify account integrity.

The minimum-account estimate applies frozen section 8's three filter ratios to
every intended opening/increase in the base-cost 10,000-USDT m=2 main account:
minimum notional / intended notional, quantity step / absolute unrounded quantity,
and minimum quantity / absolute unrounded quantity. Take the maximum across all
intentions, multiply by 10,000 and round upward to the next 10 USDT. Preserve the
limiting coin, hour, signed quantity, notional and filter for explanation.

Refused orders and quantities rounded to zero count, including a flip's opening
leg. Band-skipped plans and pure reductions do not. An explicit no-intention case
returns no estimate. This is a scaling diagnostic, not a rerun or proof that a
small account follows the same path; changed rounding/refusals can alter it.

`OrderPlan.intended_increase_notional` is an additive nullable field. Production
plans record a positive unrounded open notional for an increase and zero for no
increase. Null means unavailable legacy evidence, not zero. The existing quantity
field remains signed; executable orders and trading arithmetic are unchanged.
The generic evidence writer retains the added field.

## Review correction and evidence

Five initial tests exposed the missing APIs/notional evidence. Independent review
found that a legacy plan with both intention fields absent could be skipped even
when it contained an opening order. Two failing regression cases reproduced this.
Production no-increase plans now record explicit zero notional, and the estimator
rejects unknown/inconsistent intention evidence instead of claiming no openings.
This also refuses ambiguous legacy plans rather than guessing their lost inputs.

All 85 focused cost/order/execution/replay/evidence checks pass, along with Ruff,
formatting and mypy. The independent review ran 36 checks before the correction;
the correction is evidenced by RED-to-GREEN tests, not claimed as a second review.
Full CI and substantive exact-head Bob/Claude review remain required before merge.

No data access, dependency, trading-rule change or historical replay occurred.
Codex owns integration into the final report. Present hosting capital separately
from this filter-based estimate, retain the limitations, and never turn a reported
capital estimate into a new acceptance gate.
