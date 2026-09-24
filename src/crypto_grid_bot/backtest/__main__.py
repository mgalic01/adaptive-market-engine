"""Historical replay commands: fetch, verify and run. Offline except ``fetch``.

    python -m crypto_grid_bot.backtest fetch  --spec config/datasets/verify-2024h1.toml
    python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml
    python -m crypto_grid_bot.backtest run    --spec config/datasets/verify-2024h1.toml \\
        --config config/default.toml
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from crypto_grid_bot.backtest.dataset import (
    fetch_dataset,
    load_manifest,
    load_spec,
    verify_dataset,
    write_manifest,
)
from crypto_grid_bot.backtest.features import FEATURE_VERSION, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.replay import (
    PATH_MODES,
    RunConfig,
    check_accounting,
    cross_check_hourly,
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
    spec_path: Path, config_path: Path, data_dir: Path, symbol: str, path_mode: str, gated: bool
) -> dict[str, Any]:
    spec, config = load_spec(spec_path), load_config(config_path)
    manifest = load_manifest(manifest_path(spec_path))
    rules = rules_for(
        symbol,
        manifest["instruments"][symbol],
        spec.fee_rate,
        spec.slippage_rate,
        spec.participation,
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
        round_trip_cost=float(2 * (spec.fee_rate + spec.slippage_rate) + spread),
        order_notional=float(spec.initial_quote * Decimal("0.8") / config.maximum_levels),
    )
    run = RunConfig(symbol, path_mode, gated, rules, spec.initial_quote, spread)
    metrics, account = replay(config, run, load_minutes(data_dir, manifest, symbol), features)
    return summarise(run, metrics, account, check_accounting(run, metrics, account))


def cross_check_job(spec_path: Path, data_dir: Path, symbol: str) -> dict[str, Any]:
    manifest = load_manifest(manifest_path(spec_path))
    hourly = load_hourly(data_dir, manifest, symbol)
    return {
        "symbol": symbol,
        **cross_check_hourly(load_minutes(data_dir, manifest, symbol), hourly),
    }


def _table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Pair | Path | Strategy | Return % | Max DD % | Buy&hold % | B&H DD % | Fees | "
        "Buys/Sells | Grids | Range exits | Invested % | Halted |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['symbol']} | {r['path_mode']} | {r['strategy']} | {r['return_pct']:.2f} | "
            f"{r['max_drawdown_pct']:.2f} | {r['buy_and_hold_return_pct']:.2f} | "
            f"{r['buy_and_hold_max_drawdown_pct']:.2f} | {Decimal(r['fees']):.2f} | "
            f"{r['buys']}/{r['sells']} | {r['grids_opened']} | {r['range_exits']} | "
            f"{r['time_with_inventory_pct']:.1f} | {r['halted_at'] or 'no'} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m crypto_grid_bot.backtest")
    parser.add_argument("command", choices=("fetch", "verify", "run"))
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config/default.toml"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--out", type=Path, default=Path("data/backtests"))
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    spec = load_spec(args.spec)
    if args.command == "fetch":
        manifest = fetch_dataset(spec, args.data_dir)
        write_manifest(manifest_path(args.spec), manifest)
        missing = [f for f in manifest["files"] if f["status"] == "missing"]
        print(json.dumps({"files": len(manifest["files"]), "missing": missing}, indent=1))
        return 0
    manifest = load_manifest(manifest_path(args.spec))
    verify_dataset(spec, manifest, args.data_dir)
    jobs = max(1, min(args.jobs, 8))
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        checks = [
            pool.submit(cross_check_job, args.spec, args.data_dir, symbol) for symbol in spec.traded
        ]
        if args.command == "verify":
            print(json.dumps([c.result() for c in checks], indent=1))
            return 0
        futures = [
            pool.submit(run_job, args.spec, args.config, args.data_dir, s, mode, gated)
            for s in spec.traded
            for mode in PATH_MODES
            for gated in (True, False)
        ]
        cross_checks = [c.result() for c in checks]
        results = [f.result() for f in futures]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out / spec.name / stamp
    out.mkdir(parents=True, exist_ok=True)
    document = {
        "dataset": spec.name,
        "purpose": spec.purpose,
        "feature_version": FEATURE_VERSION,
        "manifest_created_at": manifest["created_at"],
        "hourly_cross_checks": cross_checks,
        "results": results,
    }
    (out / "results.json").write_text(json.dumps(document, indent=1, default=str) + "\n")
    table = _table(results)
    (out / "summary.md").write_text(table + "\n")
    brief = [{k: v for k, v in r.items() if k != "hourly_equity"} for r in results]
    print(json.dumps({"out": str(out), "hourly_cross_checks": cross_checks}, indent=1))
    print(table)
    print(json.dumps(brief, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
