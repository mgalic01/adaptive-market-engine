"""Chronology, adapter and accounting tests for the historical replay (synthetic data)."""

import math
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import (
    RunConfig,
    bar_quotes,
    candidate_for,
    check_accounting,
    replay,
    signals_for,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import MarketRules
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator

ROOT = Path(__file__).resolve().parents[1]
START_MS = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
WARMUP = 800  # hours; the feature engine needs 742


def candle(open_ms, o, h, low, c, volume="1000000", taker="500000"):
    o, h, low, c = (D(str(round(x, 6))) for x in (o, h, low, c))
    return Kline(open_ms, o, h, low, c, D(volume), D(volume) * c, D(taker))


def hourly(count, start_ms=START_MS, amplitude=0.08):
    candles = []
    previous = 1.0
    for i in range(count):
        close = 1.0 + amplitude * math.sin(2 * math.pi * i / 24)
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        candles.append(candle(start_ms + i * HOUR_MS, previous, high, low, close))
        previous = close
    return candles


def engine_for(candles, **overrides):
    series = SeriesFeatures("TESTUSDT", candles)
    basket = [SeriesFeatures(f"B{i}USDT", candles, full=False) for i in range(5)]
    options = {
        "range_atr_multiple": 2.0,
        "levels": 8,
        "minimum_cost_multiple": 3.0,
        "round_trip_cost": 0.0035,
        "order_notional": 10.0,
        **overrides,
    }
    return FeatureEngine(series, series, basket, **options)


RULES = MarketRules(
    symbol="TESTUSDT",
    tick_size=D("0.0001"),
    quantity_step=D("0.1"),
    minimum_notional=D("5"),
)


class FeatureChronologyTests(unittest.TestCase):
    def test_warm_up_returns_none_then_inputs(self):
        candles = hourly(WARMUP)
        engine = engine_for(candles)
        self.assertIsNone(engine.at(START_MS + 100 * HOUR_MS))
        inputs = engine.at(START_MS + WARMUP * HOUR_MS)
        self.assertIsNotNone(inputs)
        self.assertEqual(START_MS + (WARMUP - 1) * HOUR_MS, inputs.hour_open_ms)

    def test_unfinished_and_future_candles_cannot_change_a_decision(self):
        candles = hourly(WARMUP + 10)
        decision_ms = START_MS + WARMUP * HOUR_MS + 30 * 60_000  # mid-hour
        baseline = engine_for(candles).at(decision_ms)
        # Candles opening at or after the decision hour are unfinished or in the future.
        unfinished_from = decision_ms - 1800_000  # open time of the decision hour
        changed = [
            replace(k, close=k.close * 3, high=k.high * 3) if k.open_ms >= unfinished_from else k
            for k in candles
        ]
        self.assertEqual(baseline, engine_for(changed).at(decision_ms))
        # The last completed candle is used: changing it changes the decision inputs.
        last = decision_ms - 1800_000 - HOUR_MS
        edited = [replace(k, close=k.close * D("0.9")) if k.open_ms == last else k for k in candles]
        self.assertNotEqual(baseline, engine_for(edited).at(decision_ms))

    def test_stale_hourly_data_zeroes_quality(self):
        candles = hourly(WARMUP)
        engine = engine_for(candles)
        fresh = engine.at(START_MS + WARMUP * HOUR_MS)
        stale = engine.at(START_MS + (WARMUP + 3) * HOUR_MS)
        self.assertEqual(1.0, fresh.market_quality)
        self.assertEqual(0.0, stale.market_quality)
        self.assertEqual(0.0, stale.pair_quality)


class AdapterTests(unittest.TestCase):
    def test_path_order_prices_sizes_and_timestamps(self):
        bar = candle(START_MS, 1.0, 1.02, 0.97, 1.01, volume="1000", taker="300")
        for mode, order in (("high_first", ("high", "low")), ("low_first", ("low", "high"))):
            quotes = bar_quotes(bar, "TESTUSDT", mode, D("0.0005"), D("0.0001"))
            self.assertEqual(4, len(quotes))
            times = [q.observed_at for q in quotes]
            self.assertEqual(sorted(times), times)
            self.assertEqual(len(set(times)), 4)
            by_kind = dict(zip(("open", *order, "close"), quotes, strict=True))
            self.assertEqual(D("1.02"), by_kind["high"].ask)  # trade lifted the ask
            self.assertEqual(D("0.97"), by_kind["low"].bid)  # trade hit the bid
            for quote in quotes:
                self.assertLess(quote.bid, quote.ask)
                self.assertEqual(D(0), quote.bid % D("0.0001"))
            self.assertEqual(D("300"), sum(q.bid_size for q in quotes))  # taker buys
            self.assertEqual(D("700"), sum(q.ask_size for q in quotes))  # taker sells


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")

    def test_child_order_cannot_fill_inside_the_bar_that_created_it(self):
        simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100))
        account = simulator.store.read()
        simulator.close()
        engine = engine_for(hourly(WARMUP))
        inputs = engine.at(START_MS + WARMUP * HOUR_MS)

        def frames(bar):
            when = datetime.fromtimestamp(bar.open_ms / 1000, UTC)
            signals = signals_for(inputs, when, gated=False)
            metrics = candidate_for(inputs, "TESTUSDT", 0.05, gated=False)
            epoch = f"TESTUSDT/{bar.open_ms}"
            quotes = bar_quotes(bar, "TESTUSDT", "low_first", D("0.0005"), RULES.tick_size)
            return [
                Frame(q, signals, metrics, inputs.fair_value, inputs.atr, True, epoch)
                for q in quotes
            ]

        t = START_MS + WARMUP * HOUR_MS
        fair = float(inputs.fair_value)
        for f in frames(candle(t, fair, fair, fair, fair)):
            simulator.step(account, f)
        buys = sorted(o.price for o in account.orders.values() if o.side == "buy")
        self.assertTrue(buys, "grid should open in the ungated baseline")
        top, target = buys[-1], max(o.target for o in account.orders.values())
        # One bar dips through the top buy and then spikes far above every target.
        spike = candle(t + 60_000, fair, float(target) * 1.05, float(top) * 0.99, fair)
        filled_sides = [
            fill["side"] for f in frames(spike) for fill in simulator.step(account, f)["fills"]
        ]
        self.assertIn("buy", filled_sides)
        self.assertNotIn("sell", filled_sides)  # the child sell waits for a later bar
        later = candle(t + 120_000, fair, float(target) * 1.05, fair, fair)
        later_sides = [
            fill["side"] for f in frames(later) for fill in simulator.step(account, f)["fills"]
        ]
        self.assertIn("sell", later_sides)

    def test_replay_accounting_identities_hold_for_both_paths(self):
        candles = hourly(WARMUP)
        engine = engine_for(candles)
        t = START_MS + WARMUP * HOUR_MS
        minutes = []
        for i in range(600):  # ten hours of strong one-minute oscillation
            mid = float(engine.at(t).fair_value) * (1 + 0.03 * math.sin(2 * math.pi * i / 90))
            minutes.append(candle(t + i * 60_000, mid, mid * 1.003, mid * 0.997, mid))
        for mode in ("high_first", "low_first"):
            run = RunConfig("TESTUSDT", mode, False, RULES, D(100), D("0.0005"))
            metrics, account = replay(self.config, run, minutes, engine)
            with self.subTest(mode=mode):
                self.assertGreater(metrics.buys, 0)
                self.assertGreater(metrics.sells, 0)
                self.assertEqual([], check_accounting(run, metrics, account))
                self.assertEqual(0, metrics.transient_pauses)
                self.assertEqual(600, metrics.bars)
                self.assertGreater(metrics.hold_final, 0)

    def test_gated_replay_marks_news_absent_and_can_stay_in_cash(self):
        engine = engine_for(hourly(WARMUP))
        t = START_MS + WARMUP * HOUR_MS
        minutes = [candle(t + i * 60_000, 1.0, 1.001, 0.999, 1.0) for i in range(30)]
        run = RunConfig("TESTUSDT", "high_first", True, RULES, D(100), D("0.0005"))
        metrics, account = replay(self.config, run, minutes, engine)
        self.assertEqual([], check_accounting(run, metrics, account))
        self.assertEqual(30, sum(metrics.regimes.values()))


class CompatibilityTests(unittest.TestCase):
    def test_unused_epoch_is_not_persisted(self):
        from crypto_grid_bot.simulation.models import Account, LimitOrder

        account = Account.start(D(100))
        account.orders["a"] = LimitOrder("a", "buy", D("1"), D("6"), D("6"))
        account.orders["b"] = LimitOrder("b", "buy", D("1"), D("6"), D("6"), epoch="bar")
        saved = account.to_dict()["orders"]
        self.assertNotIn("epoch", saved["a"])
        self.assertEqual("bar", saved["b"]["epoch"])
        self.assertEqual(account.orders, Account.from_dict(account.to_dict()).orders)

    def test_coverage_counts_whole_hours_mid_hour(self):
        engine = engine_for(hourly(WARMUP))
        self.assertEqual(1.0, engine.at(START_MS + WARMUP * HOUR_MS + 30 * 60_000).pair_quality)


class ReasonKeyTests(unittest.TestCase):
    def test_scorer_context_is_dropped_and_numbers_masked(self):
        from crypto_grid_bot.backtest.replay import reason_key

        reason = (
            "base quality 0.675; regime fit 0.35; news multiplier 1.00; "
            "opportunity score 0.236 is below minimum"
        )
        self.assertEqual("pause: opportunity score # is below minimum", reason_key("pause", reason))
        self.assertEqual(
            "cash: grid spacing #% is below required #%",
            reason_key("cash", "grid spacing 0.7156% is below required 1.0806%"),
        )
