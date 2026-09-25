# Bob: BTCUSDT funding-rate cadence over all months (2020–2024)

- **Author:** Bob (IBM)
- **Date:** 2026-09-25
- **Branch:** `bob/funding-cadence`
- **Reviewed Scope:** Task `docs/tasks/2026-09-25-bob-funding-cadence.md` (authored by Claude on PR #16 / branch `claude/repo-connection-mqhoss`)
- **Data Source:** Binance Vision Futures UM monthly archive (`data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/`)
- **Period:** 2020-01 to 2024-12 (60 months total, 1,827 days, strictly before the 2025-01 reserved window)

---

## 1. Executive Summary & Core Answers

1. **Header Consistency:**
   - **Every** month (60/60) has the exact header: `calc_time,funding_interval_hours,last_funding_rate`.
   - Zero header deviations across all 5,481 rows.
2. **Interval Value & Cadence:**
   - `funding_interval_hours` is **identically 8** in every single row across all 60 months.
   - **Zero** missing settlements (expected 5,481 for 1,827 days × 3 settlements/day; actual is exactly 5,481).
   - **Zero** duplicate scheduled times.
   - **Zero** steps deviating from 8.0 hours.
3. **Interval Semantic Interpretation (Question 3):**
   - Because `funding_interval_hours` never changes from 8 across the entire 2020–2024 dataset, whether the field describes the interval to the *next* settlement or the interval *ending* at that record is **not determinable** from historical data changes, and has **zero observable impact** on backtesting or strategy execution in the 2020–2024 dataset.
4. **Timestamp Offsets:**
   - **Zero** records have `calc_time` more than 60 seconds past the whole UTC hour.
   - The **largest offset in the entire 5,481 record archive is 47 milliseconds (0.047 seconds)**, occurring at `calc_time = 1631865600047` (2021-09-17 08:00:00.047 UTC).
   - Flooring `calc_time` to the whole UTC hour (`(calc_time // 3600000) * 3600000`) is 100% exact and lossless.

---

## 2. Step 4 Metrics Summary

| Check Item | Count / Value | Notes |
| --- | --- | --- |
| Checksums verified | 60 / 60 | SHA-256 matched for all `.zip` files against `.CHECKSUM` |
| Total records parsed | 5,481 | Exactly 1,827 days × 3 intervals/day |
| Non-8h steps between consecutive settlements | **0** | Every step is exactly 8 hours |
| Duplicate scheduled timestamps | **0** | No duplicates found |
| Rows with `calc_time` offset > 60s past the hour | **0** | All timestamps within 47 ms of the UTC hour |
| Largest timestamp offset past the hour | **47 ms** (0.047s) | Record `1631865600047` in month `2021-09` |
| Step mismatches with previous record interval | **0** | All steps equal previous interval (8) |
| Step mismatches with next record interval | **0** | All steps equal next interval (8) |

---

## 3. Per-Month Survey Table (60 Months)

| Month | Header | Rows | First calc_time | Last calc_time | Intervals |
| --- | --- | --- | --- | --- | --- |
| 2020-01 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1577836800000 | 1580486400000 | 8 |
| 2020-02 | `calc_time,funding_interval_hours,last_funding_rate` | 87 | 1580515200000 | 1582992000000 | 8 |
| 2020-03 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1583020800000 | 1585670400001 | 8 |
| 2020-04 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1585699200002 | 1588262400000 | 8 |
| 2020-05 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1588291200000 | 1590940800000 | 8 |
| 2020-06 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1590969600000 | 1593532800002 | 8 |
| 2020-07 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1593561600002 | 1596211200000 | 8 |
| 2020-08 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1596240000005 | 1598889600001 | 8 |
| 2020-09 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1598918400000 | 1601481600000 | 8 |
| 2020-10 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1601510400000 | 1604160000000 | 8 |
| 2020-11 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1604188800000 | 1606752000000 | 8 |
| 2020-12 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1606780800000 | 1609430400010 | 8 |
| 2021-01 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1609459200002 | 1612108800000 | 8 |
| 2021-02 | `calc_time,funding_interval_hours,last_funding_rate` | 84 | 1612137600001 | 1614528000000 | 8 |
| 2021-03 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1614556800000 | 1617206400000 | 8 |
| 2021-04 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1617235200025 | 1619798400003 | 8 |
| 2021-05 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1619827200002 | 1622476800000 | 8 |
| 2021-06 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1622505600001 | 1625068800005 | 8 |
| 2021-07 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1625097600000 | 1627747200003 | 8 |
| 2021-08 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1627776000005 | 1630425600003 | 8 |
| 2021-09 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1630454400000 | 1633017600005 | 8 |
| 2021-10 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1633046400012 | 1635696000001 | 8 |
| 2021-11 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1635724800009 | 1638288000000 | 8 |
| 2021-12 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1638316800000 | 1640966400000 | 8 |
| 2022-01 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1640995200006 | 1643644800000 | 8 |
| 2022-02 | `calc_time,funding_interval_hours,last_funding_rate` | 84 | 1643673600010 | 1646064000002 | 8 |
| 2022-03 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1646092800002 | 1648742400015 | 8 |
| 2022-04 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1648771200000 | 1651334400015 | 8 |
| 2022-05 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1651363200000 | 1654012800000 | 8 |
| 2022-06 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1654041600000 | 1656604800000 | 8 |
| 2022-07 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1656633600001 | 1659283200019 | 8 |
| 2022-08 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1659312000010 | 1661961600013 | 8 |
| 2022-09 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1661990400012 | 1664553600007 | 8 |
| 2022-10 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1664582400008 | 1667232000010 | 8 |
| 2022-11 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1667260800000 | 1669824000015 | 8 |
| 2022-12 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1669852800001 | 1672502400000 | 8 |
| 2023-01 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1672531200000 | 1675180800007 | 8 |
| 2023-02 | `calc_time,funding_interval_hours,last_funding_rate` | 84 | 1675209600013 | 1677600000005 | 8 |
| 2023-03 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1677628800016 | 1680278400011 | 8 |
| 2023-04 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1680307200000 | 1682870400010 | 8 |
| 2023-05 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1682899200004 | 1685548800000 | 8 |
| 2023-06 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1685577600008 | 1688140800001 | 8 |
| 2023-07 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1688169600000 | 1690819200001 | 8 |
| 2023-08 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1690848000000 | 1693497600000 | 8 |
| 2023-09 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1693526400000 | 1696089600000 | 8 |
| 2023-10 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1696118400000 | 1698768000000 | 8 |
| 2023-11 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1698796800000 | 1701360000000 | 8 |
| 2023-12 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1701388800000 | 1704038400000 | 8 |
| 2024-01 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1704067200000 | 1706716800000 | 8 |
| 2024-02 | `calc_time,funding_interval_hours,last_funding_rate` | 87 | 1706745600000 | 1709222400000 | 8 |
| 2024-03 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1709251200000 | 1711900800001 | 8 |
| 2024-04 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1711929600000 | 1714492800000 | 8 |
| 2024-05 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1714521600000 | 1717171200000 | 8 |
| 2024-06 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1717200000000 | 1719763200000 | 8 |
| 2024-07 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1719792000000 | 1722441600000 | 8 |
| 2024-08 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1722470400000 | 1725120000000 | 8 |
| 2024-09 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1725148800000 | 1727712000000 | 8 |
| 2024-10 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1727740800000 | 1730390400000 | 8 |
| 2024-11 | `calc_time,funding_interval_hours,last_funding_rate` | 90 | 1730419200000 | 1732982400000 | 8 |
| 2024-12 | `calc_time,funding_interval_hours,last_funding_rate` | 93 | 1733011200000 | 1735660800000 | 8 |

---

## 4. Questions and Observations for Claude and Codex

1. **Deterministic 8-Hour Alignment:**
   - Since every single historical settlement from 2020-01-01 00:00:00 UTC through 2024-12-31 16:00:00 UTC occurs on the 8-hour boundary (00:00, 08:00, 16:00 UTC) with offsets < 50ms, can Spec §3 G safely freeze the alignment rule as `floor(calc_time to UTC hour)`?
2. **Missing/Duplicated Settlement Edge Cases:**
   - The archive has 0 missing or duplicate settlements in 2020–2024. Does the spec require any additional runtime fail-closed guard beyond checking `step == 8` and `duplicate_timestamp == False` during dataset ingestion?
3. **Semantic Field Interpretation:**
   - Because `funding_interval_hours` is constant across all 5,481 rows, the forward vs backward interval interpretation cannot produce different behavior. Is there any remaining blocker to freezing Variant G specification text?
