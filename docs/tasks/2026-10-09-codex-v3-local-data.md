# V3 local historical data collection task

**State: prepared for review; not started.** Executor: Codex Desktop. Reviewer:
Bob. The owner approved the executor exception, not the download start. Merging
this non-Bob task file does not launch the Bob workflow. Start only after Bob's
substantive review of this full task head, required checks, and the owner's final
go naming this task. This is data preparation, not strategy replay.

## Fixed inputs and locations

- Collector checkout commit: `5822e0dac8501a0ab0f55ce96827c44782daf2d5`.
  Use the entire checkout at that commit, including its dependencies and `src/`.
- Spec blob at that commit: `docs/EXPERIMENT_SPEC_V3.md`, SHA-256
  `e337dbcaa89ca1bfeb5293f678aded60c3350aa8465c594e7a8c1c78aae3c191`.
- Spot source manifest blob at that commit:
  `config/datasets/full-range-2017-2024.manifest.json`, SHA-256
  `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e`.
- Request plan: 2,710 archive identities, SHA-256
  `9a9bc20f1383aadd9fb9f0739dc4af1f8b07bc88a198f989d1eca5c6612e069d`.
- Root: `E:/adaptive-market-engine/v3`.
- Isolated detached collector checkout: `E:/adaptive-market-engine/v3/collector-5822e0d`.
- Raw exported inputs: `E:/adaptive-market-engine/v3/inputs-5822e0d`.
- Empty spot-cache location: `E:/adaptive-market-engine/v3/spot-cache`.
- Fresh output: `E:/adaptive-market-engine/v3/inventory-20261009-01`.
- Log directory, outside output: `E:/adaptive-market-engine/v3/logs-20261009-01`.

The root did not exist at preparation; no earlier V3 collection was performed in
this session. Recheck before starting. If output, prior V3 snapshots or evidence
from an earlier attempt exist, stop and inspect their provenance; do not overwrite,
remove them, refetch filters or silently choose a new attempt. Recovery is a
separate reviewed/authorized operation. An empty spot cache is deliberate; the
collector fetches non-ADA spot files only against their existing source pins.

E: had 729,308,557,824 bytes free at preparation. Recheck space. The 2,710 times
64 MiB archive limit is a theoretical ceiling of 169.4 GiB, not an expected
download size; allow additional room for metadata and retained copies. Report
actual bytes afterwards. No paid service or API key is used.

## Offline preparation after review, before any network request

1. Check no other collector is running against these paths. Create an isolated
   Git worktree at the exact collector commit, without modifying an active test
   checkout. Resolve all paths under the named E: root. No deletion is permitted.
2. Use the repository's locked Python environment. Set `PYTHONPATH` to the
   collector checkout's absolute `src` directory. Verify its HEAD and clean tracked
   code. Record Python version and the collector SHA in the external log directory.
3. Export both inputs from raw Git blobs using Python `subprocess.check_output`
   with separate Git arguments and binary writes. Do not use PowerShell text
   redirection or normalize bytes. Verify the SHA-256s above.
4. Run `python scripts/v3_inventory.py plan` offline in the collector checkout.
   Require 2,710 identities, the exact plan hash, spot start 2018-06, futures
   discovery start 2017-01, final month 2024-12 and `fetch_authorized: false`.
   Early futures discovery records missing archives; it is not a listing-date claim.
5. Record the reviewed task's full SHA and Bob verdict and the owner's final start.
   No network request precedes that start.

## One authorized collection attempt

From the pinned collector checkout, with the pinned environment, invoke:

```text
python scripts/v3_inventory.py fetch
  --output E:/adaptive-market-engine/v3/inventory-20261009-01
  --cache-dir E:/adaptive-market-engine/v3/spot-cache
  --spec-file E:/adaptive-market-engine/v3/inputs-5822e0d/EXPERIMENT_SPEC_V3.md
  --spec-sha256 e337dbcaa89ca1bfeb5293f678aded60c3350aa8465c594e7a8c1c78aae3c191
  --spot-manifest E:/adaptive-market-engine/v3/inputs-5822e0d/spot-source.manifest.json
  --spot-manifest-sha256 069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e
```

The displayed lines are one argument list, not separate shell commands. Capture
stdout, stderr, start/end times and exit status in the log directory. Keep the
owner informed of progress or failure. Do not add retry wrappers.

Only the fixed development archive/checksum requests on `data.binance.vision`,
spot filters at `data-api.binance.vision/api/v3/exchangeInfo`, and the one public
read-only GET of `fapi.binance.com/fapi/v1/exchangeInfo` are permitted. No keys,
signed endpoints, orders, redirects, directory listing or 2025+ market data.
Today's filter metadata is the spec's explicit exception; it is not a reserved
price-data request. Save both original raw snapshots without replacement.

## Verification and delivery

On failure or interruption, retain the entire output and logs, confirm the process
has stopped, and report the exact stage/error. Do not restart automatically, reuse
the output directory, delete partial files or request another filter snapshot.
A separately approved recovery must reuse both valid snapshots with their pinned
digests; if either is absent, resolve that state before any replacement request.

On exit zero, compute the raw manifest SHA-256 and run the same pinned checkout's
offline verifier:

```text
python scripts/v3_inventory.py verify
  --output E:/adaptive-market-engine/v3/inventory-20261009-01
  --manifest-sha256 <computed raw inventory.manifest.json SHA-256>
```

Retain the verifier output and exit status. A manifest file's presence alone is
not success. Do not replay strategies during verification. Keep all archive bytes
locally; do not put ZIP files in Git. Submit the raw snapshots, manifest and a
verification report for Bob review, preserving byte hashes across Git line endings.
Report missing/excluded months, masks, candidate first-full months and joins,
mandatory-close gaps, actual retained size and the current-filter limitation.

Do not silently select a backup destination. Retain the original E: copy and
report backup status honestly. No dataset eligibility decision, completing trial
registration, historical replay, final verdict or reserved-window access follows
automatically from collection. Candidate-space-7 is the current preregistration;
reviewed data and complete replay code still need the separate completion event.
