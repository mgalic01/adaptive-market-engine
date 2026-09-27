"""A soft drawdown shrinks new buys to the risk engine's multiplier; it never locks.

Before this change a soft drawdown paused the account, and a pause only cleared on a
fully passing risk check, which a flat account below its high-water mark can never
reach: replays of V0 sat in cash for 102-235 days after one. Prices are constructed.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import place
from crypto_grid_bot.simulation.models import D, LimitOrder, MarketRules
from crypto_grid_bot.simulation.runner import PaperSimulator

ROOT = Path(__file__).resolve().parents[1]
START = datetime(2026, 1, 1, tzinfo=UTC)


def frame(index, bid="0.02300"):
    template = demo_frames(1)[0]
    when = START + timedelta(seconds=index)
    return replace(
        template,
        quote=replace(
            template.quote,
            event_id=f"soft/{index}",
            observed_at=when.isoformat(),
            received_at=when.isoformat(),
            bid=D(bid),
            ask=D(bid) + D("0.00001"),
        ),
        signals=replace(template.signals, observed_at=when),
        allow_new_grid=True,
    )


class SoftDrawdownTests(TestCase):
    def setUp(self):
        self.sim = PaperSimulator(
            Path(":memory:"), load_config(ROOT / "config/default.toml"), MarketRules()
        )
        self.addCleanup(self.sim.close)

    def account(self, drawdown):
        """A fresh flat account whose high-water mark sits ``drawdown`` above it."""
        account = self.sim.store.read()
        account.risk_high = account.cash / (1 - D(drawdown))
        account.day, account.day_start = START.date().isoformat(), account.cash
        return account

    @staticmethod
    def committed(account):
        return sum(o.price * o.quantity for o in account.orders.values() if o.side == "buy")

    def test_flat_account_past_soft_drawdown_trades_at_a_quarter_size(self):
        normal, reduced = self.account("0"), self.account("0.09")
        self.assertEqual("open_grid", self.sim.step(normal, frame(0))["decision"])
        report = self.sim.step(reduced, frame(0))
        self.assertEqual("open_grid", report["decision"])
        self.assertEqual("", reduced.pause)
        self.assertEqual(D("0.25"), report["capital_multiplier"])
        ratio = self.committed(reduced) / self.committed(normal)
        # Lot flooring per level can only shave the quarter, never exceed it.
        self.assertLessEqual(ratio, D("0.25"))
        self.assertGreater(ratio, D("0.24"))

    def test_below_soft_drawdown_nothing_changes(self):
        report = self.sim.step(self.account("0.07"), frame(0))
        self.assertEqual("open_grid", report["decision"])
        self.assertNotIn("capital_multiplier", report)

    def test_an_existing_pause_recovers_while_the_soft_drawdown_persists(self):
        # The state every locked-out replay was in: flat, paused, drawdown above 8%.
        account = self.account("0.09")
        account.pause, account.draining = "soft drawdown reached: 9.00%", True
        first = self.sim.step(account, frame(0))
        self.assertEqual("pause", first["decision"])
        second = self.sim.step(account, frame(1))
        self.assertEqual("", account.pause)
        self.assertEqual("open_grid", second["decision"])
        self.assertEqual(D("0.25"), second["capital_multiplier"])

    def test_reentry_after_a_sell_is_a_quarter_of_the_sold_quantity(self):
        account = self.account("0")
        account.cash -= D("23")
        account.inventory = D("1000")
        account.risk_high = account.equity(frame(0, "0.02320").quote, MarketRules()) / D("0.91")
        account.day_start = account.risk_high * D("0.91")
        place(
            account,
            LimitOrder("s", "sell", D("0.02310"), D("1000"), D("1000"), reentry=D("0.02250")),
            MarketRules(),
        )
        report = self.sim.step(account, frame(0, "0.02320"))
        self.assertEqual(["sell"], [fill["side"] for fill in report["fills"]])
        (reentry,) = (o for o in account.orders.values() if o.side == "buy")
        self.assertEqual((D("250"), D("0.02310")), (reentry.quantity, reentry.target))

    def test_daily_loss_still_pauses_and_hard_drawdown_still_halts(self):
        daily = self.account("0")
        daily.day_start = daily.cash / D("0.96")
        daily.risk_high = daily.day_start
        self.assertEqual("pause", self.sim.step(daily, frame(0))["decision"])
        hard = self.account("0.13")
        self.assertEqual("halt", self.sim.step(hard, frame(0))["decision"])
        self.assertTrue(hard.halt.startswith("hard drawdown"))
