"""The v4-cells workflow's plan: validate the dispatch's inputs and build the cells' matrix.

The ``plan`` job of ``.github/workflows/v4-cells.yml`` passes the four inputs of the dispatch to
this script through environment variables, never as text in a script:

``--data-run ID --arms A,B --capitals 1000,10000 --costs 1,2 --github-output FILE``

* the data run's id must be digits only (1 to 20 of them, no leading zero), since it names the
  run whose ``v4-data`` artifact the jobs download;
* every arm must be one of the engine's ``ARMS`` (``hold_btc_trend`` and ``v3_as_built`` are
  built in a later step, so they are refused), every capital one of ``CAPITALS`` (1000 and
  10000) and every cost multiple one of ``COST_MULTIPLES`` (1 and 2). Each is plain digits or a
  name, exactly as the cell CLI takes it; spaces around a comma are ignored, and an empty item or
  a repeat is refused (two jobs would upload the same artifact).

The cells are the arms, capitals and costs asked for, in the order of ``arms.all_cells()``: arms
in ``ARMS`` order, then capital, then cost multiple. At most 8 x 2 x 2 = 32 of them.

Only when every input is valid does it append three lines to the file named by
``--github-output``: ``data_run=<id>``, ``matrix=<one line of JSON>`` and ``cells=<count>``. The
matrix is ``{"include": [{"cell": ID, "arm": A, "capital": C, "costs": K}, ...]}``, for a job
matrix of ``fromJSON``. A refused input writes nothing and exits 1; an offending value is shown as
its ``repr``, cut at 60 characters, so it stays on one line of the log. Standard output carries
the number of cells and the run's id.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Collection, Sequence
from pathlib import Path

from crypto_grid_bot.v4.engine.arms import ARMS, CAPITALS, COST_MULTIPLES, CellSpec

# The text of each value the cell CLI takes, exactly: never ``int(text)``, which also accepts
# "+1000", " 1000", "1_000" and full-width digits.
CAPITAL_CHOICES = {str(capital): capital for capital in CAPITALS}
COST_CHOICES = {str(multiple): multiple for multiple in COST_MULTIPLES}

_RUN_ID = re.compile(r"[1-9][0-9]{0,19}")


def check_run_id(text: str) -> str:
    """The run id, if it is plain ASCII digits; otherwise a ``ValueError``."""
    if _RUN_ID.fullmatch(text) is None:
        raise ValueError(f"run id must be 1 to 20 digits, no leading zero, got {text!r:.60}")
    return text


def _pick(text: str, what: str, choices: Collection[str]) -> set[str]:
    """The comma-separated items of ``text``, each one of ``choices``, with no repeat."""
    picked: set[str] = set()
    for item in text.split(","):
        item = item.strip()
        if not item:
            raise ValueError(f"the {what} list {text!r:.60} has an empty item")
        if item not in choices:
            raise ValueError(f"unknown {what} {item!r:.60}: one of {', '.join(choices)} required")
        if item in picked:
            raise ValueError(f"{what} {item} is listed twice")
        picked.add(item)
    return picked


def build_cells(arms: str, capitals: str, costs: str) -> tuple[CellSpec, ...]:
    """The cells of the arms, capitals and cost multiples given, in ``all_cells()`` order."""
    chosen_arms = _pick(arms, "arm", tuple(ARMS))
    chosen_capitals = _pick(capitals, "capital", CAPITAL_CHOICES)
    chosen_costs = _pick(costs, "cost multiple", COST_CHOICES)
    return tuple(
        CellSpec(arm, capital, multiple)
        for arm in ARMS
        if arm in chosen_arms
        for capital in CAPITALS
        if str(capital) in chosen_capitals
        for multiple in COST_MULTIPLES
        if str(multiple) in chosen_costs
    )


def matrix_json(cells: Sequence[CellSpec]) -> str:
    """The job matrix as one compact line of JSON: ``{"include": [...]}``."""
    include = [
        {
            "cell": cell.cell_id,
            "arm": cell.arm,
            "capital": cell.capital,
            "costs": cell.cost_multiple,
        }
        for cell in cells
    ]
    return json.dumps({"include": include}, separators=(",", ":"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v4_cells_plan.py", description=__doc__)
    parser.add_argument("--data-run", required=True, help="the id of the v4-data run")
    parser.add_argument("--arms", required=True, help="comma-separated arm names")
    parser.add_argument("--capitals", required=True, help="comma-separated, from 1000 and 10000")
    parser.add_argument("--costs", required=True, help="comma-separated cost multiples, 1 and 2")
    parser.add_argument(
        "--github-output", type=Path, required=True, help="the file $GITHUB_OUTPUT names"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data_run = check_run_id(args.data_run)
        cells = build_cells(args.arms, args.capitals, args.costs)
    except ValueError as exc:
        print(f"::error::v4_cells_plan: {exc}: refused", file=sys.stderr, flush=True)
        return 1
    lines = f"data_run={data_run}\nmatrix={matrix_json(cells)}\ncells={len(cells)}\n"
    try:
        with args.github_output.open("a", encoding="ascii", newline="\n") as output:
            output.write(lines)
    except OSError as exc:
        print(
            f"::error::v4_cells_plan: writing the output file failed: {type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        return 1
    print(f"v4_cells_plan: {len(cells)} cells planned for data run {data_run}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
