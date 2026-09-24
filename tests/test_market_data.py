"""Network-independent contract, persistence and no-execution regression tests."""

import json
import sqlite3
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import MagicMock, patch

from crypto_grid_bot.market_data.client import (
    HOST,
    MAX_BODY,
    FeedError,
    PublicClient,
    Response,
    https_proxy,
    public_get,
)
from crypto_grid_bot.market_data.collector import Collector, encode
from crypto_grid_bot.market_data.command import capture_once, run_capture
from crypto_grid_bot.market_data.parsing import (
    HOUR_MS,
    DataError,
    amount,
    diagnostics,
    parse_book,
    parse_candles,
    parse_instrument,
)
from crypto_grid_bot.market_data.store import ObservationStore

NOW = 500_000 * HOUR_MS + 10_000
SYMBOL = "ADAUSDC"


def metadata():
    return {
        "symbols": [
            {
                "symbol": SYMBOL,
                "status": "TRADING",
                "isSpotTradingAllowed": True,
                "orderTypes": ["LIMIT", "MARKET"],
                "baseAsset": "ADA",
                "quoteAsset": "USDC",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.0001"},
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.1",
                        "minQty": "0.1",
                        "maxQty": "1000000",
                    },
                    {"filterType": "NOTIONAL", "minNotional": "5", "maxNotional": "1000000"},
                ],
            }
        ]
    }


def history(now=NOW):
    boundary = now // HOUR_MS * HOUR_MS
    return [
        [
            boundary - (60 - i) * HOUR_MS,
            "1",
            "1.1",
            "0.9",
            "1",
            "100",
            boundary - (59 - i) * HOUR_MS - 1,
            "100",
            2,
            "50",
            "50",
            "0",
        ]
        for i in range(60)
    ]


def book():
    return {
        "lastUpdateId": 100,
        "bids": [["0.999", "100"], ["0.990", "200"]],
        "asks": [["1.001", "120"], ["1.010", "200"]],
    }


class FakeFeed:
    def __init__(self, now=NOW):
        self.now = now
        self.calls = []
        self.overrides = {}

    def __call__(self, path, params):
        self.calls.append((path, params))
        values = {
            "/api/v3/time": {"serverTime": self.now},
            "/api/v3/exchangeInfo": metadata(),
            "/api/v3/klines": history(self.now),
            "/api/v3/depth": book(),
        }
        value = self.overrides.get(path, values[path])
        return (
            value if isinstance(value, Response) else Response(200, {}, json.dumps(value).encode())
        )


def collector(feed=None):
    feed = feed or FakeFeed()
    return Collector(PublicClient(feed), wall_ms=lambda: feed.now, monotonic=lambda: 0)


class ParsingTests(unittest.TestCase):
    def test_constant_market_measurements_have_known_values(self):
        instrument = parse_instrument(metadata(), SYMBOL)
        candles = parse_candles(history(), NOW)
        result = diagnostics(candles, parse_book(book(), instrument))
        self.assertEqual(D(result["sma20"]), D(1))
        self.assertEqual(D(result["sma50"]), D(1))
        self.assertEqual(D(result["atr14_simple"]), D("0.2"))
        self.assertEqual(D(result["return_24h_pct"]), D(0))
        self.assertEqual(D(result["efficiency20"]), D(0))
        self.assertEqual(D(result["spread_pct"]), D("0.2"))
        self.assertEqual(D(result["quote_volume_24h"]), D(2400))
        self.assertEqual(D(result["visible_bid_depth_0_5pct"]), D("99.9"))
        self.assertEqual(D(result["visible_ask_depth_0_5pct"]), D("120.12"))

    def test_monotonic_closes_have_efficiency_one(self):
        rows = history()
        for i, row in enumerate(rows):
            row[1:5] = [str(i + 1)] * 4
        result = diagnostics(
            parse_candles(rows, NOW), parse_book(book(), parse_instrument(metadata(), SYMBOL))
        )
        self.assertEqual(D(result["efficiency20"]), D(1))
        self.assertEqual(D(result["return_24h_pct"]), (D(60) / D(36) - 1) * 100)

    def test_unsafe_decimal_values_fail_closed(self):
        for value in ("NaN", "Infinity", "-1", "0", "1e-1000000", "1e99", True, 0.5, None):
            with self.subTest(value=value), self.assertRaises(DataError):
                amount(value)

    def test_unclosed_stale_missing_disordered_and_bad_ohlc_history_rejected(self):
        bad = []
        bad.append(history()[1:40])
        bad.append(history()[:-1])
        rows = history()
        rows[30] = rows[29]
        bad.append(rows)
        rows = history()
        rows[1], rows[2] = rows[2], rows[1]
        bad.append(rows)
        rows = history()
        rows[-1][6] = NOW
        bad.append(rows)
        rows = history()
        rows[0][2] = "0.5"
        bad.append(rows)
        rows = history()
        rows[0][5] = "NaN"
        bad.append(rows)
        rows = history()
        rows[0][0] = True
        bad.append(rows)
        rows = history()
        rows[0][9] = "200"
        bad.append(rows)
        for rows in bad:
            with self.subTest(rows=rows[-1]), self.assertRaises(DataError):
                parse_candles(rows, NOW)

    def test_symbol_status_permissions_and_filters_are_required(self):
        for key, value in (
            ("symbol", "BTCUSDC"),
            ("status", "BREAK"),
            ("isSpotTradingAllowed", False),
            ("orderTypes", ["MARKET"]),
            ("orderTypes", "LIMIT"),
            ("baseAsset", "BTC"),
            ("filters", []),
        ):
            payload = metadata()
            payload["symbols"][0][key] = value
            with self.subTest(key=key), self.assertRaises(DataError):
                parse_instrument(payload, SYMBOL)
        payload = metadata()
        payload["symbols"][0]["filters"].append({"filterType": "MIN_NOTIONAL", "minNotional": "10"})
        self.assertEqual(parse_instrument(payload, SYMBOL).min_notional, D(10))

    def test_bad_books_rejected(self):
        invalid = []
        for levels in (
            [],
            [["1.001", "1"]],
            [["NaN", "1"]],
            [["0.999", "0"]],
            [["0.999", "1"], ["0.999", "2"]],
            [["0.998", "1"], ["0.999", "1"]],
            [["0.99901", "1"]],
        ):
            payload = book()
            payload["bids"] = levels
            invalid.append(payload)
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(DataError):
                parse_book(payload, parse_instrument(metadata(), SYMBOL))


class ClientTests(unittest.TestCase):
    def setUp(self):
        # Transport tests must not depend on the developer's or CI's proxy settings.
        env = patch.dict("os.environ", {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_transport_is_fixed_host_get_only_and_rejects_signed_parameters(self):
        with patch("crypto_grid_bot.market_data.client.http.client.HTTPSConnection") as factory:
            response = factory.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b"{}"
            response.getheaders.return_value = []
            public_get("/api/v3/time", {})
            factory.assert_called_once_with(HOST, timeout=10)
            factory.return_value.request.assert_called_once_with(
                "GET", "/api/v3/time", headers={"Accept": "application/json"}
            )
            factory.return_value.close.assert_called_once()
        transport = MagicMock()
        client = PublicClient(transport)
        for path, params in (
            ("/api/v3/order", {}),
            ("/api/v3/account", {}),
            ("https://elsewhere/api/v3/time", {}),
            ("/api/v3/time", {"signature": "secret"}),
        ):
            with self.assertRaises(DataError):
                client.get(path, params)
        transport.assert_not_called()

    def test_http_errors_redirects_api_errors_and_invalid_json_do_not_fallback(self):
        for response in (
            Response(301, {}, b""),
            Response(451, {}, b""),
            Response(503, {}, b""),
            Response(200, {}, b'{"code":-1121}'),
            Response(200, {}, b"not json"),
            Response(200, {}, b"x" * (MAX_BODY + 1)),
        ):
            transport = MagicMock(return_value=response)
            with self.subTest(status=response.status), self.assertRaises((FeedError, DataError)):
                PublicClient(transport).get("/api/v3/time", {})
            self.assertEqual(transport.call_count, 1)

    def test_rate_limit_blocks_further_requests_without_sleep_or_retry(self):
        for status, minimum in ((429, 60), (418, 172800)):
            transport = MagicMock(return_value=Response(status, {"retry-after": "120"}, b""))
            client = PublicClient(transport, monotonic=lambda: 1)
            with self.assertRaises(FeedError) as caught:
                client.get("/api/v3/time", {})
            self.assertGreaterEqual(caught.exception.retry_after, minimum)
            with self.assertRaises(FeedError):
                client.get("/api/v3/time", {})
            self.assertEqual(transport.call_count, 1)

    def test_https_proxy_tunnels_to_the_fixed_host_only(self):
        with (
            patch.dict("os.environ", {"HTTPS_PROXY": "http://127.0.0.1:3128"}),
            patch("crypto_grid_bot.market_data.client.http.client.HTTPSConnection") as factory,
        ):
            response = factory.return_value.getresponse.return_value
            response.status = 200
            response.read.return_value = b"{}"
            response.getheaders.return_value = []
            public_get("/api/v3/time", {})
            factory.assert_called_once_with("127.0.0.1", 3128, timeout=10)
            factory.return_value.set_tunnel.assert_called_once_with(HOST, 443)
            factory.return_value.request.assert_called_once_with(
                "GET", "/api/v3/time", headers={"Accept": "application/json"}
            )

    def test_https_proxy_honours_no_proxy_and_rejects_unsafe_forms(self):
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy:8080", "NO_PROXY": HOST}):
            self.assertIsNone(https_proxy())
        with patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy:8080"}):
            self.assertEqual(("proxy", 8080), https_proxy())
        for raw in ("socks5://proxy:1080", "http://user:secret@proxy:8080", "http://proxy:99999"):
            with (
                self.subTest(proxy=raw),
                patch.dict("os.environ", {"HTTPS_PROXY": raw}),
                self.assertRaises(FeedError),
            ):
                https_proxy()

    def test_socket_failure_closes_connection(self):
        with patch("crypto_grid_bot.market_data.client.http.client.HTTPSConnection") as factory:
            factory.return_value.request.side_effect = TimeoutError()
            with self.assertRaises(FeedError):
                public_get("/api/v3/time", {})
            factory.return_value.close.assert_called_once()


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "market.db"
        self.store = ObservationStore(self.path)
        self.addCleanup(lambda: self.store.close())

    def count(self, table):
        # Test-owned table identifiers, never a production query path.
        return self.store.connection.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_capture_uses_closed_candles_and_never_authorizes_orders(self):
        feed = FakeFeed()
        result = capture_once(collector(feed), self.store, SYMBOL)
        self.assertFalse(result["orders_authorized"])
        self.assertEqual(result["decision"], "observe_only")
        self.assertEqual(len(feed.calls), 5)
        self.assertEqual(feed.calls[2][1]["endTime"], str(NOW // HOUR_MS * HOUR_MS - 1))
        self.assertEqual(self.count("candles"), 60)
        body = self.store.connection.execute("SELECT body FROM captures").fetchone()[0]
        self.assertIn('"raw_sha256"', body)
        self.assertIn("local_request_window_not_exchange_event_time", body)

    def test_restart_exact_replay_and_repeated_book_do_not_duplicate_liquidity(self):
        observation = collector().capture(SYMBOL)
        self.assertTrue(self.store.save(observation))
        self.store.close()
        self.store = ObservationStore(self.path)
        self.assertFalse(self.store.save(json.loads(encode(observation))))
        later = collector(FakeFeed(NOW + 60_000)).capture(SYMBOL)
        self.assertTrue(self.store.save(later))
        self.assertEqual(self.count("captures"), 2)
        self.assertEqual(self.count("books"), 1)
        self.assertEqual(self.count("candles"), 60)

    def test_changed_capture_id_payload_rejected(self):
        observation = collector().capture(SYMBOL)
        self.store.save(observation)
        observation["received_ms"] += 1
        with self.assertRaisesRegex(DataError, "reused"):
            self.store.save(observation)
        self.assertEqual(self.count("captures"), 1)

    def test_candle_revision_rolls_back_whole_snapshot_and_records_failure(self):
        capture_once(collector(), self.store, SYMBOL)
        feed = FakeFeed(NOW + HOUR_MS)
        rows = history(feed.now)
        rows[-2][4] = "1.05"
        feed.overrides["/api/v3/klines"] = rows
        with self.assertRaisesRegex(DataError, "closed candle changed"):
            capture_once(collector(feed), self.store, SYMBOL)
        self.assertEqual(self.count("captures"), 1)
        self.assertEqual(self.count("candles"), 60)
        self.assertEqual(self.count("failures"), 1)

    def test_revised_or_regressing_books_rollback_including_new_candle(self):
        self.store.save(collector().capture(SYMBOL))
        for update, quantity in ((99, "100"), (100, "200")):
            feed = FakeFeed(NOW + HOUR_MS)
            payload = book()
            payload["lastUpdateId"] = update
            payload["bids"][0][1] = quantity
            feed.overrides["/api/v3/depth"] = payload
            with self.assertRaises(DataError):
                capture_once(collector(feed), self.store, SYMBOL)
            self.assertEqual(self.count("captures"), 1)
            self.assertEqual(self.count("candles"), 60)

    def test_stale_server_clock_and_slow_capture_are_rejected(self):
        for wall, monotonic in (
            (lambda: NOW + 6000, lambda: 0),
            (lambda: NOW, iter([0, 11]).__next__),
        ):
            with self.assertRaises(DataError):
                capture_once(
                    Collector(PublicClient(FakeFeed()), wall_ms=wall, monotonic=monotonic),
                    self.store,
                    SYMBOL,
                )
        self.assertEqual(self.count("captures"), 0)
        self.assertEqual(self.count("failures"), 2)

    def test_out_of_order_capture_rejected(self):
        self.store.save(collector().capture(SYMBOL))
        with self.assertRaisesRegex(DataError, "clock did not advance"):
            self.store.save(collector(FakeFeed(NOW - 1)).capture(SYMBOL))

    def test_ban_is_persisted_and_prevents_requests_after_restart(self):
        feed = FakeFeed()
        feed.overrides["/api/v3/time"] = Response(429, {"retry-after": "120"}, b"")
        with self.assertRaises(FeedError):
            capture_once(collector(feed), self.store, SYMBOL)
        self.store.close()
        self.store = ObservationStore(self.path)
        fresh = FakeFeed(NOW + 60_000)
        with self.assertRaisesRegex(DataError, "cooldown active"):
            capture_once(collector(fresh), self.store, SYMBOL)
        self.assertEqual(fresh.calls, [])
        self.assertEqual(self.count("captures"), 0)

    def test_hour_boundary_does_not_include_a_later_candle(self):
        feed = FakeFeed(NOW // HOUR_MS * HOUR_MS + HOUR_MS - 500)
        clock_calls = 0

        def advancing_clock(path, params):
            nonlocal clock_calls
            if path == "/api/v3/time":
                clock_calls += 1
                if clock_calls == 2:
                    feed.now += 1000
            return feed(path, params)

        ticks = iter([0, 1])
        item = Collector(
            PublicClient(advancing_clock), wall_ms=lambda: feed.now, monotonic=ticks.__next__
        ).capture(SYMBOL)
        self.assertEqual(item["diagnostics"]["latest_close_ms"], NOW // HOUR_MS * HOUR_MS - 1)
        self.assertEqual(
            item["server_finished_ms"] // HOUR_MS, item["server_started_ms"] // HOUR_MS + 1
        )

    def test_large_valid_prices_and_small_steps_do_not_overflow_precision(self):
        payload = metadata()
        payload["symbols"][0]["filters"][0]["tickSize"] = "0.000000000000000001"
        payload["symbols"][0]["filters"][1]["stepSize"] = "0.000000000000000001"
        levels = {
            "lastUpdateId": 1,
            "bids": [["999999999999999999", "1"]],
            "asks": [["1000000000000000000", "1"]],
        }
        parsed = parse_book(levels, parse_instrument(payload, SYMBOL))
        self.assertEqual(parsed.asks[0][0], D("1e18"))

    def test_existing_paper_database_is_not_modified(self):
        path = Path(self.temp.name) / "paper.db"
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE account (body TEXT)")
        before = path.read_bytes()
        with self.assertRaisesRegex(DataError, "separate"):
            ObservationStore(path)
        self.assertEqual(path.read_bytes(), before)

    def test_failure_on_final_insert_rolls_back_all_observation_rows(self):
        self.store.connection.execute("""CREATE TRIGGER fail_capture BEFORE INSERT ON captures
            BEGIN SELECT RAISE(ABORT, 'injected write failure'); END;""")
        with self.assertRaises(sqlite3.Error):
            self.store.save(collector().capture(SYMBOL))
        for table in ("captures", "candles", "books"):
            self.assertEqual(self.count(table), 0)

    def test_cli_run_is_bounded_and_stops_on_error(self):
        for samples, interval in ((0, 60), (121, 60), (1, 0)):
            with self.assertRaises(DataError):
                run_capture(self.path, SYMBOL, samples, interval)
        with (
            patch("crypto_grid_bot.market_data.command.Collector", return_value=collector()),
            patch("builtins.print") as output,
        ):
            self.assertEqual(run_capture(self.path, SYMBOL, 1, 60), 0)
        self.assertFalse(json.loads(output.call_args.args[0])["orders_authorized"])


if __name__ == "__main__":
    unittest.main()
