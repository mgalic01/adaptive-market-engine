# Claude: two errors in the hourly defect calendar, measured

- **Date:** 2026-09-27
- **Corrects:** [Bob: hour-level defect calendar](2026-09-26-bob-hourly-defect-calendar.md)
  (PR #60, merged). That report is annotated in place; its tables, appendices and hashes
  are unchanged, because they record what Bob's scripts produced.
- **Found by:** the 2026-09-27 full audit; measured by a Claude agent, then every figure
  below reproduced independently from the scripts in this file's appendix.
- **Owner's go for the follow-up Bob run:** 2026-09-27, "i approve al paid bob reruns".

## Artifacts

| Artifact | SHA-256 |
| --- | --- |
| `data/calendar_denominator.py` | `ee5dd6d9cb7d588c8c74cb8f4077ed41287f39cbc3b84264f7903742317861a3` |
| `data/eventwide_per_hour.py` | `6bb93dd063c287ab67283336d17d221e4012e28173f8652704b37405350bd943` |
| 890-row measurement from the eligibility record's first script | `c2aad1ab9c1c0a739d791800ccaeee553b5d2e2f4fcfc154ddf21133b9f234e7` |

Both scripts are in the appendix. The first reads the 890-row measurement of the
[eligibility record](2026-09-27-claude-eligibility-thresholds.md) and Bob's published
table. The second reads the local 1m and 1h archive cache for the nine months the
published events fall in (2017-08 to 2022-04), calls `development_month` on each month,
and makes no network request.

## Error 1: hours missing from both archives are in neither column

Bob's per-pair table divides defect hours by "processed" hours. Both counts are keyed on
the hours found in either archive, so an hour missing from **both** the 1m and the 1h
archive is in neither the numerator nor the denominator. The table's heading calls this a
"share of listed hours"; it is not.

**Proof that this is the only difference.** For every one of the **69** published
pair-year cells, the measurement's `masked − absent_both` equals Bob's defect count and its
`expected − absent_both` equals Bob's processed count, both at once. The measurement's
defect predicate is the same as Bob's, and its denominator is every expected hour from
the pair's listing hour (`audit.expected_hours`).

**What is missing:** 468 pair-hours, 58 distinct UTC hours in 12 months. In each of those
months every listed pair is affected, for the same number of hours. These are the 14
outages of the [outage calendar](2026-09-26-bob-outage-calendar.md), whose `Total Expected`
column already publishes the correct denominators (BTCUSDT 2018: 6,600, not 6,579).

| Month | Pairs | Hours each | Pair-hours |
| --- | ---: | ---: | ---: |
| 2018-06 | 7 | 11 | 77 |
| 2018-10 | 7 | 3 | 21 |
| 2018-11 | 7 | 7 | 49 |
| 2019-03 | 8 | 6 | 48 |
| 2019-05 | 8 | 10 | 80 |
| 2019-08 | 9 | 8 | 72 |
| 2019-11 | 9 | 4 | 36 |
| 2020-04 | 9 | 2 | 18 |
| 2020-06 | 9 | 3 | 27 |
| 2020-11 | 10 | 1 | 10 |
| 2021-03 | 10 | 1 | 10 |
| 2021-09 | 10 | 2 | 20 |
| **Total** | | **58 distinct hours** | **468** |

**Corrected per-pair totals** (parsed months; the 14 unparsed months stay excluded):

| Pair | Published | Corrected | Hours added |
| --- | --- | --- | ---: |
| BTCUSDT | 209/54,442 = 0.38% | 267/54,500 = 0.49% | 58 |
| ETHUSDT | 241/54,442 = 0.44% | 299/54,500 = 0.55% | 58 |
| BNBUSDT | 336/53,219 = 0.63% | 394/53,277 = 0.74% | 58 |
| SOLUSDT | 166/34,118 = 0.49% | 170/34,122 = 0.50% | 4 |
| XRPUSDT | 47/51,822 = 0.09% | 105/51,880 = 0.20% | 58 |
| ADAUSDT | 302/51,490 = 0.59% | 360/51,548 = 0.70% | 58 |
| DOGEUSDT | 3,904/42,327 = 9.22% | 3,925/42,348 = 9.27% | 21 |
| LTCUSDT | 61/52,622 = 0.12% | 119/52,680 = 0.23% | 58 |
| LINKUSDT | 1,329/45,673 = 2.91% | 1,366/45,710 = 2.99% | 37 |
| TRXUSDT | 51/50,163 = 0.10% | 109/50,221 = 0.22% | 58 |
| **All ten** | **6,646/490,318 = 1.355%** | **7,114/490,786 = 1.450%** | **468** |

The script prints all 36 pair-year cells that change. The ones that matter:

- **Two cells read 0.00% and are not zero:** BTCUSDT 2019 is 28/8,040 (0.35%) and XRPUSDT
  2020 is 6/6,600 (0.09%).
- The understatement is largest where the rate is smallest: TRXUSDT 2018 goes from 0.02%
  to 0.53%. No cell in the original table is an upper bound for its pair-year.
- 2021 goes from 0.02–0.03% to 0.07–0.09% for every pair. 2022 to 2024 are unchanged.
- The headline pairs barely move: DOGEUSDT 2019 52.96% → 53.09%, LINKUSDT 2019 16.76% →
  17.07%, ADAUSDT 2019 3.08% → 3.42%.

The day-level step has the same construction (the union of day keys found), with no
branch for a day missing from both archives. No published figure changes, because the
longest outage is 10 consecutive hours, so no day is missing whole; the defect is recorded
for the next script.

## Error 2: "exchange-wide" is not computed as defined

The report defines an event as exchange-wide "if at least 80% of listed pairs at that time
are affected". Bob's events script instead takes the union of affected pairs and the union
of listed pairs **over the whole event** and divides them. An event where a different
single pair is defective in each hour scores 100%, and that is the most common pattern in
the published table, not an edge case.

The second script rebuilds the hour statuses as Bob's calendar script does and first
reproduces the published union figures for **all 78 rows exactly**. Then, per hour:

| Rule | Events | Hours |
| --- | ---: | ---: |
| Published (union over the event) | 78 | 211 |
| **At least 80% in every hour (the report's stated rule)** | **27** | **32** |
| At least 80% in at least one hour | 54 | 137 |

Only 73 of the 211 published hours individually reach 80%. All 24 single-hour events
survive; 51 of the 54 multi-hour events do not. The survivors are events 1, 5, 7, 11, 23,
25, 27, 29, 32, 34, 35, 42, 50, 51, 52, 57, 58, 60, 62, 63, 64, 72, 73, 75, 76, 77 and 78.

Examples, affected/listed in each hour:

- **#74** (2019-11-13 04:00, 2 h): 8/9, then **1/9**.
- **#71** (2017-11-21 18:00, 10 h): eight of the ten hours at **1/3**.
- **#4** (2017-08-19 13:00, 17 h): 1/2 in 12 of the 17 hours.

The "Listed pairs affected" column is also the union over the event, not a figure for any
hour in it.

**Event summary by year, reclassified.** The runs are unchanged; demoted events move to
pair-specific.

| Year | Exchange-wide events | Exchange-wide hours | Pair-specific events | Pair-specific hours |
| --- | --- | --- | --- | --- |
| 2017 | 71 → **21** | 203 → **26** | 250 → **300** | 425 → **602** |
| 2018 | 2 | 2 | 79 | 83 |
| 2019 | 1 → **0** | 2 → **0** | 1,633 → **1,634** | 3,579 → **3,581** |
| 2020 | 0 | 0 | 1,093 | 1,794 |
| 2021 | 1 | 1 | 3 | 3 |
| 2022 | 3 | 3 | 3 | 3 |
| 2023 | 0 | 0 | 4 | 4 |
| 2024 | 0 | 0 | 0 | 0 |
| **Total** | **78 → 27** | **211 → 32** | **3,065 → 3,116** | **5,891 → 6,070** |

71 of the 78 published events fall in 2017, all with only 2 or 3 pairs listed, where
"80%" means every pair. (Corrected at review, 2026-09-28: this line first said "66 of the
78 … in 2017–2018". The two 2018 events, 72 and 73, have 4 and 7 pairs listed.) The outage calendar requires at least 5 listed pairs; this report has no
such floor. Whether to add one is a definition choice for the re-run below, stated there,
not decided here.

## What these two corrections cannot settle

Fixing error 1 adds the 58 outage hours to the defect hours, and events are merged from
consecutive defect hours. So the event boundaries themselves change. One case is exact:
the outage calendar's 2019-11-13 02:00–03:00 all-pairs outage is contiguous with event
#74 (04:00–05:00). Merged, the run is 9/9, 9/9, 8/9, 1/9 and does not meet the per-hour
rule. The other 13 outages cannot be checked here, because the 3,065 pair-specific events
were never published. A Bob task
([combined defect census](../tasks/2026-09-27-bob-combined-defect-census.md)) re-runs
both corrections together.

## Names

Three different predicates are called "exchange-wide" in merged records, on three
disjoint sets of hours:

1. this report: the union ratio over an event, at least 0.8, no floor (78 events);
2. the outage calendar: every listed pair missing from both archives in every hour, at
   least 5 pairs listed (14 events);
3. the fold-grid record: months failing the parser for 90–100% of listed pairs (10 months).

From the re-run on, each count names its rule: **`breadth-per-hour-v1`** (at least 80% of
the pairs listed at that hour, in every hour), **`outage-all-pairs-v1`** (the outage
calendar's rule, unchanged), and **`unparsed-breadth`** (a month measure, never called an
event). "Exchange-wide" appears only as a gloss next to one of those names.

## Downstream records

| Record | Affected? |
| --- | --- |
| [Eligibility thresholds](2026-09-27-claude-eligibility-thresholds.md) (2% cap) | **No.** It uses `expected_hours`, so it counts these hours. Had it used Bob's table it would have admitted two months wrongly: ADAUSDT 2019-05 (2.28% real → 0.95%) and TRXUSDT 2018-06 (2.35% → 0.00%). |
| [Fold grid and eligibility](2026-09-27-claude-fold-grid-and-eligibility.md) | **Yes: two sentences, corrected in place.** BTCUSDT 2018–2024 is 69 defect hours in 52,680 (0.131%), not 11 in 52,622 (0.021%), and **none** of the ten pairs is below 0.12% over those years (six were said to be). Its conclusion, a fold count from the test-month check, does not depend on these rates and stands. |
| `docs/EXPERIMENT_SPEC_V1.md` §5, the comparison mask | **No.** The mask is all-or-nothing per pair-window and cites no rate, and every hour missing from both archives falls in 2018–2021, outside both current windows. A future window over one of the 12 months will fail the mask for every pair, which the old table hid. |
| [Outage calendar](2026-09-26-bob-outage-calendar.md) | No figure changes. Its 2019-11-13 outage merges with event #74 once error 1 is fixed (above); a forward note is added. |
| [Codex retrospective review](2026-09-26-codex-retrospective-review.md) | Its "denominator excludes unparsed months by definition" is incomplete: it also excludes hours missing from both archives. |

## Appendix

### 1. `data/calendar_denominator.py`

```text
"""Recompute the hourly defect calendar's per-pair table on the expected-hours denominator.

Input: the 890-row measurement printed by data/masked_fraction.py (eligibility record),
whose `masked` count uses the same defect predicate as Bob's data/calendar.py and whose
`expected` count is every hour from the pair's listing hour, from
crypto_grid_bot.backtest.audit.expected_hours. Bob's table drops hours absent from both
archives from the numerator and the denominator. This script shows that exactly that
class is the difference, cell by cell, then prints the corrected table.

    python data/calendar_denominator.py data/masked_fraction.jsonl \
        docs/reviews/2026-09-26-bob-hourly-defect-calendar.md
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict

PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT",
]  # fmt: skip
YEARS = range(2017, 2025)
CELL = re.compile(r"(\d+)/(\d+) \(")


def published(report: str) -> dict[tuple[str, int], tuple[int, int]]:
    """(pair, year) -> (defect hours, processed hours) from Bob's per-pair table."""
    table: dict[tuple[str, int], tuple[int, int]] = {}
    for line in open(report, encoding="utf-8"):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        pair = cells[0].strip("*") if cells else ""
        if pair not in PAIRS or len(cells) < 9:
            continue
        for year, cell in zip(YEARS, cells[1:9], strict=True):
            found = CELL.match(cell)
            if found:
                table[pair, year] = (int(found.group(1)), int(found.group(2)))
    return table


def main(measurement: str, report: str) -> None:
    sums: dict[tuple[str, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    absent_by_month: dict[str, dict[str, int]] = defaultdict(dict)
    for line in open(measurement, encoding="utf-8"):
        row = json.loads(line)
        if row["month"] > "2024-12":
            raise SystemExit(f"{row['month']} is in the reserved window")
        if row["status"] != "ok":
            continue
        cell = sums[row["pair"], int(row["month"][:4])]
        for key in ("expected", "masked", "absent_both"):
            cell[key] += row[key]
        if row["absent_both"]:
            absent_by_month[row["month"]][row["pair"]] = row["absent_both"]

    pub = published(report)
    matched = [
        key
        for key, (defect, processed) in pub.items()
        if (sums[key]["masked"] - sums[key]["absent_both"], sums[key]["expected"] - sums[key]["absent_both"])
        == (defect, processed)
    ]  # fmt: skip
    print(f"published pair-year cells: {len(pub)}")
    print("masked - absent_both == published defect and expected - absent_both ==")
    print(f"published processed, both at once: {len(matched)} of {len(pub)}")

    print("\nabsent from both archives, by month (pair-hours):")
    total = 0
    for month, pairs in sorted(absent_by_month.items()):
        hours = sorted(set(pairs.values()))
        total += sum(pairs.values())
        print(f"  {month}: {len(pairs)} pairs x {hours} h = {sum(pairs.values())}")
    print(f"  total pair-hours: {total}")

    print("\ncorrected, pair-years whose figures change (published -> expected hours):")
    for pair in PAIRS:
        for year in YEARS:
            cell = sums.get((pair, year))
            if not cell or not cell["absent_both"] or (pair, year) not in pub:
                continue
            defect, processed = pub[pair, year]
            print(
                f"  {pair} {year}: {defect}/{processed} = {100 * defect / processed:.2f}%"
                f" -> {cell['masked']}/{cell['expected']} = "
                f"{100 * cell['masked'] / cell['expected']:.2f}%"
            )

    print("\nper pair, all parsed months:")
    grand = [0, 0, 0, 0]
    for pair in PAIRS:
        d0 = sum(pub[k][0] for k in pub if k[0] == pair)
        p0 = sum(pub[k][1] for k in pub if k[0] == pair)
        d1 = sum(sums[k]["masked"] for k in sums if k[0] == pair)
        p1 = sum(sums[k]["expected"] for k in sums if k[0] == pair)
        grand = [grand[0] + d0, grand[1] + p0, grand[2] + d1, grand[3] + p1]
        print(
            f"  {pair}: {d0}/{p0} = {100 * d0 / p0:.2f}% -> {d1}/{p1} = {100 * d1 / p1:.2f}%"
            f" (+{d1 - d0} h)"
        )
    d0, p0, d1, p1 = grand
    print(f"  all ten: {d0}/{p0} = {100 * d0 / p0:.3f}% -> {d1}/{p1} = {100 * d1 / p1:.3f}%")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

### 2. `data/eventwide_per_hour.py`

```text
"""Apply the hourly calendar's own "exchange-wide" definition hour by hour.

Bob's data/events.py divides the union of affected pairs by the union of listed pairs
over a whole event, so an event where a different single pair is defective each hour
scores 1.0. The report defines exchange-wide as "at least 80% of listed pairs at that
time are affected". This script rebuilds the hour statuses the way data/calendar.py does
(the union of hour keys found in the two archives, the same compare_bars and tolerance),
from the local cache, for the months the 78 published events fall in. It first shows it
reproduces every published row's union figures, then applies the stated per-hour rule.

A per-hour ratio can never exceed the union ratio, so the per-hour rule can only demote
a published event, never promote one: reading these months is sufficient.

    PYTHONPATH=src python data/eventwide_per_hour.py \
        docs/reviews/2026-09-26-bob-hourly-defect-calendar.md
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from crypto_grid_bot.backtest.audit import development_month
from crypto_grid_bot.backtest.dataset import local_path
from crypto_grid_bot.backtest.klines import INTERVAL_MS, aggregate, read_archive
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE, compare_bars

DATA = Path("data")
HOUR_MS = INTERVAL_MS["1h"]
# First archive month per pair: the same listing rule data/calendar.py applies.
LISTING = {
    "BTCUSDT": "2017-08", "ETHUSDT": "2017-08", "BNBUSDT": "2017-11", "LTCUSDT": "2017-12",
    "ADAUSDT": "2018-04", "XRPUSDT": "2018-05", "TRXUSDT": "2018-06", "LINKUSDT": "2019-01",
    "DOGEUSDT": "2019-07", "SOLUSDT": "2020-08",
}  # fmt: skip
ROW = re.compile(
    r"^\| (\d+) \| (\d{4}-\d\d-\d\d \d\d:00) \| (\d{4}-\d\d-\d\d \d\d:00) \| (\d+) \| [^|]+ \|"
    r" (\d+)/(\d+) \("
)


def to_ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=UTC).timestamp() * 1000)


def month_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m")


def main(report: str) -> None:
    events = [
        (int(m[1]), to_ms(m[2]), to_ms(m[3]), int(m[4]), int(m[5]), int(m[6]))
        for m in (ROW.match(line) for line in open(report, encoding="utf-8"))
        if m
    ]
    months = sorted({month_of(start) for _, start, *_ in events} | {month_of(e[2]) for e in events})
    defective: dict[int, set[str]] = defaultdict(set)
    for month in months:
        development_month(month)
        for symbol, first in LISTING.items():
            if month < first:
                continue
            minutes, _ = read_archive(local_path(DATA, symbol, "1m", month), symbol, "1m", month)
            hours, _ = read_archive(local_path(DATA, symbol, "1h", month), symbol, "1h", month)
            ours = {bar.open_ms: bar for bar in aggregate(minutes, HOUR_MS)}
            theirs = {bar.open_ms: bar for bar in hours}
            for hour in set(ours) | set(theirs):
                a, b = ours.get(hour), theirs.get(hour)
                if a is None or b is None:
                    defective[hour].add(symbol)
                elif compare_bars(a, b, VOLUME_DRIFT_TOLERANCE) not in ("match", "drift"):
                    defective[hour].add(symbol)

    def listed(hour: int) -> set[str]:
        return {s for s, first in LISTING.items() if month_of(hour) >= first}

    rows = []
    for number, start, end, count, aff, lst in events:
        span = range(start, end + HOUR_MS, HOUR_MS)
        assert len(span) == count, number
        per_hour = [(len(defective[h] & listed(h)), len(listed(h))) for h in span]
        union_aff = set().union(*(defective[h] & listed(h) for h in span))
        union_listed = set().union(*(listed(h) for h in span))
        rows.append((number, start, count, per_hour, (len(union_aff), len(union_listed)), (aff, lst)))

    print(f"published events: {len(rows)}, hours: {sum(r[2] for r in rows)}")
    same = sum(1 for r in rows if r[4] == r[5])
    print(f"union affected/listed reproduced exactly: {same} of {len(rows)}")

    every = [r for r in rows if all(a / n >= 0.8 for a, n in r[3])]
    some = [r for r in rows if any(a / n >= 0.8 for a, n in r[3])]
    good_hours = sum(1 for r in rows for a, n in r[3] if a / n >= 0.8)
    print(f"at least 80% in every hour (the stated rule): {len(every)} events, "
          f"{sum(r[2] for r in every)} hours")  # fmt: skip
    print(f"at least 80% in at least one hour: {len(some)} events, {sum(r[2] for r in some)} hours")
    print(f"hours individually at 80% or more: {good_hours} of {sum(r[2] for r in rows)}")
    print("events meeting the stated rule: " + ", ".join(str(r[0]) for r in every))

    print("\nby year: exchange-wide events/hours, published -> stated rule")
    for year in sorted({month_of(r[1])[:4] for r in rows}):
        pub = [r for r in rows if month_of(r[1]).startswith(year)]
        kept = [r for r in pub if r in every]
        print(f"  {year}: {len(pub)}/{sum(r[2] for r in pub)} -> {len(kept)}/{sum(r[2] for r in kept)}")

    print("\nexamples (affected/listed per hour):")
    for number in (4, 49, 69, 71, 74):
        row = next(r for r in rows if r[0] == number)
        print(f"  #{number}: " + ", ".join(f"{a}/{n}" for a, n in row[3]))


if __name__ == "__main__":
    main(sys.argv[1])
```
