"""Masks reach every consumer, and the checks run on the post-mask expected set.

Long-window data plan, Task 3 (spec v1 section 5: rules 1-5 and "The post-mask expected
set"). ``mask_job`` computes one ``SymbolMask`` per checked symbol; the loaders, the three
cross-checks, ``prepare_run``, the grid replay's minutes and variant D's minutes take it.

* A symbol whose mask is ``None`` (or that the map does not name) loads exactly as today,
  with the strict reader. ``test_no_mask_changes_nothing`` compares every loader and check
  with golden outputs captured from the code before this change (``GOLDEN_*``), never with
  a second call that passes the default.
* A symbol mapped to a set, even an empty one, loads with the repairing reader and drops
  every bar in a masked hour and in a documented exclusion.

Synthetic data only, built through the pinned fetch code from a fake archive: no network,
nothing after 2024-12, and nothing here is market data or evidence.
"""

import hashlib
import math
import pickle
import shutil
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch

import test_backtest_loaders as loaders

from crypto_grid_bot.backtest import trend_benchmark
from crypto_grid_bot.backtest.dataset import (
    fetch_dataset,
    load_manifest,
    load_spec,
    local_path,
    write_manifest,
)
from crypto_grid_bot.backtest.features import FeatureEngine, SeriesFeatures
from crypto_grid_bot.backtest.jobs import (
    SymbolMask,
    cross_check_job,
    mask_job,
    prepare_run,
    run_job,
)
from crypto_grid_bot.backtest.klines import Kline, aggregate
from crypto_grid_bot.backtest.masking import masked_days
from crypto_grid_bot.backtest.replay import (
    check_hourly_series,
    cross_check_daily,
    cross_check_hourly,
    load_candles,
    load_daily,
    load_hourly,
    load_minutes,
)
from crypto_grid_bot.backtest.trend_benchmark import trend_job
from crypto_grid_bot.market_data.parsing import DataError
from crypto_grid_bot.simulation.models import timestamp
from crypto_grid_bot.simulation.runner import PaperSimulator

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/default.toml"
MINUTE_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000


def ms(year, month, day=1, hour=0):
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp() * 1000)


def month_of(open_ms):
    return datetime.fromtimestamp(open_ms / 1000, UTC).strftime("%Y-%m")


def hours_between(start_ms, end_ms):
    return range(start_ms, end_ms, HOUR_MS)


def hour_of(open_ms):
    return open_ms // HOUR_MS * HOUR_MS


def walk(start_ms, count, step, base, seed):
    """``count`` bars from ``start_ms``: a sawtooth around ``base``, exact in Decimal."""
    bars = []
    for i in range(count):
        o = base + D((i * 7 + seed) % 41 - 20) / 100
        c = base + D((i * 7 + seed + 9) % 41 - 20) / 100
        volume = D(15 + (i + seed) % 7) / 10
        high, low = max(o, c) + D("0.05"), min(o, c) - D("0.05")
        bars.append(Kline(start_ms + i * step, o, high, low, c, volume, volume * c, volume / 2))
    return bars


def csv_text(bars, step):
    """Binance's 12-column CSV rows of ``bars``, each closing on its boundary."""
    return "".join(
        f"{k.open_ms},{k.open},{k.high},{k.low},{k.close},{k.volume},{k.open_ms + step - 1},"
        f"{k.quote_volume},10,{k.taker_buy_base},{k.taker_buy_base * k.close},0\n"
        for k in bars
    )


def add_bars(archive, symbol, interval, step, bars):
    """Each month of ``bars`` as Binance's monthly archive of ``symbol`` at ``interval``."""
    months: dict[str, list[Kline]] = {}
    for k in bars:
        months.setdefault(month_of(k.open_ms), []).append(k)
    for month, rows in months.items():
        archive.add(symbol, interval, month, csv_text(rows, step))


def write_local(data_dir, symbol, interval, month, text):
    """Replace a stored archive behind the manifest's back (loaders do not re-hash it)."""
    with zipfile.ZipFile(local_path(data_dir, symbol, interval, month), "w") as archive:
        archive.writestr(f"{symbol}-{interval}-{month}.csv", text)


def digest(bars):
    """Every field of every bar, in order, as (count, short SHA-256)."""
    text = "".join(
        f"{k.open_ms},{k.open},{k.high},{k.low},{k.close},{k.volume},{k.quote_volume},"
        f"{k.taker_buy_base}\n"
        for k in bars
    )
    return len(bars), hashlib.sha256(text.encode()).hexdigest()[:16]


def manifest_of(spec_path):
    return load_manifest(spec_path.with_name(spec_path.stem + ".manifest.json"))


COMMON = """initial_quote = "100"
fee_rate = "0.001"
slippage_rate = "0.0005"
participation = "0.10"
assumed_spread_pct = "0.05"
"""

# --- A clean window: every hour and minute present and consistent ------------------------
# ETHUSDT is traded; BTCUSDT is an untraded market proxy, BNBUSDT an untraded basket member.
CLEAN_SPEC = (
    """name = "clean-window"
purpose = "masked-checks test"
traded = ["ETHUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["ETHUSDT", "BNBUSDT"]
daily_warmup_start = "2022-12"
warmup_start = "2023-01"
start = "2023-02"
end = "2023-02"
"""
    + COMMON
)
DEC_2022, JAN_2023, FEB_2023, MAR_2023 = ms(2022, 12), ms(2023, 1), ms(2023, 2), ms(2023, 3)
CLEAN_SYMBOLS = ("ETHUSDT", "BTCUSDT", "BNBUSDT")
CLEAN_FILTERS = {"base": "X", "quote": "USDT", "tick_size": "0.01"}
CLEAN_FILTERS |= {"quantity_step": "0.0001", "min_notional": "5"}
# The hour whose minutes the second clean build leaves out (2023-02-14T05:00Z).
SKIPPED_HOUR = ms(2023, 2, 14, 5)


def build_clean(work, *, skip_hour=None):
    """The clean window's spec, manifest and archives under ``work``; returns the spec's
    path. ETHUSDT's evaluation hours aggregate its minutes, and every daily bar of the
    hourly window aggregates its hours, so every check passes. ``skip_hour`` leaves that
    hour's minutes out of ETHUSDT's 1m archive."""
    archive = loaders.FakeArchive()
    for seed, (symbol, base) in enumerate(zip(CLEAN_SYMBOLS, (D(100), D(200), D(50)), strict=True)):
        hourly = walk(JAN_2023, (FEB_2023 - JAN_2023) // HOUR_MS, HOUR_MS, base, seed)
        if symbol == "ETHUSDT":
            minutes = walk(FEB_2023, (MAR_2023 - FEB_2023) // MINUTE_MS, MINUTE_MS, base, seed)
            hourly += aggregate(minutes)
            kept = [k for k in minutes if hour_of(k.open_ms) != skip_hour]
            add_bars(archive, symbol, "1m", MINUTE_MS, kept)
        else:
            hourly += walk(FEB_2023, (MAR_2023 - FEB_2023) // HOUR_MS, HOUR_MS, base, seed + 3)
        add_bars(archive, symbol, "1h", HOUR_MS, hourly)
        if symbol != "BNBUSDT":
            days = walk(DEC_2022, 31, DAY_MS, base, seed) + list(aggregate(hourly, DAY_MS))
            add_bars(archive, symbol, "1d", DAY_MS, days)
    spec_path = work / "clean-window.toml"
    spec_path.write_text(CLEAN_SPEC)
    manifest = fetch_dataset(
        load_spec(spec_path),
        work / "data",
        fetcher=archive,
        instruments=lambda symbol: CLEAN_FILTERS,
    )
    write_manifest(work / "clean-window.manifest.json", manifest)
    return spec_path


# --- A window around DOGEUSDT 2020-02, a documented basket absence ------------------------
RUN_SPEC = (
    """name = "doge-window"
purpose = "masked-consumers test"
traded = ["BTCUSDT", "ETHUSDT"]
market_proxy = "BTCUSDT"
breadth_basket = ["ETHUSDT", "BNBUSDT", "DOGEUSDT"]
daily_warmup_start = "2020-01"
warmup_start = "2020-01"
start = "2020-03"
end = "2020-03"
"""
    + COMMON
    + """
[[basket_exclusions]]
symbol = "DOGEUSDT"
from = "2020-02-01T00:00Z"
to = "2020-03-01T00:00Z"
reason = "synthetic: DOGEUSDT 2020-02, which the repair rule cannot rescue"
"""
)
JAN_2020, FEB_2020, MAR_2020, APR_2020 = ms(2020, 1), ms(2020, 2), ms(2020, 3), ms(2020, 4)
RUN_TRADED = ("BTCUSDT", "ETHUSDT")
RUN_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "DOGEUSDT")
RUN_FILTERS = {"base": "X", "quote": "USDT", "tick_size": "0.0001"}
RUN_FILTERS |= {"quantity_step": "0.1", "min_notional": "5"}
RUN_HOURS = hours_between(JAN_2020, APR_2020)
DOGE_EXCLUDED = set(hours_between(FEB_2020, MAR_2020))
EVALUATION_MINUTES = 480  # the first eight hours of 2020-03, for both traded pairs
# DOGEUSDT 2020-02's repaired row: its close is cut short of the boundary.
DOGE_REPAIRED_HOUR = ms(2020, 2, 10, 5)


def sine_bar(open_ms, o, h, low, c):
    o, h, low, c = (D(str(round(x, 6))) for x in (o, h, low, c))
    return Kline(open_ms, o, h, low, c, D(10**6), D(10**6) * c, D(5 * 10**5))


def sine_hours():
    """A daily sine wave around 1.0 (``test_full_stack.hours``'s phase, in which grids open
    at the evaluation start), over every hour of 2020-01 to 2020-03."""
    candles, previous = [], 1.0
    for i, open_ms in enumerate(RUN_HOURS):
        close = 1.0 + 0.08 * math.sin(2 * math.pi * (i + 8) / 24)
        high, low = max(previous, close) * 1.004, min(previous, close) * 0.996
        candles.append(sine_bar(open_ms, previous, high, low, close))
        previous = close
    return candles


def build_run(work):
    """The DOGEUSDT window's spec, manifest and archives under ``work``; returns the spec's
    path. Every symbol has the same complete hours; the traded pairs' minutes oscillate 3%
    around the fair value for eight hours, so the ungated V0 grid fills in each of them."""
    hourly = sine_hours()
    engine = FeatureEngine(
        SeriesFeatures("BTCUSDT", hourly),
        SeriesFeatures("BTCUSDT", hourly),
        [SeriesFeatures(f"B{i}USDT", hourly, full=False) for i in range(5)],
        range_atr_multiple=2.0,
        levels=8,
        minimum_cost_multiple=3.0,
        round_trip_cost=0.0035,
    )
    fair = float(engine.at(MAR_2020).fair_value)
    minutes = []
    for i in range(EVALUATION_MINUTES):
        mid = fair * (1 + 0.03 * math.sin(2 * math.pi * i / 90))
        minutes.append(sine_bar(MAR_2020 + i * MINUTE_MS, mid, mid * 1.003, mid * 0.997, mid))
    archive = loaders.FakeArchive()
    for symbol in RUN_SYMBOLS:
        add_bars(archive, symbol, "1h", HOUR_MS, hourly)
    for symbol in RUN_TRADED:
        add_bars(archive, symbol, "1m", MINUTE_MS, minutes)
        add_bars(archive, symbol, "1d", DAY_MS, aggregate(hourly, DAY_MS))
    spec_path = work / "doge-window.toml"
    spec_path.write_text(RUN_SPEC)
    manifest = fetch_dataset(
        load_spec(spec_path),
        work / "data",
        fetcher=archive,
        instruments=lambda symbol: RUN_FILTERS,
    )
    write_manifest(work / "doge-window.manifest.json", manifest)
    return spec_path


# --- Function-level fixtures with every kind of failure, one hour or day each -------------
T0 = ms(2024, 1, 1)


def dirty_hourly_inputs():
    """Minutes and hours over [T0, T0 + 8 h): hour 0 and 7 match; 1 lacks a minute; 2's
    close and 3's volume (within the drift tolerance) differ from the minutes; 4 has no
    minutes, 5 nothing, and 6 minutes but no hour."""
    minutes, hours = [], []
    for h in range(8):
        bars = walk(T0 + h * HOUR_MS, 60, MINUTE_MS, D(100), h)
        (official,) = aggregate(bars)
        if h == 1:
            bars = bars[:30] + bars[31:]
        if h == 2:
            official = replace(official, close=official.close + D("0.01"))
        if h == 3:
            official = replace(official, volume=official.volume * D("1.0005"))
        if h not in (4, 5):
            minutes += bars
        if h not in (5, 6):
            hours.append(official)
    return minutes, hours, (T0, T0 + 8 * HOUR_MS)


def dirty_daily_inputs():
    """Hours of four days from T0 and daily bars from two days before: day 0 matches; day 1
    lacks an hour; day 2's daily bar differs; day 3 has no daily bar; day 0's bar is listed
    twice; and of the two days before, the second has no bar."""
    hours, daily = [], [walk(T0 - 2 * DAY_MS, 1, DAY_MS, D(100), 0)[0]]
    for day in range(4):
        bars = walk(T0 + day * DAY_MS, 24, HOUR_MS, D(100), day)
        (merged,) = aggregate(bars, DAY_MS)
        if day == 1:
            bars = bars[:5] + bars[6:]
        if day == 2:
            merged = replace(merged, high=merged.high + D(1))
        hours += bars
        if day != 3:
            daily.append(merged)
        if day == 0:
            daily.append(merged)
    return daily, hours, (T0 - 2 * DAY_MS, T0 + 4 * DAY_MS), (T0, T0 + 4 * DAY_MS)


def dirty_series_inputs():
    """Hours over [T0, T0 + 6 h): 0, 1 twice, 3 and 5 present; 4 documented as excluded."""
    bars = walk(T0, 6, HOUR_MS, D(100), 0)
    series = [bars[0], bars[1], bars[1], bars[3], bars[5]]
    return series, (T0, T0 + 6 * HOUR_MS), [(T0 + 4 * HOUR_MS, T0 + 5 * HOUR_MS)]


# --- Golden outputs, captured from the code before this change (fa432f7) -----------------
# Built on test_backtest_loaders.LoaderTests.setUp's fixture: editing that fixture moves these.
GOLDEN_LOADERS = {
    "minutes BTCUSDT": (6, "108b9ced82b70fb8"),
    "minutes ETHUSDT": (5, "2e0626693f767bb2"),
    "hourly BTCUSDT": (4, "235eecffb1397113"),
    "daily BTCUSDT": (4, "8b366f4603678383"),
    "candles 1m BTCUSDT": (6, "108b9ced82b70fb8"),
    "candles 1h XRPUSDT": (0, "e3b0c44298fc1c14"),
}
GOLDEN_CLEAN_LOADS = {
    "minutes ETHUSDT": (40320, "475476a197147200"),
    "hourly ETHUSDT": (1416, "aa242c5add7355f7"),
    "hourly BTCUSDT": (1416, "864580b75fc1578c"),
    "hourly BNBUSDT": (1416, "82653f2cd77b828e"),
    "daily ETHUSDT": (90, "ff7ca0b1b6b7c5ee"),
    "daily BTCUSDT": (90, "ad2fd79305063968"),
}
GOLDEN_CLEAN_CHECKS = {
    "ETHUSDT": {
        "symbol": "ETHUSDT",
        "hours_compared": 672,
        "hours_mismatched": 0,
        "hours_volume_drift": 0,
        "hours_missing": 0,
        "hours_absent_from_minutes": 0,
        "hours_absent_from_both": 0,
        "hours_incomplete": 0,
        "minutes_missing": 0,
        "daily_days_compared": 59,
        "daily_days_mismatched": 0,
        "daily_days_volume_drift": 0,
        "daily_days_missing": 0,
        "daily_days_duplicated": 0,
        "daily_days_hours_incomplete": 0,
        "daily_warmup_days": 62,
        "daily_warmup_short": 1,
    },
    "BTCUSDT": {
        "symbol": "BTCUSDT",
        "role": "market_proxy",
        "series_hours_present": 1416,
        "series_hours_missing": 0,
        "series_hours_duplicated": 0,
        "series_hours_excluded": 0,
        "daily_days_compared": 59,
        "daily_days_mismatched": 0,
        "daily_days_volume_drift": 0,
        "daily_days_missing": 0,
        "daily_days_duplicated": 0,
        "daily_days_hours_incomplete": 0,
        "daily_warmup_days": 62,
        "daily_warmup_short": 1,
    },
    "BNBUSDT": {
        "symbol": "BNBUSDT",
        "role": "breadth_basket",
        "series_hours_present": 1416,
        "series_hours_missing": 0,
        "series_hours_duplicated": 0,
        "series_hours_excluded": 0,
    },
}
GOLDEN_DIRTY = {
    "hourly": {
        "hours_compared": 5,
        "hours_mismatched": 2,
        "hours_volume_drift": 1,
        "hours_missing": 1,
        "hours_absent_from_minutes": 1,
        "hours_absent_from_both": 1,
        "hours_incomplete": 1,
        "minutes_missing": 1,
    },
    "hourly strict": {
        "hours_compared": 5,
        "hours_mismatched": 3,
        "hours_volume_drift": 0,
        "hours_missing": 1,
        "hours_absent_from_minutes": 1,
        "hours_absent_from_both": 1,
        "hours_incomplete": 1,
        "minutes_missing": 1,
    },
    "daily": {
        "daily_days_compared": 2,
        "daily_days_mismatched": 1,
        "daily_days_volume_drift": 0,
        "daily_days_missing": 2,
        "daily_days_duplicated": 1,
        "daily_days_hours_incomplete": 1,
        "daily_warmup_days": 1,
        "daily_warmup_short": 1,
    },
    "daily strict": {
        "daily_days_compared": 2,
        "daily_days_mismatched": 1,
        "daily_days_volume_drift": 0,
        "daily_days_missing": 2,
        "daily_days_duplicated": 1,
        "daily_days_hours_incomplete": 1,
        "daily_warmup_days": 3,
        "daily_warmup_short": 1,
    },
    "series": {
        "series_hours_present": 4,
        "series_hours_missing": 1,
        "series_hours_duplicated": 1,
        "series_hours_excluded": 1,
    },
    "series without exclusions": {
        "series_hours_present": 4,
        "series_hours_missing": 2,
        "series_hours_duplicated": 1,
        "series_hours_excluded": 0,
    },
}
# Owner decision 14 (2026-10-07) adds one key to a daily record with a mismatch: the
# mismatched days by name. The dirty fixture's is day 2. Every captured key and value
# above stands; a record with no mismatch, as every clean one, gains nothing.
NAMED_MISMATCH = {"daily_mismatched_days": ["2024-01-03"]}
DIRTY_NOW = GOLDEN_DIRTY | {
    name: GOLDEN_DIRTY[name] | NAMED_MISMATCH for name in ("daily", "daily strict")
}


def loader_fixture(test):
    """``test_backtest_loaders``' own fixture: two months of BTCUSDT and ETHUSDT archives,
    a missing month, and a manifest in a shuffled order."""
    fixture = loaders.LoaderTests()
    fixture.setUp()
    test.addCleanup(fixture.tearDown)
    return fixture.data, fixture.manifest


def loader_outputs(data, manifest):
    """Every loader's output on ``test_backtest_loaders``' fixture, with no mask."""
    return {
        "minutes BTCUSDT": digest(list(load_minutes(data, manifest, "BTCUSDT"))),
        "minutes ETHUSDT": digest(list(load_minutes(data, manifest, "ETHUSDT"))),
        "hourly BTCUSDT": digest(load_hourly(data, manifest, "BTCUSDT")),
        "daily BTCUSDT": digest(load_daily(data, manifest, "BTCUSDT")),
        "candles 1m BTCUSDT": digest(load_candles(data, manifest, "BTCUSDT", "1m")),
        "candles 1h XRPUSDT": digest(load_candles(data, manifest, "XRPUSDT", "1h")),
    }


def clean_loads(spec_path):
    """Every loader's output on the clean window, with no mask."""
    data, manifest = spec_path.parent / "data", manifest_of(spec_path)
    outputs = {"minutes ETHUSDT": digest(list(load_minutes(data, manifest, "ETHUSDT")))}
    for symbol in CLEAN_SYMBOLS:
        outputs[f"hourly {symbol}"] = digest(load_hourly(data, manifest, symbol))
    for symbol in ("ETHUSDT", "BTCUSDT"):
        outputs[f"daily {symbol}"] = digest(load_daily(data, manifest, symbol))
    return outputs


def dirty_checks():
    """The three checks on the function-level fixtures, with no mask."""
    minutes, hours, window = dirty_hourly_inputs()
    daily, day_hours, daily_window, hourly_window = dirty_daily_inputs()
    series, series_window, excluded = dirty_series_inputs()
    return {
        "hourly": cross_check_hourly(minutes, hours, window),
        "hourly strict": cross_check_hourly(minutes, hours, window, D(0)),
        "daily": cross_check_daily(daily, day_hours, daily_window, hourly_window, T0),
        "daily strict": cross_check_daily(
            daily, day_hours, daily_window, hourly_window, T0 + DAY_MS, D(0)
        ),
        "series": check_hourly_series(series, series_window, excluded),
        "series without exclusions": check_hourly_series(series, series_window),
    }


class NoMaskTests(unittest.TestCase):
    """With no mask, every loader and check gives exactly what it gave before masks."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.spec_path = build_clean(Path(cls.temp.name))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_no_mask_changes_nothing(self):
        data, manifest = loader_fixture(self)
        self.assertEqual(GOLDEN_LOADERS, loader_outputs(data, manifest))
        self.assertEqual(GOLDEN_CLEAN_LOADS, clean_loads(self.spec_path))
        self.assertEqual(DIRTY_NOW, dirty_checks())
        # Passing None, or an empty set of masked hours to a check, is still no mask.
        clean_data, clean_manifest = self.spec_path.parent / "data", manifest_of(self.spec_path)
        self.assertEqual(
            GOLDEN_CLEAN_LOADS["minutes ETHUSDT"],
            digest(list(load_minutes(clean_data, clean_manifest, "ETHUSDT", mask=None))),
        )
        self.assertEqual(
            GOLDEN_CLEAN_LOADS["hourly BTCUSDT"],
            digest(load_candles(clean_data, clean_manifest, "BTCUSDT", "1h", mask=None)),
        )
        minutes, hours, window = dirty_hourly_inputs()
        self.assertEqual(
            GOLDEN_DIRTY["hourly"],
            cross_check_hourly(minutes, hours, window, masked=frozenset()),
        )
        daily, day_hours, daily_window, hourly_window = dirty_daily_inputs()
        self.assertEqual(
            DIRTY_NOW["daily"],
            cross_check_daily(
                daily, day_hours, daily_window, hourly_window, T0, masked_days=frozenset()
            ),
        )
        series, series_window, excluded = dirty_series_inputs()
        self.assertEqual(
            GOLDEN_DIRTY["series"],
            check_hourly_series(series, series_window, excluded, masked=frozenset()),
        )
        # On a clean window every symbol's mask is None, and each cross-check record, run
        # with that mask, equals today's, keys and values.
        for symbol in CLEAN_SYMBOLS:
            with self.subTest(symbol=symbol):
                symbol_mask = mask_job(self.spec_path, clean_data, symbol)
                self.assertIsInstance(symbol_mask, SymbolMask)
                self.assertEqual(symbol, symbol_mask.symbol)
                self.assertIsNone(symbol_mask.mask)
                self.assertEqual(["2023-01", "2023-02"], [m.month for m in symbol_mask.months])
                self.assertFalse(any(m.masked or m.excluded for m in symbol_mask.months))
                golden = GOLDEN_CLEAN_CHECKS[symbol]
                self.assertEqual(golden, cross_check_job(self.spec_path, clean_data, symbol))
                record = cross_check_job(self.spec_path, clean_data, symbol, mask=symbol_mask.mask)
                self.assertEqual(list(golden), list(record))
                self.assertEqual(golden, record)


class MaskedChecksTests(unittest.TestCase):
    """The checks with masked hours: those hours leave the expected set."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.spec_path = build_clean(Path(cls.temp.name), skip_hour=SKIPPED_HOUR)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_masked_hour_leaves_the_expected_set(self):
        # The functions: every failing hour of the fixture masked, so only hours 0 and 7
        # are expected, and both match.
        minutes, hours, window = dirty_hourly_inputs()
        masked = frozenset(T0 + h * HOUR_MS for h in range(1, 7))
        self.assertEqual(
            {
                "hours_compared": 2,
                "hours_mismatched": 0,
                "hours_volume_drift": 0,
                "hours_missing": 0,
                "hours_absent_from_minutes": 0,
                "hours_absent_from_both": 0,
                "hours_incomplete": 0,
                "minutes_missing": 0,
            },
            cross_check_hourly(minutes, hours, window, masked=masked),
        )
        # Masking only the hour with no minutes removes only its failure.
        only = cross_check_hourly(minutes, hours, window, masked=frozenset({T0 + 4 * HOUR_MS}))
        self.assertEqual({**GOLDEN_DIRTY["hourly"], "hours_absent_from_minutes": 0}, only)
        series, series_window, excluded = dirty_series_inputs()
        masked_series = frozenset({T0 + HOUR_MS, T0 + 2 * HOUR_MS})  # the duplicate, the gap
        self.assertEqual(
            {
                "series_hours_present": 3,
                "series_hours_missing": 0,
                "series_hours_duplicated": 0,
                "series_hours_excluded": 1,
            },
            check_hourly_series(series, series_window, excluded, masked=masked_series),
        )
        # The job: ETHUSDT's hour with no minutes is masked (rule 2), and its record, run
        # on the post-mask expected set, fails nothing: it is the clean record less that
        # hour, and less its day in the daily check, which counts the skip.
        data = self.spec_path.parent / "data"
        symbol_mask = mask_job(self.spec_path, data, "ETHUSDT")
        self.assertEqual(frozenset({SKIPPED_HOUR}), symbol_mask.mask)
        unmasked = cross_check_job(self.spec_path, data, "ETHUSDT")
        self.assertEqual(1, unmasked["hours_absent_from_minutes"])
        clean = GOLDEN_CLEAN_CHECKS["ETHUSDT"]
        expected = {
            **clean,
            "hours_compared": clean["hours_compared"] - 1,
            "daily_days_compared": clean["daily_days_compared"] - 1,
            "daily_days_skipped_for_masks": 1,
        }
        record = cross_check_job(self.spec_path, data, "ETHUSDT", mask=symbol_mask.mask)
        self.assertEqual(expected, record)
        # The other symbols are clean, and their records stay today's.
        for symbol in ("BTCUSDT", "BNBUSDT"):
            self.assertIsNone(mask_job(self.spec_path, data, symbol).mask)

    def test_daily_check_skips_and_counts_masked_days(self):
        daily, hours, daily_window, hourly_window = dirty_daily_inputs()
        days = masked_days({T0 + DAY_MS + 5 * HOUR_MS, T0 + 2 * DAY_MS + 7 * HOUR_MS})
        self.assertEqual(frozenset({T0 + DAY_MS, T0 + 2 * DAY_MS}), days)
        result = cross_check_daily(daily, hours, daily_window, hourly_window, T0, masked_days=days)
        # Days 1 (an hour short) and 2 (a differing bar) are skipped and counted; day 3's
        # missing bar and day 0's duplicate stay failures, since daily bars are never masked.
        self.assertEqual(
            {
                **GOLDEN_DIRTY["daily"],
                "daily_days_compared": 1,
                "daily_days_mismatched": 0,
                "daily_days_hours_incomplete": 0,
                "daily_days_skipped_for_masks": 2,
            },
            result,
        )
        # A masked day outside the hourly window is not compared, so it is not counted.
        outside = cross_check_daily(
            daily, hours, daily_window, hourly_window, T0, masked_days={T0 - DAY_MS}
        )
        self.assertEqual(DIRTY_NOW["daily"], outside)
        # In a run, the official 1d bar of a masked day stays in use: the daily bars are
        # read whole, whatever the pair's mask (A's SMA refuses gaps).
        data, manifest = self.spec_path.parent / "data", manifest_of(self.spec_path)
        masks = {"ETHUSDT": frozenset({SKIPPED_HOUR})}
        prepared = prepare_run(
            self.spec_path, CONFIG, data, "ETHUSDT", "high_first", False, masks=masks
        )
        whole = load_daily(data, manifest, "ETHUSDT")
        self.assertEqual(whole, prepared.daily)
        self.assertIn(SKIPPED_HOUR // DAY_MS * DAY_MS, [k.open_ms for k in prepared.daily])
        self.assertNotIn(SKIPPED_HOUR, [k.open_ms for k in prepared.hourly])


class RunDataset(unittest.TestCase):
    """The DOGEUSDT window, built once for the class."""

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.spec_path = build_run(Path(cls.temp.name))
        cls.data = cls.spec_path.parent / "data"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()


# Masked hours of every kind: warm-up hours of each symbol, and an evaluation hour (with
# minutes) of each traded pair.
MASKS = {
    "BTCUSDT": frozenset({ms(2020, 2, 10, 5), MAR_2020 + 2 * HOUR_MS}),
    "ETHUSDT": frozenset({ms(2020, 1, 20, 7), MAR_2020 + HOUR_MS}),
    "BNBUSDT": frozenset({ms(2020, 1, 25, 3)}),
    "DOGEUSDT": frozenset({ms(2020, 1, 15, 9)}),
}


def expected_opens(symbol, masks):
    """The hours a symbol's series keeps under ``masks``: all, less its masked hours and,
    once it has a mask, its documented exclusion."""
    mask = masks.get(symbol)
    if mask is None:
        return list(RUN_HOURS)
    excluded = DOGE_EXCLUDED if symbol == "DOGEUSDT" else set()
    return [h for h in RUN_HOURS if h not in mask and h not in excluded]


class MaskedConsumersTests(RunDataset):
    def test_masks_reach_the_proxy_the_basket_and_variant_d(self):
        # Review Focus 3, on the grid runs: every pair's features read its own series, the
        # proxy's and every basket member's, each post-mask, and so does variant E.
        for masks in ({}, MASKS):
            for pair in RUN_TRADED:
                with self.subTest(pair=pair, masked=bool(masks)):
                    prepared = prepare_run(
                        self.spec_path, CONFIG, self.data, pair, "high_first", False, masks=masks
                    )
                    features = prepared.features
                    self.assertEqual(expected_opens(pair, masks), features.pair.opens)
                    self.assertEqual(expected_opens("BTCUSDT", masks), features.market.opens)
                    self.assertEqual(
                        [expected_opens(s, masks) for s in ("ETHUSDT", "BNBUSDT", "DOGEUSDT")],
                        [series.opens for series in features.basket],
                    )
                    self.assertEqual(features.pair.opens, [k.open_ms for k in prepared.hourly])
        # Variant D loads no basket (trend_job's prepare_run has basket=False): its minutes
        # and its warm-up gate, which reads the pair and the proxy, are post-mask.
        seen = {}
        real = trend_benchmark.replay_trend

        def capture(run, minutes, closes, warmed, **reported):
            minutes = list(minutes)
            seen["minutes"], seen["gate"] = [k.open_ms for k in minutes], warmed.__self__
            return real(run, minutes, closes, warmed, **reported)

        for pair in RUN_TRADED:
            with self.subTest(variant="D", pair=pair):
                with patch.object(trend_benchmark, "replay_trend", capture):
                    row = trend_job(
                        self.spec_path, CONFIG, self.data, pair, "high_first", masks=MASKS
                    )
                self.assertEqual([], row["accounting_problems"])
                evaluation = {h for h in MASKS[pair] if h >= MAR_2020}
                self.assertEqual(
                    [
                        MAR_2020 + i * MINUTE_MS
                        for i in range(EVALUATION_MINUTES)
                        if hour_of(MAR_2020 + i * MINUTE_MS) not in evaluation
                    ],
                    seen["minutes"],
                )
                self.assertEqual(expected_opens(pair, MASKS), seen["gate"].pair.opens)
                self.assertEqual(expected_opens("BTCUSDT", MASKS), seen["gate"].market.opens)
                self.assertEqual((), seen["gate"].basket)

    def test_grid_run_omits_masked_minutes(self):
        masked_hour = MAR_2020 + 3 * HOUR_MS

        def traced(masks):
            quotes, fills = [], []
            real = PaperSimulator.step

            def step(simulator, account, frame):
                report = real(simulator, account, frame)
                at = int(timestamp(frame.quote.observed_at).timestamp() * 1000)
                quotes.append(at)
                fills.extend(at for _ in report["fills"])
                return report

            with patch.object(PaperSimulator, "step", step):
                row = run_job(
                    self.spec_path,
                    CONFIG,
                    self.data,
                    "ETHUSDT",
                    "high_first",
                    False,
                    masks=masks,
                )
            self.assertEqual([], row["accounting_problems"])
            inside = range(masked_hour, masked_hour + HOUR_MS)
            return row, [q for q in quotes if q in inside], [f for f in fills if f in inside]

        row, quotes, fills = traced(None)
        self.assertEqual(4 * 60, len(quotes))
        self.assertTrue(fills, "the unmasked V0 run fills inside the hour")
        masked_row, masked_quotes, masked_fills = traced({"ETHUSDT": frozenset({masked_hour})})
        self.assertEqual(([], []), (masked_quotes, masked_fills))
        self.assertEqual(row["bars"] - 60, masked_row["bars"])

    def test_documented_exclusion_bars_are_dropped_with_a_mask(self):
        manifest = manifest_of(self.spec_path)
        excluded = [(FEB_2020, MAR_2020)]
        # mask=None: DOGEUSDT's clean 2020-02 archive loads whole, as today, exclusion or
        # not, and mask_job finds nothing to mask (2020-02 has no expected hour).
        whole = [k.open_ms for k in load_hourly(self.data, manifest, "DOGEUSDT")]
        self.assertEqual(list(RUN_HOURS), whole)
        self.assertEqual(
            whole,
            [
                k.open_ms
                for k in load_hourly(self.data, manifest, "DOGEUSDT", mask=None, excluded=excluded)
            ],
        )
        clean = mask_job(self.spec_path, self.data, "DOGEUSDT")
        self.assertIsNone(clean.mask)
        for pair in RUN_TRADED:
            prepared = prepare_run(self.spec_path, CONFIG, self.data, pair, "high_first", False)
            self.assertEqual(whole, prepared.features.basket[2].opens)
        # A repaired row in 2020-02: the strict reader refuses the archive, so only a
        # caller with a mask can read it. February counts no masked hour, the mask is the
        # empty set, not None, and with it every DOGEUSDT bar of 2020-02, the repaired
        # hour's included, is absent from every pair's breadth series.
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            shutil.copytree(self.data, work / "data")
            shutil.copy(self.spec_path, work / self.spec_path.name)
            write_manifest(work / "doge-window.manifest.json", manifest)
            spec_path, data = work / self.spec_path.name, work / "data"
            rows = sine_hours()
            february = [k for k in rows if month_of(k.open_ms) == "2020-02"]
            lines = csv_text(february, HOUR_MS).splitlines()
            index = (DOGE_REPAIRED_HOUR - FEB_2020) // HOUR_MS
            fields = lines[index].split(",")
            fields[6] = str(DOGE_REPAIRED_HOUR + HOUR_MS - 1000)  # cut short of the boundary
            lines[index] = ",".join(fields)
            write_local(data, "DOGEUSDT", "1h", "2020-02", "\n".join(lines) + "\n")
            with self.assertRaises(DataError):
                load_hourly(data, manifest, "DOGEUSDT")
            symbol_mask = mask_job(spec_path, data, "DOGEUSDT")
            self.assertEqual(frozenset(), symbol_mask.mask)
            (february_mask,) = [m for m in symbol_mask.months if m.month == "2020-02"]
            self.assertEqual(
                (frozenset(), frozenset()), (february_mask.expected, february_mask.masked)
            )
            self.assertFalse(february_mask.excluded)
            masks = {"DOGEUSDT": symbol_mask.mask}
            for pair in RUN_TRADED:
                with self.subTest(pair=pair):
                    prepared = prepare_run(
                        spec_path, CONFIG, data, pair, "high_first", False, masks=masks
                    )
                    doge = prepared.features.basket[2]
                    self.assertEqual("DOGEUSDT", doge.symbol)
                    self.assertEqual(expected_opens("DOGEUSDT", masks), doge.opens)
                    self.assertNotIn(DOGE_REPAIRED_HOUR, doge.opens)
            # Its check counts the exclusion and fails nothing.
            record = cross_check_job(spec_path, data, "DOGEUSDT", mask=symbol_mask.mask)
            self.assertEqual(
                {
                    "symbol": "DOGEUSDT",
                    "role": "breadth_basket",
                    "series_hours_present": len(RUN_HOURS) - len(DOGE_EXCLUDED),
                    "series_hours_missing": 0,
                    "series_hours_duplicated": 0,
                    "series_hours_excluded": len(DOGE_EXCLUDED),
                },
                record,
            )

    def test_mask_job_decides_none_from_the_reads(self):
        # Controller ruling 2: a month the manifest lists as missing gives no read; its
        # expected hours are masked and the 17% rule excludes it. The result crosses a
        # process pool, so it pickles.
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            shutil.copy(self.spec_path, work / self.spec_path.name)
            manifest = manifest_of(self.spec_path)
            for entry in manifest["files"]:
                if (entry["symbol"], entry["interval"], entry["month"]) == (
                    "BNBUSDT",
                    "1h",
                    "2020-01",
                ):
                    entry["status"] = "missing"
            write_manifest(work / "doge-window.manifest.json", manifest)
            symbol_mask = mask_job(work / self.spec_path.name, self.data, "BNBUSDT")
        january = frozenset(hours_between(JAN_2020, FEB_2020))
        self.assertEqual(january, symbol_mask.mask)
        self.assertEqual(
            [("2020-01", True), ("2020-02", False), ("2020-03", False)],
            [(m.month, m.excluded) for m in symbol_mask.months],
        )
        self.assertEqual(symbol_mask, pickle.loads(pickle.dumps(symbol_mask)))

    def test_an_ok_archive_that_is_unreadable_masks_its_month_and_its_check_raises(self):
        # Decision 5: the manifest lists BNBUSDT 1h 2020-01 as ok, but the stored zip holds
        # two members, so the repairing reader calls it unreadable. mask_job counts it as
        # not clean (no bars: January is masked and excluded); the cross-check that then
        # loads it with that mask fails closed.
        with tempfile.TemporaryDirectory() as temp:
            work = Path(temp)
            shutil.copytree(self.data, work / "data")
            shutil.copy(self.spec_path, work / self.spec_path.name)
            write_manifest(work / "doge-window.manifest.json", manifest_of(self.spec_path))
            spec_path, data = work / self.spec_path.name, work / "data"
            with zipfile.ZipFile(local_path(data, "BNBUSDT", "1h", "2020-01"), "w") as archive:
                archive.writestr("BNBUSDT-1h-2020-01.csv", "")
                archive.writestr("extra.csv", "")
            symbol_mask = mask_job(spec_path, data, "BNBUSDT")
            self.assertEqual(frozenset(hours_between(JAN_2020, FEB_2020)), symbol_mask.mask)
            self.assertTrue(symbol_mask.months[0].excluded)
            with self.assertRaises(DataError):
                cross_check_job(spec_path, data, "BNBUSDT", mask=symbol_mask.mask)


class UnreadableArchiveTests(unittest.TestCase):
    def test_ok_archive_that_is_unreadable_still_raises(self):
        # Fail-closed, as today: the manifest lists the archive as ok, so a masked load
        # that cannot read it raises DataError instead of masking its hours. Only a
        # manifest status other than ok gives no bars.
        data, manifest = loader_fixture(self)
        local_path(data, "BTCUSDT", "1h", "2024-02").write_bytes(b"not a zip")
        for mask in (None, frozenset()):
            with self.subTest(mask=mask), self.assertRaises(DataError):
                load_hourly(data, manifest, "BTCUSDT", mask=mask)
        local_path(data, "BTCUSDT", "1m", "2024-02").write_bytes(b"not a zip")
        with self.assertRaises(DataError):
            list(load_minutes(data, manifest, "BTCUSDT", mask=frozenset()))
        # A member whose deflate stream is garbage: the repairing reader calls it
        # unreadable, and the masked load still raises.
        name = "ETHUSDT-1m-2024-01.csv"
        path = local_path(data, "ETHUSDT", "1m", "2024-01")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr(name, b"\x01\x00\x00\x00\x00")
        raw = bytearray(path.read_bytes())
        deflate = zipfile.ZIP_DEFLATED.to_bytes(2, "little")
        raw[8:10] = deflate
        central = raw.rfind(b"PK\x01\x02")
        raw[central + 10 : central + 12] = deflate
        path.write_bytes(raw)
        with self.assertRaises(DataError):
            list(load_minutes(data, manifest, "ETHUSDT", mask=frozenset()))
        # A missing file still raises as it does today.
        local_path(data, "BTCUSDT", "1m", "2024-01").unlink()
        with self.assertRaises(OSError):
            list(load_minutes(data, manifest, "BTCUSDT", mask=frozenset()))

    def test_a_masked_load_drops_the_readers_untrusted_hours(self):
        # A hand-made mask that omits an untrusted hour: the reader keeps one copy of a
        # duplicated row, and the masked load still drops that hour. The strict reader
        # refuses the archive.
        data, manifest = loader_fixture(self)
        rows = loaders.hour_rows(loaders.JAN_2024_MS, 2).splitlines()
        write_local(data, "BTCUSDT", "1h", "2024-01", "\n".join([rows[0], *rows]) + "\n")
        with self.assertRaises(DataError):
            load_hourly(data, manifest, "BTCUSDT")
        opens = [k.open_ms for k in load_hourly(data, manifest, "BTCUSDT", mask=frozenset())]
        feb = loaders.FEB_2024_MS
        self.assertEqual([loaders.JAN_2024_MS + HOUR_MS, feb, feb + HOUR_MS], opens)


if __name__ == "__main__":
    unittest.main()
