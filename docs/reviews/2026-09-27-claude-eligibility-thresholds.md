# Owner decision: the eligibility rule for development folds

- **Date:** 2026-09-27. **Author:** Claude (cloud session `session_012TnmLLUR1KhRL31nnfnujH`).
- **Status: owner decision, recorded before any variant result exists.** The owner
  confirmed decisions 1 and 2 of
  [the fold-grid report](2026-09-27-claude-fold-grid-and-eligibility.md) and asked for the
  two open values to be proposed from measurement rather than picked. Fixing the rule now
  is what keeps the walk-forward honest: choosing it after seeing returns would be the
  post-hoc tuning `START_HERE.md` step 1 forbids.
- **Scope.** Sets the mask granularity, the maximum masked fraction and the repair rule's
  price tolerance. It changes no code, no parser and no criterion, and says nothing about
  any strategy's performance. Reads cached development archives only; no network, and
  nothing touches the reserved window.

## The decisions

1. **Mask defect hours; do not fail their month.** Decision 1 of the fold-grid report.
2. **Adopt Bob's [refined parser rule](2026-09-26-bob-refined-parser-rule.md)** for
   off-boundary close times. Decision 2.
3. **Maximum masked fraction: 2% of a month's expected hours, counting real defects
   only.** A pair-month carrying more is not eligible, masked or otherwise.
4. **The open-only convention class is excluded from that count by its own named rule**,
   not by a price tolerance.
5. **Price tolerance on repaired hours: none — strict equality**, `Decimal(0)`.

## Why 2%, and why counted on real defects

Decision 3's number is worth little without decision 4, and the measurement shows why.

Every pair-month of the development window was measured from the local cache: **890
pair-months**, of which **674 parse**, 106 do not (the repair rule's territory) and 110
are not cached here. For each, the share of expected hours a mask would have to cover,
split into the **open-only convention class** — the hour's first minute had no trades, so
the 1m archive carries the previous close while the official 1h bar opens at the first
traded minute ([finding](2026-09-26-claude-open-mismatch-explained.md),
[provenance](2026-09-26-claude-volume-field-provenance.md)) — and **everything else**.

### The convention class dominates the apparent defect rate

| Pair-year | All masked hours | Real defects |
| --- | ---: | ---: |
| DOGEUSDT 2019 | **53.1%** | **11.91%** |
| DOGEUSDT 2020 | 24.7% | 4.45% |
| LINKUSDT 2019 | 17.1% | 3.56% |
| LINKUSDT 2020 | 0.7% | 0.18% |

Between 74% and 82% of the apparent rate in the worst pair-years is the convention
difference. DOGE 2019's 53% — the figure the fold-grid report cited as making its 79.6%
an upper bound — is **11.9%** of real defects.

### Where the distribution breaks

Real-defect share across the 674 parseable pair-months:

| Band | Months |
| --- | ---: |
| below 0.1% | 481 |
| 0.1% to 0.5% | 111 |
| 0.5% to 1% | 29 |
| 1% to 2% | 31 |
| **2% to 3%** | **4** |
| 3% to 5% | 2 |
| 5% to 7.5% | 3 |
| 7.5% to 10% | 6 |
| 10% to 15% | 6 |
| 15% to 25% | 1 |

**There is no empty gap.** I looked for one and will not claim it. What there is is a
sharp break at 2%: 31 months in [1%, 2%), then 4 in [2%, 3%). Below 2% lies **96.7%** of
all parseable pair-months. The worst real-defect month anywhere in the development window
is DOGEUSDT 2019-09 at **16.5%**; nothing exceeds it.

The choice is insensitive over a wide range, which is the next best thing to a gap:

| Cap | Pair-months excluded |
| --- | ---: |
| 2% | 22 of 674 (3.3%) |
| 3% | 18 (2.7%) |
| 5% | 16 (2.4%) |

Any cap in [2%, 5%] differs by at most six months. **2%** is the tightest value sitting
after the break: a month at the cap still has 98% of its hours intact, about 14 masked
hours in 720.

### Why the count must exclude the convention class

Applying the same cap to **raw** mismatch counts instead:

| Cap | Excluded on all masked hours | Excluded on real defects | Wrongly excluded |
| --- | ---: | ---: | ---: |
| 1% | 81 (12.0%) | 53 (7.9%) | 28 |
| **2%** | **50 (7.4%)** | **22 (3.3%)** | **28** |
| 3% | 39 (5.8%) | 18 (2.7%) | 21 |
| 5% | 33 (4.9%) | 16 (2.4%) | 17 |

**A 2% cap on raw mismatches discards 28 pair-months whose real defect rate is under
2%** — sound months, dropped for a labelling convention. They include DOGEUSDT 2020-08,
-09, -10 and -11 (real defects 1.1% to 1.8%), BTCUSDT 2017-10 (1.3%), ADAUSDT 2019-12
(1.8%), SOLUSDT 2020-11 (1.3%) and LINKUSDT 2019-12 (0.7%). Four consecutive months of
DOGE, the pair whose usable folds are scarcest.

So **what is counted matters more than where the line is drawn.** That is the substance
of decision 4, and it is why the open-mismatch finding turned out to be load-bearing
rather than academic.

## Why no price tolerance, and no bundling

Decision 5 keeps `Decimal(0)`: an hour holding a repaired row must match the official
archive exactly. Bob's refined rule already measured usability under strict hour checks,
so this changes nothing he reported — it declines to loosen it.

The open question his report left was whether a **price tolerance** should be added. It
should not be used for this. The thing such a tolerance would absorb is the convention
class, and that class is 74% to 82% of apparent defects in thin months. Folding it into a
tolerance would silently settle the open-only reclassification — a separate question the
owner and Codex have not decided — and would do so in a form that also hides real price
disagreements of the same magnitude. Decision 4 handles the convention class by name,
visibly, and leaves everything else strict.

## What this does not decide

- **Whether a masked month replays validly.** The cap bounds how much is masked; it does
  not establish that a masked hour can be skipped without distorting a grid's state. That
  is replay policy and is not settled here.
- **The open-only reclassification** in the cross-check itself. Untouched.
- **Anything about returns.** No strategy was run. Every figure is data coverage.
- **The 110 not-cached pair-months.** Absent from this container's cache, not known to be
  absent upstream. The bands describe the 674 that parse.

## What I checked, and what I could not

- Every figure comes from the appendix script run over the local cache; none is typed by
  hand. It makes no network request, and calls `development_month` before touching any
  month, so the reserved window cannot be read.
- The convention class is identified exactly as the merged finding defines it —
  `differing_fields` returning `("open",)` alone — not by a heuristic.
- **Corroboration.** This measurement gives DOGE 2019 a total of 2,287 masked hours; Bob
  independently measured 2,275 for the same pair-year, with different code on a different
  machine. Close but not identical, and the difference is definitional rather than a
  discrepancy to reconcile: his calendar counts listed hours, this counts expected hours
  from the pair's first listed hour, and his excludes unparsed months by construction.
- **Could not check:** whether any specific masked month is tradeable. That needs a
  replay, which would mean looking at returns before this rule is fixed — exactly what
  must not happen. The cap is therefore a data-coverage bound justified by the
  distribution, not by strategy behaviour.

## Reproducing

`data/` is git-ignored, so the source is reproduced below in full and the hash pins it.
Run from the repository root with the archives cached; it reads nothing else.

## Appendix: `data/masked_fraction.py` source

SHA-256: `a3dfd49b2ac77b5c0058d68441a9c810e3df51b6ac8012592af51220212b9547`

```text
"""Per-pair-month share of hours a mask would have to cover, from the LOCAL cache only.

Decision 1 of the draft spec needs a maximum masked fraction a month may carry and
still count as usable. The merged hourly defect calendar reports per-pair-YEAR shares;
a monthly cap needs monthly figures. This measures them.

A masked hour is any expected hour that is not cleanly present in both archives: absent
from either, or present in both but failing compare_bars under the configured drift
tolerance. Expected hours run from the pair's first listed hour of the month.

Reads cached archives directly — no network, no fetch, no reserved window (months are
filtered against DEVELOPMENT_END). Unparseable months are skipped and counted: the
repair rule, not the mask, is what reaches those.

    PYTHONPATH=src python data/masked_fraction.py > data/masked_fraction.jsonl
"""

import json
import sys
from pathlib import Path

from crypto_grid_bot.backtest.audit import (
    ABSENT_BOTH, DEVELOPMENT_END, HOUR_MS, PRESENT_BOTH,
    development_month, differing_fields, expected_hours, hour_statuses,
)
from crypto_grid_bot.backtest.dataset import local_path
from crypto_grid_bot.backtest.klines import aggregate, read_archive
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE
from crypto_grid_bot.market_data.parsing import DataError

DATA = Path("data")
PAIRS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
         "ADAUSDT", "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT"]


def months():
    y, m = 2017, 8
    while f"{y:04d}-{m:02d}" <= DEVELOPMENT_END:
        yield f"{y:04d}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def measure(symbol, month):
    development_month(month)
    paths = {iv: local_path(DATA, symbol, iv, month) for iv in ("1m", "1h")}
    if not all(p.exists() for p in paths.values()):
        return {"status": "not_cached"}
    try:
        minutes, _ = read_archive(paths["1m"], symbol, "1m", month)
        hours, _ = read_archive(paths["1h"], symbol, "1h", month)
    except DataError as exc:
        return {"status": "unparsed", "detail": str(exc)[:80]}
    if not minutes:
        return {"status": "empty"}
    ours = {k.open_ms: k for k in aggregate(minutes)}
    theirs = {k.open_ms: k for k in hours}
    first_hour = minutes[0].open_ms // HOUR_MS * HOUR_MS
    statuses = hour_statuses(ours, theirs, expected_hours(first_hour, month))
    masked = open_only = 0
    for hour, status in statuses.items():
        if status != PRESENT_BOTH:
            masked += 1
            continue
        fields = differing_fields(ours[hour], theirs[hour], VOLUME_DRIFT_TOLERANCE)
        if not fields:
            continue
        masked += 1
        # The open-only class is a convention difference, not corruption: the hour's
        # first minute had no trades, so the 1m archive carries the previous close while
        # the official 1h bar opens at the first traded minute (2026-09-26 report, and
        # its provenance note). Counted separately so a mask threshold can be set on
        # corruption alone, and so the two are never conflated.
        if fields == ("open",):
            open_only += 1
    expected = len(statuses)
    hard = masked - open_only
    return {"status": "ok", "expected": expected, "masked": masked,
            "open_only": open_only, "hard": hard,
            "fraction": round(masked / expected, 6) if expected else None,
            "hard_fraction": round(hard / expected, 6) if expected else None,
            "absent_both": sum(1 for s in statuses.values() if s == ABSENT_BOTH)}


if __name__ == "__main__":
    for symbol in PAIRS:
        for month in months():
            row = {"pair": symbol, "month": month, **measure(symbol, month)}
            print(json.dumps(row), flush=True)
            if row["status"] == "ok":
                print(f"{symbol} {month} all={row['fraction']:.4f} hard={row['hard_fraction']:.4f}", file=sys.stderr, flush=True)
```
