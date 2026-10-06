"""The repairing kline reader (long-window data plan, Task 1; spec v1 section 5, rule 1).

``parse_rows_repaired`` returns the bars it can trust and the hours it cannot, where
``parse_rows`` rejects the whole archive. Its repair rule is ``audit.fix_closes``'s
refined rule, pinned here by a direct comparison with it.
"""

import csv
import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from test_backtest_data import JAN_2024_MS, make_zip, minute_rows, row
from test_backtest_loaders import hour_rows

from crypto_grid_bot.backtest.audit import fix_closes
from crypto_grid_bot.backtest.klines import (
    parse_rows,
    parse_rows_repaired,
    read_archive,
    read_archive_repaired,
)
from crypto_grid_bot.market_data.parsing import DataError

MONTH = "2024-01"
MIN = 60_000
HOUR = 3_600_000


def csv_row(open_ms, close_ms=None, *, step=MIN):
    """A valid row (``test_backtest_data.row``), its close time overridden if given."""
    fields = row(open_ms, step=step).split(",")
    if close_ms is not None:
        fields[6] = str(close_ms)
    return ",".join(fields)


def with_field(text, index, value):
    fields = text.split(",")
    fields[index] = value
    return ",".join(fields)


def text_of(*lines):
    return "\n".join(lines) + "\n"


def opens(result):
    return [bar.open_ms for bar in result.bars]


class SameBothWaysTests(unittest.TestCase):
    def test_valid_archive_reads_the_same_both_ways(self):
        # The archives tests/test_backtest_data.py builds and accepts: milliseconds and
        # microseconds, an internal gap with a partial month, bars across hours, hourly
        # rows, a whole month, and an empty file (which parse_rows accepts too).
        cases = {
            "milliseconds": (minute_rows(JAN_2024_MS, 3), "1m"),
            "microseconds": (minute_rows(JAN_2024_MS, 3, us=True), "1m"),
            "gap": (text_of(row(JAN_2024_MS + MIN), row(JAN_2024_MS + 5 * MIN)), "1m"),
            "across hours": (
                text_of(
                    row(JAN_2024_MS, o="1", h="2", low="0.5", c="1.5"),
                    row(JAN_2024_MS + MIN, o="1.5", h="3", low="1.4", c="2.5"),
                    row(JAN_2024_MS + HOUR, o="9", h="9", low="9", c="9"),
                ),
                "1m",
            ),
            "hourly": (hour_rows(JAN_2024_MS, 3), "1h"),
            "whole month": (hour_rows(JAN_2024_MS, 31 * 24), "1h"),
            "empty": ("", "1m"),
        }
        with tempfile.TemporaryDirectory() as temp:
            for name, (text, interval) in cases.items():
                with self.subTest(case=name):
                    bars, stats = parse_rows(text, interval, MONTH)
                    result = parse_rows_repaired(text, interval, MONTH)
                    self.assertEqual((bars, stats), (result.bars, result.stats))
                    self.assertEqual(
                        ("", frozenset(), frozenset()),
                        (result.unreadable, result.repaired, result.masked_hours),
                    )
                    # And through the zip: the same member the strict reader expects.
                    path = Path(temp) / f"{name}.zip".replace(" ", "-")
                    path.write_bytes(make_zip("ADAUSDT", interval, MONTH, text))
                    strict = read_archive(path, "ADAUSDT", interval, MONTH)
                    self.assertEqual(strict, (bars, stats))
                    self.assertEqual(
                        result, read_archive_repaired(path, "ADAUSDT", interval, MONTH)
                    )


class RepairRuleTests(unittest.TestCase):
    def test_repair_rule_matches_the_refined_rule(self):
        # Review Focus 1. The cases mirror tests/test_backtest_audit.py: a truncated
        # close before an adjacent row (2021-12, 2019-06) and before a gap are repaired;
        # an unaligned open, and a next row opening before open + step, are not.
        hours = [JAN_2024_MS + n * HOUR for n in range(5)]
        adjacent = hours[0]  # truncated; the next row opens exactly open + step
        gapped = hours[1] + 5 * MIN  # truncated; the next row opens two steps later
        unaligned = hours[2] + 14_789  # never repaired, whatever follows
        early = hours[3] + 10 * MIN  # truncated; the next row opens at its own open
        last = hours[4]  # the file's last row, close open + step - 2
        text = text_of(
            csv_row(adjacent, adjacent + 30_000),
            csv_row(adjacent + MIN),
            csv_row(gapped, gapped + 20_000),
            csv_row(gapped + 2 * MIN),
            csv_row(unaligned, hours[2] + MIN),
            csv_row(early, early + 41_646),
            csv_row(early),
            csv_row(last, last + MIN - 2),
        )
        result = parse_rows_repaired(text, "1m", MONTH)
        self.assertEqual("", result.unreadable)
        self.assertEqual(frozenset({adjacent, gapped, last}), result.repaired)
        self.assertEqual(frozenset({hours[2], hours[3]}), result.masked_hours)
        # The unaligned row and the truncated row before its duplicate are dropped; the
        # duplicate, judged against the last kept row, is kept (its hour is masked).
        self.assertEqual(
            [adjacent, adjacent + MIN, gapped, gapped + 2 * MIN, early, last], opens(result)
        )
        self.assertEqual(
            (6, adjacent, last, ("ms",)),
            (
                result.stats.rows,
                result.stats.first_open_ms,
                result.stats.last_open_ms,
                result.stats.timestamp_units,
            ),
        )
        # Exactly the rows audit's refined rule fixes, and nothing else.
        fixed = fix_closes(list(csv.reader(io.StringIO(text))), "1m", "refined")[1]
        self.assertEqual(fixed, sorted(result.repaired))
        # The repair touches the close time only: the strict parser reads the same bar.
        self.assertEqual(parse_rows(csv_row(adjacent) + "\n", "1m", MONTH)[0][0], result.bars[0])

    def test_hourly_rows_are_repaired_the_same_way(self):
        text = text_of(
            csv_row(JAN_2024_MS, JAN_2024_MS + 1_000_000, step=HOUR),
            csv_row(JAN_2024_MS + HOUR, step=HOUR),
            csv_row(JAN_2024_MS + 2 * HOUR, JAN_2024_MS + 2 * HOUR + 5, step=HOUR),
            csv_row(JAN_2024_MS + 2 * HOUR + 30 * MIN, step=HOUR),
        )
        result = parse_rows_repaired(text, "1h", MONTH)
        self.assertEqual(frozenset({JAN_2024_MS}), result.repaired)
        self.assertEqual(frozenset({JAN_2024_MS + 2 * HOUR}), result.masked_hours)
        self.assertEqual([JAN_2024_MS, JAN_2024_MS + HOUR], opens(result))


class UntrustedRowTests(unittest.TestCase):
    def test_duplicate_and_out_of_order_rows_mask_only_their_hours(self):
        # Five hours of minutes. Minute 70 (hour 1) is duplicated; minute 130 (hour 2)
        # arrives after minute 131 instead of before it. Both extra rows are dropped,
        # the first copy of 70 stays, and every other bar is kept.
        lines = []
        for minute in range(300):
            if minute == 130:
                continue
            lines.append(csv_row(JAN_2024_MS + minute * MIN))
            if minute == 70:
                lines.append(csv_row(JAN_2024_MS + 70 * MIN))
            if minute == 131:
                lines.append(csv_row(JAN_2024_MS + 130 * MIN))
        with self.assertRaises(DataError):
            parse_rows(text_of(*lines), "1m", MONTH)
        result = parse_rows_repaired(text_of(*lines), "1m", MONTH)
        self.assertEqual(
            frozenset({JAN_2024_MS + HOUR, JAN_2024_MS + 2 * HOUR}), result.masked_hours
        )
        self.assertEqual(frozenset(), result.repaired)
        # Bars and statistics are those of the rows that were kept, as parse_rows has them.
        kept = text_of(*(csv_row(JAN_2024_MS + m * MIN) for m in range(300) if m != 130))
        self.assertEqual(parse_rows(kept, "1m", MONTH), (result.bars, result.stats))

    def test_out_of_order_row_masks_the_previous_rows_hour_too(self):
        # Minute 59 (hour 0) arrives after minute 60 (hour 1): both hours are masked.
        lines = [csv_row(JAN_2024_MS + m * MIN) for m in range(120) if m != 59]
        lines.insert(60, csv_row(JAN_2024_MS + 59 * MIN))
        result = parse_rows_repaired(text_of(*lines), "1m", MONTH)
        self.assertEqual(frozenset({JAN_2024_MS, JAN_2024_MS + HOUR}), result.masked_hours)
        self.assertEqual([JAN_2024_MS + m * MIN for m in range(120) if m != 59], opens(result))

    def test_other_untrusted_rows_mask_only_their_hour(self):
        # Each bad row sits between two good ones, in hours 0 and 2.
        middle = JAN_2024_MS + HOUR
        us_open = row(middle, us=True).replace(str(middle * 1000), str(middle * 1000 + 999), 1)
        cases = {
            "too few columns": (",".join(csv_row(middle).split(",")[:5]), middle),
            "malformed price": (with_field(csv_row(middle), 1, "x"), middle),
            "inconsistent OHLC": (row(middle, h="0.95"), middle),
            "taker volume": (row(middle, volume="3"), middle),
            "mixed units": (with_field(csv_row(middle), 6, str(middle + MIN - 1) + "999"), middle),
            "unaligned open": (row(middle + 1), middle),
            "microsecond open off its boundary": (us_open, middle),
            "outside the month": (row(JAN_2024_MS - MIN), JAN_2024_MS - HOUR),
            # Its close would be repaired, but the row is dropped for the month.
            "truncated close outside the month": (
                csv_row(JAN_2024_MS - MIN, JAN_2024_MS - MIN + 5),
                JAN_2024_MS - HOUR,
            ),
        }
        for name, (bad, hour) in cases.items():
            with self.subTest(case=name):
                text = text_of(csv_row(JAN_2024_MS), bad, csv_row(JAN_2024_MS + 2 * HOUR))
                with self.assertRaises(DataError):
                    parse_rows(text, "1m", MONTH)
                result = parse_rows_repaired(text, "1m", MONTH)
                self.assertEqual("", result.unreadable)
                self.assertEqual(frozenset({hour}), result.masked_hours)
                self.assertEqual(frozenset(), result.repaired)
                self.assertEqual([JAN_2024_MS, JAN_2024_MS + 2 * HOUR], opens(result))


class UnreadableTests(unittest.TestCase):
    def assertUnreadable(self, result):
        self.assertNotEqual("", result.unreadable)
        self.assertEqual(([], 0), (result.bars, result.stats.rows))
        self.assertEqual((frozenset(), frozenset()), (result.repaired, result.masked_hours))

    def test_unreadable_archive_has_no_bars(self):
        text = minute_rows(JAN_2024_MS, 3).encode()
        name = f"ADAUSDT-1m-{MONTH}.csv"
        cases = {
            "two members": ({name: text, "ADAUSDT-1m-2024-02.csv": text}, "exactly"),
            "wrong member": ({"other.csv": text}, "exactly"),
            "not ASCII": ({name: b"\xff\xfe"}, "ASCII"),
        }
        with tempfile.TemporaryDirectory() as temp:
            for label, (members, reason) in cases.items():
                with self.subTest(case=label):
                    path = Path(temp) / f"{label.replace(' ', '-')}.zip"
                    with zipfile.ZipFile(path, "w") as archive:
                        for member, content in members.items():
                            archive.writestr(member, content)
                    result = read_archive_repaired(path, "ADAUSDT", "1m", MONTH)
                    self.assertUnreadable(result)
                    self.assertIn(reason, result.unreadable)
                    with self.assertRaises(DataError):
                        read_archive(path, "ADAUSDT", "1m", MONTH)
            junk = Path(temp) / "junk.zip"
            junk.write_bytes(b"not a zip")
            result = read_archive_repaired(junk, "ADAUSDT", "1m", MONTH)
            self.assertUnreadable(result)
            self.assertIn("invalid zip", result.unreadable)

    def test_malformed_open_makes_the_archive_unreadable(self):
        good = csv_row(JAN_2024_MS)
        next_row = csv_row(JAN_2024_MS + MIN)
        cases = {
            "non-numeric open": with_field(next_row, 0, "abc"),
            "signed open": with_field(next_row, 0, "-5"),
            "fractional open": with_field(next_row, 0, f"{JAN_2024_MS + MIN}.5"),
            "empty open": with_field(next_row, 0, ""),
            "too many digits": with_field(next_row, 0, "9" * 18),
            "empty line": "",
        }
        for name, bad in cases.items():
            with self.subTest(case=name):
                text = text_of(good, bad, csv_row(JAN_2024_MS + 2 * MIN))
                result = parse_rows_repaired(text, "1m", MONTH)
                self.assertUnreadable(result)
                self.assertIn("line 2", result.unreadable)

    def test_a_malformed_close_masks_only_its_hour(self):
        middle = JAN_2024_MS + HOUR
        text = text_of(
            csv_row(JAN_2024_MS),
            with_field(csv_row(middle), 6, "abc"),
            csv_row(JAN_2024_MS + 2 * HOUR),
        )
        result = parse_rows_repaired(text, "1m", MONTH)
        self.assertEqual("", result.unreadable)
        self.assertEqual(frozenset({middle}), result.masked_hours)
        self.assertEqual([JAN_2024_MS, JAN_2024_MS + 2 * HOUR], opens(result))

    def test_a_row_with_a_readable_open_and_missing_fields_is_only_untrusted(self):
        text = text_of(csv_row(JAN_2024_MS), str(JAN_2024_MS + HOUR), csv_row(JAN_2024_MS + MIN))
        result = parse_rows_repaired(text, "1m", MONTH)
        self.assertEqual("", result.unreadable)
        self.assertEqual(frozenset({JAN_2024_MS + HOUR}), result.masked_hours)
        self.assertEqual([JAN_2024_MS, JAN_2024_MS + MIN], opens(result))


class ScopeTests(unittest.TestCase):
    def test_daily_archives_and_reserved_months_are_refused_not_reported_unreadable(self):
        # Daily bars keep the strict reader; the reserved window is a policy refusal, not
        # a defect of the archive, so it must raise and never come back as "unreadable".
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "a.zip"
            path.write_bytes(make_zip("ADAUSDT", "1d", MONTH, ""))
            for call in (
                lambda: parse_rows_repaired("", "1d", MONTH),
                lambda: parse_rows_repaired("", "5m", MONTH),
                lambda: read_archive_repaired(path, "ADAUSDT", "1d", MONTH),
                lambda: read_archive_repaired(path, "ADAUSDT", "1m", "2025-01"),
                lambda: read_archive_repaired(path, "../ADAUSDT", "1m", MONTH),
                lambda: parse_rows_repaired("", "1m", "2024-13"),
            ):
                with self.assertRaises(DataError):
                    call()


if __name__ == "__main__":
    unittest.main()
