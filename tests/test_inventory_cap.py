"""Variant B (experiment spec v1, section 3 B): the seven required cases and wiring.

Prices are constructed to hit each boundary; nothing here is backtest evidence.
"""

import json
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.demo import demo_frames
from crypto_grid_bot.simulation.execution import match, place
from crypto_grid_bot.simulation.inventory_cap import (
    capped_quantity,
    committed_exposure,
    fits,
    mark,
    prospective_active_equity,
)
from crypto_grid_bot.simulation.models import Account, D, LimitOrder, MarketRules, Quote
from crypto_grid_bot.simulation.runner import PaperSimulator, SimulationPolicy
from crypto_grid_bot.simulation.store import encode

ROOT = Path(__file__).resolve().parents[1]
CAP = D("0.4")
RULES = MarketRules(
    "TESTUSDT", D("0.01"), D("1"), D("5"), D("0.001"), D("0.0005"), D("0.1"), D("0.002")
)


def quote(bid="10", ask=None, size="1000"):
    return Quote(
        "q",
        "TESTUSDT",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
        D(bid),
        D(ask) if ask else D(bid) + D("0.01"),
        D(size),
        D(size),
    )


def buy(identity, price, quantity, target=None):
    return LimitOrder(identity, "buy", D(price), D(quantity), D(quantity), target)


def cap(account, current, price, quantity, rules=RULES):
    return capped_quantity(account, current, rules, CAP, D(price), D(quantity))


class ArithmeticTests(TestCase):
    def test_prospective_equity_and_exposure_include_fees_and_haircuts(self):
        account = Account.start(D("100"))
        account.pending, account.inventory = D("10"), D("2")
        place(account, buy("r", "9", "3"), RULES)
        current = quote("10")
        # Mark = 10 x 0.9995 x 0.998; haircut per unit notional = 1.001 - 0.9995 x 0.998.
        self.assertEqual(D("9.97501"), mark(current, RULES))
        self.assertEqual(D("109.95002"), account.equity(current, RULES))
        # Resting 9 x 3 = 27 plus a proposed 16, both at cost including the maker fee:
        # 2 x 9.97501 + 43 x 1.001, and 109.95002 - 43 x 0.003499.
        self.assertEqual(D("62.99302"), committed_exposure(account, current, RULES, D("16")))
        self.assertEqual(
            D("109.799563"), prospective_active_equity(account, current, RULES, D("16"))
        )
        # Without the proposed buy, only the resting one is charged.
        self.assertEqual(D("46.97702"), committed_exposure(account, current, RULES))
        self.assertEqual(D("109.855547"), prospective_active_equity(account, current, RULES))


class PlacementBoundaryTests(TestCase):
    def test_first_level_that_does_not_fit_is_resized_then_lower_levels_skipped(self):
        account = Account.start(D("100"))
        current = quote("10.5")
        place(account, buy("a", "10", "2"), RULES)
        # Room for 2.21 lots at 9: the requested 3 are floored to 2, notional 18 >= 5.
        self.assertEqual(D("2"), cap(account, current, "9", "3"))
        place(account, buy("b", "9", "2"), RULES)
        self.assertTrue(fits(account, current, RULES, CAP))
        # One more lot at 9 would breach the cap: the resize is the largest that fits.
        self.assertFalse(fits(account, current, RULES, CAP, D("9")))
        # Room left is under one lot at 8, so the next level is skipped.
        self.assertEqual(D("0"), cap(account, current, "8", "2"))

    def test_resized_level_below_minimum_notional_is_skipped(self):
        account = Account.start(D("100"))
        current = quote("11.5")
        place(account, buy("a", "11", "3"), RULES)
        # Room for 1.7 lots at 4: one lot is 4, below the minimum notional of 5.
        self.assertEqual(D("0"), cap(account, current, "4", "3"))
        # The same room with a lower minimum notional resizes instead of skipping.
        lower = replace(RULES, minimum_notional=D("1"))
        self.assertEqual(D("1"), cap(account, current, "4", "3", lower))

    def test_lot_flooring_below_one_lot_places_nothing(self):
        account = Account.start(D("100"))
        current = quote("10.5")
        place(account, buy("a", "10", "3"), RULES)
        # Room for 0.99 of a lot at 10 floors to zero lots.
        self.assertEqual(D("0"), cap(account, current, "10", "3"))


class ConcurrencyAndLifecycleTests(TestCase):
    def test_resting_buys_that_each_fit_alone_do_not_fit_together(self):
        current = quote("10.5")
        for identity in ("x", "y"):
            alone = Account.start(D("100"))
            self.assertEqual(D("3"), cap(alone, current, "10", "3"), identity)
        together = Account.start(D("100"))
        place(together, buy("x", "10", "3"), RULES)
        self.assertEqual(D("0"), cap(together, current, "10", "3"))

    def run_reentry(self, capped):
        account = Account.start(D("100"))
        account.cash, account.inventory = D("60"), D("4")
        place(account, LimitOrder("s", "sell", D("11"), D("2"), D("2"), reentry=D("10")), RULES)
        current = quote("11.1")
        seen = []

        def check(order_id, price, quantity):
            seen.append((order_id, price, quantity))
            return capped_quantity(account, current, RULES, CAP, price, quantity)

        fills = match(account, current, RULES, reentry_quantity=check if capped else None)
        self.assertEqual(["sell"], [fill.side for fill in fills])
        (reentry,) = (order for order in account.orders.values() if order.side == "buy")
        return account, reentry, seen

    def test_reentry_is_resized_when_it_is_created_at_the_cap(self):
        _, uncapped, _ = self.run_reentry(False)
        self.assertEqual(D("2"), uncapped.quantity)
        account, reentry, seen = self.run_reentry(True)
        # The check runs after the sell filled, at the sold level and quantity.
        self.assertEqual([("q/reentry/1", D("10"), D("2"))], seen)
        self.assertEqual(
            (D("1"), D("1"), D("11")), (reentry.quantity, reentry.remaining, reentry.target)
        )
        self.assertTrue(fits(account, quote("11.1"), RULES, CAP))

    def test_partial_fill_remainder_still_counts_before_a_new_buy(self):
        account = Account.start(D("100"))
        place(account, buy("p", "10", "2"), RULES)
        fills = match(account, quote("9.89", ask="9.9", size="10"), RULES)
        self.assertEqual([D("1")], [fill.quantity for fill in fills])
        self.assertEqual(D("1"), account.orders["p"].remaining)
        current = quote("9.89", ask="9.9")
        # The filled lot is inventory at the mark; the unfilled lot is still a commitment.
        self.assertEqual(
            mark(current, RULES) + D("10") * D("1.001"),
            committed_exposure(account, current, RULES),
        )
        self.assertEqual(D("2"), cap(account, current, "9.5", "10"))
        self.assertFalse(fits(account, current, RULES, CAP, D("9.5") * 3))
        # Only because the remainder counts: without it, a third lot would fit.
        del account.orders["p"]
        self.assertEqual(D("3"), cap(account, current, "9.5", "10"))

    def test_price_driven_breach_sells_nothing_blocks_buys_then_resumes(self):
        account = Account.start(D("100"))
        account.cash, account.inventory = D("70"), D("3")
        before = encode(account.to_dict())
        self.assertEqual(D("1"), cap(account, quote("10"), "9", "1"))
        # A rally lifts inventory at the mark above 40% of prospective active equity.
        self.assertFalse(fits(account, quote("20"), RULES, CAP))
        self.assertEqual(D("0"), cap(account, quote("20"), "9", "1"))
        # No forced sale and no order: the check has no side effects.
        self.assertEqual(before, encode(account.to_dict()))
        self.assertEqual(D("1"), cap(account, quote("10"), "9", "1"))


class SimulatorWiringTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = load_config(ROOT / "config/default.toml")

    def open(self, name, policy=None):
        simulator = PaperSimulator(
            Path(self.temp.name) / name, self.config, MarketRules(), policy=policy
        )
        self.addCleanup(simulator.close)
        return simulator

    def test_policy_rejects_caps_outside_zero_to_one(self):
        for value in (D("0"), D("1"), D("1.5"), D("-0.1")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                SimulationPolicy(inventory_cap=value)
        self.assertEqual(CAP, SimulationPolicy(inventory_cap=CAP).inventory_cap)

    def test_off_by_default_and_absent_from_existing_identities(self):
        simulator = self.open("v0.db")
        row = simulator.store.connection.execute("SELECT identity FROM state").fetchone()[0]
        self.assertNotIn("inventory_cap", json.loads(row)["policy"])
        report = simulator.process(demo_frames(1)[0])
        self.assertNotIn("capped", report)

    def test_cap_is_part_of_the_account_identity(self):
        self.open("b.db", SimulationPolicy(inventory_cap=CAP)).close()
        with self.assertRaisesRegex(ValueError, "settings differ"):
            self.open("b.db")
        reopened = self.open("b.db", SimulationPolicy(inventory_cap=CAP))
        row = reopened.store.connection.execute("SELECT identity FROM state").fetchone()[0]
        self.assertEqual("0.4", json.loads(row)["policy"]["inventory_cap"])

    def test_new_grid_places_highest_levels_first_and_records_the_rest(self):
        frame = demo_frames(1)[0]
        v0 = self.open("v0.db").process(frame)
        simulator = self.open("b.db", SimulationPolicy(inventory_cap=CAP))
        report = simulator.process(frame)
        account = simulator.store.read()
        self.assertEqual("open_grid", report["decision"])
        placed = sorted(account.orders.values(), key=lambda order: order.price, reverse=True)
        self.assertLess(len(placed), len(v0["opened"]))
        # V0's order IDs end in the level index, lowest price first.
        by_level = sorted(v0["opened"], key=lambda order_id: int(order_id.rsplit("/", 1)[1]))
        self.assertEqual(by_level[::-1][: len(placed)], [order.order_id for order in placed])
        # Every level V0 would have placed is either placed whole or recorded.
        recorded = {entry["order_id"]: entry for entry in report["capped"]}
        self.assertEqual(set(by_level), {order.order_id for order in placed} | set(recorded))
        below = by_level[::-1][len(placed) :]
        self.assertTrue(all(recorded[order_id]["action"] == "skipped" for order_id in below))
        self.assertTrue(fits(account, frame.quote, simulator.rules, CAP))
