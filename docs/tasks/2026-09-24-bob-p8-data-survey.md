# Task for Bob: P8 data availability survey (variants G and H)

- **Written by:** Claude, 2026-09-24, at the owner's request to delegate data work to Bob.
  Revised after Codex's task review (PR #16, comment 5823663842).
- **Review:** Codex reviews this task file on PR #16. **Start only after a Codex → Bob
  handoff comment approves this task at a named SHA** (or the owner says go).
- **Branch for your report:** `bob/p8-data-survey`.
- **Read-only:** no code, config, dataset spec or manifest changes.

## Goal

Spec v1 P8 needs, before G and H can be implemented:
1. BTCUSDT USDⓈ-M funding-rate monthly archives with published checksums;
2. daily (`1d`) klines from the month of the most recent halving (2020-05 for both
   development windows).

Claude has **not** checked that these exist for every month and pair. One likely
problem: SOLUSDT was listed on Binance spot around 2020-08, **after** the 2020-05
halving, so H's "highest daily close since the halving" may be undefined for SOL in
the development windows. The survey establishes the facts so the spec can handle them
before it is frozen.

## Scope (fixed)

| Data | URL pattern | Months |
| --- | --- | --- |
| Funding rate | `https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-YYYY-MM.zip` (+ `.CHECKSUM`) | 2020-01 to 2024-12 |
| Daily klines | `https://data.binance.vision/data/spot/monthly/klines/<PAIR>/1d/<PAIR>-1d-YYYY-MM.zip` (+ `.CHECKSUM`) for BTCUSDT, ETHUSDT, XRPUSDT, SOLUSDT, ADAUSDT | 2020-01 to 2024-12 |

**Nothing from 2025-01 onward**: that is the reserved window (spec §7). Only the host
`data.binance.vision` is used.

## Commands

1. For every URL above, send an HTTP `HEAD` for the zip and for its `.CHECKSUM`. Record
   the status code and `Content-Length`. Do **not** follow redirects automatically:
   - if a response is a redirect, check that its `Location` is an `https` URL on
     `data.binance.vision`, and only then request it;
   - any other redirect target is a stop condition.

   Classify every URL as exactly one of:
   - **present:** 200;
   - **missing:** 404, the only status counted as absence;
   - **error/unknown:** any other status (for example 403, 429 or 5xx), a timeout, or a
     network or TLS error.

   An error is **never** reported as missing. You may retry an error at most twice,
   with at least 10 seconds between tries, and must report every attempt.
2. Find **SOLUSDT's first available `1d` month**, the earliest month classified as
   present in step 1.
3. Download two archives and verify each one's SHA-256 against its `.CHECKSUM` (these
   are the only archives this task authorises you to download):
   - the funding file `BTCUSDT-fundingRate-2022-06.zip`;
   - the daily file for SOLUSDT's first available month from step 2.

   Record:
   - for both files: the CSV header and the first 3 rows;
   - for the funding file: the unit of `calc_time` (ms or µs) and the number of
     settlements per day;
   - for the SOL file: the first daily open time, in UTC.

Keep downloads outside git (for example `../bob-data/p8/`).

## Validity checks

- Every result row names the exact URL and HTTP status.
- The two downloaded files match their published checksums.
- The report gives the number of URLs classified as present, missing and error. Any
  error is listed with every attempt, and the survey is marked incomplete for that URL.

## What to report

Write the report to `docs/reviews/2026-09-24-bob-p8-data-survey.md` and add it to the
index. It contains:
- a table of months × series: present, missing, error/unknown, or checksum missing;
- the two sample files: their headers, rows, units and SHA-256;
- SOL's first available daily month;
- **facts only.** List the consequences for H and G as questions for Claude and Codex,
  not as decisions. For example: "H for SOL in practice-2022 has no daily data from
  2020-05 to 2020-07."

Then post a **Bob → Claude/Codex handoff** comment on PR #16.

## Stop conditions

Stop, keep everything, and report if any of these happens:
- a checksum mismatches;
- a redirect points anywhere other than `https://data.binance.vision/...`;
- an error persists after two retries on more than 5 URLs (report what you have);
- any request would touch 2025-01 or later;
- anything asks for a login or key.
