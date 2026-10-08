"""V3 data eligibility, independent of the legacy funding signal's cadence rules."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import Kline, RepairedRead, month_bounds_ms
from crypto_grid_bot.backtest.window import development_month


@dataclass(frozen=True, slots=True)
class FundingSchedule:
    eligible: bool
    interval_hours: int | None
    expected_slots: int
    reasons: tuple[str, ...]


def funding_schedule(records: Sequence[FundingRecord], month: str) -> FundingSchedule:
    """Apply frozen V3 Ã‚Â§2 to the entire month, retaining every bad record as evidence."""
    development_month(month)
    start, end = month_bounds_ms(month)
    if not records:
        return FundingSchedule(False, None, 0, ("missing funding records",))
    interval = records[0].interval_hours
    if type(interval) is not int or interval <= 0 or 24 % interval:
        return FundingSchedule(False, None, 0, ("interval must divide 24 hours",))
    step = interval * 3_600_000
    expected = (end - start) // step
    slots: set[int] = set()
    reasons: set[str] = set()
    for record in records:
        if type(record.interval_hours) is not int or record.interval_hours != interval:
            reasons.add("interval changes within month")
        rate = record.rate
        exponent = rate.as_tuple().exponent
        if not rate.is_finite() or not isinstance(exponent, int) or not -18 <= exponent <= 18:
            reasons.add("invalid funding rate")
        stamp = record.calc_time_ms
        if type(stamp) is not int or not start <= stamp < end:
            reasons.add("record outside month")
            continue
        slot, offset = divmod(stamp - start, step)
        if offset > 60_000:
            reasons.add("record off scheduled slot")
            continue
        if slot in slots:
            reasons.add("duplicate scheduled slot")
        slots.add(slot)
    if len(slots) != expected:
        reasons.add("missing scheduled slot")
    return FundingSchedule(not reasons, interval, expected, tuple(sorted(reasons)))


@dataclass(frozen=True, slots=True)
class HourlyMonth:
    excluded: bool
    masked_hours: frozenset[int]
    daily_bars: tuple[Kline, ...]


def hourly_month(
    bars: Sequence[Kline], month: str, masked: frozenset[int] = frozenset()
) -> HourlyMonth:
    """Aggregate trusted 1h rows; caller supplies the reader's repair and mask union.

    Missing hours are inferred. Returned daily timestamps are UTC midnight even
    when the first usable hour is later. Excluded months produce no daily signals.
    """
    development_month(month)
    start, end = month_bounds_ms(month)
    hour = 3_600_000
    expected = frozenset(range(start, end, hour))
    if not masked <= expected:
        raise ValueError("mask must contain aligned hours in this month")
    available: dict[int, Kline] = {}
    for bar in bars:
        if bar.open_ms not in expected:
            raise ValueError("bar outside month or not aligned to an hour")
        if bar.open_ms in available:
            raise ValueError("duplicate hourly bar")
        available[bar.open_ms] = bar
    missing = expected - available.keys()
    masks = frozenset(masked | missing)
    excluded = len(masks) * 100 > len(expected) * 17
    if excluded:
        return HourlyMonth(True, masks, ())
    daily: list[Kline] = []
    with localcontext() as context:
        context.prec = 60
        for day in range(start, end, 24 * hour):
            rows = [available[t] for t in range(day, day + 24 * hour, hour) if t not in masks]
            if len(rows) < 20:
                continue
            daily.append(
                Kline(
                    day,
                    rows[0].open,
                    max(row.high for row in rows),
                    min(row.low for row in rows),
                    rows[-1].close,
                    sum((row.volume for row in rows), Decimal(0)),
                    sum((row.quote_volume for row in rows), Decimal(0)),
                    sum((row.taker_buy_base for row in rows), Decimal(0)),
                )
            )
    return HourlyMonth(False, masks, tuple(daily))


def repaired_month(read: RepairedRead, month: str) -> HourlyMonth:
    """Bridge from the existing repairing reader without forgetting repaired hours."""
    start, end = month_bounds_ms(month)
    # The repairing reader also reports bad rows outside the archive's month.
    # Their hours do not belong in this month's mask or its 17% denominator.
    masks = frozenset(t for t in read.repaired | read.masked_hours if start <= t < end)
    return hourly_month(read.bars, month, masks)


def mandatory_close_hour(excluded_month: str, unmasked_hours: frozenset[int]) -> int | None:
    """Earliest permitted pre-exclusion fill, or None (the run would be invalid).

    These are manifest eligibility facts, not a prediction of live feed availability.
    The caller supplies unmasked futures execution hours, not spot signal hours.
    """
    development_month(excluded_month)
    start, _ = month_bounds_ms(excluded_month)
    hour = 3_600_000
    for stamp in range(start - 23 * hour, start, hour):
        if stamp in unmasked_hours:
            return stamp
    return None
