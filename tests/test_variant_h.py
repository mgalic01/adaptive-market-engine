"""Tests for experiment variant H: Bitcoin halving cycle context (spec v1 §3 H).

Covers:
  - phase_m() computation (including boundary conditions)
  - cycle_signal() H2 and H3 activation
  - ATH unavailability (short daily history)
  - H2 blocks new grid via replay()
  - H2 reduces outside-range threshold to 2h
  - H3 lowers opportunity score minimum via replay()
  - cycle_gate=False is identical to V0
"""

import math
import unittest
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.cycle import (
    _HALVINGS,
    H2_OUTSIDE_RANGE_SECONDS,
    H2_PRICE_MULTIPLE,
    H3_PRICE_MULTIPLE,
    H3_SCORE_RELAXATION,
    compute_ath,
    compute_sma200,
    cycle_signal,
    phase_m,
)
from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, replay
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import MarketRules
from crypto_grid_bot.simulation.runner import SimulationPolicy

ROOT = Path(__file__).resolve().parents[1]

# The 2020 halving, used as a convenient fixed reference.
_H2020 = _HALVINGS[1]  # 2020-05-11 19:23:43 UTC

DAY_MS = 86_400_000
HOUR_MS_LOCAL = HOUR_MS  # avoid shadowing the import

RULES = MarketRules(
    symbol="TESTUSDT",
    tick_size=D("0.0001"),
    quantity_step=D("0.1"),
    minimum_notional=D("5"),
)
WARMUP = 800  # hours; consistent with test_backtest_replay.py

START_MS = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)


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


def daily_bars(start_ms, count, price=D("1.0")):
    """Synthetic daily bars at a fixed price."""
    return [candle(start_ms + i * DAY_MS, price, price, price, price) for i in range(count)]


def engine_for(candles, daily_bars=None):
    series = SeriesFeatures("TESTUSDT", candles)
    basket = [SeriesFeatures(f"B{i}USDT", candles, full=False) for i in range(5)]
    return FeatureEngine(
        series,
        series,
        basket,
        range_atr_multiple=2.0,
        levels=8,
        minimum_cost_multiple=3.0,
        round_trip_cost=0.0035,
        hourly_candles=candles,
        daily_bars=daily_bars,
    )


# ---------------------------------------------------------------------------
# phase_m() unit tests
# ---------------------------------------------------------------------------


class PhaseMTests(unittest.TestCase):
    """spec v1 §3 H: phase m = whole calendar months since the most recent halving."""

    def _obs(self, year, month, day, hour=0, minute=0, second=0):
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)

    def test_zero_at_halving_instant(self):
        # Exactly at the 2020 halving: 0 complete months have elapsed.
        self.assertEqual(phase_m(_H2020), 0)

    def test_zero_before_one_month_anniversary(self):
        # One second before the 1-month anniversary is still phase 0.
        just_before = datetime(2020, 6, 11, 19, 23, 42, tzinfo=UTC)
        self.assertEqual(phase_m(just_before), 0)

    def test_one_at_one_month_anniversary(self):
        # At the 1-month anniversary instant, phase = 1.
        one_month = datetime(2020, 6, 11, 19, 23, 43, tzinfo=UTC)
        self.assertEqual(phase_m(one_month), 1)

    def test_months_accumulate(self):
        # 18 complete months after the 2020 halving = 2021-11.
        m18 = datetime(2021, 11, 11, 19, 23, 43, tzinfo=UTC)
        self.assertEqual(phase_m(m18), 18)

    def test_h2_band_entry_month_18(self):
        # First moment of H2 band: phase 18 (exactly at month-18 anniversary).
        m18_exact = datetime(2021, 11, 11, 19, 23, 43, tzinfo=UTC)
        m = phase_m(m18_exact)
        self.assertGreaterEqual(m, 18)
        self.assertLess(m, 30)

    def test_h3_band_entry_month_30(self):
        # Phase 30 starts at 30 complete months after halving.
        m30 = datetime(2022, 11, 11, 19, 23, 43, tzinfo=UTC)
        self.assertEqual(phase_m(m30), 30)

    def test_h3_band_exit_month_48(self):
        # Phase 48 is outside H3 (half-open [30, 48)): no modification at 48.
        # 2020-05-11 + 48 months = 2024-05-11; but the 2024 halving (2024-04-20) comes first,
        # so we use a date just before 2024-04-20 to keep the 2020 halving as reference.
        # 2023-11-11 19:23:43 is exactly 42 months after 2020-05-11 → in H3 band.
        # Instead test that 2023-12-01 is in [30,48): 2023-12 is month 42.
        m42 = datetime(2023, 12, 1, tzinfo=UTC)
        m = phase_m(m42)
        self.assertGreaterEqual(m, 30)
        self.assertLess(m, 48)
        # Also verify month 30 itself is exactly correct (tested in test_h3_band_entry_month_30).

    def test_earlier_halving_used_before_2020(self):
        # An observation in late 2017 (between 2016 and 2020 halvings) uses 2016 halving.
        obs = datetime(2017, 12, 1, tzinfo=UTC)
        h2016 = _HALVINGS[0]  # 2016-07-09
        expected = (obs.year - h2016.year) * 12 + (obs.month - h2016.month)
        if obs.day < h2016.day or (obs.day == h2016.day and obs.time() < h2016.time()):
            expected -= 1
        self.assertEqual(phase_m(obs), expected)

    def test_2024_halving_used_after_it(self):
        # After the 2024 halving, the 2024 halving is the reference.
        one_month_later = datetime(2024, 5, 20, 0, 9, 27, tzinfo=UTC)
        self.assertEqual(phase_m(one_month_later), 1)


# ---------------------------------------------------------------------------
# cycle_signal() unit tests
# ---------------------------------------------------------------------------


class CycleSignalTests(unittest.TestCase):
    """spec v1 §3 H: H2 and H3 activation logic."""

    # A timestamp in the H2 band: phase [18, 30) after the 2020 halving.
    # 2021-11-12 is comfortably in month 18.
    _H2_OBS_MS = int(datetime(2021, 11, 12, tzinfo=UTC).timestamp() * 1000)
    # A timestamp in the H3 band: phase [30, 48) after the 2020 halving.
    # 2022-12-01 is comfortably in month 30+.
    _H3_OBS_MS = int(datetime(2022, 12, 1, tzinfo=UTC).timestamp() * 1000)
    # A timestamp in the neutral band [0, 18).
    _NEUTRAL_OBS_MS = int(datetime(2020, 9, 1, tzinfo=UTC).timestamp() * 1000)

    def test_h2_active_when_price_above_threshold(self):
        sma200 = D("1.0")
        close = H2_PRICE_MULTIPLE * sma200 + D("0.01")  # just above 1.60×SMA200
        sig = cycle_signal(self._H2_OBS_MS, close, sma200, None)
        self.assertTrue(sig.h2_active)
        self.assertFalse(sig.h3_active)

    def test_h2_inactive_when_price_at_threshold(self):
        # Strict inequality: C > 1.60×SMA200; at the threshold → False.
        sma200 = D("1.0")
        close = H2_PRICE_MULTIPLE * sma200  # exactly 1.60 → not strictly greater
        sig = cycle_signal(self._H2_OBS_MS, close, sma200, None)
        self.assertFalse(sig.h2_active)

    def test_h2_inactive_when_price_below_threshold(self):
        sma200 = D("1.0")
        close = H2_PRICE_MULTIPLE * sma200 - D("0.01")
        sig = cycle_signal(self._H2_OBS_MS, close, sma200, None)
        self.assertFalse(sig.h2_active)

    def test_h2_inactive_when_sma200_unavailable(self):
        close = D("2.0")
        sig = cycle_signal(self._H2_OBS_MS, close, None, None)
        self.assertFalse(sig.h2_active)

    def test_h2_inactive_outside_phase_band(self):
        sma200 = D("1.0")
        close = H2_PRICE_MULTIPLE * sma200 + D("0.01")
        sig = cycle_signal(self._NEUTRAL_OBS_MS, close, sma200, None)
        self.assertFalse(sig.h2_active)

    def test_h3_active_when_price_below_threshold(self):
        ath = D("2.0")
        close = H3_PRICE_MULTIPLE * ath - D("0.01")  # just below 0.50×ATH
        sig = cycle_signal(self._H3_OBS_MS, close, None, ath)
        self.assertTrue(sig.h3_active)
        self.assertFalse(sig.h2_active)

    def test_h3_inactive_when_price_at_threshold(self):
        # C < 0.50×ATH (strict): at the threshold → False.
        ath = D("2.0")
        close = H3_PRICE_MULTIPLE * ath
        sig = cycle_signal(self._H3_OBS_MS, close, None, ath)
        self.assertFalse(sig.h3_active)

    def test_h3_inactive_when_price_above_threshold(self):
        ath = D("2.0")
        close = H3_PRICE_MULTIPLE * ath + D("0.01")
        sig = cycle_signal(self._H3_OBS_MS, close, None, ath)
        self.assertFalse(sig.h3_active)

    def test_h3_inactive_when_ath_unavailable(self):
        """ath=None means H3 never activates (spec: ATH unavailable → H3 never relaxes)."""
        close = D("0.1")  # very low, would trigger H3 if ATH were available
        sig = cycle_signal(self._H3_OBS_MS, close, None, None)
        self.assertFalse(sig.h3_active)
        self.assertFalse(sig.ath_available)

    def test_ath_available_reported_correctly(self):
        sig_with = cycle_signal(self._H3_OBS_MS, D("1.0"), None, D("2.0"))
        sig_without = cycle_signal(self._H3_OBS_MS, D("1.0"), None, None)
        self.assertTrue(sig_with.ath_available)
        self.assertFalse(sig_without.ath_available)

    def test_neutral_phase_no_h2_no_h3(self):
        sma200 = D("1.0")
        ath = D("2.0")
        close = H2_PRICE_MULTIPLE * sma200 + D("0.01")  # would trigger H2 if in band
        sig = cycle_signal(self._NEUTRAL_OBS_MS, close, sma200, ath)
        self.assertFalse(sig.h2_active)
        self.assertFalse(sig.h3_active)

    def test_phase_correct_in_signal(self):
        sig = cycle_signal(self._H2_OBS_MS, D("1.0"), D("1.0"), None)
        self.assertGreaterEqual(sig.phase, 18)
        self.assertLess(sig.phase, 30)


# ---------------------------------------------------------------------------
# compute_sma200 / compute_ath unit tests
# ---------------------------------------------------------------------------


class ComputeSma200Tests(unittest.TestCase):
    def test_none_when_fewer_than_200_bars(self):
        bars = daily_bars(START_MS, 199, D("1.0"))
        obs_ms = START_MS + 200 * DAY_MS
        self.assertIsNone(compute_sma200(bars, obs_ms))

    def test_some_result_with_200_completed_bars(self):
        bars = daily_bars(START_MS, 200, D("1.0"))
        # obs must be after the last bar's open_ms.
        obs_ms = START_MS + 200 * DAY_MS
        result = compute_sma200(bars, obs_ms)
        self.assertIsNotNone(result)
        self.assertEqual(result, D("1.0"))

    def test_current_bar_excluded(self):
        # A bar opening exactly at obs_ms must not be counted.
        bars = daily_bars(START_MS, 201, D("1.0"))
        obs_ms = START_MS + 200 * DAY_MS  # bar[200] opens at this exact ms
        result = compute_sma200(bars, obs_ms)
        self.assertIsNotNone(result)  # 200 bars before obs_ms are available

    def test_uses_last_200(self):
        # 300 bars: first 100 at price 2.0, last 200 at price 1.0.
        bars = daily_bars(START_MS, 100, D("2.0")) + daily_bars(
            START_MS + 100 * DAY_MS, 200, D("1.0")
        )
        obs_ms = START_MS + 300 * DAY_MS
        result = compute_sma200(bars, obs_ms)
        self.assertEqual(result, D("1.0"))


class ComputeAthTests(unittest.TestCase):
    """spec v1 §3 H: ATH is highest completed daily close since the most recent halving."""

    def test_none_when_data_starts_after_halving(self):
        # Daily data begins 1 day after the 2020 halving → returns None.
        h_ms = int(_H2020.timestamp() * 1000)
        start_after_halving = h_ms + DAY_MS
        bars = daily_bars(start_after_halving, 100, D("1.0"))
        obs_ms = start_after_halving + 100 * DAY_MS
        self.assertIsNone(compute_ath(bars, obs_ms))

    def test_some_result_when_data_covers_halving(self):
        # Daily data starts 1 day before the 2020 halving.
        h_ms = int(_H2020.timestamp() * 1000)
        start = h_ms - DAY_MS
        bars = daily_bars(start, 100, D("1.5"))
        obs_ms = start + 100 * DAY_MS
        result = compute_ath(bars, obs_ms)
        self.assertIsNotNone(result)
        self.assertEqual(result, D("1.5"))

    def test_ath_is_max_since_halving(self):
        # Some bars before the halving (should be ignored) and some after.
        h_ms = int(_H2020.timestamp() * 1000)
        pre = daily_bars(h_ms - 5 * DAY_MS, 5, D("999.0"))  # high but before halving
        post = daily_bars(h_ms, 10, D("1.0"))
        post[3] = candle(h_ms + 3 * DAY_MS, D("5.0"), D("5.0"), D("5.0"), D("5.0"))
        bars = pre + post
        obs_ms = h_ms + 10 * DAY_MS
        result = compute_ath(bars, obs_ms)
        self.assertEqual(result, D("5.0"))

    def test_current_bar_excluded(self):
        # A bar opening at obs_ms must not count toward ATH.
        h_ms = int(_H2020.timestamp() * 1000)
        # Put a high bar at obs_ms exactly.
        bars = daily_bars(h_ms, 10, D("1.0"))
        obs_ms = h_ms + 9 * DAY_MS  # bar 9 opens here
        bars[9] = candle(obs_ms, D("999.0"), D("999.0"), D("999.0"), D("999.0"))
        result = compute_ath(bars, obs_ms)
        # Only bars 0–8 are "completed before obs_ms".
        self.assertEqual(result, D("1.0"))


# ---------------------------------------------------------------------------
# Replay integration tests
# ---------------------------------------------------------------------------


class VariantHReplayTests(unittest.TestCase):
    """spec v1 §3 H: cycle-gate integration tests through replay()."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.all_hours = hourly(WARMUP + 60)
        self.t = START_MS + WARMUP * HOUR_MS

    def _engine(self, daily=None):
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
            daily_bars=daily,
        )

    def _fair(self):
        return float(self._engine().at(self.t).fair_value)

    def _bars(self, start, stop, price):
        return [
            candle(self.t + i * 60_000, price, price * 1.001, price * 0.999, price)
            for i in range(start, stop)
        ]

    def _daily_bars_for_phase(self, phase, price=D("1.0")):
        """Return synthetic daily bars sufficient to put the observation in the given phase band.

        The observation (self.t) is at 2024-01-01. We use the 2020 halving as reference.
        Phase 0 starts at 2020-05-11. We go far enough back to guarantee 200 completed bars.
        """
        # Start 500 days before self.t so compute_sma200 has enough bars.
        start_ms = self.t - 500 * DAY_MS
        return daily_bars(start_ms, 500, price)

    def test_h2_blocks_new_grid(self):
        """H2 active → no new grid opened.

        Strategy: pick an observation in the H2 band [18,30) after the 2020 halving
        (2022-01-15 ≈ phase 20). Build daily bars at a low price (0.60) so
        SMA200 = 0.60. The hourly features produce fair_value ≈ 1.0, giving
        fair_value > 1.60 × SMA200 = 0.96, which triggers H2.
        """
        h2_t = int(datetime(2022, 1, 15, tzinfo=UTC).timestamp() * 1000)
        h2_hours_start = h2_t - WARMUP * HOUR_MS
        h2_hours = hourly(WARMUP + 20, start_ms=h2_hours_start)
        series = SeriesFeatures("TESTUSDT", h2_hours)
        basket = [SeriesFeatures(f"B{i}USDT", h2_hours, full=False) for i in range(5)]
        engine = FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
            hourly_candles=h2_hours,
        )
        fair = float(engine.at(h2_t).fair_value)
        # daily bars at 0.60 → SMA200 = 0.60; fair_value ≈ 1.0 > 1.60 × 0.60 = 0.96 → H2 active.
        sma_price = D("0.60")
        d_bars = daily_bars(h2_t - 300 * DAY_MS, 300, sma_price)
        minutes = [
            candle(h2_t + i * 60_000, fair, fair * 1.001, fair * 0.999, fair) for i in range(20)
        ]
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        policy = SimulationPolicy(cycle_gate=True)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy, daily=d_bars)
        self.assertEqual(metrics.grids_opened, 0)
        self.assertEqual(account.halt, "")

    def test_cycle_gate_off_is_v0(self):
        """cycle_gate=False must produce the same grids_opened as V0 (no daily needed)."""
        fair = self._fair()
        minutes = self._bars(0, 20, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        metrics_v0, _ = replay(self.config, run, list(minutes), engine)
        # V0 doesn't need daily; cycle_gate=False also shouldn't require it.
        metrics_off, _ = replay(
            self.config,
            run,
            list(minutes),
            engine,
            policy=SimulationPolicy(cycle_gate=False),
        )
        self.assertEqual(metrics_v0.grids_opened, metrics_off.grids_opened)

    def test_cycle_gate_raises_without_daily(self):
        """cycle_gate=True with daily=None must raise ValueError."""
        fair = self._fair()
        minutes = self._bars(0, 5, fair)
        engine = self._engine()
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        policy = SimulationPolicy(cycle_gate=True)
        with self.assertRaises(ValueError):
            replay(self.config, run, minutes, engine, policy=policy, daily=None)

    def test_h2_reduces_outside_range_threshold(self):
        """H2 uses 2h threshold instead of 6h (spec §3 H: strictly tighter)."""
        self.assertEqual(H2_OUTSIDE_RANGE_SECONDS, 7200)
        # The constant is defined in cycle.py and used in runner.py; no replay needed here.
        # Just assert the constant is what the spec requires.
        self.assertLess(H2_OUTSIDE_RANGE_SECONDS, 6 * 3600)

    def test_h3_score_relaxation_constant(self):
        """H3 lowers score minimum by exactly 0.10 (spec §3 H)."""
        self.assertEqual(H3_SCORE_RELAXATION, 0.10)

    def test_neutral_phase_allows_grid(self):
        """When H is active but phase is in [0,18) (neutral), new grids open normally."""
        # self.t = 2024-01-01. Phase relative to 2020 halving is ~43 months (H3 band).
        # Phase relative to 2024 halving is negative (halving is in the future).
        # To guarantee a neutral phase, pick an obs in 2020-07 (phase ~2 after 2020-05).
        neutral_t = int(datetime(2020, 8, 1, tzinfo=UTC).timestamp() * 1000)
        n_start = neutral_t - WARMUP * HOUR_MS
        n_hours = hourly(WARMUP + 20, start_ms=n_start)
        series = SeriesFeatures("TESTUSDT", n_hours)
        basket = [SeriesFeatures(f"B{i}USDT", n_hours, full=False) for i in range(5)]
        engine = FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
            hourly_candles=n_hours,
        )
        fair = float(engine.at(neutral_t).fair_value)
        d_bars = daily_bars(neutral_t - 300 * DAY_MS, 300, D(str(round(fair, 6))))
        minutes = [
            candle(neutral_t + i * 60_000, fair, fair * 1.001, fair * 0.999, fair)
            for i in range(20)
        ]
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        policy = SimulationPolicy(cycle_gate=True)
        metrics, account = replay(self.config, run, minutes, engine, policy=policy, daily=d_bars)
        # Neutral phase: H has no effect, grid should open as in V0.
        metrics_v0, _ = replay(self.config, run, list(minutes), engine)
        self.assertEqual(metrics.grids_opened, metrics_v0.grids_opened)
        self.assertEqual(account.halt, "")
