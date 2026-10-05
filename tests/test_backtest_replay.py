"""Chronology, adapter and accounting tests for the historical replay (synthetic data)."""

import math
import random
import statistics
import unittest
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal as D
from decimal import getcontext, localcontext
from pathlib import Path

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
    order_requests,
    replay,
    signals_for,
    summarise,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import CandidateMetrics, MarketRegime, MarketSignals, RegimeAssessment
from crypto_grid_bot.simulation.execution import match, place, reduce_unreserved
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
from crypto_grid_bot.strategy.structure import ResistanceZones, nearest_resistance

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
        # nearest resistance above fair value appears then.
        before, after = engine.at(midnight_ms - 60_000), engine.at(midnight_ms)
        self.assertEqual(before.hour_open_ms, after.hour_open_ms)  # inside the hole
        self.assertIsNone(nearest_resistance(float(before.fair_value), before.resistance))
        self.assertEqual(1.03, nearest_resistance(float(after.fair_value), after.resistance))

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
        for variant, policy in (
            ("A", SimulationPolicy(trend_switch=True)),
            ("B", SimulationPolicy(inventory_cap=cap)),
            ("C", SimulationPolicy(trend_switch=True, inventory_cap=cap)),
        ):
            with self.subTest(variant=variant):
                self.assertEqual(policy, variant_policy(variant))
                self.assertEqual(variant, variant_name(policy))
                self.assertEqual(
                    replace(policy, structure=True), variant_policy(variant, structure=True)
                )
        self.assertEqual(SimulationPolicy(structure=True), variant_policy(None, structure=True))
        self.assertIn("not the spec", variant_name(SimulationPolicy(inventory_cap=D("0.5"))))
        with self.assertRaises(ValueError):
            variant_policy("E")


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

    def test_a_target_is_raised_to_resistance_or_stays_geometric_without_a_zone(self):
        # The two upper buy levels have the zone at 1.03 in range and target 1.0289, above
        # their geometric targets; the two lower ones are over 0.08 below it and keep theirs.
        account = self.open_grid((ResistanceZones((1.03,), 0.08),))
        self.assertEqual(self.RAISED, self.targets(account))

    def test_a_target_is_lowered_to_resistance(self):
        # A zone at 1.0, within 0.03 of the top buy level only: 1.0 x 0.999 is 0.9990, below
        # that level's geometric target 1.0093 and still 1.86% above the level.
        account = self.open_grid((ResistanceZones((1.0,), 0.03),))
        self.assertEqual([*self.GEOMETRIC[:3], (D("0.9808"), D("0.999"))], self.targets(account))

    def test_a_level_whose_target_cannot_clear_costs_gets_no_buy(self):
        # A zone at 0.985: 0.985 x 0.999 floors to 0.9840, only 0.33% above the top buy
        # level, which may not target above the zone and cannot profit below it, so it gets
        # no buy. The next level down targets 0.9840 too, 3.2% above it. The three levels
        # left share the whole budget, 80% of the 100 units.
        account = self.open_grid((ResistanceZones((0.985,), 0.05),))
        self.assertEqual([*self.GEOMETRIC[:2], (D("0.9531"), D("0.984"))], self.targets(account))
        for order in account.orders.values():
            share = D(80) / 3 / (order.price * (1 + RULES.fee_rate))
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

    def test_daily_zones_come_before_hourly(self):
        # Daily 1.03 within 0.08, hourly 1.0 within 0.12. The two upper buy levels have the
        # daily zone in range and target it, though the hourly zone is nearer; the two lower
        # ones have no daily zone in range and target the hourly one.
        daily, hourly_zones = ResistanceZones((1.03,), 0.08), ResistanceZones((1.0,), 0.12)
        expected = [(D("0.9"), D("0.999")), (D("0.9261"), D("0.999")), *self.RAISED[2:]]
        self.assertEqual(expected, self.targets(self.open_grid((daily, hourly_zones))))
        # The features list the daily zones first: an engine given only one timeframe
        # gives that timeframe's zones alone.
        candles, days = zone_candles(), zone_days()
        both = engine_for(candles, hourly_candles=candles, daily_bars=days)
        alone = [
            engine_for(candles, **timeframe).at(ZONE_MIDNIGHT_MS).resistance
            for timeframe in ({"daily_bars": days}, {"hourly_candles": candles})
        ]
        self.assertEqual((*alone[0], *alone[1]), both.at(ZONE_MIDNIGHT_MS).resistance)

    def test_a_target_raised_above_the_top_level_widens_the_grid_upper_bound(self):
        # A zone at 1.15 within 0.2 of the two upper buy levels raises their targets to
        # 1.1488, above the top level 1.1. A bid on the way there is inside the grid's
        # range, so the outside-range clock does not start; the lower bound is unchanged.
        account = self.open_grid((ResistanceZones((1.15,), 0.2),))
        self.assertEqual((D("0.9"), D("1.1488")), (account.grid_lower, account.grid_upper))
        rising = replace(self.frame.quote, bid=D("1.12"), ask=D("1.1205"))
        self.simulator._track_range(account, rising)
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
