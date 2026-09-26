"""Data-audit functions on synthetic bars and rows whose right answers are known.

Each case is taken from a real finding: PR #60 (hours missing from both archives were
invisible), #66 (outage events, field breakdown), #59 and #65 (close repair rules).
"""

import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path

from crypto_grid_bot.backtest.audit import (
    ABSENT_BOTH,
    ABSENT_HOURLY,
    ABSENT_MINUTES,
    HOUR_MS,
    PRESENT_BOTH,
    close_class,
    development_month,
    differing_fields,
    expected_hours,
    fix_closes,
    hour_statuses,
    outage_events,
    rule_outcome,
)
from crypto_grid_bot.backtest.audit_run import audit_outages, audit_rules, months
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.market_data.parsing import DataError
from tests.test_backtest_loaders import FakeArchive, hour_rows, minute_rows

JAN_2024 = 1704067200000  # 2024-01-01T00:00:00Z
MIN = 60_000


def bar(o="1", h="2", lo="0.5", c="1.5", v="10", t=JAN_2024):
    return Kline(t, D(o), D(h), D(lo), D(c), D(v), D("0"), D("0"))


def rows(*spec, step=MIN):
    """CSV rows from (open offset in steps, close offset in ms or None for normal)."""
    out = []
    for n, close in spec:
        open_ms = JAN_2024 + n * step
        close_ms = open_ms + step - 1 if close is None else open_ms + close
        out.append(
            [str(open_ms), "1", "2", "0.5", "1.5", "10", str(close_ms), "15", "3", "5", "7", "0"]
        )
    return out


class WindowTests(unittest.TestCase):
    def test_reserved_window_is_refused(self):
        self.assertEqual("2024-12", development_month("2024-12"))
        for month in ("2025-01", "2026-06"):
            with self.subTest(month=month), self.assertRaises(DataError):
                development_month(month)
        self.assertEqual("2017-08", months()[0])
        self.assertEqual("2024-12", months()[-1])
        self.assertEqual(89, len(months()))

    def test_expected_hours_start_at_listing_and_stop_at_month_end(self):
        listing = JAN_2024 + 5 * HOUR_MS + 17 * MIN  # 05:17 → hour 05:00
        hours = expected_hours(listing, "2024-01")
        self.assertEqual(JAN_2024 + 5 * HOUR_MS, hours[0])
        self.assertEqual(31 * 24 - 5, len(hours))
        self.assertEqual(31 * 24 * 29, len(expected_hours(0, "2024-02")) * 31)  # full month


class StatusTests(unittest.TestCase):
    def test_every_expected_hour_gets_one_status(self):
        # PR #60: an hour in neither archive must still be reported.
        h = [JAN_2024 + i * HOUR_MS for i in range(4)]
        minutes = [h[0] + 3 * MIN, h[2]]  # one minute is enough to count
        official = [h[0], h[1]]
        statuses = hour_statuses(minutes, official, h)
        self.assertEqual(
            [PRESENT_BOTH, ABSENT_MINUTES, ABSENT_HOURLY, ABSENT_BOTH],
            [statuses[x] for x in h],
        )


class EventTests(unittest.TestCase):
    def test_consecutive_hours_merge_and_end_is_exclusive(self):
        pairs = {f"P{i}" for i in range(5)}
        h = [JAN_2024 + i * HOUR_MS for i in range(5)]
        absent = {h[0]: set(pairs), h[1]: set(pairs), h[3]: {"P0"}}
        listed = {x: set(pairs) for x in h}
        events = outage_events(absent, listed)
        self.assertEqual(2, len(events))
        first, second = events
        self.assertEqual(
            (h[0], h[2], 2, "all_pairs", 5),
            (first.start_ms, first.end_ms, first.hours, first.kind, first.listed),
        )
        self.assertEqual(("pair_specific", ("P0",)), (second.kind, second.pairs))

    def test_few_listed_pairs_are_not_called_exchange_wide(self):
        # PR #60: in 2017 two or three pairs were listed, so "80%" meant everyone.
        absent = {JAN_2024: {"BTCUSDT", "ETHUSDT"}}
        listed = {JAN_2024: {"BTCUSDT", "ETHUSDT"}}
        self.assertEqual("all_listed_few", outage_events(absent, listed)[0].kind)


class FieldTests(unittest.TestCase):
    def test_fields_are_named(self):
        cases = [
            (bar(o="1.1"), ("open",)),  # PR #66: the most common class
            (bar(v="12"), ("volume",)),  # PR #60: 2021-01-21 was volume only
            (bar(o="1.1", h="2.2", v="12"), ("open", "high", "volume")),
            (bar(v="10.005"), ()),  # drift within 0.1% is not a mismatch
            (bar(o="1.1", v="10.005"), ("open",)),  # drifting volume is not blamed
            (bar(), ()),
        ]
        for ours, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, differing_fields(ours, bar()))
        self.assertEqual(("volume",), differing_fields(bar(v="10.005"), bar(), D(0)))


class CloseRuleTests(unittest.TestCase):
    def test_classes_test_the_open_first(self):
        # PR #59 missed the unaligned open; it is checked before the close.
        self.assertEqual("ok", close_class(JAN_2024, JAN_2024 + MIN - 1, MIN))
        self.assertEqual("unaligned_open", close_class(JAN_2024 + 14_789, JAN_2024 + MIN, MIN))
        self.assertEqual("past_boundary", close_class(JAN_2024, JAN_2024 + MIN, MIN))
        self.assertEqual("truncated", close_class(JAN_2024, JAN_2024 + 41_646, MIN))
        self.assertEqual("other", close_class(JAN_2024, JAN_2024 - 1, MIN))

    def test_rules_differ_only_where_the_next_row_is_adjacent(self):
        # Row 0 truncated, next row adjacent (2021-12, 2019-06): refined fixes it, narrow
        # does not. Row 2 truncated before a gap: both fix it.
        data = rows((0, 30_000), (1, None), (2, 20_000), (5, None))
        narrow_text, narrow = fix_closes(data, "1m", "narrow")
        _, refined = fix_closes(data, "1m", "refined")
        self.assertEqual([JAN_2024 + 2 * MIN], narrow)
        self.assertEqual([JAN_2024, JAN_2024 + 2 * MIN], refined)
        self.assertIn(str(JAN_2024 + 3 * MIN - 1), narrow_text)
        self.assertEqual("1,2,0.5,1.5,10", narrow_text.splitlines()[2].split(",", 1)[1][:14])

    def test_refined_rule_never_fixes_an_unaligned_open(self):
        data = [
            [
                str(JAN_2024 + 14_789),
                "1",
                "2",
                "0.5",
                "1.5",
                "10",
                str(JAN_2024 + MIN),
                "15",
                "3",
                "5",
                "7",
                "0",
            ]
        ]
        self.assertEqual([], fix_closes(data, "1m", "refined")[1])
        self.assertEqual([JAN_2024 + 14_789], fix_closes(data, "1m", "narrow")[1])


class RuleOutcomeTests(unittest.TestCase):
    def month_rows(self, hour_open="1"):
        # One hour of minutes, the 35th truncated with the next minute adjacent; the
        # official hour is truncated too, as in DOGEUSDT 2020-02-19 11:00 (PR #65).
        minutes = rows(*[(i, 20_000 if i == 35 else None) for i in range(60)])
        hour = rows((0, 1_000_000), step=HOUR_MS)
        hour[0][1] = hour_open
        hour[0][5] = "600"  # 60 minutes of volume 10
        return minutes, hour

    def test_refined_rule_is_usable_when_the_archives_agree(self):
        minutes, hour = self.month_rows()
        outcome = rule_outcome(minutes, hour, "2024-01", "refined")
        self.assertEqual(
            (True, "", (JAN_2024,)), (outcome.usable, outcome.reason, outcome.fixed_hours)
        )
        self.assertFalse(rule_outcome(minutes, hour, "2024-01", "narrow").usable)

    def test_refined_rule_rejects_an_archive_disagreement_and_names_the_field(self):
        minutes, hour = self.month_rows(hour_open="0.99")
        outcome = rule_outcome(minutes, hour, "2024-01", "refined")
        self.assertFalse(outcome.usable)
        self.assertEqual(f"hour {JAN_2024} differs on open", outcome.reason)

    def test_reserved_month_is_refused(self):
        with self.assertRaises(DataError):
            rule_outcome([], [], "2025-01", "narrow")


class RunnerTests(unittest.TestCase):
    def test_outage_audit_end_to_end_on_a_fake_archive(self):
        archive = FakeArchive()
        text = minute_rows(JAN_2024, 3 * 60)  # hours 00-02
        text = (
            "\n".join(line for i, line in enumerate(text.splitlines()) if not 60 <= i < 120) + "\n"
        )
        archive.add("BTCUSDT", "1m", "2024-01", text)
        hourly = hour_rows(JAN_2024, 3).splitlines()
        archive.add("BTCUSDT", "1h", "2024-01", "\n".join([hourly[0], hourly[2]]) + "\n")
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_outages(Path(tmp), archive)
        self.assertEqual({"BTCUSDT": "2024-01-01 00:00"}, result["first_hour"])
        # Hour 01 is missing from both archives: one pair listed, so "all_listed_few".
        first = result["events"][0]
        self.assertEqual(
            ("2024-01-01 01:00", "2024-01-01 02:00", 1, "all_listed_few"),
            (first["start"], first["end_exclusive"], first["hours"], first["kind"]),
        )
        # Hours 03:00 onwards of January have no data in either archive either.
        self.assertEqual(31 * 24 - 2, result["summary"]["event_hours"])
        # The fake hourly bars carry one minute's volume (10), not 60 minutes' (600):
        # both compared hours mismatch on volume alone, and the audit says so.
        self.assertEqual([["2024", "volume", 2]], result["mismatch_fields"])

    def test_rules_audit_skips_pairs_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_rules(Path(tmp), FakeArchive())
        self.assertEqual({"pair_months": 0}, result["summary"])


if __name__ == "__main__":
    unittest.main()
