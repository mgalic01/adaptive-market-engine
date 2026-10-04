from dataclasses import replace
from unittest import TestCase

from crypto_grid_bot.simulation.execution import (
    exit_price,
    exitable,
    liquidate,
    match,
    place,
    reduce_unreserved,
)
from crypto_grid_bot.simulation.inventory_cap import mark
from crypto_grid_bot.simulation.models import Account, D, LimitOrder, MarketRules, Quote


def quote(bid="9.8", ask="9.9", size="100"):
    return Quote(
        "q",
        "TESTUSDT",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
        D(bid),
        D(ask),
        D(size),
        D(size),
    )


class ExecutionTests(TestCase):
    def setUp(self):
        self.rules = MarketRules(
            "TESTUSDT", D("0.01"), D("1"), D("5"), D("0.001"), D("0.0005"), D("0.1")
        )
        self.account = Account.start(D("100"))

    def order(self, identity="a", quantity="5", target=None):
        return LimitOrder(identity, "buy", D("10"), D(quantity), D(quantity), target)

    def test_reservations_include_fees_and_cannot_spend_savings(self):
        self.account.pending = D("50")
        with self.assertRaises(ValueError):
            place(self.account, self.order(), self.rules)
        self.assertEqual({}, self.account.orders)
        self.account.pending = D("20")
        place(self.account, self.order(), self.rules)
        self.assertEqual(D("29.950"), self.account.available_quote(self.rules))
        with self.assertRaises(ValueError):
            place(self.account, self.order("b"), self.rules)
        del self.account.orders["a"]  # how the engine cancels
        self.assertEqual(D("80"), self.account.available_quote(self.rules))

    def test_shared_liquidity_partial_fills_and_cancel(self):
        place(self.account, self.order(), self.rules)
        place(self.account, self.order("b", "4"), self.rules)
        fills = match(self.account, quote(size="30"), self.rules)
        self.assertEqual(1, len(fills))
        self.assertEqual(D("3"), fills[0].quantity)
        self.assertEqual(D("69.970"), self.account.cash)
        self.assertEqual(D("3"), self.account.inventory)
        self.assertEqual(D("2"), self.account.orders["a"].remaining)
        self.assertEqual(D("60.060"), self.account.reserved_quote(self.rules))
        del self.account.orders["a"]  # how the engine cancels
        self.assertEqual(D("40.040"), self.account.reserved_quote(self.rules))

    def test_child_sell_cannot_fill_until_later_event(self):
        place(self.account, self.order(target=D("11")), self.rules)
        fills = match(self.account, quote(), self.rules)
        self.assertEqual(["buy"], [fill.side for fill in fills])
        self.assertEqual(D("5"), self.account.reserved_base())
        fills = match(self.account, quote("11.2", "11.3"), self.rules)
        self.assertEqual(["sell"], [fill.side for fill in fills])
        self.assertEqual(D("104.895"), self.account.cash)
        self.assertEqual(D("0.105"), self.account.fees)
        self.assertEqual(0, self.account.inventory)

    def test_no_touch_fill_or_fill_outside_limit_after_slippage(self):
        place(self.account, self.order(), self.rules)
        for ask in ["10", "9.999", "10.1"]:
            self.assertEqual([], match(self.account, quote("9.9", ask), self.rules))
        self.assertEqual(D("100"), self.account.cash)

    def test_filters_and_overselling(self):
        orders = [
            LimitOrder("x", "buy", D("10.001"), D("1"), D("1")),
            LimitOrder("x", "buy", D("10"), D("0.5"), D("0.5")),
            LimitOrder("x", "buy", D("1"), D("1"), D("1")),
            LimitOrder("x", "sell", D("10"), D("1"), D("1")),
        ]
        for order in orders:
            with self.subTest(order=order), self.assertRaises(ValueError):
                place(self.account, order, self.rules)

    def test_zero_volume_and_invalid_market_data(self):
        place(self.account, self.order(), self.rules)
        self.assertEqual([], match(self.account, quote(size="0"), self.rules))
        for bad in [
            replace(quote(), bid=D("NaN")),
            quote("11", "10"),
            replace(quote(), symbol="WRONG"),
            quote(size="-1"),
        ]:
            with self.assertRaises(ValueError):
                match(self.account, bad, self.rules)
        self.assertEqual(D("100"), self.account.cash)

    def test_emergency_liquidation_respects_depth_and_reports_dust(self):
        self.account.inventory = D("10")
        result = liquidate(self.account, quote(size="20"), self.rules)
        self.assertEqual(D("2"), result.fills[0].quantity)
        self.assertEqual(D("9.79"), result.fills[0].price)
        self.assertEqual(("", D("8")), (result.blocked, self.account.inventory))
        # A bid that cannot support one minimum notional refuses and says which refusal.
        refused = liquidate(self.account, quote("0.01", "0.02"), self.rules)
        self.assertEqual(([], "dust"), (refused.fills, refused.blocked))
        self.assertEqual(D("8"), self.account.inventory)


class MakerTakerFeeTests(TestCase):
    """Resting fills pay the maker fee; marketable exits and liquidation marks pay taker."""

    def rules(self, maker="0", taker="0.0009"):
        return MarketRules(
            "TESTUSDT",
            D("0.01"),
            D("1"),
            D("5"),
            D(maker),
            D("0.0005"),
            D("0.1"),
            None if taker is None else D(taker),
        )

    def test_taker_defaults_to_maker_and_identity_is_unchanged(self):
        rules = self.rules("0.001", None)
        self.assertEqual(D("0.001"), rules.taker_fee)
        self.assertNotIn("taker_fee_rate", rules.identity())
        self.assertEqual(D("0.0009"), self.rules().identity()["taker_fee_rate"])

    def test_invalid_taker_fee_is_rejected(self):
        for value in ("-0.001", "0.1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.rules(taker=value)

    def test_resting_grid_fills_pay_maker_fee(self):
        rules, account = self.rules(), Account.start(D("100"))
        place(account, LimitOrder("a", "buy", D("10"), D("5"), D("5"), D("11")), rules)
        self.assertEqual(D("50"), account.reserved_quote(rules))  # zero maker fee reserved
        (buy,) = match(account, quote(), rules)
        self.assertEqual(D("0"), buy.fee)
        self.assertEqual(D("50"), account.cash)
        (sell,) = match(account, replace(quote("11.2", "11.3"), event_id="q2"), rules)
        self.assertEqual(("sell", D("0")), (sell.side, sell.fee))
        self.assertEqual(D("105"), account.cash)
        self.assertEqual(D("0"), account.fees)

    def test_exit_pays_taker_fee_and_equity_marks_at_taker(self):
        rules, account = self.rules(), Account.start(D("100"))
        account.inventory = D("5")
        mark = D("5") * D("9.8") * (1 - D("0.0005")) * (1 - D("0.0009"))
        self.assertEqual(D("100") + mark, account.equity(quote(), rules))
        (fill,) = reduce_unreserved(account, quote(), rules).fills
        self.assertEqual(D("9.79"), fill.price)
        self.assertEqual(D("9.79") * 5 * D("0.0009"), fill.fee)
        self.assertEqual(fill.fee, account.fees)


class FillTriggerTests(TestCase):
    """D9 (owner decision 2026-10-05): the missed-fill sweep's own resting-fill trigger.
    Unset, it is the slippage; exits and marks keep the slippage either way."""

    def rules(self, trigger=None):
        return MarketRules(
            "TESTUSDT",
            D("0.01"),
            D("1"),
            D("5"),
            D("0"),
            D("0.0005"),
            D("0.1"),
            D("0.0009"),
            None if trigger is None else D(trigger),
        )

    def test_unset_it_is_the_slippage_and_the_identity_omits_it(self):
        rules = self.rules()
        self.assertEqual(D("0.0005"), rules.fill_trigger)
        self.assertNotIn("fill_trigger_rate", rules.identity())
        self.assertEqual(D("0.0002"), self.rules("0.0002").identity()["fill_trigger_rate"])
        for value in ("-0.0001", "0.1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.rules(value)

    def test_it_alone_decides_whether_a_resting_order_fills(self):
        # A buy at 10 fills when ask x (1 + trigger) < 10; a sell at 11 when
        # bid x (1 - trigger) > 11. Each quote fills at one trigger and not the other.
        cases = (
            ("buy", None, ("9.9", "9.992"), True),  # 9.992 x 1.0005 < 10
            ("buy", "0.001", ("9.9", "9.992"), False),  # 9.992 x 1.001 > 10
            ("buy", None, ("9.9", "9.997"), False),  # 9.997 x 1.0005 > 10
            ("buy", "0.0002", ("9.9", "9.997"), True),  # 9.997 x 1.0002 < 10
            ("sell", None, ("11.008", "11.02"), True),  # 11.008 x 0.9995 > 11
            ("sell", "0.001", ("11.008", "11.02"), False),  # 11.008 x 0.999 < 11
        )
        for side, trigger, (bid, ask), fills in cases:
            with self.subTest(side=side, trigger=trigger, bid=bid, ask=ask):
                rules, account = self.rules(trigger), Account.start(D("100"))
                account.inventory = D("5")
                price = D("10") if side == "buy" else D("11")
                place(account, LimitOrder("o", side, price, D("5"), D("5")), rules)
                self.assertEqual(fills, bool(match(account, quote(bid, ask), rules)))

    def test_exits_and_marks_keep_the_slippage(self):
        default, swept = self.rules(), self.rules("0.002")
        self.assertEqual(exit_price(quote(), default), exit_price(quote(), swept))
        self.assertEqual(mark(quote(), default), mark(quote(), swept))
        fills = []
        for rules in (default, swept):
            account = Account.start(D("100"))
            account.inventory = D("5")
            self.assertEqual(
                Account.start(D("100")).cash + mark(quote(), rules) * 5,
                account.equity(quote(), rules),
            )
            (fill,) = reduce_unreserved(account, quote(), rules).fills
            fills.append((fill.price, fill.quantity, fill.fee, account.cash))
        self.assertEqual(fills[0], fills[1])


class PanelHardeningTests(TestCase):
    """Hardening from the 2026-09-28 panel review (PR #122 follow-up)."""

    def setUp(self):
        self.rules = MarketRules(
            "TESTUSDT", D("0.01"), D("1"), D("5"), D("0.001"), D("0.0005"), D("0.1")
        )
        self.account = Account.start(D("100"))

    def test_a_non_positive_maximum_is_refused(self):
        self.account.inventory = D("10")
        for maximum in (D("0"), D("-5")):
            with self.subTest(maximum=maximum), self.assertRaisesRegex(ValueError, "positive"):
                reduce_unreserved(self.account, quote(), self.rules, maximum=maximum)

    def test_resting_orders_cannot_claim_more_inventory_than_is_held(self):
        # A buy filled 6 of 10 says 6 units are held for its child sell. Fewer than 6 in
        # inventory would make unpaired_inventory negative and the exit classifier report
        # nothing owed.
        self.account.orders["b"] = LimitOrder("b", "buy", D("10"), D("10"), D("4"))
        self.account.inventory = D("3")
        with self.assertRaisesRegex(ValueError, "claim more inventory"):
            self.account.validate(self.rules)
        self.account.inventory = D("6")
        self.account.validate(self.rules)

    def test_exactly_the_minimum_notional_is_sellable_and_one_step_less_is_not(self):
        # exit price = floor(0.0501 * (1 - 0.0005), 0.01) = 0.05; 100 units are worth
        # exactly the 5.0 minimum notional.
        at_bid = quote("0.0501", "0.0502")
        self.account.inventory = D("100")
        self.assertEqual(D("100"), exitable(self.account, at_bid, self.rules))
        self.account.inventory = D("99")
        self.assertEqual(D("0"), exitable(self.account, at_bid, self.rules))


class SimcoreAuditTests(TestCase):
    """Fill remainders, refused reentries and the validation switch (2026-10 audit)."""

    def setUp(self):
        self.rules = MarketRules(
            "TESTUSDT", D("0.01"), D("1"), D("5"), D("0.001"), D("0.0005"), D("0.1")
        )
        self.account = Account.start(D("100"))

    def test_a_fill_reports_what_is_still_resting(self):
        place(self.account, LimitOrder("a", "buy", D("10"), D("5"), D("5")), self.rules)
        (partial,) = match(self.account, quote(size="30"), self.rules)
        self.assertEqual((D("3"), D("2")), (partial.quantity, partial.remaining))
        (rest,) = match(self.account, replace(quote(), event_id="q2"), self.rules)
        self.assertEqual((D("2"), D("0")), (rest.quantity, rest.remaining))

    def sell_with_reentry(self):
        self.account.inventory = D("5")
        place(
            self.account,
            LimitOrder("s", "sell", D("11"), D("5"), D("5"), reentry=D("4")),
            self.rules,
        )

    def test_a_refused_reentry_is_recorded_with_its_reason(self):
        for quantity, reason in [
            (D("1"), "order is below minimum notional"),  # 4 x 1 < 5
            (D("100"), "insufficient unprotected quote balance including fees"),
        ]:
            with self.subTest(reason=reason):
                self.setUp()
                self.sell_with_reentry()
                refused = []
                (fill,) = match(
                    self.account,
                    quote("11.2", "11.3"),
                    self.rules,
                    reentry_quantity=lambda order_id, price, requested, q=quantity: q,
                    refused=refused,
                )
                self.assertEqual("sell", fill.side)
                self.assertEqual({}, self.account.orders)  # the level left the grid
                self.assertEqual(
                    [
                        {
                            "order_id": "q/reentry/1",
                            "price": D("4"),
                            "quantity": quantity,
                            "reason": reason,
                        }
                    ],
                    refused,
                )

    def test_a_placed_reentry_is_not_recorded(self):
        self.sell_with_reentry()
        refused = []
        match(self.account, quote("11.2", "11.3"), self.rules, refused=refused)
        self.assertEqual([], refused)
        self.assertEqual(["q/reentry/1"], list(self.account.orders))

    def test_check_false_skips_only_the_whole_account_validation(self):
        self.account.halt = "inconsistent: a halt without its category"
        order = LimitOrder("a", "buy", D("10"), D("5"), D("5"))
        with self.assertRaisesRegex(ValueError, "halt category"):
            place(self.account, order, self.rules)
        with self.assertRaisesRegex(ValueError, "halt category"):
            match(self.account, quote(), self.rules)
        place(self.account, order, self.rules, check=False)
        # The new order's own checks always run.
        with self.assertRaisesRegex(ValueError, "minimum notional"):
            place(
                self.account,
                LimitOrder("b", "buy", D("1"), D("1"), D("1")),
                self.rules,
                check=False,
            )
        self.assertEqual(1, len(match(self.account, quote(), self.rules, check=False)))
