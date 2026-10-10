# V3 trade lifecycle integration

Index: Ordered account journal feeds runner lifecycle attribution, fees, funding,
excursions, exit priority and censored terminal trades; synthetic checks only.

Purpose: make trade profit factor and explanations of gains/losses inspectable.
Owner: Codex Desktop. Stacked on the runner PR; never merge into that dependency.

The account records immutable fill events with before/after positions and funding
events in actual insertion order. This preserves fills before funding and reductions
after funding even when their timestamps coincide. Existing accounting formulas
are unchanged.

The lifecycle ledger consumes the append-only journal once, retaining fills,
realized/unrealized PnL, fees, signed funding, duration, favourable/adverse excursions
and profit given back. Before-fill and after-reduction states preserve earlier gains
when average entry changes. A flip closes one lifecycle and opens another. Exit
conditions follow frozen priority; missing closing reasons are errors, not guesses.

The runner retains explicit decision reasons across masked fill hours, derives
mechanical flip/rounding/minimum/delevering conditions, observes hourly extremes,
and censors remaining trades at terminal or liquidation marks without new fills.
The caller must supply signal-zero, pick-change and exclusion provenance: target
weight alone cannot distinguish those causes.

Validation: 148 focused synthetic tests pass across all strategy primitives,
including 12 lifecycle and 14 runner tests. Cases cover long/short, partial closes,
funding, flips, pre-increase excursions, invalid terminal batches, duplicate funding,
journal order, explicit reasons, deferred exits and reconciliation of lifecycle net
results with account equity. Ruff, mypy and Bandit pass. External review/full CI
are pending at publication.

Remaining integration limits: data adapter and exclusion scheduling, full decision
metadata, walk-forward selection, metrics/export, and bounded evidence storage.
The journal currently retains all events in memory. The runner consumes only new
events, checking the absolute cursor and preceding immutable event identity. The
full-snapshot API retains its prefix check for explicit snapshot validation.
Returned lifecycle objects are mutable; consumers must not mutate them. More input
consistency checks and immutable report snapshots may be appropriate before export.

No real market data, replay, dependency, exchange integration or frozen-rule change.
The accounting tolerance proposal remains unadopted and strict audits still stop.

## Cloud review corrections

The review at 8280addff0cd369c50945a4732b830486aa1ea37 identified repeated
full-journal traversal and missing terminal lifecycle records for unrestorable
leverage. Both were reproduced before correction. The runner now requests one
suffix batch per hour and derives exit reasons only for that batch; the ledger
appends consumed references without recopying history. Batch continuity rejects
replays, skipped indices and a different predecessor. This relies on the account's
private append-only storage and immutable events; it does not scan old entries for
unauthorized private mutation. Full historical account audits remain separate.

Both no-tradable-position and leverage-not-restored outcomes now censor remaining
positions at the last checkpoint's price and exact timestamp, without a closing
fill. Synthetic funding-triggered cases verify unrealized PnL, funding and duration.

Validation for these corrections: 69 account/execution/lifecycle/runner/pending
tests pass; Ruff, mypy and diff whitespace checks pass. Full CI and renewed external
review at the new head are required before merge. No profitability claim or market
data access. No new dependency or known security issue in this change.
