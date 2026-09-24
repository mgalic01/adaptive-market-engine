"""Validate Binance public responses before deriving any diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

HOUR_MS = 3_600_000
D = Decimal


class DataError(ValueError):
    """An observation is incomplete, stale or internally inconsistent."""


def symbol_name(value: str) -> str:
    if not re.fullmatch(r"[A-Z0-9]{2,24}", value, flags=re.ASCII):
        raise DataError("symbol must contain 2-24 uppercase ASCII letters/digits")
    return value


def integer(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 10**16:
        raise DataError("expected a bounded non-negative integer")
    return value


def amount(value: Any, *, positive: bool = True) -> Decimal:
    if not isinstance(value, str) or len(value) > 64:
        raise DataError("expected a decimal string")
    try:
        number = D(value)
    except InvalidOperation as exc:
        raise DataError("invalid decimal") from exc
    if not number.is_finite() or not 0 <= number <= D("1e18") or (positive and not number):
        raise DataError("decimal must be finite and within bounds")
    # Extremely small exponents can exhaust Decimal operations downstream.
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or not -18 <= exponent <= 18:
        raise DataError("unsupported decimal precision")
    return number


@dataclass(frozen=True)
class Candle:
    open_ms: int
    close_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal


@dataclass(frozen=True)
class Instrument:
    symbol: str
    base: str
    quote: str
    tick_size: Decimal
    quantity_step: Decimal
    min_quantity: Decimal
    max_quantity: Decimal
    min_notional: Decimal
    max_notional: Decimal | None


@dataclass(frozen=True)
class Book:
    update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]

    @property
    def midpoint(self) -> Decimal:
        return (self.bids[0][0] + self.asks[0][0]) / 2

    @property
    def spread_pct(self) -> Decimal:
        return (self.asks[0][0] - self.bids[0][0]) / self.midpoint * 100


def parse_instrument(payload: Any, symbol: str) -> Instrument:
    try:
        entries = payload["symbols"]
        if not isinstance(entries, list) or len(entries) != 1:
            raise DataError("expected exactly one requested symbol")
        item = entries[0]
        if item["symbol"] != symbol or item["status"] != "TRADING":
            raise DataError("requested symbol is unavailable or halted")
        if (
            item["isSpotTradingAllowed"] is not True
            or not isinstance(item["orderTypes"], list)
            or "LIMIT" not in item["orderTypes"]
        ):
            raise DataError("spot limit orders are not supported")
        base, quote = symbol_name(item["baseAsset"]), symbol_name(item["quoteAsset"])
        if base + quote != symbol or base == quote:
            raise DataError("inconsistent asset mapping")
        raw_filters = item["filters"]
        if not isinstance(raw_filters, list):
            raise DataError("expected a list of exchange filters")
        filters = {f["filterType"]: f for f in raw_filters}
        if len(filters) != len(raw_filters):
            raise DataError("duplicate exchange filters")
        price, lot = filters["PRICE_FILTER"], filters["LOT_SIZE"]
        notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL"))
        if notional is None:
            raise DataError("missing notional filter")
        minima = [
            amount(f["minNotional"])
            for k, f in filters.items()
            if k in ("MIN_NOTIONAL", "NOTIONAL")
        ]
        maximum = amount(notional["maxNotional"]) if "maxNotional" in notional else None
        result = Instrument(
            symbol,
            base,
            quote,
            amount(price["tickSize"]),
            amount(lot["stepSize"]),
            amount(lot["minQty"]),
            amount(lot["maxQty"]),
            max(minima),
            maximum,
        )
        if result.max_quantity < result.min_quantity:
            raise DataError("quantity bounds are inverted")
        if maximum is not None and maximum < result.min_notional:
            raise DataError("notional bounds are inverted")
        return result
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise DataError("invalid exchange information") from exc


def parse_candles(payload: Any, server_ms: int) -> tuple[Candle, ...]:
    if not isinstance(payload, list) or not 50 <= len(payload) <= 1000:
        raise DataError("insufficient or excessive hourly history")
    candles: list[Candle] = []
    try:
        for row in payload:
            if not isinstance(row, list) or len(row) != 12:
                raise DataError("invalid kline layout")
            start, end = integer(row[0]), integer(row[6])
            if start % HOUR_MS or end != start + HOUR_MS - 1 or end >= server_ms:
                raise DataError("candle is unclosed or not a UTC hourly candle")
            if candles and start != candles[-1].open_ms + HOUR_MS:
                raise DataError("candle history has gaps, duplicates or disorder")
            o, h, low, c = (amount(row[i]) for i in range(1, 5))
            if not low <= min(o, c) <= max(o, c) <= h:
                raise DataError("inconsistent OHLC prices")
            volume, quote_volume = amount(row[5], positive=False), amount(row[7], positive=False)
            integer(row[8])
            taker_base, taker_quote = (
                amount(row[9], positive=False),
                amount(row[10], positive=False),
            )
            if taker_base > volume or taker_quote > quote_volume:
                raise DataError("taker volume exceeds total volume")
            candles.append(Candle(start, end, o, h, low, c, volume, quote_volume))
    except (IndexError, TypeError) as exc:
        raise DataError("invalid candle response") from exc
    expected_close = (server_ms // HOUR_MS) * HOUR_MS - 1
    if candles[-1].close_ms != expected_close:
        raise DataError("latest closed hourly candle is missing")
    return tuple(candles)


def parse_book(payload: Any, instrument: Instrument) -> Book:
    try:
        sides: list[tuple[tuple[Decimal, Decimal], ...]] = []
        for name in ("bids", "asks"):
            levels = payload[name]
            if not isinstance(levels, list) or not 1 <= len(levels) <= 100:
                raise DataError("empty or excessive order book")
            parsed = []
            for row in levels:
                if not isinstance(row, list) or len(row) != 2:
                    raise DataError("invalid book level")
                price, quantity = amount(row[0]), amount(row[1])
                with localcontext() as context:
                    context.prec = 80
                    if price % instrument.tick_size or quantity % instrument.quantity_step:
                        raise DataError("book violates advertised precision")
                parsed.append((price, quantity))
            prices = [level[0] for level in parsed]
            if len(set(prices)) != len(prices) or prices != sorted(prices, reverse=name == "bids"):
                raise DataError("book levels are duplicated or unsorted")
            sides.append(tuple(parsed))
        result = Book(integer(payload["lastUpdateId"]), sides[0], sides[1])
        if result.bids[0][0] >= result.asks[0][0]:
            raise DataError("locked or crossed order book")
        return result
    except (KeyError, TypeError, IndexError) as exc:
        raise DataError("invalid order book") from exc


def diagnostics(candles: tuple[Candle, ...], book: Book) -> dict[str, str | int]:
    """Descriptive measurements only, never a broad-market regime or buy signal."""
    closes = [c.close for c in candles]
    sma20, sma50 = sum(closes[-20:], D(0)) / 20, sum(closes[-50:], D(0)) / 50
    changes = [abs(b - a) for a, b in zip(closes[-21:-1], closes[-20:], strict=True)]
    path = sum(changes, D(0))
    true_ranges = [
        max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
        for p, c in zip(candles[-15:-1], candles[-14:], strict=True)
    ]
    band = D("0.005")
    bid_depth = sum(p * q for p, q in book.bids if p >= book.midpoint * (1 - band))
    ask_depth = sum(p * q for p, q in book.asks if p <= book.midpoint * (1 + band))
    return {
        "closed_candles": len(candles),
        "latest_close_ms": candles[-1].close_ms,
        "last_closed_price": str(closes[-1]),
        "sma20": str(sma20),
        "sma50": str(sma50),
        "sma20_vs_sma50_pct": str((sma20 / sma50 - 1) * 100),
        "return_24h_pct": str((closes[-1] / closes[-25] - 1) * 100),
        "atr14_simple": str(sum(true_ranges) / 14),
        "efficiency20": str(abs(closes[-1] - closes[-21]) / path if path else D(0)),
        "quote_volume_24h": str(sum(c.quote_volume for c in candles[-24:])),
        "spread_pct": str(book.spread_pct),
        "visible_bid_depth_0_5pct": str(bid_depth),
        "visible_ask_depth_0_5pct": str(ask_depth),
    }
