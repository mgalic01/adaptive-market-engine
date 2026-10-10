# V3 monthly input assembly

Index: Codex connects verified monthly inventory to market-separated replay inputs; calendar review and historical dispatch remain upstream.

## Change and purpose

The offline decoder/loader returned monthly records while the experiment runner
consumes per-market histories. `assemble_replay_inputs` connects those interfaces.
It requires the complete unique fixed inventory, ten-symbol filters and an explicit
join calendar equal to the verified coverage candidates. All join months must have
eligible spot, futures and funding entries. A disputed candidate must be resolved
upstream; matching it is not human approval or completing registration.

Spot and futures hourly bars remain separate. Spot daily signals omit spot-excluded
months only; futures-only exclusions keep updating signals per section 4. Spot
history starts at the first full spot month, retaining in-scope warmup before
joining. Original funding timestamps are retained, simultaneous coins share
one group, and duplicate bars or same-coin funding timestamps are rejected.
Source manifest/spec hashes are carried through. `replay_ready` remains false.

## Verification and limits

After correcting a synthetic fixture's Kline argument count, six tests failed for
the missing API and passed after implementation. Additional grouping/duplicate
checks brought the focused decoder/loader/assembly run to 28 passing tests. Ruff
and focused mypy passed. Separate read-only review found no actionable defects.

This function consumes the already verified loader result; it does not revalidate
raw archive contents or claim the mutable Python objects are a security boundary.
No files, network, historical replay, trading changes or dependencies. It does not
implement the full-size hold's treatment of excluded months or certify a result.
Current-head Bob review and required CI are still needed before merge.

Cloud review caught two defects missed by the initial reviews: dropping valid spot
bars during futures-only exclusions and admitting partial listing-month warmup.
Both received failing regression tests before correction. The plan and description
above now reflect the section 4 signal-continuity rule. No historical run occurred
with either defect; the original head was not merged.
