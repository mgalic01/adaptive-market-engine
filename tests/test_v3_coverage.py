"""Coverage diagnostics use synthetic metadata, never price archives."""

import sys
from pathlib import Path

import pytest

from crypto_grid_bot.backtest.klines import month_bounds_ms

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def inventory():
    from fetch_v3_data import archive_path
    from v3_inventory import planned_requests

    return [
        {
            "kind": kind,
            "symbol": symbol,
            "month": month,
            "path": archive_path(kind, symbol, month),
            "status": "missing",
            "sha256": None,
        }
        for kind, symbol, month in planned_requests()
    ]


def enable(entries, kind, month, first_offset=0, masked=()):
    row = next(
        x for x in entries if x["kind"] == kind and x["month"] == month and x["symbol"] == "BTCUSDT"
    )
    start, end = month_bounds_ms(month)
    row.update(status="eligible", sha256="a" * 64)
    if kind != "funding":
        row.update(
            first_open_ms=start + first_offset,
            last_open_ms=end - 3_600_000,
            masked_hours=list(masked),
        )
    return row


def test_coverage_join_warmup_and_quarter_grid():
    from v3_inventory import coverage_diagnostics

    entries = inventory()
    enable(entries, "spot", "2018-06")
    for month in ("2020-01", "2020-02"):
        for kind in ("spot", "futures", "funding"):
            enable(entries, kind, month)
    summary = coverage_diagnostics(entries)
    coin = summary["coins"]["BTCUSDT"]
    assert coin["first_full_spot_month_candidate"] == "2018-06"
    assert coin["first_full_futures_month_candidate"] == "2020-01"
    assert coin["first_portfolio_month_candidate"] == "2020-01"
    assert coin["spot_history_calendar_days"] == 579
    assert coin["less_than_year_of_spot_history"] is False
    assert summary["first_test_quarter_candidate"] == "2021-07"
    assert summary["test_quarters_candidate"] == 14
    assert summary["coverage_review_required"] is True


def test_partial_listing_month_is_not_first_full_and_funding_can_delay_join():
    from v3_inventory import coverage_diagnostics

    entries = inventory()
    for month in ("2020-01", "2020-02", "2020-03"):
        enable(entries, "spot", month)
        enable(entries, "futures", month, first_offset=3600000 if month == "2020-01" else 0)
    enable(entries, "funding", "2020-01")
    enable(entries, "funding", "2020-03")
    coin = coverage_diagnostics(entries)["coins"]["BTCUSDT"]
    assert coin["first_full_futures_month_candidate"] == "2020-02"
    assert coin["first_portfolio_month_candidate"] == "2020-03"
    assert coin["less_than_year_of_spot_history"] is True


def test_exclusion_close_diagnostics_distinguish_futures_and_hold_prices():
    from v3_inventory import coverage_diagnostics

    entries = inventory()
    start, _ = month_bounds_ms("2020-03")
    first_fill = start - 23 * 3_600_000
    for kind in ("spot", "futures", "funding"):
        enable(entries, kind, "2020-02")
    enable(entries, "futures", "2020-02", masked=[first_fill])
    enable(entries, "spot", "2020-02", masked=range(first_fill, start, 3_600_000))
    # March is absent, so the previous last day's available hours decide close diagnostics.
    close = coverage_diagnostics(entries)["coins"]["BTCUSDT"]["excluded_months"][0]
    assert close["month"] == "2020-03"
    assert close["futures_close_ms"] == first_fill + 3_600_000
    assert close["hold_close_ms"] is None
    assert close["previous_month_eligible"] is True


def test_incomplete_or_duplicate_inventory_cannot_produce_coverage():
    from v3_inventory import coverage_diagnostics

    entries = inventory()
    with pytest.raises(ValueError, match="complete"):
        coverage_diagnostics(entries[:-1])
    with pytest.raises(ValueError, match="duplicate"):
        coverage_diagnostics([*entries, entries[0]])


@pytest.mark.parametrize("excluded", [False, True])
def test_first_full_month_requires_eligible_archive_with_both_calendar_boundaries(excluded):
    from v3_inventory import coverage_diagnostics

    entries = inventory()
    enable(entries, "spot", "2018-06")
    row = enable(entries, "futures", "2020-01", first_offset=3600000)
    if excluded:
        row.update(status="excluded", first_open_ms=month_bounds_ms("2020-01")[0])
    # February is absent; March ends early despite beginning on its first hour.
    row = enable(entries, "futures", "2020-03")
    row["last_open_ms"] -= 3600000
    enable(entries, "futures", "2020-04")
    coin = coverage_diagnostics(entries)["coins"]["BTCUSDT"]
    assert coin["first_full_futures_month_candidate"] == "2020-04"


def test_delayed_portfolio_join_requires_full_futures_month():
    from v3_inventory import coverage_diagnostics

    entries = inventory()
    for month in ("2020-01", "2020-02", "2020-03"):
        enable(entries, "spot", month)
        enable(entries, "futures", month, first_offset=3600000 if month == "2020-02" else 0)
    enable(entries, "funding", "2020-02")
    enable(entries, "funding", "2020-03")
    coin = coverage_diagnostics(entries)["coins"]["BTCUSDT"]
    assert coin["first_portfolio_month_candidate"] == "2020-03"
