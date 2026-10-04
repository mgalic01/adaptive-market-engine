"""Spec v1 amendments 2 and 3 (owner decisions D15 and D16, 2026-10-02).

Amendment 2: a flat account with no orders and no range exit pending clears its grid
bounds and outside-range clock at once. Amendment 3: the outside-range clock stands still
while the account is halted. Prices are constructed, not backtest evidence; the fixtures
step one second per frame, with a 10-second outside-range window.
"""

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from test_strategy_recovery import at_fair_value, frame

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import D, MarketRules
from crypto_grid_bot.simulation.runner import RESTART_PAUSE, PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode

ROOT = Path(__file__).resolve().parents[1]
DAY = 86400
BAND = (D("0.022"), D("0.024"))  # the bounds of the grid frame(0) opens


def tight(index, bid):
    """A frame whose ATR is too small for any grid to cover its costs."""
    return replace(frame(index, bid), atr=D("0.00001"))


def crossed(index, bid):
    """An invalid frame (bid above ask): an ``integrity`` halt."""
    current = frame(index, bid)
    return replace(current, quote=replace(current.quote, ask=D(bid) - D("0.00100")))


class FlatBoundsAndHaltClockTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "paper.db"
        self.config = replace(load_config(ROOT / "config/default.toml"), minimum_transfer_quote=0.1)
        self.policy = SimulationPolicy(
            outside_range_seconds=10, maximum_frame_gap_seconds=30, recenter_cooldown_seconds=20
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

    def put(self, account):
        """Overwrite the saved account (autocommit connection) for a constructed state."""
        self.sim.store.connection.execute(
            "UPDATE state SET data=? WHERE id=1", (encode(account.to_dict()),)
        )

    def sell_out_with_no_new_grid(self):
        """A grid fills, then sells out above its band on a frame too tight for the next
        grid: the account is flat with no orders and no range exit pending."""
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))
        report = self.sim.process(tight(2, "0.02500"))
        state = self.state()
        self.assertEqual(("cash", D(0), {}), (report["decision"], state.inventory, state.orders))
        self.assertFalse(state.range_exit)
        return report

    # -- amendment 2 -------------------------------------------------------------------

    def test_a_flat_account_with_no_exit_pending_clears_its_bounds_and_regrids_at_once(self):
        report = self.sell_out_with_no_new_grid()
        state = self.state()
        self.assertEqual({"lower": "0.022", "upper": "0.02400"}, report["bounds_cleared"])
        self.assertEqual((D(0), D(0)), (state.grid_lower, state.grid_upper))
        self.assertEqual((D(0), ""), (state.outside_seconds, state.outside_last))
        # Far longer than the 10-second window above the old band: before amendment 2 the
        # empty account timed out into a range exit here and then waited for its cooldown.
        for index in range(3, 20):
            report = self.sim.process(tight(index, "0.02500"))
            self.assertEqual(("cash", False), (report["decision"], report["range_exit"]))
        # The first frame on which a grid is viable opens one, around the current price.
        report = self.sim.process(at_fair_value(20, "0.02500"))
        self.assertEqual("open_grid", report["decision"])
        state = self.state()
        self.assertTrue(state.grid_lower <= D("0.02500") <= state.grid_upper)

    def test_a_genuine_range_exit_keeps_its_bounds_and_full_cooldown(self):
        self.sim.process(frame(0))
        self.sim.process(frame(1, "0.02196"))  # the buys fill; below the band from here
        for index in range(2, 12):
            report = self.sim.process(frame(index, "0.02196"))
        state = self.state()
        self.assertTrue(report["range_exit"])  # 10 s outside: inventory forced out
        self.assertEqual((D(0), {}), (state.inventory, state.orders))
        self.assertEqual(BAND, (state.grid_lower, state.grid_upper))
        # Flat with no orders, but an exit is pending: its bounds and the 20-second
        # recentre cooldown stay, across a process restart too.
        for index in range(12, 31):
            if index == 20:
                self.restart_process()
            report = self.sim.process(at_fair_value(index, "0.02196"))
            self.assertNotIn("bounds_cleared", report)
            self.assertEqual(("pause", []), (report["decision"], report["opened"]))
            self.assertEqual(BAND, (self.state().grid_lower, self.state().grid_upper))
        report = self.sim.process(at_fair_value(31, "0.02196"))
        self.assertEqual("recenter", report["range_exit_cleared"])
        self.assertFalse(self.sim.process(at_fair_value(32, "0.02196"))["opened"])
        self.assertTrue(self.sim.process(at_fair_value(33, "0.02196"))["opened"])

    def test_a_process_restart_keeps_the_cleared_state(self):
        cleared = self.sell_out_with_no_new_grid()
        self.restart_process()
        state = self.state()
        self.assertEqual(
            (D(0), D(0), D(0), ""),
            (state.grid_lower, state.grid_upper, state.outside_seconds, state.outside_last),
        )
        # The clearing frame is journaled: it replays its recorded result, unchanged.
        before = encode(state.to_dict())
        self.assertEqual(cleared, self.sim.process(tight(2, "0.02500")))
        self.assertEqual(before, encode(self.state().to_dict()))
        for index in range(3, 20):
            if index == 10:
                self.restart_process()
            self.assertFalse(self.sim.process(tight(index, "0.02500"))["range_exit"])
        self.assertEqual("open_grid", self.sim.process(at_fair_value(20, "0.02500"))["decision"])

    # -- amendment 3 -------------------------------------------------------------------

    def test_the_clock_stands_still_while_halted_and_never_counts_the_halt(self):
        self.sim.process(frame(0))
        for index in range(1, 6):  # the buys fill; 4 s observed below the band
            self.sim.process(frame(index, "0.02196"))
        self.assertEqual(D(4), self.state().outside_seconds)
        self.sim.process(crossed(6, "0.02196"))  # an integrity halt, with the exit armed
        # A book too thin to sell into: the halted account keeps its inventory, and so its
        # grid's bounds, for far longer than the 10-second window. Before amendment 3 the
        # clock ran on and exited the halted account to cash at 00:00:11.
        for index in range(7, 21):
            report = self.sim.process(frame(index, "0.02196", size="0"))
            state = self.state()
            self.assertEqual(("halt", False), (report["decision"], state.range_exit))
            self.assertEqual(D(3566), state.inventory)
            self.assertEqual(
                (D(4), frame(5).quote.observed_at), (state.outside_seconds, state.outside_last)
            )
        # No engine path ends a halt with this clock intact: a restart or resume needs a
        # flat account, whose clock amendment 2 and the restart's field list clear. Ending
        # the halt in the saved state shows the clock resumes from its frozen 4 s, and that
        # the 15 halted seconds are not counted: the first frame after the halt only
        # restarts the interval.
        account = self.state()
        account.halt = account.halt_since = account.halt_category = ""
        account.liquidating = False
        self.put(account)
        self.sim.process(frame(21, "0.02196", size="0"))
        self.assertEqual(D(4), self.state().outside_seconds)
        for index in range(22, 27):
            self.sim.process(frame(index, "0.02196", size="0"))
        self.assertEqual((D(9), False), (self.state().outside_seconds, self.state().range_exit))
        self.assertTrue(self.sim.process(frame(27, "0.02196", size="0"))["range_exit"])

    def test_a_range_exit_triggered_before_a_halt_completes_through_it(self):
        self.sim.process(frame(0))
        for index in range(1, 11):
            self.sim.process(frame(index, "0.02196"))
        # 10 s outside on a thin book: the exit starts and sells only 1000 units.
        report = self.sim.process(frame(11, "0.02196", size="10000"))
        self.assertTrue(report["range_exit"])
        self.assertEqual(D(2566), self.state().inventory)
        # A crash halts the account; the halt's liquidation sells the rest.
        report = self.sim.process(frame(12, "0.01000"))
        state = self.state()
        self.assertEqual(
            ("halt", "drawdown", D(0)), (report["decision"], state.halt_category, state.inventory)
        )
        exits = [report["range_exit"]]
        for index in range(13, 40):
            report = self.sim.process(frame(index, "0.01000"))
            exits.append(report["range_exit"])
            self.assertNotIn("bounds_cleared", report)  # the exit is still pending
        self.assertEqual(BAND, (self.state().grid_lower, self.state().grid_upper))
        self.assertTrue(all(exits))  # one exit, held through the halt and never re-counted
        # The restart ends the exit with the halt, exactly as amendment 1 lists.
        report = self.sim.process(frame(DAY + 12, "0.01000"))
        state = self.state()
        self.assertIn("restart", report)
        self.assertEqual(
            (False, "", D(0), D(0), RESTART_PAUSE),
            (
                state.range_exit,
                state.range_exit_since,
                state.grid_lower,
                state.grid_upper,
                state.pause,
            ),
        )
