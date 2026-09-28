# Masked fraction of the months the repair rule rescues

- **Task file:** `docs/tasks/2026-09-27-bob-rescued-month-masking.md`
- **Date:** 2026-09-28 (run started Mon Sep 28 01:55:43 UTC 2026; ended Mon Sep 28 02:50:39 UTC 2026)
- **Commit:** `ad98f7b` (HEAD at run start: `ad98f7b Merge pull request #123`)
- **Python:** 3.12.14
- **Report produced by:** IBM Bob task runner (`bob-task.yml`)

## Commands run

```
date -u
# Mon Sep 28 01:55:43 UTC 2026

PYTHONPATH=src python data/rescued_masking.py > data/rescued_masking.jsonl 2> data/rescued_masking.stderr.log
# completed Mon Sep 28 02:50:39 UTC 2026

python data/rescued_bands.py data/rescued_masking.jsonl
sha256sum data/rescued_masking.py
sha256sum data/rescued_masking.jsonl
sha256sum data/rescued_bands.py
```

SHA-256 of `data/rescued_masking.py` (after last edit, before run):
`68e712ac83122da105eb2e8ea67c62ce1bf4b68a80dda4e5e955fd8381ed5c12`

SHA-256 of `data/rescued_masking.jsonl`:
`1af83e7a1c90feeba2fabd3a6030c71063648bf491985a990873eb1f8ea98a63`

SHA-256 of `data/rescued_bands.py`:
`b50f35f82438c8510f2e2c4d679730691b8e159943853e8ab0d476a4076ed537`

Appendix A source check:
`sed -n '168,385p' docs/reviews/2026-09-27-bob-rescued-month-masking.md | sha256sum`
→ `68e712ac83122da105eb2e8ea67c62ce1bf4b68a80dda4e5e955fd8381ed5c12  -`

Appendix B source check:
`sed -n '393,505p' docs/reviews/2026-09-27-bob-rescued-month-masking.md | sha256sum`
→ `b50f35f82438c8510f2e2c4d679730691b8e159943853e8ab0d476a4076ed537  -`

## Step 3: Self-verification

All figures computed by `python data/rescued_bands.py data/rescued_masking.jsonl`.

| Figure | Claude | Bob | Equal? |
| --- | ---: | ---: | --- |
| pair-months that parse without repair | 674 | 674 | ✓ |
| pair-months with no archive upstream (pre-listing) | 110 | 110 | ✓ |
| `repaired` months | 98 | 98 | ✓ |
| `unusable` months | 8 | 8 | ✓ |
| Unusable identities | BTC, ETH, BNB 2017-12; BTC, ETH, BNB, LTC 2018-02; DOGE 2020-02 | same | ✓ |
| BTCUSDT 2017-09, real defects | 4.31% | 4.31% | ✓ |
| ETHUSDT 2017-09, real defects | 10.14% | 10.14% | ✓ |
| LTCUSDT listing hour | 2017-12-13 03:00 UTC | 2017-12-13 03:00 UTC | ✓ |

All eight checks equal. No differences; the run continues.

**LTCUSDT listing hour derivation:** LTCUSDT 2017-12 is the first present 1m archive for LTC.
Its `expected` count is 453. December 2017 has 744 hours total; 744 − 453 = 291 hours from
month start = 12 days 3 hours, placing the listing at 2017-12-13 03:00 UTC. The original
`masked_fraction.py` script derives the listing hour from the first *parseable* month, which
for LTCUSDT is 2018-03 (2017-12 through 2018-02 all fail the strict parser). This change
is one of the four task-mandated corrections; it follows the same pattern as
`audit_run.audit_outages`.

**Unusable month reasons (from `rule_outcome`):**

| Pair-month | Reason |
| --- | --- |
| BTCUSDT 2017-12 | `parse: line 4681: open/close time is not a 1m boundary` |
| ETHUSDT 2017-12 | `parse: line 4681: open/close time is not a 1m boundary` |
| BNBUSDT 2017-12 | `parse: line 4681: open/close time is not a 1m boundary` |
| BTCUSDT 2018-02 | `parse: line 10110: open/close time is not a 1m boundary` |
| ETHUSDT 2018-02 | `parse: line 10110: open/close time is not a 1m boundary` |
| BNBUSDT 2018-02 | `parse: line 10110: open/close time is not a 1m boundary` |
| LTCUSDT 2018-02 | `parse: line 10110: open/close time is not a 1m boundary` |
| DOGEUSDT 2020-02 | `hour 1582110000000 differs on open` |

## Step 2: Output tables

### Total pair-months and statuses

890 total rows; statuses (printed by `rescued_bands.py`):
- `ok` (parse without repair): **674**
- `repaired` (rescued by refined rule): **98**
- `unusable` (refined rule cannot rescue): **8**
- `not_cached` (Binance does not publish month): **110**

### Repaired months: real-defect thresholds

| Threshold | Repaired months above |
| ---: | ---: |
| above 1% | 22 |
| above 2% | 9 |
| above 3% | 8 |
| above 5% | 5 |

### Repaired months above 2% real defects (9 months)

| Pair | Month | Expected | Masked | Open-only | Hard | All masked | Real defects |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| DOGEUSDT | 2021-12 | 744 | 119 | 0 | 119 | 15.99% | 15.99% |
| ETHUSDT | 2017-09 | 720 | 241 | 168 | 73 | 33.47% | 10.14% |
| DOGEUSDT | 2020-03 | 744 | 335 | 260 | 75 | 45.03% | 10.08% |
| LTCUSDT | 2021-12 | 744 | 75 | 0 | 75 | 10.08% | 10.08% |
| LINKUSDT | 2021-12 | 744 | 74 | 0 | 74 | 9.95% | 9.95% |
| BTCUSDT | 2017-09 | 720 | 125 | 94 | 31 | 17.36% | 4.31% |
| TRXUSDT | 2021-12 | 744 | 27 | 0 | 27 | 3.63% | 3.63% |
| ADAUSDT | 2021-12 | 744 | 23 | 0 | 23 | 3.09% | 3.09% |
| SOLUSDT | 2021-12 | 744 | 19 | 0 | 19 | 2.55% | 2.55% |

### Band table: real-defect fractions

The same bands as the eligibility record's second appendix. First column: the 674 months
that parse without repair (matching the eligibility record). Second column: all 772 months
(674 ok + 98 repaired) for direct comparison.

| Band | ok only (674) | ok + repaired (772) |
| ---: | ---: | ---: |
| [0.000, 0.001) | 481 | 489 |
| [0.001, 0.005) | 111 | 146 |
| [0.005, 0.010) | 29 | 62 |
| [0.010, 0.020) | 31 | 44 |
| [0.020, 0.030) | 4 | 5 |
| [0.030, 0.050) | 2 | 5 |
| [0.050, 0.075) | 3 | 3 |
| [0.075, 0.100) | 6 | 7 |
| [0.100, 0.150) | 6 | 9 |
| [0.150, 0.250) | 1 | 2 |
| [0.250, 0.500) | 0 | 0 |
| [0.500, 1.010) | 0 | 0 |
| **Total** | **674** | **772** |

The 2% break (31 months in [1%, 2%), 4 in [2%, 3%)) that the eligibility record found
in the ok-only population holds in the combined population: 44 in [1%, 2%), 5 in [2%, 3%).
The break widens: 5 in [2%, 3%) vs. 4, while [1%, 2%) grows by 13 (from 31 to 44). The
shape is preserved but not sharpened.

## Ideas and proposals

**2021-12 cluster.** Six pairs have real-defect rates above 2% in 2021-12: DOGE 15.99%,
LTC 10.08%, LINK 9.95%, TRX 3.63%, ADA 3.09%, SOL 2.55%. The other four pairs in that
calendar month are below 2% (BTC 0.13%, BNB 0.13%, ETH 0.00%, XRP 0.27%). Five of the
nine months above 2% are in this single calendar month. A 2% cap would exclude all five.
Whether a month-wide event caused this is not checked here; the data tables are the evidence.

**2021-04 cluster.** Ten of 98 repaired months are in 2021-04, all at exactly 1.25% (9 hard
defects out of 720 expected hours). These are the same 9 hours across all pairs, suggesting
a single exchange-wide event. All sit below the 2% cap.

**DOGEUSDT 2020-03: large open-only fraction in a repaired month.** This month has 335 masked
hours (45.03%), of which 260 are open-only convention class. The 75 real defects (10.08%)
exceed the 2% cap. The convention-class share (77.6%) is high but consistent with DOGE's
known early-trading behaviour.

**Cap sensitivity in the full population.** With 98 repaired months added, months above 2%
grow from 22 to 31 (22 ok + 9 repaired). The same insensitivity the eligibility record
noted ([2%, 5%] differs by at most a few months) holds here too: the additional months
cluster at the extremes (below 1% or well above 5%), so the cap choice in [2%, 5%] is
not more sensitive with the repaired population than without. These figures are data-coverage
counts only; no strategy performance was run.

## Appendix A: `data/rescued_masking.py` source

SHA-256: `68e712ac83122da105eb2e8ea67c62ce1bf4b68a80dda4e5e955fd8381ed5c12`

```text
"""Per-pair-month masked fraction, including months rescued by the refined repair rule.

Extends data/masked_fraction.py (SHA-256:
f23e1c8bca7f2ead15ee3e2683776d31459e6fcdfc7d7c72223e04ead65fa1be) with four changes:
1. Repair path for ArchiveParseError months (refined rule).
2. Listing hour from the first ROW of the pair's earliest PRESENT 1m archive (parseable or not).
3. No 'ok' row when expected hours == 0: record 'pre_listing' instead.
4. Fetch every pair-month through fetch_file before reading, so every file is hash-checked.

    PYTHONPATH=src python data/rescued_masking.py > data/rescued_masking.jsonl
"""

import csv
import io
import json
import sys
from pathlib import Path

from crypto_grid_bot.backtest.audit import (
    ABSENT_BOTH, DEVELOPMENT_END, HOUR_MS, PRESENT_BOTH,
    development_month, differing_fields, expected_hours, fix_closes,
    hour_statuses, rule_outcome,
)
from crypto_grid_bot.backtest.dataset import (
    ArchiveParseError, DataError, fetch_file, local_path,
    archive_get,
)
from crypto_grid_bot.backtest.klines import aggregate, parse_rows, read_archive, read_member
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE

DATA = Path("data")
PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
         "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"]


def months():
    y, m = 2017, 8
    while f"{y:04d}-{m:02d}" <= DEVELOPMENT_END:
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def measure_ok(symbol, month, listing_hour, minutes, hours):
    """Measure masking for a month whose klines are already parsed."""
    ours = {k.open_ms: k for k in aggregate(minutes)}
    theirs = {k.open_ms: k for k in hours}
    statuses = hour_statuses(ours, theirs, expected_hours(listing_hour, month))
    expected = len(statuses)
    # Change 3: no 'ok' row when expected hours == 0 — record 'pre_listing'
    if expected == 0:
        return {"status": "pre_listing"}
    masked = open_only = 0
    for hour, status in statuses.items():
        if status != PRESENT_BOTH:
            masked += 1
            continue
        fields = differing_fields(ours[hour], theirs[hour], VOLUME_DRIFT_TOLERANCE)
        if not fields:
            continue
        masked += 1
        if fields == ("open",):
            open_only += 1
    hard = masked - open_only
    return {
        "status": "ok",
        "expected": expected,
        "masked": masked,
        "open_only": open_only,
        "hard": hard,
        "fraction": round(masked / expected, 6),
        "hard_fraction": round(hard / expected, 6),
        "absent_both": sum(1 for s in statuses.values() if s == ABSENT_BOTH),
    }


def repair(symbol, month, listing_hour, path_1m, path_1h):
    """Repair path (Change 1): read raw rows, apply refined rule, measure if usable."""
    member_1m = f"{symbol}-1m-{month}.csv"
    member_1h = f"{symbol}-1h-{month}.csv"
    try:
        text_1m = read_member(path_1m, member_1m)
        text_1h = read_member(path_1h, member_1h)
    except DataError as exc:
        return {"status": "unusable", "reason": f"read_member: {exc}"}

    minute_rows = list(csv.reader(io.StringIO(text_1m)))
    hour_rows = list(csv.reader(io.StringIO(text_1h)))

    outcome = rule_outcome(minute_rows, hour_rows, month, "refined")
    if not outcome.usable:
        return {"status": "unusable", "reason": outcome.reason}

    # Repair and parse
    try:
        fixed_1m, _ = fix_closes(minute_rows, "1m", "refined")
        fixed_1h, _ = fix_closes(hour_rows, "1h", "refined")
        minutes, _ = parse_rows(fixed_1m, "1m", month)
        hours_klines, _ = parse_rows(fixed_1h, "1h", month)
    except DataError as exc:
        return {"status": "unusable", "reason": f"parse after repair: {exc}"}

    if not minutes:
        return {"status": "empty"}

    # Measure exactly as an ok month but with status 'repaired'
    result = measure_ok(symbol, month, listing_hour, minutes, hours_klines)
    if result["status"] == "pre_listing":
        return result  # pre_listing stays as-is
    result["status"] = "repaired"
    return result


def measure(symbol, month, listing_hour):
    """Measure one pair-month; handles fetch, repair path and normal path.

    Change 4: fetch both archives through fetch_file (hash-checked).
    Outcomes:
      - status 'missing' from fetch_file → return not_cached (must not be unusable)
      - ArchiveParseError from fetch_file → repair path (Change 1)
      - any other DataError → stop the run (caller raises)
    """
    development_month(month)

    parse_error_intervals = set()

    # Change 4: fetch 1m and 1h archives, handle by outcome type
    for interval in ("1m", "1h"):
        try:
            result = fetch_file(DATA, symbol, interval, month, archive_get)
        except ArchiveParseError:
            # Archive passed SHA-256 but doesn't parse — eligible for repair path
            parse_error_intervals.add(interval)
            continue
        except DataError:
            # Checksum file malformed/absent, checksum without archive, hash mismatch — STOP
            raise
        if result["status"] == "missing":
            # Binance does not publish this month — record not_cached; must not be unusable
            return {"status": "not_cached"}

    path_1m = local_path(DATA, symbol, "1m", month)
    path_1h = local_path(DATA, symbol, "1h", month)

    # If either interval had a parse error, go to repair path
    if parse_error_intervals:
        return repair(symbol, month, listing_hour, path_1m, path_1h)

    # Both files parsed successfully through fetch_file; read them now
    try:
        minutes, _ = read_archive(path_1m, symbol, "1m", month)
        hours, _ = read_archive(path_1h, symbol, "1h", month)
    except DataError as exc:
        # Shouldn't happen (fetch_file already parsed them), but treat as unusable to
        # report rather than stop — the file is not an integrity failure
        return {"status": "unusable", "reason": f"re-read: {exc}"}

    if not minutes:
        return {"status": "empty"}

    return measure_ok(symbol, month, listing_hour, minutes, hours)


def listing_hour_of(symbol):
    """Change 2: The pair's listing hour from the first ROW of the pair's earliest
    PRESENT 1m archive, parseable or not.

    The original masked_fraction.py script took the first PARSEABLE month, which is wrong
    for LTCUSDT whose earliest months fail the strict parser. This version takes the first
    row of the earliest month that is present on Binance (regardless of parseability), as
    audit_run.audit_outages does.
    """
    for month in months():
        # Fetch to check if the file is present and hash-valid
        parse_error = False
        try:
            result = fetch_file(DATA, symbol, "1m", month, archive_get)
        except ArchiveParseError:
            parse_error = True  # Present and hash-valid but doesn't parse
        except DataError:
            raise  # Stop on integrity failure
        else:
            if result["status"] == "missing":
                continue  # Not published for this month

        # The archive exists on disk (whether parseable or not); read the first row
        path = local_path(DATA, symbol, "1m", month)
        member = f"{symbol}-1m-{month}.csv"
        try:
            text = read_member(path, member)
        except DataError:
            continue
        rows = list(csv.reader(io.StringIO(text)))
        if rows:
            try:
                return int(rows[0][0]) // HOUR_MS * HOUR_MS
            except (ValueError, IndexError):
                continue
    return None


if __name__ == "__main__":
    for symbol in PAIRS:
        listing = listing_hour_of(symbol)
        if listing is None:
            print(json.dumps({"pair": symbol, "status": "no_cached_month"}), flush=True)
            continue
        for month in months():
            try:
                row = {"pair": symbol, "month": month, **measure(symbol, month, listing)}
            except DataError as exc:
                # Any DataError that is not ArchiveParseError stops the run
                print(f"STOP: DataError for {symbol} {month}: {exc}", file=sys.stderr)
                sys.exit(1)
            print(json.dumps(row), flush=True)
            if row["status"] in ("ok", "repaired"):
                print(f"{symbol} {month} status={row['status']} "
                      f"all={row['fraction']:.4f} hard={row['hard_fraction']:.4f}",
                      file=sys.stderr, flush=True)
```

## Appendix B: `data/rescued_bands.py` source

SHA-256: `b50f35f82438c8510f2e2c4d679730691b8e159943853e8ab0d476a4076ed537`

```text
"""Reduce rescued_masking.jsonl to the tables the task report publishes.

    python data/rescued_bands.py data/rescued_masking.jsonl
"""

import json
import sys
from collections import Counter, defaultdict

BANDS = [
    (0.0, 0.001), (0.001, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 0.03),
    (0.03, 0.05), (0.05, 0.075), (0.075, 0.10), (0.10, 0.15), (0.15, 0.25),
    (0.25, 0.50), (0.50, 1.01),
]
THRESHOLDS = [0.01, 0.02, 0.03, 0.05]

def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]

def band_label(lo, hi):
    return f"[{lo:.3f},{hi:.3f})"

def main(path):
    rows = load(path)
    status = Counter(r["status"] for r in rows)
    print(f"Total rows: {len(rows)}")
    print(f"Statuses: {dict(status)}")
    print()

    # Step 3 verification figures
    ok = [r for r in rows if r["status"] == "ok"]
    repaired = [r for r in rows if r["status"] == "repaired"]
    unusable = [r for r in rows if r["status"] == "unusable"]
    not_cached = [r for r in rows if r["status"] == "not_cached"]
    pre_listing = [r for r in rows if r["status"] == "pre_listing"]

    print("=== STEP 3 VERIFICATION ===")
    print(f"pair-months that parse without repair (ok): {len(ok)}")
    print(f"pair-months with no archive upstream (not_cached + pre_listing): {len(not_cached) + len(pre_listing)}")
    print(f"  not_cached: {len(not_cached)}")
    print(f"  pre_listing: {len(pre_listing)}")
    print(f"repaired months: {len(repaired)}")
    print(f"unusable months: {len(unusable)}")
    print("Unusable list:")
    for r in unusable:
        print(f"  {r['pair']} {r['month']}: {r.get('reason','')}")
    print()

    # BTC 2017-09 and ETH 2017-09
    btc_sep = next((r for r in rows if r["pair"] == "BTCUSDT" and r["month"] == "2017-09"), None)
    eth_sep = next((r for r in rows if r["pair"] == "ETHUSDT" and r["month"] == "2017-09"), None)
    print(f"BTCUSDT 2017-09 status={btc_sep['status']} hard_fraction={btc_sep['hard_fraction']:.4f} ({100*btc_sep['hard_fraction']:.2f}%)")
    print(f"ETHUSDT 2017-09 status={eth_sep['status']} hard_fraction={eth_sep['hard_fraction']:.4f} ({100*eth_sep['hard_fraction']:.2f}%)")

    # LTCUSDT listing hour — derived from the first present 1m archive's first row
    # We can check by finding the first LTC row and seeing what listing was used
    ltc_rows = [r for r in rows if r["pair"] == "LTCUSDT"]
    # Find the first non-not_cached LTC row to infer listing_hour
    # The listing hour affects expected_hours; we can check the first row where expected > 0
    ltc_first = next((r for r in ltc_rows if r["status"] in ("ok","repaired") and r.get("expected",0) > 0), None)
    print(f"\nLTCUSDT first measured month: {ltc_first['pair']} {ltc_first['month']} expected={ltc_first.get('expected')}")
    print()

    # Repaired months: thresholds
    print("=== REPAIRED MONTHS: HARD-DEFECT THRESHOLDS ===")
    for t in THRESHOLDS:
        above = [r for r in repaired if r["hard_fraction"] > t]
        print(f"  above {t:.0%}: {len(above)}")
    print()
    print("Repaired months above 2% (hard_fraction > 0.02):")
    above_2 = sorted([r for r in repaired if r["hard_fraction"] > 0.02],
                     key=lambda r: -r["hard_fraction"])
    for r in above_2:
        print(f"  {r['pair']} {r['month']}: expected={r['expected']} masked={r['masked']} hard={r['hard']} hard_fraction={100*r['hard_fraction']:.2f}%")
    print()

    # Band tables
    print("=== BAND TABLE: 674 ok months (parse without repair) ===")
    print("Band (hard_fraction) | Count")
    for lo, hi in BANDS:
        k = sum(1 for r in ok if lo <= r["hard_fraction"] < hi)
        if k > 0:
            print(f"  {band_label(lo,hi)}: {k}")
    print()

    all_measured = ok + repaired
    print(f"=== BAND TABLE: all {len(all_measured)} measured months (ok + repaired) ===")
    print("Band (hard_fraction) | Count")
    for lo, hi in BANDS:
        k = sum(1 for r in all_measured if lo <= r["hard_fraction"] < hi)
        if k > 0:
            print(f"  {band_label(lo,hi)}: {k}")
    print()

    # Full band tables (matching eligibility record format)
    print("=== FULL BAND TABLE (both) ===")
    print(f"{'Band':22s} | {'ok only':>8} | {'ok+repaired':>11}")
    for lo, hi in BANDS:
        ko = sum(1 for r in ok if lo <= r["hard_fraction"] < hi)
        ka = sum(1 for r in all_measured if lo <= r["hard_fraction"] < hi)
        print(f"  {band_label(lo,hi):20s} | {ko:>8} | {ka:>11}")
    print()
    print(f"Total ok: {len(ok)}")
    print(f"Total ok+repaired: {len(all_measured)}")

    # All repaired months
    print("\n=== ALL REPAIRED MONTHS (sorted by hard_fraction desc) ===")
    for r in sorted(repaired, key=lambda r: -r["hard_fraction"]):
        print(f"  {r['pair']} {r['month']}: exp={r['expected']} masked={r['masked']} open_only={r['open_only']} hard={r['hard']} "
              f"all={100*r['fraction']:.2f}% hard={100*r['hard_fraction']:.2f}%")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/rescued_masking.jsonl")
```
