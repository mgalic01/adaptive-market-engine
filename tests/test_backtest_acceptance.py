"""Spec v1 section 6: the acceptance scorer, on synthetic results only.

No market data and no backtest result is read. The file-level tests build results.json
files the way the backtest CLI writes them, against the committed development dataset
specs (configuration, not data), so the C5 windows and the P4 mask are the real ones.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
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

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "config" / "datasets"
FROZEN_CONFIG = sha256_file(ROOT / "config" / "default.toml")


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

    def test_c2_needs_both_path_medians_and_the_mean_above_zero(self) -> None:
        def runs(high, low):
            return [run(path="high_first", return_pct=F(r)) for r in high] + [
                run(path="low_first", return_pct=F(r)) for r in low
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
        self.assertEqual(numbers["median return % (low_first)"], F(-1, 4))
        self.assertEqual(numbers["mean return %"], F(5, 8))

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


def passing(variant, mean_return, drawdown=F(2)):
    """A score that passes C1-C6 with this mean return and mean max drawdown."""
    return score.score_variant(
        variant,
        both_paths(
            return_pct=F(mean_return),
            max_drawdown_pct=F(drawdown),
            active_max_drawdown_pct=F(drawdown),
            baseline=F(-1000),
        ),
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

    def test_a_drawdown_tie_goes_to_the_simplicity_order(self) -> None:
        self.assertEqual(score.select([passing(v, 1) for v in ("C", "F", "B")]).winner, "B")
        # F precedes C in the simplicity order, though C comes first in section 4.
        self.assertEqual(score.select([passing("C", 1), passing("F", 1)]).winner, "F")

    def test_drawdowns_equal_after_rounding_are_a_tie(self) -> None:
        result = score.select([passing("C", 1, "3.0000001"), passing("F", 1, "3.0000004")])
        self.assertEqual(result.winner, "F")

    def test_d_is_never_selected(self) -> None:
        result = score.select([passing("D", 5), passing("V0", 1)])
        self.assertEqual(result.winner, "V0")
        self.assertNotIn("D", result.figures)

    def test_e_is_not_eligible_until_codex_has_reviewed_it(self) -> None:
        scores = [passing("E", 5), passing("V0", 1)]
        self.assertEqual(score.select(scores).winner, "V0")
        with patch.object(score, "E_ELIGIBLE", True):
            self.assertEqual(score.select(scores).winner, "E")

    def test_a_failing_variant_is_not_eligible(self) -> None:
        unsafe = score.score_variant(
            "A", both_paths(return_pct=F(9), baseline=F(-1000), buy_and_hold_max_drawdown_pct=F(1))
        )
        self.assertFalse(unsafe.passed)
        self.assertEqual(score.select([unsafe, passing("V0", 1)]).winner, "V0")
        no_winner = score.select([unsafe])
        self.assertEqual((no_winner.outcome, no_winner.winner), ("no winner", None))


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


class MaskTests(unittest.TestCase):
    def test_the_development_windows_have_the_specs_c5_and_r1_lengths(self) -> None:
        for name, days, months in (("verify-2024h1", 182, 6), ("practice-2022", 245, 8)):
            with self.subTest(name):
                spec = load_spec(SPECS / f"{name}.toml")
                window = score.window_of(spec, clean_checks(spec))
                self.assertEqual((window.days, window.months), (days, months))

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
        # BTCUSDT is the market proxy, so its own failure excludes every pair.
        next(c for c in checks if c["symbol"] == "BTCUSDT")["minutes_missing"] = 1
        self.assertEqual(score.window_of(spec, checks).included, ())

    def test_checks_must_be_one_per_checked_symbol(self) -> None:
        spec = load_spec(SPECS / "verify-2024h1.toml")
        with self.assertRaises(score.ScoringError):
            score.window_of(spec, clean_checks(spec)[1:])


# File-level tests: synthetic results.json files as the backtest CLI writes them.


def row(symbol, path, variant="V0", ret="1", dd=2.0, **changes):
    """One result row. ``variant`` "ungated" is the ungated V0 baseline."""
    data = {
        "symbol": symbol,
        "path_mode": path,
        "strategy": {"ungated": score.BASELINE, "D": BENCHMARK}.get(variant, score.GRID),
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
    if variant not in ("V0", "ungated"):
        data["variant"] = variant
    return data | changes


def document(dataset, rows, **changes):
    spec_path = SPECS / f"{dataset}.toml"
    failures = cli.result_failures(rows)
    data = {
        "dataset": dataset,
        "purpose": "synthetic",
        "feature_version": FEATURE_VERSION,
        "engine_version": ENGINE_VERSION,
        "manifest_created_at": "synthetic",
        "spec_sha256": sha256_file(spec_path),
        "manifest_sha256": f"manifest of {dataset}",
        "config_sha256": FROZEN_CONFIG,
        "integrity_rules": {"version": INTEGRITY_RULES, "volume_drift_tolerance": "0.001"},
        "fees": {"maker": "0", "taker": "0.0009"},
        "valid": not failures,
        "failures": failures,
        "hourly_cross_checks": clean_checks(load_spec(spec_path)),
        "results": rows,
    }
    return data | changes


# Each variant's mean return in the synthetic matrix. A clears the others by more than
# the tie margin; E would clear A, but E is not eligible.
RETURNS = {"A": "2", "E": "3"}


def rows_for(dataset, variant):
    """A variant's rows over every traded pair and path. SOLUSDT has rejected frames in
    practice-2022, as its unsourced filters cause."""
    spec = load_spec(SPECS / f"{dataset}.toml")
    rows = []
    for pair in spec.traded:
        for path in PATH_MODES:
            rejected = int(dataset == "practice-2022" and pair == "SOLUSDT")
            if variant == "ungated":
                rows.append(row(pair, path, variant, "-1", 4.0, transient_pauses=rejected))
            elif variant == "D":  # not a grid: D's rows count no cycles (P7)
                rows.append(row(pair, path, "D", "1", completed_cycles=0, transient_pauses=0))
            else:
                ret = RETURNS.get(variant, "1")
                rows.append(row(pair, path, variant, ret, transient_pauses=rejected))
    return rows


def matrix(variants=score.VARIANTS):
    """One results.json per variant and window, as the CLI writes them: D shares V0's
    (``run --trend-benchmark``), and every file carries the ungated baseline rows."""
    documents = {}
    for dataset in score.WINDOWS:
        for variant in variants:
            if variant == "D":
                continue
            names = [variant, "D"] if variant == "V0" and "D" in variants else [variant]
            rows = [r for name in [*names, "ungated"] for r in rows_for(dataset, name)]
            documents[dataset, variant] = document(dataset, rows)
    return documents


class FileTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.out = self.tmp / "verdict.json"

    def write(self, documents):
        paths = []
        for data in documents:
            directory = Path(tempfile.mkdtemp(dir=self.tmp))
            (directory / "results.json").write_text(json.dumps(data, indent=1, default=str))
            paths.append(str(directory))
        return paths

    def run_scorer(self, documents):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = score.main([*self.write(documents), "--out", str(self.out)])
        verdict = json.loads(self.out.read_text()) if self.out.exists() else None
        return code, stdout.getvalue(), stderr.getvalue(), verdict

    def refused(self, documents, reason):
        code, _, stderr, verdict = self.run_scorer(documents)
        self.assertEqual(code, 2)
        self.assertIn(reason, stderr)
        self.assertNotIn("variants", verdict)
        selection = verdict["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("refused", None))
        self.assertTrue(any(reason in line for line in selection["reasons"]))

    def test_the_whole_matrix_selects_a_winner_and_writes_the_verdict(self) -> None:
        code, text, _, verdict = self.run_scorer(matrix().values())
        self.assertEqual(code, 0)
        selection = verdict["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("winner", "A"))
        self.assertEqual(selection["tie_set"], ["A"])
        self.assertNotIn("E", selection["eligible"])
        self.assertEqual(selection["eligible"]["A"]["mean_return_pct"], "2.000000")
        self.assertIn("Selection (spec v1 section 6): winner: A", text)
        self.assertIn(score.C7_NOTE, text)
        text.encode("ascii")  # any console can print it
        # The mask excludes practice-2022 SOLUSDT for every variant, so its rejected
        # frames fail no variant's C4; each variant has 2 + 2 pairs on both paths.
        practice = verdict["comparison_mask"]["practice-2022"]
        self.assertFalse(practice["pairs"]["SOLUSDT"]["included"])
        self.assertTrue(practice["minimum_evidence"])
        v0 = verdict["variants"]["V0"]
        self.assertTrue(v0["passed"])
        self.assertEqual(len(v0["runs"]), 8)
        # 40 cycles: 280/182 a week in verify-2024h1 and 280/245 in practice-2022.
        self.assertEqual(
            v0["criteria"]["C5"]["numbers"]["mean completed cycles per week"], "122/91"
        )
        # D is scored for information: no grid, so no cycles, and never selectable.
        d = verdict["variants"]["D"]
        self.assertEqual((d["passed"], d["selectable"]), (False, False))
        self.assertEqual(len(verdict["inputs"]), 20)
        self.assertEqual(verdict["scorer"]["code_sha256"], jobs.SOURCE_IDENTITY)

    def test_an_invalid_run_fails_only_its_own_variant(self) -> None:
        documents = matrix()
        rows = documents["verify-2024h1", "B"]["results"]
        rows[0]["accounting_problems"] = ["cash identity failed"]
        documents["verify-2024h1", "B"] = document("verify-2024h1", rows)
        _, _, _, verdict = self.run_scorer(documents.values())
        c4 = verdict["variants"]["B"]["criteria"]["C4"]
        self.assertFalse(c4["passed"])
        self.assertIn("cash identity failed", c4["failing"][0])
        self.assertTrue(verdict["variants"]["V0"]["criteria"]["C4"]["passed"])
        self.assertEqual(verdict["selection"]["winner"], "A")

    def test_a_failure_of_the_whole_file_invalidates_every_row_in_it(self) -> None:
        documents = matrix()
        file = documents["verify-2024h1", "A"]
        file["failures"] = [*file["failures"], "the checkout changed during the run: x -> y"]
        file["valid"] = False
        _, _, _, verdict = self.run_scorer(documents.values())
        runs = verdict["variants"]["A"]["runs"]
        validity = {(r["window"], r["valid"]) for r in runs}
        self.assertEqual(validity, {("practice-2022", True), ("verify-2024h1", False)})
        self.assertIn("checkout changed", runs[-1]["problems"][0])
        self.assertEqual(verdict["selection"]["winner"], "V0")

    def test_a_missing_run_fails_c4_and_stops_the_selection(self) -> None:
        documents = matrix()
        rows = documents["practice-2022", "C"]["results"]
        documents["practice-2022", "C"]["results"] = [
            r
            for r in rows
            if (r["symbol"], r["path_mode"], r.get("variant")) != ("XRPUSDT", "low_first", "C")
        ]
        _, text, _, verdict = self.run_scorer(documents.values())
        c4 = verdict["variants"]["C"]["criteria"]["C4"]
        self.assertEqual(c4["failing"], ["practice-2022 XRPUSDT low_first: missing"])
        selection = verdict["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("incomplete matrix", None))
        self.assertIn("C is missing 1 runs", selection["reasons"])
        self.assertIn("incomplete matrix", text)

    def test_a_missing_variant_stops_the_selection(self) -> None:
        variants = tuple(v for v in score.VARIANTS if v != "H")
        _, _, _, verdict = self.run_scorer(matrix(variants).values())
        self.assertNotIn("H", verdict["variants"])
        self.assertEqual(verdict["selection"]["outcome"], "incomplete matrix")
        self.assertIn("variants not in the inputs: H", verdict["selection"]["reasons"])

    def test_the_c6_baseline_comes_from_the_same_file(self) -> None:
        documents = matrix()
        for dataset in score.WINDOWS:
            for r in documents[dataset, "B"]["results"]:
                if r["strategy"] == score.BASELINE:
                    r |= {"final_total_equity": "103", "max_drawdown_pct": 2.0}
        _, _, _, verdict = self.run_scorer(documents.values())
        self.assertFalse(verdict["variants"]["B"]["criteria"]["C6"]["passed"])
        self.assertTrue(verdict["variants"]["F"]["criteria"]["C6"]["passed"])

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
            (selection["outcome"], selection["winner"]), ("insufficient evidence", None)
        )
        pairs = verdict["comparison_mask"]["verify-2024h1"]["pairs"]
        self.assertEqual(pairs["BTCUSDT"]["reasons"], ["ETHUSDT: series_hours_missing=3"])

    def test_inputs_that_are_not_acceptance_runs_are_refused(self) -> None:
        def changed(change):
            documents = matrix()
            change(documents["verify-2024h1", "V0"])
            return documents.values()

        def each_row(**fields):
            return lambda file: [r.update(fields) for r in file["results"]]

        def rules(**fields):
            return lambda file: [r["rules"].update(fields) for r in file["results"]]

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
            "changed since they ran": lambda f: f.update(spec_sha256="0" * 64),
            "not a spec v1 variant": each_row(variant="B (inventory cap 0.5, not the spec's 0.40)"),
            "not the frozen config/default.toml": lambda f: f.update(config_sha256="tuned"),
            "comparison mask differs": lambda f: f["hourly_cross_checks"][0].update(
                hours_missing=1
            ),
            "malformed results (KeyError": lambda f: f["results"][0].pop("max_drawdown_pct"),
            "not a non-negative number": each_row(buy_and_hold_max_drawdown_pct=-1.0),
        }
        for reason, change in cases.items():
            with self.subTest(reason):
                self.refused(changed(change), reason)

    def test_a_batch_on_another_config_is_refused_however_consistent(self) -> None:
        documents = matrix()
        for file in documents.values():
            file["config_sha256"] = "config"  # every file agrees, on the wrong config
        self.refused(documents.values(), "not the frozen config/default.toml")

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
            file["config_sha256"], file["spec_sha256"] = config[other], spec[other]
        self.assertEqual(self.run_scorer(documents.values())[3]["selection"]["winner"], "A")

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
        self.assertEqual(verdict["selection"]["winner"], "A")

    def test_a_refused_rerun_replaces_the_earlier_verdict(self) -> None:
        documents = matrix()
        self.assertEqual(self.run_scorer(documents.values())[3]["selection"]["winner"], "A")
        documents["verify-2024h1", "V0"]["engine_version"] = "drawdown-recovery-v1"
        self.refused(documents.values(), "engine 'drawdown-recovery-v1'")

    def test_a_run_that_fails_midway_leaves_no_earlier_verdict(self) -> None:
        paths = self.write(matrix().values())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(score.main([*paths, "--out", str(self.out)]), 0)
        with (
            patch.object(score, "assess", side_effect=RuntimeError("interrupted")),
            self.assertRaises(RuntimeError),
        ):
            score.main([*paths, "--out", str(self.out)])
        selection = json.loads(self.out.read_text())["selection"]
        self.assertEqual((selection["outcome"], selection["winner"]), ("not scored", None))

    def test_the_verdict_never_overwrites_an_input(self) -> None:
        (path,) = self.write([matrix()["verify-2024h1", "V0"]])
        results = Path(path) / "results.json"
        before = results.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            score.main([path, "--out", str(results)])
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
            code = score.main([str(file), "--out", str(self.out)])
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

    def test_the_module_runs_as_a_command(self) -> None:
        paths = self.write(matrix().values())
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        command = [sys.executable, "-m", "crypto_grid_bot.backtest.acceptance", *paths]
        done = subprocess.run(
            [*command, "--out", str(self.out)],
            capture_output=True,
            env=env,
            check=False,
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn(b"winner: A", done.stdout)
        self.assertEqual(json.loads(self.out.read_text())["selection"]["winner"], "A")


if __name__ == "__main__":
    unittest.main()
