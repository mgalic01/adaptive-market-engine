"""Network-free tests for archive parsing, checksum verification and manifests."""

import contextlib
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from dataclasses import replace
from decimal import Decimal as D
from functools import partial
from pathlib import Path
from unittest.mock import patch

from crypto_grid_bot.backtest import __main__ as cli
from crypto_grid_bot.backtest import dataset
from crypto_grid_bot.backtest.dataset import (
    ArchiveParseError,
    archive_path,
    fetch_dataset,
    fetch_file,
    fetch_funding_file,
    funding_archive_path,
    funding_local_path,
    load_manifest,
    load_spec,
    local_path,
    verify_dataset,
    write_manifest,
)
from crypto_grid_bot.backtest.funding import FundingSignal, read_funding_archive
from crypto_grid_bot.backtest.klines import (
    aggregate,
    parse_rows,
    read_archive,
    read_member,
)
from crypto_grid_bot.backtest.replay import load_funding
from crypto_grid_bot.market_data.client import FeedError
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

    def add_funding(self, symbol, month, text, *, checksum=None, member=None):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(member or f"{symbol}-fundingRate-{month}.csv", text)
        body = buffer.getvalue()
        path = funding_archive_path(symbol, month)
        digest = checksum or hashlib.sha256(body).hexdigest()
        self.objects[path] = body
        name = path.rsplit("/", 1)[1]
        self.objects[path + ".CHECKSUM"] = f"{digest}  {name}".encode()

    def __call__(self, path):
        self.requests.append(path)
        return self.objects.get(path)


FUNDING_HEADER = "calc_time,funding_interval_hours,last_funding_rate\n"


def funding_rows(start_ms, count):
    return FUNDING_HEADER + "".join(
        f"{start_ms + i * 8 * 3_600_000},8,0.0001\n" for i in range(count)
    )


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = body

    def read(self, limit):
        return self._body[:limit]


class FakeConnection:
    """One canned HTTP response; records the request and whether it was closed."""

    def __init__(self, status=200, body=b"", *, fail=None):
        self.status, self.body, self.fail = status, body, fail
        self.requests = []
        self.closed = False

    def __call__(self, host, *, timeout):
        self.host = host
        return self

    def request(self, method, path):
        self.requests.append((method, path))
        if self.fail is not None:
            raise self.fail

    def getresponse(self):
        return FakeResponse(self.status, self.body)

    def close(self):
        self.closed = True


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

    def test_non_ascii_checksum_body_fails_at_the_data_error_boundary(self):
        # A corrupt or hostile .CHECKSUM response used to raise UnicodeDecodeError, which
        # escaped the DataError boundary every caller fails closed on.
        self.archive.add("ADAUSDT", "1m", "2024-01", minute_rows(JAN_2024_MS, 5))
        path = archive_path("ADAUSDT", "1m", "2024-01") + ".CHECKSUM"
        self.archive.objects[path] = b"\xff\xfe not ascii"
        with self.assertRaisesRegex(DataError, "unexpected checksum file"):
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

    def tiny_dataset(self):
        """A one-pair, two-month dataset, fetched from the fake archive: (spec, manifest)."""
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
            instruments=lambda symbol: {
                "tick_size": "0.0001",
                "quantity_step": "0.1",
                "min_notional": "5",
            },
        )
        return spec, manifest

    def test_manifest_round_trip_and_tamper_detection(self):
        spec, manifest = self.tiny_dataset()
        json.dumps(manifest)  # serialisable
        verify_dataset(spec, manifest, self.data)
        local_path(self.data, "ADAUSDT", "1h", "2024-01").write_bytes(b"tampered")
        with self.assertRaisesRegex(DataError, "checksum"):
            verify_dataset(spec, manifest, self.data)
        with self.assertRaisesRegex(DataError, "do not match"):
            verify_dataset(replace(spec, end="2024-02"), manifest, self.data)

    def test_funding_archives_are_optional_and_verified_like_klines(self):
        # Codex review of #165: G's archives (spec v1 P8) must pass verification. The
        # klines still cover the spec exactly; a funding entry has a kind and no interval,
        # and its archive is checksum-verified like a kline archive.
        spec, manifest = self.tiny_dataset()
        months = ("2023-12", "2024-01")
        for month, start in zip(months, (1701388800011, JAN_2024_MS + 11), strict=True):
            self.archive.add_funding("BTCUSDT", month, funding_rows(start, 4))
        funding = [fetch_funding_file(self.data, "BTCUSDT", m, self.archive) for m in months]
        with_funding = manifest | {"files": manifest["files"] + funding}
        path = self.data / "with-funding.manifest.json"
        write_manifest(path, with_funding)
        self.assertEqual(json.loads(json.dumps(with_funding)), load_manifest(path))
        verify_dataset(spec, with_funding, self.data)
        records = load_funding(self.data, with_funding, "BTCUSDT", months)
        self.assertEqual(8, len(records))  # a non-empty history reaches G
        self.assertTrue(
            FundingSignal(records).state(JAN_2024_MS + 16 * 3_600_000 + 60_000).available
        )
        # The P8 report's entry shape (its appendix, BTCUSDT 2022-04) is admitted as it is.
        p8 = {
            "bytes": 926,
            "expected_records": 90,
            "first_calc_time_ms": 1648771200000,
            "interval_hours": {"8": 90},
            "invalid_records": 0,
            "kind": "fundingRate",
            "last_calc_time_ms": 1651334400015,
            "max_offset_ms": 31,
            "month": "2022-04",
            "records": 90,
            "sha256": "57e2776cc68b3169fc9f8632dad67278f470cd453407a8ebe6c87963c8a31357",
            "status": "ok",
            "symbol": "BTCUSDT",
            "url": "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/"
            "BTCUSDT-fundingRate-2022-04.zip",
        }
        write_manifest(path, manifest | {"files": manifest["files"] + [p8]})
        load_manifest(path)
        # A wrong checksum, a changed archive and a month listed twice all fail.
        wrong = [entry | {"sha256": "0" * 64} for entry in funding]
        cases = (
            (manifest | {"files": manifest["files"] + wrong}, "checksum"),
            (manifest | {"files": manifest["files"] + funding + funding[:1]}, "twice"),
        )
        for bad, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(DataError, message):
                verify_dataset(spec, bad, self.data)
        funding_local_path(self.data, "BTCUSDT", "2024-01").write_bytes(b"tampered")
        with self.assertRaisesRegex(DataError, "checksum"):
            verify_dataset(spec, with_funding, self.data)
        # A missing funding month is recorded, not verified, as for klines.
        missing = funding[:1] + [{**funding[1], "status": "missing"}]
        missing[1].pop("sha256")
        verify_dataset(spec, manifest | {"files": manifest["files"] + missing}, self.data)

    def test_a_refetch_keeps_and_verifies_the_manifests_funding_archives(self):
        # Codex review of #165: `fetch` rebuilt the files from the spec's klines alone, so
        # a re-fetch dropped the funding entries G needs. Given the manifest it refreshes,
        # it fetches and verifies their archives again and keeps them after the klines,
        # and the klines come out exactly as without it.
        spec, manifest = self.tiny_dataset()
        self.archive.add_funding("BTCUSDT", "2024-01", funding_rows(JAN_2024_MS + 11, 4))
        funding = fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        previous = manifest | {"files": manifest["files"] + [funding]}
        archive = funding_local_path(self.data, "BTCUSDT", "2024-01")
        archive.write_bytes(b"tampered")  # verified again: fetched anew
        filters = {"tick_size": "0.0001", "quantity_step": "0.1", "min_notional": "5"}
        refetched = fetch_dataset(
            spec,
            self.data,
            fetcher=self.archive,
            instruments=lambda symbol: filters,
            previous=previous,
        )
        self.assertEqual(previous["files"], refetched["files"])
        verify_dataset(spec, refetched, self.data)
        self.assertEqual(funding["sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        # Without funding entries, as every committed manifest, nothing changes.
        plain = fetch_dataset(
            spec, self.data, fetcher=self.archive, instruments=lambda symbol: filters
        )
        self.assertEqual(manifest["files"], plain["files"])
        self.assertEqual(
            plain["files"],
            fetch_dataset(
                spec,
                self.data,
                fetcher=self.archive,
                instruments=lambda s: filters,
                previous=manifest,
            )["files"],
        )

    def test_the_fetch_command_keeps_the_manifests_funding_archives(self):
        spec, manifest = self.tiny_dataset()
        self.archive.add_funding("BTCUSDT", "2024-01", funding_rows(JAN_2024_MS + 11, 4))
        funding = fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        spec_path = self.data / "tiny.toml"
        spec_path.write_text(
            (ROOT / "config/datasets/verify-2024h1.toml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        manifest_file = self.data / "tiny.manifest.json"
        write_manifest(manifest_file, manifest | {"files": manifest["files"] + [funding]})
        filters = {"tick_size": "0.0001", "quantity_step": "0.1", "min_notional": "5"}
        offline = partial(fetch_dataset, fetcher=self.archive, instruments=lambda symbol: filters)
        with (
            patch.object(cli, "load_spec", lambda path: spec),
            patch.object(cli, "fetch_dataset", offline),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                0, cli.main(["fetch", "--spec", str(spec_path), "--data-dir", str(self.data)])
            )
        written = load_manifest(manifest_file)
        self.assertEqual([funding], [f for f in written["files"] if f.get("kind")])
        verify_dataset(spec, written, self.data)

    def test_funding_entries_are_validated_before_file_access(self):
        spec = load_spec(ROOT / "config/datasets/verify-2024h1.toml")
        entry = {
            "kind": "fundingRate",
            "symbol": "BTCUSDT",
            "month": "2024-01",
            "status": "ok",
            "sha256": "a" * 64,
        }
        for update in (
            {"kind": "openInterest"},
            {"month": "2025-01"},
            {"month": "2024-1"},
            {"symbol": "../BTCUSDT"},
            {"status": "unparsed"},
            {"sha256": "z" * 64},
        ):
            manifest = {
                "schema": 1,
                "dataset": spec.name,
                "instruments": {},
                "files": [entry | update],
            }
            path = self.data / "malformed.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(update=update):
                with self.assertRaises(DataError):
                    load_manifest(path)
                with self.assertRaises(DataError):
                    verify_dataset(spec, manifest, self.data)
        del entry["month"]
        with self.assertRaisesRegex(DataError, "incomplete"):
            verify_dataset(
                spec,
                {"schema": 1, "dataset": spec.name, "instruments": {}, "files": [entry]},
                self.data,
            )

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

    def test_manifest_validation_rejects_bad_entries_before_file_access(self):
        spec = load_spec(ROOT / "config/datasets/verify-2024h1.toml")
        entry = {
            "symbol": "ADAUSDT",
            "interval": "1m",
            "month": "2024-01",
            "status": "ok",
            "sha256": "a" * 64,
        }
        for update in (
            {"month": "9999-12"},
            {"month": "2024-13"},
            {"symbol": "../ADAUSDT"},
            {"interval": []},
            {"status": []},
            {"sha256": None},
            {"sha256": "z" * 64},
        ):
            manifest = {
                "schema": 1,
                "dataset": spec.name,
                "instruments": {},
                "files": [entry | update],
            }
            path = self.data / "malformed.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(update=update):
                with self.assertRaises(DataError):
                    load_manifest(path)
                with self.assertRaises(DataError):
                    verify_dataset(spec, manifest, self.data)

    def test_manifest_validation_rejects_bad_exchange_filters(self):
        spec = load_spec(ROOT / "config/datasets/verify-2024h1.toml")
        good = {"tick_size": "0.0001", "quantity_step": "0.1", "min_notional": "5"}
        for instruments in (
            {"ADAUSDT": []},
            {"ADAUSDT": {k: v for k, v in good.items() if k != "tick_size"}},
            {"ADAUSDT": good | {"min_notional": "five"}},
            {"ADAUSDT": good | {"quantity_step": "0"}},
            {"ADAUSDT": good | {"tick_size": "-0.0001"}},
            {"ADAUSDT": good | {"tick_size": "1E-9999"}},
            {"ADAUSDT": good | {"tick_size": 0.0001}},
            {"../ADAUSDT": good},
        ):
            manifest = {"schema": 1, "dataset": spec.name, "instruments": instruments, "files": []}
            path = self.data / "malformed.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.subTest(instruments=instruments):
                with self.assertRaisesRegex(DataError, "exchange filters|instrument entry"):
                    load_manifest(path)
                with self.assertRaisesRegex(DataError, "exchange filters|instrument entry"):
                    verify_dataset(spec, manifest, self.data)

    def test_manifest_loading_rejects_invalid_utf8(self):
        path = self.data / "bad-encoding.json"
        path.write_bytes(b"\xff")
        with self.assertRaisesRegex(DataError, "invalid dataset manifest JSON"):
            load_manifest(path)

    def test_committed_manifests_remain_loadable(self):
        for path in (ROOT / "config/datasets").glob("*.manifest.json"):
            with self.subTest(path=path.name):
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), load_manifest(path))

    def test_committed_specs_remain_loadable(self):
        specs = sorted((ROOT / "config/datasets").glob("*.toml"))
        self.assertTrue(specs)
        for path in specs:
            with self.subTest(path=path.name):
                self.assertEqual(path.stem, load_spec(path).name)

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

    def test_daily_warmup_start_is_optional_and_validated(self):
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        spec = load_spec(ROOT / "config/datasets/verify-2024h1.toml")
        self.assertEqual("2020-05", spec.daily_warmup_start)
        self.assertIn(("BTCUSDT", "1d", "2020-05"), spec.required())
        without = "\n".join(
            line for line in source.splitlines() if not line.startswith("daily_warmup_start")
        )
        for text, ok in (
            (without, True),
            (
                source.replace('daily_warmup_start = "2020-05"', 'daily_warmup_start = "2024-02"'),
                False,
            ),
            (source.replace('daily_warmup_start = "2020-05"', "daily_warmup_start = 5"), False),
        ):
            with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
                handle.write(text)
            self.addCleanup(Path(handle.name).unlink)
            with self.subTest(ok=ok):
                if ok:
                    parsed = load_spec(Path(handle.name))
                    self.assertIsNone(parsed.daily_warmup_start)
                    self.assertFalse(any(i == "1d" for _, i, _ in parsed.required()))
                else:
                    with self.assertRaises(DataError):
                        load_spec(Path(handle.name))

    def test_basket_exclusions_are_optional_documented_and_validated(self):
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        self.assertEqual(
            (), load_spec(ROOT / "config/datasets/verify-2024h1.toml").basket_exclusions
        )

        def table(symbol="DOGEUSDT", start="2023-11-01T00:00Z", end="2023-11-02T08:00Z", **extra):
            fields = {"symbol": symbol, "from": start, "to": end, "reason": "not yet listed"}
            fields |= extra
            body = "\n".join(f"{k} = {v!r}".replace("'", '"') for k, v in fields.items())
            return "\n[[basket_exclusions]]\n" + body + "\n"

        good = source + table()
        cases = (
            (good, True),
            (source + table(symbol="ADAUSDT"), False),  # traded
            (source + table(symbol="BTCUSDT"), False),  # market proxy
            (source + table(symbol="AVAXUSDT"), False),  # not in the basket
            (source + table(start="2023-11-01T00:30Z"), False),  # not a whole hour
            (source + table(start="2023-11-02T08:00Z"), False),  # from == to
            (source + table(reason=" "), False),
            (source + table(note="x"), False),  # unknown key
            (good + table(start="2023-11-02T07:00Z", end="2023-11-03T00:00Z"), False),  # overlap
            (good + table(start="2023-11-02T08:00Z", end="2023-11-03T00:00Z"), True),  # adjacent
        )
        for text, ok in cases:
            with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
                handle.write(text)
            self.addCleanup(Path(handle.name).unlink)
            with self.subTest(text=text[len(source) :]):
                if ok:
                    (first, *_) = load_spec(Path(handle.name)).basket_exclusions
                    self.assertEqual(
                        ("DOGEUSDT", 32 * 3_600_000), (first.symbol, first.end_ms - first.start_ms)
                    )
                else:
                    with self.assertRaises(DataError):
                        load_spec(Path(handle.name))

    def test_a_malformed_warmup_start_is_a_data_error_with_daily_history(self):
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(source.replace('warmup_start = "2023-11"', "warmup_start = 202311"))
        self.addCleanup(Path(handle.name).unlink)
        with self.assertRaises(DataError):
            load_spec(Path(handle.name))

    def test_spec_accepts_a_zero_maker_fee(self):
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(source.replace('fee_rate = "0.001"', 'fee_rate = "0"'))
        self.addCleanup(Path(handle.name).unlink)
        self.assertEqual(0, load_spec(Path(handle.name)).fee_rate)


class FundingFetchTests(unittest.TestCase):
    """fetch_funding_file mirrors fetch_file for the USDT-M funding archives (spec P8)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.archive = FakeArchive()

    def test_verified_file_is_stored_and_described(self):
        self.archive.add_funding("BTCUSDT", "2024-01", funding_rows(JAN_2024_MS, 4))
        entry = fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        self.assertEqual("ok", entry["status"])
        self.assertEqual("fundingRate", entry["kind"])
        self.assertEqual(4, entry["records"])
        target = funding_local_path(self.data, "BTCUSDT", "2024-01")
        self.assertTrue(target.exists())
        self.assertEqual(
            self.data / "binance/data/futures/um/monthly/fundingRate/BTCUSDT"
            "/BTCUSDT-fundingRate-2024-01.zip",
            target,
        )
        self.assertEqual(entry["sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
        self.assertEqual(
            "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT"
            "/BTCUSDT-fundingRate-2024-01.zip",
            entry["url"],
        )

    def test_checksum_mismatch_is_rejected_and_nothing_is_stored(self):
        self.archive.add_funding(
            "BTCUSDT", "2024-01", funding_rows(JAN_2024_MS, 4), checksum="0" * 64
        )
        with self.assertRaisesRegex(DataError, "SHA-256"):
            fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        self.assertFalse(funding_local_path(self.data, "BTCUSDT", "2024-01").exists())

    def test_a_checksum_naming_another_file_is_rejected(self):
        self.archive.add_funding("BTCUSDT", "2024-01", funding_rows(JAN_2024_MS, 4))
        path = funding_archive_path("BTCUSDT", "2024-01")
        digest = self.archive.objects[path + ".CHECKSUM"].split(b"  ")[0].decode()
        self.archive.objects[path + ".CHECKSUM"] = f"{digest}  BTCUSDT-1d-2024-01.zip".encode()
        with self.assertRaisesRegex(DataError, "unexpected checksum file"):
            fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        self.assertFalse(funding_local_path(self.data, "BTCUSDT", "2024-01").exists())

    def test_unpublished_month_is_recorded_missing(self):
        entry = fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        self.assertEqual("missing", entry["status"])
        self.assertEqual(
            [
                funding_archive_path("BTCUSDT", "2024-01") + ".CHECKSUM",
                funding_archive_path("BTCUSDT", "2024-01"),
            ],
            self.archive.requests,
        )

    def test_an_archive_without_a_checksum_is_an_error(self):
        self.archive.add_funding("BTCUSDT", "2024-01", funding_rows(JAN_2024_MS, 4))
        del self.archive.objects[funding_archive_path("BTCUSDT", "2024-01") + ".CHECKSUM"]
        with self.assertRaisesRegex(DataError, "without a checksum"):
            fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)

    def test_cached_file_is_reused_only_when_checksum_matches(self):
        self.archive.add_funding("BTCUSDT", "2024-01", funding_rows(JAN_2024_MS, 4))
        fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        zip_path = funding_archive_path("BTCUSDT", "2024-01")
        self.assertEqual(1, self.archive.requests.count(zip_path))
        funding_local_path(self.data, "BTCUSDT", "2024-01").write_bytes(b"tampered")
        fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)
        self.assertEqual(2, self.archive.requests.count(zip_path))

    def test_a_hash_verified_archive_the_parser_rejects_is_a_parse_error(self):
        # Wrong member name, and a row outside the month: both fail after the checksum.
        cases = {
            "member": dict(member="ETHUSDT-fundingRate-2024-01.csv"),
            "rows": dict(text=funding_rows(JAN_2025_MS, 2)),
        }
        for name, extra in cases.items():
            with self.subTest(name):
                self.archive = FakeArchive()
                text = extra.pop("text", funding_rows(JAN_2024_MS, 4))
                self.archive.add_funding("BTCUSDT", "2024-01", text, **extra)
                with self.assertRaises(ArchiveParseError):
                    fetch_funding_file(self.data, "BTCUSDT", "2024-01", self.archive)

    def test_a_reserved_month_is_refused_before_any_request_or_cache_access(self):
        with self.assertRaisesRegex(DataError, "reserved window"):
            fetch_funding_file(self.data, "BTCUSDT", "2025-01", self.archive)
        self.assertEqual([], self.archive.requests)
        self.assertEqual([], list(self.data.iterdir()))

    def test_the_last_development_month_is_still_fetched(self):
        december = 1733011200000  # 2024-12-01T00:00:00Z
        self.archive.add_funding("BTCUSDT", "2024-12", funding_rows(december, 3))
        entry = fetch_funding_file(self.data, "BTCUSDT", "2024-12", self.archive)
        self.assertEqual(("ok", 3), (entry["status"], entry["records"]))

    def test_the_path_helpers_validate_their_arguments(self):
        for symbol, month in (("btcusdt", "2024-01"), ("BTCUSDT", "2024-1"), ("BTCUSDT", "x")):
            with self.subTest(symbol=symbol, month=month), self.assertRaises(DataError):
                funding_archive_path(symbol, month)


class ArchiveGetTests(unittest.TestCase):
    """archive_get's path guard and status handling, with a canned connection."""

    KLINE = archive_path("ADAUSDT", "1m", "2024-12")
    FUNDING = funding_archive_path("BTCUSDT", "2024-12")

    def get(self, path, connection):
        with patch.object(dataset, "https_connection", connection):
            return dataset.archive_get(path)

    def test_both_canonical_shapes_reach_the_fixed_host(self):
        for path in (
            self.KLINE,
            self.KLINE + ".CHECKSUM",
            self.FUNDING,
            self.FUNDING + ".CHECKSUM",
        ):
            with self.subTest(path=path):
                connection = FakeConnection(200, b"zip")
                self.assertEqual(b"zip", self.get(path, connection))
                self.assertEqual("data.binance.vision", connection.host)
                self.assertEqual([("GET", path)], connection.requests)
                self.assertTrue(connection.closed)

    def test_forbidden_paths_are_refused_before_connecting(self):
        connection = FakeConnection(200, b"zip")
        base = "/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-"
        forbidden = {
            "directory": "/data/futures/um/monthly/fundingRate/BTCUSDT/",
            "query": base + "2024-12.zip?prefix=x",
            "reserved suffix trick": base + "2025-01.zip?x=-2024-12.zip",
            "symbol mismatch": base.replace("BTCUSDT-", "ETHUSDT-") + "2024-12.zip",
            "other market": base.replace("/um/", "/cm/") + "2024-12.zip",
            "relative": base.lstrip("/") + "2024-12.zip",
            "csv": base + "2024-12.csv",
        }
        for name, path in forbidden.items():
            with (
                self.subTest(name),
                self.assertRaisesRegex(DataError, "not a monthly spot kline archive or"),
            ):
                self.get(path, connection)
        for path in (base + "2025-01.zip", base + "2025-01.zip.CHECKSUM"):
            with self.subTest(path=path), self.assertRaisesRegex(DataError, "reserved window"):
                self.get(path, connection)
        self.assertEqual([], connection.requests)

    def test_404_is_missing_and_every_other_status_is_an_error(self):
        self.assertIsNone(self.get(self.FUNDING, FakeConnection(404, b"")))
        for status in (301, 302, 307, 403, 429, 500, 503):
            with self.subTest(status=status), self.assertRaisesRegex(FeedError, f"HTTP {status}"):
                self.get(self.FUNDING, FakeConnection(status, b"elsewhere"))

    def test_transport_failures_and_oversized_bodies_are_feed_errors(self):
        for fail in (OSError("reset"), dataset.http.client.HTTPException("bad")):
            connection = FakeConnection(fail=fail)
            with self.subTest(fail=fail), self.assertRaisesRegex(FeedError, "transport"):
                self.get(self.FUNDING, connection)
            self.assertTrue(connection.closed)
        too_big = b"x" * (dataset.MAX_ZIP_BYTES + 1)
        with self.assertRaisesRegex(FeedError, "size limit"):
            self.get(self.FUNDING, FakeConnection(200, too_big))


class ReservedWindowTests(unittest.TestCase):
    """The reserved window (2025-01 onward) is refused on every path to archive data.

    Each test asserts the error names the reserved window, so it proves the window
    guard fired rather than an unrelated check. That matters: the manifest test above
    already rejects "9999-12", but only because that month overflows, not because of
    any window rule; a realistic reserved month used to pass straight through.
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)

    def _spec_with(self, old: str, new: str) -> Path:
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        assert old in source, old
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(source.replace(old, new))
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_fetch_file_refuses_a_reserved_month_before_any_network_call(self):
        calls: list[str] = []

        def fetcher(path):
            calls.append(path)
            return None

        with self.assertRaisesRegex(DataError, "reserved window"):
            fetch_file(self.data, "ADAUSDT", "1m", "2025-01", fetcher)
        self.assertEqual([], calls, "the reserved month reached the fetcher")
        self.assertFalse(any(self.data.rglob("*")), "something was written for a reserved month")

    def test_fetch_file_still_accepts_the_last_development_month(self):
        archive = FakeArchive()
        archive.add("ADAUSDT", "1m", "2024-12", minute_rows(JAN_2024_MS, 1))
        # The fake's rows are for January, so this is expected to fail on content --
        # but only after the window guard has let 2024-12 through to the fetcher.
        calls: list[str] = []

        def fetcher(path):
            calls.append(path)
            return archive(path)

        try:
            fetch_file(self.data, "ADAUSDT", "1m", "2024-12", fetcher)
        except DataError as exc:
            self.assertNotIn("reserved window", str(exc))
        self.assertTrue(calls, "2024-12 was refused, but it is a development month")

    def test_a_spec_reaching_the_reserved_window_is_rejected(self):
        for old, new in (
            ('end = "2024-06"', 'end = "2025-01"'),
            ('end = "2024-06"', 'end = "2026-08"'),
            ('start = "2024-01"\nend = "2024-06"', 'start = "2025-01"\nend = "2025-06"'),
            ('daily_warmup_start = "2020-05"', 'daily_warmup_start = "2025-01"'),
        ):
            with self.subTest(new=new), self.assertRaisesRegex(DataError, "reserved window"):
                load_spec(self._spec_with(old, new))

    def test_a_spec_ending_at_the_last_development_month_is_accepted(self):
        spec = load_spec(self._spec_with('end = "2024-06"', 'end = "2024-12"'))
        self.assertEqual("2024-12", spec.end)
        self.assertEqual("2024-12", max(month for _, _, month in spec.required()))

    def test_a_manifest_listing_a_reserved_month_is_rejected(self):
        spec = load_spec(ROOT / "config/datasets/verify-2024h1.toml")
        manifest = {
            "schema": 1,
            "dataset": spec.name,
            "instruments": {},
            "files": [
                {
                    "symbol": "ADAUSDT",
                    "interval": "1m",
                    "month": "2025-01",
                    "status": "ok",
                    "sha256": "a" * 64,
                }
            ],
        }
        path = self.data / "reserved.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(DataError, "reserved window"):
            load_manifest(path)
        with self.assertRaisesRegex(DataError, "reserved window"):
            verify_dataset(spec, manifest, self.data)

    def _archive(self, member: str) -> Path:
        # A real zip holding exactly the expected member: if the guard were missing,
        # the reader would open it and fail on its contents instead.
        path = self.data / (member.removesuffix(".csv") + ".zip")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(member, "not,parsed\n")
        return path

    def test_the_kline_reader_refuses_a_reserved_month_without_opening_it(self):
        path = self._archive("ADAUSDT-1m-2025-01.csv")
        with self.assertRaisesRegex(DataError, "reserved window"):
            read_archive(path, "ADAUSDT", "1m", "2025-01")

    def test_the_funding_reader_refuses_a_reserved_month_without_opening_it(self):
        path = self._archive("BTCUSDT-fundingRate-2025-01.csv")
        with self.assertRaisesRegex(DataError, "reserved window"):
            read_funding_archive(path, "BTCUSDT", "2025-01")

    def test_the_raw_member_reader_refuses_a_reserved_month(self):
        # read_member is imported directly by audit_run, so the wrappers' guards are not
        # the only way in; a real zip proves the refusal precedes opening it.
        path = self._archive("ADAUSDT-1m-2025-01.csv")
        with self.assertRaisesRegex(DataError, "reserved window"):
            read_member(path, "ADAUSDT-1m-2025-01.csv")
        self.assertIn(
            "not,parsed",
            read_member(self._archive("ADAUSDT-1m-2024-12.csv"), "ADAUSDT-1m-2024-12.csv"),
        )

    def test_the_raw_member_reader_refuses_a_name_carrying_no_month(self):
        path = self._archive("ADAUSDT-1m-2024-12.csv")
        with self.assertRaisesRegex(DataError, "carries no month"):
            read_member(path, "anything.csv")

    def test_the_archive_fetcher_refuses_a_reserved_month_before_connecting(self):
        # archive_get is a reusable network API; fetch_file's guard is not the only way in.
        calls: list[str] = []

        def connection(host, timeout):
            calls.append(host)
            raise AssertionError("no connection may be opened for a reserved month")

        with patch.object(dataset, "https_connection", connection):
            for path in (
                "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2025-01.zip",
                "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m-2025-01.zip.CHECKSUM",
            ):
                with self.assertRaisesRegex(DataError, "reserved window"):
                    dataset.archive_get(path)
            with self.assertRaisesRegex(DataError, "monthly spot kline archive"):
                dataset.archive_get("/data/spot/monthly/klines/ADAUSDT/1m/index.html")
        self.assertEqual([], calls)

    def test_the_fetcher_refuses_a_reserved_path_wearing_a_development_suffix(self):
        # An end-anchored month search reads the query, not the object: this path asks
        # for 2025-01 while ending in "-2024-12.zip".
        calls: list[str] = []

        def connection(host, timeout):
            calls.append(host)
            raise AssertionError("no connection may be opened for a reserved month")

        base = "/data/spot/monthly/klines/ADAUSDT/1m/ADAUSDT-1m"
        with patch.object(dataset, "https_connection", connection):
            for path in (
                f"{base}-2025-01.zip?x=-2024-12.zip",
                f"{base}-2025-01.zip#-2024-12.zip",
                f"{base}-2025-01.zip/../ADAUSDT-1m-2024-12.zip",
                # The file name must agree with its own directories.
                "/data/spot/monthly/klines/ADAUSDT/1m/BTCUSDT-1m-2024-12.zip",
                "/data/spot/monthly/klines/ADAUSDT/1h/ADAUSDT-1m-2024-12.zip",
            ):
                with (
                    self.subTest(path=path),
                    self.assertRaisesRegex(DataError, "monthly spot kline archive"),
                ):
                    dataset.archive_get(path)
        self.assertEqual([], calls)

    def test_the_fetcher_still_accepts_the_canonical_paths(self):
        seen: list[str] = []

        def connection(host, timeout):
            seen.append(host)
            raise DataError("stop before the network")

        canonical = archive_path("ADAUSDT", "1m", "2024-12")
        with patch.object(dataset, "https_connection", connection):
            for path in (canonical, canonical + ".CHECKSUM"):
                with self.subTest(path=path), self.assertRaises(DataError):
                    dataset.archive_get(path)
        self.assertEqual(2, len(seen))  # both reached the connection, so both passed

    def test_the_readers_still_open_the_last_development_month(self):
        # The same archive contents in 2024-12 get past the guard to the parser.
        kline = self._archive("ADAUSDT-1m-2024-12.csv")
        funding = self._archive("BTCUSDT-fundingRate-2024-12.csv")
        for call in (
            lambda: read_archive(kline, "ADAUSDT", "1m", "2024-12"),
            lambda: read_funding_archive(funding, "BTCUSDT", "2024-12"),
        ):
            with self.assertRaises(DataError) as caught:
                call()
            self.assertNotIn("reserved window", str(caught.exception))


class UnpaddedMonthTests(unittest.TestCase):
    def test_a_spec_with_an_unpadded_month_is_refused_not_iterated_to_year_end(self):
        # Before the fix ``end = "2024-6"`` passed the window guard, and ``months()``
        # then ran "2024-12" <= "2024-6" as text: 204 required files instead of 140.
        source = (ROOT / "config/datasets/verify-2024h1.toml").read_text()
        assert 'end = "2024-06"' in source
        with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as handle:
            handle.write(source.replace('end = "2024-06"', 'end = "2024-6"'))
        self.addCleanup(Path(handle.name).unlink)
        with self.assertRaisesRegex(DataError, "zero-padded"):
            load_spec(Path(handle.name))
