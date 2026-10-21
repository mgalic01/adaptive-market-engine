"""Per coin and side trade lifecycles across the spot and futures venues, for the trade records.

Implements the spec's "Records" (the "Per trade lifecycle" bullet and its sub-bullets), the
"Window end" bullet of "Account and execution" and "How a cell that stops early ends" in
"Safety", with the plan's Ruling R6 and the controller's rulings on this task.

* **A lifecycle is keyed by the coin**, that is its spot symbol. The perpetual may carry another
  symbol (1000SHIBUSDT for SHIBUSDT), so funding and every call here name the coin, and a coin's
  futures fills must all carry one perpetual symbol.
* **Side and ending.** The side is the sign of the coin's signed notional over both venues as
  ``after_batch`` is given it (``long`` or ``short``). A lifecycle opens when that leaves zero.
  It ends when the sign is strictly opposite to its side, and the same batch opens the new side.
  It also ends when both legs are flat. A net zero with a leg still held (dust offset by a
  futures short) keeps it open, and so does dust alone. Both tests run once per batch, after all
  its fills, never between two of them, so a full spot-to-futures move stays one lifecycle.
* **Which fills belong to which lifecycle.** All of a batch's fills go to the lifecycle that
  receives them, except in a sign change. There, a fill that reduces a leg that is held belongs to
  the lifecycle that ends, and a fill that opens or extends a leg belongs to the one that begins
  (the fees and the venue figures follow the fills; the P&L of an opening fill is 0). Dust left
  by a short's closing is long, so it ends the short and is a long lifecycle of its own.
* **P&L.** ``gross_pnl`` is the realised P&L of the lifecycle's fills (each fill comes with the
  figure ``Ledger.fill`` gave it), before fees and funding, plus the unrealised P&L when the
  lifecycle is censored. ``fees`` is the sum of the fills' fees and ``funding`` the signed sum
  of the funding passed (positive credits the wallet), so ``gross_pnl - fees + funding`` is the
  net. ``best_unrealised`` is the maximum, over the marks passed to ``mark``, of the gross
  realised P&L so far plus that mark's unrealised P&L, and ``given_back`` is ``best_unrealised -
  gross_pnl``. The caller passes the hourly open mark of the combined position (Ruling R6), and
  a stop or window-end mark just before ``censor``; every ``mark`` counts. Neither figure is
  clamped: ``given_back`` is negative when the exit beats every mark. A lifecycle that no mark
  ever saw (opened and closed within one hour) has ``best_unrealised == gross_pnl``.
* **Censoring.** ``censor`` ends every open lifecycle at once, with ``censored=True`` and the last
  unrealised P&L passed to ``mark``. A lifecycle whose position changed since that mark has no
  usable value, so ``censor`` refuses it. With reason ``window end`` a lifecycle whose last batch
  left only dust is labelled ``window end (dust)``; a stop keeps its own reason.
* **Venues.** ``venues`` lists, per venue, the bought and sold quantities in that venue's units,
  the fees and the realised P&L, and for futures the funding. Both venues are always present.

Amounts are exact ``Fraction``s inside and exact Decimals out. Every call checks all its input
before it changes any state, so a refused call leaves the lifecycles as they were. Calls share one
clock, which may not go backwards; several calls may share an hour.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Literal

from crypto_grid_bot.v4.engine.ledger import Fill, Venue
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.numbers import to_decimal, to_fraction

Side = Literal["long", "short"]

EXIT_REASONS: tuple[str, ...] = (
    "signal",
    "universe exit",
    "funding-month exit",
    "margin cut",
    "ceiling cut",
    "delisting",
    "window end",
    "window end (dust)",
    "liquidation",
    "limit_unrestorable",
)
# A batch of fills can end a lifecycle with these. The two stops and the dust label are not
# fill-driven: a stop ends the cell without a fill, and the dust label is derived by ``censor``.
_BATCH_REASONS: tuple[str, ...] = EXIT_REASONS[:7]
_CENSOR_REASONS: tuple[str, ...] = ("window end", "liquidation", "limit_unrestorable")
_DUST_LABEL = "window end (dust)"

# The V4 data layer's symbol pattern (ruling R7).
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")

_ZERO = Fraction(0)
_SIDES: dict[int, Side] = {1: "long", -1: "short"}


@dataclass(frozen=True, slots=True)
class Lifecycle:
    """One ended or censored trade of one coin on one side.

    ``venues`` maps each venue to ``bought_quantity``, ``sold_quantity``, ``fees`` and
    ``realised_pnl``, and for ``futures`` also ``funding``. ``unrealised`` is 0 for a lifecycle
    closed by fills and, for a censored one, its unrealised P&L at the censoring mark (which
    ``gross_pnl`` includes). ``holding_hours`` is ``(exit_ms - entry_ms) // 1 hour``.
    """

    coin: str
    side: Side
    entry_ms: int
    exit_ms: int
    exit_reason: str
    gross_pnl: Decimal
    fees: Decimal
    funding: Decimal
    best_unrealised: Decimal
    given_back: Decimal
    holding_hours: int
    censored: bool
    venues: Mapping[Venue, Mapping[str, Decimal]]
    unrealised: Decimal = Decimal(0)


@dataclass(slots=True)
class _Leg:
    """One venue's running figures inside an open lifecycle."""

    bought: Fraction = _ZERO
    sold: Fraction = _ZERO
    fees: Fraction = _ZERO
    realised: Fraction = _ZERO
    funding: Fraction = _ZERO


def _new_legs() -> dict[Venue, _Leg]:
    return {"spot": _Leg(), "futures": _Leg()}


@dataclass(slots=True)
class _Open:
    """An open lifecycle. ``spot`` and ``futures`` are the legs after the last batch;
    ``unrealised`` is the last mark since that batch, or None when there is none."""

    side: int
    entry_ms: int
    spot: Fraction
    futures: Fraction
    dust_only: bool
    legs: dict[Venue, _Leg] = field(default_factory=_new_legs)
    best: Fraction | None = None
    unrealised: Fraction | None = None

    def realised(self) -> Fraction:
        return self.legs["spot"].realised + self.legs["futures"].realised

    def add(self, fill: Fill, realised: Fraction) -> None:
        leg = self.legs[fill.venue]
        quantity = to_fraction(fill.quantity)
        if fill.side > 0:
            leg.bought += quantity
        else:
            leg.sold += quantity
        leg.fees += to_fraction(fill.fee)
        leg.realised += realised

    def mark(self, unrealised: Fraction) -> None:
        self.unrealised = unrealised
        value = self.realised() + unrealised
        if self.best is None or value > self.best:
            self.best = value

    def finish(self, coin: str, exit_ms: int, reason: str, *, censored: bool) -> Lifecycle:
        unrealised = (self.unrealised or _ZERO) if censored else _ZERO
        gross = self.realised() + unrealised
        best = gross if self.best is None else self.best
        spot, futures = self.legs["spot"], self.legs["futures"]
        venues: dict[Venue, Mapping[str, Decimal]] = {
            "spot": MappingProxyType(
                {
                    "bought_quantity": to_decimal(spot.bought),
                    "sold_quantity": to_decimal(spot.sold),
                    "fees": to_decimal(spot.fees),
                    "realised_pnl": to_decimal(spot.realised),
                }
            ),
            "futures": MappingProxyType(
                {
                    "bought_quantity": to_decimal(futures.bought),
                    "sold_quantity": to_decimal(futures.sold),
                    "fees": to_decimal(futures.fees),
                    "realised_pnl": to_decimal(futures.realised),
                    "funding": to_decimal(futures.funding),
                }
            ),
        }
        return Lifecycle(
            coin=coin,
            side=_SIDES[self.side],
            entry_ms=self.entry_ms,
            exit_ms=exit_ms,
            exit_reason=reason,
            gross_pnl=to_decimal(gross),
            fees=to_decimal(spot.fees + futures.fees),
            funding=to_decimal(futures.funding),
            best_unrealised=to_decimal(best),
            given_back=to_decimal(best - gross),
            holding_hours=(exit_ms - self.entry_ms) // HOUR_MS,
            censored=censored,
            venues=MappingProxyType(venues),
            unrealised=to_decimal(unrealised),
        )


class Lifecycles:
    """The open lifecycles of all coins, fed batch by batch by the hour loop."""

    def __init__(self) -> None:
        self._open: dict[str, _Open] = {}
        self._perpetual: dict[str, str] = {}
        self._last_ms = -1

    def after_batch(
        self,
        hour_ms: int,
        coin: str,
        signed_notional: Decimal,
        spot_qty: Decimal,
        futures_qty: Decimal,
        dust_only: bool,
        fills: Sequence[tuple[Fill, Decimal]],
        reason: str,
    ) -> Lifecycle | None:
        """Report one whole batch of a coin's fills and apply the opening and ending tests.

        ``signed_notional`` is the coin's notional over both venues after the batch (positive
        long) and ``spot_qty`` and ``futures_qty`` are the legs after it, in the venues' units
        (``Ledger.quantity``). ``dust_only`` says the coin holds only unsellable spot dust.
        ``fills`` are the batch's fills in order, each with the realised P&L ``Ledger.fill``
        returned, and ``reason`` is the batch's: it becomes the exit reason of a lifecycle the
        batch ends. Returns the lifecycle that ended, or None. A sign change returns the ended
        one and opens the other at ``hour_ms``.

        The fills must carry the coin's spot symbol on spot and one perpetual symbol on
        futures, and must move the legs from what the last batch left to what is passed here.
        """
        hour = self._time(hour_ms)
        name = _symbol(coin, "coin")
        notional = _amount(signed_notional, "signed_notional", signed=True)
        spot = _amount(spot_qty, "spot_qty")
        futures = _amount(futures_qty, "futures_qty", signed=True)
        if type(dust_only) is not bool:
            raise ValueError(f"dust_only must be a bool, got {dust_only!r:.40}")
        if not isinstance(reason, str) or reason not in _BATCH_REASONS:
            raise ValueError(f"a batch reason must be one of {_BATCH_REASONS}, got {reason!r:.40}")
        entries, perpetual = self._entries(fills, name)
        flat = spot == 0 and futures == 0
        sign = (notional > 0) - (notional < 0)
        _check_legs(name, spot, futures, sign, dust_only)
        held = self._open.get(name)
        before = (held.spot, held.futures) if held is not None else (_ZERO, _ZERO)
        closing = _replay(name, entries, before, (spot, futures))

        if held is None:
            if flat:
                if entries:
                    raise ValueError(
                        f"{name} has no open lifecycle and is flat after the batch, so its "
                        f"{len(entries)} fills would be lost: a batch may not open and close"
                    )
                self._commit(hour, name, perpetual)
                return None
            if sign == 0:
                raise ValueError(
                    f"{name} would open a lifecycle with a net notional of 0, so it has no side"
                )
            fresh = _Open(sign, hour, spot, futures, dust_only)
            for fill, realised in entries:
                fresh.add(fill, realised)
            self._commit(hour, name, perpetual)
            self._open[name] = fresh
            return None

        if flat or sign == -held.side:
            # The lifecycle ends. After a sign change, only the fills that reduce a held leg are
            # its own; the rest begin the new side. When both legs are flat, all are its own.
            begun = None if flat else _Open(sign, hour, spot, futures, dust_only)
            for (fill, realised), reduces in zip(entries, closing, strict=True):
                if begun is None or reduces:
                    held.add(fill, realised)
                else:
                    begun.add(fill, realised)
            ended = held.finish(name, hour, reason, censored=False)
            self._commit(hour, name, perpetual)
            if begun is None:
                del self._open[name]
            else:
                self._open[name] = begun
            return ended

        for fill, realised in entries:
            held.add(fill, realised)
        if entries:
            held.unrealised = None  # the position changed: the last mark no longer describes it
        held.spot, held.futures, held.dust_only = spot, futures, dust_only
        self._commit(hour, name, perpetual)
        return None

    def funding(self, coin: str, amount: Decimal) -> None:
        """Add one signed funding ``amount`` (positive credits the wallet) to the coin's open
        lifecycle, under the futures venue. A coin with no open lifecycle is refused."""
        name = _symbol(coin, "coin")
        value = _amount(amount, "amount", signed=True)
        held = self._open.get(name)
        if held is None:
            raise ValueError(f"funding for {name}, which has no open lifecycle")
        held.legs["futures"].funding += value

    def mark(self, hour_ms: int, coin: str, unrealised: Decimal) -> None:
        """Record the coin's unrealised P&L over both venues at this hour (the open mark of the
        combined position). It counts toward ``best_unrealised`` and is the value ``censor``
        uses until the next batch that has fills."""
        hour = self._time(hour_ms)
        name = _symbol(coin, "coin")
        value = _amount(unrealised, "unrealised", signed=True)
        held = self._open.get(name)
        if held is None:
            raise ValueError(f"a mark for {name}, which has no open lifecycle")
        held.mark(value)
        self._last_ms = hour

    def censor(self, hour_ms: int, reason: str) -> tuple[Lifecycle, ...]:
        """End every open lifecycle at ``hour_ms`` as censored, with ``reason`` (``window end``,
        ``liquidation`` or ``limit_unrestorable``) and the unrealised P&L of its last mark. With
        ``window end`` a lifecycle left with only dust is labelled ``window end (dust)``. Returns
        them sorted by coin; every lifecycle must have been marked since its last batch."""
        hour = self._time(hour_ms)
        if not isinstance(reason, str) or reason not in _CENSOR_REASONS:
            raise ValueError(
                f"a censoring reason must be one of {_CENSOR_REASONS}, got {reason!r:.40}"
            )
        for name in sorted(self._open):
            if self._open[name].unrealised is None:
                raise ValueError(
                    f"the open lifecycle of {name} has no mark since its last batch; "
                    "pass its unrealised P&L to mark() first"
                )
        ended = tuple(
            held.finish(
                name,
                hour,
                _DUST_LABEL if reason == "window end" and held.dust_only else reason,
                censored=True,
            )
            for name, held in sorted(self._open.items())
        )
        self._open.clear()
        self._last_ms = hour
        return ended

    def _time(self, hour_ms: object) -> int:
        if type(hour_ms) is not int or hour_ms < 0:
            raise ValueError(f"hour_ms must be a non-negative int (ms), got {hour_ms!r:.40}")
        if hour_ms < self._last_ms:
            raise ValueError(f"time may not go backwards: {hour_ms} < {self._last_ms}")
        return hour_ms

    def _commit(self, hour: int, coin: str, perpetual: str | None) -> None:
        self._last_ms = hour
        if perpetual is not None:
            self._perpetual[coin] = perpetual

    def _entries(self, fills: object, coin: str) -> tuple[list[tuple[Fill, Fraction]], str | None]:
        """The batch's fills with their exact realised P&L, and the perpetual symbol they carry
        (None with no futures fill). Checks the symbols against the coin."""
        if not isinstance(fills, Sequence) or isinstance(fills, str | bytes):
            raise ValueError(f"fills must be a sequence of (Fill, realised P&L), got {fills!r:.40}")
        known = self._perpetual.get(coin)
        entries: list[tuple[Fill, Fraction]] = []
        for item in fills:
            if not (isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], Fill)):
                raise ValueError(f"each fill must be a (Fill, realised P&L) pair, got {item!r:.60}")
            fill, realised = item
            entries.append((fill, _amount(realised, "realised P&L", signed=True)))
            if fill.venue == "spot":
                if fill.symbol != coin:
                    raise ValueError(f"a spot fill of {fill.symbol} does not belong to {coin}")
            elif known is None:
                known = fill.symbol
            elif fill.symbol != known:
                raise ValueError(
                    f"{coin}'s perpetual is {known}, but a futures fill carries {fill.symbol}"
                )
        perpetual = known if known != self._perpetual.get(coin) else None
        return entries, perpetual


def _replay(
    coin: str,
    entries: Sequence[tuple[Fill, Fraction]],
    before: tuple[Fraction, Fraction],
    after: tuple[Fraction, Fraction],
) -> list[bool]:
    """Walk the fills from the legs before the batch and require them to end at the legs passed.
    Returns, per fill, whether it reduces a leg that is held."""
    quantity = {"spot": before[0], "futures": before[1]}
    reduces: list[bool] = []
    for fill, _ in entries:
        held = quantity[fill.venue]
        new = held + fill.side * to_fraction(fill.quantity)
        if fill.venue == "spot" and new < 0:
            raise ValueError(f"a spot sell of {fill.quantity} {coin} exceeds the held {held}")
        if held * new < 0:
            raise ValueError(
                f"a futures fill of {fill.side * fill.quantity} {fill.symbol} crosses zero from "
                f"{held}; a flip is a close and an open"
            )
        reduces.append(held != 0 and abs(new) < abs(held))
        quantity[fill.venue] = new
    if (quantity["spot"], quantity["futures"]) != after:
        raise ValueError(
            f"the fills of {coin} take its legs to spot {quantity['spot']} and futures "
            f"{quantity['futures']}, but spot {after[0]} and futures {after[1]} were passed"
        )
    return reduces


def _check_legs(coin: str, spot: Fraction, futures: Fraction, sign: int, dust_only: bool) -> None:
    """The legs, the notional's sign and the dust flag must agree."""
    if spot == 0 and futures == 0:
        if sign != 0:
            raise ValueError(f"{coin} is flat but its signed notional is not 0")
    elif futures == 0:
        if sign <= 0:
            raise ValueError(f"{coin} holds only a long spot leg, but its notional is not positive")
    elif spot == 0 and sign != (futures > 0) - (futures < 0):
        raise ValueError(f"{coin} holds only a futures leg, but its notional has the other sign")
    if dust_only and not (spot > 0 and futures == 0):
        raise ValueError(f"{coin} is marked dust only, so it must hold a spot leg and no futures")


def _symbol(value: object, what: str) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{what} must match [A-Z0-9]{{2,30}}, got {value!r:.40}")
    return value


def _amount(value: object, what: str, *, signed: bool = False) -> Fraction:
    """The exact value of a finite Decimal, which may not be negative unless ``signed``."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} must be a finite Decimal, got {value!r:.40}")
    if not signed and value < 0:
        raise ValueError(f"{what} must not be negative, got {value}")
    return to_fraction(value)
