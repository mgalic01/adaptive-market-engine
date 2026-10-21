"""The engine's view of the step-2 data packs: compact hourly series, daily bars, the monthly
universe, perpetual eligibility and funding.

Implements the spec's "Universe: coins chosen by a rule" (a perpetual is eligible only point in
time), "Data" (masked hours have no bar, the 20-of-24 day rule, funding months, the window) and
the 168-hour dead-market window of "Safety", over the pack contract in the docstring of
``crypto_grid_bot.v4.data.pack``.

``Market.load`` reads ``data.json`` (``"v4-data/1"``, written by ``scripts/v4_data.py``). It
verifies the daily pack and the hourly index by their pins, then each coin pack by the pin the
index gives, one pack at a time. Each pack must carry its own format, and the ``config_sha256``
and ``end_month`` of ``data.json``. A file is read only by a plain name inside the data
directory. Only the universes are kept from the daily pack. Each coin pack's rows become
compact stores, and its document is released before the next one is read.

Masking follows the contract: rows include masked bars, and ``SeriesStore.from_rows`` drops
every masked open. An open with no row is masked as well, so ``bar`` returns None for it. A
month in a mask's ``unreadable`` already has all its intervals in ``masked``. A store keeps
five ``array("q")``: the opens, and the open, high, low and close scaled by ``10**d``. Here
``d`` is the most decimal places of any kept price after ``normalize()``. Every price comes
back as exactly its Decimal value, with ``d`` decimals: ``0.09865000`` in a series whose ``d``
is 5 comes back as ``0.09865``.

Daily bars are ``combined.assessment.daily_bars`` (V3's day rule: at least 20 usable hours of
the UTC day) over the unmasked spot hours. They are built once per coin, with zero volumes,
since the engine needs prices only.

Nothing here calls the 2024 guard or touches the network.
"""

from __future__ import annotations

import json
import re
from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Context, Decimal, DecimalException, Inexact, InvalidOperation, Rounded
from pathlib import Path
from types import MappingProxyType
from typing import Any

from crypto_grid_bot.backtest.klines import INTERVAL_MS, Kline, month_bounds_ms
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.pack import (
    COIN_FORMAT,
    DAILY_FORMAT,
    INDEX_FORMAT,
    coin_pack_file,
    read_canonical,
)
from crypto_grid_bot.v4.engine.arms import DEAD_MARKET_HOURS

DATA_FORMAT = "v4-data/1"
DATA_FILE = "data.json"
HOUR_MS = INTERVAL_MS["1h"]
COMPLETE = "complete"

# The V4 data layer's symbol pattern (ruling R7).
_SYMBOL = re.compile(r"[A-Z0-9]{2,30}")
_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
# A pack's file: a plain name, never a path out of the data directory.
_FILE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# normalize() and scaleb() under this context never round a price the data reader accepts (at
# most 1e18, exponents -18 to 18: 37 digits); a price that would round is refused.
_EXACT = Context(prec=100, traps=[InvalidOperation, Inexact, Rounded])
_ZERO = Decimal(0)
_RULE_FIELDS = ("step", "min_qty", "max_qty", "min_notional", "tick")


@dataclass(frozen=True, slots=True)
class HourBar:
    """One unmasked hourly bar's prices (ruling P2). The engine needs no volumes."""

    open_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class SeriesStore:
    """One venue's unmasked hourly bars, in five ``array("q")``: the opens in ms, and the open,
    high, low and close as integers scaled by ``10**places``. Build one with ``from_rows``."""

    __slots__ = ("_close", "_high", "_low", "_open", "_opens", "_places")

    def __init__(
        self,
        opens: array[int],
        open_: array[int],
        high: array[int],
        low: array[int],
        close: array[int],
        places: int,
    ) -> None:
        if not len(opens) == len(open_) == len(high) == len(low) == len(close):
            raise ValueError("a series store's arrays must have one entry per bar")
        if type(places) is not int or places < 0:
            raise ValueError(f"places must be a non-negative int, got {places!r}")
        self._opens, self._open, self._high, self._low, self._close = opens, open_, high, low, close
        self._places = places

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[str | int]], masked: Iterable[int]) -> SeriesStore:
        """The store of a pack series' rows, ``[open_ms, open, high, low, close, ...]`` (only
        the first five fields are read), less every open in ``masked``.

        Every row's open must be a non-negative int on an hour, strictly increasing across the
        rows, masked ones included. A kept row's prices must be positive finite decimal strings,
        with the low at or below the open and close and the high at or above them. A refusal
        is a ``ValueError``.
        """
        hidden = _masked_opens(masked)
        opens: list[int] = []
        prices: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
        places, previous = 0, -1
        for number, values in enumerate(rows):
            if len(values) < 5:
                raise ValueError(f"row {number}: at least 5 columns required, got {len(values)}")
            open_ms = values[0]
            if type(open_ms) is not int or open_ms < 0 or open_ms % HOUR_MS:
                raise ValueError(
                    f"row {number}: the open must be a non-negative int on an hour, "
                    f"got {open_ms!r:.40}"
                )
            if open_ms <= previous:
                raise ValueError(f"row {number}: opens must be strictly increasing ({open_ms})")
            previous = open_ms
            if open_ms in hidden:
                continue
            o, h, low, c = (_price(values[i], number, open_ms) for i in (1, 2, 3, 4))
            if low > min(o, c):
                raise ValueError(f"row {number} ({open_ms}): the low {low} is above the body")
            if h < max(o, c):
                raise ValueError(f"row {number} ({open_ms}): the high {h} is below the body")
            places = max(places, _places(o), _places(h), _places(low), _places(c))
            opens.append(open_ms)
            prices.append((o, h, low, c))
        open_, high, low_, close = (
            _column([_scaled(bar[field], places) for bar in prices], places) for field in range(4)
        )
        return cls(array("q", opens), open_, high, low_, close, places)

    def __len__(self) -> int:
        return len(self._opens)

    @property
    def first_open_ms(self) -> int | None:
        """The first unmasked bar's open, or None for an empty store."""
        return self._opens[0] if self._opens else None

    def opens(self) -> Sequence[int]:
        """Every unmasked bar's open, in order: a read-only view of the store's array (``list()``
        it to compare it with a list)."""
        return memoryview(self._opens).toreadonly()

    def bar(self, open_ms: int) -> HourBar | None:
        """The bar that opens at ``open_ms``, or None if that hour is masked or has no row."""
        index = bisect_left(self._opens, open_ms)
        if index == len(self._opens) or self._opens[index] != open_ms:
            return None
        return self._bar(index)

    def bars(self) -> Iterator[HourBar]:
        """Every unmasked bar, in open order."""
        return (self._bar(index) for index in range(len(self._opens)))

    def last_open_at_or_before(self, ms: int) -> int | None:
        """The open of the last unmasked bar that opens at or before ``ms``, or None."""
        index = bisect_right(self._opens, ms)
        return self._opens[index - 1] if index else None

    def last_close_before(self, ms: int) -> Decimal | None:
        """The close of the last unmasked bar that closed before ``ms``, or None. A bar that
        opens at t closes before t + 1 h, so its close is known from t + 1 h on."""
        index = bisect_right(self._opens, ms - HOUR_MS)
        return self._value(self._close[index - 1]) if index else None

    def _value(self, scaled: int) -> Decimal:
        return Decimal(scaled).scaleb(-self._places, _EXACT)

    def _bar(self, index: int) -> HourBar:
        return HourBar(
            self._opens[index],
            self._value(self._open[index]),
            self._value(self._high[index]),
            self._value(self._low[index]),
            self._value(self._close[index]),
        )


@dataclass(frozen=True, slots=True)
class Perpetual:
    """A coin's USDT-M perpetual, in its own units: one contract is ``multiplier`` coins and
    its prices, filters and funding are per contract. ``funding`` is (time_ms, rate) in the
    pack's order, and ``months`` maps ``"YYYY-MM"`` to the month's funding status."""

    symbol: str
    multiplier: int
    store: SeriesStore
    funding: tuple[tuple[int, Decimal], ...]
    months: Mapping[str, str]
    rules: VenueRules

    def __post_init__(self) -> None:
        _symbol(self.symbol, "perpetual")
        if type(self.multiplier) is not int or self.multiplier < 1:
            raise ValueError(
                f"perpetual {self.symbol}: the multiplier must be a positive int, "
                f"got {self.multiplier!r}"
            )


@dataclass(frozen=True, slots=True)
class Coin:
    """One coin ever selected: its spot series and rules, and its perpetual if it has one."""

    symbol: str
    spot: SeriesStore
    spot_rules: VenueRules
    perpetual: Perpetual | None

    def __post_init__(self) -> None:
        _symbol(self.symbol, "coin")


class Market:
    """The packs as the engine reads them. ``Market.load`` builds one from a data directory;
    the constructor takes the parts directly.

    ``universes`` maps a month to its selected symbols in rank order. Every selected symbol
    must be one of ``coins``. The window opens at 00:00 UTC of the first month whose selection
    is not empty (spec "Data") and ends with the last hour of ``end_month``.
    """

    __slots__ = (
        "_coins",
        "_daily",
        "_funding",
        "_universes",
        "end_month",
        "symbols",
        "window_end_ms",
        "window_start_ms",
    )

    def __init__(
        self, *, end_month: str, universes: Mapping[str, Sequence[str]], coins: Iterable[Coin]
    ) -> None:
        end_ms = month_bounds_ms(_month(end_month, "end_month"))[1]
        by_symbol: dict[str, Coin] = {}
        owners: dict[str, str] = {}  # perpetual -> its coin
        for coin in coins:
            if not isinstance(coin, Coin):
                raise ValueError(f"coins: Coin required, got {coin!r:.60}")
            if coin.symbol in by_symbol:
                raise ValueError(f"coins: {coin.symbol} is listed twice")
            by_symbol[coin.symbol] = coin
            if coin.perpetual is not None:
                if coin.perpetual.symbol in owners:
                    raise ValueError(
                        f"coins: {coin.perpetual.symbol} is the perpetual of both "
                        f"{owners[coin.perpetual.symbol]} and {coin.symbol}"
                    )
                owners[coin.perpetual.symbol] = coin.symbol
        months: dict[str, tuple[str, ...]] = {}
        for month in sorted(universes):
            _month(month, "universe month")
            if month > end_month:
                raise ValueError(f"universe {month} is after end_month {end_month}")
            selected = tuple(universes[month])
            unknown = [symbol for symbol in selected if symbol not in by_symbol]
            if unknown:
                raise ValueError(f"universe {month}: no coin pack for {', '.join(unknown)}")
            if len(set(selected)) != len(selected):
                raise ValueError(f"universe {month}: a symbol is selected twice")
            months[month] = selected
        first = next((month for month, selected in months.items() if selected), None)
        if first is None:
            raise ValueError("no universe month has a selection, so the window has no start")
        self.end_month = end_month
        self.window_start_ms = month_bounds_ms(first)[0]
        self.window_end_ms = end_ms - HOUR_MS
        self.symbols = tuple(sorted(by_symbol))
        self._coins = by_symbol
        self._universes = months
        self._daily: dict[str, tuple[Kline, ...]] = {}
        self._funding = _funding_by_hour(by_symbol[symbol] for symbol in self.symbols)

    @classmethod
    def load(cls, data_dir: Path) -> Market:
        """The market of a data directory, every pack verified by its pin (module docstring)."""
        folder = Path(data_dir)
        header = _data_json(folder / DATA_FILE)
        packs = header.get("packs")
        if not isinstance(packs, dict):
            raise ValueError(f"{folder / DATA_FILE}: packs must be an object")
        daily = _pack(folder, packs.get("daily"), DAILY_FORMAT, "the daily pack", header)
        universes = _universes(daily)
        del daily  # only the universes are needed; the candidates' daily bars can go
        index = _pack(folder, packs.get("hourly_index"), INDEX_FORMAT, "the hourly index", header)
        listed, perpetuals = index.get("coins"), index.get("perpetuals")
        if not isinstance(listed, dict) or not isinstance(perpetuals, dict):
            raise ValueError("the hourly index: coins and perpetuals must be objects")
        unknown = sorted(set(perpetuals) - set(listed))
        if unknown:
            raise ValueError(f"the hourly index: perpetuals of coins it does not list: {unknown}")
        coins: list[Coin] = []
        for symbol in sorted(listed):
            label = f"the coin pack of {_symbol(symbol, 'the hourly index')}"
            record = listed[symbol]
            if not isinstance(record, dict) or record.get("file") != coin_pack_file(symbol):
                raise ValueError(f"{label}: the file must be {coin_pack_file(symbol)}")
            document = _pack(folder, record, COIN_FORMAT, label, header)
            if document.get("coin") != symbol:
                raise ValueError(f"{label} holds the coin {document.get('coin')!r:.40}")
            if document.get("perpetual") != perpetuals.get(symbol):
                raise ValueError(
                    f"{label}: its perpetual {document.get('perpetual')!r:.80} is not the "
                    f"index's {perpetuals.get(symbol)!r:.80}"
                )
            coins.append(_coin(document, symbol, label))
            del document  # one coin pack's document at a time
        return cls(end_month=header["end_month"], universes=universes, coins=coins)

    def universe(self, month: str) -> tuple[str, ...]:
        """The month's selected symbols in rank order; () for a month without a selection."""
        return self._universes.get(_month(month, "month"), ())

    def coin(self, symbol: str) -> Coin:
        found = self._coins.get(symbol)
        if found is None:
            raise ValueError(f"{symbol!r:.40} is not a coin of the packs")
        return found

    def daily(self, symbol: str) -> tuple[Kline, ...]:
        """The coin's UTC daily bars from its unmasked spot hours (V3's 20-of-24 day rule),
        with zero volumes. Built on the first call and cached."""
        bars = self._daily.get(symbol)
        if bars is None:
            hours = [
                Kline(bar.open_ms, bar.open, bar.high, bar.low, bar.close, _ZERO, _ZERO, _ZERO)
                for bar in self.coin(symbol).spot.bars()
            ]
            bars = self._daily[symbol] = daily_bars(hours)
        return bars

    def perpetual_eligible(self, symbol: str, decision_ms: int) -> bool:
        """Whether the coin has an eligible perpetual at ``decision_ms`` (spec "Universe"),
        judged point in time: its first bar is at or before the decision, it has a bar that
        opens in the 168 hours before it, and the decision's funding month is complete."""
        _instant(decision_ms, "decision_ms")
        perpetual = self.coin(symbol).perpetual
        if perpetual is None:
            return False
        first = perpetual.store.first_open_ms
        if first is None or first > decision_ms:
            return False
        last = perpetual.store.last_open_at_or_before(decision_ms - 1)
        if last is None or last < decision_ms - DEAD_MARKET_HOURS * HOUR_MS:
            return False
        return perpetual.months.get(_month_of(decision_ms)) == COMPLETE

    def funding_events(self, hour_open_ms: int) -> tuple[tuple[str, int, Decimal], ...]:
        """Every funding record in the hour that opens at ``hour_open_ms``, as (perpetual,
        time_ms, rate), in time order (then by perpetual, then as the pack lists them)."""
        if _instant(hour_open_ms, "hour_open_ms") % HOUR_MS:
            raise ValueError(f"{hour_open_ms} is not an hour's open")
        return self._funding.get(hour_open_ms, ())

    def funding_month(self, symbol: str, month: str) -> str | None:
        """The coin's perpetual's funding status for ``month``, or None without a perpetual or
        without a status for that month."""
        _month(month, "month")
        perpetual = self.coin(symbol).perpetual
        return None if perpetual is None else perpetual.months.get(month)


def _symbol(value: object, what: str) -> str:
    if not isinstance(value, str) or _SYMBOL.fullmatch(value) is None:
        raise ValueError(f"{what}: symbol must match [A-Z0-9]{{2,30}}, got {value!r:.40}")
    return value


def _month(value: object, what: str) -> str:
    if not isinstance(value, str) or _MONTH.fullmatch(value) is None:
        raise ValueError(f"{what} must be YYYY-MM, got {value!r:.40}")
    return value


def _instant(value: object, what: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{what} must be an int (ms), got {value!r:.40}")
    return value


def _month_of(ms: int) -> str:
    moment = datetime.fromtimestamp(ms // 1000, UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def _masked_opens(masked: Iterable[int]) -> frozenset[int]:
    opens = frozenset(masked)
    bad = next((value for value in opens if type(value) is not int), None)
    if bad is not None:
        raise ValueError(f"masked opens must be ints, got {bad!r:.40}")
    return opens


def _price(value: object, number: int, open_ms: int) -> Decimal:
    """Row ``number``'s price ``value``: a positive finite decimal string. The message is built
    only for a refusal, since a series has millions of prices."""
    try:
        price = Decimal(value) if isinstance(value, str) else None
    except InvalidOperation:
        price = None
    if price is None:
        raise ValueError(
            f"row {number} ({open_ms}): a price is a decimal string, got {value!r:.40}"
        )
    if not price.is_finite() or price <= 0:
        raise ValueError(
            f"row {number} ({open_ms}): a price must be finite and positive, got {value!r:.40}"
        )
    return price


def _places(price: Decimal) -> int:
    """The decimal places of ``price`` once trailing zeros are dropped."""
    try:
        exponent = price.normalize(_EXACT).as_tuple().exponent
    except DecimalException as exc:
        raise ValueError(f"price {price} has more digits than a series can hold") from exc
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _scaled(price: Decimal, places: int) -> int:
    return int(price.scaleb(places, _EXACT))  # exact: places is at least the price's decimals


def _column(values: list[int], places: int) -> array[int]:
    try:
        return array("q", values)
    except OverflowError:
        raise ValueError(f"prices scaled to {places} decimals do not fit 64-bit integers") from None


def _decimal(value: object, what: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError(f"{what}: a decimal string required, got {value!r:.40}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{what}: a decimal string required, got {value!r:.40}") from None
    if not number.is_finite():
        raise ValueError(f"{what}: a finite decimal required, got {value!r:.40}")
    return number


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _not_an_integer(text: str) -> object:
    raise ValueError(f"number {text} is not an integer")


def _data_json(path: Path) -> dict[str, Any]:
    """``data.json``: an ASCII JSON object of format ``DATA_FORMAT``, with no duplicate key and
    no float, naming the run (``config_sha256``, ``end_month``) its packs must carry."""
    try:
        document = json.loads(
            path.read_bytes().decode("ascii"),
            object_pairs_hook=_unique_keys,
            parse_float=_not_an_integer,
            parse_constant=_not_an_integer,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: not ASCII JSON ({exc})") from exc
    if not isinstance(document, dict):
        raise ValueError(f"{path}: the top level must be a JSON object")
    if document.get("format") != DATA_FORMAT:
        raise ValueError(f"{path}: format {document.get('format')!r:.40}, expected {DATA_FORMAT!r}")
    if not isinstance(document.get("config_sha256"), str):
        raise ValueError(f"{path}: config_sha256 must be a string")
    _month(document.get("end_month"), f"{path}: end_month")
    return document


def _pack(
    folder: Path, record: object, expected: str, label: str, header: Mapping[str, Any]
) -> dict[str, Any]:
    """The pack ``record`` names (``{file, sha256, json_bytes}``), read by its pin, once its
    format is ``expected`` and it is of the run ``header`` names."""
    if not isinstance(record, dict):
        raise ValueError(f"{label}: a record {{file, sha256, json_bytes}} required")
    file, pin = record.get("file"), record.get("sha256")
    if not isinstance(file, str) or _FILE.fullmatch(file) is None:
        raise ValueError(
            f"{label}: the file must be a plain name in the data directory, got {file!r:.60}"
        )
    if not isinstance(pin, str):
        raise ValueError(f"{label}: sha256 must be a string")
    document = read_canonical(folder / file, pin)
    if document.get("format") != expected:
        raise ValueError(
            f"{label} ({file}): format {document.get('format')!r:.40}, expected {expected!r}"
        )
    for key in ("config_sha256", "end_month"):
        if document.get(key) != header[key]:
            raise ValueError(
                f"{label} ({file}): {key} {document.get(key)!r:.70} is not data.json's "
                f"{header[key]!r:.70}"
            )
    return document


def _universes(daily: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    entries = daily.get("universes")
    if not isinstance(entries, list):
        raise ValueError("the daily pack: universes must be a list")
    universes: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("selected"), list):
            raise ValueError("the daily pack: each universe needs a month and a selected list")
        month = _month(entry.get("month"), "the daily pack: universe month")
        if month in universes:
            raise ValueError(f"the daily pack: universe {month} is listed twice")
        universes[month] = tuple(
            _symbol(symbol, f"the daily pack: universe {month}") for symbol in entry["selected"]
        )
    return universes


def _series(document: Mapping[str, Any], venue: str, label: str) -> SeriesStore:
    rows, masks = document.get(venue), document.get("masks")
    if not isinstance(rows, list) or not isinstance(masks, dict):
        raise ValueError(f"{label}: {venue} rows and masks required")
    mask = masks.get(venue)
    if not isinstance(mask, dict) or not isinstance(mask.get("masked"), list):
        raise ValueError(f"{label}: no {venue} mask (a missing entry is an error, never clean)")
    try:
        return SeriesStore.from_rows(rows, mask["masked"])
    except ValueError as exc:
        raise ValueError(f"{label}, {venue}: {exc}") from exc


def _rules(document: Mapping[str, Any], venue: str, label: str) -> VenueRules:
    rules = document.get("rules")
    entry = rules.get(venue) if isinstance(rules, dict) else None
    if not isinstance(entry, dict):
        raise ValueError(f"{label}: no {venue} rules")
    values = {name: _decimal(entry.get(name), f"{label} {venue} {name}") for name in _RULE_FIELDS}
    return VenueRules(**values)


def _funding(rows: object, label: str) -> tuple[tuple[int, Decimal], ...]:
    if not isinstance(rows, list):
        raise ValueError(f"{label}: funding must be a list")
    funding: list[tuple[int, Decimal]] = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int:
            raise ValueError(f"{label}: a funding row is [time_ms, rate, interval_hours]")
        funding.append((row[0], _decimal(row[1], f"{label} funding rate")))
    return tuple(funding)


def _funding_months(months: object, label: str) -> Mapping[str, str]:
    if not isinstance(months, dict) or not all(
        isinstance(month, str) and isinstance(status, str) for month, status in months.items()
    ):
        raise ValueError(f"{label}: funding_months must map months to statuses")
    return MappingProxyType(dict(months))


def _coin(document: Mapping[str, Any], symbol: str, label: str) -> Coin:
    spot = _series(document, "spot", label)
    entry = document.get("perpetual")
    perpetual = None
    if entry is not None:
        multiplier = entry.get("multiplier") if isinstance(entry, dict) else None
        if type(multiplier) is not int:
            raise ValueError(f"{label}: the perpetual must be {{symbol, multiplier}} or null")
        perpetual = Perpetual(
            symbol=_symbol(entry.get("symbol"), f"{label} perpetual"),
            multiplier=multiplier,  # Perpetual checks that it is positive
            store=_series(document, "futures", label),
            funding=_funding(document.get("funding"), label),
            months=_funding_months(document.get("funding_months"), label),
            rules=_rules(document, "futures", label),
        )
    return Coin(symbol, spot, _rules(document, "spot", label), perpetual)


def _funding_by_hour(coins: Iterable[Coin]) -> dict[int, tuple[tuple[str, int, Decimal], ...]]:
    """Every perpetual's funding records grouped by the open of the hour they fall in, each
    hour's in time order, then by perpetual; the sort is stable, so ties keep the pack order."""
    hours: dict[int, list[tuple[str, int, Decimal]]] = {}
    for coin in coins:
        if coin.perpetual is None:
            continue
        for time_ms, rate in coin.perpetual.funding:
            hours.setdefault(time_ms - time_ms % HOUR_MS, []).append(
                (coin.perpetual.symbol, time_ms, rate)
            )
    return {
        hour: tuple(sorted(events, key=lambda event: (event[1], event[0])))
        for hour, events in hours.items()
    }
