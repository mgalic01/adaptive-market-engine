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

``--data-run ID`` instead checks the data run itself, before anything of it is downloaded (the
``plan`` job pipes ``gh api repos/<repository>/actions/runs/<ID>`` into it, so the download of a
run that is not the diagnostic data run never starts): it reads that run's JSON from standard
input (at most ``MAX_RUN_BYTES``, UTF-8 JSON, no duplicate key) and exits 0 only if
``check_data_run`` accepts it: its ``id`` is ``ID``, its ``path`` is the v4-data workflow's, its
``display_title`` is that workflow's run name for the full stage with the pre-2025 config, and its
``conclusion`` is ``success``. A run of the full config (data to 2026-09) or of the discover
stage, a failed or unfinished run, a run of another workflow or anything that is not such a JSON
object exits 1. Its output is the run's id and the verdict, never a field of the run.
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

# The data run's workflow, and its run name (``run-name: v4-data <stage> <config>``) for the full
# stage with the pre-2025 config: the only data run whose packs a cells run may download.
DATA_WORKFLOW_PATH = ".github/workflows/v4-data.yml"
DATA_RUN_TITLE = "v4-data full config/v4_data_pre2025.json"
# A run's JSON is a few kilobytes; anything far larger is not one.
MAX_RUN_BYTES = 1_000_000

_MONTH = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_RUN_ID = re.compile(r"[1-9][0-9]{0,19}")
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
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--data", type=Path, help="the data directory")
    target.add_argument(
        "--data-run", help="the data run's id; its JSON from the GitHub API on standard input"
    )
    parser.add_argument(
        "--latest-month",
        default=LATEST_ALLOWED,
        help=f"the latest end_month to accept, YYYY-MM, at most {LATEST_ALLOWED} (the default)",
    )
    return parser


def check_data_run(run: object, run_id: str) -> None:
    """Accept only the diagnostic data run: ``run`` is the GitHub API's JSON object of workflow
    run ``run_id``, a successful run of the v4-data workflow's full stage with the pre-2025
    config. Anything else is a ``ValueError`` whose message names no field's value."""
    if _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("the run id is not 1 to 20 digits with no leading zero")
    if not isinstance(run, dict):
        raise ValueError("the API's answer is not a JSON object")
    if type(run.get("id")) is not int or run["id"] != int(run_id):
        raise ValueError("the API's answer is of another run")
    if run.get("path") != DATA_WORKFLOW_PATH:
        raise ValueError(f"it is not a run of {DATA_WORKFLOW_PATH}")
    if run.get("display_title") != DATA_RUN_TITLE:
        raise ValueError(f"it is not the run named {DATA_RUN_TITLE!r}")
    if run.get("conclusion") != "success":
        raise ValueError("it did not finish with the conclusion success")


def _check_run(run_id: str) -> int:
    """``--data-run``: the run's JSON from standard input, through ``check_data_run``."""
    shown = run_id if _RUN_ID.fullmatch(run_id) else "(not a run id)"
    try:
        raw = sys.stdin.buffer.read(MAX_RUN_BYTES + 1)
        if len(raw) > MAX_RUN_BYTES:
            raise ValueError(f"the API's answer is larger than {MAX_RUN_BYTES} bytes")
        # UTF-8, not ASCII: the answer holds free text (the head commit's message, say).
        run = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_keys)
        check_data_run(run, run_id)
    except (OSError, ValueError) as exc:  # a decoding or JSON error is a ValueError
        reason = str(exc) if type(exc) is ValueError else type(exc).__name__
        return _refuse(f"data run {shown}: {reason}")
    print(
        f"v4_cells_guard: data run {run_id}: a successful {DATA_RUN_TITLE!r} run: accepted",
        flush=True,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.data_run is not None:
        return _check_run(args.data_run)
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
