from decimal import Decimal as D

import pytest

from crypto_grid_bot.trend.filters import OrderFilters
from crypto_grid_bot.trend.spot_benchmark import SpotRunner

T, HOUR = 1727740800000, 3600000


def account(cost=1, reason="completed"):
    filters = OrderFilters(*map(D, ("1", "100000", "1", "5", "1", "100000", "1", "1")))
    runner = SpotRunner({"BTCUSDT": filters}, cost_multiple=cost)
    for i in range(48):
        price = D(100 if i < 24 else 101)
        runner.step(
            T + i * HOUR, {"BTCUSDT": (price, price, price)}, {"BTCUSDT": D(".1")} if i == 0 else {}
        )
    runner.finish({"BTCUSDT": D(101)}, reason=reason)
    return runner


def test_spot_summary_preserves_costs_and_completed_metrics():
    from crypto_grid_bot.trend.spot_report import build_spot_report

    base, stressed = build_spot_report(account()), build_spot_report(account(2))
    assert base.net_pnl == D("8.4995")
    assert stressed.net_pnl < base.net_pnl
    assert base.fees == D("1.0005")
    assert base.traded_notional == D("1000.5")
    assert base.sharpe is not None and base.cagr is not None
    assert base.interval is None  # fewer than 60 returns
    assert base.monthly.months[0].month == "2024-10"
    assert base.worst_drawdown is not None


def test_known_invalid_spot_retains_partial_evidence_not_completed_metrics():
    from crypto_grid_bot.trend.spot_report import build_spot_report

    report = build_spot_report(account(reason="unavailable_exclusion_close"))
    assert report.reason == "unavailable_exclusion_close"
    assert report.sharpe is report.cagr is report.monthly is report.interval is None
    assert report.samples and report.fees > 0


@pytest.mark.parametrize("damage", ["cash", "sample", "engine", "audit"])
def test_untrusted_or_failed_spot_evidence_aborts_report(damage):
    from crypto_grid_bot.trend.spot_report import build_spot_report

    runner = account()
    if damage == "cash":
        runner.account.cash += 1
    elif damage == "sample":
        runner.samples[1] = (runner.samples[1][0], D(20000))
    elif damage == "engine":
        runner.stopped = "engine_failure"
    else:
        runner.audits.clear()
    with pytest.raises(ValueError):
        build_spot_report(runner)
