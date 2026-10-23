"""The shared spot and USDT-M futures account of V4: FIFO lots by venue and symbol, one cash
balance, funding, marks and the exact audit.

Implements the spec's "Account and execution: one shared account" (one wallet; funding on
futures) and the "Futures margin" and "Accounting" bullets of "Safety", with the plan's
Ruling R2. The pattern is V3.1's ``combined.account.CombinedAccount`` (copied, not called: it
keys positions by symbol alone and books collateral, and V4 does neither).

* **One wallet, no collateral bucket** (Ruling R2). ``cash`` is the wallet's USDT. A spot buy
  spends ``quantity x price + fee`` and a spot sell adds ``quantity x price - fee``. A futures
  fill moves cash by its realised P&L minus its fee and nothing else: the initial margin is
  computed by the allocation, never booked. So ``backing = cash + futures unrealised P&L``,
  which equals V3.1's free cash + collateral + unrealised P&L.
* **Positions are FIFO lots keyed by (venue, symbol)** (Review Focus 1), so a coin holds its
  spot leg and a perpetual leg of the same name at once. Quantities and prices are in each
  venue's own units, coins on spot and contracts on the perpetual (Ruling R5); the ledger
  never sees a multiplier. Spot is long only, and a spot sell may not exceed the held
  quantity. A futures fill that would cross zero is refused, so the caller books a flip as a
  close and then an open.
* **Funding** is a signed amount added to cash and to nothing else. The caller computes it as
  ``-quantity x rate x price`` (spec "Shorts on futures", V3.1's ``funding_cashflow``), so a
  long pays a positive rate and a short receives it. Only an open futures leg takes funding.
* **Marks.** ``maintenance = 0.01 x sum |quantity x mark|`` over the futures legs, and
  ``ratio = backing / maintenance``, None with no futures leg (the engine reads None as
  +infinity). ``gross_notional`` sums the spot and futures notionals, and
  ``gross = gross_notional / equity``, None when equity is at or below zero.
* **Audit** ("Accounting"), from running totals kept apart from the cash and the lots:
  ``wallet_residual = cash - (initial - spot buys + spot sells - fees + realised futures P&L +
  funding)``; per (venue, symbol) ever traded, ``held - (bought - sold)``, with ``held``
  summed from the lots; ``equity_residual = equity - (initial + realised + unrealised - fees
  + funding)``, where equity comes from each position's running quantity and cost and the
  unrealised P&L from its lots, lot by lot. The first two are exactly 0 and the third is
  returned for the caller to hold within 1e-18.

  In the equity identity the futures realised P&L is not the booked total, which is also
  what moved cash and so would cancel. It is the futures fills' flow, ``sum -side x quantity
  x price``, plus the open futures lots' basis, ``sum side x lot quantity x lot price``, which
  equals the booked total exactly when the FIFO booking is right. Spot realised P&L never
  moves cash (a spot fill moves it by its notional), so its booked total is checked as it is.

The ledger books what it is given and admits nothing: the cash clip and the safety checks
decide what may fill, so a fill or funding may take cash below zero. Amounts are exact
``Fraction``s inside. Every value returned is the exact Decimal of one (``numbers.to_decimal``),
except the two quotients, ``ratio`` and ``gross``, which are Decimal divisions under
``CONTEXT``. Every call checks all its input before it changes any state, so a refused call
leaves the ledger as it was. Fills and funding share one clock, which may not go backwards.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from types import MappingProxyType
from typing import Literal, get_args

from crypto_grid_bot.v4.engine.arms import MAINTENANCE_RATE
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal, to_fraction

Venue = Literal["spot", "futures"]
_VENUES: tuple[str, ...] = get_args(Venue)
_Key = tuple[Venue, str]

# The V4 data layer's symbol pattern (ruling R7).
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")

_ZERO = Fraction(0)
_MAINTENANCE = to_fraction(MAINTENANCE_RATE)


@dataclass(frozen=True, slots=True)
class Fill:
    """One trade on one venue: ``side`` +1 buys and -1 sells ``quantity`` (venue units) at
    ``price``, paying ``fee`` USDT. ``reason`` is carried for the records."""

    timestamp_ms: int
    venue: Venue
    symbol: str
    side: int
    quantity: Decimal
    price: Decimal
    fee: Decimal
    reason: str

    def __post_init__(self) -> None:
        _timestamp(self.timestamp_ms)
        _venue(self.venue)
        _symbol(self.symbol)
        if type(self.side) is not int or self.side not in (1, -1):
            raise ValueError(f"side must be +1 or -1, got {self.side!r:.40}")
        _number(self.quantity, "quantity", positive=True)
        _number(self.price, "price", positive=True)
        _number(self.fee, "fee")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError(f"reason must be a non-empty string, got {self.reason!r:.40}")


@dataclass(frozen=True, slots=True)
class Mark:
    """The account at one set of prices. ``ratio`` is None with no futures leg (read as
    +infinity); ``gross`` is None when equity is at or below zero."""

    equity: Decimal
    cash: Decimal
    spot_value: Decimal
    futures_upnl: Decimal
    backing: Decimal
    maintenance: Decimal
    ratio: Decimal | None
    gross_notional: Decimal
    gross: Decimal | None


@dataclass(frozen=True, slots=True)
class Audit:
    """The accounting identities' residuals. ``quantity_residuals`` covers every (venue,
    symbol) the ledger has traded, sorted. The wallet and quantity residuals are exactly 0;
    the caller holds ``|equity_residual| <= 1e-18``."""

    wallet_residual: Decimal
    quantity_residuals: Mapping[tuple[Venue, str], Decimal]
    equity_residual: Decimal


@dataclass(frozen=True, slots=True)
class _Lot:
    quantity: Fraction
    price: Fraction


@dataclass(frozen=True, slots=True)
class _Position:
    """One open leg: its side (+1 long, -1 short; spot is always +1), its FIFO lots (oldest
    first), and the running sum of their quantities and of their quantity x price."""

    side: int
    lots: tuple[_Lot, ...]
    quantity: Fraction
    cost: Fraction

    def unrealised(self, mark: Fraction) -> Fraction:
        # Equal to the sum over the lots of side x quantity x (mark - price).
        return self.side * (self.quantity * mark - self.cost)


class Ledger:
    """The one shared account: cash, the spot and futures legs, and the audit totals."""

    def __init__(self, initial_cash: Decimal) -> None:
        self._initial = _number(initial_cash, "initial_cash", positive=True)
        self._cash = self._initial
        self._positions: dict[_Key, _Position] = {}
        self._last_ms = -1
        # Audit totals, each kept apart from the cash and the lots.
        self._spot_bought = _ZERO  # USDT notional of spot buys
        self._spot_sold = _ZERO  # USDT notional of spot sells
        self._fees = _ZERO
        self._realised_spot = _ZERO
        self._realised_futures = _ZERO
        self._futures_flow = _ZERO  # sum of -side x quantity x price over futures fills
        self._funding = _ZERO
        self._traded: dict[_Key, tuple[Fraction, Fraction]] = {}  # quantity bought, sold

    @property
    def cash(self) -> Decimal:
        """The wallet's USDT."""
        return to_decimal(self._cash)

    def fill(self, f: Fill) -> Decimal:
        """Book one fill and return its realised P&L (0 for a buy on spot or a futures fill
        that opens or increases). Refuses a spot sell above the held quantity and a futures
        fill that would cross zero."""
        if not isinstance(f, Fill):
            raise ValueError(f"a Fill is required, got {f!r:.60}")
        self._clock(f.timestamp_ms)
        key: _Key = (f.venue, f.symbol)
        quantity, price, fee = to_fraction(f.quantity), to_fraction(f.price), to_fraction(f.fee)
        held = self._positions.get(key)
        if held is not None and held.side != f.side:
            if quantity > held.quantity:
                if f.venue == "spot":
                    raise ValueError(
                        f"a spot sell of {f.quantity} {f.symbol} exceeds the held "
                        f"{to_decimal(held.quantity)}"
                    )
                raise ValueError(
                    f"a futures fill of {f.side * f.quantity} {f.symbol} crosses zero from "
                    f"{to_decimal(held.side * held.quantity)}; book a flip as a close and an open"
                )
            position, realised = _reduce(held, quantity, price)
        elif f.venue == "spot" and f.side < 0:
            raise ValueError(f"a spot sell of {f.quantity} {f.symbol} exceeds the held 0")
        else:
            position, realised = _increase(held, f.side, quantity, price), _ZERO
        notional = quantity * price
        if f.venue == "spot":
            move = (notional if f.side < 0 else -notional) - fee
        else:
            move = realised - fee
        result = to_decimal(realised)
        # Commit: nothing above changed any state.
        self._cash += move
        if position is None:
            del self._positions[key]
        else:
            self._positions[key] = position
        bought, sold = self._traded.get(key, (_ZERO, _ZERO))
        self._traded[key] = (bought + quantity, sold) if f.side > 0 else (bought, sold + quantity)
        self._fees += fee
        if f.venue == "spot":
            if f.side > 0:
                self._spot_bought += notional
            else:
                self._spot_sold += notional
            self._realised_spot += realised
        else:
            self._realised_futures += realised
            self._futures_flow -= f.side * notional
        self._last_ms = f.timestamp_ms
        return result

    def funding(self, timestamp_ms: int, perpetual: str, amount: Decimal) -> None:
        """Add one signed funding ``amount`` (USDT, positive credits) to cash. The perpetual
        must have an open futures leg."""
        self._clock(timestamp_ms)
        _symbol(perpetual)
        value = _number(amount, "amount", signed=True)
        if ("futures", perpetual) not in self._positions:
            raise ValueError(f"funding on {perpetual} needs an open futures position")
        self._cash += value
        self._funding += value
        self._last_ms = timestamp_ms

    def quantity(self, venue: Venue, symbol: str) -> Decimal:
        """The held quantity in venue units: signed on futures, never negative on spot."""
        position = self._positions.get((_venue(venue), _symbol(symbol)))
        return Decimal(0) if position is None else to_decimal(position.side * position.quantity)

    def positions(self) -> Mapping[tuple[Venue, str], Decimal]:
        """Every open leg's quantity, as ``quantity`` gives it, sorted by (venue, symbol)."""
        return MappingProxyType(
            {
                key: to_decimal(self._positions[key].side * self._positions[key].quantity)
                for key in sorted(self._positions)
            }
        )

    def unrealised(self, venue: Venue, symbol: str, mark: Decimal) -> Decimal:
        """The FIFO unrealised P&L of one leg at ``mark`` (0 for a leg not held)."""
        position = self._positions.get((_venue(venue), _symbol(symbol)))
        price = _number(mark, "mark", positive=True)
        return Decimal(0) if position is None else to_decimal(position.unrealised(price))

    def mark(self, prices: Mapping[tuple[Venue, str], Decimal]) -> Mark:
        """The account at ``prices``, which must price every open leg; extras are ignored."""
        spot_value, futures_upnl, futures_notional = self._value(self._prices(prices))
        backing = self._cash + futures_upnl
        equity = backing + spot_value
        maintenance = _MAINTENANCE * futures_notional
        gross_notional = spot_value + futures_notional
        return Mark(
            equity=to_decimal(equity),
            cash=to_decimal(self._cash),
            spot_value=to_decimal(spot_value),
            futures_upnl=to_decimal(futures_upnl),
            backing=to_decimal(backing),
            maintenance=to_decimal(maintenance),
            ratio=_quotient(backing, maintenance) if maintenance else None,
            gross_notional=to_decimal(gross_notional),
            gross=_quotient(gross_notional, equity) if equity > 0 else None,
        )

    def audit(self, prices: Mapping[tuple[Venue, str], Decimal]) -> Audit:
        """The residuals of the three accounting identities at ``prices`` (as ``mark``)."""
        marks = self._prices(prices)
        spot_value, futures_upnl, _ = self._value(marks)
        equity = self._cash + spot_value + futures_upnl
        wallet = self._cash - (
            self._initial
            - self._spot_bought
            + self._spot_sold
            - self._fees
            + self._realised_futures
            + self._funding
        )
        quantities: dict[tuple[Venue, str], Decimal] = {}
        for key in sorted(self._traded):
            bought, sold = self._traded[key]
            position = self._positions.get(key)
            held = (
                _ZERO
                if position is None
                else position.side * sum((lot.quantity for lot in position.lots), _ZERO)
            )
            quantities[key] = to_decimal(held - (bought - sold))
        unrealised = futures_basis = _ZERO
        for key, position in self._positions.items():
            for lot in position.lots:
                unrealised += position.side * lot.quantity * (marks[key] - lot.price)
                if key[0] == "futures":
                    futures_basis += position.side * lot.quantity * lot.price
        # Futures realised P&L from the fills' flows and the open lots' basis, not from the
        # booked total: the booked number is also what moved cash, so it would cancel here.
        expected = (
            self._initial
            + self._realised_spot
            + self._futures_flow
            + futures_basis
            + unrealised
            - self._fees
            + self._funding
        )
        return Audit(
            wallet_residual=to_decimal(wallet),
            quantity_residuals=MappingProxyType(quantities),
            equity_residual=to_decimal(equity - expected),
        )

    def _clock(self, timestamp_ms: int) -> None:
        _timestamp(timestamp_ms)
        if timestamp_ms < self._last_ms:
            raise ValueError(f"time may not go backwards: {timestamp_ms} < {self._last_ms}")

    def _prices(self, prices: Mapping[tuple[Venue, str], Decimal]) -> dict[_Key, Fraction]:
        """The exact price of every open leg, from ``prices``."""
        if not isinstance(prices, Mapping):
            raise ValueError("prices must be a mapping of (venue, symbol) to a Decimal price")
        marks: dict[_Key, Fraction] = {}
        for key in self._positions:
            if key not in prices:
                raise ValueError(f"no price for the open {key[0]} position {key[1]}")
            marks[key] = _number(prices[key], f"the {key[0]} price of {key[1]}", positive=True)
        return marks

    def _value(self, marks: Mapping[_Key, Fraction]) -> tuple[Fraction, Fraction, Fraction]:
        """Spot value, futures unrealised P&L and futures notional, from the running totals."""
        spot_value = futures_upnl = futures_notional = _ZERO
        for key, position in self._positions.items():
            price = marks[key]
            if key[0] == "spot":
                spot_value += position.quantity * price
            else:
                futures_upnl += position.unrealised(price)
                futures_notional += position.quantity * price
        return spot_value, futures_upnl, futures_notional


def _increase(held: _Position | None, side: int, quantity: Fraction, price: Fraction) -> _Position:
    lot = _Lot(quantity, price)
    if held is None:
        return _Position(side, (lot,), quantity, quantity * price)
    return _Position(
        side, (*held.lots, lot), held.quantity + quantity, held.cost + quantity * price
    )


def _reduce(
    held: _Position, quantity: Fraction, price: Fraction
) -> tuple[_Position | None, Fraction]:
    """Take ``quantity`` from the oldest lots first. Returns the rest (None when nothing is
    left) and the realised P&L."""
    remaining, pnl, cost = quantity, _ZERO, held.cost
    kept: list[_Lot] = []
    for lot in held.lots:
        take = min(remaining, lot.quantity)
        if take:
            remaining -= take
            pnl += take * (price - lot.price)
            cost -= take * lot.price
        if take < lot.quantity:
            kept.append(lot if not take else _Lot(lot.quantity - take, lot.price))
    if remaining:
        raise RuntimeError("the lots hold less than the position's quantity")  # unreachable
    realised = held.side * pnl
    if not kept:
        return None, realised
    return _Position(held.side, tuple(kept), held.quantity - quantity, cost), realised


def _quotient(numerator: Fraction, denominator: Fraction) -> Decimal:
    """``numerator / denominator`` as a Decimal division of the two exact Decimals."""
    with localcontext(CONTEXT):
        return to_decimal(numerator) / to_decimal(denominator)


def _timestamp(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"a timestamp must be a non-negative int (ms), got {value!r:.40}")
    return value


def _venue(value: object) -> Venue:
    if isinstance(value, str):
        if value == "spot":
            return "spot"
        if value == "futures":
            return "futures"
    raise ValueError(f"venue must be one of {_VENUES}, got {value!r:.40}")


def _symbol(value: object) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"symbol must match [A-Z0-9]{{2,30}}, got {value!r:.40}")
    return value


def _number(value: object, what: str, *, positive: bool = False, signed: bool = False) -> Fraction:
    """The exact value of a finite Decimal: positive, signed, or (the default) at least 0."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} must be a finite Decimal, got {value!r:.40}")
    if positive and value <= 0:
        raise ValueError(f"{what} must be positive, got {value}")
    if not positive and not signed and value < 0:
        raise ValueError(f"{what} must not be negative, got {value}")
    return to_fraction(value)
