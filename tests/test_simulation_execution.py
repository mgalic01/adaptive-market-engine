from dataclasses import replace
from unittest import TestCase

from crypto_grid_bot.simulation.execution import cancel, liquidate, match, place, reduce_unreserved
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
        cancel(self.account, "a")
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
        cancel(self.account, "a")
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
        fills = liquidate(self.account, quote(size="20"), self.rules)
        self.assertEqual(D("2"), fills[0].quantity)
        self.assertEqual(D("9.79"), fills[0].price)
        self.assertEqual(D("8"), self.account.inventory)
        self.assertEqual([], liquidate(self.account, quote("0.01", "0.02"), self.rules))
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
        (fill,) = reduce_unreserved(account, quote(), rules)
        self.assertEqual(D("9.79"), fill.price)
        self.assertEqual(D("9.79") * 5 * D("0.0009"), fill.fee)
        self.assertEqual(fill.fee, account.fees)
