"""Exchange boundary used by execution code."""

from __future__ import annotations

from typing import Protocol

from crypto_grid_bot.domain import OrderSide, PaperOrder


class Exchange(Protocol):
    def place_limit_order(
        self, *, symbol: str, side: OrderSide, price: float, quantity: float
    ) -> PaperOrder: ...

    def cancel_order(self, order_id: str) -> None: ...

    def open_orders(self, symbol: str | None = None) -> tuple[PaperOrder, ...]: ...
