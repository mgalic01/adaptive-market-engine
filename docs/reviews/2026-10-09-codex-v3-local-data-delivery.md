# V3 local data delivery proposal

Index: Current E: delivery proposal with verified pins and both-snapshot recovery; executor access or an owner-approved local Codex exception, reviewed task and owner start remain pending.

## Purpose and status

**Update, 2026-10-09:** the owner selected E:, with dedicated root
`E:/adaptive-market-engine/v3`; see [the decision record](2026-10-09-owner-v3-storage-and-hold-timing.md).
This does not start the download. Pins below were refreshed from main after PR 247.
This remains a proposal, not an executable task. Both-snapshot reuse is implemented
by PR 230.

This prepares the evidence needed to judge the frozen V3 experiment. It does not
change its strategies, sizing, criteria or reserved-window boundary. It is a
proposal for an owner-started local data task, not a Bob workflow task file and
not an automatic trigger. Codex owns preparation and verification; the owner
chooses storage and starts the reviewed fetch. The frozen executor remains Bob,
using a reviewed task file; Codex prepares it but does not substitute itself as
executor. Confirm that Bob has access to the selected local directory before
finalizing that task. This proposal is not that executable task file.

Collector source inspected at main
`3b573ba0326a2487b43f7b00d18a1458b320029b`:
`scripts/v3_inventory.py` and `scripts/fetch_v3_data.py`. This pins the collector
for this proposal only. It is not the completing registration of replay code.

The current remote Bob task accepts a small report and discards raw artifacts;
its network prompt also excludes the two public filter endpoints the frozen spec
permits. Local retention resolves those delivery constraints without changing the
remote workflow, provided a local Bob session can retain the files. Downside: the
owner must retain and back up the local archives;
a Git manifest alone cannot recover an upstream archive that later disappears.

## Storage and inputs

Use the selected root `E:/adaptive-market-engine/v3`. E: had 729,308,557,824 bytes
(679.2 GiB) free at the follow-up check. Recheck before execution; free space is not
an estimate of data size. Do not delete existing data to make room. The request plan is 2,710
archive identities; at the collector's 64 MiB per-file ceiling, the theoretical
archive ceiling is about 169.4 GiB, not an estimate of actual download size.
Reserve additional space for snapshots, metadata and a retained backup.

Keep separate directories for byte-pinned inputs, an optional existing spot cache,
and each inventory attempt. The output directory must not exist before `fetch`;
the collector creates it and refuses reuse. An empty cache is valid: missing
pinned spot archives are downloaded only if they match the original digest.
Existing corrupted cache files are errors, not permission to replace them.

Input SHA-256 pins (raw Git blob bytes at the collector commit):

| Input | SHA-256 |
|---|---|
| `docs/EXPERIMENT_SPEC_V3.md` | `9f559da41b33b704d22f1322ca6018ec06ba50f79a8270c81d35fb3cfe9a7b31` |
| `config/datasets/full-range-2017-2024.manifest.json` | `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e` |
| Ordered request plan, compact JSON | `9a9bc20f1383aadd9fb9f0739dc4af1f8b07bc88a198f989d1eca5c6612e069d` |

Windows checkout conversion can change the spec's bytes to CRLF. Do not change
the registered pin to accept a checkout hash. Export the raw blob with Python's
`subprocess.check_output(["git", "show", commit + ":" + path])` and write it in
binary mode. Avoid PowerShell text redirection, which can change encoding or
line endings. Verify the exported bytes against the table before use.

## Reviewed execution contract

Before owner start, record the exact proposal head and reviewer verdict, collector
commit, selected absolute directories, input hashes, whether any earlier futures
snapshot exists, and the intended recovery mode. Verify sufficient free space and
that no other collector uses the same output directory. Use the repository's
locked Python environment. Set `PYTHONPATH` to that checkout's absolute `src`
directory: otherwise an older installed copy can be imported accidentally.

Run `python scripts/v3_inventory.py plan` offline first. It must show 2,710
identities, the plan hash above, spot from 2018-06, futures discovery from 2017-01,
last month 2024-12, and `fetch_authorized: false`. The early discovery horizon
records unavailable archives; it does not establish contract listing dates.

After the explicit owner start only, invoke the existing `fetch` subcommand with:

- `--output`: the fresh attempt directory;
- `--cache-dir`: the selected existing spot-cache root or an empty cache location;
- `--spec-file` and `--spec-sha256`: the byte-exact exported spec and its table pin;
- `--spot-manifest` and `--spot-manifest-sha256`: the exported source manifest and
  its table pin;
- recovery flags below whenever a previous valid futures snapshot exists.

Public network access is restricted by the collector to the fixed development
archives and their checksums on `data.binance.vision`, spot filters at
`data-api.binance.vision/api/v3/exchangeInfo`, and the one-time futures filters at
`fapi.binance.com/fapi/v1/exchangeInfo`. No API keys, signed requests, orders,
directory listings or 2025-and-later market data. Current filter snapshots are the
spec's explicit exception for filter metadata, not access to reserved prices.
The collector refuses redirects and bounds response sizes. Capture start/end
times, collector SHA, exit status and error text outside the inventory directory.

## Retention and recovery

Retain the entire attempt directory, including both raw `snapshots/*.json`, all
`archives/`, partial files and `inventory.manifest.json` if produced. A manifest
file existing after a failed process is not proof of completed preparation.
Never clean or reuse a failed directory, silently retry the task, or fetch a
replacement futures snapshot to make a run succeed.

For an interrupted or failed attempt, first establish that its worker has stopped.
If a valid raw futures snapshot was retained, a separately authorized recovery
uses a fresh output directory plus both `--reuse-futures-snapshot <saved path>`
and `--futures-snapshot-sha256 <verified digest>`, plus
`--reuse-spot-snapshot <saved path>` and `--spot-snapshot-sha256 <verified digest>`
when the original spot response is available. The CLI validates supplied digests
and filter contents before constructing transport. With both saved responses,
neither filter endpoint is called. Preserve both original responses and do not
silently replace either. Recovery does not checkpoint archive
downloads. The original attempt stays intact. If no valid snapshot survives,
stop and report the state to the owner;
another futures request needs an explicit decision, not an automatic retry.

After a successful fetch, hash the final manifest and run the offline verifier:
`python scripts/v3_inventory.py verify --output <attempt directory> --manifest-sha256 <digest>`.
Retain its output and exit status. Verification rehashes and reparses local
archives and snapshots and recomputes coverage; it does not authorize replay.
Copy retained data to the chosen backup location and verify those same pins there.
No backup destination is assumed or silently created by this proposal.

## Repository delivery and the next gate

Submit the raw filter snapshots, reproducible manifest and a concise verification
report on a separate data PR. Preserve raw bytes in Git (explicit binary attributes
where needed); verify hashes from `git show` after staging and committing, not
only from working-tree files. Do not commit large archive ZIPs. The manifest pins
their paths and hashes; the local original and backup retain their actual bytes.
Check real artifact sizes before submission; do not route them through the remote
Bob report publisher or assume its 200,000-byte bound is adequate.

The report must distinguish missing archives, excluded months, masks, candidate
first-full months, portfolio membership, and missing mandatory close hours. These
are coverage evidence, not automatic eligibility approval or a trading result.
It must disclose that today's exchange filters stand in for historical filters.

Only after review of the delivered manifest, coverage decisions and complete
replay code may the completing registration event pin that manifest and reviewed
code to the trial ID. `replay_ready: false` in preparation is deliberate. No
historical strategy replay, parameter selection or reserved-window access is
authorized by this proposal or by successful inventory verification.

## Executor decision required before an executable task

The frozen spec sections 2 and 9 name Bob as the owner-started collector. The
existing GitHub Bob runner cannot write to the owner's local E: drive and discards
large raw artifacts after publishing its small report. A local Bob session with
access to E: would preserve the rule; that access has not been established.

If no such session is available, the recommended narrow replacement is:
**allow Codex Desktop to execute this one owner-started, independently reviewed,
pinned local data-collection task on E:, while Bob reviews the task and the
delivered manifest/coverage.** Retain all endpoint restrictions, both original
snapshots, fresh attempt directories, failure evidence, reserved-window prohibition
and separate completing-registration gate. This does not delegate trading or
change any strategy or acceptance criterion.

Downside: Codex would prepare and execute the collector, reducing separation of
implementation and execution. Independent Bob review and retained byte hashes help
audit it but do not eliminate that loss of independence. Keeping Bob as executor
instead requires a confirmed local Bob session or a separately reviewed transfer
mechanism from the remote runner; either adds setup work.

This paragraph is a proposal, not approval. If the owner chooses the exception,
record it in the frozen spec and append a successor candidate registration before
execution, then review the exact executable task. Ask for the final download go
only after that task is concrete and reviewed. No market-data request has run.

## Checks performed for this proposal

Read the collector and CLI's input validation, transport bounds, snapshot ordering,
fresh-directory requirement, archive pin reuse, recovery arguments and offline
verification paths. Recomputed raw input hashes and the offline plan; verified
the spec's local difference is solely CRLF conversion. No market archives or
filter endpoints were fetched. Exact-head external review remains required.
