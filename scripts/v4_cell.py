"""V4.0's one-cell CLI: replay one cell of the run over a data directory, then verify and write
its report.

Step 4's cells matrix runs it once per cell on GitHub's machines (no heavy work runs on the owner's
PC). It implements the spec's "Reports" (a cell that runs and verifies writes a ``summary.json``,
even if it stops early; a cell that cannot run or verify writes none) and the "Engineering" bullet
"each cell verifies its own report" (rebuild and equality, inside the cell job).

``run --data D --arm A --capital {1000,10000} --costs {1,2} --out O``:

1. refuses the cell's folder ``O/<cell id>/`` (``CellSpec.cell_id``, such as ``v4_main-10000-1x``)
   if it already holds any of the cell's four files: a cell's files are never replaced;
2. loads the market of the data directory D (``Market.load``: ``data.json`` and every pack, each
   verified by its pin) before anything is written, so a bad pin or bad data writes nothing;
3. replays the cell into its folder, created if missing: ``run_v4_cell`` for a V4 arm and
   ``run_hold_cell`` for a hold arm, by the arm's family. The replay writes ``records.jsonl`` and
   ``receipt.json``; an exception in its loop is the outcome ``engine_error`` (ruling P5);
4. builds the summary from the records (``build_summary``) and verifies it, in memory, against the
   records and the replay's receipt (``verify_summary``), before anything more is written;
5. writes ``summary.json`` and ``report.html`` (``write_cell_outputs``), then reads
   ``summary.json`` back and requires its bytes to be the canonical JSON of the verified summary.

The ``v3_as_built`` arm (the ``v3`` family) is refused before step 1, with nothing read or
written: V3's arm runs through its own CLI, ``scripts/v4_v3_cell.py``, on V3's own pack.

**Exit status.** 0 once the verified summary is written, whatever the cell's outcome:
``complete``, ``liquidated``, ``limit_unrestorable``, ``accounting_failure`` or ``engine_error``
(the last two with their short failure summaries). 1 when no verified summary could be written:
the ``v3_as_built`` arm, a folder that already holds outputs, a data directory that does not
load, a failure after the replay, a summary that does not verify (then neither ``summary.json``
nor ``report.html`` is written), or a ``summary.json`` whose bytes on disk are not the verified
summary's. 2 for bad
arguments (argparse's own): an arm, capital or cost multiple that is not the run's.

**Output.** Standard output carries one line per cell: its id, outcome, record count, hours (open
marks) and the summary's SHA-256, counts and pins only, never a price or an equity (owner rule:
public logs). Standard error never echoes an exception's text, which may hold a price: a failure
is one line naming the cell, the step that failed and the exception's type.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine.arms import ARMS, CAPITALS, COST_MULTIPLES, CellSpec
from crypto_grid_bot.v4.engine.hold import run_hold_cell
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.run import RECEIPT_FILE, RECORDS_FILE, CellResult, run_v4_cell
from crypto_grid_bot.v4.engine.summary import (
    PAGE_FILE,
    SUMMARY_FILE,
    build_summary,
    render_page,
    verify_summary,
    write_cell_outputs,
)

# The cell's four files, in the order they are written.
OUTPUT_FILES = (RECORDS_FILE, RECEIPT_FILE, SUMMARY_FILE, PAGE_FILE)

Runner = Callable[[Market, CellSpec, Path], CellResult]
# The v3 family is not here: V3's arm has its own CLI, which reads V3's pack.
RUNNERS: dict[str, Runner] = {"v4": run_v4_cell, "hold": run_hold_cell}


def _say(line: str) -> None:
    """A line of standard output: counts and pins only."""
    print(line, flush=True)


def _fail(name: str, step: str, exc: BaseException | None = None) -> int:
    """One line of standard error, the failed ``step`` and the exception's type, never its
    message; returns the exit status 1."""
    kind = "" if exc is None else f": {type(exc).__name__}"
    print(f"{name}: {step}{kind}", file=sys.stderr, flush=True)
    return 1


def run_cell(args: argparse.Namespace) -> int:
    """The ``run`` command: one cell's replay, verified summary and page (module docstring)."""
    cell = CellSpec(args.arm, args.capital, args.costs)
    family = ARMS[cell.arm].family
    if family not in RUNNERS:  # the v3 family: refused before anything is read or written
        message = f"v4_cell run: the {cell.arm} arm runs through scripts/v4_v3_cell.py"
        print(message, file=sys.stderr, flush=True)
        return 1
    name = f"v4_cell run: {cell.cell_id}"
    folder = Path(args.out) / cell.cell_id
    found = [file for file in OUTPUT_FILES if (folder / file).exists()]
    if found:
        return _fail(name, f"refused: the cell's folder already holds {', '.join(found)}")
    try:
        market = Market.load(Path(args.data))
    except Exception as exc:
        return _fail(name, "refused: loading the data directory failed", exc)
    try:
        result = RUNNERS[family](market, cell, folder)
    except Exception as exc:  # outside the loop: the loop's own exceptions are engine_error
        return _fail(name, "the replay failed outside its loop", exc)
    records = folder / RECORDS_FILE
    try:
        summary = build_summary(cell, result, records)
    except Exception as exc:
        return _fail(name, "building the summary failed", exc)
    try:
        verify_summary(summary, records, result.receipt)
    except Exception as exc:
        return _fail(name, "the summary does not verify against the records; none written", exc)
    try:
        expected = _canonical(summary)
        digest = write_cell_outputs(folder, summary, render_page(summary))
    except Exception as exc:
        return _fail(name, "writing the summary and the page failed", exc)
    try:
        written = (folder / SUMMARY_FILE).read_bytes()
    except OSError as exc:
        return _fail(name, f"reading {SUMMARY_FILE} back failed", exc)
    if written != expected:
        return _fail(name, f"{SUMMARY_FILE} on disk is not the verified summary's canonical JSON")
    _say(
        f"{name}: outcome {result.outcome}, {result.receipt.record_count} records, "
        f"{len(result.open_marks)} hours, summary sha256 {digest}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_cell.py", description="One V4.0 cell, replayed and reported (see the docstring)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("run", help="replay one cell and write its four files")
    command.add_argument("--data", type=Path, required=True, help="the data directory")
    command.add_argument("--arm", choices=tuple(ARMS), required=True)
    command.add_argument("--capital", type=int, choices=CAPITALS, required=True)
    command.add_argument(
        "--costs", type=int, choices=COST_MULTIPLES, required=True, help="the cost multiple"
    )
    command.add_argument(
        "--out", type=Path, required=True, help="the cells' folder; the cell writes O/<cell id>/"
    )
    return parser


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {"run": run_cell}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command: its exit status (module docstring)."""
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
