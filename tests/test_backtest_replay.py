"""Chronology, adapter and accounting tests for the historical replay (synthetic data)."""

import math
import random
import statistics
import tempfile
import unittest
import zipfile
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import getcontext, localcontext
from pathlib import Path
from unittest.mock import patch

from crypto_grid_bot.backtest.dataset import funding_local_path
from crypto_grid_bot.backtest.features import (
    BASELINE_HOURS,
    FEATURE_VERSION,
    HOUR_MS,
    STALE_AFTER_MS,
    STRUCTURE_FEATURE_VERSION,
    FeatureEngine,
    SeriesFeatures,
    _rolling_median,
)
from crypto_grid_bot.backtest.funding import FundingRecord, FundingSignal
from crypto_grid_bot.backtest.jobs import variant_name, variant_policy
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
    load_funding,
    order_requests,
    replay,
    signals_for,
    summarise,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import CandidateMetrics, MarketSignals
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import match, place, reduce_unreserved
from crypto_grid_bot.simulation.models import Account, LimitOrder, MarketRules, Quote, timestamp
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator, SimulationPolicy
from crypto_grid_bot.strategy.order_flow import flow_blocked, taker_buy_share
from crypto_grid_bot.strategy.volume_exit import VolumeHistory

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
    "soft_drawdown_closes",
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

    def test_daily_bars_after_the_decision_cannot_change_structure_inputs(self):
        # Issue #158-1: the V2 structure features once read every daily bar, including
        # the decision's own unfinished day and later ones. A day may count only once it
        # has closed (open + 1 day <= decision minute), as in TrendSchedule.
        day = 86_400_000
        candles = hourly(WARMUP + 72)
        midnight = (WARMUP // 24 + 2) * 24  # an hour index that opens a UTC day
        midnight_ms = START_MS + midnight * HOUR_MS
        # A two-hour hole across that midnight: the pair's latest completed candle does
        # not change there while a daily bar does, so a cache keyed on the pair alone
        # would serve the previous day's structure.
        candles = [c for i, c in enumerate(candles) if i not in (midnight - 1, midnight)]
        # Flat days below fair value, except one high at 1.03 four days before that
        # midnight: the day closing at midnight is the third after it, which confirms it
        # as a swing high, so a resistance zone above fair value appears exactly then.
        rng = random.Random(158)
        days = []
        for d in range(-60, 45):
            open_ms, close = START_MS + d * day, 0.97 + rng.uniform(-0.005, 0.005)
            high = 1.03 if open_ms == midnight_ms - 4 * day else close * 1.005
            days.append(candle(open_ms, close, high, close * 0.995, close))

        def structure_engine(daily):
            return engine_for(candles, hourly_candles=candles, daily_bars=daily)

        engine = structure_engine(days)  # one engine, queried in order: its caches
        start = midnight_ms - 30 * HOUR_MS
        minutes = [*range(start, start + 60 * HOUR_MS, 20 * 60_000)]
        minutes += [midnight_ms + k * 60_000 for k in (-1, 0, 1)]
        for minute in sorted(minutes):
            completed = [d for d in days if d.open_ms + day <= minute]
            expected = structure_engine(completed).at(minute)
            # Days not closed by the decision minute changed beyond recognition, plus
            # days that do not exist yet: none of it may reach the decision.
            future = [
                replace(d, high=d.high * 5, low=d.low / 5, close=d.close * 3)
                for d in days
                if d.open_ms + day > minute
            ]
            later = [candle(days[-1].open_ms + k * day, 9.0, 9.9, 8.1, 9.5) for k in range(1, 30)]
            self.assertEqual(expected, structure_engine(completed + future + later).at(minute))
            self.assertEqual(expected, engine.at(minute), minute)
        # The completed days are in use, from the minute the confirming day closes.
        before, after = engine.at(midnight_ms - 60_000), engine.at(midnight_ms)
        self.assertEqual(before.hour_open_ms, after.hour_open_ms)  # inside the hole
        self.assertIsNone(before.fta_resistance)
        self.assertEqual(1.03, after.fta_resistance)

    def test_stale_hourly_data_zeroes_quality(self):
        candles = hourly(WARMUP)
        engine = engine_for(candles)
        fresh = engine.at(START_MS + WARMUP * HOUR_MS)
        stale = engine.at(START_MS + (WARMUP + 3) * HOUR_MS)
        self.assertEqual(1.0, fresh.market_quality)
        self.assertEqual(0.0, stale.market_quality)
        self.assertEqual(0.0, stale.pair_quality)


class FeatureEfficiencyTests(unittest.TestCase):
    """The incremental medians and the cached Inputs give exactly the direct results."""

    OPTIONS = {
        "range_atr_multiple": 2.0,
        "levels": 8,
        "minimum_cost_multiple": 3.0,
        "round_trip_cost": 0.0035,
    }

    def setUp(self):
        candles = hourly(WARMUP + 12)
        # The pair misses four hours near the end, so it goes stale one minute after an
        # hour boundary; the basket members end at different hours and go stale in turn.
        self.pair_candles = candles[: WARMUP + 2] + candles[WARMUP + 6 :]
        self.pair = SeriesFeatures("TESTUSDT", self.pair_candles)
        self.basket = [
            SeriesFeatures(f"B{i}USDT", candles[: WARMUP + 3 + i], full=False) for i in range(6)
        ]

    def engine(self, **structure):
        return FeatureEngine(self.pair, self.pair, self.basket, **self.OPTIONS, **structure)

    def test_rolling_median_equals_a_fresh_median_of_every_window(self):
        rng = random.Random(11)
        values = [None] * 5 + [rng.choice([0.0, -0.0, 1.5, 2.5, rng.random()]) for _ in range(400)]
        values[200:203] = [None] * 3
        for size in (1, 2, 5, 6, 50):
            expected = [None] * len(values)
            for i in range(size - 1, len(values)):
                window = values[i - size + 1 : i + 1]
                if None not in window:
                    expected[i] = statistics.median(window)
            with self.subTest(size=size):
                # repr tells -0.0 from 0.0: the window must also keep a stable sort's order.
                got = _rolling_median(values, size)
                self.assertEqual([repr(v) for v in expected], [repr(v) for v in got])

    def test_series_baselines_are_the_medians_of_their_30_day_windows(self):
        for series, i in ((self.pair, WARMUP), (self.pair, 733), (self.pair, 742)):
            for values, medians in (
                (series.atr_pct, series.atr_pct_median),
                (series.qv24, series.qv24_median),
            ):
                window = values[i - BASELINE_HOURS + 1 : i + 1]
                expected = None if None in window else statistics.median(window)
                self.assertEqual(expected, medians[i])
        self.assertIsNone(self.pair.qv24_median[741])
        self.assertIsNotNone(self.pair.qv24_median[742])

    def test_every_minute_matches_an_uncached_engine_in_any_order(self):
        engine = self.engine()
        first, end = START_MS + (WARMUP - 60) * HOUR_MS, START_MS + (WARMUP + 12) * HOUR_MS
        minutes = list(range(first, end, 60_000))
        rng = random.Random(5)
        for minute in [*minutes, *reversed(minutes), *rng.sample(minutes, 500)]:
            self.assertEqual(self.engine().at(minute), engine.at(minute), minute)

    def test_structure_features_match_an_uncached_engine_in_any_order(self):
        # The V2 structure inputs: the pair's hourly candles and a daily history that
        # starts 30 days earlier, so completed days exist at every minute checked.
        days = [
            candle(START_MS + (d - 30) * 86_400_000, p, p * 1.03, p * 0.97, p * 1.01)
            for d, p in enumerate(1.0 + 0.2 * math.sin(d / 3) for d in range(90))
        ]
        structure = {"hourly_candles": self.pair_candles, "daily_bars": days}
        engine = self.engine(**structure)
        first, end = START_MS + (WARMUP - 6) * HOUR_MS, START_MS + (WARMUP + 12) * HOUR_MS
        minutes = list(range(first, end, 7 * 60_000))
        for minute in [*minutes, *reversed(minutes)]:
            inputs = engine.at(minute)
            self.assertEqual(self.engine(**structure).at(minute), inputs, minute)
            # The structure inputs are in use, not their unavailable defaults.
            self.assertNotEqual(0.0, inputs.structure_alignment)
            self.assertIsNotNone(inputs.fta_resistance)

    def test_staleness_inside_an_hour_is_not_served_from_the_cache(self):
        engine = self.engine()
        # The pair's last candle before its hole completes at WARMUP + 2 hours.
        edge = START_MS + (WARMUP + 2) * HOUR_MS + STALE_AFTER_MS
        before, after = engine.at(edge), engine.at(edge + 60_000)
        self.assertEqual(edge // HOUR_MS, (edge + 60_000) // HOUR_MS)
        self.assertGreater(before.pair_quality, 0.0)
        self.assertEqual(0.0, after.pair_quality)

    def test_one_result_is_reused_within_an_hour(self):
        engine = self.engine()
        minute = START_MS + (WARMUP - 10) * HOUR_MS
        self.assertIs(engine.at(minute), engine.at(minute + 59 * 60_000))
        self.assertIsNot(engine.at(minute), engine.at(minute + 60 * 60_000))

    def test_warmed_is_exactly_whether_at_returns_inputs(self):
        engine = self.engine()
        seen = set()
        for minute in range(START_MS + 730 * HOUR_MS, START_MS + 760 * HOUR_MS, 60_000):
            warmed = engine.warmed(minute)
            seen.add(warmed)
            self.assertEqual(self.engine().at(minute) is not None, warmed, minute)
        self.assertEqual({False, True}, seen)


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

    def test_the_fill_trigger_defaults_to_the_slippage_and_only_moves_resting_fills(self):
        # D9 (owner decision 2026-10-05). Set to the slippage, the trigger gives the same
        # run as when it is unset, and only the rules record it; a stricter one misses
        # resting fills, with the accounting intact.
        engine = engine_for(hourly(WARMUP))
        t = START_MS + WARMUP * HOUR_MS
        minutes = []
        for i in range(600):
            mid = float(engine.at(t).fair_value) * (1 + 0.03 * math.sin(2 * math.pi * i / 90))
            minutes.append(candle(t + i * 60_000, mid, mid * 1.003, mid * 0.997, mid))
        rows = []
        for trigger in (None, D("0.0005"), D("0.005")):
            rules = replace(RULES, fill_trigger_rate=trigger)
            run = RunConfig("TESTUSDT", "high_first", False, rules, D(100), D("0.0005"))
            metrics, account = replay(self.config, run, minutes, engine)
            rows.append(summarise(run, metrics, account, check_accounting(run, metrics, account)))
        default, same, strict = rows
        self.assertNotIn("fill_trigger_rate", default.pop("rules"))
        self.assertEqual("0.0005", same.pop("rules")["fill_trigger_rate"])
        self.assertEqual(default, same)
        self.assertEqual([], strict["accounting_problems"])
        self.assertLess(strict["buys"], default["buys"])

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
        # rejected as a transient (its report carries no range_exit flag). Not so far as
        # the hard drawdown: 20% below once halted the account, and the one exit counted
        # then was a flat, halted account timing out of its old band, which amendments 2
        # and 3 removed. At 10% below the exit is genuine, with inventory held.
        low = fair * 0.9
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

    def test_structure_runs_are_labelled_and_v0_labels_are_unchanged(self):
        # Issue #158-3: results must say what produced them.
        engine = engine_for(hourly(WARMUP))
        t = START_MS + WARMUP * HOUR_MS
        minutes = [candle(t + i * 60_000, 1.0, 1.001, 0.999, 1.0) for i in range(5)]
        labels = {}
        for gated in (True, False):
            run = RunConfig("TESTUSDT", "low_first", gated, RULES, D(100), D("0.0005"))
            metrics, account = replay(self.config, run, minutes, engine)
            for version in (FEATURE_VERSION, STRUCTURE_FEATURE_VERSION):
                row = summarise(run, metrics, account, [], feature_version=version)
                labels[gated, version] = (row["strategy"], row["feature_version"])
        self.assertEqual(
            {
                (True, FEATURE_VERSION): ("gated grid (price-only-v1)", "price-only-v1"),
                (False, FEATURE_VERSION): ("ungated grid baseline", "price-only-v1"),
                (True, STRUCTURE_FEATURE_VERSION): (
                    "gated grid (price-only-v1+structure-v1)",
                    "price-only-v1+structure-v1",
                ),
                (False, STRUCTURE_FEATURE_VERSION): (
                    "ungated grid baseline (price-only-v1+structure-v1)",
                    "price-only-v1+structure-v1",
                ),
            },
            labels,
        )

    def test_variant_policies_and_names(self):
        cap = D("0.40")
        self.assertIsNone(variant_policy(None))
        self.assertIsNone(variant_name(None))
        self.assertIsNone(variant_name(SimulationPolicy(structure=True)))
        c = {"trend_switch": True, "inventory_cap": cap}
        for variant, policy in (
            ("A", SimulationPolicy(trend_switch=True)),
            ("B", SimulationPolicy(inventory_cap=cap)),
            ("C", SimulationPolicy(**c)),
            ("E", SimulationPolicy(volume_exit=True)),
            ("F", SimulationPolicy(flow_block_entry=True)),
            ("G", SimulationPolicy(funding_gate=True)),
            ("H", SimulationPolicy(cycle_gate=True)),
            ("C+G", SimulationPolicy(**c, funding_gate=True)),
            ("C+H", SimulationPolicy(**c, cycle_gate=True)),
        ):
            with self.subTest(variant=variant):
                self.assertEqual(policy, variant_policy(variant))
                self.assertEqual(variant, variant_name(policy))
                self.assertEqual(
                    replace(policy, structure=True), variant_policy(variant, structure=True)
                )
        self.assertEqual(SimulationPolicy(structure=True), variant_policy(None, structure=True))
        self.assertIn("not the spec", variant_name(SimulationPolicy(inventory_cap=D("0.5"))))
        for undeclared in ("", "D", "A+G", "E+F", "G+H"):
            with self.subTest(undeclared=undeclared), self.assertRaises(ValueError):
                variant_policy(undeclared)

    def test_only_declared_variant_combinations_run(self):
        # Spec v1 §3 and §4: E and F stand alone; G and H run alone or with C (A and B).
        cap = D("0.40")
        for flags in (
            {"volume_exit": True, "trend_switch": True},
            {"volume_exit": True, "inventory_cap": cap},
            {"volume_exit": True, "funding_gate": True},
            {"flow_block_entry": True, "trend_switch": True},
            {"flow_block_entry": True, "volume_exit": True},
            {"funding_gate": True, "trend_switch": True},
            {"funding_gate": True, "inventory_cap": cap},
            {"cycle_gate": True, "trend_switch": True},
            {"cycle_gate": True, "inventory_cap": cap},
            {"funding_gate": True, "cycle_gate": True},
            {"funding_gate": True, "cycle_gate": True, "trend_switch": True, "inventory_cap": cap},
        ):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, "no variant"):
                SimulationPolicy(**flags)
        # The V2 structure flag is not a variant and goes with any of them.
        self.assertEqual("E", SimulationPolicy(volume_exit=True, structure=True).variant)
        self.assertEqual("", SimulationPolicy(structure=True).variant)


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
    """F17/F18: _open_grid passes fta_resistance only in RANGE and only under the V2
    structure policy; full chain."""

    def setUp(self):
        from crypto_grid_bot.domain import MarketRegime, RegimeAssessment

        self.MarketRegime = MarketRegime
        self.RegimeAssessment = RegimeAssessment
        self.config = load_config(ROOT / "config/default.toml")

    def _open_grid_regime(self, regime_value, fta_resistance, structure=True):
        """Open a grid with a specific regime and fta_resistance; return the grid plan used."""
        import contextlib

        policy = SimulationPolicy(structure=structure)
        simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100), policy)
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

    def test_fta_suppressed_without_the_structure_policy(self):
        """V0 (structure off, the default) never caps grid levels, even in RANGE."""
        fta = float(engine_for(hourly(WARMUP)).at(START_MS + WARMUP * HOUR_MS).fair_value) * 1.05
        result = self._open_grid_regime(self.MarketRegime.RANGE, fta, structure=False)
        self.assertIsNone(result)

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


def utc_at(ms):
    return datetime.fromtimestamp(ms / 1000, UTC)


class VolumeExitTests(unittest.TestCase):
    """Variant E's volume check (spec v1 §3 E), on constructed volumes."""

    HOUR = START_MS + 800 * HOUR_MS  # the hour of t0, still open at t0
    START = HOUR + 30 * 60_000  # the minute of t0
    T0 = START + 9_000  # the episode's first outside observation
    END = START + 6 * HOUR_MS  # the measured minutes open in [START, END)

    def hours(self, volume="30"):
        return {START_MS + i * HOUR_MS: D(volume) for i in range(820)}

    def minutes(self, volume="1"):
        return {self.START + i * 60_000: D(volume) for i in range(-60, 420)}

    def check(self, hours=None, minutes=None, observed=None):
        history = VolumeHistory((hours if hours is not None else self.hours()).items())
        for open_ms, volume in (minutes if minutes is not None else self.minutes()).items():
            history.record(open_ms, volume)
        return history.extends(utc_at(self.T0), utc_at(observed or self.END))

    def test_equality_exits_and_below_extends(self):
        # A median of 30: the threshold is 2 x 30 x 6 = 360, over 360 measured minutes.
        self.assertFalse(self.check(minutes=self.minutes("1")))  # 360: equality exits
        self.assertTrue(self.check(minutes=self.minutes("0.999")))
        self.assertFalse(self.check(minutes=self.minutes("1.001")))

    def test_missing_or_degenerate_data_is_unavailable(self):
        hours, minutes = self.hours(), self.minutes("0.999")
        del hours[self.HOUR - 5 * HOUR_MS]
        self.assertIsNone(self.check(hours=hours, minutes=minutes))
        minutes = self.minutes("0.999")
        del minutes[self.START + 100 * 60_000]
        self.assertIsNone(self.check(minutes=minutes))
        self.assertIsNone(self.check(hours=self.hours("0"), minutes=self.minutes("0.999")))
        # A zero-volume measured minute is valid input: 359 x 1 < 360.
        minutes = self.minutes()
        minutes[self.START + 100 * 60_000] = D(0)
        self.assertTrue(self.check(minutes=minutes))

    def test_the_median_of_720_hours_is_the_mean_of_the_two_middle_ones(self):
        hours = self.hours()
        for k in range(720):  # 360 hours of 10 and 360 of 50: a median of 30
            hours[self.HOUR - (k + 1) * HOUR_MS] = D(10 if k % 2 else 50)
        self.assertFalse(self.check(hours=hours, minutes=self.minutes("1")))
        self.assertTrue(self.check(hours=hours, minutes=self.minutes("0.999")))

    def test_no_bar_unfinished_at_t0_or_after_the_span_reaches_the_decision(self):
        # The hour of t0 and every later one, set far up: any read of them moves the
        # median of these distinct reference volumes (1 to 720, a threshold of 4,326)
        # past the measured 4,330.8, which then extends instead of exiting.
        ranked = self.hours()
        for k in range(720):
            ranked[self.HOUR - (k + 1) * HOUR_MS] = D(720 - k)
        minutes = self.minutes("12.03")
        self.assertFalse(self.check(hours=ranked, minutes=minutes))
        later = {o: (D(10**9) if o >= self.HOUR else v) for o, v in ranked.items()}
        later |= {self.HOUR + k * HOUR_MS: D(10**9) for k in range(40)}
        self.assertFalse(self.check(hours=later, minutes=minutes))
        # The minutes from t0 + 6 h on, set far up: any read of them would exit.
        minutes = self.minutes("0.999")
        self.assertTrue(self.check(minutes=minutes))
        after = {o: (D(10**9) if o >= self.END else v) for o, v in minutes.items()}
        after |= {self.END + k * 60_000: D(10**9) for k in range(600)}
        self.assertTrue(self.check(minutes=after))
        # A later decision uses the same span; one before the span has closed has none.
        self.assertTrue(self.check(minutes=after, observed=self.END + 5 * HOUR_MS))
        self.assertIsNone(self.check(minutes=after, observed=self.END - 1))
        # The span's own last minute is read.
        minutes[self.END - 60_000] = D(2)
        self.assertFalse(self.check(minutes=minutes))


class VariantEReplayTests(unittest.TestCase):
    """Variant E through replay(): a grid at minute 0, then 10% below its band."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.candles = hourly(WARMUP)
        self.engine = engine_for(self.candles)
        self.t = START_MS + WARMUP * HOUR_MS
        self.run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))

    def minutes(self, volume="1000000", taker="500000", later=None):
        """Minute 0 at fair value, then 800 minutes 10% lower: t0 is minute 1's open, so
        the measured span is minutes 1 to 360. ``later`` is the volume from minute 361."""
        fair = float(self.engine.at(self.t).fair_value)
        low = fair * 0.9
        bars = [candle(self.t, fair, fair * 1.001, fair * 0.999, fair)]
        for i in range(1, 801):
            v, k = (later, "0") if later and i >= 361 else (volume, taker)
            bars.append(candle(self.t + i * 60_000, low, low * 1.001, low * 0.999, low, v, k))
        return bars

    def replay(self, minutes, policy=None, hourly=None):
        metrics, account = replay(
            self.config,
            self.run,
            minutes,
            self.engine,
            policy,
            hourly=self.candles if hourly is None else hourly,
        )
        self.assertEqual([], check_accounting(self.run, metrics, account))
        return metrics, account

    def exit_at(self, minute):
        return utc_at(self.t + minute * 60_000).isoformat()

    def assertAsV0(self, minutes, outcome, hourly=None):
        v0, v0_account = self.replay(minutes)
        e, e_account = self.replay(minutes, SimulationPolicy(volume_exit=True), hourly)
        self.assertEqual({"volume_exit_checks": {outcome: 1}}, e.variant_counts)
        self.assertEqual(asdict(v0), asdict(replace(e, variant_counts={})))
        self.assertEqual(v0_account.to_dict(), e_account.to_dict())
        self.assertEqual(self.exit_at(361), e_account.range_exit_since)

    def test_low_volume_extends_the_exit_from_6_to_12_hours(self):
        minutes = self.minutes("1", "0")
        _, v0 = self.replay(minutes)
        self.assertEqual(self.exit_at(361), v0.range_exit_since)
        e, account = self.replay(minutes, SimulationPolicy(volume_exit=True))
        self.assertEqual({"volume_exit_checks": {"extended": 1}}, e.variant_counts)
        self.assertEqual(self.exit_at(721), account.range_exit_since)
        # Volume from t0 + 6 h on, however large, cannot reach the decision.
        late, late_account = self.replay(
            self.minutes("1", "0", later="1000000000"), SimulationPolicy(volume_exit=True)
        )
        self.assertEqual(e.variant_counts, late.variant_counts)
        self.assertEqual(self.exit_at(721), late_account.range_exit_since)

    def test_volume_at_or_above_the_threshold_exits_as_v0(self):
        self.assertAsV0(self.minutes(), "exit")

    def test_a_missing_reference_hour_or_measured_minute_exits_as_v0(self):
        low = self.minutes("1", "0")
        gap = [c for c in self.candles if c.open_ms != self.t - 100 * HOUR_MS]
        self.assertAsV0(low, "unavailable", hourly=gap)
        self.assertAsV0([b for i, b in enumerate(low) if i != 100], "unavailable")

    def test_v0_ignores_the_hourly_history_and_e_refuses_to_run_without_it(self):
        minutes = self.minutes("1", "0")
        v0 = replay(self.config, self.run, minutes, self.engine)
        with_hourly = replay(self.config, self.run, minutes, self.engine, hourly=self.candles)
        self.assertEqual(asdict(v0[0]), asdict(with_hourly[0]))
        self.assertEqual({}, v0[0].variant_counts)
        with self.assertRaisesRegex(ValueError, "hourly history"):
            replay(self.config, self.run, minutes, self.engine, SimulationPolicy(volume_exit=True))


class OrderFlowTests(unittest.TestCase):
    """Variant F's taker-buy share and its block (spec v1 §3 F)."""

    MINUTE = START_MS + 100 * 60_000  # the decision's minute

    def bars(self, takers, volume="1000", end=None):
        """One bar per minute up to ``end`` (default: the decision's minute), oldest first."""
        end = self.MINUTE if end is None else end
        first = end - len(takers) * 60_000
        return [
            candle(first + i * 60_000, 1, 1, 1, 1, volume=volume, taker=taker)
            for i, taker in enumerate(takers)
        ]

    def test_the_share_of_the_fifteen_minutes_before(self):
        self.assertEqual(D("0.5"), taker_buy_share(self.bars(["500"] * 15), self.MINUTE))
        self.assertEqual(D("0.4"), taker_buy_share(self.bars(["400"] * 15), self.MINUTE))
        older = self.bars(["0"] * 5 + ["500"] * 15)  # bars before the fifteen are not read
        self.assertEqual(D("0.5"), taker_buy_share(older, self.MINUTE))

    def test_a_missing_minute_is_unavailable_and_a_zero_volume_minute_is_not(self):
        bars = self.bars(["500"] * 15)
        self.assertIsNone(taker_buy_share(bars[1:], self.MINUTE))  # fourteen
        self.assertIsNone(taker_buy_share(bars[:7] + bars[8:], self.MINUTE))  # a gap
        stale = self.bars(["500"] * 15, end=self.MINUTE - 60_000)
        self.assertIsNone(taker_buy_share(stale, self.MINUTE))  # the latest is missing
        zero = candle(bars[7].open_ms, 1, 1, 1, 1, volume="0", taker="0")
        self.assertEqual(D("0.5"), taker_buy_share(bars[:7] + [zero] + bars[8:], self.MINUTE))
        self.assertIsNone(taker_buy_share(self.bars(["0"] * 15, volume="0"), self.MINUTE))
        # The decision's own minute is never read: given, it makes the share unavailable.
        current = candle(self.MINUTE, 1, 1, 1, 1, volume="1000", taker="1000")
        self.assertIsNone(taker_buy_share([*bars, current], self.MINUTE))

    def test_the_block_turns_on_below_040_and_off_from_045(self):
        for blocked, share, expected in (
            (False, D("0.40"), False),  # 0.40 is not below 0.40
            (True, D("0.40"), True),  # in the band the flag keeps its state
            (True, D("0.4499"), True),
            (False, D("0.4499"), False),
            (True, D("0.45"), False),  # 0.45 turns it off
            (False, D("0.3999"), True),
            (False, None, True),  # unavailable blocks
        ):
            with self.subTest(blocked=blocked, share=share):
                self.assertEqual(expected, flow_blocked(blocked, share))


class VariantFEngineTests(unittest.TestCase):
    """Variant F's block in the engine: cancellations, fragments, other pauses."""

    F = SimulationPolicy(flow_block_entry=True)

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100), self.F)
        self.account = self.simulator.store.read()
        self.simulator.close()  # step() uses no store
        self.inputs = engine_for(hourly(WARMUP)).at(START_MS + WARMUP * HOUR_MS)

    def frames(self, minute, share, candidate=None):
        """The four frames of a flat minute bar at fair value, ``minute`` after warm-up."""
        open_ms = START_MS + WARMUP * HOUR_MS + minute * 60_000
        fair = float(self.inputs.fair_value)
        bar = candle(open_ms, fair, fair, fair, fair)
        signals = signals_for(self.inputs, utc_at(open_ms), gated=False)
        candidate = candidate or candidate_for(self.inputs, "TESTUSDT", 0.05, 1e9, gated=False)
        return [
            Frame(
                quote,
                signals,
                candidate,
                self.inputs.fair_value,
                self.inputs.atr,
                True,
                f"TESTUSDT/{open_ms}",
                flow_share=share,
            )
            for quote in bar_quotes(bar, "TESTUSDT", "low_first", D("0.0005"), RULES.tick_size)
        ]

    def step(self, frames):
        return [self.simulator.step(self.account, frame) for frame in frames]

    def partly_filled_buy(self, key, quantity, filled):
        price = D("1.0000")
        self.account.cash -= filled * price * (1 + RULES.fee_rate)
        self.account.inventory += filled
        self.account.orders[key] = LimitOrder(
            key, "buy", price, quantity, quantity - filled, target=D("1.1000")
        )

    def test_a_cancelled_partial_fill_gets_its_sell_and_fragments_wait_for_the_minimum(self):
        (frame, *_) = self.frames(0, None)
        # 5 filled at a target of 1.1 is 5.5, above the minimum notional of 5: one sell.
        self.partly_filled_buy("a/buy/0", D(10), D(5))
        # 0.1 filled is 0.11 there: it waits as a fragment.
        self.partly_filled_buy("b/buy/0", D(1), D("0.1"))
        self.account.validate(RULES)
        self.simulator._block_buys(self.account, frame)
        sell = self.account.orders["a/buy/0/fragment"]
        self.assertEqual(
            ("sell", D("1.1000"), D(5), D("1.0000"), frame.epoch),
            (sell.side, sell.price, sell.quantity, sell.reentry, sell.epoch),
        )
        self.assertEqual({D("1.1"): D("0.1")}, self.account.flow_fragments)
        self.assertEqual(["a/buy/0/fragment"], list(self.account.orders))
        # 4.5 more for the same target: 4.6 x 1.1 = 5.06, so one sell for both.
        self.partly_filled_buy("c/buy/0", D(5), D("4.5"))
        self.simulator._block_buys(self.account, frame)
        self.assertEqual(D("4.6"), self.account.orders["c/buy/0/fragment"].quantity)
        self.assertEqual({}, self.account.flow_fragments)
        self.account.validate(RULES)

    def test_fragments_an_exit_has_sold_are_ordinary_inventory_again(self):
        (frame, *_) = self.frames(0, None)
        self.account.flow_fragments[D("1.1")] = D(3)  # held by nothing: an exit sold it
        self.partly_filled_buy("a/buy/0", D(1), D("0.1"))
        self.simulator._block_buys(self.account, frame)
        self.assertEqual({D("1.1"): D("0.1")}, self.account.flow_fragments)
        self.assertFalse(self.account.orders)

    def test_a_block_cancels_every_resting_buy_and_counts_the_cancellations(self):
        orders = self.account.orders = RequestCountingOrders()
        opened = self.step(self.frames(0, D("0.5")))
        self.assertTrue(any(report["opened"] for report in opened))
        buys = sorted(k for k, o in self.account.orders.items() if o.side == "buy")
        before = orders.requests
        (report, *_) = self.step(self.frames(1, D("0.3")))
        self.assertEqual(len(buys), orders.requests - before)
        self.assertEqual(buys, report["cancelled"])
        self.assertFalse(self.account.orders)
        self.assertTrue(self.account.flow_block)

    def test_the_block_starts_on_and_unblocking_lifts_only_fs_restriction(self):
        (report, *_) = self.step(self.frames(0, D("0.42")))  # in the band: stays blocked
        self.assertEqual(
            ("cash", "order flow: buys blocked"), (report["decision"], report["reason"])
        )
        # Unblocked while a V0 eligibility pause is on: the pause stays, and no grid.
        poor = replace(candidate_for(self.inputs, "TESTUSDT", 0.05, 1e9, gated=False), spread_pct=1)
        reports = self.step(self.frames(1, D("0.5"), poor))
        self.assertFalse(self.account.flow_block)
        self.assertEqual({"pause"}, {r["decision"] for r in reports})
        self.assertFalse(self.account.orders)
        # Eligible again: the pause clears after its confirmations, and a grid opens.
        reports = self.step(self.frames(2, D("0.5")))
        self.assertTrue(any(r["opened"] for r in reports))


class VariantFReplayTests(unittest.TestCase):
    """Variant F through replay() on synthetic minutes (spec v1 §3 F)."""

    F = SimulationPolicy(flow_block_entry=True)

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.engine = engine_for(hourly(WARMUP))
        self.t = START_MS + WARMUP * HOUR_MS
        self.fair = float(self.engine.at(self.t).fair_value)
        self.run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))

    def minutes(self, count, taker="500000", start=0, price=None):
        price = price or self.fair
        return [
            candle(self.t + i * 60_000, price, price * 1.001, price * 0.999, price, taker=taker)
            for i in range(start, start + count)
        ]

    def replay(self, minutes, policy=F):
        metrics, account = replay(self.config, self.run, minutes, self.engine, policy)
        self.assertEqual([], check_accounting(self.run, metrics, account))
        return metrics, account

    def test_f_fails_closed_until_fifteen_minutes_are_known_and_while_the_share_is_low(self):
        self.assertEqual(0, self.replay(self.minutes(15))[0].grids_opened)
        self.assertEqual(1, self.replay(self.minutes(16))[0].grids_opened)
        low, _ = self.replay(self.minutes(30, taker="300000"))
        self.assertEqual(0, low.grids_opened)
        self.assertIn("cash: order flow: buys blocked", low.reasons)

    def test_the_current_minute_never_changes_its_own_block_state(self):
        def seen(minutes):
            states, real_step = [], PaperSimulator.step

            def recording(simulator, account, frame):
                report = real_step(simulator, account, frame)
                states.append((frame.epoch, frame.flow_share, account.flow_block))
                return report

            with patch.object(PaperSimulator, "step", recording):
                self.replay(minutes)
            return states

        base = self.minutes(30)
        changed = list(base)  # minute 20: ten times the volume, none of it taker-bought
        changed[20] = replace(base[20], volume=D(10**7), taker_buy_base=D(0))
        before, after = seen(base), seen(changed)
        minute_20, minute_21 = slice(80, 84), slice(84, 88)  # four frames per minute
        self.assertEqual(before[minute_20], after[minute_20])
        # From the next minute on, the changed bar is part of the share, and blocks.
        self.assertNotEqual(before[minute_21], after[minute_21])
        self.assertTrue(all(blocked for _, _, blocked in after[minute_21]))

    def test_a_range_exit_still_happens_while_buys_are_blocked(self):
        # The grid opens at minute 15; from minute 30 the price is 10% below its band and
        # the share is low, so F blocks. The range exit still comes 6 h later, as V0's.
        minutes = self.minutes(30)
        minutes += self.minutes(400, taker="100000", start=30, price=self.fair * 0.9)
        _, v0 = self.replay(minutes, None)
        metrics, account = self.replay(minutes)
        self.assertEqual(utc_at(self.t + 390 * 60_000).isoformat(), account.range_exit_since)
        self.assertEqual(v0.range_exit_since, account.range_exit_since)
        self.assertEqual(1, metrics.range_exits)


class VariantGTests(unittest.TestCase):
    """Variant G through replay(), with constructed funding records (spec v1 §3 G)."""

    G = SimulationPolicy(funding_gate=True)

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.engine = engine_for(hourly(WARMUP))
        self.t = START_MS + WARMUP * HOUR_MS
        fair = float(self.engine.at(self.t).fair_value)
        self.minutes = [candle(self.t + i * 60_000, fair, fair, fair, fair) for i in range(30)]
        self.run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))

    def signal(self, rate):
        """Settlements 24, 16 and 8 hours before the first minute, 11 ms past the hour:
        uniform, and overdue from a minute after it."""
        hours = (24, 16, 8)
        return FundingSignal(FundingRecord(self.t - h * HOUR_MS + 11, 8, D(rate)) for h in hours)

    def replay(self, minutes, policy=G, funding=None):
        metrics, account = replay(
            self.config, self.run, minutes, self.engine, policy, funding=funding
        )
        self.assertEqual([], check_accounting(self.run, metrics, account))
        return metrics, account

    def test_high_or_unavailable_funding_blocks_a_new_grid(self):
        for rate, opened in (
            ("0.001", 0),  # all three above +0.0005
            ("0.0005", 1),  # exactly +0.0005 is not above it
            ("-0.001", 1),
        ):
            with self.subTest(rate=rate):
                metrics, _ = self.replay(self.minutes[:1], funding=self.signal(rate))
                self.assertEqual(opened, metrics.grids_opened)
        # No history at all is unavailable: G fails closed.
        metrics, _ = self.replay(self.minutes[:1], funding=FundingSignal([]))
        self.assertEqual(0, metrics.grids_opened)
        self.assertIn("cash: funding gate: funding high or unavailable", metrics.reasons)
        with self.assertRaisesRegex(ValueError, "funding history"):
            replay(self.config, self.run, self.minutes, self.engine, self.G)

    def test_existing_grids_and_exits_are_unaffected(self):
        # Clear at minute 0, so the grid opens as in V0; overdue from minute 1, so G
        # blocks from then on. The grid's fills and its range exit 6 h after leaving the
        # band are V0's, exactly.
        low = float(self.engine.at(self.t).fair_value) * 0.9
        minutes = self.minutes + [
            candle(self.t + i * 60_000, low, low * 1.001, low * 0.999, low) for i in range(30, 430)
        ]
        funding = self.signal("0.0001")
        self.assertTrue(funding.state(self.t).available)
        self.assertEqual("overdue", funding.state(self.t + 60_000).reason)
        v0, v0_account = self.replay(minutes, None)
        g, g_account = self.replay(minutes, funding=funding)
        self.assertEqual(asdict(v0), asdict(g))
        self.assertEqual(v0_account.to_dict(), g_account.to_dict())
        self.assertEqual(1, g.range_exits)

    def test_funding_archives_load_from_the_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            path = funding_local_path(data, "BTCUSDT", "2024-01")
            path.parent.mkdir(parents=True)
            rows = "".join(f"{1704067200011 + h * HOUR_MS},8,0.0001\n" for h in (0, 8, 16))
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "BTCUSDT-fundingRate-2024-01.csv",
                    "calc_time,funding_interval_hours,last_funding_rate\n" + rows,
                )
            missing = {"kind": "fundingRate", "symbol": "BTCUSDT", "month": "2024-02"}
            files = [
                {"kind": "fundingRate", "symbol": "BTCUSDT", "month": "2024-01", "status": "ok"},
                missing | {"status": "missing"},
                {"kind": "fundingRate", "symbol": "ETHUSDT", "month": "2024-01", "status": "ok"},
                {"symbol": "BTCUSDT", "interval": "1h", "month": "2024-01", "status": "ok"},
            ]
            signal = load_funding(data, {"files": files}, "BTCUSDT")
        usable = 1704067200000 + 16 * HOUR_MS + 60_000  # the third record's publication
        self.assertFalse(signal.state(usable - 1000).available)
        self.assertEqual("clear", signal.state(usable).reason)
        empty = load_funding(Path("."), {"files": []}, "BTCUSDT")
        self.assertFalse(empty.state(usable).available)


class RuntimeVariantPaperTests(unittest.TestCase):
    """E and F keep runtime account state that is never saved, so they run in replay
    only (spec v1 §3; docs/PAPER_SIMULATION.md)."""

    def test_a_paper_account_refuses_e_and_f_and_runs_g_and_h(self):
        config, frame = load_config(ROOT / "config/default.toml"), demo_frames(1)[0]
        for policy, refused in (
            (SimulationPolicy(volume_exit=True), True),
            (SimulationPolicy(flow_block_entry=True), True),
            (SimulationPolicy(funding_gate=True), False),
            (SimulationPolicy(cycle_gate=True), False),
        ):
            with self.subTest(variant=policy.variant), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "paper.db"
                simulator = PaperSimulator(path, config, MarketRules(), policy=policy)
                try:
                    if refused:
                        with self.assertRaisesRegex(ValueError, "historical replay only"):
                            simulator.process(frame)
                        with self.assertRaisesRegex(ValueError, "historical replay only"):
                            simulator.resume(frame, event_id="e1", reason="test")
                    else:
                        simulator.process(frame)
                finally:
                    simulator.close()

    def test_runtime_state_is_never_saved(self):
        account = Account.start(D(100))
        saved = set(account.to_dict())
        account.volume_since, account.volume_extended = "2024-01-01T00:00:00+00:00", True
        account.flow_block, account.flow_fragments = False, {D("1.1"): D("0.1")}
        self.assertEqual(saved, set(account.to_dict()))
