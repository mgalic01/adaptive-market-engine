"""Per-venue order rules read from the saved Binance filters, and the pinned cost profiles.

Pure and offline: ``venue_rules`` reads an ``exchangeInfo`` document that the caller has
already parsed, and nothing here opens a path or touches the network. Every refusal is a
``ValueError`` that names the symbol (and, for a filter problem, the filter).

``COST_PROFILE_PINS`` maps each cost multiple to the SHA-256 of that profile's canonical
JSON: ``{"multiple": 1, "spot": {...}, "futures": {...}}`` where each venue object holds
``fee_rate``, ``slippage_rate`` and ``round_trip_cost_rate`` as ``str(Decimal)``, written
with ``json.dumps(..., sort_keys=True, separators=(",", ":"))`` and encoded as UTF-8.
"""

import hashlib
import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.market_data.parsing import amount, symbol_name

Venue = Literal["spot", "futures"]

# Fee, slippage and round-trip bound per venue at multiple 1, as registered for V3.1.
_BASE_RATES: dict[Venue, tuple[Decimal, Decimal, Decimal]] = {
    "spot": (Decimal("0.001"), Decimal("0.0005"), Decimal("0.004")),
    "futures": (Decimal("0.0005"), Decimal("0.0005"), Decimal("0.0025")),
}
_MULTIPLES = (1, 2)
_NOTIONAL_KINDS = ("NOTIONAL", "MIN_NOTIONAL")
_NOTIONAL_KEYS = ("notional", "minNotional")


def venue_rules(snapshot: Mapping[str, object], symbol: str, venue: Venue) -> VenueRules:
    """Return the order rules of one USDT symbol, read from a parsed ``exchangeInfo``.

    Quantity limits take the stricter of ``LOT_SIZE`` and ``MARKET_LOT_SIZE``, because the
    replay fills at the bar open and also rests limit orders: the larger minimum, the
    smaller positive maximum (a zero market maximum is ignored) and the lot step. The
    minimum notional is the largest value among the ``NOTIONAL`` and ``MIN_NOTIONAL``
    filters present, and the tick is ``PRICE_FILTER``'s. Refuses a missing symbol, a
    non-USDT quote asset, a futures contract that is not perpetual, a duplicate symbol or
    filter, a market step that differs from the lot step, and any filter value that is
    absent, ambiguous or unparsable.
    """
    if venue not in _BASE_RATES:
        raise ValueError(f"unknown venue {venue!r}: spot or futures required")
    if not isinstance(symbol, str):
        raise ValueError(f"symbol must be a string, got {symbol!r}")
    try:
        symbol_name(symbol)
    except ValueError as exc:
        raise ValueError(f"invalid symbol {symbol!r}: {exc}") from exc
    label = f"{symbol} ({venue})"
    entry = _symbol_entry(snapshot, symbol, label)
    if entry.get("quoteAsset") != "USDT":
        raise ValueError(f"{label}: expected USDT quote asset, got {entry.get('quoteAsset')!r}")
    if venue == "futures" and entry.get("contractType") != "PERPETUAL":
        raise ValueError(
            f"{label}: expected a PERPETUAL contract, got {entry.get('contractType')!r}"
        )
    filters = _filters_by_type(entry, label)

    price = _filter(filters, "PRICE_FILTER", label)
    tick = _value(price, "PRICE_FILTER", "tickSize", label, positive=True)

    lot = _filter(filters, "LOT_SIZE", label)
    step = _value(lot, "LOT_SIZE", "stepSize", label, positive=True)
    min_qty = _value(lot, "LOT_SIZE", "minQty", label, positive=False)
    max_qty = _value(lot, "LOT_SIZE", "maxQty", label, positive=True)
    market = filters.get("MARKET_LOT_SIZE")
    if market is not None:
        market_step = _value(market, "MARKET_LOT_SIZE", "stepSize", label, positive=False)
        market_min = _value(market, "MARKET_LOT_SIZE", "minQty", label, positive=False)
        market_max = _value(market, "MARKET_LOT_SIZE", "maxQty", label, positive=False)
        if market_step and market_step != step:
            raise ValueError(
                f"{label}: MARKET_LOT_SIZE stepSize {market_step} differs from "
                f"LOT_SIZE stepSize {step}"
            )
        min_qty = max(min_qty, market_min)
        if market_max:
            max_qty = min(max_qty, market_max)

    try:
        return VenueRules(
            step=step,
            min_qty=min_qty,
            max_qty=max_qty,
            min_notional=_minimum_notional(filters, label),
            tick=tick,
        )
    except ValueError as exc:
        raise ValueError(f"{label}: unusable order rules ({exc})") from exc


def cost_profile(multiple: int, venue: Venue) -> Costs:
    """Return the registered cost rates of one venue at multiple 1 (base) or 2 (doubled).

    Base spot is fee 0.001, slippage 0.0005 and round-trip bound 0.004; base futures is
    0.0005, 0.0005 and 0.0025. A multiple of 2 doubles all three. Refuses any other
    multiple (a bool or a float included) and any other venue.
    """
    if type(multiple) is not int or multiple not in _MULTIPLES:
        raise ValueError(f"cost multiple must be 1 or 2, got {multiple!r}")
    if venue not in _BASE_RATES:
        raise ValueError(f"unknown venue {venue!r}: spot or futures required")
    # normalize() keeps each product in its shortest form (0.0005 * 2 is 0.001, not 0.0010),
    # so the canonical JSON that the pins hash does not depend on how a rate was computed.
    fee, slippage, round_trip = (rate * multiple for rate in _BASE_RATES[venue])
    return Costs(fee.normalize(), slippage.normalize(), round_trip.normalize())


def _profile_digest(multiple: int) -> str:
    """The SHA-256 (hex) of one multiple's canonical JSON, both venues together."""
    profile: dict[str, object] = {"multiple": multiple}
    for venue in sorted(_BASE_RATES):
        costs = cost_profile(multiple, venue)
        profile[venue] = {
            "fee_rate": str(costs.fee_rate),
            "slippage_rate": str(costs.slippage_rate),
            "round_trip_cost_rate": str(costs.round_trip_cost_rate),
        }
    text = json.dumps(profile, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


COST_PROFILE_PINS: dict[int, str] = {multiple: _profile_digest(multiple) for multiple in _MULTIPLES}


def _symbol_entry(snapshot: Mapping[str, object], symbol: str, label: str) -> Mapping[str, object]:
    """The one snapshot entry for ``symbol``; every entry must be well formed."""
    entries = snapshot.get("symbols")
    if not isinstance(entries, list):
        raise ValueError(f"{label}: snapshot must contain a symbols list")
    found: Mapping[str, object] | None = None
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("symbol"), str):
            raise ValueError(f"{label}: invalid snapshot symbol entry {entry!r}")
        if entry["symbol"] == symbol:
            if found is not None:
                raise ValueError(f"{label}: duplicate snapshot symbol")
            found = entry
    if found is None:
        raise ValueError(f"{label}: symbol is missing from the snapshot")
    return found


def _filters_by_type(entry: Mapping[str, object], label: str) -> dict[str, Mapping[str, object]]:
    """The symbol's filters keyed by ``filterType``; a repeated type is refused."""
    filters = entry.get("filters")
    if not isinstance(filters, list):
        raise ValueError(f"{label}: the filters list is missing")
    by_kind: dict[str, Mapping[str, object]] = {}
    for item in filters:
        if not isinstance(item, Mapping) or not isinstance(item.get("filterType"), str):
            raise ValueError(f"{label}: malformed filter entry {item!r}")
        kind = item["filterType"]
        if kind in by_kind:
            raise ValueError(f"{label}: duplicate {kind} filter")
        by_kind[kind] = item
    return by_kind


def _filter(
    filters: Mapping[str, Mapping[str, object]], kind: str, label: str
) -> Mapping[str, object]:
    if kind not in filters:
        raise ValueError(f"{label}: {kind} filter is missing")
    return filters[kind]


def _value(
    item: Mapping[str, object], kind: str, name: str, label: str, *, positive: bool
) -> Decimal:
    """One filter field as a strict Decimal; a missing or unparsable field is refused."""
    if name not in item:
        raise ValueError(f"{label}: {kind} has no {name}")
    try:
        return amount(item[name], positive=positive)
    except ValueError as exc:
        raise ValueError(f"{label}: {kind} {name} is unusable ({exc})") from exc


def _minimum_notional(filters: Mapping[str, Mapping[str, object]], label: str) -> Decimal:
    """The largest minimum notional among the notional filters present."""
    minima = []
    for kind in _NOTIONAL_KINDS:
        if kind not in filters:
            continue
        keys = [key for key in _NOTIONAL_KEYS if key in filters[kind]]
        if len(keys) != 1:
            raise ValueError(f"{label}: {kind} must carry exactly one of notional and minNotional")
        minima.append(_value(filters[kind], kind, keys[0], label, positive=False))
    if not minima:
        raise ValueError(f"{label}: neither a NOTIONAL nor a MIN_NOTIONAL filter is present")
    return max(minima)
