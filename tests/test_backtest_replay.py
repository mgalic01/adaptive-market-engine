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
    DAY_MS,
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
from crypto_grid_bot.domain import CandidateMetrics, MarketRegime, MarketSignals, RegimeAssessment
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import exit_state, match, place, reduce_unreserved
from crypto_grid_bot.simulation.models import (
    Account,
    LimitOrder,
    MarketRules,
    Quote,
    floor_step,
    timestamp,
)
from crypto_grid_bot.simulation.runner import Frame, PaperSimulator, SimulationPolicy
from crypto_grid_bot.strategy.grid import GridNotViable
from crypto_grid_bot.strategy.order_flow import flow_blocked, taker_buy_share
from crypto_grid_bot.strategy.structure import ResistanceZones, nearest_resistance
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
# An hour index that opens a UTC day, where the daily resistance of zone_days() appears.
ZONE_MIDNIGHT = (WARMUP // 24 + 2) * 24
ZONE_MIDNIGHT_MS = START_MS + ZONE_MIDNIGHT * HOUR_MS


def zone_candles():
    """The pair's hourly candles with a two-hour hole across ZONE_MIDNIGHT_MS: the latest
    completed candle does not change there while a daily bar does, so a cache keyed on
    the pair alone would serve the previous day's structure."""
    hole = (ZONE_MIDNIGHT - 1, ZONE_MIDNIGHT)
    return [c for i, c in enumerate(hourly(WARMUP + 72)) if i not in hole]


def zone_days():
    """Flat days below fair value, except one high at 1.03 four days before
    ZONE_MIDNIGHT_MS: the day closing at that midnight is the third after it, which
    confirms it as a swing high, so a resistance zone above fair value appears exactly
    then."""
    rng = random.Random(158)
    days = []
    for d in range(-60, 45):
        open_ms, close = START_MS + d * DAY_MS, 0.97 + rng.uniform(-0.005, 0.005)
        high = 1.03 if open_ms == ZONE_MIDNIGHT_MS - 4 * DAY_MS else close * 1.005
        days.append(candle(open_ms, close, high, close * 0.995, close))
    return days


def unseen_days_changed(days, minute):
    """The ``days`` closed by ``minute``, and the same with every other day changed beyond
    recognition plus days that do not exist yet: none of that may reach the decision."""
    completed = [d for d in days if d.open_ms + DAY_MS <= minute]
    future = [
        replace(d, high=d.high * 5, low=d.low / 5, close=d.close * 3)
        for d in days
        if d.open_ms + DAY_MS > minute
    ]
    later = [candle(days[-1].open_ms + k * DAY_MS, 9.0, 9.9, 8.1, 9.5) for k in range(1, 30)]
    return completed, completed + future + later


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
        candles, days, midnight_ms = zone_candles(), zone_days(), ZONE_MIDNIGHT_MS

        def structure_engine(daily):
            return engine_for(candles, hourly_candles=candles, daily_bars=daily)

        engine = structure_engine(days)  # one engine, queried in order: its caches
        start = midnight_ms - 30 * HOUR_MS
        minutes = [*range(start, start + 60 * HOUR_MS, 20 * 60_000)]
        minutes += [midnight_ms + k * 60_000 for k in (-1, 0, 1)]
        for minute in sorted(minutes):
            completed, changed = unseen_days_changed(days, minute)
            expected = structure_engine(completed).at(minute)
            self.assertEqual(expected, structure_engine(changed).at(minute))
            self.assertEqual(expected, engine.at(minute), minute)
        # The completed days are in use, from the minute the confirming day closes: the
        # nearest resistance above fair value appears then, in reach.
        before, after = engine.at(midnight_ms - 60_000), engine.at(midnight_ms)
        self.assertEqual(before.hour_open_ms, after.hour_open_ms)  # inside the hole
        self.assertIsNone(nearest_resistance(float(before.fair_value), before.resistance))
        nearest = nearest_resistance(float(after.fair_value), after.resistance)
        self.assertEqual((1.03, True), nearest)

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
            self.assertNotEqual((), inputs.resistance)

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
                    "gated grid (price-only-v1+structure-v2)",
                    "price-only-v1+structure-v2",
                ),
                (False, STRUCTURE_FEATURE_VERSION): (
                    "ungated grid baseline (price-only-v1+structure-v2)",
                    "price-only-v1+structure-v2",
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
        for undeclared in ("", "D", "A+G", "E+F", "G+H", "C+F+G+H+V2", "C+E+F+G+H"):
            with self.subTest(undeclared=undeclared), self.assertRaises(ValueError):
                variant_policy(undeclared)

    def test_the_full_stack_is_c_f_g_and_h_with_the_structure_features(self):
        # Spec v1 §3 (test-plan amendment, 2026-10-05): C+F+G+H+V2, which E is not in.
        full = SimulationPolicy(
            trend_switch=True,
            inventory_cap=D("0.40"),
            flow_block_entry=True,
            funding_gate=True,
            cycle_gate=True,
            structure=True,
        )
        self.assertEqual(full, variant_policy("C+F+G+H", structure=True))
        self.assertEqual("C+F+G+H", full.variant)
        self.assertEqual("C+F+G+H", variant_name(full))
        # Its identity adds every part's flag to V0's, and nothing else.
        added = set(full.identity()) - set(SimulationPolicy().identity())
        self.assertEqual(
            {
                "inventory_cap",
                "trend_switch",
                "flow_block_entry",
                "funding_gate",
                "cycle_gate",
                "structure",
            },
            added,
        )
        self.assertNotIn("volume_exit", full.identity())
        # Without the structure features it is not the declared combination.
        with self.assertRaisesRegex(ValueError, "no variant C\\+F\\+G\\+H without"):
            variant_policy("C+F+G+H")

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
        # The full stack is declared with the V2 structure flag only, and exactly as
        # C+F+G+H: a part missing, E added or C split is refused, structure or not.
        full = {"trend_switch": True, "inventory_cap": cap, "flow_block_entry": True}
        full |= {"funding_gate": True, "cycle_gate": True}
        for flags in (
            full,
            {**full, "volume_exit": True, "structure": True},
            {**full, "trend_switch": False, "structure": True},
            {**full, "inventory_cap": None, "structure": True},
            {**full, "flow_block_entry": False, "structure": True},
            {**full, "funding_gate": False, "structure": True},
            {**full, "cycle_gate": False, "structure": True},
        ):
            with self.subTest(flags=flags), self.assertRaisesRegex(ValueError, "no variant"):
                SimulationPolicy(**flags)
        self.assertEqual("C+F+G+H", SimulationPolicy(**full, structure=True).variant)
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

    def test_exit_reasons_reconcile_within_the_simulators_rounding(self):
        # The full-range formal runs (2026-10-07): each reason's exit P&L and the exit total
        # are summed at the simulator's precision (50 digits), fill by fill, so with two
        # reasons the two sums round differently, here by 1e-46. An exact comparison failed
        # every such run; the tolerance is the P&L reconciliation's (P6), 1e-18.
        minutes = self.flat(0, 60, self.fair) + self.flat(60, 540, self.fair * 0.95)
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        metrics, account = replay(self.config, run, minutes, self.engine)
        total = metrics.exit_pnl_by_reason["range_exit"]
        metrics.exit_pnl_by_reason = {"range_exit": total + D("1e-45"), "liquidation": D("-9e-46")}
        self.assertEqual([], check_accounting(run, metrics, account))
        # A real gap still fails.
        metrics.exit_pnl_by_reason = {"range_exit": total, "liquidation": D("-0.000001")}
        self.assertEqual(
            ["exit P&L by reason does not sum to the exit total"],
            check_accounting(run, metrics, account),
        )

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


class DocumentedDailyDefectTests(unittest.TestCase):
    """Owner decision 14 (2026-10-07), as narrowed on review: on 2021-01-21, a documented
    Binance volume defect, the daily check excuses only the volume. The day's prices are
    still compared with its 24 hours, so the premise of the grant (identical prices) is
    checked on every run. A record with a mismatch names the mismatched days. Synthetic
    bars only."""

    DAY = 86_400_000
    DEFECT = int(datetime(2021, 1, 21, tzinfo=UTC).timestamp() * 1000)
    START = DEFECT - DAY  # three days: 2021-01-20, the listed 21st and the 22nd
    # The fields a daily record had before this decision; neither new key is among them.
    FIELDS = {
        "daily_days_compared",
        "daily_days_mismatched",
        "daily_days_volume_drift",
        "daily_days_missing",
        "daily_days_duplicated",
        "daily_days_hours_incomplete",
        "daily_warmup_days",
        "daily_warmup_short",
    }

    def bars(self, start=START):
        from crypto_grid_bot.backtest.klines import aggregate

        hours = hourly(72, start_ms=start)
        return list(aggregate(hours, self.DAY)), hours

    def check(self, daily, hours, hourly_start=START, tolerance=None, masked_days=frozenset()):
        end = self.START + 3 * self.DAY
        return cross_check_daily(
            daily,
            hours,
            (self.START, end),
            (hourly_start, end),
            end,
            tolerance,
            masked_days=masked_days,
        )

    @staticmethod
    def short_volume(bar):
        """``bar`` with 2.4% less volume and its prices unchanged, as Bob's defect calendar
        found BTCUSDT's official 1d bar of 2021-01-21 against its 24 hours (131803.182926
        against 135004.076658)."""
        return replace(bar, volume=bar.volume * D("0.976"))

    def test_the_listed_days_volume_is_excused_and_counted(self):
        from crypto_grid_bot.backtest.replay import DOCUMENTED_DAILY_DEFECTS

        self.assertEqual(["2021-01-21"], list(DOCUMENTED_DAILY_DEFECTS))
        reason = DOCUMENTED_DAILY_DEFECTS["2021-01-21"]
        self.assertNotIn("\n", reason)
        self.assertIn("2026-09-26-bob-hourly-defect-calendar.md", reason)
        self.assertIn("2026-10-07-claude-v2-decisions-after-first-read.md", reason)
        daily, hours = self.bars()
        clean = self.check(daily, hours)
        daily[1] = self.short_volume(daily[1])
        result = self.check(daily, hours)
        # The day is compared: its prices equal its hours', so its volume is excused,
        # counted neither as a mismatch nor as drift.
        self.assertEqual(
            {
                "daily_days_compared": 3,
                "daily_days_mismatched": 0,
                "daily_days_volume_drift": 0,
                "daily_days_missing": 0,
                "daily_days_duplicated": 0,
                "daily_days_hours_incomplete": 0,
                "daily_warmup_days": 3,
                "daily_warmup_short": 1,
                "daily_days_volume_excused": 1,
            },
            result,
        )
        # Whatever its volume: a bar that agrees in full is excused alike.
        self.assertEqual(result, clean)
        # With strict volume (--strict-volume) as well.
        self.assertEqual(result, self.check(daily, hours, tolerance=D(0)))
        # The day goes through the presence and completeness checks like any other: a
        # missing bar is missing, a duplicated one duplicated, and a missing hour makes
        # the day incomplete. A day not compared is not excused.
        without = self.check([daily[0], daily[2]], hours)
        self.assertEqual(1, without["daily_days_missing"])
        self.assertEqual(2, without["daily_days_compared"])
        self.assertNotIn("daily_days_volume_excused", without)
        twice = self.check([*daily, daily[1]], hours)
        self.assertEqual(1, twice["daily_days_duplicated"])
        gap = self.check(daily, hours[:30] + hours[31:])  # one hour of the 21st absent
        self.assertEqual(1, gap["daily_days_hours_incomplete"])
        self.assertEqual(2, gap["daily_days_compared"])
        self.assertNotIn("daily_days_volume_excused", gap)

    def test_a_price_difference_on_the_listed_day_is_a_named_mismatch(self):
        """Only the volume is excused. A price that differs from the 24 hours' on the
        listed day is a mismatch as on any other day, named 2021-01-21, so a 1d price
        error that day fails its pair. Bob's calendar shows identical prices that day only
        for BTCUSDT and DOGEUSDT; every run now checks it for each pair."""
        daily, hours = self.bars()
        bar = self.short_volume(daily[1])
        moved = {
            "open": replace(bar, open=bar.open + D("0.0001")),
            "high": replace(bar, high=bar.high + D("0.0001")),
            "low": replace(bar, low=bar.low - D("0.0001")),
            "close": replace(bar, close=bar.close + D("0.0001")),
        }
        for field, changed in moved.items():
            for tolerance in (None, D(0)):
                with self.subTest(field=field, strict=tolerance is not None):
                    result = self.check([daily[0], changed, daily[2]], hours, tolerance=tolerance)
                    self.assertEqual(1, result["daily_days_mismatched"])
                    self.assertEqual(["2021-01-21"], result["daily_mismatched_days"])
                    self.assertEqual(0, result["daily_days_volume_drift"])
                    self.assertEqual(3, result["daily_days_compared"])
                    self.assertNotIn("daily_days_volume_excused", result)

    def test_the_same_difference_on_another_day_fails_and_is_named(self):
        daily, hours = self.bars()
        for index, name in ((0, "2021-01-20"), (2, "2021-01-22")):
            with self.subTest(name):
                bad = list(daily)
                bad[index] = self.short_volume(bad[index])
                result = self.check(bad, hours)
                self.assertEqual(1, result["daily_days_mismatched"])
                self.assertEqual([name], result["daily_mismatched_days"])
                self.assertEqual(3, result["daily_days_compared"])
                self.assertEqual(1, result["daily_days_volume_excused"])
        # Every mismatched day is named, in date order; a drift within the tolerance is
        # not a mismatch and is not named.
        bad = [self.short_volume(daily[0]), daily[1], self.short_volume(daily[2])]
        result = self.check(bad, hours)
        self.assertEqual(2, result["daily_days_mismatched"])
        self.assertEqual(["2021-01-20", "2021-01-22"], result["daily_mismatched_days"])
        drift = [replace(daily[0], volume=daily[0].volume * D("1.001")), *daily[1:]]
        result = self.check(drift, hours)
        self.assertEqual(1, result["daily_days_volume_drift"])
        self.assertEqual(0, result["daily_days_mismatched"])
        self.assertNotIn("daily_mismatched_days", result)
        # In a window without the listed day, a mismatch is named the same way.
        early, early_hours = self.bars(start=START_MS)
        early[1] = replace(early[1], close=early[1].close + D("0.0001"))
        window = (START_MS, START_MS + 3 * self.DAY)
        result = cross_check_daily(early, early_hours, window, window, window[1])
        self.assertEqual(["2024-01-02"], result["daily_mismatched_days"])
        self.assertNotIn("daily_days_volume_excused", result)

    def test_a_masked_listed_day_takes_the_masked_path(self):
        # A listed day that also holds a masked hour is skipped and counted as masked, as
        # before, so daily_days_skipped_for_masks stays the count
        # jobs.skipped_days_for_masks gives.
        daily, hours = self.bars()
        daily[1] = replace(self.short_volume(daily[1]), high=daily[1].high + D(1))
        result = self.check(daily, hours, masked_days=frozenset({self.DEFECT}))
        self.assertEqual(1, result["daily_days_skipped_for_masks"])
        self.assertNotIn("daily_days_volume_excused", result)
        self.assertEqual((2, 0), (result["daily_days_compared"], result["daily_days_mismatched"]))

    def test_stage_1_like_records_carry_neither_new_key(self):
        # Stage 1's daily windows start in 2020-05 and hold 2021-01-21, but their hourly
        # windows start in 2022-04 and 2023-11: the day is checked for presence only, never
        # compared, so it is neither excused nor counted, whatever its bar.
        from crypto_grid_bot.backtest.dataset import load_spec
        from crypto_grid_bot.backtest.jobs import hourly_window
        from crypto_grid_bot.backtest.klines import month_bounds_ms

        for name in ("practice-2022", "verify-2024h1"):
            with self.subTest(name):
                spec = load_spec(ROOT / "config" / "datasets" / f"{name}.toml")
                self.assertLess(month_bounds_ms(spec.daily_warmup_start)[0], self.DEFECT)
                self.assertGreater(hourly_window(spec)[0], self.DEFECT)
        daily, hours = self.bars()
        daily[1] = replace(self.short_volume(daily[1]), high=daily[1].high + D(1))
        later = self.START + 2 * self.DAY
        result = self.check(daily, hours, hourly_start=later)
        self.assertEqual(self.FIELDS, set(result))
        self.assertEqual(1, result["daily_days_compared"])  # the 22nd alone
        self.assertEqual(0, result["daily_days_mismatched"])
        self.assertEqual(0, result["daily_days_missing"])
        # A clean window without the day carries neither key either.
        clean, clean_hours = self.bars(start=START_MS)
        window = (START_MS, START_MS + 3 * self.DAY)
        self.assertEqual(
            self.FIELDS, set(cross_check_daily(clean, clean_hours, window, window, window[1]))
        )


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


# ---------------------------------------------------------------------------
# V2 sell targets below resistance (owner decision D19) — 2026-10-05
# ---------------------------------------------------------------------------


class SellAtResistanceTests(unittest.TestCase):
    """D19: under the V2 structure policy, in a ranging market, each buy level's sell
    target sits just below the nearest resistance above it (synthetic numbers).

    Fair value 1 and ATR 0.05 give V0's eight levels 0.9, 0.9261, 0.9531, 0.9808, 1.0093,
    1.0387, 1.0689 and 1.1. The four below the 1.0000 bid are the buy levels, each
    targeting the next level (``GEOMETRIC``). Costs are 2 x (0.1% + 0.05%) plus the 0.05%
    spread, so a target must lie at least 1.05% above its buy level.
    """

    GEOMETRIC = [
        (D("0.9"), D("0.9261")),
        (D("0.9261"), D("0.9531")),
        (D("0.9531"), D("0.9808")),
        (D("0.9808"), D("1.0093")),
    ]
    # A daily zone at 1.03, searched within 0.08: 1.03 x 0.999 floors to 1.0289.
    RAISED = [*GEOMETRIC[:2], (D("0.9531"), D("1.0289")), (D("0.9808"), D("1.0289"))]

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")

    def open_grid(
        self, resistance, *, structure=True, regime=MarketRegime.RANGE, fair=D(1), atr=D("0.05")
    ):
        """A fresh 100-unit account after ``_open_grid`` on one frame at fair value."""
        policy = SimulationPolicy(structure=structure)
        self.simulator = PaperSimulator(Path(":memory:"), self.config, RULES, D(100), policy)
        account = self.simulator.store.read()
        self.simulator.close()
        when = datetime.fromtimestamp(START_MS / 1000, UTC)
        stamp, size = when.isoformat(), D(10**6)
        quote = Quote(
            "TESTUSDT/grid", "TESTUSDT", stamp, stamp, fair, fair + D("0.0005"), size, size
        )
        signals = MarketSignals(0.0, 0.0, 0.0, 0.0, 0.0, 10.0, observed_at=when)
        candidate = CandidateMetrics("TESTUSDT", 1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.05, 1e9)
        self.frame = Frame(quote, signals, candidate, fair, atr, resistance=resistance)
        self.simulator._open_grid(account, self.frame, [], RegimeAssessment(regime, 0, 1, ()))
        return account

    @staticmethod
    def targets(account):
        return sorted((order.price, order.target) for order in account.orders.values())

    def test_a_target_is_raised_only_to_a_zone_in_reach(self):
        # The two upper buy levels have the zone at 1.03 in reach (within 0.08) and target
        # 1.0289, above their geometric targets. It is over 0.08 above the two lower ones,
        # so it only caps them, and their geometric targets lie below it: they stand.
        account = self.open_grid((ResistanceZones((1.03,), 0.08),))
        self.assertEqual(self.RAISED, self.targets(account))
        # No zone at all: the geometric targets.
        self.assertEqual(self.GEOMETRIC, self.targets(self.open_grid(())))

    def test_a_target_is_lowered_to_resistance(self):
        # A zone at 1.0, within 0.03 of the top buy level only: 1.0 x 0.999 is 0.9990, below
        # that level's geometric target 1.0093 and still 1.86% above the level.
        account = self.open_grid((ResistanceZones((1.0,), 0.03),))
        self.assertEqual([*self.GEOMETRIC[:3], (D("0.9808"), D("0.999"))], self.targets(account))

    def test_a_zone_out_of_reach_caps_a_target_that_would_reach_it(self):
        # A zone at 1.009, within 0.02 of no buy level, raises nothing, but the top level's
        # geometric target 1.0093 would sit above it, so it is lowered to 1.0079, just below
        # (1.009 x 0.999, floored). The lower levels' geometric targets lie below it.
        account = self.open_grid((ResistanceZones((1.009,), 0.02),))
        self.assertEqual([*self.GEOMETRIC[:3], (D("0.9808"), D("1.0079"))], self.targets(account))
        # A zone at 0.99 caps the top level at 0.9890, only 0.84% above it: no buy there.
        account = self.open_grid((ResistanceZones((0.99,), 0.005),))
        self.assertEqual(self.GEOMETRIC[:3], self.targets(account))

    def test_a_geometric_target_left_standing_keeps_v0s_rule(self):
        # ATR 0.0184 rounds the lowest buy pair to 0.9632 and 0.9733, 1.049% apart, short
        # of the 1.05% costs require, so V0 refuses the whole grid. A zone at 2.0, out of
        # reach, caps nothing: every geometric target stands, and V2 refuses it alike.
        far = (ResistanceZones((2.0,), 0.01),)
        for structure, resistance in ((False, ()), (True, far)):
            with self.subTest(structure=structure):
                with self.assertRaises(GridNotViable) as refused:
                    self.open_grid(resistance, structure=structure, atr=D("0.0184"))
                self.assertEqual(
                    "rounded spacing cannot cover conservative costs", str(refused.exception)
                )

    def test_a_level_whose_target_cannot_clear_costs_gets_no_buy(self):
        # A zone at 0.985: 0.985 x 0.999 floors to 0.9840, only 0.33% above the top buy
        # level, which may not target above the zone and cannot profit below it, so it gets
        # no buy. The next level down targets 0.9840 too, 3.2% above it. Every order is
        # sized as in V0, a quarter of the budget (80% of the 100 units): the skipped
        # level's share stays unspent and enlarges no other order.
        account = self.open_grid((ResistanceZones((0.985,), 0.05),))
        self.assertEqual([*self.GEOMETRIC[:2], (D("0.9531"), D("0.984"))], self.targets(account))
        for order in account.orders.values():
            share = D(80) / 4 / (order.price * (1 + RULES.fee_rate))
            self.assertEqual(floor_step(share, RULES.quantity_step), order.quantity)

    def test_a_grid_whose_every_level_is_blocked_is_refused_naming_the_resistance(self):
        # A zone 0.2-0.3% above each buy level: no target below one of them clears costs.
        blocking = ResistanceZones((0.902, 0.928, 0.955, 0.983), 0.05)
        with self.assertRaises(GridNotViable) as refused:
            self.open_grid((blocking,))
        self.assertEqual(
            "no buy level can sell below resistance at 0.902, 0.928, 0.955, 0.983 and clear costs",
            str(refused.exception),
        )

    def test_the_nearest_zone_on_any_timeframe_counts(self):
        # Daily 1.03 within 0.08, hourly 1.0 within 0.12: every buy level has the nearer
        # hourly zone in reach and targets 0.9990 just below it, whatever the order of the
        # timeframes.
        daily, hourly_zones = ResistanceZones((1.03,), 0.08), ResistanceZones((1.0,), 0.12)
        below_hourly = [(low, D("0.999")) for low, _ in self.GEOMETRIC]
        for timeframes in ((daily, hourly_zones), (hourly_zones, daily)):
            self.assertEqual(below_hourly, self.targets(self.open_grid(timeframes)))
        # A nearer zone counts at any distance: the daily 1.0 is in reach (within 0.03) of
        # the top buy level only, but it is the nearest zone above every level, so the
        # level at 0.9531 keeps its geometric target 0.9808 instead of rising to the hourly
        # 1.03, which would sit above the daily zone.
        timeframes = (ResistanceZones((1.0,), 0.03), ResistanceZones((1.03,), 0.08))
        expected = [*self.GEOMETRIC[:3], (D("0.9808"), D("0.999"))]
        self.assertEqual(expected, self.targets(self.open_grid(timeframes)))
        # The features give each timeframe's zones as an engine given only that timeframe.
        candles, days = zone_candles(), zone_days()
        both = engine_for(candles, hourly_candles=candles, daily_bars=days)
        alone = [
            engine_for(candles, **timeframe).at(ZONE_MIDNIGHT_MS).resistance
            for timeframe in ({"daily_bars": days}, {"hourly_candles": candles})
        ]
        self.assertCountEqual((*alone[0], *alone[1]), both.at(ZONE_MIDNIGHT_MS).resistance)

    def test_a_zone_without_a_positive_radius_never_raises_but_still_caps(self):
        # A zero radius (a zero ATR) reaches nothing, so its zone at 1.0 raises no target,
        # but the top level's geometric target 1.0093 would sit above it and is lowered to
        # 0.9990. The hourly 1.03 in reach raises nothing either: the zone at 1.0 is nearer.
        zero = ResistanceZones((1.0,), 0.0)
        capped = [*self.GEOMETRIC[:3], (D("0.9808"), D("0.999"))]
        self.assertEqual(capped, self.targets(self.open_grid((zero,))))
        timeframes = (zero, ResistanceZones((1.03,), 0.08))
        self.assertEqual(capped, self.targets(self.open_grid(timeframes)))

    def test_a_target_raised_above_the_top_level_widens_the_grid_upper_bound(self):
        # A zone at 1.15 within 0.2 of the two upper buy levels raises their targets to
        # 1.1488, above the top level 1.1. A bid on the way there is inside the grid's
        # range, so the outside-range clock does not start; the lower bound is unchanged.
        account = self.open_grid((ResistanceZones((1.15,), 0.2),))
        self.assertEqual((D("0.9"), D("1.1488")), (account.grid_lower, account.grid_upper))
        rising = replace(self.frame.quote, bid=D("1.12"), ask=D("1.1205"))
        self.simulator._track_range(account, rising, None, {})  # no H rule, no journal
        self.assertEqual("", account.outside_last)

    def test_only_a_ranging_market_sells_below_resistance(self):
        # The RANGE-only rule is kept, and registered (D20): any other regime keeps V0's
        # geometric targets.
        for regime in MarketRegime:
            with self.subTest(regime=regime):
                account = self.open_grid((ResistanceZones((1.03,), 0.08),), regime=regime)
                expected = self.RAISED if regime == MarketRegime.RANGE else self.GEOMETRIC
                self.assertEqual(expected, self.targets(account))

    def test_with_structure_off_nothing_changes(self):
        # V0: the same frame, resistance and all, opens the geometric grid, the budget
        # shared by all four levels, in the band its levels span.
        account = self.open_grid((ResistanceZones((1.15,), 0.2),), structure=False)
        self.assertEqual(self.GEOMETRIC, self.targets(account))
        self.assertEqual((D("0.9"), D("1.1")), (account.grid_lower, account.grid_upper))
        for order in account.orders.values():
            share = D(80) / 4 / (order.price * (1 + RULES.fee_rate))
            self.assertEqual(floor_step(share, RULES.quantity_step), order.quantity)
        # A frame without resistance, as every V0 frame is, journals what it did before V2.
        journal = replace(self.frame, resistance=()).payload()
        fields = {"quote", "signals", "candidate", "fair_value", "atr", "allow_new_grid"}
        self.assertEqual(fields, set(journal))
        self.assertEqual(({"prices": (1.15,), "radius": 0.2},), self.frame.payload()["resistance"])

    def test_targets_read_only_days_closed_by_the_decision(self):
        # The zone at 1.03 is confirmed by the day that closes at ZONE_MIDNIGHT_MS. Changing
        # the decision's own unfinished day or any later day, or adding days, changes no
        # target; the day confirming the zone counts once it has closed, not a minute before.
        candles, days = zone_candles(), zone_days()

        def targets_at(minute, daily):
            inputs = engine_for(candles, hourly_candles=candles, daily_bars=daily).at(minute)
            grid = self.open_grid(inputs.resistance, fair=inputs.fair_value, atr=inputs.atr)
            return self.targets(grid)

        for minute in (ZONE_MIDNIGHT_MS - 60_000, ZONE_MIDNIGHT_MS + 12 * HOUR_MS):
            with self.subTest(minute=minute):
                completed, changed = unseen_days_changed(days, minute)
                self.assertEqual(targets_at(minute, completed), targets_at(minute, changed))
        before = targets_at(ZONE_MIDNIGHT_MS - 60_000, days)
        after = targets_at(ZONE_MIDNIGHT_MS, days)
        self.assertNotIn(D("1.0289"), {target for _, target in before})
        self.assertIn(D("1.0289"), {target for _, target in after})

    def test_replay_carries_the_resistance_to_the_grid(self):
        # Ungated, so the first frame is a quiet range and opens a grid, three hours after
        # the zone at 1.03 is confirmed. With structure the top buy level targets 1.0289,
        # the two lowest target 0.9773 just below the daily zone at 0.9784, and the level at
        # 0.9726, which that zone leaves no target clearing costs, gets no buy.
        candles = zone_candles()
        engine = engine_for(candles, hourly_candles=candles, daily_bars=zone_days())
        t = ZONE_MIDNIGHT_MS + 3 * HOUR_MS
        fair = float(engine.at(t).fair_value)
        minutes = [candle(t + i * 60_000, fair, fair * 1.001, fair * 0.999, fair) for i in range(3)]
        run = RunConfig("TESTUSDT", "low_first", False, RULES, D(100), D("0.0005"))
        lows = [D("0.9455"), D("0.959"), D("0.9726"), D("0.9865")]
        for policy, highs in (
            (SimulationPolicy(structure=True), [D("0.9773"), D("0.9773"), None, D("1.0289")]),
            (None, [*lows[1:], D("1.0005")]),  # V0: the geometric next levels
        ):
            with self.subTest(policy=policy):
                _, account = replay(self.config, run, minutes, engine, policy)
                placed = [(low, high) for low, high in zip(lows, highs, strict=True) if high]
                self.assertEqual(placed, self.targets(account))


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
    """Variant E through replay(): a grid at minute 0, then outside its band from minute 1
    (t0 is minute 1's open: the measured span is minutes 1 to 360, t0 + 6 h is minute 361
    and t0 + 12 h minute 721)."""

    E = SimulationPolicy(volume_exit=True)
    # V0 with a 12-hour timer: what E's extended episodes must equal, risk actions and all,
    # when observations are continuous.
    V0_12H = SimulationPolicy(outside_range_seconds=43_200)

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.candles = hourly(WARMUP)
        self.engine = engine_for(self.candles)
        self.t = START_MS + WARMUP * HOUR_MS
        self.fair = float(self.engine.at(self.t).fair_value)
        self.run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))

    def bar(self, minute, factor, volume="1", taker="0"):
        price = self.fair * factor
        return candle(
            self.t + minute * 60_000, price, price * 1.001, price * 0.999, price, volume, taker
        )

    def minutes(self, volume="1000000", taker="500000", later=None, count=800):
        """Minute 0 at fair value, then minutes 10% lower; ``later`` is the volume from
        minute 361 on."""
        bars = [self.bar(0, 1, "1000000", "500000")]
        for i in range(1, count + 1):
            v, k = (later, "0") if later and i >= 361 else (volume, taker)
            bars.append(self.bar(i, 0.9, v, k))
        return bars

    def above_then_filled(self):
        """Above the band until minute 399, so nothing fills and the volume stays low
        (E extends at minute 361); at minute 400 the price drops below it, and the buys
        fill on high volume (a daily-loss pause, with its drain, follows)."""
        bars = [self.bar(0, 1, "1000000", "500000")]
        bars += [self.bar(i, 1.1) for i in range(1, 400)]
        return [*bars, self.bar(400, 0.9, "1000000", "0")]

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

    def assertSameAs(self, minutes, policy):
        """E's run equals ``policy``'s on these minutes but for E's own row fields, which
        it returns with E's account."""
        other, other_account = self.replay(minutes, policy)
        e, e_account = self.replay(minutes, self.E)
        self.assertEqual(asdict(other), asdict(replace(e, variant={})))
        self.assertEqual(other_account.to_dict(), e_account.to_dict())
        return e, e_account

    def test_low_volume_extends_the_exit_from_6_to_12_hours(self):
        minutes = self.minutes("1", "0")
        _, v0 = self.replay(minutes)
        self.assertEqual(self.exit_at(361), v0.range_exit_since)
        e, account = self.replay(minutes, self.E)
        self.assertEqual({"extended": 1}, e.variant["volume_exit_checks"])
        self.assertEqual(self.exit_at(721), account.range_exit_since)
        self.assertEqual(6.0, e.variant["volume_exit_extra_hours"])  # from 6 h to 12 h
        # Volume from t0 + 6 h on, however large, cannot reach the decision.
        late, late_account = self.replay(self.minutes("1", "0", later="1000000000"), self.E)
        self.assertEqual(e.variant["volume_exit_checks"], late.variant["volume_exit_checks"])
        self.assertEqual(self.exit_at(721), late_account.range_exit_since)

    def test_volume_at_or_above_the_threshold_exits_as_v0(self):
        e, account = self.assertSameAs(self.minutes(), None)
        self.assertEqual({"exit": 1}, e.variant["volume_exit_checks"])
        self.assertEqual(self.exit_at(361), account.range_exit_since)

    def test_a_missing_reference_hour_or_measured_minute_exits_as_v0(self):
        low = self.minutes("1", "0")
        gap = [c for c in self.candles if c.open_ms != self.t - 100 * HOUR_MS]
        v0, _ = self.replay(low)
        e, account = self.replay(low, self.E, gap)
        self.assertEqual({"unavailable": 1}, e.variant["volume_exit_checks"])
        self.assertEqual(asdict(v0), asdict(replace(e, variant={})))
        self.assertEqual(self.exit_at(361), account.range_exit_since)
        e, _ = self.assertSameAs([b for i, b in enumerate(low) if i != 100], None)
        self.assertEqual({"unavailable": 1}, e.variant["volume_exit_checks"])

    def test_milestones_stay_on_the_clock_from_t0_across_long_gaps(self):
        # Codex review of #165: a gap longer than maximum_frame_gap_seconds pauses V0's
        # accumulated outside time, but E decides at the first valid observation at or
        # after t0 + 6 h, and an extended episode ends at the first at or after t0 + 12 h.
        low = self.minutes("1", "0", count=900)
        for gap, exit_minute, decided, extra in (
            # Inside the measured span: unavailable, so V0's own exit, which the gap
            # delays to minute 422, applies unchanged.
            (range(100, 160), 422, "unavailable", 0.0),
            # Across t0 + 6 h, after the span: the decision waits for minute 421, on the
            # same span, and the deadline stays at minute 721 (on V0's clock: 782).
            (range(361, 421), 721, "extended", 5.0),
            # Between the two milestones: the exit still comes at t0 + 12 h.
            (range(400, 500), 721, "extended", 6.0),
            # Across t0 + 12 h: the first observation after it exits.
            (range(700, 760), 760, "extended", 6.65),
        ):
            with self.subTest(gap=gap):
                minutes = [b for i, b in enumerate(low) if i not in gap]
                e, account = self.replay(minutes, self.E)
                self.assertEqual({decided: 1}, e.variant["volume_exit_checks"])
                self.assertEqual(self.exit_at(exit_minute), account.range_exit_since)
                self.assertAlmostEqual(extra, e.variant["volume_exit_extra_hours"])
                if decided == "unavailable":
                    self.assertSameAs(minutes, None)

    def test_a_return_inside_starts_a_new_episode_with_its_own_extension(self):
        # (Both episodes start within the first hour, whose 720 reference hours exist.)
        minutes = [self.bar(0, 1, "1000000", "500000")]
        minutes += [self.bar(i, 0.9) for i in range(1, 21)]  # 20 minutes: no decision
        minutes += [self.bar(i, 1.0) for i in range(21, 26)]  # inside: the timer resets
        minutes += [self.bar(i, 0.9) for i in range(26, 800)]  # t0 is minute 26
        e, account = self.replay(minutes, self.E)
        self.assertEqual({"extended": 1}, e.variant["volume_exit_checks"])
        self.assertEqual(self.exit_at(746), account.range_exit_since)  # 26 + 720

    def test_risk_actions_during_the_extension_act_exactly_as_in_v0(self):
        # From minute 400 a daily-loss pause drains; a hard-drawdown halt or an emergency
        # exit at minute 450 falls inside the extension. E's run equals V0 with a 12-hour
        # timer, which reaches the same state with no extension at all.
        filled = self.above_then_filled()
        drop = [self.bar(i, 0.9) for i in range(401, 450)]
        drop += [self.bar(i, 0.7) for i in range(450, 800)]
        e, account = self.assertSameAs(filled + drop, self.V0_12H)
        self.assertEqual(("drawdown", self.exit_at(450)), (account.halt_category, e.halted_at))
        self.assertEqual({"extended": 1}, e.variant["volume_exit_checks"])
        self.assertAlmostEqual(89 / 60, e.variant["volume_exit_extra_hours"])  # to the halt
        plain = filled + [self.bar(i, 0.9) for i in range(401, 800)]
        emergency_from = utc_at(self.t + 450 * 60_000)

        def signals(inputs, observed_at, *, gated):
            normal = signals_for(inputs, observed_at, gated=gated)
            return replace(normal, emergency=observed_at >= emergency_from)

        with patch("crypto_grid_bot.backtest.replay.signals_for", signals):
            e, account = self.assertSameAs(plain, self.V0_12H)
        self.assertEqual(("emergency", self.exit_at(450)), (account.halt_category, e.halted_at))
        # The drain alone: the pause from minute 400 runs through the extension.
        e, account = self.assertSameAs(plain, self.V0_12H)
        self.assertTrue(account.draining)

    def test_a_partial_exit_at_12_hours_stays_latched_and_is_reported_against_the_6_hour_bid(
        self,
    ):
        # The exit starts at minute 721 and can sell 6.2 units a quote; from minute 722 the
        # price is back inside the band, and the exit goes on as V0's would.
        minutes = self.above_then_filled() + [self.bar(i, 0.9) for i in range(401, 721)]
        minutes += [self.bar(721, 0.9, "1000", "250")]
        minutes += [self.bar(i, 1.0, "1000", "250") for i in range(722, 760)]
        e, _ = self.assertSameAs(minutes, self.V0_12H)
        self.assertEqual(1, e.range_exits)
        self.assertGreater(e.sold, 4 * D("6.2"))  # more than minute 721 alone could sell
        exits = e.variant["volume_exit_extended_exits"]
        self.assertEqual(1, exits["exits"])
        self.assertEqual(str(e.exit_pnl_by_reason["range_exit"]), exits["pnl"])
        self.assertEqual(D(0), e.grid_sell_pnl)  # every sale was the extended exit's
        # The same sales at the bid of the 6-hour mark (minute 361's first quote), with no
        # fees: the P&L differs by bid x quantity - proceeds + fees.
        mark = bar_quotes(
            self.bar(361, 1.1), "TESTUSDT", "high_first", D("0.0005"), RULES.tick_size
        )[0]
        self.assertEqual(
            mark.bid * e.sold - e.sell_notional + e.sell_fees,
            D(exits["pnl_at_6h_bid"]) - D(exits["pnl"]),
        )

    def test_v0_ignores_the_hourly_history_and_e_refuses_to_run_without_it(self):
        minutes = self.minutes("1", "0")
        v0 = replay(self.config, self.run, minutes, self.engine)
        with_hourly = replay(self.config, self.run, minutes, self.engine, hourly=self.candles)
        self.assertEqual(asdict(v0[0]), asdict(with_hourly[0]))
        self.assertEqual({}, v0[0].variant)
        with self.assertRaisesRegex(ValueError, "hourly history"):
            replay(self.config, self.run, minutes, self.engine, self.E)


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

    def frames(self, minute, share, candidate=None, price=None):
        """The four frames of a flat minute bar at ``price`` (default: fair value),
        ``minute`` after warm-up."""
        open_ms = START_MS + WARMUP * HOUR_MS + minute * 60_000
        level = float(self.inputs.fair_value) if price is None else price
        bar = candle(open_ms, level, level, level, level)
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

    def partly_filled_buy(self, key, quantity, filled, target="1.1000"):
        price = D("1.0000")
        self.account.cash -= filled * price * (1 + RULES.fee_rate)
        self.account.inventory += filled
        self.account.orders[key] = LimitOrder(
            key, "buy", price, quantity, quantity - filled, target=D(target)
        )

    def two_held_fragments(self):
        """A fresh account whose block leaves 3 units at a target of 1.1 and 3 at 1.2:
        3.3 and 3.6, each below the minimum notional of 5, but 6 units together are
        sellable at the bid. Returns the block's reports."""
        self.account = Account.start(D(100))
        self.partly_filled_buy("a/buy/0", D(10), D(3))
        self.partly_filled_buy("b/buy/0", D(10), D(3), "1.2000")
        reports = self.step(self.frames(0, D("0.3")))
        self.assertEqual({D("1.1"): D(3), D("1.2"): D(3)}, self.account.flow_fragments)
        self.assertEqual((D(6), {}), (self.account.inventory, self.account.orders))
        return reports

    @staticmethod
    def exits(reports):
        return [
            (report.get("exit_reason"), fill["quantity"])
            for report in reports
            for fill in report["fills"]
            if fill["order_id"].startswith("exit/")
        ]

    def test_held_fragments_wait_for_their_targets_and_no_ordinary_drain_sells_them(self):
        # Codex review of #165: the two fragments were sold together, as one 6-unit taker
        # exit, by the drain of unpaired inventory, instead of waiting for their targets.
        self.assertEqual([], self.exits(self.two_held_fragments()))
        reports = self.step(self.frames(1, D("0.3")))  # still blocked: still held
        self.assertEqual(([], D(6)), (self.exits(reports), self.account.inventory))
        # The end-of-run verdict reports them as dust, never as an exit owed.
        quote, held = self.frames(1, None)[0].quote, self.simulator.held_fragments(self.account)
        self.assertEqual(D(6), held)
        self.assertEqual("dust", exit_state(self.account, quote, RULES, held)[0])
        self.assertEqual("incomplete", exit_state(self.account, quote, RULES)[0])

    def test_a_drain_a_halt_or_the_end_of_their_grid_sells_held_fragments(self):
        inputs = candidate_for(self.inputs, "TESTUSDT", 0.05, 1e9, gated=False)
        # A V0 pause drains them as in V0 (an ineligible spread, F still blocking).
        self.two_held_fragments()
        reports = self.step(self.frames(1, D("0.3"), replace(inputs, spread_pct=1)))
        self.assertEqual([("drain", D(6))], self.exits(reports))
        # So does a halt's liquidation (an emergency).
        self.two_held_fragments()
        frames = [
            replace(f, signals=replace(f.signals, emergency=True)) for f in self.frames(1, None)
        ]
        self.assertEqual([("liquidation", D(6))], self.exits(self.step(frames)))
        # Unblocked with no order left, their grid has ended: the account re-centres, so
        # they are ordinary unpaired inventory, drained before the next grid opens.
        self.two_held_fragments()
        reports = self.step(self.frames(1, D("0.5")))
        self.assertEqual([("drain", D(6))], self.exits(reports))
        self.assertEqual({}, self.account.flow_fragments)
        self.assertTrue(any(report["opened"] for report in reports))

    def test_a_fragment_a_range_exit_left_is_drained_once_sellable(self):
        # Codex review of #165: a range exit, its liquidation done, ended the grid with
        # only a fragment below the minimum left, while F still blocks. The harvest after
        # it makes the fragment ordinary unpaired inventory: the drain sells it once a
        # price makes it sellable, F blocking or not.
        (frame, *_) = self.frames(0, None)
        self.partly_filled_buy("a/buy/0", D(10), D("4.5"))  # 4.5 x 1.1 = 4.95: a fragment
        self.simulator._block_buys(self.account, frame)
        account, fair = self.account, self.inputs.fair_value
        account.flow_block, account.range_exit = True, True
        account.range_exit_since = frame.quote.observed_at
        account.grid_lower, account.grid_upper = fair * D("0.95"), fair * D("1.05")
        self.assertEqual({D("1.1"): D("4.5")}, account.flow_fragments)
        reports = self.step(self.frames(1, D("0.3")))  # back inside: the exit ends
        self.assertEqual(([], False), (self.exits(reports), account.range_exit))
        self.assertEqual({}, account.flow_fragments)
        # 4.5 at an exit price above 5 / 4.5 is sellable.
        reports = self.step(self.frames(2, D("0.3"), price=1.13))
        self.assertEqual([("drain", D("4.5"))], self.exits(reports))
        self.assertTrue(account.flow_block)

    def test_the_harvest_that_replaces_a_grid_drops_its_fragments(self):
        # F has stopped blocking when the grid's last sell fills, and the harvest cancels
        # the reentry buy that sell placed and opens the next grid in the same step: the
        # old grid's fragment is ordinary inventory, not the new grid's.
        (frame, *_) = self.frames(0, None)
        self.partly_filled_buy("a/buy/0", D(1), D("0.1"))  # 0.1 x 1.1 = 0.11: a fragment
        price = (self.inputs.fair_value * D("0.99")).quantize(RULES.tick_size)
        reentry = (price * D("0.98")).quantize(RULES.tick_size)
        self.account.cash -= 6 * price
        self.account.inventory += 6
        self.account.orders["b/sell/0"] = LimitOrder(
            "b/sell/0", "sell", price, D(6), D(6), None, reentry
        )
        low = float(self.inputs.fair_value) * 0.97
        self.step(self.frames(0, D("0.3"), price=low))  # blocked, the sell above the bid
        self.assertEqual({D("1.1"): D("0.1")}, self.account.flow_fragments)
        reports = self.step(self.frames(1, D("0.5")))
        self.assertTrue(any(report["opened"] for report in reports))
        self.assertEqual({}, self.account.flow_fragments)

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

    def records(self, rate, hours=(24, 16, 8)):
        """Settlements ``hours`` before the first minute, 11 ms past the hour. The default
        is uniform, and overdue from a minute after the first minute."""
        return [FundingRecord(self.t - h * HOUR_MS + 11, 8, D(rate)) for h in hours]

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
                metrics, _ = self.replay(self.minutes[:1], funding=self.records(rate))
                self.assertEqual(opened, metrics.grids_opened)
        # No history at all is unavailable: G fails closed.
        metrics, _ = self.replay(self.minutes[:1], funding=[])
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
        records = self.records("0.0001")
        self.assertTrue(FundingSignal(records).state(self.t).available)
        self.assertEqual("overdue", FundingSignal(records).state(self.t + 60_000).reason)
        v0, v0_account = self.replay(minutes, None)
        g, g_account = self.replay(minutes, funding=records)
        self.assertEqual(asdict(v0), asdict(replace(g, variant={})))
        self.assertEqual(v0_account.to_dict(), g_account.to_dict())
        self.assertEqual(1, g.range_exits)

    def test_the_grids_and_hours_blocked_and_each_settlements_lag_are_reported(self):
        # Two settlements before the first minute: G is unavailable at minute 0, and
        # blocks the grid the flat account wants. The third settles at the first
        # minute's open + 11 ms and is usable from 60 s later truncated to the second, so
        # minute 1 is the first to use it, 59.989 s after the settlement: G clears, and a
        # grid opens.
        metrics, _ = self.replay(self.minutes, funding=self.records("0.0001", (16, 8, 0)))
        self.assertEqual(1, metrics.grids_opened)
        self.assertEqual(1, metrics.variant["funding_gate_blocked_grids"])
        self.assertEqual(1 / 60, metrics.variant["funding_gate_blocked_hours"])
        lag = {"settlements": 1, "min": 59.989, "mean": 59.989, "max": 59.989}
        self.assertEqual(lag, metrics.variant["funding_gate_lag_seconds"])
        # Blocked throughout: one blocked grid, and every minute's gate closed.
        metrics, _ = self.replay(self.minutes, funding=self.records("0.001"))
        self.assertEqual(1, metrics.variant["funding_gate_blocked_grids"])
        self.assertEqual(0.5, metrics.variant["funding_gate_blocked_hours"])
        empty = {"settlements": 0, "min": None, "mean": None, "max": None}
        self.assertEqual(empty, metrics.variant["funding_gate_lag_seconds"])
        v0, _ = self.replay(self.minutes, None)
        self.assertEqual({}, v0.variant)

    def test_a_record_usable_within_a_minute_counts_from_the_next_quote(self):
        # Codex review of #165: the third settlement, 45 s before the first minute, is
        # usable 15 s into it. The quotes at +0 and +9 s precede that, so G is unavailable
        # and blocks the grid the flat account wants; from +19 s G is clear and the grid
        # opens, not a minute later. The lag is 64 s, and the gate was closed 19 s.
        records = [*self.records("0.0001", (17, 9)), FundingRecord(self.t - 45_000, 8, D("0.0001"))]
        seen, real_step = [], PaperSimulator.step

        def recording(simulator, account, frame):
            report = real_step(simulator, account, frame)
            seen.append(
                (frame.quote.observed_at[11:19], frame.funding_blocks, bool(report["opened"]))
            )
            return report

        with patch.object(PaperSimulator, "step", recording):
            metrics, _ = self.replay(self.minutes[:2], funding=records)
        expected = [("08:00:00", True, False), ("08:00:09", True, False)]
        expected += [("08:00:19", False, True), ("08:00:29", False, False)]
        self.assertEqual(expected, seen[:4])
        self.assertEqual(1, metrics.variant["funding_gate_blocked_grids"])
        self.assertEqual(19 / 3600, metrics.variant["funding_gate_blocked_hours"])
        lag = {"settlements": 1, "min": 64.0, "mean": 64.0, "max": 64.0}
        self.assertEqual(lag, metrics.variant["funding_gate_lag_seconds"])

    def test_a_manifests_funding_archives_reach_the_gate(self):
        # Records settled 16 h, 8 h and 0 h before the first minute, in the archive of
        # their month: G is available and clear, and the grid opens.
        month = utc_at(self.t).strftime("%Y-%m")
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp)
            path = funding_local_path(data, "BTCUSDT", month)
            path.parent.mkdir(parents=True)
            rows = "".join(f"{self.t - h * HOUR_MS + 11},8,0.0001\n" for h in (16, 8, 0))
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    f"BTCUSDT-fundingRate-{month}.csv",
                    "calc_time,funding_interval_hours,last_funding_rate\n" + rows,
                )
            files = [
                {"kind": "fundingRate", "symbol": "BTCUSDT", "month": month, "status": "ok"},
                {"kind": "fundingRate", "symbol": "BTCUSDT", "month": "2024-03"}
                | {"status": "missing"},
                {"kind": "fundingRate", "symbol": "ETHUSDT", "month": month, "status": "ok"},
                {"symbol": "BTCUSDT", "interval": "1h", "month": month, "status": "ok"},
            ]
            records = load_funding(data, {"files": files}, "BTCUSDT", [month])
        self.assertEqual(3, len(records))
        metrics, _ = self.replay(self.minutes[2:], funding=records)
        self.assertEqual(1, metrics.grids_opened)

    def test_a_run_without_funding_for_every_evaluation_month_is_refused(self):
        # Codex review of #165: G would block every new grid in a month without funding,
        # a result that says nothing about funding, so the run is refused instead.
        present = {"kind": "fundingRate", "symbol": "BTCUSDT", "month": "2024-01", "status": "ok"}
        cases = (
            ([], "2024-01, 2024-02"),  # a manifest without funding entries
            ([present], "2024-02"),
            ([present, present | {"month": "2024-02", "status": "missing"}], "2024-02"),
            ([present, present | {"month": "2024-02", "symbol": "ETHUSDT"}], "2024-02"),
        )
        for files, absent in cases:
            with self.subTest(files=files), self.assertRaisesRegex(ValueError, absent):
                load_funding(Path("."), {"files": files}, "BTCUSDT", ["2024-01", "2024-02"])

    def test_months_before_the_archives_begin_need_none_and_g_blocks_there(self):
        # Spec v1 §5 rule 9: BTCUSDT's funding archives begin in 2020-01, so a long window's
        # earlier evaluation months need none, and G blocks every new grid there. No
        # stage-1 window has such a month (automated review of #168).
        early = ["2019-11", "2019-12"]
        self.assertEqual([], load_funding(Path("."), {"files": []}, "BTCUSDT", early))
        metrics, _ = self.replay(self.minutes[:1], funding=[])
        self.assertEqual(0, metrics.grids_opened)
        self.assertIn("cash: funding gate: funding high or unavailable", metrics.reasons)
        # From 2020-01 on every month still needs its archive: a manifest that lists none,
        # or misses one, is refused, naming only those months.
        months = [*early, "2020-01", "2020-02"]
        present = {"kind": "fundingRate", "symbol": "BTCUSDT", "month": "2020-01", "status": "ok"}
        for files, absent in (([], "for 2020-01, 2020-02$"), ([present], "for 2020-02$")):
            with self.subTest(files=files), self.assertRaisesRegex(ValueError, absent):
                load_funding(Path("."), {"files": files}, "BTCUSDT", months)
        # With both, the archives are read and the earlier months are simply empty.
        with tempfile.TemporaryDirectory() as temp:
            data, files = Path(temp), []
            for month, first in (("2020-01", 1577836800000), ("2020-02", 1580515200000)):
                path = funding_local_path(data, "BTCUSDT", month)
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr(
                        f"BTCUSDT-fundingRate-{month}.csv",
                        f"calc_time,funding_interval_hours,last_funding_rate\n{first},8,0.0001\n",
                    )
                files.append(present | {"month": month})
            records = load_funding(data, {"files": files}, "BTCUSDT", months)
        self.assertEqual([1577836800000, 1580515200000], [r.calc_time_ms for r in records])


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
        account.volume_since, account.volume_check = "2024-01-01T00:00:00+00:00", "extended"
        account.flow_block, account.flow_fragments = False, {D("1.1"): D("0.1")}
        self.assertEqual(saved, set(account.to_dict()))
