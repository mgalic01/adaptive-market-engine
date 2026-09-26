"""Archive loaders and exchange rules used by every replay (Bob's test audit, PR #51).

``load_minutes``, ``load_hourly``, ``load_daily`` and ``rules_for`` were never called by
the suite. They feed every backtest bar and every order's rounding, so they are tested
here with real, hash-checked zips written by ``fetch_file``.
"""

import hashlib
import io
import tempfile
import unittest
import zipfile
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.dataset import archive_path, fetch_file, local_path
from crypto_grid_bot.backtest.replay import load_daily, load_hourly, load_minutes, rules_for
from crypto_grid_bot.market_data.parsing import DataError

JAN_2024_MS = 1704067200000  # 2024-01-01T00:00:00Z
FEB_2024_MS = 1706745600000  # 2024-02-01T00:00:00Z
HOUR_MS = 3_600_000
DAY_MS = 86_400_000


def row(open_ms, *, step=60_000):
    return ",".join(
        [str(open_ms), "1.0", "1.2", "0.9", "1.1", "10", str(open_ms + step - 1)]
        + ["11", "5", "4", "4.4", "0"]
    )


def minute_rows(start_ms, count):
    return "\n".join(row(start_ms + i * 60_000) for i in range(count)) + "\n"


class FakeArchive:
    """Serves zips and their CHECKSUM files by archive path; unknown paths are 404."""

    def __init__(self):
        self.objects = {}

    def add(self, symbol, interval, month, text):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(f"{symbol}-{interval}-{month}.csv", text)
        body = buffer.getvalue()
        path = archive_path(symbol, interval, month)
        self.objects[path] = body
        name = path.rsplit("/", 1)[1]
        self.objects[path + ".CHECKSUM"] = f"{hashlib.sha256(body).hexdigest()}  {name}".encode()

    def __call__(self, path):
        return self.objects.get(path)


def hour_rows(start_ms, count):
    return "\n".join(row(start_ms + i * HOUR_MS, step=HOUR_MS) for i in range(count)) + "\n"


def day_rows(start_ms, count):
    return "\n".join(row(start_ms + i * DAY_MS, step=DAY_MS) for i in range(count)) + "\n"


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data = Path(self._tmp.name)
        self.archive = FakeArchive()
        for month, start in (("2024-01", JAN_2024_MS), ("2024-02", FEB_2024_MS)):
            self.archive.add("BTCUSDT", "1m", month, minute_rows(start, 3))
            self.archive.add("BTCUSDT", "1h", month, hour_rows(start, 2))
            self.archive.add("BTCUSDT", "1d", month, day_rows(start, 2))
            self.archive.add("ETHUSDT", "1m", month, minute_rows(start, 5))
        # Later month first, a missing month, another pair and other intervals: the
        # loaders must select and order by themselves, not trust the manifest order.
        wanted = [
            ("BTCUSDT", "1m", "2024-02"),
            ("BTCUSDT", "1m", "2024-01"),
            ("BTCUSDT", "1m", "2023-12"),
            ("ETHUSDT", "1m", "2024-01"),
            ("BTCUSDT", "1h", "2024-02"),
            ("BTCUSDT", "1h", "2024-01"),
            ("BTCUSDT", "1d", "2024-02"),
            ("BTCUSDT", "1d", "2024-01"),
        ]
        self.manifest = {"files": [fetch_file(self.data, *w, self.archive) for w in wanted]}
        assert self.manifest["files"][2]["status"] == "missing"

    def tearDown(self):
        self._tmp.cleanup()

    def test_minutes_come_in_time_order_for_one_pair_only(self):
        opens = [k.open_ms for k in load_minutes(self.data, self.manifest, "BTCUSDT")]
        expected = [JAN_2024_MS + i * 60_000 for i in range(3)]
        expected += [FEB_2024_MS + i * 60_000 for i in range(3)]
        self.assertEqual(opens, expected)
        self.assertEqual(len(list(load_minutes(self.data, self.manifest, "ETHUSDT"))), 5)

    def test_hours_and_days_are_sorted_and_skip_other_intervals(self):
        hours = [k.open_ms for k in load_hourly(self.data, self.manifest, "BTCUSDT")]
        days = [k.open_ms for k in load_daily(self.data, self.manifest, "BTCUSDT")]
        self.assertEqual(hours, sorted(hours))
        self.assertEqual(hours[0], JAN_2024_MS)
        self.assertEqual(len(hours), 4)
        self.assertEqual(
            days, [JAN_2024_MS, JAN_2024_MS + DAY_MS, FEB_2024_MS, FEB_2024_MS + DAY_MS]
        )

    def test_an_unknown_pair_loads_nothing(self):
        self.assertEqual(list(load_minutes(self.data, self.manifest, "XRPUSDT")), [])
        self.assertEqual(load_hourly(self.data, self.manifest, "XRPUSDT"), [])
        self.assertEqual(load_daily(self.data, self.manifest, "XRPUSDT"), [])

    def test_a_damaged_archive_fails_closed(self):
        local_path(self.data, "BTCUSDT", "1h", "2024-02").write_bytes(b"not a zip")
        with self.assertRaises(DataError):
            load_hourly(self.data, self.manifest, "BTCUSDT")
        local_path(self.data, "BTCUSDT", "1m", "2024-01").unlink()
        with self.assertRaises(OSError):
            list(load_minutes(self.data, self.manifest, "BTCUSDT"))


class RulesForTests(unittest.TestCase):
    FILTERS = {"tick_size": "0.01", "quantity_step": "0.00001", "min_notional": "5"}

    def test_filters_and_costs_are_carried_exactly(self):
        rules = rules_for("BTCUSDT", self.FILTERS, D("0"), D("0.0005"), D("0.10"), D("0.0009"))
        self.assertEqual(rules.symbol, "BTCUSDT")
        self.assertEqual(rules.tick_size, D("0.01"))
        self.assertEqual(rules.quantity_step, D("0.00001"))
        self.assertEqual(rules.minimum_notional, D("5"))
        self.assertEqual(rules.fee_rate, D("0"))
        self.assertEqual(rules.slippage_rate, D("0.0005"))
        self.assertEqual(rules.participation, D("0.10"))
        self.assertEqual(rules.taker_fee_rate, D("0.0009"))

    def test_taker_fee_defaults_to_none(self):
        rules = rules_for("BTCUSDT", self.FILTERS, D("0.001"), D("0.0005"), D("0.10"))
        self.assertIsNone(rules.taker_fee_rate)

    def test_non_positive_filters_are_rejected(self):
        for field in self.FILTERS:
            bad = {**self.FILTERS, field: "0"}
            with self.subTest(field=field), self.assertRaises(ValueError):
                rules_for("BTCUSDT", bad, D("0.001"), D("0.0005"), D("0.10"))


if __name__ == "__main__":
    unittest.main()
