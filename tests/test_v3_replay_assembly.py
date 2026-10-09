import sys
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_v3_data import SYMBOLS  # noqa: E402
from v3_inventory import planned_requests  # noqa: E402
from v3_inventory_loader import InventoryInputs  # noqa: E402
from v3_replay_inputs import DecodedMonth  # noqa: E402

from crypto_grid_bot.backtest.funding import FundingRecord  # noqa: E402
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms  # noqa: E402


def bar(month, value=100):
    return Kline(month_bounds_ms(month)[0], *([D(value)] * 7))


@pytest.fixture
def inputs():
    months = {key: DecodedMonth(*key, "missing") for key in planned_requests()}
    first = dict.fromkeys(SYMBOLS, "2023-04")
    for symbol in SYMBOLS:
        for kind in ("spot", "futures", "funding"):
            months[kind, symbol, "2023-04"] = DecodedMonth(kind, symbol, "2023-04", "eligible")
    for month in ("2023-03", "2023-05"):
        months["spot", "BTCUSDT", month] = DecodedMonth(
            "spot", "BTCUSDT", month, "eligible", (bar(month),), (bar(month),)
        )
    for month in ("2023-05", "2023-06"):
        months["futures", "BTCUSDT", month] = DecodedMonth(
            "futures", "BTCUSDT", month, "eligible", (bar(month, 200),), (bar(month, 200),)
        )
    stamp = month_bounds_ms("2023-06")[0] + 47
    months["funding", "BTCUSDT", "2023-06"] = DecodedMonth(
        "funding",
        "BTCUSDT",
        "2023-06",
        "eligible",
        funding=(FundingRecord(stamp, 8, D("0.0001")),),
    )
    filters = dict.fromkeys(SYMBOLS, object())
    loaded = InventoryInputs(
        "a" * 64,
        "b" * 64,
        tuple(months.values()),
        filters,
        filters,
        {"coins": {s: {"first_portfolio_month_candidate": m} for s, m in first.items()}},
    )
    return loaded, first


def test_preserves_spot_warmup_separates_markets_and_combines_exclusions(inputs):
    from v3_replay_assembly import assemble_replay_inputs

    loaded, first = inputs
    result = assemble_replay_inputs(loaded, first)
    assert result.first_months == first
    assert result.manifest_sha256 == loaded.manifest_sha256
    assert result.spec_sha256 == loaded.spec_sha256
    assert result.replay_ready is False
    assert result.spot_bars["BTCUSDT"] == (bar("2023-03"),)
    assert result.spot_hourly["BTCUSDT"] == (bar("2023-03"), bar("2023-05"))
    assert result.futures_hourly["BTCUSDT"] == (bar("2023-05", 200), bar("2023-06", 200))
    assert "2023-05" in result.futures_exclusions["BTCUSDT"]
    assert "2023-05" not in result.spot_exclusions["BTCUSDT"]
    assert "2023-06" in result.spot_exclusions["BTCUSDT"]
    assert "2023-06" not in result.futures_exclusions["BTCUSDT"]
    assert "2023-03" not in result.futures_exclusions["BTCUSDT"]
    assert result.funding == {month_bounds_ms("2023-06")[0] + 47: {"BTCUSDT": D("0.0001")}}


@pytest.mark.parametrize("damage", ["duplicate", "missing", "calendar", "reserved", "filters"])
def test_refuses_mismatched_inventory_or_calendar(inputs, damage):
    from v3_replay_assembly import assemble_replay_inputs

    loaded, first = inputs
    if damage == "duplicate":
        loaded = replace(loaded, months=loaded.months + loaded.months[:1])
    elif damage == "missing":
        loaded = replace(loaded, months=loaded.months[1:])
    elif damage == "calendar":
        first["BTCUSDT"] = "2023-05"
    elif damage == "reserved":
        first["BTCUSDT"] = "2025-01"
    else:
        loaded = replace(loaded, spot_filters={})
    with pytest.raises(ValueError):
        assemble_replay_inputs(loaded, first)


def test_simultaneous_coins_share_raw_funding_group(inputs):
    from v3_replay_assembly import assemble_replay_inputs

    loaded, first = inputs
    stamp = month_bounds_ms("2023-06")[0] + 47
    months = tuple(
        replace(m, status="eligible", funding=(FundingRecord(stamp, 8, D("-0.0002")),))
        if (m.kind, m.symbol, m.month) == ("funding", "ETHUSDT", "2023-06")
        else m
        for m in loaded.months
    )
    result = assemble_replay_inputs(replace(loaded, months=months), first)
    assert result.funding[stamp] == {"BTCUSDT": D("0.0001"), "ETHUSDT": D("-0.0002")}


@pytest.mark.parametrize("kind", ["spot", "funding"])
def test_duplicate_decoded_records_are_not_silently_overwritten(inputs, kind):
    from v3_replay_assembly import assemble_replay_inputs

    loaded, first = inputs
    changed = []
    for month in loaded.months:
        if month.kind == kind and month.symbol == "BTCUSDT":
            month = replace(month, hourly=month.hourly * 2, funding=month.funding * 2)
        changed.append(month)
    with pytest.raises(ValueError, match="duplicate"):
        assemble_replay_inputs(replace(loaded, months=tuple(changed)), first)
