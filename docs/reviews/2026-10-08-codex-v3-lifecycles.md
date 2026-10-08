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
The journal currently retains all events in memory, and lifecycle consumption
checks its prior prefix. Large-run optimization must preserve evidence correctness.
Returned lifecycle objects are mutable; consumers must not mutate them. More input
consistency checks and immutable report snapshots may be appropriate before export.

No real market data, replay, dependency, exchange integration or frozen-rule change.
The accounting tolerance proposal remains unadopted and strict audits still stop.
