"""V4 engine task 2: the market view of the step-2 packs.

``SeriesStore`` keeps a series' unmasked hourly bars in five ``array("q")``; ``Market`` loads a
data directory (``data.json``, the daily pack, the hourly index and the coin packs, each by its
pin) and answers the engine's questions: bars, daily bars, the universe, perpetual eligibility
and funding. Every pack here is synthetic, written by ``tests/v4_synthetic.py`` under pytest's
``tmp_path``; the network is blocked for every test in this file (the autouse fixture below).
"""

from __future__ import annotations

import gzip
import socket
import sys
from array import array
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from v4_synthetic import (
    DAILY_PACK,
    DAY,
    HOUR,
    HOURLY_INDEX,
    CoinSpec,
    PerpetualSpec,
    Series,
    World,
    day_hours,
    every_month,
    hours_in,
    month_start,
    path,
    read_data_json,
    repack,
    write_data_json,
    write_world,
)

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.bars import FundingRow
from crypto_grid_bot.v4.data.pack import COIN_FORMAT, INDEX_FORMAT, coin_pack_file
from crypto_grid_bot.v4.data.universe import MonthlyUniverse
from crypto_grid_bot.v4.engine.market import (
    Coin,
    DataPins,
    HourBar,
    Market,
    Perpetual,
    SeriesStore,
)

D = Decimal
T0 = month_start("2025-01")  # 2025-01-01 00:00 UTC
ZERO = D(0)


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket."""

    def refuse(*args, **kwargs):
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)


# ---- builders -----------------------------------------------------------------------------


def row(open_ms: int, o: str, h: str, low: str, c: str) -> list[str | int]:
    """A coin pack row: [open_ms, open, high, low, close, volume, quote_volume]."""
    return [open_ms, o, h, low, c, "1.0", "100.0"]


def flat_row(open_ms: int, price: str = "100") -> list[str | int]:
    return row(open_ms, price, price, price, price)


def three_coins(end_month: str = "2025-02") -> World:
    """BTCUSDT with its plain perpetual, SHIBUSDT with 1000SHIBUSDT, ETHUSDT spot only, from
    2025-01-01 to the end of ``end_month``, all three selected every month."""
    hours = hours_in("2025-01", end_month)
    btc = CoinSpec(
        "BTCUSDT",
        Series(T0, path("50000", (hours, "0.0001"), noise="0.002", seed=1), wick="0.001"),
        perpetual=PerpetualSpec(),
    )
    shib = CoinSpec(
        "SHIBUSDT",
        Series(T0, path("0.00001234", (hours, "-0.0001"), noise="0.003", seed=2, places=12)),
        perpetual=PerpetualSpec(multiplier=1000, funding_rate="-0.00005"),
    )
    eth = CoinSpec("ETHUSDT", Series(T0, path("3000", (hours, "0"), noise="0.002", seed=3)))
    selected = ("BTCUSDT", "ETHUSDT", "SHIBUSDT")
    return World(end_month, (btc, shib, eth), every_month("2025-01", end_month, selected))


def same_prices(bar: HourBar | None, expected: Any) -> bool:
    return bar is not None and (bar.open_ms, bar.open, bar.high, bar.low, bar.close) == (
        expected.open_ms,
        expected.open,
        expected.high,
        expected.low,
        expected.close,
    )


def tamper(path_: Path) -> None:
    """Change one digit inside a pack's JSON and gzip it again: the pin no longer matches."""
    with gzip.open(path_, "rb") as stream:
        text = stream.read().decode("ascii")
    position = next(i for i, char in enumerate(text) if char in "123456789")
    changed = text[:position] + ("2" if text[position] == "1" else "1") + text[position + 1 :]
    path_.write_bytes(gzip.compress(changed.encode("ascii"), mtime=0))


# ---- SeriesStore ----------------------------------------------------------------------------


def test_store_keeps_only_unmasked_rows_and_treats_a_gap_as_masked():
    rows = [
        row(T0, "100", "101", "99", "100.5"),
        row(T0 + HOUR, "100.5", "150", "50", "100.6"),  # masked: kept in the rows
        row(T0 + 2 * HOUR, "100.6", "100.9", "100.1", "100.7"),
        # T0 + 3 h has no row: a gap, masked by the contract
        row(T0 + 4 * HOUR, "100.7", "100.8", "100.2", "100.3"),
    ]
    store = SeriesStore.from_rows(rows, masked=[T0 + HOUR, T0 + 9 * HOUR])

    assert list(store.opens()) == [T0, T0 + 2 * HOUR, T0 + 4 * HOUR]
    assert len(store) == 3
    assert store.bar(T0) == HourBar(T0, D("100"), D("101"), D("99"), D("100.5"))
    assert store.bar(T0 + HOUR) is None  # a masked row
    assert store.bar(T0 + 3 * HOUR) is None  # a gap
    assert store.bar(T0 + 9 * HOUR) is None  # masked, with no row (an unreadable month)
    assert store.bar(T0 - HOUR) is None and store.bar(T0 + 5 * HOUR) is None
    assert [bar.open_ms for bar in store.bars()] == list(store.opens())


def test_store_lookups_see_only_the_kept_bars():
    rows = [
        row(T0, "10", "11", "10", "11"),
        row(T0 + HOUR, "11", "12", "11", "12"),  # masked
        row(T0 + 2 * HOUR, "12", "13", "12", "13"),
        row(T0 + 5 * HOUR, "13", "14", "13", "14"),
    ]
    store = SeriesStore.from_rows(rows, masked=[T0 + HOUR])

    assert store.first_open_ms == T0
    assert store.last_open_at_or_before(T0 - 1) is None
    assert store.last_open_at_or_before(T0) == T0
    assert store.last_open_at_or_before(T0 + 2 * HOUR - 1) == T0  # the masked hour is no bar
    assert store.last_open_at_or_before(T0 + 4 * HOUR) == T0 + 2 * HOUR
    assert store.last_open_at_or_before(T0 + 99 * HOUR) == T0 + 5 * HOUR
    # A close is known once its bar has closed: the bar opening at t closes before t + 1 h.
    assert store.last_close_before(T0) is None
    assert store.last_close_before(T0 + HOUR - 1) is None
    assert store.last_close_before(T0 + HOUR) == D("11")
    assert store.last_close_before(T0 + 3 * HOUR - 1) == D("11")  # skips the masked close 12
    assert store.last_close_before(T0 + 3 * HOUR) == D("13")
    assert store.last_close_before(T0 + 99 * HOUR) == D("14")

    nothing = SeriesStore.from_rows([flat_row(T0)], masked=[T0])
    empty = SeriesStore.from_rows([], masked=[])
    for store in (nothing, empty):
        assert len(store) == 0 and list(store.opens()) == [] and list(store.bars()) == []
        assert store.first_open_ms is None
        assert store.bar(T0) is None
        assert store.last_open_at_or_before(T0 + DAY) is None
        assert store.last_close_before(T0 + DAY) is None


def test_store_round_trips_every_price_exactly():
    prices = [
        ("0.09865000", "0.09870000", "0.09860000", "0.09866000"),  # the CSV's own text
        ("100.00000000", "100.00000000", "100.00000000", "100.00000000"),
        ("43210.5", "43219.99", "43200.01", "43210.50"),
        ("1.2E-7", "1.3E-7", "1.1E-7", "1.25E-7"),  # str() of a small Decimal
        ("1E+3", "1000.1", "999.99999999", "1000"),
    ]
    rows = [row(T0 + k * HOUR, *values) for k, values in enumerate(prices)]
    store = SeriesStore.from_rows(rows, masked=[])

    for k, values in enumerate(prices):
        bar = store.bar(T0 + k * HOUR)
        assert bar is not None
        assert (bar.open, bar.high, bar.low, bar.close) == tuple(D(text) for text in values)
        # every price comes back with the series' scale: the most decimals of any price after
        # normalize(), here 9 (1.25E-7), whatever trailing zeros the text had
        for price in (bar.open, bar.high, bar.low, bar.close):
            assert price.as_tuple().exponent == -9
    assert store.last_close_before(T0 + HOUR) == D("0.09866")


def test_trailing_zeros_do_not_widen_a_series_scale():
    store = SeriesStore.from_rows([flat_row(T0, "100.00000000")], masked=[])
    bar = store.bar(T0)

    assert bar is not None and str(bar.close) == "100"


def test_store_is_compact():
    count = 100_000

    def prices(k: int) -> tuple[str, str, str, str]:
        level = 100 + k % 997
        return f"{level}.25", f"{level + 1}.5", f"{level - 1}", f"{level}.75"

    store = SeriesStore.from_rows([row(T0 + k * HOUR, *prices(k)) for k in range(count)], [])
    held = [getattr(store, name) for name in SeriesStore.__slots__]

    assert len(store) == count
    assert not hasattr(store, "__dict__")
    assert all(isinstance(value, array | int) for value in held)  # no list of Decimals behind it
    assert sum(sys.getsizeof(value) for value in held) / count < 64
    k = 54_321
    assert store.bar(T0 + k * HOUR) == HourBar(T0 + k * HOUR, *(D(text) for text in prices(k)))


@pytest.mark.parametrize(
    ("rows", "masked", "message"),
    [
        ([["0", "1", "1", "1", "1"]], [], "open"),
        ([[True, "1", "1", "1", "1"]], [], "open"),
        ([[float(T0), "1", "1", "1", "1"]], [], "open"),
        ([flat_row(T0 + 1)], [], "hour"),
        ([flat_row(-HOUR)], [], "open"),
        ([flat_row(T0), flat_row(T0)], [], "increasing"),
        ([flat_row(T0 + HOUR), flat_row(T0)], [T0], "increasing"),  # masked rows count too
        ([[T0, "1", "1", "1"]], [], "columns"),
        ([[T0, 1.5, "2", "1", "1.5"]], [], "decimal string"),
        ([[T0, 1, "1", "1", "1"]], [], "decimal string"),
        ([flat_row(T0, "abc")], [], "decimal string"),
        ([flat_row(T0, "NaN")], [], "positive"),
        ([flat_row(T0, "Infinity")], [], "positive"),
        ([flat_row(T0, "0")], [], "positive"),
        ([flat_row(T0, "-1")], [], "positive"),
        ([row(T0, "100", "101", "100.5", "100.2")], [], "low"),  # low above the close
        ([row(T0, "100", "100.1", "99", "100.2")], [], "high"),  # high below the close
        ([flat_row(T0, "10000000000000"), flat_row(T0 + HOUR, "1E-8")], [], "64-bit"),
        ([flat_row(T0)], ["0"], "masked"),
        ([flat_row(T0)], [True], "masked"),
    ],
)
def test_store_refuses_rows_the_pack_contract_forbids(rows, masked, message):
    with pytest.raises(ValueError, match=message):
        SeriesStore.from_rows(rows, masked)


def test_bars_coins_and_perpetuals_are_frozen():
    bar = HourBar(T0, D(1), D(1), D(1), D(1))
    with pytest.raises(FrozenInstanceError):
        bar.close = D(2)  # type: ignore[misc]
    store = SeriesStore.from_rows([], [])
    rules = VenueRules(D("0.001"), D("0.001"), D("1000"), D("5"), D("0.01"))
    perpetual = Perpetual("1000SHIBUSDT", 1000, store, (), {}, rules)
    coin = Coin("SHIBUSDT", store, rules, perpetual)
    with pytest.raises(FrozenInstanceError):
        coin.perpetual = None  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        perpetual.multiplier = 1  # type: ignore[misc]
    with pytest.raises(ValueError, match="symbol"):
        Coin("shib", store, rules, None)
    with pytest.raises(ValueError, match="multiplier"):
        Perpetual("1000SHIBUSDT", 0, store, (), {}, rules)


# ---- Market.load ----------------------------------------------------------------------------


def test_market_loads_the_world_the_builder_wrote(tmp_path):
    world = three_coins()
    market = Market.load(write_world(tmp_path, world))

    assert market.symbols == ("BTCUSDT", "ETHUSDT", "SHIBUSDT")
    assert market.end_month == "2025-02"
    for spec in world.coins:
        coin = market.coin(spec.symbol)
        assert coin.symbol == spec.symbol and coin.spot_rules == spec.spot_rules
        expected = spec.spot.bars()
        assert len(coin.spot) == len(expected)
        assert all(same_prices(coin.spot.bar(bar.open_ms), bar) for bar in expected)
        if spec.perpetual is None:
            assert coin.perpetual is None
            continue
        perpetual = coin.perpetual
        assert perpetual is not None
        series = spec.perpetual.series_for(spec.spot)
        assert perpetual.symbol == spec.perpetual.name(spec.symbol)
        assert perpetual.multiplier == spec.perpetual.multiplier
        assert perpetual.rules == spec.perpetual.rules
        assert all(same_prices(perpetual.store.bar(bar.open_ms), bar) for bar in series.bars())
        rows = spec.perpetual.funding_rows(series)
        assert perpetual.funding == tuple((r.time_ms, r.rate) for r in rows)
        assert dict(perpetual.months) == {"2025-01": "complete", "2025-02": "complete"}
    shib = market.coin("SHIBUSDT").perpetual
    assert shib is not None and (shib.symbol, shib.multiplier) == ("1000SHIBUSDT", 1000)
    # the contract's prices are the coin's times the multiplier, in the pack as in the store
    spot_bar, contract_bar = market.coin("SHIBUSDT").spot.bar(T0 + DAY), shib.store.bar(T0 + DAY)
    assert spot_bar is not None and contract_bar is not None
    assert contract_bar.close == spot_bar.close * 1000
    with pytest.raises(ValueError, match="XRPUSDT"):
        market.coin("XRPUSDT")


def test_a_loaded_market_keeps_the_pins_of_data_json(tmp_path):
    """Task 14 ruling: a market loaded from a data directory names what it was read from:
    data.json's config_sha256 and end_month and the pins of the daily pack and the hourly index
    (which pins every coin pack), so a cell's outcome record can carry them. A market built in
    memory has none, and pins must be well formed and of the market's end month."""
    data_dir = write_world(tmp_path, three_coins())
    header = read_data_json(data_dir)

    market = Market.load(data_dir)

    assert market.pins == DataPins(
        header["config_sha256"],
        "2025-02",
        header["packs"]["daily"]["sha256"],
        header["packs"]["hourly_index"]["sha256"],
    )
    coins = [market.coin("BTCUSDT")]
    assert (
        Market(end_month="2025-02", universes={"2025-01": ("BTCUSDT",)}, coins=coins).pins is None
    )
    with pytest.raises(ValueError, match="end_month"):
        Market(
            end_month="2025-03", universes={"2025-01": ("BTCUSDT",)}, coins=coins, pins=market.pins
        )
    with pytest.raises(ValueError, match="DataPins"):
        Market(end_month="2025-02", universes={"2025-01": ("BTCUSDT",)}, coins=coins, pins={})
    pins = market.pins
    assert pins is not None
    with pytest.raises(FrozenInstanceError):
        pins.end_month = "2025-03"  # type: ignore[misc]
    for change, message in [
        ({"daily_sha256": "ABC"}, "daily_sha256"),
        ({"index_sha256": pins.daily_sha256.upper()}, "index_sha256"),
        ({"end_month": "2025-13"}, "end_month"),
        ({"config_sha256": ""}, "config_sha256"),
    ]:
        with pytest.raises(ValueError, match=message):
            replace(pins, **change)


def test_market_verifies_every_pin_and_refuses_a_tampered_coin_pack(tmp_path):
    world = three_coins()
    Market.load(write_world(tmp_path / "clean", world))  # loads as written

    for name, file in [
        ("daily", DAILY_PACK),
        ("index", HOURLY_INDEX),
        ("coin", coin_pack_file("ETHUSDT")),
    ]:
        data_dir = write_world(tmp_path / name, world)
        tamper(data_dir / file)
        with pytest.raises(ValueError, match="sha256"):
            Market.load(data_dir)

    # A coin pack swapped for another coin's: each is intact, neither has the other's pin.
    data_dir = write_world(tmp_path / "swapped", world)
    btc, eth = data_dir / coin_pack_file("BTCUSDT"), data_dir / coin_pack_file("ETHUSDT")
    btc_bytes = btc.read_bytes()
    btc.write_bytes(eth.read_bytes())
    eth.write_bytes(btc_bytes)
    with pytest.raises(ValueError, match="sha256"):
        Market.load(data_dir)

    # A coin pack missing from the folder.
    data_dir = write_world(tmp_path / "missing", world)
    (data_dir / coin_pack_file("SHIBUSDT")).unlink()
    with pytest.raises(OSError):
        Market.load(data_dir)


def _set(key: str, value: object):
    def change(document: dict[str, Any]) -> None:
        document[key] = value

    return change


@pytest.mark.parametrize(
    ("file", "change", "message"),
    [
        (DAILY_PACK, _set("format", COIN_FORMAT), "format"),
        (HOURLY_INDEX, _set("format", "v4-hourly-index/2"), "format"),
        (coin_pack_file("BTCUSDT"), _set("format", INDEX_FORMAT), "format"),
        (coin_pack_file("BTCUSDT"), _set("config_sha256", "f" * 64), "config_sha256"),
        (DAILY_PACK, _set("end_month", "2025-01"), "end_month"),
        (coin_pack_file("BTCUSDT"), _set("coin", "ETHUSDT"), "ETHUSDT"),
        (coin_pack_file("BTCUSDT"), _set("perpetual", None), "perpetual"),
        (HOURLY_INDEX, _set("perpetuals", {}), "perpetual"),
    ],
)
def test_market_refuses_a_validly_pinned_pack_that_is_not_the_one_expected(
    tmp_path, file, change, message
):
    data_dir = write_world(tmp_path, three_coins())
    repack(data_dir, file, change)

    with pytest.raises(ValueError, match=message):
        Market.load(data_dir)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_set("format", "v4-data/2"), "format"),
        (_set("config_sha256", "e" * 64), "config_sha256"),
    ],
)
def test_market_refuses_a_data_json_of_another_format_or_run(tmp_path, change, message):
    data_dir = write_world(tmp_path, three_coins())
    document = read_data_json(data_dir)
    change(document)
    write_data_json(data_dir, document)

    with pytest.raises(ValueError, match=message):
        Market.load(data_dir)


@pytest.mark.parametrize("file", ["../daily.pack.json.gz", "sub/daily.pack.json.gz", "C:x", ""])
def test_market_reads_packs_from_the_data_directory_only(tmp_path, file):
    data_dir = write_world(tmp_path, three_coins())
    document = read_data_json(data_dir)
    document["packs"]["daily"]["file"] = file
    write_data_json(data_dir, document)

    with pytest.raises(ValueError, match="plain name"):
        Market.load(data_dir)


# ---- daily bars, the window and the universe ----------------------------------------------


def test_daily_bars_follow_the_20_of_24_rule_and_skip_masked_hours(tmp_path):
    days = [T0 + k * DAY for k in range(4)]
    masked = day_hours(days[1], range(4)) + day_hours(days[2], range(3))
    missing = day_hours(days[2], (3, 4)) + day_hours(days[3], (23,))
    spikes = {open_ms: ("1000", "1") for open_ms in day_hours(days[1], range(4))}
    series = Series(
        T0,
        path("100", (96, "0.001"), noise="0.01", seed=5),
        masked=masked,
        missing=missing,
        extremes=spikes,
    )
    world = World("2025-01", (CoinSpec("BTCUSDT", series),), {"2025-01": ("BTCUSDT",)})
    market = Market.load(write_world(tmp_path, world))

    usable = [bar for bar in series.bars() if bar.open_ms not in set(masked)]
    expected = []
    for day in (days[0], days[1], days[3]):  # day 2 has 19 unmasked hours, so no bar
        hours = [bar for bar in usable if day <= bar.open_ms < day + DAY]
        assert len(hours) == {days[0]: 24, days[1]: 20, days[3]: 23}[day]
        expected.append(
            Kline(
                day,
                hours[0].open,
                max(bar.high for bar in hours),
                min(bar.low for bar in hours),
                hours[-1].close,
                ZERO,
                ZERO,
                ZERO,
            )
        )
    daily = market.daily("BTCUSDT")

    assert daily == tuple(expected)
    assert daily[1].high < 1000 and daily[1].low > 1  # the masked hours' spikes are not in it
    assert daily[1].open == series.bars()[28].open  # the day opens at its first unmasked hour
    assert market.daily("BTCUSDT") is daily  # computed once


def test_window_runs_from_the_first_universe_month_to_end_month(tmp_path):
    hours = hours_in("2025-01", "2025-04")
    coins = (
        CoinSpec("BTCUSDT", Series(T0, path("100", (hours, "0")))),
        CoinSpec("ETHUSDT", Series(T0, path("10", (hours, "0")))),
    )
    universes = {
        "2025-01": (),  # a month whose selection is empty does not open the window
        "2025-02": ("BTCUSDT",),
        "2025-03": ("ETHUSDT", "BTCUSDT"),
    }
    market = Market.load(write_world(tmp_path, World("2025-04", coins, universes)))

    assert market.window_start_ms == month_start("2025-02")
    assert market.window_end_ms == month_start("2025-05") - HOUR  # the last hour of 2025-04
    assert market.universe("2025-02") == ("BTCUSDT",)
    assert market.universe("2025-03") == ("ETHUSDT", "BTCUSDT")  # in rank order
    assert market.universe("2025-01") == ()
    assert market.universe("2025-04") == ()  # no universe entry
    assert market.universe("2024-12") == ()
    with pytest.raises(ValueError, match="YYYY-MM"):
        market.universe("2025-3")


def test_market_keeps_each_months_full_selection_record(tmp_path):
    """Spec "Universe": the selection is recorded every month, with the ranked list and its
    volumes and who entered and who left. ``Market.selection`` keeps each month's whole record
    from the daily pack: the candidates below the cut and the exclusions included."""
    data_dir = write_world(tmp_path, three_coins())

    def enrich(document: dict[str, Any]) -> None:
        january = document["universes"][0]
        january["ranked"].append(["XRPUSDT", "12.5", 29])  # ranked, not selected
        january["excluded"] = [["BTCUPUSDT", "leveraged"], ["USDCUSDT", "stablecoin"]]

    repack(data_dir, DAILY_PACK, enrich)
    market = Market.load(data_dir)

    january = market.selection("2025-01")
    assert january == MonthlyUniverse(
        month="2025-01",
        selected=("BTCUSDT", "ETHUSDT", "SHIBUSDT"),
        ranked=(
            ("BTCUSDT", D(3000), 30),
            ("ETHUSDT", D(2000), 30),
            ("SHIBUSDT", D(1000), 30),
            ("XRPUSDT", D("12.5"), 29),
        ),
        excluded=(("BTCUPUSDT", "leveraged"), ("USDCUSDT", "stablecoin")),
        entered=("BTCUSDT", "ETHUSDT", "SHIBUSDT"),
        left=(),
    )
    assert january.ranked[3][1] == D("12.5") and type(january.ranked[3][2]) is int
    february = market.selection("2025-02")
    assert february is not None and february.entered == () and february.left == ()
    assert market.universe("2025-01") == january.selected
    assert market.selection("2025-03") is None  # no universe entry, no selection record
    with pytest.raises(ValueError, match="YYYY-MM"):
        market.selection("2025-1")
    # A Market built from its parts without selection records has none.
    built = Market(
        end_month="2025-01", universes={"2025-01": ("BTCUSDT",)}, coins=[market.coin("BTCUSDT")]
    )
    assert built.selection("2025-01") is None


def test_a_selection_record_must_match_its_universe(tmp_path):
    market = Market.load(write_world(tmp_path, three_coins()))
    coins = [market.coin("BTCUSDT"), market.coin("ETHUSDT")]
    record = MonthlyUniverse(
        "2025-01", ("BTCUSDT",), (("BTCUSDT", D(1), 30),), (), ("BTCUSDT",), ()
    )

    accepted = Market(
        end_month="2025-01",
        universes={"2025-01": ("BTCUSDT",)},
        coins=coins,
        selections={"2025-01": record},
    )
    assert accepted.selection("2025-01") is record
    for selections, message in [
        ({"2025-01": replace(record, selected=("ETHUSDT",))}, "selected"),
        ({"2025-02": replace(record, month="2025-02")}, "no universe"),
        ({"2025-01": replace(record, month="2025-02")}, "month"),
        ({"2025-01": ("BTCUSDT",)}, "MonthlyUniverse"),
    ]:
        with pytest.raises(ValueError, match=message):
            Market(
                end_month="2025-02",
                universes={"2025-01": ("BTCUSDT",)},
                coins=coins,
                selections=selections,
            )


def _universe_field(key: str, value: object):
    def change(document: dict[str, Any]) -> None:
        if value is _DROP:
            del document["universes"][0][key]
        else:
            document["universes"][0][key] = value

    return change


_DROP = object()


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("ranked", [["BTCUSDT", "1"]], "ranked"),
        ("ranked", [["BTCUSDT", "x", 30]], "decimal"),
        ("ranked", [["BTCUSDT", "1", "30"]], "bars"),
        ("ranked", [["btc", "1", 30]], "symbol"),
        ("ranked", None, "ranked"),
        ("excluded", [["BTCUSDT"]], "excluded"),
        ("excluded", [["BTCUSDT", 7]], "excluded"),
        ("entered", "BTCUSDT", "entered"),
        ("left", _DROP, "left"),
    ],
)
def test_market_refuses_a_malformed_selection_record(tmp_path, key, value, message):
    data_dir = write_world(tmp_path, three_coins())
    repack(data_dir, DAILY_PACK, _universe_field(key, value))

    with pytest.raises(ValueError, match=message):
        Market.load(data_dir)


def test_a_world_with_no_selection_or_an_unpacked_symbol_is_refused(tmp_path):
    coins = (CoinSpec("BTCUSDT", Series(T0, path("100", (48, "0")))),)
    empty = World("2025-01", coins, {"2025-01": ()})
    unpacked = World("2025-01", coins, {"2025-01": ("BTCUSDT", "XRPUSDT")})

    with pytest.raises(ValueError, match="no universe month has a selection"):
        Market.load(write_world(tmp_path / "empty", empty))
    with pytest.raises(ValueError, match="XRPUSDT"):
        Market.load(write_world(tmp_path / "unpacked", unpacked))


# ---- perpetual eligibility and funding ----------------------------------------------------


def test_perpetual_eligibility_is_point_in_time(tmp_path):
    hours = hours_in("2025-01", "2025-04")
    listed = T0 + 9 * DAY  # the perpetual's first bar: 2025-01-10 00:00
    gap = month_start("2025-02") + 9 * DAY  # no bar from 2025-02-10 00:00 for 169 hours
    perpetual = Series(
        listed,
        path("100", (hours - 9 * 24, "0")),
        missing=tuple(range(gap, gap + 100 * HOUR, HOUR)),
        masked=tuple(range(gap + 100 * HOUR, gap + 169 * HOUR, HOUR)),  # masked: no bar either
    )
    btc = CoinSpec(
        "BTCUSDT",
        Series(T0, path("100", (hours, "0"))),
        perpetual=PerpetualSpec(series=perpetual, months={"2025-03": "missing_slot"}),
    )
    eth = CoinSpec("ETHUSDT", Series(T0, path("10", (hours, "0"))))
    universes = every_month("2025-01", "2025-04", ("BTCUSDT", "ETHUSDT"))
    market = Market.load(write_world(tmp_path, World("2025-04", (btc, eth), universes)))
    eligible = market.perpetual_eligible

    # before the first bar, and at it: no bar yet in the 168 hours before the decision
    assert not eligible("BTCUSDT", listed - DAY)
    assert not eligible("BTCUSDT", listed)
    assert eligible("BTCUSDT", listed + HOUR)
    # the last bar before the gap opens at gap - 1 h
    assert eligible("BTCUSDT", gap + 167 * HOUR)  # that bar is 168 hours before
    assert not eligible("BTCUSDT", gap + 168 * HOUR)  # 169 hours: a dead market
    assert eligible("BTCUSDT", gap + 170 * HOUR)  # the bar at gap + 169 h is back
    # an incomplete funding month: no eligible perpetual for the whole month
    assert eligible("BTCUSDT", month_start("2025-03") - DAY)
    assert not eligible("BTCUSDT", month_start("2025-03"))
    assert not eligible("BTCUSDT", month_start("2025-04") - HOUR)
    assert eligible("BTCUSDT", month_start("2025-04"))
    # no perpetual: spot-only
    assert not eligible("ETHUSDT", month_start("2025-02"))

    assert market.funding_month("BTCUSDT", "2025-03") == "missing_slot"
    assert market.funding_month("BTCUSDT", "2025-02") == "complete"
    assert market.funding_month("BTCUSDT", "2024-12") is None
    assert market.funding_month("ETHUSDT", "2025-02") is None


def test_funding_events_fall_in_their_hour_in_time_order(tmp_path):
    hours = 48
    eight, sixteen = T0 + 8 * HOUR, T0 + 16 * HOUR
    btc_funding = [  # out of time order, as a pack may hold them
        FundingRow(sixteen + 3_599_999, D("0.0003"), 8),  # still the 16:00 hour
        FundingRow(eight + 5, D("0.0001"), 8),
        FundingRow(sixteen, D("0.0002"), 8),
        FundingRow(sixteen + HOUR, D("0.0004"), 8),  # the next hour's
    ]
    shib_funding = [FundingRow(sixteen + 1000, D("-0.0005"), 8)]
    btc = CoinSpec(
        "BTCUSDT",
        Series(T0, path("100", (hours, "0"))),
        perpetual=PerpetualSpec(funding=btc_funding),
    )
    shib = CoinSpec(
        "SHIBUSDT",
        Series(T0, path("0.00001", (hours, "0"), places=10)),
        perpetual=PerpetualSpec(multiplier=1000, funding=shib_funding),
    )
    world = World("2025-01", (btc, shib), {"2025-01": ("BTCUSDT", "SHIBUSDT")})
    market = Market.load(write_world(tmp_path, world))

    assert market.funding_events(sixteen) == (
        ("BTCUSDT", sixteen, D("0.0002")),
        ("1000SHIBUSDT", sixteen + 1000, D("-0.0005")),
        ("BTCUSDT", sixteen + 3_599_999, D("0.0003")),
    )
    assert market.funding_events(sixteen + HOUR) == (("BTCUSDT", sixteen + HOUR, D("0.0004")),)
    assert market.funding_events(eight) == (("BTCUSDT", eight + 5, D("0.0001")),)
    assert market.funding_events(T0) == ()
    with pytest.raises(ValueError, match="hour"):
        market.funding_events(sixteen + 1)


# ---- the synthetic builder, and the 2024 guard ---------------------------------------------


def test_synthetic_paths_follow_their_legs_and_are_seeded():
    assert path("100", (2, "0.01"), (1, "-0.5")) == (D("101"), D("102.01"), D("51.005"))
    noisy = path("100", (200, "0"), noise="0.01", seed=7)
    assert noisy == path("100", (200, "0"), noise="0.01", seed=7)
    assert noisy != path("100", (200, "0"), noise="0.01", seed=8)
    assert len(set(noisy)) > 50
    with pytest.raises(ValueError, match="reaches"):
        path("1", (1, "-1"))


def test_reading_far_beyond_2024_never_calls_the_2024_guard(monkeypatch, tmp_path):
    calls: list[str] = []

    def spy(month: str) -> str:
        calls.append(month)
        return month

    monkeypatch.setattr("crypto_grid_bot.backtest.klines.development_month", spy)
    monkeypatch.setattr("crypto_grid_bot.backtest.window.development_month", spy)
    for name, module in list(sys.modules.items()):  # every other module that imported it
        if name.startswith("crypto_grid_bot.") and hasattr(module, "development_month"):
            monkeypatch.setattr(module, "development_month", spy)
    start = month_start("2031-08")
    hours = hours_in("2031-08", "2031-09")
    btc = CoinSpec(
        "BTCUSDT",
        Series(start, path("100", (hours, "0.0002"), noise="0.002")),
        perpetual=PerpetualSpec(),
    )
    world = World("2031-09", (btc,), every_month("2031-08", "2031-09", ("BTCUSDT",)))
    market = Market.load(write_world(tmp_path, world))

    assert market.window_start_ms == start
    assert market.universe("2031-09") == ("BTCUSDT",)
    assert len(market.daily("BTCUSDT")) == hours // 24
    assert market.coin("BTCUSDT").spot.bar(start + DAY) is not None
    assert market.perpetual_eligible("BTCUSDT", start + 10 * DAY)
    assert market.funding_events(start + 8 * HOUR) == (("BTCUSDT", start + 8 * HOUR, D("0.0001")),)
    assert market.funding_month("BTCUSDT", "2031-09") == "complete"
    assert calls == []  # no name of the 2024 guard was ever called
