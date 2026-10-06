"""The hour mask and the 17% rule, month by month (long-window data plan, Task 2).

Spec v1 section 5, rules 1, 2, 3 and 5, "The post-mask expected set" and the 17% rule. The
mask is pure: it takes the repairing reader's ``RepairedRead``s for one symbol-month, so the
duplicate and repair cases here go through ``parse_rows_repaired`` and the real reader, and
only the large months and the counts the reader already guarantees are built by hand.
"""

import ast
import unittest
from datetime import UTC, datetime
from decimal import Decimal as D
from fractions import Fraction
from pathlib import Path

from test_backtest_data import JAN_2024_MS, row

from crypto_grid_bot.backtest import audit, masking
from crypto_grid_bot.backtest.dataset import BasketExclusion
from crypto_grid_bot.backtest.klines import (
    FileStats,
    Kline,
    RepairedRead,
    month_bounds_ms,
    parse_rows_repaired,
)
from crypto_grid_bot.backtest.masking import (
    SEVENTEEN,
    apply_seventeen_percent,
    hourly_only_month_mask,
    masked_days,
    real_defect_share,
    traded_month_mask,
)

MIN = 60_000
HOUR = 3_600_000
DAY = 86_400_000
MONTH = "2024-01"
JAN = JAN_2024_MS
SOL_LISTING = int(datetime(2020, 8, 11, 6, tzinfo=UTC).timestamp() * 1000)


def hour(n, base=JAN):
    """The open of the ``n``-th hour from ``base``."""
    return base + n * HOUR


def around(first, count, month=MONTH, symbol="TESTUSDT"):
    """Exclusion ranges that leave exactly the ``count`` hours from ``first`` expected."""
    start, end = month_bounds_ms(month)
    last = first + count * HOUR
    ranges = [BasketExclusion(symbol, start, first, "test")] if first > start else []
    return ranges + ([BasketExclusion(symbol, last, end, "test")] if last < end else [])


def minute_lines(h, *, skip=(), volume="10"):
    """The rows of hour ``h``'s minutes, minus the minute offsets in ``skip``."""
    return [row(h + i * MIN, volume=volume) for i in range(60) if i not in skip]


def hourly_line(open_ms, *, volume="600", **prices):
    """An hourly row; its volume is 60 minutes of volume 10, as ``minute_lines`` gives."""
    return row(open_ms, step=HOUR, volume=volume, **prices)


def truncated(line):
    """The row with its close one ms early: off the boundary, and repairable."""
    fields = line.split(",")
    fields[6] = str(int(fields[6]) - 1)
    return ",".join(fields)


def text_of(*lines):
    return "".join(f"{line}\n" for line in lines)


def minutes_of(*lines):
    return parse_rows_repaired(text_of(*lines), "1m", MONTH)


def hourly_of(*lines, month=MONTH):
    return parse_rows_repaired(text_of(*lines), "1h", month)


def minute_klines(h, *, count=60, volume="10", open_="1.0"):
    return [
        Kline(h + i * MIN, D(open_), D("1.2"), D("0.9"), D("1.1"), D(volume), D("11"), D("4"))
        for i in range(count)
    ]


def official_kline(h, *, volume="600", open_="1.0"):
    return Kline(h, D(open_), D("1.2"), D("0.9"), D("1.1"), D(volume), D("660"), D("240"))


def hand_read(bars, *, repaired=(), masked=()):
    """A ``RepairedRead`` built by hand; the mask never reads its ``stats``."""
    stats = FileStats(len(bars), 0, 0, 0, None, None, ())
    return RepairedRead(list(bars), stats, frozenset(repaired), frozenset(masked), "")


class HourEntryTests(unittest.TestCase):
    def test_clean_hour_enters_and_incomplete_hour_is_masked(self):
        h = [hour(i) for i in range(5)]
        minutes = minutes_of(
            *minute_lines(h[0]), *minute_lines(h[1], skip={30}), *minute_lines(h[3])
        )
        hourly = hourly_of(hourly_line(h[0]), hourly_line(h[1], volume="590"), hourly_line(h[2]))
        mask = traded_month_mask(minutes, hourly, MONTH, around(h[0], 5))
        self.assertEqual(MONTH, mask.month)
        self.assertEqual(frozenset(h), mask.expected)
        self.assertEqual(frozenset(h[1:]), mask.masked)  # rule 2: 59 minutes mask the hour
        self.assertEqual(
            {
                h[1]: "incomplete hour",
                h[2]: "no minute bars",
                h[3]: "no hourly bar",
                h[4]: "absent from both archives",
            },
            mask.reasons,
        )
        self.assertIsInstance(mask.reasons, dict)
        self.assertEqual(mask.masked, mask.defects)
        self.assertEqual(frozenset(), mask.open_only)
        self.assertEqual(frozenset(), mask.repaired)
        self.assertFalse(mask.excluded)

    def test_repaired_hour_needs_an_exact_match(self):
        # Review Focus 2. 600.3 against the minutes' 600 is 0.05% off: drift under
        # drift-tolerance-v1, a mismatch against a repaired row's exact (Decimal(0)) test.
        h = hour(0)
        exclusions = around(h, 1)
        minutes = minute_lines(h)
        repaired_minute = [*minutes[:-1], truncated(minutes[-1])]
        drifted, exact = hourly_line(h, volume="600.3"), hourly_line(h)

        unrepaired = traded_month_mask(minutes_of(*minutes), hourly_of(drifted), MONTH, exclusions)
        self.assertEqual(frozenset(), unrepaired.masked)  # enters as drift
        self.assertEqual(frozenset(), unrepaired.repaired)

        cases = {
            "repaired hourly row": (minutes_of(*minutes), hourly_of(truncated(drifted))),
            "repaired minute row": (minutes_of(*repaired_minute), hourly_of(drifted)),
        }
        for name, (minute_read, hourly_read) in cases.items():
            with self.subTest(case=name):
                mask = traded_month_mask(minute_read, hourly_read, MONTH, exclusions)
                self.assertEqual(frozenset({h}), mask.masked)
                self.assertEqual({h: "mismatch on volume"}, mask.reasons)
                self.assertEqual(frozenset({h}), mask.repaired)
                self.assertEqual(frozenset({h}), mask.defects)

        # Review Focus 1: a repaired hour that matches exactly is admitted.
        admitted = traded_month_mask(
            minutes_of(*repaired_minute), hourly_of(truncated(exact)), MONTH, exclusions
        )
        self.assertEqual(frozenset(), admitted.masked)
        self.assertEqual(frozenset({h}), admitted.repaired)

    def test_extra_minute_or_second_hourly_bar_masks_the_hour(self):
        # The reader keeps one copy of a duplicated row, so the hour's bars look right:
        # only the reader's masked_hours tell the mask that it was not.
        h = [hour(i) for i in range(3)]
        first_hour = minute_lines(h[0])
        duplicated = [*first_hour[:31], first_hour[30], *first_hour[31:]]  # minute 30 twice
        minutes = minutes_of(*duplicated, *minute_lines(h[1]), *minute_lines(h[2]))
        hourly = hourly_of(
            hourly_line(h[0]), hourly_line(h[1]), hourly_line(h[1]), hourly_line(h[2])
        )
        self.assertEqual(60, sum(h[0] <= bar.open_ms < h[1] for bar in minutes.bars))
        self.assertEqual(frozenset({h[0]}), minutes.masked_hours)
        self.assertEqual(h, [bar.open_ms for bar in hourly.bars])
        self.assertEqual(frozenset({h[1]}), hourly.masked_hours)

        mask = traded_month_mask(minutes, hourly, MONTH, around(h[0], 3))
        self.assertEqual(frozenset(h[:2]), mask.masked)
        self.assertEqual({h[0]: "untrusted row", h[1]: "untrusted row"}, mask.reasons)

    def test_the_mask_rechecks_the_counts_the_reader_guarantees(self):
        # The reader never hands over two bars at one open or an off-grid minute, but a
        # read built by hand can: the mask counts them instead of trusting the reader.
        h = [hour(i) for i in range(2)]
        exclusions = around(h[0], 2)
        two_hourly = [official_kline(h[0]), official_kline(h[0]), official_kline(h[1])]
        extra_minute = [*minute_klines(h[0]), *minute_klines(h[1])]
        extra_minute.insert(31, minute_klines(h[0] + 30 * MIN + 1_000, count=1)[0])  # off-grid
        mask = traded_month_mask(hand_read(extra_minute), hand_read(two_hourly), MONTH, exclusions)
        self.assertEqual({h[0]: "extra hourly bar"}, mask.reasons)
        only_extra_minute = traded_month_mask(
            hand_read(extra_minute),
            hand_read([official_kline(h[0]), official_kline(h[1])]),
            MONTH,
            exclusions,
        )
        self.assertEqual({h[0]: "extra minute bars"}, only_extra_minute.reasons)
        hourly_only = hourly_only_month_mask(hand_read(two_hourly), MONTH, exclusions)
        self.assertEqual({h[0]: "extra hourly bar"}, hourly_only.reasons)

    def test_a_missing_minute_is_an_incomplete_hour_whatever_else_the_hour_holds(self):
        # Rule 2: fewer than 60 distinct minutes on the grid is an incomplete hour, even
        # when a duplicate or an off-grid bar brings the hour's bar count back to 60.
        h = [hour(i) for i in range(2)]
        official = [official_kline(h[0]), official_kline(h[1])]
        valid = minute_klines(h[0])
        gap = valid[:30] + valid[31:]  # minute 30 is missing
        duplicate, off_grid = valid[10], minute_klines(h[0] + 45 * MIN + 1_000, count=1)[0]
        cases = {
            "59 valid": (gap, "incomplete hour"),
            "59 valid and a duplicate": ([*gap, duplicate], "incomplete hour"),
            "59 valid and an off-grid bar": ([*gap, off_grid], "incomplete hour"),
            "60 valid and a duplicate": ([*valid, duplicate], "extra minute bars"),
            "60 valid and an off-grid bar": ([*valid, off_grid], "extra minute bars"),
        }
        for name, (bars, reason) in cases.items():
            with self.subTest(case=name):
                minutes = hand_read([*bars, *minute_klines(h[1])])
                mask = traded_month_mask(minutes, hand_read(official), MONTH, around(h[0], 2))
                self.assertEqual({h[0]: reason}, mask.reasons)

    def test_untrusted_hours_outside_the_month_or_its_exclusions_never_count(self):
        # A masked row can sit before the month (out of order) or outside it, and a
        # documented exclusion's hours are not the month's. Only expected hours mask.
        start, end = month_bounds_ms(MONTH)
        h = hour(10)
        exclusions = around(h, 1)
        outside = {start - HOUR, end, hour(3)}  # before the month, after it, excluded
        for name, build in {
            "traded": lambda masked: traded_month_mask(
                hand_read(minute_klines(h), masked=masked),
                hand_read([official_kline(h)], masked=outside),
                MONTH,
                exclusions,
            ),
            "hourly-only": lambda masked: hourly_only_month_mask(
                hand_read([official_kline(h)], masked=masked), MONTH, exclusions
            ),
        }.items():
            with self.subTest(case=name):
                clean = build(outside)
                self.assertEqual(frozenset({h}), clean.expected)
                self.assertEqual(frozenset(), clean.masked)
                self.assertEqual({}, clean.reasons)
                inside = build(outside | {h})
                self.assertEqual({h: "untrusted row"}, inside.reasons)


class HourlyOnlyTests(unittest.TestCase):
    def test_hourly_only_symbol_masks_repaired_hours(self):
        # Rule 5: with no minutes to check it against, a repaired hour is masked.
        h = [hour(i) for i in range(6)]
        hourly = hourly_of(
            hourly_line(h[0]),
            truncated(hourly_line(h[1])),  # repaired: the next row opens an hour later
            hourly_line(h[2]),
            hourly_line(h[3]),
            hourly_line(h[3]),  # a duplicate: the reader keeps one copy
        )  # h[4] and h[5] are absent
        self.assertEqual(frozenset({h[1]}), hourly.repaired)
        mask = hourly_only_month_mask(hourly, MONTH, around(h[0], 6))
        self.assertEqual(frozenset(h), mask.expected)
        self.assertEqual(
            {
                h[1]: "repaired hour with no minutes to check it",
                h[3]: "untrusted row",
                h[4]: "no hourly bar",
                h[5]: "no hourly bar",
            },
            mask.reasons,
        )
        self.assertEqual(frozenset(mask.reasons), mask.masked)
        self.assertEqual(mask.masked, mask.defects)
        self.assertEqual(frozenset(), mask.open_only)  # hourly-only months have none
        self.assertEqual(frozenset({h[1]}), mask.repaired)
        self.assertFalse(mask.excluded)


class SeventeenPercentTests(unittest.TestCase):
    def test_seventeen_percent_rule_boundary_listing_and_open_only(self):
        # Review Focus 4. A 700-hour expected month: 44 hours inside a listing exclusion.
        start, _ = month_bounds_ms(MONTH)
        exclusions = [BasketExclusion("TESTUSDT", start, hour(44, start), "listing")]
        hours = [hour(i, hour(44, start)) for i in range(700)]
        self.assertEqual(Fraction(17, 100), SEVENTEEN)

        for defects in (119, 120):
            with self.subTest(case="hourly-only", defects=defects):
                present = [official_kline(h) for h in hours[: 700 - defects]]
                month = hourly_only_month_mask(hand_read(present), MONTH, exclusions)
                self.assertEqual(700, len(month.expected))
                self.assertEqual(defects, len(month.defects))
                self.assertEqual(Fraction(defects, 700), real_defect_share(month))
                self.check_boundary(month, defects, excluded=defects == 120)

            with self.subTest(case="traded, with open-only hours", defects=defects):
                month = self.traded_month_with_open_only(hours, exclusions, defects, open_only=60)
                self.assertEqual(frozenset(hours[defects : defects + 60]), month.open_only)
                self.assertEqual(frozenset(hours[:defects]), month.defects)
                self.assertEqual(defects + 60, len(month.masked))  # 25.6% of the hours masked
                self.assertEqual(Fraction(defects, 700), real_defect_share(month))
                self.check_boundary(month, defects, excluded=defects == 120)

        # SOLUSDT 2020-08 lists at 2020-08-11 06:00: its 246 earlier hours are not expected,
        # so they do not count. Counted among 744 hours they would exclude the month alone.
        month_start, month_end = month_bounds_ms("2020-08")
        listing = [
            BasketExclusion("SOLUSDT", month_bounds_ms("2017-08")[0], SOL_LISTING, "listing")
        ]
        listed = list(range(SOL_LISTING, month_end, HOUR))
        self.assertEqual(246, (SOL_LISTING - month_start) // HOUR)
        complete = hand_read([official_kline(h) for h in listed])
        sol = hourly_only_month_mask(complete, "2020-08", listing)
        self.assertEqual(frozenset(listed), sol.expected)
        self.assertEqual(498, len(sol.expected))
        self.assertEqual(frozenset(), sol.masked)
        self.assertEqual(Fraction(0), real_defect_share(sol))
        self.assertFalse(apply_seventeen_percent(sol).excluded)
        unlisted = hourly_only_month_mask(complete, "2020-08", [])
        self.assertEqual(744, len(unlisted.expected))
        self.assertEqual(246, len(unlisted.defects))  # the 246 hours would be defects
        self.assertTrue(apply_seventeen_percent(unlisted).excluded)

    def traded_month_with_open_only(self, hours, exclusions, defects, open_only):
        minutes: list[Kline] = []
        official: list[Kline] = []
        for i, h in enumerate(hours):
            short = i < defects and i % 2 == 1  # a defect: one minute missing
            no_hourly = i < defects and i % 2 == 0  # a defect: no hourly bar
            only_open = defects <= i < defects + open_only  # the hourly bar opens differently
            minutes += minute_klines(h, count=59 if short else 60)
            if not no_hourly:
                official.append(
                    official_kline(
                        h, volume="590" if short else "600", open_="1.05" if only_open else "1.0"
                    )
                )
        return traded_month_mask(hand_read(minutes), hand_read(official), MONTH, exclusions)

    def check_boundary(self, month, defects, *, excluded):
        """119 of 700 (exactly 17%) keeps the month as it is; 120 masks all 700 hours."""
        kept = apply_seventeen_percent(month)
        self.assertEqual(excluded, kept.excluded)
        if not excluded:
            self.assertEqual(month.masked, kept.masked)
            self.assertEqual(month.reasons, kept.reasons)
            return
        self.assertEqual(month.expected, kept.masked)
        self.assertEqual(700, len(kept.masked))
        self.assertEqual(defects, len(kept.defects))  # still the share that excluded it
        self.assertEqual(Fraction(defects, 700), real_defect_share(kept))
        for field in ("month", "expected", "defects", "repaired", "open_only"):
            self.assertEqual(getattr(month, field), getattr(kept, field), field)
        # Every hour has a reason: the earlier ones stay, the newly masked get the rule's.
        self.assertEqual(kept.masked, frozenset(kept.reasons))
        for hour_ms, reason in kept.reasons.items():
            self.assertEqual(month.reasons.get(hour_ms, "month excluded (17% rule)"), reason)
        self.assertEqual(
            700 - len(month.masked), list(kept.reasons.values()).count("month excluded (17% rule)")
        )
        self.assertFalse(month.excluded)  # the input is not changed
        self.assertEqual(month.masked, frozenset(month.reasons))

    def test_hours_before_listing_do_not_count_toward_the_rule(self):
        # SOLUSDT 2020-08 (246 of its 744 hours precede the listing, as the Review Focus 4
        # test shows): 84 defects are 16.9% of the 498 expected hours and 85 are 17.07%.
        month_end = month_bounds_ms("2020-08")[1]
        listing = [
            BasketExclusion("SOLUSDT", month_bounds_ms("2017-08")[0], SOL_LISTING, "listing")
        ]
        listed = list(range(SOL_LISTING, month_end, HOUR))
        for defects, excluded in ((84, False), (85, True)):
            with self.subTest(defects=defects):
                present = hand_read([official_kline(h) for h in listed[: len(listed) - defects]])
                mask = hourly_only_month_mask(present, "2020-08", listing)
                self.assertEqual(Fraction(defects, 498), real_defect_share(mask))
                self.assertEqual(excluded, apply_seventeen_percent(mask).excluded)

    def test_month_with_no_expected_hours_is_kept(self):
        # SOLUSDT 2019-03 is wholly before the listing; DOGEUSDT 2020-02 is wholly inside
        # rule 5's exclusion. Neither has an hour to defect, so neither is divided or excluded.
        sol = [BasketExclusion("SOLUSDT", month_bounds_ms("2017-08")[0], SOL_LISTING, "listing")]
        no_archive = parse_rows_repaired("", "1h", "2019-03")
        no_minutes = parse_rows_repaired("", "1m", "2019-03")
        doge_start, doge_end = month_bounds_ms("2020-02")
        doge = [
            BasketExclusion("DOGEUSDT", doge_start, doge_end, "rule 5: the repair cannot rescue")
        ]
        h = [hour(i, doge_start) for i in range(3)]
        archive = hourly_of(
            hourly_line(h[0]),
            truncated(hourly_line(h[1])),  # a repaired hour
            hourly_line(h[2]),
            hourly_line(h[2]),  # an untrusted one
            month="2020-02",
        )
        self.assertEqual(frozenset({h[1]}), archive.repaired)
        self.assertEqual(frozenset({h[2]}), archive.masked_hours)

        cases = {
            "SOLUSDT 2019-03": hourly_only_month_mask(no_archive, "2019-03", sol),
            "SOLUSDT 2019-03, traded": traded_month_mask(no_minutes, no_archive, "2019-03", sol),
            "DOGEUSDT 2020-02": hourly_only_month_mask(archive, "2020-02", doge),
        }
        for name, month in cases.items():
            with self.subTest(case=name):
                self.assertEqual(frozenset(), month.expected)
                self.assertEqual(frozenset(), month.masked)  # the loader drops the bars
                self.assertEqual({}, month.reasons)
                self.assertEqual(frozenset(), month.defects)
                self.assertEqual(frozenset(), month.repaired)
                self.assertIsNone(real_defect_share(month))
                kept = apply_seventeen_percent(month)
                self.assertFalse(kept.excluded)
                self.assertEqual(frozenset(), kept.masked)

    def test_unreadable_archive_masks_every_hour_and_excludes_the_month(self):
        # Rule 1: an archive that cannot be read leaves all its hours absent; they are
        # masked as defects, and the 17% rule then excludes the month.
        h = [hour(i) for i in range(3)]
        unreadable = parse_rows_repaired(text_of("not-a-time,1,2,3,4,5,6,7,8,9,10,0"), "1h", MONTH)
        self.assertNotEqual("", unreadable.unreadable)
        minutes = minutes_of(*minute_lines(h[0]), *minute_lines(h[1]), *minute_lines(h[2]))
        exclusions = around(h[0], 3)
        for name, month in {
            "traded": traded_month_mask(minutes, unreadable, MONTH, exclusions),
            "hourly-only": hourly_only_month_mask(unreadable, MONTH, exclusions),
        }.items():
            with self.subTest(case=name):
                self.assertEqual(frozenset(h), month.defects)
                self.assertEqual(Fraction(1), real_defect_share(month))
                self.assertTrue(apply_seventeen_percent(month).excluded)


class OpenOnlyTests(unittest.TestCase):
    def test_open_only_hours_are_identified(self):
        h = [hour(i) for i in range(8)]
        lines = [
            hourly_line(h[0]),  # clean
            hourly_line(h[1], o="1.05"),  # only the open differs
            hourly_line(h[2], o="1.05", h="1.3"),  # the open and the high
            hourly_line(h[3], o="1.05"),  # the open, but the hour has 59 minutes
            truncated(hourly_line(h[4], o="1.05")),  # repaired, only the open differs
            hourly_line(h[5], o="1.05", volume="600.3"),  # open, within the volume drift
            truncated(hourly_line(h[6], o="1.05", volume="600.3")),  # repaired: no drift
            hourly_line(h[7], o="1.05", volume="900"),  # open, and a volume beyond the drift
        ]
        minutes = []
        for i, hour_open in enumerate(h):
            minutes += minute_lines(hour_open, skip={30} if i == 3 else ())
        mask = traded_month_mask(minutes_of(*minutes), hourly_of(*lines), MONTH, around(h[0], 8))
        self.assertEqual(frozenset({h[1], h[4], h[5]}), mask.open_only)
        self.assertEqual(frozenset(h[1:]), mask.masked)
        self.assertEqual(frozenset({h[2], h[3], h[6], h[7]}), mask.defects)
        self.assertEqual(frozenset({h[4], h[6]}), mask.repaired)
        self.assertEqual("open-only difference", mask.reasons[h[1]])
        self.assertEqual("open-only difference", mask.reasons[h[4]])
        self.assertEqual("open-only difference", mask.reasons[h[5]])
        self.assertEqual("mismatch on open+high", mask.reasons[h[2]])
        self.assertEqual("incomplete hour", mask.reasons[h[3]])
        self.assertEqual("mismatch on open+volume", mask.reasons[h[6]])
        self.assertEqual("mismatch on open+volume", mask.reasons[h[7]])
        self.assertEqual(Fraction(4, 8), real_defect_share(mask))


class MaskedDaysTests(unittest.TestCase):
    def test_masked_days_cover_each_masked_hours_day(self):
        masked = [hour(5), hour(23), hour(24), hour(24 * 2 + 12), hour(24 * 2 + 13)]
        self.assertEqual(frozenset({JAN, JAN + DAY, JAN + 2 * DAY}), masked_days(masked))
        self.assertEqual(frozenset({JAN}), masked_days(iter([hour(0), hour(23)])))
        self.assertEqual(frozenset(), masked_days(()))
        mask = hourly_only_month_mask(hand_read([]), MONTH, around(hour(5), 2))
        self.assertEqual(frozenset({JAN}), masked_days(mask.masked))


class AuditSharesTheHelpersTests(unittest.TestCase):
    def test_audit_still_uses_the_same_helpers(self):
        # The moved names stay importable from audit (audit_run, tests/test_backtest_audit
        # and the hash-pinned scripts under docs/reviews import them there), as the same
        # objects. The existing audit suite pins their behaviour.
        for name in (
            "expected_hours",
            "hour_statuses",
            "differing_fields",
            "_with_prices_of",
            "HOUR_MS",
            "PRESENT_BOTH",
            "ABSENT_MINUTES",
            "ABSENT_HOURLY",
            "ABSENT_BOTH",
            "PRICE_FIELDS",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(masking, name), getattr(audit, name))

    def test_import_direction(self):
        # masking imports klines, replay and dataset, never audit (audit imports masking);
        # replay never imports masking.
        backtest = Path(masking.__file__).parent
        imported = {}
        for module in ("masking", "replay"):
            tree = ast.parse((backtest / f"{module}.py").read_text(encoding="utf-8"))
            names = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names |= {alias.name for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names |= {node.module, *(f"{node.module}.{a.name}" for a in node.names)}
            imported[module] = names
        self.assertIn("crypto_grid_bot.backtest.replay", imported["masking"])
        self.assertNotIn("crypto_grid_bot.backtest.audit", imported["masking"])
        self.assertNotIn("crypto_grid_bot.backtest.masking", imported["replay"])


if __name__ == "__main__":
    unittest.main()
