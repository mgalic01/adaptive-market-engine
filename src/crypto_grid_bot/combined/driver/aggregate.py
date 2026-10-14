"""Every V3.1 cell's artifacts, read once: the acceptance verdict, the pages and a summary.

``aggregate`` reads what the run jobs wrote (``run_cell``, ``run_baselines``), refuses
mixed or duplicated inputs before writing anything, judges the pass/fail window W1 with
``experiment.evaluate`` and writes the summary. It never writes or rewrites an evidence
bundle (Ruling P13): each V3.1 run job wrote its cell's bundle, and aggregation records
its receipt's SHA-256.

The only accepted ``cells_dir`` layout: each artifact in its own folder, named with the
workflow's run attempt, as the workflow downloads them (each job uploads the directory
that holds its ``<cell_id>/`` or ``v3_picks/``, so the download nests)::

    cells_dir/cell-<cell_id>-attempt-<n>/<cell_id>/   a cell, as its run job wrote it
    cells_dir/v3-picks-attempt-<n>/v3_picks/          the V3 picks job

``<n>`` is a positive integer without leading zeros, and an artifact folder holds exactly
that one directory. Anything else is refused, naming the entry: a loose cell or picks
directory (downloading every artifact into one directory would let one attempt's files
overwrite another's), a file, a link or junction, another name or nesting, a folder of an
unregistered cell or holding more than its one directory, and two folders for one cell or
two picks folders (duplicates, such as attempts 1 and 2). A claim's ``attempt_id`` is
free text; when it ends in ``attempt-<m>`` (after its start or a character that is no
letter or digit), ``<m>`` must be the folder's ``<n>``, digit for digit.

Every artifact folder carries its attempt number, and every claim its run id (the
``<run>`` of its ``<run>-<cell_id>-attempt-<m>`` or ``<run>-v3_picks-attempt-<m>``
attempt id). ``aggregate`` takes the workflow's own ``<run_id>-attempt-<n>`` and records
both for every folder in ``verdict.json``. A registered run is executed once: if any W1
cell or the picks job comes from an artifact attempt other than 1, or under a claim whose
run id is not aggregation's own (or cannot be read), a job was re-run, and the verdict is
``incomplete`` with the reason "re-run detected", naming each, whatever acceptance
returned: a lone ``cell-<id>-attempt-2`` folder (its attempt 1 left no artifact) is a
re-run as surely as two folders are. ``summary.md`` discloses it. A W0 cell's re-run is
disclosed too, and changes nothing, as W0 is reported only. Re-running aggregation alone
(its own attempt number) is no re-run of any cell.

A registration is dispatched once (Ruling R4-2), and a second dispatch has its own run id
and attempt 1, so the folders cannot show it. The caller hands ``aggregate`` what its
dispatch check found (``other_dispatches``: each other dispatch of the registration that
counts, or why none could be ruled out; the driver's registered aggregate reads the
workflow's runs for it). Any of them makes the verdict ``incomplete`` too, whatever
acceptance returned; ``verdict.json`` records them and ``summary.md`` discloses them. An
earlier launch that stopped at the plan job with nothing run does not count (owner
decision v31-d21): the caller hands those over apart (``uncounted_dispatches``), and they
are recorded and disclosed the same way but leave the verdict as it is.

A cell's state follows its run job's protocol: ``outcome.json`` (the completion marker)
makes it ``completed``; ``failure.json`` a recorded ``failed`` attempt, its type and
message kept (it wins over a marker beside it: that attempt raised); a claim alone, or an
empty directory, ``killed``; no directory ``missing`` (no artifact: not run, or failed
before its claim). A completed cell whose artifacts
do not hold together is ``invalid``: an unreadable outcome or claim, a claim of another
attempt, a ``report.json`` that is not the outcome's report evidence, or, for a V3.1
cell, an evidence bundle that is missing, does not verify (``read_bundle``) or does not
bind this outcome and report. No state is ever a refusal, retried or overwritten. Only a
``completed`` cell's outcome goes to acceptance: an ``invalid`` one is withheld like a
missing one, so acceptance itself finds the cell incomplete and no verdict rests on an
outcome found inconsistent. Every state but ``completed`` leaves a W1 cell incomplete.

Refused, naming the cells, before anything is written: a claim (``attempt.json``) of
another cell, of another attempt than its folder's, or under other pins than the
registration's (code, config, data, and the pack its kind runs from); an outcome of
another cell (arm, window, capital, cost multiple, scenario), under another code, config
or data pin, or whose report is labelled with another capital.

On Windows ``cells_dir`` is read through its extended-length path: the nesting puts the
longest arms' bundle files past the 260-character limit of a system without long paths.

Only W1 outcomes go to ``evaluate``: a W0 cell is reported only, never judged or
compared, and ``evaluate`` would count it as an unregistered outcome. The summary::

    out_dir/summary/pages/<cell_id>/report.html  each V3.1 W1 cell's page; the 8 full
                                                 combined cells' with acceptance's
                                                 judgment of their cell (cell_comparison)
    out_dir/summary/pages/<cell_id>/report.json  a page's exact JSON when too large to
                                                 embed (render_bundle_report): the file
                                                 the page links and states the SHA-256 of
    out_dir/summary/w0/<cell_id>/report.html     each W0 cell's page, reported only
    out_dir/summary/w0/<cell_id>/report.json
    out_dir/summary/verdict.json                 canonical JSON: the run's mode, the
                                                 verdict, every cell's state and the
                                                 SHA-256 of its files and page, the pins
    out_dir/summary/summary.md                   the owner's tables, the mode in its
                                                 first line, written last

An ``invalid`` cell's page says so in its title.

Every directory is created once and every file is an exclusive create, all under a fresh
default decimal context, so the same cells give byte-identical files. ``summary.md`` is
the summary's completion marker. Reading the cells is the only input; no network.
"""

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from crypto_grid_bot.combined.artifacts import (
    REPORT_JSON,
    _canonical,
    _safe_path,
    _write,
    read_bundle,
)
from crypto_grid_bot.combined.dashboard import render_bundle_report
from crypto_grid_bot.combined.driver.registration import (
    ACCEPTANCE_WINDOW,
    REPORTED_WINDOW,
    Cell,
    DriverRegistration,
    _strict_json,
    check_registration,
)
from crypto_grid_bot.combined.driver.run_baselines import (
    ATTEMPT_FILE,
    MINUTE_MANIFEST_PATH,
    OUTCOME_FILE,
    PICKS_FILE,
    V3_PICKS,
    _read_picks,
)
from crypto_grid_bot.combined.driver.serialize import REPORT_SCHEMA, decode_outcome, decode_report
from crypto_grid_bot.combined.experiment import (
    AcceptanceResult,
    BaselineComparison,
    CellComparison,
    RunOutcome,
    cell_comparison,
    evaluate,
)
from crypto_grid_bot.combined.report import Report

SUMMARY_DIR = "summary"
PAGES_DIR = "pages"
W0_DIR = REPORTED_WINDOW  # summary/w0/
VERDICT_FILE = "verdict.json"
SUMMARY_FILE = "summary.md"
VERDICT_SCHEMA = "v3.1-verdict-1"
REPORT_FILE = "report.json"
PAGE_FILE = "report.html"  # beside its REPORT_JSON, the file the page's own link names
FAILURE_FILE = "failure.json"
STATES = ("completed", "failed", "killed", "missing", "invalid")
MODES = ("registered", "rehearsal", "smoke")  # a registered run, or a synthetic world's
# The summary's first line, by mode: a synthetic world's verdict says so before anything.
TITLES = {
    "registered": "# V3.1 run summary: registered run",
    "rehearsal": "# V3.1 run summary: REHEARSAL (a synthetic world; no verdict on market data)",
    "smoke": "# V3.1 run summary: SMOKE (a synthetic world; no verdict on market data)",
}

_CELL_ARTIFACT = re.compile(r"cell-([a-z0-9._-]+)-attempt-([1-9][0-9]*)")
_PICKS_ARTIFACT = re.compile(r"v3-picks-attempt-([1-9][0-9]*)")
_CLAIMED_ATTEMPT = re.compile(r"(?:^|[^A-Za-z0-9])attempt-([0-9]+)\Z")
_RUN = "[A-Za-z0-9][A-Za-z0-9._-]*"  # a run id: the workflow's run id, or a test's name
_RUN_ATTEMPT = re.compile(rf"({_RUN})-attempt-([1-9][0-9]*)")
_CLAIM_KEYS = frozenset(
    {"attempt_id", "repo_head", "code_pin", "config_pin", "pack_sha256", "data_pin"}
)
_PINS = ("code_pin", "config_pin", "data_pin", "pack_sha256")
_HUNDREDTH = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class _Read:
    """One cell (or the picks job) as read: its state, why it is not ``completed``, the
    SHA-256 of its files, and its outcome and report whenever they decode."""

    state: str
    attempt_id: str | None = None
    failure: tuple[str, str] | None = None  # (type, message) of a recorded failure
    reasons: tuple[str, ...] = ()
    outcome: RunOutcome | None = None
    report: Report | None = None
    outcome_sha256: str | None = None
    report_sha256: str | None = None
    receipt_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class _Page:
    path: str
    sha256: str
    report_json: tuple[str, str] | None  # (path, sha256) of its exact JSON beside it


def aggregate(
    reg: DriverRegistration,
    cells_dir: Path,
    out_dir: Path,
    *,
    attempt_id: str,
    mode: str,
    other_dispatches: Sequence[str],
    uncounted_dispatches: Sequence[str] = (),
) -> Path:
    """Aggregate the cell artifacts in ``cells_dir`` into ``out_dir/summary`` and return
    that directory (layout, states, re-runs and refusals in the module docstring).

    ``attempt_id`` is the workflow's ``<run_id>-attempt-<n>``: every W1 cell and the picks
    job must come from artifact attempt 1 under a claim of run ``<run_id>``, or the verdict
    is ``incomplete`` (re-run detected). ``other_dispatches`` is what the caller's dispatch
    check found (Ruling R4-2), each a line of text: any one leaves the verdict
    ``incomplete`` too (empty when no other dispatch exists, and in a synthetic run, which
    dispatches no registration). ``uncounted_dispatches`` names, a line of text each, the
    earlier launches that stopped at the plan job with nothing run (owner decision
    v31-d21): recorded and disclosed, they change nothing. Refuses, before anything is
    written, a malformed ``attempt_id``, ``other_dispatches`` or ``uncounted_dispatches``,
    a registration ``check_registration`` refuses, an existing summary, and every input
    the module docstring lists as refused, in one ``ValueError`` naming each cell. A
    missing or incomplete cell is never refused: it leaves the verdict ``incomplete``,
    unless acceptance fails it already.

    ``mode`` is the run's (``MODES``): ``registered``, or ``rehearsal`` or ``smoke`` for a
    synthetic world. ``verdict.json`` records it and ``summary.md`` names it in its first
    line, so a synthetic run's verdict never reads as the registered one.
    """
    if mode not in MODES:
        raise ValueError(f"aggregate mode {mode!r}: one of {', '.join(MODES)} required")
    for what, lines in (
        ("other dispatches", other_dispatches),
        ("uncounted dispatches", uncounted_dispatches),
    ):
        if isinstance(lines, str) or not all(type(item) is str and item.strip() for item in lines):
            raise ValueError(f"aggregate {what}: a sequence of nonblank lines required")
    run_id, run_attempt = _run_attempt(attempt_id)
    check_registration(reg)
    summary = Path(out_dir) / SUMMARY_DIR
    if summary.exists():
        raise FileExistsError(f"{summary} exists; a summary is written once")
    with localcontext(Context()):
        directories, picks_dir = _locate(_extended(Path(cells_dir)), reg)
        refusals: list[str] = []
        reads = {
            cell.cell_id: _read_cell(cell, directories.get(cell.cell_id), reg, refusals)
            for cell in reg.cells
        }
        picks = _read_picks_job(picks_dir, reg, refusals)
        if refusals:
            raise ValueError("aggregate refused:\n- " + "\n- ".join(refusals))
        origins = {
            cell.cell_id: _origin(cell.cell_id, directories.get(cell.cell_id), reads[cell.cell_id])
            for cell in reg.cells
        }
        origins[V3_PICKS] = _origin(V3_PICKS, picks_dir, picks)
        judged_owners = [c.cell_id for c in reg.cells if not c.reported_only] + [V3_PICKS]
        reported_owners = [c.cell_id for c in reg.cells if c.reported_only]
        run = _Run(
            attempt_id,
            run_id,
            run_attempt,
            _reruns(judged_owners, origins, run_id),
            _reruns(reported_owners, origins, run_id),
            tuple(other_dispatches),
            tuple(uncounted_dispatches),
        )
        judged = tuple(  # completed W1 cells only: an invalid one is withheld as missing
            read.outcome
            for cell in reg.cells
            if not cell.reported_only
            and (read := reads[cell.cell_id]).state == "completed"
            and read.outcome is not None
        )
        result = evaluate(reg.registration, judged)
        cell_reasons = _cell_reasons(reg.cells, reads, picks)
        status = (
            "incomplete"  # executed once, or no verdict: a re-run or a redispatch voids a fail
            if run.reruns or run.dispatches
            else "fail"
            if result.status == "fail"
            else "incomplete"
            if result.status == "incomplete" or cell_reasons
            else "pass"
        )
        comparisons = {
            cell.cell_id: cell_comparison(
                reg.registration,
                result,
                window=cell.window,
                capital=cell.capital_id,
                cost_multiple=cell.cost_multiple,
                scenario=cell.scenario,
            )
            for cell in reg.cells
            if cell.arm == "combined" and not cell.reported_only
        }
        summary.mkdir(exist_ok=False)
        pages = _write_pages(summary, reg.cells, reads, comparisons)
        verdict = {
            "mode": mode,
            **_verdict(reg, status, result, cell_reasons, reads, pages, picks, run, origins),
        }
        _write(summary / VERDICT_FILE, _canonical(verdict) + b"\n")
        text = _summary_text(
            reg, status, result, cell_reasons, reads, pages, picks, comparisons, run, mode
        )
        _write(summary / SUMMARY_FILE, text.encode("utf-8"))  # last: the completion marker
    return summary


@dataclass(frozen=True, slots=True)
class _Origin:
    """Where one artifact came from: its folder's attempt number (None: no folder), and
    its claim's run id, the ``<run>`` of ``<run>-<owner>-attempt-<m>`` (None: no claim,
    or, with ``claimed``, an attempt id of another shape)."""

    attempt: int | None
    run_id: str | None
    claimed: bool


@dataclass(frozen=True, slots=True)
class _Run:
    """Aggregation's own run, every re-run it found: W1 cells and the picks job
    (``reruns``, which make the verdict incomplete) and W0 cells (disclosed only), every
    other dispatch of the registration its caller found that counts (``dispatches``, which
    make the verdict incomplete too), and every earlier launch that stopped at the plan
    job with nothing run (``uncounted``, disclosed only)."""

    attempt_id: str
    run_id: str
    attempt: int
    reruns: tuple[str, ...]
    reported_reruns: tuple[str, ...]
    dispatches: tuple[str, ...]
    uncounted: tuple[str, ...]


def _run_attempt(attempt_id: object) -> tuple[str, int]:
    """The run id and attempt number of the workflow's ``<run_id>-attempt-<n>``."""
    match = _RUN_ATTEMPT.fullmatch(attempt_id) if type(attempt_id) is str else None
    if match is None:
        raise ValueError(
            f"aggregate attempt id {attempt_id!r}: <run_id>-attempt-<n> required, <n> a "
            "positive integer without leading zeros (the workflow passes "
            "<run_id>-attempt-<run_attempt>)"
        )
    return match[1], int(match[2])


def _origin(owner: str, located: tuple[Path, str] | None, read: _Read) -> _Origin:
    """The ``_Origin`` of ``owner``'s artifact (``located``: its directory and folder
    attempt; ``read``: its state, with its claim's attempt id)."""
    if read.attempt_id is None:
        run_id = None
    else:
        claimed = re.fullmatch(rf"({_RUN})-{re.escape(owner)}-attempt-[1-9][0-9]*", read.attempt_id)
        run_id = None if claimed is None else claimed[1]
    attempt = None if located is None else int(located[1])
    return _Origin(attempt, run_id, read.attempt_id is not None)


def _reruns(owners: Sequence[str], origins: Mapping[str, _Origin], run_id: str) -> tuple[str, ...]:
    """Each of ``owners`` whose artifact a re-run left: from an artifact attempt other than
    1, or claimed by another run than ``run_id`` (or by an attempt id naming no run). An
    owner without a folder left nothing; one without a claim names no run, and is
    incomplete already."""
    found = []
    for owner in owners:
        origin = origins[owner]
        if origin.attempt is None:
            continue
        problems = []
        if origin.attempt != 1:
            problems.append(f"artifact attempt {origin.attempt}, not 1")
        if origin.claimed and origin.run_id != run_id:
            claimed = "an unreadable run" if origin.run_id is None else f"run {origin.run_id}"
            problems.append(f"claimed by {claimed}, not this run {run_id}")
        if problems:
            found.append(f"{owner}: " + "; ".join(problems))
    return tuple(found)


# --- reading the cells -----------------------------------------------------------------


def _locate(
    cells_dir: Path, reg: DriverRegistration
) -> tuple[dict[str, tuple[Path, str]], tuple[Path, str] | None]:
    """Each present cell's directory with its artifact folder's attempt number, by cell
    id, and the picks job's; refuses any other entry, naming it, and duplicates."""
    if _linked(cells_dir) or not cells_dir.is_dir():
        raise ValueError(f"cells directory {cells_dir}: a directory, not a link, required")
    registered = {cell.cell_id for cell in reg.cells}
    found: dict[str, list[tuple[Path, str]]] = {}
    errors: list[str] = []
    for entry in sorted(cells_dir.iterdir(), key=lambda path: path.name):
        name = entry.name
        cell, picks = _CELL_ARTIFACT.fullmatch(name), _PICKS_ARTIFACT.fullmatch(name)
        if _linked(entry) or not entry.is_dir():
            errors.append(f"{name}: a file, link or junction, not an artifact folder")
            continue
        if picks is not None:
            inner, attempt = V3_PICKS, picks[1]
        elif cell is not None and cell[1] in registered:
            inner, attempt = cell[1], cell[2]
        elif cell is not None:
            errors.append(f"{name}: an artifact folder of {cell[1]}, not a registered cell")
            continue
        else:
            errors.append(
                f"{name}: not an artifact folder (cell-<cell_id>-attempt-<n>/ or "
                "v3-picks-attempt-<n>/)"
            )
            continue
        children = list(entry.iterdir())
        if (
            [child.name for child in children] != [inner]
            or _linked(children[0])
            or not children[0].is_dir()
        ):
            errors.append(f"{name}: an artifact folder must hold exactly its {inner}/ directory")
            continue
        found.setdefault(inner, []).append((children[0], attempt))
    for name, entries in sorted(found.items()):
        if len(entries) > 1:
            shown = ", ".join(path.parent.name for path, _ in entries)
            errors.append(f"{name}: duplicate artifact sets ({shown})")
    if errors:
        raise ValueError("aggregate refused the cells directory:\n- " + "\n- ".join(errors))
    picks_dir = found.pop(V3_PICKS)[0] if V3_PICKS in found else None
    return {name: entries[0] for name, entries in found.items()}, picks_dir


def _read_cell(
    cell: Cell, located: tuple[Path, str] | None, reg: DriverRegistration, refusals: list[str]
) -> _Read:
    """The cell ``located`` (its directory and its folder's attempt number; None: never
    run); its refusals go to ``refusals``."""
    if located is None:
        return _Read("missing")
    directory, folder_attempt = located
    claim, claim_error = _claim(directory, cell.cell_id, "cell_id")
    if claim is not None:
        expected = _pins(cell, reg)
        refusals.extend(_claim_refusals(cell.cell_id, "cell_id", claim, expected, folder_attempt))
    attempt_id = None if claim is None else str(claim["attempt_id"])
    failure_raw = _bytes(directory / FAILURE_FILE, cell.cell_id)
    if failure_raw is not None:
        failure = _failure(failure_raw)
        return _Read("failed", attempt_id, failure, () if failure else ("failure.json unreadable",))
    outcome_raw = _bytes(directory / OUTCOME_FILE, cell.cell_id)
    if outcome_raw is None:
        return _Read("killed", attempt_id, reasons=() if claim is not None else (claim_error,))
    reasons = [] if claim is not None else [claim_error]
    report_raw = _bytes(directory / REPORT_FILE, cell.cell_id)
    outcome_sha256 = _sha256(outcome_raw)
    report_sha256 = None if report_raw is None else _sha256(report_raw)
    outcome: RunOutcome | None = None
    report: Report | None = None
    outcome_text = ""
    try:
        outcome_text = outcome_raw.decode("ascii")
        outcome = decode_outcome(outcome_text)
    except ValueError as exc:  # UnicodeDecodeError included
        reasons.append(f"outcome.json unreadable: {exc}")
    if outcome is not None:
        refusals.extend(_identity_refusals(cell, outcome, reg))
        if claim is not None and outcome.attempt_id != attempt_id:
            reasons.append("the outcome is of another attempt than the claim")
        report, problem = _report(outcome, outcome_text, report_raw)
        reasons.extend([problem] if problem else [])
    receipt_sha256 = None
    if cell.kind == "v31":
        receipt_sha256, problem = _bundle(directory, cell.cell_id, outcome_sha256, report_sha256)
        reasons.extend([problem] if problem else [])
    return _Read(
        "invalid" if reasons else "completed",
        attempt_id,
        None,
        tuple(reasons),
        outcome,
        report,
        outcome_sha256,
        report_sha256,
        receipt_sha256,
    )


def _read_picks_job(
    located: tuple[Path, str] | None, reg: DriverRegistration, refusals: list[str]
) -> _Read:
    """The V3 picks job, exempt from cell decoding: its state and its completion marker's
    SHA-256, the receipt. A finished job must pass ``run_baselines._read_picks``, as every
    V3 cell's job did."""
    if located is None:
        return _Read("missing")
    directory, folder_attempt = located
    claim, claim_error = _claim(directory, V3_PICKS, "job")
    expected = {**_registration_pins(reg), "pack_sha256": reg.run_manifest.v3_pack}
    if claim is not None:
        refusals.extend(_claim_refusals(V3_PICKS, "job", claim, expected, folder_attempt))
    attempt_id = None if claim is None else str(claim["attempt_id"])
    failure_raw = _bytes(directory / FAILURE_FILE, V3_PICKS)
    if failure_raw is not None:
        failure = _failure(failure_raw)
        return _Read("failed", attempt_id, failure, () if failure else ("failure.json unreadable",))
    marker = _bytes(directory / OUTCOME_FILE, V3_PICKS)
    if marker is None:
        return _Read("killed", attempt_id, reasons=() if claim is not None else (claim_error,))
    reasons = [] if claim is not None else [claim_error]
    try:
        _read_picks(directory / PICKS_FILE, reg)
    except (OSError, ValueError) as exc:
        reasons.append(f"the picks do not verify: {exc}")
    state = "invalid" if reasons else "completed"
    return _Read(state, attempt_id, None, tuple(reasons), receipt_sha256=_sha256(marker))


def _claim(directory: Path, owner: str, key: str) -> tuple[dict[str, object] | None, str]:
    """The claim ``attempt.json`` as an object of exactly its string fields, ``key``
    naming its owner; otherwise None and why."""
    raw = _bytes(directory / ATTEMPT_FILE, owner)
    if raw is None:
        return None, "attempt.json, the claim, is missing"
    try:
        document = _strict_json(raw, ATTEMPT_FILE)
    except ValueError as exc:
        return None, f"attempt.json unreadable: {exc}"
    keys = _CLAIM_KEYS | {key}
    if (
        not isinstance(document, dict)
        or set(document) != keys
        or any(type(value) is not str for value in document.values())
    ):
        return None, f"attempt.json unreadable: the string fields {sorted(keys)} required"
    return document, ""


def _claim_refusals(
    owner: str,
    key: str,
    claim: Mapping[str, object],
    expected: Mapping[str, str | None],
    folder_attempt: str,
) -> list[str]:
    errors = []
    if claim[key] != owner:
        errors.append(f"{owner}: its attempt.json claims {key} {claim[key]!r}")
    named = _CLAIMED_ATTEMPT.search(str(claim["attempt_id"]))
    if named is not None and named[1] != folder_attempt:
        errors.append(
            f"{owner}: attempt.json attempt_id {claim['attempt_id']!r} names attempt "
            f"{named[1]}, but its artifact folder is attempt {folder_attempt}"
        )
    for pin in _PINS:
        if claim[pin] != expected[pin]:
            errors.append(
                f"{owner}: attempt.json {pin} {claim[pin]} differs from the registration's "
                f"{expected[pin]}"
            )
    return errors


def _registration_pins(reg: DriverRegistration) -> dict[str, str | None]:
    return {
        "code_pin": reg.registration.code_pin,
        "config_pin": reg.registration.config_pin,
        "data_pin": reg.run_manifest_pin,
    }


def _pins(cell: Cell, reg: DriverRegistration) -> dict[str, str | None]:
    """The pins a claim of ``cell`` holds: the registration's, and the pack its kind runs
    from (a V3 cell's the V3 input pack, a minute cell's the legacy dataset manifest)."""
    manifest = reg.run_manifest
    if cell.kind == "v3":
        pack: str | None = manifest.v3_pack
    elif cell.kind == "minute":
        pack = {pin.path: pin.sha256 for pin in manifest.data_manifests}.get(MINUTE_MANIFEST_PATH)
    else:
        pack = dict(manifest.window_packs).get(cell.window)
    return {**_registration_pins(reg), "pack_sha256": pack}


def _identity_refusals(cell: Cell, outcome: RunOutcome, reg: DriverRegistration) -> list[str]:
    identity = outcome.identity
    errors = []
    held = (
        identity.arm,
        identity.window,
        identity.capital,
        identity.cost_multiple,
        identity.scenario,
    )
    registered = (cell.arm, cell.window, cell.capital_id, cell.cost_multiple, cell.scenario)
    if held != registered:
        errors.append(
            f"{cell.cell_id}: its outcome is of another cell (arm, window, capital, cost "
            f"multiple, scenario): {held}, not {registered}"
        )
    for pin, expected in _registration_pins(reg).items():
        if getattr(identity, pin) != expected:
            errors.append(
                f"{cell.cell_id}: its outcome's {pin} {getattr(identity, pin)} differs from "
                f"the registration's {expected}"
            )
    evidence = outcome.report_evidence
    label = None if evidence is None else evidence.report.capital_label
    if label is not None and _label_capital(label) != cell.capital_id:
        errors.append(f"{cell.cell_id}: its report is labelled with another capital: {label}")
    return errors


def _label_capital(label: str) -> str:
    """The capital id a report's capital label names, as ``dashboard`` reads it."""
    return "research" if label == "research_10000_usdt" else label.partition(":")[0]


def _report(
    outcome: RunOutcome, outcome_text: str, report_raw: bytes | None
) -> tuple[Report | None, str]:
    """The cell's report, and why ``report.json`` is not its outcome's report evidence.

    ``report.json`` must be exactly ``encode_report`` of the outcome's report evidence.
    ``outcome_text`` has already passed ``decode_outcome``, so it is that evidence's
    canonical encoding: the report is compared as JSON text, never decoded twice. An
    outcome without report evidence has its report decoded from ``report.json``.
    """
    evidence = outcome.report_evidence
    if evidence is None:
        if report_raw is None:
            return None, "report.json is missing"
        try:
            return decode_report(report_raw.decode("ascii")), ""
        except ValueError as exc:  # UnicodeDecodeError included
            return None, f"report.json unreadable: {exc}"
    if report_raw is None:
        return evidence.report, "report.json is missing"
    document = json.loads(outcome_text)["outcome"]["report_evidence"]["report"]
    expected = json.dumps(
        {"schema": REPORT_SCHEMA, "report": document},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if report_raw != expected.encode("ascii"):
        return evidence.report, "report.json is not the outcome's report evidence"
    return evidence.report, ""


def _bundle(
    directory: Path, cell_id: str, outcome_sha256: str, report_sha256: str | None
) -> tuple[str | None, str]:
    """A V3.1 cell's bundle receipt SHA-256, once the bundle verifies and its metadata
    binds this cell's outcome and report; otherwise None and why."""
    path = directory / cell_id.replace(".", "-")
    try:
        bundle = read_bundle(path)
    except (OSError, ValueError) as exc:
        return None, f"evidence bundle {path.name}/ missing or unreadable: {exc}"
    metadata = json.loads(bundle.metadata_json)
    bound = (metadata.get("cell_id"), metadata.get("outcome_sha256"), metadata.get("report_sha256"))
    if bound != (cell_id, outcome_sha256, report_sha256):
        return None, f"evidence bundle {path.name}/ does not bind this cell's outcome and report"
    return bundle.receipt.receipt_sha256, ""


def _failure(raw: bytes) -> tuple[str, str] | None:
    """A recorded failure's type and message; None for an unreadable ``failure.json``."""
    try:
        document = _strict_json(raw, FAILURE_FILE)
    except ValueError:
        return None
    if (
        not isinstance(document, dict)
        or set(document) != {"type", "message"}
        or any(type(value) is not str for value in document.values())
    ):
        return None
    return str(document["type"]), str(document["message"])


def _bytes(path: Path, owner: str) -> bytes | None:
    """The file's bytes, or None when there is none; refuses a link or junction."""
    try:
        _safe_path(path)
    except ValueError as exc:
        raise ValueError(f"{owner}: {path.name}: {exc}") from exc
    return path.read_bytes() if path.is_file() else None


def _extended(path: Path) -> Path:
    """``path`` made absolute and, on Windows, in its extended-length form (``\\\\?\\``):
    a nested V3.1 cell's bundle files (``cell-<id>-attempt-<n>/<id>/<invocation>/...``)
    pass the 260-character path limit of a Windows system without long paths enabled."""
    absolute = os.path.abspath(path)
    if os.name != "nt" or absolute.startswith("\\\\"):  # already extended, or UNC
        return Path(absolute)
    return Path("\\\\?\\" + absolute)


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _cell_reasons(cells: Sequence[Cell], reads: Mapping[str, _Read], picks: _Read) -> list[str]:
    """Why W1 stays incomplete beyond what acceptance sees: each W1 cell that did not
    complete, and a picks job that did not (the V3 selector cells' picks)."""
    reasons: list[str] = []
    for cell in cells:
        if not cell.reported_only:
            reasons.extend(f"{cell.cell_id}: {text}" for text in _explained(reads[cell.cell_id]))
    reasons.extend(f"{V3_PICKS}: {text}" for text in _explained(picks))
    return reasons


def _explained(read: _Read) -> list[str]:
    if read.state == "missing":
        return ["no artifact: not run, or failed before its claim"]
    if read.state == "failed":
        detail = "failure.json unreadable" if read.failure is None else ": ".join(read.failure)
        return [f"failed attempt ({detail})"]
    if read.state == "killed":
        return ["killed, claimed without an outcome"]
    return list(read.reasons)


# --- writing the summary ---------------------------------------------------------------


def _write_pages(
    summary: Path,
    cells: Sequence[Cell],
    reads: Mapping[str, _Read],
    comparisons: Mapping[str, CellComparison],
) -> dict[str, _Page]:
    """Render each V3.1 cell's report once, into its own folder: a W1 cell's under
    ``pages/``, the full combined cells' with their comparison, and a W0 cell's under
    ``w0/``, labelled reported only. A large report's exact JSON is ``report.json`` beside
    its page, the file the page's own link names."""
    for folder in (PAGES_DIR, W0_DIR):
        (summary / folder).mkdir(exist_ok=False)
    pages = {}
    for cell in cells:
        read = reads[cell.cell_id]
        if cell.kind != "v31" or read.report is None:
            continue
        folder = W0_DIR if cell.reported_only else PAGES_DIR
        title = (
            f"Reported only ({REPORTED_WINDOW.upper()}): no acceptance · {cell.cell_id}"
            if cell.reported_only
            else f"V3.1 cell {cell.cell_id}"
        )
        if read.state == "invalid":
            title += " · INVALID cell artifacts, not judged"
        page, report_json = render_bundle_report(
            read.report, title, synthetic=False, comparison=comparisons.get(cell.cell_id)
        )
        directory = summary / folder / cell.cell_id
        directory.mkdir(exist_ok=False)
        page_raw = page.encode("utf-8")
        _write(directory / PAGE_FILE, page_raw)
        exact = None
        if report_json is not None:
            json_raw = report_json.encode("utf-8")
            _write(directory / REPORT_JSON, json_raw)
            exact = (f"{folder}/{cell.cell_id}/{REPORT_JSON}", _sha256(json_raw))
        path = f"{folder}/{cell.cell_id}/{PAGE_FILE}"
        pages[cell.cell_id] = _Page(path, _sha256(page_raw), exact)
    return pages


def _verdict(
    reg: DriverRegistration,
    status: str,
    result: AcceptanceResult,
    cell_reasons: list[str],
    reads: Mapping[str, _Read],
    pages: Mapping[str, _Page],
    picks: _Read,
    run: _Run,
    origins: Mapping[str, _Origin],
) -> dict[str, object]:
    return {
        "schema": VERDICT_SCHEMA,
        "status": status,
        "acceptance_status": result.status,
        "failures": list(result.failures),
        "incomplete_reasons": list(result.incomplete_reasons),
        "cell_incomplete_reasons": cell_reasons,
        "run": {
            "attempt_id": run.attempt_id,
            "run_id": run.run_id,
            "aggregate_attempt": run.attempt,
            "rerun_detected": bool(run.reruns),
            "reruns": list(run.reruns),
            "reported_only_reruns": list(run.reported_reruns),
            "other_dispatches": list(run.dispatches),
            "uncounted_dispatches": list(run.uncounted),
        },
        "skipped_hours": {window: list(hours) for window, hours in result.skipped_hours},
        "comparisons": [_comparison_json(row) for row in result.comparisons],
        "cells": {
            cell_id: _cell_json(read, pages.get(cell_id), origins[cell_id])
            for cell_id, read in reads.items()
        },
        "v3_picks": {
            "state": picks.state,
            "artifact_attempt": origins[V3_PICKS].attempt,
            "run_id": origins[V3_PICKS].run_id,
            "receipt_sha256": picks.receipt_sha256,
            "reasons": [] if picks.state == "completed" else _explained(picks),
        },
        "registration": {
            "code_pin": reg.registration.code_pin,
            "config_pin": reg.registration.config_pin,
            "data_pin": reg.run_manifest_pin,
            "prepare_pin": reg.prepare_pin,
            "acceptance_windows": [window.id for window in reg.registration.windows],
            "reported_windows": [window.id for window in reg.reported_windows],
        },
    }


def _cell_json(read: _Read, page: _Page | None, origin: _Origin) -> dict[str, object]:
    failure = read.failure
    return {
        "state": read.state,
        "artifact_attempt": origin.attempt,
        "run_id": origin.run_id,
        "attempt_id": read.attempt_id,
        "failure": None if failure is None else {"type": failure[0], "message": failure[1]},
        "reasons": list(read.reasons),
        "outcome_sha256": read.outcome_sha256,
        "report_sha256": read.report_sha256,
        "bundle_receipt_sha256": read.receipt_sha256,
        "page": None
        if page is None
        else {
            "path": page.path,
            "sha256": page.sha256,
            "report_json": None
            if page.report_json is None
            else {"path": page.report_json[0], "sha256": page.report_json[1]},
        },
    }


def _comparison_json(row: BaselineComparison) -> dict[str, object]:
    return {
        "window": row.window,
        "capital": row.capital,
        "cost_multiple": row.cost_multiple,
        "scenario": row.scenario,
        "baseline": row.baseline,
        "full_return": _exact(row.full_return),
        "full_max_drawdown": _exact(row.full_max_drawdown),
        "baseline_return": _exact(row.baseline_return),
        "baseline_max_drawdown": _exact(row.baseline_max_drawdown),
        "beats_return": row.beats_return,
        "beats_return_drawdown": row.beats_return_drawdown,
        "baseline_native_stop": row.baseline_native_stop,
    }


def _exact(value: Fraction | None) -> str | None:
    return None if value is None else str(value)


def _summary_text(
    reg: DriverRegistration,
    status: str,
    result: AcceptanceResult,
    cell_reasons: list[str],
    reads: Mapping[str, _Read],
    pages: Mapping[str, _Page],
    picks: _Read,
    comparisons: Mapping[str, CellComparison],
    run: _Run,
    mode: str,
) -> str:
    """The owner's summary: the verdict, any re-run, one row per full combined W1 cell,
    each cell against every baseline, the reasons, the cell states and the W0 section."""
    registration = reg.registration
    seen = (
        f"{len(cell_reasons)} cell problem(s) acceptance cannot see also leave the run "
        "incomplete (below)."
        if cell_reasons
        else "No cell problem beyond what acceptance sees."
    )
    verdict = f"Verdict: **{status.upper()}**"
    if run.reruns:
        verdict += f" (re-run detected: {len(run.reruns)} W1 cell(s) or job(s))"
    if run.dispatches:
        verdict += " (another dispatch of this registration, or none ruled out)"
    lines = [
        TITLES[mode],
        "",
        verdict,
        "",
        f"Acceptance judges the pass/fail window `{ACCEPTANCE_WINDOW}` alone and returned "
        f"**{result.status}**; `{REPORTED_WINDOW}` is reported only. {seen}",
        "",
        f"Pins: code `{registration.code_pin}`, config `{registration.config_pin}`, data "
        f"(run-manifest) `{reg.run_manifest_pin}`.",
        "",
        f"This aggregation: run `{run.run_id}`, attempt {run.attempt}.",
        "",
        *_rerun_section(run),
        *_dispatch_section(run, mode),
        f"## Full combined cells in {ACCEPTANCE_WINDOW}",
        "",
        "Each row is one full combined cell, measured on its common hourly series as "
        "acceptance measured it. A cell passes only by strictly beating every registered "
        f"baseline ({len(registration.baseline_arms)}) on compounded return and on "
        "return / max drawdown; the counts show how many it beats. Values are rounded "
        "for display; verdict.json holds them exactly.",
        "",
        "| Cell | This cell | Compounded return | Max drawdown | Return / max drawdown "
        "| Beats on return | Beats on return / max drawdown |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for cell_id, comparison in comparisons.items():
        full_return, drawdown = _full(comparison.rows)
        total = len(comparison.baselines)
        beats = sum(row.beats_return is True for row in comparison.rows)
        beats_ratio = sum(row.beats_return_drawdown is True for row in comparison.rows)
        lines.append(
            f"| `{cell_id}` | {comparison.cell_status} | {_percent(full_return)} | "
            f"{_percent(drawdown, signed=False)} | {_ratio(full_return, drawdown)} | "
            f"{beats} of {total} | "
            f"{beats_ratio} of {total} |"
        )
    lines += ["", "## Against each baseline", ""]
    for cell_id, comparison in comparisons.items():
        lines += _baseline_table(cell_id, comparison)
    lines += _bullets(f"Failures ({len(result.failures)})", result.failures)
    lines += ["## Why incomplete", ""]
    reasons = result.incomplete_reasons
    lines += _bullets(f"From acceptance ({len(reasons)})", reasons, level="###")
    lines += _bullets(f"From the cell artifacts ({len(cell_reasons)})", cell_reasons, level="###")
    lines += _cell_states(reg.cells, reads, picks)
    lines += _w0_section(reg.cells, reads, pages)
    return "\n".join(lines) + "\n"


def _rerun_section(run: _Run) -> list[str]:
    """The re-run disclosure: a registered run is executed once, so any W1 cell or the
    picks job from another attempt or run leaves the run incomplete, whatever acceptance
    returned; a W0 re-run is disclosed, and changes nothing."""
    lines = ["## Re-run detected", ""]
    if run.reruns:
        lines += [
            "A registered run is executed once. These W1 cells or jobs come from another "
            "artifact attempt than 1 or another run than this one, so the run is "
            "**incomplete**, whatever acceptance returned:",
            "",
            *(f"- {_md(item)}" for item in run.reruns),
            "",
        ]
    else:
        lines += [
            f"None: every W1 cell and the picks job that left an artifact is attempt 1 of "
            f"run `{run.run_id}`.",
            "",
        ]
    if run.reported_reruns:
        lines += [
            f"Reported-only ({REPORTED_WINDOW.upper()}) cells from another attempt or run, "
            "disclosed only:",
            "",
            *(f"- {_md(item)}" for item in run.reported_reruns),
            "",
        ]
    return lines


def _dispatch_section(run: _Run, mode: str) -> list[str]:
    """The other dispatches of the registration (Ruling R4-2): a registered run is
    dispatched once, so any other dispatch created before or with this run that counts,
    or a check that could not rule one out, leaves the run incomplete; an earlier launch
    stopped at the plan job with nothing run is disclosed and changes nothing (owner
    decision v31-d21); a synthetic run dispatches no registration and is not checked."""
    lines = ["## Another dispatch of this registration", ""]
    if run.dispatches:
        lines += [
            "A registration is dispatched once. This run's dispatch check found another "
            "dispatch of it, or could not rule one out, so the run is **incomplete**, "
            "whatever acceptance returned:",
            "",
            *(f"- {_md(item)}" for item in run.dispatches),
            "",
        ]
    elif run.uncounted:
        lines += [
            "None that counts: every earlier launch of this registration stopped at the plan "
            "job with nothing run (below).",
            "",
        ]
    elif mode == "registered":
        lines += [
            "None: no other run of this workflow dispatched this registration before or "
            "with this run.",
            "",
        ]
    else:
        lines += [f"Not checked: a {mode} run dispatches no registration.", ""]
    if run.uncounted:
        lines += [
            "Not counted, and changing nothing: a launch that fetched no data and produced "
            "no result is not an execution.",
            "",
            *(f"- {_md(item)}" for item in run.uncounted),
            "",
        ]
    return lines


def _baseline_table(cell_id: str, comparison: CellComparison) -> list[str]:
    full_return, drawdown = _full(comparison.rows)
    rows = {row.baseline: row for row in comparison.rows}
    lines = [
        f"### `{cell_id}`",
        "",
        f"Combined: compounded return {_percent(full_return)}, return / max drawdown "
        f"{_ratio(full_return, drawdown)}.",
        "",
        "| Baseline | Baseline return | Baseline return / max drawdown | Beats on return "
        "| Beats on return / max drawdown |",
        "| --- | --- | --- | --- | --- |",
    ]
    for baseline in comparison.baselines:
        row = rows.get(baseline)
        if row is None:
            values: tuple[str, ...] = ("unavailable",) * 4
        else:
            stop = row.baseline_native_stop
            values = (
                _percent(row.baseline_return) + (f" (held at its {stop} stop)" if stop else ""),
                _ratio(row.baseline_return, row.baseline_max_drawdown),
                _yes_no(row.beats_return),
                _yes_no(row.beats_return_drawdown),
            )
        lines.append(f"| `{baseline}` | " + " | ".join(values) + " |")
    return [*lines, ""]


def _full(rows: Sequence[BaselineComparison]) -> tuple[Fraction | None, Fraction | None]:
    """The full combined cell's compounded return and maximum drawdown, the same on every
    row that has them."""
    for row in rows:
        if row.full_return is not None:
            return row.full_return, row.full_max_drawdown
    return None, None


def _cell_states(cells: Sequence[Cell], reads: Mapping[str, _Read], picks: _Read) -> list[str]:
    lines = [
        "## Cells",
        "",
        "| Window | " + " | ".join(state.capitalize() for state in STATES) + " |",
        "| --- |" + " --- |" * len(STATES),
    ]
    for window in dict.fromkeys(cell.window for cell in cells):
        states = [reads[cell.cell_id].state for cell in cells if cell.window == window]
        counts = " | ".join(str(states.count(state)) for state in STATES)
        lines.append(f"| `{window}` | {counts} |")
    lines.append("")
    unfinished = [cell for cell in cells if reads[cell.cell_id].state != "completed"]
    if unfinished:
        lines += ["Cells that did not complete:", "", "| Cell | State | Detail |"]
        lines.append("| --- | --- | --- |")
        for cell in unfinished:
            read = reads[cell.cell_id]
            lines.append(f"| `{cell.cell_id}` | {read.state} | {_md(_detail(read))} |")
    else:
        lines.append("Every registered cell completed.")
    receipt = f", receipt SHA-256 `{picks.receipt_sha256}`" if picks.receipt_sha256 else ""
    detail = "" if picks.state == "completed" else f" ({_md(_detail(picks))})"
    return [*lines, "", f"V3 picks job: {picks.state}{detail}{receipt}.", ""]


def _detail(read: _Read) -> str:
    if read.state == "failed" and read.failure is not None:
        return ": ".join(read.failure)
    return "; ".join(_explained(read))


def _w0_section(
    cells: Sequence[Cell], reads: Mapping[str, _Read], pages: Mapping[str, _Page]
) -> list[str]:
    lines = [
        f"## {REPORTED_WINDOW.upper()} (reported only, no acceptance)",
        "",
        "These cells are reported only: acceptance does not judge them, and they carry no "
        "comparison and no verdict.",
        "",
        "| Cell | State | Net return | Max drawdown | Page |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell in cells:
        if not cell.reported_only:
            continue
        read, page = reads[cell.cell_id], pages.get(cell.cell_id)
        report = read.report
        net = "unavailable" if report is None else _percent(_fraction(report.net_return))
        drawdown = (
            "unavailable"
            if report is None
            else _percent(_fraction(report.max_drawdown), signed=False)
        )
        link = "none" if page is None else f"[page]({page.path})"
        lines.append(f"| `{cell.cell_id}` | {read.state} | {net} | {drawdown} | {link} |")
    return lines


def _bullets(title: str, items: Iterable[str], *, level: str = "##") -> list[str]:
    shown = [f"- {_md(item)}" for item in items]
    return [f"{level} {title}", "", *(shown or ["None."]), ""]


def _fraction(value: Decimal | None) -> Fraction | None:
    return None if value is None or not value.is_finite() else Fraction(value)


def _percent(value: Fraction | None, *, signed: bool = True) -> str:
    """A ratio as a percentage rounded to hundredths, for display only; a return carries
    its sign, a drawdown none."""
    if value is None:
        return "unavailable"
    shown = _hundredths(value * 100)
    return f"{shown:+}%" if signed and shown else f"{shown}%"


def _ratio(value: Fraction | None, drawdown: Fraction | None) -> str:
    """Return over maximum drawdown rounded to hundredths, for display only."""
    if value is None or drawdown is None:
        return "unavailable"
    if not drawdown:
        return "undefined (zero drawdown)"
    return str(_hundredths(value / drawdown))


def _hundredths(value: Fraction) -> Decimal:
    """``value`` rounded half-even to hundredths (never ``-0.00``), for display only."""
    shown = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(_HUNDREDTH)
    return shown if shown else abs(shown)


def _yes_no(beats: bool | None) -> str:
    return "unavailable" if beats is None else "yes" if beats else "no"


def _md(text: str) -> str:
    """Text safe in a Markdown table cell or bullet: one line, pipes escaped."""
    return " ".join(text.split()).replace("|", "\\|")
