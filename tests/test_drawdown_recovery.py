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

from test_backtest_replay import HOUR_MS, RULES, START_MS, WARMUP, candle, engine_for, hourly
from test_strategy_recovery import at_fair_value, frame, stale

from crypto_grid_bot.backtest.replay import RunConfig, check_accounting, replay
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.execution import exit_state
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

    def heal(self):
        """decline(), then a partial recovery to 6.6% below the reference: the episode is
        still open, but the account is back under the soft limit."""
        self.decline()
        self.sim.process(frame(5 * DAY + 2, "0.02060"))
        state = self.state()
        self.assertEqual(frame(5 * DAY).quote.observed_at, state.episode_since)
        self.assertLess(D("0.92") * state.risk_high, state.last_equity)
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

    def dust_halt(self):
        """The same halt on a thinner book: the liquidation sells 3080 units and leaves
        486, worth about 4.86 at this bid, below the 5-unit minimum notional. That is
        liquidation-complete; the residue is dust, held and marked."""
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(frame(2, "0.01000", size="30800"))
        state = self.state()
        self.assertEqual("drawdown", state.halt_category)
        self.assertEqual(D(486), state.inventory)
        self.assertEqual("dust", exit_state(state, frame(2, "0.01000").quote, self.sim.rules)[0])
        return state

    def integrity_halt(self, bid):
        """decline(), then a crossed quote (bid above ask) on day 5: an ``integrity`` halt,
        whose armed liquidation sells everything on the next frame at ``bid``. That leaves
        the account 6.67% below its reference of 100 at 0.02060, 8.28% at 0.02015 (the
        strategy audit's D17 reproduction), 9.49% at 0.01980, 3.05% below the day's start,
        and 15.90% at 0.01800."""
        self.decline()
        crossed = frame(5 * DAY + 2, "0.02015")
        self.sim.process(replace(crossed, quote=replace(crossed.quote, ask=D("0.01915"))))
        self.sim.process(frame(5 * DAY + 3, bid))
        state = self.state()
        self.assertEqual(("integrity", D(0)), (state.halt_category, state.inventory))
        return state

    def fresh(self, name):
        """A new account in its own database, for a scenario that must start clean."""
        self.sim.close()
        self.path = Path(self.temp.name) / name
        self.sim = self.open()

    def put(self, account):
        """Overwrite the saved account (autocommit connection) for a constructed state."""
        self.sim.store.connection.execute(
            "UPDATE state SET data=? WHERE id=1", (encode(account.to_dict()),)
        )

    def exhaustion(self):
        """An ``exhaustion`` halt: no active cash, 100 units of dust (about 2.3 at this
        bid), and a reference within the limits, as in the panel-review fixture. The
        harvest gate is the only exhaustion site and runs only on an account the risk
        check has not halted, so such a halt always starts under 12% drawdown."""
        account = self.state()
        account.cash, account.inventory = D(0), D(100)
        account.risk_high = account.day_start = D(2)
        account.draining = True
        self.put(account)
        self.sim.process(frame(0))
        state = self.state()
        self.assertEqual(("exhaustion", D(100)), (state.halt_category, state.inventory))
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

    def test_a_data_block_never_rebases_and_resets_the_confirmations(self):
        # Without the stale frame, 6 d + 1 s would be the second confirmation and commit.
        self.decline()
        self.sim.process(frame(6 * DAY, "0.02015"))
        self.assertEqual(1, self.state().episode_count)
        report = self.sim.process(stale(frame(6 * DAY + 1, "0.02015")))
        self.assertNotIn("rebase", report)
        self.assertIn("stale", report["reason"])
        self.assertEqual((0, D(100)), (self.state().episode_count, self.state().risk_high))
        self.assertNotIn("rebase", self.sim.process(frame(6 * DAY + 2, "0.02015")))
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

    # -- D7: a recovered episode closes without a rebase (owner decision 2026-10-02) ---

    def test_an_episode_healed_under_the_soft_limit_closes_without_a_rebase(self):
        self.heal()
        self.sim.process(frame(6 * DAY, "0.02060"))
        report = self.sim.process(frame(6 * DAY + 1, "0.02060"))  # the rebase would commit
        state = self.state()
        self.assertNotIn("rebase", report)
        self.assertEqual(
            {
                "episode_since": frame(5 * DAY).quote.observed_at,
                "closed_at": frame(6 * DAY + 1).quote.observed_at,
                "equity": str(state.last_equity),
                "reference": "100",
            },
            report["episode_closed"],
        )
        self.assertEqual(
            (D(100), "", 0), (state.risk_high, state.episode_since, state.episode_count)
        )
        self.assertEqual("hold", report["decision"])  # the pause recovered as it always did
        # Journaled: after a process restart the event replays its recorded result.
        self.restart_process()
        self.assertEqual(report, self.sim.process(frame(6 * DAY + 1, "0.02060")))

    def test_an_episode_still_8_percent_or_more_down_rebases_as_before(self):
        self.decline()  # 8.24% below the reference when the rebase falls due
        self.sim.process(frame(6 * DAY, "0.02015"))
        report = self.sim.process(frame(6 * DAY + 1, "0.02015"))
        state = self.state()
        self.assertNotIn("episode_closed", report)
        self.assertEqual(
            ("100", str(state.last_equity)),
            (report["rebase"]["old_reference"], report["rebase"]["new_reference"]),
        )
        self.assertEqual(state.last_equity, state.risk_high)

    def test_exactly_8_percent_down_still_rebases_and_a_hair_less_closes(self):
        # The risk engine counts a drawdown of exactly 8% as soft (loss >= limit), so the
        # episode closes only when equity is strictly above 92% of risk_high.
        for name, cash, closes in (("exact.db", "92", False), ("hair.db", "92.000000001", True)):
            with self.subTest(cash=cash):
                self.fresh(name)
                account = self.state()  # flat, against a reference of 100
                account.cash = account.last_equity = D(cash)
                account.episode_since = frame(-DAY).quote.observed_at
                account.pause, account.draining = "soft drawdown reached: 8.00%", True
                self.put(account)
                self.sim.process(frame(0))
                report = self.sim.process(frame(1))  # second confirmation, 24 h + 1 s
                state = self.state()
                self.assertEqual(closes, "episode_closed" in report)
                self.assertEqual(not closes, "rebase" in report)
                self.assertEqual(D(100) if closes else D(cash), state.risk_high)
                self.assertEqual("", state.episode_since)

    def test_partial_recoveries_no_longer_ratchet_the_reference_down(self):
        # The strategy audit's ratchet (D7). Before D7 the first heal rebased risk_high to
        # 93.36, so the second dip below opened no episode at all and the final fall, 12.16%
        # below the original reference, was only a daily-loss pause, never the halt.
        self.heal()
        for index in (6 * DAY, 6 * DAY + 1):
            report = self.sim.process(frame(index, "0.02060"))
        self.assertIn("episode_closed", report)
        # A second dip past 8% opens a new episode, which heals and closes the same way.
        self.sim.process(frame(7 * DAY, "0.02015"))
        self.assertEqual(frame(7 * DAY).quote.observed_at, self.state().episode_since)
        self.sim.process(frame(7 * DAY + 2, "0.02060"))
        for index in (8 * DAY, 8 * DAY + 1):
            report = self.sim.process(frame(index, "0.02060"))
        self.assertIn("episode_closed", report)
        self.assertEqual(D(100), self.state().risk_high)
        report = self.sim.process(frame(9 * DAY, "0.01905"))
        state = self.state()
        self.assertEqual(
            ("halt", "drawdown", D(100)), (report["decision"], state.halt_category, state.risk_high)
        )
        self.assertEqual("hard drawdown reached: 12.16%", report["reason"])

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

    def test_no_restart_on_an_ineligible_frame(self):
        self.halt()
        report = self.sim.process(frame(DAY + 2, "0.01000", eligible=False))
        self.assertNotIn("restart", report)
        self.assertEqual("drawdown", self.state().halt_category)
        self.assertIn("restart", self.sim.process(frame(DAY + 3, "0.01000")))

    def test_a_restart_with_only_dust_held_keeps_it_held_and_marked(self):
        self.dust_halt()
        report = self.sim.process(frame(DAY + 2, "0.01000"))
        self.assertIn("restart", report)
        state = self.state()
        self.assertEqual(D(486), state.inventory)  # not written off
        # The rebased reference is the active equity with the residue marked to the bid.
        marked = state.equity(frame(DAY + 2, "0.01000").quote, self.sim.rules)
        self.assertGreater(marked, state.cash - state.pending)
        self.assertEqual((marked, marked), (state.last_equity, state.risk_high))
        self.assertEqual(str(marked), report["restart"]["new_reference"])

    def test_no_restart_while_the_daily_loss_is_3_percent_or_more(self):
        self.dust_halt()
        # Day 1 starts from the halt's equity, with the residue marked at 0.01.
        self.sim.process(frame(DAY + 1, "0.01000"))
        # 24 hours after the halt the residue's bid has halved: a loss of about 2.4 on a
        # 55.6 day start, over 3% (the ask keeps the quoted spread under 0.15%).
        report = self.sim.process(frame(DAY + 2, "0.00500", ask="0.005005"))
        state = self.state()
        self.assertNotIn("restart", report)
        self.assertEqual(("halt", "drawdown"), (report["decision"], state.halt_category))
        self.assertGreaterEqual((state.day_start - state.last_equity) / state.day_start, D("0.03"))
        # The next UTC day starts from the lower equity, so the loss is under 3% again.
        self.assertIn("restart", self.sim.process(frame(2 * DAY + 2, "0.00500", ask="0.005005")))

    def test_emergency_and_exhaustion_halts_never_restart(self):
        self.sim.process(frame(0))
        self.sim.process(emergency(frame(1)))
        self.assertEqual("emergency", self.state().halt_category)
        for index in (DAY + 1, DAY + 2, 2 * DAY):  # the flag has cleared; all limits pass
            self.assertNotIn("restart", self.sim.process(frame(index)))
        self.assertEqual("emergency", self.state().halt_category)

        self.fresh("exhaustion.db")
        self.exhaustion()
        for index in (DAY + 1, DAY + 2, 2 * DAY):
            self.assertNotIn("restart", self.sim.process(frame(index)))
        self.assertEqual("exhaustion", self.state().halt_category)

    def test_a_halt_keeps_its_identity_through_later_exit_frames(self):
        first = self.halt()
        for index in range(3, 8):  # five more frames past 12%: each is an EXIT
            self.assertEqual("halt", self.sim.process(frame(index, "0.01000"))["decision"])
        state = self.state()
        self.assertEqual(
            (first.halt, first.halt_since, "drawdown"),
            (state.halt, state.halt_since, state.halt_category),
        )
        # An emergency halt on an account past 12% stays an emergency halt next frame.
        self.fresh("emergency.db")
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(emergency(frame(2, "0.01000")))
        self.sim.process(frame(3, "0.01000"))  # no flag, 44% down: the drawdown EXIT
        state = self.state()
        self.assertEqual(
            ("emergency", frame(2).quote.observed_at), (state.halt_category, state.halt_since)
        )

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

    def test_a_manual_resume_is_refused_while_the_emergency_flag_is_set(self):
        self.sim.process(frame(0))
        self.sim.process(emergency(frame(1)))
        before = encode(self.state().to_dict())
        # The flag makes the regime STRESS, so the eligibility check refuses first; the
        # risk check (EXIT on the flag) would refuse it too.
        with self.assertRaises(ValueError):
            self.sim.resume(emergency(frame(2)), event_id="flag-set", reason="test")
        self.assertEqual(before, encode(self.state().to_dict()))
        result = self.sim.resume(frame(3), event_id="flag-cleared", reason="test")
        self.assertEqual("resume_pending", result["decision"])

    # -- D17 and D18: the manual resume (owner decisions 2026-10-05) -------------------

    def test_a_manual_resume_of_an_exhaustion_halt_is_refused_by_name(self):
        # D18. The risk check allows here, so before it the halt was admitted, and the
        # next frame's harvest halted the account again: final in effect, never refused.
        self.exhaustion()
        before = encode(self.state().to_dict())
        with self.assertRaisesRegex(ValueError, "'active capital exhausted' halt is final"):
            self.sim.resume(frame(DAY), event_id="exhausted", reason="test")
        self.assertEqual(before, encode(self.state().to_dict()))

    def test_an_exhaustion_halt_is_refused_before_any_risk_check_and_stays_final(self):
        # On the halt's own day the risk check would refuse for the daily loss; the
        # refusal still names the exhaustion, and the account never trades again.
        self.exhaustion()
        with self.assertRaisesRegex(ValueError, "exhausted' halt is final"):
            self.sim.resume(frame(1), event_id="same-day", reason="test")
        self.assertEqual("halt", self.sim.process(frame(DAY + 1))["decision"])
        self.assertEqual("exhaustion", self.state().halt_category)

    def test_a_resume_refused_only_by_the_drawdown_rebases_as_the_restart_does(self):
        # D17. Before it, this halt, 8.28% below the reference, was refused for good.
        halted = self.integrity_halt("0.02015")
        before = halted.to_dict()
        result = self.sim.resume(frame(6 * DAY, "0.02015"), event_id="fixed", reason="test")
        state = self.state()
        self.assertEqual(
            {
                "halt_since": halted.halt_since,
                "category": "integrity",
                "halt": halted.halt,
                "old_reference": "100",
                "new_reference": str(state.last_equity),
            },
            result["restart"],
        )
        self.assertEqual(("", state.last_equity), (state.halt, state.risk_high))
        # Only the restart's fields change, beyond the day roll and the mark; C1 still
        # measures from the original peak.
        after = state.to_dict()
        changed = {key for key in before if before[key] != after.get(key)}
        self.assertLessEqual(changed, RESTART_FIELDS | STEP_FIELDS, changed)
        for key in ("measure_high", "reserve_high", "pending", "secured", "cash", "inventory"):
            self.assertEqual(before[key], after[key], key)
        # Journaled: after a process restart the same command replays its recorded result.
        self.restart_process()
        self.assertEqual(
            result, self.sim.resume(frame(6 * DAY, "0.02015"), event_id="fixed", reason="test")
        )
        # The normal confirmations apply before the account trades again.
        self.assertEqual(
            "pause", self.sim.process(at_fair_value(6 * DAY + 1, "0.02015"))["decision"]
        )
        self.assertEqual(
            "open_grid", self.sim.process(at_fair_value(6 * DAY + 2, "0.02015"))["decision"]
        )

    def test_a_resume_refused_only_by_the_drawdown_rebases_at_any_depth(self):
        halted = self.integrity_halt("0.01800")  # 15.90% below: past the 12% hard limit
        self.assertLess(halted.last_equity, D(88))
        result = self.sim.resume(frame(6 * DAY, "0.01800"), event_id="deep", reason="test")
        state = self.state()
        self.assertEqual(
            ("100", str(state.last_equity)),
            (result["restart"]["old_reference"], result["restart"]["new_reference"]),
        )
        self.assertEqual((state.last_equity, D(100)), (state.risk_high, state.measure_high))

    def test_an_emergency_halt_resumes_with_a_rebase_once_the_flag_clears_past_12_percent(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        self.sim.process(emergency(frame(2, "0.01000")))  # 44% down, liquidated at once
        before = encode(self.state().to_dict())
        with self.assertRaises(ValueError):
            self.sim.resume(emergency(frame(DAY + 1, "0.01000")), event_id="set", reason="test")
        self.assertEqual(before, encode(self.state().to_dict()))
        result = self.sim.resume(frame(DAY + 1, "0.01000"), event_id="cleared", reason="test")
        state = self.state()
        self.assertEqual(
            {
                "halt_since": frame(2).quote.observed_at,
                "category": "emergency",
                "halt": "emergency flag is active",
                "old_reference": "100",
                "new_reference": str(state.last_equity),
            },
            result["restart"],
        )
        self.assertEqual((state.last_equity, D(100)), (state.risk_high, state.measure_high))

    def test_no_rebased_resume_while_the_daily_loss_is_3_percent_or_more(self):
        halted = self.integrity_halt("0.01980")
        self.assertGreaterEqual(
            (halted.day_start - halted.last_equity) / halted.day_start, D("0.03")
        )
        before = encode(halted.to_dict())
        with self.assertRaisesRegex(ValueError, "risk limits"):
            self.sim.resume(frame(5 * DAY + 4, "0.01980"), event_id="same-day", reason="test")
        self.assertEqual(before, encode(self.state().to_dict()))
        # The next UTC day starts from the halt's equity, so the loss is under 3% again.
        result = self.sim.resume(frame(6 * DAY, "0.01980"), event_id="next-day", reason="test")
        self.assertEqual(str(self.state().risk_high), result["restart"]["new_reference"])

    def test_a_resume_the_risk_check_allows_is_unchanged_and_rebases_nothing(self):
        halted = self.integrity_halt("0.02060")  # 6.67% below the reference
        result = self.sim.resume(frame(5 * DAY + 4, "0.02060"), event_id="fixed", reason="test")
        self.assertEqual(
            {
                "decision": "resume_pending",
                "previous_halt": halted.halt,
                "operator_reason": "test",
                "fills": [],
                "opened": [],
            },
            result,
        )
        state = self.state()
        self.assertEqual(("", D(100), D(100)), (state.halt, state.risk_high, state.measure_high))

    def test_a_manual_resume_of_a_drawdown_halt_is_unchanged_and_cannot_bypass_the_restart(self):
        # Amendment 1: only the automatic restart clears this halt, after 24 hours. Both
        # tries fall on a later UTC day, where the restart's tentative check would pass.
        self.halt()
        for index in (DAY + 1, 2 * DAY):  # before the 24 hours, then after them
            before = encode(self.state().to_dict())
            with self.assertRaisesRegex(ValueError, "frozen.*restarts automatically"):
                self.sim.resume(frame(index, "0.01000"), event_id=f"try/{index}", reason="test")
            self.assertEqual(before, encode(self.state().to_dict()))
        self.assertIn("restart", self.sim.process(frame(2 * DAY + 1, "0.01000")))

    # -- episode across a halt -------------------------------------------------------

    def test_a_drawdown_halt_closes_the_episode_and_only_a_new_one_can_rebase(self):
        self.decline()  # an episode since day 5, 00:00:00, at 91.76 against 100
        self.sim.process(frame(5 * DAY + 2, "0.01000"))  # 44% down: a drawdown halt
        state = self.state()
        self.assertEqual("drawdown", state.halt_category)
        self.assertEqual(("", 0), (state.episode_since, state.episode_count))
        self.assertIn("restart", self.sim.process(frame(6 * DAY + 2, "0.01000")))
        # The old episode's 24 hours are long past and the frames confirm: no rebase,
        # because no episode is open after the restart.
        for index in (6 * DAY + 3, 6 * DAY + 4):
            report = self.sim.process(at_fair_value(index, "0.01000"))
            self.assertNotIn("rebase", report)
        self.assertEqual("open_grid", report["decision"])
        restarted = self.state().risk_high
        # A grid around 0.01 fills, then a fall over five days (none loses 3%) reaches
        # the soft drawdown on day 10: a new episode with its own cool-off.
        self.sim.process(at_fair_value(6 * DAY + 5, "0.00950"))
        for day, bid in ((7, "0.00930"), (8, "0.00900"), (9, "0.00870")):
            self.assertNotIn("rebase", self.sim.process(at_fair_value(day * DAY, bid)))
            self.assertEqual("", self.state().episode_since)
        self.sim.process(at_fair_value(10 * DAY, "0.00840"))
        self.assertEqual(frame(10 * DAY).quote.observed_at, self.state().episode_since)
        for index in (11 * DAY - 2, 11 * DAY - 1):  # two confirmations, before 24 hours
            self.assertNotIn("rebase", self.sim.process(at_fair_value(index, "0.00840")))
        self.assertEqual(restarted, self.state().risk_high)
        report = self.sim.process(at_fair_value(11 * DAY, "0.00840"))
        self.assertEqual(frame(10 * DAY).quote.observed_at, report["rebase"]["episode_since"])

    def test_a_manual_resume_leaves_no_episode_to_rebase(self):
        self.decline()
        # A partial recovery to 6.6% below the reference: the episode stays open.
        self.sim.process(frame(5 * DAY + 2, "0.02060"))
        self.assertTrue(self.state().episode_since)
        crossed = frame(5 * DAY + 3, "0.02060")
        self.sim.process(replace(crossed, quote=replace(crossed.quote, ask=D("0.01960"))))
        self.assertEqual(
            ("integrity", ""), (self.state().halt_category, self.state().episode_since)
        )
        self.sim.process(frame(5 * DAY + 4, "0.02060"))  # the armed liquidation
        result = self.sim.resume(frame(5 * DAY + 5, "0.02060"), event_id="fixed", reason="test")
        self.assertEqual("resume_pending", result["decision"])
        # Past the old episode's 24 hours, with confirmations: nothing to rebase.
        for index in (6 * DAY, 6 * DAY + 1, 6 * DAY + 2):
            self.assertNotIn("rebase", self.sim.process(frame(index, "0.02060")))
        self.assertEqual(("", D(100)), (self.state().episode_since, self.state().risk_high))

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


class MeasurementPeakTests(TestCase):
    """C1(a): the replay's peak of total equity (reserves included), which no rebase,
    restart or settlement touches: replay only ever raises it with ``max``."""

    def test_the_c1a_peak_is_never_rebased_or_restarted(self):
        engine = engine_for(hourly(WARMUP + 30))  # features cover the whole 28-hour run
        start = START_MS + WARMUP * HOUR_MS
        price = float(engine.at(start).fair_value)
        minutes = []
        for i in range(1700):
            if 30 <= i < 200:  # 0.3% a minute: past 12%, a drawdown halt
                price *= 0.997
            minutes.append(candle(start + i * 60_000, price, price * 1.001, price * 0.999, price))
        run = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))
        metrics, account = replay(load_config(ROOT / "config/default.toml"), run, minutes, engine)
        self.assertEqual([], check_accounting(run, metrics, account))
        # The flat day after the crash lets the halt restart and rebase the breaker.
        self.assertEqual((1, 1), (metrics.hard_drawdown_halts, metrics.restarts))
        self.assertLess(account.risk_high, D(88))
        # C1(a) still measures from the pre-crash peak, and so does C1(b).
        self.assertEqual(D(100), metrics.peak_equity)
        self.assertGreaterEqual(metrics.max_drawdown, D("0.12"))
        self.assertEqual(
            (D(100), metrics.max_drawdown), (account.measure_high, metrics.active_max_drawdown)
        )
