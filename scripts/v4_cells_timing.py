"""The v4-cells workflow's timing helper: a cell's wall time and peak memory, kept with the cell.

Each ``cell`` job of ``.github/workflows/v4-cells.yml`` runs ``v4_cell.py`` under
``/usr/bin/time -v -o out/<cell id>.time`` (GNU time, which ubuntu runners have at that path). The
run doubles as the spec's timing run before registration, so the numbers it sizes the registered
run by are kept with the cell:

``--time-file out/<cell id>.time --cell-dir out/<cell id>`` writes ``<cell dir>/timing.json``, one
line of JSON with ``cell`` (the folder's name), ``wall_seconds``, ``peak_rss_mb`` (the peak
resident set size, kilobytes over 1024, one decimal) and ``records_bytes`` (the size of the
cell's ``records.jsonl``, which is about 135 MB for a V4 cell).

It refuses, writing nothing and exiting 1: a time file that is missing (the runner has no
``/usr/bin/time``), one that is not the report of GNU ``time -v`` (exactly one elapsed line and
one peak-memory line, a clean exit status), a cell folder without ``records.jsonl``, and a
``timing.json`` that already exists (a cell's files are never replaced). Standard output carries
the cell's id, seconds, megabytes and bytes: times and sizes only, never a price.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from crypto_grid_bot.v4.engine.run import RECORDS_FILE

TIMING_FILE = "timing.json"

# GNU time -v prints "h:mm:ss" from one hour on, and "m:ss.ss" below it.
_ELAPSED_LINE = re.compile(
    r"^[ \t]*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?P<value>\S*)[ \t]*$", re.MULTILINE
)
_PEAK_LINE = re.compile(
    r"^[ \t]*Maximum resident set size \(kbytes\): (?P<value>[0-9]+)[ \t]*$", re.MULTILINE
)
_EXIT_LINE = re.compile(r"^[ \t]*Exit status: (?P<value>[0-9]+)[ \t]*$", re.MULTILINE)
_CLOCK = re.compile(
    r"(?:(?P<hours>[0-9]+):)?(?P<minutes>[0-9]{1,2}):(?P<seconds>[0-9]{2}(?:\.[0-9]+)?)"
)


@dataclass(frozen=True, slots=True)
class Timing:
    wall_seconds: Decimal
    peak_rss_kb: int


def _one(pattern: re.Pattern[str], text: str, what: str) -> str:
    found = pattern.findall(text)
    if len(found) != 1:
        raise ValueError(f"{len(found)} {what} lines, expected one: not GNU time -v output")
    return str(found[0])


def _wall_seconds(clock: str) -> Decimal:
    match = _CLOCK.fullmatch(clock)
    if match is None:
        raise ValueError(f"the elapsed time {clock!r:.40} is not h:mm:ss.ss or m:ss.ss")
    minutes, seconds = int(match["minutes"]), Decimal(match["seconds"])
    if minutes >= 60 or seconds >= 60:
        raise ValueError(f"the elapsed time {clock!r:.40} has minutes or seconds of 60 or more")
    hours = int(match["hours"] or 0)
    return hours * 3600 + minutes * 60 + seconds


def parse_time_output(text: str) -> Timing:
    """The wall seconds and peak resident kilobytes of one ``/usr/bin/time -v`` report of a
    command that exited 0; anything else is a ``ValueError``."""
    wall = _wall_seconds(_one(_ELAPSED_LINE, text, "elapsed wall clock"))
    peak = int(_one(_PEAK_LINE, text, "maximum resident set size"))
    if peak <= 0:
        raise ValueError("the maximum resident set size is not positive")
    for status in _EXIT_LINE.findall(text):
        if int(status) != 0:
            raise ValueError(f"the timed command exited with status {status}")
    return Timing(wall, peak)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v4_cells_timing.py", description=__doc__)
    parser.add_argument("--time-file", type=Path, required=True, help="the /usr/bin/time -v output")
    parser.add_argument("--cell-dir", type=Path, required=True, help="out/<cell id>, with records")
    return parser


def _fail(reason: str) -> int:
    print(f"::error::v4_cells_timing: {reason}", file=sys.stderr, flush=True)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cell = args.cell_dir.name
    try:
        text = args.time_file.read_text(encoding="ascii", errors="replace")
    except OSError as exc:
        return _fail(
            f"cannot read the time file ({type(exc).__name__}): "
            "is GNU time installed at /usr/bin/time?"
        )
    try:
        timing = parse_time_output(text)
    except ValueError as exc:
        return _fail(f"the time file is not a clean GNU time -v report: {exc}")
    try:
        records_bytes = (args.cell_dir / RECORDS_FILE).stat().st_size
    except OSError as exc:
        return _fail(f"cannot size {RECORDS_FILE} of {cell} ({type(exc).__name__})")
    seconds = timing.wall_seconds.quantize(Decimal("0.01"))
    megabytes = (Decimal(timing.peak_rss_kb) / 1024).quantize(Decimal("0.1"))
    document = {
        "cell": cell,
        "wall_seconds": float(seconds),
        "peak_rss_mb": float(megabytes),
        "records_bytes": records_bytes,
    }
    try:
        # Mode "x": a cell's files are never replaced.
        with (args.cell_dir / TIMING_FILE).open("x", encoding="ascii", newline="\n") as handle:
            handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    except OSError as exc:
        return _fail(f"cannot create {TIMING_FILE} of {cell} ({type(exc).__name__})")
    print(
        f"v4_cells_timing: {cell}: {seconds} s, {megabytes} MB peak, {records_bytes} record bytes",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
