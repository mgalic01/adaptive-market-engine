"""Refuse a data run that reaches 2025: the v4-cells workflow's reserved-window guard.

Owner decision v4-d03: no market data from 2025-01 onward is executed before the registered run.
``.github/workflows/v4-cells.yml`` replays the diagnostic run's cells over the packs of a
``v4-data`` run, and runs this guard on the downloaded data directory in every job that reads the
packs (``plan``, each ``cell`` before the cell, and ``diagnose``).

``--data D [--latest-month YYYY-MM]``: reads ``D/data.json`` (format ``v4-data/1``) and nothing
else in ``D``. Exit 0 only if its ``end_month`` is not after the latest month, which is
``2024-12`` unless an earlier one is given. Exit 1, writing nothing, when the data run ends after
the latest month, when the latest month asked for is after 2024-12 (the window cannot be widened
from the command line) or is not a month, and when ``data.json`` is missing, is not ASCII JSON
with no duplicate key, is not an object of that format, or lacks a well-formed ``end_month`` or
``config_sha256`` (a SHA-256, a pin and not market data).

Output: one line with the end month, the config pin and the verdict. Nothing else of
``data.json`` and nothing from a refused file is echoed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DATA_FORMAT = "v4-data/1"
DATA_FILE = "data.json"
# The reserved window opens at 2025-01: no run of this workflow may end later than this.
LATEST_ALLOWED = "2024-12"

_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_PIN = re.compile(r"[0-9a-f]{64}")


def _refuse(reason: str) -> int:
    """One line of standard error, the exit status 1."""
    print(f"::error::v4_cells_guard: {reason}: refused", file=sys.stderr, flush=True)
    return 1


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """An object with no duplicate key: a reader taking the first value and one taking the last
    must never see two different months."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v4_cells_guard.py", description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="the data directory")
    parser.add_argument(
        "--latest-month",
        default=LATEST_ALLOWED,
        help=f"the latest end_month to accept, YYYY-MM, at most {LATEST_ALLOWED} (the default)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    latest = args.latest_month
    if _MONTH.fullmatch(latest) is None:
        return _refuse("the latest month is not a month, YYYY-MM")
    if latest > LATEST_ALLOWED:  # YYYY-MM strings order like the months they name
        return _refuse(f"the latest month {latest} is after {LATEST_ALLOWED}")
    try:
        text = (args.data / DATA_FILE).read_bytes().decode("ascii")
        document = json.loads(text, object_pairs_hook=_unique_keys)
    except (OSError, ValueError):  # UnicodeDecodeError, JSONDecodeError: ValueErrors
        return _refuse(f"{DATA_FILE} is missing, unreadable or not JSON with unique keys")
    if not isinstance(document, dict):
        return _refuse(f"{DATA_FILE} is not a JSON object")
    if document.get("format") != DATA_FORMAT:
        return _refuse(f"{DATA_FILE} is not of format {DATA_FORMAT}")
    end_month = document.get("end_month")
    if not isinstance(end_month, str) or _MONTH.fullmatch(end_month) is None:
        return _refuse(f"{DATA_FILE} has no end_month of the form YYYY-MM")
    pin = document.get("config_sha256")
    if not isinstance(pin, str) or _PIN.fullmatch(pin) is None:
        return _refuse(f"{DATA_FILE} has no config_sha256 of 64 lowercase hex digits")
    if end_month > latest:
        return _refuse(f"the data run's end_month {end_month} is after the latest month {latest}")
    print(
        f"v4_cells_guard: data end_month {end_month}, config_sha256 {pin}: "
        f"accepted (latest allowed month {latest})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
