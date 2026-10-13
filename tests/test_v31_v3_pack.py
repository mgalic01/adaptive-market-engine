"""The V3 input pack: V3's own frozen assembly, written once and read back as V3's inputs.

Synthetic only: a hand-built inventory of decoded months, most of them missing, never
market data. The frozen loader's own test builds files on disk; here a spy stands in for
it and checks the call. Nothing touches the network.
"""

import gzip
import hashlib
import json
import sys
from dataclasses import replace
from decimal import Context, localcontext
from decimal import Decimal as D
from pathlib import Path

import combined_market_fixtures as fx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_v3_data import SYMBOLS  # noqa: E402
from v3_inventory import planned_requests  # noqa: E402
from v3_inventory_loader import InventoryInputs  # noqa: E402
from v3_replay_inputs import DecodedMonth  # noqa: E402

from crypto_grid_bot.backtest.funding import FundingRecord  # noqa: E402
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms  # noqa: E402
from crypto_grid_bot.combined.assessment import daily_bars  # noqa: E402
from crypto_grid_bot.combined.baseline_v3 import V3Inputs  # noqa: E402
from crypto_grid_bot.combined.driver.v3_pack import (  # noqa: E402
    V3PackFields,
    read_v3_pack,
    read_v3_pack_fields,
    write_v3_pack,
)
from crypto_grid_bot.trend.decisions import DailyDecisions  # noqa: E402
from crypto_grid_bot.trend.filters import OrderFilters  # noqa: E402

HOUR = 3_600_000
DAY = 24 * HOUR
RESERVED = 1_735_689_600_000  # 2025-01-01T00:00Z
JOIN = "2020-01"  # every coin's first portfolio month
WARMUP = "2019-11"  # BTC's and ETH's first full spot month: two months of signal warm-up
SPOT_MONTHS = ("2019-11", "2019-12", "2020-01", "2020-02", "2020-03")
FUTURES_MONTHS = ("2020-01", "2020-02", "2020-03")
PATHS = {"BTCUSDT": fx.uptrend, "ETHUSDT": fx.downtrend}
FILTERS = OrderFilters(
    D("0.001"), D("100000"), D("0.001"), D("5"), D("0.001"), D("100000"), D("0.001"), D("0")
)


def _hours(path, months, wick):
    """Hourly bars over ``months``, split by month."""
    start, end = month_bounds_ms(months[0])[0], month_bounds_ms(months[-1])[1]
    bars = fx.hourly(path, (end - start) // HOUR, start=start, wick=wick)
    by_month = {}
    for month in months:
        first, stop = month_bounds_ms(month)
        by_month[month] = tuple(bar for bar in bars if first <= bar.open_ms < stop)
    return by_month


def synthetic_inventory() -> tuple[InventoryInputs, dict[str, str]]:
    """Every planned month missing, except BTC and ETH, which carry two months of spot
    warm-up, three months of futures and funding, an excluded ETH spot month and an
    excluded BTC funding month; the other eight coins join on an eligible empty month."""
    months = {key: DecodedMonth(*key, "missing") for key in planned_requests()}
    first = dict.fromkeys(sorted(SYMBOLS), JOIN)
    spot_first = {symbol: WARMUP if symbol in PATHS else JOIN for symbol in SYMBOLS}
    for symbol in SYMBOLS:
        for kind in ("spot", "futures", "funding"):
            months[kind, symbol, JOIN] = DecodedMonth(kind, symbol, JOIN, "eligible")
    for symbol, path in PATHS.items():
        for month, rows in _hours(path, SPOT_MONTHS, 0.01).items():
            status = "excluded" if (symbol, month) == ("ETHUSDT", "2020-02") else "eligible"
            months["spot", symbol, month] = DecodedMonth(
                "spot", symbol, month, status, rows, daily_bars(rows), hold_hourly=rows
            )
        for month, rows in _hours(path, FUTURES_MONTHS, 0.02).items():
            months["futures", symbol, month] = DecodedMonth(
                "futures", symbol, month, "eligible", rows, daily_bars(rows)
            )
        rate = D("0.0001") if symbol == "BTCUSDT" else D("-0.00005")
        for month in FUTURES_MONTHS:
            first_ms, end_ms = month_bounds_ms(month)
            records = tuple(
                FundingRecord(stamp + 3, 8, rate) for stamp in range(first_ms, end_ms, 8 * HOUR)
            )
            status = "excluded" if (symbol, month) == ("BTCUSDT", "2020-03") else "eligible"
            months["funding", symbol, month] = DecodedMonth(
                "funding", symbol, month, status, funding=records
            )
    filters = dict.fromkeys(sorted(SYMBOLS), FILTERS)
    coverage = {
        "coins": {
            symbol: {
                "first_portfolio_month_candidate": first[symbol],
                "first_full_spot_month_candidate": spot_first[symbol],
            }
            for symbol in SYMBOLS
        }
    }
    inventory = InventoryInputs(
        "a" * 64, "b" * 64, tuple(months.values()), filters, filters, coverage
    )
    return inventory, first


def fields_of(assembled) -> V3PackFields:
    """The fields of V3's own ``ReplayInputs`` the pack carries."""
    return V3PackFields(
        first_months=assembled.first_months,
        spot_bars=assembled.spot_bars,
        spot_exclusions=assembled.spot_exclusions,
        futures_exclusions=assembled.futures_exclusions,
        futures_filters=assembled.futures_filters,
        futures_hourly=assembled.futures_hourly,
        funding=assembled.funding,
    )


@pytest.fixture(scope="module")
def assembled():
    from v3_replay_assembly import assemble_replay_inputs

    inventory, first = synthetic_inventory()
    return assemble_replay_inputs(inventory, first)


def experiment_runner_decisions(assembled) -> DailyDecisions:
    """The decisions exactly as ``trend/experiment_runner.py`` builds them from V3's
    assembled inputs: the spot bars, the first months and, per coin of the universe, the
    union of its futures and spot exclusions."""
    universe = set(assembled.first_months)
    union = {
        symbol: (assembled.futures_exclusions or {}).get(symbol, frozenset())
        | (assembled.spot_exclusions or {}).get(symbol, frozenset())
        for symbol in universe
    }
    return DailyDecisions(assembled.spot_bars, assembled.first_months, union)


def test_v3_pack_round_trips_and_rebuilds_the_same_decisions(assembled, tmp_path):
    fields = fields_of(assembled)
    path = tmp_path / "v3.json.gz"
    sha = write_v3_pack(fields, path)

    # The pin is the SHA-256 of the canonical JSON inside the gzip, not of the file.
    content = gzip.decompress(path.read_bytes())
    assert sha == hashlib.sha256(content).hexdigest()
    document = json.loads(content)
    assert content == json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    assert set(document) == {
        "format",
        "first_months",
        "spot_bars",
        "spot_exclusions",
        "futures_exclusions",
        "futures_filters",
        "futures_hourly",
        "funding",
    }
    # The same fields give the same pin, whatever decimal context the caller holds.
    with localcontext(Context(prec=5, capitals=0)):
        assert write_v3_pack(fields, tmp_path / "again.json.gz") == sha

    assert read_v3_pack_fields(path, sha) == fields
    inputs = read_v3_pack(path, sha)
    assert isinstance(inputs, V3Inputs)
    assert inputs.filters == assembled.futures_filters
    assert inputs.hourly == assembled.futures_hourly
    assert inputs.funding == assembled.funding
    assert list(inputs.funding) == list(assembled.funding)  # ascending, as assembled

    direct = experiment_runner_decisions(assembled)
    decisions = inputs.decisions
    assert decisions.first_months == direct.first_months
    assert decisions.excluded_months == direct.excluded_months
    assert "2020-02" in decisions.excluded_months["ETHUSDT"]  # a spot exclusion
    assert "2020-03" in decisions.excluded_months["BTCUSDT"]  # a funding exclusion
    traded = 0
    start, end = month_bounds_ms(JOIN)[0], month_bounds_ms(FUTURES_MONTHS[-1])[1]
    for day in range(start, end, DAY):
        for rule in ("R1", "R4L", None):
            decision = decisions.at(day, rule)
            assert decision == direct.at(day, rule)
            traded += any(decision.targets.values())
    assert traded  # the decisions compared are not all flat


def test_v3_pack_refuses_another_pin_and_never_replaces_a_file(assembled, tmp_path):
    fields = fields_of(assembled)
    path = tmp_path / "v3.json.gz"
    sha = write_v3_pack(fields, path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_v3_pack(fields, path)
    assert path.read_bytes() == before
    with pytest.raises(ValueError, match="differs from the pinned"):
        read_v3_pack(path, "0" * 64)
    with pytest.raises(ValueError, match="64 lowercase hex"):
        read_v3_pack(path, sha.upper())
    other = tmp_path / "other.json.gz"
    other.write_bytes(gzip.compress(b'{"format":"v3.1-input-pack/1"}'))
    with pytest.raises(ValueError):
        read_v3_pack(other, hashlib.sha256(b'{"format":"v3.1-input-pack/1"}').hexdigest())


SEALED = Kline(RESERVED, *([D(1)] * 6), D(0))


@pytest.mark.parametrize(
    "damage",
    ["spot_bar", "futures_bar", "funding", "first_month", "exclusion", "universe", "no_btc"],
)
def test_v3_pack_refuses_sealed_or_inconsistent_inputs(assembled, tmp_path, damage):
    fields = fields_of(assembled)
    btc = "BTCUSDT"
    if damage == "spot_bar":
        fields = replace(
            fields, spot_bars={**fields.spot_bars, btc: (*fields.spot_bars[btc], SEALED)}
        )
    elif damage == "futures_bar":
        hourly = {**fields.futures_hourly, btc: (*fields.futures_hourly[btc], SEALED)}
        fields = replace(fields, futures_hourly=hourly)
    elif damage == "funding":
        fields = replace(fields, funding={**fields.funding, RESERVED + 3: {btc: D("0.0001")}})
    elif damage == "first_month":
        fields = replace(fields, first_months={**fields.first_months, btc: "2025-01"})
    elif damage == "exclusion":
        exclusions = {**fields.spot_exclusions, btc: frozenset({"2025-01"})}
        fields = replace(fields, spot_exclusions=exclusions)
    elif damage == "universe":
        filters = {s: f for s, f in fields.futures_filters.items() if s != "ETHUSDT"}
        fields = replace(fields, futures_filters=filters)
    else:
        fields = replace(
            fields,
            first_months={s: m for s, m in fields.first_months.items() if s != btc},
            spot_bars={s: b for s, b in fields.spot_bars.items() if s != btc},
            spot_exclusions={s: m for s, m in fields.spot_exclusions.items() if s != btc},
            futures_exclusions={s: m for s, m in fields.futures_exclusions.items() if s != btc},
            futures_filters={s: f for s, f in fields.futures_filters.items() if s != btc},
            futures_hourly={s: h for s, h in fields.futures_hourly.items() if s != btc},
            funding={
                t: {s: r for s, r in g.items() if s != btc} for t, g in fields.funding.items()
            },
        )
        fields = replace(fields, funding={t: g for t, g in fields.funding.items() if g})
    with pytest.raises(ValueError):
        write_v3_pack(fields, tmp_path / "v3.json.gz")
    assert not (tmp_path / "v3.json.gz").exists()


def test_v3_pack_builder_matches_v3s_own_assembly(tmp_path, monkeypatch):
    import v3_inventory_loader
    import v3_replay_assembly
    import v31_v3_pack

    # The builder calls V3's own frozen loader and assembly, not copies of them.
    assert v31_v3_pack.load_inventory_inputs is v3_inventory_loader.load_inventory_inputs
    assert v31_v3_pack.assemble_replay_inputs is v3_replay_assembly.assemble_replay_inputs

    inventory, first = synthetic_inventory()
    calls = []

    def load(root, manifest_sha256):
        calls.append((root, manifest_sha256))
        return inventory

    monkeypatch.setattr(v31_v3_pack, "load_inventory_inputs", load)
    root, manifest, path = tmp_path / "inventory", "e" * 64, tmp_path / "v3.json.gz"
    sha = v31_v3_pack.build_v3_pack(root, manifest, first, path)
    assert calls == [(root, manifest)]

    expected = fields_of(v3_replay_assembly.assemble_replay_inputs(inventory, first))
    assert read_v3_pack_fields(path, sha) == expected
    assert write_v3_pack(expected, tmp_path / "direct.json.gz") == sha

    # A calendar V3's assembly refuses is refused, and no pack is written.
    with pytest.raises(ValueError, match="calendar"):
        v31_v3_pack.build_v3_pack(root, manifest, {**first, "BTCUSDT": "2020-02"}, tmp_path / "x")
    assert not (tmp_path / "x").exists()
