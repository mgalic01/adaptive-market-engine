"""Synthetic V4 data packs: small worlds for the engine's tests, and the rehearsal and timing
worlds of step 4b, written through ``pack.py``'s own builders, so the engine reads them exactly
as it will read the step-2 packs. The module was ``tests/v4_synthetic.py`` (which re-exports it).

A world is a few coins over a few months, with the universe given month by month (it is not
computed from volumes). Each coin has a spot series and, optionally, a USDT-M perpetual. A
series is a run of hourly closes from ``start_ms``, one per hour. Each bar opens at the previous
close (the first at its own close), and its high and low are the body, widened by ``wick`` or
set for one hour through ``extremes``. Any date may be used, 2025 and later included.

    from crypto_grid_bot.v4.synthetic import CoinSpec, PerpetualSpec, Series, World
    from crypto_grid_bot.v4.synthetic import every_month, month_start, path, write_world

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

**The rehearsal and timing worlds** (step 4b; ``scripts/v4_rehearsal.py`` writes them). They are
synthetic, labelled so by that digest, and never hold a real price.

* ``rehearsal_world()``: four coins over 2020-01 to 2025-03, with universes from 2020-09, so the
  window covers V3's period and 2025-01-01.
  BTCUSDT, ETHUSDT and SOLUSDT have perpetuals; XRPUSDT is spot only and is delisted after
  2023-06 (a dead market). BTC rises, falls and rises again, so its slow vote takes both signs.
  ``rehearsal_v3_fields()`` and ``REHEARSAL_PICKS`` are V3's side of the same rehearsal: the
  fields of a V3 input pack (BTCUSDT and ETHUSDT, 2020-10 to the end of 2024) and the picks a
  stand-in walk-forward returns.
* ``timing_world(coins, first, window_first, last)``: a world of the real pack's size, 80 coins
  and about 7 million hourly rows at the defaults, for the timing run. Its coins are built one at
  a time, when asked for, so the world itself is cheap to make and to inspect (``timing_rows``
  counts its rows without building a price); only ``write_world`` is heavy.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import random
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Context, Decimal, localcontext
from pathlib import Path
from typing import Any, overload

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.combined.assessment import daily_bars
from crypto_grid_bot.combined.driver.v3_pack import V3PackFields
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.trend.filters import OrderFilters
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
from crypto_grid_bot.v4.engine.v3_as_built import V3_END_MS, V3_START_MS

ROOT = Path(__file__).resolve().parents[3]  # the checkout: src/crypto_grid_bot/v4/synthetic.py
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
    rng = random.Random(seed)  # nosec B311
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


# ---- the rehearsal world ------------------------------------------------------------------------

REHEARSAL_FIRST = "2020-01"  # the first month of every rehearsal coin's spot history
REHEARSAL_WINDOW_FIRST = "2020-09"  # the first universe month, so the first window hour
REHEARSAL_LAST = "2025-03"  # the world's end_month, so the last window hour is 2025-03-31 23:00
XRP_LAST = "2023-06"  # XRPUSDT's last month: its closes end at 2023-06-30 23:00 and it is delisted
_REHEARSAL_WICK = "0.002"


def _legs(*turns: tuple[str, str, str]) -> tuple[tuple[int, str], ...]:
    """Legs ``(hours, rate)`` for the months ``(first, last, rate)`` that follow one another."""
    return tuple((hours_in(first, last), rate) for first, last, rate in turns)


def rehearsal_world() -> World:
    """The rehearsal's world (module docstring). Prices are exact, seeded, and the same on every
    machine. The three swings of BTCUSDT (up to 2021-11, down to 2022-12, up again) make its slow
    vote (close against its 200-day SMA) +1 for years and -1 for months inside the window."""

    def series(start: str, *legs: tuple[int, str], noise: str, seed: int) -> Series:
        closes = path(start, *legs, noise=noise, seed=seed)
        return Series(month_start(REHEARSAL_FIRST), closes, wick=_REHEARSAL_WICK)

    btc = CoinSpec(
        "BTCUSDT",
        series(
            "7000",
            *_legs(
                (REHEARSAL_FIRST, "2021-11", "0.000124"),  # up about 8 times
                ("2021-12", "2022-12", "-0.00011"),  # down to about a third
                ("2023-01", REHEARSAL_LAST, "0.00007"),  # up about 4 times
            ),
            noise="0.003",
            seed=11,
        ),
        PerpetualSpec(),
    )
    eth = CoinSpec(
        "ETHUSDT",
        series(
            "130",
            *_legs(
                (REHEARSAL_FIRST, "2021-11", "0.000192"),
                ("2021-12", "2022-12", "-0.000146"),
                ("2023-01", REHEARSAL_LAST, "0.00007"),
            ),
            noise="0.004",
            seed=12,
        ),
        PerpetualSpec(),
    )
    sol = CoinSpec(
        "SOLUSDT",
        series(
            "1.5",
            *_legs(
                (REHEARSAL_FIRST, "2021-11", "0.000233"),
                ("2021-12", "2022-12", "-0.000242"),
                ("2023-01", REHEARSAL_LAST, "0.000091"),
            ),
            noise="0.005",
            seed=13,
        ),
        PerpetualSpec(),
    )
    xrp = CoinSpec(  # spot only; the closes stop at 2023-06-30 23:00
        "XRPUSDT",
        series(
            "0.25",
            *_legs(
                (REHEARSAL_FIRST, "2021-11", "0.00005"),
                ("2021-12", "2022-12", "-0.00007"),
                ("2023-01", XRP_LAST, "-0.00005"),
            ),
            noise="0.004",
            seed=14,
        ),
    )
    everyone = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    universes = every_month(REHEARSAL_WINDOW_FIRST, XRP_LAST, everyone)
    universes |= every_month("2023-07", REHEARSAL_LAST, everyone[:3])
    return World(REHEARSAL_LAST, (btc, eth, sol, xrp), universes)


# V3's side of the rehearsal: the fields of a V3 input pack and the picks a stand-in
# walk-forward returns. ``scripts/v31_smoke.py`` builds the same two for its W1 window.
V3_FIRST_MONTH = "2020-10"
V3_SYMBOLS = ("BTCUSDT", "ETHUSDT")
_V3_FILTERS = OrderFilters(
    *(
        Decimal(value)
        for value in ("0.001", "100000", "0.001", "5", "0.001", "100000", "0.001", "0")
    )
)
# A pick long before the window, the one in force at its start, a change inside it, and None for
# its last day. Every stamp is 00:00 UTC and before 2025-01-01, as the frozen replay and
# ``read_v3_picks`` require; no pick can come after ``V3_END_MS``, so the last one is a day before.
REHEARSAL_PICKS: dict[int, str | None] = {
    V3_START_MS - 40 * DAY: "R1",
    V3_START_MS - DAY: "R2L",
    V3_START_MS + 365 * DAY: "R3L",
    V3_END_MS - DAY: None,
}


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _v3_hourly(points: Sequence[Decimal], start_ms: int, wick: str) -> tuple[Kline, ...]:
    """V3's hourly bars between consecutive ``points`` (the open of each is the one before its
    close), with symmetric wicks of ``wick``, as ``v31_smoke.hourly`` builds them."""
    up, down = 1 + Decimal(wick), 1 - Decimal(wick)
    bars: list[Kline] = []
    with localcontext(Context()):
        for index, (open_, close) in enumerate(zip(points, points[1:], strict=False)):
            bars.append(
                Kline(
                    start_ms + index * HOUR,
                    _cents(open_),
                    _cents(max(open_, close) * up),
                    _cents(min(open_, close) * down),
                    _cents(close),
                    Decimal(10),
                    Decimal(1000),
                    Decimal(5),
                )
            )
    return tuple(bars)


def rehearsal_v3_fields() -> V3PackFields:
    """The fields of V3's input pack for the rehearsal: BTCUSDT and ETHUSDT, hourly from
    2020-10-01 00:00 to ``V3_END_MS - HOUR`` (V3's frozen code refuses 2025 on), as
    ``v31_smoke.v3_fields`` builds them, but over bounded paths: both coins stay between about 90
    and 800 (a steady ``1.0006 ** i`` would grow past 10 ** 11 over these four years)."""
    start_ms = month_start(V3_FIRST_MONTH)
    last = "2024-12"
    swings = {
        "BTCUSDT": (
            "100",
            _legs(
                (V3_FIRST_MONTH, "2021-12", "0.000163"),
                ("2022-01", "2022-12", "-0.000105"),
                ("2023-01", last, "0.000079"),
            ),
            "0.003",
            21,
        ),
        "ETHUSDT": (
            "400",
            _legs(
                (V3_FIRST_MONTH, "2021-09", "-0.00012"),
                ("2021-10", "2022-12", "0.000163"),
                ("2023-01", "2023-06", "-0.00016"),
                ("2023-07", last, "0.000083"),
            ),
            "0.003",
            22,
        ),
    }
    spot: dict[str, tuple[Kline, ...]] = {}
    futures: dict[str, tuple[Kline, ...]] = {}
    for symbol, (first, legs, noise, seed) in swings.items():
        points = (Decimal(first), *path(first, *legs, noise=noise, seed=seed, places=2))
        if len(points) != (V3_END_MS - start_ms) // HOUR + 1:
            raise ValueError(f"{symbol}: the path does not cover the pack's hours")
        spot[symbol] = _v3_hourly(points, start_ms, "0.01")
        futures[symbol] = _v3_hourly(points, start_ms, "0.02")
    slot = FUNDING_INTERVAL_HOURS * HOUR
    rates = {
        time_ms: dict.fromkeys(V3_SYMBOLS, Decimal("0.0001"))
        for time_ms in range(start_ms // slot * slot, V3_END_MS, slot)
    }
    return V3PackFields(
        first_months=dict.fromkeys(V3_SYMBOLS, V3_FIRST_MONTH),
        spot_bars={symbol: daily_bars(bars) for symbol, bars in spot.items()},
        spot_exclusions=dict.fromkeys(V3_SYMBOLS, frozenset()),
        futures_exclusions=dict.fromkeys(V3_SYMBOLS, frozenset()),
        futures_filters=dict.fromkeys(V3_SYMBOLS, _V3_FILTERS),
        futures_hourly=futures,
        funding=rates,
    )


# ---- the timing world ---------------------------------------------------------------------------

_TIMING_LATE = "2024-06"  # the last month in which a timing coin can be listed
_TIMING_CORE = 9  # the coins besides BTCUSDT listed before the window opens: its first universe
_TIMING_MULTIPLIER = 1000
_TIMING_MULTIPLIER_COINS = 4
_TIMING_UNIVERSE = 10


@dataclass(frozen=True)
class _Listing:
    """One timing coin: its months of bars, its perpetual's multiplier (None: spot only) and the
    start, drift and seed of its price path."""

    symbol: str
    first_month: str
    last_month: str
    multiplier: int | None
    start: Decimal
    drift: Decimal
    seed: int

    def hours(self) -> int:
        return hours_in(self.first_month, self.last_month)

    def rows(self) -> int:
        """The hourly rows ``write_world`` writes for the coin: spot, and its perpetual's."""
        return self.hours() * (1 if self.multiplier is None else 2)


def _timing_listings(
    coins: int, first: str, window_first: str, last: str
) -> tuple[tuple[str, ...], list[_Listing]]:
    """The months from ``first`` to ``last`` and every coin's listing. BTCUSDT lists in ``first``.
    The next nine coins list in the months before ``window_first``, so that the first universe
    has 10 coins, and the rest one after another from ``window_first`` to 2024-06 (or ``last``).
    Three coins of four have a perpetual (BTCUSDT's the first), four of them in contracts of 1000
    coins, and one coin of eight stops trading after a month of the window, a delisting."""
    if coins < 2:
        raise ValueError("a timing world needs at least 2 coins")
    if not first < window_first <= last:
        raise ValueError(f"first {first}, window_first {window_first}, last {last}: not in order")
    months = month_range(first, last)
    opening = months.index(window_first)
    late = months.index(min(_TIMING_LATE, last))
    others = coins - 1
    core = min(_TIMING_CORE, others)
    rest = others - core
    span = late - opening + 1
    with_perpetual = [k for k in range(1, others + 1) if k % 4 != 0]
    wide = {
        with_perpetual[position * len(with_perpetual) // _TIMING_MULTIPLIER_COINS]
        for position in range(min(_TIMING_MULTIPLIER_COINS, len(with_perpetual)))
    }
    listings = [_Listing("BTCUSDT", first, last, 1, Decimal("4000"), Decimal("0.00003"), 1000)]
    for k in range(1, others + 1):
        listed = (k - 1) * opening // core if k <= core else opening + span * (k - core - 1) // rest
        ended = len(months) - 1
        if k % 8 == 0:
            earliest, latest = max(opening + 1, listed + 1), len(months) - 2
            if latest >= earliest:
                ended = earliest + k * 37 % (latest - earliest + 1)
        multiplier = None if k % 4 == 0 else (_TIMING_MULTIPLIER if k in wide else 1)
        price = Decimal(2 + k * 17 % 7) / 100 if k in wide else Decimal(5 + k * 17 % 90) / 10
        drift = Decimal(k * 13 % 11 - 5) / 100_000
        listings.append(
            _Listing(
                f"S{k:02d}USDT", months[listed], months[ended], multiplier, price, drift, 1000 + k
            )
        )
    return months, listings


def _timing_universes(
    months: Sequence[str], window_first: str, listings: Sequence[_Listing]
) -> dict[str, tuple[str, ...]]:
    """Each month from ``window_first``: the 10 listed coins that still trade, with the highest
    score, best first (fewer if fewer are). A score is the coin's own, fixed draw plus three times
    a seeded draw of the month, so the ranking turns over fast and most coins are selected at some
    point (as every coin of the real pack is); BTCUSDT's score is higher than any."""
    own = {item.symbol: random.Random(item.seed).random() for item in listings}  # nosec B311
    own["BTCUSDT"] = math.inf  # it ranks first in every month
    universes: dict[str, tuple[str, ...]] = {}
    for index, month in enumerate(months):
        if month < window_first:
            continue
        draws = random.Random(7_000_000 + index)  # nosec B311
        scores = {item.symbol: own[item.symbol] + 3 * draws.random() for item in listings}
        trading = [item for item in listings if item.first_month <= month <= item.last_month]
        best = sorted(trading, key=lambda item: -scores[item.symbol])[:_TIMING_UNIVERSE]
        universes[month] = tuple(item.symbol for item in best)
    return universes


def _timing_coin(item: _Listing) -> CoinSpec:
    closes = path(item.start, (item.hours(), item.drift), noise="0.004", seed=item.seed)
    perpetual = None if item.multiplier is None else PerpetualSpec(multiplier=item.multiplier)
    return CoinSpec(item.symbol, Series(month_start(item.first_month), closes), perpetual)


class _TimingCoins(Sequence[CoinSpec]):
    """The timing world's coins, each built (its whole price path) when it is asked for and not
    kept: a world of 80 coins is then cheap to make, and ``write_world`` holds one at a time.

    Its iteration is its own, over the listings: ``Sequence``'s default ``__iter__`` calls
    ``self[i]`` until an ``IndexError``, so an ``IndexError`` raised while building a coin would
    end the world there, silently, with the coins after it missing. Here it propagates."""

    def __init__(self, listings: Sequence[_Listing]) -> None:
        self._listings = tuple(listings)

    def __len__(self) -> int:
        return len(self._listings)

    def __iter__(self) -> Iterator[CoinSpec]:
        for item in self._listings:
            yield _timing_coin(item)

    @overload
    def __getitem__(self, index: int) -> CoinSpec: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[CoinSpec]: ...

    def __getitem__(self, index: int | slice) -> CoinSpec | Sequence[CoinSpec]:
        if isinstance(index, slice):
            return [self[position] for position in range(*index.indices(len(self)))]
        return _timing_coin(self._listings[index])


def timing_world(
    coins: int = 80,
    first: str = "2017-08",
    window_first: str = "2018-04",
    last: str = "2026-09",
) -> World:
    """The timing run's world: ``coins`` coins (BTCUSDT, then ``S01USDT``, ``S02USDT`` and so on)
    with bars from ``first`` (BTCUSDT) or later, universes from ``window_first`` to ``last``.
    At the defaults it holds 80 coins, 61 perpetuals (4 of them in contracts of 1000 coins) and
    about 7.08 million hourly rows, the size of step 2's real pack (81 coins, 78 perpetuals and
    7.0 million rows). Listings, delistings and the universes follow ``_timing_listings`` and
    ``_timing_universes``; the prices are exact, seeded random walks, the same on every machine.
    The result is cheap; writing it (``write_world``) is not."""
    months, listings = _timing_listings(coins, first, window_first, last)
    universes = _timing_universes(months, window_first, listings)
    return World(last, _TimingCoins(listings), universes)


def timing_rows(
    coins: int = 80,
    first: str = "2017-08",
    window_first: str = "2018-04",
    last: str = "2026-09",
) -> int:
    """The hourly rows ``write_world`` writes for ``timing_world`` with the same arguments, counted
    from the plan: no price is built."""
    return sum(item.rows() for item in _timing_listings(coins, first, window_first, last)[1])
