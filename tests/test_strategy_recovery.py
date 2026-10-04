"""Regressions from Claude's review; prices are constructed, not backtest evidence."""

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.control import decode_frame, resume_paper
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import (
    match,
    place,
    reduce_unreserved,
)
from crypto_grid_bot.simulation.models import (
    Account,
    D,
    LimitOrder,
    MarketRules,
    Quote,
    timestamp,
)
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=UTC)


def frame(index, bid="0.02300", *, ask=None, size="100000", eligible=True):
    template = demo_frames(1)[0]
    when = START + timedelta(seconds=index)
    return replace(
        template,
        quote=replace(
            template.quote,
            event_id=f"recovery/{index}",
            observed_at=when.isoformat(),
            received_at=when.isoformat(),
            bid=D(bid),
            ask=D(ask) if ask else D(bid) + D("0.00001"),
            bid_size=D(size),
            ask_size=D(size),
        ),
        signals=replace(template.signals, observed_at=when),
        candidate=replace(template.candidate, news_risk=0 if eligible else 0.9),
        allow_new_grid=True,
    )


def stale(current):
    received = timestamp(current.quote.observed_at) + timedelta(seconds=99)
    return replace(current, quote=replace(current.quote, received_at=received.isoformat()))


def at_fair_value(index, bid):
    return replace(frame(index, bid), fair_value=D(bid))


class StrategyRecoveryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "paper.db"
        self.config = replace(load_config(ROOT / "config/default.toml"), minimum_transfer_quote=0.1)
        # These fixtures step 1 s per frame and use 45-98 s jumps as continuity gaps.
        self.policy = SimulationPolicy(outside_range_seconds=3, maximum_frame_gap_seconds=30)
        self.sim = self.open()
        self.addCleanup(lambda: self.sim.close())

    def open(self, rules=None):
        return PaperSimulator(self.path, self.config, rules or MarketRules(), policy=self.policy)

    def reopen(self, policy, name):
        self.sim.close()
        self.policy, self.path = policy, Path(self.temp.name) / name
        self.sim = self.open()

    def restart(self):
        self.sim.close()
        self.sim = self.open()

    def test_fifty_shallow_oscillations_keep_trading_and_harvesting(self):
        self.sim.process(frame(0))
        initial_lowest = min(o.price for o in self.sim.store.read().orders.values())
        self.assertLess(initial_lowest, D("0.02270"))
        for cycle in range(50):
            self.sim.process(frame(2 * cycle + 1, "0.02270"))
            report = self.sim.process(frame(2 * cycle + 2, "0.02330"))
            state = self.sim.store.read()
            self.assertEqual(0, state.inventory)
            self.assertGreaterEqual(state.available_quote(self.sim.rules), 0)
            self.assertTrue(report["allocation"])
            if cycle in (2, 20):
                self.restart()
        state = self.sim.store.read()
        self.assertGreaterEqual(state.fill_count, 100)
        self.assertGreater(state.secured, 0)
        self.assertEqual(sum(state.confirmed_transfers.values()), state.secured)
        self.assertEqual(
            state.cash - state.pending - state.initial_cash, state.pending + state.secured
        )
        self.assertGreater(len(state.confirmed_transfers), 1)
        self.assertEqual(len(state.confirmed_transfers), len(set(state.confirmed_transfers)))

    def test_minute_cadence_recovers_without_relaxing_stale_frame_checks(self):
        self.reopen(SimulationPolicy(), "minute-recovery.db")
        self.sim.process(frame(0))
        report = self.sim.process(stale(frame(60)))
        self.assertEqual("pause", report["decision"])
        self.assertFalse(report["fills"])
        self.assertEqual(frame(0).quote.observed_at, self.sim.store.read().last_observed)
        self.assertFalse(self.sim.process(frame(120))["opened"])
        self.restart()
        self.assertTrue(self.sim.process(frame(180))["opened"])

    def test_minute_cadence_exits_after_six_hours_and_recenters_after_a_day(self):
        self.reopen(SimulationPolicy(), "minute-exit.db")
        self.sim.process(frame(0))
        # The first outside observation starts the clock; subsequent intervals count.
        exit_at = 60 + self.policy.outside_range_seconds
        recenter_at = exit_at + self.policy.recenter_cooldown_seconds
        for t in range(60, exit_at, 60):
            self.sim.process(at_fair_value(t, "0.02196"))
            self.assertFalse(self.sim.store.read().range_exit)
        self.assertGreater(self.sim.store.read().inventory, 0)
        self.restart()
        report = self.sim.process(at_fair_value(exit_at, "0.02196"))
        self.assertTrue(report["range_exit"])
        self.assertEqual(0, self.sim.store.read().inventory)
        for t in range(exit_at + 60, recenter_at, 60):
            report = self.sim.process(at_fair_value(t, "0.02196"))
            self.assertTrue(report["range_exit"])
            self.assertFalse(report["opened"])
        report = self.sim.process(at_fair_value(recenter_at, "0.02196"))
        self.assertEqual("recenter", report["range_exit_cleared"])
        self.assertFalse(report["opened"])
        self.assertFalse(self.sim.process(at_fair_value(recenter_at + 60, "0.02196"))["opened"])
        self.assertTrue(self.sim.process(at_fair_value(recenter_at + 120, "0.02196"))["opened"])
        state = self.sim.store.read()
        self.assertTrue(state.grid_lower <= D("0.02196") <= state.grid_upper)

    def test_frame_gap_boundary_counts_but_larger_gaps_preserve_only_prior_time(self):
        self.reopen(SimulationPolicy(outside_range_seconds=1000), "gap-boundary.db")
        self.sim.process(frame(0))
        self.sim.process(frame(60, "0.02500"))
        self.sim.process(frame(240, "0.02500"))  # Exactly 180 seconds counts.
        self.assertEqual(180, self.sim.store.read().outside_seconds)
        self.sim.process(frame(421, "0.02500"))  # 181 seconds does not count.
        self.assertEqual(180, self.sim.store.read().outside_seconds)
        self.sim.process(frame(481, "0.02500"))
        self.assertEqual(240, self.sim.store.read().outside_seconds)

    def test_frame_gap_policy_requires_positive_integer(self):
        for value in (0, -1, True, 60.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "frame gap"):
                SimulationPolicy(maximum_frame_gap_seconds=value)

    def test_old_policy_identity_cannot_silently_adopt_new_timing(self):
        row = self.sim.store.connection.execute("SELECT identity FROM state").fetchone()[0]
        identity = json.loads(row)
        del identity["policy"]["maximum_frame_gap_seconds"]
        self.sim.store.connection.execute("UPDATE state SET identity=?", (encode(identity),))
        with self.assertRaisesRegex(ValueError, "settings differ"):
            self.open()

    def test_broad_quality_veto_blocks_entries_at_low_opportunity_threshold(self):
        self.config = replace(self.config, minimum_opportunity_score=0.01)
        self.reopen(SimulationPolicy(), "quality-veto.db")
        for i, changes in enumerate(({"data_quality": 0.1}, {"news_risk": 0.99})):
            current = frame(i)
            current = replace(current, signals=replace(current.signals, **changes))
            report = self.sim.process(current)
            self.assertEqual("pause", report["decision"])
            self.assertIn("broad-market input quality", report["reason"])
            self.assertFalse(report["opened"])
            self.assertFalse(self.sim.store.read().orders)
        self.restart()
        self.assertFalse(self.sim.process(frame(2))["opened"])
        self.assertTrue(self.sim.process(frame(3))["opened"])

    def test_stale_frame_cannot_fill_existing_sells_or_clear_pause(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        before = self.sim.store.read()
        self.assertGreater(before.inventory, 0)
        stale = frame(2, "0.02330")
        stale = replace(
            stale,
            quote=replace(stale.quote, received_at=(START + timedelta(seconds=100)).isoformat()),
        )
        report = self.sim.process(stale)
        self.assertEqual("pause", report["decision"])
        self.assertFalse(report["fills"])
        self.assertEqual(before.inventory, self.sim.store.read().inventory)
        self.assertTrue(all(o.side == "sell" for o in self.sim.store.read().orders.values()))
        self.restart()
        recovery = frame(3, "0.02330")
        report = self.sim.process(recovery)
        self.assertTrue(report["fills"])  # Fresh reduce-only sells may complete.
        self.assertFalse(report["opened"])
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.sim.process(recovery)
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.assertTrue(self.sim.process(frame(4))["opened"])
        self.assertFalse(self.sim.store.read().pause)

    def test_recovery_requires_consecutive_eligible_frames_and_rejects_duplicate_time(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, eligible=False))
        self.assertFalse(self.sim.process(frame(2))["opened"])
        duplicate_time = replace(frame(2), quote=replace(frame(2).quote, event_id="same-time"))
        self.assertEqual("pause", self.sim.process(duplicate_time)["decision"])
        self.assertEqual(0, self.sim.store.read().recovery_count)
        self.sim.process(frame(3))
        self.sim.process(frame(4, eligible=False))
        self.assertEqual(0, self.sim.store.read().recovery_count)
        self.sim.process(frame(5))
        self.sim.process(frame(50))  # A long gap also resets continuity.
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.assertTrue(self.sim.process(frame(51))["opened"])

    def test_outside_range_exits_to_cash_and_does_not_chase_price(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        self.sim.process(frame(2, "0.02500"))
        self.restart()
        report = self.sim.process(frame(4, "0.02500"))
        self.assertEqual("pause", report["decision"])
        self.assertTrue(self.sim.store.read().range_exit)
        self.assertEqual({}, self.sim.store.read().orders)
        self.assertFalse(self.sim.process(frame(5, "0.02500"))["opened"])
        for i in (6, 7):
            self.assertFalse(self.sim.process(frame(i))["opened"])
        self.assertTrue(self.sim.process(frame(8))["opened"])

    def test_outside_range_timeout_liquidates_inventory_with_bounded_fills(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(frame(2, "0.02196"))
        self.assertGreater(self.sim.store.read().inventory, 0)
        report = self.sim.process(frame(4, "0.02196", size="10000"))
        self.assertTrue(self.sim.store.read().range_exit)
        self.assertEqual("pause", report["decision"])
        self.assertEqual(D(1000), D(report["fills"][0]["quantity"]))
        self.assertGreater(self.sim.store.read().inventory, 0)
        self.assertFalse(self.sim.store.read().orders)

    def test_invalid_frame_pauses_but_does_not_erase_outside_range_time(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        self.assertEqual("pause", self.sim.process(stale(frame(2, "0.02500")))["decision"])
        self.assertEqual(frame(1).quote.observed_at, self.sim.store.read().outside_last)
        # Two valid outside observations 3 s apart bracket the unusable frame.
        self.sim.process(frame(4, "0.02500"))
        self.assertTrue(self.sim.store.read().range_exit)

    def test_gap_neither_counts_nor_erases_outside_range_time(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        self.sim.process(frame(2, "0.02500"))
        self.sim.process(frame(100, "0.02500"))
        state = self.sim.store.read()
        self.assertFalse(state.range_exit)
        self.assertEqual(1, state.outside_seconds)
        self.assertEqual(frame(100).quote.observed_at, state.outside_last)
        self.sim.process(frame(101, "0.02500"))
        self.assertFalse(self.sim.store.read().range_exit)
        self.sim.process(frame(102, "0.02500"))
        self.assertTrue(self.sim.store.read().range_exit)

    def test_valid_inside_frame_resets_outside_range_time(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02500"))
        self.sim.process(frame(2, "0.02500"))
        self.sim.process(frame(3))
        state = self.sim.store.read()
        self.assertEqual((0, ""), (state.outside_seconds, state.outside_last))

    def test_flapping_feed_cannot_postpone_outside_range_exit(self):
        # Review #2 regression: one unusable frame every 50 s used to reset a 100 s timer
        # forever while inventory was held below the range (the 5 h / 6 h analogue).
        self.reopen(SimulationPolicy(outside_range_seconds=100), "flapping.db")
        self.sim.process(frame(0))
        exited_at = None
        for t in range(10, 400, 10):
            current = frame(t, "0.02196")
            report = self.sim.process(stale(current) if t % 50 == 0 else current)
            if self.sim.store.read().range_exit:
                exited_at = t
                break
            if t % 50:
                self.assertNotEqual("halt", report["decision"])
        self.assertEqual(110, exited_at)  # 100 s of valid outside observations

    def test_range_exit_recenters_only_after_cooldown_and_confirmation(self):
        self.reopen(
            SimulationPolicy(outside_range_seconds=3, recenter_cooldown_seconds=20), "recenter.db"
        )
        self.sim.process(frame(0))
        for t in (1, 2, 4):
            self.sim.process(frame(t, "0.02500"))
        self.assertTrue(self.sim.store.read().range_exit)
        for t in range(5, 24):
            report = self.sim.process(at_fair_value(t, "0.02500"))
            self.assertFalse(report["opened"])
            self.assertTrue(self.sim.store.read().range_exit)
        report = self.sim.process(at_fair_value(24, "0.02500"))
        self.assertEqual("recenter", report["range_exit_cleared"])
        self.assertFalse(report["opened"])
        self.assertFalse(self.sim.process(at_fair_value(25, "0.02500"))["opened"])
        self.assertTrue(self.sim.process(at_fair_value(26, "0.02500"))["opened"])
        state = self.sim.store.read()
        self.assertTrue(state.grid_lower <= D("0.02500") <= state.grid_upper)
        self.assertFalse(state.range_exit)

    def test_sixty_second_cadence_clears_pause(self):
        # Review #3: 60 s frames (the collector's fastest polling) once reset the recovery
        # streak on every frame because continuity reused the 30 s freshness limit.
        self.reopen(SimulationPolicy(), "cadence-pause.db")
        self.sim.process(frame(0))
        self.assertEqual("pause", self.sim.process(frame(60, eligible=False))["decision"])
        self.sim.process(frame(120))
        self.assertEqual(1, self.sim.store.read().recovery_count)
        self.assertTrue(self.sim.process(frame(180))["opened"])
        self.assertFalse(self.sim.store.read().pause)

    def test_sixty_second_cadence_exits_range_and_recenters(self):
        self.reopen(
            SimulationPolicy(outside_range_seconds=600, recenter_cooldown_seconds=1800),
            "cadence-range.db",
        )
        self.sim.process(frame(0))
        exited_at = None
        for t in range(60, 1200, 60):
            self.sim.process(frame(t, "0.02196"))
            if self.sim.store.read().range_exit:
                exited_at = t
                break
        self.assertEqual(660, exited_at)  # 600 s of valid 60 s outside observations
        self.assertEqual(0, self.sim.store.read().inventory)
        opened_at = None
        for t in range(exited_at + 60, exited_at + 3600, 60):
            if self.sim.process(at_fair_value(t, "0.02196"))["opened"]:
                opened_at = t
                break
        self.assertIsNotNone(opened_at)
        self.assertGreaterEqual(opened_at, exited_at + 1800)
        state = self.sim.store.read()
        self.assertTrue(state.grid_lower <= D("0.02196") <= state.grid_upper)

    def test_frame_gap_policy_is_validated(self):
        for bad in (0, 3601, 60.0):
            with self.subTest(gap=bad), self.assertRaises(ValueError):
                SimulationPolicy(maximum_frame_gap_seconds=bad)

    def test_range_exit_waits_for_old_band_when_recentering_disabled(self):
        self.reopen(
            SimulationPolicy(
                outside_range_seconds=3, recenter_after_exit=False, recenter_cooldown_seconds=1
            ),
            "no-recenter.db",
        )
        self.sim.process(frame(0))
        for t in (1, 2, 4):
            self.sim.process(frame(t, "0.02500"))
        for t in range(5, 60):
            report = self.sim.process(at_fair_value(t, "0.02500"))
            self.assertFalse(report["opened"])
        self.assertTrue(self.sim.store.read().range_exit)
        self.assertIn("recentering disabled", report["reason"])
        self.assertEqual("returned inside", self.sim.process(frame(60))["range_exit_cleared"])
        self.assertFalse(self.sim.process(frame(61))["opened"])
        self.assertTrue(self.sim.process(frame(62))["opened"])

    def test_range_exit_flag_requires_its_timestamp(self):
        state = Account.start(D(100))
        state.range_exit = True
        with self.assertRaisesRegex(ValueError, "range-exit timestamp"):
            state.validate(MarketRules())

    def test_daily_loss_pause_preserves_sell_management_and_blocks_reentry(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        report = self.sim.process(frame(2, "0.02050"))
        state = self.sim.store.read()
        self.assertEqual("pause", report["decision"])
        self.assertIn("daily loss", report["reason"])
        self.assertFalse(state.halt)
        self.assertTrue(all(o.side == "sell" for o in state.orders.values()))
        self.assertFalse(report["opened"])

    def test_hard_drawdown_stays_latched_and_resume_cannot_erase_loss(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        report = self.sim.process(frame(2, "0.01000"))
        self.assertEqual("halt", report["decision"])
        self.assertEqual(0, self.sim.store.read().inventory)
        before = self.sim.store.read()
        self.restart()
        self.assertEqual("halt", self.sim.process(frame(3))["decision"])
        with self.assertRaisesRegex(ValueError, "risk limits"):
            self.sim.resume(frame(4), event_id="loss-reset", reason="try recovery")
        after = self.sim.store.read()
        self.assertEqual(before.risk_high, after.risk_high)
        self.assertEqual(before.reserve_high, after.reserve_high)
        self.assertTrue(after.halt)

    def test_emergency_resume_is_logged_idempotent_and_requires_confirmation(self):
        self.sim.process(frame(0))
        emergency = replace(frame(1), signals=replace(frame(1).signals, emergency=True))
        self.sim.process(emergency)
        self.assertTrue(self.sim.store.read().halt)
        result = self.sim.resume(frame(2), event_id="operator-1", reason="emergency cleared")
        state = encode(self.sim.store.read().to_dict())
        self.assertEqual("resume_pending", result["decision"])
        self.assertEqual(
            result, self.sim.resume(frame(2), event_id="operator-1", reason="emergency cleared")
        )
        self.assertEqual(state, encode(self.sim.store.read().to_dict()))
        self.assertFalse(result["fills"])
        self.assertFalse(self.sim.process(frame(3))["opened"])
        self.assertTrue(self.sim.process(frame(4))["opened"])
        audit = self.sim.store.connection.execute(
            "SELECT payload FROM events WHERE event_id='control/resume/operator-1'"
        ).fetchone()[0]
        self.assertEqual("emergency cleared", json.loads(audit)["reason"])

    def test_resume_rejects_nonflat_bad_data_and_missing_reason(self):
        self.sim.process(frame(0))
        with self.assertRaises(ValueError):
            self.sim.resume(frame(1), event_id="not-halted", reason="test")
        with self.assertRaises(ValueError):
            self.sim.resume(frame(1), event_id="empty-reason", reason="")
        self.sim.process(frame(1, "0.02196"))
        emergency = replace(frame(2, size="0"), signals=replace(frame(2).signals, emergency=True))
        self.sim.process(emergency)
        with self.assertRaisesRegex(ValueError, "flat paper account"):
            self.sim.resume(frame(3), event_id="held-inventory", reason="test")

    def test_partial_cancelled_buy_is_managed_without_overselling(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02270", size="3000"))
        state = self.sim.store.read()
        self.assertGreater(state.inventory, 0)
        self.assertTrue(
            any(o.side == "buy" and o.remaining < o.quantity for o in state.orders.values())
        )
        report = self.sim.process(frame(2, eligible=False))
        self.assertTrue(report["fills"])
        self.assertEqual(0, self.sim.store.read().inventory)
        self.assertFalse(self.sim.store.read().orders)

    def test_exhausted_settlement_is_guarded_without_mutation(self):
        state = Account.start(D(100))
        state.cash = D(0)
        before = encode(state.to_dict())
        with self.assertRaisesRegex(ValueError, "exhausted"):
            self.sim._settle(state, frame(0).quote)
        self.assertEqual(before, encode(state.to_dict()))

    def test_a_held_residue_is_on_both_sides_of_the_baseline_rescaling(self):
        # The residue is excluded from the allocation base but IS in day_start, risk_high
        # and every later active-equity reading. Excluding it from both sides of the ratio
        # shrinks the baselines, which can push a later drawdown across its threshold.
        state = Account.start(D(100))
        state.cash, state.inventory = D("110"), D("100")
        state.day_start = state.risk_high = D("112")
        quote = frame(0).quote
        # Exactly Account.equity's marking, which is what populated day_start and
        # risk_high: the unrounded liquidation price, not the tick-floored exit price.
        marked = (
            state.inventory
            * quote.bid
            * (D(1) - self.sim.rules.slippage_rate)
            * (D(1) - self.sim.rules.taker_fee)
        )
        flat = Account.start(D(100))
        flat.cash, flat.inventory = state.cash, state.inventory
        self.assertEqual(flat.equity(quote, self.sim.rules), state.cash + marked)
        self.assertGreater(marked, 0)
        allocation = self.sim._settle(state, quote)
        after = D(str(allocation["active_capital_after_allocation"]))
        expected = (after + marked) / (D("110") + marked)
        self.assertEqual(D("112") * expected, state.risk_high)
        self.assertEqual(D("112") * expected, state.day_start)
        # Excluding the residue from both sides would have been strictly smaller.
        self.assertGreater(expected, after / D("110"))

    def test_older_schema_databases_are_not_silently_reinterpreted(self):
        row = self.sim.store.connection.execute("SELECT identity FROM state").fetchone()[0]
        identity = json.loads(row)
        self.assertEqual(7, identity["schema"])
        # 4 is in the list: a database written before "exit-residue-v1" ran under the old
        # lifecycle, where a residue blocked settlement and a validation halt armed no
        # exit, so reopening it here would mix two semantics in one event history. 6 is
        # too: it was written with V2 structure either always on or not present at all.
        for old in (1, 2, 3, 4, 5, 6):
            identity["schema"] = old
            self.sim.store.connection.execute("UPDATE state SET identity=?", (encode(identity),))
            with self.subTest(schema=old), self.assertRaisesRegex(ValueError, "settings differ"):
                self.open()

    def crossed(self, index, bid="0.02330"):
        """A frame whose quote is invalid (bid above ask): raises ValueError, not Transient."""
        current = frame(index, bid)
        return replace(current, quote=replace(current.quote, ask=D(bid) - D("0.00100")))

    def test_data_halt_holding_inventory_exits_on_the_next_valid_frame(self):
        # Absorbing state 1: the halt cancelled the resting sells that were the only exit,
        # and resume() refuses a non-flat account, so the position was frozen for good.
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        held = self.sim.store.read()
        self.assertGreater(held.inventory, 0)
        report = self.sim.process(self.crossed(2))
        after_bad = self.sim.store.read()
        self.assertEqual("halt", report["decision"])
        self.assertIn("uncrossed", report["reason"])
        # Nothing is traded on the invalid frame itself: it returns before liquidation.
        self.assertFalse(report["fills"])
        self.assertEqual(held.inventory, after_bad.inventory)
        self.assertEqual(held.cash, after_bad.cash)
        self.assertEqual(held.fees, after_bad.fees)
        self.assertTrue(after_bad.liquidating)
        self.assertFalse(after_bad.orders)
        self.restart()
        exit_report = self.sim.process(frame(3, "0.02330"))
        self.assertEqual("halt", exit_report["decision"])
        self.assertEqual("liquidation", exit_report["exit_reason"])
        self.assertEqual(0, self.sim.store.read().inventory)
        self.assertEqual(
            "resume_pending",
            self.sim.resume(frame(4), event_id="incident-1", reason="feed fixed")["decision"],
        )
        self.assertFalse(self.sim.store.read().liquidating)

    def test_a_flat_data_halt_stays_resumable_without_arming_liquidation(self):
        # The one genuinely recoverable halt must keep working, and a flat halt must not
        # be marked as liquidating.
        self.sim.process(frame(0))
        report = self.sim.process(replace(frame(1), atr=D(0)))
        self.assertEqual("halt", report["decision"])
        state = self.sim.store.read()
        self.assertEqual(0, state.inventory)
        self.assertFalse(state.liquidating)
        self.assertEqual(
            "resume_pending",
            self.sim.resume(frame(2), event_id="flat-1", reason="input fixed")["decision"],
        )

    def test_incomplete_liquidation_still_blocks_resume_and_says_why(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(self.crossed(2))
        # A thin book cannot absorb the position, so the exit is still outstanding.
        self.sim.process(frame(3, "0.02330", size="1000"))
        self.assertGreater(self.sim.store.read().inventory, 0)
        with self.assertRaisesRegex(ValueError, "flat paper account.*still held"):
            self.sim.resume(frame(4), event_id="too-early", reason="test")

    def test_a_halt_holding_only_dust_is_resumable(self):
        # Spec v1 amendment 1 reverses PR #122's exact-zero rule: a residue below the
        # exchange minimum is liquidation-complete, so it no longer locks a resumable
        # (integrity) halt. It stays held and marked; the risk check still decides.
        self.dust()
        self.sim.process(self.crossed(3))
        state = self.sim.store.read()
        self.assertEqual(("integrity", D(100)), (state.halt_category, state.inventory))
        result = self.sim.resume(frame(4, "0.02330"), event_id="dust/4", reason="test")
        state = self.sim.store.read()
        self.assertEqual("resume_pending", result["decision"])
        self.assertEqual(("", "", D(100)), (state.halt, state.halt_category, state.inventory))
        self.assertTrue(state.draining)

    def dust(self):
        """Leave a residue below the minimum notional: 100 units are worth about 2.3."""
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196", size="1000"))
        self.sim.process(frame(2, eligible=False))  # cancels the partial buy, arms the drain
        state = self.sim.store.read()
        self.assertEqual(D(100), state.inventory)
        self.assertLess(state.inventory * D("0.02330"), self.sim.rules.minimum_notional)
        self.assertFalse(state.orders)
        return state

    def test_unsellable_residue_does_not_freeze_a_healthy_account(self):
        # Neither halted nor paused, eligible data, 2.3 of 100 units stuck as dust: the
        # harvest gate required inventory == ZERO, so no grid was ever opened again.
        self.dust()
        for index in range(3, 10):
            self.sim.process(frame(index, "0.02330"))
        state = self.sim.store.read()
        self.assertEqual(D(100), state.inventory)  # still unsellable, and not written off
        self.assertGreaterEqual(state.cycles, 2)
        self.assertTrue(any(order.side == "buy" for order in state.orders.values()))

    def test_a_residue_that_becomes_sellable_is_exited_not_left_behind(self):
        self.dust()
        for index in range(3, 10):
            self.sim.process(frame(index, "0.02330"))
        self.assertEqual(D(100), self.sim.store.read().inventory)
        # A tenfold price rise puts the residue above the minimum notional again.
        for index in range(10, 14):
            self.sim.process(frame(index, "0.23300"))
        self.assertEqual(0, self.sim.store.read().inventory)

    def test_a_residue_that_becomes_sellable_is_exited_while_buys_rest(self):
        # The new grid's lower buys cannot pair the old residue: each buy's sell covers
        # only its own fill. So the residue is sold once the market will take it.
        self.dust()
        for index in range(3, 10):
            self.sim.process(frame(index, "0.02330"))
        self.assertTrue(any(o.side == "buy" for o in self.sim.store.read().orders.values()))
        self.sim.process(frame(10, "0.06000"))
        state = self.sim.store.read()
        self.assertEqual(0, state.inventory)
        self.assertTrue(any(o.side == "buy" for o in state.orders.values()))

    def test_range_exit_clears_with_an_unsellable_residue(self):
        # Absorbing state 4: clearing the exit required inventory == ZERO, which
        # liquidation cannot deliver once the remainder is below the minimum notional.
        self.dust()
        for index in (3, 4, 5, 7, 8):
            self.sim.process(frame(index, "0.02500"))
        self.assertTrue(self.sim.store.read().range_exit)
        self.assertEqual(D(100), self.sim.store.read().inventory)
        report = self.sim.process(frame(9, "0.02300"))
        self.assertEqual("returned inside", report["range_exit_cleared"])
        state = self.sim.store.read()
        self.assertFalse(state.range_exit)
        self.assertEqual(D(100), state.inventory)

    def test_a_hard_drawdown_halt_says_it_restarts_by_itself_not_by_hand(self):
        # Spec v1 amendment 1: the manual resume is still refused by the frozen risk
        # check, and the refusal now says what clears the halt instead: the cool-off.
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(frame(2, "0.01000"))
        state = self.sim.store.read()
        self.assertTrue(state.halt)
        self.assertEqual(
            ("drawdown", frame(2).quote.observed_at), (state.halt_category, state.halt_since)
        )
        with self.assertRaisesRegex(ValueError, "frozen.*restarts automatically"):
            self.sim.resume(frame(3), event_id="drawdown", reason="try recovery")

    def test_resume_cli_loads_saved_rules_and_requires_current_frame(self):
        self.check_resume_cli()

    def test_resume_cli_restores_a_separate_taker_fee(self):
        self.sim.close()
        self.path = Path(self.temp.name) / "taker.db"
        self.sim = self.open(MarketRules(fee_rate=D("0"), taker_fee_rate=D("0.0009")))
        self.check_resume_cli()  # a mis-decoded taker fee would fail as "settings differ"

    def test_resume_cli_restores_the_inventory_cap(self):
        self.reopen(replace(self.policy, inventory_cap=D("0.4")), "capped.db")
        self.check_resume_cli()  # a dropped or undecoded cap would fail loudly, not resume

    def check_resume_cli(self):
        emergency = replace(frame(0), signals=replace(frame(0).signals, emergency=True))
        self.sim.process(emergency)
        recent = frame(1)
        now = datetime.now(UTC)
        recent = replace(
            recent,
            quote=replace(recent.quote, observed_at=now.isoformat(), received_at=now.isoformat()),
            signals=replace(recent.signals, observed_at=now),
        )
        path = Path(self.temp.name) / "frame.json"
        path.write_text(encode(recent.payload()))
        self.assertEqual(recent.payload(), decode_frame(json.loads(path.read_text())).payload())
        report = resume_paper(self.path, self.config, path, event_id="cli", reason="reviewed")
        self.assertEqual("resume_pending", report["decision"])
        path.write_text(encode(frame(1).payload()))
        with self.assertRaisesRegex(ValueError, "current fresh"):
            resume_paper(self.path, self.config, path, event_id="old", reason="reviewed")


class ReentryTests(TestCase):
    def setUp(self):
        self.rules = MarketRules("TESTUSDT", D("0.01"), D(1), D(5))
        self.account = Account.start(D(100))

    def quote(self, i, bid, size="1000"):
        when = (START + timedelta(seconds=i)).isoformat()
        return Quote(str(i), "TESTUSDT", when, when, D(bid), D(bid) + D("0.01"), D(size), D(size))

    def test_reentry_continues_while_other_inventory_is_held(self):
        place(self.account, LimitOrder("upper", "buy", D(10), D(2), D(2), target=D(11)), self.rules)
        place(self.account, LimitOrder("lower", "buy", D(9), D(2), D(2), target=D(10)), self.rules)
        match(self.account, self.quote(0, "8.8"), self.rules)
        fills = match(self.account, self.quote(1, "10.2"), self.rules)
        self.assertEqual(["sell"], [f.side for f in fills])
        self.assertEqual(D(2), self.account.inventory)
        self.assertTrue(any(o.side == "buy" and o.price == 9 for o in self.account.orders.values()))
        self.assertEqual(
            ["buy"], [f.side for f in match(self.account, self.quote(2, "8.8"), self.rules)]
        )
        self.assertEqual(D(4), self.account.inventory)

    def test_partial_sell_waits_for_completion_and_reserve_cannot_fund_reentry(self):
        self.account.cash = D(80)
        self.account.inventory = D(2)
        place(
            self.account, LimitOrder("sell", "sell", D(11), D(2), D(2), reentry=D(10)), self.rules
        )
        match(self.account, self.quote(0, "11.2", "10"), self.rules)
        self.assertTrue(all(o.side == "sell" for o in self.account.orders.values()))
        self.account.pending = D(90)
        match(self.account, self.quote(1, "11.2", "10"), self.rules)
        self.assertEqual({}, self.account.orders)
        self.assertEqual(D(90), self.account.pending)

    def test_remaining_liquidity_and_reserved_inventory_are_respected(self):
        self.account.inventory = D(8)
        place(self.account, LimitOrder("sell", "sell", D(11), D(4), D(4)), self.rules)
        quote = self.quote(0, "11.2", "60")
        fills = match(self.account, quote, self.rules, recycle=False)
        exits = reduce_unreserved(
            self.account, quote, self.rules, consumed=sum((f.quantity for f in fills), D(0))
        ).fills
        self.assertEqual(D(4), fills[0].quantity)
        self.assertEqual(D(2), exits[0].quantity)
        self.assertEqual(D(2), self.account.inventory)


class PanelFixTests(TestCase):
    """Findings of the 2026-09-28 panel review on the runner (PR #122 follow-up)."""

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "paper.db"
        self.config = replace(load_config(ROOT / "config/default.toml"), minimum_transfer_quote=0.1)
        self.policy = SimulationPolicy(outside_range_seconds=3, maximum_frame_gap_seconds=30)
        self.sim = PaperSimulator(self.path, self.config, MarketRules(), policy=self.policy)

    def tearDown(self):
        if self.sim is not None:
            self.sim.close()

    def test_resolved_is_the_stricter_gate_under_a_partly_filled_buy(self):
        # The harvest gate calls _resolved while buys may still rest. Its docstring once
        # claimed every caller was gated on an empty book; it is not, and the two
        # measures disagree here by design: _resolved refuses the harvest, while the
        # drain's measure owes nothing because the child sell will pair the inventory.
        from crypto_grid_bot.simulation.execution import exit_state, unpaired_inventory

        account = Account.start(D(100))
        account.orders["b"] = LimitOrder("b", "buy", D("0.02000"), D(5000), D(2000))
        account.inventory = D(3000)
        account.cash = D(40)
        quote = frame(0).quote
        self.assertFalse(self.sim._resolved(account, quote))
        self.assertEqual(D(0), unpaired_inventory(account))
        self.assertEqual("", exit_state(account, quote, self.sim.rules)[0])

    def test_an_exhaustion_halt_arms_the_exit_for_a_held_residue(self):
        # Before the fix this was the one halt site that left liquidating False, so a
        # residue held at exhaustion was reported as stuck only a frame later, once the
        # risk engine re-halted the account.
        account = Account.start(D(100))
        account.cash = D(0)
        account.inventory = D(100)  # about 2.3 quote at this bid: below the minimum
        account.risk_high = account.day_start = D("2")
        account.draining = True
        self.sim._step(account, frame(0))
        self.assertTrue(account.halt.startswith("active capital exhausted"), account.halt)
        self.assertTrue(account.liquidating)

    def test_a_schema_four_database_is_refused_by_the_resume_cli(self):
        self.sim.process(frame(0))
        self.sim.close()
        connection = sqlite3.connect(self.path)
        try:
            identity = json.loads(
                connection.execute("SELECT identity FROM state WHERE id=1").fetchone()[0]
            )
            identity["schema"] = 4
            connection.execute("UPDATE state SET identity=? WHERE id=1", (json.dumps(identity),))
            connection.commit()
        finally:
            connection.close()
        now = datetime.now(UTC)
        recent = frame(1)
        recent = replace(
            recent,
            quote=replace(recent.quote, observed_at=now.isoformat(), received_at=now.isoformat()),
            signals=replace(recent.signals, observed_at=now),
        )
        path = Path(self.temp.name) / "frame.json"
        path.write_text(encode(recent.payload()))
        with self.assertRaisesRegex(ValueError, "paper schema 7"):
            resume_paper(self.path, self.config, path, event_id="cli", reason="reviewed")
        self.sim = None  # the tampered database cannot be reopened; nothing left to close
