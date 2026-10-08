# Proposed V3 accounting-rounding amendment

Index: Codex reproduced a Decimal60 exact-PnL identity conflict before any market replay; proposes an owner-approved 1e-18 USDT PnL reconciliation tolerance only.

Status: PROPOSAL, not adopted. Frozen `EXPERIMENT_SPEC_V3.md` remains unchanged.

## Reproduction

All values are synthetic. With precision60 ROUND_HALF_EVEN, normal cost settings,
buy1 unit at unslipped1, buy6 at unslipped2, then sell7 at unslipped2:

```python
from decimal import Decimal as D, Context, ROUND_HALF_EVEN, localcontext

with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
    initial = D(10000)
    buy1 = D(1) * (D(1) + D('.0005'))
    buy2 = D(2) * (D(1) + D('.0005'))
    sell = D(2) * (D(1) - D('.0005'))
    average = (buy1 + D(6) * buy2) / D(7)
    realized = D(7) * (sell - average)
    fees = buy1*D('.0005') + D(6)*buy2*D('.0005') + D(7)*sell*D('.0005')
    wallet = initial + realized - fees
    residual = (wallet - initial) - (realized - fees)
    assert residual == D('-1e-59')
```

The wallet identity holds by its written formula, and the book is flat. But adding
initial capital rounds away digits; subtracting it cannot restore them. Therefore
the third exact identity in §6 fails even with correct fills and accounting.
Two independent local calculations reproduced this. No market data was inspected.

## Concrete proposed amendment

Keep all trading, sizing, costs, prices, criteria and operation order unchanged.
Keep Decimal60 ROUND_HALF_EVEN. Keep wallet reconstruction from ledger totals and
bought-minus-sold quantities exact.

For §6's equity-change/PnL reconciliation only, accept an absolute residual at most
`0.000000000000000001` USDT (`1e-18`). Always record the signed residual, including
accepted nonzero residuals. A larger residual remains an accounting defect and
stops the experiment with no verdict under §8. Do not add balancing entries, adjust
trade PnL, round archived inputs or suppress failed runs.

This is the same absolute PnL audit tolerance used in the older replay's identity
check, but its existence there does not authorize changing frozen V3. The owner
must explicitly adopt this amendment before the implementation accepts it.

## Until adopted

Implement exact checks and report the reproduction as a known specification
conflict. Do not dispatch a V3 replay. Account primitives and chronology tests can
proceed using synthetic fixtures. The strict check must not silently become tolerant.

A negative portfolio variance caused by frozen-precision arithmetic is likewise an
engine/numerical failure to diagnose, not one of §8's strategy-invalid outcomes.
The earlier sizing handoff's instruction to label it an invalid run is corrected
in the account follow-up; numerical defects must not bias rule selection.
