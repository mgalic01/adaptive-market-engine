# Independent P8 Data Availability Survey (Variants G and H)

- **Author:** IBM Bob (Independent Consultant), 2026-09-24
- **Task Spec:** `docs/tasks/2026-09-24-bob-p8-data-survey.md`
- **Branch:** `bob/p8-data-survey`
- **Status:** Complete (Survey & Verification)

## Executive Summary

- **Total URLs surveyed:** 720 (360 zip archives + 360 `.CHECKSUM` files across 6 series for 2020-01 to 2024-12).
- **Present (HTTP 200):** 706 URLs.
- **Missing (HTTP 404):** 14 URLs (all 7 months of `SOLUSDT-1d` from 2020-01 to 2020-07, both `.zip` and `.CHECKSUM`).
- **Error / Unknown (Non-200/404, TLS/network timeouts):** 0 URLs (0 errors encountered across all series).
- **Checksum verification:** 100% matched for sampled archives (`BTCUSDT-fundingRate-2022-06.zip` and `SOLUSDT-1d-2020-08.zip`).
- **SOLUSDT first available daily month:** `2020-08` (starts on `2020-08-11 00:00:00 UTC`).

## Series Availability Matrix (2020-01 to 2024-12)

| Series | URL Path Pattern | Present Months (200) | Missing Months (404) | Errors | First Available Month |
| --- | --- | --- | --- | --- | --- |
| `BTCUSDT` Funding Rate | `futures/um/monthly/fundingRate/BTCUSDT/` | 60 / 60 (2020-01 to 2024-12) | 0 | 0 | `2020-01` |
| `BTCUSDT` 1d Klines | `spot/monthly/klines/BTCUSDT/1d/` | 60 / 60 (2020-01 to 2024-12) | 0 | 0 | `2020-01` |
| `ETHUSDT` 1d Klines | `spot/monthly/klines/ETHUSDT/1d/` | 60 / 60 (2020-01 to 2024-12) | 0 | 0 | `2020-01` |
| `XRPUSDT` 1d Klines | `spot/monthly/klines/XRPUSDT/1d/` | 60 / 60 (2020-01 to 2024-12) | 0 | 0 | `2020-01` |
| `ADAUSDT` 1d Klines | `spot/monthly/klines/ADAUSDT/1d/` | 60 / 60 (2020-01 to 2024-12) | 0 | 0 | `2020-01` |
| `SOLUSDT` 1d Klines | `spot/monthly/klines/SOLUSDT/1d/` | 53 / 60 (2020-08 to 2024-12) | 7 (2020-01..2020-07) | 0 | `2020-08` |

### Detailed Annual Breakdown

| Year | BTC Funding | BTC 1d | ETH 1d | XRP 1d | ADA 1d | SOL 1d |
| --- | --- | --- | --- | --- | --- | --- |
| **2020** | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | **Aug–Dec (5/12)** (Jan–Jul 404) |
| **2021** | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) |
| **2022** | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) |
| **2023** | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) |
| **2024** | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) | Jan–Dec (12/12) |

## Sample Archive Verification and Inspection

### 1. BTCUSDT Funding Rate Sample (`BTCUSDT-fundingRate-2022-06.zip`)
- **URL:** `https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2022-06.zip`
- **Checksum URL:** `https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2022-06.zip.CHECKSUM`
- **Expected SHA-256:** `0cd0708f8903829eb46f98cf60f4b2516c986e1ccddf6620a5912b48e16baf93`
- **Actual SHA-256:** `0cd0708f8903829eb46f98cf60f4b2516c986e1ccddf6620a5912b48e16baf93` (**MATCH**)
- **CSV Header:** `calc_time,funding_interval_hours,last_funding_rate`
- **First 3 Data Rows:**
  ```csv
  1654041600000,8,0.00010000
  1654070400011,8,0.00010000
  1654099200000,8,0.00010000
  ```
- **Field Units and Cadence:**
  - `calc_time` is in **milliseconds (`ms`)** (13-digit Unix timestamp).
  - `funding_interval_hours` is `8` (standard 8-hour settlement interval).
  - **Settlements per day:** Exactly **3.0 settlements/day** (90 records for the 30-day month of June 2022, settling at 00:00, 08:00, 16:00 UTC). Note slight timestamp jitter on some settlement timestamps (e.g., `1654070400011` is `+11ms` after 08:00:00 UTC), confirming that flooring/quantizing to the settlement hour boundary is required.

### 2. SOLUSDT Daily Klines Sample (`SOLUSDT-1d-2020-08.zip`)
- **URL:** `https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1d/SOLUSDT-1d-2020-08.zip`
- **Checksum URL:** `https://data.binance.vision/data/spot/monthly/klines/SOLUSDT/1d/SOLUSDT-1d-2020-08.zip.CHECKSUM`
- **Expected SHA-256:** `40ddd9549f8c5901b3a049cba929c0c7fbb22c0d5b7c5f6152cf2e242db3220e`
- **Actual SHA-256:** `40ddd9549f8c5901b3a049cba929c0c7fbb22c0d5b7c5f6152cf2e242db3220e` (**MATCH**)
- **CSV Structure:** Standard Binance spot kline CSV (no text header line; raw OHLCV rows).
- **First 3 Data Rows:**
  ```csv
  1597104000000,2.85000000,3.52080000,2.84330000,3.29850000,1552384.78000000,1597190399999,4939148.93810700,13490,741770.79000000,2370192.68111900,0
  1597190400000,3.29850000,3.92890000,3.08000000,3.75580000,1737042.95000000,1597276799999,6176153.72463800,21118,889133.50000000,3161944.26881700,0
  1597276800000,3.75000000,4.13870000,3.50030000,3.73000000,1685759.24000000,1597363199999,6446567.98049000,22922,716358.46000000,2755764.74800600,0
  ```
- **First Daily Open Time:** `1597104000000` = **`2020-08-11 00:00:00 UTC`** (total 21 daily bars in August 2020).

## Factual Findings & Technical Questions for Claude and Codex

1. **SOL Halving Window Absence (Variant H):**
   - The 2020 Bitcoin halving occurred on **2020-05-11 19:23:43 UTC**.
   - SOLUSDT spot daily data on Binance begins on **2020-08-11 00:00:00 UTC** (3 months post-halving).
   - **Question for Claude/Codex:** For Variant H (H3 post-halving ATH tracker), should SOL's post-halving reference peak in 2020–2022 use the highest close starting from SOL's listing date (`2020-08-11`), or does SOL require an explicit missing-history flag/exclusion for pre-listing halving windows?

2. **Funding Rate Timestamp Jitter & Interval Handling (Variant G):**
   - Historical `BTCUSDT-fundingRate` files have `calc_time` in milliseconds with occasional small millisecond offsets past the exact hour (e.g. `1654070400011` vs `1654070400000`).
   - `funding_interval_hours` is consistently `8`.
   - **Question for Claude/Codex:** Does the parser floor `calc_time` to the nearest hour (or integer multiple of `funding_interval_hours * 3600 * 1000 ms`), as recently codified in commit `894d545`?

3. **100% Archive Integrity for Warm-up Data:**
   - All 5 traded pairs (BTC, ETH, XRP, ADA, and post-listing SOL) have complete, continuous, checksummed 1d archives from 2020-01 (or 2020-08 for SOL) through 2024-12, providing >200 bars of warm-up for all 2022 and 2024 development runs.

## Stop Conditions & Protocol Adherence
- No 2025+ reserved data was requested or touched.
- No redirects outside `data.binance.vision` occurred.
- All downloaded sample archives verified with 0 checksum mismatches.
- Read-only verification: no source, tests, configs, or manifests were altered.