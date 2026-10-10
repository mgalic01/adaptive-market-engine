# V3 data batch: implementation brief (prepared while register validation runs)

Authority: frozen EXPERIMENT_SPEC_V3 sections 2–3 and 9 step 3 at main 66bddf8.
This is an implementation brief, not a fetch authorization. Owner starts Bob's task.

## Verified reuse boundaries

- backtest.dataset.archive_get currently rejects futures kline paths; it accepts
  only spot monthly klines and futures funding. Do not silently broaden this legacy
  entry point. Add a narrow futures-kline transport in the new fetch script outside
  src, with canonical symbol/1h/month path matching and reserved-month rejection at
  the lowest network boundary. Reject redirects, oversized responses and mismatches.
- funding.parse_funding_rows can supply records, but FundingRecord.valid enforces
  legacy intervals {1,2,4,8}. V3 permits every positive interval dividing 24:
  {1,2,3,4,6,8,12,24}. Add V3 schedule eligibility separately; preserve G semantics.
- Spot manifest has nine of ten required symbols. Reuse verified spot checksums and
  fetch ADA through the same owner-started task; do not commission a duplicate scan.
- Futures exchangeInfo is exactly one read-only GET in the reviewed script outside
  src. Persist response bytes/hash for later offline parsing. No keys or redirects.

## TDD implementation sequence

1. New trend data schema and synthetic fixtures: futures/spot/funding entries,
   checksum provenance, filters, first full months, repair masks and exclusions.
   Tests: unsupported symbol, reserved month at transport, absent checksum, wrong
   digest, duplicate entries, exact response limit and unexpected redirect.
2. V3 funding schedule checker: same interval throughout month, each expected UTC
   slot exactly once, offset 0..60000 ms inclusive, finite rate and numeric bounds.
   Test all divisors of 24, nondivisors, missing/duplicate/off-slot records, interval
   transitions, empty file and month boundary. No importing G's validity decision.
3. Integrity/aggregation: reuse repairing reader without changing it; mask every
   repaired/missing hour. Exclude month above 17% masked. Day needs 20 unmasked hours;
   OHLC aggregates unmasked hours only. Test 19/20-hour boundaries and equality at
   month threshold, gap-spanning returns and independent spot/futures exclusions.
4. Manifest diagnostics: first full month, spot warmup <365 days, every excluded
   month and existence of permitted mandatory-close fallback hour before it starts.
   A manifest summary is not permission to fabricate absent prices or fill timestamps.
5. Pinned external fetch script plus Bob task: network-blocked tests for URL allowlist,
   one futures filter request, reuse verification, all ten symbols, end 2024-12,
   archive checksums and deterministic manifest serialization. No invocation here.
6. Review script at exact SHA with Bob; owner starts data task. Only then inspect
   produced development-data manifest and prepare its reviewed registration pins.

Full strategy code remains after register commit. Futures funding/price event order
and rules in sections 4–8 are later batches, not part of this data preparation batch.
No observed book data exists here; do not infer order-flow imbalance from these bars.
