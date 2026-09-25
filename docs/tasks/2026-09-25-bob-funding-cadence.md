# Task for Bob: BTCUSDT funding-rate cadence over all months (variant G)

- **Written by:** Claude, 2026-09-25, following Bob's P8 survey (`bob/p8-data-survey`
  `761b2ee`) and Codex's G review (PR #16, comment 5826926934).
- **Review:** Codex reviews this task file on PR #16. **Start only after a Codex → Bob
  handoff comment approves it at a named SHA** (or the owner says go).
- **Branch for your report:** `bob/funding-cadence`.
- **Read-only:** do not change code, configs, dataset specs or manifests.

## Goal

Spec §3 G stays unfrozen until three questions about the funding archive are answered.
The P8 survey sampled one month only.
1. Does **every** month from 2020-01 to 2024-12 have the header
   `calc_time,funding_interval_hours,last_funding_rate`?
2. Is `funding_interval_hours` ever anything other than 8, and is any expected
   settlement ever missing or duplicated?
3. Where the interval changes (if it ever does), does the value describe the interval to
   the **next** settlement or the one **ending** at that record?

## Scope (fixed)

- **Files:** the 60 files `BTCUSDT-fundingRate-YYYY-MM.zip`, 2020-01 to 2024-12. They
  are at `https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/`,
  each with its `.CHECKSUM`.
- **Reserved window:** nothing from 2025-01 onward. Use only the host
  `data.binance.vision`.
- **Redirects:** apply the same rule as the P8 task. Check that a redirect target is
  `https://data.binance.vision/...` before following it.

## Steps

1. Download each zip and its `.CHECKSUM`. Verify SHA-256. Keep the files outside git.
2. For each file, record:
   - the header line;
   - the row count;
   - the first and last `calc_time`;
   - the set of `funding_interval_hours` values.
3. Across all months in order, compute `scheduled = floor(calc_time to the UTC hour)`
   and, for each consecutive pair of records:
   - `step = scheduled(next) − scheduled(prev)` in hours;
   - whether `step` equals the **previous** record's interval;
   - whether `step` equals the **next** record's interval.
4. Report:
   - every step that is not 8 hours;
   - every scheduled time that appears twice;
   - every row whose `calc_time` is more than 60 seconds past its scheduled hour;
   - the largest such offset in the whole set.

## Validity checks

- All 60 checksums match. A mismatch is a stop condition.
- The report gives counts for every item in step 4, including zeros.

## What to report

Write `docs/reviews/2026-09-25-bob-funding-cadence.md` and add it to the index. It
contains:
- the per-month table from step 2;
- the step-4 lists and counts;
- the largest offset past the hour;
- for question 3: either "no interval changes in 2020–2024, so not determinable", or the
  evidence at each change.

Report facts only, and list the consequences as questions for Claude and Codex. Then
post a **Bob → Claude/Codex handoff** comment on PR #16.

## Stop conditions

Stop, keep everything, and report if:
- a checksum mismatches;
- a redirect leaves `data.binance.vision`;
- anything would touch 2025-01 or later;
- anything asks for a login or key.
