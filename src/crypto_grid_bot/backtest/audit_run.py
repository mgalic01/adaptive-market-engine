"""Run the data audits over the cached, hash-checked development archives.

    python -m crypto_grid_bot.backtest.audit_run outages --out data/outages.json
    python -m crypto_grid_bot.backtest.audit_run rules --out data/rules.json

``outages`` covers every basket pair from 2017-08 to 2024-12: hour statuses, outage
events and the field breakdown of every mismatched hour. ``rules`` measures the narrow
and refined close-repair rules on the months the strict parser rejects. Both fetch only
through ``fetch_file``, which checks Binance's SHA-256, and both refuse any month after
2024-12. The printed summary is what a review compares against a report.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.audit import (
    ABSENT_BOTH,
    DEVELOPMENT_END,
    HOUR_MS,
    development_month,
    differing_fields,
    expected_hours,
    hour_statuses,
    outage_events,
    rule_outcome,
)
from crypto_grid_bot.backtest.dataset import ArchiveParseError, archive_get, fetch_file, local_path
from crypto_grid_bot.backtest.klines import Kline, aggregate, read_archive, read_member
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE
from crypto_grid_bot.market_data.client import FeedError

BASKET = [
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
FIRST_MONTH = "2017-08"
# The months the strict parser rejects (PR #49's inventory, PR #59's classes).
UNPARSED_MONTHS = [
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
]

Fetcher = Callable[[str], bytes | None]


def months(first: str = FIRST_MONTH, last: str = DEVELOPMENT_END) -> list[str]:
    out = []
    year, month = map(int, first.split("-"))
    while f"{year:04d}-{month:02d}" <= last:
        out.append(development_month(f"{year:04d}-{month:02d}"))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _fetch(data: Path, symbol: str, interval: str, month: str, get: Fetcher) -> str:
    """'ok', 'missing' or 'unparsed'; retries transport failures, never hash failures."""
    development_month(month)  # Refuse reserved data before any network or cache access.
    for attempt in range(4):
        try:
            entry = fetch_file(data, symbol, interval, month, get)
        except ArchiveParseError:
            return "unparsed"
        except FeedError:
            if attempt == 3:
                raise
            time.sleep(2**attempt)
            continue
        return "missing" if entry.get("status") == "missing" else "ok"
    raise AssertionError("unreachable")


def _rows(data: Path, symbol: str, interval: str, month: str) -> list[list[str]]:
    text = read_member(
        local_path(data, symbol, interval, month), f"{symbol}-{interval}-{month}.csv"
    )
    return list(csv.reader(io.StringIO(text)))


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


def audit_outages(data: Path, get: Fetcher = archive_get) -> dict[str, Any]:
    first_hour: dict[str, int] = {}
    unparsed: list[str] = []
    absent: dict[int, set[str]] = defaultdict(set)
    listed: dict[int, set[str]] = defaultdict(set)
    status_counts: Counter[tuple[str, str, str]] = Counter()
    combos: Counter[tuple[str, str]] = Counter()
    for symbol in BASKET:
        for month in months():
            minute_state = _fetch(data, symbol, "1m", month, get)
            if minute_state == "missing":
                continue
            if symbol not in first_hour:
                first_row = _rows(data, symbol, "1m", month)[0]
                first_hour[symbol] = int(first_row[0]) // HOUR_MS * HOUR_MS
            hour_state = _fetch(data, symbol, "1h", month, get)
            if minute_state != "ok" or hour_state != "ok":
                unparsed.append(f"{symbol} {month}")
                continue
            minutes, _ = read_archive(local_path(data, symbol, "1m", month), symbol, "1m", month)
            hours, _ = read_archive(local_path(data, symbol, "1h", month), symbol, "1h", month)
            ours: dict[int, Kline] = {k.open_ms: k for k in aggregate(minutes)}
            theirs: dict[int, Kline] = {k.open_ms: k for k in hours}
            statuses = hour_statuses(ours, theirs, expected_hours(first_hour[symbol], month))
            for hour, status in statuses.items():
                listed[hour].add(symbol)
                status_counts[(symbol, month[:4], status)] += 1
                if status == ABSENT_BOTH:
                    absent[hour].add(symbol)
            for hour in sorted(set(ours) & set(theirs)):
                fields = differing_fields(ours[hour], theirs[hour], VOLUME_DRIFT_TOLERANCE)
                if fields:
                    combos[(month[:4], "+".join(fields))] += 1
    events = outage_events(absent, listed)
    return {
        "first_hour": {s: _utc(h) for s, h in first_hour.items()},
        "unparsed": unparsed,
        "status_counts": [[*key, n] for key, n in sorted(status_counts.items())],
        "events": [
            {
                "start": _utc(e.start_ms),
                "end_exclusive": _utc(e.end_ms),
                "hours": e.hours,
                "kind": e.kind,
                "listed": e.listed,
                "pairs": list(e.pairs),
            }
            for e in events
        ],
        "mismatch_fields": [[year, fields, n] for (year, fields), n in sorted(combos.items())],
        "summary": {
            "events": len(events),
            "event_hours": sum(e.hours for e in events),
            "mismatched_hours": sum(combos.values()),
        },
    }


def audit_rules(data: Path, get: Fetcher = archive_get) -> dict[str, Any]:
    rows = []
    usable = Counter[str]()
    for month in UNPARSED_MONTHS:
        for symbol in BASKET:
            states = {iv: _fetch(data, symbol, iv, month, get) for iv in ("1m", "1h")}
            if "missing" in states.values():
                continue
            minute_rows = _rows(data, symbol, "1m", month)
            hour_rows = _rows(data, symbol, "1h", month)
            row: dict[str, Any] = {"month": month, "symbol": symbol}
            for rule in ("narrow", "refined"):
                outcome = rule_outcome(minute_rows, hour_rows, month, rule)
                usable[rule] += outcome.usable
                row[rule] = outcome.reason or "usable"
            rows.append(row)
    return {"pair_months": rows, "summary": {"pair_months": len(rows), **usable}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("audit", choices=("outages", "rules"))
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_outages(args.data) if args.audit == "outages" else audit_rules(args.data)
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
