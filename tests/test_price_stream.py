"""Network-free tests for the read-only best-price stream."""

import asyncio
import json
import random
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
    SUMMARY_TICK_LIMIT,
    BookTick,
    PriceBook,
    PriceStream,
    StreamStopped,
    parse_book_ticker,
    run_stream,
    stream_url,
    summarize,
    summarize_tallies,
    tally_tick,
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

    def test_real_connector_refuses_every_redirect(self):
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        async def probe(location):
            connection = stream_module.NoRedirectConnect(stream_url(["ADAUSDC"]))
            redirect = InvalidStatus(Response(302, "Found", Headers({"Location": location})))
            return connection.process_redirect(redirect)

        for location in (
            "wss://example.invalid/stream",  # cross-host
            "wss://data-stream.binance.vision/other",  # same host still counts as an attempt
        ):
            with self.subTest(location=location):
                self.assertIsInstance(asyncio.run(probe(location)), InvalidStatus)

    def test_default_connector_uses_the_no_redirect_class(self):
        captured = {}

        class Recorder:
            def __init__(self, url, **kwargs):
                captured.update(url=url, **kwargs)

            def __await__(self):
                return iter(())

        with patch.object(stream_module, "NoRedirectConnect", Recorder):
            asyncio.run(stream_module.default_connector("wss://data-stream.binance.vision/x"))
        self.assertEqual("wss://data-stream.binance.vision/x", captured["url"])
        self.assertEqual(stream_module.MAX_MESSAGE, captured["max_size"])

    @staticmethod
    def _await_redirecting_handshake(location):
        """Run the real connect() loop with only the TCP/handshake faked."""
        from websockets.datastructures import Headers
        from websockets.http11 import Response

        opened, aborted = [], []

        class FakeTransport:
            def abort(self):
                aborted.append(1)

        class FakeConnection:
            transport = FakeTransport()

            async def handshake(self, *args):
                raise InvalidStatus(Response(302, "Found", Headers({"Location": location})))

        async def fake_open(self):
            opened.append(self.uri)
            return FakeConnection()

        with patch.object(stream_module.NoRedirectConnect, "open_tcp_connection", fake_open):
            try:
                asyncio.run(stream_module.default_connector(stream_url(["ADAUSDC"])))
            except InvalidStatus:
                return opened, aborted, True
        return opened, aborted, False

    def test_awaited_default_connector_opens_once_and_never_follows(self):
        for location in ("wss://example.invalid/stream", "wss://data-stream.binance.vision/x"):
            with self.subTest(location=location):
                opened, aborted, refused = self._await_redirecting_handshake(location)
                self.assertTrue(refused)
                self.assertEqual([stream_url(["ADAUSDC"])], opened)  # redirect never opened
                self.assertEqual(1, len(aborted))

    def test_redirect_status_is_a_failed_attempt_not_a_stop(self):
        clock = Clock()
        connector = Connector(clock, [rejected(302), [message(1), message(2)]])
        with patch.object(stream_module, "SILENCE_SECONDS", 0.01):
            stats = self.run_stream(make_stream(clock, connector), 5)
        self.assertEqual(2, len(connector.urls))
        self.assertIn("handshake rejected: HTTP 302", stats.errors)

    def test_no_order_or_account_endpoint_is_reachable(self):
        source = Path(stream_module.__file__).read_text(encoding="utf-8")
        for forbidden in ("api.binance.com", "listenKey", "signature", "X-MBX-APIKEY", "/order"):
            self.assertNotIn(forbidden, source)


def reference_summary(stream, ticks_in_order, limit):
    """The pre-tally code, kept verbatim as the oracle: buffer every tick, then reduce."""
    ticks = {}
    for tick in ticks_in_order:  # run_stream's former record()
        series = ticks.setdefault(tick.symbol, [])
        if len(series) < limit:
            series.append(tick)
    symbols = {}
    for symbol in sorted(stream.book.symbols):  # the former summarize()
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
        "source": stream_module.STREAM_HOST,
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


def random_ticks(seed, count):
    """Irregular arrivals: repeats, wall-clock steps back, a symbol the stream lacks."""
    rng = random.Random(seed)
    received, ticks = 1_700_000_000_000, []
    for update_id in range(count):
        symbol = rng.choice(["ADAUSDC", "BTCUSDC", "BTCUSDC", "ETHUSDC", "XRPUSDC"])
        received += rng.choice([0, 1, 7, 250, 4000, -30])
        bid = D(rng.randint(1, 10**6)) / D(10**4)
        ask = bid + D(rng.randint(1, 500)) / D(10**4)
        ticks.append(BookTick(symbol, update_id, bid, D("1"), ask, D("2"), received))
    # DOTUSDC's only gap is negative, so its max_gap_ms is below zero.
    for update_id, step in ((1, 0), (2, -30)):
        ticks.append(
            BookTick("DOTUSDC", update_id, D("5"), D("1"), D("5.01"), D("1"), received + step)
        )
    return ticks


class SummaryTallyTests(unittest.TestCase):
    def stream(self):
        stream = PriceStream(["ADAUSDC", "BTCUSDC", "DOTUSDC", "ETHUSDC", "SOLUSDC"])
        stream.stats.connects, stream.stats.ticks, stream.stats.errors = 3, 5000, ["x"]
        stream.stats.stopped_reason = "HTTP 429 on connect; stream stopped"
        return stream

    def test_running_tallies_match_the_former_buffered_summary(self):
        stream, ticks = self.stream(), random_ticks(7, 5000)
        btc = sum(tick.symbol == "BTCUSDC" for tick in ticks)
        self.assertGreater(btc, 1000)  # so the patched limits below are really reached
        for limit in (SUMMARY_TICK_LIMIT, 1000, 1):
            with (
                self.subTest(limit=limit),
                patch.object(stream_module, "SUMMARY_TICK_LIMIT", limit),
            ):
                tallies = {}
                for tick in ticks:
                    tally_tick(tallies, tick)
                expected = reference_summary(stream, ticks, limit)
                actual = summarize_tallies(stream, tallies)
                self.assertEqual(
                    json.dumps(expected, sort_keys=True), json.dumps(actual, sort_keys=True)
                )
                self.assertEqual(min(limit, btc), actual["symbols"]["BTCUSDC"]["ticks"])
                self.assertEqual(0, actual["symbols"]["SOLUSDC"]["ticks"])

    def test_summarize_of_whole_series_matches_the_former_code(self):
        stream, ticks = self.stream(), random_ticks(11, 3000)
        grouped = {}
        for tick in ticks:
            grouped.setdefault(tick.symbol, []).append(tick)
        self.assertEqual(
            json.dumps(reference_summary(stream, ticks, len(ticks)), sort_keys=True),
            json.dumps(summarize(stream, grouped), sort_keys=True),
        )


class RunStreamTests(unittest.TestCase):
    def run_with(self, clock, scripts, seconds):
        connector = Connector(clock, scripts)
        with (
            patch.object(
                stream_module, "PriceStream", lambda symbols: make_stream(clock, connector, symbols)
            ),
            patch.object(stream_module, "SILENCE_SECONDS", 0.01),
        ):
            return run_stream(["ADAUSDC"], seconds)

    def test_summary_reports_tallied_ticks(self):
        scripts = [[message(1), message(2, bid="0.2340"), message(3, bid="0.2300")]]
        summary = self.run_with(Clock(), scripts, 5)
        ada = summary["symbols"]["ADAUSDC"]
        self.assertEqual((3, 1000), (ada["ticks"], ada["max_gap_ms"]))
        self.assertEqual(("0.2300", "0.2345"), (ada["last_bid"], ada["last_ask"]))
        self.assertIsNone(summary["stopped_reason"])

    def test_ban_mid_run_keeps_the_collected_summary(self):
        scripts = [[message(1), message(2), lost()], rejected(429), [message(3)]]
        with self.assertRaises(StreamStopped) as caught:
            self.run_with(Clock(), scripts, 60)
        self.assertIsInstance(caught.exception, FeedError)
        summary = caught.exception.summary
        self.assertEqual("HTTP 429 on connect; stream stopped", summary["stopped_reason"])
        self.assertEqual(2, summary["symbols"]["ADAUSDC"]["ticks"])
        self.assertEqual((2, 1, 1), (summary["ticks"], summary["connects"], summary["disconnects"]))
