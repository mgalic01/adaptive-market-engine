"""Each cell's ``summary.json``, its self-verification and its HTML page.

Implements the spec's "Reports" (the fields of a full summary, the outcomes and their nulls, the
short failure summaries), the parts of "Pass rule" a cell supplies (the open marks with their
completeness flags, from which the verdict computes the common measure for every arm; the eras;
"promising, not proven") and "Safety" (a cell that stops early: the stop's mark is the final
equity, and the marks run to the stop).

**From the records alone.** ``build_summary`` reads the cell's ``records.jsonl`` to the end through
``read_records``, so the hash chain and the receipt are checked, and takes every number from its
``hourly`` and ``outcome`` records. The cell spec gives only the cell and the initial equity (its
capital). The ``CellResult`` is only cross-checked: its outcome, reason and stop, and for a full
summary its open marks, final equity, equity at 2025-01-01 and equity after the close, must be
what the records say, and its receipt must be the ``receipt.json`` next to the records. Every
mismatch is a ``ValueError`` naming the field. ``verify_summary`` takes the cell from the summary,
rebuilds the summary the same way and requires equality, with exact types (``true`` is not ``1``),
raising a ``ValueError`` that names the first differing field (``open_marks[5][1]``,
``eras[2].return``).

**The cell, its window and its data are bound to the records.** The outcome record names its
``cell``, its ``window`` and the ``data`` it was replayed on (run.py's ``cell_record``,
``window_record`` and ``data_record``). The rebuild requires that cell to be the one asked for
(``build_summary``'s spec, or the summary's own ``cell``), and the first open mark, taken before
any fill, to equal its capital. It requires the first hourly record to be the window's first hour
(``start_ms``), no hour after its last (``end_ms``), and a complete cell to end at that last hour.
So a summary relabelled to another arm, capital, cost level or window does not verify, records
that start late or a complete cell that ends early are refused, and every number of a summary,
``initial_equity`` included, is checked against the records.

**Exact JSON.** Every Decimal is a string. Equities are spelled as the records spell them; the
computed values are ``str`` of a Decimal computed under ``CONTEXT``. ``write_cell_outputs``
writes the summary as V3.1's canonical JSON (sorted keys, no spaces, ASCII, no newline), so its
bytes and SHA-256 are deterministic.

**A full summary** (outcome ``complete``, ``liquidated`` or ``limit_unrestorable``) has exactly
these keys:

* ``format`` (``v4-summary-1``); ``cell``: ``id``, ``arm``, ``capital``, ``cost_multiple``;
  ``window``: the outcome record's ``start_ms`` and ``end_ms`` (the opens of the window's first
  and last hour); ``data``: the outcome record's (``config_sha256``, ``end_month``,
  ``daily_sha256``, ``index_sha256``), or null for a market built in memory;
* ``outcome``; ``reason`` (null, or for ``limit_unrestorable`` one of run.py's
  ``LIMIT_REASONS``); ``stop_ms`` (the stop's hour, null for ``complete``). Both are always
  present, so no field of a full summary is missing;
* ``initial_equity`` (the capital); ``final_equity`` (the outcome record's: after the window-end
  close, or the stop's mark); ``equity_2025`` (the open mark at 2025-01-01 00:00 UTC, null without
  one); ``final_after_close`` (null for a stop);
* ``max_drawdown``: ``trend.metrics.maximum_drawdown`` over the open-mark equities, then the final
  equity; ``compounded_return``: ``final_equity / initial_equity - 1``;
* ``liquidations``: 1 for ``liquidated``, else 0; ``accounting_residual``: the largest absolute
  ``equity_residual`` of the hourly audits; ``receipt_sha256``: the SHA-256 of ``receipt.json``;
* ``eras``: the three of ``ERAS``, each ``name``, ``start_ms``, ``end_ms``, ``start_equity``,
  ``end_equity`` and ``return``; ``years``: one per calendar year from the first simulated hour's
  to the last's, each ``year`` and the same five;
* ``open_marks``: ``[open_ms, equity, complete]`` for every hour with an open mark, in order. Only
  the hour of a stop at its synthetic closes, before its open mark, has none.

**A period** (an era or a year) starts at the open mark of its first simulated hour, the later of
its own start and the window's. It ends at the open mark of the hour that starts the next period;
when there is none, because the cell ended inside the period or stopped at that hour before its
open mark, it ends at the final equity, at the window's end for a complete cell (the last hour's
open plus one hour) or at ``stop_ms`` for a stop. Its return is ``end / start - 1`` under
``CONTEXT``, null when the start equity is not positive. A period with no open mark at its first
hour, because the window starts after it, the cell never reached it, or it lies wholly after the
stop, has every value null. The years after a stop are not listed: the records do not say where
the window would have ended.

**A failure summary** has only ``format``, ``cell``, ``window``, ``data``, ``outcome`` and the
failure's details:
``accounting_failure`` its ``identity`` (``wallet``, ``quantity`` or ``equity``), ``hour_ms`` and
the residual ``values``; ``engine_error`` the exception's ``type`` and ``message`` and ``hour_ms``
(null if before the first hour). It holds no audit residual: a result's audit is a fresh ledger's
zeros until the first audit, so an engine error's would read as clean.

**The page** (``render_page``) is self-contained HTML: no script, nothing fetched, system fonts,
every text value escaped, and a Content-Security-Policy that allows only its inline style. It
shows the outcome, the plain statement that only the third era was unseen when V4 was designed,
so a pass means "promising", not "proven", and then either the failure's details or the headline
numbers (rounded for reading), the equity path as an inline SVG sparkline (at most
``SPARKLINE_POINTS`` evenly spaced points, first and last included) and the eras and years
tables.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from html import escape
from pathlib import Path

from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.combined.artifacts import _canonical, _digest
from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.v4.engine.arms import CellSpec
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.records import Receipt, read_receipt, read_records
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    ACCOUNTING_IDENTITIES,
    ENGINE_ERROR,
    EQUITY_2025_MS,
    LIMIT_REASONS,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
    OUTCOME_COMPLETE,
    RECEIPT_FILE,
    CellResult,
    cell_record,
)

SUMMARY_FORMAT = "v4-summary-1"
SUMMARY_FILE = "summary.json"
PAGE_FILE = "report.html"

FULL_OUTCOMES = frozenset({OUTCOME_COMPLETE, LIQUIDATED, LIMIT_UNRESTORABLE})
FAILURE_OUTCOMES = frozenset({ACCOUNTING_FAILURE, ENGINE_ERROR})

_START_2021 = month_bounds_ms("2021-01")[0]
# Spec "Pass rule", the eras: (name, start, end) in ms; None is the window's own bound.
ERAS: tuple[tuple[str, int | None, int | None], ...] = (
    ("start-2020", None, _START_2021),
    ("2021-2024", _START_2021, EQUITY_2025_MS),
    ("2025-end", EQUITY_2025_MS, None),
)
SPARKLINE_POINTS = 1000

_CELL_KEYS = frozenset({"id", "arm", "capital", "cost_multiple"})
_WINDOW_KEYS = frozenset({"start_ms", "end_ms"})
_DATA_KEYS = frozenset({"config_sha256", "end_month", "daily_sha256", "index_sha256"})
_PERIOD_KEYS = ("start_ms", "end_ms", "start_equity", "end_equity", "return")
_NOTE = (
    "Only the third era, 2025-01-01 to the end, was unseen when V4 was designed, "
    "so a pass means promising, not proven."
)


# ---- reading the records --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Hour:
    """One ``hourly`` record: the open mark as the record spells it (None when the hour stopped
    before it), its completeness flag, and the audit's equity residual."""

    open_ms: int
    equity: str | None
    complete: bool | None
    residual: Decimal


@dataclass(frozen=True, slots=True)
class _Records:
    hours: tuple[_Hour, ...]
    outcome: Mapping[str, object]
    window: Mapping[str, int]

    def marks(self) -> list[tuple[int, str, bool]]:
        return [
            (hour.open_ms, hour.equity, hour.complete)
            for hour in self.hours
            if hour.equity is not None and hour.complete is not None
        ]


def _read(records_path: Path, receipt: Receipt, cell: CellSpec) -> _Records:
    """Every ``hourly`` record and the one ``outcome`` record, reading the file to its end (so
    ``read_records`` checks the receipt's counts and final hash before anything is used), once
    the records are of ``cell``: the outcome record names it, with a well-formed ``window`` and
    ``data``, the first open mark, before any fill, is its capital, and the hours lie in the
    window, the first of them its first hour."""
    hours: list[_Hour] = []
    outcome: dict[str, object] | None = None
    for kind, record in read_records(records_path, receipt):
        if outcome is not None:
            raise ValueError(f"a {kind} record follows the outcome record")
        if kind == "hourly":
            hours.append(_hour(record, hours))
        elif kind == "outcome":
            outcome = record
    if outcome is None:
        raise ValueError("the records hold no outcome record")
    named = outcome.get("cell")
    if _first_difference(named, cell_record(cell), "cell") is not None:  # exact types
        label = named.get("id") if isinstance(named, dict) else named
        raise ValueError(f"the records are of the cell {label!r:.60}, not {cell.cell_id}")
    data = outcome.get("data")
    if data is not None and (
        not isinstance(data, dict)
        or set(data) != _DATA_KEYS
        or not all(isinstance(value, str) for value in data.values())
    ):
        raise ValueError("the outcome record's data must be null or its four pins as strings")
    window = _window(outcome.get("window"))
    if hours:
        first = hours[0]
        if first.equity is None or Decimal(first.equity) != Decimal(cell.capital):
            raise ValueError(
                f"the first open mark, {first.equity}, is not the capital of {cell.cell_id}"
            )
        if first.open_ms != window["start_ms"]:
            raise ValueError(
                f"the first hour, {first.open_ms}, is not the window's first, {window['start_ms']}"
            )
        if hours[-1].open_ms > window["end_ms"]:
            raise ValueError(
                f"the hour {hours[-1].open_ms} is after the window's last, {window['end_ms']}"
            )
    return _Records(tuple(hours), outcome, window)


def _window(value: object) -> dict[str, int]:
    """The outcome record's window: the opens of its first and last hour, in order."""
    if (
        not isinstance(value, dict)
        or set(value) != _WINDOW_KEYS
        or not all(
            type(item) is int and item >= 0 and item % HOUR_MS == 0 for item in value.values()
        )
        or value["start_ms"] > value["end_ms"]
    ):
        raise ValueError(
            "the outcome record's window must be its start_ms and end_ms, hour opens in order"
        )
    return {"start_ms": value["start_ms"], "end_ms": value["end_ms"]}


def _hour(record: Mapping[str, object], previous: Sequence[_Hour]) -> _Hour:
    """One hourly record, checked: the hour after the previous one, and an open mark on every
    hour but the last (only a stop before its open mark leaves an hour without one)."""
    open_ms = record.get("open_ms")
    if type(open_ms) is not int or open_ms % HOUR_MS:
        raise ValueError(f"hourly record: open_ms {open_ms!r:.40} is not an hour's open")
    if previous:
        last = previous[-1]
        if last.equity is None:
            raise ValueError(
                f"hourly record at {open_ms}: an hour without an open mark is not last"
            )
        if open_ms != last.open_ms + HOUR_MS:
            raise ValueError(f"hourly record at {open_ms}: not the hour after {last.open_ms}")
    equity, complete = record.get("open_equity"), record.get("complete")
    if equity is None and complete is None:
        mark: str | None = None
        flag: bool | None = None
    else:
        if type(complete) is not bool:
            raise ValueError(f"hourly record at {open_ms}: complete must be a boolean")
        mark = _text(equity, f"the open mark at {open_ms}")
        flag = complete
    residual = _decimal(record.get("equity_residual"), f"the equity residual at {open_ms}")
    return _Hour(open_ms, mark, flag, residual)


def _decimal(value: object, name: str) -> Decimal:
    """A Decimal string of the records: finite and spelled as ``str`` of its Decimal."""
    if type(value) is not str:
        raise ValueError(f"{name} must be a Decimal string, got {value!r:.40}")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{name} is not a Decimal: {value!r:.40}") from None
    if not number.is_finite() or str(number) != value:
        raise ValueError(f"{name} is not a finite Decimal as the records write it: {value!r:.40}")
    return number


def _text(value: object, name: str) -> str:
    """A Decimal string of the records, kept as it is spelled."""
    _decimal(value, name)
    return str(value)


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer or null, got {value!r:.40}")
    return value


def _optional_str(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string or null, got {value!r:.40}")
    return value


# ---- the summary ----------------------------------------------------------------------------


def build_summary(cell: CellSpec, result: CellResult, records_path: Path) -> dict[str, object]:
    """The cell's summary, from its records and its spec (module docstring); ``result`` is
    cross-checked against the records, and its receipt against ``receipt.json``."""
    if not isinstance(cell, CellSpec):
        raise ValueError(f"a CellSpec is required, got {cell!r:.60}")
    if not isinstance(result, CellResult):
        raise ValueError(f"a CellResult is required, got {result!r:.60}")
    path = Path(records_path)
    receipt_sha256 = _receipt_sha256(path, result.receipt)
    records = _read(path, result.receipt, cell)
    _cross_check(records, result)
    return _summary(cell, records, receipt_sha256)


def verify_summary(summary: dict[str, object], records_path: Path, receipt: Receipt) -> None:
    """Rebuild ``summary`` from the records (checked against ``receipt``, which must be the
    ``receipt.json`` next to them) and require equality; otherwise a ValueError names the first
    field that differs."""
    if not isinstance(summary, dict):
        raise ValueError("a summary must be a JSON object")
    cell = _summary_cell(summary)
    path = Path(records_path)
    expected = _summary(cell, _read(path, receipt, cell), _receipt_sha256(path, receipt))
    where = _first_difference(summary, expected, "")
    if where is not None:
        raise ValueError(f"summary field {where} does not match the cell's records")


def _receipt_sha256(records_path: Path, receipt: Receipt) -> str:
    """The SHA-256 of ``receipt.json`` next to the records, which must hold ``receipt``."""
    path = records_path.parent / RECEIPT_FILE
    if read_receipt(path) != receipt:
        raise ValueError(f"{path.name} next to the records is not the receipt given")
    return _digest(path.read_bytes())


def _summary_cell(summary: Mapping[str, object]) -> CellSpec:
    cell = summary.get("cell")
    if not isinstance(cell, dict) or set(cell) != _CELL_KEYS:
        raise ValueError("summary field cell must hold exactly id, arm, capital and cost_multiple")
    try:
        spec = CellSpec(cell["arm"], cell["capital"], cell["cost_multiple"])
    except ValueError as exc:
        raise ValueError(f"summary field cell: {exc}") from None
    if cell["id"] != spec.cell_id:
        raise ValueError(f"summary field cell: id {cell['id']!r:.40} is not {spec.cell_id}")
    return spec


def _cross_check(records: _Records, result: CellResult) -> None:
    """The result must say what the records say."""
    outcome = records.outcome
    checks: list[tuple[str, object, object]] = [
        ("outcome", result.outcome, outcome.get("outcome")),
        ("reason", result.reason, outcome.get("reason")),
        ("stop_ms", result.stop_ms, outcome.get("stop_ms")),
    ]
    if outcome.get("outcome") in FULL_OUTCOMES:
        checks += [
            (
                "open_marks",
                [(ms, str(equity), flag) for ms, equity, flag in result.open_marks],
                records.marks(),
            ),
            ("final_equity", str(result.final_equity), outcome.get("final_equity")),
            ("equity_2025", _spelled(result.equity_2025), outcome.get("equity_2025")),
            (
                "final_after_close",
                _spelled(result.final_after_close),
                outcome.get("final_after_close"),
            ),
        ]
    for name, mine, theirs in checks:
        if mine != theirs:
            raise ValueError(f"the cell result's {name} does not match the records")


def _spelled(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _summary(cell: CellSpec, records: _Records, receipt_sha256: str) -> dict[str, object]:
    name = records.outcome.get("outcome")
    if name in FULL_OUTCOMES:
        return _full(cell, records, receipt_sha256)
    if name in FAILURE_OUTCOMES:
        return _failure(cell, records)
    raise ValueError(f"unknown outcome {name!r:.40}")


def _full(cell: CellSpec, records: _Records, receipt_sha256: str) -> dict[str, object]:
    """A full summary (module docstring), up to the stop for a stopped cell."""
    outcome = records.outcome
    name = str(outcome["outcome"])
    reason = _optional_str(outcome.get("reason"), "the outcome's reason")
    stop_ms = _optional_int(outcome.get("stop_ms"), "the outcome's stop_ms")
    if not records.hours:
        raise ValueError(f"a {name} cell has no hourly records")
    first_ms, last_ms = records.hours[0].open_ms, records.hours[-1].open_ms
    if name == OUTCOME_COMPLETE and (reason is not None or stop_ms is not None):
        raise ValueError("a complete cell has no reason and no stop")
    if name == LIQUIDATED and reason is not None:
        raise ValueError(f"a liquidation has no reason, got {reason!r:.40}")
    if name == LIMIT_UNRESTORABLE and reason not in LIMIT_REASONS:
        raise ValueError(f"{reason!r:.40} is not a reason of {LIMIT_UNRESTORABLE}")
    if name != OUTCOME_COMPLETE and stop_ms != last_ms:
        raise ValueError(f"the stop at {stop_ms} is not the last hour, {last_ms}")
    if name == OUTCOME_COMPLETE and last_ms != records.window["end_ms"]:
        raise ValueError(
            f"a complete cell ends at the window's last hour, {records.window['end_ms']}, "
            f"not {last_ms}"
        )
    marks = records.marks()
    if name == OUTCOME_COMPLETE and len(marks) != len(records.hours):
        raise ValueError("every hour of a complete cell has an open mark")
    if outcome.get("hours") != len(marks):
        raise ValueError(f"the outcome record's hours is not the {len(marks)} open marks")
    final_text = _text(outcome.get("final_equity"), "the final equity")
    final = Decimal(final_text)
    after = _optional_text(outcome.get("final_after_close"), "the equity after the close")
    if after != (final_text if name == OUTCOME_COMPLETE else None):
        raise ValueError("the equity after the close is the final equity, and null for a stop")
    by_ms = {ms: equity for ms, equity, _ in marks}
    equity_2025 = by_ms.get(EQUITY_2025_MS)
    if outcome.get("equity_2025") != equity_2025:
        raise ValueError("the outcome record's equity_2025 is not the 2025-01-01 open mark")
    end_ms = last_ms + HOUR_MS if name == OUTCOME_COMPLETE else last_ms
    ending = _Ending(first_ms, last_ms, by_ms, final_text, end_ms)
    initial = Decimal(cell.capital)
    with localcontext(CONTEXT):
        compounded = final / initial - 1
    drawdown = maximum_drawdown([Decimal(equity) for _, equity, _ in marks] + [final])
    residual = max((hour.residual.copy_abs() for hour in records.hours), default=Decimal(0))
    years = range(_year_of(first_ms), _year_of(last_ms) + 1)
    return {
        "format": SUMMARY_FORMAT,
        "cell": cell_record(cell),
        "window": dict(records.window),
        "data": records.outcome.get("data"),
        "outcome": name,
        "reason": reason,
        "stop_ms": stop_ms,
        "initial_equity": str(initial),
        "final_equity": final_text,
        "equity_2025": equity_2025,
        "final_after_close": after,
        "max_drawdown": str(drawdown),
        "compounded_return": str(compounded),
        "liquidations": 1 if name == LIQUIDATED else 0,
        "accounting_residual": str(residual),
        "receipt_sha256": receipt_sha256,
        "eras": [{"name": era, **ending.period(start, end)} for era, start, end in ERAS],
        "years": [
            {"year": number, **ending.period(_year_start(number), _year_start(number + 1))}
            for number in years
        ],
        "open_marks": [[ms, equity, flag] for ms, equity, flag in marks],
    }


@dataclass(frozen=True, slots=True)
class _Ending:
    """What the periods of one cell are measured on: its first and last simulated hours, its
    open marks by hour, and its final equity with the time it stands for."""

    first_ms: int
    last_ms: int
    marks: Mapping[int, str]
    final: str
    end_ms: int

    def period(self, start: int | None, end: int | None) -> dict[str, object]:
        """One era or year from ``start`` to ``end`` (None: the window's own bound), as the
        module docstring defines it."""
        first = self.first_ms if start is None else max(start, self.first_ms)
        if (end is not None and first >= end) or first not in self.marks:
            return dict.fromkeys(_PERIOD_KEYS)
        start_equity = self.marks[first]
        if end is not None and end in self.marks:
            end_ms, end_equity = end, self.marks[end]
        else:
            end_ms, end_equity = self.end_ms, self.final
        change: str | None = None
        if Decimal(start_equity) > 0:
            with localcontext(CONTEXT):
                change = str(Decimal(end_equity) / Decimal(start_equity) - 1)
        return {
            "start_ms": first,
            "end_ms": end_ms,
            "start_equity": start_equity,
            "end_equity": end_equity,
            "return": change,
        }


def _year_of(ms: int) -> int:
    return datetime.fromtimestamp(ms // 1000, UTC).year


def _year_start(year: int) -> int:
    return month_bounds_ms(f"{year:04d}-01")[0]


def _failure(cell: CellSpec, records: _Records) -> dict[str, object]:
    """A short failure summary: the failure's details and nothing else (module docstring)."""
    outcome = records.outcome
    name = str(outcome["outcome"])
    head: dict[str, object] = {
        "format": SUMMARY_FORMAT,
        "cell": cell_record(cell),
        "window": dict(records.window),
        "data": outcome.get("data"),
        "outcome": name,
    }
    if name == ACCOUNTING_FAILURE:
        identity = outcome.get("reason")
        hour_ms = outcome.get("stop_ms")
        values = outcome.get("values")
        if type(identity) is not str or type(hour_ms) is not int or not isinstance(values, dict):
            raise ValueError("an accounting failure needs its identity, hour and values")
        if identity not in ACCOUNTING_IDENTITIES:
            raise ValueError(f"{identity!r:.40} is not an accounting identity")
        if not records.hours or records.hours[-1].open_ms != hour_ms:
            raise ValueError(f"the accounting failure at {hour_ms} is not the last hour")
        return {**head, "identity": identity, "hour_ms": hour_ms, "values": values}
    kind, message = outcome.get("type"), outcome.get("message")
    if type(kind) is not str or type(message) is not str:
        raise ValueError("an engine error needs its exception's type and message")
    if outcome.get("reason") != f"{kind}: {message}":
        raise ValueError("the engine error's reason is not its type and message")
    hour_ms = _optional_int(outcome.get("hour_ms"), "the engine error's hour_ms")
    return {**head, "type": kind, "message": message, "hour_ms": hour_ms}


def _first_difference(actual: object, expected: object, where: str) -> str | None:
    """The path of the first value of ``actual`` that is not ``expected``, with exact types, in
    ``expected``'s order (a missing key, then an extra one), or None if they are equal."""
    if type(actual) is not type(expected):
        return where or "the summary"
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key, item in expected.items():
            inner = f"{where}.{key}" if where else str(key)
            if key not in actual:
                return inner
            found = _first_difference(actual[key], item, inner)
            if found is not None:
                return found
        extra = [key for key in actual if key not in expected]
        if extra:
            return f"{where}.{extra[0]}" if where else str(extra[0])
        return None
    if isinstance(expected, list) and isinstance(actual, list):
        for index, (mine, theirs) in enumerate(zip(actual, expected, strict=False)):
            found = _first_difference(mine, theirs, f"{where}[{index}]")
            if found is not None:
                return found
        if len(actual) != len(expected):
            return f"{where}[{min(len(actual), len(expected))}]"
        return None
    return None if actual == expected else where


# ---- the files ------------------------------------------------------------------------------


def write_cell_outputs(out_dir: Path, summary: dict[str, object], page: str) -> str:
    """Create ``summary.json`` (canonical JSON) and ``report.html`` in ``out_dir``, both
    exclusively: if either exists, nothing is written. Returns the SHA-256 of the summary's
    bytes."""
    if not isinstance(summary, dict) or summary.get("format") != SUMMARY_FORMAT:
        raise ValueError(f"a {SUMMARY_FORMAT} summary is required")
    if type(page) is not str:
        raise ValueError("the page must be a string")
    raw = _canonical(summary)
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    targets = (folder / SUMMARY_FILE, folder / PAGE_FILE)
    for target in targets:
        if target.exists():
            raise ValueError(f"{target} already exists; a cell's files are never replaced")
    for target, data in zip(targets, (raw, page.encode("utf-8")), strict=True):
        with target.open("xb") as handle:
            handle.write(data)
    return _digest(raw)


# ---- the page -------------------------------------------------------------------------------

# The page's Content-Security-Policy: nothing is fetched, only the inline style applies. The
# ``v3_as_built`` page imports it, with ``_STYLE``, rather than copying either.
_CSP = "default-src 'none'; style-src 'unsafe-inline'"
_STYLE = """
:root{color-scheme:light dark}
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;max-width:56rem;
margin:2rem auto;padding:0 1rem;color:#1f2328;background:#ffffff}
h1{font-size:1.45rem;margin:0 0 .4rem}
h2{font-size:1.1rem;margin:1.8rem 0 .5rem}
table{border-collapse:collapse;width:100%}
th,td{padding:.3rem .6rem;border-bottom:1px solid #d0d7de;text-align:right;
font-variant-numeric:tabular-nums}
th:first-child,td:first-child{text-align:left}
.note{padding:.6rem .8rem;border-left:4px solid #9a6700;background:#fff8c5}
.muted{color:#59636e}
.wrap{overflow-x:auto}
svg{display:block;width:100%;height:auto;color:#0969da}
code{font-size:.85em;word-break:break-all}
@media (prefers-color-scheme:dark){body{color:#e6edf3;background:#0d1117}
th,td{border-color:#30363d}.note{background:#2b2111;border-color:#d29922}
.muted{color:#9198a1}svg{color:#4493f8}}
"""


def render_page(summary: dict[str, object]) -> str:
    """The cell's report page (module docstring): self-contained HTML with no script."""
    if not isinstance(summary, Mapping) or summary.get("format") != SUMMARY_FORMAT:
        raise ValueError(f"a {SUMMARY_FORMAT} summary is required")
    outcome = summary.get("outcome")
    cell = summary.get("cell")
    ident = cell.get("id") if isinstance(cell, Mapping) else None
    body = [f"<h1>V4 cell {_e(ident)}</h1>", f"<p>{_outcome_line(summary)}</p>"]
    body.append(f'<p class="note">{_e(_NOTE)}</p>')
    if outcome in FAILURE_OUTCOMES:
        body += _failure_sections(summary)
    elif outcome in FULL_OUTCOMES:
        body += _full_sections(summary)
    else:
        raise ValueError(f"unknown outcome {outcome!r:.40}")
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '<meta charset="utf-8">',
            f'<meta http-equiv="Content-Security-Policy" content="{_CSP}">',
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
            f"<title>V4 cell {_e(ident)}</title>",
            f"<style>{_STYLE}</style>",
            "</head>",
            "<body>",
            *body,
            "</body>",
            "</html>",
            "",
        ]
    )


def _outcome_line(summary: Mapping[str, object]) -> str:
    outcome = summary.get("outcome")
    line = f"Outcome: <strong>{_e(outcome)}</strong>"
    if outcome == OUTCOME_COMPLETE:
        return line + ". The window ran to its end and every position was closed."
    if outcome in (LIQUIDATED, LIMIT_UNRESTORABLE):
        if summary.get("reason") is not None:
            line += f" ({_e(summary.get('reason'))})"
        return line + (
            f" at {_e(_when(summary.get('stop_ms')))}. The figures run to the stop, "
            "and the stop's mark is the final equity."
        )
    if outcome == ACCOUNTING_FAILURE:
        return line + (
            f": the {_e(summary.get('identity'))} identity failed at "
            f"{_e(_when(summary.get('hour_ms')))}. The cell has no figures."
        )
    return line + ": the replay raised an exception. The cell has no figures."


def _failure_sections(summary: Mapping[str, object]) -> list[str]:
    rows: list[tuple[str, str]] = []
    for key, value in summary.items():
        if key in ("format", "cell", "outcome"):
            continue
        if key == "hour_ms":
            rows.append(("hour", _when(value)))
        elif key == "window" and isinstance(value, Mapping):
            rows += [(f"window: {inner}", _when(item)) for inner, item in value.items()]
        elif isinstance(value, Mapping):
            rows += [(f"{key}: {inner}", _plain(item)) for inner, item in value.items()]
        else:
            rows.append((key, _plain(value)))
    return ["<h2>Failure</h2>", _table(("Detail", "Value"), rows)]


def _full_sections(summary: Mapping[str, object]) -> list[str]:
    raw_marks = summary.get("open_marks")
    marks = raw_marks if isinstance(raw_marks, list) else []
    complete = sum(1 for row in marks if isinstance(row, list) and len(row) == 3 and row[2] is True)
    stopped = summary.get("outcome") != OUTCOME_COMPLETE
    after = summary.get("final_after_close")
    window = summary.get("window")
    first, last = (
        (window.get("start_ms"), window.get("end_ms"))
        if isinstance(window, Mapping)
        else (None, None)
    )
    headline = [
        ("Window (first and last hour)", f"{_when(first)} to {_when(last)}"),
        ("Initial equity", _usdt(summary.get("initial_equity"))),
        (
            "Final equity" + (" (the stop's mark)" if stopped else ""),
            _usdt(summary.get("final_equity")),
        ),
        ("Compounded return", _percent(summary.get("compounded_return"), signed=True)),
        ("Maximum drawdown", _percent(summary.get("max_drawdown"), signed=False)),
        ("Equity at 2025-01-01 00:00 UTC", _usdt(summary.get("equity_2025"))),
        (
            "Final equity after the window-end close",
            "n/a (no closing fill after a stop)" if after is None and stopped else _usdt(after),
        ),
        ("Hours with an open mark", f"{len(marks):,}"),
        ("Of which complete (every price source had its bar)", f"{complete:,}"),
        ("Liquidations", _plain(summary.get("liquidations"))),
        (
            "Accounting residual (largest |equity residual|)",
            _plain(summary.get("accounting_residual")) + " USDT",
        ),
        ("Receipt SHA-256", _plain(summary.get("receipt_sha256"))),
    ]
    sections = [
        "<h2>Headline</h2>",
        _table(("Figure", "Value"), headline),
        '<p class="muted">Rounded for reading; summary.json holds the exact values.</p>',
        "<h2>Equity path</h2>",
        _sparkline(summary, marks),
    ]
    head = ("From", "To", "Start equity", "End equity", "Return")
    for title, key, label in (("Eras", "eras", "name"), ("Years", "years", "year")):
        periods = summary.get(key)
        rows = [_period_row(item, label) for item in (periods if isinstance(periods, list) else [])]
        sections += [f"<h2>{title}</h2>", _table((title[:-1], *head), rows)]
    return sections


def _period_row(period: object, label: str) -> tuple[str, ...]:
    if not isinstance(period, Mapping):
        return (_plain(period), "", "", "", "", "")
    name = _plain(period.get(label))
    if period.get("start_ms") is None:
        return (name, "not reached", "", "", "", "n/a")
    return (
        name,
        _when(period.get("start_ms")),
        _when(period.get("end_ms")),
        _usdt(period.get("start_equity")),
        _usdt(period.get("end_equity")),
        _percent(period.get("return"), signed=True),
    )


def _sparkline(summary: Mapping[str, object], marks: Sequence[object]) -> str:
    """The open marks, then the final equity, as one inline SVG polyline of at most
    ``SPARKLINE_POINTS`` evenly spaced points (the first and the last always drawn)."""
    values: list[Decimal] = []
    for row in [*marks, [None, summary.get("final_equity")]]:
        number = _number(row[1]) if isinstance(row, list) and len(row) > 1 else None
        if number is not None:
            values.append(number)
    if not values:
        return '<p class="muted">No open marks.</p>'
    picked = [values[index] for index in _sample(len(values), SPARKLINE_POINTS)]
    if len(picked) == 1:
        picked *= 2
    low, high = min(values), max(values)
    width, height, pad = 800, 160, 6
    coordinates: list[str] = []
    with localcontext(CONTEXT):
        spread = high - low
        for index, value in enumerate(picked):
            x = Decimal(width * index) / (len(picked) - 1)
            y = Decimal(height) / 2
            if spread:
                y = pad + (high - value) * (height - 2 * pad) / spread
            coordinates.append(f"{_fixed(x)},{_fixed(y)}")
    head, tail = (marks[0], marks[-1]) if marks else (None, None)
    first = head[0] if isinstance(head, list) and head else None
    last = tail[0] if isinstance(tail, list) and tail else None
    caption = (
        f"{len(values) - 1:,} hourly open marks from {_when(first)} to {_when(last)}, then the "
        f"final equity; {len(picked):,} points drawn. Low {_usdt(str(low))}, "
        f"high {_usdt(str(high))}."
    )
    return "\n".join(
        [
            f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_e(caption)}">',
            f'<polyline points="{" ".join(coordinates)}" fill="none" stroke="currentColor" '
            'stroke-width="1.5" vector-effect="non-scaling-stroke"/>',
            "</svg>",
            f'<p class="muted">{_e(caption)}</p>',
        ]
    )


def _sample(count: int, limit: int) -> list[int]:
    """At most ``limit`` evenly spaced indices of ``count`` items, the first and last included."""
    if count <= limit:
        return list(range(count))
    return [step * (count - 1) // (limit - 1) for step in range(limit)]


def _table(head: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ['<div class="wrap"><table>', "<thead><tr>"]
    lines += [f"<th>{_e(cell)}</th>" for cell in head]
    lines.append("</tr></thead><tbody>")
    for row in rows:
        lines.append("<tr>" + "".join(f"<td>{_e(cell)}</td>" for cell in row) + "</tr>")
    lines.append("</tbody></table></div>")
    return "\n".join(lines)


def _e(value: object) -> str:
    """Every text value on the page is escaped, quotes included."""
    return escape("" if value is None else str(value), quote=True)


def _plain(value: object) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, list):
        return (
            "; ".join(
                " ".join(_plain(part) for part in item) if isinstance(item, list) else _plain(item)
                for item in value
            )
            or "none"
        )
    return str(value)


def _number(value: object) -> Decimal | None:
    if type(value) is not str:
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _usdt(value: object) -> str:
    number = _number(value)
    if number is None:
        return "n/a" if value is None else str(value)
    return f"{_rounded(number)} USDT"


def _percent(value: object, *, signed: bool) -> str:
    number = _number(value)
    if number is None:
        return "n/a" if value is None else str(value)
    with localcontext(CONTEXT):
        shown = _rounded(number * 100, signed=signed)
    return f"{shown}%"


def _rounded(number: Decimal, *, signed: bool = False) -> str:
    """Two decimals, half to even, with thousands separators (for reading only)."""
    with localcontext(CONTEXT):
        try:
            value = number.quantize(Decimal("0.01"))
        except InvalidOperation:
            return str(number)
        return format(value, "+,f" if signed else ",f")


def _fixed(number: Decimal) -> str:
    with localcontext(CONTEXT):
        return format(number.quantize(Decimal("0.1")), "f")


def _when(value: object) -> str:
    if type(value) is not int:
        return "n/a"
    return datetime.fromtimestamp(value // 1000, UTC).strftime("%Y-%m-%d %H:%M UTC")
