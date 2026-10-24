"""The v4-run workflow's plan: the job matrices of the cells, and the verdict step's expected file.

``.github/workflows/v4-run.yml`` (plan ``docs/superpowers/plans/2026-10-24-v4-step4b-pipeline.md``,
Task 8) calls this script in two of its jobs, passing every input through an environment variable
and never as text in a script. Nothing here reads a cell's outcome or a verdict, and standard
output carries counts and pins only (owner rule: public logs).

``matrix --mode M --github-output F`` (the ``plan`` job). The cells of a mode are
``inputs.expected_cells(M)``: the 48 cells of ``arms.all_cells()`` in order, or for ``timing`` the
44 of the arms that are not v3. The matrices are derived from that one list, so a cell that is run
is a cell that is expected, and the reverse. It appends five lines to ``F`` (GitHub's step
outputs), as ``scripts/v4_cells_plan.py`` does, and only when the mode is valid:

- ``cells=<one line of JSON>``: ``{"include": [{"cell": ID, "arm": A, "capital": C, "costs": K},
  ...]}``, the 44 cells that are not v3, in ``all_cells()`` order, for the ``cell`` job's matrix
  (``fromJSON``);
- ``v3_cells=<one line of JSON>``: the same shape for the 4 ``v3_as_built`` cells, and
  ``{"include": []}`` for ``timing``, which has none (the ``v3-cell`` job is skipped on
  ``v3_count``, since GitHub refuses an empty matrix);
- ``cell_ids=<comma-separated ids>``: the 44 cells of ``cells``, which is the diagnosis'
  ``--planned`` (the analysis job reads ``v4-cell-*`` artifacts, and the v3 cells upload none);
- ``cells_count=44`` and ``v3_count=4`` (0 for ``timing``).

A mode that is not one of ``inputs.MODES`` (``rehearsal``, ``timing``, ``registered``) is refused,
writing nothing.

``expected --mode M --data D --out E [--manifest M] [--world O] [--picks-sha256 T]`` (the
``verdict`` job) writes the expected file ``scripts/v4_verdict.py`` judges the cells against: the
canonical JSON of ``inputs.expected_record`` (``combined.artifacts._canonical``), so
``inputs.read_expected`` accepts it byte for byte, and this command reads it back to check that it
does before it succeeds. Its ``cells`` are ``expected_cells(M)``; its ``window`` and ``data`` are
those of ``Market.load(D)`` (``run.window_record`` and ``run.data_record``, so each pack is
verified by its pin); its v3 pins come from the mode's own source, and from no other:

- ``registered``: ``--manifest`` is the run manifest (``config/v4_run_manifest.json``), whose
  ``v3_pack_sha256`` is the pin, and whose ``data`` must carry the four pins of ``D``;
  ``--world`` is refused;
- ``rehearsal``: ``--world`` is the world folder, whose ``rehearsal.json`` (``read_world``) must be
  of the rehearsal scale and gives the pin, and whose ``data`` must be ``D``'s pins; ``D`` must be
  synthetic (its ``config_sha256`` is ``synthetic.CONFIG_SHA256``, v4-d03); ``--manifest`` is
  refused;
- ``timing``: no source, no v3 pin (both null in the file); ``D`` must be synthetic; ``--manifest``
  and ``--world`` are refused.

``--picks-sha256`` is the pin of ``v3_picks.json``: 64 lowercase hex digits, required in the modes
that have v3 cells (``registered`` and ``rehearsal``). A timing run has no picks job, so it takes
none (an empty one, from a workflow that passes the same arguments in every mode, is none). The
refusals above, a mismatch of the pins and an ``E`` that already exists (never replaced, refused
before ``D`` is read) write nothing; if the file written does not read back as the expected
document, it is removed again. The folder of ``E`` is created if missing. Standard output carries
one line: the mode, the cell count, the window's hours, the data's end month and the file's
SHA-256.

**Exit status**: 0 once the output is written; 1 on any refusal or failure, with nothing written;
2 for bad arguments (argparse's own).

**Errors**: one line on standard error, ``::error::v4_run_plan: <what was wrong>: refused``. It
says what this script refused in words; of any other exception (the data pack's loader, say) it
names only the step and the type, never the message, which may quote a value.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from v4_cell import _say
from v4_registration import RunManifest, read_manifest
from v4_rehearsal import read_world

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec, all_cells
from crypto_grid_bot.v4.engine.market import HOUR_MS, Market
from crypto_grid_bot.v4.engine.run import data_record, window_record
from crypto_grid_bot.v4.synthetic import CONFIG_SHA256
from crypto_grid_bot.v4.verdict.inputs import (
    MODES,
    Expected,
    expected_cells,
    expected_record,
    read_expected,
)

_HEX64 = re.compile("[0-9a-f]{64}")
# ``run.data_record``'s keys: the manifest's ``data`` holds these and its ``config_path``.
_PIN_KEYS = ("config_sha256", "end_month", "daily_sha256", "index_sha256")


class PlanError(ValueError):
    """A refusal of this script: the message says what was wrong, in words that quote no value of
    a data pack or of a cell."""


def _refuse(message: str) -> int:
    """One line of standard error, ``::error::v4_run_plan: <message>: refused``; the exit
    status 1."""
    print(f"::error::v4_run_plan: {message}: refused", file=sys.stderr, flush=True)
    return 1


def _check_mode(mode: object) -> str:
    """``mode``, if it is one of ``MODES``; otherwise a ``PlanError``."""
    if not isinstance(mode, str) or mode not in MODES:
        raise PlanError(f"unknown mode {mode!r:.40}: one of {', '.join(MODES)} required")
    return mode


# ---- matrix -----------------------------------------------------------------------------------


def _entry(cell: CellSpec) -> dict[str, object]:
    """One matrix entry, as ``v4_cells_plan.matrix_json`` writes it: what ``v4_cell.py run``
    takes."""
    return {
        "cell": cell.cell_id,
        "arm": cell.arm,
        "capital": cell.capital,
        "costs": cell.cost_multiple,
    }


def matrix(mode: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The cells of ``mode`` as matrix entries: the cells that are not v3 (44), and the v3 cells
    (4; none for ``timing``), each in ``all_cells()`` order. A mode that is not one of ``MODES``
    is a ``PlanError`` (a ``ValueError``)."""
    ids = expected_cells(_check_mode(mode))
    by_id = {cell.cell_id: cell for cell in all_cells()}
    chosen = [by_id[cell_id] for cell_id in ids]
    cells = [_entry(cell) for cell in chosen if ARMS[cell.arm].family != "v3"]
    v3_cells = [_entry(cell) for cell in chosen if ARMS[cell.arm].family == "v3"]
    return cells, v3_cells


def _matrix_json(entries: Sequence[Mapping[str, object]]) -> str:
    """A job matrix as one compact line of JSON: ``{"include": [...]}``."""
    return json.dumps({"include": list(entries)}, separators=(",", ":"))


def matrix_command(args: argparse.Namespace) -> int:
    """The ``matrix`` command (module docstring)."""
    try:
        cells, v3_cells = matrix(args.mode)
    except PlanError as exc:
        return _refuse(str(exc))
    ids = ",".join(str(cell["cell"]) for cell in cells)
    lines = (
        f"cells={_matrix_json(cells)}\nv3_cells={_matrix_json(v3_cells)}\ncell_ids={ids}\n"
        f"cells_count={len(cells)}\nv3_count={len(v3_cells)}\n"
    )
    try:
        with Path(args.github_output).open("a", encoding="ascii", newline="\n") as output:
            output.write(lines)
    except OSError as exc:
        return _refuse(f"writing the output file failed ({type(exc).__name__})")
    _say(f"v4_run_plan matrix: mode {args.mode}, {len(cells)} cells, {len(v3_cells)} v3 cells")
    return 0


# ---- expected ---------------------------------------------------------------------------------


def _picks(mode: str, picks_sha256: str | None) -> str | None:
    """The picks' pin of the expected file: required, as 64 lowercase hex digits, in a mode that
    has v3 cells; none for ``timing``, which refuses one (an empty one is none)."""
    if mode == "timing":
        if picks_sha256:
            raise PlanError("a timing run has no v3 cells: --picks-sha256 is refused")
        return None
    if not isinstance(picks_sha256, str) or _HEX64.fullmatch(picks_sha256) is None:
        raise PlanError("--picks-sha256 must be 64 lowercase hex digits (the v3 picks' pin)")
    return picks_sha256


def _source(
    mode: str, manifest: RunManifest | None, world: Mapping[str, object] | None
) -> tuple[str | None, Mapping[str, object] | None, str]:
    """The mode's one source of v3 pins (module docstring): the v3 pack's pin, the data pins the
    source says ``D`` has (None: no source), and the source's name for a refusal. The other
    source is refused."""
    if mode == "timing":
        if manifest is not None or world is not None:
            raise PlanError("a timing run has no v3 pack: --manifest and --world are refused")
        return None, None, ""
    if mode == "registered":
        if world is not None:
            raise PlanError("a registered run takes its v3 pin from --manifest: --world is refused")
        if manifest is None:
            raise PlanError("a registered run needs --manifest, the run manifest")
        return manifest.v3_pack_sha256, {key: manifest.data[key] for key in _PIN_KEYS}, "manifest"
    if manifest is not None:
        raise PlanError("a rehearsal takes its v3 pin from --world: --manifest is refused")
    if world is None:
        raise PlanError("a rehearsal needs --world, the rehearsal world folder")
    pin, data = world.get("v3_pack_sha256"), world.get("data")
    if world.get("scale") != "rehearsal" or not isinstance(pin, str) or not isinstance(data, dict):
        raise PlanError("--world is not a rehearsal world with a v3 pack")
    return pin, data, "rehearsal world"


def _remove(target: Path) -> None:
    with contextlib.suppress(OSError):
        target.unlink()


def _create(target: Path, raw: bytes, expected: Expected) -> None:
    """Create ``target`` with ``raw``, exclusively, and check that it reads back as ``expected``;
    it is removed again if it does not."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PlanError(f"creating the output folder failed ({type(exc).__name__})") from None
    try:
        with target.open("xb") as handle:
            handle.write(raw)
    except FileExistsError:
        raise PlanError("the output file already exists") from None
    except OSError as exc:
        _remove(target)
        raise PlanError(f"writing the output file failed ({type(exc).__name__})") from None
    try:
        read = read_expected(target)
    except ValueError as exc:  # its messages name what is wrong and never a value
        _remove(target)
        raise PlanError(
            f"the expected file written is not one read_expected accepts: {exc}"
        ) from None
    if read != expected:
        _remove(target)
        raise PlanError("the expected file written does not read back as itself")


def write_expected(
    mode: str,
    data_dir: Path,
    out: Path,
    *,
    manifest: RunManifest | None,
    world: Mapping[str, object] | None,
    picks_sha256: str | None,
) -> None:
    """Write the expected file of ``mode`` at ``out`` (module docstring), or raise a
    ``PlanError`` writing nothing. ``world`` is the parsed ``rehearsal.json`` (``read_world``)."""
    _check_mode(mode)
    picks = _picks(mode, picks_sha256)
    v3_pin, wanted, source = _source(mode, manifest, world)
    target = Path(out)
    if target.exists() or target.is_symlink():
        raise PlanError("the output file already exists")
    try:
        market = Market.load(Path(data_dir))
    except Exception as exc:  # the loader's messages may quote a value of a pack
        raise PlanError(f"loading the data directory failed ({type(exc).__name__})") from None
    pins = data_record(market.pins)
    if pins is None or market.pins is None:
        raise PlanError("the data directory carries no pins")
    if wanted is not None and pins != dict(wanted):
        raise PlanError(f"the data directory's pins are not the {source}'s")
    if mode != "registered" and market.pins.config_sha256 != CONFIG_SHA256:
        raise PlanError(f"a {mode} runs on synthetic data only (v4-d03): this data is not")
    expected = Expected(
        mode,
        expected_cells(mode),
        cast("Mapping[str, int]", window_record(market)),
        cast("Mapping[str, str]", pins),
        v3_pin,
        picks,
    )
    raw = _canonical(expected_record(expected))
    _create(target, raw, expected)
    hours = (market.window_end_ms - market.window_start_ms) // HOUR_MS + 1
    _say(
        f"v4_run_plan expected: mode {mode}, {len(expected.cells)} cells, {hours} window hours, "
        f"data end_month {market.end_month}, expected sha256 {hashlib.sha256(raw).hexdigest()}"
    )


def _reason(exc: BaseException) -> str:
    """What a refusal says of ``exc``: the message of a plain ``ValueError`` (``read_manifest``'s
    and ``read_world``'s name no value of a market), only the type of anything else."""
    return str(exc) if type(exc) is ValueError else type(exc).__name__


def expected_command(args: argparse.Namespace) -> int:
    """The ``expected`` command (module docstring)."""
    try:
        _check_mode(args.mode)
        manifest = None
        if args.manifest is not None:
            try:
                manifest = read_manifest(Path(args.manifest).read_bytes())
            except (OSError, ValueError) as exc:
                raise PlanError(f"--manifest cannot be read ({_reason(exc)})") from None
        world = None
        if args.world is not None:
            try:
                world = read_world(Path(args.world))
            except (OSError, ValueError) as exc:
                raise PlanError(f"--world cannot be read ({_reason(exc)})") from None
        write_expected(
            args.mode,
            args.data,
            args.out,
            manifest=manifest,
            world=world,
            picks_sha256=args.picks_sha256,
        )
    except PlanError as exc:
        return _refuse(str(exc))
    return 0


# ---- the command line -------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_run_plan.py",
        description="The v4-run workflow's job matrices and the verdict step's expected file "
        "(see the module docstring).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("matrix", help="append the job matrices to the step outputs")
    plan.add_argument("--mode", required=True, help="rehearsal, timing or registered")
    plan.add_argument(
        "--github-output", type=Path, required=True, help="the file $GITHUB_OUTPUT names"
    )
    expected = commands.add_parser("expected", help="write the verdict step's expected file")
    expected.add_argument("--mode", required=True, help="rehearsal, timing or registered")
    expected.add_argument("--data", type=Path, required=True, help="the data directory")
    expected.add_argument("--out", type=Path, required=True, help="the new expected file")
    expected.add_argument("--manifest", type=Path, help="registered: the run manifest")
    expected.add_argument("--world", type=Path, help="rehearsal: the world folder")
    expected.add_argument("--picks-sha256", help="the pin of v3_picks.json (not for timing)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command: its exit status (module docstring)."""
    args = build_parser().parse_args(argv)
    if args.command == "matrix":
        return matrix_command(args)
    return expected_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
