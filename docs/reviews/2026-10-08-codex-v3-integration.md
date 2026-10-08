# V3 inventory integration and remaining fetch gates

Index: Codex integrated fixed request planning, committed spot reuse, coverage candidates and an explicit fetch CLI; synthetic-only, owner-started task and artifact delivery remain pending.

Branch: `codex/v3-data-integration`, built on PR #211 foundation head
f02ec0a0aa65aa4466c37b4ee7ba040f3ad901c1. The frozen V3 experiment remains unchanged.

## Implemented

`scripts/v3_inventory.py` composes the data helpers:

- A fixed 2,710-archive discovery plan for all ten coins: spot 2018-06..2024-12;
  futures prices and funding 2017-01..2024-12. The deliberately early futures
  discovery bound establishes absences before candidate entry dates; it does not
  assert that contracts existed in 2017. No directory listing or reserved request.
- The existing spot manifest must match an explicit SHA-256. All requested rows
  for its nine coins must be present as metadata, including missing archives.
  Present archives retain their original checksum and canonical local cache path.
- Complete inventory diagnostics propose each coin's first full spot/futures month,
  first eligible portfolio month, spot-history calendar days, all later exclusions,
  permitted previous-day close hours for futures and the spot hold benchmark, and
  the BTC-derived first test quarter/count.
- A partial initial month is skipped when proposing a first full month. The earliest
  observed candle is evidence of available history, not proof of the exchange's
  listing date. Missing early archives can hide earlier history. Candidates remain
  review-required, and `replay_ready` stays false. Calendar warmup length is not a
  count of valid signal observations; rules must still check their own history.
- `plan` is offline. `fetch` is explicit, checks spec/manifest content pins before
  constructing the transport, and is intended only for the reviewed owner-started
  task. `verify` rehashes the inventory and files, re-parses archives and filters,
  and recomputes coverage offline. It rejects changed files or diagnostic metadata.
  No task file or automatic trigger is added by this integration.

## Evidence

Request-plan SHA-256 (compact ordered JSON):
`9a9bc20f1383aadd9fb9f0739dc4af1f8b07bc88a198f989d1eca5c6612e069d`.
Source manifest at main 3f1ef45b508797f675b957d8b6c4eb04382db77a:
`config/datasets/full-range-2017-2024.manifest.json`, raw Git-blob SHA-256
`069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e`.
The loader independently accounted for 711 hourly rows, preserving 665 archive pins
and 46 recorded absences. Only committed metadata was read, not archive prices.

Synthetic tests cover late listings, funding-delayed entry, distinct spot/futures
close availability, complete request coverage, source tampering/duplicates, and
end-to-end inventory assembly without real network. Initial missing APIs and metadata
fields were observed failing before implementation. All 99 focused tests pass;
repository Ruff, format, mypy and Bandit pass. An independent Codex reviewer found
no actionable issues through 0df648384b4a423a3878f2e9f9fc36dc2635ca44 and independently
ran 53 synthetic tests. The subsequent offline verifier has its own tamper tests;
it was not in that review. External exact-head review and CI remain pending;
#211's evidence is separate.

Follow-up verification: the new offline verifier was independently reviewed at
70e5aacd64f8192bda9d8846899b2d009db38e80, with no concrete findings. Four build/CLI
tests and additional synthetic diagnostic/path-tamper reproductions passed. That
head incorporates #211's dual-notional-filter fix; the combined focused suite is
now 101 passing tests. No real data or network was used for these checks.

## Before an owner-started Bob fetch

The current Bob workflow has two concrete integration constraints:

1. `.github/workflows/bob-task.yml` tells the worker that network use is limited to
   `data.binance.vision`. Frozen V3 section 2 separately permits spot filters and one
   public futures exchangeInfo request. A task-specific reviewed workflow exception
   must reconcile these instructions before dispatch; a task file cannot silently
   override the worker's higher-priority prompt.
2. `scripts/validate_bob_artifact.py` accepts one report up to 200,000 bytes and one
   short summary. The worker discards raw data artifacts. V3 requires committing the
   one-time raw futures response, both snapshot hashes, and a reconstructible manifest.
   Their full size is not known before retrieval. Do not assume they fit in a report
   or start a one-time fetch whose evidence cannot be retained. A separately reviewed
   bounded artifact-delivery path (or an owner-started local Bob task retaining files)
   is needed; no publisher permission or size limit is broadened here.

Codex owns the remaining delivery proposal and task preparation. The owner starts
the actual fetch after exact-head external review.
No replay runs before the reviewed manifest/code completing registration event.
