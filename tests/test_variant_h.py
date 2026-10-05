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
from unittest.mock import patch

from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, VariantReport, check_accounting, replay
from crypto_grid_bot.config import load_config
from crypto_grid_bot.domain import CandidateMetrics
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.models import ZERO, Account, MarketRules, Quote
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.strategy.cycle import H2, H3, HALVINGS, CycleSchedule, CycleSignal, phase
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


# Every component 0.65, so a RANGE score of 0.65: below V0's 0.70, not below H3's 0.60.
MIDDLING = CandidateMetrics("TESTUSDT", 0.65, 0.65, 0.65, 0.65, 0.65, 0.0, 0.04, 1e9)


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

    def test_the_ath_is_unavailable_from_a_halving_until_its_days_bar_closes(self):
        # Codex review of #165: from the 2024 halving, 2024-04-20 00:09:27, no daily close
        # has followed the most recent halving until that day's bar closes at midnight, so
        # yesterday's value, measured against the old cycle's ATH, must not stand in.
        halving_day = HALVINGS[2].date()
        # The 2020 halving's day closes at 3 (the old cycle's ATH), the day before the 2024
        # halving at 1, the halving's own day at 2, and the day after it at 0.99.
        before = (halving_day - H2020.date()).days - 1
        schedule = CycleSchedule(days(H2020.date(), [3] + [1] * before + [2, 0.99, 1]))

        def at(*fields):
            return schedule.at(ms(utc(*fields)))

        self.assertTrue(at(2024, 4, 20, 0, 5).discounted)  # before it: 1 < 0.50 x 3
        for when in ((2024, 4, 20, 0, 10), (2024, 4, 20, 23, 59)):
            with self.subTest(when=when):
                self.assertEqual(CycleSignal("2024-04-19", False, None), at(*when))
        # From midnight the halving's day has closed, at 2: the new cycle's ATH.
        self.assertFalse(at(2024, 4, 21, 0, 0).discounted)  # 2 is not below 0.50 x 2
        self.assertTrue(at(2024, 4, 22, 0, 0).discounted)  # 0.99 < 0.50 x 2, not x 3
        # A halving exactly at a midnight counts too: the bar closing at that instant
        # closed no later than the halving, so it is not since it.
        midnight = ms(utc(2024, 4, 20))
        with patch("crypto_grid_bot.strategy.cycle.HALVING_MS", (midnight,)):
            self.assertIsNone(schedule.at(midnight).discounted)
            self.assertTrue(schedule.at(midnight - 1).discounted)
        # H2's comparison, which does not depend on the cycle, is left as it is.
        overextended = CycleSchedule(days(H2020.date(), [1] * (before + 1) + [2, 2, 2]))
        self.assertTrue(overextended.at(ms(utc(2024, 4, 21, 12))).overextended)

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
        middling = replace(MIDDLING, symbol="DEMOUSDT")
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

    def test_h3_relaxes_only_the_decision_to_open_a_new_grid(self):
        # Codex review of #165: "for new grids only" (spec v1 §3 H). A flat account at a
        # score of 0.65 opens a grid, journaled as opened only because of H3.
        when = utc(2023, 6, 15, 12)  # phase 37
        discounted = CycleSignal("2023-06-14", False, True)
        middling = replace(MIDDLING, symbol="DEMOUSDT")
        _, (opened,) = self.step_all(H, [frame_at(when, discounted, middling)])
        self.assertEqual("open_grid", opened["decision"])
        self.assertTrue(opened["cycle"]["h3_only"])
        # A grid that exists at a score of 0.65 pauses and drains exactly as in V0.
        frames = [
            frame_at(when, discounted),  # eligible as in V0: the grid opens
            frame_at(when + timedelta(seconds=1), discounted, middling),
        ]
        h, h_reports = self.step_all(H, frames)
        v0, v0_reports = self.step_all(None, frames)
        self.assertEqual(["open_grid", "pause"], [r["decision"] for r in h_reports])
        self.assertNotIn("h3_only", h_reports[0]["cycle"])
        self.assertEqual([r["decision"] for r in v0_reports], [r["decision"] for r in h_reports])
        self.assertEqual(v0.to_dict(), h.to_dict())
        self.assertTrue(h_reports[1]["cancelled"])  # its buys, cancelled as V0 cancels them
        self.assertFalse(h.orders)


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
        self.at(self.MIDNIGHT)

    def at(self, midnight):
        """Hourly warm-up and two hours of minutes, 23:00 to 00:59, across ``midnight``."""
        self.config = load_config(ROOT / "config/default.toml")
        rules = MarketRules("TESTUSDT", D("0.0001"), D("0.1"), D("5"))
        self.run_config = RunConfig("TESTUSDT", "high_first", False, rules, D(100), D("0.0005"))
        start = ms(midnight) - HOUR_MS
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
        self.bars = scenario(midnight.date())

    def run_replay(self, bars, minutes, policy=H):
        daily = daily_klines(bars)
        return replay(self.config, self.run_config, minutes, self.engine, policy, daily)

    def test_unclosed_and_future_bars_never_reach_a_decision(self):
        # Until midnight, the overextended bar of 2022-01-15 has not closed.
        before = self.minutes[:60]
        metrics, account = self.run_replay(self.bars, before)
        self.assertEqual([], check_accounting(self.run_config, metrics, account))
        self.assertEqual({"None": 60}, metrics.variant["cycle_rules_by_bar"])
        for factor in (D(1000), D("0.001")):
            with self.subTest(factor=factor):
                bars = changed(self.bars, self.MIDNIGHT.date() - timedelta(days=1), factor)
                other, other_account = self.run_replay(bars, before)
                self.assertEqual(asdict(metrics), asdict(other))
                self.assertEqual(account.to_dict(), other_account.to_dict())
        # Across midnight: that bar is used from the minute it closes, and the bars after
        # it, changed beyond recognition, still change nothing.
        across, _ = self.run_replay(self.bars, self.minutes)
        self.assertEqual({"None": 60, H2: 60}, across.variant["cycle_rules_by_bar"])
        self.assertEqual({"20": 120}, across.variant["cycle_phases_by_bar"])
        self.assertEqual(0, across.variant["cycle_ath_unavailable_bars"])
        moved = changed(self.bars, self.MIDNIGHT.date(), D(1000))
        self.assertEqual(asdict(across), asdict(self.run_replay(moved, self.minutes)[0]))

    def test_v0_ignores_the_cycle_and_h_refuses_a_missing_daily_history(self):
        daily = daily_klines(self.bars)
        v0 = replay(self.config, self.run_config, self.minutes, self.engine, None, None)
        with_daily = replay(self.config, self.run_config, self.minutes, self.engine, None, daily)
        self.assertEqual(asdict(v0[0]), asdict(with_daily[0]))
        self.assertEqual({}, v0[0].variant)
        with self.assertRaisesRegex(ValueError, "daily history"):
            replay(self.config, self.run_config, self.minutes, self.engine, H, None)

    def test_bars_after_a_halving_report_its_ath_unavailable_until_midnight(self):
        # Codex review of #165: the 2024 halving falls at 00:09:27 on 2024-04-20. From the
        # bar of 00:09, whose last quote is at 00:09:29, to that of 00:59, 51 bars end with
        # no completed close since it; the 60 bars before midnight and the 9 from 00:00 to
        # 00:08 still have the 2020 cycle's ATH. The phase turns at the same instant.
        self.at(utc(2024, 4, 20))
        metrics, account = self.run_replay(self.bars, self.minutes)
        self.assertEqual([], check_accounting(self.run_config, metrics, account))
        self.assertEqual(51, metrics.variant["cycle_ath_unavailable_bars"])
        self.assertEqual({"47": 69, "0": 51}, metrics.variant["cycle_phases_by_bar"])

    def test_each_quote_reads_the_signal_at_its_own_instant(self):
        # Codex review of #165: in the bar of 00:09 on 2024-04-20, the quotes at +0, +9
        # and +19 s precede the 00:09:27 halving and keep the old cycle's value (2 is not
        # below 0.50 x 3); the one at +29 s follows it and has no ATH.
        self.at(utc(2024, 4, 20))
        seen, real_step = [], PaperSimulator.step

        def recording(simulator, account, frame):
            seen.append((frame.quote.observed_at[11:19], frame.cycle.discounted))
            return real_step(simulator, account, frame)

        with patch.object(PaperSimulator, "step", recording):
            self.run_replay(self.bars, self.minutes)
        minute = [entry for entry in seen if entry[0].startswith("00:09:")]
        expected = [("00:09:00", False), ("00:09:09", False), ("00:09:19", False)]
        self.assertEqual([*expected, ("00:09:29", None)], minute)

    def test_grids_only_h3_opened_and_unavailable_aths_are_reported(self):
        # Every candidate scores 0.65. At 00:00 on 2023-06-16 (phase 37) the bar of
        # 2023-06-15 closes at 1, below half the ATH of 3: from then H3 opens grids, and
        # each pauses at its next frame, as V0 pauses a grid scored below 0.70, without a
        # fill: their P&L is zero. Without H no grid opens at all.
        self.at(utc(2023, 6, 16))
        middling = replace(MIDDLING, spread_pct=0.05)
        with patch("crypto_grid_bot.backtest.replay.candidate_for", lambda *a, **k: middling):
            h, account = self.run_replay(self.bars, self.minutes)
            v0, _ = self.run_replay(self.bars, self.minutes, None)
        self.assertEqual([], check_accounting(self.run_config, h, account))
        self.assertEqual({"None": 60, H3: 60}, h.variant["cycle_rules_by_bar"])
        grids = h.variant["cycle_h3_grids"]
        self.assertEqual((h.grids_opened, D(0)), (grids["opened"], D(grids["pnl"])))
        self.assertGreater(grids["opened"], 1)
        self.assertEqual(0, v0.grids_opened)
        # A daily history that starts after the halving's day has no ATH: H3 never acts.
        late = [(open_ms, close) for open_ms, close in self.bars[1:]]
        with patch("crypto_grid_bot.backtest.replay.candidate_for", lambda *a, **k: middling):
            h, _ = self.run_replay(late, self.minutes)
        self.assertEqual(120, h.variant["cycle_ath_unavailable_bars"])
        self.assertEqual({"opened": 0, "pnl": "0"}, h.variant["cycle_h3_grids"])
        self.assertEqual({"None": 120}, h.variant["cycle_rules_by_bar"])


class H3PnlTests(TestCase):
    """The P&L reported for the grids only H3 opened, from constructed frames."""

    RULES = MarketRules("TESTUSDT", D("0.0001"), D("0.1"), D("5"))
    STAMP = utc(2023, 6, 16).isoformat()

    def step(self, bid, *fills, opened=False, ended=False):
        """One frame at ``bid`` after ``fills`` of 4 units, each (order ID, side, price,
        fee); returns its quote and the total equity after it."""
        account = self.account
        for _, side, price, fee in fills:
            sign = 1 if side == "buy" else -1
            account.inventory += sign * 4
            account.cash -= sign * 4 * D(price) + D(fee)
        account.grid_lower = ZERO if ended else D("0.9")
        quote = Quote("q", "TESTUSDT", self.STAMP, self.STAMP, D(bid), D(bid), D(9), D(9))
        equity = account.equity(quote, self.RULES) + account.pending + account.secured
        frame = {
            "regime": "range",
            "fills": [
                {"order_id": order_id, "price": price, "quantity": "4", "fee": fee}
                for order_id, _, price, fee in fills
            ],
            "opened": opened,
            "cycle": {"h3_only": True} if opened else {},
        }
        self.report.frame(frame, account, quote, equity, ZERO)
        return quote, equity

    def h3_grids(self, sold):
        """An H3-only grid opens while the account holds a residue of 4, below the
        minimum, and buys 4 at 1.0 and sells them at 1.05 while the price moves. Then an
        exit sells the residue and the grid ends, or, unless ``sold``, the run ends with
        the residue held and the grid open. Returns the H3 grids' row field."""
        self.account = Account.start(D(100))
        self.account.cash, self.account.inventory = D(96), D(4)
        self.report = VariantReport(H, (), self.RULES)
        self.step("1.0", opened=True)
        self.step("1.0", ("g/buy/0", "buy", "1.0", "0.004"))
        self.step("1.15")
        self.step("1.05", ("g/buy/0/sell", "sell", "1.05", "0.0042"))
        if sold:
            self.step("1.3", ("exit/1", "sell", "1.2993", "0.0051972"))
            last = self.step("1.2", ended=True)
        else:
            last = self.step("1.2")
        return self.report.fields(*last)["cycle_h3_grids"]

    def test_a_residue_held_when_an_h3_grid_opens_is_not_its_pnl(self):
        # Codex review of #165: the harvest that opens an H3-only grid may leave a residue
        # below the minimum, whose moves and sale were reported as the grid's P&L. The
        # grid's P&L is its own round trip's, whatever the residue does.
        own = 4 * D("1.05") - D("0.0042") - (4 * D("1.0") + D("0.004"))
        for sold in (True, False):
            with self.subTest(sold=sold):
                grids = self.h3_grids(sold)
                self.assertEqual((1, own), (grids["opened"], D(grids["pnl"])))
