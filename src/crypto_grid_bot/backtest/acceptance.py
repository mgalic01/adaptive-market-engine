"""The acceptance scorer: experiment spec v1 section 6 over the results a replay wrote.

    python -m crypto_grid_bot.backtest.acceptance --early-read RUN [RUN ...] --out read.json
    python -m crypto_grid_bot.backtest.acceptance --final RUN [RUN ...] --out verdict.json

Each RUN is a run directory (``data/backtests/<dataset>/<stamp>/``) or its
``results.json``. The section 4 matrix runs in two stages (section 6, "Two stages"):

* ``--early-read`` scores stage 1, ``verify-2024h1`` and ``practice-2022``. Every
  section 4 variant is judged against C1-C6 over its included runs there (every included
  pair, window and intrabar path), and R1 is reported. It says which variants pass stage
  1 and names no winner.
* ``--final`` scores both stages: stage 1 as above, stage 2 on ``full-range-2017-2024``
  judged on its own, and ``full-range-2019-2024`` for the report only (section 5, rule
  6). A variant is eligible only if it passes C1-C6 in stage 1 and in stage 2, and the
  deterministic selection ranks the eligible variants on 2017-2024. It refuses unless
  both stages' matrices are complete.

C2 and the selection judge compound-annualised returns, ``(final / initial) ** (365.25
/ d) - 1`` with ``d`` C5's window length in days; raw returns are reported beside them.
A readable table is printed, and the verdict with every figure behind it is written as
JSON.

It runs no backtest and reads no market data: only the results files, and the dataset
specs, manifests and default config committed beside this code, which must hash to the
``spec_sha256``, ``manifest_sha256`` and ``config_sha256`` each run recorded. Every run
must also come from this code's own clean commit (``code_commit``, ``code_sha256``).
Arithmetic is exact (``Fraction``): returns come from the recorded equities, and
drawdowns are read exactly as the results wrote them. An annualised return is exact
where it is rational; otherwise it is computed with a certified error bound, and a
decision that bound cannot settle refuses (``annualise``, ``certain``).

It fails closed and skips nothing:

* an input that is not an acceptance run (another code, engine, features, integrity
  rules, config, fee or sensitivity setting, an unknown variant or window, a duplicate
  run, a changed or uncommitted dataset spec or manifest) is refused: nothing is scored,
  and the verdict file says so;
* an invalid run fails its variant's C4 (section 5), and so does a run missing from the
  matrix, which also stops the early read's list and refuses the final verdict;
* a pair-window the comparison mask excludes (section 5) is excluded for every variant
  alike and listed with its reasons.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from typing import Any, NamedTuple

from crypto_grid_bot.backtest.__main__ import (
    checked_symbols,
    code_commit,
    integrity_failures,
    result_failures,
)
from crypto_grid_bot.backtest.dataset import DatasetSpec, _write_atomic, load_spec
from crypto_grid_bot.backtest.features import FEATURE_VERSION, STRUCTURE_FEATURE_VERSION
from crypto_grid_bot.backtest.jobs import SOURCE_IDENTITY
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.replay import DAY_MS, ENGINE_VERSION, INTEGRITY_RULES, PATH_MODES
from crypto_grid_bot.backtest.trend_benchmark import STRATEGY as BENCHMARK_STRATEGY

# The name of these scoring rules, recorded in every verdict. Section 7 freezes the
# scoring before the reserved window, so a change to them gets a new name: the test-plan
# amendment of 2026-10-05 (amendment 4) added V2, the full stack, annualised returns and
# the two stages.
SCORING = "spec-v1-section-6-amendment-4"
# Sections 4 and 6: acceptance is judged at the primary fees with section 4's unchanged
# inputs and capital. A run with any other value (a fee scenario, a D9 or D10 sweep) is
# reported only, never used for acceptance, so it is refused here.
PRIMARY = {
    "maker fee": Decimal("0"),
    "taker fee": Decimal("0.0009"),
    "slippage": Decimal("0.0005"),
    "participation": Decimal("0.10"),
    "assumed spread %": Decimal("0.05"),
    "capital": Decimal("100"),
}


@dataclass(frozen=True)
class Stage:
    """Windows whose included runs are judged together against C1-C6 (section 6, "Two
    stages"). A stage that is not scored is run and reported, and decides nothing."""

    name: str
    windows: tuple[str, ...]
    scored: bool = True


# Section 4 and section 6, "Two stages". Stage 1 is the early read. Stage 2 judges
# full-range-2017-2024 on its own; full-range-2019-2024 is run and reported only, since
# its evaluation lies inside 2017-2024's (section 5, rule 6).
STAGE_1 = Stage("stage 1", ("verify-2024h1", "practice-2022"))
STAGE_2 = Stage("stage 2", ("full-range-2017-2024",))
REPORTED = Stage("stage 2, reported only", ("full-range-2019-2024",), scored=False)
INVOCATIONS = {"early read": (STAGE_1,), "final": (STAGE_1, STAGE_2, REPORTED)}
# Section 6, "Annualised returns": each window's C5 length in days, annualisation's d. A
# committed dataset spec with another evaluation window is not the registered window.
REGISTERED_DAYS = {
    "verify-2024h1": 182,
    "practice-2022": 245,
    "full-range-2017-2024": 2192,
    "full-range-2019-2024": 2011,
}
EARLY_READ_NOTE = (
    "stage 1 is an early read and names no winner: a variant must also pass C1-C6 in "
    "stage 2, and the winner is ranked on full-range-2017-2024 (spec v1 section 6, 'Two "
    "stages')"
)
# Section 4: the variants. Section 6 step 4: the simplicity order of the selectable
# ones; D is a benchmark that cannot be selected (step 5). V2 and the full stack were
# registered on 2026-10-05, with V2 after E and the full stack last.
VARIANTS = ("V0", "A", "B", "C", "D", "E", "F", "G", "C+G", "H", "C+H", "V2", "C+F+G+H+V2")
SIMPLICITY_ORDER = ("V0", "A", "B", "F", "G", "H", "E", "V2", "C", "C+G", "C+H", "C+F+G+H+V2")
# The variant field of a gated row run without the V2 structure features (V0's has none).
GRID_VARIANTS = ("A", "B", "C", "E", "F", "G", "C+G", "H", "C+H")
# Section 3, V2 and the full stack: the only registered --structure runs, by the variant
# field of their rows. V2 is V0 with --structure, so its rows carry none, as V0's do; the
# full stack's carry C+F+G+H. Every other --structure row is refused.
STRUCTURE_VARIANTS = {None: "V2", "C+F+G+H": "C+F+G+H+V2"}
# Section 3 E and section 6 step 1: E is run and reported but not eligible until Codex
# has reviewed its implementation and boundary tests. Change this only in the PR that
# records that review.
E_ELIGIBLE = False
# Sections 5 and 2 (P4), the filter-availability check: no dated historical filters were
# found, so every practice-2022 SOLUSDT pair-window fails it, for every variant alike.
FILTER_EXCLUSIONS = {
    ("practice-2022", "SOLUSDT"): "no sourced historical exchange filters (spec v1 P4, section 5)",
}
MINIMUM_PAIRS = 2  # section 5: the included pairs each scored window must keep
DRAWDOWN_LIMIT_PCT = Fraction(10)  # C1
GATE_FLOOR_PCT = Fraction(1, 10)  # C6: max(max drawdown, 0.1 percentage points)
GATE_SHARE = Fraction(3, 5)  # C6: at least 60% of included runs
SELECTION_PLACES = 6  # selection steps 2 and 3: percentage points rounded to 6 decimals
TIE_MARGIN_PCT = Decimal("0.25")  # selection step 2
YEAR_DAYS = Fraction(1461, 4)  # section 6, "Annualised returns": a 365.25-day year
ANNUALISING_DIGITS = 60  # significant digits of an irrational annualised return
ANNUALISED_PLACES = 20  # the decimals the verdict writes an annualised figure with
HOSTING_EUR = 5  # R1: euros of hosting per month
R1_CAPITAL = f"capital for EUR {HOSTING_EUR}/month"
BASELINE = "ungated grid baseline"  # the ungated V0 rows, the C6 baseline
GRID = f"gated grid ({FEATURE_VERSION})"
STRUCTURE_GRID = f"gated grid ({STRUCTURE_FEATURE_VERSION})"  # V2 and the full stack
C7_NOTE = (
    "C7 not evaluated: it is not yet settled (spec v1 section 6). It selects nothing, and "
    "the reserved window stays closed until it is settled and passed, or waived."
)
NUMBERS_NOTE = (
    "exact: a decimal where it terminates, otherwise p/q; Fraction(text) reads both. An "
    f"irrational annualised return is written to {ANNUALISED_PLACES} decimals, from a "
    "computation whose error bound certifies every decision on it"
)
# The frozen acceptance inputs (sections 3 and 7): this code itself, and the dataset specs,
# manifests and default config committed beside it. Every run must have recorded their
# identities, and no command-line path can replace them with tuned copies.
REPOSITORY = Path(__file__).resolve().parents[3]
DATASET_SPECS = REPOSITORY / "config" / "datasets"
ACCEPTANCE_CONFIG = REPOSITORY / "config" / "default.toml"
# A clean commit as the backtest CLI records it: no "+dirty" and not "unknown".
_CLEAN_COMMIT = re.compile(r"[0-9a-f]{40}")
FROZEN_HINT = (
    "Run the whole batch with --record-commit from one clean checkout of the frozen "
    "commit, and score it from that same checkout."
)

Figure = Fraction | int | str


class ScoringError(Exception):
    """The inputs cannot be scored as acceptance runs; nothing is scored."""


@dataclass(frozen=True)
class Source:
    """One results.json as read: its path, its SHA-256 and its contents."""

    path: Path
    sha256: str
    document: dict[str, Any]

    @property
    def dataset(self) -> str:
        return str(self.document["dataset"])


@dataclass(frozen=True)
class Window:
    """One dataset of the matrix: its spec's traded pairs, the comparison mask over them
    (section 5) and the evaluation window that C5, annualisation and R1 divide by."""

    name: str
    pairs: tuple[str, ...]
    excluded: Mapping[str, tuple[str, ...]]  # each excluded pair and why
    days: int  # C5 and annualisation: [start of the start month, end of the end month)
    months: int  # R1: the calendar months of that window

    @property
    def included(self) -> tuple[str, ...]:
        return tuple(pair for pair in self.pairs if pair not in self.excluded)


class Annualised(NamedTuple):
    """A compound-annualised return in percent (section 6, "Annualised returns"): within
    ``bound`` of ``value``, and exactly ``value`` when ``bound`` is 0."""

    value: Fraction
    bound: Fraction


@dataclass(frozen=True)
class Run:
    """One variant's run in one included pair, window and path, with exact figures."""

    window: str
    symbol: str
    path: str
    return_pct: Fraction  # raw: C6, R1 and the report
    max_drawdown_pct: Fraction  # total equity: C1(a), C3, C6 and the selection
    active_max_drawdown_pct: Fraction  # against the C1(b) measurement reference
    buy_and_hold_max_drawdown_pct: Fraction  # C3
    hard_drawdown_halts: int  # C1
    completed_cycles: int  # C5 (P7)
    days: int  # the window's C5 length, annualisation's d
    months: int  # the window's R1 length
    problems: tuple[str, ...] = ()  # C4: why the run is invalid; empty when valid
    # C6: the ungated V0 baseline's ratio in the same pair, window and path, or None with
    # the reason the comparison is unavailable.
    baseline: Fraction | None = None
    baseline_problem: str = ""
    cycle_weeks: int = 0  # ISO weeks with a completed cycle: reported, not scored
    time_with_inventory_pct: Fraction = Fraction(0)  # reported, not scored
    # C2 and the selection: the return annualised over ``days``. Computed as the run is
    # made, so a result it cannot use is refused with its file.
    annualised: Annualised = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "annualised", annualise(self.return_pct, self.days))

    @property
    def key(self) -> tuple[str, str, str]:
        return self.window, self.symbol, self.path

    @property
    def label(self) -> str:
        return " ".join(self.key)

    @property
    def ratio(self) -> Fraction:
        return gate_ratio(self.return_pct, self.max_drawdown_pct)

    @property
    def cycle_rate(self) -> Fraction:
        """C5: completed cycles / (window days / 7), exactly."""
        return Fraction(7 * self.completed_cycles, self.days)


@dataclass(frozen=True)
class Criterion:
    """One criterion's verdict and the figures behind it."""

    name: str
    passed: bool
    numbers: dict[str, Figure]
    failing: tuple[str, ...] = ()  # the runs that fail it, and why


@dataclass(frozen=True)
class VariantScore:
    variant: str
    runs: tuple[Run, ...]
    missing: tuple[str, ...]
    criteria: tuple[Criterion, ...]
    r1: dict[str, Figure]

    @property
    def passed(self) -> bool:
        return all(criterion.passed for criterion in self.criteria)

    # The means need runs; a variant that passes always has them.
    @property
    def mean_return_pct(self) -> Fraction:
        """The mean raw return, equal weight: reported, not scored."""
        return mean([run.return_pct for run in self.runs])

    @property
    def mean_annualised_pct(self) -> Fraction:
        """The mean annualised return as computed, equal weight (C2, selection step 2,
        which certifies its rounding: ``ranked_return``)."""
        return mean([run.annualised.value for run in self.runs])

    @property
    def mean_drawdown_pct(self) -> Fraction:
        """Mean total-equity max drawdown, equal weight (selection step 3)."""
        return mean([run.max_drawdown_pct for run in self.runs])


@dataclass(frozen=True)
class StageScores:
    """One stage's windows in the inputs, each variant's verdict over their included
    runs, and why the inputs are not the stage's whole matrix."""

    stage: Stage
    windows: tuple[Window, ...]
    scores: tuple[VariantScore, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    # Early read: "early read", "insufficient evidence" or "incomplete matrix". Final:
    # "winner", "no winner" or "insufficient evidence" (an incomplete matrix refuses).
    outcome: str
    winner: str | None = None
    reasons: tuple[str, ...] = ()
    # The variants that pass C1-C6 in every scored stage of the invocation: stage 1 for
    # the early read, stage 1 and stage 2 for the final. Empty unless the matrix is whole
    # and its evidence sufficient.
    qualified: tuple[str, ...] = ()
    tie_set: tuple[str, ...] = ()
    # Each eligible variant's mean annualised return and mean max drawdown on the ranking
    # window, in percentage points rounded to 6 decimals, in the simplicity order.
    figures: Mapping[str, tuple[Decimal, Decimal]] = field(default_factory=dict)


@dataclass(frozen=True)
class Verdict:
    invocation: str  # "early read" or "final"
    sources: tuple[Source, ...]
    windows: tuple[Window, ...]  # every window in the inputs: the comparison mask
    stages: tuple[StageScores, ...]
    selection: Selection


# Arithmetic and formatting.


def mean(values: Sequence[Fraction]) -> Fraction:
    return sum(values, Fraction(0)) / len(values)


def median(values: Sequence[Fraction]) -> Fraction:
    """C2: the median of an even count is the mean of the two middle values."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def gate_ratio(return_pct: Fraction, drawdown_pct: Fraction) -> Fraction:
    """C6: return / max(max drawdown, 0.1 percentage points)."""
    return return_pct / max(drawdown_pct, GATE_FLOOR_PCT)


def integer_root(number: int, degree: int) -> int:
    """The largest integer whose ``degree``-th power is at most ``number`` (>= 0), by
    Newton's method in integers from above."""
    if number < 2:
        return number
    root = 1 << -(-number.bit_length() // degree)
    while (lower := ((degree - 1) * root + number // root ** (degree - 1)) // degree) < root:
        root = lower
    return root


def annualise(return_pct: Fraction, days: int) -> Annualised:
    """Section 6: ``(final / initial) ** (365.25 / days) - 1`` in percent, where final /
    initial is 1 + ``return_pct`` / 100 and ``days`` is C5's window length.

    * A final equity of 0 or less annualises to -100%: the power is undefined there.
    * The power is exact where it is rational, which is when the ratio's numerator and
      denominator are perfect powers of the exponent's denominator. In the registered
      windows (d = 182, 245, 2192 and 2011, so that denominator is at least 728) that
      happens only at a zero return.
    * Otherwise it is irrational, and computed in Decimal as ``exp(ln(ratio) *
      exponent)``: every step rounded half-even at ``ANNUALISING_DIGITS`` significant
      digits, ``ln`` and ``exp`` correctly so (the decimal module guarantees both), with
      more digits as the ratio nears 1 so that its distance from 1 keeps them all. With
      P digits, the five rounded steps (ratio, logarithm, exponent, product and
      exponential) leave the computed power Y within 1.55e(1 - P) * Y * (|Z| + e + 1) of
      the exact one, where Z is the computed product and e the exponent. ``bound`` is
      1e(3 - P) * Y * (|Z| + ceil(e) + 1), over 60 times that.

    The computation is deterministic, and C2 and the selection decide only what the
    bound settles (``certain``)."""
    ratio = 1 + return_pct / 100
    if ratio <= 0:
        return Annualised(Fraction(-100), Fraction(0))
    exponent = YEAR_DAYS / days
    degree = exponent.denominator
    roots = (integer_root(ratio.numerator, degree), integer_root(ratio.denominator, degree))
    if roots[0] ** degree == ratio.numerator and roots[1] ** degree == ratio.denominator:
        return Annualised((Fraction(*roots) ** exponent.numerator - 1) * 100, Fraction(0))
    change = abs(ratio - 1)
    # Decimal places of |ratio - 1| before its first digit, over-estimated from bit
    # lengths (0.31 > log10(2)) so that no large number is ever written out.
    zeros = (change.denominator.bit_length() - change.numerator.bit_length()) * 31 // 100 + 2
    digits = ANNUALISING_DIGITS + max(0, zeros)
    with localcontext(Context(prec=digits, rounding=ROUND_HALF_EVEN)):
        power = (Decimal(ratio.numerator) / ratio.denominator).ln() * (
            Decimal(exponent.numerator) / exponent.denominator
        )
        grown = Fraction(power.exp())
    bound = grown * (abs(Fraction(power)) + math.ceil(exponent) + 1) / 10 ** (digits - 3)
    return Annualised((grown - 1) * 100, bound * 100)


def enclosure(
    statistic: Callable[[Sequence[Fraction]], Fraction], figures: Sequence[Annualised]
) -> tuple[Fraction, Fraction, Fraction]:
    """``statistic`` (``mean`` or ``median``) of annualised returns: (low, value, high),
    over the figures' lower ends, values and upper ends. Both statistics are
    non-decreasing in every figure, so the exact statistic lies in [low, high]."""
    return (
        statistic([figure.value - figure.bound for figure in figures]),
        statistic([figure.value for figure in figures]),
        statistic([figure.value + figure.bound for figure in figures]),
    )


def certain[T](decide: Callable[[Fraction], T], low: Fraction, high: Fraction, what: str) -> T:
    """``decide`` for a figure known only to lie in [low, high]. ``decide`` is
    non-decreasing (a threshold or a rounding), so the same at both ends it is the
    decision for the exact figure. If the ends differ, nothing is scored, rather than a
    guess."""
    decision = decide(low)
    if decide(high) != decision:
        raise ScoringError(
            f"{what} cannot be decided: the exact value lies in [{exact(low)}, {exact(high)}], "
            f"across a decision boundary at {ANNUALISING_DIGITS} digits (spec v1 section 6, "
            "'Annualised returns')"
        )
    return decision


def positive(value: Fraction) -> bool:
    return value > 0


def rounded(value: Fraction, places: int) -> Decimal:
    """``value`` rounded exactly to ``places`` decimals, half away from zero. The Decimal
    is built from text, which keeps every digit; arithmetic would round to the context's
    28 digits, and a recorded equity can have more."""
    scaled = abs(value) * 10**places
    whole, rest = divmod(scaled.numerator, scaled.denominator)
    if 2 * rest >= scaled.denominator:
        whole += 1
    sign = "-" if value < 0 and whole else ""
    return Decimal(f"{sign}{whole}e-{places}")


def written(value: Fraction) -> Fraction:
    """An annualised figure as the verdict writes it: rounded to ``ANNUALISED_PLACES``."""
    return Fraction(rounded(value, ANNUALISED_PLACES))


def exact(value: Fraction) -> str:
    """``value`` exactly: a decimal where it terminates, otherwise ``p/q``.
    ``Fraction(text)`` reads both."""
    rest, twos, fives = value.denominator, 0, 0
    while rest % 2 == 0:
        rest, twos = rest // 2, twos + 1
    while rest % 5 == 0:
        rest, fives = rest // 5, fives + 1
    if rest != 1:
        return f"{value.numerator}/{value.denominator}"
    return format(rounded(value, max(twos, fives)), "f")


def shown(value: Figure | None) -> str:
    """A figure for the readable table: four decimals."""
    if value is None:
        return "n/a"
    return format(rounded(value, 4), "f") if isinstance(value, Fraction) else str(value)


def as_json(value: Figure | None) -> int | str | None:
    return exact(value) if isinstance(value, Fraction) else value


# The criteria (section 6). Each takes a variant's included runs and fails when there
# are none, since nothing can then be shown to hold.


def worst_drop(runs: Sequence[Run]) -> Criterion:
    """C1: in every run, the total-equity drawdown from its running peak (a) and the
    active-equity drawdown from the C1(b) measurement reference (b) are at most 10%, and
    no hard-drawdown halt happened."""
    failing = tuple(
        run.label
        for run in runs
        if max(run.max_drawdown_pct, run.active_max_drawdown_pct) > DRAWDOWN_LIMIT_PCT
        or run.hard_drawdown_halts
    )
    numbers: dict[str, Figure] = {
        "worst total-equity drawdown %": max((r.max_drawdown_pct for r in runs), default=0),
        "worst active-equity drawdown %": max((r.active_max_drawdown_pct for r in runs), default=0),
        "hard-drawdown halts": sum(run.hard_drawdown_halts for run in runs),
        "limit %": str(DRAWDOWN_LIMIT_PCT),
    }
    return Criterion("C1", bool(runs) and not failing, numbers, failing)


def makes_money(runs: Sequence[Run]) -> Criterion:
    """C2: for each intrabar path the median annualised return is above 0, and the mean
    annualised return over all runs is above 0, every run with equal weight (section 6,
    "Annualised returns"). Raw returns are reported with the runs."""
    numbers: dict[str, Figure] = {}
    passed = bool(runs)
    for path in PATH_MODES:
        name = f"median annualised return % ({path})"
        figures = [run.annualised for run in runs if run.path == path]
        if not figures:
            numbers[name] = "no runs"
            passed = False
            continue
        low, value, high = enclosure(median, figures)
        numbers[name] = written(value)
        passed = passed and certain(positive, low, high, f"C2's {name}")
    if runs:
        low, value, high = enclosure(mean, [run.annualised for run in runs])
        numbers["mean annualised return %"] = written(value)
        passed = passed and certain(positive, low, high, "C2's mean annualised return")
    return Criterion("C2", passed, numbers)


def safer_than_holding(runs: Sequence[Run]) -> Criterion:
    """C3: in every run the total-equity max drawdown is below that run's buy-and-hold
    max drawdown. A zero buy-and-hold drawdown fails, since no drawdown is below it."""
    failing = tuple(
        run.label for run in runs if not run.max_drawdown_pct < run.buy_and_hold_max_drawdown_pct
    )
    numbers: dict[str, Figure] = {
        "runs below buy-and-hold drawdown": f"{len(runs) - len(failing)} of {len(runs)}"
    }
    return Criterion("C3", bool(runs) and not failing, numbers, failing)


def integrity(runs: Sequence[Run], missing: Sequence[str] = ()) -> Criterion:
    """C4: every included run is valid (section 5). A run missing from the matrix is not."""
    failing = tuple(f"{run.label}: {'; '.join(run.problems)}" for run in runs if run.problems)
    failing += tuple(f"{label}: missing" for label in missing)
    valid = len(runs) - sum(1 for run in runs if run.problems)
    numbers: dict[str, Figure] = {"valid runs": f"{valid} of {len(runs) + len(missing)}"}
    return Criterion("C4", bool(runs) and not failing, numbers, failing)


def activity(runs: Sequence[Run]) -> Criterion:
    """C5: the mean over all runs of each run's completed cycles per week of the
    evaluation window, computed exactly, is at least 1."""
    if not runs:
        return Criterion("C5", False, {"mean completed cycles per week": "no runs"})
    rate = mean([run.cycle_rate for run in runs])
    numbers: dict[str, Figure] = {"mean completed cycles per week": rate, "minimum": 1}
    return Criterion("C5", rate >= 1, numbers)


def gate(runs: Sequence[Run]) -> Criterion:
    """C6: in at least 60% of runs the variant's return / max(max drawdown, 0.1 points)
    exceeds the ungated V0 baseline's in the same pair, window and path. A comparison
    whose baseline is missing or invalid cannot show that, so it counts against. The
    returns are raw, since the owner's annualisation names only C2 and the selection."""
    failing = tuple(
        run.label + (f": {run.baseline_problem}" if run.baseline is None else "")
        for run in runs
        if run.baseline is None or not run.ratio > run.baseline
    )
    wins = len(runs) - len(failing)
    share = Fraction(wins, len(runs)) if runs else Fraction(0)
    numbers: dict[str, Figure] = {
        "runs beating the baseline": f"{wins} of {len(runs)}",
        "share %": share * 100,
        "required %": str(GATE_SHARE * 100),
    }
    return Criterion("C6", bool(runs) and share >= GATE_SHARE, numbers, failing)


def economics(runs: Sequence[Run]) -> dict[str, Figure]:
    """R1, reported only: the capital whose mean monthly return covers 5 EUR a month of
    hosting (5 / the mean monthly return fraction), or "not reachable" when that mean is
    at or below 0. A run's monthly return is its raw window return divided by the
    window's calendar months. Hosting on the owner's own PC costs 0 EUR and needs no
    capital."""
    if not runs:
        return {R1_CAPITAL: "no runs"}
    monthly = mean([run.return_pct / 100 / run.months for run in runs])
    return {
        "mean monthly return %": monthly * 100,
        R1_CAPITAL: HOSTING_EUR / monthly if monthly > 0 else "not reachable",
    }


def score_variant(variant: str, runs: Sequence[Run], missing: Sequence[str] = ()) -> VariantScore:
    criteria = (
        worst_drop(runs),
        makes_money(runs),
        safer_than_holding(runs),
        integrity(runs, missing),
        activity(runs),
        gate(runs),
    )
    return VariantScore(variant, tuple(runs), tuple(missing), criteria, economics(runs))


# The stages and the selection (section 6).


def judge(
    stage: Stage,
    windows: Mapping[str, Window],
    named: Mapping[str, set[str]],
    found: Mapping[str, Mapping[tuple[str, str, str], Run]],
) -> StageScores:
    """C1-C6 for every variant the stage's files name, over the stage's included runs,
    and why the inputs are not the stage's whole matrix. ``named`` is each window's
    variants, ``found`` each variant's runs. A stage is judged over all its windows or
    not at all, since a verdict over part of them is not the stage's."""
    present = tuple(windows[name] for name in stage.windows if name in windows)
    gaps = [f"{name} is not in the inputs" for name in stage.windows if name not in windows]
    if gaps:
        return StageScores(stage, present, (), tuple(gaps))
    keys = [(w.name, pair, path) for w in present for pair in w.included for path in PATH_MODES]
    in_stage = {variant for w in present for variant in named[w.name]}
    scores = []
    for variant in VARIANTS:
        if variant in in_stage:
            runs = found.get(variant, {})
            scores.append(
                score_variant(
                    variant,
                    [runs[k] for k in keys if k in runs],
                    [" ".join(k) for k in keys if k not in runs],
                )
            )
    absent = [variant for variant in VARIANTS if variant not in in_stage]
    if absent:
        gaps.append("variants not in the inputs: " + ", ".join(absent))
    gaps += [f"{s.variant} is missing {len(s.missing)} runs" for s in scores if s.missing]
    return StageScores(stage, present, tuple(scores), tuple(gaps))


def selectable(variant: str) -> bool:
    """Step 1: D never (step 5); E only after Codex's implementation review."""
    return variant in SIMPLICITY_ORDER and (variant != "E" or E_ELIGIBLE)


def ranked_return(score: VariantScore) -> Decimal:
    """Step 2's figure: the mean annualised return in percentage points rounded to 6
    decimals, certified against the runs' bounds."""
    low, _, high = enclosure(mean, [run.annualised for run in score.runs])
    return certain(
        lambda value: rounded(value, SELECTION_PLACES),
        low,
        high,
        f"{score.variant}'s mean annualised return",
    )


def select(scores: Sequence[VariantScore]) -> Selection:
    """Steps 1-5 among the selectable variants that pass: the tie set is every one whose
    mean annualised return is within 0.25 points of the best; in it, the lowest mean max
    drawdown wins, and a remaining tie goes to the first in the simplicity order. Both
    means are rounded to 6 decimals before they are compared."""
    eligible = sorted(
        (s for s in scores if s.passed and selectable(s.variant)),
        key=lambda s: SIMPLICITY_ORDER.index(s.variant),
    )
    if not eligible:
        return Selection(
            "no winner", reasons=("no selectable variant passes C1-C6 in stage 1 and in stage 2",)
        )
    figures = {
        s.variant: (ranked_return(s), rounded(s.mean_drawdown_pct, SELECTION_PLACES))
        for s in eligible
    }
    best = max(mean_return for mean_return, _ in figures.values())
    tie = [v for v, (mean_return, _) in figures.items() if mean_return >= best - TIE_MARGIN_PCT]
    lowest = min(figures[v][1] for v in tie)
    # ``tie`` keeps the simplicity order, so the first at the lowest drawdown wins.
    winner = next(v for v in tie if figures[v][1] == lowest)
    return Selection("winner", winner, tie_set=tuple(tie), figures=figures)


def thin_windows(windows: Sequence[Window]) -> list[str]:
    """Section 5's minimum evidence: the windows left with fewer than 2 included pairs."""
    return [
        f"{w.name}: {len(w.included)} included pairs; section 5 needs at least {MINIMUM_PAIRS}"
        for w in windows
        if len(w.included) < MINIMUM_PAIRS
    ]


def early_read(stage: StageScores) -> Selection:
    """Section 6, "Two stages": stage 1 says which variants pass it, and names no winner.
    The list needs section 5's minimum evidence and the stage's whole matrix."""
    thin = thin_windows(stage.windows)
    if thin:
        return Selection("insufficient evidence", reasons=(*thin, EARLY_READ_NOTE))
    if stage.gaps:
        return Selection("incomplete matrix", reasons=(*stage.gaps, EARLY_READ_NOTE))
    passing = tuple(s.variant for s in stage.scores if s.passed)
    return Selection("early read", reasons=(EARLY_READ_NOTE,), qualified=passing)


def final_selection(stages: Sequence[StageScores]) -> Selection:
    """Section 6, "Two stages", over both stages' whole matrices: section 5's minimum
    evidence in every scored window, then steps 1-5 among the variants that pass C1-C6 in
    stage 1 and in stage 2, ranked on stage 2's full-range-2017-2024 alone. The reported
    window decides nothing, not even by falling short of the minimum evidence."""
    thin = thin_windows([w for s in stages if s.stage.scored for w in s.windows])
    if thin:
        return Selection("insufficient evidence", reasons=tuple(thin))
    judged = {s.stage: s for s in stages}
    first = {s.variant for s in judged[STAGE_1].scores if s.passed}
    ranked = [s for s in judged[STAGE_2].scores if s.variant in first]
    qualified = tuple(s.variant for s in ranked if s.passed)
    return replace(select(ranked), qualified=qualified)


# Reading the results.


def evaluation_window(spec: DatasetSpec) -> tuple[int, int]:
    """C5's window, ``[start of the start month, end of the end month)`` in UTC, in days,
    and R1's calendar months of it."""
    start, end = month_bounds_ms(spec.start)[0], month_bounds_ms(spec.end)[1]
    return (end - start) // DAY_MS, len(spec.months(spec.start))


def data_rule_exclusions(spec: DatasetSpec, pair: str) -> list[str]:
    """Section 5's long-window data rules that exclude a pair-window for every variant
    alike: XRP where a replayed quote breaks the tick limit (rule 8), by Bob's
    measurement.

    They arrive with the long-window data PR, which names the fields that record that
    measurement and each run's mask report (rules 1-4: masked hours, skipped days, fills
    after a masked span). Until then nothing is excluded here and no hour is masked: a
    failed hour fails its integrity check, which excludes its pair-window in
    ``window_of``, as in stage 1. When they land:

    * the measurement plugs in here;
    * masking runs before the checks, which then run on the post-mask expected set, so a
      maskable defect stops failing them in ``integrity_failures`` (section 5, "The
      post-mask expected set"), and ``window_of`` keeps its rules;
    * the mask report joins ``Run`` and ``run_json`` in ``runs_of``."""
    return []


def window_of(spec: DatasetSpec, checks: list[dict[str, Any]]) -> Window:
    """The comparison mask (section 5) from the variant-independent checks a run recorded.

    A failed check on the market proxy (its hours feed every pair's regime) or on an
    untraded breadth-basket symbol (its votes gate every pair) excludes every pair. A
    traded pair's own minute, hourly and daily checks exclude only that pair, even when it
    also votes in the basket: section 5 makes the shared completeness check one for the
    untraded symbols. A pair that fails the filter-availability check (P4) is excluded
    too, and so is one a long-window data rule excludes (``data_rule_exclusions``).
    Manifest and checksum failures stop a run before it writes results, so a results
    file exists only where they passed.
    """
    if sorted(check["symbol"] for check in checks) != sorted(checked_symbols(spec)):
        raise ScoringError("the integrity checks are not one per symbol the spec checks")
    shared = {spec.market_proxy, *(set(spec.breadth_basket) - set(spec.traded))}
    every_pair = integrity_failures([c for c in checks if c["symbol"] in shared])
    excluded: dict[str, tuple[str, ...]] = {}
    for pair in spec.traded:
        own = [c for c in checks if c["symbol"] == pair and pair not in shared]
        reasons = every_pair + integrity_failures(own)
        if (spec.name, pair) in FILTER_EXCLUSIONS:
            reasons.append(FILTER_EXCLUSIONS[spec.name, pair])
        reasons += data_rule_exclusions(spec, pair)
        if reasons:
            excluded[pair] = tuple(reasons)
    days, months = evaluation_window(spec)
    return Window(spec.name, spec.traded, excluded, days, months)


def variant_of(row: dict[str, Any]) -> str | None:
    """The section 4 variant a row belongs to, or None for the ungated V0 baseline."""
    strategy, name = row["strategy"], row.get("variant")
    if strategy == BASELINE and name is None:
        return None
    if strategy == GRID and (name is None or name in GRID_VARIANTS):
        return name or "V0"
    if strategy == STRUCTURE_GRID and name in STRUCTURE_VARIANTS:
        return STRUCTURE_VARIANTS[name]
    if strategy == BENCHMARK_STRATEGY and name == "D":
        return "D"
    raise ScoringError(f"not a spec v1 variant: strategy {strategy!r}, variant {name!r}")


def variants_in(document: dict[str, Any]) -> set[str]:
    """The section 4 variants a results.json has rows of, in any pair."""
    return {variant for row in document["results"] if (variant := variant_of(row))}


def primary_problems(row: dict[str, Any]) -> list[str]:
    """Why a row did not run at the section 4 primary settings."""
    rules = row["rules"]
    recorded = {
        "maker fee": rules["fee_rate"],
        "taker fee": rules.get("taker_fee_rate", rules["fee_rate"]),
        "slippage": rules["slippage_rate"],
        "participation": rules["participation"],
        "assumed spread %": row["assumed_spread_pct"],
        "capital": row["initial_quote"],
    }
    problems = [
        f"{name} {value}, not the primary {PRIMARY[name]}"
        for name, value in recorded.items()
        if Decimal(value) != PRIMARY[name]
    ]
    if "fill_trigger_rate" in rules:
        problems.append("a fill trigger is set: a missed-fill sensitivity run (D9)")
    return problems


def feature_problems(document: dict[str, Any]) -> list[str]:
    """Why the features a results.json records are not a spec v1 run's: V0's for every
    row, or, in a --structure run (V2 and the full stack), V2's for the gated rows and
    V0's for the ungated V0 baseline rows (``baseline_feature_version``)."""
    version, baseline = document["feature_version"], document.get("baseline_feature_version")
    expected = FEATURE_VERSION if version == STRUCTURE_FEATURE_VERSION else None
    if version not in (FEATURE_VERSION, STRUCTURE_FEATURE_VERSION) or baseline != expected:
        return [
            f"features {version!r} (ungated rows {baseline!r}), not {FEATURE_VERSION!r}, or "
            f"{STRUCTURE_FEATURE_VERSION!r} with {FEATURE_VERSION!r} for the ungated rows"
        ]
    strategies = {row["strategy"] for row in document["results"]}
    gated = {strategy for strategy in strategies if strategy.startswith("gated grid")}
    if gated - {f"gated grid ({version})"}:
        return [f"gated rows {', '.join(sorted(gated))} in a results.json of features {version!r}"]
    return []


def document_problems(document: dict[str, Any]) -> list[str]:
    """Why a results.json is not an acceptance run, or [] when it is one."""
    problems = []
    if document["engine_version"] != ENGINE_VERSION:
        problems.append(
            f"engine {document['engine_version']!r}, not {ENGINE_VERSION!r}: results of "
            "different engines are different trials and are never pooled"
        )
    problems += feature_problems(document)
    if document["integrity_rules"]["version"] != INTEGRITY_RULES:
        problems.append(
            f"integrity rules {document['integrity_rules']['version']!r}, not {INTEGRITY_RULES!r}"
        )
    if document["valid"] is not (not document["failures"]):
        problems.append("'valid' disagrees with 'failures'")
    for row in document["results"]:
        problems += primary_problems(row)
    return problems


def number(value: object) -> Fraction:
    """A recorded drawdown or share, exactly as written (floats are read as their decimal
    text). None of them can be negative."""
    if isinstance(value, bool) or not isinstance(value, int | Decimal) or value < 0:
        raise ScoringError(f"not a non-negative number: {value!r}")
    return Fraction(value)


def count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScoringError(f"not a count: {value!r}")
    return value


def return_pct(row: dict[str, Any]) -> Fraction:
    """The exact return in percent, from the recorded equities (``return_pct`` is a float)."""
    initial = Fraction(Decimal(row["initial_quote"]))
    return (Fraction(Decimal(row["final_total_equity"])) / initial - 1) * 100


def runs_of(document: dict[str, Any], window: Window) -> Iterator[tuple[str, Run]]:
    """A results.json's runs in included pair-windows, each with its validity (section 5)
    and the ungated V0 baseline from the same file (C6). Rows of excluded pairs are left
    out: the mask lists them, for every variant alike."""
    rows = document["results"]
    # A failure of the whole file, such as a checkout that changed during the run, is in
    # its failures without belonging to a row, and invalidates every row.
    of_rows = set(result_failures(rows))
    general = tuple(f for f in document["failures"] if f not in of_rows)
    baselines: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["symbol"], row["path_mode"])
        if row["symbol"] not in window.pairs or row["path_mode"] not in PATH_MODES:
            raise ScoringError(f"{window.name} has no pair and path {' '.join(key)}")
        if variant_of(row) is None:
            if key in baselines:
                raise ScoringError(f"two ungated baseline rows for {' '.join(key)}")
            baselines[key] = row
    for row in rows:
        variant = variant_of(row)
        if variant is None or row["symbol"] in window.excluded:
            continue
        baseline = baselines.get((row["symbol"], row["path_mode"]))
        ratio, why = None, "no ungated V0 baseline row in the same results.json"
        if baseline is not None:
            invalid = [*result_failures([baseline]), *general]
            why = f"the ungated V0 baseline is invalid: {'; '.join(invalid)}" if invalid else ""
            if not invalid:
                ratio = gate_ratio(return_pct(baseline), number(baseline["max_drawdown_pct"]))
        # Section 5 rules 1-4: each run's mask report (masked hours, skipped days, fills
        # after a masked span) joins the Run here, under the names the long-window data PR
        # gives it (``data_rule_exclusions``).
        yield (
            variant,
            Run(
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
                baseline=ratio,
                baseline_problem=why,
                cycle_weeks=len(row.get("completed_cycles_by_week", {})),
                time_with_inventory_pct=number(row["time_with_inventory_pct"]),
            ),
        )


def assess(sources: Sequence[Source], specs: Mapping[str, DatasetSpec], invocation: str) -> Verdict:
    """Score ``sources`` with the dataset ``specs`` they ran on (``read_frozen``), as the
    ``invocation``: the early read scores stage 1; the final scores both stages, and
    refuses unless both stages' matrices are complete."""
    windows: dict[str, Window] = {}
    named: dict[str, set[str]] = {}
    found: dict[str, dict[tuple[str, str, str], Run]] = {}
    problems: list[str] = []
    for source in sources:
        try:
            problems += [f"{source.path}: {p}" for p in document_problems(source.document)]
            window = window_of(specs[source.dataset], source.document["hourly_cross_checks"])
            if windows.setdefault(window.name, window) != window:
                raise ScoringError(f"its comparison mask differs from another {window.name} run's")
            named.setdefault(window.name, set()).update(variants_in(source.document))
            for variant, run in runs_of(source.document, window):
                runs = found.setdefault(variant, {})
                if run.key in runs:
                    raise ScoringError(f"{variant} {run.label} is in more than one input")
                runs[run.key] = run
        except ScoringError as exc:
            problems.append(f"{source.path}: {exc}")
        except (KeyError, TypeError, AttributeError, ArithmeticError, ValueError) as exc:
            problems.append(f"{source.path}: malformed results ({type(exc).__name__} {exc})")
    if problems:
        raise ScoringError("\n".join(dict.fromkeys(problems)))
    judged = tuple(judge(stage, windows, named, found) for stage in INVOCATIONS[invocation])
    if invocation == "final":
        gaps = [f"{s.stage.name}: {gap}" for s in judged for gap in s.gaps]
        if gaps:
            raise ScoringError(
                "\n".join(["the final verdict needs both stages' whole matrices", *gaps])
            )
        selection = final_selection(judged)
    else:
        selection = early_read(judged[0])
    ordered = tuple(window for s in judged for window in s.windows)
    return Verdict(invocation, tuple(sources), ordered, judged, selection)


def _refuse_constant(name: str) -> object:
    raise ValueError(f"non-finite number {name}")


def read_results(path: Path) -> Source:
    """A run directory's results.json, or the file itself, with floats read as Decimal."""
    file = path / "results.json" if path.is_dir() else path
    try:
        raw = file.read_bytes()
        document = json.loads(raw, parse_float=Decimal, parse_constant=_refuse_constant)
    except (OSError, ValueError) as exc:
        raise ScoringError(f"{file}: cannot read results ({exc})") from exc
    if not isinstance(document, dict):
        raise ScoringError(f"{file}: not a results.json")
    return Source(file, hashlib.sha256(raw).hexdigest(), document)


def text_digests(path: Path) -> tuple[str, str]:
    """The SHA-256 of a committed text file with LF and with CRLF line endings. Git checks
    the same commit out either way (``core.autocrlf`` on Windows), and the backtest CLI
    hashes the bytes it finds, so a run on Linux and one on Windows record different
    hashes of one file. Line endings change no TOML value."""
    text = path.read_bytes().replace(b"\r\n", b"\n")
    crlf = text.replace(b"\n", b"\r\n")
    return hashlib.sha256(text).hexdigest(), hashlib.sha256(crlf).hexdigest()


def committed_name(path: Path) -> str:
    """A frozen file's path as the repository commits it."""
    return path.relative_to(REPOSITORY).as_posix() if path.is_relative_to(REPOSITORY) else str(path)


def pinned(path: Path, recorded: set[str], what: str) -> list[str]:
    """Why the hashes runs recorded for a frozen file are not that committed file's: []
    when every one is, in either line-ending form."""
    digests = text_digests(path)
    unknown = sorted(recorded - set(digests))
    if not unknown:
        return []
    return [
        f"{what} {', '.join(unknown)}, not the committed {committed_name(path)} "
        f"(SHA-256 {digests[0]} with LF line endings)"
    ]


def code_problems(sources: Sequence[Source], scorer: Mapping[str, str]) -> list[str]:
    """Why the runs did not all come from the code that scores them.

    Every run must record a clean commit, the same for all, and the scorer's own source
    identity (``code_sha256``, which normalises line endings). The scorer must run from
    that same clean commit. So a run without provenance (a plain V0 run made without
    ``--record-commit``), from a dirty checkout, or from changed code that kept its version
    labels is refused.
    """
    problems = []
    for s in sources:
        commit, code = s.document.get("code_commit"), s.document.get("code_sha256")
        if not (isinstance(commit, str) and _CLEAN_COMMIT.fullmatch(commit)):
            problems.append(f"{s.path}: code commit {commit!r}, not a clean commit")
        if code != scorer["code_sha256"]:
            problems.append(f"{s.path}: code {code!r}, not the scorer's {scorer['code_sha256']}")
    commits = sorted({str(s.document.get("code_commit")) for s in sources})
    if commits != [scorer["code_commit"]]:
        problems.append(
            f"the runs come from {', '.join(commits)}; the scorer runs at {scorer['code_commit']}"
        )
    return problems


def read_frozen(
    sources: Sequence[Source], scorer: Mapping[str, str], invocation: str
) -> dict[str, DatasetSpec]:
    """Check every run against the frozen inputs, and return each window's dataset spec.

    The runs must come from the code that scores them (``code_problems``) and from the
    ``invocation``'s windows only. The default config (section 3, V0: "default config"),
    and each window's dataset spec and manifest, as committed beside this code, must hash
    to what every run recorded, and each spec's evaluation window must be the one section
    6 registers. Every window of the invocation must have its spec and manifest committed,
    even with none of its runs in the inputs: until the long-window data PR commits stage
    2's, a final run is refused and says so. A batch made with a tuned copy of any of
    them is refused, however well its files agree.
    """
    problems = code_problems(sources, scorer)
    registered = [name for stage in INVOCATIONS[invocation] for name in stage.windows]
    specs = {}
    try:
        configs = {str(s.document["config_sha256"]) for s in sources}
        problems += pinned(ACCEPTANCE_CONFIG, configs, "config")
        problems += [
            f"{name!r} is not a window of the {invocation} ({', '.join(registered)})"
            for name in sorted({s.dataset for s in sources} - set(registered))
        ]
        for name in registered:
            spec = DATASET_SPECS / f"{name}.toml"
            manifest = DATASET_SPECS / f"{name}.manifest.json"
            absent = [committed_name(file) for file in (spec, manifest) if not file.is_file()]
            if absent:
                problems.append(
                    f"{name}: no committed {' or '.join(absent)}, so its runs cannot be "
                    "pinned; stage 2's dataset specs and manifests come with the long-window "
                    "data PR (spec v1 section 4, 'Stage 2 windows')"
                )
                continue
            runs = [s.document for s in sources if s.dataset == name]
            if not runs:
                continue  # the stage's gaps name the missing window
            spec_problems = pinned(spec, {str(r["spec_sha256"]) for r in runs}, f"{name}: spec")
            problems += spec_problems
            manifests = {str(r["manifest_sha256"]) for r in runs}
            problems += pinned(manifest, manifests, f"{name}: manifest")
            if not spec_problems:
                specs[name] = load_spec(spec)
                days = evaluation_window(specs[name])[0]
                if days != REGISTERED_DAYS[name]:
                    problems.append(
                        f"{name}: the committed spec's evaluation window is {days} days; "
                        f"spec v1 section 6 registers {REGISTERED_DAYS[name]}"
                    )
    except (OSError, KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ScoringError(f"cannot check the frozen inputs ({type(exc).__name__} {exc})") from exc
    if problems:
        raise ScoringError("\n".join([*problems, FROZEN_HINT]))
    return specs


# Output.


def window_json(window: Window) -> dict[str, Any]:
    return {
        "evaluation_days": window.days,
        "evaluation_months": window.months,
        "pairs": {
            pair: {
                "included": pair not in window.excluded,
                "reasons": list(window.excluded.get(pair, ())),
            }
            for pair in window.pairs
        },
        "included_pairs": len(window.included),
        "minimum_evidence": len(window.included) >= MINIMUM_PAIRS,
    }


def run_json(run: Run) -> dict[str, Any]:
    return {
        "window": run.window,
        "symbol": run.symbol,
        "path": run.path,
        "valid": not run.problems,
        "problems": list(run.problems),
        "return_pct": exact(run.return_pct),
        "annualised_return_pct": exact(written(run.annualised.value)),
        "max_drawdown_pct": exact(run.max_drawdown_pct),
        "active_max_drawdown_pct": exact(run.active_max_drawdown_pct),
        "buy_and_hold_max_drawdown_pct": exact(run.buy_and_hold_max_drawdown_pct),
        "hard_drawdown_halts": run.hard_drawdown_halts,
        "completed_cycles": run.completed_cycles,
        "cycles_per_week": exact(run.cycle_rate),
        "iso_weeks_with_cycles": run.cycle_weeks,
        "time_with_inventory_pct": exact(run.time_with_inventory_pct),
        "gate_ratio": exact(run.ratio),
        "baseline_gate_ratio": as_json(run.baseline),
        "baseline_problem": run.baseline_problem or None,
    }


def score_json(score: VariantScore) -> dict[str, Any]:
    return {
        "passed": score.passed,
        "selectable": selectable(score.variant),
        "criteria": {
            c.name: {
                "passed": c.passed,
                "numbers": {name: as_json(value) for name, value in c.numbers.items()},
                "failing": list(c.failing),
            }
            for c in score.criteria
        },
        "r1_reported_only": {name: as_json(value) for name, value in score.r1.items()},
        "mean_return_pct": exact(score.mean_return_pct) if score.runs else None,
        "mean_annualised_return_pct": (
            exact(written(score.mean_annualised_pct)) if score.runs else None
        ),
        "mean_max_drawdown_pct": exact(score.mean_drawdown_pct) if score.runs else None,
        "missing": list(score.missing),
        "runs": [run_json(run) for run in score.runs],
    }


def stage_json(judged: StageScores) -> dict[str, Any]:
    return {
        "windows": list(judged.stage.windows),
        "scored": judged.stage.scored,  # False: run and reported, deciding nothing
        "complete": not judged.gaps,
        "gaps": list(judged.gaps),
        "passing": [s.variant for s in judged.scores if s.passed],
        "variants": {s.variant: score_json(s) for s in judged.scores},
    }


def verdict_json(verdict: Verdict) -> dict[str, Any]:
    """The verdict and every figure behind it. Numbers are exact strings: a decimal where
    it terminates, otherwise ``p/q``; irrational annualised returns are rounded."""
    selection = verdict.selection
    return {
        "scoring": SCORING,
        "invocation": verdict.invocation,
        "numbers": NUMBERS_NOTE,
        "primary": {name: str(value) for name, value in PRIMARY.items()},
        "engine_version": ENGINE_VERSION,
        "integrity_rules": INTEGRITY_RULES,
        "inputs": [
            {
                "path": str(s.path),
                "sha256": s.sha256,
                **{
                    key: s.document.get(key)
                    for key in (
                        "dataset",
                        "feature_version",
                        "spec_sha256",
                        "manifest_sha256",
                        "config_sha256",
                        "code_commit",
                        "code_sha256",
                        "policy",
                    )
                },
            }
            for s in verdict.sources
        ],
        "comparison_mask": {w.name: window_json(w) for w in verdict.windows},
        "stages": {s.stage.name: stage_json(s) for s in verdict.stages},
        "selection": {
            "outcome": selection.outcome,
            "winner": selection.winner,
            "reasons": list(selection.reasons),
            "qualified": list(selection.qualified),
            "e_eligible": E_ELIGIBLE,
            "eligible": {
                v: {
                    "mean_annualised_return_pct": format(r, "f"),
                    "mean_max_drawdown_pct": format(d, "f"),
                }
                for v, (r, d) in selection.figures.items()
            },
            "tie_set": list(selection.tie_set),
            "c7": C7_NOTE,
        },
    }


def stage_lines(judged: StageScores) -> list[str]:
    """One stage of the readable verdict."""
    stage = judged.stage
    rule = (
        "a variant passes only if all of C1-C6 pass; R1 is reported only"
        if stage.scored
        else "reported only; it decides nothing (spec v1 section 5, rule 6)"
    )
    lines = ["", f"{stage.name.capitalize()} ({', '.join(stage.windows)}): {rule}"]
    lines += [f"- not the whole matrix: {gap}" for gap in judged.gaps]
    if not judged.scores:
        return lines
    lines += [
        "| Variant | C1 | C2 | C3 | C4 | C5 | C6 | Verdict | Mean annualised % | "
        "Mean return % | Mean max DD % | R1 capital EUR |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for score in judged.scores:
        name = score.variant + ("" if selectable(score.variant) else " (not selectable)")
        marks = " | ".join("pass" if c.passed else "FAIL" for c in score.criteria)
        lines.append(
            f"| {name} | {marks} | {'PASS' if score.passed else 'FAIL'} | "
            f"{shown(score.mean_annualised_pct if score.runs else None)} | "
            f"{shown(score.mean_return_pct if score.runs else None)} | "
            f"{shown(score.mean_drawdown_pct if score.runs else None)} | "
            f"{shown(score.r1[R1_CAPITAL])} |"
        )
    for score in judged.scores:
        lines += [
            "",
            f"{score.variant} in {stage.name}: {len(score.runs)} included runs, "
            f"{len(score.missing)} missing",
        ]
        for c in score.criteria:
            figures = "; ".join(f"{name} {shown(value)}" for name, value in c.numbers.items())
            lines.append(f"- {c.name} {'pass' if c.passed else 'FAIL'}: {figures}")
            lines += [f"    {item}" for item in c.failing]
        lines.append(
            "- R1 (reported only): "
            + "; ".join(f"{name} {shown(value)}" for name, value in score.r1.items())
        )
    return lines


def render(verdict: Verdict) -> str:
    """The verdict as readable text (ASCII, so any console prints it)."""
    lines = [
        f"Acceptance scoring {SCORING}, {verdict.invocation}: primary fees maker "
        f"{PRIMARY['maker fee']} / taker {PRIMARY['taker fee']}, engine {ENGINE_VERSION}, "
        f"integrity rules {INTEGRITY_RULES}",
        f"Inputs: {len(verdict.sources)} results files (paths and SHA-256 in the JSON verdict)",
        "",
        "Comparison mask (spec v1 section 5)",
        "| Window | Pair | Included | Reasons |",
        "| --- | --- | --- | --- |",
    ]
    for window in verdict.windows:
        for pair in window.pairs:
            reasons = window.excluded.get(pair, ())
            lines.append(
                f"| {window.name} | {pair} | {'no' if reasons else 'yes'} | {'; '.join(reasons)} |"
            )
    for judged in verdict.stages:
        lines += stage_lines(judged)
    selection = verdict.selection
    lines += ["", f"Selection (spec v1 section 6, {verdict.invocation}): {selection.outcome}"]
    if selection.winner:
        lines[-1] += f": {selection.winner}"
    lines += [f"- {reason}" for reason in selection.reasons]
    if selection.outcome in ("early read", "winner", "no winner"):
        stages = "stage 1" if verdict.invocation == "early read" else "stage 1 and stage 2"
        lines.append(f"- passing {stages}: {', '.join(selection.qualified) or 'none'}")
    if selection.figures:
        lines.append(
            f"- eligible, ranked on {STAGE_2.windows[0]} (mean annualised return % / mean "
            "max DD %, rounded to 6 decimals): "
            + "; ".join(
                f"{v} {format(r, 'f')} / {format(d, 'f')}"
                for v, (r, d) in selection.figures.items()
            )
        )
        lines.append(
            "- tie set (mean annualised return within 0.25 of the best): "
            + ", ".join(selection.tie_set)
        )
    lines.append(C7_NOTE)
    return "\n".join(lines)


def unscored(invocation: str, outcome: str, reasons: Sequence[str]) -> dict[str, Any]:
    """The verdict of an invocation that scored nothing: no variant and no winner."""
    return {
        "scoring": SCORING,
        "invocation": invocation,
        "selection": {"outcome": outcome, "winner": None, "reasons": list(reasons)},
    }


def write_verdict(path: Path, document: dict[str, Any]) -> None:
    """Replace ``path`` in one step: a reader sees the old file or the new one."""
    _write_atomic(path, (json.dumps(document, indent=1) + "\n").encode())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m crypto_grid_bot.backtest.acceptance",
        description="Score backtest results against spec v1 section 6 (C1-C6, R1, selection), "
        "in its two stages.",
    )
    parser.add_argument(
        "results", type=Path, nargs="+", help="run directories, or their results.json files"
    )
    parser.add_argument("--out", type=Path, required=True, help="where to write the JSON verdict")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--early-read",
        dest="invocation",
        action="store_const",
        const="early read",
        help="stage 1 only (verify-2024h1, practice-2022): which variants pass it; names no winner",
    )
    mode.add_argument(
        "--final",
        dest="invocation",
        action="store_const",
        const="final",
        help="both stages: a variant must pass stage 1 and stage 2 (full-range-2017-2024), "
        "and the winner is ranked there; refuses unless both stages' matrices are complete",
    )
    args = parser.parse_args(argv)
    if args.out.resolve() in {
        (p / "results.json" if p.is_dir() else p).resolve() for p in args.results
    }:
        parser.error("--out must not be one of the results files it scores")
    # The code that scores, as the backtest CLI records the code that ran.
    scorer = {"code_commit": code_commit(), "code_sha256": SOURCE_IDENTITY}
    # Until this run's own verdict replaces it, --out says that nothing was scored, so a
    # refused, interrupted or failed run never leaves an earlier verdict in its place.
    pending = unscored(args.invocation, "not scored", ["scoring did not finish"])
    write_verdict(args.out, {"scorer": scorer, **pending})
    try:
        sources = [read_results(path) for path in args.results]
        verdict = assess(sources, read_frozen(sources, scorer, args.invocation), args.invocation)
    except ScoringError as exc:
        refused = unscored(args.invocation, "refused", str(exc).splitlines())
        write_verdict(args.out, {"scorer": scorer, **refused})
        print(f"Refused; nothing was scored:\n{exc}", file=sys.stderr)
        return 2
    write_verdict(args.out, {"scorer": scorer, **verdict_json(verdict)})
    print(render(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
