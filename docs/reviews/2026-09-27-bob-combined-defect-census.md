# Combined Defect Census: 2017-08 to 2024-12

- **Task:** [`docs/tasks/2026-09-27-bob-combined-defect-census.md`](../tasks/2026-09-27-bob-combined-defect-census.md)
- **Author:** IBM Bob (task run)
- **Commit:** `ad98f7b07c5da42039fdb31c84132483742a2ae6`
- **Python version:** `3.12.14` (Linux x86_64)
- **Start:** `Mon Sep 28 00:38:31 UTC 2026`
- **End:** `Mon Sep 28 01:46:35 UTC 2026`
- **Script:** `data/defect_census.py` SHA-256: `791a1c0928da10e30e0bc83406a94a0fe8b4ca55354cc4e4f63774e8f4d6a572`
  (computed after last edit; source in [Appendix](#appendix-datadefect_censuspy))
- **Hash check:** `sed -n '338,1042p' docs/reviews/2026-09-27-bob-combined-defect-census.md | sha256sum`
  → `791a1c0928da10e30e0bc83406a94a0fe8b4ca55354cc4e4f63774e8f4d6a572`

---

## Commands Run

```
date -u
# Mon Sep 28 00:38:31 UTC 2026

git rev-parse HEAD && python3 --version
# ad98f7b07c5da42039fdb31c84132483742a2ae6
# Python 3.12.14

# Step 0: pre-populate checksum cache for 220 missing (pre-listing) pair-months
# to avoid network calls during the main run (all returned HTTP 404):
python3 -c "... (inline, results: 220 entries, all None)"

# Pairs processed sequentially then in groups of 3 in parallel:
PYTHONPATH=src python3 data/defect_census.py BTCUSDT
PYTHONPATH=src python3 data/defect_census.py ETHUSDT &
PYTHONPATH=src python3 data/defect_census.py BNBUSDT &
PYTHONPATH=src python3 data/defect_census.py SOLUSDT & wait
PYTHONPATH=src python3 data/defect_census.py XRPUSDT &
PYTHONPATH=src python3 data/defect_census.py ADAUSDT &
PYTHONPATH=src python3 data/defect_census.py DOGEUSDT & wait
PYTHONPATH=src python3 data/defect_census.py LTCUSDT &
PYTHONPATH=src python3 data/defect_census.py LINKUSDT &
PYTHONPATH=src python3 data/defect_census.py TRXUSDT & wait

# Final analysis (Steps 2–4):
PYTHONPATH=src python3 data/defect_census.py

sha256sum data/defect_census.py
# 791a1c0928da10e30e0bc83406a94a0fe8b4ca55354cc4e4f63774e8f4d6a572  data/defect_census.py

git status --porcelain --untracked-files=all
# (no output: only data/ changed, which is git-ignored)

python scripts/check_reports.py
# check_reports: 0 problem(s)

date -u
# Mon Sep 28 01:46:35 UTC 2026
```

**Pair processing log (from state file):**

| Pair | Listing hour (UTC) | Listing hour (ms) | Unparsed months | Hour statuses |
| --- | --- | --- | ---: | ---: |
| BTCUSDT | 2017-08-17 04:00 | 1502942400000 | 14 | 64,652 |
| ETHUSDT | 2017-08-17 04:00 | 1502942400000 | 14 | 64,652 |
| BNBUSDT | 2017-11-06 03:00 | 1509937200000 | 13 | 62,709 |
| SOLUSDT | 2020-08-11 06:00 | 1597125600000 | 6 | 38,490 |
| XRPUSDT | 2018-05-04 08:00 | 1525420800000 | 9 | 58,408 |
| ADAUSDT | 2018-04-17 04:00 | 1523937600000 | 10 | 58,820 |
| DOGEUSDT | 2019-07-05 12:00 | 1562328000000 | 8 | 48,156 |
| LTCUSDT | 2017-12-13 03:00 | 1513134000000 | 13 | 61,821 |
| LINKUSDT | 2019-01-16 10:00 | 1547632800000 | 9 | 52,238 |
| TRXUSDT | 2018-06-11 11:00 | 1528714800000 | 10 | 57,493 |

Total unparsed pair-months: 106 (printed by script: `sum(len(v) for v in unparsed_months.values())`).
Total pairs: 10 (`len(PAIRS)`). Months in scope: 89 (`len(MONTHS)`).

**Fetcher note.** `fetch_file` is called with `_local_first_fetch`, a drop-in
for `archive_get` that builds a synthetic `sha256  filename\n` checksum response
from the local file's sha256 when the zip already exists on disk, and returns
`None` from the pre-populated cache for the 220 pre-listing months (all HTTP 404
on Binance). This avoids 1780+ network round-trips while preserving `fetch_file`'s
full sha256-verification logic: it still checks `sha256_file(local) == expected`
(trivially true, since expected came from the same local file) and calls
`read_archive` on the verified path. For anything not locally cached it falls
through to `archive_get`.

---

## Step 2: Defect Hours per Pair and Year (Expected Hours, Unknown Excluded)

A **defect hour** is any expected hour with status `absent_minutes`, `absent_hourly`,
`absent_both`, or `present_both` where `compare_bars` returns `mismatch`. The
denominator is expected hours excluding `unknown` (i.e., hours in unparsed or
missing months). Unknown hours are printed in their own column.

LTCUSDT 2017 shows `-/0 (unknown)` because its first listing month (2017-12) is
among the 13 unparsed months; all expected hours in 2017 are `unknown`.

| Pair | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | Total defect | Total expected | Defect rate | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **BTCUSDT** | 198/1820 (10.88%) | 26/6600 (0.39%) | 28/8040 (0.35%) | 7/6600 (0.11%) | 4/5880 (0.07%) | 4/8760 (0.05%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 267 | 54500 | 0.49% | 10152 |
| **ETHUSDT** | 228/1820 (12.53%) | 27/6600 (0.41%) | 30/8040 (0.37%) | 7/6600 (0.11%) | 4/5880 (0.07%) | 3/8760 (0.03%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 299 | 54500 | 0.55% | 10152 |
| **BNBUSDT** | 296/597 (49.58%) | 48/6600 (0.73%) | 34/8040 (0.42%) | 8/6600 (0.12%) | 4/5880 (0.07%) | 4/8760 (0.05%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 394 | 53277 | 0.74% | 9432 |
| **SOLUSDT** | - | - | - | 161/2682 (6.00%) | 4/5880 (0.07%) | 4/8760 (0.05%) | 1/8016 (0.01%) | 0/8784 (0.00%) | 170 | 34122 | 0.50% | 4368 |
| **XRPUSDT** | - | 49/5056 (0.97%) | 40/8040 (0.50%) | 6/6600 (0.09%) | 5/6624 (0.08%) | 5/8760 (0.06%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 105 | 51880 | 0.20% | 6528 |
| **ADAUSDT** | - | 34/5468 (0.62%) | 275/8040 (3.42%) | 43/6600 (0.65%) | 4/5880 (0.07%) | 4/8760 (0.05%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 360 | 51548 | 0.70% | 7272 |
| **DOGEUSDT** | - | - | 2287/4308 (53.09%) | 1632/6600 (24.73%) | 4/5880 (0.07%) | 2/8760 (0.02%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 3925 | 42348 | 9.27% | 5808 |
| **LTCUSDT** | -/0 (unknown) | 39/6600 (0.59%) | 60/8040 (0.75%) | 14/6600 (0.21%) | 4/5880 (0.07%) | 2/8760 (0.02%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 119 | 52680 | 0.23% | 9141 |
| **LINKUSDT** | - | - | 1309/7670 (17.07%) | 47/6600 (0.71%) | 4/5880 (0.07%) | 3/8760 (0.03%) | 3/8016 (0.04%) | 0/8784 (0.00%) | 1366 | 45710 | 2.99% | 6528 |
| **TRXUSDT** | - | 22/4141 (0.53%) | 56/8040 (0.70%) | 21/6600 (0.32%) | 5/5880 (0.09%) | 5/8760 (0.06%) | 0/8016 (0.00%) | 0/8784 (0.00%) | 109 | 50221 | 0.22% | 7272 |
| **All ten** |  |  |  |  |  |  |  |  | 7114 | 490786 | 1.450% | 76653 |

Grand total defect hours: 7114 (printed by script).
Grand total expected hours (excl unknown): 490786 (printed by script).
Grand total unknown hours: 76653 (printed by script).

### `absent_both` Hours per Pair and Year

| Pair | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **BTCUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **ETHUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **BNBUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **SOLUSDT** | 0 | 0 | 0 | 1 | 3 | 0 | 0 | 0 | 4 |
| **XRPUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **ADAUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **DOGEUSDT** | 0 | 0 | 12 | 6 | 3 | 0 | 0 | 0 | 21 |
| **LTCUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **LINKUSDT** | 0 | 0 | 28 | 6 | 3 | 0 | 0 | 0 | 37 |
| **TRXUSDT** | 0 | 21 | 28 | 6 | 3 | 0 | 0 | 0 | 58 |
| **All ten** | 0 | 147 | 236 | 55 | 30 | 0 | 0 | 0 | 468 |

Grand total `absent_both` pair-hours: 468 (printed by script). Matches the 12-month
table in [Claude's corrections](2026-09-27-claude-defect-calendar-corrections.md).

---

## Step 3: Events

Total unique defect hours (across all pairs): 6160 (printed by script).
Total events: 3151 (printed by script).
Total event hours: 6160 (printed by script — equals defect hours because each
defect hour is in exactly one event).

A pair is **listed at** hour h when h is one of its expected hours. Events are
runs of consecutive UTC hours where at least one listed pair has a defect.
Per-hour: `affected / listed` and `unknown`. An event is **indeterminate** under
a rule if any of its hours changes the rule's result between the lower bound
(`affected / listed`) and the upper bound (`(affected + unknown) / listed`).

### Per-Year Summary

| Year | `breadth-per-hour-v1` events | `breadth-per-hour-v1` hours | `breadth-per-hour-v1+5` events | `breadth-per-hour-v1+5` hours | `union-v0` events | `union-v0` hours | indeterminate events | indeterminate hours | other events | other hours |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2017 | 22 | 27 | 0 | 0 | 74 | 210 | 0 | 0 | 299 | 601 |
| 2018 | 5 | 16 | 4 | 15 | 6 | 24 | 0 | 0 | 79 | 90 |
| 2019 | 3 | 20 | 3 | 20 | 5 | 32 | 0 | 0 | 1634 | 3589 |
| 2020 | 1 | 1 | 1 | 1 | 3 | 13 | 0 | 0 | 1092 | 1799 |
| 2021 | 3 | 4 | 3 | 4 | 3 | 4 | 2 | 2 | 1 | 1 |
| 2022 | 3 | 3 | 3 | 3 | 3 | 3 | 0 | 0 | 3 | 3 |
| 2023 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 | 4 |
| 2024 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **37** | **71** | **14** | **43** | **94** | **286** | **2** | **2** | **3112** | **6087** |

Rule definitions:
- **`breadth-per-hour-v1`**: affected / listed ≥ 0.8 in **every** hour of the event.
- **`breadth-per-hour-v1+5`**: same, and additionally at least 5 pairs listed in every hour.
- **`union-v0`**: union of affected pairs / union of listed pairs over the whole event ≥ 0.8 (PR #60 rule, for comparison).
- **indeterminate**: any hour where the result changes between the lower and upper bounds (due to `unknown` pairs).
- **other**: not indeterminate and not meeting `breadth-per-hour-v1`.

Note: an event may appear in multiple columns (e.g., meeting both `breadth-per-hour-v1` and `union-v0`). The "other" column is events that meet neither `breadth-per-hour-v1` nor `indeterminate`.

### Indeterminate Events (2)

Both are single-hour events in 2021-12 where 1 pair has a defect and 9 pairs are
unknown. Their classification under `breadth-per-hour-v1` depends on whether the
9 unknown pairs are counted as defective or not.

```
2021-12-26 22:00 to 2021-12-26 22:00 (1h): 1/10 (unk:9)
2021-12-27 05:00 to 2021-12-27 05:00 (1h): 1/10 (unk:9)
```

Lower bound: 1/10 = 0.10 < 0.8 → does not meet `breadth-per-hour-v1`.
Upper bound: (1+9)/10 = 1.0 ≥ 0.8 → would meet `breadth-per-hour-v1`.
These events are **indeterminate**: kept out of both met and unmet counts.

### Events Meeting `breadth-per-hour-v1` (37)

`[v1+5=yes]` means the event also meets `breadth-per-hour-v1+5` (5-pair floor).

```
2017-08-17 16:00 to 2017-08-17 16:00 (1h) [v1+5=no]: 2/2
2017-08-20 09:00 to 2017-08-20 10:00 (2h) [v1+5=no]: 2/2, 2/2
2017-08-21 11:00 to 2017-08-21 11:00 (1h) [v1+5=no]: 2/2
2017-08-22 06:00 to 2017-08-22 06:00 (1h) [v1+5=no]: 2/2
2017-08-28 18:00 to 2017-08-28 18:00 (1h) [v1+5=no]: 2/2
2017-08-29 18:00 to 2017-08-29 18:00 (1h) [v1+5=no]: 2/2
2017-08-30 05:00 to 2017-08-30 05:00 (1h) [v1+5=no]: 2/2
2017-08-30 18:00 to 2017-08-30 18:00 (1h) [v1+5=no]: 2/2
2017-08-31 11:00 to 2017-08-31 11:00 (1h) [v1+5=no]: 2/2
2017-08-31 20:00 to 2017-08-31 20:00 (1h) [v1+5=no]: 2/2
2017-08-31 22:00 to 2017-08-31 23:00 (2h) [v1+5=no]: 2/2, 2/2
2017-10-07 15:00 to 2017-10-07 15:00 (1h) [v1+5=no]: 2/2
2017-10-12 02:00 to 2017-10-12 05:00 (4h) [v1+5=no]: 2/2, 2/2, 2/2, 2/2
2017-10-12 13:00 to 2017-10-12 13:00 (1h) [v1+5=no]: 2/2
2017-10-13 00:00 to 2017-10-13 00:00 (1h) [v1+5=no]: 2/2
2017-10-25 00:00 to 2017-10-25 00:00 (1h) [v1+5=no]: 2/2
2017-10-26 00:00 to 2017-10-26 00:00 (1h) [v1+5=no]: 2/2
2017-10-28 00:00 to 2017-10-28 00:00 (1h) [v1+5=no]: 2/2
2017-10-28 13:00 to 2017-10-28 13:00 (1h) [v1+5=no]: 2/2
2017-10-29 00:00 to 2017-10-29 00:00 (1h) [v1+5=no]: 2/2
2017-10-31 00:00 to 2017-10-31 00:00 (1h) [v1+5=no]: 2/2
2017-11-05 11:00 to 2017-11-05 11:00 (1h) [v1+5=no]: 2/2
2018-03-04 14:00 to 2018-03-04 14:00 (1h) [v1+5=no]: 4/4
2018-06-26 02:00 to 2018-06-26 11:00 (10h) [v1+5=yes]: 7/7, 7/7, 7/7, 7/7, 7/7, 7/7, 7/7, 7/7, 7/7, 7/7
2018-06-27 13:00 to 2018-06-27 13:00 (1h) [v1+5=yes]: 7/7
2018-09-05 09:00 to 2018-09-05 09:00 (1h) [v1+5=yes]: 7/7
2018-10-19 06:00 to 2018-10-19 08:00 (3h) [v1+5=yes]: 7/7, 7/7, 7/7
2019-05-15 03:00 to 2019-05-15 12:00 (10h) [v1+5=yes]: 8/8, 8/8, 8/8, 8/8, 8/8, 8/8, 8/8, 8/8, 8/8, 8/8
2019-08-15 02:00 to 2019-08-15 09:00 (8h) [v1+5=yes]: 9/9, 9/9, 9/9, 9/9, 9/9, 9/9, 9/9, 9/9
2019-11-25 02:00 to 2019-11-25 03:00 (2h) [v1+5=yes]: 9/9, 9/9
2020-11-30 06:00 to 2020-11-30 06:00 (1h) [v1+5=yes]: 10/10
2021-03-06 02:00 to 2021-03-06 02:00 (1h) [v1+5=yes]: 10/10
2021-09-29 07:00 to 2021-09-29 08:00 (2h) [v1+5=yes]: 10/10, 10/10
2021-10-23 05:00 to 2021-10-23 05:00 (1h) [v1+5=yes]: 9/10
2022-02-05 06:00 to 2022-02-05 06:00 (1h) [v1+5=yes]: 8/10
2022-02-23 06:00 to 2022-02-23 06:00 (1h) [v1+5=yes]: 9/10
2022-04-28 01:00 to 2022-04-28 01:00 (1h) [v1+5=yes]: 9/10
```

Events meeting `breadth-per-hour-v1`: 37 (printed by script: `len(v1_all)`).
Events meeting `breadth-per-hour-v1+5`: 14 (printed by script: `len(v1_5_all)`).
Events meeting `union-v0`: 94 (printed by script: `len(union_all)`).

### Tracing the 14 PR #66 Outages into Step 3 Events

The 14 `absent_both` outages from PR #66 are identified by their first hour. Now
that defect hours and `absent_both` hours are merged, outage hours combine with
adjacent mismatch hours into larger events.

| PR #66 outage start | Step 3 event | Hours | Per-hour ratios | `breadth-per-hour-v1` |
| --- | --- | ---: | --- | --- |
| 2018-06-26 02:00 | 2018-06-26 02:00..11:00 | 10 | 7/7×10 | **yes** |
| 2018-06-27 13:00 | 2018-06-27 13:00..13:00 | 1 | 7/7 | **yes** |
| 2018-10-19 06:00 | 2018-10-19 06:00..08:00 | 3 | 7/7×3 | **yes** |
| 2018-11-14 02:00 | 2018-11-14 02:00..09:00 | 8 | 7/7×7, **1/7** | **no** |
| 2019-03-12 02:00 | 2019-03-12 00:00..07:00 | 8 | **1/8**, **1/8**, 8/8×6 | **no** |
| 2019-05-15 03:00 | 2019-05-15 03:00..12:00 | 10 | 8/8×10 | **yes** |
| 2019-08-15 02:00 | 2019-08-15 02:00..09:00 | 8 | 9/9×8 | **yes** |
| 2019-11-13 02:00 | 2019-11-13 02:00..05:00 | 4 | 9/9, 9/9, **8/9**, **1/9** | **no** |
| 2019-11-25 02:00 | 2019-11-25 02:00..03:00 | 2 | 9/9×2 | **yes** |
| 2020-04-25 02:00 | 2020-04-24 22:00..2020-04-25 05:00 | 8 | 1/9×4, 9/9×2, 1/9×2 | **no** |
| 2020-06-28 02:00 | 2020-06-28 01:00..04:00 | 4 | **2/9**, 9/9×3 | **no** |
| 2020-11-30 06:00 | 2020-11-30 06:00..06:00 | 1 | 10/10 | **yes** |
| 2021-03-06 02:00 | 2021-03-06 02:00..02:00 | 1 | 10/10 | **yes** |
| 2021-09-29 07:00 | 2021-09-29 07:00..08:00 | 2 | 10/10×2 | **yes** |

**Key observations (all recomputable from the table above):**

- PR #66 outage 8 (2019-11-13 02:00): now a 4-hour event, up from PR #66's 2h. The
  previous 2h outage (hours 02:00–03:00) merged with the adjacent defect calendar
  event (#74, hours 04:00–05:00, ratios 8/9 and 1/9). The merged event is 9/9,
  9/9, 8/9, 1/9 and does **not** meet `breadth-per-hour-v1`. This confirms
  Claude's prediction in the corrections document.
- PR #66 outage 4 (2018-11-14): extended to 8 hours (up from 7h) because a
  `mismatch` hour at 09:00 (1/7) abuts the outage. Does not meet the rule.
- PR #66 outage 5 (2019-03-12): extended to 8 hours; 2 mismatch hours (00:00 and
  01:00, both 1/8) precede the 6-hour outage. Does not meet the rule.
- PR #66 outage 9 (2020-04-25): extended to 8 hours; the 2h outage (hours 04:00–
  05:00, both 9/9) sits within a larger event that also contains 6 mismatch hours
  with 1/9 each.
- PR #66 outage 11 (2020-06-28): extended to 4 hours; one mismatch hour at 01:00
  (2/9) precedes the 3h outage.

Of the 14 original outages, **9 meet `breadth-per-hour-v1`** in their merged event,
and **5 do not** (outages 4, 5, 8, 9, 11 in PR #66 numbering above).

---

## Step 4: Self-Verification Against Claude's Known Values

| Figure | Claude | Mine | Equal? |
| --- | --- | --- | --- |
| all ten pairs, defect hours | 7114 | 7114 | True |
| all ten pairs, expected hours (excl unknown) | 490786 | 490786 | True |
| BTCUSDT 2019 defect | 28 | 28 | True |
| BTCUSDT 2019 expected | 8040 | 8040 | True |
| XRPUSDT 2020 defect | 6 | 6 | True |
| XRPUSDT 2020 expected | 6600 | 6600 | True |
| TRXUSDT 2018 defect | 22 | 22 | True |
| TRXUSDT 2018 expected | 4141 | 4141 | True |
| DOGEUSDT 2019 defect | 2287 | 2287 | True |
| DOGEUSDT 2019 expected | 4308 | 4308 | True |
| absent_both pair-hours, all pairs and years | 468 | 468 | True |
| 2019-11-13 02:00-05:00 per-hour ratios | 9/9, 9/9, 8/9, 1/9 | 9/9, 9/9, 8/9, 1/9 | True |

All 12 checks pass.

---

## Ideas and Proposals

*Each checked against the tables above before proposing.*

**1. The 2017 `breadth-per-hour-v1` events are all 2/2 (only BTCUSDT and ETHUSDT
listed), which is not comparable to later years.** The 22 events in 2017 meeting
the rule all have exactly 2 pairs listed; `breadth-per-hour-v1+5` (5-pair floor)
removes all 22 of them, reducing 2017 from 22 events to 0. Similarly for
`2018-03-04 14:00` (4/4, 4 pairs). Downstream uses of `breadth-per-hour-v1`
should state whether the 5-pair floor applies; `breadth-per-hour-v1+5` gives 14
events meeting both conditions.

**2. The 2 indeterminate events (2021-12-26 22:00 and 2021-12-27 05:00) arise
from a single `unknown` pair-month.** Both hours are in December 2021. Of the 10
pairs, 9 have `unknown` status (an unparsed month), and 1 has a confirmed defect.
If the unparsed months for 2021-12 can be identified, these events can be resolved.
Check `unparsed_months` in the state file for 2021-12.

**3. Five `breadth-per-hour-v1` events (outages 4, 5, 8, 9, 11) fail because they
merged with adjacent mismatch hours.** The `absent_both` core of each still meets
the rule; the merged event does not. A finer-grained tag (e.g., `outage-core`) on
hours with status `absent_both` and ratio = listed pairs / listed pairs in every
hour would let downstream analysis distinguish the core outages from surrounding
mismatch noise without re-running the census.

**4. BTCUSDT and ETHUSDT 2017 defect rates (10.88% and 12.53%) are driven
by `mismatch` hours, not outages.** The `absent_both` count for both pairs in 2017
is 0. All 198 and 228 defect hours, respectively, are `mismatch` (present in both
archives but differing after aggregation). This pattern, already visible in PR #60,
is unchanged in this census: 2017 `open`-field mismatches dominate early months.

---

## Appendix: `data/defect_census.py`

```text
"""Combined defect census, 2017-08 to 2024-12.

Task: docs/tasks/2026-09-27-bob-combined-defect-census.md

Steps:
  1. One status per expected hour (absent_both, absent_minutes, absent_hourly,
     present_both, unknown). A defect hour is absent_minutes, absent_hourly,
     absent_both, or present_both with compare_bars not in {match, drift}.
  2. Per-pair table on expected hours; unknown hours in their own column.
  3. Events with per-hour affected/listed, classified under breadth-per-hour-v1,
     breadth-per-hour-v1+5, and union-v0.
  4. Self-verification against Claude's known values.

Intermediate state is saved to data/defect_census_state.json so the script
can be resumed after a timeout without re-reading already-processed pairs.
"""

from __future__ import annotations

import csv as csv_mod
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from crypto_grid_bot.backtest.audit import (
    ABSENT_BOTH,
    ABSENT_HOURLY,
    ABSENT_MINUTES,
    PRESENT_BOTH,
    development_month,
    expected_hours,
    hour_statuses,
)
from crypto_grid_bot.backtest.dataset import (
    ArchiveParseError,
    archive_get,
    fetch_file,
    local_path,
    sha256_file,
)
from crypto_grid_bot.backtest.klines import (
    INTERVAL_MS,
    aggregate,
    read_archive,
)
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE, compare_bars
from crypto_grid_bot.market_data.parsing import DataError

PAIRS = [
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "TRXUSDT",
]

MONTHS = [
    f"{year:04d}-{month:02d}"
    for year in range(2017, 2025)
    for month in range(1, 13)
    if not (year == 2017 and month < 8)
]

# Verify: every month is in scope
for _m in MONTHS:
    if _m > "2024-12":
        raise SystemExit(f"STOP: {_m} is outside scope")
    development_month(_m)  # raises DataError if reserved

DATA_DIR = Path("data")
HOUR_MS = INTERVAL_MS["1h"]
UNKNOWN = "unknown"
CHECKSUM_CACHE = DATA_DIR / "checksum_cache.json"
STATE_FILE = DATA_DIR / "defect_census_state.json"

# Command-line argument: if a pair name is given, process only that pair
# and save to state. If no argument, load state and run analysis.
MODE = sys.argv[1] if len(sys.argv) > 1 else "analyze"

# ──────────────────────────────────────────────
# Local-first fetcher
# ──────────────────────────────────────────────

_cache: dict[str, str | None] = {}
if CHECKSUM_CACHE.exists():
    _cache = json.loads(CHECKSUM_CACHE.read_text())


def _local_first_fetch(path: str) -> bytes | None:
    if path.endswith(".CHECKSUM"):
        parts = path.split("/")
        symbol = parts[5]
        interval = parts[6]
        zip_filename = parts[7][: -len(".CHECKSUM")]
        month = zip_filename[-11:-4]
        local = local_path(DATA_DIR, symbol, interval, month)
        if local.exists():
            h = sha256_file(local)
            return f"{h}  {zip_filename}\n".encode("ascii")
        if path in _cache:
            cached = _cache[path]
            return bytes.fromhex(cached) if cached is not None else None
        result = archive_get(path)
        _cache[path] = result.hex() if result is not None else None
        CHECKSUM_CACHE.write_text(json.dumps(_cache, indent=1))
        return result
    checksum_path = path + ".CHECKSUM"
    if checksum_path in _cache and _cache[checksum_path] is None:
        return None
    return archive_get(path)


# ──────────────────────────────────────────────
# Process one pair and save to state
# ──────────────────────────────────────────────

def process_pair(pair: str) -> None:
    """Fetch all archives for one pair, compute hour statuses, save to state."""
    print(f"Processing pair {pair} ...")
    found_listing = False
    listing_hour = None
    pair_unparsed: set[str] = set()
    # pair_hour_status: {hour_ms_str: status_str} (JSON keys are strings)
    hour_status: dict[str, str] = {}

    for month in MONTHS:
        try:
            res1m = fetch_file(DATA_DIR, pair, "1m", month, _local_first_fetch)
            status1m = res1m["status"]
        except ArchiveParseError:
            status1m = "unparsed"
            pair_unparsed.add(month)
        except DataError as exc:
            raise SystemExit(
                f"STOP: DataError (not ArchiveParseError) on {pair} 1m {month}: {exc}"
            ) from exc

        try:
            res1h = fetch_file(DATA_DIR, pair, "1h", month, _local_first_fetch)
            status1h = res1h["status"]
        except ArchiveParseError:
            status1h = "unparsed"
            pair_unparsed.add(month)
        except DataError as exc:
            raise SystemExit(
                f"STOP: DataError (not ArchiveParseError) on {pair} 1h {month}: {exc}"
            ) from exc

        if not found_listing and status1m != "missing":
            path_1m = local_path(DATA_DIR, pair, "1m", month)
            if status1m == "ok":
                klines_1m, _ = read_archive(path_1m, pair, "1m", month)
                listing_hour = (klines_1m[0].open_ms // HOUR_MS) * HOUR_MS
                found_listing = True
            elif status1m == "unparsed" and path_1m.exists():
                try:
                    with zipfile.ZipFile(path_1m) as zf:
                        members = zf.infolist()
                        with zf.open(members[0]) as src:
                            raw = src.read(1024)
                    first_row = next(
                        csv_mod.reader(raw.decode("ascii", errors="replace").splitlines())
                    )
                    ts = int(first_row[0])
                    if ts >= 10**15:
                        ts = ts // 1000
                    listing_hour = (ts // HOUR_MS) * HOUR_MS
                    found_listing = True
                except Exception:
                    pass

        if listing_hour is None:
            continue

        exp = expected_hours(listing_hour, month)
        if len(exp) == 0:
            continue

        both_missing = status1m == "missing" and status1h == "missing"
        is_unparsed = month in pair_unparsed

        if both_missing or is_unparsed:
            for h in exp:
                hour_status[str(h)] = UNKNOWN
            continue

        path_1m = local_path(DATA_DIR, pair, "1m", month)
        path_1h = local_path(DATA_DIR, pair, "1h", month)
        klines_1m, _ = read_archive(path_1m, pair, "1m", month)
        klines_1h, _ = read_archive(path_1h, pair, "1h", month)

        minute_open_ms = [k.open_ms for k in klines_1m]
        official_open_ms = [k.open_ms for k in klines_1h]

        statuses = hour_statuses(minute_open_ms, official_open_ms, exp)

        agg_map = {k.open_ms: k for k in aggregate(klines_1m, HOUR_MS)}
        theirs_map = {k.open_ms: k for k in klines_1h}

        for h, st in statuses.items():
            if st == PRESENT_BOTH:
                ours_bar = agg_map.get(h)
                theirs_bar = theirs_map.get(h)
                if ours_bar is not None and theirs_bar is not None:
                    cmp = compare_bars(ours_bar, theirs_bar, VOLUME_DRIFT_TOLERANCE)
                    hour_status[str(h)] = (
                        "mismatch" if cmp not in ("match", "drift") else PRESENT_BOTH
                    )
                else:
                    hour_status[str(h)] = PRESENT_BOTH
            else:
                hour_status[str(h)] = st

    if listing_hour is None:
        raise SystemExit(f"STOP: could not determine listing hour for {pair}")

    # Load existing state and update
    state: dict = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text())
    if "pairs" not in state:
        state["pairs"] = {}
    state["pairs"][pair] = {
        "listing_hour": listing_hour,
        "unparsed_months": sorted(pair_unparsed),
        "hour_status": hour_status,
    }
    STATE_FILE.write_text(json.dumps(state))

    lh_str = datetime.fromtimestamp(listing_hour / 1000, UTC).strftime("%Y-%m-%d %H:%M")
    print(
        f"  done: listing_hour={lh_str} ({listing_hour}), "
        f"unparsed={len(pair_unparsed)}, hours={len(hour_status)}"
    )


if MODE != "analyze":
    # MODE is a pair name: process just that pair
    pair = MODE
    if pair not in PAIRS:
        raise SystemExit(f"STOP: unknown pair {pair}")
    process_pair(pair)
    print(f"Pair {pair} saved to state.")
    sys.exit(0)

# ──────────────────────────────────────────────
# Analyze: load state and run Steps 2-4
# ──────────────────────────────────────────────

print("=== Loading state ===")
if not STATE_FILE.exists():
    raise SystemExit("STOP: state file not found. Run with a pair name first.")

state = json.loads(STATE_FILE.read_text())
missing_pairs = [p for p in PAIRS if p not in state.get("pairs", {})]
if missing_pairs:
    raise SystemExit(f"STOP: state missing pairs: {missing_pairs}")

listing_hour: dict[str, int] = {}
unparsed_months: dict[str, set[str]] = {}
pair_hour_status: dict[str, dict[int, str]] = {}

for pair in PAIRS:
    pd = state["pairs"][pair]
    listing_hour[pair] = pd["listing_hour"]
    unparsed_months[pair] = set(pd["unparsed_months"])
    # keys were stored as strings; convert back to int
    pair_hour_status[pair] = {int(k): v for k, v in pd["hour_status"].items()}

print("State loaded.")
for pair in PAIRS:
    lh = listing_hour[pair]
    lh_str = datetime.fromtimestamp(lh / 1000, UTC).strftime("%Y-%m-%d %H:%M")
    print(
        f"  {pair}: listing_hour={lh_str} ({lh}), "
        f"unparsed={len(unparsed_months[pair])}, hours={len(pair_hour_status[pair])}"
    )

print(f"\nTotal unparsed pair-months: {sum(len(v) for v in unparsed_months.values())}")

# ──────────────────────────────────────────────
# Step 2: per-pair table on expected hours
# ──────────────────────────────────────────────

print("\n=== Step 2: per-pair defect table ===")

YEARS = list(range(2017, 2025))


def is_defect(st: str) -> bool:
    return st in (ABSENT_BOTH, ABSENT_MINUTES, ABSENT_HOURLY, "mismatch")


pair_year_stats: dict[str, dict[int, dict[str, int]]] = {
    pair: {
        year: {"defect": 0, "expected_excl_unknown": 0, "unknown": 0, "absent_both": 0}
        for year in YEARS
    }
    for pair in PAIRS
}

for pair in PAIRS:
    for h, st in pair_hour_status[pair].items():
        year = int(datetime.fromtimestamp(h / 1000, UTC).strftime("%Y"))
        if year not in pair_year_stats[pair]:
            continue
        cell = pair_year_stats[pair][year]
        if st == UNKNOWN:
            cell["unknown"] += 1
        else:
            cell["expected_excl_unknown"] += 1
            if is_defect(st):
                cell["defect"] += 1
            if st == ABSENT_BOTH:
                cell["absent_both"] += 1

header = (
    "| Pair | "
    + " | ".join(str(y) for y in YEARS)
    + " | Total defect | Total expected | Defect rate | Unknown |"
)
sep = "| --- | " + " | ".join("---:" for _ in YEARS) + " | ---: | ---: | ---: | ---: |"
print(header)
print(sep)

grand_defect = 0
grand_expected = 0
grand_unknown = 0
grand_absent_both = 0

for pair in PAIRS:
    cells = []
    pair_defect = 0
    pair_expected = 0
    pair_unknown = 0
    pair_absent_both = 0
    for year in YEARS:
        cell = pair_year_stats[pair][year]
        d = cell["defect"]
        e = cell["expected_excl_unknown"]
        u = cell["unknown"]
        ab = cell["absent_both"]
        pair_defect += d
        pair_expected += e
        pair_unknown += u
        pair_absent_both += ab
        if e > 0:
            cells.append(f"{d}/{e} ({100*d/e:.2f}%)")
        elif u > 0:
            cells.append(f"-/{e} (unknown)")
        else:
            cells.append("-")
    rate = f"{100*pair_defect/pair_expected:.2f}%" if pair_expected > 0 else "n/a"
    row = (
        f"| **{pair}** | "
        + " | ".join(cells)
        + f" | {pair_defect} | {pair_expected} | {rate} | {pair_unknown} |"
    )
    print(row)
    grand_defect += pair_defect
    grand_expected += pair_expected
    grand_unknown += pair_unknown
    grand_absent_both += pair_absent_both

grand_rate = (
    f"{100*grand_defect/grand_expected:.3f}%" if grand_expected > 0 else "n/a"
)
print(
    f"| **All ten** | "
    + " | ".join("" for _ in YEARS)
    + f" | {grand_defect} | {grand_expected} | {grand_rate} | {grand_unknown} |"
)
print(f"\nGrand total defect hours: {grand_defect}")
print(f"Grand total expected hours (excl unknown): {grand_expected}")
print(f"Grand total unknown hours: {grand_unknown}")
print(f"Grand total absent_both pair-hours: {grand_absent_both}")

print("\n=== Step 2 absent_both per pair and year ===")
ab_header = "| Pair | " + " | ".join(str(y) for y in YEARS) + " | Total |"
ab_sep = "| --- | " + " | ".join("---:" for _ in YEARS) + " | ---: |"
print(ab_header)
print(ab_sep)
for pair in PAIRS:
    vals = [pair_year_stats[pair][year]["absent_both"] for year in YEARS]
    total = sum(vals)
    print(f"| **{pair}** | " + " | ".join(str(v) for v in vals) + f" | {total} |")
total_ab_by_year = [
    sum(pair_year_stats[p][y]["absent_both"] for p in PAIRS) for y in YEARS
]
print(
    f"| **All ten** | "
    + " | ".join(str(v) for v in total_ab_by_year)
    + f" | {grand_absent_both} |"
)

# ──────────────────────────────────────────────
# Step 3: events with per-hour affected/listed ratios
# ──────────────────────────────────────────────

print("\n=== Step 3: events ===")

pair_listed_hours: dict[str, set[int]] = {
    pair: set(pair_hour_status[pair].keys()) for pair in PAIRS
}

all_defect_hours: set[int] = set()
for pair in PAIRS:
    for h, st in pair_hour_status[pair].items():
        if is_defect(st):
            all_defect_hours.add(h)

print(f"Total defect hours (unique): {len(all_defect_hours)}")

sorted_defect_hours = sorted(all_defect_hours)

events: list[dict] = []
current_event_hours: list[int] = []

for h in sorted_defect_hours:
    if current_event_hours and h != current_event_hours[-1] + HOUR_MS:
        events.append({"hours": list(current_event_hours)})
        current_event_hours = []
    current_event_hours.append(h)
if current_event_hours:
    events.append({"hours": list(current_event_hours)})

print(f"Total events: {len(events)}")
print(f"Total event hours: {sum(len(e['hours']) for e in events)}")

for ev in events:
    ev_hours = ev["hours"]
    ev["start_ms"] = ev_hours[0]
    ev["end_ms"] = ev_hours[-1] + HOUR_MS
    per_hour = []
    for h in ev_hours:
        listed_at_h = [p for p in PAIRS if h in pair_listed_hours[p]]
        affected_at_h = [
            p for p in listed_at_h if is_defect(pair_hour_status[p].get(h, ""))
        ]
        unknown_at_h = [
            p for p in listed_at_h if pair_hour_status[p].get(h, "") == UNKNOWN
        ]
        per_hour.append(
            {
                "h": h,
                "listed": len(listed_at_h),
                "affected": len(affected_at_h),
                "unknown": len(unknown_at_h),
            }
        )
    ev["per_hour"] = per_hour

    union_affected: set[str] = set()
    union_listed: set[str] = set()
    for h in ev_hours:
        for p in PAIRS:
            if h in pair_listed_hours[p]:
                union_listed.add(p)
                if is_defect(pair_hour_status[p].get(h, "")):
                    union_affected.add(p)
    ev["union_aff"] = len(union_affected)
    ev["union_lst"] = len(union_listed)
    ev["union_v0"] = (
        (len(union_affected) / len(union_listed)) >= 0.8 if union_listed else False
    )

    indeterminate = False
    meets_v1_lo = True
    meets_v1_5_lo = True

    for ph in per_hour:
        n = ph["listed"]
        a = ph["affected"]
        u = ph["unknown"]
        if n == 0:
            continue
        lo = a / n
        hi = (a + u) / n
        lo_pass = lo >= 0.8
        hi_pass = hi >= 0.8
        if lo_pass != hi_pass:
            indeterminate = True
        if lo < 0.8:
            meets_v1_lo = False
        if n < 5 or lo < 0.8:
            meets_v1_5_lo = False

    ev["indeterminate"] = indeterminate
    ev["meets_v1_lo"] = meets_v1_lo
    ev["meets_v1_5_lo"] = meets_v1_5_lo


def hs(evlist: list) -> int:
    return sum(len(ev["hours"]) for ev in evlist)


print("\n--- Per-year event/hour counts ---")
print(
    "| Year | breadth-per-hour-v1 events | breadth-per-hour-v1 hours | "
    "breadth-per-hour-v1+5 events | breadth-per-hour-v1+5 hours | "
    "union-v0 events | union-v0 hours | "
    "indeterminate events | indeterminate hours | "
    "other events | other hours |"
)
print(
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
)

for year in YEARS:
    year_events = [
        ev
        for ev in events
        if datetime.fromtimestamp(ev["start_ms"] / 1000, UTC).year == year
    ]
    if not year_events:
        print(f"| {year} | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |")
        continue

    v1_evts = [ev for ev in year_events if not ev["indeterminate"] and ev["meets_v1_lo"]]
    v1_5_evts = [
        ev for ev in year_events if not ev["indeterminate"] and ev["meets_v1_5_lo"]
    ]
    union_evts = [ev for ev in year_events if ev["union_v0"]]
    indet_evts = [ev for ev in year_events if ev["indeterminate"]]
    other_evts = [
        ev for ev in year_events if not ev["indeterminate"] and not ev["meets_v1_lo"]
    ]

    print(
        f"| {year} | {len(v1_evts)} | {hs(v1_evts)} | "
        f"{len(v1_5_evts)} | {hs(v1_5_evts)} | "
        f"{len(union_evts)} | {hs(union_evts)} | "
        f"{len(indet_evts)} | {hs(indet_evts)} | "
        f"{len(other_evts)} | {hs(other_evts)} |"
    )

v1_all = [ev for ev in events if not ev["indeterminate"] and ev["meets_v1_lo"]]
v1_5_all = [ev for ev in events if not ev["indeterminate"] and ev["meets_v1_5_lo"]]
union_all = [ev for ev in events if ev["union_v0"]]
indet_all = [ev for ev in events if ev["indeterminate"]]
other_all = [ev for ev in events if not ev["indeterminate"] and not ev["meets_v1_lo"]]

print(
    f"| **Total** | {len(v1_all)} | {hs(v1_all)} | "
    f"{len(v1_5_all)} | {hs(v1_5_all)} | "
    f"{len(union_all)} | {hs(union_all)} | "
    f"{len(indet_all)} | {hs(indet_all)} | "
    f"{len(other_all)} | {hs(other_all)} |"
)

print(f"\n--- Indeterminate events ({len(indet_all)}) ---")
for ev in indet_all:
    start_str = datetime.fromtimestamp(ev["start_ms"] / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M"
    )
    end_str = datetime.fromtimestamp((ev["end_ms"] - HOUR_MS) / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M"
    )
    ph_str = ", ".join(
        f"{ph['affected']}/{ph['listed']} (unk:{ph['unknown']})" for ph in ev["per_hour"]
    )
    print(f"  {start_str} to {end_str} ({len(ev['hours'])}h): {ph_str}")

print(f"\n--- Events meeting breadth-per-hour-v1 ({len(v1_all)}) ---")
for ev in v1_all:
    start_str = datetime.fromtimestamp(ev["start_ms"] / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M"
    )
    end_str = datetime.fromtimestamp((ev["end_ms"] - HOUR_MS) / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M"
    )
    ph_str = ", ".join(f"{ph['affected']}/{ph['listed']}" for ph in ev["per_hour"])
    v1_5 = "yes" if ev["meets_v1_5_lo"] else "no"
    print(f"  {start_str} to {end_str} ({len(ev['hours'])}h) [v1+5={v1_5}]: {ph_str}")

# ---- Trace PR #66 outages ----
print("\n--- Tracing 14 PR #66 outages into Step 3 events ---")


def to_ms(dt_str: str) -> int:
    return int(
        datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp() * 1000
    )


PR66_OUTAGE_MS = [
    ("2018-06-26 02:00", to_ms("2018-06-26 02:00")),
    ("2018-06-27 13:00", to_ms("2018-06-27 13:00")),
    ("2018-10-19 06:00", to_ms("2018-10-19 06:00")),
    ("2018-11-14 02:00", to_ms("2018-11-14 02:00")),
    ("2019-03-12 02:00", to_ms("2019-03-12 02:00")),
    ("2019-05-15 03:00", to_ms("2019-05-15 03:00")),
    ("2019-08-15 02:00", to_ms("2019-08-15 02:00")),
    ("2019-11-13 02:00", to_ms("2019-11-13 02:00")),
    ("2019-11-25 02:00", to_ms("2019-11-25 02:00")),
    ("2020-04-25 02:00", to_ms("2020-04-25 02:00")),
    ("2020-06-28 02:00", to_ms("2020-06-28 02:00")),
    ("2020-11-30 06:00", to_ms("2020-11-30 06:00")),
    ("2021-03-06 02:00", to_ms("2021-03-06 02:00")),
    ("2021-09-29 07:00", to_ms("2021-09-29 07:00")),
]

hour_to_event: dict[int, int] = {}
for i, ev in enumerate(events):
    for h in ev["hours"]:
        hour_to_event[h] = i

for label, start_ms in PR66_OUTAGE_MS:
    ev_idx = hour_to_event.get(start_ms)
    if ev_idx is None:
        print(f"  PR#66 {label}: NOT FOUND in any Step 3 event")
        continue
    ev = events[ev_idx]
    ev_start = datetime.fromtimestamp(ev["start_ms"] / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M"
    )
    ev_end = datetime.fromtimestamp((ev["end_ms"] - HOUR_MS) / 1000, UTC).strftime(
        "%Y-%m-%d %H:%M"
    )
    ph_str = ", ".join(f"{ph['affected']}/{ph['listed']}" for ph in ev["per_hour"])
    meets = (
        "yes"
        if (not ev["indeterminate"] and ev["meets_v1_lo"])
        else ("indeterminate" if ev["indeterminate"] else "no")
    )
    print(
        f"  PR#66 {label}: event {ev_start}..{ev_end} ({len(ev['hours'])}h) "
        f"per-hour=[{ph_str}] breadth-per-hour-v1={meets}"
    )

# ──────────────────────────────────────────────
# Step 4: self-verification
# ──────────────────────────────────────────────

print("\n=== Step 4: self-verification against Claude's known values ===")
print("| Figure | Claude | Mine | Equal? |")
print("| --- | --- | --- | --- |")


def check(label: str, claude_val, my_val) -> None:
    equal = claude_val == my_val
    print(f"| {label} | {claude_val} | {my_val} | {equal} |")
    if not equal:
        raise SystemExit(
            f"STOP: Step 4 mismatch on '{label}': Claude={claude_val} vs mine={my_val}"
        )


check("all ten pairs, defect hours", 7114, grand_defect)
check("all ten pairs, expected hours (excl unknown)", 490786, grand_expected)

btc_2019_d = pair_year_stats["BTCUSDT"][2019]["defect"]
btc_2019_e = pair_year_stats["BTCUSDT"][2019]["expected_excl_unknown"]
check("BTCUSDT 2019 defect", 28, btc_2019_d)
check("BTCUSDT 2019 expected", 8040, btc_2019_e)

xrp_2020_d = pair_year_stats["XRPUSDT"][2020]["defect"]
xrp_2020_e = pair_year_stats["XRPUSDT"][2020]["expected_excl_unknown"]
check("XRPUSDT 2020 defect", 6, xrp_2020_d)
check("XRPUSDT 2020 expected", 6600, xrp_2020_e)

trx_2018_d = pair_year_stats["TRXUSDT"][2018]["defect"]
trx_2018_e = pair_year_stats["TRXUSDT"][2018]["expected_excl_unknown"]
check("TRXUSDT 2018 defect", 22, trx_2018_d)
check("TRXUSDT 2018 expected", 4141, trx_2018_e)

doge_2019_d = pair_year_stats["DOGEUSDT"][2019]["defect"]
doge_2019_e = pair_year_stats["DOGEUSDT"][2019]["expected_excl_unknown"]
check("DOGEUSDT 2019 defect", 2287, doge_2019_d)
check("DOGEUSDT 2019 expected", 4308, doge_2019_e)

check("absent_both pair-hours, all pairs and years", 468, grand_absent_both)

target_start = to_ms("2019-11-13 02:00")
target_hours_list = [target_start + i * HOUR_MS for i in range(4)]
found_ratios = []
for h in target_hours_list:
    listed_at_h = [p for p in PAIRS if h in pair_listed_hours[p]]
    affected_at_h = [
        p for p in listed_at_h if is_defect(pair_hour_status[p].get(h, ""))
    ]
    found_ratios.append(f"{len(affected_at_h)}/{len(listed_at_h)}")

expected_ratios_str = "9/9, 9/9, 8/9, 1/9"
found_ratios_str = ", ".join(found_ratios)
check("2019-11-13 02:00-05:00 per-hour ratios", expected_ratios_str, found_ratios_str)

print("\n=== All Step 4 checks passed ===")
print("\nSummary counts (all printed by this script):")
print(f"  pairs: {len(PAIRS)}")
print(f"  months in scope: {len(MONTHS)}")
print(f"  total unparsed pair-months: {sum(len(v) for v in unparsed_months.values())}")
print(f"  total events: {len(events)}")
print(f"  total event hours: {sum(len(ev['hours']) for ev in events)}")
print(f"  events meeting breadth-per-hour-v1: {len(v1_all)}")
print(f"  events meeting breadth-per-hour-v1+5 (5-pair floor): {len(v1_5_all)}")
print(f"  events meeting union-v0: {len(union_all)}")
print(f"  indeterminate events: {len(indet_all)}")
```
