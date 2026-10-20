"""V4 data step: each (symbol, venue) gets its order rules, present-day or inferred (ruling R2).

Snapshots are small documents shaped like the committed ``exchangeInfo`` ones (the entries copy
BTCUSDT's filters on spot and on USDT-M futures); bars are built in memory. ``rules_for`` is
pure, so there is no file and no network: the network is blocked for every test in this file
(the autouse fixture below), as in ``test_v4_data_bars.py``.
"""

from __future__ import annotations

import socket
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal as D
from decimal import localcontext
from typing import Any

import pytest

from crypto_grid_bot.combined.driver.venues import venue_rules
from crypto_grid_bot.combined.execution import VenueRules
from crypto_grid_bot.v4.data.bars import HourBar
from crypto_grid_bot.v4.data.filters import rules_for

HOUR = 3_600_000


class NetworkBlocked(OSError):
    """What every attempt to open a connection raises while a test runs."""


@pytest.fixture(autouse=True)
def network_blocked(monkeypatch):
    """No test in this file may resolve a name or open a socket; each attempt is counted."""
    attempts: list[str] = []

    def refuse(*args, **kwargs):
        attempts.append("socket")
        raise NetworkBlocked("the network is blocked in tests")

    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    return attempts


def spot_entry(symbol: str, *, status: str = "TRADING", **overrides: str) -> dict[str, Any]:
    """A spot ``exchangeInfo`` entry; the defaults are BTCUSDT's filters in the snapshot."""
    values = {
        "tick": "0.01000000",
        "step": "0.00001000",
        "max_qty": "9000.00000000",
        "market_max_qty": "135.13628083",
        "min_notional": "5.00000000",
    } | overrides
    return {
        "symbol": symbol,
        "status": status,
        "baseAsset": symbol.removesuffix("USDT"),
        "quoteAsset": "USDT",
        "filters": [
            {
                "filterType": "PRICE_FILTER",
                "minPrice": values["tick"],
                "maxPrice": "1000000.00000000",
                "tickSize": values["tick"],
            },
            {
                "filterType": "LOT_SIZE",
                "minQty": values["step"],
                "maxQty": values["max_qty"],
                "stepSize": values["step"],
            },
            {
                "filterType": "MARKET_LOT_SIZE",
                "minQty": "0.00000000",
                "maxQty": values["market_max_qty"],
                "stepSize": "0.00000000",
            },
            {
                "filterType": "NOTIONAL",
                "minNotional": values["min_notional"],
                "applyMinToMarket": True,
                "maxNotional": "9000000.00000000",
                "applyMaxToMarket": False,
                "avgPriceMins": 5,
            },
        ],
    }


def futures_entry(symbol: str, *, status: str = "TRADING", **overrides: str) -> dict[str, Any]:
    """A USDT-M futures entry; the defaults are BTCUSDT's perpetual filters in the snapshot."""
    values = {
        "tick": "0.10",
        "step": "0.001",
        "max_qty": "1000",
        "market_max_qty": "120",
    } | overrides
    return {
        "symbol": symbol,
        "pair": symbol,
        "contractType": "PERPETUAL",
        "status": status,
        "baseAsset": symbol.removesuffix("USDT"),
        "quoteAsset": "USDT",
        "filters": [
            {
                "maxPrice": "4529764",
                "tickSize": values["tick"],
                "filterType": "PRICE_FILTER",
                "minPrice": "556.80",
            },
            {
                "stepSize": values["step"],
                "minQty": values["step"],
                "maxQty": values["max_qty"],
                "filterType": "LOT_SIZE",
            },
            {
                "minQty": values["step"],
                "maxQty": values["market_max_qty"],
                "filterType": "MARKET_LOT_SIZE",
                "stepSize": values["step"],
            },
            {"notional": "50", "filterType": "MIN_NOTIONAL"},
        ],
    }


def snapshot(*entries: Mapping[str, Any]) -> dict[str, Any]:
    return {"timezone": "UTC", "symbols": list(entries)}


def make_bar(
    index: int = 0,
    *,
    open_: str = "1",
    high: str = "1",
    low: str = "1",
    close: str = "1",
    volume: str = "1",
    quote_volume: str = "1",
) -> HourBar:
    return HourBar(
        index * HOUR, D(open_), D(high), D(low), D(close), D(quote_volume), volume=D(volume)
    )


def delisted_bars() -> list[HourBar]:
    """Prices 0.09865 and 0.1, volume 1601.1: the ruling's own example, in CSV spelling."""
    return [
        make_bar(0, open_="0.1", high="0.1", low="0.09865", close="0.09865", volume="1601.1"),
        make_bar(1, open_="0.09865", high="0.1", low="0.09865", close="0.1", volume="1601.1"),
    ]


SPOT_BTC = snapshot(spot_entry("BTCUSDT"))
FUTURES_BTC = snapshot(futures_entry("BTCUSDT"))
EMPTY = snapshot()


def test_present_day_symbol_uses_the_snapshot():
    # Bars with other precisions are ignored: the snapshot decides, and may even be given none.
    bars = [make_bar(open_="0.123456789", volume="7.5")]
    spot_rules, spot_source = rules_for("BTCUSDT", "spot", SPOT_BTC, bars)
    future_rules, future_source = rules_for("BTCUSDT", "futures", FUTURES_BTC, ())
    assert spot_rules == VenueRules(
        step=D("0.00001000"),
        min_qty=D("0.00001000"),
        max_qty=D("135.13628083"),
        min_notional=D("5.00000000"),
        tick=D("0.01000000"),
    )
    assert future_rules == VenueRules(
        step=D("0.001"), min_qty=D("0.001"), max_qty=D("120"), min_notional=D("50"), tick=D("0.10")
    )
    assert (spot_source, future_source) == ("present_day", "present_day")
    assert spot_rules == venue_rules(SPOT_BTC, "BTCUSDT", "spot")
    assert future_rules == venue_rules(FUTURES_BTC, "BTCUSDT", "futures")


def test_absent_symbol_infers_tick_and_step_from_decimals_ruling_r2():
    rules, _ = rules_for("LUNAUSDT", "spot", EMPTY, delisted_bars())
    assert rules.tick == D("0.00001")
    assert rules.step == D("0.1")
    assert rules.min_qty == rules.step
    assert rules.max_qty == D("9000000000")
    assert rules.min_notional == D("5")


def test_inferred_rules_are_labelled_inferred():
    assert rules_for("LUNAUSDT", "spot", EMPTY, delisted_bars())[1] == "inferred"
    assert rules_for("LUNAUSDT", "futures", EMPTY, delisted_bars())[1] == "inferred"
    # Present elsewhere in the same snapshot is not enough: this symbol is what must be listed.
    assert rules_for("LUNAUSDT", "spot", SPOT_BTC, delisted_bars())[1] == "inferred"


def test_inferred_values_are_decimals_never_floats():
    rules, _ = rules_for("LUNAUSDT", "spot", EMPTY, delisted_bars())
    for value in (rules.step, rules.min_qty, rules.max_qty, rules.min_notional, rules.tick):
        assert type(value) is D
    # 1E-5 and 0.00001 are the same number, and the unit is exact, not a float's neighbour.
    assert rules.tick == D(1) / D(10**5)
    assert rules.tick.as_tuple() == D("0.00001").as_tuple()


def test_trailing_zeros_do_not_count_as_decimals():
    bars = [
        make_bar(
            open_="0.09865000",
            high="0.10000000",
            low="0.09865000",
            close="0.10000000",
            volume="1601.10000000",
        )
    ]
    rules, label = rules_for("LUNAUSDT", "spot", EMPTY, bars)
    assert rules.tick == D("0.00001")
    assert rules.step == D("0.1")
    assert label == "inferred"


def test_integer_only_values_give_a_unit_tick_and_step():
    # 100 and 5 have no decimals; 1E+2 is an integer written with an exponent, not a negative
    # number of decimals.
    for price, volume in (("100", "5"), ("1E+2", "5E+1"), ("100.00", "5.0"), ("0", "0")):
        rules, _ = rules_for("LUNAUSDT", "spot", EMPTY, [make_bar(open_=price, volume=volume)])
        assert (rules.tick, rules.step) == (D(1), D(1)), (price, volume)
        assert rules.min_qty == D(1)


@pytest.mark.parametrize("field", ["open_", "high", "low", "close"])
def test_tick_takes_the_most_decimals_of_any_price_field_of_any_bar(field):
    bars = [make_bar(0), make_bar(1), make_bar(2, **{field: "2.123456"}), make_bar(3)]
    rules, _ = rules_for("LUNAUSDT", "spot", EMPTY, bars)
    assert rules.tick == D("0.000001")
    assert rules.step == D(1)


def test_step_takes_the_most_decimals_of_any_bar_and_ignores_quote_volume():
    bars = [
        make_bar(0, volume="10", quote_volume="12345.6789"),
        make_bar(1, volume="0.03", quote_volume="1"),
        make_bar(2, volume="100", quote_volume="1"),
    ]
    rules, _ = rules_for("LUNAUSDT", "spot", EMPTY, bars)
    assert rules.step == D("0.01")
    assert rules.tick == D(1)


def test_decimals_do_not_depend_on_the_callers_decimal_context():
    # A 5-digit context would round 0.09865123 to 0.098651 inside normalize().
    bars = [make_bar(open_="0.09865123", volume="1601.123456")]
    expected, _ = rules_for("LUNAUSDT", "spot", EMPTY, bars)
    with localcontext() as context:
        context.prec = 5
        rules, _ = rules_for("LUNAUSDT", "spot", EMPTY, bars)
    assert rules == expected
    assert rules.tick == D("0.00000001")
    assert rules.step == D("0.000001")


def test_a_symbol_on_spot_only_is_inferred_on_futures_and_the_reverse():
    spot_only = snapshot(spot_entry("BTCUSDT"))
    futures_only = snapshot(futures_entry("BTCUSDT"))
    bars = [make_bar(open_="0.5", volume="3")]

    spot_rules, spot_label = rules_for("BTCUSDT", "spot", spot_only, bars)
    # Absent from the futures snapshot, so inferred: the bars' tick, not the spot snapshot's.
    future_rules, future_label = rules_for("BTCUSDT", "futures", EMPTY, bars)
    assert (spot_label, future_label) == ("present_day", "inferred")
    assert spot_rules.tick == D("0.01000000")
    assert (future_rules.tick, future_rules.step) == (D("0.1"), D(1))
    assert future_rules.min_notional == D("5")

    future_rules, future_label = rules_for("BTCUSDT", "futures", futures_only, bars)
    spot_rules, spot_label = rules_for("BTCUSDT", "spot", EMPTY, bars)
    assert (future_label, spot_label) == ("present_day", "inferred")
    assert future_rules.min_notional == D("50")  # the snapshot's own, not the fallback's 5
    assert spot_rules.min_notional == D("5")
    assert (spot_rules.tick, spot_rules.step) == (D("0.1"), D(1))


@pytest.mark.parametrize("venue", ["spot", "futures"])
def test_a_present_symbol_with_status_break_still_uses_the_snapshot(venue):
    make: Callable[..., dict[str, Any]] = spot_entry if venue == "spot" else futures_entry
    entry = make("EOSUSDT", status="BREAK", tick="0.00010000", step="0.1")
    # The bars say 6 decimals of price and 2 of volume; the snapshot says otherwise.
    bars = [make_bar(open_="0.123456", volume="1.25")]
    rules, label = rules_for("EOSUSDT", venue, snapshot(entry), bars)
    assert label == "present_day"
    assert rules.tick == D("0.0001")
    assert rules.step == D("0.1")
    assert rules == venue_rules(snapshot(entry), "EOSUSDT", venue)


@pytest.mark.parametrize(
    ("venue", "entry"),
    [
        ("spot", {**spot_entry("LUNAUSDT"), "quoteAsset": "BUSD"}),
        ("futures", {**futures_entry("LUNAUSDT"), "contractType": "CURRENT_QUARTER"}),
    ],
)
def test_a_present_symbol_the_snapshot_rejects_is_refused_not_inferred(venue, entry):
    with pytest.raises(ValueError, match="LUNAUSDT"):
        rules_for("LUNAUSDT", venue, snapshot(entry), delisted_bars())


def test_an_absent_symbol_without_bars_is_refused():
    for bars in ((), []):
        with pytest.raises(ValueError, match="LUNAUSDT.*no bars"):
            rules_for("LUNAUSDT", "spot", EMPTY, bars)
    # A present symbol needs no bars.
    assert rules_for("BTCUSDT", "spot", SPOT_BTC, ())[1] == "present_day"


@pytest.mark.parametrize("venue", ["margin", "", "Spot", "SPOT", "futures ", "usdt-m"])
def test_an_unknown_venue_is_refused_for_present_and_absent_symbols(venue):
    with pytest.raises(ValueError, match="venue"):
        rules_for("BTCUSDT", venue, SPOT_BTC, delisted_bars())
    with pytest.raises(ValueError, match="venue"):
        rules_for("LUNAUSDT", venue, EMPTY, delisted_bars())


@pytest.mark.parametrize("symbol", ["", "btcusdt", "BTC-USDT", "B", "BTC USDT"])
def test_an_invalid_symbol_is_refused_even_when_it_would_be_absent(symbol):
    with pytest.raises(ValueError, match="symbol"):
        rules_for(symbol, "spot", EMPTY, delisted_bars())


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"symbols": None},
        {"symbols": {"BTCUSDT": {}}},
        {"symbols": [spot_entry("BTCUSDT"), "ETHUSDT"]},
        {"symbols": [spot_entry("BTCUSDT"), {"baseAsset": "ETH"}]},
    ],
)
def test_a_malformed_snapshot_is_refused_whether_or_not_the_symbol_is_in_it(bad):
    with pytest.raises(ValueError, match="snapshot"):
        rules_for("LUNAUSDT", "spot", bad, delisted_bars())
    with pytest.raises(ValueError, match="snapshot"):
        rules_for("BTCUSDT", "spot", bad, delisted_bars())


def test_a_non_finite_bar_value_is_refused():
    for bars in (
        [make_bar(0), make_bar(1, close="NaN")],
        [make_bar(0), make_bar(1, volume="Infinity")],
    ):
        with pytest.raises(ValueError, match="finite"):
            rules_for("LUNAUSDT", "spot", EMPTY, bars)


def test_precision_beyond_what_venue_rules_accept_is_refused_with_the_symbol_named():
    # 101 decimals: VenueRules allows at most 100.
    bars = [make_bar(open_="0." + "0" * 100 + "1")]
    with pytest.raises(ValueError, match=r"LUNAUSDT \(spot\).*unusable"):
        rules_for("LUNAUSDT", "spot", EMPTY, bars)


def test_the_inputs_are_left_unchanged_and_the_answer_is_repeatable():
    bars: Sequence[HourBar] = tuple(delisted_bars())
    document = snapshot(spot_entry("BTCUSDT"))
    before = repr(document)
    first = rules_for("LUNAUSDT", "spot", document, bars)
    assert rules_for("LUNAUSDT", "spot", document, bars) == first
    assert repr(document) == before
    assert len(bars) == 2
