"""The V3 input pack: the frozen V3 arms' registered inputs, pinned once (Rulings P9, P15).

The unchanged V3 selector's walk-forward trains from BTCUSDT's first portfolio month
(2020-01), before any V3.1 window pack starts, so the V3 cells read a pack of their own.
``scripts/v31_v3_pack.py`` builds it with V3's own frozen assembly
(``v3_inventory_loader`` then ``v3_replay_assembly.assemble_replay_inputs``) and writes,
with ``write_v3_pack``, the fields of the assembled ``ReplayInputs`` that ``V3Inputs``
needs: the first months, the daily spot bars, the spot and futures exclusions, the futures
filters, the futures hourly bars and the funding. ``read_v3_pack`` rebuilds the frozen
``DailyDecisions`` from them as ``trend/experiment_runner.py`` does.

The file is gzip JSON, written and read as ``packs.write_pack``/``read_pack`` handle a
window pack (Ruling P11): the pin is the SHA-256 of the canonical JSON inside, checked
after a capped decompression and before parsing, and an existing file is never replaced.
Nothing at or after the reserved boundary (2025-01-01) is accepted. Pure: no network, and
``src`` never imports ``scripts``.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from pathlib import Path

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.combined.baseline_records import refuse_sealed
from crypto_grid_bot.combined.baseline_v3 import V3Inputs
from crypto_grid_bot.combined.driver.packs import (
    _KLINE_DECIMALS,
    _decimal,
    _int,
    _kline_row,
    _klines,
    _list,
    _object,
    _read_gzip_json,
    _str,
    _write_gzip_json,
)
from crypto_grid_bot.market_data.parsing import symbol_name
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters

_FORMAT = "v3.1-v3-input-pack/1"
_FILTERS = tuple(f.name for f in dataclasses.fields(OrderFilters))
_KEYS = frozenset(
    {
        "format",
        "first_months",
        "spot_bars",
        "spot_exclusions",
        "futures_exclusions",
        "futures_filters",
        "futures_hourly",
        "funding",
    }
)


@dataclass(frozen=True, slots=True)
class V3PackFields:
    """The fields of V3's assembled ``ReplayInputs`` (``scripts/v3_replay_assembly.py``)
    that the frozen V3 arms read, under the same names.

    One universe of coins, BTCUSDT among them: ``first_months``, ``spot_bars`` (daily),
    ``futures_filters`` and ``futures_hourly`` are keyed by exactly its symbols, and the
    exclusions by some of them. ``funding`` maps each settlement time to its coins' rates.
    """

    first_months: Mapping[str, str]
    spot_bars: Mapping[str, Sequence[Kline]]
    spot_exclusions: Mapping[str, frozenset[str]]
    futures_exclusions: Mapping[str, frozenset[str]]
    futures_filters: Mapping[str, OrderFilters]
    futures_hourly: Mapping[str, Sequence[Kline]]
    funding: Mapping[int, Mapping[str, Decimal]]


def write_v3_pack(fields: V3PackFields, path: str | Path) -> str:
    """Write ``fields`` to a new file at ``path`` and return the pack's pin: the SHA-256
    (hex) of the canonical JSON the file compresses.

    The JSON depends only on the fields (sorted keys, Decimals as their ``str()`` under a
    default context, bars in time order, exclusions sorted, funding as ``[time, {symbol:
    rate}]`` pairs in time order), so the pin is the same on any machine. Refuses, before
    anything is written, fields ``read_v3_pack`` would refuse: another universe per field,
    no BTCUSDT, bars out of order, a value that is not a finite Decimal, and any month,
    bar or funding time at or after the reserved boundary. An existing file is refused.
    """
    if not isinstance(fields, V3PackFields):
        raise ValueError("V3 pack fields required")
    _check(fields)
    with localcontext(Context()):  # str() reads the context's exponent letter case
        document = _document(fields)
    return _write_gzip_json(document, path)


def read_v3_pack_fields(path: str | Path, expected_sha256: str) -> V3PackFields:
    """The fields of the pack at ``path``, equal to the ones written; the SHA-256 of its
    JSON must be ``expected_sha256``, checked before the JSON is parsed."""
    document = _read_gzip_json(path, expected_sha256)
    with localcontext(Context()):
        fields = _fields_from(document)
    _check(fields)
    return fields


def read_v3_pack(path: str | Path, expected_sha256: str) -> V3Inputs:
    """The frozen V3 arms' inputs from the pack at ``path``, pinned by ``expected_sha256``
    (the run-manifest's ``v3_pack_sha256``).

    As ``trend/experiment_runner.py`` builds them: ``DailyDecisions(spot_bars,
    first_months, union)``, where ``union`` gives each coin of the universe its futures
    exclusions joined with its spot exclusions; the futures filters, the futures hourly
    bars and the funding are passed as they are.
    """
    fields = read_v3_pack_fields(path, expected_sha256)
    union = {
        symbol: fields.futures_exclusions.get(symbol, frozenset())
        | fields.spot_exclusions.get(symbol, frozenset())
        for symbol in sorted(fields.first_months)
    }
    decisions = DailyDecisions(fields.spot_bars, fields.first_months, union)
    return V3Inputs(decisions, fields.futures_filters, fields.futures_hourly, fields.funding)


def _check(fields: V3PackFields) -> None:
    """Refuse fields the frozen V3 arms could not read as V3's registered run did."""
    universe = set(fields.first_months)
    if "BTCUSDT" not in universe:
        raise ValueError("V3 pack: the universe must hold BTCUSDT")
    for symbol, month in fields.first_months.items():
        symbol_name(symbol)
        development_month(month)
    for name in ("spot_bars", "futures_filters", "futures_hourly"):
        if set(getattr(fields, name)) != universe:
            raise ValueError(f"V3 pack {name}: the coins of first_months required")
    for name in ("spot_exclusions", "futures_exclusions"):
        exclusions = getattr(fields, name)
        if not set(exclusions) <= universe:
            raise ValueError(f"V3 pack {name}: a coin outside first_months")
        for symbol, months in exclusions.items():
            if not isinstance(months, frozenset):
                raise ValueError(f"V3 pack {name} {symbol}: a frozenset of months required")
            for month in months:
                development_month(month)
    for name in ("spot_bars", "futures_hourly"):
        for symbol, bars in getattr(fields, name).items():
            what = f"V3 pack {name} {symbol}"
            if any(not isinstance(bar, Kline) for bar in bars):
                raise ValueError(f"{what}: klines required")
            stamps = [bar.open_ms for bar in bars]
            refuse_sealed(stamps, what)
            if any(later <= earlier for earlier, later in zip(stamps, stamps[1:], strict=False)):
                raise ValueError(f"{what}: bars in strictly ascending time order required")
            for bar in bars:
                for field in _KLINE_DECIMALS:
                    _finite(getattr(bar, field), what)
    for symbol, filters in fields.futures_filters.items():
        if not isinstance(filters, OrderFilters):
            raise ValueError(f"V3 pack futures filters {symbol}: OrderFilters required")
        for field in _FILTERS:
            _finite(getattr(filters, field), f"V3 pack futures filters {symbol}")
    refuse_sealed(fields.funding, "V3 pack funding")
    for stamp, rates in fields.funding.items():
        if not rates or not set(rates) <= universe:
            raise ValueError(f"V3 pack funding {stamp}: rates of first_months coins required")
        for value in rates.values():
            _finite(value, f"V3 pack funding {stamp}")


def _finite(value: object, what: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{what}: finite Decimals required")


def _document(fields: V3PackFields) -> dict[str, object]:
    return {
        "format": _FORMAT,
        "first_months": dict(fields.first_months),
        "spot_bars": {s: [_kline_row(bar) for bar in bars] for s, bars in fields.spot_bars.items()},
        "spot_exclusions": {s: sorted(months) for s, months in fields.spot_exclusions.items()},
        "futures_exclusions": {
            s: sorted(months) for s, months in fields.futures_exclusions.items()
        },
        "futures_filters": {
            s: {name: str(getattr(filters, name)) for name in _FILTERS}
            for s, filters in fields.futures_filters.items()
        },
        "futures_hourly": {
            s: [_kline_row(bar) for bar in bars] for s, bars in fields.futures_hourly.items()
        },
        "funding": [
            [stamp, {s: str(rate) for s, rate in rates.items()}]
            for stamp, rates in sorted(fields.funding.items())
        ],
    }


def _symbols(value: object, what: str) -> dict[str, object]:
    """A JSON object keyed by symbols."""
    if not isinstance(value, dict):
        raise ValueError(f"V3 pack {what}: an object keyed by symbol required")
    for symbol in value:
        symbol_name(symbol)
    return value


def _months(value: object, what: str) -> frozenset[str]:
    months = [_str(month, what) for month in _list(value, what)]
    if months != sorted(set(months)):
        raise ValueError(f"V3 pack {what}: months sorted, each once, required")
    return frozenset(months)


def _filters_from(value: object, what: str) -> OrderFilters:
    document = _object(value, frozenset(_FILTERS), what)
    return OrderFilters(*(_decimal(document[name], what) for name in _FILTERS))


def _funding_from(value: object) -> dict[int, dict[str, Decimal]]:
    funding: dict[int, dict[str, Decimal]] = {}
    previous: int | None = None
    for item in _list(value, "funding"):
        pair = _list(item, "funding")
        if len(pair) != 2:
            raise ValueError("V3 pack funding: [time, rates] pairs required")
        stamp = _int(pair[0], "funding time")
        if previous is not None and stamp <= previous:
            raise ValueError("V3 pack funding: times in strictly ascending order required")
        previous = stamp
        rates = _symbols(pair[1], f"funding {stamp}")
        funding[stamp] = {
            symbol: _decimal(rate, f"funding {stamp} {symbol}") for symbol, rate in rates.items()
        }
    return funding


def _fields_from(value: object) -> V3PackFields:
    document = _object(value, _KEYS, "V3 document")
    if document["format"] != _FORMAT:
        raise ValueError(f"V3 pack: format {_FORMAT!r} required")
    first = _symbols(document["first_months"], "first months")
    return V3PackFields(
        first_months={s: _str(month, f"{s} first month") for s, month in first.items()},
        spot_bars={
            s: _klines(rows, f"{s} spot bars")
            for s, rows in _symbols(document["spot_bars"], "spot bars").items()
        },
        spot_exclusions={
            s: _months(months, f"{s} spot exclusions")
            for s, months in _symbols(document["spot_exclusions"], "spot exclusions").items()
        },
        futures_exclusions={
            s: _months(months, f"{s} futures exclusions")
            for s, months in _symbols(document["futures_exclusions"], "futures exclusions").items()
        },
        futures_filters={
            s: _filters_from(filters, f"{s} futures filters")
            for s, filters in _symbols(document["futures_filters"], "futures filters").items()
        },
        futures_hourly={
            s: _klines(rows, f"{s} futures hourly")
            for s, rows in _symbols(document["futures_hourly"], "futures hourly").items()
        },
        funding=_funding_from(document["funding"]),
    )
