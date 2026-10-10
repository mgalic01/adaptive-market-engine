"""The full stack C+F+G+H+V2 (spec v1 §3, test-plan amendment of 2026-10-05) end to end.

A synthetic dataset is fetched from a fake archive by the pinned fetch code, with
BTCUSDT's funding archives in its manifest. The backtest's own pool job replays it with
every part on: A and B (together C), F, G, H and the V2 structure features. The backtest
CLI then runs V0 with D, V2 and the full stack on it, and the acceptance scorer reads the
results.json files the CLI wrote. Nothing here is market data or evidence.
"""

import contextlib
import hashlib
import io
import math
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

from test_backtest_loaders import FakeArchive

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest import acceptance as score
from crypto_grid_bot.backtest.dataset import (
    fetch_dataset,
    funding_archive_path,
    load_spec,
    write_manifest,
)
from crypto_grid_bot.backtest.features import (
    STRUCTURE_FEATURE_VERSION,
    FeatureEngine,
    SeriesFeatures,
)
from crypto_grid_bot.backtest.jobs import SymbolMask, run_job, variant_policy
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.backtest.replay import PATH_MODES
from crypto_grid_bot.simulation.runner import FULL_STACK

ROOT = Path(__file__).resolve().parents[1]
MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
MAY_2023_MS = 1682899200000  # 2023-05-01T00:00:00Z, the daily warm-up start
DEC_2023_MS = 1701388800000  # 2023-12-01T00:00:00Z, the hourly warm-up start
JAN_2024_MS = 1704067200000  # 2024-01-01T00:00:00Z, the evaluation start
TRADED = ("BTCUSDT", "ETHUSDT")
# The section 4 primary settings, so the scorer takes the runs as acceptance runs.
SPEC = """name = "full-stack"
purpose = "full-stack wiring test"
traded = ["BTCUSDT", "ETHUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"]
daily_warmup_start = "2023-05"
warmup_start = "2023-12"
start = "2024-01"
end = "2024-01"
initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""


def bar(open_ms, o, h, low, c):
    """A bar with half its volume taker-bought, which F lets through."""
    o, h, low, c = (D(str(round(x, 6))) for x in (o, h, low, c))
    return Kline(open_ms, o, h, low, c, D(10**6), D(10**6) * c, D(5 * 10**5))


def hours(start_ms, count):
    """A daily sine wave around 1.0, as the replay tests' hourly series, in the phase in
    which their grids open at 00:00 UTC (eight hours on)."""
    candles, previous = [], 1.0
    for i in range(count):
        close = 1.0 + 0.08 * math.sin(2 * math.pi * (i + 8) / 24)
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        candles.append(bar(start_ms + i * HOUR_MS, previous, high, low, close))
        previous = close
    return candles


def month_of(open_ms):
    return datetime.fromtimestamp(open_ms / 1000, UTC).strftime("%Y-%m")


def add_klines(archive, symbol, interval, step, klines):
    """Each month of ``klines`` as Binance's monthly archive of ``symbol`` at ``interval``."""
    months: dict[str, list[str]] = {}
    for k in klines:
        months.setdefault(month_of(k.open_ms), []).append(
            f"{k.open_ms},{k.open},{k.high},{k.low},{k.close},{k.volume},"
            f"{k.open_ms + step - 1},{k.quote_volume},10,{k.taker_buy_base},"
            f"{k.taker_buy_base * k.close},0"
        )
    for month, rows in months.items():
        archive.add(symbol, interval, month, "\n".join(rows) + "\n")


def add_funding(archive, first_ms, count):
    """BTCUSDT settlements every 8 hours at +0.01%, which G lets through, in the monthly
    funding archive of their month."""
    month = month_of(first_ms)
    rows = "".join(f"{first_ms + i * 8 * HOUR_MS},8,0.00010000\n" for i in range(count))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipped:
        zipped.writestr(
            f"BTCUSDT-fundingRate-{month}.csv",
            "calc_time,funding_interval_hours,last_funding_rate\n" + rows,
        )
    path, body = funding_archive_path("BTCUSDT", month), buffer.getvalue()
    archive.objects[path] = body
    name = path.rsplit("/", 1)[1]
    archive.objects[path + ".CHECKSUM"] = f"{hashlib.sha256(body).hexdigest()}  {name}".encode()
    return {"kind": "fundingRate", "symbol": "BTCUSDT", "month": month}


def make_dataset(work):
    """The dataset's spec, manifest and hash-checked archives under ``work``; returns the
    spec's path. Both traded pairs have the same bars."""
    hourly = hours(DEC_2023_MS, 744 + 2)
    engine = FeatureEngine(
        SeriesFeatures("BTCUSDT", hourly),
        SeriesFeatures("BTCUSDT", hourly),
        [SeriesFeatures(f"B{i}USDT", hourly, full=False) for i in range(5)],
        range_atr_multiple=2.0,
        levels=8,
        minimum_cost_multiple=3.0,
        round_trip_cost=0.0035,
    )
    fair = float(engine.at(JAN_2024_MS).fair_value)
    minutes = [
        bar(JAN_2024_MS + i * MINUTE_MS, fair, fair * 1.001, fair * 0.999, fair) for i in range(60)
    ]
    # Rising daily closes from 2023-05-01, 245 of them before the evaluation, so A is Up.
    # In 2024-01 the phase is 43 months, in H3's band, not H2's; the halving's bar is not
    # among the closes, so H3's all-time high is unavailable and it never acts.
    days = [
        bar(MAY_2023_MS + i * DAY_MS, *(0.5 + i / 500 + d for d in (0, 0.01, -0.01, 0)))
        for i in range(245)
    ]
    archive = FakeArchive()
    for pair in TRADED:
        add_klines(archive, pair, "1m", MINUTE_MS, minutes)
        add_klines(archive, pair, "1d", DAY_MS, days)
    # The basket votes with the pair's hours, so breadth is as good as the pair's.
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"):
        add_klines(archive, symbol, "1h", HOUR_MS, hourly)
    # G's settlements up to the evaluation start, so it is available from the start.
    funding = [add_funding(archive, DEC_2023_MS, 93), add_funding(archive, JAN_2024_MS, 1)]
    filters = {"base": "BTC", "quote": "USDT", "tick_size": "0.0001"}
    filters |= {"quantity_step": "0.1", "min_notional": "5"}
    spec_path = work / "full-stack.toml"
    spec_path.write_text(SPEC)
    manifest = fetch_dataset(
        load_spec(spec_path),
        work / "data",
        fetcher=archive,
        instruments=lambda symbol: filters,
        previous={"files": funding},
    )
    write_manifest(work / "full-stack.manifest.json", manifest)
    return spec_path


class SyntheticDataset(unittest.TestCase):
    """One synthetic dataset, built once for the class."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.spec_path = make_dataset(cls.work)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()


class FullStackJobTests(SyntheticDataset):
    """The pool job, with every part of the full stack on."""

    def job(self, gated):
        row = run_job(
            self.spec_path,
            ROOT / "config/default.toml",
            self.work / "data",
            "BTCUSDT",
            "high_first",
            gated,
            (D("0"), D("0.0009")),
            variant_policy(FULL_STACK, structure=True),
        )
        self.assertEqual([], row["accounting_problems"])
        self.assertEqual((60, 0), (row["bars"], row["transient_pauses"]))
        # G and H ran and report, as when they run alone (spec v1 §3 G and H).
        self.assertEqual({"43": 60}, row["cycle_phases_by_bar"])
        self.assertEqual(60, row["cycle_ath_unavailable_bars"])
        self.assertEqual(0, row["funding_gate_blocked_hours"])
        return row

    def test_the_gated_rows_carry_the_labels_the_scorer_reads(self):
        row = self.job(True)
        self.assertEqual("C+F+G+H", row["variant"])
        self.assertEqual(STRUCTURE_FEATURE_VERSION, row["feature_version"])
        self.assertEqual(f"gated grid ({STRUCTURE_FEATURE_VERSION})", row["strategy"])

    def test_every_part_lets_the_grid_open_once_f_knows_fifteen_minutes(self):
        # Without V0's opportunity gate, which this synthetic market does not pass, as
        # the replay tests of F and G run: F fails closed for the first 15 minutes, and
        # then A (Up), F, G (clear) and H2 (off) all allow the grid, placed under B's cap.
        row = self.job(False)
        self.assertIn("cash: order flow: buys blocked", row["top_reasons_by_bar"])
        self.assertEqual(1, row["grids_opened"])
        self.assertEqual(0, row["funding_gate_blocked_grids"])


# The CLI's pre-run checks, faked: the dataset holds one hour of minutes, which the real
# hourly/minute check fails for the rest of the month. ETHUSDT's own daily check fails, as
# SOLUSDT's P3 presence check does in practice-2022, so its pair-window is excluded.
PAIR_CHECK = {field: 0 for field in (*cli.INTEGRITY_FIELDS, *cli.DAILY_INTEGRITY_FIELDS)}
PAIR_CHECK |= {"hours_compared": 1, "daily_days_compared": 1}
BASKET_CHECK = {"role": "breadth_basket", "series_hours_present": 1, "series_hours_excluded": 0}
BASKET_CHECK |= {field: 0 for field in cli.SERIES_INTEGRITY_FIELDS}
ETH_EXCLUDED = ("ETHUSDT: daily_days_missing=3",)


def checks(spec_path, data_dir, symbol, strict_volume=False, *, config_path=None):
    check = {"symbol": symbol, **(PAIR_CHECK if symbol in TRADED else BASKET_CHECK)}
    if symbol == "ETHUSDT":
        check["daily_days_missing"] = 3
    return check


def no_mask(spec_path, data_dir, symbol):
    """A made-up mask, like the made-up checks (``checks``): None for every symbol, so the
    suite stays on the clean path it was written for. The real ``mask_job`` would mask
    almost the whole evaluation month, since the dataset holds only an hour of minutes."""
    return SymbolMask(symbol, None, ())


class CliToScorerTests(SyntheticDataset):
    """The results.json files the backtest CLI writes for V0 with D, V2 and the full
    stack, read by the acceptance scorer's row recognition and comparison mask."""

    def run_cli(self, *flags):
        out = self.work / "out" / ("".join(flags) or "v0")
        command = ["run", "--spec", str(self.spec_path), "--data-dir", str(self.work / "data")]
        command += ["--config", str(ROOT / "config/default.toml"), "--out", str(out)]
        command += ["--jobs", "1", "--maker-fee", "0", "--taker-fee", "0.0009", *flags]
        with (
            patch.object(cli, "mask_job", no_mask),
            patch.object(cli, "cross_check_job", checks),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(0, cli.main(command))
        (written,) = out.rglob("results.json")
        return score.read_results(written).document

    def test_the_scorer_reads_v0_d_v2_and_the_full_stack_and_the_excluded_pair(self):
        spec = load_spec(self.spec_path)
        windows: dict = {}
        named: dict = {}
        found: dict = {}
        for flags, variants in (
            (("--record-commit", "--trend-benchmark"), {"V0", "D"}),
            (("--structure",), {"V2"}),
            (("--variant-full",), {"C+F+G+H+V2"}),
        ):
            with self.subTest(flags=flags):
                document = self.run_cli(*flags)
                # An acceptance run, valid, with ETHUSDT excluded and not a failure.
                self.assertEqual([], score.document_problems(document))
                self.assertEqual((True, []), (document["valid"], document["failures"]))
                self.assertEqual({"ETHUSDT": list(ETH_EXCLUDED)}, document["excluded_pairs"])
                window = score.window_of(spec, document["hourly_cross_checks"])
                self.assertEqual({"ETHUSDT": ETH_EXCLUDED}, dict(window.excluded))
                self.assertEqual(windows.setdefault(window.name, window), window)
                # Every row is recognised, and only the included pair's rows are runs.
                self.assertEqual(variants, score.variants_in(document))
                runs = list(score.runs_of(document, window))
                expected = {(v, "BTCUSDT", path) for v in variants for path in PATH_MODES}
                self.assertEqual(expected, {(v, r.symbol, r.path) for v, r in runs})
                named.setdefault(window.name, set()).update(variants)
                for variant, run in runs:
                    found.setdefault(variant, {})[run.key] = run
        # Judged over the window, the excluded pair-window is no variant's missing run.
        judged = score.judge(score.Stage("synthetic", (spec.name,)), windows, named, found)
        self.assertEqual(
            {"V0": (), "D": (), "V2": (), "C+F+G+H+V2": ()},
            {s.variant: s.missing for s in judged.scores},
        )


if __name__ == "__main__":
    unittest.main()
