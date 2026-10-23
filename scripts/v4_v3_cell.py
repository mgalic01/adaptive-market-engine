"""V4.0's CLI for the ``v3_as_built`` arm: V3's picks once per run, then one v3 cell, replayed on
V3's own pack, verified and reported.

``v4_cell.py`` refuses the ``v3`` family and names this file. Step 4's workflow runs it on
GitHub's machines (no heavy work runs on the owner's PC). It implements ruling R3 of step 4a
through ``v4.engine.v3_as_built`` (its module docstring has the rules) and, as ``v4_cell.py``
does, the spec's "Reports" and the "Engineering" bullet "each cell verifies its own report".

``picks --pack P --pack-sha256 S --out O``: refuses ``O/v3_picks.json`` if it exists, then
trains V3's selector once on the pack P, read through its pin S (``run_v3_picks``), and writes
the picks there as canonical JSON. Standard output: the count of picks and the file's SHA-256,
the pin every cell then requires.

``run --pack P --pack-sha256 S --picks F --picks-sha256 T --capital {1000,10000} --costs {1,2}
--out O``:

1. refuses the cell's folder ``O/<cell id>/`` (such as ``v3_as_built-10000-1x``) if it already
   holds any of the cell's four files: a cell's files are never replaced;
2. replays the cell into its folder (``run_v3_cell``): the picks F through their pin T and the
   pack P through its pin S, then V3's replay, all before anything is written; then
   ``records.jsonl`` and ``receipt.json``. A V3 stop other than a liquidation is the outcome
   ``engine_error`` (``V3Stop``), and so is a V3 run, completed or liquidated, whose own
   accounting does not reconcile (``accounting_explained`` or ``wallet_quantity_exact`` not
   true): ``engine_error`` of type ``V3Accounting``, its message the first failed flag;
3. builds the summary from the records (``build_v3_summary``) and verifies it, in memory,
   against the records and the receipt (``verify_v3_summary``), before anything more is written;
4. writes ``summary.json`` and ``report.html`` (``write_v3_outputs``), then reads
   ``summary.json`` back and requires its bytes to be the canonical JSON of the verified summary.

**Exit status**, as ``v4_cell.py``'s: 0 once the verified summary (or the picks) is written,
whatever the cell's outcome; 1 when it could not be: an existing output, a pin that does not
match, a cell that did not run, a failure after the replay, a summary that does not verify (then
neither ``summary.json`` nor ``report.html`` is written) or bytes on disk that are not the
verified summary's; 2 for bad arguments (argparse's own): a capital or cost multiple that is not
the run's.

**Output**, as ``v4_cell.py``'s: one line per command on standard output, ids, counts and pins
only, never a price or an equity (owner rule: public logs); for ``run``, the cell's id, outcome,
record count, hours (open marks) and the summary's SHA-256. Standard error never echoes an
exception's text, which may hold a price: a failure is one line naming the command or the cell,
the step that failed and the exception's type (``v4_cell._fail``).
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from v4_cell import OUTPUT_FILES, _fail, _say

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine.arms import CAPITALS, COST_MULTIPLES, CellSpec
from crypto_grid_bot.v4.engine.run import RECORDS_FILE
from crypto_grid_bot.v4.engine.summary import SUMMARY_FILE
from crypto_grid_bot.v4.engine.v3_as_built import (
    PICKS_FILE,
    V3_ARM,
    build_v3_summary,
    read_v3_picks,
    render_v3_page,
    run_v3_cell,
    run_v3_picks,
    verify_v3_summary,
    write_v3_outputs,
)


def picks_command(args: argparse.Namespace) -> int:
    """The ``picks`` command: V3's picks, computed once and pinned (module docstring)."""
    name = "v4_v3_cell picks"
    if (Path(args.out) / PICKS_FILE).exists():
        return _fail(name, f"refused: the folder already holds {PICKS_FILE}")
    try:
        digest = run_v3_picks(args.pack, args.pack_sha256, args.out)
    except Exception as exc:
        return _fail(name, "computing the picks failed", exc)
    try:
        count = len(read_v3_picks(Path(args.out) / PICKS_FILE, digest))
    except Exception as exc:
        return _fail(name, f"reading {PICKS_FILE} back failed", exc)
    _say(f"{name}: {count} picks, {PICKS_FILE} sha256 {digest}")
    return 0


def run_command(args: argparse.Namespace) -> int:
    """The ``run`` command: one v3 cell's replay, verified summary and page (module docstring)."""
    cell = CellSpec(V3_ARM, args.capital, args.costs)
    name = f"v4_v3_cell run: {cell.cell_id}"
    folder = Path(args.out) / cell.cell_id
    found = [file for file in OUTPUT_FILES if (folder / file).exists()]
    if found:
        return _fail(name, f"refused: the cell's folder already holds {', '.join(found)}")
    try:
        receipt = run_v3_cell(
            args.pack, args.pack_sha256, args.picks, args.picks_sha256, cell, folder
        )
    except Exception as exc:  # a refused pin or input, or a failure outside V3's own loop
        return _fail(name, "the cell did not run", exc)
    records = folder / RECORDS_FILE
    try:
        summary = build_v3_summary(cell, records, receipt)
    except Exception as exc:
        return _fail(name, "building the summary failed", exc)
    try:
        verify_v3_summary(summary, records, receipt)
    except Exception as exc:
        return _fail(name, "the summary does not verify against the records; none written", exc)
    try:
        expected = _canonical(summary)
        digest = write_v3_outputs(folder, summary, render_v3_page(summary))
    except Exception as exc:
        return _fail(name, "writing the summary and the page failed", exc)
    try:
        written = (folder / SUMMARY_FILE).read_bytes()
    except OSError as exc:
        return _fail(name, f"reading {SUMMARY_FILE} back failed", exc)
    if written != expected:
        return _fail(name, f"{SUMMARY_FILE} on disk is not the verified summary's canonical JSON")
    hours = receipt.kinds.get("hourly", 0)  # one hourly record per open mark
    _say(
        f"{name}: outcome {summary['outcome']}, {receipt.record_count} records, "
        f"{hours} hours, summary sha256 {digest}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_v3_cell.py",
        description="V3's picks, and one v3_as_built cell replayed and reported (see docstring).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    picks = commands.add_parser("picks", help="train V3's selector once and pin its picks")
    picks.add_argument("--pack", type=Path, required=True, help="V3's input pack")
    picks.add_argument("--pack-sha256", required=True, help="the V3 pack's pin")
    picks.add_argument("--out", type=Path, required=True, help="the folder of v3_picks.json")
    run = commands.add_parser("run", help="replay one v3 cell and write its four files")
    run.add_argument("--pack", type=Path, required=True, help="V3's input pack")
    run.add_argument("--pack-sha256", required=True, help="the V3 pack's pin")
    run.add_argument("--picks", type=Path, required=True, help="the run's v3_picks.json")
    run.add_argument("--picks-sha256", required=True, help="the picks' pin")
    run.add_argument("--capital", type=int, choices=CAPITALS, required=True)
    run.add_argument(
        "--costs", type=int, choices=COST_MULTIPLES, required=True, help="the cost multiple"
    )
    run.add_argument(
        "--out", type=Path, required=True, help="the cells' folder; the cell writes O/<cell id>/"
    )
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "picks": picks_command,
    "run": run_command,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command: its exit status (module docstring)."""
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
