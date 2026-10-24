"""Hand-built V4 summaries for the verdict's tests (step 4b, tasks 2, 4 and 7).

The verdict step reads ``summary.json`` and ``receipt.json`` only, so a test of it needs summaries
that ``verdict.inputs.read_cell`` accepts, and the means to alter one cell at a time. These are
written the way the engine writes them (canonical JSON, a receipt whose digest the summary names,
the eras and years of ``summary.py``'s own period rules) but from hand-built marks, so no replay
runs. Nothing here touches the network or a real pack.

* ``expected_for(cells=None, mode=..., hours=50, ...)``: the expected document (``Expected``) the
  summaries match: the 48 cells in ``all_cells()`` order (44, no v3, for ``timing``), one window,
  one set of data pins and the two v3 pins (None for ``timing``). ``write_expected`` writes it
  as the canonical file ``read_expected`` reads.
* ``write_summary(root, cell_id, outcome=..., marks=..., ...)``: one folder
  ``v4-summary-<cell>-attempt-<n>/`` with a valid ``receipt.json`` and a ``summary.json`` of the
  arm's format and the outcome's keys. The three figures the caller owns are the open ``marks``
  (``(hour_ms, equity, complete)``, equities as Decimal strings, valid ones: the built figures
  are computed from them), ``final_after_close`` and ``equity_2025``. Every other field has a
  default (a stop's ``stop_ms`` is its last mark's hour, ``final_equity`` is ``final_after_close``
  or the last mark's equity, a failure's details are fixed words) and ``**extra`` replaces any
  top-level field of the built document; ``DROP`` removes one. A failure summary ignores
  the three figures. To spoil a summary in a way the builder cannot (a bad number, a bad mark),
  write it and then ``edit_summary`` or ``store_summary`` it.
* ``full_set(root, hours=50, mode=..., overrides=None, omit=())``: every cell of ``expected_for``
  written with the standard cell (below); ``overrides`` maps a cell id to ``write_summary``
  keywords that replace the standard ones, and ``omit`` lists the cells not written.

**The standard cell** has ``hours`` complete hourly marks from ``START_MS`` (V3's first hour), then
a final equity after the close, and for a V4 or hold arm an ``equity_2025`` halfway along its
path. The paths are exact and rise, so a hand-built set has a known shape: the V4 arms rise
without a drawdown (``v4_main`` fastest, at 1x faster than at 2x), the hold arms rise slower with
a 3 % dip, and ``v3_as_built`` rises slowest with the same dip, with no ``equity_2025`` and no
``final_after_close`` (a v3 cell has neither). So ``v4_main`` beats ``hold_universe`` and
``v3_as_built`` on every measure and the standard set passes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from crypto_grid_bot.combined.artifacts import _canonical
from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.v4.engine.arms import ARMS, CellSpec
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.records import Receipt, write_receipt
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    CEILING,
    ENGINE_ERROR,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
    OUTCOME_COMPLETE,
    RECEIPT_FILE,
    cell_record,
)
from crypto_grid_bot.v4.engine.summary import (
    ERAS,
    SUMMARY_FILE,
    SUMMARY_FORMAT,
    _Ending,
    _year_of,
    _year_start,
)
from crypto_grid_bot.v4.engine.v3_as_built import (
    V3_ARM,
    V3_CAPITAL,
    V3_CAPITAL_ADAPTER,
    V3_END_MS,
    V3_START_MS,
    V3_SUMMARY_FORMAT,
    v3_window,
)
from crypto_grid_bot.v4.verdict.inputs import Expected, expected_cells, expected_record

START_MS = V3_START_MS
HOURS = 50
DROP = object()  # in ``write_summary``'s ``**extra`` and ``edit_summary``: remove the field


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


DATA = {
    "config_sha256": sha("fixture config"),
    "end_month": "2025-03",
    "daily_sha256": sha("fixture daily pack"),
    "index_sha256": sha("fixture hourly index"),
}
V3_PACK = sha("fixture v3 pack")
PICKS = sha("fixture v3 picks")


def window_of(hours: int = HOURS) -> dict[str, int]:
    """The V4 and hold cells' window of a standard set: ``hours`` hours from ``START_MS``."""
    return {"start_ms": START_MS, "end_ms": START_MS + (hours - 1) * HOUR_MS}


def expected_for(
    cells: Sequence[str] | None = None,
    *,
    mode: str = "rehearsal",
    hours: int = HOURS,
    window: Mapping[str, int] | None = None,
    data: Mapping[str, str] | None = None,
    v3_pack_sha256: str | None = V3_PACK,
    picks_sha256: str | None = PICKS,
) -> Expected:
    """The expected document of the standard set; ``cells`` None means every cell of the mode."""
    timing = mode == "timing"
    chosen = tuple(cells) if cells is not None else expected_cells(mode)
    return Expected(
        mode,
        chosen,
        dict(window if window is not None else window_of(hours)),
        dict(data if data is not None else DATA),
        None if timing else v3_pack_sha256,
        None if timing else picks_sha256,
    )


def write_expected(path: Path, expected: Expected) -> Path:
    """The expected file: canonical JSON, as ``read_expected`` reads it."""
    path.write_bytes(_canonical(expected_record(expected)))
    return path


# ---- the standard cell ----------------------------------------------------------------------


def spec_of(cell_id: str) -> CellSpec:
    arm, capital, multiple = cell_id.rsplit("-", 2)
    return CellSpec(arm, int(capital), int(multiple.removesuffix("x")))


def text(value: Decimal) -> str:
    """A Decimal as a plain, normalised string: ``10030`` rather than ``10030.0000``."""
    return format(value.normalize(), "f")


def equity_at(cell_id: str, index: int, hours: int = HOURS) -> Decimal:
    """The standard cell's equity at its ``index``-th hour (module docstring)."""
    spec = spec_of(cell_id)
    family = ARMS[spec.arm].family
    capital = Decimal(spec.capital)
    place = list(ARMS).index(spec.arm)
    with localcontext(CONTEXT):
        if family == "v4":
            rate = Decimal("0.0020") if spec.cost_multiple == 1 else Decimal("0.0018")
            rate -= Decimal("0.00001") * place
            return capital + capital * rate * index
        rate = Decimal("0.0008") if family == "hold" else Decimal("0.0006")
        rate -= Decimal("0.00001") * place
        value = capital + capital * rate * index
        dip = range(hours // 5, hours // 5 + max(1, hours // 10))
        return value - capital * Decimal("0.03") if index in dip else value


def marks_for(cell_id: str, hours: int = HOURS) -> list[tuple[int, str, bool]]:
    """The standard cell's open marks: all complete, one an hour from ``START_MS``."""
    return [
        (START_MS + index * HOUR_MS, text(equity_at(cell_id, index, hours)), True)
        for index in range(hours)
    ]


def standard_cell(cell_id: str, hours: int = HOURS) -> dict[str, object]:
    """``write_summary``'s three figures for the standard cell."""
    marks: list[tuple[int, str, bool]] = marks_for(cell_id, hours)
    if ARMS[spec_of(cell_id).arm].family == "v3":
        return {"marks": marks, "final_after_close": None, "equity_2025": None}
    return {
        "marks": marks,
        "final_after_close": text(equity_at(cell_id, hours, hours)),
        "equity_2025": text(equity_at(cell_id, hours // 2, hours)),
    }


# ---- one summary ----------------------------------------------------------------------------


def write_summary(
    root: Path,
    cell_id: str,
    *,
    outcome: str = OUTCOME_COMPLETE,
    marks: Sequence[tuple[int, str, bool]] = (),
    final_after_close: str | None = None,
    equity_2025: str | None = None,
    expected: Expected,
    attempt: int = 1,
    **extra: object,
) -> Path:
    """Write ``root/v4-summary-<cell_id>-attempt-<attempt>/`` (module docstring) and return it."""
    spec = spec_of(cell_id)
    folder = root / f"v4-summary-{cell_id}-attempt-{attempt}"
    folder.mkdir(parents=True)
    kinds = {"hourly": len(marks), "outcome": 1} if marks else {"outcome": 1}
    receipt = Receipt(sha(f"records {cell_id}"), len(marks) + 1, sha(f"chain {cell_id}"), kinds)
    digest = write_receipt(folder / RECEIPT_FILE, receipt)
    if outcome in (ACCOUNTING_FAILURE, ENGINE_ERROR):
        document = _failure(spec, outcome, expected)
    else:
        document = _full(spec, outcome, list(marks), final_after_close, equity_2025, expected)
        document["receipt_sha256"] = digest
    store_summary(folder, _changed(document, extra))
    return folder


def _changed(document: dict[str, object], changes: Mapping[str, object]) -> dict[str, object]:
    changed = dict(document)
    for key, value in changes.items():
        if value is DROP:
            changed.pop(key, None)
        else:
            changed[key] = value
    return changed


def _head(spec: CellSpec, outcome: str, expected: Expected) -> dict[str, object]:
    v3 = spec.arm == V3_ARM
    return {
        "format": V3_SUMMARY_FORMAT if v3 else SUMMARY_FORMAT,
        "cell": cell_record(spec),
        "window": v3_window() if v3 else dict(expected.window),
        "data": (
            {"v3_pack_sha256": expected.v3_pack_sha256, "picks_sha256": expected.picks_sha256}
            if v3
            else dict(expected.data)
        ),
        "outcome": outcome,
    }


def _failure(spec: CellSpec, outcome: str, expected: Expected) -> dict[str, object]:
    head = _head(spec, outcome, expected)
    if outcome == ACCOUNTING_FAILURE:
        values = {"wallet_residual": "1E-40", "quantity_residuals": [], "equity_residual": "0"}
        return {**head, "identity": "wallet", "hour_ms": START_MS, "values": values}
    kind = "V3Stop" if spec.arm == V3_ARM else "RuntimeError"
    return {**head, "type": kind, "message": "injected", "hour_ms": None}


def _full(
    spec: CellSpec,
    outcome: str,
    marks: list[tuple[int, str, bool]],
    final_after_close: str | None,
    equity_2025: str | None,
    expected: Expected,
) -> dict[str, object]:
    v3 = spec.arm == V3_ARM
    complete = outcome == OUTCOME_COMPLETE
    head = _head(spec, outcome, expected)
    first = marks[0][0] if marks else (V3_START_MS if v3 else expected.window["start_ms"])
    last = marks[-1][0] if marks else first
    final_text = (
        final_after_close
        if final_after_close is not None
        else (marks[-1][1] if marks else str(spec.capital))
    )
    final, initial = Decimal(final_text), Decimal(spec.capital)
    with localcontext(CONTEXT):
        compounded = final / initial - 1
    drawdown = maximum_drawdown([Decimal(equity) for _, equity, _ in marks] + [final])
    end_ms = V3_END_MS if v3 and complete else (last + HOUR_MS if complete else last)
    ending = _Ending(first, last, {ms: equity for ms, equity, _ in marks}, final_text, end_ms)
    reason = CEILING if outcome == LIMIT_UNRESTORABLE else None
    document: dict[str, object] = {
        **head,
        "reason": reason,
        "stop_ms": None if complete else last,
        "initial_equity": str(initial),
        "final_equity": final_text,
        "equity_2025": equity_2025,
        "final_after_close": final_after_close,
        "max_drawdown": str(drawdown),
        "compounded_return": str(compounded),
        "liquidations": 1 if outcome == LIQUIDATED else 0,
        "accounting_residual": "0",
        "eras": [{"name": era, **ending.period(start, end)} for era, start, end in ERAS],
        "years": [
            {"year": year, **ending.period(_year_start(year), _year_start(year + 1))}
            for year in range(_year_of(first), _year_of(last) + 1)
        ],
        "open_marks": [[ms, equity, flag] for ms, equity, flag in marks],
    }
    if v3:
        document["disclosures"] = [V3_CAPITAL_ADAPTER] if spec.capital != V3_CAPITAL else []
    return document


# ---- altering a written summary -------------------------------------------------------------


def load_summary(folder: Path) -> dict[str, object]:
    document = json.loads((folder / SUMMARY_FILE).read_bytes())
    assert isinstance(document, dict)
    return document


def store_summary(folder: Path, document: Mapping[str, object]) -> None:
    """Write ``document`` as the folder's ``summary.json``, canonical, replacing what is there."""
    (folder / SUMMARY_FILE).write_bytes(_canonical(dict(document)))


def edit_summary(folder: Path, **changes: object) -> dict[str, object]:
    """Replace (or, with ``DROP``, remove) top-level fields of a written summary, keeping it
    canonical; the receipt is left as it is. Returns the new document."""
    document = _changed(load_summary(folder), changes)
    store_summary(folder, document)
    return document


# ---- a set ----------------------------------------------------------------------------------


def full_set(
    root: Path,
    hours: int = HOURS,
    *,
    mode: str = "rehearsal",
    overrides: Mapping[str, Mapping[str, object]] | None = None,
    omit: Collection[str] = (),
) -> Expected:
    """Write every cell of ``expected_for(mode=mode, hours=hours)`` under ``root`` and return
    that expected document (module docstring)."""
    expected = expected_for(mode=mode, hours=hours)
    for cell_id in expected.cells:
        if cell_id in omit:
            continue
        keywords: dict[str, Any] = {
            **standard_cell(cell_id, hours),
            **(overrides or {}).get(cell_id, {}),
        }
        write_summary(root, cell_id, expected=expected, **keywords)
    return expected
