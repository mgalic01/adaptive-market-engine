"""Assemble already verified inventory records; no data access or authorization."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from fetch_v3_data import SYMBOLS
from v3_inventory import planned_requests
from v3_inventory_loader import InventoryInputs

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.window import development_month
from crypto_grid_bot.trend.filters import OrderFilters


@dataclass(frozen=True, slots=True)
class ReplayInputs:
    manifest_sha256: str
    spec_sha256: str
    first_months: dict[str, str]
    spot_bars: dict[str, tuple[Kline, ...]]
    spot_hourly: dict[str, tuple[Kline, ...]]
    futures_hourly: dict[str, tuple[Kline, ...]]
    spot_filters: dict[str, OrderFilters]
    futures_filters: dict[str, OrderFilters]
    funding: dict[int, dict[str, Decimal]]
    spot_exclusions: dict[str, frozenset[str]]
    futures_exclusions: dict[str, frozenset[str]]
    replay_ready: Literal[False] = False


def assemble_replay_inputs(
    inventory: InventoryInputs, first_months: Mapping[str, str]
) -> ReplayInputs:
    """Join verified months against an explicit, matching candidate calendar.

    Caller must obtain inventory from load_inventory_inputs, review coverage and
    commit registration before historical dispatch. Matching this calendar is not
    approval; a disputed candidate must be resolved upstream. Pre-join eligible
    spot history remains warmup. Post-join daily signals omit either market's
    excluded months. Available hourly prices stay market-specific for accounting.
    """
    if any(
        set(mapping) != SYMBOLS
        for mapping in (first_months, inventory.spot_filters, inventory.futures_filters)
    ):
        raise ValueError("the fixed ten-symbol universe is required")
    first = {symbol: development_month(month) for symbol, month in first_months.items()}
    coins = inventory.coverage.get("coins", {})
    if any(
        coins.get(symbol, {}).get("first_portfolio_month_candidate") != month
        for symbol, month in first.items()
    ):
        raise ValueError("explicit join calendar differs from verified coverage candidate")
    indexed = {(m.kind, m.symbol, m.month): m for m in inventory.months}
    if len(indexed) != len(inventory.months) or set(indexed) != set(planned_requests()):
        raise ValueError("complete unique fixed inventory required")
    if any(m.status not in {"eligible", "excluded", "missing"} for m in indexed.values()):
        raise ValueError("unknown decoded status")
    for symbol, month in first.items():
        if any(
            indexed[kind, symbol, month].status != "eligible"
            for kind in ("spot", "futures", "funding")
        ):
            raise ValueError("join month must be eligible in both markets and funding")
    spot_exclusions, futures_exclusions = {}, {}
    for symbol in sorted(SYMBOLS):
        months = {
            month
            for kind, coin, month in indexed
            if kind == "futures" and coin == symbol and month >= first[symbol]
        }
        spot_exclusions[symbol] = frozenset(
            month for month in months if indexed["spot", symbol, month].status != "eligible"
        )
        futures_exclusions[symbol] = frozenset(
            month
            for month in months
            if any(
                indexed[kind, symbol, month].status != "eligible" for kind in ("futures", "funding")
            )
        )
    daily: dict[str, list[Kline]] = {s: [] for s in sorted(SYMBOLS)}
    spot: dict[str, list[Kline]] = {s: [] for s in sorted(SYMBOLS)}
    futures: dict[str, list[Kline]] = {s: [] for s in sorted(SYMBOLS)}
    funding: dict[int, dict[str, Decimal]] = {}
    for (_, symbol, month), decoded in sorted(indexed.items()):
        if decoded.status != "eligible":
            continue
        if decoded.kind == "spot":
            spot[symbol].extend(decoded.hourly)
            if month not in spot_exclusions[symbol] | futures_exclusions[symbol]:
                daily[symbol].extend(decoded.daily)
        elif decoded.kind == "futures":
            futures[symbol].extend(decoded.hourly)
        else:
            for event in decoded.funding:
                group = funding.setdefault(event.calc_time_ms, {})
                if symbol in group:
                    raise ValueError("duplicate funding timestamp for symbol")
                group[symbol] = event.rate

    def ordered(rows: dict[str, list[Kline]]) -> dict[str, tuple[Kline, ...]]:
        result = {}
        for symbol, values in rows.items():
            values.sort(key=lambda row: row.open_ms)
            if len({row.open_ms for row in values}) != len(values):
                raise ValueError("duplicate assembled bar")
            result[symbol] = tuple(values)
        return result

    return ReplayInputs(
        inventory.manifest_sha256,
        inventory.spec_sha256,
        first,
        ordered(daily),
        ordered(spot),
        ordered(futures),
        dict(inventory.spot_filters),
        dict(inventory.futures_filters),
        dict(sorted(funding.items())),
        spot_exclusions,
        futures_exclusions,
    )
