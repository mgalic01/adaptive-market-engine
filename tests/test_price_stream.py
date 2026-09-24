"""Network-free tests for the read-only best-price stream."""

import asyncio
import json
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import MagicMock, patch

from websockets.exceptions import ConnectionClosedError, InvalidStatus

from crypto_grid_bot.market_data import stream as stream_module
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.market_data.stream import (
    MAX_CONNECTS,
    PriceBook,
    PriceStream,
    parse_book_ticker,
    stream_url,
)

SYMBOLS = frozenset({"ADAUSDC"})


def message(update_id=1, bid="0.2344", ask="0.2345", symbol="ADAUSDC", stream=None):
    return json.dumps(
        {
            "stream": stream or f"{symbol.lower()}@bookTicker",
            "data": {"u": update_id, "s": symbol, "b": bid, "B": "100", "a": ask, "A": "200"},
        }
    )


class Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def wall_ms(self):
        return int(self.now * 1000)

    async def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeConnection:
    """Yields scripted items; each consumes one simulated second. Then stays silent."""

    def __init__(self, clock, items):
        self.clock, self.items, self.closed = clock, list(items), False

    async def recv(self):
        if not self.items:
            await asyncio.sleep(3600)
        item = self.items.pop(0)
        self.clock.now += 1
        if isinstance(item, BaseException):
            raise item
        return item

    async def close(self):
        self.closed = True


def lost():
    return ConnectionClosedError(None, None)


def rejected(status):
    response = MagicMock()
    response.status_code = status
    return InvalidStatus(response)


class Connector:
    def __init__(self, clock, scripts):
        self.clock, self.scripts, self.urls, self.connections = clock, list(scripts), [], []

    async def __call__(self, url):
        self.urls.append(url)
        script = self.scripts.pop(0) if self.scripts else []
        if isinstance(script, BaseException):
            raise script
        connection = FakeConnection(self.clock, script)
        self.connections.append(connection)
        return connection


def make_stream(clock, connector, symbols=("ADAUSDC",)):
    return PriceStream(
        symbols,
        connector=connector,
        monotonic=clock.monotonic,
        wall_ms=clock.wall_ms,
        sleep=clock.sleep,
        jitter=lambda: 1.0,
    )


class ParsingTests(unittest.TestCase):
    def test_url_is_fixed_host_and_validated_symbols_only(self):
        self.assertEqual(
            "wss://data-stream.binance.vision/stream?streams=adausdc@bookTicker/btcusdc@bookTicker",
            stream_url(["ADAUSDC", "BTCUSDC"]),
        )
        for bad in ([], ["ADAUSDC", "ADAUSDC"], ["adausdc"], ["ADA/USDC"], ["X"] * 11):
            with self.subTest(symbols=bad), self.assertRaises(DataError):
                stream_url(bad)

    def test_valid_message_parses_to_exact_decimals(self):
        tick = parse_book_ticker(message(7), SYMBOLS, 1234)
        self.assertEqual(("ADAUSDC", 7, 1234), (tick.symbol, tick.update_id, tick.received_ms))
        self.assertEqual(
            (D("0.2344"), D("100"), D("0.2345"), D("200")),
            (tick.bid, tick.bid_size, tick.ask, tick.ask_size),
        )

    def test_malformed_unexpected_or_crossed_messages_are_rejected(self):
        bad = [
            message(bid="0.2345", ask="0.2345"),
            message(bid="0.2346", ask="0.2345"),
            message(symbol="BTCUSDC"),
            message(stream="adausdc@depth"),
            message(bid="-1"),
            message(bid="nan"),
            message(update_id=-1),
            message().encode(),
            "x" * 20000,
            "not json",
            json.dumps({"stream": "adausdc@bookTicker"}),
            json.dumps({"stream": "adausdc@bookTicker", "data": []}),
        ]
        for raw in bad:
            with self.subTest(raw=str(raw)[:60]), self.assertRaises(DataError):
                parse_book_ticker(raw, SYMBOLS, 0)


class PriceBookTests(unittest.TestCase):
    def test_regression_is_corrupt_duplicate_is_ignored_and_stale_is_refused(self):
        book = PriceBook(["ADAUSDC"], max_age_ms=5000)
        self.assertTrue(book.update(parse_book_ticker(message(5), SYMBOLS, 1000)))
        self.assertFalse(book.update(parse_book_ticker(message(5), SYMBOLS, 1100)))
        with self.assertRaises(DataError):
            book.update(parse_book_ticker(message(4), SYMBOLS, 1200))
        self.assertEqual(5, book.latest("ADAUSDC", 6000).update_id)
        with self.assertRaisesRegex(FeedError, "stale"):
            book.latest("ADAUSDC", 6001)
        with self.assertRaisesRegex(FeedError, "stale"):
            book.latest("ADAUSDC", 999)  # future-dated relative to the reader
        book.clear()
        with self.assertRaisesRegex(FeedError, "no live price"):
            book.latest("ADAUSDC", 1000)


class StreamTests(unittest.TestCase):
    def run_stream(self, stream, seconds, on_tick=None):
        return asyncio.run(stream.run(seconds, on_tick))

    def test_disconnect_clears_prices_and_reconnects_with_growing_backoff(self):
        clock = Clock()
        connector = Connector(
            clock, [[message(1), lost()], [lost()], [lost()], [message(2), message(3)]]
        )
        stream = make_stream(clock, connector)
        seen = []
        with patch.object(stream_module, "SILENCE_SECONDS", 0.01):
            stats = self.run_stream(stream, 40, lambda tick: seen.append(tick.update_id))
        self.assertEqual([1, 2, 3], seen)
        self.assertGreaterEqual(stats.disconnects, 3)
        self.assertEqual([1, 2, 4], clock.sleeps[:3])  # full-jitter upper bound
        self.assertTrue(all(connection.closed for connection in connector.connections))
        with self.assertRaises(FeedError):
            stream.book.latest("ADAUSDC", clock.wall_ms())  # cleared after the run

    def test_corrupt_message_drops_the_connection(self):
        clock = Clock()
        connector = Connector(clock, [[message(5), message(4)], [message(9)]])
        stream = make_stream(clock, connector)
        seen = []
        with patch.object(stream_module, "SILENCE_SECONDS", 0.01):
            stats = self.run_stream(stream, 5, lambda tick: seen.append(tick.update_id))
        self.assertEqual([5, 9], seen)
        self.assertEqual(1, stats.invalid)
        self.assertEqual(2, stats.connects)

    def test_silence_is_treated_as_a_dead_connection(self):
        clock = Clock()
        connector = Connector(clock, [[message(1)], [message(2)]])
        stream = make_stream(clock, connector)
        with patch.object(stream_module, "SILENCE_SECONDS", 0.01):
            stats = self.run_stream(stream, 10)
        self.assertGreaterEqual(stats.silences, 1)
        self.assertGreaterEqual(stats.connects, 2)

    def test_rate_limit_or_ban_on_connect_stops_without_retry(self):
        for status in (429, 418):
            clock = Clock()
            connector = Connector(clock, [rejected(status), [message(1)]])
            with self.subTest(status=status), self.assertRaisesRegex(FeedError, str(status)):
                self.run_stream(make_stream(clock, connector), 60)
            self.assertEqual(1, len(connector.urls))

    def test_connection_attempts_are_capped_per_window(self):
        clock = Clock()
        connector = Connector(clock, [OSError("refused")] * 100)
        # The backoff ladder alone stays under the cap; the cap guards fast reconnect paths.
        with patch.object(stream_module, "BACKOFF_SECONDS", (0.001,)):
            stats = self.run_stream(make_stream(clock, connector), 200)
        self.assertEqual(MAX_CONNECTS, len(connector.urls))
        self.assertEqual("connection attempt budget exhausted", stats.stopped_reason)

    def test_planned_rotation_before_binance_24h_limit(self):
        clock = Clock()
        connector = Connector(clock, [[message(i) for i in range(1, 6)], [message(6), message(7)]])
        stream = make_stream(clock, connector)
        with (
            patch.object(stream_module, "CONNECTION_LIFETIME_SECONDS", 3),
            patch.object(stream_module, "SILENCE_SECONDS", 0.01),
        ):
            stats = self.run_stream(stream, 5)
        self.assertEqual(1, stats.rotations)
        self.assertEqual([], clock.sleeps)  # rotation reconnects without backoff
        self.assertTrue(connector.connections[0].closed)

    def test_stable_planned_rotation_resets_backoff(self):
        clock = Clock()
        refused = OSError("refused")
        scripts = [refused, refused, refused, [message(i) for i in range(1, 6)], refused]
        connector = Connector(clock, scripts)
        stream = make_stream(clock, connector)
        with (
            patch.object(stream_module, "CONNECTION_LIFETIME_SECONDS", 3),
            patch.object(stream_module, "STABLE_SECONDS", 2),
            patch.object(stream_module, "SILENCE_SECONDS", 0.01),
        ):
            stats = self.run_stream(stream, 20)
        self.assertEqual(1, stats.rotations)
        self.assertEqual([1, 2, 4], clock.sleeps[:3])  # ladder from the early failures
        self.assertEqual(1, clock.sleeps[3])  # after the stable rotation: back to 1 s

    def test_no_order_or_account_endpoint_is_reachable(self):
        source = Path(stream_module.__file__).read_text(encoding="utf-8")
        for forbidden in ("api.binance.com", "listenKey", "signature", "X-MBX-APIKEY", "/order"):
            self.assertNotIn(forbidden, source)
