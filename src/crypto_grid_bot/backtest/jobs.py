"""Work the backtest CLI sends to its process pool.

These functions live here, not in ``__main__``, because a pool pickles them by module
and name. Under the spawn start method (the Windows and macOS default), a worker does
not re-run a package's ``__main__``, so functions defined there by
``python -m crypto_grid_bot.backtest`` cannot be found and every job failed with
``BrokenProcessPool``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.dataset import load_manifest, load_spec
from crypto_grid_bot.backtest.features import FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.replay import (
    VOLUME_DRIFT_TOLERANCE,
    RunConfig,
    check_accounting,
    check_hourly_series,
    cross_check_daily,
    cross_check_hourly,
    load_daily,
    load_hourly,
    load_minutes,
    replay,
    rules_for,
    summarise,
)
from crypto_grid_bot.config import load_config


def manifest_path(spec_path: Path) -> Path:
    return spec_path.with_name(spec_path.stem + ".manifest.json")


def run_job(
    spec_path: Path,
    config_path: Path,
    data_dir: Path,
    symbol: str,
    path_mode: str,
    gated: bool,
    fees: tuple[Decimal, Decimal | None] | None = None,
) -> dict[str, Any]:
    """``fees`` is (maker, taker) overriding the spec; taker None means maker."""
    spec, config = load_spec(spec_path), load_config(config_path)
    manifest = load_manifest(manifest_path(spec_path))
    maker, taker = fees or (spec.fee_rate, None)
    rules = rules_for(
        symbol,
        manifest["instruments"][symbol],
        maker,
        spec.slippage_rate,
        spec.participation,
        taker,
    )
    spread = spec.assumed_spread_pct / 100
    pair = SeriesFeatures(symbol, load_hourly(data_dir, manifest, symbol))
    market = (
        pair
        if spec.market_proxy == symbol
        else SeriesFeatures(spec.market_proxy, load_hourly(data_dir, manifest, spec.market_proxy))
    )
    basket = [
        SeriesFeatures(s, load_hourly(data_dir, manifest, s), full=False)
        for s in spec.breadth_basket
    ]
    features = FeatureEngine(
        pair,
        market,
        basket,
        range_atr_multiple=config.range_atr_multiple,
        levels=config.maximum_levels,
        minimum_cost_multiple=config.minimum_grid_cost_multiple,
        # A grid cycle is two resting fills, so it pays the maker fee twice.
        round_trip_cost=float(2 * (maker + spec.slippage_rate) + spread),
    )
    run = RunConfig(symbol, path_mode, gated, rules, spec.initial_quote, spread)
    metrics, account = replay(config, run, load_minutes(data_dir, manifest, symbol), features)
    return summarise(run, metrics, account, check_accounting(run, metrics, account))


def cross_check_job(
    spec_path: Path, data_dir: Path, symbol: str, strict_volume: bool = False
) -> dict[str, Any]:
    tolerance = Decimal(0) if strict_volume else VOLUME_DRIFT_TOLERANCE
    spec, manifest = load_spec(spec_path), load_manifest(manifest_path(spec_path))
    hourly = load_hourly(data_dir, manifest, symbol)
    window = (month_bounds_ms(spec.start)[0], month_bounds_ms(spec.end)[1])
    if symbol in spec.traded:
        minutes = load_minutes(data_dir, manifest, symbol)
        result = {"symbol": symbol, **cross_check_hourly(minutes, hourly, window, tolerance)}
    else:
        # No minute data: check the hours over warm-up and evaluation. Only a basket
        # symbol may have documented absences; the proxy must be complete.
        proxy = symbol == spec.market_proxy
        excluded = [(e.start_ms, e.end_ms) for e in spec.basket_exclusions if e.symbol == symbol]
        hourly_window = (month_bounds_ms(spec.warmup_start)[0], window[1])
        result = {
            "symbol": symbol,
            "role": "market_proxy" if proxy else "breadth_basket",
            **check_hourly_series(hourly, hourly_window, excluded),
        }
    if spec.daily_warmup_start and symbol in {*spec.traded, spec.market_proxy}:
        daily = load_daily(data_dir, manifest, symbol)
        result |= cross_check_daily(
            daily,
            hourly,
            (month_bounds_ms(spec.daily_warmup_start)[0], window[1]),
            (month_bounds_ms(spec.warmup_start)[0], window[1]),
            window[0],
            tolerance,
        )
    return result
