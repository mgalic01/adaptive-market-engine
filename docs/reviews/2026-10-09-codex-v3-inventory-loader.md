# Offline V3 inventory input loader

Index: Verify complete hash-pinned inventory and snapshots before exposing decoded monthly records; coverage remains a candidate and replay authorization remains false.

## What it provides

`scripts/v3_inventory_loader.py` connects the saved collection directory to the
monthly decoder from PR241. `load_inventory_inputs(root, manifest_sha256)` first
uses the existing inventory verifier: all 2710 canonical identities, statistics,
coverage, archive hashes and snapshot hashes must agree. It then rechecks every
byte sequence against the same pins when reading it for decoding. No partial
dataset is returned if any input fails.

The result contains decoded monthly records, typed spot and futures filters,
manifest/spec hashes and the original candidate coverage. It always retains
`replay_ready=False`. There is no network client, CLI, trial registration or
historical dispatcher in this module. Local inputs must come from the authorized
data task; calling this helper is not a substitute for that authorization.

## Evidence

Six new generated-inventory tests failed for the missing API before implementation
and pass afterwards. Combined with the decoder, **19 focused tests pass**.
The complete 2710-entry synthetic fixture includes eligible BTC spot/futures/
funding files and explicit missing entries. It checks exact record counts and
both ten-symbol filter sets. Corrupt archive, snapshot and manifest bytes fail;
even re-pinned altered coverage or a reserved-date identity fails validation.
No historical data was fetched or read.

Ruff, formatting, mypy (MYPYPATH=src) and Bandit pass. Full CI and substantive
current-head Bob/Claude review remain required before merge. PR241 is a dependency.

## Remaining work and limitations

Verified collection coverage still needs review against the actual data before
an approved replay manifest can pin portfolio joins and cross-market exclusions.
The completing trial registration must then bind the final code and manifest.
The frozen historical run, full-size hold diagnostic and result certification
are not implemented or authorized by this loader. No strategy or dependency
change is introduced. The loader reuses private inventory-validation helpers;
future refactors must keep their boundary checks intact.
