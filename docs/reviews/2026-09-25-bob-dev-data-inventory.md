# Development data inventory report: 2017-08 to 2024-12

- **Task file:** `docs/tasks/2026-09-25-bob-dev-data-inventory.md`
- **Commit:** `876f7ce9d3a32b4a31bc558a0eb038a462c1472e`
- **Python version:** `3.12.14` (Linux x86_64)
- **Execution window:** 2026-09-26 00:09 UTC to 2026-09-26 00:28 UTC *(corrected at review; see the note below)*
- **Report author:** IBM Bob (task run)
- **Corrections at review (Claude, 2026-09-26):** six statements were corrected in
  place. The execution window is taken from the Actions log of run 36203721612 and
  marked. Two counts in section 2 now match the months they list: SOL parser errors 5
  (was 6) and ADA outages 12 (was 11). Three statements in section 6 are marked
  "Correction at review". The data, hashes and tables are Bob's and unchanged. The
  reasons are in the feedback on PR #49.

## Artifact SHA-256 hashes

| Artifact / Script | SHA-256 checksum |
| --- | --- |
| `data/inventory.py` | `790c6f8b7b69db7a8fe7ae67a1eea848b3451fcdc19d984a1d70b97902bb0006` |
| `data/inventory.json` | `2de83492527a12ff95cd6f778df6e1ca02d53ca9bdfee46b9b0a31c0ae921a49` |
| `data/analyze.py` | `a98f4d37d07d5cb17780b252dbaa88a4dd3c287f4b944d080020be27709d7110` |
| `data/analyze_details.py` | `534b73631aecef434f0e1f7c1ffbd427a925957649855ba0947386aaed822e7e` |
| `data/inspect_csv.py` | `9110fe20bd5f665bb764fca46ee90111501d02283e17b5683a7f8821bc77b300` |
| `data/check_proposal.py` | `4f234505c09ca417014be97f29bae18bba18b9daf404ab411084409ff5bc983f` |
| `data/check_early.py` | `d7105064e977a2b537c78f4de4797fe383330813736bc8a9553304738b955341` |
| `data/generate_summary_table.py` | `5073ee3c778a71e72fc337baebb6b43d0cbda9e90b731454d182c9266331a2f3` |

Execution completed with `rows 890` (10 symbols × 89 months from 2017-08 to 2024-12).

---

## 1. Summary table

A **clean** month is defined by the task specification as:
- All three intervals (`1m`, `1h`, `1d`) have `status == "ok"`
- All three intervals have `missing_rows == 0` and `gaps == 0`
- Hourly cross-check against 1m aggregation (`cross_check`) has `hours_mismatched == 0`, `hours_missing == 0`, `hours_absent_from_minutes == 0`, and `hours_incomplete == 0`.

| Pair | First file month | First clean month | Clean months | Longest clean run | Months not clean (from 1st clean) | Available months (from 1st file) |
| --- | --- | --- | --- | --- | --- | --- |
| **BTCUSDT** | 2017-08 | 2018-04 | 54 | 21 | 27 | 89 |
| **ETHUSDT** | 2017-08 | 2018-04 | 54 | 21 | 27 | 89 |
| **BNBUSDT** | 2017-11 | 2018-04 | 50 | 21 | 31 | 86 |
| **SOLUSDT** | 2020-08 | 2021-01 | 37 | 21 | 11 | 53 |
| **XRPUSDT** | 2018-05 | 2018-12 | 52 | 21 | 21 | 80 |
| **ADAUSDT** | 2018-04 | 2018-05 | 44 | 21 | 36 | 81 |
| **DOGEUSDT** | 2019-07 | 2021-01 | 38 | 21 | 10 | 66 |
| **LTCUSDT** | 2017-12 | 2018-04 | 47 | 21 | 34 | 85 |
| **LINKUSDT** | 2019-01 | 2020-08 | 38 | 15 | 15 | 72 |
| **TRXUSDT** | 2018-06 | 2018-08 | 47 | 21 | 30 | 79 |

*Note on Longest Clean Run:* For 9 of the 10 pairs, the longest consecutive clean run is exactly **21 months**, spanning **2023-04 to 2024-12** (inclusive). For LINKUSDT, due to single hourly mismatches in 2023-08 and 2023-09, its longest clean run is **15 months** (2023-10 to 2024-12).

---

## 2. Unclean months per pair (from first clean month to 2024-12)

### BTCUSDT (27 unclean months after 2018-04)
- **Parser boundary errors (1m & 1h rejected):**
  - `2018-07`: `1m error: line 4343: open/close time is not a 1m boundary; 1h error: line 73: open/close time is not a 1h boundary`
  - `2019-06`: `1m error: line 9914: open/close time is not a 1m boundary; 1h error: line 166: open/close time is not a 1h boundary`
  - `2020-02`: `1m error: line 26556: open/close time is not a 1m boundary; 1h error: line 443: open/close time is not a 1h boundary`
  - `2020-03`: `1m error: line 4882: open/close time is not a 1m boundary; 1h error: line 82: open/close time is not a 1h boundary`
  - `2020-12`: `1m error: line 29650: open/close time is not a 1m boundary; 1h error: line 495: open/close time is not a 1h boundary`
  - `2021-02`: `1m error: line 14621: open/close time is not a 1m boundary; 1h error: line 244: open/close time is not a 1h boundary`
  - `2021-04`: `1m error: line 34651: open/close time is not a 1m boundary; 1h error: line 579: open/close time is not a 1h boundary`
  - `2021-08`: `1m error: line 17400: open/close time is not a 1m boundary; 1h error: line 290: open/close time is not a 1h boundary`
  - `2021-12`: `1m error: line 33420: open/close time is not a 1m boundary; 1h error: line 557: open/close time is not a 1h boundary`
  - `2023-03`: `1m error: line 33880: open/close time is not a 1m boundary; 1h error: line 565: open/close time is not a 1h boundary`
- **Exchange outages / internal data gaps:**
  - `2018-06`: `1m missing_rows=705 (gaps=2: after 2018-06-26T01:59: 600 bars; after 2018-06-27T12:59: 105 bars); 1h missing_rows=11; cross_check hours_mismatched=1, hours_incomplete=1`
  - `2018-10`: `1m missing_rows=210 (after 2018-10-19T05:59: 210 bars); 1h missing_rows=3; cross_check hours_incomplete=1`
  - `2018-11`: `1m missing_rows=420 (after 2018-11-14T01:59: 420 bars); 1h missing_rows=7`
  - `2019-03`: `1m missing_rows=360 (after 2019-03-12T01:59: 360 bars); 1h missing_rows=6`
  - `2019-05`: `1m missing_rows=600 (after 2019-05-15T02:59: 600 bars); 1h missing_rows=10`
  - `2019-08`: `1m missing_rows=480 (after 2019-08-15T01:59: 480 bars); 1h missing_rows=8`
  - `2019-11`: `1m missing_rows=263 (gaps=3: after 2019-11-13T01:59: 140 bars; after 2019-11-13T05:29: 3 bars; after 2019-11-25T01:59: 120 bars); 1h missing_rows=4; cross_check hours_incomplete=2`
  - `2020-04`: `1m missing_rows=150 (after 2020-04-25T01:59: 150 bars); 1h missing_rows=2; cross_check hours_mismatched=1, hours_incomplete=1`
  - `2020-06`: `1m missing_rows=210 (after 2020-06-28T01:59: 210 bars); 1h missing_rows=3; cross_check hours_incomplete=1`
  - `2020-11`: `1m missing_rows=60 (after 2020-11-30T05:59: 60 bars); 1h missing_rows=1`
  - `2021-03`: `1m missing_rows=90 (after 2021-03-06T01:59: 90 bars); 1h missing_rows=1; cross_check hours_incomplete=1`
  - `2021-09`: `1m missing_rows=120 (after 2021-09-29T06:59: 120 bars); 1h missing_rows=2`
- **Hourly cross-check mismatches only:**
  - `2018-05`, `2018-09`, `2021-10`: `cross_check hours_mismatched=1`
  - `2022-02`, `2022-04`: `cross_check hours_mismatched=2`

### ETHUSDT (27 unclean months after 2018-04)
- **Parser boundary errors:** identical 10 months as BTC (`2018-07`, `2019-06`, `2020-02`, `2020-03`, `2020-12`, `2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** identical 12 months and identical gap timestamps/durations as BTC (`2018-06`, `2018-10`, `2018-11`, `2019-03`, `2019-05`, `2019-08`, `2019-11`, `2020-04`, `2020-06`, `2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2018-05`, `2018-09`, `2021-10`, `2022-02`: `cross_check hours_mismatched=1`
  - `2022-04`: `cross_check hours_mismatched=2`

### BNBUSDT (31 unclean months after 2018-04)
- **Parser boundary errors:** identical 10 months as BTC (`2018-07`, `2019-06`, `2020-02`, `2020-03`, `2020-12`, `2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** identical 12 months as BTC (`2018-06`, `2018-10`, `2018-11`, `2019-03`, `2019-05`, `2019-08`, `2019-11`, `2020-04`, `2020-06`, `2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2018-05`, `2018-08`, `2019-09`, `2021-10`: `cross_check hours_mismatched=1`
  - `2018-09`: `cross_check hours_mismatched=3`
  - `2018-12`: `cross_check hours_mismatched=5`
  - `2019-01`: `cross_check hours_mismatched=4`
  - `2022-02`, `2022-04`: `cross_check hours_mismatched=2`

### SOLUSDT (11 unclean months after 2021-01)
- **Parser boundary errors:** 5 months (`2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:**
  - `2021-03`: `1m missing_rows=90; 1h missing_rows=1; cross_check hours_incomplete=1`
  - `2021-09`: `1m missing_rows=120; 1h missing_rows=2`
  - `2023-02`: `1m missing_rows=1 (after 2023-02-14T16:38: 1 bar); cross_check hours_mismatched=1, hours_incomplete=1`
- **Hourly cross-check mismatches only:**
  - `2021-10`: `cross_check hours_mismatched=1`
  - `2022-02`, `2022-04`: `cross_check hours_mismatched=2`

### XRPUSDT (21 unclean months after 2018-12)
- **Parser boundary errors:** 8 months (`2019-06`, `2020-02`, `2020-03`, `2020-12`, `2021-02`, `2021-04`, `2021-08`, `2023-03`). Note: `2021-12` was clean on XRP!
- **Exchange outages / gaps:** 9 months (`2019-03`, `2019-05`, `2019-08`, `2019-11`, `2020-04`, `2020-06`, `2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2019-12`: `cross_check hours_mismatched=10`
  - `2021-12`, `2022-02`: `cross_check hours_mismatched=2`
  - `2022-04`: `cross_check hours_mismatched=3`

### ADAUSDT (36 unclean months after 2018-05)
- **Parser boundary errors:** 10 months (`2018-07`, `2019-06`, `2020-02`, `2020-03`, `2020-12`, `2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** 12 months (`2018-06`, `2018-10`, `2018-11`, `2019-03`, `2019-05`, `2019-08`, `2019-11`, `2020-04`, `2020-06`, `2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2018-09`, `2021-10`, `2022-02`: `cross_check hours_mismatched=1`
  - `2018-12`: `cross_check hours_mismatched=5`
  - `2019-01`: `cross_check hours_mismatched=11`
  - `2019-02`, `2019-04`: `cross_check hours_mismatched=8`
  - `2019-07`: `cross_check hours_mismatched=21`
  - `2019-09`: `cross_check hours_mismatched=27`
  - `2019-10`: `cross_check hours_mismatched=18`
  - `2019-12`: `cross_check hours_mismatched=66`
  - `2020-01`: `cross_check hours_mismatched=22`
  - `2020-05`: `cross_check hours_mismatched=2`
  - `2022-04`: `cross_check hours_mismatched=3`

### DOGEUSDT (10 unclean months after 2021-01)
- **Parser boundary errors:** 5 months (`2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** 2 months (`2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2021-10`, `2022-02`, `2022-04`: `cross_check hours_mismatched=1`

### LTCUSDT (34 unclean months after 2018-04)
- **Parser boundary errors:** 10 months (`2018-07`, `2019-06`, `2020-02`, `2020-03`, `2020-12`, `2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** 12 months (`2018-06`, `2018-10`, `2018-11`, `2019-03`, `2019-05`, `2019-08`, `2019-11`, `2020-04`, `2020-06`, `2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2018-05`, `2019-04`, `2019-09`, `2020-10`, `2021-10`: `cross_check hours_mismatched=1`
  - `2018-09`, `2019-01`, `2020-09`, `2022-02`: `cross_check hours_mismatched=2`
  - `2019-02`, `2020-01`: `cross_check hours_mismatched=4`
  - `2019-12`: `cross_check hours_mismatched=15`

### LINKUSDT (15 unclean months after 2020-08)
- **Parser boundary errors:** 6 months (`2020-12`, `2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** 3 months (`2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2021-10`, `2022-04`, `2023-02`, `2023-08`, `2023-09`: `cross_check hours_mismatched=1`
  - `2022-02`: `cross_check hours_mismatched=2`

### TRXUSDT (30 unclean months after 2018-08)
- **Parser boundary errors:** 9 months (`2019-06`, `2020-02`, `2020-03`, `2020-12`, `2021-02`, `2021-04`, `2021-08`, `2021-12`, `2023-03`).
- **Exchange outages / gaps:** 11 months (`2018-10`, `2018-11`, `2019-03`, `2019-05`, `2019-08`, `2019-11`, `2020-04`, `2020-06`, `2020-11`, `2021-03`, `2021-09`).
- **Hourly cross-check mismatches only:**
  - `2018-09`, `2020-07`, `2021-10`: `cross_check hours_mismatched=1`
  - `2019-02`: `cross_check hours_mismatched=5`
  - `2019-04`, `2022-04`: `cross_check hours_mismatched=3`
  - `2019-12`: `cross_check hours_mismatched=7`
  - `2020-01`: `cross_check hours_mismatched=4`
  - `2020-05`, `2022-02`: `cross_check hours_mismatched=2`

---

## 3. Error analysis and CSV inspection

Every single error encountered during ingestion was of the form:
`line <N>: open/close time is not a <1m/1h> boundary`.
There were **no checksum errors, HTTP download failures, or corrupt archive files**.

### Error inventory table

| Month | Interval | Line | Error message | Affected pairs |
| --- | --- | --- | --- | --- |
| **2017-09** | 1m | 8160 | `open/close time is not a 1m boundary` | 2 pairs (BTCUSDT, ETHUSDT) |
| **2017-09** | 1h | 136 | `open/close time is not a 1h boundary` | 2 pairs (BTCUSDT, ETHUSDT) |
| **2017-12** | 1m | 4681 | `open/close time is not a 1m boundary` | 3 pairs (BTCUSDT, ETHUSDT, BNBUSDT) |
| **2017-12** | 1m | 7589 | `open/close time is not a 1m boundary` | 1 pair (LTCUSDT) |
| **2017-12** | 1h | 421 | `open/close time is not a 1h boundary` | 3 pairs (BTCUSDT, ETHUSDT, BNBUSDT) |
| **2017-12** | 1h | 130 | `open/close time is not a 1h boundary` | 1 pair (LTCUSDT) |
| **2018-01** | 1m | 4501 | `open/close time is not a 1m boundary` | 4 pairs (BTCUSDT, ETHUSDT, BNBUSDT, LTCUSDT) |
| **2018-01** | 1h | 76 | `open/close time is not a 1h boundary` | 4 pairs (BTCUSDT, ETHUSDT, BNBUSDT, LTCUSDT) |
| **2018-02** | 1m | 10109 | `open/close time is not a 1m boundary` | 4 pairs (BTCUSDT, ETHUSDT, BNBUSDT, LTCUSDT) |
| **2018-02** | 1h | 169 | `open/close time is not a 1h boundary` | 4 pairs (BTCUSDT, ETHUSDT, BNBUSDT, LTCUSDT) |
| **2018-07** | 1m | 4343 | `open/close time is not a 1m boundary` | 7 pairs (BTC, ETH, BNB, XRP, ADA, LTC, TRX) |
| **2018-07** | 1h | 73 | `open/close time is not a 1h boundary` | 7 pairs (BTC, ETH, BNB, XRP, ADA, LTC, TRX) |
| **2019-06** | 1m | 9914 | `open/close time is not a 1m boundary` | 8 pairs (BTC, ETH, BNB, XRP, ADA, LTC, LINK, TRX) |
| **2019-06** | 1h | 166 | `open/close time is not a 1h boundary` | 8 pairs (BTC, ETH, BNB, XRP, ADA, LTC, LINK, TRX) |
| **2020-02** | 1m | 26556 | `open/close time is not a 1m boundary` | 9 pairs (all except SOL) |
| **2020-02** | 1h | 443 | `open/close time is not a 1h boundary` | 9 pairs (all except SOL) |
| **2020-03** | 1m | 4882 | `open/close time is not a 1m boundary` | 9 pairs (all except SOL) |
| **2020-03** | 1h | 82 | `open/close time is not a 1h boundary` | 9 pairs (all except SOL) |
| **2020-12** | 1m | 29650 / 29649 | `open/close time is not a 1m boundary` | 10 pairs (all pairs) |
| **2020-12** | 1h | 495 | `open/close time is not a 1h boundary` | 10 pairs (all pairs) |
| **2021-02** | 1m | 14621 | `open/close time is not a 1m boundary` | 10 pairs (all pairs) |
| **2021-02** | 1h | 244 | `open/close time is not a 1h boundary` | 10 pairs (all pairs) |
| **2021-04** | 1m | 34651 / 34652 | `open/close time is not a 1m boundary` | 10 pairs (all pairs) |
| **2021-04** | 1h | 579 | `open/close time is not a 1h boundary` | 10 pairs (all pairs) |
| **2021-08** | 1m | 17400 | `open/close time is not a 1m boundary` | 10 pairs (all pairs) |
| **2021-08** | 1h | 290 | `open/close time is not a 1h boundary` | 10 pairs (all pairs) |
| **2021-12** | 1m | 33420 | `open/close time is not a 1m boundary` | 9 pairs (all except XRP) |
| **2021-12** | 1h | 557 | `open/close time is not a 1h boundary` | 9 pairs (all except XRP) |
| **2023-03** | 1m | 33880 | `open/close time is not a 1m boundary` | 10 pairs (all pairs) |
| **2023-03** | 1h | 565 | `open/close time is not a 1h boundary` | 10 pairs (all pairs) |

### Offending CSV inspection

Inspection of raw CSV files inside the archives (`data/inspect_csv.py`) reveals the root cause:

1. **BTCUSDT 1m 2017-09 around line 8160:**
   - **Line 8159:** `1504713480000,4619.47000000,4619.47000000,4619.47000000,4619.47000000,0.48351100,1504713539999,2233.56455917,1,0.48351100,2233.56455917,11151.34947496`
     - Open: `1504713480000` (2017-09-06 15:58:00 UTC), Close: `1504713539999` (15:58:59.999 UTC) — **valid 1m candle**.
   - **Line 8160 (offending):** `1504713540000,4603.74000000,4619.43000000,4603.74000000,4619.43000000,0.27733300,1504713600000,1277.13769335,2,0.02349700,108.54274671,11146.71897399`
     - Open: `1504713540000` (2017-09-06 15:59:00 UTC), Close: `1504713600000` (15:60:00.000 UTC).
     - **Defect:** Binance published the close time as `...600000` (+60,000 ms) instead of `...599999` (+59,999 ms). The parser checks `close_ms == open_ms + step - 1` and therefore rejects it.
   - **Line 8161:** `1504738800000,4619.43000000,4619.64000000,4619.43000000,4619.64000000,2.22691100,1504738859999,10287.31182534,3,2.22691100,10287.31182534,11211.97366827`
     - Open: `1504738800000` (2017-09-06 23:00:00 UTC) — an exchange maintenance gap occurred immediately following line 8160.

2. **BTCUSDT 1m 2023-03 around line 33880:**
   - **Line 33879:** `1679661480000,28080.00000000,28080.00000000,28080.00000000,28080.00000000,0.00000000,1679661539999,0.00000000,0,0.00000000,0.00000000,0` (Open 12:38:00 UTC, Close 12:38:59.999 UTC).
   - **Line 33880 (offending):** `1679661540000,28080.00000000,28080.00000000,28080.00000000,28080.00000000,0.00000000,1679661581646,0.00000000,0,0.00000000,0.00000000,0`
     - Open: `1679661540000` (12:39:00 UTC), Close: `1679661581646` (12:39:41.646 UTC).
     - **Defect:** Binance cut off the candle mid-minute at 41.646s when spot trading was suspended on 2023-03-24 due to an engine bug before maintenance.

---

## 4. Daily data analysis (`1d` ok while `1m` or `1h` not ok)

There are **106 symbol-months** where `1d` is completely `ok` (and has 0 missing rows / gaps), but `1m` and `1h` failed with parser boundary errors.
Because daily bars are computed daily without fractional-second boundary anomalies at exchange pause events:
- **2017-09:** 2 pairs (BTC, ETH)
- **2017-12:** 4 pairs (BTC, ETH, BNB, LTC)
- **2018-01:** 4 pairs (BTC, ETH, BNB, LTC)
- **2018-02:** 4 pairs (BTC, ETH, BNB, LTC)
- **2018-07:** 7 pairs (BTC, ETH, BNB, XRP, ADA, LTC, TRX)
- **2019-06:** 8 pairs (BTC, ETH, BNB, XRP, ADA, LTC, LINK, TRX)
- **2020-02:** 9 pairs (all except SOL)
- **2020-03:** 9 pairs (all except SOL)
- **2020-12:** 10 pairs (all pairs)
- **2021-02:** 10 pairs (all pairs)
- **2021-04:** 10 pairs (all pairs)
- **2021-08:** 10 pairs (all pairs)
- **2021-12:** 9 pairs (all except XRP)
- **2023-03:** 10 pairs (all pairs)

---

## 5. Comparison with data-reuse proposal estimates

Proposal estimates from PR #33 (`docs/reviews/2026-09-25-claude-data-reuse-proposal.md`):

| Pair | Proposal estimated 1st complete month | Actual 1st available month | Actual 1st clean month | Status / Verdict |
| --- | --- | --- | --- | --- |
| **BTCUSDT** | `2017-09` | `2017-08` (partial, listed Aug 17) | `2018-04` | **Fails:** `2017-09` rejected by parser (close timestamp anomaly). `2017-10`, `2017-11` have hourly mismatches; `2017-12`..`2018-02` rejected by parser; `2018-03` has volume drift/mismatch. |
| **ETHUSDT** | `2017-10` | `2017-08` (partial, listed Aug 17) | `2018-04` | **Fails:** `2017-10` has 103 cross-check hourly mismatches against Binance's 1h archive. |
| **ADAUSDT** | `2018-05` | `2018-04` (partial, listed mid-Apr) | `2018-05` | **Holds:** `2018-05` is completely clean across 1m, 1h, 1d with 0 mismatches. |
| **XRPUSDT** | `2018-06` | `2018-05` (partial, listed May 4) | `2018-12` | **Fails:** `2018-06` contains Binance maintenance outages on June 26 & 27 (705 missing 1m bars, 11 missing 1h bars, 3 hourly mismatches). First clean month is `2018-12`. |

---

## 6. Ideas and proposals

1. **Handling boundary timestamp anomalies at maintenance cutoffs (Parser Enhancement):**
   - *Observation:* 14 distinct months across all pairs fail parsing solely because the final candle before an unscheduled maintenance window has a close timestamp ending in `000` (e.g. 2017-09) or a truncated millisecond (e.g. 2023-03).
   - *Why it helps:* If the parser permitted the last bar preceding an internal gap to have a truncated close timestamp (or if close timestamp validation was normalized `close_ms <= open_ms + step - 1`), 106 pair-months could be parsed and utilized. *[Correction at review: the `<=` rule would still reject the 2017-09 row quoted above, whose close is one millisecond past the boundary; only truncated rows would pass. The 106 is therefore unsupported. How many rows are of each kind is measured by the task `docs/tasks/2026-09-26-bob-parser-anomaly-classes.md`.]*
   - *How to test:* Write a test fixture in `tests/test_klines.py` using lines 8159-8161 from `BTCUSDT-1m-2017-09.csv` and verify that gap detection correctly flags the gap while preserving all valid preceding and succeeding bars.
2. **Daily indicator warm-up from 2017-08:**
   - *Observation:* While 1m klines for 2017-09 to 2018-02 are rejected by the strict parser, `1d` klines are completely intact, gapless, and valid from 2017-09 onwards.
   - *Why it helps:* Indicator warm-up (e.g., SMA50 / SMA200 for market regimes and filters) requires 200 daily bars. Using `1d` archives allows warm-up to begin as early as 2017-08/09, enabling walk-forward trading windows to start in 2018 without requiring full 1m resolution during the warm-up phase.
   - *How to test:* Verify `dataset.py` load routines to allow separate loading of `1d` history for warm-up before the fold's 1m replay window. *[Correction at review: this already exists as prerequisite P3, `daily_warmup_start` in both dataset specs.]*
3. **Walk-forward fold alignment with clean spans:**
   - *Observation:* The historical data exhibits a clean, unbroken 21-month span from `2023-04` to `2024-12` across 9 pairs *[Correction at review: the original "and continuous clean blocks throughout 2022" is removed; 2022-02 and 2022-04 are not clean for any of the ten pairs, per section 2.]*
   - *Why it helps:* Walk-forward fold design in Spec v1 can align test windows with known clean stretches or account for known exchange maintenance pauses (e.g., 2018-11, 2019-05, 2020-04) using the existing gap-handling semantics.
   - *How to test:* Cross-reference proposed walk-forward window boundaries against `data/inventory.json` clean month sets before freezing fold definitions.

---

## Self-check validation evidence

1. `rows 890` was output and recorded by `data/inventory.py` run on all 10 symbols across 89 months (2017-08..2024-12).
2. All cited scripts exist in `data/` and hashes were computed via `sha256sum`.
3. Checked `git status --porcelain --untracked-files=all`: only `docs/reviews/2026-09-25-bob-dev-data-inventory.md` will be untracked in git.
