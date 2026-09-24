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
    Metrics,
    RequestCountingOrders,
    RunConfig,
    _record_fills,
    bar_quotes,
    candidate_for,
    check_accounting,
    cross_check_daily,
    order_requests,
    replay,
    signals_for,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals
from crypto_grid_bot.simulation.execution import match, place
from crypto_grid_bot.simulation.models import Account, LimitOrder, MarketRules, Quote, timestamp
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
            metrics = candidate_for(inputs, "TESTUSDT", 0.05, 1e9, gated=False)
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

    def test_rejected_frames_do_not_inflate_the_range_exit_count(self):
        from unittest.mock import patch

        candles = hourly(WARMUP)
        engine = engine_for(candles)
        t = START_MS + WARMUP * HOUR_MS
        fair = float(engine.at(t).fair_value)
        minutes = [
            candle(t + i * 60_000, fair, fair * 1.003, fair * 0.997, fair) for i in range(60)
        ]
        # Then eight hours far below the grid: one range exit, with every other frame
        # rejected as a transient (its report carries no range_exit flag).
        low = fair * 0.8
        minutes += [
            candle(t + i * 60_000, low, low * 1.001, low * 0.999, low) for i in range(60, 540)
        ]
        real_step, calls = PaperSimulator.step, []

        def flaky(simulator, account, frame):
            calls.append(1)
            if len(calls) > 600 and len(calls) % 2:
                return {"fills": [], "opened": [], "decision": "pause", "reason": "rejected"}
            return real_step(simulator, account, frame)

        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        with patch.object(PaperSimulator, "step", flaky):
            metrics, account = replay(self.config, run, minutes, engine)
        self.assertTrue(account.range_exit)
        self.assertEqual(1, metrics.range_exits)

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


class CrossCheckTests(unittest.TestCase):
    def test_hour_with_no_minute_data_is_reported(self):
        from crypto_grid_bot.backtest.klines import aggregate
        from crypto_grid_bot.backtest.replay import cross_check_hourly

        minutes = [candle(START_MS + i * 60_000, 1.0, 1.0, 1.0, 1.0) for i in range(60)]
        official = list(aggregate(minutes))
        official.append(candle(START_MS + HOUR_MS, 1.0, 1.0, 1.0, 1.0))  # no 1m data
        result = cross_check_hourly(minutes, official, (START_MS, START_MS + 2 * HOUR_MS))
        self.assertEqual(1, result["hours_compared"])
        self.assertEqual(0, result["hours_mismatched"])
        self.assertEqual(1, result["hours_absent_from_minutes"])
        # Official hours outside the minute window (warm-up) are not counted.
        outside = cross_check_hourly(minutes, official, (START_MS, START_MS + HOUR_MS))
        self.assertEqual(0, outside["hours_absent_from_minutes"])


class DepthBoundTests(unittest.TestCase):
    """R2: depth is sized against the largest order the engine could place."""

    def test_one_pair_case_is_ineligible_at_the_boundary(self):
        from crypto_grid_bot.backtest.replay import depth_multiple
        from crypto_grid_bot.domain import MarketRegime, RegimeAssessment
        from crypto_grid_bot.simulation.models import Account
        from crypto_grid_bot.strategy.opportunity import OpportunityScorer

        account = Account.start(D(100))
        # Codex's reproduction: one pair takes 80% of cash = 80 per order.
        depth = depth_multiple(1200.0, account, RULES, D(1))
        self.assertAlmostEqual(15.0, depth)
        scorer = OpportunityScorer(
            minimum_score=0.1,
            maximum_news_risk=0.3,
            maximum_spread_pct=0.15,
            minimum_depth_multiple=50.0,
        )
        regime = RegimeAssessment(MarketRegime.RANGE, 0.0, 1.0, ())
        metrics = CandidateMetrics("TESTUSDT", 1, 1, 1, 1, 1, 0, 0.05, depth)
        self.assertFalse(scorer.score(metrics, regime).eligible)
        enough = CandidateMetrics("TESTUSDT", 1, 1, 1, 1, 1, 0, 0.05, 50.0)
        self.assertTrue(scorer.score(enough, regime).eligible)

    def test_bound_tracks_capital_and_excludes_pending_reserve(self):
        from crypto_grid_bot.backtest.replay import depth_multiple
        from crypto_grid_bot.simulation.models import Account

        grown = Account.start(D(100))
        grown.cash = D(200)
        self.assertAlmostEqual(1200 / 160, depth_multiple(1200.0, grown, RULES, D(1)))
        grown.pending = D(50)  # protected reserve never funds an order
        self.assertAlmostEqual(1200 / 120, depth_multiple(1200.0, grown, RULES, D(1)))
        empty = Account.start(D(100))
        empty.cash = D(0)
        self.assertAlmostEqual(1200 / 5, depth_multiple(1200.0, empty, RULES, D(1)))  # min notional


class SellSettleReopenTests(unittest.TestCase):
    """R2 follow-up: a step can sell, settle and reopen with the proceeds."""

    def setUp(self):
        from crypto_grid_bot.simulation.models import LimitOrder

        self.config = load_config(ROOT / "config/default.toml")
        simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100))
        self.simulator = simulator
        self.account = simulator.store.read()
        simulator.close()
        # Codex's reproduction: 20 cash, 80 inventory under one older resting sell.
        self.account.cash, self.account.inventory = D(20), D(80)
        self.account.orders["old/sell"] = LimitOrder(
            "old/sell", "sell", D("1.001"), D(80), D(80), epoch="old"
        )
        self.account.validate(RULES)
        when = datetime(2024, 1, 2, tzinfo=UTC)
        self.quote = Quote(
            "q",
            "TESTUSDT",
            when.isoformat(),
            when.isoformat(),
            D("1.002"),
            D("1.0025"),
            D(1000),
            D(1000),
        )
        self.signals = MarketSignals(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, observed_at=when)

    def step(self, minute_volume):
        from crypto_grid_bot.backtest.replay import depth_multiple

        depth = depth_multiple(minute_volume, self.account, RULES, self.quote.bid)
        candidate = CandidateMetrics("TESTUSDT", 1, 1, 1, 1, 1, 0, 0.05, depth)
        frame = Frame(self.quote, self.signals, candidate, D(1), D("0.05"), True, "new")
        return depth, self.simulator.step(self.account, frame)

    def test_codex_reproduction_is_now_ineligible(self):
        depth, report = self.step(900.0)
        self.assertLess(depth, 50)  # bound covers the 80 of sell proceeds (was 56.25)
        self.assertTrue(any(f["side"] == "sell" for f in report["fills"]))
        self.assertFalse(report["opened"])  # no grid reopened on thin liquidity

    def test_bound_never_overstates_depth_of_orders_actually_opened(self):
        depth, report = self.step(9000.0)
        self.assertTrue(report["opened"])
        largest = max(o.price * o.quantity for o in self.account.orders.values() if o.side == "buy")
        self.assertLessEqual(depth, 9000.0 / float(largest))

    def test_multi_quote_bar_with_protected_reserves_never_bypasses_liquidity(self):
        from crypto_grid_bot.backtest.replay import depth_multiple

        # Protected money: 5 pending and 10 already secured (journal must reconcile).
        bar = candle(START_MS, 1.0, 1.003, 0.999, 1.002, volume="4000", taker="2000")
        for volume in (900.0, 9000.0):  # thin, then ample liquidity
            with self.subTest(volume=volume):
                self.setUp()
                account = self.account
                account.cash, account.pending, account.secured = D(35), D(5), D(10)
                account.confirmed_transfers = {"earlier": D(10)}
                account.validate(RULES)
                sold = False
                for quote in bar_quotes(
                    bar, "TESTUSDT", "high_first", D("0.0005"), RULES.tick_size
                ):
                    depth = depth_multiple(volume, account, RULES, quote.bid)
                    when = timestamp(quote.observed_at)
                    signals = MarketSignals(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, observed_at=when)
                    metrics = CandidateMetrics("TESTUSDT", 1, 1, 1, 1, 1, 0, 0.05, depth)
                    frame = Frame(quote, signals, metrics, D(1), D("0.05"), True, "bar")
                    report = self.simulator.step(account, frame)
                    sold |= any(f["side"] == "sell" for f in report["fills"])
                    new_buys = [
                        o for o in account.orders.values() if o.side == "buy" and o.epoch == "bar"
                    ]
                    for order in new_buys:  # every order placed passed the liquidity test
                        self.assertGreaterEqual(volume / float(order.price * order.quantity), 50)
                self.assertTrue(sold)  # the exit still happens when entries are vetoed
                self.assertGreaterEqual(account.pending, D(5))  # reserve never spent
                self.assertEqual(D(10), account.secured)
                account.validate(RULES)

    def test_pending_reserve_is_excluded_from_the_bound(self):
        from crypto_grid_bot.backtest.replay import depth_multiple

        before = depth_multiple(900.0, self.account, RULES, self.quote.bid)
        self.account.pending = D(10)
        self.assertGreater(depth_multiple(900.0, self.account, RULES, self.quote.bid), before)


class DegenerateHistoryTests(unittest.TestCase):
    """R3: flat or zero-volume history vetoes entries instead of crashing."""

    def test_flat_prices_and_zero_volume_do_not_crash(self):
        flat = [candle(START_MS + i * HOUR_MS, 1, 1, 1, 1) for i in range(WARMUP)]
        quiet = [
            candle(START_MS + i * HOUR_MS, 1, 1.01, 0.99, 1, volume="0", taker="0")
            for i in range(WARMUP)
        ]
        for name, history in (("flat", flat), ("zero volume", quiet)):
            with self.subTest(history=name):
                inputs = engine_for(history).at(START_MS + WARMUP * HOUR_MS)
                self.assertTrue(inputs.degenerate)
                self.assertEqual(0.0, inputs.market_quality)

    def test_degenerate_bars_keep_marking_inventory_and_block_entries(self):
        config = load_config(ROOT / "config/default.toml")
        history = hourly(WARMUP)
        # The last 20 completed hours are perfectly flat: ATR over them is zero.
        last = history[-1].open_ms
        history = history[:-20] + [
            candle(last - k * HOUR_MS, 1, 1, 1, 1) for k in range(19, -1, -1)
        ]
        engine = engine_for(history)
        t = START_MS + WARMUP * HOUR_MS
        self.assertTrue(engine.at(t).degenerate)
        for gated in (True, False):
            run = RunConfig("TESTUSDT", "high_first", gated, RULES, D(100), D("0.0005"))
            minutes = [candle(t + i * 60_000, 1.0, 1.001, 0.999, 1.0) for i in range(30)]
            metrics, account = replay(config, run, minutes, engine)
            with self.subTest(gated=gated):
                self.assertEqual(30, metrics.bars)  # no bar skipped
                self.assertEqual(0, metrics.grids_opened)  # entries vetoed
                self.assertFalse(account.halt)
                self.assertEqual([], check_accounting(run, metrics, account))

    def test_already_invested_account_crosses_into_degenerate_history(self):
        config = load_config(ROOT / "config/default.toml")
        normal = hourly(WARMUP)
        flat_start = START_MS + WARMUP * HOUR_MS
        history = normal + [candle(flat_start + k * HOUR_MS, 1, 1, 1, 1) for k in range(16)]
        engine = engine_for(history)
        fair = float(engine.at(flat_start).fair_value)
        minutes = []
        for i in range(16 * 60):
            # Ten hours of swings open and fill grid buys, then price holds below the
            # grid while the hourly history goes flat.
            swing = fair * (1 + 0.03 * math.sin(2 * math.pi * i / 90))
            mid = swing if i < 600 else fair * 0.95
            minutes.append(candle(flat_start + i * 60_000, mid, mid * 1.003, mid * 0.997, mid))
        self.assertTrue(engine.at(minutes[-1].open_ms).degenerate)
        run = RunConfig("TESTUSDT", "low_first", False, RULES, D(100), D("0.0005"))
        metrics, account = replay(config, run, minutes, engine)
        self.assertEqual(len(minutes), metrics.bars)  # every bar still marked
        self.assertGreater(metrics.bars_with_inventory, 0)
        self.assertEqual([], check_accounting(run, metrics, account))


class OrderRequestCountTests(unittest.TestCase):
    """Placements plus cancellations, as counted against an exchange's daily budget."""

    def order(self, order_id, side="buy", quantity="1", target=None, reentry=None):
        q = D(quantity)
        return LimitOrder(order_id, side, D("1"), q, q, target, reentry)

    def test_book_operations_are_counted_at_the_operation(self):
        orders = RequestCountingOrders()
        for name in ("a", "b", "c"):
            orders[name] = self.order(name)
        orders["a"] = orders["a"]  # replacing an existing order is not a new placement
        self.assertEqual(3, orders.requests)
        orders["b"].remaining = D("0")
        del orders["b"]  # fully filled: no request
        del orders["c"]  # cancelled with quantity left
        self.assertEqual(4, orders.requests)
        orders["d"] = self.order("d")
        orders.clear()  # cancels a and d
        self.assertEqual(7, orders.requests)
        with self.assertRaises(NotImplementedError):
            orders.pop("x", None)

    def test_marketable_exits_count_one_placement_each(self):
        orders = RequestCountingOrders()
        fills = [{"order_id": "exit/q1"}, {"order_id": "b1"}]
        self.assertEqual(1, order_requests(orders, 0, fills))

    def test_reentry_placed_and_cancelled_in_one_step_is_counted(self):
        # Codex's PR #14 case: the last grid sell fills, match() places its reentry buy,
        # and the flat account then cancels that buy before the step returns.
        account = Account.start(D(100))
        orders = account.orders = RequestCountingOrders()
        account.inventory = D("10")
        place(account, self.order("s", "sell", "10", reentry=D("0.9")), RULES)
        since = orders.requests
        quote = Quote(
            "q",
            "TESTUSDT",
            "2024-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            D("1.01"),
            D("1.0101"),
            D("1000"),
            D("1000"),
        )
        fills = [vars(fill) for fill in match(account, quote, RULES)]
        self.assertEqual(["sell"], [fill["side"] for fill in fills])
        self.assertTrue(any(o.side == "buy" for o in account.orders.values()))
        PaperSimulator._cancel_buys(account)
        self.assertEqual({}, dict(account.orders))
        # One reentry placement and one cancellation; the filled sell costs nothing.
        self.assertEqual(2, order_requests(orders, since, fills))


class ProfitAttributionTests(unittest.TestCase):
    def fill(self, order_id, side, price, quantity, fee="0"):
        return {
            "order_id": order_id,
            "side": side,
            "price": price,
            "quantity": quantity,
            "fee": fee,
        }

    def test_grid_and_exit_sells_are_attributed_at_average_cost(self):
        metrics = Metrics()
        _record_fills(
            metrics,
            [self.fill("b1", "buy", "10", "2", "0.02"), self.fill("b2", "buy", "8", "2", "0.02")],
        )
        self.assertEqual(D("36.04"), metrics.cost_basis)  # average cost 9.01 incl. fees
        _record_fills(metrics, [self.fill("b1/sell", "sell", "11", "1", "0.011")])
        self.assertEqual(D("11") - D("0.011") - D("9.01"), metrics.grid_sell_pnl)
        _record_fills(metrics, [self.fill("exit/q9", "sell", "7", "3", "0.021")])
        self.assertEqual(D("21") - D("0.021") - D("27.03"), metrics.exit_pnl)
        self.assertEqual((1, D("0")), (metrics.exit_sells, metrics.cost_basis))


class MeasurementTests(unittest.TestCase):
    """Spec v1 prerequisites P1, P2, P6 and P7: measurement only, no decision changes."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.engine = engine_for(hourly(WARMUP))
        self.t = START_MS + WARMUP * HOUR_MS
        self.fair = float(self.engine.at(self.t).fair_value)

    def flat(self, start, stop, price):
        return [
            candle(self.t + i * 60_000, price, price * 1.001, price * 0.999, price)
            for i in range(start, stop)
        ]

    def run_replay(self, minutes):
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        metrics, account = replay(self.config, run, minutes, self.engine)
        self.assertEqual([], check_accounting(run, metrics, account))  # includes P6
        return metrics, account

    def test_range_exit_losses_are_labelled_and_reconcile(self):
        minutes = self.flat(0, 60, self.fair) + self.flat(60, 540, self.fair * 0.95)
        metrics, _ = self.run_replay(minutes)
        self.assertEqual({"range_exit"}, set(metrics.exit_pnl_by_reason))
        self.assertLess(metrics.exit_pnl_by_reason["range_exit"], 0)
        self.assertEqual(0, metrics.hard_drawdown_halts)

    def test_hard_drawdown_liquidation_is_labelled_and_fails_the_halt_veto(self):
        minutes = self.flat(0, 30, self.fair)
        price = self.fair
        for i in range(30, 200):
            price *= 0.997
            minutes.append(candle(self.t + i * 60_000, price, price * 1.001, price * 0.999, price))
        metrics, account = self.run_replay(minutes)
        self.assertTrue(account.halt.startswith("hard drawdown"))
        self.assertEqual({"liquidation"}, set(metrics.exit_pnl_by_reason))
        self.assertEqual(1, metrics.hard_drawdown_halts)  # one latched halt, not evaluations
        # C1(b) basis: active equity against the engine's risk high-water mark.
        self.assertGreaterEqual(metrics.active_max_drawdown, D("0.12"))

    def test_drain_exit_is_labelled(self):
        simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100))
        account = simulator.store.read()
        simulator.close()
        inputs = self.engine.at(self.t)
        account.inventory, account.cash = D("20"), D("80")
        account.pause, account.draining = "test pause", True
        bar = candle(self.t, self.fair, self.fair, self.fair, self.fair)
        when = datetime.fromtimestamp(bar.open_ms / 1000, UTC)
        signals = signals_for(inputs, when, gated=False)
        candidate = candidate_for(inputs, "TESTUSDT", 0.05, 1e9, gated=False)
        (quote, *_) = bar_quotes(bar, "TESTUSDT", "high_first", D("0.0005"), RULES.tick_size)
        frame = Frame(quote, signals, candidate, inputs.fair_value, inputs.atr, True, "e")
        report = simulator.step(account, frame)
        self.assertTrue(any(f["order_id"].startswith("exit/") for f in report["fills"]))
        self.assertEqual("drain", report["exit_reason"])

    def test_completed_cycles_count_fully_filled_grid_sells(self):
        minutes = []
        for i in range(600):
            mid = self.fair * (1 + 0.03 * math.sin(2 * math.pi * i / 90))
            minutes.append(candle(self.t + i * 60_000, mid, mid * 1.003, mid * 0.997, mid))
        metrics, _ = self.run_replay(minutes)
        self.assertGreater(metrics.completed_cycles, 0)
        self.assertLessEqual(metrics.completed_cycles, metrics.sells)
        self.assertEqual(metrics.completed_cycles, sum(metrics.cycles_by_week.values()))
        self.assertEqual({}, metrics.exit_pnl_by_reason)

    def test_buy_and_hold_is_marked_at_every_quote_not_only_the_close(self):
        # One bar dips 5% intrabar and closes unchanged: a close-only mark misses it.
        minutes = self.flat(0, 3, self.fair)
        minutes.append(
            candle(self.t + 3 * 60_000, self.fair, self.fair, self.fair * 0.95, self.fair)
        )
        minutes += self.flat(4, 6, self.fair)
        metrics, _ = self.run_replay(minutes)
        self.assertGreater(metrics.hold_max_drawdown, D("0.045"))

    def test_counting_book_records_completed_orders_separately_from_cancellations(self):
        orders = RequestCountingOrders()
        orders["a/sell"] = LimitOrder("a/sell", "sell", D("1"), D("1"), D("1"))
        orders["b"] = LimitOrder("b", "buy", D("1"), D("1"), D("1"))
        orders["a/sell"].remaining = D("0")
        del orders["a/sell"]
        del orders["b"]
        self.assertEqual(["a/sell"], orders.completed)
        self.assertEqual(3, orders.requests)  # two placements, one cancellation


class DailyCrossCheckTests(unittest.TestCase):
    """Spec v1 P3: complete, unique daily bars that agree with their 24 hours."""

    DAY = 86_400_000

    def hours(self, days):
        return hourly(24 * days)

    def daily_from(self, hours):
        from crypto_grid_bot.backtest.klines import aggregate

        return list(aggregate(hours, self.DAY))

    def check(self, daily, hours, days=3, warmup_days=3):
        window = (START_MS, START_MS + days * self.DAY)
        return cross_check_daily(daily, hours, window, window, START_MS + warmup_days * self.DAY)

    def test_consistent_days_pass(self):
        hours = self.hours(3)
        result = self.check(self.daily_from(hours), hours)
        self.assertEqual(3, result["daily_days_compared"])
        for key in ("daily_days_mismatched", "daily_days_missing", "daily_days_duplicated"):
            self.assertEqual(0, result[key])
        self.assertEqual(0, result["daily_days_hours_incomplete"])
        self.assertEqual(3, result["daily_warmup_days"])
        self.assertEqual(1, result["daily_warmup_short"])  # fewer than 200 days

    def test_volume_only_drift_is_a_mismatch(self):
        hours = self.hours(3)
        daily = self.daily_from(hours)
        daily[1] = replace(daily[1], volume=daily[1].volume + D("1"))
        self.assertEqual(1, self.check(daily, hours)["daily_days_mismatched"])

    def test_missing_day_duplicate_day_and_missing_hour_are_counted(self):
        hours = self.hours(3)
        daily = self.daily_from(hours)
        self.assertEqual(1, self.check(daily[:2], hours)["daily_days_missing"])
        self.assertEqual(1, self.check([*daily, daily[2]], hours)["daily_days_duplicated"])
        gap = hours[:30] + hours[31:]  # one hour of day 2 absent
        self.assertEqual(1, self.check(daily, gap)["daily_days_hours_incomplete"])
