"""V4.0's synthetic worlds for the step-4b rehearsal and timing runs, the stand-in picks of the
rehearsal's V3 arm, the rehearsal's forced outcomes and its scenario checks.

``.github/workflows/v4-run.yml`` (modes ``rehearsal`` and ``timing``) runs it on GitHub's machines
(no heavy work runs on the owner's PC). Both worlds are synthetic (``crypto_grid_bot.v4.synthetic``)
and never hold a real price: their data pack's ``config_sha256`` is ``CONFIG_SHA256``, which no real
config has. No market data from 2025 onward is executed before the registered run (v4-d03).

``world --scale {rehearsal,timing} --out O``:

1. refuses an ``O`` that exists (nothing is written);
2. creates ``O`` and writes the world's data pack to ``O/v4data/`` (``synthetic.write_world``, the
   same files as ``scripts/v4_data.py``) and, for the rehearsal scale only, V3's input pack to
   ``O/v3pack/v3-input.pack.json.gz`` (``combined.driver.v3_pack.write_v3_pack``, over
   ``rehearsal_v3_fields``);
3. for the rehearsal scale only, writes ``O/world.tar``: the world's git repository, built from
   this checkout (``CHECKOUT``) by ``v4_registration.build_rehearsal_repo``, whose run manifest
   pins the world's own data (``REHEARSAL_CONFIG_PATH`` and the data pack's four pins) and V3
   pack, under the folder ``repo/`` (Ruling W3: the rehearsal gates it exactly as a registered
   run is gated; ``tar -xf O/world.tar -C O`` gives ``O/repo``);
4. writes ``O/rehearsal.json`` last, as canonical JSON (``combined.artifacts._canonical``) created
   exclusively: ``format`` (``WORLD_FORMAT``), ``scale``, ``data`` (``run.data_record`` of the
   written world: the data pack's pins), ``v3_pack_sha256`` (the pack's pin; null for the timing
   scale) and ``registration_sha256`` (the SHA-256 of ``world.tar``'s registration file, which the
   rehearsal's gate is given; null for the timing scale, which is not gated);
5. removes ``O`` again if anything failed.

The ``rehearsal`` scale is ``rehearsal_world`` (four coins, 2020-09 to 2025-03); the ``timing``
scale is ``timing_world`` at its defaults, 80 coins and about 7 million hourly rows, which is
heavy: only GitHub's machines write it.

``picks --world O --out P``: V3's selector trains over V3's four-year walk-forward, which is far too
long for a rehearsal, so this runs ``scripts/v4_v3_cell.py picks`` with that one computation
replaced (``baseline_v3.run_walk_forward``). The stand-in records two training attempts around one
short frozen replay, as ``scripts/v31_smoke.py`` does, and returns ``REHEARSAL_PICKS``. The original
is restored afterwards, whatever happens. It refuses, writing nothing, unless ``O/rehearsal.json``
reads (``read_world``), names the rehearsal scale and a V3 pack pin that is not V3.1's registered
pin (``v4_v3_pack.EXPECTED_PACK_SHA256``), and the pack at ``O/v3pack/`` hashes to that pin.
Then it writes ``P/v3_picks.json`` as ``v4_v3_cell.py`` does.

``force --world O --kind K --out F [--picks P --picks-sha256 T]`` (Ruling W3) makes one stop
outcome that a synthetic world does not produce by itself, through the real cell CLIs. It refuses,
writing nothing, unless ``O/rehearsal.json`` reads and names the rehearsal scale and synthetic data
(its ``config_sha256`` is ``CONFIG_SHA256``), ``O/v4data/data.json`` is synthetic too
(``v4_run_guard.check_synthetic_data``) and holds those pins, and, for a v3 kind, the world's V3
pack is not V3.1's registered one and ``--picks`` and ``--picks-sha256`` are given (and only
then). While the cell runs, one name is replaced (``forcing``); the original is restored
afterwards, whatever happens:

- ``liquidated``: ``run.liquidated`` returns True for the first mark at or after ``FORCE_FROM_MS``;
- ``limit_unrestorable``: ``run.ceiling_breached`` returns True at every check at or after
  ``FORCE_FROM_MS``, so the ceiling's cut cannot restore it;
- ``accounting_failure``: ``run._audit_failure`` returns ``wallet`` for the first audit at or
  after ``FORCE_FROM_MS``;
- ``engine_error``: ``run._hourly_record`` raises ``RuntimeError("forced")`` for the first hour at
  or after ``FORCE_FROM_MS``;
- ``v3_stop`` and ``v3_accounting``: the result returned through ``v3_as_built.replay_v3_baseline``
  gets the stop status ``forced`` (not ``liquidation``), or ``accounting_explained`` False.

The engine's predicates are given a mark or an audit, not an hour, so a forced one reads the hour
from the engine itself: the ``_hour_ms`` of the cell state whose method called it (``_engine_hour``;
every caller in ``run.py`` is such a method). ``FORCE_FROM_MS`` is looked up as the cell runs.
Then ``v4_cell.main run`` (the V4 kinds, cell ``v4_main-1000-1x``) or ``v4_v3_cell.main run`` (the
v3 kinds, ``FORCED_CELL``) writes the cell into ``F/<cell id>/``, its standard output discarded
(it names the outcome). The summary is read back, and the forced name must have fired and the
summary be the forced outcome: ``liquidated``; ``limit_unrestorable`` with reason ``ceiling``;
``accounting_failure`` of identity ``wallet``; ``engine_error`` of type ``RuntimeError``, message
``forced``; for these four the stop's hour (``stop_ms``, or ``hour_ms`` for a failure) at or after
``FORCE_FROM_MS``. ``v3_stop`` must be an ``engine_error`` of type ``V3Stop`` (message ``forced``)
and ``v3_accounting`` one of type ``V3Accounting`` (message ``accounting_explained``). Otherwise
force exits 1.

``scenarios --base S --forced F --out X`` turns a base set and the forced cells into the eleven
scenarios of ``SCENARIOS``, each with a known expected verdict (Rulings V1 to V3 and V10). ``S``
holds the downloaded ``v4-summary-*`` folders, each of regular files only; ``F`` holds the six
forced cells as ``force`` lays them out, ``F/<kind>/<cell id>/`` with its ``summary.json`` and
``receipt.json``. It refuses an ``X`` that exists, a base without a folder a scenario changes
(``v4-summary-<cell>-attempt-1``) and a forced set without one of its cells, writing nothing.
Each scenario is a folder ``X/<name>/`` of copies of ``S``'s folders with its change:

- ``base``: none; expected ``pass or fail`` with no cell missing or refused;
- ``main_liquidated``, ``main_limit``, ``main_accounting``: ``v4_main-1000-1x``'s folder holds the
  forced ``liquidated``, ``limit_unrestorable`` or ``accounting_failure`` cell; ``fail``;
- ``main_engine_error``: likewise, the forced ``engine_error`` cell; ``incomplete``;
- ``hold_missing``: ``hold_universe-10000-1x``'s folder is removed; ``incomplete``;
- ``v3_stop``, ``v3_accounting``: ``v3_as_built-1000-1x``'s folder holds the forced cell of that
  kind; ``incomplete``;
- ``rerun``: ``v4_main-10000-2x``'s folder is renamed ``-attempt-2``; ``incomplete``;
- ``relabelled``: ``hold_universe-1000-1x``'s files are copied into ``hold_universe-10000-1x``'s
  folder; ``incomplete``;
- ``liquidated_and_missing``: ``main_liquidated``'s change and ``hold_missing``'s; ``fail``.

Then it writes ``X/scenarios.json`` (``SCENARIOS_FILE``), ``{name: expected}`` as canonical JSON,
last. The verdict step (``scripts/v4_verdict.py``) then judges each ``X/<name>/`` into
``V/<name>/``.

``check --scenarios X --verdicts V`` reads ``X/scenarios.json``, which must be ``SCENARIOS``, and
each scenario's ``V/<name>/verdict.json``. A scenario is as expected only if the verdict's outcome
is the expected one and its ``missing`` cells and refused ``(folder, step)`` pairs are exactly
those the scenario's change implies (``implied``, from the same table): none for ``base`` and for
a forced cell (which must therefore be accepted), the cell for a removal, the cell and its
``-attempt-2`` folder at step ``rerun`` for a re-run, the target cell and its folder at step
``cell`` for a relabelling, and the union for a combination. So an ``incomplete`` reached
through another refusal (a forced cell refused, say) is not as expected. A verdict file that
cannot be read, or is not a rehearsal's verdict, is not as expected either.

**Exit status**: 0 once the world (or the picks, the forced cell, the scenarios) is written, and
for ``check`` when every scenario is as expected; 1 otherwise; 2 for bad arguments (argparse's
own).

**Output**: one line on standard output, counts, names and pins only, never a price (owner rule:
public logs); for ``world``, the scale, the coin count, the hourly row count and the pins; for
``force``, the forced cell and its summary's SHA-256; for ``check``, one line per scenario,
``<name>: as expected`` or ``<name>: NOT as expected``. Neither ``force`` nor ``check`` ever prints
a cell's outcome or a verdict. Standard error never echoes an exception's text
(``v4_cell._fail``): a failure is one line naming the command, the step and the exception's type.
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import FrameType, MappingProxyType, ModuleType, SimpleNamespace
from typing import Any, NoReturn

from v4_cell import _fail, _say
from v4_cell import main as v4_cell_main
from v4_registration import RunManifest, build_rehearsal_repo
from v4_run_guard import check_synthetic_data
from v4_v3_cell import main as v3_cell_main
from v4_v3_pack import EXPECTED_PACK_SHA256, PACK_FILE

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.combined.baseline_records import BaselineEvidence
from crypto_grid_bot.combined.driver.v3_pack import write_v3_pack
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.v4.engine import run, v3_as_built
from crypto_grid_bot.v4.engine.ledger import Audit, Mark
from crypto_grid_bot.v4.engine.market import DataPins
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    CEILING,
    ENGINE_ERROR,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
    RECEIPT_FILE,
    WALLET_IDENTITY,
    data_record,
)
from crypto_grid_bot.v4.engine.summary import SUMMARY_FILE
from crypto_grid_bot.v4.engine.v3_as_built import (
    ACCOUNTING_FLAGS,
    V3_ACCOUNTING,
    V3_START_MS,
    V3_STOP,
)
from crypto_grid_bot.v4.synthetic import (
    CONFIG_SHA256,
    DAY,
    REHEARSAL_PICKS,
    read_data_json,
    rehearsal_v3_fields,
    rehearsal_world,
    timing_world,
    write_world,
)
from crypto_grid_bot.v4.verdict.inputs import MAX_SUMMARY_BYTES
from crypto_grid_bot.v4.verdict.report import VERDICT_FORMAT, read_canonical_json

WORLD_FILE = "rehearsal.json"
WORLD_FORMAT = "v4-rehearsal-world-1"
DATA_DIR = "v4data"
V3_DIR = "v3pack"
WORLD_TAR = "world.tar"
REPO_DIR = "repo"  # world.tar's one folder: the world's repository
SCALES = ("rehearsal", "timing")
# The checkout whose tracked code world.tar's repository commits at its code pin: this one.
CHECKOUT = Path(__file__).resolve().parents[1]
# The run manifest's data config path in world.tar: the registered run's (scripts/v4_data.py's
# default). The world's config pin is CONFIG_SHA256, which no file hashes to, so a registered
# guard (v4_run_guard.py --manifest) never accepts the world; a rehearsal's is --synthetic.
REHEARSAL_CONFIG_PATH = "config/v4_data.json"

# The forced outcomes (Ruling W3), the first hour a forced fault may hit, and the forced cells.
FORCED = (
    "liquidated",
    "limit_unrestorable",
    "accounting_failure",
    "engine_error",
    "v3_stop",
    "v3_accounting",
)
FORCE_FROM_MS = month_bounds_ms("2024-06")[0]  # the first hour a forced fault may hit
FORCED_CELL: Mapping[str, str] = MappingProxyType(
    {
        "v3_stop": "v3_as_built-1000-1x",
        "v3_accounting": "v3_as_built-1000-1x",
    }
)  # others: MAIN_CELL
MAIN_CELL = "v4_main-1000-1x"
FORCED_MESSAGE = "forced"  # the forced RuntimeError's message
FORCED_V3_STATUS = "forced"  # the forced V3 stop's status, not V3's "liquidation"

# The scenarios (Rulings V1 to V3, V10): name -> the verdict's expected outcome.
# The base's expected verdict: a pass or a fail, with no cell missing or refused.
BASE_EXPECTED = "pass or fail"
SCENARIOS_FILE = "scenarios.json"
VERDICT_FILE = "verdict.json"  # what scripts/v4_verdict.py writes for each scenario

_STAGING = "staging"  # write_world writes <root>/data; the world's folder is renamed from there
_REPO_STAGING = "repo-staging"  # build_rehearsal_repo writes <root>/repo; it is tarred from there
_MAX_WORLD_BYTES = 4096
_MAX_PACK_BYTES = 1 << 28  # the V3 pack's JSON is about 15 MB; refuse anything near 256 MiB
_MAX_SCENARIOS_BYTES = 4096
_MAX_VERDICT_BYTES = 1 << 26  # a verdict.json holds counts and a few lists of hours
_HEX64 = re.compile("[0-9a-f]{64}")
_MONTH = re.compile("[0-9]{4}-(0[1-9]|1[0-2])")
_WORLD_KEYS = frozenset({"format", "scale", "data", "v3_pack_sha256", "registration_sha256"})
_DATA_KEYS = frozenset({"config_sha256", "end_month", "daily_sha256", "index_sha256"})


# ---- rehearsal.json ------------------------------------------------------------------------------


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _refuse_number(text: str) -> NoReturn:
    raise ValueError(f"{WORLD_FILE}: a float or a non-finite number, {text}")


def _loads(raw: bytes) -> object:
    """Strict JSON: UTF-8, no duplicate keys, no floats, no NaN or infinities."""
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_refuse_number,
            parse_constant=_refuse_number,
        )
    except UnicodeDecodeError:
        raise ValueError(f"{WORLD_FILE}: not UTF-8") from None
    except json.JSONDecodeError:
        raise ValueError(f"{WORLD_FILE}: not JSON") from None


def _is_hex64(value: object) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def read_world(root: Path) -> dict[str, object]:
    """The ``rehearsal.json`` of the world folder ``root``, refused unless it is exactly what
    ``world`` writes: canonical JSON with unique keys and the five keys ``format``
    (``WORLD_FORMAT``), ``scale`` (``rehearsal`` or ``timing``), ``data`` (``run.data_record``'s
    four keys: a config digest, an end month and the two pack pins), ``v3_pack_sha256`` and
    ``registration_sha256`` (each 64 lowercase hex digits or null; null for a timing world's V3
    pack, which has none). A missing file is refused too."""
    path = Path(root) / WORLD_FILE
    if not path.is_file():
        raise ValueError(f"{WORLD_FILE}: missing")
    if path.stat().st_size > _MAX_WORLD_BYTES:
        raise ValueError(f"{WORLD_FILE}: larger than {_MAX_WORLD_BYTES} bytes")
    raw = path.read_bytes()
    document = _loads(raw)
    if _canonical(document) != raw:
        raise ValueError(f"{WORLD_FILE}: not canonical JSON")
    if not isinstance(document, dict) or set(document) != _WORLD_KEYS:
        raise ValueError(f"{WORLD_FILE}: the keys are not {sorted(_WORLD_KEYS)}")
    if document["format"] != WORLD_FORMAT:
        raise ValueError(f"{WORLD_FILE}: the format is not {WORLD_FORMAT}")
    if document["scale"] not in SCALES:
        raise ValueError(f"{WORLD_FILE}: the scale is not one of {SCALES}")
    data = document["data"]
    if (
        not isinstance(data, dict)
        or set(data) != _DATA_KEYS
        or not isinstance(data["config_sha256"], str)
        or not data["config_sha256"]
        or not isinstance(data["end_month"], str)
        or _MONTH.fullmatch(data["end_month"]) is None
        or not _is_hex64(data["daily_sha256"])
        or not _is_hex64(data["index_sha256"])
    ):
        raise ValueError(f"{WORLD_FILE}: data is not a data record")
    for key in ("v3_pack_sha256", "registration_sha256"):
        if document[key] is not None and not _is_hex64(document[key]):
            raise ValueError(f"{WORLD_FILE}: {key} is neither a SHA-256 nor null")
    if document["scale"] == "timing" and document["v3_pack_sha256"] is not None:
        raise ValueError(f"{WORLD_FILE}: a timing world has no V3 pack")
    return document


# ---- world ---------------------------------------------------------------------------------------


def _writable(function: Callable[..., object], name: str, exc: BaseException) -> None:
    """``shutil.rmtree``'s handler: make the file writable and try again (git writes its objects
    read-only, which Windows does not delete as they are)."""
    os.chmod(name, stat.S_IWRITE)
    function(name)


def _remove_tree(path: Path) -> None:
    shutil.rmtree(path, onexc=_writable)


def _anonymous(member: tarfile.TarInfo) -> tarfile.TarInfo:
    """A member of world.tar without the builder's user and group."""
    member.uid = member.gid = 0
    member.uname = member.gname = ""
    return member


def _world_repository(out: Path, pins: DataPins, v3_pin: str) -> str:
    """Write ``out/world.tar`` (module docstring, ``world`` step 3) and return the SHA-256 of its
    registration file."""
    manifest = RunManifest(
        {
            "config_path": REHEARSAL_CONFIG_PATH,
            "config_sha256": pins.config_sha256,
            "end_month": pins.end_month,
            "daily_sha256": pins.daily_sha256,
            "index_sha256": pins.index_sha256,
        },
        v3_pin,
    )
    staging = out / _REPO_STAGING
    repo, registration = build_rehearsal_repo(staging, CHECKOUT, manifest)
    with tarfile.open(out / WORLD_TAR, "x") as tar:
        tar.add(repo, arcname=REPO_DIR, filter=_anonymous)
    _remove_tree(staging)
    return registration


def _build(out: Path, scale: str) -> str:
    """Write the world of ``scale`` into the new folder ``out``; its summary line."""
    world = rehearsal_world() if scale == "rehearsal" else timing_world()
    staging = out / _STAGING
    write_world(staging, world).rename(out / DATA_DIR)
    staging.rmdir()
    header = read_data_json(out / DATA_DIR)
    packs = header["packs"]
    daily, index = packs["daily"]["sha256"], packs["hourly_index"]["sha256"]
    pins = DataPins(header["config_sha256"], header["end_month"], daily, index)
    v3_pin: str | None = None
    registration: str | None = None
    if scale == "rehearsal":
        (out / V3_DIR).mkdir()
        v3_pin = write_v3_pack(rehearsal_v3_fields(), out / V3_DIR / PACK_FILE)
        registration = _world_repository(out, pins, v3_pin)
    document = {
        "format": WORLD_FORMAT,
        "scale": scale,
        "data": data_record(pins),
        "v3_pack_sha256": v3_pin,
        "registration_sha256": registration,
    }
    with (out / WORLD_FILE).open("xb") as handle:  # last: a folder with it is a whole world
        handle.write(_canonical(document))
    return (
        f"v4_rehearsal world: scale {scale}, {header['coin_packs']} coins, "
        f"{header['hourly_rows']} hourly rows, daily sha256 {daily}, index sha256 {index}, "
        f"v3 pack sha256 {v3_pin or 'none'}, registration sha256 {registration or 'none'}"
    )


def world_command(args: argparse.Namespace) -> int:
    """The ``world`` command: a world folder, whole or not at all (module docstring)."""
    name = "v4_rehearsal world"
    out = Path(args.out)
    if out.exists() or out.is_symlink():
        return _fail(name, "refused: the output folder already exists")
    try:
        out.mkdir(parents=True)
    except OSError as exc:
        return _fail(name, "creating the output folder failed", exc)
    try:
        line = _build(out, args.scale)
    except BaseException as exc:
        with contextlib.suppress(OSError):
            _remove_tree(out)  # the folder did not exist before this run
        if not isinstance(exc, Exception):
            raise
        return _fail(name, "writing the world failed; the folder is removed", exc)
    _say(line)
    return 0


# ---- picks ---------------------------------------------------------------------------------------


def _walk_forward(
    decisions: DailyDecisions,
    filters: Mapping[str, OrderFilters],
    hourly_bars: Mapping[str, Sequence[Kline]],
    rates: Mapping[int, Mapping[str, Decimal]],
    *,
    record: Callable[[Attempt], None],
) -> SimpleNamespace:
    """Stands in for V3's frozen walk-forward (its calendar is fixed to 2020-2024): records a
    started and a finished training attempt around one short frozen replay, under a fresh run-id
    prefix as V3's own does, and returns ``REHEARSAL_PICKS``."""
    run_id = f"{uuid.uuid4().hex}-train-2021-06-R2L"
    start, end = V3_START_MS - 2 * DAY, V3_START_MS
    schedule = ((start, "R2L"),)
    record(
        Attempt(
            run_id,
            "training",
            "R2L",
            start,
            end,
            None,
            None,
            state="started",
            pick_schedule=schedule,
        )
    )
    result = replay_window(
        decisions,
        filters,
        hourly_bars,
        rates,
        start,
        end,
        dict(schedule),
        multiple=2,
        cost_multiple=1,
    )
    record(Attempt(run_id, "training", "R2L", start, end, result, None, pick_schedule=schedule))
    return SimpleNamespace(picks=dict(REHEARSAL_PICKS), out_of_sample=result)


@contextmanager
def stand_in_walk_forward() -> Iterator[None]:
    """Replace V3's walk-forward (``baseline_v3.run_walk_forward``, which ``selector_picks``
    calls) while the block runs; the original is restored afterwards, whatever happens."""
    namespace = vars(baseline_v3)
    original = namespace["run_walk_forward"]
    namespace["run_walk_forward"] = _walk_forward
    try:
        yield
    finally:
        namespace["run_walk_forward"] = original


def _pack_pin(pack: Path) -> str:
    """The pin of a V3 pack: the SHA-256 of the canonical JSON the file compresses."""
    digest, size = hashlib.sha256(), 0
    with gzip.open(pack, "rb") as stream:
        while chunk := stream.read(1 << 20):
            size += len(chunk)
            if size > _MAX_PACK_BYTES:
                raise ValueError(f"{pack.name}: larger than {_MAX_PACK_BYTES} bytes")
            digest.update(chunk)
    return digest.hexdigest()


def picks_command(args: argparse.Namespace) -> int:
    """The ``picks`` command: the rehearsal's V3 picks, from the stand-in (module docstring)."""
    name = "v4_rehearsal picks"
    root = Path(args.world)
    try:
        world = read_world(root)
    except Exception as exc:
        return _fail(name, f"reading {WORLD_FILE} failed", exc)
    pin = world["v3_pack_sha256"]
    if world["scale"] != "rehearsal" or not isinstance(pin, str):
        return _fail(name, f"refused: {WORLD_FILE} does not name a rehearsal world's V3 pack")
    if pin == EXPECTED_PACK_SHA256:
        return _fail(name, "refused: the world names V3.1's registered pack")
    pack = root / V3_DIR / PACK_FILE
    try:
        actual = _pack_pin(pack)
    except Exception as exc:
        return _fail(name, "hashing the V3 pack failed", exc)
    if actual != pin:
        return _fail(name, f"refused: the V3 pack is not the one {WORLD_FILE} names")
    with stand_in_walk_forward():
        return v3_cell_main(
            ["picks", "--pack", str(pack), "--pack-sha256", pin, "--out", str(args.out)]
        )


# ---- force ---------------------------------------------------------------------------------------

_V3_KINDS = frozenset({"v3_stop", "v3_accounting"})
# The name each kind replaces while its cell runs (module docstring).
_FORCE_POINTS: Mapping[str, tuple[ModuleType, str]] = MappingProxyType(
    {
        "liquidated": (run, "liquidated"),
        "limit_unrestorable": (run, "ceiling_breached"),
        "accounting_failure": (run, "_audit_failure"),
        "engine_error": (run, "_hourly_record"),
        "v3_stop": (v3_as_built, "replay_v3_baseline"),
        "v3_accounting": (v3_as_built, "replay_v3_baseline"),
    }
)
# What a forced cell's summary must say (module docstring), and which of its hours must be at or
# after FORCE_FROM_MS (None: a v3 kind, whose result is changed after V3's replay).
_WANTED: Mapping[str, tuple[Mapping[str, object], str | None]] = MappingProxyType(
    {
        "liquidated": ({"outcome": LIQUIDATED}, "stop_ms"),
        "limit_unrestorable": ({"outcome": LIMIT_UNRESTORABLE, "reason": CEILING}, "stop_ms"),
        "accounting_failure": (
            {"outcome": ACCOUNTING_FAILURE, "identity": WALLET_IDENTITY},
            "hour_ms",
        ),
        "engine_error": (
            {"outcome": ENGINE_ERROR, "type": RuntimeError.__name__, "message": FORCED_MESSAGE},
            "hour_ms",
        ),
        "v3_stop": ({"outcome": ENGINE_ERROR, "type": V3_STOP, "message": FORCED_V3_STATUS}, None),
        "v3_accounting": (
            {"outcome": ENGINE_ERROR, "type": V3_ACCOUNTING, "message": ACCOUNTING_FLAGS[0]},
            None,
        ),
    }
)
_HourlyRecord = Callable[[int, tuple[Mark, bool] | None, Mark, Audit], dict[str, object]]


def forced_cell(kind: str) -> str:
    """The cell ``kind`` forces: ``FORCED_CELL``'s for a v3 kind, ``MAIN_CELL`` for the others."""
    if kind not in FORCED:
        raise ValueError(f"unknown forced kind {kind!r:.40}: one of {', '.join(FORCED)}")
    return FORCED_CELL.get(kind, MAIN_CELL)


@dataclass(slots=True)
class Fired:
    """How many times a forced name changed what the engine saw."""

    count: int = 0


def _engine_hour(frame: FrameType | None) -> int:
    """The hour the V4 engine is in when it calls a forced predicate: the ``_hour_ms`` of the cell
    state whose method made the call, ``frame`` (every call of ``liquidated``, ``ceiling_breached``
    and ``_audit_failure`` in ``run.py`` is in a method of ``run._CellState``). Any other caller
    is a RuntimeError: inside the cell's loop it is an ``engine_error``, which ``force`` then
    refuses as not the forced outcome."""
    state = None if frame is None else frame.f_locals.get("self")
    if not isinstance(state, run._CellState):
        raise RuntimeError("a forced name was called outside a cell's hour")
    return state._hour_ms


def _forced_liquidated(original: Callable[[Mark], bool], fired: Fired) -> Callable[[Mark], bool]:
    def liquidated(mark: Mark) -> bool:
        if not fired.count and _engine_hour(sys._getframe(1)) >= FORCE_FROM_MS:
            fired.count += 1
            return True
        return original(mark)

    return liquidated


def _forced_ceiling(original: Callable[[Mark], bool], fired: Fired) -> Callable[[Mark], bool]:
    def ceiling_breached(mark: Mark) -> bool:
        if _engine_hour(sys._getframe(1)) >= FORCE_FROM_MS:
            fired.count += 1
            return True
        return original(mark)

    return ceiling_breached


def _forced_audit(
    original: Callable[[Audit], str | None], fired: Fired
) -> Callable[[Audit], str | None]:
    def audit_failure(audit: Audit) -> str | None:
        if not fired.count and _engine_hour(sys._getframe(1)) >= FORCE_FROM_MS:
            fired.count += 1
            return WALLET_IDENTITY
        return original(audit)

    return audit_failure


def _forced_hourly(original: _HourlyRecord, fired: Fired) -> _HourlyRecord:
    def hourly_record(
        h: int, open_: tuple[Mark, bool] | None, mark: Mark, audit: Audit
    ) -> dict[str, object]:
        if h >= FORCE_FROM_MS:
            fired.count += 1
            raise RuntimeError(FORCED_MESSAGE)
        return original(h, open_, mark, audit)

    return hourly_record


def _forced_v3(
    original: Callable[..., BaselineEvidence], fired: Fired, *, stop: bool
) -> Callable[..., BaselineEvidence]:
    def replay_v3_baseline(*args: Any, **kwargs: Any) -> BaselineEvidence:
        evidence = original(*args, **kwargs)
        fired.count += 1
        if stop:
            return replace(evidence, status=FORCED_V3_STATUS)
        return replace(evidence, accounting_explained=False)

    return replay_v3_baseline


def _stand_in(kind: str, original: Any, fired: Fired) -> object:
    """The forced replacement of ``kind``'s name (module docstring)."""
    if kind == "liquidated":
        return _forced_liquidated(original, fired)
    if kind == "limit_unrestorable":
        return _forced_ceiling(original, fired)
    if kind == "accounting_failure":
        return _forced_audit(original, fired)
    if kind == "engine_error":
        return _forced_hourly(original, fired)
    return _forced_v3(original, fired, stop=kind == "v3_stop")


@contextmanager
def forcing(kind: str) -> Iterator[Fired]:
    """Replace the one name ``kind`` forces (``_FORCE_POINTS``) while the block runs, yielding
    how often it fired; the original is restored afterwards, whatever happens."""
    if kind not in FORCED:
        raise ValueError(f"unknown forced kind {kind!r:.40}: one of {', '.join(FORCED)}")
    module, name = _FORCE_POINTS[kind]
    namespace = vars(module)
    original = namespace[name]
    fired = Fired()
    namespace[name] = _stand_in(kind, original, fired)
    try:
        yield fired
    finally:
        namespace[name] = original


def _is_forced(kind: str, cell: str, summary: object) -> bool:
    """Whether ``summary`` is ``cell``'s and the forced outcome of ``kind`` (``_WANTED``)."""
    if not isinstance(summary, dict):
        return False
    record = summary.get("cell")
    if not isinstance(record, dict) or record.get("id") != cell:
        return False
    fields, hour_key = _WANTED[kind]
    if any(summary.get(key) != value for key, value in fields.items()):
        return False
    if hour_key is None:
        return True
    hour = summary.get(hour_key)
    return type(hour) is int and hour >= FORCE_FROM_MS


def _cell_argv(cell: str) -> list[str]:
    """``--capital`` and ``--costs`` of a cell id ``<arm>-<capital>-<multiple>x``."""
    _, capital, multiple = cell.rsplit("-", 2)
    return ["--capital", capital, "--costs", multiple.removesuffix("x")]


def force_command(args: argparse.Namespace) -> int:
    """The ``force`` command: one forced outcome through the real cell CLI (module docstring)."""
    name = "v4_rehearsal force"
    kind: str = args.kind
    v3 = kind in _V3_KINDS
    given = (args.picks is not None, args.picks_sha256 is not None)
    if v3 and not all(given):
        return _fail(name, "refused: a v3 kind needs --picks and --picks-sha256")
    if not v3 and any(given):
        return _fail(name, "refused: --picks and --picks-sha256 go with a v3 kind")
    root = Path(args.world)
    try:
        world = read_world(root)
    except Exception as exc:
        return _fail(name, f"reading {WORLD_FILE} failed", exc)
    if world["scale"] != "rehearsal":
        return _fail(name, f"refused: {WORLD_FILE} is not a rehearsal world's")
    data = world["data"]
    if not isinstance(data, dict) or data["config_sha256"] != CONFIG_SHA256:
        return _fail(name, f"refused: {WORLD_FILE} names data that is not synthetic")
    try:
        pins = check_synthetic_data(root / DATA_DIR)
    except Exception as exc:
        return _fail(name, "refused: the data pack is not synthetic", exc)
    if pins != data:
        return _fail(name, f"refused: the data pack is not the one {WORLD_FILE} names")
    cell = forced_cell(kind)
    out = Path(args.out)
    runner: Callable[[Sequence[str] | None], int]
    if v3:
        pin = world["v3_pack_sha256"]
        if not isinstance(pin, str):
            return _fail(name, f"refused: {WORLD_FILE} names no V3 pack")
        if pin == EXPECTED_PACK_SHA256:
            return _fail(name, "refused: the world names V3.1's registered pack")
        pack = root / V3_DIR / PACK_FILE
        argv = ["run", "--pack", str(pack), "--pack-sha256", pin]
        argv += ["--picks", str(args.picks), "--picks-sha256", str(args.picks_sha256)]
        runner = v3_cell_main
    else:
        argv = ["run", "--data", str(root / DATA_DIR), "--arm", cell.rsplit("-", 2)[0]]
        runner = v4_cell_main
    argv += [*_cell_argv(cell), "--out", str(out)]
    label = f"{name}: {cell}"
    try:
        # The cell's own line names its outcome: it is discarded (owner rule: public logs).
        with forcing(kind) as fired, contextlib.redirect_stdout(io.StringIO()):
            code = runner(argv)
    except Exception as exc:
        return _fail(label, "the cell did not run", exc)
    if code != 0:
        return _fail(label, "the cell's CLI wrote no summary")
    path = out / cell / SUMMARY_FILE
    try:
        summary = read_canonical_json(path, MAX_SUMMARY_BYTES, f"the forced {SUMMARY_FILE}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception as exc:
        return _fail(label, f"reading {SUMMARY_FILE} back failed", exc)
    if not fired.count or not _is_forced(kind, cell, summary):
        return _fail(label, "NOT as expected")
    _say(f"{label}, summary sha256 {digest}: as expected")
    return 0


# ---- scenarios -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Swap:
    """The forced cell of ``kind`` in its cell's folder."""

    kind: str


@dataclass(frozen=True, slots=True)
class _Drop:
    """``cell``'s folder removed."""

    cell: str


@dataclass(frozen=True, slots=True)
class _Rerun:
    """``cell``'s folder renamed ``-attempt-2``."""

    cell: str


@dataclass(frozen=True, slots=True)
class _Relabel:
    """``source``'s files in ``target``'s folder."""

    source: str
    target: str


_Change = _Swap | _Drop | _Rerun | _Relabel
_HOLD = "hold_universe-10000-1x"
_HOLD_SMALL = "hold_universe-1000-1x"
_RERUN = "v4_main-10000-2x"
# The scenario table (module docstring): name -> (the expected verdict, the changes to the base).
_TABLE: Mapping[str, tuple[str, tuple[_Change, ...]]] = MappingProxyType(
    {
        "base": (BASE_EXPECTED, ()),
        "main_liquidated": ("fail", (_Swap("liquidated"),)),
        "main_limit": ("fail", (_Swap("limit_unrestorable"),)),
        "main_accounting": ("fail", (_Swap("accounting_failure"),)),
        "main_engine_error": ("incomplete", (_Swap("engine_error"),)),
        "hold_missing": ("incomplete", (_Drop(_HOLD),)),
        "v3_stop": ("incomplete", (_Swap("v3_stop"),)),
        "v3_accounting": ("incomplete", (_Swap("v3_accounting"),)),
        "rerun": ("incomplete", (_Rerun(_RERUN),)),
        "relabelled": ("incomplete", (_Relabel(_HOLD_SMALL, _HOLD),)),
        "liquidated_and_missing": ("fail", (_Swap("liquidated"), _Drop(_HOLD))),
    }
)
SCENARIOS: Mapping[str, str] = MappingProxyType(
    {scenario: expected for scenario, (expected, _) in _TABLE.items()}
)  # name -> expected verdict outcome
# The base folders the scenarios change: each must be there, at its first attempt.
_CHANGED_CELLS = (MAIN_CELL, FORCED_CELL["v3_stop"], _HOLD, _HOLD_SMALL, _RERUN)

_Layout = dict[str, dict[str, Path]]  # a set of summaries: folder name -> file name -> source


def _folder(cell: str, attempt: int = 1) -> str:
    return f"v4-summary-{cell}-attempt-{attempt}"


def _files(folder: Path) -> dict[str, Path]:
    """A folder's files, refused unless each is a regular file (not a link)."""
    files: dict[str, Path] = {}
    for item in sorted(folder.iterdir()):
        if item.is_symlink() or not item.is_file():
            raise ValueError(f"{folder.name:.80}/{item.name:.80} is not a regular file")
        files[item.name] = item
    return files


def _read_base(base: Path) -> _Layout:
    """The base set: each folder of ``base`` and its files; every entry must be a folder (not a
    link) of regular files, and each folder a scenario changes must be there."""
    layout: _Layout = {}
    for folder in sorted(base.iterdir()):
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError(f"the base holds {folder.name:.80}, which is not a folder")
        layout[folder.name] = _files(folder)
    for cell in _CHANGED_CELLS:
        if _folder(cell) not in layout:
            raise ValueError(f"the base has no folder {_folder(cell)}")
    return layout


def _read_forced(forced: Path) -> dict[str, dict[str, Path]]:
    """The forced cells, ``forced/<kind>/<cell id>/``: each one's summary and receipt."""
    cells: dict[str, dict[str, Path]] = {}
    for kind in FORCED:
        folder = forced / kind / forced_cell(kind)
        files = {name: folder / name for name in (SUMMARY_FILE, RECEIPT_FILE)}
        if any(path.is_symlink() or not path.is_file() for path in files.values()):
            raise ValueError(f"the forced cells have no {kind}/{forced_cell(kind)}")
        cells[kind] = files
    return cells


def _scenario(
    base: _Layout, forced: Mapping[str, dict[str, Path]], changes: Sequence[_Change]
) -> _Layout:
    """The base with ``changes`` applied, in order."""
    layout = dict(base)
    for change in changes:
        match change:
            case _Swap(kind):
                layout[_folder(forced_cell(kind))] = dict(forced[kind])
            case _Drop(cell):
                del layout[_folder(cell)]
            case _Rerun(cell):
                layout[_folder(cell, 2)] = layout.pop(_folder(cell))
            case _Relabel(source, target):
                layout[_folder(target)] = base[_folder(source)]
    return layout


def _write_layout(target: Path, layout: _Layout) -> None:
    target.mkdir()
    for folder, files in sorted(layout.items()):
        (target / folder).mkdir()
        for file, source in files.items():
            shutil.copyfile(source, target / folder / file)


def scenarios_command(args: argparse.Namespace) -> int:
    """The ``scenarios`` command: the eleven scenario folders and their table (module
    docstring), whole or not at all."""
    name = "v4_rehearsal scenarios"
    out = Path(args.out)
    if out.exists() or out.is_symlink():
        return _fail(name, "refused: the output folder already exists")
    try:
        base = _read_base(Path(args.base))
        forced = _read_forced(Path(args.forced))
    except ValueError as exc:
        return _fail(name, f"refused: {exc}")
    except OSError as exc:
        return _fail(name, "reading the base or the forced cells failed", exc)
    try:
        out.mkdir(parents=True)
    except OSError as exc:
        return _fail(name, "creating the output folder failed", exc)
    try:
        for scenario, (_, changes) in _TABLE.items():
            _write_layout(out / scenario, _scenario(base, forced, changes))
        with (out / SCENARIOS_FILE).open("xb") as handle:  # last: a folder with it is whole
            handle.write(_canonical(dict(SCENARIOS)))
    except BaseException as exc:
        with contextlib.suppress(OSError):
            _remove_tree(out)  # the folder did not exist before this run
        if not isinstance(exc, Exception):
            raise
        return _fail(name, "writing the scenarios failed; the folder is removed", exc)
    _say(
        f"{name}: {len(SCENARIOS)} scenarios of {len(base)} base folders and {len(forced)} "
        "forced cells"
    )
    return 0


# ---- check ---------------------------------------------------------------------------------------


def implied(changes: Sequence[_Change]) -> tuple[list[str], list[tuple[str, str]]]:
    """The cells a scenario's ``changes`` leave missing, and the folders they leave refused with
    the step that refuses them, both sorted (Rulings V2, V3): a forced cell in place of a base
    cell leaves neither, so it must be accepted; a removed cell is missing; a re-run cell is
    missing and its ``-attempt-2`` folder refused at ``rerun``; a relabelled cell is missing and
    its folder refused at ``cell``; several changes leave the union of theirs."""
    missing: list[str] = []
    refused: list[tuple[str, str]] = []
    for change in changes:
        match change:
            case _Swap():
                pass
            case _Drop(cell):
                missing.append(cell)
            case _Rerun(cell):
                missing.append(cell)
                refused.append((_folder(cell, 2), "rerun"))
            case _Relabel(_, target):
                missing.append(target)
                refused.append((_folder(target), "cell"))
    return sorted(missing), sorted(refused)


def _note(name: str, scenario: str, why: str) -> None:
    print(f"{name}: {scenario}: {why}", file=sys.stderr, flush=True)


def _refused_pairs(value: object) -> list[tuple[str, str]] | None:
    """A verdict's ``refused`` as sorted ``(folder, step)`` pairs, or None if it is not a list of
    objects with a string folder and step."""
    if not isinstance(value, list):
        return None
    pairs: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        folder, step = item.get("folder"), item.get("step")
        if not isinstance(folder, str) or not isinstance(step, str):
            return None
        pairs.append((folder, step))
    return sorted(pairs)


def _as_expected(
    name: str, scenario: str, path: Path, expected: str, changes: Sequence[_Change]
) -> bool:
    """Whether the verdict at ``path`` is ``expected`` (for ``BASE_EXPECTED``, a pass or a fail)
    for the scenario's own reason: its missing cells and its refused folders and steps are exactly
    those its ``changes`` imply (``implied``), so an outcome reached through another refusal is
    not as expected. A file that cannot be read, that is not a rehearsal's verdict, or whose cells
    are not the scenario's, is not; why is one line on standard error, naming no outcome."""
    try:
        document = read_canonical_json(path, _MAX_VERDICT_BYTES, VERDICT_FILE)
    except ValueError as exc:
        _note(name, scenario, str(exc))
        return False
    verdict = document.get("verdict") if isinstance(document, dict) else None
    judged = document.get("expected") if isinstance(document, dict) else None
    missing = document.get("missing") if isinstance(document, dict) else None
    refused = _refused_pairs(document.get("refused")) if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or document.get("format") != VERDICT_FORMAT
        or not isinstance(verdict, dict)
        or not isinstance(judged, dict)
        or judged.get("mode") != "rehearsal"
        or not isinstance(missing, list)
        or not all(isinstance(cell, str) for cell in missing)
        or refused is None
    ):
        _note(name, scenario, f"{VERDICT_FILE} is not a rehearsal's verdict")
        return False
    if (sorted(missing), refused) != implied(changes):
        _note(name, scenario, "the missing and refused cells are not the scenario's")
        return False
    outcome = verdict.get("outcome")
    if expected == BASE_EXPECTED:
        return outcome in ("pass", "fail")
    return outcome == expected


def check_command(args: argparse.Namespace) -> int:
    """The ``check`` command: every scenario's verdict against its expected one (module
    docstring)."""
    name = "v4_rehearsal check"
    try:
        table = read_canonical_json(
            Path(args.scenarios) / SCENARIOS_FILE, _MAX_SCENARIOS_BYTES, SCENARIOS_FILE
        )
    except ValueError as exc:
        return _fail(name, f"refused: {exc}")
    if table != dict(SCENARIOS):
        return _fail(name, f"refused: {SCENARIOS_FILE} is not this script's table")
    wrong = 0
    for scenario, (expected, changes) in _TABLE.items():
        path = Path(args.verdicts) / scenario / VERDICT_FILE
        right = _as_expected(name, scenario, path, expected, changes)
        _say(f"{scenario}: {'as expected' if right else 'NOT as expected'}")
        wrong += not right
    return 1 if wrong else 0


# ---- the command line ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_rehearsal.py",
        description="The step-4b rehearsal and timing worlds, the rehearsal's V3 picks, its "
        "forced outcomes and its scenario checks (see docstring).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    world = commands.add_parser("world", help="write a synthetic world folder")
    world.add_argument("--scale", choices=SCALES, required=True)
    world.add_argument("--out", type=Path, required=True, help="the new world folder")
    picks = commands.add_parser("picks", help="write the rehearsal's stand-in V3 picks")
    picks.add_argument("--world", type=Path, required=True, help="a rehearsal world folder")
    picks.add_argument("--out", type=Path, required=True, help="the folder of v3_picks.json")
    force = commands.add_parser("force", help="run one cell with a forced outcome")
    force.add_argument("--world", type=Path, required=True, help="a rehearsal world folder")
    force.add_argument("--kind", choices=FORCED, required=True)
    force.add_argument(
        "--out", type=Path, required=True, help="the cells' folder; the cell writes O/<cell id>/"
    )
    force.add_argument("--picks", type=Path, help="a v3 kind's v3_picks.json")
    force.add_argument("--picks-sha256", help="a v3 kind's pin of the picks")
    scenarios = commands.add_parser("scenarios", help="write the scenario folders")
    scenarios.add_argument("--base", type=Path, required=True, help="the v4-summary-* folders")
    scenarios.add_argument("--forced", type=Path, required=True, help="the forced cells")
    scenarios.add_argument("--out", type=Path, required=True, help="the new scenarios folder")
    check = commands.add_parser("check", help="compare each scenario's verdict with its own")
    check.add_argument("--scenarios", type=Path, required=True, help="the scenarios folder")
    check.add_argument(
        "--verdicts", type=Path, required=True, help="the verdict folders, one per scenario"
    )
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "world": world_command,
    "picks": picks_command,
    "force": force_command,
    "scenarios": scenarios_command,
    "check": check_command,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command: its exit status (module docstring)."""
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
