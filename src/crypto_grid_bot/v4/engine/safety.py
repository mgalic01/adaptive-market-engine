"""The safety rules of V4 as pure helpers: liquidation on the futures backing, adverse-extreme
prices, the margin-cushion and 3x-ceiling cut factors, dead markets, the 10% penalised price and
the funding-month exit hour.

Implements the spec's "Safety" (the 3x ceiling, futures margin, the margin cushion, liquidation,
delisting or a dead market) and, from "Data", the timing of a funding-month close. The hour loop
composes these helpers in the order of "Order of events in an hour"; nothing here holds a
ledger, books a fill or reads the clock.

* **Thresholds are exact.** ``liquidated`` (``maintenance > 0 and backing <= maintenance``),
  ``cushion_breached`` (``maintenance > 0 and backing < 3 x maintenance``) and
  ``ceiling_breached`` (``gross_notional > 3 x equity``) compare the Mark's exact Decimals,
  never its 60-digit ``ratio`` or ``gross`` (V3.1's ``futures_margin`` advises the same). With
  equity at or below zero, any gross notional is a breach; with none there is nothing to cut.
* **The cut factors** are ``k = (backing / 4 - untradable maintenance) / tradable maintenance``
  and ``k' = (2.7 x equity - untradable gross) / tradable gross``. Each is the exact quotient
  truncated toward zero to ``CONTEXT.prec`` significant digits, so it is never rounded up and a
  leg cut to ``held x k`` and floored to its step cannot end above the exact target. A caller
  must multiply ``held x k`` exactly (or truncate it), never in a 60-digit context that rounds.
  A factor at or below 0 is returned as it is and means "close every tradable position"; None
  means nothing is tradable, so the limit cannot be restored.
* **Adverse prices** put every held leg at its bar's extreme against it at once: a long (every
  spot leg, and a positive futures quantity) at the low, a short at the high. A leg whose hour is
  masked has no bar and takes its carried mark.
* **Dead markets.** ``DeadMarkets`` is told, hour by hour, whether each held leg's own venue had
  a bar. A leg is due to close at hour ``h`` when none of the 168 hours ``[h - 168 h, h)`` had
  one, whether or not hour ``h`` has a bar. It keeps one number per leg, the open of its last
  bar, and answers ``due(h)`` from that alone, so it learns nothing about hour ``h`` or later
  (``due(h)`` is refused once a leg has been observed at ``h``). It agrees with the store's own
  answer, ``last_open_at_or_before(h - 1) < h - 168 h``, which the tests check.
* **Funding-month exit hour.** The fill hour of a futures close before an incomplete funding
  month. ``funding_exit_hour`` reads only which perpetual hours have a bar, between the decision
  and the month's first midnight; the month's status is the spec's disclosed look-ahead.

Synthetic closes at one instant form one batch that the loop values at ``penalised_price``
together with ``Ledger.mark`` and ``liquidated``; the outcome ``limit_unrestorable`` (reasons
``ceiling``, ``margin_cushion`` and ``required_fill``) is the loop's to record.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Mapping
from decimal import ROUND_DOWN, Context, Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Literal, get_args

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.v4.engine.arms import (
    CEILING,
    CEILING_TARGET,
    CUSHION_FLOOR,
    CUSHION_TARGET,
    DEAD_MARKET_HOURS,
    DEAD_MARKET_PENALTY,
)
from crypto_grid_bot.v4.engine.ledger import Mark, Venue
from crypto_grid_bot.v4.engine.market import HOUR_MS, HourBar, Market
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_decimal, to_fraction

_Key = tuple[Venue, str]
_VENUES: tuple[str, ...] = get_args(Venue)

# The V4 data layer's symbol pattern (ruling R7).
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")
_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")

# Quotients are cut toward zero, never rounded, at the engine's precision.
_TRUNCATE = Context(prec=CONTEXT.prec, rounding=ROUND_DOWN)
_CEILING = to_fraction(CEILING)
_CEILING_TARGET = to_fraction(CEILING_TARGET)
_PENALTY = to_fraction(DEAD_MARKET_PENALTY)
# The fill of a funding-month close is 01:00 UTC of the previous month's last day: 23 hours
# before the month's first midnight.
_EXIT_LEAD_MS = 23 * HOUR_MS


# --- the account checks ---------------------------------------------------------------------


def liquidated(mark: Mark) -> bool:
    """Whether the account is liquidated at ``mark``: there is a futures position and backing is
    at or below maintenance."""
    checked = _mark(mark)
    return checked.maintenance > 0 and checked.backing <= checked.maintenance


def cushion_breached(mark: Mark) -> bool:
    """Whether the margin ratio is below 3 at ``mark``: there is a futures position and backing
    is below 3 x maintenance. A ratio of exactly 3 is not a breach."""
    checked = _mark(mark)
    return checked.maintenance > 0 and to_fraction(checked.backing) < CUSHION_FLOOR * to_fraction(
        checked.maintenance
    )


def ceiling_breached(mark: Mark) -> bool:
    """Whether gross exposure is above 3 x equity at ``mark``. With equity at or below zero any
    gross notional is a breach; with no gross notional there is none."""
    checked = _mark(mark)
    gross = to_fraction(checked.gross_notional)
    return gross > 0 and gross > _CEILING * to_fraction(checked.equity)


def adverse_prices(
    held: Mapping[tuple[Venue, str], Decimal],
    bars: Mapping[tuple[Venue, str], HourBar | None],
    carried: Mapping[tuple[Venue, str], Decimal],
) -> Mapping[tuple[Venue, str], Decimal]:
    """The price of every held leg at the bar's extreme against it, all at once.

    ``held`` maps each open leg to its signed quantity (spot is positive). A long takes its own
    venue's bar low and a short its high. A leg whose entry in ``bars`` is None (a masked hour)
    takes its ``carried`` mark; that mark must be there. A held leg with no entry in ``bars`` at
    all is refused, so a forgotten lookup is never read as a masked hour. Entries of ``bars``
    and ``carried`` for legs that are not held are ignored. The result is read-only, in
    (venue, symbol) order.
    """
    if not (
        isinstance(held, Mapping) and isinstance(bars, Mapping) and isinstance(carried, Mapping)
    ):
        raise ValueError("held, bars and carried must be mappings keyed by (venue, symbol)")
    keys = sorted(_key_of(key) for key in held)
    prices: dict[_Key, Decimal] = {}
    for key in keys:
        venue, symbol = key
        quantity = _amount(held[key], f"the held quantity of the {venue} leg {symbol}", signed=True)
        if quantity == 0:
            raise ValueError(
                f"the {venue} leg {symbol} is held with quantity 0; it must be nonzero"
            )
        if venue == "spot" and quantity < 0:
            raise ValueError(f"the spot leg {symbol} has a negative quantity; spot is long only")
        if key not in bars:
            raise ValueError(
                f"bars has no entry for the held {venue} leg {symbol} (None marks a masked hour)"
            )
        bar = bars[key]
        if bar is None:
            if key not in carried:
                raise ValueError(f"no carried mark for the masked {venue} leg {symbol}")
            mark = carried[key]
            _amount(mark, f"the carried mark of the {venue} leg {symbol}", positive=True)
            prices[key] = mark
        elif isinstance(bar, HourBar):
            prices[key] = bar.low if quantity > 0 else bar.high
        else:
            raise ValueError(f"the bar of the {venue} leg {symbol} must be a HourBar or None")
    return MappingProxyType(prices)


# --- the cut factors ------------------------------------------------------------------------


def cushion_factor(
    backing: Decimal, untradable_maintenance: Decimal, tradable_maintenance: Decimal
) -> Decimal | None:
    """``k = (backing / 4 - untradable maintenance) / tradable maintenance``, cut toward zero to
    60 significant digits: the factor that brings the margin ratio back to 4 before fees when
    every tradable futures position is cut to ``held x k``. None when no maintenance is tradable
    (the cushion cannot be restored). A ``k`` at or below 0 is returned as it is and means close
    every tradable futures position."""
    available = _amount(backing, "backing", signed=True)
    untradable = _amount(untradable_maintenance, "untradable_maintenance")
    tradable = _amount(tradable_maintenance, "tradable_maintenance")
    if tradable == 0:
        return None
    return _truncate((available / CUSHION_TARGET - untradable) / tradable)


def ceiling_factor(
    equity: Decimal, untradable_gross: Decimal, tradable_gross: Decimal
) -> Decimal | None:
    """``k' = (2.7 x equity - untradable gross) / tradable gross``, cut toward zero to 60
    significant digits: the factor that brings gross exposure back to 2.7 x equity before fees
    when every tradable position is cut to ``held x k'``. None when no gross is tradable (the
    limit cannot be restored). A ``k'`` at or below 0 is returned as it is and means close every
    tradable position."""
    available = _amount(equity, "equity", signed=True)
    untradable = _amount(untradable_gross, "untradable_gross")
    tradable = _amount(tradable_gross, "tradable_gross")
    if tradable == 0:
        return None
    return _truncate((_CEILING_TARGET * available - untradable) / tradable)


# --- dead markets ---------------------------------------------------------------------------


class DeadMarkets:
    """Which held legs have gone 168 hours without a bar on their own venue.

    ``observe`` records one leg's hour, with a bar or without, and the loop does it for every
    held leg each hour, after asking ``due`` for that hour. ``due(h)`` lists the observed legs
    with no bar in any of the 168 hours before ``h``. A leg that was never observed is never
    listed. A leg first observed without a bar counts from that hour: nothing is known before it,
    so 168 observed misses are needed. ``forget`` ends a leg's record when its position closes.
    """

    __slots__ = ("_legs",)

    def __init__(self) -> None:
        # Per leg: the last observed hour, and the reference hour, which is the open of its last
        # bar (or the hour before the first observation, if no bar was seen).
        self._legs: dict[_Key, tuple[int, int]] = {}

    def observe(self, hour_ms: int, venue: Venue, symbol: str, has_bar: bool) -> None:
        """Record that the leg's venue had (or lacked) a bar in the hour that opens at
        ``hour_ms``. A leg's hours must come in increasing order."""
        hour = _hour(hour_ms, "hour_ms")
        key = (_venue(venue), _symbol(symbol, "symbol"))
        if type(has_bar) is not bool:
            raise ValueError(f"has_bar must be a bool, got {has_bar!r:.40}")
        seen = self._legs.get(key)
        if seen is None:
            self._legs[key] = (hour, hour if has_bar else hour - HOUR_MS)
            return
        last_hour, reference = seen
        if hour <= last_hour:
            raise ValueError(
                f"observations of {key[0]} {key[1]} must come in hourly order: "
                f"{hour} is not after {last_hour}"
            )
        self._legs[key] = (hour, hour if has_bar else reference)

    def due(self, hour_ms: int) -> tuple[tuple[Venue, str], ...]:
        """The legs due to close at the hour that opens at ``hour_ms``: no bar in any hour of
        ``[hour_ms - 168 h, hour_ms)``. Sorted by symbol, spot before futures. Asking about an
        hour that a leg has already been observed in is refused, since it would see that hour."""
        now = _hour(hour_ms, "hour_ms")
        for key, (last_hour, _) in self._legs.items():
            if last_hour >= now:
                raise ValueError(
                    f"hour {now} is already observed for {key[0]} {key[1]} (up to {last_hour}); "
                    "ask before observing the hour"
                )
        limit = now - DEAD_MARKET_HOURS * HOUR_MS
        return tuple(
            sorted((key for key, (_, ref) in self._legs.items() if ref < limit), key=_order)
        )

    def forget(self, venue: Venue, symbol: str) -> None:
        """Drop the leg's record (its position closed). A leg that is not there is ignored."""
        self._legs.pop((_venue(venue), _symbol(symbol, "symbol")), None)


def penalised_price(last_close: Decimal, side_held: int) -> Decimal:
    """The synthetic close price of a dead market: ``last_close x (1 - 0.10)`` for a long
    (``side_held`` +1) and ``x (1 + 0.10)`` for a short (-1), exact."""
    close = _amount(last_close, "last_close", positive=True)
    if type(side_held) is not int or side_held not in (1, -1):
        raise ValueError(f"side_held must be +1 (long) or -1 (short), got {side_held!r:.40}")
    return to_decimal(close * (1 - _PENALTY if side_held > 0 else 1 + _PENALTY))


# --- the funding-month exit -----------------------------------------------------------------


def funding_exit_hour(market: Market, coin: str, month: str) -> int | Literal["synthetic"]:
    """The open (ms) of the hour that fills the futures close before the incomplete funding
    ``month`` (``"YYYY-MM"``) of ``coin``: 01:00 UTC on the previous month's last day if the
    perpetual has a bar there, else the first perpetual bar after that hour and before the
    month's first midnight, else ``"synthetic"``, a close at 00:00 of the month's first day.

    Only the existence of bars is read, up to the month's first midnight. The month's status is
    not checked: the caller knows which months are incomplete. A coin without a perpetual, or
    one the packs do not know, is a ValueError.
    """
    if not isinstance(month, str) or _MONTH.fullmatch(month) is None:
        raise ValueError(f"month must be YYYY-MM, got {month!r:.40}")
    perpetual = market.coin(coin).perpetual
    if perpetual is None:
        raise ValueError(f"{coin} has no perpetual, so it has no funding-month exit")
    month_start = month_bounds_ms(month)[0]
    fill = month_start - _EXIT_LEAD_MS
    store = perpetual.store
    if store.bar(fill) is not None:
        return fill
    opens = store.opens()
    index = bisect_right(opens, fill)
    if index < len(opens) and opens[index] < month_start:
        return int(opens[index])
    return "synthetic"


# --- helpers --------------------------------------------------------------------------------


def _truncate(value: Fraction) -> Decimal:
    """``value`` cut toward zero to ``CONTEXT.prec`` significant digits (exact when it fits)."""
    return _TRUNCATE.divide(Decimal(value.numerator), Decimal(value.denominator))


def _order(key: _Key) -> tuple[str, bool]:
    """Symbol order, with a coin's spot leg before its futures leg."""
    return key[1], key[0] != "spot"


def _mark(value: object) -> Mark:
    if not isinstance(value, Mark):
        raise ValueError(f"a Mark is required, got {value!r:.60}")
    return value


def _venue(value: object) -> Venue:
    if isinstance(value, str):
        if value == "spot":
            return "spot"
        if value == "futures":
            return "futures"
    raise ValueError(f"venue must be one of {_VENUES}, got {value!r:.40}")


def _symbol(value: object, what: str) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{what} must match [A-Z0-9]{{2,30}}, got {value!r:.40}")
    return value


def _key_of(value: object) -> _Key:
    if not isinstance(value, tuple) or len(value) != 2:
        raise ValueError(f"a leg is a (venue, symbol) tuple, got {value!r:.60}")
    return _venue(value[0]), _symbol(value[1], "symbol")


def _hour(value: object, what: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{what} must be a non-negative int (ms), got {value!r:.40}")
    if value % HOUR_MS:
        raise ValueError(f"{what} {value} is not on an hour")
    return value


def _amount(value: object, what: str, *, positive: bool = False, signed: bool = False) -> Fraction:
    """The exact value of a finite Decimal: positive, signed, or (the default) at least 0."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} must be a finite Decimal, got {value!r:.40}")
    if positive and value <= 0:
        raise ValueError(f"{what} must be positive, got {value}")
    if not positive and not signed and value < 0:
        raise ValueError(f"{what} must not be negative, got {value}")
    return to_fraction(value)
