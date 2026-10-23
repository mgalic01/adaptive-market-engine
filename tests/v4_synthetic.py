"""Synthetic V4 data packs for the engine's tests: small worlds written through ``pack.py``'s own
builders, so the engine reads them exactly as it will read the step-2 packs.

A world is a few coins over a few months, with the universe given month by month (it is not
computed from volumes). Each coin has a spot series and, optionally, a USDT-M perpetual. A
series is a run of hourly closes from ``start_ms``, one per hour. Each bar opens at the previous
close (the first at its own close), and its high and low are the body, widened by ``wick`` or
set for one hour through ``extremes``. Any date may be used, 2025 and later included.

    from v4_synthetic import CoinSpec, PerpetualSpec, Series, World, every_month, month_start
    from v4_synthetic import path, write_world

    btc = CoinSpec(
        "BTCUSDT",
        Series(month_start("2025-01"), path("50000", (24 * 59, "0.0004"), noise="0.004")),
        perpetual=PerpetualSpec(),
    )
    world = World("2025-02", (btc,), every_month("2025-01", "2025-02", ("BTCUSDT",)))
    market = Market.load(write_world(tmp_path, world))

What later tests need, and how to get it:

* a steady uptrend or downtrend: ``path(start, (hours, rate))`` with a small ``noise``. Sizing
  gives a coin whose daily returns never vary (sigma 0) no weight, so a trend that should
  trade needs some noise;
* a crash: a short leg with a large negative rate, ``path("100", (720, "0.001"), (1, "-0.5"))``,
  and ``extremes`` for an intrahour low or high;
* a coin that stops trading (a delisting): a series whose closes end early. A perpetual that
  dies while spot still trades: ``PerpetualSpec(series=...)`` with fewer closes;
* a multiplier perpetual: ``PerpetualSpec(multiplier=1000)`` on ``SHIBUSDT`` is
  ``1000SHIBUSDT``. Its default series is the spot closes times the multiplier;
* masked hours: ``Series(masked=...)`` writes the rows and lists them as masked, and
  ``Series(missing=...)`` writes no row at all (a gap, which the pack contract also treats as
  masked). A masked day is five or more such hours of one UTC day (``day_hours`` helps);
* an incomplete funding month: ``PerpetualSpec(months={"2025-03": "missing_slot"})``. By
  default every month of the perpetual's kline span is ``"complete"``, with a funding record
  at each 00:00, 08:00 and 16:00 UTC slot inside the span at ``funding_rate``.
  ``PerpetualSpec(funding=[FundingRow(...)])`` writes those rows instead, in the order given.

``write_world(root, world)`` writes ``root / "data"``: the daily pack (the universes, and no
daily bars: the engine reads only the universes from it), one coin pack per coin, the hourly
index and ``data.json``, the same files and keys as ``scripts/v4_data.py``'s ``pack`` stage.
``repack`` rewrites one written pack and re-pins it up the chain, so that a test can hand the
loader a pack that is validly pinned but wrong in one place.

The manifests are empty (no archive was read) and ``config_sha256`` is ``CONFIG_SHA256``, a
fixed digest that no real config has. Nothing here touches the network or a real pack.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import random
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.archives import KINDS
from crypto_grid_bot.v4.data.bars import FundingRow, HourBar
from crypto_grid_bot.v4.data.config import load_data_config
from crypto_grid_bot.v4.data.config import months as month_range
from crypto_grid_bot.v4.data.pack import (
    coin_pack_document,
    coin_pack_file,
    daily_pack_document,
    hourly_index_document,
    write_canonical,
)
from crypto_grid_bot.v4.data.universe import MonthlyUniverse

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "v4_data.json"
CONFIG_SHA256 = hashlib.sha256(b"v4 synthetic world").hexdigest()
# The file names scripts/v4_data.py writes.
DATA_FORMAT = "v4-data/1"
DATA_FILE = "data.json"
DAILY_PACK = "daily.pack.json.gz"
HOURLY_INDEX = "hourly-index.json.gz"

HOUR = 3_600_000
DAY = 24 * HOUR
FUNDING_INTERVAL_HOURS = 8
VOLUME = Decimal("1000")  # every bar's base volume; the engine reads no volume

SPOT_RULES = VenueRules(
    step=Decimal("0.00001"),
    min_qty=Decimal("0.00001"),
    max_qty=Decimal("9000"),
    min_notional=Decimal("5"),
    tick=Decimal("0.00000001"),
)
FUTURES_RULES = VenueRules(
    step=Decimal("0.001"),
    min_qty=Decimal("0.001"),
    max_qty=Decimal("1000000"),
    min_notional=Decimal("5"),
    tick=Decimal("0.00000001"),
)

_WIDE = Context(prec=60, rounding=ROUND_HALF_EVEN)

Price = Decimal | str


def month_start(month: str) -> int:
    """00:00 UTC on the first day of ``month`` (``"YYYY-MM"``), in ms."""
    return month_bounds_ms(month)[0]


def month_of(ms: int) -> str:
    """The UTC month (``"YYYY-MM"``) that ``ms`` falls in."""
    moment = datetime.fromtimestamp(ms // 1000, UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def hours_in(first: str, last: str) -> int:
    """The number of hours from the start of ``first`` to the end of ``last``."""
    return (month_bounds_ms(last)[1] - month_start(first)) // HOUR


def day_hours(day_ms: int, hours: Collection[int]) -> tuple[int, ...]:
    """The opens of the given hours (0 to 23) of the UTC day that starts at ``day_ms``."""
    if day_ms % DAY:
        raise ValueError(f"{day_ms} is not 00:00 UTC")
    return tuple(day_ms + hour * HOUR for hour in sorted(hours))


def every_month(first: str, last: str, selected: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """The same universe, ``selected`` in rank order, for every month ``first`` to ``last``."""
    return {month: tuple(selected) for month in month_range(first, last)}


def path(
    start: Price,
    *legs: tuple[int, Price],
    noise: Price = "0",
    seed: int = 0,
    places: int = 8,
) -> tuple[Decimal, ...]:
    """Hourly closes: for each leg ``(hours, rate)``, ``hours`` closes, each the previous one
    (``start`` before the first) times ``1 + rate + noise x u``, rounded half-even to ``places``
    decimals. ``u`` is -1, 0 or 1, drawn from ``random.Random(seed)`` with integers only, so a
    path is the same on every machine. A close that rounds to zero or below is refused.
    """
    rng = random.Random(seed)
    quantum = Decimal(1).scaleb(-places)
    price, wobble = Decimal(start), Decimal(noise)
    closes: list[Decimal] = []
    with localcontext(_WIDE):
        for hours, rate in legs:
            drift = Decimal(rate)
            for _ in range(hours):
                step = drift + wobble * (rng.randrange(3) - 1)
                price = (price * (1 + step)).quantize(quantum)
                if price <= 0:
                    raise ValueError(f"the path reaches {price} after {len(closes)} closes")
                closes.append(price)
    return tuple(closes)


def _places(value: Decimal) -> int:
    exponent = value.normalize(_WIDE).as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


@dataclass(frozen=True)
class Series:
    """One venue's hourly bars: ``closes[k]`` is the close of the hour that opens at
    ``start_ms + k`` hours.

    * ``masked``: opens whose row is written and also listed as masked, as a repaired row is;
    * ``missing``: opens with no row at all, a gap inside the series;
    * ``extremes``: open -> (high, low) for chosen hours, which must contain the body;
    * ``wick``: every other bar's high and low extend this fraction beyond its body, rounded
      outwards to the body's decimals.
    """

    start_ms: int
    closes: Sequence[Price]
    masked: Collection[int] = ()
    missing: Collection[int] = ()
    extremes: Mapping[int, tuple[Price, Price]] = field(default_factory=dict)
    wick: Price = "0"

    @property
    def end_ms(self) -> int:
        """The open of the hour after the last one."""
        return self.start_ms + len(self.closes) * HOUR

    def opens(self) -> range:
        """Every hour's open, rows or not."""
        return range(self.start_ms, self.end_ms, HOUR)

    def times(self, factor: int) -> Series:
        """The same hours with every close times ``factor`` and no mask: a perpetual's default
        series, in contract units."""
        with localcontext(_WIDE):
            closes = tuple(Decimal(close) * factor for close in self.closes)
        return replace(self, closes=closes, masked=(), missing=(), extremes={})

    def bars(self) -> list[HourBar]:
        """The rows of the series as the pack holds them: every hour but the missing ones."""
        if self.start_ms % HOUR:
            raise ValueError(f"series start {self.start_ms} is not on an hour")
        if not self.closes:
            raise ValueError("a series needs at least one close")
        span = range(self.start_ms, self.end_ms, HOUR)
        for name, opens in (("masked", self.masked), ("missing", self.missing)):
            stray = sorted(set(opens) - set(span))
            if stray:
                raise ValueError(f"{name} opens outside the series: {stray[:3]}")
        stray = sorted(set(self.extremes) - set(span) - set(self.missing))
        if stray:
            raise ValueError(f"extremes outside the series' rows: {stray[:3]}")
        missing, wick = frozenset(self.missing), Decimal(self.wick)
        bars: list[HourBar] = []
        with localcontext(_WIDE):
            previous = Decimal(self.closes[0])
            for open_ms, raw in zip(span, self.closes, strict=True):
                open_, close = previous, Decimal(raw)
                previous = close
                if open_ms in missing:
                    continue
                high, low = max(open_, close), min(open_, close)
                if open_ms in self.extremes:
                    high, low = (Decimal(value) for value in self.extremes[open_ms])
                elif wick:
                    quantum = Decimal(1).scaleb(-max(_places(open_), _places(close)))
                    high = (high * (1 + wick)).quantize(quantum, ROUND_CEILING)
                    low = (low * (1 - wick)).quantize(quantum, ROUND_FLOOR)
                if not 0 < low <= min(open_, close) <= max(open_, close) <= high:
                    raise ValueError(f"bar {open_ms}: low {low} and high {high} must hold the body")
                bars.append(
                    HourBar(open_ms, open_, high, low, close, close * VOLUME, volume=VOLUME)
                )
        return bars

    def mask(self) -> tuple[list[int], dict[str, str], list[str]]:
        """The series' entry in a pack's ``masks``: (masked opens, unreadable, absent)."""
        return sorted(set(self.masked)), {}, []


@dataclass(frozen=True)
class PerpetualSpec:
    """A coin's USDT-M perpetual. ``symbol`` defaults to the coin's own name for multiplier 1
    and to the multiplier's prefix plus it otherwise (``1000SHIBUSDT``); ``series`` defaults to
    the spot closes times the multiplier, over the same hours and with no mask. ``months``
    overrides the generated statuses (``"complete"`` for each month of the kline span), and may
    name other months too."""

    multiplier: int = 1
    series: Series | None = None
    funding_rate: Price = "0.0001"
    funding: Sequence[FundingRow] | None = None
    months: Mapping[str, str] = field(default_factory=dict)
    rules: VenueRules = FUTURES_RULES
    symbol: str | None = None

    def name(self, coin: str) -> str:
        """The perpetual's symbol for ``coin``."""
        if self.symbol is not None:
            return self.symbol
        return coin if self.multiplier == 1 else f"{self.multiplier}{coin}"

    def series_for(self, spot: Series) -> Series:
        """The perpetual's series: ``series``, or the coin's ``spot`` times the multiplier."""
        return spot.times(self.multiplier) if self.series is None else self.series

    def funding_rows(self, series: Series) -> list[FundingRow]:
        """The rows written: ``funding`` if given, else one record at each slot from the first
        open to the last close."""
        if self.funding is not None:
            return list(self.funding)
        slot = FUNDING_INTERVAL_HOURS * HOUR
        first = -(-series.start_ms // slot) * slot  # the first slot at or after the first open
        rate = Decimal(self.funding_rate)
        return [
            FundingRow(time_ms, rate, FUNDING_INTERVAL_HOURS)
            for time_ms in range(first, series.end_ms, slot)
        ]

    def funding_months(self, series: Series) -> dict[str, str]:
        span = month_range(month_of(series.start_ms), month_of(series.end_ms - 1))
        return {month: "complete" for month in span} | dict(self.months)


@dataclass(frozen=True)
class CoinSpec:
    """One coin: its spot symbol and series, and optionally its perpetual."""

    symbol: str
    spot: Series
    perpetual: PerpetualSpec | None = None
    spot_rules: VenueRules = SPOT_RULES


@dataclass(frozen=True)
class World:
    """Every coin, and the universe: month -> the selected symbols in rank order, written as
    given (sorted by month; a month may have an empty selection, and a month left out has no
    universe entry). No series may run past ``end_month``."""

    end_month: str
    coins: Sequence[CoinSpec]
    universes: Mapping[str, Sequence[str]]


def _universes(world: World) -> list[MonthlyUniverse]:
    result: list[MonthlyUniverse] = []
    previous: tuple[str, ...] = ()
    for month in sorted(world.universes):
        selected = tuple(world.universes[month])
        count = len(selected)
        result.append(
            MonthlyUniverse(
                month=month,
                selected=selected,
                ranked=tuple(
                    (symbol, Decimal(1000 * (count - rank)), 30)
                    for rank, symbol in enumerate(selected)
                ),
                excluded=(),
                entered=tuple(symbol for symbol in selected if symbol not in previous),
                left=tuple(symbol for symbol in previous if symbol not in selected),
            )
        )
        previous = selected
    return result


def _json_bytes(target: Path) -> int:
    with gzip.open(target, "rb") as stream:
        return len(stream.read())


def _write_pack(target: Path, document: Mapping[str, Any]) -> dict[str, Any]:
    """Write one pack and return its record as data.json and the index hold it."""
    pin = write_canonical(document, target)
    return {"file": target.name, "sha256": pin, "json_bytes": _json_bytes(target)}


def _write_data_json(data_dir: Path, document: Mapping[str, Any]) -> None:
    target = data_dir / DATA_FILE
    target.unlink(missing_ok=True)
    with target.open("x", encoding="ascii", newline="\n") as handle:
        handle.write(json.dumps(document, indent=1, sort_keys=True) + "\n")


def write_world(root: Path, world: World) -> Path:
    """Write ``world``'s packs and ``data.json`` to a new folder ``root / "data"`` and return
    it. Every pack goes through ``pack.py``'s builders, which check what they write."""
    config = replace(load_data_config(CONFIG_PATH), end_month=world.end_month)
    end_ms = month_bounds_ms(world.end_month)[1]
    data_dir = Path(root) / "data"
    data_dir.mkdir(parents=True)
    coins: dict[str, tuple[str, str, int]] = {}
    perpetuals: dict[str, dict[str, object]] = {}
    rows = 0
    for spec in world.coins:
        spot = spec.spot.bars()
        if spec.spot.end_ms > end_ms:
            raise ValueError(f"{spec.symbol}: the spot series runs past {world.end_month}")
        masks = {"spot": spec.spot.mask()}
        rules = {"spot": (spec.spot_rules, "present_day")}
        entry: dict[str, object] | None = None
        futures: list[HourBar] = []
        funding: list[FundingRow] = []
        funding_months: dict[str, str] = {}
        if spec.perpetual is not None:
            series = spec.perpetual.series_for(spec.spot)
            if series.end_ms > end_ms:
                raise ValueError(f"{spec.symbol}: the perpetual runs past {world.end_month}")
            entry = {
                "symbol": spec.perpetual.name(spec.symbol),
                "multiplier": spec.perpetual.multiplier,
            }
            futures = series.bars()
            funding = spec.perpetual.funding_rows(series)
            funding_months = spec.perpetual.funding_months(series)
            masks["futures"] = series.mask()
            rules["futures"] = (spec.perpetual.rules, "present_day")
            perpetuals[spec.symbol] = entry
        document = coin_pack_document(
            config,
            [],
            coin=spec.symbol,
            spot=spot,
            perpetual=entry,
            futures=futures,
            masks=masks,
            funding=funding,
            funding_months=funding_months,
            rules=rules,
            config_sha256=CONFIG_SHA256,
        )
        record = _write_pack(data_dir / coin_pack_file(spec.symbol), document)
        coins[spec.symbol] = (record["sha256"], record["file"], record["json_bytes"])
        rows += len(spot) + len(futures)
    universes = _universes(world)
    daily = daily_pack_document(
        config, [], {}, {}, universes, masks={}, config_sha256=CONFIG_SHA256
    )
    index = hourly_index_document(
        config, coins=coins, perpetuals=perpetuals, config_sha256=CONFIG_SHA256
    )
    packs = {
        "daily": _write_pack(data_dir / DAILY_PACK, daily),
        "hourly_index": _write_pack(data_dir / HOURLY_INDEX, index),
    }
    selected = {symbol for symbol_list in world.universes.values() for symbol in symbol_list}
    _write_data_json(
        data_dir,
        {
            "format": DATA_FORMAT,
            "config_sha256": CONFIG_SHA256,
            "end_month": world.end_month,
            "packs": packs,
            "archives": dict.fromkeys(KINDS, 0),
            "universe_months": len(universes),
            "selected_symbols": len(selected),
            "coin_packs": len(coins),
            "largest_coin_pack_json_bytes": max((size for _, _, size in coins.values()), default=0),
            "hourly_rows": rows,
            "perpetuals": len(perpetuals),
            "multiplier_perpetuals": sum(e["multiplier"] != 1 for e in perpetuals.values()),
        },
    )
    return data_dir


def read_pack(target: Path) -> dict[str, Any]:
    """A pack's document, read without its pin (for tests that change one)."""
    with gzip.open(target, "rb") as stream:
        document: dict[str, Any] = json.loads(stream.read())
    return document


def read_data_json(data_dir: Path) -> dict[str, Any]:
    """A written world's ``data.json``."""
    document: dict[str, Any] = json.loads((data_dir / DATA_FILE).read_text(encoding="ascii"))
    return document


def write_data_json(data_dir: Path, document: Mapping[str, Any]) -> None:
    """Replace ``data.json`` with ``document``, written as the data step writes it."""
    _write_data_json(data_dir, document)


def repack(data_dir: Path, file: str, change: Callable[[dict[str, Any]], None]) -> None:
    """Rewrite the pack ``file`` of a written world with ``change`` applied to its document,
    then re-pin it up the chain: a coin pack in the index, and the index or the daily pack in
    ``data.json``. Only what ``change`` did differs, and every pin is right."""
    data = read_data_json(data_dir)
    target = data_dir / file
    document = read_pack(target)
    change(document)
    target.unlink()
    record = _write_pack(target, document)
    packs = data["packs"]
    if file in (packs["daily"]["file"], packs["hourly_index"]["file"]):
        key = "daily" if file == packs["daily"]["file"] else "hourly_index"
        packs[key] = record
    else:
        index_path = data_dir / packs["hourly_index"]["file"]
        index = read_pack(index_path)
        coin = next(coin for coin, entry in index["coins"].items() if entry["file"] == file)
        index["coins"][coin] = record
        index_path.unlink()
        packs["hourly_index"] = _write_pack(index_path, index)
    _write_data_json(data_dir, data)
