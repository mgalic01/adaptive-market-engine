"""Hour masks and the 17% rule, month by month (spec v1 section 5, rules 1, 2, 3 and 5).

One ``MonthMask`` describes one symbol-month: which hours should exist (the month's hours
minus the symbol's documented exclusions, listing hours included), which of them are masked
and why, and whether the 17% rule excludes the month. The masks are pure functions of the
repairing reader's ``RepairedRead``s (``klines.parse_rows_repaired``), built one symbol-month
at a time so that only one month of minutes is ever held. A masked hour is absent: it is the
caller's to drop from every consumer.

``expected_hours``, ``hour_statuses`` and ``differing_fields`` live here because the masks
need them and ``audit`` imports this module (and ``replay``), never the other way round;
``audit`` re-exports them. This module must not import ``audit``, and ``replay`` must not
import this module.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction

from crypto_grid_bot.backtest.dataset import BasketExclusion
from crypto_grid_bot.backtest.klines import (
    INTERVAL_MS,
    Kline,
    RepairedRead,
    aggregate,
    month_bounds_ms,
)
from crypto_grid_bot.backtest.replay import VOLUME_DRIFT_TOLERANCE, compare_bars
from crypto_grid_bot.backtest.window import development_month

HOUR_MS = INTERVAL_MS["1h"]
MINUTE_MS = INTERVAL_MS["1m"]
DAY_MS = INTERVAL_MS["1d"]
PRESENT_BOTH = "present_both"
ABSENT_MINUTES = "absent_minutes"
ABSENT_HOURLY = "absent_hourly"
ABSENT_BOTH = "absent_both"
PRICE_FIELDS = ("open", "high", "low", "close")

# More than this share of a month's expected hours masked as real defects excludes the month.
SEVENTEEN = Fraction(17, 100)

UNTRUSTED_ROW = "untrusted row"
NO_HOURLY_BAR = "no hourly bar"
NO_MINUTE_BARS = "no minute bars"
NO_BARS = "absent from both archives"
EXTRA_HOURLY_BAR = "extra hourly bar"
INCOMPLETE_HOUR = "incomplete hour"
EXTRA_MINUTE_BARS = "extra minute bars"
OPEN_ONLY = "open-only difference"
UNCHECKED_REPAIR = "repaired hour with no minutes to check it"


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


@dataclass(frozen=True, slots=True)
class MonthMask:
    """The mask of one symbol-month; every hour is an ``int`` ms open.

    ``expected`` is the month's hours minus the documented exclusions. ``masked`` is a subset
    of it, and ``reasons`` says why each masked hour is (a readout, not a decision).
    ``defects`` are the masked hours other than ``open_only``, found when the mask was built:
    the 17% rule masks the whole month without changing them, so an excluded month still
    reports the share that excluded it. ``repaired`` are the expected hours that hold a
    repaired row in either archive. ``open_only`` is empty for an hourly-only month.
    """

    month: str
    expected: frozenset[int]
    masked: frozenset[int]
    reasons: dict[int, str]
    defects: frozenset[int]
    repaired: frozenset[int]
    open_only: frozenset[int]
    excluded: bool


def _hour_of(open_ms: int) -> int:
    return open_ms // HOUR_MS * HOUR_MS


def _expected(month: str, exclusions: Sequence[BasketExclusion]) -> frozenset[int]:
    """The month's hours outside every exclusion range ``[start_ms, end_ms)``."""
    hours = expected_hours(0, month)
    near = [e for e in exclusions if e.start_ms < hours.stop and hours.start < e.end_ms]
    return frozenset(h for h in hours if not any(e.start_ms <= h < e.end_ms for e in near))


def _minute_opens(hour: int) -> list[int]:
    """The 60 minute opens an hour must hold, once each."""
    return list(range(hour, hour + HOUR_MS, MINUTE_MS))


def _by_hour(bars: Iterable[Kline]) -> dict[int, list[Kline]]:
    grouped: dict[int, list[Kline]] = defaultdict(list)
    for bar in bars:
        grouped[_hour_of(bar.open_ms)].append(bar)
    return grouped


def _finish(
    month: str,
    expected: frozenset[int],
    reasons: dict[int, str],
    open_only: frozenset[int],
    repaired: frozenset[int],
) -> MonthMask:
    masked = frozenset(reasons)
    return MonthMask(
        month, expected, masked, reasons, masked - open_only, repaired, open_only, False
    )


_ABSENCE_REASONS = {
    ABSENT_BOTH: NO_BARS,
    ABSENT_MINUTES: NO_MINUTE_BARS,
    ABSENT_HOURLY: NO_HOURLY_BAR,
}


def traded_month_mask(
    minutes: RepairedRead,
    hourly: RepairedRead,
    month: str,
    exclusions: Sequence[BasketExclusion],
) -> MonthMask:
    """The mask of a traded pair's evaluation month (spec v1 section 5, rules 1 and 2).

    ``exclusions`` are the symbol's own documented ranges. An expected hour enters only if:

    * neither read reports an untrusted row in it (masked first: the reader keeps one copy of
      a duplicated or out-of-order row, so the hour's bars look right);
    * exactly one 1h bar exists, and exactly one 1m bar sits at each of its 60 minute opens
      and none elsewhere in it;
    * and the aggregated minutes match the 1h bar under ``drift-tolerance-v1``, or exactly
      (``Decimal(0)``, prices and volume) when either archive repaired a row in that hour.

    Every other expected hour is masked. One whose bars are complete and whose only
    differing field is ``open`` is ``open_only``, the convention class that the 17% rule
    does not count. Masked hours outside the expected set (a row outside the month, an
    excluded hour) never count.
    """
    expected = _expected(month, exclusions)
    untrusted = minutes.masked_hours | hourly.masked_hours
    held = {_hour_of(o) for o in minutes.repaired | hourly.repaired}
    minute_bars = _by_hour(sorted(minutes.bars, key=lambda bar: bar.open_ms))
    official = _by_hour(hourly.bars)
    statuses = hour_statuses(
        (bar.open_ms for bar in minutes.bars), (bar.open_ms for bar in hourly.bars), expected
    )
    reasons: dict[int, str] = {}
    open_only: set[int] = set()
    for hour in sorted(expected):
        if hour in untrusted:
            reasons[hour] = UNTRUSTED_ROW
        elif statuses[hour] != PRESENT_BOTH:
            reasons[hour] = _ABSENCE_REASONS[statuses[hour]]
        elif len(official[hour]) != 1:
            reasons[hour] = EXTRA_HOURLY_BAR
        elif [bar.open_ms for bar in minute_bars[hour]] != _minute_opens(hour):
            reasons[hour] = INCOMPLETE_HOUR if len(minute_bars[hour]) < 60 else EXTRA_MINUTE_BARS
        else:
            tolerance = Decimal(0) if hour in held else VOLUME_DRIFT_TOLERANCE
            fields = differing_fields(
                next(aggregate(minute_bars[hour])), official[hour][0], tolerance
            )
            if fields == ("open",):
                reasons[hour] = OPEN_ONLY
                open_only.add(hour)
            elif fields:
                reasons[hour] = f"mismatch on {'+'.join(fields)}"
    return _finish(month, expected, reasons, frozenset(open_only), frozenset(held & expected))


def hourly_only_month_mask(
    hourly: RepairedRead, month: str, exclusions: Sequence[BasketExclusion]
) -> MonthMask:
    """The mask of a month that has only a 1h archive (spec v1 section 5, rules 1 and 5).

    That covers an untraded basket symbol, an untraded proxy, and a traded pair's hourly
    warm-up months. An expected hour enters only if the read reports no untrusted row in it,
    exactly one 1h bar exists, and that bar is not a repaired row: with no minutes to check
    it against, a repaired hour is masked. ``open_only`` is always empty.
    """
    expected = _expected(month, exclusions)
    repaired = frozenset({_hour_of(o) for o in hourly.repaired} & expected)
    official = _by_hour(hourly.bars)
    reasons: dict[int, str] = {}
    for hour in sorted(expected):
        count = len(official.get(hour, ()))
        if hour in hourly.masked_hours:
            reasons[hour] = UNTRUSTED_ROW
        elif count == 0:
            reasons[hour] = NO_HOURLY_BAR
        elif count > 1:
            reasons[hour] = EXTRA_HOURLY_BAR
        elif hour in repaired:
            reasons[hour] = UNCHECKED_REPAIR
    return _finish(month, expected, reasons, frozenset(), repaired)


def real_defect_share(month: MonthMask) -> Fraction | None:
    """Real defects over expected hours, unchanged by an exclusion; None with no expected hour.

    A month wholly inside documented exclusions (SOLUSDT before its listing, DOGEUSDT 2020-02)
    has no expected hour, counts nothing toward the 17% rule and is never excluded.
    """
    return Fraction(len(month.defects), len(month.expected)) if month.expected else None


def apply_seventeen_percent(month: MonthMask) -> MonthMask:
    """The month, excluded (every expected hour masked) if real defects exceed 17%.

    Exactly 17% keeps it. ``defects``, ``open_only``, ``repaired`` and ``reasons`` are copied
    unchanged, so the excluded month still reports why; ``reasons`` covers only the hours that
    were masked before the rule, and ``excluded`` says the rest of the month is masked too.
    """
    share = real_defect_share(month)
    if share is None or share <= SEVENTEEN:
        return month
    return replace(month, masked=month.expected, reasons=dict(month.reasons), excluded=True)


def masked_days(masked: Iterable[int]) -> frozenset[int]:
    """The UTC day opens that contain a masked hour (rule 3: P3 skips these days)."""
    return frozenset(hour // DAY_MS * DAY_MS for hour in masked)
