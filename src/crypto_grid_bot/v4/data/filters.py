"""Order rules for each (symbol, venue) of the V4 data step: present-day, or inferred (ruling R2).

A symbol that appears in the pinned present-day ``exchangeInfo`` snapshot of its venue (ruling
R3: the V3.1 snapshots) uses the rules ``combined.driver.venues.venue_rules`` reads from it,
labelled ``"present_day"``. Appearing is all that counts: a symbol whose ``status`` is
``BREAK`` or ``SETTLING`` is still present, and a present symbol the snapshot cannot give
usable rules for is refused, never inferred.

A symbol that is absent, typically a delisted one, gets the fixed fallback of ruling R2,
labelled ``"inferred"``, from its own bars:

* ``tick`` is 10^-d, where d is the most decimal places in any bar's open, high, low or close;
* ``step`` is 10^-d the same way, from the bars' base ``volume`` (not ``quote_volume``), and
  ``min_qty`` is ``step``;
* ``max_qty`` is ``9000000000`` and ``min_notional`` is ``5``, on either venue.

Decimals are counted from the Decimal exponent after ``normalize()`` drops trailing zeros, so
``"0.09865000"`` counts 5 and an integer, ``"1E+2"`` included, counts 0 (``tick`` and ``step``
are then 1). Nothing is a float and nothing depends on the caller's Decimal context.

Pure: no network, no file, no clock. Every refusal is a ``ValueError`` that names the symbol.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import MAX_PREC, Context, Decimal
from typing import Literal

from crypto_grid_bot.combined.driver.venues import Venue, venue_rules
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.v4.data.bars import HourBar

Source = Literal["present_day", "inferred"]

# Ruling R2's fixed values for a symbol the snapshot does not list.
INFERRED_MAX_QTY = Decimal("9000000000")
INFERRED_MIN_NOTIONAL = Decimal("5")
# normalize() rounds to the context's precision; this one is exact for any Decimal.
_EXACT = Context(prec=MAX_PREC)


def rules_for(
    symbol: str, venue: str, snapshot: Mapping[str, object], bars: Sequence[HourBar]
) -> tuple[VenueRules, Source]:
    """The order rules of one USDT symbol on one venue, and where they came from.

    ``venue`` is ``"spot"`` or ``"futures"``, ``snapshot`` that venue's parsed ``exchangeInfo``
    and ``bars`` the symbol's hourly bars on it. A symbol listed in the snapshot gets
    ``venue_rules``' answer and ``"present_day"``; bars are not read. Any other symbol gets the
    inferred rules and ``"inferred"``, so it needs at least one bar. Refuses an unknown venue,
    an invalid symbol, a snapshot without a well formed symbols list, a listed symbol that
    ``venue_rules`` refuses, an unlisted one with no bars or with a non-finite bar value, and
    one whose bar precision the rules cannot hold.
    """
    kind = _venue(venue)
    label = f"{symbol} ({kind})"
    try:
        symbol_name(symbol)
    except ValueError as exc:
        raise ValueError(f"invalid symbol {symbol!r}: {exc}") from exc
    if _listed(snapshot, symbol, label):
        return venue_rules(snapshot, symbol, kind), "present_day"
    if not bars:
        raise ValueError(f"{label}: absent from the snapshot and has no bars to infer rules from")
    prices = (price for bar in bars for price in (bar.open, bar.high, bar.low, bar.close))
    tick = _unit(_decimals(prices, label))
    step = _unit(_decimals((bar.volume for bar in bars), label))
    try:
        rules = VenueRules(
            step=step,
            min_qty=step,
            max_qty=INFERRED_MAX_QTY,
            min_notional=INFERRED_MIN_NOTIONAL,
            tick=tick,
        )
    except ValueError as exc:
        raise ValueError(f"{label}: unusable inferred order rules ({exc})") from exc
    return rules, "inferred"


def _venue(venue: str) -> Venue:
    """``venue`` as ``venue_rules``' own type; anything but its two values is refused."""
    if venue == "spot":
        return "spot"
    if venue == "futures":
        return "futures"
    raise ValueError(f"unknown venue {venue!r}: spot or futures required")


def _listed(snapshot: Mapping[str, object], symbol: str, label: str) -> bool:
    """Whether the snapshot lists ``symbol``, whatever its status.

    Every entry must be well formed, as ``venue_rules`` requires, so that one snapshot is
    accepted or refused alike for a listed symbol and an unlisted one.
    """
    entries = snapshot.get("symbols")
    if not isinstance(entries, list):
        raise ValueError(f"{label}: snapshot must contain a symbols list")
    listed = False
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("symbol"), str):
            raise ValueError(f"{label}: invalid snapshot symbol entry {entry!r}")
        listed = listed or entry["symbol"] == symbol
    return listed


def _decimals(values: Iterable[Decimal], label: str) -> int:
    """The most decimal places among ``values`` once trailing zeros are dropped (0 for none)."""
    places = 0
    for value in values:
        if not value.is_finite():
            raise ValueError(f"{label}: bar value {value} is not finite")
        exponent = value.normalize(_EXACT).as_tuple().exponent
        assert isinstance(exponent, int)  # a finite Decimal's exponent is an int
        places = max(places, -exponent)
    return places


def _unit(places: int) -> Decimal:
    """10^-places, built from its digits so that no Decimal context can round it."""
    return Decimal((0, (1,), -places))
