"""Each run reports its masked hours, skipped days and fills after a masked span.

Long-window data plan, Task 4 (spec v1 section 5: rule 1's "Each run reports", rules 3
and 4). Every row, the grid's and variant D's, gains three fields, each written only when
non-zero, so that a run with no mask keeps its exact row (section 6, the stage-1 identity
check):

* ``masked_hours``: the pair's masked hours inside the evaluation window;
* ``days_skipped_for_masks``: the days the pair's daily/hourly check skips for them;
* ``fills_after_masked_span``: the fills on the first replayed minute after a masked span.
  A gap that no masked hour explains, from feature warm-up or from missing data, is not a
  masked span.

Synthetic data only (``test_backtest_masked_checks``' DOGEUSDT window and
``test_trend_benchmark``'s daily closes): no network, nothing after 2024-12, and nothing
here is market data or evidence.
"""

import hashlib
import shutil
import tempfile
import unittest
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch

import test_backtest_masked_checks as mc
from test_trend_benchmark import RUN, SWITCHING, E, always, flat

from crypto_grid_bot.backtest.jobs import cross_check_job, prepare_run, run_job
from crypto_grid_bot.backtest.replay import MaskedSpans, load_minutes, replay
from crypto_grid_bot.backtest.trend_benchmark import replay_trend, summarise_trend, trend_job
from crypto_grid_bot.simulation.models import timestamp
from crypto_grid_bot.simulation.runner import PaperSimulator

CONFIG, MAR_2020, APR_2020 = mc.CONFIG, mc.MAR_2020, mc.APR_2020
MINUTE_MS, HOUR_MS, DAY_MS = mc.MINUTE_MS, mc.HOUR_MS, mc.DAY_MS
MASK_FIELDS = {"masked_hours", "days_skipped_for_masks", "fills_after_masked_span"}
# The evaluation window of the DOGEUSDT spec (2020-03), as run_job passes it to replay.
WINDOW = (MAR_2020, APR_2020)
# Three evaluation hours on two UTC days (2020-03-01 and 2020-03-15), and a warm-up hour.
EVALUATION_HOURS = {MAR_2020 + 2 * HOUR_MS, MAR_2020 + 5 * HOUR_MS, mc.ms(2020, 3, 15, 4)}
WARMUP_HOUR = mc.ms(2020, 1, 20, 7)
# Row layouts (count of keys, short SHA-256 of the keys in order) of an ETHUSDT V0 grid run
# and an ETHUSDT D run on the DOGEUSDT window, captured from the code before this change
# (2cd7fb8). Built on test_backtest_masked_checks.build_run: editing it moves these.
GOLDEN_GRID_LAYOUT = (59, "58a37bca160012b5")
GOLDEN_D_LAYOUT = (46, "02e99c3c257a23b1")


def layout(row):
    return len(row), hashlib.sha256("\n".join(row).encode()).hexdigest()[:16]


def mask_fields(row):
    return {key: row[key] for key in MASK_FIELDS & row.keys()}


def mask_counts(metrics):
    return metrics.masked_hours, metrics.days_skipped_for_masks, metrics.fills_after_masked_span


class StepTrace:
    """Every fill of a grid replay by the minute of its quote, and the order book after
    each minute's last quote, from ``PaperSimulator.step``."""

    def __init__(self):
        self.fills: Counter[int] = Counter()
        self.filled: defaultdict[int, list[str]] = defaultdict(list)
        self.books: dict[int, set[str]] = {}

    def __enter__(self):
        real = PaperSimulator.step

        def step(simulator, account, frame):
            report = real(simulator, account, frame)
            at = int(timestamp(frame.quote.observed_at).timestamp() * 1000)
            minute = at // MINUTE_MS * MINUTE_MS
            self.fills[minute] += len(report["fills"])
            self.filled[minute] += [str(fill["order_id"]) for fill in report["fills"]]
            self.books[minute] = set(account.orders)
            return report

        self._patch = patch.object(PaperSimulator, "step", step)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class MaskedRunTests(mc.RunDataset):
    def run_eth(self, masks, spec_path=None):
        return run_job(
            spec_path or self.spec_path,
            CONFIG,
            self.data,
            "ETHUSDT",
            "high_first",
            False,
            masks=masks,
        )

    def trend_eth(self, masks):
        return trend_job(self.spec_path, CONFIG, self.data, "ETHUSDT", "high_first", masks=masks)

    def test_fill_after_a_masked_span_is_flagged(self):
        masked_hour = MAR_2020 + 3 * HOUR_MS
        after = masked_hour + HOUR_MS  # the first replayed minute after the span
        with StepTrace() as trace:
            row = self.run_eth({"ETHUSDT": frozenset({masked_hour})})
        self.assertEqual([], row["accounting_problems"])
        self.assertGreater(trace.fills[after], 0, "the fixture fills right after the span")
        self.assertEqual(trace.fills[after], row["fills_after_masked_span"])
        # Rule 4: those orders stayed open across the span. Each was resting after the last
        # replayed minute before it.
        self.assertLessEqual(set(trace.filled[after]), trace.books[masked_hour - MINUTE_MS])
        # Two spans: only each span's first replayed minute counts, not the fills after it.
        first, second = MAR_2020 + 2 * HOUR_MS, MAR_2020 + 5 * HOUR_MS
        with StepTrace() as trace:
            row = self.run_eth({"ETHUSDT": frozenset({first, second})})
        flagged = trace.fills[first + HOUR_MS] + trace.fills[second + HOUR_MS]
        self.assertGreater(flagged, 0)
        self.assertEqual(flagged, row["fills_after_masked_span"])
        self.assertLess(flagged, sum(n for minute, n in trace.fills.items() if minute > first))

    def test_a_gap_no_masked_hour_explains_is_not_a_masked_span(self):
        # Hour 3 is masked; hour 6 is a gap too, left by feature warm-up (features.at None)
        # or by minutes missing without a mask. Only hour 3's span is flagged, though the
        # first minute after hour 6 fills as well.
        masked_hour, hole = MAR_2020 + 3 * HOUR_MS, MAR_2020 + 6 * HOUR_MS
        masks = {"ETHUSDT": frozenset({masked_hour})}
        prepared = prepare_run(
            self.spec_path, CONFIG, self.data, "ETHUSDT", "high_first", False, masks=masks
        )
        real_at = prepared.features.at

        class WarmingFeatures:
            def at(self, minute_ms):
                return None if hole <= minute_ms < hole + HOUR_MS else real_at(minute_ms)

        for gap in ("warm-up", "missing minutes"):
            with self.subTest(gap=gap):
                minutes = list(
                    load_minutes(self.data, prepared.manifest, "ETHUSDT", mask=masks["ETHUSDT"])
                )
                features = prepared.features
                if gap == "warm-up":
                    features = WarmingFeatures()
                else:
                    minutes = [k for k in minutes if not hole <= k.open_ms < hole + HOUR_MS]
                with StepTrace() as trace:
                    metrics, _ = replay(
                        prepared.config,
                        prepared.run,
                        minutes,
                        features,
                        window=WINDOW,
                        masked=masks["ETHUSDT"],
                    )
                self.assertEqual(int(gap == "warm-up") * 60, metrics.warmup_bars)
                self.assertGreater(trace.fills[hole + HOUR_MS], 0, "it fills after the gap")
                self.assertGreater(trace.fills[masked_hour + HOUR_MS], 0)
                self.assertEqual(
                    trace.fills[masked_hour + HOUR_MS], metrics.fills_after_masked_span
                )
                self.assertEqual(1, metrics.masked_hours)

    def test_unmasked_run_rows_gain_no_field(self):
        grid = self.run_eth(None)
        self.assertEqual(GOLDEN_GRID_LAYOUT, layout(grid))
        d = self.trend_eth(None)
        self.assertEqual(GOLDEN_D_LAYOUT, layout(d))
        # No mask in any form is reported: an empty map, a pair mapped to None, and a pair
        # with an empty mask (the repairing reader, nothing dropped) give the same rows.
        for masks in ({}, {"ETHUSDT": None}, {"ETHUSDT": frozenset()}):
            with self.subTest(masks=masks):
                self.assertEqual(grid, self.run_eth(masks))
                self.assertEqual(d, self.trend_eth(masks))
        # The proxy's and the basket's masks shape the features; they are not the pair's
        # and are not reported in its rows.
        others = {
            "BTCUSDT": frozenset({MAR_2020 + 2 * HOUR_MS}),
            "BNBUSDT": frozenset({WARMUP_HOUR}),
        }
        self.assertEqual({}, mask_fields(self.run_eth(others)))
        self.assertEqual({}, mask_fields(self.trend_eth(others)))
        # The replay itself: the window with no mask leaves the Metrics exactly as without.
        prepared = prepare_run(self.spec_path, CONFIG, self.data, "ETHUSDT", "high_first", False)

        def metrics(**window):
            minutes = load_minutes(self.data, prepared.manifest, "ETHUSDT")
            return replay(prepared.config, prepared.run, minutes, prepared.features, **window)[0]

        self.assertEqual(metrics(), metrics(window=WINDOW, masked=frozenset()))

    def test_masked_hours_and_skipped_days_are_counted(self):
        mask = frozenset(EVALUATION_HOURS | {WARMUP_HOUR})
        row = self.run_eth({"ETHUSDT": mask})
        self.assertEqual([], row["accounting_problems"])
        self.assertEqual(3, row["masked_hours"])  # the warm-up hour is outside the window
        # Rule 3: the daily check's hours run from the warm-up start, so its days are
        # 2020-03-01, 2020-03-15 and 2020-01-20, as that check counts them.
        self.assertEqual(3, row["days_skipped_for_masks"])
        record = cross_check_job(self.spec_path, self.data, "ETHUSDT", mask=mask)
        self.assertEqual(record["daily_days_skipped_for_masks"], row["days_skipped_for_masks"])
        # Each field is written only when non-zero. A masked hour after the last minute
        # flags no fill; a warm-up hour alone is no evaluation hour.
        late = self.run_eth({"ETHUSDT": frozenset({mc.ms(2020, 3, 20, 4)})})
        self.assertEqual({"masked_hours": 1, "days_skipped_for_masks": 1}, mask_fields(late))
        warm = self.run_eth({"ETHUSDT": frozenset({WARMUP_HOUR})})
        self.assertEqual({"days_skipped_for_masks": 1}, mask_fields(warm))
        # A spec with no daily history has no daily check, so no day is skipped.
        with tempfile.TemporaryDirectory() as temp:
            spec_path = Path(temp) / "no-daily.toml"
            text = self.spec_path.read_text()
            spec_path.write_text(text.replace('daily_warmup_start = "2020-01"\n', ""))
            self.assertNotIn("daily_warmup_start", spec_path.read_text())
            shutil.copy(
                self.spec_path.with_name("doge-window.manifest.json"),
                spec_path.with_name("no-daily.manifest.json"),
            )
            no_daily = self.run_eth({"ETHUSDT": mask}, spec_path)
        self.assertEqual(3, no_daily["masked_hours"])
        self.assertNotIn("days_skipped_for_masks", no_daily)

    def test_d_rows_report_masked_spans(self):
        # Through trend_job: D holds cash over this window (its daily closes are level, and
        # equal is not above), so it fills nothing, and its row carries the other two.
        mask = frozenset(EVALUATION_HOURS | {WARMUP_HOUR})
        row = self.trend_eth({"ETHUSDT": mask})
        self.assertEqual((0, 0, []), (row["buys"], row["sells"], row["accounting_problems"]))
        self.assertEqual({"masked_hours": 3, "days_skipped_for_masks": 3}, mask_fields(row))
        # D's replay: hold during day E, so D buys at its first quote; cash during E+1, so it
        # sells at the first quote after a span masked across midnight. Only the sell is
        # flagged; with the same gap unmasked, nothing is.
        minutes = [flat(E + i * MINUTE_MS, "1") for i in range(3)]
        minutes += [flat(E + DAY_MS + 2 * HOUR_MS + i * MINUTE_MS, "1") for i in range(3)]
        window = (E, E + 3 * DAY_MS)
        span = frozenset({E + 23 * HOUR_MS, E + DAY_MS + HOUR_MS})
        metrics, account = replay_trend(
            RUN, minutes, SWITCHING, always, window=window, masked=span, days_skipped_for_masks=2
        )
        self.assertEqual(
            [("2024-03-01T00:00:00+00:00", "buy"), ("2024-03-02T02:00:00+00:00", "sell")],
            [(at, fill.side) for at, fill in metrics.fills],
        )
        self.assertEqual((2, 2, 1), mask_counts(metrics))
        d_row = summarise_trend(RUN, metrics, account, [])
        expected = {"masked_hours": 2, "days_skipped_for_masks": 2, "fills_after_masked_span": 1}
        self.assertEqual(expected, mask_fields(d_row))
        elsewhere = frozenset({E + 2 * DAY_MS + 5 * HOUR_MS})  # in the window, not the gap
        metrics, account = replay_trend(
            RUN, minutes, SWITCHING, always, window=window, masked=elsewhere
        )
        self.assertEqual((1, 0, 0), mask_counts(metrics))
        unmasked, unmasked_account = replay_trend(RUN, minutes, SWITCHING, always)
        self.assertEqual({}, mask_fields(summarise_trend(RUN, unmasked, unmasked_account, [])))
        self.assertEqual(unmasked, replay_trend(RUN, minutes, SWITCHING, always, window=window)[0])

    def test_a_mask_needs_the_window(self):
        # masked_hours counts the mask inside the evaluation window, so a mask without a
        # window is refused rather than counted as zero.
        prepared = prepare_run(self.spec_path, CONFIG, self.data, "ETHUSDT", "high_first", False)
        span = frozenset({MAR_2020 + 3 * HOUR_MS})
        with self.assertRaises(ValueError):
            replay(prepared.config, prepared.run, [], prepared.features, masked=span)
        with self.assertRaises(ValueError):
            replay_trend(RUN, [], SWITCHING, always, masked=span)


class MaskedSpansTests(unittest.TestCase):
    def test_only_the_first_replayed_minute_after_a_masked_hour_is_flagged(self):
        h = [MAR_2020 + i * HOUR_MS for i in range(8)]
        spans = MaskedSpans(frozenset({h[2], h[5], APR_2020}), WINDOW)
        self.assertEqual(2, spans.hours)  # APR_2020 is the window's end, outside it
        replayed = [
            (h[1], False),  # the run's first replayed minute: nothing before it
            (h[1] + MINUTE_MS, False),
            (h[3], True),  # hour 2 is masked
            (h[3] + MINUTE_MS, False),  # the same hour: not the first after the span
            (h[4] + 30 * MINUTE_MS, False),  # the next hour, nothing masked between
            (h[5] + 10 * MINUTE_MS, False),  # a minute of masked hour 5 the caller kept
            (h[6], True),  # right after masked hour 5
            (h[7] + 59 * MINUTE_MS, False),
        ]
        self.assertEqual(replayed, [(at, spans.first_after(at)) for at, _ in replayed])

    def test_a_gap_with_no_masked_hour_is_not_a_span(self):
        spans = MaskedSpans(frozenset({MAR_2020 + 9 * HOUR_MS}), WINDOW)
        flags = [spans.first_after(MAR_2020 + i * HOUR_MS) for i in (0, 3, 8, 10, 30)]
        self.assertEqual([False, False, False, True, False], flags)
