# V3 local collection recovery: snapshot ceiling

**State: prepared for review; not started.** Codex Desktop executes; Bob reviews
this task and delivered data. Required CI, substantive Bob review of the complete
head and a separate owner recovery start are required before any endpoint request.
Merging this non-Bob task file starts no workflow or collection.

## Why a replacement is necessary

[Attempt 01](../reviews/2026-10-09-codex-v3-collection-failure.md) stopped at the
spot metadata size guard. Neither snapshot nor any archive was saved. Preserve
`E:/adaptive-market-engine/v3/inventory-20261009-01` and `logs-20261009-01` unchanged.
There is no valid snapshot from that attempt to reuse. This task proposes one
replacement spot metadata GET and the first futures metadata GET, then the same
fixed archive plan. It is an explicit recovery exception, not an automatic retry.

The corrected shared snapshot limit is 32 MiB. Downside: a larger bounded response
and JSON parse can consume more memory. The old body was not retained: its total
size and validity are unknown, so the change does not guarantee collection success.

## Fixed inputs

- Entire collector checkout: `6fae09299bdcb382a26e02d094c7271cbfb60ebb`.
- Detached checkout: `E:/adaptive-market-engine/v3/collector-6fae092`.
- Python: existing `E:/adaptive-market-engine/v3/python312/Scripts/python.exe`
  (3.12.14); verify every version in the collector's `requirements-dev.lock`.
- Reuse unchanged raw inputs under `E:/adaptive-market-engine/v3/inputs-5822e0d`:
  `EXPERIMENT_SPEC_V3.md`, SHA-256
  `e337dbcaa89ca1bfeb5293f678aded60c3350aa8465c594e7a8c1c78aae3c191`;
  `spot-source.manifest.json`, SHA-256
  `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e`.
- Plan: 2,710 identities, SHA-256
  `9a9bc20f1383aadd9fb9f0739dc4af1f8b07bc88a198f989d1eca5c6612e069d`.
- Fresh output: `E:/adaptive-market-engine/v3/inventory-20261009-02`.
- Fresh external logs: `E:/adaptive-market-engine/v3/logs-20261009-02`.
- Existing empty cache: `E:/adaptive-market-engine/v3/spot-cache`.

Before execution, inspect the preserved failure provenance, verify no collector is
running, and require the new checkout/output/log paths absent. Verify the cache is
still empty. Existing new-attempt artifacts require investigation, not overwriting
or silently choosing another attempt. Create the isolated checkout and log directory;
verify exact HEAD, clean tracked code, dependency versions, input hashes and free
space. Set PYTHONPATH to its absolute src directory. Run the offline plan and require
the exact hash/count, spot start 2018-06, futures discovery 2017-01, end 2024-12 and
fetch_authorized=false. Record the reviewed task head, Bob verdict and owner start.

## One separately authorized attempt

Run from the pinned checkout, capturing stdout/stderr, start/end and exit status:

```text
E:/adaptive-market-engine/v3/python312/Scripts/python.exe scripts/v3_inventory.py fetch
  --output E:/adaptive-market-engine/v3/inventory-20261009-02
  --cache-dir E:/adaptive-market-engine/v3/spot-cache
  --spec-file E:/adaptive-market-engine/v3/inputs-5822e0d/EXPERIMENT_SPEC_V3.md
  --spec-sha256 e337dbcaa89ca1bfeb5293f678aded60c3350aa8465c594e7a8c1c78aae3c191
  --spot-manifest E:/adaptive-market-engine/v3/inputs-5822e0d/spot-source.manifest.json
  --spot-manifest-sha256 069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e
```

These lines form one argument list. No retry wrapper. Only the original endpoints:
fixed development archives/checksums on data.binance.vision, spot exchangeInfo on
data-api.binance.vision/api/v3/exchangeInfo, and one read-only futures exchangeInfo
GET on fapi.binance.com/fapi/v1/exchangeInfo. No redirects, keys, orders, additional
endpoints, directory listings or 2025+ price/funding data. Save successful original
snapshots. A later failure does not authorize replacing either valid snapshot.

On failure/interruption retain all output/logs, confirm termination, report the
stage and stop network work. Any further recovery is separately reviewed and
owner-authorized; do not rerun this command. On exit zero compute the raw manifest
SHA-256 and run this checkout's offline verify command against output02 and that
hash; preserve its status/output. Manifest existence alone is not verification.

Deliver raw snapshots, manifest, coverage/masks, first-full-month calendar,
mandatory-close gaps, retained size and verification evidence in a PR for Bob.
ZIP archives stay on E:. Report current-filter limitations and backup status;
no backup destination is assumed. Candidate-space-7 and strategy parameters are
unchanged. Data collection does not authorize completing registration, strategy
replay, a final verdict or reserved-window access.
