"""V4.0's one-cell CLI: replay one cell of the run over a data directory, then write and verify
its report.

Step 4's cells matrix runs it once per cell on GitHub's machines (no heavy work runs on the owner's
PC). It implements the spec's "Reports" (every cell writes a ``summary.json``, even one that stops
early) and the "Engineering" bullet "each cell verifies its own report" (rebuild and equality,
inside the cell job).

``run --data D --arm A --capital {1000,10000} --costs {1,2} --out O``:

1. refuses the cell's folder ``O/<cell id>/`` (``CellSpec.cell_id``, such as ``v4_main-10000-1x``)
   if it already holds any of the cell's four files: a cell's files are never replaced;
2. loads the market of the data directory D (``Market.load``: ``data.json`` and every pack, each
   verified by its pin) before anything is written, so a bad pin or bad data writes nothing;
3. replays the cell into its folder, created if missing: ``run_v4_cell`` for a V4 arm and
   ``run_hold_cell`` for a hold arm, by the arm's family. The replay writes ``records.jsonl`` and
   ``receipt.json``; an exception in its loop is the outcome ``engine_error`` (ruling P5);
4. builds the summary from the records (``build_summary``), renders its page and writes
   ``summary.json`` and ``report.html`` (``write_cell_outputs``);
5. reads ``summary.json`` back and verifies it against the records and ``receipt.json``
   (``verify_summary``).

**Exit status.** 0 once the summary is written and verified, whatever the cell's outcome:
``complete``, ``liquidated``, ``limit_unrestorable``, ``accounting_failure`` or ``engine_error``
(the last two with their short failure summaries). 1 when no summary could be written: a folder
that already holds outputs, a data directory that does not load, or a failure after the replay
and before the summary was written; and 1 too when the summary was written but does not verify,
since a report that does not match its records must stop the cell job. 2 for bad arguments
(argparse's own): an arm, capital or cost multiple that is not the run's.

**Output.** Standard output carries one line per cell: its id, outcome, record count, hours (open
marks) and the summary's SHA-256, counts and pins only, never a price or an equity (owner rule:
public logs). A refusal goes to standard error with its reason, every decimal number in it hidden
(a pack the loader refuses may name a bar's value). A failure after the replay names only the
step and the exception's type: its message may hold an equity.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from crypto_grid_bot.v4.engine.arms import ARMS, CAPITALS, COST_MULTIPLES, CellSpec
from crypto_grid_bot.v4.engine.hold import run_hold_cell
from crypto_grid_bot.v4.engine.market import Market
from crypto_grid_bot.v4.engine.records import read_receipt
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
RUNNERS: dict[str, Runner] = {"v4": run_v4_cell, "hold": run_hold_cell}

# A decimal number in a refusal's reason, such as a bar's price, is hidden before it is printed.
# Only numbers with a decimal point: a hex digest, which a pin's refusal names, has none.
_DECIMAL = re.compile(r"[0-9]*\.[0-9]+(?:[eE][-+]?[0-9]+)?")


def _say(line: str) -> None:
    """A line of standard output: counts and pins only."""
    print(line, flush=True)


def _log(line: str) -> None:
    """A line of standard error."""
    print(line, file=sys.stderr, flush=True)


def _hidden(reason: str) -> str:
    """``reason`` with every decimal number replaced by ``<number>``."""
    return _DECIMAL.sub("<number>", reason)


def _refuse_existing(folder: Path) -> None:
    """Refuse a cell folder that already holds any of the cell's files."""
    found = [name for name in OUTPUT_FILES if (folder / name).exists()]
    if found:
        raise ValueError(
            f"{folder} already holds {', '.join(found)}; a cell's files are never replaced"
        )


def _read_summary(path: Path) -> dict[str, object]:
    """The written ``summary.json``, as JSON (canonical, so ASCII with no float)."""
    document = json.loads(path.read_bytes().decode("ascii"))
    if not isinstance(document, dict):
        raise ValueError(f"{path.name} does not hold a JSON object")
    return document


def run_cell(args: argparse.Namespace) -> int:
    """The ``run`` command: one cell's replay, summary, page and verification (module
    docstring)."""
    cell = CellSpec(args.arm, args.capital, args.costs)
    name = f"v4_cell run: {cell.cell_id}"
    folder = Path(args.out) / cell.cell_id
    try:
        _refuse_existing(folder)
        market = Market.load(Path(args.data))
    except (ValueError, OSError) as exc:  # OSError: a missing or unreadable file
        _log(f"{name}: refused: {_hidden(str(exc))}")
        return 1
    try:
        result = RUNNERS[ARMS[cell.arm].family](market, cell, folder)
    except Exception as exc:  # outside the loop: the loop's own exceptions are engine_error
        _log(f"{name}: the replay raised outside its loop ({type(exc).__name__})")
        return 1
    try:
        summary = build_summary(cell, result, folder / RECORDS_FILE)
        digest = write_cell_outputs(folder, summary, render_page(summary))
    except Exception as exc:
        _log(f"{name}: no summary was written ({type(exc).__name__})")
        return 1
    try:
        written = _read_summary(folder / SUMMARY_FILE)
        verify_summary(written, folder / RECORDS_FILE, read_receipt(folder / RECEIPT_FILE))
    except Exception as exc:
        _log(f"{name}: {SUMMARY_FILE} does not verify against the records ({type(exc).__name__})")
        return 1
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
