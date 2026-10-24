"""V4 step 4b, task 3: the pass rule (``v4.verdict.rule``).

Pure arithmetic over ``CellFacts`` and open-mark lists built here, so nothing is read from disk and
nothing can reach the network. The tests follow the module: the zero-drawdown ratio (V5), the
common boundaries (V4), a path's numbers (V5), the four conditions (V6 to V9), then the precedence
(V10). Every value is an exact Decimal.

One example of the task's brief is changed on purpose, and the docstring of
``test_condition_1_ends_with_the_final_after_close`` says why: the brief's hold path (100, 101, 102
and a final 103) never falls, so by V5 its ratio is +infinity and nothing finite beats it. The test
keeps the brief's main path and final, asserts the False the rule gives against that hold path, and
asserts the brief's True against the same hold path given a dip.
"""

from __future__ import annotations

import contextlib
import itertools
import re
from collections.abc import Iterator
from decimal import Decimal, localcontext

import pytest

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
from crypto_grid_bot.v4.verdict.inputs import CellFacts, expected_cells
from crypto_grid_bot.v4.verdict.rule import (
    CAPITALS_JUDGED,
    INFINITY,
    MAIN_ARM,
    STOP_FAILS,
    Check,
    Incomputable,
    Mark,
    PathMeasure,
    Verdict,
    after_stop,
    common_boundaries,
    condition_1,
    condition_2,
    condition_3,
    condition_4,
    decide,
    path_measure,
    ratio,
    skipped_against_v3,
    skipped_hours,
)

D = Decimal
V3_LAST = V3_END_MS - HOUR_MS
SECRET = D("8675309.4271")  # an equity that must never show in a note or a reason
# Condition 1's window (a required keyword): the hours 0 to 3, those of most tests' marks. The
# tests of its skipped hours give their own.
WINDOW = (0, 3 * HOUR_MS)
# The cells of a run (owner decision v4-d25: every one counts): the 48 of a registered run and a
# rehearsal, and the 44 of a timing run (no v3 cell).
RUN = expected_cells("registered")
TIMING = expected_cells("timing")
# The 8 cells the four conditions read.
PASS_RULE_CELLS = (
    "v4_main-1000-1x",
    "v4_main-1000-2x",
    "v4_main-10000-1x",
    "v4_main-10000-2x",
    "hold_universe-1000-1x",
    "hold_universe-10000-1x",
    "v3_as_built-1000-1x",
    "v3_as_built-10000-1x",
)
REPORTED = [cell for cell in RUN if cell not in PASS_RULE_CELLS]  # the 40 that decide nothing
OTHER_ARMS = [cell for cell in RUN if not cell.startswith(f"{MAIN_ARM}-")]  # all but v4_main's


@contextlib.contextmanager
def callers_error() -> Iterator[None]:
    """A ``ValueError`` that is the caller's mistake, not an ``Incomputable`` (the data's)."""
    with pytest.raises(ValueError) as caught:
        yield
    assert not isinstance(caught.value, Incomputable)


def marks(equities: list[int | str], *, start: int = 0, skip: tuple[int, ...] = ()) -> list[Mark]:
    """Open marks at consecutive hours from ``start`` (an hour open in ms). The indexes in ``skip``
    are flagged incomplete."""
    return [
        (start + index * HOUR_MS, D(equity), index not in skip)
        for index, equity in enumerate(equities)
    ]


def facts(
    arm: str = "v4_main",
    capital: int = 1000,
    cost: int = 1,
    outcome: str = OUTCOME_COMPLETE,
    **changes: object,
) -> CellFacts:
    """The facts of one cell. A complete cell ends where it began, a stop has a stop hour and no
    equity after the close, a failure summary has no figures at all."""
    cell_id = f"{arm}-{capital}-{cost}x"
    failed = outcome in (ACCOUNTING_FAILURE, ENGINE_ERROR)
    stopped = outcome in (LIQUIDATED, LIMIT_UNRESTORABLE)
    figure = None if failed else D(capital)
    base: dict[str, object] = {
        "folder": f"v4-summary-{cell_id}-attempt-1",
        "cell_id": cell_id,
        "arm": arm,
        "capital": capital,
        "cost_multiple": cost,
        "outcome": outcome,
        "reason": None,
        "stop_ms": 5 * HOUR_MS if stopped else None,
        "initial_equity": D(capital),
        "final_equity": figure,
        "equity_2025": figure,
        "final_after_close": D(capital) if outcome == OUTCOME_COMPLETE else None,
        "compounded_return": None if failed else D(0),
        "max_drawdown": None if failed else D(0),
        "eras": (),
        "years": (),
        "disclosures": (),
        "summary_sha256": "0" * 64,
        "marks": 0 if failed else 3,
    }
    return CellFacts(**{**base, **changes})  # type: ignore[arg-type]


def holds(condition: int, capital: int, value: bool | None = True) -> Check:
    return Check(condition, capital, value, None, None, None if value is not None else "n/a")


def all_checks(value: bool | None = True) -> list[Check]:
    return [holds(n, capital, value) for capital in CAPITALS_JUDGED for n in (1, 2, 3, 4)]


def run_cells(cells: tuple[str, ...] = RUN, **outcomes: str) -> dict[str, CellFacts]:
    """The run's cells (``cells``: all 48 by default), complete, each ``arm_capital_cost``
    outcome overridable by its cell id with ``-`` written ``_`` (``v4_main_1000_2x=LIQUIDATED``)."""
    found = {}
    for cell_id in cells:
        arm, capital, cost = cell_id.rsplit("-", 2)
        outcome = outcomes.get(cell_id.replace("-", "_"), OUTCOME_COMPLETE)
        found[cell_id] = facts(arm, int(capital), int(cost.removesuffix("x")), outcome)
    return found


def with_outcome(cell: str, outcome: str) -> dict[str, CellFacts]:
    """The run's 48 cells, complete but ``cell``, which ends in ``outcome``."""
    return run_cells(**{cell.replace("-", "_"): outcome})


def decided(
    accepted: dict[str, CellFacts] | None = None,
    checks: list[Check] | None = None,
    *,
    expected: tuple[str, ...] = RUN,
    missing: tuple[str, ...] = (),
    reruns: tuple[str, ...] = (),
    dispatches: tuple[str, ...] = (),
) -> Verdict:
    return decide(
        run_cells(expected) if accepted is None else accepted,
        all_checks() if checks is None else checks,
        expected=expected,
        missing=missing,
        reruns=reruns,
        dispatches=dispatches,
    )


# ---- V5: the zero-drawdown rule -------------------------------------------------------------


def test_ratio_zero_drawdown_rule() -> None:
    assert ratio(D("0.5"), D(0)) == INFINITY
    assert ratio(D(0), D(0)) == 0
    assert ratio(D("-0.1"), D(0)) == 0
    assert ratio(D("0.5"), D("0.25")) == 2
    assert D("1E+50") < INFINITY
    assert not INFINITY > INFINITY
    # exact Decimal division under CONTEXT, not float
    with localcontext(CONTEXT):
        assert ratio(D(1), D(3)) == D(1) / D(3)


def test_ratio_refuses_a_negative_drawdown_and_non_finite_input() -> None:
    for compounded, drawdown in [(D(1), D("-0.1")), (D("NaN"), D(1)), (D(1), D("Infinity"))]:
        with callers_error():
            ratio(compounded, drawdown)


def test_infinity_is_not_greater_than_itself() -> None:
    """Two paths that only rise have no drawdown and a positive return: both are +infinity, and
    +infinity is not greater than itself."""
    main = facts(final_after_close=D(106))
    hold = facts("hold_universe", final_after_close=D(104))
    check = condition_1(main, marks([100, 102, 104]), hold, marks([100, 101, 102]), window=WINDOW)
    assert isinstance(check.main, PathMeasure) and isinstance(check.other, PathMeasure)
    assert check.main.ratio == INFINITY and check.other.ratio == INFINITY
    assert check.holds is False


# ---- V4: the common boundaries --------------------------------------------------------------


def test_common_boundaries_skip_an_hour_incomplete_on_either_side() -> None:
    left = marks([1, 2, 3, 4, 5], skip=(1,))
    right = marks([1, 2, 3, 4, 5], skip=(3,))
    assert common_boundaries(left, right) == (0, 2 * HOUR_MS, 4 * HOUR_MS)
    # an hour only one side has is not common: right has hours 1 to 3, left is incomplete at 1
    assert common_boundaries(left, marks([1, 2, 3], start=HOUR_MS)) == (2 * HOUR_MS, 3 * HOUR_MS)
    assert common_boundaries(left, marks([1, 2], start=3 * HOUR_MS)) == (3 * HOUR_MS, 4 * HOUR_MS)
    assert common_boundaries(left, []) == ()
    assert common_boundaries([], right) == ()


def test_common_boundaries_range_includes_both_ends() -> None:
    both = marks([1, 2, 3, 4, 5])
    assert common_boundaries(both, both, start_ms=HOUR_MS, end_ms=3 * HOUR_MS) == (
        HOUR_MS,
        2 * HOUR_MS,
        3 * HOUR_MS,
    )
    assert common_boundaries(both, both, start_ms=3 * HOUR_MS) == (3 * HOUR_MS, 4 * HOUR_MS)
    assert common_boundaries(both, both, end_ms=0) == (0,)
    assert common_boundaries(both, both, start_ms=9 * HOUR_MS) == ()


# ---- V5: a path's numbers -------------------------------------------------------------------


def test_path_measure_numbers_are_exact() -> None:
    path = marks([100, 110, 105])
    measure = path_measure(path, [0, HOUR_MS, 2 * HOUR_MS], D(120))
    assert measure.hours == 3 and measure.first_ms == 0 and measure.last_ms == 2 * HOUR_MS
    assert (measure.start_equity, measure.end_equity) == (D(100), D(120))
    assert measure.compounded_return == D("0.2")
    with localcontext(CONTEXT):
        assert measure.max_drawdown == D(5) / D(110)
        assert measure.ratio == D("0.2") / (D(5) / D(110))
    # without a final point the path ends at its last boundary
    bare = path_measure(path, [0, HOUR_MS, 2 * HOUR_MS], None)
    assert bare.end_equity == D(105) and bare.compounded_return == D("0.05")


def test_path_measure_refuses_what_it_cannot_measure() -> None:
    path = marks([100, 110, 105], skip=(1,))
    with pytest.raises(Incomputable):  # no boundary at all
        path_measure(path, [], None)
    with pytest.raises(Incomputable):  # an hour with an incomplete mark
        path_measure(path, [0, HOUR_MS], None)
    with pytest.raises(Incomputable):  # an hour with no mark
        path_measure(path, [0, 9 * HOUR_MS], None)
    for first in (0, -5):  # V5: the first equity is not positive
        with pytest.raises(Incomputable):
            path_measure(marks([first, 10]), [0, HOUR_MS], D(10))
    with callers_error():  # hours out of order
        path_measure(marks([100, 110]), [HOUR_MS, 0], None)


# ---- V7: condition 1 ------------------------------------------------------------------------


def test_condition_1_ends_with_the_final_after_close() -> None:
    """The path is the common boundaries, then each arm's final after its close. The brief's main
    path, 100, 110, 105 and final 120, has a return of 0.2 (not the 0.05 of its last mark) and a
    drawdown of 5/110. The brief pairs it with a hold path of 100, 101, 102 and final 103 and
    expects True, but that hold path has no drawdown and a positive return, so V5 makes its ratio
    +infinity and the condition cannot hold. With the same hold path given a dip, 100, 102, 101
    and final 103, the finite ratio of the hold is beaten."""
    main = facts(final_after_close=D(120))
    rising = facts("hold_universe", final_after_close=D(103))
    flat_up = condition_1(
        main, marks([100, 110, 105]), rising, marks([100, 101, 102]), window=WINDOW
    )
    assert isinstance(flat_up.main, PathMeasure) and isinstance(flat_up.other, PathMeasure)
    assert flat_up.other.max_drawdown == 0 and flat_up.other.ratio == INFINITY
    assert flat_up.holds is False

    dipped = condition_1(
        main, marks([100, 110, 105]), rising, marks([100, 102, 101]), window=WINDOW
    )
    assert dipped.condition == 1 and dipped.capital == 1000 and dipped.note is None
    assert isinstance(dipped.main, PathMeasure) and isinstance(dipped.other, PathMeasure)
    assert dipped.main.compounded_return == D("0.2")
    with localcontext(CONTEXT):
        assert dipped.main.max_drawdown == D(5) / D(110)
        assert dipped.other.max_drawdown == D(1) / D(102)
    assert dipped.main.end_equity == D(120) and dipped.other.end_equity == D(103)
    assert dipped.main.hours == 3 and dipped.other.hours == 3
    assert dipped.holds is True


def test_condition_1_compares_ratios_not_returns() -> None:
    """A higher return with a deeper fall does not beat a calmer path."""
    main = facts(final_after_close=D(150))
    hold = facts("hold_universe", final_after_close=D(110))
    check = condition_1(main, marks([100, 50, 100]), hold, marks([100, 105, 104]), window=WINDOW)
    assert isinstance(check.main, PathMeasure) and isinstance(check.other, PathMeasure)
    assert check.main.compounded_return == D("0.5") > check.other.compounded_return == D("0.1")
    assert check.main.ratio == 1 < check.other.ratio  # 0.5 / 0.5 against 0.1 / (1/105)
    assert check.holds is False


def test_condition_1_uses_only_hours_both_arms_marked_complete() -> None:
    main = facts(final_after_close=D(120))
    hold = facts("hold_universe", final_after_close=D(103))
    main_marks = marks([100, 999, 110, 105], skip=(1,))
    hold_marks = marks([100, 101, 102, 101], skip=(3,))
    check = condition_1(main, main_marks, hold, hold_marks, window=WINDOW)
    assert isinstance(check.main, PathMeasure) and isinstance(check.other, PathMeasure)
    assert check.main.hours == 2 and check.other.hours == 2
    assert (check.main.start_equity, check.other.start_equity) == (D(100), D(100))
    assert check.main.max_drawdown == 0  # the 999 mark was skipped, not read


@pytest.mark.parametrize(
    "main_changes, hold_changes",
    [
        ({"outcome": LIQUIDATED, "final_after_close": None}, {}),
        ({"outcome": ENGINE_ERROR, "final_after_close": None}, {}),
        ({}, {"outcome": LIQUIDATED, "final_after_close": None}),
        ({}, {"outcome": ACCOUNTING_FAILURE, "final_after_close": None}),
        ({}, {"outcome": ENGINE_ERROR, "final_after_close": None}),
        ({"final_after_close": None}, {}),
        ({}, {"final_after_close": None}),
    ],
)
def test_condition_1_needs_both_arms_complete(main_changes, hold_changes) -> None:
    """V7: both must be complete, and any other outcome of hold_universe is incomplete."""
    main = facts(**main_changes)
    hold = facts("hold_universe", **hold_changes)
    check = condition_1(main, marks([100, 110, 105]), hold, marks([100, 102, 101]), window=WINDOW)
    assert check.holds is None and check.main is None and check.other is None
    assert check.note


def test_condition_1_first_equity_not_positive_is_incomputable() -> None:
    main = facts(final_after_close=D(120))
    hold = facts("hold_universe", final_after_close=D(103))
    check = condition_1(main, marks([0, 110, 105]), hold, marks([100, 102, 101]), window=WINDOW)
    assert check.holds is None and check.note


def test_empty_common_boundaries_are_incomputable() -> None:
    main = facts(final_after_close=D(120))
    hold = facts("hold_universe", final_after_close=D(103))
    # no hour in common
    check = condition_1(
        main, marks([100, 110]), hold, marks([100, 102], start=9 * HOUR_MS), window=WINDOW
    )
    assert (check.holds, check.main, check.other) == (None, None, None) and check.note
    # every common hour incomplete on one side
    check = condition_1(
        main, marks([100, 110], skip=(0, 1)), hold, marks([100, 102]), window=WINDOW
    )
    assert check.holds is None and check.note
    # no marks at all
    assert condition_1(main, [], hold, [], window=WINDOW).holds is None
    # condition 2 with a v4 path wholly outside v3's period
    v3 = facts("v3_as_built")
    outside = marks([100, 110], start=V3_END_MS)
    assert condition_2(facts(), outside, v3, marks([100, 101], start=V3_START_MS)).holds is None
    assert condition_2(facts(), outside, v3, outside).holds is None


def test_conditions_of_two_unlike_cells_are_a_callers_error() -> None:
    main = facts(final_after_close=D(120))
    with callers_error():
        condition_1(main, marks([100]), facts("hold_universe", 10000), marks([100]), window=WINDOW)
    with callers_error():
        condition_1(main, marks([100]), facts("hold_universe", cost=2), marks([100]), window=WINDOW)
    with callers_error():
        condition_2(main, marks([100]), facts("v3_as_built", 10000), marks([100]))
    with callers_error():
        condition_3(facts(cost=1))
    with callers_error():
        condition_4(facts(cost=2))


# ---- V8: condition 2 ------------------------------------------------------------------------


def test_condition_2_counts_only_v3s_period() -> None:
    """The marks before V3_START_MS and after V3_END_MS - HOUR_MS are ignored, and both ends of
    the period are included. With them, v4_main would be far ahead; without, it is behind."""
    before = [V3_START_MS - 2 * HOUR_MS, V3_START_MS - HOUR_MS]
    inside = [V3_START_MS, V3_START_MS + HOUR_MS, V3_LAST]
    after = [V3_END_MS, V3_END_MS + HOUR_MS]
    hours = before + inside + after
    main_marks: list[Mark] = [
        (hour, D(equity), True)
        for hour, equity in zip(hours, [50, 50, 100, 110, 99, 300, 300], strict=True)
    ]
    v3_marks: list[Mark] = [
        (hour, D(equity), True)
        for hour, equity in zip(hours, [1, 1, 100, "100.5", 101, 1000, 1000], strict=True)
    ]
    check = condition_2(facts(), main_marks, facts("v3_as_built"), v3_marks)
    assert check.condition == 2 and check.capital == 1000 and check.note is None
    assert isinstance(check.main, PathMeasure) and isinstance(check.other, PathMeasure)
    for measure in (check.main, check.other):
        assert measure.hours == 3
        assert (measure.first_ms, measure.last_ms) == (V3_START_MS, V3_LAST)
    assert (check.main.start_equity, check.main.end_equity) == (D(100), D(99))  # no final point
    assert check.main.compounded_return == D("-0.01")
    assert check.other.compounded_return == D("0.01")
    assert check.main.max_drawdown == D("0.1")
    assert check.holds is False


def test_condition_2_compares_returns_not_ratios() -> None:
    inside = [V3_START_MS, V3_START_MS + HOUR_MS, V3_LAST]
    v4: list[Mark] = [(h, D(e), True) for h, e in zip(inside, [100, 80, 130], strict=True)]
    v3: list[Mark] = [(h, D(e), True) for h, e in zip(inside, [100, 101, 102], strict=True)]
    check = condition_2(facts(), v4, facts("v3_as_built"), v3)
    assert isinstance(check.main, PathMeasure) and isinstance(check.other, PathMeasure)
    assert check.main.ratio < check.other.ratio == INFINITY  # worse ratio, better return
    assert check.holds is True


def test_after_stop_holds_the_final_equity_to_the_period_end() -> None:
    path = marks([100, 90, 80, 70], start=V3_START_MS)
    stop = V3_START_MS + 2 * HOUR_MS
    until = stop + 4 * HOUR_MS
    later = after_stop(path, stop, D(40), until)
    # the marks up to the stop stay as they are (the stop hour's open is before the stop); a mark
    # after it, which a stopped cell does not have, is dropped
    assert later[:3] == path[:3]
    assert later[3:] == [(stop + k * HOUR_MS, D(40), True) for k in range(1, 5)]
    assert after_stop(path, stop, D(40), stop) == path[:3]  # nothing after the stop to fill
    assert after_stop(path, stop, D(40), stop - HOUR_MS) == path[:3]
    # a stop that is not on an hour fills from the next hour open
    off_hour = after_stop(path[:2], V3_START_MS + HOUR_MS + 5, D(40), V3_START_MS + 3 * HOUR_MS)
    assert [hour for hour, _, _ in off_hour] == [V3_START_MS + k * HOUR_MS for k in range(4)]
    assert off_hour[-1] == (V3_START_MS + 3 * HOUR_MS, D(40), True)


def test_condition_2_after_a_v3_liquidation() -> None:
    """V6: after its stop v3 holds nothing, so at every hour to 2024-12-31 23:00 its equity is its
    final equity and its mark is complete. Only v4_main's marks then decide the common hours."""
    start = V3_START_MS
    v3_marks = marks([100, 90, 80], start=start)  # the stop hour is the last mark's
    v3 = facts("v3_as_built", outcome=LIQUIDATED, stop_ms=start + 2 * HOUR_MS, final_equity=D(40))
    main_marks = marks([100, 101, 102, 103, 104, 105], start=start, skip=(4,))
    main_marks.append((V3_LAST, D(110), True))
    check = condition_2(facts(), main_marks, v3, v3_marks)
    assert check.holds is True and check.note is None
    assert isinstance(check.main, PathMeasure) and isinstance(check.other, PathMeasure)
    # six hours main marked complete (index 4 skipped) plus the last hour, all common
    assert check.main.hours == check.other.hours == 6
    assert check.other.last_ms == V3_LAST
    assert (check.other.start_equity, check.other.end_equity) == (D(100), D(40))
    assert check.other.compounded_return == D("-0.6")
    assert check.other.max_drawdown == D("0.6")
    assert check.main.compounded_return == D("0.1")


def test_condition_2_liquidated_v3_with_no_stop_hour_or_equity_is_incomputable() -> None:
    """The inputs do not enforce a stop hour on a stopped outcome (task 2's review), so the rule
    must not crash on one."""
    start = V3_START_MS
    main_marks = marks([100, 101, 102], start=start)
    v3_marks = marks([100, 90, 80], start=start)
    for changes in ({"stop_ms": None}, {"final_equity": None}):
        v3 = facts("v3_as_built", outcome=LIQUIDATED, **changes)
        check = condition_2(facts(), main_marks, v3, v3_marks)
        assert (check.holds, check.main, check.other) == (None, None, None) and check.note


@pytest.mark.parametrize("outcome", [ENGINE_ERROR, ACCOUNTING_FAILURE, LIMIT_UNRESTORABLE])
def test_condition_2_needs_a_v3_path(outcome: str) -> None:
    """V6 covers a liquidated v3 only; any other stop or failure leaves no path to compare."""
    start = V3_START_MS
    v3 = facts("v3_as_built", outcome=outcome)
    check = condition_2(facts(), marks([100, 101], start=start), v3, [])
    assert check.holds is None and check.note


def test_condition_2_needs_a_v4_arm_that_ran_the_period() -> None:
    start = V3_START_MS
    stopped = facts(outcome=LIQUIDATED)
    check = condition_2(
        stopped,
        marks([100, 101], start=start),
        facts("v3_as_built"),
        marks([100, 101], start=start),
    )
    assert check.holds is None and check.note


# ---- V9: conditions 3 and 4 -----------------------------------------------------------------


def test_conditions_3_and_4() -> None:
    gain = facts(cost=2, capital=10000, final_after_close=D("10000.01"))
    three = condition_3(gain)
    assert (three.condition, three.capital, three.holds) == (3, 10000, True)
    assert (three.main, three.other, three.note) == (D("10000.01"), D(10000), None)
    # net profit must be positive: break-even is not
    assert condition_3(facts(cost=2, final_after_close=D(1000))).holds is False
    assert condition_3(facts(cost=2, final_after_close=D("999.99"))).holds is False

    kept = facts(final_after_close=D(1200), equity_2025=D(1100))
    four = condition_4(kept)
    assert (four.condition, four.capital, four.holds) == (4, 1000, True)
    assert (four.main, four.other, four.note) == (D(1200), D(1100), None)
    assert condition_4(facts(final_after_close=D(1100), equity_2025=D(1100))).holds is False
    assert condition_4(facts(final_after_close=D(1000), equity_2025=D(1100))).holds is False


def test_condition_4_with_no_equity_at_2025_cannot_be_computed() -> None:
    check = condition_4(facts(final_after_close=D(1200), equity_2025=None))
    assert (check.condition, check.capital) == (4, 1000)
    assert (check.holds, check.main, check.other) == (None, None, None) and check.note


@pytest.mark.parametrize(
    "outcome", [LIQUIDATED, LIMIT_UNRESTORABLE, ACCOUNTING_FAILURE, ENGINE_ERROR]
)
def test_conditions_3_and_4_of_a_cell_that_did_not_complete(outcome: str) -> None:
    three = condition_3(facts(cost=2, outcome=outcome))
    four = condition_4(facts(outcome=outcome))
    for check in (three, four):
        assert check.holds is None and check.main is None and check.note


def test_condition_3_and_4_with_no_equity_after_the_close() -> None:
    assert condition_3(facts(cost=2, final_after_close=None)).holds is None
    assert condition_4(facts(final_after_close=None)).holds is None


# ---- skipped hours: "skipped for all arms alike and listed" ---------------------------------


def dense(
    first: int, last: int, *, incomplete: tuple[int, ...] = (), absent: tuple[int, ...] = ()
) -> list[Mark]:
    """A mark at every hour open from ``first`` to ``last`` (both included), complete except at
    the ``incomplete`` hours, and none at the ``absent`` ones."""
    return [
        (hour, D(100), hour not in incomplete)
        for hour in range(first, last + 1, HOUR_MS)
        if hour not in absent
    ]


def test_skipped_hours_list_what_either_arm_misses_sorted() -> None:
    left = marks([1, 2, 3, 4, 5, 6], skip=(1,))  # incomplete at hour 1
    right = [
        mark for index, mark in enumerate(marks([1, 2, 3, 4, 5, 6])) if index != 3
    ]  # no hour 3
    assert skipped_hours(left, right, start_ms=0, end_ms=5 * HOUR_MS) == (HOUR_MS, 3 * HOUR_MS)
    # an hour both arms miss is listed once, and both ends of the range are included
    both = skipped_hours(
        marks([1, 2, 3], skip=(0, 2)), marks([1, 2, 3], skip=(0,)), start_ms=0, end_ms=2 * HOUR_MS
    )
    assert both == (0, 2 * HOUR_MS)
    # hours outside the range are not listed; hours beyond the marks, inside it, are
    assert skipped_hours(left, right, start_ms=HOUR_MS, end_ms=3 * HOUR_MS) == (
        HOUR_MS,
        3 * HOUR_MS,
    )
    assert skipped_hours(left, right, start_ms=4 * HOUR_MS, end_ms=7 * HOUR_MS) == (
        6 * HOUR_MS,
        7 * HOUR_MS,
    )
    assert skipped_hours([], [], start_ms=0, end_ms=2 * HOUR_MS) == (0, HOUR_MS, 2 * HOUR_MS)
    assert skipped_hours(left, right, start_ms=4 * HOUR_MS, end_ms=3 * HOUR_MS) == ()
    with callers_error():  # the range starts at an hour open
        skipped_hours(left, right, start_ms=5, end_ms=HOUR_MS)


def test_condition_1_lists_the_skipped_hours_of_its_window() -> None:
    """Each arm misses a different hour: both are listed, sorted, and the path has the others."""
    main = facts(final_after_close=D(120))
    hold = facts("hold_universe", final_after_close=D(103))
    main_marks = marks([100, 110, 105, 108, 109, 111], skip=(1,))
    hold_marks = [m for index, m in enumerate(marks([100, 102, 101, 104, 105, 106])) if index != 3]
    check = condition_1(main, main_marks, hold, hold_marks, window=(0, 5 * HOUR_MS))
    assert check.skipped_ms == (HOUR_MS, 3 * HOUR_MS)
    assert isinstance(check.main, PathMeasure) and check.main.hours == 4
    # the window decides which hours count: hours past the last mark are skipped too
    wider = condition_1(main, main_marks, hold, hold_marks, window=(0, 7 * HOUR_MS))
    assert wider.skipped_ms == (HOUR_MS, 3 * HOUR_MS, 6 * HOUR_MS, 7 * HOUR_MS)
    # the window is required: a computed check always lists its skipped hours (a computed check
    # of condition 1 with none is a record check_from_record refuses)
    with pytest.raises(TypeError, match="window"):
        condition_1(main, main_marks, hold, hold_marks)  # type: ignore[call-arg]
    # a check that cannot be computed lists nothing
    stopped = facts(outcome=LIQUIDATED)
    cannot = condition_1(stopped, main_marks, hold, hold_marks, window=(0, 5 * HOUR_MS))
    assert cannot.holds is None and cannot.skipped_ms is None
    no_hour = condition_1(
        main, marks([100], start=9 * HOUR_MS), hold, hold_marks, window=(0, 5 * HOUR_MS)
    )
    assert no_hour.holds is None and no_hour.skipped_ms is None


def test_condition_2_lists_the_skipped_hours_of_v3s_period() -> None:
    """Only the period counts (the marks around it do not), and the arms miss different hours."""
    start = V3_START_MS
    main_marks = [
        (start - HOUR_MS, D(50), True),
        *dense(start, V3_LAST, incomplete=(start + 7 * HOUR_MS,)),
    ]
    main_marks.append((V3_END_MS, D(300), True))
    v3_marks = dense(start - HOUR_MS, V3_END_MS, absent=(start + 3 * HOUR_MS,))
    check = condition_2(facts(), main_marks, facts("v3_as_built"), v3_marks)
    assert check.skipped_ms == (start + 3 * HOUR_MS, start + 7 * HOUR_MS)
    assert check.note is None and check.holds is not None
    # a period with few marks lists every other hour of it, in order
    sparse = [(h, D(100), True) for h in (start, start + HOUR_MS, V3_LAST)]
    sparse_check = condition_2(facts(), sparse, facts("v3_as_built"), sparse)
    everything = range(start, V3_LAST + 1, HOUR_MS)
    assert sparse_check.skipped_ms == tuple(
        h for h in everything if h not in {s for s, _, _ in sparse}
    )
    assert len(sparse_check.skipped_ms or ()) == len(everything) - 3


def test_condition_2_after_a_v3_liquidation_skips_no_hour_v4_main_marked() -> None:
    """V6 makes v3's mark complete at every hour after its stop, so an hour after the stop is
    skipped only where v4_main's mark is missing or incomplete there."""
    start = V3_START_MS
    stop = start + 2 * HOUR_MS
    v3 = facts("v3_as_built", outcome=LIQUIDATED, stop_ms=stop, final_equity=D(40))
    v3_marks = dense(start, stop)  # the stop hour's open is its last mark
    complete = condition_2(facts(), dense(start, V3_LAST), v3, v3_marks)
    assert complete.holds is not None and complete.skipped_ms == ()
    gaps = (start + 4 * HOUR_MS, start + 9 * HOUR_MS)
    marked = dense(start, V3_LAST, incomplete=gaps[:1], absent=gaps[1:])
    check = condition_2(facts(), marked, v3, v3_marks)
    assert check.skipped_ms == gaps
    assert isinstance(check.other, PathMeasure) and check.other.last_ms == V3_LAST
    # before the stop, v3's own missing marks are skipped as for any arm
    early = condition_2(
        facts(), dense(start, V3_LAST), v3, dense(start, stop, absent=(start + HOUR_MS,))
    )
    assert early.skipped_ms == (start + HOUR_MS,)


def test_skipped_against_v3_needs_a_v3_path() -> None:
    with pytest.raises(Incomputable):
        skipped_against_v3(
            dense(V3_START_MS, V3_LAST), facts("v3_as_built", outcome=ENGINE_ERROR), []
        )
    complete = skipped_against_v3(
        dense(V3_START_MS, V3_LAST), facts("v3_as_built"), dense(V3_START_MS, V3_LAST)
    )
    assert complete == ()


def test_conditions_3_and_4_and_an_unmeasured_check_list_no_hours() -> None:
    assert condition_3(facts(cost=2, final_after_close=D(1100))).skipped_ms is None
    assert condition_4(facts(final_after_close=D(1100))).skipped_ms is None
    absent = decide({}, [], expected=(), missing=[], reruns=[], dispatches=[])
    assert all(check.skipped_ms is None for check in absent.checks)


# ---- V10: precedence ------------------------------------------------------------------------


V4_MAIN = [cell for cell in RUN if cell.startswith(f"{MAIN_ARM}-")]


def test_the_run_s_cells_and_the_stop_outcomes() -> None:
    assert len(RUN) == 48 and len(set(RUN)) == 48
    assert set(PASS_RULE_CELLS) <= set(RUN)
    assert len(REPORTED) == 40 and len(OTHER_ARMS) == 44 and len(V4_MAIN) == 4
    assert tuple(cell for cell in RUN if not cell.startswith("v3_as_built-")) == TIMING
    assert len(TIMING) == 44
    assert {LIQUIDATED, LIMIT_UNRESTORABLE, ACCOUNTING_FAILURE} == STOP_FAILS
    assert CAPITALS_JUDGED == (1000, 10000)


def test_a_stop_in_any_v4_main_cell_fails_whatever_is_missing() -> None:
    accepted = run_cells(v4_main_1000_2x=LIQUIDATED)
    del accepted["hold_universe-10000-1x"]
    verdict = decide(
        accepted,
        all_checks(None)[:6],
        expected=RUN,
        missing=["hold_universe-10000-1x"],
        reruns=["v3_as_built-1000-1x"],
        dispatches=["another"],
    )
    assert verdict.outcome == "fail"


@pytest.mark.parametrize("cell, outcome", list(itertools.product(V4_MAIN, sorted(STOP_FAILS))))
def test_every_stop_outcome_of_every_v4_main_cell_is_a_fail(cell: str, outcome: str) -> None:
    accepted = with_outcome(cell, outcome)
    verdict = decided(accepted, all_checks(True), reruns=("x",), dispatches=("y",))
    assert verdict.outcome == "fail"
    assert any(cell in reason and outcome in reason for reason in verdict.reasons)


def test_the_fail_precedence_wins_over_every_incomplete_cause() -> None:
    """v4-d25 leaves the fail precedence above everything: a stopped v4_main fails with a missing
    reported cell, a refused one, an engine error and an accounting failure in other arms, a
    re-run, another dispatch and checks that cannot be computed, all at once."""
    accepted = run_cells(
        v4_main_10000_2x=LIMIT_UNRESTORABLE,
        v4_vol25_1000_1x=ENGINE_ERROR,
        hold_btc_10000_2x=ACCOUNTING_FAILURE,
    )
    del accepted["v4_long_only-1000-1x"]
    verdict = decide(
        accepted,
        all_checks(None)[:3],
        expected=RUN,
        missing=["v4_long_only-1000-1x", "v4_confirm3-10000-1x"],
        reruns=["v4_main-1000-1x"],
        dispatches=["another"],
    )
    assert verdict.outcome == "fail"
    for cell in (
        "v4_main-10000-2x",
        "v4_vol25-1000-1x",
        "hold_btc-10000-2x",
        "v4_long_only-1000-1x",
        "v4_confirm3-10000-1x",
    ):
        assert any(cell in reason for reason in verdict.reasons), cell
    # without the stop, the same causes are incomplete
    accepted["v4_main-10000-2x"] = facts(capital=10000, cost=2)
    unstopped = decide(
        accepted,
        all_checks(None)[:3],
        expected=RUN,
        missing=["v4_long_only-1000-1x", "v4_confirm3-10000-1x"],
        reruns=["v4_main-1000-1x"],
        dispatches=["another"],
    )
    assert unstopped.outcome == "incomplete"


@pytest.mark.parametrize("cell", OTHER_ARMS)
def test_a_reported_stop_is_a_result_not_the_fail_precedence(cell: str) -> None:
    """V10 step 1 is v4_main's alone, and a liquidated or limit_unrestorable cell of another arm
    is a full summary, a reported result: by itself it makes the verdict neither fail nor
    incomplete (v4-d25). With the checks as supplied here, the verdict passes."""
    for outcome in (LIQUIDATED, LIMIT_UNRESTORABLE):
        verdict = decided(with_outcome(cell, outcome))
        assert verdict.outcome == "pass", (cell, outcome)
        assert verdict.reasons == ()


def test_a_stopped_hold_universe_is_incomplete_through_its_condition() -> None:
    """Another arm's stop is the conditions' business: a liquidated hold_universe has no path
    (V7), so condition 1 is incomputable and the verdict is incomplete."""
    accepted = run_cells(hold_universe_1000_1x=LIQUIDATED)
    checks = [
        holds(1, 1000, None) if (c.condition, c.capital) == (1, 1000) else c for c in all_checks()
    ]
    verdict = decided(accepted, checks)
    assert verdict.outcome == "incomplete"
    assert not any("hold_universe-1000-1x" in reason for reason in verdict.reasons)


@pytest.mark.parametrize("cell", OTHER_ARMS)
def test_an_accounting_failure_outside_v4_main_is_incomplete(cell: str) -> None:
    """v4-d25: a cell whose own accounting failed is not usable evidence, so outside v4_main
    (where it fails the run) it makes the verdict incomplete, in a reported arm too."""
    verdict = decided(with_outcome(cell, ACCOUNTING_FAILURE))
    assert verdict.outcome == "incomplete", cell
    assert [reason for reason in verdict.reasons if cell in reason] == [
        f"cell {cell} ended in an accounting failure, so it is not usable evidence"
    ]


@pytest.mark.parametrize("cell", RUN)
def test_an_engine_error_or_a_missing_cell_of_the_run_is_incomplete(cell: str) -> None:
    """v4-d25: every one of the 48 cells counts, the 40 reported ones too."""
    errored = decided(with_outcome(cell, ENGINE_ERROR))
    assert errored.outcome == "incomplete", cell
    assert [reason for reason in errored.reasons if cell in reason] == [
        f"cell {cell} ended in an engine error"
    ]

    accepted = run_cells()
    del accepted[cell]
    gone = decided(accepted, all_checks(True), missing=(cell,))
    assert gone.outcome == "incomplete", cell
    assert [reason for reason in gone.reasons if cell in reason] == [
        f"cell {cell} is missing or refused"
    ]

    # missing from `accepted` alone is enough, whether or not it is listed in `missing`
    assert decided(accepted, all_checks(True)).outcome == "incomplete", cell
    # and listing it as missing is enough when `accepted` still has it
    assert decided(run_cells(), all_checks(True), missing=(cell,)).outcome == "incomplete"


def test_a_missing_reported_cell_is_incomplete() -> None:
    """The cells of Bob's question: ones no condition reads. Before v4-d25 they changed nothing."""
    verdict = decided(missing=("hold_universe-1000-2x", "v4_vol25-1000-1x"))
    assert verdict.outcome == "incomplete"
    assert verdict.reasons == (
        "cell v4_vol25-1000-1x is missing or refused",
        "cell hold_universe-1000-2x is missing or refused",
    )  # in the run's order, not the caller's
    assert all(check.holds is True for check in verdict.checks)  # every condition still holds


def test_a_timing_run_counts_its_44_cells() -> None:
    """A timing run's expected file lists the 44 cells that are not v3: those are the ones that
    count, and its verdict (not a result) is incomplete through condition 2, which reads v3."""
    accepted = run_cells(TIMING)
    timing = [c for c in all_checks(True) if c.condition != 2]  # the step plans no condition 2
    verdict = decided(accepted, timing, expected=TIMING)
    assert verdict.outcome == "incomplete"
    assert not any("is missing or refused" in reason for reason in verdict.reasons)
    assert [c.holds for c in verdict.checks if c.condition == 2] == [None, None]
    assert all(
        "not in this run" in str(c.note) for c in verdict.checks if c.condition == 2
    )  # the filled-in note
    # with the 8 checks given, the 44 alone would pass: no v3 cell is missing from a timing run
    assert decided(accepted, expected=TIMING).outcome == "pass"
    # and each of its 44 counts as any run's
    for cell in ("v4_vol25-10000-2x", "hold_btc_trend-1000-1x"):
        assert cell in TIMING
        short = dict(accepted)
        del short[cell]
        assert decided(short, expected=TIMING, missing=(cell,)).outcome == "incomplete"
        errored = run_cells(TIMING, **{cell.replace("-", "_"): ENGINE_ERROR})
        assert decided(errored, expected=TIMING).outcome == "incomplete"


def test_decide_refuses_cells_that_are_not_the_run_s() -> None:
    with callers_error():
        decided(run_cells(), expected=TIMING)  # accepted v3 cells in a timing run
    with callers_error():
        decided(missing=("v4_main-500-1x",))
    with callers_error():
        decided(run_cells(TIMING), expected=TIMING, missing=("v3_as_built-1000-1x",))


def test_a_missing_check_counts_as_incomputable() -> None:
    checks = [c for c in all_checks(True) if (c.condition, c.capital) != (3, 10000)]
    assert len(checks) == 7
    verdict = decided(checks=checks)
    assert verdict.outcome == "incomplete"
    assert len(verdict.checks) == 8
    absent = [c for c in verdict.checks if (c.condition, c.capital) == (3, 10000)]
    assert [c.holds for c in absent] == [None] and absent[0].note
    assert any("condition 3" in reason and "10000" in reason for reason in verdict.reasons)
    assert decided(checks=[]).outcome == "incomplete"


def test_rerun_or_dispatch_is_incomplete() -> None:
    assert decided(reruns=("v4_main-1000-1x",)).outcome == "incomplete"
    assert decided(reruns=("v4_vol25-1000-1x",)).outcome == "incomplete"  # whatever the cell
    dispatched = decided(dispatches=("an earlier run",))
    assert dispatched.outcome == "incomplete"
    # one reason for both of its causes: another dispatch, or a re-run of one of this run's jobs
    assert dispatched.reasons == (
        "another dispatch of this registration, or a re-run of one of this run's jobs, was found",
    )
    assert decided(reruns=("x",)).reasons == ("a re-run of a cell was found",)
    assert decided(missing=(), reruns=(), dispatches=()).outcome == "pass"
    # a re-run does not hide a condition that fails: both are reported, incomplete decides
    mixed = decided(checks=all_checks(True)[:-1] + [holds(4, 10000, False)], reruns=("x",))
    assert mixed.outcome == "incomplete"
    # a stop still wins over a re-run or another dispatch
    stopped = decided(
        with_outcome("v4_main-10000-1x", ACCOUNTING_FAILURE), reruns=("x",), dispatches=("y",)
    )
    assert stopped.outcome == "fail"


def test_all_eight_checks_hold_is_pass_one_false_is_fail() -> None:
    passing = decided()
    assert passing.outcome == "pass" and len(passing.checks) == 8
    assert passing.reasons == ()
    for capital, condition in itertools.product(CAPITALS_JUDGED, (1, 2, 3, 4)):
        checks = [
            holds(c.condition, c.capital, not (c.condition == condition and c.capital == capital))
            for c in all_checks()
        ]
        verdict = decided(checks=checks)
        assert verdict.outcome == "fail", (condition, capital)
        assert len(verdict.reasons) == 1
        assert f"condition {condition}" in verdict.reasons[0] and str(capital) in verdict.reasons[0]
    # one check that cannot be computed is incomplete, never a pass and never a fail
    for index in range(8):
        checks = all_checks(True)
        checks[index] = holds(checks[index].condition, checks[index].capital, None)
        assert decided(checks=checks).outcome == "incomplete"
    # incomplete outranks a failed condition
    both = all_checks(False)
    both[0] = holds(1, 1000, None)
    assert decided(checks=both).outcome == "incomplete"


def test_decide_orders_the_checks_by_capital_then_condition() -> None:
    shuffled = list(reversed(all_checks()))
    verdict = decided(checks=shuffled)
    assert [(c.capital, c.condition) for c in verdict.checks] == [
        (capital, n) for capital in CAPITALS_JUDGED for n in (1, 2, 3, 4)
    ]


def test_decide_refuses_checks_that_are_not_the_rules() -> None:
    with callers_error():
        decided(checks=all_checks() + [holds(1, 1000)])  # a duplicate
    with callers_error():
        decided(checks=[holds(5, 1000)])  # not a condition
    with callers_error():
        decided(checks=[holds(1, 500)])  # not a judged capital


def test_notes_and_reasons_are_words_never_a_figure() -> None:
    """Public logs carry no equity. Feed a distinctive equity through every path that writes a note
    or a reason, and look for it, and for any decimal figure, in the words."""
    figures = {"final_after_close": SECRET, "equity_2025": SECRET, "final_equity": SECRET}
    main = facts(**figures)
    hold = facts("hold_universe", **figures)
    v3_path = marks([SECRET], start=V3_START_MS)
    notes = [
        condition_1(
            main,
            marks([SECRET, 110]),
            facts("hold_universe", outcome=LIQUIDATED),
            [],
            window=WINDOW,
        ),
        condition_1(main, marks([0, 110]), hold, marks([0, 110]), window=WINDOW),
        condition_1(main, marks([SECRET]), hold, marks([SECRET], start=HOUR_MS), window=WINDOW),
        condition_2(main, v3_path, facts("v3_as_built", outcome=ENGINE_ERROR), []),
        condition_2(
            main,
            v3_path,
            facts("v3_as_built", outcome=LIQUIDATED, stop_ms=None, final_equity=SECRET),
            v3_path,
        ),
        condition_2(facts(outcome=LIQUIDATED, final_equity=SECRET), v3_path, hold, v3_path),
        condition_3(facts(cost=2, outcome=LIQUIDATED, final_equity=SECRET)),
        condition_4(facts(final_after_close=SECRET, equity_2025=None)),
        condition_4(facts(outcome=ACCOUNTING_FAILURE)),
    ]
    assert all(check.holds is None and check.note for check in notes)
    words = [check.note for check in notes if check.note]

    accepted = run_cells(hold_universe_1000_1x=ENGINE_ERROR)
    del accepted["v3_as_built-1000-1x"]
    accepted["v4_main-10000-2x"] = facts(
        capital=10000, cost=2, outcome=LIQUIDATED, final_equity=SECRET
    )
    accepted["v4_vol60-1000-2x"] = facts("v4_vol60", cost=2, outcome=ACCOUNTING_FAILURE)
    verdict = decide(
        accepted,
        [Check(1, 1000, False, None, None, None), Check(2, 1000, None, None, None, words[0])],
        expected=RUN,
        missing=["v3_as_built-1000-1x"],
        reruns=["v4_main-1000-1x"],
        dispatches=["run 4242424242 of the same registration"],
    )
    assert len(verdict.reasons) >= 8
    words.extend(verdict.reasons)
    for text in words:
        assert "8675309" not in text and "4242424242" not in text
        assert re.search(r"[0-9]+[.][0-9]+", text) is None


def test_a_verdict_carries_its_checks_unchanged() -> None:
    measure = PathMeasure(3, 0, 2 * HOUR_MS, D(100), D(120), D("0.2"), D("0.04"), D(5))
    checks = all_checks()
    checks[0] = Check(1, 1000, True, measure, measure, None)
    verdict = decided(checks=checks)
    assert verdict.checks[0].main is measure
    assert verdict.outcome == "pass"
