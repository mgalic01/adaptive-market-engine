"""Variant A (experiment spec v1, section 3 A): the daily SMA50/SMA200 trend switch.

Prices and daily closes are constructed to hit each rule; nothing here is backtest
evidence, and no market data is read.
"""

import json
import math
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crypto_grid_bot.backtest.features import HOUR_MS, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, check_accounting, replay
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.control import decode_frame, resume_paper
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.models import ZERO, Account, MarketRules, floor_step
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode
from crypto_grid_bot.simulation.trend_switch import (
    DAY_MS,
    DOWN,
    MIDDLE,
    RECOVERING,
    UNAVAILABLE,
    UP,
    TrendSchedule,
    TrendSignal,
    classify_days,
    effective_state,
    next_state,
    simple_moving_average,
    starts_down_sequence,
)

ROOT = Path(__file__).resolve().parents[1]
DAY0 = datetime(2026, 1, 1, tzinfo=UTC)
DAY0_MS = int(DAY0.timestamp() * 1000)
A = SimulationPolicy(trend_switch=True)
TICK = MarketRules().tick_size


def day(n):
    return (DAY0.date() + timedelta(days=n)).isoformat()


def signal(n, state, last_down=None):
    return TrendSignal(day(n), state, None if last_down is None else day(last_down))


def daily(closes, first_ms=DAY0_MS, skip=()):
    """Daily Klines with the given closes, one per UTC day; days in ``skip`` are absent."""
    bars = []
    for index, close in enumerate(closes):
        if index in skip:
            continue
        price = D(str(close))
        bars.append(Kline(first_ms + index * DAY_MS, price, price, price, price, D(1), price, D(0)))
    return bars


def frame_at(when, bid="0.02300", *, ask=None, size="100000", trend=None):
    template = demo_frames(1)[0]
    stamp = when.isoformat()
    bid = D(str(bid))
    return replace(
        template,
        quote=replace(
            template.quote,
            event_id=f"a/{stamp}",
            observed_at=stamp,
            received_at=stamp,
            bid=bid,
            ask=D(str(ask)) if ask is not None else bid + TICK,
            bid_size=D(size),
            ask_size=D(size),
        ),
        signals=replace(template.signals, observed_at=when),
        allow_new_grid=True,
        trend=trend,
    )


class SmaArithmeticTests(TestCase):
    def test_windows_of_one_to_two_hundred(self):
        closes = [D(i) for i in range(1, 201)]
        # (1 + ... + 200) / 200 and (151 + ... + 200) / 50, both exact.
        self.assertEqual(D("100.5"), simple_moving_average(closes, 199, 200))
        self.assertEqual(D("175.5"), simple_moving_average(closes, 199, 50))
        self.assertEqual(D("25.5"), simple_moving_average(closes, 49, 50))
        self.assertIsNone(simple_moving_average(closes, 198, 200))
        self.assertIsNone(simple_moving_average(closes, 48, 50))

    def test_fractional_closes_are_exact_decimals(self):
        closes = [D("2")] * 199 + [D("2.37")]
        # (199 x 2 + 2.37) / 200 = 400.37 / 200 and (49 x 2 + 2.37) / 50 = 100.37 / 50.
        self.assertEqual(D("2.00185"), simple_moving_average(closes, 199, 200))
        self.assertEqual(D("2.0074"), simple_moving_average(closes, 199, 50))

    def test_a_missing_day_inside_the_window_leaves_the_average_undefined(self):
        closes = [D(i) for i in range(1, 201)]
        closes[150] = None
        self.assertIsNone(simple_moving_average(closes, 199, 200))
        self.assertIsNone(simple_moving_average(closes, 199, 50))
        # A window that ends before the gap is unaffected.
        self.assertEqual(D("125.5"), simple_moving_average(closes, 149, 50))

    def test_classified_averages_match_the_hand_values(self):
        (first,) = classify_days(daily([D(i) for i in range(1, 201)]))
        self.assertEqual((D("100.5"), D("175.5"), D(200)), (first.sma200, first.sma50, first.close))


class StateMachineTests(TestCase):
    def test_transition_table(self):
        sma50, sma200 = D(90), D(100)
        above, middle, down = D(101), D(95), D(80)
        cases = [
            (MIDDLE, above, RECOVERING),
            (DOWN, above, RECOVERING),
            (UNAVAILABLE, above, RECOVERING),  # the two-close count restarts
            (RECOVERING, above, UP),
            (UP, above, UP),
            (UP, middle, MIDDLE),  # leaving Up takes one close at or below SMA200
            (UP, down, DOWN),
            (RECOVERING, down, DOWN),
            (UP, sma200, MIDDLE),  # C = SMA200 is not above it
            (MIDDLE, sma50, DOWN),  # C = SMA50 is not above it
        ]
        for previous, close, expected in cases:
            with self.subTest(previous=previous, close=close):
                self.assertEqual(expected, next_state(previous, close, sma50, sma200))
        for missing in ((None, sma50, sma200), (above, None, sma200), (above, sma50, None)):
            self.assertEqual(UNAVAILABLE, next_state(UP, *missing))
        with self.assertRaises(ValueError):
            next_state("sideways", above, sma50, sma200)

    def test_machine_starts_on_the_first_sma200_day_from_middle(self):
        self.assertEqual([], classify_days(daily([100] * 199)))
        # Day 199 closes at its averages (Down); two closes above SMA200 then reach Up,
        # and one close at or below both averages (SMA50 101, SMA200 100.25) leaves it.
        closes = [100] * 200 + [130, 130, 90]
        states = [entry.state for entry in classify_days(daily(closes))]
        self.assertEqual([DOWN, RECOVERING, UP, DOWN], states)
        self.assertEqual(day(199), classify_days(daily(closes))[0].day)
        # From the initial Middle, the first close above SMA200 is only Recovering.
        states = [entry.state for entry in classify_days(daily([100] * 199 + [130, 130]))]
        self.assertEqual([RECOVERING, UP], states)

    def test_a_missing_bar_is_unavailable_until_the_averages_are_defined_again(self):
        closes = [100] * 200 + [130, 130, 130, 130]
        entries = classify_days(daily(closes, skip={202}))
        self.assertEqual([day(199 + i) for i in range(5)], [entry.day for entry in entries])
        # Day 202 is missing. The gap also leaves SMA50 and SMA200 undefined while it is
        # inside their windows, so day 203 is Unavailable too (the conservative reading).
        self.assertEqual(
            [DOWN, RECOVERING, UP, UNAVAILABLE, UNAVAILABLE],
            [entry.state for entry in entries],
        )

    def test_invalid_daily_series_is_refused(self):
        bars = daily([100] * 3)
        with self.assertRaises(ValueError):
            classify_days([bars[0], bars[0]])
        with self.assertRaises(ValueError):
            classify_days([replace(bars[0], open_ms=bars[0].open_ms + 1)])


class NoLookaheadTests(TestCase):
    def setUp(self):
        # Up through day 201, then day 202 closes far below both averages (Down).
        self.bars = daily([100 + i for i in range(202)] + [1, 300, 300])
        self.schedule = TrendSchedule(self.bars)

    def test_a_bar_is_used_only_from_the_instant_it_closes(self):
        closes_at = DAY0_MS + 203 * DAY_MS  # the day-202 bar closes at 00:00 UTC of day 203
        before, after = self.schedule.at(closes_at - 1), self.schedule.at(closes_at)
        self.assertEqual((day(201), UP), (before.day, before.state))
        self.assertEqual((day(202), DOWN, day(202)), (after.day, after.state, after.last_down))
        self.assertEqual(before, self.schedule.at(closes_at - DAY_MS))

    def test_bars_closing_after_the_decision_never_change_it(self):
        for cut in range(200, len(self.bars)):
            known = TrendSchedule(self.bars[:cut])
            first_unknown_close = DAY0_MS + (cut + 1) * DAY_MS
            for when in (first_unknown_close - DAY_MS, first_unknown_close - 1):
                with self.subTest(cut=cut, when=when):
                    self.assertEqual(known.at(when), self.schedule.at(when))
            self.assertEqual(cut, known.completed_bars(first_unknown_close - 1))

    def test_before_classification_is_middle_and_after_the_data_is_unavailable(self):
        self.assertEqual(TrendSignal(day(100), MIDDLE), self.schedule.at(DAY0_MS + 101 * DAY_MS))
        late = self.schedule.at(DAY0_MS + 400 * DAY_MS)
        self.assertEqual((day(399), UNAVAILABLE, day(202)), (late.day, late.state, late.last_down))

    def test_signal_from_an_unclosed_bar_is_rejected(self):
        noon = (DAY0 + timedelta(days=5, hours=12)).isoformat()
        TrendSignal(day(4), UP).validate(noon)
        with self.assertRaisesRegex(ValueError, "not closed"):
            TrendSignal(day(5), UP).validate(noon)
        with self.assertRaises(ValueError):
            TrendSignal(day(4), UP, day(5)).validate(noon)  # last Down after its own day
        with self.assertRaises(ValueError):
            TrendSignal(day(4), "sideways").validate(noon)

    def test_dates_must_be_in_canonical_iso_form(self):
        # Bob's C1 on PR #114: days are ordered as text, so an unpadded day that parses
        # would sort wrongly. It is refused.
        when = (DAY0 + timedelta(days=2)).isoformat()
        TrendSignal("2026-01-01", UP).validate(when)
        for day, last_down in (("2026-1-1", None), ("2026-01-01", "2025-12-3")):
            with self.subTest(day=day, last_down=last_down), self.assertRaises(ValueError):
                TrendSignal(day, UP, last_down).validate(when)

    def test_engine_halts_rather_than_act_on_lookahead(self):
        simulator = PaperSimulator(
            Path(":memory:"), load_config(ROOT / "config/default.toml"), MarketRules(), policy=A
        )
        self.addCleanup(simulator.close)
        when = DAY0 + timedelta(days=5, hours=12)
        report = simulator.process(frame_at(when, trend=signal(5, UP)))
        self.assertEqual("halt", report["decision"])
        self.assertIn("not closed", report["reason"])
        self.assertFalse(simulator.store.read().orders)

    def test_stale_or_missing_signal_gates_as_unavailable(self):
        noon = (DAY0 + timedelta(days=5, hours=12)).isoformat()
        self.assertEqual(UP, effective_state(signal(4, UP), noon))
        self.assertEqual(UNAVAILABLE, effective_state(signal(3, UP), noon))
        self.assertEqual(UNAVAILABLE, effective_state(None, noon))

    def test_down_sequence_start_rule(self):
        self.assertTrue(starts_down_sequence(signal(4, DOWN, 4), ""))
        # On the first signal an older Down day predates the run and does not count.
        self.assertFalse(starts_down_sequence(signal(4, MIDDLE, 2), ""))
        # A Down day that became effective during a gap still counts afterwards.
        self.assertTrue(starts_down_sequence(signal(4, MIDDLE, 3), day(2)))
        self.assertFalse(starts_down_sequence(signal(4, MIDDLE, 2), day(2)))
        self.assertFalse(starts_down_sequence(signal(4, UP), day(3)))


class SwitchingTests(TestCase):
    """The engine under variant A, driven frame by frame on constructed prices."""

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        self.sim = self.simulator(A)
        self.account = Account.start(D(100))

    def simulator(self, policy):
        simulator = PaperSimulator(Path(":memory:"), self.config, MarketRules(), policy=policy)
        simulator.close()  # step() uses no store
        return simulator

    def step(self, when, trend, **quote):
        return self.sim.step(self.account, frame_at(when, trend=trend, **quote))

    def copy(self):
        return Account.from_dict(json.loads(encode(self.account.to_dict())))

    def open_and_fill_two_levels(self):
        """Up on day 1: open a grid, then fill its two highest buys. Returns (bid, ask)."""
        t1 = DAY0 + timedelta(days=1)
        self.assertEqual("open_grid", self.step(t1, signal(0, UP))["decision"])
        buys = sorted((o.price for o in self.account.orders.values()), reverse=True)
        ask = floor_step(buys[1] / D("1.0006"), TICK)
        report = self.step(t1 + timedelta(seconds=1), signal(0, UP), bid=ask - TICK, ask=ask)
        self.assertEqual(2, sum(fill["side"] == "buy" for fill in report["fills"]))
        self.assertFalse(self.account.pause)
        return ask - TICK, ask

    def start_down(self):
        """Down classified on day 1 takes effect at 00:00 UTC of day 2 (T0)."""
        bid, ask = self.open_and_fill_two_levels()
        sells = {k for k, o in self.account.orders.items() if o.side == "sell"}
        self.assertEqual(2, len(sells))
        self.assertTrue(any(o.side == "buy" for o in self.account.orders.values()))
        t0 = DAY0 + timedelta(days=2)
        report = self.step(t0, signal(1, DOWN, 1), bid=bid, ask=ask)
        self.assertEqual([], report["fills"])
        self.assertEqual(sells, set(self.account.orders))  # buys cancelled, sells stay
        self.assertEqual(t0.isoformat(), self.account.down_since)
        self.assertEqual(t0.isoformat(), report["trend"]["down_since"])
        self.assertEqual(day(1), self.account.trend_day)
        return t0, bid

    def lowest_sells(self):
        return sorted(
            (o for o in self.account.orders.values() if o.side == "sell"), key=lambda o: o.price
        )

    def test_only_up_opens_a_new_grid(self):
        when = DAY0 + timedelta(days=1)
        for trend in (
            signal(0, MIDDLE),
            signal(0, RECOVERING),
            signal(0, UNAVAILABLE),
            signal(0, DOWN, 0),
            signal(-1, UP),  # stale: not the bar of the day before the observation
            None,
        ):
            with self.subTest(trend=trend):
                self.account = Account.start(D(100))
                report = self.step(when, trend)
                self.assertEqual("cash", report["decision"])
                self.assertIn("trend switch", report["reason"])
                self.assertFalse(self.account.orders)
                self.assertEqual("", self.account.down_since)  # flat: a sequence ends
        self.account = Account.start(D(100))
        report = self.step(when, signal(0, UP))
        self.assertEqual("open_grid", report["decision"])
        self.assertEqual({"state": UP, "day": day(0), "down_since": None}, report["trend"])

    def test_down_cancels_buys_keeps_sells_and_blocks_reentries(self):
        t0, bid = self.start_down()
        lower, upper = self.lowest_sells()
        # The same account without a running sequence (V0 rules) recycles the level.
        v0_account = self.copy()
        v0_account.down_since = ""
        lift = floor_step(lower.price * D("1.002"), TICK)
        later = frame_at(t0 + timedelta(hours=12), lift, trend=signal(1, DOWN, 1))
        self.simulator(SimulationPolicy()).step(v0_account, replace(later, trend=None))
        self.assertTrue(any(o.side == "buy" for o in v0_account.orders.values()))
        # Twelve hours after T0 the lower sell fills completely; no reentry buy follows.
        report = self.sim.step(self.account, later)
        self.assertEqual([lower.order_id], [fill["order_id"] for fill in report["fills"]])
        self.assertEqual({upper.order_id}, set(self.account.orders))
        self.assertEqual(t0.isoformat(), self.account.down_since)

    def test_deadline_liquidates_with_trend_exit_and_retries_residuals(self):
        t0, bid = self.start_down()
        held = self.account.inventory
        # A second before the deadline nothing is forced.
        before = self.step(t0 + timedelta(days=1, seconds=-1), signal(1, DOWN, 1), bid=bid)
        self.assertEqual([], before["fills"])
        # Another Down day (day 2) does not reset the deadline. Bid size 5000 at 10%
        # participation bounds each observation to 500 units.
        deadline = t0 + timedelta(days=1)
        report = self.step(deadline, signal(2, DOWN, 2), bid=bid, size="5000")
        self.assertEqual("trend_exit", report["exit_reason"])
        (fill,) = report["fills"]
        self.assertTrue(fill["order_id"].startswith("exit/"))
        self.assertEqual(D(500), D(fill["quantity"]))
        self.assertFalse(self.account.orders)  # the remaining sells were cancelled
        self.assertEqual(held - 500, self.account.inventory)
        self.assertEqual(t0.isoformat(), self.account.down_since)
        later = deadline
        while self.account.inventory:
            later += timedelta(seconds=1)
            report = self.step(later, signal(2, DOWN, 2), bid=bid, size="5000")
            self.assertEqual("trend_exit", report["exit_reason"])
        self.assertEqual(t0.isoformat(), report["down_sequence_ended"])
        self.assertEqual("", self.account.down_since)

    def test_the_deadline_cancels_the_sells_before_this_observations_matching(self):
        # Codex on PR #114: a deadline quote crossing both resting sells filled them
        # first, flattening the account with no exit reason. The spec cancels the sells
        # before the bounded exit; so must the engine.
        t0, _bid = self.start_down()
        sells = self.lowest_sells()
        crossing = sells[-1].price + TICK
        report = self.step(t0 + timedelta(days=1), signal(2, DOWN, 2), bid=crossing, size="5000")
        self.assertFalse(any(f["order_id"] in {o.order_id for o in sells} for f in report["fills"]))
        self.assertEqual(sorted(o.order_id for o in sells), report["cancelled"])
        self.assertEqual("trend_exit", report["exit_reason"])
        self.assertTrue(all(f["order_id"].startswith("exit/") for f in report["fills"]))

    def test_a_sub_minimum_remainder_ends_the_sequence_instead_of_looping(self):
        # Bob's F1 on PR #114: the sequence waited for inventory == 0, which a residue
        # below the minimum notional never reaches; recycle stayed off and the account
        # emitted an empty trend_exit on every frame for good. PR #122's rule applies:
        # the sequence ends when nothing sellable is left, and the residue stays marked.
        t0, bid = self.start_down()
        # Stand the account at the deadline holding only a residue: no orders, 100 units
        # (about 2.3 quote at this bid, below the minimum notional) and its cash intact.
        self.account.orders.clear()
        self.account.inventory = D(100)
        self.account.cash = D(100)
        report = self.step(t0 + timedelta(days=1), signal(2, DOWN, 2), bid=bid, size="5000")
        self.assertEqual([], report["fills"])
        self.assertEqual("dust", report["exit_blocked"])
        self.assertEqual(t0.isoformat(), report["down_sequence_ended"])
        self.assertEqual("", self.account.down_since)
        self.assertEqual(D(100), self.account.inventory)
        later = self.step(t0 + timedelta(days=2), signal(3, UP), bid=bid)
        self.assertEqual("open_grid", later["decision"])
        self.assertEqual(D(100), self.account.inventory)  # held through the new grid

    def test_a_stale_signal_neither_starts_a_sequence_nor_advances_the_applied_day(self):
        # Bob's F2 and C2 on PR #114: starts_down_sequence read the raw signal, so a
        # two-day-old Down object cancelled the buys while the effective state was
        # Unavailable, and trend_day advanced on it.
        bid, ask = self.open_and_fill_two_levels()
        applied = self.account.trend_day
        orders = set(self.account.orders)
        stale = self.step(DAY0 + timedelta(days=3), signal(1, DOWN, 1), bid=bid, ask=ask)
        self.assertEqual("unavailable", stale["trend"]["state"])
        self.assertEqual("", self.account.down_since)
        self.assertEqual(applied, self.account.trend_day)
        self.assertEqual(orders, set(self.account.orders))

    def test_unavailable_observations_inside_a_sequence_keep_its_deadline(self):
        # Bob's C4 on PR #114: the deadline is wall-clock from T0, so missing daily bars
        # after the start neither end the sequence nor postpone the exit.
        t0, bid = self.start_down()
        for seconds in (1, 3600, 86_399):
            report = self.step(t0 + timedelta(seconds=seconds), None, bid=bid)
            self.assertEqual("unavailable", report["trend"]["state"])
            self.assertEqual(t0.isoformat(), self.account.down_since)
            self.assertNotIn("exit_reason", report)
        report = self.step(t0 + timedelta(days=1), None, bid=bid, size="5000")
        self.assertEqual("trend_exit", report["exit_reason"])

    def test_a_sequence_that_ends_flat_leaves_no_obsolete_grid_behind(self):
        # Codex on PR #114: cancelling an unfilled grid left its bounds and outside clock,
        # so 121 observations outside those bounds put an empty account into a range exit
        # and the next Up day stayed paused.
        t1 = DAY0 + timedelta(days=1)
        self.assertEqual("open_grid", self.step(t1, signal(0, UP))["decision"])
        lower = self.account.grid_lower
        self.assertGreater(lower, ZERO)
        report = self.step(DAY0 + timedelta(days=2), signal(1, DOWN, 1))
        self.assertFalse(self.account.orders)
        self.assertIn("down_sequence_ended", report)
        self.assertEqual(
            (ZERO, ZERO, ZERO, ""),
            (
                self.account.grid_lower,
                self.account.grid_upper,
                self.account.outside_seconds,
                self.account.outside_last,
            ),
        )
        far_below = floor_step(lower * D("0.9"), TICK)  # outside the old bounds, still tradable
        when = DAY0 + timedelta(days=2, seconds=1)
        for _ in range(130):
            when += timedelta(seconds=180)
            self.step(when, signal(1, DOWN, 1), bid=far_below)
        self.assertFalse(self.account.range_exit)
        # Back at a price the demo frame's fair value can grid, the next Up day opens.
        self.assertEqual(
            "open_grid", self.step(DAY0 + timedelta(days=4), signal(3, UP))["decision"]
        )

    def test_started_sequence_completes_after_the_state_returns_to_up(self):
        t0, bid = self.start_down()
        # Up before the deadline: still no new grid and no new buy.
        report = self.step(t0 + timedelta(hours=1), signal(1, UP, 0), bid=bid)
        self.assertEqual(UP, report["trend"]["state"])
        self.assertFalse(any(o.side == "buy" for o in self.account.orders.values()))
        report = self.step(t0 + timedelta(days=1), signal(2, UP, 1), bid=bid)
        self.assertEqual("trend_exit", report["exit_reason"])
        self.assertEqual(D(0), self.account.inventory)
        # Flat now, but the sequence ends only after this observation's grid decision.
        self.assertEqual("cash", report["decision"])
        self.assertIn("Down sequence running", report["reason"])
        self.assertEqual("", self.account.down_since)
        again = self.step(t0 + timedelta(days=1, seconds=1), signal(2, UP, 1), bid=bid)
        self.assertEqual("open_grid", again["decision"])

    def test_reentry_after_the_sequence_needs_up(self):
        t0, bid = self.start_down()
        self.step(t0 + timedelta(days=1), signal(2, DOWN, 2), bid=bid)
        self.assertEqual(D(0), self.account.inventory)
        self.assertEqual("", self.account.down_since)
        report = self.step(t0 + timedelta(days=2), signal(3, RECOVERING, 2), bid=bid)
        self.assertEqual("cash", report["decision"])
        report = self.step(t0 + timedelta(days=3), signal(4, UP, 2), bid=bid)
        self.assertEqual("open_grid", report["decision"])

    def test_middle_keeps_the_existing_grid_running(self):
        bid, ask = self.open_and_fill_two_levels()
        buys = {k for k, o in self.account.orders.items() if o.side == "buy"}
        lower, _ = self.lowest_sells()
        t = DAY0 + timedelta(days=2)
        self.step(t, signal(1, MIDDLE), bid=bid, ask=ask)
        self.assertEqual("", self.account.down_since)
        self.assertTrue(buys <= set(self.account.orders))  # nothing cancelled
        lift = floor_step(lower.price * D("1.002"), TICK)
        report = self.step(t + timedelta(hours=1), signal(1, MIDDLE), bid=lift)
        self.assertEqual([lower.order_id], [fill["order_id"] for fill in report["fills"]])
        self.assertEqual(1, sum("/reentry/" in key for key in self.account.orders))

    def test_same_step_labels_follow_the_ranking(self):
        t0, bid = self.start_down()
        deadline = t0 + timedelta(days=1)
        saved = self.copy()
        self.account.pause, self.account.draining = "test pause", True
        report = self.step(deadline, signal(2, DOWN, 2), bid=bid)
        self.assertEqual("drain", report["exit_reason"])  # drain outranks trend_exit
        self.assertEqual(D(0), self.account.inventory)

        self.account = Account.from_dict(json.loads(encode(saved.to_dict())))
        self.account.orders.clear()
        self.account.range_exit, self.account.range_exit_since = True, t0.isoformat()
        report = self.step(deadline, signal(2, DOWN, 2), bid=bid)
        self.assertEqual("range_exit", report["exit_reason"])

        self.account = Account.from_dict(json.loads(encode(saved.to_dict())))
        self.account.orders.clear()
        self.account.halt = "test halt without liquidation"
        self.account.halt_category = "integrity"
        report = self.step(deadline, signal(2, DOWN, 2), bid=bid)
        self.assertEqual([], report["fills"])  # the halt is V0's; the deadline adds nothing
        self.assertEqual(t0.isoformat(), self.account.down_since)


class PersistenceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "a.db"
        self.config = load_config(ROOT / "config/default.toml")

    def open(self, policy=A):
        simulator = PaperSimulator(self.path, self.config, MarketRules(), policy=policy)
        self.addCleanup(simulator.close)
        return simulator

    def saved(self, simulator, column):
        row = simulator.store.connection.execute(f"SELECT {column} FROM state").fetchone()
        return json.loads(row[0])

    def test_switch_is_part_of_the_account_identity(self):
        simulator = self.open()
        self.assertIs(True, self.saved(simulator, "identity")["policy"]["trend_switch"])
        simulator.close()
        with self.assertRaisesRegex(ValueError, "settings differ"):
            self.open(SimulationPolicy())
        with self.assertRaises(ValueError):
            SimulationPolicy(trend_switch=1)
        # Variant C is A + B: both switches are recorded in one identity.
        both = SimulationPolicy(inventory_cap=D("0.4"), trend_switch=True).identity()
        self.assertEqual((D("0.4"), True), (both["inventory_cap"], both["trend_switch"]))

    def test_down_sequence_survives_a_restart(self):
        simulator = self.open()
        t1 = DAY0 + timedelta(days=1)
        self.assertEqual(
            "open_grid", simulator.process(frame_at(t1, trend=signal(0, UP)))["decision"]
        )
        buys = sorted((o.price for o in simulator.store.read().orders.values()), reverse=True)
        ask = floor_step(buys[0] / D("1.0006"), TICK)
        simulator.process(
            frame_at(t1 + timedelta(seconds=1), ask - TICK, ask=ask, trend=signal(0, UP))
        )
        t0 = DAY0 + timedelta(days=2)
        simulator.process(frame_at(t0, ask - TICK, ask=ask, trend=signal(1, DOWN, 1)))
        self.assertEqual(t0.isoformat(), self.saved(simulator, "data")["down_since"])
        simulator.close()
        reopened = self.open()
        account = reopened.store.read()
        self.assertEqual((t0.isoformat(), day(1)), (account.down_since, account.trend_day))
        self.assertGreater(account.inventory, 0)
        report = reopened.process(
            frame_at(t0 + timedelta(days=1), ask - TICK, trend=signal(2, DOWN, 2))
        )
        self.assertEqual("trend_exit", report["exit_reason"])
        self.assertNotIn("down_since", self.saved(reopened, "data"))  # ended, flat

    def test_journalled_frame_round_trips_its_signal(self):
        current = frame_at(DAY0 + timedelta(days=3), trend=signal(2, DOWN, 1))
        payload = json.loads(encode(current.payload()))
        self.assertEqual({"day": day(2), "state": DOWN, "last_down": day(1)}, payload["trend"])
        self.assertEqual(current.payload(), decode_frame(payload).payload())

    def test_resume_cli_restores_the_trend_switch(self):
        simulator = self.open()
        emergency = frame_at(DAY0 + timedelta(days=1), trend=signal(0, UP))
        simulator.process(replace(emergency, signals=replace(emergency.signals, emergency=True)))
        simulator.close()
        now = datetime.now(UTC)
        path = Path(self.temp.name) / "frame.json"
        path.write_text(encode(frame_at(now).payload()))
        # A dropped switch would fail as "settings differ" instead of resuming.
        report = resume_paper(self.path, self.config, path, event_id="cli", reason="reviewed")
        self.assertEqual("resume_pending", report["decision"])


class V0UnchangedTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = load_config(ROOT / "config/default.toml")

    def run_demo(self, name, frames, policy=None):
        simulator = PaperSimulator(
            Path(self.temp.name) / name, self.config, MarketRules(), policy=policy
        )
        self.addCleanup(simulator.close)
        reports = [simulator.process(frame) for frame in frames]
        connection = simulator.store.connection
        return reports, connection.execute("SELECT identity, data FROM state").fetchone()

    def test_unset_switch_leaves_identity_state_journal_and_reports_unchanged(self):
        frames = demo_frames(30)
        reports, (identity, data) = self.run_demo("v0.db", frames)
        self.assertNotIn("trend_switch", json.loads(identity)["policy"])
        self.assertFalse({"trend_day", "down_since"} & set(json.loads(data)))
        self.assertNotIn("trend", frames[0].payload())
        self.assertFalse(any("trend" in report for report in reports))
        # With the switch off, a signal on the frame is ignored entirely.
        signed = [replace(f, trend=signal(-1, DOWN, -1)) for f in frames]
        other, (other_identity, other_data) = self.run_demo("signed.db", signed)
        self.assertEqual((reports, identity, data), (other, other_identity, other_data))
        # The persisted policy is exactly the pre-variant field set.
        unset = {
            "inventory_cap": None,
            "trend_switch": False,
            "volume_exit": False,
            "flow_block_entry": False,
        }
        self.assertEqual(asdict(SimulationPolicy()), SimulationPolicy().identity() | unset)


def hourly(count, start_ms, amplitude=0.08):
    candles, previous = [], 1.0
    for i in range(count):
        close = 1.0 + amplitude * math.sin(2 * math.pi * i / 24)
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        o, h, lo, c = (D(str(round(x, 6))) for x in (previous, high, low, close))
        candles.append(Kline(start_ms + i * HOUR_MS, o, h, lo, c, D(10**6), D(10**6) * c, D(0)))
        previous = close
    return candles


class ReplayWiringTests(TestCase):
    """Variant A through replay() on synthetic klines; nothing is downloaded or read."""

    MIDNIGHT = DAY0_MS + 260 * DAY_MS
    WARMUP = 800

    def setUp(self):
        self.config = load_config(ROOT / "config/default.toml")
        rules = MarketRules("TESTUSDT", D("0.0001"), D("0.1"), D("5"))
        self.run_config = RunConfig("TESTUSDT", "high_first", False, rules, D(100), D("0.0005"))
        start = self.MIDNIGHT - HOUR_MS
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
        # 23:00 to 00:30 UTC across the midnight at which the last daily bar closes.
        self.minutes = [
            Kline(
                start + i * 60_000,
                *(D(str(round(fair * f, 6))) for f in (1, 1.001, 0.999, 1)),
                D(10**6),
                D(10**6),
                D(5 * 10**5),
            )
            for i in range(90)
        ]
        # Rising closes (Up) through day 258; day 259 crashes below both averages (Down).
        self.daily = daily([100 + i for i in range(259)] + [1])

    def replay(self, policy, daily_bars):
        return replay(self.config, self.run_config, self.minutes, self.engine, policy, daily_bars)

    def test_down_classification_takes_effect_at_midnight(self):
        metrics, account = self.replay(A, self.daily)
        self.assertEqual([], check_accounting(self.run_config, metrics, account))
        self.assertEqual(1, metrics.grids_opened)  # opened under Up, before midnight
        self.assertFalse(account.orders)  # its resting buys were cancelled at 00:00
        self.assertEqual(day(259), account.trend_day)
        self.assertEqual("", account.down_since)  # nothing was held, so it ended at once
        # Without variant A the same grid is still resting after midnight.
        _, v0 = self.replay(None, self.daily)
        self.assertTrue(v0.orders)

    def test_v0_ignores_the_daily_history(self):
        with_daily = self.replay(None, self.daily)
        without = self.replay(None, None)
        self.assertEqual(asdict(with_daily[0]), asdict(without[0]))
        self.assertEqual(encode(with_daily[1].to_dict()), encode(without[1].to_dict()))

    def test_variant_a_refuses_missing_or_short_daily_history(self):
        with self.assertRaisesRegex(ValueError, "daily history"):
            self.replay(A, None)
        with self.assertRaisesRegex(ValueError, "200 completed daily bars"):
            self.replay(A, self.daily[-199:])
