"""Offline, bounded parsing of the filter snapshots pinned by V3's data manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from crypto_grid_bot.market_data.parsing import amount, symbol_name


@dataclass(frozen=True, slots=True)
class OrderFilters:
    min_quantity: Decimal
    max_quantity: Decimal
    step_size: Decimal
    min_notional: Decimal
    lot_min_quantity: Decimal
    lot_max_quantity: Decimal
    lot_step_size: Decimal
    market_step_size: Decimal


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate snapshot JSON key")
        result[key] = value
    return result


def parse_filter_snapshot(
    raw: bytes, symbols: tuple[str, ...], *, futures: bool
) -> dict[str, OrderFilters]:
    """Preserve both lot filters; effective market step falls back only when zero."""
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("filter snapshot exceeds size limit")
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError("unique requested symbols required")
    for symbol in symbols:
        symbol_name(symbol)
    document = json.loads(raw, object_pairs_hook=_object)
    if not isinstance(document, dict) or not isinstance(document.get("symbols"), list):
        raise ValueError("snapshot must contain symbol list")
    rows: dict[str, dict[str, Any]] = {}
    for entry in document["symbols"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("symbol"), str):
            raise ValueError("invalid snapshot symbol entry")
        symbol = entry["symbol"]
        if symbol in rows:
            raise ValueError("duplicate snapshot symbol")
        rows[symbol] = entry
    result: dict[str, OrderFilters] = {}
    for symbol in symbols:
        if symbol not in rows:
            raise ValueError(f"missing snapshot symbol: {symbol}")
        entry = rows[symbol]
        if entry.get("quoteAsset") != "USDT":
            raise ValueError("expected USDT quote asset")
        if futures and entry.get("contractType") != "PERPETUAL":
            raise ValueError("expected perpetual contract")
        filters = entry.get("filters")
        if not isinstance(filters, list):
            raise ValueError("missing symbol filters")
        by_kind: dict[str, dict[str, Any]] = {}
        for item in filters:
            if not isinstance(item, dict) or not isinstance(item.get("filterType"), str):
                raise ValueError("invalid filter entry")
            kind = item["filterType"]
            if kind in by_kind:
                raise ValueError("duplicate filter type")
            by_kind[kind] = item
        try:
            lot, market = by_kind["LOT_SIZE"], by_kind["MARKET_LOT_SIZE"]
            lot_min = amount(lot.get("minQty"), positive=False)
            lot_max = amount(lot.get("maxQty"))
            lot_step = amount(lot.get("stepSize"))
            market_min = amount(market.get("minQty"), positive=False)
            market_max = amount(market.get("maxQty"))
            market_step = amount(market.get("stepSize"), positive=False)
            notionals = [by_kind[key] for key in ("MIN_NOTIONAL", "NOTIONAL") if key in by_kind]
            if not notionals:
                raise ValueError("missing minimum notional")
            minima = []
            for notional in notionals:
                values = [notional[key] for key in ("notional", "minNotional") if key in notional]
                if len(values) != 1:
                    raise ValueError("ambiguous or absent minimum notional value")
                minima.append(amount(values[0], positive=False))
            minimum = max(minima)
        except KeyError as exc:
            raise ValueError("missing lot filter") from exc
        step = market_step or lot_step
        if lot_min > lot_max or market_min > market_max or lot_step > lot_max or step > market_max:
            raise ValueError("inconsistent quantity limits")
        result[symbol] = OrderFilters(
            market_min, market_max, step, minimum, lot_min, lot_max, lot_step, market_step
        )
    return result
