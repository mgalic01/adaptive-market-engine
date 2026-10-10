"""Offline exchange-filter parsing uses synthetic snapshots, never API requests."""

import json
from decimal import Decimal

import pytest

from crypto_grid_bot.trend.filters import parse_filter_snapshot


def snapshot(step="0.001"):
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "quoteAsset": "USDT",
                "contractType": "PERPETUAL",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.001",
                        "maxQty": "1000",
                        "stepSize": "0.001",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "minQty": "0.002",
                        "maxQty": "100",
                        "stepSize": step,
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }


@pytest.mark.parametrize("step,effective", [("0.01", "0.01"), ("0", "0.001")])
def test_market_limits_and_step_fallback(step, effective):
    parsed = parse_filter_snapshot(json.dumps(snapshot(step)).encode(), ("BTCUSDT",), futures=True)
    item = parsed["BTCUSDT"]
    assert item.step_size == Decimal(effective)
    assert item.min_quantity == Decimal("0.002")
    assert item.max_quantity == Decimal(100)
    assert item.min_notional == Decimal(5)
    assert item.lot_step_size == Decimal("0.001")


@pytest.mark.parametrize(
    "case",
    [
        "missing-symbol",
        "missing-filter",
        "duplicate-symbol",
        "duplicate-filter",
        "nan",
        "inverted",
        "zero-lot-step",
        "wrong-contract",
        "wrong-quote",
    ],
)
def test_bad_snapshots_rejected(case):
    doc = snapshot()
    item = doc["symbols"][0]
    if case == "missing-symbol":
        doc["symbols"] = []
    elif case == "missing-filter":
        item["filters"].pop()
    elif case == "duplicate-symbol":
        doc["symbols"].append(item)
    elif case == "duplicate-filter":
        item["filters"].append(item["filters"][0])
    elif case == "nan":
        item["filters"][1]["minQty"] = "NaN"
    elif case == "inverted":
        item["filters"][1]["minQty"] = "200"
    elif case == "zero-lot-step":
        item["filters"][0]["stepSize"] = "0"
    elif case == "wrong-contract":
        item["contractType"] = "CURRENT_QUARTER"
    else:
        item["quoteAsset"] = "USDC"
    with pytest.raises(ValueError):
        parse_filter_snapshot(json.dumps(doc).encode(), ("BTCUSDT",), futures=True)


def test_spot_min_notional_field():
    doc = snapshot()
    doc["symbols"][0]["filters"][-1] = {"filterType": "NOTIONAL", "minNotional": "10"}
    parsed = parse_filter_snapshot(json.dumps(doc).encode(), ("BTCUSDT",), futures=False)
    assert parsed["BTCUSDT"].min_notional == Decimal(10)


def test_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        parse_filter_snapshot(b'{"symbols": [], "symbols": []}', ("BTCUSDT",), futures=True)


@pytest.mark.parametrize("other,expected", [("10", "10"), ("3", "5")])
def test_both_notional_filters_use_stricter_minimum(other, expected):
    doc = snapshot()
    doc["symbols"][0]["filters"][-1] = {"filterType": "MIN_NOTIONAL", "minNotional": "5"}
    doc["symbols"][0]["filters"].append({"filterType": "NOTIONAL", "minNotional": other})
    parsed = parse_filter_snapshot(json.dumps(doc).encode(), ("BTCUSDT",), futures=False)
    assert parsed["BTCUSDT"].min_notional == Decimal(expected)
