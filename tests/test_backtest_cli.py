"""R1: integrity failures must invalidate verify/run and never reach replay; a traded
pair's own failure excludes only that pair-window (spec v1 §5)."""

import contextlib
import gc
import io
import json
import math
import subprocess
import sys
import tempfile
import unittest
import weakref
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import test_backtest_masked_checks as masked_checks

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest import acceptance as score
from crypto_grid_bot.backtest import jobs
from crypto_grid_bot.backtest.dataset import fetch_dataset, load_spec, local_path, write_manifest
from crypto_grid_bot.backtest.features import (
    FEATURE_VERSION,
    STRUCTURE_FEATURE_VERSION,
    FeatureEngine,
    SeriesFeatures,
)
from crypto_grid_bot.backtest.klines import Kline, aggregate, month_bounds_ms
from crypto_grid_bot.backtest.masking import (
    HOUR_MS,
    INCOMPLETE_HOUR,
    NO_HOURLY_BAR,
    NO_MINUTE_BARS,
    MonthMask,
    apply_seventeen_percent,
)
from crypto_grid_bot.backtest.replay import cross_check_hourly
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.simulation.runner import SimulationPolicy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_nopool  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SPEC = str(ROOT / "config/datasets/verify-2024h1.toml")
# What a fake job records for a keyword the CLI did not pass: a clean window must submit
# every job exactly as before masks existed.
NOT_PASSED = "not passed"
CLEAN = {
    "hours_compared": 10,
    "hours_mismatched": 0,
    "hours_missing": 0,
    "hours_absent_from_minutes": 0,
    "hours_absent_from_both": 0,
    "hours_incomplete": 0,
    "minutes_missing": 0,
}


class Done:
    def __init__(self, value):
        self.value = value

    def result(self):
        return self.value


class Inline:
    """Synchronous stand-in for ProcessPoolExecutor."""

    def __init__(self, max_workers, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        return Done(fn(*args))


def good_result(symbol, mode, gated):
    return {
        "symbol": symbol,
        "path_mode": mode,
        "strategy": "gated" if gated else "ungated",
        "return_pct": 0.0,
        "max_drawdown_pct": 0.0,
        "buy_and_hold_return_pct": 0.0,
        "buy_and_hold_max_drawdown_pct": 0.0,
        "fees": "0",
        "buys": 0,
        "sells": 0,
        "grids_opened": 0,
        "range_exits": 0,
        "time_with_inventory_pct": 0.0,
        "max_order_requests_per_day": 0,
        "halted_at": None,
        "accounting_problems": [],
        "transient_pauses": 0,
        "bars": 100,
        "hourly_equity": [],
    }


def failing(field):
    """A value that fails integrity field ``field``: none compared, or a count above zero."""
    return {field: 0} if field.endswith("_compared") else {field: 1}


def month_mask(month, reasons):
    """The ``MonthMask`` of ``month``, every hour expected, whose masked hours are ``reasons``'s
    (hour -> reason, every one a real defect) before the 17% rule, which then applies."""
    start, end = month_bounds_ms(month)
    masked = frozenset(reasons)
    found = MonthMask(
        month,
        frozenset(range(start, end, HOUR_MS)),
        masked,
        dict(reasons),
        masked,
        frozenset(),
        frozenset(),
        False,
    )
    return apply_seventeen_percent(found)


def symbol_mask(symbol, *months):
    return jobs.SymbolMask(symbol, frozenset().union(*(m.masked for m in months)), months)


FEB_2024, MAR_2024 = month_bounds_ms("2024-02")[0], month_bounds_ms("2024-03")[0]
FEB_3 = FEB_2024 + 2 * 24 * HOUR_MS
# verify-2024h1's masks in the comparison-mask test: ADAUSDT's masked hours, among them two
# that cross a month's end; BTCUSDT's six days without minutes in February, over 17% of it,
# which exclude the month; DOGEUSDT's mask, a set with no hour in it (a repaired row only).
# Every other symbol's mask is None.
MASKED_WINDOW = {
    "ADAUSDT": symbol_mask(
        "ADAUSDT",
        month_mask(
            "2024-02",
            {
                FEB_3 + 5 * HOUR_MS: INCOMPLETE_HOUR,
                FEB_3 + 6 * HOUR_MS: INCOMPLETE_HOUR,
                FEB_3 + 7 * HOUR_MS: NO_MINUTE_BARS,
                FEB_3 + 9 * HOUR_MS: INCOMPLETE_HOUR,
                MAR_2024 - HOUR_MS: NO_HOURLY_BAR,
            },
        ),
        month_mask("2024-03", {MAR_2024: NO_HOURLY_BAR}),
    ),
    "BTCUSDT": symbol_mask(
        "BTCUSDT",
        month_mask("2024-02", {FEB_2024 + h * HOUR_MS: NO_MINUTE_BARS for h in range(6 * 24)}),
    ),
    "DOGEUSDT": symbol_mask("DOGEUSDT", month_mask("2024-02", {})),
}
MASKED_WINDOW_COMPARISON_MASK = {
    "ADAUSDT": {
        "masked": [
            {"from": "2024-02-03T05:00Z", "to": "2024-02-03T07:00Z", "reason": "incomplete hour"},
            {"from": "2024-02-03T07:00Z", "to": "2024-02-03T08:00Z", "reason": "no minute bars"},
            {"from": "2024-02-03T09:00Z", "to": "2024-02-03T10:00Z", "reason": "incomplete hour"},
            {"from": "2024-02-29T23:00Z", "to": "2024-03-01T01:00Z", "reason": "no hourly bar"},
        ],
        "excluded_months": [],
    },
    "BTCUSDT": {
        "masked": [
            {"from": "2024-02-01T00:00Z", "to": "2024-02-07T00:00Z", "reason": "no minute bars"},
            {
                "from": "2024-02-07T00:00Z",
                "to": "2024-03-01T00:00Z",
                "reason": "month excluded (17% rule)",
            },
        ],
        "excluded_months": ["2024-02"],
    },
}


# The comparison mask of a window whose only entry is XRPUSDT's breach of two quotes.
QUOTE_BREACH_MASK = {"XRPUSDT": {"masked": [], "excluded_months": [], "tick_limit_quotes": 2}}


class CliIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.spec = SPEC
        self.checks = dict(CLEAN)
        self.overrides: dict[str, dict] = {}  # one symbol's check fields
        self.result_patch = {}
        self.replays = []
        self.fees = []
        self.strict = []
        self.policies = []
        self.arms = []
        self.verified = []
        self.symbol_masks: dict[str, jobs.SymbolMask] = {}  # every other symbol's is None
        self.events = []  # each job and the comparison mask, in the order they happen
        self.configs = []  # the config every check was given
        self.quote = None  # what XRPUSDT's statistic job returns (mask-report)
        comparison_mask = cli.comparison_mask

        def recorded_comparison_mask(masks):
            self.events.append(("comparison mask",))
            return comparison_mask(masks)

        patches = [
            patch.object(cli, "ProcessPoolExecutor", Inline),
            patch.object(cli, "load_manifest", lambda path: {"created_at": "t"}),
            patch.object(cli, "verify_dataset", lambda *a: self.verified.append(a)),
            patch.object(cli, "code_commit", lambda: "0123abc"),
            patch.object(cli, "_identity", lambda *a: {}),
            patch.object(cli, "mask_job", self.fake_mask),
            patch.object(cli, "comparison_mask", recorded_comparison_mask),
            patch.object(cli, "cross_check_job", self.fake_check),
            patch.object(cli, "quote_test_job", self.fake_quote),
            patch.object(cli, "run_job", self.fake_run),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def fake_mask(self, spec, data_dir, symbol):
        self.events.append(("mask", symbol))
        return self.symbol_masks.get(symbol, jobs.SymbolMask(symbol, None, ()))

    def fake_check(
        self,
        spec,
        data_dir,
        symbol,
        strict_volume=False,
        *,
        mask=NOT_PASSED,
        config_path=NOT_PASSED,
    ):
        self.events.append(("check", symbol, mask))
        self.strict.append(strict_volume)
        self.configs.append(config_path)
        return {"symbol": symbol, **self.checks, **self.overrides.get(symbol, {})}

    def fake_quote(self, spec, data_dir, config_path, mask):
        self.events.append(("quote", mask))
        self.configs.append(config_path)
        return self.quote

    def fake_run(
        self,
        spec,
        config,
        data_dir,
        symbol,
        mode,
        gated,
        fees=None,
        policy=None,
        *,
        masks=NOT_PASSED,
    ):
        self.events.append(("run", symbol, masks))
        self.replays.append(symbol)
        self.fees.append(fees)
        self.policies.append(policy)
        self.arms.append((gated, policy))
        return {**good_result(symbol, mode, gated), **self.result_patch}

    def main(self, command, *extra):
        """The CLI's exit code; what it printed is kept in ``self.printed``."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([command, "--spec", str(self.spec), "--out", self.temp.name, *extra])
        self.printed = out.getvalue()
        return code

    def test_clean_data_verifies_and_runs(self):
        self.assertEqual(0, self.main("verify"))
        self.assertEqual(0, self.main("run"))
        self.assertTrue(self.replays)
        (written,) = Path(self.temp.name).rglob("results.json")
        document = json.loads(written.read_text())
        self.assertTrue(document["valid"])
        self.assertNotIn("excluded_pairs", document)  # every check passed: no exclusion

    def test_mask_is_computed_before_the_first_job_and_written_only_when_non_empty(self):
        # Spec v1 section 5: masking runs first, for every checked symbol, and the
        # comparison mask is fixed before any check or run. Each check then takes its own
        # symbol's mask, and every run the whole map. A clean window (every mask None, as
        # in stage 1) takes today's exact path: each job is submitted as before, and
        # neither verify nor results.json carries a comparison mask.
        symbols = cli.checked_symbols(jobs.load_spec(Path(self.spec)))
        self.assertEqual(0, self.main("verify"))
        self.assertNotIn("comparison_mask", json.loads(self.printed))
        self.assertEqual(0, self.main("run", "--out", str(Path(self.temp.name) / "clean")))
        (clean,) = Path(self.temp.name, "clean").rglob("results.json")
        self.assertNotIn("comparison_mask", json.loads(clean.read_text()))
        self.assertEqual({NOT_PASSED}, {e[2] for e in self.events if e[0] in ("check", "run")})
        # A masked window: the same mask in verify, in mask-report and in results.json.
        self.symbol_masks = MASKED_WINDOW
        masks = {s: MASKED_WINDOW[s].mask if s in MASKED_WINDOW else None for s in symbols}
        self.assertEqual(0, self.main("verify"))
        self.assertEqual(MASKED_WINDOW_COMPARISON_MASK, json.loads(self.printed)["comparison_mask"])
        self.events.clear()
        self.assertEqual(0, self.main("mask-report"))
        report = json.loads(self.printed)
        self.assertEqual(MASKED_WINDOW_COMPARISON_MASK, report["comparison_mask"])
        # No check and no run.
        self.assertEqual(["mask"] * len(symbols) + ["comparison mask"], [e[0] for e in self.events])
        self.events.clear()
        self.assertEqual(0, self.main("run", "--out", str(Path(self.temp.name) / "masked")))
        self.assertEqual(
            ["mask"] * len(symbols) + ["comparison mask"] + ["check"] * len(symbols) + ["run"] * 8,
            [e[0] for e in self.events],
        )
        self.assertEqual(symbols, [e[1] for e in self.events if e[0] == "mask"])
        # A symbol whose mask is None is checked as before; a set, even an empty one, is
        # passed to its check.
        self.assertEqual(
            [(s, NOT_PASSED if masks[s] is None else masks[s]) for s in symbols],
            [e[1:] for e in self.events if e[0] == "check"],
        )
        self.assertEqual([masks] * 8, [e[2] for e in self.events if e[0] == "run"])
        (written,) = Path(self.temp.name, "masked").rglob("results.json")
        document = json.loads(written.read_text())
        self.assertEqual(MASKED_WINDOW_COMPARISON_MASK, document["comparison_mask"])
        # Variant D's runs take the map too.
        seen = []

        def fake_trend(spec, config, data_dir, symbol, mode, fees=None, *, masks=NOT_PASSED):
            seen.append(masks)
            return {**good_result(symbol, mode, True), "strategy": "trend benchmark D"}

        with patch.object(cli, "trend_job", fake_trend):
            out = str(Path(self.temp.name) / "benchmark")
            self.assertEqual(0, self.main("run", "--trend-benchmark", "--out", out))
        self.assertEqual([masks] * 4, seen)  # two pairs, two paths
        # So do the missed-fill sweep's runs, with their trigger.
        swept = []

        def fake_run(*args, fill_trigger=None, masks=NOT_PASSED):
            swept.append((fill_trigger, masks))
            return self.fake_run(*args)

        with patch.object(cli, "run_job", fake_run):
            out = str(Path(self.temp.name) / "swept")
            self.assertEqual(0, self.main("run", "--fill-trigger", "0.0002", "--out", out))
        self.assertEqual([(Decimal("0.0002"), masks)] * 8, swept)

    def test_the_month_tables_do_not_outlive_the_mask_phase(self):
        # Task 5's review: each SymbolMask's month tables (every month's expected hours,
        # tens of MB over a long window) serve only the comparison mask and the map of
        # masked hours. None is still held when the first run starts; only the masked
        # hours go on.
        tables = []

        def fake_mask(spec, data_dir, symbol):
            month = month_mask("2024-02", {FEB_3: NO_MINUTE_BARS})
            symbol_mask = jobs.SymbolMask(symbol, month.masked, (month,))
            tables.append(weakref.ref(symbol_mask))
            return symbol_mask

        held = []

        def fake_run(*args, masks):
            gc.collect()
            held.append(sum(table() is not None for table in tables))
            return self.fake_run(*args)

        with patch.object(cli, "mask_job", fake_mask), patch.object(cli, "run_job", fake_run):
            self.assertEqual(0, self.main("run"))
        self.assertTrue(tables)
        self.assertEqual([0] * 8, held)

    def test_a_traded_pairs_own_failed_check_excludes_only_that_pair_window(self):
        # Spec v1 section 5, as for practice-2022's SOLUSDT with daily history from
        # 2020-05: its P3 presence check fails on the days before its listing. Only that
        # pair-window is excluded: it is not replayed and has no rows, its failing check
        # stays in its integrity fields, and BTCUSDT and XRPUSDT run as a valid run.
        practice = str(ROOT / "config/datasets/practice-2022.toml")
        daily = {"daily_days_compared": 10} | {field: 0 for field in cli.DAILY_INTEGRITY_FIELDS}
        self.overrides = {"SOLUSDT": {**daily, "daily_days_missing": 102}}
        self.assertEqual(0, self.main("verify", "--spec", practice))
        self.assertEqual(0, self.main("run", "--spec", practice))
        self.assertEqual({"BTCUSDT", "XRPUSDT"}, set(self.replays))
        self.assertEqual(8, len(self.replays))  # 2 pairs x 2 paths x gated and ungated
        (written,) = Path(self.temp.name).rglob("results.json")
        document = json.loads(written.read_text())
        self.assertEqual((True, []), (document["valid"], document["failures"]))
        reasons = ["SOLUSDT: daily_days_missing=102"]
        self.assertEqual({"SOLUSDT": reasons}, document["excluded_pairs"])
        (sol,) = [c for c in document["hourly_cross_checks"] if c["symbol"] == "SOLUSDT"]
        self.assertEqual(102, sol["daily_days_missing"])
        self.assertEqual({"BTCUSDT", "XRPUSDT"}, {r["symbol"] for r in document["results"]})

    def test_an_xrp_quote_breach_excludes_its_pair_window_and_enters_the_comparison_mask(self):
        # Spec v1 section 5 rule 8: XRPUSDT's cross-check records tick_limit_quotes only when
        # a replayed quote breaks the spread limit. The record is XRP's own failure, which
        # excludes its pair-window for every variant (no rows, an excluded_pairs entry, the
        # window still valid), and the comparison mask records the breach beside the mask the
        # hours gave it. A pass writes nothing anywhere.
        practice = str(ROOT / "config/datasets/practice-2022.toml")
        self.assertEqual(0, self.main("verify", "--spec", practice))
        self.assertNotIn("comparison_mask", json.loads(self.printed))
        self.assertNotIn("excluded_pairs", json.loads(self.printed))
        self.assertEqual(0, self.main("run", "--spec", practice, "--out", self.temp.name + "/pass"))
        (written,) = Path(self.temp.name, "pass").rglob("results.json")
        document = json.loads(written.read_text())
        self.assertFalse({"comparison_mask", "excluded_pairs"} & set(document))
        self.assertEqual(
            {"BTCUSDT", "SOLUSDT", "XRPUSDT"}, {r["symbol"] for r in document["results"]}
        )
        self.assertFalse(any("tick_limit_quotes" in c for c in document["hourly_cross_checks"]))
        # The breach, and XRP's hours masked as well.
        july = month_bounds_ms("2022-07")[0]
        self.symbol_masks = {
            "XRPUSDT": symbol_mask(
                "XRPUSDT",
                month_mask("2022-07", {july + h * HOUR_MS: NO_MINUTE_BARS for h in range(3)}),
            )
        }
        self.overrides = {"XRPUSDT": {"tick_limit_quotes": 7}}
        reason = ["XRPUSDT: tick_limit_quotes=7"]
        mask = {
            "XRPUSDT": {
                "masked": [
                    {
                        "from": "2022-07-01T00:00Z",
                        "to": "2022-07-01T03:00Z",
                        "reason": "no minute bars",
                    }
                ],
                "excluded_months": [],
                "tick_limit_quotes": 7,
            }
        }
        self.assertEqual(0, self.main("verify", "--spec", practice))
        printed = json.loads(self.printed)
        self.assertEqual(
            ({"XRPUSDT": reason}, mask), (printed["excluded_pairs"], printed["comparison_mask"])
        )
        self.replays.clear()
        self.assertEqual(
            0, self.main("run", "--spec", practice, "--out", self.temp.name + "/breach")
        )
        self.assertEqual({"BTCUSDT", "SOLUSDT"}, set(self.replays))
        (written,) = Path(self.temp.name, "breach").rglob("results.json")
        document = json.loads(written.read_text())
        self.assertEqual((True, []), (document["valid"], document["failures"]))
        self.assertEqual({"XRPUSDT": reason}, document["excluded_pairs"])
        self.assertEqual(mask, document["comparison_mask"])
        self.assertEqual({"BTCUSDT", "SOLUSDT"}, {r["symbol"] for r in document["results"]})
        (xrp,) = [c for c in document["hourly_cross_checks"] if c["symbol"] == "XRPUSDT"]
        self.assertEqual(7, xrp["tick_limit_quotes"])
        # With no hour masked, the breach is the whole mask.
        self.symbol_masks = {}
        self.assertEqual(0, self.main("verify", "--spec", practice))
        quotes = {"XRPUSDT": {"masked": [], "excluded_months": [], "tick_limit_quotes": 7}}
        self.assertEqual(quotes, json.loads(self.printed)["comparison_mask"])

    def test_every_check_is_given_the_config(self):
        # Rule 8 reads config/default.toml's maximum_spread_pct in XRPUSDT's check, so the
        # CLI passes --config to every check, masked or not.
        self.assertEqual(0, self.main("verify"))
        self.assertEqual({Path("config/default.toml")}, set(self.configs))
        self.configs.clear()
        self.symbol_masks = MASKED_WINDOW
        self.assertEqual(0, self.main("verify", "--config", "other.toml"))
        symbols = cli.checked_symbols(jobs.load_spec(Path(self.spec)))
        self.assertEqual([Path("other.toml")] * len(symbols), self.configs)

    def test_mask_report_prints_xrps_statistic_only_where_xrp_is_traded(self):
        # Ruling: mask-report prints rule 8's statistic, the same one the cross-check
        # records, when XRPUSDT is traded, run on XRP's own mask; elsewhere the key is null
        # and no statistic is computed. Its comparison mask carries the breach, as a run's.
        self.assertEqual(0, self.main("mask-report"))
        report = json.loads(self.printed)
        self.assertIsNone(report["xrp_quote_test"])
        self.assertNotIn("quote", [e[0] for e in self.events])
        practice = str(ROOT / "config/datasets/practice-2022.toml")
        passing = {
            "maximum_spread_pct": "0.15",
            "widest_spread_pct": "0.0999",
            "tick_limit_quotes": 0,
            "breaches": False,
        }
        breach = {
            **passing,
            "widest_spread_pct": "0.1998",
            "tick_limit_quotes": 2,
            "breaches": True,
        }
        xrp_mask = symbol_mask("XRPUSDT", month_mask("2022-07", {}))
        for quote, comparison in ((passing, {}), (breach, QUOTE_BREACH_MASK)):
            with self.subTest(quote=quote):
                self.events.clear()
                self.quote, self.symbol_masks = quote, {"XRPUSDT": xrp_mask}
                self.assertEqual(0, self.main("mask-report", "--spec", practice))
                report = json.loads(self.printed)
                self.assertEqual(quote, report["xrp_quote_test"])
                self.assertEqual(comparison, report["comparison_mask"])
                # One statistic job, after every mask and before any other job, which is
                # given XRPUSDT's own mask and the config.
                self.assertEqual("comparison mask", self.events[-2][0])
                self.assertEqual(("quote", xrp_mask.mask), self.events[-1])
                self.assertEqual([Path("config/default.toml")], self.configs[-1:])
        self.assertEqual(0, self.main("mask-report", "--spec", practice, "--config", "x.toml"))
        self.assertEqual(Path("x.toml"), self.configs[-1])

    def test_a_failure_of_the_market_proxys_hours_still_excludes_every_pair(self):
        # BTCUSDT is traded too, but as the proxy its hours feed every pair's regime, so a
        # failure about them is never its own: nothing replays, whatever the other pairs
        # show. A 1m or 1d bar that disagrees with its hours counts as one, since the
        # check cannot show which archive is wrong, and so does an hour left unchecked:
        # one with no minutes, or none compared at all (the automated review of #170).
        fields = {*cli.INTEGRITY_FIELDS, *cli.DAILY_INTEGRITY_FIELDS, "hours_compared"}
        self.assertLessEqual(cli.PROXY_HOURLY_FIELDS, fields)
        self.assertEqual(
            cli.PROXY_HOURLY_FIELDS,
            {
                "hours_compared",
                "hours_mismatched",
                "hours_missing",
                "hours_absent_from_minutes",
                "hours_absent_from_both",
                "daily_days_mismatched",
                "daily_days_hours_incomplete",
            },
        )
        practice = str(ROOT / "config/datasets/practice-2022.toml")
        daily = {"daily_days_compared": 10} | {field: 0 for field in cli.DAILY_INTEGRITY_FIELDS}
        shared = sorted(cli.PROXY_HOURLY_FIELDS)
        for overrides in (
            *({"BTCUSDT": {**daily, **failing(field)}} for field in shared),
            {"BTCUSDT": {"hours_missing": 1}, "SOLUSDT": {"hours_incomplete": 1}},
            # Its own daily failure as well does not make the hourly one its own.
            {"BTCUSDT": {**daily, "daily_days_missing": 1, "hours_mismatched": 1}},
        ):
            with self.subTest(overrides=overrides):
                self.overrides = overrides
                self.assertEqual(2, self.main("verify", "--spec", practice))
                self.assertEqual(2, self.main("run", "--spec", practice))
                self.assertEqual([], self.replays)
                self.assertEqual([], list(Path(self.temp.name).rglob("results.json")))

    def test_a_traded_proxys_minute_or_daily_failure_excludes_only_its_pair_window(self):
        # Codex's review of #170: BTCUSDT's 1m and 1d bars feed only its own runs, so a
        # failure confined to them excludes BTCUSDT alone. SOLUSDT and XRPUSDT still run,
        # with BTCUSDT's hours as their market proxy, as a valid run. The minute failures
        # left here are gaps inside hours whose 1h bar still matched its minutes.
        practice = str(ROOT / "config/datasets/practice-2022.toml")
        daily = {"daily_days_compared": 10} | {field: 0 for field in cli.DAILY_INTEGRITY_FIELDS}
        own = {*cli.INTEGRITY_FIELDS, *cli.DAILY_INTEGRITY_FIELDS} - cli.PROXY_HOURLY_FIELDS
        self.assertEqual(
            own,
            {
                "minutes_missing",
                "hours_incomplete",
                "daily_days_missing",
                "daily_days_duplicated",
                "daily_warmup_short",
            },
        )
        cases = [({field: 2}, f"BTCUSDT: {field}=2") for field in sorted(own)]
        cases += [({"daily_days_compared": 0}, "BTCUSDT: no daily bars compared")]
        for number, (fields, reason) in enumerate(cases):
            with self.subTest(fields=fields):
                # A run's directory is stamped to the second, so each case writes to its own
                # output: cases that straddle a second must not leave two results.json here.
                out = Path(self.temp.name) / f"case{number}"
                self.replays.clear()
                self.overrides = {"BTCUSDT": {**daily, **fields}}
                self.assertEqual(0, self.main("verify", "--spec", practice))
                self.assertEqual(0, self.main("run", "--spec", practice, "--out", str(out)))
                self.assertEqual({"SOLUSDT", "XRPUSDT"}, set(self.replays))
                self.assertEqual(8, len(self.replays))  # 2 pairs x 2 paths x gated and ungated
                (written,) = out.rglob("results.json")
                document = json.loads(written.read_text())
                self.assertEqual((True, []), (document["valid"], document["failures"]))
                self.assertEqual({"BTCUSDT": [reason]}, document["excluded_pairs"])
                self.assertNotIn("BTCUSDT", {r["symbol"] for r in document["results"]})

    def test_fee_overrides_reach_every_replay_and_the_results(self):
        self.assertEqual(0, self.main("run"))
        self.assertEqual({(Decimal("0.001"), None)}, set(self.fees))  # spec fee, taker = maker
        self.fees.clear()
        self.assertEqual(0, self.main("run", "--maker-fee", "0", "--taker-fee", "0.0009"))
        self.assertEqual({(Decimal("0"), Decimal("0.0009"))}, set(self.fees))
        (latest,) = Path(self.temp.name).rglob("*-m0-t0.0009/results.json")
        fees = json.loads(latest.read_text())["fees"]
        self.assertEqual({"maker": "0", "taker": "0.0009"}, fees)

    def test_a_fill_trigger_reaches_every_replay_and_is_recorded(self):
        # D9: the missed-fill sweep's trigger. A run without it submits and writes exactly
        # as before; the fixture's fake_run takes no fill_trigger at all.
        self.assertEqual(0, self.main("run"))
        (plain,) = Path(self.temp.name).rglob("results.json")
        self.assertFalse({"fill_trigger", "code_commit"} & set(json.loads(plain.read_text())))
        self.assertNotIn("fill", plain.parent.name)
        triggers = []

        def fake_run(*args, fill_trigger=None):
            triggers.append(fill_trigger)
            return self.fake_run(*args)

        self.replays.clear()
        with patch.object(cli, "run_job", fake_run):
            self.assertEqual(0, self.main("run", "--fill-trigger", "0.0002"))
        self.assertEqual([Decimal("0.0002")] * len(self.replays), triggers)
        self.assertTrue(triggers)
        (swept,) = Path(self.temp.name).rglob("*-m0.001-t0.001-fill0.0002/results.json")
        document = json.loads(swept.read_text())
        self.assertEqual(("0.0002", "0123abc"), (document["fill_trigger"], document["code_commit"]))

    def test_out_of_range_fill_trigger_is_rejected(self):
        for value in ("-0.001", "0.1", "abc"):
            with self.subTest(value=value), self.assertRaises(DataError):
                self.main("run", "--fill-trigger", value)

    def test_integrity_rules_are_versioned_and_strict_mode_reaches_every_check(self):
        self.assertEqual(0, self.main("run"))
        self.assertEqual({False}, set(self.strict))
        self.strict.clear()
        self.assertEqual(0, self.main("run", "--strict-volume", "--maker-fee", "0.0005"))
        self.assertEqual({True}, set(self.strict))
        documents = {
            p.parent.name.split("-m")[-1]: json.loads(p.read_text())
            for p in Path(self.temp.name).rglob("results.json")
        }
        self.assertEqual(
            {"version": "drift-tolerance-v1", "volume_drift_tolerance": "0.001"},
            documents["0.001-t0.001"]["integrity_rules"],
        )
        self.assertEqual(
            {"version": "strict-v0", "volume_drift_tolerance": "0"},
            documents["0.0005-t0.0005"]["integrity_rules"],
        )

    def documents(self):
        return {
            p.parent.name.split("-m0.001-t0.001")[-1]: json.loads(p.read_text())
            for p in Path(self.temp.name).rglob("results.json")
        }

    def test_v0_records_no_policy_and_no_commit_unless_asked(self):
        self.assertEqual(0, self.main("run"))
        self.assertEqual({None}, set(self.policies))
        (v0,) = self.documents().values()
        self.assertEqual(FEATURE_VERSION, v0["feature_version"])
        self.assertFalse({"policy", "code_commit", "code_sha256"} & set(v0))
        # --record-commit adds the commit alone; the run is still V0.
        for written in Path(self.temp.name).rglob("results.json"):
            written.unlink()
        self.assertEqual(0, self.main("run", "--record-commit"))
        self.assertEqual({None}, set(self.policies))
        (recorded,) = self.documents().values()
        self.assertEqual(
            {"code_commit": "0123abc", "code_sha256": jobs.SOURCE_IDENTITY},
            {k: recorded[k] for k in set(recorded) - set(v0)},
        )

    def test_variant_and_structure_flags_reach_every_replay_and_are_recorded(self):
        cap = Decimal("0.40")
        c = {"trend_switch": True, "inventory_cap": cap}
        full = {**c, "flow_block_entry": True, "funding_gate": True, "cycle_gate": True}
        full |= {"structure": True}
        cases = {
            ("--variant-a",): ("-variant-A", SimulationPolicy(trend_switch=True)),
            ("--variant-b",): ("-variant-B", SimulationPolicy(inventory_cap=cap)),
            ("--variant-c",): ("-variant-C", SimulationPolicy(**c)),
            ("--variant-e",): ("-variant-E", SimulationPolicy(volume_exit=True)),
            ("--variant-f",): ("-variant-F", SimulationPolicy(flow_block_entry=True)),
            ("--variant-g",): ("-variant-G", SimulationPolicy(funding_gate=True)),
            ("--variant-h",): ("-variant-H", SimulationPolicy(cycle_gate=True)),
            ("--variant-cg",): ("-variant-C+G", SimulationPolicy(**c, funding_gate=True)),
            ("--variant-ch",): ("-variant-C+H", SimulationPolicy(**c, cycle_gate=True)),
            # The full stack C+F+G+H+V2: its one flag sets every part, structure included.
            ("--variant-full",): ("-variant-C+F+G+H-structure", SimulationPolicy(**full)),
            ("--variant-full", "--structure"): (
                "-variant-C+F+G+H-structure",
                SimulationPolicy(**full),
            ),
            ("--structure",): ("-structure", SimulationPolicy(structure=True)),
            ("--variant-b", "--structure"): (
                "-variant-B-structure",
                SimulationPolicy(inventory_cap=cap, structure=True),
            ),
        }
        for flags, (suffix, policy) in cases.items():
            with self.subTest(flags=flags):
                self.arms.clear()
                for written in Path(self.temp.name).rglob("results.json"):
                    written.unlink()  # two cases share a suffix
                self.assertEqual(0, self.main("run", *flags))
                # Codex review of #160: the ungated rows stay the ungated V0 baseline.
                self.assertEqual({(True, policy), (False, None)}, set(self.arms))
                document = self.documents()[suffix]
                self.assertEqual(
                    json.loads(json.dumps(policy.identity(), default=str)), document["policy"]
                )
                self.assertEqual("0123abc", document["code_commit"])
                structure = policy.structure
                version = STRUCTURE_FEATURE_VERSION if structure else FEATURE_VERSION
                self.assertEqual(version, document["feature_version"])
                # Codex review of #160: the ungated V0 rows' version is stated as well.
                baseline = {"baseline_feature_version": FEATURE_VERSION} if structure else {}
                self.assertEqual(
                    baseline, {k: v for k, v in document.items() if k == "baseline_feature_version"}
                )

    def test_mode_switch_cli_maps_to_policy(self):
        # Spec v2's mode switcher: its flag builds its one policy, F's block and nothing else,
        # for the gated rows, and the ungated rows stay the V0 baseline. It runs on V0's
        # features, and it is not a v1 variant, so it takes no other variant's flag.
        ms = SimulationPolicy(mode_switch=True, flow_block_entry=True)
        self.assertEqual(0, self.main("run", "--mode-switch"))
        self.assertEqual({(True, ms), (False, None)}, set(self.arms))
        document = self.documents()["-variant-MS"]
        self.assertEqual(json.loads(json.dumps(ms.identity(), default=str)), document["policy"])
        self.assertEqual("0123abc", document["code_commit"])
        self.assertEqual(FEATURE_VERSION, document["feature_version"])
        self.assertNotIn("baseline_feature_version", document)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.main("run", "--mode-switch", "--variant-f")
        with self.assertRaisesRegex(ValueError, "F's block and nothing else"):
            self.main("run", "--mode-switch", "--structure")

    def test_the_commit_is_taken_before_any_check_or_replay(self):
        # Codex review of #160: a commit read after the run could name other code.
        seen = []

        def commit():
            seen.append((len(self.verified), len(self.strict), len(self.replays)))
            return "0123abc"

        with patch.object(cli, "code_commit", commit):
            self.assertEqual(0, self.main("run", "--variant-a"))
        # The snapshot comes before everything; the second reading checks it at the end.
        self.assertEqual((0, 0, 0), seen[0])
        self.assertEqual(2, len(seen))

    def test_pool_workers_check_their_sources_and_runs_name_them(self):
        # Codex review of #160: each pool worker compares its sources with the CLI's.
        made = []

        class Capturing(Inline):
            def __init__(self, max_workers, **kwargs):
                made.append(kwargs)

        with patch.object(cli, "ProcessPoolExecutor", Capturing):
            self.assertEqual(0, self.main("run", "--variant-a", "--jobs", "2"))
        self.assertEqual(
            [{"initializer": jobs.check_sources, "initargs": (jobs.SOURCE_IDENTITY,)}], made
        )
        (document,) = self.documents().values()
        self.assertEqual(jobs.SOURCE_IDENTITY, document["code_sha256"])

    def test_a_checkout_changed_during_the_run_makes_it_invalid(self):
        # Codex review of #160: spawned workers may have imported the newer code.
        commits = iter(["0123abc", "4567def"])
        with patch.object(cli, "code_commit", lambda: next(commits)):
            self.assertEqual(2, self.main("run", "--variant-b"))
        (document,) = self.documents().values()
        self.assertFalse(document["valid"])
        self.assertIn(
            "the checkout changed during the run: 0123abc -> 4567def", document["failures"]
        )

    def test_a_trend_benchmark_run_records_its_commit(self):
        # Codex review of #160: variant D is evidence too.
        def fake_trend(spec, config, data_dir, symbol, mode, fees=None):
            return {**good_result(symbol, mode, True), "strategy": "trend benchmark D"}

        with patch.object(cli, "trend_job", fake_trend):
            self.assertEqual(0, self.main("run", "--trend-benchmark"))
        (document,) = self.documents().values()
        self.assertEqual("0123abc", document["code_commit"])
        self.assertNotIn("policy", document)

    def test_only_one_variant_at_a_time(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.main("run", "--variant-a", "--variant-b")

    def test_one_job_runs_every_check_in_this_process(self):
        # run_nopool.py is the CLI with --jobs 1: no pool, and the dataset is verified
        # and cross-checked before any replay, exactly as with a pool.
        with patch.object(cli, "ProcessPoolExecutor", None):
            self.assertEqual(0, self.main("run", "--jobs", "1"))
            self.assertTrue(self.verified)
            self.assertTrue(self.strict)  # the cross-checks ran
            self.assertTrue(self.replays)
            self.checks = {**CLEAN, "hours_missing": 1}
            self.replays.clear()
            self.assertEqual(2, self.main("run", "--jobs", "1"))
            self.assertEqual([], self.replays)

    def test_run_nopool_is_the_cli_run_with_one_job(self):
        spec = ["--spec", "config/datasets/long-bull-bear-2022.toml"]
        self.assertEqual(
            ["run", *spec, "--variant-a", "--structure", "--jobs", "1"],
            run_nopool.cli_args(["long-bull-bear-2022", "--variant-a", "--structure"]),
        )
        default = ["run", "--spec", "config/datasets/long-recovery-2023-2024.toml"]
        self.assertEqual([*default, "--jobs", "1"], run_nopool.cli_args([]))
        self.assertEqual(
            [*default, "--variant-b", "--jobs", "1"], run_nopool.cli_args(["--variant-b"])
        )

    def test_out_of_range_fee_override_is_rejected(self):
        for value in ("-0.001", "0.1", "abc", ""):
            with self.subTest(value=value), self.assertRaises(DataError):
                self.main("run", "--maker-fee", value)

    def test_each_chronology_failure_fails_and_prevents_replay(self):
        failing = {field: 1 for field in cli.INTEGRITY_FIELDS} | {"hours_compared": 0}
        for field, value in failing.items():
            with self.subTest(field=field):
                self.checks = {**CLEAN, field: value}
                self.replays.clear()
                self.assertEqual(2, self.main("verify"))
                self.assertEqual(2, self.main("run"))
                self.assertEqual([], self.replays)  # replay never invoked

    def test_invalid_replay_results_fail_but_are_kept_for_diagnosis(self):
        for patch_value in (
            {"accounting_problems": ["cash identity failed"]},
            {"transient_pauses": 3},
            {"bars": 0},
        ):
            with self.subTest(patch=patch_value):
                self.result_patch = patch_value
                self.assertEqual(2, self.main("run"))
        written = sorted(Path(self.temp.name).rglob("results.json"))
        self.assertTrue(written)
        document = json.loads(written[-1].read_text())
        self.assertFalse(document["valid"])
        self.assertTrue(document["failures"])


PROXY_CLEAN = {"role": "market_proxy", "series_hours_present": 10, "series_hours_excluded": 0}
PROXY_CLEAN |= {field: 0 for field in cli.SERIES_INTEGRITY_FIELDS}


class MarketProxyCheckTests(CliIntegrityTests):
    """A market proxy that is not traded is still cross-checked (Codex, PR #16)."""

    def setUp(self):
        super().setUp()
        spec = (
            Path(SPEC).read_text().replace('market_proxy = "BTCUSDT"', 'market_proxy = "ETHUSDT"')
        )
        self.spec = Path(self.temp.name) / "proxy.toml"
        self.spec.write_text(spec)
        self.proxy_checks = dict(PROXY_CLEAN)
        self.checked = []

    def fake_check(
        self,
        spec,
        data_dir,
        symbol,
        strict_volume=False,
        *,
        mask=NOT_PASSED,
        config_path=NOT_PASSED,
    ):
        self.checked.append(symbol)
        if symbol == "ETHUSDT":
            self.events.append(("check", symbol, mask))
            self.configs.append(config_path)
            return {"symbol": symbol, **self.proxy_checks}
        return super().fake_check(
            spec, data_dir, symbol, strict_volume, mask=mask, config_path=config_path
        )

    def test_a_run_whose_every_pair_is_excluded_replays_nothing(self):
        # Each traded pair's own check fails while the untraded proxy passes: no pair is
        # left to replay, so the run fails as before, with every failure reported.
        self.overrides = {pair: {"hours_missing": 1} for pair in ("ADAUSDT", "BTCUSDT")}
        self.assertEqual(2, self.main("verify"))
        self.assertEqual(2, self.main("run"))
        self.assertEqual([], self.replays)
        # One of them alone is excluded, and the other pair runs.
        self.overrides = {"ADAUSDT": {"hours_missing": 1}}
        self.assertEqual(0, self.main("run"))
        self.assertEqual({"BTCUSDT"}, set(self.replays))

    def test_untraded_proxy_is_checked_but_not_replayed(self):
        self.assertEqual(0, self.main("run"))
        self.assertEqual(
            [
                "ADAUSDT",
                "BTCUSDT",
                "ETHUSDT",
                "BNBUSDT",
                "SOLUSDT",
                "XRPUSDT",
                "DOGEUSDT",
                "LTCUSDT",
                "LINKUSDT",
                "TRXUSDT",
            ],
            self.checked,
        )
        self.assertNotIn("ETHUSDT", self.replays)

    def test_a_broken_proxy_archive_fails_and_prevents_replay(self):
        failing = {field: 1 for field in cli.SERIES_INTEGRITY_FIELDS}
        for field, value in (failing | {"series_hours_present": 0}).items():
            with self.subTest(field=field):
                self.proxy_checks = {**PROXY_CLEAN, field: value}
                self.replays.clear()
                self.assertEqual(2, self.main("verify"))
                self.assertEqual(2, self.main("run"))
                self.assertEqual([], self.replays)

    def test_traded_proxy_and_basket_members_are_checked_once(self):
        self.spec.write_text(Path(SPEC).read_text())
        self.assertEqual(0, self.main("verify"))
        self.assertEqual(
            [
                "ADAUSDT",
                "BTCUSDT",
                "ETHUSDT",
                "BNBUSDT",
                "SOLUSDT",
                "XRPUSDT",
                "DOGEUSDT",
                "LTCUSDT",
                "LINKUSDT",
                "TRXUSDT",
            ],
            self.checked,
        )


class BasketCheckTests(MarketProxyCheckTests):
    """Breadth-basket inputs are validated; only documented absences are exempt."""

    def fake_check(
        self,
        spec,
        data_dir,
        symbol,
        strict_volume=False,
        *,
        mask=NOT_PASSED,
        config_path=NOT_PASSED,
    ):
        if symbol == "DOGEUSDT":
            self.checked.append(symbol)
            self.events.append(("check", symbol, mask))
            self.configs.append(config_path)
            return {"symbol": symbol, **self.basket_check}
        return super().fake_check(
            spec, data_dir, symbol, strict_volume, mask=mask, config_path=config_path
        )

    def setUp(self):
        super().setUp()
        self.basket_check = {**PROXY_CLEAN, "role": "breadth_basket", "series_hours_excluded": 0}

    def test_an_unexplained_basket_gap_fails_and_prevents_replay(self):
        for field in cli.SERIES_INTEGRITY_FIELDS:
            with self.subTest(field=field):
                self.basket_check[field] = 1
                self.replays.clear()
                self.assertEqual(2, self.main("verify"))
                self.assertEqual(2, self.main("run"))
                self.assertEqual([], self.replays)
                self.basket_check[field] = 0

    def test_a_basket_member_documented_absent_for_the_whole_window_passes(self):
        self.basket_check |= {"series_hours_present": 0, "series_hours_excluded": 24}
        self.assertEqual(0, self.main("verify"))


def month_row(month, expected, masked=0, share="0", excluded=False):
    return {
        "month": month,
        "expected_hours": expected,
        "masked_hours": masked,
        "open_only_hours": 0,
        "real_defect_share": share,
        "excluded": excluded,
    }


class MaskReportTests(unittest.TestCase):
    def test_mask_report_prints_shares_without_replaying(self):
        # mask-report prints the masks of a synthetic window as mask_job computes them, with
        # no check and no replay: the masked-checks tests' DOGEUSDT window. Its traded pairs
        # have minutes for March's first eight hours only, which do not match their hours,
        # so every March hour is masked and the 17% rule excludes the month. BNBUSDT and
        # DOGEUSDT read with nothing masked, so their masks are None, and DOGEUSDT 2020-02,
        # wholly inside its documented absence, has no expected hour and no share.
        with tempfile.TemporaryDirectory() as temp:
            spec, data = masked_checks.build_run(Path(temp)), Path(temp) / "data"
            argv = ["mask-report", "--spec", str(spec), "--data-dir", str(data), "--jobs", "1"]
            out = io.StringIO()
            with (
                patch.object(cli, "cross_check_job", None),  # never reached
                patch.object(cli, "run_job", None),
                patch.object(cli, "trend_job", None),
                contextlib.redirect_stdout(out),
            ):
                self.assertEqual(0, cli.main(argv))
            report = json.loads(out.getvalue())
            # The dataset is verified first, as for verify and run.
            local_path(data, "BNBUSDT", "1h", "2020-01").write_bytes(b"tampered")
            with (
                self.assertRaisesRegex(DataError, "checksum"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                cli.main(argv)
        march = [
            {
                "from": "2020-03-01T00:00Z",
                "to": "2020-03-01T08:00Z",
                "reason": "mismatch on open+high+low+close+volume",
            },
            {"from": "2020-03-01T08:00Z", "to": "2020-04-01T00:00Z", "reason": "no minute bars"},
        ]
        traded = {
            "mask_is_none": False,
            "repaired_hours": 0,
            "dropped_hours": 0,
            "masked_hours": 744,
            "months": [
                month_row("2020-01", 744),
                month_row("2020-02", 696),
                month_row("2020-03", 744, 744, "1", True),
            ],
        }
        untraded = {
            "mask_is_none": True,
            "repaired_hours": 0,
            "dropped_hours": 0,
            "masked_hours": 0,
            "months": [
                month_row("2020-01", 744),
                month_row("2020-02", 696),
                month_row("2020-03", 744),
            ],
        }
        doge = {**untraded, "months": [*untraded["months"]]}
        doge["months"][1] = month_row("2020-02", 0, share=None)
        self.assertEqual(
            {
                "dataset": "doge-window",
                "xrp_quote_test": None,  # XRPUSDT is not traded here
                "comparison_mask": {
                    "BTCUSDT": {"masked": march, "excluded_months": ["2020-03"]},
                    "ETHUSDT": {"masked": march, "excluded_months": ["2020-03"]},
                },
                "symbols": {
                    "BTCUSDT": traded,
                    "ETHUSDT": traded,
                    "BNBUSDT": untraded,
                    "DOGEUSDT": doge,
                },
                "totals": {
                    "symbols_with_a_mask": 2,
                    "repaired_hours": 0,
                    "dropped_hours": 0,
                    "masked_hours": 1488,
                    "excluded_months": 2,
                },
            },
            report,
        )


MASKED_RUN_SPEC = (
    """name = "masked-run"
purpose = "masked CLI run test"
traded = ["BTCUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["BTCUSDT"]
daily_warmup_start = "2019-06"
warmup_start = "2020-01"
start = "2020-03"
end = "2020-03"
"""
    + masked_checks.COMMON
)
MAR_2020, APR_2020 = masked_checks.MAR_2020, masked_checks.APR_2020
RUN_MINUTE_MS, DAY_MS = masked_checks.MINUTE_MS, masked_checks.DAY_MS
# A row's mask report (spec v1 section 5 rules 1, 3 and 4), each field written when non-zero.
MASK_ROW_FIELDS = {"masked_hours", "days_skipped_for_masks", "fills_after_masked_span"}
# The evaluation hour whose minutes the masked-run window leaves out: 2020-03-01T03:00Z.
MASKED_RUN_HOUR = MAR_2020 + 3 * HOUR_MS
# Its replayed span: March's first eight hours, less the masked one.
MASKED_RUN_SPAN = 8


def build_masked_run(work):
    """A one-pair window whose replay spans one masked evaluation hour, under ``work``;
    returns the spec's path.

    BTCUSDT's hourly warm-up (2020-01 and 2020-02) is the masked-checks tests' daily sine,
    and its daily history from 2019-06 is long enough for P3. In March, as in those tests'
    DOGEUSDT window, its first eight hours of minutes oscillate around the fair value, so
    the ungated grid fills, and here their 1h bars aggregate them. The 03:00 hour has no
    minutes, so it is masked (rule 2).

    Every later March hour has its 60 minutes and a 1h bar whose open alone differs from
    them: an open-only hour, which is masked but not counted by the 17% rule. So the month
    is kept, and the replay is the eight hours less the masked one, not a whole month of
    minutes, which would take minutes of replay per run."""
    sine = masked_checks.sine_bar
    hourly = [k for k in masked_checks.sine_hours() if k.open_ms < MAR_2020]
    features = FeatureEngine(
        SeriesFeatures("BTCUSDT", hourly),
        SeriesFeatures("BTCUSDT", hourly),
        [SeriesFeatures(f"B{i}USDT", hourly, full=False) for i in range(5)],
        range_atr_multiple=2.0,
        levels=8,
        minimum_cost_multiple=3.0,
        round_trip_cost=0.0035,
    )
    fair = float(features.at(MAR_2020).fair_value)
    minutes = []
    for i in range(MASKED_RUN_SPAN * 60):
        mid = fair * (1 + 0.03 * math.sin(2 * math.pi * i / 90))
        minutes.append(sine(MAR_2020 + i * RUN_MINUTE_MS, mid, mid * 1.003, mid * 0.997, mid))
    hourly += aggregate(minutes)
    for hour in range(MAR_2020 + MASKED_RUN_SPAN * HOUR_MS, APR_2020, HOUR_MS):
        quiet = [
            sine(hour + i * RUN_MINUTE_MS, fair, fair * 1.001, fair * 0.999, fair)
            for i in range(60)
        ]
        minutes += quiet
        (official,) = aggregate(quiet)
        hourly.append(replace(official, open=Decimal(str(round(fair * 1.0005, 6)))))
    first_day = masked_checks.ms(2019, 6)
    days = [sine(first_day + i * DAY_MS, 1.0, 1.01, 0.99, 1.0) for i in range(214)]
    days += aggregate(hourly, DAY_MS)  # 2019-06-01 to 2019-12-31, then the hourly window's
    archive = masked_checks.loaders.FakeArchive()
    kept = [k for k in minutes if k.open_ms // HOUR_MS * HOUR_MS != MASKED_RUN_HOUR]
    masked_checks.add_bars(archive, "BTCUSDT", "1m", RUN_MINUTE_MS, kept)
    masked_checks.add_bars(archive, "BTCUSDT", "1h", HOUR_MS, hourly)
    masked_checks.add_bars(archive, "BTCUSDT", "1d", DAY_MS, days)
    spec_path = work / "masked-run.toml"
    spec_path.write_text(MASKED_RUN_SPEC)
    manifest = fetch_dataset(
        load_spec(spec_path),
        work / "data",
        fetcher=archive,
        instruments=lambda symbol: masked_checks.RUN_FILTERS,
    )
    write_manifest(work / "masked-run.manifest.json", manifest)
    return spec_path


class MaskedRunTests(unittest.TestCase):
    def test_a_masked_run_writes_its_mask_and_the_scorer_reads_it(self):
        # One CLI run with the real jobs, nothing faked (Task 5's review): the masked hour
        # and the open-only hours reach results.json's comparison mask, the cross-check runs
        # on the post-mask expected set, each row reports its masked hours, skipped days and
        # (the ungated grid's, which rests orders across the span) fills after the span,
        # and the acceptance scorer reads the document as an acceptance run.
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            spec_path = build_masked_run(work)
            argv = ["run", "--spec", str(spec_path), "--data-dir", str(work / "data")]
            argv += ["--config", str(ROOT / "config/default.toml"), "--out", str(work / "out")]
            argv += ["--jobs", "1"]
            argv += ["--maker-fee", "0", "--taker-fee", "0.0009"]  # section 4's primaries
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, cli.main(argv))
            (written,) = (work / "out").rglob("results.json")
            document = score.read_results(written).document
            spec = load_spec(spec_path)
        self.assertEqual(
            {
                "BTCUSDT": {
                    "masked": [
                        {
                            "from": "2020-03-01T03:00Z",
                            "to": "2020-03-01T04:00Z",
                            "reason": "no minute bars",
                        },
                        {
                            "from": "2020-03-01T08:00Z",
                            "to": "2020-04-01T00:00Z",
                            "reason": "open-only difference",
                        },
                    ],
                    "excluded_months": [],
                }
            },
            document["comparison_mask"],
        )
        (check,) = document["hourly_cross_checks"]
        self.assertEqual(MASKED_RUN_SPAN - 1, check["hours_compared"])
        self.assertEqual(31, check["daily_days_skipped_for_masks"])  # every March day
        masked = 744 - (MASKED_RUN_SPAN - 1)
        for row in document["results"]:
            with self.subTest(row=(row["path_mode"], row["strategy"])):
                fills = {} if score.variant_of(row) else {"fills_after_masked_span": 1}
                self.assertEqual(
                    {"masked_hours": masked, "days_skipped_for_masks": 31, **fills},
                    {k: row[k] for k in row.keys() & MASK_ROW_FIELDS},
                )
                self.assertEqual((MASKED_RUN_SPAN - 1) * 60, row["bars"])  # no masked minute
        self.assertEqual((True, []), (document["valid"], document["failures"]))
        self.assertEqual([], score.document_problems(document))
        window = score.window_of(spec, document["hourly_cross_checks"])
        self.assertEqual((("BTCUSDT",), {}), (window.included, dict(window.excluded)))
        self.assertEqual(
            [("V0", path, (), "") for path in ("high_first", "low_first")],
            sorted(
                (variant, run.path, run.problems, run.baseline_problem)
                for variant, run in score.runs_of(document, window)
            ),
        )


CLEAN_FIELDS = dict.fromkeys(cli.INTEGRITY_FIELDS, 0)


class QuoteIntegrityTests(unittest.TestCase):
    def test_stage_1_checks_still_need_every_existing_field(self):
        # tick_limit_quotes is read with a default, since only a breach writes it; every
        # other integrity field keeps its direct lookup, so a stage-1 record that lacks one
        # still raises, as before.
        pair = {"symbol": "XRPUSDT", "hours_compared": 10, **CLEAN_FIELDS}
        self.assertEqual([], cli.integrity_failures([pair]))
        for field in (*cli.INTEGRITY_FIELDS, "hours_compared"):
            with self.subTest(field=field), self.assertRaises(KeyError):
                cli.integrity_failures([{k: v for k, v in pair.items() if k != field}])
        daily = {"daily_days_compared": 10, **dict.fromkeys(cli.DAILY_INTEGRITY_FIELDS, 0)}
        self.assertEqual([], cli.integrity_failures([pair | daily]))
        for field in cli.DAILY_INTEGRITY_FIELDS:
            with self.subTest(field=field), self.assertRaises(KeyError):
                cli.integrity_failures([pair | {k: v for k, v in daily.items() if k != field}])
        series = {"symbol": "ETHUSDT", **PROXY_CLEAN, "role": "breadth_basket"}
        for field in cli.SERIES_INTEGRITY_FIELDS:
            with self.subTest(field=field), self.assertRaises(KeyError):
                cli.integrity_failures([{k: v for k, v in series.items() if k != field}])
        # The new field is read on a traded pair's check, and a zero is no failure.
        self.assertEqual(("tick_limit_quotes",), cli.QUOTE_INTEGRITY_FIELDS)
        self.assertEqual([], cli.integrity_failures([{**pair, "tick_limit_quotes": 0}]))
        self.assertEqual(
            ["XRPUSDT: tick_limit_quotes=3"],
            cli.integrity_failures([{**pair, "tick_limit_quotes": 3}]),
        )

    def test_a_quote_breach_is_the_xrp_pairs_own_failure(self):
        # XRP is traded and is not the market proxy, so scoped_failures makes the record
        # its own, and no other pair's, with no code beyond the field's name.
        spec = jobs.load_spec(ROOT / "config/datasets/practice-2022.toml")
        daily = {"daily_days_compared": 10} | dict.fromkeys(cli.DAILY_INTEGRITY_FIELDS, 0)
        checks = []
        for symbol in cli.checked_symbols(spec):
            if symbol in spec.traded:
                checks.append({"symbol": symbol, "hours_compared": 10, **CLEAN_FIELDS, **daily})
            else:
                checks.append({"symbol": symbol, **PROXY_CLEAN, "role": "breadth_basket"})
        self.assertEqual(([], {}), cli.scoped_failures(spec, checks))
        next(c for c in checks if c["symbol"] == "XRPUSDT")["tick_limit_quotes"] = 4
        self.assertEqual(
            ([], {"XRPUSDT": ["XRPUSDT: tick_limit_quotes=4"]}), cli.scoped_failures(spec, checks)
        )


class DocumentedDailyDefectIntegrityTests(unittest.TestCase):
    """Owner decision 14 (2026-10-07): a day the daily check skips as a documented defect
    is a count, not a failure, and the mismatched days a record names fail only through
    their count."""

    def test_a_documented_skip_is_no_failure(self):
        pair = {"symbol": "BTCUSDT", "hours_compared": 10, **CLEAN_FIELDS}
        daily = {"daily_days_compared": 10, **dict.fromkeys(cli.DAILY_INTEGRITY_FIELDS, 0)}
        for field in ("daily_days_skipped_documented", "daily_mismatched_days"):
            self.assertNotIn(field, cli.DAILY_INTEGRITY_FIELDS)
            self.assertNotIn(field, cli.PROXY_HOURLY_FIELDS)
        skipped = pair | daily | {"daily_days_skipped_documented": 1}
        self.assertEqual([], cli.integrity_failures([skipped]))
        mismatched = skipped | {"daily_days_mismatched": 1, "daily_mismatched_days": ["2021-01-22"]}
        self.assertEqual(["BTCUSDT: daily_days_mismatched=1"], cli.integrity_failures([mismatched]))
        # On a window's checks, the skip excludes nothing, as a masked day's does not.
        spec = jobs.load_spec(ROOT / "config/datasets/practice-2022.toml")
        checks = []
        for symbol in cli.checked_symbols(spec):
            if symbol in spec.traded:
                checks.append(skipped | {"symbol": symbol})
            else:
                checks.append({"symbol": symbol, **PROXY_CLEAN, "role": "breadth_basket"})
        self.assertEqual(([], {}), cli.scoped_failures(spec, checks))


XRP_WINDOW = """name = "xrp-window"
purpose = "synthetic: rule 8's statistic through cross_check_job"
traded = ["BTCUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["BTCUSDT", "XRPUSDT"]
warmup_start = "2024-01"
start = "2024-02"
end = "2024-02"
initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""
XRP_NOT_TRADED = XRP_WINDOW.replace('traded = ["BTCUSDT", "XRPUSDT"]', 'traded = ["BTCUSDT"]')
MINUTE_MS = 60_000
FEB_1, FEB_END = month_bounds_ms("2024-02")
CONFIG = ROOT / "config/default.toml"


def flat_minutes(first_ms, count, price="1"):
    """``count`` minutes from ``first_ms``, each open, high, low and close at ``price``."""
    p = Decimal(price)
    return [
        Kline(first_ms + i * MINUTE_MS, p, p, p, p, Decimal(10), 10 * p, Decimal(4))
        for i in range(count)
    ]


class XrpQuoteJobTests(unittest.TestCase):
    """Spec v1 section 5 rule 8 through ``cross_check_job`` and ``quote_test_job``, on
    synthetic minutes: ``load_minutes`` returns one-shot iterators, as the real one does,
    and counts its calls."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.spec = Path(self.temp.name) / "xrp-window.toml"
        self.spec.write_text(XRP_WINDOW)
        self.calls = []
        # Three evaluation hours at 1.0 and the last hour before them, which is warm-up and
        # never replayed; no quote of them is wide.
        self.warm_up = FEB_1 - HOUR_MS
        self.minutes = flat_minutes(self.warm_up, 60) + flat_minutes(FEB_1, 180)
        manifest = {"instruments": {s: {"tick_size": "0.0001"} for s in ("BTCUSDT", "XRPUSDT")}}
        for item in (
            patch.object(jobs, "load_manifest", lambda path: manifest),
            patch.object(jobs, "load_minutes", self.load_minutes),
            patch.object(jobs, "load_hourly", self.load_hourly),
        ):
            item.start()
            self.addCleanup(item.stop)

    def kept(self, mask):
        return [
            k for k in self.minutes if mask is None or k.open_ms // HOUR_MS * HOUR_MS not in mask
        ]

    def load_minutes(self, data_dir, manifest, symbol, *, mask=None, excluded=()):
        self.calls.append((symbol, mask, list(excluded)))
        return iter(self.kept(mask))  # one pass only

    def load_hourly(self, data_dir, manifest, symbol, *, mask=None, excluded=()):
        return list(aggregate(self.kept(mask)))

    def widen(self, minute, price="0.1"):
        """Replace the minute of ``self.minutes`` that opens at ``minute`` by a flat bar at a
        price whose open and close quotes are wide: at 0.1 with a 0.0001 tick they are
        0.0999 / 0.1001, 0.1998%."""
        index = next(i for i, k in enumerate(self.minutes) if k.open_ms == minute)
        self.minutes[index] = flat_minutes(minute, 1, price)[0]

    def check(self, symbol="XRPUSDT", **keywords):
        return jobs.cross_check_job(self.spec, Path("data"), symbol, config_path=CONFIG, **keywords)

    def hourly_counts(self, mask=None):
        """What the cross-check alone gives, from fresh iterators."""
        window = jobs.evaluation_bounds_ms(jobs.load_spec(self.spec))
        hourly = list(aggregate(self.kept(mask)))
        return cross_check_hourly(iter(self.kept(mask)), hourly, window, masked=mask or frozenset())

    def test_one_wide_quote_excludes_xrp_and_a_pass_writes_nothing(self):
        # A pass: no key. The cross-check reads the minutes, and the statistic reads them
        # again in a second call, since the first exhausted its iterator.
        passed = self.check()
        self.assertEqual({"symbol": "XRPUSDT", **self.hourly_counts()}, passed)
        self.assertEqual(4, passed["hours_compared"])
        self.assertEqual(["XRPUSDT", "XRPUSDT"], [call[0] for call in self.calls])
        # One wide minute in the evaluation months: its open and close quotes breach, so the
        # record counts two, and everything the cross-check counts is as it was. A wide
        # minute in the warm-up hour is not replayed and counts nothing.
        self.widen(FEB_1 + 90 * MINUTE_MS)
        self.widen(self.warm_up + 5 * MINUTE_MS)
        self.calls.clear()
        breached = self.check()
        self.assertEqual(2, breached.pop("tick_limit_quotes"))
        self.assertEqual({"symbol": "XRPUSDT", **self.hourly_counts()}, breached)
        self.assertEqual(2, len(self.calls))
        # The window is [start, end): the last minute of the month is in it, the next out.
        self.minutes = flat_minutes(self.warm_up, 60) + flat_minutes(FEB_1, 180)
        self.minutes += flat_minutes(FEB_END - MINUTE_MS, 1, "0.1")
        self.assertEqual(2, self.check()["tick_limit_quotes"])
        self.minutes[-1] = flat_minutes(FEB_END, 1, "0.1")[0]
        self.assertNotIn("tick_limit_quotes", self.check())

    def test_the_statistic_is_taken_on_the_minutes_the_mask_leaves(self):
        # Month by month, like the masks: a wide quote inside a masked hour is not replayed.
        # Both passes read the pair's mask, and its documented absences.
        wide = FEB_1 + 90 * MINUTE_MS
        self.widen(wide)
        mask = frozenset({wide // HOUR_MS * HOUR_MS})
        record = self.check(mask=mask)
        self.assertEqual({"symbol": "XRPUSDT", **self.hourly_counts(mask)}, record)
        self.assertEqual([("XRPUSDT", mask, [])] * 2, self.calls)
        self.calls.clear()
        self.assertEqual(2, self.check(mask=frozenset())["tick_limit_quotes"])
        self.assertEqual([("XRPUSDT", frozenset(), [])] * 2, self.calls)

    def test_it_is_computed_for_xrp_only_and_only_where_xrp_is_traded(self):
        # BTCUSDT's minutes are read once, whatever they hold; with XRP a basket member only
        # (as in verify-2024h1) none of XRP's minutes is read at all.
        self.widen(FEB_1 + 90 * MINUTE_MS)
        self.assertNotIn("tick_limit_quotes", self.check("BTCUSDT"))
        self.assertEqual(["BTCUSDT"], [call[0] for call in self.calls])
        self.spec.write_text(XRP_NOT_TRADED)
        self.calls.clear()
        record = self.check("XRPUSDT")
        self.assertEqual(("breadth_basket", []), (record["role"], self.calls))
        self.assertNotIn("tick_limit_quotes", record)

    def test_xrp_needs_the_config_and_a_call_without_it_still_works_for_others(self):
        # Without maximum_spread_pct the test cannot run, and a pass would be a guess.
        with self.assertRaises(ValueError):
            jobs.cross_check_job(self.spec, Path("data"), "XRPUSDT")
        alone = jobs.cross_check_job(self.spec, Path("data"), "BTCUSDT")
        self.assertEqual({"symbol": "BTCUSDT", **self.hourly_counts()}, alone)

    def test_the_statistic_job_gives_what_mask_report_prints(self):
        # One pass: the widest spread in percent, the count above the limit, the limit and
        # whether it breaches, on the minutes of the evaluation months after masking.
        self.widen(FEB_1 + 90 * MINUTE_MS)
        self.widen(self.warm_up + 5 * MINUTE_MS)
        breach = {
            "maximum_spread_pct": "0.15",
            "widest_spread_pct": str(Decimal("0.0002") / Decimal("0.1001") * 100),
            "tick_limit_quotes": 2,
            "breaches": True,
        }
        self.assertEqual(breach, jobs.quote_test_job(self.spec, Path("data"), CONFIG, None))
        self.assertEqual([("XRPUSDT", None, [])], self.calls)
        masked = jobs.quote_test_job(self.spec, Path("data"), CONFIG, frozenset({FEB_1 + HOUR_MS}))
        calm = Decimal("0.0006") / Decimal("1.0003") * 100  # 1.0: bid 0.9997, ask 1.0003
        self.assertEqual(
            {
                **breach,
                "widest_spread_pct": str(calm),
                "tick_limit_quotes": 0,
                "breaches": False,
            },
            masked,
        )
        self.spec.write_text(XRP_NOT_TRADED)
        self.calls.clear()
        self.assertIsNone(jobs.quote_test_job(self.spec, Path("data"), CONFIG, None))
        self.assertEqual([], self.calls)


XRP_ARCHIVES = (
    """name = "xrp-archives"
purpose = "rule 8 through the real readers"
traded = ["BTCUSDT", "XRPUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["BTCUSDT", "XRPUSDT"]
warmup_start = "2023-01"
start = "2023-02"
end = "2023-02"
"""
    + masked_checks.COMMON
)
XRP_FILTERS = {
    "BTCUSDT": {"base": "BTC", "quote": "USDT", "tick_size": "0.01"},
    "XRPUSDT": {"base": "XRP", "quote": "USDT", "tick_size": "0.0001"},
}
for _filters in XRP_FILTERS.values():
    _filters |= {"quantity_step": "0.0001", "min_notional": "5"}


def build_xrp_archives(work, wide_minute=None):
    """The spec, manifest and archives of a window that trades BTCUSDT (flat at 100) and
    XRPUSDT (flat at 1.0) through February 2023, under ``work``; returns the spec's path.
    ``wide_minute`` makes that minute of February XRPUSDT's flat 0.1, whose open and close
    quotes are wide. Every hour is the aggregate of its minutes, so every check passes."""
    jan, feb, mar = (month_bounds_ms(m)[0] for m in ("2023-01", "2023-02", "2023-03"))
    archive = masked_checks.loaders.FakeArchive()
    for symbol, price in (("BTCUSDT", "100"), ("XRPUSDT", "1")):
        minutes = flat_minutes(feb, (mar - feb) // MINUTE_MS, price)
        if symbol == "XRPUSDT" and wide_minute is not None:
            minutes[wide_minute] = flat_minutes(feb + wide_minute * MINUTE_MS, 1, "0.1")[0]
        warm_up = flat_minutes(jan, (feb - jan) // MINUTE_MS, price)
        hourly = [*aggregate(warm_up), *aggregate(minutes)]
        masked_checks.add_bars(archive, symbol, "1m", MINUTE_MS, minutes)
        masked_checks.add_bars(archive, symbol, "1h", HOUR_MS, hourly)
    Path(work).mkdir(parents=True, exist_ok=True)
    spec_path = Path(work) / "xrp-archives.toml"
    spec_path.write_text(XRP_ARCHIVES)
    manifest = fetch_dataset(
        load_spec(spec_path),
        Path(work) / "data",
        fetcher=archive,
        instruments=lambda symbol: XRP_FILTERS[symbol],
    )
    write_manifest(Path(work) / "xrp-archives.manifest.json", manifest)
    return spec_path


class XrpArchivesTests(unittest.TestCase):
    """Rule 8 end to end on synthetic archives: the real readers, masks, checks and CLI, with
    no fake job. One window passes; in the other XRPUSDT has one flat minute at 0.1, in the
    middle of February."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.passing = build_xrp_archives(Path(cls.temp.name, "pass"))
        cls.breaching = build_xrp_archives(Path(cls.temp.name, "breach"), wide_minute=20_000)

    def invoke(self, command, spec, *extra):
        data = spec.parent / "data"
        argv = [command, "--spec", str(spec), "--data-dir", str(data), "--config", str(CONFIG)]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([*argv, "--jobs", "1", *extra])
        # verify and mask-report each print one JSON document, and nothing else.
        return code, json.loads(out.getvalue())

    def test_verify_excludes_xrp_for_a_breach_and_writes_nothing_for_a_pass(self):
        def checks(report):
            return {c["symbol"]: c for c in report["checks"]}

        code, report = self.invoke("verify", self.passing)
        self.assertEqual((0, "valid"), (code, report["status"]))
        self.assertFalse({"excluded_pairs", "comparison_mask"} & set(report))
        self.assertFalse(any("tick_limit_quotes" in c for c in report["checks"]))
        passed = checks(report)["XRPUSDT"]
        self.assertEqual(672, passed["hours_compared"])  # 28 days
        code, report = self.invoke("verify", self.breaching)
        self.assertEqual((0, "valid"), (code, report["status"]))
        self.assertEqual({"XRPUSDT": ["XRPUSDT: tick_limit_quotes=2"]}, report["excluded_pairs"])
        breach = {"masked": [], "excluded_months": [], "tick_limit_quotes": 2}
        self.assertEqual({"XRPUSDT": breach}, report["comparison_mask"])
        # The record carries the count and everything else the cross-check counts, as for a
        # pass; no other symbol's does.
        found = checks(report)
        self.assertEqual(2, found["XRPUSDT"].pop("tick_limit_quotes"))
        self.assertEqual(passed, found["XRPUSDT"])
        self.assertNotIn("tick_limit_quotes", found["BTCUSDT"])

    def test_mask_report_prints_the_same_statistic(self):
        calm = Decimal("0.0006") / Decimal("1.0003") * 100  # 1.0: bid 0.9997, ask 1.0003
        wide = Decimal("0.0002") / Decimal("0.1001") * 100  # 0.1: bid 0.0999, ask 0.1001
        for spec, widest, quotes in ((self.passing, calm, 0), (self.breaching, wide, 2)):
            with self.subTest(quotes=quotes):
                code, report = self.invoke("mask-report", spec)
                self.assertEqual(0, code)
                self.assertEqual(
                    {
                        "maximum_spread_pct": "0.15",
                        "widest_spread_pct": str(widest),
                        "tick_limit_quotes": quotes,
                        "breaches": bool(quotes),
                    },
                    report["xrp_quote_test"],
                )
                self.assertEqual(bool(quotes), "XRPUSDT" in report["comparison_mask"])
                self.assertTrue(report["symbols"]["XRPUSDT"]["mask_is_none"])


class HourlySeriesTests(unittest.TestCase):
    def test_missing_and_duplicated_series_hours_are_counted(self):
        from test_backtest_replay import HOUR_MS, START_MS, candle

        from crypto_grid_bot.backtest.replay import check_hourly_series

        hours = [candle(START_MS + i * HOUR_MS, 1, 1, 1, 1) for i in (0, 1, 1, 3)]
        outside = candle(START_MS + 9 * HOUR_MS, 1, 1, 1, 1)
        result = check_hourly_series([*hours, outside], (START_MS, START_MS + 4 * HOUR_MS))
        self.assertEqual(
            {
                "series_hours_present": 3,
                "series_hours_missing": 1,
                "series_hours_duplicated": 1,
                "series_hours_excluded": 0,
            },
            result,
        )

    def test_documented_hours_are_excluded_but_other_gaps_still_count(self):
        from test_backtest_replay import HOUR_MS, START_MS, candle

        from crypto_grid_bot.backtest.replay import check_hourly_series

        window = (START_MS, START_MS + 6 * HOUR_MS)
        hours = [candle(START_MS + i * HOUR_MS, 1, 1, 1, 1) for i in (2, 3, 5)]
        listing = [(START_MS, START_MS + 2 * HOUR_MS)]  # absent before listing
        result = check_hourly_series(hours, window, listing)
        self.assertEqual((2, 1), (result["series_hours_excluded"], result["series_hours_missing"]))


class CompletenessTests(unittest.TestCase):
    def test_incomplete_hours_and_hours_absent_everywhere_are_counted(self):
        from test_backtest_replay import HOUR_MS, START_MS, candle

        from crypto_grid_bot.backtest.klines import aggregate
        from crypto_grid_bot.backtest.replay import cross_check_hourly

        # Hour 0 has 59 flat minutes (one zero-volume minute missing); the exact OHLCV
        # aggregate still matches. Hour 1 exists nowhere.
        minutes = [candle(START_MS + i * 60_000, 1, 1, 1, 1) for i in range(59)]
        official = list(aggregate(minutes))
        result = cross_check_hourly(minutes, official, (START_MS, START_MS + 2 * HOUR_MS))
        self.assertEqual(0, result["hours_mismatched"])
        self.assertEqual(1, result["hours_incomplete"])
        self.assertEqual(1, result["minutes_missing"])
        self.assertEqual(1, result["hours_absent_from_both"])


class CodeCommitTests(unittest.TestCase):
    """Codex review of #160: uncommitted edits to tracked files are recorded."""

    def commit_with(self, porcelain: str, committed: dict | None = jobs.SOURCE_FILES) -> str:
        def fake_run(args, **kwargs):
            out = "0123abc\n" if "rev-parse" in args else porcelain
            return subprocess.CompletedProcess(args, 0, stdout=out, stderr="")

        with (
            patch.object(cli.subprocess, "run", fake_run),
            patch.object(cli, "committed_sources", lambda commit: committed),
        ):
            return cli.code_commit()

    def test_clean_checkout_records_the_commit(self) -> None:
        self.assertEqual("0123abc", self.commit_with(""))

    def test_edited_tracked_file_marks_the_commit_dirty(self) -> None:
        self.assertEqual("0123abc+dirty", self.commit_with(" M src/x.py\n"))

    def test_a_commit_whose_sources_were_not_imported_is_dirty(self) -> None:
        # Codex review of #160: a checkout moved to another clean commit after the
        # imports leaves no edit to see, but its sources are not the ones running.
        moved = {**jobs.SOURCE_FILES, "strategy/regime.py": "0" * 64}
        self.assertEqual("0123abc+dirty", self.commit_with("", moved))
        self.assertEqual("0123abc+dirty", self.commit_with("", None))  # git cannot read it

    def test_committed_sources_hash_the_tree_as_the_imports_do(self) -> None:
        tree = cli.committed_sources("HEAD")
        if tree is None:
            self.skipTest("no git checkout to read")
        self.assertIn("backtest/jobs.py", tree)
        # A source the P8 run pins never changes, so git's copy and the disk agree,
        # whatever line endings the checkout uses.
        pinned = ROOT / "src/crypto_grid_bot/market_data/parsing.py"
        self.assertEqual(jobs.source_hash(pinned.read_bytes()), tree["market_data/parsing.py"])

    def test_the_summary_names_a_variant(self) -> None:
        # Codex review of #160: summary.md alone tells the variants from V0.
        v0, variant = good_result("BTCUSDT", "ohlc", True), good_result("BTCUSDT", "ohlc", True)
        variant["variant"] = "B"
        rows = cli._table([v0, variant]).splitlines()[2:]
        self.assertIn("| gated |", rows[0])
        self.assertIn("| gated, variant B |", rows[1])


class VariantGRefusalTests(unittest.TestCase):
    def test_a_g_run_on_a_manifest_without_funding_archives_is_refused(self):
        # Codex review of #165: such a run blocks every new grid and could be published
        # as valid.
        spec = jobs.load_spec(Path(SPEC))
        prepared = jobs.PreparedRun(spec, None, {"files": []}, None, None, None, [])
        with (
            patch.object(jobs, "prepare_run", lambda *args, **kwargs: prepared),
            patch.object(jobs, "replay", None),  # never reached
            self.assertRaisesRegex(ValueError, "funding archive for every evaluation month"),
        ):
            jobs.run_job(
                Path(SPEC),
                ROOT / "config/default.toml",
                Path("data"),
                "BTCUSDT",
                "high_first",
                True,
                None,
                SimulationPolicy(funding_gate=True),
            )
