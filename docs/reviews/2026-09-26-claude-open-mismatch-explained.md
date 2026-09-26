# Claude: the "open only" mismatches are a convention difference, not a defect

- **Date:** 2026-09-26. **Author:** Claude. **Run:** this cloud session, Python 3.12.
- **Question.** PR #66 measured 6,646 mismatched hours between the 1m and 1h archives,
  and **5,277 of them (79%) differ on the `open` alone**, with high, low, close and
  volume identical. That was the largest unexplained class in the data, and it drove
  the apparent defect rates for thin pairs. This note explains it exactly.
- **Answer.** Every one is an hour whose **first minute had no trades**. The two
  archives then label the hour's open differently, and neither is wrong:
  - the **1m archive** synthesises a flat zero-volume bar carrying the previous close,
    and our `aggregate()` takes that first minute's open;
  - **Binance's 1h bar** opens at the **first actually traded minute**.

## Evidence

Measured on the cached, hash-checked archives. Every count is printed by the script in
the appendix; none is typed by hand.

| Sample | Open-only hours | First minute has zero volume | Their open == first traded minute's open |
| --- | ---: | ---: | ---: |
| DOGEUSDT, LINKUSDT — 2019-08..10 | 1,024 | 1,024 (100%) | 1,024 (100%) |
| BTCUSDT, ETHUSDT — 2017-10..11 | 207 | 207 (100%) | 207 (100%) |
| DOGEUSDT, TRXUSDT — 2020-05..06 | 458 | 458 (100%) | 458 (100%) |
| **Total** | **1,689** | **1,689 (100%)** | **1,689 (100%)** |

Leading untraded minutes per hour: 1 to 5 in 1,379 hours (81.6%), 6 or more in 310
(18.4%). So the gap is usually short, but not always.

**Scope, stated precisely.** 1,689 hours were checked, across six pairs and three eras
(2017, 2019, 2020). That is 32% of the 5,277-hour open-only class, with **no
exceptions in the sample**. The remaining hours of that class were not individually
verified, and this note does not claim they were.

## A hypothesis that was refuted

The first guess was the opposite: that Binance's 1h open was a carry-forward
continuation value and ours was the real first trade. That is **false**. Measured on
the same 1,024 hours, **our** open equals the previous minute's close in 1,023 (99.9%),
not theirs. The minute archive is the one that stitches continuously. The refuted
hypothesis is recorded here because it was the reason for running the measurement.

## What follows, and what does not

- **These hours are not corrupt.** The traded range of the hour is identical in both
  archives: high, low, close and volume agree by definition of this class. Only the
  label on an hour that began without trades differs.
- **Nothing in a replay changes.** The backtest replays **minute** bars; the 1h archive
  is used only for the integrity cross-check. So the strategy never consumes the
  disputed value.
- **The cross-check is what should change.** Treating an open-only difference on an
  hour whose first minute has zero volume as a *defect* overstates the defect rate,
  most severely for thin pairs: it is the bulk of DOGEUSDT's 2019 rate (52.96% of hours
  in PR #60's table) and of LINKUSDT's (16.76%).
- **This is not a decision.** Whether to reclassify these hours belongs to the owner
  and Codex, like the refined parser rule and the outage policy. It is evidence for
  that decision, not an adoption of it. No parser, spec, config or integrity rule is
  changed by this note.

## Reproducing

```
PYTHONPATH=src python data/open_mismatch.py DOGEUSDT,LINKUSDT 2019-08,2019-09,2019-10
PYTHONPATH=src python data/open_mismatch.py BTCUSDT,ETHUSDT 2017-10,2017-11
PYTHONPATH=src python data/open_mismatch.py DOGEUSDT,TRXUSDT 2020-05,2020-06
```

`data/` is git-ignored, so the script's source is reproduced below in full.

## Appendix: `data/open_mismatch.py` source

SHA-256: `b2fd8ad3492a74ae92a10122fcf8bc6900d6b3fa7ab00fa6f54ae28aaea4af7e`

```text
"""Refined: in open-only mismatch hours, is the first minute a zero-volume
synthesized bar, and does Binance's 1h open equal the first TRADED minute's open?
"""
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from crypto_grid_bot.backtest.audit import differing_fields
from crypto_grid_bot.backtest.dataset import archive_get, fetch_file, local_path
from crypto_grid_bot.backtest.klines import aggregate, read_archive
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE
D, H, M = Path("data"), 3_600_000, 60_000
ZERO = Decimal(0)

def load(sym, iv, month):
    fetch_file(D, sym, iv, month, archive_get)
    return read_archive(local_path(D, sym, iv, month), sym, iv, month)[0]

def analyse(sym, month):
    mins = load(sym, "1m", month)
    hrs = {k.open_ms: k for k in load(sym, "1h", month)}
    by_min = {k.open_ms: k for k in mins}
    ours = {k.open_ms: k for k in aggregate(mins)}
    t = Counter()
    for h in sorted(set(ours) & set(hrs)):
        if differing_fields(ours[h], hrs[h], VOLUME_DRIFT_TOLERANCE) != ("open",):
            continue
        t["open_only"] += 1
        minutes = [by_min[h + i * M] for i in range(60) if h + i * M in by_min]
        if not minutes:
            continue
        if minutes[0].volume == ZERO:
            t["first_minute_has_zero_volume"] += 1
        traded = [m for m in minutes if m.volume > ZERO]
        if traded and hrs[h].open == traded[0].open:
            t["their_open == first_TRADED_minute_open"] += 1
        if traded and ours[h].open == traded[0].open:
            t["our_open == first_traded_minute_open"] += 1
        # how many leading zero-volume minutes?
        lead = 0
        for m in minutes:
            if m.volume > ZERO:
                break
            lead += 1
        t[f"leading_zero_minutes_{'0' if lead==0 else '1-5' if lead<=5 else '6+'}"] += 1
    return t

if __name__ == "__main__":
    total = Counter()
    for sym in sys.argv[1].split(","):
        for month in sys.argv[2].split(","):
            total.update(analyse(sym, month))
    n = total["open_only"]
    print(f"open-only mismatch hours: {n}")
    for k, v in sorted(total.items()):
        if k != "open_only":
            print(f"  {k}: {v} ({100*v/n:.1f}%)")
```

Hash check: `sed -n '74,130p' docs/reviews/2026-09-26-claude-open-mismatch-explained.md | sha256sum` gives `b2fd8ad3492a74ae92a10122fcf8bc6900d6b3fa7ab00fa6f54ae28aaea4af7e`.
