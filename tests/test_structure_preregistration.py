"""Pins every V2 rule and setting frozen in docs/STRUCTURE_PREREGISTRATION.md (D20).

A failure here means a registered V2 rule or value changed. That is a re-registration,
not a fix: amend the pre-registration first (what changed, why and when), bump
STRUCTURE_FEATURE_VERSION, then update this test. The sell-at-resistance rule's
behaviour is pinned by SellAtResistanceTests in test_backtest_replay.py, and the
completed-days rule also by FeatureChronologyTests there. Synthetic data only.
"""

import unittest
from dataclasses import asdict, replace
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from test_backtest_replay import (
    HOUR_MS,
    ROOT,
    ZONE_MIDNIGHT_MS,
    engine_for,
    zone_candles,
    zone_days,
)
from test_structure import Bar, bullish_bars, flat_bars

from crypto_grid_bot.backtest import features
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import MarketRules
from crypto_grid_bot.simulation.runner import RESISTANCE_TARGET, PaperSimulator, SimulationPolicy
from crypto_grid_bot.strategy.regime import RegimeClassifier
from crypto_grid_bot.strategy.structure import (
    ResistanceZones,
    StructureParams,
    analyse_multi_timeframe,
    detect_swing_highs,
    detect_swing_lows,
)


class StructurePreregistrationTests(unittest.TestCase):
    def test_the_structure_settings_and_the_results_label(self):
        self.assertEqual(
            {
                "swing_n": 3,
                "merge_atr": 0.5,
                "max_distance_atr": 5.0,
                "min_swings": 2,
                "atr_period": 14,
                "zone_recency_weight": 0.5,
            },
            asdict(StructureParams()),
        )
        self.assertEqual("price-only-v1+structure-v2", features.STRUCTURE_FEATURE_VERSION)

    def test_the_inputs_are_completed_bars_only(self):
        # The pair's last 500 completed hourly candles, the daily bars closed by the
        # decision minute (TrendSchedule's rule), no weekly bars; each timeframe's zones.
        candles, days = zone_candles(), zone_days()
        minute = ZONE_MIDNIGHT_MS + 12 * HOUR_MS  # mid-day: today's bar is unfinished
        engine = engine_for(candles, hourly_candles=candles, daily_bars=days)
        with patch.object(
            features, "analyse_multi_timeframe", wraps=analyse_multi_timeframe
        ) as analyse:
            inputs = engine.at(minute)
        (call,) = analyse.call_args_list
        hourly, daily = call.kwargs["hourly_bars"], call.kwargs["daily_bars"]
        self.assertEqual(500, len(hourly))
        self.assertEqual(minute - HOUR_MS, hourly[-1].open_ms)
        closed = [day.open_ms for day in days if day.open_ms + features.DAY_MS <= minute]
        self.assertEqual(closed, [bar.open_ms for bar in daily])
        self.assertIsNone(call.kwargs["weekly_bars"])
        mtf = analyse_multi_timeframe(**call.kwargs)
        zones = [ResistanceZones.of(timeframe, 5.0) for timeframe in (mtf.daily, mtf.hourly)]
        self.assertCountEqual(zones, inputs.resistance)

    def test_the_timeframe_weights(self):
        # One timeframe bullish among ranging ones scores its own weight; without weekly
        # bars, as features.py supplies none, the other two are renormalised (0.30, 0.70).
        params = StructureParams(swing_n=1, atr_period=5)
        bull, flat = bullish_bars(), flat_bars(11)
        for (hourly, daily, weekly), alignment in (
            ((bull, flat, flat), 0.15),
            ((flat, bull, flat), 0.35),
            ((flat, flat, bull), 0.50),
            ((bull, flat, None), 0.30),
            ((flat, bull, None), 0.70),
        ):
            mtf = analyse_multi_timeframe(hourly, daily, weekly, 100.0, params)
            self.assertAlmostEqual(alignment, mtf.alignment)

    def test_the_regime_vote(self):
        self.assertEqual(
            {
                "trend": 0.25,
                "breadth": 0.20,
                "momentum": 0.15,
                "volatility_health": 0.15,
                "liquidity_health": 0.15,
                "structure_alignment": 0.10,
            },
            RegimeClassifier(structure=True)._weights,
        )

    def test_swings_are_strict(self):
        # D21: a swing is higher (lower) than the 3 bars on each side. Equal extremes 3 bars
        # apart, a flat or double top that close, give no swing; 4 bars apart, each is one.
        def swings(peaks):
            plain = [Bar(i, 100.0, 99.0, 99.5) for i in range(15)]
            tops = [replace(b, high=105.0) if b.open_ms in peaks else b for b in plain]
            bottoms = [replace(b, low=94.0) if b.open_ms in peaks else b for b in plain]
            return (
                [s.index for s in detect_swing_highs(tops, StructureParams().swing_n)],
                [s.index for s in detect_swing_lows(bottoms, StructureParams().swing_n)],
            )

        self.assertEqual(([], []), swings({5, 8}))
        self.assertEqual(([5, 9], [5, 9]), swings({5, 9}))

    def test_the_target_buffer_and_the_owners_example(self):
        # D19, the owner's example: resistance at 0.355 above a buy level whose geometric
        # target is 0.342 gives a target of 0.354, just below it.
        self.assertEqual(D("0.999"), RESISTANCE_TARGET)
        config = load_config(ROOT / "config/default.toml")
        rules = MarketRules(symbol="TESTUSDT", tick_size=D("0.001"))
        policy = SimulationPolicy(structure=True)
        simulator = PaperSimulator(Path(":memory:"), config, rules, policy=policy)
        simulator.close()
        resistance = (ResistanceZones((0.355,), 0.05),)
        kept = simulator._below_resistance([(D("0.330"), D("0.342"))], resistance, D("0.0105"))
        self.assertEqual([(D("0.330"), D("0.354"))], kept)
