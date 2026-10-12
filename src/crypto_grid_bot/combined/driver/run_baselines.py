"""The V3.1 baseline cells, each run once: the matched spot hold, the frozen V3 arms and
the frozen minute baselines (V0, the V1 variants, V2 and comparator D).

``run_hold_cell`` replays the hold adapter on the cell's window pack. The frozen V3 arms
read the V3 input pack (``driver.v3_pack``, Rulings P9 and P15): ``compute_v3_picks``
trains V3's unchanged selector once, and ``run_v3_cell`` replays one V3 arm on a registered
window, the selector from those shared picks. ``run_minute_cell`` replays one minute arm on
the frozen pairs from the verified legacy dataset (Ruling P14), with the jobs the frozen
``backtest.jobs`` helpers build. Every job follows ``run_cell``'s protocol (Ruling P13),
with its helpers: cheap checks first, then the claim (the directory, created once, and
``attempt.json``), then the work under a fresh default decimal context, then the files,
each an exclusive create, the completion marker last; an exception after the claim leaves
``failure.json`` and propagates::

    <out_dir>/<cell_id>/attempt.json            the claim: cell id, attempt id, repo head,
                                                code and config pins, the pack's SHA-256
                                                (a V3 cell's is the V3 input pack's, a
                                                minute cell's the legacy dataset
                                                manifest's) and the data pin
    <out_dir>/<cell_id>/native_evidence.json    the cell's metadata (run_cell's fields)
                                                and the adapter's own evidence; a minute
                                                cell's also its ``minute_inputs``
    <out_dir>/<cell_id>/report.json             encode_report
    <out_dir>/<cell_id>/outcome.json            encode_outcome, last: the completion marker

    <out_dir>/v3_picks/attempt.json             the claim, with ``job`` for ``cell_id``
    <out_dir>/v3_picks/attempts.jsonl           V3's own attempt records, streamed
    <out_dir>/v3_picks/v3_picks.json            the picks, bound to the claim and the log
    <out_dir>/v3_picks/outcome.json             the SHA-256 of the three files above, last:
                                                the completion marker

A baseline adapter returns ``BaselineEvidence``, which holds no funnel journal
(``Evidence``), so a baseline cell has no ``write_bundle`` bundle. ``native_evidence.json``
holds what the adapter records besides its report: the native marks in its own timing
(``[timestamp_ms, kind, equity, spot_value, futures_collateral]``), its stop status,
liquidations, accounting residual and checks, and its disclosures. A minute cell adds the
inputs it ran on (``_minute_inputs``): the SHA-256 of the dataset spec, the bot config and
the legacy manifest, its frozen version, and per pair the path mode, gate, costs, minute
count and masked hours inside the window. Nothing here touches the network.
"""

import contextlib
import hashlib
import os
import re
import shutil
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO

from crypto_grid_bot.backtest.dataset import DatasetSpec, is_funding, load_manifest, load_spec
from crypto_grid_bot.backtest.jobs import (
    Masks,
    PreparedRun,
    evaluation_bounds_ms,
    exclusion_ranges,
    manifest_path,
    mask_job,
    prepare_run,
    skipped_days_for_masks,
    variant_policy,
)
from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.backtest.replay import PATH_MODES, load_funding, load_minutes
from crypto_grid_bot.combined.artifacts import _canonical, _safe_path, _write
from crypto_grid_bot.combined.baseline_hold import HoldMarket, replay_hold_baseline
from crypto_grid_bot.combined.baseline_minute import (
    MinuteJob,
    TrendJob,
    replay_grid_baseline,
    replay_trend_baseline,
)
from crypto_grid_bot.combined.baseline_records import BaselineEvidence, refuse_sealed
from crypto_grid_bot.combined.baseline_v3 import (
    SELECTOR,
    V3Inputs,
    replay_v3_baseline,
    selector_picks,
    window_picks,
)
from crypto_grid_bot.combined.driver.packs import WindowPack
from crypto_grid_bot.combined.driver.registration import (
    Cell,
    CellKind,
    DriverRegistration,
    _strict_json,
)
from crypto_grid_bot.combined.driver.run_cell import (
    _attempt,
    _capital,
    _check_attempt,
    _claimed,
    _identity,
    _metadata,
    _pack_errors,
    _registered,
)
from crypto_grid_bot.combined.driver.serialize import encode_outcome, encode_report
from crypto_grid_bot.combined.driver.venues import cost_profile
from crypto_grid_bot.combined.experiment import Capital, Window, capital_label
from crypto_grid_bot.combined.outcomes import baseline_outcome
from crypto_grid_bot.simulation.runner import MODE_SWITCH
from crypto_grid_bot.strategy.daily_sma import DailyCloses
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import ReplayResult
from crypto_grid_bot.trend.walk_forward import RULES

V3_PICKS = "v3_picks"  # the picks job's directory under out_dir
PICKS_FILE = "v3_picks.json"
ATTEMPT_FILE = "attempt.json"  # the claim, as ``run_cell._claimed`` writes it
ATTEMPTS_FILE = "attempts.jsonl"
OUTCOME_FILE = "outcome.json"
NATIVE_EVIDENCE_FILE = "native_evidence.json"
BASELINE_SCHEMA = "v3.1-baseline-1"
PICKS_SCHEMA = "v3.1-v3-picks-2"
PICKS_OUTCOME_SCHEMA = "v3.1-v3-picks-outcome-1"
MAX_PICKS_BYTES = 1024 * 1024

# The frozen minute baselines' dataset spec and bot config as the frozen V1 and V2 runs
# used them (spec v1 section 4; the backtest workflow's ``--spec`` and its default
# ``--config``), by repository path. The run-manifest pins the dataset's manifest under
# MINUTE_MANIFEST_PATH.
MINUTE_SPEC_PATH = "config/datasets/full-range-2017-2024.toml"
MINUTE_MANIFEST_PATH = "config/datasets/full-range-2017-2024.manifest.json"
MINUTE_CONFIG_PATH = "config/default.toml"
MINUTE_PAIRS = ("BTCUSDT", "ETHUSDT", "XRPUSDT")  # the frozen traded pairs (proposal §2)
FUNDING_SYMBOL = "BTCUSDT"  # spec v1 §3 G: BTCUSDT's funding gates every pair, as run_job
# The pinned V1 variants (registration.V1_VARIANTS) by their frozen names (runner.VARIANTS).
_V1_NAMES = {
    "a": "A",
    "b": "B",
    "c": "C",
    "e": "E",
    "f": "F",
    "g": "G",
    "cg": "C+G",
    "h": "H",
    "ch": "C+H",
}
_SLIPPAGE_LINE = re.compile(r'^slippage_rate = "[^"\n]*"$', re.MULTILINE)

_RESERVED = 1_735_689_600_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_STAMP = re.compile(r"0|[1-9][0-9]*")
_RUN_ID = re.compile(r"([0-9a-f]{32})-(.+)", re.DOTALL)
_PICKS_KEYS = frozenset(
    {
        "schema",
        "v3_pack_sha256",
        "run_manifest_sha256",
        "config_pin",
        "code_pin",
        "attempt_id",
        "repo_head",
        "attempt_json_sha256",
        "attempts_sha256",
        "picks",
    }
)


def run_hold_cell(
    cell: Cell,
    pack: WindowPack,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
) -> Path:
    """Replay the registered matched spot hold cell ``cell`` on ``pack`` once and return
    its artifact directory, ``out_dir/<cell_id>`` (layout in the module docstring).

    Each pack coin is one market: its spot hourly bars and spot rules at the base spot
    costs, ``cost_profile(1, "spot")``, because ``replay_hold_baseline`` itself scales the
    fee and slippage rates by ``cost_multiple``, which is the cell's. The capital, window,
    skipped hours (the pack's, equal to the registered window's) and adapter pin come from
    the registration. Refuses, before anything is written, a cell that is not a registered
    native hold cell, a pack of another window, an empty attempt id, a repo head that is
    not 40 lowercase hex and an existing cell directory.
    """
    window = _baseline_window(cell, reg, "hold", "a matched spot hold cell required")
    if errors := _pack_errors(pack, window):
        raise ValueError(f"cell {cell.cell_id}: " + "; ".join(errors))
    _check_attempt(attempt_id, repo_head)
    capital = _capital(reg, cell.capital_id)
    adapter_pin = dict(reg.registration.adapter_pins)[cell.arm]
    pack_pin = dict(reg.run_manifest.window_packs)[cell.window]
    attempt = _cell_attempt(cell, reg, window, attempt_id, repo_head, pack_pin)
    directory = Path(out_dir) / cell.cell_id
    with _claimed(directory, attempt):
        base = cost_profile(1, "spot")  # scaled by the adapter, never here as well
        markets = {
            coin.symbol: HoldMarket(coin.spot_hourly, coin.spot_rules, base) for coin in pack.coins
        }
        evidence = replay_hold_baseline(
            markets,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            initial=capital.initial_equity,
            cost_multiple=cell.cost_multiple,
            source_refs=(f"v31-pack:{pack_pin}", f"v31-run-manifest:{reg.run_manifest_pin}"),
            adapter_pin=adapter_pin,
            skipped_hours=pack.skipped_hours,
            capital_label=capital_label(capital),
        )
        _write_cell(
            directory, attempt, cell, reg, window, capital, adapter_pin, evidence, attempt_id
        )
    return directory


def compute_v3_picks(
    v3_inputs: V3Inputs,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
) -> Path:
    """Train V3's unchanged selector once and return the path of its picks,
    ``out_dir/v3_picks/v3_picks.json``, which every V3 cell then reads.

    ``selector_picks`` runs V3's frozen walk-forward at research capital (10,000 USDT)
    and base cost, holding the capital adapter's lock. Each attempt V3 records is written
    at once as one canonical line of ``attempts.jsonl`` (``_AttemptLog``), so a failed
    walk-forward keeps every attempt it made. ``v3_picks.json`` is canonical JSON that
    binds the picks to this job: the schema, the V3 input pack's and the run-manifest's
    SHA-256, the registration's config and code pins, this job's attempt id and repo head,
    the SHA-256 of its ``attempt.json`` (the claim) and of ``attempts.jsonl``, and
    ``picks``, each pick time in ms as a decimal string mapped to its rule, or null for a
    flat quarter. ``outcome.json`` follows it, last: the schema, the job, the attempt id and
    the SHA-256 of the claim, the log and ``v3_picks.json``. A job that did not finish has
    no marker, and a picks file cannot be swapped for another afterwards.

    ``v3_inputs`` must be ``read_v3_pack(path, reg.run_manifest.v3_pack)``: the V3 input
    pack read against the run-manifest's ``v3_pack_sha256``. Refuses, before anything is
    written, other inputs, an empty attempt id, a repo head that is not 40 lowercase hex
    and an existing picks directory.
    """
    if not isinstance(v3_inputs, V3Inputs):
        raise ValueError("V3 inputs (read_v3_pack) required")
    if not isinstance(reg, DriverRegistration):
        raise ValueError("a DriverRegistration required")
    _check_attempt(attempt_id, repo_head)
    pin = reg.run_manifest.v3_pack
    attempt: dict[str, object] = {
        "job": V3_PICKS,
        **_attempt(
            reg,
            attempt_id=attempt_id,
            repo_head=repo_head,
            pack_sha256=pin,
            data_pin=reg.run_manifest_pin,
        ),
    }
    directory = Path(out_dir) / V3_PICKS
    with _claimed(directory, attempt):
        claim_sha256 = hashlib.sha256((directory / ATTEMPT_FILE).read_bytes()).hexdigest()
        with _AttemptLog(directory / ATTEMPTS_FILE) as log:
            picks, _ = selector_picks(v3_inputs, record=log)
        document = {
            "schema": PICKS_SCHEMA,
            "v3_pack_sha256": pin,
            "run_manifest_sha256": reg.run_manifest_pin,
            "config_pin": reg.registration.config_pin,
            "code_pin": reg.registration.code_pin,
            "attempt_id": attempt_id,
            "repo_head": repo_head,
            "attempt_json_sha256": claim_sha256,
            "attempts_sha256": log.sha256(),
            "picks": _picks_document(picks),
        }
        picks_raw = _canonical(document)
        _write(directory / PICKS_FILE, picks_raw)
        _write(directory / OUTCOME_FILE, _canonical(_picks_outcome(document, picks_raw)))  # last
    return directory / PICKS_FILE


def run_v3_cell(
    cell: Cell,
    v3_inputs: V3Inputs,
    picks_path: Path,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
) -> Path:
    """Replay the registered frozen V3 cell ``cell`` once and return its artifact
    directory, ``out_dir/<cell_id>`` (layout in the module docstring).

    ``v3_inputs`` must be ``read_v3_pack(path, reg.run_manifest.v3_pack)``: a V3 cell's
    data is the V3 input pack, read against the run-manifest's ``v3_pack_sha256``, never a
    window pack's pin. The execution gate checks the cell's window pack (W1), whose skipped
    hours are the registered window's that this cell's report uses. ``picks_path`` is
    ``compute_v3_picks``'s file. It must name the same V3 pack and run-manifest, and its
    picks job (the directory beside it) must be the registered one, finished and
    unchanged (``_read_picks``): a completion marker that pins the picks file, the retained
    ``attempts.jsonl`` and ``attempt.json`` hashing to the values the picks record, and the
    picks' and the claim's config pin, code pin, V3 pack and run-manifest equal to the
    registration's. The selector replays ``window_picks`` of those picks over the window;
    a fixed long-only rule takes no picks, as its adapter replays the rule itself. The
    capital's starting equity, the cell's cost multiple (V3's own native cost multiple),
    the window and the adapter pin come from the registration. Refuses, before anything is
    written, a cell that is not a registered native V3 cell, other inputs, an unreadable or
    untrusted picks file or job, an empty attempt id, a repo head that is not 40 lowercase
    hex and an existing cell directory.
    """
    window = _baseline_window(cell, reg, "v3", "a frozen V3 baseline cell required")
    if not isinstance(v3_inputs, V3Inputs):
        raise ValueError("V3 inputs (read_v3_pack) required")
    _check_attempt(attempt_id, repo_head)
    picks, picks_sha256 = _read_picks(picks_path, reg)
    capital = _capital(reg, cell.capital_id)
    adapter_pin = dict(reg.registration.adapter_pins)[cell.arm]
    pin = reg.run_manifest.v3_pack
    attempt = _cell_attempt(cell, reg, window, attempt_id, repo_head, pin)
    refs = (f"v3-pack:{pin}", f"v31-run-manifest:{reg.run_manifest_pin}")
    selector = cell.arm == SELECTOR
    directory = Path(out_dir) / cell.cell_id
    with _claimed(directory, attempt):
        evidence = replay_v3_baseline(
            cell.arm,
            v3_inputs,
            start_ms=window.start_ms,
            end_ms=window.end_ms,
            initial=capital.initial_equity,
            cost_multiple=cell.cost_multiple,
            source_refs=(*refs, f"v3-picks:{picks_sha256}") if selector else refs,
            adapter_pin=adapter_pin,
            picks=window_picks(picks, window.start_ms, window.end_ms) if selector else None,
            skipped_hours=window.skipped_hours,
            capital_label=capital_label(capital),
        )
        _write_cell(
            directory, attempt, cell, reg, window, capital, adapter_pin, evidence, attempt_id
        )
    return directory


@dataclass(frozen=True, slots=True)
class MinuteVersion:
    """How a minute arm replays: comparator D (``trend``), or a frozen grid whose
    ``variant`` is ``backtest.jobs.variant_policy``'s name (None for V0, ``MODE_SWITCH``
    for V2, spec v2's mode switcher), in the native path mode ``path_mode``."""

    arm: str
    trend: bool
    variant: str | None
    path_mode: str


def minute_version(arm: str) -> MinuteVersion:
    """The frozen version of a registered minute arm (``registration.minute_arms``):
    ``matched_v0_grid_<mode>``, ``matched_v1_<variant>_grid_<mode>`` for a pinned V1
    variant, ``matched_v2_grid_<mode>`` or ``matched_d_trend_<mode>``, where ``<mode>`` is
    one of ``backtest.replay.PATH_MODES``. Refuses any other arm."""
    if type(arm) is str:
        for mode in PATH_MODES:
            base = arm.removeprefix("matched_").removesuffix(f"_{mode}")
            if arm != f"matched_{base}_{mode}":
                continue
            if base == "v0_grid":
                return MinuteVersion(arm, False, None, mode)
            if base == "v2_grid":
                return MinuteVersion(arm, False, MODE_SWITCH, mode)
            if base == "d_trend":
                return MinuteVersion(arm, True, None, mode)
            variant = base.removeprefix("v1_").removesuffix("_grid")
            if base == f"v1_{variant}_grid" and variant in _V1_NAMES:
                return MinuteVersion(arm, False, _V1_NAMES[variant], mode)
    raise ValueError(f"arm {arm!r} is not a registered minute baseline arm")


def minute_masks(spec_path: Path, data_dir: Path) -> dict[str, frozenset[int] | None]:
    """Every symbol's frozen mask (spec v1 section 5) as the frozen backtest CLI builds
    them before any job: ``backtest.jobs.mask_job`` over the spec's whole window for each
    symbol whose data reaches a decision (the traded pairs, the market proxy and the
    breadth basket). A mask is None when the symbol reads clean, and then its archives load
    with the strict reader; a set, even an empty one, loads them with the repairing reader
    less those hours. A traded pair's masked hours lose their minutes, so the minute
    baselines have no opening quote at a masked hour inside the window: the registration
    must skip such an hour for every arm, or the comparison stays incomplete."""
    spec = load_spec(spec_path)
    symbols = dict.fromkeys([*spec.traded, spec.market_proxy, *spec.breadth_basket])
    return {symbol: mask_job(spec_path, data_dir, symbol).mask for symbol in symbols}


def run_minute_cell(
    cell: Cell,
    data_dir: Path,
    reg: DriverRegistration,
    out_dir: Path,
    *,
    attempt_id: str,
    repo_head: str,
    spec_path: Path,
    config_path: Path,
) -> Path:
    """Replay the registered frozen minute baseline cell ``cell`` once and return its
    artifact directory, ``out_dir/<cell_id>`` (layout in the module docstring).

    - ``data_dir``: the verified legacy dataset, laid out as ``backtest.dataset.local_path``
      reads it (``data_dir/binance/data/...``). The caller has verified every archive the
      manifest lists against its SHA-256 (``backtest.dataset.verify_dataset``).
    - ``spec_path``: the frozen dataset spec, ``MINUTE_SPEC_PATH`` in the checkout, with
      its manifest beside it (``backtest.jobs.manifest_path``); the manifest's SHA-256 must
      be the run-manifest's pin of ``MINUTE_MANIFEST_PATH``.
    - ``config_path``: the frozen bot config, ``MINUTE_CONFIG_PATH`` in the checkout.

    Each of the spec's pairs (``MINUTE_PAIRS``) is one job, built exactly as the frozen
    ``backtest.jobs.run_job`` (grids) and ``trend_benchmark.trend_job`` (D) build theirs:
    ``prepare_run`` in the arm's path mode, a grid gated with the version's
    ``variant_policy`` and the basket, D ungated without it; every symbol's frozen mask
    (``minute_masks``); BTCUSDT's funding for G; the pair's minutes, played only inside the
    registered window, which is also the replay's evaluation window. The cell's cost
    multiple picks the registered spot cost profile (``cost_profile``): at 1 the frozen
    spec's own rates (maker = taker 0.1%, slippage 0.05%); at 2 maker, taker and slippage
    doubled, with the fill trigger kept at base slippage so only the costs change, and the
    spread unchanged (``_cost_spec``). Capital, window, skipped hours and adapter pin come
    from the registration; the adapter splits the capital equally across the pairs.

    Refuses, before anything is written, a cell that is not a registered native minute
    cell, an empty attempt id, a repo head that is not 40 lowercase hex, a dataset that is
    not the pinned one (``_minute_dataset``) and an existing cell directory.
    """
    window = _baseline_window(cell, reg, "minute", "a minute baseline cell required")
    version = minute_version(cell.arm)
    _check_attempt(attempt_id, repo_head)
    spec_file, config_file, data = Path(spec_path), Path(config_path), Path(data_dir)
    spec, legacy_sha = _minute_dataset(spec_file, reg, window)
    capital = _capital(reg, cell.capital_id)
    adapter_pin = dict(reg.registration.adapter_pins)[cell.arm]
    attempt = _cell_attempt(cell, reg, window, attempt_id, repo_head, legacy_sha)
    refs = (f"legacy-manifest:{legacy_sha}", f"v31-run-manifest:{reg.run_manifest_pin}")
    bounds = (window.start_ms, window.end_ms)
    directory = Path(out_dir) / cell.cell_id
    with _claimed(directory, attempt):
        masks = minute_masks(spec_file, data)
        with _cost_spec(spec_file, cell.cost_multiple) as cost_spec:
            prepared = {
                pair: _prepared(version, cost_spec, config_file, data, pair, cell, masks)
                for pair in spec.traded
            }
        manifest = load_manifest(manifest_path(spec_file))
        minutes = {
            pair: _window_minutes(data, manifest, spec, pair, masks.get(pair), bounds)
            for pair in spec.traded
        }
        label = capital_label(capital)
        jobs: Mapping[str, MinuteJob | TrendJob]
        if version.trend:
            trend_jobs = {
                pair: _trend_job(setup, minutes[pair], spec, masks.get(pair), bounds)
                for pair, setup in prepared.items()
            }
            jobs = trend_jobs
            evidence = replay_trend_baseline(
                cell.arm,
                trend_jobs,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
                initial=capital.initial_equity,
                source_refs=refs,
                adapter_pin=adapter_pin,
                skipped_hours=window.skipped_hours,
                capital_label=label,
            )
        else:
            grid_jobs = {
                pair: _grid_job(
                    version, setup, minutes[pair], spec, manifest, data, masks.get(pair), bounds
                )
                for pair, setup in prepared.items()
            }
            jobs = grid_jobs
            evidence = replay_grid_baseline(
                cell.arm,
                grid_jobs,
                start_ms=window.start_ms,
                end_ms=window.end_ms,
                initial=capital.initial_equity,
                source_refs=refs,
                adapter_pin=adapter_pin,
                skipped_hours=window.skipped_hours,
                capital_label=label,
            )
        inputs = _minute_inputs(version, spec_file, config_file, legacy_sha, jobs, bounds)
        _write_cell(
            directory,
            attempt,
            cell,
            reg,
            window,
            capital,
            adapter_pin,
            evidence,
            attempt_id,
            extra={"minute_inputs": inputs},
        )
    return directory


def _minute_dataset(
    spec_path: Path, reg: DriverRegistration, window: Window
) -> tuple[DatasetSpec, str]:
    """The frozen dataset spec at ``spec_path`` and its manifest's SHA-256, once both are
    the registered minute baselines' dataset; otherwise one ``ValueError`` naming each
    difference.

    The manifest beside the spec must hash to the run-manifest's pin of
    ``MINUTE_MANIFEST_PATH`` and belong to the spec's dataset. The spec must trade
    ``MINUTE_PAIRS``, have daily history (D, A, H and V2 read daily bars), price at the
    registered base spot profile (fee and slippage of ``cost_profile(1, "spot")``) and
    evaluate months that cover the window, so that every minute played inside it is masked
    as the frozen rules mask evaluation months (from both archives).
    """
    manifest_file = manifest_path(spec_path)
    legacy_sha = hashlib.sha256(manifest_file.read_bytes()).hexdigest()
    pins = {pin.path: pin.sha256 for pin in reg.run_manifest.data_manifests}
    pinned = pins.get(MINUTE_MANIFEST_PATH)
    if pinned != legacy_sha:
        raise ValueError(
            f"the legacy manifest {manifest_file} has SHA-256 {legacy_sha}; the run-manifest "
            f"pins {pinned} for {MINUTE_MANIFEST_PATH}"
        )
    spec = load_spec(spec_path)
    manifest = load_manifest(manifest_file)
    base = cost_profile(1, "spot")
    errors = []
    if manifest["dataset"] != spec.name:
        errors.append(f"the manifest is dataset {manifest['dataset']!r}, not {spec.name!r}")
    if spec.traded != MINUTE_PAIRS:
        errors.append(f"the spec trades the pairs {spec.traded}, not {MINUTE_PAIRS}")
    if spec.daily_warmup_start is None:
        errors.append("the spec has no daily history (daily_warmup_start)")
    if (spec.fee_rate, spec.slippage_rate) != (base.fee_rate, base.slippage_rate):
        errors.append(
            f"the spec's base costs (fee {spec.fee_rate}, slippage {spec.slippage_rate}) "
            f"are not the registered base spot profile's ({base.fee_rate}, "
            f"{base.slippage_rate})"
        )
    first, last = evaluation_bounds_ms(spec)
    if not first <= window.start_ms < window.end_ms <= last:
        errors.append(
            f"the spec's evaluation months {spec.start}..{spec.end} do not cover window "
            f"{window.id} [{window.start_ms}, {window.end_ms})"
        )
    if errors:
        raise ValueError("minute dataset refused: " + "; ".join(errors))
    return spec, legacy_sha


@contextlib.contextmanager
def _cost_spec(spec_path: Path, multiple: int) -> Iterator[Path]:
    """The dataset spec at the cell's costs, for ``prepare_run``.

    At base cost it is the frozen spec itself. At doubled cost it is a copy, in a fresh
    temporary directory beside a byte copy of the manifest, whose one ``slippage_rate``
    line holds the doubled profile's slippage (``prepare_run`` reads slippage only from the
    spec) and which differs from the frozen spec in nothing else: ``load_spec`` of both
    must be equal but for that rate. The doubled maker and taker fees and the fill trigger
    at base slippage reach ``prepare_run`` as its ``fees`` and ``fill_trigger`` arguments
    (``_prepared``); the spread is the spec's, unchanged.
    """
    if multiple == 1:
        yield spec_path
        return
    slippage = cost_profile(multiple, "spot").slippage_rate
    text = spec_path.read_text(encoding="utf-8")
    if len(_SLIPPAGE_LINE.findall(text)) != 1:
        raise ValueError(f"{spec_path}: one slippage_rate line required")
    changed = _SLIPPAGE_LINE.sub(lambda _: f'slippage_rate = "{slippage}"', text)
    with tempfile.TemporaryDirectory(prefix="v31-minute-costs-") as scratch:
        target = Path(scratch) / spec_path.name
        target.write_bytes(changed.encode("utf-8"))
        shutil.copyfile(manifest_path(spec_path), manifest_path(target))
        if load_spec(target) != replace(load_spec(spec_path), slippage_rate=slippage):
            raise ValueError(f"{spec_path}: the doubled-cost spec differs beyond its slippage")
        yield target


def _prepared(
    version: MinuteVersion,
    spec_path: Path,
    config_path: Path,
    data_dir: Path,
    pair: str,
    cell: Cell,
    masks: Masks,
) -> PreparedRun:
    """The pair's frozen job setup at the cell's costs, as ``run_job`` (a grid: gated, with
    the basket and the version's structure setting) or ``trend_job`` (D: ungated, no basket)
    calls ``prepare_run``. ``fees`` is (maker, None): taker None means maker, so both are
    the profile's fee; the fill trigger is the base slippage at doubled cost and the
    spec's own (None) at base cost."""
    costs, base = cost_profile(cell.cost_multiple, "spot"), cost_profile(1, "spot")
    policy = None if version.trend else variant_policy(version.variant)
    return prepare_run(
        spec_path,
        config_path,
        data_dir,
        pair,
        version.path_mode,
        not version.trend,
        (costs.fee_rate, None),
        basket=not version.trend,
        structure=policy is not None and policy.structure,
        fill_trigger=None if cell.cost_multiple == 1 else base.slippage_rate,
        masks=masks,
    )


def _window_minutes(
    data_dir: Path,
    manifest: dict[str, Any],
    spec: DatasetSpec,
    pair: str,
    mask: frozenset[int] | None,
    bounds: tuple[int, int],
) -> tuple[Kline, ...]:
    """The pair's minutes the frozen replay plays inside ``bounds``: read by the frozen
    ``load_minutes`` with the pair's mask and documented absences, as
    ``backtest.jobs.replayed_minutes`` reads them, from only the pair's 1m month archives
    that overlap ``bounds`` (the manifest listing no other), and kept inside them."""
    start, end = bounds

    def overlapping(entry: dict[str, Any]) -> bool:
        if is_funding(entry) or (entry["symbol"], entry["interval"]) != (pair, "1m"):
            return False
        first, last = month_bounds_ms(entry["month"])
        return first < end and start < last

    listing = {**manifest, "files": [entry for entry in manifest["files"] if overlapping(entry)]}
    minutes = load_minutes(
        data_dir, listing, pair, mask=mask, excluded=exclusion_ranges(spec, pair)
    )
    return tuple(bar for bar in minutes if start <= bar.open_ms < end)


def _grid_job(
    version: MinuteVersion,
    prepared: PreparedRun,
    minutes: tuple[Kline, ...],
    spec: DatasetSpec,
    manifest: dict[str, Any],
    data_dir: Path,
    mask: frozenset[int] | None,
    bounds: tuple[int, int],
) -> MinuteJob:
    """The pair's frozen grid job, as ``run_job`` replays it: the version's policy, the
    pair's daily and hourly history, BTCUSDT's funding when G reads it, and the window."""
    policy = variant_policy(version.variant)
    funding = (
        load_funding(data_dir, manifest, FUNDING_SYMBOL, spec.months(spec.start))
        if policy is not None and policy.funding_gate
        else None
    )
    masked = mask or frozenset()
    return MinuteJob(
        prepared.config,
        prepared.run,
        minutes,
        prepared.features,
        policy,
        prepared.daily,
        prepared.hourly,
        funding,
        bounds,
        masked,
        skipped_days_for_masks(spec, masked),
    )


def _trend_job(
    prepared: PreparedRun,
    minutes: tuple[Kline, ...],
    spec: DatasetSpec,
    mask: frozenset[int] | None,
    bounds: tuple[int, int],
) -> TrendJob:
    """The pair's comparator-D job, as ``trend_job`` replays it: the pair's daily closes,
    V0's warm-up gate (``FeatureEngine.warmed``) and the window."""
    masked = mask or frozenset()
    return TrendJob(
        prepared.run,
        minutes,
        DailyCloses((bar.open_ms, bar.close) for bar in prepared.daily or ()),
        prepared.features.warmed,
        bounds,
        masked,
        skipped_days_for_masks(spec, masked),
    )


def _minute_inputs(
    version: MinuteVersion,
    spec_path: Path,
    config_path: Path,
    legacy_sha: str,
    jobs: Mapping[str, MinuteJob | TrendJob],
    bounds: tuple[int, int],
) -> dict[str, object]:
    """What a minute cell ran on, for ``native_evidence.json``: the SHA-256 of the dataset
    spec, the bot config and the legacy manifest, the frozen version, and per pair the
    path mode, gate, effective costs, minutes played and masked hours inside the window."""
    start, end = bounds
    pairs: dict[str, object] = {}
    for pair, job in sorted(jobs.items()):
        rules = job.run.rules
        pairs[pair] = {
            "path_mode": job.run.path_mode,
            "gated": job.run.gated,
            "costs": {
                "maker_fee": str(rules.fee_rate),
                "taker_fee": str(rules.taker_fee),
                "slippage": str(rules.slippage_rate),
                "fill_trigger": str(rules.fill_trigger),
                "spread": str(job.run.spread),
            },
            "minutes": len(job.minutes),
            "masked_hours_in_window": sorted(h for h in job.masked if start <= h < end),
        }
    return {
        "dataset_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "bot_config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "legacy_manifest_sha256": legacy_sha,
        "version": {"trend": version.trend, "variant": version.variant},
        "pairs": pairs,
    }


def _baseline_window(cell: Cell, reg: DriverRegistration, kind: CellKind, required: str) -> Window:
    """The registered window of ``cell``, a registered baseline cell of ``kind``; a
    baseline runs in V3.1's native scenario only."""
    window = _registered(cell, reg, kind, required)
    if cell.scenario != "native":
        raise ValueError(f"cell {cell.cell_id}: a baseline cell runs native")
    return window


def _cell_attempt(
    cell: Cell,
    reg: DriverRegistration,
    window: Window,
    attempt_id: str,
    repo_head: str,
    pack_sha256: str,
) -> dict[str, object]:
    return {
        "cell_id": cell.cell_id,
        **_attempt(
            reg,
            attempt_id=attempt_id,
            repo_head=repo_head,
            pack_sha256=pack_sha256,
            data_pin=window.data_pin,
        ),
    }


def _write_cell(
    directory: Path,
    attempt: Mapping[str, object],
    cell: Cell,
    reg: DriverRegistration,
    window: Window,
    capital: Capital,
    adapter_pin: str,
    evidence: BaselineEvidence,
    attempt_id: str,
    *,
    extra: Mapping[str, object] | None = None,
) -> None:
    """The cell's outcome under its registered identity, then its files in order:
    the native evidence (with ``extra``'s fields, if any), the report and, last, the
    outcome."""
    identity = _identity(cell, reg, window, capital, adapter_pin)
    outcome = baseline_outcome(evidence, identity, attempt_id=attempt_id)
    outcome_raw = encode_outcome(outcome).encode("ascii")
    report_raw = encode_report(evidence.report).encode("ascii")
    metadata = _metadata(
        BASELINE_SCHEMA, attempt, cell, capital, reg, adapter_pin, outcome_raw, report_raw
    )
    native = {**metadata, "evidence": _evidence_document(evidence), **(extra or {})}
    _write(directory / NATIVE_EVIDENCE_FILE, _canonical(native))
    _write(directory / "report.json", report_raw)
    _write(directory / "outcome.json", outcome_raw)  # last: the completion marker


def _evidence_document(evidence: BaselineEvidence) -> dict[str, object]:
    """The adapter's evidence besides its report, Decimals as their ``str()``."""
    return {
        "arm": evidence.arm,
        "native_label": evidence.native_label,
        "status": evidence.status,
        "liquidations": evidence.liquidations,
        "accounting_residual": _text(evidence.accounting_residual),
        "accounting_explained": evidence.accounting_explained,
        "wallet_quantity_exact": evidence.wallet_quantity_exact,
        "disclosures": list(evidence.disclosures),
        "native_marks": [
            [
                mark.timestamp_ms,
                mark.kind,
                _text(mark.equity),
                _text(mark.spot_value),
                _text(mark.futures_collateral),
            ]
            for mark in evidence.native
        ],
    }


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Decimal):
        raise ValueError("baseline evidence values must be Decimals")
    return str(value)


class _AttemptLog:
    """V3's ``record`` callback: each ``Attempt`` becomes one canonical JSON line of a new
    file, written, flushed and synced before the walk-forward goes on (V3's contract: the
    caller persists each record before returning); no runner is kept.

    A line holds the attempt's fields (its run id as ``run``) and, for a result, its stop
    reason, trade reconciliation residual and final equity. V3 prefixes every run id of a
    walk-forward with one random ``uuid4().hex``, the only part that differs between two
    runs on the same inputs: it is dropped, so the file is byte-identical across runs; the
    rest of the run id and the state name each record uniquely.
    """

    def __init__(self, path: Path) -> None:
        self._stream: BinaryIO = _safe_path(path).open("xb")
        self._digest = hashlib.sha256()
        self._prefix: str | None = None

    def __enter__(self) -> "_AttemptLog":
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stream.close()

    def __call__(self, attempt: Attempt) -> None:
        if not isinstance(attempt, Attempt):
            raise ValueError("V3 attempt record required")
        row = {
            "run": self._run(attempt.run_id),
            "state": attempt.state,
            "phase": attempt.phase,
            "rule": attempt.rule,
            "start_ms": attempt.start_ms,
            "end_ms_exclusive": attempt.end_ms_exclusive,
            "multiple": attempt.multiple,
            "cost_multiple": attempt.cost_multiple,
            "pick_schedule": [[stamp, rule] for stamp, rule in attempt.pick_schedule],
            "error": attempt.error,
            "result": None if attempt.result is None else _result(attempt.result),
        }
        line = _canonical(row) + b"\n"
        self._stream.write(line)
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._digest.update(line)

    def sha256(self) -> str:
        """The SHA-256 of every line written."""
        return self._digest.hexdigest()

    def _run(self, run_id: str) -> str:
        match = _RUN_ID.fullmatch(run_id) if type(run_id) is str else None
        if match is None:
            raise ValueError(f"V3 run id {run_id!r}: a walk-forward's hex prefix required")
        prefix, run = match.groups()
        if self._prefix is None:
            self._prefix = prefix
        elif prefix != self._prefix:
            raise ValueError("V3 attempts of more than one walk-forward")
        return run


def _result(result: ReplayResult) -> dict[str, object]:
    runner = result.runner
    path = runner.equity_path if runner is not None else []
    return {
        "reason": result.reason,
        "trade_reconciliation_residual": _text(result.trade_reconciliation_residual),
        "final_equity": _text(path[-1].equity) if path else None,
    }


def _picks_document(picks: Mapping[int, str | None]) -> dict[str, str | None]:
    """The picks as JSON: each time in ms as a decimal string, before the reserved
    boundary, mapped to a frozen rule or null."""
    refuse_sealed(picks, "V3 picks")
    if not picks or any(rule is not None and rule not in RULES for rule in picks.values()):
        raise ValueError("V3 picks: one or more picks of frozen rules or null required")
    return {str(stamp): rule for stamp, rule in sorted(picks.items())}


def _picks_outcome(document: Mapping[str, object], picks_raw: bytes) -> dict[str, object]:
    """The picks job's completion marker for the picks ``document`` written as
    ``picks_raw``: what the job's three files hash to."""
    return {
        "schema": PICKS_OUTCOME_SCHEMA,
        "job": V3_PICKS,
        "attempt_id": document["attempt_id"],
        "attempt_json_sha256": document["attempt_json_sha256"],
        "attempts_sha256": document["attempts_sha256"],
        "picks_sha256": hashlib.sha256(picks_raw).hexdigest(),
    }


def _read_picks(path: Path, reg: DriverRegistration) -> tuple[dict[int, str | None], str]:
    """The picks in ``compute_v3_picks``'s file at ``path``, and the file's SHA-256.

    The file must be the canonical JSON ``compute_v3_picks`` writes, for the registered
    V3 input pack and run-manifest; any other text, schema, pin, time or rule is refused.
    So is a picks job that is not the registered one, finished and unchanged
    (``_picks_job_errors``): one ``ValueError`` names every mismatch.
    """
    raw = Path(path).read_bytes()
    if len(raw) > MAX_PICKS_BYTES:
        raise ValueError(f"{path}: a V3 picks file of at most {MAX_PICKS_BYTES} bytes required")
    document = _strict_json(raw, "V3 picks")
    if not isinstance(document, dict) or set(document) != _PICKS_KEYS:
        raise ValueError(f"V3 picks: the fields {sorted(_PICKS_KEYS)} required")
    if _canonical(document) != raw:
        raise ValueError("V3 picks: not the canonical encoding (sorted keys, no spaces, ASCII)")
    if document["schema"] != PICKS_SCHEMA:
        raise ValueError(f"V3 picks: schema {PICKS_SCHEMA!r} required")
    if document["v3_pack_sha256"] != reg.run_manifest.v3_pack:
        raise ValueError("V3 picks: computed from another V3 pack than the run-manifest's")
    if document["run_manifest_sha256"] != reg.run_manifest_pin:
        raise ValueError("V3 picks: computed under another run-manifest")
    for key in ("attempt_json_sha256", "attempts_sha256"):
        digest = document[key]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            raise ValueError(f"V3 picks: {key} must be 64 lowercase hex")
    _check_attempt(document["attempt_id"], document["repo_head"])
    given = document["picks"]
    if not isinstance(given, dict):
        raise ValueError("V3 picks: an object of picks required")
    picks: dict[int, str | None] = {}
    for stamp, rule in given.items():
        if _STAMP.fullmatch(stamp) is None or int(stamp) >= _RESERVED:
            raise ValueError(f"V3 picks: time {stamp!r} must be ms before the reserved boundary")
        if rule is not None and rule not in RULES:
            raise ValueError(f"V3 picks: {rule!r} is not a frozen V3 rule")
        picks[int(stamp)] = rule
    if not picks:
        raise ValueError("V3 picks: one or more picks required")
    if errors := _picks_job_errors(Path(path).parent, raw, document, reg):
        header = f"V3 picks {path}: not a finished picks job of this registration:"
        raise ValueError("\n- ".join([header, *errors]))
    return dict(sorted(picks.items())), hashlib.sha256(raw).hexdigest()


def _picks_job_errors(
    directory: Path, raw: bytes, document: Mapping[str, Any], reg: DriverRegistration
) -> list[str]:
    """How the picks job in ``directory`` differs from the registered, finished one that
    wrote the picks ``document`` (its bytes ``raw``); empty when it does not.

    The picks' config and code pins must be the registration's. ``outcome.json``, the
    completion marker, must exist and hold the hashes of the claim, the log and the picks
    file. ``attempts.jsonl`` and ``attempt.json`` must hash to the values the picks record,
    and the claim must be the one ``compute_v3_picks`` writes: this job, the picks'
    attempt id and repo head, the registration's code and config pins, and the V3 pack and
    run-manifest it names.
    """
    registration = reg.registration
    errors = [
        f"the picks' {key} {_shown(document[key])} differs from the registration's {pin}"
        for key, pin in (
            ("config_pin", registration.config_pin),
            ("code_pin", registration.code_pin),
        )
        if document[key] != pin
    ]
    marker = _small_file(directory / OUTCOME_FILE)
    if marker is None:
        errors.append(f"{OUTCOME_FILE}, the completion marker, is missing: an unfinished job")
    else:
        errors += _document_errors(marker, OUTCOME_FILE, _picks_outcome(document, raw))
    log = directory / ATTEMPTS_FILE
    if not log.is_file():
        errors.append(f"{ATTEMPTS_FILE}, V3's retained attempt log, is missing")
    elif (digest := _file_sha256(log)) != document["attempts_sha256"]:
        errors.append(
            f"{ATTEMPTS_FILE} hashes to {digest}, not the picks' attempts_sha256 "
            f"{document['attempts_sha256']}"
        )
    claim = _small_file(directory / ATTEMPT_FILE)
    if claim is None:
        errors.append(f"{ATTEMPT_FILE}, the picks job's claim, is missing")
        return errors
    if (digest := hashlib.sha256(claim).hexdigest()) != document["attempt_json_sha256"]:
        errors.append(
            f"{ATTEMPT_FILE} hashes to {digest}, not the picks' attempt_json_sha256 "
            f"{document['attempt_json_sha256']}"
        )
    expected = {
        "job": V3_PICKS,
        "attempt_id": document["attempt_id"],
        "repo_head": document["repo_head"],
        "code_pin": registration.code_pin,
        "config_pin": registration.config_pin,
        "pack_sha256": reg.run_manifest.v3_pack,
        "data_pin": reg.run_manifest_pin,
    }
    return errors + _document_errors(claim, ATTEMPT_FILE, expected)


def _document_errors(raw: bytes, name: str, expected: Mapping[str, object]) -> list[str]:
    """How the canonical JSON file ``raw`` differs from the ``expected`` object: each field
    that is missing, extra or unequal, or a file that is not that canonical JSON."""
    try:
        found = _strict_json(raw, name)
    except (ValueError, RecursionError) as exc:
        return [f"{name} is not readable JSON: {_shown(str(exc))}"]
    if not isinstance(found, dict):
        return [f"{name}: a JSON object required"]
    errors = [
        f"{name}: {key} is {_shown(found.get(key))}, expected {_shown(expected.get(key))}"
        for key in sorted(found.keys() | expected.keys())
        if key not in found or key not in expected or found[key] != expected[key]
    ]
    if not errors and _canonical(found) != raw:
        errors.append(f"{name}: not the canonical encoding (sorted keys, no spaces, ASCII)")
    return errors


def _small_file(path: Path) -> bytes | None:
    """The bytes of the small job file ``path``, or None when it is not a file."""
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        raw = stream.read(MAX_PICKS_BYTES + 1)
    if len(raw) > MAX_PICKS_BYTES:
        raise ValueError(f"{path}: a picks job file of at most {MAX_PICKS_BYTES} bytes required")
    return raw


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _shown(value: object) -> str:
    """``value`` as a short ``repr``, so that a hostile file cannot flood a message."""
    text = repr(value)
    return text if len(text) <= 100 else text[:97] + "..."
