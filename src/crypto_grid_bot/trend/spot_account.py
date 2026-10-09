"""Decimal60 spot cash settlement for the frozen V3 comparison account."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.filters import OrderFilters

ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class SpotFill:
    symbol: str
    timestamp_ms: int
    requested: Decimal
    quantity: Decimal
    price: Decimal
    fee: Decimal
    reason: str | None
    open_price: Decimal


@dataclass(frozen=True, slots=True)
class SpotAudit:
    cash_residual: Decimal
    quantity_residuals: dict[str, Decimal]

    @property
    def exact(self) -> bool:
        return self.cash_residual == 0 and all(v == 0 for v in self.quantity_residuals.values())


def _finite(value: Decimal, *, positive: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value.copy_abs() > Decimal("1e36")
    ):
        raise ValueError("finite bounded Decimal required")
    if positive and value <= 0:
        raise ValueError("positive value required")


def _floor(value: Fraction, step: Decimal) -> Decimal:
    return Decimal(value // Fraction(step)) * step


class SpotAccount:
    def __init__(self, *, cost_multiple: int = 1) -> None:
        if type(cost_multiple) is not int or cost_multiple not in (1, 2):
            raise ValueError("invalid cost multiple")
        self.initial = Decimal(10000)
        self.cash = self.initial
        self.holdings: dict[str, Decimal] = {}
        self.fills: list[SpotFill] = []
        self._clock = -1
        self.cost_multiple = cost_multiple

    def execute(
        self,
        symbol: str,
        quantity: Decimal,
        open_price: Decimal,
        filters: OrderFilters,
        timestamp_ms: int,
    ) -> tuple[SpotFill, ...]:
        """Balanced maximum-quantity splitting; each child obeys spot cash limits."""
        _finite(quantity)
        for value in (filters.step_size, filters.max_quantity, filters.min_quantity):
            _finite(value, positive=True)
        if quantity < 0 and quantity.copy_abs() > self.holdings.get(symbol, ZERO):
            raise ValueError("spot cannot sell unowned quantity")
        if quantity.copy_abs() <= filters.max_quantity:
            return (self.fill(symbol, quantity, open_price, filters, timestamp_ms),)
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            steps = Fraction(quantity.copy_abs()) // Fraction(filters.step_size)
            maximum = Fraction(filters.max_quantity) // Fraction(filters.step_size)
            if maximum < 1:
                raise ValueError("maximum quantity is below step")
            count = (steps + maximum - 1) // maximum
            base, extra = divmod(steps, count)
            sizes = [(base + (i < extra)) * filters.step_size for i in range(count)]
            if any(size < filters.min_quantity for size in sizes):
                raise ValueError("no valid balanced quantity split")
            fills = []
            for size in sizes:
                fill = self.fill(
                    symbol, size if quantity > 0 else -size, open_price, filters, timestamp_ms
                )
                fills.append(fill)
                if fill.quantity == 0 or fill.reason == "cash_clipped":
                    break
            return tuple(fills)

    def fill(
        self,
        symbol: str,
        quantity: Decimal,
        open_price: Decimal,
        filters: OrderFilters,
        timestamp_ms: int,
    ) -> SpotFill:
        """Settle one bounded order; the caller splits orders above max quantity."""
        symbol_name(symbol)
        _finite(quantity)
        _finite(open_price, positive=True)
        if quantity == 0:
            raise ValueError("nonzero order quantity required")
        if type(timestamp_ms) is not int or timestamp_ms < 0 or timestamp_ms < self._clock:
            raise ValueError("chronological timestamp required")
        development_month(datetime.fromtimestamp(timestamp_ms // 1000, UTC).strftime("%Y-%m"))
        for value in (filters.step_size, filters.min_quantity, filters.max_quantity):
            _finite(value, positive=True)
        _finite(filters.min_notional)
        if filters.min_notional < 0 or filters.min_quantity > filters.max_quantity:
            raise ValueError("invalid order filters")
        if quantity.copy_abs() > filters.max_quantity:
            raise ValueError("split order above maximum quantity before settlement")
        if quantity < 0 and quantity.copy_abs() > self.holdings.get(symbol, ZERO):
            raise ValueError("spot cannot sell unowned quantity")
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            fee_rate = Decimal(".001") * self.cost_multiple
            slip = Decimal(".0005") * self.cost_multiple
            price = open_price * (1 + slip if quantity > 0 else 1 - slip)
            size = _floor(Fraction(quantity.copy_abs()), filters.step_size)
            reason = None
            if quantity > 0:
                affordable = _floor(
                    Fraction(self.cash) / Fraction(price * (1 + fee_rate)), filters.step_size
                )
                if affordable < size:
                    size, reason = affordable, "cash_clipped"
            if size < filters.min_quantity:
                size, reason = ZERO, "minimum_quantity"
            elif size * price < filters.min_notional:
                size, reason = ZERO, "minimum_notional"
            signed = size if quantity > 0 else -size
            fee = size * price * fee_rate
            cash = self.cash - (signed * price + fee)
            if cash < 0:
                raise ValueError("cash affordability calculation overspent")
            holding = self.holdings.get(symbol, ZERO) + signed
            result = SpotFill(
                symbol, timestamp_ms, quantity, signed, price, fee, reason, open_price
            )
            self.cash = cash
            self.holdings[symbol] = holding
            self.fills.append(result)
            self._clock = timestamp_ms
            return result

    def mark(self, prices: Mapping[str, Decimal]) -> Decimal:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            equity = self.cash
            for symbol, quantity in sorted(self.holdings.items()):
                if quantity:
                    price = prices[symbol]
                    _finite(price, positive=True)
                    equity += quantity * price
            return equity

    def audit(self) -> SpotAudit:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            cash = self.initial
            quantities: dict[str, Decimal] = {}
            for fill in self.fills:
                cash -= fill.quantity * fill.price + fill.fee
                quantities[fill.symbol] = quantities.get(fill.symbol, ZERO) + fill.quantity
            return SpotAudit(
                self.cash - cash,
                {
                    symbol: self.holdings.get(symbol, ZERO) - quantities.get(symbol, ZERO)
                    for symbol in self.holdings.keys() | quantities.keys()
                },
            )
