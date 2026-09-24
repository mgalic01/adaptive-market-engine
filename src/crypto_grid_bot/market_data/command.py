"""Finite foreground collection sessions with durable failure reporting."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from crypto_grid_bot.market_data.client import FeedError, PublicClient
from crypto_grid_bot.market_data.collector import Collector, encode
from crypto_grid_bot.market_data.parsing import DataError, symbol_name
from crypto_grid_bot.market_data.store import ObservationStore


def capture_once(collector: Collector, store: ObservationStore, symbol: str) -> dict[str, Any]:
    symbol_name(symbol)
    store.check_cooldown(collector.wall_ms())
    try:
        observation = collector.capture(symbol)
        saved = store.save(observation)
    except (DataError, FeedError) as exc:
        store.failure(
            symbol,
            collector.wall_ms(),
            str(exc),
            exc.retry_after if isinstance(exc, FeedError) else 0,
        )
        raise
    return {
        "mode": "read_only_market_capture",
        "capture_id": observation["capture_id"],
        "saved": saved,
        "diagnostics": observation["diagnostics"],
        "decision": observation["decision"],
        "orders_authorized": False,
        "blockers": observation["blockers"],
    }


def run_capture(database: Path, symbol: str, samples: int, poll_seconds: int) -> int:
    symbol_name(symbol)
    if not 1 <= samples <= 120 or not 60 <= poll_seconds <= 3600:
        raise DataError("samples must be 1-120 and polling interval 60-3600 seconds")
    store = ObservationStore(database)
    collector = Collector(PublicClient())
    try:
        for index in range(samples):
            if index:
                time.sleep(poll_seconds)
            print(encode(capture_once(collector, store, symbol)), flush=True)
        return 0
    except (DataError, FeedError, sqlite3.Error) as exc:
        print(
            encode({"status": "stopped", "reason": str(exc), "orders_authorized": False}),
            flush=True,
        )
        return 2
    finally:
        store.close()
