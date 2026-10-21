"""The spot-first allocation of V4's targets and the cash clip of its increases.

Implements the spec's "Account and execution: one shared account" (the bullets "Longs on spot
first, coin by coin" and its cash clip) and the admission rule of "Safety" (the margin
cushion). Both are pure functions: they see no ledger, no market and no clock.

* **Allocation.** ``allocate`` splits each trading coin's target between spot and futures, in
  USDT notional at the fill hour's unslipped opens. The coins that keep their legs (deferred,
  no-bar, band-kept) keep them as held, a leg that a mandatory exit closes counting as 0, and
  they enter the room ``R = 0.98 x equity - S_K - D - F_K / 3`` as fixed holdings. The split
  runs on ``residual = target - dust``: positive residuals are longs (E when the coin has an
  eligible perpetual, N when it is spot-only), negative ones are shorts on futures (a spot-only
  coin's negative residual is 0). Spot capacity is ``s_max = max(0, min(G_L, 1.5 x (R - (G_L +
  G_S) / 3)))``. If ``s_max >= G_N`` the N coins are fully on spot and the E coins share
  ``s_max - G_N`` of spot pro rata to their residuals; otherwise the E coins are fully on
  futures and the N coins scale by ``k = max(0, R - (G_E + G_S) / 3) / G_N``, capped at 1.
  Nothing is redistributed, and nothing here scales the E coins to the room: when they do not
  fit, the cash clip bounds them.
* **Cash clip.** ``clip_increases`` takes the increases in the order given (alphabetical by
  symbol, the spot leg before the futures leg within a coin: the caller's order) and admits
  to each the largest notional that keeps both terms of free cash at or above 0 after the
  increase's own effect, so no increase takes the margin ratio below 4 and none is made while
  it is below 4. The terms are ``cash - open initial margin`` (1) and ``backing - 4 x
  maintenance`` (2). With ``n`` the notional at the unslipped open, ``s`` the slippage rate
  and ``f`` the fee rate of the venue:

  - a spot buy consumes ``n (1 + s)(1 + f)`` from both terms (spend plus fee);
  - a futures increase consumes ``n / 3 + n (1 + s) f`` from term 1 (the initial margin it
    adds and its fee), and ``n (1 + s) f + n s + 4 x 0.01 n`` from term 2 (its fee, its
    slippage loss when marked at the open, and 4 times the maintenance it adds). A short's fee
    is on a price below the open, so the figure is a safe upper bound for it.

  Cash, initial margin, backing and maintenance are updated by what was admitted before the
  next increase. The result keeps the input order and its zeros, so the caller can record
  each cut; the caller converts the admitted notional to a quantity, rounds it to the step and
  skips an increase that is now below the filters.
* **Venue units.** ``to_venue_quantity`` is ``notional / price`` in the venue's own units,
  truncated toward zero to ``CONTEXT.prec`` significant digits (and to 100 decimal places, the
  bound of the order helpers), so a later floor to the step never exceeds the true quotient.
  On a multiplier perpetual (1000SHIBUSDT) ``price`` is the contract price, already
  ``multiplier`` times the coin's.

``allocate`` computes under ``CONTEXT``. The clip does its arithmetic in exact ``Fraction``s,
so that an admitted amount can never leave a term below 0 by a rounding, and returns Decimals
truncated toward zero.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, Context, Decimal, localcontext
from fractions import Fraction
from types import MappingProxyType
from typing import get_args

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.v4.engine.arms import (
    COST_RESERVE,
    CUSHION_TARGET,
    INITIAL_MARGIN_DIVISOR,
    MAINTENANCE_RATE,
)
from crypto_grid_bot.v4.engine.ledger import Venue
from crypto_grid_bot.v4.engine.numbers import CONTEXT, to_fraction

# The V4 data layer's symbol pattern (ruling R7).
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")
_VENUES: tuple[str, ...] = get_args(Venue)

# Bounds of the amounts taken in: |value| below 1e37 and at most 1000 decimal places (a split
# can leave many digits on a tiny share, and the exact arithmetic here must stay small).
_MAX_ADJUSTED = 36
_MIN_INPUT_EXPONENT = -1000
# What is handed on to the order helpers: at most 100 decimal places, as they require.
_MAX_DECIMALS = 100

# The spot capacity factor of the spec: with spot s and the rest on futures at 1/3 initial
# margin, s + (G_L - s + G_S) / 3 <= R gives s <= 1.5 x (R - (G_L + G_S) / 3).
SPOT_CAPACITY_FACTOR = Decimal("1.5")

_ZERO = Decimal(0)
_ONE = Decimal(1)
_MARGIN_DIVISOR = Decimal(INITIAL_MARGIN_DIVISOR)
# Quotients are cut toward zero, never rounded, at the engine's precision.
_TRUNCATE = Context(prec=CONTEXT.prec, rounding=ROUND_DOWN)
_QUANTUM = Decimal(1).scaleb(-_MAX_DECIMALS)


@dataclass(frozen=True, slots=True)
class CoinState:
    """One coin at the fill hour, amounts in USDT notional at the unslipped opens.

    ``target_notional`` is the signed target. ``spot_notional`` is the held spot, dust
    excluded; ``dust_notional`` the unsellable spot dust; ``futures_notional`` the signed
    held futures. ``eligible`` is True when the coin has a perpetual. ``keeps_legs`` marks a
    coin that keeps its legs as held (deferred, no-bar or band-kept); ``exiting_legs`` are
    the legs a mandatory exit closes this hour, which count as 0 for such a coin.
    """

    coin: str
    target_notional: Decimal
    spot_notional: Decimal
    dust_notional: Decimal
    futures_notional: Decimal
    eligible: bool
    keeps_legs: bool
    exiting_legs: frozenset[Venue]

    def __post_init__(self) -> None:
        _symbol(self.coin, "coin")
        _check(self.target_notional, "target_notional", signed=True)
        _check(self.spot_notional, "spot_notional")
        _check(self.dust_notional, "dust_notional")
        _check(self.futures_notional, "futures_notional", signed=True)
        if type(self.eligible) is not bool:
            raise ValueError(f"eligible must be a bool, got {self.eligible!r:.40}")
        if type(self.keeps_legs) is not bool:
            raise ValueError(f"keeps_legs must be a bool, got {self.keeps_legs!r:.40}")
        if not isinstance(self.exiting_legs, frozenset) or not all(
            leg in _VENUES for leg in self.exiting_legs
        ):
            raise ValueError(
                f"exiting_legs must be a frozenset of {_VENUES}, got {self.exiting_legs!r:.60}"
            )


@dataclass(frozen=True, slots=True)
class LegTargets:
    """A coin's target notional on each venue: ``spot`` (dust excluded, never negative; the
    caller adds the coin's dust back when it plans the spot leg) and signed ``futures``."""

    spot: Decimal
    futures: Decimal

    def __post_init__(self) -> None:
        _check(self.spot, "spot")
        _check(self.futures, "futures", signed=True)


def allocate(equity: Decimal, coins: Sequence[CoinState]) -> Mapping[str, LegTargets]:
    """The spot and futures targets of every coin given, in USDT notional.

    The result has one entry per coin, in the input order. A coin that keeps its legs gets
    its held legs (an exiting leg 0). A spot-only coin never gets futures. ``exiting_legs``
    matters only to the coins that keep their legs: a trading coin is re-targeted whole, and
    its closing fills in the same batch. ``equity`` is the equity at the fill hour's opens
    before the hour's fills; a negative room is allowed and gives no spot beyond the fixed
    holdings.
    """
    _check(equity, "equity", signed=True)
    states = tuple(coins)
    seen: set[str] = set()
    for state in states:
        if not isinstance(state, CoinState):
            raise ValueError(f"coins must be CoinState, got {state!r:.60}")
        if state.coin in seen:
            raise ValueError(f"coin {state.coin} appears twice")
        seen.add(state.coin)
    with localcontext(CONTEXT):
        legs = _allocate(equity, states)
    return MappingProxyType({state.coin: legs[state.coin] for state in states})


def _allocate(equity: Decimal, states: tuple[CoinState, ...]) -> dict[str, LegTargets]:
    legs: dict[str, LegTargets] = {}
    spot_kept = futures_kept = dust = g_s = _ZERO
    longs_eligible: list[tuple[str, Decimal]] = []  # E
    longs_spot_only: list[tuple[str, Decimal]] = []  # N
    for state in states:
        dust += state.dust_notional
        if state.keeps_legs:
            spot = _ZERO if "spot" in state.exiting_legs else state.spot_notional
            futures = _ZERO if "futures" in state.exiting_legs else state.futures_notional
            legs[state.coin] = LegTargets(spot, futures)
            spot_kept += spot
            futures_kept += abs(futures)
            continue
        residual = state.target_notional - state.dust_notional
        if residual > 0:
            (longs_eligible if state.eligible else longs_spot_only).append((state.coin, residual))
        elif residual < 0 and state.eligible:
            legs[state.coin] = LegTargets(_ZERO, residual)  # a short: all on futures
            g_s -= residual
        else:  # a residual of 0, or a spot-only coin's negative one
            legs[state.coin] = LegTargets(_ZERO, _ZERO)
    g_e = sum((r for _, r in longs_eligible), _ZERO)
    g_n = sum((r for _, r in longs_spot_only), _ZERO)
    g_l = g_e + g_n
    room = (_ONE - COST_RESERVE) * equity - spot_kept - dust - futures_kept / _MARGIN_DIVISOR
    capacity = max(
        _ZERO,
        min(g_l, SPOT_CAPACITY_FACTOR * (room - (g_l + g_s) / _MARGIN_DIVISOR)),
    )
    if capacity >= g_n:
        # N is fully on spot; E shares what is left of the capacity, pro rata to its residuals.
        # (There is an E coin only when g_e > 0, and capacity <= g_l caps the share at 1.)
        shared = capacity - g_n
        for coin, residual in longs_spot_only:
            legs[coin] = LegTargets(residual, _ZERO)
        for coin, residual in longs_eligible:
            spot = min(residual, shared * residual / g_e)
            legs[coin] = LegTargets(spot, residual - spot)
    else:
        # E is fully on futures; N scales by one common factor (g_n > capacity >= 0 here).
        scale = min(_ONE, max(_ZERO, room - (g_e + g_s) / _MARGIN_DIVISOR) / g_n)
        for coin, residual in longs_eligible:
            legs[coin] = LegTargets(_ZERO, residual)
        for coin, residual in longs_spot_only:
            legs[coin] = LegTargets(scale * residual, _ZERO)
    return legs


def clip_increases(
    increases: Sequence[tuple[str, Venue, Decimal]],
    cash: Decimal,
    open_initial_margin: Decimal,
    backing: Decimal,
    maintenance: Decimal,
    costs: Mapping[Venue, Costs],
) -> tuple[tuple[str, Venue, Decimal], ...]:
    """Cut each increase to what the free cash pays for, in the order given.

    ``increases`` are ``(coin, venue, notional)`` at the unslipped opens, ``notional`` at
    least 0. ``cash``, ``open_initial_margin`` (the open futures' notional at the open / 3),
    ``backing`` and ``maintenance`` are the account after the hour's reductions. Returns
    ``(coin, venue, admitted)`` for every increase, in the same order, with the zeros kept;
    ``admitted`` is the whole ``notional`` (the same Decimal) when it fits, and otherwise
    the largest amount that keeps ``cash - open initial margin`` and ``backing - 4 x
    maintenance`` at or above 0 after the increase, truncated toward zero. Refuses a venue
    that ``costs`` lacks.
    """
    cash_now = _amount(cash, "cash", signed=True)
    margin_now = _amount(open_initial_margin, "open_initial_margin")
    backing_now = _amount(backing, "backing", signed=True)
    upkeep_now = _amount(maintenance, "maintenance")
    maintenance_rate = to_fraction(MAINTENANCE_RATE)
    margin_rate = Fraction(1, INITIAL_MARGIN_DIVISOR)
    rates: dict[str, tuple[Fraction, Fraction]] = {}
    admitted: list[tuple[str, Venue, Decimal]] = []
    for item in increases:
        coin, venue, notional = _increase(item)
        if venue not in rates:
            rates[venue] = _costs(costs, venue)
        fee_rate, slippage_rate = rates[venue]
        wanted = to_fraction(notional)
        fee_paid = (1 + slippage_rate) * fee_rate  # the fee on a unit of notional
        if venue == "spot":
            spent = (1 + slippage_rate) * (1 + fee_rate)  # cash and backing per unit bought
            used_cash = used_backing = spent
        else:
            used_cash = margin_rate + fee_paid  # term 1: the margin it adds, and its fee
            # Term 2: its fee, its slippage loss at the open, and 4 times the maintenance it adds.
            used_backing = fee_paid + slippage_rate + CUSHION_TARGET * maintenance_rate
        room_cash = max(cash_now - margin_now, Fraction(0))  # term 1, floored at 0
        room_backing = max(backing_now - CUSHION_TARGET * upkeep_now, Fraction(0))  # term 2
        cap = min(room_cash / used_cash, room_backing / used_backing)
        if cap >= wanted:
            amount, taken = notional, wanted
        else:
            amount = _truncate(cap)
            taken = to_fraction(amount)
        admitted.append((coin, venue, amount))
        if venue == "spot":
            cash_now -= taken * spent
            backing_now -= taken * spent
        else:
            cash_now -= taken * fee_paid
            margin_now += taken * margin_rate
            backing_now -= taken * (fee_paid + slippage_rate)
            upkeep_now += taken * maintenance_rate
    return tuple(admitted)


def to_venue_quantity(notional: Decimal, price: Decimal) -> Decimal:
    """``notional / price`` in the venue's own units, cut toward zero to 60 significant digits.

    ``price`` is the venue's own price: for a multiplier perpetual such as 1000SHIBUSDT the
    contract price, which is ``multiplier`` times the coin's. ``notional`` may be negative (a
    short); the quantity then is too. The cut never rounds up, so flooring the result to the
    step later never exceeds the true quotient.
    """
    amount = _amount(notional, "notional", signed=True)
    unit_price = _amount(price, "price", positive=True)
    return _truncate(amount / unit_price)


def _truncate(value: Fraction) -> Decimal:
    """``value`` cut toward zero to ``CONTEXT.prec`` significant digits (exact when it fits),
    and to at most 100 decimal places, the bound of the order and execution helpers a
    quantity goes on to."""
    cut = _TRUNCATE.divide(Decimal(value.numerator), Decimal(value.denominator))
    exponent = cut.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -_MAX_DECIMALS:
        cut = cut.quantize(_QUANTUM, context=_TRUNCATE)
    return cut


def _increase(item: object) -> tuple[str, Venue, Decimal]:
    if not isinstance(item, tuple) or len(item) != 3:
        raise ValueError(f"each increase must be a (coin, venue, notional) tuple, got {item!r:.60}")
    coin, venue, notional = item
    _symbol(coin, "coin")
    _check(notional, "notional")
    return coin, _venue(venue), notional


def _costs(costs: Mapping[Venue, Costs], venue: Venue) -> tuple[Fraction, Fraction]:
    """The fee rate and the slippage rate of one venue, each in [0, 1)."""
    if venue not in costs:
        raise ValueError(f"costs has no {venue} entry")
    entry = costs[venue]
    fee_rate = _amount(entry.fee_rate, "fee_rate")
    slippage_rate = _amount(entry.slippage_rate, "slippage_rate")
    if fee_rate >= 1 or slippage_rate >= 1:
        raise ValueError(f"the {venue} cost rates must be below 1")
    return fee_rate, slippage_rate


def _venue(value: object) -> Venue:
    if isinstance(value, str):
        if value == "spot":
            return "spot"
        if value == "futures":
            return "futures"
    raise ValueError(f"venue must be one of {_VENUES}, got {value!r:.40}")


def _symbol(value: object, what: str) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{what}: symbol must match [A-Z0-9]{{2,30}}, got {value!r:.40}")
    return value


def _check(value: object, what: str, *, signed: bool = False) -> None:
    """Refuse anything but a bounded finite Decimal (at least 0 unless ``signed``)."""
    _amount(value, what, signed=signed)


def _amount(value: object, what: str, *, positive: bool = False, signed: bool = False) -> Fraction:
    """The exact value of a bounded finite Decimal: positive, signed, or (the default) at
    least 0."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what} must be a finite Decimal, got {value!r:.40}")
    exponent = value.as_tuple().exponent
    if (
        value.adjusted() > _MAX_ADJUSTED
        or not isinstance(exponent, int)
        or exponent < _MIN_INPUT_EXPONENT
    ):
        raise ValueError(f"{what} must be below 1e37 with at most 1000 decimals, got {value!r:.40}")
    if positive and value <= 0:
        raise ValueError(f"{what} must be positive, got {value}")
    if not positive and not signed and value < 0:
        raise ValueError(f"{what} must not be negative, got {value}")
    return to_fraction(value)
