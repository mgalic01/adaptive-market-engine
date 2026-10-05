"""The full stack C+F+G+H+V2 (spec v1 §3, test-plan amendment of 2026-10-05) end to end.

A synthetic dataset is fetched from a fake archive by the pinned fetch code, with
BTCUSDT's funding archives in its manifest, and the backtest's own pool job replays it
with every part on: A and B (together C), F, G, H and the V2 structure features.
Nothing here is market data or evidence.
"""

import hashlib
import io
import math
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path

from test_backtest_loaders import FakeArchive

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
from crypto_grid_bot.backtest.jobs import run_job, variant_policy
from crypto_grid_bot.backtest.klines import Kline

ROOT = Path(__file__).resolve().parents[1]
MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
MAY_2023_MS = 1682899200000  # 2023-05-01T00:00:00Z, the daily warm-up start
DEC_2023_MS = 1701388800000  # 2023-12-01T00:00:00Z, the hourly warm-up start
JAN_2024_MS = 1704067200000  # 2024-01-01T00:00:00Z, the evaluation start
SPEC = """name = "full-stack"
purpose = "full-stack wiring test"
traded = ["BTCUSDT"]
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


class FullStackJobTests(unittest.TestCase):
    """The pool job on one synthetic dataset, built once for the class."""

    @classmethod
    def setUpClass(cls):
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
            bar(JAN_2024_MS + i * MINUTE_MS, fair, fair * 1.001, fair * 0.999, fair)
            for i in range(60)
        ]
        # Rising daily closes from 2023-05-01, 245 of them before the evaluation, so A is
        # Up. In 2024-01 the phase is 43 months, in H3's band, not H2's; the halving's bar
        # is not among the closes, so H3's all-time high is unavailable and it never acts.
        days = [
            bar(MAY_2023_MS + i * DAY_MS, *(0.5 + i / 500 + d for d in (0, 0.01, -0.01, 0)))
            for i in range(245)
        ]
        archive = FakeArchive()
        add_klines(archive, "BTCUSDT", "1m", MINUTE_MS, minutes)
        add_klines(archive, "BTCUSDT", "1d", DAY_MS, days)
        # The basket votes with the pair's hours, so breadth is as good as the pair's.
        for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT"):
            add_klines(archive, symbol, "1h", HOUR_MS, hourly)
        # G's settlements up to the evaluation start, so it is available from the start.
        funding = [add_funding(archive, DEC_2023_MS, 93), add_funding(archive, JAN_2024_MS, 1)]
        filters = {"base": "BTC", "quote": "USDT", "tick_size": "0.0001"}
        filters |= {"quantity_step": "0.1", "min_notional": "5"}
        cls.temp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.temp.name)
        cls.spec_path = cls.work / "full-stack.toml"
        cls.spec_path.write_text(SPEC)
        manifest = fetch_dataset(
            load_spec(cls.spec_path),
            cls.work / "data",
            fetcher=archive,
            instruments=lambda symbol: filters,
            previous={"files": funding},
        )
        write_manifest(cls.work / "full-stack.manifest.json", manifest)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def job(self, gated):
        row = run_job(
            self.spec_path,
            ROOT / "config/default.toml",
            self.work / "data",
            "BTCUSDT",
            "high_first",
            gated,
            (D("0"), D("0.0009")),
            variant_policy("C+F+G+H", structure=True),
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


if __name__ == "__main__":
    unittest.main()
