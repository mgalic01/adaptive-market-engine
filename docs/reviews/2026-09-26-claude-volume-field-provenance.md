# Claude: what the open-only class actually compares, and the provenance now discharged

- **Date:** 2026-09-26. **Author:** Claude. **Run:** Claude cloud session, Python 3.12.
- **Provenance discharged (2026-09-27).** A second Claude cloud session
  (`session_012TnmLLUR1KhRL31nnfnujH`) still held the cached archives and published the
  measurement source and output at PR #83 comment 5850715025. The debt this file recorded
  as owed is settled; the sampling limit is not. See
  [Provenance discharged](#provenance-discharged-2026-09-27-source-published-and-hash-pinned)
  and the appendix, which supersede the "still owed" section below. That section is kept
  as the checkpoint it was when written, not as current status.
- **Scope.** One residual accuracy defect in
  [the open-only report](2026-09-26-claude-open-mismatch-explained.md), fixed in this PR,
  and the honest provenance status of Claude's exact-volume measurements. Code reading
  only: no archive was downloaded, opened or measured, and no integrity rule, parser,
  spec, mask or config changes.
- **Why this file exists.** The finding was reviewed at PR #82 head
  `0b550469d053b3e49c5a33cf684e19e0eb3fed71` and posted there as comment 5850581120 at
  about 22:44 UTC. PR #82 had already merged at **22:42:28 UTC** as
  `94b07a8ca7bf7092f4e5a2c57a167218d2bbb60a`, so that comment sits on a merged PR that
  nobody is notified about. This indexed note on `main` is the durable record instead.

## The defect: "volume fields", plural, overstates the comparison

PR #82 correctly replaced "volume agree by definition of this class" with a drift-tolerance
statement. The replacement then said "the volume **fields** pass the configured drift
tolerance", and the "What follows" bullet said "passing volume **tolerances**". Both plurals
claim more than the code does.

`compare_bars` (`src/crypto_grid_bot/backtest/replay.py:577`) compares exactly five values:

- four prices — `open`, `high`, `low`, `close` — for exact equality; and
- **one** volume field, `ours.volume` against `theirs.volume`, against the **single**
  `VOLUME_DRIFT_TOLERANCE` (`replay.py:572`, `Decimal("0.001")`).

`quote_volume` and `taker_buy_base` are never compared on this path. They appear only as
values carried through by `_with_prices_of` (`src/crypto_grid_bot/backtest/audit.py:144`),
which substitutes the reference prices so `differing_fields` can decide whether volume
alone would fail the tolerance. Nothing reads them for agreement.

So the open-only class establishes: three prices equal, `volume` within 0.1%, and
**nothing whatever** about the other two volume fields. The plural invited the opposite
reading. Fixed in this PR to the singular, naming the two uncompared fields explicitly.

## Provenance of Claude's exact-volume measurements: still owed (superseded 2026-09-27)

**Superseded.** This section records the status as written on 2026-09-26, when this
session had no archives. The source was published the same evening; see
[Provenance discharged](#provenance-discharged-2026-09-27-source-published-and-hash-pinned).
The container limitation below was real and is left unedited as the record of it.

At PR #80 comment 5850528551 Claude reported that `volume`, `quote_volume` and
`taker_buy_base` were all **exactly** equal across all 1,689 sampled hours. Codex
correctly recorded that as a newly reported measurement, not reproduced evidence, and
assigned Claude a separate indexed follow-up carrying its source.

**That source is not published here, and this session could not produce it.** `data/` does
not exist in this container: the cached archives did not survive, so the measurement
cannot be rerun and no hash-pinned appendix can be verified against real output.
Re-downloading archives was not authorized for this session, and the measurement script
has no built-in reserved-window guard.

Status, stated plainly:

| Claim | Standing |
| --- | --- |
| `compare_bars` compares four prices and one volume field | **Verified here** by reading `replay.py:577` and `audit.py:144`. No data needed. |
| All three volume fields exactly equal across 1,689 hours | **Unverified historical claim** *as of 2026-09-26.* Reported at PR #80 comment 5850528551, source not published, not reproducible in this container. **Superseded 2026-09-27:** source published and hash-pinned; see the section below. |

The conclusion of the open-only report does not rest on the second row, which is why its
absence blocked nothing. As written on 2026-09-26 the debt stood open, pending a
hash-pinned appendix and rerun output whenever archives were available again. They arrived
the same evening from a session that still held them; the next section records that.

## Provenance discharged (2026-09-27): source published and hash-pinned

A second Claude cloud session, `session_012TnmLLUR1KhRL31nnfnujH`, still had `data/`
intact — about 1.4 GB of cached, hash-checked archives — and published the measurement
source and its verbatim output at PR #83 comment 5850715025. The script is reproduced in
full in [the appendix](#appendix-datavolume_fieldspy-source), pinned by SHA-256.

**Standing of this evidence, precisely.** This is a **Claude-reported rerun with its
source verified by Codex, not independently rerun by Codex.** Codex extracted the 58-line
source from that comment and recomputed its SHA-256 as
`5cf501572069e6b807ec4283f0886a462be9e5820777d219ea320a199d9385d9`, matching the comment
(PR #83 comment 5851019971); this session recomputed the same digest from the comment body
and also matched. What is verified is that the published source is intact and that its
digest is agreed by three parties. **No archive measurement has been reproduced by anyone
other than the reporting session.**

**Measured result.** Across the three invocations, all three fields were exactly equal on
every open-only hour, and the worst relative `volume` difference was `0`:

| Sample | Open-only hours | `volume` | `quote_volume` | `taker_buy_base` |
| --- | ---: | ---: | ---: | ---: |
| DOGEUSDT, LINKUSDT — 2019-08..10 | 1,024 | 1,024 (100%) | 1,024 (100%) | 1,024 (100%) |
| BTCUSDT, ETHUSDT — 2017-10..11 | 207 | 207 (100%) | 207 (100%) | 207 (100%) |
| DOGEUSDT, TRXUSDT — 2020-05..06 | 458 | 458 (100%) | 458 (100%) | 458 (100%) |
| **Total** | **1,689** | **1,689 (100%)** | **1,689 (100%)** | **1,689 (100%)** |

1,024 + 207 + 458 = 1,689, the same sample as the open-only report. The reporting session
states this is an independent rerun with a rewritten script rather than a replay of the
earlier numbers, and that it reproduces them exactly.

**Limits that this does not discharge.**

- **Sampling.** The result covers those **1,689 hours only** — about 32% of the class. The
  remaining **3,588** of 5,277 hours are unmeasured for every field, and the samples are
  not uniformly distributed across 2017–2024.
- **The 1,023/1,024 previous-close statistic is a separate, still-open gap.** This script
  does not compute it; no published source reproduces it. It remains an unverified
  historical claim, exactly as
  [the open-only report](2026-09-26-claude-open-mismatch-explained.md) records.
- **Not offline, and not conditionally so.** The script calls `development_month(month)`
  before any fetch or cache access, so it refuses 2025-01 onward by construction rather
  than by careful argument choice — a real improvement on the script behind PR #80 comment
  5850528551. But `fetch_file` (`src/crypto_grid_bot/backtest/dataset.py:293-303`) calls
  `fetcher(path + ".CHECKSUM")` **unconditionally**, before it ever looks at the cache: the
  `target.exists()` test is at `dataset.py:319`. So **every invocation makes at least one
  network request per archive, even when every archive is already cached and verifies.**
  Only the archive body itself is conditional — it is downloaded when the local file is
  missing or its SHA-256 does not match. This must never be described as offline,
  cache-only, or as reaching the network merely for an absent or unverified archive.
- **No reclassification.** Nothing here advances any integrity-rule relaxation or
  reclassification of the open-only class; that decision stays with Codex and the owner.

## What I checked, and what I could not

- Verified at merged `main` `94b07a8ca7bf7092f4e5a2c57a167218d2bbb60a`: `compare_bars`
  and `differing_fields` bodies, `VOLUME_DRIFT_TOLERANCE`, and that no other call site
  compares `quote_volume` or `taker_buy_base` for archive agreement.
- Re-ran `python scripts/check_reports.py` after these edits: **seven** appendix scripts
  hash-checked (the new `data/volume_fields.py` appendix included), zero problems. The
  open-only appendix bytes are untouched by this PR.
- Independently confirmed, during the PR #82 review, that `features.py:57` stores
  `c.open_ms` (timestamps) and that `__main__.py:77,81,84` build `SeriesFeatures` from
  `load_hourly` for pair, market proxy and every breadth member.
- Recomputed the appendix SHA-256 from PR #83 comment 5850715025 myself: 58 lines plus the
  closing newline hash to `5cf5015720…9385d9`, matching both the comment and Codex's
  independent extraction.
- Read `audit.py:144` directly and confirmed it is the `_with_prices_of` definition, with
  the `return Kline(` body at `:145`. Citation corrected accordingly.
- **Could not check:** any archive measurement, including the 1,689-hour counts and the
  1,023/1,024 previous-close statistic. This session has no `data/`. The counts are
  published with their source in the appendix, reported by
  `session_012TnmLLUR1KhRL31nnfnujH`; the 1,023/1,024 statistic remains unsourced.

## Owners

- The measurement source is **discharged** — published, hash-pinned and agreed by three
  digests. Claude still owns any broader measurement beyond the 1,689-hour sample, and the
  unsourced 1,023/1,024 previous-close statistic.
- Codex and the owner still own whether to reclassify the open-only class; nothing here
  advances that decision, and no acceptance condition is proposed or changed.

## Reproducing

Save the exact appendix source as `data/volume_fields.py` before using these commands. They
need the development-window archives; `development_month` refuses 2025-01 onward.

**These commands are not offline.** `fetch_file` requests each archive's `.CHECKSUM` over
the network on every call, before any cache lookup, so running them reaches
`data.binance.vision` even when every archive is already cached and verifies. Only the
archive body is conditional, downloaded when the local copy is missing or its SHA-256 does
not match. Do not run them expecting a cache-only operation.

```
PYTHONPATH=src python data/volume_fields.py DOGEUSDT,LINKUSDT 2019-08,2019-09,2019-10
PYTHONPATH=src python data/volume_fields.py BTCUSDT,ETHUSDT 2017-10,2017-11
PYTHONPATH=src python data/volume_fields.py DOGEUSDT,TRXUSDT 2020-05,2020-06
```

## Appendix: `data/volume_fields.py` source

SHA-256: `5cf501572069e6b807ec4283f0886a462be9e5820777d219ea320a199d9385d9`

Reported by Claude cloud session `session_012TnmLLUR1KhRL31nnfnujH` at PR #83 comment
5850715025. `data/` is git-ignored, so the source lives here and the hash pins it.

```text
"""In the open-only mismatch class, are the three volume fields exactly equal?

The class only requires `volume` within VOLUME_DRIFT_TOLERANCE and never compares
`quote_volume` or `taker_buy_base` at all, so exact equality is a measurement, not a
definition. Development window only; reads the cached hash-checked archives.

    PYTHONPATH=src python data/volume_fields.py DOGEUSDT,LINKUSDT 2019-08,2019-09,2019-10
"""

import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

from crypto_grid_bot.backtest.audit import development_month, differing_fields
from crypto_grid_bot.backtest.dataset import archive_get, fetch_file, local_path
from crypto_grid_bot.backtest.klines import aggregate, read_archive
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE

DATA = Path("data")


def load(symbol: str, interval: str, month: str) -> list:
    development_month(month)  # never touch the reserved window
    fetch_file(DATA, symbol, interval, month, archive_get)
    return read_archive(local_path(DATA, symbol, interval, month), symbol, interval, month)[0]


def measure(symbol: str, month: str, t: Counter) -> Decimal:
    minutes = load(symbol, "1m", month)
    theirs = {k.open_ms: k for k in load(symbol, "1h", month)}
    ours = {k.open_ms: k for k in aggregate(minutes)}
    worst = Decimal(0)
    for hour in sorted(set(ours) & set(theirs)):
        a, b = ours[hour], theirs[hour]
        if differing_fields(a, b, VOLUME_DRIFT_TOLERANCE) != ("open",):
            continue
        t["open_only_hours"] += 1
        t["volume_exactly_equal"] += a.volume == b.volume
        t["quote_volume_exactly_equal"] += a.quote_volume == b.quote_volume
        t["taker_buy_base_exactly_equal"] += a.taker_buy_base == b.taker_buy_base
        if a.volume != b.volume and b.volume > 0:
            worst = max(worst, abs(a.volume - b.volume) / b.volume)
    return worst


if __name__ == "__main__":
    totals: Counter = Counter()
    worst = Decimal(0)
    for sym in sys.argv[1].split(","):
        for mon in sys.argv[2].split(","):
            worst = max(worst, measure(sym, mon, totals))
    n = totals["open_only_hours"]
    print(f"open-only hours: {n}")
    for key in ("volume", "quote_volume", "taker_buy_base"):
        v = totals[f"{key}_exactly_equal"]
        print(f"  {key} exactly equal: {v} ({100 * v / n:.2f}%)")
    print(f"  worst relative volume difference: {worst}")
```
