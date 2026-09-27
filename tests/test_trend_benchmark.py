"""Variant D, the trend benchmark (spec v1 §3 D), and its shared daily-SMA signal.

Synthetic data only. Every price, quantity and fee below is computed by hand from the
adapter's rounding rules and written as a literal; the test does not recompute it with
the code under test.
"""

import contextlib
import io
import json
import pickle
import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from test_backtest_cli import CLEAN, SPEC, Done, good_result
from test_backtest_loaders import FakeArchive, day_rows, hour_rows, minute_rows
from test_backtest_replay import HOUR_MS, START_MS, WARMUP, candle, engine_for, hourly

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest.dataset import fetch_dataset, load_spec, write_manifest
from crypto_grid_bot.backtest.jobs import run_job
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import RunConfig, bar_quotes, replay
from crypto_grid_bot.backtest.trend_benchmark import (
    SMA_LENGTH,
    TrendAccount,
    check_trend_accounting,
    daily_history_problems,
    enter,
    exit_step,
    replay_trend,
    trend_job,
)
from crypto_grid_bot.config import load_config
from crypto_grid_bot.simulation.models import MarketRules
from crypto_grid_bot.strategy.daily_sma import (
    DAY_MS,
    DailyCloses,
    close_above_sma,
    signal_day,
)

ROOT = Path(__file__).resolve().parents[1]
# Evaluation day E: observations during E may use the daily bar of E - 1 only.
E = int(datetime(2024, 3, 1, tzinfo=UTC).timestamp() * 1000)
MINUTE_MS = 60_000
RULES = MarketRules(
    symbol="TESTUSDT",
    tick_size=D("0.0001"),
    quantity_step=D("0.1"),
    minimum_notional=D("5"),
    fee_rate=D("0"),  # maker: D never pays it
    slippage_rate=D("0.0005"),
    participation=D("0.10"),
    taker_fee_rate=D("0.0009"),  # primary Revolut X taker fee
)
RUN = RunConfig("TESTUSDT", "high_first", False, RULES, D(100), D("0.0005"))


def closes_ending(last_day, values):
    """Daily closes for consecutive days ending at ``last_day``, oldest first."""
    first = last_day - (len(values) - 1) * DAY_MS
    return [(first + i * DAY_MS, D(v)) for i, v in enumerate(values)]


# Hold during day E (bar E-1 is above its SMA50), cash during E+1, hold during E+2.
# SMA50(E-1) = (49 x 1 + 2) / 50 = 1.02 < 2
# SMA50(E)   = (48 x 1 + 2 + 0.5) / 50 = 1.01 > 0.5
# SMA50(E+1) = (47 x 1 + 2 + 0.5 + 3) / 50 = 1.05 < 3
SWITCHING = DailyCloses(closes_ending(E + DAY_MS, ["1"] * 49 + ["2", "0.5", "3"]))


def flat(open_ms, price, volume="1000000", taker="500000"):
    p = D(price)
    return Kline(open_ms, p, p, p, p, D(volume), D(volume) * p, D(taker))


def always(_open_ms):
    return True


def run_d(minutes, closes, evaluated=always, run=RUN):
    metrics, account = replay_trend(run, minutes, closes, evaluated)
    return metrics, account


class DailySmaTests(unittest.TestCase):
    def test_signal_day_is_the_previous_utc_day_at_and_after_midnight(self):
        self.assertEqual(E - DAY_MS, signal_day(E))  # 00:00:00.000 uses the bar just closed
        self.assertEqual(E - DAY_MS, signal_day(E + DAY_MS - 1))
        self.assertEqual(E - 2 * DAY_MS, signal_day(E - 1))  # one ms earlier: not yet

    def test_hand_computed_sma_and_strict_comparison(self):
        rising = DailyCloses(closes_ending(E, ["1"] * 49 + ["2"]))
        self.assertEqual(D("1.02"), rising.sma(E, 50))
        self.assertTrue(close_above_sma(rising, E, 50))
        level = DailyCloses(closes_ending(E, ["1"] * 50))
        self.assertEqual(D("1"), level.sma(E, 50))
        self.assertFalse(close_above_sma(level, E, 50))  # equal is not above
        falling = DailyCloses(closes_ending(E, ["1"] * 49 + ["0.99"]))
        self.assertEqual(D("0.9998"), falling.sma(E, 50))
        self.assertFalse(close_above_sma(falling, E, 50))
        # Three days, by hand: (3 + 4 + 8) / 3 = 5 < 8.
        short = DailyCloses(closes_ending(E, ["3", "4", "8"]))
        self.assertEqual(D("5"), short.sma(E, 3))
        self.assertTrue(close_above_sma(short, E, 3))

    def test_short_history_missing_day_and_non_positive_values_are_undefined(self):
        self.assertIsNone(close_above_sma(DailyCloses(closes_ending(E, ["1"] * 49)), E, 50))
        gap = [bar for bar in closes_ending(E, ["1"] * 49 + ["2"]) if bar[0] != E - 10 * DAY_MS]
        self.assertIsNone(close_above_sma(DailyCloses(gap), E, 50))
        self.assertIsNone(DailyCloses(gap).sma(E, 50))
        for bad in ("0", "-1"):
            with self.subTest(close=bad):
                values = ["1"] * 49 + ["2"]
                values[20] = bad
                self.assertIsNone(close_above_sma(DailyCloses(closes_ending(E, values)), E, 50))
                self.assertIsNone(
                    close_above_sma(DailyCloses(closes_ending(E, ["1"] * 49 + [bad])), E, 50)
                )
        # The bar of the day itself missing is undefined too; no older bar stands in.
        self.assertIsNone(
            close_above_sma(DailyCloses(closes_ending(E - DAY_MS, ["1"] * 60)), E, 50)
        )

    def test_a_later_bar_never_changes_an_earlier_value(self):
        base = closes_ending(E, ["1"] * 49 + ["2"])
        later = base + [(E + DAY_MS, D("1000"))]
        self.assertEqual(DailyCloses(base).sma(E, 50), DailyCloses(later).sma(E, 50))

    def test_malformed_series_is_rejected(self):
        with self.assertRaises(ValueError):
            DailyCloses([(E, D(1)), (E, D(2))])  # duplicate day
        with self.assertRaises(ValueError):
            DailyCloses([(E + HOUR_MS, D(1))])  # not a UTC-midnight open
        with self.assertRaises(ValueError):
            DailyCloses([(E, D("NaN"))])
        with self.assertRaises(ValueError):
            DailyCloses([]).sma(E, 0)


class FillArithmeticTests(unittest.TestCase):
    """Hand-computed fills. Flat bar at 1.0000 with a 0.05% spread (high_first):

    quote 0 (open)  bid 0.9997 = floor(0.99975), ask 1.0003 = ceil(1.00025)
    quote 1 (high)  bid 0.9995 = floor(0.9995),  ask 1.0000
    quote 2 (low)   bid 1.0000,                  ask 1.0005 = ceil(1.0005)
    quote 3 (close) as quote 0
    """

    def test_single_entry_fill_with_taker_fee(self):
        metrics, account = run_d([flat(E, "1")], SWITCHING)
        # Buy price ceil_tick(1.0003 x 1.0005 = 1.00080015) = 1.0009.
        # All-in unit cost 1.0009 x 1.0009 = 1.00180081; 100 / 1.00180081 = 99.82... -> 99.8.
        # Participation: ask size (1,000,000 - 500,000) / 4 = 125,000; 10% = 12,500.
        (fill,) = [f for _, f in metrics.fills]
        self.assertEqual(("buy", D("1.0009"), D("99.8")), (fill.side, fill.price, fill.quantity))
        self.assertEqual(D("0.089900838"), fill.fee)  # 99.8 x 1.0009 = 99.88982; x 0.0009
        self.assertEqual(D("0.020279162"), account.cash)  # 100 - 99.88982 - 0.089900838
        self.assertEqual(D("99.8"), account.inventory)
        # Quote 1: 0.020279162 buys 0.0 at 1.0005 -> below the minimum, the entry ends.
        self.assertEqual("idle", account.phase)
        self.assertEqual((1, 0, 1), (metrics.buys, metrics.sells, metrics.entries_started))
        self.assertEqual([], check_trend_accounting(RUN, metrics, account))

    def test_entry_then_exit_with_fees_and_realised_pnl(self):
        minutes = [flat(E, "1"), flat(E + DAY_MS, "1.2")]
        metrics, account = run_d(minutes, SWITCHING)
        # E+1 00:00:00, quote 0: bid floor(1.2 x 0.99975 = 1.1997) = 1.1997.
        # Sell price floor_tick(1.1997 x 0.9995 = 1.19910015) = 1.1991.
        # Bid size 500,000 / 4 = 125,000; 10% = 12,500, so all 99.8 sell at once.
        sell = metrics.fills[1][1]
        self.assertEqual(f"trend/sell/TESTUSDT/{E + DAY_MS}/0", sell.order_id)
        self.assertEqual(("sell", D("1.1991"), D("99.8")), (sell.side, sell.price, sell.quantity))
        self.assertEqual(D("0.107703162"), sell.fee)  # 99.8 x 1.1991 = 119.67018; x 0.0009
        # 0.020279162 + 119.67018 - 0.107703162 = 119.582756.
        self.assertEqual(D("119.582756"), account.cash)
        self.assertEqual(D("0"), account.inventory)
        # Average cost 99.979720838 (notional + fee); 119.562476838 - 99.979720838.
        self.assertEqual(D("19.582756"), metrics.realised_pnl)
        self.assertEqual(D("119.582756"), metrics.final_equity)
        self.assertEqual(D("0.197604000"), metrics.buy_fees + metrics.sell_fees)
        self.assertEqual([], check_trend_accounting(RUN, metrics, account))

    def test_entry_residual_is_the_remaining_quote_budget(self):
        # Ask size (2,000 - 1,000) / 4 = 250; 10% = 25.0 per quote, so the entry fills
        # over several quotes, each sized from the cash then left.
        metrics, account = run_d([flat(E, "1", "2000", "1000")], SWITCHING)
        got = [(f.price, f.quantity, f.fee) for _, f in metrics.fills]
        self.assertEqual(
            [
                (D("1.0009"), D("25.0"), D("0.02252025")),  # 25.0225 x 0.0009
                (D("1.0005"), D("25.0"), D("0.02251125")),  # ceil(1.0000 x 1.0005)
                (D("1.0011"), D("25.0"), D("0.02252475")),  # ceil(1.0005 x 1.0005)
                # Cash 24.86994375 / (1.0009 x 1.0009) = 24.825... -> 24.8 < 25.0 cap.
                (D("1.0009"), D("24.8"), D("0.022340088")),
            ],
            got,
        )
        self.assertEqual(D("0.025283662"), account.cash)
        self.assertGreaterEqual(account.cash, 0)
        self.assertEqual([], check_trend_accounting(RUN, metrics, account))

    def test_a_retry_never_spends_more_than_the_cash_left(self):
        account = TrendAccount(cash=D("5.1"), holding=True, phase="entering")
        (quote, *_) = bar_quotes(flat(E, "1"), "TESTUSDT", "high_first", D("0.0005"), D("0.0001"))
        fill = enter(account, quote, RULES)
        # 5.1 / 1.00180081 = 5.09... -> 5.0; 5.0 x 1.0009 = 5.0045 >= 5 minimum.
        self.assertEqual(D("5.0"), fill.quantity)
        self.assertEqual(D("0.09099595"), account.cash)  # 5.1 - 5.0045 - 0.00450405
        self.assertIsNone(enter(account, quote, RULES))
        self.assertEqual("idle", account.phase)

    def test_exit_remainder_below_minimum_stays_as_dust(self):
        (quote, *_) = bar_quotes(flat(E, "2"), "TESTUSDT", "high_first", D("0.0005"), D("0.0001"))
        # Sell price floor_tick(1.9995 x 0.9995 = 1.99850025) = 1.9985; 2.5 x 1.9985 < 5.
        account = TrendAccount(cash=D(0), inventory=D("2.5"), phase="exiting")
        self.assertIsNone(exit_step(account, quote, RULES))
        self.assertEqual(("idle", D("2.5")), (account.phase, account.inventory))

    def test_thin_exit_observation_retries_instead_of_ending(self):
        # Bid size 40 / 4 = 10; 10% = 1.0 unit, 1.9985 < 5: nothing now, keep exiting.
        thin = flat(E, "2", "80", "40")
        (quote, *_) = bar_quotes(thin, "TESTUSDT", "high_first", D("0.0005"), D("0.0001"))
        account = TrendAccount(cash=D(0), inventory=D("10"), phase="exiting")
        self.assertIsNone(exit_step(account, quote, RULES))
        self.assertEqual(("exiting", D("10")), (account.phase, account.inventory))

    def test_literal_reading_a_thin_entry_observation_ends_the_entry(self):
        # Handoff question 1: "the entry ends when that quantity is below the minimum
        # notional" is applied literally, so a zero-volume first observation ends it.
        minutes = [flat(E, "1", "0", "0"), flat(E + MINUTE_MS, "1")]
        metrics, account = run_d(minutes, SWITCHING)
        self.assertEqual((1, 0), (metrics.entries_started, metrics.buys))
        self.assertEqual((D(100), D(0)), (account.cash, account.inventory))


class TimingTests(unittest.TestCase):
    def test_no_lookahead_the_first_fill_is_at_midnight_after_the_signal_bar(self):
        # Bar E-1 turns the signal to hold; it closes at E. Before E only bar E-2 counts,
        # whose close equals its SMA (cash).
        closes = DailyCloses(closes_ending(E - DAY_MS, ["1"] * 50 + ["2"]))
        minutes = [flat(E - 2 * MINUTE_MS, "1"), flat(E - MINUTE_MS, "1"), flat(E, "1")]
        metrics, _ = run_d(minutes, closes)
        (observed, fill), *_ = metrics.fills
        self.assertEqual(f"trend/buy/TESTUSDT/{E}/0", fill.order_id)
        self.assertEqual("2024-03-01T00:00:00+00:00", observed)
        self.assertEqual({"cash": 2, "hold": 1}, dict(metrics.signal_by_bar))

    def test_the_bar_still_forming_never_changes_a_decision(self):
        # During day E the bar of E is still forming. Whatever it says, fills in E match.
        minutes = [flat(E + i * HOUR_MS, "1") for i in range(24)]
        base = closes_ending(E - DAY_MS, ["1"] * 49 + ["2"])
        runs = [
            run_d(minutes, DailyCloses(base + extra))[0].fills
            for extra in ([], [(E, D("0.0001"))], [(E, D("1000"))])
        ]
        self.assertTrue(runs[0])
        self.assertEqual(runs[0], runs[1])
        self.assertEqual(runs[0], runs[2])

    def test_warm_up_not_ready_means_no_position(self):
        closes = DailyCloses(closes_ending(E - DAY_MS, ["1"] * 48 + ["2"]))  # 49 bars only
        metrics, account = run_d([flat(E + i * MINUTE_MS, "1") for i in range(5)], closes)
        self.assertEqual((0, 0), (metrics.buys, metrics.entries_started))
        self.assertEqual({"undefined": 5}, dict(metrics.signal_by_bar))
        self.assertEqual((D(100), D(0)), (account.cash, account.inventory))
        self.assertEqual(D(0), metrics.max_drawdown)

    def test_minutes_the_grid_replay_skips_are_skipped_and_entry_waits_for_the_first(self):
        minutes = [flat(E + i * MINUTE_MS, "1") for i in range(5)]
        ready_from = E + 3 * MINUTE_MS
        metrics, _ = run_d(minutes, SWITCHING, evaluated=lambda ms: ms >= ready_from)
        self.assertEqual((3, 2), (metrics.warmup_bars, metrics.bars))
        self.assertEqual(ready_from, metrics.first_bar_ms)
        self.assertEqual(f"trend/buy/TESTUSDT/{ready_from}/0", metrics.fills[0][1].order_id)

    def test_reversals_abandon_the_unfinished_side_at_the_same_observation(self):
        # 5.0 units per quote each way at price 2: ask and bid size 200 / 4 = 50; 10% = 5.
        day_e = [flat(E, "2", "400", "200"), flat(E + MINUTE_MS, "2", "400", "200")]
        day_e1 = [flat(E + DAY_MS, "2", "400", "200")]
        day_e2 = [flat(E + 2 * DAY_MS, "2", "400", "200")]
        metrics, account = run_d(day_e + day_e1 + day_e2, SWITCHING)
        sides = [(f.order_id.split("/")[1], f.quantity) for _, f in metrics.fills]
        # Day E: 8 buys of 5.0 = 40.0, entry still running (cash ~19.9 left).
        self.assertEqual([("buy", D("5.0"))] * 8, sides[:8])
        # E+1 00:00:00: the entry is abandoned and the exit starts at that same quote;
        # 4 sells of 5.0 leave 20.0 unsold when the day's only minute ends.
        self.assertEqual([("sell", D("5.0"))] * 4, sides[8:12])
        self.assertEqual(f"trend/sell/TESTUSDT/{E + DAY_MS}/0", metrics.fills[8][1].order_id)
        # E+2 00:00:00: the exit is abandoned; the 20.0 stay held and the new entry adds.
        self.assertEqual(f"trend/buy/TESTUSDT/{E + 2 * DAY_MS}/0", metrics.fills[12][1].order_id)
        self.assertEqual((1, 1), (metrics.entries_abandoned, metrics.exits_abandoned))
        self.assertEqual((2, 1), (metrics.entries_started, metrics.exits_started))
        self.assertGreater(account.inventory, D("20.0"))
        self.assertEqual([], check_trend_accounting(RUN, metrics, account))


class SamplingTests(unittest.TestCase):
    """P2: D's equity and buy-and-hold are sampled exactly like the grid replay's."""

    def test_same_evaluated_bars_hourly_schedule_and_buy_and_hold_as_v0(self):
        engine = engine_for(hourly(WARMUP))
        # Ten-minute steps from hour 740 to 760: the first few are still warm-up.
        minutes = [
            candle(START_MS + 740 * HOUR_MS + i * 10 * MINUTE_MS, 1.0, 1.004, 0.996, 1.0)
            for i in range(120)
        ]
        run = RunConfig("TESTUSDT", "low_first", False, RULES, D(100), D("0.0005"))
        config = load_config(ROOT / "config/default.toml")
        v0, _ = replay(config, run, minutes, engine)
        last = signal_day(minutes[-1].open_ms)
        closes = DailyCloses(closes_ending(last, ["1"] * 80 + ["2"] * 20))
        d, account = run_d(minutes, closes, lambda ms: engine.at(ms) is not None, run)
        self.assertGreater(v0.warmup_bars, 0)
        self.assertGreater(d.buys, 0)
        for name in ("warmup_bars", "bars", "first_bar_ms", "last_bar_ms"):
            self.assertEqual(getattr(v0, name), getattr(d, name), name)
        self.assertEqual([h[0] for h in v0.hourly_equity], [h[0] for h in d.hourly_equity])
        self.assertEqual([h[2] for h in v0.hourly_equity], [h[2] for h in d.hourly_equity])
        self.assertEqual((v0.hold_final, v0.hold_max_drawdown), (d.hold_final, d.hold_max_drawdown))
        self.assertEqual(4 * d.bars, d.frames)  # one sample per quote
        self.assertEqual([], check_trend_accounting(run, d, account))

    def test_drawdown_is_sampled_at_every_quote_after_fills(self):
        # Invested at E, then one bar dips 5% intrabar and closes unchanged.
        dip = Kline(E + MINUTE_MS, D(1), D(1), D("0.95"), D(1), D(1000000), D(1000000), D(500000))
        metrics, _ = run_d([flat(E, "1"), dip, flat(E + 2 * MINUTE_MS, "1")], SWITCHING)
        self.assertGreater(metrics.max_drawdown, D("0.045"))
        self.assertEqual(D(metrics.hourly_equity[0][1]), metrics.final_equity)


class AccountingTests(unittest.TestCase):
    def test_tampering_is_detected(self):
        metrics, account = run_d([flat(E, "1")], SWITCHING)
        account.cash += D("0.01")
        problems = check_trend_accounting(RUN, metrics, account)
        self.assertTrue(any(p.startswith("cash identity failed") for p in problems))
        self.assertTrue(any(p.startswith("final equity identity failed") for p in problems))
        account.cash -= D("0.01")
        metrics.realised_pnl += D("0.01")
        problems = check_trend_accounting(RUN, metrics, account)
        self.assertEqual(1, len(problems))
        self.assertTrue(problems[0].startswith("P&L reconciliation failed"))

    def test_a_spec_without_daily_history_makes_the_run_invalid(self):
        spec = load_spec(Path(SPEC))
        self.assertEqual([], daily_history_problems(spec))
        with tempfile.TemporaryDirectory() as temp:
            text = Path(SPEC).read_text().replace('daily_warmup_start = "2023-05"\n', "")
            path = Path(temp) / "no-daily.toml"
            path.write_text(text)
            (problem,) = daily_history_problems(load_spec(path))
        self.assertIn("daily_warmup_start", problem)


class Inline:
    """Synchronous stand-in for ProcessPoolExecutor that records submitted functions."""

    submitted: list = []

    def __init__(self, max_workers):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def submit(self, fn, *args):
        self.submitted.append((fn, args))
        if fn.__name__ == "cross_check_job":
            return Done({"symbol": args[2], **CLEAN})
        if fn is trend_job:
            return Done({**good_result(args[3], args[4], False), "variant": "D"})
        return Done(good_result(*args[3:6]))


class CliTests(unittest.TestCase):
    """V0 unchanged: without the flag the CLI submits and writes exactly what it did."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        Inline.submitted = []
        patches = [
            patch.object(cli, "ProcessPoolExecutor", Inline),
            patch.object(cli, "load_manifest", lambda path: {"created_at": "t"}),
            patch.object(cli, "verify_dataset", lambda *a: None),
            patch.object(cli, "_identity", lambda *a: {}),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def run_cli(self, *extra):
        out = Path(self.temp.name) / str(len(extra))
        with contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["run", "--spec", SPEC, "--out", str(out), *extra])
        (written,) = out.rglob("results.json")
        return code, json.loads(written.read_text())

    def test_without_the_flag_no_trend_job_runs_and_the_document_is_unchanged(self):
        code, document = self.run_cli()
        self.assertEqual(0, code)
        self.assertNotIn(trend_job, [fn for fn, _ in Inline.submitted])
        self.assertNotIn("trend_benchmark", document)
        self.assertEqual(8, len(document["results"]))  # 2 pairs x 2 paths x gated/ungated

    def test_the_flag_adds_one_d_run_per_pair_and_path_with_the_same_fees(self):
        code, document = self.run_cli(
            "--trend-benchmark", "--maker-fee", "0", "--taker-fee", "0.0009"
        )
        self.assertEqual(0, code)
        calls = [args for fn, args in Inline.submitted if fn is trend_job]
        self.assertEqual(
            [
                (symbol, mode, (D("0"), D("0.0009")))
                for symbol in ("ADAUSDT", "BTCUSDT")
                for mode in ("high_first", "low_first")
            ],
            [args[3:] for args in calls],
        )
        self.assertEqual("D (spec v1 §3 D)", document["trend_benchmark"])
        self.assertEqual(12, len(document["results"]))
        self.assertEqual(4, sum(1 for r in document["results"] if r.get("variant") == "D"))

    def test_trend_job_is_importable_by_a_spawned_worker(self):
        self.assertEqual("crypto_grid_bot.backtest.trend_benchmark", trend_job.__module__)
        self.assertIs(trend_job, pickle.loads(pickle.dumps(trend_job)))  # nosec B301


DEC_2023_MS = int(datetime(2023, 12, 1, tzinfo=UTC).timestamp() * 1000)
NOV_2023_MS = int(datetime(2023, 11, 1, tzinfo=UTC).timestamp() * 1000)
JAN_2024_MS = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1000)


class TrendJobTests(unittest.TestCase):
    """The pool job end to end on a tiny synthetic archive (nothing is downloaded)."""

    def test_trend_job_matches_the_grid_run_window_and_samples(self):
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            spec_path = work / "tiny.toml"
            spec_path.write_text(
                'name = "tiny"\npurpose = "variant D wiring test"\ntraded = ["BTCUSDT"]\n'
                'market_proxy = "BTCUSDT"\nbreadth_basket = ["BTCUSDT"]\n'
                'daily_warmup_start = "2023-11"\nwarmup_start = "2023-12"\n'
                'start = "2024-01"\nend = "2024-01"\n'
                'initial_quote = "100"\nfee_rate = "0.001"\nslippage_rate = "0.0005"\n'
                'participation = "0.10"\nassumed_spread_pct = "0.05"\n'
            )
            archive = FakeArchive()
            archive.add("BTCUSDT", "1m", "2024-01", minute_rows(JAN_2024_MS, 120))
            archive.add("BTCUSDT", "1h", "2023-12", hour_rows(DEC_2023_MS, 744))
            archive.add("BTCUSDT", "1h", "2024-01", hour_rows(JAN_2024_MS, 3))
            archive.add("BTCUSDT", "1d", "2023-11", day_rows(NOV_2023_MS, 30))
            archive.add("BTCUSDT", "1d", "2023-12", day_rows(DEC_2023_MS, 31))
            archive.add("BTCUSDT", "1d", "2024-01", day_rows(JAN_2024_MS, 31))
            filters = {"base": "BTC", "quote": "USDT", "tick_size": "0.01"}
            filters |= {"quantity_step": "0.00001", "min_notional": "5"}
            manifest = fetch_dataset(
                load_spec(spec_path), work / "data", fetcher=archive, instruments=lambda s: filters
            )
            write_manifest(work / "tiny.manifest.json", manifest)
            config = ROOT / "config/default.toml"
            fees = (D("0"), D("0.0009"))
            grid = run_job(spec_path, config, work / "data", "BTCUSDT", "high_first", True, fees)
            d = trend_job(spec_path, config, work / "data", "BTCUSDT", "high_first", fees)
        self.assertEqual([], d["accounting_problems"])
        self.assertEqual(("D", False), (d["variant"], d["selectable"]))
        self.assertEqual(grid["window"], d["window"])
        self.assertEqual(grid["bars"], d["bars"])
        self.assertGreater(d["bars"], 0)
        self.assertEqual([h[0] for h in grid["hourly_equity"]], [h[0] for h in d["hourly_equity"]])
        self.assertEqual([h[2] for h in grid["hourly_equity"]], [h[2] for h in d["hourly_equity"]])
        # Every daily close is 1.1, equal to its SMA50: never above, so D stays in cash.
        self.assertEqual({"cash": 120}, d["signal_by_bar"])
        self.assertEqual((0, D(100)), (d["buys"], D(d["final_total_equity"])))
        self.assertEqual(SMA_LENGTH, 50)


if __name__ == "__main__":
    unittest.main()
