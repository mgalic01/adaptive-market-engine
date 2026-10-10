# Bob: full-range-2017-2024 and full-range-2019-2024 fetch

Index: RESULT 2 problem(s) — verify invalid on both windows (BTCUSDT/ETHUSDT daily_days_mismatched=1, XRPUSDT tick_limit_quotes=545 and daily_days_mismatched=1); manifests and digest written; no manifest committed; Claude must investigate and act.

- **Task:** docs/tasks/2026-10-07-bob-full-range-2017-2024-fetch.md
- **Report:** docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md
- **Commit:** 394fa8160715d7053fce5feb38fb2a3864de3966
- **Python:** 3.12.14
- **Clock at start:** Wed Oct 07 10:14:07 UTC 2026

## Steps 1 to 3

**Step 1**

```text
Wed Oct 07 10:14:07 UTC 2026
394fa8160715d7053fce5feb38fb2a3864de3966
Python 3.12.14
data ready
```

**Step 2**

Tree hash:
```text
96de9766551d478883f3451bcaae261f165fd3d4
```

Git status (empty — no local changes under src):
```text

```

Pin count and results:
```text
6 pins
scripts/fetch_full_range.py: OK
tests/test_fetch_full_range.py: OK
config/datasets/full-range-2017-2024.toml: OK
config/datasets/full-range-2019-2024.toml: OK
config/datasets/long-bull-bear-2022.manifest.json: OK
config/default.toml: OK
```

**Step 3**

```text
27 passed in 23.35s
```

## Steps 4 and 5

**Step 4**

```text
python scripts/fetch_full_range.py start data/full-range
STARTED pid 2484; log data/full-range/run.log; exit file data/full-range/run.exit
```

Wait 1: `RUNNING pid 2484; latest: FUNDING 60 of 60 months ok; records 5481`
Wait 2: `RUNNING pid 2484; latest: MANIFEST full-range-2017-2024 ... sha256 069024759d...`
Wait 3: `RUNNING pid 2484; latest: VERIFY full-range-2017-2024 failure: XRPUSDT: daily_days_mismatched=1`
Wait 4 (final):
```text
DONE exit=1
REQUESTS 3613 to data.binance.vision, 2364 of them .CHECKSUM; latest month 2024-12; after 2024-12: 0
REPORT run log 16575 bytes before this line and digest 125659 bytes: 142234 bytes; the report takes them as text (limit 190000)
PROBLEM verify of full-range-2017-2024 is invalid (exit 2)
PROBLEM verify of full-range-2019-2024 is invalid (exit 2)
RESULT 2 problem(s)
```

`start` ran once. 4 waits total. Run was not lost (no `GONE`).

**Step 5**

```text
sha256sum data/full-range-tests.log data/full-range/run*.log data/full-range/run.exit data/full-range/*.toml data/full-range/*.json data/full-range/*.txt
6e4e307c520e67bfe6fd64cb1cb70f80f3d5783ec3f5c44a487eda3633b80c5e  data/full-range-tests.log
346b4ded0e025ec9d7c29c4a1fe2d09e47984ddaf885847123f5c72696b4e2ff  data/full-range/run.log
4355a46b19d348dc2f57c046f8ef63d4538ebb936000f3c9ee954a27460dd865  data/full-range/run.exit
f4216524de089988a15fbddd72a9625a737f41be5a8dcb4bed6a36ccf8e0addb  data/full-range/full-range-2017-2024.toml
8dad70041f4423706b0eeba272595fb24af74cb83713b6316abb68e5a40dafcb  data/full-range/full-range-2019-2024.toml
069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e  data/full-range/full-range-2017-2024.manifest.json
161c5f8d7342e90b94b9a50b13a6e299b3c01e476754e16739ce14bd5bdf2fcd  data/full-range/full-range-2017-2024.mask-report.json
9ff49bf79f59c9818e5f671790a9b9d157b6a52ff59670f5eb0bf4eeb8629c2e  data/full-range/full-range-2017-2024.verify.json
40fa4da932b661e846d2cdf19ee3ae099bd9b1ec1f5ab13a3069dd82a4f223dc  data/full-range/full-range-2019-2024.manifest.json
0f072175bb198a7024ecaa660e456e07f13403d3650e1f69ad9f12663e1de1b7  data/full-range/full-range-2019-2024.verify.json
d10331a68985b3daa678debbc666d55fe04f13bc5be5fbf15f2e337e879b89ef  data/full-range/full-range-2017-2024.digest.txt
3b09d79b47b023c871d78cd58a373f97f7143b18392b1745f1b2f32e6a5a8b02  data/full-range/requests.txt
```

```text
python scripts/fetch_full_range.py measure data/full-range data
SIZE 16841 data/full-range/run.log
SIZE 125659 data/full-range/full-range-2017-2024.digest.txt
RESERVED-WINDOW FILES 0
```

## Run log

```text
PLAN full-range-2017-2024: 1164 kline files (1m 216, 1h 711, 1d 237) and 60 BTCUSDT funding months 2020-01..2024-12; spec config/datasets/full-range-2017-2024.toml sha256 f4216524de089988a15fbddd72a9625a737f41be5a8dcb4bed6a36ccf8e0addb
PLAN full-range-2019-2024: 1080 kline files (1m 198, 1h 648, 1d 234), all in full-range-2017-2024's, and the same funding months; spec config/datasets/full-range-2019-2024.toml sha256 8dad70041f4423706b0eeba272595fb24af74cb83713b6316abb68e5a40dafcb
PLAN latest month 2024-12; 2448 planned paths; data dir data/full-range
FILTERS config/datasets/long-bull-bear-2022.manifest.json sha256 349ce104be44d28d918b22dc99dd611f56d174011b50cb144393a97940c72374: BTCUSDT, ETHUSDT, XRPUSDT, fetched_at 2026-09-30T21:34:57+00:00
FUNDING 60 of 60 months ok; records 5481
KLINES full-range-2017-2024: 1164 files; missing 46, ok 1118; complete months 906
MANIFEST full-range-2017-2024 data/full-range/full-range-2017-2024.manifest.json files 1224 created_at 2026-10-07T10:31:33+00:00 sha256 069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e
COMPARE full-range-2019-2024: 1140 files; every entry equals full-range-2017-2024's: True
KLINES full-range-2019-2024: 1080 files; missing 25, ok 1055; complete months 876
MANIFEST full-range-2019-2024 data/full-range/full-range-2019-2024.manifest.json files 1140 created_at 2026-10-07T10:38:31+00:00 sha256 40fa4da932b661e846d2cdf19ee3ae099bd9b1ec1f5ab13a3069dd82a4f223dc
DIGEST data/full-range/full-range-2017-2024.digest.txt lines 1227 bytes 125659 sha256 d10331a68985b3daa678debbc666d55fe04f13bc5be5fbf15f2e337e879b89ef; rebuilds both manifests byte for byte: True
VERIFY full-range-2017-2024 exit 2 status invalid; failures 4; included pairs 3 of 3: BTCUSDT, ETHUSDT, XRPUSDT; output data/full-range/full-range-2017-2024.verify.json sha256 9ff49bf79f59c9818e5f671790a9b9d157b6a52ff59670f5eb0bf4eeb8629c2e
VERIFY full-range-2017-2024 failure: XRPUSDT: tick_limit_quotes=545
VERIFY full-range-2017-2024 failure: BTCUSDT: daily_days_mismatched=1
VERIFY full-range-2017-2024 failure: ETHUSDT: daily_days_mismatched=1
VERIFY full-range-2017-2024 failure: XRPUSDT: daily_days_mismatched=1
MASK report data/full-range/full-range-2017-2024.mask-report.json sha256 161c5f8d7342e90b94b9a50b13a6e299b3c01e476754e16739ce14bd5bdf2fcd
MASK totals symbols_with_a_mask=9 repaired_hours=81 dropped_hours=0 masked_hours=789 excluded_months=0
MASK XRPUSDT quote test: maximum_spread_pct=0.15 widest_spread_pct=0.1972386587771203155818540434 tick_limit_quotes=545 breaches=True
MASK symbol-months with a masked hour or an exclusion: 181
MASK BTCUSDT 2018-06 masked 11/720 open-only 0 share 11/720 excluded False
MASK BTCUSDT 2018-07 masked 8/744 open-only 0 share 1/93 excluded False
MASK BTCUSDT 2018-10 masked 3/744 open-only 0 share 1/248 excluded False
MASK BTCUSDT 2018-11 masked 7/720 open-only 0 share 7/720 excluded False
MASK BTCUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK BTCUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK BTCUSDT 2019-06 masked 2/720 open-only 0 share 1/360 excluded False
MASK BTCUSDT 2019-08 masked 8/744 open-only 0 share 1/93 excluded False
MASK BTCUSDT 2019-11 masked 6/720 open-only 0 share 1/120 excluded False
MASK BTCUSDT 2020-02 masked 8/696 open-only 0 share 1/87 excluded False
MASK BTCUSDT 2020-03 masked 3/744 open-only 0 share 1/248 excluded False
MASK BTCUSDT 2020-04 masked 4/720 open-only 0 share 1/180 excluded False
MASK BTCUSDT 2020-06 masked 4/720 open-only 0 share 1/180 excluded False
MASK BTCUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK BTCUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK BTCUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK BTCUSDT 2021-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK BTCUSDT 2021-04 masked 12/720 open-only 0 share 1/60 excluded False
MASK BTCUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK BTCUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK BTCUSDT 2021-10 masked 1/744 open-only 0 share 1/744 excluded False
MASK BTCUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK BTCUSDT 2022-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK BTCUSDT 2022-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK BTCUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK ETHUSDT 2018-06 masked 11/720 open-only 0 share 11/720 excluded False
MASK ETHUSDT 2018-07 masked 8/744 open-only 0 share 1/93 excluded False
MASK ETHUSDT 2018-10 masked 3/744 open-only 0 share 1/248 excluded False
MASK ETHUSDT 2018-11 masked 7/720 open-only 0 share 7/720 excluded False
MASK ETHUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK ETHUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK ETHUSDT 2019-06 masked 2/720 open-only 0 share 1/360 excluded False
MASK ETHUSDT 2019-08 masked 9/744 open-only 0 share 3/248 excluded False
MASK ETHUSDT 2019-11 masked 6/720 open-only 0 share 1/120 excluded False
MASK ETHUSDT 2020-02 masked 8/696 open-only 0 share 1/87 excluded False
MASK ETHUSDT 2020-03 masked 3/744 open-only 0 share 1/248 excluded False
MASK ETHUSDT 2020-04 masked 4/720 open-only 0 share 1/180 excluded False
MASK ETHUSDT 2020-06 masked 4/720 open-only 0 share 1/180 excluded False
MASK ETHUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK ETHUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK ETHUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK ETHUSDT 2021-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK ETHUSDT 2021-04 masked 12/720 open-only 0 share 1/60 excluded False
MASK ETHUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK ETHUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK ETHUSDT 2021-10 masked 1/744 open-only 0 share 1/744 excluded False
MASK ETHUSDT 2022-02 masked 1/672 open-only 0 share 1/672 excluded False
MASK ETHUSDT 2022-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK ETHUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK XRPUSDT 2018-06 masked 11/720 open-only 0 share 11/720 excluded False
MASK XRPUSDT 2018-07 masked 8/744 open-only 0 share 1/93 excluded False
MASK XRPUSDT 2018-10 masked 3/744 open-only 0 share 1/248 excluded False
MASK XRPUSDT 2018-11 masked 7/720 open-only 0 share 7/720 excluded False
MASK XRPUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK XRPUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK XRPUSDT 2019-06 masked 2/720 open-only 0 share 1/360 excluded False
MASK XRPUSDT 2019-08 masked 9/744 open-only 0 share 3/248 excluded False
MASK XRPUSDT 2019-11 masked 6/720 open-only 0 share 1/120 excluded False
MASK XRPUSDT 2019-12 masked 10/744 open-only 7 share 1/248 excluded False
MASK XRPUSDT 2020-02 masked 8/696 open-only 0 share 1/87 excluded False
MASK XRPUSDT 2020-03 masked 3/744 open-only 0 share 1/248 excluded False
MASK XRPUSDT 2020-04 masked 3/720 open-only 0 share 1/240 excluded False
MASK XRPUSDT 2020-06 masked 4/720 open-only 0 share 1/180 excluded False
MASK XRPUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK XRPUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK XRPUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK XRPUSDT 2021-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK XRPUSDT 2021-04 masked 12/720 open-only 0 share 1/60 excluded False
MASK XRPUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK XRPUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK XRPUSDT 2021-12 masked 2/744 open-only 0 share 1/372 excluded False
MASK XRPUSDT 2022-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK XRPUSDT 2022-04 masked 3/720 open-only 0 share 1/240 excluded False
MASK XRPUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK BNBUSDT 2018-06 masked 11/720 open-only 0 share 11/720 excluded False
MASK BNBUSDT 2018-07 masked 8/744 open-only 0 share 1/93 excluded False
MASK BNBUSDT 2018-10 masked 3/744 open-only 0 share 1/248 excluded False
MASK BNBUSDT 2018-11 masked 7/720 open-only 0 share 7/720 excluded False
MASK BNBUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK BNBUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK BNBUSDT 2019-06 masked 1/720 open-only 0 share 1/720 excluded False
MASK BNBUSDT 2019-08 masked 8/744 open-only 0 share 1/93 excluded False
MASK BNBUSDT 2019-11 masked 4/720 open-only 0 share 1/180 excluded False
MASK BNBUSDT 2020-02 masked 7/696 open-only 0 share 7/696 excluded False
MASK BNBUSDT 2020-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK BNBUSDT 2020-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK BNBUSDT 2020-06 masked 3/720 open-only 0 share 1/240 excluded False
MASK BNBUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK BNBUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK BNBUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK BNBUSDT 2021-03 masked 1/744 open-only 0 share 1/744 excluded False
MASK BNBUSDT 2021-04 masked 6/720 open-only 0 share 1/120 excluded False
MASK BNBUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK BNBUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK BNBUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK BNBUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK SOLUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK SOLUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK SOLUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK SOLUSDT 2021-03 masked 1/744 open-only 0 share 1/744 excluded False
MASK SOLUSDT 2021-04 masked 6/720 open-only 0 share 1/120 excluded False
MASK SOLUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK SOLUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK SOLUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK SOLUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK DOGEUSDT 2019-08 masked 8/744 open-only 0 share 1/93 excluded False
MASK DOGEUSDT 2019-11 masked 4/720 open-only 0 share 1/180 excluded False
MASK DOGEUSDT 2020-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK DOGEUSDT 2020-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK DOGEUSDT 2020-06 masked 3/720 open-only 0 share 1/240 excluded False
MASK DOGEUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK DOGEUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK DOGEUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK DOGEUSDT 2021-03 masked 1/744 open-only 0 share 1/744 excluded False
MASK DOGEUSDT 2021-04 masked 6/720 open-only 0 share 1/120 excluded False
MASK DOGEUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK DOGEUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK DOGEUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK DOGEUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK LTCUSDT 2018-06 masked 11/720 open-only 0 share 11/720 excluded False
MASK LTCUSDT 2018-07 masked 8/744 open-only 0 share 1/93 excluded False
MASK LTCUSDT 2018-10 masked 3/744 open-only 0 share 1/248 excluded False
MASK LTCUSDT 2018-11 masked 7/720 open-only 0 share 7/720 excluded False
MASK LTCUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK LTCUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK LTCUSDT 2019-06 masked 1/720 open-only 0 share 1/720 excluded False
MASK LTCUSDT 2019-08 masked 8/744 open-only 0 share 1/93 excluded False
MASK LTCUSDT 2019-11 masked 4/720 open-only 0 share 1/180 excluded False
MASK LTCUSDT 2020-02 masked 7/696 open-only 0 share 7/696 excluded False
MASK LTCUSDT 2020-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK LTCUSDT 2020-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK LTCUSDT 2020-06 masked 3/720 open-only 0 share 1/240 excluded False
MASK LTCUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK LTCUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK LTCUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK LTCUSDT 2021-03 masked 1/744 open-only 0 share 1/744 excluded False
MASK LTCUSDT 2021-04 masked 6/720 open-only 0 share 1/120 excluded False
MASK LTCUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK LTCUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK LTCUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK LTCUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK LINKUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK LINKUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK LINKUSDT 2019-06 masked 1/720 open-only 0 share 1/720 excluded False
MASK LINKUSDT 2019-08 masked 8/744 open-only 0 share 1/93 excluded False
MASK LINKUSDT 2019-11 masked 4/720 open-only 0 share 1/180 excluded False
MASK LINKUSDT 2020-02 masked 7/696 open-only 0 share 7/696 excluded False
MASK LINKUSDT 2020-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK LINKUSDT 2020-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK LINKUSDT 2020-06 masked 3/720 open-only 0 share 1/240 excluded False
MASK LINKUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK LINKUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK LINKUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK LINKUSDT 2021-03 masked 1/744 open-only 0 share 1/744 excluded False
MASK LINKUSDT 2021-04 masked 6/720 open-only 0 share 1/120 excluded False
MASK LINKUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK LINKUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK LINKUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK LINKUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK TRXUSDT 2018-06 masked 11/469 open-only 0 share 11/469 excluded False
MASK TRXUSDT 2018-07 masked 8/744 open-only 0 share 1/93 excluded False
MASK TRXUSDT 2018-10 masked 3/744 open-only 0 share 1/248 excluded False
MASK TRXUSDT 2018-11 masked 7/720 open-only 0 share 7/720 excluded False
MASK TRXUSDT 2019-03 masked 6/744 open-only 0 share 1/124 excluded False
MASK TRXUSDT 2019-05 masked 10/744 open-only 0 share 5/372 excluded False
MASK TRXUSDT 2019-06 masked 1/720 open-only 0 share 1/720 excluded False
MASK TRXUSDT 2019-08 masked 8/744 open-only 0 share 1/93 excluded False
MASK TRXUSDT 2019-11 masked 4/720 open-only 0 share 1/180 excluded False
MASK TRXUSDT 2020-02 masked 7/696 open-only 0 share 7/696 excluded False
MASK TRXUSDT 2020-03 masked 2/744 open-only 0 share 1/372 excluded False
MASK TRXUSDT 2020-04 masked 2/720 open-only 0 share 1/360 excluded False
MASK TRXUSDT 2020-06 masked 3/720 open-only 0 share 1/240 excluded False
MASK TRXUSDT 2020-11 masked 1/720 open-only 0 share 1/720 excluded False
MASK TRXUSDT 2020-12 masked 5/744 open-only 0 share 5/744 excluded False
MASK TRXUSDT 2021-02 masked 2/672 open-only 0 share 1/336 excluded False
MASK TRXUSDT 2021-03 masked 1/744 open-only 0 share 1/744 excluded False
MASK TRXUSDT 2021-04 masked 6/720 open-only 0 share 1/120 excluded False
MASK TRXUSDT 2021-08 masked 5/744 open-only 0 share 5/744 excluded False
MASK TRXUSDT 2021-09 masked 2/720 open-only 0 share 1/360 excluded False
MASK TRXUSDT 2021-12 masked 1/744 open-only 0 share 1/744 excluded False
MASK TRXUSDT 2023-03 masked 2/744 open-only 0 share 1/372 excluded False
VERIFY full-range-2019-2024 exit 2 status invalid; failures 4; included pairs 3 of 3: BTCUSDT, ETHUSDT, XRPUSDT; output data/full-range/full-range-2019-2024.verify.json sha256 0f072175bb198a7024ecaa660e456e07f13403d3650e1f69ad9f12663e1de1b7
VERIFY full-range-2019-2024 failure: XRPUSDT: tick_limit_quotes=545
VERIFY full-range-2019-2024 failure: BTCUSDT: daily_days_mismatched=1
VERIFY full-range-2019-2024 failure: ETHUSDT: daily_days_mismatched=1
VERIFY full-range-2019-2024 failure: XRPUSDT: daily_days_mismatched=1
REQUESTS 3613 to data.binance.vision, 2364 of them .CHECKSUM; latest month 2024-12; after 2024-12: 0; list data/full-range/requests.txt sha256 3b09d79b47b023c871d78cd58a373f97f7143b18392b1745f1b2f32e6a5a8b02
REPORT run log 16575 bytes before this line and digest 125659 bytes: 142234 bytes; the report takes them as text (limit 190000)
PROBLEM verify of full-range-2017-2024 is invalid (exit 2)
PROBLEM verify of full-range-2019-2024 is invalid (exit 2)
RESULT 2 problem(s)
```

## Digest

```text
digest of full-range-2017-2024 and full-range-2019-2024, format v1 (scripts/fetch_full_range.py)
manifest full-range-2017-2024 created_at 2026-10-07T10:31:33+00:00 files 1224 sha256 069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e
manifest full-range-2019-2024 created_at 2026-10-07T10:38:31+00:00 files 1140 sha256 40fa4da932b661e846d2cdf19ee3ae099bd9b1ec1f5ab13a3069dd82a4f223dc
BTCUSDT-1m-2019-01.zip 08dd2f7306258d1b9fd0b9fc00ee807c1c96e9803c74c78c00a0072bfc826728 ok 2120781 full
BTCUSDT-1m-2019-02.zip 5ef0c96cb6f7cadb70cdceeb190ac350bf605dcde3930cdb3cc8942dc0ac98bc ok 1915927 full
BTCUSDT-1m-2019-03.zip 30f0b1d9a47950ced20f62045291669f984a55552181769ff3f1df8433a93e09 ok 2089484 rows=44280 gaps=1
BTCUSDT-1m-2019-04.zip 617647d93837bc5a9a4866c089b87b21f9780d479dece0f623e8354be36216fe ok 2090113 full
BTCUSDT-1m-2019-05.zip 7a32f26d7f878332384dc61dde639e49c5007c2b45d6bc360b0bec37817baa08 ok 2198447 rows=44040 gaps=1
BTCUSDT-1m-2019-06.zip 8c7acbfa0d71c87f6ba965e8d62ec83b258b4a3aaab9a8c17f708ece35214a1a ok 2177693 rows=43139 gaps=1
BTCUSDT-1m-2019-07.zip f907354d0d2ce079c828d1654093729b4e571b4e1134159bf8f9a023ba955739 ok 2272709 full
BTCUSDT-1m-2019-08.zip 367c5ece72129de80347c34bbd24e6f5f868711ce66b0a830c6945c4259e7d33 ok 2207879 rows=44160 gaps=1
BTCUSDT-1m-2019-09.zip 6bed8bcf250caedf243cd890cdffd93b6266e7f3007a8bb7e6d13b95a15645f1 ok 2140033 full
BTCUSDT-1m-2019-10.zip 11c16f00ee0a568336fae0929f758416be94e78bd250ea31b60d083d1cb6494b ok 2217849 full
BTCUSDT-1m-2019-11.zip 6a896c7a603a2c8deb12233e53c3f8fbc2676b8c0b7b85fcf53a3b57fad021d7 ok 2133961 rows=42937 gaps=3
BTCUSDT-1m-2019-12.zip bb30eef0f17336dccac395b3ff60df077160548485a3230c6fe62387f48fc79a ok 2197736 full
BTCUSDT-1m-2020-01.zip 02df6da44ed8145fbb9ed819858185d9e2f15eb025c5bec8a4ea2d8738cd0d19 ok 2224194 full
BTCUSDT-1m-2020-02.zip 05aedf91c80f579da396951b1d9e84587d02c9684352e1ff17d4468f556c674e ok 2077466 rows=41346 gaps=2
BTCUSDT-1m-2020-03.zip ee5d21ec0f3c5bdef1da330d8b74d8571779fe757bb7e9f272847d36b95a71a2 ok 2277959 rows=44512 gaps=1
BTCUSDT-1m-2020-04.zip 83e052ee74ede21aa617830c121ce052e5f29b735710fe65159fc594b2028301 ok 2164104 rows=43050 gaps=1
BTCUSDT-1m-2020-05.zip 3a38ca9123ab0c44063561faed5e90c3e716c93ea42c3e67a968be505b677ba0 ok 2265162 full
BTCUSDT-1m-2020-06.zip 4f7a6721f2b9f0a74d66ce7818c73dad002a454e11a5280485e3c123d27f7698 ok 2131275 rows=42990 gaps=1
BTCUSDT-1m-2020-07.zip 003bcab2ea8d5d0268f7f627a117022d4fa4826aa85bdb82bcae98dd4f24f2a2 ok 2203867 full
BTCUSDT-1m-2020-08.zip 661b02c77ad1baac0d649e658dc5fb8434b6acc15560b767301e7981bdbe0c66 ok 2257706 full
BTCUSDT-1m-2020-09.zip a60c06861b59893bb2f06813b7f181cba970b5dac9d38fcf5db8e2c13fbd27f7 ok 2174596 full
BTCUSDT-1m-2020-10.zip d7b0fc63c86b2d54f4391fd4ed69e0fd12497108061ca4006d9f709e653cfe40 ok 2220925 full
BTCUSDT-1m-2020-11.zip 07ff8e3aa21d340a9e25c32644a4cd6c15e4280879d39815159eb5c858895488 ok 2228577 rows=43140 gaps=1
BTCUSDT-1m-2020-12.zip a53a9352fd808d10981f68191138b39ef142e15ca88e03a061309f1699419749 ok 2304125 rows=44350 gaps=2
BTCUSDT-1m-2021-01.zip 9364a063efa0604d5b9d2536fb68f922da5afa3d8f94a26a527471a1e2f87801 ok 2399851 full
BTCUSDT-1m-2021-02.zip 21723e4951ba30037cb8417278b7cf4a38d47c625b1cb5ac97864d539ae6d407 ok 2157176 rows=40241 gaps=1
BTCUSDT-1m-2021-03.zip 54387ec23e27440b220c693b94e97c21dbb3a82d3b7606fd8cfe9f40a69cc85b ok 2375057 rows=44550 gaps=1
BTCUSDT-1m-2021-04.zip 016ea34ee7e52c4783c1e03ec65c710361c1ccf228d3a4c0b44a4d0baa859641 ok 2265385 rows=42766 gaps=2
BTCUSDT-1m-2021-05.zip afed5ec95ede42509edb5ffce2d64c4af0916cac9878df99b8bb15c8e7d1488a ok 2407992 full
BTCUSDT-1m-2021-06.zip 29ff5a78be8701d67376d480041f93957f5d26b3435c9feb48001a77ac973c62 ok 2299606 full
BTCUSDT-1m-2021-07.zip b7befce6203924e3c782ad19859bbe7d4fe38a2bd2d525101235cc6fc6fc10a8 ok 2322442 full
BTCUSDT-1m-2021-08.zip 8e886c3aeb7eb625493e875bfaf181eeb5a316dad424c86d042ad2c73cad563b ok 2309698 rows=44370 gaps=1
BTCUSDT-1m-2021-09.zip 27edb4a4623701ba3c5b3f6d4de1848964abb31188036236827fd28cf9bdb853 ok 2172157 rows=43080 gaps=1
BTCUSDT-1m-2021-10.zip aad7e2fa6d48c33098b61ac5f7dbbbb4d4234222b5a5ebb4e9b1bbced7670f3f ok 2259946 full
BTCUSDT-1m-2021-11.zip cb4cf36e1590663a803b28261189a719fd00bc1d8eef672378df02a934862df2 ok 2183167 full
BTCUSDT-1m-2021-12.zip 2b6c79547da2d87e6735d29fcb2d75f0e15c9cbfcec6396c8d8f20b3632d8e0b ok 2242006 full
BTCUSDT-1m-2022-01.zip ce0e16e834331e70b3041677c7f409818d5904bb59cb7b880695e4cacd34fc09 ok 2229634 full
BTCUSDT-1m-2022-02.zip 748844587c78902e4c35886620197053ee39f3e7104fbdcbfde00fe829bbfd1a ok 2011133 full
BTCUSDT-1m-2022-03.zip f8a05f6657cb7f8ac41c047bae65bff74703f058f56517dca28a817d390b82d3 ok 2207992 full
BTCUSDT-1m-2022-04.zip 6e840c81076ac25e6acdbfe4aaeb7aa8b1895a70d8111a3c2908c5134072f097 ok 2103010 full
BTCUSDT-1m-2022-05.zip 154311f08aa264e233b0c7b472aa490c8cfd1b6083ba86cf6c18134e50536b89 ok 2216492 full
BTCUSDT-1m-2022-06.zip 0ced8899e9c3b2c098e1c5fc4993250bac22d8684d2d38404310351f35e32c0c ok 2158139 full
BTCUSDT-1m-2022-07.zip b7b9100066d75037063d0798b91fab91d62c348a21888ace2363a75a6089e7cc ok 2298791 full
BTCUSDT-1m-2022-08.zip 7517a604803c40cd38b29fb490d7bce83d01e1e4ac9e9ae2bcd52adaea55a291 ok 2318381 full
BTCUSDT-1m-2022-09.zip 72b22ae8bbb91342c672c2915680729ce2e7223d21386de08d4af906e6bb0713 ok 2260540 full
BTCUSDT-1m-2022-10.zip 5c9497d81e565c88256b1b17e86bc7257fc1f4a133ec50109c6a5a9bbd180f3f ok 2300603 full
BTCUSDT-1m-2022-11.zip 7b7463638505f303ea91ababadff27bbb46c6d448428f99288f5faf790250a71 ok 2241831 full
BTCUSDT-1m-2022-12.zip 38f93ad56a5f13491094b0ef965f03cea2d6097cc72b7179489b7d60d5fd446b ok 2261860 full
BTCUSDT-1m-2023-01.zip 664116c2f33465d191684887f0d4834c02eb0a2635ada43eca855a99e6b6b0c5 ok 2304509 full
BTCUSDT-1m-2023-02.zip bff03104aa247f791a12a122336cb8c928e19fea5b74276d83a248878b9a619a ok 2109501 full
BTCUSDT-1m-2023-03.zip 5591171a15f210af647a2fb68ab8cbad45a3a595cfe9a0eec9d06e5e84928bec ok 2300446 rows=44560 gaps=1
BTCUSDT-1m-2023-04.zip c71baedea84f9fc1a0ad297b383505b1cb84c0a7fc111caa149aa6fb2defa5da ok 2064504 full
BTCUSDT-1m-2023-05.zip c83bd079dc67b9e542d07fe9491f8b1bf513185d6d7cc4ce17710f21c8d0037b ok 2111728 full
BTCUSDT-1m-2023-06.zip d8cf5d1817fa1d8cba8eaf4d189614cf05b15d7233e9e29a0156d2dee2cfaad1 ok 2043702 full
BTCUSDT-1m-2023-07.zip 8f32a4ef47bd758b33bfaf680a71792f8d97ca4d89ae55ff3d2272cc3974560c ok 2033186 full
BTCUSDT-1m-2023-08.zip b4d775d24d905660d8ad00bfa1fc0157ec83c4b4f0c4aacca8818dad5d17c6c6 ok 2018512 full
BTCUSDT-1m-2023-09.zip 22333eaa3f971ad0686c02532b7b23d02e5e32c298d9bf4fa55894fbb755da99 ok 1967613 full
BTCUSDT-1m-2023-10.zip 9e854972545806398d124571916348238ce39961072730c200cca3c2e0bd50a3 ok 2099200 full
BTCUSDT-1m-2023-11.zip 4b1462878f31fd736385b761f6bb0a3f525936a6ae9f5f52c3e3b95ee2df35b4 ok 2056098 full
BTCUSDT-1m-2023-12.zip c8b684a66b5ddbb58bf116251359c2dd83a07ce46791f4caa16dd4301eb17636 ok 2144300 full
BTCUSDT-1m-2024-01.zip 40b78258091a468f8756843f207f5913eafc1d6e756c40a78711320d93fa5e75 ok 2169570 full
BTCUSDT-1m-2024-02.zip 431132e0db8b9fe6e5c93c8e9ba3ae37dbcfa0edcdd57618b1b78ac18d14be79 ok 2013843 full
BTCUSDT-1m-2024-03.zip a9af86295eae839f1d072643c67eed7fcc47bb1d82c12ef312d041eec9511e7b ok 2221094 full
BTCUSDT-1m-2024-04.zip 753040cbfaa72bf9b1fdc6253a3b521a9a174a664dfd0929a556be327b016bc6 ok 2120723 full
BTCUSDT-1m-2024-05.zip 0f709143f66a09acc430d24a5f27f9accd52689c23ce10f2c0b6ea26997bfa8a ok 2144250 full
BTCUSDT-1m-2024-06.zip 90f4fc3f55918787848c71f4cd0f2f1a5851bbffaf6392e76e9ab555b7479d2b ok 2018857 full
BTCUSDT-1m-2024-07.zip 9cfd749fd2027a0c6f261bed607b49dd1256369fb41b784934544a3676f8162e ok 2141506 full
BTCUSDT-1m-2024-08.zip 6a1cac2a5482132dc5a030534aa028e2becc560877f2b93b7add90194f576c42 ok 2164472 full
BTCUSDT-1m-2024-09.zip 1e30f6091b05eeb7b0449735d749354b81ab429ab1449bae82a21e316db8eac3 ok 2049758 full
BTCUSDT-1m-2024-10.zip 13f7f9f9bed652fd152422246cfbcaefa6223692c5c37fb3ca4e72f45501e607 ok 2121607 full
BTCUSDT-1m-2024-11.zip c30a63bd0e8a77f2d18a2a019272b907f29a84fd5378796cf9333b041edcb12b ok 2146495 full
BTCUSDT-1m-2024-12.zip 58fef0b7c7abce7a0201efd04ed3732f236f607f3fcecf228fb8384cad1ae2c1 ok 2218893 full
ETHUSDT-1m-2019-01.zip 86e6770246976d2ab0b21a22084bffd3a4c11c7cab9d4cda1dcaf30e1a772cf4 ok 1947120 full
ETHUSDT-1m-2019-02.zip 4b320265d1c632ed6fc174201d20a7fe5112f26c5ddf9aad822d29040c2dc5c4 ok 1751557 full
ETHUSDT-1m-2019-03.zip e8c2e8180a1253b2128adabe6d59e6be1669ba24f2d7c9427b5ef2771eddd94d ok 1894430 rows=44280 gaps=1
ETHUSDT-1m-2019-04.zip edc798b17340883d5b0c779d4077a75cb80f1ce4d22155532ba0e024dc56d1b3 ok 1901529 full
ETHUSDT-1m-2019-05.zip fdb21c1b49a831073898dc060b35ee8a4cb93cdfd901d4ed2fc0439b0bd33dc8 ok 2003954 rows=44040 gaps=1
ETHUSDT-1m-2019-06.zip fe214b966bf8ca7472eeb8a52120a995c6df9119788b0801a1ec10f84ec1b517 ok 1956764 rows=43139 gaps=1
ETHUSDT-1m-2019-07.zip 2e8794d8f1c30c8640617289a3f072d581746ea9e299f623936ac9ab0f0d024b ok 2012878 full
ETHUSDT-1m-2019-08.zip c0e04e35b1e512355708abd81e882ef185c7f1469f290539872de8bb2197b145 ok 1929333 rows=44160 gaps=1
ETHUSDT-1m-2019-09.zip ed943b86487a8a94eda85b2f526ede929dbbd1f41aefe7b8311552aa47827976 ok 1910267 full
ETHUSDT-1m-2019-10.zip e36eadbbde9973e4596f6f5cab7e864bddd6b8bf64e0c98f1949e907877125f1 ok 1980284 full
ETHUSDT-1m-2019-11.zip fcfe68f4c98deb2ec57e191413082f8cad63c9af194d322c16f13589f8a040e5 ok 1876691 rows=42937 gaps=3
ETHUSDT-1m-2019-12.zip b0bdcb05d6a7a210ad53b96cc8a2db844281461880f508afd1cfbacdf759e1cc ok 1897053 full
ETHUSDT-1m-2020-01.zip 48886abc91602bcd38a79ca6af913e294dc2e2ea653bcac419699cb471a56f4c ok 1957705 full
ETHUSDT-1m-2020-02.zip bf55b325926b016c2de79ed5ce5ce066ec72a4d652700be356ded28b3209728e ok 1899967 rows=41346 gaps=2
ETHUSDT-1m-2020-03.zip 4be4045d288edf14305d486ac2f74df763664633a81dee2c9bf856aa4bc57298 ok 2057355 rows=44512 gaps=1
ETHUSDT-1m-2020-04.zip 874ffde63826cca5d991ab7b7a727ae9b4f8fc3696f10b1ddb78c74e56566c85 ok 1962295 rows=43050 gaps=1
ETHUSDT-1m-2020-05.zip ddd7c0679fe93c1c087ff9a5c9a495f84d3d22830d3731f2d38c054e141d3681 ok 2025434 full
ETHUSDT-1m-2020-06.zip 1340d9c29d4a4c660a44336ab0b9c9470faad2a3bdf3bcd1122b0e575088ce38 ok 1916095 rows=42990 gaps=1
ETHUSDT-1m-2020-07.zip f91b6e1f027c421161880af78a37bcfef3923551d1d1c8abe96374a3130b84a9 ok 2006491 full
ETHUSDT-1m-2020-08.zip 3500a8e33232a5c7d7c4d3adaaf65889a0382a11ac78967679052424eade907a ok 2095705 full
ETHUSDT-1m-2020-09.zip 7e7bf162ccf90d74dd0c89c969d86bd2fa6cb4aa99e5d635c0540fbafbc01624 ok 2038016 full
ETHUSDT-1m-2020-10.zip be7d2d73aa9d879b4043ea82e97d37fe78cd404ff94cebb123a50c7ffc9bd090 ok 2041946 full
ETHUSDT-1m-2020-11.zip d886f8e908d9ade6c9f1def4a93267ab5701aba92e873419b9627bf7d9f20352 ok 2053613 rows=43140 gaps=1
ETHUSDT-1m-2020-12.zip 84b8aae21ed5be1c6257c596d7bf4717117cfb4d515febe4dbacd37d7666c7f8 ok 2116324 rows=44349 gaps=2
ETHUSDT-1m-2021-01.zip 19406d35bbc4c5511c1c04265369a3dcd6719ff2195e0bdb0bf5147e937ee857 ok 2250430 full
ETHUSDT-1m-2021-02.zip 964070408500f1e189daf68832abc14d53ee03c53e9971d23aef180f5730543e ok 2014257 rows=40241 gaps=1
ETHUSDT-1m-2021-03.zip a315049701c13cb36884412ae501e4b83582dbead0b9b07db9c8e58578c4b589 ok 2200711 rows=44550 gaps=1
ETHUSDT-1m-2021-04.zip 7a9c6f70708570a7a786afe7451c8fc8cab20e5efb6fcb11aa242521bd19edc9 ok 2141416 rows=42766 gaps=2
ETHUSDT-1m-2021-05.zip 241b0fbc11f80d36f5ed97b4ae2f618180542646a6c11e8c012bfe5bbea7bee8 ok 2307771 full
ETHUSDT-1m-2021-06.zip e9cc31fd36a498c14b668016a6b9a9a11a92dee39583760d8289228f32509143 ok 2167997 full
ETHUSDT-1m-2021-07.zip eef8b511856eb16c728ac76395784b1bdba42fc528e70bc93cf41641e3b4dc90 ok 2205160 full
ETHUSDT-1m-2021-08.zip e6d65e00e8eb757c748c61469268d921f679968e40b9329b04d66ed5392c0073 ok 2197307 rows=44370 gaps=1
ETHUSDT-1m-2021-09.zip 5bbfb9f41522b2fd1472e4f4b164a5ba4711b02aab37eebe0b2b25a1286c90a9 ok 2070369 rows=43080 gaps=1
ETHUSDT-1m-2021-10.zip 734dda1470947fee74e8c48b2a243d7c81acc286fd20cca913ca70429f288107 ok 2134308 full
ETHUSDT-1m-2021-11.zip a91e027bbbace0f12f05782f5f3203206b1674d58d1376ad1ced85f98f07b447 ok 2068447 full
ETHUSDT-1m-2021-12.zip 4afcb0943a7a7e474904bc2f40983abc5155c6c88cd0775f5b5b2977cb69a69f ok 2131175 full
ETHUSDT-1m-2022-01.zip 38386e47208de53dddfcb47490533d19284dd2331099b0679fcf75e7e0eb5b1e ok 2114115 full
ETHUSDT-1m-2022-02.zip 4a316d17bac7b19f6d55e23910479b0354177bead4d6488f5829cb959df85178 ok 1912778 full
ETHUSDT-1m-2022-03.zip 41d2ebb5fc88f090ec38e51b785b6621738dac1ce996de14e0f9945024c02f78 ok 2089094 full
ETHUSDT-1m-2022-04.zip f5eefaafeebe9934811c1ccc46acc93e3de342761dc33349ab6917ade9018e5c ok 2008130 full
ETHUSDT-1m-2022-05.zip 7f3e2df3fc5c365cd678233c27d7a8864855bab0709370ac665d388e5795dfc3 ok 2110136 full
ETHUSDT-1m-2022-06.zip c189abf1f43601f3a389819f93a955ba0d96dab19dee0804dc1c741e26977e8c ok 2056565 full
ETHUSDT-1m-2022-07.zip d536b2ae7c8161736f3f54e6d196ab53c86616e983b6c195ddad02936517e079 ok 2119356 full
ETHUSDT-1m-2022-08.zip 6d5171bf39094bf479c49d7835bd99e4880b497bfcb3ccd655fc9298a7f508d9 ok 2107847 full
ETHUSDT-1m-2022-09.zip 2f608ec0e0072c8ec88dc8df798e101af9937702edd37f3447107faa00c84445 ok 2020746 full
ETHUSDT-1m-2022-10.zip 99648a89a2a713738cf36780f748a6ab9f84737d52fde3728dd59218ac832bc3 ok 2020787 full
ETHUSDT-1m-2022-11.zip 925acf2264f9ffbe1dea1beada4b480eed9bfd7585bebe799a276d7e85ada0df ok 1994209 full
ETHUSDT-1m-2022-12.zip 0a4c1f1a0d983cdf3207737bcff6550e6fa00dd6e0e4abb7a6c686beaca5a58f ok 1955495 full
ETHUSDT-1m-2023-01.zip c69ea0c9b620b53f15dc5e20a1446a2f233e2d8c8dd8eaa8bf49dae92f3162c3 ok 1989184 full
ETHUSDT-1m-2023-02.zip 4ee0c9bf3c53c038798df52b085156f0fae2c59406e3e1c02ade5f680a129a11 ok 1828792 full
ETHUSDT-1m-2023-03.zip e2552c2298f4b67027bfa1f7da364b0d398e96a76dae8fa2085dddf357f60a69 ok 2052232 rows=44560 gaps=1
ETHUSDT-1m-2023-04.zip 87d0e7d1a21d72636f60cdd50557c90cc1921664596f5b4e9713c0365c3410c5 ok 1956086 full
ETHUSDT-1m-2023-05.zip fe57aa54eb3467ec40d04c1585e8019c8fb0fb2085abf28bb8e615ab5461def0 ok 1980623 full
ETHUSDT-1m-2023-06.zip c12d39ce1b3b6a47e09e4b5a1c64d39939b9b58108f2c6f87e39d544cb0430f3 ok 1907373 full
ETHUSDT-1m-2023-07.zip ad0b53a0f9b7ec4dd13c3d9c8a2f93dcbf797ea7ae40c8a109f5a275983869f2 ok 1920823 full
ETHUSDT-1m-2023-08.zip fd3f848b8ee996504745083b8b2a34e5bdf2bd388a8fc7edf426d8dc10bffe7f ok 1884880 full
ETHUSDT-1m-2023-09.zip 7bfed19a472eaa4691d1920c865d07436262e7dc9ad737509db14dc6bcc2429e ok 1840420 full
ETHUSDT-1m-2023-10.zip e7c67fa12dd93c7bebd4a5893852b3b1b0ac3faf30ec2a590fa6c942fabf4e4d ok 1958976 full
ETHUSDT-1m-2023-11.zip b3a5ba98d81b4bc62022d35d85d4e28c6ab7ca550d8283643191f66f6f986c66 ok 1960231 full
ETHUSDT-1m-2023-12.zip 9a0d342828ced43d17a97341234ec9d6344eba9945b5a5dccc73eabb253a83bb ok 2040096 full
ETHUSDT-1m-2024-01.zip 2fb2c9b77365183f77e185de3578de2f3be5fefe433d7c0564f033f968d5e23c ok 2050101 full
ETHUSDT-1m-2024-02.zip ede3c9d4d47a5e9fdbc2e37b7086d97d4bcceec54316dd345fe0a1f8e648c443 ok 1922719 full
ETHUSDT-1m-2024-03.zip b63d885ef49b4e0f2a654ab02c5dcb502fb8abeb7300f3ebff4a33aadd3d4a82 ok 2118386 full
ETHUSDT-1m-2024-04.zip 9c6ef16ea4e0593ac4547d2f6c64c272d8f39806871473c4877885af47a67b88 ok 2016825 full
ETHUSDT-1m-2024-05.zip 4e09e26b7a2b352d24c25f6fc6cdd531d167d460a48226e4a8080413e0bb5e66 ok 2054099 full
ETHUSDT-1m-2024-06.zip 27040862f050687c6da296108dfcfb29e0500e0f9c8dd73669146e9e68a128c0 ok 1945704 full
ETHUSDT-1m-2024-07.zip bda530d17235096c0e619edff1bef56154923b980d7a73406ea66114966ba0d2 ok 2050486 full
ETHUSDT-1m-2024-08.zip de64ff8c0e9bd0ff9ca7fc4015948fac94087c7293915a2a7f7bb47780e98e60 ok 2065075 full
ETHUSDT-1m-2024-09.zip cb2ef3750b2608a871dcc6db479382e33b7d341f89ea17ed58b9fd44db88a793 ok 1965720 full
ETHUSDT-1m-2024-10.zip 99b11df1d79a2408d639cf512f1cfc6a4df4687de9146bd6271f9489ba15a8ba ok 2039885 full
ETHUSDT-1m-2024-11.zip 2c3e15ae6458707b07d2d8b51ad6634756153bc65f9bbb44d5ddb7ecdbccd0c6 ok 2062193 full
ETHUSDT-1m-2024-12.zip 76e33a1db36f036c1e5866de2ebc54ab825522c801e1f9c487a85be781af4716 ok 2126128 full
XRPUSDT-1m-2019-01.zip 42a1dbfc7307378de4d77bd062a73a8da51413adf4299367490ed61984b2a6ee ok 1783441 full
XRPUSDT-1m-2019-02.zip 6f90aa5eb4ce86f05772bef4a30570da511017aa542e04932fe1b3ed6a97113d ok 1624809 full
XRPUSDT-1m-2019-03.zip a8ea9fb2d7d5f5490b5c366296d310c16eac9c0be89dd89c6c043de4c8bfc684 ok 1740215 rows=44280 gaps=1
XRPUSDT-1m-2019-04.zip 449c971bd80ddef61e514d7d16abee43fb29f6dd0f9f74be4b34e19e3fc26687 ok 1754320 full
XRPUSDT-1m-2019-05.zip a7dcde6c903278dd3b746656937694f891200215d96dd8dfade5808f8aa553e3 ok 1850628 rows=44040 gaps=1
XRPUSDT-1m-2019-06.zip 272278a12abaefac6873663331d738feff2ebe27cb6cddd3e65a13eb3d7f593a ok 1830555 rows=43139 gaps=1
XRPUSDT-1m-2019-07.zip d3c518093b4d7f849c1ae54dc8bc68b75170e41e4e5def327d37bdb086abf292 ok 1838509 full
XRPUSDT-1m-2019-08.zip e468b2b7890e824464cf8f5aeb81b85fa6908b164b2594e93a0963f464af3108 ok 1752407 rows=44160 gaps=1
XRPUSDT-1m-2019-09.zip 4483361b531f3eced8914f29c630ef6c7b6290eb852c39dc320da54f0d766da1 ok 1727468 full
XRPUSDT-1m-2019-10.zip f86da16d470c87bc13fd22f4f6619b9038e5bb02077a17eacfa8f3a63dc1eb63 ok 1812041 full
XRPUSDT-1m-2019-11.zip 4001d9e9a001dfe2a562a6deff88266092f58e0e82211189e38a20ad4f1c18f6 ok 1705670 rows=42937 gaps=3
XRPUSDT-1m-2019-12.zip 7eacc827fd71cc7168f6637241a592f2619d30a83f56045da8ec36d6326f3508 ok 1609179 full
XRPUSDT-1m-2020-01.zip f5b5a7c25b482d37f72cc3958da314bc5b0cc10cd7ab005f66fd5af0fcb81090 ok 1782612 full
XRPUSDT-1m-2020-02.zip 0814ef265b082c7991aa170414349936b7148c70417ab154a11dee6148920cca ok 1745583 rows=41346 gaps=2
XRPUSDT-1m-2020-03.zip a9f638f06662821192c3f69f99afcab9994803b94cc27d36c8235a6d906fb9d9 ok 1855759 rows=44512 gaps=1
XRPUSDT-1m-2020-04.zip bcc12bd6e27aee34ebfec2278abb3715fe91238ae333ce2aad50d5613129be4f ok 1729327 rows=43050 gaps=1
XRPUSDT-1m-2020-05.zip e8e60ac9fbe44276d636fc0d479d645b96ad8930680c48ff6fc813bda8c4d912 ok 1783833 full
XRPUSDT-1m-2020-06.zip 2eb7cbce219b6b4864b9793ae85e1667217f12a35cdef870dbbe3c56ef3e86f4 ok 1654664 rows=42990 gaps=1
XRPUSDT-1m-2020-07.zip 96e8d64ca897c60a8bb91ae8268468b058401cabef4b644ce8fd0cdfbf2ff927 ok 1799605 full
XRPUSDT-1m-2020-08.zip be9b6604aa95052d6c292ee9fa29f42df4906f93450d2e1ac5c75c040e240902 ok 1901165 full
XRPUSDT-1m-2020-09.zip 6ec9d10a8684269dbf9391b74487e45533c5649bf426a62f5b7e373ae816ebc3 ok 1764381 full
XRPUSDT-1m-2020-10.zip 4086136a23b8cc3049bd0076145cdf4e3d40ff73017a24befee76b4fd1323da6 ok 1789319 full
XRPUSDT-1m-2020-11.zip 2657626520da268dbc1ac4d099d0f2a489df2ef21851fb0112bb6f7cc3c0f5de ok 1879284 rows=43140 gaps=1
XRPUSDT-1m-2020-12.zip 43355aa84f6e24831e7f791eaa7870473074589735c590ebfb131569c39fd972 ok 2037220 rows=44349 gaps=2
XRPUSDT-1m-2021-01.zip 73af2ae8e9c2ed6290a4e0e89320344aff0f9e0dbc4cb6ca99732ad55ac6831d ok 2017967 full
XRPUSDT-1m-2021-02.zip 73b959d3af743840fc5fe693c447aeff46e23c94ce96ec4ea673dd2d85e78e6e ok 1870456 rows=40241 gaps=1
XRPUSDT-1m-2021-03.zip b7f508eeaa0a34989e2a7baa9da6c41aac118fda7b9aebb133aecd2a13205919 ok 2005543 rows=44550 gaps=1
XRPUSDT-1m-2021-04.zip e7a2d790416579579959f8910cf59bafce8e03da0fe242bc5042ffe0a1bb0a4d ok 2052789 rows=42767 gaps=2
XRPUSDT-1m-2021-05.zip 35186f99f8cfe0093967b0f63c00245235b0ea28f7c71cab9743642ff8ec59fb ok 2091267 full
XRPUSDT-1m-2021-06.zip 2c4f932554177aec5f236ff0c65511e23be27f24ad2e18ea7852921e2826d88f ok 1919483 full
XRPUSDT-1m-2021-07.zip 3bb5b14f18cd369260bb1a06bec9a48551e222c2e8d5dfcbce713fc1350112d2 ok 1911569 full
XRPUSDT-1m-2021-08.zip 7e5dab7bdaeec266cf58ff7e4809d49dad1959f379e32a381bae476a6560e09e ok 1948777 rows=44370 gaps=1
XRPUSDT-1m-2021-09.zip beaa16e73e57586ac20975c930d1d74f2ab44534169222f52eaffeda270a6006 ok 1690390 rows=43080 gaps=1
XRPUSDT-1m-2021-10.zip 3faea6db1a4ac956339ad13c993bc43e148ea1bfcca3f18746c88a9ec9581a2d ok 1732662 full
XRPUSDT-1m-2021-11.zip 7a6fc1719ccbec99aa8b0495916bbd9e46c73c7d59a17bc115674bf4735c3e20 ok 1682928 full
XRPUSDT-1m-2021-12.zip 6e6ad14bebcc3403069b37cf1c3105e8792f8a49be4bab0b1d2cdffd6859545b ok 1720156 full
XRPUSDT-1m-2022-01.zip 777f7fd0cc255c95ac43c18b7b7cb202e474af86b29e02898d189d296f010d02 ok 1665994 full
XRPUSDT-1m-2022-02.zip 83c7caeff6cbf0ac8f505b98be6ed1d07995c838f47cf65c499df6e7bc2da1c5 ok 1549872 full
XRPUSDT-1m-2022-03.zip 8ffb1bcfe11c568ede421226fa1e86d477b2fcbb0446b61edf67e29feb9a72ab ok 1675896 full
XRPUSDT-1m-2022-04.zip acd3c0fecc5af5bcf7581a00098a041fed5895b2a3e7f65e9377f218e5ac5e3b ok 1588704 full
XRPUSDT-1m-2022-05.zip d74ec0797f62afb0455d9cb886ca5e72cb4e83ea191ac0032bc0b7aeef63da20 ok 1662019 full
XRPUSDT-1m-2022-06.zip ebe36cdf629a85bbd4437cb6ccc8de4c00e5ebb674c669fbfe9793a40ec13194 ok 1574335 full
XRPUSDT-1m-2022-07.zip c5d16ce8ad34cf0c4cde151e6706b82bcb0591b227a30027878957849ca4449f ok 1596371 full
XRPUSDT-1m-2022-08.zip 2065bb2f4de9812adb2c701e91775ece3c5c81f1fb00d1236e9c32f7da3a0739 ok 1563297 full
XRPUSDT-1m-2022-09.zip a529d48a7826f5adac1f8a6f06549718d04fdf463783db7ead7134ae6a69bb04 ok 1584509 full
XRPUSDT-1m-2022-10.zip ecde9ced9ad0d05c7501d3ac9183a7fab73d2c855df4e49241dd81cdf8f0383a ok 1628297 full
XRPUSDT-1m-2022-11.zip 838ef0f8a41d44484e2df9077607b0af33aa7d25263a1beeb1ffcbd471dfb6b9 ok 1587313 full
XRPUSDT-1m-2022-12.zip 59621d1076e485e617c232eedddbddf1c4f930687bf5a254bfa45acb09961f9e ok 1544912 full
XRPUSDT-1m-2023-01.zip 1fcd000025f1e7ba233de4b38463cb23017530813ea8db412ea81a878f0567aa ok 1597739 full
XRPUSDT-1m-2023-02.zip 798acb01ce8d43ca4ab94d6aa059ca15498af96088aac985a202ec1dc6c35a24 ok 1425578 full
XRPUSDT-1m-2023-03.zip 2b203759453af143ae3f26dca22237cb1a4db6f6423e009ce5e5f459859a7f70 ok 1648065 rows=44560 gaps=1
XRPUSDT-1m-2023-04.zip 4752b4942e1785a429d8c240a33fcc4ff4af0fd741970c7f1b909e8cb22145bc ok 1568033 full
XRPUSDT-1m-2023-05.zip 489e1e0b89b5755369671fdb87b6be87bd427df2104f8731d71a139cac00e72d ok 1582454 full
XRPUSDT-1m-2023-06.zip 5dc441b17babf643b45db165b2d9fc93e5866223d8d6bbe2281e1f65ac618bcd ok 1571387 full
XRPUSDT-1m-2023-07.zip ab2751fcc117167350081ee0601f4a846b329ce7bbcb543da925e5e16bf798a6 ok 1640392 full
XRPUSDT-1m-2023-08.zip 89153a1bdc14c620a81463b88cd256c99857ff38cf188bc187e4df3fd6a2cbd2 ok 1607764 full
XRPUSDT-1m-2023-09.zip 732f498075b74cb5d491760106fd2e1318746b132b03c1caeb1d36f196173e8f ok 1504903 full
XRPUSDT-1m-2023-10.zip 7c218aa5e4c666a0b2141d9af055a40ce1b32ee40bff1a1a1c341035deae0d0b ok 1571909 full
XRPUSDT-1m-2023-11.zip 97e3332c1f2c98409e461aed034a06a67c61a1b9226e05a8c004725c776c71fd ok 1601303 full
XRPUSDT-1m-2023-12.zip 133af64d455ff9030fb87b5fe2030a8d4e9b1d26f0ceecb5c19afae93d23763c ok 1635923 full
XRPUSDT-1m-2024-01.zip 7307c945202ff1ca4c7253cafd0eb32c7fb386f6affc626b05085dcca8bc6ab1 ok 1616439 full
XRPUSDT-1m-2024-02.zip bb09ee2826c57f65cbbe01910e8ee87865e3e2c0e61bfa53bde2d85052361c03 ok 1517232 full
XRPUSDT-1m-2024-03.zip 67b6cc9a7a95f742598c2e322aa3575150ca72f0ce97c8d2d35fc7b02c6a0875 ok 1710294 full
XRPUSDT-1m-2024-04.zip 7723a19e8e732ebac38bfd602772b5bc35866d878c02d37da8e4fd6892010c6e ok 1600651 full
XRPUSDT-1m-2024-05.zip a1231fd035be7bab1094c652de47a5943fc6dbd1055e3ae41c61f96134aece73 ok 1576013 full
XRPUSDT-1m-2024-06.zip 21cbc69db10fe45a7ec09983332dc6d6421ff84518d9fa6ef4f4943b67e6eb40 ok 1493091 full
XRPUSDT-1m-2024-07.zip 08c29b28bc0408777ee9b3e5d4ad083972ca494f1d9f9611909d5130df8e67a6 ok 1651037 full
XRPUSDT-1m-2024-08.zip 4c59e3ea764bdd93aea41c1431aa9fb6279ccf652ddfac58a4e5271317defdb6 ok 1641406 full
XRPUSDT-1m-2024-09.zip bc5dc9b1f099dbf7abf37234badb0ace9a0dd9d72883be63cd3dac540d5eee1e ok 1547725 full
XRPUSDT-1m-2024-10.zip 00d72539d3a2e6759b460e2f969ec446bfb23ada4a3cd2df081c0e61253a6a0a ok 1583250 full
XRPUSDT-1m-2024-11.zip 95b32d9b9b25a3c214f2eb225897e786c2469f7f9c759774b5d7ab87ce3de97c ok 1719410 full
XRPUSDT-1m-2024-12.zip 1772d2484aade02a23777136c98ac3dad2373cc3418a356f6d9fe70d88bfb83e ok 1847055 full
BNBUSDT-1h-2018-06.zip 5387d0cfb2a73fbfc8e8e8dc5ca48b43284bfe8264a36b755e77eb0e8c10b094 ok 36218 rows=709 gaps=2
BNBUSDT-1h-2018-07.zip f257601fd9bb65f4cad1b19ef1ff2184dc9db514c11967cde3fd9d87596bd8df ok 36920 rows=737 gaps=1
BNBUSDT-1h-2018-08.zip 03b335750cc26363a51bdbf3d1869c5f5f4cb5e04596ac023080bac944b61f9c ok 37040 full
BNBUSDT-1h-2018-09.zip 8ef80e4b099d4d86edf9e2bacb49d014e46394cf7965cb5ef533190661176921 ok 35365 full
BNBUSDT-1h-2018-10.zip a6060c7540ac3a8df0895ea41abfa02e30824276c44920efcb21768ed8b5dfcc ok 36221 rows=741 gaps=1
BNBUSDT-1h-2018-11.zip 3f9d645cb6127e03232685214aaa86c3db6fc04739ff25d3c3caa03a86fa4b31 ok 34843 rows=713 gaps=1
BNBUSDT-1h-2018-12.zip b8d439e9224923bbd61e62e87bc692cff9d0b01afa34671c39676d86f01003f7 ok 36706 full
BNBUSDT-1h-2019-01.zip fab1f4d8efc9978956530efb57c9a68fe390dd0a79348426aab73b2555a6438b ok 36927 full
BNBUSDT-1h-2019-02.zip 33c2c515d6c04edfc6418626a6b11191d68c67ff796b8427644f8a8ed0a35232 ok 34423 full
BNBUSDT-1h-2019-03.zip da199264f411a43222cb2af089226d10e30b06b6c32b576b3f92809042f45cd7 ok 37872 rows=738 gaps=1
BNBUSDT-1h-2019-04.zip 40c0bc056473ef0cee27bb6f5581f97b8618df3b5b56c448ed13dc4961becf33 ok 37231 full
BNBUSDT-1h-2019-05.zip d5c3c8c2b0dbe21b04acaf39779011a622a054d2c535a45c540eabb55d1c13fc ok 38637 rows=734 gaps=1
BNBUSDT-1h-2019-06.zip b3f6c0d041b2fa945d485eb4b2805d20eac3d6be5c020e0e3956f846873fbde5 ok 38017 full
BNBUSDT-1h-2019-07.zip 0fe6fb80aa91c45e2bc8840a156965fe71104085e128204c7d824d15b23ecd56 ok 38985 full
BNBUSDT-1h-2019-08.zip af790ed24b662f5f68bd27c5fde95f2a11924cf28880b134eeb42b6f54ab6f06 ok 37841 rows=736 gaps=1
BNBUSDT-1h-2019-09.zip 7ef077252f2dcf0257173cc4970b7cf13e34f7e2b46022c486574827e8cd58b0 ok 36753 full
BNBUSDT-1h-2019-10.zip 7f3e63d09c4609aa40366520820591f79acc57353b9abdef94f464b0174571de ok 37900 full
BNBUSDT-1h-2019-11.zip 1ca416955111421077893e24b67b7316acb64ead64bd6b65d5cd4b08f8b3d54e ok 36524 rows=716 gaps=2
BNBUSDT-1h-2019-12.zip 393a169bce92cda5393800c5d4f3a2287f07b766f1b0d811e330a696c1c16205 ok 37283 full
BNBUSDT-1h-2020-01.zip c7c633f64a90da9d3b26437e795334dda7400088edbf46e3dd276ab8104627d6 ok 37815 full
BNBUSDT-1h-2020-02.zip cce9cb682bee3e14a5fddf41cb19c91e1cd8892ba01fd378d7029f1efc77dcf6 ok 36106 rows=690 gaps=2
BNBUSDT-1h-2020-03.zip 961a87ed37f1ab7347f62ddf849d5148d1d8118b510b76e8439de0dc12355484 ok 38812 rows=743 gaps=1
BNBUSDT-1h-2020-04.zip 3328ea16356715151fe25d50e2e571211e3eb61df5e48296f2bb2045ed11fc5e ok 37138 rows=718 gaps=1
BNBUSDT-1h-2020-05.zip 5efb838267b1fb2d697eb882ba2594f50e0a39059f9bc1230f9731455de757a0 ok 37999 full
BNBUSDT-1h-2020-06.zip 7be1b27d6944570a9605d46f01fc40e97298c17864491fe960daef2ef1509622 ok 36116 rows=717 gaps=1
BNBUSDT-1h-2020-07.zip 9e5b8debbed787781379dc5d34a55c2752b6c142b60b35a1ecbe213c3da053dd ok 38148 full
BNBUSDT-1h-2020-08.zip 0cf6d7391bc0fe9adeea6d1e0c9bb283fe3f0d35697d3c08146964277d586b16 ok 38666 full
BNBUSDT-1h-2020-09.zip c9c96f9c69e6d049fd9439cd5637c86ffdc100340bcb351327c120e726b688e0 ok 39279 full
BNBUSDT-1h-2020-10.zip beff332c397453baf21f80ea4c4eb603649a455c6bbdacb614c097b0e38bc275 ok 40287 full
BNBUSDT-1h-2020-11.zip 0f021ef432d688d84402beeb699d56af37c286fbdbb755568c5befe3533215bd ok 39002 rows=719 gaps=1
BNBUSDT-1h-2020-12.zip 787805f1a8f7721ab1e9908ea446d806d09a210a2120aeda9667e66e09ab6ccd ok 40352 rows=740 gaps=2
BNBUSDT-1h-2021-01.zip 5cdf6cb04631af89dcf108fb7cb8f5c0a5d23ee6c7a5ab9fbd3db3086637e694 ok 41325 full
BNBUSDT-1h-2021-02.zip 43b7f41f3f21631ff10bd8773dc15b51fad7e34e71781abe44e293d783be2215 ok 39636 rows=671 gaps=1
BNBUSDT-1h-2021-03.zip 3b91972b1b96f3744ac6cd176ce805a2205ca0e04695ca86c0cda5d2adcb600a ok 43542 rows=743 gaps=1
BNBUSDT-1h-2021-04.zip 7a7c1d9b77747355826fcc8bfafa02881baacda993dd6aa552229697b7809864 ok 42489 rows=715 gaps=2
BNBUSDT-1h-2021-05.zip 487847e1fb70123743a58793305629d327d6cd4515e059d40e4017a9e120fe01 ok 41887 full
BNBUSDT-1h-2021-06.zip 6778ed4eacf42e5c8fe3ae44cfbc932fff6c690db59cfa93b096010628441f99 ok 39809 full
BNBUSDT-1h-2021-07.zip ca4060e5f13413a1b861483641d4dd9d3fe81c7a612caba21b565b4e20346934 ok 40166 full
BNBUSDT-1h-2021-08.zip 40c898781fa5eb29fa76b4fd6950a119fdf743c2305b99d2727e96d8730c52a5 ok 39664 rows=740 gaps=1
BNBUSDT-1h-2021-09.zip 2aaf3c5358b46ef7d59d7013fd3dacf2a9ecf27037929f061611c028d205abe1 ok 35105 rows=718 gaps=1
BNBUSDT-1h-2021-10.zip dc2acb054fdcea05d7c8cb4511376b20954d034f6ddfd4d5cd07cb405886c082 ok 36370 full
BNBUSDT-1h-2021-11.zip dc3f62a12d9f21818c9bd8b35511e3e255fc4f4bf114fc4e4506a32267f97e6f ok 35834 full
BNBUSDT-1h-2021-12.zip 8bbc6c5be0dd58d060085a2048d2d9a807183fce333234cee1cfb03447b14b36 ok 36351 full
BNBUSDT-1h-2022-01.zip 663ea08387d4c5155b2421ebeaaaba14850e4362cc9e24ee7979bfefab03f625 ok 36270 full
BNBUSDT-1h-2022-02.zip 00b3aab119398a6ef303a9b122f7ee819eb1c62c358d3d511ceae345b74ba6db ok 32428 full
BNBUSDT-1h-2022-03.zip c6c3ae3b1332fc39d92749bd126fb675571fbe80576cd95d56d0a16a0ec77afd ok 35502 full
BNBUSDT-1h-2022-04.zip 496c543a2aac62b3d8ab6a71c89da4db9ad4fcd9bc640905edbeda7b4487004f ok 34372 full
BNBUSDT-1h-2022-05.zip e183a9b786ba8c2ddcfb48cf974dcd8edad5c6816e865e3ec62d9d94eec08c7e ok 36016 full
BNBUSDT-1h-2022-06.zip ea7faf8f2d22c27768b868ca431c56d2cbb83d955d3debe1e6dfb70f034de32a ok 34396 full
BNBUSDT-1h-2022-07.zip 829ef1e541a13599cba457ce963674c2f14447899c7f43b878299e5f59a2b7f5 ok 35025 full
BNBUSDT-1h-2022-08.zip 927a92e9c381729b063cbe89a4a8bca10898aca61e1a6919a016ea7eb959304f ok 35110 full
BNBUSDT-1h-2022-09.zip 054d3296f060a815d7ad5c6485d4883430dad0fc08e78f0be10df66884620eed ok 33360 full
BNBUSDT-1h-2022-10.zip dfc624a65e466abc9698c1d153843d78f1df449107bce97c5215525417fa3718 ok 33929 full
BNBUSDT-1h-2022-11.zip f9f9497753bd5d1df5a2a59ee5dfe07edd79f2be7aaa14a5371511a464fa2495 ok 34303 full
BNBUSDT-1h-2022-12.zip acc9f21b1ed51b5f4cc2978ee95a0e50ffea7891cd1037a01c8c88c4e71a7104 ok 33928 full
BNBUSDT-1h-2023-01.zip 4d7ad8f2cc41682200d6e8d1ab6088219e302b3a356f9997c19395b0208497b5 ok 34390 full
BNBUSDT-1h-2023-02.zip 0e15c412a2a14f40e67c12b5546ef736f88d045815e68341f1f5a567cc428ac6 ok 31305 full
BNBUSDT-1h-2023-03.zip 55bba490654b69c26cc1989f17902737535682f70491132f66246fbea3b7017a ok 34621 rows=743 gaps=1
BNBUSDT-1h-2023-04.zip d45f37c1f4c7bce00774074ab01c5f385ba150e28e5cb0c84a73371d2042c313 ok 33367 full
BNBUSDT-1h-2023-05.zip 882253ca7518d2b5cebdc388b6e8cf5a1c19d180e629f848d201c5bda54c46c3 ok 33914 full
BNBUSDT-1h-2023-06.zip 27607d49c36f479d582801faa9b8eb698b79032ca4aac69d65c720eeca6cf122 ok 33671 full
BNBUSDT-1h-2023-07.zip 7bfa51be86f9822859af309dc579134089c2e8040a9f66503be0d5cd96499060 ok 34033 full
BNBUSDT-1h-2023-08.zip 5eebe4ec692c43e9bc8722632da94cd79187aa17b848da9361656ce0be430bd0 ok 33541 full
BNBUSDT-1h-2023-09.zip 159a99069e8826ee23aca59b5dc7864a083fe5a4d8b13f888b68dfaa4317816b ok 32070 full
BNBUSDT-1h-2023-10.zip 65e6c269037fb53ed74b9cd03219a42d98dff1d48cffde8307e9d9c73dfce63b ok 33638 full
BNBUSDT-1h-2023-11.zip 486035abf6083f90e53e0c49e0fa829d0380d174a65ea6e8bb9066f76b139554 ok 33769 full
BNBUSDT-1h-2023-12.zip 9153d4b7bf9e5cc6c49857b65ad7a3566faf525774deb0336aad1af9b44bd639 ok 35321 full
BNBUSDT-1h-2024-01.zip e06554367764c662b9690e28359193fb9c8b9d5d44cd09f4b23d6d022fe9552a ok 35215 full
BNBUSDT-1h-2024-02.zip c79637210a9b67dcd198cdff3d75c8f275bbb0be13ff0a7703378e16fe051d52 ok 32997 full
BNBUSDT-1h-2024-03.zip 06e124d8cdeda60dd327ad23d9f61470f874e14e6fe495cb1739b50961af48dc ok 36669 full
BNBUSDT-1h-2024-04.zip 623fae707bcafc75e01281565626f1ea0fac03d010d630dad7f67fc76ff31e72 ok 34882 full
BNBUSDT-1h-2024-05.zip 489692791a583ed29b26fcadfba774832820a842e8e393e41764df9221279d2e ok 34971 full
BNBUSDT-1h-2024-06.zip c9f4bf8e332c1a4dc3e57655f17c12a5554f8bd085ddabf70fbe464b7071ba95 ok 34039 full
BNBUSDT-1h-2024-07.zip 6fd039df81b4a12d699b9f810cb39dfbb389edb1d508571d49432247c630fb4a ok 35087 full
BNBUSDT-1h-2024-08.zip 4334244cd1cd0e2ed4d9a1e42d92e67418b83b9565d8eb9618f826005f1655f2 ok 35380 full
BNBUSDT-1h-2024-09.zip 2697bc4cfc775ad17de0adfabd4b94ac4d575414dd374e72a9b77339f7dd2930 ok 34071 full
BNBUSDT-1h-2024-10.zip 36768457c4e40c9b80088d0e2559876822e18269ecb782b5f570f0b205ef9d8f ok 34791 full
BNBUSDT-1h-2024-11.zip 133bb27dc562eafce74b7a7deaaf7742a5e7790efbd23130876b2ce41a18c77b ok 36964 full
BNBUSDT-1h-2024-12.zip 9ffb3beebc21b20ac140d985050a49fa1e11b475aa9dff3f9b75e55a9b832165 ok 38661 full
BTCUSDT-1h-2018-06.zip 20894cb34d1049cbdd93df83be5f218c6ae1b5ca27b689b1b076ac5bc809fb81 ok 40629 rows=709 gaps=2
BTCUSDT-1h-2018-07.zip 29610f0bb84011e494b83881584d1eb2d3a61c5801ee51ebea7c1c4e6a9b4210 ok 42249 rows=737 gaps=1
BTCUSDT-1h-2018-08.zip cad3b2b11aefa082a07ae3d8f11dfd6ee5018702dfd3986277151b66ae002991 ok 42956 full
BTCUSDT-1h-2018-09.zip d8109c9f64af195fb9babf498f84ece9e7ac471618977202dcf710461e124d00 ok 41166 full
BTCUSDT-1h-2018-10.zip 959094f6d37e7cae75951cea30fdc3d5b1eb9de58a6cf1ce40f0e49d0adfb79b ok 41446 rows=741 gaps=1
BTCUSDT-1h-2018-11.zip a75aba58d80b798809e47819990fad71418c0982be1c4643b5a0490e0f86bd91 ok 40709 rows=713 gaps=1
BTCUSDT-1h-2018-12.zip c5f05f2966529220add51dc1ee66ab7408ae787179f96c288e4f6ff021f51edd ok 42802 full
BTCUSDT-1h-2019-01.zip 41cb84ccff03d5372f22e7502a1c563dd7b3b15347fe086b16daa98aced7a179 ok 41901 full
BTCUSDT-1h-2019-02.zip fc054507a0f33b54bcc2f292243b8caa765927572e92731283f42498c64dc4e6 ok 37982 full
BTCUSDT-1h-2019-03.zip 2c4a969908c2570299052b4faf27b4a39561b1043babc7a65a846a6a65abaa2e ok 41360 rows=738 gaps=1
BTCUSDT-1h-2019-04.zip d37e1150e8f4556a22cb2ed98d9b6eefe7b5df3be9f06587e273baea2bbf960e ok 41191 full
BTCUSDT-1h-2019-05.zip ddffd71adc100760d31ab5ea0fb8d8ccf5f3c80a06a31808a024324b4a693799 ok 43004 rows=734 gaps=1
BTCUSDT-1h-2019-06.zip 079b0071aaf0642d3608bca3ee14e50e394550176da3e4029d22761e288466e8 ok 42603 full
BTCUSDT-1h-2019-07.zip f45beec30a4812d42b8eb3a34da3f75e5dee0433032a06ba57ff48644ee7c2f9 ok 44318 full
BTCUSDT-1h-2019-08.zip 50b058b5774190b577f1bc45767aeb33f4e947dc00e8d143f6c4afa0f5a3cd34 ok 43243 rows=736 gaps=1
BTCUSDT-1h-2019-09.zip 2aaaf6e4d0455b889225ca1cfde23a15e2359850f803bc9998df30ac1bbef63f ok 42109 full
BTCUSDT-1h-2019-10.zip d44a2b3e463683c8bfc61c2f15f156665dc3dd3835e69c2ea3b49a518ca14b43 ok 43434 full
BTCUSDT-1h-2019-11.zip 63572600e87350f1d5679049a44e8338cf7b692d0c67220dc316267a91af108b ok 41930 rows=716 gaps=2
BTCUSDT-1h-2019-12.zip 87267b84d9f0e64ec94799d62de6730825c6a44f154ada5ed8c2dd267df78481 ok 43061 full
BTCUSDT-1h-2020-01.zip 4ef7fa698b6821493f4c8317bc616d48bcdf5951d32fe6e40aaa7608886e51ca ok 43583 full
BTCUSDT-1h-2020-02.zip 0189065a1b789825448530cb3fdddcefa45ca13b0a6bca181f358c72d3a6d5e6 ok 40628 rows=690 gaps=2
BTCUSDT-1h-2020-03.zip cc36c481c31ef93115d96b5a7045ec2ef737e5339546d6688cb1f677526c6787 ok 44270 rows=743 gaps=1
BTCUSDT-1h-2020-04.zip 4f08d13c81cadf8d5fc7afcd0924d084d2f81c7d004323812e7508ad135f89e7 ok 42275 rows=718 gaps=1
BTCUSDT-1h-2020-05.zip 1559b30329851938a54e6782cd28dcbf34ec27a6cc82132250db9a357f4eaf5a ok 44022 full
BTCUSDT-1h-2020-06.zip 2ccf45a7307e09dec1fd3622d54057e7e44371bf70a8be1030687f654341799e ok 41724 rows=717 gaps=1
BTCUSDT-1h-2020-07.zip 378b83c163c8d315075189b039b027d705c3ae225461f04c1226569a4edfcb99 ok 43137 full
BTCUSDT-1h-2020-08.zip 3b4fbdfe798389a1317e333772f176bce711856d87e68c1b77f09631b0cf4b84 ok 43923 full
BTCUSDT-1h-2020-09.zip 46f236c7cd38d72d4a37e80a45e357e7bec48bc89cc6a36c0c17ceb92ce8d101 ok 42467 full
BTCUSDT-1h-2020-10.zip 72fe011922ace0851a44ffa51327d75545212a7e8179867d514a5934ce93a6e0 ok 43559 full
BTCUSDT-1h-2020-11.zip c3f3548fd082f0fa63d2138a5aca3b572729f6351de8a20c895a80acd3ae395b ok 43234 rows=719 gaps=1
BTCUSDT-1h-2020-12.zip c880c8e76e2dbcbed04bc1ddd549949a94a4314520dc1f1becbd881453aa5ede ok 44596 rows=740 gaps=2
BTCUSDT-1h-2021-01.zip a2fa12bec12d942e58dbc7fb223973bd2173dfccf8e09edc501bda40b3c3638e ok 45988 full
BTCUSDT-1h-2021-02.zip 8cd20f5058dc7585cfa874a3ab0e5fd0096f369c182d8fda80dc16495050e018 ok 41575 rows=671 gaps=1
BTCUSDT-1h-2021-03.zip 748783e9715835dd334fbc0cbbff0518962ebbcbe0430acb65f2f506193bad2d ok 45712 rows=743 gaps=1
BTCUSDT-1h-2021-04.zip e5a33803814e6771c4c85e8f2e28e90e46d40f14ca3180a8c10c305cf07fab74 ok 43918 rows=715 gaps=2
BTCUSDT-1h-2021-05.zip 728503d417904afff17b403e66f74c18ed0067d3f8e4215130c8a97180c9fccc ok 46221 full
BTCUSDT-1h-2021-06.zip 9ea9585cf2c938044d2d1b613f451ff9482bd7d2a38da2c9d22cf0c9f00f65ac ok 44232 full
BTCUSDT-1h-2021-07.zip 993a88728e31b4c4e6f3b28442ab251de5ee434fe06865e1b57063a4f91fc8d9 ok 45217 full
BTCUSDT-1h-2021-08.zip 5cadb462255761842326a2c4b5fe2a91c8a2135c3ba6dd5f0969877f0722f4be ok 44883 rows=740 gaps=1
BTCUSDT-1h-2021-09.zip 0d344f8ab39d910c148b89fada91256afcb3e8b20eb812ebc158ac8ac527ea07 ok 42473 rows=718 gaps=1
BTCUSDT-1h-2021-10.zip 8065fe2ddd9992398b49fb76e83a60e51392e1ecd4b46c438c075d3e5f6e2291 ok 44164 full
BTCUSDT-1h-2021-11.zip 64d376e949c3518c3b526cac41322114a2e7287395e9089f0da34e25079c2940 ok 42690 full
BTCUSDT-1h-2021-12.zip b01133a69b22aa7904742a06a892ff3811152377f61e23977051a937afe2fbaa ok 43757 full
BTCUSDT-1h-2022-01.zip e04068d0aee5e3571dc7e9a1d220475047f544e1cf1bad800b7cbbf190281c40 ok 43687 full
BTCUSDT-1h-2022-02.zip 4e479b38278726cccb9257f5564c5c78477144d3ffe69df6afaf3b55ace617be ok 39642 full
BTCUSDT-1h-2022-03.zip 1cfb082f6bc9a2937b5b846073ddf65f71b18f2502778ac667aab3421ef80085 ok 43784 full
BTCUSDT-1h-2022-04.zip 7157a267e70bcd9ae04a8898527fad00d7733e941df9b95a1d5e0ae6dcd61c3e ok 42204 full
BTCUSDT-1h-2022-05.zip ff0744eceba5e6d2f7145ecfdc9d3fac84f4576c15221dbeb71c6d6e59484300 ok 43955 full
BTCUSDT-1h-2022-06.zip b18f6f8edbb41960f81aec100c7836fdc0de6d640ee4309a3d0fad999ae0a2c8 ok 42662 full
BTCUSDT-1h-2022-07.zip 9f0ba9663f9fada7692b3cfe645df3832599f9e785056ddd77bd464475553e9e ok 44740 full
BTCUSDT-1h-2022-08.zip 3cc22044f94cb303d12013293ba6db6d44abdf1490d38d00f1389e98717a3891 ok 44748 full
BTCUSDT-1h-2022-09.zip a65dcd73017d92ea8d86e82ea1aee3dac55881f8672594d2e85d1cf392e1e78a ok 43701 full
BTCUSDT-1h-2022-10.zip 2591cbbe022ce9d4559aee1fa41ea0033324c2c4debc776cfedc9588167d413b ok 44566 full
BTCUSDT-1h-2022-11.zip 5608adf8602a8ac616ee03c2c4461a37f4646631d67edf3d2f1a94e82e5c5065 ok 43509 full
BTCUSDT-1h-2022-12.zip 69c5e5f01df947bfea48ab3c8e2f462b7358effa9e2700489a4ad0dbd29b24aa ok 44019 full
BTCUSDT-1h-2023-01.zip ea8caf7fd56c7f7143723f56f8d12a2fc0b643badbcdae5c660db2d11454a11d ok 44765 full
BTCUSDT-1h-2023-02.zip 53525b700548a19488fcb8754778acdf7941c9ba0b6e7eb548a51a376ef8d86b ok 40955 full
BTCUSDT-1h-2023-03.zip 7f2afb8e0179a57ac31eab5205660298ba5eb77039ac2e21aef9b715ff3d06ce ok 44928 rows=743 gaps=1
BTCUSDT-1h-2023-04.zip 1787dc83836deafaa77d4276cbe3b3ca1fe0083b3017079e3560605ff4f7a4ba ok 41904 full
BTCUSDT-1h-2023-05.zip 16b33557a4a4040fc56c711f4b1a750ebafb5a7f8dd46c060d9fc8c66cdc1982 ok 43095 full
BTCUSDT-1h-2023-06.zip 05f87fb5f004ee0aff019adb7015afab8df0baaaf2b77154d75ae53e18d59b11 ok 41669 full
BTCUSDT-1h-2023-07.zip f49a738a793055a583784e78a54840a43861fd110118cbe1add14ef1afb63032 ok 42245 full
BTCUSDT-1h-2023-08.zip e983243d44536a06ff4707cf35df29f636fe788e6fb69c3b3feed2ef43d343d4 ok 42213 full
BTCUSDT-1h-2023-09.zip 28e12ccaf15745bfe11f570b9079793750047fde3d340fe0231858b26bc0f9d9 ok 40962 full
BTCUSDT-1h-2023-10.zip 165ec50601f914d6c41b776414096bc73974bf45fcd41aaddfedd1cf66cb6c6e ok 42928 full
BTCUSDT-1h-2023-11.zip 4f550d182d529839dd9cfc28ef0ecca8cd8003e991067e92a2af5b9e92762f49 ok 41648 full
BTCUSDT-1h-2023-12.zip 6117d93e3eb6574df6b0087a45cf12e171afe91789b523b0bfcce00d8f1b6e37 ok 43309 full
BTCUSDT-1h-2024-01.zip cf873a185bd5b24b8e00034e49583fcb49928e0c3a45c6fc27a632a683655417 ok 43482 full
BTCUSDT-1h-2024-02.zip b83aa7319ef1d4baa7b923c0fe802b88dfaf241c7456af295f1f656a24379b33 ok 40711 full
BTCUSDT-1h-2024-03.zip b0851daf609d6ab82fdf8f1d1c4fbd974bc1b4e6530a832067516ac1c2be63a6 ok 44044 full
BTCUSDT-1h-2024-04.zip e266707ad2ea3cd4680bf1ac5025f0c1bfeb38e703374a91f8dc193d1ec8d48f ok 42474 full
BTCUSDT-1h-2024-05.zip 077c71eec71a8ecf2edb6e3a3927b600b8f358fd37066ce120c19fb5302a9ab8 ok 43425 full
BTCUSDT-1h-2024-06.zip 2e1f968fa34b9feabfb19cc6eec47a146e20d64a706f4b17d0babf4d2f475c39 ok 41535 full
BTCUSDT-1h-2024-07.zip 41fd58a70ae40bebb74682555cc5054709f8dde0f5c8193ae2103dac95274e5f ok 43162 full
BTCUSDT-1h-2024-08.zip 88521a975ee7bfdd21f891d81f4243a01b90b977cf525d11747e27c66e3bad60 ok 43406 full
BTCUSDT-1h-2024-09.zip 123f402c6dbf19b9b72b4af7ad4d5325c73ba4833148cc398b803d7a34ac5c5f ok 41468 full
BTCUSDT-1h-2024-10.zip 393b18ad2634f0cd3b2fd54321c8286ea143419cf3129b4cc44e089681912b03 ok 42989 full
BTCUSDT-1h-2024-11.zip 7a51fe8811c754ff43a2be0ba10e53a6d4218521e27ac765fbc9a1ca0fc15bac ok 42752 full
BTCUSDT-1h-2024-12.zip dfec812f73a84257b195cbdaed34d020fa77e845625c061c13bd6a60e7ef9372 ok 44271 full
DOGEUSDT-1h-2018-06.zip missing
DOGEUSDT-1h-2018-07.zip missing
DOGEUSDT-1h-2018-08.zip missing
DOGEUSDT-1h-2018-09.zip missing
DOGEUSDT-1h-2018-10.zip missing
DOGEUSDT-1h-2018-11.zip missing
DOGEUSDT-1h-2018-12.zip missing
DOGEUSDT-1h-2019-01.zip missing
DOGEUSDT-1h-2019-02.zip missing
DOGEUSDT-1h-2019-03.zip missing
DOGEUSDT-1h-2019-04.zip missing
DOGEUSDT-1h-2019-05.zip missing
DOGEUSDT-1h-2019-06.zip missing
DOGEUSDT-1h-2019-07.zip b6a303e2f070f039663692b7dc22332ed61bd6281f7737df3b3db49ae36db208 ok 29843 rows=636 gaps=1 first_open_ms=1562328000000
DOGEUSDT-1h-2019-08.zip b5e15ced0127048e14bd6a1daeeb0ea8d5fe108d16a5e7c7ff49a43e18e41edb ok 33134 rows=736 gaps=1
DOGEUSDT-1h-2019-09.zip 834e8ed30690e08e58fa6d356104c42bb3fb7b120c37a7d920a90726c7571071 ok 32119 full
DOGEUSDT-1h-2019-10.zip 249170b1d7f3c56d8cecf8b3ad43cb4c84e08eee95ae2fce3d38ac72251f1786 ok 34181 full
DOGEUSDT-1h-2019-11.zip 51efa4af8de2e7fee39f98220aa091da037c10684bfe5d939050ad2c44545ce4 ok 32455 rows=716 gaps=2
DOGEUSDT-1h-2019-12.zip 81c9e7c9eb3a301b8e1604a3d0098e4de9f066e90502e048acea46d89dae82d1 ok 33343 full
DOGEUSDT-1h-2020-01.zip 4a7b805b539ed935e653780575b2d8cbbe84675a5cad88018693710ac209ce14 ok 33860 full
DOGEUSDT-1h-2020-02.zip 1d30f3502afb72621887e2c1f3f13bd8690a4690418143fb91ede1273a17d51e ok 32742 rows=690 gaps=2
DOGEUSDT-1h-2020-03.zip 4bd6b341e6249e379a0c324fc58b399bbf4c7fbb9ab2c828d22a495f35fdd9c5 ok 34405 rows=743 gaps=1
DOGEUSDT-1h-2020-04.zip f04a9bb723ea01db14c14528057394ded3ca91d36e8974334b3b07cca8860728 ok 32726 rows=718 gaps=1
DOGEUSDT-1h-2020-05.zip bc4b3136a22b3e5df603b695c5b0d6c1b50bf3d0bafc50dc1c32a3f9f569763d ok 34101 full
DOGEUSDT-1h-2020-06.zip 5a6283bbb9d3150f8f286b80e96c7c55562ae2dc6327d10fafa6a84b139adf2f ok 32281 rows=717 gaps=1
DOGEUSDT-1h-2020-07.zip 5411d769fc8161deca0ba3cb4471446fe3c6b4754216db5b24a3995edf201524 ok 36681 full
DOGEUSDT-1h-2020-08.zip 5b05e8ffd11aff3d1a12bffaa433212a7fbaaebf636651d88a54b18c668d4c53 ok 36438 full
DOGEUSDT-1h-2020-09.zip 9890ef4c7225b71b4b375477d637472e1df493c05117fa8e3ad464c59d1b8a1a ok 34802 full
DOGEUSDT-1h-2020-10.zip f7c4a54f89afa57c4dbb9ff6128c1bfb7a90ebd7142b024eff5e4cde3e76a42a ok 35040 full
DOGEUSDT-1h-2020-11.zip f0b0aee627a29dc72b476b0589eed1a53a3ba6e0f2cd2a84bec0baa4ec79abf6 ok 35231 rows=719 gaps=1
DOGEUSDT-1h-2020-12.zip b028192a15fe8ee3a500375c0031f30da679ec85cacf5a39f9a804ffe74500fd ok 36756 rows=740 gaps=2
DOGEUSDT-1h-2021-01.zip 88aaaa60e0ef2fc00b484bf70e39c251a549715081cf04df27c258ab3865dbab ok 40082 full
DOGEUSDT-1h-2021-02.zip 7412710e3a36d4094589468433d6fc602de56834eae347cc9e12186c5890e0e5 ok 38289 rows=671 gaps=1
DOGEUSDT-1h-2021-03.zip e3d5c2b7c9c56b91243995060e4d66d43cedc66b8e6f43ca9089c74631a0c031 ok 40448 rows=743 gaps=1
DOGEUSDT-1h-2021-04.zip c425d82ec2b08ad2c71e8c6f001163db4cff059dfd0c4e94004ad3f5f89b760f ok 41214 rows=715 gaps=2
DOGEUSDT-1h-2021-05.zip ef8f7b42261662befa971a6190129866cdb77ecf72bc3650fa0d28849e296631 ok 42202 full
DOGEUSDT-1h-2021-06.zip 7c6707ba5a06571fb52a065c237f7950f6a75c3eea02ae75c93788c8aa0b278a ok 39441 full
DOGEUSDT-1h-2021-07.zip bae7abe6c08eabc06eed943971fc18647ecd7112e3a7a61b5f235551ac896356 ok 39607 full
DOGEUSDT-1h-2021-08.zip 5dfa72df4dd5c3e749d7c55f8c393874cd37242fbcf6aa5bf13d75ecf898a114 ok 39445 rows=740 gaps=1
DOGEUSDT-1h-2021-09.zip 344075723caf8ef1fde3e02ebcbfeca8cdbec73f60073381da15dae68488555f ok 33930 rows=718 gaps=1
DOGEUSDT-1h-2021-10.zip 78dacb5b135d357d128bf279813df1b70f3f6a2d1925f7f8a82569277714f78c ok 35801 full
DOGEUSDT-1h-2021-11.zip e29ec2e5b96cc8891a81c39cc1bb90836841e29a9bd117dbd2203c19abd5126e ok 34118 full
DOGEUSDT-1h-2021-12.zip ed88cd69397807248e11b5d88452ed234a1bc142ec552659eef9497fef9d8195 ok 34755 full
DOGEUSDT-1h-2022-01.zip 88facccb3ca642e4d35466a9582fdb26daedfbc7212fe8fa96ff92a2955a00e2 ok 34459 full
DOGEUSDT-1h-2022-02.zip fcdc748a12a11532b483764bf2e1c6b16e1190c6f505e6bdea74e2143d057ef5 ok 30836 full
DOGEUSDT-1h-2022-03.zip 9a50c0659470dfe01bd00c289c7911845c9315787770b5a3a7115be051a8917e ok 33568 full
DOGEUSDT-1h-2022-04.zip 2fc52be02b99ba599c1be52948c380df7393001efbe91d7f63a1bac6cb1a96f3 ok 33571 full
DOGEUSDT-1h-2022-05.zip 521c98bd23222666c45d6b160750077d4bb595d6327ed5847a1b929dd649c9fc ok 33917 full
DOGEUSDT-1h-2022-06.zip a0ce87bd06c0e27afbd0500d8bee96b13cb95f4c22ae24b6bf05f2e7f9401cff ok 35375 full
DOGEUSDT-1h-2022-07.zip 394f6821f9116043f254ba84164dba4ee65e78e72da0ee7ee52e833a84f3df6a ok 35814 full
DOGEUSDT-1h-2022-08.zip 3f5d5e8bb08a6f6bf4e65c583106613d192423f3a5a97afb83506171ef894f7b ok 36103 full
DOGEUSDT-1h-2022-09.zip 9208aa1391740c039624c939cf679438c9311433cfd0ea809a916b064578c19a ok 34196 full
DOGEUSDT-1h-2022-10.zip e82cd8f8e4a715343aa51b2db6bfb0364043ab002bf5d269ba398dd66a9e2112 ok 35588 full
DOGEUSDT-1h-2022-11.zip c9ead67955dfaf773030c17a452cb90642748d06f9f7cce04db423fc0ba7ff63 ok 36666 full
DOGEUSDT-1h-2022-12.zip 6bd543de72fe15f34e700729ac89ccc58297c739f739d20c96a33111fcfe270c ok 36340 full
DOGEUSDT-1h-2023-01.zip e2268e2e5e0c4f2f6dfe4c4b266efe1462199d27f2ae30680de9b085246dc7c3 ok 36323 full
DOGEUSDT-1h-2023-02.zip 955e493be9285e91e08940dd85114b9effc150f1409f95c89e34534a7a16fa8d ok 32706 full
DOGEUSDT-1h-2023-03.zip 02ace49d8d4859b18a1c76ae49f123e8bbf7d6bd2f4ec3e0fdc760846398d2d6 ok 35908 rows=743 gaps=1
DOGEUSDT-1h-2023-04.zip 679eb560f012a1ffaf4d4ec6d5c67e5be4e985847922e2167b73e3bf8b609e23 ok 35485 full
DOGEUSDT-1h-2023-05.zip e644ec6833f638b234340eb213399b098bd7f3ad584a5f90ca55e664c9aeb144 ok 34901 full
DOGEUSDT-1h-2023-06.zip 4558abf6d805775018c492c7262087de5134556bb9aea8095ef2a198e3cb6674 ok 34013 full
DOGEUSDT-1h-2023-07.zip b7f300d3230eb92fc0a053c4f486035c2894c80a79feb20f9894770d3ee5601a ok 35793 full
DOGEUSDT-1h-2023-08.zip 78f82eba2cf2973f0718c99de1e7814f3c98517c2bca2ca9c9e37414e6306586 ok 35178 full
DOGEUSDT-1h-2023-09.zip 4213c127128398d1a9f39123f89f63d112b69cc8646354787e2bc341667daef1 ok 32879 full
DOGEUSDT-1h-2023-10.zip ba035b6ef397298a426c18e56515ea3a011df19235cd2dd63ef0ddd58a892390 ok 34763 full
DOGEUSDT-1h-2023-11.zip 41a0d21b18e6e68fb19ecbcd7a59247b01549f7c6ec87814d8bcea4a6695342a ok 35496 full
DOGEUSDT-1h-2023-12.zip 5b9694ba219be166073375f83546859b528dfec5e7f215cd95252aff7de40564 ok 36539 full
DOGEUSDT-1h-2024-01.zip e78fe79bde16446bf807f238a23370e152350918a54245ccac693d7b60954f30 ok 35950 full
DOGEUSDT-1h-2024-02.zip 170a2625ba3f9dda464064f8541cf5d6fc6ff89b7c4c5f6b6cb1d851f1bfff4b ok 33513 full
DOGEUSDT-1h-2024-03.zip a5a9d991a50eeee0e308e7ff501b1147503c910ffa8d355b03bb64edea504b81 ok 38975 full
DOGEUSDT-1h-2024-04.zip 3687f21e9cf02f4483e39aa10d4d4bc712730460d766e0f95d9776d9e5912a91 ok 36904 full
DOGEUSDT-1h-2024-05.zip d654dde92a9b66244713f94cb16aaf7c25b4f18eda9636e27c2a6e0b98735d48 ok 37550 full
DOGEUSDT-1h-2024-06.zip 1494326c6d0743286befcd35ab33cd64568dccb8c1c287c6c58cb4454dd01619 ok 35183 full
DOGEUSDT-1h-2024-07.zip 7b400c33bcd274dd3f88d350bd838108b05472a76445e53fb391af5093497da4 ok 36845 full
DOGEUSDT-1h-2024-08.zip 400789c4b9e8ec19c7f4a1c9f2371e9c407566b766e1eaf9c1282ff7efabce27 ok 36527 full
DOGEUSDT-1h-2024-09.zip 71b1bc2692af1c48f71113f45847f3e15025546d3f07de4d82bec8f1e6057a03 ok 35187 full
DOGEUSDT-1h-2024-10.zip 141feebde550cf88cc5bc73d571d3a8980642ccdc6bcfb87948aed5880fbbdbd ok 37280 full
DOGEUSDT-1h-2024-11.zip 08e12031d541d424e6ed64bdd28e08fdda063fb82c86d27168980f23a4b16b58 ok 38578 full
DOGEUSDT-1h-2024-12.zip de8180d361a49ce9b2906a106823f61f199638dbaa0f02ca1ed1c3916ea2c02b ok 39122 full
ETHUSDT-1h-2018-06.zip 89ca6f4f5f3d7eda63a1e2b73e89137c84de07f64dca9f3137c0b5720a373f16 ok 38094 rows=709 gaps=2
ETHUSDT-1h-2018-07.zip 52e7fc8fcd45d532b9c39c7188e7b0f23c7cd0b1fb85ab9f96a1f769e985d45e ok 39428 rows=737 gaps=1
ETHUSDT-1h-2018-08.zip 08aa5c8650555341cb9a97bb36d224a885f7f43d2639062d86dc73999ba7a8c5 ok 40152 full
ETHUSDT-1h-2018-09.zip 4dc44f74cddfb7fdb4e443bfc5625ddd01a219bd05bf9b828edebb460cad24d2 ok 39154 full
ETHUSDT-1h-2018-10.zip cb5965743f2d34dcbc9e74c838e631d102ded65bbab6af7f9be1f1a47c1d5902 ok 38544 rows=741 gaps=1
ETHUSDT-1h-2018-11.zip c5ec22c135d03b693efc18ee5a800976eeeffa0d77c2018eb4b8001c34dbd261 ok 37852 rows=713 gaps=1
ETHUSDT-1h-2018-12.zip c879eedf9c34e514d4366a521c9270641359128168b493e5e7c1c86fdc47cccd ok 39734 full
ETHUSDT-1h-2019-01.zip dfcb945fc3bb86dbb6695e5c043b6e55cd239c52abd7cabdaa7bafef2c9ddf1b ok 39432 full
ETHUSDT-1h-2019-02.zip 274f269cdb4d5e261776f36dc013dfd894e6708b3ef1716b50e8d35e9e16f6c9 ok 35539 full
ETHUSDT-1h-2019-03.zip 00baadffa3bb44317c2b8b188da4303b486e9c06c042f6ef735755257ad246dc ok 38409 rows=738 gaps=1
ETHUSDT-1h-2019-04.zip 1a71dd3568ff0c875ef870f0023d2a9e7c8cdd7d7b427e373cdddb9b02909c51 ok 38262 full
ETHUSDT-1h-2019-05.zip 147ba87d425554fe66c387c44100f6c6fbf0857d116ebbe16a5854ae5662f2c3 ok 39800 rows=734 gaps=1
ETHUSDT-1h-2019-06.zip 3b51d2c72e8ba3891bb8631d226a5d1610ada0abc8095f7b48de539db8fcd6e0 ok 39069 full
ETHUSDT-1h-2019-07.zip 341560f517488020a87e50c379b37cc2605dbeceeb29a171d8f078186e2ed6eb ok 40233 full
ETHUSDT-1h-2019-08.zip 84a769439af04f0c8413c32f9c8dcfd5a29241b8bcfb389776b296a6b4f8b6d4 ok 38918 rows=736 gaps=1
ETHUSDT-1h-2019-09.zip 4c2f8e47ac294e8f10726273b5a637ed172e98711915960eb5d15e71421d1ea7 ok 38471 full
ETHUSDT-1h-2019-10.zip 546117d59598496fcb3122772c2c9bf45d0c2dd7a25a9b07bd78a9cb83ad677b ok 39685 full
ETHUSDT-1h-2019-11.zip 222067844687455cf1f50022f906eb19eb0001e690378f3c5a12e89dd7bdc721 ok 37868 rows=716 gaps=2
ETHUSDT-1h-2019-12.zip c7734b09fafca18a99f4906ba33b34a37cb96b8c0f866e6b92f9e951f99f5b8d ok 38826 full
ETHUSDT-1h-2020-01.zip 9e0ca4d30bcb22d5c876b912b3160445d2410634d09e9584060f592c30a06402 ok 39551 full
ETHUSDT-1h-2020-02.zip 1cf8a5b129d16bed072c46e158b5914247007ec7e00b489880f422c80c73afbe ok 37876 rows=690 gaps=2
ETHUSDT-1h-2020-03.zip 2d80640a11d7de0eb052637d25aa95eb42602a927ad7c0be6d77a7689fbe93d3 ok 40856 rows=743 gaps=1
ETHUSDT-1h-2020-04.zip 0171b734b6131a542d79e35dc2ffbf886c1353574ef0983e95c4a8eb2856e56a ok 39174 rows=718 gaps=1
ETHUSDT-1h-2020-05.zip 4a02d33138486434643a314ea561e274f95c9d93124763d15cbf18bf809ca771 ok 40466 full
ETHUSDT-1h-2020-06.zip d605f9ad1cc5556cfef7559f2d9e5cda0e55deba7f8ec03ea253bf8ec2f99d81 ok 38510 rows=717 gaps=1
ETHUSDT-1h-2020-07.zip 3a740ceed16217e109224e01ca0ce552d241bf39045d82d29f69e61f13149ff8 ok 40313 full
ETHUSDT-1h-2020-08.zip 2b50f4e13ad28b1502cb99abb6e2d71048a46f207ecbd02aa4720ae1e451f703 ok 41392 full
ETHUSDT-1h-2020-09.zip 1bbbb6fece1ff1f5ac8b42b8073686bc1e05e1cee404f453843a5cb5716d3a95 ok 40089 full
ETHUSDT-1h-2020-10.zip 7dac6824ff1762f704b9cd6becab4282ceada67be26f0466d378341c41db0ea2 ok 40737 full
ETHUSDT-1h-2020-11.zip a1b583dd091363fa1375bced29f78f69889c6da219d1c136b9d0f9269a19158b ok 40447 rows=719 gaps=1
ETHUSDT-1h-2020-12.zip 3928cbf56a66752d619eb438b92e0bc8cca2c8f0420237e5f5e81fdc19db13ea ok 41720 rows=740 gaps=2
ETHUSDT-1h-2021-01.zip 01d6bb8175fb847a256ca1cc14dce06194a86c740d7edc951a5d2835aba9b577 ok 43823 full
ETHUSDT-1h-2021-02.zip f2e871ec862f36045bfa06a05210832d6b772a101a62b18bc7acddf906083b44 ok 39318 rows=671 gaps=1
ETHUSDT-1h-2021-03.zip 64d15bc69f1788ccfa775cea47bf2f614a2ccb4eccf66257f512c8cd99d497ad ok 43093 rows=743 gaps=1
ETHUSDT-1h-2021-04.zip 299b928009158743a92860a66c75ba898243ecbdfa8ef9b346c0a7fd553bcbff ok 41907 rows=715 gaps=2
ETHUSDT-1h-2021-05.zip 56707e7dbceacc194a6ecd31ea2b2a75a5c5f428182e63055217188c7e47c89d ok 44688 full
ETHUSDT-1h-2021-06.zip e5244f5f095543d47d24a617c67292cf5daf95cc403407f5fff2fbd394580512 ok 42407 full
ETHUSDT-1h-2021-07.zip 7048eb9eec2a091a3550f16870b93165eb21885ba6e217dac28682aebf248241 ok 43318 full
ETHUSDT-1h-2021-08.zip 9e390848fe76625e72b8f4eac86d405ed33c79ca9d79d9af14266c54d9d215af ok 43105 rows=740 gaps=1
ETHUSDT-1h-2021-09.zip c10a61248a5c92280e35beadcfdf33220fdc0561ab1973893a4fe5a3335d3b78 ok 40803 rows=718 gaps=1
ETHUSDT-1h-2021-10.zip 332cdaac0de88dd2452c0ed2561f86e99ebba6f89d9db69b35aa9f52acafe805 ok 42076 full
ETHUSDT-1h-2021-11.zip fc8093a34678bd6ce4436c411127a69f245b2d5cfa6208aee67ffda504a70664 ok 40833 full
ETHUSDT-1h-2021-12.zip 7cec67435b94112e7d1a8ec45b4d0167735102d12cb8649699aedf5018b09a80 ok 41944 full
ETHUSDT-1h-2022-01.zip 14a3875732b7e404be2522aec94b5f17fc43f81e77c0a68fdd72980ea644ef5a ok 41862 full
ETHUSDT-1h-2022-02.zip 2c155824e909de8c1f91a41bbdc2356c29f3c16944db3982a7c912ff58083eb3 ok 37936 full
ETHUSDT-1h-2022-03.zip 9af5cd5120e2942f763f0a45cec35b0a98322015d52b29884655875f8bfe361d ok 41670 full
ETHUSDT-1h-2022-04.zip d47fd9d00967d87564a52cc7025960de98513f863a83018e9f9dd0eb5875df39 ok 40240 full
ETHUSDT-1h-2022-05.zip 382390f47d0660bb3dc16aaedf7901002a2293ca7a375045b08d956208c95615 ok 41837 full
ETHUSDT-1h-2022-06.zip 9fd8dabf04723354423f643b62b74ac5f1046e28f855c0e15d9eb68b5e49f559 ok 40835 full
ETHUSDT-1h-2022-07.zip 87c81755af5e05b5b24182eed98582284b6896048d231a245581d76df669d4b4 ok 42054 full
ETHUSDT-1h-2022-08.zip 7792ffb44dbcd7a9964ea796ffc2dc2049b5437a5a317c07b64eb4be8aac1a13 ok 41777 full
ETHUSDT-1h-2022-09.zip e64c3e782b8421fa035843584bff1ddcdee84ee1bcb06d6e154915855d6917c4 ok 40195 full
ETHUSDT-1h-2022-10.zip e0e1d08f8e089a0273e2ad62ad052b690d4082c82bf56da6f7b2c37795e2ab6f ok 40772 full
ETHUSDT-1h-2022-11.zip 109c93bc5db33562650e146c9a9332ec4496dae5021cf942f5c75317c75d16eb ok 39897 full
ETHUSDT-1h-2022-12.zip 6f704c3ed1be5ce404b5ca53e733e42b005308714218ff9e21d15e7cfb128f01 ok 40023 full
ETHUSDT-1h-2023-01.zip 6a646f674ecfa736db1e6fd0c4ebaf26594806efde851f2c7081aec533714e3d ok 40509 full
ETHUSDT-1h-2023-02.zip c23f2ce377caba0279a932cfea93701bd02c996879293c5c395eaba06a943039 ok 36954 full
ETHUSDT-1h-2023-03.zip 90d268be1e0d39f7411f88ca3c0f21fe110fee7ff3c1dd054555e1fea6e22d8d ok 41120 rows=743 gaps=1
ETHUSDT-1h-2023-04.zip 36598c7b9ac93706b8c9f9e6da11bc2137f605c442dab139ac35e397efcd9473 ok 39687 full
ETHUSDT-1h-2023-05.zip e03f762cd90b9a4eb6bf3499a05f4df84a71fd23f18d8b1b9c2e88eb469b0f2e ok 40460 full
ETHUSDT-1h-2023-06.zip 7ca4b8f6f6ff04f6899fe49b68df2c7b60841dfadb4a334631491af2d192bfbf ok 39155 full
ETHUSDT-1h-2023-07.zip b141e7b3ec07f24756b1c5c27b562acfe06d331678a49c493a5fa2cba44eb97a ok 39931 full
ETHUSDT-1h-2023-08.zip 25930d0ba8280ec82b879d130071582c3ee4d5a1fbe31dc34c016b2c314d3525 ok 39655 full
ETHUSDT-1h-2023-09.zip 3453dc6570a7193ab358e5a4c592439b4073028b1ab09412610d9409cf330219 ok 38385 full
ETHUSDT-1h-2023-10.zip d91229dd47c4cf53b8e326b500295a4fb9f0316faca0e2149076065bc53ae049 ok 40238 full
ETHUSDT-1h-2023-11.zip 2be46057e4a5b40b4b7c6bdf5b163aa22e353048e62907e730cd471fbf3a62b5 ok 39562 full
ETHUSDT-1h-2023-12.zip 89ec0d0b4f4ee72f4f1c2fad52ec1d94435d525bb107ae23d6f9716c77dbc428 ok 41082 full
ETHUSDT-1h-2024-01.zip 1fdb3a8fa6b77ef30ef17ed4b71b184172ef1f812d83bd0f50bbd08e71a92057 ok 41245 full
ETHUSDT-1h-2024-02.zip f080ff288b2f7e85e78c5370a8a3258b93f85531ff96b4131c1b7889649a8ba4 ok 38782 full
ETHUSDT-1h-2024-03.zip 4eb16ab0c5db15e5e0d77827f5c19c215c7ce601a5501d9563b75bda7602f46e ok 42083 full
ETHUSDT-1h-2024-04.zip 8b710fad720ae0bc75eaded37b3add95ca49122ae398f3f6e33e57e864da781e ok 40291 full
ETHUSDT-1h-2024-05.zip 0307d64f0d9ae6ff4001442a014d7b02dcbc5a003dcc36ba139f1c9695996b51 ok 41346 full
ETHUSDT-1h-2024-06.zip 59ee6920bd72d93d1130c89711c93ea192bbfd5f82b548dcb0448f66450f6a06 ok 39586 full
ETHUSDT-1h-2024-07.zip 83181cfcc1f1e32a542e2c220cbd58acd1c550cc64ad1e2c414e47088266aa7c ok 41340 full
ETHUSDT-1h-2024-08.zip d908255a48978f6acb769c4b856a3307c58a8c19dbf2b3b7f10067245d5e8b89 ok 41335 full
ETHUSDT-1h-2024-09.zip bfbdda97d03abac469199120ec3c2f1305e2d5947e9155ff84dbeafe33cd4a67 ok 39572 full
ETHUSDT-1h-2024-10.zip cbb13664485b6c9a6365da7ae23299b722ab5926a6aed516add486ef501883bc ok 41095 full
ETHUSDT-1h-2024-11.zip 29cd30419b86d5dff5467a7a81d43e492aaaeb3669db216ab8badaad5fe610ec ok 40916 full
ETHUSDT-1h-2024-12.zip 84312b7dc2b5c903853c78d94f587ef1d24b7960d7bd95f5bfe3afc3db006203 ok 42106 full
LINKUSDT-1h-2018-06.zip missing
LINKUSDT-1h-2018-07.zip missing
LINKUSDT-1h-2018-08.zip missing
LINKUSDT-1h-2018-09.zip missing
LINKUSDT-1h-2018-10.zip missing
LINKUSDT-1h-2018-11.zip missing
LINKUSDT-1h-2018-12.zip missing
LINKUSDT-1h-2019-01.zip 2a32a06d7b0380c5873940ea7538ada7c0d94d995a91af7573bc962ed058e5da ok 17120 rows=374 gaps=1 first_open_ms=1547632800000
LINKUSDT-1h-2019-02.zip 77b04e82a0f818d7b92038dbe9735341e9c511433a1f1da2e4a76a3c3d12e0c4 ok 29887 full
LINKUSDT-1h-2019-03.zip 97bd872f9adea9d5e548f9ed6539fb13845e14510ad6368bd0a76600fb2a51da ok 32777 rows=738 gaps=1
LINKUSDT-1h-2019-04.zip fc17117d265b7863b73e1ae9135aa2db64f61fbfd8ed7cd9db1f065a2f6bf25e ok 32163 full
LINKUSDT-1h-2019-05.zip 870e740ce5dbec43630e4d36cb9fd28129e614633750818ed37a494e61c7bda2 ok 34870 rows=734 gaps=1
LINKUSDT-1h-2019-06.zip 8fb606d14022797fe0f10d95ba65206d576a2365177fe065f05060ecfca42ef1 ok 35826 full
LINKUSDT-1h-2019-07.zip 6aa4fc178c790e57a8e4681ec367b1e158e1d16ae8b18f135f0b7c0cab3f3c1b ok 37400 full
LINKUSDT-1h-2019-08.zip 29a7329f4fac22f3fb83bfb1cd77a6063391d336f85943e55a22dc15648a263c ok 35954 rows=736 gaps=1
LINKUSDT-1h-2019-09.zip 2d9cc516628ce1af7f0f6b6b8025b7158d76452ff7efa4ded4bee13870602039 ok 34881 full
LINKUSDT-1h-2019-10.zip 0594e49acd1faf14ab6334cceae42147decf7cebd82257c01c3585119c3a3a2d ok 37254 full
LINKUSDT-1h-2019-11.zip 72a0deb6a22ca5119c82d6bc9af191bfceef85f26524d2c535e1a717dcc5aaa2 ok 35118 rows=716 gaps=2
LINKUSDT-1h-2019-12.zip 4e34fa322de66a667d1f7b2939ad7a565327efae51b10d3eb52846f5ff7ec4da ok 35858 full
LINKUSDT-1h-2020-01.zip 8bbaf6d9e92f17075eb1c2c2d361bbcc99739920ccaa07dd05df13dd74415882 ok 36483 full
LINKUSDT-1h-2020-02.zip ccfe1bca73f58814ae076531127f9c0b26d6a0a69425f7afcc849e9c242aaa77 ok 35407 rows=690 gaps=2
LINKUSDT-1h-2020-03.zip 83024a236e1cb5fe510f8454b7168911e5e683a96a573e4e7f286d69c623d3da ok 38590 rows=743 gaps=1
LINKUSDT-1h-2020-04.zip a6f810f89cf4e5c5eae04d8e9b59462e5856349c4c1e3415ca883227caa8a610 ok 36812 rows=718 gaps=1
LINKUSDT-1h-2020-05.zip b379b72b8942af38027bb601266fe245e7b1338c787db5acfe7af864bf5d2ad9 ok 37416 full
LINKUSDT-1h-2020-06.zip 35f80865714564df185703b30c442671941b6243b242af6b8cb0ee0ca0cfab2c ok 35657 rows=717 gaps=1
LINKUSDT-1h-2020-07.zip db336706c4cf37aee254f880c1efa846f5a2ad96faac56503201df75281920e3 ok 38794 full
LINKUSDT-1h-2020-08.zip 50a722f1e7d367ad62450db8e8999f2b563f77faa0d4e3a3b30937e8a4fd1d0f ok 40232 full
LINKUSDT-1h-2020-09.zip 3657c6e8d3432426e5f5653a04a0312ba72a40485177a5fdaf13e65c86129361 ok 38495 full
LINKUSDT-1h-2020-10.zip 5d01f7172939911b96f8f51acd9033146a53f85754ff492e914387966dd133b7 ok 39096 full
LINKUSDT-1h-2020-11.zip e95b305d7d3f03f919ece434be6e63c8c6b58a21a462cc1c20c93645a4288ba6 ok 38496 rows=719 gaps=1
LINKUSDT-1h-2020-12.zip bc974b49e81feae3e27e5a21f70ea60872bb4b40e6b5fc422d96fb2446b99c55 ok 38997 rows=740 gaps=2
LINKUSDT-1h-2021-01.zip 84f5cb9004a29d318fbbba80c318626f7e5057449609b6825851f933005b1ba8 ok 40791 full
LINKUSDT-1h-2021-02.zip c9f104837f1b74f27c079ee4e2e90efeeeba7e89e89c3824a969300671704190 ok 36705 rows=671 gaps=1
LINKUSDT-1h-2021-03.zip 67772529781940d76ca74ecdce8f034cc17d18ed41b8278e936cd191624e947d ok 39728 rows=743 gaps=1
LINKUSDT-1h-2021-04.zip 54aa1132d22715ada63d6ab598666322a1e8483a9749fa664a7edc07dea8a550 ok 38978 rows=715 gaps=2
LINKUSDT-1h-2021-05.zip 2fefbde92344e02db9580afda4b552bc7a56bfb0620b19666d80d81ba60347f4 ok 40147 full
LINKUSDT-1h-2021-06.zip 9d9ece6b5102dc6b214c133dd8d064ea5815063a675ad973a75ba5aa24daa265 ok 37811 full
LINKUSDT-1h-2021-07.zip f20f6b1550b58d1e1ad79a26a42c21aa7ad1ca843229d1d405a479893763df73 ok 38217 full
LINKUSDT-1h-2021-08.zip 2cc2c50421c90f1c7c5c861b8ea870be077b3555f394ea0030188034adb42caf ok 37890 rows=740 gaps=1
LINKUSDT-1h-2021-09.zip a5c8f039fcb54bfb727f24a358ca830375b036c11efc8cf1479647da81f0dda6 ok 34249 rows=718 gaps=1
LINKUSDT-1h-2021-10.zip 73f07c095711baf09fcc0b318d827f96c2f7c38f72f8e2d85c5faa4056c5dce6 ok 34866 full
LINKUSDT-1h-2021-11.zip c6f696abb67542cb1a17adb7c2f97a3b0ab8be95f67f4188bd61c16ab77b55f0 ok 33701 full
LINKUSDT-1h-2021-12.zip f392d562afa3caa6096ccbc39b27360f5a0b1814f3f93ff3977dc0b90fe2d49d ok 34666 full
LINKUSDT-1h-2022-01.zip e175720debbde2715fadf1764ba3befee542a7aac28c03bc0a8afeaf7969263e ok 35203 full
LINKUSDT-1h-2022-02.zip 4a56550c4c38117e5144643a598dc5178f7ba3307fe98e1b97101b126ce5e3b6 ok 30860 full
LINKUSDT-1h-2022-03.zip 451635e223e3ca61a8e69542fbfc6622bf1c3d199b7838662107a40bfe558d24 ok 33719 full
LINKUSDT-1h-2022-04.zip c7f9b42a7b3d0d89db2b632b35f5411b9b5679a5c2f076556bfa763a23d30af1 ok 32060 full
LINKUSDT-1h-2022-05.zip ded10c8d5d9467288193547c75f80bb360e257539a70140769f711915d5804fc ok 33465 full
LINKUSDT-1h-2022-06.zip 6bcbcdecf621b21f56cf89a9dd7a56d8b9571078a03ba400896d5683cec42f8d ok 32811 full
LINKUSDT-1h-2022-07.zip 4aeb499146fd8d60e27b8e9eb7ab6091960cfeceb7008513002f6b68c3352a97 ok 34575 full
LINKUSDT-1h-2022-08.zip 38e7cfec7db4b001b210ec08ad87029a5eece1854236adaa831c623532b87bb4 ok 35676 full
LINKUSDT-1h-2022-09.zip 55b88696abb180769f83c0ea1d41a6cc3d560d7a0cccbfd5490928b6096ce8c8 ok 34719 full
LINKUSDT-1h-2022-10.zip 6ada8dbf3efe06bce441c5586523942a02c0d0f6923ab094bdc24af0a8606765 ok 35142 full
LINKUSDT-1h-2022-11.zip 36cdd0281fb2d2d35bca060f97e450b018fb195f93b62c1cf7edfa1e2ca81331 ok 35177 full
LINKUSDT-1h-2022-12.zip 37153bc0c583e905d21a9475ecaaaa0e8456560c361eea2115f2688d62f0b657 ok 34646 full
LINKUSDT-1h-2023-01.zip 67ab94f8ed330bceaf5281730ba18b625443231391484e06ec1c806d9572971c ok 35140 full
LINKUSDT-1h-2023-02.zip 3e1f995c0739dd18a90898dd548e040f76e721f19720b27d30a66b0246c73a1f ok 32131 full
LINKUSDT-1h-2023-03.zip 1402b8c7068945f51d84293ce15626b4d2721510322214d34ab6f50959a6e229 ok 35363 rows=743 gaps=1
LINKUSDT-1h-2023-04.zip 856b36e5fb904c9b352f6bc8069c20ff848df5735b84600062038e2d03ab274b ok 33985 full
LINKUSDT-1h-2023-05.zip df807f085376fe7ab69b746f55325f372225612007785f4b6919c5c974fb85ba ok 34078 full
LINKUSDT-1h-2023-06.zip da3eead782447a5afc15991ddb5042cacc978f9a887f8c1c20f78a6567efd665 ok 33598 full
LINKUSDT-1h-2023-07.zip 39dfc47fffcfae0ec1d8a3c2a76e4e85f4e8530eefc0c64da9a0b91ff5fee29e ok 35023 full
LINKUSDT-1h-2023-08.zip f09a2535d77883a170170384de91de3c8e4c9013ba7d024ecb74f61eac9f8455 ok 34642 full
LINKUSDT-1h-2023-09.zip 394c2fd04c3da621ad28cfc089f69cb319f36170166735e3642d95ec08749f2d ok 33754 full
LINKUSDT-1h-2023-10.zip 0ff89ccf6bca3b422f411b35490612e10e71ba8fafb60c4417b4a60b42b448f4 ok 35777 full
LINKUSDT-1h-2023-11.zip 34dd10448bf4d6ecb6bb8494ac9c2f42b1ab36305e5ed33300e52656d2ceb2c9 ok 35774 full
LINKUSDT-1h-2023-12.zip f74f19c98fbd135ff3153c7411e76cea97f87035fb9c546960bacb7308ab73f2 ok 36654 full
LINKUSDT-1h-2024-01.zip 6b51a1a3515f1ed10c163301a05a67b1d6418edc1ece5126d62413bf79af2239 ok 36530 full
LINKUSDT-1h-2024-02.zip 464d24506b15009111d3fd0b35135980d3aa5b2820d689853776420866872b23 ok 34409 full
LINKUSDT-1h-2024-03.zip d9b858bfdb71d4dc214b5ef7c2e7fc06c0fe7eae20f87359d0b319f699e29c97 ok 36730 full
LINKUSDT-1h-2024-04.zip 87d33c5eda1744fe52a88de1c0c1600b9ab9e44e8654722369b9e4fa451d6546 ok 34960 full
LINKUSDT-1h-2024-05.zip 5e855c04f61be1c705d18b11e52bd93edcea7400f5f577876525c9479fcae1bf ok 35929 full
LINKUSDT-1h-2024-06.zip be103fe4dc46059d51efd8564ca444342a05f62042c530ddd4908753ffc30217 ok 34350 full
LINKUSDT-1h-2024-07.zip 8df65ec85239a360a08742d6545ecf9088318f80e3c3bd302406071b5791542c ok 34751 full
LINKUSDT-1h-2024-08.zip 8c7e1b50eba0c2aa86157c509830509b4e6b4cbf275fb4e0c59586265a0fb71b ok 32644 full
LINKUSDT-1h-2024-09.zip b911cb9ddcd47aa5eeff1ac8474565625d72f333c20c5e26e9c602963e3f22c1 ok 31453 full
LINKUSDT-1h-2024-10.zip 95a4cfbcc3a99b0772e36c9d70e1d6ad10339e5a7beaf07d46f5b87fd814913c ok 32792 full
LINKUSDT-1h-2024-11.zip 46330477ee33935adfe21766e49ca6a23a02022ba2c7ebe38adb95827f607b68 ok 33201 full
LINKUSDT-1h-2024-12.zip ec977e8140a0c30a0df1b20917143c5005f5beacdd7a683f1d68f48aa2bf0d99 ok 35529 full
LTCUSDT-1h-2018-06.zip 533fa9a223bfde4fa028465ba02c9e5ec10c07eda79b0c30d12681cd9ee751bb ok 36052 rows=709 gaps=2
LTCUSDT-1h-2018-07.zip eca51ae8280fecbe16b2e0c51daa0e45856e7675e75f461839caa8845bf50299 ok 37308 rows=737 gaps=1
LTCUSDT-1h-2018-08.zip 5cbee9af0babae663314ed9c8ee9081702dccdf96b85ed2b259bae7b9f775a8d ok 37440 full
LTCUSDT-1h-2018-09.zip 4e1ebf3dcefbd3b09b68f6991fac4673fcffd332cccdabb3641522998b9c1fea ok 36669 full
LTCUSDT-1h-2018-10.zip d566772e09330d4ef6a0b07bca9d46848a4d5e9ac8c1c3645e8ed1669720790d ok 36483 rows=741 gaps=1
LTCUSDT-1h-2018-11.zip 7862b617bd38f406b7635448e12c44a5b2f397f312ea5662a5521b3b7ec3aa3a ok 35598 rows=713 gaps=1
LTCUSDT-1h-2018-12.zip 309ee69ccf09a01f86de5da1ee05200f8ca13534619c7fe6dae7a2d0ed6591ff ok 37267 full
LTCUSDT-1h-2019-01.zip 81b5a22d8fb7bcae5921f9c57ff618217ecbaee1b13cc7d023281d777caaf7c6 ok 37156 full
LTCUSDT-1h-2019-02.zip 1c097f3191b9615bd3560afbf448d84227b6bafdcbaba9d19f7024ee33ae79ca ok 34222 full
LTCUSDT-1h-2019-03.zip 95385059757194d963a23de6e58dbf533d87b757e6f94afb82add83fe39344f3 ok 37390 rows=738 gaps=1
LTCUSDT-1h-2019-04.zip 3122df3b00923b3dd2cbe2eceefb1906b90094546d5f42171e24025da67ccc86 ok 37408 full
LTCUSDT-1h-2019-05.zip dbc05b2104581a75142d2827d6d5611688a5f70e77c81e151a5c7f1bccbbb5c8 ok 38742 rows=734 gaps=1
LTCUSDT-1h-2019-06.zip fb96987af6d4d722533d2da87def633ea7631f604fc0f008ef004975e987888e ok 38279 full
LTCUSDT-1h-2019-07.zip 8956ebb08e298c430e2b777cc4b6e0d8768efe7db9f7dd404a4ced371404cbf9 ok 38944 full
LTCUSDT-1h-2019-08.zip 93fe59583f76016a5e574ebac22832adacda5950d41f2fc2bc21f888a0b94b90 ok 37699 rows=736 gaps=1
LTCUSDT-1h-2019-09.zip 78f90b5fb3fb1324c9e28ab05bf3e20039ee1f86c2f71f58eeddc7b257aed1f0 ok 36896 full
LTCUSDT-1h-2019-10.zip a04c74194f88e4d6c39e2ba008353aa53d5bc28542b587dc98550a4788809bc4 ok 37877 full
LTCUSDT-1h-2019-11.zip 35a07f6516314a091ad8a9cb0cfc6001e7f17525db9f4dbfab171101db14c03d ok 36534 rows=716 gaps=2
LTCUSDT-1h-2019-12.zip 593a377117f6aae0e7ccd77bfb52f4e537fdbd4e702e565919465c7d2387e1cf ok 37114 full
LTCUSDT-1h-2020-01.zip fcd4d0ea6343d095a4251b017adf04b00ef71140f361e5b090fd52c53e5f20c0 ok 38508 full
LTCUSDT-1h-2020-02.zip 3947231a23fc83b3b6554dfc045de83b9b01077bb3b955333f11681247f4186e ok 36545 rows=690 gaps=2
LTCUSDT-1h-2020-03.zip cdc6e26a58d02b36a4908dc6d43085dfda8d7480b83ff3d0bc7847a818540137 ok 38876 rows=743 gaps=1
LTCUSDT-1h-2020-04.zip aac386476b4be08b4843f2c5ea3c0398e12774eabf0baa17e29fac1e59a36195 ok 36950 rows=718 gaps=1
LTCUSDT-1h-2020-05.zip 5972dce8761dd1ef752ae287fbe91eb8799cde119bf5ceb7471459cc3c82afbf ok 38029 full
LTCUSDT-1h-2020-06.zip 58be7ef80a7ec8ba0371f27f065190a82ceb2646894d3fb0f8f90944b69961fe ok 36009 rows=717 gaps=1
LTCUSDT-1h-2020-07.zip abb7614fbbaf30c067194e07233b171576bd88d52f66c607f94e2d89fc50e24f ok 37694 full
LTCUSDT-1h-2020-08.zip b6c00d2ab21f981d683717bb2903cbedded26811b9ea8d4049006bdd37e527a2 ok 39054 full
LTCUSDT-1h-2020-09.zip 32ea21dbe093b323ecd2117a6d1f01a739dc2db4304ba3ec5497e46a6c820a54 ok 36866 full
LTCUSDT-1h-2020-10.zip 8eefe393fe88eaddf1ae999ca7c8eacb89ffa430e36f0229a083b83b17dc9719 ok 38177 full
LTCUSDT-1h-2020-11.zip 6b4b93899e63d87ef5d8cabc65e0d0cfe089f3be2171508db556a944c331c277 ok 38676 rows=719 gaps=1
LTCUSDT-1h-2020-12.zip 40e81bd5f3db19355281ac854ff32bec7ea12edae6737c8759e245e66e70ab7e ok 40545 rows=740 gaps=2
LTCUSDT-1h-2021-01.zip 642062570108e0548d04e8a7919f4a77df5f8eb5d645b70b5f890ef6d7aa4294 ok 41429 full
LTCUSDT-1h-2021-02.zip b2c9f8eec684488469d7c01110ab314f029782739b8555c41119f4f9db209011 ok 37699 rows=671 gaps=1
LTCUSDT-1h-2021-03.zip f61dea2032da0f79b1ac43ccc4670d92a95dfbd8423ade291e954cb555dad743 ok 40919 rows=743 gaps=1
LTCUSDT-1h-2021-04.zip 0e2a358866f150f414c36a8a9ec316a45d8c0e849018792038f64d3dc652d85a ok 40222 rows=715 gaps=2
LTCUSDT-1h-2021-05.zip 1aa462b92b56938fb2acb8bbb74c36196adcfa53e7c7284d53a62e9f45bbc698 ok 42386 full
LTCUSDT-1h-2021-06.zip be8bddedd584a84edfe39ec5f6fee138a424853827a056ea0a57162af190e24e ok 39404 full
LTCUSDT-1h-2021-07.zip 52d5957a5435ac5f7778f93d3bf0a912ad0301f343e1416606125494c2f4f2ef ok 39732 full
LTCUSDT-1h-2021-08.zip 496b4d45cfa44246d21520028f50bc976b554eaf31602e330600e90648fdbd8f ok 39277 rows=740 gaps=1
LTCUSDT-1h-2021-09.zip 49a78fe70f766ca2963601b0ad5cb4d28e7da0837fd8b7b3fa7d74e61cfee5e9 ok 34106 rows=718 gaps=1
LTCUSDT-1h-2021-10.zip 8b7a5b9b5f4521240a8660ec0791246f72d3524ae4ad3aef16b13f1f93ae3125 ok 34716 full
LTCUSDT-1h-2021-11.zip 1e40819b58a25c9061ec97fc71404e588d7b328180ee109d06c9ea610275ab46 ok 34675 full
LTCUSDT-1h-2021-12.zip ad3840b810283687ac0f4871530ae0267ed01f29ce6f5f6364217cd6bcf8d8f7 ok 34543 full
LTCUSDT-1h-2022-01.zip 3a9794415a86c3e7f9fb64506d7f68c6e0fff6eefeaa8a6a6e944cd4c2d868b0 ok 34147 full
LTCUSDT-1h-2022-02.zip 1858d0bbd5f1ed4e11328187a1f83bd206e3c799b40a8df8ad2f0e54ed4af0f5 ok 30995 full
LTCUSDT-1h-2022-03.zip 1854a03e7dbdce45f55ebe22b7f33e9c4c87c674d86a0d3b57c7751dce86b6f0 ok 33720 full
LTCUSDT-1h-2022-04.zip 8167347902d9f416ed7ed164a3fa62d900ef0d1a62e011903b6d737e1c9f5a17 ok 32183 full
LTCUSDT-1h-2022-05.zip 5d34f20edbbf5accb7638b585d5dda472543a252c913f5258a04a21c7b5adfb0 ok 33817 full
LTCUSDT-1h-2022-06.zip 0f092d78868513cfc6a95e082953992364de16ca001c25a77e6810fd4d5afc2e ok 33880 full
LTCUSDT-1h-2022-07.zip a409659bef4d8bf70f3b891e9f2cc74f713252ac957ae1d494a1927f273ffca0 ok 35444 full
LTCUSDT-1h-2022-08.zip bc5832e0cfdb42328ec45a9257600fc27f4b984aa8469da3ca047a1db86829c9 ok 35344 full
LTCUSDT-1h-2022-09.zip d26bba7a68e8ee6d68c2a1e479e6b53255daba21e5150aa052aeaff49b63bb41 ok 34416 full
LTCUSDT-1h-2022-10.zip ec82cc7b50b83a3978bffa178f562b49b391dce386fbf7c3b90317cb54faffb9 ok 34461 full
LTCUSDT-1h-2022-11.zip 5487333e47823fa73235add9f52f4510658e1f322179ba911f9e42815aa6500c ok 35501 full
LTCUSDT-1h-2022-12.zip 1df478e5dfa58d8621f58d6d3e83729f40a009e547d97a716fd80f6b386ca5d7 ok 35691 full
LTCUSDT-1h-2023-01.zip 8274e95f747c09e8572f2b82a0f9cf83107bf35021a9ce52a49570f9d5ae5be9 ok 35943 full
LTCUSDT-1h-2023-02.zip d5fb0a883ddeec1edd671020d938a575ce17f60a7dbbd9f5fe9dddf44d942a5f ok 32421 full
LTCUSDT-1h-2023-03.zip 5bff0aabf51ebfd217fcf43554bc800fe986bcaac29b62f38e5d2901464a7610 ok 36400 rows=743 gaps=1
LTCUSDT-1h-2023-04.zip 0d064be091fe9d0bf8ba464547c7b308da967ccbc16f262c9cf3631971e6011c ok 34777 full
LTCUSDT-1h-2023-05.zip e76604a9576263a64741c26859d96f913f0094276ce54fafe690d0443330d19c ok 35824 full
LTCUSDT-1h-2023-06.zip 761347afb2e4d99d376bbb29a633934345c43702aa70df14f6d0b1c5cc24045d ok 34923 full
LTCUSDT-1h-2023-07.zip 189cdd64a6a086e07a8f295146b0527eaeb019a505394104d51dee087c00bb54 ok 36174 full
LTCUSDT-1h-2023-08.zip b6e7eeba84992fb4a51deea895642ce4946b3ae7ae21dded0442dadd04d56953 ok 35319 full
LTCUSDT-1h-2023-09.zip 77d3467fc451be1b734e15ea319f7e22d57acece06a101bcca992ca25502ee0f ok 33632 full
LTCUSDT-1h-2023-10.zip 17eb8956bd6da099a87badad8fe9f4dade02f4eebc340c7a1195fe7290c30f31 ok 34771 full
LTCUSDT-1h-2023-11.zip 1101148d0cc2d689297f140dc14443ff75ceacb04ff0da15268e0f7aa1256410 ok 34271 full
LTCUSDT-1h-2023-12.zip 749a7f2f87c7899536e44169855fd90e024907fd119a228db593298c4192996f ok 35463 full
LTCUSDT-1h-2024-01.zip 3e1f6528cbb332217299c7680695fe38dfeeebedcdfbcc2afabbf298a8d3987f ok 35469 full
LTCUSDT-1h-2024-02.zip a424af8884ee0b62ee995fc22300bf42ce39ae349a86a6d2b84d504f89aef55c ok 33053 full
LTCUSDT-1h-2024-03.zip 0bc58cdd72250228cebf36930360c7a78bc01648e539eaf88ce64902dd035785 ok 36957 full
LTCUSDT-1h-2024-04.zip 50491d3d4f990e442f2f39c4dde466c758553212ebeb84fd30af5d21af4b1c82 ok 35399 full
LTCUSDT-1h-2024-05.zip ffad9fb08f17e39c25ebec05b694832b0f991dd46a27e5e44ffc499ffb6f83dd ok 35172 full
LTCUSDT-1h-2024-06.zip 40d412a612d4802e5f9b2b536197b83790293f4cfb1923df9c1f7428ab108036 ok 33895 full
LTCUSDT-1h-2024-07.zip cfa1c2aa2b1fb47d742b6f2a3f01db275b9d5d4fe71f2820438707fdee2ecc3c ok 35078 full
LTCUSDT-1h-2024-08.zip a0127b390cb3fcb5701f870d418051d1ef34c108b5b98bbb1a34de92028e45cb ok 35346 full
LTCUSDT-1h-2024-09.zip 842c111facb472c619d73a5946e116e83db055f57c66562789697166060d9327 ok 33998 full
LTCUSDT-1h-2024-10.zip fc7cc2e09dc6330296856c3530014278ddbe824dc048f6f9c2e14a6388f92be4 ok 35102 full
LTCUSDT-1h-2024-11.zip bb95fd8e06f8826dce2e9cb9b8cb1f4840fc6ef79e6c9f27fa13a541118f6fa9 ok 35575 full
LTCUSDT-1h-2024-12.zip 9b877c51f01fba9a13dd7b5c97bf5db8da598167f4b6a7d6eeb58d746a16f015 ok 37340 full
SOLUSDT-1h-2018-06.zip missing
SOLUSDT-1h-2018-07.zip missing
SOLUSDT-1h-2018-08.zip missing
SOLUSDT-1h-2018-09.zip missing
SOLUSDT-1h-2018-10.zip missing
SOLUSDT-1h-2018-11.zip missing
SOLUSDT-1h-2018-12.zip missing
SOLUSDT-1h-2019-01.zip missing
SOLUSDT-1h-2019-02.zip missing
SOLUSDT-1h-2019-03.zip missing
SOLUSDT-1h-2019-04.zip missing
SOLUSDT-1h-2019-05.zip missing
SOLUSDT-1h-2019-06.zip missing
SOLUSDT-1h-2019-07.zip missing
SOLUSDT-1h-2019-08.zip missing
SOLUSDT-1h-2019-09.zip missing
SOLUSDT-1h-2019-10.zip missing
SOLUSDT-1h-2019-11.zip missing
SOLUSDT-1h-2019-12.zip missing
SOLUSDT-1h-2020-01.zip missing
SOLUSDT-1h-2020-02.zip missing
SOLUSDT-1h-2020-03.zip missing
SOLUSDT-1h-2020-04.zip missing
SOLUSDT-1h-2020-05.zip missing
SOLUSDT-1h-2020-06.zip missing
SOLUSDT-1h-2020-07.zip missing
SOLUSDT-1h-2020-08.zip 6ef27bef72d1fd9e3aae9d6182cbf87f386cd31890f5fd9541e37659b792fdb3 ok 24309 rows=498 gaps=1 first_open_ms=1597125600000
SOLUSDT-1h-2020-09.zip fbcea2e036e28e112f49e2b2a898a0cfbfece7889b4708c5daf4aff2276394a8 ok 35486 full
SOLUSDT-1h-2020-10.zip 4ff21da911f0557d5f8eedd4bdb3c223ecc7406c87fb1b56bf1bafd7295b5633 ok 35564 full
SOLUSDT-1h-2020-11.zip d745f5ff7ce118031c362899bc42282f838b8b77f5bcef035d4d88e570e7305f ok 34996 rows=719 gaps=1
SOLUSDT-1h-2020-12.zip 791b0facab9d3b94fb8c6c4bfd712391ee7526de3e4ddbe6e1797a7f21d2801b ok 35663 rows=740 gaps=2
SOLUSDT-1h-2021-01.zip ea5f900dec5986dc42bb617b53b5b1fa3e995cb2eedb30b0e4cd97498e8a0e5c ok 37829 full
SOLUSDT-1h-2021-02.zip 4f0d06729fd2601cabd2c3ec63d82552358fa4381479dbf1b3dde5ab927dbc52 ok 35286 rows=671 gaps=1
SOLUSDT-1h-2021-03.zip 36eb5c89019e49fc97477fca9fc2dbc79ccfda91f246fe1b70c6e905ce91f579 ok 38526 rows=743 gaps=1
SOLUSDT-1h-2021-04.zip b642201a82243a290c4b3a2f5c94d3aa5088a631f4b71faac1b81bc373f88d51 ok 38650 rows=715 gaps=2
SOLUSDT-1h-2021-05.zip ae2f4afc892f9b949a9c56f30c1143d9d267c313cfad17ee1dd6d738ffc98f29 ok 39642 full
SOLUSDT-1h-2021-06.zip 6b62bd2c29fe923868ead8ee6ec420a205bac46a3573a384061dd12113c11a3b ok 38261 full
SOLUSDT-1h-2021-07.zip 5caaf512734e089498a1793783f5e91b5df881c625546f57c8b026888cb27ae1 ok 38416 full
SOLUSDT-1h-2021-08.zip f06ca4825d66c1d8faf0294ba6147b17e100175d08b422470d4daeff48243d31 ok 39185 rows=740 gaps=1
SOLUSDT-1h-2021-09.zip da02b1053bc0b6de434645fabff293c41927fc6a0720199eb141deb598a4b825 ok 36292 rows=718 gaps=1
SOLUSDT-1h-2021-10.zip 3293815f4ab92f3ce2146a06c517e0fc62c1baa9273492041617195f56b511a2 ok 36703 full
SOLUSDT-1h-2021-11.zip 577c3127dde0f4869a2195662aeec896a135f686962a172aad42176d9655fba0 ok 35612 full
SOLUSDT-1h-2021-12.zip e6e88ff1edc3a6910df90bbe311e0ec071913bd8673307adb4d4ecf41db4ef5e ok 36348 full
SOLUSDT-1h-2022-01.zip cd070a2f7daeaa33835ca00ab10c371a0bc89c353591c65977706635b7418ca0 ok 35909 full
SOLUSDT-1h-2022-02.zip f6eed394dcbfb8815120c328d1c1e22136e25febb9854ce6c0bbd566c92fb673 ok 32570 full
SOLUSDT-1h-2022-03.zip 8d2e26a84944cf39f343c0b7669e7dabf03bcd7d7afc3e82f6ef2161452f6542 ok 35608 full
SOLUSDT-1h-2022-04.zip 001350cb05168fadc8d1240ae89a37f878f986a78951232191a890f77bbb7bcc ok 34599 full
SOLUSDT-1h-2022-05.zip f68c41a69d18b96d72c9449662cc5c563287369f56033d873f087091db9fb817 ok 35796 full
SOLUSDT-1h-2022-06.zip 4e111c3b8d040f832accab28b4405c6a23b90f33883fa8857ba60ec1d073bfef ok 34446 full
SOLUSDT-1h-2022-07.zip 10a6858a4c66cd1e0ea3e4a4265a737d3114f73062094a75bd48e9c8afd14aee ok 35142 full
SOLUSDT-1h-2022-08.zip a76d0f3bca32a91f4ea923c60c6c87256a673b2a73bdcc117449fc8e4f57ebe6 ok 34858 full
SOLUSDT-1h-2022-09.zip bcba92d96fd85adcf5894674551a3ac52334b1836fcd7b09745c6c2ec70e930a ok 33215 full
SOLUSDT-1h-2022-10.zip c855d5b612c4b362110007383e27c965db324f54ab091ac82cf00b827cab8f6b ok 33673 full
SOLUSDT-1h-2022-11.zip d61c2d3b3ba2e772d39fcc1181973359cd8b59fd1a9b8b29aa8e1dc394d889c9 ok 33510 full
SOLUSDT-1h-2022-12.zip 9f2df163d62154fd641ab95228e6123e378cfc972effea348721317515ddc9d6 ok 32820 full
SOLUSDT-1h-2023-01.zip 24e284cea68c9a42bd6a5bd6cdc2ce56ca00fea106728f36de3d171b215f6905 ok 34669 full
SOLUSDT-1h-2023-02.zip e6c07a992221248893cd519539d2937e241931e1f129206bd13d4197b1f3b6c9 ok 31034 full
SOLUSDT-1h-2023-03.zip 7345fc8807e3e73e11595b5b371bf96d414048f77d1498964fa5c5f8fe3f02e7 ok 34243 rows=743 gaps=1
SOLUSDT-1h-2023-04.zip 89bb7df7673715efdaac4445bc5e7bb980e78469245f6f6baa978d4e7e2a8bc5 ok 32821 full
SOLUSDT-1h-2023-05.zip 8578fd237c61fe3cf535eea93143f094989f26af41cc2d24c813f4836daaeb44 ok 33278 full
SOLUSDT-1h-2023-06.zip 0e2e5c23418ff24a31cbcb4fe95e73db1c7fc90abcf960b86c37b53b3b19c77d ok 32713 full
SOLUSDT-1h-2023-07.zip 7eebf42589b01a086f3be7f2af9a39d1a5df6dbd16f062ae383717725ea008c8 ok 34337 full
SOLUSDT-1h-2023-08.zip 25cb0c865a4bf34ac55dee9cfea5a39d7d9f765c0f7654158086202ff78a9c9f ok 33419 full
SOLUSDT-1h-2023-09.zip 47b3f1869eca8bf460a31570c38ae5ad9eb338773493cad95683cb3d933c05f5 ok 31997 full
SOLUSDT-1h-2023-10.zip 2d4fdfa1fc9b7bcf69382883e472b4ce741cd6470ead4d4bce46c6d263988837 ok 34447 full
SOLUSDT-1h-2023-11.zip 2fb358d1f7fc162236cadb344f21dca8b270e5ef6e88964c9f49a9c3f28b714c ok 34943 full
SOLUSDT-1h-2023-12.zip 8ed8a6482a5538cbcc683f861305f049c86ea09bf0f10cff19a525b55eada4b8 ok 36698 full
SOLUSDT-1h-2024-01.zip f2a90d8c6ed9f666b95e85e048ac4f6ba424c7fe143a982f671ad0b7f0c8cbdc ok 36429 full
SOLUSDT-1h-2024-02.zip fd194ff79e56690fa5bb463b6c280f5c521fb39087c6f4d5fa9c683eb92ca0d8 ok 33893 full
SOLUSDT-1h-2024-03.zip b24ea98ce4ffebb0bc831acd1de8558f49c371ff4774fa31667daa11ffc0dd6c ok 37162 full
SOLUSDT-1h-2024-04.zip ab98165d2c785e871a4614bcb853edbd49b0701a2b3fed1f9d0bf602d128a4fc ok 35891 full
SOLUSDT-1h-2024-05.zip effcd422f7171f6b8fdaec8b8a7bdf9f354e772503569ca648f5a106f82871d9 ok 38445 full
SOLUSDT-1h-2024-06.zip 578fd34d382d7663934a9556c3316a28ac504cffa9a53434b2909f241271898f ok 36763 full
SOLUSDT-1h-2024-07.zip 828f2a8814662d3bcff915eec19fd1771ec996a4a024317fda3f2d2ba61fb310 ok 38488 full
SOLUSDT-1h-2024-08.zip 4f9d4d80f237b67b7038f6d2fc4e131daf8ca65f679359a92ba33574014b1c2a ok 38646 full
SOLUSDT-1h-2024-09.zip 70641e992419a4003519e06094c68b2e13971341e92559e307a38d7215d94b63 ok 36920 full
SOLUSDT-1h-2024-10.zip 3b5d4eb1f9049f8030a01886d2d9ca346da66163fd1fa81ba145fca5fa085edd ok 38281 full
SOLUSDT-1h-2024-11.zip 62fd1843a47ec177849a68faf0a5c33ae11bc33b462f664657a6a68246743080 ok 38110 full
SOLUSDT-1h-2024-12.zip af4ab37dbb738e3ee0c168fe9b55366111e4ad112a905f4740a6efbd810e752d ok 38845 full
TRXUSDT-1h-2018-06.zip e51f870aeca1b2df8d6223da6f48d9e12d48a333c2263c196993755e1fccc3cb ok 22888 rows=458 gaps=3 first_open_ms=1528714800000
TRXUSDT-1h-2018-07.zip eb0a81861bba1cec3b6693d42bb41a0e0c58d2f627b82ea5085e0404e55cc084 ok 36395 rows=737 gaps=1
TRXUSDT-1h-2018-08.zip 42fd71b5bd111cf7623d7d82af3e963b188b40948591368cccd1247ce3859ffe ok 36784 full
TRXUSDT-1h-2018-09.zip 0bd65f6d98f028aa1eac71bfada2fc7daf82bbdbeb731c04eab208e1fccf9b59 ok 35038 full
TRXUSDT-1h-2018-10.zip b155ac817640609c3d7b2425365f1e75f9c454a22cceea30f38e99049068c3c5 ok 35270 rows=741 gaps=1
TRXUSDT-1h-2018-11.zip fb7a7f989abcb0d296db3279dfd5c758098b1ac7234c1f326aa2e0000eea674c ok 34217 rows=713 gaps=1
TRXUSDT-1h-2018-12.zip 2888e4bc3de92bcc5b76a62198931463fef83df5ffbbfa9d9b3737e0fe78d319 ok 35965 full
TRXUSDT-1h-2019-01.zip fc542237c54156b80734cc28558687dd5e2f2ad6c6e2f5032da1d678835ae877 ok 36778 full
TRXUSDT-1h-2019-02.zip 140e89a03f5612c73601e0488cdd62e78de5d1b840f8568fb59a64c0f368522d ok 32062 full
TRXUSDT-1h-2019-03.zip 7c78c14fd9e7516abf22f1f65a32f469b4d22a7f5b781379cf6112dffa3c2591 ok 34346 rows=738 gaps=1
TRXUSDT-1h-2019-04.zip 567099976420afe9ccfe4887cd1a5400c6b49fc00536f6eaa17a866499286af4 ok 34719 full
TRXUSDT-1h-2019-05.zip d64cd3870ddb893f63808312acf972f90b26263e03c3fa20e3ba55ce7e5d6e87 ok 36428 rows=734 gaps=1
TRXUSDT-1h-2019-06.zip 52bc3a3163581ae8a33939c09215461a264891c9f7b36a720a8c1ad0b5a23003 ok 35864 full
TRXUSDT-1h-2019-07.zip bb33f38f67e1ebed5a987495a6c4a8004ae07bb1df8c3ce1b49716674421bc3f ok 36248 full
TRXUSDT-1h-2019-08.zip 2628ad4371e2f1ad75ea0b94773e540608ac7d3d384b8909954b94ae304b7f0d ok 34832 rows=736 gaps=1
TRXUSDT-1h-2019-09.zip 4709f091420b167752cc04d6ae70cb08ab081968fd2c3966580803024731230a ok 34700 full
TRXUSDT-1h-2019-10.zip 36df74eb9a9ab176c3a909b1ec4567decf60eaf21eb59190dc02052a1cff9c6f ok 36027 full
TRXUSDT-1h-2019-11.zip 1c8cb90a0ba2e5f11a9ca980b4646127fa080bfcfedd84de1471266973ce5841 ok 34199 rows=716 gaps=2
TRXUSDT-1h-2019-12.zip aaa593da18c80be17879fb86e5a6101a4e5ae709d75e2dd2b0c48f8ce6bf5125 ok 35288 full
TRXUSDT-1h-2020-01.zip 523fa048a08403ec42c079bebdec481d7974bc121d38238c2aeb687d1eb60490 ok 35977 full
TRXUSDT-1h-2020-02.zip 514267cd53bfadc30ac13c58530fbcbe5a0bb241383397c92c2d855a8af35dd3 ok 34248 rows=690 gaps=2
TRXUSDT-1h-2020-03.zip a890abc13a182159befb9f64615b997ec19f0234efc4fb6680f80ab59ad2719c ok 35846 rows=743 gaps=1
TRXUSDT-1h-2020-04.zip 1239dd565bda8673974c61bd41f967f008798db2679fcbb76b67373806e8589a ok 33969 rows=718 gaps=1
TRXUSDT-1h-2020-05.zip 11f8750cc5aa3d147a02b7427936d981b18d76b671c8cc289e8f8422b75515d5 ok 35325 full
TRXUSDT-1h-2020-06.zip d0a4ad4f2d79e5e3a9eeaffb42afdd59d944ba920019f520da6b98fe5faa43dd ok 33756 rows=717 gaps=1
TRXUSDT-1h-2020-07.zip 8f9fed6c2807b5fb60e5d21f29394961594b31a23998cff1e79399fe61f92566 ok 35367 full
TRXUSDT-1h-2020-08.zip 66c4c7f0df431aecad77e25545dbfa4108d5fd7991da3192aa0a7adf8e3fd714 ok 37037 full
TRXUSDT-1h-2020-09.zip 5a860987d3b9d4ce9f6ceacb5495fee3e1ca2209fdf628ab0fc4f000ba299a89 ok 36697 full
TRXUSDT-1h-2020-10.zip b12f570c47fe72de9cf2cd81b5be331240e2da209ee7b96fe721b36c3a2319e3 ok 35940 full
TRXUSDT-1h-2020-11.zip 69f3f8ec5e1e68fa94946907430b6225be18b5c91e4573b3d47af1572b7c398a ok 35597 rows=719 gaps=1
TRXUSDT-1h-2020-12.zip 3b48b678192f843c52a841ce333d3fd54799c75e5dc7e8fb39cb9511df9318c1 ok 36660 rows=740 gaps=2
TRXUSDT-1h-2021-01.zip 64688b9088a3da1c3c07ac2c0a3d1a449840b9510f6378df24e84c086ef64989 ok 37765 full
TRXUSDT-1h-2021-02.zip 956149f8d57154f9f8697862f0a4bfcbbaa1150e685042e8f9b2c4623be99853 ok 35000 rows=671 gaps=1
TRXUSDT-1h-2021-03.zip d6b74e984ab37819883277a89a479dd30b084333e8d644a48b3653d5d1cae86a ok 38296 rows=743 gaps=1
TRXUSDT-1h-2021-04.zip b06a93598a3616ddc6d5eb0e4d16ce71bb0127b31a3367f705d542e3881eea9d ok 38864 rows=715 gaps=2
TRXUSDT-1h-2021-05.zip e75c00e3eab8d97c260327fa73c50b216c575ded81b08175b335e993af8838cc ok 39930 full
TRXUSDT-1h-2021-06.zip a0a4248458be4ab854e6c3d21a35d5744d8a9f05eff8442b1dbdeab311f22204 ok 37027 full
TRXUSDT-1h-2021-07.zip 634b9da6c8b027f2933265af4acf26c0c8d4719772e8ff55993c033259f52c46 ok 37343 full
TRXUSDT-1h-2021-08.zip eb113a8acefb366132585005786b845bdfa75eeb2a75da8e77a69a849cd2f490 ok 37909 rows=740 gaps=1
TRXUSDT-1h-2021-09.zip 9150b53f3dda95b66197c20c0f4cb96f0e379b09c0d51ff9808a137f52e47a8e ok 37747 rows=718 gaps=1
TRXUSDT-1h-2021-10.zip 8f77f8bcac4ff138930daaf6706db3c4555b732ab7e331bc7b4b616f1ebc52f2 ok 38669 full
TRXUSDT-1h-2021-11.zip ad030a2c003f2e1c055c6914fe1fb25177b8131f974f8218c9d4d6131a974f4a ok 38280 full
TRXUSDT-1h-2021-12.zip 7dffa2f5c6832378026336c6bc62b2e0d57d05500ae89be0a9794b216a991a59 ok 38385 full
TRXUSDT-1h-2022-01.zip 4088bdac56ea9c299a896ba66a3723e8ace39191bd0e3a96f0d747a3bb0c939d ok 38082 full
TRXUSDT-1h-2022-02.zip d031c868cd0e684c6fb59accc03d08e4954cd2fe4331581c2aa22cb5b480e248 ok 34320 full
TRXUSDT-1h-2022-03.zip 695f300b6454fdf92cc233948d4a188d3c83671842f6dfd80875fca27f0e83a8 ok 37440 full
TRXUSDT-1h-2022-04.zip 197d20a88012a73856c8a9261c89dd80f9d394c8a33bda223b0b7df70dfece9d ok 36436 full
TRXUSDT-1h-2022-05.zip a6df6f43c2f6d26b4e0f657d9486f40998b01f5e09abd4ec20808fff861af1ac ok 39010 full
TRXUSDT-1h-2022-06.zip 5a4f44a0eb0d5770aa5af03009f3a027bea0187bb77bf89bcb4d5e923d1f4eae ok 37101 full
TRXUSDT-1h-2022-07.zip e171168ddec0181c2353226223105cfe0014ffa9d0f14a2f7d95ddea2147ec85 ok 37157 full
TRXUSDT-1h-2022-08.zip 1e69babd513d51713b1b9bfd3c09c8c2984d95dec0f2d808bf0be357a44209f0 ok 36478 full
TRXUSDT-1h-2022-09.zip fc5d53c779da8bf52b1108ce6eea625588e9f147ee4882517c4c2a7abae8633b ok 35093 full
TRXUSDT-1h-2022-10.zip d7edf1a0330f52b848014fab7ee1590206cc1f937cf7928e2e12f94091cca857 ok 36213 full
TRXUSDT-1h-2022-11.zip 5247436b2dc5b43bb46bdd5fbba0954c3a7fcaab6289f690001ba0af8e4cd9eb ok 35873 full
TRXUSDT-1h-2022-12.zip a67f2a99b176c4089500c8befb5fa45368395cbc62001bd8a00a8fafc5f5c3a8 ok 35827 full
TRXUSDT-1h-2023-01.zip 21bb3b9d4831ff81de5662efd0b8607fa59e05a9738f77b15ae7d694e63e6f7c ok 36471 full
TRXUSDT-1h-2023-02.zip d9a616fcef5647542bb58ec7978baea064af8d4cf9199ef276748b58b57a2501 ok 33140 full
TRXUSDT-1h-2023-03.zip 2df2375e70c751975ccc7bd55740f36a7d510bf5dae54db85565714ef2ac7dce ok 36763 rows=743 gaps=1
TRXUSDT-1h-2023-04.zip 502988835691c08e0f891a2ec14d4dd53550ebba00579ab2b02952d367933847 ok 34782 full
TRXUSDT-1h-2023-05.zip ab1f95a02405b9edd459eb6d0e20c9a6fde7abd5cb59b726086ca3286c523ba4 ok 36213 full
TRXUSDT-1h-2023-06.zip 6af9557845655503949b51031a288a2d6a56ca71732704b25451076823e5a763 ok 35305 full
TRXUSDT-1h-2023-07.zip 7532f87818b94f5838c79ee0e6e8807ef0d984b25abbf752426703087efc49ad ok 36239 full
TRXUSDT-1h-2023-08.zip 345e3eb79ff1d0224d7ccf356cadecc640b8a8c2c9ee64efe1e4fb4cdcd3f91d ok 35546 full
TRXUSDT-1h-2023-09.zip b47699d049564a3b024f158819ace11ae3047f2261450a55fceacd2876de776d ok 34598 full
TRXUSDT-1h-2023-10.zip a38629ee761764c6fdc93dca824325e433c3336aaf6f62e4f80b0a159ce21e61 ok 36082 full
TRXUSDT-1h-2023-11.zip 1a053453918f717ba72eb9b7708854447acf6fa6f26c61a00b8e7dbf3252f3c2 ok 35551 full
TRXUSDT-1h-2023-12.zip edcd6f8116529c35a16b81a3c4ea392b9afa306bc31774cdeaf28a13e8037a54 ok 36542 full
TRXUSDT-1h-2024-01.zip ed42812ce5f33a37cca6a14bc4c776265422d091e7569c4bcd38532a5ad43925 ok 36982 full
TRXUSDT-1h-2024-02.zip 22f1d5b6a6927dc7832554a3026f852c63c9d0798caecd67feea1b005e9e2375 ok 34631 full
TRXUSDT-1h-2024-03.zip de0d6ec2c37dac6cf5c2e6c1263c4c9a540b1b41d4bc277afd9f4361a651be92 ok 37056 full
TRXUSDT-1h-2024-04.zip 363cd2bce9a2b2a45542ac37a8dbeac2a4cbd285ab4ee4776634a81c921e58e6 ok 36028 full
TRXUSDT-1h-2024-05.zip 8e57109870f8d5b1c0470df987ef9db2c43a810d3a37bf566ec1f0fee88d2e3d ok 36583 full
TRXUSDT-1h-2024-06.zip 87c6b9853734136a112824fb3e8a95047fbd0d1da2121e1a5ab2ba76118ce48e ok 35207 full
TRXUSDT-1h-2024-07.zip e52b81ca0491781e5ae117defd038825f54bd994c755ee9c7653d6c56dfed6e4 ok 35844 full
TRXUSDT-1h-2024-08.zip db1b03c8c74a595d395ce03e9b2d08ee76a1428ba84088586997f08750133833 ok 34718 full
TRXUSDT-1h-2024-09.zip 33208e62a01b8529a25b86cded1cfb07bdc8919234216d48104de9403e7391f8 ok 32455 full
TRXUSDT-1h-2024-10.zip 2690a78092e9310732f44c2da20412fda07dcd0572d1981763383b265986e5bb ok 33573 full
TRXUSDT-1h-2024-11.zip 19a1b8a424999599de59be7470a50b2413cc45b2fd97bbcf4109091900dd83e7 ok 34328 full
TRXUSDT-1h-2024-12.zip 9b7be26a67221219cd5ccd96979bf306cb30e7f8f7de397699671c50cab97a75 ok 37158 full
XRPUSDT-1h-2018-06.zip fe93cd01c2455aab0b2212935f24a1f8794b600e47c57737d46ef50ffd7529ab ok 35934 rows=709 gaps=2
XRPUSDT-1h-2018-07.zip 579eb4c29f68bd10a4cbb5f95cf159576172a51bc990b30e7e821b6b4570cfbb ok 36343 rows=737 gaps=1
XRPUSDT-1h-2018-08.zip 7876c1dcc97164b24f4ef4401e8009cc36e0f0188cb85c4ff92e82744eb78993 ok 37130 full
XRPUSDT-1h-2018-09.zip c4193fd96dbb0f8c4f1da5fcfc6d779f10a2446667d41bcf702d2ae17a838f0d ok 36688 full
XRPUSDT-1h-2018-10.zip df71fb18eaff83ecb2fe9b5b059991d580d7f9e4e0b69ec3c96090d0de76c4be ok 37415 rows=741 gaps=1
XRPUSDT-1h-2018-11.zip 2f07784ad9a07ec64d2196ea835e7ea665eb1c94c6040b3ca40f6589cceda4cd ok 36652 rows=713 gaps=1
XRPUSDT-1h-2018-12.zip 1851555a7e457fc31822d39557fcb651cf22f58cf7f26af42be4c7553f991465 ok 37766 full
XRPUSDT-1h-2019-01.zip 546e26f902de89e7a28566b55103f9cad49d8943aa665fa95e68b644267bd385 ok 36899 full
XRPUSDT-1h-2019-02.zip 3d93cc03dfb6fd80744ca8c54715e0aa3fac6cd5cf7796fd26b2c9a1e2e1c9a5 ok 33488 full
XRPUSDT-1h-2019-03.zip 53597213a6b802bb52c6a72553b963287eaf4ba3164260726ba229d037651670 ok 35960 rows=738 gaps=1
XRPUSDT-1h-2019-04.zip 37b125682cda36028eb4a0fc5b08f2ed2d59d2b7b258ff93d675406cee4850f2 ok 36146 full
XRPUSDT-1h-2019-05.zip 89fe516bbf5fb03d216976c24b1a9eddb484d992eca016c9d4603dce98fdb78f ok 37637 rows=734 gaps=1
XRPUSDT-1h-2019-06.zip eb6b178a0709e63fe2bdf4a7ad70bf7b9fb02bf3235f350a433dd4c212c724ff ok 37193 full
XRPUSDT-1h-2019-07.zip f2159d9b67fc7984f8e855ee0f6e0233a5f1b84d5dbd6e64c9b22658863c2372 ok 37586 full
XRPUSDT-1h-2019-08.zip 0f90818d843cac4b8a6dcd99ce09e0c9d364a3dfe202e29f4b2f62b9e129c713 ok 36457 rows=736 gaps=1
XRPUSDT-1h-2019-09.zip c3baa932f2dad70aa687fdb7cedccc973cc3927d010a85cb04fc7f67982a3e6f ok 35907 full
XRPUSDT-1h-2019-10.zip 3a3ccc9d0ff2bf23ebf17909d4795410dacf423327a81f2331ec5d6d89150c6e ok 37472 full
XRPUSDT-1h-2019-11.zip 33d03b02d74eb19bcae99278ce7bccab38db2f559e04e6f5e04bae127ee7f50a ok 35744 rows=716 gaps=2
XRPUSDT-1h-2019-12.zip 3d99d7de02840d6d74dea82d62171f84b777c5a8043ae38fd58079b5b44f069a ok 36349 full
XRPUSDT-1h-2020-01.zip 6d3c6e97ad191075edc3e851ae629439c9f05d4a512d0f702a08854b4d6f2dd7 ok 37164 full
XRPUSDT-1h-2020-02.zip 46a4dd2ea2aaf71ad34e298c66f4fd08dad5991ad1586f17f062d7a26e39f24b ok 35693 rows=690 gaps=2
XRPUSDT-1h-2020-03.zip d6ffc4debb2056d7405d47a258e0362ec06294a1370b9d4023b822e03e148b7f ok 37967 rows=743 gaps=1
XRPUSDT-1h-2020-04.zip ee109631971e10b4e78fcd4bf01c0c1a44e8e305089f0313c8677ce65a756728 ok 35928 rows=718 gaps=1
XRPUSDT-1h-2020-05.zip 53212ceec479499ed11ba1dc52c10831f077f209fa3bcc67d0b571c5ba9b58ae ok 37106 full
XRPUSDT-1h-2020-06.zip 66fe7be668d26c8b472c6536aeecbf43b9502a73c3a59a49189243a53999939e ok 35142 rows=717 gaps=1
XRPUSDT-1h-2020-07.zip b34c0c5310059a6c6934e39e4009b7e9e9d1a8401aab5e16045fa1e5fdcd2006 ok 37440 full
XRPUSDT-1h-2020-08.zip c6e7d10022a88013f21deb07593eecb12ad82839a9afaeb13314f7af3c51414e ok 38554 full
XRPUSDT-1h-2020-09.zip a164aeab6827996c6a56e774115de952833c2741b2f231b6a1ba9a81d84b1e4d ok 36396 full
XRPUSDT-1h-2020-10.zip 19320ca14976dd7735f0cad1d1422ced50274c92c993e43d915d83328906a7dd ok 37245 full
XRPUSDT-1h-2020-11.zip 1c467210d25fd2b2e745ea02b78bbd46a93dd0122dec1e535cd78c7ed1b39d4c ok 38025 rows=719 gaps=1
XRPUSDT-1h-2020-12.zip 006d64df2a6ec9f1462075bff97a03c9feadc6dbfe01b08aa52e47ad3a9246b0 ok 40489 rows=740 gaps=2
XRPUSDT-1h-2021-01.zip 547a7c359666086072f24b6af2056aa08b1fd2a2450476c9f56d31c55b139d18 ok 40051 full
XRPUSDT-1h-2021-02.zip 998bf641c713c800807bcf50c84e0fc74eb4c7c2a2ad5df6d66fca7174aa1f77 ok 36893 rows=671 gaps=1
XRPUSDT-1h-2021-03.zip bdf9fb6687fb1044e5c560c4a37147ac9d09dbecd14b03a54c5c546e7b695a5c ok 39739 rows=743 gaps=1
XRPUSDT-1h-2021-04.zip 0a5f1ce7d9724726e75a8da116bf2adda123a8e78530f7e309d3f6633865b5f9 ok 40504 rows=715 gaps=2
XRPUSDT-1h-2021-05.zip 6aae8ca0411fb079bd97b6a2928420fd2314d6937a659af46043e9651e86a44d ok 41275 full
XRPUSDT-1h-2021-06.zip 97bf1c3547d34cea80e8f6267265cce36bede0b760476e9e215f96704302f197 ok 38635 full
XRPUSDT-1h-2021-07.zip 18f1db3600b8ac5bce58aa525a56512b0c62eb4679a3052abbfe6a41fbf76f79 ok 39071 full
XRPUSDT-1h-2021-08.zip 023f48b1cc5cd2934817ca4c32d6c49ce7436eb9a767cdca5e65c3aa206ae8eb ok 39341 rows=740 gaps=1
XRPUSDT-1h-2021-09.zip 1bf6a19694019605f3d8914d01ba4d26b7735fd0e5bb001cac6947fc6b5471a8 ok 34964 rows=718 gaps=1
XRPUSDT-1h-2021-10.zip 7203e4bfed4dfcc86823eb18ef2e5494813b091ce173e86f9292f4e17d4848fd ok 35859 full
XRPUSDT-1h-2021-11.zip ab342c4ec5ab6955f959781ac2ae2ace6fc7ee49e66c79f4324f5334237318f2 ok 34746 full
XRPUSDT-1h-2021-12.zip 5ef1521a608eb28cd3ceeac69f0156d21d3da881e41bdd7aedb2a2f73534dd8e ok 35705 full
XRPUSDT-1h-2022-01.zip 3dd1aac953fbf7ed2d3f019bd3d85e7b1cfc335493723b02ea422543eb12be6e ok 35064 full
XRPUSDT-1h-2022-02.zip aa4fc993b3a634164574297fe55143652af3543ac87a1bba2865177808e20541 ok 32480 full
XRPUSDT-1h-2022-03.zip 7f919c2ea70d24ec90f617a697216c1fe6f0eaaf27a4c4d5514b59ef8b87b907 ok 35140 full
XRPUSDT-1h-2022-04.zip fc87ce152ba125900f7a3e181edb514a1dd2c625ddea4f9c25aa3fb9b7393da7 ok 33733 full
XRPUSDT-1h-2022-05.zip d597c3bf8094b9ae317154ca762ffdb7669c1207a6952682b37fd65e1d31cb76 ok 35208 full
XRPUSDT-1h-2022-06.zip 8347834a6951818114ad6aa914833ce1585123bc35bbe34623f2bc5f3108049a ok 33564 full
XRPUSDT-1h-2022-07.zip 67e062f1453d9b60f34d472829d4d1670ac24176af9b554b3650150b8e4da364 ok 34208 full
XRPUSDT-1h-2022-08.zip ee7291e5da57026319d088b29376b13f5eece37520a7181fd1040acf5f68298a ok 33657 full
XRPUSDT-1h-2022-09.zip ab5af203255ab893f20301362b07cdd93bf2686a794a6dffd1bb75588be1ae34 ok 33732 full
XRPUSDT-1h-2022-10.zip 2cd0fa7d849f8be4e42171bec9b715886088619d062474b77756d15e7e489e16 ok 34646 full
XRPUSDT-1h-2022-11.zip 13f222c67465b9eba0a0eb0644d43a1c22cc16b2be8c533e8e578c8a2028bdc1 ok 33826 full
XRPUSDT-1h-2022-12.zip a8cc8dcc3e93c0ef22dcf842336f355b2ecbb8ab49b8124631c3894b45905105 ok 33734 full
XRPUSDT-1h-2023-01.zip 5efb145b921b6d2adcf73338eaf787033e333033c49623a0d9152682e91b9f93 ok 34242 full
XRPUSDT-1h-2023-02.zip 907ff8915cdf9ea1c02c4949c6872d208f5f2c81c18e1751dcf1166fe2902118 ok 30691 full
XRPUSDT-1h-2023-03.zip f714a3c98ba10e82a79ec8fe126b78d70a9b3804dbbde00294c0d1d3f3280df2 ok 35023 rows=743 gaps=1
XRPUSDT-1h-2023-04.zip de8ce6aedf975d5ef89560a93a1fefb35ea51d06719a3636dd37034883c396a5 ok 33433 full
XRPUSDT-1h-2023-05.zip c5ea3091f0e130331c00ef75d36a2a2403cf4134c392fbf8b85ec97b6c21ae9b ok 34153 full
XRPUSDT-1h-2023-06.zip ebf9c8259a56ba70e5dfd37ec36ede85443ece2c352ba13a33017a8b5bfe83ad ok 33479 full
XRPUSDT-1h-2023-07.zip 5c92d13b871a149840ce45cac89991a0401451f3475c503a1e1622d71839a6b9 ok 34980 full
XRPUSDT-1h-2023-08.zip dd70ed1784aafd35b6a2b6b304abefc8a7acb20900bcee24889f5f3746219e1d ok 34641 full
XRPUSDT-1h-2023-09.zip fe3e268b4464a8745240f6dcc5c3d245c23f42e6d0432f2cef254ed49cb4f50b ok 32859 full
XRPUSDT-1h-2023-10.zip 70407de31af716063c041443ad0b8563adfb7c78bf6d20001060e5ce7142b2b0 ok 34235 full
XRPUSDT-1h-2023-11.zip 8f58815f558f51def4455ad31e5afe0b43548e54c8905541bee72b5058504a6a ok 33940 full
XRPUSDT-1h-2023-12.zip 25152d0d103af6372f509ee705ab8739a9aef936f9862f745a19f12f2cc99192 ok 34661 full
XRPUSDT-1h-2024-01.zip 77159b42f03dfbe6cd42a05d3491081d34a37293f97b0972b3391757d3c3dcbc ok 34572 full
XRPUSDT-1h-2024-02.zip 4491e38698b5d787da8616136e0c2090e2b6c5efd3e937657245410274e9544c ok 32404 full
XRPUSDT-1h-2024-03.zip b2cb09642dfc521ca15e203e2c6d2d96e67c81467005fa9d43aa5ea74f316918 ok 35732 full
XRPUSDT-1h-2024-04.zip 60ac7130e31cd5dee55c5107adbcf52b4b38874e9757a2c5599c6c4ae262bcf9 ok 34007 full
XRPUSDT-1h-2024-05.zip 6a10159e5b18de42a3a88bcf7502e881a2013143d70720df347b7fbbae023971 ok 34173 full
XRPUSDT-1h-2024-06.zip 218efe7887d1dee55eb9094bc16361f2bde83fec29e33143d3d9f7a3df72a4d4 ok 32672 full
XRPUSDT-1h-2024-07.zip 35b918d07cd7dc678cee9f7d65f468b556b9310490110151cea866e5b1a8eccb ok 35107 full
XRPUSDT-1h-2024-08.zip 00648458df95d1c616e1a44f19a6e8b25269071c685cba625897f732c1c205c6 ok 34968 full
XRPUSDT-1h-2024-09.zip c8f04c971faf07da02d29d68e27c1b83e1e42709a50c06dfe8be43f00fdb14c0 ok 33287 full
XRPUSDT-1h-2024-10.zip 76afc2abe3a70a2c79f5706d6a66e5154a58927613f033d2c76e4ac5d5eedca7 ok 34041 full
XRPUSDT-1h-2024-11.zip 010994259de1aa0378e21fd2a4755153b69f1f6f4779d91b0098a4d4c4d5545c ok 35755 full
XRPUSDT-1h-2024-12.zip 31f6d94510b7db48db22109cdcfed960112bda90a8ff5c670ae528cbf3b05db4 ok 37436 full
BTCUSDT-1d-2018-06.zip 9cd929f61b53ef27850b51824f3ae9bfbd32500398f60c8248d2502c8cc272d6 ok 2099 full
BTCUSDT-1d-2018-07.zip d1a387dc6b141c2b651fc591247923c4aba79d04e604d9b9ac898c4484a323f6 ok 2157 full
BTCUSDT-1d-2018-08.zip dc7607655efcc6a6abeaa012c2b9c25b49f1bcd44662978ce679402fbfb91494 ok 2163 full
BTCUSDT-1d-2018-09.zip 67306134323d0bdd11fe31af648552083d9f850a1689fcd8078bde392b5f0ec0 ok 2084 full
BTCUSDT-1d-2018-10.zip 50483687294e6aa225ded362010a0cd6deef013c36413f2b15ebe887ae8324bd ok 2113 full
BTCUSDT-1d-2018-11.zip 1765dea3f7e23349d6c5f225b9c0b8a5bb11c924bc8847d53b8965769cf83013 ok 2115 full
BTCUSDT-1d-2018-12.zip 5fccaa5d3e0fd00ba8592d5c3dce5bf64b41ae3f24c8b309e9329f1582417dfc ok 2160 full
BTCUSDT-1d-2019-01.zip 445904985d35f847c5c0cb4dc582c10e07967aaa6a424ee30373194b2f815519 ok 2149 full
BTCUSDT-1d-2019-02.zip 9bcdcbc003cce89ba5917367cd617bdd5abf17e427e4f7625b62f9ab9cc7439c ok 1955 full
BTCUSDT-1d-2019-03.zip 385bd09eea4a950b5a509cc2dac8812b5945d4b7edc180a26e43287a5812a7b4 ok 2119 full
BTCUSDT-1d-2019-04.zip 73774cf609ff32f08ca86e999f72aa6451cf76aaf55dc51a4c7922f20c805bd3 ok 2074 full
BTCUSDT-1d-2019-05.zip 924f9b192e6817ebc627581d826b1272747e1d36e2725a805e616558a231919e ok 2190 full
BTCUSDT-1d-2019-06.zip a027352795179a3255ecf05cf3be4f8030e836deee0dc6a5f14ebdc173b345e2 ok 2147 full
BTCUSDT-1d-2019-07.zip 52afd0bad5ac94a8cfec04d8922e2ec19806783c3a905d4e1149246561c4a331 ok 2217 full
BTCUSDT-1d-2019-08.zip b33dc2c6b606598d8daa5db45d60b568b42d2d4ec33b8f4cd9303da1ee6a58c4 ok 2212 full
BTCUSDT-1d-2019-09.zip 9d1d72fb97ea4324615b096af10a78c0511ba99569e729e483acd983fd2d0677 ok 2120 full
BTCUSDT-1d-2019-10.zip f117e45966cefc57a57ba5c9296bee5b989b125b145bca5459da7201c7191db7 ok 2184 full
BTCUSDT-1d-2019-11.zip d8e85503c78a4e8a0289046607f3a9e2b304d511812167ad97b3be82923df39e ok 2123 full
BTCUSDT-1d-2019-12.zip 1d0cf3ae0ab25953a733b51cc84c21b4685089ed86f278ad9fc7ea3acdd4be17 ok 2168 full
BTCUSDT-1d-2020-01.zip b77d84cc335299783f64e6ef845ffbab6cc6198a2c396cc1c2c6f8dd1a9db5a5 ok 2192 full
BTCUSDT-1d-2020-02.zip 808ebfc66e77113d4d5f4ead3a5e0eab4404b62548fa786b07830a4d73972152 ok 2045 full
BTCUSDT-1d-2020-03.zip 26a062af0efb4dbba71fa3db7a041629ee7cc4cf636ed13a98bf90f8fe0e1d0d ok 2222 full
BTCUSDT-1d-2020-04.zip bf4674f7aaf5baafea9e1d73c95344558b381dfe0c117110a156a0d64d8d5cf5 ok 2126 full
BTCUSDT-1d-2020-05.zip 7ae5d56d12ce599fbceac80ae04bde51c7421b39f22f924f1f46a53e560a1f75 ok 2183 full
BTCUSDT-1d-2020-06.zip 19e9ffb7c77e0b8c7bc17d6c47fdc52eb50fcb61ac8d94d32b9c13eb17c700d6 ok 2103 full
BTCUSDT-1d-2020-07.zip 76fab627ce54ba1457c63e3906e2afd3162cf053283709672fb3eb676b3dde3b ok 2174 full
BTCUSDT-1d-2020-08.zip ff20895a43680f991fa26ee2c9b34376c17487404d57a22f088af8c7ed1fd9ec ok 2197 full
BTCUSDT-1d-2020-09.zip d6f9590a181d58a992e6a3ce2346a4dbc96ecf5310c12df66c57be4818bfc28a ok 2148 full
BTCUSDT-1d-2020-10.zip e240ecb14f1120af34290ed9c7e8937e7cd8a80f0d0bbc88a924f7e520e78cec ok 2210 full
BTCUSDT-1d-2020-11.zip 4a7b8bd36409c7ae92916489621e298d750e5dda7be5b7389dc814dffb16a29e ok 2161 full
BTCUSDT-1d-2020-12.zip 77e2c7fa9a940828b3f36f7212f6def777acfc1402d173bdfad958d2e37ea469 ok 2231 full
BTCUSDT-1d-2021-01.zip 6ff53d94f600e2a208882bfd5c00e2133cff8f07e57b7f373af29f85f86e0284 ok 2295 full
BTCUSDT-1d-2021-02.zip f18254dc4a70f396494be83a6081cfafd1935aaef42aef5a12f18b0244edeb27 ok 2103 full
BTCUSDT-1d-2021-03.zip f43e48b5efc8e0b06e0520b91aad4e5668844c766933c0c5cf403115dba03303 ok 2282 full
BTCUSDT-1d-2021-04.zip 3dd852f06608173dec98b7210f6a38728ef221f08717b362b4f3f09436e0a5fe ok 2189 full
BTCUSDT-1d-2021-05.zip 3122e1ebaa1376937d479964563dced19f850636a700bb7cb97d7872ea8c8f28 ok 2283 full
BTCUSDT-1d-2021-06.zip 9875e11e890f75ef6eb0188ef7f952e5c0ba6919bd6d72d3da4d6847b84c5ccf ok 2204 full
BTCUSDT-1d-2021-07.zip 636f588a6abb568f977aea3ae798f34ced4135f2f96fbc1493a2f9ab54a844eb ok 2264 full
BTCUSDT-1d-2021-08.zip 68612e3fb74c184f97e4d3b2e061dd3743156401a6813ab897014b0b35caedd7 ok 2246 full
BTCUSDT-1d-2021-09.zip 9f6535a0fe8a417b0909d230e4a02f6a9933eb23c770f54c9f6bf140e8d02257 ok 2156 full
BTCUSDT-1d-2021-10.zip ba50ff3dab5726ca8b9fa26065fe3a8f612aed4baa978ecdd9d39647cd108684 ok 2210 full
BTCUSDT-1d-2021-11.zip 64162d8ec11458e9d02f49d8569e47765517852bcf0a908cd4d71211e3912e62 ok 2166 full
BTCUSDT-1d-2021-12.zip 6231b57d3a3b71fb76a1a34078a01a01275a59870857bf60408ccd3ba4618e75 ok 2196 full
BTCUSDT-1d-2022-01.zip a4a2e0432a8f0b42e2da71ac26599b2e6385b579ca4feba692a95cb897decdcd ok 2183 full
BTCUSDT-1d-2022-02.zip faffa5eadb9ebf0b32742773777596d0dbf3f282e94a16dd05cf1eb7b53a3763 ok 2011 full
BTCUSDT-1d-2022-03.zip 452129b478585b18931f728f89daed9d2a19d4824b932af7a099366efd4db639 ok 2206 full
BTCUSDT-1d-2022-04.zip 70413f67212d012ebfd600a6ebf20c03a9c8311bf764ab6d21d1bfd2d21d1b19 ok 2117 full
BTCUSDT-1d-2022-05.zip 53eee1be2d5b461dabc67645ad706610b0465d8bbacd5f9cd99fc790c68f18f5 ok 2212 full
BTCUSDT-1d-2022-06.zip dd5047ce33c16231bcb01f534951a709937bbfe0c0667c61f20f188cf9b94de4 ok 2169 full
BTCUSDT-1d-2022-07.zip 216567f1a8bc1dbeaada097f7eddff12dafde177c16b26507c762a613a57eb5f ok 2245 full
BTCUSDT-1d-2022-08.zip fc8bd69e95141afb6f83c5a4450c3f6b49c4a1cb16e42d90eb960c3ffa9e766e ok 2237 full
BTCUSDT-1d-2022-09.zip 68a8357e23277ebd98842fd88d492b012d53dd578b5061cafb8c070c440b235e ok 2213 full
BTCUSDT-1d-2022-10.zip 5b086535cba596ef1b465f247a26385b4ccfd12673a76f225e2dd9e00dddadfd ok 2219 full
BTCUSDT-1d-2022-11.zip 142202b226078f54342c4a1d74c8c6081a98c655d7d6f6fba06314f9c101e2d9 ok 2191 full
BTCUSDT-1d-2022-12.zip aff24746afa9a3dbd355dd3462bcef80e59e96ed9aa55f79007532f9e07991bf ok 2222 full
BTCUSDT-1d-2023-01.zip a9fd53b75add7cc42fb4779a545811606260f79810f3826215d6ebecda11bb36 ok 2250 full
BTCUSDT-1d-2023-02.zip 13df1e3633f15be3eeba4768d0cc323ef221191002657b53936a6d0fb5e6556f ok 2072 full
BTCUSDT-1d-2023-03.zip 1cb1209700ec74fa4592048de2e4ea4a38ab2bd622dfe03f1d6195c249501381 ok 2265 full
BTCUSDT-1d-2023-04.zip 999e86be73731ebc347c6ada94abceb5e291b65e7f1b4df2ce390af1aa2a4a08 ok 2108 full
BTCUSDT-1d-2023-05.zip c343e4689784c29f83d25147a096dd44b6ae5c1063c909f8adda82b56414469d ok 2168 full
BTCUSDT-1d-2023-06.zip 634919565c55a29729543d730927ca4b547c0e52d118a38de730f37fdd7617ef ok 2099 full
BTCUSDT-1d-2023-07.zip 32363d37de02e6ad8d334ac332c685f8cdf5684733a9f2cfbca40e15e591396b ok 2132 full
BTCUSDT-1d-2023-08.zip 8c5e47bfe3f0b0273534379e8ba5c93e69c84d67e8b9a03f293d6621bead2a5f ok 2160 full
BTCUSDT-1d-2023-09.zip 2fe68ecad48d6927a9280d89700e991cb6481dc2767698c785f2b2d1c0b14744 ok 2080 full
BTCUSDT-1d-2023-10.zip 358b83bf0c2a5d5390a4bc4d4ae14fa9df0f56139642ad996c0df0f7bc712400 ok 2154 full
BTCUSDT-1d-2023-11.zip fac9823cac7bf56a3a6038c3b79417e949b00c172939e62000451c8c25edd7c1 ok 2102 full
BTCUSDT-1d-2023-12.zip 056dad65795c9264ef90ee668a4c245e8fec73ebcbb272d28f5596c389913979 ok 2177 full
BTCUSDT-1d-2024-01.zip 474c1ce6fbb09e42cfc7231fee249aecc58af2fb5918570ffeba37998926b4a4 ok 2190 full
BTCUSDT-1d-2024-02.zip 4dae0b3d6b8ea59e39e6493b7964040c52459ea7b0a50b9c2793dcbfae53800d ok 2053 full
BTCUSDT-1d-2024-03.zip f7cd4fcafe79d1fac0c830d5fe152f7b3b9100e7c97e40352188766388af0ae0 ok 2224 full
BTCUSDT-1d-2024-04.zip b4a8542c33e5251fb53f8a3352dd4e6f3cde4ac25f2c24935db8089aa1a2c3a0 ok 2141 full
BTCUSDT-1d-2024-05.zip 0175f696039b9e30f06c6398d218c99e577661ac30424869c648fe9770507248 ok 2185 full
BTCUSDT-1d-2024-06.zip 8a0f6416c2a83cfa15ba26c688d716fdafe35bb1748dd244f0550e8b2f7e38f7 ok 2095 full
BTCUSDT-1d-2024-07.zip 9a2963ef6541b4d7630eff8df7b2eaee48ece33180af03c34b0bf92675692899 ok 2203 full
BTCUSDT-1d-2024-08.zip df41fe3260920b85da86855b4880f34618982e689081317d3d63b9b3bbcb1d53 ok 2190 full
BTCUSDT-1d-2024-09.zip 89e459b2a8f4b138dc742d9358c0084fcabf719d40468e156c3149a3635f3359 ok 2106 full
BTCUSDT-1d-2024-10.zip d442a5f158d45d9ff7b1584b35023a4161cf915a3857f5e71a2a2e6aa68c69c5 ok 2203 full
BTCUSDT-1d-2024-11.zip b197219d9e8b5e933226e1cd24fe2b7bfc3a2e8a3e74e6f7dc08a48f314da8c3 ok 2157 full
BTCUSDT-1d-2024-12.zip 82ec90210f492694b9d01722f97f579108ee787968b8485b53d736ea735700da ok 2218 full
ETHUSDT-1d-2018-06.zip 1ea19c2401da7834c05f5ef6bf267396b42a74270b2a7dc99bb6c22ab92b2967 ok 2001 full
ETHUSDT-1d-2018-07.zip d9bfa2b313084c574f0da99f5fd7a0c61522c5ad38df6cf7615abcacc9ab94ed ok 2052 full
ETHUSDT-1d-2018-08.zip 1006383c7741f63cd748dc5b1aa712450c5569427e41a26063f97f8bc5d3cfc0 ok 2061 full
ETHUSDT-1d-2018-09.zip c3fd03563b6b9d5a7b659a7866365425e4923c3830dae7eb3377bcc796ff508d ok 2012 full
ETHUSDT-1d-2018-10.zip 0a6adbd54433817171527d020941d218e804137eb420dca870f712e2e098e909 ok 2021 full
ETHUSDT-1d-2018-11.zip c317bdd16cab973dab7b74e6bd5b41461b3fdc63e6554969bb11039b862bea52 ok 2001 full
ETHUSDT-1d-2018-12.zip fec688ae856a2f512b221fd93e953686e9ae31a759ae35e703130be997a00c8d ok 2055 full
ETHUSDT-1d-2019-01.zip 5db0fac2caac1662a9711a131db4023b872687ec4419aee607b22fb28efa9d0f ok 2041 full
ETHUSDT-1d-2019-02.zip 5dd233c56bc043f86cf20230aeae6557f196a03f229b483d4808d4c372ecfbf6 ok 1857 full
ETHUSDT-1d-2019-03.zip 7110a0c9bed5a226f331b1db9e17908c8cf41e9739fa5380e1bdb6a07128e1d1 ok 1997 full
ETHUSDT-1d-2019-04.zip b123b48109e16ca09d0494c1135e3c013c7e48db17c8da606f72d508056cc01b ok 1997 full
ETHUSDT-1d-2019-05.zip e54b6777906b8d46ff68ed93ec655fde458240b3d5231cc98c34ae61a7414f14 ok 2097 full
ETHUSDT-1d-2019-06.zip 2447c3549842f4729a86147518ec59643263a4555b95a8369a63d7b18e8ccea2 ok 2005 full
ETHUSDT-1d-2019-07.zip 211372309c6ab41b04a487ccc907974e1fd25ebedd30a8e5efb4e6f3ce33ccd1 ok 2071 full
ETHUSDT-1d-2019-08.zip a006cf295ddb6dcb4202a7a536f657b6b8042bd27aa3cc711149bfc18b98573a ok 2034 full
ETHUSDT-1d-2019-09.zip 3f5b401f768be3ef62f22d0352169d2f99b79e0783173f9635972b10de2ac494 ok 1994 full
ETHUSDT-1d-2019-10.zip c705e5dfaaf0a35878b42c66ceef333df3cc08bfe9c2809994a4d692efb7b140 ok 2062 full
ETHUSDT-1d-2019-11.zip 0e53010ba35f4b17baff9c5036996ada587a545edd5700ef1123dae26d415b58 ok 1986 full
ETHUSDT-1d-2019-12.zip dbda569579729247ec329713ace57a0093a28f186897e3547a753e99ef3e4baf ok 2013 full
ETHUSDT-1d-2020-01.zip 60eb92d3c0010521ae0a80855f59aa1018b390492e5ee2fa9f1916afcf99bfc0 ok 2050 full
ETHUSDT-1d-2020-02.zip a4927f2f99a99becee21abc71c16d4c8f44262f8f7d86c937a16b871071acfc1 ok 1960 full
ETHUSDT-1d-2020-03.zip f9e9b8e0f556d30c624b9f8fc623dd366f29d9da7082c48b3f8ada4105ca81b3 ok 2093 full
ETHUSDT-1d-2020-04.zip f963e1e3679f68253ddc43921c8bde865e34938ab97d1c53e4737d5b29825b3a ok 2018 full
ETHUSDT-1d-2020-05.zip aeb988e3582382defd2f6cbb36da3bb090e19e9fc060f4eded02edca7b6b3c85 ok 2094 full
ETHUSDT-1d-2020-06.zip 2aeee240c48684d04f27b0aad484798faa0894d09dc45aa93be2f2b53a27dfe5 ok 2016 full
ETHUSDT-1d-2020-07.zip 722e0731f69bb21ed4d0a4ff9e8b9a9720211b015e9c4bcc27054e594581d1e5 ok 2088 full
ETHUSDT-1d-2020-08.zip 192e8bc02d4002994fdb721195bef53753b4fcf24810533d091e3777979aead6 ok 2090 full
ETHUSDT-1d-2020-09.zip 1ae7c22a58c249e7c231fff048fa8bc08b93016be112e211744053d8f8f96b88 ok 2041 full
ETHUSDT-1d-2020-10.zip cb36755f3638dedde237cd9d36f990d7e15940abfd9d8b3e636fd2ec4e6031e0 ok 2093 full
ETHUSDT-1d-2020-11.zip ab032f6eecf184ac52f3bc1eefff55031e98bedf256523b7e495b952197f08e0 ok 2076 full
ETHUSDT-1d-2020-12.zip 40dd3b625132d93b36397f9f4dcceaf6be13f50ffb357c28d06003370fd11176 ok 2129 full
ETHUSDT-1d-2021-01.zip 9c077a151ad30786ffbf2d560f457fb727ea3fc4f0932e6e287e2bf22ce5ba16 ok 2214 full
ETHUSDT-1d-2021-02.zip 07b43daa2cd8487fc7a652c58237b93a7a07108e5f4d5cb9ec086d7737898d99 ok 2005 full
ETHUSDT-1d-2021-03.zip 0f3fe06236480c4aed3460eac7b2d4e0ef621ec4cc5da20445797cb682b74dc2 ok 2195 full
ETHUSDT-1d-2021-04.zip d483115836d4c285943064b22461670ff30ef1601b1183c4034c7edb4fffeedf ok 2115 full
ETHUSDT-1d-2021-05.zip bc68e71360869ed2f1d06bfa07ec6599c5bdb38406d6b712635afe2c6f1df7fa ok 2240 full
ETHUSDT-1d-2021-06.zip b8ddb26be6c48876a04a7fddfbc3f4c8842f53b8e217613eac9dd15a55836597 ok 2136 full
ETHUSDT-1d-2021-07.zip c33ea50dc263d559315e7bf3dd6ab87a40f12747fe6fd0c16b5dff28dbd7b58f ok 2186 full
ETHUSDT-1d-2021-08.zip 3cffa7628cff71c9b2ec5f33085c90317fc1d9866ac701ca9742322344182397 ok 2200 full
ETHUSDT-1d-2021-09.zip 14e849630ad4d5ae2f899c289c395736c12f1b699486b9dcfd1d7e058e4fff18 ok 2089 full
ETHUSDT-1d-2021-10.zip 4f9e66dc56961d8552082782b2cdac5a149e125da90694885ab90363a63e8ff5 ok 2129 full
ETHUSDT-1d-2021-11.zip 8e9ebb3bcc07d3080db603ceafaec29fe66612bd160ad737235a3476fc8eafe9 ok 2080 full
ETHUSDT-1d-2021-12.zip 2f30c04c60988621d47afa115e2b7771785440ee3effe87355d5f7038d234361 ok 2114 full
ETHUSDT-1d-2022-01.zip d992b05664b21cef2e104aa93ab1de487fe396f68dc9767380d87998cc7969a1 ok 2139 full
ETHUSDT-1d-2022-02.zip 2d7eeb5c0c0574ebfff2d7369f3b991e2693fe81a2defc87525c667598c3ceef ok 1948 full
ETHUSDT-1d-2022-03.zip 0cfffeb995ad02f64b0a1235db34fbca7982aef8b104ee4bb7fd52605323ad53 ok 2131 full
ETHUSDT-1d-2022-04.zip 2e3269eb718fd3c75f41a11f03c91f3e3af91bd14815b79b216ec371a876ec57 ok 2041 full
ETHUSDT-1d-2022-05.zip fe39dd94b5e65aced7b4979fd6357fcd3700ae556a9d03c507d9983d507a628e ok 2144 full
ETHUSDT-1d-2022-06.zip 62633207619685b148ef58bdc910b78a33fef724ac2b507ef57e7878145516dc ok 2060 full
ETHUSDT-1d-2022-07.zip 6b4b9bdc7b0e1e6b87b95e750343d898c0df36d9d885bfeae594ca4e29ac0981 ok 2130 full
ETHUSDT-1d-2022-08.zip 9f54ee2471795608f083a175285cbfd77f5de473cbeaa0d491b3751cf791a3a9 ok 2118 full
ETHUSDT-1d-2022-09.zip 64daaa8bedcb3e82736d5b6426974aadd814007067fc81380ae87e04e1112714 ok 2022 full
ETHUSDT-1d-2022-10.zip 01a81d5a27053ead87542d1329763bfd22978080f6c3e7ee588f189cd49ff8d6 ok 2088 full
ETHUSDT-1d-2022-11.zip 83cef6abcb76dffbac6c6ad0e2842dd218f226e1e4a1839e78e35b12dd68a015 ok 2061 full
ETHUSDT-1d-2022-12.zip e3f2c5851ef573c35733f29293188310099683948692d8e8ba008b17fdbd508f ok 2050 full
ETHUSDT-1d-2023-01.zip 811ff55e20735e6fff55ef37c0c3e922eb6d26d41fe84fc04b2a03c0179549ad ok 2087 full
ETHUSDT-1d-2023-02.zip 2f6cdf5aa6613ab3621dbd730a234935e8909f980f1195f7581abf145e422cce ok 1916 full
ETHUSDT-1d-2023-03.zip dbfe653bf62ebac3e4e2bf5c96160de6c76bcbd76e4979ca2105d11cf2bdf77e ok 2098 full
ETHUSDT-1d-2023-04.zip d316aea182914c088b06d03640812bae72e889a347ed9dcc78bb8ad10ed1bdf9 ok 2019 full
ETHUSDT-1d-2023-05.zip a86ef09c35c764e6f0066953074ffb0dc93239afe92e3d73e232fbc95cdeab51 ok 2087 full
ETHUSDT-1d-2023-06.zip 4932a5fd8853ddf99f3853a501e5f35ffad45a07a466bbf4603ddb7fb4c821ac ok 1994 full
ETHUSDT-1d-2023-07.zip f66293651e4a841fe9bc36cc76483bdb9c1faaa085377fbbd2fd064cd401cd5e ok 2036 full
ETHUSDT-1d-2023-08.zip e694749c085b888401f51002dbd21bc8cf0c4d801d2da311e72d6c1ae97627d4 ok 2058 full
ETHUSDT-1d-2023-09.zip c1faa848529e17e15deafb208d817155576ef51e556813109cdb60c0153ac73d ok 1985 full
ETHUSDT-1d-2023-10.zip baadc74c685a63d7ba453531c9f4d1df81a5719200501ab229018352a1be9630 ok 2059 full
ETHUSDT-1d-2023-11.zip 8faf9f53efe268d25d01b987b3a364cd9f1983703ab2f78486192c29218b1faf ok 2022 full
ETHUSDT-1d-2023-12.zip 1778c56d995fe5d32a0816a5214feabcd84d594f4e882315b4e225d6e86e5275 ok 2086 full
ETHUSDT-1d-2024-01.zip 49598e812edcbf446f20d21a3ffc382a6f51fc1982a7e4224b78a416dbe36e8d ok 2109 full
ETHUSDT-1d-2024-02.zip 36ebece2c2a6fcccdc4ee2924cd037870e88fa09877208843e2cbdf5f5c93a44 ok 1976 full
ETHUSDT-1d-2024-03.zip 78f5a6edba263350c1df6d4678596570ae5ce5df38edd4e253ec89431fbddfc0 ok 2125 full
ETHUSDT-1d-2024-04.zip d0a5088a3d49cea7269dc3bf7f29912e23a390c87fb7b14acbed210ac9be8177 ok 2050 full
ETHUSDT-1d-2024-05.zip d0c98ff2f16913e1c1f9bb72165086056ae9923db5b07f113ca6eaf334b87bbf ok 2109 full
ETHUSDT-1d-2024-06.zip 5198557b48b8df354f5dc07e76270e988416f9e8972e577d9c327b31d2cb1db1 ok 2014 full
ETHUSDT-1d-2024-07.zip ae4a1a154d9c4e27bb7551293216d6824a0455fef7ecea0efb5084e145ba1ac5 ok 2093 full
ETHUSDT-1d-2024-08.zip e41fc2dcefc5d0737fd74e943602327cfdbcde04dec40d94030cfcf01720e593 ok 2107 full
ETHUSDT-1d-2024-09.zip 6e6add68412a0d89199fb6185b88b24994c32522e4ee67ac88d02ab8b81eb1c1 ok 2030 full
ETHUSDT-1d-2024-10.zip cc2ae0b168f8ddd7b45441a30ae9aa95f748ec9ecaa19ab3cf5e9ec21fc63783 ok 2084 full
ETHUSDT-1d-2024-11.zip fe8b32f1ab7a3a72316b404ffc9d7002cb75801364f12dc52eddfedbb3e3af43 ok 2074 full
ETHUSDT-1d-2024-12.zip e36880cb5d79157599878eb97db2d20a5bc10f904384501f0b3571a09c1b6bcc ok 2128 full
XRPUSDT-1d-2018-06.zip 6f864d35d6a07081c4b294e3d6c2d3c1114d5a63864efc89b92c43f908a7bdf8 ok 1912 full
XRPUSDT-1d-2018-07.zip 7f06e273ddf51c090e683cb7f8139b2c6b6a124a608079b3485ebc80d029480e ok 1906 full
XRPUSDT-1d-2018-08.zip 63863a88505124d1abbe1e3242602ff4127946863aa92ae0f67315fb12ca25be ok 1927 full
XRPUSDT-1d-2018-09.zip 0b45f0a6e337f4e04c280da40dddbf72e0cd37fb1a421563fe9bbf975ac6c6a2 ok 1914 full
XRPUSDT-1d-2018-10.zip 2a9a62b403140f7572db597c56be3a2ca79f3a0baf9a60b9cda64723e4e487c7 ok 1966 full
XRPUSDT-1d-2018-11.zip 9b218a7de4ab34334069c19ce99877e57d30f3e712e0f7737947e94b70f5888f ok 1903 full
XRPUSDT-1d-2018-12.zip b69fbc69315754424ecd913f955cc13fa634cd9b39883108223b66b50871d094 ok 1956 full
XRPUSDT-1d-2019-01.zip aaaea822828bf014de70341fbf30e70b9b9002a62bdf2c166a35e77fbdb89931 ok 1900 full
XRPUSDT-1d-2019-02.zip 1b55ec7581c85a6cbac4a2f8fb5fc317594edb538ec6630e1de41345ca6059a7 ok 1766 full
XRPUSDT-1d-2019-03.zip f0272b5075489c8a793215ea7ae2cd80ed0967d361f5c86a3a2878921eb654de ok 1884 full
XRPUSDT-1d-2019-04.zip ec5ad9b94701a9e0d52ec0b39e49e71b0ac93efc09b953ebef4b9975826f819e ok 1889 full
XRPUSDT-1d-2019-05.zip de25e5ca2d2d116e5cb91868c56ddd91d838de4f0b3ad7ea82a64e55cf1f373a ok 1986 full
XRPUSDT-1d-2019-06.zip c376b2aff021bca414fad1e83265ab7bf426086b67848158eaf13438da055c51 ok 1904 full
XRPUSDT-1d-2019-07.zip 06caa0bbfab12f39bc9d86aed91bc29c8d543d48c6656d9e2eb0345df4838db9 ok 1931 full
XRPUSDT-1d-2019-08.zip 35a8a286afb654b51974c862e5df014bc25c6351fb21f440ce267d7816f9e5cb ok 1930 full
XRPUSDT-1d-2019-09.zip f9b0f4bb64906f5c195198db73ab8f6bf766856354a272c71c697e82efd82198 ok 1877 full
XRPUSDT-1d-2019-10.zip 2c6b02d3544aaee4dbcfb9087aacd5852320d1654c05d0747eb2f9650888d6d1 ok 1937 full
XRPUSDT-1d-2019-11.zip a5e7f061fc88ef693fcc028ea868b30a410ea8ac7bfc266005617c44bf58e100 ok 1881 full
XRPUSDT-1d-2019-12.zip 52e98eacd9be0234d683651afe788a0f13b3bec042adec4fce7b2a2c359eae54 ok 1909 full
XRPUSDT-1d-2020-01.zip 6d233df9242d22fbf1d9f8b00b018dfe2e4fe5a9c7432a4c3d8a5f7a2c3fadef ok 1925 full
XRPUSDT-1d-2020-02.zip d678cae33f2d576468e707cd2b40799d7728a9ed0dc07f68915e3d76a462f96e ok 1863 full
XRPUSDT-1d-2020-03.zip 11de79c36b11a6549498b9f298d6c846ade4f8776c941f4a302316780c919550 ok 1961 full
XRPUSDT-1d-2020-04.zip ceb065861878366a8c9c71e38e97a5f99d8473e62c981d945ff27defb32dba86 ok 1892 full
XRPUSDT-1d-2020-05.zip d9256ff5abfd7ae9c6991cda9c6bda4ead885da655d049aab19f28d578ecbddc ok 1923 full
XRPUSDT-1d-2020-06.zip 44162ba1ac5e7b31db76f5798ab2cad73b5e12de4084fdbd6547ce6fee602534 ok 1861 full
XRPUSDT-1d-2020-07.zip 75307a63512d929cdbfbc8ed220a8e813e8fc275e4258c55981e1030499b22be ok 1939 full
XRPUSDT-1d-2020-08.zip 493372b00d49d4ca0a4c78e0b30f4cefd4a14fec576a5bab8c89408a5f29efa7 ok 1988 full
XRPUSDT-1d-2020-09.zip 556c7a7c968ee8726d1af4436fd5d587118486dd90fb61f7b6791dc063b8c1ee ok 1890 full
XRPUSDT-1d-2020-10.zip 3c1c5f6def1060e10e8c1607cadfe426f765a5fb25421f44d433a7b727d78dda ok 1937 full
XRPUSDT-1d-2020-11.zip 2b861e841478996e54a260f3b818b937b7ffd9e3d008723f5263198a53a0b136 ok 1961 full
XRPUSDT-1d-2020-12.zip 56f6e592c1da5401af7082e345a937d3dc3157ee91e465e54f9f777ffdb077ab ok 2094 full
XRPUSDT-1d-2021-01.zip 53b2af75344e28cf5b87c6b88451cff0c5155c511ebd776a357a38b60aa7511b ok 2040 full
XRPUSDT-1d-2021-02.zip c307b2f377c74b15aaabc2fe147f4b6828a0347233ca73c6c263c46b55769119 ok 1887 full
XRPUSDT-1d-2021-03.zip 3c3e4b7aaa07ba8f43ffc5fe9b0079d56f00fafcd7848870ff5149571cf091f9 ok 2040 full
XRPUSDT-1d-2021-04.zip 9c7051467d928c789f00ecd81b417539e2d57252278f24a4b3075fbae5d9ca4f ok 2075 full
XRPUSDT-1d-2021-05.zip c21aade0e23847c36447bc7484bbb74f730d7e584779e5069e9b2d6e5a8db0db ok 2091 full
XRPUSDT-1d-2021-06.zip c6ea29b2ee938d6cd69355c5dc5651be1cd5b186f417a19c7660d1191b8564ae ok 1984 full
XRPUSDT-1d-2021-07.zip 6b7489a4ee06c0e8caa6c6895ef26d289c2f6f6a43169f177e85c90fca2ccc89 ok 2018 full
XRPUSDT-1d-2021-08.zip 9dd6d014a6b4e12e10fdec3d26197141a49d3a23bd5a451fe8abdf552062f611 ok 2064 full
XRPUSDT-1d-2021-09.zip b5ed02c6aa63dbbaa255e84887fe9b6eac1d54225b94c8c258218ffafc0ad63e ok 1885 full
XRPUSDT-1d-2021-10.zip 7f5a25774455bd74ccc0cd9d7e233c8ecf0167f366140936f0edc9d6a607752b ok 1871 full
XRPUSDT-1d-2021-11.zip ef825d7243a3f7871af370cc6d3a63e159254d3e03d7b7a5e908ec59afdc9ca0 ok 1838 full
XRPUSDT-1d-2021-12.zip a2c2348f54a0da8cd1d90fbba6bb90cfd8d5adcc5c71656b898cd3e5677c8ae2 ok 1871 full
XRPUSDT-1d-2022-01.zip 41ebf5ea4b08c2b5eff9cedc9a7f1a94c82b8b2714d7328dc38bd28b37e83f1c ok 1850 full
XRPUSDT-1d-2022-02.zip 6ed8b24c43e0c27d5d2f55d17e065060c1acdb193b48b37a59b8a341f49e80ba ok 1698 full
XRPUSDT-1d-2022-03.zip f24700067ee73f7a6332324dafa793cee60c211652b958abb6af5dbb58474f30 ok 1868 full
XRPUSDT-1d-2022-04.zip 9365367487e1839d85fb09553cb049ef36053fc33393c8baa4eaf84421dd7e75 ok 1776 full
XRPUSDT-1d-2022-05.zip 2c75f5fb14c7d7bb261c88bbec05089e0930a95f31152893b291a6f3312016d3 ok 1873 full
XRPUSDT-1d-2022-06.zip 0ab3e8fd000fae80b1de3eb1d929fa83c2509dc419428e98e1219dff520f1564 ok 1780 full
XRPUSDT-1d-2022-07.zip 8890abf0a4ad78adb010a73bec02345a089b37594fe7288a22c42382934fb45b ok 1815 full
XRPUSDT-1d-2022-08.zip ce580f5537079389719850790799957109fb66cfeef6f75c9ce83d5b0516dc6e ok 1782 full
XRPUSDT-1d-2022-09.zip 8da4fa67267f0c3951dd6e2a26e086cb13a8bdbb26e07eaee95c5376e00098ec ok 1789 full
XRPUSDT-1d-2022-10.zip a05c1ef9219d4a75652b657974b33a7f58f4bce6679e0016fd3eeb7bff0b8534 ok 1827 full
XRPUSDT-1d-2022-11.zip 0164f972460dc83b469bcb60b31fa314141f6aa6706001fc42ded8073bde9463 ok 1785 full
XRPUSDT-1d-2022-12.zip 202fed22611f52fb7c8e7459a15482136de30cfb6f9aa3b6f7172ebc204e2156 ok 1788 full
XRPUSDT-1d-2023-01.zip 8be26490687e21718f03fc24138a2b2369b67eed27cd2a4df2341bd9de1ff8f1 ok 1825 full
XRPUSDT-1d-2023-02.zip 3980f23c45e2512de04b3b35dfd3c74847397544c3878a5aa577aee7f0400e6c ok 1632 full
XRPUSDT-1d-2023-03.zip 00dc37357422723ce04e7871d05d89454f7ac16758a29b5d6eb990ed8d647589 ok 1845 full
XRPUSDT-1d-2023-04.zip 9ae8857bfcda35413ece8f8d038ab0ad7a6b810bef0552a008ab162c393d251a ok 1782 full
XRPUSDT-1d-2023-05.zip 4d407d9b06d7b8af4263cb6a02dd72d762b82b3fac747044407095661cc4b0a2 ok 1809 full
XRPUSDT-1d-2023-06.zip fc2055e68aff582d847adbfdc2fbca7cb9fcbae4811e5068a5f5a41d81212db9 ok 1777 full
XRPUSDT-1d-2023-07.zip 2e9c69ad1ac561bb0884f934d6a15a87be3d8b657b5852d5a78e7f9119f4f194 ok 1851 full
XRPUSDT-1d-2023-08.zip 7265881181ea7542fd0fc7c765256a53ad26c0e9ed219be4ee616991b58c5f84 ok 1834 full
XRPUSDT-1d-2023-09.zip 480c0f760cd26249c93f8df3939376e27df741fd40052f627a1272e00eb1d236 ok 1745 full
XRPUSDT-1d-2023-10.zip 9c5280a4bee20f99e1c5b808a7eb321768370e82d49c706c71225aa9d2587733 ok 1830 full
XRPUSDT-1d-2023-11.zip 7c88be1782d857618087bd828bbfd45e828dc9cc7e6e64eda0fa0b70dc107508 ok 1791 full
XRPUSDT-1d-2023-12.zip 92de6e8836a3f349b485a13664305526a597b90eecc1be9fc1f4cbee51d48f78 ok 1818 full
XRPUSDT-1d-2024-01.zip 8f7f49bd9983bb41300d1e34b9f1f2c8f71eb83a59e8f80e4e8dc0f25be398e5 ok 1855 full
XRPUSDT-1d-2024-02.zip a9397519b2c63d7975647cc25da8e0402d681daa40f1ffa53abd72ff4339518f ok 1719 full
XRPUSDT-1d-2024-03.zip bb59eb280b27bb4b8f53fb451a371be2d5792de73a3ba5855fef9f06036ae2df ok 1875 full
XRPUSDT-1d-2024-04.zip c01cebab808784c9ace45e07f4fa0a0eebcfab9ac2434ba91e4ba10e0bd12e59 ok 1814 full
XRPUSDT-1d-2024-05.zip f41ee9027a174e557c1e77864565d98fa3657661eccefd378cbb31b6aa0fff0c ok 1811 full
XRPUSDT-1d-2024-06.zip 67373424c870228cc94683da6a3f8cf502a9ed9d862881bd3f76b0cabee71e97 ok 1750 full
XRPUSDT-1d-2024-07.zip 614caa7bf49eef199b9ac2aca0584b1c867378d0be244711f33a41bf62dbd8f3 ok 1852 full
XRPUSDT-1d-2024-08.zip ff037823bd6a03610bf098d3fd1424a19e6685c649045dd450e08d2cc288b951 ok 1837 full
XRPUSDT-1d-2024-09.zip 93486c5b023b290da8fb1f46d8960d43bb0fa728ba0760bb27233bfc61d0de22 ok 1772 full
XRPUSDT-1d-2024-10.zip 8412c6971d6c3086dae895bd8d5653ab1af3509e7760ac0e57cf1183e3d5c912 ok 1809 full
XRPUSDT-1d-2024-11.zip c1cbca9c5727d3534e3d31702f2e05bbbe3be7787f30bd9cafc1cb0902d44c1e ok 1883 full
XRPUSDT-1d-2024-12.zip 60a2b7c038950663a77d9a278966bc47a78eac9655d563f89e9f2412efcfea29 ok 1972 full
BTCUSDT-fundingRate-2020-01.zip 7f81b2f3694d13779e7e896b69d60cd61e9444d7b9f9e90df761935e1c1b76e2 ok 825 records=93
BTCUSDT-fundingRate-2020-02.zip 6599466d108d120c64a078824326c063ed2d4335b3292e52c5e572f79166533a ok 885 records=87
BTCUSDT-fundingRate-2020-03.zip eee845fde6336e29d25889563cba3d2cff2d4d640e51fb1f82ae9b28cedaee77 ok 928 records=93
BTCUSDT-fundingRate-2020-04.zip d009ce034d08c3dcf3e7f874b0f8b0ec76ba507bc6bb4e007e541df537bafbce ok 867 records=90
BTCUSDT-fundingRate-2020-05.zip 3f2b56dd6b9a42457009bb367d0adadd3cf7e2216cd325172d0089e3883125a8 ok 839 records=93
BTCUSDT-fundingRate-2020-06.zip 30b3470ff98576578973d75e3c157a5cbf1778b11e4c26b4b4ff70a3cbb348ec ok 791 records=90
BTCUSDT-fundingRate-2020-07.zip 18dae7b11075fc0fba79ad47df46683415cba5d027caa69c66bc2a5c9d9b459a ok 712 records=93
BTCUSDT-fundingRate-2020-08.zip e6f6d1749f674c85d4766e0eb36af6ea40d91a0674234d30df80eb9876b094e3 ok 854 records=93
BTCUSDT-fundingRate-2020-09.zip 7ae9a3b6afb2dc06e46080582908ec8c27063b707a14c7f1e679dc991ff48032 ok 838 records=90
BTCUSDT-fundingRate-2020-10.zip 4c55b191c101f39c7fb193a6529665dd9e83302ca21876521e4c93b3902e9fb1 ok 828 records=93
BTCUSDT-fundingRate-2020-11.zip 676356a2d075caa51b4f8ada026e9430dc320ffd23d2343b13b7aa25324ed6d1 ok 854 records=90
BTCUSDT-fundingRate-2020-12.zip d7390f90edf54cc4ad9bbe78e2f6b291ae06ad9539f591a2d0fce445873bbd63 ok 852 records=93
BTCUSDT-fundingRate-2021-01.zip cff916dc4b638ec3de97828e8911cd91cf7d7a3d0836ec0175869c374e66823d ok 981 records=93
BTCUSDT-fundingRate-2021-02.zip 819a7b107443686adb313fc5fc223302a29f3981e1d1bd9828ad0ade65a8a8af ok 956 records=84
BTCUSDT-fundingRate-2021-03.zip 2125fd300848938c7b992b8f7b7b5007d5b277a4ff1ebda7da083b40242729da ok 918 records=93
BTCUSDT-fundingRate-2021-04.zip 9cd888e3b0a1954813d0062c2e60426fdc8e34a7f258f6838371ec67f535b028 ok 914 records=90
BTCUSDT-fundingRate-2021-05.zip ed934afb9cf84df6ecae742e755147333a84244836a66b51523abc66dd5f63af ok 960 records=93
BTCUSDT-fundingRate-2021-06.zip 7b8d9bfb8816636b800764dafb2aa2307d19166c695bfa245adbf7d01d61f766 ok 883 records=90
BTCUSDT-fundingRate-2021-07.zip 8ab3df641d3bcf40527491f8e26d046ad2b662d1950ead9555ad32975571b7fe ok 973 records=93
BTCUSDT-fundingRate-2021-08.zip 7eb681cc45b94176f4b9192a62c3a1925d79031ba001cea2d8dec6ff6e5b9c35 ok 781 records=93
BTCUSDT-fundingRate-2021-09.zip 03f25a7c25eef18d5f5b5b7bb0b664cab7a210b409f37e95a54e141808a0752d ok 828 records=90
BTCUSDT-fundingRate-2021-10.zip f25820d6add687addbca3ef43bee58f70853a6da53832a0c1bc22d00dc8ec64a ok 951 records=93
BTCUSDT-fundingRate-2021-11.zip e2e6b2d7218607e7e4a38137d50f553c2cfb901275c19edf567024c1cc6de85f ok 919 records=90
BTCUSDT-fundingRate-2021-12.zip bf3ce484faf41d7dccfd38c5cc3d8de34d8297df30ab10784e874cc10fd1b310 ok 815 records=93
BTCUSDT-fundingRate-2022-01.zip 22ee19079b620f5c6d820e7d7f8bafa7fde866d89bd664863b8bd527749c12cb ok 906 records=93
BTCUSDT-fundingRate-2022-02.zip fa95088258a905c79ab79e8984d2f6f66933ec2e814dbab4ef9da89b01ab484a ok 890 records=84
BTCUSDT-fundingRate-2022-03.zip 4cf0883bc07f4ed4cdd3b0d8c0d166b4d15d21e666ab752f9f44401af4d6172f ok 904 records=93
BTCUSDT-fundingRate-2022-04.zip 57e2776cc68b3169fc9f8632dad67278f470cd453407a8ebe6c87963c8a31357 ok 926 records=90
BTCUSDT-fundingRate-2022-05.zip bced8a5013d09742b96682e6fd01ad4456213515a03d7586ec2b1f2689af5255 ok 915 records=93
BTCUSDT-fundingRate-2022-06.zip 0cd0708f8903829eb46f98cf60f4b2516c986e1ccddf6620a5912b48e16baf93 ok 966 records=90
BTCUSDT-fundingRate-2022-07.zip 29d58cce0cd45f74c6a112039835c6d9ee5a7e60e7c38c2503beb7930453a4fe ok 917 records=93
BTCUSDT-fundingRate-2022-08.zip 6f4f0c6c84c05694b4b4a5c085776730fd4059723eecd98ee6ffeb3fde4da811 ok 997 records=93
BTCUSDT-fundingRate-2022-09.zip d62cd4e13009de37add446dc4f63ead4c56dcc4955a1e60f6726bcadc5a68fa9 ok 960 records=90
BTCUSDT-fundingRate-2022-10.zip ad9efed10d4ca1567b865d7a158790977cec1b925395634217069df6696c8bc9 ok 950 records=93
BTCUSDT-fundingRate-2022-11.zip 8febe5bec1a029e993bbf27490761f8c47c32849bf7dd13441b2b2f6ec1ffb51 ok 1000 records=90
BTCUSDT-fundingRate-2022-12.zip 4218c78331bcc4dbeb5768fa112242a880971c1f2cfd1d3f32aaa26ca34069af ok 982 records=93
BTCUSDT-fundingRate-2023-01.zip 05e3df32f28d0d50f4c5a280adee9368b4a66fc68c6ddca1b3277087ac0d19f5 ok 863 records=93
BTCUSDT-fundingRate-2023-02.zip 5227accd9aaa59f71f5e682abffb58be5f99573ed208ab968b1704c81ac11345 ok 808 records=84
BTCUSDT-fundingRate-2023-03.zip ab022adff9b853d2f33cf80154e77c770f57c3392f0bbc36564b2e2cdbd0e872 ok 956 records=93
BTCUSDT-fundingRate-2023-04.zip 2931039d26818edc65d4faefba84945fd1ba52989dd58fb127dc3cd7a12c7fbf ok 952 records=90
BTCUSDT-fundingRate-2023-05.zip 5d026fece46df86293054c8c56c2c8de575d30161b82979b11831831217a246e ok 983 records=93
BTCUSDT-fundingRate-2023-06.zip 3ffdde6f1dc9c3c065d77ae43f3ba64d19d4cb76512d4bc1d541933d4fb2e6f7 ok 845 records=90
BTCUSDT-fundingRate-2023-07.zip 0304baed9fd407293a8a8040b30a1b68bd344803b630d33530375b421733a930 ok 861 records=93
BTCUSDT-fundingRate-2023-08.zip 516a8f50631c6ede6a9642f6d1590b6a22c33ba09935501d2ace8dc1396501fd ok 846 records=93
BTCUSDT-fundingRate-2023-09.zip 3fd9df6fd1eef33cf5fe625c27012359bc6d64a68c109305d7b44a0354f533c2 ok 914 records=90
BTCUSDT-fundingRate-2023-10.zip 03105cc140150bffca834bcccbddc6cfee245e079d2df1759653243bd6e92448 ok 865 records=93
BTCUSDT-fundingRate-2023-11.zip 8015d2997f8d5e757ff3707ee87800ca30a74da0129daa747b64117f07bcc186 ok 696 records=90
BTCUSDT-fundingRate-2023-12.zip 8f02fdd2a2da261bbf13ab301c74bdb57fae005f19d5088e9ece5f8824c1a2a7 ok 810 records=93
BTCUSDT-fundingRate-2024-01.zip 3e0d30870672aa8f0f937881056e3cfd55913ae5c780cd50b33f2763aa0ba58e ok 696 records=93
BTCUSDT-fundingRate-2024-02.zip daf1e4901e3d6436d82ad60f90d007eb5300be8047cfef121007203a7212cde6 ok 776 records=87
BTCUSDT-fundingRate-2024-03.zip 711dcaf2a341aedfd06447b4117b540f60adb0784c5e64a313c718e4cf092bc3 ok 939 records=93
BTCUSDT-fundingRate-2024-04.zip 6d220b8e2815362a11d294d35dbca28568370d8295351937eceec10f2b359b85 ok 842 records=90
BTCUSDT-fundingRate-2024-05.zip aef8c5fdce1493fd570b5829a72f2f17c7e459483390f25544d16c2a30be592e ok 830 records=93
BTCUSDT-fundingRate-2024-06.zip 43fc4473820d1fb4fe340d1b1951a87555f6841aa352e684fa95d6adffce04c6 ok 721 records=90
BTCUSDT-fundingRate-2024-07.zip acab0593c1452660ce74a6c239fb215c1192b0a9c6e8c1689e6495de40a0174b ok 847 records=93
BTCUSDT-fundingRate-2024-08.zip 7003d29a43dd5f9357f838da8766834954939e22c1d80af682d9f33984f67b71 ok 904 records=93
BTCUSDT-fundingRate-2024-09.zip 6ef23b02392b481ef9c3855434bf3644289fb6e228b4f7d9a0dfc6d3cdff1116 ok 924 records=90
BTCUSDT-fundingRate-2024-10.zip 26db65ac8020d80ece35df79c254c5f7e24427529bcceeb2972748c4fe2d2707 ok 801 records=93
BTCUSDT-fundingRate-2024-11.zip e1b19cccfe2cdcba48b022790789b7b01edd86c075f39bc152e44c267d43bd51 ok 746 records=90
BTCUSDT-fundingRate-2024-12.zip 069409f525ebf6370ee1c7defe475167de4b97284c5ac8e68768652968cd3dc9 ok 808 records=93
```

## Results

**Validity checks:**

1. Pins (Step 2): tree hash `96de9766551d478883f3451bcaae261f165fd3d4` matches; git status empty; `6 pins`; all six `OK`. **Pass.**
2. Tests (Step 3): `27 passed`. **Pass.**
3. Run outcome (Step 4): `DONE exit=1`; run log last line `RESULT 2 problem(s)`. **Fail** — see PROBLEM lines below.
   - Funding: `FUNDING 60 of 60 months ok` — **holds.**
   - VERIFY scored window: `exit 2 status invalid; failures 4; included pairs 3 of 3` — **invalid.**
   - VERIFY reported window: `exit 2 status invalid; failures 4; included pairs 3 of 3` — **invalid (reported only; §5 rule 6).**
   - MASK exclusions: `excluded_months=0` — **holds** (no month excluded under the 17% rule).
   - COMPARE: `every entry equals full-range-2017-2024's: True` — **holds.**
   - DIGEST: `rebuilds both manifests byte for byte: True` — **holds.**
   - No check raised (no `PROBLEM` naming an exception).
4. REQUESTS line: `latest month 2024-12; after 2024-12: 0` — **holds.** No `OutOfScope`, no traceback.
5. Reserved-window check (Step 5): `RESERVED-WINDOW FILES 0` — **holds.**
6. Append checks (Step 6c): both blocks `reads back: True`; see checks section.

**KLINES lines:**

- `KLINES full-range-2017-2024: 1164 files; missing 46, ok 1118` — missing 46 matches expected exactly.
- `KLINES full-range-2019-2024: 1080 files; missing 25, ok 1055` — missing 25 matches expected exactly.

**VERIFY lines and failures:**

scored window `full-range-2017-2024`:
`exit 2 status invalid; failures 4; included pairs 3 of 3: BTCUSDT, ETHUSDT, XRPUSDT`
- `XRPUSDT: tick_limit_quotes=545`
- `BTCUSDT: daily_days_mismatched=1`
- `ETHUSDT: daily_days_mismatched=1`
- `XRPUSDT: daily_days_mismatched=1`

reported window `full-range-2019-2024`:
`exit 2 status invalid; failures 4; included pairs 3 of 3: BTCUSDT, ETHUSDT, XRPUSDT`
- same four failures as above.

The scored window keeps 3 of 3 pairs (no exclusion under §5 rule 8). No XRPUSDT exclusion. The reported window also keeps 3 of 3 (reported only; §5 rule 6 applies).

**MASK totals line:**

`MASK totals symbols_with_a_mask=9 repaired_hours=81 dropped_hours=0 masked_hours=789 excluded_months=0`

XRPUSDT quote test: `maximum_spread_pct=0.15 widest_spread_pct=0.1972... tick_limit_quotes=545 breaches=True`

Symbol-months with a masked hour or an exclusion: 181

**REQUESTS and REPORT lines:**

`REQUESTS 3613 to data.binance.vision, 2364 of them .CHECKSUM; latest month 2024-12; after 2024-12: 0`
`RESERVED-WINDOW FILES 0`
`REPORT run log 16575 bytes before this line and digest 125659 bytes: 142234 bytes; the report takes them as text (limit 190000)`

**Appended blocks (Step 6c):**

- Run log: text, 16866 bytes; reads back: True
- Digest: text, 125683 bytes; reads back: True

**Hashes:**

- Digest sha256: `d10331a68985b3daa678debbc666d55fe04f13bc5be5fbf15f2e337e879b89ef`
- Manifest full-range-2017-2024 sha256: `069024759d2e999cd09801a17961c12f6b6f57e73bb66900748364261260b94e`
- Manifest full-range-2019-2024 sha256: `40fa4da932b661e846d2cdf19ee3ae099bd9b1ec1f5ab13a3069dd82a4f223dc`

This run commits no manifest. Both manifests are written under `data/full-range/` (git-ignored). Claude rebuilds them from the digest in a reviewed PR after the verify failures are resolved.

## Ideas and proposals

The two VERIFY problems need investigation before the manifests can be committed and stage 2 can run.

1. **`daily_days_mismatched=1` on BTCUSDT, ETHUSDT and XRPUSDT.** The scored window's `1d` files run 2018-06 to 2024-12 (79 months). A mismatch of 1 means the daily archive delivered one more or one fewer calendar day than the spec expects. The run log records no checksum failure and no `PROBLEM` on a check raising, so the file was accepted by Binance's checksum. This could be a Binance publishing edge case (a late-month file with one extra or missing day), a spec boundary definition, or a leap-day count. Claude should inspect `data/full-range/full-range-2017-2024.verify.json` to find the specific month and pair, and check that month's `1d` archive against its expected day count.

2. **`tick_limit_quotes=545` on XRPUSDT.** The `MASK` quote test shows `widest_spread_pct=0.1972`, which exceeds `maximum_spread_pct=0.15` from `config/default.toml`. The `tick_limit_quotes=545` count is the number of hours breaching the spread limit. The MASK did not exclude any month (all `excluded False`), so no 17%-rule month was triggered. The verify check reports this as a failure. Claude should check whether the spread filter in `verify` uses the same threshold as the mask, and whether this failure blocks stage 2 or is a known condition from the eligibility record.

**Clock at end of run:** Wed Oct 07 10:48:45 UTC 2026

## Checks

```text
?? docs/reviews/2026-10-07-bob-full-range-2017-2024-fetch.md
check_reports: verified 2026-09-26-bob-hourly-defect-calendar.md:data/calendar.py
check_reports: corrected 2026-09-26-bob-hourly-defect-calendar.md:data/events.py (states 53097095f39c.., appendix is 55f19293acc5..)
check_reports: verified 2026-09-26-bob-outage-calendar.md:data/outages.py
check_reports: verified 2026-09-26-bob-parser-anomaly-classes.md:data/anomalies.py
check_reports: verified 2026-09-26-bob-refined-parser-rule.md:data/refined_rule.py
check_reports: verified 2026-09-26-claude-open-mismatch-explained.md:data/open_mismatch.py
check_reports: verified 2026-09-26-claude-volume-field-provenance.md:data/volume_fields.py
check_reports: verified 2026-09-27-bob-combined-defect-census.md:data/defect_census.py
check_reports: verified 2026-09-27-bob-p8-funding-archives.md:data/p8_archives.py
check_reports: verified 2026-09-27-bob-rescued-month-masking.md:data/rescued_masking.py
check_reports: verified 2026-09-27-bob-rescued-month-masking.md:data/rescued_bands.py
check_reports: verified 2026-09-27-claude-defect-calendar-corrections.md:data/calendar_denominator.py
check_reports: verified 2026-09-27-claude-defect-calendar-corrections.md:data/eventwide_per_hour.py
check_reports: verified 2026-09-27-claude-eligibility-thresholds.md:data/masked_fraction.py
check_reports: verified 2026-09-27-claude-eligibility-thresholds.md:data/masked_bands.py
check_reports: verified 2026-09-27-claude-eligibility-thresholds.md:data/masked_corrections.py
check_reports: verified 2026-09-27-claude-fold-grid-and-eligibility.md:data/fold_eligibility.py
check_reports: verified 2026-09-27-claude-soft-drawdown-lockout.md:data/flat_stretches.py
check_reports: verified 2026-09-28-claude-v2-downtrend-research.md:data/v2_downtrend_research.py
check_reports: 33 stated hash(es): 18 verified, 1 corrected in place, 14 unverifiable
check_reports: 171 script mention(s) without a hash (information; a mention is not a pin)
check_reports: 0 problem(s)
Wed Oct 07 10:49:28 UTC 2026
```
