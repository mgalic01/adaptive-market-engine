"""Venue order rules read from saved Binance filters, and the two pinned cost profiles.

Fixtures are small documents shaped like ``exchangeInfo``; only the one real-snapshot test
opens the committed files (local disk, no network).
"""

import copy
import hashlib
import json
from decimal import Decimal as D
from pathlib import Path
from typing import Any

import pytest

from crypto_grid_bot.combined.decisions import Costs
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS, cost_profile, venue_rules
from crypto_grid_bot.combined.execution import VenueRules

SNAPSHOT_DIR = Path(__file__).resolve().parents[1] / "config/datasets/v3-20261009/snapshots"
COINS = (
    "BTCUSDT",
    "ETHUSDT",
    "BNBUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "DOGEUSDT",
    "LTCUSDT",
    "LINKUSDT",
    "TRXUSDT",
)


def spot_filters() -> list[dict[str, Any]]:
    """BTCUSDT's spot filters as the committed spot snapshot carries them."""
    return [
        {
            "filterType": "PRICE_FILTER",
            "minPrice": "0.01000000",
            "maxPrice": "1000000.00000000",
            "tickSize": "0.01000000",
        },
        {
            "filterType": "LOT_SIZE",
            "minQty": "0.00001000",
            "maxQty": "9000.00000000",
            "stepSize": "0.00001000",
        },
        {"filterType": "ICEBERG_PARTS", "limit": 100},
        {
            "filterType": "MARKET_LOT_SIZE",
            "minQty": "0.00000000",
            "maxQty": "135.13628083",
            "stepSize": "0.00000000",
        },
        {
            "filterType": "NOTIONAL",
            "minNotional": "5.00000000",
            "applyMinToMarket": True,
            "maxNotional": "9000000.00000000",
            "applyMaxToMarket": False,
            "avgPriceMins": 5,
        },
        {"filterType": "MAX_NUM_ORDERS", "maxNumOrders": 200},
    ]


def futures_filters() -> list[dict[str, Any]]:
    """BTCUSDT's futures filters as the committed futures snapshot carries them."""
    return [
        {
            "maxPrice": "4529764",
            "tickSize": "0.10",
            "filterType": "PRICE_FILTER",
            "minPrice": "556.80",
        },
        {"stepSize": "0.001", "minQty": "0.001", "maxQty": "1000", "filterType": "LOT_SIZE"},
        {"minQty": "0.001", "maxQty": "120", "filterType": "MARKET_LOT_SIZE", "stepSize": "0.001"},
        {"filterType": "MAX_NUM_ORDERS", "limit": 200},
        {"notional": "50", "filterType": "MIN_NOTIONAL"},
        {"multiplierDown": "0.9500", "multiplierUp": "1.0500", "filterType": "PERCENT_PRICE"},
    ]


def spot_entry(filters: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "status": "TRADING",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "filters": spot_filters() if filters is None else filters,
    }
    return {**entry, **overrides}


def futures_entry(filters: list[dict[str, Any]] | None = None, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "symbol": "BTCUSDT",
        "contractType": "PERPETUAL",
        "baseAsset": "BTC",
        "quoteAsset": "USDT",
        "filters": futures_filters() if filters is None else filters,
    }
    return {**entry, **overrides}


def snapshot(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"timezone": "UTC", "symbols": list(entries)}


def without(filters: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [item for item in filters if item["filterType"] != kind]


def changed(filters: list[dict[str, Any]], kind: str, **fields: Any) -> list[dict[str, Any]]:
    """The filters with one filter's fields replaced (a field set to None is removed)."""
    result = []
    for item in filters:
        if item["filterType"] == kind:
            item = {key: value for key, value in {**item, **fields}.items() if value is not None}
        result.append(item)
    return result


def spot_rules(filters: list[dict[str, Any]]) -> VenueRules:
    return venue_rules(snapshot(spot_entry(filters)), "BTCUSDT", "spot")


def futures_rules(filters: list[dict[str, Any]]) -> VenueRules:
    return venue_rules(snapshot(futures_entry(filters)), "BTCUSDT", "futures")


def test_rules_from_the_committed_snapshot_shape() -> None:
    spot = snapshot(spot_entry())
    futures = snapshot(futures_entry())
    before = copy.deepcopy((spot, futures))

    assert venue_rules(spot, "BTCUSDT", "spot") == VenueRules(
        step=D("0.00001"),
        min_qty=D("0.00001"),
        max_qty=D("135.13628083"),
        min_notional=D("5"),
        tick=D("0.01"),
    )
    assert venue_rules(futures, "BTCUSDT", "futures") == VenueRules(
        step=D("0.001"),
        min_qty=D("0.001"),
        max_qty=D("120"),
        min_notional=D("50"),
        tick=D("0.1"),
    )
    assert (spot, futures) == before
    assert venue_rules(spot, "BTCUSDT", "spot") == venue_rules(spot, "BTCUSDT", "spot")


def test_the_requested_symbol_is_the_one_read() -> None:
    other = spot_entry(changed(spot_filters(), "PRICE_FILTER", tickSize="0.0001"), symbol="ETHUSDT")
    document = snapshot(spot_entry(), other)

    assert venue_rules(document, "BTCUSDT", "spot").tick == D("0.01")
    assert venue_rules(document, "ETHUSDT", "spot").tick == D("0.0001")


@pytest.mark.parametrize("venue", ["spot", "futures"])
def test_missing_tick_size_is_refused(venue: str) -> None:
    make = spot_entry if venue == "spot" else futures_entry
    base = spot_filters() if venue == "spot" else futures_filters()

    for filters in (changed(base, "PRICE_FILTER", tickSize=None), without(base, "PRICE_FILTER")):
        with pytest.raises(ValueError, match=r"BTCUSDT.*PRICE_FILTER"):
            venue_rules(snapshot(make(filters)), "BTCUSDT", venue)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["0", "0.00000000", "abc", "-0.01", "NaN", 0.01, None])
def test_an_unusable_tick_size_is_refused(bad: object) -> None:
    filters = changed(spot_filters(), "PRICE_FILTER", tickSize=bad)

    with pytest.raises(ValueError, match=r"BTCUSDT.*PRICE_FILTER"):
        spot_rules(filters)


def test_a_symbol_missing_from_the_snapshot_is_refused() -> None:
    with pytest.raises(ValueError, match="DOGEUSDT"):
        venue_rules(snapshot(spot_entry()), "DOGEUSDT", "spot")


def test_a_duplicate_symbol_is_refused() -> None:
    with pytest.raises(ValueError, match="BTCUSDT.*duplicate"):
        venue_rules(snapshot(spot_entry(), spot_entry()), "BTCUSDT", "spot")


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"symbols": {}},
        {"symbols": ["BTCUSDT"]},
        {"symbols": [{"quoteAsset": "USDT"}]},
    ],
)
def test_a_snapshot_without_a_symbol_list_is_refused(document: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="BTCUSDT"):
        venue_rules(document, "BTCUSDT", "spot")


@pytest.mark.parametrize("quote", ["BUSD", "usdt", None])
def test_a_non_usdt_quote_asset_is_refused(quote: object) -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*USDT"):
        venue_rules(snapshot(spot_entry(quoteAsset=quote)), "BTCUSDT", "spot")
    with pytest.raises(ValueError, match=r"BTCUSDT.*USDT"):
        venue_rules(snapshot(futures_entry(quoteAsset=quote)), "BTCUSDT", "futures")


@pytest.mark.parametrize("contract", ["CURRENT_QUARTER", "NEXT_QUARTER", "", None])
def test_a_futures_contract_that_is_not_perpetual_is_refused(contract: object) -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*PERPETUAL"):
        venue_rules(snapshot(futures_entry(contractType=contract)), "BTCUSDT", "futures")


def test_a_spot_symbol_needs_no_contract_type() -> None:
    assert spot_rules(spot_filters()).tick == D("0.01")


def test_an_unknown_venue_is_refused() -> None:
    with pytest.raises(ValueError, match="venue"):
        venue_rules(snapshot(spot_entry()), "BTCUSDT", "margin")  # type: ignore[arg-type]


def test_a_malformed_symbol_is_refused() -> None:
    with pytest.raises(ValueError, match="btcusdt"):
        venue_rules(snapshot(spot_entry()), "btcusdt", "spot")


def test_a_missing_filter_list_is_refused() -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*filters"):
        venue_rules(snapshot({**spot_entry(), "filters": None}), "BTCUSDT", "spot")


@pytest.mark.parametrize("item", ["LOT_SIZE", {"stepSize": "1"}, {"filterType": 7}])
def test_a_malformed_filter_entry_is_refused(item: object) -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*filter"):
        spot_rules([*spot_filters(), item])  # type: ignore[list-item]


def test_a_duplicate_filter_type_is_refused() -> None:
    for kind in ("PRICE_FILTER", "LOT_SIZE", "MARKET_LOT_SIZE", "NOTIONAL"):
        filters = spot_filters()
        filters.append(next(item for item in filters if item["filterType"] == kind))

        with pytest.raises(ValueError, match=rf"BTCUSDT.*duplicate.*{kind}"):
            spot_rules(filters)


@pytest.mark.parametrize("field", ["stepSize", "minQty", "maxQty"])
def test_a_lot_size_field_that_is_missing_is_refused(field: str) -> None:
    with pytest.raises(ValueError, match=rf"BTCUSDT.*LOT_SIZE.*{field}"):
        spot_rules(changed(spot_filters(), "LOT_SIZE", **{field: None}))


def test_a_missing_lot_size_filter_is_refused() -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*LOT_SIZE"):
        spot_rules(without(spot_filters(), "LOT_SIZE"))


@pytest.mark.parametrize("bad", ["abc", "", 1, "-1", "Infinity"])
def test_an_unparsable_lot_size_value_is_refused(bad: object) -> None:
    for field in ("stepSize", "minQty", "maxQty"):
        with pytest.raises(ValueError, match=rf"BTCUSDT.*LOT_SIZE.*{field}"):
            spot_rules(changed(spot_filters(), "LOT_SIZE", **{field: bad}))


def test_the_larger_minimum_quantity_of_the_two_lot_filters_applies() -> None:
    filters = changed(spot_filters(), "MARKET_LOT_SIZE", minQty="0.00500000")
    assert spot_rules(filters).min_qty == D("0.005")

    filters = changed(spot_filters(), "LOT_SIZE", minQty="0.01000000")
    filters = changed(filters, "MARKET_LOT_SIZE", minQty="0.00500000")
    assert spot_rules(filters).min_qty == D("0.01")


def test_the_smaller_positive_maximum_quantity_of_the_two_lot_filters_applies() -> None:
    assert spot_rules(spot_filters()).max_qty == D("135.13628083")

    filters = changed(spot_filters(), "MARKET_LOT_SIZE", maxQty="20000.00000000")
    assert spot_rules(filters).max_qty == D("9000")


def test_a_zero_market_maximum_quantity_is_ignored() -> None:
    filters = changed(spot_filters(), "MARKET_LOT_SIZE", maxQty="0.00000000")

    assert spot_rules(filters).max_qty == D("9000")


def test_a_symbol_without_a_market_lot_filter_uses_the_lot_filter_alone() -> None:
    rules = spot_rules(without(spot_filters(), "MARKET_LOT_SIZE"))

    assert (rules.step, rules.min_qty, rules.max_qty) == (D("0.00001"), D("0.00001"), D("9000"))


def test_a_market_lot_filter_missing_a_field_is_refused() -> None:
    for field in ("stepSize", "minQty", "maxQty"):
        with pytest.raises(ValueError, match=rf"BTCUSDT.*MARKET_LOT_SIZE.*{field}"):
            spot_rules(changed(spot_filters(), "MARKET_LOT_SIZE", **{field: None}))


def test_an_unparsable_market_lot_value_is_refused() -> None:
    for field in ("stepSize", "minQty", "maxQty"):
        with pytest.raises(ValueError, match=rf"BTCUSDT.*MARKET_LOT_SIZE.*{field}"):
            spot_rules(changed(spot_filters(), "MARKET_LOT_SIZE", **{field: "n/a"}))


def test_a_market_step_equal_to_the_lot_step_is_accepted_however_it_is_written() -> None:
    filters = changed(futures_filters(), "MARKET_LOT_SIZE", stepSize="0.00100000")

    assert futures_rules(filters).step == D("0.001")


def test_a_market_step_that_differs_from_the_lot_step_is_refused() -> None:
    filters = changed(futures_filters(), "MARKET_LOT_SIZE", stepSize="0.01")

    with pytest.raises(ValueError, match=r"BTCUSDT.*MARKET_LOT_SIZE.*stepSize"):
        futures_rules(filters)


def test_a_minimum_quantity_the_venue_could_never_trade_is_refused() -> None:
    filters = changed(spot_filters(), "MARKET_LOT_SIZE", minQty="200.00000000")

    with pytest.raises(ValueError, match="BTCUSDT"):
        spot_rules(filters)


def test_the_largest_minimum_notional_among_the_filters_applies() -> None:
    both = [
        *without(futures_filters(), "MIN_NOTIONAL"),
        {"filterType": "MIN_NOTIONAL", "notional": "5"},
    ]
    both.append({"filterType": "NOTIONAL", "minNotional": "100.0"})
    assert futures_rules(both).min_notional == D("100")

    both = changed(both, "NOTIONAL", minNotional="2.0")
    assert futures_rules(both).min_notional == D("5")


def test_either_notional_key_is_read_from_either_filter() -> None:
    legacy = [
        *without(spot_filters(), "NOTIONAL"),
        {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
    ]

    assert spot_rules(legacy).min_notional == D("10")


def test_a_snapshot_without_any_minimum_notional_filter_is_refused() -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*(NOTIONAL|notional)"):
        spot_rules(without(spot_filters(), "NOTIONAL"))
    with pytest.raises(ValueError, match=r"BTCUSDT.*(NOTIONAL|notional)"):
        futures_rules(without(futures_filters(), "MIN_NOTIONAL"))


def test_an_ambiguous_minimum_notional_filter_is_refused() -> None:
    both_keys = changed(spot_filters(), "NOTIONAL", notional="7")
    no_key = changed(spot_filters(), "NOTIONAL", minNotional=None)

    for filters in (both_keys, no_key):
        with pytest.raises(ValueError, match=r"BTCUSDT.*NOTIONAL"):
            spot_rules(filters)


@pytest.mark.parametrize("bad", ["abc", 5, "-1", ""])
def test_an_unparsable_minimum_notional_is_refused(bad: object) -> None:
    with pytest.raises(ValueError, match=r"BTCUSDT.*NOTIONAL"):
        spot_rules(changed(spot_filters(), "NOTIONAL", minNotional=bad))


def test_doubled_profile_doubles_every_rate() -> None:
    for venue in ("spot", "futures"):
        base, doubled = cost_profile(1, venue), cost_profile(2, venue)  # type: ignore[arg-type]

        assert doubled.fee_rate == 2 * base.fee_rate
        assert doubled.slippage_rate == 2 * base.slippage_rate
        assert doubled.round_trip_cost_rate == 2 * base.round_trip_cost_rate


def test_the_base_profiles_carry_the_registered_rates() -> None:
    assert cost_profile(1, "spot") == Costs(D("0.001"), D("0.0005"), D("0.004"))
    assert cost_profile(1, "futures") == Costs(D("0.0005"), D("0.0005"), D("0.0025"))
    assert cost_profile(2, "spot") == Costs(D("0.002"), D("0.001"), D("0.008"))
    assert cost_profile(2, "futures") == Costs(D("0.001"), D("0.001"), D("0.005"))


@pytest.mark.parametrize("multiple", [0, 3, -1, 10, True, 1.0, 2.0, "1", None])
def test_unknown_multiple_is_refused(multiple: object) -> None:
    with pytest.raises(ValueError, match="multiple"):
        cost_profile(multiple, "spot")  # type: ignore[arg-type]


def test_an_unknown_cost_venue_is_refused() -> None:
    with pytest.raises(ValueError, match="venue"):
        cost_profile(1, "margin")  # type: ignore[arg-type]


def test_profile_pins_are_stable() -> None:
    assert COST_PROFILE_PINS == {
        1: "080ebaee2ff778dd082d3a15e868da3c2e55d6dbb20e7f718706e2e394e41c76",
        2: "b99eb4ad4f3458f8d501be30fe53aab695906117478884bdcdff2e42a5c3af1e",
    }


def test_profile_pins_hash_the_documented_canonical_json() -> None:
    canonical = {
        1: (
            '{"futures":{"fee_rate":"0.0005","round_trip_cost_rate":"0.0025",'
            '"slippage_rate":"0.0005"},"multiple":1,'
            '"spot":{"fee_rate":"0.001","round_trip_cost_rate":"0.004",'
            '"slippage_rate":"0.0005"}}'
        ),
        2: (
            '{"futures":{"fee_rate":"0.001","round_trip_cost_rate":"0.005",'
            '"slippage_rate":"0.001"},"multiple":2,'
            '"spot":{"fee_rate":"0.002","round_trip_cost_rate":"0.008",'
            '"slippage_rate":"0.001"}}'
        ),
    }

    for multiple, text in canonical.items():
        assert json.loads(text)["multiple"] == multiple
        assert COST_PROFILE_PINS[multiple] == hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.skipif(
    not (SNAPSHOT_DIR / "spot.json").is_file() or not (SNAPSHOT_DIR / "futures.json").is_file(),
    reason="the committed filter snapshots are not in this checkout",
)
def test_rules_build_for_every_coin_from_the_committed_snapshots() -> None:
    documents = {
        venue: json.loads((SNAPSHOT_DIR / f"{venue}.json").read_text(encoding="utf-8"))
        for venue in ("spot", "futures")
    }

    for venue, document in documents.items():
        for coin in COINS:
            rules = venue_rules(document, coin, venue)  # type: ignore[arg-type]
            assert rules.step > 0
            assert rules.tick > 0
            assert rules.min_notional > 0

    spot = venue_rules(documents["spot"], "BTCUSDT", "spot")
    assert (spot.step, spot.tick, spot.min_notional) == (D("0.00001"), D("0.01"), D("5"))
    futures = venue_rules(documents["futures"], "BTCUSDT", "futures")
    assert (futures.step, futures.min_notional) == (D("0.001"), D("50"))
