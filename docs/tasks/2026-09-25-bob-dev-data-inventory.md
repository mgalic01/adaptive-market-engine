# Task for Bob: inventory of the development data, 2017-08 to 2024-12

- **Written by:** Claude, 2026-09-25, at the owner's request to give Bob as much
  checking work as possible.
- **Review:** starts automatically when this file is merged. The merge follows the
  current rule (Bob's NOTED on the PR, green checks, no required fix open).
- **Report:** `docs/reviews/2026-09-25-bob-dev-data-inventory.md`, nothing else.
- **Read first:** [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md).

## Why

The owner chose 2017-08 to 2024-12 as the development span. The data-reuse proposal
on PR #33 (still open, so not on `main`; read it with `git show
origin/claude/repo-connection-mqhoss:docs/reviews/2026-09-25-claude-data-reuse-proposal.md`)
estimates each pair's first complete month, and a task is needed to confirm them. Claude's quick sample already found that the project's strict parser **rejects**
BTCUSDT 2017-09 and 2018-02 ("open/close time is not a 1m boundary"). So "first
complete month" and "first month the project can use" are not the same thing. This
task measures, for every pair and month, what the project can actually use.

## Scope

- **Pairs:** the ten breadth-basket pairs of the dataset specs: BTCUSDT, ETHUSDT,
  BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, DOGEUSDT, LTCUSDT, LINKUSDT, TRXUSDT.
- **Months:** 2017-08 to 2024-12. The script refuses anything later. **Never** fetch or
  open 2025-01 or later.
- **Intervals:** 1m, 1h, 1d spot klines from `data.binance.vision`, through the
  project's own `fetch_file` (it checks Binance's published SHA-256 for every file).
- **Out of scope:** funding-rate archives (the project's fetch code reads spot klines
  only), any code, spec or manifest change, any backtest.

## Step 1: save and run the script

Save this exactly as `data/inventory.py`. Record its SHA-256 (`sha256sum`).

```python
"""python data/inventory.py FIRST LAST OUT_JSON SYMBOL [SYMBOL ...]

Inventory of Binance spot monthly kline archives (1m, 1h, 1d) for the development
span. Every archive is checked against Binance's published SHA-256 by the project's
own fetch code; the 1m file of each month is also compared with the official 1h file.
"""

import json
import multiprocessing
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from crypto_grid_bot.backtest.dataset import archive_get, fetch_file, local_path
from crypto_grid_bot.backtest.klines import INTERVAL_MS, month_bounds_ms, read_archive
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE, cross_check_hourly
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError

FIRST, LAST, OUT = sys.argv[1], sys.argv[2], Path(sys.argv[3])
SYMBOLS = sys.argv[4:]
DATA = Path("data")
# The reserved evaluation window starts 2025-01. Never go near it.
if not ("2017-01" <= FIRST <= LAST <= "2024-12"):
    sys.exit(f"refusing span {FIRST}..{LAST}: must lie within 2017-01..2024-12")


def months(first: str, last: str) -> list[str]:
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def gap_starts(path: Path, symbol: str, interval: str, month: str) -> list[str]:
    """UTC open times after which the next bar is missing (at most 20 listed)."""
    klines, _ = read_archive(path, symbol, interval, month)
    step = INTERVAL_MS[interval]
    out = []
    for a, b in zip(klines, klines[1:], strict=False):
        if b.open_ms - a.open_ms != step:
            when = datetime.fromtimestamp(a.open_ms / 1000, UTC).isoformat()
            out.append(f"after {when}: {(b.open_ms - a.open_ms) // step - 1} bars missing")
    return out[:20]


def one(job: tuple[str, str]) -> dict:
    symbol, month = job
    row: dict = {"symbol": symbol, "month": month}
    for interval in ("1m", "1h", "1d"):
        try:
            entry = fetch_file(DATA, symbol, interval, month, archive_get)
            if entry["status"] == "ok" and entry["gaps"]:
                path = local_path(DATA, symbol, interval, month)
                entry["gap_starts"] = gap_starts(path, symbol, interval, month)
        except (DataError, FeedError) as exc:
            entry = {"status": "error", "error": str(exc)}
        row[interval] = entry
    if row["1m"].get("status") == "ok" and row["1h"].get("status") == "ok":
        minutes, _ = read_archive(local_path(DATA, symbol, "1m", month), symbol, "1m", month)
        hours, _ = read_archive(local_path(DATA, symbol, "1h", month), symbol, "1h", month)
        window = month_bounds_ms(month)
        row["cross_check"] = cross_check_hourly(minutes, hours, window, VOLUME_DRIFT_TOLERANCE)
        row["cross_check_strict"] = cross_check_hourly(minutes, hours, window, Decimal(0))
    return row


if __name__ == "__main__":
    jobs = [(s, m) for s in SYMBOLS for m in months(FIRST, LAST)]
    rows = []
    with multiprocessing.get_context("fork").Pool(4) as pool:
        for row in pool.imap(one, jobs):
            rows.append(row)
            statuses = (row[i].get("status") for i in ("1m", "1h", "1d"))
            print(row["symbol"], row["month"], *statuses, flush=True)
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    print("rows", len(rows))
```

Run it from the repository root:

```sh
set -o pipefail
sha256sum data/inventory.py
python data/inventory.py 2017-08 2024-12 data/inventory.json \
  BTCUSDT ETHUSDT BNBUSDT SOLUSDT XRPUSDT ADAUSDT DOGEUSDT LTCUSDT LINKUSDT TRXUSDT \
  | tee data/inventory.log
sha256sum data/inventory.json
```

It prints one line per pair and month and ends with `rows 890` (10 pairs × 89 months).
Claude's timing: six months of one pair take about 15 seconds on 4 cores, so expect
roughly 30 to 40 minutes.

**What the fields mean** (read `src/crypto_grid_bot/backtest/klines.py` and
`replay.py` to confirm):
- `status`: `ok` (downloaded, hash-checked and parsed), `missing` (Binance publishes
  no file for that month), or `error` with the exact message. An `error` is a result
  to report, not a reason to stop.
- `rows`, `expected_rows`, `missing_rows`, `gaps`: from the project's parser. `gaps`
  also counts a partial first or last month (a pair listed mid-month).
  `gap_starts` lists only gaps **inside** the file, up to 20.
- `cross_check` and `cross_check_strict`: the 1m file aggregated to hours against
  Binance's own 1h file, with the project's volume-drift tolerance and without it.
  These are the counts the backtest's integrity gate uses.

## Step 2: analyse (your own work)

Using `data/inventory.json`, write short Python in `data/` for each item, and give each
script's SHA-256 in the report.

1. **Per pair:** the first month with any file, and the first **clean** month. A clean
   month has all three intervals `ok`, `missing_rows == 0`, and `cross_check` with
   `hours_mismatched`, `hours_missing`, `hours_absent_from_minutes` and
   `hours_incomplete` all 0.
2. **Per pair:** from its first clean month to 2024-12, every month that is **not**
   clean, with the reason: error message, missing rows, internal gaps (`gap_starts`)
   or cross-check counts. Group repeated identical reasons.
3. **Per pair:** the longest run of consecutive clean months, and the total number of
   clean months.
4. **Error messages:** every distinct `error` text, with how many files have it and
   in which pairs and months. For the parser errors (not a 1m/1h boundary), open **one**
   example CSV from the zip under `data/binance/...` and quote the offending line and
   the line before it, so Claude can tell whether the parser or the archive is at fault.
5. **Daily data:** the months where `1d` is `ok` but `1m` or `1h` is not. Daily
   signals (SMA50/SMA200) use `1d` only.
6. **Compare with the proposal's estimates:** BTC 2017-09, ETH 2017-10, ADA 2018-05,
   XRP 2018-06. State where they hold and where they do not.

## Step 3: report

`docs/reviews/2026-09-25-bob-dev-data-inventory.md`:
- the task file, the commit (`git rev-parse HEAD`), the Python version, and the start
  and end time;
- the SHA-256 of `data/inventory.py`, `data/inventory.json` and each analysis script;
- a summary table: pair, first file month, first clean month, clean months, longest
  clean run, months not clean;
- the per-pair lists from Step 2 (grouped, so the report stays under 150 KB);
- the error table and the CSV example;
- **Ideas and proposals** (separate section): for example, how the development
  windows or folds could avoid the defects, whether any error looks like a parser bug,
  and what a later task should check. Each idea says why it helps and how to test it.
  These are proposals for Claude and the owner, not decisions.

Do not paste the JSON into the report. It stays in `data/` and is lost with the
machine, which is why its SHA-256 and your scripts must be in the report.

## Stop conditions

- The script refuses the span, or crashes (a Python traceback, not a per-file
  `error`): stop and report the full traceback.
- Any file for 2025-01 or later appears anywhere: stop and report. (The workflow also
  fails the run.)
- Anything else unexpected: stop, keep everything, report.

## Self-check before your final message

Go through [`docs/BOB_PRACTICE.md`](../BOB_PRACTICE.md), "Before you finish". In
particular: `rows 890` was printed; every number in the report comes from a named
script; and `git status --porcelain --untracked-files=all` shows only your report.
