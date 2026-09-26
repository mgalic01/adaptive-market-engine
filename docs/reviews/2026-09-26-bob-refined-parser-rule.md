# Refined parser rule measurement on the 14 unparsed months

- **Task:** [`docs/tasks/2026-09-26-bob-refined-parser-rule.md`](../tasks/2026-09-26-bob-refined-parser-rule.md)
- **Author:** Bob (task runner)
- **Date:** 2026-09-26
- **Commit:** `8fe6484447bcc86ec825cdefa5bb1e79c372e636`
- **Python version:** `Python 3.12.14`
- **Start:** `Sat Sep 26 10:03:06 UTC 2026`
- **End:** `Sat Sep 26 10:28:00 UTC 2026`
- **Script:** `data/refined_rule.py`
  SHA-256: `084a2be0b884774aab6e68ed5e35a8f932ec3b8eefbbaafa37f59e302fca6c2e`
  (source in [Appendix](#appendix-datarefined_rulepy-source); hash verified below) *[Corrections at review (Claude, 2026-09-26): Claude's independent script reproduces narrow 82, refined 99 and the single DOGEUSDT failure; two statements are marked "Correction at review" in place; reasons in the feedback on PR #65.]*

---

## Commands run

1. `date -u` → `Sat Sep 26 10:03:06 UTC 2026`
2. `git rev-parse HEAD` → `8fe6484447bcc86ec825cdefa5bb1e79c372e636`
3. `python --version` → `Python 3.12.14`
4. `python data/refined_rule.py` (output below; data cached from prior run, network used only for first fetch)
5. `sha256sum data/refined_rule.py` → `084a2be0b884774aab6e68ed5e35a8f932ec3b8eefbbaafa37f59e302fca6c2e`
6. `date -u` → `Sat Sep 26 10:28:00 UTC 2026`

Independent verification (separate inline script):
- unaligned-open totals confirmed: `2017-12 1m = 61203 OK`, `2018-02 1m = 4804 OK`, `2018-02 1h = 172 OK`
- failing (c) rows confirmed: 2 mismatch rows (DOGEUSDT 2020-02 1m and 1h), 18 not_testable (belong to parse-failing files)
- narrow usable = 82, refined usable without (c) = 100, refined usable with (c) = 99

---

## Unaligned-open count verification

The task says to reproduce three reference counts as the check that condition (a) is implemented.
These are **totals across all pairs** for a given month and interval.

| Interval | Month   | Count (this run) | Expected | Status |
| ---      | ---     | ---:             | ---:     | ---    |
| 1m       | 2017-12 | 61,203           | 61,203   | OK     |
| 1m       | 2018-02 | 4,804            | 4,804    | OK     |
| 1h       | 2018-02 | 172              | 172      | OK     |

Per-file breakdown (non-zero only):

| Symbol   | Interval | Month   | Unaligned-open rows |
| ---      | ---      | ---     | ---:                |
| BTCUSDT  | 1m       | 2017-12 | 20,401              |
| ETHUSDT  | 1m       | 2017-12 | 20,401              |
| BNBUSDT  | 1m       | 2017-12 | 20,401              |
| BTCUSDT  | 1m       | 2018-02 | 1,201               |
| BTCUSDT  | 1h       | 2018-02 | 43                  |
| ETHUSDT  | 1m       | 2018-02 | 1,201               |
| ETHUSDT  | 1h       | 2018-02 | 43                  |
| BNBUSDT  | 1m       | 2018-02 | 1,201               |
| BNBUSDT  | 1h       | 2018-02 | 43                  |
| LTCUSDT  | 1m       | 2018-02 | 1,201               |
| LTCUSDT  | 1h       | 2018-02 | 43                  |

3 pairs × 20,401 = 61,203 ✓  
4 pairs × 1,201 = 4,804 ✓  
4 pairs × 43 = 172 ✓

---

## Step 1 and Step 2 results: per-file anomalous row conditions

Column definitions:
- **anomalous**: rows where `close != open + step - 1`
- **(a)**: of those, rows with `open % step == 0`
- **(a+b)**: rows meeting (a) AND (b) — last row of file OR next open ≥ open+step
- **(a+b+c)**: rows meeting (a+b) that also pass the strict hour check (compare_bars result = "match"); "n/a" when the refined fixed text did not parse
- **refined_parse**: result of `parse_rows(fixed_text_refined, interval, month)`
- **narrow_parse**: result of `parse_rows(fixed_text_narrow, interval, month)`

```
month    symbol     ivl   anomalous    (a)   (a+b)   (a+b+c)  refined_parse  narrow_parse
2017-09  BTCUSDT    1m            1      1       1         1             ok            ok
2017-09  BTCUSDT    1h            1      1       1         1             ok            ok
2017-09  ETHUSDT    1m            1      1       1         1             ok            ok
2017-09  ETHUSDT    1h            1      1       1         1             ok            ok
2017-12  BTCUSDT    1m            3      2       1       n/a          error         error
2017-12  BTCUSDT    1h            1      1       1       n/a             ok         error
2017-12  ETHUSDT    1m            3      2       1       n/a          error         error
2017-12  ETHUSDT    1h            1      1       1       n/a             ok         error
2017-12  BNBUSDT    1m            3      2       1       n/a          error         error
2017-12  BNBUSDT    1h            1      1       1       n/a             ok         error
2017-12  LTCUSDT    1m            2      2       2         2             ok            ok
2017-12  LTCUSDT    1h            1      1       1         1             ok         error
2018-01  BTCUSDT    1m            1      1       1         1             ok            ok
2018-01  BTCUSDT    1h            1      1       1         1             ok            ok
2018-01  ETHUSDT    1m            1      1       1         1             ok            ok
2018-01  ETHUSDT    1h            1      1       1         1             ok            ok
2018-01  BNBUSDT    1m            1      1       1         1             ok            ok
2018-01  BNBUSDT    1h            1      1       1         1             ok            ok
2018-01  LTCUSDT    1m            1      1       1         1             ok            ok
2018-01  LTCUSDT    1h            1      1       1         1             ok            ok
2018-02  BTCUSDT    1m            3      2       2       n/a          error         error
2018-02  BTCUSDT    1h            2      1       1       n/a          error         error
2018-02  ETHUSDT    1m            3      2       2       n/a          error         error
2018-02  ETHUSDT    1h            2      1       1       n/a          error         error
2018-02  BNBUSDT    1m            3      2       2       n/a          error         error
2018-02  BNBUSDT    1h            2      1       1       n/a          error         error
2018-02  LTCUSDT    1m            3      2       2       n/a          error         error
2018-02  LTCUSDT    1h            2      1       1       n/a          error         error
2018-07  BTCUSDT    1m            1      1       1         1             ok            ok
2018-07  BTCUSDT    1h            1      1       1         1             ok            ok
2018-07  ETHUSDT    1m            1      1       1         1             ok            ok
2018-07  ETHUSDT    1h            1      1       1         1             ok            ok
2018-07  BNBUSDT    1m            1      1       1         1             ok            ok
2018-07  BNBUSDT    1h            1      1       1         1             ok            ok
2018-07  XRPUSDT    1m            1      1       1         1             ok            ok
2018-07  XRPUSDT    1h            1      1       1         1             ok            ok
2018-07  ADAUSDT    1m            1      1       1         1             ok            ok
2018-07  ADAUSDT    1h            1      1       1         1             ok            ok
2018-07  LTCUSDT    1m            1      1       1         1             ok            ok
2018-07  LTCUSDT    1h            1      1       1         1             ok            ok
2018-07  TRXUSDT    1m            1      1       1         1             ok            ok
2018-07  TRXUSDT    1h            1      1       1         1             ok            ok
2019-06  BTCUSDT    1m            1      1       1         1             ok            ok
2019-06  BTCUSDT    1h            1      1       1         1             ok         error
2019-06  ETHUSDT    1m            1      1       1         1             ok            ok
2019-06  ETHUSDT    1h            1      1       1         1             ok         error
2019-06  BNBUSDT    1m            1      1       1         1             ok            ok
2019-06  BNBUSDT    1h            1      1       1         1             ok         error
2019-06  XRPUSDT    1m            1      1       1         1             ok            ok
2019-06  XRPUSDT    1h            1      1       1         1             ok         error
2019-06  ADAUSDT    1m            1      1       1         1             ok            ok
2019-06  ADAUSDT    1h            1      1       1         1             ok         error
2019-06  LTCUSDT    1m            1      1       1         1             ok            ok
2019-06  LTCUSDT    1h            1      1       1         1             ok         error
2019-06  LINKUSDT   1m            1      1       1         1             ok            ok
2019-06  LINKUSDT   1h            1      1       1         1             ok         error
2019-06  TRXUSDT    1m            1      1       1         1             ok            ok
2019-06  TRXUSDT    1h            1      1       1         1             ok         error
2020-02  BTCUSDT    1m            1      1       1         1             ok            ok
2020-02  BTCUSDT    1h            1      1       1         1             ok            ok
2020-02  ETHUSDT    1m            1      1       1         1             ok            ok
2020-02  ETHUSDT    1h            1      1       1         1             ok            ok
2020-02  BNBUSDT    1m            1      1       1         1             ok            ok
2020-02  BNBUSDT    1h            1      1       1         1             ok            ok
2020-02  XRPUSDT    1m            1      1       1         1             ok            ok
2020-02  XRPUSDT    1h            1      1       1         1             ok            ok
2020-02  ADAUSDT    1m            1      1       1         1             ok            ok
2020-02  ADAUSDT    1h            1      1       1         1             ok            ok
2020-02  DOGEUSDT   1m            1      1       1         0             ok            ok
2020-02  DOGEUSDT   1h            1      1       1         0             ok            ok
2020-02  LTCUSDT    1m            1      1       1         1             ok            ok
2020-02  LTCUSDT    1h            1      1       1         1             ok            ok
2020-02  LINKUSDT   1m            1      1       1         1             ok            ok
2020-02  LINKUSDT   1h            1      1       1         1             ok            ok
2020-02  TRXUSDT    1m            1      1       1         1             ok            ok
2020-02  TRXUSDT    1h            1      1       1         1             ok            ok
2020-03  BTCUSDT    1m            1      1       1         1             ok            ok
2020-03  BTCUSDT    1h            1      1       1         1             ok            ok
2020-03  ETHUSDT    1m            1      1       1         1             ok            ok
2020-03  ETHUSDT    1h            1      1       1         1             ok            ok
2020-03  BNBUSDT    1m            1      1       1         1             ok            ok
2020-03  BNBUSDT    1h            1      1       1         1             ok            ok
2020-03  XRPUSDT    1m            1      1       1         1             ok            ok
2020-03  XRPUSDT    1h            1      1       1         1             ok            ok
2020-03  ADAUSDT    1m            1      1       1         1             ok            ok
2020-03  ADAUSDT    1h            1      1       1         1             ok            ok
2020-03  DOGEUSDT   1m            1      1       1         1             ok            ok
2020-03  DOGEUSDT   1h            1      1       1         1             ok            ok
2020-03  LTCUSDT    1m            1      1       1         1             ok            ok
2020-03  LTCUSDT    1h            1      1       1         1             ok            ok
2020-03  LINKUSDT   1m            1      1       1         1             ok            ok
2020-03  LINKUSDT   1h            1      1       1         1             ok            ok
2020-03  TRXUSDT    1m            1      1       1         1             ok            ok
2020-03  TRXUSDT    1h            1      1       1         1             ok            ok
2020-12  BTCUSDT    1m            1      1       1         1             ok            ok
2020-12  BTCUSDT    1h            1      1       1         1             ok            ok
2020-12  ETHUSDT    1m            1      1       1         1             ok            ok
2020-12  ETHUSDT    1h            1      1       1         1             ok            ok
2020-12  BNBUSDT    1m            1      1       1         1             ok            ok
2020-12  BNBUSDT    1h            1      1       1         1             ok            ok
2020-12  SOLUSDT    1m            1      1       1         1             ok            ok
2020-12  SOLUSDT    1h            1      1       1         1             ok            ok
2020-12  XRPUSDT    1m            1      1       1         1             ok            ok
2020-12  XRPUSDT    1h            1      1       1         1             ok            ok
2020-12  ADAUSDT    1m            1      1       1         1             ok            ok
2020-12  ADAUSDT    1h            1      1       1         1             ok            ok
2020-12  DOGEUSDT   1m            1      1       1         1             ok            ok
2020-12  DOGEUSDT   1h            1      1       1         1             ok            ok
2020-12  LTCUSDT    1m            1      1       1         1             ok            ok
2020-12  LTCUSDT    1h            1      1       1         1             ok            ok
2020-12  LINKUSDT   1m            1      1       1         1             ok            ok
2020-12  LINKUSDT   1h            1      1       1         1             ok            ok
2020-12  TRXUSDT    1m            1      1       1         1             ok            ok
2020-12  TRXUSDT    1h            1      1       1         1             ok            ok
2021-02  BTCUSDT    1m            1      1       1         1             ok            ok
2021-02  BTCUSDT    1h            1      1       1         1             ok            ok
2021-02  ETHUSDT    1m            1      1       1         1             ok            ok
2021-02  ETHUSDT    1h            1      1       1         1             ok            ok
2021-02  BNBUSDT    1m            1      1       1         1             ok            ok
2021-02  BNBUSDT    1h            1      1       1         1             ok            ok
2021-02  SOLUSDT    1m            1      1       1         1             ok            ok
2021-02  SOLUSDT    1h            1      1       1         1             ok            ok
2021-02  XRPUSDT    1m            1      1       1         1             ok            ok
2021-02  XRPUSDT    1h            1      1       1         1             ok            ok
2021-02  ADAUSDT    1m            1      1       1         1             ok            ok
2021-02  ADAUSDT    1h            1      1       1         1             ok            ok
2021-02  DOGEUSDT   1m            1      1       1         1             ok            ok
2021-02  DOGEUSDT   1h            1      1       1         1             ok            ok
2021-02  LTCUSDT    1m            1      1       1         1             ok            ok
2021-02  LTCUSDT    1h            1      1       1         1             ok            ok
2021-02  LINKUSDT   1m            1      1       1         1             ok            ok
2021-02  LINKUSDT   1h            1      1       1         1             ok            ok
2021-02  TRXUSDT    1m            1      1       1         1             ok            ok
2021-02  TRXUSDT    1h            1      1       1         1             ok            ok
2021-04  BTCUSDT    1m            1      1       1         1             ok            ok
2021-04  BTCUSDT    1h            1      1       1         1             ok            ok
2021-04  ETHUSDT    1m            1      1       1         1             ok            ok
2021-04  ETHUSDT    1h            1      1       1         1             ok            ok
2021-04  BNBUSDT    1m            1      1       1         1             ok            ok
2021-04  BNBUSDT    1h            1      1       1         1             ok            ok
2021-04  SOLUSDT    1m            1      1       1         1             ok            ok
2021-04  SOLUSDT    1h            1      1       1         1             ok            ok
2021-04  XRPUSDT    1m            1      1       1         1             ok            ok
2021-04  XRPUSDT    1h            1      1       1         1             ok            ok
2021-04  ADAUSDT    1m            1      1       1         1             ok            ok
2021-04  ADAUSDT    1h            1      1       1         1             ok            ok
2021-04  DOGEUSDT   1m            1      1       1         1             ok            ok
2021-04  DOGEUSDT   1h            1      1       1         1             ok            ok
2021-04  LTCUSDT    1m            1      1       1         1             ok            ok
2021-04  LTCUSDT    1h            1      1       1         1             ok            ok
2021-04  LINKUSDT   1m            1      1       1         1             ok            ok
2021-04  LINKUSDT   1h            1      1       1         1             ok            ok
2021-04  TRXUSDT    1m            1      1       1         1             ok            ok
2021-04  TRXUSDT    1h            1      1       1         1             ok            ok
2021-08  BTCUSDT    1m            1      1       1         1             ok            ok
2021-08  BTCUSDT    1h            1      1       1         1             ok            ok
2021-08  ETHUSDT    1m            1      1       1         1             ok            ok
2021-08  ETHUSDT    1h            1      1       1         1             ok            ok
2021-08  BNBUSDT    1m            1      1       1         1             ok            ok
2021-08  BNBUSDT    1h            1      1       1         1             ok            ok
2021-08  SOLUSDT    1m            1      1       1         1             ok            ok
2021-08  SOLUSDT    1h            1      1       1         1             ok            ok
2021-08  XRPUSDT    1m            1      1       1         1             ok            ok
2021-08  XRPUSDT    1h            1      1       1         1             ok            ok
2021-08  ADAUSDT    1m            1      1       1         1             ok            ok
2021-08  ADAUSDT    1h            1      1       1         1             ok            ok
2021-08  DOGEUSDT   1m            1      1       1         1             ok            ok
2021-08  DOGEUSDT   1h            1      1       1         1             ok            ok
2021-08  LTCUSDT    1m            1      1       1         1             ok            ok
2021-08  LTCUSDT    1h            1      1       1         1             ok            ok
2021-08  LINKUSDT   1m            1      1       1         1             ok            ok
2021-08  LINKUSDT   1h            1      1       1         1             ok            ok
2021-08  TRXUSDT    1m            1      1       1         1             ok            ok
2021-08  TRXUSDT    1h            1      1       1         1             ok            ok
2021-12  BTCUSDT    1m            1      1       1         1             ok         error
2021-12  BTCUSDT    1h            1      1       1         1             ok         error
2021-12  ETHUSDT    1m            1      1       1         1             ok         error
2021-12  ETHUSDT    1h            1      1       1         1             ok         error
2021-12  BNBUSDT    1m            1      1       1         1             ok         error
2021-12  BNBUSDT    1h            1      1       1         1             ok         error
2021-12  SOLUSDT    1m            1      1       1         1             ok         error
2021-12  SOLUSDT    1h            1      1       1         1             ok         error
2021-12  XRPUSDT    1m            0      0       0         0             ok            ok
2021-12  XRPUSDT    1h            0      0       0         0             ok            ok
2021-12  ADAUSDT    1m            1      1       1         1             ok         error
2021-12  ADAUSDT    1h            1      1       1         1             ok         error
2021-12  DOGEUSDT   1m            1      1       1         1             ok         error
2021-12  DOGEUSDT   1h            1      1       1         1             ok         error
2021-12  LTCUSDT    1m            1      1       1         1             ok         error
2021-12  LTCUSDT    1h            1      1       1         1             ok         error
2021-12  LINKUSDT   1m            1      1       1         1             ok         error
2021-12  LINKUSDT   1h            1      1       1         1             ok         error
2021-12  TRXUSDT    1m            1      1       1         1             ok         error
2021-12  TRXUSDT    1h            1      1       1         1             ok         error
2023-03  BTCUSDT    1m            1      1       1         1             ok            ok
2023-03  BTCUSDT    1h            1      1       1         1             ok            ok
2023-03  ETHUSDT    1m            1      1       1         1             ok            ok
2023-03  ETHUSDT    1h            1      1       1         1             ok            ok
2023-03  BNBUSDT    1m            1      1       1         1             ok            ok
2023-03  BNBUSDT    1h            1      1       1         1             ok            ok
2023-03  SOLUSDT    1m            1      1       1         1             ok            ok
2023-03  SOLUSDT    1h            1      1       1         1             ok            ok
2023-03  XRPUSDT    1m            1      1       1         1             ok            ok
2023-03  XRPUSDT    1h            1      1       1         1             ok            ok
2023-03  ADAUSDT    1m            1      1       1         1             ok            ok
2023-03  ADAUSDT    1h            1      1       1         1             ok            ok
2023-03  DOGEUSDT   1m            1      1       1         1             ok            ok
2023-03  DOGEUSDT   1h            1      1       1         1             ok            ok
2023-03  LTCUSDT    1m            1      1       1         1             ok            ok
2023-03  LTCUSDT    1h            1      1       1         1             ok            ok
2023-03  LINKUSDT   1m            1      1       1         1             ok            ok
2023-03  LINKUSDT   1h            1      1       1         1             ok            ok
2023-03  TRXUSDT    1m            1      1       1         1             ok            ok
2023-03  TRXUSDT    1h            1      1       1         1             ok            ok
```

Note on (a+b+c) = "n/a": the 1m file for BTC/ETH/BNB in 2017-12 and all four pairs in 2018-02 does not parse
even after the refined fix because the unaligned-open rows (open % step ≠ 0) are not addressed by the rule;
those rows fail the strict open-time check. The 1h file parses (no unaligned opens), but since the 1m fails
the pair-month is not usable regardless of (c).

---

## Rows that the rule would fix but condition (c) fails

Two rows fail condition (c) — both in DOGEUSDT 2020-02:

| Symbol  | Interval | Month   | Line  | UTC open time            | Result   |
| ---     | ---      | ---     | ---:  | ---                      | ---      |
| DOGEUSDT | 1m      | 2020-02 | 26556 | 2020-02-19T11:35:00+00:00 | mismatch |
| DOGEUSDT | 1h      | 2020-02 |   443 | 2020-02-19T11:00:00+00:00 | mismatch |

For both rows the fixed 1m bar aggregated to the `2020-02-19 11:00 UTC` hour disagrees with the official 1h bar by exactly 1 tick on the open price:

| Field  | Aggregated fixed 1m | Official 1h   | Difference   |
| ---    | ---                 | ---           | ---          |
| open   | 0.00281390          | 0.00281380    | +1.0E-7 (1 tick) |
| high   | 0.00281400          | 0.00281400    | 0            |
| low    | 0.00280320          | 0.00280320    | 0            |
| close  | 0.00281300          | 0.00281300    | 0            |
| volume | 3119255.00000000    | 3119255.00000000 | 0         |

This is the same mismatch that PR #59 found. It is a 1-tick open discrepancy between the 1m and 1h Binance archives, not introduced by the rule fix. ~~The 1h 1m row open at 11:35 is the anomalous row (truncated); the open of the 11:35 bar is 0.00281390 in the 1m archive and the official 1h bar open (which represents 11:00) is 0.00281380. The fixed 1m, aggregated over the hour, opens at 0.00281390 (the 11:00:00 1m bar), which differs from the 1h archive's 0.00281380 by one tick.~~ *[Correction at review (Claude): the fix rewrites only a close timestamp, which changes no price or volume, so it cannot cause a mismatch. The fixed 1h row at 11:00 opens at 0.00281380; the 1m archive's 11:00 minute opens at 0.00281390. The 11:35 1m row does not contribute to the hour's open. Condition (c) failed because the two archives disagree on the open by one tick.]*

---

## Step 2: usable pair-months under each rule

### Per-month table

| Month   | Pairs with files | Usable (refined) | Usable (narrow) |
| ---     | ---:             | ---:             | ---:            |
| 2017-09 | 2                | 2                | 2               |
| 2017-12 | 4                | 1                | 0               |
| 2018-01 | 4                | 4                | 4               |
| 2018-02 | 4                | 0                | 0               |
| 2018-07 | 7                | 7                | 7               |
| 2019-06 | 8                | 8                | 0               |
| 2020-02 | 9                | 8                | 9               |
| 2020-03 | 9                | 9                | 9               |
| 2020-12 | 10               | 10               | 10              |
| 2021-02 | 10               | 10               | 10              |
| 2021-04 | 10               | 10               | 10              |
| 2021-08 | 10               | 10               | 10              |
| 2021-12 | 10               | 10               | 1               |
| 2023-03 | 10               | 10               | 10              |
| **Total** | **107**        | **99**           | **82**          |

107 pair-months have at least one file. Totals: `len(refined_usable) = 99`, `len(narrow_usable) = 82`.

### One-line answer

**The refined rule gives 99 usable pair-months, against 82 under the narrow rule.**

### Unusable pair-months under the refined rule

| Month   | Symbol   | Reason (first failure) |
| ---     | ---      | ---                    |
| 2017-12 | BTCUSDT  | 1m parse failed: unaligned-open rows remain (line 4681: open/close time is not a 1m boundary) |
| 2017-12 | ETHUSDT  | 1m parse failed: unaligned-open rows remain |
| 2017-12 | BNBUSDT  | 1m parse failed: unaligned-open rows remain |
| 2018-02 | BTCUSDT  | 1m parse failed: unaligned-open rows remain (line 10110) |
| 2018-02 | ETHUSDT  | 1m parse failed: unaligned-open rows remain |
| 2018-02 | BNBUSDT  | 1m parse failed: unaligned-open rows remain |
| 2018-02 | LTCUSDT  | 1m parse failed: unaligned-open rows remain |
| 2020-02 | DOGEUSDT | 1m line 26556 condition(c) = mismatch (1-tick open difference vs official 1h bar) |

LTCUSDT 2017-12: the 1m file is ok under the refined rule (LTCUSDT was listed after the anomaly event; no unaligned-open rows), and the 1h file parses. However, condition (c) passes for LTCUSDT 2017-12 (counted as 1 usable pair-month). Note that the narrow rule rejects LTCUSDT 2017-12 1h because the anomalous close row is not before a gap at the 1h level (the narrow rule requires a gap, not just continuity).

---

## Explanation of why each month differs between the two rules

### Months that changed from narrow to refined

**2019-06** (0 → 8 usable pairs): Under the narrow rule the 1h bar at 21:00 is rejected because the next 1h bar is at 22:00, which is exactly `open + 3600000` — the narrow rule requires `next_open > open + step`, but condition (b) of the refined rule requires only `next_open >= open + step`. The 1h close row meets (a) (open at 21:00:00 is aligned) and (b) (next open is at open+step). The refined rule therefore fixes it, and condition (c) passes. All 8 pairs in 2019-06 become usable.

**2021-12** (1 → 10 usable pairs): Under the narrow rule the anomalous row on 2021-12-24 04:59 is rejected for 9 pairs because the next row opens at 05:00:00 = open + 60s, so there is no gap. The refined rule's condition (b) accepts `next_open == open + step`. Condition (a) is met (04:59:00 open is aligned). Condition (c) passes. All 9 formerly rejected pairs in 2021-12 become usable.

**2017-12 LTCUSDT** (0 → 1 usable pair): LTCUSDT was listed mid-December after the alignment event, so its 1m file has no unaligned-open rows. Its 1h anomalous row (narrow rule rejected because no gap in 1h) is accepted by condition (b) of the refined rule.

### Months that did not change

**2017-12 BTC/ETH/BNB** (0 → 0): The unaligned-open rows (20,401 per pair in 1m) are not addressed by the rule — the close fix does not change that `open % step ≠ 0`. The strict parser rejects those rows at the open-time check. These remain unusable under both rules.

**2018-02** (0 → 0): Same reason: 1,201 unaligned-open rows per pair in 1m and 43 per pair in 1h. The rule does not fix misaligned opens.

### Month that regressed

**2020-02 DOGEUSDT** (usable under narrow, not usable under refined): The narrow rule accepted this pair-month because the truncated 1m row at 11:35 is before a gap and the narrow rule does not check condition (c). The refined rule requires (c), which fails here due to a 1-tick open discrepancy between the aggregated 1m and the official 1h bar. Under the narrow rule, the hour check is not required, so the narrow rule counts this pair-month as usable.

---

## Ideas and proposals

These are checked against the tables above before being proposed.

1. **The refined rule strictly dominates the narrow rule except for DOGEUSDT 2020-02.** It adds 17 pair-months (2019-06: +8, 2021-12: +9, 2017-12 LTCUSDT: +1) and removes 1 (2020-02 DOGEUSDT fails the hour check). The net gain is +17, from 82 to 99.

2. **The DOGEUSDT 2020-02 mismatch is a Binance archive discrepancy, not introduced by the rule fix.** The 1m archive and 1h archive of DOGEUSDT for 2020-02-19 11:00 differ by 1 tick on the open price independently of any rule. PR #59 already found this. If the owner decides a 1-tick price discrepancy between the two archives is acceptable (similar to the volume-drift tolerance), DOGEUSDT 2020-02 would also be usable under the refined rule, giving 100 pair-months. That would require a policy decision beyond the scope of this task.

3. **The 2017-12 BTC/ETH/BNB and 2018-02 failure reason is the unaligned open, not the close.** The refined rule (like the narrow rule) fixes only the close timestamp. For these months to become usable, a separate rule would be needed to accept or reinterpret the rows with misaligned open timestamps. This is a different class of anomaly. There are 20,401 such rows per pair in 2017-12 1m and 1,201 per pair in 2018-02 1m. Any proposal for those months should be treated as a separate task and measured separately with its own integrity checks.

4. **Condition (c) is an integrity gate that cost 1 pair-month and ~~prevented no false acceptances~~ failed no other fixed row.** *[Correction at review (Claude): whether it prevented a false acceptance cannot be known from these data; what was measured is that no other fixed row failed (c).]* In all other cases where (a+b) was met and the file parsed, condition (c) passed at strict zero tolerance. The only failure was the pre-existing Binance archive discrepancy in DOGEUSDT 2020-02. If this condition is adopted, the owner should document how the DOGEUSDT case is handled (either exclude it, or accept the 1-tick archive discrepancy policy-wide).

---

## Appendix: `data/refined_rule.py` source

SHA-256: `084a2be0b884774aab6e68ed5e35a8f932ec3b8eefbbaafa37f59e302fca6c2e`

```text
"""Measure the refined parser rule on the 14 unparsed months.

Task: docs/tasks/2026-09-26-bob-refined-parser-rule.md

Definitions
-----------
For each row whose close is not open + step - 1:
  (a) aligned open:  open % step == 0
  (b) continuity:    last row of file  OR  next row opens at open + step or later
  (c) strict hour check: the 1h hour containing the row compares 'match' when
      ours (aggregated fixed 1m minutes) is compared with the official 1h bar
      using compare_bars(..., Decimal(0)).
      For a 1h row, compare it with the aggregated fixed 1m minutes of the same
      hour.  If the other-interval file did not parse, result is "not testable".

Refined rule fix: a row that meets (a) AND (b) gets close = open + step - 1
in memory only.  Rows that do not meet both (a) and (b) are left unchanged.

Narrow rule fix (PR #59): a row whose close != open + step - 1 gets close =
open + step - 1 in memory only, IF it is the last row before a gap OR the last
row of the file.  No alignment check.
"""

from __future__ import annotations

import csv
import io
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.dataset import archive_get, fetch_file, local_path
from crypto_grid_bot.backtest.klines import (
    INTERVAL_MS,
    MICROSECOND_FLOOR,
    _time,
    aggregate,
    month_bounds_ms,
    parse_rows,
    read_member,
)
from crypto_grid_bot.backtest.replay import compare_bars
from crypto_grid_bot.market_data.parsing import DataError

MONTHS = (
    "2017-09",
    "2017-12",
    "2018-01",
    "2018-02",
    "2018-07",
    "2019-06",
    "2020-02",
    "2020-03",
    "2020-12",
    "2021-02",
    "2021-04",
    "2021-08",
    "2021-12",
    "2023-03",
)

PAIRS = (
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
)

INTERVALS = ("1m", "1h")


def _fetch_and_read(data_dir: Path, symbol: str, interval: str, month: str):
    """Fetch if needed; return CSV text or None if missing."""
    target_zip = local_path(data_dir, symbol, interval, month)
    if not target_zip.exists():
        try:
            fetch_file(data_dir, symbol, interval, month, archive_get)
        except DataError:
            pass
    if not target_zip.exists():
        return None
    csv_name = f"{symbol}-{interval}-{month}.csv"
    return read_member(target_zip, csv_name)


def _walk_rows(text: str, interval: str):
    """
    Walk all rows, returning list of dicts:
      line_no, open_ms, close_ms, raw (list[str]), error (str|None)
    """
    step = INTERVAL_MS[interval]
    rows = []
    for line_no, row in enumerate(csv.reader(io.StringIO(text)), start=1):
        if len(row) != 12:
            rows.append({"line_no": line_no, "open_ms": None, "close_ms": None,
                         "raw": row, "error": f"column count {len(row)}"})
            continue
        try:
            o_ms, _ = _time(row[0], closing=False)
            c_ms, _ = _time(row[6], closing=True)
            rows.append({"line_no": line_no, "open_ms": o_ms, "close_ms": c_ms,
                         "raw": row, "error": None})
        except Exception as exc:
            rows.append({"line_no": line_no, "open_ms": None, "close_ms": None,
                         "raw": row, "error": str(exc)})
    return rows


def _build_fixed_text(row_data: list[dict], interval: str, *, refined: bool) -> str:
    """
    Build fixed CSV text.
    refined=True  -> refined rule: fix iff (a) AND (b)
    refined=False -> narrow rule: fix iff last-before-gap OR last-of-file
    """
    step = INTERVAL_MS[interval]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    n = len(row_data)
    for idx, rd in enumerate(row_data):
        raw = list(rd["raw"])
        o_ms = rd["open_ms"]
        c_ms = rd["close_ms"]
        if o_ms is not None and c_ms is not None and c_ms != o_ms + step - 1:
            is_last = (idx == n - 1)
            next_opens_at = None
            if not is_last:
                nxt = row_data[idx + 1]
                next_opens_at = nxt["open_ms"]
            is_last_before_gap = (
                not is_last
                and next_opens_at is not None
                and next_opens_at > o_ms + step
            )
            continuity_b = is_last or (next_opens_at is not None and next_opens_at >= o_ms + step)
            aligned_a = (o_ms % step == 0)

            if refined:
                do_fix = aligned_a and continuity_b
            else:
                do_fix = is_last_before_gap or is_last

            if do_fix:
                # Rewrite close_time column (col 6) to open + step - 1
                raw_c = raw[6]
                if int(raw_c) >= MICROSECOND_FLOOR:
                    raw[6] = str((o_ms + step - 1) * 1000 + 999)
                else:
                    raw[6] = str(o_ms + step - 1)
        writer.writerow(raw)
    return out.getvalue()


def _classify_row_conditions(row_data: list[dict], interval: str):
    """
    For each anomalous row (close != open+step-1), classify:
      (a) aligned open
      (b) continuity (last row OR next opens at open+step or later)
    Returns list of dicts.
    """
    step = INTERVAL_MS[interval]
    results = []
    n = len(row_data)
    for idx, rd in enumerate(row_data):
        o_ms = rd["open_ms"]
        c_ms = rd["close_ms"]
        if o_ms is None or c_ms is None:
            continue
        if c_ms == o_ms + step - 1:
            continue
        is_last = (idx == n - 1)
        next_opens_at = None
        if not is_last:
            nxt = row_data[idx + 1]
            next_opens_at = nxt["open_ms"]
        continuity_b = is_last or (next_opens_at is not None and next_opens_at >= o_ms + step)
        aligned_a = (o_ms % step == 0)
        results.append({
            "line_no": rd["line_no"],
            "open_ms": o_ms,
            "close_ms": c_ms,
            "a_aligned": aligned_a,
            "b_continuity": continuity_b,
            "is_last": is_last,
            "next_open": next_opens_at,
        })
    return results


def _count_unaligned(row_data: list[dict], interval: str) -> int:
    """Count rows with unaligned open (open % step != 0)."""
    step = INTERVAL_MS[interval]
    return sum(1 for rd in row_data if rd["open_ms"] is not None and rd["open_ms"] % step != 0)


def main(data_dir: Path):
    # Safety check: no 2025+ months
    for m in MONTHS:
        yr = int(m[:4])
        if yr >= 2025:
            sys.exit(f"STOP: prohibited month {m}")

    print(f"START: {len(MONTHS)} months, {len(PAIRS)} pairs, {len(INTERVALS)} intervals")
    print(f"Months: {MONTHS}")
    print()

    # -----------------------------------------------------------------------
    # Phase 1: fetch, walk rows, classify conditions (a) and (b)
    # -----------------------------------------------------------------------
    # file_data[(symbol, interval, month)] = {"text": str, "row_data": [...], "status": str}
    file_data: dict[tuple, dict] = {}

    # unaligned-open counts (printed for the three reference files)
    unaligned_counts: dict[tuple, int] = {}

    for month in MONTHS:
        for symbol in PAIRS:
            for interval in INTERVALS:
                key = (symbol, interval, month)
                text = _fetch_and_read(data_dir, symbol, interval, month)
                if text is None:
                    file_data[key] = {"text": None, "row_data": None, "status": "missing"}
                    continue
                row_data = _walk_rows(text, interval)
                ua = _count_unaligned(row_data, interval)
                unaligned_counts[key] = ua
                file_data[key] = {"text": text, "row_data": row_data, "status": "present"}

    # Print the three reference unaligned-open counts (totals across all pairs)
    print("=== Unaligned-open count verification (totals across all pairs) ===")
    ref_checks = [
        ("1m", "2017-12", 61203),
        ("1m", "2018-02", 4804),
        ("1h", "2018-02", 172),
    ]
    for ivl, mon, expected in ref_checks:
        total = sum(unaligned_counts.get((sym, ivl, mon), 0) for sym in PAIRS)
        status = "OK" if total == expected else f"MISMATCH (expected {expected})"
        print(f"  {ivl} {mon} total across all pairs: {total}  [{status}]")
    print()

    # Full unaligned-open table (per file)
    print("=== All unaligned-open counts per file (non-zero only) ===")
    for month in MONTHS:
        for symbol in PAIRS:
            for interval in INTERVALS:
                key = (symbol, interval, month)
                ua = unaligned_counts.get(key, 0)
                if ua > 0:
                    print(f"  {symbol} {interval} {month}: {ua} unaligned-open rows")
    print()

    # -----------------------------------------------------------------------
    # Phase 2: build fixed texts and parse them
    # -----------------------------------------------------------------------
    # fixed_klines[(symbol, interval, month, "refined"|"narrow")] = list[Kline] or None
    # parse_results[(symbol, interval, month, "refined"|"narrow")] = (ok, error_or_stats)
    parse_results: dict[tuple, Any] = {}
    fixed_klines: dict[tuple, Any] = {}

    for month in MONTHS:
        for symbol in PAIRS:
            for interval in INTERVALS:
                key = (symbol, interval, month)
                fd = file_data[key]
                if fd["status"] == "missing":
                    for rulename in ("refined", "narrow"):
                        parse_results[(symbol, interval, month, rulename)] = ("missing", None)
                        fixed_klines[(symbol, interval, month, rulename)] = None
                    continue
                row_data = fd["row_data"]
                for rulename in ("refined", "narrow"):
                    is_refined = (rulename == "refined")
                    fixed_text = _build_fixed_text(row_data, interval, refined=is_refined)
                    try:
                        klines, stats = parse_rows(fixed_text, interval, month)
                        parse_results[(symbol, interval, month, rulename)] = ("ok", stats)
                        fixed_klines[(symbol, interval, month, rulename)] = klines
                    except DataError as exc:
                        parse_results[(symbol, interval, month, rulename)] = ("error", str(exc))
                        fixed_klines[(symbol, interval, month, rulename)] = None

    # -----------------------------------------------------------------------
    # Phase 3: condition (c) – hourly cross-check for refined-rule anomalous rows
    # -----------------------------------------------------------------------
    # For each (symbol, month) where both intervals parsed under refined rule,
    # for each anomalous row in 1m that the refined rule fixed (a+b met),
    # check condition (c): compare aggregate(fixed_1m of that hour) vs official 1h
    # For anomalous rows in 1h that refined rule fixed, compare aggregate(fixed_1m of same hour)

    # c_results[(symbol, month, line_no, interval)] = "match"|"drift"|"mismatch"|"not_testable"
    c_results: dict[tuple, str] = {}
    # failing_c rows: list of detail dicts
    failing_c_rows: list[dict] = []

    for month in MONTHS:
        for symbol in PAIRS:
            for interval in INTERVALS:
                key_base = (symbol, interval, month)
                fd = file_data[key_base]
                if fd["status"] == "missing":
                    continue
                row_data = fd["row_data"]
                step = INTERVAL_MS[interval]

                # Only process rows that meet (a) AND (b) — the ones the refined rule fixes
                anomalous = _classify_row_conditions(row_data, interval)
                refined_fixed = [r for r in anomalous if r["a_aligned"] and r["b_continuity"]]
                if not refined_fixed:
                    continue

                # Get the fixed klines for both intervals
                k1m = fixed_klines.get((symbol, "1m", month, "refined"))
                k1h = fixed_klines.get((symbol, "1h", month, "refined"))

                for arow in refined_fixed:
                    o_ms = arow["open_ms"]
                    c_ms = arow["close_ms"]
                    line_no = arow["line_no"]
                    hour_open_ms = (o_ms // INTERVAL_MS["1h"]) * INTERVAL_MS["1h"]
                    c_key = (symbol, month, line_no, interval)

                    if interval == "1m":
                        # ours = aggregated fixed 1m of that hour
                        # theirs = official 1h bar (fixed_klines 1h)
                        if k1m is None or k1h is None:
                            c_results[c_key] = "not_testable"
                            continue
                        hour_minutes = [k for k in k1m if k.open_ms // INTERVAL_MS["1h"] * INTERVAL_MS["1h"] == hour_open_ms]
                        if not hour_minutes:
                            c_results[c_key] = "not_testable"
                            continue
                        agg_list = list(aggregate(hour_minutes, INTERVAL_MS["1h"]))
                        if len(agg_list) != 1:
                            c_results[c_key] = "not_testable"
                            continue
                        ours = agg_list[0]
                        h1h_map = {k.open_ms: k for k in k1h}
                        theirs = h1h_map.get(hour_open_ms)
                        if theirs is None:
                            c_results[c_key] = "not_testable"
                            continue
                        result = compare_bars(ours, theirs, Decimal(0))
                        c_results[c_key] = result
                        if result != "match":
                            utc_str = datetime.fromtimestamp(o_ms / 1000, UTC).isoformat()
                            # Compute difference
                            diff_o = ours.open - theirs.open
                            diff_h = ours.high - theirs.high
                            diff_l = ours.low - theirs.low
                            diff_c = ours.close - theirs.close
                            diff_v = ours.volume - theirs.volume
                            failing_c_rows.append({
                                "symbol": symbol, "month": month, "interval": interval,
                                "line_no": line_no, "open_ms": o_ms, "close_ms": c_ms,
                                "utc_open": utc_str, "hour_ms": hour_open_ms,
                                "result": result,
                                "diff_open": str(diff_o), "diff_high": str(diff_h),
                                "diff_low": str(diff_l), "diff_close": str(diff_c),
                                "diff_volume": str(diff_v),
                                "ours": f"O={ours.open} H={ours.high} L={ours.low} C={ours.close} V={ours.volume}",
                                "theirs": f"O={theirs.open} H={theirs.high} L={theirs.low} C={theirs.close} V={theirs.volume}",
                            })
                    else:
                        # interval == "1h"
                        # ours = aggregated fixed 1m minutes of that same hour
                        # theirs = this fixed 1h bar (from fixed_klines 1h)
                        if k1m is None:
                            c_results[c_key] = "not_testable"
                            continue
                        hour_minutes = [k for k in k1m if k.open_ms // INTERVAL_MS["1h"] * INTERVAL_MS["1h"] == hour_open_ms]
                        if not hour_minutes:
                            c_results[c_key] = "not_testable"
                            continue
                        agg_list = list(aggregate(hour_minutes, INTERVAL_MS["1h"]))
                        if len(agg_list) != 1:
                            c_results[c_key] = "not_testable"
                            continue
                        ours = agg_list[0]
                        if k1h is None:
                            c_results[c_key] = "not_testable"
                            continue
                        h1h_map = {k.open_ms: k for k in k1h}
                        theirs = h1h_map.get(hour_open_ms)
                        if theirs is None:
                            c_results[c_key] = "not_testable"
                            continue
                        result = compare_bars(ours, theirs, Decimal(0))
                        c_results[c_key] = result
                        if result != "match":
                            utc_str = datetime.fromtimestamp(o_ms / 1000, UTC).isoformat()
                            diff_o = ours.open - theirs.open
                            diff_h = ours.high - theirs.high
                            diff_l = ours.low - theirs.low
                            diff_c = ours.close - theirs.close
                            diff_v = ours.volume - theirs.volume
                            failing_c_rows.append({
                                "symbol": symbol, "month": month, "interval": interval,
                                "line_no": line_no, "open_ms": o_ms, "close_ms": c_ms,
                                "utc_open": utc_str, "hour_ms": hour_open_ms,
                                "result": result,
                                "diff_open": str(diff_o), "diff_high": str(diff_h),
                                "diff_low": str(diff_l), "diff_close": str(diff_c),
                                "diff_volume": str(diff_v),
                                "ours": f"O={ours.open} H={ours.high} L={ours.low} C={ours.close} V={ours.volume}",
                                "theirs": f"O={theirs.open} H={theirs.high} L={theirs.low} C={theirs.close} V={theirs.volume}",
                            })

    # -----------------------------------------------------------------------
    # Phase 4: determine usable pair-months under each rule
    # -----------------------------------------------------------------------
    # Refined rule: both 1m and 1h parse after fix AND every fixed row passes (c)
    # (a row with c="not_testable" counts as failing)
    # Narrow rule: both 1m and 1h parse after fix

    refined_usable: list[tuple[str, str]] = []
    narrow_usable: list[tuple[str, str]] = []
    refined_unusable_reason: dict[tuple[str, str], str] = {}

    for month in MONTHS:
        for symbol in PAIRS:
            # Check narrow
            r1m_n = parse_results.get((symbol, "1m", month, "narrow"), ("missing", None))
            r1h_n = parse_results.get((symbol, "1h", month, "narrow"), ("missing", None))
            if r1m_n[0] == "ok" and r1h_n[0] == "ok":
                narrow_usable.append((month, symbol))

            # Check refined
            r1m_r = parse_results.get((symbol, "1m", month, "refined"), ("missing", None))
            r1h_r = parse_results.get((symbol, "1h", month, "refined"), ("missing", None))
            if r1m_r[0] == "missing" and r1h_r[0] == "missing":
                refined_unusable_reason[(month, symbol)] = "missing"
                continue
            if r1m_r[0] != "ok":
                reason = f"1m parse failed: {r1m_r[1]}"
                refined_unusable_reason[(month, symbol)] = reason
                continue
            if r1h_r[0] != "ok":
                reason = f"1h parse failed: {r1h_r[1]}"
                refined_unusable_reason[(month, symbol)] = reason
                continue

            # Both parse; check (c) for every fixed row
            c_fail = None
            for interval in INTERVALS:
                fd = file_data[(symbol, interval, month)]
                if fd["status"] == "missing":
                    continue
                row_data = fd["row_data"]
                step = INTERVAL_MS[interval]
                anomalous = _classify_row_conditions(row_data, interval)
                refined_fixed = [r for r in anomalous if r["a_aligned"] and r["b_continuity"]]
                for arow in refined_fixed:
                    c_key = (symbol, month, arow["line_no"], interval)
                    c_val = c_results.get(c_key, "not_testable")
                    if c_val != "match":
                        c_fail = f"{interval} line {arow['line_no']} condition(c)={c_val}"
                        break
                if c_fail:
                    break

            if c_fail:
                refined_unusable_reason[(month, symbol)] = c_fail
            else:
                refined_usable.append((month, symbol))

    # -----------------------------------------------------------------------
    # Phase 5: Print results
    # -----------------------------------------------------------------------

    print("=== Parse results per file (anomalous row conditions) ===")
    print(f"{'month':<8} {'symbol':<10} {'ivl':<4} "
          f"{'anomalous':>9} {'(a)':>6} {'(a+b)':>7} {'(a+b+c)':>9} "
          f"{'refined_parse':>13} {'narrow_parse':>12}")
    for month in MONTHS:
        for symbol in PAIRS:
            for interval in INTERVALS:
                key = (symbol, interval, month)
                fd = file_data[key]
                if fd["status"] == "missing":
                    continue
                row_data = fd["row_data"]
                step = INTERVAL_MS[interval]
                anomalous = _classify_row_conditions(row_data, interval)
                n_anom = len(anomalous)
                n_a = sum(1 for r in anomalous if r["a_aligned"])
                n_ab = sum(1 for r in anomalous if r["a_aligned"] and r["b_continuity"])
                # (a+b+c): only for those that parse under refined
                r_ref = parse_results.get((symbol, interval, month, "refined"), ("?", None))
                r_nar = parse_results.get((symbol, interval, month, "narrow"), ("?", None))
                # count (c) passes among (a+b) rows
                n_abc = 0
                if r_ref[0] == "ok":
                    for arow in anomalous:
                        if arow["a_aligned"] and arow["b_continuity"]:
                            c_key = (symbol, month, arow["line_no"], interval)
                            c_val = c_results.get(c_key, "not_testable")
                            if c_val == "match":
                                n_abc += 1
                abc_str = str(n_abc) if r_ref[0] == "ok" else "n/a"
                refined_parse_ok = r_ref[0]
                narrow_parse_ok = r_nar[0]
                print(f"{month:<8} {symbol:<10} {interval:<4} "
                      f"{n_anom:>9} {n_a:>6} {n_ab:>7} {abc_str:>9} "
                      f"{refined_parse_ok:>13} {narrow_parse_ok:>12}")
    print()

    print("=== Failing (c) rows ===")
    if not failing_c_rows:
        print("  None")
    else:
        for fr in failing_c_rows:
            print(f"  {fr['symbol']} {fr['interval']} {fr['month']} line {fr['line_no']} "
                  f"utc={fr['utc_open']} result={fr['result']}")
            print(f"    ours:   {fr['ours']}")
            print(f"    theirs: {fr['theirs']}")
            print(f"    diff: O={fr['diff_open']} H={fr['diff_high']} L={fr['diff_low']} "
                  f"C={fr['diff_close']} V={fr['diff_volume']}")
    print()

    print("=== Usable pair-months ===")
    print(f"  Refined rule: {len(refined_usable)} usable pair-months (vs 82 under narrow rule)")
    print(f"  Narrow rule:  {len(narrow_usable)} usable pair-months")
    print()

    print("=== Per-month usable pairs ===")
    print(f"{'month':<8}  {'refined':>10}  {'narrow':>10}")
    for month in MONTHS:
        pairs_with_files = [s for s in PAIRS
                            if file_data.get((s, "1m", month), {}).get("status") == "present"
                            or file_data.get((s, "1h", month), {}).get("status") == "present"]
        n_ref = sum(1 for (m, s) in refined_usable if m == month)
        n_nar = sum(1 for (m, s) in narrow_usable if m == month)
        total = len(pairs_with_files)
        print(f"{month:<8}  {n_ref:>4}/{total:<4}      {n_nar:>4}/{total:<4}")
    print()

    print("=== Unusable pair-months under refined rule (with reason) ===")
    any_printed = False
    for month in MONTHS:
        for symbol in PAIRS:
            reason = refined_unusable_reason.get((month, symbol))
            if reason and reason != "missing":
                print(f"  {month} {symbol}: {reason}")
                any_printed = True
    if not any_printed:
        print("  None (all pairs with files are usable)")
    print()

    print(f"FINAL: refined_usable={len(refined_usable)}  narrow_usable={len(narrow_usable)}")
    print(f"  Narrow rule check: {'PASS (82)' if len(narrow_usable) == 82 else f'MISMATCH: got {len(narrow_usable)}, expected 82'}")


if __name__ == "__main__":
    main(Path("data"))
```

Hash check (the fence above must reproduce the script's SHA-256):
`sed -n '409,971p' docs/reviews/2026-09-26-bob-refined-parser-rule.md | sha256sum`
