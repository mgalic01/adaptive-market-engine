"""Flat-stretch search: every case is a defect of the appendix script on PR #102.

The synthetic series here contain no market data. Each is a hand-built
``hourly_equity`` series in the shape ``replay.py`` writes it:
``[hour open ms, strategy total equity, buy-and-hold value]``.
"""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from flat_stretches import (  # noqa: E402
    HOUR_MS,
    analyse,
    select,
    stretches,
)

START = 1_654_000_000_000 // HOUR_MS * HOUR_MS  # an arbitrary hour boundary, 2022-05-31


def series(*runs: tuple[Decimal, int, int]) -> list[tuple[int, Decimal]]:
    """Build a series from (equity, sample count, hours between samples) runs."""
    out: list[tuple[int, Decimal]] = []
    ms = START
    for equity, count, spacing in runs:
        for _ in range(count):
            out.append((ms, equity))
            ms += spacing * HOUR_MS
    return out


def document(*results: list[tuple[int, Decimal]]) -> dict:
    return {
        "dataset": "synthetic",
        "fees": {"maker": "0", "taker": "0.0009"},
        "results": [
            {
                "symbol": f"SYN{n}USDT",
                "path_mode": "high_first",
                "strategy": "ungated grid baseline",
                "hourly_equity": [[ms, str(equity), "0"] for ms, equity in s],
            }
            for n, s in enumerate(results)
        ],
    }


class LabelsTest(unittest.TestCase):
    def test_changed_stretch_is_labelled_changed_with_the_time_it_changed(self) -> None:
        # Peak 100, then flat at 91 (9% down) for 31 samples, then equity moves.
        s = series((Decimal(100), 1, 1), (Decimal(91), 31, 1), (Decimal(92), 5, 1))
        found = select(stretches(s), min_hours=24, threshold=Decimal(8))
        self.assertEqual(len(found), 1)
        flat = found[0]
        self.assertFalse(flat.censored)
        self.assertEqual(flat.span_hours, 30)  # 31 samples span 30 hours
        self.assertEqual(flat.samples, 31)
        self.assertEqual(flat.missing_hours, 0)
        self.assertEqual(flat.changed_at_ms, s[32][0])
        self.assertEqual(f"{flat.drawdown_pct:.2f}", "9.00")
        self.assertIn("CHANGED", flat.describe(s[-1][0]))

    def test_stretch_running_into_the_end_of_the_series_is_labelled_censored(self) -> None:
        # The same flat run, but the series stops while still flat.
        s = series((Decimal(100), 1, 1), (Decimal(91), 31, 1))
        found = select(stretches(s), min_hours=24, threshold=Decimal(8))
        self.assertEqual(len(found), 1)
        flat = found[0]
        self.assertTrue(flat.censored)
        self.assertIsNone(flat.changed_at_ms)
        self.assertEqual(flat.end_ms, s[-1][0])
        self.assertEqual(flat.hours_to_series_end(s[-1][0]), 0)
        text = flat.describe(s[-1][0])
        self.assertIn("CENSORED", text)
        self.assertIn("lower bound", text)

    def test_only_the_final_stretch_can_ever_be_censored(self) -> None:
        # Two qualifying flat runs; the first must be CHANGED, the last CENSORED.
        s = series(
            (Decimal(100), 1, 1),
            (Decimal(91), 30, 1),
            (Decimal(95), 2, 1),
            (Decimal(90), 40, 1),
        )
        found = select(stretches(s), min_hours=24, threshold=Decimal(8))
        self.assertEqual([f.censored for f in found], [False, True])


class GapTest(unittest.TestCase):
    def test_a_gappy_flat_span_is_found_by_time_although_its_sample_count_is_small(self) -> None:
        # 21 samples three hours apart: 60 wall-clock hours flat, 40 of them unobserved.
        # The old script's `hours = j - i + 1` gives 21 and drops this at the 24 gate.
        s = series((Decimal(100), 1, 1), (Decimal(90), 21, 3))
        found = select(stretches(s), min_hours=24, threshold=Decimal(8))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].span_hours, 60)
        self.assertEqual(found[0].samples, 21)
        self.assertEqual(found[0].missing_hours, 40)
        self.assertIn("40 h missing", found[0].describe(s[-1][0]))
        self.assertEqual(len(select(stretches(s), min_hours=61, threshold=Decimal(8))), 0)

    def test_twenty_four_samples_span_twenty_three_hours_and_miss_a_twenty_four_hour_gate(
        self,
    ) -> None:
        # The old script counted this as "24 h". It is 23 hours of elapsed time.
        s = series((Decimal(100), 1, 1), (Decimal(90), 24, 1), (Decimal(95), 1, 1))
        self.assertEqual(stretches(s)[1].span_hours, 23)
        self.assertEqual(select(stretches(s), min_hours=24, threshold=Decimal(8)), [])
        self.assertEqual(len(select(stretches(s), min_hours=23, threshold=Decimal(8))), 1)

    def test_two_samples_inside_one_hour_count_as_one_present_hour(self) -> None:
        # replay.py stamps an hourly sample with the minute bar that opened the hour, so
        # a run whose first minutes are absent can be stamped mid-hour. Missing hours are
        # counted over distinct hour buckets, never over samples.
        flat = [(START + h * HOUR_MS, Decimal(90)) for h in range(25)]
        flat.insert(1, (START + 30 * 60 * 1000, Decimal(90)))  # a second sample in hour 0
        s = [(START - HOUR_MS, Decimal(100)), *flat]
        found = select(stretches(s), min_hours=24, threshold=Decimal(8))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].samples, 26)
        self.assertEqual(found[0].hours_present, 25)
        self.assertEqual(found[0].span_hours, 24)
        self.assertEqual(found[0].missing_hours, 0)


class ThresholdTest(unittest.TestCase):
    def test_drawdown_is_measured_against_the_running_peak_at_the_stretch_start(self) -> None:
        s = series((Decimal(100), 1, 1), (Decimal(120), 1, 1), (Decimal(110), 30, 1))
        flat = stretches(s)[-1]
        self.assertEqual(flat.peak, Decimal(120))
        self.assertEqual(f"{flat.drawdown_pct:.2f}", "8.33")
        self.assertEqual(len(select([flat], min_hours=24, threshold=Decimal(8))), 1)
        self.assertEqual(select([flat], min_hours=24, threshold=Decimal(9)), [])

    def test_a_flat_series_at_its_own_peak_has_no_drawdown_and_no_division_error(self) -> None:
        s = series((Decimal(100), 40, 1))
        found = stretches(s)
        self.assertEqual(found[0].drawdown_pct, Decimal(0))
        self.assertEqual(select(found, min_hours=24, threshold=Decimal(7)), [])

    def test_an_all_zero_series_does_not_divide_by_zero(self) -> None:
        self.assertEqual(stretches(series((Decimal(0), 30, 1)))[0].drawdown_pct, Decimal(0))


class DocumentTest(unittest.TestCase):
    def test_analyse_reads_a_results_document_and_reports_per_result(self) -> None:
        changed = series((Decimal(100), 1, 1), (Decimal(91), 31, 1), (Decimal(92), 3, 1))
        censored = series((Decimal(100), 1, 1), (Decimal(91), 31, 1))
        out = analyse(document(changed, censored), min_hours=24, threshold=Decimal(8))
        self.assertEqual(
            [name for name, _, _ in out],
            ["SYN0USDT high_first ungated", "SYN1USDT high_first ungated"],
        )
        self.assertEqual([[s.censored for s in found] for _, found, _ in out], [[False], [True]])
        self.assertEqual([end for _, _, end in out], [changed[-1][0], censored[-1][0]])

    def test_an_empty_series_reports_no_stretches(self) -> None:
        out = analyse(document([]), min_hours=24, threshold=Decimal(8))
        self.assertEqual(out, [("SYN0USDT high_first ungated", [], 0)])


if __name__ == "__main__":
    unittest.main()


class MidHourSampleTest(unittest.TestCase):
    def test_a_stretch_whose_first_sample_is_mid_hour_spans_whole_hours(self) -> None:
        # replay.py stamps an hour with the minute bar that opened it, so a stretch can
        # start at :30. Measured on raw timestamps this 25-hour stretch spanned 23 h,
        # reported -1 missing hours and was dropped at the 24 h gate.
        flat = [(START + 30 * 60 * 1000, Decimal(90))]
        flat += [(START + h * HOUR_MS, Decimal(90)) for h in range(1, 25)]
        s = [(START - HOUR_MS, Decimal(100)), *flat, (START + 25 * HOUR_MS, Decimal(95))]
        found = stretches(s)[1]
        self.assertEqual(25, found.hours_present)
        self.assertEqual(24, found.span_hours)
        self.assertEqual(0, found.missing_hours)
        self.assertEqual(1, len(select(stretches(s), min_hours=24, threshold=Decimal(8))))
        self.assertEqual(1, found.hours_to_series_end(START + 25 * HOUR_MS))
