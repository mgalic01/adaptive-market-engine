# Claude: sampled open-only mismatches support an opening-price convention hypothesis

- **Date:** 2026-09-26. **Author:** Claude. **Run:** Claude cloud session, Python 3.12.
- **Review correction (2026-09-27):** Codex narrowed the claims after reviewing PR #81.
  The historical counts and appendix below are preserved, not independently rerun.
  See the [independent review](2026-09-27-codex-checkin-review.md).
- **Question.** PR #66 reported 6,646 mismatched hours, including 5,277 (79%)
  classified as `open` only. This means high, low and close match exactly and the one
  compared volume field, `volume`, is within the configured drift tolerance, **not that
  volumes are identical**. `quote_volume` and `taker_buy_base` are not compared at all,
  so this class says nothing about them
  ([provenance note](2026-09-26-claude-volume-field-provenance.md)).
- **Working hypothesis.** In the reported sample, the first available minute has zero
  base volume and the official hourly open equals the first available positive-volume
  minute's open. This is consistent with differing opening-price conventions. It does
  not establish the mechanism for all 5,277 hours or prove that every input is valid.

## Evidence and limits

Claude reported the following measurements on hash-checked archives. The appendix
prints per-group counts for the first-available-minute and first-traded-minute checks;
this table combines the three invocations. Codex checked the source and arithmetic,
but did not rerun these archives or independently verify their measurement outputs.

| Sample | Open-only hours | First available minute has zero volume | Their open == first available traded minute's open |
| --- | ---: | ---: | ---: |
| DOGEUSDT, LINKUSDT — 2019-08..10 | 1,024 | 1,024 (100%) | 1,024 (100%) |
| BTCUSDT, ETHUSDT — 2017-10..11 | 207 | 207 (100%) | 207 (100%) |
| DOGEUSDT, TRXUSDT — 2020-05..06 | 458 | 458 (100%) | 458 (100%) |
| **Total** | **1,689** | **1,689 (100%)** | **1,689 (100%)** |

Claude reported 1 to 5 leading available zero-volume rows in 1,379 hours (81.6%),
and 6 or more in 310 (18.4%). These count rows present in the input, not necessarily
consecutive elapsed minutes: the script skips absent timestamps.

The sample contains **five unique pairs**, with DOGEUSDT appearing in two groups,
and three eras (2017, 2019, 2020). The 1,689 hours cover about 32% of the 5,277-hour
class. The remaining hours were not individually checked by this script. The samples
are not uniformly distributed through 2017–2024; later/high-volume eras remain a gap.

The appendix does not require all 60 minute timestamps, require a row at the exact
hour boundary, check that a zero-volume row is flat, or compare its price with the
previous close. Thus it does not by itself prove that the first clock minute was
untraded, or that Binance synthesized a carry-forward bar. Those are hypotheses
requiring additional evidence before any integrity-rule relaxation.

## An earlier hypothesis and its provenance limit

Claude's initial hypothesis was that the official hourly open carried the previous
close while the minute aggregate represented the first trade. The reported first-trade
comparison supports the opposite relationship in this sample. Claude also reported
that the minute aggregate's open equalled the previous minute's close in 1,023 of
1,024 cases. **That statistic is not computed by the published appendix**, and the
source/output for that separate check is not included here. Preserve it as an
unverified historical claim, not independently reproducible evidence for reclassification.

## What follows, and what does not

- **Potential convention difference, not a corruption verdict.** Matching high, low
  and close and a `volume` within the single configured tolerance support the hypothesis
  in sampled rows. They do not certify complete hours, say anything about the two
  uncompared volume fields, or prove all other integrity conditions.
- **No runtime change in this report.** Replay uses minute bars for execution, but
  `backtest/__main__.py:run_job` also loads official hourly archives for pair,
  market-proxy and breadth features. The current `SeriesFeatures` calculations do not
  consume candle opening prices (its `opens` array stores timestamps). That narrower
  observation does not make hourly archives irrelevant or prove future reclassification
  cannot change eligible data and replay results.
- **Reclassification remains a proposal.** The sampled mechanism may explain part
  of the high historical mismatch rates, including DOGEUSDT and LINKUSDT. A rule change
  needs complete-hour checks, broader evidence and separately reviewed acceptance
  conditions; a zero-volume first available row alone is insufficient.
- **No policy adoption.** Existing parser, spec, config, masks and integrity rules
  remain in force. No reserved-window access or experiment is authorized by this note.

## Reproducing

Save the exact appendix source as `data/open_mismatch.py` before using these commands.
The script calls `fetch_file` with `archive_get`: it can access the network even when
archives are cached. It has no built-in reserved-window guard. Use only separately
approved development inputs; the commands below name pre-2025 dates. These commands
were **not** run as part of Codex's review.

```
PYTHONPATH=src python data/open_mismatch.py DOGEUSDT,LINKUSDT 2019-08,2019-09,2019-10
PYTHONPATH=src python data/open_mismatch.py BTCUSDT,ETHUSDT 2017-10,2017-11
PYTHONPATH=src python data/open_mismatch.py DOGEUSDT,TRXUSDT 2020-05,2020-06
```

`data/` is git-ignored; the published script and pinned hash below remain unchanged.

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

Hash check: run `python scripts/check_reports.py` from the repository root; it extracts the fenced source, normalizes line endings and verifies the pinned hash without executing the appendix.
