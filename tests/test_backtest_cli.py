"""R1: integrity failures must invalidate verify/run and never reach replay."""

import contextlib
import io
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.market_data.parsing import DataError

ROOT = Path(__file__).resolve().parents[1]
SPEC = str(ROOT / "config/datasets/verify-2024h1.toml")
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

    def __init__(self, max_workers):
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


class CliIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.checks = dict(CLEAN)
        self.result_patch = {}
        self.replays = []
        self.fees = []
        self.strict = []
        patches = [
            patch.object(cli, "ProcessPoolExecutor", Inline),
            patch.object(cli, "load_manifest", lambda path: {"created_at": "t"}),
            patch.object(cli, "verify_dataset", lambda *a: None),
            patch.object(cli, "_identity", lambda *a: {}),
            patch.object(cli, "cross_check_job", self.fake_check),
            patch.object(cli, "run_job", self.fake_run),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def fake_check(self, spec, data_dir, symbol, strict_volume=False):
        self.strict.append(strict_volume)
        return {"symbol": symbol, **self.checks}

    def fake_run(self, spec, config, data_dir, symbol, mode, gated, fees=None):
        self.replays.append(symbol)
        self.fees.append(fees)
        return {**good_result(symbol, mode, gated), **self.result_patch}

    def main(self, command, *extra):
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main([command, "--spec", SPEC, "--out", self.temp.name, *extra])

    def test_clean_data_verifies_and_runs(self):
        self.assertEqual(0, self.main("verify"))
        self.assertEqual(0, self.main("run"))
        self.assertTrue(self.replays)
        (written,) = Path(self.temp.name).rglob("results.json")
        self.assertTrue(json.loads(written.read_text())["valid"])

    def test_fee_overrides_reach_every_replay_and_the_results(self):
        self.assertEqual(0, self.main("run"))
        self.assertEqual({(Decimal("0.001"), None)}, set(self.fees))  # spec fee, taker = maker
        self.fees.clear()
        self.assertEqual(0, self.main("run", "--maker-fee", "0", "--taker-fee", "0.0009"))
        self.assertEqual({(Decimal("0"), Decimal("0.0009"))}, set(self.fees))
        (latest,) = Path(self.temp.name).rglob("*-m0-t0.0009/results.json")
        fees = json.loads(latest.read_text())["fees"]
        self.assertEqual({"maker": "0", "taker": "0.0009"}, fees)

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

    def fake_check(self, spec, data_dir, symbol, strict_volume=False):
        self.checked.append(symbol)
        if symbol == "ETHUSDT":
            return {"symbol": symbol, **self.proxy_checks}
        return super().fake_check(spec, data_dir, symbol, strict_volume)

    def main(self, command, *extra):
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.main([command, "--spec", str(self.spec), "--out", self.temp.name, *extra])

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

    def fake_check(self, spec, data_dir, symbol, strict_volume=False):
        if symbol == "DOGEUSDT":
            self.checked.append(symbol)
            return {"symbol": symbol, **self.basket_check}
        return super().fake_check(spec, data_dir, symbol, strict_volume)

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
