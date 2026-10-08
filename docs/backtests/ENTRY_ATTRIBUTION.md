# Reading the Uptrend entry funnel

This additive report explains why a selected Uptrend mode does or does not purchase
inventory. It does not change selection, sizing, recovery or risk limits. It is the
first batch of the owner's approved V2 diagnostic work, not a new strategy trial.

Future MS replay rows contain `modes.entries`. Existing saved results do not acquire
these records retroactively; the scored V2 verdict remains unchanged. No historical
replay is part of this change.

| Field | Meaning |
| --- | --- |
| `schema_version` | Entry report version, currently 1 |
| `selected` | Number of hourly opportunities where Uptrend was selected |
| `selected_outcomes` | First-frame outcomes for those selections |
| `continuation_outcomes` | Outcomes of subsequent quote-level buy attempts while entering |
| `records` | One timestamped detail record per selected opportunity |

Outcomes are `blocked`, `filled`, `budget`, or `depth`. A `filled` result may be a
partial entry. `depth` can later fill; `budget` ends the entry, retaining any amount
already purchased. Neither a fill nor a selection is a completed round trip.
Continuation counts are attempts, not additional opportunities. A continuation's
full record is in its frame's `uptrend_entry` output, but is not retained in the
compact result-row detail list. Thus the compact report does not yet map every
selection through to its final position outcome.

For selected entries, the independent first-stage blockers are `risk_action`,
`risk_recovery`, and `not_flat`; more than one may appear. Recovery is reported
after the current frame's confirmation update. Only when those gates pass does
the existing engine check daily inputs and stop validity, reported as
`daily_inputs_unavailable` or `invalid_stop`. Absence of a later blocker does not
mean the later gate was evaluated. Selector-level exclusions remain in the existing
`modes.decisions` report; they are a different stage of the funnel.

Detail records include observed time, available capital before the attempt, active
equity, both risk reference peaks, bid/ask and ask size, minimum notional, daily RSI
and ATR, and filled quantity. When an actual buy is attempted they also contain the
entry timestamp, stop, initial limits, and remaining cash/risk allowances **before**
the attempt. Monetary/quantity Decimal values are JSON strings. `available_cash`
means cash less pending reserve, not cash net of resting buy reservations. The
engine's separate spendable-cash check still applies. `budget` combines insufficient
cash cap, spendable cash and risk allowance under lot/minimum-notional constraints;
this schema does not claim to identify which bound was decisive.

Limits: the records do not estimate hypothetical profits on rejected entries, classify
independent market opportunities, provide full trade P&L or favorable/adverse
excursions, or establish a profitable strategy. The next batch should link selected
entries to position lifecycles and attribute grid inventory exit losses. That is
separate from this narrowly testable entry-reporting change.

Verification uses synthetic inputs only. The frozen pre-diagnostics replay digest
still covers all prior numerical and frame fields after excluding just the new
report blocks, alongside the previously excluded selector explanation fields.
