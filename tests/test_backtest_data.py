"""Network-free tests for archive parsing, checksum verification and manifests."""

import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.dataset import (
    archive_path,
    fetch_dataset,
    fetch_file,
    load_manifest,
    load_spec,
    local_path,
    verify_dataset,
)
from crypto_grid_bot.backtest.klines import aggregate, parse_rows, read_archive
from crypto_grid_bot.market_data.parsing import DataError

ROOT = Path(__file__).resolve().parents[1]
JAN_2024_MS = 1704067200000  # 2024-01-01T00:00:00Z
JAN_2025_MS = 1735689600000  # 2025-01-01T00:00:00Z


def row(open_ms, o="1.0", h="1.2", low="0.9", c="1.1", *, step=60_000, us=False, volume="10"):
    scale = 1000 if us else 1
    close = (open_ms + step) * scale - 1
    return ",".join(
        [str(open_ms * scale), o, h, low, c, volume, str(close), "11", "5", "4", "4.4", "0"]
    )


def minute_rows(start_ms, count, **kwargs):
    return "\n".join(row(start_ms + i * 60_000, **kwargs) for i in range(count)) + "\n"


def make_zip(symbol, interval, month, text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{symbol}-{interval}-{month}.csv", text)
    return buffer.getvalue()


class FakeArchive:
    """Serves zips and CHECKSUM files by archive path; unknown paths are 404."""

    def __init__(self):
        self.objects = {}
        self.requests = []

    def add(self, symbol, interval, month, text, *, checksum=None):
        body = make_zip(symbol, interval, month, text)
        path = archive_path(symbol, interval, month)
        digest = checksum or hashlib.sha256(body).hexdigest()
        self.objects[path] = body
        name = path.rsplit("/", 1)[1]
        self.objects[path + ".CHECKSUM"] = f"{digest}  {name}".encode()

    def __call__(self, path):
        self.requests.append(path)
        return self.objects.get(path)


class ParseTests(unittest.TestCase):
    def test_millisecond_and_microsecond_rows_normalise_to_milliseconds(self):
        ms_rows, ms_stats = parse_rows(minute_rows(JAN_2024_MS, 3), "1m", "2024-01")
        us_rows, us_stats = parse_rows(minute_rows(JAN_2025_MS, 3, us=True), "1m", "2025-01")
        self.assertEqual(JAN_2024_MS + 120_000, ms_rows[2].open_ms)
        self.assertEqual(JAN_2025_MS + 120_000, us_rows[2].open_ms)
        self.assertEqual(("ms",), ms_stats.timestamp_units)
        self.assertEqual(("us",), us_stats.timestamp_units)
        self.assertEqual(D("1.2"), us_rows[0].high)
        self.assertEqual(D("4"), us_rows[0].taker_buy_base)

    def test_gaps_and_partial_months_are_counted_not_filled(self):
        text = row(JAN_2024_MS + 60_000) + "\n" + row(JAN_2024_MS + 300_000) + "\n"
        rows, stats = parse_rows(text, "1m", "2024-01")
        self.assertEqual(2, len(rows))
        self.assertEqual(31 * 1440, stats.expected_rows)
        self.assertEqual(31 * 1440 - 2, stats.missing_rows)
        self.assertEqual(3, stats.gaps)  # leading, internal and trailing absence

    def test_malformed_rows_are_rejected(self):
        good = row(JAN_2024_MS)
        cases = {
            "header": "open_time,open,high,low,close,volume,close_time,a,b,c,d,e\n" + good,
            "columns": good + ",extra",
            "unaligned": row(JAN_2024_MS + 1),
            "outside month": row(JAN_2024_MS - 60_000),
            "ohlc": row(JAN_2024_MS, h="0.95"),
            "negative": row(JAN_2024_MS, low="-1"),
            "duplicate": good + "\n" + good,
            "out of order": row(JAN_2024_MS + 60_000) + "\n" + good,
            "taker volume": row(JAN_2024_MS, volume="3"),
            "mixed units": good.replace(
                str(JAN_2024_MS + 59_999), str(JAN_2024_MS + 59_999) + "999"
            ),
            "us not boundary": row(JAN_2025_MS, us=True).replace(
                str(JAN_2025_MS * 1000), str(JAN_2025_MS * 1000 + 999), 1
            ),
        }
        for name, text in cases.items():
            month = "2025-01" if name == "us not boundary" else "2024-01"
            with self.subTest(case=name), self.assertRaises(DataError):
                parse_rows(text, "1m", month)

    def test_hourly_aggregation_matches_candle_semantics(self):
        rows, _ = parse_rows(
            row(JAN_2024_MS, o="1", h="2", low="0.5", c="1.5")
            + "\n"
            + row(JAN_2024_MS + 60_000, o="1.5", h="3", low="1.4", c="2.5")
            + "\n"
            + row(JAN_2024_MS + 3_600_000, o="9", h="9", low="9", c="9"),
            "1m",
            "2024-01",
        )
        first, second = aggregate(rows)
        self.assertEqual(
            (JAN_2024_MS, D(1), D(3), D("0.5"), D("2.5")),
            (first.open_ms, first.open, first.high, first.low, first.close),
        )
        self.assertEqual(D(20), first.volume)
        self.assertEqual(JAN_2024_MS + 3_600_000, second.open_ms)

    def test_archive_must_contain_exactly_the_expected_member(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.zip"
            path.write_bytes(make_zip("ADAUSDT", "1m", "2024-02", minute_rows(JAN_2024_MS, 1)))
            with self.assertRaisesRegex(DataError, "exactly"):
                read_archive(path, "ADAUSDT", "1m", "2024-01")


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.archive = FakeArchive()

    def test_verified_file_is_stored_and_described(self):
        self.archive.add("ADAUSDT", "1m", "2024-01", minute_rows(JAN_2024_MS, 5))
        entry = fetch_file(self.data, "ADAUSDT", "1m", "2024-01", self.archive)
        self.assertEqual("ok", entry["status"])
        self.assertEqual(5, entry["rows"])
        self.assertTrue(local_path(self.data, "ADAUSDT", "1m", "2024-01").exists())
        self.assertTrue(entry["url"].startswith("https://data.binance.vision/data/spot/"))

    def test_checksum_mismatch_is_rejected_and_nothing_is_stored(self):
        self.archive.add("ADAUSDT", "1m", "2024-01", minute_rows(JAN_2024_MS, 5), checksum="0" * 64)
        with self.assertRaisesRegex(DataError, "SHA-256"):
            fetch_file(self.data, "ADAUSDT", "1m", "2024-01", self.archive)
        self.assertFalse(local_path(self.data, "ADAUSDT", "1m", "2024-01").exists())

    def test_unpublished_month_is_recorded_missing(self):
        entry = fetch_file(self.data, "NEWUSDC", "1m", "2024-01", self.archive)
        self.assertEqual("missing", entry["status"])

    def test_cached_file_is_reused_only_when_checksum_matches(self):
        self.archive.add("ADAUSDT", "1m", "2024-01", minute_rows(JAN_2024_MS, 5))
        fetch_file(self.data, "ADAUSDT", "1m", "2024-01", self.archive)
        fetch_file(self.data, "ADAUSDT", "1m", "2024-01", self.archive)
        zip_path = archive_path("ADAUSDT", "1m", "2024-01")
        self.assertEqual(1, self.archive.requests.count(zip_path))
        local_path(self.data, "ADAUSDT", "1m", "2024-01").write_bytes(b"tampered")
        fetch_file(self.data, "ADAUSDT", "1m", "2024-01", self.archive)
        self.assertEqual(2, self.archive.requests.count(zip_path))

    def test_manifest_round_trip_and_tamper_detection(self):
        spec = replace(
            load_spec(ROOT / "config/datasets/verify-2024h1.toml"),
            traded=("ADAUSDT",),
            market_proxy="ADAUSDT",
            breadth_basket=(),
            warmup_start="2023-12",
            start="2024-01",
            end="2024-01",
        )
        for interval in ("1m", "1h"):
            for month, start in (("2023-12", 1701388800000), ("2024-01", JAN_2024_MS)):
                step = 60_000 if interval == "1m" else 3_600_000
                text = "\n".join(row(start + i * step, step=step) for i in range(3)) + "\n"
                self.archive.add("ADAUSDT", interval, month, text)
        manifest = fetch_dataset(
            spec,
            self.data,
            fetcher=self.archive,
            instruments=lambda symbol: {"tick_size": "0.0001"},
        )
        json.dumps(manifest)  # serialisable
        verify_dataset(spec, manifest, self.data)
        local_path(self.data, "ADAUSDT", "1h", "2024-01").write_bytes(b"tampered")
        with self.assertRaisesRegex(DataError, "checksum"):
            verify_dataset(spec, manifest, self.data)
        with self.assertRaisesRegex(DataError, "do not match"):
            verify_dataset(replace(spec, end="2024-02"), manifest, self.data)

    def test_malformed_manifests_fail_with_data_errors(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as handle:
            handle.write("{not json")
        self.addCleanup(Path(handle.name).unlink)
        with self.assertRaisesRegex(DataError, "invalid dataset manifest JSON"):
            load_manifest(Path(handle.name))

        spec = load_spec(ROOT / "config/datasets/verify-2024h1.toml")
        for manifest in (
            {"schema": 1, "dataset": spec.name, "instruments": {}, "files": [{}]},
            {
                "schema": 1,
                "dataset": spec.name,
                "instruments": {},
                "files": [
                    {
                        "symbol": "ADAUSDT",
                        "interval": "1m",
                        "month": "2024-01",
                        "status": "downloaded",
                    }
                ],
            },
        ):
            with self.subTest(manifest=manifest), self.assertRaises(DataError):
                verify_dataset(spec, manifest, self.data)

    def test_spec_rejects_unknown_fields_and_bad_values(self):
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        for bad in (
            source + 'surprise = "x"\n',
            source.replace('fee_rate = "0.001"', 'fee_rate = "0.5"'),
            source.replace('fee_rate = "0.001"', 'fee_rate = "-0.001"'),
            source.replace('fee_rate = "0.001"', 'fee_rate = "NaN"'),
            source.replace('fee_rate = "0.001"', 'fee_rate = "sNaN"'),
            source.replace('initial_quote = "100"', 'initial_quote = "Infinity"'),
            source.replace('start = "2024-01"', 'start = "2023-11"'),
        ):
            with (
                self.subTest(bad=bad[-40:]),
                tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle,
            ):
                handle.write(bad)
            with self.assertRaises(DataError):
                load_spec(Path(handle.name))
            Path(handle.name).unlink()

    def test_spec_accepts_a_zero_maker_fee(self):
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(source.replace('fee_rate = "0.001"', 'fee_rate = "0"'))
        self.addCleanup(Path(handle.name).unlink)
        self.assertEqual(0, load_spec(Path(handle.name)).fee_rate)
