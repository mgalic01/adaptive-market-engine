"""Bounded offline execution arithmetic, never a venue adapter or event engine.

The caller verifies quotes/marks and funding publication, retains reservations and
partial close obligations, and checks newly filled positions against the adverse
same-bar path. Funding uses pre-event holdings. No helper here schedules live orders.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.account import PositionSnapshot


def _number(value: Decimal, *, positive: bool = False, signed: bool = False) -> Fraction:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("finite Decimal required")
    exponent = value.as_tuple().exponent
    if value.copy_abs() > Decimal("1e36") or not isinstance(exponent, int) or exponent < -100:
        raise ValueError("bounded magnitude and precision required")
    if (positive and value <= 0) or (not signed and value < 0):
        raise ValueError("invalid number sign")
    return Fraction(value)


def _decimal(value: Fraction) -> Decimal:
    # Decimal inputs, products and integer-step rounding have terminating fractions.
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
        return Decimal(value.numerator) / Decimal(value.denominator)


def _side(side: int) -> None:
    if type(side) is not int or side not in {-1, 1}:
        raise ValueError("side must be exactly +1 or -1")


@dataclass(frozen=True, slots=True)
class VenueRules:
    step: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal
    tick: Decimal

    def __post_init__(self) -> None:
        step = _number(self.step, positive=True)
        minimum = _number(self.min_qty)
        maximum = _number(self.max_qty, positive=True)
        _number(self.min_notional)
        _number(self.tick, positive=True)
        if step > maximum or minimum > (maximum // step) * step:
            raise ValueError("inconsistent quantity filters")


def floor_quantity(quantity: Decimal, rules: VenueRules) -> Decimal:
    """Floor to step only; callers separately apply minimums and maximum order size."""
    value, step = _number(quantity), Fraction(rules.step)
    return _decimal((value // step) * step)


def adverse_price(price: Decimal, side: int, rules: VenueRules) -> Decimal:
    """Round buy execution prices up, sell execution prices down, to the venue tick."""
    _side(side)
    value, tick = _number(price, positive=True), Fraction(rules.tick)
    steps = -((-value) // tick) if side == 1 else value // tick
    if steps <= 0:
        raise ValueError("no positive executable tick")
    return _decimal(steps * tick)


@dataclass(frozen=True, slots=True)
class Reduction:
    quantity: Decimal
    dust: bool
    reason: str


def executable_reduction(quantity: Decimal, price: Decimal, rules: VenueRules) -> Reduction:
    """One legal reduction of an absolute holding, at an externally verified fresh quote.

    Missing/invalid quotes raise, never establish dust. Even flat classification
    requires a valid quote here; the engine may already know a ledger position is zero.
    A max-quantity cap is a partial reduction, not a dust classification of its residue.
    """
    held, quote = _number(quantity), _number(price, positive=True)
    if not held:
        return Reduction(Decimal(0), False, "flat")
    capped = min(held, Fraction(rules.max_qty))
    amount = floor_quantity(_decimal(capped), rules)
    if (
        not amount
        or amount < rules.min_qty
        or Fraction(amount) * quote < Fraction(rules.min_notional)
    ):
        return Reduction(Decimal(0), True, "below_venue_minimum")
    return Reduction(amount, False, "executable")


def _order_values(decision_ms: int, side: int, quantity: Decimal) -> None:
    if type(decision_ms) is not int or decision_ms < 0:
        raise ValueError("nonnegative integer decision time required")
    _side(side)
    _number(quantity, positive=True)


@dataclass(frozen=True, slots=True)
class MarketOrder:
    decision_ms: int
    side: int
    quantity: Decimal

    def __post_init__(self) -> None:
        _order_values(self.decision_ms, self.side, self.quantity)


@dataclass(frozen=True, slots=True)
class LimitOrder:
    decision_ms: int
    side: int
    quantity: Decimal
    limit: Decimal

    def __post_init__(self) -> None:
        _order_values(self.decision_ms, self.side, self.quantity)
        _number(self.limit, positive=True)


@dataclass(frozen=True, slots=True)
class ExecutionFill:
    bar_open_ms: int
    at_open: bool
    quantity: Decimal
    price: Decimal
    remaining_quantity: Decimal


def simulate_order(
    order: MarketOrder | LimitOrder,
    bar: Kline | None,
    rules: VenueRules,
    *,
    slippage: Decimal = Decimal(0),
    max_quantity_available: Decimal | None = None,
) -> ExecutionFill | None:
    """Execute only in bars opening at/after the completed-information decision boundary.

    Markets use open plus adverse slippage/tick rounding. Touched limits use their
    exact tick-valid limit: no favorable gap credit and no slippage past that limit.
    Fees are charged by the engine. ``at_open=False`` identifies an intrabar fill;
    OHLC supplies no exact fill timestamp. The engine must preserve that uncertainty.

    Minimum filters apply to the scheduled order, not each partial execution. Explicit
    zero liquidity gives no fill; None means the caller's declared unlimited model.
    Never infer liquidity from OHLC volume or consider an unfilled remainder canceled.
    """
    if not isinstance(order, (MarketOrder, LimitOrder)):
        raise ValueError("explicit market or limit order required")
    slip = _number(slippage)
    if slip >= 1:
        raise ValueError("slippage must be below one")
    quantity = _number(order.quantity, positive=True)
    if floor_quantity(order.quantity, rules) != order.quantity or order.quantity > rules.max_qty:
        raise ValueError("scheduled quantity violates step or maximum")
    limit = order.limit if isinstance(order, LimitOrder) else None
    if limit is not None and Fraction(limit) % Fraction(rules.tick):
        raise ValueError("scheduled limit is not tick aligned")
    capacity = quantity if max_quantity_available is None else _number(max_quantity_available)
    if bar is None:
        return None
    if not isinstance(bar, Kline) or type(bar.open_ms) is not int or bar.open_ms < 0:
        raise ValueError("valid bar timestamp required")
    for price in (bar.open, bar.high, bar.low, bar.close):
        _number(price, positive=True)
    if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close):
        raise ValueError("invalid OHLC prices")
    if order.decision_ms > bar.open_ms:
        return None
    at_open = True
    if limit is not None:
        if (bar.low > limit) if order.side == 1 else (bar.high < limit):
            return None
        price = limit
        at_open = bar.open <= limit if order.side == 1 else bar.open >= limit
    else:
        price = adverse_price(
            _decimal(Fraction(bar.open) * (1 + order.side * slip)), order.side, rules
        )
    if order.quantity < rules.min_qty or quantity * Fraction(price) < Fraction(rules.min_notional):
        return None
    amount = floor_quantity(_decimal(min(quantity, capacity)), rules)
    if not amount:
        return None
    return ExecutionFill(bar.open_ms, at_open, amount, price, _decimal(quantity - Fraction(amount)))


def funding_cashflow(position: PositionSnapshot, published_rate: Decimal, mark: Decimal) -> Decimal:
    """Wallet credit positive: positive-rate longs pay, shorts receive.

    Caller supplies source-verified published funding and the pre-timestamp position;
    this arithmetic does not apply an admission filter or exempt an existing holding.
    """
    if position.venue != "futures":
        raise ValueError("funding requires a futures position")
    quantity = _number(position.quantity, signed=True)
    rate = _number(published_rate, signed=True)
    return _decimal(-quantity * rate * _number(mark, positive=True))


@dataclass(frozen=True, slots=True)
class MarginState:
    backing: Decimal
    maintenance: Decimal
    ratio: Decimal | None


def futures_margin(free_cash: Decimal, positions: tuple[PositionSnapshot, ...]) -> MarginState:
    """Aggregate the futures-eligible shared wallet, excluding spot inventory.

    Maintenance is .01 of gross futures marked notional, pinned to frozen V3
    FuturesAccount.check_liquidation. Backing is free cash plus futures collateral
    plus futures unrealized P&L, NOT per-lot isolated collateral and NOT spot equity.
    Caller verifies current marks. Compare backing and multiples of maintenance for
    exact threshold decisions; ratio is a 60-digit reporting value (None if flat).
    """
    backing = _number(free_cash, signed=True)
    maintenance = Fraction(0)
    if not isinstance(positions, tuple):
        raise ValueError("immutable position snapshot required")
    seen: set[str] = set()
    for position in positions:
        if position.symbol in seen or position.venue not in {"spot", "futures"}:
            raise ValueError("duplicate or invalid venue position")
        seen.add(position.symbol)
        if position.venue == "futures":
            quantity = _number(position.quantity, signed=True)
            mark = _number(position.mark, positive=True)
            backing += _number(position.collateral) + _number(position.unrealized_pnl, signed=True)
            maintenance += abs(quantity) * mark / 100
    ratio = None
    if maintenance:
        with localcontext() as context:
            context.prec = 60
            ratio = (
                Decimal(backing.numerator)
                * maintenance.denominator
                / (Decimal(backing.denominator) * maintenance.numerator)
            )
    return MarginState(_decimal(backing), _decimal(maintenance), ratio)
