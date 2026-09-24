"""In-memory exchange that cannot reach a real account."""

from __future__ import annotations

from datetime import UTC, datetime
from math import isfinite
from uuid import uuid4

from crypto_grid_bot.domain import OrderSide, PaperOrder


class PaperExchange:
    def __init__(self) -> None:
        self._orders: dict[str, PaperOrder] = {}

    def place_limit_order(
        self, *, symbol: str, side: OrderSide, price: float, quantity: float
    ) -> PaperOrder:
        if any(not isfinite(value) or value <= 0 for value in (price, quantity)):
            raise ValueError("price and quantity must be finite and positive")
        if not isfinite(price * quantity):
            raise ValueError("order notional overflow")
        if not symbol.strip() or not isinstance(side, OrderSide):
            raise ValueError("symbol and order side must be valid")
        order = PaperOrder(
            order_id=uuid4().hex,
            symbol=symbol.upper(),
            side=side,
            price=price,
            quantity=quantity,
            created_at=datetime.now(UTC),
        )
        self._orders[order.order_id] = order
        return order

    def cancel_order(self, order_id: str) -> None:
        if order_id not in self._orders:
            raise KeyError(f"unknown order: {order_id}")
        del self._orders[order_id]

    def open_orders(self, symbol: str | None = None) -> tuple[PaperOrder, ...]:
        orders = tuple(self._orders.values())
        if symbol is None:
            return orders
        expected = symbol.upper()
        return tuple(order for order in orders if order.symbol == expected)
