"""V4.0's synthetic worlds for the step-4b rehearsal and timing runs, and the stand-in picks of the
rehearsal's V3 arm.

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
3. writes ``O/rehearsal.json`` last, as canonical JSON (``combined.artifacts._canonical``) created
   exclusively: ``format`` (``WORLD_FORMAT``), ``scale``, ``data`` (``run.data_record`` of the
   written world: the data pack's pins), ``v3_pack_sha256`` (the pack's pin; null for the timing
   scale) and ``registration_sha256`` (null here: step 4b task 7 fills it for a rehearsal);
4. removes ``O`` again if anything failed.

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

**Exit status**: 0 once the world (or the picks) is written, 1 when it could not be, 2 for bad
arguments (argparse's own).

**Output**: one line on standard output, counts and pins only, never a price (owner rule: public
logs); for ``world``, the scale, the coin count, the hourly row count and the pins. Standard error
never echoes an exception's text (``v4_cell._fail``): a failure is one line naming the command, the
step and the exception's type.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import shutil
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

from v4_cell import _fail, _say
from v4_v3_cell import main as v3_cell_main
from v4_v3_pack import EXPECTED_PACK_SHA256, PACK_FILE

from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.combined import baseline_v3
from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.combined.driver.v3_pack import write_v3_pack
from crypto_grid_bot.trend.decisions import DailyDecisions
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.orchestration import Attempt
from crypto_grid_bot.trend.replay import replay_window
from crypto_grid_bot.v4.engine.market import DataPins
from crypto_grid_bot.v4.engine.run import data_record
from crypto_grid_bot.v4.engine.v3_as_built import V3_START_MS
from crypto_grid_bot.v4.synthetic import (
    DAY,
    REHEARSAL_PICKS,
    read_data_json,
    rehearsal_v3_fields,
    rehearsal_world,
    timing_world,
    write_world,
)

WORLD_FILE = "rehearsal.json"
WORLD_FORMAT = "v4-rehearsal-world-1"
DATA_DIR = "v4data"
V3_DIR = "v3pack"
SCALES = ("rehearsal", "timing")

_STAGING = "staging"  # write_world writes <root>/data; the world's folder is renamed from there
_MAX_WORLD_BYTES = 4096
_MAX_PACK_BYTES = 1 << 28  # the V3 pack's JSON is about 15 MB; refuse anything near 256 MiB
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
    if scale == "rehearsal":
        (out / V3_DIR).mkdir()
        v3_pin = write_v3_pack(rehearsal_v3_fields(), out / V3_DIR / PACK_FILE)
    document = {
        "format": WORLD_FORMAT,
        "scale": scale,
        "data": data_record(pins),
        "v3_pack_sha256": v3_pin,
        "registration_sha256": None,
    }
    with (out / WORLD_FILE).open("xb") as handle:  # last: a folder with it is a whole world
        handle.write(_canonical(document))
    return (
        f"v4_rehearsal world: scale {scale}, {header['coin_packs']} coins, "
        f"{header['hourly_rows']} hourly rows, daily sha256 {daily}, index sha256 {index}, "
        f"v3 pack sha256 {v3_pin or 'none'}"
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
        shutil.rmtree(out, ignore_errors=True)  # the folder did not exist before this run
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


# ---- the command line ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_rehearsal.py",
        description="The step-4b rehearsal and timing worlds, and the rehearsal's V3 picks "
        "(see docstring).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    world = commands.add_parser("world", help="write a synthetic world folder")
    world.add_argument("--scale", choices=SCALES, required=True)
    world.add_argument("--out", type=Path, required=True, help="the new world folder")
    picks = commands.add_parser("picks", help="write the rehearsal's stand-in V3 picks")
    picks.add_argument("--world", type=Path, required=True, help="a rehearsal world folder")
    picks.add_argument("--out", type=Path, required=True, help="the folder of v3_picks.json")
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "world": world_command,
    "picks": picks_command,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command: its exit status (module docstring)."""
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
