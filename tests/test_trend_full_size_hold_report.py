from dataclasses import replace
from decimal import Decimal as D

import pytest

from crypto_grid_bot.backtest.klines import Kline, month_bounds_ms
from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.full_size_hold import replay_full_size_hold

START = month_bounds_ms("2024-10")[0]
HOUR = 3600000


def result(available=True):
    limits = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    rows = [Kline(START + HOUR, *([D(100)] * 7))] if available else []
    return replay_full_size_hold(
        {"BTCUSDT": rows}, {"BTCUSDT": "2023-01"}, {"BTCUSDT": limits}, START, START + 24 * HOUR
    )


def test_completed_summary_recomputes_drawdown_and_retains_attempts():
    from crypto_grid_bot.trend.full_size_hold_report import build_full_size_hold_report

    account = result()
    report = build_full_size_hold_report(account)
    assert report.reason is None
    assert report.max_drawdown == account.max_drawdown > 0
    assert report.attempt_times == account.purchase_times
    assert report.fees == sum(f.fee for f in account.account.fills)
    assert report.cash == account.account.cash
    assert report.net_pnl == account.samples[-1][1] - 10000


def test_unavailable_summary_does_not_publish_completed_performance():
    from crypto_grid_bot.trend.full_size_hold_report import build_full_size_hold_report

    report = build_full_size_hold_report(result(False))
    assert report.reason == "unavailable_first_purchase"
    assert report.max_drawdown is None and report.net_pnl is None
    assert report.missing_symbols == ("BTCUSDT",)


@pytest.mark.parametrize("damage", ["cash", "sample", "failure", "boundary"])
def test_corrupted_or_partial_diagnostic_is_rejected(damage):
    from crypto_grid_bot.trend.full_size_hold_report import build_full_size_hold_report

    account = result()
    if damage == "cash":
        account.account.cash += 1
    elif damage == "sample":
        account.samples[0] = (START + HOUR, D(9999))
    elif damage == "failure":
        account.reason = "engine_failure"
    else:
        account = replace(account, end_ms_exclusive=START + 48 * HOUR)
    with pytest.raises(ValueError):
        build_full_size_hold_report(account)
