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
* **Cash clip.** ``clip_increases`` applies the spec's rule literally. The hour loop calls it
  one increase at a time, in the fill order (alphabetical by the coin's spot symbol, the spot
  leg before the futures leg within a coin), each time on the ledger's state after the
  previous real fill (controller ruling, Task 8): an admitted increase is still floored to the
  step, or refused by the filters, before it fills, and only what actually fills may move the
  account the next increase sees. Free cash is ``min(cash - open initial margin, backing - 4 x
  maintenance)``. An increase is cut to the largest notional whose need fits in it, where, for
  a notional ``n`` at the unslipped open, a slippage rate ``s`` and a fee rate ``f``:

  - a spot buy needs its slipped notional plus its fee, ``n (1 + s)(1 + f)``;
  - a futures increase needs its initial margin plus its fee, ``n / 3 + fee``, the fee being
    ``f`` times the increase's own slipped notional: ``n (1 + s)`` for a buy (a long) and
    ``n (1 - s)`` for a sell (a short).

  The side of a futures increase is the sign of its notional (negative for a short); a spot
  buy is never negative. The admitted amount keeps the sign. So no increase takes the margin
  ratio below 4 and none is made while it is below 4: what a futures increase takes from
  ``backing - 4 x maintenance`` is its fee, its slippage loss at the open ``n s`` and 4 x the
  1% maintenance it adds, which is no more than its need when ``s + 0.04 <= 1/3`` (checked).
  Given several increases, the function updates its own copy of the account after each
  admitted one, on the unrounded amount: a spot buy takes its cost from cash and backing; a
  futures increase takes its fee from cash, adds ``n / 3`` to the initial margin, takes its fee
  and slippage loss from backing and adds 1% of ``n`` to the maintenance. That is why the loop
  passes one at a time: the update it would make for an increase later floored or skipped
  never happens in the ledger. The result keeps the input order and its zeros, so the caller
  can record each cut; the caller converts the admitted notional to a quantity, rounds it to
  the step and skips an increase that is now below the filters.
* **Venue units.** ``to_venue_quantity`` is ``notional / price`` in the venue's own units,
  truncated toward zero to ``CONTEXT.prec`` significant digits (and to 100 decimal places, the
  bound of the order helpers), so a later floor to the step never exceeds the true quotient.
  On a multiplier perpetual (1000SHIBUSDT) ``price`` is the contract price, already
  ``multiplier`` times the coin's.

``allocate`` computes under ``CONTEXT``. The clip does its arithmetic in exact ``Fraction``s,
so that an admitted amount can never need more than the free cash by a rounding, and returns
Decimals truncated toward zero.
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
    held futures. ``eligible`` is the coin's eligibility as decided at the decision (a perpetual
    listed point in time, and at a month's last-day decision a complete funding month next), not
    whether a perpetual exists: a coin with a perpetual can be ineligible, and is then spot-only
    here (the hour loop passes the latest decision's, and False for a replacement buy).
    ``keeps_legs`` marks a coin that keeps its legs as held (deferred, no-bar or band-kept);
    ``exiting_legs`` are the legs a mandatory exit closes this hour, which count as 0 for such a
    coin.
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

    ``increases`` are ``(coin, venue, notional)`` at the unslipped opens. A spot ``notional`` is
    at least 0; a futures one is signed, negative for a short increase (its sign is its side,
    which sets the price the fee is charged on). ``cash``, ``open_initial_margin`` (the open
    futures' notional at the open / 3), ``backing`` and ``maintenance`` are the account the
    first increase meets. The hour loop passes a single increase, on the ledger after the hour's
    reductions and every earlier increase that actually filled (module docstring); with several,
    each later one meets this function's own update of the account. Free cash is ``min(cash -
    open initial margin, backing - 4 x maintenance)``, and an increase is admitted up to the
    largest amount whose need fits in it (a spot buy ``n (1 + s)(1 + f)``, a futures increase
    ``n / 3`` plus its fee). Returns ``(coin, venue, admitted)`` for every increase, in the same
    order, with the zeros kept; ``admitted`` is the whole ``notional`` (the same Decimal) when
    it fits, and otherwise the cut amount, with the notional's sign, truncated toward zero.
    Refuses a venue that ``costs`` lacks.
    """
    cash_now = _amount(cash, "cash", signed=True)
    margin_now = _amount(open_initial_margin, "open_initial_margin")
    backing_now = _amount(backing, "backing", signed=True)
    upkeep_now = _amount(maintenance, "maintenance")
    maintenance_rate = to_fraction(MAINTENANCE_RATE)
    margin_rate = Fraction(1, INITIAL_MARGIN_DIVISOR)
    # A futures increase takes fee + n s + 4 x 0.01 n from term 2 and needs n / 3 + fee.
    slippage_limit = margin_rate - CUSHION_TARGET * maintenance_rate
    rates: dict[str, tuple[Fraction, Fraction]] = {}
    admitted: list[tuple[str, Venue, Decimal]] = []
    for item in increases:
        coin, venue, notional = _increase(item)
        if venue not in rates:
            rates[venue] = _costs(costs, venue)
            if venue == "futures" and rates[venue][1] > slippage_limit:
                raise ValueError(
                    f"the futures slippage rate {rates[venue][1]} is above {slippage_limit}: an "
                    "increase's need would no longer cover what it takes from the cushion"
                )
        fee_rate, slippage_rate = rates[venue]
        side = -1 if notional < 0 else 1
        wanted = abs(to_fraction(notional))
        # What the increase costs per unit of notional: for a spot buy, cash and backing alike.
        fee_paid = fee_rate * (1 + side * slippage_rate)  # the fee on its own slipped notional
        need = (1 + slippage_rate) * (1 + fee_rate) if venue == "spot" else margin_rate + fee_paid
        free = min(cash_now - margin_now, backing_now - CUSHION_TARGET * upkeep_now)
        cap = max(free, Fraction(0)) / need
        if cap >= wanted:
            amount, taken = notional, wanted
        else:
            amount = _truncate(side * cap)
            taken = abs(to_fraction(amount))
        admitted.append((coin, venue, amount))
        if venue == "spot":
            cash_now -= taken * need
            backing_now -= taken * need
        else:
            cash_now -= taken * fee_paid
            margin_now += taken * margin_rate
            backing_now -= taken * (fee_paid + slippage_rate)  # the fee, and the loss at the open
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
    kind = _venue(venue)
    _check(notional, "notional", signed=kind == "futures")
    return coin, kind, notional


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
