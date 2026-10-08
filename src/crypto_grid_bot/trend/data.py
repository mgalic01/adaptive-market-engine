"""V3 data eligibility, independent of the legacy funding signal's cadence rules."""

from collections.abc import Sequence
from dataclasses import dataclass

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.backtest.window import development_month


@dataclass(frozen=True, slots=True)
class FundingSchedule:
    eligible: bool
    interval_hours: int | None
    expected_slots: int
    reasons: tuple[str, ...]


def funding_schedule(records: Sequence[FundingRecord], month: str) -> FundingSchedule:
    """Apply frozen V3 §2 to the entire month, retaining every bad record as evidence."""
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
