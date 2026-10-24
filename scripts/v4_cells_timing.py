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
one peak-memory line, a clean exit status, no terminating signal), a cell folder without
``records.jsonl``, and a
``timing.json`` that already exists (a cell's files are never replaced); a ``timing.json`` whose
write fails is removed again, so no partial file is left. Standard output carries the cell's id,
seconds, megabytes and bytes: times and sizes only, never a price.

``--time-file diagnose.time --diagnosis-dir diagnosis`` times the ``diagnose`` job's own step the
same way, as the proxy for the registered run's verdict step and its 2 GB memory limit: it writes
``<diagnosis dir>/diagnose-timing.json``, one line of JSON with ``step`` (``diagnose``),
``wall_seconds``, ``peak_rss_mb`` and ``exit_status``. The diagnosis exits 1 when it refused a
cell but wrote the diagnosis of the others, so here a report of a command that exited 1 is
timed too, with its status; the folder must exist (the diagnosis made it) and the file must not.
The ``analysis`` job of ``.github/workflows/v4-run.yml`` times its diagnosis the same way.

``--time-file verdict.time --verdict-dir verdict`` times the verdict step of v4-run.yml's
``verdict`` job (``scripts/v4_verdict.py``) the same way: it writes
``<verdict dir>/verdict-timing.json`` with ``step`` (``verdict``), ``wall_seconds``,
``peak_rss_mb`` and ``exit_status``, in a folder that must exist, and never over a file. A
verdict that failed (it exits 1 having written nothing, or is killed) is timed too, with its
status: that is the run a timing run must not lose, and the workflow makes the folder for it.
For both steps, a command killed by a signal N (out of memory, say), whose exit status GNU time
leaves undefined, is timed with 128 + N, the status GNU time then exits with. The three targets
exclude each other. Standard output carries the step's seconds, megabytes and exit status: times
only, never a count of cells, an outcome or the verdict.
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
DIAGNOSE_TIMING_FILE = "diagnose-timing.json"
VERDICT_TIMING_FILE = "verdict-timing.json"

# GNU time -v prints "h:mm:ss" from one hour on, and "m:ss.ss" below it.
_ELAPSED_LINE = re.compile(
    r"^[ \t]*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (?P<value>\S*)[ \t]*$", re.MULTILINE
)
_PEAK_LINE = re.compile(
    r"^[ \t]*Maximum resident set size \(kbytes\): (?P<value>[0-9]+)[ \t]*$", re.MULTILINE
)
_EXIT_LINE = re.compile(r"^[ \t]*Exit status: (?P<value>[0-9]+)[ \t]*$", re.MULTILINE)
_SIGNAL_LINE = re.compile(
    r"^[ \t]*Command terminated by signal (?P<value>[0-9]+)[ \t]*$", re.MULTILINE
)
_CLOCK = re.compile(
    r"(?:(?P<hours>[0-9]+):)?(?P<minutes>[0-9]{1,2}):(?P<seconds>[0-9]{2}(?:\.[0-9]+)?)"
)


@dataclass(frozen=True, slots=True)
class Timing:
    wall_seconds: Decimal
    peak_rss_kb: int
    exit_status: int = 0


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


def parse_time_output(text: str, *, allow_failure: bool = False) -> Timing:
    """The wall seconds and peak resident kilobytes of one ``/usr/bin/time -v`` report of a
    command that exited 0; anything else is a ``ValueError``. With ``allow_failure`` a command
    that exited with another status is timed too, with that status (one exit line at most).

    A command killed by a signal (the kernel's out-of-memory kill, say) is reported by GNU time as
    ``Command terminated by signal N`` with ``Exit status: 0``, its exit status being undefined:
    with ``allow_failure`` it is timed with the status GNU time itself then exits with, 128 + N;
    without, it is refused, as a failed command is."""
    wall = _wall_seconds(_one(_ELAPSED_LINE, text, "elapsed wall clock"))
    peak = int(_one(_PEAK_LINE, text, "maximum resident set size"))
    if peak <= 0:
        raise ValueError("the maximum resident set size is not positive")
    statuses = [int(status) for status in _EXIT_LINE.findall(text)]
    signals = [int(signal) for signal in _SIGNAL_LINE.findall(text)]
    if len(signals) > 1:
        raise ValueError(f"{len(signals)} terminating signal lines, expected one at most")
    if allow_failure:
        if len(statuses) > 1:
            raise ValueError(f"{len(statuses)} exit status lines, expected one at most")
        if signals:
            return Timing(wall, peak, 128 + signals[0])
        return Timing(wall, peak, statuses[0] if statuses else 0)
    if signals:
        raise ValueError(f"the timed command was terminated by signal {signals[0]}")
    for status in statuses:
        if status != 0:
            raise ValueError(f"the timed command exited with status {status}")
    return Timing(wall, peak)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v4_cells_timing.py", description=__doc__)
    parser.add_argument("--time-file", type=Path, required=True, help="the /usr/bin/time -v output")
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--cell-dir", type=Path, help="out/<cell id>, with records")
    target.add_argument(
        "--diagnosis-dir", type=Path, help="the diagnosis folder, for diagnose-timing.json"
    )
    target.add_argument(
        "--verdict-dir", type=Path, help="the verdict folder, for verdict-timing.json"
    )
    return parser


def _fail(reason: str) -> int:
    print(f"::error::v4_cells_timing: {reason}", file=sys.stderr, flush=True)
    return 1


def _read_time_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="ascii", errors="replace")
    except OSError as exc:
        _fail(
            f"cannot read the time file ({type(exc).__name__}): "
            "is GNU time installed at /usr/bin/time?"
        )
        return None


def _create(path: Path, document: dict[str, object]) -> None:
    """Create ``path`` exclusively (mode "x": a file already there is never replaced) with
    ``document`` as one line of JSON. A write or close that fails removes the file it made, so
    no partial file is left behind: the diagnosis refuses a cell whose ``timing.json`` is not the
    cell's, and the workflow keeps a replay whose timing failed, without its timing."""
    handle = path.open("x", encoding="ascii", newline="\n")
    try:
        with handle:
            handle.write(json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _step_timing(step: str, file_name: str, time_file: Path, folder: Path) -> int:
    """``--diagnosis-dir`` and ``--verdict-dir``: one step's ``file_name`` in ``folder``, with
    ``step`` (``diagnose`` or ``verdict``) and its exit status (module docstring)."""
    text = _read_time_file(time_file)
    if text is None:
        return 1
    try:
        timing = parse_time_output(text, allow_failure=True)
    except ValueError as exc:
        return _fail(f"the time file is not a GNU time -v report: {exc}")
    seconds = timing.wall_seconds.quantize(Decimal("0.01"))
    megabytes = (Decimal(timing.peak_rss_kb) / 1024).quantize(Decimal("0.1"))
    document = {
        "step": step,
        "wall_seconds": float(seconds),
        "peak_rss_mb": float(megabytes),
        "exit_status": timing.exit_status,
    }
    try:
        # In a folder that must exist: the step's own files are never replaced.
        _create(folder / file_name, document)
    except OSError as exc:
        return _fail(f"cannot create {file_name} ({type(exc).__name__})")
    print(
        f"v4_cells_timing: {step}: {seconds} s, {megabytes} MB peak, "
        f"exit status {timing.exit_status}",
        flush=True,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.diagnosis_dir is not None:
        return _step_timing("diagnose", DIAGNOSE_TIMING_FILE, args.time_file, args.diagnosis_dir)
    if args.verdict_dir is not None:
        return _step_timing("verdict", VERDICT_TIMING_FILE, args.time_file, args.verdict_dir)
    cell = args.cell_dir.name
    text = _read_time_file(args.time_file)
    if text is None:
        return 1
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
        # A cell's files are never replaced.
        _create(args.cell_dir / TIMING_FILE, document)
    except OSError as exc:
        return _fail(f"cannot create {TIMING_FILE} of {cell} ({type(exc).__name__})")
    print(
        f"v4_cells_timing: {cell}: {seconds} s, {megabytes} MB peak, {records_bytes} record bytes",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
