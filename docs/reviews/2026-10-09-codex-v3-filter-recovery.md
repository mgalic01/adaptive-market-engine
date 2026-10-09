# V3 recovery preserves both filter snapshots

Index: Added byte-pinned spot snapshot recovery alongside futures recovery; synthetic checks only, no fetch or historical dispatch.

## Problem and change

Frozen V3 section 2 records both filter snapshots once. Existing recovery could
preserve the futures response but unconditionally requested spot filters again.
The local data-delivery proposal review exposed that gap before any actual fetch.

`collect_inventory` and `build_inventory` now accept an optional `spot_snapshot`
alongside `futures_snapshot`. The CLI adds `--reuse-spot-snapshot` and
`--spot-snapshot-sha256`. Both arguments must be supplied together; byte size,
digest and filter contents are checked before transport construction. A supplied
spot snapshot is copied unchanged into the fresh inventory and suppresses the
spot filter GET. The existing futures path and fresh-fetch behavior are unchanged.

Recovery of an attempt that retained both responses supplies both pairs of flags.
If only spot was saved before the first futures request, spot-only reuse permits
that still-unmade futures request under the separately authorized task. Absence
of a local snapshot is not evidence that an endpoint was never called: the owner
and executor must inspect the failed attempt before deciding whether a request
is allowed. These helpers do not enforce a global once-only registry across
directories, automatically retry, or authorize any network operation.

## Verification

Expanded synthetic inventory tests cover all combinations of fresh and reused
spot/futures snapshots, with and without an archive. Fake transports assert that
the reused endpoint is not invoked. The resulting raw spot bytes match the input;
offline inventory verification validates both snapshot hashes. CLI tests reject
missing pins, wrong pins and invalid contents for both markets before transport.

Before implementation, seven new cases failed because spot recovery arguments
and the collector parameter were absent. After implementation, all 62 focused
inventory/transport tests pass. Ruff lint and formatting and mypy pass. Full-suite
and exact-head external review results belong in the PR; none are claimed here.
No market data or filter endpoint was accessed, and no dependency was added.

## Operational handoff

Codex owns this fix; Bob remains the frozen data-task executor. The proposal in
PR 229 separately covers local retention, raw Git input pins and owner start.
When this fix is merged, update that proposal's recovery prerequisite with this
reviewed implementation, and pin the final collector code in the executable task.
Retain original failed directories and supply the exact saved hashes; never
replace snapshots or infer a successful inventory from a leftover manifest.
The completing trial registration and historical replay gates remain unchanged.
