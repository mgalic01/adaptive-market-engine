"""The V3.1 registration: every cell the driver runs, and every pin each cell must match.

Four committed JSON files, each read strictly: a duplicate key, a JSON float or NaN is
refused, money and FX values are decimal strings, and every object holds exactly its keys.

- ``config/v3_1_prepare.json`` (``load_prepare_config``, Ruling P1): the windows with their
  symbols, and the data manifests and the spot and futures filter snapshots by path and
  SHA-256. Prepare runs from it before any registration exists.
- The FX source record (Ruling P10f): ``schema``, ``usd_per_eur`` (the ECB reference
  rate, USDT taken at par), ``reference_date``, ``source_url`` (an https ECB page) and
  ``retrieved_on``. Its file's SHA-256 is the owner_small capital's ``fx_pin``.
- ``config/v3_1_run_manifest.json`` (``run_manifest``, ``write_run_manifest``): every input
  pin of every cell, as canonical JSON. Its file's SHA-256 is every window's ``data_pin``
  (Ruling P10b).
- ``config/v3_1_registration.json`` (``load_registration``): the code pin, the prepare and
  run-manifest pins, the arms, adapter pins, cost profiles, capitals, the windows with
  their skipped hours, and the cell list. Its file's SHA-256 is the ``config_pin``
  (Ruling P10a), computed on load: the file never holds it.

Reading those files and ``adapter_pins``' ``git ls-tree`` are the only I/O; no network.
"""

import hashlib
import json
import re
import subprocess
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlsplit

from crypto_grid_bot.backtest.replay import PATH_MODES
from crypto_grid_bot.combined.common_series import skipped_hours_valid
from crypto_grid_bot.combined.driver.venues import COST_PROFILE_PINS
from crypto_grid_bot.combined.experiment import (
    SCENARIOS,
    Capital,
    Registration,
    Window,
    _registration_errors,
)
from crypto_grid_bot.market_data.parsing import symbol_name

CellKind = Literal["v31", "v3", "hold", "minute"]

# The pinned V1 grid variants (owner, 2026-10-12); a registration carries exactly these.
V1_VARIANTS = ("a", "b", "c", "e", "f", "g", "cg", "h", "ch")
COMPONENT_ARMS = (
    "spot_trend",
    "futures_trend",
    "futures_trend_long_only",
    "spot_grid",
    "combined",
    "combined_without_continuation",
    "combined_without_full_short_qualification",
    "combined_without_discretionary_trailing",
    "combined_without_funding_admission",
    "combined_without_recovery",
)
V3_ARMS = ("unchanged_v3_selector", *(f"unchanged_v3_r{i}_long_only" for i in range(1, 7)))
HOLD_ARM = "matched_spot_hold"
MENU_PLACEHOLDER = "matched_spot_baselines"
MENU_PATH = "config/v3_1_experiment_menu.json"
ACCEPTANCE_WINDOW = "w1"  # the pass/fail window, the only one acceptance judges
REPORTED_WINDOW = "w0"  # reported only: the combined arm, no acceptance
COST_MULTIPLES = (1, 2)
CAPITAL_IDS = ("research", "owner_small")

REGISTRATION_SCHEMA = "v3.1-registration-1"
PREPARE_SCHEMA = "v3.1-prepare-1"
RUN_MANIFEST_SCHEMA = "v3.1-run-manifest-1"
FX_RECORD_SCHEMA = "v3.1-fx-record-1"

_RESERVED = 1_735_689_600_000
_DAY = 86_400_000
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_WINDOW_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")  # no '.', the cell id separator
_CELL_ID = re.compile(r"[a-z0-9._-]+")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_FIRST_RESERVED_DAY = date(2025, 1, 1)
_ABBREVIATIONS = {"open_low_high_close": "olhc", "open_high_low_close": "ohlc", "native": "native"}
_KINDS: dict[str, CellKind] = {"v31": "v31", "v3": "v3", "hold": "hold", "minute": "minute"}
_COST_PROFILES = tuple((multiple, COST_PROFILE_PINS[multiple]) for multiple in COST_MULTIPLES)

_REGISTRATION_KEYS = frozenset(
    {
        "schema",
        "code_pin",
        "prepare_sha256",
        "run_manifest_sha256",
        "observation_policy",
        "scenarios",
        "v1_variants",
        "arms",
        "adapter_pins",
        "cost_profiles",
        "capitals",
        "windows",
        "reported_windows",
        "cells",
    }
)
_WINDOW_KEYS = frozenset({"id", "start_ms", "end_ms", "skipped_hours"})
_CAPITAL_KEYS = frozenset({"id", "currency", "amount", "initial_equity"})
_FX_CAPITAL_KEYS = _CAPITAL_KEYS | {"fx_rate", "fx_record"}
_PIN_KEYS = frozenset({"path", "sha256"})
_COST_KEYS = frozenset({"multiple", "sha256"})
_PREPARE_KEYS = frozenset({"schema", "windows", "data_manifests", "filter_snapshots"})
_PREPARE_WINDOW_KEYS = frozenset({"id", "start_ms", "end_ms", "symbols"})
_SNAPSHOT_KEYS = frozenset({"spot", "futures"})
_MANIFEST_KEYS = frozenset(
    {
        "schema",
        "data_manifests",
        "filter_snapshots",
        "window_packs",
        "v3_pack_sha256",
        "prepare_sha256",
    }
)
_FX_RECORD_KEYS = frozenset(
    {"schema", "usd_per_eur", "reference_date", "source_url", "retrieved_on"}
)

_SRC = "src/crypto_grid_bot/"
_SHARED_PACKAGES = ("market_data",)
# Each kind's adapter module set (Ruling P12): named modules, and packages whose every
# ``.py`` file counts. Components take ``combined`` without its ``baseline_*.py`` files.
_MODULE_SETS: dict[CellKind, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "v31": ((), ("combined",)),
    "v3": (("combined/baseline_v3.py", "combined/baseline_records.py"), ("trend",)),
    "hold": (("combined/baseline_hold.py", "combined/baseline_records.py"), ()),
    "minute": (
        ("combined/baseline_minute.py", "combined/baseline_records.py"),
        ("backtest", "simulation", "strategy"),
    ),
}


def minute_arms(v1_variants: tuple[str, ...]) -> tuple[str, ...]:
    """The minute baselines ``experiment.required_baselines`` names, in registration order:
    V0, each V1 variant as given, V2 and D, each in both path modes."""
    bases = ("v0_grid", *(f"v1_{variant}_grid" for variant in v1_variants), "v2_grid", "d_trend")
    return tuple(f"matched_{base}_{mode}" for base in bases for mode in PATH_MODES)


_MINUTE_ARMS = minute_arms(V1_VARIANTS)
_REGISTERED_ARMS = (*COMPONENT_ARMS, *V3_ARMS, HOLD_ARM, *_MINUTE_ARMS)


def registered_arms(
    menu_arms: Sequence[str], v1_variants: tuple[str, ...] = V1_VARIANTS
) -> tuple[str, ...]:
    """The menu's arms with its one ``matched_spot_baselines`` replaced, in place, by the
    minute arms of ``v1_variants``: the arm list a registration must carry."""
    if list(menu_arms).count(MENU_PLACEHOLDER) != 1:
        raise ValueError(f"the menu must name {MENU_PLACEHOLDER} exactly once")
    expanded = minute_arms(v1_variants)
    return tuple(
        arm for item in menu_arms for arm in (expanded if item == MENU_PLACEHOLDER else (item,))
    )


@dataclass(frozen=True, slots=True)
class Cell:
    """One registered run: an arm in one window, scenario, cost multiple and capital.

    ``cell_id`` is ``<window>.<arm>.<olhc|ohlc|native>.c<multiple>.<capital>``, URL-safe
    (``[a-z0-9._-]+``). Baselines run ``native``; ``reported_only`` cells (W0) carry no
    acceptance. ``dataclasses.asdict`` gives the cell's object in the registration file.
    """

    cell_id: str
    arm: str
    window: str
    scenario: str
    cost_multiple: int
    capital_id: str
    kind: CellKind
    reported_only: bool


@dataclass(frozen=True, slots=True)
class FilePin:
    """A committed file by repository-relative POSIX path and the SHA-256 of its bytes."""

    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class PrepareWindow:
    id: str
    start_ms: int
    end_ms: int
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PrepareConfig:
    """Prepare's inputs (Ruling P1); ``data_manifests`` sorted by path and ``sha256`` the
    file's own SHA-256, which the registration and the run-manifest pin."""

    windows: tuple[PrepareWindow, ...]
    data_manifests: tuple[FilePin, ...]
    spot_filters: FilePin
    futures_filters: FilePin
    sha256: str


@dataclass(frozen=True, slots=True)
class RunManifest:
    """The run-manifest's pins: files sorted by path, packs by window id."""

    data_manifests: tuple[FilePin, ...]
    filter_snapshots: tuple[FilePin, ...]
    window_packs: tuple[tuple[str, str], ...]
    v3_pack: str
    prepare: str


@dataclass(frozen=True, slots=True)
class DriverRegistration:
    """A loaded registration. ``registration`` is what acceptance judges: its windows are
    W1 alone. ``reported_windows`` is W0. Every window's data pin is ``run_manifest_pin``;
    ``menu_arms`` are the committed menu's, unexpanded. ``fx_record_paths`` are the
    repository paths of the FX records the capitals name, sorted (the execution gate
    accepts a change to them)."""

    registration: Registration
    reported_windows: tuple[Window, ...]
    cells: tuple[Cell, ...]
    run_manifest_pin: str
    run_manifest: RunManifest
    prepare_pin: str
    menu_arms: tuple[str, ...]
    fx_record_paths: tuple[str, ...] = ()


def required_cells(reg: DriverRegistration) -> tuple[Cell, ...]:
    """Every cell the registration must list, in a fixed order.

    For each acceptance window, each arm of ``registered_arms`` (the menu's, expanded with
    the pinned V1 variants), in that order: components in both modeled scenarios,
    baselines ``native``; within each, cost multiples 1 then 2 and the capitals research
    then owner_small. Then each reported window's ``combined`` cells in the same nesting,
    ``reported_only``. Refuses a menu whose arms are not the registered arm set.
    """
    cells: list[Cell] = []
    arms = registered_arms(reg.menu_arms, V1_VARIANTS)
    for window in reg.registration.windows:
        for arm in arms:
            kind = _arm_kind(arm)
            scenarios = SCENARIOS if kind == "v31" else ("native",)
            cells.extend(_cells(window.id, arm, kind, scenarios, reported_only=False))
    for window in reg.reported_windows:
        cells.extend(_cells(window.id, "combined", "v31", SCENARIOS, reported_only=True))
    return tuple(cells)


def check_registration(reg: DriverRegistration) -> None:
    """Return None for a registration the driver may run; otherwise raise one
    ``ValueError`` listing every problem found.

    Checks that ``experiment``'s registration rules pass; that W1 is the only acceptance
    window and W0 the only reported one, valid by the same rules; that every data pin is
    the run-manifest pin; the prepare, pack and cost-profile pins; the pinned V1 variants;
    that the arms equal the menu's with its spot baselines expanded; and that the cell
    list equals ``required_cells``.
    """
    if not isinstance(reg, DriverRegistration):
        raise ValueError("a DriverRegistration required")
    registration = reg.registration
    errors = list(_registration_errors(registration))
    window_ids = tuple(window.id for window in registration.windows)
    reported_ids = tuple(window.id for window in reg.reported_windows)
    if window_ids != (ACCEPTANCE_WINDOW,):
        errors.append(f"the acceptance window must be {ACCEPTANCE_WINDOW} alone, got {window_ids}")
    if reported_ids != (REPORTED_WINDOW,):
        errors.append(f"the reported window must be {REPORTED_WINDOW} alone, got {reported_ids}")
    for window in reg.reported_windows:
        errors.extend(_reported_window_errors(window))
    if not _is_sha(reg.run_manifest_pin):
        errors.append("the run-manifest pin must be 64 lowercase hex")
    for window in (*registration.windows, *reg.reported_windows):
        if window.data_pin != reg.run_manifest_pin:
            errors.append(f"{window.id}: the data pin is not the run-manifest pin")
    if not _is_sha(reg.prepare_pin) or reg.prepare_pin != reg.run_manifest.prepare:
        errors.append("the registration's prepare pin differs from the run-manifest's")
    packed = tuple(window_id for window_id, _ in reg.run_manifest.window_packs)
    if sorted(packed) != sorted((*window_ids, *reported_ids)):
        errors.append(f"the run-manifest packs windows {packed}, not the registered windows")
    if tuple(registration.cost_profiles) != _COST_PROFILES:
        errors.append(f"the cost profiles must be {_COST_PROFILES}, venues.COST_PROFILE_PINS")
    for capital in registration.capitals:
        if capital.id == "research" and (capital.fx_rate, capital.fx_pin) != (None, None):
            errors.append("the research capital takes no FX rate or record")
    if registration.v1_variants != V1_VARIANTS:
        errors.append(f"the V1 variants must be {', '.join(V1_VARIANTS)}")
    errors.extend(_arm_errors(registration.arms, reg.menu_arms))
    try:
        expected = required_cells(reg)
    except ValueError as exc:
        errors.append(f"no required cell list: {exc}")
    else:
        errors.extend(_cell_errors(reg.cells, expected))
    if errors:
        raise ValueError("registration refused:\n- " + "\n- ".join(errors))


def load_registration(
    path: str | Path, run_manifest_path: str | Path, *, repo_root: str | Path = "."
) -> DriverRegistration:
    """The registration at ``path``, with ``check_registration`` passed.

    ``config_pin`` is the SHA-256 of the file's bytes; a file holding a ``config_pin`` key
    is refused. The run-manifest file's SHA-256 must equal the recorded
    ``run_manifest_sha256`` and becomes every window's ``data_pin``. The FX record's path
    (repository-relative, under ``repo_root``) must hash to its recorded SHA-256, which
    becomes the capital's ``fx_pin``, and hold the capital's ``fx_rate``. The arm menu is
    read from ``repo_root``/``MENU_PATH``.
    """
    data = Path(path).read_bytes()
    document = _strict_json(data, "registration")
    if isinstance(document, dict) and "config_pin" in document:
        raise ValueError(
            "registration: the file cannot hold its own config_pin; it is the SHA-256 of "
            "the file's bytes, computed on load"
        )
    doc = _object(document, _REGISTRATION_KEYS, "registration")
    _schema(doc, REGISTRATION_SCHEMA, "registration")
    manifest_data = Path(run_manifest_path).read_bytes()
    manifest_pin = _sha256(manifest_data)
    recorded = _str(doc["run_manifest_sha256"], "registration run_manifest_sha256")
    if recorded != manifest_pin:
        raise ValueError(
            f"run-manifest: {run_manifest_path} has SHA-256 {manifest_pin}; "
            f"the registration pins {recorded}"
        )
    manifest = _run_manifest_from(manifest_data)
    root = Path(repo_root)
    arms = _strings(doc["arms"], "registration arms")
    capitals = _list(doc["capitals"], "capitals")
    registration = Registration(
        arms=arms,
        baseline_arms=tuple(arm for arm in arms if arm not in COMPONENT_ARMS),
        windows=_windows(doc["windows"], manifest_pin, "windows"),
        capitals=tuple(_capital(item, root) for item in capitals),
        cost_profiles=tuple(_cost_profile(item) for item in _list(doc["cost_profiles"], "costs")),
        code_pin=_str(doc["code_pin"], "registration code_pin"),
        config_pin=_sha256(data),
        observation_policy=_str(doc["observation_policy"], "registration observation_policy"),
        adapter_pins=tuple(
            (arm, _str(pin, f"adapter pin of {arm}"))
            for arm, pin in sorted(_mapping(doc["adapter_pins"], "adapter_pins").items())
        ),
        scenarios=_strings(doc["scenarios"], "registration scenarios"),
        v1_variants=_strings(doc["v1_variants"], "registration v1_variants"),
    )
    reg = DriverRegistration(
        registration=registration,
        reported_windows=_windows(doc["reported_windows"], manifest_pin, "reported_windows"),
        cells=tuple(_cell(item) for item in _list(doc["cells"], "cells")),
        run_manifest_pin=manifest_pin,
        run_manifest=manifest,
        prepare_pin=_str(doc["prepare_sha256"], "registration prepare_sha256"),
        menu_arms=_menu_arms((root / MENU_PATH).read_bytes()),
        fx_record_paths=_fx_record_paths(capitals),
    )
    check_registration(reg)
    return reg


def load_prepare_config(path: str | Path) -> PrepareConfig:
    """The prepare config at ``path`` (Ruling P1), with its file's SHA-256.

    Refuses: no window, a repeated window id, an id outside ``[a-z0-9][a-z0-9_-]*``, a
    window that is not whole UTC days, at least two, ending at or before the reserved
    boundary; an empty or repeated symbol list or an invalid symbol; no data manifest; a
    path that is not canonical and repository-relative; a malformed SHA-256; filter
    snapshots other than one spot and one futures file at different paths.
    """
    data = Path(path).read_bytes()
    doc = _object(_strict_json(data, "prepare"), _PREPARE_KEYS, "prepare")
    _schema(doc, PREPARE_SCHEMA, "prepare")
    windows = tuple(_prepare_window(item) for item in _list(doc["windows"], "prepare windows"))
    ids = [window.id for window in windows]
    if not windows or len(set(ids)) != len(ids):
        raise ValueError("prepare: one or more windows required, and window ids must be unique")
    manifests = _file_pins(doc["data_manifests"], "prepare data_manifests")
    if not manifests:
        raise ValueError("prepare: one or more data manifests required")
    snapshots = _object(doc["filter_snapshots"], _SNAPSHOT_KEYS, "prepare filter_snapshots")
    spot = _file_pin(snapshots["spot"], "prepare spot filter snapshot")
    futures = _file_pin(snapshots["futures"], "prepare futures filter snapshot")
    if spot.path == futures.path:
        raise ValueError("prepare: the spot and futures filter snapshots must differ")
    return PrepareConfig(windows, manifests, spot, futures, _sha256(data))


def run_manifest(
    prepare: PrepareConfig, *, window_packs: Mapping[str, str], v3_pack: str
) -> dict[str, object]:
    """The run-manifest document: every input pin of every cell (Rulings P1, P2, P9, P10b).

    ``data_manifests`` and ``filter_snapshots`` map each file's path to its SHA-256 as
    ``prepare`` pins them; ``window_packs`` maps each prepare window id to its pack pin
    (``packs.write_pack``'s); ``v3_pack_sha256`` is the V3 input pack's pin and
    ``prepare_sha256`` the prepare file's. Refuses packs for any other windows than
    prepare's and a malformed pin.
    """
    if not isinstance(prepare, PrepareConfig):
        raise ValueError("a PrepareConfig required")
    ids = sorted(window.id for window in prepare.windows)
    if sorted(window_packs) != ids:
        raise ValueError(
            f"run-manifest: window packs must be exactly the prepare windows {ids}, "
            f"got {sorted(window_packs)}"
        )
    snapshots = (prepare.spot_filters, prepare.futures_filters)
    document: dict[str, object] = {
        "schema": RUN_MANIFEST_SCHEMA,
        "data_manifests": {pin.path: pin.sha256 for pin in prepare.data_manifests},
        "filter_snapshots": {pin.path: pin.sha256 for pin in snapshots},
        "window_packs": {
            window_id: _sha(sha, f"run-manifest pack of {window_id}")
            for window_id, sha in sorted(window_packs.items())
        },
        "v3_pack_sha256": _sha(v3_pack, "run-manifest V3 pack"),
        "prepare_sha256": _sha(prepare.sha256, "run-manifest prepare"),
    }
    _run_manifest_from(_canonical(document))
    return document


def write_run_manifest(manifest: Mapping[str, object], path: str | Path) -> str:
    """Write ``manifest`` to a new file at ``path`` as canonical JSON (sorted keys, no
    spaces, a trailing newline) and return the file's SHA-256, the data pin. Refuses a
    document ``load_registration`` would refuse; an existing file is never replaced."""
    data = _canonical(manifest)
    _run_manifest_from(data)
    with open(path, "xb") as handle:
        handle.write(data)
    return _sha256(data)


def adapter_pins(repo_root: str | Path, commit: str) -> dict[str, str]:
    """Each registered arm's adapter pin at ``commit``, keyed by every registered arm.

    An arm's pin is the SHA-256 of ``json.dumps(listing, separators=(",", ":"))`` (ASCII),
    where ``listing`` is ``[path, blob id]`` for each module of the arm's set, sorted by
    path. Blob ids come from ``git ls-tree -r`` at the commit, never the working tree, so a
    Windows autocrlf checkout and Linux CI agree. The module sets (Ruling P12), each with
    every ``src/crypto_grid_bot/market_data/**/*.py``:

    - the 10 components: ``combined/**/*.py`` except ``baseline_*.py``;
    - the 7 V3 arms: ``combined/baseline_v3.py``, ``combined/baseline_records.py`` and
      ``trend/**/*.py``;
    - ``matched_spot_hold``: ``combined/baseline_hold.py`` and ``baseline_records.py``;
    - the 24 minute arms: ``combined/baseline_minute.py``, ``baseline_records.py`` and
      ``{backtest,simulation,strategy}/**/*.py``.

    Refuses a commit that is not 40 lowercase hex or that git cannot read, and a commit
    missing a named module or every module of a listed package.
    """
    if type(commit) is not str or _COMMIT.fullmatch(commit) is None:
        raise ValueError(f"commit {commit!r}: 40 lowercase hex required")
    blobs = _blobs(Path(repo_root), commit)
    pins = {kind: _module_pin(kind, blobs) for kind in _MODULE_SETS}
    return {arm: pins[_arm_kind(arm)] for arm in sorted(_REGISTERED_ARMS)}


def _arm_kind(arm: str) -> CellKind:
    if arm in COMPONENT_ARMS:
        return "v31"
    if arm in V3_ARMS:
        return "v3"
    if arm == HOLD_ARM:
        return "hold"
    if arm in _MINUTE_ARMS:
        return "minute"
    raise ValueError(f"arm {arm!r} is not a registered V3.1 arm")


def _cells(
    window: str, arm: str, kind: CellKind, scenarios: tuple[str, ...], *, reported_only: bool
) -> Iterator[Cell]:
    for scenario in scenarios:
        for multiple in COST_MULTIPLES:
            for capital in CAPITAL_IDS:
                cell_id = f"{window}.{arm}.{_ABBREVIATIONS[scenario]}.c{multiple}.{capital}"
                if _CELL_ID.fullmatch(cell_id) is None:
                    raise ValueError(f"cell id {cell_id!r}: [a-z0-9._-] only")
                yield Cell(cell_id, arm, window, scenario, multiple, capital, kind, reported_only)


def _reported_window_errors(window: Window) -> list[str]:
    """``experiment``'s window rules, for a window its registration does not judge."""
    start, end = window.start_ms, window.end_ms
    if (
        not isinstance(window.id, str)
        or not _WINDOW_ID.fullmatch(window.id)
        or type(start) is not int
        or type(end) is not int
        or not 0 <= start < end <= _RESERVED
        or not _is_sha(window.data_pin)
    ):
        return [f"{window.id}: invalid window dates or data pin"]
    if start % _DAY or end % _DAY or end - start < 2 * _DAY:
        return [f"{window.id}: whole UTC days and at least two days required"]
    if not skipped_hours_valid(window.skipped_hours, start, end):
        return [
            f"{window.id}: skipped hours must be sorted hours strictly inside the window, "
            "never its first or last hour"
        ]
    return []


def _arm_errors(arms: tuple[str, ...], menu_arms: tuple[str, ...]) -> list[str]:
    try:
        expected = registered_arms(menu_arms, V1_VARIANTS)
    except ValueError as exc:
        return [str(exc)]
    if tuple(arms) == expected:
        return []
    missing = [arm for arm in expected if arm not in arms]
    extra = [arm for arm in arms if arm not in expected]
    return [
        f"the arms must equal the menu's arms with {MENU_PLACEHOLDER} expanded to the "
        f"{len(_MINUTE_ARMS)} minute arms, in order (missing: {', '.join(missing) or 'none'}; "
        f"unexpected: {', '.join(extra) or 'none'})"
    ]


def _cell_errors(cells: tuple[Cell, ...], expected: tuple[Cell, ...]) -> list[str]:
    if tuple(cells) == expected:
        return []
    ids = Counter(cell.cell_id for cell in cells)
    required = {cell.cell_id: cell for cell in expected}
    errors = []
    if missing := [cell_id for cell_id in required if cell_id not in ids]:
        errors.append(f"cells missing: {', '.join(missing)}")
    if extra := [cell_id for cell_id in ids if cell_id not in required]:
        errors.append(f"cells outside the required list: {', '.join(extra)}")
    if repeated := [cell_id for cell_id, count in ids.items() if count > 1]:
        errors.append(f"cells duplicated: {', '.join(repeated)}")
    altered = sorted(
        {
            cell.cell_id
            for cell in cells
            if cell.cell_id in required and cell != required[cell.cell_id]
        }
    )
    if altered:
        errors.append(f"cells differing from the required fields: {', '.join(altered)}")
    return errors or ["cells out of the required order"]


def _windows(value: object, data_pin: str, what: str) -> tuple[Window, ...]:
    windows = []
    for item in _list(value, what):
        doc = _object(item, _WINDOW_KEYS, what)
        windows.append(
            Window(
                id=_str(doc["id"], f"{what} id"),
                start_ms=_int(doc["start_ms"], f"{what} start_ms"),
                end_ms=_int(doc["end_ms"], f"{what} end_ms"),
                data_pin=data_pin,
                skipped_hours=tuple(
                    _int(hour, f"{what} skipped hour")
                    for hour in _list(doc["skipped_hours"], f"{what} skipped_hours")
                ),
            )
        )
    return tuple(windows)


def _capital(value: object, root: Path) -> Capital:
    """A capital; one with an ``fx_record`` gets that file's verified SHA-256 as fx_pin."""
    with_fx = isinstance(value, dict) and bool({"fx_rate", "fx_record"} & value.keys())
    doc = _object(value, _FX_CAPITAL_KEYS if with_fx else _CAPITAL_KEYS, "capital")
    capital_id = _str(doc["id"], "capital id")
    what = f"capital {capital_id}"
    initial = _decimal(doc["initial_equity"], f"{what} initial_equity")
    currency = _str(doc["currency"], f"{what} currency")
    amount = _decimal(doc["amount"], f"{what} amount")
    if not with_fx:
        return Capital(capital_id, initial, currency, amount)
    rate = _decimal(doc["fx_rate"], f"{what} fx_rate")
    pin = _file_pin(doc["fx_record"], f"{what} fx_record")
    data = (root / pin.path).read_bytes()
    actual = _sha256(data)
    if actual != pin.sha256:
        raise ValueError(
            f"{what}: FX record {pin.path} has SHA-256 {actual}; the registration pins {pin.sha256}"
        )
    recorded = _fx_rate(data, pin.path)
    if recorded != rate:
        raise ValueError(
            f"{what}: FX record rate {recorded} differs from the capital's fx_rate {rate}"
        )
    return Capital(capital_id, initial, currency, amount, fx_rate=rate, fx_pin=actual)


def _fx_record_paths(capitals: list[object]) -> tuple[str, ...]:
    """The FX record paths of capitals ``_capital`` has already read, sorted, each once."""
    return tuple(
        sorted(
            {
                _file_pin(item["fx_record"], "fx_record").path
                for item in capitals
                if isinstance(item, dict) and "fx_record" in item
            }
        )
    )


def _fx_rate(data: bytes, path: str) -> Decimal:
    """The USD per EUR rate of a valid FX source record: an ECB reference rate dated
    before 2025, retrieved on or after that date, from an https ECB URL."""
    what = f"FX record {path}"
    doc = _object(_strict_json(data, what), _FX_RECORD_KEYS, what)
    _schema(doc, FX_RECORD_SCHEMA, what)
    rate = _decimal(doc["usd_per_eur"], f"{what} usd_per_eur")
    if not rate:
        raise ValueError(f"{what}: a positive usd_per_eur required")
    reference = _date(doc["reference_date"], f"{what} reference_date")
    retrieved = _date(doc["retrieved_on"], f"{what} retrieved_on")
    if reference >= _FIRST_RESERVED_DAY:
        raise ValueError(f"{what}: the reference date must be before 2025-01-01")
    if retrieved < reference:
        raise ValueError(f"{what}: retrieved before its reference date")
    url = urlsplit(_str(doc["source_url"], f"{what} source_url"))
    host = url.hostname or ""
    if url.scheme != "https" or not (host == "ecb.europa.eu" or host.endswith(".ecb.europa.eu")):
        raise ValueError(f"{what}: an https ECB (ecb.europa.eu) source URL required")
    return rate


def _cost_profile(value: object) -> tuple[int, str]:
    doc = _object(value, _COST_KEYS, "cost profile")
    return _int(doc["multiple"], "cost profile multiple"), _str(doc["sha256"], "cost profile")


def _cell(value: object) -> Cell:
    doc = _object(value, frozenset(field.name for field in fields(Cell)), "cell")
    cell_id = _str(doc["cell_id"], "cell id")
    kind = _KINDS.get(_str(doc["kind"], f"cell {cell_id} kind"))
    if kind is None:
        raise ValueError(f"cell {cell_id}: kind must be one of {', '.join(_KINDS)}")
    return Cell(
        cell_id=cell_id,
        arm=_str(doc["arm"], f"cell {cell_id} arm"),
        window=_str(doc["window"], f"cell {cell_id} window"),
        scenario=_str(doc["scenario"], f"cell {cell_id} scenario"),
        cost_multiple=_int(doc["cost_multiple"], f"cell {cell_id} cost_multiple"),
        capital_id=_str(doc["capital_id"], f"cell {cell_id} capital_id"),
        kind=kind,
        reported_only=_bool(doc["reported_only"], f"cell {cell_id} reported_only"),
    )


def _menu_arms(data: bytes) -> tuple[str, ...]:
    document = _strict_json(data, "menu")
    if not isinstance(document, dict) or "arms" not in document:
        raise ValueError("menu: an arms list required")
    return _strings(document["arms"], "menu arms")


def _prepare_window(value: object) -> PrepareWindow:
    doc = _object(value, _PREPARE_WINDOW_KEYS, "prepare window")
    window_id = _str(doc["id"], "prepare window id")
    if _WINDOW_ID.fullmatch(window_id) is None:
        raise ValueError(f"prepare window id {window_id!r}: [a-z0-9][a-z0-9_-]* required")
    what = f"prepare window {window_id}"
    start = _int(doc["start_ms"], f"{what} start_ms")
    end = _int(doc["end_ms"], f"{what} end_ms")
    if start % _DAY or end % _DAY or not 0 <= start < end <= _RESERVED or end - start < 2 * _DAY:
        raise ValueError(
            f"{what}: start and end must be whole UTC days before the reserved boundary "
            f"({_RESERVED}), at least two days apart"
        )
    symbols = _strings(doc["symbols"], f"{what} symbols")
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValueError(f"{what}: symbols must be nonempty and unique")
    for symbol in symbols:
        try:
            symbol_name(symbol)
        except ValueError as exc:
            raise ValueError(f"{what}: invalid symbol {symbol!r} ({exc})") from exc
    return PrepareWindow(window_id, start, end, symbols)


def _run_manifest_from(data: bytes) -> RunManifest:
    """The run-manifest in ``data``, which must be its canonical JSON."""
    doc = _object(_strict_json(data, "run-manifest"), _MANIFEST_KEYS, "run-manifest")
    _schema(doc, RUN_MANIFEST_SCHEMA, "run-manifest")
    if data != _canonical(doc):
        raise ValueError("run-manifest: not canonical JSON (sorted keys, no spaces, one newline)")
    manifests = _file_pins(doc["data_manifests"], "run-manifest data_manifests")
    snapshots = _file_pins(doc["filter_snapshots"], "run-manifest filter_snapshots")
    packs = tuple(
        (window_id, _sha(sha, f"run-manifest pack of {window_id}"))
        for window_id, sha in sorted(_mapping(doc["window_packs"], "window_packs").items())
    )
    if not manifests or len(snapshots) != 2 or not packs:
        raise ValueError("run-manifest: data manifests, two filter snapshots and packs required")
    for window_id, _ in packs:
        if _WINDOW_ID.fullmatch(window_id) is None:
            raise ValueError(f"run-manifest: invalid window id {window_id!r}")
    return RunManifest(
        manifests,
        snapshots,
        packs,
        _sha(doc["v3_pack_sha256"], "run-manifest V3 pack"),
        _sha(doc["prepare_sha256"], "run-manifest prepare"),
    )


def _blobs(root: Path, commit: str) -> dict[str, str]:
    """Every blob at ``commit`` by repository path, from ``git ls-tree``."""
    process = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", "--full-tree", f"{commit}^{{commit}}"],
        capture_output=True,
        check=False,
    )
    if process.returncode:
        message = process.stderr.decode("utf-8", "replace").strip()
        raise ValueError(f"git ls-tree cannot read commit {commit} in {root}: {message}")
    blobs: dict[str, str] = {}
    for record in process.stdout.split(b"\0"):
        if not record:
            continue
        meta, tab, name = record.partition(b"\t")
        parts = meta.split(b" ")
        if not tab or len(parts) != 3:
            raise ValueError(f"git ls-tree: unreadable record {record!r}")
        if parts[1] == b"blob":
            blobs[name.decode("utf-8")] = parts[2].decode("ascii")
    return blobs


def _module_pin(kind: CellKind, blobs: Mapping[str, str]) -> str:
    named, packages = _MODULE_SETS[kind]
    chosen = {_SRC + name for name in named}
    if missing := sorted(chosen - blobs.keys()):
        raise ValueError(f"{kind} adapter modules missing at the commit: {', '.join(missing)}")
    for package in (*packages, *_SHARED_PACKAGES):
        prefix = f"{_SRC}{package}/"
        found = {
            path
            for path in blobs
            if path.startswith(prefix)
            and path.endswith(".py")
            and not (package == "combined" and PurePosixPath(path).name.startswith("baseline_"))
        }
        if not found:
            raise ValueError(f"{kind}: no {prefix}**/*.py module at the commit")
        chosen |= found
    listing = [[path, blobs[path]] for path in sorted(chosen)]
    return _sha256(json.dumps(listing, separators=(",", ":")).encode("ascii"))


def _canonical(document: object) -> bytes:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return (text + "\n").encode("ascii")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _strict_json(data: bytes, what: str) -> object:
    """``data`` parsed as UTF-8 JSON, refusing duplicate keys, floats and NaN/Infinity."""

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{what}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def refuse(text: str) -> object:
        raise ValueError(f"{what}: {text} is a JSON float or constant; write decimals as strings")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{what}: not UTF-8 ({exc})") from exc
    return json.loads(text, object_pairs_hook=unique, parse_float=refuse, parse_constant=refuse)


def _schema(doc: dict[str, object], schema: str, what: str) -> None:
    if doc["schema"] != schema:
        raise ValueError(f"{what}: schema {schema!r} required, got {doc['schema']!r}")


def _object(value: object, keys: frozenset[str], what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{what}: a JSON object required")
    if missing := sorted(keys - value.keys()):
        raise ValueError(f"{what}: missing fields: {', '.join(missing)}")
    if extra := sorted(value.keys() - keys):
        raise ValueError(f"{what}: unexpected fields: {', '.join(extra)}")
    return value


def _mapping(value: object, what: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{what}: a JSON object required")
    return value


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{what}: a list required")
    return value


def _str(value: object, what: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{what}: a string required")
    return value


def _strings(value: object, what: str) -> tuple[str, ...]:
    return tuple(_str(item, what) for item in _list(value, what))


def _int(value: object, what: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{what}: an integer required")
    return value


def _bool(value: object, what: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{what}: true or false required")
    return value


def _decimal(value: object, what: str) -> Decimal:
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f'{what}: a plain decimal string required, such as "104.50"')
    return Decimal(value)


def _date(value: object, what: str) -> date:
    text = _str(value, what)
    try:
        if _DATE.fullmatch(text) is None:
            raise ValueError(text)
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{what}: a YYYY-MM-DD date required") from exc


def _sha(value: object, what: str) -> str:
    if not _is_sha(value):
        raise ValueError(f"{what}: a SHA-256 of 64 lowercase hex required")
    return str(value)


def _path(value: object, what: str) -> str:
    """A canonical repository-relative POSIX path, as ``scripts/trial_register`` takes."""
    text = _str(value, what)
    path = PurePosixPath(text)
    if (
        not text.strip()
        or "\\" in text
        or ":" in text
        or path.is_absolute()
        or ".." in path.parts
        or str(path) != text
        or text == "."
    ):
        raise ValueError(f"{what}: a canonical relative repository path required, got {text!r}")
    return text


def _file_pin(value: object, what: str) -> FilePin:
    doc = _object(value, _PIN_KEYS, what)
    return FilePin(_path(doc["path"], f"{what} path"), _sha(doc["sha256"], f"{what} sha256"))


def _file_pins(value: object, what: str) -> tuple[FilePin, ...]:
    """A ``{path: sha256}`` object as file pins sorted by path."""
    return tuple(
        FilePin(_path(path, what), _sha(sha, f"{what} {path}"))
        for path, sha in sorted(_mapping(value, what).items())
    )
