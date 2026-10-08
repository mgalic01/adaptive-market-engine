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
