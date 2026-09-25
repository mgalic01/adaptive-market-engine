"""Synthetic tests for the funding archive parser and the G signal (spec v1 §3 G)."""

import io
import tempfile
import unittest
import zipfile
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.funding import (
    FundingRecord,
    FundingSignal,
    parse_funding_rows,
    read_funding_archive,
)
from crypto_grid_bot.market_data.parsing import DataError

T0 = 1704067200000  # 2024-01-01T00:00:00Z, synthetic series only
H = 3_600_000
S = 1000
PUB = 60 * S  # publication allowance


def rec(hour, interval=8, rate="0.0001", offset_ms=11):
    return FundingRecord(T0 + hour * H + offset_ms, interval, D(rate))


def at(hour, seconds=0):
    return T0 + hour * H + seconds * S


def series(*pairs, rate="0.0001"):
    return FundingSignal(rec(hour, interval, rate) for hour, interval in pairs)


class FundingSignalTests(unittest.TestCase):
    def assertAvailable(self, signal, t_ms):
        state = signal.state(t_ms)
        self.assertTrue(state.available, state.reason)

    def assertUnavailable(self, signal, t_ms, reason=None):
        state = signal.state(t_ms)
        self.assertFalse(state.available)
        self.assertTrue(state.blocks)
        if reason is not None:
            self.assertEqual(state.reason, reason)

    def test_constant_cadence_is_available_up_to_the_overdue_boundary(self):
        signal = series((0, 8), (8, 8), (16, 8))
        self.assertAvailable(signal, at(16) + PUB)
        self.assertFalse(signal.state(at(16) + PUB).blocks)
        # Overdue boundary: scheduled(r3) + 8 h + 60 s.
        self.assertAvailable(signal, at(24) + PUB - S)
        self.assertUnavailable(signal, at(24) + PUB, "overdue")

    def test_usability_boundary(self):
        signal = series((0, 8), (8, 8), (16, 8))
        # calc_time 16h + 11 ms is truncated to the second before adding 60 s.
        self.assertUnavailable(signal, at(16) + PUB - S, "insufficient_history")
        self.assertAvailable(signal, at(16) + PUB)

    def test_cadence_change_8_to_4(self):
        signal = series((0, 8), (8, 8), (16, 8), (20, 4), (24, 4), (28, 4))
        # Between the deadlines, before the first 4-hour record is usable: available.
        self.assertAvailable(signal, at(20) + PUB - S)
        # Its publication boundary: (8, 8, 4) is mixed.
        self.assertUnavailable(signal, at(20) + PUB, "mixed_interval")
        self.assertUnavailable(signal, at(24) + PUB, "mixed_interval")  # (8, 4, 4)
        # Recovery: the first (4, 4, 4) with 4-hour steps, exactly.
        self.assertUnavailable(signal, at(28) + PUB - S, "mixed_interval")
        self.assertAvailable(signal, at(28) + PUB)

    def test_cadence_change_4_to_8(self):
        signal = series((0, 4), (4, 4), (8, 4), (16, 8), (24, 8), (32, 8))
        # The old deadline scheduled(r3) + 4 h + 60 s passes first.
        self.assertAvailable(signal, at(12) + PUB - S)
        self.assertUnavailable(signal, at(12) + PUB, "overdue")
        # The first changed record's publication boundary.
        self.assertUnavailable(signal, at(16) + PUB - S, "overdue")
        self.assertUnavailable(signal, at(16) + PUB, "mixed_interval")  # (4, 4, 8)
        self.assertUnavailable(signal, at(24) + PUB, "mixed_interval")  # (4, 8, 8)
        self.assertUnavailable(signal, at(32) + PUB - S, "mixed_interval")
        self.assertAvailable(signal, at(32) + PUB)  # (8, 8, 8)

    def test_hidden_gap_is_unavailable(self):
        # (4 h, missing, 8 h): the 8-hour step alone would pass under "ending".
        signal = series((-4, 4), (0, 4), (8, 8))
        self.assertUnavailable(signal, at(8) + PUB, "mixed_interval")

    def test_missing_newest_record_is_unavailable(self):
        signal = series((0, 8), (8, 8), (16, 8))
        for t in (at(24) + PUB, at(30), at(32) - S):
            self.assertUnavailable(signal, t, "overdue")

    def test_invalid_newest_record_never_falls_back(self):
        cases = [(0, "0.0001"), (3, "0.0001"), (12, "0.0001"), (None, "0.0001")]
        cases += [(8, "NaN"), (8, "Infinity"), (8, "-Infinity")]
        for interval, rate in cases:
            with self.subTest(interval=interval, rate=rate):
                signal = FundingSignal([rec(0), rec(8), rec(16), rec(24, interval, rate)])
                self.assertAvailable(signal, at(24) + PUB - S)
                for t in (at(24) + PUB, at(31)):
                    self.assertUnavailable(signal, t, "invalid_newest")

    def test_insufficient_history(self):
        for records in ([], [rec(0)], [rec(0), rec(8)]):
            with self.subTest(count=len(records)):
                signal = FundingSignal(records)
                self.assertUnavailable(signal, at(0), "insufficient_history")
                self.assertUnavailable(signal, at(20), "insufficient_history")

    def test_invalid_older_record(self):
        for position in (0, 1):
            for interval, rate in ((3, "0.0001"), (None, "0.0001"), (8, "NaN")):
                with self.subTest(position=position, interval=interval, rate=rate):
                    records = [rec(0), rec(8), rec(16)]
                    records[position] = rec(8 * position, interval, rate)
                    signal = FundingSignal(records)
                    self.assertUnavailable(signal, at(16) + PUB, "invalid_older")

    def test_unseen_shortening_with_missing_changed_record(self):
        # True cadence became 4 h after 16:00; the 20:00 record is missing. The
        # convention cannot see it: available until the old 8-hour deadline.
        signal = series((0, 8), (8, 8), (16, 8))
        self.assertAvailable(signal, at(20) + PUB + S)
        self.assertAvailable(signal, at(24) + PUB - S)
        self.assertUnavailable(signal, at(24) + PUB, "overdue")

    def test_duplicate_scheduled_times_are_an_integrity_failure(self):
        with self.assertRaises(DataError):
            FundingSignal([rec(0), rec(8), rec(8, offset_ms=500), rec(16)])

    def test_rate_boundary_is_strict(self):
        t = at(16) + PUB
        self.assertFalse(series((0, 8), (8, 8), (16, 8), rate="0.0005").state(t).blocks)
        high = series((0, 8), (8, 8), (16, 8), rate="0.00050001").state(t)
        self.assertTrue(high.available)
        self.assertTrue(high.blocks)
        self.assertEqual(high.reason, "high_funding")
        mixed = FundingSignal([rec(0, rate="0.001"), rec(8, rate="0.0005"), rec(16, rate="0.001")])
        self.assertFalse(mixed.state(t).blocks)

    def test_negative_funding_never_blocks(self):
        signal = series((0, 8), (8, 8), (16, 8), rate="-0.01")
        self.assertFalse(signal.state(at(16) + PUB).blocks)

    def test_recovery_after_a_gap(self):
        # The 24:00 settlement is missing.
        signal = series((0, 8), (8, 8), (16, 8), (32, 8), (40, 8), (48, 8))
        self.assertUnavailable(signal, at(32) + PUB, "step_mismatch")
        self.assertUnavailable(signal, at(40) + PUB, "step_mismatch")
        self.assertUnavailable(signal, at(48) + PUB - S, "step_mismatch")
        self.assertAvailable(signal, at(48) + PUB)


HEADER = "calc_time,funding_interval_hours,last_funding_rate\n"


class FundingParserTests(unittest.TestCase):
    def test_parses_ms_and_us_times_and_keeps_invalid_fields(self):
        text = HEADER + (
            f"{T0 + 11},8,0.00010000\n{(T0 + 8 * H + 47) * 1000},,0.0001\n{T0 + 16 * H},3,NaN\n"
        )
        records = parse_funding_rows(text, "2024-01")
        self.assertEqual([r.calc_time_ms for r in records], [T0 + 11, T0 + 8 * H + 47, T0 + 16 * H])
        self.assertEqual([r.interval_hours for r in records], [8, None, 3])
        self.assertEqual(records[0].scheduled_ms, T0)
        self.assertFalse(records[1].valid)
        self.assertFalse(records[2].rate.is_finite())

    def test_structure_errors_raise(self):
        bad = {
            "header": "time,interval,rate\n",
            "columns": HEADER + f"{T0},8\n",
            "time": HEADER + "abc,8,0.0001\n",
            "rate": HEADER + f"{T0},8,abc\n",
            "month": HEADER + f"{T0 - 1},8,0.0001\n",
            "order": HEADER + f"{T0 + H},8,0.0001\n{T0},8,0.0001\n",
            "duplicate": HEADER + f"{T0},8,0.0001\n{T0},8,0.0001\n",
        }
        for name, text in bad.items():
            with self.subTest(name), self.assertRaises(DataError):
                parse_funding_rows(text, "2024-01")
        with self.assertRaises(DataError):
            parse_funding_rows("", "2024-01")

    def test_reads_the_expected_archive_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.zip"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("BTCUSDT-fundingRate-2024-01.csv", HEADER + f"{T0},8,0.0001\n")
            path.write_bytes(buffer.getvalue())
            self.assertEqual(len(read_funding_archive(path, "BTCUSDT", "2024-01")), 1)
            with self.assertRaises(DataError):
                read_funding_archive(path, "ETHUSDT", "2024-01")


if __name__ == "__main__":
    unittest.main()
