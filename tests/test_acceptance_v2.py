"""Spec v2 section 8: the v2 scorer, on synthetic results only.

No market data and no backtest result is read. Task 6 has not built the mode switcher's
rows yet, so the MS rows here carry exactly the fields the scorer's module docstring
lists for it (``MS_ROW_FIELDS`` and ``MODES_FIELDS``); F's and D's rows are spec v1's,
as its scorer's tests build them. The stage-1 windows use the committed dataset specs.
full-range-2017-2024 has no committed spec or manifest yet, so a synthetic one with spec
v1 section 4's frozen definition is written to a temporary directory, and the scorer is
pointed there.
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
from decimal import Decimal
from fractions import Fraction as F
from pathlib import Path
from unittest.mock import patch

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest import acceptance as score
from crypto_grid_bot.backtest import acceptance_v2 as v2
from crypto_grid_bot.backtest import jobs
from crypto_grid_bot.backtest.dataset import load_spec, sha256_file
from crypto_grid_bot.backtest.features import FEATURE_VERSION
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.replay import DAY_MS, ENGINE_VERSION, INTEGRITY_RULES, PATH_MODES
from crypto_grid_bot.backtest.trend_benchmark import STRATEGY as BENCHMARK

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "config" / "datasets"
FROZEN_CONFIG = sha256_file(ROOT / "config" / "default.toml")
# A synthetic clean commit, which the in-process tests give the scorer as its own.
FROZEN_COMMIT = "c0ffee" + "0" * 34
FULL = "full-range-2017-2024"
WINDOWS = (FULL, "practice-2022", "verify-2024h1")
TRADED = {
    FULL: ("BTCUSDT", "ETHUSDT", "XRPUSDT"),
    "practice-2022": ("BTCUSDT", "SOLUSDT", "XRPUSDT"),
    "verify-2024h1": ("ADAUSDT", "BTCUSDT"),
}
FIRST_MONTH = {FULL: "2019-01", "practice-2022": "2022-06", "verify-2024h1": "2024-01"}
HOUR_MS = 3_600_000


def run(**changes):
    """A valid MS run in full-range-2017-2024 that passes C1-C4 on its own."""
    values = {
        "window": FULL,
        "symbol": "BTCUSDT",
        "path": "high_first",
        "return_pct": F(10),
        "max_drawdown_pct": F(2),
        "active_max_drawdown_pct": F(2),
        "buy_and_hold_max_drawdown_pct": F(5),
        "hard_drawdown_halts": 0,
        "completed_cycles": 60,
        "days": 2192,
        "months": 72,
    }
    return score.Run(**{**values, **changes})


def yearly(annual):
    """The raw return in percent over 1461 days that annualises to exactly ``annual``
    percent, so that the annualised return is rational and computed exactly."""
    return ((1 + F(annual) / 100) ** 4 - 1) * 100


def four_years(annual, dd=F(2), **changes):
    return run(return_pct=yearly(annual), max_drawdown_pct=dd, days=1461, months=48, **changes)


class CriterionTests(unittest.TestCase):
    def test_activity_threshold_inclusive(self) -> None:
        runs = [run(symbol=pair, days=36525) for pair in ("BTCUSDT", "ETHUSDT")]
        exactly = v2.activity_v2(runs, {r.label: 1200 for r in runs})  # 12.00 a year
        self.assertTrue(exactly.passed)
        self.assertEqual(exactly.numbers["mean round trips per year"], F(12))
        below = v2.activity_v2(runs, {r.label: 1199 for r in runs})  # 11.99 a year
        self.assertFalse(below.passed)
        self.assertEqual(below.numbers["mean round trips per year"], F(1199, 100))
        # In the scored window's 2,192 days: 73 round trips are 12.16 a year, 72 are 11.997.
        scored = [run()]
        self.assertTrue(v2.activity_v2(scored, {scored[0].label: 73}).passed)
        self.assertFalse(v2.activity_v2(scored, {scored[0].label: 72}).passed)
        # The mean is exact and over every run, each with its own window length.
        mixed = [run(days=1461), run(symbol="ETHUSDT", days=36525)]
        c5 = v2.activity_v2(mixed, {mixed[0].label: 47, mixed[1].label: 1203})
        self.assertEqual(c5.numbers["mean round trips per year"], (F(47, 4) + F(1203, 100)) / 2)
        self.assertFalse(v2.activity_v2([], {}).passed)

    def test_round_trips_use_the_rows_completed_cycles(self) -> None:
        data = row(FULL, "BTCUSDT", "high_first")
        self.assertEqual(v2.round_trips(data), 60 + 20)
        # modes carries the uptrend count and no copy of the grid count, which is read
        # from the row's own completed_cycles, as Run.completed_cycles reads it.
        self.assertEqual(set(data["modes"]) - {"held_at_end"}, set(v2.MODES_FIELDS))
        self.assertNotIn("completed_cycles", data["modes"])
        data["completed_cycles"] = 61
        self.assertEqual(v2.round_trips(data), 81)
        for bad in (True, -1, 1.5, Decimal("1.5"), "3"):
            with self.subTest(uptrend_trades=bad):
                broken = row(FULL, "BTCUSDT", "high_first")
                broken["modes"]["uptrend_trades"] = bad
                with self.assertRaises(score.ScoringError):
                    v2.round_trips(broken)
        with self.assertRaises(score.ScoringError):
            v2.round_trips(row(FULL, "BTCUSDT", "high_first", completed_cycles=True))

    def test_gate_needs_positive_return_and_beats_always_grid(self) -> None:
        cases = {
            "beats both": (four_years(10), four_years(5), True),
            "ties always-grid": (four_years(10), four_years(10), False),
            "below always-grid": (four_years(10, dd=F(4)), four_years(6), False),  # 2.5 < 3
            "zero return": (four_years(0), four_years(-5), False),
            "negative return": (four_years(-1), four_years(-5), False),
            # The 0.1-point floor is v1's gate_ratio's: 1 / 0.1 = 10 does not beat 6 / 0.5.
            "floored drawdown": (four_years(1, dd=F(1, 20)), four_years(6, dd=F(1, 2)), False),
            "floored, still ahead": (four_years(1, dd=F(1, 20)), four_years(4, dd=F(1, 2)), True),
        }
        for name, (candidate, always_grid, passes) in cases.items():
            with self.subTest(name):
                c6 = v2.earns_its_place([candidate], {always_grid.key: always_grid})
                self.assertEqual(c6.passed, passes)
                self.assertEqual(len(c6.failing), 0 if passes else 1)
        c6 = v2.earns_its_place([four_years(-1)], {four_years(-5).key: four_years(-5)})
        self.assertIn("cash", c6.failing[0])

    def test_gate_uses_annualised_returns_and_counts_a_missing_or_invalid_always_grid_against(
        self,
    ) -> None:
        candidate = run(return_pct=F(10), max_drawdown_pct=F(5), days=2192)
        always_grid = run(return_pct=F(20), max_drawdown_pct=F("9.9"), days=2192)
        # The raw ratios would favour F: 10 / 5 = 2.0 against 20 / 9.9 = 2.0202.
        self.assertEqual(candidate.ratio, F(2))
        self.assertGreater(always_grid.ratio, candidate.ratio)
        # The annualised ones favour the run: 1.6008 / 5 = 0.3202 against 3.0846 / 9.9.
        mine = v2.annualised_ratio(candidate)
        theirs = v2.annualised_ratio(always_grid)
        self.assertEqual(round(float(mine[1]), 4), 0.3202)
        self.assertEqual(round(float(theirs[1]), 4), 0.3116)
        self.assertTrue(mine[0] <= mine[1] <= mine[2])
        c6 = v2.earns_its_place([candidate], {always_grid.key: always_grid})
        self.assertTrue(c6.passed)
        self.assertEqual(c6.numbers["share %"], F(100))
        missing = v2.earns_its_place([candidate], {})
        self.assertFalse(missing.passed)
        self.assertIn("no always-grid (F) run", missing.failing[0])
        invalid = run(return_pct=F(-50), problems=("BTCUSDT/high_first/x: 3 rejected frames",))
        c6 = v2.earns_its_place([candidate], {invalid.key: invalid})
        self.assertFalse(c6.passed)
        self.assertIn("always-grid (F) run is invalid: BTCUSDT/high_first/x", c6.failing[0])
        # The same pair and path in another window never stands in.
        elsewhere = run(window="practice-2022", return_pct=F(-50), days=245, months=8)
        self.assertFalse(v2.earns_its_place([candidate], {elsewhere.key: elsewhere}).passed)

    def test_gate_share_boundary(self) -> None:
        keys = [(pair, path) for pair in ("BTCUSDT", "ETHUSDT", "XRPUSDT") for path in PATH_MODES]
        always_grid = [run(symbol=s, path=p, return_pct=F(1)) for s, p in keys[:5]]
        grid = {r.key: r for r in always_grid}
        for wins, passes in ((3, True), (2, False)):
            with self.subTest(wins=wins):
                runs = [
                    run(symbol=s, path=p, return_pct=F(10) if i < wins else F(-1))
                    for i, (s, p) in enumerate(keys[:5])
                ]
                c6 = v2.earns_its_place(runs, grid)
                self.assertEqual(c6.passed, passes)
                self.assertEqual(c6.numbers["runs beating always-grid and cash"], f"{wins} of 5")
                self.assertEqual(c6.numbers["share %"], F(wins * 20))
                self.assertEqual(c6.numbers["required %"], "60")
        self.assertFalse(v2.earns_its_place([], grid).passed)

    def test_upside_capture_two_months(self) -> None:
        january, february = month_bounds_ms("2019-01")
        data = {
            "initial_quote": "100",
            "final_total_equity": "105.04",
            "hourly_equity": [[january, "100", "100"], [february, "104", "110"]],
            "modes": {"buy_and_hold_final": "104.5"},
        }
        # Buy-and-hold +10% then -5%, the bot +4% then +1%: only January counts.
        self.assertEqual(v2.upside_capture(data), F(2, 5))
        # No month in which buy-and-hold gains: nothing to capture.
        data["modes"]["buy_and_hold_final"] = "99"
        data["hourly_equity"][1][2] = "99.5"
        self.assertIsNone(v2.upside_capture(data))

    def test_upside_capture_uses_month_boundary_samples(self) -> None:
        january, february = month_bounds_ms("2019-01")
        data = {
            "initial_quote": "100",
            "final_total_equity": "105.04",
            "hourly_equity": [
                [january, "98", "95"],  # January's first sample is not where it starts
                [february - HOUR_MS, "99", "99"],  # January's last sample
                [february + 5 * HOUR_MS, "104", "110"],  # February's first, after a gap
                [february + 300 * HOUR_MS, "103", "108"],
            ],
            "modes": {"buy_and_hold_final": "104.5"},
        }
        # January runs from the initial capital to February's first sample, so the move
        # from January's last sample to it counts in January: +10% and +4%. From the first
        # sample it would be 110/95 and 104/98; in February, 104.5/99 and 105.04/99.
        self.assertEqual(v2.upside_capture(data), F(2, 5))
        # A month with no sample of its own has a zero return; the move across it falls
        # in the month before.
        march = month_bounds_ms("2019-03")[0]
        gap = {**data, "hourly_equity": [[january, "100", "100"], [march, "110", "121"]]}
        gap |= {"final_total_equity": "110", "modes": {"buy_and_hold_final": "121"}}
        self.assertEqual(v2.upside_capture(gap), F(10, 21))
        # With the evaluation's first month named, a first month without a sample of its
        # own still starts from the initial capital and ends at the next month's first.
        late = {
            "initial_quote": "100",
            "final_total_equity": "105.04",
            "hourly_equity": [[february, "104", "110"]],
            "modes": {"buy_and_hold_final": "104.5"},
        }
        self.assertEqual(v2.upside_capture(late, "2019-01"), F(2, 5))
        # Unnamed, February is the first month, from 100 to the finals: 5.04 / 4.5.
        self.assertEqual(v2.upside_capture(late), F(28, 25))
        with self.assertRaises(score.ScoringError):
            v2.upside_capture(late, "2019-03")  # a sample before the first month
        backwards = {**data, "hourly_equity": [data["hourly_equity"][1], data["hourly_equity"][0]]}
        with self.assertRaises(score.ScoringError):
            v2.upside_capture(backwards)

    def test_c1_to_c4_reuse_v1_functions(self) -> None:
        fixtures = {
            "passing": [run(), run(symbol="ETHUSDT"), run(path="low_first")],
            "failing": [
                run(),
                run(symbol="ETHUSDT", max_drawdown_pct=F(11)),
                run(path="low_first", hard_drawdown_halts=1),
                run(symbol="XRPUSDT", return_pct=F(-30), problems=("XRPUSDT: accounting",)),
                run(symbol="ETHUSDT", path="low_first", buy_and_hold_max_drawdown_pct=F(1)),
            ],
        }
        for name, runs in fixtures.items():
            with self.subTest(name):
                grid = {r.key: run(symbol=r.symbol, path=r.path, return_pct=F(1)) for r in runs}
                criteria = v2.criteria(runs, {r.label: 80 for r in runs}, grid)
                self.assertEqual([c.name for c in criteria], ["C1", "C2", "C3", "C4", "C5", "C6"])
                v1 = (
                    score.worst_drop(runs),
                    score.makes_money(runs),
                    score.safer_than_holding(runs),
                    score.integrity(runs),
                )
                self.assertEqual(criteria[:4], v1)
                self.assertEqual(all(c.passed for c in v1), name == "passing")


# File-level tests: synthetic results.json files as the backtest CLI writes them.

FULL_SPEC = """name = "full-range-2017-2024"
purpose = "synthetic stand-in for the long-window spec, for the v2 scorer's tests"
traded = ["BTCUSDT", "ETHUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = [
  "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
  "DOGEUSDT", "LTCUSDT", "LINKUSDT", "TRXUSDT",
]
daily_warmup_start = "2018-06"
warmup_start = "2018-06"
start = "2019-01"
end = "2024-12"
initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""


def write_datasets(directory):
    """Copies of the committed stage-1 dataset specs and manifests, and a synthetic
    full-range-2017-2024 spec with a stub manifest (the scorer only hashes it)."""
    for name in ("practice-2022", "verify-2024h1"):
        for suffix in (".toml", ".manifest.json"):
            shutil.copyfile(SPECS / f"{name}{suffix}", directory / f"{name}{suffix}")
    (directory / f"{FULL}.toml").write_text(FULL_SPEC)
    (directory / f"{FULL}.manifest.json").write_text('{"synthetic": "long-window stub"}\n')


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


LABELS = {
    "MS": (v2.MODE_SWITCH_STRATEGY, "MS"),
    "F": (score.GRID, "F"),
    "A": (score.GRID, "A"),
    "D": (BENCHMARK, "D"),
    "ungated": (score.BASELINE, None),
}
RETURNS = {"MS": "10", "F": "1", "A": "1", "D": "3"}


def modes(dataset):
    """An MS row's ``modes`` as Task 6 writes it: the times sum to the window's length."""
    total = score.REGISTERED_DAYS[dataset] * DAY_MS
    grid = uptrend = total // 4
    return {
        "time_ms": {"cash": total - grid - uptrend, "grid": grid, "uptrend": uptrend},
        "switches": 9,
        "uptrend_trades": 20,
        "stops": 4,
        "fades": 16,
        "held_at_end": {"quantity": "0", "value": "0"},
        "buy_and_hold_final": "104.5",
    }


def row(dataset, symbol, path, role="MS", ret="10", dd=2.0, **changes):
    """One result row. ``role`` "ungated" is the ungated V0 baseline."""
    strategy, variant = LABELS[role]
    data = {
        "symbol": symbol,
        "path_mode": path,
        "strategy": strategy,
        "initial_quote": "100",
        "final_total_equity": str(Decimal(100) + Decimal(ret)),
        "return_pct": float(ret),
        "max_drawdown_pct": dd,
        "active_max_drawdown_pct": dd,
        "buy_and_hold_max_drawdown_pct": 5.0,
        "hard_drawdown_halts": 0,
        "completed_cycles": 0 if role == "D" else 60,
        "completed_cycles_by_week": {} if role == "D" else {"2019-W02": 60},
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
    if variant is not None:
        data["variant"] = variant
    if role == "MS":
        january, february = month_bounds_ms(FIRST_MONTH[dataset])
        data["modes"] = modes(dataset)
        # The bot +5% and buy-and-hold +10% in the first month, then buy-and-hold falls:
        # an upside capture of 0.5.
        data["hourly_equity"] = [[january, "100", "100"], [february, "105", "110"]]
    return data | changes


def results(dataset, kind, returns):
    """One results.json's rows. The MS file carries D's rows (``--trend-benchmark``) and
    every file the ungated V0 baseline's, which here fail C1 and lose money: counting
    them anywhere would fail the mode switcher."""
    roles = {"MS": ("MS", "D"), "F": ("F",), "A": ("A",)}[kind]
    rows = []
    for role in (*roles, "ungated"):
        for pair in TRADED[dataset]:
            for path in PATH_MODES:
                if role == "ungated":
                    rows.append(row(dataset, pair, path, role, "-50", 60.0))
                else:
                    ret = returns.get((dataset, role), RETURNS[role])
                    rows.append(row(dataset, pair, path, role, ret))
    return rows


def document(dataset, rows, directory, checks):
    """A results.json as the CLI writes it, pinned to the specs in ``directory``."""
    failures = cli.result_failures(rows)
    return {
        "dataset": dataset,
        "purpose": "synthetic",
        "feature_version": FEATURE_VERSION,
        "engine_version": ENGINE_VERSION,
        "manifest_created_at": "synthetic",
        "spec_sha256": sha256_file(directory / f"{dataset}.toml"),
        "manifest_sha256": sha256_file(directory / f"{dataset}.manifest.json"),
        "config_sha256": FROZEN_CONFIG,
        "code_commit": FROZEN_COMMIT,
        "code_sha256": jobs.SOURCE_IDENTITY,
        "integrity_rules": {"version": INTEGRITY_RULES, "volume_drift_tolerance": "0.001"},
        "fees": {"maker": "0", "taker": "0.0009"},
        "valid": not failures,
        "failures": failures,
        "hourly_cross_checks": checks,
        "results": rows,
    }


class ScorerFiles(unittest.TestCase):
    """Writes results files to a temporary directory and runs the scorer on them, with
    the synthetic commit as its own and the temporary dataset specs as the committed."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)
        self.out = self.tmp / "verdict.json"
        self.datasets = self.tmp / "datasets"
        self.datasets.mkdir()
        write_datasets(self.datasets)
        # The checks come from unchanged specs, so that a test can change one on disk.
        pristine = self.tmp / "pristine"
        pristine.mkdir()
        write_datasets(pristine)
        self.checks = {name: clean_checks(load_spec(pristine / f"{name}.toml")) for name in WINDOWS}
        for patcher in (
            patch.object(v2, "code_commit", return_value=FROZEN_COMMIT),
            patch.object(v2, "DATASET_SPECS", self.datasets),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def document(self, dataset, kind, returns=()):
        rows = results(dataset, kind, dict(returns))
        return document(dataset, rows, self.datasets, json.loads(json.dumps(self.checks[dataset])))

    def files(self, returns=()):
        """An MS file and an F file per window."""
        return {
            (dataset, kind): self.document(dataset, kind, returns)
            for dataset in WINDOWS
            for kind in ("MS", "F")
        }

    def rewrite(self, dataset, old, new):
        path = self.datasets / f"{dataset}.toml"
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))

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
            code = v2.main([*self.write(documents), "--out", str(self.out)])
        verdict = json.loads(self.out.read_text()) if self.out.exists() else None
        return code, stdout.getvalue(), stderr.getvalue(), verdict

    def refused(self, documents, reason):
        code, _, stderr, verdict = self.run_scorer(documents)
        self.assertEqual(code, 2, stderr)
        self.assertIn(reason, stderr)
        self.assertNotIn("windows", verdict)
        self.assertEqual(verdict["outcome"], "refused")
        self.assertTrue(any(reason in line for line in verdict["reasons"]))
        return verdict


class FileTests(ScorerFiles):
    def test_cli_scores_ms_against_f_and_ignores_the_ungated_rows(self) -> None:
        code, text, _, verdict = self.run_scorer(self.files().values())
        self.assertEqual(code, 0)
        self.assertEqual((verdict["scoring"], verdict["outcome"]), (v2.SCORING, "pass"))
        # Spec v1's feature check refuses an unknown "gated grid" strategy.
        self.assertFalse(v2.MODE_SWITCH_STRATEGY.startswith("gated grid"))
        self.assertEqual(list(verdict["windows"]), list(WINDOWS))
        full = verdict["windows"][FULL]
        self.assertTrue(full["scored"] and full["passed"])
        self.assertEqual(list(full["criteria"]), ["C1", "C2", "C3", "C4", "C5", "C6"])
        self.assertTrue(all(c["passed"] for c in full["criteria"].values()))
        # 3 pairs on 2 paths, each 80 round trips over 2,192 days.
        self.assertEqual(len(full["runs"]), 6)
        c5 = full["criteria"]["C5"]["numbers"]
        self.assertEqual(F(c5["mean round trips per year"]), 80 * score.YEAR_DAYS / 2192)
        self.assertEqual(full["criteria"]["C6"]["numbers"]["share %"], "100")
        first = full["runs"][0]
        self.assertEqual((first["symbol"], first["path"]), ("BTCUSDT", "high_first"))
        self.assertEqual(first["round_trips"], 80)
        self.assertEqual(first["round_trips_by_mode"], {"grid": 60, "uptrend": 20})
        self.assertEqual(first["time_in_mode_pct"], {"cash": "50", "grid": "25", "uptrend": "25"})
        self.assertEqual((first["mode_switches"], first["uptrend_stops"]), (9, 4))
        self.assertEqual(first["uptrend_fades"], 16)
        self.assertEqual(first["upside_capture"], "0.5")
        self.assertEqual(first["buy_and_hold_return_pct"], "4.5")
        self.assertGreater(
            F(first["annualised_gate_ratio"]), F(first["always_grid_annualised_gate_ratio"])
        )
        self.assertNotIn("baseline_gate_ratio", first)  # v1's C6 baseline is not v2's
        # The comparators: F's runs, and D's, which ride on the MS files.
        self.assertEqual(len(full["always_grid"]["runs"]), 6)
        self.assertEqual(full["always_grid"]["mean_return_pct"], "1")
        self.assertEqual(len(full["benchmark_d"]["runs"]), 6)
        self.assertEqual(full["benchmark_d"]["mean_return_pct"], "3")
        # The reported windows: practice-2022 SOLUSDT is excluded for every role (P4).
        for name in WINDOWS[1:]:
            with self.subTest(name):
                reported = verdict["windows"][name]
                self.assertFalse(reported["scored"])
                self.assertEqual(len(reported["runs"]), 4)
                self.assertEqual(len(reported["benchmark_d"]["runs"]), 4)
        self.assertFalse(
            verdict["comparison_mask"]["practice-2022"]["pairs"]["SOLUSDT"]["included"]
        )
        self.assertEqual(verdict["c7"], score.C7_NOTE)
        self.assertEqual(len(verdict["inputs"]), 6)
        recorded = verdict["inputs"][0]
        for key in ("path", "sha256", "dataset", "spec_sha256", "manifest_sha256"):
            self.assertIn(key, recorded)
        self.assertEqual(
            (recorded["config_sha256"], recorded["code_commit"], recorded["code_sha256"]),
            (FROZEN_CONFIG, FROZEN_COMMIT, jobs.SOURCE_IDENTITY),
        )
        self.assertEqual(verdict["scorer"]["code_sha256"], jobs.SOURCE_IDENTITY)
        self.assertIn("Outcome (spec v2 section 8): pass", text)
        self.assertIn(score.C7_NOTE, text)
        text.encode("ascii")  # any console can print it

        # A file of another v1 variant (A) is refused, and so is a set without F's rows,
        # and an MS row under v1's gated-grid strategy.
        documents = self.files()
        documents[FULL, "F"] = self.document(FULL, "A")
        self.refused(documents.values(), "not a spec v2 row: variant A")
        without_f = {key: file for key, file in self.files().items() if key[1] != "F"}
        self.refused(without_f.values(), "F full-range-2017-2024 BTCUSDT high_first: missing")
        documents = self.files()
        documents[FULL, "MS"]["results"][0]["strategy"] = score.GRID
        self.refused(documents.values(), "variant 'MS' under strategy 'gated grid (price-only-v1)'")
        documents = self.files()
        documents[FULL, "F"]["results"][0]["strategy"] = v2.MODE_SWITCH_STRATEGY
        self.refused(documents.values(), "variant 'F' under strategy 'mode switcher (spec-v2)'")
        # An MS row without a field Task 6 must write is refused by name.
        documents = self.files()
        del documents[FULL, "MS"]["results"][0]["modes"]["time_ms"]
        self.refused(documents.values(), "an MS row lacks modes.time_ms")

    def test_reported_windows_decide_nothing_and_a_failed_criterion_fails(self) -> None:
        losing = {("practice-2022", "MS"): "-1", ("verify-2024h1", "MS"): "-1"}
        _, _, _, verdict = self.run_scorer(self.files(losing).values())
        self.assertFalse(verdict["windows"]["practice-2022"]["passed"])
        self.assertEqual(verdict["outcome"], "pass")
        _, text, _, verdict = self.run_scorer(self.files({(FULL, "MS"): "-1"}).values())
        self.assertEqual(verdict["outcome"], "fail")
        self.assertEqual(verdict["reasons"], [f"{FULL}: C2 fails", f"{FULL}: C6 fails"])
        self.assertIn("Outcome (spec v2 section 8): fail", text)

    def test_a_failure_of_the_whole_file_invalidates_its_runs(self) -> None:
        # Built as spec v1's runs_of builds them: a failure of the file, such as a checkout
        # that changed during the run, invalidates every row in it. In the MS file that
        # fails C4; in the F file it makes always-grid invalid, which counts against C6.
        for kind, criterion in (("MS", "C4"), ("F", "C6")):
            with self.subTest(kind):
                documents = self.files()
                file = documents[FULL, kind]
                file["failures"] = [*file["failures"], "the checkout changed during the run"]
                file["valid"] = False
                _, _, _, verdict = self.run_scorer(documents.values())
                self.assertEqual(verdict["outcome"], "fail")
                self.assertEqual(verdict["reasons"], [f"{FULL}: {criterion} fails"])
                failing = verdict["windows"][FULL]["criteria"][criterion]["failing"]
                self.assertEqual(len(failing), 6)
                self.assertIn("the checkout changed during the run", failing[0])

    def test_r1_is_reported_and_gates_nothing(self) -> None:
        _, _, _, verdict = self.run_scorer(self.files().values())
        full = verdict["windows"][FULL]
        # 10% over 72 months: 5 / (0.1 / 72) = 3,600 EUR, far above 100 USDT a run.
        self.assertEqual(full["r1_reported_only"][score.R1_CAPITAL], "3600")
        self.assertNotIn("R1", full["criteria"])
        unreachable = {score.R1_CAPITAL: "not reachable"}
        with patch.object(v2, "economics", return_value=unreachable):
            _, _, _, verdict = self.run_scorer(self.files().values())
        self.assertEqual(verdict["outcome"], "pass")
        self.assertEqual(verdict["windows"][FULL]["r1_reported_only"], unreachable)

    def test_a_missing_run_is_refused(self) -> None:
        documents = self.files()
        for kind in ("MS", "F"):
            with self.subTest(kind):
                left = {key: file for key, file in documents.items() if key != (FULL, kind)}
                verdict = self.refused(left.values(), f"{kind} {FULL} XRPUSDT low_first: missing")
                self.assertIn(f"{kind} {FULL} BTCUSDT high_first: missing", verdict["reasons"])
                self.assertIn(v2.WHOLE_MATRIX, verdict["reasons"])
        documents = self.files()
        documents[FULL, "MS"]["results"] = [
            r
            for r in documents[FULL, "MS"]["results"]
            if (r["symbol"], r["path_mode"], r.get("variant")) != ("ETHUSDT", "low_first", "MS")
        ]
        verdict = self.refused(documents.values(), f"MS {FULL} ETHUSDT low_first: missing")
        self.assertEqual(
            verdict["reasons"], [v2.WHOLE_MATRIX, f"MS {FULL} ETHUSDT low_first: missing"]
        )
        # An input from a window spec v2 does not register.
        documents = self.files()
        stray = {**documents["verify-2024h1", "MS"], "dataset": "long-bull-bear-2022"}
        self.refused([*documents.values(), stray], "'long-bull-bear-2022' is not a spec v2 window")

    def test_reported_windows_must_be_complete(self) -> None:
        documents = self.files()
        no_verify = {key: file for key, file in documents.items() if key[0] != "verify-2024h1"}
        self.refused(no_verify.values(), "verify-2024h1 is not in the inputs")
        for name in (FULL, "practice-2022"):
            with self.subTest(name):
                documents = self.files()
                file = documents[name, "MS"]
                file["results"] = [r for r in file["results"] if r["strategy"] != BENCHMARK]
                self.refused(documents.values(), f"D {name} BTCUSDT high_first: missing")

    def test_inconsistent_comparison_masks_are_refused(self) -> None:
        documents = self.files()
        checks = documents[FULL, "F"]["hourly_cross_checks"]
        next(c for c in checks if c["symbol"] == "ETHUSDT")["minutes_missing"] = 1
        self.refused(documents.values(), f"its comparison mask differs from another {FULL} run's")

    def test_duplicate_rows_are_refused(self) -> None:
        documents = self.files()
        rows = documents[FULL, "MS"]["results"]
        rows.append(dict(rows[0]))
        reason = f"MS {FULL} BTCUSDT high_first has more than one row in the inputs"
        self.refused(documents.values(), reason)
        documents = self.files()
        self.refused([*documents.values(), documents[FULL, "MS"]], reason)
        # D on both the MS and the F run of a window: a second D row for each key.
        documents = self.files()
        file = documents[FULL, "F"]
        file["results"] += [
            r for r in documents[FULL, "MS"]["results"] if r["strategy"] == BENCHMARK
        ]
        self.refused(documents.values(), f"D {FULL} BTCUSDT high_first has more than one row")
        # A duplicate is refused even in a pair-window the mask excludes.
        documents = self.files()
        rows = documents["practice-2022", "MS"]["results"]
        rows.append(next(dict(r) for r in rows if r["symbol"] == "SOLUSDT"))
        self.refused(documents.values(), "MS practice-2022 SOLUSDT high_first has more than one")

    def test_one_included_pair_is_insufficient_evidence(self) -> None:
        documents = self.files()
        for (dataset, _), file in documents.items():
            if dataset == FULL:
                for check in file["hourly_cross_checks"]:
                    if check["symbol"] in ("ETHUSDT", "XRPUSDT"):
                        check["minutes_missing"] = 1
        code, text, _, verdict = self.run_scorer(documents.values())
        self.assertEqual(code, 0)
        self.assertEqual(verdict["outcome"], "insufficient evidence")
        self.assertEqual(
            verdict["reasons"], [f"{FULL}: 1 included pairs; section 5 needs at least 2"]
        )
        # BTCUSDT's two MS runs pass C1-C6, and still nothing passes.
        full = verdict["windows"][FULL]
        self.assertEqual((len(full["runs"]), full["passed"]), (2, True))
        self.assertFalse(verdict["comparison_mask"][FULL]["minimum_evidence"])
        self.assertIn("insufficient evidence", text)

    def test_a_wrong_warm_up_is_refused(self) -> None:
        # Spec v1 section 4's full-range-2017-2024 warms up from 2018-06, hourly and
        # daily. A daily warm-up from 2018-07 is refused: it would follow the hourly one,
        # which the dataset loader itself refuses. Warm-ups that load are refused against
        # the registration, though the evaluation window is right.
        cases = (
            ('daily_warmup_start = "2018-06"', 'daily_warmup_start = "2018-07"', None),
            (
                'daily_warmup_start = "2018-06"',
                'daily_warmup_start = "2018-05"',
                "the committed spec's daily_warmup_start is '2018-05'; spec v2 registers '2018-06'",
            ),
            (
                'warmup_start = "2018-06"\n',
                'warmup_start = "2018-07"\n',
                "the committed spec's warmup_start is '2018-07'; spec v2 registers '2018-06'",
            ),
        )
        for old, new, registered in cases:
            with self.subTest(new):
                write_datasets(self.datasets)
                self.rewrite(FULL, old, new)
                documents = self.files()  # pinned to the changed spec
                verdict = self.refused(
                    documents.values(), "daily_warmup_start" if registered is None else registered
                )
                if registered is not None:
                    self.assertTrue(
                        any(line.startswith(f"{FULL}: ") for line in verdict["reasons"])
                    )

    def test_a_wrong_window_is_refused(self) -> None:
        self.rewrite(FULL, 'start = "2019-01"', 'start = "2019-02"')
        verdict = self.refused(
            self.files().values(),
            f"{FULL}: the committed spec's evaluation window is 2161 days; spec v2 section 8 "
            "registers 2192",
        )
        self.assertIn(
            f"{FULL}: the committed spec's start is '2019-02'; spec v2 registers '2019-01'",
            verdict["reasons"],
        )
        write_datasets(self.datasets)
        self.rewrite("practice-2022", 'end = "2023-01"', 'end = "2023-02"')
        self.refused(self.files().values(), "practice-2022: the committed spec's end is '2023-02'")
        write_datasets(self.datasets)
        self.rewrite(FULL, '"ETHUSDT", "XRPUSDT"]', '"ETHUSDT", "SOLUSDT", "XRPUSDT"]')
        self.refused(self.files().values(), f"{FULL}: the committed spec's traded is")

    def test_refused_scoring_overwrites_a_stale_verdict(self) -> None:
        documents = self.files()
        self.assertEqual(self.run_scorer(documents.values())[3]["outcome"], "pass")
        for file in documents.values():
            file["config_sha256"] = "tuned"  # every file agrees, on the wrong config
        verdict = self.refused(documents.values(), "not the committed config/default.toml")
        self.assertIn(score.FROZEN_HINT, verdict["reasons"])
        for change, reason in (
            (lambda f: f.update(spec_sha256="0" * 64), f"{FULL}: spec "),
            (lambda f: f.update(manifest_sha256="0" * 64), f"{FULL}: manifest "),
            (lambda f: f.update(code_commit=FROZEN_COMMIT + "+dirty"), "not a clean commit"),
            (lambda f: f.update(code_sha256="0" * 64), "not the scorer's"),
            (lambda f: f.update(engine_version="drawdown-recovery-v1"), "engine"),
            (lambda f: f["results"][0]["rules"].update(fee_rate="0.001"), "maker fee 0.001"),
            (lambda f: f["results"][0]["rules"].update(taker_fee_rate="0.001"), "taker fee"),
            (lambda f: f["results"][0].pop("max_drawdown_pct"), "an MS row lacks max_drawdown_pct"),
            # D's rows follow the MS rows in the MS file; D has no field list of its own.
            (lambda f: f["results"][6].pop("max_drawdown_pct"), "malformed results (KeyError"),
        ):
            with self.subTest(reason):
                documents = self.files()
                change(documents[FULL, "MS"])
                self.refused(documents.values(), reason)
        # A run that stops midway leaves "not scored", never an earlier verdict.
        paths = self.write(self.files().values())
        with (
            patch.object(v2, "assess", side_effect=RuntimeError("interrupted")),
            self.assertRaises(RuntimeError),
        ):
            v2.main([*paths, "--out", str(self.out)])
        self.assertEqual(json.loads(self.out.read_text())["outcome"], "not scored")
        # The verdict never overwrites an input.
        (path,) = self.write([self.files()[FULL, "MS"]])
        results_file = Path(path) / "results.json"
        before = results_file.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            v2.main([path, "--out", str(results_file)])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(results_file.read_bytes(), before)

    def test_a_structure_run_is_refused(self) -> None:
        # Spec v2 section 2: V0's features (price-only-v1); no --structure run is registered.
        documents = self.files()
        documents[FULL, "MS"] |= {
            "feature_version": FEATURE_VERSION + "+structure-v2",
            "baseline_feature_version": FEATURE_VERSION,
        }
        self.refused(documents.values(), "spec v2 runs V0's features")

    def test_the_module_runs_as_a_command_and_checks_its_real_commit(self) -> None:
        # Unpatched, the command reads its own commit from git, which is never the
        # synthetic one the files record, so the whole batch is refused.
        paths = self.write(self.files().values())
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        command = [sys.executable, "-m", "crypto_grid_bot.backtest.acceptance_v2", *paths]
        done = subprocess.run(
            [*command, "--out", str(self.out)], capture_output=True, env=env, check=False
        )
        self.assertEqual(done.returncode, 2, done.stderr)
        verdict = json.loads(self.out.read_text())
        self.assertEqual(verdict["outcome"], "refused")
        self.assertTrue(any("the scorer runs at" in line for line in verdict["reasons"]))


if __name__ == "__main__":
    unittest.main()
