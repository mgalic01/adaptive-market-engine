"""Variant H (experiment spec v1, section 3 H): Bitcoin cycle context.

Daily closes, frames and minute bars are constructed to hit each rule; nothing here is
backtest evidence, and no market data is read. Every date is synthetic and before 2025.
"""

import math
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal as D
from pathlib import Path
from unittest import TestCase

from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, check_accounting, replay
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.models import Account, MarketRules
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.strategy.cycle import H2, HALVINGS, CycleSchedule, CycleSignal, phase
from crypto_grid_bot.strategy.daily_sma import DAY_MS

ROOT = Path(__file__).resolve().parents[1]
H = SimulationPolicy(cycle_gate=True)
H2020 = HALVINGS[1]  # 2020-05-11 19:23:43 UTC


def utc(*fields):
    return datetime(*fields, tzinfo=UTC)


def midnight(day):
    return datetime.combine(day, time(), UTC)


def ms(when):
    return int(when.timestamp()) * 1000  # whole seconds only


def days(first, closes):
    """(open ms, close) per UTC day from the date ``first``; a None close is a missing day."""
    start = ms(midnight(first))
    return [(start + i * DAY_MS, D(str(c))) for i, c in enumerate(closes) if c is not None]


def scenario(today):
    """Daily bars from the 2020 halving's day through two days after ``today``.
    Yesterday's close (2) is H2-overextended, against an SMA200 of 1.005, and not
    H3-discounted, against the halving day's ATH of 3."""
    yesterday = (today - H2020.date()).days - 1
    return days(H2020.date(), [3] + [1] * (yesterday - 1) + [2, 1, 1, 1])


def changed(bars, today, factor):
    """Today's bar and every later one moved by ``factor``, and thirty more days appended."""
    cut = ms(midnight(today))
    moved = [(open_ms, close * factor if open_ms >= cut else close) for open_ms, close in bars]
    last = moved[-1][0]
    return moved + [(last + k * DAY_MS, D(9) * factor) for k in range(1, 31)]


def frame_at(when, cycle, candidate=None):
    """The demo engine's frame (a RANGE market, an eligible pair) at ``when``."""
    template = demo_frames(1)[0]
    stamp = when.isoformat()
    return replace(
        template,
        quote=replace(template.quote, event_id=f"h/{stamp}", observed_at=stamp, received_at=stamp),
        signals=replace(template.signals, observed_at=when),
        candidate=candidate or template.candidate,
        allow_new_grid=True,
        cycle=cycle,
    )


class PhaseTests(TestCase):
    def test_whole_months_turn_at_the_anniversary_instant(self):
        second = timedelta(seconds=1)
        self.assertEqual(0, phase(H2020))
        self.assertEqual(46, phase(H2020 - second))  # still the 2016 halving's cycle
        self.assertEqual(0, phase(utc(2020, 6, 11, 19, 23, 42)))
        self.assertEqual(1, phase(utc(2020, 6, 11, 19, 23, 43)))
        self.assertEqual(17, phase(utc(2021, 11, 11, 19, 23, 42)))
        self.assertEqual(18, phase(utc(2021, 11, 11, 19, 23, 43)))  # H2's band opens
        self.assertEqual(30, phase(utc(2022, 11, 11, 19, 23, 43)))  # H3's band opens
        self.assertEqual(16, phase(utc(2017, 12, 1)))  # 2016-07-09: day 1 < day 9
        self.assertEqual(1, phase(utc(2024, 5, 20, 0, 9, 27)))  # after the 2024 halving
        self.assertIsNone(phase(HALVINGS[0] - second))  # before the first halving


class CycleScheduleTests(TestCase):
    def test_overextension_reads_the_signal_days_close_and_a_gapless_sma200(self):
        first = date(2021, 6, 1)
        # 200 days at 1, then 2 (SMA200 1.005: 2 > 1.60 x 1.005), then 1 again.
        schedule = CycleSchedule(days(first, [1] * 200 + [2, 1]))
        day_200 = ms(midnight(first)) + 200 * DAY_MS
        self.assertFalse(schedule.at(day_200 + DAY_MS - 1).overextended)  # day 199's close
        self.assertTrue(schedule.at(day_200 + DAY_MS).overextended)  # day 200's, now closed
        self.assertFalse(schedule.at(day_200 + 2 * DAY_MS).overextended)
        # A missing day inside the window leaves SMA200 undefined: no H2 (D6).
        gap = CycleSchedule(days(first, [1] * 50 + [None] + [1] * 149 + [2]))
        self.assertFalse(gap.at(day_200 + DAY_MS).overextended)

    def test_ath_runs_from_the_halving_days_bar_through_the_signal_day(self):
        # The 2020-05-11 bar opened before the halving instant and closed after it: its
        # close is the first since the halving, so it counts.
        halving_day = H2020.date()
        start = ms(midnight(halving_day))
        schedule = CycleSchedule(days(halving_day, [100, 40, 45]))
        self.assertTrue(schedule.at(start + 2 * DAY_MS).discounted)  # 40 < 0.50 x 100
        self.assertTrue(schedule.at(start + 3 * DAY_MS).discounted)
        # A history that starts after that bar has no ATH: H3 never relaxes.
        late = CycleSchedule(days(halving_day + timedelta(days=1), [40, 45, 46]))
        self.assertIsNone(late.at(start + 3 * DAY_MS).discounted)
        # Nor does one that misses a day since the halving.
        gap = CycleSchedule(days(halving_day, [100, None, 40, 45]))
        self.assertIsNone(gap.at(start + 4 * DAY_MS).discounted)
        # A close at exactly half the ATH is not below it.
        exact = CycleSchedule(days(halving_day, [100, 50]))
        self.assertFalse(exact.at(start + 2 * DAY_MS).discounted)

    def test_a_new_halving_starts_a_new_ath(self):
        before = HALVINGS[2].date() - timedelta(days=3)  # 2024-04-17
        schedule = CycleSchedule(days(before, [500, 500, 500, 100, 45]))
        self.assertTrue(schedule.at(ms(midnight(before)) + 5 * DAY_MS).discounted)

    def test_outside_the_history_there_is_nothing_to_read(self):
        signal = CycleSchedule([]).at(ms(utc(2022, 1, 16, 12)))
        self.assertEqual(CycleSignal("2022-01-15"), signal)


class NoLookaheadTests(TestCase):
    """At any moment of day ``d``, the bar of ``d`` and every later bar are unknown."""

    H2_TODAY = date(2022, 1, 16)  # phase 20: H2's band
    H3_TODAY = date(2023, 6, 15)  # phase 37: H3's band

    def test_todays_and_later_bars_never_change_the_signal(self):
        for today in (self.H2_TODAY, self.H3_TODAY):
            bars = scenario(today)
            schedule = CycleSchedule(bars)
            for offset in (
                timedelta(0),
                timedelta(minutes=1),
                timedelta(hours=15),
                timedelta(hours=23, minutes=59),
            ):
                when = midnight(today) + offset
                expected = schedule.at(ms(when))
                self.assertEqual((today - timedelta(days=1)).isoformat(), expected.day)
                self.assertEqual((True, False), (expected.overextended, expected.discounted))
                # Moved far up and far down: read anywhere, as C, in SMA200 or in the
                # ATH, today's close would flip a comparison.
                for factor in (D(1000), D("0.001")):
                    with self.subTest(today=today, offset=offset, factor=factor):
                        other = CycleSchedule(changed(bars, today, factor)).at(ms(when))
                        self.assertEqual(expected, other)
                        self.assertEqual(expected.rule(when), other.rule(when))
        # From the instant it closes, today's bar is used.
        bars, tomorrow = scenario(self.H2_TODAY), ms(midnight(self.H2_TODAY)) + DAY_MS
        moved = CycleSchedule(changed(bars, self.H2_TODAY, D(1000)))
        self.assertNotEqual(CycleSchedule(bars).at(tomorrow), moved.at(tomorrow))

    def test_the_rule_follows_yesterdays_bar_across_midnight(self):
        schedule = CycleSchedule(scenario(self.H2_TODAY))
        start = midnight(self.H2_TODAY)
        just_before = start - timedelta(milliseconds=1)
        # Yesterday's bar, overextended, closes at midnight; until then the one before.
        self.assertIsNone(schedule.at(ms(start) - 1).rule(just_before))
        self.assertEqual(H2, schedule.at(ms(start)).rule(start))
        later = start + timedelta(days=1)  # today's bar closes at 1: H2 ends
        self.assertIsNone(schedule.at(ms(later)).rule(later))

    def test_signal_from_an_unclosed_bar_is_rejected(self):
        noon = utc(2022, 1, 16, 12)
        CycleSignal("2022-01-15", True).validate(noon)
        with self.assertRaisesRegex(ValueError, "not closed"):
            CycleSignal("2022-01-16", True).validate(noon)
        for bad in (CycleSignal("2022-1-15"), CycleSignal("2022-01-15", 1), CycleSignal(5)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bad.validate(noon)

    def test_a_stale_signal_changes_nothing(self):
        noon = utc(2022, 1, 16, 12)
        self.assertEqual(H2, CycleSignal("2022-01-15", True).rule(noon))
        self.assertIsNone(CycleSignal("2022-01-14", True).rule(noon))

    def test_engine_halts_rather_than_act_on_lookahead(self):
        simulator = PaperSimulator(
            Path(":memory:"), load_config(ROOT / "config/default.toml"), MarketRules(), policy=H
        )
        self.addCleanup(simulator.close)
        noon = utc(2022, 1, 16, 12)
        report = simulator.process(frame_at(noon, CycleSignal("2022-01-16", True)))
        self.assertEqual("halt", report["decision"])
        self.assertIn("not closed", report["reason"])
        self.assertFalse(simulator.store.read().orders)


class EngineTests(TestCase):
    """The engine under variant H, frame by frame on the demo market."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")

    def step_all(self, policy, frames):
        simulator = PaperSimulator(Path(":memory:"), self.config, MarketRules(), policy=policy)
        simulator.close()  # step() uses no store
        account = Account.start(D(100))
        return account, [simulator.step(account, frame) for frame in frames]

    def test_h2_blocks_a_new_grid(self):
        when = utc(2022, 1, 16, 12)  # phase 20
        _, (report,) = self.step_all(H, [frame_at(when, CycleSignal("2022-01-15", True))])
        self.assertEqual(("cash", "cycle H2: overextended"), (report["decision"], report["reason"]))
        self.assertEqual({"day": "2022-01-15", "phase": 20, "rule": H2}, report["cycle"])
        _, (opened,) = self.step_all(H, [frame_at(when, CycleSignal("2022-01-15", False))])
        self.assertEqual("open_grid", opened["decision"])

    def test_h2_turning_on_exits_a_timer_already_past_two_hours_at_once(self):
        # A grid opens at 21:00, and from 21:10 the bid is above its band. At midnight
        # the newly closed bar is overextended: 2 h 50 min have elapsed, at least 2 h, so
        # the grid exits there, while V0's 6 h threshold keeps it.
        evening = utc(2022, 1, 15, 21)
        calm, hot = CycleSignal("2022-01-14", False), CycleSignal("2022-01-15", True)
        tick = MarketRules().tick_size
        frames = [frame_at(evening, calm)]
        for minute in range(10, 181):
            when = evening + timedelta(minutes=minute)
            frame = frame_at(when, hot if when.day == 16 else calm)
            quote = replace(frame.quote, bid=D("0.02500"), ask=D("0.02500") + tick)
            frames.append(replace(frame, quote=quote))
        for policy, exited in ((H, utc(2022, 1, 16).isoformat()), (None, "")):
            with self.subTest(policy=policy):
                account, reports = self.step_all(policy, frames)
                self.assertEqual("open_grid", reports[0]["decision"])
                self.assertEqual(exited, account.range_exit_since)

    def test_h3_lowers_the_score_minimum_and_nothing_else(self):
        when = utc(2023, 6, 15, 12)  # phase 37
        discounted, plain = CycleSignal("2023-06-14", False, True), CycleSignal("2023-06-14")
        middling = replace(  # a score of 0.65: below 0.70, not below 0.60
            demo_frames(1)[0].candidate,
            range_quality=0.65,
            net_grid_edge=0.65,
            liquidity_quality=0.65,
            downside_quality=0.65,
            data_quality=0.65,
        )
        cases = (
            (discounted, middling, "open_grid"),
            (plain, middling, "pause"),
            (discounted, replace(middling, spread_pct=0.5), "pause"),  # another check fails
            (discounted, replace(middling, range_quality=0.0), "pause"),  # 0.455 < 0.60
        )
        for cycle, candidate, decision in cases:
            with self.subTest(cycle=cycle, candidate=candidate):
                _, (report,) = self.step_all(H, [frame_at(when, cycle, candidate)])
                self.assertEqual(decision, report["decision"])
        # Without the cycle gate the same frame pauses, as in V0.
        _, (v0,) = self.step_all(None, [frame_at(when, discounted, middling)])
        self.assertEqual("pause", v0["decision"])


def hourly(count, start_ms):
    candles, previous = [], 1.0
    for i in range(count):
        close = 1.0 + 0.08 * math.sin(2 * math.pi * i / 24)
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        o, h, lo, c = (D(str(round(x, 6))) for x in (previous, high, low, close))
        candles.append(Kline(start_ms + i * HOUR_MS, o, h, lo, c, D(10**6), D(10**6) * c, D(0)))
        previous = close
    return candles


def daily_klines(bars):
    return [Kline(open_ms, c, c, c, c, D(1), c, D(0)) for open_ms, c in bars]


class ReplayWiringTests(TestCase):
    """Variant H through replay() across a midnight, on synthetic klines; modelled on the
    structure features' lookahead test in tests/test_backtest_replay.py."""

    MIDNIGHT = utc(2022, 1, 16)  # phase 20: H2's band
    WARMUP = 800

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        rules = MarketRules("TESTUSDT", D("0.0001"), D("0.1"), D("5"))
        self.run_config = RunConfig("TESTUSDT", "high_first", False, rules, D(100), D("0.0005"))
        start = ms(self.MIDNIGHT) - HOUR_MS
        candles = hourly(self.WARMUP, start - self.WARMUP * HOUR_MS)
        series = SeriesFeatures("TESTUSDT", candles)
        basket = [SeriesFeatures(f"B{i}USDT", candles, full=False) for i in range(5)]
        self.engine = FeatureEngine(
            series,
            series,
            basket,
            range_atr_multiple=2.0,
            levels=8,
            minimum_cost_multiple=3.0,
            round_trip_cost=0.0035,
        )
        fair = float(self.engine.at(start).fair_value)
        # 23:00 to 00:59 UTC, across the midnight at which the overextended bar closes.
        self.minutes = [
            Kline(
                start + i * 60_000,
                *(D(str(round(fair * f, 6))) for f in (1, 1.001, 0.999, 1)),
                D(10**6),
                D(10**6),
                D(5 * 10**5),
            )
            for i in range(120)
        ]
        self.bars = scenario(self.MIDNIGHT.date())

    def run_replay(self, bars, minutes):
        return replay(self.config, self.run_config, minutes, self.engine, H, daily_klines(bars))

    def test_unclosed_and_future_bars_never_reach_a_decision(self):
        # Until midnight, the overextended bar of 2022-01-15 has not closed.
        before = self.minutes[:60]
        metrics, account = self.run_replay(self.bars, before)
        self.assertEqual([], check_accounting(self.run_config, metrics, account))
        self.assertEqual({"None": 60}, metrics.variant_counts["cycle_rules_by_bar"])
        for factor in (D(1000), D("0.001")):
            with self.subTest(factor=factor):
                bars = changed(self.bars, self.MIDNIGHT.date() - timedelta(days=1), factor)
                other, other_account = self.run_replay(bars, before)
                self.assertEqual(asdict(metrics), asdict(other))
                self.assertEqual(account.to_dict(), other_account.to_dict())
        # Across midnight: that bar is used from the minute it closes, and the bars after
        # it, changed beyond recognition, still change nothing.
        across, _ = self.run_replay(self.bars, self.minutes)
        self.assertEqual({"None": 60, H2: 60}, across.variant_counts["cycle_rules_by_bar"])
        self.assertEqual({"20": 120}, across.variant_counts["cycle_phases_by_bar"])
        moved = changed(self.bars, self.MIDNIGHT.date(), D(1000))
        self.assertEqual(asdict(across), asdict(self.run_replay(moved, self.minutes)[0]))

    def test_v0_ignores_the_cycle_and_h_refuses_a_missing_daily_history(self):
        daily = daily_klines(self.bars)
        v0 = replay(self.config, self.run_config, self.minutes, self.engine, None, None)
        with_daily = replay(self.config, self.run_config, self.minutes, self.engine, None, daily)
        self.assertEqual(asdict(v0[0]), asdict(with_daily[0]))
        self.assertEqual({}, v0[0].variant_counts)
        with self.assertRaisesRegex(ValueError, "daily history"):
            replay(self.config, self.run_config, self.minutes, self.engine, H, None)
