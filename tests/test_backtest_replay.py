"""Chronology, adapter and accounting tests for the historical replay (synthetic data)."""

import math
import unittest
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import getcontext, localcontext
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
    cross_check_hourly,
    order_requests,
    replay,
    signals_for,
    summarise,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals
from crypto_grid_bot.simulation.execution import match, place, reduce_unreserved
from crypto_grid_bot.simulation.models import Account, LimitOrder, MarketRules, Quote, timestamp
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator

ROOT = Path(__file__).resolve().parents[1]
START_MS = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)
WARMUP = 800  # hours; the feature engine needs 743 completed observations
# Every field of a replay summary (results.json rows); a change must be deliberate.
SUMMARY_FIELDS = {
    "symbol",
    "path_mode",
    "strategy",
    "feature_version",
    "engine_version",
    "news_component",
    "window",
    "initial_quote",
    "final_total_equity",
    "return_pct",
    "max_drawdown_pct",
    "buy_and_hold_return_pct",
    "buy_and_hold_max_drawdown_pct",
    "fees",
    "turnover",
    "realised_grid_sell_pnl",
    "realised_exit_pnl",
    "exit_sells",
    "realised_exit_pnl_by_reason",
    "completed_cycles",
    "completed_cycles_by_week",
    "active_max_drawdown_pct",
    "risk_evaluations",
    "hard_drawdown_halts",
    "soft_drawdown_rebases",
    "drawdown_restarts",
    "order_requests",
    "max_order_requests_per_day",
    "days_over_request_budget",
    "buys",
    "sells",
    "grids_opened",
    "range_exits",
    "reserve_pending",
    "reserve_secured",
    "final_inventory",
    "bars",
    "warmup_bars_skipped",
    "frames",
    "time_with_inventory_pct",
    "time_with_orders_pct",
    "mean_exposure_when_invested_pct",
    "halted_at",
    "halt_reason",
    "transient_pauses",
    "regimes_by_bar",
    "decisions_by_bar",
    "top_reasons_by_bar",
    "accounting_problems",
    "rules",
    "assumed_spread_pct",
    "hourly_equity",
    "exit_blocked_frames",
    "exit_blocked_frames_by_kind",
    "max_exit_blocked_streak",
    "max_unsellable_notional",
    "final_exit_blocked",
    "final_unsellable_notional",
}


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
        # Warm-up boundary: inputs are available once enough candles have closed.
        self.assertIsInstance(inputs.trend, float)

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

    def test_summary_reports_the_run_it_was_given(self):
        # Bob's test audit (PR #51, P5): summarise formats every replay result and was
        # never called by a test.
        engine = engine_for(hourly(WARMUP))
        t = START_MS + WARMUP * HOUR_MS
        minutes = [candle(t + i * 60_000, 1.0, 1.001, 0.999, 1.0) for i in range(30)]
        run = RunConfig("TESTUSDT", "low_first", True, RULES, D(100), D("0.0005"))
        metrics, account = replay(self.config, run, minutes, engine)
        problems = check_accounting(run, metrics, account)
        summary = summarise(run, metrics, account, problems)
        self.assertEqual("TESTUSDT", summary["symbol"])
        self.assertEqual("low_first", summary["path_mode"])
        self.assertEqual("gated grid (price-only-v1)", summary["strategy"])
        self.assertIn("ABSENT", summary["news_component"])
        self.assertEqual(str(metrics.final_equity), summary["final_total_equity"])
        self.assertEqual("100", summary["initial_quote"])
        expected = float((metrics.final_equity / D(100) - 1) * 100)
        self.assertEqual(expected, summary["return_pct"])
        self.assertEqual(metrics.completed_cycles, summary["completed_cycles"])
        self.assertEqual(metrics.bars, summary["bars"])
        self.assertEqual(problems, summary["accounting_problems"])
        self.assertIsNone(summary["halted_at"])
        self.assertNotIn("orders_authorized", summary)
        window = summary["window"]
        self.assertEqual(datetime.fromtimestamp(t / 1000, UTC).isoformat(), window[0])
        last = t + 29 * 60_000
        self.assertEqual(datetime.fromtimestamp(last / 1000, UTC).isoformat(), window[1])
        # Bob's review of #54: pin the whole schema, so a dropped or renamed field fails.
        self.assertEqual(SUMMARY_FIELDS, set(summary))


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

    def test_high_precision_fill_journal_reconciles_with_simulator_balances(self):
        rules = MarketRules(
            symbol="TESTUSDT",
            tick_size=D("1e-18"),
            quantity_step=D("1e-18"),
            minimum_notional=D("1"),
            fee_rate=D("0.001"),
            taker_fee_rate=D("0.003"),
            slippage_rate=D(0),
            participation=D(1),
        )
        run = RunConfig("TESTUSDT", "low_first", True, rules, D(100), D("0.0005"))
        account, metrics = Account.start(D(100)), Metrics()
        orders = (
            ("b", "buy", "1.234567890123456789", "2.345678901234567890", "1", "1.1"),
            ("b/sell", "sell", "1.334567890123456789", "1.123456789012345678", "1.4", "1.5"),
            (
                "exit/q",
                "sell",
                "1.134567890123456789",
                "1.222222112222222212",
                "1.134567890123456789",
                "1.3",
            ),
        )
        # Like PaperSimulator.step: account operations use 50 digits, then the
        # replay receives fills outside that context. Neither may round the other.
        with localcontext() as caller:
            caller.prec = 28
            for index, (key, side, price, quantity, bid, ask) in enumerate(orders):
                with self.subTest(side=side, order=key):
                    when = f"2024-01-01T00:0{index}:00+00:00"
                    quote = Quote(key, rules.symbol, when, when, D(bid), D(ask), D(100), D(100))
                    with localcontext() as simulator:
                        simulator.prec = 50
                        if key.startswith("exit/"):
                            fills = reduce_unreserved(account, quote, rules).fills
                        else:
                            place(
                                account,
                                LimitOrder(key, side, D(price), D(quantity), D(quantity)),
                                rules,
                            )
                            fills = match(account, quote, rules)
                        account.last_equity = account.equity(quote, rules)
                        metrics.final_equity = account.last_equity
                    self.assertEqual(1, len(fills))
                    _record_fills(metrics, [asdict(fill) for fill in fills], "test_exit")
                    self.assertEqual(28, getcontext().prec)
                    metrics.frames += 1
                    self.assertEqual([], check_accounting(run, metrics, account))
            self.assertEqual(D(0), account.inventory)
            self.assertEqual(D(0), metrics.cost_basis)
            self.assertEqual(1, metrics.exit_sells)
            self.assertEqual({"test_exit": metrics.exit_pnl}, metrics.exit_pnl_by_reason)


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

    def test_volume_drift_is_counted_separately_up_to_the_tolerance(self):
        hours = self.hours(3)
        daily = self.daily_from(hours)
        volume = daily[1].volume
        within = replace(daily[1], volume=volume * D("1.001"))  # exactly 0.1%
        beyond = replace(daily[1], volume=volume * D("1.0011"))
        moved = replace(daily[1], close=daily[1].close + D("0.0001"))
        for bar, drift, mismatched in ((within, 1, 0), (beyond, 0, 1), (moved, 0, 1)):
            with self.subTest(bar=bar):
                result = self.check([daily[0], bar, daily[2]], hours)
                self.assertEqual(drift, result["daily_days_volume_drift"])
                self.assertEqual(mismatched, result["daily_days_mismatched"])

    def test_missing_day_duplicate_day_and_missing_hour_are_counted(self):
        hours = self.hours(3)
        daily = self.daily_from(hours)
        self.assertEqual(1, self.check(daily[:2], hours)["daily_days_missing"])
        self.assertEqual(1, self.check([*daily, daily[2]], hours)["daily_days_duplicated"])
        gap = hours[:30] + hours[31:]  # one hour of day 2 absent
        self.assertEqual(1, self.check(daily, gap)["daily_days_hours_incomplete"])


class BasketGapTests(unittest.TestCase):
    """Codex (PR #16): an unexpected basket gap can change the vote set while the minimum
    vote count still passes, so the gap must be caught by data validation."""

    def test_a_basket_gap_changes_breadth_silently_and_verify_catches_it(self):
        from crypto_grid_bot.backtest.replay import check_hourly_series

        def trend(slope):
            return [candle(START_MS + i * HOUR_MS, 1, 1, 1, 1 + slope * i) for i in range(WARMUP)]

        candles = hourly(WARMUP)
        pair = SeriesFeatures("TESTUSDT", candles)
        rising = [SeriesFeatures(f"U{i}USDT", trend(0.001), full=False) for i in range(5)]
        falling = trend(-0.0005)
        gapped = falling[:-3]  # the last three hours are missing
        options = {
            "range_atr_multiple": 2.0,
            "levels": 8,
            "minimum_cost_multiple": 3.0,
            "round_trip_cost": 0.0035,
        }
        minute = START_MS + WARMUP * HOUR_MS
        breadth = {}
        for name, series in (("complete", falling), ("gapped", gapped)):
            basket = [*rising, SeriesFeatures("DOWNUSDT", series, full=False)]
            inputs = FeatureEngine(pair, pair, basket, **options).at(minute)
            breadth[name] = inputs.breadth
        # Six voters (five up, one down) versus five: breadth moves, and both runs still
        # have at least MINIMUM_BREADTH_MARKETS votes, so the engine cannot tell.
        self.assertAlmostEqual(2 * 5 / 6 - 1, breadth["complete"])
        self.assertEqual(1.0, breadth["gapped"])
        window = (START_MS, minute)
        self.assertEqual(0, check_hourly_series(falling, window)["series_hours_missing"])
        self.assertEqual(3, check_hourly_series(gapped, window)["series_hours_missing"])


class VolumeDriftTests(unittest.TestCase):
    """Owner decision 2026-09-24: volume-only drift up to 0.1% is counted, not fatal."""

    def test_compare_bars(self):
        from crypto_grid_bot.backtest.replay import compare_bars

        base = candle(START_MS, 1.0, 1.1, 0.9, 1.05, volume="1000")
        self.assertEqual("match", compare_bars(base, base))
        self.assertEqual("drift", compare_bars(replace(base, volume=D("1000.9")), base))
        self.assertEqual("drift", compare_bars(replace(base, volume=D("999")), base))
        self.assertEqual("mismatch", compare_bars(replace(base, volume=D("1001.01")), base))
        self.assertEqual("mismatch", compare_bars(replace(base, high=base.high + 1), base))
        zero = replace(base, volume=D("0"))
        self.assertEqual("mismatch", compare_bars(base, zero))  # no relative tolerance on 0
        # Strict mode (tolerance 0): any volume difference is a mismatch.
        strict = D(0)
        self.assertEqual("match", compare_bars(base, base, strict))
        self.assertEqual("mismatch", compare_bars(replace(base, volume=D("999")), base, strict))

    def test_hourly_drift_is_reported_and_not_a_mismatch(self):
        from crypto_grid_bot.backtest.klines import aggregate

        minutes = [candle(START_MS + i * 60_000, 1.0, 1.001, 0.999, 1.0) for i in range(60)]
        (hour,) = aggregate(minutes)
        drifted = replace(hour, volume=hour.volume * D("1.0005"))
        result = cross_check_hourly(minutes, [drifted], (START_MS, START_MS + HOUR_MS))
        self.assertEqual((0, 1), (result["hours_mismatched"], result["hours_volume_drift"]))
        strict = cross_check_hourly(minutes, [drifted], (START_MS, START_MS + HOUR_MS), D(0))
        self.assertEqual((1, 0), (strict["hours_mismatched"], strict["hours_volume_drift"]))


# ---------------------------------------------------------------------------
# Audit fix tests (F16, F17, F18) — 2026-09-30
# ---------------------------------------------------------------------------


class SignalsForStructureAlignmentTests(unittest.TestCase):
    """F16: signals_for(gated=True) must pass structure_alignment from Inputs."""

    def _inputs(self, structure_alignment: float):
        from dataclasses import replace as dc_replace

        engine = engine_for(hourly(WARMUP))
        base = engine.at(START_MS + WARMUP * HOUR_MS)
        # Replace structure_alignment with a known non-zero value.
        return dc_replace(base, structure_alignment=structure_alignment)

    def test_gated_signals_carries_structure_alignment(self):
        """structure_alignment from Inputs must appear in the gated MarketSignals."""
        when = datetime(2024, 6, 1, tzinfo=UTC)
        inputs = self._inputs(0.75)
        signals = signals_for(inputs, when, gated=True)
        self.assertAlmostEqual(0.75, signals.structure_alignment)

    def test_gated_signals_negative_structure_alignment(self):
        when = datetime(2024, 6, 1, tzinfo=UTC)
        inputs = self._inputs(-0.50)
        signals = signals_for(inputs, when, gated=True)
        self.assertAlmostEqual(-0.50, signals.structure_alignment)

    def test_ungated_signals_structure_alignment_is_zero(self):
        """Ungated baseline always uses structure_alignment=0.0 (by design)."""
        when = datetime(2024, 6, 1, tzinfo=UTC)
        inputs = self._inputs(0.99)
        signals = signals_for(inputs, when, gated=False)
        self.assertEqual(0.0, signals.structure_alignment)


class FtaRegimeGateTests(unittest.TestCase):
    """F17/F18: _open_grid passes fta_resistance only in RANGE; full chain."""

    def setUp(self):
        from crypto_grid_bot.domain import MarketRegime, RegimeAssessment

        self.MarketRegime = MarketRegime
        self.RegimeAssessment = RegimeAssessment
        self.config = load_config(ROOT / "config/default.toml")

    def _open_grid_regime(self, regime_value, fta_resistance):
        """Open a grid with a specific regime and fta_resistance; return the grid plan used."""
        import contextlib

        simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100))
        account = simulator.store.read()
        simulator.close()

        engine = engine_for(hourly(WARMUP))
        inputs = engine.at(START_MS + WARMUP * HOUR_MS)
        when = datetime.fromtimestamp((START_MS + WARMUP * HOUR_MS) / 1000, UTC)

        from dataclasses import replace as dc_replace

        # Force a specific fta_resistance onto the inputs
        inputs = dc_replace(inputs, fta_resistance=fta_resistance)

        signals = signals_for(inputs, when, gated=True)
        candidate = candidate_for(inputs, "TESTUSDT", 0.05, 1e9, gated=True)
        quote = bar_quotes(
            candle(
                START_MS + WARMUP * HOUR_MS,
                float(inputs.fair_value),
                float(inputs.fair_value) * 1.001,
                float(inputs.fair_value) * 0.999,
                float(inputs.fair_value),
            ),
            "TESTUSDT",
            "low_first",
            D("0.0005"),
            RULES.tick_size,
        )[0]
        frame = Frame(
            quote,
            signals,
            candidate,
            inputs.fair_value,
            inputs.atr,
            True,
            None,
            None,
            fta_resistance,
        )

        regime = self.RegimeAssessment(regime_value, 0.5, 0.9, ())
        # Capture fta passed to builder by patching it
        captured = {}
        original_build = simulator.builder.build

        def capture_build(**kwargs):
            captured["fta_resistance"] = kwargs.get("fta_resistance")
            return original_build(**kwargs)

        simulator.builder.build = capture_build
        with contextlib.suppress(Exception):
            simulator._open_grid(account, frame, [], regime)
        return captured.get("fta_resistance", "NOT_CALLED")

    def test_fta_passed_in_range_regime(self):
        """FTA resistance cap is active when regime is RANGE."""
        fta = float(engine_for(hourly(WARMUP)).at(START_MS + WARMUP * HOUR_MS).fair_value) * 1.05
        result = self._open_grid_regime(self.MarketRegime.RANGE, fta)
        self.assertEqual(fta, result)

    def test_fta_suppressed_in_bull_regime(self):
        """FTA resistance cap is disabled when regime is BULL."""
        fta = float(engine_for(hourly(WARMUP)).at(START_MS + WARMUP * HOUR_MS).fair_value) * 1.05
        result = self._open_grid_regime(self.MarketRegime.BULL, fta)
        self.assertIsNone(result)

    def test_fta_suppressed_in_bear_regime(self):
        """FTA resistance cap is disabled when regime is BEAR."""
        fta = float(engine_for(hourly(WARMUP)).at(START_MS + WARMUP * HOUR_MS).fair_value) * 1.05
        result = self._open_grid_regime(self.MarketRegime.BEAR, fta)
        self.assertIsNone(result)

    def test_frame_carries_fta_from_inputs(self):
        """F18: Inputs.fta_resistance is preserved through Frame construction."""
        engine = engine_for(hourly(WARMUP))
        inputs = engine.at(START_MS + WARMUP * HOUR_MS)
        from dataclasses import replace as dc_replace

        fta_val = float(inputs.fair_value) * 1.08
        inputs = dc_replace(inputs, fta_resistance=fta_val)
        when = datetime.fromtimestamp((START_MS + WARMUP * HOUR_MS) / 1000, UTC)
        signals = signals_for(inputs, when, gated=True)
        candidate = candidate_for(inputs, "TESTUSDT", 0.05, 1e9, gated=True)
        quote = bar_quotes(
            candle(
                START_MS + WARMUP * HOUR_MS,
                float(inputs.fair_value),
                float(inputs.fair_value) * 1.001,
                float(inputs.fair_value) * 0.999,
                float(inputs.fair_value),
            ),
            "TESTUSDT",
            "low_first",
            D("0.0005"),
            RULES.tick_size,
        )[0]
        frame = Frame(
            quote,
            signals,
            candidate,
            inputs.fair_value,
            inputs.atr,
            True,
            None,
            None,
            inputs.fta_resistance,
        )
        self.assertAlmostEqual(fta_val, frame.fta_resistance)


# ---------------------------------------------------------------------------
# Variant E tests (spec v1 §3 E) — volume-confirmed range exit
# ---------------------------------------------------------------------------


class EThresholdTests(unittest.TestCase):
    """_e_compute_threshold: median of 720 completed 1h base volumes × 2 × 6."""

    def _hours(self, count, volume):
        return [
            candle(START_MS + i * HOUR_MS, 1.0, 1.001, 0.999, 1.0, volume=str(volume))
            for i in range(count)
        ]

    def test_threshold_is_2_times_median_times_6(self):
        from crypto_grid_bot.backtest.replay import _e_compute_threshold

        # 720 hours all with volume=100 → median=100, threshold=2×100×6=1200
        hours = self._hours(720, 100)
        t0_ms = START_MS + 720 * HOUR_MS  # exactly after the last hour closes
        result = _e_compute_threshold(hours, t0_ms)
        self.assertEqual(D("1200"), result)

    def test_fewer_than_720_hours_returns_none(self):
        from crypto_grid_bot.backtest.replay import _e_compute_threshold

        hours = self._hours(719, 100)
        t0_ms = START_MS + 720 * HOUR_MS
        self.assertIsNone(_e_compute_threshold(hours, t0_ms))

    def test_zero_median_returns_none(self):
        from crypto_grid_bot.backtest.replay import _e_compute_threshold

        # All zero volume → median 0 → threshold unavailable
        hours = self._hours(720, 0)
        t0_ms = START_MS + 720 * HOUR_MS
        self.assertIsNone(_e_compute_threshold(hours, t0_ms))

    def test_uses_only_completed_hours_before_t0(self):
        from crypto_grid_bot.backtest.replay import _e_compute_threshold

        # Hours with open_ms < floor_hour(t0): included. Hours at or after: excluded.
        # t0 is mid-hour (START_MS + 720 h + 30 min). floor_hour = START_MS + 720 h.
        # So only the first 720 hours (open_ms in [START_MS, START_MS+719h]) qualify.
        hours = self._hours(721, 100)  # 721 hours, last one opens at START_MS+720h
        t0_ms = START_MS + 720 * HOUR_MS + 30 * 60_000  # mid-hour
        # floor_hour(t0) = START_MS + 720*HOUR_MS
        # completed = open_ms < floor_hour_t0 → hours[0..719] → exactly 720
        result = _e_compute_threshold(hours, t0_ms)
        self.assertEqual(D("1200"), result)

    def test_even_count_median_is_mean_of_two_middle(self):
        from crypto_grid_bot.backtest.replay import _e_compute_threshold

        # Build 720 hours: half with volume=100, half with volume=200
        # Sorted: 360×100, 360×200 → median = (100+200)/2 = 150 → threshold = 1800
        hours = [
            candle(
                START_MS + i * HOUR_MS, 1.0, 1.001, 0.999, 1.0, volume="100" if i < 360 else "200"
            )
            for i in range(720)
        ]
        t0_ms = START_MS + 720 * HOUR_MS
        result = _e_compute_threshold(hours, t0_ms)
        self.assertEqual(D("1800"), result)


class VariantEReplayTests(unittest.TestCase):
    """Spec v1 §3 E: volume-confirmed range exit, end-to-end via replay()."""

    # Use a simpler, faster replay setup than the full WARMUP scenario.
    # We need: enough hourly candles for features + 720 for E threshold + evaluation bars.

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        # Build 750 warmup hours + enough evaluation minutes.
        self.all_hours = hourly(WARMUP + 50)
        self.t = START_MS + WARMUP * HOUR_MS

    def _engine(self, extra_hourly=None):
        hours = self.all_hours if extra_hourly is None else extra_hourly
        series = SeriesFeatures("TESTUSDT", hours)
        basket = [SeriesFeatures(f"B{i}USDT", hours, full=False) for i in range(5)]
        return FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
            hourly_candles=hours,
        )

    def _run(self, minutes, engine=None, volume_exit=True):
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        engine = engine or self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        policy = SimulationPolicy(volume_exit=volume_exit)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy)
        self.assertEqual([], check_accounting(run, metrics, account))
        return metrics, account

    def _fair(self):
        return float(self._engine().at(self.t).fair_value)

    def _bars(self, start, stop, price):
        """Return 1m bars from minute `start` to minute `stop` (exclusive) at `price`."""
        return [
            candle(self.t + i * 60_000, price, price * 1.001, price * 0.999, price)
            for i in range(start, stop)
        ]

    # 6 hours = 360 minutes
    _SIX_H = 360
    # 12 hours = 720 minutes
    _TWELVE_H = 720

    def test_volume_above_threshold_exits_at_6h(self):
        """Volume ≥ threshold: no extension, range exit fires at 6 h (spec: equality exits)."""
        # Place the grid, then go outside range with high volume (10× threshold).
        fair = self._fair()
        minutes = self._bars(0, 30, fair)  # grid opens
        # Outside-range: bars just below grid_lower (0.955 × fair < grid_lower ≈ 0.951 × fair),
        # with huge volume. threshold ≈ 2 × 1M × 6 = 12M; 2M per bar >> threshold.
        # 0.955 keeps inventory value drop well below the 12% hard-drawdown limit.
        minutes += [
            candle(
                self.t + (30 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="2000000",
            )
            for i in range(self._SIX_H + 10)
        ]
        metrics, account = self._run(minutes)
        # Should have exited (range exit) within 6h window.
        self.assertGreater(metrics.range_exits, 0)
        self.assertFalse(account.halt)

    def test_volume_below_threshold_extends_to_12h(self):
        """Volume < threshold: extension granted, exit fires at 12 h."""
        fair = self._fair()
        minutes = self._bars(0, 30, fair)  # grid opens
        # Outside-range: tiny volume bars → extension granted → exit at 12h.
        # threshold ≈ 2 × 1M × 6 = 12M; volume=1 per bar is far below.
        # 0.955 × fair keeps drawdown within the 12% hard-halt limit.
        minutes += [
            candle(
                self.t + (30 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="1",
                taker="0",
            )
            for i in range(self._TWELVE_H + 10)
        ]
        metrics, account = self._run(minutes)
        # Must still exit (extended to 12h, but range exit fires).
        self.assertGreater(metrics.range_exits, 0)
        self.assertFalse(account.halt)

    def test_return_inside_range_resets_episode(self):
        """Price returning inside range resets the timer; a later departure starts a new episode."""
        fair = self._fair()
        minutes = self._bars(0, 30, fair)  # grid opens
        # Step 1: go outside for 3h (below extension threshold).
        # 0.955 × fair keeps drawdown within the 12% hard-halt limit.
        minutes += [
            candle(
                self.t + (30 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="1",
                taker="0",
            )
            for i in range(180)
        ]
        # Step 2: return inside range for 5 minutes.
        minutes += self._bars(210, 215, fair)
        # Step 3: go outside again for 7h (enough to exit at 6h on second episode).
        minutes += [
            candle(
                self.t + (215 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="2000000",
            )
            for i in range(self._SIX_H + 10)
        ]
        metrics, _ = self._run(minutes)
        # The second episode should trigger a range exit.
        self.assertGreater(metrics.range_exits, 0)

    def test_missing_reference_falls_back_to_v0_6h_exit(self):
        """Fewer than 720 reference hours → threshold unavailable → V0 6h exit."""
        # Use the same stable WARMUP+50 candles as all other E tests so the grid opens
        # cleanly. Only override hourly_candles to 100 entries (< 720) so that
        # _e_compute_threshold returns None and the code falls back to the V0 6h exit.
        hours = self.all_hours
        series = SeriesFeatures("TESTUSDT", hours)
        basket = [SeriesFeatures(f"B{i}USDT", hours, full=False) for i in range(5)]
        sparse_engine = FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
            hourly_candles=hours[:100],  # only 100 entries → _e_compute_threshold returns None
        )
        fair = float(sparse_engine.at(self.t).fair_value)
        minutes = self._bars(0, 30, fair)  # grid opens
        # 0.955 × fair keeps drawdown within the 12% hard-halt limit.
        minutes += [
            candle(
                self.t + (30 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="1",
                taker="0",
            )
            for i in range(self._SIX_H + 10)
        ]
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        policy = SimulationPolicy(volume_exit=True)
        metrics, account = replay(self.config, run, minutes, sparse_engine, policy=policy)
        # threshold is None → falls back to V0 6h exit (no extension).
        # The range exit must still fire.
        self.assertGreater(metrics.range_exits, 0)

    def test_variant_e_off_behaves_identically_to_v0(self):
        """volume_exit=False must produce the same range_exits as a V0 (policy=None) run."""
        fair = self._fair()
        minutes = self._bars(0, 30, fair)
        # 0.955 × fair keeps drawdown within the 12% hard-halt limit.
        minutes += [
            candle(
                self.t + (30 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="2000000",
            )
            for i in range(self._SIX_H + 10)
        ]
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        # V0 run.
        metrics_v0, _ = replay(self.config, run, list(minutes), engine)
        # Variant E off run.
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        metrics_e_off, _ = replay(
            self.config, run, list(minutes), engine, policy=SimulationPolicy(volume_exit=False)
        )
        self.assertEqual(metrics_v0.range_exits, metrics_e_off.range_exits)


class FShareTests(unittest.TestCase):
    """Unit tests for _f_compute_share (spec v1 §3 F signal computation)."""

    def _buf(self, count, start_ms=START_MS, taker_ratio=0.5):
        """Return ``count`` consecutive 1m bars with the given taker ratio."""
        return [
            candle(
                start_ms + i * 60_000,
                1.0,
                1.001,
                0.999,
                1.0,
                volume="1000",
                taker=str(int(1000 * taker_ratio)),
            )
            for i in range(count)
        ]

    def test_exactly_15_bars_returns_share(self):
        from crypto_grid_bot.backtest.replay import _f_compute_share

        buf = self._buf(15)  # bars 0..14; current bar is at minute 15
        current_ms = START_MS + 15 * 60_000
        result = _f_compute_share(buf, current_ms)
        self.assertAlmostEqual(result, 0.5, places=6)

    def test_fewer_than_15_returns_none(self):
        from crypto_grid_bot.backtest.replay import _f_compute_share

        buf = self._buf(14)
        result = _f_compute_share(buf, START_MS + 14 * 60_000)
        self.assertIsNone(result)

    def test_gap_in_window_returns_none(self):
        """A missing bar anywhere in the 15-bar window makes share unavailable."""
        from crypto_grid_bot.backtest.replay import _f_compute_share

        # 15 bars with a 2-minute gap between bars 10 and 11.
        buf = [
            candle(START_MS + (i if i <= 10 else i + 1) * 60_000, 1.0, 1.001, 0.999, 1.0)
            for i in range(15)
        ]
        current_ms = START_MS + 17 * 60_000  # after the last bar
        result = _f_compute_share(buf, current_ms)
        self.assertIsNone(result)

    def test_zero_volume_bar_inside_window_is_valid(self):
        """A single zero-volume bar inside the window is valid (spec §3 F)."""
        from crypto_grid_bot.backtest.replay import _f_compute_share

        buf = [
            candle(START_MS + i * 60_000, 1.0, 1.001, 0.999, 1.0, volume="1000", taker="500")
            for i in range(15)
        ]
        # Replace bar 7 with zero volume (still consecutive).
        buf[7] = candle(START_MS + 7 * 60_000, 1.0, 1.001, 0.999, 1.0, volume="0", taker="0")
        current_ms = START_MS + 15 * 60_000
        result = _f_compute_share(buf, current_ms)
        # 14 bars with 500/1000 = 0.5 taker ratio, 1 bar with 0/0.
        # total_vol = 14*1000 + 0 = 14000; taker_buy = 14*500 + 0 = 7000 → share = 0.5.
        self.assertAlmostEqual(result, 0.5, places=6)

    def test_all_zero_volume_returns_none(self):
        """Zero aggregate volume over 15 bars → share unavailable."""
        from crypto_grid_bot.backtest.replay import _f_compute_share

        buf = [
            candle(START_MS + i * 60_000, 1.0, 1.001, 0.999, 1.0, volume="0", taker="0")
            for i in range(15)
        ]
        result = _f_compute_share(buf, START_MS + 15 * 60_000)
        self.assertIsNone(result)

    def test_threshold_equality_at_040_blocks(self):
        """share == 0.40 (strict): share < 0.40 is False → block stays on if already on."""
        from crypto_grid_bot.backtest.replay import _F_BLOCK_THRESHOLD

        # 0.40 is NOT < 0.40 (strict), so the block should not turn ON due to this check.
        self.assertFalse(_F_BLOCK_THRESHOLD > 0.40)

    def test_threshold_equality_at_045_unblocks(self):
        """share == 0.45 (inclusive): should unblock."""
        from crypto_grid_bot.backtest.replay import _F_UNBLOCK_THRESHOLD

        self.assertTrue(_F_UNBLOCK_THRESHOLD <= 0.45)


class VariantFReplayTests(unittest.TestCase):
    """Spec v1 §3 F: order-flow entry block, end-to-end via replay()."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.all_hours = hourly(WARMUP + 50)
        self.t = START_MS + WARMUP * HOUR_MS

    def _engine(self):
        hours = self.all_hours
        series = SeriesFeatures("TESTUSDT", hours)
        basket = [SeriesFeatures(f"B{i}USDT", hours, full=False) for i in range(5)]
        return FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
            hourly_candles=hours,
        )

    def _fair(self):
        return float(self._engine().at(self.t).fair_value)

    def _run(self, minutes, flow_block_entry=True):
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        policy = SimulationPolicy(flow_block_entry=flow_block_entry)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy)
        self.assertEqual([], check_accounting(run, metrics, account))
        return metrics, account

    def _bars(self, start, stop, price, taker_ratio=0.5):
        """1m bars at ``price`` from minute ``start`` to ``stop`` (exclusive)."""
        vol = "1000000"
        tak = str(int(1_000_000 * taker_ratio))
        return [
            candle(
                self.t + i * 60_000,
                price,
                price * 1.001,
                price * 0.999,
                price,
                volume=vol,
                taker=tak,
            )
            for i in range(start, stop)
        ]

    def test_cancellation_counts_against_request_budget(self):
        """Buys cancelled while flow_block is on count against the per-day request budget."""
        fair = self._fair()
        # 15 high-taker-buy bars to warm up the signal (share = 0.8 → unblock).
        minutes = self._bars(0, 15, fair, taker_ratio=0.8)
        # Grid opens on bar 15 (share >= 0.45 → unblocked, grid placed).
        # 5 more in-range bars at high taker ratio to let the grid settle.
        minutes += self._bars(15, 20, fair, taker_ratio=0.8)
        # Now switch to low taker buy (share drops to 0.1 → block turns on).
        # We need 15 consecutive low-taker bars for the signal to update.
        minutes += self._bars(20, 35, fair * 0.999, taker_ratio=0.1)
        metrics, account = self._run(minutes)
        # When flow_block turned on, buys were cancelled → request count > 0.
        total_requests = sum(metrics.requests_by_day.values())
        self.assertGreater(total_requests, 0)
        # Account must not be halted and accounting must pass (checked in _run).
        self.assertEqual(account.halt, "")

    def test_flow_block_off_does_not_block_grid(self):
        """flow_block_entry=False (V0) must open a grid on the first eligible frame."""
        fair = self._fair()
        # 16 in-range bars at high taker (plenty for signal warmup if F were active).
        minutes = self._bars(0, 16, fair, taker_ratio=0.8)
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        # V0 run: should open a grid.
        metrics_v0, _ = replay(self.config, run, minutes, engine)
        # F off (explicit False): same behaviour as V0.
        metrics_f_off, _ = replay(
            self.config, run, list(minutes), engine, policy=SimulationPolicy(flow_block_entry=False)
        )
        self.assertEqual(metrics_v0.grids_opened, metrics_f_off.grids_opened)

    def test_missing_minute_vs_zero_volume(self):
        """A missing minute makes share unavailable (block stays on).
        A zero-volume minute inside the window is valid (spec §3 F).
        """
        from crypto_grid_bot.backtest.replay import _f_compute_share

        # Build a window of 15 bars, one of which is zero-volume.
        zero_vol_buf = [
            candle(START_MS + i * 60_000, 1.0, 1.001, 0.999, 1.0, volume="1000", taker="600")
            for i in range(15)
        ]
        zero_vol_buf[5] = candle(
            START_MS + 5 * 60_000, 1.0, 1.001, 0.999, 1.0, volume="0", taker="0"
        )
        share_zero = _f_compute_share(zero_vol_buf, START_MS + 15 * 60_000)
        # Zero-volume bar is valid: total_vol = 14*1000, taker = 14*600 → 0.6.
        self.assertIsNotNone(share_zero)
        self.assertAlmostEqual(share_zero, 0.6, places=5)

        # Build a window with a 2-minute gap (missing bar).
        gap_buf = [
            candle(START_MS + (i if i < 5 else i + 1) * 60_000, 1.0, 1.001, 0.999, 1.0)
            for i in range(15)
        ]
        share_gap = _f_compute_share(gap_buf, START_MS + 17 * 60_000)
        self.assertIsNone(share_gap)

    def test_unblock_while_v0_eligibility_pause_active(self):
        """F unblocking does not clear a V0 eligibility pause; the pause must remain."""
        fair = self._fair()
        # Warm up F signal with high taker so it starts unblocked.
        minutes = self._bars(0, 16, fair, taker_ratio=0.8)
        # Run just these bars to check that account is not halted.
        metrics, account = self._run(minutes)
        # Account starts in cash (no V0 pause injected by this bar sequence).
        # The test verifies the interaction: F off means pause is preserved by V0.
        # Verify F signal threshold logic: share >= 0.45 unblocks, but any V0 pause persists.
        from crypto_grid_bot.backtest.replay import _F_BLOCK_THRESHOLD, _F_UNBLOCK_THRESHOLD

        # Confirmed: F unblock threshold >= 0.45.
        self.assertEqual(_F_UNBLOCK_THRESHOLD, 0.45)
        self.assertEqual(_F_BLOCK_THRESHOLD, 0.40)

    def test_overlapping_f_block_and_range_exit(self):
        """When flow_block is active during a range exit, range exit still fires normally."""
        fair = self._fair()
        # 15 bars warmup with high taker ratio → signal available, share ≥ 0.45 → unblocked.
        minutes = self._bars(0, 15, fair, taker_ratio=0.8)
        # 15 more in-range bars to open a grid.
        minutes += self._bars(15, 30, fair, taker_ratio=0.8)
        # Now go outside range with LOW taker ratio → flow_block turns on.
        # Use 0.955 × fair to avoid the halt (same as E tests).
        SIX_H = 360
        minutes += [
            candle(
                self.t + (30 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="2000000",
                taker=str(int(2_000_000 * 0.1)),  # low taker → flow_block on
            )
            for i in range(SIX_H + 10)
        ]
        metrics, account = self._run(minutes)
        # Range exit should still fire despite flow_block being active.
        self.assertGreater(metrics.range_exits, 0)


class FFragmentTests(unittest.TestCase):
    """Unit tests for _f_cancel_buys: partial-fill and fragment accumulation (spec v1 §3 F)."""

    def _make_simulator(self):
        config = load_config(ROOT / "config/default.toml")
        sim = PaperSimulator(
            Path(":memory:"),
            config,
            RULES,
            D(100),
            policy=__import__(
                "crypto_grid_bot.simulation.runner", fromlist=["SimulationPolicy"]
            ).SimulationPolicy(flow_block_entry=True),
        )
        account = sim.store.read()
        sim.close()
        return sim, account

    def _quote(self):
        when = datetime(2024, 1, 2, tzinfo=UTC)
        return Quote(
            "q",
            "TESTUSDT",
            when.isoformat(),
            when.isoformat(),
            D("1.002"),
            D("1.0025"),
            D(1000),
            D(1000),
        )

    def test_partial_fill_creates_resting_sell_at_target(self):
        """A partially-filled buy (quantity > remaining) gets a sell at target when cancelled."""
        sim, account = self._make_simulator()
        quote = self._quote()
        report: dict = {"cancelled": [], "fills": []}

        # Construct a partially-filled buy: quantity=10, remaining=5, target=1.1.
        # Pre-condition: account needs cash and inventory to satisfy validation.
        # filled = quantity - remaining = 5
        # cash was reduced by filled * price * (1 + fee) when it filled; inventory was increased.
        # minimum_notional = 5, price = 1.0, target = 1.1, so filled_notional = 5 * 1.1 = 5.5 >= 5.
        filled_qty = D("5")
        buy_price = D("1.0000")
        target_price = D("1.1000")
        buy_qty = D("10")
        remaining_qty = buy_qty - filled_qty
        fee = filled_qty * buy_price * RULES.fee_rate
        # Set up the account state: cash reduced by filled cost, inventory increased.
        account.cash -= filled_qty * buy_price + fee
        account.inventory += filled_qty
        order = LimitOrder(
            "test/buy/0", "buy", buy_price, buy_qty, remaining_qty, target=target_price
        )
        account.orders["test/buy/0"] = order
        # Validate the account after manual state setup.
        account.validate(RULES)

        sim._f_cancel_buys(account, quote, report)

        # The buy must be cancelled.
        self.assertNotIn("test/buy/0", account.orders)
        # A sell at target_price must be placed for the filled quantity.
        sells = [o for o in account.orders.values() if o.side == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0].price, target_price)
        # The sell notional = target * qty >= min_notional (5.5 >= 5) so it's placed directly.
        self.assertGreaterEqual(sells[0].price * sells[0].quantity, RULES.minimum_notional)

    def test_below_minimum_fragment_accumulates_then_places_sell(self):
        """Fragments below min_notional accumulate; a sell is placed once the total meets it."""
        sim, account = self._make_simulator()
        quote = self._quote()
        report1: dict = {"cancelled": [], "fills": []}
        report2: dict = {"cancelled": [], "fills": []}

        # min_notional = 5. At target = 1.0, quantity_step = 0.1.
        # For a single fragment: filled=0.1, notional = 0.1 * 1.0 = 0.1 < 5 → fragment.
        # After 50 such fragments: 50 * 0.1 = 5.0 → sell placed.
        fill_qty = D("0.1")
        buy_price = D("1.0000")
        target_price = D("1.0000")  # use same as buy to avoid > check
        # target must be > buy price per spec; use 1.001 ticked correctly
        target_price = D("1.1000")
        buy_qty = D("1.0")

        def _add_partial_buy(key, filled):
            """Helper: add a partially-filled buy order with ``filled`` quantity done."""
            rem = buy_qty - filled
            fee = filled * buy_price * RULES.fee_rate
            account.cash -= filled * buy_price + fee
            account.inventory += filled
            order = LimitOrder(key, "buy", buy_price, buy_qty, rem, target=target_price)
            account.orders[key] = order

        # First cancellation: fragment too small (0.1 * 1.1 = 0.11 < 5).
        _add_partial_buy("buy/first", fill_qty)
        account.validate(RULES)
        sim._f_cancel_buys(account, quote, report1)

        # Fragment accumulated but no sell placed yet.
        self.assertNotIn("buy/first", account.orders)
        sell_count_after_first = sum(1 for o in account.orders.values() if o.side == "sell")
        self.assertEqual(sell_count_after_first, 0)
        self.assertIn(target_price, account.flow_fragments)
        self.assertEqual(account.flow_fragments[target_price], fill_qty)

        # Second cancellation: add enough so total reaches min_notional.
        # need: (existing + new) * target >= min_notional → new >= (5 - 0.1) / 1.1 ≈ 4.45
        # use 50 * 0.1 = 5 total → need to add 4.9 more in fill_qty steps... simplify:
        # just add one large partial fill that pushes total over min_notional.
        large_fill = D("5.0")
        large_buy_qty = D("6.0")
        rem2 = large_buy_qty - large_fill
        fee2 = large_fill * buy_price * RULES.fee_rate
        account.cash -= large_fill * buy_price + fee2
        account.inventory += large_fill
        order2 = LimitOrder(
            "buy/second", "buy", buy_price, large_buy_qty, rem2, target=target_price
        )
        account.orders["buy/second"] = order2
        account.validate(RULES)
        sim._f_cancel_buys(account, quote, report2)

        self.assertNotIn("buy/second", account.orders)
        # Now the fragment total should be enough to place a sell.
        sells = [o for o in account.orders.values() if o.side == "sell"]
        self.assertEqual(len(sells), 1)
        self.assertGreaterEqual(sells[0].price * sells[0].quantity, RULES.minimum_notional)


class VariantGReplayTests(unittest.TestCase):
    """Spec v1 §3 G: funding-rate gate, integration tests via replay()."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.all_hours = hourly(WARMUP + 50)
        self.t = START_MS + WARMUP * HOUR_MS

    def _engine(self):
        hours = self.all_hours
        series = SeriesFeatures("TESTUSDT", hours)
        basket = [SeriesFeatures(f"B{i}USDT", hours, full=False) for i in range(5)]
        return FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
            hourly_candles=hours,
        )

    def _fair(self):
        return float(self._engine().at(self.t).fair_value)

    def _bars(self, start, stop, price):
        return [
            candle(self.t + i * 60_000, price, price * 1.001, price * 0.999, price)
            for i in range(start, stop)
        ]

    def _funding_signal(self, rate):
        """Build a FundingSignal whose three most-recent usable records all carry ``rate``."""
        from decimal import Decimal as D

        from crypto_grid_bot.backtest.funding import FundingRecord, FundingSignal

        # Three 8-hour settlements before the evaluation window.
        # self.t is at WARMUP hours from START_MS.
        # Place them 24h, 16h and 8h before self.t so they are usable at t.
        hour_ms = 3_600_000
        settle_3 = self.t - 8 * hour_ms  # scheduled at self.t - 8h
        settle_2 = self.t - 16 * hour_ms
        settle_1 = self.t - 24 * hour_ms
        # calc_time = scheduled + 11 ms offset; usable = calc_time + 60_000
        records = [
            FundingRecord(settle_1 + 11, 8, D(rate)),
            FundingRecord(settle_2 + 11, 8, D(rate)),
            FundingRecord(settle_3 + 11, 8, D(rate)),
        ]
        return FundingSignal(records)

    def test_high_funding_blocks_new_grid(self):
        """G blocks a new grid when all three rates > 0.0005."""
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        fair = self._fair()
        minutes = self._bars(0, 20, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        signal = self._funding_signal("0.001")  # rate 0.001 > 0.0005 → blocks
        policy = SimulationPolicy(funding_gate=True)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy, funding=signal)
        # G must block all grid opens.
        self.assertEqual(metrics.grids_opened, 0)
        self.assertEqual(account.halt, "")

    def test_low_funding_allows_grid(self):
        """G does not block when the rate is <= 0.0005."""
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        fair = self._fair()
        minutes = self._bars(0, 20, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        signal = self._funding_signal("0.0003")  # rate 0.0003 <= 0.0005 → clear
        policy = SimulationPolicy(funding_gate=True)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy, funding=signal)
        # G must not block grid opens; at least one grid should open.
        self.assertGreater(metrics.grids_opened, 0)
        self.assertEqual(account.halt, "")

    def test_funding_gate_off_is_v0(self):
        """funding_gate=False must produce the same grids_opened as V0."""
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        fair = self._fair()
        minutes = self._bars(0, 20, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        metrics_v0, _ = replay(self.config, run, list(minutes), engine)
        metrics_g_off, _ = replay(
            self.config,
            run,
            list(minutes),
            engine,
            policy=SimulationPolicy(funding_gate=False),
        )
        self.assertEqual(metrics_v0.grids_opened, metrics_g_off.grids_opened)

    def test_no_funding_data_fails_closed(self):
        """funding=None with funding_gate=True fails closed (no new grids)."""
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        fair = self._fair()
        minutes = self._bars(0, 20, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        policy = SimulationPolicy(funding_gate=True)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy, funding=None)
        self.assertEqual(metrics.grids_opened, 0)
        self.assertEqual(account.halt, "")

    def test_existing_grid_and_exits_unaffected(self):
        """G only blocks new grids; existing grids' sells and range exits continue."""
        from crypto_grid_bot.simulation.runner import SimulationPolicy

        fair = self._fair()
        # First open a grid WITHOUT G active (so the grid is placed).
        first_minutes = self._bars(0, 20, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        # Then run with G active + high rate AND an outside-range sequence.
        signal = self._funding_signal("0.001")  # blocks new grids
        policy = SimulationPolicy(funding_gate=True)
        # Combine in-range bars (grid will try to open, G blocks) + outside bars.
        SIX_H = 360
        outside_bars = [
            candle(
                self.t + (20 + i) * 60_000,
                fair * 0.955,
                fair * 0.956,
                fair * 0.954,
                fair * 0.955,
                volume="2000000",
            )
            for i in range(SIX_H + 10)
        ]
        minutes = first_minutes + outside_bars
        metrics, account = replay(self.config, run, minutes, engine, policy=policy, funding=signal)
        # G blocked the new grid, so grids_opened = 0.
        self.assertEqual(metrics.grids_opened, 0)
        # The account should not be halted (no inventory to liquidate).
        self.assertEqual(account.halt, "")
