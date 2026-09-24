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
    fee_rate,
    fetch_dataset,
    load_manifest,
    load_spec,
    sha256_file,
    verify_dataset,
    write_manifest,
)
from crypto_grid_bot.backtest.features import FEATURE_VERSION, FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.replay import (
    PATH_MODES,
    RunConfig,
    check_accounting,
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


def cross_check_job(spec_path: Path, data_dir: Path, symbol: str) -> dict[str, Any]:
    spec, manifest = load_spec(spec_path), load_manifest(manifest_path(spec_path))
    hourly = load_hourly(data_dir, manifest, symbol)
    window = (month_bounds_ms(spec.start)[0], month_bounds_ms(spec.end)[1])
    minutes = load_minutes(data_dir, manifest, symbol)
    result = {"symbol": symbol, **cross_check_hourly(minutes, hourly, window)}
    if spec.daily_warmup_start:
        daily = load_daily(data_dir, manifest, symbol)
        result |= cross_check_daily(
            daily,
            hourly,
            (month_bounds_ms(spec.daily_warmup_start)[0], window[1]),
            (month_bounds_ms(spec.warmup_start)[0], window[1]),
            window[0],
        )
    return result


# Any non-zero value means the minute data cannot be trusted for this window.
INTEGRITY_FIELDS = (
    "hours_mismatched",
    "hours_missing",
    "hours_absent_from_minutes",
    "hours_absent_from_both",
    "hours_incomplete",
    "minutes_missing",
)


# Present only when the spec declares daily_warmup_start (spec v1 P3).
DAILY_INTEGRITY_FIELDS = (
    "daily_days_mismatched",
    "daily_days_missing",
    "daily_days_duplicated",
    "daily_days_hours_incomplete",
    "daily_warmup_short",
)


def integrity_failures(checks: list[dict[str, Any]]) -> list[str]:
    """Chronology/completeness failures. Genuine listing gaps are not exempted yet:
    a dataset spanning a listing or delisting must be declared explicitly first."""
    failures = [
        f"{check['symbol']}: {field}={check[field]}"
        for check in checks
        for field in INTEGRITY_FIELDS
        if check[field]
    ]
    failures += [f"{c['symbol']}: no hours compared" for c in checks if not c["hours_compared"]]
    for check in checks:
        if "daily_days_compared" not in check:
            continue
        failures += [
            f"{check['symbol']}: {field}={check[field]}"
            for field in DAILY_INTEGRITY_FIELDS
            if check[field]
        ]
        if not check["daily_days_compared"]:
            failures.append(f"{check['symbol']}: no daily bars compared")
    return failures


def result_failures(results: list[dict[str, Any]]) -> list[str]:
    failures = []
    for r in results:
        name = f"{r['symbol']}/{r['path_mode']}/{r['strategy']}"
        failures += [f"{name}: {problem}" for problem in r["accounting_problems"]]
        if r["transient_pauses"]:
            failures.append(f"{name}: {r['transient_pauses']} rejected frames")
        if not r["bars"]:
            failures.append(f"{name}: no evaluation bars")
    return failures


def _identity(spec_path: Path, config_path: Path) -> dict[str, str]:
    return {
        "spec_sha256": sha256_file(spec_path),
        "manifest_sha256": sha256_file(manifest_path(spec_path)),
        "config_sha256": sha256_file(config_path),
    }


def _table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Pair | Path | Strategy | Return % | Max DD % | Buy&hold % | B&H DD % | Fees | "
        "Buys/Sells | Grids | Range exits | Invested % | Max req/day | Halted |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| --- |",
    ]
    for r in results:
        lines.append(
            f"| {r['symbol']} | {r['path_mode']} | {r['strategy']} | {r['return_pct']:.2f} | "
            f"{r['max_drawdown_pct']:.2f} | {r['buy_and_hold_return_pct']:.2f} | "
            f"{r['buy_and_hold_max_drawdown_pct']:.2f} | {Decimal(r['fees']):.2f} | "
            f"{r['buys']}/{r['sells']} | {r['grids_opened']} | {r['range_exits']} | "
            f"{r['time_with_inventory_pct']:.1f} | {r['max_order_requests_per_day']} | "
            f"{r['halted_at'] or 'no'} |"
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
    parser.add_argument("--maker-fee", help="override the spec fee for resting fills")
    parser.add_argument("--taker-fee", help="fee for marketable exits (default: maker)")
    args = parser.parse_args(argv)
    spec = load_spec(args.spec)
    maker = fee_rate(args.maker_fee, "maker fee") if args.maker_fee is not None else spec.fee_rate
    taker = fee_rate(args.taker_fee, "taker fee") if args.taker_fee is not None else None
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
        # Chronology is settled before any replay starts; invalid data never replays.
        cross_checks = [
            pool.submit(cross_check_job, args.spec, args.data_dir, symbol).result()
            for symbol in spec.traded
        ]
        failures = integrity_failures(cross_checks)
        if args.command == "verify" or failures:
            status = "invalid" if failures else "valid"
            print(
                json.dumps(
                    {"status": status, "failures": failures, "checks": cross_checks}, indent=1
                )
            )
            return 2 if failures else 0
        futures = [
            pool.submit(
                run_job, args.spec, args.config, args.data_dir, s, mode, gated, (maker, taker)
            )
            for s in spec.traded
            for mode in PATH_MODES
            for gated in (True, False)
        ]
        results = [f.result() for f in futures]
    failures = result_failures(results)
    stamp = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + f"-m{maker}-t{maker if taker is None else taker}"
    )
    out = args.out / spec.name / stamp
    out.mkdir(parents=True, exist_ok=True)
    document = {
        "dataset": spec.name,
        "purpose": spec.purpose,
        "feature_version": FEATURE_VERSION,
        "manifest_created_at": manifest["created_at"],
        **_identity(args.spec, args.config),
        "fees": {"maker": str(maker), "taker": str(taker if taker is not None else maker)},
        # Invalid results are kept for diagnosis but are never performance evidence.
        "valid": not failures,
        "failures": failures,
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
    if failures:
        print(json.dumps({"status": "invalid", "failures": failures}, indent=1))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
