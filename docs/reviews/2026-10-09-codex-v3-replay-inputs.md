# V3 monthly replay-input decoding

Index: Offline decoder binds supplied monthly bytes to inventory diagnostics and exposes only eligible unmasked prices or exact funding records; no dispatch or data-access authorization.

## Purpose and behavior

The frozen experiment needs the same repaired data used for its inventory to
reach the replay without accidentally restoring masked hours. The new
`scripts/v3_replay_inputs.py` helper takes one inventory entry and its supplied
bytes. It reuses `inspect_archive` to recompute the hash, eligibility, masks and
statistics, and requires equality before returning records. Canonical identity
and the development-window guard run before decoding. A supplied local path is
validated but never opened.

Eligible kline months expose only unmasked hourly bars and the existing daily
aggregation (at least 20 unmasked hours). Every repaired hour remains masked.
Funding records retain original millisecond timestamps and exact Decimal rates.
Missing and excluded entries return their explicit status with no replay records.
The original inventory remains the source of exclusion reasons and diagnostics.

## Verification

All 13 new synthetic tests failed for the missing API before implementation and
pass afterwards. The wider selection passes **65 tests**: test_v3_replay_inputs
(13), test_fetch_v3_data (37), test_v3_coverage (7), test_v3_inventory_build (8).
Cases cover futures headers, missing/repaired hours, daily completeness, excluded
price/funding months, raw funding offsets, hash/statistic disagreement, reserved
dates and missing-versus-present bytes. No market data was read or downloaded.

Full-tree Ruff and formatting pass; mypy with MYPYPATH=src and Bandit pass for
the new script. Independent read-only review found no actionable defect in this
single-entry scope. Full CI and substantive current-head Bob/Claude review are
required before merging.

## Limits and remaining integration

This does not turn a collection inventory into an approved replay manifest.
The enclosing adapter still must validate the entire inventory, settle reviewed
first-full months and cross-market exclusions, bind snapshots and code to the
completing trial registration, and preserve source identities in results.
No CLI, downloader, historical dispatch, new dependency or strategy change is
introduced. Decoding deliberately re-inspects each archive before parsing its
records; this duplicates parsing work to keep the existing inventory validation
authoritative until actual profiling justifies consolidation.

Codex owns that remaining adapter and registration integration. Owner choices
for storage and the full-size hold's missing-first-purchase-bar behavior remain
pending, as does the owner-started reviewed Bob data task.
