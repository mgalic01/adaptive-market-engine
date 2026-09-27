# Proposed eligibility thresholds for development folds (from measurement)

- **Date:** 2026-09-27. **Author:** Claude (cloud session `session_012TnmLLUR1KhRL31nnfnujH`).
- **Status: two values PROPOSED from measurement. Not yet an owner decision.** The owner
  confirmed the *approach* — adopt hour-level masking and Bob's refined repair rule
  ([PR #92](https://github.com/mgalic01/adaptive-market-engine/pull/92), still open and
  changing) — and asked for the two values it leaves open to be derived rather than picked.
  **The owner has not confirmed 2% or `Decimal(0)`; this record proposes them.** An earlier
  version of this document called them an owner decision, which overstated the
  confirmation given. Corrected after review.
- **Why record it before results exist.** Whichever values are adopted must be fixed before
  any variant runs, or choosing them becomes the post-hoc tuning `START_HERE.md` step 1
  forbids. Proposing them now, with the measurement attached, is what makes that possible.
- **Scope.** Proposes the maximum masked fraction and the repair rule's price tolerance. It
  changes no code, parser or criterion, and says nothing about any strategy's performance.
  Reads cached development archives only; no network, and nothing touches the reserved
  window.

## The decisions

1. **Mask defect hours; do not fail their month.** The mask setting of PR #92.
2. **Adopt Bob's [refined parser rule](2026-09-26-bob-refined-parser-rule.md)** for
   off-boundary close times. The repair setting of PR #92.
3. **Proposed maximum masked fraction: 2% of a month's expected hours, counting real
   defects only.** A pair-month carrying more would not be eligible, masked or otherwise.
   **Measured on the raw-parseable population only** — see the population section below;
   the cutoff is unmeasured for months the repair rule rescues, so the rule is proposed
   for that population rather than validated on it.
4. **The open-only convention class is excluded from that count by its own named rule**,
   not by a price tolerance.
5. **Proposed price tolerance on repaired hours: none — strict equality**, `Decimal(0)`.

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
difference. DOGE 2019's 53% — which PR #92 cites among the reasons its usable-fold count is
a ceiling — is **11.9%** of real defects.

**This record deliberately quotes no headline count from PR #92.** That PR is open and its
figure has already moved once while this document sat in review: a start-bound correction
took it from 199 usable pair-folds to 185. Everything below rests on the measurement in
this record's own appendix, so it does not go stale when #92 changes again. How the two fit
together is for #92 to state once both are merged.

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

## The measurement's population is narrower than the rule's

**The cap is measured on the 674 months that parse *without* repair. The 106 the refined
repair rule would rescue are not in any band above.** The script classifies a month as
`unparsed` and moves on; it does not apply the repair rule and then measure. So the
distribution describes a population narrower than the eligible set the adopted rule
creates, and a repaired month's real-defect share is unmeasured here.

That matters in a specific direction: the ten exchange-wide unparseable months are the ones
the repair rule exists for, and nothing here shows whether their defect shares sit below
2% or above it. If they sit above, the cap would exclude the very months the repair rule was
adopted to recover — and the two decisions would work against each other. Measuring that
needs the repair rule applied before the parse split, which this script does not do.

**This is the largest open limitation of the proposal**, raised by Codex's review, and it is
a reason to treat 2% as provisional until the repaired months are measured too.

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
- **Corroboration, and a correction to how it was explained.** This measurement gives
  DOGE 2019 **2,287** masked hours; Bob independently measured **2,275**. An earlier version
  of this record attributed the 12-hour gap to a definitional difference (listed versus
  expected hours, and his exclusion of unparsed months). **That explanation was wrong**, and
  Codex Cloud's review identified the real cause. DOGE 2019 has exactly **12 absent-both
  hours — 8 in 2019-08 and 4 in 2019-11** — which Bob's hourly calendar routes to the outage
  calendar by construction while this script counts them as masked. 2,287 − 2,275 = 12. So
  the two measurements agree **exactly**, which is a stronger result than the approximate
  agreement previously claimed, and it was only visible once the cause was named correctly.
- **The open-only deduction is by field signature, not per-instance verification.** An hour
  is deducted from the real-defect count when `differing_fields` returns `("open",)` alone.
  That assumes the mechanism established in
  [the open-mismatch finding](2026-09-26-claude-open-mismatch-explained.md) — an untraded
  first minute — holds for **every** such hour. It was verified on 1,689 of them, not on all
  5,277. This script does not re-check the first minute's volume per instance, so the split
  between convention and real defects inherits that inference.
- **This is a defect count, not a validity proof.** The script compares aggregated 1m
  against the official 1h bars hour by hour. It does **not** check that each hour holds a
  full 60 minutes, and it does not run the daily or hourly validation the audit tooling
  performs. So a month under the cap is a month whose *compared* hours mostly agree — not a
  month shown to be replayable. Read the counts as structural, on the raw-parseable
  population, and nothing more.
- **Archive bytes are not re-verified here.** The script calls `read_archive` on the local
  cache directly rather than going through `fetch_file`, so Binance's published SHA-256 is
  not re-checked during this measurement. The cached files were checksum-verified when
  fetched; this run trusts that, and a reader reproducing it on a tampered cache would get
  tampered numbers without warning.
- **Listing hour derived once per symbol, as `audit_run.audit_outages` does.** An earlier
  version took `minutes[0]` per month, which shortens the expected-hours denominator for any
  later month whose data starts late, understating the defect share. Measured on this cache:
  nine months have a shortened denominator and **all nine are listing months**, where
  shortening is correct — zero later months are affected, so the two derivations agree here.
  The fix therefore removes a fragility rather than changing a number. That claim rests on
  the nine-month count above, measured directly; a full re-run under the fixed script was
  still in progress when this was written, so the PR thread carries its result rather than
  this record resting on it.
- **Could not check:** whether any specific masked month is tradeable. That needs a
  replay, which would mean looking at returns before this rule is fixed — exactly what
  must not happen. The cap is therefore a data-coverage bound justified by the
  distribution, not by strategy behaviour.

## Reproducing

`data/` is git-ignored, so both sources are reproduced below in full and their hashes pin
them. Run from the repository root with the archives cached.

```
PYTHONPATH=src python data/masked_fraction.py > data/masked_fraction.jsonl
python data/masked_bands.py data/masked_fraction.jsonl
```

**Every table above comes from the second script**, not from ad-hoc code. An earlier version
published tables with no committed reducer, so they could not be regenerated from the
appendix; Codex's review caught that.

## Appendix: `data/masked_fraction.py` source

SHA-256: `f23e1c8bca7f2ead15ee3e2683776d31459e6fcdfc7d7c72223e04ead65fa1be`

Produces one JSON line per pair-month. The hash changed from the version first pushed
here (`a3dfd49b…`): that one derived the listing hour per month, and the fix derives it
once per symbol. Both derivations agree on this cache for the reason given above; the
full re-run's result is reported on the PR rather than asserted here.

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


def measure(symbol, month, listing_hour):
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
    # Derive the pair's listing hour ONCE, from its first cached month, and reuse it —
    # the pattern audit_run.audit_outages uses. Taking minutes[0] per month would shorten
    # the expected-hours denominator for any later month whose data starts late, which
    # understates the defect share. Measured on this cache: nine months have a shortened
    # denominator and all nine are listing months, where shortening is correct, so the two
    # derivations agree here — but only by luck of the data, not by construction.
    statuses = hour_statuses(ours, theirs, expected_hours(listing_hour, month))
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


def listing_hour_of(symbol):
    """The pair's first cached hour, from the earliest month that parses."""
    for month in months():
        path = local_path(DATA, symbol, "1m", month)
        if not path.exists():
            continue
        try:
            minutes, _ = read_archive(path, symbol, "1m", month)
        except DataError:
            continue
        if minutes:
            return minutes[0].open_ms // HOUR_MS * HOUR_MS
    return None


if __name__ == "__main__":
    for symbol in PAIRS:
        listing = listing_hour_of(symbol)
        if listing is None:
            print(json.dumps({"pair": symbol, "status": "no_cached_month"}), flush=True)
            continue
        for month in months():
            row = {"pair": symbol, "month": month, **measure(symbol, month, listing)}
            print(json.dumps(row), flush=True)
            if row["status"] == "ok":
                print(f"{symbol} {month} all={row['fraction']:.4f} hard={row['hard_fraction']:.4f}", file=sys.stderr, flush=True)
```

## Appendix: `data/masked_bands.py` source

SHA-256: `6bb4940179e76c45950cd4061a662054e7d1e1ae82beb4b4f6a184078c8eda40`

Reduces that JSONL to every table this record publishes — the two band tables, the cap
table, the pair-year comparison and the worst real-defect month. Added because the
tables originally had no committed reducer.

```text
"""Reduce masked_fraction.jsonl to the tables the eligibility record publishes.

Codex's review of PR #100 found the record's tables had no committed reducer: they were
produced by ad-hoc code that was never published, so a reader could not regenerate them
from the appendix. This is that reducer. Every table in the record comes from here.

    PYTHONPATH=src python data/masked_fraction.py > data/masked_fraction.jsonl
    python data/masked_bands.py data/masked_fraction.jsonl
"""

import json
import sys
from collections import Counter

BANDS = [
    (0.0, 0.001), (0.001, 0.005), (0.005, 0.01), (0.01, 0.02), (0.02, 0.03),
    (0.03, 0.05), (0.05, 0.075), (0.075, 0.10), (0.10, 0.15), (0.15, 0.25),
    (0.25, 0.50), (0.50, 1.01),
]
CAPS = [0.01, 0.02, 0.03, 0.05]
PAIR_YEARS = [("DOGEUSDT", "2019"), ("DOGEUSDT", "2020"), ("LINKUSDT", "2019"), ("LINKUSDT", "2020")]


def load(path):
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def main(path):
    rows = load(path)
    status = Counter(r["status"] for r in rows)
    ok = [r for r in rows if r["status"] == "ok"]
    n = len(ok)
    print(f"rows {len(rows)}; statuses {dict(status)}")
    print(f"parseable pair-months measured: {n}")
    print("\nNOTE: the cap is measured on these raw-parseable months only. Months the")
    print("refined repair rule would rescue are counted as 'unparsed' here and are NOT")
    print("in any band below, so the distribution describes a population narrower than")
    print("the adopted rule's eligible set.")

    for key, label in (("hard_fraction", "HARD defects only"), ("fraction", "ALL masked hours")):
        print(f"\n=== {label} ===")
        for lo, hi in BANDS:
            k = sum(1 for r in ok if lo <= r[key] < hi)
            print(f"  [{lo:>5.3f},{hi:>5.3f})  {k:>4}")

    print("\n=== months excluded by a cap ===")
    print("  cap    on all masked        on hard only        wrongly excluded")
    for cap in CAPS:
        a = sum(1 for r in ok if r["fraction"] > cap)
        h = sum(1 for r in ok if r["hard_fraction"] > cap)
        wrong = sum(1 for r in ok if r["fraction"] > cap and r["hard_fraction"] <= cap)
        print(f"  {cap:>5.2f}  {a:>4} ({100 * a / n:>4.1f}%)        {h:>4} ({100 * h / n:>4.1f}%)"
              f"        {wrong:>3}")

    print("\n=== pair-years: convention class versus real defects ===")
    for pair, year in PAIR_YEARS:
        sel = [r for r in ok if r["pair"] == pair and r["month"].startswith(year)]
        if not sel:
            continue
        exp = sum(r["expected"] for r in sel)
        allm = sum(r["masked"] for r in sel)
        hard = sum(r["hard"] for r in sel)
        absent = sum(r["absent_both"] for r in sel)
        print(f"  {pair} {year}: {len(sel):>2} months, expected {exp:>5}, "
              f"all {100 * allm / exp:>5.1f}%, real {100 * hard / exp:>5.2f}%, "
              f"absent-both {absent}")

    worst = max(ok, key=lambda r: r["hard_fraction"])
    print(f"\nworst real-defect month: {worst['pair']} {worst['month']} "
          f"{worst['hard_fraction']:.4f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/masked_fraction.jsonl")
```
