from unittest import TestCase

from crypto_grid_bot.domain import OrderSide
from crypto_grid_bot.exchange.paper import PaperExchange


class PaperExchangeTests(TestCase):
    def test_order_lifecycle(self) -> None:
        exchange = PaperExchange()
        order = exchange.place_limit_order(
            symbol="nightusdt", side=OrderSide.BUY, price=0.02, quantity=250
        )
        self.assertEqual(1, len(exchange.open_orders("NIGHTUSDT")))
        exchange.cancel_order(order.order_id)
        self.assertEqual(0, len(exchange.open_orders()))

    def test_invalid_values_never_create_an_order(self) -> None:
        exchange = PaperExchange()
        for bad in [float("nan"), float("inf"), -1, 0]:
            for price, quantity in [(bad, 1), (1, bad)]:
                with self.assertRaises(ValueError):
                    exchange.place_limit_order(
                        symbol="TESTUSDT", side=OrderSide.BUY, price=price, quantity=quantity
                    )
        self.assertEqual((), exchange.open_orders())
