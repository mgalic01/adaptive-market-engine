from decimal import Decimal

import pytest

from crypto_grid_bot.backtest.funding import FundingRecord
from crypto_grid_bot.backtest.klines import month_bounds_ms
from crypto_grid_bot.trend.data import funding_schedule


def records(interval=8):
    start, end = month_bounds_ms("2024-02")
    return [
        FundingRecord(t, interval, Decimal("0.0001"))
        for t in range(start, end, interval * 3_600_000)
    ]


@pytest.mark.parametrize("interval", [1, 2, 3, 4, 6, 8, 12, 24])
def test_all_spec_intervals(interval):
    result = funding_schedule(records(interval), "2024-02")
    assert result.eligible
    assert result.interval_hours == interval
    assert result.expected_slots == 29 * 24 // interval
    assert result.reasons == ()


@pytest.mark.parametrize(
    "offset,eligible", [(0, True), (47, True), (60000, True), (60001, False), (-1, False)]
)
def test_settlement_offset(offset, eligible):
    rows = records()
    rows[0] = FundingRecord(rows[0].calc_time_ms + offset, 8, rows[0].rate)
    assert funding_schedule(rows, "2024-02").eligible is eligible


@pytest.mark.parametrize("case", ["empty", "missing", "duplicate", "mixed", "nondivisor", "nan"])
def test_ineligible_month(case):
    rows = records()
    if case == "empty":
        rows = []
    elif case == "missing":
        rows.pop()
    elif case == "duplicate":
        rows[-1] = rows[0]
    elif case == "mixed":
        rows[-1] = FundingRecord(rows[-1].calc_time_ms, 4, rows[-1].rate)
    elif case == "nondivisor":
        rows = [FundingRecord(row.calc_time_ms, 5, row.rate) for row in rows]
    else:
        rows[-1] = FundingRecord(rows[-1].calc_time_ms, 8, Decimal("NaN"))
    result = funding_schedule(rows, "2024-02")
    assert not result.eligible
    assert result.reasons


def test_legacy_gate_does_not_change():
    row = FundingRecord(0, 3, Decimal("0.0001"))
    assert not row.valid
    assert funding_schedule(records(3), "2024-02").eligible


def test_reserved_month_rejected_before_inspection():
    with pytest.raises(ValueError):
        funding_schedule([], "2025-01")


def hourly_bars():
    from crypto_grid_bot.backtest.klines import Kline

    start, end = month_bounds_ms("2024-02")
    return [
        Kline(
            t,
            Decimal(10),
            Decimal(12),
            Decimal(9),
            Decimal(11),
            Decimal(1),
            Decimal(10),
            Decimal("0.5"),
        )
        for t in range(start, end, 3_600_000)
    ]


@pytest.mark.parametrize("missing,day_present", [(4, True), (5, False)])
def test_daily_completeness(missing, day_present):
    from crypto_grid_bot.trend.data import hourly_month

    bars = hourly_bars()
    result = hourly_month(bars[missing:], "2024-02")
    assert not result.excluded
    assert len(result.daily_bars) == (29 if day_present else 28)
    assert len(result.masked_hours) == missing
    if day_present:
        day = result.daily_bars[0]
        assert day.open_ms == bars[0].open_ms
        assert day.volume == Decimal(20)
        assert (day.open, day.high, day.low, day.close) == (
            Decimal(10),
            Decimal(12),
            Decimal(9),
            Decimal(11),
        )


@pytest.mark.parametrize("missing,excluded", [(118, False), (119, True)])
def test_month_seventeen_percent_boundary(missing, excluded):
    from crypto_grid_bot.trend.data import hourly_month

    result = hourly_month(hourly_bars()[missing:], "2024-02")
    assert result.excluded is excluded
    if excluded:
        assert result.daily_bars == ()


def test_repaired_hour_not_in_daily_extremes():
    from dataclasses import replace

    from crypto_grid_bot.trend.data import hourly_month

    bars = hourly_bars()
    bars[2] = replace(bars[2], high=Decimal(999))
    result = hourly_month(bars, "2024-02", frozenset({bars[2].open_ms}))
    assert result.daily_bars[0].high == Decimal(12)
    assert result.daily_bars[0].volume == Decimal(23)


def test_duplicate_hour_rejected():
    from crypto_grid_bot.trend.data import hourly_month

    bars = hourly_bars()
    with pytest.raises(ValueError, match="duplicate"):
        hourly_month([*bars, bars[0]], "2024-02")


def test_reader_repairs_are_always_masked():
    from crypto_grid_bot.backtest.klines import FileStats, RepairedRead
    from crypto_grid_bot.trend.data import repaired_month

    bars = hourly_bars()
    stats = FileStats(len(bars), len(bars), 0, 0, bars[0].open_ms, bars[-1].open_ms, ("ms",))
    read = RepairedRead(bars, stats, frozenset({bars[0].open_ms}), frozenset({bars[1].open_ms}), "")
    result = repaired_month(read, "2024-02")
    assert result.masked_hours == frozenset({bars[0].open_ms, bars[1].open_ms})
    assert result.daily_bars[0].volume == Decimal(22)


def test_mandatory_close_uses_last_day_at_one_or_next_unmasked_hour():
    from crypto_grid_bot.trend.data import mandatory_close_hour

    start, _ = month_bounds_ms("2024-03")
    first = start - 23 * 3_600_000  # February 29 at 01:00 UTC
    assert mandatory_close_hour("2024-03", frozenset({first, first + 3_600_000})) == first
    assert mandatory_close_hour("2024-03", frozenset({first + 3_600_000})) == first + 3_600_000


def test_mandatory_close_never_uses_midnight_or_excluded_month():
    from crypto_grid_bot.trend.data import mandatory_close_hour

    start, _ = month_bounds_ms("2024-03")
    assert mandatory_close_hour("2024-03", frozenset({start - 86_400_000, start})) is None


def test_mandatory_close_reserved_month_rejected():
    from crypto_grid_bot.trend.data import mandatory_close_hour

    with pytest.raises(ValueError):
        mandatory_close_hour("2025-01", frozenset())
