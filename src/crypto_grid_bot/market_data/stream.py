"""Read-only Binance public best-price stream; never orders, keys or account data.

Binance's spot ``<symbol>@bookTicker`` messages carry no exchange event time, so
freshness is measured on local receipt, and a silent connection is treated as dead.
A disconnect clears every price: there is no stale fallback.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import InvalidStatus, WebSocketException

from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError, amount, integer, symbol_name

STREAM_HOST = "data-stream.binance.vision"
MAX_SYMBOLS = 10
MAX_MESSAGE = 16_384
# Binance closes stream connections after 24 h; rotate well before that.
CONNECTION_LIFETIME_SECONDS = 23 * 3600
# No message at all for this long means the connection is dead or the market halted.
SILENCE_SECONDS = 30.0
# A connection that stayed up this long resets the backoff ladder.
STABLE_SECONDS = 60.0
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 32, 60, 120, 300)
# Binance allows 300 connection attempts per 5 minutes per IP; stay far below it.
MAX_CONNECTS = 10
CONNECT_WINDOW_SECONDS = 300.0


@dataclass(frozen=True)
class BookTick:
    symbol: str
    update_id: int
    bid: Decimal
    bid_size: Decimal
    ask: Decimal
    ask_size: Decimal
    received_ms: int


def stream_url(symbols: Iterable[str]) -> str:
    names = [symbol_name(symbol) for symbol in symbols]
    if not 1 <= len(names) <= MAX_SYMBOLS or len(set(names)) != len(names):
        raise DataError(f"stream requires 1-{MAX_SYMBOLS} distinct symbols")
    streams = "/".join(f"{name.lower()}@bookTicker" for name in names)
    return f"wss://{STREAM_HOST}/stream?streams={streams}"


def parse_book_ticker(raw: str | bytes, symbols: frozenset[str], received_ms: int) -> BookTick:
    if not isinstance(raw, str) or len(raw) > MAX_MESSAGE:
        raise DataError("stream message must be bounded text")
    try:
        message = json.loads(raw)
        stream, data = message["stream"], message["data"]
        symbol = symbol_name(data["s"])
        if symbol not in symbols or stream != f"{symbol.lower()}@bookTicker":
            raise DataError("unexpected stream or symbol")
        tick = BookTick(
            symbol,
            integer(data["u"]),
            amount(data["b"]),
            amount(data["B"]),
            amount(data["a"]),
            amount(data["A"]),
            received_ms,
        )
    except (ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError("invalid book ticker message") from exc
    if tick.bid >= tick.ask:
        raise DataError("locked or crossed best prices")
    return tick


class PriceBook:
    """Latest validated best prices; readers get fresh data or an error, never a guess."""

    def __init__(self, symbols: Iterable[str], *, max_age_ms: int = 5000) -> None:
        self.symbols = frozenset(symbol_name(symbol) for symbol in symbols)
        if not 0 < max_age_ms <= 60_000:
            raise ValueError("price max age must be 1-60000 ms")
        self._max_age_ms = max_age_ms
        self._latest: dict[str, BookTick] = {}

    def update(self, tick: BookTick) -> bool:
        """Return False for an exact repeat; a regressing update ID is corrupt data."""
        previous = self._latest.get(tick.symbol)
        if previous is not None:
            if tick.update_id < previous.update_id:
                raise DataError("book ticker update ID regressed")
            if tick.update_id == previous.update_id:
                return False
        self._latest[tick.symbol] = tick
        return True

    def clear(self) -> None:
        self._latest.clear()

    def latest(self, symbol: str, now_ms: int) -> BookTick:
        tick = self._latest.get(symbol)
        if tick is None:
            raise FeedError(f"no live price for {symbol}")
        if not 0 <= now_ms - tick.received_ms <= self._max_age_ms:
            raise FeedError(f"live price for {symbol} is stale")
        return tick


@dataclass
class StreamStats:
    connects: int = 0
    disconnects: int = 0
    rotations: int = 0
    silences: int = 0
    messages: int = 0
    ticks: int = 0
    duplicates: int = 0
    invalid: int = 0
    stopped_reason: str = ""
    errors: list[str] = field(default_factory=list)


class Connection(Protocol):
    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[Connection]]


async def default_connector(url: str) -> Connection:
    # Proxy settings come from HTTPS_PROXY/NO_PROXY; TLS uses the system trust store.
    return await ws_connect(
        url,
        open_timeout=10,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
        max_size=MAX_MESSAGE,
        max_queue=256,
    )


class PriceStream:
    def __init__(
        self,
        symbols: Iterable[str],
        *,
        connector: Connector = default_connector,
        monotonic: Callable[[], float] = time.monotonic,
        wall_ms: Callable[[], int] = lambda: time.time_ns() // 1_000_000,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        max_age_ms: int = 5000,
    ) -> None:
        self.url = stream_url(symbols)
        self.book = PriceBook(symbols, max_age_ms=max_age_ms)
        self.stats = StreamStats()
        self._connector = connector
        self._monotonic = monotonic
        self._wall_ms = wall_ms
        self._sleep = sleep
        self._jitter = jitter
        self._attempts: deque[float] = deque()

    def _note(self, error: str) -> None:
        self.stats.errors = (self.stats.errors + [error])[-20:]

    async def _wait_for_connect_budget(self, deadline: float) -> bool:
        now = self._monotonic()
        while self._attempts and now - self._attempts[0] >= CONNECT_WINDOW_SECONDS:
            self._attempts.popleft()
        if len(self._attempts) < MAX_CONNECTS:
            return True
        wait = self._attempts[0] + CONNECT_WINDOW_SECONDS - now
        if now + wait >= deadline:
            return False
        await self._sleep(wait)
        return True

    async def run(
        self, seconds: float, on_tick: Callable[[BookTick], None] | None = None
    ) -> StreamStats:
        """Stream for a finite time. HTTP 418/429 on connect stops without retrying."""
        if not 0 < seconds <= 86400:
            raise ValueError("stream duration must be 0-86400 seconds")
        deadline = self._monotonic() + seconds
        failures = 0
        while self._monotonic() < deadline:
            if not await self._wait_for_connect_budget(deadline):
                self.stats.stopped_reason = "connection attempt budget exhausted"
                break
            self._attempts.append(self._monotonic())
            opened = self._monotonic()
            try:
                connection = await self._connector(self.url)
            except InvalidStatus as exc:
                status = exc.response.status_code
                if status in (418, 429):
                    self.stats.stopped_reason = f"HTTP {status} on connect; stream stopped"
                    raise FeedError(self.stats.stopped_reason) from exc
                self._note(f"handshake rejected: HTTP {status}")
            except (OSError, TimeoutError, WebSocketException) as exc:
                self._note(f"connect failed: {type(exc).__name__}")
            else:
                self.stats.connects += 1
                try:
                    rotated = await self._consume(connection, opened, deadline, on_tick)
                finally:
                    self.book.clear()
                    await connection.close()
                if rotated:
                    # A planned rotation ends a healthy connection: forget earlier failures.
                    self.stats.rotations += 1
                    if self._monotonic() - opened >= STABLE_SECONDS:
                        failures = 0
                    continue
                if self._monotonic() >= deadline:
                    break
                self.stats.disconnects += 1
                if self._monotonic() - opened >= STABLE_SECONDS:
                    failures = 0
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                break
            base = BACKOFF_SECONDS[min(failures, len(BACKOFF_SECONDS) - 1)]
            failures += 1
            await self._sleep(min(remaining, base * (0.5 + 0.5 * self._jitter())))
        return self.stats

    async def _consume(
        self,
        connection: Connection,
        opened: float,
        deadline: float,
        on_tick: Callable[[BookTick], None] | None,
    ) -> bool:
        """Read until deadline (False), planned rotation (True) or any failure (False)."""
        while True:
            now = self._monotonic()
            if now >= deadline:
                return False
            if now - opened >= CONNECTION_LIFETIME_SECONDS:
                return True
            try:
                raw = await asyncio.wait_for(
                    connection.recv(), timeout=min(SILENCE_SECONDS, deadline - now)
                )
            except TimeoutError:
                if self._monotonic() < deadline:
                    self.stats.silences += 1
                    self._note("stream silent; reconnecting")
                return False
            except (OSError, WebSocketException) as exc:
                self._note(f"connection lost: {type(exc).__name__}")
                return False
            self.stats.messages += 1
            try:
                tick = parse_book_ticker(raw, self.book.symbols, self._wall_ms())
                if not self.book.update(tick):
                    self.stats.duplicates += 1
                    continue
            except DataError as exc:
                # Corrupt or out-of-order data invalidates the whole connection.
                self.stats.invalid += 1
                self._note(f"invalid message: {exc}")
                return False
            self.stats.ticks += 1
            if on_tick is not None:
                on_tick(tick)


def summarize(stream: PriceStream, ticks: dict[str, list[BookTick]]) -> dict[str, Any]:
    symbols: dict[str, Any] = {}
    for symbol in sorted(stream.book.symbols):
        series = ticks.get(symbol, [])
        gaps = [b.received_ms - a.received_ms for a, b in zip(series, series[1:], strict=False)]
        last = series[-1] if series else None
        symbols[symbol] = {
            "ticks": len(series),
            "max_gap_ms": max(gaps) if gaps else None,
            "last_bid": str(last.bid) if last else None,
            "last_ask": str(last.ask) if last else None,
            "last_spread_pct": (
                str((last.ask - last.bid) / ((last.ask + last.bid) / 2) * 100) if last else None
            ),
        }
    stats = stream.stats
    return {
        "mode": "read_only_price_stream",
        "source": STREAM_HOST,
        "orders_authorized": False,
        "symbols": symbols,
        "connects": stats.connects,
        "disconnects": stats.disconnects,
        "rotations": stats.rotations,
        "silences": stats.silences,
        "messages": stats.messages,
        "ticks": stats.ticks,
        "duplicates": stats.duplicates,
        "invalid": stats.invalid,
        "stopped_reason": stats.stopped_reason or None,
        "recent_errors": stats.errors,
    }


def run_stream(symbols: list[str], seconds: int) -> dict[str, Any]:
    if not 1 <= seconds <= 3600:
        raise DataError("stream duration must be 1-3600 seconds")
    stream = PriceStream(symbols)
    ticks: dict[str, list[BookTick]] = {}

    def record(tick: BookTick) -> None:
        series = ticks.setdefault(tick.symbol, [])
        if len(series) < 200_000:
            series.append(tick)

    asyncio.run(stream.run(seconds, record))
    return summarize(stream, ticks)
