"""The spec v2 scorer: experiment spec v2 section 8 over the results a replay wrote.

    python -m crypto_grid_bot.backtest.acceptance_v2 RUN [RUN ...] --out verdict.json

Each RUN is a run directory or its ``results.json``. The candidate is the mode switcher
(MS). C6 compares it with always-grid (spec v1's variant F) and with cash, and variant D
and buy-and-hold are reported only. ``full-range-2017-2024`` is the scored window
(``SCORED``): the mode switcher passes spec v2 only if C1-C6 all pass over its included
runs there. ``practice-2022`` and ``verify-2024h1`` are run as a sanity check and
reported only (``REPORTED``). The criteria:

* C1-C4 are spec v1's, computed by spec v1's scorer (``acceptance``);
* C5: each run's round trips (its completed grid cycles plus its completed uptrend
  trades) per 365.25-day year of the window, with a mean of at least 12, exactly;
* C6: in at least 60% of runs the run's return is positive, so it beats cash, and its
  compound-annualised return / max(drawdown, 0.1 points) exceeds always-grid's in the
  same window, pair and path. Where the two runs' raw returns and floored drawdowns
  order their exact ratios, that order decides, so an exact tie does not exceed;
  otherwise a comparison is decided only where the annualising error bounds settle it,
  as C2's are. A missing or invalid always-grid run counts against.

Reported, deciding nothing: upside capture, the mode readouts (the share of time in each
mode, the mode switches, the round trips by mode, the uptrend stops and fades), D,
buy-and-hold and R1.

Everything v1 and v2 share is spec v1's scorer, unchanged: the input checks, the pins to
this code's clean commit and to the dataset specs, manifests and default config committed
beside it, the comparison mask, the exact arithmetic and the fail-closed verdict file.
Like it, this scorer fails closed and skips nothing:

* an input that is not a spec v2 run is refused, and nothing is scored. That covers
  another code, engine, features, integrity rules, config, fee or sensitivity setting; a
  row that is not MS, F, D or the ungated V0 baseline (which every results file carries,
  and which is ignored); a window outside ``SCORED`` and ``REPORTED``; a committed spec
  without its registered months, warm-ups and pairs; two rows for one role, window, pair
  and path; and two comparison masks for one window;
* the inputs must hold every window's whole matrix, an MS, an F and a D row for every
  included pair and path, or they are refused: a gap is never scored as a fail;
* a scored window left with fewer than 2 included pairs gives "insufficient evidence".

The rows this scorer reads. F's and D's are spec v1's rows. The MS rows come from Task 6
of the build plan (``docs/superpowers/plans/2026-10-06-mode-switcher.md``), and each must
carry ``strategy`` = ``MODE_SWITCH_STRATEGY`` with ``variant`` = "MS", and every field
of ``MS_ROW_FIELDS``:

* spec v1's row fields, read as spec v1's scorer reads them: ``symbol``, ``path_mode``,
  ``initial_quote``, ``final_total_equity``, ``max_drawdown_pct``,
  ``active_max_drawdown_pct``, ``buy_and_hold_max_drawdown_pct``,
  ``hard_drawdown_halts``, ``completed_cycles`` (the grid's completed cycles, the only
  record of them), ``time_with_inventory_pct``, ``accounting_problems``,
  ``transient_pauses``, ``bars``, ``final_exit_blocked``, ``final_unsellable_notional``,
  ``rules`` and ``assumed_spread_pct``;
* ``hourly_equity``: ``[open_ms, total equity, buy-and-hold value]`` at each hour's
  first replayed bar, as replay writes it for every row;
* ``modes``, with every key of ``MODES_FIELDS``:

  - ``uptrend_trades``: the completed uptrend round trips, a count. Grid cycles are
    never copied here;
  - ``buy_and_hold_final``: buy-and-hold's final value, as an exact decimal string;
  - ``time_ms``: the milliseconds spent in each mode of ``MODE_NAMES``, summing to the
    window's registered length;
  - ``switches``, ``stops`` and ``fades``: counts.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, NamedTuple

from crypto_grid_bot.backtest import acceptance
from crypto_grid_bot.backtest.__main__ import code_commit, result_failures
from crypto_grid_bot.backtest.acceptance import (
    C7_NOTE,
    FROZEN_HINT,
    GATE_FLOOR_PCT,
    NUMBERS_NOTE,
    PRIMARY,
    REGISTERED_DAYS,
    YEAR_DAYS,
    Criterion,
    Figure,
    Run,
    ScoringError,
    Source,
    Window,
    as_json,
    certain,
    code_problems,
    committed_name,
    count,
    document_problems,
    economics,
    evaluation_window,
    exact,
    gate_ratio,
    integrity,
    makes_money,
    mean,
    number,
    pinned,
    positive,
    read_results,
    return_pct,
    run_json,
    safer_than_holding,
    shown,
    thin_windows,
    variant_of,
    window_json,
    window_of,
    worst_drop,
    write_verdict,
    written,
)
from crypto_grid_bot.backtest.dataset import DatasetSpec, load_spec
from crypto_grid_bot.backtest.features import FEATURE_VERSION
from crypto_grid_bot.backtest.jobs import SOURCE_IDENTITY
from crypto_grid_bot.backtest.replay import DAY_MS, ENGINE_VERSION, INTEGRITY_RULES, PATH_MODES

# The name of these scoring rules, recorded in every verdict.
SCORING = "spec-v2-section-8"
ROUND_TRIPS_PER_YEAR = 12  # C5
GATE_SHARE = Fraction(3, 5)  # C6: at least 60% of included runs, as in spec v1
# Section 8: the window that decides, and the sanity windows that are run and reported.
SCORED = ("full-range-2017-2024",)
REPORTED = ("practice-2022", "verify-2024h1")


class Registration(NamedTuple):
    """A window as spec v2 section 8 registers it, by its dataset spec's fields."""

    daily_warmup_start: str | None
    warmup_start: str
    start: str
    end: str
    traded: tuple[str, ...]  # sorted


# Section 8: full-range-2017-2024 as spec v1 section 4 froze it (evaluation 2019-01 to
# 2024-12, warm-ups from 2018-06), and the two sanity windows as their committed v1 specs
# have them, with each window's pairs. Every indicator and early decision is computed
# from the warm-ups, so they are registered too. REGISTERED_DAYS gives the lengths.
REGISTRATIONS = {
    "full-range-2017-2024": Registration(
        "2018-06", "2018-06", "2019-01", "2024-12", ("BTCUSDT", "ETHUSDT", "XRPUSDT")
    ),
    "practice-2022": Registration(
        "2020-05", "2022-04", "2022-06", "2023-01", ("BTCUSDT", "SOLUSDT", "XRPUSDT")
    ),
    "verify-2024h1": Registration(
        "2020-05", "2023-11", "2024-01", "2024-06", ("ADAUSDT", "BTCUSDT")
    ),
}

# The rows (the module docstring lists them). The MS rows' labels: the strategy must not
# start with "gated grid", which spec v1's feature check reserves for its own grids.
MODE_SWITCH_STRATEGY = "mode switcher (spec-v2)"
MODE_SWITCH = "MS"
ROLES = (MODE_SWITCH, "F", "D")  # the candidate, always-grid (C6) and D (reported)
HOURLY_EQUITY = "hourly_equity"
MODES = "modes"
UPTREND_TRADES = "uptrend_trades"
BUY_AND_HOLD_FINAL = "buy_and_hold_final"
TIME_MS = "time_ms"
SWITCHES = "switches"
STOPS = "stops"
FADES = "fades"
MODE_NAMES = ("cash", "grid", "uptrend")
MS_ROW_FIELDS = (
    "symbol",
    "path_mode",
    "strategy",
    "variant",
    "initial_quote",
    "final_total_equity",
    "max_drawdown_pct",
    "active_max_drawdown_pct",
    "buy_and_hold_max_drawdown_pct",
    "hard_drawdown_halts",
    "completed_cycles",
    "time_with_inventory_pct",
    "accounting_problems",
    "transient_pauses",
    "bars",
    "final_exit_blocked",
    "final_unsellable_notional",
    "rules",
    "assumed_spread_pct",
    HOURLY_EQUITY,
    MODES,
)
MODES_FIELDS = (UPTREND_TRADES, BUY_AND_HOLD_FINAL, TIME_MS, SWITCHES, STOPS, FADES)

# The frozen inputs are spec v1's: the dataset specs, manifests and default config
# committed beside this code.
DATASET_SPECS = acceptance.DATASET_SPECS
ACCEPTANCE_CONFIG = acceptance.ACCEPTANCE_CONFIG
WHOLE_MATRIX = (
    "spec v2 needs every window's whole matrix: an MS, an F and a D row for every included "
    "pair and path (section 8)"
)
ACCEPTED_NOTE = (
    "the mode switcher passes C1-C6 over full-range-2017-2024's included runs (spec v2 section 8)"
)
# Spec v1's run figures that are not spec v2's: v1's C5 rate and its C6 baseline ratios.
V1_ONLY = ("cycles_per_week", "gate_ratio", "baseline_gate_ratio", "baseline_problem")
# What the verdict records of each input, as spec v1's verdict does.
INPUT_FIELDS = (
    "dataset",
    "feature_version",
    "spec_sha256",
    "manifest_sha256",
    "config_sha256",
    "code_commit",
    "code_sha256",
    "policy",
)


@dataclass(frozen=True)
class Readout:
    """An MS run's reported figures (section 8, "Reported, not gating"). Its grid cycles
    are the run's own ``Run.completed_cycles``, never a copy."""

    uptrend_trades: int
    time_ms: Mapping[str, int]  # each of MODE_NAMES
    switches: int
    stops: int
    fades: int
    buy_and_hold_return_pct: Fraction
    upside_capture: Fraction | None


@dataclass(frozen=True)
class WindowScore:
    """One window's included runs by role, and the mode switcher's C1-C6 over them."""

    window: Window
    scored: bool  # False: run and reported, deciding nothing
    ms: tuple[Run, ...]
    always_grid: tuple[Run, ...]
    benchmark: tuple[Run, ...]  # D
    criteria: tuple[Criterion, ...]
    r1: dict[str, Figure]

    @property
    def passed(self) -> bool:
        return all(criterion.passed for criterion in self.criteria)


@dataclass(frozen=True)
class Verdict:
    sources: tuple[Source, ...]
    windows: tuple[WindowScore, ...]  # SCORED, then REPORTED
    trips: Mapping[str, int]  # each MS run's round trips, by run label
    readouts: Mapping[str, Readout]  # by run label
    # "pass", "fail" or "insufficient evidence"; an incomplete matrix refuses.
    outcome: str
    reasons: tuple[str, ...]


# The criteria (section 8).


def round_trips(row: dict[str, Any]) -> int:
    """C5's count: the completed grid cycles, read from the row's own
    ``completed_cycles`` as ``Run.completed_cycles`` is, plus the completed uptrend
    trades. Both pass through spec v1's ``count``, which refuses a boolean, a negative or
    a non-integer, so malformed evidence is refused rather than scored."""
    return count(row["completed_cycles"]) + count(row[MODES][UPTREND_TRADES])


def activity_v2(runs: Sequence[Run], trips: Mapping[str, int]) -> Criterion:
    """C5: the mean over all runs of each run's round trips x 365.25 / the window's days,
    computed exactly, is at least 12. ``trips`` holds each run's round trips by label."""
    if not runs:
        return Criterion("C5", False, {"mean round trips per year": "no runs"})
    rate = mean([Fraction(trips[run.label]) * YEAR_DAYS / run.days for run in runs])
    numbers: dict[str, Figure] = {
        "mean round trips per year": rate,
        "minimum": ROUND_TRIPS_PER_YEAR,
    }
    return Criterion("C5", rate >= ROUND_TRIPS_PER_YEAR, numbers)


def annualised_ratio(run: Run) -> tuple[Fraction, Fraction, Fraction]:
    """C6's ratio: the annualised return / max(drawdown, 0.1 points), as (low, value,
    high) over the annualised return's error bound. ``gate_ratio`` increases with the
    return, so the exact ratio lies in [low, high]."""
    value, bound = run.annualised
    drawdown = run.max_drawdown_pct
    return (
        gate_ratio(value - bound, drawdown),
        gate_ratio(value, drawdown),
        gate_ratio(value + bound, drawdown),
    )


def exceeds_exactly(run: Run, grid: Run) -> bool | None:
    """Whether ``run``'s exact annualised ratio exceeds always-grid's (``grid``'s), where
    their raw returns and floored drawdowns alone settle it; None where only the
    annualised values can, or where ``run``'s return is not above 0 or the two runs'
    days differ.

    Over the same days, annualising is non-decreasing in the return, and increasing above
    -100%. With ``run``'s return above 0, its annualised return is above 0, and above
    always-grid's whenever its raw return is above always-grid's. So its ratio is at most
    always-grid's when its return is at most always-grid's and its floored drawdown at
    least always-grid's, and above it when its return is at least always-grid's and its
    floored drawdown at most always-grid's, one of them strictly. An exact tie in both,
    which no error bound can settle, does not exceed."""
    if run.return_pct <= 0 or run.days != grid.days:
        return None
    drawdown = max(run.max_drawdown_pct, GATE_FLOOR_PCT)
    grid_drawdown = max(grid.max_drawdown_pct, GATE_FLOOR_PCT)
    if run.return_pct <= grid.return_pct and drawdown >= grid_drawdown:
        return False
    if run.return_pct >= grid.return_pct and drawdown <= grid_drawdown:
        return True
    return None


def earns_its_place(
    ms: Sequence[Run], always_grid: Mapping[tuple[str, str, str], Run]
) -> Criterion:
    """C6: in at least 60% of runs, the run beats cash, whose ratio is 0, and its
    annualised ratio exceeds always-grid's in the same window, pair and path
    (``always_grid`` by ``Run.key``).

    * Annualising keeps a return's sign, so a run beats cash only with a raw return above
      0, which is exact.
    * The comparison with always-grid is decided exactly where the two runs' raw returns
      and floored drawdowns order their ratios (``exceeds_exactly``), so an exact tie does
      not exceed. Otherwise it is decided with ``certain`` over the interval the two
      annualised returns' bounds give, and a comparison they cannot settle refuses the
      scoring, as C2's do.
    * A missing or invalid always-grid run cannot show that the run beats it, so it counts
      against. ``Run.ratio`` is raw, spec v1's C6, so it is not used."""
    failing = []
    for run in ms:
        grid = always_grid.get(run.key)
        if not run.return_pct > 0:
            failing.append(f"{run.label}: return {exact(run.return_pct)}% does not beat cash")
        elif grid is None:
            failing.append(f"{run.label}: no always-grid (F) run")
        elif grid.problems:
            failing.append(
                f"{run.label}: the always-grid (F) run is invalid: {'; '.join(grid.problems)}"
            )
        else:
            low, value, high = annualised_ratio(run)
            grid_low, grid_value, grid_high = annualised_ratio(grid)
            what = f"C6's comparison with always-grid in {run.label}"
            exceeds = exceeds_exactly(run, grid)
            if exceeds is None:
                exceeds = certain(positive, low - grid_high, high - grid_low, what)
            if not exceeds:
                failing.append(
                    f"{run.label}: annualised ratio {exact(written(value))} does not exceed "
                    f"always-grid's {exact(written(grid_value))}"
                )
    wins = len(ms) - len(failing)
    share = Fraction(wins, len(ms)) if ms else Fraction(0)
    numbers: dict[str, Figure] = {
        "runs beating always-grid and cash": f"{wins} of {len(ms)}",
        "share %": share * 100,
        "required %": str(GATE_SHARE * 100),
    }
    return Criterion("C6", bool(ms) and share >= GATE_SHARE, numbers, tuple(failing))


def criteria(
    ms: Sequence[Run], trips: Mapping[str, int], always_grid: Mapping[tuple[str, str, str], Run]
) -> tuple[Criterion, ...]:
    """C1-C6 over the mode switcher's included runs: C1-C4 are spec v1's own."""
    return (
        worst_drop(ms),
        makes_money(ms),
        safer_than_holding(ms),
        integrity(ms),
        activity_v2(ms, trips),
        earns_its_place(ms, always_grid),
    )


# Reported, not gating (section 8).


def month_of(moment_ms: int) -> str:
    """The UTC calendar month, YYYY-MM, of a moment in milliseconds."""
    return datetime.fromtimestamp(moment_ms // 1000, UTC).strftime("%Y-%m")


def upside_capture(row: dict[str, Any], first_month: str | None = None) -> Fraction | None:
    """Over the calendar months in which buy-and-hold's return is above 0, the sum of the
    run's monthly returns divided by the sum of buy-and-hold's; None when there is no
    such month. Returns are raw, from ``hourly_equity``, whose samples the run and
    buy-and-hold share (spec v1 P2).

    Month m runs from B(m), the first sample at or after its start, to B(m + 1). The first
    month starts from ``initial_quote`` for both, and the last ends at the two final
    values. A month with no sample of its own has a zero return, since its B is the next
    month's, and the movement across it falls in the month before. The first month is
    ``first_month``, the evaluation's, or else the first sample's: the two differ only
    when the evaluation's first month has no sample at all."""
    initial = Fraction(Decimal(row["initial_quote"]))
    starts: dict[str, tuple[Fraction, Fraction]] = {}
    previous = -1
    for moment, total, hold in row[HOURLY_EQUITY]:
        if count(moment) <= previous:
            raise ScoringError(f"{HOURLY_EQUITY} is not in time order at {moment}")
        previous = moment
        starts.setdefault(month_of(moment), (Fraction(Decimal(total)), Fraction(Decimal(hold))))
    months = sorted(starts)
    first = first_month or (months[0] if months else "")
    if months and months[0] < first:
        raise ScoringError(f"{HOURLY_EQUITY} has a sample in {months[0]}, before {first}")
    marks = [(initial, initial), *(starts[month] for month in months if month != first)]
    final = (
        Fraction(Decimal(row["final_total_equity"])),
        Fraction(Decimal(row[MODES][BUY_AND_HOLD_FINAL])),
    )
    run_sum = hold_sum = Fraction(0)
    for (run_start, hold_start), (run_end, hold_end) in zip(
        marks, [*marks[1:], final], strict=True
    ):
        if hold_end / hold_start - 1 > 0:
            run_sum += run_end / run_start - 1
            hold_sum += hold_end / hold_start - 1
    return run_sum / hold_sum if hold_sum else None


def readout_of(row: dict[str, Any], window: Window, first_month: str) -> Readout:
    """An MS row's readouts. The modes' times must sum to the window's length, so that
    each share of time is of the whole window."""
    modes = row[MODES]
    times = modes[TIME_MS]
    if not isinstance(times, dict) or not set(times) <= set(MODE_NAMES):
        raise ScoringError(f"{MODES}.{TIME_MS} is not a time for each of {', '.join(MODE_NAMES)}")
    time_ms = {mode: count(times.get(mode, 0)) for mode in MODE_NAMES}
    length = window.days * DAY_MS
    if sum(time_ms.values()) != length:
        raise ScoringError(
            f"the modes' times sum to {sum(time_ms.values())} ms, not {window.name}'s {length}"
        )
    initial = Fraction(Decimal(row["initial_quote"]))
    return Readout(
        uptrend_trades=count(modes[UPTREND_TRADES]),
        time_ms=time_ms,
        switches=count(modes[SWITCHES]),
        stops=count(modes[STOPS]),
        fades=count(modes[FADES]),
        buy_and_hold_return_pct=(Fraction(Decimal(modes[BUY_AND_HOLD_FINAL])) / initial - 1) * 100,
        upside_capture=upside_capture(row, first_month),
    )


# Reading the results.


def role_of(row: dict[str, Any]) -> str | None:
    """A row's part in spec v2's evaluation, from its strategy and variant together:
    "MS", the candidate; "F", always-grid for C6, only under spec v1's gated-grid
    strategy, as ``acceptance.variant_of`` reads it; "D", reported only; or None for the
    ungated V0 baseline, which every results file carries and which is ignored. Any other
    row is refused."""
    strategy, variant = row["strategy"], row.get("variant")
    if strategy == MODE_SWITCH_STRATEGY or variant == MODE_SWITCH:
        if (strategy, variant) != (MODE_SWITCH_STRATEGY, MODE_SWITCH):
            raise ScoringError(
                f"variant {variant!r} under strategy {strategy!r}: the mode switcher's rows "
                f"carry variant {MODE_SWITCH!r} with strategy {MODE_SWITCH_STRATEGY!r}"
            )
        return MODE_SWITCH
    v1 = variant_of(row)  # refuses a row that is not a spec v1 variant's
    if v1 is None or v1 in ROLES:
        return v1
    raise ScoringError(
        f"not a spec v2 row: variant {v1} (strategy {strategy!r}); spec v2 scores the mode "
        "switcher against F, and reports D (section 8)"
    )


def ms_fields(row: dict[str, Any]) -> None:
    """Refuse an MS row without a field this scorer reads (``MS_ROW_FIELDS``)."""
    missing = [name for name in MS_ROW_FIELDS if name not in row]
    if not missing:
        if not isinstance(row[MODES], dict):
            raise ScoringError(f"an MS row's {MODES} is not a mapping")
        missing = [f"{MODES}.{name}" for name in MODES_FIELDS if name not in row[MODES]]
    if missing:
        raise ScoringError(f"an MS row lacks {', '.join(missing)}")


def feature_problems_v2(document: dict[str, Any]) -> list[str]:
    """Section 2: the grid is V0's, on V0's features; no --structure run is registered."""
    version = document["feature_version"]
    if version != FEATURE_VERSION:
        return [f"features {version!r}: spec v2 runs V0's features, {FEATURE_VERSION!r}"]
    return []


def run_of(row: dict[str, Any], window: Window, general: tuple[str, ...]) -> Run:
    """A row's run, built as spec v1's ``runs_of`` builds one, without v1's C6 baseline:
    its problems are the row's own failures and its file's general ones (C4)."""
    return Run(
        window=window.name,
        symbol=row["symbol"],
        path=row["path_mode"],
        return_pct=return_pct(row),
        max_drawdown_pct=number(row["max_drawdown_pct"]),
        active_max_drawdown_pct=number(row["active_max_drawdown_pct"]),
        buy_and_hold_max_drawdown_pct=number(row["buy_and_hold_max_drawdown_pct"]),
        hard_drawdown_halts=count(row["hard_drawdown_halts"]),
        completed_cycles=count(row["completed_cycles"]),
        days=window.days,
        months=window.months,
        problems=(*result_failures([row]), *general),
        cycle_weeks=len(row.get("completed_cycles_by_week", {})),
        time_with_inventory_pct=number(row["time_with_inventory_pct"]),
    )


def matrix_gaps(
    windows: Mapping[str, Window], found: Mapping[str, Mapping[tuple[str, str, str], Run]]
) -> list[str]:
    """Why the inputs are not every window's whole matrix: [] when they are."""
    gaps = []
    for name in (*SCORED, *REPORTED):
        window = windows.get(name)
        if window is None:
            gaps.append(f"{name} is not in the inputs")
            continue
        for role in ROLES:
            gaps += [
                f"{role} {name} {pair} {path}: missing"
                for pair in window.included
                for path in PATH_MODES
                if (name, pair, path) not in found[role]
            ]
    return gaps


def score_window(
    window: Window,
    found: Mapping[str, Mapping[tuple[str, str, str], Run]],
    trips: Mapping[str, int],
) -> WindowScore:
    keys = [(window.name, pair, path) for pair in window.included for path in PATH_MODES]
    ms = [found[MODE_SWITCH][key] for key in keys]
    return WindowScore(
        window=window,
        scored=window.name in SCORED,
        ms=tuple(ms),
        always_grid=tuple(found["F"][key] for key in keys),
        benchmark=tuple(found["D"][key] for key in keys),
        criteria=criteria(ms, trips, found["F"]),
        r1=economics(ms),
    )


def assess(sources: Sequence[Source], specs: Mapping[str, DatasetSpec]) -> Verdict:
    """Score ``sources`` with the dataset ``specs`` they ran on (``read_frozen``). The
    input checks are spec v1's ``assess``'s, and the inputs must be every window's whole
    matrix."""
    windows: dict[str, Window] = {}
    found: dict[str, dict[tuple[str, str, str], Run]] = {role: {} for role in ROLES}
    seen: set[tuple[str, ...]] = set()
    trips: dict[str, int] = {}
    readouts: dict[str, Readout] = {}
    problems: list[str] = []
    for source in sources:
        try:
            document = source.document
            checks = [*document_problems(document), *feature_problems_v2(document)]
            problems += [f"{source.path}: {problem}" for problem in checks]
            spec = specs[source.dataset]
            window = window_of(spec, document["hourly_cross_checks"])
            if windows.setdefault(window.name, window) != window:
                raise ScoringError(f"its comparison mask differs from another {window.name} run's")
            rows = document["results"]
            # A failure of the whole file is in its failures without belonging to a row,
            # and invalidates every row (spec v1's runs_of).
            of_rows = set(result_failures(rows))
            general = tuple(f for f in document["failures"] if f not in of_rows)
            for row in rows:
                key = (window.name, row["symbol"], row["path_mode"])
                if row["symbol"] not in window.pairs or row["path_mode"] not in PATH_MODES:
                    raise ScoringError(f"{window.name} has no pair and path {' '.join(key[1:])}")
                role = role_of(row)
                if role is None:
                    continue
                if role == MODE_SWITCH:
                    ms_fields(row)
                # One row per role, window, pair and path, even where the mask excludes
                # the pair, so that overlapping files cannot overweight a pair.
                if (role, *key) in seen:
                    raise ScoringError(
                        f"{role} {' '.join(key)} has more than one row in the inputs"
                    )
                seen.add((role, *key))
                if row["symbol"] in window.excluded:
                    continue
                run = run_of(row, window, general)
                found[role][key] = run
                if role == MODE_SWITCH:
                    trips[run.label] = round_trips(row)
                    readouts[run.label] = readout_of(row, window, spec.start)
        except ScoringError as exc:
            problems.append(f"{source.path}: {exc}")
        except (KeyError, TypeError, AttributeError, ArithmeticError, ValueError) as exc:
            problems.append(f"{source.path}: malformed results ({type(exc).__name__} {exc})")
    if problems:
        raise ScoringError("\n".join(dict.fromkeys(problems)))
    gaps = matrix_gaps(windows, found)
    if gaps:
        raise ScoringError("\n".join([WHOLE_MATRIX, *gaps]))
    scores = tuple(score_window(windows[name], found, trips) for name in (*SCORED, *REPORTED))
    scored = [score for score in scores if score.scored]
    # Spec v1 section 5's minimum evidence, carried over by spec v2 section 2.
    thin = thin_windows([score.window for score in scored])
    if thin:
        outcome, reasons = "insufficient evidence", tuple(thin)
    elif all(score.passed for score in scored):
        outcome, reasons = "pass", (ACCEPTED_NOTE,)
    else:
        outcome = "fail"
        reasons = tuple(
            f"{score.window.name}: {c.name} fails"
            for score in scored
            for c in score.criteria
            if not c.passed
        )
    return Verdict(tuple(sources), scores, trips, readouts, outcome, reasons)


def registration_problems(name: str, spec: DatasetSpec) -> list[str]:
    """Why a committed spec is not the window section 8 registers under ``name``: its
    months, warm-ups and pairs, and the evaluation length ``evaluation_window`` gives."""
    registered = REGISTRATIONS[name]
    committed = Registration(
        spec.daily_warmup_start, spec.warmup_start, spec.start, spec.end, tuple(sorted(spec.traded))
    )
    problems = [
        f"{name}: the committed spec's {field} is {value!r}; spec v2 registers {expected!r}"
        for field, value, expected in zip(Registration._fields, committed, registered, strict=True)
        if value != expected
    ]
    days = evaluation_window(spec)[0]
    if days != REGISTERED_DAYS[name]:
        problems.append(
            f"{name}: the committed spec's evaluation window is {days} days; spec v2 section 8 "
            f"registers {REGISTERED_DAYS[name]}"
        )
    return problems


def read_frozen(sources: Sequence[Source], scorer: Mapping[str, str]) -> dict[str, DatasetSpec]:
    """Check every run against the frozen inputs, and return each window's dataset spec.

    As spec v1's ``read_frozen``: the runs must come from the code that scores them
    (``code_problems``), and the default config and each window's dataset spec and
    manifest, as committed beside this code, must hash to what every run recorded. The
    windows are spec v2's, ``SCORED`` and ``REPORTED``: an input from another window is
    refused, every one of them must have its spec and manifest committed, and each spec
    must be the window section 8 registers (``registration_problems``)."""
    problems = code_problems(sources, scorer)
    registered = (*SCORED, *REPORTED)
    specs = {}
    try:
        configs = {str(s.document["config_sha256"]) for s in sources}
        problems += pinned(ACCEPTANCE_CONFIG, configs, "config")
        problems += [
            f"{name!r} is not a spec v2 window ({', '.join(registered)})"
            for name in sorted({s.dataset for s in sources} - set(registered))
        ]
        for name in registered:
            spec_path = DATASET_SPECS / f"{name}.toml"
            manifest = DATASET_SPECS / f"{name}.manifest.json"
            absent = [committed_name(file) for file in (spec_path, manifest) if not file.is_file()]
            if absent:
                problems.append(
                    f"{name}: no committed {' or '.join(absent)}, so its runs cannot be "
                    "pinned; full-range-2017-2024's come with the long-window data PR (spec v2 "
                    "section 9, step 2)"
                )
                continue
            runs = [s.document for s in sources if s.dataset == name]
            if not runs:
                continue  # the matrix check names the missing window
            spec_problems = pinned(
                spec_path, {str(r["spec_sha256"]) for r in runs}, f"{name}: spec"
            )
            problems += spec_problems
            manifests = {str(r["manifest_sha256"]) for r in runs}
            problems += pinned(manifest, manifests, f"{name}: manifest")
            if not spec_problems:
                specs[name] = load_spec(spec_path)
                problems += registration_problems(name, specs[name])
    except (OSError, KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ScoringError(f"cannot check the frozen inputs ({type(exc).__name__} {exc})") from exc
    if problems:
        raise ScoringError("\n".join([*problems, FROZEN_HINT]))
    return specs


# Output.


def run_figures(run: Run) -> dict[str, Any]:
    """A run as spec v1's verdict writes it, without v1's C5 rate and C6 baseline, and
    with C6's annualised ratio."""
    figures = {key: value for key, value in run_json(run).items() if key not in V1_ONLY}
    return {**figures, "annualised_gate_ratio": exact(written(annualised_ratio(run)[1]))}


def ms_run_json(
    run: Run, verdict: Verdict, always_grid: Mapping[tuple[str, str, str], Run]
) -> dict[str, Any]:
    readout, trips = verdict.readouts[run.label], verdict.trips[run.label]
    grid = always_grid.get(run.key)
    length = run.days * DAY_MS
    return {
        **run_figures(run),
        "always_grid_annualised_gate_ratio": (
            exact(written(annualised_ratio(grid)[1])) if grid is not None else None
        ),
        "round_trips": trips,
        "round_trips_per_year": exact(Fraction(trips) * YEAR_DAYS / run.days),
        "round_trips_by_mode": {"grid": run.completed_cycles, "uptrend": readout.uptrend_trades},
        "time_in_mode_pct": {
            mode: exact(Fraction(100 * time, length)) for mode, time in readout.time_ms.items()
        },
        "mode_switches": readout.switches,
        "uptrend_stops": readout.stops,
        "uptrend_fades": readout.fades,
        "buy_and_hold_return_pct": exact(readout.buy_and_hold_return_pct),
        "upside_capture": as_json(readout.upside_capture),
    }


def means(runs: Sequence[Run]) -> dict[str, str | None]:
    """The mean raw return, annualised return and max drawdown, equal weight."""
    if not runs:
        return dict.fromkeys(
            ("mean_return_pct", "mean_annualised_return_pct", "mean_max_drawdown_pct")
        )
    return {
        "mean_return_pct": exact(mean([run.return_pct for run in runs])),
        "mean_annualised_return_pct": exact(written(mean([run.annualised.value for run in runs]))),
        "mean_max_drawdown_pct": exact(mean([run.max_drawdown_pct for run in runs])),
    }


def window_score_json(score: WindowScore, verdict: Verdict) -> dict[str, Any]:
    grid = {run.key: run for run in score.always_grid}
    return {
        "scored": score.scored,  # False: run and reported, deciding nothing
        "passed": score.passed,
        "criteria": {
            c.name: {
                "passed": c.passed,
                "numbers": {name: as_json(value) for name, value in c.numbers.items()},
                "failing": list(c.failing),
            }
            for c in score.criteria
        },
        "r1_reported_only": {name: as_json(value) for name, value in score.r1.items()},
        **means(score.ms),
        "runs": [ms_run_json(run, verdict, grid) for run in score.ms],
        "always_grid": {
            **means(score.always_grid),
            "runs": [run_figures(r) for r in score.always_grid],
        },
        "benchmark_d": {
            **means(score.benchmark),
            "runs": [run_figures(r) for r in score.benchmark],
        },
    }


def verdict_json(verdict: Verdict) -> dict[str, Any]:
    """The verdict and every figure behind it, numbers as spec v1's verdict writes them."""
    return {
        "scoring": SCORING,
        "candidate": MODE_SWITCH_STRATEGY,
        "numbers": NUMBERS_NOTE,
        "primary": {name: str(value) for name, value in PRIMARY.items()},
        "engine_version": ENGINE_VERSION,
        "integrity_rules": INTEGRITY_RULES,
        "inputs": [
            {
                "path": str(s.path),
                "sha256": s.sha256,
                **{key: s.document.get(key) for key in INPUT_FIELDS},
            }
            for s in verdict.sources
        ],
        "comparison_mask": {s.window.name: window_json(s.window) for s in verdict.windows},
        "windows": {s.window.name: window_score_json(s, verdict) for s in verdict.windows},
        "outcome": verdict.outcome,
        "reasons": list(verdict.reasons),
        "c7": C7_NOTE,
    }


def window_lines(score: WindowScore, verdict: Verdict) -> list[str]:
    """One window of the readable verdict."""
    rule = (
        "scored: the mode switcher passes only if C1-C6 all pass; R1 is reported only"
        if score.scored
        else "reported only; it decides nothing (spec v2 section 8)"
    )
    lines = [
        "",
        f"{score.window.name}: {rule}",
        f"Mode switcher: {len(score.ms)} included runs, {'PASS' if score.passed else 'FAIL'}",
    ]
    for c in score.criteria:
        figures = "; ".join(f"{name} {shown(value)}" for name, value in c.numbers.items())
        lines.append(f"- {c.name} {'pass' if c.passed else 'FAIL'}: {figures}")
        lines += [f"    {item}" for item in c.failing]
    lines.append(
        "- R1 (reported only): " + "; ".join(f"{k} {shown(v)}" for k, v in score.r1.items())
    )
    lines.append("| Runs | Mean annualised % | Mean return % | Mean max DD % |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name, runs in (
        ("mode switcher", score.ms),
        ("always-grid (F)", score.always_grid),
        ("D (reported only)", score.benchmark),
    ):
        averages = [
            mean([run.annualised.value for run in runs]) if runs else None,
            mean([run.return_pct for run in runs]) if runs else None,
            mean([run.max_drawdown_pct for run in runs]) if runs else None,
        ]
        lines.append(f"| {name} | " + " | ".join(shown(value) for value in averages) + " |")
    lines.append(
        "| Run | Round trips (grid + uptrend) | Time cash / grid / uptrend % | Switches | "
        "Stops | Fades | Buy-and-hold % | Upside capture |"
    )
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for run in score.ms:
        readout = verdict.readouts[run.label]
        length = run.days * DAY_MS
        shares = " / ".join(shown(Fraction(100 * readout.time_ms[m], length)) for m in MODE_NAMES)
        lines.append(
            f"| {run.label} | {run.completed_cycles} + {readout.uptrend_trades} | {shares} | "
            f"{readout.switches} | {readout.stops} | {readout.fades} | "
            f"{shown(readout.buy_and_hold_return_pct)} | {shown(readout.upside_capture)} |"
        )
    return lines


def render(verdict: Verdict) -> str:
    """The verdict as readable text (ASCII, so any console prints it)."""
    lines = [
        f"Spec v2 scoring {SCORING}: the mode switcher against always-grid (variant F) and "
        f"cash; primary fees maker {PRIMARY['maker fee']} / taker {PRIMARY['taker fee']}, "
        f"engine {ENGINE_VERSION}, integrity rules {INTEGRITY_RULES}",
        f"Inputs: {len(verdict.sources)} results files (paths and SHA-256 in the JSON verdict)",
        "",
        "Comparison mask (spec v1 section 5, carried over by spec v2 section 2)",
        "| Window | Pair | Included | Reasons |",
        "| --- | --- | --- | --- |",
    ]
    for score in verdict.windows:
        for pair in score.window.pairs:
            reasons = score.window.excluded.get(pair, ())
            lines.append(
                f"| {score.window.name} | {pair} | {'no' if reasons else 'yes'} | "
                f"{'; '.join(reasons)} |"
            )
    for score in verdict.windows:
        lines += window_lines(score, verdict)
    lines += ["", f"Outcome (spec v2 section 8): {verdict.outcome}"]
    lines += [f"- {reason}" for reason in verdict.reasons]
    lines.append(C7_NOTE)
    return "\n".join(lines)


def unscored(outcome: str, reasons: Sequence[str]) -> dict[str, Any]:
    """The verdict of a run that scored nothing."""
    return {"scoring": SCORING, "outcome": outcome, "reasons": list(reasons)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m crypto_grid_bot.backtest.acceptance_v2",
        description="Score the mode switcher's backtest results against spec v2 section 8 "
        "(C1-C6, with the reported readouts).",
    )
    parser.add_argument(
        "results", type=Path, nargs="+", help="run directories, or their results.json files"
    )
    parser.add_argument("--out", type=Path, required=True, help="where to write the JSON verdict")
    args = parser.parse_args(argv)
    if args.out.resolve() in {
        (p / "results.json" if p.is_dir() else p).resolve() for p in args.results
    }:
        parser.error("--out must not be one of the results files it scores")
    # The code that scores, as the backtest CLI records the code that ran.
    scorer = {"code_commit": code_commit(), "code_sha256": SOURCE_IDENTITY}
    # Until this run's own verdict replaces it, --out says that nothing was scored, so a
    # refused, interrupted or failed run never leaves an earlier verdict in its place.
    write_verdict(
        args.out, {"scorer": scorer, **unscored("not scored", ["scoring did not finish"])}
    )
    try:
        sources = [read_results(path) for path in args.results]
        verdict = assess(sources, read_frozen(sources, scorer))
    except ScoringError as exc:
        write_verdict(args.out, {"scorer": scorer, **unscored("refused", str(exc).splitlines())})
        print(f"Refused; nothing was scored:\n{exc}", file=sys.stderr)
        return 2
    write_verdict(args.out, {"scorer": scorer, **verdict_json(verdict)})
    print(render(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
