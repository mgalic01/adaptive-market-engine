"""V4.0's verdict step: the verdict of a run's cells from their ``summary.json`` files and receipts
alone, and the first page of the run summary.

The ``verdict`` job of ``.github/workflows/v4-run.yml`` (plan
``docs/superpowers/plans/2026-10-24-v4-step4b-pipeline.md``, Task 4) runs this after the cells.
It adds no trading rule: it applies the spec's pass rule (v4-d04, ``v4.verdict.rule``) to what the
cells wrote, and it never reads a record. It is resumable (ruling V13): a run that stops, for any
reason, is continued by running it again with the same arguments.

``--summaries S --expected E --progress P --out O [--dispatch-reasons F]``:

1. refuses an ``O`` that already holds ``verdict.json`` or ``verdict.md``; reads ``E`` with
   ``inputs.read_expected``; refuses an ``E`` of mode ``registered`` without ``F`` (a registered
   run's other dispatches are its verdict's input); reads ``F`` if there is one (canonical JSON
   ``{"format": "v4-dispatch-check-1", "earlier": [<non-empty strings>]}``, which
   ``v4_registration.py dispatch-check --judge-all`` writes: the earlier dispatches of the same
   registration; any other shape is refused, and without ``F`` (a rehearsal or a timing run)
   there are none); lists the subfolders of ``S`` in sorted order (the workflow downloads each
   cell's artifact into one);
   and computes the **inputs digest**: the SHA-256 of the canonical JSON of ``E``'s own SHA-256,
   each subfolder's name with the SHA-256 of its ``summary.json`` and of its ``receipt.json`` (null
   when it has none) and the dispatch reasons;
2. if ``P/progress.json`` exists it must be a progress file (canonical JSON of the format
   ``v4-verdict-progress-1``) of the same inputs digest, and every record in it must be what this
   step writes (a cell's facts are its listed file's, a check's ``holds`` is what its sides say),
   otherwise the step refuses and writes nothing, the progress file included: a changed input
   needs a fresh progress folder. If it does not exist, ``P`` is created;
3. for each subfolder not yet in the progress, in order: ``inputs.read_cell`` accepts it (its
   facts are recorded) or refuses it (its step and reason are recorded); the file must still be the
   one that was listed. The progress is saved after each folder;
4. V3: a folder with an attempt other than 1 is a re-run (the cell has a re-run, so the verdict is
   incomplete whatever the cell; a first attempt that was accepted stays accepted, so a stopped
   ``v4_main`` still fails); two accepted folders of one cell refuse both (step ``duplicate``);
   ``missing`` is the expected cells without an accepted folder. A refused cell counts as missing
   and its outcome is never read (V2);
5. each of the 8 checks (4 conditions x 2 capitals: ``rule.condition_1`` to ``condition_4``, from
   the pass rule's cells only) and each V11 pair not yet in the progress (every non-v3 arm at each
   capital and cost against ``hold_universe`` and against ``v3_as_built`` at the same capital and
   cost, by ``rule.measure_against_hold`` and ``measure_against_v3``) is measured when all its
   cells are accepted. A measure loads the marks of at most two cells (``inputs.read_marks``; each
   file must still hash to its accepted facts' ``summary_sha256``), keeps the numbers, saves the
   progress and drops the marks. A pair that cannot be measured is recorded with its reason. The
   checks of conditions 1 and 2 also list their skipped hours (``skipped_ms``): the hour opens of
   their range (``expected.window``; v3's period) that are not common boundaries of their two
   arms, as the spec says hours missing from any source are "skipped for all arms alike and
   listed"; a pair records only how many (``skipped_hours``);
6. ``rule.decide`` gives the verdict from the accepted cells only (refused and absent cells are
   ``missing``, never ``accepted``) and the expected file's cells, every one of which counts
   (owner decision v4-d25); ``report.verdict_document`` and ``report.render_verdict_page``
   build ``O/verdict.json`` (canonical JSON) and ``O/verdict.md`` (the page), both created
   exclusively (V14); if the second cannot be written, the first is removed again, and so is a
   folder this step made, so a failed write leaves no file.

The progress file holds numbers, never marks (V13): the cells' facts and the checks' and pairs'
measures, replaced atomically (a temporary file, then ``os.replace``) after each step. The outputs
hold no timestamp and no path, so a resumed run writes the same bytes as an uninterrupted one.

**Exit status.** 0 once both files are written, whatever the verdict (a stopped, incomplete or
failing run is a verdict, not an error); 1 for every refusal or failure, with no output written; 2
for bad arguments (argparse's own). An interrupt (``KeyboardInterrupt``) is not caught: it leaves
the last whole progress file and no output.

**Output.** Standard output carries three lines of counts: the folders and how many cells were
accepted, refused and missing (and how many folders were read and resumed), the measures and how
many were computed and resumed, and the files written. Never a price, an equity, a return, a
cell's outcome or the verdict (owner rule: public logs). A failure is one line on standard error
naming the step and the exception's type, never its text. The page and ``verdict.json`` hold the
results and stay on the owner's PC (the workflow uploads them as a 1-day artifact).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine.arms import ARMS, CAPITALS, COST_MULTIPLES
from crypto_grid_bot.v4.engine.run import RECEIPT_FILE
from crypto_grid_bot.v4.engine.summary import SUMMARY_FILE
from crypto_grid_bot.v4.engine.v3_as_built import V3_ARM
from crypto_grid_bot.v4.verdict.inputs import (
    MAX_SUMMARY_BYTES,
    CellFacts,
    CellRefused,
    Expected,
    facts_from_record,
    facts_record,
    read_cell,
    read_expected,
    read_marks,
)
from crypto_grid_bot.v4.verdict.report import (
    PROGRESS_FORMAT,
    check_from_record,
    check_record,
    measure_from_record,
    measure_record,
    read_canonical_json,
    read_dispatch_reasons,
    render_verdict_page,
    rerun_cells,
    verdict_document,
)
from crypto_grid_bot.v4.verdict.rule import (
    CAPITALS_JUDGED,
    CONDITION_LABELS,
    MAIN_ARM,
    Incomputable,
    Mark,
    condition_1,
    condition_2,
    condition_3,
    condition_4,
    decide,
    measure_against_hold,
    measure_against_v3,
    skipped_against_v3,
    skipped_hours,
)

JSON_FILE = "verdict.json"
MD_FILE = "verdict.md"
OUTPUT_FILES = (JSON_FILE, MD_FILE)
PROGRESS_FILE = "progress.json"
HOLD_ARM = "hold_universe"
MAX_PROGRESS_BYTES = 256 << 20
_PROGRESS_KEYS = frozenset({"format", "inputs", "cells", "checks", "pairs"})
# The kinds of a step: the conditions ``c1`` to ``c4`` and a V11 pair, ``hold`` (against
# hold_universe) or ``v3`` (against v3_as_built). Conditions 3 and 4 read the facts only.
_UNMARKED = ("c3", "c4")


def check_key(capital: int, condition: int) -> str:
    """The progress key of a check: ``<capital>:<condition>``."""
    return f"{capital}:{condition}"


def pair_key(cell_id: str, kind: str) -> str:
    """The progress key of a V11 pair: ``<cell id>:hold`` or ``<cell id>:v3``."""
    return f"{cell_id}:{kind}"


def _non_v3_cells() -> list[str]:
    return [
        f"{arm}-{capital}-{multiple}x"
        for arm, spec in ARMS.items()
        if spec.family != "v3"
        for capital in CAPITALS
        for multiple in COST_MULTIPLES
    ]


VALID_CHECK_KEYS = frozenset(
    check_key(capital, condition) for capital in CAPITALS_JUDGED for condition in CONDITION_LABELS
)
VALID_PAIR_KEYS = frozenset(
    pair_key(cell, kind) for cell in _non_v3_cells() for kind in ("hold", "v3")
)


# ---- stopping ---------------------------------------------------------------------------------


class _Stop(Exception):
    """A refusal or failure that writes nothing: the ``step`` and the exception that caused it."""

    def __init__(self, step: str, cause: BaseException | None = None) -> None:
        super().__init__(step)
        self.step = step
        self.cause = cause


class _Changed(_Stop):
    """An input that is not the one the digest, the listing or the accepted facts name."""


def _say(line: str) -> None:
    """A line of standard output: counts only."""
    print(line, flush=True)


def _fail(step: str, exc: BaseException | None = None) -> int:
    """One line of standard error, the failed ``step`` and the exception's type, never its
    message; returns the exit status 1."""
    kind = "" if exc is None else f": {type(exc).__name__}"
    print(f"v4_verdict: {step}{kind}", file=sys.stderr, flush=True)
    return 1


# ---- the inputs -------------------------------------------------------------------------------


def _file_digest(path: Path) -> str | None:
    """The SHA-256 of a regular file, streamed; None for anything that is not one (or cannot be
    read) and a size marker for a file over ``MAX_SUMMARY_BYTES`` (``read_cell`` refuses it)."""
    try:
        if path.is_symlink() or not path.is_file():
            return None
        size = path.stat().st_size
        if size > MAX_SUMMARY_BYTES:
            return f"too-large:{size}"
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def inputs_digest(
    expected_path: Path,
    listing: Mapping[str, tuple[str | None, str | None]],
    dispatches: Sequence[str],
) -> str:
    """The inputs digest (module docstring, step 1): ``E``'s SHA-256, every subfolder's name with
    its ``summary.json``'s and ``receipt.json``'s SHA-256 and the dispatch reasons."""
    document = {
        "expected": _file_digest(expected_path),
        "folders": [[name, summary, receipt] for name, (summary, receipt) in listing.items()],
        "dispatches": list(dispatches),
    }
    return hashlib.sha256(_canonical(document)).hexdigest()


def _expected(path: Path) -> Expected:
    try:
        return read_expected(path)
    except ValueError as exc:
        raise _Stop("refused: reading the expected file", exc) from None


def _dispatches(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return ()
    try:
        return read_dispatch_reasons(path)
    except ValueError as exc:
        raise _Stop("refused: reading the dispatch reasons file", exc) from None


def _folders(root: Path) -> list[Path]:
    try:
        return sorted((path for path in Path(root).iterdir() if path.is_dir()), key=_name)
    except OSError as exc:
        raise _Stop("refused: reading the summaries folder", exc) from None


def _name(path: Path) -> str:
    return path.name


# ---- the progress file ------------------------------------------------------------------------


def save_progress(path: Path, document: Mapping[str, object]) -> None:
    """Replace the progress file atomically: write a temporary file beside it, then
    ``os.replace``, so a stop at any moment leaves the last whole file."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(_canonical(dict(document)))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _new_progress(digest: str) -> dict[str, Any]:
    return {"format": PROGRESS_FORMAT, "inputs": digest, "cells": {}, "checks": {}, "pairs": {}}


def _load_progress(
    path: Path,
    digest: str,
    listing: Mapping[str, tuple[str | None, str | None]],
    expected: Expected,
) -> dict[str, Any]:
    """The progress file of the same inputs, every record checked (module docstring, step 2)."""
    try:
        document = read_canonical_json(path, MAX_PROGRESS_BYTES, "the progress file")
    except ValueError as exc:
        raise _Stop("refused: reading the progress file", exc) from None
    if (
        not isinstance(document, dict)
        or set(document) != _PROGRESS_KEYS
        or document["format"] != PROGRESS_FORMAT
    ):
        raise _Stop("refused: the progress file is not a v4-verdict-progress-1 file")
    if document["inputs"] != digest:
        raise _Changed("refused: the inputs changed since the progress was written")
    try:
        _check_progress(document, listing, expected)
    except ValueError as exc:
        raise _Stop(
            "refused: the progress file holds a record this step did not write", exc
        ) from None
    return document


def _check_progress(
    document: Mapping[str, Any],
    listing: Mapping[str, tuple[str | None, str | None]],
    expected: Expected,
) -> None:
    """Every record of a progress file is exactly what the step writes; else a ``ValueError``."""
    cells, checks, pairs = document["cells"], document["checks"], document["pairs"]
    if not all(isinstance(table, dict) for table in (cells, checks, pairs)):
        raise ValueError("the progress file's cells, checks and pairs are not objects")
    for folder, entry in cells.items():
        if folder not in listing:
            raise ValueError("a progress entry is of a folder that is not listed")
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("a cell's progress entry is not one of facts or refused")
        if "facts" in entry:
            facts = facts_from_record(entry["facts"])
            if (
                facts.folder != folder
                or facts.summary_sha256 != listing[folder][0]
                or facts.cell_id not in expected.cells
            ):
                raise ValueError("a cell's facts are not those of its listed folder")
        else:
            refusal = entry.get("refused")
            if (
                not isinstance(refusal, dict)
                or set(refusal) != {"step", "reason"}
                or not all(type(item) is str for item in refusal.values())
            ):
                raise ValueError("a cell's refusal is not a step and a reason")
    for key, record in checks.items():
        check = check_from_record(record)
        if key not in VALID_CHECK_KEYS or key != check_key(check.capital, check.condition):
            raise ValueError("a check's record is not of its key")
    for key, record in pairs.items():
        if key not in VALID_PAIR_KEYS:
            raise ValueError("a pair's key is not a non-v3 cell against hold or v3")
        _check_pair(record)


def _check_pair(record: object) -> None:
    if not isinstance(record, dict):
        raise ValueError("a pair's record is not an object")
    if set(record) == {"incomputable"}:
        if type(record["incomputable"]) is not str:
            raise ValueError("a pair's reason is not a string")
    elif set(record) == {"main", "other", "skipped_hours"}:
        measure_from_record(record["main"])
        measure_from_record(record["other"])
        skipped = record["skipped_hours"]
        if type(skipped) is not int or skipped < 0:
            raise ValueError("a pair's skipped hours are not a count")
    else:
        raise ValueError("a pair's record is neither a measure pair nor an incomputable one")


# ---- reading the cells ------------------------------------------------------------------------


def _read_one(folder: Path, expected: Expected, listed: str | None) -> dict[str, object]:
    """The progress entry of one folder: its facts, or its refusal. The file must still be the
    one that was listed."""
    entry: dict[str, object]
    try:
        facts = read_cell(folder, expected)
    except CellRefused as refusal:
        entry = {"refused": {"step": refusal.step, "reason": refusal.reason}}
    else:
        if facts.summary_sha256 != listed:
            raise _Changed("refused: a summary changed after the inputs were listed")
        entry = {"facts": facts_record(facts)}
    if _file_digest(folder / SUMMARY_FILE) != listed:
        raise _Changed("refused: a summary changed after the inputs were listed")
    return entry


@dataclass(frozen=True)
class Classified:
    """The folders judged (V1 to V3): the accepted cells by id (in the expected order), the
    refused folders by name (step, reason), the expected cells that are missing, and the cells
    that have a re-run folder."""

    accepted: dict[str, CellFacts]
    refused: dict[str, tuple[str, str]]
    missing: list[str]
    reruns: list[str]


def classify(
    entries: Mapping[str, CellFacts | tuple[str, str]], cells: Sequence[str]
) -> Classified:
    """V3 over the cells' entries by folder name: two accepted folders of one cell refuse both
    (step ``duplicate``), a refused cell is missing (V2) and a re-run folder marks its cell."""
    groups: dict[str, list[tuple[str, CellFacts]]] = {}
    refused: dict[str, tuple[str, str]] = {}
    for folder, entry in entries.items():
        if isinstance(entry, CellFacts):
            groups.setdefault(entry.cell_id, []).append((folder, entry))
        else:
            refused[folder] = entry
    accepted: dict[str, CellFacts] = {}
    for cell_id in cells:
        group = groups.get(cell_id, [])
        if len(group) == 1:
            accepted[cell_id] = group[0][1]
    for group in groups.values():
        if len(group) > 1:
            for folder, _ in group:
                refused[folder] = ("duplicate", "another accepted folder holds the same cell")
    missing = [cell for cell in cells if cell not in accepted]
    return Classified(accepted, refused, missing, rerun_cells(refused))


# ---- the measures -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Step:
    """One measure still to make: the progress ``section`` and ``key`` it fills, its ``kind`` (a
    condition ``c1`` to ``c4``, or a V11 pair ``hold`` or ``v3``) and its one or two cells."""

    section: str
    key: str
    kind: str
    first: CellFacts
    second: CellFacts | None = None


def plan_steps(accepted: Mapping[str, CellFacts]) -> list[_Step]:
    """The measures of the accepted cells, in order: each capital's four conditions (from the pass
    rule's 1x and 2x ``v4_main`` cells), then each non-v3 cell's two V11 pairs. A measure whose
    cells are not all accepted is not planned."""
    steps: list[_Step] = []
    for capital in CAPITALS_JUDGED:
        main_1x = accepted.get(f"{MAIN_ARM}-{capital}-1x")
        main_2x = accepted.get(f"{MAIN_ARM}-{capital}-2x")
        hold = accepted.get(f"{HOLD_ARM}-{capital}-1x")
        v3 = accepted.get(f"{V3_ARM}-{capital}-1x")
        if main_1x is not None and hold is not None:
            steps.append(_Step("checks", check_key(capital, 1), "c1", main_1x, hold))
        if main_1x is not None and v3 is not None:
            steps.append(_Step("checks", check_key(capital, 2), "c2", main_1x, v3))
        if main_2x is not None:
            steps.append(_Step("checks", check_key(capital, 3), "c3", main_2x))
        if main_1x is not None:
            steps.append(_Step("checks", check_key(capital, 4), "c4", main_1x))
    for cell_id in _non_v3_cells():
        cell = accepted.get(cell_id)
        if cell is None:
            continue
        for kind, other_arm in (("hold", HOLD_ARM), ("v3", V3_ARM)):
            other = accepted.get(f"{other_arm}-{cell.capital}-{cell.cost_multiple}x")
            if other is not None:
                steps.append(_Step("pairs", pair_key(cell_id, kind), kind, cell, other))
    return steps


def _marks_or_none(folder: Path) -> list[Mark] | None:
    try:
        return read_marks(folder)
    except CellRefused:
        return None


def _marks_of(root: Path, facts: CellFacts) -> list[Mark]:
    """The open marks of an accepted cell, if its file is still the accepted one before and
    after they are read (``read_marks`` ignores the digest); a failure summary has none."""
    if facts.marks == 0:
        return []
    folder = Path(root) / facts.folder
    path = folder / SUMMARY_FILE
    if _file_digest(path) != facts.summary_sha256:
        raise _Changed("refused: a summary changed after it was accepted")
    marks = _marks_or_none(folder)
    if marks is None or len(marks) != facts.marks or _file_digest(path) != facts.summary_sha256:
        raise _Changed("refused: a summary changed after it was accepted")
    return marks


def _compute(
    step: _Step,
    first_marks: Sequence[Mark],
    second_marks: Sequence[Mark],
    window: tuple[int, int],
) -> dict[str, object]:
    """The record of a measure, from its cells' facts and marks. ``window`` is the run's first and
    last hour open: the range condition 1 and the pairs against ``hold_universe`` skip hours in."""
    first, second = step.first, step.second
    if step.kind == "c3":
        return check_record(condition_3(first))
    if step.kind == "c4":
        return check_record(condition_4(first))
    if second is None:
        raise ValueError("a measure against another cell needs that cell")
    if step.kind == "c1":
        return check_record(condition_1(first, first_marks, second, second_marks, window=window))
    if step.kind == "c2":
        return check_record(condition_2(first, first_marks, second, second_marks))
    try:
        if step.kind == "hold":
            mine, theirs = measure_against_hold(first, first_marks, second, second_marks)
            skipped = skipped_hours(first_marks, second_marks, start_ms=window[0], end_ms=window[1])
        else:
            mine, theirs = measure_against_v3(first, first_marks, second, second_marks)
            skipped = skipped_against_v3(first_marks, second, second_marks)
    except Incomputable as why:
        return {"incomputable": str(why)}
    # A pair reports how many hours it skipped, not which (the checks list theirs).
    return {
        "main": measure_record(mine),
        "other": measure_record(theirs),
        "skipped_hours": len(skipped),
    }


def _run_step(root: Path, step: _Step, window: tuple[int, int]) -> dict[str, object]:
    """Make one measure, with the marks of at most two cells held, and drop them."""
    if step.kind in _UNMARKED:
        return _compute(step, (), (), window)
    first = _marks_of(root, step.first)
    if step.second is None or step.second.folder == step.first.folder:
        return _compute(step, first, first, window)
    second = _marks_of(root, step.second)
    return _compute(step, first, second, window)


# ---- the outputs ------------------------------------------------------------------------------


def _create(path: Path, data: bytes) -> None:
    """Create ``path`` exclusively with ``data``; a write that fails removes the file it made."""
    handle = path.open("xb")
    try:
        with handle:
            handle.write(data)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _write_outputs(out: Path, payload: bytes, page: bytes) -> None:
    """V14: both files, exclusively; if the second cannot be written the first is removed (and a
    folder this step made), so a failed write leaves no file."""
    made_out = not out.exists()
    created: list[Path] = []
    try:
        out.mkdir(parents=True, exist_ok=True)
        for target, data in ((out / JSON_FILE, payload), (out / MD_FILE, page)):
            _create(target, data)
            created.append(target)
    except BaseException:
        for target in created:
            target.unlink(missing_ok=True)
        if made_out:
            with contextlib.suppress(OSError):
                out.rmdir()
        raise


# ---- the command ------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="v4_verdict.py", description="The V4 run's verdict step (see the docstring)."
    )
    parser.add_argument(
        "--summaries", type=Path, required=True, help="the summaries: one subfolder per cell"
    )
    parser.add_argument("--expected", type=Path, required=True, help="the expected file")
    parser.add_argument(
        "--progress", type=Path, required=True, help="the folder of progress.json (resumable)"
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="the folder for verdict.json and verdict.md"
    )
    parser.add_argument(
        "--dispatch-reasons",
        type=Path,
        default=None,
        help="the dispatch check's file of earlier dispatches (required for a registered run); "
        "without it there are none",
    )
    return parser


def _read_cells(
    folders: Sequence[Path],
    listing: Mapping[str, tuple[str | None, str | None]],
    expected: Expected,
    progress: dict[str, Any],
    progress_path: Path,
) -> tuple[int, int]:
    """Module docstring, step 3: read each folder not yet in the progress and save the progress
    after each. Returns how many folders were read and how many were resumed."""
    cells: dict[str, Any] = progress["cells"]
    read = resumed = 0
    for folder in folders:
        if folder.name in cells:
            resumed += 1
            continue
        cells[folder.name] = _read_one(folder, expected, listing[folder.name][0])
        save_progress(progress_path, progress)
        read += 1
    return read, resumed


def _entries(
    progress: Mapping[str, Any], listing: Mapping[str, tuple[str | None, str | None]]
) -> dict[str, CellFacts | tuple[str, str]]:
    """The progress's cells in folder order: the facts of an accepted one, the step and reason of
    a refused one."""
    entries: dict[str, CellFacts | tuple[str, str]] = {}
    for name in listing:
        entry = progress["cells"][name]
        if "facts" in entry:
            entries[name] = facts_from_record(entry["facts"])
        else:
            entries[name] = (entry["refused"]["step"], entry["refused"]["reason"])
    return entries


def _measure(
    root: Path,
    steps: Sequence[_Step],
    window: tuple[int, int],
    progress: dict[str, Any],
    progress_path: Path,
) -> tuple[int, int]:
    """Module docstring, step 5: make each measure not yet in the progress and save the progress
    after each. Returns how many were computed and how many were resumed."""
    computed = resumed = 0
    for step in steps:
        table: dict[str, Any] = progress[step.section]
        if step.key in table:
            resumed += 1
            continue
        table[step.key] = _run_step(root, step, window)
        save_progress(progress_path, progress)
        computed += 1
    return computed, resumed


def _run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    held = [name for name in OUTPUT_FILES if (out / name).exists()]
    if held:
        raise _Stop(f"refused: the out folder already holds {', '.join(held)}")
    expected = _expected(args.expected)
    if expected.mode == "registered" and args.dispatch_reasons is None:
        # A registered run's other dispatches are an input of its verdict (Ruling G4): without
        # the dispatch check's file, none could be told from a check that never ran.
        raise _Stop("refused: a registered run's verdict needs --dispatch-reasons")
    dispatches = _dispatches(args.dispatch_reasons)
    folders = _folders(args.summaries)
    listing = {
        folder.name: (_file_digest(folder / SUMMARY_FILE), _file_digest(folder / RECEIPT_FILE))
        for folder in folders
    }
    digest = inputs_digest(args.expected, listing, dispatches)
    progress_path = Path(args.progress) / PROGRESS_FILE
    if progress_path.exists():
        progress = _load_progress(progress_path, digest, listing, expected)
    else:
        progress = _new_progress(digest)
        Path(args.progress).mkdir(parents=True, exist_ok=True)

    read, resumed = _read_cells(folders, listing, expected, progress, progress_path)
    classified = classify(_entries(progress, listing), expected.cells)
    _say(
        f"v4_verdict: cells: {len(folders)} folders, {len(classified.accepted)} accepted, "
        f"{len(classified.refused)} refused, {len(classified.missing)} missing "
        f"({read} read, {resumed} resumed)"
    )

    steps = plan_steps(classified.accepted)
    window = (expected.window["start_ms"], expected.window["end_ms"])
    computed, resumed = _measure(args.summaries, steps, window, progress, progress_path)
    checks = [
        check_from_record(progress["checks"][step.key])
        for step in steps
        if step.section == "checks"
    ]
    pairs: dict[str, dict[str, object]] = {}
    for step in steps:
        if step.section == "pairs":
            pairs.setdefault(step.first.cell_id, {})[step.kind] = progress["pairs"][step.key]
    _say(
        f"v4_verdict: measures: {len(checks)} checks, {sum(map(len, pairs.values()))} pairs "
        f"({computed} computed, {resumed} resumed)"
    )

    verdict = decide(
        classified.accepted,
        checks,
        expected=expected.cells,
        missing=classified.missing,
        reruns=classified.reruns,
        dispatches=dispatches,
    )
    document = verdict_document(
        expected,
        verdict,
        classified.accepted,
        classified.refused,
        classified.missing,
        pairs,
        dispatches,
    )
    payload = _canonical(document)  # exact JSON only: strings, integers, booleans, null
    page = render_verdict_page(document).encode("utf-8")
    _write_outputs(out, payload, page)
    _say(f"v4_verdict: wrote {JSON_FILE} and {MD_FILE}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Judge the cells (module docstring); the exit status."""
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except _Stop as stop:
        return _fail(stop.step, stop.cause)
    except Exception as exc:
        return _fail("stopped by an unexpected error", exc)


if __name__ == "__main__":
    raise SystemExit(main())
