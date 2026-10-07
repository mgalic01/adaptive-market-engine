"""Spec v1 section 6: the acceptance scorer, on synthetic results only.

No market data and no backtest result is read. The file-level tests build results.json
files the way the backtest CLI writes them, against the committed stage-1 dataset specs
(configuration, not data), so the C5 windows and the P4 mask are the real ones. The
stage-2 windows have no committed specs or manifests yet, so the final-verdict tests write
synthetic ones with spec v1 section 4's frozen definitions to a temporary directory and
point the scorer there.
"""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction as F
from pathlib import Path
from unittest.mock import patch

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest import acceptance as score
from crypto_grid_bot.backtest import jobs
from crypto_grid_bot.backtest.dataset import DatasetSpec, load_spec, sha256_file
from crypto_grid_bot.backtest.features import FEATURE_VERSION, STRUCTURE_FEATURE_VERSION
from crypto_grid_bot.backtest.replay import ENGINE_VERSION, INTEGRITY_RULES, PATH_MODES
from crypto_grid_bot.backtest.trend_benchmark import STRATEGY as BENCHMARK
from crypto_grid_bot.simulation.runner import FULL_STACK

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "config" / "datasets"
FROZEN_CONFIG = sha256_file(ROOT / "config" / "default.toml")
# A synthetic clean commit. The in-process tests give the scorer this commit as its own,
# so they do not depend on the state of the checkout they run in.
FROZEN_COMMIT = "c0ffee" + "0" * 34
STAGE_1 = score.STAGE_1.windows
LONG = ("full-range-2017-2024", "full-range-2019-2024")


def run(**changes):
    """A valid run that passes every criterion on its own; its C5 rate is exactly 1
    (26 cycles in 182 days)."""
    values = {
        "window": "verify-2024h1",
        "symbol": "BTCUSDT",
        "path": "high_first",
        "return_pct": F(1),
        "max_drawdown_pct": F(2),
        "active_max_drawdown_pct": F(2),
        "buy_and_hold_max_drawdown_pct": F(5),
        "hard_drawdown_halts": 0,
        "completed_cycles": 26,
        "days": 182,
        "months": 6,
        "baseline": F(0),
    }
    return score.Run(**{**values, **changes})


def both_paths(**changes):
    return [run(path=path, **changes) for path in PATH_MODES]


def yearly(annual):
    """The raw return in percent over 1461 days, four 365.25-day years, that annualises
    to exactly ``annual`` percent: the power is 1/4 there, and this ratio a fourth power,
    so the annualised return is rational and computed exactly."""
    return ((1 + F(annual) / 100) ** 4 - 1) * 100


def over_four_years(annual, **changes):
    """A 1461-day run whose annualised return is exactly ``annual`` percent; 209 cycles
    keep its C5 rate above 1."""
    return run(return_pct=yearly(annual), days=1461, completed_cycles=209, **changes)


def reference(return_pct, days):
    """The annualised return in percent from the same formula at 400 digits."""
    ratio, exponent = 1 + return_pct / 100, F(1461, 4 * days)
    with localcontext(Context(prec=400, rounding=ROUND_HALF_EVEN)):
        power = (Decimal(ratio.numerator) / ratio.denominator).ln() * exponent.numerator
        grown = (power / exponent.denominator).exp()
    return (F(grown) - 1) * 100


class CriterionTests(unittest.TestCase):
    def test_c1_passes_at_exactly_10_percent_on_both_bases(self) -> None:
        on_limit = run(max_drawdown_pct=F(10), active_max_drawdown_pct=F(10))
        self.assertTrue(score.worst_drop([on_limit]).passed)

    def test_c1_fails_just_above_10_percent_on_either_basis(self) -> None:
        above = F(10) + F(1, 10**15)
        for changes in ({"max_drawdown_pct": above}, {"active_max_drawdown_pct": above}):
            with self.subTest(**{k: str(v) for k, v in changes.items()}):
                result = score.worst_drop([run(**changes), run(path="low_first")])
                self.assertFalse(result.passed)
                self.assertEqual(result.failing, ("verify-2024h1 BTCUSDT high_first",))

    def test_c1_fails_on_any_hard_drawdown_halt(self) -> None:
        halted = run(hard_drawdown_halts=1, max_drawdown_pct=F(1), active_max_drawdown_pct=F(1))
        result = score.worst_drop([halted])
        self.assertFalse(result.passed)
        self.assertEqual(result.numbers["hard-drawdown halts"], 1)

    def test_c2_median_of_an_even_count_is_the_mean_of_the_middle_two(self) -> None:
        self.assertEqual(score.median([F(-1), F(3), F(1, 2), F(1)]), F(3, 4))
        self.assertEqual(score.median([F(5), F(-2), F(1)]), F(1))

    def test_c2_needs_both_path_medians_and_the_mean_annualised_return_above_zero(self) -> None:
        def runs(high, low):  # annualised returns in percent, exact
            return [over_four_years(a, path="high_first") for a in high] + [
                over_four_years(a, path="low_first") for a in low
            ]

        cases = {
            "passes": (runs([1, 2], [1, 3]), True),
            "a path median below zero": (runs([1, 2], ["-1", "0.5"]), False),
            "a path median exactly zero": (runs([-1, 1], [2, 2]), False),
            "the mean exactly zero": (runs([1, 1, -4], [1, 1]), False),
            "no runs on one path": (runs([1, 2], []), False),
        }
        for name, (case, expected) in cases.items():
            with self.subTest(name):
                self.assertEqual(score.makes_money(case).passed, expected)
        numbers = score.makes_money(runs([1, 2], ["-1", "0.5"])).numbers
        self.assertEqual(numbers["median annualised return % (low_first)"], F(-1, 4))
        self.assertEqual(numbers["mean annualised return %"], F(5, 8))

    def test_c2_judges_annualised_returns_not_raw_ones(self) -> None:
        # Over 2192 days +100% and -90% annualise to about +12.24% and -31.86%. Both path
        # medians of [+100, +100, -90] stay positive, but the annualised mean is about
        # -2.46%, though the raw mean is +36.7%.
        long = [
            run(path=path, return_pct=F(ret), days=2192, completed_cycles=400)
            for path in PATH_MODES
            for ret in (100, 100, -90)
        ]
        result = score.makes_money(long)
        self.assertFalse(result.passed)
        self.assertGreater(result.numbers["median annualised return % (high_first)"], 12)
        self.assertLess(result.numbers["mean annualised return %"], -2)
        # Over 182 days -1% and +1% annualise to about -1.997% and +2.017%, so a raw
        # median of exactly 0, which would fail, is a positive annualised one.
        short = [run(path=path, return_pct=F(ret)) for path in PATH_MODES for ret in (-1, 1)]
        self.assertTrue(score.makes_money(short).passed)

    def test_a_c2_decision_its_bound_cannot_settle_refuses(self) -> None:
        # At 1 significant digit (and the few more a 1% return adds) the bound is wider
        # than the return, so C2 cannot tell whether the median is above 0.
        with (
            patch.object(score, "ANNUALISING_DIGITS", 1),
            self.assertRaises(score.ScoringError) as raised,
        ):
            score.makes_money(both_paths())
        self.assertIn(
            "C2's median annualised return % (high_first) cannot be decided", str(raised.exception)
        )

    def test_c3_needs_a_drawdown_strictly_below_buy_and_hold(self) -> None:
        self.assertTrue(score.safer_than_holding([run()]).passed)
        equal = run(max_drawdown_pct=F(5), active_max_drawdown_pct=F(5))
        self.assertFalse(score.safer_than_holding([equal]).passed)
        flat = run(max_drawdown_pct=F(0), buy_and_hold_max_drawdown_pct=F(0))
        self.assertFalse(score.safer_than_holding([flat]).passed)

    def test_c4_fails_on_an_invalid_or_a_missing_run(self) -> None:
        self.assertTrue(score.integrity(both_paths()).passed)
        invalid = score.integrity([run(problems=("2 rejected frames",)), run(path="low_first")])
        self.assertFalse(invalid.passed)
        self.assertEqual(invalid.failing, ("verify-2024h1 BTCUSDT high_first: 2 rejected frames",))
        missing = score.integrity([run()], ["verify-2024h1 BTCUSDT low_first"])
        self.assertEqual(missing.failing, ("verify-2024h1 BTCUSDT low_first: missing",))
        self.assertEqual(missing.numbers["valid runs"], "1 of 2")

    def test_c5_mean_rate_is_exact_and_at_least_one(self) -> None:
        self.assertTrue(score.activity([run(completed_cycles=26)]).passed)
        self.assertFalse(score.activity([run(completed_cycles=25)]).passed)
        # 34 and 36 cycles in 245 days average exactly one a week.
        mixed = [run(completed_cycles=34, days=245), run(completed_cycles=36, days=245)]
        result = score.activity(mixed)
        self.assertTrue(result.passed)
        self.assertEqual(result.numbers["mean completed cycles per week"], F(1))
        self.assertFalse(score.activity(mixed[:1]).passed)

    def test_c6_needs_60_percent_of_runs_strictly_above_the_baseline(self) -> None:
        # Each run's ratio is 1 / 2; a baseline of 1/2 ties, which is not a win.
        wins = [run(baseline=F(2, 5)) for _ in range(3)]
        ties = [run(baseline=F(1, 2)) for _ in range(2)]
        self.assertTrue(score.gate(wins + ties).passed)
        result = score.gate(wins[:2] + ties + [run(baseline=F(1, 2))])
        self.assertFalse(result.passed)
        self.assertEqual(result.numbers["runs beating the baseline"], "2 of 5")

    def test_c6_floors_the_drawdown_at_one_tenth_of_a_point(self) -> None:
        self.assertEqual(run(return_pct=F(1, 20), max_drawdown_pct=F(0)).ratio, F(1, 2))
        self.assertEqual(run(return_pct=F(1), max_drawdown_pct=F(1, 20)).ratio, F(10))

    def test_c6_and_r1_keep_raw_returns(self) -> None:
        # +1% over 182 days annualises to about +2.017%, but C6's ratio and R1 use 1%.
        self.assertEqual(run().ratio, F(1, 2))
        self.assertEqual(score.economics([run()])["mean monthly return %"], F(1, 6))

    def test_c6_counts_an_unavailable_baseline_against_the_variant(self) -> None:
        lost = run(baseline=None, baseline_problem="no ungated V0 baseline row")
        result = score.gate([run(baseline=F(0)), run(baseline=F(0)), lost, lost])
        self.assertFalse(result.passed)
        self.assertIn(
            "verify-2024h1 BTCUSDT high_first: no ungated V0 baseline row", result.failing
        )

    def test_every_criterion_fails_without_runs(self) -> None:
        result = score.score_variant("V0", [], ["verify-2024h1 BTCUSDT high_first"])
        self.assertEqual([c.passed for c in result.criteria], [False] * 6)

    def test_r1_divides_five_by_the_mean_monthly_return(self) -> None:
        # 3% and 1% over six months: a mean monthly fraction of 1/300.
        r1 = score.economics([run(return_pct=F(3)), run(return_pct=F(1))])
        self.assertEqual(r1[score.R1_CAPITAL], F(1500))
        self.assertEqual(r1["mean monthly return %"], F(1, 3))

    def test_r1_is_not_reachable_at_or_below_zero_by_calendar_month(self) -> None:
        # +8% over 8 months and -6% over 6 months: the mean window return is +1%, but
        # the mean monthly return is exactly 0.
        runs = [run(return_pct=F(8), months=8), run(return_pct=F(-6), months=6)]
        self.assertEqual(score.economics(runs)[score.R1_CAPITAL], "not reachable")


class AnnualisingTests(unittest.TestCase):
    def test_annualising_compounds_over_a_365_25_day_year(self) -> None:
        # Over 1461 days the power is 1/4 and over 487 days 3/4, so these are exact.
        cases = {
            (F(1500), 1461): F(100),
            (yearly(10), 1461): F(10),
            (yearly(-10), 1461): F(-10),
            (F(1500), 487): F(700),
            (F(0), 2192): F(0),
        }
        for (ret, days), expected in cases.items():
            with self.subTest(ret=str(ret), days=days):
                self.assertEqual(score.annualise(ret, days), (expected, F(0)))

    def test_a_final_equity_of_zero_or_less_annualises_to_minus_100(self) -> None:
        for ret in (F(-100), F(-150), F(-(10**9))):
            for days in score.REGISTERED_DAYS.values():
                with self.subTest(ret=str(ret), days=days):
                    self.assertEqual(score.annualise(ret, days), (F(-100), F(0)))
        self.assertEqual(run(return_pct=F(-100)).annualised, (F(-100), F(0)))

    def test_an_irrational_annualised_return_lies_within_its_bound(self) -> None:
        returns = ("1", "-1", "350", "-99.99", "1e-40", "-1e-40")
        returns += ("12.345678901234567890123456789012345678901234567890",)
        for days in score.REGISTERED_DAYS.values():
            for text in returns:
                ret = F(Decimal(text))
                value, bound = score.annualise(ret, days)
                with self.subTest(days=days, ret=text):
                    self.assertGreater(bound, 0)
                    self.assertLess(bound, (1 + abs(value)) / 10**50)
                    self.assertLessEqual(abs(value - reference(ret, days)), bound)

    def test_the_bound_encloses_the_exact_power_in_integers(self) -> None:
        # y = x ** (a / b) exactly when y ** b = x ** a, so an enclosure [low, high] of y
        # needs low ** b <= x ** a <= high ** b, checked in exact rationals. The short
        # windows' denominators, 728 and 980, keep these powers quick.
        for days in (182, 245):
            exponent = F(1461, 4 * days)
            for text in ("1", "-1", "12.345678901234567890123456789"):
                ret = F(Decimal(text))
                value, bound = score.annualise(ret, days)
                with self.subTest(days=days, ret=text):
                    power = (1 + ret / 100) ** exponent.numerator
                    self.assertLessEqual((1 + (value - bound) / 100) ** exponent.denominator, power)
                    self.assertLessEqual(power, (1 + (value + bound) / 100) ** exponent.denominator)

    def test_annualising_never_changes_a_runs_sign(self) -> None:
        for text in ("1e-70", "-1e-70", "1e-20", "-1e-20", "5", "-5", "200", "-99.9999"):
            for days in score.REGISTERED_DAYS.values():
                ret = F(Decimal(text))
                value, bound = score.annualise(ret, days)
                with self.subTest(ret=text, days=days):
                    # The whole enclosure keeps the sign, so no decision on it is lost.
                    if ret > 0:
                        self.assertGreater(value - bound, 0)
                    else:
                        self.assertLess(value + bound, 0)

    def test_integer_roots_are_exact(self) -> None:
        big = 12345678901234567890
        cases = {
            (0, 3): 0,
            (1, 728): 1,
            (101**4, 4): 101,
            (101**4 - 1, 4): 100,
            (10**60, 728): 1,
            (2**728, 728): 2,
            (big**7, 7): big,
            (big**7 + 1, 7): big,
            (big**7 - 1, 7): big - 1,
        }
        for (number, degree), root in cases.items():
            with self.subTest(degree=degree, root=root):
                self.assertEqual(score.integer_root(number, degree), root)

    def test_a_decision_stands_only_when_both_ends_of_its_enclosure_agree(self) -> None:
        tiny = F(1, 10**60)
        self.assertTrue(score.certain(score.positive, tiny, F(1), "x"))
        self.assertFalse(score.certain(score.positive, F(-1), F(0), "x"))  # 0 is not above 0
        with self.assertRaises(score.ScoringError):
            score.certain(score.positive, -tiny, tiny, "x")
        # A rounding to 6 decimals, the selection's, decides alike.
        half = F(5, 10**7)

        def six(value):
            return score.rounded(value, 6)

        self.assertEqual(score.certain(six, half + tiny, half + 2 * tiny, "x"), Decimal("0.000001"))
        with self.assertRaises(score.ScoringError):
            score.certain(six, half - tiny, half + tiny, "x")


class NumberTests(unittest.TestCase):
    def test_rounding_is_exact_and_half_away_from_zero(self) -> None:
        self.assertEqual(score.rounded(F(5, 10**7), 6), Decimal("0.000001"))
        self.assertEqual(score.rounded(F(-5, 10**7), 6), Decimal("-0.000001"))
        self.assertEqual(score.rounded(F(49, 10**8), 6), Decimal("0.000000"))
        self.assertEqual(score.rounded(F(1, 3), 6), Decimal("0.333333"))
        self.assertEqual(score.rounded(F(2, 3), 6), Decimal("0.666667"))

    def test_exact_writes_a_decimal_where_it_terminates_and_p_over_q_otherwise(self) -> None:
        expected = {F(1, 4): "0.25", F(10): "10", F(-5, 2): "-2.5", F(1, 3): "1/3"}
        for value, text in expected.items():
            with self.subTest(text):
                self.assertEqual(score.exact(value), text)
                self.assertEqual(F(score.exact(value)), value)

    def test_no_digit_is_lost_beyond_the_decimal_context(self) -> None:
        # The simulator settles at precision 50, so a recorded equity can have more than
        # the 28 digits of Decimal arithmetic.
        text = "-0.12345678901234567890123456789012345678901234"
        self.assertEqual(score.exact(F(Decimal(text))), text)
        self.assertEqual(score.rounded(F(10**40 + 1, 10), 1), Decimal("1" + "0" * 39 + ".1"))
        self.assertEqual(str(score.rounded(F(-1, 10**9), 6)), "0.000000")  # no "-0"


def passing(variant, annual, drawdown=F(2)):
    """A score that passes C1-C6 with this mean annualised return, exact over 1461-day
    runs, and this mean max drawdown."""
    return score.score_variant(
        variant,
        [
            over_four_years(
                annual,
                path=path,
                max_drawdown_pct=F(drawdown),
                active_max_drawdown_pct=F(drawdown),
                baseline=F(-1000),
            )
            for path in PATH_MODES
        ],
    )


class SelectionTests(unittest.TestCase):
    def test_the_best_mean_return_wins_beyond_the_tie_margin(self) -> None:
        result = score.select([passing("V0", "1.5", 1), passing("A", 2, 3)])
        self.assertEqual((result.outcome, result.winner, result.tie_set), ("winner", "A", ("A",)))

    def test_the_tie_set_includes_exactly_025_below_the_best(self) -> None:
        tied = score.select([passing("V0", "1.75", 1), passing("A", 2, 3)])
        self.assertEqual((tied.winner, tied.tie_set), ("V0", ("V0", "A")))
        outside = score.select([passing("V0", "1.749999", 1), passing("A", 2, 3)])
        self.assertEqual(outside.winner, "A")

    def test_mean_returns_are_rounded_to_6_decimals_half_up_before_comparing(self) -> None:
        # 2.0000004 rounds to 2.000000, so 1.75 is within 0.25 of it; unrounded it is not.
        down = score.select([passing("A", "2.0000004", 3), passing("B", "1.75", 1)])
        self.assertEqual(down.winner, "B")
        # 2.0000005 rounds half up to 2.000001, which puts 1.75 outside the tie set.
        up = score.select([passing("A", "2.0000005", 3), passing("B", "1.75", 1)])
        self.assertEqual(up.winner, "A")
        self.assertEqual(up.figures["A"], (Decimal("2.000001"), Decimal("3.000000")))

    def test_the_tie_band_applies_to_the_mean_annualised_return(self) -> None:
        # Annualised 10% and 9.75% tie, inclusive, though their raw returns over 1461 days
        # (46.41% and about 45.08%) lie 1.33 points apart; the lower drawdown wins.
        tied = score.select([passing("A", 10, 3), passing("B", "9.75", 1)])
        self.assertEqual((tied.winner, tied.tie_set), ("B", ("A", "B")))
        self.assertEqual(tied.figures["B"][0], Decimal("9.750000"))

        # Raw 1% and 1.2% over 182 days lie 0.2 points apart, but annualised (about
        # 2.017% and 2.423%) more than 0.25: no tie, so the lower drawdown does not win.
        def short(variant, ret, drawdown):
            changes = {"max_drawdown_pct": F(drawdown), "active_max_drawdown_pct": F(drawdown)}
            return score.score_variant(
                variant, both_paths(return_pct=F(ret), baseline=F(-1000), **changes)
            )

        apart = score.select([short("A", 1, 1), short("B", "1.2", 3)])
        self.assertEqual((apart.winner, apart.tie_set), ("B", ("B",)))
        self.assertEqual(apart.figures["A"][0], Decimal("2.016972"))

    def test_a_drawdown_tie_goes_to_the_simplicity_order(self) -> None:
        self.assertEqual(score.select([passing(v, 1) for v in ("C", "F", "B")]).winner, "B")
        # F precedes C in the simplicity order, though C comes first in section 4.
        self.assertEqual(score.select([passing("C", 1), passing("F", 1)]).winner, "F")

    def test_the_variants_and_the_simplicity_order_are_the_registered_ones(self) -> None:
        # Spec v1 section 4's variant list and section 6 step 4's order, amendment 4.
        self.assertEqual(
            score.VARIANTS,
            ("V0", "A", "B", "C", "D", "E", "F", "G", "C+G", "H", "C+H", "V2", "C+F+G+H+V2"),
        )
        self.assertEqual(
            score.SIMPLICITY_ORDER,
            ("V0", "A", "B", "F", "G", "H", "E", "V2", "C", "C+G", "C+H", "C+F+G+H+V2"),
        )

    def test_v2_follows_e_and_the_full_stack_comes_last(self) -> None:
        def winner(*variants):
            return score.select([passing(v, 1) for v in variants]).winner

        self.assertEqual(winner("C+F+G+H+V2", "C", "V2"), "V2")
        self.assertEqual(winner("V2", "H"), "H")
        self.assertEqual(winner("C+F+G+H+V2", "C+H"), "C+H")
        self.assertEqual(winner("C+F+G+H+V2"), "C+F+G+H+V2")  # selectable on its own
        with patch.object(score, "E_ELIGIBLE", True):
            self.assertEqual(winner("V2", "E"), "E")

    def test_drawdowns_equal_after_rounding_are_a_tie(self) -> None:
        result = score.select([passing("C", 1, "3.0000001"), passing("F", 1, "3.0000004")])
        self.assertEqual(result.winner, "F")

    def test_d_is_never_selected(self) -> None:
        result = score.select([passing("D", 5), passing("V0", 1)])
        self.assertEqual(result.winner, "V0")
        self.assertNotIn("D", result.figures)

    def test_e_is_eligible_since_codex_reviewed_it_and_not_without_that_review(self) -> None:
        # Section 3 E records Codex's implementation review (#165), so E is eligible.
        scores = [passing("E", 5), passing("V0", 1)]
        self.assertTrue(score.E_ELIGIBLE)
        self.assertEqual(score.select(scores).winner, "E")
        with patch.object(score, "E_ELIGIBLE", False):
            self.assertEqual(score.select(scores).winner, "V0")

    def test_a_failing_variant_is_not_eligible(self) -> None:
        unsafe = score.score_variant(
            "A", both_paths(return_pct=F(9), baseline=F(-1000), buy_and_hold_max_drawdown_pct=F(1))
        )
        self.assertFalse(unsafe.passed)
        self.assertEqual(score.select([unsafe, passing("V0", 1)]).winner, "V0")
        no_winner = score.select([unsafe])
        self.assertEqual((no_winner.outcome, no_winner.winner), ("no winner", None))


class VariantTests(unittest.TestCase):
    """Spec v1 section 3: which result rows are which registered variant."""

    def test_v2_and_the_full_stack_are_the_structure_rows_the_engine_writes(self) -> None:
        # V2 is V0 with --structure: no variant field. The full stack (--variant-full)
        # names the variant C+F+G+H. Both carry V2's features label.
        self.assertEqual(score.variant_of({"strategy": score.STRUCTURE_GRID}), "V2")
        full = {"strategy": score.STRUCTURE_GRID, "variant": FULL_STACK}
        self.assertEqual(score.variant_of(full), "C+F+G+H+V2")
        # The name is the one the engine writes on a full-stack row.
        policy = jobs.variant_policy(FULL_STACK, structure=True)
        self.assertEqual(("C+F+G+H", FULL_STACK), (jobs.variant_name(policy), policy.variant))
        self.assertEqual(score.STRUCTURE_GRID, f"gated grid ({STRUCTURE_FEATURE_VERSION})")

    def test_other_structure_rows_are_refused(self) -> None:
        refused = [
            {"strategy": score.STRUCTURE_GRID, "variant": name}
            for name in ("A", "C", "C+G", "C+H", "E", "C+F+G+H+V2", "V2", "")
        ]
        refused += [
            {"strategy": score.GRID, "variant": FULL_STACK},  # the full stack without V2
            {"strategy": score.GRID, "variant": "V2"},
            {"strategy": f"ungated grid baseline ({STRUCTURE_FEATURE_VERSION})"},
        ]
        for row in refused:
            with self.subTest(**row), self.assertRaises(score.ScoringError):
                score.variant_of(row)

    def test_a_structure_files_features_must_be_v2s_with_v0s_baseline(self) -> None:
        rows = [{"strategy": score.STRUCTURE_GRID}, {"strategy": score.BASELINE}]
        structure = {"feature_version": STRUCTURE_FEATURE_VERSION, "results": rows}
        structure["baseline_feature_version"] = FEATURE_VERSION
        self.assertEqual(score.feature_problems(structure), [])
        without = {k: v for k, v in structure.items() if k != "baseline_feature_version"}
        self.assertIn("features", score.feature_problems(without)[0])
        mixed = {**structure, "results": [*rows, {"strategy": score.GRID, "variant": "A"}]}
        self.assertIn("gated rows", score.feature_problems(mixed)[0])
        plain = {"feature_version": FEATURE_VERSION, "results": [{"strategy": score.GRID}]}
        self.assertEqual(score.feature_problems(plain), [])
        self.assertIn("gated rows", score.feature_problems({**plain, "results": rows})[0])


def clean_checks(spec):
    """Passing integrity checks, one per symbol the CLI checks for ``spec``."""
    checks = []
    for symbol in cli.checked_symbols(spec):
        if symbol in spec.traded:
            check = {"symbol": symbol, "hours_compared": 24, "hours_volume_drift": 0}
            check |= dict.fromkeys(cli.INTEGRITY_FIELDS, 0)
            check |= {"daily_days_compared": 30, "daily_days_volume_drift": 0}
            check |= {"daily_warmup_days": 230, **dict.fromkeys(cli.DAILY_INTEGRITY_FIELDS, 0)}
        else:
            check = {"symbol": symbol, "role": "breadth_basket", "series_hours_present": 24}
            check |= {"series_hours_missing": 0, "series_hours_duplicated": 0}
            check |= {"series_hours_excluded": 0}
        checks.append(check)
    return checks


# Spec v1 section 4's frozen definitions of the two stage-2 windows: warm-ups, evaluation
# starts and the basket exclusions, each ending at the symbol's first candle. Every other
# field is LONG_SPEC's.
LONG_WINDOWS = {
    "full-range-2017-2024": (
        ("2018-06", "2018-06", "2019-01"),
        [
            ("SOLUSDT", "2018-06-01T00:00Z", "2020-08-11T06:00Z", "listing"),
            ("DOGEUSDT", "2018-06-01T00:00Z", "2019-07-05T12:00Z", "listing"),
            ("LINKUSDT", "2018-06-01T00:00Z", "2019-01-16T10:00Z", "listing"),
            ("TRXUSDT", "2018-06-01T00:00Z", "2018-06-11T11:00Z", "listing"),
            ("DOGEUSDT", "2020-02-01T00:00Z", "2020-03-01T00:00Z", "section 5 rule 5"),
        ],
    ),
    "full-range-2019-2024": (
        ("2018-07", "2019-01", "2019-07"),
        [
            ("SOLUSDT", "2019-01-01T00:00Z", "2020-08-11T06:00Z", "listing"),
            ("DOGEUSDT", "2019-01-01T00:00Z", "2019-07-05T12:00Z", "listing"),
            ("LINKUSDT", "2019-01-01T00:00Z", "2019-01-16T10:00Z", "listing"),
            ("DOGEUSDT", "2020-02-01T00:00Z", "2020-03-01T00:00Z", "section 5 rule 5"),
        ],
    ),
}
LONG_SPEC = """name = "{name}"
purpose = "synthetic stage-2 window for the scorer's tests"
traded = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = [
  "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
  "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT",
]
daily_warmup_start = "{daily}"
warmup_start = "{warmup}"
start = "{start}"
end = "2024-12"
initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""
EXCLUSION = """
[[basket_exclusions]]
symbol = "{}"
from = "{}"
to = "{}"
reason = "{}"
"""


def write_datasets(directory):
    """Copies of the committed stage-1 dataset specs and manifests, and synthetic ones of
    the stage-2 windows (the manifests are stubs: the scorer only hashes them)."""
    for name in STAGE_1:
        for suffix in (".toml", ".manifest.json"):
            shutil.copyfile(SPECS / f"{name}{suffix}", directory / f"{name}{suffix}")
    for name, ((daily, warmup, start), exclusions) in LONG_WINDOWS.items():
        text = LONG_SPEC.format(name=name, daily=daily, warmup=warmup, start=start)
        text += "".join(EXCLUSION.format(*exclusion) for exclusion in exclusions)
        (directory / f"{name}.toml").write_text(text)
        (directory / f"{name}.manifest.json").write_text('{"synthetic": "stage-2 stub"}\n')


class MaskTests(unittest.TestCase):
    def test_the_stage_1_windows_have_the_specs_c5_and_r1_lengths(self) -> None:
        for name, days, months in (("verify-2024h1", 182, 6), ("practice-2022", 245, 8)):
            with self.subTest(name):
                spec = load_spec(SPECS / f"{name}.toml")
                window = score.window_of(spec, clean_checks(spec))
                self.assertEqual((window.days, window.months), (days, months))
                self.assertEqual(window.days, score.REGISTERED_DAYS[name])

    def test_the_stage_2_windows_have_the_registered_lengths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            write_datasets(Path(directory))
            for name, months in (("full-range-2017-2024", 72), ("full-range-2019-2024", 66)):
                with self.subTest(name):
                    spec = load_spec(Path(directory) / f"{name}.toml")
                    window = score.window_of(spec, clean_checks(spec))
                    self.assertEqual(
                        (window.days, window.months), (score.REGISTERED_DAYS[name], months)
                    )
                    self.assertEqual(window.included, ("BTCUSDT", "ETHUSDT", "XRPUSDT"))

    def test_scorer_excludes_the_same_xrp_window(self) -> None:
        # Section 5 rule 8: a replayed XRP quote that breaks the tick limit puts
        # tick_limit_quotes in XRPUSDT's cross-check record, which scoped_failures makes its
        # own failure. window_of excludes that pair-window as it does any failed check, with
        # no hook of its own (data_rule_exclusions stays empty), and no XRP run is then
        # expected: the matrix wants rows from the two included pairs only. A failed hour
        # still fails its check and excludes the pair-window, as in stage 1.
        with tempfile.TemporaryDirectory() as directory:
            write_datasets(Path(directory))
            spec = load_spec(Path(directory) / "full-range-2017-2024.toml")
            for pair in spec.traded:
                self.assertEqual(score.data_rule_exclusions(spec, pair), [])
            checks = clean_checks(spec)
            window = score.window_of(spec, checks)
            self.assertEqual(window.included, ("BTCUSDT", "ETHUSDT", "XRPUSDT"))
            xrp = next(c for c in checks if c["symbol"] == "XRPUSDT")
            xrp["tick_limit_quotes"] = 3
            window = score.window_of(spec, checks)
            self.assertEqual(window.excluded, {"XRPUSDT": ("XRPUSDT: tick_limit_quotes=3",)})
            self.assertEqual(window.included, ("BTCUSDT", "ETHUSDT"))
            for pair in spec.traded:
                self.assertEqual(score.data_rule_exclusions(spec, pair), [])
            # The results file the CLI writes for it has no XRP rows, and one that kept them
            # would have them left out: either way the scorer's runs are BTC's and ETH's.
            dataset = "full-range-2017-2024"
            rows = rows_for(dataset, "V0", directory=Path(directory))
            for kept in (rows, [r for r in rows if r["symbol"] != "XRPUSDT"]):
                written = document(dataset, kept, Path(directory), hourly_cross_checks=checks)
                # As the scorer reads a file: floats as Decimals.
                results = json.loads(json.dumps(written, default=str), parse_float=Decimal)
                runs = list(score.runs_of(results, window))
                self.assertEqual({run.symbol for _, run in runs}, {"BTCUSDT", "ETHUSDT"})
                self.assertEqual(len(runs), 4)  # two pairs, two paths
            # The stage wants the two included pairs' runs only, so none is missing.
            found = {"V0": {run.key: run for _, run in runs}}
            judged = score.judge(score.STAGE_2, {dataset: window}, {dataset: {"V0"}}, found)
            (v0,) = judged.scores
            self.assertEqual((v0.variant, len(v0.runs), v0.missing), ("V0", 4, ()))
            # Another failure of XRP's check joins the breach in its reasons.
            xrp["hours_incomplete"] = 1
            window = score.window_of(spec, checks)
            reasons = ("XRPUSDT: hours_incomplete=1", "XRPUSDT: tick_limit_quotes=3")
            self.assertEqual(window.excluded, {"XRPUSDT": reasons})
            del xrp["tick_limit_quotes"]
            window = score.window_of(spec, checks)
            self.assertEqual(window.excluded, {"XRPUSDT": ("XRPUSDT: hours_incomplete=1",)})

    def test_window_of_is_unchanged_without_the_new_keys(self) -> None:
        # Spec v1 section 6, decision 18: the long-window data code leaves acceptance.py's
        # code as it is. On cross-checks that carry none of the fields that code adds, as
        # every stage-1 record does, window_of gives each stage-1 window its pairs and its
        # exclusions exactly as before. A day the daily check skips for a mask is a count,
        # not a failure: it excludes nothing. Stage 1's own files are not in the
        # repository; the stage-1 identity check (scripts/stage1_identity.py) reads them.
        added = {"daily_days_skipped_for_masks", "tick_limit_quotes"}
        sol = (score.FILTER_EXCLUSIONS["practice-2022", "SOLUSDT"],)
        for name, days, included, excluded in (
            ("verify-2024h1", 182, ("ADAUSDT", "BTCUSDT"), {}),
            ("practice-2022", 245, ("BTCUSDT", "XRPUSDT"), {"SOLUSDT": sol}),
        ):
            with self.subTest(name):
                spec = load_spec(SPECS / f"{name}.toml")
                checks = clean_checks(spec)
                self.assertFalse(added & {field for check in checks for field in check})
                window = score.window_of(spec, checks)
                self.assertEqual(
                    score.Window(name, spec.traded, excluded, days, len(spec.months(spec.start))),
                    window,
                )
                self.assertEqual(included, window.included)
                for check in checks:
                    if "daily_days_compared" in check:
                        check["daily_days_skipped_for_masks"] = 3
                self.assertEqual(window, score.window_of(spec, checks))

    def test_practice_2022_sol_fails_the_filter_check_for_every_variant(self) -> None:
        spec = load_spec(SPECS / "practice-2022.toml")
        window = score.window_of(spec, clean_checks(spec))
        self.assertEqual(window.included, ("BTCUSDT", "XRPUSDT"))
        self.assertIn("P4", window.excluded["SOLUSDT"][0])

    def test_a_failed_check_excludes_the_pairs_it_feeds(self) -> None:
        spec = DatasetSpec(
            name="synthetic",
            purpose="test",
            traded=("AAAUSDT", "BBBUSDT"),
            market_proxy="AAAUSDT",
            breadth_basket=("AAAUSDT", "BBBUSDT", "CCCUSDT"),
            warmup_start="2023-01",
            start="2023-03",
            end="2023-04",
            initial_quote=Decimal(100),
            fee_rate=Decimal(0),
            slippage_rate=Decimal("0.0005"),
            participation=Decimal("0.10"),
            assumed_spread_pct=Decimal("0.05"),
        )
        for symbol, field, excluded in (
            # A traded pair's own check: that pair only, though it also votes in the basket.
            ("BBBUSDT", "minutes_missing", {"BBBUSDT"}),
            ("CCCUSDT", "series_hours_missing", {"AAAUSDT", "BBBUSDT"}),  # breadth: every pair
            ("AAAUSDT", "hours_mismatched", {"AAAUSDT", "BBBUSDT"}),  # the proxy: every pair
        ):
            with self.subTest(symbol):
                checks = clean_checks(spec)
                next(c for c in checks if c["symbol"] == symbol)[field] = 1
                window = score.window_of(spec, checks)
                self.assertEqual(set(window.excluded), excluded)
                self.assertEqual(window.days, 61)

    def test_a_traded_pairs_own_failure_excludes_only_that_pair(self) -> None:
        # Codex's case: SOLUSDT also votes in practice-2022's basket, and its minute
        # failure must not take BTCUSDT and XRPUSDT with it.
        spec = load_spec(SPECS / "practice-2022.toml")
        checks = clean_checks(spec)
        next(c for c in checks if c["symbol"] == "SOLUSDT")["minutes_missing"] = 1
        window = score.window_of(spec, checks)
        self.assertEqual(window.included, ("BTCUSDT", "XRPUSDT"))
        self.assertEqual(window.excluded["SOLUSDT"][0], "SOLUSDT: minutes_missing=1")
        # BTCUSDT is the market proxy, but its minutes feed only its own runs (Codex's
        # review of #170): a minute failure excludes it alone. One in its hours, which
        # feed every pair, excludes every pair.
        btc = next(c for c in checks if c["symbol"] == "BTCUSDT")
        btc["minutes_missing"] = 1
        window = score.window_of(spec, checks)
        self.assertEqual(window.included, ("XRPUSDT",))
        self.assertEqual(window.excluded["BTCUSDT"], ("BTCUSDT: minutes_missing=1",))
        btc["hours_missing"] = 1
        self.assertEqual(score.window_of(spec, checks).included, ())

    def test_a_traded_proxys_failure_reaches_every_pair_only_through_its_hours(self) -> None:
        # verify-2024h1 trades ADAUSDT and BTCUSDT, the market proxy. A failure that leaves
        # a proxy hour missing, in doubt or unchecked (a 1m or 1d bar that disagrees with
        # it, no minutes behind it, no hour compared at all) excludes both pairs. Any other
        # failure of its 1m or 1d bars excludes BTCUSDT alone.
        spec = load_spec(SPECS / "verify-2024h1.toml")
        shared = (
            "hours_compared",
            "hours_mismatched",
            "hours_missing",
            "hours_absent_from_minutes",
            "hours_absent_from_both",
            "daily_days_mismatched",
            "daily_days_hours_incomplete",
        )
        own = (
            "minutes_missing",
            "hours_incomplete",
            "daily_days_missing",
            "daily_days_duplicated",
            "daily_warmup_short",
            "daily_days_compared",
        )
        cases = [(field, {"ADAUSDT", "BTCUSDT"}) for field in shared]
        cases += [(field, {"BTCUSDT"}) for field in own]
        for field, excluded in cases:
            with self.subTest(field):
                checks = clean_checks(spec)
                value = 0 if field.endswith("_compared") else 1
                next(c for c in checks if c["symbol"] == "BTCUSDT")[field] = value
                window = score.window_of(spec, checks)
                self.assertEqual(set(window.excluded), excluded)
                reason = {
                    "hours_compared": "BTCUSDT: no hours compared",
                    "daily_days_compared": "BTCUSDT: no daily bars compared",
                }.get(field, f"BTCUSDT: {field}=1")
                self.assertEqual(window.excluded["BTCUSDT"], (reason,))

    def test_checks_must_be_one_per_checked_symbol(self) -> None:
        spec = load_spec(SPECS / "verify-2024h1.toml")
        with self.assertRaises(score.ScoringError):
            score.window_of(spec, clean_checks(spec)[1:])


# File-level tests: synthetic results.json files as the backtest CLI writes them.

# The rows' labels by variant: V2 and the full stack are --structure runs, with V2's
# features label, and the full stack's rows name the variant C+F+G+H (--variant-full).
STRATEGIES = {
    "ungated": score.BASELINE,
    "D": BENCHMARK,
    "V2": score.STRUCTURE_GRID,
    "C+F+G+H+V2": score.STRUCTURE_GRID,
}
VARIANT_FIELDS = {"V0": None, "ungated": None, "V2": None, "C+F+G+H+V2": FULL_STACK}


def row(symbol, path, variant="V0", ret="1", dd=2.0, **changes):
    """One result row. ``variant`` "ungated" is the ungated V0 baseline."""
    data = {
        "symbol": symbol,
        "path_mode": path,
        "strategy": STRATEGIES.get(variant, score.GRID),
        "initial_quote": "100",
        "final_total_equity": str(Decimal(100) + Decimal(ret)),
        "return_pct": float(ret),
        "max_drawdown_pct": dd,
        "active_max_drawdown_pct": dd,
        "buy_and_hold_max_drawdown_pct": 5.0,
        "hard_drawdown_halts": 0,
        "completed_cycles": 40,
        "completed_cycles_by_week": {"2024-W01": 40},
        "time_with_inventory_pct": 12.5,
        "accounting_problems": [],
        "transient_pauses": 0,
        "bars": 100,
        "final_exit_blocked": None,
        "final_unsellable_notional": "0",
        "rules": {
            "symbol": symbol,
            "tick_size": "0.01",
            "quantity_step": "0.001",
            "minimum_notional": "5",
            "fee_rate": "0",
            "slippage_rate": "0.0005",
            "participation": "0.10",
            "taker_fee_rate": "0.0009",
        },
        "assumed_spread_pct": "0.05",
    }
    field = VARIANT_FIELDS.get(variant, variant)
    if field is not None:
        data["variant"] = field
    return data | changes


def document(dataset, rows, directory=SPECS, **changes):
    """A results.json as the CLI writes it; a --structure run's records V2's features,
    and V0's for its ungated baseline rows."""
    spec_path = directory / f"{dataset}.toml"
    structure = any(r["strategy"] == score.STRUCTURE_GRID for r in rows)
    failures = cli.result_failures(rows)
    data = {
        "dataset": dataset,
        "purpose": "synthetic",
        "feature_version": STRUCTURE_FEATURE_VERSION if structure else FEATURE_VERSION,
        **({"baseline_feature_version": FEATURE_VERSION} if structure else {}),
        "engine_version": ENGINE_VERSION,
        "manifest_created_at": "synthetic",
        "spec_sha256": sha256_file(spec_path),
        "manifest_sha256": sha256_file(directory / f"{dataset}.manifest.json"),
        "config_sha256": FROZEN_CONFIG,
        "code_commit": FROZEN_COMMIT,
        "code_sha256": jobs.SOURCE_IDENTITY,
        "integrity_rules": {"version": INTEGRITY_RULES, "volume_drift_tolerance": "0.001"},
        "fees": {"maker": "0", "taker": "0.0009"},
        "valid": not failures,
        "failures": failures,
        "hourly_cross_checks": clean_checks(load_spec(spec_path)),
        "results": rows,
    }
    return data | changes


# Each variant's raw return % in every window of the synthetic matrix, unless a test sets
# its own. A clears the others by more than the tie margin; E would clear A, but E is not
# eligible.
RETURNS = {"A": "2", "E": "3"}
# Completed cycles per run: at least one a week in each window's C5 length.
CYCLES = {STAGE_1[0]: 40, STAGE_1[1]: 40, LONG[0]: 400, LONG[1]: 400}


def rows_for(dataset, variant, ret="1", directory=SPECS):
    """A variant's rows over every traded pair and path. SOLUSDT has rejected frames in
    practice-2022, as its unsourced filters cause."""
    spec = load_spec(directory / f"{dataset}.toml")
    rows = []
    for pair in spec.traded:
        for path in PATH_MODES:
            rejected = int(dataset == "practice-2022" and pair == "SOLUSDT")
            usual = {"transient_pauses": rejected, "completed_cycles": CYCLES[dataset]}
            if variant == "ungated":
                rows.append(row(pair, path, variant, "-1", 4.0, **usual))
            elif variant == "D":  # not a grid: D's rows count no cycles (P7)
                rows.append(row(pair, path, "D", "1", completed_cycles=0, transient_pauses=0))
            else:
                rows.append(row(pair, path, variant, ret, **usual))
    return rows


def matrix(variants=score.VARIANTS, windows=STAGE_1, returns=(), directory=SPECS):
    """One results.json per variant and window, as the CLI writes them: D shares V0's
    (``run --trend-benchmark``), and every file carries the ungated baseline rows.
    ``returns`` maps (window, variant) to that variant's raw return % there."""
    returns = dict(returns)
    documents = {}
    for dataset in windows:
        for variant in variants:
            if variant == "D":
                continue
            names = [variant, "D"] if variant == "V0" and "D" in variants else [variant]
            rows = []
            for name in [*names, "ungated"]:
                ret = returns.get((dataset, name), RETURNS.get(name, "1"))
                rows += rows_for(dataset, name, ret, directory)
            documents[dataset, variant] = document(dataset, rows, directory)
    return documents


class ScorerFiles(unittest.TestCase):
    """Writes results files to a temporary directory and runs the scorer on them, giving
    it the synthetic commit as its own."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.out = self.tmp / "verdict.json"
        commit = patch.object(score, "code_commit", return_value=FROZEN_COMMIT)
        commit.start()
        self.addCleanup(commit.stop)

    def write(self, documents):
        paths = []
        for data in documents:
            directory = Path(tempfile.mkdtemp(dir=self.tmp))
            (directory / "results.json").write_text(json.dumps(data, indent=1, default=str))
            paths.append(str(directory))
        return paths

    def run_scorer(self, documents, invocation="--early-read"):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = score.main([*self.write(documents), invocation, "--out", str(self.out)])
        verdict = json.loads(self.out.read_text()) if self.out.exists() else None
        return code, stdout.getvalue(), stderr.getvalue(), verdict

    def refused(self, documents, reason, invocation="--early-read"):
        code, _, stderr, verdict = self.run_scorer(documents, invocation)
        self.assertEqual(code, 2)
        self.assertIn(reason, stderr)
        self.assertNotIn("stages", verdict)
        selection = verdict["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("refused", None))
        self.assertTrue(any(reason in line for line in selection["reasons"]))


class FileTests(ScorerFiles):
    def test_the_early_read_says_which_variants_pass_stage_1_and_names_no_winner(self) -> None:
        code, text, _, verdict = self.run_scorer(matrix().values())
        self.assertEqual(code, 0)
        self.assertEqual(verdict["invocation"], "early read")
        selection = verdict["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("early read", None))
        self.assertEqual(selection["reasons"], [score.EARLY_READ_NOTE])
        passing = ["V0", "A", "B", "C", "E", "F", "G", "C+G", "H", "C+H", "V2", "C+F+G+H+V2"]
        self.assertEqual(selection["qualified"], passing)  # D has no cycles
        self.assertEqual((selection["eligible"], selection["tie_set"]), ({}, []))
        self.assertIn("Selection (spec v1 section 6, early read): early read", text)
        self.assertIn("- passing stage 1: " + ", ".join(passing), text)
        self.assertNotIn("Selection (spec v1 section 6, early read): winner", text)
        self.assertIn(score.C7_NOTE, text)
        text.encode("ascii")  # any console can print it
        self.assertEqual(list(verdict["stages"]), ["stage 1"])
        stage = verdict["stages"]["stage 1"]
        self.assertEqual((stage["complete"], stage["passing"]), (True, passing))
        # The mask excludes practice-2022 SOLUSDT for every variant, so its rejected
        # frames fail no variant's C4; each variant has 2 + 2 pairs on both paths.
        practice = verdict["comparison_mask"]["practice-2022"]
        self.assertFalse(practice["pairs"]["SOLUSDT"]["included"])
        self.assertTrue(practice["minimum_evidence"])
        v0 = stage["variants"]["V0"]
        self.assertTrue(v0["passed"])
        self.assertEqual(len(v0["runs"]), 8)
        # 40 cycles: 280/182 a week in verify-2024h1 and 280/245 in practice-2022.
        self.assertEqual(
            v0["criteria"]["C5"]["numbers"]["mean completed cycles per week"], "122/91"
        )
        # D is scored for information: no grid, so no cycles, and never selectable.
        d = stage["variants"]["D"]
        self.assertEqual((d["passed"], d["selectable"]), (False, False))
        self.assertEqual(len(verdict["inputs"]), 24)
        self.assertEqual(verdict["scorer"]["code_sha256"], jobs.SOURCE_IDENTITY)

    def test_v2_and_full_stack_rows_are_scored_as_registered_variants(self) -> None:
        _, _, _, verdict = self.run_scorer(matrix().values())
        variants = verdict["stages"]["stage 1"]["variants"]
        for name in ("V2", "C+F+G+H+V2"):
            with self.subTest(name):
                self.assertEqual(len(variants[name]["runs"]), 8)
                self.assertTrue(variants[name]["passed"] and variants[name]["selectable"])
        features = {i["dataset"] + " " + i["feature_version"] for i in verdict["inputs"]}
        self.assertIn(f"verify-2024h1 {STRUCTURE_FEATURE_VERSION}", features)

    def test_returns_are_reported_raw_and_annualised(self) -> None:
        _, _, _, verdict = self.run_scorer(matrix().values())
        a = verdict["stages"]["stage 1"]["variants"]["A"]
        practice = next(r for r in a["runs"] if r["window"] == "practice-2022")
        self.assertEqual(practice["return_pct"], "2")  # +2% over 245 days
        expected = score.annualise(F(2), 245).value
        self.assertEqual(F(practice["annualised_return_pct"]), score.written(expected))
        self.assertEqual(a["mean_return_pct"], "2")
        c2 = a["criteria"]["C2"]["numbers"]
        self.assertEqual(c2["mean annualised return %"], a["mean_annualised_return_pct"])
        self.assertGreater(F(a["mean_annualised_return_pct"]), 2)

    def test_an_invalid_run_fails_only_its_own_variant(self) -> None:
        documents = matrix()
        rows = documents["verify-2024h1", "B"]["results"]
        rows[0]["accounting_problems"] = ["cash identity failed"]
        documents["verify-2024h1", "B"] = document("verify-2024h1", rows)
        _, _, _, verdict = self.run_scorer(documents.values())
        variants = verdict["stages"]["stage 1"]["variants"]
        c4 = variants["B"]["criteria"]["C4"]
        self.assertFalse(c4["passed"])
        self.assertIn("cash identity failed", c4["failing"][0])
        self.assertTrue(variants["V0"]["criteria"]["C4"]["passed"])
        self.assertNotIn("B", verdict["selection"]["qualified"])
        self.assertIn("A", verdict["selection"]["qualified"])

    def test_a_failure_of_the_whole_file_invalidates_every_row_in_it(self) -> None:
        documents = matrix()
        file = documents["verify-2024h1", "A"]
        file["failures"] = [*file["failures"], "the checkout changed during the run: x -> y"]
        file["valid"] = False
        _, _, _, verdict = self.run_scorer(documents.values())
        runs = verdict["stages"]["stage 1"]["variants"]["A"]["runs"]
        validity = {(r["window"], r["valid"]) for r in runs}
        self.assertEqual(validity, {("practice-2022", True), ("verify-2024h1", False)})
        verify = next(r for r in runs if r["window"] == "verify-2024h1")
        self.assertIn("checkout changed", verify["problems"][0])
        self.assertNotIn("A", verdict["selection"]["qualified"])

    def test_a_missing_run_fails_c4_and_stops_the_early_reads_list(self) -> None:
        documents = matrix()
        rows = documents["practice-2022", "C"]["results"]
        documents["practice-2022", "C"]["results"] = [
            r
            for r in rows
            if (r["symbol"], r["path_mode"], r.get("variant")) != ("XRPUSDT", "low_first", "C")
        ]
        _, text, _, verdict = self.run_scorer(documents.values())
        c4 = verdict["stages"]["stage 1"]["variants"]["C"]["criteria"]["C4"]
        self.assertEqual(c4["failing"], ["practice-2022 XRPUSDT low_first: missing"])
        selection = verdict["selection"]
        self.assertEqual(
            (selection["outcome"], selection["winner"], selection["qualified"]),
            ("incomplete matrix", None, []),
        )
        self.assertIn("C is missing 1 runs", selection["reasons"])
        self.assertIn("incomplete matrix", text)

    def test_a_missing_variant_or_window_stops_the_early_reads_list(self) -> None:
        variants = tuple(v for v in score.VARIANTS if v != "H")
        _, _, _, verdict = self.run_scorer(matrix(variants).values())
        self.assertNotIn("H", verdict["stages"]["stage 1"]["variants"])
        self.assertEqual(verdict["selection"]["outcome"], "incomplete matrix")
        self.assertIn("variants not in the inputs: H", verdict["selection"]["reasons"])
        # Without one of its windows, stage 1 is not judged at all.
        _, _, _, verdict = self.run_scorer(matrix(windows=STAGE_1[:1]).values())
        stage = verdict["stages"]["stage 1"]
        self.assertEqual(
            (stage["variants"], stage["gaps"]), ({}, ["practice-2022 is not in the inputs"])
        )
        self.assertEqual(verdict["selection"]["outcome"], "incomplete matrix")

    def test_the_c6_baseline_comes_from_the_same_file(self) -> None:
        documents = matrix()
        for dataset in STAGE_1:
            for r in documents[dataset, "B"]["results"]:
                if r["strategy"] == score.BASELINE:
                    r |= {"final_total_equity": "103", "max_drawdown_pct": 2.0}
        _, _, _, verdict = self.run_scorer(documents.values())
        variants = verdict["stages"]["stage 1"]["variants"]
        self.assertFalse(variants["B"]["criteria"]["C6"]["passed"])
        self.assertTrue(variants["F"]["criteria"]["C6"]["passed"])

    def test_a_window_left_with_one_pair_is_insufficient_evidence(self) -> None:
        documents = matrix()
        for (dataset, _), file in documents.items():
            if dataset == "verify-2024h1":
                next(c for c in file["hourly_cross_checks"] if c["symbol"] == "ETHUSDT")[
                    "series_hours_missing"
                ] = 3
        _, _, _, verdict = self.run_scorer(documents.values())
        selection = verdict["selection"]
        self.assertEqual(
            (selection["outcome"], selection["winner"], selection["qualified"]),
            ("insufficient evidence", None, []),
        )
        pairs = verdict["comparison_mask"]["verify-2024h1"]["pairs"]
        self.assertEqual(pairs["BTCUSDT"]["reasons"], ["ETHUSDT: series_hours_missing=3"])

    def test_inputs_that_are_not_acceptance_runs_are_refused(self) -> None:
        def changed(change, variant="V0"):
            documents = matrix()
            change(documents["verify-2024h1", variant])
            return documents.values()

        def each_row(**fields):
            return lambda file: [r.update(fields) for r in file["results"]]

        def rules(**fields):
            return lambda file: [r["rules"].update(fields) for r in file["results"]]

        def gated(**fields):
            return lambda file: [
                r.update(fields) for r in file["results"] if r["strategy"] != score.BASELINE
            ]

        cases = {
            "engine 'drawdown-recovery-v1'": lambda f: f.update(
                engine_version="drawdown-recovery-v1"
            ),
            "features": lambda f: f.update(feature_version=STRUCTURE_FEATURE_VERSION),
            "integrity rules 'strict-v0'": lambda f: f["integrity_rules"].update(
                version="strict-v0"
            ),
            "maker fee 0.001": rules(fee_rate="0.001"),
            "missed-fill sensitivity": rules(fill_trigger_rate="0.0002"),
            "assumed spread % 0.10": each_row(assumed_spread_pct="0.10"),
            "not the committed config/datasets/verify-2024h1.toml": lambda f: f.update(
                spec_sha256="0" * 64
            ),
            "not the committed config/datasets/verify-2024h1.manifest.json": lambda f: f.update(
                manifest_sha256="0" * 64
            ),
            "not a clean commit": lambda f: f.update(code_commit=FROZEN_COMMIT + "+dirty"),
            "code commit None, not a clean commit": lambda f: [
                f.pop("code_commit"),
                f.pop("code_sha256"),
            ],
            "not the scorer's": lambda f: f.update(code_sha256="0" * 64),
            "the runs come from": lambda f: f.update(code_commit="1" * 40),
            "not a spec v1 variant": each_row(variant="B (inventory cap 0.5, not the spec's 0.40)"),
            "not the committed config/default.toml": lambda f: f.update(config_sha256="tuned"),
            "comparison mask differs": lambda f: f["hourly_cross_checks"][0].update(
                hours_missing=1
            ),
            "malformed results (KeyError": lambda f: f["results"][0].pop("max_drawdown_pct"),
            "not a non-negative number": each_row(buy_and_hold_max_drawdown_pct=-1.0),
            "'long-bull-bear-2022' is not a window of the early read": lambda f: f.update(
                dataset="long-bull-bear-2022"
            ),
            # V0's file with a --structure row: its gated rows disagree with its features.
            "gated rows": lambda f: f["results"][0].update(strategy=score.STRUCTURE_GRID),
        }
        for reason, change in cases.items():
            with self.subTest(reason):
                self.refused(changed(change), reason)
        structure = {
            # --structure with another variant, such as Bob's prior V2 + A runs.
            "not a spec v1 variant: strategy 'gated grid (price-only-v1+structure-v2)', "
            "variant 'A'": ("V2", gated(variant="A")),
            "not a spec v1 variant: strategy 'gated grid (price-only-v1+structure-v2)', "
            "variant 'C'": ("C+F+G+H+V2", gated(variant="C")),
            "(ungated rows None)": ("V2", lambda f: f.pop("baseline_feature_version")),
        }
        for reason, (variant, change) in structure.items():
            with self.subTest(reason):
                self.refused(changed(change, variant), reason)

    def test_a_batch_on_another_config_is_refused_however_consistent(self) -> None:
        documents = matrix()
        for file in documents.values():
            file["config_sha256"] = "config"  # every file agrees, on the wrong config
        self.refused(documents.values(), "not the committed config/default.toml")

    def test_a_batch_from_a_uniformly_modified_manifest_is_refused(self) -> None:
        # Codex's case: every practice-2022 file agrees on one manifest, not the committed.
        documents = matrix()
        for (dataset, _), file in documents.items():
            if dataset == "practice-2022":
                file["manifest_sha256"] = "1" * 64
        self.refused(
            documents.values(), "not the committed config/datasets/practice-2022.manifest.json"
        )

    def test_the_scorer_must_run_from_the_batchs_own_commit(self) -> None:
        with patch.object(score, "code_commit", return_value="2" * 40 + "+dirty"):
            code, _, stderr, _ = self.run_scorer(matrix().values())
        self.assertEqual(code, 2)
        self.assertIn(f"the runs come from {FROZEN_COMMIT}; the scorer runs at 2222", stderr)
        self.assertIn(score.FROZEN_HINT, stderr)

    def test_an_annualised_decision_its_bound_cannot_settle_refuses_the_scoring(self) -> None:
        with patch.object(score, "ANNUALISING_DIGITS", 1):
            code, _, stderr, verdict = self.run_scorer(matrix().values())
        self.assertEqual((code, verdict["selection"]["outcome"]), (2, "refused"))
        self.assertIn("cannot be decided", stderr)

    def test_the_invocation_is_named_and_single(self) -> None:
        (path,) = self.write([matrix()["verify-2024h1", "V0"]])
        for argv in ([path], [path, "--early-read", "--final"]):
            with (
                self.subTest(argv=argv[1:]),
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                score.main([*argv, "--out", str(self.out)])
            self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.out.exists())

    def test_text_digests_are_one_pair_for_either_line_endings(self) -> None:
        lf, crlf = self.tmp / "lf.toml", self.tmp / "crlf.toml"
        lf.write_bytes(b'a = "1"' + bytes([10]) + b"b = 2" + bytes([10]))
        crlf.write_bytes(lf.read_bytes().replace(bytes([10]), bytes([13, 10])))
        self.assertEqual(score.text_digests(lf), score.text_digests(crlf))
        self.assertEqual(score.text_digests(lf)[0], sha256_file(lf))
        self.assertEqual(score.text_digests(lf)[1], sha256_file(crlf))

    def test_either_line_endings_of_the_frozen_files_are_accepted(self) -> None:
        # Git checks the committed files out with LF on Linux and CRLF on Windows, and a
        # run records the hash of the bytes it found. Use the form this checkout lacks.
        documents = matrix()
        config = score.text_digests(score.ACCEPTANCE_CONFIG)
        other = 1 if config[0] == FROZEN_CONFIG else 0
        for (dataset, _), file in documents.items():
            spec = score.text_digests(score.DATASET_SPECS / f"{dataset}.toml")
            data = score.text_digests(score.DATASET_SPECS / f"{dataset}.manifest.json")
            file["config_sha256"], file["spec_sha256"] = config[other], spec[other]
            file["manifest_sha256"] = data[other]
        verdict = self.run_scorer(documents.values())[3]
        self.assertEqual(verdict["selection"]["outcome"], "early read")

    def test_a_traded_pairs_own_failure_leaves_the_other_pairs_scored(self) -> None:
        documents = matrix()
        for (dataset, _), file in documents.items():
            if dataset == "practice-2022":
                checks = file["hourly_cross_checks"]
                next(c for c in checks if c["symbol"] == "SOLUSDT")["minutes_missing"] = 1
        _, _, _, verdict = self.run_scorer(documents.values())
        pairs = verdict["comparison_mask"]["practice-2022"]["pairs"]
        self.assertEqual(len(pairs["SOLUSDT"]["reasons"]), 2)  # its minutes, and P4
        self.assertTrue(pairs["BTCUSDT"]["included"] and pairs["XRPUSDT"]["included"])
        self.assertEqual(verdict["selection"]["outcome"], "early read")

    def test_a_refused_rerun_replaces_the_earlier_verdict(self) -> None:
        documents = matrix()
        self.assertEqual(
            self.run_scorer(documents.values())[3]["selection"]["outcome"], "early read"
        )
        documents["verify-2024h1", "V0"]["engine_version"] = "drawdown-recovery-v1"
        self.refused(documents.values(), "engine 'drawdown-recovery-v1'")

    def test_a_run_that_fails_midway_leaves_no_earlier_verdict(self) -> None:
        paths = self.write(matrix().values())
        argv = [*paths, "--early-read", "--out", str(self.out)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(score.main(argv), 0)
        with (
            patch.object(score, "assess", side_effect=RuntimeError("interrupted")),
            self.assertRaises(RuntimeError),
        ):
            score.main(argv)
        selection = json.loads(self.out.read_text())["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("not scored", None))

    def test_the_verdict_never_overwrites_an_input(self) -> None:
        (path,) = self.write([matrix()["verify-2024h1", "V0"]])
        results = Path(path) / "results.json"
        before = results.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            score.main([path, "--early-read", "--out", str(results)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(results.read_bytes(), before)

    def test_the_same_run_in_two_inputs_is_refused(self) -> None:
        documents = matrix()
        self.refused([*documents.values(), documents["verify-2024h1", "V0"]], "more than one input")

    def test_a_non_finite_number_is_refused(self) -> None:
        file = self.tmp / "results.json"
        file.write_text('{"dataset": "verify-2024h1", "x": NaN}')
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = score.main([str(file), "--early-read", "--out", str(self.out)])
        self.assertEqual(code, 2)
        self.assertIn("non-finite number NaN", stderr.getvalue())
        self.assertEqual(json.loads(self.out.read_text())["selection"]["outcome"], "refused")

    def test_floats_are_read_as_their_decimal_text_and_returns_from_equities(self) -> None:
        file = self.tmp / "results.json"
        file.write_text(
            json.dumps(document("verify-2024h1", [row("BTCUSDT", "high_first", dd=0.1)]))
        )
        source = score.read_results(file)
        self.assertEqual(source.document["results"][0]["max_drawdown_pct"], Decimal("0.1"))
        spec = load_spec(SPECS / "verify-2024h1.toml")
        window = score.window_of(spec, clean_checks(spec))
        source.document["results"][0]["return_pct"] = 5.0  # the float is not used
        ((variant, scored),) = score.runs_of(source.document, window)
        self.assertEqual(
            (variant, scored.return_pct, scored.max_drawdown_pct), ("V0", F(1), F(1, 10))
        )

    def test_the_module_runs_as_a_command_and_checks_its_real_commit(self) -> None:
        # Unpatched, the command reads its own commit from git, which is never the
        # synthetic one the files record, so the whole batch is refused.
        paths = self.write(matrix().values())
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        command = [sys.executable, "-m", "crypto_grid_bot.backtest.acceptance", *paths]
        done = subprocess.run(
            [*command, "--early-read", "--out", str(self.out)],
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(done.returncode, 2, done.stderr)
        selection = json.loads(self.out.read_text())["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("refused", None))
        self.assertTrue(any("the scorer runs at" in line for line in selection["reasons"]))


class StageTests(ScorerFiles):
    """The final verdict over both stages (spec v1 section 6, "Two stages"), with the
    stage-2 windows' synthetic specs and manifests in a temporary directory."""

    def setUp(self) -> None:
        super().setUp()
        self.datasets = self.tmp / "datasets"
        self.datasets.mkdir()
        write_datasets(self.datasets)
        specs = patch.object(score, "DATASET_SPECS", self.datasets)
        specs.start()
        self.addCleanup(specs.stop)

    def both(self, returns=(), variants=score.VARIANTS, windows=(*STAGE_1, *LONG)):
        return matrix(variants, windows, returns, self.datasets)

    def final(self, documents):
        return self.run_scorer(documents.values(), "--final")

    def test_the_winner_is_ranked_on_2017_2024_alone(self) -> None:
        # A is best in stage 1 (and in 2017-2024 beats the rest but B), B is best in
        # 2017-2024, and F is best in 2019-2024, which is reported only.
        returns = {(LONG[0], "B"): "20", (LONG[1], "F"): "60"}
        code, text, _, verdict = self.final(self.both(returns))
        self.assertEqual(code, 0)
        self.assertEqual(verdict["invocation"], "final")
        selection = verdict["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("winner", "B"))
        self.assertEqual(selection["tie_set"], ["B"])
        # 20% over 2192 days annualises to 3.084618% (6 decimals); A's 2% to 0.330513%.
        eligible = selection["eligible"]
        self.assertEqual(eligible["B"]["mean_annualised_return_pct"], "3.084618")
        self.assertEqual(eligible["A"]["mean_annualised_return_pct"], "0.330513")
        self.assertEqual(list(eligible), list(score.SIMPLICITY_ORDER))  # E too (section 3 E)
        self.assertEqual(list(verdict["stages"]), ["stage 1", "stage 2", "stage 2, reported only"])
        reported = verdict["stages"]["stage 2, reported only"]
        self.assertFalse(reported["scored"])
        self.assertEqual(reported["variants"]["F"]["mean_return_pct"], "60")
        self.assertIn("Selection (spec v1 section 6, final): winner: B", text)
        self.assertIn("ranked on full-range-2017-2024", text)
        self.assertIn("reported only; it decides nothing", text)
        self.assertEqual(len(verdict["inputs"]), 48)

    def test_a_variant_must_pass_c1_to_c6_in_both_stages(self) -> None:
        # The full stack is best in 2017-2024 but fails stage 1; V2 is best in stage 1
        # but fails stage 2; B, best of the rest in 2017-2024, wins.
        returns = {
            (STAGE_1[0], "C+F+G+H+V2"): "-1",
            (STAGE_1[1], "V2"): "5",
            (STAGE_1[0], "V2"): "5",
            (LONG[0], "C+F+G+H+V2"): "50",
            (LONG[0], "V2"): "-1",
            (LONG[0], "B"): "20",
        }
        _, _, _, verdict = self.final(self.both(returns))
        stages = verdict["stages"]
        self.assertNotIn("C+F+G+H+V2", stages["stage 1"]["passing"])
        self.assertIn("C+F+G+H+V2", stages["stage 2"]["passing"])
        self.assertIn("V2", stages["stage 1"]["passing"])
        self.assertNotIn("V2", stages["stage 2"]["passing"])
        selection = verdict["selection"]
        self.assertEqual(selection["winner"], "B")
        expected = ["V0", "A", "B", "C", "E", "F", "G", "C+G", "H", "C+H"]
        self.assertEqual(selection["qualified"], expected)
        self.assertIn("E", selection["eligible"])  # eligible since Codex's review (section 3 E)

    def test_no_variant_passing_both_stages_is_no_winner(self) -> None:
        returns = {(LONG[0], variant): "-1" for variant in score.VARIANTS}
        _, text, _, verdict = self.final(self.both(returns))
        selection = verdict["selection"]
        self.assertEqual(
            (selection["outcome"], selection["winner"], selection["qualified"]),
            ("no winner", None, []),
        )
        self.assertIn("- passing stage 1 and stage 2: none", text)

    def test_an_incomplete_stage_refuses_the_final_verdict(self) -> None:
        def without_run(documents):
            file = documents[LONG[0], "B"]
            file["results"] = [
                r
                for r in file["results"]
                if (r["symbol"], r["path_mode"], r.get("variant")) != ("XRPUSDT", "low_first", "B")
            ]
            return documents

        cases = {
            "stage 2: B is missing 1 runs": without_run(self.both()),
            "stage 2, reported only: full-range-2019-2024 is not in the inputs": self.both(
                windows=(*STAGE_1, LONG[0])
            ),
            "stage 2: full-range-2017-2024 is not in the inputs": self.both(windows=STAGE_1),
            "stage 1: variants not in the inputs: H": {
                key: file for key, file in self.both().items() if key[1] != "H" or key[0] in LONG
            },
        }
        for reason, documents in cases.items():
            with self.subTest(reason):
                self.refused(documents.values(), reason, "--final")
                self.assertIn(
                    "the final verdict needs both stages' whole matrices",
                    json.loads(self.out.read_text())["selection"]["reasons"],
                )

    def test_a_stage_2_window_without_its_committed_files_is_refused(self) -> None:
        documents = self.both()
        (self.datasets / "full-range-2017-2024.manifest.json").unlink()
        reason = "full-range-2017-2024: no committed "
        self.refused(documents.values(), reason, "--final")
        self.assertIn(
            "full-range-2017-2024.manifest.json, so its runs cannot be pinned", self.out.read_text()
        )
        # A final run says so even with no stage-2 run in its inputs.
        stage_1 = {k: f for k, f in documents.items() if k[0] in STAGE_1}
        self.refused(stage_1.values(), reason, "--final")

    def test_a_committed_spec_with_another_window_is_refused(self) -> None:
        spec = self.datasets / "full-range-2017-2024.toml"
        spec.write_text(spec.read_text().replace('start = "2019-01"', 'start = "2019-02"'))
        reason = "full-range-2017-2024: the committed spec's evaluation window is 2161 days"
        self.refused(self.both().values(), reason, "--final")

    def test_2017_2024_with_fewer_than_2_pairs_is_insufficient_evidence(self) -> None:
        documents = self.both()
        for (dataset, _), file in documents.items():
            if dataset == LONG[0]:
                for check in file["hourly_cross_checks"]:
                    if check["symbol"] in ("ETHUSDT", "XRPUSDT"):
                        check["minutes_missing"] = 1
        _, _, _, verdict = self.final(documents)
        selection = verdict["selection"]
        self.assertEqual(
            (selection["outcome"], selection["winner"]), ("insufficient evidence", None)
        )
        self.assertEqual(
            selection["reasons"],
            ["full-range-2017-2024: 1 included pairs; section 5 needs at least 2"],
        )

    def test_the_reported_window_decides_nothing(self) -> None:
        # 2019-2024 keeps one pair, and every variant fails there: B still wins.
        returns = {(LONG[0], "B"): "20", **{(LONG[1], v): "-5" for v in score.VARIANTS}}
        documents = self.both(returns)
        for (dataset, _), file in documents.items():
            if dataset == LONG[1]:
                for check in file["hourly_cross_checks"]:
                    if check["symbol"] in ("ETHUSDT", "XRPUSDT"):
                        check["minutes_missing"] = 1
        _, _, _, verdict = self.final(documents)
        self.assertFalse(verdict["comparison_mask"][LONG[1]]["minimum_evidence"])
        self.assertEqual(verdict["stages"]["stage 2, reported only"]["passing"], [])
        self.assertEqual(
            (verdict["selection"]["outcome"], verdict["selection"]["winner"]), ("winner", "B")
        )

    def test_the_early_read_refuses_stage_2_inputs(self) -> None:
        reason = "'full-range-2017-2024' is not a window of the early read"
        self.refused(self.both(windows=(*STAGE_1, LONG[0])).values(), reason)


if __name__ == "__main__":
    unittest.main()
