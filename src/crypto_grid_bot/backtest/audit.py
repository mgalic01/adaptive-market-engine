"""Data-audit functions for the development archives (2017-08 to 2024-12 only).

Bob's task runs and Claude's reviews wrote these checks from scratch each time (PRs
#49, #59, #60, #65, #66). Here they are once, tested on synthetic data where the right
answer is known, so a task calls them and a review reruns them:

* hour statuses against the hours that should exist, not the hours found (#60);
* outage events across pairs, with the number of pairs listed at the time (#66);
* which fields differ when two bars mismatch (#60, #66);
* close-time anomaly classes, and the narrow and refined repair rules (#59, #65).

Months after ``DEVELOPMENT_END`` are refused: the reserved evaluation window is only
opened on the owner's explicit go, never by an audit.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from crypto_grid_bot.backtest.klines import (
    INTERVAL_MS,
    Kline,
    aggregate,
    month_bounds_ms,
    parse_rows,
)
from crypto_grid_bot.backtest.replay import compare_bars
from crypto_grid_bot.market_data.parsing import DataError

HOUR_MS = INTERVAL_MS["1h"]
DEVELOPMENT_END = "2024-12"
PRESENT_BOTH = "present_both"
ABSENT_MINUTES = "absent_minutes"
ABSENT_HOURLY = "absent_hourly"
ABSENT_BOTH = "absent_both"
PRICE_FIELDS = ("open", "high", "low", "close")
Rule = Literal["narrow", "refined"]


def development_month(month: str) -> str:
    """``month`` if it is inside the development window; DataError otherwise."""
    month_bounds_ms(month)  # validates the YYYY-MM form
    if month > DEVELOPMENT_END:
        raise DataError(f"{month} is in the reserved window; audits stop at {DEVELOPMENT_END}")
    return month


def expected_hours(first_hour_ms: int, month: str) -> range:
    """Every hour of ``month`` from the pair's first listed hour on (end exclusive)."""
    start, end = month_bounds_ms(development_month(month))
    return range(max(first_hour_ms // HOUR_MS * HOUR_MS, start), end, HOUR_MS)


def hour_statuses(
    minute_hours: Iterable[int], official_hours: Iterable[int], expected: Iterable[int]
) -> dict[int, str]:
    """Status of each expected hour: whether it has minutes, an official 1h bar, both
    or neither. An hour with any 1m bar counts as having minutes."""
    minutes = {h // HOUR_MS * HOUR_MS for h in minute_hours}
    official = set(official_hours)
    statuses = {}
    for hour in expected:
        has_minutes, has_official = hour in minutes, hour in official
        if has_minutes and has_official:
            statuses[hour] = PRESENT_BOTH
        elif has_official:
            statuses[hour] = ABSENT_MINUTES
        elif has_minutes:
            statuses[hour] = ABSENT_HOURLY
        else:
            statuses[hour] = ABSENT_BOTH
    return statuses


@dataclass(frozen=True, slots=True)
class Event:
    start_ms: int
    end_ms: int  # exclusive: the hour after the last affected hour
    pairs: tuple[str, ...]
    listed: int  # pairs listed at the start hour
    kind: str  # "all_pairs", "all_listed_few" or "pair_specific"

    @property
    def hours(self) -> int:
        return (self.end_ms - self.start_ms) // HOUR_MS


def outage_events(
    absent: Mapping[int, set[str]], listed: Mapping[int, set[str]], min_listed: int = 5
) -> list[Event]:
    """Merge consecutive affected hours into events.

    ``absent`` maps an hour to the pairs missing it; ``listed`` maps an hour to the
    pairs listed then. An event is "all_pairs" when every listed pair is affected in
    every hour and at least ``min_listed`` pairs are listed; "all_listed_few" when
    every listed pair is affected but fewer are listed; otherwise "pair_specific".
    """
    events: list[Event] = []
    run: list[int] = []

    def close_run() -> None:
        if not run:
            return
        pairs = tuple(sorted(set().union(*(absent[h] for h in run))))
        everyone = all(absent[h] >= listed.get(h, set()) for h in run)
        count = len(listed.get(run[0], set()))
        if everyone and count >= min_listed:
            kind = "all_pairs"
        elif everyone:
            kind = "all_listed_few"
        else:
            kind = "pair_specific"
        events.append(Event(run[0], run[-1] + HOUR_MS, pairs, count, kind))

    for hour in sorted(h for h, pairs in absent.items() if pairs):
        if run and hour != run[-1] + HOUR_MS:
            close_run()
            run = []
        run.append(hour)
    close_run()
    return events


def differing_fields(
    ours: Kline, theirs: Kline, tolerance: Decimal | None = None
) -> tuple[str, ...]:
    """The fields that make ``compare_bars`` report a mismatch; empty otherwise.

    Volume is listed only when it alone would fail the tolerance, so a price mismatch
    with drifting volume reads as the price field, as in PR #66's table.
    """
    if compare_bars(ours, theirs, tolerance) != "mismatch":
        return ()
    prices = tuple(f for f in PRICE_FIELDS if getattr(ours, f) != getattr(theirs, f))
    volume_ok = compare_bars(_with_prices_of(ours, theirs), theirs, tolerance) != "mismatch"
    return prices if volume_ok else (*prices, "volume")


def _with_prices_of(bar: Kline, reference: Kline) -> Kline:
    return Kline(
        bar.open_ms,
        reference.open,
        reference.high,
        reference.low,
        reference.close,
        bar.volume,
        bar.quote_volume,
        bar.taker_buy_base,
    )


def close_class(open_ms: int, close_ms: int, step: int) -> str:
    """'ok', 'unaligned_open', 'past_boundary', 'truncated' or 'other' (PR #59's classes,
    with the unaligned open it missed tested first)."""
    if open_ms % step:
        return "unaligned_open"
    if close_ms == open_ms + step - 1:
        return "ok"
    if close_ms >= open_ms + step:
        return "past_boundary"
    if open_ms <= close_ms:
        return "truncated"
    return "other"


def fix_closes(rows: Sequence[Sequence[str]], interval: str, rule: Rule) -> tuple[str, list[int]]:
    """CSV text with off-boundary closes rewritten under ``rule``, and the fixed opens.

    Both rules rewrite close to ``open + step - 1`` and change no price or volume.
    "narrow" (PR #59): only the last row of the file or the last row before a gap.
    "refined" (PR #65): an aligned open, and the next row opens at ``open + step`` or
    later (or none follows).
    """
    step = INTERVAL_MS[interval]
    out: list[list[str]] = []
    fixed: list[int] = []
    for i, raw in enumerate(rows):
        row = list(raw)
        open_ms, close_ms = int(row[0]), int(row[6])
        following = int(rows[i + 1][0]) if i + 1 < len(rows) else None
        if close_ms != open_ms + step - 1:
            if rule == "narrow":
                accepted = following is None or following > open_ms + step
            else:
                accepted = open_ms % step == 0 and (
                    following is None or following >= open_ms + step
                )
            if accepted:
                row[6] = str(open_ms + step - 1)
                fixed.append(open_ms)
        out.append(row)
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(out)
    return buffer.getvalue(), fixed


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    usable: bool
    reason: str  # "" when usable
    fixed_hours: tuple[int, ...]


def rule_outcome(
    minute_rows: Sequence[Sequence[str]],
    hour_rows: Sequence[Sequence[str]],
    month: str,
    rule: Rule,
) -> RuleOutcome:
    """Whether a pair-month is usable under ``rule``: both fixed texts parse and, for
    "refined", every hour holding a fixed row matches strictly (condition (c))."""
    development_month(month)
    minute_text, minute_fixed = fix_closes(minute_rows, "1m", rule)
    hour_text, hour_fixed = fix_closes(hour_rows, "1h", rule)
    hours = tuple(sorted({o // HOUR_MS * HOUR_MS for o in minute_fixed + hour_fixed}))
    try:
        minutes, _ = parse_rows(minute_text, "1m", month)
        official, _ = parse_rows(hour_text, "1h", month)
    except DataError as exc:
        return RuleOutcome(False, f"parse: {exc}", hours)
    if rule == "narrow":
        return RuleOutcome(True, "", hours)
    ours = {k.open_ms: k for k in aggregate(minutes)}
    theirs = {k.open_ms: k for k in official}
    for hour in hours:
        if hour not in ours or hour not in theirs:
            return RuleOutcome(False, f"hour {hour} missing from one archive", hours)
        fields = differing_fields(ours[hour], theirs[hour], Decimal(0))
        if fields:
            return RuleOutcome(False, f"hour {hour} differs on {'+'.join(fields)}", hours)
    return RuleOutcome(True, "", hours)
