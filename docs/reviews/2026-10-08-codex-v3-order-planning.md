# V3 order planning handoff

Index: Codex implemented frozen V3 rebalance bands and market-order quantity planning, including flip/refusal/reduction/split diagnostics; account execution remains pending.

Branch `codex/v3-order-planning`, following sizing PR #214.
Spec: `docs/EXPERIMENT_SPEC_V3.md` section5 steps4–5.

`src/crypto_grid_bot/trend/orders.py` provides a pure `plan_rebalance` API.
It consumes target weight, signed held quantity, pre-fill-hour equity and unslipped
open, plus pinned effective market-order filters. It emits signed `OrderIntent`s
with reduce-only flags, the current weight, rounded target quantity, refusals and
reduction adjustment reasons. There is no exchange integration or account mutation.

The weight band is strictly greater than 0.01, with target/held sign differences
forcing a trade. The band is tested before quantity rounding. Zero target against
an open position closes regardless of its size. Quantity rounds toward zero to
the market step. A rounded-zero target can close when the weight band permits it;
rounding alone cannot bypass that band.

Open/increase orders must meet minimum quantity and unslipped minimum notional.
Reductions ignore minimum notional, are raised to minimum quantity (next valid
step if necessary), and close dust remainders. Existing whole-position dust can
close even when below minimum. Flips close first and evaluate their opening leg
separately, so a refused new opening leaves flat. The account must execute all
symbols' reductions before any increases; this API handles one symbol only.

Oversized orders follow the frozen ceil(quantity/maximum) split count, distributing
remaining steps to earlier orders. A prescribed split that cannot satisfy minimum
or maximum raises ValueError; the runner must label that run invalid, not try a
new unregistered splitting algorithm. Held quantity must already match the step.
All computation uses a fresh Decimal60 ROUND_HALF_EVEN context.

22 order tests and43 sizing/signal tests pass locally. They cover strict band,
weight-before-rounding, signs, negative rounding, flip refusals, minimum/max equality,
minimum reductions, dust, balanced splits, impossible prescribed splits, invalid
inputs/filters and ambient context independence. The initial15 tests failed on
the absent API before implementation. Ruff and mypy pass. Independent review and
new-head CI remain pending at this writing.

No new dependencies, frozen parameters, market data reads, fetches, live-order
routes or known security findings. Account wallet/PnL/funding/liquidation chronology,
deferred orders, WFO and analytics are still outstanding. This layer alone cannot
run a strategy or establish profitability.


## Rounded-away attempt correction

Cloud found that a required opening/increase rounded to zero could disappear from
the decision evidence. The plan now retains signed `intended_increase_quantity`
before quantity rounding for every band-approved opening/increase, including
filled and minimum-refused attempts. A flip records its new leg only, excluding
the closing quantity. `quantity_rounded_to_zero` marks a blocked opening/increase;
a within-band no-op or an ordinary reduction has no increase attempt.
Six new failing regressions cover flat, same-side long/short and flip rounding,
plus filled/refused intent sizes. All28 order and43 sizing/signal tests pass.
The account-size reporter must consume this field for every non-None attempt.

The minimum-notional-before-split interpretation is disclosed on the PR: the
frozen text explicitly tests the complete quantity change and only names minimum
quantity as its invalid-split condition. Bob and independent review found this
faithful to the frozen text. It is not a claim that each child's minimum notional
matches live exchange enforcement.

## Zero-rounded sizing exits

The next Cloud review identified the reduction counterpart: a nonzero target
outside the band can round to zero and close the held position. It now carries
`quantity_rounded_to_zero` even though it has no intended increase. Two long/short
regressions failed before the fix and pass afterward; a third verifies explicit
zero targets and within-band no-ops are not mislabeled. All31 order tests and43
sizing/signal tests pass. Ruff, format, mypy and the report checker pass. This
changes decision evidence only; emitted quantities and costs are unchanged.
The future lifecycle consumer still applies the frozen exit-trigger precedence.
