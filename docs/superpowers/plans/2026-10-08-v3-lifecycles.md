# V3 lifecycle evidence implementation

Purpose: attribute each trade's net result and profit given back to fills, funding
and held-position excursions so the frozen trade profit factor can be verified.

1. Build an event-fed lifecycle ledger. Consume actual account fills in execution
   order with before/after positions; never reconstruct ambiguous equal-timestamp
   ordering by sorting separate fill and funding lists.
2. Track flat-to-position entry, partial reductions, full closes and flips as
   separate lives. Require caller-supplied exit conditions and apply frozen priority.
3. Accumulate signed funding, realised PnL and fees. Observe pre-fill excursions,
   post-reduction excursions, hourly favourable/adverse states and terminal marks.
4. Finalize open positions as censored without invented fills. Validate duration,
   net result, excursions and nonnegative profit given back on synthetic examples.
5. Integrate account event hooks and runner provenance, then publish the complete
   batch for independent review. Do not claim aggregation alone is full reporting.

No frozen parameter change, real data read or replay. Owner: Codex Desktop.
