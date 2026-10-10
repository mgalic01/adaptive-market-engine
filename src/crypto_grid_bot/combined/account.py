"""Unified exact spot/futures wallet for already admitted execution events.

This ledger sends no orders. Funding amounts are signed, already-computed wallet
cash flows: positive credits, negative debits. The engine must retain published
funding evidence and calculate from pre-timestamp holdings before applying exits.
Fill marks are explicitly identified historical observations, never fresh quotes.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from fractions import Fraction

from crypto_grid_bot.market_data.parsing import symbol_name


@dataclass(frozen=True, slots=True)
class FillEvent:
    event_id: str
    timestamp_ms: int
    symbol: str
    owner: str
    venue: str
    side: int
    quantity: Decimal
    price: Decimal
    fee: Decimal
    lot_id: str | None = None


@dataclass(frozen=True, slots=True)
class FundingEvent:
    event_id: str
    timestamp_ms: int
    symbol: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class LotSnapshot:
    lot_id: str
    quantity: Decimal
    entry_price: Decimal
    collateral: Decimal


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    symbol: str
    owner: str
    venue: str
    quantity: Decimal
    entry_cost: Decimal
    collateral: Decimal
    mark: Decimal
    mark_source: str
    mark_timestamp_ms: int | None
    unrealized_pnl: Decimal
    lots: tuple[LotSnapshot, ...]


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    free_cash: Decimal
    positions: tuple[PositionSnapshot, ...]
    equity: Decimal
    realized_pnl: Decimal
    fees: Decimal
    funding: Decimal
    reconciliation_residual: Decimal
    integrity_ok: bool
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Lot:
    lot_id: str
    owner: str
    venue: str
    side: int
    quantity: Fraction
    price: Fraction

    @property
    def collateral(self) -> Fraction:
        return self.quantity * self.price / 2 if self.venue == "futures" else Fraction(0)


def _decimal(value: Fraction) -> Decimal:
    # All ledger operations preserve terminating fractions: only division by two.
    # Dynamic precision accommodates decimal inputs without rounding or caller context.
    with localcontext() as context:
        context.prec = len(str(abs(value.numerator))) + 4 * len(str(value.denominator)) + 10
        return Decimal(value.numerator) / Decimal(value.denominator)


def _number(value: Decimal, *, positive: bool = False, signed: bool = False) -> Fraction:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("finite Decimal required")
    if (positive and value <= 0) or (not signed and value < 0):
        raise ValueError("invalid quantity, price or fee sign")
    return Fraction(value)


class CombinedAccount:
    """Single wallet, FIFO lots and immutable snapshots. Serialize calls externally.

    Exact rational bookkeeping avoids weighted-average/partial-close rounding.
    Negative cash from real fills/funding is booked and permanently flags integrity;
    it is not permission to admit exposure. Pending reservations live in the allocator.
    """

    def __init__(self, initial_cash: Decimal) -> None:
        self._initial = _number(initial_cash, positive=True)
        self._cash = self._initial
        self._positions: dict[str, tuple[_Lot, ...]] = {}
        self._marks: dict[str, tuple[Decimal, int]] = {}
        self._events: dict[str, FillEvent | FundingEvent] = {}
        self._last_ms = -1
        self._realized = Fraction(0)
        self._fees = Fraction(0)
        self._funding = Fraction(0)
        self._issues: set[str] = set()

    def apply(self, event: FillEvent | FundingEvent) -> AccountSnapshot:
        """Validate completely before mutation; repeat IDs are no-ops, conflicts fail."""
        if not isinstance(event, (FillEvent, FundingEvent)):
            raise ValueError("unsupported account event")
        if not isinstance(event.event_id, str) or not event.event_id:
            raise ValueError("event ID required")
        if type(event.timestamp_ms) is not int or event.timestamp_ms < 0:
            raise ValueError("nonnegative integer timestamp required")
        symbol_name(event.symbol)
        if isinstance(event, FillEvent):
            if type(event.side) is not int or event.side not in {-1, 1}:
                raise ValueError("side must be +1 or -1")
            _number(event.quantity, positive=True)
            _number(event.price, positive=True)
            _number(event.fee)
        else:
            _number(event.amount, signed=True)
        old = self._events.get(event.event_id)
        if old is not None:
            if old != event:
                raise ValueError("conflicting duplicate account event")
            return self.snapshot()
        if event.timestamp_ms < self._last_ms:
            raise ValueError("account events must be chronological")
        if isinstance(event, FillEvent):
            cash, lots, realized = self._fill(event)
            self._cash = cash
            if lots:
                self._positions[event.symbol] = lots
            else:
                self._positions.pop(event.symbol, None)
            self._realized += realized
            self._fees += Fraction(event.fee)
            self._marks[event.symbol] = (event.price, event.timestamp_ms)
        else:
            lots = self._positions.get(event.symbol, ())
            if not lots or lots[0].venue != "futures":
                raise ValueError("funding requires existing futures holdings")
            amount = Fraction(event.amount)
            self._cash += amount
            self._funding += amount
        if self._cash < 0:
            self._issues.add("negative_free_cash")
        self._events[event.event_id] = event
        self._last_ms = event.timestamp_ms
        return self.snapshot()

    def _fill(self, event: FillEvent) -> tuple[Fraction, tuple[_Lot, ...], Fraction]:
        if (
            event.owner not in {"spot_grid", "spot_trend", "futures_trend"}
            or (event.venue == "spot" and event.owner == "futures_trend")
            or (event.venue == "futures" and event.owner != "futures_trend")
        ):
            raise ValueError("owner and venue must match")
        if event.venue not in {"spot", "futures"}:
            raise ValueError("invalid venue")
        if event.lot_id is not None and (not isinstance(event.lot_id, str) or not event.lot_id):
            raise ValueError("nonempty lot ID required")
        lots = self._positions.get(event.symbol, ())
        if lots and (lots[0].owner != event.owner or lots[0].venue != event.venue):
            raise ValueError("asset already owned by another strategy or venue")
        quantity, price, fee = Fraction(event.quantity), Fraction(event.price), Fraction(event.fee)
        cash = self._cash - fee
        if not lots or lots[0].side == event.side:
            if event.venue == "spot" and event.side < 0:
                raise ValueError("spot cannot open short")
            lot_id = event.lot_id if event.lot_id is not None else event.event_id
            if any(lot.lot_id == lot_id for lot in lots):
                raise ValueError("duplicate open lot ID")
            new = _Lot(lot_id, event.owner, event.venue, event.side, quantity, price)
            cash -= quantity * price if event.venue == "spot" else new.collateral
            return cash, (*lots, new), Fraction(0)
        eligible = [lot for lot in lots if event.lot_id is None or lot.lot_id == event.lot_id]
        if sum(lot.quantity for lot in eligible) < quantity:
            raise ValueError("close exceeds eligible inventory; no implicit flip")
        remaining, realized = quantity, Fraction(0)
        retained: list[_Lot] = []
        for lot in lots:
            take = min(remaining, lot.quantity) if lot in eligible else Fraction(0)
            remaining -= take
            pnl = take * lot.side * (price - lot.price)
            realized += pnl
            cash += take * price if lot.venue == "spot" else take * lot.price / 2 + pnl
            if take < lot.quantity:
                retained.append(replace(lot, quantity=lot.quantity - take))
        return cash, tuple(retained), realized

    def snapshot(self, marks: Mapping[str, Decimal] | None = None) -> AccountSnapshot:
        """Value with explicit complete marks, or identified last-fill observations.

        Caller marks are not persisted and do not imply freshness. If supplied,
        every held asset requires a finite positive mark. No inventory is dust-erased.
        """
        positions: list[PositionSnapshot] = []
        equity, unrealized = self._cash, Fraction(0)
        for symbol, lots in sorted(self._positions.items()):
            if marks is not None and symbol not in marks:
                raise ValueError("missing explicit mark")
            mark = marks[symbol] if marks is not None else self._marks[symbol][0]
            price = _number(mark, positive=True)
            quantity = sum(lot.quantity * lot.side for lot in lots)
            cost = sum(lot.quantity * lot.price for lot in lots)
            collateral = sum((lot.collateral for lot in lots), Fraction(0))
            pnl = sum((lot.quantity * lot.side * (price - lot.price) for lot in lots), Fraction(0))
            unrealized += pnl
            equity += quantity * price if lots[0].venue == "spot" else collateral + pnl
            positions.append(
                PositionSnapshot(
                    symbol,
                    lots[0].owner,
                    lots[0].venue,
                    _decimal(Fraction(quantity)),
                    _decimal(Fraction(cost)),
                    _decimal(collateral),
                    mark,
                    "caller" if marks is not None else "fill",
                    None if marks is not None else self._marks[symbol][1],
                    _decimal(pnl),
                    tuple(
                        LotSnapshot(
                            lot.lot_id,
                            _decimal(lot.quantity * lot.side),
                            _decimal(lot.price),
                            _decimal(lot.collateral),
                        )
                        for lot in lots
                    ),
                )
            )
        residual = equity - (
            self._initial + self._realized + unrealized - self._fees + self._funding
        )
        issues = set(self._issues)
        if residual:
            issues.add("reconciliation_residual")
        if equity <= 0:
            issues.add("capital_exhausted")
        return AccountSnapshot(
            _decimal(self._cash),
            tuple(positions),
            _decimal(equity),
            _decimal(self._realized),
            _decimal(self._fees),
            _decimal(self._funding),
            _decimal(residual),
            not issues,
            tuple(sorted(issues)),
        )
