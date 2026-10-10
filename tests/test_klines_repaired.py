"""The repairing kline reader (long-window data plan, Task 1; spec v1 section 5, rule 1).

``parse_rows_repaired`` returns the bars it can trust and the hours it cannot, where
``parse_rows`` rejects the whole archive. Its repair rule is ``audit.fix_closes``'s
refined rule, pinned here by a direct comparison with it.
"""

import csv
import io
import lzma
import random
import tempfile
import unittest
import zipfile
import zlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_backtest_data import (
    JAN_2024_MS,
    corrupt_zip,
    encrypted_zip,
    make_zip,
    minute_rows,
    row,
    unsupported_zip,
)
from test_backtest_loaders import hour_rows

from crypto_grid_bot.backtest.audit import fix_closes
from crypto_grid_bot.backtest.klines import (
    parse_rows,
    parse_rows_repaired,
    read_archive,
    read_archive_repaired,
    read_member,
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


def us_row(open_ms, close_us=None):
    """A valid microsecond row, its close time (in microseconds) overridden if given."""
    text = row(open_ms, us=True)
    return text if close_us is None else with_field(text, 6, str(close_us))


def random_minute_rows(rng, count):
    """``count`` minute rows with strictly increasing opens: (open ms, close ms) pairs.

    Some opens are off their minute, some follow an aligned row inside its own minute (so
    they block its repair), some leave gaps; some closes are off the boundary.
    """
    pairs = []
    minute = 0
    for index in range(count):
        previous = pairs[-1][0] if pairs else None
        if previous is not None and previous % MIN == 0 and rng.random() < 0.1:
            open_ms = previous + rng.randrange(1, MIN)
        else:
            minute += rng.choice((1, 1, 1, 2, 5)) if index else 0
            open_ms = JAN_2024_MS + minute * MIN
            if rng.random() < 0.1:
                open_ms += rng.randrange(1, MIN)
        close_ms = open_ms + MIN - 1
        if rng.random() < 0.3:
            while close_ms == open_ms + MIN - 1:
                close_ms = open_ms + rng.randrange(-MIN, 2 * MIN)
        pairs.append((open_ms, close_ms))
    return pairs


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
        # close before an adjacent row (2021-12, 2019-06) and before a gap are repaired,
        # and so are a close at or past open + step and a close before the open; an
        # unaligned open, and a next row opening before open + step, are not.
        hours = [JAN_2024_MS + n * HOUR for n in range(9)]
        adjacent = hours[0]  # truncated; the next row opens exactly open + step
        gapped = hours[1] + 5 * MIN  # truncated; the next row opens two steps later
        unaligned = hours[2] + 14_789  # never repaired, whatever follows
        early = hours[3] + 10 * MIN  # truncated; the next row opens at its own open
        past = hours[4]  # close at open + step, one millisecond past the boundary
        backwards = hours[5]  # close one millisecond before the open
        shadowed = hours[6] + 5 * MIN  # truncated; its raw next row is dropped (below)
        dropped_next = shadowed + MIN + 14_789  # unaligned, one step later: dropped
        blocked = hours[7] + 5 * MIN  # truncated; its raw next row opens within the step
        blocker = blocked + 14_789  # unaligned, dropped, yet it blocks the repair above
        last = hours[8]  # the file's last row, close open + step - 2
        text = text_of(
            csv_row(adjacent, adjacent + 30_000),
            csv_row(adjacent + MIN),
            csv_row(gapped, gapped + 20_000),
            csv_row(gapped + 2 * MIN),
            csv_row(unaligned, hours[2] + MIN),
            csv_row(early, early + 41_646),
            csv_row(early),
            csv_row(past, past + MIN),
            csv_row(past + MIN),
            csv_row(backwards, backwards - 1),
            csv_row(backwards + MIN),
            csv_row(shadowed, shadowed + 20_000),
            csv_row(dropped_next),
            csv_row(blocked, blocked + 20_000),
            csv_row(blocker),
            csv_row(blocked + MIN),
            csv_row(last, last + MIN - 2),
        )
        result = parse_rows_repaired(text, "1m", MONTH)
        self.assertEqual("", result.unreadable)
        # `following` is the raw next row in file order, as in audit.fix_closes, whether or
        # not that row is kept: `shadowed` is repaired although its next row is dropped,
        # and `blocked` is not, because its dropped next row opens before open + step.
        self.assertEqual(
            frozenset({adjacent, gapped, past, backwards, shadowed, last}), result.repaired
        )
        self.assertEqual(frozenset({hours[2], hours[3], hours[6], hours[7]}), result.masked_hours)
        # The unaligned rows, the truncated row before its duplicate and `blocked` are
        # dropped; the duplicate, judged against the last kept row, is kept.
        self.assertEqual(
            [
                adjacent,
                adjacent + MIN,
                gapped,
                gapped + 2 * MIN,
                early,
                past,
                past + MIN,
                backwards,
                backwards + MIN,
                shadowed,
                blocked + MIN,
                last,
            ],
            opens(result),
        )
        self.assertEqual(
            (12, adjacent, last, ("ms",)),
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

    def test_random_rows_are_repaired_as_the_refined_rule_says_in_both_units(self):
        # Codex review of #186: a truncated microsecond close must reach the repair rule,
        # not be refused by the parser first. The same random rows, in milliseconds and in
        # microseconds (a close on its boundary ends in 999 us, any other close in some other
        # number of microseconds), are repaired exactly where audit.fix_closes repairs them,
        # every other untrusted row masks its hour, and both units read the same bars.
        rng = random.Random(186)
        pairs = random_minute_rows(rng, 2_000)
        ms_lines, us_lines = [], []
        for open_ms, close_ms in pairs:
            on_boundary = close_ms == open_ms + MIN - 1
            close_us = (open_ms + MIN) * 1000 - 1 if on_boundary else close_ms * 1000
            if not on_boundary:
                close_us += rng.randrange(999)  # 0 to 998 us: never the boundary's 999
            ms_lines.append(csv_row(open_ms, close_ms))
            us_lines.append(us_row(open_ms, close_us))
        in_ms = parse_rows_repaired(text_of(*ms_lines), "1m", MONTH)
        in_us = parse_rows_repaired(text_of(*us_lines), "1m", MONTH)
        fixed = fix_closes(list(csv.reader(io.StringIO(text_of(*ms_lines)))), "1m", "refined")[1]
        self.assertEqual(fixed, sorted(in_ms.repaired))
        self.assertEqual(fixed, sorted(in_us.repaired))
        untrusted = {
            open_ms - open_ms % HOUR
            for open_ms, close_ms in pairs
            if open_ms % MIN or (close_ms != open_ms + MIN - 1 and open_ms not in fixed)
        }
        self.assertEqual(frozenset(untrusted), in_ms.masked_hours)
        self.assertEqual(frozenset(untrusted), in_us.masked_hours)
        self.assertEqual(in_ms.bars, in_us.bars)
        self.assertEqual(replace(in_ms.stats, timestamp_units=("us",)), in_us.stats)
        # The draw exercises every branch: repairs, blocked repairs and unaligned opens.
        blocked = [o for o, c in pairs if o % MIN == 0 and c != o + MIN - 1 and o not in fixed]
        self.assertTrue(fixed and blocked and any(o % MIN for o, _ in pairs))

    def test_a_microsecond_close_in_the_right_millisecond_is_still_off_its_boundary(self):
        # A close of open + step - 1 ms that does not end in 999 us is off its boundary,
        # though its millisecond is right: it is repaired where the rule allows, its hour is
        # masked where the rule does not, and it is never kept as it stands.
        repaired, blocked = JAN_2024_MS, JAN_2024_MS + HOUR
        text = text_of(
            us_row(repaired, (repaired + MIN - 1) * 1000 + 500),
            us_row(repaired + MIN),
            us_row(blocked, (blocked + MIN - 1) * 1000),
            us_row(blocked + 30_000),  # inside the step: blocks the repair, and is unaligned
            us_row(blocked + 2 * MIN),
        )
        with self.assertRaisesRegex(DataError, "not a candle boundary"):
            parse_rows(text, "1m", MONTH)
        result = parse_rows_repaired(text, "1m", MONTH)
        self.assertEqual("", result.unreadable)
        self.assertEqual(frozenset({repaired}), result.repaired)
        self.assertEqual(frozenset({blocked}), result.masked_hours)
        self.assertEqual([repaired, repaired + MIN, blocked + 2 * MIN], opens(result))
        self.assertEqual(("us",), result.stats.timestamp_units)
        # The repair touches the close time only: the strict parser reads the same bar.
        self.assertEqual(parse_rows(us_row(repaired) + "\n", "1m", MONTH)[0][0], result.bars[0])


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

    def test_an_out_of_order_row_masks_both_hours_whatever_else_is_wrong(self):
        # The last kept row is in hour 1 and the bad row opens before it, in hour 0 (or
        # before the month). Both hours are masked even where another check would have
        # rejected the row first, and the row is dropped, never reported repaired.
        hour_0, hour_1 = JAN_2024_MS, JAN_2024_MS + HOUR
        kept = hour_1 + 5 * MIN
        cases = {
            "valid row": (csv_row(hour_0 + MIN), hour_0),
            "unaligned open": (row(hour_0 + 14_789), hour_0),
            "outside the month": (row(JAN_2024_MS - MIN), JAN_2024_MS - HOUR),
            "malformed close": (with_field(csv_row(hour_0 + MIN), 6, "abc"), hour_0),
            "too few columns": (",".join(csv_row(hour_0 + MIN).split(",")[:5]), hour_0),
            "inconsistent OHLC": (row(hour_0 + MIN, h="0.95"), hour_0),
            # Its close would be repaired: its next row opens two hours later.
            "truncated close": (csv_row(hour_0 + MIN, hour_0 + MIN + 5), hour_0),
        }
        for name, (bad, hour) in cases.items():
            with self.subTest(case=name):
                text = text_of(csv_row(kept), bad, csv_row(JAN_2024_MS + 2 * HOUR))
                result = parse_rows_repaired(text, "1m", MONTH)
                self.assertEqual("", result.unreadable)
                self.assertEqual(frozenset({hour, hour_1}), result.masked_hours)
                self.assertEqual(frozenset(), result.repaired)
                self.assertEqual([kept, JAN_2024_MS + 2 * HOUR], opens(result))

    def test_other_untrusted_rows_mask_only_their_hour(self):
        # Each bad row sits between two good ones, in hours 0 and 2, except the rows before
        # the month: after an in-month row they would also be out of order, which masks
        # that row's hour too (the test above), so they come first and only the month rule
        # applies.
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
        first = {"outside the month", "truncated close outside the month"}
        for name, (bad, hour) in cases.items():
            with self.subTest(case=name):
                lines = [csv_row(JAN_2024_MS), bad, csv_row(JAN_2024_MS + 2 * HOUR)]
                text = text_of(*([bad, lines[0], lines[2]] if name in first else lines))
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

    def test_an_undecodable_member_is_unreadable_not_an_error(self):
        # A member flagged deflate whose stream is garbage: read_member lets zlib's error
        # through (the strict readers still raise it); the repairing reader reports it.
        name = f"ADAUSDT-1m-{MONTH}.csv"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "garbage.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as archive:
                archive.writestr(name, b"\x01\x00\x00\x00\x00")  # a stored block, bad lengths
            data = bytearray(path.read_bytes())
            deflate = zipfile.ZIP_DEFLATED.to_bytes(2, "little")
            data[8:10] = deflate  # the local header's compression method
            central = data.rfind(b"PK\x01\x02")
            data[central + 10 : central + 12] = deflate  # and the central directory's
            path.write_bytes(data)
            with self.assertRaises(zlib.error):
                read_member(path, name)
            with self.assertRaises(zlib.error):
                read_archive(path, "ADAUSDT", "1m", MONTH)
            self.assertUnreadable(read_archive_repaired(path, "ADAUSDT", "1m", MONTH))

    def test_every_undecodable_member_is_unreadable_not_an_error(self):
        # Codex review of #186: a checksum-valid archive whose member is encrypted (zipfile
        # raises RuntimeError) or compressed by a method zipfile cannot read (its subclass
        # NotImplementedError) is spec v1 section 5 rule 1's archive that cannot be read:
        # its hours are absent and masked, not fatal to mask_job. So is a corrupt bzip2 or
        # LZMA stream, as a corrupt deflate stream already was. The strict readers still
        # raise.
        text = minute_rows(JAN_2024_MS, 3)
        longer = minute_rows(JAN_2024_MS, 60)
        cases = {
            "encrypted member": (encrypted_zip("ADAUSDT", "1m", MONTH, text), RuntimeError),
            "unsupported compression": (
                unsupported_zip("ADAUSDT", "1m", MONTH, text),
                NotImplementedError,
            ),
            "corrupt bzip2 stream": (
                corrupt_zip("ADAUSDT", "1m", MONTH, longer, zipfile.ZIP_BZIP2),
                OSError,
            ),
            "corrupt LZMA stream": (
                corrupt_zip("ADAUSDT", "1m", MONTH, longer, zipfile.ZIP_LZMA),
                lzma.LZMAError,
            ),
        }
        with tempfile.TemporaryDirectory() as temp:
            for label, (body, error) in cases.items():
                with self.subTest(case=label):
                    path = Path(temp) / f"{label.replace(' ', '-')}.zip"
                    path.write_bytes(body)
                    with self.assertRaises(error) as raised:
                        read_archive(path, "ADAUSDT", "1m", MONTH)
                    self.assertIs(error, type(raised.exception))
                    self.assertUnreadable(read_archive_repaired(path, "ADAUSDT", "1m", MONTH))

    def test_an_errno_less_os_error_is_unreadable_only_from_a_bzip2_member(self):
        # Codex review of #189: bzip2's "Invalid data stream" is an OSError without an
        # errno, and so may be another failure while reading. Only a bzip2 member's makes
        # the archive unreadable; from a deflate or a stored member it still raises.
        name = f"ADAUSDT-1m-{MONTH}.csv"
        failure = OSError("Invalid data stream")
        with tempfile.TemporaryDirectory() as temp:
            for method in (zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED, zipfile.ZIP_BZIP2):
                path = Path(temp) / f"method-{method}.zip"
                with zipfile.ZipFile(path, "w", method) as archive:
                    archive.writestr(name, minute_rows(JAN_2024_MS, 3))
                with (
                    self.subTest(method=method),
                    patch.object(zipfile.ZipExtFile, "read", side_effect=failure),
                ):
                    if method == zipfile.ZIP_BZIP2:
                        self.assertUnreadable(read_archive_repaired(path, "ADAUSDT", "1m", MONTH))
                        continue
                    with self.assertRaises(OSError) as raised:
                        read_archive_repaired(path, "ADAUSDT", "1m", MONTH)
                    self.assertIs(failure, raised.exception)

    def test_a_file_system_error_still_raises(self):
        # An OSError with an errno is the file system's, not the archive's: a denied open
        # must not turn a month's hours into masked ones.
        denied = PermissionError(13, "Permission denied")
        with (
            patch("crypto_grid_bot.backtest.klines.read_member", side_effect=denied),
            self.assertRaises(PermissionError),
        ):
            read_archive_repaired(Path("a.zip"), "ADAUSDT", "1m", MONTH)

    def test_an_eof_while_reading_is_unreadable_and_a_missing_file_still_raises(self):
        with patch("crypto_grid_bot.backtest.klines.read_member", side_effect=EOFError()):
            result = read_archive_repaired(Path("a.zip"), "ADAUSDT", "1m", MONTH)
        self.assertUnreadable(result)  # the reason is never empty, which would mean readable
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(FileNotFoundError):
            read_archive_repaired(Path(temp) / "missing.zip", "ADAUSDT", "1m", MONTH)

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
