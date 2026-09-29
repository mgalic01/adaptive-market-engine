"""Flat-equity stretch search over a replay's hourly total-equity series.

Reads only ``results.json`` files a replay already wrote (the ``hourly_equity``
series: ``[hour open ms, strategy total equity, buy-and-hold value]``). No market
data and no re-run are involved.

This corrects two defects of the appendix script in
``docs/reviews/2026-09-27-claude-soft-drawdown-lockout.md``
(SHA-256 ``543e58c5...``):

1. **Length and the gate were sample counts, not time.** The old script used
   ``hours = j - i + 1``, the number of consecutive equal samples, and gated on
   ``hours >= 24``. ``replay.py`` appends to ``hourly_equity`` only when a kline
   opens a new hour, so absent hours leave no sample: a flat span of 60
   wall-clock hours recorded in 21 samples was reported as "none" — a false
   negative in what the docstring calls a counterexample search. The count also
   overstates the span by one hour (24 samples span 23 hours). Here the span is
   ``end_ms - start_ms`` and the gate is on that span.

2. **"never resumed" was right-censoring, not evidence.** The old flag
   ``resumed = j + 1 < len(he)`` is true exactly when the flat run ended because
   equity changed, and false exactly when it ran into the last sample of the
   series. So "never resumed" meant "the series ended while still flat", at most
   one stretch per result could ever qualify, and no resumption was observable
   for any of them. Here the outcome is a three-way label — ``CHANGED``,
   ``CENSORED``, or excluded — and a censored stretch reports its span as a
   lower bound.

What it still cannot show, by construction: constant *total* equity is not proof
of a flat account or of no trading, and the drawdown here is measured against
this series' own running peak of total equity, not against the engine's
reserve-adjusted ``risk_high`` on *active* equity. Those need the per-step
instrumented trace, not this script.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

HOUR_MS = 3_600_000
ZERO = Decimal(0)


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class Stretch:
    """One maximal run of equal consecutive hourly total-equity samples."""

    start_ms: int
    end_ms: int  # the last sample still equal to the first
    samples: int
    hours_present: int  # distinct hour buckets the samples fall in
    equity: Decimal
    peak: Decimal  # running peak of total equity at the stretch's first sample
    drawdown_pct: Decimal  # against that peak
    censored: bool  # True: the series ended while still flat; nothing observable after
    changed_at_ms: int | None  # first sample with a different equity, if any

    @property
    def span_hours(self) -> int:
        """Elapsed hours between the first and last sample of the stretch.

        Measured between the samples' *hour buckets*, not their raw timestamps: a
        sample stamped mid-hour (the first minutes of its hour absent) would otherwise
        shorten the span by a fraction of an hour, drop the stretch at a 24 h gate, and
        make ``missing_hours`` negative. ``samples`` is not the measure either: it is one
        larger for a gapless stretch and smaller than the span wherever hours are missing.
        """
        return self.end_ms // HOUR_MS - self.start_ms // HOUR_MS

    @property
    def missing_hours(self) -> int:
        """Hours inside the stretch with no sample, so with equity unobserved.

        Counted over distinct hour buckets, not samples: ``replay.py`` stamps each
        hourly sample with the *minute* bar that opened the hour, which is the hour
        boundary only when the minute data for that hour is complete.
        """
        return self.span_hours + 1 - self.hours_present

    def describe(self) -> str:
        span = f"{self.span_hours} h ({self.span_hours / 24:.1f} d)"
        gaps = f", {self.missing_hours} h missing" if self.missing_hours else ""
        if self.censored:
            outcome = (
                f"CENSORED at series end {utc(self.end_ms)}: "
                "flat when the data ran out, no later equity observable; span is a lower bound"
            )
        elif self.changed_at_ms is not None:
            waited = self.changed_at_ms // HOUR_MS - self.start_ms // HOUR_MS
            outcome = f"CHANGED at {utc(self.changed_at_ms)} after {waited} h"
        else:
            raise ValueError("a stretch that is not censored must record when equity changed")
        return f"{utc(self.start_ms)} {span}{gaps} dd={self.drawdown_pct:.2f}% -> {outcome}"


def stretches(series: list[tuple[int, Decimal]]) -> list[Stretch]:
    """Every maximal flat run in a series of (hour open ms, total equity) samples.

    The series must be ordered by timestamp. No gate is applied here; filtering is
    the caller's, so that a caller can also see the stretches a gate drops.
    """
    peak = ZERO
    peaks: list[Decimal] = []
    for _, equity in series:
        peak = max(peak, equity)
        peaks.append(peak)
    found: list[Stretch] = []
    i = 0
    while i < len(series):
        j = i
        while j + 1 < len(series) and series[j + 1][1] == series[i][1]:
            j += 1
        # The run ended either because equity changed at j + 1, or because the
        # series ended. Only the first is an observation; the second is censoring.
        censored = j + 1 >= len(series)
        start_peak = peaks[i]
        found.append(
            Stretch(
                start_ms=series[i][0],
                end_ms=series[j][0],
                samples=j - i + 1,
                hours_present=len({ms // HOUR_MS for ms, _ in series[i : j + 1]}),
                equity=series[i][1],
                peak=start_peak,
                drawdown_pct=(
                    (start_peak - series[i][1]) / start_peak * 100 if start_peak > ZERO else ZERO
                ),
                censored=censored,
                changed_at_ms=None if censored else series[j + 1][0],
            )
        )
        i = j + 1
    return found


def select(all_stretches: list[Stretch], *, min_hours: int, threshold: Decimal) -> list[Stretch]:
    """Stretches spanning at least ``min_hours`` of wall clock at ``threshold``% or more."""
    return [s for s in all_stretches if s.span_hours >= min_hours and s.drawdown_pct >= threshold]


def series_of(result: dict[str, Any]) -> list[tuple[int, Decimal]]:
    return [(int(ms), Decimal(total)) for ms, total, _ in result["hourly_equity"]]


def result_name(result: dict[str, Any]) -> str:
    if result.get("benchmark"):  # a benchmark row, e.g. variant D: not a grid run
        kind = f"variant {result['variant']}"
    else:
        kind = "gated" if str(result["strategy"]).startswith("gated") else "ungated"
    return f"{result['symbol']} {result['path_mode']} {kind}"


def analyse(
    document: dict[str, Any], *, min_hours: int, threshold: Decimal
) -> list[tuple[str, list[Stretch], int]]:
    """Per result: its name, its selected stretches, and the series' last sample ms."""
    out: list[tuple[str, list[Stretch], int]] = []
    for result in document["results"]:
        series = series_of(result)
        if not series:
            out.append((result_name(result), [], 0))
            continue
        end_ms = series[-1][0]
        out.append(
            (
                result_name(result),
                select(stretches(series), min_hours=min_hours, threshold=threshold),
                end_ms,
            )
        )
    return out


def report(paths: list[Path], *, min_hours: int, threshold: Decimal) -> list[str]:
    lines: list[str] = []
    for path in paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        fees = document["fees"]
        lines.append(f"== {document['dataset']} {fees['maker']}/{fees['taker']} ({path.name})")
        for name, found, end_ms in analyse(document, min_hours=min_hours, threshold=threshold):
            if not found:
                lines.append(f"  {name}: none")
                continue
            censored = sum(1 for s in found if s.censored)
            lines.append(
                f"  {name}: {len(found)} stretch(es), {censored} censored, "
                f"series ends {utc(end_ms) if end_ms else 'n/a'}"
            )
            for stretch in found:
                lines.append(f"    {stretch.describe()}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threshold",
        type=Decimal,
        default=Decimal(7),
        help="minimum total-equity drawdown in percent, against the series' running peak",
    )
    parser.add_argument(
        "--min-hours",
        type=int,
        default=24,
        help="minimum elapsed hours between the first and last sample of a flat stretch",
    )
    parser.add_argument("results", type=Path, nargs="+", help="results.json files")
    args = parser.parse_args(argv)
    for line in report(args.results, min_hours=args.min_hours, threshold=args.threshold):
        print(line)
    return 0


__all__ = ["Stretch", "analyse", "report", "select", "stretches"]

if __name__ == "__main__":
    raise SystemExit(main())
