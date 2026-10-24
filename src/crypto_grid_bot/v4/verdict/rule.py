"""The pass rule (v4-d04) of step 4b: a path's numbers, the four conditions and the precedence.

Implements rulings V4 to V10. The verdict step (``scripts/v4_verdict.py``) loads the cells' facts
(``inputs.read_cell``) and, for the one or two cells a measure needs, their open marks
(``inputs.read_marks``), and calls the functions here. Nothing is read or written here.

**The spec's rule.** V4.0 passes only if ``v4_main`` meets all four, at both capitals:

1. its compounded return / maximum drawdown is greater than ``hold_universe``'s (normal costs);
2. its compounded return is greater than ``v3_as_built``'s over their common period (normal costs);
3. its net profit is positive at doubled costs;
4. its equity at the window's end is greater than its equity at 2025-01-01 00:00 UTC (normal costs).

**One common measure for every arm.** Compounded return and maximum drawdown in conditions 1 and 2
use each arm's equity marked at the common hourly boundaries, so the hours missing from any source
are skipped for all arms alike.

* **V4, common boundaries.** The common boundaries of two arms are the hours at which both have an
  open mark flagged ``complete`` (``common_boundaries``). If none remain, the condition cannot be
  computed, and the verdict is incomplete.
* **V5, a path's numbers** (``path_measure``). Compounded return is ``last / first - 1``, and
  maximum drawdown is ``trend.metrics.maximum_drawdown(path)``, both under ``CONTEXT``. If the first
  equity is not positive, the measure cannot be computed. Return over drawdown uses the
  zero-drawdown rule (``ratio``): with a drawdown of 0 it is ``Decimal("Infinity")`` when the return
  is positive and ``Decimal(0)`` otherwise. "Greater" is the plain Decimal ``>``, so +infinity is
  greater than every finite value and not greater than itself.
* **V6, a liquidated ``v3_as_built`` in condition 2** (``after_stop``). After its stop the arm holds
  nothing, so at every hour after ``stop_ms`` up to 2024-12-31 23:00 its equity is its
  ``final_equity`` and its mark counts as complete. Only ``v4_main``'s marks then decide which hours
  are common. The inputs do not enforce a stop hour on a stopped outcome, so a stopped cell with no
  ``stop_ms`` (or no ``final_equity``) is incomputable here, never a crash.
* **V7, condition 1** (``condition_1``). The path is each arm's equity at the common boundaries of
  ``v4_main-<c>-1x`` and ``hold_universe-<c>-1x``, then each arm's ``final_after_close`` as the last
  point. Both must be ``complete``; any other outcome of ``hold_universe`` is incomplete.
* **V8, condition 2** (``condition_2``). The common boundaries count from ``V3_START_MS``
  (2021-07-01 00:00) to ``V3_END_MS - HOUR_MS`` (2024-12-31 23:00), both included. There is no
  final point: neither arm has a synthetic close there.
* **V9, conditions 3 and 4** (``condition_3``, ``condition_4``). Condition 3 is
  ``final_after_close > initial_equity`` for ``v4_main-<c>-2x``. Condition 4 is
  ``final_after_close > equity_2025`` for ``v4_main-<c>-1x``; a null ``equity_2025`` cannot be
  computed, so the verdict is incomplete.
* **V10, precedence** (``decide``), in this order. First **fail** if an accepted ``v4_main``
  summary, at either capital and either cost, is ``liquidated``, ``limit_unrestorable`` or
  ``accounting_failure``. Otherwise **incomplete** if one of the 8 required cells is missing,
  refused or ``engine_error``, if a re-run or another dispatch of the same registration was found,
  or if a condition cannot be computed. Otherwise **pass** if all 8 checks hold (4 conditions x 2
  capitals), else **fail**.

**Decisions of this module** (beyond the rulings, each cheap):

* A ``PathMeasure`` counts the common boundaries only: ``hours`` is their number and ``last_ms`` the
  last of them, so condition 1's final point (which has no hour) is in ``end_equity`` and not in
  ``hours``.
* ``measure_against_hold`` and ``measure_against_v3`` are the measures of conditions 1 and 2 for any
  two cells of one capital and one cost multiple. V11 reports every non-v3 arm that way, so the
  verdict step uses them, and ``condition_1`` and ``condition_2`` are those plus the comparison.
  Cells of unlike capitals or costs are a caller's ``ValueError``, not an incomputable check.
* A non-v3 arm that did not complete has no path to the window's end, so it is incomputable in
  conditions 1 and 2. (For ``v4_main`` the precedence has already failed the verdict.)
* ``decide`` returns all 8 checks, ordered by capital then condition. A check the caller did not
  supply is filled in as incomputable, and says so. Its ``reasons`` list every finding, in this
  order: the stopped ``v4_main`` cells, the required cells that are missing or refused, those that
  ended in an engine error, a re-run, another dispatch, the conditions that cannot be computed, and
  the conditions that do not hold. The outcome is the precedence's; the reasons are everything the
  owner needs to read beside it.
* ``Check.note``, ``Incomputable`` messages and ``Verdict.reasons`` are words and cell ids only:
  never an equity, a return or a quoted dispatch (public logs carry no figures).

Every division and subtraction runs under ``CONTEXT``. No live execution; no API keys.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Literal

from crypto_grid_bot.trend.metrics import maximum_drawdown
from crypto_grid_bot.v4.engine.market import HOUR_MS
from crypto_grid_bot.v4.engine.numbers import CONTEXT
from crypto_grid_bot.v4.engine.run import (
    ACCOUNTING_FAILURE,
    ENGINE_ERROR,
    LIMIT_UNRESTORABLE,
    LIQUIDATED,
    OUTCOME_COMPLETE,
)
from crypto_grid_bot.v4.engine.v3_as_built import V3_END_MS, V3_START_MS
from crypto_grid_bot.v4.verdict.inputs import CellFacts

Mark = tuple[int, Decimal, bool]  # (hour open in ms, equity, complete), as inputs.read_marks
INFINITY = Decimal("Infinity")
STOP_FAILS = frozenset({LIQUIDATED, LIMIT_UNRESTORABLE, ACCOUNTING_FAILURE})
CAPITALS_JUDGED = (1000, 10000)
REQUIRED = (
    "v4_main-1000-1x",
    "v4_main-1000-2x",
    "v4_main-10000-1x",
    "v4_main-10000-2x",
    "hold_universe-1000-1x",
    "hold_universe-10000-1x",
    "v3_as_built-1000-1x",
    "v3_as_built-10000-1x",
)
MAIN_ARM = "v4_main"
CONDITION_LABELS: Mapping[int, str] = {
    1: "return over drawdown against hold_universe",
    2: "return against v3_as_built over their common period",
    3: "net profit at doubled costs",
    4: "equity at the window's end against 2025-01-01",
}
# The 8 checks of the rule, in the order a verdict lists them.
_KEYS = tuple((capital, condition) for capital in CAPITALS_JUDGED for condition in (1, 2, 3, 4))


class Incomputable(ValueError):
    """A measure or condition that cannot be computed. The message says why in words and never
    carries a value: the verdict is incomplete."""


@dataclass(frozen=True, slots=True)
class PathMeasure:
    """One arm's path over the common boundaries: their number (``hours``), the first and last of
    them, the path's first and last equity (the last is the final after the close in condition 1),
    its compounded return, its maximum drawdown and their ratio."""

    hours: int
    first_ms: int
    last_ms: int
    start_equity: Decimal
    end_equity: Decimal
    compounded_return: Decimal
    max_drawdown: Decimal
    ratio: Decimal


@dataclass(frozen=True, slots=True)
class Check:
    """One condition at one capital. ``holds`` is None when it cannot be computed (or a needed cell
    is missing), and ``note`` says why in words. ``main`` and ``other`` are the two sides: two
    ``PathMeasure`` for conditions 1 and 2, two Decimals for 3 and 4, None when ``holds`` is."""

    condition: int
    capital: int
    holds: bool | None
    main: PathMeasure | Decimal | None
    other: PathMeasure | Decimal | None
    note: str | None


@dataclass(frozen=True, slots=True)
class Verdict:
    outcome: Literal["pass", "fail", "incomplete"]
    reasons: tuple[str, ...]
    checks: tuple[Check, ...]


# ---- V4, V5: the measures -------------------------------------------------------------------


def ratio(compounded: Decimal, drawdown: Decimal) -> Decimal:
    """Return over drawdown, with V5's zero-drawdown rule: with a drawdown of 0 it is +infinity
    when the return is positive and 0 otherwise."""
    if not (compounded.is_finite() and drawdown.is_finite()) or drawdown < 0:
        raise ValueError("a ratio needs a finite return and a finite drawdown that is not negative")
    if drawdown == 0:
        return INFINITY if compounded > 0 else Decimal(0)
    with localcontext(CONTEXT):
        return compounded / drawdown


def common_boundaries(
    left: Sequence[Mark],
    right: Sequence[Mark],
    *,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> tuple[int, ...]:
    """The hours at which both arms have an open mark flagged complete, in order, from
    ``start_ms`` to ``end_ms`` (both included; open on a side left None)."""
    shared = {hour for hour, _, complete in left if complete}
    shared.intersection_update(hour for hour, _, complete in right if complete)
    return tuple(
        sorted(
            hour
            for hour in shared
            if (start_ms is None or hour >= start_ms) and (end_ms is None or hour <= end_ms)
        )
    )


def after_stop(
    marks: Sequence[Mark], stop_ms: int, final_equity: Decimal, until_ms: int
) -> list[Mark]:
    """V6: the marks of a stopped arm that holds nothing after its stop. The marks up to
    ``stop_ms`` stay (the stop hour's open is the last real mark); every hour after it up to
    ``until_ms`` is its ``final_equity``, flagged complete."""
    path = [mark for mark in marks if mark[0] <= stop_ms]
    first = (stop_ms // HOUR_MS + 1) * HOUR_MS
    path.extend((hour, final_equity, True) for hour in range(first, until_ms + 1, HOUR_MS))
    return path


def path_measure(marks: Sequence[Mark], hours: Sequence[int], final: Decimal | None) -> PathMeasure:
    """V5: the path of ``marks`` at ``hours`` (strictly increasing, each a complete mark), then
    ``final`` as the last point if there is one."""
    if not hours:
        raise Incomputable("the path has no common hour")
    if any(later <= earlier for earlier, later in zip(hours, hours[1:], strict=False)):
        raise ValueError("a path's hours must strictly increase")
    wanted = set(hours)
    found = {hour: equity for hour, equity, complete in marks if complete and hour in wanted}
    if len(found) != len(wanted):
        raise Incomputable("a boundary of the path has no complete mark")
    path = [found[hour] for hour in hours]
    if final is not None:
        path.append(final)
    if not all(equity.is_finite() for equity in path):
        raise Incomputable("an equity of the path is not finite")
    first, last = path[0], path[-1]
    if first <= 0:
        raise Incomputable("the path's first equity is not positive")
    with localcontext(CONTEXT):
        compounded = last / first - 1
    drawdown = maximum_drawdown(path)
    return PathMeasure(
        hours=len(hours),
        first_ms=hours[0],
        last_ms=hours[-1],
        start_equity=first,
        end_equity=last,
        compounded_return=compounded,
        max_drawdown=drawdown,
        ratio=ratio(compounded, drawdown),
    )


def _pair(left: CellFacts, right: CellFacts) -> None:
    if (left.capital, left.cost_multiple) != (right.capital, right.cost_multiple):
        raise ValueError("the two cells differ in capital or in cost multiple")


def _closed(cell: CellFacts) -> Decimal:
    """The cell's equity after its window-end close, if it ran to the end of its window."""
    if cell.outcome != OUTCOME_COMPLETE:
        raise Incomputable(f"{cell.arm} did not complete")
    if cell.final_after_close is None:
        raise Incomputable(f"{cell.arm} has no equity after its window-end close")
    return cell.final_after_close


def measure_against_hold(
    arm: CellFacts, arm_marks: Sequence[Mark], hold: CellFacts, hold_marks: Sequence[Mark]
) -> tuple[PathMeasure, PathMeasure]:
    """V7, condition 1's measure of two cells: each one's equity at their common boundaries, then
    its ``final_after_close``. Both must be complete."""
    _pair(arm, hold)
    arm_final, hold_final = _closed(arm), _closed(hold)
    hours = common_boundaries(arm_marks, hold_marks)
    if not hours:
        raise Incomputable("the two arms have no common hour with complete marks")
    return path_measure(arm_marks, hours, arm_final), path_measure(hold_marks, hours, hold_final)


def _v3_path(v3: CellFacts, marks: Sequence[Mark]) -> Sequence[Mark]:
    """The marks condition 2 reads for ``v3_as_built``: its own when it completed, V6's when it
    was liquidated."""
    if v3.outcome == OUTCOME_COMPLETE:
        return marks
    if v3.outcome == LIQUIDATED:
        if v3.stop_ms is None or v3.final_equity is None:
            raise Incomputable(f"{v3.arm} was liquidated but has no stop hour or final equity")
        return after_stop(marks, v3.stop_ms, v3.final_equity, V3_END_MS - HOUR_MS)
    raise Incomputable(f"{v3.arm} left no path: it ended in {v3.outcome}")


def measure_against_v3(
    arm: CellFacts, arm_marks: Sequence[Mark], v3: CellFacts, v3_marks: Sequence[Mark]
) -> tuple[PathMeasure, PathMeasure]:
    """V6 and V8, condition 2's measure of two cells: each one's equity at the common boundaries
    from ``V3_START_MS`` to ``V3_END_MS - HOUR_MS``, both included, with no final point."""
    _pair(arm, v3)
    if arm.outcome != OUTCOME_COMPLETE:
        raise Incomputable(f"{arm.arm} did not run to the end of v3's period")
    other = _v3_path(v3, v3_marks)
    hours = common_boundaries(arm_marks, other, start_ms=V3_START_MS, end_ms=V3_END_MS - HOUR_MS)
    if not hours:
        raise Incomputable("the two arms have no common hour with complete marks in v3's period")
    return path_measure(arm_marks, hours, None), path_measure(other, hours, None)


# ---- V7 to V9: the four conditions ----------------------------------------------------------


def _unknown(condition: int, capital: int, why: Incomputable | str) -> Check:
    return Check(condition, capital, None, None, None, str(why))


def condition_1(
    main: CellFacts, main_marks: Sequence[Mark], hold: CellFacts, hold_marks: Sequence[Mark]
) -> Check:
    """Compounded return / maximum drawdown is greater than ``hold_universe``'s (V7)."""
    try:
        mine, theirs = measure_against_hold(main, main_marks, hold, hold_marks)
    except Incomputable as why:
        return _unknown(1, main.capital, why)
    return Check(1, main.capital, mine.ratio > theirs.ratio, mine, theirs, None)


def condition_2(
    main: CellFacts, main_marks: Sequence[Mark], v3: CellFacts, v3_marks: Sequence[Mark]
) -> Check:
    """Compounded return is greater than ``v3_as_built``'s over their common period (V6, V8)."""
    try:
        mine, theirs = measure_against_v3(main, main_marks, v3, v3_marks)
    except Incomputable as why:
        return _unknown(2, main.capital, why)
    return Check(
        2, main.capital, mine.compounded_return > theirs.compounded_return, mine, theirs, None
    )


def condition_3(main_2x: CellFacts) -> Check:
    """Net profit is positive at doubled costs: ``final_after_close > initial_equity`` (V9)."""
    if main_2x.cost_multiple != 2:
        raise ValueError("condition 3 is judged at doubled costs")
    try:
        final = _closed(main_2x)
    except Incomputable as why:
        return _unknown(3, main_2x.capital, why)
    initial = main_2x.initial_equity
    return Check(3, main_2x.capital, final > initial, final, initial, None)


def condition_4(main_1x: CellFacts) -> Check:
    """Equity at the window's end is greater than at 2025-01-01 00:00: ``final_after_close >
    equity_2025`` (V9). A null ``equity_2025`` cannot be computed."""
    if main_1x.cost_multiple != 1:
        raise ValueError("condition 4 is judged at normal costs")
    try:
        final = _closed(main_1x)
    except Incomputable as why:
        return _unknown(4, main_1x.capital, why)
    if main_1x.equity_2025 is None:
        return _unknown(4, main_1x.capital, "the cell has no equity at 2025-01-01 00:00")
    return Check(4, main_1x.capital, final > main_1x.equity_2025, final, main_1x.equity_2025, None)


# ---- V10: the precedence --------------------------------------------------------------------


def _by_key(checks: Sequence[Check]) -> dict[tuple[int, int], Check]:
    """The checks keyed by (capital, condition); anything but one of the rule's 8 is a caller's
    error."""
    found: dict[tuple[int, int], Check] = {}
    for check in checks:
        key = (check.capital, check.condition)
        if key not in _KEYS:
            raise ValueError("a check is not one of the rule's four conditions at a judged capital")
        if key in found:
            raise ValueError("two checks are of the same condition at the same capital")
        found[key] = check
    return found


def _label(check: Check) -> str:
    label = CONDITION_LABELS[check.condition]
    return f"condition {check.condition} ({label}) at capital {check.capital}"


def _absent(capital: int, condition: int) -> Check:
    return Check(condition, capital, None, None, None, "not computed: a required cell is missing")


def decide(
    accepted: Mapping[str, CellFacts],
    checks: Sequence[Check],
    *,
    missing: Collection[str],
    reruns: Collection[str],
    dispatches: Collection[str],
) -> Verdict:
    """V10. ``accepted`` is the accepted cells by id; ``missing`` the cells that are missing or
    refused (only the 8 required ones count); ``reruns`` and ``dispatches`` what was found of
    another attempt or another dispatch of the same registration (any at all is incomplete);
    ``checks`` the conditions computed so far (a check not supplied counts as incomputable)."""
    found = _by_key(checks)
    ordered = tuple(found.get(key) or _absent(*key) for key in _KEYS)

    stops = sorted(
        (cell for cell in accepted.values() if cell.arm == MAIN_ARM and cell.outcome in STOP_FAILS),
        key=lambda cell: cell.cell_id,
    )
    lost = set(missing)
    gone = [cell for cell in REQUIRED if cell not in accepted or cell in lost]
    errored = [
        cell for cell in REQUIRED if cell not in gone and accepted[cell].outcome == ENGINE_ERROR
    ]
    unknown = [check for check in ordered if check.holds is None]
    failed = [check for check in ordered if check.holds is False]

    reasons = [f"a v4_main cell stopped: {cell.cell_id} is {cell.outcome}" for cell in stops]
    reasons += [f"required cell {cell} is missing or refused" for cell in gone]
    reasons += [f"required cell {cell} ended in an engine error" for cell in errored]
    if reruns:
        reasons.append("a re-run of a cell was found")
    if dispatches:
        reasons.append("another dispatch of the same registration was found")
    for check in unknown:
        reasons.append(
            f"{_label(check)} cannot be computed" + (f": {check.note}" if check.note else "")
        )
    reasons += [f"{_label(check)} does not hold" for check in failed]

    outcome: Literal["pass", "fail", "incomplete"]
    if stops:
        outcome = "fail"
    elif gone or errored or reruns or dispatches or unknown:
        outcome = "incomplete"
    elif failed:
        outcome = "fail"
    else:
        outcome = "pass"
    return Verdict(outcome, tuple(reasons), ordered)
