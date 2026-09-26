"""Data-audit functions on synthetic bars and rows whose right answers are known.

Each case is taken from a real finding: PR #60 (hours missing from both archives were
invisible), #66 (outage events, field breakdown), #59 and #65 (close repair rules).
"""

import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import Mock, call, patch

from test_backtest_loaders import FakeArchive, hour_rows, minute_rows

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
from crypto_grid_bot.backtest.audit_run import _fetch, audit_outages, audit_rules, months
from crypto_grid_bot.backtest.dataset import (
    ArchiveParseError,
    archive_path,
    fetch_file,
    local_path,
)
from crypto_grid_bot.backtest.klines import Kline
from crypto_grid_bot.market_data.client import FeedError
from crypto_grid_bot.market_data.parsing import DataError

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


class FetchBoundaryTests(unittest.TestCase):
    def archive(self):
        archive = FakeArchive()
        archive.add("BTCUSDT", "1m", "2024-01", minute_rows(JAN_2024, 60))
        hourly = hour_rows(JAN_2024, 1).strip().split(",")
        hourly[5] = "600"  # Matches the 60 minutes' base volume.
        archive.add("BTCUSDT", "1h", "2024-01", ",".join(hourly) + "\n")
        return archive

    def test_integrity_failures_abort_before_raw_cache_reads_and_are_not_retried(self):
        path = archive_path("BTCUSDT", "1m", "2024-01")
        for cached in (False, True):
            for defect in ("hash", "malformed_checksum", "missing_checksum", "missing_body"):
                for runner in (audit_outages, audit_rules):
                    with self.subTest(cached=cached, defect=defect, runner=runner.__name__):
                        archive = self.archive()
                        with tempfile.TemporaryDirectory() as tmp:
                            data = Path(tmp)
                            if cached:
                                for interval in ("1m", "1h"):
                                    fetch_file(data, "BTCUSDT", interval, "2024-01", archive)
                            if defect in ("hash", "missing_body"):
                                archive.objects[path + ".CHECKSUM"] = (
                                    "0" * 64 + "  " + path.rsplit("/", 1)[1]
                                ).encode()
                            if defect == "malformed_checksum":
                                archive.objects[path + ".CHECKSUM"] = b"invalid checksum"
                            elif defect == "missing_checksum":
                                del archive.objects[path + ".CHECKSUM"]
                            elif defect == "missing_body":
                                del archive.objects[path]
                            get = Mock(side_effect=archive)
                            with (
                                patch("crypto_grid_bot.backtest.audit_run.BASKET", ["BTCUSDT"]),
                                patch(
                                    "crypto_grid_bot.backtest.audit_run.months",
                                    return_value=["2024-01"],
                                ),
                                patch(
                                    "crypto_grid_bot.backtest.audit_run.UNPARSED_MONTHS",
                                    ["2024-01"],
                                ),
                                patch("crypto_grid_bot.backtest.audit_run._rows") as raw_rows,
                                patch("crypto_grid_bot.backtest.audit_run.time.sleep") as sleep,
                                self.assertRaises(DataError) as raised,
                            ):
                                runner(data, get)
                            self.assertNotIsInstance(raised.exception, ArchiveParseError)
                            raw_rows.assert_not_called()
                            sleep.assert_not_called()
                            self.assertEqual(
                                1 if defect == "malformed_checksum" else 2, get.call_count
                            )
                            if not cached:
                                self.assertFalse(
                                    local_path(data, "BTCUSDT", "1m", "2024-01").exists()
                                )

    def test_verified_parse_failure_remains_repairable_for_fresh_and_cached_archives(self):
        archive = self.archive()
        text = minute_rows(JAN_2024, 60).splitlines()
        last = text[-1].split(",")
        last[6] = str(int(last[0]) + 30_000)
        text[-1] = ",".join(last)
        archive.add("BTCUSDT", "1m", "2024-01", "\n".join(text) + "\n")
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            with self.assertRaises(ArchiveParseError) as raised:
                fetch_file(data, "BTCUSDT", "1m", "2024-01", archive)
            self.assertIsInstance(raised.exception, DataError)
            self.assertIsInstance(raised.exception.__cause__, DataError)
            for cached in (False, True):
                if not cached:
                    local_path(data, "BTCUSDT", "1m", "2024-01").unlink()
                with self.subTest(cached=cached):
                    self.assertEqual("unparsed", _fetch(data, "BTCUSDT", "1m", "2024-01", archive))
                    with (
                        patch("crypto_grid_bot.backtest.audit_run.BASKET", ["BTCUSDT"]),
                        patch("crypto_grid_bot.backtest.audit_run.UNPARSED_MONTHS", ["2024-01"]),
                    ):
                        result = audit_rules(data, archive)
                    self.assertEqual(
                        {"pair_months": 1, "narrow": 1, "refined": 1}, result["summary"]
                    )

    def test_transport_failure_retries_are_bounded_and_can_recover(self):
        archive = self.archive()
        checksum = archive_path("BTCUSDT", "1m", "2024-01") + ".CHECKSUM"
        for recover in (False, True):
            replies = [FeedError("synthetic transport failure") for _ in range(3)]
            replies += (
                [archive(checksum), archive(checksum.removesuffix(".CHECKSUM"))]
                if recover
                else [FeedError("still unavailable")]
            )
            get = Mock(side_effect=replies)
            with (
                tempfile.TemporaryDirectory() as tmp,
                patch("crypto_grid_bot.backtest.audit_run.time.sleep") as sleep,
            ):
                with self.subTest(recover=recover):
                    if recover:
                        self.assertEqual("ok", _fetch(Path(tmp), "BTCUSDT", "1m", "2024-01", get))
                    else:
                        with self.assertRaises(FeedError):
                            _fetch(Path(tmp), "BTCUSDT", "1m", "2024-01", get)
                    self.assertEqual([call(1), call(2), call(4)], sleep.call_args_list)
                    self.assertEqual(5 if recover else 4, get.call_count)

    def test_reserved_month_is_refused_before_fetch_or_cache_access(self):
        get = Mock(side_effect=AssertionError("reserved network access"))
        with tempfile.TemporaryDirectory() as tmp:
            with patch("crypto_grid_bot.backtest.audit_run.fetch_file") as fetch:
                with self.assertRaises(DataError):
                    _fetch(Path(tmp), "BTCUSDT", "1m", "2025-01", get)
                fetch.assert_not_called()
                get.assert_not_called()


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

    def test_a_pair_in_an_unparsed_month_is_not_counted_as_listed(self):
        # Bob's #70 question. The outage task (Step 2) defines "listed at h" as
        # excluding the pair's unparsed months: its status there is unknown, so it
        # neither confirms nor refutes an outage. ETHUSDT's month fails to parse
        # (one close off the boundary mid-file), so hour 01 counts one listed pair.
        archive = FakeArchive()
        text = minute_rows(JAN_2024, 3 * 60)
        btc = "\n".join(line for i, line in enumerate(text.splitlines()) if not 60 <= i < 120)
        archive.add("BTCUSDT", "1m", "2024-01", btc + "\n")
        hourly = hour_rows(JAN_2024, 3).splitlines()
        archive.add("BTCUSDT", "1h", "2024-01", "\n".join([hourly[0], hourly[2]]) + "\n")
        eth = text.splitlines()
        fields = eth[5].split(",")
        fields[6] = str(int(fields[0]) + 30_000)  # truncated close, next minute adjacent
        eth[5] = ",".join(fields)
        archive.add("ETHUSDT", "1m", "2024-01", "\n".join(eth) + "\n")
        archive.add("ETHUSDT", "1h", "2024-01", hour_rows(JAN_2024, 3))
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_outages(Path(tmp), archive)
        self.assertEqual(["ETHUSDT 2024-01"], result["unparsed"])
        first = result["events"][0]
        self.assertEqual(
            (1, "all_listed_few", ["BTCUSDT"]), (first["listed"], first["kind"], first["pairs"])
        )

    def test_rules_audit_skips_pairs_without_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = audit_rules(Path(tmp), FakeArchive())
        self.assertEqual({"pair_months": 0}, result["summary"])


if __name__ == "__main__":
    unittest.main()
