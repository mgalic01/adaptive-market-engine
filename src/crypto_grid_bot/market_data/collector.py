"""Capture one coherent diagnostic observation, never execute or simulate orders."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from crypto_grid_bot.market_data.client import HOST, PublicClient
from crypto_grid_bot.market_data.parsing import (
    HOUR_MS,
    DataError,
    diagnostics,
    integer,
    parse_book,
    parse_candles,
    parse_instrument,
    symbol_name,
)

SCHEMA_VERSION = 1


def encode(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":"), allow_nan=False)


def server_time(payload: Any) -> int:
    try:
        return integer(payload["serverTime"])
    except (KeyError, TypeError) as exc:
        raise DataError("missing exchange server clock") from exc


class Collector:
    def __init__(
        self,
        client: PublicClient,
        *,
        wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.client = client
        self.wall_ms = wall_ms
        self.monotonic = monotonic

    def capture(self, symbol: str) -> dict[str, Any]:
        symbol_name(symbol)
        start = self.monotonic()
        local_start = self.wall_ms()
        first = server_time(self.client.get("/api/v3/time", {}))
        local_first = self.wall_ms()
        self._check_clock(first, local_start, local_first)
        metadata = self.client.get("/api/v3/exchangeInfo", {"symbol": symbol})
        instrument = parse_instrument(metadata, symbol)
        # Request only hours closed BEFORE the first clock sample, even across an hour boundary.
        end_ms = first // HOUR_MS * HOUR_MS - 1
        raw_candles = self.client.get(
            "/api/v3/klines",
            {
                "symbol": symbol,
                "interval": "1h",
                "limit": "250",
                "endTime": str(end_ms),
            },
        )
        candles = parse_candles(raw_candles, first)
        book_requested = self.wall_ms()
        raw_book = self.client.get("/api/v3/depth", {"symbol": symbol, "limit": "100"})
        book_received = self.wall_ms()
        book = parse_book(raw_book, instrument)
        local_last_start = self.wall_ms()
        last = server_time(self.client.get("/api/v3/time", {}))
        received = self.wall_ms()
        self._check_clock(last, local_last_start, received)
        duration = self.monotonic() - start
        if not 0 <= duration <= 10 or not 0 <= last - first <= 10000:
            raise DataError("capture exceeded ten-second coherence window")
        if abs((received - local_start) - duration * 1000) > 1000:
            raise DataError("local clock changed during capture")
        if last < first or received < local_start:
            raise DataError("clock moved backwards during capture")
        raw = {"exchange_info": metadata, "klines": raw_candles, "depth": raw_book}
        return {
            "schema_version": SCHEMA_VERSION,
            "source": HOST,
            "symbol": symbol,
            "capture_id": f"{symbol}:{last}",
            "server_started_ms": first,
            "server_finished_ms": last,
            "received_ms": received,
            "book_requested_ms": book_requested,
            "book_received_ms": book_received,
            "book_timestamp_kind": "local_request_window_not_exchange_event_time",
            "instrument": asdict(instrument),
            "candles": [asdict(c) for c in candles],
            "book": asdict(book),
            "diagnostics": diagnostics(candles, book),
            "raw_sha256": hashlib.sha256(encode(raw).encode()).hexdigest(),
            "raw": raw,
            "decision": "observe_only",
            "orders_authorized": False,
            "blockers": [
                "universe membership and asset identity not verified",
                "broad-market regime and news freshness unavailable",
                "account eligibility and actual fees unverified",
                "snapshots cannot establish incremental fill liquidity",
            ],
        }

    @staticmethod
    def _check_clock(server: int, before: int, after: int) -> None:
        if not 0 <= after - before <= 2000:
            raise DataError("server clock request was too slow or clock moved backwards")
        midpoint = (before + after) // 2
        if abs(server - midpoint) > 5000:
            raise DataError("local/exchange clock skew exceeds five seconds")
