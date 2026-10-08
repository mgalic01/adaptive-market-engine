"""V3 futures ledger primitives; the hourly scheduler supplies event ordering."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from types import MappingProxyType

from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.orders import OrderIntent

ZERO = Decimal(0)
ONE = Decimal(1)


def _context() -> Context:
    return Context(prec=60, rounding=ROUND_HALF_EVEN)


def _number(value: Decimal, *, positive: bool = False) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value.copy_abs() > Decimal("1e36")
    ):
        raise ValueError("invalid account number")
    if positive and value <= ZERO:
        raise ValueError("positive account value required")


@dataclass(frozen=True, slots=True)
class Position:
    quantity: Decimal = ZERO
    average_entry: Decimal = ZERO


@dataclass(frozen=True, slots=True)
class Fill:
    symbol: str
    timestamp_ms: int
    quantity: Decimal
    open_price: Decimal
    price: Decimal
    fee: Decimal
    realized: Decimal
    reduce_only: bool


@dataclass(frozen=True, slots=True)
class FillEvent:
    fill: Fill
    before: Position
    after: Position


@dataclass(frozen=True, slots=True)
class FundingPayment:
    symbol: str
    quantity: Decimal
    price: Decimal
    rate: Decimal
    payment: Decimal  # Positive is paid, negative is received.


@dataclass(frozen=True, slots=True)
class FundingEvent:
    timestamp_ms: int
    payments: tuple[FundingPayment, ...]


@dataclass(frozen=True, slots=True)
class AccountMark:
    wallet: Decimal
    unrealized: Decimal
    equity: Decimal
    gross_notional: Decimal
    margin_ratio: Decimal | None
    gross_leverage: Decimal | None
    prices: Mapping[str, Decimal]


@dataclass(frozen=True, slots=True)
class Liquidation:
    timestamp_ms: int
    mark: AccountMark


@dataclass(frozen=True, slots=True)
class AccountingAudit:
    wallet_residual: Decimal
    quantity_residuals: dict[str, Decimal]
    equity_residual: Decimal

    @property
    def exact(self) -> bool:
        return (
            self.wallet_residual == ZERO
            and self.equity_residual == ZERO
            and all(value == ZERO for value in self.quantity_residuals.values())
        )


class FuturesAccount:
    """Chronological ledger, with the wallet evaluated in the frozen formula order.

    Callers must perform the hourly pre/post-fill and funding checks required by
    section6. No liquidation fee/fill or post-liquidation mutation is permitted.
    """

    def __init__(self, initial: Decimal = Decimal(10000), cost_multiple: int = 1) -> None:
        _number(initial, positive=True)
        if type(cost_multiple) is not int or cost_multiple not in (1, 2):
            raise ValueError("cost multiple must be1 or2")
        self.initial = initial
        self.cost_multiple = cost_multiple
        self._positions: dict[str, Position] = {}
        self._fills: list[Fill] = []
        self._funding: list[FundingEvent] = []
        self._events: list[FillEvent | FundingEvent] = []
        self._realized = self._fees = self._paid = self._received = ZERO
        self._clock = -1
        self._funding_clock = -1
        self.liquidation: Liquidation | None = None

    @property
    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    @property
    def fills(self) -> tuple[Fill, ...]:
        return tuple(self._fills)

    @property
    def funding(self) -> tuple[FundingEvent, ...]:
        return tuple(self._funding)

    @property
    def events(self) -> tuple[FillEvent | FundingEvent, ...]:
        """Actual insertion order, including ties between funding and fills."""
        return tuple(self._events)

    @property
    def wallet(self) -> Decimal:
        with localcontext(_context()):
            return self.initial + self._realized - self._fees - self._paid + self._received

    def _time(self, stamp: int) -> None:
        if self.liquidation is not None:
            raise ValueError("account is terminal after liquidation")
        if type(stamp) is not int or stamp < 0 or stamp < self._clock:
            raise ValueError("events must have nondecreasing valid timestamps")
        development_month(datetime.fromtimestamp(stamp // 1000, UTC).strftime("%Y-%m"))

    def fill(
        self, symbol: str, intent: OrderIntent, open_price: Decimal, timestamp_ms: int
    ) -> Fill:
        self._time(timestamp_ms)
        symbol_name(symbol)
        with localcontext(_context()):
            _number(open_price, positive=True)
            _number(intent.quantity)
            quantity = intent.quantity
            held = self._positions.get(symbol, Position())
            if quantity == ZERO:
                raise ValueError("zero fill quantity")
            if intent.reduce_only:
                if held.quantity * quantity >= ZERO or abs(quantity) > abs(held.quantity):
                    raise ValueError("reduce-only fill must reduce without crossing zero")
            elif held.quantity * quantity < ZERO:
                raise ValueError("opposite-side opening must close separately first")
            cost = Decimal(".0005") * self.cost_multiple
            price = open_price * (ONE + cost if quantity > ZERO else ONE - cost)
            fee = abs(quantity) * price * cost
            realized = ZERO
            entry = held.average_entry
            if intent.reduce_only:
                difference = price - entry if held.quantity > ZERO else entry - price
                realized = abs(quantity) * difference
            else:
                entry = (abs(held.quantity) * entry + abs(quantity) * price) / (
                    abs(held.quantity) + abs(quantity)
                )
            record = Fill(
                symbol, timestamp_ms, quantity, open_price, price, fee, realized, intent.reduce_only
            )
            self._positions[symbol] = Position(held.quantity + quantity, entry)
            self._realized += realized
            self._fees += fee
            self._fills.append(record)
            self._events.append(FillEvent(record, held, self._positions[symbol]))
            self._clock = timestamp_ms
            return record

    def fund(
        self, timestamp_ms: int, rates: Mapping[str, Decimal], prices: Mapping[str, Decimal]
    ) -> FundingEvent:
        self._time(timestamp_ms)
        if not rates:
            raise ValueError("empty funding group")
        if timestamp_ms <= self._funding_clock:
            raise ValueError("same-time funding must be supplied as one complete group")
        payments = []
        with localcontext(_context()):
            for symbol in sorted(rates):
                symbol_name(symbol)
                rate = rates[symbol]
                _number(rate)
                quantity = self._positions.get(symbol, Position()).quantity
                if quantity == ZERO:
                    continue
                if symbol not in prices:
                    raise ValueError("funding price missing for open position")
                price = prices[symbol]
                _number(price, positive=True)
                payments.append(
                    FundingPayment(symbol, quantity, price, rate, quantity * price * rate)
                )
            # Build the entire group before committing any charge or changing clocks.
            paid = sum((row.payment for row in payments if row.payment > ZERO), ZERO)
            received = sum((-row.payment for row in payments if row.payment < ZERO), ZERO)
            event = FundingEvent(timestamp_ms, tuple(payments))
            self._paid += paid
            self._received += received
            self._funding.append(event)
            self._events.append(event)
            self._clock = self._funding_clock = timestamp_ms
            return event

    def mark(self, prices: Mapping[str, Decimal]) -> AccountMark:
        with localcontext(_context()):
            unrealized = gross = ZERO
            used = {}
            for symbol, held in sorted(self._positions.items()):
                if held.quantity == ZERO:
                    continue
                if symbol not in prices:
                    raise ValueError("mark price missing for open position")
                price = prices[symbol]
                _number(price, positive=True)
                used[symbol] = price
                unrealized += held.quantity * (price - held.average_entry)
                gross += abs(held.quantity) * price
            wallet = self.wallet
            equity = wallet + unrealized
            margin = equity / gross if gross != ZERO else None
            leverage = gross / equity if equity > ZERO else None
            return AccountMark(
                wallet, unrealized, equity, gross, margin, leverage, MappingProxyType(used)
            )

    def check_liquidation(self, prices: Mapping[str, Decimal], timestamp_ms: int) -> AccountMark:
        self._time(timestamp_ms)
        with localcontext(_context()):
            mark = self.mark(prices)
            if mark.gross_notional > ZERO and mark.equity <= Decimal(".01") * mark.gross_notional:
                self.liquidation = Liquidation(timestamp_ms, mark)
            self._clock = timestamp_ms
            return mark

    def audit(self, prices: Mapping[str, Decimal]) -> AccountingAudit:
        """Reconstruct from event records; retain exact residuals, never patch them."""
        with localcontext(_context()):
            realized = sum((row.realized for row in self._fills), ZERO)
            fees = sum((row.fee for row in self._fills), ZERO)
            paid = received = ZERO
            for event in self._funding:
                paid += sum((row.payment for row in event.payments if row.payment > ZERO), ZERO)
                received += sum(
                    (-row.payment for row in event.payments if row.payment < ZERO), ZERO
                )
            expected_wallet = self.initial + realized - fees - paid + received
            residuals = {}
            symbols = set(self._positions) | {row.symbol for row in self._fills}
            for symbol in sorted(symbols):
                position = self._positions.get(symbol, Position())
                bought = sum(
                    (
                        row.quantity
                        for row in self._fills
                        if row.symbol == symbol and row.quantity > ZERO
                    ),
                    ZERO,
                )
                sold = sum(
                    (
                        -row.quantity
                        for row in self._fills
                        if row.symbol == symbol and row.quantity < ZERO
                    ),
                    ZERO,
                )
                residuals[symbol] = position.quantity - (bought - sold)
            mark = self.mark(prices)
            expected_change = realized + mark.unrealized - fees - paid + received
            return AccountingAudit(
                self.wallet - expected_wallet,
                residuals,
                (mark.equity - self.initial) - expected_change,
            )
