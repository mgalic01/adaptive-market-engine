"""The verdict's inputs: one cell's ``summary.json``, accepted or refused, and the expected file.

Implements rulings V1 to V3 of step 4b. The verdict step judges the run's 48 cells from their
``summary.json`` files and receipts only, never their records, so what it reads must be exactly
what a cell job wrote. ``read_cell(folder, expected)`` returns the cell's ``CellFacts`` or raises
``CellRefused(step, reason)``. A refused cell counts as missing and its outcome is never read, not
even for the fail precedence (V2). ``reason`` names what was wrong in words and never quotes a
value of the file (public logs carry no prices or equities).

**The steps**, in this order; the first one that fails refuses:

1. ``folder``: the folder is named ``v4-summary-<cell id>-attempt-<n>`` and is a folder;
2. ``rerun``: its attempt is 1. Any other is a re-run (V3), refused before its file is read;
3. ``json``: ``summary.json`` exists and is a JSON object whose bytes are the canonical JSON
   (``combined.artifacts._canonical``: sorted keys, no spaces, ASCII, no newline) of their own
   strict parse: UTF-8, unique keys, no floats, no NaN or infinity;
4. ``format``: ``v4-summary-v3-1`` for ``v3_as_built``, ``v4-summary-1`` for every other arm;
5. ``cell``: the summary's ``cell`` is the folder's, and one of ``expected.cells``;
6. ``window``: the expected window of a V4 or hold cell; a v3 cell's is V3's own,
   ``{start_ms: V3_START_MS, end_ms: V3_END_MS - HOUR_MS}``;
7. ``data``: the expected ``data`` pins of a V4 or hold cell; a v3 cell's are the expected
   ``v3_pack_sha256`` and ``picks_sha256``. A null ``data`` is refused: the expected file's
   is never null;
8. ``keys``: the outcome is one the arm has, and the keys are exactly its outcome's set
   (``FULL_KEYS``, ``V3_FULL_KEYS`` or ``FAILURE_KEYS``), the reason is null (for a
   ``limit_unrestorable``, one of ``run.LIMIT_REASONS``), and the nested containers (the eras,
   the years, the disclosures, a failure's details) have the shape the format gives;
9. ``numbers``: every number is what the format says. A Decimal is a string that is finite, is
   spelled as ``str`` of its Decimal (so no sign, space, underscore or foreign digit) and whose
   exponent is at most ``MAX_EXPONENT`` in magnitude: ``1E-40`` is how the engine writes a tiny
   residual, ``1E+999999`` is finite and would overflow the verdict's arithmetic. An integer is
   a non-negative ``int`` (never ``True``). Besides, ``initial_equity`` is the cell's capital;
10. ``marks``: the open marks are ``[int, str, bool]`` rows with strictly increasing hours and at
    least one row, and the first mark is the capital;
11. ``receipt``: a full summary (``complete``, ``liquidated``, ``limit_unrestorable``) has a
    ``receipt.json`` beside it that ``records.read_receipt`` reads and whose bytes hash to the
    summary's ``receipt_sha256``. A failure summary (``accounting_failure``, ``engine_error``)
    has no marks and no receipt check.

**Decisions of this module** (beyond V1's list, each cheap and true of every summary the engine
writes). A v3 cell has only the outcomes ``complete``, ``liquidated`` and ``engine_error``
(``v3_as_built`` writes no others). A failure summary's ``CellFacts`` has no ``stop_ms``: the
format gives its hour as ``hour_ms`` and the verdict never reads it. The facts keep the eras
and years as the summary spells them (strings for Decimals).

**Memory.** ``read_cell`` parses a cell's summary, checks it and keeps only the count of marks;
``read_marks`` re-reads the file for the one cell whose marks a measure needs, and re-checks that
it is still canonical with well-formed marks, so a file changed after its acceptance is refused
rather than mis-read.

**The expected file** (``read_expected``, written by step 4b's plan job) is canonical JSON with
exactly the keys ``format`` (``v4-verdict-expected-1``), ``mode``, ``cells`` (the 48 ids of
``all_cells()`` in order, the 44 of the non-v3 arms for ``timing``), ``window``, ``data`` (the
four pins of ``run.data_record``, never null), ``v3_pack_sha256`` and ``picks_sha256`` (64 hex
digits, both null for ``timing`` and only there).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any, NoReturn, TypeGuard

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec, all_cells
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.records import _loads, read_receipt
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    ACCOUNTING_IDENTITIES,
    ENGINE_ERROR,
    LIMIT_REASONS,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
    OUTCOME_COMPLETE,
    RECEIPT_FILE,
)
from crypto_grid_bot.v4.engine.summary import (
    ERAS,
    FAILURE_OUTCOMES,
    FULL_OUTCOMES,
    SUMMARY_FILE,
    SUMMARY_FORMAT,
)
from crypto_grid_bot.v4.engine.v3_as_built import (
    V3_ARM,
    V3_END_MS,
    V3_START_MS,
    V3_SUMMARY_FORMAT,
)

EXPECTED_FORMAT = "v4-verdict-expected-1"
MODES = ("rehearsal", "timing", "registered")
FOLDER = re.compile(
    r"v4-summary-(?P<cell>[a-z0-9_]+-[0-9]+-[12]x)-attempt-(?P<attempt>[1-9][0-9]*)"
)

# A real cell's summary is under 3 MB (about 50,000 hourly marks); this is far above that.
MAX_SUMMARY_BYTES = 32 << 20
MAX_EXPECTED_BYTES = 1 << 20
# The largest exponent magnitude of a Decimal string: far beyond any equity or residual, far
# inside what ``CONTEXT`` (Emax 999999) can multiply and divide.
MAX_EXPONENT = 1000

# The keys of a V4 full summary: ``summary.py``'s module docstring, pinned against a real summary
# by ``test_full_keys_match_a_real_summary``.
FULL_KEYS: frozenset[str] = frozenset(
    {
        "format",
        "cell",
        "window",
        "data",
        "outcome",
        "reason",
        "stop_ms",
        "initial_equity",
        "final_equity",
        "equity_2025",
        "final_after_close",
        "max_drawdown",
        "compounded_return",
        "liquidations",
        "accounting_residual",
        "receipt_sha256",
        "eras",
        "years",
        "open_marks",
    }
)
# ``v3_as_built`` adds V3's own disclosures (``v3_as_built.py``'s module docstring).
V3_FULL_KEYS: frozenset[str] = FULL_KEYS | {"disclosures"}
_HEAD_KEYS = frozenset({"format", "cell", "window", "data", "outcome"})
FAILURE_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        ACCOUNTING_FAILURE: _HEAD_KEYS | {"identity", "hour_ms", "values"},
        ENGINE_ERROR: _HEAD_KEYS | {"type", "message", "hour_ms"},
    }
)

_V3_OUTCOMES = frozenset({OUTCOME_COMPLETE, LIQUIDATED, ENGINE_ERROR})
_CELL_KEYS = frozenset({"id", "arm", "capital", "cost_multiple"})
_PERIOD_KEYS = frozenset({"start_ms", "end_ms", "start_equity", "end_equity", "return"})
_ERA_KEYS = _PERIOD_KEYS | {"name"}
_YEAR_KEYS = _PERIOD_KEYS | {"year"}
_VALUES_KEYS = frozenset({"wallet_residual", "quantity_residuals", "equity_residual"})
_DECIMALS = ("initial_equity", "final_equity", "max_drawdown", "compounded_return")
_OPTIONAL_DECIMALS = ("equity_2025", "final_after_close")
_WINDOW_KEYS = frozenset({"start_ms", "end_ms"})
_DATA_KEYS = frozenset({"config_sha256", "end_month", "daily_sha256", "index_sha256"})
_EXPECTED_KEYS = frozenset(
    {"format", "mode", "cells", "window", "data", "v3_pack_sha256", "picks_sha256"}
)
_HEX64 = re.compile("[0-9a-f]{64}")
_MONTH = re.compile(r"[0-9]{4}-(0[1-9]|1[0-2])")


class CellRefused(ValueError):
    """A cell whose summary is refused: the ``step`` of V1 to V3 that refused it (``folder``,
    ``rerun``, ``json``, ``format``, ``cell``, ``window``, ``data``, ``keys``, ``numbers``,
    ``marks`` or ``receipt``) and the ``reason``, in words, never quoting a value of the file."""

    def __init__(self, step: str, reason: str) -> None:
        super().__init__(step, reason)
        self.step = step
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.step}: {self.reason}"


@dataclass(frozen=True, slots=True)
class Expected:
    """What the cells of this run must carry (the module docstring's expected file)."""

    mode: str
    cells: tuple[str, ...]
    window: Mapping[str, int]
    data: Mapping[str, str]
    v3_pack_sha256: str | None
    picks_sha256: str | None


@dataclass(frozen=True, slots=True)
class CellFacts:
    """What the verdict keeps of one accepted cell. ``reason`` is the stop reason of a
    ``limit_unrestorable``, the failure type of an ``engine_error`` (``V3Stop``, ...) and the
    identity of an ``accounting_failure``. A failure summary has no figures: its Decimals are
    None but ``initial_equity``, the capital, and its ``marks`` is 0."""

    folder: str
    cell_id: str
    arm: str
    capital: int
    cost_multiple: int
    outcome: str
    reason: str | None
    stop_ms: int | None
    initial_equity: Decimal
    final_equity: Decimal | None
    equity_2025: Decimal | None
    final_after_close: Decimal | None
    compounded_return: Decimal | None
    max_drawdown: Decimal | None
    eras: tuple[Mapping[str, object], ...]
    years: tuple[Mapping[str, object], ...]
    disclosures: tuple[str, ...]
    summary_sha256: str
    marks: int


def _no(step: str, reason: str) -> NoReturn:
    raise CellRefused(step, reason)


# ---- exact values ---------------------------------------------------------------------------


def _exact(actual: object, wanted: object) -> bool:
    """Equality with exact JSON types: ``True`` is not 1, ``1.0`` is not 1, a list is not a
    tuple's twin."""
    if type(actual) is not type(wanted):
        return False
    if isinstance(wanted, dict) and isinstance(actual, dict):
        return actual.keys() == wanted.keys() and all(
            _exact(actual[key], item) for key, item in wanted.items()
        )
    if isinstance(wanted, list) and isinstance(actual, list):
        return len(actual) == len(wanted) and all(
            _exact(mine, theirs) for mine, theirs in zip(actual, wanted, strict=True)
        )
    return bool(actual == wanted)


def _decimal(value: object) -> Decimal | None:
    """The Decimal a string spells, or None if it is not a finite Decimal as the engine spells
    it (module docstring, step 9)."""
    if type(value) is not str:
        return None
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or str(number) != value or abs(number.adjusted()) > MAX_EXPONENT:
        return None
    return number


def _natural(value: object) -> TypeGuard[int]:
    return type(value) is int and value >= 0


def _hex(value: object) -> bool:
    return type(value) is str and _HEX64.fullmatch(value) is not None


# ---- reading one cell -----------------------------------------------------------------------


def read_cell(folder: Path, expected: Expected) -> CellFacts:
    """The facts of the cell in ``folder``, or ``CellRefused`` naming the first step that fails
    (module docstring). The folder is never changed."""
    folder = Path(folder)
    cell_id = _named(folder)
    raw = _summary_bytes(folder)
    summary = _document(raw)
    arm = cell_id.rsplit("-", 2)[0]
    _check_format(summary, arm)
    spec = _check_cell(summary, cell_id, expected)
    _check_window(summary, spec, expected)
    _check_data(summary, spec, expected)
    outcome = _check_keys(summary, spec)
    _check_numbers(summary, spec, outcome)
    marks: list[tuple[int, Decimal, bool]] = []
    if outcome in FULL_OUTCOMES:
        marks = _open_marks(summary, Decimal(spec.capital))
        _check_receipt(folder, summary)
    return _facts(folder.name, spec, outcome, summary, hashlib.sha256(raw).hexdigest(), len(marks))


def read_marks(folder: Path) -> list[tuple[int, Decimal, bool]]:
    """The open marks of a full cell ``read_cell`` accepted, as ``(hour_ms, equity, complete)``.
    The file is re-read and must still be canonical, with well-formed marks starting at the
    cell's capital; otherwise ``CellRefused``."""
    summary = _document(_summary_bytes(Path(folder)))
    cell = summary.get("cell")
    capital = cell.get("capital") if isinstance(cell, dict) else None
    if type(capital) is not int:
        _no("cell", "the summary has no cell with a capital")
    return _open_marks(summary, Decimal(capital))


def _named(folder: Path) -> str:
    """Steps 1 and 2: the folder's cell id; refuses a name that is not the format's, a path
    that is not a folder and any attempt but the first."""
    found = FOLDER.fullmatch(folder.name)
    if found is None:
        _no("folder", "the folder is not named v4-summary-<cell>-attempt-<n>")
    if folder.is_symlink() or not folder.is_dir():
        _no("folder", "the path is not a folder")
    if found["attempt"] != "1":
        _no("rerun", "the folder is a re-run: its attempt is not 1")
    return found["cell"]


def _summary_bytes(folder: Path) -> bytes:
    path = folder / SUMMARY_FILE
    try:
        if path.is_symlink() or not path.is_file():
            _no("json", f"{SUMMARY_FILE} is missing or is not a file")
        if path.stat().st_size > MAX_SUMMARY_BYTES:
            _no("json", f"{SUMMARY_FILE} is too large to be a cell's summary")
        return path.read_bytes()
    except OSError:
        _no("json", f"{SUMMARY_FILE} cannot be read")


def _document(raw: bytes) -> dict[str, Any]:
    """Step 3: the summary, if its bytes are the canonical JSON of their own strict parse."""
    try:
        document = _loads(raw)
        canonical = _canonical(document)
    except ValueError:
        _no(
            "json",
            f"{SUMMARY_FILE} is not strict JSON (UTF-8, unique keys, no floats, NaN or infinity)",
        )
    if canonical != raw:
        _no("json", f"{SUMMARY_FILE} is not in canonical form (sorted keys, no spaces, no newline)")
    if not isinstance(document, dict):
        _no("json", f"{SUMMARY_FILE} is not a JSON object")
    return document


def _check_format(summary: Mapping[str, Any], arm: str) -> None:
    wanted = V3_SUMMARY_FORMAT if arm == V3_ARM else SUMMARY_FORMAT
    if not _exact(summary.get("format"), wanted):
        _no("format", "the format is not the one the cell's arm writes")


def _check_cell(summary: Mapping[str, Any], cell_id: str, expected: Expected) -> CellSpec:
    """Step 5: the summary's cell is the folder's and is expected. Returns its spec."""
    if cell_id not in expected.cells:
        _no("cell", "the folder's cell is not one the expected file lists")
    cell = summary.get("cell")
    if not isinstance(cell, dict) or set(cell) != _CELL_KEYS:
        _no("cell", "the cell is not exactly an id, an arm, a capital and a cost multiple")
    try:
        spec = CellSpec(cell["arm"], cell["capital"], cell["cost_multiple"])
    except ValueError:
        _no("cell", "the cell's arm, capital or cost multiple is not one of the run's")
    if not _exact(cell["id"], spec.cell_id):
        _no("cell", "the cell's id is not the one its arm, capital and cost multiple make")
    if spec.cell_id != cell_id:
        _no("cell", "the summary is of another cell than its folder's")
    return spec


def _check_window(summary: Mapping[str, Any], spec: CellSpec, expected: Expected) -> None:
    wanted: dict[str, int] = (
        {"start_ms": V3_START_MS, "end_ms": V3_END_MS - HOUR_MS}
        if spec.arm == V3_ARM
        else dict(expected.window)
    )
    if not _exact(summary.get("window"), wanted):
        _no("window", "the window is not the expected one")


def _check_data(summary: Mapping[str, Any], spec: CellSpec, expected: Expected) -> None:
    wanted: dict[str, str | None] = (
        {"v3_pack_sha256": expected.v3_pack_sha256, "picks_sha256": expected.picks_sha256}
        if spec.arm == V3_ARM
        else dict(expected.data)
    )
    if not _exact(summary.get("data"), wanted):
        _no("data", "the data pins are not the expected ones")


# ---- keys -----------------------------------------------------------------------------------


def _check_keys(summary: Mapping[str, Any], spec: CellSpec) -> str:
    """Step 8: the outcome, the key set it has, and the shape of what is nested. Returns the
    outcome."""
    v3 = spec.arm == V3_ARM
    outcome = summary.get("outcome")
    allowed = _V3_OUTCOMES if v3 else FULL_OUTCOMES | FAILURE_OUTCOMES
    if type(outcome) is not str or outcome not in allowed:
        _no("keys", "the outcome is not one the cell's arm has")
    wanted = (
        FAILURE_KEYS[outcome]
        if outcome in FAILURE_OUTCOMES
        else (V3_FULL_KEYS if v3 else FULL_KEYS)
    )
    present = set(summary)
    if present != wanted:
        missing = sorted(wanted - present)
        _no(
            "keys",
            f"keys missing: {', '.join(missing)}"
            if missing
            else f"{len(present - wanted)} key(s) the outcome does not have",
        )
    if outcome in FAILURE_OUTCOMES:
        _check_failure_shape(summary, outcome)
        return outcome
    reason = summary["reason"]
    if outcome == LIMIT_UNRESTORABLE:
        reasoned = type(reason) is str and reason in LIMIT_REASONS
    else:
        reasoned = reason is None
    if not reasoned:
        _no("keys", "the reason is not the outcome's: null, or for a limit stop one of the limits")
    _check_periods(summary["eras"], _ERA_KEYS, "eras")
    _check_periods(summary["years"], _YEAR_KEYS, "years")
    if [era["name"] for era in summary["eras"]] != [name for name, _, _ in ERAS]:
        _no("keys", "the eras are not the format's three, in order")
    if v3:
        disclosures = summary["disclosures"]
        if not isinstance(disclosures, list) or not all(
            type(item) is str and item for item in disclosures
        ):
            _no("keys", "the disclosures are not a list of nonempty strings")
    return outcome


def _check_periods(periods: object, keys: frozenset[str], name: str) -> None:
    if (
        not isinstance(periods, list)
        or not periods
        or not all(isinstance(item, dict) and set(item) == keys for item in periods)
    ):
        _no("keys", f"{name} is not a list of periods with the format's keys")


def _check_failure_shape(summary: Mapping[str, Any], outcome: str) -> None:
    if outcome == ENGINE_ERROR:
        if type(summary["type"]) is not str or type(summary["message"]) is not str:
            _no("keys", "an engine error's type and message are not strings")
        return
    values = summary["values"]
    identity = summary["identity"]
    if type(identity) is not str or identity not in ACCOUNTING_IDENTITIES:
        _no("keys", "an accounting failure's identity is not one of the format's")
    if not isinstance(values, dict) or set(values) != _VALUES_KEYS:
        _no("keys", "an accounting failure's values are not the format's residuals")
    rows = values["quantity_residuals"]
    if not isinstance(rows, list) or not all(
        isinstance(row, list) and len(row) == 3 and type(row[0]) is str and type(row[1]) is str
        for row in rows
    ):
        _no("keys", "an accounting failure's quantity residuals are not [venue, symbol, value]")


# ---- numbers --------------------------------------------------------------------------------


def _check_numbers(summary: Mapping[str, Any], spec: CellSpec, outcome: str) -> None:
    """Step 9 (module docstring)."""
    if outcome in FAILURE_OUTCOMES:
        hour = summary["hour_ms"]
        if not (_natural(hour) or (hour is None and outcome == ENGINE_ERROR)):
            _no("numbers", "the failure's hour is not a non-negative integer")
        if outcome == ACCOUNTING_FAILURE:
            values = summary["values"]
            found = [values["wallet_residual"], values["equity_residual"]]
            found += [row[2] for row in values["quantity_residuals"]]
            if any(_decimal(item) is None for item in found):
                _no("numbers", "a residual is not a finite Decimal string")
        return
    for name in (*_DECIMALS, "accounting_residual"):
        if _decimal(summary[name]) is None:
            _no("numbers", f"{name} is not a finite Decimal string")
    for name in _OPTIONAL_DECIMALS:
        if summary[name] is not None and _decimal(summary[name]) is None:
            _no("numbers", f"{name} is neither null nor a finite Decimal string")
    if _decimal(summary["initial_equity"]) != Decimal(spec.capital):
        _no("numbers", "initial_equity is not the cell's capital")
    if summary["stop_ms"] is not None and not _natural(summary["stop_ms"]):
        _no("numbers", "stop_ms is neither null nor a non-negative integer")
    if not _natural(summary["liquidations"]):
        _no("numbers", "liquidations is not a non-negative integer")
    for name, label in (("eras", None), ("years", "year")):
        for index, period in enumerate(summary[name]):
            _check_period_numbers(period, f"{name}[{index}]", label)
    rows = summary["open_marks"]
    if isinstance(rows, list):  # a row of another shape is the marks step's
        for index, row in enumerate(rows):
            if isinstance(row, list) and len(row) == 3 and _decimal(row[1]) is None:
                _no("numbers", f"open_marks[{index}] holds an equity that is not a finite Decimal")


def _check_period_numbers(period: Mapping[str, Any], where: str, label: str | None) -> None:
    if label is not None and not _natural(period[label]):
        _no("numbers", f"{where}: {label} is not a non-negative integer")
    for name in ("start_ms", "end_ms"):
        if period[name] is not None and not _natural(period[name]):
            _no("numbers", f"{where}: {name} is neither null nor a non-negative integer")
    for name in ("start_equity", "end_equity", "return"):
        if period[name] is not None and _decimal(period[name]) is None:
            _no("numbers", f"{where}: {name} is neither null nor a finite Decimal string")


# ---- marks and receipt ----------------------------------------------------------------------


def _open_marks(summary: Mapping[str, Any], capital: Decimal) -> list[tuple[int, Decimal, bool]]:
    """Step 10: the open marks as ``(hour_ms, equity, complete)``."""
    rows = summary.get("open_marks")
    if not isinstance(rows, list) or not rows:
        _no("marks", "the summary has no open marks")
    marks: list[tuple[int, Decimal, bool]] = []
    for row in rows:
        if not (
            isinstance(row, list)
            and len(row) == 3
            and type(row[0]) is int
            and type(row[1]) is str
            and type(row[2]) is bool
        ):
            _no("marks", "an open mark is not [hour, equity, complete] of an int, a string, a flag")
        equity = _decimal(row[1])
        if equity is None:
            _no("numbers", "an open mark's equity is not a finite Decimal string")
        if marks and row[0] <= marks[-1][0]:
            _no("marks", "the open marks' hours do not strictly increase")
        marks.append((row[0], equity, row[2]))
    if marks[0][1] != capital:
        _no("marks", "the first open mark is not the cell's capital")
    return marks


def _check_receipt(folder: Path, summary: Mapping[str, Any]) -> None:
    """Step 11: ``receipt.json`` is a receipt in canonical form and is the one the summary names."""
    path = folder / RECEIPT_FILE
    if path.is_symlink() or not path.is_file():
        _no("receipt", f"{RECEIPT_FILE} is missing or is not a file")
    try:
        read_receipt(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except (ValueError, OSError):
        _no("receipt", f"{RECEIPT_FILE} is not a receipt in its canonical form")
    if not _exact(summary["receipt_sha256"], digest):
        _no("receipt", f"the summary names another {RECEIPT_FILE} than the one beside it")


# ---- the facts ------------------------------------------------------------------------------


def _optional_decimal(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _facts(
    name: str, spec: CellSpec, outcome: str, summary: Mapping[str, Any], digest: str, marks: int
) -> CellFacts:
    """The facts of a summary every step accepted."""
    head: dict[str, Any] = {
        "folder": name,
        "cell_id": spec.cell_id,
        "arm": spec.arm,
        "capital": spec.capital,
        "cost_multiple": spec.cost_multiple,
        "outcome": outcome,
        "initial_equity": Decimal(spec.capital),
        "summary_sha256": digest,
        "marks": marks,
    }
    if outcome in FAILURE_OUTCOMES:
        kind = summary["identity"] if outcome == ACCOUNTING_FAILURE else summary["type"]
        return CellFacts(
            **head,
            reason=kind,
            stop_ms=None,
            final_equity=None,
            equity_2025=None,
            final_after_close=None,
            compounded_return=None,
            max_drawdown=None,
            eras=(),
            years=(),
            disclosures=(),
        )
    return CellFacts(
        **head,
        reason=summary["reason"],
        stop_ms=summary["stop_ms"],
        final_equity=Decimal(summary["final_equity"]),
        equity_2025=_optional_decimal(summary["equity_2025"]),
        final_after_close=_optional_decimal(summary["final_after_close"]),
        compounded_return=Decimal(summary["compounded_return"]),
        max_drawdown=Decimal(summary["max_drawdown"]),
        eras=tuple(dict(item) for item in summary["eras"]),
        years=tuple(dict(item) for item in summary["years"]),
        disclosures=tuple(summary.get("disclosures", ())),
    )


_FACT_KEYS = frozenset(
    {
        "folder",
        "cell_id",
        "arm",
        "capital",
        "cost_multiple",
        "outcome",
        "reason",
        "stop_ms",
        "initial_equity",
        "final_equity",
        "equity_2025",
        "final_after_close",
        "compounded_return",
        "max_drawdown",
        "eras",
        "years",
        "disclosures",
        "summary_sha256",
        "marks",
    }
)
_FACT_DECIMALS = (
    "initial_equity",
    "final_equity",
    "equity_2025",
    "final_after_close",
    "compounded_return",
    "max_drawdown",
)


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def facts_record(facts: CellFacts) -> dict[str, object]:
    """The facts as a canonical-JSON-ready dict: Decimals as strings, tuples as lists."""
    return {
        "folder": facts.folder,
        "cell_id": facts.cell_id,
        "arm": facts.arm,
        "capital": facts.capital,
        "cost_multiple": facts.cost_multiple,
        "outcome": facts.outcome,
        "reason": facts.reason,
        "stop_ms": facts.stop_ms,
        "initial_equity": _text(facts.initial_equity),
        "final_equity": _text(facts.final_equity),
        "equity_2025": _text(facts.equity_2025),
        "final_after_close": _text(facts.final_after_close),
        "compounded_return": _text(facts.compounded_return),
        "max_drawdown": _text(facts.max_drawdown),
        "eras": [dict(item) for item in facts.eras],
        "years": [dict(item) for item in facts.years],
        "disclosures": list(facts.disclosures),
        "summary_sha256": facts.summary_sha256,
        "marks": facts.marks,
    }


def _periods(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("a facts record's eras and years are lists of objects")
    return tuple(dict(item) for item in value)


def facts_from_record(record: Mapping[str, object]) -> CellFacts:
    """The inverse of ``facts_record``, for the progress file. A record that is not exactly
    what ``facts_record`` writes is a ``ValueError``."""
    if not isinstance(record, Mapping) or set(record) != _FACT_KEYS:
        raise ValueError("a facts record has exactly the fields of CellFacts")
    folder, cell_id, arm = record["folder"], record["cell_id"], record["arm"]
    found = FOLDER.fullmatch(folder) if type(folder) is str else None
    if found is None or found["attempt"] != "1" or found["cell"] != cell_id:
        raise ValueError("a facts record's folder is not the first attempt of its cell")
    capital, multiple = record["capital"], record["cost_multiple"]
    if type(arm) is not str or type(capital) is not int or type(multiple) is not int:
        raise ValueError("a facts record's arm, capital and cost multiple are not str, int, int")
    if CellSpec(arm, capital, multiple).cell_id != cell_id:
        raise ValueError("a facts record's cell id is not its arm, capital and cost multiple")
    outcome = record["outcome"]
    if type(outcome) is not str or outcome not in FULL_OUTCOMES | FAILURE_OUTCOMES:
        raise ValueError("a facts record's outcome is not one of the run's")
    numbers: dict[str, Decimal | None] = {}
    for name in _FACT_DECIMALS:
        value = record[name]
        numbers[name] = None if value is None else _decimal(value)
        if value is not None and numbers[name] is None:
            raise ValueError(f"a facts record's {name} is not a finite Decimal string")
    initial = numbers.pop("initial_equity")
    if initial is None:
        raise ValueError("a facts record's initial_equity is null")
    reason, stop_ms, marks = record["reason"], record["stop_ms"], record["marks"]
    if reason is not None and type(reason) is not str:
        raise ValueError("a facts record's reason is neither a string nor null")
    if stop_ms is not None and not _natural(stop_ms):
        raise ValueError("a facts record's stop_ms is neither null nor a non-negative integer")
    if not _natural(marks) or not _hex(record["summary_sha256"]):
        raise ValueError("a facts record's marks or summary_sha256 is malformed")
    eras, years = _periods(record["eras"]), _periods(record["years"])
    notes = record["disclosures"]
    if not isinstance(notes, list) or not all(type(item) is str and item for item in notes):
        raise ValueError("a facts record's disclosures are not a list of nonempty strings")
    return CellFacts(
        folder=str(folder),
        cell_id=str(cell_id),
        arm=arm,
        capital=capital,
        cost_multiple=multiple,
        outcome=outcome,
        reason=reason,
        stop_ms=stop_ms,
        initial_equity=initial,
        final_equity=numbers["final_equity"],
        equity_2025=numbers["equity_2025"],
        final_after_close=numbers["final_after_close"],
        compounded_return=numbers["compounded_return"],
        max_drawdown=numbers["max_drawdown"],
        eras=eras,
        years=years,
        disclosures=tuple(notes),
        summary_sha256=str(record["summary_sha256"]),
        marks=int(marks),
    )


# ---- the expected file ----------------------------------------------------------------------


def expected_cells(mode: str) -> tuple[str, ...]:
    """The cells of a mode, in ``all_cells()`` order: all 48, or for ``timing`` the 44 of the
    arms that are not v3."""
    return tuple(
        cell.cell_id for cell in all_cells() if mode != "timing" or ARMS[cell.arm].family != "v3"
    )


def expected_record(expected: Expected) -> dict[str, object]:
    """The expected file's document (module docstring), for the writer; ``read_expected`` reads it
    back."""
    return {
        "format": EXPECTED_FORMAT,
        "mode": expected.mode,
        "cells": list(expected.cells),
        "window": dict(expected.window),
        "data": dict(expected.data),
        "v3_pack_sha256": expected.v3_pack_sha256,
        "picks_sha256": expected.picks_sha256,
    }


def read_expected(path: Path) -> Expected:
    """Read the expected file, refusing anything that is not exactly what the module docstring
    describes (a ``ValueError`` that names what is wrong, never a value)."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_EXPECTED_BYTES:
            raise ValueError("the expected file is too large")
        raw = path.read_bytes()
    except OSError:
        raise ValueError("the expected file cannot be read") from None
    try:
        document = _loads(raw)
        canonical = _canonical(document)
    except ValueError:
        raise ValueError("the expected file is not strict JSON") from None
    if canonical != raw:
        raise ValueError("the expected file is not in canonical form")
    if not isinstance(document, dict) or set(document) != _EXPECTED_KEYS:
        raise ValueError("the expected file does not have exactly the format's keys")
    if document["format"] != EXPECTED_FORMAT:
        raise ValueError(f"the expected file's format is not {EXPECTED_FORMAT}")
    mode = document["mode"]
    if type(mode) is not str or mode not in MODES:
        raise ValueError(f"the expected file's mode is not one of {', '.join(MODES)}")
    cells = document["cells"]
    if not isinstance(cells, list) or tuple(cells) != expected_cells(mode):
        raise ValueError("the expected file's cells are not the mode's, in all_cells() order")
    window = _expected_window(document["window"])
    data = _expected_data(document["data"])
    pins = (document["v3_pack_sha256"], document["picks_sha256"])
    if mode == "timing":
        if pins != (None, None):
            raise ValueError("a timing run has no v3 pins")
    elif not all(_hex(pin) for pin in pins):
        raise ValueError("the v3 pins are not 64 lowercase hex digits")
    return Expected(mode, expected_cells(mode), window, data, pins[0], pins[1])


def _expected_window(value: object) -> dict[str, int]:
    if (
        not isinstance(value, dict)
        or set(value) != _WINDOW_KEYS
        or not all(_natural(item) and item % HOUR_MS == 0 for item in value.values())
        or value["start_ms"] > value["end_ms"]
    ):
        raise ValueError("the expected window is not a start and an end, hour opens in order")
    return {"start_ms": value["start_ms"], "end_ms": value["end_ms"]}


def _expected_data(value: object) -> dict[str, str]:
    if (
        not isinstance(value, dict)
        or set(value) != _DATA_KEYS
        or not all(type(item) is str and item for item in value.values())
        or not all(_hex(value[name]) for name in ("daily_sha256", "index_sha256"))
        or _MONTH.fullmatch(value["end_month"]) is None
    ):
        raise ValueError("the expected data is not the four pins of run.data_record")
    return {name: str(value[name]) for name in sorted(_DATA_KEYS)}
