"""Spec v1 amendment 1 (drawdown recovery): the tests it requires before any rerun.

Prices are constructed, not backtest evidence. The fixtures step one second per frame,
so a 24-hour cool-off is a jump of 86400 seconds; the continuity gap (30 s) breaks the
confirmation count, which is why every rebase and restart below needs two consecutive
eligible frames after the jump.
"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from test_strategy_recovery import at_fair_value, frame

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import Account, D, MarketRules
from crypto_grid_bot.simulation.runner import RESTART_PAUSE, PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400
# A fall of about 2% a day: below the 3% daily-loss pause, past the 8% soft drawdown on
# day 5 and never near the 12% hard drawdown.
DECLINE = ["0.02196", "0.02150", "0.02105", "0.02060", "0.02015"]
# The fields an automatic restart may change (amendment 1, "The restart then changes
# exactly these fields"), beyond the timestamps and the mark every valid step records.
RESTART_FIELDS = {
    "halt",
    "liquidating",
    "range_exit",
    "range_exit_since",
    "outside_seconds",
    "outside_last",
    "grid_lower",
    "grid_upper",
    "risk_high",
    "halt_since",
    "halt_category",
    "pause",
    "recovery_count",
    "draining",
    "down_since",
}
STEP_FIELDS = {"last_observed", "last_received", "last_equity", "measure_high", "day", "day_start"}


def emergency(current):
    return replace(current, signals=replace(current.signals, emergency=True))


class DrawdownRecoveryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "paper.db"
        self.config = replace(load_config(ROOT / "config/default.toml"), minimum_transfer_quote=0.1)
        # A wide range window: these tests are about the drawdown controls, not the
        # outside-range exit, which the recovery fixtures trigger after 3 seconds.
        self.policy = SimulationPolicy(
            outside_range_seconds=10_000_000, maximum_frame_gap_seconds=30
        )
        self.sim = self.open()
        self.addCleanup(lambda: self.sim.close())

    def open(self):
        return PaperSimulator(self.path, self.config, MarketRules(), policy=self.policy)

    def restart_process(self):
        self.sim.close()
        self.sim = self.open()

    def state(self):
        return self.sim.store.read()

    # -- fixtures -----------------------------------------------------------------

    def decline(self):
        """Open a grid, fill its buys, then fall 2% a day until the soft drawdown."""
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        for day, bid in enumerate(DECLINE, start=1):
            report = self.sim.process(frame(day * DAY, bid))
            self.sim.process(frame(day * DAY + 1, bid))
        self.assertIn("soft drawdown", report["reason"])
        state = self.state()
        self.assertEqual(frame(5 * DAY).quote.observed_at, state.episode_since)
        self.assertEqual(D(100), state.risk_high)
        return state

    def halt(self):
        """A hard-drawdown halt at 00:00:02 on day 0, fully liquidated."""
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        report = self.sim.process(frame(2, "0.01000"))
        state = self.state()
        self.assertEqual("halt", report["decision"])
        self.assertEqual(
            ("drawdown", frame(2).quote.observed_at), (state.halt_category, state.halt_since)
        )
        self.assertEqual(D(0), state.inventory)
        return state

    # -- soft drawdown (option C) --------------------------------------------------

    def test_the_first_reduce_starts_an_episode_and_nothing_rebases_before_24_hours(self):
        self.decline()
        # 23 h 59 min 58 s after the episode start, two eligible frames: still too early.
        for index in (6 * DAY - 2, 6 * DAY - 1):
            report = self.sim.process(frame(index, "0.02015"))
            self.assertNotIn("rebase", report)
        self.assertEqual(D(100), self.state().risk_high)
        # 24 h exactly, second consecutive confirmation: committed.
        report = self.sim.process(frame(6 * DAY, "0.02015"))
        state = self.state()
        self.assertEqual(
            {
                "episode_since": frame(5 * DAY).quote.observed_at,
                "old_reference": "100",
                "new_reference": str(state.last_equity),
            },
            report["rebase"],
        )
        self.assertEqual(state.last_equity, state.risk_high)
        self.assertEqual(("", 0), (state.episode_since, state.episode_count))
        self.assertEqual(D(100), state.measure_high)  # C1(b): never rebased
        # The pause then recovers normally and the grid is managed again.
        self.assertEqual("hold", self.sim.process(frame(6 * DAY + 1, "0.02015"))["decision"])

    def test_a_trigger_just_before_midnight_still_waits_a_full_day(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        # Each UTC day starts from the previous frame's equity, so the fall is spread so
        # that no day loses 3% and the trigger frame is the last second of day 4.
        for index, bid in (
            (DAY, "0.02196"),
            (2 * DAY, "0.02150"),
            (3 * DAY, "0.02105"),
            (3 * DAY + 1, "0.02080"),
            (4 * DAY, "0.02050"),
        ):
            self.sim.process(frame(index, bid))
        trigger = 5 * DAY - 1  # 23:59:59 on day 4
        report = self.sim.process(frame(trigger, "0.02015"))
        self.assertIn("soft drawdown", report["reason"])
        self.assertEqual(frame(trigger).quote.observed_at, self.state().episode_since)
        # The day rolls one second later; that is not a cool-off.
        self.sim.process(frame(trigger + 1, "0.02015"))
        self.sim.process(frame(trigger + 2, "0.02015"))
        self.assertEqual(D(100), self.state().risk_high)
        self.sim.process(frame(trigger + DAY - 1, "0.02015"))
        self.assertEqual(D(100), self.state().risk_high)
        self.assertIn("rebase", self.sim.process(frame(trigger + DAY, "0.02015")))

    def test_no_rebase_while_a_daily_pause_an_emergency_or_a_data_block_is_active(self):
        self.decline()
        # A 3%+ fall inside the day after the cool-off: the tentative check says PAUSE.
        self.sim.process(frame(6 * DAY, "0.02015"))
        report = self.sim.process(frame(6 * DAY + 1, "0.01920"))
        self.assertNotIn("rebase", report)
        self.assertIn("daily loss", report["reason"])
        self.assertEqual(0, self.state().episode_count)
        # Back at the day's start price: one confirmation, then an emergency frame.
        self.sim.process(frame(6 * DAY + 2, "0.02015"))
        self.assertEqual(1, self.state().episode_count)
        report = self.sim.process(emergency(frame(6 * DAY + 3, "0.02015")))
        self.assertEqual("halt", report["decision"])  # the emergency halt ends the episode
        self.assertEqual(
            ("emergency", ""), (self.state().halt_category, self.state().episode_since)
        )

    def test_an_ineligible_frame_resets_the_confirmations(self):
        self.decline()
        self.sim.process(frame(6 * DAY, "0.02015"))
        self.assertEqual(1, self.state().episode_count)
        self.sim.process(frame(6 * DAY + 1, "0.02015", eligible=False))
        self.assertEqual(0, self.state().episode_count)
        self.sim.process(frame(6 * DAY + 2, "0.02015"))
        self.assertEqual(D(100), self.state().risk_high)
        self.assertIn("rebase", self.sim.process(frame(6 * DAY + 3, "0.02015")))

    def test_one_rebase_per_episode_and_a_later_reduce_starts_a_new_one(self):
        self.decline()
        self.sim.process(frame(6 * DAY, "0.02015"))
        self.sim.process(frame(6 * DAY + 1, "0.02015"))
        first = self.state()
        self.assertEqual(first.last_equity, first.risk_high)
        # Another 8% fall from the rebased reference, spread over three days so no day
        # loses 3%: a new episode with its own cool-off.
        for day, bid in ((7, "0.01950"), (8, "0.01880"), (9, "0.01810")):
            self.sim.process(frame(day * DAY, bid))
            self.assertEqual("", self.state().episode_since)  # under 8% from 91.76
        report = self.sim.process(frame(10 * DAY, "0.01760"))
        state = self.state()
        self.assertIn("soft drawdown", report["reason"])
        self.assertEqual(frame(10 * DAY).quote.observed_at, state.episode_since)
        self.assertEqual(first.risk_high, state.risk_high)  # its own 24-hour cool-off
        self.sim.process(frame(10 * DAY + 1, "0.01760"))
        self.assertEqual(first.risk_high, self.state().risk_high)

    def test_a_process_restart_before_and_after_a_rebase_keeps_the_episode(self):
        self.decline()
        self.restart_process()
        self.assertEqual(frame(5 * DAY).quote.observed_at, self.state().episode_since)
        self.sim.process(frame(6 * DAY, "0.02015"))
        self.restart_process()
        self.assertEqual(1, self.state().episode_count)
        self.assertIn("rebase", self.sim.process(frame(6 * DAY + 1, "0.02015")))
        self.restart_process()
        state = self.state()
        self.assertEqual(("", state.last_equity), (state.episode_since, state.risk_high))

    def test_a_range_exit_waiting_in_cash_is_released_by_the_rebase(self):
        # Before the amendment this was the lockout: the exit needs ALLOW to clear, and
        # a flat account 8% below its reference could never reach it.
        self.sim.close()
        self.policy = SimulationPolicy(outside_range_seconds=3, maximum_frame_gap_seconds=30)
        self.path = Path(self.temp.name) / "range.db"
        self.sim = self.open()
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        for index in range(2, 6):  # four seconds outside the band: exit to cash
            self.sim.process(frame(index, "0.02015"))
        state = self.state()
        self.assertTrue(state.range_exit)
        self.assertEqual(D(0), state.inventory)
        # On day 0 the fall is a daily loss, which outranks the soft drawdown in the
        # engine; the episode starts at the next day's first frame, 8% below 100.
        self.sim.process(frame(DAY + 6, "0.02015"))
        state = self.state()
        self.assertEqual(frame(DAY + 6).quote.observed_at, state.episode_since)
        self.assertTrue(state.range_exit)  # flat, 8% below: the old lockout
        self.sim.process(frame(2 * DAY + 6, "0.02015"))
        self.assertTrue(self.state().range_exit)
        report = self.sim.process(frame(2 * DAY + 7, "0.02015"))
        self.assertIn("rebase", report)
        self.assertEqual("recenter", report["range_exit_cleared"])
        self.assertFalse(self.state().range_exit)

    # -- measurement references ----------------------------------------------------

    def test_the_c1b_reference_equals_risk_high_at_every_evaluation_without_a_rebase(self):
        seen = []
        self.sim.risk_observer = lambda equity, high, reference, decision: seen.append(
            (high, reference)
        )
        self.sim.process(frame(0))
        for index, bid in enumerate(
            ["0.02196", "0.02330", "0.02400", "0.02300", "0.02330"], start=1
        ):
            self.sim.process(frame(index, bid))
        state = self.state()
        self.assertGreater(state.settlement_count, 0)  # the harvest scaled both references
        self.assertGreater(len(seen), 5)
        self.assertTrue(all(high == reference for high, reference in seen), seen)
        self.assertEqual(state.risk_high, state.measure_high)

    def test_the_c1b_reference_is_scaled_at_settlement_and_never_rebased_or_restarted(self):
        self.decline()
        self.sim.process(frame(6 * DAY, "0.02015"))
        self.sim.process(frame(6 * DAY + 1, "0.02015"))
        state = self.state()
        self.assertLess(state.risk_high, state.measure_high)
        self.assertEqual(D(100), state.measure_high)
        # Then a crash, a halt and an automatic restart: still untouched.
        self.sim.process(frame(6 * DAY + 2, "0.01000"))
        self.assertEqual("drawdown", self.state().halt_category)
        report = self.sim.process(frame(7 * DAY + 2, "0.01000"))
        self.assertIn("restart", report)
        self.assertEqual(D(100), self.state().measure_high)

    # -- hard drawdown (automatic restart) -----------------------------------------

    def test_a_drawdown_halt_restarts_after_24_hours_with_a_recovery_pause(self):
        self.halt()
        report = self.sim.process(frame(DAY + 1, "0.01000"))  # 23:59:59 after the halt
        self.assertEqual("halt", report["decision"])
        report = self.sim.process(frame(DAY + 2, "0.01000"))
        state = self.state()
        self.assertEqual(
            {
                "halt_since": frame(2).quote.observed_at,
                "category": "drawdown",
                "halt": "hard drawdown reached: 44.38%",
                "old_reference": "100",
                "new_reference": str(state.last_equity),
            },
            report["restart"],
        )
        self.assertEqual(
            ("", "", "", RESTART_PAUSE),
            (state.halt, state.halt_since, state.halt_category, state.pause),
        )
        self.assertEqual(
            (state.last_equity, True, 0), (state.risk_high, state.draining, state.recovery_count)
        )
        self.assertEqual("pause", report["decision"])
        # The normal confirmations apply before a new grid.
        self.assertEqual("pause", self.sim.process(frame(DAY + 3, "0.01000"))["decision"])
        self.assertNotEqual("pause", self.sim.process(frame(DAY + 4, "0.01000"))["decision"])

    def test_a_restart_changes_only_the_listed_fields(self):
        self.halt()
        self.sim.process(frame(DAY + 1, "0.01000"))
        before = self.state().to_dict()
        self.assertIn("restart", self.sim.process(frame(DAY + 2, "0.01000")))
        after = self.state().to_dict()
        changed = {key for key in before if before[key] != after.get(key)} | {
            key for key in after if key not in before
        }
        self.assertLessEqual(changed, RESTART_FIELDS | STEP_FIELDS, changed)
        for key in (
            "day",
            "day_start",
            "measure_high",
            "reserve_high",
            "pending",
            "secured",
            "cash",
            "inventory",
        ):
            self.assertEqual(before[key], after[key], key)

    def test_a_restart_waits_for_the_liquidation_to_complete_and_admits_dust(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(frame(2, "0.01000", size="3000"))  # thin book: one chunk sells
        state = self.state()
        self.assertEqual("drawdown", state.halt_category)
        self.assertGreater(state.inventory, 0)
        # A day later the book is still thin: the exit is incomplete, no restart.
        report = self.sim.process(frame(DAY + 2, "0.01000", size="0"))
        self.assertNotIn("restart", report)
        self.assertTrue(self.state().halt)
        # A deep book completes the liquidation and the restart happens on that frame.
        report = self.sim.process(frame(DAY + 3, "0.01000"))
        self.assertIn("restart", report)
        self.assertFalse(self.state().halt)

    def test_the_emergency_flag_blocks_a_restart_while_set(self):
        self.halt()
        report = self.sim.process(emergency(frame(DAY + 2, "0.01000")))
        self.assertNotIn("restart", report)
        state = self.state()
        self.assertEqual("drawdown", state.halt_category)  # never re-categorised
        self.assertIn("restart", self.sim.process(frame(DAY + 3, "0.01000")))

    def test_a_halt_instance_restarts_at_most_once_and_a_new_fall_is_a_new_instance(self):
        self.halt()
        self.sim.process(frame(DAY + 2, "0.01000"))
        self.assertFalse(self.state().halt)
        # Recover the pause, open a grid around the new price and fill its buys.
        self.sim.process(at_fair_value(DAY + 3, "0.01000"))
        report = self.sim.process(at_fair_value(DAY + 4, "0.01000"))
        self.assertEqual("open_grid", report["decision"])
        self.sim.process(at_fair_value(DAY + 5, "0.00900"))
        self.assertGreater(self.state().inventory, 0)
        # 12% below the rebased reference: a new instance with its own cool-off.
        report = self.sim.process(at_fair_value(DAY + 6, "0.00740"))
        state = self.state()
        self.assertEqual(
            ("halt", "drawdown", frame(DAY + 6).quote.observed_at),
            (report["decision"], state.halt_category, state.halt_since),
        )
        self.assertNotIn("restart", self.sim.process(at_fair_value(2 * DAY + 5, "0.00740")))
        self.assertIn("restart", self.sim.process(at_fair_value(2 * DAY + 6, "0.00740")))

    def test_only_a_drawdown_halt_restarts(self):
        self.sim.process(frame(0))
        crossed = replace(frame(1), quote=replace(frame(1).quote, ask=D("0.02200")))
        self.sim.process(crossed)  # bid above ask: an integrity halt
        state = self.state()
        self.assertEqual(
            ("integrity", frame(1).quote.observed_at), (state.halt_category, state.halt_since)
        )
        # A crash past 12% during the integrity halt does not re-categorise it, and a
        # day later it is still latched.
        self.sim.process(frame(2, "0.01000"))
        self.assertEqual("integrity", self.state().halt_category)
        report = self.sim.process(frame(DAY + 2, "0.01000"))
        self.assertNotIn("restart", report)
        self.assertTrue(self.state().halt)

    def test_an_invalid_frame_during_a_drawdown_halt_keeps_its_identity(self):
        first = self.halt()
        crossed = replace(frame(3), quote=replace(frame(3).quote, ask=D("0.02000")))
        self.sim.process(crossed)
        state = self.state()
        self.assertEqual(
            (first.halt, first.halt_since, "drawdown"),
            (state.halt, state.halt_since, state.halt_category),
        )

    def test_a_restart_is_journaled_and_idempotent_across_a_process_restart(self):
        self.halt()
        self.restart_process()
        report = self.sim.process(frame(DAY + 2, "0.01000"))
        self.assertIn("restart", report)
        state = encode(self.state().to_dict())
        self.restart_process()
        self.assertEqual(report, self.sim.process(frame(DAY + 2, "0.01000")))  # duplicate event
        self.assertEqual(state, encode(self.state().to_dict()))

    # -- manual resume ---------------------------------------------------------------

    def test_a_manual_resume_admits_dust_but_not_an_incomplete_liquidation(self):
        self.sim.process(frame(0))
        crossed = replace(
            frame(1, "0.02196"), quote=replace(frame(1, "0.02196").quote, ask=D("0.02000"))
        )
        self.sim.process(frame(1, "0.02196", size="1000"))  # a partial buy: 100 units held
        self.sim.process(replace(frame(2), quote=replace(frame(2).quote, ask=D("0.02000"))))
        state = self.state()
        self.assertEqual("integrity", state.halt_category)
        self.assertEqual(D(100), state.inventory)  # dust at this bid
        result = self.sim.resume(frame(3), event_id="dust", reason="test")
        self.assertEqual("resume_pending", result["decision"])
        self.assertEqual(("", ""), (self.state().halt_category, self.state().halt_since))
        del crossed

    def test_policy_cooloffs_are_validated_and_persisted(self):
        for name in ("soft_cooloff_seconds", "hard_cooloff_seconds"):
            with self.subTest(name), self.assertRaisesRegex(ValueError, name):
                SimulationPolicy(**{name: 0})
        identity = SimulationPolicy().identity()
        self.assertEqual(
            (86400, 86400), (identity["soft_cooloff_seconds"], identity["hard_cooloff_seconds"])
        )

    def test_account_state_validates_the_halt_identity(self):
        account = Account.start(D(100))
        account.halt = "x"
        with self.assertRaisesRegex(ValueError, "halt category"):
            account.validate(MarketRules())
        account.halt_category = "drawdown"
        account.episode_since = frame(0).quote.observed_at
        with self.assertRaisesRegex(ValueError, "episode"):
            account.validate(MarketRules())
