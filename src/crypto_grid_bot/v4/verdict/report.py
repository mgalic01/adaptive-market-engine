"""The verdict step's record forms and its run summary page (step 4b, task 4; rulings V11 to V14).

``scripts/v4_verdict.py`` computes; this module says how what it computed is written down. It
holds no state and reads only what it is given a path to (the dispatch reasons file, via
``read_dispatch_reasons``, and canonical JSON files, via ``read_canonical_json``).

**Record forms** (the progress file's and ``verdict.json``'s, owned here). A ``PathMeasure`` is an
object of its eight fields, a ``Check`` an object of its six, a ``Verdict`` its outcome, its
reasons and its eight checks. Every Decimal is its ``str``; the one infinite value is a ratio, and
it is the string ``"Infinity"``. ``measure_from_record`` and ``check_from_record`` are the inverses
and refuse anything but exactly what the writers write: the exact keys, exact types, a Decimal
spelled as ``str`` of its value, a ratio that may be ``Infinity`` and no other figure that may,
and a ``Check`` whose ``holds`` is what its two sides say (a progress file is replayed into the
verdict, so a record that contradicts itself is refused rather than believed).

**The document** (``verdict_document``) is the exact JSON the step writes as ``verdict.json``:

* ``format`` (``v4-verdict-1``), ``expected`` (``inputs.expected_record``), ``verdict`` (outcome,
  reasons, the 8 checks). A check of condition 1 or 2 that was computed has ``skipped_ms``, the
  sorted hour opens of its range that are not common boundaries of its two arms (the spec: "hours
  missing from any source are skipped for all arms alike and listed"), a list of integers; any
  other check has null there;
* ``cells``: the accepted cells' ``inputs.facts_record``, in the expected file's order, each with
  its eras, years and disclosures;
* ``missing`` (the cells that are missing or refused), ``refused`` (one ``{folder, step, reason}``
  per refused folder, sorted by folder), ``reruns`` (the cells with a re-run folder) and
  ``dispatches`` (the earlier dispatches the dispatch check found);
* ``pairs``: by cell id, ``{"hold": P, "v3": P}``, V11's reported comparisons of every non-v3 arm at
  each capital and cost against ``hold_universe`` and ``v3_as_built`` at the same capital and cost
  (condition 1's measure and condition 2's). ``P`` is ``{"main": measure, "other": measure,
  "skipped_hours": <the number of hours skipped>}`` (a count only) or, when the pair cannot be
  measured, ``{"incomputable": reason}``. None of it decides anything;
* ``analysis``: the name of the analysis step's artifact (V12), by mode.

It holds no timestamp and no path, so a resumed run writes the same bytes as an uninterrupted one.

**The page** (``render_verdict_page``, Markdown) is built from the document alone. Rehearsal and
timing pages open with ``SYNTHETIC``; then a title naming the mode; then, in this order: the
verdict (with a plain-language headline) and its reasons; the four conditions at each capital with
both sides' numbers (return, drawdown, ratio) and, for conditions 1 and 2, the number of skipped
hours (``verdict.json`` lists them); the spec's note on the eras; the comparison table of
every arm by capital by cost; the eras (and the years of ``v4_main``); the variants and neighbours
beside ``v4_main`` at 1x; the disclosures (every ``disclosures`` entry of the v3 summaries, so the
1,000 USDT capital adapter is named, and the synthetic world of a rehearsal); the missing, refused
and re-run cells and the other dispatches; the analysis artifact's name.

Every value that comes from a file or a run is escaped for Markdown (``escape``): a backslash, a
``|``, a backtick and a ``<`` get a backslash and every line break (and any control character)
becomes a space, so no value can end a table cell or a row, open a code span or a tag. Figures
are rounded for reading (percentages to 0.01, USDT to 0.01, ratios to 0.0001); ``verdict.json``
holds them exactly. A page is an artifact the owner reads: its outcomes and figures never reach
standard output (the step prints counts only).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.v4.engine.arms import ARMS, CAPITALS, COST_MULTIPLES
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.v3_as_built import V3_ARM, V3_CAPITAL_ADAPTER
from crypto_grid_bot.v4.verdict.inputs import (
    FOLDER,
    CellFacts,
    Expected,
    _bytes_of,
    _size_of,
    _strict,
    expected_record,
    facts_record,
)
from crypto_grid_bot.v4.verdict.rule import (
    CAPITALS_JUDGED,
    CONDITION_LABELS,
    MAIN_ARM,
    STOP_FAILS,
    Check,
    PathMeasure,
    Verdict,
    ratio,
)

VERDICT_FORMAT = "v4-verdict-1"
PROGRESS_FORMAT = "v4-verdict-progress-1"
# ``--dispatch-reasons``: ``v4_registration.py dispatch-check --judge-all`` writes this document.
DISPATCH_FORMAT = "v4-dispatch-check-1"
MAX_DISPATCH_BYTES = 1 << 20
# A figure of a record is bounded far beyond any equity or ratio of a real run.
MAX_FIGURE_EXPONENT = 10_000

SYNTHETIC = "Synthetic data: this is a test of the pipeline, not a result"
ERA_NOTE = (
    "Only the third era, 2025-01-01 to the end, was unseen when V4 was designed, so a pass means "
    "promising, not proven."
)
MODE_TITLES: Mapping[str, str] = {
    "registered": "registered run",
    "rehearsal": "rehearsal (synthetic data)",
    "timing": "timing run (synthetic data)",
}
# The analysis job's artifact by mode (plan, Task 10); ``<n>`` is the run attempt.
ANALYSIS_ARTIFACTS: Mapping[str, str] = {
    "registered": "v4-analysis-attempt-<n>",
    "rehearsal": "v4-rehearsal-analysis-attempt-<n>",
    "timing": "v4-timing-analysis-attempt-<n>",
}
SYNTHETIC_DISCLOSURE = (
    "This run used a synthetic world: its prices, funding, universe and v3 pack were generated by "
    "the rehearsal builder, so none of its numbers is a result of any market."
)
DISCLOSURE_WORDS: Mapping[str, str] = {
    V3_CAPITAL_ADAPTER: (
        "v3_as_built at 1,000 USDT is V3's own selector with only the starting capital changed "
        "(V3.1's capital adapter), not a V3 tuned for that capital."
    ),
}
# The variants and neighbours of V4's main arm (spec, "Versions in the run"), in the page's order.
VARIANT_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("volatility variants", ("v4_vol25", "v4_vol60")),
    ("neighbours (lookbacks x0.75 and x1.25)", ("v4_faster", "v4_slower")),
    ("other variants", ("v4_long_only", "v4_btc200_shorts", "v4_confirm3")),
)
NA = "n/a"

_MEASURE_FIELDS = (
    "hours",
    "first_ms",
    "last_ms",
    "start_equity",
    "end_equity",
    "compounded_return",
    "max_drawdown",
    "ratio",
)
_MEASURE_INTS = ("hours", "first_ms", "last_ms")
_CHECK_KEYS = frozenset({"condition", "capital", "holds", "main", "other", "note", "skipped_ms"})


# ---- the record forms -------------------------------------------------------------------------


def _parse(value: object) -> Decimal | None:
    """The Decimal a string spells, if it is spelled as ``str`` of that Decimal; else None."""
    if type(value) is not str:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if str(number) == value else None


def _figure(value: object, *, infinite: bool = False) -> Decimal:
    """A record's Decimal: finite and bounded, or (only where ``infinite``) the string
    ``"Infinity"``. Anything else is a ``ValueError`` that quotes nothing."""
    number = _parse(value)
    if number is None:
        raise ValueError("a record's figure is not a Decimal spelled as the step writes it")
    if number.is_infinite():
        if infinite and number > 0:
            return number
        raise ValueError("a record's figure is infinite where only a ratio may be")
    if not number.is_finite() or abs(number.adjusted()) > MAX_FIGURE_EXPONENT:
        raise ValueError("a record's figure is not a finite Decimal of a sensible size")
    return number


def measure_record(measure: PathMeasure) -> dict[str, object]:
    """A ``PathMeasure`` as exact JSON: integers, and Decimals as strings (``"Infinity"`` for an
    infinite ratio)."""
    return {
        "hours": measure.hours,
        "first_ms": measure.first_ms,
        "last_ms": measure.last_ms,
        "start_equity": str(measure.start_equity),
        "end_equity": str(measure.end_equity),
        "compounded_return": str(measure.compounded_return),
        "max_drawdown": str(measure.max_drawdown),
        "ratio": str(measure.ratio),
    }


def measure_from_record(record: object) -> PathMeasure:
    """The inverse of ``measure_record``; a record that is not exactly what it writes is a
    ``ValueError``."""
    if not isinstance(record, Mapping) or set(record) != set(_MEASURE_FIELDS):
        raise ValueError("a measure record has exactly the fields of PathMeasure")
    hours, first_ms, last_ms = (record[name] for name in _MEASURE_INTS)
    if not all(type(item) is int and item >= 0 for item in (hours, first_ms, last_ms)):
        raise ValueError("a measure record's hours and instants are not non-negative integers")
    if hours < 1 or last_ms < first_ms:
        raise ValueError("a measure record has no hour, or its last hour is before its first")
    return PathMeasure(
        hours=hours,
        first_ms=first_ms,
        last_ms=last_ms,
        start_equity=_figure(record["start_equity"]),
        end_equity=_figure(record["end_equity"]),
        compounded_return=_figure(record["compounded_return"]),
        max_drawdown=_figure(record["max_drawdown"]),
        ratio=_figure(record["ratio"], infinite=True),
    )


def _side(value: PathMeasure | Decimal | None) -> object:
    if value is None:
        return None
    return measure_record(value) if isinstance(value, PathMeasure) else str(value)


def check_record(check: Check) -> dict[str, object]:
    """A ``Check`` as exact JSON: its two sides are measure records (conditions 1 and 2) or
    Decimal strings (3 and 4), null when it could not be computed. ``skipped_ms`` is the sorted
    list of the hours its range skipped (conditions 1 and 2 when computed), else null."""
    return {
        "condition": check.condition,
        "capital": check.capital,
        "holds": check.holds,
        "main": _side(check.main),
        "other": _side(check.other),
        "note": check.note,
        "skipped_ms": None if check.skipped_ms is None else list(check.skipped_ms),
    }


def _skipped_from_record(value: object) -> tuple[int, ...]:
    """A list of skipped hours: hour opens, strictly increasing; else a ``ValueError``."""
    if not isinstance(value, list):
        raise ValueError("a check record's skipped hours are not a list")
    previous = -1
    for hour in value:
        if type(hour) is not int or hour <= previous or hour % HOUR_MS != 0:
            raise ValueError(
                "a check record's skipped hours are not strictly increasing hour opens"
            )
        previous = hour
    return tuple(value)


def _holds(condition: int, main: PathMeasure | Decimal, other: PathMeasure | Decimal) -> bool:
    """What a condition's two sides say: conditions 1 compares the ratios, 2 the returns, and 3
    and 4 the two equities (the rule's own comparisons)."""
    if isinstance(main, PathMeasure) and isinstance(other, PathMeasure):
        if condition == 1:
            return main.ratio > other.ratio
        return main.compounded_return > other.compounded_return
    if isinstance(main, Decimal) and isinstance(other, Decimal):
        return main > other
    raise ValueError("a check's two sides are not of one kind")


def check_from_record(record: object) -> Check:
    """The inverse of ``check_record``. A record that is not exactly what it writes, or whose
    ``holds`` is not what its sides say, is a ``ValueError``."""
    if not isinstance(record, Mapping) or set(record) != _CHECK_KEYS:
        raise ValueError("a check record has exactly the fields of Check")
    condition, capital, holds, note = (
        record["condition"],
        record["capital"],
        record["holds"],
        record["note"],
    )
    if type(condition) is not int or condition not in CONDITION_LABELS:
        raise ValueError("a check record's condition is not one of the rule's four")
    if type(capital) is not int or capital not in CAPITALS_JUDGED:
        raise ValueError("a check record's capital is not a judged one")
    if holds is not None and type(holds) is not bool:
        raise ValueError("a check record's holds is neither a boolean nor null")
    if note is not None and type(note) is not str:
        raise ValueError("a check record's note is neither a string nor null")
    if (holds is None) != (note is not None):
        raise ValueError("a check record has a note exactly when it could not be computed")
    main, other, skipped = record["main"], record["other"], record["skipped_ms"]
    if holds is None:
        if main is not None or other is not None or skipped is not None:
            raise ValueError("a check that could not be computed has no sides and no hours")
        return Check(condition, capital, None, None, None, note)
    sides: tuple[PathMeasure | Decimal, PathMeasure | Decimal]
    if condition in (1, 2):
        sides = (measure_from_record(main), measure_from_record(other))
        hours: tuple[int, ...] | None = _skipped_from_record(skipped)
    else:
        sides = (_figure(main), _figure(other))
        if skipped is not None:
            raise ValueError("a check of condition 3 or 4 has no skipped hours")
        hours = None
    if holds is not _holds(condition, *sides):
        raise ValueError("a check record's holds is not what its two sides say")
    return Check(condition, capital, holds, sides[0], sides[1], None, hours)


def verdict_record(verdict: Verdict) -> dict[str, object]:
    """A ``Verdict`` as exact JSON: outcome, reasons and its eight checks."""
    return {
        "outcome": verdict.outcome,
        "reasons": list(verdict.reasons),
        "checks": [check_record(check) for check in verdict.checks],
    }


# ---- the dispatch reasons ---------------------------------------------------------------------


def read_canonical_json(path: Path, limit: int, what: str) -> object:
    """The parse of a file that must be strict canonical JSON: at most ``limit`` bytes, UTF-8,
    unique keys, no floats, NaN or infinity, and byte for byte ``combined.artifacts._canonical``
    of its own parse (sorted keys, no spaces, no newline). Otherwise a ``ValueError`` that names
    ``what`` and quotes nothing of the file."""
    size = _size_of(Path(path))
    if size is not None and size > limit:
        raise ValueError(f"{what} is too large")
    raw = _bytes_of(Path(path))
    if raw is None:
        raise ValueError(f"{what} cannot be read")
    parsed = _strict(raw)
    if parsed is None:
        raise ValueError(f"{what} is not strict JSON (UTF-8, unique keys, no floats, NaN)")
    document, canonical = parsed
    if canonical != raw:
        raise ValueError(f"{what} is not in canonical form")
    return document


def read_dispatch_reasons(path: Path) -> tuple[str, ...]:
    """The earlier dispatches of ``--dispatch-reasons``: canonical JSON ``{"format":
    "v4-dispatch-check-1", "earlier": [<non-empty strings>]}`` and nothing else. Any other shape
    is a ``ValueError`` that says what is wrong and quotes nothing of the file."""
    document = read_canonical_json(path, MAX_DISPATCH_BYTES, "the dispatch reasons file")
    if not isinstance(document, dict) or set(document) != {"format", "earlier"}:
        raise ValueError("the dispatch reasons file does not have exactly format and earlier")
    if document["format"] != DISPATCH_FORMAT:
        raise ValueError(f"the dispatch reasons file's format is not {DISPATCH_FORMAT}")
    earlier = document["earlier"]
    if not isinstance(earlier, list) or not all(type(item) is str and item for item in earlier):
        raise ValueError("the dispatch reasons file's earlier is not a list of non-empty strings")
    return tuple(earlier)


# ---- the document -----------------------------------------------------------------------------


def rerun_cells(refused: Mapping[str, tuple[str, str]]) -> list[str]:
    """The cells that have a re-run folder: the folders refused at step ``rerun`` (their names
    are the format's, or ``read_cell`` would have refused them at ``folder``), once each, sorted."""
    cells = set()
    for folder, (step, _) in refused.items():
        found = FOLDER.fullmatch(folder) if step == "rerun" else None
        if found is not None:
            cells.add(found["cell"])
    return sorted(cells)


def verdict_document(
    expected: Expected,
    verdict: Verdict,
    accepted: Mapping[str, CellFacts],
    refused: Mapping[str, tuple[str, str]],
    missing: Sequence[str],
    pairs: Mapping[str, Mapping[str, object]],
    dispatches: Sequence[str],
) -> dict[str, object]:
    """The document of ``verdict.json`` (module docstring). ``accepted`` is the accepted cells by
    id, ``refused`` the refused folders by name (step, reason), ``missing`` the cells that are
    missing or refused, ``pairs`` V11's comparisons by cell id and ``dispatches`` the earlier
    dispatches."""
    return {
        "format": VERDICT_FORMAT,
        "expected": expected_record(expected),
        "verdict": verdict_record(verdict),
        "cells": [facts_record(accepted[cell]) for cell in expected.cells if cell in accepted],
        "missing": list(missing),
        "refused": [
            {"folder": folder, "step": step, "reason": reason}
            for folder, (step, reason) in sorted(refused.items())
        ],
        "reruns": rerun_cells(refused),
        "dispatches": list(dispatches),
        "pairs": {cell: dict(rows) for cell, rows in sorted(pairs.items())},
        "analysis": ANALYSIS_ARTIFACTS[expected.mode],
    }


# ---- escaping and figures ---------------------------------------------------------------------


def escape(value: object) -> str:
    """``value`` as text that is safe in a Markdown table cell or line: a backslash, ``|``, a
    backtick and ``<`` are escaped, and every line break and other control character is a space."""
    out: list[str] = []
    for char in str(value):
        if char in "\\|`<":
            out.append("\\" + char)
        elif unicodedata.category(char) in ("Cc", "Zl", "Zp"):
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def _decimal(value: object) -> Decimal | None:
    """A figure of the document, leniently: None for an absent or unreadable one (the page
    never fails on a figure)."""
    number = _parse(value)
    return number if number is not None and not number.is_nan() else None


def _percent(value: object, *, signed: bool = False) -> str:
    """A fraction as a percentage to 0.01 (a return is signed, a drawdown is not)."""
    number = _decimal(value)
    if number is None or not number.is_finite():
        return NA
    with localcontext(CONTEXT):
        scaled = number * 100
    return f"{scaled:+,.2f} %" if signed else f"{scaled:,.2f} %"


def _usdt(value: object) -> str:
    number = _decimal(value)
    return f"{number:,.2f}" if number is not None and number.is_finite() else NA


def _ratio_text(number: Decimal | None) -> str:
    if number is None:
        return NA
    if number.is_infinite():
        return "infinite" if number > 0 else NA
    return f"{number:,.4f}"


def _own_ratio(cell: Mapping[str, Any] | None) -> str:
    """A cell's own return over drawdown (V5's zero-drawdown rule), from its summary's figures."""
    if cell is None or cell["compounded_return"] is None or cell["max_drawdown"] is None:
        return NA
    compounded, drawdown = _decimal(cell["compounded_return"]), _decimal(cell["max_drawdown"])
    if compounded is None or drawdown is None:
        return NA
    try:
        return _ratio_text(ratio(compounded, drawdown))
    except ValueError:
        return NA


def _measure_text(record: object) -> str:
    """One side of a condition: its return, drawdown and ratio."""
    if not isinstance(record, Mapping):
        return NA
    return (
        f"return {_percent(record.get('compounded_return'), signed=True)}, "
        f"drawdown {_percent(record.get('max_drawdown'))}, "
        f"ratio {_ratio_text(_decimal(record.get('ratio')))}"
    )


def _table(head: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    lines.extend("| " + " | ".join(escape(item) for item in row) + " |" for row in rows)
    return lines


def _bullets(items: Iterable[object], none: str) -> list[str]:
    lines = [f"- {escape(item)}" for item in items]
    return lines or [none]


# ---- the page ---------------------------------------------------------------------------------


class _View:
    """What the page reads of the document, by cell."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self.document = document
        self.mode: str = document["expected"]["mode"]
        self.verdict: Mapping[str, Any] = document["verdict"]
        self.cells: dict[str, Mapping[str, Any]] = {
            cell["cell_id"]: cell for cell in document["cells"]
        }
        self.pairs: Mapping[str, Mapping[str, Any]] = document["pairs"]
        self.refused_steps: dict[str, list[str]] = {}
        for row in document["refused"]:
            found = FOLDER.fullmatch(row["folder"])
            if found is not None:
                self.refused_steps.setdefault(found["cell"], []).append(row["step"])

    def status(self, cell_id: str) -> str:
        """The outcome of an accepted cell; else why it is not one."""
        cell = self.cells.get(cell_id)
        if cell is not None:
            return str(cell["outcome"])
        steps = self.refused_steps.get(cell_id)
        return f"refused ({', '.join(sorted(set(steps)))})" if steps else "missing"

    def pair(self, cell_id: str, kind: str) -> Mapping[str, Any] | None:
        found = self.pairs.get(cell_id, {}).get(kind)
        return found if isinstance(found, Mapping) else None


def _cells() -> Iterable[tuple[str, str]]:
    """Every cell in the run's order, as its arm and its id."""
    for arm in ARMS:
        for capital in CAPITALS:
            for multiple in COST_MULTIPLES:
                yield arm, f"{arm}-{capital}-{multiple}x"


def _pair_columns(view: _View, arm: str, cell_id: str) -> tuple[str, str]:
    """The comparison table's last two columns: condition 1's measure (ratio, the arm over
    ``hold_universe``) and condition 2's (return, the arm over ``v3_as_built``)."""
    if ARMS[arm].family == "v3":
        return NA, NA
    columns = []
    for kind, field in (("hold", "ratio"), ("v3", "compounded_return")):
        pair = view.pair(cell_id, kind)
        if pair is None:
            columns.append(NA)
        elif "incomputable" in pair:
            columns.append("cannot be computed")
        else:
            main, other = pair["main"], pair["other"]
            if field == "ratio":
                text = (
                    f"{_ratio_text(_decimal(main['ratio']))} / "
                    f"{_ratio_text(_decimal(other['ratio']))}"
                )
            else:
                text = (
                    f"{_percent(main['compounded_return'], signed=True)} / "
                    f"{_percent(other['compounded_return'], signed=True)}"
                )
            columns.append(text)
    return columns[0], columns[1]


def _cell_row(view: _View, arm: str, cell_id: str) -> list[object]:
    cell = view.cells.get(cell_id)
    own = (
        (
            _percent(cell["compounded_return"], signed=True),
            _percent(cell["max_drawdown"]),
            _own_ratio(cell),
        )
        if cell is not None and cell["compounded_return"] is not None
        else (NA, NA, NA)
    )
    return [cell_id, view.status(cell_id), *own, *_pair_columns(view, arm, cell_id)]


_CELL_HEAD = (
    "Cell",
    "Outcome",
    "Return",
    "Max drawdown",
    "Return / drawdown",
    "Cond. 1 measure: ratio, arm / hold_universe",
    "Cond. 2 measure: return, arm / v3_as_built",
)


def _headline(view: _View) -> str:
    checks = view.verdict["checks"]
    failed = sum(1 for check in checks if check["holds"] is False)
    outcome = view.verdict["outcome"]
    stopped = any(
        cell["arm"] == MAIN_ARM and cell["outcome"] in STOP_FAILS for cell in view.cells.values()
    )
    if outcome == "pass":
        return (
            f"{MAIN_ARM} met all {len(checks)} checks, the four conditions at both capitals, so "
            "under the registered rule V4.0 passes. That means promising, not proven."
        )
    if outcome == "fail" and stopped:
        return (
            f"{MAIN_ARM} was stopped in at least one cell (liquidated, a limit it could not "
            "restore, or an accounting failure), which fails V4.0 whatever else is missing."
        )
    if outcome == "fail":
        return f"{failed} of the {len(checks)} checks do not hold, so V4.0 fails the rule."
    return (
        "The verdict cannot be given: something the rule needs is missing, refused, re-run, "
        "repeated by another dispatch or cannot be computed, and an incomplete run is never a "
        "pass. The reasons say which."
    )


def _verdict_section(view: _View) -> list[str]:
    checks = view.verdict["checks"]
    count = {
        key: sum(1 for check in checks if check["holds"] is key) for key in (True, False, None)
    }
    outcome = str(view.verdict["outcome"])
    lines = [
        "## The verdict",
        "",
        f"**{outcome.upper()}.** {_headline(view)}",
        "",
        f"Checks that hold: {count[True]} of {len(checks)}; that do not hold: {count[False]}; "
        f"that cannot be computed: {count[None]}. Figures on this page are rounded for reading; "
        "`verdict.json` beside it holds them exactly.",
        "",
        "Reasons:",
        "",
    ]
    lines += _bullets(view.verdict["reasons"], "- None: nothing is missing and every check holds.")
    return lines


def _side_text(condition: int, side: object, other: bool) -> str:
    """One side of a condition: its measure (1 and 2) or its equity (3 and 4)."""
    if side is None:
        return NA
    if condition in (1, 2):
        name = ("hold_universe" if condition == 1 else "v3_as_built") if other else MAIN_ARM
        return f"{name}: {_measure_text(side)}"
    if not other:
        return f"final after close {_usdt(side)}"
    return (
        f"initial equity {_usdt(side)}" if condition == 3 else f"equity at 2025-01-01 {_usdt(side)}"
    )


def _conditions_section(view: _View) -> list[str]:
    lines = [
        "## The four conditions",
        "",
        "Each condition at each capital, with both sides' numbers. Return is the compounded return "
        "over the path the condition names, drawdown the maximum drawdown over the same path and "
        "ratio their quotient (infinite when there is no drawdown and the return is positive). "
        "Conditions 1 and 2 skip, for both arms alike, the hours at which either arm has no "
        "complete mark: the table counts them, and `verdict.json` lists them "
        "(`verdict.checks[].skipped_ms`).",
    ]
    for capital in CAPITALS_JUDGED:
        rows = []
        for check in view.verdict["checks"]:
            if check["capital"] != capital:
                continue
            condition = check["condition"]
            holds = {True: "yes", False: "no", None: "cannot be computed"}[check["holds"]]
            rows.append(
                [
                    condition,
                    CONDITION_LABELS[condition],
                    holds,
                    _side_text(condition, check["main"], False),
                    _side_text(condition, check["other"], True),
                    NA if check["skipped_ms"] is None else len(check["skipped_ms"]),
                    check["note"] or "",
                ]
            )
        lines += ["", f"### Capital {capital} USDT", ""]
        lines += _table(
            [
                "Condition",
                "What it compares",
                "Holds",
                MAIN_ARM,
                "Other side",
                "Skipped hours",
                "Note",
            ],
            rows,
        )
    return lines


def _comparison_section(view: _View) -> list[str]:
    lines = [
        "## The comparison table",
        "",
        "Every arm, by capital and by cost (1x is normal costs, 2x doubled). The last two columns "
        "are reported only, using condition 1's measure (return over drawdown over the hours both "
        "arms have a complete mark, then each one's equity after its window-end close) and "
        "condition 2's (compounded return over the hours both have a complete mark from "
        "2021-07-01 00:00 to 2024-12-31 23:00), against `hold_universe` and `v3_as_built` at the "
        "same capital and cost. Nothing here decides the verdict except through the four "
        "conditions above.",
        "",
    ]
    rows = [_cell_row(view, arm, cell_id) for arm, cell_id in _cells()]
    return lines + _table(_CELL_HEAD, rows)


def _eras_section(view: _View) -> list[str]:
    names = ("start-2020", "2021-2024", "2025-end")
    lines = [
        "## The eras",
        "",
        "Each cell's compounded return in the spec's three eras: the window's start to 2020-12-31, "
        "2021-01-01 to 2024-12-31, and 2025-01-01 to the end. n/a is an era the cell did not "
        "trade.",
        "",
    ]
    rows = []
    for _, cell_id in _cells():
        cell = view.cells.get(cell_id)
        if cell is None or not cell["eras"]:
            continue
        returns = {era["name"]: era["return"] for era in cell["eras"]}
        rows.append(
            [
                cell_id,
                cell["outcome"],
                *(_percent(returns.get(name), signed=True) for name in names),
            ]
        )
    lines += _table(["Cell", "Outcome", *names], rows) if rows else ["No cell has eras."]
    mains = [cell_id for arm, cell_id in _cells() if arm == MAIN_ARM]
    years: dict[int, dict[str, object]] = {}
    for cell_id in mains:
        for year in (view.cells.get(cell_id) or {"years": ()})["years"]:
            years.setdefault(int(year["year"]), {})[cell_id] = year["return"]
    lines += ["", f"### Years of {MAIN_ARM}", ""]
    if years:
        year_rows = [
            [year, *(_percent(years[year].get(cell_id), signed=True) for cell_id in mains)]
            for year in sorted(years)
        ]
        lines += _table(["Year", *mains], year_rows)
    else:
        lines.append(f"No {MAIN_ARM} cell has years.")
    return lines


def _variants_section(view: _View) -> list[str]:
    lines = [
        "## Variants and neighbours at 1x",
        "",
        f"{MAIN_ARM} beside its volatility variants, its neighbours and the v4-d22 arms, at normal "
        "costs. Reported only.",
    ]
    for capital in CAPITALS:
        lines += ["", f"### Capital {capital} USDT", ""]
        rows = []
        for group, arms in (("the main arm", (MAIN_ARM,)), *VARIANT_GROUPS):
            for arm in arms:
                cell_id = f"{arm}-{capital}-1x"
                rows.append([group, *_cell_row(view, arm, cell_id)])
        lines += _table(["Group", *_CELL_HEAD], rows)
    return lines


def _disclosures_section(view: _View) -> list[str]:
    lines = ["## Disclosures", ""]
    noted: dict[str, list[str]] = {}
    for arm, cell_id in _cells():
        cell = view.cells.get(cell_id)
        if arm == V3_ARM and cell is not None:
            for note in cell["disclosures"]:
                noted.setdefault(note, []).append(cell_id)
    items: list[str] = []
    if view.mode != "registered":
        items.append(SYNTHETIC_DISCLOSURE)
    for note, cells in noted.items():
        words = DISCLOSURE_WORDS.get(note)
        items.append(f"{note}: in {', '.join(cells)}." + (f" {words}" if words else ""))
    if not noted:
        has_v3 = any(arm == V3_ARM for arm, cell_id in _cells() if cell_id in view.cells)
        items.append(
            "The accepted v3 summaries carried no disclosures."
            if has_v3
            else "No v3 summary was accepted, so no v3 disclosure was read."
        )
    return lines + _bullets(items, "None.")


def _missing_section(view: _View) -> list[str]:
    document = view.document
    lines = [
        "## Missing, refused and re-run cells, and other dispatches",
        "",
        "### Missing cells",
        "",
    ]
    lines += _bullets(document["missing"], "None.")
    lines += ["", "### Refused folders", ""]
    refused = document["refused"]
    lines += (
        _table(
            ["Folder", "Step", "Reason"], [[r["folder"], r["step"], r["reason"]] for r in refused]
        )
        if refused
        else ["None."]
    )
    lines += ["", "### Re-run cells", ""]
    lines += _bullets(document["reruns"], "None.")
    lines += ["", "### Other dispatches", ""]
    lines += _bullets(document["dispatches"], "None.")
    return lines


def _analysis_section(view: _View) -> list[str]:
    return [
        "## The analysis artifact",
        "",
        "The run summary is two pages. This is the first. The second, `diagnosis.md` (long "
        "against short, and per coin, from the records), is in the analysis step's artifact "
        f"`{view.document['analysis']}`, where `<n>` is the run attempt of this run.",
    ]


def render_verdict_page(document: Mapping[str, object]) -> str:
    """The run summary's first page, as Markdown (module docstring), from ``verdict_document``'s
    document."""
    view = _View(document)
    title = f"# V4.0 verdict: {MODE_TITLES[view.mode]}"
    lines: list[str] = [SYNTHETIC, ""] if view.mode != "registered" else []
    lines += [title, ""]
    lines += _verdict_section(view)
    lines += [""] + _conditions_section(view)
    lines += ["", "## A note from the spec", "", ERA_NOTE]
    lines += [""] + _comparison_section(view)
    lines += [""] + _eras_section(view)
    lines += [""] + _variants_section(view)
    lines += [""] + _disclosures_section(view)
    lines += [""] + _missing_section(view)
    lines += [""] + _analysis_section(view)
    return "\n".join(lines) + "\n"
