# Full-size hold diagnostic implementation

Goal: implement frozen section 8 plus the owner's 2026-10-09 timing amendment,
registered as v3-candidate-space-6 before this code. Use supplied unmasked spot
bars (including diagnostic prices retained from excluded months), never files or
network. There is no strategy signal, sizing cap, rebalancing, sale or later join.

Implement `trend.full_size_hold.replay_full_size_hold`: initial 10000-USDT cash,
equal fee-inclusive allocations to initial members, each filled once at its first
available hourly open at/after start+1h. Use SpotAccount market lot/minimum filters,
slippage, fees and maximum-order splitting. Retain refused fills and cash dust.
Do not redistribute reserved allocations. No available bar before end means an
unavailable diagnostic with the missing symbols, not an invented fill.

Keep timestamped open, post-fill, favourable-then-adverse and terminal equity,
01:00 daily samples plus terminal sample, exact cash/quantity audits and scheduled
versus actual entry times. Carry last unmasked open in gaps; terminal uses last
available close. Engine defects raise with partial evidence, not an invalid
strategy classification. The supplied end boundary is exclusive and at most
2025-01-01; no 2025 prices allowed.

Tests first: delayed coin retains original budget; later joins ignored; no sells
or reallocations after price changes; unavailable first fill; repaired/missing
bars represented as absent; fees/filter refusals/splits; chronological data and
reserved-date rejection; terminal mark and audit. Then implement, run related
account/benchmark tests, static checks, independent review and Bob/CI.

Review focus: fee-inclusive budget arithmetic, intrahour state order, gap marks,
unavailable-vs-failed distinction and no silent allocation redistribution.

Review clarifications (PR 247): masked/repaired hours are absent just like missing
hours; usable bars in excluded months remain available to this diagnostic. Idle
reserved cash contributes to every equity sample. Quantity is the market-step
floor of (10000/N)/(actual_open*1.0005*1.001). Minimum-filter refusals retain cash
and are recorded as attempts, not successful purchases. A missing first price
makes the whole diagnostic unavailable, not the A5 benchmark or strategy invalid.

Evidence: use the existing atomic journal/writer for immutable started/finished
records and hashed exact JSONL. Retain outcome, attempted timestamps, budgets,
cash/holdings, fills, audits and equity/samples. A missing first price is recorded
as unavailable; an engine error retains partial evidence and re-raises. An
interruption or failed publication leaves a pending start, with no automatic retry.

Budget representation: `budgets` is a Decimal60 display approximation; it is not
an exact cash-ledger balance or a spent-cash reconciliation target. The exact
allocation is the rational `initial / len(budgets)` (10000/N), reconstructible from
the evidence. Purchase quantities use that exact rational before flooring to the
market step; settlement then uses the existing Decimal60 account. Unspent cash
includes market-step dust, refused allocations and reservations. Cash and quantity
audits reconcile actual fills, never these displayed allocation approximations.
