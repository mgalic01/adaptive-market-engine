"""Direct tests for small gateways that only had indirect coverage.

Proposed by Bob's test-suite audit (PR #51, P1-P4 and P6): each function checks data
from outside the program, or maps configuration into the strategy, and had no test of
its own edge cases.
"""

import unittest
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.config import load_config
from crypto_grid_bot.market_data.collector import server_time
from crypto_grid_bot.market_data.parsing import DataError, integer, symbol_name
from crypto_grid_bot.market_data.stream import BookTick, PriceStream, run_stream, summarize
from crypto_grid_bot.strategy.regime import thresholds_from_config

ROOT = Path(__file__).resolve().parents[1]


class SymbolNameTests(unittest.TestCase):
    def test_accepts_uppercase_ascii_letters_and_digits(self):
        for value in ("BTCUSDT", "AB", "1000SATSUSDT", "A" * 24):
            with self.subTest(value=value):
                self.assertEqual(value, symbol_name(value))

    def test_rejects_anything_that_could_reach_a_path_or_query_unchecked(self):
        for value in ("", "A", "A" * 25, "btcusdt", "BTC USDT", "BTC/USDT", "../BTC", "BTCÜSDT"):
            with self.subTest(value=value), self.assertRaises(DataError):
                symbol_name(value)


class IntegerTests(unittest.TestCase):
    def test_accepts_bounded_non_negative_integers(self):
        for value in (0, 1, 10**16):
            with self.subTest(value=value):
                self.assertEqual(value, integer(value))

    def test_rejects_other_types_and_out_of_range_values(self):
        # bool is a subclass of int; the exact type check keeps True out.
        for value in (-1, 10**16 + 1, 1.0, "5", None, True, D("1")):
            with self.subTest(value=value), self.assertRaises(DataError):
                integer(value)


class ServerTimeTests(unittest.TestCase):
    def test_reads_the_exchange_clock(self):
        self.assertEqual(1704067200000, server_time({"serverTime": 1704067200000}))

    def test_a_missing_or_malformed_clock_fails_closed(self):
        # {"serverTime": True}: Bob's review of #54, the exact-type check at the gateway.
        payloads = ({}, None, [], "1704067200000", {"serverTime": "1704067200000"})
        for payload in (*payloads, {"serverTime": True}, {"serverTime": -1}):
            with self.subTest(payload=payload), self.assertRaises(DataError):
                server_time(payload)


class StreamSummaryTests(unittest.TestCase):
    def tick(self, symbol, update_id, received_ms, bid="99", ask="101"):
        return BookTick(symbol, update_id, D(bid), D("1"), D(ask), D("1"), received_ms)

    def test_summary_with_and_without_ticks(self):
        stream = PriceStream(["BTCUSDT", "ETHUSDT"])
        ticks = {"BTCUSDT": [self.tick("BTCUSDT", 1, 1000), self.tick("BTCUSDT", 2, 1750)]}
        summary = summarize(stream, ticks)
        self.assertFalse(summary["orders_authorized"])
        self.assertEqual("read_only_price_stream", summary["mode"])
        btc, eth = summary["symbols"]["BTCUSDT"], summary["symbols"]["ETHUSDT"]
        self.assertEqual(2, btc["ticks"])
        self.assertEqual(750, btc["max_gap_ms"])
        self.assertEqual(("99", "101"), (btc["last_bid"], btc["last_ask"]))
        self.assertEqual(D("2"), D(btc["last_spread_pct"]))
        self.assertEqual(
            {"ticks": 0, "max_gap_ms": None, "last_bid": None, "last_ask": None},
            {k: eth[k] for k in ("ticks", "max_gap_ms", "last_bid", "last_ask")},
        )
        self.assertIsNone(eth["last_spread_pct"])

    def test_stream_duration_is_bounded_before_any_connection(self):
        for seconds in (0, -1, 3601):
            with self.subTest(seconds=seconds), self.assertRaises(DataError):
                run_stream(["BTCUSDT"], seconds)


class RegimeThresholdTests(unittest.TestCase):
    def test_every_threshold_comes_from_its_config_field(self):
        config = load_config(ROOT / "config" / "default.toml")
        thresholds = thresholds_from_config(config)
        pairs = {
            "bull": "bull_threshold",
            "bear": "bear_threshold",
            "range_score_limit": "range_score_limit",
            "range_adx_limit": "range_adx_limit",
            "minimum_confidence": "minimum_confidence",
            "minimum_input_quality": "minimum_input_quality",
            "range_dispersion_limit": "range_dispersion_limit",
        }
        for field, source in pairs.items():
            with self.subTest(field=field):
                self.assertEqual(getattr(config, source), getattr(thresholds, field))


if __name__ == "__main__":
    unittest.main()
