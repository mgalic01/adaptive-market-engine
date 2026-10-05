"""Historical replay commands: fetch, verify and run. Offline except ``fetch``.

    python -m crypto_grid_bot.backtest fetch  --spec config/datasets/verify-2024h1.toml
    python -m crypto_grid_bot.backtest verify --spec config/datasets/verify-2024h1.toml
    python -m crypto_grid_bot.backtest run    --spec config/datasets/verify-2024h1.toml \\
        --config config/default.toml
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from crypto_grid_bot import source_hash
from crypto_grid_bot.backtest.dataset import (
    DatasetSpec,
    fee_rate,
    fetch_dataset,
    load_manifest,
    load_spec,
    sha256_file,
    verify_dataset,
    write_manifest,
)
from crypto_grid_bot.backtest.features import FEATURE_VERSION, STRUCTURE_FEATURE_VERSION
from crypto_grid_bot.backtest.jobs import (
    SOURCE_FILES,
    SOURCE_IDENTITY,
    check_sources,
    cross_check_job,
    manifest_path,
    run_job,
    variant_policy,
)
from crypto_grid_bot.backtest.replay import (
    ENGINE_VERSION,
    INTEGRITY_RULES,
    PATH_MODES,
    STRICT_INTEGRITY_RULES,
    VOLUME_DRIFT_TOLERANCE,
)
from crypto_grid_bot.backtest.trend_benchmark import trend_job


def checked_symbols(spec: DatasetSpec) -> list[str]:
    """Every symbol whose data reaches a decision: traded pairs, the market proxy (its
    hourly bars feed every pair's regime signals) and the breadth basket (its votes gate
    eligibility). Each is checked once."""
    return list(dict.fromkeys([*spec.traded, spec.market_proxy, *spec.breadth_basket]))


# Any non-zero value means the minute data cannot be trusted for this window.
INTEGRITY_FIELDS = (
    "hours_mismatched",
    "hours_missing",
    "hours_absent_from_minutes",
    "hours_absent_from_both",
    "hours_incomplete",
    "minutes_missing",
)


# Checks on an untraded market proxy or basket symbol (hourly data only).
SERIES_INTEGRITY_FIELDS = ("series_hours_missing", "series_hours_duplicated")


# Present only when the spec declares daily_warmup_start (spec v1 P3).
DAILY_INTEGRITY_FIELDS = (
    "daily_days_mismatched",
    "daily_days_missing",
    "daily_days_duplicated",
    "daily_days_hours_incomplete",
    "daily_warmup_short",
)


def integrity_failures(checks: list[dict[str, Any]]) -> list[str]:
    """Chronology/completeness failures. A basket symbol's listing or delisting gap is
    exempt only where the spec documents it in ``basket_exclusions``."""
    failures = []
    for check in checks:
        series = "role" in check
        fields = SERIES_INTEGRITY_FIELDS if series else INTEGRITY_FIELDS
        failures += [
            f"{check['symbol']}: {field}={check[field]}" for field in fields if check[field]
        ]
        # A basket symbol documented as absent for the whole window has no hours.
        wholly_excluded = (
            series and check["series_hours_excluded"] and not check["series_hours_missing"]
        )
        if not check["series_hours_present" if series else "hours_compared"] and not (
            wholly_excluded
        ):
            failures.append(f"{check['symbol']}: no hours compared")
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
        # A run that ends with an exit still owed (liquidation, range exit or drain)
        # and inventory the market would accept still unsold has not shown an exit
        # path, so its drawdown and return are not evidence. A remainder no exchange
        # would buy (dust) is reported, not failed.
        if r.get("final_exit_blocked") == "incomplete":
            failures.append(
                f"{name}: run ended with an exit still incomplete; "
                f"{r['final_unsellable_notional']} unsold"
            )
    return failures


def _identity(spec_path: Path, config_path: Path) -> dict[str, str]:
    return {
        "spec_sha256": sha256_file(spec_path),
        "manifest_sha256": sha256_file(manifest_path(spec_path)),
        "config_sha256": sha256_file(config_path),
    }


def committed_sources(commit: str) -> dict[str, str] | None:
    """This package's Python sources at ``commit``, hashed as jobs.source_files()
    hashes the ones this process imported, or None when git cannot read them."""
    git, root = shutil.which("git"), Path(__file__).resolve().parents[1]
    if git is None:
        return None
    try:
        listing = subprocess.run(  # nosec B603
            [git, "ls-tree", "-r", "-z", commit, "."],
            cwd=root,
            capture_output=True,
            timeout=10,
            check=False,
        )
        blobs: dict[str, str] = {}
        for entry in listing.stdout.decode().split("\0"):
            meta, _, path = entry.partition("\t")
            if path.endswith(".py") and meta.split()[1:2] == ["blob"]:
                blobs[path] = meta.split()[2]
        batch = subprocess.run(  # nosec B603
            [git, "cat-file", "--batch"],
            cwd=root,
            input="".join(f"{blob}\n" for blob in blobs.values()).encode(),
            capture_output=True,
            timeout=30,
            check=False,
        )
        if listing.returncode != 0 or batch.returncode != 0:
            return None
        sources, data, at = {}, batch.stdout, 0
        for path in blobs:  # `<id> blob <size>\n<content>\n`, in the order asked
            header = data.index(b"\n", at)
            size = int(data[at:header].split()[2])
            sources[path] = source_hash(data[header + 1 : header + 1 + size])
            at = header + size + 2
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None
    return sources


def code_commit() -> str:
    """The git commit of this code, with "+dirty" when tracked files differ from it or
    when its sources are not the ones this process imported, which a checkout moved
    since the imports would make them: the commit alone would not be the code that ran
    (Codex reviews of #160). "unknown" outside a git checkout."""
    git = shutil.which("git")
    if git is None:
        return "unknown"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603
            [git, *args],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    try:
        head = run("rev-parse", "HEAD")
        status = run("status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    commit = head.stdout.strip()
    if head.returncode != 0 or not commit or status.returncode != 0:
        return "unknown"
    clean = not status.stdout.strip() and committed_sources(commit) == SOURCE_FILES
    return commit + ("" if clean else "+dirty")


class InProcess:
    """A stand-in for ProcessPoolExecutor that runs each job when it is submitted, in
    this process (``--jobs 1``). It avoids starting a worker, which is slow under the
    spawn start method; the results are the same."""

    def __enter__(self) -> InProcess:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def submit(self, fn: Callable[..., Any], /, *args: Any) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_result(fn(*args))
        return future


def _table(results: list[dict[str, Any]]) -> str:
    lines = [
        "| Pair | Path | Strategy | Return % | Max DD % | Buy&hold % | B&H DD % | Fees | "
        "Buys/Sells | Grids | Range exits | Invested % | Max req/day | Halted |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| --- |",
    ]
    for r in results:
        # A variant's rows name it, so the table alone tells each variant from V0 (Codex
        # review of #160); a V0 row keeps its exact text.
        strategy = r["strategy"] + (f", variant {r['variant']}" if "variant" in r else "")
        lines.append(
            f"| {r['symbol']} | {r['path_mode']} | {strategy} | {r['return_pct']:.2f} | "
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
    parser.add_argument(
        "--fill-trigger",
        help="the missed-fill sensitivity sweep only (spec v1 §4, D9): how far a quote must "
        "cross a resting limit to fill (default: the spec's slippage, which exits still pay)",
    )
    parser.add_argument(
        "--strict-volume",
        action="store_true",
        help="fail on any volume difference (no drift tolerance)",
    )
    parser.add_argument(
        "--trend-benchmark",
        action="store_true",
        help="also run variant D, the trend benchmark (spec v1 §3 D; not a grid, "
        "no risk controls, cannot be selected)",
    )
    variants = parser.add_mutually_exclusive_group()
    variants.add_argument(
        "--variant-a",
        action="store_const",
        const="A",
        dest="variant",
        help="enable variant A: daily SMA50/SMA200 trend switch (spec v1 §3 A); "
        "requires daily_warmup_start in the spec",
    )
    variants.add_argument(
        "--variant-b",
        action="store_const",
        const="B",
        dest="variant",
        help="enable variant B: inventory cap at 40%% of prospective active equity (spec v1 §3 B)",
    )
    variants.add_argument(
        "--variant-c",
        action="store_const",
        const="C",
        dest="variant",
        help="enable variant C: A and B together (spec v1 §3 C); requires "
        "daily_warmup_start in the spec",
    )
    variants.add_argument(
        "--variant-e",
        action="store_const",
        const="E",
        dest="variant",
        help="enable variant E: volume-confirmed range exit (spec v1 §3 E); not eligible "
        "for selection until Codex has reviewed it",
    )
    variants.add_argument(
        "--variant-f",
        action="store_const",
        const="F",
        dest="variant",
        help="enable variant F: order-flow entry block (spec v1 §3 F)",
    )
    variants.add_argument(
        "--variant-g",
        action="store_const",
        const="G",
        dest="variant",
        help="enable variant G: BTCUSDT funding-rate gate (spec v1 §3 G); refuses to run "
        "unless the manifest lists BTCUSDT's funding archive for every evaluation month (P8)",
    )
    variants.add_argument(
        "--variant-h",
        action="store_const",
        const="H",
        dest="variant",
        help="enable variant H: Bitcoin cycle context (spec v1 §3 H); requires "
        "daily_warmup_start in the spec",
    )
    variants.add_argument(
        "--variant-cg",
        action="store_const",
        const="C+G",
        dest="variant",
        help="enable C+G: variant C with the funding-rate gate (spec v1 §3 G), a declared "
        "interaction; requires daily_warmup_start in the spec and G's funding archives",
    )
    variants.add_argument(
        "--variant-ch",
        action="store_const",
        const="C+H",
        dest="variant",
        help="enable C+H: variant C with the cycle context (spec v1 §3 H), a declared "
        "interaction; requires daily_warmup_start in the spec",
    )
    parser.add_argument(
        "--structure",
        action="store_true",
        help="enable the V2 market-structure features (structure alignment vote and sell "
        "targets below resistance; off in V0). Results are labelled " + STRUCTURE_FEATURE_VERSION,
    )
    parser.add_argument(
        "--record-commit",
        action="store_true",
        help="record the code's git commit in results.json (always recorded for a "
        "variant, --structure or --trend-benchmark run)",
    )
    args = parser.parse_args(argv)
    spec = load_spec(args.spec)
    maker = fee_rate(args.maker_fee, "maker fee") if args.maker_fee is not None else spec.fee_rate
    taker = fee_rate(args.taker_fee, "taker fee") if args.taker_fee is not None else None
    fill = fee_rate(args.fill_trigger, "fill trigger") if args.fill_trigger is not None else None
    if args.command == "fetch":
        # A re-fetch keeps the funding archives the manifest lists (spec v1 P8, variant G).
        path = manifest_path(args.spec)
        previous = load_manifest(path) if path.exists() else None
        manifest = fetch_dataset(spec, args.data_dir, previous=previous)
        write_manifest(path, manifest)
        missing = [f for f in manifest["files"] if f["status"] == "missing"]
        print(json.dumps({"files": len(manifest["files"]), "missing": missing}, indent=1))
        return 0
    policy = variant_policy(args.variant, structure=args.structure)
    # Taken before anything runs, dataset verification included: the code imported now is
    # the code that runs, even if the checkout changes during a long run (Codex review of
    # #160). Every run that is not plain V0 records it; V0 keeps its exact layout.
    recorded = policy is not None or args.trend_benchmark or args.record_commit or fill is not None
    commit = code_commit() if recorded else None
    manifest = load_manifest(manifest_path(args.spec))
    verify_dataset(spec, manifest, args.data_dir)
    integrity = {
        "version": STRICT_INTEGRITY_RULES if args.strict_volume else INTEGRITY_RULES,
        "volume_drift_tolerance": "0" if args.strict_volume else str(VOLUME_DRIFT_TOLERANCE),
    }
    jobs = max(1, min(args.jobs, 8))
    # Each pool worker refuses to start on other sources than this process imported
    # (jobs.check_sources); the run then fails before any result is written.
    executor = (
        InProcess()
        if jobs == 1
        else ProcessPoolExecutor(
            max_workers=jobs, initializer=check_sources, initargs=(SOURCE_IDENTITY,)
        )
    )
    with executor as pool:
        # Chronology is settled before any replay starts; invalid data never replays.
        # Submit every check before waiting on any, so they run in parallel.
        checks = [
            pool.submit(cross_check_job, args.spec, args.data_dir, symbol, args.strict_volume)
            for symbol in checked_symbols(spec)
        ]
        cross_checks = [check.result() for check in checks]
        failures = integrity_failures(cross_checks)
        if args.command == "verify" or failures:
            status = "invalid" if failures else "valid"
            print(
                json.dumps(
                    {
                        "status": status,
                        "integrity_rules": integrity,
                        "failures": failures,
                        "checks": cross_checks,
                    },
                    indent=1,
                )
            )
            return 2 if failures else 0
        # A sensitivity run's fill trigger reaches every grid replay (D9). Without the flag
        # each job is submitted exactly as before. D places no resting order, so the
        # trigger cannot change it.
        grid_job = run_job if fill is None else partial(run_job, fill_trigger=fill)
        futures = [
            pool.submit(
                grid_job,
                args.spec,
                args.config,
                args.data_dir,
                s,
                mode,
                gated,
                (maker, taker),
                # The ungated rows are always the spec's ungated V0 baseline, which C6
                # compares a variant with, never the variant without its gate (Codex
                # review of #160).
                policy if gated else None,
            )
            for s in spec.traded
            for mode in PATH_MODES
            for gated in (True, False)
        ]
        if args.trend_benchmark:
            futures += [
                pool.submit(
                    trend_job, args.spec, args.config, args.data_dir, s, mode, (maker, taker)
                )
                for s in spec.traded
                for mode in PATH_MODES
            ]
        results = [f.result() for f in futures]
    failures = result_failures(results)
    if commit is not None and (after := code_commit()) != commit:
        # Spawned workers import the code from disk when they start, so after a change of
        # checkout during the run the recorded commit may not be the code that ran (Codex
        # review of #160). Such a run is kept for diagnosis but is not evidence.
        failures.append(f"the checkout changed during the run: {commit} -> {after}")
    # A variant or structure run says so in its directory name; V0's keeps its form.
    stamp = (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        + f"-m{maker}-t{maker if taker is None else taker}"
        + (f"-fill{fill}" if fill is not None else "")
        + (f"-variant-{args.variant}" if args.variant else "")
        + ("-structure" if args.structure else "")
    )
    out = args.out / spec.name / stamp
    out.mkdir(parents=True, exist_ok=True)
    document = {
        "dataset": spec.name,
        "purpose": spec.purpose,
        "feature_version": STRUCTURE_FEATURE_VERSION if args.structure else FEATURE_VERSION,
        # A structure run's ungated rows are the V0 baseline, with V0's features; each row
        # carries its own version (Codex review of #160).
        **({"baseline_feature_version": FEATURE_VERSION} if args.structure else {}),
        "engine_version": ENGINE_VERSION,
        "manifest_created_at": manifest["created_at"],
        **_identity(args.spec, args.config),
        "integrity_rules": integrity,
        "fees": {"maker": str(maker), "taker": str(taker if taker is not None else maker)},
        # Present only in a missed-fill sensitivity run (D9), so every other results.json
        # keeps its exact layout.
        **({"fill_trigger": str(fill)} if fill is not None else {}),
        # Present only when D ran, so a grid-only results.json keeps its exact layout.
        **({"trend_benchmark": "D (spec v1 §3 D)"} if args.trend_benchmark else {}),
        # Present only for a variant or structure run (or --record-commit), so a V0
        # results.json keeps its exact layout.
        **({"policy": policy.identity()} if policy is not None else {}),
        **({"code_commit": commit} if commit is not None else {}),
        # The sources that ran, which the commit alone cannot vouch for (Codex review of
        # #160); recorded with the commit, so a V0 results.json keeps its exact layout.
        **({"code_sha256": SOURCE_IDENTITY} if commit is not None else {}),
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
