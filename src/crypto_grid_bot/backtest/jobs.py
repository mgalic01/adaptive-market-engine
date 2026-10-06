"""Work the backtest CLI sends to its process pool.

These functions live here, not in ``__main__``, because a pool pickles them by module
and name. Under the spawn start method (the Windows and macOS default), a worker does
not re-run a package's ``__main__``, so functions defined there by
``python -m crypto_grid_bot.backtest`` cannot be found and every job failed with
``BrokenProcessPool``.
"""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from crypto_grid_bot import SOURCE_HASHES, source_hash
from crypto_grid_bot.backtest.dataset import (
    DatasetSpec,
    is_funding,
    load_manifest,
    load_spec,
    local_path,
)
from crypto_grid_bot.backtest.features import (
    FEATURE_VERSION,
    STRUCTURE_FEATURE_VERSION,
    FeatureEngine,
    SeriesFeatures,
)
from crypto_grid_bot.backtest.klines import (
    Kline,
    RepairedRead,
    month_bounds_ms,
    parse_rows_repaired,
    read_archive_repaired,
)
from crypto_grid_bot.backtest.masking import (
    MonthMask,
    apply_seventeen_percent,
    hourly_only_month_mask,
    masked_days,
    traded_month_mask,
)
from crypto_grid_bot.backtest.replay import (
    VOLUME_DRIFT_TOLERANCE,
    RunConfig,
    check_accounting,
    check_hourly_series,
    cross_check_daily,
    cross_check_hourly,
    load_daily,
    load_funding,
    load_hourly,
    load_minutes,
    replay,
    rules_for,
    summarise,
)
from crypto_grid_bot.config import BotConfig, load_config
from crypto_grid_bot.simulation.runner import MODE_SWITCH, VARIANTS, SimulationPolicy


def source_files() -> dict[str, str]:
    """This package's Python sources by path from the package root, each with the hash
    of the source this process compiled (``SOURCE_HASHES``) or, for a file it never
    imported, of the file on disk now."""
    root = Path(__file__).resolve().parents[1]
    files = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        module = ".".join((root.name, *relative.with_suffix("").parts))
        source = SOURCE_HASHES.get(module.removesuffix(".__init__"))
        files[relative.as_posix()] = source or source_hash(path.read_bytes())
    return files


def source_identity(files: dict[str, str] | None = None) -> str:
    """SHA-256 of this package's sources (``source_files()``), by path."""
    digest = hashlib.sha256()
    for relative, source in (source_files() if files is None else files).items():
        digest.update(f"{relative}\0{source}\0".encode())
    return digest.hexdigest()


def check_sources(expected: str) -> None:
    """A pool worker's initializer: refuse to run unless the sources this worker imported
    are the CLI's (Codex review of #160). A spawned worker imports the code from disk
    when it starts, so a checkout that changed, even one that changed back, while the
    workers started would otherwise run other code under the recorded commit. The
    identity compared is the one taken as this module was imported, from the sources
    the worker compiled, never a fresh read of the disk, which could already be back
    to the expected sources."""
    if expected != SOURCE_IDENTITY:
        raise RuntimeError("a pool worker's sources differ from the backtest CLI's")


# Spec v1 section 3 B: committed exposure at most 40% of prospective active equity.
VARIANT_B_INVENTORY_CAP = Decimal("0.40")


def manifest_path(spec_path: Path) -> Path:
    return spec_path.with_name(spec_path.stem + ".manifest.json")


# One mask per symbol (``SymbolMask.mask``); None loads with today's strict reader.
Masks = Mapping[str, frozenset[int] | None]


def exclusion_ranges(spec: DatasetSpec, symbol: str) -> list[tuple[int, int]]:
    """The symbol's documented absences (``[[basket_exclusions]]``) as [start, end) ms."""
    return [(e.start_ms, e.end_ms) for e in spec.basket_exclusions if e.symbol == symbol]


def evaluation_bounds_ms(spec: DatasetSpec) -> tuple[int, int]:
    """The evaluation months, ``start`` to ``end``, as [start, end) ms."""
    return month_bounds_ms(spec.start)[0], month_bounds_ms(spec.end)[1]


def hourly_window(spec: DatasetSpec) -> tuple[int, int]:
    """The hourly warm-up and the evaluation months as [start, end) ms: the span the hourly
    series checks and the daily/hourly check compare (``cross_check_job``)."""
    return month_bounds_ms(spec.warmup_start)[0], evaluation_bounds_ms(spec)[1]


def skipped_days_for_masks(spec: DatasetSpec, masked: frozenset[int]) -> int:
    """How many days the pair's daily/hourly check skips for its ``masked`` hours (spec v1
    §5 rule 3): the days holding a masked hour inside ``hourly_window``, exactly as
    ``cross_check_job`` counts them in ``daily_days_skipped_for_masks``. Zero without daily
    history (no ``daily_warmup_start``), since there is then no daily check."""
    if not spec.daily_warmup_start:
        return 0
    start, end = hourly_window(spec)
    return sum(1 for day in masked_days(masked) if start <= day < end)


def variant_policy(variant: str | None, *, structure: bool = False) -> SimulationPolicy | None:
    """The policy of spec v1 variant ``variant`` (a name in ``VARIANTS``, such as "A" or
    "C+G"; None is V0), with the V2 structure features when ``structure``; the full
    stack, "C+F+G+H", is declared only with them. None when nothing differs from V0, so
    a V0 run takes exactly the path it always has."""
    if variant is not None and variant not in VARIANTS[1:]:
        raise ValueError(f"unknown variant {variant!r}")
    if variant == MODE_SWITCH:
        # Registered, but not yet a job: refused, never run as V0 under its name.
        raise ValueError("variant MS (spec v2's mode switcher) has no backtest job yet")
    if variant is None and not structure:
        return None
    parts = set((variant or "").split("+"))
    return SimulationPolicy(
        trend_switch=bool(parts & {"A", "C"}),
        inventory_cap=VARIANT_B_INVENTORY_CAP if parts & {"B", "C"} else None,
        volume_exit="E" in parts,
        flow_block_entry="F" in parts,
        funding_gate="G" in parts,
        cycle_gate="H" in parts,
        structure=structure,
    )


def variant_name(policy: SimulationPolicy | None) -> str | None:
    """The spec v1 variant a policy runs, for the result rows; None for V0."""
    if policy is None or not policy.variant:
        return None
    name, cap = policy.variant, policy.inventory_cap
    if cap is not None and cap != VARIANT_B_INVENTORY_CAP:
        name += f" (inventory cap {cap}, not the spec's {VARIANT_B_INVENTORY_CAP})"
    return name


@dataclass(frozen=True)
class PreparedRun:
    spec: DatasetSpec
    config: BotConfig
    manifest: dict[str, Any]
    run: RunConfig
    features: FeatureEngine
    # The pair's daily bars when the spec has daily history (P3), else None: read by
    # the structure features, variant A's trend switch, variant H and variant D.
    daily: list[Kline] | None
    # The pair's hourly bars, which also feed ``features``: read by variant E.
    hourly: list[Kline]


def prepare_run(
    spec_path: Path,
    config_path: Path,
    data_dir: Path,
    symbol: str,
    path_mode: str,
    gated: bool,
    fees: tuple[Decimal, Decimal | None] | None = None,
    *,
    basket: bool = True,
    structure: bool = False,
    fill_trigger: Decimal | None = None,
    masks: Masks | None = None,
) -> PreparedRun:
    """The dataset, rules and features of one run, shared by the grid and variant-D jobs
    so that D's warm-up gate is built exactly as V0's.

    ``fees`` is (maker, taker) overriding the spec; taker None means maker. Without
    ``basket`` the breadth series are not loaded: they change feature values, never
    whether a minute is warmed up (``FeatureEngine.warmed``). ``structure`` gives the
    features the candles of the V2 structure features (SimulationPolicy.structure);
    without them the features are V0's. ``fill_trigger`` overrides how far a quote must
    cross a resting limit, for the labelled missed-fill sweep only (D9); None keeps it
    at the spec's slippage, which exits and marks always pay.

    ``masks`` maps a symbol to its mask (``mask_job``). Each symbol's mask applies to its
    hourly bars: the pair's, the market proxy's and every basket member's, so the features
    and ``hourly`` are post-mask. A symbol mapped to None, or absent, loads with today's
    strict reader; a set, even an empty one, loads with the repairing reader and drops its
    masked hours and documented absences (``replay.load_candles``). Daily bars are never
    masked.
    """
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
        fill_trigger,
    )
    spread = spec.assumed_spread_pct / 100
    chosen = masks or {}

    def hourly_of(s: str) -> list[Kline]:
        return load_hourly(
            data_dir, manifest, s, mask=chosen.get(s), excluded=exclusion_ranges(spec, s)
        )

    pair_hourly = hourly_of(symbol)
    pair = SeriesFeatures(symbol, pair_hourly)
    market = (
        pair
        if spec.market_proxy == symbol
        else SeriesFeatures(spec.market_proxy, hourly_of(spec.market_proxy))
    )
    breadth = [
        SeriesFeatures(s, hourly_of(s), full=False) for s in (spec.breadth_basket if basket else ())
    ]
    # Daily bars are loaded only when the spec declares a daily_warmup_start.
    pair_daily = (
        load_daily(data_dir, manifest, symbol)
        if spec.daily_warmup_start and symbol in {*spec.traded, spec.market_proxy}
        else None
    )
    features = FeatureEngine(
        pair,
        market,
        breadth,
        range_atr_multiple=config.range_atr_multiple,
        levels=config.maximum_levels,
        minimum_cost_multiple=config.minimum_grid_cost_multiple,
        # A grid cycle is two resting fills, so it pays the maker fee twice.
        round_trip_cost=float(2 * (maker + spec.slippage_rate) + spread),
        hourly_candles=pair_hourly if structure else None,
        daily_bars=pair_daily if structure else None,
    )
    run = RunConfig(symbol, path_mode, gated, rules, spec.initial_quote, spread)
    return PreparedRun(spec, config, manifest, run, features, pair_daily, pair_hourly)


def run_job(
    spec_path: Path,
    config_path: Path,
    data_dir: Path,
    symbol: str,
    path_mode: str,
    gated: bool,
    fees: tuple[Decimal, Decimal | None] | None = None,
    policy: SimulationPolicy | None = None,
    *,
    fill_trigger: Decimal | None = None,
    masks: Masks | None = None,
) -> dict[str, Any]:
    """``fees`` is (maker, taker) overriding the spec; taker None means maker.

    ``policy`` controls simulation variants; None gives V0 behaviour. Variants A and H
    require the pair's daily bars, and variant G BTCUSDT's funding archives in the
    manifest for every evaluation month from 2020-01, where they begin. A variant's rows
    name it, and rows with the V2 structure features carry their feature version.
    ``fill_trigger`` is the missed-fill sweep's resting-fill trigger (D9, see
    ``prepare_run``); the rows' ``rules`` then record it. ``masks`` is every symbol's
    mask (see ``prepare_run``); the pair's also drops the minutes of its masked hours and
    documented absences before the replay. None, or a pair it does not name, reads the
    minutes exactly as today. The pair's own mask, and no other symbol's, is reported in
    its row (spec v1 §5 rule 1): ``masked_hours``, ``days_skipped_for_masks`` and
    ``fills_after_masked_span``, each only when non-zero (``replay.mask_report``).
    """
    structure = policy is not None and policy.structure
    prepared = prepare_run(
        spec_path,
        config_path,
        data_dir,
        symbol,
        path_mode,
        gated,
        fees,
        structure=structure,
        fill_trigger=fill_trigger,
        masks=masks,
    )
    spec, run = prepared.spec, prepared.run
    mask = (masks or {}).get(symbol)
    minutes = load_minutes(
        data_dir,
        prepared.manifest,
        symbol,
        mask=mask,
        excluded=exclusion_ranges(spec, symbol),
    )
    # Spec v1 §3 G: BTCUSDT's funding gates every pair. A manifest without its funding
    # archive for an evaluation month from 2020-01 on refuses a G run (load_funding).
    funding = (
        load_funding(data_dir, prepared.manifest, "BTCUSDT", spec.months(spec.start))
        if policy is not None and policy.funding_gate
        else None
    )
    masked = mask or frozenset()
    metrics, account = replay(
        prepared.config,
        run,
        minutes,
        prepared.features,
        policy=policy,
        daily=prepared.daily,
        hourly=prepared.hourly,
        funding=funding,
        window=evaluation_bounds_ms(spec),
        masked=masked,
        days_skipped_for_masks=skipped_days_for_masks(spec, masked),
    )
    version = STRUCTURE_FEATURE_VERSION if structure else FEATURE_VERSION
    problems = check_accounting(run, metrics, account)
    row = summarise(run, metrics, account, problems, feature_version=version)
    name = variant_name(policy)
    if name is not None:  # Absent for V0, so V0 rows keep their exact layout.
        row["variant"] = name
    return row


def cross_check_job(
    spec_path: Path,
    data_dir: Path,
    symbol: str,
    strict_volume: bool = False,
    *,
    mask: frozenset[int] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    """The symbol's pre-run checks, as one record, which the CLI writes whole.

    ``mask`` is the symbol's ``SymbolMask.mask``. With a mask, the bars load with the
    repairing reader less the masked hours and documented absences, and every check runs
    on the post-mask expected set (spec v1 §5): the masked hours leave it, and the daily
    check skips each day that holds one and counts it. The record then gains only
    ``daily_days_skipped_for_masks``, when non-zero; no mask enters it. With None, the
    record is today's. ``config_path`` is reserved for the tick-limit test (spec v1 §5
    rule 8) and is not read yet.
    """
    tolerance = Decimal(0) if strict_volume else VOLUME_DRIFT_TOLERANCE
    spec, manifest = load_spec(spec_path), load_manifest(manifest_path(spec_path))
    # Only an untraded basket symbol may have documented absences; the proxy and the
    # traded pairs must be complete (load_spec refuses an exclusion naming one of them).
    excluded = exclusion_ranges(spec, symbol)
    masked = mask or frozenset()
    hourly = load_hourly(data_dir, manifest, symbol, mask=mask, excluded=excluded)
    window = evaluation_bounds_ms(spec)
    if symbol in spec.traded:
        minutes = load_minutes(data_dir, manifest, symbol, mask=mask, excluded=excluded)
        result = {
            "symbol": symbol,
            **cross_check_hourly(minutes, hourly, window, tolerance, masked=masked),
        }
    else:
        # No minute data: check the hours over warm-up and evaluation.
        proxy = symbol == spec.market_proxy
        result = {
            "symbol": symbol,
            "role": "market_proxy" if proxy else "breadth_basket",
            **check_hourly_series(hourly, hourly_window(spec), excluded, masked=masked),
        }
    if spec.daily_warmup_start and symbol in {*spec.traded, spec.market_proxy}:
        daily = load_daily(data_dir, manifest, symbol)
        result |= cross_check_daily(
            daily,
            hourly,
            (month_bounds_ms(spec.daily_warmup_start)[0], window[1]),
            hourly_window(spec),
            window[0],
            tolerance,
            masked_days=masked_days(masked),
        )
    return result


@dataclass(frozen=True)
class SymbolMask:
    """One symbol's mask (spec v1 §5 rules 1, 2 and 5, and the 17% rule).

    ``mask`` is None when every 1m and 1h archive of the symbol in the window reads with
    nothing repaired, dropped or untrusted and no hour is masked: the symbol then loads
    with today's strict reader. Otherwise it is every masked hour, possibly none, and the
    symbol loads with the repairing reader. ``months`` is the per-month table, for the
    comparison mask and ``mask-report``.
    """

    symbol: str
    mask: frozenset[int] | None
    months: tuple[MonthMask, ...]


def _untouched(read: RepairedRead) -> bool:
    """Whether the repairing reader repaired, dropped and distrusted nothing, so that the
    strict reader gives the same bars and statistics. Every dropped row puts its hour in
    ``masked_hours``, so an empty ``masked_hours`` means that no row was dropped."""
    return not (read.repaired or read.masked_hours or read.unreadable)


def mask_job(spec_path: Path, data_dir: Path, symbol: str) -> SymbolMask:
    """The symbol's mask over the window, read month by month with the repairing reader.

    A traded pair's evaluation months are masked from both archives (rules 1 and 2), and
    its hourly warm-up months from the 1h archive alone, as every month of an untraded
    proxy or basket symbol is (rules 1 and 5). Each month uses the symbol's own documented
    absences, and then the 17% rule. A month the manifest does not list as ok gives no
    read: no bars, so its expected hours are masked. Only one month's bars are held at a
    time.
    """
    spec, manifest = load_spec(spec_path), load_manifest(manifest_path(spec_path))
    exclusions = [e for e in spec.basket_exclusions if e.symbol == symbol]
    listed = {
        (entry["interval"], entry["month"])
        for entry in manifest["files"]
        if not is_funding(entry) and entry["symbol"] == symbol and entry["status"] == "ok"
    }
    evaluation = set(spec.months(spec.start)) if symbol in spec.traded else set()
    untouched = True
    months = []

    def read(interval: str, month: str) -> RepairedRead:
        nonlocal untouched
        if (interval, month) not in listed:
            return parse_rows_repaired("", interval, month)  # no read: no bars
        result = read_archive_repaired(
            local_path(data_dir, symbol, interval, month), symbol, interval, month
        )
        untouched = untouched and _untouched(result)
        return result

    for month in spec.months():
        hourly = read("1h", month)
        if month in evaluation:
            month_mask = traded_month_mask(read("1m", month), hourly, month, exclusions)
        else:
            month_mask = hourly_only_month_mask(hourly, month, exclusions)
        month_mask = apply_seventeen_percent(month_mask)
        untouched = untouched and not month_mask.masked
        months.append(month_mask)
    masked = frozenset().union(*(m.masked for m in months))
    return SymbolMask(symbol, None if untouched else masked, tuple(months))


# Every job module is loaded before the sources are hashed, so the identity covers all
# the code a worker can run; trend_benchmark imports prepare_run from here, so it is
# loaded last. Each one is hashed as compiled (crypto_grid_bot.SOURCE_HASHES), so a
# checkout that changes, even one that changes back, while a spawned worker loads its
# code gives that worker another identity (Codex review of #160).
importlib.import_module("crypto_grid_bot.backtest.trend_benchmark")
SOURCE_FILES = source_files()
SOURCE_IDENTITY = source_identity(SOURCE_FILES)
